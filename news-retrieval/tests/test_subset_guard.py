"""Tests for the time-window subset guard (CON-121)."""
from datetime import datetime, timedelta, timezone

from db import get_db
from models.articles import filter_articles_for_window


def _insert_covering_run(
    domain: str,
    days_back: int = 14,
    model: str = "none",
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
        "published": "2024-01-01T00:00:00+00:00",
    },
    {
        "url": "http://example.com/recent",
        "title": "Recent Article",
        "summary": "",
        "source": "Test",
        # published is None → always included
        "published": None,
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


async def test_subset_run_articles_resolve_through_covering_run(
    client, admin_key
) -> None:
    """GET /runs/{subset_id}/articles returns the covering run's articles,
    filtered to the subset's window, with real URLs (not copied rows) -
    CON-121 read-through after the global url uniqueness constraint made
    copying article rows into the subset run impossible."""
    covering_id = _insert_covering_run(
        "ai_news", days_back=14, articles=_ARTICLES_14D
    )

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )
    assert resp.status_code == 200
    subset_id = resp.json()["id"]
    assert subset_id != covering_id

    articles_resp = await client.get(f"/runs/{subset_id}/articles")
    assert articles_resp.status_code == 200
    body = articles_resp.json()

    urls = {a["url"] for a in body["articles"]}
    assert urls == {"http://example.com/recent"}  # "old" (2024) is outside 7d
    for article in body["articles"]:
        assert article["url"] is not None


async def test_subset_run_window_cutoff_is_frozen_not_recomputed(
    client, admin_key
) -> None:
    """A subset run's window_cutoff is stored at creation time and does not
    move on later reads - proves the fix for the article_count/resolved-set
    drift that "now() - days_back" recomputed on every read would cause."""
    before_create = datetime.now(timezone.utc)
    covering_id = _insert_covering_run("ai_news", days_back=14)

    resp = await client.post(
        "/run",
        json={"domain": "ai_news", "days_back": 7},
        headers={"x-ocn-caller": admin_key},
    )
    assert resp.status_code == 200
    subset_id = resp.json()["id"]
    assert subset_id != covering_id
    after_create = datetime.now(timezone.utc)

    with get_db() as conn:
        row = conn.execute(
            "SELECT window_cutoff FROM runs WHERE id = ?", (subset_id,)
        ).fetchone()
    stored_cutoff = row["window_cutoff"]
    assert stored_cutoff is not None

    # window_cutoff should equal ~(creation time - 7 days), computed once
    # at creation - not something that moves forward on later reads.
    expected_lower = before_create - timedelta(days=7, seconds=5)
    expected_upper = after_create - timedelta(days=7) + timedelta(seconds=5)
    assert expected_lower <= stored_cutoff <= expected_upper

    # Reading twice, with real (if small) wall-clock time elapsed between
    # calls, must not change the stored cutoff or the resolved article set.
    first_resp = await client.get(f"/runs/{subset_id}/articles")
    second_resp = await client.get(f"/runs/{subset_id}/articles")
    assert first_resp.json() == second_resp.json()

    with get_db() as conn:
        row_after_reads = conn.execute(
            "SELECT window_cutoff FROM runs WHERE id = ?", (subset_id,)
        ).fetchone()
    assert row_after_reads["window_cutoff"] == stored_cutoff


def test_filter_articles_for_window_explicit_cutoff_overrides_now() -> None:
    """An explicit cutoff keeps a near-boundary article in, even though the
    default now()-recomputed cutoff would have just excluded it - this is
    what makes a subset run's resolved set immune to read-time drift."""
    near_boundary_published = (
        datetime.now(timezone.utc) - timedelta(days=6, hours=23)
    ).isoformat()
    articles = [{
        "url": "http://example.com/near-boundary",
        "published": near_boundary_published,
    }]

    frozen_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    result_with_frozen_cutoff = filter_articles_for_window(
        articles, days_back=7, max_articles=None, cutoff=frozen_cutoff
    )
    assert len(result_with_frozen_cutoff) == 1

    far_future_cutoff = datetime.now(timezone.utc) + timedelta(days=3)
    result_with_advanced_cutoff = filter_articles_for_window(
        articles, days_back=7, max_articles=None, cutoff=far_future_cutoff
    )
    assert result_with_advanced_cutoff == []


async def test_subset_with_naive_iso_published_dates(
    client, admin_key
) -> None:
    """Subset run succeeds (200) when covering articles have naive ISO 8601
    published dates - guards against TypeError on tz-naive vs tz-aware
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
