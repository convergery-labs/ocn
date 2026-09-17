"""Stage C, Layer 1: free, direct company-name match against a headline.

Word-boundary matching, not naive substring - a naive `name in title`
check produces real false positives on short/common company names (e.g.
a company literally named "US Steel" would match almost any headline
mentioning "US"; "Intel" would match the word "intel" inside
"intelligence agencies"). Layer 1's match is kept "regardless of what the
model returns" (per the spec), so a bad match here is unusually sticky -
worth the extra care a naive substring check doesn't give.

Company names are checked longest-first (get_companies_for_name_matching
already returns them in that order) so a specific, longer name is matched
before a shorter name that might accidentally be a substring/prefix of it,
and each ticker is only ever returned once even if multiple naming
variants happened to match.
"""
from __future__ import annotations

import re

# Confirmed live against the real cached company data (research-universe,
# 706 US-listed companies): 209 of 706 (30%) have a legal-suffix name
# ("Advanced Micro Devices, INC", "Edwards Lifesciences Corporation") that
# essentially never appears verbatim in a real news headline - matching on
# the raw stored name would silently fail to match roughly a third of the
# universe. Stripped from the SEARCH PATTERN only, not from the stored
# company_name itself (still needed as-is for any display/attribution use).
_LEGAL_SUFFIX_RE = re.compile(
    r",?\s+(Inc|Incorporated|Corp|Corporation|Ltd|Limited|LLC|Co|Company|"
    r"Group|Holdings?|plc|Public Limited Company|SA|AG|NV|SE)\.?\s*$",
    re.IGNORECASE,
)


def _strip_legal_suffix(company_name: str) -> str:
    # applied repeatedly - some names stack more than one suffix word
    # ("CommScope Holding Company Inc" -> strip "Inc" -> strip "Company" ->
    # "CommScope Holding")
    previous = None
    name = company_name
    while name != previous:
        previous = name
        name = _LEGAL_SUFFIX_RE.sub("", name).strip()
    return name


# Company names below this length are excluded from matching entirely.
# Considered lowering to 3 to catch real short names like "AMD"/"IBM", but
# rejected: word-boundary matching alone can't distinguish a short company
# name used AS a company reference from the same word used in its ordinary
# English sense - a company literally named "ARM" would then match every
# headline using "arm" as a verb/noun, which is a worse failure mode than
# missing a genuine short-name company here. Short-named companies are
# still expected to surface via Stage C's Layer 2 model call, which has
# real sentence context, not just a string-length heuristic - this
# function accepting the miss for those names is a deliberate, known
# tradeoff, not an oversight.
_MIN_NAME_LENGTH = 4


def _build_pattern(company_name: str) -> re.Pattern[str] | None:
    name = _strip_legal_suffix(company_name.strip())
    if len(name) < _MIN_NAME_LENGTH:
        return None
    return re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)


def find_direct_company_matches(
    title: str, companies: list[dict],
) -> list[str]:
    """Return tickers of companies whose name appears in the headline as a
    whole word/phrase (word-boundary match, case-insensitive).

    ``companies`` must already be ordered longest-name-first (see
    get_companies_for_name_matching) - this function does not re-sort.
    """
    if not title:
        return []
    matched: list[str] = []
    seen_tickers: set[str] = set()
    for company in companies:
        ticker = company["ticker"]
        if ticker in seen_tickers:
            continue
        pattern = _build_pattern(company["company_name"])
        if pattern is not None and pattern.search(title):
            matched.append(ticker)
            seen_tickers.add(ticker)
    return matched
