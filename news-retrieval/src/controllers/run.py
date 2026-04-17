"""Pipeline execution controller."""
import logging
from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel, Field

import pipeline as pl
from models.articles import create_articles
from models.domains import get_domain_config
from models.runs import complete_run, create_run, fail_run

logger = logging.getLogger(__name__)


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


def create_run_record(request: RunRequest) -> int:
    """Validate domain and create a run record; return the run_id.

    Raises:
        KeyError: if the domain slug is not found in the database.
    """
    config = get_domain_config(request.domain)
    if config is None:
        raise KeyError(
            f"Unknown domain slug: '{request.domain}'."
        )
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return create_run(
        name=f"{request.domain}_{timestamp}",
        domain=request.domain,
        days_back=request.days_back,
        max_articles=request.max_articles,
        focus=request.focus,
        callback_url=request.callback_url,
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
    try:
        result = pl.run(
            domain_slug=request.domain,
            domain_name=config["name"],
            domain_description=config["description"],
            days_back=request.days_back,
            max_articles=max_articles,
            focus=request.focus,
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
