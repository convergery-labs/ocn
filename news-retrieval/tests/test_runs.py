"""Tests for POST /run."""
from db import get_db


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
