"""Routes for /articles."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.articles import get_article, list_articles

router = APIRouter()


@router.get("/articles")
def get_articles(
    domain: list[str] = Query(default=[]),
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = None,
    include_body: bool = False,
) -> dict:
    """Return paginated articles across all runs, newest id first.

    Optionally filtered by domain slugs and/or published date range.
    """
    try:
        articles, next_cursor = list_articles(
            domains=domain or None,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            cursor=cursor,
            include_body=include_body,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return {"articles": articles, "next_cursor": next_cursor}


@router.get("/articles/{article_id}")
def get_article_by_id(article_id: int) -> dict:
    """Return a single article by id."""
    article = get_article(article_id)
    if article is None:
        raise HTTPException(
            status_code=404, detail="Article not found."
        )
    return article
