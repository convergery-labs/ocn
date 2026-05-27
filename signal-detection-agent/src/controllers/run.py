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
from adapters.web_search import search_entity_context
from models.jobs import (
    create_job,
    get_completed_job_for_run,
    get_recent_entity_classifications,
    insert_classification,
    update_job_status,
)
from pipeline.classifier import classify_article_two_stage, has_usable_body, load_prompt

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


async def run_agent_pipeline(job_id: int, domain: str, news_run_id: int, limit: int | None = None) -> None:
    """Background task: fetch → classify → persist."""
    update_job_status(job_id, "running")
    try:
        run_id = news_run_id

        articles = await get_run_articles(run_id)
    except NewsRetrievalError:
        logger.exception("Pre-classification pipeline failed for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    usable = [a for a in articles if has_usable_body(a)]
    if limit is not None:
        usable = usable[:limit]
    update_job_status(job_id, "running", article_count=len(usable))

    system_prompt_v1 = load_prompt(config.DEFAULT_PROMPT)
    system_prompt_v2 = load_prompt(config.DEFAULT_PROMPT_V2)
    models = [config.OPENAI_MODEL]

    def entity_history_fn(entity_names: list[str]) -> list[dict]:
        return get_recent_entity_classifications(entity_names)

    def web_search_fn(entity_names: list[str], signal_reason: str = "") -> list[dict]:
        results: list[dict] = []
        event_hint = signal_reason[:60].strip() if signal_reason else ""
        for i, name in enumerate(entity_names[:2]):
            query = f"{name} {event_hint}".strip() if event_hint else name
            results.extend(
                search_entity_context(
                    query,
                    provider=config.WEB_SEARCH_PROVIDER,
                    api_key=config.WEB_SEARCH_API_KEY,
                    # apply delay on 2nd+ query to avoid DuckDuckGo rate limiting
                    rate_delay=(i > 0 and config.WEB_SEARCH_PROVIDER == "duckduckgo"),
                )
            )
        return results

    batch_context = [
        {"title": a.get("title", ""), "url": a.get("url", "")}
        for a in usable
    ]

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(article: dict[str, Any]) -> bool:
        """Classify a single article; returns True if skipped."""
        async with semaphore:
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda a=article: classify_article_two_stage(
                        a,
                        system_prompt_v1=system_prompt_v1,
                        system_prompt_v2=system_prompt_v2,
                        entity_history_fn=entity_history_fn,
                        web_search_fn=web_search_fn,
                        models=models,
                        api_key=config.OPENAI_API_KEY,
                        base_url=config.OPENAI_BASE_URL,
                        timeout=config.OPENAI_TIMEOUT,
                        max_attempts=config.OPENAI_MAX_ATTEMPTS,
                        batch_context=[b for b in batch_context if b["url"] != a.get("url")],
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
