"""Routes for /articles."""
from fastapi import APIRouter, HTTPException

from models.articles import get_article

router = APIRouter()


@router.get("/articles/{article_id}")
def get_article_by_id(article_id: int) -> dict:
    """Return a single article by id."""
    article = get_article(article_id)
    if article is None:
        raise HTTPException(
            status_code=404, detail="Article not found."
        )
    return article
