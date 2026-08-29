"""Repository layer - agent_jobs and agent_classifications tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


def create_job(domain: str, news_run_id: int | None = None) -> int:
    """Insert a new agent_jobs row with status=pending; return its id."""
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO agent_jobs (domain, news_run_id, status)
            VALUES (%s, %s, 'pending')
            RETURNING id
            """,
            (domain, news_run_id),
        ).fetchone()
    return int(row["id"])


def update_job_status(
    job_id: int,
    status: str,
    *,
    article_count: int | None = None,
    set_completed_at: bool = False,
) -> None:
    """Update job status and optionally article_count / completed_at."""
    if article_count is not None and set_completed_at:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_jobs
                SET status = %s, article_count = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (status, article_count, job_id),
            )
    elif article_count is not None:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s, article_count = %s WHERE id = %s",
                (status, article_count, job_id),
            )
    elif set_completed_at:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s, completed_at = NOW() WHERE id = %s",
                (status, job_id),
            )
    else:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s WHERE id = %s",
                (status, job_id),
            )


def insert_classification(job_id: int, article: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row."""
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, article_id, url, title,
                signal_detection, signal_score, signal_reason,
                materiality, category, entities_json,
                base_signal_detection, base_signal_score,
                novelty, novelty_basis, confidence, confidence_basis,
                refinement_reason, entity_names_normalized,
                pre_verification_score, verification_qa,
                published
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                article.get("id"),
                article.get("url"),
                article.get("title"),
                result["signal_detection"],
                float(result["signal_score"]),
                result.get("signal_reason"),
                result["materiality"],
                result["category"],
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                result.get("base_signal_detection"),
                result.get("base_signal_score"),
                result.get("novelty"),
                result.get("novelty_basis"),
                result.get("confidence"),
                result.get("confidence_basis"),
                result.get("refinement_reason"),
                entity_names_normalized,
                result.get("pre_verification_score"),
                json.dumps(result.get("verification_qa") or [], ensure_ascii=False),
                article.get("published"),
            ),
        )


def insert_filing_classification(job_id: int, filing: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row for an SEC filing (source_type='sec_filing').

    category is left NULL - not computed at this stage for filings.
    materiality matches the base-pass news schema (high/medium/low/none).

    ticker/form_type/item_codes/filing_filed_at and result["filing_summary"]
    (the stage-1 summarizer's structured output - headline, guidance,
    stated_figures, positives, negatives, outlook, disclosure_flags,
    citations - set by classify_filing_two_stage(), absent when the
    extraction_found=False short-circuit skipped stage 1 entirely) all go in
    metadata, not dedicated typed columns - they're sec_filing-specific the
    same way Taiwan's rank/clause-reason/translated-text fields are
    taiwan_market_signal-specific, and metadata is the existing JSONB bag for
    exactly that (see insert_taiwan_signal_classification). ticker comes
    from news-retrieval's filing metadata (the same value already used to
    build `title` below) - added so callers can filter agent_classifications
    by ticker without parsing it back out of the title string.
    """
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    metadata: dict[str, Any] = {
        "ticker": result.get("ticker"),
        "form_type": result.get("form_type"),
        "item_codes": result.get("item_codes") or [],
        "filing_filed_at": result.get("filed_at"),
    }
    if result.get("filing_summary"):
        metadata["filing_summary"] = result["filing_summary"]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, source_type, source_id, url, title,
                signal_detection, signal_score, signal_reason, materiality,
                entities_json, entity_names_normalized, metadata
            ) VALUES (%s, 'sec_filing', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                filing.get("accession_number"),
                result.get("primary_doc_url", ""),
                f"{filing.get('ticker', '')} {filing.get('form_type', '')} filing",
                result["signal_detection"],
                float(result["signal_score"]),
                result.get("signal_reason"),
                result.get("materiality"),
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                entity_names_normalized,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )


def insert_geopolitical_classification(job_id: int, article: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row for a geopolitical article (source_type='geopolitical').

    category and materiality are left NULL - the geopolitical prompt does not
    assign either (deferred to a later stage, see prompts/geopolitical_classifier_v1.txt).
    concreteness/economic_scale are the two factor sub-scores unique to this domain.
    """
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, source_type, source_id, url, title,
                signal_detection, signal_score, signal_reason,
                concreteness, economic_scale,
                entities_json, entity_names_normalized, published
            ) VALUES (%s, 'geopolitical', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                article.get("id"),
                article.get("url"),
                article.get("title"),
                result["signal_detection"],
                float(result["signal_score"]),
                result.get("signal_reason"),
                result.get("concreteness"),
                result.get("economic_scale"),
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                entity_names_normalized,
                article.get("published"),
            ),
        )


# Path 1/2 signals (revenue_rank_signal, announcement_materiality_signal)
# use HIGH/WEAK/NOISE, distinct from this table's existing
# signal/weak_signal/noise vocabulary used by the LLM-classified sources
# (news, sec_filing, geopolitical) - mapped here so taiwan_market_signal
# rows are queryable via the same signal_detection column as everything
# else (e.g. "give me today's HIGH items" doesn't need a special case).
_TAIWAN_SIGNAL_MAP = {"HIGH": "signal", "WEAK": "weak_signal", "NOISE": "noise"}


def insert_taiwan_signal_classification(
    job_id: int, article: dict[str, Any], result: dict[str, Any],
) -> None:
    """Upsert one agent_classifications row for a taiwan_market_signal item
    (source_type='taiwan_market_signal') - a TWSE/TPEx revenue or material
    announcement row read from news-retrieval.

    Unlike the LLM-classified source types above, revenue ranking and
    clause-code lookup are computed here (not news-retrieval - see
    conversation decision to keep news-retrieval fetch/dedup-only), so
    ``result`` carries a rank- or lookup-derived HIGH/WEAK/NOISE signal
    rather than a model's signal/weak_signal/noise judgment. Mapped onto
    the existing signal_detection column via _TAIWAN_SIGNAL_MAP so these
    rows are queryable the same way as every other source_type.

    Digest-composition fields (rank, translated text, percentages, etc.)
    have no equivalent typed column on this table and go in ``metadata``
    instead - same JSONB-bag rationale as news-retrieval's articles.metadata.
    category/materiality/entities_json are left at their defaults (NULL/
    '[]') - this source type doesn't use the LLM-classification vocabulary
    those columns were built for.
    """
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, source_type, source_id, url, title,
                signal_detection, signal_score, signal_reason,
                published, metadata
            ) VALUES (%s, 'taiwan_market_signal', %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                result.get("source_id"),
                article.get("url"),
                article.get("title"),
                _TAIWAN_SIGNAL_MAP[result["signal"]],
                result.get("signal_score", 1.0),
                result.get("reason"),
                article.get("published"),
                json.dumps(result.get("metadata") or {}, ensure_ascii=False),
            ),
        )


def get_existing_taiwan_source_ids(source_ids: list[str]) -> set[str]:
    """Return the subset of source_ids already classified as
    source_type='taiwan_market_signal', across ALL prior jobs (not scoped
    to today or to one job_id) - the twice-daily run must never reclassify
    a ticker+period/ticker+timestamp combination once it exists, since the
    idx_agent_classifications_taiwan_source_id unique index would reject a
    duplicate insert anyway; checking first avoids wasting an LLM/lookup
    call on something we already know will be a no-op.

    Same shape as get_existing_filing_source_ids - one batched query, not
    one per item.
    """
    if not source_ids:
        return set()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT source_id FROM agent_classifications
            WHERE source_type = 'taiwan_market_signal' AND source_id = ANY(%s)
            """,
            (source_ids,),
        ).fetchall()
    return {r["source_id"] for r in rows}


def get_taiwan_revenue_rows_for_periods(periods: list[str]) -> list[dict[str, Any]]:
    """Return existing mops_revenue rows already stored for the given
    period_gregorian values, across ALL prior jobs.

    Used to re-rank a period's full known field (already-stored rows +
    today's newly-fetched ones) rather than ranking today's arrivals in
    isolation - a straggler filing that arrives after the rest of the
    period's companies would otherwise get ranked against only itself
    ("rank 1 of 1") instead of the true field size. These rows are read-only
    context for the rank computation; only update_taiwan_revenue_rank below
    writes any of them back.
    """
    if not periods:
        return []
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, source_id, metadata
            FROM agent_classifications
            WHERE source_type = 'taiwan_market_signal'
              AND metadata->>'source_category' = 'mops_revenue'
              AND metadata->>'period_gregorian' = ANY(%s)
            """,
            (periods,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_taiwan_revenue_rank(
    source_id: str,
    *,
    revenue_rank_signal: str,
    signal_reason: str,
    metadata: dict[str, Any],
) -> None:
    """Overwrite an existing mops_revenue row's rank/signal fields after a
    later arrival in the same period changed the true field size.

    ``revenue_rank_signal`` is HIGH/WEAK (rank_revenue_by_yoy's own
    vocabulary, same as insert_taiwan_signal_classification's ``signal``
    param) - mapped to signal_detection's signal/weak_signal vocabulary via
    _TAIWAN_SIGNAL_MAP here so callers don't need to know about that
    mapping, same division of responsibility as the insert path.

    Only called when the newly-computed rank actually differs from what's
    stored (see rank_revenue_by_yoy's changed-row detection) - most re-ranks
    don't move anyone's position and this is a no-op for those rows. The
    previous rank/signal are preserved in metadata.rank_revision_history so
    a caller can see a row was revised rather than treating a changed value
    as if it had always been that way.
    """
    with get_db() as conn:
        conn.execute(
            """
            UPDATE agent_classifications
            SET signal_detection = %s, signal_reason = %s, metadata = %s
            WHERE source_type = 'taiwan_market_signal' AND source_id = %s
            """,
            (
                _TAIWAN_SIGNAL_MAP[revenue_rank_signal],
                signal_reason,
                json.dumps(metadata, ensure_ascii=False),
                source_id,
            ),
        )


def get_existing_filing_source_ids(source_ids: list[str]) -> set[str]:
    """Return the subset of source_ids (accession_numbers) already classified
    as source_type='sec_filing'. One batched query, not one per filing - used
    to diff a day's fetched filings against what's already in the table before
    calling the classifier, so unchanged filings are never reclassified.
    """
    if not source_ids:
        return set()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT source_id FROM agent_classifications
            WHERE source_type = 'sec_filing' AND source_id = ANY(%s)
            """,
            (source_ids,),
        ).fetchall()
    return {r["source_id"] for r in rows}


def get_filing_source_ids_missing_ticker() -> list[str]:
    """Return source_ids (accession_numbers) for sec_filing rows whose
    metadata has no 'ticker' key yet - the backfill target set for
    backfill_filing_tickers(). One-time migration: rows written before
    insert_filing_classification() started storing ticker in metadata.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT source_id FROM agent_classifications
            WHERE source_type = 'sec_filing'
              AND (metadata IS NULL OR NOT (metadata ? 'ticker'))
        """).fetchall()
    return [r["source_id"] for r in rows if r["source_id"]]


def backfill_filing_tickers(accession_to_ticker: dict[str, str]) -> int:
    """Merge 'ticker' into metadata for existing sec_filing rows, keyed by
    accession_number (source_id). accession_to_ticker is built by the caller
    from news-retrieval's own GET /market/sec-filings/{ticker} - the same
    source insert_filing_classification() originally used - never guessed
    from the title string, which is display-only and not guaranteed to
    parse back into a valid ticker for every filer. Returns the number of
    rows updated; a source_id with no entry in the map is left untouched
    (news-retrieval's DynamoDB has a 180-day TTL, so a very old filing's
    ticker may no longer be resolvable this way).
    """
    if not accession_to_ticker:
        return 0
    with get_db() as conn:
        updated = 0
        for source_id, ticker in accession_to_ticker.items():
            result = conn.execute(
                """
                UPDATE agent_classifications
                SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('ticker', %s)
                WHERE source_type = 'sec_filing' AND source_id = %s
                """,
                (ticker, source_id),
            )
            updated += result.rowcount
    return updated


def get_recent_entity_classifications(
    entity_names: list[str],
    *,
    days: int = 90,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Return recent rows that mention any of the given entity names.

    Includes signal/weak_signal rows (for novelty and downgrade decisions) and
    borderline noise rows with signal_score >= 0.28 (as escalation context).
    Stage 2 uses the signal_detection field to distinguish the two.
    """
    if not entity_names:
        return []
    normalized_names = [name.lower() for name in entity_names]
    placeholders = ", ".join(["%s"] * len(normalized_names))
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT signal_detection, signal_score, signal_reason, category,
                   entities_json, title, url, stored_at
            FROM agent_classifications
            WHERE stored_at >= NOW() - INTERVAL '{days} days'
              AND (
                signal_detection IN ('signal', 'weak_signal')
                OR (signal_detection = 'noise' AND signal_score >= 0.28)
              )
              AND entity_names_normalized && ARRAY[{placeholders}]::TEXT[]
            ORDER BY stored_at DESC
            LIMIT %s
            """,
            [*normalized_names, limit],
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        if rec.get("signal_score") is not None:
            rec["signal_score"] = float(rec["signal_score"])
        if rec.get("stored_at") is not None:
            rec["stored_at"] = rec["stored_at"].isoformat()
        results.append(rec)
    return results


def get_completed_job_for_run(news_run_id: int) -> dict[str, Any] | None:
    """Return the most recent completed job for a given news_run_id, or None."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM agent_jobs
            WHERE news_run_id = %s AND status = 'completed'
            ORDER BY id DESC LIMIT 1
            """,
            (news_run_id,),
        ).fetchone()
    return dict(row) if row else None


def get_job(job_id: int) -> dict[str, Any] | None:
    """Return a single agent_jobs row, or None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_jobs WHERE id = %s", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def list_jobs(
    limit: int = 20,
    cursor: str | None = None,
    status: str | None = "completed",
    domain: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_jobs, newest-first. Defaults to completed only.

    domain filters to agent_jobs.domain - callers that poll for "the latest
    job" across multiple domains (news, sec_filing, ...) must pass this,
    otherwise "most recent completed job" can return a job from a different
    domain than the one they actually wanted (e.g. a same-day SEC filing job
    completing after the news job would otherwise silently win).
    """
    params: list[Any] = []
    conditions: list[str] = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if domain:
        conditions.append("domain = %s")
        params.append(domain)
    if cursor:
        after_id = decode_cursor(cursor)
        conditions.append("id < %s")
        params.append(after_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_jobs {where} ORDER BY id DESC LIMIT %s",
            params,
        ).fetchall()
    jobs = [dict(r) for r in rows]
    next_cursor = None
    if len(jobs) > limit:
        jobs = jobs[:limit]
        next_cursor = encode_cursor(jobs[-1]["id"])
    return {"jobs": jobs, "next_cursor": next_cursor}


def list_all_results(
    limit: int = 100,
    cursor: str | None = None,
    signal_detection: str | None = None,
    source_type: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications across all jobs, newest first.

    ticker matches metadata->>'ticker' (JSONB) - the only place ticker is
    stored today (see insert_filing_classification). Only sec_filing rows
    populate this field currently, so combining ticker with another
    source_type filter returns no rows, same as querying a mismatched
    source_type/signal_detection pair would. Matched case-insensitively
    (UPPER() both sides) since callers may pass a lowercase ticker; this
    also matches the expression index on UPPER(metadata->>'ticker') in
    db.py, so the comparison stays index-friendly rather than falling back
    to a sequential scan.
    """
    params: list[Any] = []
    conditions = []
    if signal_detection:
        conditions.append("signal_detection = %s")
        params.append(signal_detection)
    if source_type:
        conditions.append("source_type = %s")
        params.append(source_type)
    if ticker:
        conditions.append("UPPER(metadata->>'ticker') = UPPER(%s)")
        params.append(ticker)
    if cursor:
        after_id = decode_cursor(cursor)
        conditions.append("id < %s")
        params.append(after_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_classifications
            {where}
            ORDER BY id DESC LIMIT %s
            """,
            params,
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        results.append(rec)
    next_cursor = None
    if len(results) > limit:
        results = results[:limit]
        next_cursor = encode_cursor(results[-1]["id"])
    return {"results": results, "next_cursor": next_cursor}


def list_results(
    job_id: int,
    limit: int = 100,
    cursor: str | None = None,
    signal_detection: str | None = None,
    source_type: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications for a job.

    ticker matches metadata->>'ticker' - see list_all_results for details.
    """
    params: list[Any] = [job_id]
    extra_conditions = ""
    if signal_detection:
        extra_conditions += " AND signal_detection = %s"
        params.append(signal_detection)
    if source_type:
        extra_conditions += " AND source_type = %s"
        params.append(source_type)
    if ticker:
        extra_conditions += " AND UPPER(metadata->>'ticker') = UPPER(%s)"
        params.append(ticker)
    if cursor:
        after_id = decode_cursor(cursor)
        extra_conditions += " AND id > %s"
        params.append(after_id)
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_classifications
            WHERE job_id = %s {extra_conditions}
            ORDER BY id ASC LIMIT %s
            """,
            params,
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        results.append(rec)
    next_cursor = None
    if len(results) > limit:
        results = results[:limit]
        next_cursor = encode_cursor(results[-1]["id"])
    return {"results": results, "next_cursor": next_cursor}
