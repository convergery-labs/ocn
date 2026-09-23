"""News aggregation pipeline: fetch articles from configured sources."""
import html
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import trafilatura
from openai import OpenAI
from trafilatura.settings import use_config

from dart_corp_code import resolve_corp_codes
from models.articles import (
    append_also_reported_by,
    get_already_stored_urls,
    get_recent_articles_for_domain,
    get_recent_gdelt_articles_for_ticker,
)
from models.sources import load_sources

logger = logging.getLogger(__name__)

_NEWSAPI_PAGE_SIZE = 30        # articles fetched per category per request
_SERPAPI_RESULTS_PER_QUERY = 30  # articles fetched per query from Google News
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SERPAPI_DATE_RE = re.compile(
    r"(\d{2}/\d{2}/\d{4}), (\d{1,2}:\d{2} [AP]M), \+0000 UTC"
)


def _parse_newsapi_date(date_str: str) -> datetime | None:
    """Parse a NewsAPI ISO-8601 publishedAt string to a UTC datetime."""
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


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
# Step 1 - fetch
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
    downloaded = trafilatura.fetch_url(url, config=_TRAFILATURA_CONFIG)
    return trafilatura.extract(downloaded) if downloaded else None


# feedparser's own default User-Agent identifies it as a bot and is
# rejected outright (HTTP 403) by at least one real, on-target Korean RSS
# feed (hankyung.com) that returns clean 200s for a normal browser
# User-Agent - see _parse_feed below. Applied to every RSS source, not
# just the one feed where this was caught, since any other WAF-protected
# feed would fail the same silent way (bozo=True, 0 entries, easy to
# misread as "this source is dead" rather than "this source is blocking
# feedparser specifically").
_RSS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Trafilatura's own default fetch User-Agent identifies it as a bot and is
# rejected outright (HTTP 403) by at least one real, on-target source
# (dailymail.com, confirmed live: 403 with Trafilatura's default UA, clean
# 200 with a normal browser UA) - same root cause _RSS_USER_AGENT above
# already fixes for RSS feeds, applied here to every trafilatura.fetch_url
# call (GDELT, SerpAPI, and the RSS content:encoded-fallback body fetches)
# so a WAF blocking Trafilatura specifically doesn't read as "this source
# has no body text". Does not fix sites that block scraping regardless of
# UA (confirmed live: reuters.com, bloomberg.com return 401/403 even with
# this same browser UA) - those still fail open to a null body, same as
# before.
_TRAFILATURA_CONFIG = use_config()
_TRAFILATURA_CONFIG.set("DEFAULT", "USER_AGENTS", _RSS_USER_AGENT)


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
    # Optional post-fetch title filter (config.title_filter, a regex
    # pattern string) - for a general/mixed-topic feed with no
    # business/economy section feed of its own (e.g. Yonhap's only
    # confirmed-working feed is its general wire, ~85% off-topic for this
    # pipeline's purposes: politics, diplomacy, sports). None/absent means
    # no filtering at all, unchanged behavior for every other RSS source.
    title_filter = (source.get("config") or {}).get("title_filter")
    title_filter_re = re.compile(title_filter, re.IGNORECASE) if title_filter else None
    t0 = time.perf_counter()
    # feedparser's own default User-Agent (UniversalFeedParser/...)
    # identifies it as a bot - confirmed live 2026-09-23 that at least one
    # real, on-target Korean feed (hankyung.com/feed/economy) 403s that
    # default outright while returning clean 200s + full content for a
    # normal browser User-Agent. Same underlying risk class as the
    # DART/document-fetch WAF issue found earlier - a source can look
    # "broken" (bozo=True, 0 entries) when it's actually just bot-blocked,
    # not genuinely dead the way ETNews's frozen feed was.
    feed = feedparser.parse(url, request_headers={"User-Agent": _RSS_USER_AGENT})
    results = []
    filtered_out = 0
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
        title = entry.get("title", "")
        if title_filter_re and not title_filter_re.search(title):
            filtered_out += 1
            continue
        article_url = entry.get("link", "")
        results.append({
            "title": title,
            "url": article_url,
            "published": entry.get("published", ""),
            "source": feed.feed.get("title", url),
            "summary": _clean_summary(entry.get("summary", "")),
            "body": _extract_body(entry, article_url, no_fetch),
            "_pub_date": pub_date,
        })
    logger.info(
        "[TIMER] feed=%s articles=%d filtered_out=%d elapsed=%.2fs",
        url, len(results), filtered_out, time.perf_counter() - t0,
    )
    return results


def _fetch_rss(sources: list[dict], days_back: int) -> list[dict]:
    """Fetch articles from RSS feeds in parallel.

    Args:
        sources: List of RSS source dicts with a ``url`` key.
        days_back: Exclude articles older than this many days.

    Returns:
        List of article dicts with a ``_pub_date`` key for sorting.
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
    logger.info(
        "[TIMER] rss total: feeds=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


def _days_to_tbs(days_back: int) -> str | None:
    """Map days_back to a SerpAPI tbs date-range parameter."""
    if days_back <= 1:
        return "qdr:d"
    if days_back <= 7:
        return "qdr:w"
    if days_back <= 30:
        return "qdr:m"
    return None


def _parse_serpapi_date(date_str: str) -> datetime | None:
    """Parse a SerpAPI date string to a UTC datetime, or None on failure."""
    m = _SERPAPI_DATE_RE.match(date_str)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %I:%M %p"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch_one_serpapi(source: dict, days_back: int, api_key: str) -> list[dict]:
    """Fetch Google News results for a SerpAPI source.

    If ``config`` contains a ``queries`` list, all queries are fetched in
    parallel and results are deduplicated by URL. Falls back to
    ``source["url"]`` as a single query when ``queries`` is absent.

    Args:
        source: Source dict; ``config.queries`` is the preferred query list;
            ``url`` is used as a single query when ``queries`` is absent.
        days_back: Used to set the SerpAPI tbs date-range filter.
        api_key: SerpAPI API key.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    config = dict(source.get("config") or {})
    queries: list[str] = config.pop("queries", None) or [source["url"]]
    tbs = _days_to_tbs(days_back)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    def _fetch_query(query: str) -> list[dict]:
        params: dict = {"engine": "google_news", "q": query, "api_key": api_key, "num": _SERPAPI_RESULTS_PER_QUERY, **config}
        if tbs:
            params["tbs"] = tbs
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params=params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("[SERPAPI] query=%r failed: %s", query, exc)
            return []
        results = []
        for r in data.get("news_results", []):
            pub_date = _parse_serpapi_date(r.get("date", ""))
            if pub_date and pub_date < cutoff:
                continue
            results.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "published": r.get("date", ""),
                "source": r.get("source", {}).get("name", ""),
                "summary": _clean_summary(r.get("snippet", "")),
                "_pub_date": pub_date,
            })
        return results

    t0 = time.perf_counter()
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        for query_results in executor.map(_fetch_query, queries):
            for a in query_results:
                if a["url"] and a["url"] not in seen_urls:
                    seen_urls.add(a["url"])
                    candidates.append(a)

    def _fetch_body(url: str) -> str | None:
        if not url:
            return None
        downloaded = trafilatura.fetch_url(url, config=_TRAFILATURA_CONFIG)
        return trafilatura.extract(downloaded) if downloaded else None

    with ThreadPoolExecutor(max_workers=10) as executor:
        bodies = list(executor.map(_fetch_body, [a["url"] for a in candidates]))

    for article, body in zip(candidates, bodies):
        article["body"] = body

    logger.info(
        "[TIMER] serpapi source=%r queries=%d articles=%d elapsed=%.2fs",
        source["url"], len(queries), len(candidates), time.perf_counter() - t0,
    )
    return candidates


def _fetch_serpapi(
    sources: list[dict],
    days_back: int,
    api_key: str,
) -> list[dict]:
    """Fetch Google News articles from SerpAPI for multiple queries in parallel.

    Args:
        sources: List of SerpAPI source dicts; ``url`` is the search query.
        days_back: Used to set the SerpAPI tbs date-range filter.
        api_key: SerpAPI API key.

    Returns:
        List of article dicts with ``_pub_date`` set to None.
    """
    articles: list[dict] = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as executor:
        for source_articles in executor.map(
            partial(_fetch_one_serpapi, days_back=days_back, api_key=api_key),
            sources,
        ):
            articles.extend(source_articles)
    logger.info(
        "[TIMER] serpapi total: sources=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


def _fetch_one_newsapi(source: dict, days_back: int, api_key: str) -> list[dict]:
    """Fetch top-headlines articles for a single NewsAPI source.

    If ``config`` contains a ``categories`` list, one HTTP request is made per
    category and results are deduplicated by URL before body enrichment.

    Args:
        source: Source dict; ``config`` carries NewsAPI params (``endpoint``,
            ``categories``, ``language``, etc.).
        days_back: Exclude articles older than this many days.
        api_key: NewsAPI API key.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    config = dict(source.get("config") or {})
    endpoint = config.pop("endpoint", "top-headlines")
    categories: list[str | None] = config.pop("categories", [None])
    from_date = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    base_url = f"https://newsapi.org/v2/{endpoint}"

    t0 = time.perf_counter()
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    for category in categories:
        params: dict = {**config, "pageSize": _NEWSAPI_PAGE_SIZE, "apiKey": api_key}
        if endpoint == "everything":
            params["from"] = from_date
        if category is not None:
            params["category"] = category
        try:
            resp = httpx.get(base_url, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(
                "[NEWSAPI] source=%r category=%r failed: %s",
                source["url"], category, exc,
            )
            continue
        for r in data.get("articles", []):
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            pub_date = _parse_newsapi_date(r.get("publishedAt", ""))
            if pub_date and pub_date < cutoff:
                continue
            seen_urls.add(url)
            raw_content = r.get("content", "") or ""
            candidates.append({
                "title": r.get("title", ""),
                "url": url,
                "published": r.get("publishedAt", ""),
                "source": (r.get("source") or {}).get("name", ""),
                "summary": _clean_summary(r.get("description", "") or ""),
                "body": _clean_summary(raw_content) or None,
                "_pub_date": pub_date,
            })

    logger.info(
        "[TIMER] newsapi source=%r articles=%d elapsed=%.2fs",
        source["url"], len(candidates), time.perf_counter() - t0,
    )
    return candidates


def _fetch_newsapi(
    sources: list[dict],
    days_back: int,
    api_key: str,
) -> list[dict]:
    """Fetch articles from NewsAPI for multiple sources in parallel.

    Args:
        sources: List of NewsAPI source dicts with ``config`` carrying API params.
        days_back: Exclude articles older than this many days.
        api_key: NewsAPI API key.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    articles: list[dict] = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as executor:
        for source_articles in executor.map(
            partial(_fetch_one_newsapi, days_back=days_back, api_key=api_key),
            sources,
        ):
            articles.extend(source_articles)
    logger.info(
        "[TIMER] newsapi total: sources=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


# research-universe tickers use dot notation for both US share classes
# (BRK.B) and foreign exchange suffixes (6503.JP, 000660.KS, ATCO-A.ST).
# Alpha Vantage only covers US-listed symbols and expects a dash for share
# classes (BRK-B). A true US share class is ALL-LETTERS.SINGLE-LETTER with
# no dash; anything else containing a dot (numeric prefixes, 2+ letter
# suffixes, or a dash elsewhere in the ticker) is a foreign exchange
# suffix and gets dropped.
_AV_SHARE_CLASS_RE = re.compile(r"^([A-Z]+)\.([A-Z])$")


def _normalize_av_ticker(ticker: str) -> str | None:
    """Convert a research-universe ticker to Alpha Vantage format, or None if unsupported."""
    ticker = ticker.strip().upper()
    share_class = _AV_SHARE_CLASS_RE.match(ticker)
    if share_class:
        return f"{share_class.group(1)}-{share_class.group(2)}"
    if "." in ticker:
        return None
    return ticker


def _fetch_universe_tickers(base_url: str, api_key: str | None = None) -> list[str]:
    """Fetch US-listed ticker symbols from the research-universe API.

    Calls GET /companies?country=United States&has_ticker=true (both verified
    and pending_review companies), normalizes each ticker to Alpha Vantage
    format (see _normalize_av_ticker), and drops any still-foreign tickers
    that slip through the country filter (the data has some mislabeled rows,
    e.g. Japan/HK/Korea listings tagged "United States"). Falls back to []
    on any error so the caller can continue with config-only tickers.

    Args:
        base_url: research-universe service base URL, e.g.
            "http://research-universe.staging.ocn.internal:8007"
        api_key: service API key (ru_ prefix) for Authorization header
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(
            f"{base_url}/companies",
            params={
                "country": "United States",
                "has_ticker": "true",
                "limit": 10000,
            },
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        companies = resp.json()
        tickers = []
        for c in companies:
            raw = c.get("ticker", "").strip()
            if not raw:
                continue
            normalized = _normalize_av_ticker(raw)
            if normalized:
                tickers.append(normalized)
        logger.info("[ALPHA_VANTAGE] fetched %d tickers from universe API", len(tickers))
        return tickers
    except Exception as exc:
        logger.warning(
            "[ALPHA_VANTAGE] universe API unavailable, falling back to config tickers: %s", exc
        )
        return []


# Alpha Vantage API limits (premium key):
# - 75 calls/minute, no daily limit
# - 1 ticker per call (multi-ticker requests return far fewer articles)
_AV_CALLS_PER_MINUTE = 75
_AV_MIN_INTERVAL = 60.0 / _AV_CALLS_PER_MINUTE  # ~0.8 seconds between calls
 

def get_tracked_ticker_universe(
    universe_url: str | None, universe_api_key: str | None = None,
) -> list[str]:
    """Single source of truth for the tracked ticker universe: US-listed
    tickers fetched live from research-universe, normalized and deduped.
    Used by both the Alpha Vantage fetch (this module) and the
    /market/tracked-tickers route, so the two never drift apart.

    Returns [] if universe_url is not set or research-universe is
    unreachable - callers treat an empty list as "skip this poll run"
    rather than falling back to a hardcoded list.
    """
    if not universe_url:
        return []
    return list(dict.fromkeys(_fetch_universe_tickers(universe_url, universe_api_key)))


def _fetch_alpha_vantage(
    sources: list[dict],
    alpha_vantage_key: str,
    universe_url: str | None = None,
    universe_api_key: str | None = None,
) -> list[dict]:
    """Fetch company-specific news from Alpha Vantage News & Sentiments API.

    One API call per ticker — multi-ticker requests return far fewer articles.
    Premium key has no daily call cap, only the per-minute rate limit above.

    Args:
        sources: List of alpha_vantage source dicts with ``config.tickers``.
        alpha_vantage_key: Alpha Vantage API key.
        universe_url: research-universe base URL; tickers are fetched
            dynamically from here (see get_tracked_ticker_universe). If
            unset or unreachable, no tickers are fetched and this run
            is skipped.
        universe_api_key: Service API key (ru_ prefix) for research-universe auth.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    # Always fetch last 24 hours only — AV is a daily source and fetching
    # wider windows re-fetches articles already stored from previous runs.
    _av_cutoff_days = 1
    cutoff = datetime.now(timezone.utc) - timedelta(days=_av_cutoff_days)
    time_from = cutoff.strftime("%Y%m%dT%H%M")

    tickers = get_tracked_ticker_universe(universe_url, universe_api_key)

    if not tickers:
        logger.warning("[ALPHA_VANTAGE] no tickers configured, skipping")
        return []

    logger.info("[ALPHA_VANTAGE] tickers=%d", len(tickers))

    # Fixed interval: 1 call/sec to stay within 60/min steady rate
    last_call_time: list[float] = [0.0]

    def _rate_limited_get(ticker: str) -> list[dict]:
        now = time.monotonic()
        elapsed = now - last_call_time[0]
        if elapsed < _AV_MIN_INTERVAL:
            time.sleep(_AV_MIN_INTERVAL - elapsed)
        last_call_time[0] = time.monotonic()

        try:
            resp = httpx.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "time_from": time_from,
                    "limit": 50,
                    "apikey": alpha_vantage_key,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("[ALPHA_VANTAGE] ticker=%r failed: %s", ticker, exc)
            return []

        results = []
        for item in data.get("feed", []):
            raw_date = item.get("time_published", "")
            try:
                pub_date = datetime.strptime(raw_date, "%Y%m%dT%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pub_date = None
            if pub_date and pub_date < cutoff:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "published": pub_date.isoformat() if pub_date else raw_date,
                "source": item.get("source", ""),
                "summary": _clean_summary(item.get("summary", "")),
                "body": None,
                "_pub_date": pub_date,
                # metadata: source-specific enrichment from Alpha Vantage.
                # overall_sentiment_score: float (-1 bearish to +1 bullish)
                # overall_sentiment_label: e.g. "Somewhat-Bullish"
                # ticker_sentiment: [{ticker, relevance_score, ticker_sentiment_score, ticker_sentiment_label}]
                # topics: [{topic, relevance_score}]
                "metadata": {
                    "overall_sentiment_score": item.get("overall_sentiment_score"),
                    "overall_sentiment_label": item.get("overall_sentiment_label"),
                    "ticker_sentiment": item.get("ticker_sentiment", []),
                    "topics": item.get("topics", []),
                },
            })
        logger.info("[ALPHA_VANTAGE] ticker=%r articles=%d", ticker, len(results))
        return results

    t0 = time.perf_counter()
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for ticker in tickers:
        for article in _rate_limited_get(ticker):
            if article["url"] and article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                articles.append(article)

    logger.info(
        "[TIMER] alpha_vantage tickers=%d articles=%d elapsed=%.2fs",
        len(tickers), len(articles), time.perf_counter() - t0,
    )
    return articles


_FEDERAL_REGISTER_URL = "https://www.federalregister.gov/api/v1/documents.json"
_FEDERAL_REGISTER_PAGE_SIZE = 100


def _fetch_one_federal_register(source: dict, days_back: int) -> list[dict]:
    """Fetch Federal Register documents for a single source's agency/type filter.

    No API key required. Paginates via ``next_page_url`` until exhausted.

    Args:
        source: Source dict; ``config.agencies`` and ``config.type`` scope
            the query to specific agencies and document types.
        days_back: Exclude documents published before this many days ago.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    config = dict(source.get("config") or {})
    agencies: list[str] = config.get("agencies", [])
    doc_types: list[str] = config.get("type", [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    params: dict = {
        "per_page": _FEDERAL_REGISTER_PAGE_SIZE,
        "order": "newest",
        "conditions[publication_date][gte]": cutoff.strftime("%Y-%m-%d"),
    }
    if agencies:
        params["conditions[agencies][]"] = agencies
    if doc_types:
        params["conditions[type][]"] = doc_types

    t0 = time.perf_counter()
    results: list[dict] = []
    url: str | None = _FEDERAL_REGISTER_URL
    request_params: dict | None = params

    while url:
        try:
            resp = httpx.get(url, params=request_params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("[FEDERAL_REGISTER] source=%r failed: %s", source["url"], exc)
            break

        for doc in data.get("results", []):
            pub_date = None
            try:
                pub_date = datetime.strptime(
                    doc.get("publication_date", ""), "%Y-%m-%d"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            if pub_date and pub_date < cutoff:
                continue
            agency_names = [a.get("name", "") for a in doc.get("agencies", [])]
            results.append({
                "title": doc.get("title", ""),
                "url": doc.get("html_url", ""),
                "published": doc.get("publication_date", ""),
                "source": ", ".join(filter(None, agency_names)) or "Federal Register",
                "summary": _clean_summary(doc.get("abstract") or ""),
                "body": None,
                "_pub_date": pub_date,
                "metadata": {
                    "type": doc.get("type"),
                    "document_number": doc.get("document_number"),
                    "agencies": agency_names,
                    "executive_order_number": doc.get("executive_order_number"),
                },
            })

        # next_page_url already carries the query string - drop params on
        # subsequent requests to avoid duplicating conditions.
        url = data.get("next_page_url")
        request_params = None

    logger.info(
        "[TIMER] federal_register source=%r articles=%d elapsed=%.2fs",
        source["url"], len(results), time.perf_counter() - t0,
    )
    return results


def _fetch_federal_register(sources: list[dict], days_back: int) -> list[dict]:
    """Fetch Federal Register documents for multiple sources in parallel.

    Args:
        sources: List of federal_register source dicts with ``config``
            carrying ``agencies`` and ``type`` filters.
        days_back: Exclude documents published before this many days ago.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    articles: list[dict] = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as executor:
        for source_articles in executor.map(
            partial(_fetch_one_federal_register, days_back=days_back),
            sources,
        ):
            articles.extend(source_articles)
    logger.info(
        "[TIMER] federal_register total: sources=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_GDELT_MIN_INTERVAL = 15.0  # GDELT's documented floor is 5s; observed to tighten under load -
# bumped from 10.0 after a live run showed 17/29 queries failing (429s, SSL handshake
# timeouts, connection resets) even at 10s spacing for the Taiwan per-company-name query
# pattern specifically (vs. geopolitical_news's broader theme queries, which succeed
# reliably at the same interval) - this alone won't fix the separate, larger loss from
# the company-name-in-title filter (Path 3 Stage A) dropping most surviving results.
_GDELT_MAXRECORDS = 250
_GDELT_MAX_ROUNDS = 3  # round-robin passes over rate-limited queries before giving up
_GDELT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ocn-news-retrieval/1.0;"
    " +https://opengrowthventures.com)"
)


_GDELT_RATE_LIMITED = object()  # sentinel: distinguishes 429 from "no results"

# Title-similarity dedup for Taiwan GDELT articles: two outlets covering the
# same underlying fact will use different wording, so exact URL/title
# matching can't catch it - only ticker-scoped Taiwan GDELT rows carry a
# "ticker" in metadata (set via source config's query_ticker map), so this
# check is a no-op for the geopolitical_news GDELT source, which has no
# ticker concept. Small model (1536 dims) since only short titles are
# compared, not full article bodies, within a narrow same-ticker window.
_TITLE_EMBEDDING_MODEL = "openai/text-embedding-3-small"
_TITLE_DEDUP_WINDOW_HOURS = 24
_TITLE_DEDUP_SIMILARITY_THRESHOLD = 0.90


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_domain_for_also_reported_by(article: dict) -> str | None:
    """Return the registrable domain for an also_reported_by entry, derived
    from the article's own url - never from article["source"].

    Confirmed live: article["source"] is a display name ("PBS", "Bloomberg",
    "Bloomberg Law News", "ABC News - Breaking News, Latest News and
    Videos"), not a domain - both dedup call sites in this module were
    storing that raw display name into also_reported_by, so any downstream
    consumer comparing against a domain allowlist (signal-detection-agent's
    Stage D corroboration check) could never match it, silently making
    corroboration structurally unreachable. Same "www." stripping as
    signal-detection-agent's Stage A _extract_domain, so a value written
    here is directly comparable against that service's ALLOWED_DOMAINS
    without further normalization.
    """
    url = article.get("url") or ""
    host = urlparse(url).hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[len("www."):]
    return host or None


_EMBED_TITLES_MAX_ATTEMPTS = 3
_EMBED_TITLES_RETRY_BACKOFF_SECS = 2.0


def _embed_titles(titles: list[str], api_key: str | None) -> list[list[float] | None]:
    """Embed a batch of titles via OpenRouter, same model class already used
    by signal-detection for lightweight claim-level comparison (as opposed
    to the larger text-embedding-3-large used there for full-body
    clustering — titles are short, a smaller model is enough and cheaper).

    Returns one embedding per title, in order; a title's slot is None if
    it was blank or every attempt failed, so callers must treat missing
    embeddings as "cannot compare" rather than "definitely not a duplicate"
    (fail-open - never silently drop an article because embedding failed).

    Blank/whitespace-only titles are filtered out before the API call and
    always map to None, never sent. Confirmed live: OpenRouter's embeddings
    endpoint rejects the ENTIRE batch with one 400 ("too_small": a string
    must have >=1 characters) if even one input is blank - and since the
    request is unchanged, every retry fails identically, so one blank title
    among 1362 real ones silently zeroed out embedding coverage (and so
    dedup) for the whole run. 6 of the 11 most recent geopolitical_news
    daily runs hit this exact failure before the filter was added here -
    not a rare blip, roughly half of all runs. Confirmed same-story
    duplicates across up to 4 different outlets (e.g. "EU lifts sanctions
    on Russian oligarchs Usmanov/Fridman", reuters.com/kyivpost.com/ft.com/
    france24.com) went unmerged as a direct result.

    Retries up to _EMBED_TITLES_MAX_ATTEMPTS times with a short fixed
    backoff before falling back to all-None for whatever's left in the
    batch (now only real, non-blank titles - a transient network/API error
    remains the only retryable failure mode). Confirmed live, separately:
    a single transient connection error on this call (no retry, at the
    time) caused an entire 369-article geopolitical_news fetch to skip
    dedup completely. A one-off network blip failing open for a handful of
    unresolvable titles is an acceptable, rare cost; failing open for an
    entire day's fetch on the first retry-free error is not.
    """
    if not titles:
        return []
    results: list[list[float] | None] = [None] * len(titles)
    embeddable_indices = [i for i, t in enumerate(titles) if t and t.strip()]
    if not embeddable_indices:
        return results
    embeddable_titles = [titles[i] for i in embeddable_indices]

    last_exc: Exception | None = None
    for attempt in range(1, _EMBED_TITLES_MAX_ATTEMPTS + 1):
        try:
            client = _make_client(api_key)
            response = client.embeddings.create(
                model=_TITLE_EMBEDDING_MODEL, input=embeddable_titles,
            )
            for i, item in zip(embeddable_indices, response.data):
                results[i] = item.embedding
            return results
        except Exception as exc:
            last_exc = exc
            if attempt < _EMBED_TITLES_MAX_ATTEMPTS:
                logger.warning(
                    "[GDELT] title embedding attempt %d/%d failed for batch"
                    " of %d, retrying: %s",
                    attempt, _EMBED_TITLES_MAX_ATTEMPTS, len(embeddable_titles), exc,
                )
                time.sleep(_EMBED_TITLES_RETRY_BACKOFF_SECS)
    logger.warning(
        "[GDELT] title embedding failed for batch of %d after %d attempts: %s",
        len(embeddable_titles), _EMBED_TITLES_MAX_ATTEMPTS, last_exc,
    )
    return results


# Below _SAME_EVENT_SIMILARITY_FLOOR, two titles are treated as definitely
# not the same story - no LLM call. Set from real geopolitical_news data:
# the lowest similarity measured between two confirmed-same-story headlines
# ("EU Delists 2 Oligarchs, Extends Russia Sanctions for 3 Years..." vs
# "EU to Extend Russia Sanctions After Latvia Drops Opposition to Oligarch
# Delistings", both about the same September 2026 EU Council decision) was
# 0.5951 - the floor is set just below that, not at an arbitrary round
# number. At or above _DOMAIN_TITLE_DEDUP_SIMILARITY_THRESHOLD (0.82 for
# geopolitical_news), two titles are treated as definitely the same story -
# also no LLM call, matching existing behavior exactly. Only the band
# between the two calls _titles_describe_same_event - see that function's
# docstring for why title similarity alone can't resolve this band.
_SAME_EVENT_SIMILARITY_FLOOR = 0.50

_SAME_EVENT_SYSTEM_PROMPT = (
    "You judge whether two news headlines report the SAME underlying event"
    " - the same specific government/institutional action, decision,"
    " ruling, signing, or announcement - even if the two headlines lead"
    " with different details, emphasize different consequences, or use"
    " different wording for the same outcome. Different outlets covering"
    " one real-world action commonly emphasize different angles of it and"
    " use different phrasing for the same outcome - this is still the SAME"
    " event.\n\n"
    "Watch for these specific traps:\n"
    "- 'Lifting sanctions on X', 'removing X from the sanctions list', and"
    " 'delisting X' all mean the SAME thing (X is no longer sanctioned) -"
    " never treat these as opposite or different actions.\n"
    "- A single vote or decision that both extends/renews a sanctions"
    " package AND delists specific individuals as part of that same vote"
    " is ONE event, not two - a headline emphasizing only the extension and"
    " another emphasizing only the delisting can both be reporting the"
    " exact same Council/legislative action.\n\n"
    "Treat two headlines as DIFFERENT events only when they describe a"
    " genuinely different action, decision, or moment in time: e.g. a"
    " proposal, attempt, or failed vote vs. its later actual approval; an"
    " announcement vs. a separate, later reaction to it; or two distinct"
    " developments on different days in a multi-day story."
    ' Return strict JSON only: {"same_event": true or false}'
)


_SAME_EVENT_LLM_CONCURRENCY = 10


def _resolve_db_borderline_matches_parallel(
    pending: list[tuple[int, str, str, Any]], api_key: str | None,
) -> dict[int, bool | None]:
    """Resolve a batch of DB-history borderline same-event checks concurrently.

    ``pending`` is a list of (article_index, article_title, candidate_title,
    candidate_db_id) - one entry per article whose best borderline
    candidate came from DB history (never same-batch; see the docstring on
    the two-phase split in _dedup_by_title_similarity_for_domain for why
    same-batch borderline candidates are excluded from this fast path and
    resolved sequentially instead).

    Each check only depends on its own (article_title, candidate_title)
    pair, fixed before any of these calls run - none of them can change
    another's outcome, so running them concurrently produces the exact
    same per-pair results as running them one at a time, just faster.
    Bounded by _SAME_EVENT_LLM_CONCURRENCY workers, each with its own
    OpenAI client (httpx.Client instances aren't meant to be shared across
    threads).

    Returns {article_index: same_event_result}, same True/False/None
    semantics as _titles_describe_same_event itself.
    """
    if not pending:
        return {}

    def _check_one(item):
        idx, article_title, candidate_title, _candidate_db_id = item
        return idx, _titles_describe_same_event(article_title, candidate_title, api_key)

    results: dict[int, bool | None] = {}
    with ThreadPoolExecutor(max_workers=_SAME_EVENT_LLM_CONCURRENCY) as executor:
        futures = [executor.submit(_check_one, item) for item in pending]
        for future in as_completed(futures):
            idx, same_event = future.result()
            results[idx] = same_event
    return results


def _titles_describe_same_event(
    title_a: str, title_b: str, api_key: str | None,
) -> bool | None:
    """Ask an LLM whether two headlines report the same underlying event.

    Exists because title-embedding similarity alone cannot separate real
    same-story duplicates from real different-story near-misses in this
    domain - confirmed live on geopolitical_news: a 9-headline cluster
    confirmed (by a human reviewing the actual stored rows) to be the same
    EU Council sanctions-extension story scored pairwise similarity
    0.5951-0.8177, which fully overlaps the similarity range (0.61-0.72)
    of a separately-confirmed pair of genuinely DIFFERENT stories (two
    distinct Canada-tariff headlines) that motivated raising the threshold
    to 0.82 in the first place - i.e. there is no single similarity cutoff
    that includes the real duplicate cluster while excluding the real
    false-positive case; they occupy the same band. This resolves that
    band with real semantic judgment instead of a threshold that cannot
    exist.

    Prompt history (tested live against an 8-case set: reaction-vs-event,
    multi-day story development, a confirmed false-positive pair, and 5
    EU sanctions-delisting headlines confirmed by a human to be one real
    event): the original wording scored 4/8, missing 4 of 5 EU cases -
    root cause was two specific reading failures, not vague instructions:
    the model read "lifting sanctions on X" and "removing X from the
    sanctions list" as OPPOSITE actions (they mean the same thing), and
    treated "delist individuals" and "extend the sanctions package" as
    two events even when reported as one Council vote. Two more general
    rewrites (a broader "same source article" framing, with and without
    also naming the sanctions-terminology trap) scored 5/8 each - worse
    than naming the specific traps directly, so this prompt keeps the
    explicit trap callouts rather than relying on general phrasing.
    Current wording scores 6/8 - fixed 3 of the 4 EU misses; the
    remaining miss is a headline that mentions delisting only in a
    subordinate clause explaining WHY an extension happened, which the
    model reads as background rather than as itself reporting the
    delisting - and introduced one new miss (conflates a failed vote with
    the later successful one), which fails toward extra merging rather
    than extra dropping, same direction other failures already accept.

    Returns True/False, or None on any failure (network, non-JSON, wrong
    shape) - callers must treat None as "cannot determine" and fail open
    (not a duplicate), same discipline as _embed_titles: a missed dedup is
    far cheaper than wrongly merging two real, distinct stories.
    """
    try:
        client = _make_client(api_key)
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": _SAME_EVENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Headline A: {title_a}\nHeadline B: {title_b}"},
            ],
        )
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)
        same_event = parsed.get("same_event")
        if not isinstance(same_event, bool):
            raise ValueError(f"same_event field missing or not boolean: {parsed!r}")
        return same_event
    except Exception as exc:
        logger.warning(
            "[GDELT] same-event check failed, treating as not-duplicate"
            " (fail-open): %r vs %r: %s",
            title_a, title_b, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Path 3, Stage A - free NOISE removal for GDELT (no model, runs before
# translation and before Stage B's model call - see module docstring notes
# on ordering: the company-name check below must run on the native-language
# title, since translating first would make this check depend on
# translation quality for no benefit).
# ---------------------------------------------------------------------------

# Domains confirmed live, in this project, to be genuine Taiwan financial
# or general-news press (not an exhaustive list - a starter allowlist,
# same spirit as the clause-code table above). Extend as more legitimate
# outlets are observed in real GDELT results.
_TAIWAN_PRESS_ALLOWLIST: frozenset[str] = frozenset({
    "setn.com",
    "digitimes.com.tw",
    "taipeitimes.com",
    "focustaiwan.tw",
    "udn.com",
    "money.udn.com",
    "ctee.com.tw",       # Commercial Times
    "cna.com.tw",        # Central News Agency
    # Added after a real live run against GDELT (2026-08-24) surfaced these
    # 4 domains carrying genuine, on-topic Taiwan company coverage
    # (Quanta, Wistron) that the original 8-domain starter list rejected -
    # each verified as a legitimate Taiwan outlet before adding.
    "n.yam.com",           # Yam News (蕃新聞) - general Taiwan news portal/aggregator
    "finance.ettoday.net", # ETtoday Finance Cloud - Taiwan financial-news vertical
    "news.ustv.com.tw",    # Unique Business News (非凡新聞) - Taiwan financial/business broadcaster
    # China Times (中國時報) - mainstream, Taiwan-headquartered, and it
    # carried real Wistron coverage in the same live test. Included, but
    # flagged: since its 2008 acquisition by Want Want China Times Group,
    # multiple credible sources (Freedom House, Taiwan's Mainland Affairs
    # Council, FT reporting) document PRC editorial-influence concerns on
    # cross-strait political topics. Judged acceptable for routine company
    # revenue/business reporting (this allowlist's actual purpose), not a
    # blanket endorsement of the outlet's political coverage - revisit if
    # this ever needs to expand beyond financial/business news.
    "chinatimes.com",
    # Added after a second real live run against GDELT (2026-08-24) surfaced
    # these domains carrying genuine, on-topic Taiwan company coverage
    # (TSMC, King Slide, Wistron) that the 12-domain list at that point
    # still rejected. Two OTHER domains from the same run - woman.udn.com
    # (a lifestyle/beauty vertical) and blog.udn.com (an unedited,
    # user-generated blogging platform) - were deliberately NOT added
    # despite being subdomains of the already-allowlisted udn.com: neither
    # is financial/business news, and udn.com's own allowlisting doesn't
    # extend to every subdomain under it.
    "ec.ltn.com.tw",  # Liberty Times (自由時報) dedicated finance/economics vertical
    "newtalk.tw",     # Newtalk News (新頭殼) - general Taiwan news outlet, not finance-dedicated but carries real company coverage
    "nownews.com",    # NOWnews (今日新聞) - general Taiwan news outlet, same reasoning
})

# Same purpose as _TAIWAN_PRESS_ALLOWLIST, scoped to Korea instead - a
# starter list, not exhaustive by design (per the Korea Signals spec's own
# "trusted Korean list" framing and explicit user instruction not to make
# this comprehensive), of domains this project has directly, live-verified
# as real Korean trade/business press: the five RSS feeds already seeded in
# KOREA_RSS_SOURCES below (thelec.kr, feedburner.com/zdkorea resolves to
# zdnet.co.kr bylines, businesspost.co.kr, ddaily.co.kr, and Yonhap's
# yna.co.kr), plus hankyung.com (Korea Economic Daily - confirmed reachable
# during the RSS User-Agent fix earlier in this build, even though it isn't
# one of the seeded RSS sources itself). GDELT can surface other genuine
# Korean outlets beyond this starter set the same way real Taiwan runs
# surfaced n.yam.com/finance.ettoday.net/etc. after the fact - extend as
# more legitimate Korean outlets are observed in real GDELT results, same
# process as Taiwan's own list above, not by trying to enumerate every
# Korean publication upfront.
_KOREA_PRESS_ALLOWLIST: frozenset[str] = frozenset({
    "thelec.kr",          # THE ELEC (디일렉)
    "zdnet.co.kr",        # ZDNet Korea (지디넷코리아)
    "businesspost.co.kr", # BusinessPost (비즈니스포스트)
    "ddaily.co.kr",       # DigitalDaily (디지털데일리)
    "yna.co.kr",          # Yonhap (연합뉴스)
    "hankyung.com",       # Korea Economic Daily (한국경제)
})

# Bug fixed 2026-09-23, live-confirmed against the test DB: BOTH
# KOREA_GDELT_SOURCE and KOREA_GDELT_ENGLISH_SOURCE (seed.py) populate
# query_ticker, so both were routed through _filter_by_domain_allowlist -
# which, before this map existed, only ever checked against
# _TAIWAN_PRESS_ALLOWLIST regardless of which domain's GDELT source called
# it. Result: every real Korea GDELT article (Korean-language AND the
# English-coverage-check source) was being silently dropped, since no
# Korean or English-wire domain is on the Taiwan-specific list - confirmed
# by a direct query against the local test DB returning zero
# source_category='gdelt' rows ever stored under korea_market_signal,
# despite the source being seeded and scheduled since early in this build.
_DOMAIN_PRESS_ALLOWLIST: dict[str, frozenset[str]] = {
    "taiwan_market_signal": _TAIWAN_PRESS_ALLOWLIST,
    "korea_market_signal": _KOREA_PRESS_ALLOWLIST,
}


def _filter_by_domain_allowlist(
    articles: list[dict], query_ticker: dict[str, str], domain_slug: str,
) -> list[dict]:
    """Drop GDELT articles whose domain is not on ``domain_slug``'s press
    allowlist (see ``_DOMAIN_PRESS_ALLOWLIST``).

    Only touches ticker-scoped GDELT articles (those whose ``_query`` is in
    ``query_ticker`` - the same test used by dedup) - other sources pass
    through untouched. Keyed on ``_query`` presence rather than
    ``metadata.source_category``, since this runs BEFORE
    _dedup_by_title_similarity, which is what actually writes
    source_category - at this point in the pipeline that field doesn't
    exist yet.

    A ticker key ending in ``-en`` (KOREA_GDELT_ENGLISH_SOURCE's convention
    - see seed.py) marks an English-coverage-CHECK query, not a primary
    signal source: its whole purpose is "does English coverage exist at
    all", so allowlisting it against a trusted-press list is the wrong
    concept (Reuters/Bloomberg/etc. covering a story is exactly the
    positive result this check wants to detect, not something to filter
    out for being untrusted) - passed through unconditionally instead.

    GDELT's ``domain`` field (stored as the article's ``source``) is
    compared case-insensitively; articles with no ``source`` set are
    dropped (fail-closed here, unlike the embedding fail-open logic below,
    since a domain we can't identify at all can't be verified as
    legitimate press for this market).

    Bug fixed 2026-09-23: this used to check unconditionally against
    _TAIWAN_PRESS_ALLOWLIST regardless of which domain's GDELT source
    called it, which silently dropped every real Korea GDELT article
    (Korean-language AND English-coverage-check) - confirmed live against
    the test DB (zero source_category='gdelt' rows ever stored under
    korea_market_signal despite the source being seeded and scheduled).
    """
    allowlist = _DOMAIN_PRESS_ALLOWLIST.get(domain_slug, frozenset())
    kept = []
    dropped = 0
    for a in articles:
        ticker_key = query_ticker.get(a.get("_query", ""))
        if not ticker_key:
            kept.append(a)
            continue
        if ticker_key.endswith("-en"):
            kept.append(a)
            continue
        domain = (a.get("source") or "").lower()
        if domain in allowlist:
            kept.append(a)
        else:
            dropped += 1
            logger.info("[PATH3-A] dropped (domain not allowlisted): %r", domain)
    if dropped:
        logger.info("[PATH3-A] domain allowlist: dropped %d article(s)", dropped)
    return kept


def _filter_by_company_name_in_title(
    articles: list[dict],
    query_ticker: dict[str, str],
    query_english_name: dict[str, str] | None = None,
) -> list[dict]:
    """Drop GDELT articles whose title doesn't actually contain the company
    name that was queried for.

    GDELT matches on free-text company name, not a guaranteed ticker field
    - this is a common failure mode of keyword search generally (a query
    for a company name can surface an article that only mentions that
    company in passing, inside a story primarily about something else).
    Checking here, on the native-language title, catches the case where the
    queried name doesn't appear in the returned headline at all.

    Must run BEFORE translation - the query string itself (and therefore
    the name to check for) is in whichever language was used to search
    (native Chinese or English name), and checking against the original,
    untranslated title avoids making this check depend on translation
    quality. Case-insensitive for English names; exact substring match for
    Chinese names (no case concept).

    Also accepts the ticker's English name as a fallback match, even for a
    native-name query - GDELT's sourcelang:chinese scope still surfaces some
    English-language syndication (Taipei Times, Focus Taiwan), which was
    being dropped by a native-name-only check despite genuinely naming the
    company. ``query_english_name`` is optional so other sources (e.g.
    geopolitical_news's theme queries, which have no ticker mapping at all)
    are unaffected.

    Keyed on ``_query`` presence, same reasoning as the allowlist filter
    above - source_category isn't set yet at this point in the pipeline.
    """
    query_english_name = query_english_name or {}
    kept = []
    dropped = 0
    for a in articles:
        query = a.get("_query", "")
        if not query_ticker.get(query):
            kept.append(a)
            continue
        # The query string is "{name} sourcelang:chinese sourcecountry:TW" -
        # the name is everything before the first operator.
        name = query.split(" sourcelang:")[0].strip()
        english_name = query_english_name.get(query, "")
        title = a.get("title") or ""
        title_lower = title.lower()
        if (name and name.lower() in title_lower) or (
            english_name and english_name.lower() in title_lower
        ):
            kept.append(a)
        else:
            dropped += 1
            logger.info(
                "[PATH3-A] dropped (queried name %r / english name %r not"
                " found in title %r)",
                name, english_name, title,
            )
    if dropped:
        logger.info(
            "[PATH3-A] company-name-in-title: dropped %d article(s)", dropped,
        )
    return kept


def _dedup_by_title_similarity(
    articles: list[dict], query_ticker: dict[str, str],
) -> list[dict]:
    """Drop Taiwan GDELT articles whose title is near-identical in meaning
    to one already stored for the same ticker in the last
    ``_TITLE_DEDUP_WINDOW_HOURS`` hours (rolling window relative to now,
    not calendar-day, so a duplicate that lands just after midnight isn't
    missed).

    Each article dict must carry ``_query`` (the GDELT query string that
    produced it, used to look up its ticker via ``query_ticker`` — GDELT has
    no ticker field itself, only a company-name query). Articles whose
    query has no ticker mapping (e.g. non-Taiwan GDELT sources) pass through
    unchanged - this function is a no-op unless ticker-scoped queries are
    present.

    Embedding failures fail open: an article whose title couldn't be
    embedded, or whose only comparison candidates lack a stored embedding,
    is kept rather than silently dropped or silently deduped.
    """
    ticker_scoped = [a for a in articles if query_ticker.get(a.get("_query", ""))]
    if not ticker_scoped:
        return articles

    api_key = os.environ.get("OPENROUTER_API_KEY")
    new_embeddings = _embed_titles([a["title"] for a in ticker_scoped], api_key)

    kept: list[dict] = []
    dropped = 0
    # Cache recent-article lookups per ticker within this call - multiple
    # surviving articles for the same ticker in one run shouldn't each
    # trigger their own DB query.
    recent_cache: dict[str, list[dict]] = {}
    # Candidates kept so far *within this same batch*, per ticker - required
    # in addition to the DB-backed recent_cache above, since two outlets can
    # both surface the same story within one poll run, before either has
    # been stored yet. Each entry also carries the in-memory article dict
    # itself (unlike DB candidates, which carry a row id instead) so a later
    # duplicate in the same batch can be merged into it directly rather
    # than needing a DB round-trip.
    kept_this_batch: dict[str, list[dict]] = {}

    for article, embedding in zip(ticker_scoped, new_embeddings):
        ticker = query_ticker[article["_query"]]
        if embedding is None:
            # No embedding to compare with, so this can't be checked for
            # duplicates against future polls either - but it still needs
            # ticker/source_category set, same as the normal path below,
            # so downstream consumers (ranking, filters) can rely on these
            # fields being present on every taiwan_market_signal GDELT row.
            article["metadata"]["ticker"] = ticker
            article["metadata"]["source_type"] = "gdelt"
            article["metadata"]["source_category"] = "gdelt"
            kept.append(article)
            continue

        if ticker not in recent_cache:
            recent_cache[ticker] = get_recent_gdelt_articles_for_ticker(
                ticker, hours=_TITLE_DEDUP_WINDOW_HOURS,
            )

        # Each candidate: (title, embedding, db_id_or_None, batch_article_or_None).
        # Exactly one of the last two is set - db_id for a DB-backed
        # candidate (needs an UPDATE), batch_article for a same-batch one
        # (can be merged in-memory, not yet written).
        candidates = [
            (c.get("title"), (c.get("metadata") or {}).get("title_embedding"),
             c.get("id"), None)
            for c in recent_cache[ticker]
        ] + [
            (c["title"], c["metadata"]["title_embedding"], None, c)
            for c in kept_this_batch.get(ticker, [])
        ]

        match = None
        for candidate_title, candidate_embedding, db_id, batch_article in candidates:
            if not candidate_embedding:
                continue
            similarity = _cosine_similarity(embedding, candidate_embedding)
            if similarity >= _TITLE_DEDUP_SIMILARITY_THRESHOLD:
                logger.info(
                    "[GDELT] near-duplicate title (similarity=%.3f)"
                    " ticker=%s new=%r existing=%r",
                    similarity, ticker, article["title"], candidate_title,
                )
                match = (db_id, batch_article)
                break

        if match is not None:
            db_id, batch_article = match
            domain = _extract_domain_for_also_reported_by(article)
            if batch_article is not None:
                # Same-batch match: merge in-memory, nothing written yet.
                also_reported_by = batch_article["metadata"].setdefault(
                    "also_reported_by", []
                )
                if domain and domain not in also_reported_by:
                    also_reported_by.append(domain)
            elif db_id is not None and domain:
                # Cross-run match: the existing row is already stored, so
                # this needs a real UPDATE rather than an in-memory merge.
                try:
                    append_also_reported_by(db_id, domain)
                except Exception as exc:
                    logger.warning(
                        "[GDELT] failed to record also_reported_by for"
                        " article_id=%s domain=%r: %s", db_id, domain, exc,
                    )
            dropped += 1
            continue

        # ticker + source_type must be written here, not left implicit -
        # get_recent_gdelt_articles_for_ticker()'s query filters on both
        # (metadata->>'ticker', metadata->>'source_type') to find candidates
        # for the NEXT poll run's dedup check. Without these, that lookup
        # always returns empty and cross-run dedup silently never fires.
        article["metadata"]["ticker"] = ticker
        article["metadata"]["source_type"] = "gdelt"
        article["metadata"]["source_category"] = "gdelt"
        article["metadata"]["title_embedding"] = embedding
        kept.append(article)
        kept_this_batch.setdefault(ticker, []).append(article)

    # Articles whose query has no ticker mapping (non-Taiwan GDELT sources)
    # were excluded from ticker_scoped above and never touched - add back.
    untouched = [a for a in articles if not query_ticker.get(a.get("_query", ""))]
    logger.info(
        "[GDELT] title-similarity dedup: %d ticker-scoped article(s),"
        " %d dropped as near-duplicates", len(ticker_scoped), dropped,
    )
    return untouched + kept


# Domains with no ticker/agency/curated-source pre-scoping (see the skip
# list in run()) - RSS/SerpAPI/NewsAPI sources for these routinely surface
# the same underlying story from multiple outlets with differently-worded
# titles, same problem _dedup_by_title_similarity solves for Taiwan GDELT,
# just scoped by domain instead of ticker.
_TITLE_DEDUP_DOMAINS: frozenset[str] = frozenset({
    "ai_news", "smart_money", "geopolitical_news", "korea_market_signal",
})

# ai_news/smart_money: wider than Taiwan GDELT's 24h (_TITLE_DEDUP_WINDOW_HOURS)
# - RSS/SerpAPI/NewsAPI sources publish re-coverage of the same story across a
# longer tail than same-day Taiwan company filings/news, so a same-day-only
# window was missing duplicates that appear the next day.
# geopolitical_news: 168h (7 days) - matches this domain's own full article
# retention (see Article Retention in CLAUDE.md), so a story that resurfaces
# anywhere within its retained lifetime still gets caught as a duplicate of
# the original, not just same-news-cycle re-reporting. Deliberately wider
# than Taiwan's 24h: geopolitical stories are corroborated by wire services
# over a longer tail than a same-day window would catch. Trade-off accepted:
# more embedding-comparison candidates per run than a 24h window, and a
# genuine multi-day story development (e.g. a conflict escalating days
# later) risks being merged into the original as a "duplicate" rather than
# treated as new - both weighed against catching more real duplicates.
_DOMAIN_TITLE_DEDUP_WINDOW_HOURS: dict[str, int] = {
    "ai_news": 48,
    "smart_money": 48,
    "geopolitical_news": 168,
    # Korea Signals spec Section 5.7, Filter 3: "drop anything that repeats
    # a story already seen in the last day" - literally 24h, unlike the
    # other domains here (which widened past 24h after missing real
    # duplicates - see comment below). No such finding yet for Korea; start
    # at the spec's literal number rather than importing another domain's
    # correction pre-emptively.
    "korea_market_signal": 24,
}

# Per-domain override of _TITLE_DEDUP_SIMILARITY_THRESHOLD (0.90 default,
# used by ai_news/smart_money and Taiwan GDELT). geopolitical_news lowered
# twice after real same-story duplicates were confirmed missed just under
# each prior threshold:
#   0.90 -> 0.85: "Canada Sanctions Streit Group Over Armored Vehicle
#   Supplies to Russia" (militarnyi.com) vs "Canada Hits Streit Group With
#   Sanctions Over Armored Vehicles Used by Russia's National Guard"
#   (kyivpost.com), measured at 0.8691.
#   0.85 -> 0.82: "US Congress passes Russia sanctions bill" (dw.com) vs
#   "Congress passes sweeping US sanctions bill targeting Russia"
#   (aljazeera.com), measured at 0.8488 - both allowlisted wire sources,
#   so this specific miss was directly suppressing real corroboration
#   downstream (Stage D's corroborated check).
# Kept domain-specific rather than lowering the shared default globally:
# geopolitical wire coverage of the same event varies headline wording
# more than ai_news/smart_money's typical re-reporting, and 0.82 keeps a
# real margin above the ~0.61-0.72 range three genuinely different
# Canada-tariff headlines (different specifics: general tariffs vs. named
# products) scored in the same real dataset - so this still catches both
# confirmed-missed duplicates without pulling those distinct stories
# together. If a third real miss turns up close to 0.82, that's a signal
# this domain's headline variance may need a different approach entirely
# (e.g. entity/actor overlap in addition to title similarity) rather than
# a third threshold nudge.
_DOMAIN_TITLE_DEDUP_SIMILARITY_THRESHOLD: dict[str, float] = {
    "geopolitical_news": 0.82,
}

# korea_market_signal mixes DART filings, Customs export data, and RSS/GDELT
# news in one domain - unlike ai_news/smart_money/geopolitical_news, which
# are news-only. The Korea Signals spec's S7 "drop anything that repeats a
# story already seen" (Filter 3) is a NEWS-story rule; a DART filing header
# ("SK Hynix: 단일판매·공급계약체결") is never a near-duplicate of a real
# headline by embedding similarity in practice, but running the comparison
# over filing/customs rows at all is still wasted work and the wrong
# candidate pool in principle - so korea_market_signal excludes any article
# whose stored/incoming metadata.source_category is one of these from BOTH
# sides of the comparison (new batch and DB-side recent candidates), rather
# than trying to enumerate "is a news source_type" (RSS articles set no
# source_category at all at this point in the pipeline - see _parse_feed -
# so absence of source_category means "news", not "unknown").
_DOMAIN_TITLE_DEDUP_EXCLUDED_CATEGORIES: dict[str, frozenset[str]] = {
    "korea_market_signal": frozenset({"dart_filing", "kr_customs_export"}),
}

# Domains where a borderline-similarity pair (see _SAME_EVENT_SIMILARITY_FLOOR)
# gets resolved by _titles_describe_same_event instead of staying unmerged.
# geopolitical_news only for now - confirmed live there that title similarity
# alone can't separate real duplicates from real different-story near-misses
# (see that function's docstring); ai_news/smart_money haven't shown the same
# confirmed failure, so they keep the cheaper threshold-only comparison
# rather than paying for LLM calls speculatively.
_SAME_EVENT_LLM_DOMAINS: frozenset[str] = frozenset({"geopolitical_news"})


def _dedup_by_title_similarity_for_domain(
    articles: list[dict], domain_slug: str,
) -> list[dict]:
    """Drop articles whose title is near-identical in meaning to one already
    stored for this domain in the last ``_DOMAIN_TITLE_DEDUP_WINDOW_HOURS[domain_slug]``
    hours.

    Same algorithm as ``_dedup_by_title_similarity`` (Taiwan GDELT), scoped
    by domain instead of ticker - ai_news/smart_money/geopolitical_news sources
    aren't ticker-scoped, so "same domain" is the natural comparison boundary
    instead.

    Embedding failures fail open: an article whose title couldn't be
    embedded, or whose only comparison candidates lack a stored embedding,
    is kept rather than silently dropped or silently deduped.

    Domains in ``_DOMAIN_TITLE_DEDUP_EXCLUDED_CATEGORIES`` mix news articles
    with non-news rows (e.g. korea_market_signal's DART filings/Customs
    export data) - rows whose ``metadata.source_category`` is in that set
    are excluded from both the incoming batch and the DB-side candidate
    pool, since this check is a news-story rule, not a general dedup.
    """
    if not articles:
        return articles

    excluded_categories = _DOMAIN_TITLE_DEDUP_EXCLUDED_CATEGORIES.get(domain_slug)
    if excluded_categories:
        non_news = [
            a for a in articles
            if (a.get("metadata") or {}).get("source_category") in excluded_categories
        ]
        articles = [
            a for a in articles
            if (a.get("metadata") or {}).get("source_category") not in excluded_categories
        ]
        if not articles:
            return non_news
    else:
        non_news = []

    api_key = os.environ.get("OPENROUTER_API_KEY")
    new_embeddings = _embed_titles([a["title"] for a in articles], api_key)

    recent = get_recent_articles_for_domain(
        domain_slug, hours=_DOMAIN_TITLE_DEDUP_WINDOW_HOURS[domain_slug],
    )
    if excluded_categories:
        recent = [
            c for c in recent
            if (c.get("metadata") or {}).get("source_category") not in excluded_categories
        ]
    candidates = [
        (c.get("title"), (c.get("metadata") or {}).get("title_embedding"),
         c.get("id"), None)
        for c in recent
    ]
    threshold = _DOMAIN_TITLE_DEDUP_SIMILARITY_THRESHOLD.get(
        domain_slug, _TITLE_DEDUP_SIMILARITY_THRESHOLD,
    )
    same_event_domain = domain_slug in _SAME_EVENT_LLM_DOMAINS

    # Phase 1 (sequential, no I/O): resolve each article's DB-history-only
    # hard match and best DB-history-only borderline candidate. DB history
    # (``candidates``) is fixed before this loop starts - unlike same-batch
    # candidates (which grow as earlier articles in THIS batch survive),
    # comparing against it never depends on what order articles are
    # processed in, so this pass is safe to resolve out of order (which
    # phase 2 then does, concurrently).
    db_hard_match: dict[int, Any] = {}
    db_borderline: dict[int, tuple[float, str, Any]] = {}
    for i, (article, embedding) in enumerate(zip(articles, new_embeddings)):
        article.setdefault("metadata", {})
        if embedding is None:
            continue
        best_borderline: tuple[float, str, Any] | None = None
        for candidate_title, candidate_embedding, db_id, _batch_article in candidates:
            if not candidate_embedding:
                continue
            similarity = _cosine_similarity(embedding, candidate_embedding)
            if similarity >= threshold:
                db_hard_match[i] = db_id
                break
            if (
                same_event_domain
                and similarity >= _SAME_EVENT_SIMILARITY_FLOOR
                and (best_borderline is None or similarity > best_borderline[0])
            ):
                best_borderline = (similarity, candidate_title, db_id)
        else:
            if best_borderline is not None:
                db_borderline[i] = best_borderline

    # Phase 2 (parallel): resolve every DB-history borderline check
    # concurrently - each pair is independent (see
    # _resolve_db_borderline_matches_parallel's docstring), so this is
    # the one part of the whole function safe to run out of order and
    # concurrently. Same-batch borderline checks are deliberately NOT
    # included here - they're resolved sequentially in phase 3 below,
    # since which same-batch candidates even EXIST depends on batch
    # order (an earlier article being dropped means it's never added to
    # kept_this_batch for a later article to match against).
    pending = [
        (i, articles[i]["title"], title, db_id)
        for i, (sim, title, db_id) in db_borderline.items()
    ]
    db_same_event_results = _resolve_db_borderline_matches_parallel(pending, api_key)

    # Phase 3 (sequential): walk the batch in order exactly as before,
    # but hard matches and DB-borderline same-event checks are already
    # known from phases 1-2 (no LLM call needed here for those) - only a
    # same-batch borderline candidate (rare: two outlets in one fetch)
    # still triggers an inline LLM call, same as the original single-pass
    # version, preserving its exact behavior for that case.
    kept_this_batch: list[dict] = []
    kept: list[dict] = []
    dropped = 0

    for i, (article, embedding) in enumerate(zip(articles, new_embeddings)):
        if embedding is None:
            kept.append(article)
            continue

        match: tuple[Any, dict | None] | None = None

        if i in db_hard_match:
            db_id = db_hard_match[i]
            logger.info(
                "[%s] near-duplicate title (threshold=%.2f) new=%r db_id=%s",
                domain_slug, threshold, article["title"], db_id,
            )
            match = (db_id, None)
        elif i in db_borderline and db_same_event_results.get(i):
            similarity, candidate_title, db_id = db_borderline[i]
            logger.info(
                "[%s] near-duplicate title via same-event check"
                " (similarity=%.3f, below threshold=%.2f) new=%r existing=%r",
                domain_slug, similarity, threshold, article["title"], candidate_title,
            )
            match = (db_id, None)
        else:
            # No DB-history match - only same-batch candidates kept so
            # far can still produce a match, checked sequentially exactly
            # as the original single-pass loop did.
            best_batch_borderline: tuple[float, str, dict] | None = None
            for batch_article in kept_this_batch:
                candidate_title = batch_article["title"]
                candidate_embedding = batch_article["metadata"]["title_embedding"]
                similarity = _cosine_similarity(embedding, candidate_embedding)
                if similarity >= threshold:
                    logger.info(
                        "[%s] near-duplicate title (similarity=%.3f, threshold=%.2f)"
                        " new=%r existing=%r",
                        domain_slug, similarity, threshold, article["title"], candidate_title,
                    )
                    match = (None, batch_article)
                    break
                if (
                    same_event_domain
                    and similarity >= _SAME_EVENT_SIMILARITY_FLOOR
                    and (best_batch_borderline is None or similarity > best_batch_borderline[0])
                ):
                    best_batch_borderline = (similarity, candidate_title, batch_article)
            if match is None and best_batch_borderline is not None:
                similarity, candidate_title, batch_article = best_batch_borderline
                same_event = _titles_describe_same_event(
                    article["title"], candidate_title, api_key,
                )
                if same_event:
                    logger.info(
                        "[%s] near-duplicate title via same-event check"
                        " (similarity=%.3f, below threshold=%.2f)"
                        " new=%r existing=%r",
                        domain_slug, similarity, threshold, article["title"], candidate_title,
                    )
                    match = (None, batch_article)

        if match is not None:
            db_id, batch_article = match
            outlet = _extract_domain_for_also_reported_by(article)
            if batch_article is not None:
                also_reported_by = batch_article["metadata"].setdefault(
                    "also_reported_by", []
                )
                if outlet and outlet not in also_reported_by:
                    also_reported_by.append(outlet)
            elif db_id is not None and outlet:
                try:
                    append_also_reported_by(db_id, outlet)
                except Exception as exc:
                    logger.warning(
                        "[%s] failed to record also_reported_by for"
                        " article_id=%s outlet=%r: %s",
                        domain_slug, db_id, outlet, exc,
                    )
            dropped += 1
            continue

        article["metadata"]["title_embedding"] = embedding
        kept.append(article)
        kept_this_batch.append(article)

    logger.info(
        "[%s] title-similarity dedup: %d article(s), %d dropped as"
        " near-duplicates", domain_slug, len(articles), dropped,
    )
    return kept + non_news


def _fetch_one_gdelt(query: str, days_back: int):
    """Fetch GDELT DOC 2.0 API results for a single theme query, one attempt.

    English-only. DOC API returns headline + URL metadata only, no body
    text — the Context 2.0 API returns snippet text but rejects bare
    ``theme:`` filters ("keywords too common"), so DOC is used here for
    theme-filter support; ``body`` is left None for a later fetch step.

    Makes exactly one HTTP request — no internal retry. GDELT's rate limit
    has been observed to persist well beyond its documented 5-second floor,
    so retrying a single query immediately just stalls every other query
    behind it; the caller (_fetch_gdelt) instead moves on to the next query
    and retries rate-limited ones in a later round-robin pass, once more
    real time has actually elapsed.

    Args:
        query: GDELT query string, e.g. "theme:ARMEDCONFLICT sourcelang:english".
        days_back: Exclude articles older than this many days (clamped to
            90 - DOC API only covers a rolling 3-month window).

    Returns:
        List of article dicts with ``_pub_date`` set, or the
        ``_GDELT_RATE_LIMITED`` sentinel if GDELT returned 429.
    """
    timespan_days = min(days_back, 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": _GDELT_MAXRECORDS,
        "timespan": f"{timespan_days}d",
        "sort": "datedesc",
        "format": "json",
    }

    try:
        resp = httpx.get(
            _GDELT_DOC_URL,
            params=params,
            headers={"User-Agent": _GDELT_USER_AGENT},
            timeout=30.0,
        )
        if resp.status_code == 429:
            logger.warning("[GDELT] query=%r rate-limited", query)
            return _GDELT_RATE_LIMITED
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[GDELT] query=%r failed: %s", query, exc)
        return []

    results = []
    for item in data.get("articles", []):
        try:
            pub_date = datetime.strptime(
                item.get("seendate", ""), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pub_date = None
        if pub_date and pub_date < cutoff:
            continue
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "published": item.get("seendate", ""),
            "source": item.get("domain", ""),
            "summary": None,
            "body": None,
            "_pub_date": pub_date,
            # transient - which query produced this; consumed by
            # _dedup_by_title_similarity's ticker lookup, stripped before
            # storage same as _pub_date (never enters the DB write path).
            "_query": query,
            "metadata": {
                "sourcecountry": item.get("sourcecountry"),
                "language": item.get("language"),
            },
        })
    logger.info(
        "[GDELT] query=%r articles=%d", query, len(results),
    )
    return results


def _fetch_gdelt(sources: list[dict], days_back: int, domain_slug: str = "") -> list[dict]:
    """Fetch articles from GDELT for multiple theme queries, round-robin.

    Runs every query once, in order, spaced by ``_GDELT_MIN_INTERVAL`` to
    respect GDELT's rate limit. Queries that come back 429'd are not
    retried immediately (that would stall every later query behind them) —
    they're collected and retried in a second pass, up to
    ``_GDELT_MAX_ROUNDS`` total passes, by which point real time has
    actually elapsed and the rate limit is more likely to have cleared.
    Queries still failing after the last pass are skipped for this run
    (fail-open per query, not per run).

    Once all queries are fetched and deduplicated, articles already stored
    globally (any domain, any prior run) are dropped *before* the
    body-fetch step — GDELT's theme queries return heavily overlapping
    results day-to-day, so fetching bodies for already-seen URLs would be
    wasted work. Remaining articles get their body fetched in parallel via
    Trafilatura, since DOC API returns no body/summary text itself.

    Args:
        sources: List of gdelt source dicts; ``config.queries`` is a list
            of GDELT query strings (one per theme/category).
        days_back: Exclude articles older than this many days.
        domain_slug: The domain these sources belong to - used for the
            domain-scoped press allowlist (_DOMAIN_PRESS_ALLOWLIST) below.
            Passed explicitly by the caller (run() via _fetch_articles),
            not read off a source dict - a source dict here (as returned
            by load_sources) never carries its own domain_slug field
            (unlike list_sources, an unrelated admin/UI-facing query which
            does join it in). Bug fixed 2026-09-23, confirmed live: this
            function used to try `sources[0].get("domain_slug", "")`,
            which always silently returned "" (never matching any real
            key in _DOMAIN_PRESS_ALLOWLIST) - a real staging run showed
            every GDELT article for korea_market_signal being dropped by
            the allowlist check, including ones from domains that ARE on
            _KOREA_PRESS_ALLOWLIST (zdnet.co.kr, ddaily.co.kr), proving
            the lookup itself was never reaching the right allowlist, not
            that those domains were missing from it.

    Returns:
        List of article dicts with ``_pub_date`` set, deduplicated by URL.
    """
    pending: list[str] = []
    for source in sources:
        config = source.get("config") or {}
        pending.extend(config.get("queries", []))
    total_queries = len(pending)

    t0 = time.perf_counter()
    seen_urls: set[str] = set()
    articles: list[dict] = []
    last_call_time = 0.0

    for round_num in range(1, _GDELT_MAX_ROUNDS + 1):
        retry_queue: list[str] = []
        for query in pending:
            elapsed = time.monotonic() - last_call_time
            if last_call_time and elapsed < _GDELT_MIN_INTERVAL:
                time.sleep(_GDELT_MIN_INTERVAL - elapsed)
            last_call_time = time.monotonic()

            result = _fetch_one_gdelt(query, days_back)
            if result is _GDELT_RATE_LIMITED:
                retry_queue.append(query)
                continue
            for article in result:
                if article["url"] and article["url"] not in seen_urls:
                    seen_urls.add(article["url"])
                    articles.append(article)

        if not retry_queue:
            break
        logger.info(
            "[GDELT] round %d/%d: %d quer(y/ies) rate-limited, retrying"
            " in next round",
            round_num, _GDELT_MAX_ROUNDS, len(retry_queue),
        )
        pending = retry_queue
    else:
        logger.warning(
            "[GDELT] %d/%d quer(y/ies) still rate-limited after %d"
            " round(s), skipping for this run",
            len(pending), total_queries, _GDELT_MAX_ROUNDS,
        )

    already_stored = get_already_stored_urls([a["url"] for a in articles])
    before = len(articles)
    articles = [a for a in articles if a["url"] not in already_stored]
    logger.info(
        "[GDELT] dropped %d already-stored article(s) before body fetch",
        before - len(articles),
    )

    query_ticker: dict[str, str] = {}
    query_english_name: dict[str, str] = {}
    for source in sources:
        config = source.get("config") or {}
        query_ticker.update(config.get("query_ticker", {}))
        query_english_name.update(config.get("query_english_name", {}))

    # Path 3, Stage A (spec order: allowlist -> name-in-title -> dedup).
    # All three are no-ops for sources with no ticker mapping (e.g.
    # geopolitical_news's theme queries) - only ticker-scoped Taiwan
    # queries are affected. Run before translation and before the body
    # fetch below, so a dropped article never wastes translation cost or a
    # Trafilatura fetch.
    if query_ticker:
        before_stage_a = len(articles)
        articles = _filter_by_domain_allowlist(articles, query_ticker, domain_slug)
        articles = _filter_by_company_name_in_title(
            articles, query_ticker, query_english_name,
        )
        logger.info(
            "[GDELT] Path 3 Stage A (allowlist + name-check): %d -> %d article(s)",
            before_stage_a, len(articles),
        )

        before_title_dedup = len(articles)
        articles = _dedup_by_title_similarity(articles, query_ticker)
        logger.info(
            "[GDELT] title-similarity dedup: %d -> %d article(s)",
            before_title_dedup, len(articles),
        )

    def _fetch_body(url: str) -> str | None:
        downloaded = trafilatura.fetch_url(url, config=_TRAFILATURA_CONFIG)
        return trafilatura.extract(downloaded) if downloaded else None

    with ThreadPoolExecutor(max_workers=10) as executor:
        bodies = list(executor.map(_fetch_body, [a["url"] for a in articles]))
    for article, body in zip(articles, bodies):
        article["body"] = body

    logger.info(
        "[TIMER] gdelt total: queries=%d articles=%d elapsed=%.2fs",
        total_queries, len(articles), time.perf_counter() - t0,
    )
    return articles


_TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
_TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
_TWSE_MATERIAL_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
_TPEX_MATERIAL_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"

# TPEx has been observed to reset the connection on a bare httpx request;
# a browser User-Agent avoids it. Applied to all four TWSE/TPEx calls for
# consistency even though only TPEx showed the issue.
_TWSE_TPEX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        " AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/124.0.0.0 Safari/537.36"
    ),
}

# TPEx's site is served through Cloudflare (a clean, stable 2-IP answer
# set), plus a separate origin IP that serves a broken TWCA-issued cert
# directly (intermediate missing a Subject Key Identifier extension -
# OpenSSL 3.x's stricter chain builder rejects it; curl's looser
# chain-building tolerates it). This was originally suspected to be
# Cloudflare edge-routing flakiness, observed to fail in bursts (e.g. 8/8
# retries failing together in one run) - but root-caused via live DNS
# testing to be LOCAL macOS resolver cache pollution on the dev machine
# used to build this, intermittently returning that bare origin IP instead
# of Cloudflare's. 20/20 real HTTPS calls from a Linux container (the
# ECS/Fargate production environment's actual OS) succeeded with zero SSL
# errors - this is not expected to reproduce in production. The retry loop
# below is kept as a harmless safety net (costs nothing on a clean
# resolver, and would still help if a transient real Cloudflare-side issue
# ever occurs) but is not itself the fix for the dev-machine symptom that
# motivated it - don't re-investigate this as a live Cloudflare edge issue
# without first checking the calling host's DNS resolution.
_TPEX_SSL_RETRY_ATTEMPTS = 8
_TPEX_SSL_RETRY_BACKOFF_SECONDS = 2.0


def _get_with_ssl_retry(url: str, *, headers: dict, timeout: float) -> httpx.Response:
    """GET with retry on transient SSL verification failure.

    Retries the exact same request (full verification, never relaxed) up
    to ``_TPEX_SSL_RETRY_ATTEMPTS`` times, waiting
    ``_TPEX_SSL_RETRY_BACKOFF_SECONDS`` between attempts — used for TPEx,
    whose CDN intermittently serves a cert chain that fails strict
    validation on one edge node but succeeds on the next. The backoff
    matters as much as the attempt count: retrying instantly tends to hit
    the same anycast route and thus the same bad edge repeatedly.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _TPEX_SSL_RETRY_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
            last_exc = exc
            logger.warning(
                "[TPEX] SSL verification failed (attempt %d/%d), retrying"
                " in %.0fs: %s",
                attempt, _TPEX_SSL_RETRY_ATTEMPTS,
                _TPEX_SSL_RETRY_BACKOFF_SECONDS, exc,
            )
            if attempt < _TPEX_SSL_RETRY_ATTEMPTS:
                time.sleep(_TPEX_SSL_RETRY_BACKOFF_SECONDS)
    raise last_exc


def _roc_to_gregorian_year(roc_year: int) -> int:
    """Convert an ROC (Minguo) calendar year to Gregorian."""
    return roc_year + 1911


def _parse_roc_date(value: str) -> datetime | None:
    """Parse a TWSE/TPEx ROC-calendar date string (YYYMMDD) to UTC midnight.

    Returns None if the value isn't a well-formed 7-digit ROC date.
    """
    if not value or not value.isdigit() or len(value) != 7:
        return None
    try:
        roc_year, month, day = int(value[:3]), int(value[3:5]), int(value[5:7])
        return datetime(
            _roc_to_gregorian_year(roc_year), month, day, tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _parse_roc_period(value: str) -> str | None:
    """Convert an ROC-calendar year-month string (YYYMM) to 'YYYY-MM'.

    Returns None if the value isn't a well-formed 5-digit ROC period.
    """
    if not value or not value.isdigit() or len(value) != 5:
        return None
    roc_year, month = int(value[:3]), int(value[3:5])
    return f"{_roc_to_gregorian_year(roc_year)}-{month:02d}"


def _parse_roc_time(value: str) -> str | None:
    """Parse an up-to-6-digit HHMMSS time string (not zero-padded) to 'HH:MM:SS'."""
    if not value or not value.isdigit():
        return None
    value = value.zfill(6)
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"


def _to_float(value: str) -> float | None:
    """Cast a TWSE/TPEx numeric-string field to float, or None if blank/invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _today_roc_date() -> str:
    """Return today's date (UTC) as a 7-digit ROC-calendar string (YYYMMDD)."""
    now = datetime.now(timezone.utc)
    return f"{now.year - 1911}{now.month:02d}{now.day:02d}"


def _check_freshness(output_date: str, source_label: str) -> bool:
    """Compare a TWSE/TPEx response's 出表日期 (report/output date) against
    today's actual date and log a warning if they don't match.

    TWSE/TPEx's revenue and material-announcement endpoints always return
    only the single latest snapshot (no date/period query param exists —
    verified against the live Swagger spec), so 出表日期 is the only signal
    that today's poll actually got a fresh response rather than a stale
    cache or a delayed publish. Confirmed live that 出表日期 equals the
    actual current date under normal operation.

    Returns:
        True if the response is fresh (matches today), False otherwise.
        Never raises — a malformed/missing output_date is treated as stale
        rather than crashing the fetch.
    """
    today = _today_roc_date()
    if output_date == today:
        return True
    logger.warning(
        "[%s] response output_date=%r does not match today=%r —"
        " data may be stale (TWSE/TPEx delayed publish, or a cached"
        " response)",
        source_label, output_date, today,
    )
    return False


def _to_int(value: str) -> int | None:
    """Cast a TWSE/TPEx numeric-string field to int, or None if blank/invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _fetch_one_revenue_dump(
    url: str, exchange: str, tickers: list[str], ticker_names: dict[str, str] | None = None,
) -> list[dict]:
    """Fetch one TWSE/TPEx monthly-revenue full-dump endpoint, filtered by ticker.

    Both TWSE (t187ap05_L) and TPEx (mopsfin_t187ap05_O) return an identical
    14-key Chinese-language schema, all values as strings, and no ticker
    query param — the full company roster is pulled every time and filtered
    client-side against ``tickers``.

    Args:
        url: Full-dump JSON endpoint URL.
        exchange: "TWSE" or "TPEx", stored in metadata and used to build a
            synthesized dedup URL (revenue rows have no natural article URL).
        tickers: Ticker codes to keep; rows for other companies are dropped.
        ticker_names: Known-correct English company name per ticker, from
            TAIWAN_TICKER_UNIVERSE (seed.py). Set directly as
            metadata.translated_company_name here rather than asking an
            LLM to translate 公司名稱 downstream - confirmed live that
            LLM translation of bare 2-4 character Taiwan company names
            produces serious errors (e.g. 2383 Elite Material
            mistranslated as "Taiwan Semiconductor Manufacturing
            Company"; 8210 Chenbro translated literally as "Diligence
            and sincerity"). We have the ground truth here; no reason to
            let a model guess it.

    Returns:
        List of article dicts with ``_pub_date`` set (last day of the
        reported period) and a synthesized ``url`` for dedup.
    """
    t0 = time.perf_counter()
    ticker_set = set(tickers)
    ticker_names = ticker_names or {}
    try:
        if exchange == "TPEx":
            resp = _get_with_ssl_retry(url, headers=_TWSE_TPEX_HEADERS, timeout=30.0)
        else:
            resp = httpx.get(url, headers=_TWSE_TPEX_HEADERS, timeout=30.0)
            resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.warning("[%s_REVENUE] failed: %s", exchange.upper(), exc)
        return []

    # 出表日期 (report/output date) is identical across every row in a
    # response — TWSE/TPEx always return a single current snapshot with no
    # date/period query param, so this is the only signal that today's poll
    # actually got fresh data rather than a stale cache or delayed publish.
    is_fresh = (
        _check_freshness(rows[0].get("出表日期", ""), f"{exchange.upper()}_REVENUE")
        if rows else True
    )

    results = []
    for row in rows:
        ticker = row.get("公司代號", "")
        if ticker not in ticker_set:
            continue
        period = _parse_roc_period(row.get("資料年月", ""))
        if not period:
            continue
        mom_pct = _to_float(row.get("營業收入-上月比較增減(%)", ""))
        yoy_pct = _to_float(row.get("營業收入-去年同月增減(%)", ""))
        remarks = row.get("備註", "")
        results.append({
            "title": (
                f"{row.get('公司名稱', ticker)} ({ticker}) {period} revenue:"
                f" {yoy_pct:+.1f}% YoY" if yoy_pct is not None
                else f"{row.get('公司名稱', ticker)} ({ticker}) {period} revenue"
            ),
            "url": f"{exchange.lower()}-revenue://{ticker}/{period}",
            "published": period,
            "source": exchange,
            "summary": None,
            "body": None,
            "_pub_date": datetime.strptime(period, "%Y-%m").replace(
                tzinfo=timezone.utc
            ),
            "metadata": {
                "ticker": ticker,
                "company_name": row.get("公司名稱"),
                "industry": row.get("產業別"),
                "period_gregorian": period,
                "revenue_current_month": _to_int(row.get("營業收入-當月營收", "")),
                "revenue_prior_month": _to_int(row.get("營業收入-上月營收", "")),
                "revenue_prior_year_month": _to_int(
                    row.get("營業收入-去年當月營收", "")
                ),
                "mom_pct": mom_pct,
                "yoy_pct": yoy_pct,
                "revenue_ytd": _to_int(row.get("累計營業收入-當月累計營收", "")),
                "revenue_ytd_prior_year": _to_int(
                    row.get("累計營業收入-去年累計營收", "")
                ),
                "ytd_yoy_pct": _to_float(
                    row.get("累計營業收入-前期比較增減(%)", "")
                ),
                "remarks": remarks if remarks and remarks != "-" else None,
                "exchange": exchange,
                "is_stale": not is_fresh,
                "source_category": "mops_revenue",
                "translated_company_name": ticker_names.get(ticker),
            },
        })
    logger.info(
        "[TIMER] %s_revenue url=%r matched=%d/%d elapsed=%.2fs fresh=%s",
        exchange.lower(), url, len(results), len(rows), time.perf_counter() - t0,
        is_fresh,
    )
    return results


def _fetch_twse_revenue(sources: list[dict]) -> list[dict]:
    """Fetch TWSE monthly revenue for tickers across all twse_revenue sources."""
    tickers: list[str] = []
    ticker_names: dict[str, str] = {}
    for source in sources:
        config = source.get("config") or {}
        tickers.extend(config.get("tickers", []))
        ticker_names.update(config.get("ticker_names", {}))
    if not tickers:
        return []
    return _fetch_one_revenue_dump(_TWSE_REVENUE_URL, "TWSE", tickers, ticker_names)


def _fetch_tpex_revenue(sources: list[dict]) -> list[dict]:
    """Fetch TPEx monthly revenue for tickers across all tpex_revenue sources."""
    tickers: list[str] = []
    ticker_names: dict[str, str] = {}
    for source in sources:
        config = source.get("config") or {}
        tickers.extend(config.get("tickers", []))
        ticker_names.update(config.get("ticker_names", {}))
    if not tickers:
        return []
    return _fetch_one_revenue_dump(_TPEX_REVENUE_URL, "TPEx", tickers, ticker_names)


# TWSE and TPEx material-announcement feeds use different key names for the
# same fields (TWSE: Chinese keys throughout; TPEx: English keys for
# ticker/company/date). This maps both onto one common field name.
_TWSE_MATERIAL_KEYS = {
    "output_date": "出表日期",
    "ticker": "公司代號",
    "company_name": "公司名稱",
    "subject": "主旨 ",  # trailing space is part of TWSE's actual key
}
_TPEX_MATERIAL_KEYS = {
    "output_date": "Date",
    "ticker": "SecuritiesCompanyCode",
    "company_name": "CompanyName",
    "subject": "主旨",
}


def _fetch_one_material_dump(
    url: str,
    exchange: str,
    tickers: list[str],
    key_map: dict[str, str],
    ticker_names: dict[str, str] | None = None,
) -> list[dict]:
    """Fetch one TWSE/TPEx material-announcements full-dump endpoint, filtered by ticker.

    Args:
        url: Full-dump JSON endpoint URL.
        exchange: "TWSE" or "TPEx".
        tickers: Ticker codes to keep; rows for other companies are dropped.
        key_map: Maps common field names to this exchange's actual JSON keys
            (TWSE and TPEx disagree on key names — see module-level constants).
        ticker_names: Known-correct English company name per ticker - see
            _fetch_one_revenue_dump's docstring for why this is set
            directly rather than left to an LLM translation step.

    Returns:
        List of article dicts with ``_pub_date`` set (statement date/time)
        and a synthesized ``url`` for dedup.
    """
    t0 = time.perf_counter()
    ticker_set = set(tickers)
    ticker_names = ticker_names or {}
    try:
        if exchange == "TPEx":
            resp = _get_with_ssl_retry(url, headers=_TWSE_TPEX_HEADERS, timeout=30.0)
        else:
            resp = httpx.get(url, headers=_TWSE_TPEX_HEADERS, timeout=30.0)
            resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.warning("[%s_MATERIAL] failed: %s", exchange.upper(), exc)
        return []

    # See _fetch_one_revenue_dump for why this check exists — same "always
    # latest snapshot, no date param" API shape applies here.
    is_fresh = (
        _check_freshness(
            rows[0].get(key_map["output_date"], ""), f"{exchange.upper()}_MATERIAL"
        )
        if rows else True
    )

    results = []
    for row in rows:
        ticker = row.get(key_map["ticker"], "")
        if ticker not in ticker_set:
            continue
        statement_date = _parse_roc_date(row.get("發言日期", ""))
        statement_time = _parse_roc_time(row.get("發言時間", ""))
        fact_date = _parse_roc_date(row.get("事實發生日", ""))
        company_name = row.get(key_map["company_name"], ticker)
        subject = row.get(key_map["subject"], "")
        date_key = (
            statement_date.strftime("%Y-%m-%d") if statement_date else "unknown"
        )
        results.append({
            "title": f"{company_name} ({ticker}): {subject}",
            "url": (
                f"{exchange.lower()}-material://{ticker}/{date_key}"
                f"/{row.get('發言時間', '0')}"
            ),
            "published": statement_date.isoformat() if statement_date else "",
            "source": exchange,
            "summary": _clean_summary(subject),
            "body": _clean_summary(row.get("說明", "") or ""),
            "_pub_date": statement_date,
            "metadata": {
                "ticker": ticker,
                "company_name": company_name,
                "disclosure_clause_code": row.get("符合條款"),
                "statement_date": (
                    statement_date.strftime("%Y-%m-%d") if statement_date else None
                ),
                "statement_time": statement_time,
                "fact_occurred_date": (
                    fact_date.strftime("%Y-%m-%d") if fact_date else None
                ),
                "exchange": exchange,
                "is_stale": not is_fresh,
                "source_category": "mops_material",
                "translated_company_name": ticker_names.get(ticker),
            },
        })
    logger.info(
        "[TIMER] %s_material url=%r matched=%d/%d elapsed=%.2fs fresh=%s",
        exchange.lower(), url, len(results), len(rows), time.perf_counter() - t0,
        is_fresh,
    )
    return results


def _fetch_twse_material(sources: list[dict]) -> list[dict]:
    """Fetch TWSE material announcements for tickers across all twse_material sources."""
    tickers: list[str] = []
    ticker_names: dict[str, str] = {}
    for source in sources:
        config = source.get("config") or {}
        tickers.extend(config.get("tickers", []))
        ticker_names.update(config.get("ticker_names", {}))
    if not tickers:
        return []
    return _fetch_one_material_dump(
        _TWSE_MATERIAL_URL, "TWSE", tickers, _TWSE_MATERIAL_KEYS, ticker_names,
    )


def _fetch_tpex_material(sources: list[dict]) -> list[dict]:
    """Fetch TPEx material announcements for tickers across all tpex_material sources."""
    tickers: list[str] = []
    ticker_names: dict[str, str] = {}
    for source in sources:
        config = source.get("config") or {}
        tickers.extend(config.get("tickers", []))
        ticker_names.update(config.get("ticker_names", {}))
    if not tickers:
        return []
    return _fetch_one_material_dump(
        _TPEX_MATERIAL_URL, "TPEx", tickers, _TPEX_MATERIAL_KEYS, ticker_names,
    )


# DART (Financial Supervisory Service) filing list + document body fetch.
# Covers Korea Signals spec Section 4's S2 (supply contract), S3 (capacity
# commitment), S4 (preliminary earnings), S5 (guidance disclosure), and S6
# (rumour adjudication) - all five live under DART's "I" (거래소공시/exchange
# disclosure) pblntf_ty category, since DART mirrors KRX-mandated
# disclosures rather than having a distinct structured endpoint per report
# type (confirmed 2026-09-22 against DART's own official pblntf_detail_ty
# taxonomy - no dedicated code exists for e.g. "supply contract"
# specifically). Report-type identification is therefore by matching
# report_nm text, not a query parameter.
#
# S6 was an open question (does DART carry the exchange's rumour-demand
# separately from the company's answer?) - resolved live 2026-09-22 against
# a real SK Hynix example (corp_code 00164779, rcept_no 20260821800214 /
# 20260821800524): YES, DART carries both as distinct filings, and flr_nm
# distinguishes them (exchange = "유가증권시장본부", company = the ticker's
# own name). The precision rule 5.6 needs ("hours between the two") is NOT
# available from list.json's rcept_dt (date-only, no time component) - both
# filings showed the same date. It IS recoverable, but only from inside the
# ANSWER filing's document body, which restates the original demand time as
# free text, e.g. "거래소의 조회요구(2026년 08월 21일 11:35)에 따른
# 공시사항임". Extracting that timestamp from body text is a downstream
# parsing task (signal-detection-agent), not done here - this fetcher's job
# is only to ensure both filings, bodies included, reach storage (see
# "조회공시" in _DART_TARGET_REPORT_PATTERNS below).
#
# S1 (export data) is NOT covered here - separate source (Korea Customs).
_DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

# Substrings matched against report_nm (DART's filing title) to decide which
# filings are worth a full document-body fetch. Matched as "contains", not
# exact-equals, since real report_nm values append suffixes (e.g. a
# correction: "...체결정정"). Left un-narrowed beyond this for now - false
# positives here cost one extra document fetch, not a wrong classification
# (classification itself is signal-detection-agent's job, not fetched here).
_DART_TARGET_REPORT_PATTERNS = [
    "단일판매",       # S2 - single-sale/supply contract conclusion
    "공급계약",       # S2 - supply contract (alternate phrasing)
    "시설투자",       # S3 - facility/capacity investment
    "유형자산",       # S3 - tangible asset acquisition (equipment purchases)
    "잠정",           # S4 - preliminary earnings. Confirmed live 2026-09-23
                      # the real report_nm is
                      # "연결재무제표기준영업(잠정)실적(공정공시)" - "(잠정)"
                      # sits as a bracketed qualifier INSIDE the compound
                      # word, not concatenated as a single
                      # "잠정실적"/"잠정영업실적" substring. The two
                      # previous patterns here never matched a single real
                      # filing (verified: 14 real S4 filings in stored
                      # data, all fetched only because "공정공시" below
                      # also matched their same title) - this fixes the
                      # dead patterns rather than leaving them as
                      # harmless-looking but non-functional dead code.
    "공정공시",       # S5 - fair disclosure (voluntary guidance)
    "조회공시",       # S6 - rumour adjudication (both the exchange's demand
                      # and the company's answer use this term; confirmed
                      # live 2026-09-22 both filings are needed - the
                      # precise demand timestamp is NOT in list.json's
                      # rcept_dt (date-only), it's embedded as text inside
                      # the ANSWER filing's body, e.g. "거래소의 조회요구
                      # (2026년 08월 21일 11:35)" - so both filings' bodies
                      # must be fetched, not just the answer's.
    "해명",           # S6-adjacent - 자율적 해명공시 (voluntary clarification
                      # disclosure), report_nm "풍문또는보도에대한해명" - a
                      # DISTINCT mechanism from 조회공시 confirmed via
                      # research 2026-09-23: introduced by KRX effective
                      # 2015-09-07, this is COMPANY-initiated (a company
                      # clarifying a rumor on its own, without the
                      # exchange demanding it), unlike 조회공시 which is
                      # exchange-compelled. Real examples found live
                      # (SK Hynix 2026-07-22 and 2026-09-04, Samsung
                      # Electronics 2026-07-23) had NO body fetched before
                      # this pattern was added, since "해명" shares no
                      # substring with "조회공시" - classified separately
                      # in signal-detection-agent
                      # (classify_voluntary_clarification), not folded
                      # into the exchange-demand rule.
]

_dart_rate_lock = threading.Lock()
_dart_last_call = [0.0]
_DART_MIN_INTERVAL = 0.25  # conservative pending confirmation of DART's actual rate limit


def _dart_rate_sleep() -> None:
    with _dart_rate_lock:
        elapsed = time.monotonic() - _dart_last_call[0]
        if elapsed < _DART_MIN_INTERVAL:
            time.sleep(_DART_MIN_INTERVAL - elapsed)
        _dart_last_call[0] = time.monotonic()


def _dart_matches_target_report(report_nm: str) -> bool:
    return any(pattern in report_nm for pattern in _DART_TARGET_REPORT_PATTERNS)


def _fetch_dart_document_body(corp_code: str, rcept_no: str, api_key: str) -> str | None:
    """Fetch and extract plain text from a DART filing's document.xml.

    Despite the .xml filename/extension, the member DART actually zips is
    XForms-flavored HTML (confirmed live 2026-09-22: content starts with
    "<html><head>...charset=euc-kr"), not well-formed XML - a strict XML
    parser fails on it (unescaped "&", mismatched/unclosed tags are normal
    in real filings). Stripped the same way sec_edgar.py's
    fetch_filing_text() handles SEC's HTML filings: drop script/style
    blocks, strip tags, unescape entities.

    The declared "charset=euc-kr" meta tag is WRONG - confirmed live by
    decoding the raw bytes both ways: euc-kr produces mojibake on every
    Korean character, utf-8 produces correct readable Korean (e.g. the
    font-name string decodes cleanly as "돋움체" under utf-8, garbage under
    euc-kr). This is a stale/incorrect header on DART's side, not
    something to infer from - decode as utf-8 regardless of what the
    document claims.

    Returns None on any failure - callers treat a missing body as "not yet
    fetched", not an error, same fail-open convention as the rest of this
    pipeline.
    """
    import zipfile
    from io import BytesIO

    _dart_rate_sleep()
    try:
        resp = httpx.get(
            _DART_DOCUMENT_URL,
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=30.0,
        )
        resp.raise_for_status()
        # On failure DART returns a small XML error envelope instead of a
        # zip - confirmed live 2026-09-23 (status "014", message "파일이
        # 존재하지 않습니다"/file does not exist) for a [첨부정정]
        # (attachment-correction) filing, which apparently has no document
        # body of its own to fetch. Checked explicitly before attempting
        # to unzip so this fails with the real reason, not a misleading
        # "not a zip file" error that gives no clue what actually happened.
        if resp.content[:5] != b"PK\x03\x04" and b"<status>" in resp.content[:200]:
            logger.warning(
                "[DART] document.xml returned an error envelope for"
                " rcept_no=%s (not a zip) - body: %r",
                rcept_no, resp.content[:200],
            )
            return None
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            # DART zips a single member per filing; name varies (usually
            # "{rcept_no}.xml" but not guaranteed), so take whichever
            # member is present rather than assuming a fixed filename
            # (unlike corpCode.xml's fixed CORPCODE.xml).
            names = zf.namelist()
            if not names:
                return None
            raw = zf.read(names[0])
        decoded = raw.decode("utf-8", errors="replace")
        stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", decoded, flags=re.S | re.I)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        stripped = html.unescape(stripped)
        return re.sub(r"\s+", " ", stripped).strip() or None
    except Exception as exc:
        logger.warning(
            "[DART] document fetch failed corp_code=%s rcept_no=%s error=%s",
            corp_code, rcept_no, exc,
        )
        return None


def _fetch_one_dart_filing_list(
    corp_code: str,
    stock_code: str,
    company_name: str,
    api_key: str,
    bgn_de: str,
    end_de: str,
) -> list[dict]:
    """Fetch DART's filing list for one company over a date range.

    Returns article dicts with a synthetic url (dart-filing://corp_code/
    rcept_no) so the DB's existing global-unique-url dedup applies without
    any DART-specific dedup logic. Full document body is fetched only for
    report_nm values matching _DART_TARGET_REPORT_PATTERNS.
    """
    _dart_rate_sleep()
    try:
        resp = httpx.get(
            _DART_LIST_URL,
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": "I",
                "page_count": 100,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[DART] list fetch failed corp_code=%s error=%s", corp_code, exc)
        return []

    # DART returns status "013" (no data) as a normal empty result, not an
    # error - only log/skip other non-success codes.
    status = data.get("status")
    if status not in ("000", "013"):
        logger.warning(
            "[DART] list fetch corp_code=%s status=%s message=%s",
            corp_code, status, data.get("message"),
        )
    filings = data.get("list") or []

    results = []
    for filing in filings:
        report_nm = filing.get("report_nm", "")
        rcept_no = filing.get("rcept_no", "")
        rcept_dt = filing.get("rcept_dt", "")
        pub_date = (
            datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=timezone.utc)
            if rcept_dt else None
        )
        body = (
            _fetch_dart_document_body(corp_code, rcept_no, api_key)
            if _dart_matches_target_report(report_nm) else None
        )
        results.append({
            "title": f"{company_name} ({stock_code}): {report_nm}",
            "url": f"dart-filing://{corp_code}/{rcept_no}",
            "published": rcept_dt,
            "source": filing.get("flr_nm") or "DART",
            "summary": None,
            "body": body,
            "_pub_date": pub_date,
            "metadata": {
                "corp_cls": filing.get("corp_cls"),
                "corp_code": corp_code,
                "stock_code": stock_code,
                "rcept_no": rcept_no,
                "rm": filing.get("rm"),
                "pblntf_ty": "I",
                "source_category": "dart_filing",
            },
        })
    return results


def _fetch_dart_filing(sources: list[dict], days_back: int, api_key: str) -> list[dict]:
    """Fetch DART filings for all companies across all dart_filing sources.

    Resolves stock_code -> corp_code once (cached process-lifetime by
    dart_corp_code), then queries the filing list per company. Companies
    with no resolvable corp_code (e.g. an unlisted entity with no
    stock_code at all) are skipped with a warning, not an error - matches
    KOREA_TICKER_UNIVERSE's Hanwha Semitech entry, which is intentionally
    absent from every dart_filing source's ticker config for this reason.
    """
    tickers: list[dict[str, str]] = []
    for source in sources:
        config = source.get("config") or {}
        tickers.extend(config.get("companies", []))
    if not tickers:
        return []

    stock_codes = [t["ticker"] for t in tickers]
    corp_code_map = resolve_corp_codes(stock_codes, api_key)

    bgn_de = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d")
    end_de = datetime.now(timezone.utc).strftime("%Y%m%d")

    articles: list[dict] = []
    for t in tickers:
        stock_code = t["ticker"]
        corp_code = corp_code_map.get(stock_code)
        if not corp_code:
            logger.warning("[DART] skipping stock_code=%s - no corp_code resolved", stock_code)
            continue
        articles.extend(
            _fetch_one_dart_filing_list(
                corp_code, stock_code, t["company"], api_key, bgn_de, end_de,
            )
        )
    return articles


# Korea Customs Service export-figure press-release scraper (S1 - export
# surprise). Fallback for the official data.go.kr 10-day provisional
# export-statistics API (dataset 15157908), which requires a personal
# account gated behind Korea's phone/ARC-linked identity verification - not
# obtainable without a Korean-resident proxy. This scrapes the same
# underlying figure from Korea Customs' own public press-release board
# instead, which needs no login at all.
#
# Confirmed live 2026-09-23: no RSS feed exists for this board, and post
# IDs (nttSn) are a global auto-increment across ~6,600+ unrelated posts
# (drug busts, personnel notices, etc.) - not usable as a date-based
# pattern. The only reliable way to find the newest release is the
# board's own server-side search, which is a POST (not GET query params -
# a GET-param guess 404'd first), with the recurring report family
# isolated by searching the title (searchType=sj) for "수출입 현황".
_CUSTOMS_LIST_URL = "https://www.customs.go.kr/kcs/na/ntt/selectNttList.do"
_CUSTOMS_INFO_URL = "https://www.customs.go.kr/kcs/na/ntt/selectNttInfo.do"
_CUSTOMS_BBS_ID = "1362"
_CUSTOMS_MI = "2891"
_CUSTOMS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_CUSTOMS_LIST_PAGE_MAX_ATTEMPTS = 3
_CUSTOMS_LIST_PAGE_RETRY_BACKOFF_SECS = 2.0

# Confirmed live 2026-09-23 against real posts: the 10-day/20-day
# preliminary releases only ever state the semiconductor figure as a
# dollar value plus a superlative record/streak claim - e.g.
# "반도체(341억 달러) 수출 동기간 역대최대" (semiconductor exports of
# $34.1bn, a period record) - never a year-over-year percentage or a
# share-of-total-exports percentage in the page's own HTML text (checked
# every occurrence of "반도체" on a real 20-day release page, found
# exactly one, matching this pattern; also searched for "차지" - the verb
# used for "share of" - and found zero matches). The YoY% Section 5.1
# needs is therefore NOT available from the source at 10-day granularity
# and must be computed by this pipeline itself, from its own stored
# history of these dollar figures - matching the doc's own build note
# that this rule needs two years of history before it means anything.
#
# "억" is a Korean numeral unit = 100,000,000 (one hundred million) - "341
# 억" is not a typo/OCR artifact, it is standard Korean notation for large
# won/dollar figures and must be multiplied out, not read digit-by-digit.
# Confirmed live 2026-09-23 against real historical posts (backfill
# verification): the bracketed semiconductor figure is stated as either
# "반도체(341억 달러)" (10-day/20-day releases) or "반도체 수출(468억 달러)"
# (monthly confirmed releases - an extra "수출"/export word inserted
# between 반도체 and the parenthesis) - both real phrasings, not a typo in
# one of them. The optional "(?:수출)?" covers both without a second
# pattern.
_CUSTOMS_SEMICONDUCTOR_PATTERN = re.compile(
    r"반도체\s*(?:수출)?\s*\(\s*([\d,]+)\s*억\s*달러\s*\)"
)
_CUSTOMS_PERIOD_PATTERN = re.compile(
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(?:~|-)\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*수출입\s*현황"
)
# Monthly CONFIRMED release title, e.g. "2026년 8월 월간 수출입 현황
# [확정치]" - distinct from the day-range pattern above (no day numbers,
# has "월간"/monthly) and from the monthly PROVISIONAL title (same month
# number but no "월간" word, e.g. "2026년 8월 수출입 현황 [잠정치]" -
# confirmed live this provisional monthly variant has no bracketed
# semiconductor figure in extractable form, so it is deliberately NOT
# matched by this pattern nor produced by classify_export_surprise's
# period grouping - see _classify_customs_period_type's own docstring).
_CUSTOMS_MONTHLY_CONFIRMED_PERIOD_PATTERN = re.compile(
    r"(\d{4})년\s*(\d{1,2})월\s*월간\s*수출입\s*현황\s*\[\s*확정치\s*\]"
)
# Confirmed live: only the monthly CONFIRMED release states a real YoY%
# in its own body text ("전년 동월 대비 수출은 68.7% 증가") - 10-day/20-day
# releases never do (checked live, see module comment on
# _CUSTOMS_SEMICONDUCTOR_PATTERN's own history). This is the TOTAL export
# YoY%, not semiconductor-specific - used only as a cross-check value,
# never as classify_export_surprise's own computed semiconductor YoY
# (which is always computed by this pipeline from its own stored history,
# per spec Section 5.1's own design intent).
_CUSTOMS_YOY_PATTERN = re.compile(
    r"전년\s*동월\s*대비\s*수출\s*은?\s*([\d.]+)\s*%\s*증가"
)
# Confirmed live 2026-09-23 against a real May 2026 monthly CONFIRMED
# post that had NO bracketed dollar figure at all (unlike June/July/
# August's same-type posts, which do - real inconsistency between
# individual releases, not a parsing gap): this same post instead states
# a real, SEMICONDUCTOR-SPECIFIC (not total-export) YoY% series, e.g.
# "반도체 전년동월대비 증감률(%): ['25.10월] 25.2 → [11월] 38.7 → ... →
# [5월] 167.7" - a genuinely better data point than the dollar figure for
# S1's own purposes (it's already the exact YoY comparison Section 5.1
# needs, semiconductor-specific, and it comes with several trailing
# months embedded in the same sentence). Captures everything after the
# label up to the next "*"-prefixed series (the next line is always a
# different product's own series, e.g. "승용차"/passenger cars) or end of
# string.
_CUSTOMS_SEMI_YOY_SERIES_HEADER_PATTERN = re.compile(
    r"반도체\s*전년동월대비\s*증감률\s*\(%\)\s*:\s*(.+?)(?:\*|$)"
)
# One entry in that series: "['25. 10월] 25.2" or "[11월] 38.7" (year
# omitted when unchanged from the previous entry - real behavior
# confirmed live, not every entry restates it) with an optional "△"
# prefix meaning negative (a real minus sign glyph used throughout this
# board's tables, confirmed live on the same page's "승용차" series
# showing "△12.6" for an actual year-on-year decline). The apostrophe
# before the 2-digit year is a RIGHT SINGLE QUOTATION MARK (U+2019, "'"),
# not an ASCII apostrophe (confirmed live via direct byte inspection of a
# real fetched page - a plain "'?" silently matched nothing here and made
# every entry in a real series fail to parse, since the year group never
# matched at all). Both accepted, in case a straight apostrophe appears
# in some other real post never checked.
_CUSTOMS_SEMI_YOY_SERIES_ENTRY_PATTERN = re.compile(
    r"\[\s*(?:['’]?(\d{2})\.\s*)?(\d{1,2})\s*월\s*\]\s*(△?)\s*([\d.]+)"
)


def _fetch_customs_list_page(page: int) -> list[dict]:
    """Return every '수출입 현황' post on one page of the board's title
    search results (confirmed live 2026-09-23: ~10 posts/page, 47 total
    pages at the time of checking - real history reaching back through at
    least mid-2025, likely further).

    Post links are JS-driven (href="javascript:"), not real <a href>
    URLs - the real post identifiers live in data-id (nttSn) and
    data-url (nttSnUrl) attributes on the same anchor tag, alongside its
    title attribute, filtered to the nttInfoBtn class used for this
    board's title links specifically. Returns [] after
    ``_CUSTOMS_LIST_PAGE_MAX_ATTEMPTS`` failed attempts - fail-open, same
    convention as every other fetcher in this module, but retried first:
    confirmed live this board can return a transient "server disconnected"
    error on an otherwise-real, non-empty page (seen during backfill
    verification) - without a retry, that transient error is
    indistinguishable from "this page is genuinely past the end of
    results" to fetch_customs_export_backfill's own stopping condition,
    which would silently truncate a real backfill run short.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _CUSTOMS_LIST_PAGE_MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(
                _CUSTOMS_LIST_URL,
                data={
                    "bbsId": _CUSTOMS_BBS_ID,
                    "mi": _CUSTOMS_MI,
                    "searchType": "sj",
                    "searchValue": "수출입 현황",
                    "currPage": str(page),
                },
                headers={"User-Agent": _CUSTOMS_USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _CUSTOMS_LIST_PAGE_MAX_ATTEMPTS:
                logger.warning(
                    "[CUSTOMS] list fetch attempt %d/%d failed page=%d, retrying: %s",
                    attempt, _CUSTOMS_LIST_PAGE_MAX_ATTEMPTS, page, exc,
                )
                time.sleep(_CUSTOMS_LIST_PAGE_RETRY_BACKOFF_SECS)
    else:
        logger.warning(
            "[CUSTOMS] list fetch failed page=%d after %d attempts: %s",
            page, _CUSTOMS_LIST_PAGE_MAX_ATTEMPTS, last_exc,
        )
        return []

    return [
        {"ntt_sn": ntt_sn, "ntt_url": ntt_url, "title": html.unescape(title)}
        for ntt_sn, ntt_url, title in re.findall(
            r'data-id="(\d+)"\s+data-url="([a-f0-9]+)"\s+class="nttInfoBtn"'
            r'\s+title="([^"]+)"',
            resp.text,
        )
    ]


def _fetch_customs_newest_post(days_back: int) -> dict | None:
    """Find the newest '수출입 현황' post via the board's title search
    (page 1's first result - confirmed live the board lists newest-first).

    Returns {"ntt_sn": str, "ntt_url": str, "title": str} for the newest
    matching post, or None on any failure - fail-open, same convention as
    every other fetcher in this module.
    """
    posts = _fetch_customs_list_page(1)
    if not posts:
        logger.warning("[CUSTOMS] no matching post found in search results")
        return None
    return posts[0]


def _classify_customs_period_type(title: str) -> tuple[str, dict[str, Any]] | None:
    """Classify a real Customs board title into one of the THREE period
    types Korea Signals spec Section 5.1 actually asks for ("days 1-10,
    days 1-20, or full month") - returns (period_type, fields) or None if
    the title doesn't match any of the three.

    Confirmed live 2026-09-23 against real historical titles: at least 5
    distinct title shapes exist on this board, not 3 - a monthly
    PROVISIONAL release (e.g. "2026년 8월 수출입 현황 [잠정치]", no "월간"
    word) that has no bracketed semiconductor figure in extractable plain
    text, and a "기업규모별" (by company size) report that doesn't mention
    semiconductors at all. Both are deliberately NOT matched here -
    returning None for them, not a guessed period_type - since forcing
    them into one of the three real types would either silently produce
    a NULL semiconductor value or double-count a period already covered
    by the monthly CONFIRMED release for the same month.

    period_type is one of "10day", "20day", "monthly" - "monthly" always
    refers to the CONFIRMED release specifically (the only monthly
    variant this function ever returns), never the provisional one.
    """
    day_range = _CUSTOMS_PERIOD_PATTERN.search(title)
    if day_range:
        y1, m1, d1, y2, m2, d2 = day_range.groups()
        y2 = y2 or y1
        period_start = f"{y1}-{int(m1):02d}-{int(d1):02d}"
        period_end = f"{y2}-{int(m2):02d}-{int(d2):02d}"
        period_type = "10day" if int(d2) <= 10 else "20day"
        return period_type, {"period_start": period_start, "period_end": period_end}

    monthly = _CUSTOMS_MONTHLY_CONFIRMED_PERIOD_PATTERN.search(title)
    if monthly:
        y, m = monthly.groups()
        # A full-month period's "end" is the month's own last day - not
        # computed exactly here (would need real per-month day counts,
        # leap years); the first day of the NEXT month minus one day is
        # unnecessary precision for what published/period_end are used
        # for downstream (grouping/sorting by month, not exact-day math),
        # so period_end is left as the month's first day too, distinguished
        # from period_start only by period_type="monthly" - a caller
        # needing the real last day should derive it from period_type,
        # not assume period_end is that day.
        period_start = f"{y}-{int(m):02d}-01"
        return "monthly", {"period_start": period_start, "period_end": period_start}

    return None


def _parse_customs_semi_yoy_series(text: str) -> dict[str, float]:
    """Parse the semiconductor-specific YoY% trailing series (see
    _CUSTOMS_SEMI_YOY_SERIES_HEADER_PATTERN's own docstring for a real
    example) into {"YYYY-MM": pct, ...}.

    A year digit is only restated in the source when it changes from the
    previous entry (confirmed live: "['25.10월] 25.2 → [11월] 38.7" - Nov
    doesn't repeat '25) - carried forward here from the last entry that
    DID state one. An entry appearing before any year has been stated at
    all is skipped (can't anchor it to a real year) rather than guessed.
    """
    header = _CUSTOMS_SEMI_YOY_SERIES_HEADER_PATTERN.search(text)
    if not header:
        return {}
    series: dict[str, float] = {}
    current_year: int | None = None
    for year_suffix, month, sign, value in _CUSTOMS_SEMI_YOY_SERIES_ENTRY_PATTERN.findall(
        header.group(1)
    ):
        if year_suffix:
            current_year = 2000 + int(year_suffix)
        if current_year is None:
            continue
        try:
            pct = float(value)
        except ValueError:
            continue
        if sign == "△":
            pct = -pct
        series[f"{current_year}-{int(month):02d}"] = pct
    return series


def _extract_customs_figures(text: str) -> dict[str, Any]:
    """Pull the semiconductor export figure, the semiconductor-specific
    YoY% series (if present - monthly CONFIRMED releases only, and not
    even every one of those, see _CUSTOMS_SEMI_YOY_SERIES_HEADER_PATTERN's
    own docstring), and the total-export YoY% cross-check value (see
    _CUSTOMS_YOY_PATTERN's own docstring for why this is never used as
    classify_export_surprise's own computed YoY) out of a Customs post's
    plain-text body.

    Returns {} if NEITHER the dollar figure NOR the YoY series was found -
    a real, expected outcome for some post shapes (see
    _classify_customs_period_type's own docstring), not treated as an
    error by any caller. A post with the series but no dollar figure (the
    real May/April/March/Feb/Jan 2026 monthly examples found during
    backfill verification) still returns real data via the series alone -
    _build_customs_article's own "no semiconductor figure" check looks
    for either field, not just the dollar one.
    """
    fields: dict[str, Any] = {}
    semi_match = _CUSTOMS_SEMICONDUCTOR_PATTERN.search(text)
    if semi_match:
        fields["semiconductor_export_usd_billion"] = (
            int(semi_match.group(1).replace(",", "")) / 10.0
        )
    semi_yoy_series = _parse_customs_semi_yoy_series(text)
    if semi_yoy_series:
        fields["semiconductor_yoy_pct_series"] = semi_yoy_series
        # The series' own last entry is this release's own period - a
        # direct, stated semiconductor YoY%, not the total-export one
        # _CUSTOMS_YOY_PATTERN captures.
        fields["semiconductor_yoy_pct_stated"] = semi_yoy_series[max(semi_yoy_series)]
    yoy_match = _CUSTOMS_YOY_PATTERN.search(text)
    if yoy_match:
        try:
            fields["total_export_yoy_pct_stated"] = float(yoy_match.group(1))
        except ValueError:
            pass
    return fields


def _fetch_customs_post_body(ntt_sn: str, ntt_url: str) -> str | None:
    """Fetch and clean one Customs board post's body text. Returns None on
    any failure - fail-open, same convention as every other fetcher here.

    Strips the per-word <span> fragments the HWP-to-HTML export wraps
    every few characters in - confirmed live these break a direct regex
    against the raw HTML, so tags must be stripped and whitespace
    collapsed first, same pattern as sec_edgar.py's HTML handling.
    """
    try:
        resp = httpx.get(
            _CUSTOMS_INFO_URL,
            params={"mi": _CUSTOMS_MI, "bbsId": _CUSTOMS_BBS_ID, "nttSn": ntt_sn, "nttSnUrl": ntt_url},
            headers={"User-Agent": _CUSTOMS_USER_AGENT},
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("[CUSTOMS] post fetch failed ntt_sn=%s: %s", ntt_sn, exc)
        return None
    text = re.sub(r"<[^>]+>", " ", resp.text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _build_customs_article(post: dict, text: str) -> dict | None:
    """Build one article dict from a Customs post's title + cleaned body,
    or None if the title isn't one of the three period types
    classify_export_surprise needs (_classify_customs_period_type) or
    NEITHER a semiconductor dollar figure NOR a semiconductor YoY% series
    was found in the body (_extract_customs_figures) - both real, expected
    outcomes for some post shapes, not errors.

    Shared by both the newest-only fetch (_fetch_customs_export_data) and
    the historical backfill (_fetch_customs_export_backfill) - one place
    defining what makes a post into a storable article, so the two
    fetchers can never silently diverge on that definition.
    """
    period_info = _classify_customs_period_type(post["title"])
    if period_info is None:
        return None
    period_type, period_fields = period_info

    figures = _extract_customs_figures(text)
    if not ({"semiconductor_export_usd_billion", "semiconductor_yoy_pct_stated"} & figures.keys()):
        logger.warning(
            "[CUSTOMS] no semiconductor figure or YoY series found in post ntt_sn=%s title=%r",
            post["ntt_sn"], post["title"],
        )
        return None

    period_end = period_fields["period_end"]
    pub_date = None
    try:
        pub_date = datetime.strptime(period_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pub_date = None

    return {
        "title": post["title"],
        "url": f"kr-customs-export://semiconductor/{post['ntt_sn']}",
        "published": period_end,
        "source": "Korea Customs Service",
        "summary": None,
        "body": text[:5000],
        "_pub_date": pub_date,
        "metadata": {
            "ntt_sn": post["ntt_sn"],
            "period_type": period_type,
            **period_fields,
            **figures,
            "source_category": "kr_customs_export",
        },
    }


def _fetch_customs_export_data(sources: list[dict], days_back: int) -> list[dict]:
    """Fetch the newest Korea Customs semiconductor export figure.

    Only produces an article for the newest 10-day/20-day/monthly release
    found - this is the going-forward path the 4-hourly schedule runs
    every poll; historical backfill is a SEPARATE, one-time fetcher
    (_fetch_customs_export_backfill) - see that function's own docstring
    for why a real 2-year backfill turned out to be reachable through
    this same no-login board after all (confirmed live 2026-09-23,
    reversing this comment's own earlier claim that no backfill existed).

    url is deliberately keyed on ntt_sn (the post's own unique board ID),
    not on period alone - a distinct real post exists per release, so
    this is a natural, already-unique dedup key without needing to invent
    a period+revision scheme.
    """
    post = _fetch_customs_newest_post(days_back)
    if post is None:
        return []
    text = _fetch_customs_post_body(post["ntt_sn"], post["ntt_url"])
    if text is None:
        return []
    article = _build_customs_article(post, text)
    return [article] if article else []


# ~2 years of history at 3 releases/month (10-day + 20-day + monthly) plus
# the 2 non-target report shapes each month (monthly provisional,
# 기업규모별) that also appear in this same title search - confirmed live
# 2026-09-23 that ~5 posts/month appear across all shapes, so 2 years
# needs roughly 120 posts / ~10 posts-per-page = ~12 pages minimum;
# doubled for margin since real page density varies (some months had more
# report variants than others in the pages actually checked).
_CUSTOMS_BACKFILL_MAX_PAGES = 30
# Confirmed live 2026-09-23: this board's detail pages genuinely stop
# including inline breakdown text at some point in its history (March
# 2026 in the specific run checked) - everything older is a stub page
# linking to a .hwpx/.pdf attachment this scraper never opens. A real,
# permanent content-format boundary, not a transient gap - once a real
# run crosses it, every earlier post will also fail the same way, so
# there's no reason to keep walking further pages after a solid run of
# consecutive misses among otherwise-target-type posts. 4 is a small
# margin above 1 (a single miss could still be one of the OTHER real
# gaps this module already accepts - a genuinely missing figure on one
# real post, a transient fetch failure already retried and still failed)
# without walking dozens of pointless pages once the real boundary is
# crossed.
_CUSTOMS_BACKFILL_STOP_AFTER_CONSECUTIVE_MISSES = 4


def fetch_customs_export_backfill(max_pages: int = _CUSTOMS_BACKFILL_MAX_PAGES) -> list[dict]:
    """One-time historical backfill for korea_market_signal's
    kr_customs_export source - walks the SAME title-search board
    _fetch_customs_export_data already polls going forward, but paginates
    through it instead of only ever reading page 1's first match.

    Confirmed live 2026-09-23: this board's own title search already
    returns full pagination (~10 posts/page, 47 total pages at the time of
    checking) with no login or Korean identity verification required at
    all - directly reversing the earlier finding (recorded in
    KOREA_CUSTOMS_EXPORT_SOURCE's own seed.py comment, now stale) that
    "this scraper only ever sees whatever's newest right now" and that S1
    was therefore permanently out of scope. HOWEVER, also confirmed live:
    the board's own detail-page FORMAT changed at some point in its own
    history (March 2026, in the specific run checked) - posts from that
    point forward embed the full breakdown (including, for monthly
    CONFIRMED releases, a real semiconductor-specific YoY% series - see
    _extract_customs_figures) directly in the page's own HTML; everything
    older is a stub page linking to a .hwpx/.pdf attachment this scraper
    never opens. This means REAL backfillable depth today is roughly 7
    months (March-September 2026), not the full 2 years Section 5.1's own
    build note asks for - genuinely short of the 12 EQUIVALENT periods
    (12 prior same-period-type readings) that rule needs before it's
    computable, so a real first classification still needs several more
    months of the existing 4-hourly poll's own organic growth on top of
    this backfill, not an immediate fix. This function stops itself once
    it detects that older-format boundary (see
    _CUSTOMS_BACKFILL_STOP_AFTER_CONSECUTIVE_MISSES) rather than walking
    dozens of pages that can only ever return stub pages past that point.

    The existing 4-hourly scheduled fetch (_fetch_customs_export_data)
    still only reads page 1 - this function is a SEPARATE, one-time (or
    manually re-run) call, not part of that regular poll.

    Stops after ``max_pages`` (a real page limit, not a date-based one -
    the board has no date filter on this search, only pagination), as
    soon as a page returns zero posts (end of results), or once the
    older-format boundary is detected (see above) - whichever comes
    first. Not stopped by encountering an already-stored URL - unlike the
    regular fetch, a one-time backfill run is expected to see mostly-new
    URLs throughout, and stopping early on the first repeat would risk
    missing genuine gaps if pages are ever returned out of strict
    chronological order (not confirmed either way - safer to walk every
    page up to whichever real stopping condition fires first).

    Returns article dicts in the same shape _fetch_customs_export_data
    produces (via the same shared _build_customs_article) - posts that
    aren't one of the three target period types, or have no extractable
    semiconductor figure, are silently skipped (see
    _classify_customs_period_type / _extract_customs_figures's own
    docstrings for why that's a real, expected outcome, not an error).
    """
    articles: list[dict] = []
    skipped_period_type = 0
    skipped_no_figure = 0
    skipped_fetch_failed = 0
    consecutive_no_figure = 0

    for page in range(1, max_pages + 1):
        posts = _fetch_customs_list_page(page)
        if not posts:
            logger.info("[CUSTOMS_BACKFILL] page=%d empty, stopping", page)
            break
        for post in posts:
            period_info = _classify_customs_period_type(post["title"])
            if period_info is None:
                skipped_period_type += 1
                continue
            text = _fetch_customs_post_body(post["ntt_sn"], post["ntt_url"])
            if text is None:
                skipped_fetch_failed += 1
                continue
            article = _build_customs_article(post, text)
            if article is None:
                skipped_no_figure += 1
                consecutive_no_figure += 1
                if consecutive_no_figure >= _CUSTOMS_BACKFILL_STOP_AFTER_CONSECUTIVE_MISSES:
                    logger.info(
                        "[CUSTOMS_BACKFILL] %d consecutive target-type posts with no"
                        " extractable figure - stopping (this board's detail-page"
                        " format changed at some point in its history; confirmed"
                        " live 2026-09-23 that posts before March 2026 are stub"
                        " pages linking to a .hwpx/.pdf attachment this scraper"
                        " never opens, not a parsing bug)",
                        consecutive_no_figure,
                    )
                    return articles
                continue
            consecutive_no_figure = 0
            articles.append(article)

    logger.info(
        "[CUSTOMS_BACKFILL] pages_walked<=%d articles=%d skipped_period_type=%d"
        " skipped_no_figure=%d skipped_fetch_failed=%d",
        max_pages, len(articles), skipped_period_type, skipped_no_figure,
        skipped_fetch_failed,
    )
    return articles


def _fetch_articles(
    sources: list[dict],
    days_back: int,
    max_articles: int,
    serpapi_key: str | None = None,
    newsapi_key: str | None = None,
    alpha_vantage_key: str | None = None,
    universe_url: str | None = None,
    universe_api_key: str | None = None,
    dart_api_key: str | None = None,
    domain_slug: str = "",
) -> list[dict]:
    """Fetch articles from all sources, routing by source_type.

    Args:
        sources: List of source dicts (RSS, SerpAPI, NewsAPI, Alpha Vantage,
            Federal Register, and/or GDELT).
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles; 0 means no limit.
        serpapi_key: SerpAPI API key; SerpAPI sources are skipped if None.
        newsapi_key: NewsAPI API key; NewsAPI sources are skipped if None.
        alpha_vantage_key: Alpha Vantage API key; AV sources are skipped if None.
        universe_url: research-universe base URL for dynamic ticker fetching.
        universe_api_key: Service API key (ru_ prefix) for research-universe auth.
        dart_api_key: DART (Korea FSS) API key; dart_filing sources are
            skipped if None.
        domain_slug: The domain this fetch is for - passed through to
            _fetch_gdelt for its own domain-scoped press allowlist (see
            that function's own docstring for why sources' own dicts
            can't carry this: load_sources' SELECT never includes
            domain_slug, unlike list_sources - a source dict read via the
            normal run() path has no such field to read it off of).

    Returns:
        List of article dicts sorted newest-first.
    """
    rss_sources = [s for s in sources if s.get("source_type", "rss") == "rss"]
    serpapi_sources = [s for s in sources if s.get("source_type") == "google_news"]
    newsapi_sources = [s for s in sources if s.get("source_type") == "newsapi"]
    alpha_vantage_sources = [s for s in sources if s.get("source_type") == "alpha_vantage"]
    federal_register_sources = [s for s in sources if s.get("source_type") == "federal_register"]
    gdelt_sources = [s for s in sources if s.get("source_type") == "gdelt"]
    twse_revenue_sources = [s for s in sources if s.get("source_type") == "twse_revenue"]
    tpex_revenue_sources = [s for s in sources if s.get("source_type") == "tpex_revenue"]
    twse_material_sources = [s for s in sources if s.get("source_type") == "twse_material"]
    tpex_material_sources = [s for s in sources if s.get("source_type") == "tpex_material"]
    dart_filing_sources = [s for s in sources if s.get("source_type") == "dart_filing"]
    kr_customs_export_sources = [s for s in sources if s.get("source_type") == "kr_customs_export"]

    articles: list[dict] = []
    t0 = time.perf_counter()

    if rss_sources:
        articles.extend(_fetch_rss(rss_sources, days_back))

    if serpapi_sources:
        if serpapi_key:
            articles.extend(_fetch_serpapi(serpapi_sources, days_back, serpapi_key))
        else:
            logger.warning(
                "SERPAPI_KEY not set - skipping %d serpapi source(s)",
                len(serpapi_sources),
            )

    if newsapi_sources:
        if newsapi_key:
            articles.extend(_fetch_newsapi(newsapi_sources, days_back, newsapi_key))
        else:
            logger.warning(
                "NEWSAPI_KEY not set - skipping %d newsapi source(s)",
                len(newsapi_sources),
            )

    if alpha_vantage_sources:
        if alpha_vantage_key:
            articles.extend(_fetch_alpha_vantage(alpha_vantage_sources, alpha_vantage_key, universe_url, universe_api_key))
        else:
            logger.warning(
                "ALPHA_VANTAGE_API_KEY not set - skipping %d alpha_vantage source(s)",
                len(alpha_vantage_sources),
            )

    if federal_register_sources:
        articles.extend(_fetch_federal_register(federal_register_sources, days_back))

    if gdelt_sources:
        articles.extend(_fetch_gdelt(gdelt_sources, days_back, domain_slug))

    if twse_revenue_sources:
        articles.extend(_fetch_twse_revenue(twse_revenue_sources))

    if tpex_revenue_sources:
        articles.extend(_fetch_tpex_revenue(tpex_revenue_sources))

    if twse_material_sources:
        articles.extend(_fetch_twse_material(twse_material_sources))

    if tpex_material_sources:
        articles.extend(_fetch_tpex_material(tpex_material_sources))

    if dart_filing_sources:
        if dart_api_key:
            articles.extend(_fetch_dart_filing(dart_filing_sources, days_back, dart_api_key))
        else:
            logger.warning(
                "DART_API_KEY not set - skipping %d dart_filing source(s)",
                len(dart_filing_sources),
            )

    if kr_customs_export_sources:
        articles.extend(_fetch_customs_export_data(kr_customs_export_sources, days_back))

    articles.sort(
        key=lambda a: (
            a["_pub_date"] or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    if max_articles:
        articles = articles[:max_articles]
    for a in articles:
        a["published"] = a.pop("_pub_date")  # normalised UTC datetime; None if source omitted date

    logger.info(
        "[TIMER] fetch total: sources=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_ARTICLE_KEYS = ("url", "title", "summary", "source", "published", "body", "metadata")


def run(
    domain_slug: str,
    days_back: int = 7,
    max_articles: int = 0,
) -> dict[str, Any]:
    """Fetch articles for the given domain.

    Args:
        domain_slug: Domain identifier used to query sources from DB.
        days_back: Exclude articles older than this many days.
        max_articles: Cap on total articles fetched; 0 means no limit.

    Returns:
        Dict with ``"articles"`` (list of article dicts).
    """
    t0 = time.perf_counter()
    serpapi_key = (
        os.environ.get("SERPAPI_KEY_GEOPOLITICAL")
        if domain_slug == "geopolitical_news"
        else os.environ.get("SERPAPI_KEY")
    )
    newsapi_key = os.environ.get("NEWSAPI_KEY")
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    universe_url = os.environ.get("RESEARCH_UNIVERSE_URL")
    universe_api_key = os.environ.get("RESEARCH_UNIVERSE_API_KEY")
    dart_api_key = os.environ.get("DART_API_KEY")

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"articles": []}

    articles = _fetch_articles(
        sources, days_back, max_articles, serpapi_key, newsapi_key, alpha_vantage_key,
        universe_url, universe_api_key, dart_api_key, domain_slug,
    )
    if not articles:
        return {"articles": []}

    # Global cross-domain, cross-run dedup: drop articles already stored
    # under ANY domain's prior run. Bounded to this run's candidate URLs,
    # not a full history pull.
    seen_urls = get_already_stored_urls([a["url"] for a in articles])
    articles = [a for a in articles if a["url"] not in seen_urls]
    if not articles:
        return {"articles": []}

    # ai_news/smart_money: RSS/SerpAPI/NewsAPI sources aren't pre-scoped to
    # one story the way ticker/agency-filtered domains are, so the same
    # story from multiple outlets survives the URL-only dedup above with
    # different URLs and differently-worded titles. Same title-similarity
    # embedding check as Taiwan GDELT (_dedup_by_title_similarity), scoped
    # by domain instead of ticker.
    if domain_slug in _TITLE_DEDUP_DOMAINS:
        before_title_dedup = len(articles)
        articles = _dedup_by_title_similarity_for_domain(articles, domain_slug)
        logger.info(
            "[%s] title-similarity dedup: %d -> %d article(s)",
            domain_slug, before_title_dedup, len(articles),
        )

    # taiwan_market_signal: news-retrieval's job stops at fetch, Stage A
    # filtering (allowlist + name-in-title, already run inside
    # _fetch_gdelt), and exact/title-similarity dedup — matching every
    # other domain's fetch/store-raw boundary. Revenue ranking, material-
    # announcement clause classification, and translation all moved to
    # signal-detection-agent (see insert_taiwan_signal_classification in
    # that service's models/jobs.py) - keeping this service uniformly
    # fetch-only rather than the sole domain doing classification/
    # translation work here.

    logger.info(
        "[TIMER] domain=%s total=%.2fs articles=%d",
        domain_slug, time.perf_counter() - t0, len(articles),
    )
    return {
        "articles": [
           {k: a.get(k) for k in _ARTICLE_KEYS} for a in articles
        ],
    }
