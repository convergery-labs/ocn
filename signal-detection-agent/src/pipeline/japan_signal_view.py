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
    # Its own type, not J3's. Both describe an absence, but a missing
    # announcement slot is a specific expected filing that did not
    # arrive, while this is a company drifting from its own cadence
    # with no particular filing due - and a consumer separating the
    # watch list from the event feed should not have to do it by id.
    "jp_watching": ("watching", "W", "IR Bank financials"),
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

_JAPAN_TICKER_BY_CODE = {t["code"]: t for t in JAPAN_TICKER_UNIVERSE}


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


def _short_holder_name(name: str | None) -> str | None:
    """Trim the legal suffixes off an institution's name.

    "Sumitomo Mitsui Trust Asset Management Co., Ltd." is the filing's
    own wording; a card has room for who filed, not their incorporation
    status.
    """
    if not name:
        return None
    for suffix in (" Co., Ltd.", " Co.,Ltd.", " Co., Ltd", " Corporation",
                   " Securities Co., Ltd.", ", Inc.", " Inc.", " Ltd.", " K.K."):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("Asset Management", "AM").strip()


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
        # Say which way it went, matching the metric's own label -
        # "reported results" tells a reader nothing they cannot see
        # from the category.
        progress = meta.get("progress_pct")
        typical = meta.get("progress_habit_typical_pct")
        elapsed = meta.get("fiscal_year_elapsed_pct")
        baseline = typical if (typical is not None and typical != progress) else elapsed
        if progress is not None and baseline is not None:
            return ("Ran ahead of its full-year target" if progress >= baseline
                    else "Ran behind its full-year target")
        return "Reported results against full-year target"
    if signal_type == "missing":
        return "Expected forecast announcement overdue"
    if signal_type == "watching":
        return "Quiet longer than its usual cadence"
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
        # Name the holder and say what they did. "Large shareholding
        # reported" is the filing's category, not its content, and the
        # holder's name was only reachable in Japanese inside the
        # reason sentence.
        holder = _short_holder_name(
            meta.get("translated_filer_name") or meta.get("filer_name")
        )
        code = meta.get("signal_reason_code") or ""
        pct = _format_pct(meta.get("holding_pct"))
        stake = f"{pct} stake" if pct else "stake"
        if "passive" in code:
            what = f"Passive {stake} filed"
        elif "crosses_five_pct" in code:
            what = f"New {stake} crossing 5%"
        else:
            what = f"{stake.capitalize()} changed"
        # Verb-first and without the issuer's name: the card prints the
        # company itself, and a summary strip composing
        # "{company} {headline}" would otherwise repeat it.
        return f"{what} by {holder}" if holder else "Large shareholding reported"
    if signal_type == "press":
        # The classifier's verdict is not the story. Where a translated
        # headline exists, the report's own subject is what a reader
        # needs; the verdict stays in `signal`.
        headline = meta.get("translated_title")
        if headline:
            # Stored titles are "{company} ({code}): {headline}" - take
            # the headline, then drop a leading company name the
            # article's own wording repeats, since the card already
            # shows it.
            subject = (headline.split(": ", 1)[-1] if ": " in headline else headline).strip()
            # Match on the first word, not the registered name: press
            # writes "Resonac" where the universe says "Resonac
            # Holdings", so an exact prefix check leaves the repeat in.
            company = meta.get("company") or ""
            head = company.split()[0] if company else ""
            if len(head) >= 3 and subject.lower().startswith(head.lower()):
                subject = subject[len(head):].lstrip(" ,-–—'’s")
            return subject or "Press reported a checkable fact"
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
        progress = meta.get("progress_pct")
        elapsed = meta.get("fiscal_year_elapsed_pct")
        typical = meta.get("progress_habit_typical_pct")
        # Measure against the company's own usual pace where one exists:
        # a company that habitually books 60% of its year by Q2 is not
        # "ahead" at 55% just because only 50% of the year has passed.
        # The elapsed year is the fallback, used when no usual pace has
        # been established - and when the stored typical is just this
        # same reading (too few samples for a median to differ from the
        # one value in it), which is a comparison with itself.
        if progress is not None and typical is not None and typical != progress:
            gap = round(progress - typical, 1)
            return {"value": gap, "unit": "pts", "text": None,
                    "label": "ahead of its usual pace" if gap >= 0
                    else "behind its usual pace"}
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
    if signal_type == "watching":
        # How long the company has been silent is the headline number
        # here, even though no filing is being reported.
        days = meta.get("days_since_last_revision")
        if days is not None:
            return {"value": days, "unit": "days", "text": None,
                    "label": "since last revision"}
        return {"value": None, "unit": None, "text": "Quiet", "label": "no recent revision"}
    if signal_type == "missing":
        # A slot that did not produce a filing has no number of its own.
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
    # A typical equal to this very reading means the company's stored
    # history is this one row, so the median is the value itself -
    # "46.7% against a usual 46.7%" compares a number with itself and
    # tells a reader nothing.
    if progress is not None and typical is not None and typical != progress:
        return (f"{_format_pct(progress)} reached against a usual "
                f"{_format_pct(typical)} at this point.")
    if progress is not None and elapsed is not None:
        return f"{_format_pct(progress)} reached with {_format_pct(elapsed)} of the year gone."
    spreads = meta.get("industry_spreads_away")
    average = meta.get("industry_baseline_avg_yoy_pct")
    if spreads is not None and average is not None:
        return (f"Ran {abs(spreads):.1f} times its usual distance from the "
                f"recent average of {_format_pct(average)}.")
    days = meta.get("days_since_last_revision")
    gap = meta.get("typical_days_between_revisions")
    if days is not None and gap:
        return f"{days} days since the last revision, against a usual {gap}."

    # The remaining types carry no habit to compare against, so what
    # makes them unusual is the size of the thing itself measured
    # against the company - a buyback as a share of the company, an
    # investment as a share of its balance sheet, a holding as a share
    # of its equity. Without this these rows said nothing at all.
    buyback_pct = meta.get("buyback_pct_of_shares_outstanding")
    if buyback_pct is not None:
        return (f"Covers {_format_pct(buyback_pct)} of shares outstanding"
                f"{' - a large programme for one authorisation' if buyback_pct >= 5 else ''}.")
    capex_pct = meta.get("capex_pct_of_total_assets")
    if capex_pct is not None:
        return f"Worth {_format_pct(capex_pct)} of the company's total assets."
    holding = meta.get("holding_pct")
    if holding is not None:
        code = meta.get("signal_reason_code") or ""
        basis = ("filed under the passive-investor regime" if "passive" in code
                 else "filed on an active basis")
        return f"A {_format_pct(holding)} stake, {basis}."
    if meta.get("filed_in_english"):
        return ("The company published this filing in English as well as Japanese, "
                "which it does not do for most disclosures.")

    # Everything else has no established comparison. "Why it's unusual"
    # must answer that question or stay empty - a line explaining why
    # the comparison is unavailable belongs in the caveat, which is
    # where a reader looks for what limits the card.
    return None


def _caveat(signal_type: str, meta: dict[str, Any]) -> str | None:
    """What stops the number being read as more than it is."""
    if signal_type == "watching":
        return ("A pace reading, not an event - the company has filed nothing, "
                "which is not good or bad on its own.")
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
    # Why a card has no "unusual" line: the comparison could not be
    # made, which limits the reading rather than describing it.
    if signal_type == "capacity" and meta.get("capex_investment_jpy") is None:
        return ("The announcement states no investment figure, so its scale "
                "against the company's balance sheet is unknown.")
    if (signal_type in ("forecast", "progress")
            and meta.get("habit_typical_size_pct") is None
            and meta.get("habit_is_trusted") is not False):
        samples = meta.get("habit_sample_size")
        if samples:
            return (f"Only {samples} past revision{'s' if samples != 1 else ''} on "
                    f"record - too few to say what is usual for this company.")
        return "No past revisions on record to compare this against."
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
        # Coverage always follows the filing - see
        # _ENGLISH_COVERAGE_MAX_LEAD_HOURS - so there is no "before"
        # case to render.
        gap = meta.get("english_coverage_hours_after_japanese")
        if gap is None:
            figures.append({"label": "English coverage", "value": "Found"})
        elif gap < 48:
            figures.append({"label": "English coverage",
                            "value": f"Appeared {gap:.0f}h after the filing"})
        else:
            figures.append({"label": "English coverage",
                            "value": f"Appeared {gap / 24:.0f} days after the filing"})

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


_QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def _next_quarter_end(fiscal_year_end: str | None) -> tuple[str, str] | None:
    """The company's next reporting period end, and which quarter it is.

    Japanese issuers announce roughly four to six weeks after a quarter
    closes, but that is a convention rather than a scheduled date, and
    this pipeline has no filed calendar for them. So the period end is
    returned and the announcement date is left unset - the contract
    renders that as "Date not confirmed", which is the true state.
    """
    from datetime import date
    if not fiscal_year_end:
        return None
    try:
        fy_month = int(fiscal_year_end.split("-")[0])
    except (ValueError, IndexError):
        return None

    today = date.today()
    for month, day in _QUARTER_ENDS:
        end = date(today.year, month, day)
        if end > today:
            break
    else:
        end = date(today.year + 1, *_QUARTER_ENDS[0])
    # Quarter number counted from the company's own fiscal year start,
    # not the calendar - most of this universe closes in March.
    quarter = ((end.month - fy_month - 1) % 12) // 3 + 1
    return end.isoformat(), f"Q{quarter}"


def _next_checkpoint(meta: dict[str, Any], signal_type: str) -> dict[str, Any] | None:
    """What will next show whether this signal held, and when.

    The company's own next results come first: they are the direct test
    of a forecast, a progress reading or a capacity commitment, and a
    reader asking "when will I know" means this company before anyone
    else. A linked US name's earnings is the fallback, because the
    read-through is a second-order claim.

    An industry reading belongs to no company, so its checkpoint is the
    next monthly SEAJ release.
    """
    if signal_type == "industry":
        # SEAJ publishes monthly, so the next release is the next read
        # of the same series - the only thing that confirms or revises
        # this month's figure. The release day is not scheduled
        # publicly, so only the period is named.
        return {
            "event": "Next SEAJ monthly billings release",
            "date": None,
            "periodEnd": None,
            "supports": "The next month continuing the same direction",
            "weakens": "The next month reverting to the recent average",
        }

    ticker = _JAPAN_TICKER_BY_CODE.get(meta.get("code") or "")
    if ticker:
        period = _next_quarter_end(ticker.get("fiscal_year_end"))
        if period:
            end_iso, quarter = period
            return {
                "event": f"{ticker['company']} {quarter} results",
                # No filed announcement date exists for these companies
                # - see _next_quarter_end.
                "date": None,
                "periodEnd": end_iso,
                "supports": "The company's own results confirming it",
                "weakens": "Results showing no change",
            }

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
