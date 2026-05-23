"""HTTP client for the signal-detection service."""
import base64
import json
import time
from typing import Any

import httpx

import config


class SignalDetectionError(Exception):
    """Raised when signal-detection returns an unexpected response."""


def _headers() -> dict[str, str]:
    """Return the x-ocn-caller header for service-to-service calls."""
    caller = json.dumps(
        {"sub": config.SIGNAL_CALLER_SUB, "role": "admin", "domains": []}
    )
    encoded = base64.b64encode(caller.encode()).decode()
    return {"x-ocn-caller": encoded}


def get_latest_job() -> dict[str, Any] | None:
    """Return the most recent completed classification job, or None."""
    with httpx.Client(base_url=config.SIGNAL_DETECTION_URL) as client:
        resp = client.get(
            "/classifications",
            params={"limit": 1},
            headers=_headers(),
            timeout=15,
        )
    if resp.status_code != 200:
        raise SignalDetectionError(
            f"GET /classifications returned {resp.status_code}: "
            f"{resp.text}"
        )
    jobs = resp.json().get("jobs", [])
    return jobs[0] if jobs else None


def trigger_run(
    domain: str = "ai_news",
    callback_url: str | None = None,
) -> int:
    """POST /run to signal-detection; return job_id."""
    payload: dict[str, Any] = {"domain": domain}
    if callback_url:
        payload["callback_url"] = callback_url
    with httpx.Client(base_url=config.SIGNAL_DETECTION_URL) as client:
        resp = client.post(
            "/run",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
    if resp.status_code != 202:
        raise SignalDetectionError(
            f"POST /run returned {resp.status_code}: {resp.text}"
        )
    return resp.json()["job_id"]


def poll_job_until_done(job_id: int) -> dict[str, Any]:
    """Poll GET /classifications/{job_id} until completed or failed."""
    for _ in range(config.POLL_MAX_ATTEMPTS):
        with httpx.Client(base_url=config.SIGNAL_DETECTION_URL) as client:
            resp = client.get(
                f"/classifications/{job_id}",
                headers=_headers(),
                timeout=60,
            )
        if resp.status_code != 200:
            raise SignalDetectionError(
                f"GET /classifications/{job_id} returned "
                f"{resp.status_code}"
            )
        job = resp.json()
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise SignalDetectionError(
                f"Classification job {job_id} failed"
            )
        time.sleep(config.POLL_INTERVAL_SECONDS)
    raise SignalDetectionError(
        f"Timed out waiting for classification job {job_id}"
    )


def get_job_results(job_id: int) -> list[dict[str, Any]]:
    """Paginate GET /classifications/{job_id}/results; return all rows."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    with httpx.Client(base_url=config.SIGNAL_DETECTION_URL) as client:
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(
                f"/classifications/{job_id}/results",
                params=params,
                headers=_headers(),
                timeout=15,
            )
            if resp.status_code != 200:
                raise SignalDetectionError(
                    f"GET /classifications/{job_id}/results returned "
                    f"{resp.status_code}"
                )
            body = resp.json()
            results.extend(body.get("results", []))
            cursor = body.get("next_cursor")
            if not cursor:
                break
    return results
