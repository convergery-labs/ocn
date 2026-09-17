"""Unit tests for the company cache refresh job (feeds Stage C's Layer 1
name match and Layer 3 category->ticker expansion)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.category_map_refresh import _normalize_companies


def test_company_normalized_with_categories():
    companies = [
        {"ticker": "NVDA", "company_name": "Nvidia", "categories": ["04. Semiconductor Manufacturing"]},
    ]
    result = _normalize_companies(companies)
    assert result == [
        {"ticker": "NVDA", "company_name": "Nvidia", "categories": ["Semiconductor Manufacturing"]},
    ]


def test_ordinal_prefix_is_stripped():
    # Confirmed live: research-universe's GET /companies returns category
    # names with a leading "NN. " ordinal prefix, not the bare names in
    # ALLOWED_CATEGORIES.
    companies = [
        {"ticker": "XYZ", "company_name": "X Corp", "categories": ["19. Applications & Digital Economy"]},
    ]
    result = _normalize_companies(companies)
    assert result[0]["categories"] == ["Applications & Digital Economy"]


def test_multi_category_company_keeps_all_categories():
    companies = [
        {
            "ticker": "NVDA", "company_name": "Nvidia",
            "categories": ["04. Semiconductor Manufacturing", "09. Cloud & Compute Platforms"],
        },
    ]
    result = _normalize_companies(companies)
    assert set(result[0]["categories"]) == {"Semiconductor Manufacturing", "Cloud & Compute Platforms"}


def test_private_ticker_is_excluded():
    companies = [{"ticker": "Private", "company_name": "X", "categories": []}]
    result = _normalize_companies(companies)
    assert result == []


def test_missing_ticker_is_excluded():
    companies = [
        {"ticker": None, "company_name": "X", "categories": []},
        {"company_name": "Y", "categories": []},
    ]
    result = _normalize_companies(companies)
    assert result == []


def test_unrecognized_category_after_prefix_strip_is_dropped():
    companies = [
        {"ticker": "XYZ", "company_name": "X Corp", "categories": ["99. Not A Real Category"]},
    ]
    result = _normalize_companies(companies)
    assert result[0]["categories"] == []


def test_company_with_no_categories_still_kept_for_name_matching():
    # even with zero categories, the company should still be retained -
    # Layer 1's name match doesn't depend on categories being present.
    companies = [{"ticker": "XYZ", "company_name": "X Corp", "categories": []}]
    result = _normalize_companies(companies)
    assert result == [{"ticker": "XYZ", "company_name": "X Corp", "categories": []}]


def test_multiple_companies_all_normalized():
    companies = [
        {"ticker": "NVDA", "company_name": "Nvidia", "categories": ["04. Semiconductor Manufacturing"]},
        {"ticker": "AMD", "company_name": "AMD", "categories": ["04. Semiconductor Manufacturing"]},
    ]
    result = _normalize_companies(companies)
    assert len(result) == 2
    assert {c["ticker"] for c in result} == {"NVDA", "AMD"}
