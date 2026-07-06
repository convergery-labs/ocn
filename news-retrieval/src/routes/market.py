"""Routes for /market — read market data from DynamoDB."""
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from fastapi import APIRouter, HTTPException

router = APIRouter()

_AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")
_INDEX_TICKERS = ["SPY", "QQQ", "SOXX"]

_TABLES = {
    "quote": os.environ.get("DYNAMODB_TABLE_QUOTE", "ocn-market-quote"),
    "overview": os.environ.get("DYNAMODB_TABLE_OVERVIEW", "ocn-market-overview"),
    "price_history": os.environ.get("DYNAMODB_TABLE_PRICE_HISTORY", "ocn-market-price-history"),
    "earnings": os.environ.get("DYNAMODB_TABLE_EARNINGS", "ocn-market-earnings"),
    "indices": os.environ.get("DYNAMODB_TABLE_INDICES", "ocn-market-indices"),
    "market_status": os.environ.get("DYNAMODB_TABLE_MARKET_STATUS", "ocn-market-status"),
}


def _table(name: str):
    return boto3.resource("dynamodb", region_name=_AWS_REGION).Table(_TABLES[name])


def _deserialize(item: dict) -> dict:
    """Convert Decimal values to float for JSON serialisation."""
    return {
        k: float(v) if isinstance(v, Decimal) else v
        for k, v in item.items()
        if k != "ttl"
    }


def _latest(table_name: str, pk_name: str, pk_value: str) -> dict | None:
    """Return the most recent item for a partition key, or None."""
    result = _table(table_name).query(
        KeyConditionExpression=Key(pk_name).eq(pk_value),
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    return _deserialize(items[0]) if items else None


def _not_found(ticker: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"No data available for {ticker} yet. Poller may not have run.",
    )


@router.get("/market/quote/{ticker}")
def get_quote(ticker: str) -> dict:
    """Current price, change, volume, previous close for a ticker."""
    item = _latest("quote", "ticker", ticker.upper())
    if not item:
        raise _not_found(ticker)
    return item


@router.get("/market/overview/{ticker}")
def get_overview(ticker: str) -> dict:
    """Fundamentals strip: market cap, P/E, 52-week range, analyst target, beta, sector."""
    item = _latest("overview", "ticker", ticker.upper())
    if not item:
        raise _not_found(ticker)
    return item


@router.get("/market/price-history/{ticker}")
def get_price_history(ticker: str) -> dict:
    """Last 10 trading days of adjusted close prices."""
    result = _table("price_history").query(
        KeyConditionExpression=Key("ticker").eq(ticker.upper()),
        ScanIndexForward=False,
        Limit=10,
    )
    items = result.get("Items", [])
    if not items:
        raise _not_found(ticker)
    return {"ticker": ticker.upper(), "history": [_deserialize(i) for i in items]}


@router.get("/market/earnings/{ticker}")
def get_earnings(ticker: str) -> dict:
    """Next earnings date, estimated EPS, last quarter surprise %."""
    item = _latest("earnings", "ticker", ticker.upper())
    if not item:
        raise _not_found(ticker)
    return item


@router.get("/market/indices")
def get_indices() -> dict:
    """Latest price and change% for SPY, QQQ, SOXX."""
    indices = {}
    for ticker in _INDEX_TICKERS:
        item = _latest("indices", "ticker", ticker)
        if item:
            indices[ticker] = item
    if not indices:
        raise HTTPException(status_code=503, detail="No index data available yet.")
    return {"indices": indices}


@router.get("/market/status")
def get_market_status() -> dict:
    """US market open/closed status."""
    item = _latest("market_status", "market", "US")
    if not item:
        raise HTTPException(status_code=503, detail="No market status data available yet.")
    return item
