"""Pipeline execution controller."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

import pipeline as pl
from models.articles import create_articles
from models.categories import create_categories
from models.domains import get_domain_config
from models.runs import complete_run, create_run, fail_run


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


def execute(request: RunRequest) -> dict:
    """Run the pipeline and return the full response payload.

    Raises:
        KeyError: if the domain slug is not found in the database.
        ValueError: if the domain has no taxonomy categories.
    """
    config = get_domain_config(request.domain)
    if config is None:
        raise KeyError(
            f"Unknown domain slug: '{request.domain}'."
        )
    if not config["taxonomy"]:
        raise ValueError(
            f"Domain '{request.domain}' has no taxonomy categories. "
            "Add categories via POST /taxonomies before running."
        )

    max_articles = request.max_articles or 0
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    run_id = create_run(
        name=f"{request.domain}_{timestamp}",
        domain=request.domain,
        days_back=request.days_back,
        max_articles=request.max_articles,
        focus=request.focus,
    )

    try:
        result = pl.run(
            domain_slug=request.domain,
            domain_name=config["name"],
            taxonomy=config["taxonomy"],
            days_back=request.days_back,
            max_articles=max_articles,
            focus=request.focus,
        )
    except Exception as exc:
        fail_run(run_id, str(exc))
        raise

    categories = result["categories"]
    cat_id_map = create_categories(run_id, list(categories.keys()))
    all_articles = [
        {**art, "run_id": run_id, "category_id": cat_id_map[cat]}
        for cat, arts in categories.items()
        for art in arts
    ]
    if all_articles:
        create_articles(all_articles)
    complete_run(run_id, result["summary"], len(categories))

    return {
        "status": "completed",
        "run_id": run_id,
        "domain": request.domain,
        "summary": result["summary"],
        "categories": categories,
        "parameters_used": {
            "days_back": request.days_back,
            "max_articles": max_articles or "unlimited",
            "focus": request.focus,
        },
        "timestamp": timestamp,
    }
