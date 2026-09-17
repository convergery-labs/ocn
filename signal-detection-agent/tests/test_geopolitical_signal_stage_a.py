"""Unit tests for Stage A (free rule-based filtering) of the
geopolitical_signal pipeline."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_classifier import classify_geopolitical_signal_stage_a


def _article(**overrides):
    base = {
        "id": 1,
        "title": "Iran closes the Strait of Hormuz",
        "source": "Reuters",
        "url": "https://www.reuters.com/x",
        "published": "2026-09-08T06:40:00+00:00",
        "metadata": {"language": "English", "sourcecountry": "US"},
    }
    base.update(overrides)
    return base


def test_non_english_is_dropped():
    result = classify_geopolitical_signal_stage_a(
        _article(metadata={"language": "French"}),
    )
    assert result == {"outcome": "DROPPED", "drop_reason": "non_english"}


def test_untrusted_domain_is_dropped():
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://orissapost.com/x"),
    )
    assert result == {"outcome": "DROPPED", "drop_reason": "domain_not_allowed"}


def test_domain_check_uses_url_not_source():
    # Confirmed live: article["source"] can be a display name ("Reuters"),
    # not a domain at all - the domain check must be driven by url, not
    # source, or real Reuters/Bloomberg articles get silently dropped.
    result = classify_geopolitical_signal_stage_a(
        _article(
            source="Reuters",
            url="https://www.reuters.com/business/aerospace-defense/x",
            title="Austria breaks up sanctions evasion scheme",
        ),
    )
    assert result["outcome"] != "DROPPED"


def test_native_script_source_with_trusted_url_is_not_dropped():
    # Confirmed live: militarnyi.com's source field is "Мілітарний"
    # (Ukrainian, non-Latin) - must not affect the url-based domain check.
    result = classify_geopolitical_signal_stage_a(
        _article(
            source="Мілітарний",
            url="https://militarnyi.com/en/news/canada-sanctions-streit-group/",
            title="Canada Sanctions Streit Group Over Armored Vehicle Supplies",
        ),
    )
    assert result["outcome"] != "DROPPED"


def test_subdomain_must_be_explicitly_allowlisted():
    # Confirmed live: en.interfax.com.ua is the real observed subdomain,
    # distinct from bare interfax.com.ua - both are allowlisted explicitly,
    # not via suffix matching.
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://en.interfax.com.ua/news/general/x.html"),
    )
    assert result["outcome"] != "DROPPED"


def test_unlisted_subdomain_of_an_allowed_domain_is_still_dropped():
    # A subdomain NOT explicitly listed should not silently match via
    # substring/suffix logic - domain matching is exact-value only.
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://sports.reuters.com/x"),
    )
    assert result == {"outcome": "DROPPED", "drop_reason": "domain_not_allowed"}


def test_www_prefix_is_stripped():
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://www.reuters.com/x", title="Iran seizes a tanker"),
    )
    assert result["outcome"] != "DROPPED"


def test_bare_domain_without_www_matches_too():
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://reuters.com/x", title="Iran seizes a tanker"),
    )
    assert result["outcome"] != "DROPPED"


def test_talk_verb_is_weak():
    result = classify_geopolitical_signal_stage_a(
        _article(title="Iran warns it may close the Strait of Hormuz"),
    )
    assert result == {"outcome": "WEAK"}


def test_talk_verb_case_insensitive():
    result = classify_geopolitical_signal_stage_a(
        _article(title="Iran WARNS it may close the Strait of Hormuz"),
    )
    assert result == {"outcome": "WEAK"}


def test_action_verb_is_waiting():
    result = classify_geopolitical_signal_stage_a(
        _article(title="Iran closes the Strait of Hormuz"),
    )
    assert result == {"outcome": "WAITING"}


def test_ambiguous_title_is_waiting():
    result = classify_geopolitical_signal_stage_a(
        _article(title="China conducts live-fire drills encircling Taiwan"),
    )
    assert result == {"outcome": "WAITING"}


def test_language_check_runs_before_domain_check():
    # untrusted domain AND non-English - non_english should win (rule order)
    result = classify_geopolitical_signal_stage_a(
        _article(url="https://orissapost.com/x", metadata={"language": "French"}),
    )
    assert result == {"outcome": "DROPPED", "drop_reason": "non_english"}


def test_missing_language_metadata_does_not_drop():
    # fail-open: no language field at all should not be treated as non-English
    result = classify_geopolitical_signal_stage_a(
        _article(metadata={}),
    )
    assert result["outcome"] != "DROPPED"


def test_missing_url_is_dropped_as_domain_not_allowed():
    # no url means no domain can be derived - fails the allowlist check
    # rather than raising, same as any other unrecognized domain.
    result = classify_geopolitical_signal_stage_a(
        _article(url=""),
    )
    assert result == {"outcome": "DROPPED", "drop_reason": "domain_not_allowed"}


def test_spec_worked_examples_reuters_export_controls():
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="US announces new export controls on chipmaking equipment to China",
            url="https://www.reuters.com/technology/x",
        ),
    )
    assert result == {"outcome": "WAITING"}


def test_spec_worked_example_analyst_opinion_is_ambiguous_not_talk():
    # "Analysts say tensions could push oil to $100" - "could" is a talk verb
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="Analysts say tensions could push oil to $100",
            url="https://www.reuters.com/markets/x",
        ),
    )
    assert result == {"outcome": "WEAK"}


def test_federal_register_trade_keyword_title_is_high_without_stage_b():
    # Confirmed live: this exact real headline (a real presidential
    # proclamation restricting polysilicon imports) reached Stage B (no
    # talk-verb match) and was classified WEAK there anyway - the
    # bureaucratic title alone doesn't state whether the measure is
    # completed, and federalregister.gov articles have no body text to
    # give Stage B more context. A Federal Register notice IS the
    # official record of an already-enacted action, so this is decided
    # for free in Stage A instead of asking Stage B to judge intent from
    # an information-poor title.
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="Adjusting Imports of Polysilicon and Its Derivatives Into the United States",
            url="https://www.federalregister.gov/documents/2026/08/11/x",
        ),
    )
    assert result == {"outcome": "HIGH"}


def test_federal_register_sanctions_keyword_is_high():
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="Continuing Sanctions With Respect to Specified Persons",
            url="https://www.federalregister.gov/documents/2026/08/11/y",
        ),
    )
    assert result == {"outcome": "HIGH"}


def test_federal_register_without_trade_keyword_falls_through_to_normal_rules():
    # no trade/sanctions keyword in the title - normal talk/action-verb
    # rules still apply, not an automatic HIGH just for being this domain
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="National Purple Heart Day, 2026",
            url="https://www.federalregister.gov/documents/2026/08/11/z",
        ),
    )
    assert result == {"outcome": "WAITING"}


def test_trade_keyword_on_a_non_federal_register_domain_is_not_auto_high():
    # the rule is scoped to federalregister.gov specifically - a regular
    # news article using the word "tariff" must still go through the
    # normal talk/action-verb path, not bypass Stage B
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="Tariff talks continue between US and Canada",
            url="https://www.reuters.com/markets/x",
        ),
    )
    assert result == {"outcome": "WAITING"}


def test_federal_register_action_notice_check_is_case_insensitive():
    result = classify_geopolitical_signal_stage_a(
        _article(
            title="ADJUSTING TARIFF RATES FOR CERTAIN GOODS",
            url="https://www.federalregister.gov/documents/2026/08/11/w",
        ),
    )
    assert result == {"outcome": "HIGH"}
