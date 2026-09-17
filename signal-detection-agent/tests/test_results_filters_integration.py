"""Integration tests for list_all_results' filters (grade, impacted_category,
impacted_ticker, channel, corroborated, published_from/published_to).

Unlike every other test in this suite, these hit a REAL Postgres connection
- list_all_results/list_results build raw SQL directly against get_db(),
with no injectable seam to mock (no repository interface, no DB fixture in
this codebase's conftest.py today). A pure-mock unit test here would only
verify the Python glue, not the actual SQL - and the impacted_ticker filter
had a real bug (jsonb_array_elements_text choking on a JSON null, not a
missing key) that only real data caught, not a syntax/compile check. So
these tests insert real rows into agent_classifications, query through
list_all_results, and clean up after themselves - skipped automatically if
no DB is reachable (e.g. running outside the docker-compose network),
rather than failing the whole suite in an environment without Postgres.
"""
import sys
import os
import json
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

try:
    from db import get_db, init_db
    from models.jobs import create_job, list_all_results
    # importing db.py does not itself open a connection (psycopg2 connects
    # lazily) - actually attempt one here, so this skip check catches "not
    # running inside the docker-compose network" (e.g. a plain .venv/bin/
    # pytest run on the host, where the Docker-internal hostname
    # postgres-signal doesn't resolve), not just an import-time failure.
    with get_db() as _conn:
        _conn.execute("SELECT 1")
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DB_AVAILABLE, reason="requires a reachable Postgres (run inside docker-compose network)"
)

_TEST_MARKER = "test_results_filters_integration"


def _cleanup():
    with get_db() as conn:
        conn.execute(
            "DELETE FROM agent_classifications WHERE metadata->>'_test_marker' = %s",
            (_TEST_MARKER,),
        )


@pytest.fixture(autouse=True)
def _db_setup_teardown():
    init_db()
    _cleanup()
    yield
    _cleanup()


def _insert_row(
    *,
    article_id: int,
    title: str,
    url: str,
    published: datetime,
    metadata: dict,
):
    job_id = create_job(domain="geopolitical_news")
    full_metadata = {**metadata, "_test_marker": _TEST_MARKER}
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications
                (job_id, article_id, url, title, signal_detection, published, source_type, metadata)
            VALUES (%s, %s, %s, %s, 'signal', %s, 'geopolitical_signal', %s::jsonb)
            """,
            (job_id, article_id, url, title, published, json.dumps(full_metadata)),
        )


def test_grade_filter_matches_only_that_grade():
    _insert_row(
        article_id=900001, title="TOP row", url="https://reuters.com/a",
        published=datetime.now(timezone.utc),
        metadata={"grade": "TOP"},
    )
    _insert_row(
        article_id=900002, title="STANDARD row", url="https://reuters.com/b",
        published=datetime.now(timezone.utc),
        metadata={"grade": "STANDARD"},
    )
    result = list_all_results(source_type="geopolitical_signal", grade="TOP", limit=100)
    titles = {r["title"] for r in result["results"]}
    assert "TOP row" in titles
    assert "STANDARD row" not in titles


def test_impacted_category_filter_matches_array_containment():
    _insert_row(
        article_id=900003, title="Semis row", url="https://reuters.com/c",
        published=datetime.now(timezone.utc),
        metadata={"impacted_categories": ["Semiconductor Manufacturing", "Cloud & Compute Platforms"]},
    )
    _insert_row(
        article_id=900004, title="Energy row", url="https://reuters.com/d",
        published=datetime.now(timezone.utc),
        metadata={"impacted_categories": ["Energy & Grid Infrastructure"]},
    )
    result = list_all_results(
        source_type="geopolitical_signal", impacted_category="Semiconductor Manufacturing", limit=100,
    )
    titles = {r["title"] for r in result["results"]}
    assert "Semis row" in titles
    assert "Energy row" not in titles


def test_impacted_ticker_filter_matches_direct_or_by_category_case_insensitive():
    _insert_row(
        article_id=900005, title="Direct match row", url="https://reuters.com/e",
        published=datetime.now(timezone.utc),
        metadata={"impacted_companies_direct": ["NVDA"], "impacted_companies_by_category": None},
    )
    _insert_row(
        article_id=900006, title="Category match row", url="https://reuters.com/f",
        published=datetime.now(timezone.utc),
        metadata={"impacted_companies_direct": None, "impacted_companies_by_category": ["AMD", "TSM"]},
    )
    _insert_row(
        article_id=900007, title="No match row", url="https://reuters.com/g",
        published=datetime.now(timezone.utc),
        metadata={"impacted_companies_direct": None, "impacted_companies_by_category": None},
    )
    result = list_all_results(source_type="geopolitical_signal", impacted_ticker="nvda", limit=100)
    titles = {r["title"] for r in result["results"]}
    assert "Direct match row" in titles
    assert "Category match row" not in titles
    assert "No match row" not in titles

    result2 = list_all_results(source_type="geopolitical_signal", impacted_ticker="AMD", limit=100)
    titles2 = {r["title"] for r in result2["results"]}
    assert "Category match row" in titles2
    assert "Direct match row" not in titles2


def test_impacted_ticker_filter_does_not_crash_on_null_arrays():
    # regression test: jsonb_array_elements_text raised
    # psycopg2.errors.InvalidParameterValue: cannot extract elements from a
    # scalar when metadata->'impacted_companies_direct' is JSON null (not a
    # missing key) - COALESCE alone does not catch this, only
    # jsonb_typeof(...) = 'array' does. Confirmed live against real Stage C
    # output, which stores exactly this shape on a fail-open row.
    _insert_row(
        article_id=900008, title="Null arrays row", url="https://reuters.com/h",
        published=datetime.now(timezone.utc),
        metadata={"impacted_companies_direct": None, "impacted_companies_by_category": None},
    )
    result = list_all_results(source_type="geopolitical_signal", impacted_ticker="NVDA", limit=100)
    titles = {r["title"] for r in result["results"]}
    assert "Null arrays row" not in titles


def test_channel_filter():
    _insert_row(
        article_id=900009, title="Sanctions row", url="https://reuters.com/i",
        published=datetime.now(timezone.utc),
        metadata={"channel": "sanctions"},
    )
    _insert_row(
        article_id=900010, title="Trade row", url="https://reuters.com/j",
        published=datetime.now(timezone.utc),
        metadata={"channel": "trade"},
    )
    result = list_all_results(source_type="geopolitical_signal", channel="sanctions", limit=100)
    titles = {r["title"] for r in result["results"]}
    assert "Sanctions row" in titles
    assert "Trade row" not in titles


def test_corroborated_filter_true_and_false():
    _insert_row(
        article_id=900011, title="Corroborated row", url="https://reuters.com/k",
        published=datetime.now(timezone.utc),
        metadata={"corroborated": True},
    )
    _insert_row(
        article_id=900012, title="Not corroborated row", url="https://reuters.com/l",
        published=datetime.now(timezone.utc),
        metadata={"corroborated": False},
    )
    result_true = list_all_results(source_type="geopolitical_signal", corroborated=True, limit=100)
    titles_true = {r["title"] for r in result_true["results"]}
    assert "Corroborated row" in titles_true
    assert "Not corroborated row" not in titles_true

    result_false = list_all_results(source_type="geopolitical_signal", corroborated=False, limit=100)
    titles_false = {r["title"] for r in result_false["results"]}
    assert "Not corroborated row" in titles_false
    assert "Corroborated row" not in titles_false


def test_published_from_to_filters_are_inclusive_date_range():
    # scoped with a unique marker channel (not just source_type, which alone
    # has thousands of real rows from other test sessions in this shared
    # local DB - a bare limit=100 newest-first page would not reliably
    # contain our just-inserted row otherwise) so the assertion is exact
    # regardless of how much other data already exists in the table.
    now = datetime.now(timezone.utc)
    _insert_row(
        article_id=900013, title="In range row", url="https://reuters.com/m",
        published=now - timedelta(days=1),
        metadata={"channel": _TEST_MARKER},
    )
    _insert_row(
        article_id=900014, title="Too old row", url="https://reuters.com/n",
        published=now - timedelta(days=30),
        metadata={"channel": _TEST_MARKER},
    )
    from_date = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    result = list_all_results(
        source_type="geopolitical_signal", channel=_TEST_MARKER,
        published_from=from_date, published_to=to_date, limit=100,
    )
    titles = {r["title"] for r in result["results"]}
    assert "In range row" in titles
    assert "Too old row" not in titles


def test_combined_filters_all_apply_together():
    _insert_row(
        article_id=900015, title="Matches all row", url="https://reuters.com/o",
        published=datetime.now(timezone.utc),
        metadata={
            "grade": "STRONG", "channel": "trade", "corroborated": False,
            "impacted_categories": ["Semiconductor Manufacturing"],
        },
    )
    _insert_row(
        article_id=900016, title="Wrong channel row", url="https://reuters.com/p",
        published=datetime.now(timezone.utc),
        metadata={
            "grade": "STRONG", "channel": "sanctions", "corroborated": False,
            "impacted_categories": ["Semiconductor Manufacturing"],
        },
    )
    result = list_all_results(
        source_type="geopolitical_signal", grade="STRONG", channel="trade",
        corroborated=False, impacted_category="Semiconductor Manufacturing", limit=100,
    )
    titles = {r["title"] for r in result["results"]}
    assert "Matches all row" in titles
    assert "Wrong channel row" not in titles
