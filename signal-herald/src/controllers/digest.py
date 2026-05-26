"""Digest pipeline orchestration: check → run → fetch → group → email."""
import logging
from datetime import date, datetime, timezone
from typing import Any

from adapters import llm_client, signal_agent_client, smtp_sender
import config

logger = logging.getLogger(__name__)


def _is_today(iso_timestamp: str | None) -> bool:
    if not iso_timestamp:
        return False
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date() == date.today()
    except ValueError:
        return False


def run_digest_polling(force: bool = False) -> None:
    """Run the full digest pipeline using polling (cron path)."""
    logger.info("Starting digest pipeline (polling mode, force=%s)", force)

    if not force:
        latest = signal_agent_client.get_latest_job()
        if latest and _is_today(latest.get("completed_at")):
            job_id = latest["id"]
            logger.info("Today's job already exists (job_id=%s)", job_id)
            _build_and_send(job_id=job_id)
            return

    logger.info("Triggering fresh pipeline run")
    job_id = signal_agent_client.trigger_run(domain="ai_news")
    logger.info("Pipeline triggered: job_id=%s", job_id)
    signal_agent_client.poll_job_until_done(job_id)
    logger.info("Pipeline completed: job_id=%s", job_id)
    _build_and_send(job_id=job_id)


async def run_digest_async() -> None:
    """Run the full digest pipeline asynchronously (A2A serve path)."""
    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_digest_polling)


def _build_and_send(job_id: int) -> None:
    """Fetch results, group by category, summarise, and send the email."""
    logger.info("Fetching results for job_id=%s", job_id)
    results = signal_agent_client.get_job_results(job_id)
    logger.info("Fetched %d classification rows", len(results))

    # Group all articles (signal + weak_signal + noise) by category
    categorised: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        category = r.get("category")
        if not category or category not in config.CATEGORIES:
            continue
        categorised.setdefault(category, []).append(r)

    logger.info(
        "Grouped into %d categories: %s",
        len(categorised),
        list(categorised.keys()),
    )

    summaries: dict[str, str] = {}
    for category, articles in categorised.items():
        logger.info(
            "Summarising category: %s (%d articles)", category, len(articles)
        )
        summaries[category] = llm_client.summarise_category(category, articles)

    smtp_sender.send_digest(summaries=summaries, categorised=categorised)
    logger.info("Digest pipeline complete")
