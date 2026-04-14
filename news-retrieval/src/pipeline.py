"""Linear two-pass news aggregation pipeline.

Pass 1 — parallel LLM batch categorisation (gpt-4o-mini, structured output).
Pass 2 — parallel LLM report generation (claude-haiku-4-5).
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
from typing import Any

import feedparser
import httpx
from openai import OpenAI
from pydantic import BaseModel

from models.sources import load_sources

logger = logging.getLogger(__name__)

_PASS1_BATCH_SIZE = 5
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REPORTS_DIR = os.environ.get("REPORTS_DIR", "/app/reports")


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


def _make_client(model_group: str) -> OpenAI:
    """Return an OpenAI-compatible client pointed at OpenRouter.

    Args:
        model_group: ``"pass1"`` or ``"pass2"``, used only for logging.
    """
    logger.debug("Creating OpenAI client for %s", model_group)
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
# Step 3 — write reports (pass 2)
# ---------------------------------------------------------------------------

def _pass2_write_reports(
    qualifying: dict[str, list[str]],
    article_meta: dict[str, dict],
    domain_name: str,
    summary_depth: str,
    client: OpenAI,
) -> dict[str, str]:
    """Generate one markdown report per qualifying category in parallel.

    Returns:
        Dict mapping category name to markdown string.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    rate_limiter = _RateLimiter(rate=15.0)

    def _write_one(category: str, urls: list[str]) -> tuple[str, str]:
        rate_limiter.acquire()
        articles = [
            article_meta[url] for url in urls if url in article_meta
        ]
        articles_text = "\n---\n".join(
            f"Title: {a['title']}\nURL: {a['url']}\n"
            f"Summary: {a.get('summary', '')}"
            for a in articles
        )
        depth_note = (
            "1–2 sentences" if summary_depth == "brief"
            else "2–4 sentences"
        )
        system_msg = (
            f"You are a {domain_name} news analyst."
            f" Write a complete markdown report for the category"
            f" \"{category}\" using the article summaries provided.\n\n"
            f"Report format:\n# {category} — {today}\n\n"
            "## {{Article Title}}\n{{url}}\n"
            f"{{summary paragraph ({depth_note} per article)}}\n\n"
            "[one section per article]\n\n"
            "## Category Summary\n"
            "[Several paragraphs synthesising major trends, implications,"
            " and dynamics. Go beyond listing — provide insight and"
            " analysis. Reserve 'inflection point' language only where"
            " evidence shows a change in kind rather than degree.]\n\n"
            "Use article titles and URLs exactly as given."
        )
        response = client.chat.completions.create(
            model="anthropic/claude-haiku-4-5",
            temperature=0,
            messages=[
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        f"Category: {category}\n\nArticles:\n{articles_text}"
                    ),
                },
            ],
        )
        return category, response.choices[0].message.content

    reports: dict[str, str] = {}
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {
            executor.submit(_write_one, cat, urls): cat
            for cat, urls in qualifying.items()
        }
        done, not_done = futures_wait(futures, timeout=120)
        if not_done:
            logger.warning("[PASS2] %d reports timed out", len(not_done))
        for future in done:
            try:
                category, markdown = future.result()
                reports[category] = markdown
            except Exception as exc:
                logger.warning("[PASS2] report failed: %s", exc)

    logger.info(
        "[PASS2] categories=%d reports=%d elapsed=%.2fs",
        len(qualifying), len(reports), time.perf_counter() - t0,
    )
    return reports


def _save_reports(reports: dict[str, str]) -> list[str]:
    """Write each report to ``$REPORTS_DIR`` as a markdown file.

    Returns:
        List of filenames (basenames only) that were written.
    """
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filenames = []
    for category, content in reports.items():
        filename = f"{category.lower()}_{date_str}.md"
        filepath = os.path.join(_REPORTS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("[SAVE] %s", filepath)
        filenames.append(filename)
    return filenames


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    domain_slug: str,
    domain_name: str,
    taxonomy: list[str],
    days_back: int = 7,
    max_articles: int = 0,
    summary_depth: str = "detailed",
    focus: str | None = None,
) -> dict[str, Any]:
    """Run the two-pass pipeline for the given domain.

    Args:
        domain_slug: Domain identifier used to query sources from the DB.
        domain_name: Human-readable name used in LLM prompts.
        taxonomy: Ordered list of category names the LLM must use verbatim.
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles fetched; 0 means no limit.
        summary_depth: ``"brief"`` or ``"detailed"``.
        focus: Optional free-text instruction to narrow topics covered.

    Returns:
        Dict with ``"summary"`` (str) and ``"reports"``
        (category → markdown).
    """
    t0 = time.perf_counter()
    client_p1 = _make_client("pass1")
    client_p2 = _make_client("pass2")

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"summary": "No sources configured.", "reports": {}}

    articles = _fetch_articles(sources, days_back, max_articles)
    if not articles:
        return {"summary": "No articles found.", "reports": {}}

    article_meta = {a["url"]: a for a in articles}

    qualifying = _pass1_categorize(
        articles, taxonomy, domain_name, focus, client_p1
    )
    if not qualifying:
        return {"summary": "No qualifying categories.", "reports": {}}

    reports = _pass2_write_reports(
        qualifying, article_meta, domain_name, summary_depth, client_p2
    )
    filenames = _save_reports(reports)

    logger.info(
        "[TIMER] domain=%s total=%.2fs reports=%d",
        domain_slug, time.perf_counter() - t0, len(reports),
    )
    return {
        "summary": (
            f"Completed {domain_name} digest: {len(reports)} categories."
        ),
        "reports": reports,
        "filenames": filenames,
    }
