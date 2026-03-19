"""Tools for news aggregator agents."""
import os
import re
import json
import time
import logging
import feedparser
import trafilatura
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List

logger = logging.getLogger(__name__)

from langchain_core.tools import tool

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

OUTPUT_DIR = os.environ.get("REPORTS_DIR", "/app/reports")


def make_fetch_news_tool(
    feeds: List[str],
    tool_name: str = "fetch_news",
    article_registry: dict | None = None,
    total_counter=None,
):
    """
    Return a LangChain @tool that fetches articles from the given RSS feeds.

    Args:
        feeds: List of RSS feed URLs to poll.
        tool_name: Name to give the tool (must be unique per agent).
        article_registry: If provided, fetched articles are stored here keyed
                          by URL so callers can later detect uncategorized ones.

    Returns:
        A LangChain tool function.
    """
    @tool(tool_name)
    def fetch_news(days_back: int = 7, max_articles: int = 0) -> str:
        """
        Fetch recent news articles from curated RSS feeds.

        Args:
            days_back: Number of days back to retrieve news (default: 7).
            max_articles: Maximum articles to return; 0 means no limit.

        Returns:
            JSON string with matching articles sorted by date (newest first),
            each containing title, url, published date, and source.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        articles = []

        def _parse_feed(feed_url: str) -> list:
            t0 = time.perf_counter()
            feed = feedparser.parse(feed_url)
            elapsed = time.perf_counter() - t0
            results = []
            for entry in feed.entries:
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(
                        *entry.published_parsed[:6], tzinfo=timezone.utc
                    )
                    if pub_date < cutoff:
                        continue
                results.append(
                    {
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": feed.feed.get("title", feed_url),
                        "_pub_date": pub_date,
                    }
                )
            logger.info(
                "[TIMER] feed=%s articles=%d elapsed=%.2fs",
                feed_url,
                len(results),
                elapsed,
            )
            return results

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as executor:
            for feed_articles in executor.map(_parse_feed, feeds):
                articles.extend(feed_articles)
        logger.info(
            "[TIMER] fetch_news total: feeds=%d articles=%d elapsed=%.2fs",
            len(feeds),
            len(articles),
            time.perf_counter() - t0,
        )

        articles.sort(
            key=lambda a: a["_pub_date"] or datetime.min.replace(
                tzinfo=timezone.utc
            ),
            reverse=True,
        )
        if max_articles:
            articles = articles[:max_articles]

        for article in articles:
            del article["_pub_date"]

        if article_registry is not None:
            article_registry.clear()
            article_registry.update({a["url"]: a["title"] for a in articles})
        if total_counter is not None:
            total_counter._total_fetched = len(articles)

        return json.dumps(articles, indent=2)

    return fetch_news


def _fetch_one(url: str) -> dict:
    """Fetch and extract content from a single URL."""
    try:
        t0 = time.perf_counter()
        response = requests.get(
            url, headers=_HEADERS, timeout=15, allow_redirects=True
        )
        http_elapsed = time.perf_counter() - t0
        response.raise_for_status()
        t1 = time.perf_counter()
        content = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
            url=response.url,
        )
        extract_elapsed = time.perf_counter() - t1
        logger.info(
            "[TIMER] article http=%.2fs extract=%.2fs url=%s",
            http_elapsed,
            extract_elapsed,
            url,
        )
        return {"url": url, "content": content or ""}
    except Exception as e:
        logger.warning("[TIMER] article error=%.2fs url=%s err=%s", time.perf_counter() - t0, url, e)
        return {"url": url, "content": f"Error: {str(e)}"}


@tool
def fetch_articles_content(urls: List[str]) -> str:
    """
    Fetch and extract the main text content from a list of article URLs.

    Fetches all URLs concurrently. Use this instead of calling
    fetch_article_content individually for each URL.

    Args:
        urls: List of article URLs to fetch.

    Returns:
        JSON string mapping each URL to its full extracted text content.
    """
    results = {}
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_one, url): url for url in urls}
        for future in as_completed(futures):
            result = future.result()
            results[result["url"]] = result["content"]
    logger.info(
        "[TIMER] fetch_articles_content total: urls=%d elapsed=%.2fs",
        len(urls),
        time.perf_counter() - t0,
    )
    return json.dumps(results, indent=2)


_URL_RE = re.compile(r"^https?://\S+$", re.MULTILINE)


def make_save_report_tool(
    collector: dict | None = None,
    article_registry: dict | None = None,
):
    """
    Return a LangChain @tool that saves reports to disk and optionally
    records their content in the provided collector dict.

    Args:
        collector: If provided, each saved report's content is stored here
                   under its theme name so callers can include it in responses.
        article_registry: If provided, URLs found in each report are removed
                          from the registry so the remainder are uncategorized.
    """
    @tool
    def save_themed_report(theme: str, content: str) -> str:
        """
        Save a themed news report as a markdown file.

        Args:
            theme: The theme/category name. Used as the base of the filename.
            content: The full markdown content to write to the report file.

        Returns:
            Confirmation message with the saved file path, or an error message.
        """
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{theme.lower()}_{date_str}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        if collector is not None:
            collector[theme] = content

        if article_registry is not None:
            for url in _URL_RE.findall(content):
                article_registry.pop(url, None)

        return f"Report saved to {filepath}"

    return save_themed_report
