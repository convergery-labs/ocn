"""Digest pipeline orchestration: check → run → fetch → email."""
import logging
from datetime import date, datetime, timezone
from typing import Any

from adapters import llm_client, signal_client, smtp_sender

logger = logging.getLogger(__name__)


def _is_today(iso_timestamp: str | None) -> bool:
    """Return True if iso_timestamp is from today UTC."""
    if not iso_timestamp:
        return False
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date() == date.today()
    except ValueError:
        return False


def run_digest_polling() -> None:
    """Run the full digest pipeline using polling.

    Used by the CLI `run` command (cron path).
    """
    logger.info("Starting digest pipeline (polling mode)")

    latest = signal_client.get_latest_job()
    if latest and _is_today(latest.get("completed_at")):
        job_id = latest["job_id"]
        logger.info(
            "Today's classification already exists (job_id=%s)", job_id
        )
    else:
        logger.info("No fresh classification found; triggering pipeline")
        job_id = signal_client.trigger_run(domain="ai_news")
        logger.info("Pipeline triggered: job_id=%s", job_id)
        signal_client.poll_job_until_done(job_id)
        logger.info("Pipeline completed: job_id=%s", job_id)

    _build_and_send(job_id=job_id)


async def run_digest_async() -> None:
    """Run the full digest pipeline asynchronously (A2A serve path)."""
    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_digest_polling)


def _build_and_send(job_id: int) -> None:
    """Fetch results, categorise, summarise, and send the email."""
    logger.info("Fetching classification results for job_id=%s", job_id)
    classifications = signal_client.get_job_results(job_id)
    logger.info("Fetched %d classification rows", len(classifications))

    enriched: list[dict[str, Any]] = [
        {
            "url": c["article_url"],
            "title": c.get("article_title") or c["article_url"],
            "label": c.get("label", ""),
            "composite_score": c.get("composite_score", 0.0),
        }
        for c in classifications
    ]

    logger.info("Categorising %d articles via LLM", len(enriched))
    categorised = llm_client.categorise_articles(enriched)
    logger.info(
        "Categorisation complete: %d categories populated",
        len(categorised),
    )

    summaries: dict[str, str] = {}
    for category, cat_articles in categorised.items():
        logger.info("Summarising category: %s", category)
        summaries[category] = llm_client.summarise_category(
            category, cat_articles
        )

    smtp_sender.send_digest(summaries=summaries, categorised=categorised)
    logger.info("Digest pipeline complete")
