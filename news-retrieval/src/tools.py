"""Tools for news aggregator agents."""
import html
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import List

import feedparser
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get("REPORTS_DIR", "/app/reports")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_summary(raw: str) -> str:
    """Strip HTML tags, unescape entities, and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return " ".join(text.split())


def make_fetch_news_tool(
    feeds: List[str],
    tool_name: str = "fetch_news",
    article_registry: dict | None = None,
    total_counter=None,
    weekly_feeds: List[str] | None = None,
):
    """Return a LangChain @tool that fetches articles from the given RSS feeds.

    Args:
        feeds: List of RSS feed URLs to poll.
        tool_name: Name to give the tool (must be unique per agent).
        article_registry: If provided, fetched articles are stored here keyed
                          by URL so callers can later detect uncategorized ones.
        total_counter: Object whose ``_total_fetched`` attribute is updated
                       with the number of articles retrieved.
        weekly_feeds: Optional feeds included only when days_back >= 7.

    Returns:
        A LangChain tool function.
    """
    @tool(tool_name)
    def fetch_news(days_back: int = 7, max_articles: int = 0) -> str:
        """Fetch recent news articles from curated RSS feeds.

        Args:
            days_back: Number of days back to retrieve news (default: 7).
            max_articles: Maximum articles to return; 0 means no limit.

        Returns:
            JSON string with matching articles sorted by date (newest first),
            each containing title, url, published date, source, and summary.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        active_feeds = list(feeds)
        if weekly_feeds and days_back >= 7:
            active_feeds.extend(weekly_feeds)
            logger.info(
                "[FEEDS] days_back=%d including %d weekly feeds (total %d)",
                days_back,
                len(weekly_feeds),
                len(active_feeds),
            )
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
                        "summary": _clean_summary(entry.get("summary", "")),
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
            for feed_articles in executor.map(_parse_feed, active_feeds):
                articles.extend(feed_articles)
        logger.info(
            "[TIMER] fetch_news total: feeds=%d articles=%d elapsed=%.2fs",
            len(active_feeds),
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


_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+", re.MULTILINE)


def make_save_report_tool(
    collector: dict | None = None,
    article_registry: dict | None = None,
):
    """Return a LangChain @tool that saves reports to disk and optionally
    records their content in the provided collector dict.

    Args:
        collector: If provided, each saved report's content is stored here
                   under its theme name so callers can include it in responses.
        article_registry: If provided, URLs found in each report are removed
                          from the registry so the remainder are uncategorized.
    """
    @tool
    def save_themed_report(theme: str, content: str) -> str:
        """Save a themed news report as a markdown file.

        Args:
            theme: The theme/category name. Used as the base of the filename.
            content: The full markdown content to write to the report file.

        Returns:
            Confirmation message with the saved file path, or an error.
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
