"""Orchestration - fetch articles from news-retrieval, classify via LLM, persist."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import config
from adapters.news_client import (
    NewsRetrievalError,
    fetch_latest_run,
    get_run_articles,
    list_completed_runs,
    poll_run_until_done,
    trigger_run,
)
from models.jobs import (
    create_job,
    get_completed_job_for_run,
    get_existing_taiwan_source_ids,
    get_taiwan_revenue_rows_for_periods,
    insert_taiwan_signal_classification,
    update_job_status,
    update_taiwan_revenue_rank,
)
from pipeline.classifier import has_usable_body
from pipeline.dispatch import get_domain_config, known_domains
from pipeline.taiwan_signal_classifier import classify_taiwan_signal_batch

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.CLASSIFY_CONCURRENCY)


async def resolve_news_run_id(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
) -> int:
    """Resolve which news-retrieval run to classify against."""
    if run_id is not None:
        await poll_run_until_done(run_id)
        return run_id
    if use_latest_run:
        existing = await fetch_latest_run(domain)
        if existing is not None:
            return existing
    resolved = await trigger_run(domain, days_back)
    await poll_run_until_done(resolved)
    return resolved


async def submit_run(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
    force: bool,
) -> tuple[int, int, bool]:
    """Resolve news_run_id, check cache, create job if needed.

    Returns (job_id, news_run_id, cached) where cached=True means an existing
    completed job was found and no new classification run is needed.
    """
    news_run_id = await resolve_news_run_id(domain, run_id, days_back, use_latest_run)
    if not force:
        existing = get_completed_job_for_run(news_run_id)
        if existing:
            return int(existing["id"]), news_run_id, True
    job_id = create_job(domain=domain, news_run_id=news_run_id)
    return job_id, news_run_id, False


def _is_period_in_active_filing_window(period_gregorian: str) -> bool:
    """A revenue period is only re-ranked against newly-arrived stragglers
    while it's the current or previous calendar month (UTC) - TWSE/TPEx
    monthly filings land within roughly the first 2-3 weeks after
    month-end, so anything older than that is treated as closed: no more
    re-ranking, no more update_taiwan_revenue_rank calls for it, ever.

    This bounds how long a stored row can change after the fact to a
    known, short window, rather than every row being mutable forever -
    the tradeoff decided over rank correctness vs. mutable history: fix
    the field size while filings are still trickling in for a period, but
    don't reopen a period that's long since settled.
    """
    try:
        period = datetime.strptime(period_gregorian, "%Y-%m").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    today = datetime.now(timezone.utc)
    months_diff = (today.year - period.year) * 12 + (today.month - period.month)
    return 0 <= months_diff <= 1


async def run_taiwan_signal_classification(job_id: int, from_date: str, to_date: str) -> None:
    """Classify taiwan_market_signal items across ALL of news-retrieval's
    completed runs in [from_date, to_date] - not just the latest run.

    news-retrieval polls this domain every 30 minutes, so a single day can
    have ~30 separate completed runs; fetch_latest_run/get_run_articles
    (built for the single-run news/sec_filing/geopolitical paths) would
    silently see only the most recent one. This function instead lists
    every completed run in the window and pools their articles before
    classifying, so a twice-daily pass sees the full day's fetched data.

    Only classifies items not already classified - checked via
    get_existing_taiwan_source_ids against the (ticker+period or
    ticker+timestamp) source_id classify_taiwan_signal_batch derives, not
    against article id, since the same underlying fact can legitimately
    appear in multiple news-retrieval runs (re-fetched, not yet superseded)
    and must still only be classified once.

    Revenue ranking is period-scoped, not just today's-batch-scoped: for
    every mops_revenue period present in today's pooled articles, this
    also pulls the already-stored rows for that period (if it's still in
    the active filing window - see _is_period_in_active_filing_window) as
    read-only ranking context, so a late-arriving filing gets ranked
    against the true known field instead of just itself. Any already-
    stored row whose rank/signal changes as a result is updated in place
    via update_taiwan_revenue_rank - see that function and
    rank_revenue_by_yoy's docstrings for why this is the one place
    taiwan_market_signal data is allowed to change after insert.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.TAIWAN_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch taiwan_market_signal articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    revenue_periods = {
        a["metadata"]["period_gregorian"]
        for a in all_articles
        if (a.get("metadata") or {}).get("source_category") == "mops_revenue"
        and a["metadata"].get("period_gregorian")
    }
    active_periods = [p for p in revenue_periods if _is_period_in_active_filing_window(p)]
    revenue_context = get_taiwan_revenue_rows_for_periods(active_periods)
    # get_taiwan_revenue_rows_for_periods returns {id, source_id, metadata}
    # rows shaped for the DB, not news-retrieval's article shape -
    # rank_revenue_by_yoy only ever reads/writes article["metadata"], so a
    # thin wrapper is enough; "id" being present is how it tells a context
    # row apart from a freshly-fetched article (see its docstring).
    context_wrapped = [
        {"id": r["id"], "source_id": r["source_id"], "metadata": r["metadata"]}
        for r in revenue_context
    ]

    # Rank/classify/translate needs the FULL pooled set together (ranking
    # spans all tickers for a period), so this runs before the
    # already-classified filter below - filtering first would rank against
    # a partial set and produce wrong ranks, same reasoning as
    # news-retrieval's original per-poll ranking gap.
    classified, changed_context = classify_taiwan_signal_batch(
        all_articles, revenue_context=context_wrapped,
    )

    candidate_source_ids = [c["result"]["source_id"] for c in classified]
    already_done = get_existing_taiwan_source_ids(candidate_source_ids)
    to_insert = [c for c in classified if c["result"]["source_id"] not in already_done]

    update_job_status(job_id, "running", article_count=len(to_insert))

    inserted = 0
    for c in to_insert:
        try:
            insert_taiwan_signal_classification(job_id, c["article"], c["result"])
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert taiwan_market_signal classification for"
                " source_id=%s (job %d)",
                c["result"]["source_id"], job_id,
            )

    revised = 0
    for row in changed_context:
        meta = row["metadata"]
        try:
            update_taiwan_revenue_rank(
                row["source_id"],
                revenue_rank_signal=meta["revenue_rank_signal"],
                signal_reason=meta["revenue_rank_reason"],
                metadata=meta,
            )
            revised += 1
        except Exception:
            logger.exception(
                "Failed to update revised taiwan_market_signal rank for"
                " source_id=%s (job %d)",
                row["source_id"], job_id,
            )

    logger.info(
        "[TAIWAN_SIGNAL] job=%d runs=%d pooled_articles=%d classified=%d"
        " already_done=%d inserted=%d revenue_context=%d revised=%d",
        job_id, len(run_ids), len(all_articles), len(classified),
        len(already_done), inserted, len(context_wrapped), revised,
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


async def run_agent_pipeline(job_id: int, domain: str, news_run_id: int, limit: int | None = None) -> None:
    """Background task: fetch → classify → persist.

    Routing is entirely dispatch.get_domain_config(domain) - sec_filing and
    taiwan_market_signal never reach this function (they have their own
    entry points: controllers/filing_run.py, run_taiwan_signal_classification
    above), so an unregistered domain here is either a caller error (typo,
    stale domain string) or a genuinely new domain that hasn't been
    registered in pipeline/dispatch.py yet - either way, fail the job loudly
    rather than silently classifying it against the wrong domain's prompt
    and schema.
    """
    update_job_status(job_id, "running")
    try:
        articles = await get_run_articles(news_run_id)
    except NewsRetrievalError:
        logger.exception("Pre-classification pipeline failed for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    usable = [a for a in articles if has_usable_body(a)]
    if limit is not None:
        usable = usable[:limit]
    update_job_status(job_id, "running", article_count=len(usable))

    domain_config = get_domain_config(domain)
    if domain_config is None:
        logger.error(
            "No classifier registered for domain=%r (job %d) - known domains: %s",
            domain, job_id, ", ".join(known_domains()),
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    batch_context = [
        {"title": a.get("title", ""), "url": a.get("url", "")}
        for a in usable[:20]
    ]

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(article: dict[str, Any]) -> bool:
        """Classify a single article; returns True if skipped."""
        async with semaphore:
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda a=article: domain_config.classify_one(a, batch_context=batch_context),
                )
                domain_config.insert_fn(job_id, article, result)
                return False
            except Exception:
                logger.exception(
                    "Classification failed for article %s (job %d, domain=%s)",
                    article.get("url"), job_id, domain,
                )
                return True

    outcomes = await asyncio.gather(*[classify_one(a) for a in usable])
    skipped = sum(outcomes)

    if skipped == len(usable) and usable:
        update_job_status(job_id, "failed", set_completed_at=True)
    else:
        update_job_status(job_id, "completed", set_completed_at=True)
