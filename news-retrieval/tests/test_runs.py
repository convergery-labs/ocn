"""Tests for POST /run."""
from db import get_db
from models.runs import fail_stuck_runs


async def test_valid_run_returns_202(
    client, admin_key, mock_pipeline
) -> None:
    """POST /run on a known domain returns 202 with run_id."""
    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["status"] == "running"


async def test_valid_run_creates_db_record(
    client, admin_key, mock_pipeline
) -> None:
    """A 202 response results in a completed run row in the DB."""
    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )
    run_id = resp.json()["run_id"]
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    assert row is not None
    assert row["status"] == "completed"


async def test_unknown_domain_returns_404(
    client, admin_key
) -> None:
    """POST /run with an unknown domain slug must return 404."""
    resp = await client.post(
        "/run",
        json={"domain": "no_such_domain"},
        headers={"x-ocn-caller": admin_key},
    )
    assert resp.status_code == 404


async def test_run_on_other_users_domain_returns_403(
    client, other_user_key, user_domain
) -> None:
    """A caller who does not own the domain must receive 403."""
    key, _ = other_user_key
    resp = await client.post(
        "/run",
        json={"domain": "test-domain"},
        headers={"x-ocn-caller": key},
    )
    assert resp.status_code == 403


def test_fail_stuck_runs_marks_only_old_running_rows() -> None:
    """A run stuck in 'running' past max_hours is marked failed; a recent
    running run and an already-completed run are both left untouched.

    Confirmed live (2026-09-25, run_id=472): a scheduled fetch can die
    completely silently and leave its run row stuck in 'running'
    indefinitely - fail_orphaned_runs (server-startup-only) never catches
    this on a long-lived server, so fail_stuck_runs exists as an
    age-gated, restart-independent alternative.
    """
    with get_db() as conn:
        stuck_id = conn.execute(
            "INSERT INTO runs (domain, name, status, started_at,"
            " days_back, model)"
            " VALUES ('ai_news', 'test-stuck', 'running',"
            " NOW() - INTERVAL '5 hours', 1, 'none') RETURNING id"
        ).fetchone()["id"]
        recent_id = conn.execute(
            "INSERT INTO runs (domain, name, status, started_at,"
            " days_back, model)"
            " VALUES ('ai_news', 'test-recent', 'running',"
            " NOW() - INTERVAL '10 minutes', 1, 'none') RETURNING id"
        ).fetchone()["id"]
        completed_id = conn.execute(
            "INSERT INTO runs (domain, name, status, started_at,"
            " completed_at, days_back, model)"
            " VALUES ('ai_news', 'test-completed', 'completed',"
            " NOW() - INTERVAL '5 hours', NOW() - INTERVAL '4 hours',"
            " 1, 'none') RETURNING id"
        ).fetchone()["id"]
        conn.commit()

    failed_ids = fail_stuck_runs(max_hours=3)
    assert stuck_id in failed_ids
    assert recent_id not in failed_ids
    assert completed_id not in failed_ids

    with get_db() as conn:
        stuck_row = conn.execute(
            "SELECT status FROM runs WHERE id = ?", (stuck_id,)
        ).fetchone()
        recent_row = conn.execute(
            "SELECT status FROM runs WHERE id = ?", (recent_id,)
        ).fetchone()
    assert stuck_row["status"] == "failed"
    assert recent_row["status"] == "running"
