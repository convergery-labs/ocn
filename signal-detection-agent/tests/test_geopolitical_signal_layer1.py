"""Unit tests for Stage C, Layer 1 (direct company-name match)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_layer1 import find_direct_company_matches


def _companies(*pairs):
    # helper: [(name, ticker), ...] -> list[dict], sorted longest-name-first
    # like get_companies_for_name_matching does.
    items = [{"company_name": n, "ticker": t} for n, t in pairs]
    return sorted(items, key=lambda c: len(c["company_name"]), reverse=True)


def test_exact_company_name_match():
    result = find_direct_company_matches(
        "US restricts Nvidia AI chip sales to China",
        _companies(("Nvidia", "NVDA")),
    )
    assert result == ["NVDA"]


def test_no_match_returns_empty():
    result = find_direct_company_matches(
        "China conducts live-fire drills encircling Taiwan",
        _companies(("Nvidia", "NVDA")),
    )
    assert result == []


def test_case_insensitive_match():
    result = find_direct_company_matches(
        "NVIDIA faces new export restrictions",
        _companies(("Nvidia", "NVDA")),
    )
    assert result == ["NVDA"]


def test_word_boundary_avoids_false_positive_on_substring():
    # "Intel" should not match inside "intelligence"
    result = find_direct_company_matches(
        "US intelligence agencies warn of new threats",
        _companies(("Intel", "INTC")),
    )
    assert result == []


def test_short_common_word_company_name_is_never_matched():
    # a company literally named "US Steel" - "US" alone should not create
    # false-positive matches on every headline mentioning the country
    result = find_direct_company_matches(
        "US imposes new tariffs on Chinese steel",
        _companies(("US", "USX")),  # too short, below _MIN_NAME_LENGTH
    )
    assert result == []


def test_longest_name_preferred_when_names_overlap():
    # "Union Pacific" should match on its own, not accidentally also
    # register a shorter unrelated company contained within another word
    result = find_direct_company_matches(
        "Union Pacific announces new rail routes",
        _companies(("Union Pacific", "UNP"), ("Union", "UNIO")),
    )
    assert "UNP" in result


def test_multiple_distinct_companies_all_matched():
    result = find_direct_company_matches(
        "Nvidia and Applied Materials both hit by new export controls",
        _companies(("Nvidia", "NVDA"), ("Applied Materials", "AMAT")),
    )
    assert set(result) == {"NVDA", "AMAT"}


def test_short_ticker_style_name_below_threshold_is_not_matched():
    # a bare 3-letter name like "AMD" is below _MIN_NAME_LENGTH - a real,
    # known limitation (documented in geopolitical_signal_layer1.py) since
    # a length-based rule alone can't tell a real short company name apart
    # from an ambiguous common word/acronym.
    result = find_direct_company_matches(
        "AMD unveils new chip architecture",
        _companies(("AMD", "AMDX")),
    )
    assert result == []


def test_same_ticker_not_duplicated_across_naming_variants():
    result = find_direct_company_matches(
        "Nvidia Corporation faces new Nvidia export restrictions",
        _companies(("Nvidia Corporation", "NVDA"), ("Nvidia", "NVDA")),
    )
    assert result.count("NVDA") == 1


def test_empty_title_returns_empty():
    result = find_direct_company_matches("", _companies(("Nvidia", "NVDA")))
    assert result == []


def test_empty_company_list_returns_empty():
    result = find_direct_company_matches("Nvidia faces new restrictions", [])
    assert result == []


def test_spec_worked_example_nvidia_restrictions():
    result = find_direct_company_matches(
        "US restricts Nvidia AI chip sales to China",
        _companies(("Nvidia", "NVDA"), ("Applied Materials", "AMAT")),
    )
    assert result == ["NVDA"]


def test_legal_suffix_is_stripped_for_matching():
    # Confirmed live: 30% of real cached company names carry a legal
    # suffix ("Advanced Micro Devices, INC") that never appears verbatim
    # in a real headline - without stripping it, this company would never
    # match any real headline.
    result = find_direct_company_matches(
        "Advanced Micro Devices announces new chip architecture",
        _companies(("Advanced Micro Devices, INC", "AMDX")),
    )
    assert result == ["AMDX"]


def test_corporation_suffix_is_stripped():
    result = find_direct_company_matches(
        "Edwards Lifesciences faces new export restrictions",
        _companies(("Edwards Lifesciences Corporation", "EW")),
    )
    assert result == ["EW"]


def test_stacked_legal_suffixes_are_all_stripped():
    # "CommScope Holding Company Inc" - two suffix words stacked
    result = find_direct_company_matches(
        "CommScope Holding faces new tariffs",
        _companies(("CommScope Holding Company Inc", "COMM")),
    )
    assert result == ["COMM"]


def test_public_limited_company_suffix_is_stripped():
    result = find_direct_company_matches(
        "Trane Technologies announces expansion",
        _companies(("Trane Technologies Public Limited Company", "TT")),
    )
    assert result == ["TT"]
