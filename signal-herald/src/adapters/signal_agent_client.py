"""HTTP client for the signal-detection-agent service."""
import base64
import json
import time
from typing import Any

import httpx

import config


class SignalAgentError(Exception):
    """Raised when signal-detection-agent returns an unexpected response."""


def _headers() -> dict[str, str]:
    caller = json.dumps(
        {"sub": config.SIGNAL_CALLER_SUB, "role": "admin", "domains": []}
    )
    encoded = base64.b64encode(caller.encode()).decode()
    return {"x-ocn-caller": encoded}


def get_latest_job() -> dict[str, Any] | None:
    """Return the most recent completed job, or None."""
    with httpx.Client(base_url=config.SIGNAL_AGENT_URL) as client:
        resp = client.get(
            "/jobs",
            params={"limit": 1, "status": "completed"},
            headers=_headers(),
            timeout=15,
        )
    if resp.status_code != 200:
        raise SignalAgentError(
            f"GET /jobs returned {resp.status_code}: {resp.text}"
        )
    jobs = resp.json().get("jobs", [])
    return jobs[0] if jobs else None


def trigger_run(domain: str = "ai_news") -> int:
    """POST /run to signal-detection-agent; return job_id."""
    with httpx.Client(base_url=config.SIGNAL_AGENT_URL) as client:
        resp = client.post(
            "/run",
            json={"domain": domain},
            headers=_headers(),
            timeout=180,
        )
    if resp.status_code not in (200, 202):
        raise SignalAgentError(
            f"POST /run returned {resp.status_code}: {resp.text}"
        )
    return resp.json()["job_id"]


def poll_job_until_done(job_id: int) -> dict[str, Any]:
    """Poll GET /jobs/{job_id} until completed or failed."""
    for _ in range(config.POLL_MAX_ATTEMPTS):
        with httpx.Client(base_url=config.SIGNAL_AGENT_URL) as client:
            resp = client.get(
                f"/jobs/{job_id}",
                headers=_headers(),
                timeout=60,
            )
        if resp.status_code != 200:
            raise SignalAgentError(
                f"GET /jobs/{job_id} returned {resp.status_code}"
            )
        job = resp.json()
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise SignalAgentError(f"Signal agent job {job_id} failed")
        time.sleep(config.POLL_INTERVAL_SECONDS)
    raise SignalAgentError(
        f"Timed out waiting for signal agent job {job_id}"
    )


def get_job_results(job_id: int) -> list[dict[str, Any]]:
    """Paginate GET /jobs/{job_id}/results; return all rows."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    with httpx.Client(base_url=config.SIGNAL_AGENT_URL) as client:
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(
                f"/jobs/{job_id}/results",
                params=params,
                headers=_headers(),
                timeout=15,
            )
            if resp.status_code != 200:
                raise SignalAgentError(
                    f"GET /jobs/{job_id}/results returned {resp.status_code}"
                )
            body = resp.json()
            results.extend(body.get("results", []))
            cursor = body.get("next_cursor")
            if not cursor:
                break
    return results
