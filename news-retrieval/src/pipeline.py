"""News aggregation pipeline: fetch and relevance-filter articles.

Pass 1 - title-only relevance filter (LLM via OpenRouter).
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


def _fetch_universe_tickers(base_url: str, api_key: str | None = None) -> list[str]:
    """Fetch verified ticker symbols from the research-universe API.

    Calls GET /companies?status=verified and returns a deduplicated list
    of non-empty ticker strings. Falls back to [] on any error so the
    caller can continue with config-only tickers.

    Args:
        base_url: research-universe service base URL, e.g.
            "http://research-universe.staging.ocn.internal:8007"
        api_key: service API key (ru_ prefix) for Authorization header
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(
            f"{base_url}/companies",
            params={"status": "verified", "limit": 10000},
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        companies = resp.json()
        tickers = [c["ticker"] for c in companies if c.get("ticker", "").strip()]
        logger.info("[ALPHA_VANTAGE] fetched %d tickers from universe API", len(tickers))
        return tickers
    except Exception as exc:
        logger.warning(
            "[ALPHA_VANTAGE] universe API unavailable, falling back to config tickers: %s", exc
        )
        return []


# Alpha Vantage API limits (premium key):
# - 75 calls/minute, 500 calls/day
# - 1 ticker per call (multi-ticker requests return far fewer articles)
# - Capped at 500 tickers per run to stay within daily quota
_AV_CALLS_PER_MINUTE = 60  # steady rate: 1 call/sec, well under the 75/min premium limit
_AV_MIN_INTERVAL = 60.0 / _AV_CALLS_PER_MINUTE  # 1.0 second between calls
_AV_DAILY_LIMIT = 500

# Hardcoded 500 popular US-listed AI-economy tickers for Alpha Vantage.
# Dynamic fetch via research-universe API can ADD new tickers on top of this list
# but will never overwrite it — these are the guaranteed baseline.
#count = 453
_AV_BASE_TICKERS: list[str] = [
    "NVDA","MSFT","AAPL","AMZN","GOOGL","META","TSLA","AVGO","ORCL","AMD",
    "CRM","NOW","INTU","ADBE","CSCO","IBM","TXN","QCOM","ARM","INTC",
    "AMAT","LRCX","KLAC","SNPS","CDNS","MRVL","ANSS","FTNT","PANW","CRWD",
    "ZS","OKTA","DDOG","SNOW","MDB","PLTR","NET","ANET","SMCI","DELL",
    "HPE","NTAP","PSTG","WDC","STX","KEYS","TRMK","VIAV","LITE","COHR",
    "IPGP","IIVI","MKSI","ENTG","ACLS","ONTO","FORM","CAMT","COHU","KLIC",
    "ACMR","LASE","RMBS","SIMO","ALGM","CEVA","SLAB","SITM","MTSI","NXPI",
    "MCHP","MPWR","SWKS","QRVO","ADI","LSCC","AMBA","POWI","AXTI","AOSL",
    "DIOD","IXYS","SMTC","VSH","CRUS","NVMI","UCTT","AAOI","IESC","RBBN",
    "INFN","CIEN","COMM","CASA","CALX","ADTN","IDCC","EXTR","FFIV","JNPR",
    "NTGR","EQIX","DLR","AMT","CCI","SBAC","IRM","CONE","QTS","REIT",
    "GLPK","COLD","NSA","LSI","UNIT","CORR","NLST","CLFD","XTLB","UBER",
    "LYFT","DASH","ABNB","BKNG","EXPE","TRIP","OPEN","RDFN","Z","SHOP",
    "ETSY","EBAY","W","WISH","OSTK","PRTS","REAL","RENT","SQ","PYPL",
    "AFRM","UPST","SOFI","LC","OPFI","DAVE","MOGO","CURO","COIN","MSTR",
    "RIOT","MARA","BTDR","HUT","CIFR","IREN","WULF","CORZ","GOOG","SNAP",
    "PINS","RDDT","MTCH","BUMBLE","IAC","NFLX","DIS","WBD","PARA","FOX",
    "FOXA","SIRI","SPOT","SONO","RBLX","U","EA","TTWO","ATVI","NTES",
    "SE","GRAB","GOTO","BABA","JD","PDD","BIDU","TCEHY","TME","HUYA",
    "DOYU","IQ","BILI","TSM","ASML","SAP","CFLT","GTLB","HUBS","BILL",
    "PAYC","PCTY","SMAR","APPN","MNDY","ASAN","JAMF","DOCN","DOMO","BOX",
    "ALB","FCX","MP","RIO","CCJ","NEE","VST","CEG","GEV","NRG",
    "TOELY","MU","VRT","TT","MOD","FIX","ETN","APH","PWR","ISRG",
    "LMT","AXON","WDAY","VEEV","TEAM","ZM","DOCU","S","TENB","RPD",
    "CYBR","QLYS","VRNT","SAIL","ENFN","RDWR","AI","BBAI","SOUN","GFAI",
    "HOOD","NU","FLUT","MELI","BRZE","PATH","IROBOT","NVTS","ACHR","JOBY",
    "RKLB","LUNR","PL","SPIR","HII","RTX","BA","NOC","GD","RIVN",
    "LCID","FSR","XPEV","LI","NIO","SDGR","RXRX","TWST","ILMN","TEM",
    "MDAI","VZ","T","TMUS","KAKAO","9984.T","ADSK","ANGI","AZPN","BL",
    "CDAY","CORT","CWAN","ESTC","FIVN","FOUR","FRSH","GENI","GWRE","HCP",
    "HIMS","IO","KROS","LPSN","MANH","NCNO","NTNX","PCVX","PRGS","RAMP",
    "RNG","SAMSF","SPT","TASK","TOST","TXRH","TYRA","VNET","VRNS","WEX",
    "WOLF","XPOF","ZI","AMKR","AEHR","ASYS","CAVM","CLAR","CMGE","ENVX",
    "GFS","HIMX","IMOS","INTF","IPSN","IXHL","KOPN","MRAM","NUVL","NVEC",
    "PCYG","PLAB","PRCT","PSI","ACAD","APLT","ARWR","BEAM","BLUE","CGEM",
    "DNLI","EDIT","FOLD","GERN","GRPH","IMVT","IONS","IOVA","ITRI","KDNY",
    "KRYS","LOGC","NKLA","NTLA","PACB","PRME","PTGX","REGN","RGEN","RLAY",
    "RNA","ROOF","SAGE","ACIW","ACVA","BWXT","CACI","DRS","ESIT","FLIR",
    "HEI","KTOS","LDOS","MANT","MRCY","PSN","SAIC","SPCE","SPY","SWAV",
    "TDY","TXT","VRSN","CMBM","CSGS","DSGX","EGHT","EXLX","FSLY","GCMG",
    "GLBE","GWAV","ITRN","LMND","LPTH","MIME","MNKD","MXIM","BNTX","CFFE",
    "CHX","CNXC","CREE","DOOO","DSEY","ESYS","FARO","FLEX","FROG","GCBC",
    "HLIO","IRBT","ITIC","JMIA","KPLT","LIQT","MNSO","MOXC","NCTY","NEPT",
    "NFLY","NKTR","NLOK","NOVA","NUAN","AKAM","ALTR","APPF","APPM","ARIS",
    "AVLR","BCOV","BFLY","BIGC","BLKB","BVS","CARG","CGNT","CHKP","CLOU",
    "CODA","CPRT","DCBO",
]


def _fetch_alpha_vantage(
    sources: list[dict],
    days_back: int,
    alpha_vantage_key: str,
    universe_url: str | None = None,
    universe_api_key: str | None = None,
) -> list[dict]:
    """Fetch company-specific news from Alpha Vantage News & Sentiments API.

    One API call per ticker — multi-ticker requests return far fewer articles.
    Keep config.tickers in seed.py to <= 500 to stay within the 500 calls/day quota.

    Args:
        sources: List of alpha_vantage source dicts with ``config.tickers``.
        days_back: Exclude articles older than this many days.
        api_key: Alpha Vantage API key.
        universe_url: research-universe base URL; if set, tickers are fetched
            dynamically. Falls back to config tickers if unreachable.
        universe_api_key: Service API key (ru_ prefix) for research-universe auth.

    Returns:
        List of article dicts with ``_pub_date`` set.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    time_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime(
        "%Y%m%dT%H%M"
    )

    tickers: list[str] = list(_AV_BASE_TICKERS)

    # Dynamic fetch from research-universe is wired but disabled:
    # _AV_BASE_TICKERS already fills the 500-ticker daily quota so dynamic
    # tickers would be cut off anyway. Re-enable when base list is reduced.
    # if universe_url:
    #     dynamic = _fetch_universe_tickers(universe_url, universe_api_key)
    #     tickers.extend(dynamic)
    # tickers = list(dict.fromkeys(tickers))

    if len(tickers) > _AV_DAILY_LIMIT:
        tickers = tickers[:_AV_DAILY_LIMIT]

    if not tickers:
        logger.warning("[ALPHA_VANTAGE] no tickers configured, skipping")
        return []

    logger.info("[ALPHA_VANTAGE] tickers=%d (base=%d)", len(tickers), len(_AV_BASE_TICKERS))

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
        sources: List of source dicts (RSS, SerpAPI, NewsAPI, and/or Alpha Vantage).
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
            articles.extend(_fetch_alpha_vantage(alpha_vantage_sources, days_back, alpha_vantage_key, universe_url, universe_api_key))
        else:
            logger.warning(
                "ALPHA_VANTAGE_API_KEY not set - skipping %d alpha_vantage source(s)",
                len(alpha_vantage_sources),
            )

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
        "[TIMER] fetch total: sources=%d articles=%d elapsed=%.2fs",
        len(sources), len(articles), time.perf_counter() - t0,
    )
    return articles


# ---------------------------------------------------------------------------
# Step 2 - relevance filter (Pass 1)
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
            "OpenRouter authentication failed - check your API key"
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

    Sends only ``url`` and ``title`` - no summary - keeping token cost low.
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

_ARTICLE_KEYS = ("url", "title", "summary", "source", "published", "body", "metadata")


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
    serpapi_key = os.environ.get("SERPAPI_KEY")
    newsapi_key = os.environ.get("NEWSAPI_KEY")
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    universe_url = os.environ.get("RESEARCH_UNIVERSE_URL")
    universe_api_key = os.environ.get("RESEARCH_UNIVERSE_API_KEY")

    sources = load_sources(domain_slug, days_back)
    if not sources:
        return {"articles": []}

    articles = _fetch_articles(
        sources, days_back, max_articles, serpapi_key, newsapi_key, alpha_vantage_key, universe_url, universe_api_key
    )
    if not articles:
        return {"articles": []}

    # Alpha Vantage articles are pre-filtered by ticker — already scoped to universe
    # companies by definition, so LLM relevance filter adds no value and would drop
    # legitimate company-specific news (earnings, filings, etc.).
    if domain_slug == "company_news":
        relevant = articles
    else:
        relevant = _filter_articles(
            articles, domain_name, domain_description, focus, client, model
        )

    logger.info(
        "[TIMER] domain=%s total=%.2fs articles=%d",
        domain_slug, time.perf_counter() - t0, len(relevant),
    )
    return {
        "articles": [
           {k: a.get(k) for k in _ARTICLE_KEYS} for a in relevant
        ],
    }
