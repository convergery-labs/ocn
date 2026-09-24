"""Per-series publication frequency, needed only for suppression
mechanism C (confirmation reversal, spec section 5): "For weekly and
monthly series, a move that fully reverses at the next observation is
reclassified NOISE." This does NOT apply to daily series - a daily
rate's "next observation" is just the following trading day, not a
meaningful confirmation window, and the spec's own examples (jobless
claims, the Philadelphia Fed survey) are explicitly weekly/monthly.

Classified from the spec's own section 7 series table (native
publication cadence per series, not the tier rule's own d1d/d1w/d4w
window language, which is a measurement window, not the series'
underlying release cadence).
"""
from __future__ import annotations

from enum import Enum


class Frequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


SERIES_FREQUENCY: dict[str, Frequency] = {
    # Background state variables - daily market series
    "DFII10": Frequency.DAILY, "DFII5": Frequency.DAILY, "T10YIE": Frequency.DAILY,
    "T5YIFR": Frequency.DAILY, "T10Y2Y": Frequency.DAILY, "T10Y3M": Frequency.DAILY,
    "DGS10": Frequency.DAILY, "DGS3MO": Frequency.DAILY, "DGS2": Frequency.DAILY,
    "DGS1": Frequency.DAILY, "DFF": Frequency.DAILY, "DFEDTARU": Frequency.DAILY,
    "FEDTARMD": Frequency.QUARTERLY,  # SEP, 4x/year
    "BAA10Y": Frequency.DAILY,
    "NFCI": Frequency.WEEKLY, "ANFCI": Frequency.WEEKLY, "NFCICREDIT": Frequency.WEEKLY,
    "DRTSCILM": Frequency.QUARTERLY,  # SLOOS
    "WALCL": Frequency.WEEKLY, "RRPONTSYD": Frequency.DAILY, "WTREGEN": Frequency.DAILY,
    "WRESBAL": Frequency.WEEKLY, "TOTRESNS": Frequency.MONTHLY,
    "DTWEXBGS": Frequency.DAILY,
    # Early-arriving hard data
    "ICSA": Frequency.WEEKLY, "WEI": Frequency.WEEKLY,
    "GACDFSA066MSFRBPHI": Frequency.MONTHLY, "NEWORDER": Frequency.MONTHLY,
    "close_today_bal": Frequency.DAILY,
    # Consumer and market-facing
    "CPIAUCSL": Frequency.MONTHLY, "CPILFESL": Frequency.MONTHLY, "PCEPILFE": Frequency.MONTHLY,
    "PAYEMS": Frequency.MONTHLY, "UNRATE": Frequency.MONTHLY, "SAHMREALTIME": Frequency.MONTHLY,
    "JTSJOL": Frequency.MONTHLY, "CCSA": Frequency.WEEKLY, "RSAFS": Frequency.MONTHLY,
    "HOUST": Frequency.MONTHLY, "PERMIT": Frequency.MONTHLY, "MORTGAGE30US": Frequency.WEEKLY,
    "CSUSHPINSA": Frequency.MONTHLY, "TOTALSL": Frequency.MONTHLY, "DRCCLACBS": Frequency.QUARTERLY,
    "VIXCLS": Frequency.DAILY, "VXVCLS": Frequency.DAILY,
}

# Mechanism C only applies to these - spec's own "weekly and monthly
# series" language. Quarterly series (FEDTARMD, DRTSCILM, DRCCLACBS) are
# excluded too: their "next observation" is 3 months away, and none of
# the spec's own examples or reasoning cover a quarterly-cadence
# confirmation window - treating them the same as weekly/monthly would
# be extrapolating past what the spec actually specifies.
CONFIRMATION_REVERSAL_ELIGIBLE: frozenset[str] = frozenset(
    sid for sid, freq in SERIES_FREQUENCY.items()
    if freq in (Frequency.WEEKLY, Frequency.MONTHLY)
)
