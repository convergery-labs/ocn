"""DB query functions for article records."""
from typing import Optional

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


def _encode_article_cursor(article_id: int) -> str:
    """Encode an article keyset position as an opaque cursor string."""
    return encode_cursor({"id": article_id})


def _decode_article_cursor(cursor: str) -> int:
    """Decode an article cursor; raises ValueError if malformed."""
    return decode_cursor(cursor)["id"]


def create_articles(articles: list[dict]) -> None:
    """Batch-insert article records.

    Args:
        articles: List of article dicts with keys:
            ``run_id``, ``url``, ``title``,
            ``summary``, ``source``, ``published``.
    """
    if not articles:
        return
    with get_db() as conn:
        conn.execute_values(
            "INSERT INTO articles"
            " (run_id, url, title, summary, source, published, body)"
            " VALUES %s",
            [
                (
                    a["run_id"],
                    a.get("url"),
                    a.get("title"),
                    a.get("summary"),
                    a.get("source"),
                    a.get("published"),
                    a.get("body"),
                )
                for a in articles
            ],
        )


def list_articles_for_run(
    run_id: int,
    limit: int = 20,
    cursor: Optional[str] = None,
    include_body: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """Return paginated articles for a run, ordered by id asc.

    Returns a (rows, next_cursor) tuple. next_cursor is None when
    there are no further pages. Body fields are omitted unless
    include_body is True.
    """
    params: dict = {"run_id": run_id, "limit": limit + 1}
    after_clause = ""

    if cursor is not None:
        after_id = _decode_article_cursor(cursor)
        after_clause = "AND id > :after_id"
        params["after_id"] = after_id

    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT * FROM articles
            WHERE run_id = :run_id {after_clause}
            ORDER BY id ASC
            LIMIT :limit
            """,
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]

    if not include_body:
        for row in rows:
            row.pop("body", None)

    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_article_cursor(rows[-1]["id"])

    return rows, next_cursor


def list_articles(
    domain: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
    include_body: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """Return paginated articles across all runs, ordered by id asc.

    Optionally filtered to a single domain slug. Body fields are
    omitted unless include_body is True.
    """
    params: dict = {"limit": limit + 1}
    domain_clause = ""
    after_clause = ""

    if domain is not None:
        domain_clause = "AND r.domain = :domain"
        params["domain"] = domain

    if cursor is not None:
        after_id = _decode_article_cursor(cursor)
        after_clause = "AND a.id > :after_id"
        params["after_id"] = after_id

    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT a.*, r.domain FROM articles a
            JOIN runs r ON r.id = a.run_id
            WHERE TRUE {domain_clause} {after_clause}
            ORDER BY a.id ASC
            LIMIT :limit
            """,
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]

    if not include_body:
        for row in rows:
            row.pop("body", None)

    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_article_cursor(rows[-1]["id"])

    return rows, next_cursor


def fetch_all_articles_for_run(run_id: int) -> list[dict]:
    """Return all article rows for a run as dicts (no pagination)."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM articles"
            " WHERE run_id = :run_id ORDER BY id ASC",
            {"run_id": run_id},
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
