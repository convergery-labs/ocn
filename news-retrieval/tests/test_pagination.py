"""Tests for cursor-based pagination on /runs and /runs/{id}/articles."""
from models.articles import create_articles
from models.runs import complete_run, create_run


def _make_run(name: str) -> int:
    """Insert a completed run and return its id."""
    run_id = create_run(
        name, "ai_news", 7, None, None, "test-model"
    )
    complete_run(run_id, 0)
    return run_id


async def test_runs_first_page_has_next_cursor(client) -> None:
    """GET /runs?limit=2 returns 2 rows and a next_cursor."""
    for i in range(3):
        _make_run(f"pag-run-{i}")

    resp = await client.get("/runs?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 2
    assert body["next_cursor"] is not None


async def test_runs_last_page_has_null_cursor(client) -> None:
    """Following the cursor to the last page yields next_cursor=null."""
    for i in range(3):
        _make_run(f"pag-run-{i}")

    resp1 = await client.get("/runs?limit=2")
    cursor = resp1.json()["next_cursor"]

    resp2 = await client.get(f"/runs?limit=2&cursor={cursor}")
    body2 = resp2.json()
    assert len(body2["runs"]) == 1
    assert body2["next_cursor"] is None


async def test_articles_pagination_advances_through_pages(
    client,
) -> None:
    """GET /runs/{id}/articles cursor paginates all articles."""
    run_id = _make_run("art-pag-run")
    complete_run(run_id, 5)
    create_articles([
        {
            "run_id": run_id,
            "url": f"http://ex.com/{i}",
            "title": f"Art {i}",
            "summary": "s",
            "source": "src",
            "published": "2026-01-01",
        }
        for i in range(5)
    ])

    resp1 = await client.get(
        f"/runs/{run_id}/articles?limit=2"
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["articles"]) == 2
    assert body1["next_cursor"] is not None

    resp2 = await client.get(
        f"/runs/{run_id}/articles?limit=2"
        f"&cursor={body1['next_cursor']}"
    )
    body2 = resp2.json()
    assert len(body2["articles"]) == 2
    assert body2["next_cursor"] is not None

    resp3 = await client.get(
        f"/runs/{run_id}/articles?limit=2"
        f"&cursor={body2['next_cursor']}"
    )
    body3 = resp3.json()
    assert len(body3["articles"]) == 1
    assert body3["next_cursor"] is None


async def test_articles_body_excluded_by_default(client) -> None:
    """GET /runs/{id}/articles omits body field by default."""
    run_id = _make_run("no-body-default-run")
    create_articles([{
        "run_id": run_id,
        "url": "http://ex.com/1",
        "title": "Art 1",
        "summary": "s",
        "source": "src",
        "published": "2026-01-01",
        "body": "full article text",
    }])

    resp = await client.get(f"/runs/{run_id}/articles")
    assert resp.status_code == 200
    article = resp.json()["articles"][0]
    assert "body" not in article


async def test_articles_body_included_when_requested(client) -> None:
    """GET /runs/{id}/articles?include_body=true returns body field."""
    run_id = _make_run("with-body-run")
    create_articles([{
        "run_id": run_id,
        "url": "http://ex.com/1",
        "title": "Art 1",
        "summary": "s",
        "source": "src",
        "published": "2026-01-01",
        "body": "full article text",
    }])

    resp = await client.get(
        f"/runs/{run_id}/articles?include_body=true"
    )
    assert resp.status_code == 200
    article = resp.json()["articles"][0]
    assert article["body"] == "full article text"


async def test_articles_body_excluded_when_false(client) -> None:
    """GET /runs/{id}/articles?include_body=false omits body field."""
    run_id = _make_run("explicit-no-body-run")
    create_articles([{
        "run_id": run_id,
        "url": "http://ex.com/1",
        "title": "Art 1",
        "summary": "s",
        "source": "src",
        "published": "2026-01-01",
        "body": "full article text",
    }])

    resp = await client.get(
        f"/runs/{run_id}/articles?include_body=false"
    )
    assert resp.status_code == 200
    article = resp.json()["articles"][0]
    assert "body" not in article
