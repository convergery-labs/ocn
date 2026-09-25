"""Routes for /macro - read macro_signal observations from Postgres,
and trigger a fetch.

Not under /market/* - that prefix is DynamoDB-backed elsewhere
(routes/market.py) and is forced to require auth at the api-gateway
proxy layer specifically. /macro/* instead enforces its own auth
directly on each route via Depends(require_auth)/Depends(require_admin)
- CONFIRMED LIVE (2026-09-25) that relying on the gateway alone is not
safe: the api-gateway's /news/* proxy uses optional_auth except for a
path.startswith("market/") special case, so any route under this
prefix that doesn't declare its own auth dependency is reachable with
no Authorization header at all. GET /macro/observations was missing
this and served real data unauthenticated until this fix - do not
assume gateway-level enforcement for any future route added here."""
import os
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import require_admin, require_auth
from controllers.macro_run import create_macro_fetch_run, run_macro_fetch
from macro_signal_fetch import MACRO_SERIES_UNIVERSE
from models.macro_observations import get_macro_observations

router = APIRouter()

# Real ask (frontend ticket, 2026-09-25): /macro/series returned only
# series_id + channel, so the UI could only show a raw FRED code
# (T10Y2Y) and a raw native-unit change (+0.05) instead of a real name
# and "+5bp". Display-only metadata, kept separate from
# MACRO_SERIES_UNIVERSE (news-retrieval's own fetch config - source_type/
# revised flags the fetcher needs, not display concerns) rather than
# adding display fields to that dict. Every entry here must have a
# MACRO_SERIES_UNIVERSE counterpart - checked once at import time below
# so a future series addition can't silently ship without a display name.
MACRO_SERIES_DISPLAY: dict[str, dict[str, str]] = {
    "DFII10": {"name": "10-Year TIPS Yield", "unit": "percent"},
    "DFII5": {"name": "5-Year TIPS Yield", "unit": "percent"},
    "T10YIE": {"name": "10-Year Breakeven Inflation Rate", "unit": "percent"},
    "T5YIFR": {"name": "5-Year, 5-Year Forward Inflation Expectation", "unit": "percent"},
    "T10Y2Y": {"name": "10Y-2Y Treasury Spread", "unit": "percent"},
    "T10Y3M": {"name": "10Y-3M Treasury Spread", "unit": "percent"},
    "DGS10": {"name": "10-Year Treasury Yield", "unit": "percent"},
    "DGS3MO": {"name": "3-Month Treasury Yield", "unit": "percent"},
    "DGS2": {"name": "2-Year Treasury Yield", "unit": "percent"},
    "DGS1": {"name": "1-Year Treasury Yield", "unit": "percent"},
    "DFF": {"name": "Effective Federal Funds Rate", "unit": "percent"},
    "DFEDTARU": {"name": "Federal Funds Target Rate (Upper Bound)", "unit": "percent"},
    "FEDTARMD": {"name": "Federal Funds Rate Median Projection (SEP)", "unit": "percent"},
    "BAA10Y": {"name": "Moody's Baa Corporate Bond Spread over 10-Year Treasury", "unit": "percent"},
    "NFCI": {"name": "Chicago Fed National Financial Conditions Index", "unit": "index"},
    "ANFCI": {"name": "Chicago Fed Adjusted National Financial Conditions Index", "unit": "index"},
    "NFCICREDIT": {"name": "Chicago Fed NFCI Credit Subindex", "unit": "index"},
    "DRTSCILM": {"name": "Net % of Banks Tightening C&I Loan Standards", "unit": "percent"},
    "WALCL": {"name": "Federal Reserve Total Assets", "unit": "millions_usd"},
    "RRPONTSYD": {"name": "Overnight Reverse Repurchase Agreements", "unit": "billions_usd"},
    "WTREGEN": {"name": "Treasury General Account Balance", "unit": "billions_usd"},
    "WRESBAL": {"name": "Reserve Balances with Federal Reserve Banks", "unit": "billions_usd"},
    "TOTRESNS": {"name": "Total Reserves of Depository Institutions", "unit": "billions_usd"},
    "DTWEXBGS": {"name": "Trade Weighted U.S. Dollar Index (Broad)", "unit": "index"},
    "ICSA": {"name": "Initial Jobless Claims", "unit": "count"},
    "WEI": {"name": "Weekly Economic Index", "unit": "percent"},
    "GACDFSA066MSFRBPHI": {"name": "Philadelphia Fed Coincident Diffusion Index", "unit": "index"},
    "NEWORDER": {"name": "Manufacturers' New Orders: Nondefense Capital Goods ex-Aircraft", "unit": "millions_usd"},
    "close_today_bal": {"name": "Treasury Daily Closing Cash Balance", "unit": "millions_usd"},
    "CPIAUCSL": {"name": "Consumer Price Index (All Items)", "unit": "index"},
    "CPILFESL": {"name": "Core Consumer Price Index (ex Food & Energy)", "unit": "index"},
    "PCEPILFE": {"name": "Core PCE Price Index", "unit": "index"},
    "PAYEMS": {"name": "Nonfarm Payrolls", "unit": "thousands"},
    "UNRATE": {"name": "Unemployment Rate", "unit": "percent"},
    "SAHMREALTIME": {"name": "Sahm Rule Recession Indicator", "unit": "percentage_points"},
    "JTSJOL": {"name": "Job Openings (JOLTS)", "unit": "thousands"},
    "CCSA": {"name": "Continued Jobless Claims", "unit": "count"},
    "RSAFS": {"name": "Retail Sales", "unit": "millions_usd"},
    "HOUST": {"name": "Housing Starts", "unit": "thousands"},
    "PERMIT": {"name": "Building Permits", "unit": "thousands"},
    "MORTGAGE30US": {"name": "30-Year Fixed Mortgage Rate", "unit": "percent"},
    "CSUSHPINSA": {"name": "S&P/Case-Shiller Home Price Index", "unit": "index"},
    "TOTALSL": {"name": "Total Consumer Credit Outstanding", "unit": "billions_usd"},
    "DRCCLACBS": {"name": "Credit Card Delinquency Rate", "unit": "percent"},
    "VIXCLS": {"name": "CBOE Volatility Index (VIX)", "unit": "index"},
    "VXVCLS": {"name": "CBOE 3-Month Volatility Index", "unit": "index"},
}

_missing_display = [s["series_id"] for s in MACRO_SERIES_UNIVERSE if s["series_id"] not in MACRO_SERIES_DISPLAY]
assert not _missing_display, f"MACRO_SERIES_DISPLAY is missing entries for: {_missing_display}"


@router.get("/macro/series")
def list_macro_series(
    caller: dict[str, Any] = Depends(require_auth),
) -> dict:
    """The full tracked series universe (series_id, channel, display
    name, unit), straight from macro_signal_fetch.MACRO_SERIES_UNIVERSE
    + this module's own MACRO_SERIES_DISPLAY map - no DB query, both are
    fixed in-memory constants. Added for the frontend's "Coverage X / Y
    series" display: X (series reporting in a window) is already
    countable from /results rows, but nothing exposed Y (total tracked)
    until this endpoint; name/unit added on a follow-up ticket so the UI
    isn't limited to showing raw FRED codes and raw native-unit deltas."""
    return {
        "series": [
            {
                "series_id": s["series_id"], "channel": s["channel"],
                "name": MACRO_SERIES_DISPLAY[s["series_id"]]["name"],
                "unit": MACRO_SERIES_DISPLAY[s["series_id"]]["unit"],
            }
            for s in MACRO_SERIES_UNIVERSE
        ],
        "total": len(MACRO_SERIES_UNIVERSE),
    }


@router.get("/macro/observations")
def list_macro_observations(
    series: list[str] = Query(default=[]),
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(default=500, ge=1, le=2000),
    cursor: Optional[str] = None,
    caller: dict[str, Any] = Depends(require_auth),
) -> dict:
    """Cursor-paginated macro_observations rows, optionally filtered by
    series_id and/or observation_date range. Consumed by
    signal-detection-agent's macro_signal pipeline adapter.

    CONFIRMED LIVE (2026-09-25, real staging ALB request with no
    Authorization header): this route was missing Depends(require_auth)
    entirely - the module docstring's claim that this prefix is
    "gateway-proxied automatically" assumed the route itself enforced
    auth the way every other GET route in this file does; it never did.
    Real macro_observations data (3 years of FRED/Treasury history) was
    served to unauthenticated requests until this fix."""
    try:
        observations, next_cursor = get_macro_observations(
            series_ids=series or None,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            cursor=cursor,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return {"observations": observations, "next_cursor": next_cursor}


class MacroFetchRequest(BaseModel):
    incremental: bool = False


@router.post("/macro/fetch", status_code=202)
async def trigger_macro_fetch(
    body: MacroFetchRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Trigger a macro_signal fetch (FRED + Treasury Fiscal Data),
    tracked as a real `runs` row (GET /runs?domain=macro_signal), same
    as every other domain's fetch - see controllers/macro_run.py's own
    docstring for why this bypasses POST /run's generic
    create_run_record/run_pipeline path rather than reusing it outright.

    incremental=false (default): full 3-year backfill re-pull per
    series - the one-time initial backfill, or a deliberate re-backfill.
    Takes several minutes (hundreds of real FRED/Treasury HTTP calls
    with rate-limit backoff) - runs in the background, poll GET
    /runs/{run_id} for status.
    incremental=true: the ~1-day fetch window used by the twice-daily
    schedule.

    require_admin (not plain require_auth) since this triggers real
    external API calls under a shared FRED_API_KEY credential and can
    run for several minutes - same privilege tier as
    frequencies.py/grants.py's own admin-only mutations.
    """
    fred_api_key = os.environ.get("FRED_API_KEY")
    if not fred_api_key:
        raise HTTPException(status_code=500, detail="FRED_API_KEY is not configured.")

    run_id = create_macro_fetch_run(incremental=body.incremental)
    background_tasks.add_task(run_macro_fetch, run_id, fred_api_key, incremental=body.incremental)
    return JSONResponse(status_code=202, content={"run_id": run_id, "status": "running"})
