"""Orchestration — fetch articles from news-retrieval, classify via LLM, persist."""
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
    poll_run_until_done,
    trigger_run,
)
from models.jobs import (
    create_job,
    insert_classification,
    update_job_status,
)
from pipeline.classifier import classify_article, has_usable_body, load_prompt

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.CLASSIFY_CONCURRENCY)


async def submit_run(domain: str, run_id: int | None = None) -> int:
    """Create an agent_jobs row and return job_id.

    If run_id is provided the pipeline will reuse that news-retrieval run
    (useful for testing without triggering a fresh fetch).
    """
    return create_job(domain=domain, news_run_id=run_id)


async def run_agent_pipeline(job_id: int, domain: str, news_run_id: int | None, limit: int | None = None) -> None:
    """Background task: fetch → classify → persist."""
    update_job_status(job_id, "running")
    try:
        if news_run_id is not None:
            run_id = news_run_id
            await poll_run_until_done(run_id)
        else:
            existing = await fetch_latest_run(domain)
            if existing is not None:
                run_id = existing
            else:
                run_id = await trigger_run(domain)
                await poll_run_until_done(run_id)

        articles = await get_run_articles(run_id)
    except NewsRetrievalError:
        logger.exception("Pre-classification pipeline failed for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    usable = [a for a in articles if has_usable_body(a)]
    if limit is not None:
        usable = usable[:limit]
    update_job_status(job_id, "running", article_count=len(usable))

    system_prompt = load_prompt(config.DEFAULT_PROMPT)
    models = [config.OPENAI_MODEL]
    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(article: dict[str, Any]) -> bool:
        """Classify a single article; returns True if skipped."""
        async with semaphore:
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda: classify_article(
                        article,
                        system_prompt=system_prompt,
                        models=models,
                        api_key=config.OPENAI_API_KEY,
                        base_url=config.OPENAI_BASE_URL,
                        timeout=config.OPENAI_TIMEOUT,
                        max_attempts=config.OPENAI_MAX_ATTEMPTS,
                    ),
                )
                insert_classification(job_id, article, result)
                return False
            except Exception:
                logger.exception(
                    "Classification failed for article %s (job %d)",
                    article.get("url"), job_id,
                )
                return True

    outcomes = await asyncio.gather(*[classify_one(a) for a in usable])
    skipped = sum(outcomes)

    if skipped == len(usable) and usable:
        update_job_status(job_id, "failed", set_completed_at=True)
    else:
        update_job_status(job_id, "completed", set_completed_at=True)
