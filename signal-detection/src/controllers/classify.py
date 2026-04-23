"""Orchestration for classification job submission and execution."""
import logging
import os

import httpx

from models.jobs import (
    JobRow,
    create_job,
    find_processing_job,
    update_job_status,
)

logger = logging.getLogger(__name__)


class RunNotFoundError(Exception):
    """Raised when the referenced news-retrieval run does not exist."""


class DuplicateJobError(Exception):
    """Raised when a processing job for run_id already exists."""


def _news_retrieval_url() -> str:
    """Return the news-retrieval base URL from env."""
    return os.environ.get(
        "NEWS_RETRIEVAL_URL", "http://news-retrieval:8000"
    )


async def validate_run_id(run_id: int) -> None:
    """Confirm run_id exists in news-retrieval; raise RunNotFoundError if not.

    Raises:
        RunNotFoundError: if the run does not exist or news-retrieval
            returns a non-200 response.
    """
    url = f"{_news_retrieval_url()}/runs/{run_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise RunNotFoundError(
            f"news-retrieval unreachable: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise RunNotFoundError(
            f"run {run_id} not found in news-retrieval"
        )


async def submit_classify_job(
    run_id: str | None,
    articles: list[dict],
    callback_url: str | None,
) -> JobRow:
    """Validate, create a job record, and return it.

    For Mode A (run_id provided): verifies run existence and uniqueness.
    For Mode B (articles provided directly): generates a fresh run_id.

    Raises:
        RunNotFoundError: Mode A only — run_id not found.
        DuplicateJobError: Mode A only — processing job already exists.
    """
    if run_id is not None:
        await validate_run_id(int(run_id))
        existing = find_processing_job(run_id)
        if existing:
            raise DuplicateJobError(
                f"A processing job already exists for run_id={run_id}"
            )
        effective_run_id = run_id
    else:
        import uuid
        effective_run_id = str(uuid.uuid4())

    job = create_job(
        run_id=effective_run_id,
        status="processing",
        callback_url=callback_url,
        article_count=len(articles),
    )
    return job


async def run_classification_stub(
    job_id: int,
    articles: list[dict],
    callback_url: str | None,
) -> None:
    """Stub background task — CON-137/138 will replace this body."""
    try:
        update_job_status(job_id, "completed", set_completed_at=True)
    except Exception:
        logger.exception("Failed to mark job %d completed", job_id)
        try:
            update_job_status(job_id, "failed", set_completed_at=True)
        except Exception:
            logger.exception(
                "Failed to mark job %d failed", job_id
            )
        if callback_url:
            _fire_callback(callback_url, job_id, "failed")
        return
    if callback_url:
        _fire_callback(callback_url, job_id, "completed")


def _fire_callback(
    callback_url: str,
    job_id: int,
    status: str,
) -> None:
    """POST job completion status to callback_url; errors are swallowed."""
    import httpx as _httpx
    try:
        with _httpx.Client(timeout=10.0) as client:
            client.post(
                callback_url,
                json={"job_id": job_id, "status": status},
            )
    except Exception:
        logger.warning(
            "Callback to %s failed for job %d", callback_url, job_id
        )
