"""SEC EDGAR filing fetch helpers: ticker→CIK mapping + submissions lookup."""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"

_USER_AGENT = "OCN SignalDetection kajal.nain@opengrowth.com"
_MIN_INTERVAL = 0.15  # ~6-7 req/sec, under SEC's 10 req/sec guidance

_FORM_TYPES = {"8-K", "10-Q", "10-K"}

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

    Each item: ticker, form_type, filed_at, accession_number, primary_doc_url.
    Returns [] if the ticker has no known CIK or the fetch fails.
    """
    cik_map = _load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        logger.warning("[SEC_EDGAR] no CIK found for ticker=%s", ticker)
        return []

    data = _fetch_submissions(cik, last_call)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    if not forms:
        return []

    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    cik_int = str(int(cik))

    filings = []
    for i, form in enumerate(forms):
        if form not in _FORM_TYPES:
            continue
        accession = accession_numbers[i]
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        accession_nodash = accession.replace("-", "")
        filings.append({
            "ticker": ticker.upper(),
            "form_type": form,
            "filed_at": filing_dates[i] if i < len(filing_dates) else "",
            "accession_number": accession,
            "primary_doc_url": _ARCHIVES_URL.format(
                cik_int=cik_int, accession_nodash=accession_nodash, primary_doc=primary_doc,
            ) if primary_doc else "",
        })
    return filings
