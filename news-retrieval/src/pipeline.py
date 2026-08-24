"""News aggregation pipeline: fetch articles from configured sources."""
import html
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import feedparser
import httpx
import trafilatura
from openai import OpenAI

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
        return trafilatura.extract(trafilatura.fetch_url(url)) if url else None

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
_GDELT_MIN_INTERVAL = 10.0  # GDELT's documented floor is 5s; observed to tighten under load
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


def _embed_titles(titles: list[str], api_key: str | None) -> list[list[float] | None]:
    """Embed a batch of titles via OpenRouter, same model class already used
    by signal-detection for lightweight claim-level comparison (as opposed
    to the larger text-embedding-3-large used there for full-body
    clustering — titles are short, a smaller model is enough and cheaper).

    Returns one embedding per title, in order; a title's slot is None if the
    batch call fails, so callers must treat missing embeddings as "cannot
    compare" rather than "definitely not a duplicate" (fail-open — never
    silently drop an article because embedding failed).
    """
    if not titles:
        return []
    try:
        client = _make_client(api_key)
        response = client.embeddings.create(
            model=_TITLE_EMBEDDING_MODEL, input=titles,
        )
        return [item.embedding for item in response.data]
    except Exception as exc:
        logger.warning(
            "[GDELT] title embedding failed for batch of %d: %s",
            len(titles), exc,
        )
        return [None] * len(titles)


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


def _filter_by_domain_allowlist(
    articles: list[dict], query_ticker: dict[str, str],
) -> list[dict]:
    """Drop GDELT articles whose domain is not on the Taiwan press allowlist.

    Only touches ticker-scoped GDELT articles (those whose ``_query`` is in
    ``query_ticker`` - the same test used by dedup) - other sources pass
    through untouched. Keyed on ``_query`` presence rather than
    ``metadata.source_category``, since this runs BEFORE
    _dedup_by_title_similarity, which is what actually writes
    source_category - at this point in the pipeline that field doesn't
    exist yet.

    GDELT's ``domain`` field (stored as the article's ``source``) is
    compared case-insensitively; articles with no ``source`` set are
    dropped (fail-closed here, unlike the embedding fail-open logic below,
    since a domain we can't identify at all can't be verified as
    legitimate Taiwan press).
    """
    kept = []
    dropped = 0
    for a in articles:
        if not query_ticker.get(a.get("_query", "")):
            kept.append(a)
            continue
        domain = (a.get("source") or "").lower()
        if domain in _TAIWAN_PRESS_ALLOWLIST:
            kept.append(a)
        else:
            dropped += 1
            logger.info("[PATH3-A] dropped (domain not allowlisted): %r", domain)
    if dropped:
        logger.info("[PATH3-A] domain allowlist: dropped %d article(s)", dropped)
    return kept


def _filter_by_company_name_in_title(
    articles: list[dict], query_ticker: dict[str, str],
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

    Keyed on ``_query`` presence, same reasoning as the allowlist filter
    above - source_category isn't set yet at this point in the pipeline.
    """
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
        title = a.get("title") or ""
        if name and name.lower() in title.lower():
            kept.append(a)
        else:
            dropped += 1
            logger.info(
                "[PATH3-A] dropped (queried name %r not found in title %r)",
                name, title,
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
            domain = article.get("source")
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
_TITLE_DEDUP_DOMAINS: frozenset[str] = frozenset({"ai_news", "smart_money"})

# Wider than Taiwan GDELT's 24h (_TITLE_DEDUP_WINDOW_HOURS) - ai_news and
# smart_money sources (RSS/SerpAPI/NewsAPI) publish re-coverage of the same
# story across a longer tail than same-day Taiwan company filings/news, so
# a same-day-only window was missing duplicates that appear the next day.
_DOMAIN_TITLE_DEDUP_WINDOW_HOURS = 48


def _dedup_by_title_similarity_for_domain(
    articles: list[dict], domain_slug: str,
) -> list[dict]:
    """Drop articles whose title is near-identical in meaning to one already
    stored for this domain in the last ``_DOMAIN_TITLE_DEDUP_WINDOW_HOURS``
    hours.

    Same algorithm as ``_dedup_by_title_similarity`` (Taiwan GDELT), scoped
    by domain instead of ticker - ai_news/smart_money sources aren't
    ticker-scoped, so "same domain" is the natural comparison boundary
    instead.

    Embedding failures fail open: an article whose title couldn't be
    embedded, or whose only comparison candidates lack a stored embedding,
    is kept rather than silently dropped or silently deduped.
    """
    if not articles:
        return articles

    api_key = os.environ.get("OPENROUTER_API_KEY")
    new_embeddings = _embed_titles([a["title"] for a in articles], api_key)

    recent = get_recent_articles_for_domain(
        domain_slug, hours=_DOMAIN_TITLE_DEDUP_WINDOW_HOURS,
    )
    candidates = [
        (c.get("title"), (c.get("metadata") or {}).get("title_embedding"),
         c.get("id"), None)
        for c in recent
    ]
    # Same-batch candidates kept so far - two outlets can surface the same
    # story within one run, before either has been stored yet.
    kept_this_batch: list[dict] = []

    kept: list[dict] = []
    dropped = 0

    for article, embedding in zip(articles, new_embeddings):
        article.setdefault("metadata", {})
        if embedding is None:
            kept.append(article)
            continue

        batch_candidates = candidates + [
            (c["title"], c["metadata"]["title_embedding"], None, c)
            for c in kept_this_batch
        ]

        match = None
        for candidate_title, candidate_embedding, db_id, batch_article in batch_candidates:
            if not candidate_embedding:
                continue
            similarity = _cosine_similarity(embedding, candidate_embedding)
            if similarity >= _TITLE_DEDUP_SIMILARITY_THRESHOLD:
                logger.info(
                    "[%s] near-duplicate title (similarity=%.3f)"
                    " new=%r existing=%r",
                    domain_slug, similarity, article["title"], candidate_title,
                )
                match = (db_id, batch_article)
                break

        if match is not None:
            db_id, batch_article = match
            outlet = article.get("source")
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
    return kept


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


def _fetch_gdelt(sources: list[dict], days_back: int) -> list[dict]:
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
    for source in sources:
        query_ticker.update((source.get("config") or {}).get("query_ticker", {}))

    # Path 3, Stage A (spec order: allowlist -> name-in-title -> dedup).
    # All three are no-ops for sources with no ticker mapping (e.g.
    # geopolitical_news's theme queries) - only ticker-scoped Taiwan
    # queries are affected. Run before translation and before the body
    # fetch below, so a dropped article never wastes translation cost or a
    # Trafilatura fetch.
    if query_ticker:
        before_stage_a = len(articles)
        articles = _filter_by_domain_allowlist(articles, query_ticker)
        articles = _filter_by_company_name_in_title(articles, query_ticker)
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
        downloaded = trafilatura.fetch_url(url)
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


def _fetch_articles(
    sources: list[dict],
    days_back: int,
    max_articles: int,
    serpapi_key: str | None = None,
    newsapi_key: str | None = None,
    alpha_vantage_key: str | None = None,
    universe_url: str | None = None,
    universe_api_key: str | None = None,
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
        articles.extend(_fetch_gdelt(gdelt_sources, days_back))

    if twse_revenue_sources:
        articles.extend(_fetch_twse_revenue(twse_revenue_sources))

    if tpex_revenue_sources:
        articles.extend(_fetch_tpex_revenue(tpex_revenue_sources))

    if twse_material_sources:
        articles.extend(_fetch_twse_material(twse_material_sources))

    if tpex_material_sources:
        articles.extend(_fetch_tpex_material(tpex_material_sources))

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

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"articles": []}

    articles = _fetch_articles(
        sources, days_back, max_articles, serpapi_key, newsapi_key, alpha_vantage_key,
        universe_url, universe_api_key,
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
