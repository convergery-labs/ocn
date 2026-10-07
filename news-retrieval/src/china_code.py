"""China exchange-identifier mappings: cninfo orgId and HKEX stockId.

Both of China's disclosure sources are keyed by an internal identifier
that is NOT the stock code, and both answer a wrong/absent identifier
with an empty success rather than an error - a company that filed
nothing and a company we cannot address look identical. That is what
makes resolving these worth doing explicitly rather than assuming:

  cninfo   `stock` must be "CODE,ORGID". A bare code returns
           totalAnnouncement=0. orgId has at least three unrelated
           formats across the universe (gssz0000977, 9900014448,
           nssc1000455), so it cannot be derived from the code.
  HKEX     `stockId` is an internal issuer id. SMIC's code is 00981 but
           its id is 7249; Alibaba's 09988 is 1000015694. Passing the
           code returns an empty 200 - confirmed live, five of six
           companies silently returned nothing this way, and Tencent
           only worked by coincidence (00700 -> 700 is a valid
           unrelated id).

Both were previously hardcoded in seed.py's CHINA_TICKER_UNIVERSE,
resolved by hand once on 2026-10-05. This module replaces that with the
same runtime resolution Japan (edinet_code.py), Korea
(dart_corp_code.py) and the US (SEC company_tickers.json) already use,
so the catalogue no longer has to carry an identifier that only one
vendor's API understands - and a relisting or an orgId change is picked
up on the next run instead of going stale in a literal.

Verified live 2026-10-06 against the previously hardcoded values:
16/16 orgIds and 6/6 stockIds resolved identically.
"""
import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# The same bulk list cninfo's own site search is built on. Despite the
# "szse" name it carries BOTH exchanges - confirmed live, 6,259 rows
# including 600/603/688 Shanghai codes, so no separate SSE fetch is
# needed.
_CNINFO_STOCK_LIST_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"

# HKEX has no bulk download; this is the autocomplete its own disclosure
# search box calls, queried once per code.
_HKEX_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"

# Both hosts serve a browser-oriented endpoint and are inconsistent
# about answering a bare client. Sent on every request here for the
# same reason the China fetchers in pipeline.py send them.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

_cninfo_org_id_cache: dict[str, str] | None = None
_hkex_stock_id_cache: dict[str, str] = {}

# Matches the JSONP wrapper HKEX replies with: callback({...});
_HKEX_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.S)


def _load_cninfo_org_id_map() -> dict[str, str]:
    """Fetch and cache cninfo's code -> orgId mapping (process lifetime).

    On failure, caches an EMPTY map rather than retrying - the same
    trade-off edinet_code.py documents, and safe for the same reason:
    this domain runs as one-shot `trigger` CLI invocations, one fresh
    ECS task per CloudWatch run, so the cache is reset every run and a
    transient outage cannot poison later ones. Callers degrade to
    fetching nothing for that run rather than raising.

    The response is a JSON object whose `stockList` holds one entry per
    listed company: {"code", "pinyin", "category", "orgId", "zwjc"}.
    `zwjc` is the exchange's own registered short name - the same field
    CHINA_TICKER_UNIVERSE's native_name was taken from.
    """
    global _cninfo_org_id_cache
    if _cninfo_org_id_cache is not None:
        return _cninfo_org_id_cache

    try:
        resp = httpx.get(_CNINFO_STOCK_LIST_URL, headers=_HEADERS, timeout=60.0)
        resp.raise_for_status()
        rows = resp.json().get("stockList") or []
        mapping: dict[str, str] = {}
        for row in rows:
            code = (row.get("code") or "").strip()
            org_id = (row.get("orgId") or "").strip()
            if code and org_id:
                mapping[code] = org_id
        _cninfo_org_id_cache = mapping
        logger.info("[CHINA] loaded cninfo orgId map entries=%d", len(mapping))
    except Exception as exc:
        logger.warning("[CHINA] failed to load cninfo orgId map: %s", exc)
        _cninfo_org_id_cache = {}
    return _cninfo_org_id_cache


def resolve_cninfo_org_ids(codes: list[str]) -> dict[str, str]:
    """Return {code: orgId} for the given mainland codes.

    One bulk request covers the whole universe. Codes with no match are
    omitted and logged, never raised - a silently-skipped code would
    otherwise produce zero filings with no indication of why, which is
    precisely the failure this module exists to make visible.
    """
    full_map = _load_cninfo_org_id_map()
    resolved = {c: full_map[c] for c in codes if c in full_map}
    missing = [c for c in codes if c not in full_map]
    if missing:
        logger.warning("[CHINA] no cninfo orgId found for codes=%s", missing)
    return resolved


def _fetch_hkex_stock_id(hk_code: str) -> str | None:
    """Resolve one HK listing code to its internal HKEX stockId.

    Two details confirmed live 2026-10-06, both of which return a
    plausible-looking wrong answer rather than an error if ignored:

    - The `callback` parameter is REQUIRED. Without it the endpoint
      answers HTTP 200 with an empty body, not JSON.
    - The query is a PREFIX search and returns near matches alongside
      the exact one: "00981" came back with 5 entries (09810, 09812...).
      Only the entry whose `code` equals the requested one is used.
      Taking the first hit would work today - the exact match happens to
      sort first - but that is the API's ordering choice, not a
      guarantee, and this domain has already been bitten once by an
      identifier that looked right (Tencent's 00700 -> 700).
    """
    try:
        resp = httpx.get(
            _HKEX_PREFIX_URL,
            params={"callback": "callback", "lang": "EN", "type": "A",
                    "name": hk_code, "market": "SEHK"},
            headers={**_HEADERS, "Referer": "https://www1.hkexnews.hk/"},
            timeout=30.0,
        )
        resp.raise_for_status()
        m = _HKEX_JSONP_RE.match(resp.text.strip())
        if not m:
            logger.warning("[CHINA] hkex prefix.do unparseable for code=%s",
                           hk_code)
            return None
        rows = json.loads(m.group(1)).get("stockInfo") or []
    except Exception as exc:
        logger.warning("[CHINA] hkex prefix.do failed for code=%s: %s",
                       hk_code, exc)
        return None

    for row in rows:
        if (row.get("code") or "").strip() == hk_code:
            stock_id = row.get("stockId")
            if stock_id is not None:
                return str(stock_id)
    logger.warning("[CHINA] no exact hkex match for code=%s (%d near matches)",
                   hk_code, len(rows))
    return None


def resolve_hkex_stock_ids(hk_codes: list[str]) -> dict[str, str]:
    """Return {hk_code: stockId} for the given HK listing codes.

    HKEX publishes no bulk list, so this is one request per code -
    acceptable because the HK-listed slice of this universe is 6
    companies, and results are cached for the process lifetime. Codes
    that do not resolve are omitted and logged, same contract as
    resolve_cninfo_org_ids.
    """
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for code in hk_codes:
        if code in _hkex_stock_id_cache:
            resolved[code] = _hkex_stock_id_cache[code]
            continue
        stock_id = _fetch_hkex_stock_id(code)
        if stock_id:
            _hkex_stock_id_cache[code] = stock_id
            resolved[code] = stock_id
        else:
            missing.append(code)
    if missing:
        logger.warning("[CHINA] no hkex stockId found for codes=%s", missing)
    if resolved:
        logger.info("[CHINA] resolved hkex stockIds count=%d", len(resolved))
    return resolved
