"""Tests for controllers/macro_run.py - macro_signal fetch run tracking
via the same `runs` table every other domain uses (GET /runs?domain=
macro_signal), and the POST /macro/fetch route that triggers it."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest


def test_create_macro_fetch_run_uses_real_lookback_days_for_backfill():
    with patch("controllers.macro_run.create_run", return_value=42) as mock_create:
        from controllers.macro_run import create_macro_fetch_run
        from macro_signal_fetch import FETCH_LOOKBACK_DAYS

        run_id = create_macro_fetch_run(incremental=False)

    assert run_id == 42
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["domain"] == "macro_signal"
    assert call_kwargs["days_back"] == FETCH_LOOKBACK_DAYS
    assert call_kwargs["max_articles"] is None
    assert call_kwargs["focus"] is None


def test_create_macro_fetch_run_uses_real_lookback_days_for_incremental():
    with patch("controllers.macro_run.create_run", return_value=43) as mock_create:
        from controllers.macro_run import create_macro_fetch_run
        from macro_signal_fetch import INCREMENTAL_LOOKBACK_DAYS

        create_macro_fetch_run(incremental=True)

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["days_back"] == INCREMENTAL_LOOKBACK_DAYS


def test_run_macro_fetch_completes_run_with_real_observation_count():
    fake_observations = [{"series_id": "DGS10"}, {"series_id": "DFF"}]
    with patch("controllers.macro_run.fetch_all_macro_signals", return_value=fake_observations), \
         patch("controllers.macro_run.insert_macro_observations", return_value=2) as mock_insert, \
         patch("controllers.macro_run.complete_run") as mock_complete, \
         patch("controllers.macro_run.fail_run") as mock_fail:
        from controllers.macro_run import run_macro_fetch
        run_macro_fetch(run_id=1, fred_api_key="fake-key", incremental=True)

    mock_insert.assert_called_once_with(fake_observations)
    mock_complete.assert_called_once_with(1, 2)
    mock_fail.assert_not_called()


def test_run_macro_fetch_marks_run_failed_on_exception_not_raised():
    """A real fetch failure (bad key, FRED outage) must land the run
    row in status='failed', not propagate and crash the caller -
    especially important for the background-task path (routes/macro.py)
    where an uncaught exception would just vanish into FastAPI's
    background task machinery with no record of what happened."""
    with patch("controllers.macro_run.fetch_all_macro_signals", side_effect=RuntimeError("FRED is down")), \
         patch("controllers.macro_run.insert_macro_observations") as mock_insert, \
         patch("controllers.macro_run.complete_run") as mock_complete, \
         patch("controllers.macro_run.fail_run") as mock_fail:
        from controllers.macro_run import run_macro_fetch
        run_macro_fetch(run_id=7, fred_api_key="fake-key", incremental=False)  # must not raise

    mock_insert.assert_not_called()
    mock_complete.assert_not_called()
    mock_fail.assert_called_once()
    assert mock_fail.call_args.args[0] == 7
    assert "FRED is down" in mock_fail.call_args.args[1]


def test_post_macro_fetch_requires_fred_api_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.create_app())
    resp = client.post(
        "/macro/fetch",
        json={"incremental": True},
        headers={"x-ocn-caller": _admin_caller_header()},
    )
    assert resp.status_code == 500


def test_post_macro_fetch_creates_run_and_returns_202(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    from fastapi.testclient import TestClient
    import app as app_module

    with patch("routes.macro.create_macro_fetch_run", return_value=99), \
         patch("routes.macro.run_macro_fetch"):
        client = TestClient(app_module.create_app())
        resp = client.post(
            "/macro/fetch",
            json={"incremental": True},
            headers={"x-ocn-caller": _admin_caller_header()},
        )

    assert resp.status_code == 202
    assert resp.json() == {"run_id": 99, "status": "running"}


def test_get_macro_series_requires_auth():
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.create_app())
    resp = client.get("/macro/series")
    assert resp.status_code == 401


def test_get_macro_series_returns_full_universe_with_valid_auth():
    """Real ask (frontend ticket, 2026-09-25): the UI shows "Coverage
    X / Y series" but had no way to read Y (total tracked series) -
    only X (series reporting in a window) was derivable from /results
    rows. This is a fixed in-memory constant (MACRO_SERIES_UNIVERSE),
    not a DB query - asserting the real count (46) so this breaks
    loudly if the universe ever changes without this test being
    updated."""
    from fastapi.testclient import TestClient
    import app as app_module
    from macro_signal_fetch import MACRO_SERIES_UNIVERSE

    client = TestClient(app_module.create_app())
    resp = client.get(
        "/macro/series",
        headers={"x-ocn-caller": _admin_caller_header()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(MACRO_SERIES_UNIVERSE) == 46
    assert len(body["series"]) == 46
    assert {"series_id": "DGS10", "channel": "discount_rate"} in body["series"]


def test_get_macro_observations_requires_auth():
    """Regression test for a real bug found live (2026-09-25, real staging
    ALB request with no Authorization header returned 200 with real
    data): GET /macro/observations was missing Depends(require_auth)
    entirely. The api-gateway's /news/* proxy only enforces its own
    auth for paths starting with "market/" (see api-gateway/routes/
    proxy_routes.py) - any other /news/* route, this one included, is
    reachable with no x-ocn-caller header unless the route enforces its
    own auth, same as every other GET route in this file already does."""
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.create_app())
    resp = client.get("/macro/observations")
    assert resp.status_code == 401


def test_get_macro_observations_returns_data_with_valid_auth():
    from fastapi.testclient import TestClient
    import app as app_module

    with patch("routes.macro.get_macro_observations", return_value=([], None)):
        client = TestClient(app_module.create_app())
        resp = client.get(
            "/macro/observations",
            headers={"x-ocn-caller": _admin_caller_header()},
        )
    assert resp.status_code == 200


def _admin_caller_header() -> str:
    import base64
    import json
    return base64.b64encode(json.dumps({"sub": 0, "role": "admin", "domains": []}).encode()).decode()
