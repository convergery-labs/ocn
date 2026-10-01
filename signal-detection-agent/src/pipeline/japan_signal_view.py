"""Shape classified japan_market_signal rows into the JpSignal objects
the Japan Signals tab renders.

This is a presentation layer over rows that are already classified: it
reads stored values and formats them, and computes nothing a rule has
not already decided. Where the consuming contract asks for a field this
pipeline has no data for, the field is null rather than filled with a
plausible value - a trading screen showing an inferred direction or an
invented checkpoint is worse than one showing neither.

Card text (headline, metric labels, caveat) is templated per signal type
here rather than written by a model: every value on a card is a figure
the classifier already settled, and a model asked to restate final
figures was confirmed to alter them.
"""
from __future__ import annotations

from typing import Any

from pipeline.japan_earnings_calendar import next_report_for
from pipeline.japan_read_through import links_for
from pipeline.japan_signal_summary import (
    _age_hours,
    _format_jpy_millions,
    _format_pct,
    signal_implication,
)
from pipeline.japan_ticker_universe import JAPAN_TICKER_UNIVERSE

# source_category -> (contract `type`, contract `code`, human source)
_TYPE_BY_CATEGORY: dict[str, tuple[str, str, str]] = {
    "jp_forecast": ("forecast", "J1", "IR Bank financials"),
    "jp_missing_revision": ("missing", "J3", "IR Bank financials"),
    "jp_industry": ("industry", "J4", "SEAJ billings"),
    "jp_capex": ("capacity", "J5", "MONOist factory news"),
    "jp_buyback": ("buyback", "J6", "IR Bank buyback history"),
    "jp_ownership": ("ownership", "J6", "Large shareholding report (EDINET)"),
    "jp_press": ("press", "J7", "Japan press (Jiji / Newswitch)"),
    "jp_watching": ("missing", "J3", "IR Bank financials"),
    "jp_disclosure": ("disclosure", "J8", "TDnet disclosure (Kabutan)"),
    "jp_extraordinary": ("disclosure", "J8", "Extraordinary report (EDINET)"),
}

_CLASSIFICATION = {
    "signal": "High Signal",
    "weak_signal": "Weak Signal",
    "noise": "Noise",
}

_INDUSTRY_SUBJECT = "Japan semiconductor equipment industry"

_CUSTOMERS_BY_CODE = {
    t["code"]: t.get("customers") or [] for t in JAPAN_TICKER_UNIVERSE
}


def _is_progress_row(meta: dict[str, Any]) -> bool:
    return meta.get("progress_pct") is not None


def _signal_type(meta: dict[str, Any]) -> tuple[str, str, str]:
    """Resolve the contract's type/code/source for one row.

    jp_forecast covers two of them: a forward-looking revision (J1) and
    a results-against-forecast reading (J2), told apart by whether the
    row carries a progress figure.
    """
    category = meta.get("source_category") or ""
    if category == "jp_forecast" and _is_progress_row(meta):
        return ("progress", "J2", "IR Bank financials")
    return _TYPE_BY_CATEGORY.get(category, ("forecast", "J1", "IR Bank financials"))


def _headline(signal_type: str, meta: dict[str, Any]) -> str:
    """Verb-first, no company name - the card prints the name separately."""
    if signal_type == "forecast":
        pct = meta.get("operating_profit_pct_change")
        if pct is not None:
            return f"{'Raised' if pct > 0 else 'Cut'} full-year profit forecast"
        revised = meta.get("margin_revised_pct")
        reference = meta.get("margin_reference_prior_year_actual_pct")
        if revised is not None and reference is not None:
            return f"{'Raised' if revised > reference else 'Cut'} operating margin guidance"
        return "Revised full-year guidance"
    if signal_type == "progress":
        return "Reported results against full-year target"
    if signal_type == "missing":
        return "Expected forecast announcement overdue"
    if signal_type == "industry":
        yoy = meta.get("yoy_pct")
        if yoy is not None:
            return f"Industry equipment billings {'rose' if yoy > 0 else 'fell'} year-on-year"
        return "Industry equipment billings reported"
    if signal_type == "capacity":
        return "Announced a capacity investment"
    if signal_type == "buyback":
        return "Announced a share buyback programme"
    if signal_type == "ownership":
        return "Large shareholding reported"
    if signal_type == "press":
        return "Press reported a checkable fact"
    if signal_type == "disclosure":
        return "Filed a corporate disclosure"
    return "Classified event"


def _change(signal_type: str, meta: dict[str, Any]) -> str | None:
    """The before-to-after line, in the units the filing itself uses."""
    if signal_type == "forecast":
        prev = _format_jpy_millions(meta.get("operating_profit_previous"))
        rev = _format_jpy_millions(meta.get("operating_profit_revised"))
        if prev and rev:
            return f"{prev} → {rev}"
        revised = meta.get("margin_revised_pct")
        reference = meta.get("margin_reference_prior_year_actual_pct")
        if revised is not None and reference is not None:
            return f"{_format_pct(reference)} → {_format_pct(revised)} operating margin"
        return None
    if signal_type == "progress":
        progress = _format_pct(meta.get("progress_pct"))
        elapsed = _format_pct(meta.get("fiscal_year_elapsed_pct"))
        if progress and elapsed:
            return f"{progress} reached · {elapsed} of year elapsed"
        return None
    if signal_type == "industry":
        billings = meta.get("billings_3mo_avg_millions_jpy")
        if billings is not None:
            return f"{_format_jpy_millions(billings)} (3-month average)"
        return None
    if signal_type == "buyback":
        shares = meta.get("buyback_program_limit_shares")
        if shares is not None:
            return f"up to {shares:,} shares"
        return None
    if signal_type == "ownership":
        pct = meta.get("holding_pct")
        return f"{_format_pct(pct)} held" if pct is not None else None
    if signal_type == "capacity":
        yen = meta.get("capex_investment_jpy")
        if yen is not None:
            return f"{_format_jpy_millions(yen / 1_000_000)} investment"
        return None
    return None


def _metric(signal_type: str, meta: dict[str, Any]) -> dict[str, Any]:
    """The big number on the card, or the word that stands in for it."""
    if signal_type == "forecast":
        pct = meta.get("operating_profit_pct_change")
        if pct is not None:
            return {"value": pct, "unit": "%", "text": None, "label": "forecast change"}
        revised = meta.get("margin_revised_pct")
        reference = meta.get("margin_reference_prior_year_actual_pct")
        if revised is not None and reference is not None:
            return {"value": round(revised - reference, 1), "unit": "pts",
                    "text": None, "label": "vs. last year's margin"}
        return {"value": None, "unit": None, "text": "Revised", "label": "guidance"}
    if signal_type == "progress":
        progress, elapsed = meta.get("progress_pct"), meta.get("fiscal_year_elapsed_pct")
        if progress is not None and elapsed is not None:
            gap = round(progress - elapsed, 1)
            return {"value": gap, "unit": "pts", "text": None,
                    "label": "ahead of schedule" if gap >= 0 else "behind schedule"}
        return {"value": None, "unit": None, "text": "Results", "label": "vs. target"}
    if signal_type == "industry":
        yoy = meta.get("yoy_pct")
        if yoy is not None:
            return {"value": yoy, "unit": "%", "text": None, "label": "industry sales, YoY"}
        return {"value": None, "unit": None, "text": "Industry", "label": "billings"}
    if signal_type == "buyback":
        pct = meta.get("buyback_pct_of_shares_outstanding")
        if pct is not None:
            return {"value": pct, "unit": "%", "text": None, "label": "of shares outstanding"}
        return {"value": None, "unit": None, "text": "Buyback", "label": "announced"}
    if signal_type == "ownership":
        pct = meta.get("holding_pct")
        if pct is not None:
            return {"value": pct, "unit": "%", "text": None, "label": "holding reported"}
        return {"value": None, "unit": None, "text": "5% holding", "label": "reported"}
    if signal_type == "capacity":
        pct = meta.get("capex_pct_of_total_assets")
        if pct is not None:
            return {"value": pct, "unit": "%", "text": None, "label": "of total assets"}
        return {"value": None, "unit": None, "text": "Capacity", "label": "investment"}
    if signal_type == "missing":
        return {"value": None, "unit": None, "text": "No update", "label": "expected window passed"}
    if signal_type == "press":
        return {"value": None, "unit": None, "text": "Press", "label": "report"}
    if signal_type == "disclosure":
        return {"value": None, "unit": None, "text": "Disclosure", "label": "corporate action"}
    return {"value": None, "unit": None, "text": None, "label": ""}


def _unusual(meta: dict[str, Any]) -> str | None:
    """How far this sits outside the company's own normal range."""
    pct = meta.get("operating_profit_pct_change")
    median = meta.get("habit_typical_size_pct")
    if pct is not None and median:
        multiple = abs(pct) / median
        word = "raise" if pct > 0 else "cut"
        if multiple >= 1.2:
            return (f"About {multiple:.1f}x this company's usual {word} "
                    f"of {_format_pct(median)}.")
        return f"In line with this company's usual {word} of {_format_pct(median)}."
    progress, elapsed = meta.get("progress_pct"), meta.get("fiscal_year_elapsed_pct")
    typical = meta.get("progress_habit_typical_pct")
    if progress is not None and typical is not None:
        return (f"{_format_pct(progress)} reached against a usual "
                f"{_format_pct(typical)} at this point.")
    if progress is not None and elapsed is not None:
        return f"{_format_pct(progress)} reached with {_format_pct(elapsed)} of the year gone."
    spreads = meta.get("industry_spreads_away")
    average = meta.get("industry_baseline_avg_yoy_pct")
    if spreads is not None and average is not None:
        return (f"{abs(spreads):.1f} spreads from the trailing 12-month "
                f"average of {_format_pct(average)}.")
    days = meta.get("days_since_last_revision")
    gap = meta.get("typical_days_between_revisions")
    if days is not None and gap:
        return f"{days} days since the last revision, against a usual {gap}."
    return None


def _caveat(signal_type: str, meta: dict[str, Any]) -> str | None:
    """What stops the number being read as more than it is."""
    if signal_type == "missing":
        ratio = meta.get("hit_ratio")
        month = meta.get("expected_month")
        if ratio is not None and month:
            return (f"Filed in month {month} in {round(ratio * 100)}% of past years. "
                    f"An absence, not a result - not good or bad on its own.")
    if signal_type == "industry":
        return "A 3-month moving average, not a single month's billings."
    if signal_type == "ownership":
        return ("A large-shareholding filing reports a position, not an intention - "
                "a holder may be building or unwinding.")
    if signal_type == "press":
        if meta.get("unconfirmed"):
            return "Reported by the press, not confirmed by the company."
    if signal_type == "disclosure":
        base = ("Judged from the filing's own title - the disclosure's full terms are "
                "in the document itself.")
        if meta.get("filed_in_english"):
            # Reported because it says who the filing is aimed at, not
            # because it affected the classification - see
            # classify_corporate_disclosure.
            return base + " The company also published it in English."
        return base
    if signal_type == "forecast" and meta.get("habit_is_trusted") is False:
        return ("Too few past revisions to establish this company's usual size, "
                "so the comparison is against the fixed floor only.")
    return None


def _rule_text(meta: dict[str, Any]) -> str | None:
    """Which bar the row cleared, in the units the bar is set in."""
    median = meta.get("habit_typical_size_pct")
    mad = meta.get("habit_typical_size_mad_pct")
    if median is not None and mad is not None:
        return (f"Its own bar is {_format_pct(median + 2 * mad)} - "
                f"a typical {_format_pct(median)} plus twice its "
                f"{_format_pct(mad)} spread.")
    return None


def _evidence(meta: dict[str, Any]) -> dict[str, Any]:
    """Recorded figures, the usual band, and the bar that was applied.

    usualRange and threshold are deliberately separate: a revision can
    sit above the company's normal band and still fall short of the bar
    that makes it a signal, and the page draws both.
    """
    figures: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        if value is not None:
            figures.append({"label": label, "value": str(value)})

    add("Previous forecast", _format_jpy_millions(meta.get("operating_profit_previous")))
    add("Revised forecast", _format_jpy_millions(meta.get("operating_profit_revised")))
    add("Change", _format_pct(meta.get("operating_profit_pct_change"), signed=True))
    add("Typical revision size", _format_pct(meta.get("habit_typical_size_pct")))
    add("Revisions on record", meta.get("habit_sample_size"))
    add("Progress to target", _format_pct(meta.get("progress_pct")))
    add("Year elapsed", _format_pct(meta.get("fiscal_year_elapsed_pct")))
    add("Billings, 3-month average",
        _format_jpy_millions(meta.get("billings_3mo_avg_millions_jpy")))
    add("Year-on-year", _format_pct(meta.get("yoy_pct"), signed=True))
    add("Holding", _format_pct(meta.get("holding_pct")))
    add("Buyback share of shares outstanding",
        _format_pct(meta.get("buyback_pct_of_shares_outstanding")))
    add("Investment share of total assets",
        _format_pct(meta.get("capex_pct_of_total_assets")))
    add("Days since last revision", meta.get("days_since_last_revision"))
    add("Usual interval", meta.get("typical_days_between_revisions"))

    # The English-coverage gap: how long a Japanese-language event has
    # gone before an English-reading desk could have seen it.
    found = meta.get("english_coverage_found")
    if found is False:
        figures.append({"label": "English coverage", "value": "None found yet"})
    elif found:
        gap = meta.get("english_coverage_hours_after_japanese")
        if gap is None:
            figures.append({"label": "English coverage", "value": "Found"})
        elif gap >= 0:
            figures.append({"label": "English coverage",
                            "value": f"Appeared {gap:.0f}h after the Japanese filing"})
        else:
            figures.append({"label": "English coverage",
                            "value": f"Appeared {abs(gap):.0f}h before the Japanese filing"})

    usual_range = None
    threshold = None
    median = meta.get("habit_typical_size_pct")
    mad = meta.get("habit_typical_size_mad_pct")
    if median is not None and mad is not None:
        value = meta.get("operating_profit_pct_change")
        usual_range = {
            "low": round(median - mad, 1),
            "high": round(median + mad, 1),
            "value": abs(value) if value is not None else None,
            "unit": "%",
        }
        threshold = round(median + 2 * mad, 1)

    # No sourceId here: it would be the row's own `id` on every row, the
    # same value under a second name. The evidence panel shows `id`.
    return {
        "figures": figures,
        "usualRange": usual_range,
        "threshold": threshold,
        "reasonCode": meta.get("signal_reason_code"),
        "notes": [],
        "discrepancy": None,
    }


def _source_url(meta: dict[str, Any], source_id: str | None) -> str | None:
    """A link to the document behind the row, for a reader checking it.

    Most rows carry a usable link already: IRBANK filings store the
    filing PDF, SEAJ stores its release, and the press and capex
    fetchers use the article's own URL as the row's id. The two that
    don't - EDINET filings and IRBANK buyback history - store a
    synthetic id whose parts address a real public page, so the link is
    rebuilt from those rather than left null.

    Returns None where no public document backs the row: a missing
    announcement (J3) and a stale-cadence reading (WATCHING) both
    describe an absence, so there is nothing to open.
    """
    pdf_url = meta.get("pdf_url")
    if pdf_url:
        return pdf_url

    if source_id and source_id.startswith(("http://", "https://")):
        return source_id

    if source_id and source_id.startswith(
        ("edinet-filing://", "edinet-buyback://", "edinet-extraordinary://")
    ):
        # All three EDINET schemes are {some_edinet_code}/{doc_id}, and
        # the document is served by doc id alone whichever filing type
        # it is - verified against real shareholding, buyback and
        # extraordinary doc ids, each returning a PDF.
        doc_id = meta.get("doc_id") or source_id.rsplit("/", 1)[-1]
        return f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_id}.pdf"

    if source_id and source_id.startswith("irbank-buyback://"):
        # irbank-buyback://{code}/{doc_id} - the per-company buyback
        # page carries the whole programme history, including this row.
        code = meta.get("code")
        return f"https://irbank.net/{code}/buyback" if code else None

    return None


def _connections(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """US-listed names this event reads through to, strongest first.

    Marked ``Static reference`` because the link is a standing property
    of the two companies' businesses, not something this particular
    filing established. An event-specific link - a filing naming a
    customer outright - would be ``Event-specific``, which nothing
    produces yet.
    """
    out = []
    for link in links_for(meta.get("code")):
        out.append({
            "ticker": link["ticker"],
            "name": link["name"],
            "relationship": link["relationship"],
            "connection": link["connection"],
            "evidence": "Static reference",
            "strength": link["strength"],
            "lag": link["lag"],
        })
    return out


def _next_checkpoint(meta: dict[str, Any], signal_type: str) -> dict[str, Any] | None:
    """When the strongest linked name next reports, and what to watch.

    The checkpoint is the linked company's results rather than the
    Japanese company's own: the read-through is the claim being tested,
    so the event that settles it is the one at the other end of the
    link. Returns None when there is no link, or when the stored date
    has passed - see next_report_for on why a stale date is withheld
    rather than printed.
    """
    links = links_for(meta.get("code"))
    if not links:
        return None
    link = links[0]
    report = next_report_for(link["ticker"])
    if not report:
        return None
    iso, event = report

    direction = signal_implication(meta)
    if direction == "Positive":
        supports = f"{link['name']} guiding higher on the same demand"
        weakens = f"{link['name']} reporting flat or softer demand"
    elif direction == "Negative":
        supports = f"{link['name']} guiding lower on the same demand"
        weakens = f"{link['name']} holding guidance despite it"
    else:
        supports = f"{link['name']} citing the same end-market shift"
        weakens = f"{link['name']} reporting no change"

    return {
        "event": event,
        "date": iso,
        "supports": supports,
        "weakens": weakens,
    }


def to_jp_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one classified row into a JpSignal object."""
    meta = row.get("metadata") or {}
    signal_type, code, source = _signal_type(meta)
    category = meta.get("source_category")
    is_industry = category == "jp_industry"

    if is_industry:
        date_kind = "Summary date"
        date_confirmed = bool(meta.get("date_confirmed"))
    elif category in ("jp_missing_revision", "jp_watching"):
        date_kind = "Detected"
        date_confirmed = True
    else:
        date_kind = "Published"
        date_confirmed = True

    reporting_period = meta.get("period")
    if reporting_period is None and meta.get("period_type"):
        reporting_period = f"{meta['period_type'].replace('_', ' ').capitalize()}, against full-year target"

    company_reason = meta.get("translated_reason") or meta.get("reason")

    return {
        "id": row.get("source_id") or row.get("url"),
        "type": signal_type,
        "code": code,
        "company": meta.get("company") or (_INDUSTRY_SUBJECT if is_industry else None),
        "ticker": meta.get("code"),
        "isIndustry": is_industry,
        "classification": _CLASSIFICATION.get(row.get("signal_detection"), "Noise"),
        "implication": signal_implication(meta),
        "date": row.get("published"),
        "dateKind": date_kind,
        "dateConfirmed": date_confirmed,
        "reportingPeriod": reporting_period,
        "source": source,
        "headline": _headline(signal_type, meta),
        "change": _change(signal_type, meta),
        "metric": _metric(signal_type, meta),
        "signal": row.get("signal_reason"),
        "unusual": _unusual(meta),
        "companyReason": company_reason,
        "caveat": _caveat(signal_type, meta),
        "ruleText": _rule_text(meta),
        "sourceUrl": _source_url(meta, row.get("source_id")),
        "connections": _connections(meta),
        "nextCheckpoint": _next_checkpoint(meta, signal_type),
        "evidence": _evidence(meta),
    }
