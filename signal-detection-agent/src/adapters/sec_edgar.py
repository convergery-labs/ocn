"""SEC EDGAR filing text fetch + results-section extraction.

Filing metadata (ticker, form_type, accession_number, item_codes,
primary_doc_url, ...) is owned entirely by news-retrieval: its poller fetches
from EDGAR daily and stores in DynamoDB (`ocn-sec-filings`), read via
GET /market/sec-filings/{ticker} (see adapters/news_client.get_sec_filings).
signal-detection-agent does not call EDGAR's submissions API itself - only
the two functions here remain, since fetching a filing's full body text is
not something news-retrieval does (it stores metadata + a link only).
"""
from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "OCN SignalDetection kajal.nain@opengrowth.com"
_MIN_INTERVAL = 0.15  # ~6-7 req/sec, under SEC's 10 req/sec guidance


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


def extract_results_section(text: str) -> tuple[str, bool]:
    """Extract the quantitative results-of-operations section from 10-K/10-Q text.

    Returns (section_text, found) - found=False means no marker matched and
    the fallback (first max_chars of the raw document) was used; callers
    should treat that case as lower-confidence, since the fallback is likely
    to be XBRL tag metadata or front-matter, not the real section.
    """
    low = text.lower()

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
