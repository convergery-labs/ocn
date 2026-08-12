"""SEC EDGAR filing text fetch + results-section extraction + XBRL financial facts.

Filing metadata (ticker, form_type, accession_number, item_codes,
primary_doc_url, ...) is owned entirely by news-retrieval: its poller fetches
from EDGAR daily and stores in DynamoDB (`ocn-sec-filings`), read via
GET /market/sec-filings/{ticker} (see adapters/news_client.get_sec_filings).
signal-detection-agent does not call EDGAR's submissions API itself - only
the functions here remain, since fetching a filing's full body text (and,
for 10-K/10-Q, its structured XBRL facts) is not something news-retrieval
does (it stores metadata + a link only).
"""
from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "OCN SignalDetection kajal.nain@opengrowth.com"
_MIN_INTERVAL = 0.15  # ~6-7 req/sec, under SEC's 10 req/sec guidance
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _rate_sleep(last_call: list[float]) -> None:
    elapsed = time.monotonic() - last_call[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    last_call[0] = time.monotonic()


def fetch_filing_text(primary_doc_url: str, last_call: list[float], *, max_chars: int = 600_000) -> str:
    """Fetch a filing's primary document live and return plain text (HTML stripped).

    Never persisted by the caller - fetched fresh for one classification call.
    Returns "" on any failure.
    """
    if not primary_doc_url:
        return ""
    _rate_sleep(last_call)
    try:
        resp = httpx.get(primary_doc_url, headers={"User-Agent": _USER_AGENT}, timeout=30.0)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("[SEC_EDGAR] filing text fetch failed url=%s error=%s", primary_doc_url, exc)
        return ""

    import html as html_module

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


_RESULTS_MARKERS_PRECISE = [
    "net revenues increased",
    "net revenues decreased",
    "total net revenues increased",
    "total net revenues decreased",
    "net revenue increased",
    "net revenue decreased",
    "total revenues increased",
    "total revenues decreased",
    "revenue increased",
    "revenue decreased",
    "revenues increased",
    "revenues decreased",
    "net loss increased",
    "net loss decreased",
    "net income increased",
    "net income decreased",
    "net sales increased",
    "net sales decreased",
    "sales increased",
    "sales decreased",
    "income increased",
    "income decreased",
]

_RESULTS_MARKERS_GENERIC = [
    re.compile(r"fiscal (?:year )?\d{4} compared to fiscal (?:year )?\d{4}", re.I),
    re.compile(r"(?:year|quarter) ended [a-z]+ \d{1,2},? \d{4},? compared to", re.I),
    re.compile(r"results of operations for (?:the )?(?:fiscal )?(?:year|quarter)", re.I),
    re.compile(r"increased \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"decreased \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"net loss of \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"net income of \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"were \$[\d,.]+ (?:million|billion) in \d{4}, compared to", re.I),
]

_RESULTS_WINDOW_BEFORE = 500
_RESULTS_WINDOW_AFTER = 15_000


def _find_results_window(text: str) -> tuple[int, int, bool]:
    """Locate the results-of-operations window's (start, end) offsets in text.
    Same marker logic as before extract_results_section was split into this
    helper + the note-based extraction below - see that function's docstring
    for why marker coverage (not position filtering) is what matters here.
    """
    low = text.lower()

    precise_positions = [idx for marker in _RESULTS_MARKERS_PRECISE if (idx := low.find(marker)) != -1]
    if precise_positions:
        idx = min(precise_positions)
        start = max(0, idx - _RESULTS_WINDOW_BEFORE)
        return start, idx + _RESULTS_WINDOW_AFTER, True

    generic_positions = [m.start() for pattern in _RESULTS_MARKERS_GENERIC if (m := pattern.search(text))]
    if generic_positions:
        idx = min(generic_positions)
        start = max(0, idx - _RESULTS_WINDOW_BEFORE)
        return start, idx + _RESULTS_WINDOW_AFTER, True

    return 0, _RESULTS_WINDOW_AFTER, False


def extract_results_section(text: str) -> tuple[str, bool]:
    """Extract the quantitative results-of-operations section from 10-K/10-Q text.

    Returns (section_text, found) - found=False means no marker matched and
    the fallback (first max_chars of the raw document) was used; callers
    should treat that case as lower-confidence, since the fallback is likely
    to be XBRL tag metadata or front-matter, not the real section.
    """
    start, end, found = _find_results_window(text)
    return text[start:end], found


# Financial-statement notes carrying qualitative risk content that a fixed
# results-of-operations window misses - confirmed empirically on a real AAPL
# 10-Q: the EU State Aid legal matter (a genuinely material item) lives in
# the "Income Taxes" note at char ~34K, while the results-of-operations
# window (found via revenue-comparison phrasing) sits at ~72K-87K - neither
# a wider nor an earlier-shifted single window covers both, since they are
# in different, non-adjacent notes. Every 10-K/10-Q numbers its financial
# statement notes "Note N - Title" per GAAP disclosure requirements; the
# title wording is standard even though the note NUMBER varies by filer
# (confirmed: AAPL's Contingencies note is Note 10, MSFT's is Note 14) - so
# matching on title text, not number, generalizes across filers.
_QUALITATIVE_NOTE_TITLES = [
    "income taxes",
    "commitments and contingencies",
    "contingencies",
    "legal proceedings",
    "debt",
]
_NOTE_HEADER_PATTERN = re.compile(r"Note\s+\d+\s*[—–-]\s*([A-Za-z][A-Za-z ,]+)")
_QUALITATIVE_NOTE_MAX_CHARS = 6_000  # per note - these are usually a few paragraphs, not tables


def _extract_qualitative_notes(text: str) -> str:
    """Find and return the content of qualitative-risk notes (Income Taxes,
    Contingencies, Debt, ...) by locating "Note N - Title" headers and
    slicing to the next header (or _QUALITATIVE_NOTE_MAX_CHARS, whichever is
    shorter) - a note's real extent, not a guessed fixed window.
    """
    headers = list(_NOTE_HEADER_PATTERN.finditer(text))
    sections: list[str] = []
    for i, match in enumerate(headers):
        title = match.group(1).strip().lower()
        if not any(keyword in title for keyword in _QUALITATIVE_NOTE_TITLES):
            continue
        start = match.start()
        next_start = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        end = min(start + _QUALITATIVE_NOTE_MAX_CHARS, next_start)
        sections.append(text[start:end])
    return "\n\n".join(sections)


def extract_filing_sections(text: str) -> tuple[str, bool]:
    """Extract both the quantitative results-of-operations window AND the
    qualitative risk notes (income taxes, contingencies/legal, debt) from
    10-Q/10-K text, concatenated - replaces sending the full ~100K-500K char
    document while still covering the content a single fixed window misses.

    Returns (combined_text, results_found) - results_found mirrors
    extract_results_section's found flag (whether the numbers narrative was
    located); qualitative notes are additive best-effort and don't affect it,
    since their absence just means this filing didn't discuss those topics,
    not that extraction failed.
    """
    start, end, found = _find_results_window(text)
    results_section = text[start:end]
    qualitative = _extract_qualitative_notes(text)
    if not qualitative:
        return results_section, found
    return results_section + "\n\n--- Other notes (legal/tax/debt) ---\n\n" + qualitative, found


# ---------------------------------------------------------------------------
# XBRL structured financial facts (10-K/10-Q only - 8-K rarely carries them)
# ---------------------------------------------------------------------------

# Each logical field lists fallback tag names in priority order - companies
# tag the same concept differently depending on which XBRL taxonomy version
# they adopted (e.g. pre/post ASC 606 revenue recognition), so a single fixed
# tag name misses real data on some filers. Confirmed empirically: AAPL's
# actual revenue tag for this era is SalesRevenueNet, not Revenues.
_XBRL_FIELD_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense"],
    "dividends_per_share": ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "stock_repurchased": ["PaymentsForRepurchaseOfCommonStock"],
    "repurchase_program_authorized": ["StockRepurchaseProgramAuthorizedAmount1", "StockRepurchaseProgramAuthorizedAmount"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "income_tax_expense": ["IncomeTaxExpenseBenefit"],
    "effective_tax_rate": ["EffectiveIncomeTaxRateContinuingOperations"],
}


def fetch_company_facts(cik: str, last_call: list[float]) -> dict:
    """Fetch the full XBRL companyfacts document for a CIK. Returns {} on failure.

    This is a large (multi-MB, multi-year) document - callers should extract
    what they need via extract_xbrl_facts_for_filing() and discard the rest,
    not re-fetch per filing if classifying several filings for the same
    ticker in one batch (see classify_filings_for_ticker's per-ticker caching
    pattern for company_overview - the same principle applies here).
    """
    _rate_sleep(last_call)
    try:
        resp = httpx.get(
            _COMPANYFACTS_URL.format(cik=cik),
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[SEC_EDGAR] companyfacts fetch failed cik=%s error=%s", cik, exc)
        return {}


def _period_days(entry: dict) -> int:
    """Duration in days of an XBRL fact's reporting period, or 0 if it's a
    point-in-time fact (balance sheet items have no 'start', only 'end').
    """
    if not entry.get("start") or not entry.get("end"):
        return 0
    from datetime import date
    start = date.fromisoformat(entry["start"])
    end = date.fromisoformat(entry["end"])
    return (end - start).days


# Target reporting-period length per form type, for disambiguating candidates
# that share the same accession + end date. Confirmed empirically THIS IS
# FORM-TYPE-DEPENDENT, not "shortest always wins": a 10-Q's own accession
# tags both the single quarter (~91 days) and year-to-date cumulative
# (~182-273 days) under the same end date - want the quarter, the shorter
# one. A 10-K's own accession ALSO tags both the full fiscal year (~365
# days) AND just Q4 alone (~91 days) under the SAME end date (confirmed on a
# real AbbVie 10-K: EarningsPerShareDiluted tagged both $6.45/year and
# $2.26/Q4-only under one accession + end=2021-12-31) - here the shorter
# period is the WRONG one; a 10-K's "current results" means the full year.
# Point-in-time facts (period_days=0, e.g. balance sheet items) have no
# competing candidate at the same end date regardless of form type, so the
# target is irrelevant for those - there is only ever one to pick.
_TARGET_PERIOD_DAYS = {"10-Q": 91, "10-K": 365}


def _find_prior_year_value(
    usgaap: dict, accession_number: str, period_of_report: str, target_days: int,
) -> float | None:
    """Same-period-prior-year revenue, tagged under the SAME accession as the
    current filing (every 10-Q/10-K states its comparison to the prior-year
    period, and XBRL tags both current and comparative figures together).

    Built because relying on text markers to find a filer's revenue
    comparison table is unreliable - confirmed on a real CACI 10-Q where the
    actual "Revenues $1,744,270 ... $1,583,980 ... 10.1%" comparison table
    sat outside the extracted text window entirely, causing both a cheap and
    an expensive model to independently get materiality wrong (one guessed
    "medium" without the real number, one correctly said "insufficient data"
    and defaulted low) - neither had the actual percentage. XBRL's own
    'frame' field (e.g. 'CY2022Q1') explicitly marks these prior-year
    comparative facts, but matching on year-over-year end-date arithmetic
    (not the frame string, whose format isn't fully reliable across filers)
    is more robust: take period_of_report's end date, subtract ~1 year, and
    look for a same-form-type-length entry ending on that date instead.
    """
    from datetime import date, timedelta
    if not period_of_report:
        return None
    try:
        current_end = date.fromisoformat(period_of_report)
    except ValueError:
        return None
    prior_end = current_end - timedelta(days=365)
    # Filings don't always land on the exact same calendar date a year prior.
    # Confirmed empirically this needs to be wider than a few days: AAPL's
    # fiscal year (52/53-week, ending the last Saturday of a month) put the
    # real prior-year comparative 6 days outside an initial +/-4 day window -
    # a leap year alone can shift this by a day, and 52/53-week fiscal
    # calendars can drift further. +/-10 days comfortably covers both
    # without being so wide it risks matching a different, non-comparative
    # period (the next-nearest real candidate is a full quarter away).
    prior_window = {(prior_end + timedelta(days=d)).isoformat() for d in range(-10, 11)}

    for concept in _XBRL_FIELD_CONCEPTS["revenue"]:
        concept_data = usgaap.get(concept)
        if not concept_data:
            continue
        candidates = [
            e for entries in (concept_data.get("units") or {}).values() for e in entries
            if e.get("accn") == accession_number and e.get("end") in prior_window
        ]
        if candidates:
            best = min(candidates, key=lambda e: abs(_period_days(e) - target_days))
            return best["val"]
    return None


def extract_xbrl_facts_for_filing(
    company_facts: dict, accession_number: str, period_of_report: str, form_type: str,
) -> dict[str, float | None]:
    """Filter a companyfacts document down to the exact figures reported under
    one specific filing (by accession_number - XBRL tags every fact with the
    accession of the filing that reported it, so this isolates the current
    filing's own tagged data from other filings' data in the same document).

    One accession_number is not enough by itself, though: a single filing's
    own accession tags MULTIPLE overlapping periods that share the same end
    date - confirmed on two real filings this session: AAPL's Q2 FY2017 10-Q
    tags both the single quarter ($52.9B revenue) and year-to-date six months
    ($131.2B) under one accession + end date; AbbVie's FY2021 10-K tags both
    the full year ($6.45 diluted EPS) and Q4-only ($2.26) under one accession
    + end date. period_of_report filters to entries whose 'end' matches it
    (eliminating prior-year comparatives), and among same-end-date
    candidates, the one whose period length is CLOSEST to this form type's
    expected reporting period (_TARGET_PERIOD_DAYS) wins - not a blanket
    "shortest wins" rule, which is correct for 10-Q but silently picks the
    wrong (Q4-only) figure for 10-K.

    Returns a flat dict of logical field name -> value (None if the filing
    didn't tag that concept under any of its fallback names, or under this
    exact period). Exact numbers from SEC's own structured data - not
    model-extracted, not summarized, so there is no hallucination risk from
    the model's own recall - but this period-selection step is itself a real
    correctness requirement, not a formality; confirmed getting it wrong
    silently produces a plausible-looking but wrong number (Q4 EPS quoted as
    the annual figure), not an obviously-broken one.
    """
    usgaap = (company_facts.get("facts") or {}).get("us-gaap") or {}
    result: dict[str, float | None] = {}
    target_days = _TARGET_PERIOD_DAYS.get(form_type, 365)

    for field, concept_names in _XBRL_FIELD_CONCEPTS.items():
        candidates: list[dict] = []
        for concept in concept_names:
            concept_data = usgaap.get(concept)
            if not concept_data:
                continue
            for entries in (concept_data.get("units") or {}).values():
                candidates.extend(
                    e for e in entries
                    if e.get("accn") == accession_number and e.get("end") == period_of_report
                )
            if candidates:
                break  # this concept name matched - don't also check lower-priority fallbacks

        if candidates:
            best = min(candidates, key=lambda e: abs(_period_days(e) - target_days))
            result[field] = best["val"]
        else:
            result[field] = None

    result["revenue_prior_year"] = _find_prior_year_value(
        usgaap, accession_number, period_of_report, target_days,
    )

    return result
