"""Unit tests for Stage D's pure grading logic (no model call, no I/O)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_stage_d import grade_geopolitical_signal_article


def _grade(**overrides):
    defaults = {
        "url": "https://www.reuters.com/some/story",
        "title": "US imposes new sanctions on Iran",
        "also_reported_by": None,
        "impacted_companies_direct": None,
    }
    defaults.update(overrides)
    return grade_geopolitical_signal_article(**defaults)


def test_all_three_true_grades_top():
    result = _grade(
        title="US sanctions Iran, 20 vessels turned away",
        also_reported_by=["apnews.com"],
    )
    assert result["corroborated"] is True
    assert result["primary_source"] is True
    assert result["specific"] is True
    assert result["grade"] == "TOP"


def test_two_of_three_true_grades_strong():
    # primary_source true (reuters.com), specific true (has digit),
    # corroborated false (no also_reported_by) -> 2 of 3
    result = _grade(title="US sanctions Iran, 20 vessels turned away")
    assert result["corroborated"] is False
    assert result["primary_source"] is True
    assert result["specific"] is True
    assert result["grade"] == "STRONG"


def test_one_true_grades_standard():
    # primary_source true only - no digit, no company match, not corroborated
    result = _grade(title="US sanctions Iran aviation sector")
    assert result["primary_source"] is True
    assert result["corroborated"] is False
    assert result["specific"] is False
    assert result["grade"] == "STANDARD"


def test_zero_true_grades_standard():
    result = _grade(
        url="https://www.some-random-blog.com/story",
        title="US sanctions Iran aviation sector",
    )
    assert result["primary_source"] is False
    assert result["corroborated"] is False
    assert result["specific"] is False
    assert result["grade"] == "STANDARD"


def test_corroboration_requires_allowlisted_domain_not_any_outlet():
    # real data case: also_reported_by full of AP-affiliate local TV
    # stations, none of them on the allowlist - not real corroboration
    result = _grade(
        also_reported_by=["wsbtv.com", "kmbc.com", "wcvb.com", "wdsu.com"],
    )
    assert result["corroborated"] is False


def test_corroboration_true_when_one_entry_is_allowlisted():
    result = _grade(
        also_reported_by=["wsbtv.com", "kmbc.com", "apnews.com"],
    )
    assert result["corroborated"] is True


def test_corroboration_strips_www_prefix():
    result = _grade(also_reported_by=["www.reuters.com"])
    assert result["corroborated"] is True


def test_corroboration_false_on_empty_or_none_also_reported_by():
    assert _grade(also_reported_by=None)["corroborated"] is False
    assert _grade(also_reported_by=[])["corroborated"] is False


def test_primary_source_true_for_allowlisted_domain():
    result = _grade(url="https://www.bloomberg.com/news/articles/x")
    assert result["primary_source"] is True


def test_primary_source_false_for_non_allowlisted_domain():
    result = _grade(url="https://www.some-random-blog.com/story")
    assert result["primary_source"] is False


def test_primary_source_strips_www_and_matches_subdomain_exactly():
    # matches Stage A's own _extract_domain rule - en.interfax.com.ua is
    # its own listed entry, not derived by suffix-matching interfax.com.ua
    result = _grade(url="https://en.interfax.com.ua/news/general/123.html")
    assert result["primary_source"] is True


def test_specific_true_when_title_has_digit():
    result = _grade(title="Trump hits Canada with 50% tariffs", also_reported_by=None)
    assert result["specific"] is True


def test_specific_true_when_direct_company_match_present_even_without_digit():
    result = _grade(
        title="US sanctions Iran aviation sector",
        impacted_companies_direct=["NVDA"],
    )
    assert result["specific"] is True


def test_specific_false_when_no_digit_and_no_company_match():
    result = _grade(title="US sanctions Iran aviation sector")
    assert result["specific"] is False


def test_empty_impacted_companies_direct_list_does_not_count_as_specific():
    result = _grade(
        title="US sanctions Iran aviation sector",
        impacted_companies_direct=[],
    )
    assert result["specific"] is False
