"""SEC EDGAR filing fetch helpers: ticker→CIK mapping + submissions lookup."""
import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"

_USER_AGENT = "OCN SignalDetection kajal.nain@opengrowth.com"
_MIN_INTERVAL = 0.15  # ~6-7 req/sec, under SEC's 10 req/sec guidance

# 6-K/40-F/20-F are foreign private issuers' equivalents of 8-K/10-K
# (40-F: Canadian MJDS annual report, 20-F: other-foreign-issuer annual
# report, 6-K: current report) - added after confirming ~12% of the
# tracked ticker universe (81/662, including TSM, BABA, ARM, SAP) files
# ONLY these forms and never 8-K/10-Q/10-K, so was previously getting zero
# SEC filing coverage. Deliberately NOT widened further (e.g. to remove
# the filter entirely) - EDGAR returns many purely administrative forms
# per company (SC 13G, CORRESP, F-X, UPLOAD, S-8 POS, ...) with no
# narrative content to summarize; this allowlist stays scoped to forms
# confirmed (empirically, on real AEM/TSM filings) to carry real
# financial/business narrative.
_FORM_TYPES = {"8-K", "10-Q", "10-K", "6-K", "40-F", "20-F"}

_cik_map_cache: dict[str, str] | None = None


def _rate_sleep(last_call: list[float]) -> None:
    elapsed = time.monotonic() - last_call[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    last_call[0] = time.monotonic()


def _load_cik_map() -> dict[str, str]:
    """Fetch and cache the EDGAR ticker→CIK mapping (process lifetime)."""
    global _cik_map_cache
    if _cik_map_cache is not None:
        return _cik_map_cache

    try:
        resp = httpx.get(_TICKERS_URL, headers={"User-Agent": _USER_AGENT}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        _cik_map_cache = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in data.values()
        }
        logger.info("[SEC_EDGAR] loaded CIK map entries=%d", len(_cik_map_cache))
    except Exception as exc:
        logger.warning("[SEC_EDGAR] failed to load ticker→CIK map: %s", exc)
        _cik_map_cache = {}
    return _cik_map_cache


def _fetch_submissions(cik: str, last_call: list[float]) -> dict:
    _rate_sleep(last_call)
    try:
        resp = httpx.get(
            _SUBMISSIONS_URL.format(cik=cik),
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[SEC_EDGAR] submissions fetch failed cik=%s error=%s", cik, exc)
        return {}


def fetch_recent_filings(ticker: str, last_call: list[float]) -> list[dict]:
    """Return recent 8-K/10-Q/10-K filings for a ticker.

    Each item: ticker, cik, form_type, filed_at, accepted_at, period_of_report,
    accession_number, primary_doc_url, item_codes (list[str], only populated
    for 8-K; [] for 10-Q/10-K), filer_category.

    cik, accepted_at, period_of_report, and filer_category all come from the
    same submissions.json call already made here - no new fetch. accepted_at
    (SEC's acceptanceDateTime) is distinct from filed_at (filingDate) and is
    needed to detect same-day-as-an-earlier-release filings. filer_category
    (SEC's own filer-size tier, e.g. "Large accelerated filer") is a free,
    always-available proxy for company scale until real revenue/market-cap
    data is wired in from another source.

    Returns [] if the ticker has no known CIK or the fetch fails.
    """
    cik_map = _load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        logger.warning("[SEC_EDGAR] no CIK found for ticker=%s", ticker)
        return []

    data = _fetch_submissions(cik, last_call)
    filer_category = re.sub(r"<[^>]+>", "", data.get("category") or "").strip()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    if not forms:
        return []

    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    acceptance_date_times = recent.get("acceptanceDateTime", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])
    items = recent.get("items", [])
    cik_int = str(int(cik))

    filings = []
    for i, form in enumerate(forms):
        if form not in _FORM_TYPES:
            continue
        accession = accession_numbers[i]
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        accession_nodash = accession.replace("-", "")
        raw_items = items[i] if i < len(items) else ""
        item_codes = [code.strip() for code in raw_items.split(",") if code.strip()]
        filings.append({
            "ticker": ticker.upper(),
            "cik": cik,
            "form_type": form,
            "filed_at": filing_dates[i] if i < len(filing_dates) else "",
            "accepted_at": acceptance_date_times[i] if i < len(acceptance_date_times) else "",
            "period_of_report": report_dates[i] if i < len(report_dates) else "",
            "accession_number": accession,
            "primary_doc_url": _ARCHIVES_URL.format(
                cik_int=cik_int, accession_nodash=accession_nodash, primary_doc=primary_doc,
            ) if primary_doc else "",
            "item_codes": item_codes,
            "filer_category": filer_category,
        })
    return filings


def fetch_filing_text(primary_doc_url: str, last_call: list[float], *, max_chars: int = 600_000) -> str:
    """Fetch a filing's primary document live and return plain text (HTML stripped).

    Never persisted by the caller - fetched fresh for one classification call.
    Returns "" on any failure. Default max_chars=600_000 covers a full 10-K
    (~500K chars observed on real filings) so extract_results_section() below
    has the whole document to search - callers passing this straight to an
    LLM without extraction should cap it themselves (8-K/10-Q rarely need to).
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


# Quantitative results-of-operations language varies a lot by filer - some
# open the MD&A results subsection with a revenue figure immediately ("net
# revenues increased by 23%"), others open with business overview narrative
# even within the correct subsection (e.g. CACI's 10-K says "fiscal 2023
# compared to fiscal 2022" as its results-comparison marker, with numbers
# appearing later). A fixed offset from the MD&A section heading is
# unreliable either way - confirmed empirically: on one real 10-K the actual
# comparison sat ~230K chars past the heading.
#
# Two-tier search: exact revenue/earnings comparison phrases first (found
# closest to the real numbers when present), then generic fiscal-year
# comparison phrases (a SEC-required MD&A element in every 10-K/10-Q,
# structurally more reliable across filers even if less precise).
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
    # Dollar-figure comparison language - confirmed empirically to catch cases
    # the exact-phrase and generic-fiscal-period tiers both miss (e.g. "Net
    # sales in 2025 increased $90.1 million, or 10.9%, to $916.7 million from
    # $826.6 million" - BMI; "net loss of $59.5 million" multi-year comparison
    # - ADPT). Broader than the precise tier's fixed phrase list, so it
    # generalizes to filer-specific wording without enumerating every variant.
    re.compile(r"increased \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"decreased \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"net loss of \$[\d,.]+ (?:million|billion)", re.I),
    re.compile(r"net income of \$[\d,.]+ (?:million|billion)", re.I),
    # "[metric] were $X million in YYYY, compared to $Y million in YYYY" -
    # confirmed on a real Coca-Cola 10-K ("Net operating revenues were
    # $47,941 million in 2025, compared to $47,061 million in 2024") - the
    # figures come before the comparison word here, unlike the "increased $X"
    # pattern above where the comparison word comes first.
    re.compile(r"were \$[\d,.]+ (?:million|billion) in \d{4}, compared to", re.I),
]

_RESULTS_WINDOW_BEFORE = 500
_RESULTS_WINDOW_AFTER = 15_000


def extract_results_section(text: str) -> tuple[str, bool]:
    """Extract the quantitative results-of-operations section from 10-K/10-Q text.

    Returns (section_text, found) - found=False means no marker matched and
    the fallback (first max_chars of the raw document) was used; callers
    should treat that case as lower-confidence and log it, since the fallback
    is likely to be XBRL tag metadata or front-matter, not the real section.

    Tries precise revenue/earnings comparison phrases first, then generic
    SEC-required fiscal-period-comparison language (present in every 10-K/
    10-Q's MD&A by regulation, even when the specific revenue phrasing
    varies by filer).

    Marker coverage matters more than position filtering here - confirmed
    empirically against a real 55-company sample: filings that looked like
    "TOC pollution" failures (e.g. Google, 11 occurrences of "results of
    operations" before the real section) actually failed because the marker
    list lacked the exact phrasing used ("revenues increased", plural, vs
    only "revenue increased" being listed) - the real section's first
    occurrence of a correctly-listed marker was the right one all along.
    """
    low = text.lower()

    # Take the EARLIEST match across all precise markers, not the first
    # marker in list order that matches anywhere - a later-listed marker can
    # legitimately match earlier in the document than an earlier-listed one
    # (confirmed on a real Coca-Cola 10-K: "net loss of $X million" matched a
    # minor hedging footnote at position ~375K, while a differently-worded
    # marker matched the real results section at position ~311K - checking
    # markers in list order and returning on first hit picked the wrong one).
    precise_positions = [idx for marker in _RESULTS_MARKERS_PRECISE if (idx := low.find(marker)) != -1]
    if precise_positions:
        idx = min(precise_positions)
        start = max(0, idx - _RESULTS_WINDOW_BEFORE)
        return text[start:idx + _RESULTS_WINDOW_AFTER], True

    generic_positions = [m.start() for pattern in _RESULTS_MARKERS_GENERIC if (m := pattern.search(text))]
    if generic_positions:
        idx = min(generic_positions)
        start = max(0, idx - _RESULTS_WINDOW_BEFORE)
        return text[start:idx + _RESULTS_WINDOW_AFTER], True

    return text[:_RESULTS_WINDOW_AFTER], False
