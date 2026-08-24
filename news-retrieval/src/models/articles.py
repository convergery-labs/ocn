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


def expire_articles_for_domain(domain: str, days: int) -> int:
    """Delete articles for a domain published more than ``days`` days ago.

    Articles with a NULL ``published`` date are never deleted (fail-open) -
    there is no reliable age to judge them by, and dropping them silently
    would lose real data. Returns the number of rows deleted.
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            DELETE FROM articles a
            USING runs r
            WHERE a.run_id = r.id
              AND r.domain = :domain
              AND a.published IS NOT NULL
              AND a.published < NOW() - (:days || ' days')::INTERVAL
            """,
            {"domain": domain, "days": days},
        )
        return cur.rowcount


def get_recent_gdelt_articles_for_ticker(
    ticker: str, hours: int = 24,
) -> list[dict]:
    """Return recently-stored GDELT articles for one ticker, for title-
    similarity dedup.

    Scoped by ``metadata->>'ticker'`` and ``created_at`` (not ``published``)
    - ``created_at`` is when we first saw the fact, which is what a rolling
    dedup window needs; GDELT's own ``seendate``/``published`` can lag or
    lead when we actually ingested it. Bounded to one ticker's recent
    articles only (a handful of rows), not the full corpus, since the
    similarity check only ever needs to compare against same-company,
    same-window candidates.

    Returns each row's ``id``, ``title``, ``url``, and ``metadata`` (which
    carries the stored ``title_embedding``, if present - rows stored before
    this field existed, or where the embedding call failed, have it absent
    and are skipped by the caller's similarity check, not treated as
    errors).
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT a.id, a.title, a.url, a.metadata
            FROM articles a
            JOIN runs r ON r.id = a.run_id
            WHERE r.domain = 'taiwan_market_signal'
              AND a.metadata->>'ticker' = :ticker
              AND a.metadata->>'source_type' = 'gdelt'
              AND a.created_at > NOW() - (:hours || ' hours')::INTERVAL
            ORDER BY a.created_at DESC
            """,
            {"ticker": ticker, "hours": hours},
        )
        return [dict(row) for row in cur.fetchall()]


def get_recent_articles_for_domain(
    domain: str, hours: int = 24,
) -> list[dict]:
    """Return recently-stored articles for one domain, for title-similarity
    dedup (same purpose as ``get_recent_gdelt_articles_for_ticker``, scoped
    by domain instead of ticker since ai_news/smart_money have no ticker
    concept).

    Scoped by ``created_at`` (not ``published``) - ``created_at`` is when we
    first saw the fact, which is what a rolling dedup window needs; a
    source's own ``published`` timestamp can lag or lead when we actually
    ingested it. Bounded to one domain's recent articles only, not the full
    corpus, since the similarity check only ever needs to compare against
    same-domain, same-window candidates.

    Returns each row's ``id``, ``title``, ``url``, and ``metadata`` (which
    carries the stored ``title_embedding``, if present - rows stored before
    this field existed, or where the embedding call failed, have it absent
    and are skipped by the caller's similarity check, not treated as
    errors).
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT a.id, a.title, a.url, a.metadata
            FROM articles a
            JOIN runs r ON r.id = a.run_id
            WHERE r.domain = :domain
              AND a.created_at > NOW() - (:hours || ' hours')::INTERVAL
            ORDER BY a.created_at DESC
            """,
            {"domain": domain, "hours": hours},
        )
        return [dict(row) for row in cur.fetchall()]


def append_also_reported_by(article_id: int, domain: str) -> None:
    """Record that another outlet (``domain``) also covered the story
    already stored as ``article_id``, without inserting a duplicate row.

    Used when a new GDELT article's title matches an already-stored
    article from an earlier poll run (cross-run duplicate) - the new
    article carries the "same story, different outlet" signal that would
    otherwise be lost by simply dropping it. Same-batch duplicates (two new
    articles in one poll run) don't need this - the surviving article
    hasn't been inserted yet, so its ``also_reported_by`` list is merged
    in-memory before the first insert instead.

    Idempotent: the ``NOT (... @> ...)`` guard means re-adding a domain
    already present in the list is a no-op, not a duplicate entry.
    """
    with get_db() as conn:
        conn.execute(
            """
            UPDATE articles
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{also_reported_by}',
                COALESCE(metadata->'also_reported_by', '[]'::jsonb)
                    || to_jsonb(:domain::text)
            )
            WHERE id = :article_id
              AND NOT COALESCE(
                  metadata->'also_reported_by' @> to_jsonb(:domain::text),
                  FALSE
              )
            """,
            {"article_id": article_id, "domain": domain},
        )


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
        # Same bug/fix as models/runs.py's list_runs: a.published is a
        # TIMESTAMPTZ, comparing directly against a bare date casts to
        # midnight and silently excludes every article published later
        # that same day. Exclusive upper bound at the next day instead.
        clauses.append("a.published < :to_date + INTERVAL '1 day'")
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
