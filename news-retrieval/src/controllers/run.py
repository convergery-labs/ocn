"""Pipeline execution controller."""
import logging
import os
from datetime import datetime
from typing import Optional, TypedDict

import httpx
from pydantic import BaseModel, Field, model_validator

import pipeline as pl
from models.api_keys import ApiKeyRow
from models.articles import create_articles
from models.atomic import atomic
from models.domains import (
    get_domain_by_slug,
    get_domain_config,
    lock_domain_row,
)
from models.runs import (
    RunRow,
    complete_run,
    create_run,
    fail_run,
    get_cached_run_today,
    get_running_run_for_domain,
)

logger = logging.getLogger(__name__)


class RunCreateResult(TypedDict):
    """Result of create_run_record — new run or cache hit."""

    run_id: int
    cache_hit: bool
    cached_run: Optional[RunRow]


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


def create_run_record(
    request: RunRequest, caller: ApiKeyRow
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
            owner = domain.get("created_by")
            if owner is not None and owner != caller["id"]:
                raise PermissionError(
                    "You do not own this domain."
                )
        resolved_model = request.model or os.environ["OPENROUTER_MODEL"]
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
            run_id=run_id, cache_hit=False, cached_run=None
        )


def _fire_webhook(url: str, payload: dict) -> None:
    """POST payload to url as JSON; log but swallow any error."""
    try:
        httpx.post(url, json=payload, timeout=10.0)
    except Exception as exc:
        logger.warning("Webhook delivery failed for %s: %s", url, exc)


def run_pipeline(run_id: int, request: RunRequest) -> None:
    """Execute the pipeline in the background and update the run record."""
    config = get_domain_config(request.domain)
    max_articles = request.max_articles or 0
    resolved_model = request.model or os.environ["OPENROUTER_MODEL"]
    try:
        result = pl.run(
            domain_slug=request.domain,
            domain_name=config["name"],
            domain_description=config["description"],
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
