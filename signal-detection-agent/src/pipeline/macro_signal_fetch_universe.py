"""series_id -> FRED release_id mapping, needed by COLLAPSE (grouping
same-release survivors) on this side of the pipeline.

Deliberately duplicated from news-retrieval's macro_release_times.py
rather than imported cross-service (these are two separate deployed
services with no shared runtime) - same documented tradeoff that
module's own docstring already accepts for the reverse direction
(SERIES_RELEASE_ID there doesn't import fetch-side config from here
either). Keep both copies in sync when a series' release_id changes.
"""
from __future__ import annotations

MACRO_SERIES_TO_RELEASE_ID: dict[str, int] = {
    "DFII10": 18, "DFII5": 18, "T10YIE": 18, "T5YIFR": 18,
    "T10Y2Y": 18, "T10Y3M": 18, "DGS10": 18, "DGS3MO": 18, "DGS2": 18, "DGS1": 18,
    "DFF": 18, "DFEDTARU": 18, "FEDTARMD": 326,
    "BAA10Y": 18, "NFCI": 221, "ANFCI": 221, "NFCICREDIT": 221,
    "DRTSCILM": 191, "WALCL": 20, "RRPONTSYD": 379, "WTREGEN": 20,
    "WRESBAL": 20, "TOTRESNS": 21, "DTWEXBGS": 18,
    "ICSA": 180, "WEI": 465, "GACDFSA066MSFRBPHI": 351, "NEWORDER": 95,
    "close_today_bal": -1,  # Treasury Fiscal Data, no FRED release_id - own synthetic id, unique from every real one
    "CPIAUCSL": 10, "CPILFESL": 10, "PCEPILFE": 54,
    "PAYEMS": 50, "UNRATE": 50, "SAHMREALTIME": 456, "JTSJOL": 192,
    "CCSA": 180, "RSAFS": 9, "HOUST": 27, "PERMIT": 27,
    "MORTGAGE30US": 190, "CSUSHPINSA": 199, "TOTALSL": 14, "DRCCLACBS": 231,
    "VIXCLS": 200, "VXVCLS": 200,
}
