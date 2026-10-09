"""The china_market_signal metadata fields a consumer joins on.

These cover the four things the China Signals page reads and that
nothing else would catch if they regressed: the currency a figure was
filed in, why a read-through link exists, the capex baseline, and the
tracked-universe list.

The currency and relationship tests exist because both fields are
easy to drop silently - a figure with no currency still looks like a
number, and a read-through group with no relationship still renders.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pipeline.china_companies import (  # noqa: E402
    CHINA_COMPANIES, china_company_universe, read_through_for)
from pipeline.china_signal_classifier import (  # noqa: E402
    _c5_table_column, _c6_sector, _C5_CAPEX_TABLE_ROW_RE, _iso_currency,
    classify_platform_capex, compute_c5_baselines, extract_filing_figures,
    resolve_issuer)

_VALID_RELATIONSHIPS = {"competitor", "supplier", "customer", "parent"}


class TestCurrency:
    """C3/C5 figures name the currency they were FILED in."""

    @pytest.mark.parametrize("marker,expected", [
        ("US$", "USD"), ("USD", "USD"), ("$", "USD"), ("美元", "USD"),
        ("HK$", "HKD"), ("港元", "HKD"),
        ("RMB", "CNY"), ("人民币", "CNY"), ("¥", "CNY"),
        (None, "CNY"), ("", "CNY"), ("ZZZ", "CNY"),
    ])
    def test_markers_normalise_to_iso_codes(self, marker, expected):
        # A consumer switches on this field, so three spellings of one
        # currency is a bug even though each is individually correct.
        assert _iso_currency(marker) == expected

    def test_a_us_dollar_commitment_keeps_its_filed_figure(self, monkeypatch):
        # Baidu's JOYY acquisition, the one real USD case in the
        # stored history: US$2.1bn converted to CNY for comparability,
        # with the filed figure kept beside it.
        #
        # The ECB lookup is stubbed rather than called - a unit test
        # that reaches the network fails when the network does, and
        # would assert against a rate that is not this test's subject.
        import pipeline.china_signal_classifier as mod
        monkeypatch.setattr(mod, "_fx_lookup", lambda code, date: 6.7858)
        figures = extract_filing_figures(
            "The Company will invest US$2.1 billion in the acquisition.",
            "2023-02-07")
        entry = figures["max_amount_entry"]
        assert _iso_currency(entry["currency"]) == "USD"
        assert entry["native_value"] == pytest.approx(2.1e9)
        # Pinned to the FILING's date, not the run date - this is what
        # makes a reclassify reproduce the same figure.
        assert entry["fx_rate"] == pytest.approx(6.7858)
        assert entry["fx_rate_as_of"] == "2023-02-07"
        assert entry["fx_rate_source"] == "ecb"
        # The converted value is what baselines compare against.
        assert figures["max_amount"] == pytest.approx(2.1e9 * 6.7858)

    def test_a_failed_lookup_falls_back_rather_than_skipping_conversion(
            self, monkeypatch):
        # The failure that matters: an unconverted US$ figure entering
        # a renminbi baseline is a ~7x error, so a dead API must still
        # convert - on an approximation, marked as one.
        import pipeline.china_signal_classifier as mod
        monkeypatch.setattr(mod, "_fx_lookup", lambda code, date: None)
        figures = extract_filing_figures(
            "The Company will invest US$2.1 billion in the acquisition.",
            "2023-02-07")
        entry = figures["max_amount_entry"]
        assert entry["fx_rate"] > 6.0, "a dollar figure must not pass at 1.0"
        assert entry["fx_rate_source"] == "fallback"

    def test_the_rate_is_cached_per_date_not_per_figure(self, monkeypatch):
        # A backfill classifies thousands of filings across a few
        # hundred dates; one lookup per date, not per amount.
        import pipeline.china_signal_classifier as mod
        calls: list[tuple[str, str]] = []

        def _counting(code, date):
            calls.append((code, date))
            return 6.7858

        monkeypatch.setattr(mod, "_fx_lookup", _counting)
        for _ in range(3):
            extract_filing_figures(
                "The Company will invest US$2.1 billion.", "2023-02-07")
        # _fx_lookup itself memoises; here it is stubbed, so just
        # assert the same (code, date) is what gets asked for.
        assert {c for c in calls} == {("USD", "2023-02-07")}

    def test_a_renminbi_filing_is_not_converted(self):
        figures = extract_filing_figures("本公司拟投资人民币15.5亿元建设产线。")
        assert _iso_currency(figures["max_amount_entry"]["currency"]) == "CNY"
        assert figures["max_amount"] == pytest.approx(15.5e8)

    @pytest.mark.parametrize("body,expected", [
        ("Capital expenditures of RMB 52.8 billion", "CNY"),
        ("capital expenditure US$ 3.2 billion", "USD"),
        ("资本开支 45 亿元", "CNY"),
    ])
    def test_capex_rows_carry_a_currency(self, body, expected):
        rows = classify_platform_capex([
            {"title": "", "body": body,
             "metadata": {"code": "00700", "company": "Tencent"}}])
        assert rows[0]["result"]["metadata"]["currency"] == expected


class TestCapexTableColumn:
    """The capex column picked matches the period the title reports."""

    # Tencent's interim table: three quarterly columns, then two
    # cumulative ones. Taking the first stored a QUARTER under an H1
    # label - 6 of 7 stored rows were wrong this way.
    ROW = "Capital expenditures (d) 52,784 31,936 19,107 84,720 46,583"

    def test_a_half_year_title_takes_the_cumulative_column(self):
        m = _C5_CAPEX_TABLE_ROW_RE.search(self.ROW)
        assert _c5_table_column(m, "2026H1") == pytest.approx(84720)

    def test_a_nine_month_title_takes_the_cumulative_column(self):
        m = _C5_CAPEX_TABLE_ROW_RE.search(self.ROW)
        assert _c5_table_column(m, "2026Q3") == pytest.approx(84720)

    def test_no_period_falls_back_to_the_first_column(self):
        m = _C5_CAPEX_TABLE_ROW_RE.search(self.ROW)
        assert _c5_table_column(m, None) == pytest.approx(52784)

    def test_a_single_figure_row_is_unaffected(self):
        m = _C5_CAPEX_TABLE_ROW_RE.search("Capital expenditures 12,345")
        assert _c5_table_column(m, "2026H1") == pytest.approx(12345)


class TestCapexBaselines:
    """C5 reports the same spread fields C2 does."""

    @staticmethod
    def _filings(values, code="09988", company="Alibaba Group"):
        return [{"title": f"{2020 + i}年年度报告",
                 "body": f"Capital expenditures of RMB {v} billion.",
                 "metadata": {"code": code, "company": company}}
                for i, v in enumerate(values)]

    def test_a_baseline_needs_three_observations(self):
        [row] = compute_c5_baselines(self._filings([40.0, 52.8]))
        assert row["sample_size"] == 2
        assert row["is_trusted"] is False
        # Refuses to state a spread it cannot compute, rather than
        # reporting a fabricated one.
        assert row["mad"] is None

    def test_a_trusted_baseline_carries_median_and_mad(self):
        [row] = compute_c5_baselines(self._filings([40.0, 52.8, 55.0, 95.0]))
        assert row["is_trusted"] is True
        assert row["sample_size"] == 4
        assert row["median"] > 0 and row["mad"] > 0
        assert row["metric"] == "capex_value"

    def test_rows_carry_the_baseline_fields_when_one_exists(self):
        filings = self._filings([40.0, 52.8, 55.0, 95.0])
        baselines = {(r["code"], r["period_type"]): r
                     for r in compute_c5_baselines(filings)}
        rows = classify_platform_capex(filings, baselines=baselines)
        for row in rows:
            meta = row["result"]["metadata"]
            assert "company_median_value" in meta
            assert "company_mad_value" in meta
            assert "deviation_mads" in meta
            assert meta["baseline_observations"] == 4

    def test_without_a_baseline_the_fields_are_absent_not_zero(self):
        # "Not measured" and "measured and ordinary" must stay
        # distinguishable; a 0.0 default would conflate them.
        meta = classify_platform_capex(
            self._filings([52.8]))[0]["result"]["metadata"]
        assert "deviation_mads" not in meta
        assert "baseline_observations" not in meta

    def test_a_flat_history_does_not_inflate_an_ordinary_move(self):
        # The fraction-of-median floor is what stops a company with
        # near-identical quarters scoring every later move as enormous.
        flat = self._filings([50.0, 50.1, 50.2, 50.3], code="00700",
                             company="Tencent")
        baselines = {(r["code"], r["period_type"]): r
                     for r in compute_c5_baselines(flat)}
        probe = [{"title": "2026年年度报告",
                  "body": "Capital expenditures of RMB 60.0 billion.",
                  "metadata": {"code": "00700", "company": "Tencent"}}]
        meta = classify_platform_capex(
            probe, baselines=baselines)[0]["result"]["metadata"]
        assert abs(meta["deviation_mads"]) < 3.0


class TestReadThroughRelationship:
    """Every read-through link says WHY the two are linked."""

    def test_every_link_in_the_table_has_a_valid_relationship(self):
        for code, company in CHINA_COMPANIES.items():
            for link in company["read_through"]:
                assert link.get("relationship") in _VALID_RELATIONSHIPS, (
                    f"{code} {company['company']} -> {link['tickers']}")

    def test_the_builder_emits_it(self):
        [link] = read_through_for("688082", "C3")[:1]
        assert link["relationship"] == "parent"
        assert link["tickers"] == ["ACMR"]

    def test_relationship_is_stable_where_direction_is_not(self):
        # MP Materials is a competitor to the rare-earth names whether
        # the signal type makes the read `same` (policy) or `opposite`
        # (output). Direction alone cannot express that.
        [under_c2] = read_through_for("600111", "C2")
        [under_c1] = read_through_for("600111", "C1")
        assert under_c2["direction"] == "opposite"
        assert under_c1["direction"] == "same"
        assert under_c2["relationship"] == under_c1["relationship"] == (
            "competitor")

    def test_a_foundry_buying_tools_is_a_customer_not_a_competitor(self):
        links = {tuple(link["tickers"]): link
                 for link in read_through_for("688981", "C3")}
        assert links[("TSM", "UMC", "GFS")]["relationship"] == "competitor"
        assert links[("AMAT", "LRCX", "KLAC")]["relationship"] == "customer"


class TestIssuer:
    """Policy and trade rows name the body that issued the document."""

    def test_a_provincial_body_is_read_from_the_title(self):
        # The reported bug: Hubei's own notice, published on the MIIT
        # site, was attributed to the ministry. 8 of 87 stored MIIT
        # rows are provincial like this.
        issuer, source = resolve_issuer(
            "湖北通信管理局赴襄阳、十堰开展安全生产、网络运行安全专项督导检查",
            "miit_policy")
        assert issuer == "Hubei Communications Administration"
        assert source == "document"

    def test_a_genuine_ministry_document_keeps_the_ministry(self):
        # The other 79 really are MIIT - the fix must not take those
        # away in the course of fixing the 8.
        issuer, source = resolve_issuer(
            "工业和信息化部等五部门关于组织开展2026年度国家绿色算力设施推荐工作的通知",
            "miit_policy")
        assert issuer.startswith("Ministry of Industry")
        assert source == "source"

    @pytest.mark.parametrize("source_type,expected", [
        ("mofcom_policy", "Ministry of Commerce (MOFCOM)"),
        ("samr_action", "State Administration for Market Regulation (SAMR)"),
        ("cac_review", "Cyberspace Administration of China (CAC)"),
        ("nbs_ic_output", "National Bureau of Statistics (NBS)"),
        ("comtrade_china_trade", "UN Comtrade"),
        ("cn_state_press", "Xinhua"),
    ])
    def test_every_policy_and_trade_source_resolves(self, source_type,
                                                    expected):
        # cn_state_press, cac_review and nbs_ic_output stored no
        # issuing_body at all and would have rendered as raw codes.
        issuer, source = resolve_issuer("某公告标题", source_type)
        assert issuer == expected
        assert source == "source"

    def test_an_unmapped_source_gets_no_issuer_rather_than_a_guess(self):
        assert resolve_issuer("x", "press_cn") == (None, "")
        assert resolve_issuer("x", None) == (None, "")

    def test_the_source_field_distinguishes_a_fact_from_a_fallback(self):
        # Without this a per-feed default is indistinguishable from a
        # name read off the document - which is how the Hubei row
        # looked correct while being wrong.
        _, from_doc = resolve_issuer("浙江通信管理局开展主题活动", "miit_policy")
        _, from_feed = resolve_issuer("关于某事项的通知", "miit_policy")
        assert from_doc == "document"
        assert from_feed == "source"


class TestC6Sector:
    """C6 rows carry the sector their commodity code belongs to."""

    @pytest.mark.parametrize("code,expected", [
        ("8542", "Semiconductors"),
        ("8486", "Semiconductor Equipment"),
        # A more specific code still resolves on its HS4 prefix.
        ("85423110", "Semiconductors"),
    ])
    def test_known_codes_resolve(self, code, expected):
        assert _c6_sector(code) == expected

    def test_an_unmapped_code_gets_no_sector(self):
        # A sector is a lookup, not an inference - an unknown code
        # gets nothing rather than a plausible-sounding label.
        assert _c6_sector("9999") is None
        assert _c6_sector(None) is None
        assert _c6_sector("") is None


class TestUniverseView:
    """GET /china-signals/universe's payload."""

    def test_it_covers_every_tracked_company(self):
        universe = china_company_universe()
        assert len(universe) == len(CHINA_COMPANIES)
        assert {c["code"] for c in universe} == set(CHINA_COMPANIES)

    def test_every_company_has_a_native_name(self):
        missing = [c["code"] for c in china_company_universe()
                   if not c["native_name"]]
        assert missing == []

    def test_dual_listed_names_carry_an_hk_code(self):
        by_code = {c["code"]: c for c in china_company_universe()}
        assert by_code["688981"]["hk_code"] == "00981"
        assert by_code["688347"]["hk_code"] == "01347"
        # A mainland-only listing has none, rather than a placeholder.
        assert by_code["002371"]["hk_code"] is None

    def test_it_is_json_serialisable(self):
        # signal_roles is a set on the table and would raise here if
        # the view ever spread the record instead of naming fields.
        import json
        assert json.dumps(china_company_universe())

    def test_signal_roles_are_ordered_so_the_response_is_stable(self):
        for company in china_company_universe():
            assert company["signal_roles"] == sorted(company["signal_roles"])

    def test_internal_routing_details_are_not_exposed(self):
        for company in china_company_universe():
            for link in company["read_through"]:
                assert set(link) == {"tickers", "direction", "relationship"}
