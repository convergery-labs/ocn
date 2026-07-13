"""Background poller: fetches market data from Alpha Vantage and writes to DynamoDB."""
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_AV_BASE_URL = "https://www.alphavantage.co/query"
_AV_MIN_INTERVAL = 1.0  # 1 call/sec → 60/min, safely under 75/min premium limit

_INDEX_TICKERS = ["SPY", "QQQ", "SOXX"]

# quotes mode: 1 call/ticker + 3 indices + 1 market_status
# At 1 call/sec, 600 tickers = ~604 sec (~10 min) — fits the 15-min schedule window
# with headroom for slow AV responses. Increase if poll interval is widened.
_MAX_QUOTES_TICKERS = 600

_AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")

# Self URL — used to check if company_news pipeline is currently running
# On ECS this is the internal service discovery URL; locally it's localhost
_NEWS_RETRIEVAL_URL = os.environ.get("NEWS_RETRIEVAL_URL", "http://localhost:8000")

_LOCK_TABLE = os.environ.get("DYNAMODB_TABLE_LOCK", "ocn-market-lock")
_LOCK_TTL_SECONDS = 20 * 60  # 20 min — auto-expires if poller crashes mid-run

# DynamoDB table names
_TABLES = {
    "quote": os.environ.get("DYNAMODB_TABLE_QUOTE", "ocn-market-quote"),
    "overview": os.environ.get("DYNAMODB_TABLE_OVERVIEW", "ocn-market-overview"),
    "price_history": os.environ.get("DYNAMODB_TABLE_PRICE_HISTORY", "ocn-market-price-history"),
    "earnings": os.environ.get("DYNAMODB_TABLE_EARNINGS", "ocn-market-earnings"),
    "indices": os.environ.get("DYNAMODB_TABLE_INDICES", "ocn-market-indices"),
    "market_status": os.environ.get("DYNAMODB_TABLE_MARKET_STATUS", "ocn-market-status"),
}


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _dynamodb() -> "boto3.resource":
    return boto3.resource("dynamodb", region_name=_AWS_REGION)


def _table(name: str):
    return _dynamodb().Table(_TABLES[name])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl(days: int) -> int:
    return int(time.time()) + (days * 86400)


def _to_decimal(value: str) -> Decimal:
    """Convert string number to Decimal for DynamoDB (no floats allowed)."""
    try:
        return Decimal(str(value).rstrip("%").strip() or "0")
    except Exception:
        return Decimal("0")


# ---------------------------------------------------------------------------
# Distributed lock — prevents overlapping poller runs
# ---------------------------------------------------------------------------

def _acquire_lock(mode: str) -> bool:
    """Try to acquire the poll lock for the given mode.

    Uses DynamoDB conditional write — atomic across all ECS tasks.
    Returns True if lock acquired, False if another run is already active.
    """
    lock_key = f"poll-{mode}"
    client = boto3.client("dynamodb", region_name=_AWS_REGION)
    try:
        client.put_item(
            TableName=_LOCK_TABLE,
            Item={
                "lock_key": {"S": lock_key},
                "acquired_at": {"S": _now_iso()},
                "ttl": {"N": str(int(time.time()) + _LOCK_TTL_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(lock_key)",
        )
        return True
    except client.exceptions.ConditionalCheckFailedException:
        return False
    except Exception as exc:
        logger.warning("[LOCK] acquire failed, proceeding without lock: %s", exc)
        return True  # fail open — better to double-poll than to permanently skip


def _release_lock(mode: str) -> None:
    """Delete the lock item after a successful poll run."""
    try:
        boto3.client("dynamodb", region_name=_AWS_REGION).delete_item(
            TableName=_LOCK_TABLE,
            Key={"lock_key": {"S": f"poll-{mode}"}},
        )
    except Exception as exc:
        logger.warning("[LOCK] release failed (TTL will expire it): %s", exc)


# ---------------------------------------------------------------------------
# Alpha Vantage fetch helpers
# ---------------------------------------------------------------------------

def _av_get(params: dict, av_key: str) -> dict:
    try:
        resp = httpx.get(
            _AV_BASE_URL,
            params={**params, "apikey": av_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[AV] request failed params=%s error=%s", params, exc)
        return {}


def _rate_sleep(last_call: list[float]) -> None:
    elapsed = time.monotonic() - last_call[0]
    if elapsed < _AV_MIN_INTERVAL:
        time.sleep(_AV_MIN_INTERVAL - elapsed)
    last_call[0] = time.monotonic()


# ---------------------------------------------------------------------------
# Company news guard — skip AV polling if company_news pipeline is running
# ---------------------------------------------------------------------------

def _company_news_running() -> bool:
    """Return True if a company_news pipeline run is currently active.

    Checks the runs API on this same service. Fails open (returns False)
    so a transient error never permanently blocks the poller.
    """
    try:
        resp = httpx.get(
            f"{_NEWS_RETRIEVAL_URL}/runs",
            params={"domain": "company_news", "limit": 1},
            timeout=5.0,
        )
        runs = resp.json().get("runs", [])
        if runs and runs[0].get("status") == "running":
            logger.info("[POLLER] company_news pipeline is running — skipping AV calls to avoid rate limit")
            return True
        return False
    except Exception as exc:
        logger.warning("[POLLER] could not check company_news status, proceeding: %s", exc)
        return False  # fail open


# ---------------------------------------------------------------------------
# Daily mode: OVERVIEW, EARNINGS, TIME_SERIES_DAILY_ADJUSTED
# ---------------------------------------------------------------------------

def _poll_overview(ticker: str, av_key: str, last_call: list[float]) -> None:
    _rate_sleep(last_call)
    data = _av_get({"function": "OVERVIEW", "symbol": ticker}, av_key)
    if not data or "MarketCapitalization" not in data:
        logger.warning("[AV] OVERVIEW empty for %s", ticker)
        return

    _table("overview").put_item(Item={
        "ticker": ticker,
        "recorded_at": _now_iso(),
        "name": data.get("Name", ""),
        "exchange": data.get("Exchange", ""),
        "market_cap": _to_decimal(data.get("MarketCapitalization", "0")),
        "pe_ratio": _to_decimal(data.get("PERatio", "0")),
        "week_52_high": _to_decimal(data.get("52WeekHigh", "0")),
        "week_52_low": _to_decimal(data.get("52WeekLow", "0")),
        "analyst_target": _to_decimal(data.get("AnalystTargetPrice", "0")),
        "beta": _to_decimal(data.get("Beta", "0")),
        "sector": data.get("Sector", ""),
        "ttl": _ttl(30),
    })
    logger.info("[DYNAMODB] overview written ticker=%s", ticker)


def _poll_earnings(ticker: str, av_key: str, last_call: list[float]) -> None:
    _rate_sleep(last_call)
    data = _av_get({"function": "EARNINGS", "symbol": ticker}, av_key)
    quarterly = data.get("quarterlyEarnings", [])
    if not quarterly:
        logger.warning("[AV] EARNINGS empty for %s", ticker)
        return

    def _safe_float(val) -> float:
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return 0.0

    last = quarterly[0]
    estimated = _safe_float(last.get("estimatedEPS"))
    reported = _safe_float(last.get("reportedEPS"))
    surprise_pct = (
        round((reported - estimated) / abs(estimated) * 100, 2)
        if estimated != 0 else 0.0
    )

    next_report = ""
    estimated_next = "0"
    for q in quarterly:
        if not q.get("reportedEPS"):
            next_report = q.get("fiscalDateEnding", "")
            estimated_next = q.get("estimatedEPS") or "0"
            break

    _table("earnings").put_item(Item={
        "ticker": ticker,
        "recorded_at": _now_iso(),
        "next_report_date": next_report or "unknown",
        "estimated_eps": _to_decimal(estimated_next),
        "last_surprise_pct": _to_decimal(str(surprise_pct)),
        "ttl": _ttl(30),
    })
    logger.info("[DYNAMODB] earnings written ticker=%s", ticker)


def _poll_price_history(ticker: str, av_key: str, last_call: list[float]) -> None:
    _rate_sleep(last_call)
    data = _av_get(
        {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker, "outputsize": "compact"},
        av_key,
    )
    series = data.get("Time Series (Daily)", {})
    if not series:
        logger.warning("[AV] TIME_SERIES_DAILY_ADJUSTED empty for %s", ticker)
        return

    dates = sorted(series.keys(), reverse=True)[:10]
    table = _table("price_history")
    with table.batch_writer() as batch:
        for date_str in dates:
            adj_close = series[date_str].get("5. adjusted close", "0")
            batch.put_item(Item={
                "ticker": ticker,
                "date": date_str,
                "adjusted_close": _to_decimal(adj_close),
                "ttl": _ttl(365),
            })
    logger.info("[DYNAMODB] price_history written ticker=%s days=%d", ticker, len(dates))


def run_daily(tickers: list[str], av_key: str) -> None:
    """Poll OVERVIEW, EARNINGS, TIME_SERIES_DAILY_ADJUSTED for each ticker."""
    if _company_news_running():
        return
    if not _acquire_lock("daily"):
        logger.info("[POLLER] daily already running — skipping this trigger")
        return
    try:
        logger.info("[POLLER] daily mode tickers=%d", len(tickers))
        last_call: list[float] = [0.0]
        for ticker in tickers:
            logger.info("[POLLER] daily ticker=%s", ticker)
            try:
                _poll_overview(ticker, av_key, last_call)
                _poll_earnings(ticker, av_key, last_call)
                _poll_price_history(ticker, av_key, last_call)
            except Exception as exc:
                logger.error("[POLLER] daily ticker=%s failed, skipping: %s", ticker, exc)
        logger.info("[POLLER] daily complete")
    finally:
        _release_lock("daily")


# ---------------------------------------------------------------------------
# Quotes mode: GLOBAL_QUOTE per ticker + indices + MARKET_STATUS
# ---------------------------------------------------------------------------

def _poll_quote(ticker: str, av_key: str, last_call: list[float]) -> None:
    _rate_sleep(last_call)
    data = _av_get({"function": "GLOBAL_QUOTE", "symbol": ticker}, av_key)
    quote = data.get("Global Quote", {})
    if not quote:
        logger.warning("[AV] GLOBAL_QUOTE empty for %s", ticker)
        return

    _table("quote").put_item(Item={
        "ticker": ticker,
        "recorded_at": _now_iso(),
        "price": _to_decimal(quote.get("05. price", "0")),
        "change": _to_decimal(quote.get("09. change", "0")),
        "change_percent": _to_decimal(quote.get("10. change percent", "0%")),
        "volume": _to_decimal(quote.get("06. volume", "0")),
        "previous_close": _to_decimal(quote.get("08. previous close", "0")),
        "ttl": _ttl(4),
    })
    logger.info("[DYNAMODB] quote written ticker=%s", ticker)


def _poll_indices(av_key: str, last_call: list[float]) -> None:
    for ticker in _INDEX_TICKERS:
        _rate_sleep(last_call)
        data = _av_get({"function": "GLOBAL_QUOTE", "symbol": ticker}, av_key)
        quote = data.get("Global Quote", {})
        if not quote:
            logger.warning("[AV] GLOBAL_QUOTE empty for index %s", ticker)
            continue
        _table("indices").put_item(Item={
            "ticker": ticker,
            "recorded_at": _now_iso(),
            "price": _to_decimal(quote.get("05. price", "0")),
            "change_percent": _to_decimal(quote.get("10. change percent", "0%")),
            "ttl": _ttl(4),
        })
        logger.info("[DYNAMODB] indices written ticker=%s", ticker)


def _poll_market_status(av_key: str, last_call: list[float]) -> None:
    _rate_sleep(last_call)
    data = _av_get({"function": "MARKET_STATUS"}, av_key)
    markets = data.get("markets", [])
    us = next((m for m in markets if m.get("region") == "United States"), None)
    if not us:
        logger.warning("[AV] MARKET_STATUS no US market found")
        return
    _table("market_status").put_item(Item={
        "market": "US",
        "recorded_at": _now_iso(),
        "current_status": us.get("current_status", "unknown"),
        "local_open": us.get("local_open", ""),
        "local_close": us.get("local_close", ""),
        "ttl": _ttl(4),
    })
    logger.info("[DYNAMODB] market_status written")


def run_quotes(tickers: list[str], av_key: str) -> None:
    """Poll GLOBAL_QUOTE for each ticker + indices + MARKET_STATUS."""
    if _company_news_running():
        return
    if not _acquire_lock("quotes"):
        logger.info("[POLLER] quotes already running — skipping this trigger")
        return

    try:
        if len(tickers) > _MAX_QUOTES_TICKERS:
            logger.warning(
                "[POLLER] ticker list truncated %d → %d to stay within 15-min window",
                len(tickers), _MAX_QUOTES_TICKERS,
            )
            tickers = tickers[:_MAX_QUOTES_TICKERS]

        logger.info("[POLLER] quotes mode tickers=%d", len(tickers))
        t0 = time.perf_counter()
        last_call: list[float] = [0.0]

        for ticker in tickers:
            _poll_quote(ticker, av_key, last_call)

        _poll_indices(av_key, last_call)
        _poll_market_status(av_key, last_call)

        elapsed = time.perf_counter() - t0
        logger.info("[POLLER] quotes complete elapsed=%.1fs", elapsed)
        if elapsed > 840:
            logger.warning(
                "[POLLER] quotes took %.1fs — approaching 15-min schedule window. "
                "Consider reducing ticker count or increasing poll interval.",
                elapsed,
            )
    finally:
        _release_lock("quotes")
