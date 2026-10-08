"""Per-company baselines, cached between a refresh job and the daily
classify pass.

A signal in these domains means "unusual FOR THIS COMPANY" - a revenue
growth rate judged against that company's own history rather than
against whoever else happened to file this quarter. Computing that needs
years of filings; the scheduled classify pass pools a single day. This
table is what lets the two coexist: a periodic job rebuilds the
baselines from the full history, and the daily pass reads them.

Without it the same classifier gives different answers depending on how
it was invoked - a four-year backfill produces signals while the daily
schedule sees two or three observations per company, falls below its own
trust floor and produces none.

See db.py's own comment on the table for why it is market-agnostic but
currently China-only.
"""
from typing import Any

from db import get_db

# What each metric measures, so a reader does not have to infer it from
# the column name. Values are stored as-is; nothing validates them, and
# the writer and reader are the same module by design.
METRIC_REVENUE_YOY = "revenue_yoy"          # C2, percent
METRIC_COMMITMENT_VALUE = "commitment_value"  # C3, currency units


def upsert_baselines(domain: str, rows: list[dict[str, Any]]) -> int:
    """Replace every baseline for one domain with a freshly computed set.

    A DELETE-then-INSERT rather than an upsert per row: a company that
    has dropped below the trust floor since the last refresh, or whose
    period type no longer appears, must LOSE its row rather than keep a
    stale one. An upsert alone would leave that row behind and the
    classifier would go on judging against a baseline nothing recomputes.

    Returns the number of rows written.
    """
    if not rows:
        return 0
    with get_db() as conn:
        conn.execute(
            "DELETE FROM market_signal_baselines WHERE domain = %s",
            (domain,),
        )
        conn.execute_values(
            "INSERT INTO market_signal_baselines"
            " (domain, code, metric, period_type, company, median, mad,"
            "  sample_size, is_trusted, computed_from)"
            " VALUES %s",
            [
                (
                    domain,
                    r["code"],
                    r["metric"],
                    r.get("period_type") or "",
                    r.get("company"),
                    r.get("median"),
                    r.get("mad"),
                    r["sample_size"],
                    r["is_trusted"],
                    r.get("computed_from"),
                )
                for r in rows
            ],
        )
    return len(rows)


def load_baselines(domain: str, metric: str | None = None) -> dict[
        tuple[str, str], dict[str, Any]]:
    """Every baseline for one domain, keyed (code, period_type).

    Only TRUSTED rows are returned. An untrusted row records that the
    company was measured and found to have too little history - useful
    to a reader, but a classifier reading it would be judging against a
    baseline the refresh job already declined to stand behind.

    Keyed without `metric` when one is given, since a caller asking for
    revenue baselines has no use for commitment ones in the same dict.
    """
    sql = ("SELECT code, metric, period_type, company, median, mad,"
           "       sample_size, computed_from, refreshed_at"
           "  FROM market_signal_baselines"
           " WHERE domain = %s AND is_trusted = TRUE")
    params: list[Any] = [domain]
    if metric:
        sql += " AND metric = %s"
        params.append(metric)
    with get_db() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return {(r["code"], r["period_type"]): dict(r) for r in rows}
