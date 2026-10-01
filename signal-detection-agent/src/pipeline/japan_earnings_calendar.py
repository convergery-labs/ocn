"""Next reporting date per US-listed read-through ticker.

A signal tells a reader something may be true; this says when they will
find out. The date is the next scheduled results release for the linked
US name, which is the first public event that can confirm or contradict
a read-through.

HAND-MAINTAINED, AND IT GOES STALE. These are scheduled dates, and a
company can move its own. Refresh once a quarter, at the same time the
read-through links are reviewed. Two properties keep a missed refresh
from doing damage:

  - A date in the past is treated as unknown rather than printed, so a
    stale entry produces no timing line instead of a wrong one. See
    ``next_report_for``.
  - Dates are keyed by ticker, not by link, so a name appearing under
    several Japanese companies has exactly one date to update.

Not sourced from the market-data poller: that fetches Alpha Vantage's
fiscal-period-end estimate for a different ticker universe entirely,
which is neither an announcement date nor these names. A wrong date on
a trading screen is worse than no date, so this stays explicit.

Refreshed 2026-10-01 for the quarter ending December 2026.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# ticker -> (ISO date, what the event is called on the card)
_NEXT_REPORT: dict[str, tuple[str, str]] = {
    "AAPL": ("2026-10-29", "Apple Q4 earnings"),
    "ADI": ("2026-11-24", "Analog Devices Q4 earnings"),
    "AMAT": ("2026-11-12", "Applied Materials Q4 earnings"),
    "AMD": ("2026-10-27", "AMD Q3 earnings"),
    "AMZN": ("2026-10-29", "Amazon Q3 earnings"),
    "APH": ("2026-10-21", "Amphenol Q3 earnings"),
    "ARM": ("2026-11-04", "Arm Q2 earnings"),
    "ASML": ("2026-10-14", "ASML Q3 earnings"),
    "AVGO": ("2026-12-10", "Broadcom Q4 earnings"),
    "CAMT": ("2026-11-10", "Camtek Q3 earnings"),
    "COHR": ("2026-11-04", "Coherent Q1 earnings"),
    "DD": ("2026-11-04", "DuPont Q3 earnings"),
    "ENTG": ("2026-10-28", "Entegris Q3 earnings"),
    "GLW": ("2026-10-27", "Corning Q3 earnings"),
    "INTC": ("2026-10-22", "Intel Q3 earnings"),
    "KLAC": ("2026-10-28", "KLA Q1 earnings"),
    "LITE": ("2026-11-05", "Lumentum Q1 earnings"),
    "LRCX": ("2026-10-21", "Lam Research Q1 earnings"),
    "MCHP": ("2026-11-05", "Microchip Q2 earnings"),
    "MKSI": ("2026-11-04", "MKS Instruments Q3 earnings"),
    "MSFT": ("2026-10-28", "Microsoft Q1 earnings"),
    "MU": ("2026-12-17", "Micron Q1 earnings"),
    "NVDA": ("2026-11-18", "Nvidia Q3 earnings"),
    "NXPI": ("2026-11-03", "NXP Q3 earnings"),
    "ONTO": ("2026-11-05", "Onto Innovation Q3 earnings"),
    "QCOM": ("2026-11-04", "Qualcomm Q4 earnings"),
    "STX": ("2026-10-21", "Seagate Q1 earnings"),
    "TER": ("2026-10-28", "Teradyne Q3 earnings"),
    "TSM": ("2026-10-15", "TSMC Q3 earnings"),
    "TXN": ("2026-10-20", "Texas Instruments Q3 earnings"),
    "WDC": ("2026-10-29", "Western Digital Q1 earnings"),
}


def next_report_for(ticker: str, as_of: datetime | None = None
                    ) -> tuple[str, str] | None:
    """Return (ISO date, event name) for a ticker's next results, or None.

    A stored date that has already passed means the table has not been
    refreshed since that company reported. None is returned rather than
    the stale date, so the card shows "Next checkpoint not available"
    instead of pointing a reader at an event that already happened.
    """
    entry = _NEXT_REPORT.get(ticker)
    if not entry:
        return None
    iso, event = entry
    today = (as_of or datetime.now(timezone.utc)).date()
    if date.fromisoformat(iso) < today:
        return None
    return iso, event
