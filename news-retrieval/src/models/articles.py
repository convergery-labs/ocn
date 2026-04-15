"""DB query functions for article records."""
from typing import Optional

from db import get_db


def create_articles(articles: list[dict]) -> None:
    """Batch-insert article records.

    Args:
        articles: List of article dicts with keys:
            ``run_id``, ``category_id``, ``url``, ``title``,
            ``summary``, ``source``, ``published``.
    """
    if not articles:
        return
    with get_db() as conn:
        conn.execute_values(
            "INSERT INTO articles"
            " (run_id, category_id, url, title,"
            "  summary, source, published)"
            " VALUES %s",
            [
                (
                    a["run_id"],
                    a["category_id"],
                    a.get("url"),
                    a.get("title"),
                    a.get("summary"),
                    a.get("source"),
                    a.get("published"),
                )
                for a in articles
            ],
        )


def list_articles_for_run(run_id: int) -> list[dict]:
    """Return all articles for a run, ordered by id."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM articles WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_articles_for_category(
    run_id: int,
    category_id: int,
) -> list[dict]:
    """Return articles for a specific category within a run."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM articles"
            " WHERE run_id = ? AND category_id = ?"
            " ORDER BY id",
            (run_id, category_id),
        )
        return [dict(row) for row in cur.fetchall()]


def get_article(article_id: int) -> Optional[dict]:
    """Return a single article by id, or None if not found."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM articles WHERE id = ?",
            (article_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
