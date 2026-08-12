"""Orchestration - daily SEC filing classification job.

Mirrors controllers/run.py's shape (create job -> classify concurrently ->
persist -> mark complete) but for SEC filings: read each tracked ticker's
recent filing metadata from news-retrieval (adapters/news_client.get_sec_filings
-> GET /market/sec-filings/{ticker}), which news-retrieval's own daily poller
fetches from SEC EDGAR and stores in DynamoDB. This service never calls
EDGAR's submissions API directly - only the filing body text (fetch_filing_text
below) is fetched here, since news-retrieval stores metadata + a link only.

One CloudWatch schedule triggers this directly (see infra/modules/ecs_cluster),
timed to run after news-retrieval's own sec_filings poller (01:00 UTC daily) -
there is no push/fire-and-forget step between the two services. The ticker
universe (get_tracked_tickers) is likewise read live from news-retrieval
rather than duplicated, since that list is its single source of truth.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import config
from adapters import sec_edgar
from adapters.news_client import get_sec_filings, get_tracked_tickers
from models.jobs import (
    create_job,
    get_existing_filing_source_ids,
    insert_filing_classification,
    update_job_status,
)
from pipeline.filing_classifier import classify_filing, load_sec_filing_prompt

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.FILING_CLASSIFY_CONCURRENCY)


async def _fetch_all_filings(tickers: list[str]) -> list[dict[str, Any]]:
    """Fetch stored filing metadata for every tracked ticker from news-retrieval.
    One HTTP call per ticker, bounded by FILING_CLASSIFY_CONCURRENCY - this is
    a read against news-retrieval's own DynamoDB-backed endpoint, not a call to
    SEC EDGAR, so there's no external rate limit to share across tickers here.
    """
    semaphore = asyncio.Semaphore(config.FILING_CLASSIFY_CONCURRENCY)

    async def fetch_one(ticker: str) -> list[dict[str, Any]]:
        async with semaphore:
            try:
                return await get_sec_filings(ticker)
            except Exception:
                logger.exception("Failed to fetch filings for ticker=%s", ticker)
                return []

    results = await asyncio.gather(*[fetch_one(t) for t in tickers])
    return [filing for filings in results for filing in filings]


def _fetch_filing_text_and_extract(filing: dict[str, Any], last_call: list[float]) -> tuple[str, bool]:
    """Fetch one filing's text and, for 10-K, extract the results section.
    8-K/10-Q are small enough to pass in full (confirmed this session:
    ~4K chars for 8-K, ~100K chars for 10-Q) - only 10-K (~500K chars) needs
    extraction before it can be sent to the classifier.
    """
    text = sec_edgar.fetch_filing_text(filing["primary_doc_url"], last_call)
    if not text:
        return "", False
    if filing["form_type"] == "10-K":
        return sec_edgar.extract_results_section(text)
    return text, True


async def run_filing_classification_job(job_id: int) -> None:
    """Background task: fetch tracked tickers' filings -> dedup -> classify -> persist."""
    update_job_status(job_id, "running")
    try:
        tickers = await get_tracked_tickers()
    except Exception:
        logger.exception("Failed to fetch tracked ticker list for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    loop = asyncio.get_event_loop()
    all_filings = await _fetch_all_filings(tickers)

    accession_numbers = [f["accession_number"] for f in all_filings if f.get("accession_number")]
    existing = get_existing_filing_source_ids(accession_numbers)
    new_filings = [f for f in all_filings if f.get("accession_number") not in existing]
    update_job_status(job_id, "running", article_count=len(new_filings))

    if not new_filings:
        logger.info("No new filings for job %d (fetched=%d, all already classified)", job_id, len(all_filings))
        update_job_status(job_id, "completed", set_completed_at=True)
        return

    system_prompt = load_sec_filing_prompt()
    models = [config.OPENAI_MODEL]
    semaphore = asyncio.Semaphore(config.FILING_CLASSIFY_CONCURRENCY)
    fetch_last_call = [0.0]

    async def classify_one(filing: dict[str, Any]) -> bool:
        """Classify a single filing; returns True if skipped (failed)."""
        async with semaphore:
            try:
                filing_text, extraction_found = await loop.run_in_executor(
                    _executor, _fetch_filing_text_and_extract, filing, fetch_last_call,
                )
                result = await loop.run_in_executor(
                    _executor,
                    lambda f=filing, t=filing_text, found=extraction_found: classify_filing(
                        f, t,
                        system_prompt=system_prompt,
                        models=models,
                        api_key=config.OPENAI_API_KEY,
                        base_url=config.OPENAI_BASE_URL,
                        timeout=config.OPENAI_TIMEOUT,
                        max_attempts=config.OPENAI_MAX_ATTEMPTS,
                        extraction_found=found,
                        cache_system_prompt=True,
                    ),
                )
                insert_filing_classification(job_id, filing, result)
                return False
            except Exception:
                logger.exception(
                    "Filing classification failed for accession=%s (job %d)",
                    filing.get("accession_number"), job_id,
                )
                return True

    outcomes = await asyncio.gather(*[classify_one(f) for f in new_filings])
    skipped = sum(outcomes)

    if skipped == len(new_filings) and new_filings:
        update_job_status(job_id, "failed", set_completed_at=True)
    else:
        update_job_status(job_id, "completed", set_completed_at=True)


def submit_filing_run() -> int:
    """Create a new agent_jobs row for the SEC filing domain; return its id.
    Caller schedules run_filing_classification_job(job_id) as a background task.
    """
    return create_job(domain=config.SEC_FILING_DOMAIN)
