"""Tests for the macro_signal domain: knowledge_time construction,
first-print rule branching, upsert dedup, and the /macro/observations
endpoint. Uses the real news-retrieval-test Postgres DB per this
service's existing test conventions; FRED/Treasury HTTP calls are
mocked - never hits real external APIs in tests.
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from macro_release_times import (
    KnowledgeTimeDropped,
    knowledge_time_for_observation,
)
from models.macro_observations import get_macro_observations, insert_macro_observations


# --- knowledge_time construction ---

def test_tier_a_verified_release_dst_boundary():
    """January (EST, UTC-5) vs July (EDT, UTC-4) for the same nominal
    08:30 ET release time must differ by exactly 1 hour in UTC."""
    kt_jan, conf_jan = knowledge_time_for_observation("CPIAUCSL", date(2026, 1, 14), release_date=date(2026, 1, 14))
    kt_jul, conf_jul = knowledge_time_for_observation("CPIAUCSL", date(2026, 7, 14), release_date=date(2026, 7, 14))
    assert conf_jan == "verified"
    assert conf_jul == "verified"
    assert kt_jan.hour - kt_jul.hour == 1


def test_tier_a_none_time_release_falls_back_to_close_stamp():
    """release_id 17 (H.10 Foreign Exchange Rates) has no fixed clock
    time in RELEASE_TIMES - falls through to 16:30 ET."""
    kt, conf = knowledge_time_for_observation("DTWEXBGS", date(2026, 8, 28), release_date=date(2026, 8, 28))
    assert conf == "verified"
    # DTWEXBGS is in DAILY_MARKET_CLOSE_SERIES anyway, so this exercises
    # the close-stamp path either way.
    assert kt.hour in (20, 21)  # 16:30 ET in UTC, DST-dependent


def test_tier_c_known_lag_close_today_bal():
    kt, conf = knowledge_time_for_observation("close_today_bal", date(2026, 8, 28))  # a Friday
    assert conf == "known_lag"
    assert kt.date() == date(2026, 8, 31)  # next business day, skipping the weekend


def test_no_tier_applies_raises_dropped():
    with pytest.raises(KnowledgeTimeDropped):
        knowledge_time_for_observation("NOT_A_REAL_SERIES", date(2026, 8, 28), release_date=date(2026, 8, 28))


def test_verified_tier_series_without_release_date_is_dropped_not_guessed():
    with pytest.raises(KnowledgeTimeDropped):
        knowledge_time_for_observation("CPIAUCSL", date(2026, 8, 28), release_date=None)


# --- first-print rule branching ---

def test_first_print_rule_pre_cutoff_uses_plain_fred():
    from macro_signal_fetch import FRED_FIRST_PRINT_CUTOFF
    assert FRED_FIRST_PRINT_CUTOFF == date(2015, 1, 1)


def test_first_print_rule_branches_by_revised_flag():
    """CRITICAL: the ALFRED vintage_dates parameter must be the VERIFIED
    RELEASE DATE, not the observation date and not merely the nearest
    release-calendar date - confirmed live against real FRED that (a)
    passing the observation date directly is a 400 ("Vintage date is
    not a release date for this series"), and (b) nearest-by-proximity
    resolution silently attaches the WRONG month's release for
    CPI/PAYEMS-style series that publish ~6 weeks after month-end. This
    test uses a release_date DIFFERENT from the observation date
    specifically to catch a regression - a test that coincidentally uses
    the same value for both would pass even with either bug present.

    Also confirms the resolved release date is reused directly for the
    row's knowledge_time construction (not re-resolved via a second,
    possibly-different call) - the cheap resolver must NOT be invoked
    for a post-cutoff ALFRED row."""
    obs_date = date(2026, 8, 28)
    pre_cutoff_obs_date = date(2014, 6, 1)
    verified_release_date = date(2026, 9, 12)  # deliberately different from obs_date
    cheap_release_date = date(2014, 7, 1)  # deliberately different from pre_cutoff_obs_date

    with patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_verified", return_value=verified_release_date) as mock_verified, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_cheap", return_value=cheap_release_date) as mock_cheap:
        mock_fetch.side_effect = [
            # One combined plain call now covers both pre- and
            # post-cutoff observations (the original two-call shape was
            # fetching the same series twice with identical params -
            # fixed alongside the lookback bound).
            [
                {"date": pre_cutoff_obs_date.isoformat(), "value": "2.5"},
                {"date": obs_date.isoformat(), "value": "3.1"},
            ],
            [{"date": obs_date.isoformat(), "value": "3.1"}],  # ALFRED vintage call
        ]
        from macro_signal_fetch import _fetch_one_fred_series
        rows = _fetch_one_fred_series({"series_id": "CPIAUCSL", "revised": True}, "fake-key")

        vintage_calls = [c for c in mock_fetch.call_args_list if c.kwargs.get("vintage") is not None]
        assert len(vintage_calls) == 1
        assert vintage_calls[0].kwargs["vintage"] == verified_release_date  # NOT obs_date, NOT nearest-only

        alfred_row = next(r for r in rows if r["source"] == "fred_alfred")
        assert alfred_row["vintage"] == verified_release_date

        pre_cutoff_row = next(r for r in rows if r["source"] == "fred")
        assert pre_cutoff_row["vintage"] is None  # never-verified pre-cutoff row has no vintage

        # Verified resolver called once (for the post-cutoff row); cheap
        # resolver called once (for the pre-cutoff row) - never the
        # verified resolver twice for the same row.
        assert mock_verified.call_count == 1
        assert mock_cheap.call_count == 1


def test_first_print_rule_skips_observation_when_release_date_unresolvable():
    with patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_verified", return_value=None):
        mock_fetch.return_value = [{"date": "2026-08-28", "value": "3.1"}]  # one combined plain call, post-cutoff only
        from macro_signal_fetch import _fetch_one_fred_series
        rows = _fetch_one_fred_series({"series_id": "CPIAUCSL", "revised": True}, "fake-key")
        # No ALFRED call should have been attempted, and no row produced
        # for the unresolvable observation - never a 400, never a guess.
        vintage_calls = [c for c in mock_fetch.call_args_list if c.kwargs.get("vintage") is not None]
        assert len(vintage_calls) == 0
        assert rows == []


def test_never_revised_series_always_plain_call_no_vintage():
    with patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_cheap", return_value=date(2026, 8, 28)):
        mock_fetch.return_value = [{"date": "2026-08-28", "value": "4.5"}]
        from macro_signal_fetch import _fetch_one_fred_series
        rows = _fetch_one_fred_series({"series_id": "DGS10", "revised": False}, "fake-key")

        for call in mock_fetch.call_args_list:
            assert call.kwargs.get("vintage") is None
        assert all(r["source"] == "fred" for r in rows)


# --- DB: insert/upsert/read (real test Postgres) ---

@pytest.fixture(autouse=True)
def _clean_macro_observations():
    from db import get_db, init_db
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM macro_observations")
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM macro_observations")


def _sample_obs(**overrides):
    base = {
        "series_id": "DGS10",
        "observation_date": date(2026, 8, 28),
        "value": 4.73,
        "knowledge_time": knowledge_time_for_observation("DGS10", date(2026, 8, 28), date(2026, 8, 28))[0],
        "knowledge_time_confidence": "verified",
        "vintage": None,
        "source": "fred",
        "raw_payload": {"date": "2026-08-28", "value": "4.73"},
    }
    base.update(overrides)
    return base


def test_insert_and_upsert_no_duplicate():
    count1 = insert_macro_observations([_sample_obs()])
    assert count1 == 1
    # Re-insert the same (series_id, observation_date, NULL vintage) key -
    # must update in place, not create a second row.
    count2 = insert_macro_observations([_sample_obs(value=4.80)])
    assert count2 == 1

    rows, _ = get_macro_observations(series_ids=["DGS10"])
    assert len(rows) == 1
    assert float(rows[0]["value"]) == 4.80


def test_different_vintages_are_distinct_rows():
    insert_macro_observations([_sample_obs(series_id="CPIAUCSL", vintage=date(2020, 1, 1), source="fred_alfred")])
    insert_macro_observations([_sample_obs(series_id="CPIAUCSL", vintage=date(2020, 2, 1), source="fred_alfred")])
    rows, _ = get_macro_observations(series_ids=["CPIAUCSL"])
    assert len(rows) == 2


def test_get_macro_observations_filters_by_series_and_date():
    insert_macro_observations([
        _sample_obs(series_id="DGS10", observation_date=date(2026, 8, 27)),
        _sample_obs(series_id="DGS10", observation_date=date(2026, 8, 28)),
        _sample_obs(series_id="DFII10", observation_date=date(2026, 8, 28)),
    ])
    rows, _ = get_macro_observations(series_ids=["DGS10"], from_date=date(2026, 8, 28))
    assert len(rows) == 1
    assert rows[0]["series_id"] == "DGS10"
    assert rows[0]["observation_date"] == date(2026, 8, 28)


def test_get_macro_observations_pagination():
    obs = [
        _sample_obs(series_id="DGS10", observation_date=date(2026, 1, 1 + i))
        for i in range(5)
    ]
    insert_macro_observations(obs)

    page1, cursor1 = get_macro_observations(series_ids=["DGS10"], limit=2)
    assert len(page1) == 2
    assert cursor1 is not None

    page2, cursor2 = get_macro_observations(series_ids=["DGS10"], limit=2, cursor=cursor1)
    assert len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})

    page3, cursor3 = get_macro_observations(series_ids=["DGS10"], limit=2, cursor=cursor2)
    assert len(page3) == 1
    assert cursor3 is None


# --- Treasury Fiscal Data: account_type era handling ---

def _treasury_page(rows, total_pages=1):
    return {"data": rows, "meta": {"total-pages": total_pages}}


def test_treasury_fiscal_queries_all_three_account_type_eras():
    """CONFIRMED LIVE 2026-09-24: Treasury's DTS operating_cash_balance
    table renamed/restructured account_type twice - 'Federal Reserve
    Account' (through 2021-09-30), then 'Treasury General Account (TGA)'
    (through 2022-04-15), then split into Opening/Deposits/Withdrawals/
    Closing rows with the real balance in open_today_bal on the
    '...Closing Balance' row, not close_today_bal (which is 'null' on
    every row in that era). A single filter/field pair silently
    truncates history at 2021-09-30 - this test catches a regression
    back to that single-era bug."""
    from macro_signal_fetch import _TREASURY_ACCOUNT_TYPE_ERAS

    responses_by_account_type = {
        "Federal Reserve Account": _treasury_page([
            {"record_date": "2020-01-02", "account_type": "Federal Reserve Account", "close_today_bal": "1000"},
        ]),
        "Treasury General Account (TGA)": _treasury_page([
            {"record_date": "2021-10-01", "account_type": "Treasury General Account (TGA)", "close_today_bal": "2000"},
        ]),
        "Treasury General Account (TGA) Closing Balance": _treasury_page([
            {"record_date": "2025-01-02", "account_type": "Treasury General Account (TGA) Closing Balance", "open_today_bal": "3000"},
        ]),
    }

    def fake_get(url, params=None, timeout=None):
        # filter now looks like "account_type:eq:<name>,record_date:gte:<date>"
        account_type = params["filter"].split(":eq:", 1)[1].split(",record_date:gte:")[0]
        resp = MagicMock()
        resp.json.return_value = responses_by_account_type[account_type]
        resp.raise_for_status.return_value = None
        return resp

    with patch("macro_signal_fetch.httpx.get", side_effect=fake_get):
        from macro_signal_fetch import fetch_treasury_fiscal
        rows = fetch_treasury_fiscal()

    assert len(_TREASURY_ACCOUNT_TYPE_ERAS) == 3
    dates = {r["observation_date"]: r["value"] for r in rows}
    assert dates[date(2020, 1, 2)] == 1000.0
    assert dates[date(2021, 10, 1)] == 2000.0
    # The 2025 row's value comes from open_today_bal, not close_today_bal
    # (which doesn't exist in the response for this era) - confirms the
    # per-era value_field mapping is actually used, not hardcoded to
    # close_today_bal everywhere.
    assert dates[date(2025, 1, 2)] == 3000.0


# --- Fetch lookback bound (3 years, not each series' full history) ---

def test_fred_fetch_bounds_observation_start_to_lookback():
    """The pipeline's z-score only ever reads a rolling 2-year window -
    fetching each series' full history (some series' FRED history goes
    back to the 1940s) wastes fetch time and storage on data nothing
    downstream reads. This confirms observation_start is actually passed
    to FRED, not silently dropped."""
    with patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_cheap", return_value=None):
        mock_fetch.return_value = [{"date": "2026-08-28", "value": "4.5"}]
        from macro_signal_fetch import _fetch_one_fred_series, FETCH_LOOKBACK_DAYS
        _fetch_one_fred_series({"series_id": "DGS10", "revised": False}, "fake-key", lookback_days=100)

        assert mock_fetch.call_count == 1
        call = mock_fetch.call_args
        assert call.kwargs.get("observation_start") is not None
        expected_start = date.today() - timedelta(days=100)
        assert call.kwargs["observation_start"] == expected_start


def test_fred_fetch_defaults_to_module_lookback_constant():
    with patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch, \
         patch("macro_signal_fetch._resolve_release_date_for_observation_cheap", return_value=None):
        mock_fetch.return_value = []
        from macro_signal_fetch import _fetch_one_fred_series, FETCH_LOOKBACK_DAYS
        _fetch_one_fred_series({"series_id": "DGS10", "revised": False}, "fake-key")

        expected_start = date.today() - timedelta(days=FETCH_LOOKBACK_DAYS)
        assert mock_fetch.call_args.kwargs["observation_start"] == expected_start
        assert FETCH_LOOKBACK_DAYS == 3 * 365


# --- Incremental fetch mode (daily runs fetch a fixed 2-day window,
# not the full 3-year backfill) ---

def test_incremental_mode_uses_fixed_short_lookback():
    """incremental=True must pass a small, FIXED lookback_days to every
    series' fetch - no watermark lookup, no per-series DB query, just a
    constant. This is what makes a daily scheduled run cheap instead of
    re-pulling years of history every day."""
    from macro_signal_fetch import INCREMENTAL_LOOKBACK_DAYS

    with patch("macro_signal_fetch._fetch_one_fred_series") as mock_fetch_series, \
         patch("macro_signal_fetch.fetch_treasury_fiscal") as mock_fetch_treasury:
        mock_fetch_series.return_value = []
        mock_fetch_treasury.return_value = []
        from macro_signal_fetch import fetch_all_macro_signals
        fetch_all_macro_signals("fake-key", incremental=True)

        assert INCREMENTAL_LOOKBACK_DAYS == 1
        dgs10_calls = [c for c in mock_fetch_series.call_args_list if c.args[0]["series_id"] == "DGS10"]
        assert len(dgs10_calls) == 1
        assert dgs10_calls[0].kwargs["lookback_days"] == 1

        treasury_calls = mock_fetch_treasury.call_args_list
        assert len(treasury_calls) == 1
        assert treasury_calls[0].kwargs["lookback_days"] == 1


def test_non_incremental_mode_uses_full_lookback():
    """The default (incremental=False) must fetch the full 3-year window
    per series - the one-time initial backfill shape."""
    with patch("macro_signal_fetch._fetch_one_fred_series") as mock_fetch_series, \
         patch("macro_signal_fetch.fetch_treasury_fiscal") as mock_fetch_treasury:
        mock_fetch_series.return_value = []
        mock_fetch_treasury.return_value = []
        from macro_signal_fetch import fetch_all_macro_signals
        fetch_all_macro_signals("fake-key", incremental=False)

        dgs10_calls = [c for c in mock_fetch_series.call_args_list if c.args[0]["series_id"] == "DGS10"]
        assert dgs10_calls[0].kwargs["lookback_days"] is None  # None -> callee's own FETCH_LOOKBACK_DAYS (3yr) default


# --- Release date candidate search: nearest-first, both directions ---

def test_release_date_candidates_nearest_first_prefers_backward_over_farther_forward():
    """CONFIRMED LIVE: FEDTARMD's observation_date is the year a dot-plot
    projection is FOR, not a date data covers up to - its real release
    date can be BEFORE observation_date (e.g. the 2026-01-01 observation
    was released 2025-12-10, 22 days backward) while a later, unrelated
    forward release also exists on the same release_id's calendar
    (2026-03-18, 76 days forward). A forward-first search wrongly
    returns the farther, unrelated forward candidate; nearest-first (by
    absolute distance) correctly prefers the close backward one."""
    from macro_signal_fetch import _release_date_candidates

    with patch("macro_signal_fetch._fred_release_dates") as mock_dates, \
         patch("macro_signal_fetch.SERIES_RELEASE_ID", {"FEDTARMD": 326}):
        mock_dates.return_value = {
            date(2025, 12, 10): date(2025, 12, 10),
            date(2026, 3, 18): date(2026, 3, 18),
        }
        candidates = _release_date_candidates("FEDTARMD", date(2026, 1, 1), "fake-key")

    assert candidates[0] == date(2025, 12, 10)  # nearest (22 days) before the farther one (76 days)


def test_verified_resolver_skips_nearer_wrong_candidate_and_finds_real_one():
    """When a nearer-but-wrong candidate exists (e.g. the prior month's
    release, which doesn't actually contain this observation) alongside
    the real, farther release, the VERIFIED resolver must reject the
    wrong nearby one (its ALFRED call won't contain this observation_date)
    and keep trying until it finds the real one - unlike the cheap
    resolver, which would wrongly accept the first (nearest) candidate
    with no verification."""
    from macro_signal_fetch import _resolve_release_date_for_observation_verified

    with patch("macro_signal_fetch._fred_release_dates") as mock_dates, \
         patch("macro_signal_fetch.SERIES_RELEASE_ID", {"CPILFESL": 10}), \
         patch("macro_signal_fetch._fetch_fred_observations") as mock_fetch:
        mock_dates.return_value = {
            date(2014, 12, 18): date(2014, 12, 18),  # nearer (14 days back), but wrong - a different month's release
            date(2015, 2, 26): date(2015, 2, 26),      # farther (56 days forward), the REAL release
        }

        def fake_fetch(series_id, api_key, *, vintage=None, observation_start=None):
            if vintage == date(2014, 12, 18):
                return [{"date": "2014-12-01", "value": "237.9"}]  # doesn't contain 2015-01-01
            if vintage == date(2015, 2, 26):
                return [{"date": "2015-01-01", "value": "239.9"}]  # DOES contain it
            return []

        mock_fetch.side_effect = fake_fetch
        result = _resolve_release_date_for_observation_verified("CPILFESL", date(2015, 1, 1), "fake-key")

    assert result == date(2015, 2, 26)  # correctly skipped the nearer wrong one


# --- Vintage fetch caching (avoid re-fetching the same ALFRED vintage) ---

def test_vintage_fetch_is_cached_across_calls():
    """CONFIRMED LIVE: without caching, a 200-day candidate search window
    means nearby monthly observations independently re-fetch the exact
    same (series_id, vintage) ALFRED call - one real run showed NEWORDER
    alone making 311 HTTP calls for a ~36-observation window because a
    handful of vintage dates were each fetched 5-6 times. A published
    vintage's contents never change, so the second call for the same
    (series_id, vintage) must hit the cache, not the network."""
    import macro_signal_fetch as msf
    msf._vintage_fetch_cache.clear()

    with patch("macro_signal_fetch._fred_get") as mock_fred_get:
        mock_fred_get.return_value = {"observations": [{"date": "2024-01-01", "value": "1.0"}]}

        r1 = msf._fetch_fred_observations("NEWORDER", "fake-key", vintage=date(2024, 2, 1))
        r2 = msf._fetch_fred_observations("NEWORDER", "fake-key", vintage=date(2024, 2, 1))

        assert mock_fred_get.call_count == 1  # second call hit the cache, no second HTTP call
        assert r1 == r2


def test_vintage_fetch_cache_is_per_series_and_per_vintage():
    """A cache hit must be scoped to the exact (series_id, vintage) pair
    - a different series or a different vintage date must NOT reuse
    another entry's cached response."""
    import macro_signal_fetch as msf
    msf._vintage_fetch_cache.clear()

    with patch("macro_signal_fetch._fred_get") as mock_fred_get:
        mock_fred_get.side_effect = [
            {"observations": [{"date": "2024-01-01", "value": "1.0"}]},
            {"observations": [{"date": "2024-02-01", "value": "2.0"}]},
            {"observations": [{"date": "2024-01-01", "value": "3.0"}]},
        ]
        msf._fetch_fred_observations("NEWORDER", "fake-key", vintage=date(2024, 2, 1))
        msf._fetch_fred_observations("NEWORDER", "fake-key", vintage=date(2024, 3, 1))  # different vintage
        msf._fetch_fred_observations("CPILFESL", "fake-key", vintage=date(2024, 2, 1))  # different series

        assert mock_fred_get.call_count == 3  # none of these should have hit each other's cache entry


def test_plain_call_is_never_cached():
    """A plain call (vintage=None) means 'latest values as of now' - its
    meaning depends on when it's called, so it must never be served from
    the vintage cache (which only applies to immutable ALFRED vintages)."""
    import macro_signal_fetch as msf
    msf._vintage_fetch_cache.clear()

    with patch("macro_signal_fetch._fred_get") as mock_fred_get:
        mock_fred_get.return_value = {"observations": []}
        msf._fetch_fred_observations("DGS10", "fake-key")
        msf._fetch_fred_observations("DGS10", "fake-key")

        assert mock_fred_get.call_count == 2  # each plain call hits the network, never cached
