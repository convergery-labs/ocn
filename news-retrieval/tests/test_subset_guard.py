"""Tests for the time-window subset guard (CON-121)."""
from db import get_db


def _insert_covering_run(
    domain: str,
    days_back: int = 14,
    model: str = "test-model",
    focus: str | None = None,
    articles: list[dict] | None = None,
    started_at: str = "NOW()",
) -> int:
    """Insert a completed run (and optional articles) and return its id."""
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
            (f"cover-{domain}", domain, days_back, focus, model),
        ).fetchone()
        run_id = row["id"]
        if articles:
            for art in articles:
                conn.execute(
                    """
                    INSERT INTO articles
                        (run_id, url, title, summary, source, published)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        art.get("url"),
                        art.get("title"),
                        art.get("summary"),
                        art.get("source"),
                        art.get("published"),
                    ),
                )
    return run_id


_ARTICLES_14D = [
    {
        "url": "http://example.com/old",
        "title": "Old Article",
        "summary": "",
        "source": "Test",
        "published": "Mon, 01 Jan 2024 00:00:00 +0000",
    },
    {
        "url": "http://example.com/recent",
        "title": "Recent Article",
        "summary": "",
        "source": "Test",
        # published is empty → treated as None → always included
        "published": "",
    },
]


async def test_wider_run_covers_narrower_request(
    client, admin_key
) -> None:
    """POST /run with narrower days_back returns 200 cache_hit when a
    wider same-day completed run exists."""
    _insert_covering_run("ai_news", days_back=14)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["cache_hit"] is True
    assert body["days_back"] == 7


async def test_subset_run_id_differs_from_covering_run_id(
    client, admin_key
) -> None:
    """A new run is created for the subset; its id differs from the
    covering run."""
    covering_id = _insert_covering_run("ai_news", days_back=14)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    body = resp.json()
    assert body["cache_hit"] is True
    assert body["id"] != covering_id


async def test_different_model_does_not_cover(
    client, admin_key, mock_pipeline
) -> None:
    """A covering run with a different model does not trigger the guard."""
    _insert_covering_run("ai_news", days_back=14, model="other-model")

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_narrower_existing_does_not_cover(
    client, admin_key, mock_pipeline
) -> None:
    """A completed run with smaller days_back cannot cover a wider request."""
    _insert_covering_run("ai_news", days_back=3)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_force_bypasses_subset_guard(
    client, admin_key, mock_pipeline
) -> None:
    """force=true dispatches a fresh run even when a covering run exists."""
    _insert_covering_run("ai_news", days_back=14)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7, "force": True},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202
    assert resp.json().get("cache_hit") is not True


async def test_yesterday_wider_run_does_not_cover(
    client, admin_key, mock_pipeline
) -> None:
    """A wider run from yesterday does not satisfy the UTC-day boundary."""
    _insert_covering_run(
        "ai_news",
        days_back=14,
        started_at="NOW() - INTERVAL '1 day'",
    )

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 202


async def test_subset_with_naive_iso_published_dates(
    client, admin_key
) -> None:
    """Subset run succeeds (200) when covering articles have naive ISO 8601
    published dates — guards against TypeError on tz-naive vs tz-aware
    comparison (CON-147)."""
    from datetime import datetime, timedelta, timezone

    recent = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M:%S")  # naive ISO 8601, no tz suffix

    _insert_covering_run(
        "ai_news",
        days_back=14,
        articles=[
            {
                "url": "http://example.com/naive-dt",
                "title": "Naive DateTime Article",
                "summary": "",
                "source": "Test",
                "published": recent,
            }
        ],
    )

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )

    assert resp.status_code == 200
    assert resp.json()["cache_hit"] is True
