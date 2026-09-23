"""DART (Financial Supervisory Service) corp_code mapping.

DART's filing-list API is keyed by its own 8-digit corp_code, not the
6-character KRX stock code - a query using the stock code returns an empty
result, not an error, so this mapping must be resolved up front rather than
assumed. See seed.py's KOREA_TICKER_UNIVERSE for the stock_code -> corp_code
join this module exists to perform.
"""
import logging
import zipfile
from io import BytesIO
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

_corp_code_map_cache: dict[str, str] | None = None


def _load_corp_code_map(api_key: str) -> dict[str, str]:
    """Fetch and cache DART's stock_code -> corp_code mapping (process lifetime).

    Downloads the full corpCode.xml bulk mapping (all entities ever
    registered on DART, listed and unlisted) and keeps only the
    stock_code -> corp_code pairs for entries that have a stock_code at
    all - unlisted entities report stock_code as a blank string and are
    dropped, since nothing in this pipeline can look them up without one.
    """
    global _corp_code_map_cache
    if _corp_code_map_cache is not None:
        return _corp_code_map_cache

    try:
        resp = httpx.get(_CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=30.0)
        resp.raise_for_status()
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")
        root = ElementTree.fromstring(xml_bytes)

        mapping: dict[str, str] = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code and corp_code:
                mapping[stock_code] = corp_code
        _corp_code_map_cache = mapping
        logger.info("[DART] loaded corp_code map entries=%d", len(mapping))
    except Exception as exc:
        logger.warning("[DART] failed to load corp_code map: %s", exc)
        _corp_code_map_cache = {}
    return _corp_code_map_cache


def resolve_corp_codes(stock_codes: list[str], api_key: str) -> dict[str, str]:
    """Return {stock_code: corp_code} for the given stock codes.

    Stock codes with no match in DART's mapping are omitted from the
    result (not raised as an error) - callers must check for missing
    entries explicitly, since a silently-skipped ticker would otherwise
    produce zero filings with no warning of why.
    """
    full_map = _load_corp_code_map(api_key)
    resolved = {code: full_map[code] for code in stock_codes if code in full_map}
    missing = [code for code in stock_codes if code not in full_map]
    if missing:
        logger.warning("[DART] no corp_code found for stock_codes=%s", missing)
    return resolved
