"""DB query functions for article records."""
import json
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime as _parse_rfc2822
from typing import Optional

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


def _encode_article_cursor(article_id: int) -> str:
    """Encode an article keyset position as an opaque cursor string."""
    return encode_cursor({"id": article_id})


def _decode_article_cursor(cursor: str) -> int:
    """Decode an article cursor; raises ValueError if malformed."""
    return decode_cursor(cursor)["id"]


def _parse_published_date(published) -> Optional[datetime]:
    """Try RFC 2822 then ISO 8601; return None if unparseable.

    Accepts either a string (as fetched from pipeline sources) or a
    ``datetime`` (as read back from the ``TIMESTAMPTZ`` articles.published
    column via psycopg2). Always returns a UTC-aware datetime.
    """
    if not published:
        return None
    if isinstance(published, datetime):
        return (
            published if published.tzinfo is not None
            else published.replace(tzinfo=timezone.utc)
        )
    try:
        return _parse_rfc2822(published)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def filter_articles_for_window(
    articles: list[dict],
    days_back: int,
    max_articles: Optional[int],
    cutoff: Optional[datetime] = None,
) -> list[dict]:
    """Return articles within days_back of now, capped by max_articles.

    Articles with unparseable or missing published dates are included
    (fail-open).

    Args:
        cutoff: Explicit cutoff to filter against, e.g. a subset run's
            frozen ``window_cutoff``. Defaults to ``now() - days_back`` when
            omitted — callers that need a stable result across repeated
            reads (not recomputed against wall-clock time on every call)
            must pass an explicit, previously-frozen cutoff.
    """
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    filtered = [
        a for a in articles
        if (pub := _parse_published_date(a.get("published", "")))
        is None or pub >= cutoff
    ]
    if max_articles:
        filtered = filtered[:max_articles]
    return filtered


def get_already_stored_urls(urls: list[str]) -> set[str]:
    """Return the subset of ``urls`` already stored, across all domains.

    Global (not domain-scoped) — a URL stored under any domain's run is
    considered seen everywhere, matching the DB's global uniqueness
    constraint on ``articles.url``. Bounded to the given candidate URLs
    rather than pulling a domain's entire article history, so cost scales
    with the size of one run's fetch, not with cumulative history.

    Used to exclude previously-seen articles from a new run before they
    reach the relevance filter, a body-fetch step, or re-insertion — the
    DB's unique index on ``url`` is the final backstop if this check is
    ever skipped or races with a concurrent run.
    """
    if not urls:
        return set()
    with get_db() as conn:
        cur = conn.execute(
            "SELECT url FROM articles WHERE url = ANY(:urls)",
            {"urls": urls},
        )
        return {row["url"] for row in cur.fetchall()}


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
            " (run_id, url, title, summary, source, published, body, metadata)"
            " VALUES %s"
            " ON CONFLICT DO NOTHING",
            [
                (
                    a["run_id"],
                    a.get("url"),
                    a.get("title"),
                    a.get("summary"),
                    a.get("source"),
                    a.get("published"),
                    a.get("body"),
                    json.dumps(a["metadata"]) if a.get("metadata") else None,
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


def list_articles_for_run_resolved(
    run: dict,
    limit: int = 20,
    cursor: Optional[str] = None,
    include_body: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """Return paginated articles for a run, resolving through source_run_id.

    A subset run (CON-121) stores no article rows of its own — its
    ``source_run_id`` points at the covering run whose rows it draws from.
    This filters the covering run's articles to the subset's own
    ``days_back``/``max_articles`` window before paginating, so callers see
    the same result they would have if the rows had actually been copied.
    Runs without a ``source_run_id`` fall through to the normal per-run read.

    Filters against the subset run's frozen ``window_cutoff`` (set once at
    creation), not wall-clock time at read time — otherwise the resolved
    article set would keep shrinking on every later read as articles near
    the window boundary age out, drifting from the ``article_count`` that
    was recorded once at creation.

    Args:
        run: Full run row (as returned by ``get_run``), not just an id —
            needs ``id``, ``source_run_id``, ``days_back``, ``max_articles``,
            ``window_cutoff``.
    """
    if not run.get("source_run_id"):
        return list_articles_for_run(
            run["id"], limit=limit, cursor=cursor, include_body=include_body
        )

    source = fetch_all_articles_for_run(run["source_run_id"])
    filtered = filter_articles_for_window(
        source, run["days_back"], run.get("max_articles"),
        cutoff=run.get("window_cutoff"),
    )
    filtered.sort(key=lambda a: a["id"])

    if cursor is not None:
        after_id = _decode_article_cursor(cursor)
        filtered = [a for a in filtered if a["id"] > after_id]

    rows = filtered[:limit + 1]
    if not include_body:
        for row in rows:
            row.pop("body", None)

    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_article_cursor(rows[-1]["id"])

    return rows, next_cursor


def list_articles(
    domains: Optional[list[str]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
    include_body: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """Return paginated articles across all runs, newest id first.

    Optionally filtered to one or more domain slugs and/or a date range
    on the article published date. Body fields are omitted unless
    include_body is True.
    """
    params: dict = {"limit": limit + 1}
    clauses: list[str] = []

    if domains:
        clauses.append("r.domain = ANY(:domains)")
        params["domains"] = domains

    if from_date is not None:
        clauses.append("a.published >= :from_date")
        params["from_date"] = from_date

    if to_date is not None:
        clauses.append("a.published <= :to_date")
        params["to_date"] = to_date

    if cursor is not None:
        after_id = _decode_article_cursor(cursor)
        clauses.append("a.id < :after_id")
        params["after_id"] = after_id

    where = ("AND " + " AND ".join(clauses)) if clauses else ""

    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT a.*, r.domain FROM articles a
            JOIN runs r ON r.id = a.run_id
            WHERE TRUE {where}
            ORDER BY a.id DESC
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

    return rows, next_cursor  # type: ignore[return-value]


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
