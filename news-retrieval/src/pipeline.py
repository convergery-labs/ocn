"""Single-pass news aggregation pipeline.

Pass 1 — parallel LLM batch categorisation (gpt-4o-mini, structured
output). Returns structured categories with article lists.
"""
import html
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx
from openai import OpenAI
from pydantic import BaseModel

from models.sources import load_sources

logger = logging.getLogger(__name__)

_PASS1_BATCH_SIZE = 5
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Token-bucket rate limiter, safe for concurrent threads."""

    def __init__(self, rate: float) -> None:
        """Args: rate: maximum calls per second (also the burst cap)."""
        self._rate = rate
        self._tokens = float(rate)
        self._last_refill = time.perf_counter()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.perf_counter()
                self._tokens = min(
                    self._rate,
                    self._tokens + (now - self._last_refill) * self._rate,
                )
                self._last_refill = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
            time.sleep(0.05)


class _ArticleAssignment(BaseModel):
    """A single article-to-category assignment from the LLM."""

    url: str
    category: str


class _BatchCategories(BaseModel):
    """Structured output envelope for a categorisation batch."""

    assignments: list[_ArticleAssignment]


def _make_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    return OpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        http_client=httpx.Client(http2=False, timeout=60.0),
    )


def _clean_summary(raw: str) -> str:
    """Strip HTML tags, unescape entities, and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Step 1 — fetch
# ---------------------------------------------------------------------------

def _fetch_articles(
    sources: list[dict],
    days_back: int,
    max_articles: int,
) -> list[dict]:
    """Fetch and filter articles from RSS feeds in parallel.

    Args:
        sources: List of source dicts with a ``url`` key.
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles; 0 means no limit.

    Returns:
        List of article dicts sorted newest-first.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    articles: list[dict] = []

    def _parse_feed(url: str) -> list[dict]:
        t0 = time.perf_counter()
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries:
            pub_date = None
            if (
                hasattr(entry, "published_parsed")
                and entry.published_parsed
            ):
                pub_date = datetime(
                    *entry.published_parsed[:6], tzinfo=timezone.utc
                )
                if pub_date < cutoff:
                    continue
            results.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": feed.feed.get("title", url),
                "summary": _clean_summary(entry.get("summary", "")),
                "_pub_date": pub_date,
            })
        logger.info(
            "[TIMER] feed=%s articles=%d elapsed=%.2fs",
            url, len(results), time.perf_counter() - t0,
        )
        return results

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as executor:
        for feed_articles in executor.map(
            _parse_feed, [s["url"] for s in sources]
        ):
            articles.extend(feed_articles)

    articles.sort(
        key=lambda a: (
            a["_pub_date"] or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    if max_articles:
        articles = articles[:max_articles]
    for a in articles:
        del a["_pub_date"]

    logger.info(
        "[TIMER] fetch total: feeds=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


# ---------------------------------------------------------------------------
# Step 2 — categorise (pass 1)
# ---------------------------------------------------------------------------

def _pass1_categorize(
    articles: list[dict],
    taxonomy: list[str],
    domain_name: str,
    focus: str | None,
    client: OpenAI,
) -> dict[str, list[str]]:
    """Categorise articles in parallel batches using structured output.

    Returns:
        Dict mapping category name to list of qualifying article URLs.
        Only categories with at least 2 articles are included.
    """
    taxonomy_set = set(taxonomy)
    taxonomy_str = "\n".join(f"  - {cat}" for cat in taxonomy)
    focus_line = f"\nAdditional focus: {focus}" if focus else ""
    system_msg = (
        f"You are a {domain_name} news categorisation assistant.\n"
        "Assign each article to the single most relevant category"
        " from the taxonomy below.\n"
        "Use the category name exactly as given."
        " If no category fits, use \"none\".\n"
        "Return JSON in this exact format:\n"
        "{\"assignments\": [{\"url\": \"...\", \"category\": \"...\"}]}\n\n"
        f"Only assign a category if the article is directly and primarily"
        f" about {domain_name}-related topics.\n\n"
        f"Taxonomy:\n{taxonomy_str}{focus_line}"
    )
    rate_limiter = _RateLimiter(rate=15.0)

    def _categorize_batch(
        batch: list[dict],
    ) -> list[tuple[str, str]]:
        rate_limiter.acquire()
        articles_text = "\n\n".join(
            f"Article {i + 1}:\nURL: {a['url']}\n"
            f"Title: \"{a['title']}\"\n"
            f"Source: {a['source']}\n"
            f"Summary: {a.get('summary', '')}"
            for i, a in enumerate(batch)
        )
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            response_format={"type": "json_object"},
            temperature=0,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": articles_text},
            ],
        )
        data = json.loads(response.choices[0].message.content)
        result = _BatchCategories(**data)
        return [(a.url, a.category) for a in result.assignments]

    batches = [
        articles[i:i + _PASS1_BATCH_SIZE]
        for i in range(0, len(articles), _PASS1_BATCH_SIZE)
    ]
    category_map: dict[str, list[str]] = {}
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(_categorize_batch, b): b for b in batches}
        done, not_done = futures_wait(futures, timeout=90)
        if not_done:
            logger.warning("[PASS1] %d batches timed out", len(not_done))
        for future in done:
            try:
                for url, category in future.result():
                    if category != "none" and category in taxonomy_set:
                        category_map.setdefault(category, []).append(url)
            except Exception as exc:
                logger.warning("[PASS1] batch failed: %s", exc)

    qualifying = {
        cat: urls
        for cat, urls in category_map.items()
        if len(urls) >= 2
    }
    logger.info(
        "[PASS1] articles=%d batches=%d qualifying=%d elapsed=%.2fs",
        len(articles), len(batches), len(qualifying),
        time.perf_counter() - t0,
    )
    return qualifying


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_ARTICLE_KEYS = ("url", "title", "summary", "source", "published")


def run(
    domain_slug: str,
    domain_name: str,
    taxonomy: list[str],
    days_back: int = 7,
    max_articles: int = 0,
    focus: str | None = None,
) -> dict[str, Any]:
    """Run the single-pass pipeline for the given domain.

    Args:
        domain_slug: Domain identifier used to query sources from DB.
        domain_name: Human-readable name used in LLM prompts.
        taxonomy: Ordered list of category names the LLM must use.
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles fetched; 0 means no limit.
        focus: Optional free-text instruction to narrow topics.

    Returns:
        Dict with ``"summary"`` (str) and ``"categories"``
        (category → list of article dicts).
    """
    t0 = time.perf_counter()
    client = _make_client()

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"summary": "No sources configured.", "categories": {}}

    articles = _fetch_articles(sources, days_back, max_articles)
    if not articles:
        return {"summary": "No articles found.", "categories": {}}

    article_meta = {a["url"]: a for a in articles}

    qualifying = _pass1_categorize(
        articles, taxonomy, domain_name, focus, client
    )
    if not qualifying:
        return {
            "summary": "No qualifying categories.",
            "categories": {},
        }

    categories = {
        cat: [
            {k: article_meta[url][k] for k in _ARTICLE_KEYS}
            for url in urls
            if url in article_meta
        ]
        for cat, urls in qualifying.items()
    }

    logger.info(
        "[TIMER] domain=%s total=%.2fs categories=%d",
        domain_slug, time.perf_counter() - t0, len(categories),
    )
    return {
        "summary": (
            f"Completed {domain_name} digest:"
            f" {len(categories)} categories."
        ),
        "categories": categories,
    }
