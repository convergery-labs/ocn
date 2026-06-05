"""Orchestration for the unified fetch-and-classify pipeline."""
import asyncio
import logging
import os

import httpx

from controllers.classify import (
    _fire_callback,
    run_agent_loop,
    validate_domain,
)
from models.jobs import update_job_article_count, update_job_status

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 10
_FETCH_PAGE_SIZE = 100


def _news_retrieval_url() -> str:
    """Return the news-retrieval base URL from env."""
    return os.environ.get("NEWS_RETRIEVAL_URL", "http://news-retrieval:8000")


def _service_caller_header() -> str:
    """Return the x-ocn-caller header value for internal news-retrieval calls.

    Defaults to a pre-encoded admin identity when the env var is absent.
    """
    return os.environ.get(
        "NEWS_RETRIEVAL_SERVICE_CALLER",
        "eyJzdWIiOiAwLCAicm9sZSI6ICJhZG1pbiIsICJkb21haW5zIjogW119",
    )


async def _trigger_news_run(request) -> int:
    """POST to news-retrieval /run and return the run_id.

    Handles 202 (new run), 200 (cache hit), and 409 (conflict - returns
    the conflicting run_id so the caller can poll it).

    Raises:
        RuntimeError: on unexpected HTTP errors or network failures.
    """
    base = _news_retrieval_url()
    payload = {
        "domain": request.domain,
        "days_back": request.days_back,
        "force": request.force,
    }
    if request.max_articles is not None:
        payload["max_articles"] = request.max_articles
    if request.focus is not None:
        payload["focus"] = request.focus

    headers = {"x-ocn-caller": _service_caller_header()}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/run", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"news-retrieval unreachable: {exc}") from exc

    if resp.status_code == 200:
        # Cache hit - response is the RunRow directly, keyed by "id"
        return int(resp.json()["id"])
    if resp.status_code == 202:
        return int(resp.json()["run_id"])
    if resp.status_code == 409:
        return int(resp.json()["detail"]["run_id"])
    raise RuntimeError(
        f"news-retrieval POST /run returned {resp.status_code}: {resp.text}"
    )


async def _poll_news_run(run_id: int) -> None:
    """Poll GET /runs/{run_id} until status is completed or failed.

    Raises:
        RuntimeError: on timeout or news-retrieval run failure.
    """
    base = _news_retrieval_url()
    timeout_secs = int(
        os.environ.get("PIPELINE_POLL_TIMEOUT_SECS", "600")
    )
    elapsed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                resp = await client.get(f"{base}/runs/{run_id}")
                resp.raise_for_status()
                status = resp.json().get("status")
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to poll news-retrieval run {run_id}: {exc}"
                ) from exc

            if status == "completed":
                return
            if status == "failed":
                raise RuntimeError(
                    f"news-retrieval run {run_id} failed"
                )

            if elapsed >= timeout_secs:
                raise RuntimeError(
                    f"Timed out waiting for news-retrieval run {run_id}"
                )

            await asyncio.sleep(_POLL_INTERVAL_SECS)
            elapsed += _POLL_INTERVAL_SECS


async def _fetch_articles(run_id: int) -> list[dict]:
    """Paginate GET /runs/{run_id}/articles and return all articles."""
    base = _news_retrieval_url()
    articles: list[dict] = []
    cursor: str | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict = {
                "include_body": "true",
                "limit": _FETCH_PAGE_SIZE,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                resp = await client.get(
                    f"{base}/runs/{run_id}/articles", params=params
                )
                resp.raise_for_status()
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to fetch articles for run {run_id}: {exc}"
                ) from exc

            data = resp.json()
            articles.extend(data.get("articles", []))
            cursor = data.get("next_cursor")
            if not cursor:
                break

    return articles


async def fetch_and_classify(
    job_id: int,
    request,
    callback_url: str | None,
) -> None:
    """Fetch articles from news-retrieval then run the classification pipeline.

    On pre-classification failure (triggering the run, polling, or fetching
    articles), marks the job failed and fires the callback. Classification
    errors are handled by run_agent_loop itself.
    """
    try:
        await validate_domain(request.domain)
        news_run_id = await _trigger_news_run(request)
        await _poll_news_run(news_run_id)
        articles = await _fetch_articles(news_run_id)
        update_job_article_count(job_id, len(articles))
    except Exception:
        logger.exception(
            "Pre-classification pipeline failed for job %d", job_id
        )
        try:
            update_job_status(job_id, "failed", set_completed_at=True)
        except Exception:
            logger.exception("Failed to mark job %d failed", job_id)
        if callback_url:
            _fire_callback(callback_url, job_id, "failed")
        return

    await run_agent_loop(job_id, articles, callback_url, domain=request.domain)
