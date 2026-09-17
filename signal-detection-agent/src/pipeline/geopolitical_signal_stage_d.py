"""Stage D: free quality grading for geopolitical_signal rows Stage C has
already tagged (signal_detection='signal').

No model call anywhere in this module - every check is a deterministic
lookup, same free-checks philosophy as Stage A. Stage D answers a
different question than Stage C: Stage C says "who is this relevant to",
Stage D says "how much should a reader trust this specific item" - the
grade this produces is what would ultimately decide ordering in a digest
(TOP items first), not whether an item is included at all.

Three independent checks, each true/false:
  - corroborated: at least one other outlet (news-retrieval's
    metadata.also_reported_by on the source article) is itself a
    wire/paper-of-record on Stage A's own domain allowlist - not just any
    also_reported_by entry, since real data shows that field can be
    entirely local TV affiliates re-syndicating the same AP wire copy
    (confirmed live: article 16514 had 25 also_reported_by entries, all
    ABC/NBC local affiliates carrying one AP story - none of that is
    independent corroboration).
  - primary_source: the article's own domain is on Stage A's allowlist.
    Expected to be true for nearly every row reaching Stage D, since
    Stage A already only lets allowlisted-domain articles through in the
    first place - this check exists for completeness/documentation, not
    because it meaningfully differentiates rows in practice.
  - specific: the headline itself contains a digit (a concrete number -
    percentage, dollar amount, count, etc), OR Stage C's Layer 1 found a
    direct company-name match in the headline (impacted_companies_direct
    non-empty). Either is evidence the story is about something concrete
    rather than a vague, unquantified claim.

Grade: TOP (all 3 true), STRONG (exactly 2 true), STANDARD (0 or 1 true).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from pipeline.geopolitical_signal_classifier import ALLOWED_DOMAINS

_DIGIT_RE = re.compile(r"\d")


def _extract_domain(url: str | None) -> str:
    """Same domain-derivation rule as Stage A's _extract_domain - strip
    "www.", keep any other subdomain as-is (e.g. en.interfax.com.ua stays
    its own full value, matching how ALLOWED_DOMAINS itself lists it).
    """
    host = urlparse(url or "").hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[len("www."):]
    return host


def _is_corroborated(also_reported_by: list[str] | None) -> bool:
    """True if at least one also_reported_by entry is itself a domain on
    Stage A's allowlist - a real second wire/paper-of-record covering the
    same story, not just any syndicating outlet.

    also_reported_by entries are recorded as news-retrieval saw them
    (domain or source string, not normalized the same way _extract_domain
    normalizes a URL) - checked with the same "www." stripping so
    "www.reuters.com" and "reuters.com" both match.
    """
    if not also_reported_by:
        return False
    for entry in also_reported_by:
        domain = (entry or "").strip().lower()
        if domain.startswith("www."):
            domain = domain[len("www."):]
        if domain in ALLOWED_DOMAINS:
            return True
    return False


def _is_specific(title: str, impacted_companies_direct: list[str] | None) -> bool:
    return bool(_DIGIT_RE.search(title or "")) or bool(impacted_companies_direct)


def grade_geopolitical_signal_article(
    *,
    url: str | None,
    title: str | None,
    also_reported_by: list[str] | None,
    impacted_companies_direct: list[str] | None,
) -> dict[str, Any]:
    """Return {grade, corroborated, primary_source, specific} for one
    Stage-C-tagged article. Pure/free - no model call, no I/O; callers
    fetch also_reported_by from news-retrieval before calling this.
    """
    corroborated = _is_corroborated(also_reported_by)
    primary_source = _extract_domain(url) in ALLOWED_DOMAINS
    specific = _is_specific(title or "", impacted_companies_direct)

    true_count = sum((corroborated, primary_source, specific))
    if true_count == 3:
        grade = "TOP"
    elif true_count == 2:
        grade = "STRONG"
    else:
        grade = "STANDARD"

    return {
        "grade": grade,
        "corroborated": corroborated,
        "primary_source": primary_source,
        "specific": specific,
    }
