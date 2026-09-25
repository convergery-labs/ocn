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


@router.get("/macro/series")
def list_macro_series(
    caller: dict[str, Any] = Depends(require_auth),
) -> dict:
    """The full tracked series universe (series_id + channel), straight
    from macro_signal_fetch.MACRO_SERIES_UNIVERSE - no DB query, this is
    a fixed in-memory constant. Added for the frontend's "Coverage X / Y
    series" display: X (series reporting in a window) is already
    countable from /results rows, but nothing exposed Y (total tracked)
    until this endpoint."""
    return {
        "series": [
            {"series_id": s["series_id"], "channel": s["channel"]}
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
