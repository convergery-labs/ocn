"""Orchestration - fetch articles from news-retrieval, classify via LLM, persist."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
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
    insert_taiwan_signal_classification,
    update_job_status,
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

    # Rank/classify/translate needs the FULL pooled set together (ranking
    # spans all tickers for a period), so this runs before the
    # already-classified filter below - filtering first would rank against
    # a partial set and produce wrong ranks, same reasoning as
    # news-retrieval's original per-poll ranking gap.
    classified = classify_taiwan_signal_batch(all_articles)

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

    logger.info(
        "[TAIWAN_SIGNAL] job=%d runs=%d pooled_articles=%d classified=%d"
        " already_done=%d inserted=%d",
        job_id, len(run_ids), len(all_articles), len(classified),
        len(already_done), inserted,
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
