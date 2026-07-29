"""Pipeline execution controller."""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

import httpx
from pydantic import BaseModel, Field, model_validator

import pipeline as pl
from typing import Any

from models.api_key_domains import has_domain_access
from models.articles import (
    create_articles,
    fetch_all_articles_for_run,
    filter_articles_for_window,
)
from models.atomic import atomic
from models.domains import (
    DomainConfig,
    get_domain_by_slug,
    lock_domain_row,
)
from models.runs import (
    RunRow,
    complete_run,
    create_run,
    fail_run,
    get_cached_run_today,
    get_covering_run_today,
    get_run,
    get_running_run_for_domain,
)

logger = logging.getLogger(__name__)


class RunCreateResult(TypedDict):
    """Result of create_run_record - new run or cache hit."""

    run_id: int
    cache_hit: bool
    cached_run: Optional[RunRow]
    domain_config: Optional[DomainConfig]


class RunConflictError(Exception):
    """Raised when a run is already in progress for the requested domain."""

    def __init__(self, run_id: int) -> None:
        """Store the conflicting run id."""
        super().__init__(f"Run {run_id} already in progress.")
        self.run_id = run_id


class RunRequest(BaseModel):
    """Parameters for a pipeline run."""

    domain: str = Field(
        description="Domain slug, e.g. 'ai_news' or 'smart_money'."
    )
    days_back: int = Field(
        default=7,
        ge=1,
        description="Exclude articles older than this many days.",
    )
    max_articles: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Cap on total articles fetched; omit for no limit."
        ),
    )
    focus: Optional[str] = Field(
        default=None,
        description="Optional instruction to narrow topics covered.",
    )
    callback_url: Optional[str] = Field(
        default=None,
        description=(
            "URL to POST a status payload to on run completion"
            " or failure."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "Bypass the duplicate-run guard and start a new run"
            " regardless of any in-progress run for the domain."
        ),
    )
    model: Optional[str] = Field(
        default=None,
        description=(
            "OpenRouter model string to use for relevance filtering."
            " Defaults to the server's OPENROUTER_MODEL env var."
        ),
    )
    openrouter_api_key: Optional[str] = Field(
        default=None,
        description=(
            "Caller-supplied OpenRouter API key. Required when"
            " 'model' is provided. Defaults to server's key."
        ),
    )

    @model_validator(mode="after")
    def _require_key_with_model(self) -> "RunRequest":
        """Raise if model is set without an openrouter_api_key."""
        if self.model is not None and self.openrouter_api_key is None:
            raise ValueError(
                "openrouter_api_key is required when model is provided"
            )
        return self


def _create_subset_run(
    request: RunRequest,
    resolved_model: str,
    covering: RunRow,
    domain_config: DomainConfig,
) -> RunCreateResult:
    """Create a completed run whose articles resolve through a covering run.

    Stores no article rows of its own — the global uniqueness constraint on
    ``articles.url`` (see db.py) means a URL already stored under the
    covering run's id cannot be copied into a new row. Instead this run's
    ``source_run_id`` points at the covering run; reads resolve through it,
    filtered to this run's narrower window (see CON-121, CON-147).

    The window's cutoff is computed once, here, and frozen as
    ``window_cutoff`` rather than recomputed against wall-clock time on
    every later read — otherwise articles near the window boundary could
    silently drop out of the resolved set (and article_count would drift
    out of sync with it) the longer this run sits between creation and
    being read.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=request.days_back)
    source = fetch_all_articles_for_run(covering["id"])
    filtered = filter_articles_for_window(
        source, request.days_back, request.max_articles, cutoff=cutoff
    )
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    subset_id = create_run(
        name=f"{request.domain}_{ts}",
        domain=request.domain,
        days_back=request.days_back,
        max_articles=request.max_articles,
        focus=request.focus,
        model=resolved_model,
        callback_url=request.callback_url,
        source_run_id=covering["id"],
        window_cutoff=cutoff,
    )
    complete_run(subset_id, len(filtered))
    return RunCreateResult(
        run_id=subset_id,
        cache_hit=True,
        cached_run=get_run(subset_id),
        domain_config=domain_config,
    )


def create_run_record(
    request: RunRequest, caller: dict[str, Any]
) -> RunCreateResult:
    """Validate domain ownership and create a run record.

    Returns a RunCreateResult. On a cache hit, cache_hit=True and
    cached_run contains the existing run; no new run is created.

    Raises:
        KeyError: if the domain slug is not found in the database.
        PermissionError: if the caller does not own the domain.
        RunConflictError: if a run is already in progress and force is False.
    """
    with atomic():
        lock_domain_row(request.domain)
        domain = get_domain_by_slug(request.domain)
        if domain is None:
            raise KeyError(
                f"Unknown domain slug: '{request.domain}'."
            )
        if caller["role"] != "admin":
            if domain.get("created_by") is not None:
                if not has_domain_access(
                    caller["id"], domain["id"]
                ):
                    raise PermissionError(
                        "You do not own this domain."
                    )
        resolved_model = request.model or os.environ["OPENROUTER_MODEL"]
        domain_config: DomainConfig = {
            "name": domain["name"],
            "description": domain.get("description"),
        }
        if not request.force:
            cached = get_cached_run_today(
                request.domain,
                request.days_back,
                request.focus,
                resolved_model,
            )
            if cached is not None:
                return RunCreateResult(
                    run_id=cached["id"],
                    cache_hit=True,
                    cached_run=cached,
                    domain_config=domain_config,
                )
            covering = get_covering_run_today(
                request.domain,
                request.days_back,
                request.focus,
                resolved_model,
            )
            if covering is not None:
                return _create_subset_run(
                    request, resolved_model, covering, domain_config
                )
            existing_id = get_running_run_for_domain(request.domain)
            if existing_id is not None:
                raise RunConflictError(existing_id)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        run_id = create_run(
            name=f"{request.domain}_{timestamp}",
            domain=request.domain,
            days_back=request.days_back,
            max_articles=request.max_articles,
            focus=request.focus,
            model=resolved_model,
            callback_url=request.callback_url,
        )
        return RunCreateResult(
            run_id=run_id,
            cache_hit=False,
            cached_run=None,
            domain_config=domain_config,
        )


def _fire_webhook(url: str, payload: dict) -> None:
    """POST payload to url as JSON; log but swallow any error."""
    try:
        httpx.post(url, json=payload, timeout=10.0)
    except Exception as exc:
        logger.warning("Webhook delivery failed for %s: %s", url, exc)


def run_pipeline(
    run_id: int,
    request: RunRequest,
    domain_config: DomainConfig,
) -> None:
    """Execute the pipeline in the background and update the run record."""
    max_articles = request.max_articles or 0
    resolved_model = request.model or os.environ["OPENROUTER_MODEL"]
    try:
        result = pl.run(
            domain_slug=request.domain,
            domain_name=domain_config["name"],
            domain_description=domain_config["description"],
            days_back=request.days_back,
            max_articles=max_articles,
            focus=request.focus,
            model=resolved_model,
            openrouter_api_key=request.openrouter_api_key,
        )
    except Exception as exc:
        fail_run(run_id, str(exc))
        if request.callback_url:
            _fire_webhook(request.callback_url, {
                "run_id": run_id,
                "status": "failed",
                "domain": request.domain,
                "summary": str(exc),
            })
        return

    articles = result["articles"]
    all_articles = [
        {**art, "run_id": run_id} for art in articles
    ]
    if all_articles:
        create_articles(all_articles)
    complete_run(run_id, len(articles))
    if request.callback_url:
        _fire_webhook(request.callback_url, {
            "run_id": run_id,
            "status": "completed",
            "domain": request.domain,
            "summary": None,
        })
