"""Card-text rules for the Japan Signals view layer.

Each test here pins a wording or link bug reported against the live
API, using the same row shape the real data has.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from pipeline.japan_signal_view import (
    _checkpoint_tests,
    _edinet_still_serves,
    _headline,
    _metric,
    _press_claim_noun,
    _press_headline,
    _rule_text,
    _source_url,
    _target_period_label,
    _usable_progress_baseline,
)


def _recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()


class TestReversalDirection:
    """The rule text must name the direction actually reversed, not the
    company's usual direction."""

    def test_reversed_raise_says_raise(self):
        text = _rule_text({
            "signal_reason_code": "reverses_direction_within_fiscal_year",
            "reversed_direction": "raise",
        })
        assert "earlier raise" in text

    def test_reversed_cut_says_cut(self):
        text = _rule_text({
            "signal_reason_code": "reverses_direction_within_fiscal_year",
            "reversed_direction": "cut",
        })
        assert "earlier cut" in text

    def test_habit_direction_is_not_used_as_a_fallback(self):
        """A row stored before the direction was recorded must stay
        neutral rather than guess from the company's habit."""
        text = _rule_text({
            "signal_reason_code": "reverses_direction_within_fiscal_year",
            "habit_typical_direction": "raise",
        })
        assert "earlier cut" not in text
        assert "earlier raise" not in text


class TestForecastHeadline:
    def test_zero_change_is_not_called_a_cut(self):
        assert _headline("forecast", {"operating_profit_pct_change": 0.0}) == (
            "Left full-year profit forecast unchanged"
        )

    @pytest.mark.parametrize("pct,word", [(5.0, "Raised"), (-33.3, "Cut")])
    def test_real_moves_keep_their_direction(self, pct, word):
        assert _headline("forecast", {"operating_profit_pct_change": pct}).startswith(word)


class TestProgressBaseline:
    """An untrusted habit must not be used to rank the company, or the
    card contradicts its own 'not enough history' signal."""

    SCREEN = {
        "progress_pct": 44.1,
        "fiscal_year_elapsed_pct": 58.5,
        "progress_habit_typical_pct": 39.5,
        "progress_habit_is_trusted": False,
    }

    def test_untrusted_habit_is_refused(self):
        assert _usable_progress_baseline(self.SCREEN) is None

    def test_headline_falls_back_to_elapsed_and_says_behind(self):
        assert _headline("progress", self.SCREEN) == "Ran behind its full-year target"

    def test_metric_matches_the_headline(self):
        metric = _metric("progress", self.SCREEN)
        assert metric["value"] == -14.4
        assert "behind" in metric["label"]

    def test_trusted_habit_is_still_used(self):
        trusted = dict(self.SCREEN, progress_habit_is_trusted=True)
        assert _usable_progress_baseline(trusted) == 39.5
        assert _headline("progress", trusted) == "Ran ahead of its full-year target"

    def test_self_referential_median_is_refused(self):
        same = dict(self.SCREEN, progress_habit_is_trusted=True,
                    progress_habit_typical_pct=44.1)
        assert _usable_progress_baseline(same) is None


class TestTargetPeriodLabel:
    @pytest.mark.parametrize("stored,expected", [
        ("full_year", "full-year"),
        ("half_year", "half-year"),
        ("quarter", "quarterly"),
        (None, "full-year"),
    ])
    def test_label_follows_the_filing(self, stored, expected):
        assert _target_period_label({"target_period_type": stored}) == expected

    def test_headline_uses_the_filings_own_period(self):
        half = {"progress_pct": 46.7, "fiscal_year_elapsed_pct": 31.2,
                "target_period_type": "half_year", "progress_habit_is_trusted": False}
        assert _headline("progress", half) == "Ran ahead of its half-year target"


class TestPressHeadline:
    META = {
        "company": "Resonac Holdings",
        # Curly quotes, as the real translated titles carry them.
        "translated_title": (
            "Resonac Holdings (4004): Resonac achieves Japan’s first success, "
            "develops “12-inch SiC substrate”"
        ),
        "publication_domain": "newswitch.jp",
    }

    def test_verb_first_past_tense_with_the_publication(self):
        assert _headline("press", self.META) == (
            "Developed a 12-inch SiC substrate (Newswitch report)"
        )

    def test_claim_noun_is_the_quoted_product(self):
        assert _press_claim_noun(self.META) == "12-inch SiC substrate"

    def test_unknown_verb_passes_through_unmangled(self):
        meta = {"company": "X Corp", "translated_title": "Ponders a new direction",
                "publication_domain": "nikkei.com"}
        assert _press_headline("Ponders a new direction", meta) == (
            "Ponders a new direction (Nikkei report)"
        )


class TestSourceUrl:
    """A buyback row links to the EDINET filing while EDINET still
    serves it, and to the company's buyback list once it does not."""

    def test_recent_buyback_links_to_the_filing_pdf(self):
        url = _source_url({"code": "285A"}, "irbank-buyback://285A/S100Z1UD",
                          "2026-09-11T00:00:00+00:00")
        assert url.endswith("/S100Z1UD.pdf")

    def test_old_buyback_falls_back_to_the_list_page(self):
        url = _source_url({"code": "4186"}, "irbank-buyback://4186/S1004UZ6",
                          "2015-06-04T00:00:00+00:00")
        assert url == "https://irbank.net/4186/buyback"

    def test_undated_row_does_not_get_a_filing_link(self):
        assert not _edinet_still_serves(None)


class TestWatchingSourceId:
    """A WATCHING row is a standing state, keyed on the company alone -
    keying it on the date emptied the Watching tab at every midnight."""

    def _run(self, as_of):
        """Drive the real function, stubbing only the two inputs a
        fixture cannot reasonably fake: which article counts as a
        genuine revision, and when it was filed."""
        from unittest.mock import patch

        import pipeline.japan_signal_classifier as mod

        article = {
            "url": "irbank-financials://6146/x",
            "title": "Disco (6146): forecast revision",
            "published": "2025-07-01T00:00:00+00:00",
            "metadata": {"code": "6146", "source_category": "jp_forecast"},
        }
        habits = {"6146": {"typical_days_between_revisions": 182,
                           "is_trusted": True, "revisions_per_year": 2.0}}
        with patch.object(mod, "_is_genuine_revision", return_value=True):
            return mod.classify_stale_revision_pattern(
                [article], stored_habits=habits, as_of=as_of,
            )

    def test_same_company_keeps_one_id_across_days(self):
        day1 = self._run(datetime(2026, 10, 1, tzinfo=timezone.utc))
        day2 = self._run(datetime(2026, 10, 2, tzinfo=timezone.utc))
        assert day1 and day2, "fixture should produce an overdue row"
        ids1 = {r["result"]["source_id"] for r in day1}
        ids2 = {r["result"]["source_id"] for r in day2}
        # The id must not move with the date, or the row disappears
        # from the Watching tab every midnight.
        assert ids1 == ids2 == {"japan-stale-revision://6146"}

    def test_the_reading_itself_still_moves_with_the_date(self):
        """The id is stable; the figure it carries is not - that is why
        the insert upserts rather than skipping."""
        day1 = self._run(datetime(2026, 10, 1, tzinfo=timezone.utc))
        day2 = self._run(datetime(2026, 10, 31, tzinfo=timezone.utc))
        d1 = day1[0]["result"]["metadata"]["days_since_last_revision"]
        d2 = day2[0]["result"]["metadata"]["days_since_last_revision"]
        assert d2 == d1 + 30


class TestCheckpointTests:
    """supports/weakens must carry this event's own figure."""

    def test_raise_names_the_revised_forecast(self):
        supports, weakens = _checkpoint_tests(
            "forecast",
            {"operating_profit_pct_change": 13.8, "operating_profit_revised": 198000.0},
            "Q3",
        )
        assert supports == "Q3 results track at or above the raised ¥198bn forecast"
        assert weakens == "Q3 results fall short of ¥198bn, or the raise is cut back"

    def test_cut_names_the_revised_forecast(self):
        supports, weakens = _checkpoint_tests(
            "forecast",
            {"operating_profit_pct_change": -33.3, "operating_profit_revised": 56000.0},
            "Q4",
        )
        assert supports == "Q4 results land at or below the cut ¥56bn forecast"
        assert "too cautious" in weakens

    def test_buyback_names_the_programme_size(self):
        supports, weakens = _checkpoint_tests(
            "buyback", {"buyback_program_limit_shares": 30000000}, "Q3")
        assert supports == "Q3 results report shares repurchased under the 30M programme"
        assert weakens == "Q3 results show little or none of the 30M programme used"

    def test_ownership_names_the_holder_and_stake(self):
        supports, weakens = _checkpoint_tests("ownership", {
            "translated_filer_name": "Sumitomo Mitsui Trust Asset Management Co., Ltd.",
            "holding_pct": 5.94,
        }, "Q4")
        assert supports == (
            "Sumitomo Mitsui Trust AM files a change report raising its 5.9% stake"
        )
        assert weakens == "Sumitomo Mitsui Trust AM's stake falls back below 5%"

    def test_press_already_announced_tests_follow_through(self):
        """Nothing left to confirm, so the checkpoint asks whether it
        turned into orders - not whether the company admits it."""
        supports, weakens = _checkpoint_tests("press", TestPressHeadline.META, "Q4")
        assert supports == "Q4 results cite 12-inch SiC substrate orders or capacity"
        assert weakens == "No mention of 12-inch SiC substrate at Q4 results"

    def test_press_unconfirmed_still_tests_confirmation(self):
        meta = dict(TestPressHeadline.META, unconfirmed=True)
        supports, _ = _checkpoint_tests("press", meta, "Q4")
        assert supports == (
            "Resonac Holdings confirms the 12-inch SiC substrate "
            "in a filing or at Q4 results"
        )

    def test_rows_with_no_specific_figure_send_null(self):
        assert _checkpoint_tests("forecast", {}, "Q3") == (None, None)
        assert _checkpoint_tests("ownership", {}, "Q3") == (None, None)

    @pytest.mark.parametrize("signal_type,meta", [
        ("forecast", {"operating_profit_pct_change": 13.8,
                      "operating_profit_revised": 198000.0}),
        ("buyback", {"buyback_program_limit_shares": 30000000}),
        ("ownership", {"translated_filer_name": "Nomura Securities Co., Ltd.",
                       "holding_pct": 5.3}),
        ("capacity", {}),
        ("disclosure", {}),
        ("missing", {}),
        ("watching", {"company": "Disco"}),
    ])
    def test_every_line_stays_under_ninety_characters(self, signal_type, meta):
        for text in _checkpoint_tests(signal_type, meta, "Q3"):
            if text is not None:
                assert len(text) < 90, text


class TestCompanyProfile:
    """Disclosed customer concentration, and how it reaches the card."""

    def test_disclosed_percentage_is_stored_with_its_period(self):
        from pipeline.japan_companies import company_for
        nvda = next(c for c in company_for("6857")["customers"]
                    if c["ticker"] == "NVDA")
        assert nvda["pct_of_sales"] == 21.6
        assert nvda["period"] == "FY3/26"

    def test_lapsed_disclosure_keeps_the_year_it_was_filed(self):
        """11.0% in FY3/25, below the threshold in FY3/26. The period
        must stay FY3/25 so a consumer can tell it is not current."""
        from pipeline.japan_companies import company_for
        amd = next(c for c in company_for("4062")["customers"]
                   if c["ticker"] == "AMD")
        assert amd["pct_of_sales"] == 11.0
        assert amd["period"] == "FY3/25"

    def test_results_no_longer_carries_connections(self):
        """Dropped as redundant: every field was derivable from the
        customers[] the frontend already fetches from /universe, and
        it was repeated on all 396 signal rows."""
        from pipeline.japan_signal_view import to_jp_signal
        row = {"source_id": "irbank-financials://6857/x", "signal_detection": "signal",
               "signal_score": None, "signal_reason": "r", "published": None,
               "title": "t", "metadata": {"code": "6857", "source_category": "jp_forecast"}}
        assert "connections" not in to_jp_signal(row)

    def test_distributors_are_flagged_so_a_consumer_can_hide_them(self):
        """SUMCO's largest disclosed customer is Sumitomo Corporation at
        27% - a trading house, so its results say nothing about wafer
        demand. The flag is what lets the frontend drop it."""
        from pipeline.japan_companies import company_for
        sumitomo = next(c for c in company_for("3436")["customers"]
                        if c["name"] == "Sumitomo Corporation")
        assert sumitomo["pct_of_sales"] == 27.0
        assert sumitomo["is_distributor"] is True

    def test_valuation_carries_its_own_date_and_staleness(self):
        from datetime import date
        from pipeline.japan_companies import valuation_for
        v = valuation_for("6857")
        assert v["asOf"] == "2026-10-01"
        assert v["isStale"] is False
        assert valuation_for("6857", date(2027, 6, 1))["isStale"] is True

    def test_every_profiled_company_is_in_the_universe(self):
        from pipeline.japan_companies import JAPAN_COMPANIES
        from pipeline.japan_companies import JAPAN_TICKER_UNIVERSE
        codes = {t["code"] for t in JAPAN_TICKER_UNIVERSE}
        assert set(JAPAN_COMPANIES) == codes


class TestMentionedCustomers:
    """Which of a company's own customers an event actually NAMES -
    the Direct/Inferred question, answered by lookup against a known
    candidate set rather than free extraction."""

    def test_english_name_is_found(self):
        from pipeline.japan_companies import mentioned_customers
        got = mentioned_customers("6857", "Advantest wins an order from NVIDIA")
        assert got == [{"name": "Nvidia", "type": "company"}]

    def test_japanese_alias_is_found(self):
        """ホンダ appears in stored text where "Honda" does not, so
        matching the English name alone misses real occurrences."""
        from pipeline.japan_companies import mentioned_customers
        got = mentioned_customers("6723", "ホンダ向けSoCの共同開発を開始")
        assert got == [{"name": "Honda", "type": "company"}]

    def test_a_substring_is_not_a_mention(self):
        """"ASE" sits inside "PHASE" - Latin names need a word
        boundary or every other row matches something."""
        from pipeline.japan_companies import mentioned_customers
        assert mentioned_customers("6315", "entering its final PHASE") == []

    def test_an_ordinary_revision_names_nobody(self):
        from pipeline.japan_companies import mentioned_customers
        assert mentioned_customers(
            "6857", "Advantest raised its full-year operating profit forecast",
        ) == []

    def test_untracked_company_and_empty_text_are_safe(self):
        from pipeline.japan_companies import mentioned_customers
        assert mentioned_customers("9999", "NVIDIA") == []
        assert mentioned_customers("6857", None) == []

    def test_customers_with_no_ticker_are_skipped(self):
        """Toshiba is a real TDK customer but delisted, so a reader has
        nothing to look up - a mention of it is not actionable."""
        from pipeline.japan_companies import mentioned_customers
        assert mentioned_customers("6762", "東芝向けHDDヘッドの出荷") == []

    def test_several_customers_in_one_event(self):
        from pipeline.japan_companies import mentioned_customers
        names = {e["name"] for e in mentioned_customers(
            "4062", "NVIDIA and Intel substrate orders both increased")}
        assert names == {"Nvidia", "Intel"}


class TestSignalImplication:
    """`signal_implication` and its thresholds moved here when the
    summary module was deleted. The progress branch reached a constant
    that did not come across with it, so every progress-type row raised
    NameError and `/japan-signals/results` returned 500 for the whole
    page - one row is enough to fail the list comprehension that shapes
    it. These pin each branch so a move cannot break one silently again.
    """

    def test_progress_ahead_of_elapsed_year_is_positive(self):
        from pipeline.japan_signal_view import signal_implication
        assert signal_implication(
            {"progress_pct": 62.0, "fiscal_year_elapsed_pct": 50.0}) == "Positive"

    def test_progress_behind_elapsed_year_is_negative(self):
        from pipeline.japan_signal_view import signal_implication
        assert signal_implication(
            {"progress_pct": 38.0, "fiscal_year_elapsed_pct": 50.0}) == "Negative"

    def test_progress_inside_the_ordinary_band_is_mixed(self):
        """A quarter never lands exactly on its share of the year; five
        points either side is ordinary, not a signal."""
        from pipeline.japan_signal_view import signal_implication
        assert signal_implication(
            {"progress_pct": 53.0, "fiscal_year_elapsed_pct": 50.0}) == "Mixed"
        assert signal_implication(
            {"progress_pct": 47.0, "fiscal_year_elapsed_pct": 50.0}) == "Mixed"

    def test_margin_guidance_against_prior_year_actual(self):
        from pipeline.japan_signal_view import signal_implication
        assert signal_implication(
            {"margin_revised_pct": 24.0,
             "margin_reference_prior_year_actual_pct": 21.0}) == "Positive"
        assert signal_implication(
            {"margin_revised_pct": 19.0,
             "margin_reference_prior_year_actual_pct": 21.0}) == "Negative"

    def test_industry_yoy_sign(self):
        from pipeline.japan_signal_view import signal_implication
        assert signal_implication({"yoy_pct": 12.5}) == "Positive"
        assert signal_implication({"yoy_pct": -3.0}) == "Negative"

    def test_empty_meta_is_safe(self):
        from pipeline.japan_signal_view import signal_implication
        assert isinstance(signal_implication({}), str)


class TestCardCarriesEntities:
    """`entities` is computed at classification time and stored, but
    `to_jp_signal` rebuilds the card field by field, so a stored column
    reaches the card only if it is named here. It was not: the entity
    work shipped and stayed invisible to the card endpoint, readable
    only on the raw /results rows.
    """

    @staticmethod
    def _row(**over):
        row = {
            "source_id": "irbank-financials://6857/x",
            "signal_detection": "signal", "signal_score": None,
            "signal_reason": "r", "published": None, "title": "t",
            "metadata": {"code": "6857", "source_category": "jp_forecast"},
        }
        row.update(over)
        return row

    def test_stored_entities_reach_the_card(self):
        from pipeline.japan_signal_view import to_jp_signal
        card = to_jp_signal(self._row(
            entities=[{"name": "Nvidia", "type": "company"}]))
        assert card["entities"] == [{"name": "Nvidia", "type": "company"}]

    def test_no_named_customer_is_an_empty_list_not_missing(self):
        """390 of 394 real rows name nobody - a revision states figures
        and mentions no customer. The key must still be present so a
        consumer renders "none named" rather than treating the field as
        absent."""
        from pipeline.japan_signal_view import to_jp_signal
        card = to_jp_signal(self._row(entities=[]))
        assert card["entities"] == []

    def test_row_without_the_column_is_safe(self):
        from pipeline.japan_signal_view import to_jp_signal
        assert to_jp_signal(self._row())["entities"] == []

    def test_null_entities_becomes_empty_list(self):
        from pipeline.japan_signal_view import to_jp_signal
        assert to_jp_signal(self._row(entities=None))["entities"] == []

    def test_several_named_customers_all_carry(self):
        from pipeline.japan_signal_view import to_jp_signal
        card = to_jp_signal(self._row(entities=[
            {"name": "Toyota", "type": "company"},
            {"name": "Honda", "type": "company"},
        ]))
        assert [e["name"] for e in card["entities"]] == ["Toyota", "Honda"]
