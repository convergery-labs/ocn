"""Tests for the concurrent-run guard (CON-111)."""
from db import get_db


def _insert_running_run(domain: str) -> int:
    """Insert a run row in 'running' status and return its id."""
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO runs"
            " (name, domain, days_back, status, model)"
            " VALUES (?, ?, 7, 'running', 'test-model')"
            " RETURNING id",
            (f"guard-{domain}", domain),
        ).fetchone()
    return row["id"]


async def test_concurrent_run_returns_409_with_run_id(
    client, admin_key
) -> None:
    """A second POST /run while one is running returns 409."""
    existing_id = _insert_running_run("ai_news")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["run_id"] == existing_id


async def test_force_bypasses_concurrent_guard(
    client, admin_key, mock_pipeline
) -> None:
    """force=true starts a new run even with one already in progress."""
    _insert_running_run("ai_news")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "force": True},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202
