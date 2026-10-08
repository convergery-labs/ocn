"""Structured revenue history for the China universe.

C2 compares a company's revenue growth against its own past growth, so
it needs a clean series of figures per reporting period. Those were
being recovered by parsing filing PDFs, which works but fails in ways
that are invisible rather than loud:

  - the largest number in a document is not always the company's own
    figure (a GigaDevice filing's biggest amount was the VALUATION of
    the company it was investing in, not its investment)
  - periodic reports lose their table headers to PDF extraction, so a
    row sitting intact below a shuffled header is never read
  - some issuers state growth qualitatively - BOE's pre-announcements
    say 营业收入同比增长超10% ("grew by MORE than 10%"), which carries
    no figure at all

All three disappear if the figures are taken from a structured source.
Confirmed against the PDF-extracted series: cninfo's own API returns
+121.83 / +17.30 / +52.40 / +56.92 for Hygon's four annual periods,
exactly what extraction produced - and additionally covers five
companies extraction could not read at all.

THREE SOURCES, IN PREFERENCE ORDER
  cninfo data20   the 16 mainland-listed companies, all four period
                  types, 3-5 observations each
  Alpha Vantage   Alibaba and Baidu, which file with the SEC - 20
                  annual periods each, far more than any mainland name
  (neither)       Tencent and Lenovo are OTC ADRs that file nothing
                  with the SEC and are not on cninfo. They stay on PDF
                  extraction, which is why that path is kept rather
                  than deleted.
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Undocumented - this is what cninfo's own web UI calls. `sign=1` is
# required and non-obvious: without it the endpoint answers HTTP 500
# with {"msg":"validate fail!"} rather than a clear error. Because it
# is unpublished it could change without notice, which is the other
# reason the PDF path is kept as a fallback.
_CNINFO_FINANCIALS_URL = (
    "http://www.cninfo.com.cn/data20/financialData/getIncomeStatement"
)
_CNINFO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}
_TIMEOUT = 30.0

# cninfo's own period keys. `three` is the nine-month cumulative figure
# a Q3 report carries, not a standalone third quarter - the same thing
# the filing itself reports, so the label matches the document.
_CNINFO_PERIOD_KEYS = {
    "year": "FY",
    "middle": "H1",
    "one": "Q1",
    "three": "Q3",
}

_AV_URL = "https://www.alphavantage.co/query"
# Alibaba and Baidu file with the SEC; their ADR tickers are what Alpha
# Vantage answers to. Tencent (TCEHY) and Lenovo (LNVGY) are deliberately
# absent - both were probed and return zero reports, being OTC ADRs with
# no SEC filing obligation.
_AV_TICKERS = {"09988": "BABA", "09888": "BIDU"}


def _yoy_from_series(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Year-on-year change for each consecutive pair in one period type.

    cninfo returns a figure per year for a given period - {"2025": ...,
    "2024": ...} - and the growth rate is derived here rather than read,
    because the API carries levels, not changes. A pair is skipped where
    either side is missing or the prior year is zero.
    """
    out: list[dict[str, Any]] = []
    years = sorted(k for k in values if str(k).isdigit())
    for i in range(1, len(years)):
        prior_year, year = years[i - 1], years[i]
        try:
            prior = float(values[prior_year])
            current = float(values[year])
        except (TypeError, ValueError):
            continue
        if not prior:
            continue
        out.append({
            "year": year,
            "revenue": current,
            "prior_revenue": prior,
            "yoy_pct": round((current - prior) / abs(prior) * 100, 2),
        })
    return out


def fetch_cninfo_revenue(code: str) -> list[dict[str, Any]]:
    """Revenue history for one mainland code, one row per period.

    Returns [] on any failure - a company whose figures cannot be
    fetched falls back to whatever the PDF path produced, rather than
    failing the run.
    """
    try:
        resp = httpx.get(_CNINFO_FINANCIALS_URL,
                         params={"scode": code, "sign": "1"},
                         headers=_CNINFO_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        records = (resp.json().get("data") or {}).get("records") or []
    except Exception as exc:
        logger.warning("[CHINA_FIN] cninfo revenue failed code=%s: %s",
                       code, exc)
        return []
    if not records:
        logger.info("[CHINA_FIN] cninfo has no income statement for %s - "
                    "expected for a Hong Kong-only listing", code)
        return []

    row = records[0]
    out: list[dict[str, Any]] = []
    for key, period_type in _CNINFO_PERIOD_KEYS.items():
        series = row.get(key)
        if not series:
            continue
        values = series[0] if isinstance(series, list) else series
        if not isinstance(values, dict):
            continue
        for entry in _yoy_from_series(values):
            out.append({**entry, "period_type": period_type,
                        "code": code, "source": "cninfo_data20"})
    return out


def fetch_av_revenue(code: str, api_key: str | None) -> list[dict[str, Any]]:
    """Revenue history for an SEC-filing ADR, annual periods only.

    Quarterly reports are available too but are NOT used: Alibaba's
    fiscal year ends 31 March, so its quarters do not line up with a
    mainland company's, and C2 compares a company only against itself
    anyway. Annual periods are the cleanest like-for-like series.
    """
    ticker = _AV_TICKERS.get(code)
    if not ticker or not api_key:
        return []
    try:
        resp = httpx.get(_AV_URL, params={
            "function": "INCOME_STATEMENT", "symbol": ticker,
            "apikey": api_key}, timeout=_TIMEOUT)
        resp.raise_for_status()
        reports = resp.json().get("annualReports") or []
    except Exception as exc:
        logger.warning("[CHINA_FIN] alpha vantage failed %s/%s: %s",
                       code, ticker, exc)
        return []

    values: dict[str, Any] = {}
    for report in reports:
        ending = report.get("fiscalDateEnding") or ""
        revenue = report.get("totalRevenue")
        if len(ending) >= 4 and revenue not in (None, "None"):
            values[ending[:4]] = revenue
    return [
        {**entry, "period_type": "FY", "code": code,
         "source": f"alpha_vantage:{ticker}"}
        for entry in _yoy_from_series(values)
    ]


def _is_mainland_code(code: str) -> bool:
    """True for a Shanghai or Shenzhen listing code.

    Mainland codes are six digits; a Hong Kong code is five with a
    leading zero (00700, 09988). cninfo covers only the former, and
    asking it about an HK code returns HTTP 500 rather than an empty
    result - a failure log for something working as intended.
    """
    return len(code) == 6 and code.isdigit()


def fetch_revenue_history(
    code: str, api_key: str | None = None,
) -> list[dict[str, Any]]:
    """One company's revenue YoY series, from the best source available.

    cninfo first - it carries all four reporting periods, where Alpha
    Vantage is used for annual only. A company on neither returns [],
    and the caller keeps whatever PDF extraction found.
    """
    # A Hong Kong listing code is not on a mainland exchange, so cninfo
    # answers HTTP 500 for it. Asking anyway would log a failure for
    # something that is working exactly as expected, so those codes go
    # straight to the ADR source.
    if code not in _AV_TICKERS and not _is_mainland_code(code):
        return []
    rows = fetch_cninfo_revenue(code) if _is_mainland_code(code) else []
    if rows:
        return rows
    return fetch_av_revenue(code, api_key)
