"""News aggregation pipeline: fetch and relevance-filter articles.

Pass 1 — title-only relevance filter (LLM via OpenRouter).
"""
import html
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import feedparser
import httpx
import openai
import trafilatura
from openai import OpenAI
from pydantic import BaseModel

from models.sources import load_sources

logger = logging.getLogger(__name__)

_PASS1_BATCH_SIZE = 20
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class _ArticleRelevance(BaseModel):
    """Relevance verdict for a single article."""

    url: str
    relevant: bool


class _BatchRelevance(BaseModel):
    """Structured output envelope for Pass 1 relevance filter."""

    articles: list[_ArticleRelevance]


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


def _make_client(api_key: str | None = None) -> OpenAI:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    return OpenAI(
        api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
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

def _extract_body(entry: Any, url: str, no_fetch: bool) -> str | None:
    """Return the best available body text for an article entry.

    Tries ``content:encoded`` first (≥ 150 words). Falls back to a
    Trafilatura fetch when the source permits it (``no_fetch=False``).

    Args:
        entry: feedparser entry object.
        url: Article URL used for Trafilatura fallback fetch.
        no_fetch: When True, skip the Trafilatura fetch.

    Returns:
        Cleaned body string, or None if unavailable.
    """
    content_list = entry.get("content", [])
    raw_body = (
        content_list[0].get("value", "") if content_list else ""
    )
    clean_body = _clean_summary(raw_body) if raw_body else ""
    if len(clean_body.split()) >= 150:
        return clean_body
    if no_fetch:
        return None
    downloaded = trafilatura.fetch_url(url)
    return trafilatura.extract(downloaded) if downloaded else None


def _parse_feed(source: dict, cutoff: datetime) -> list[dict]:
    """Parse a single RSS feed and return articles published after cutoff.

    Args:
        source: Source dict with ``url`` and ``no_fetch`` keys.
        cutoff: Exclude entries published before this datetime.

    Returns:
        List of article dicts with a ``_pub_date`` key for sorting.
    """
    url: str = source["url"]
    no_fetch: bool = source["no_fetch"]
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
        article_url = entry.get("link", "")
        results.append({
            "title": entry.get("title", ""),
            "url": article_url,
            "published": entry.get("published", ""),
            "source": feed.feed.get("title", url),
            "summary": _clean_summary(entry.get("summary", "")),
            "body": _extract_body(entry, article_url, no_fetch),
            "_pub_date": pub_date,
        })
    logger.info(
        "[TIMER] feed=%s articles=%d elapsed=%.2fs",
        url, len(results), time.perf_counter() - t0,
    )
    return results


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

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as executor:
        for feed_articles in executor.map(
            partial(_parse_feed, cutoff=cutoff),
            sources,
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
# Step 2 — relevance filter (Pass 1)
# ---------------------------------------------------------------------------

def _filter_batch(
    batch: list[dict],
    rate_limiter: _RateLimiter,
    system_msg: str,
    client: OpenAI,
    model: str,
) -> list[str]:
    """Return URLs of relevant articles in batch; on error return all URLs."""
    titles_text = "\n".join(
        f"{i + 1}. URL: {a['url']}\n   Title: {a['title']}"
        for i, a in enumerate(batch)
    )
    rate_limiter.acquire()
    try:
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            temperature=0,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": titles_text},
            ],
        )
        raw = response.choices[0].message.content or ""
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(
                f"No JSON object in response (len={len(raw)})"
            )
        data = json.loads(raw[start:end])
        result = _BatchRelevance(**data)
        return [a.url for a in result.articles if a.relevant]
    except openai.AuthenticationError:
        raise RuntimeError(
            "OpenRouter authentication failed — check your API key"
        )
    except Exception as exc:
        logger.warning(
            "[PASS1] batch failed (fail-open): %s", exc
        )
        return [a["url"] for a in batch]


def _filter_articles(
    articles: list[dict],
    domain_name: str,
    domain_description: str | None,
    focus: str | None,
    client: OpenAI,
    model: str,
) -> list[dict]:
    """Filter articles by domain relevance using titles only (Pass 1).

    Sends only ``url`` and ``title`` — no summary — keeping token cost low.
    Batches that fail are kept in full (fail-open) to avoid silent data loss.

    Args:
        articles: Full article dicts; only title and url are sent to the LLM.
        domain_name: Human-readable domain used in the prompt.
        domain_description: Optional description providing scope context.
        focus: Optional narrowing instruction appended to the prompt.
        client: OpenAI-compatible client.
        model: Model identifier string passed to the OpenRouter API.

    Returns:
        Subset of ``articles`` judged relevant to the domain.
    """
    desc_line = (
        f"\nDomain scope: {domain_description}" if domain_description else ""
    )
    focus_line = f"\nAdditional focus: {focus}" if focus else ""
    system_msg = (
        f"You are a relevance filter for a {domain_name} news digest."
        f"{desc_line}"
        f"\nFor each article title decide whether the article is"
        f" directly and primarily about {domain_name}-related"
        f" topics.{focus_line}"
        "\nReturn JSON in exactly this format:"
        '\n{"articles": [{"url": "...", "relevant": true}]}'
    )

    batches = [
        articles[i:i + _PASS1_BATCH_SIZE]
        for i in range(0, len(articles), _PASS1_BATCH_SIZE)
    ]
    rate_limiter = _RateLimiter(rate=15.0)
    relevant_urls: set[str] = set()
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {
            executor.submit(
                _filter_batch, b, rate_limiter, system_msg, client, model
            ): b
            for b in batches
        }
        done, not_done = futures_wait(futures, timeout=300)
        if not_done:
            logger.warning(
                "[PASS1] %d batches timed out (fail-open)", len(not_done)
            )
            for f in not_done:
                relevant_urls.update(a["url"] for a in futures[f])
        for future in done:
            try:
                relevant_urls.update(future.result())
            except RuntimeError:
                raise
            except Exception as exc:
                logger.warning("[PASS1] future error: %s", exc)

    filtered = [a for a in articles if a["url"] in relevant_urls]
    logger.info(
        "[PASS1] total=%d relevant=%d batches=%d elapsed=%.2fs",
        len(articles), len(filtered), len(batches),
        time.perf_counter() - t0,
    )
    return filtered


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_ARTICLE_KEYS = ("url", "title", "summary", "source", "published", "body")


def run(
    domain_slug: str,
    domain_name: str,
    domain_description: str | None = None,
    days_back: int = 7,
    max_articles: int = 0,
    focus: str | None = None,
    *,
    model: str,
    openrouter_api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch and relevance-filter articles for the given domain.

    Args:
        domain_slug: Domain identifier used to query sources from DB.
        domain_name: Human-readable name used in LLM prompts.
        domain_description: Optional description used to give the LLM
            additional context about the domain's scope.
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles fetched; 0 means no limit.
        focus: Optional free-text instruction to narrow topics.
        model: Model identifier string passed to the OpenRouter API.
        openrouter_api_key: Caller-supplied API key; falls back to
            the server's ``OPENROUTER_API_KEY`` env var when None.

    Returns:
        Dict with ``"articles"`` (list of article dicts).
    """
    t0 = time.perf_counter()
    client = _make_client(openrouter_api_key)

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"articles": []}

    articles = _fetch_articles(sources, days_back, max_articles)
    if not articles:
        return {"articles": []}

    relevant = _filter_articles(
        articles, domain_name, domain_description, focus, client, model
    )

    logger.info(
        "[TIMER] domain=%s total=%.2fs articles=%d",
        domain_slug, time.perf_counter() - t0, len(relevant),
    )
    return {
        "articles": [
            {k: a[k] for k in _ARTICLE_KEYS} for a in relevant
        ],
    }
