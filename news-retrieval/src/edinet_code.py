"""EDINET (Financial Services Agency) EDINET-code mapping.

EDINET's documents.json API never returns a usable TSE ticker for a
docTypeCode 350 (large shareholding) filing's issuerEdinetCode - secCode is
confirmed live to be null on every 350-type row, since the API describes the
FILER (who bought the shares), not the issuer, and even the filer's own
secCode is rarely populated for this document type. There is no per-ticker
lookup endpoint either. This mapping must be resolved from EDINET's own bulk
code-list download instead - see seed.py's JAPAN_TICKER_UNIVERSE for the
ticker -> edinet_code join this module exists to perform.
"""
import csv
import logging

import httpx

logger = logging.getLogger(__name__)

_EDINET_CODELIST_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"

_edinet_code_map_cache: dict[str, str] | None = None


def _load_edinet_code_map() -> dict[str, str]:
    """Fetch and cache EDINET's ticker -> edinet_code mapping (process
    lifetime).

    On a download/parse failure, caches an EMPTY map rather than retrying -
    confirmed live (simulated failure test, 2026-09-28) this correctly
    degrades resolve_edinet_codes() and every edinet_filing/
    edinet_buyback_status/edinet_extraordinary_report fetch to a clean
    early return (no exception propagates), just with zero results for
    that run. Caching the failure rather than retrying is safe specifically
    BECAUSE this runs as a one-shot `trigger` CLI invocation, one fresh
    ECS task per CloudWatch-scheduled run (see infra's
    news_retrieval_japan_market_signal_daily/_monthly rules) - the module-
    level cache is reset every run regardless, so a transient outage during
    one run cannot poison later runs the way it would in a long-lived
    server process repeatedly calling this within one process lifetime.

    Downloads the full EdinetcodeDlInfo.csv bulk mapping (every entity ever
    registered on EDINET, listed and unlisted) and keeps only rows with a
    populated 証券コード (securities code) - unlisted/delisted entities
    report this as blank and are dropped, since nothing in this pipeline can
    look them up by ticker without one (confirmed live: Shinko Electric,
    ticker 6967, is one such row as of 2026-09-28 - see seed.py's own note
    on JAPAN_TICKER_UNIVERSE).

    The CSV is Shift-JIS (cp932) encoded, not UTF-8 - confirmed live;
    decoding as UTF-8 raises rather than silently mojibake-ing, since the
    byte sequences involved are not valid UTF-8.

    Securities codes in this file are 5 digits (a 4-digit TSE ticker plus a
    trailing "0", e.g. Advantest's 6857 -> "68570") - stripped back to the
    4-character ticker form used throughout JAPAN_TICKER_UNIVERSE. Kioxia's
    alphanumeric ticker (285A) was confirmed live to resolve correctly this
    same way (its own 5-digit code strips to "285A").
    """
    global _edinet_code_map_cache
    if _edinet_code_map_cache is not None:
        return _edinet_code_map_cache

    try:
        resp = httpx.get(_EDINET_CODELIST_URL, timeout=60.0)
        resp.raise_for_status()

        import zipfile
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            # Confirmed live: single member, name EdinetcodeDlInfo.csv.
            raw = zf.read(zf.namelist()[0])
        text = raw.decode("cp932")
        # First 2 lines are a download-date banner and the column header,
        # not data - confirmed live (see this module's docstring for the
        # exact header row).
        lines = text.split("\r\n")
        reader = csv.reader(lines[2:])

        mapping: dict[str, str] = {}
        for row in reader:
            if len(row) <= 11:
                continue
            edinet_code = row[0].strip()
            sec_code = row[11].strip()
            if not edinet_code or not sec_code:
                continue
            ticker = sec_code[:-1] if sec_code.endswith("0") else sec_code
            mapping[ticker] = edinet_code
        _edinet_code_map_cache = mapping
        logger.info("[EDINET] loaded edinet_code map entries=%d", len(mapping))
    except Exception as exc:
        logger.warning("[EDINET] failed to load edinet_code map: %s", exc)
        _edinet_code_map_cache = {}
    return _edinet_code_map_cache


def resolve_edinet_codes(tickers: list[str]) -> dict[str, str]:
    """Return {ticker: edinet_code} for the given tickers.

    Tickers with no match (delisted, or a securities code format this
    module's stripping logic doesn't cover) are omitted from the result,
    not raised as an error - callers must check for missing entries
    explicitly, since a silently-skipped ticker would otherwise produce
    zero filings with no warning of why.
    """
    full_map = _load_edinet_code_map()
    resolved = {t: full_map[t] for t in tickers if t in full_map}
    missing = [t for t in tickers if t not in full_map]
    if missing:
        logger.warning("[EDINET] no edinet_code found for tickers=%s", missing)
    return resolved
