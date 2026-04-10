"""Pipeline execution controller."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

import pipeline as pl
from models.domains import get_domain_configs


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
    summary_depth: Literal["brief", "detailed"] = Field(
        default="detailed",
        description="Depth of per-article summaries.",
    )
    focus: Optional[str] = Field(
        default=None,
        description="Optional instruction to narrow topics covered.",
    )


def execute(request: RunRequest) -> dict:
    """Run the two-pass pipeline and return the full response payload.

    Raises:
        KeyError: if the domain slug is not found in the database.
        ValueError: if the domain has no taxonomy categories.
    """
    configs = get_domain_configs()
    config = configs.get(request.domain)
    if config is None:
        raise KeyError(
            f"Unknown domain '{request.domain}'. "
            f"Known domains: {list(configs)}"
        )
    if not config["taxonomy"]:
        raise ValueError(
            f"Domain '{request.domain}' has no taxonomy categories. "
            "Add categories via POST /taxonomies before running."
        )

    max_articles = request.max_articles or 0
    result = pl.run(
        domain_slug=request.domain,
        domain_name=config["name"],
        taxonomy=config["taxonomy"],
        days_back=request.days_back,
        max_articles=max_articles,
        summary_depth=request.summary_depth,
        focus=request.focus,
    )
    return {
        "status": "completed",
        "domain": request.domain,
        "summary": result["summary"],
        "reports": result["reports"],
        "parameters_used": {
            "days_back": request.days_back,
            "max_articles": max_articles or "unlimited",
            "summary_depth": request.summary_depth,
            "focus": request.focus,
        },
        "timestamp": datetime.now().isoformat(),
    }
