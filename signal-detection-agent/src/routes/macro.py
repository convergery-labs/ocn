"""Routes for /macro - trigger the macro_signal fetch+classify chain.

Mirrors news-retrieval's own routes/macro.py naming for consistency
(both services now expose a /macro/* HTTP surface for this domain -
news-retrieval's is the raw fetch trigger + observation reads, this
one is the fetch-then-classify orchestration).

Deliberately NOT under POST /run - that generic route
(routes/run.py) is built around news-retrieval's article-domain run
model (news_run_id, use_latest_run, force) which macro_signal doesn't
have (see controllers.run.run_macro_signal_full_chain's own docstring
for why this spans two services' own run/job tables instead of one
unified concept)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from auth import require_admin
from controllers.run import run_macro_signal_full_chain
from models.jobs import create_job

router = APIRouter()


class MacroRunRequest(BaseModel):
    incremental: bool = False
    from_date: str | None = None
    to_date: str | None = None
    today: bool = False


@router.post("/macro/run", status_code=202)
async def trigger_macro_run(
    body: MacroRunRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Trigger the full macro_signal chain: news-retrieval fetch (real
    3-year backfill if incremental=false, the default) -> FOMC calendar
    refresh -> Z-SCORE->TIER->SUPPRESS->COLLAPSE->INTERPRET pipeline for
    [from_date, to_date] (defaults to yesterday UTC, or today UTC if
    today=true - same semantics as run-macro-signal-pipeline's own
    --today flag, see __main__.py).

    Returns THIS service's agent_jobs job_id immediately (poll GET
    /jobs/{job_id} or GET /jobs/{job_id}/results for progress/output) -
    the whole chain, including news-retrieval's own fetch, runs in the
    background under this one job_id on signal-detection-agent's side,
    even though news-retrieval tracks its own piece of the work as a
    separate run_id in its own runs table (logged, not surfaced here -
    see run_macro_signal_full_chain's own docstring).

    require_admin - triggers a real, potentially multi-minute chain of
    external API calls (FRED/Treasury) and real LLM interpretation
    calls under shared credentials, same privilege tier as
    news-retrieval's own POST /macro/fetch.
    """
    from datetime import datetime, timedelta, timezone

    job_id = create_job(domain=config.MACRO_SIGNAL_DOMAIN)

    default_offset_days = 0 if body.today else 1
    default_date = (datetime.now(timezone.utc) - timedelta(days=default_offset_days)).strftime("%Y-%m-%d")
    from_date = body.from_date or default_date
    to_date = body.to_date or default_date

    background_tasks.add_task(
        run_macro_signal_full_chain, job_id, from_date, to_date, incremental=body.incremental,
    )
    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running"})
