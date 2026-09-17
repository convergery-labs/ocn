"""Stage A: free, rule-based noise removal for geopolitical_news articles
(source_type='geopolitical_signal' in agent_classifications).

No model call anywhere in this module - every rule here is a deterministic
lookup/keyword check, applied in the order specified by the spec's Stage A
section, so 80-90% of daily volume is filtered out before Stage B's first
AI call. Same-story cross-outlet dedup is NOT done here - it's handled
upstream in news-retrieval's _dedup_by_title_similarity_for_domain (see
pipeline.py's _TITLE_DEDUP_DOMAINS), so a duplicate never reaches this
module as a separate article to begin with.

Each article gets exactly one outcome: DROPPED (with a reason), WEAK, or
WAITING (a survivor held for Stage B) - written by
insert_geopolitical_signal_classification via
_GEOPOLITICAL_SIGNAL_STAGE_A_MAP in models/jobs.py. An article whose
article_id already has a row is skipped entirely by the caller before this
module ever runs (see get_existing_geopolitical_signal_article_ids).
"""
from __future__ import annotations

from urllib.parse import urlparse

# Wire services and papers of record, plus official US government domains.
# Geopolitics is the worst news category for junk/propaganda outlets - this
# allowlist is the main defence (spec's own framing). Kept intentionally
# narrow; extend only with sources of the same tier, not general news sites.
ALLOWED_DOMAINS: frozenset[str] = frozenset({
    # spec-named wire services / papers of record
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "aljazeera.com",
    "asia.nikkei.com",
    # additional wire services / papers of record - fill geographic gaps
    # the spec's 7 don't cover (global wire, Japan/Asia, Germany/Europe)
    "afp.com",
    "upi.com",
    "nhk.or.jp",
    "dw.com",
    "theguardian.com",
    "economist.com",
    # official US government domains - GDELT/Google News surface press
    # releases and notices from these directly
    "federalregister.gov",
    "whitehouse.gov",
    "state.gov",
    "treasury.gov",
    "commerce.gov",
    "defense.gov",
    # added after reviewing real Stage A output against a local GDELT
    # fetch (2026-08-10 to 2026-08-17, 6322 articles): these three were
    # confirmed responsible for real HIGH-candidate stories being dropped
    # as domain_not_allowed - e.g. "Canada Sanctions Streit Group Over
    # Armored Vehicle Supplies to Russia" (militarnyi.com), "AFU: Enemy
    # attacks Ukraine with Zirkon, Iskander, drone missiles" (interfax.com.ua)
    # - specialized defense/regional-conflict papers of record, not the
    # general-wire-service tier above, but real enough to add narrowly
    # rather than broadening the whole list speculatively.
    "militarnyi.com",
    "kyivpost.com",
    "interfax.com.ua",
    "en.interfax.com.ua",  # real GDELT data observed this exact subdomain,
                            # not bare interfax.com.ua - both listed rather
                            # than relying on suffix matching (see _extract_
                            # domain's docstring)
    # second review pass, same fetch: two more regional wire services
    # confirmed responsible for real missed sanctions/trade stories -
    # armenpress.am (Armenia's state wire, "Iran slams U.S. sanctions
    # policy... after Bessent says Iran is being 'suffocated'"),
    # newsukraine.rbc.ua (RBC-Ukraine, "US sanctions against Russia bill
    # moves to Congress"). Most of the rest of this pass's dropped sample
    # (aggregator sites republishing wire copy, off-topic keyword
    # coincidences, state propaganda outlets) was correctly excluded -
    # not added just because a headline contained a relevant keyword.
    "armenpress.am",
    "newsukraine.rbc.ua",
    # third review pass, fresh independent fetch (2026-09-09, run 50, 797
    # articles - separate from the Aug 10-17 sample above): aa.com.tr
    # (Anadolu Agency, Turkey's state wire service, appeared 3x for real
    # sanctions/trade stories in one small sample), france24.com (France's
    # international public broadcaster, same tier as dw.com/nhk.or.jp
    # already listed), haaretz.com (major Israeli paper of record, relevant
    # given Middle East coverage is a major theme in this feed).
    "aa.com.tr",
    "france24.com",
    "haaretz.com",
})

# Talk verbs: the headline is reporting rhetoric, not a completed/announced
# action. Matched against the title case-insensitively. Spec's own list,
# used as-is for v1 - tune later against real headlines, not more guessing
# upfront.
_TALK_VERBS: frozenset[str] = frozenset({
    "warns", "urges", "vows", "calls for", "may", "could",
    "expected to", "slams", "condemns",
})

# Action verbs: the headline is reporting a completed/announced action.
# A match here (or no match from either list - ambiguous) both continue to
# Stage B; only a talk-verb match short-circuits to WEAK for free. This set
# exists mainly for documentation/tuning visibility - it does not gate
# anything talk verbs don't already gate.
_ACTION_VERBS: frozenset[str] = frozenset({
    "strikes", "seizes", "bans", "cuts", "halts", "closes",
    "sanctions", "imposes", "extends",
})

# federalregister.gov notice titles use bureaucratic phrasing ("Adjusting
# Imports of X", "Continuation of X Assistance") that news-style talk/
# action-verb keywords don't match, and no body text is fetched for this
# source (confirmed live: article 11551's body is NULL) - so unlike a
# regular news headline, Stage B has only the bureaucratic title to judge
# from, with no fallback context. Confirmed live: even with an improved
# Stage B prompt, "Adjusting Imports of Polysilicon and Its Derivatives
# Into the United States" (a real presidential proclamation restricting
# polysilicon imports - HIGH-eligible under the spec's own trade-access
# rule) still classified WEAK, because the title alone doesn't state
# whether the measure is completed or what it does.
#
# A Federal Register notice is, by definition, the official record of an
# agency/presidential action - not a proposal or talk (unlike a news
# article, which can report on something not yet decided) - so a title
# containing one of these trade/sanctions/supply terms is treated as
# reporting a real action already, skipping Stage B's talk/action-verb
# ambiguity on an information-poor title.
_FEDERAL_REGISTER_ACTION_KEYWORDS: frozenset[str] = frozenset({
    "tariff", "import", "export control", "sanction", "embargo",
    "entity list", "denied persons", "trade restriction", "quota",
})


def _is_federal_register_action_notice(title: str, domain: str) -> bool:
    if domain != "federalregister.gov":
        return False
    lowered = title.lower()
    return any(keyword in lowered for keyword in _FEDERAL_REGISTER_ACTION_KEYWORDS)


def _matches_any(title: str, keywords: frozenset[str]) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in keywords)


def _extract_domain(article: dict) -> str:
    """Return the registrable domain to check against ALLOWED_DOMAINS.

    Confirmed live (2026-08-10 to 2026-08-17 GDELT fetch, 6322 articles)
    that article["source"] is NOT reliably a domain - depending on which
    fetcher populated it, it can be a bare domain (bnnbloomberg.ca), a
    subdomain-prefixed domain (en.interfax.com.ua), an English display name
    ("Reuters", "Bloomberg" - no domain at all), or a native-script display
    name ("Мілітарний", "Українська правда"). Trusting source directly
    silently dropped 4 real Reuters/Bloomberg articles in that same fetch.
    article["url"] was confirmed well-formed in every case in that sample,
    so the domain is derived from url instead - source is no longer read
    for this check.

    "www." is stripped so both "reuters.com" and "www.reuters.com" match a
    plain "reuters.com" allowlist entry; a subdomain like "en.interfax.com.ua"
    is matched against the allowlist as its own full value (see
    ALLOWED_DOMAINS's "interfax.com.ua" being insufficient for this exact
    case - the entry itself must include the subdomain that's actually
    observed, same as the existing "asia.nikkei.com" entry already does).
    """
    url = article.get("url") or ""
    host = urlparse(url).hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[len("www."):]
    return host


def classify_geopolitical_signal_stage_a(article: dict) -> dict:
    """Apply Stage A's free rules, in order, to one article. Returns a dict
    with at least an "outcome" key (DROPPED/WEAK/WAITING) and, for DROPPED,
    a "drop_reason" key - the shape insert_geopolitical_signal_classification
    expects as its ``result`` argument.

    Caller is responsible for Stage A rule 1 ("already classified: skip") -
    that's a database check (get_existing_geopolitical_signal_article_ids),
    not something this function can determine from one article in isolation.
    """
    language = (article.get("metadata") or {}).get("language")
    if language and language.lower() != "english":
        return {"outcome": "DROPPED", "drop_reason": "non_english"}

    domain = _extract_domain(article)
    if domain not in ALLOWED_DOMAINS:
        return {"outcome": "DROPPED", "drop_reason": "domain_not_allowed"}

    title = article.get("title") or ""

    # Confirmed live: a Federal Register notice with a trade/sanctions
    # keyword in the title still reached Stage B (no talk-verb match) and
    # was classified WEAK there anyway, because the bureaucratic title
    # alone ("Adjusting Imports of Polysilicon...") doesn't state whether
    # the measure is completed - and no body text exists for this source
    # to give Stage B more context. Skip Stage B's ambiguity entirely: a
    # Federal Register notice IS the official record of an already-enacted
    # action (never a proposal, unlike a news article), so this is free
    # and more reliable than asking a model to judge intent from an
    # information-poor title.
    if _is_federal_register_action_notice(title, domain):
        return {"outcome": "HIGH"}

    if _matches_any(title, _TALK_VERBS):
        return {"outcome": "WEAK"}

    # Action-verb match or genuinely ambiguous (no match either way) both
    # continue to Stage B - the spec treats these identically.
    return {"outcome": "WAITING"}
