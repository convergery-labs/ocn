"""Stored financial figures per company and reporting period.

Written by a periodic fetch, read by whatever needs a company's own
history. The China C2 classifier is the first consumer: it compares a
revenue growth rate against that company's past growth rates, which
means it needs a series rather than a single figure, and a series has
to be stored - a daily classify pass cannot make twenty external calls
every run, and a company's history should not disappear if an upstream
endpoint changes.

See db.py's comment on `company_financials` for why these do not live
in `articles`.
"""
import logging
from typing import Any

from db import get_db

logger = logging.getLogger(__name__)


def upsert_financials(domain: str, rows: list[dict[str, Any]]) -> int:
    """Insert or replace reported figures, one row per period.

    UPSERT rather than append: a company restating a period must
    REPLACE its earlier figure. Accumulating both would put the same
    period into its own baseline twice and narrow the spread around
    whichever period it restated most.

    Returns the number of rows written.
    """
    if not rows:
        return 0
    with get_db() as conn:
        conn.execute_values(
            "INSERT INTO company_financials"
            " (domain, code, company, metric, period_type, period_year,"
            "  value, prior_value, yoy_pct, source)"
            " VALUES %s"
            " ON CONFLICT (domain, code, metric, period_type, period_year)"
            " DO UPDATE SET value = EXCLUDED.value,"
            "               prior_value = EXCLUDED.prior_value,"
            "               yoy_pct = EXCLUDED.yoy_pct,"
            "               company = EXCLUDED.company,"
            "               source = EXCLUDED.source,"
            "               fetched_at = NOW()",
            [
                (
                    domain,
                    r["code"],
                    r.get("company"),
                    r.get("metric", "revenue"),
                    r["period_type"],
                    str(r["year"]),
                    r.get("revenue"),
                    r.get("prior_revenue"),
                    r.get("yoy_pct"),
                    r.get("source") or "unknown",
                )
                for r in rows
            ],
        )
    return len(rows)


def get_financials(
    domain: str, metric: str = "revenue",
) -> list[dict[str, Any]]:
    """Every stored figure for one domain and metric.

    Returned in the same shape the fetchers produce, so a consumer
    cannot tell a stored row from a freshly fetched one - the field
    names and types are identical whichever source wrote it.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT code, company, period_type, period_year AS year,"
            "       value AS revenue, prior_value AS prior_revenue,"
            "       yoy_pct, source, fetched_at"
            "  FROM company_financials"
            " WHERE domain = %s AND metric = %s"
            " ORDER BY code, period_type, period_year",
            (domain, metric),
        ).fetchall()
    # NUMERIC comes back from the driver as Decimal, which serialises to
    # a JSON string and would make a stored row a different shape from a
    # freshly fetched one - a consumer doing arithmetic on `yoy_pct`
    # would get a TypeError only for stored rows. Cast back to float so
    # the two paths are genuinely interchangeable.
    out: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        for field in ("revenue", "prior_revenue", "yoy_pct"):
            if record.get(field) is not None:
                record[field] = float(record[field])
        out.append(record)
    return out
