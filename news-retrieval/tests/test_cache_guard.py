"""Tests for the same-parameters cache guard (CON-120)."""
from db import get_db


def _insert_completed_run(
    domain: str,
    days_back: int = 7,
    focus: str | None = None,
    model: str = "test-model",
    started_at: str = "NOW()",
) -> int:
    """Insert a completed run row and return its id."""
    with get_db() as conn:
        row = conn.execute(
            f"""
            INSERT INTO runs
                (name, domain, days_back, focus, model,
                 status, started_at, completed_at, article_count)
            VALUES
                (?, ?, ?, ?, ?,
                 'completed', {started_at}, NOW(), 0)
            RETURNING id
            """,
            (f"cache-{domain}", domain, days_back, focus, model),
        ).fetchone()
    return row["id"]


async def test_cache_hit_returns_200_with_existing_run_id(
    client, admin_key
) -> None:
    """Second POST /run with same params returns 200 and the cached run_id."""
    existing_id = _insert_completed_run("ai_news")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == existing_id
    assert body["cache_hit"] is True


async def test_cache_hit_response_includes_run_fields(
    client, admin_key
) -> None:
    """Cache hit response contains the full run row fields."""
    _insert_completed_run("ai_news")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )

    body = resp.json()
    assert body["cache_hit"] is True
    assert body["domain"] == "ai_news"
    assert body["status"] == "completed"


async def test_different_model_is_separate_cache_entry(
    client, admin_key, mock_pipeline
) -> None:
    """A run with a different model is not a cache hit."""
    _insert_completed_run("ai_news", model="test-model")

    resp = await client.post(
        "/run",
        json={
            "domain": "ai_news",
            "model": "other-model",
            "openrouter_api_key": "dummy-key",
        },
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_different_days_back_is_not_a_cache_hit(
    client, admin_key, mock_pipeline
) -> None:
    """A run with different days_back is not a cache hit."""
    _insert_completed_run("ai_news", days_back=7)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 14},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_different_focus_is_not_a_cache_hit(
    client, admin_key, mock_pipeline
) -> None:
    """A run with a different focus is not a cache hit."""
    _insert_completed_run("ai_news", focus="LLMs only")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "focus": "robotics only"},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_force_bypasses_cache(
    client, admin_key, mock_pipeline
) -> None:
    """force=true triggers a fresh run even when a cache hit exists."""
    _insert_completed_run("ai_news")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "force": True},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body.get("cache_hit") is not True


async def test_cache_miss_proceeds_to_new_run(
    client, admin_key, mock_pipeline
) -> None:
    """With no prior completed run today, a new run is dispatched."""
    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202
    assert "run_id" in resp.json()


async def test_run_from_yesterday_is_not_a_cache_hit(
    client, admin_key, mock_pipeline
) -> None:
    """A completed run from yesterday does not satisfy the cache check."""
    _insert_completed_run(
        "ai_news",
        started_at="NOW() - INTERVAL '1 day'",
    )

    resp = await client.post(
        "/run",
        json={"domain": "ai_news"},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202
