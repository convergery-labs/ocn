"""Pytest fixtures for signal-detection-agent tests."""
# TODO: add DB, app client, and API key fixtures

import pytest


# A stand-in for the tracked Japanese universe, injected for every test.
#
# The real universe lives in research-universe and is fetched over HTTP.
# Tests must not make that call: it would make the suite depend on a
# running service, and on data that changes when someone edits a
# company. So the cache that fetch populates is filled directly instead.
#
# These are real companies with their real filed figures, not invented
# ones, because several tests assert on behaviour that only means
# something against real values - that Sumitomo Corporation is a
# DISTRIBUTOR and so excluded from read-through, that Ibiden's AMD
# share was 11.0% in FY3/25 and is therefore dated, that "ASE" must not
# match inside "PHASE". A fixture of plausible-looking fakes would pass
# while testing nothing.
_FIXTURE_COMPANIES = {
    "6857": {
        "code": "6857", "company": "Advantest",
        "native_name": "アドバンテスト", "fiscal_year_end": "03-31",
        "tse_prime_pct": 1.84, "japan_rank": 6, "japan_sales_pct": 2.2,
        "market_cap_jpy_tn": 27.23, "market_cap_usd_bn": 172.1,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "Nvidia", "ticker": "NVDA", "pct_of_sales": 21.6,
             "period": "FY3/26",
             "aliases": ("Nvidia", "NVIDIA", "エヌビディア"),
             "relationship": "customer", "is_distributor": False},
            {"name": "TSMC", "ticker": "TSM", "pct_of_sales": 11.1,
             "period": "FY3/26",
             "aliases": ("TSMC", "台積電", "台湾積体電路"),
             "relationship": "customer", "is_distributor": False},
            {"name": "US hyperscalers (unnamed)", "ticker": None,
             "pct_of_sales": None, "period": None,
             "aliases": ("US hyperscalers (unnamed)",),
             "relationship": "customer", "is_distributor": False},
        ],
    },
    "6723": {
        "code": "6723", "company": "Renesas Electronics",
        "native_name": "ルネサスエレクトロニクス", "fiscal_year_end": "12-31",
        "tse_prime_pct": 0.47, "japan_rank": 42, "japan_sales_pct": 20.4,
        "market_cap_jpy_tn": 6.3, "market_cap_usd_bn": 41.8,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "Honda", "ticker": "7267", "pct_of_sales": None,
             "period": None, "aliases": ("Honda", "ホンダ", "本田技研"),
             "relationship": "customer", "is_distributor": False},
            {"name": "WT Microelectronics", "ticker": "3036",
             "pct_of_sales": 17.1, "period": "FY12/25",
             "aliases": ("WT Microelectronics",),
             "relationship": "distributor", "is_distributor": True},
        ],
    },
    "4062": {
        "code": "4062", "company": "Ibiden", "native_name": "イビデン",
        "fiscal_year_end": "03-31", "tse_prime_pct": 0.46,
        "japan_rank": 40, "japan_sales_pct": 27.1,
        "market_cap_jpy_tn": 6.4, "market_cap_usd_bn": 42.4,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "AMD", "ticker": "AMD", "pct_of_sales": 11.0,
             "period": "FY3/25", "aliases": ("AMD", "エーエムディー"),
             "relationship": "customer", "is_distributor": False},
            {"name": "ASE Group", "ticker": "3711", "pct_of_sales": None,
             "period": None, "aliases": ("ASE Group", "ASE", "日月光"),
             "relationship": "customer", "is_distributor": False},
            {"name": "Nvidia", "ticker": "NVDA", "pct_of_sales": 29.4,
             "period": "FY3/26",
             "aliases": ("Nvidia", "NVIDIA", "エヌビディア"),
             "relationship": "customer", "is_distributor": False},
            {"name": "Intel", "ticker": "INTC", "pct_of_sales": None,
             "period": None, "aliases": ("Intel", "インテル"),
             "relationship": "customer", "is_distributor": False},
        ],
    },
    "3436": {
        "code": "3436", "company": "SUMCO", "native_name": "SUMCO",
        "fiscal_year_end": "12-31", "tse_prime_pct": 0.09,
        "japan_rank": 181, "japan_sales_pct": 19.4,
        "market_cap_jpy_tn": 1.2, "market_cap_usd_bn": 7.7,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "Sumitomo Corporation", "ticker": "8053",
             "pct_of_sales": 27.0, "period": "FY12/25",
             "aliases": ("Sumitomo Corporation", "住友商事"),
             "relationship": "distributor", "is_distributor": True},
        ],
    },
    "6146": {
        "code": "6146", "company": "Disco", "native_name": "ディスコ",
        "fiscal_year_end": "03-31", "tse_prime_pct": 0.46,
        "japan_rank": 43, "japan_sales_pct": 10.4,
        "market_cap_jpy_tn": 6.2, "market_cap_usd_bn": 41.4,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "TSMC", "ticker": "TSM", "pct_of_sales": None,
             "period": None, "aliases": ("TSMC", "台積電"),
             "relationship": "customer", "is_distributor": False},
        ],
    },
    "6762": {
        "code": "6762", "company": "TDK", "native_name": "TDK",
        "fiscal_year_end": "03-31", "tse_prime_pct": 0.42,
        "japan_rank": 48, "japan_sales_pct": 7.3,
        "market_cap_jpy_tn": 5.8, "market_cap_usd_bn": 38.4,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "Toshiba", "ticker": None, "pct_of_sales": None,
             "period": "2024", "aliases": ("Toshiba", "東芝"),
             "relationship": "customer", "is_distributor": False},
        ],
    },
    "4004": {
        "code": "4004", "company": "Resonac Holdings",
        "native_name": "レゾナック・ホールディングス",
        "fiscal_year_end": "12-31", "tse_prime_pct": 0.21,
        "japan_rank": 83, "japan_sales_pct": 43.4,
        "market_cap_jpy_tn": 2.9, "market_cap_usd_bn": 19.1,
        "market_data_as_of": "2026-10-01",
        "customers": [
            {"name": "Denso", "ticker": "6902", "pct_of_sales": None,
             "period": "2023", "aliases": ("Denso", "デンソー"),
             "relationship": "customer", "is_distributor": False},
        ],
    },
}


@pytest.fixture(autouse=True)
def _tracked_universe():
    """Serve the fixture universe to every test, and never the network.

    Autouse because the universe is not an optional dependency of the
    code under test - a classifier or card that cannot say which
    companies are tracked cannot run at all, and a test that forgot to
    request this fixture would fail with a connection error rather than
    an assertion.
    """
    import pipeline.japan_companies as jc

    jc.reset_universe_cache()
    jc._remote_companies = {
        code: {**rec, "customers": list(rec["customers"])}
        for code, rec in _FIXTURE_COMPANIES.items()
    }
    yield
    jc.reset_universe_cache()
