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

from datetime import date
from typing import Any

from pipeline.japan_companies import JAPAN_TICKER_UNIVERSE

# ---------------------------------------------------------------- #
# Card formatting helpers.                                          #
#                                                                   #
# These lived in japan_signal_summary.py until the Japan prose       #
# summary was removed - they were written there because the summary  #
# needed them first, but every real consumer is a card field, so     #
# they belong with the card layer.                                   #
# ---------------------------------------------------------------- #


def _age_hours(row: dict[str, Any]) -> float | None:
    """Hours between the row's own `published` and now (UTC) - same real
    computation korea_signal_summary.py's own _age_hours already does.
    Returns None for a J3 row (published is always null - see
    classify_missing_revision's own result shape, an absence has no real
    publication timestamp to compute an age from).
    """
    from datetime import datetime, timezone

    published = row.get("published")
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)


def _format_pct(value: float | None, signed: bool = False) -> str | None:
    """Render a percentage as the stored figure states it, dropping a
    trailing zero decimal: 53.3% stays 53.3%, 27.6% stays 27.6%, 40.0%
    reads 40%. ``signed`` prefixes a + on a positive value, for a field
    where the direction is part of the number.
    """
    if value is None:
        return None
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    if signed and value > 0:
        text = f"+{text}"
    return f"{text}%"


def _format_jpy_millions(value: float | None) -> str | None:
    """Render a JPY-millions figure (the unit every irbank_financials
    table stores) at the scale a reader uses: ¥138bn, ¥34.5bn, ¥1.4tn.

    Keeps a decimal place where the real figure has one, so a stored
    34500 reads as ¥34.5bn rather than being rounded to ¥34bn - these
    are the filing's own reported figures, and a reader comparing them
    against the filing should see the same number it states.
    """
    if value is None:
        return None
    millions = abs(float(value))
    sign = "-" if value < 0 else ""
    if millions >= 1_000_000:
        scaled, unit = millions / 1_000_000, "tn"
    elif millions >= 1_000:
        scaled, unit = millions / 1_000, "bn"
    else:
        scaled, unit = millions, "m"
    # Drop the decimal only when it is genuinely zero.
    text = f"{scaled:.1f}".rstrip("0").rstrip(".")
    return f"{sign}¥{text}{unit}"


# How far behind or ahead of schedule a company must be before the
# reading means anything. A quarter does not land exactly on its share
# of the year - results cluster around filing dates and seasonal demand
# - so a few points either side of the elapsed year is ordinary. 5
# points is the width of that ordinary band: inside it the company is
# on track, outside it the gap is the story.
_PROGRESS_ON_TRACK_BAND_PTS = 5.0


def signal_implication(meta: dict[str, Any]) -> str:
    """Return Positive / Negative / Mixed / Unclear for one classified row.

    Sets the colour of the headline number on a trading screen, so a
    direction is only claimed where the filing's own figures establish
    one. Each branch compares two real stored values; nothing is
    inferred from the kind of event, because a buyback or a capacity
    investment carries no stated direction however it is conventionally
    read.
    """
    # A yen-denominated forecast revision: the sign of the change is the
    # direction the company moved its own guidance.
    pct = meta.get("operating_profit_pct_change")
    if pct is not None:
        if pct > 0:
            return "Positive"
        if pct < 0:
            return "Negative"
        return "Mixed"

    # Margin-percentage guidance (see _MARGIN_BASED_CODES in the
    # classifier): there is no previous forecast to measure against, but
    # the filing states the same period's prior-year actual, which is the
    # comparison the company itself presents.
    revised = meta.get("margin_revised_pct")
    reference = meta.get("margin_reference_prior_year_actual_pct")
    if revised is not None and reference is not None:
        if revised > reference:
            return "Positive"
        if revised < reference:
            return "Negative"
        return "Mixed"

    # Results against forecast: progress toward the full-year target
    # against how much of the year has actually gone.
    progress = meta.get("progress_pct")
    elapsed = meta.get("fiscal_year_elapsed_pct")
    if progress is not None and elapsed is not None:
        gap = progress - elapsed
        if gap > _PROGRESS_ON_TRACK_BAND_PTS:
            return "Positive"
        if gap < -_PROGRESS_ON_TRACK_BAND_PTS:
            return "Negative"
        return "Mixed"

    # The national equipment reading: its own year-on-year sign.
    yoy = meta.get("yoy_pct")
    if yoy is not None:
        if yoy > 0:
            return "Positive"
        if yoy < 0:
            return "Negative"
        return "Mixed"

    # Ownership, buyback, capacity, press and a missing announcement
    # state no direction of their own. A holder crossing 5% may be
    # accumulating or unwinding; a buyback may signal confidence or
    # absent opportunity. Claiming a colour here would assert something
    # the filing does not.
    return "Unclear"


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

_JAPAN_TICKER_BY_CODE = {t["code"]: t for t in JAPAN_TICKER_UNIVERSE}


def _is_progress_row(meta: dict[str, Any]) -> bool:
    return meta.get("progress_pct") is not None


def _usable_progress_baseline(meta: dict[str, Any]) -> float | None:
    """The company's usual pace, where it is sound enough to judge by.

    Rejected in three cases, each of which otherwise produces a card
    that contradicts itself:

    - the habit is untrusted (too few fiscal years behind it) - the
      row's own `signal` already says there is not enough history, so
      ranking the company "ahead" against that same median says the
      opposite in the same card;
    - the stored median IS this reading, meaning the history is this
      one row and the comparison is with itself;
    - no median stored at all.

    The caller falls back to the elapsed share of the fiscal year,
    which needs no history to be true.
    """
    typical = meta.get("progress_habit_typical_pct")
    if typical is None:
        return None
    if meta.get("progress_habit_is_trusted") is False:
        return None
    if typical == meta.get("progress_pct"):
        return None
    return typical


def _target_period_label(meta: dict[str, Any]) -> str:
    """"full-year" or "half-year", matching what the filing measured
    progress against.

    The classifier stores the detected target period; a filing issuing
    fresh H1 guidance alongside Q1 results measures against that, not
    against the full year.

    Falls back to full-year when nothing is stored - that is both the
    common case and what the rest of the card says, so an unlabelled
    row stays internally consistent rather than claiming a half-year
    target the filing never mentioned.
    """
    return {
        "half_year": "half-year",
        "quarter": "quarterly",
        "full_year": "full-year",
    }.get(meta.get("target_period_type") or "", "full-year")


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


# Present-tense verbs Japanese press headlines open with, mapped to the
# past tense a card reports in. Headlines are written in a running
# present ("develops", "achieves"); every other signal type's headline
# on this card is past tense ("Raised", "Announced", "Filed"), so a
# press row in the present reads as a different kind of object.
_PRESS_VERB_PAST = {
    "achieves": "Achieved", "adopts": "Adopted", "acquires": "Acquired",
    "announces": "Announced", "begins": "Began", "boosts": "Boosted",
    "builds": "Built", "completes": "Completed", "cuts": "Cut",
    "delays": "Delayed", "develops": "Developed", "expands": "Expanded",
    "invests": "Invested", "launches": "Launched", "opens": "Opened",
    "plans": "Planned", "raises": "Raised", "reports": "Reported",
    "resumes": "Resumed", "secures": "Secured", "sells": "Sold",
    "ships": "Shipped", "signs": "Signed", "starts": "Started",
    "suspends": "Suspended", "unveils": "Unveiled", "wins": "Won",
}

# Lead clauses that are promotional framing rather than the news. A
# headline built as "{boast}, {what actually happened}" buries the
# checkable half; the card has one line, so spend it on the second.
_PRESS_FILLER_CLAUSE_MARKERS = (
    "first success", "world's first", "world’s first", "industry first",
    "industry's first", "industry’s first", "japan's first", "japan’s first",
    "successfully", "achieves success",
)


def _press_source_label(meta: dict[str, Any]) -> str | None:
    """The publication, as a reader would name it.

    Only the domain is stored on the row, so derive the masthead from
    it rather than printing "newswitch.jp" on the card.
    """
    domain = (meta.get("publication_domain") or "").lower().strip()
    if not domain:
        return None
    host = domain.split("/")[0].removeprefix("www.")
    name = host.split(".")[0]
    known = {
        "newswitch": "Newswitch", "nikkei": "Nikkei", "jiji": "Jiji",
        "reuters": "Reuters", "kyodo": "Kyodo", "monoist": "MONOist",
        "itmedia": "MONOist", "asahi": "Asahi", "yomiuri": "Yomiuri",
        "sankei": "Sankei", "mainichi": "Mainichi", "toyokeizai": "Toyo Keizai",
        "diamond": "Diamond", "bloomberg": "Bloomberg",
    }
    return known.get(name) or name.capitalize()


def _press_subject(meta: dict[str, Any]) -> str | None:
    """What the press report is about, with the company name and the
    stored title's own prefix stripped off.

    Shared by the headline and the checkpoint so the two name the same
    thing - "the 12-inch SiC substrate" in both, rather than the card
    describing one story and its checkpoint another.
    """
    headline = meta.get("translated_title")
    if not headline:
        return None
    subject = (headline.split(": ", 1)[-1] if ": " in headline else headline).strip()
    company = meta.get("company") or ""
    head = company.split()[0] if company else ""
    if len(head) >= 3 and subject.lower().startswith(head.lower()):
        subject = subject[len(head):].lstrip(" ,-–—'’s")
    return subject or None


def _press_claim_noun(meta: dict[str, Any]) -> str | None:
    """The thing the report claims, as a noun phrase a sentence can
    take: "the 12-inch SiC substrate".

    The checkpoint reads "{company} confirms the {noun}", so it needs
    the object of the headline rather than its verb clause. Quoted
    text is the reliable marker - Japanese press quotes the product or
    technology being announced - and the last clause is the fallback,
    since the news sits after any promotional lead.
    """
    subject = _press_subject(meta)
    if not subject:
        return None

    # A quoted product or technology name is exactly this noun.
    for open_q, close_q in (("“", "”"), ("「", "」"), ('"', '"')):
        if open_q in subject and close_q in subject.split(open_q, 1)[1]:
            quoted = subject.split(open_q, 1)[1].split(close_q, 1)[0].strip()
            if quoted:
                return quoted

    # Otherwise the clause after any promotional lead, with its verb
    # dropped so what remains is the object.
    clause = subject.rsplit(",", 1)[-1].strip() if "," in subject else subject
    words = clause.split()
    if words and words[0].lower().rstrip("s") in {
        w.rstrip("s") for w in _PRESS_VERB_PAST
    }:
        words = words[1:]
    noun = " ".join(words).strip(" .“”\"'")
    return noun or None


def _press_headline(subject: str, meta: dict[str, Any]) -> str:
    """Reshape a translated press headline into a card line.

    Three steps, each guarded so an unrecognised shape passes through
    rather than being mangled: drop a promotional lead clause, put the
    verb in the past tense the rest of the card uses, and attribute the
    publication, since a press row is somebody's reporting rather than
    the company's own filing.
    """
    # A promotional lead clause before a comma, with real news after it.
    if "," in subject:
        lead, rest = subject.split(",", 1)
        rest = rest.strip()
        if rest and any(m in lead.lower() for m in _PRESS_FILLER_CLAUSE_MARKERS):
            subject = rest

    # Japanese headlines bracket a product name in quotes as a matter of
    # typography, not emphasis; carried into English they read as scare
    # quotes. Drop them and give the noun its article instead.
    for open_q, close_q in (("“", "”"), ("「", "」"), ('"', '"')):
        if open_q in subject and close_q in subject.split(open_q, 1)[1]:
            before, rest = subject.split(open_q, 1)
            quoted, after = rest.split(close_q, 1)
            quoted = quoted.strip()
            if quoted:
                article = "" if before.rstrip().endswith((" a", " an", " the")) else "a "
                subject = f"{before}{article}{quoted}{after}"
            break

    words = subject.split()
    if words:
        first = words[0].lower().strip('"“”')
        past = _PRESS_VERB_PAST.get(first)
        if past:
            words[0] = past
            subject = " ".join(words)
        elif subject[0].islower():
            subject = subject[0].upper() + subject[1:]

    source = _press_source_label(meta)
    if source:
        return f"{subject} ({source} report)"
    return subject


def _headline(signal_type: str, meta: dict[str, Any]) -> str:
    """Verb-first, no company name - the card prints the name separately."""
    if signal_type == "forecast":
        pct = meta.get("operating_profit_pct_change")
        if pct is not None:
            # A filing revises sales, operating, ordinary and net income
            # independently, so operating profit is often reaffirmed
            # while other lines move. That is not a cut - and "Cut" is
            # what a bare `pct > 0` test produces at exactly 0.0.
            if pct == 0:
                return "Left full-year profit forecast unchanged"
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
        elapsed = meta.get("fiscal_year_elapsed_pct")
        baseline = _usable_progress_baseline(meta)
        if baseline is None:
            baseline = elapsed
        # Name the period the progress is actually measured against. A
        # filing can report Q1 actuals against fresh H1 guidance, and
        # the classifier records which - saying "full-year" regardless
        # contradicts the signal sentence built from the same field.
        target = _target_period_label(meta)
        if progress is not None and baseline is not None:
            return (f"Ran ahead of its {target} target" if progress >= baseline
                    else f"Ran behind its {target} target")
        return f"Reported results against {target} target"
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
            if subject:
                return _press_headline(subject, meta)
            return "Press reported a checkable fact"
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
        # The holding percentage is already the card's big number, so
        # repeating it here says nothing. Show what the stake is worth
        # in shares where the filing gives it, otherwise nothing.
        return None
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
        # Measure against the company's own usual pace where one exists
        # and is sound: a company that habitually books 60% of its year
        # by Q2 is not "ahead" at 55% just because only 50% of the year
        # has passed. The elapsed year is the fallback - see
        # _usable_progress_baseline for when the stored pace is refused.
        typical = _usable_progress_baseline(meta)
        if progress is not None and typical is not None:
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
    # See _usable_progress_baseline: an untrusted or self-referential
    # median is not something to rank the company against.
    typical = _usable_progress_baseline(meta)
    if progress is not None and typical is not None:
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
        # A High press row with no caveat reads as unexplained: the
        # reader sees a news report graded like a filing and has no
        # way to tell why. Say which of the two it is - a company
        # announcement the press picked up, or a report the publication
        # stands behind ahead of any disclosure.
        company = meta.get("company")
        source = _press_source_label(meta)
        if company and source:
            return (f"{company} announced this itself; {source} is reporting "
                    f"it after the fact.")
        return "Reported after the company's own announcement, not ahead of it."
    if signal_type == "disclosure":
        # The English-filing fact belongs to `unusual`, which is the
        # field asking what is notable about this row. It used to be
        # repeated here and in the classifier's reason as well, so one
        # fact filled three fields on the same card.
        return ("Judged from the filing's own title - the disclosure's full terms are "
                "in the document itself.")
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
    """Why this row was classified the way it was.

    Reads the rule that actually fired rather than always describing
    the size bar: a reversal and a profit-to-loss swing are signals
    regardless of size, so explaining a size threshold beside them
    contradicts the badge - a +6.2% move marked High next to "its own
    bar is 30.9%" reads as a mistake.
    """
    code = meta.get("signal_reason_code") or ""

    if code.startswith("reverses_direction"):
        # The direction of the EARLIER revision this one reverses, recorded by
        # the classifier when the rule fired. habit_typical_direction is the
        # company's usual direction across its whole history, which is a
        # different thing and gets the wording backwards whenever a habitual
        # raiser cuts (or vice versa).
        earlier = meta.get("reversed_direction")
        if earlier not in ("raise", "cut"):
            return ("Reversed its earlier revision within the same fiscal year - "
                    "a reversal counts whatever its size.")
        return (f"Reversed an earlier {earlier} within the same fiscal year - "
                f"a reversal counts whatever its size.")
    if code.startswith("profit_loss_swing"):
        return ("Moved between forecasting a profit and a loss - a swing counts "
                "whatever its size.")
    if code.startswith("rare_reviser"):
        return ("This company revises less than once a year, so any revision "
                "at all is notable.")
    if code.startswith("currency") or "currency" in code:
        return "Attributed to currency or accounting only, so not a change in trade."

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
    # An absence of coverage is not a recorded figure - the field is
    # omitted rather than listed on every row that has none.
    found = meta.get("english_coverage_found")
    if found:
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


def _source_url(meta: dict[str, Any], source_id: str | None,
                published: str | None = None) -> str | None:
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
        # irbank-buyback://{code}/{doc_id}. IRBANK sources these from
        # EDINET and keeps EDINET's own document id, so the row can
        # link to the filing itself rather than to the company's
        # buyback list, where a reader would have to find this
        # programme among all the others. Same PDF endpoint the EDINET
        # branch above uses - the document is served by doc id alone.
        doc_id = meta.get("doc_id") or source_id.rsplit("/", 1)[-1]
        if doc_id.startswith("S1") and _edinet_still_serves(published):
            return f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_id}.pdf"
        # Outside EDINET's retention window the filing PDF is gone, so
        # the company's buyback list is the only page that still shows
        # this programme. A dead link would be worse than a broad one.
        code = meta.get("code")
        return f"https://irbank.net/{code}/buyback" if code else None

    return None


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


# How old an event can be and still have a checkpoint worth showing.
# "When you'll know" answers a question about something still open: a
# forecast cut from 2019 was settled by results published years ago,
# and pointing at the next quarter instead tells a reader nothing.
# 180 days spans two reporting cycles, so a recent event is still
# covered by the results that will test it.
_CHECKPOINT_MAX_EVENT_AGE_DAYS = 180

# The oldest filing date EDINET was observed still to serve a PDF for.
# Not a published figure - measured by requesting every stored buyback
# filing's PDF on 2026-10-01: everything filed on or after 2022-05-10
# returned a document, and the newest 404 was 2021-12-07, so the real
# edge sits between those two dates.
#
# Held as a DATE rather than an age in days for two reasons: an age is
# fractional, so a day-count bound rejected the 2022-05-10 filing it
# was measured from; and EDINET's own rule is a retention period, which
# means this boundary rolls forward over time rather than staying put.
# Re-probe periodically and move this date forward - stale here means
# a few rows fall back to the IR Bank list page, which is safe, while
# moving it too far forward would hand out 404s.
_EDINET_OLDEST_SERVED_FILING_DATE = date(2022, 5, 10)


def _event_age_days(published: str | None) -> float | None:
    """Age of an event in days, or None when it carries no usable date."""
    from datetime import datetime, timezone
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _event_is_recent(published: str | None) -> bool:
    """True when an event is new enough that its outcome is still open."""
    age_days = _event_age_days(published)
    return age_days is not None and age_days <= _CHECKPOINT_MAX_EVENT_AGE_DAYS


def _edinet_still_serves(published: str | None) -> bool:
    """True when EDINET should still hold this filing's PDF.

    EDINET drops documents from its public store after a retention
    window, and a request for a dropped one returns 404 rather than a
    redirect to anything useful. Measured against the stored buyback
    filings on 2026-10-01: every document filed on or after 2022-05-10
    was served, every one before it was gone.

    Compares DATES, not elapsed seconds. An age in days is fractional
    (a filing stamped midnight is 1605.8 days old by late afternoon),
    so a day-count bound rejected the very boundary filing it was
    measured from - and the window slid shut by one more day every day
    that passed.

    The cutoff is therefore a fixed date, which is also what EDINET's
    rule actually is. It will drift the other way as the real window
    rolls forward, so it is deliberately conservative: a row inside it
    is one whose PDF was observed to exist. Refresh it by re-probing
    (see the note on _EDINET_OLDEST_SERVED_FILING_DATE).

    An undated row is treated as too old to link: a wrong link costs
    more than a broad one.
    """
    from datetime import datetime
    if not published:
        return False
    try:
        dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.date() >= _EDINET_OLDEST_SERVED_FILING_DATE


def _next_seaj_release() -> str:
    """The next SEAJ monthly billings release date.

    SEAJ publishes around the 20th of each month, covering the month
    before. The day is a pattern rather than a published schedule, so
    this is the expected date - close enough to tell a reader when to
    look, and the only cadence information the source gives.
    """
    from datetime import date
    today = date.today()
    if today.day < 20:
        return date(today.year, today.month, 20).isoformat()
    year = today.year + (today.month == 12)
    month = 1 if today.month == 12 else today.month + 1
    return date(year, month, 20).isoformat()


def _format_share_count(shares: Any) -> str | None:
    """A share count as a trader writes it: 30,000,000 -> "30M"."""
    try:
        n = float(shares)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 1_000_000:
        millions = n / 1_000_000
        return f"{millions:.0f}M" if millions >= 10 or millions.is_integer() else f"{millions:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:.0f}"


def _checkpoint_tests(
    signal_type: str, meta: dict[str, Any], quarter: str | None,
) -> tuple[str | None, str | None]:
    """What the trader will actually see at the checkpoint, and what
    would undercut it.

    Each pair names this event's own figure - the revised forecast, the
    programme size, the stake - and the same subject the event has, so
    the two lines say something only this row could say. A generic
    "results confirming it" is true of every row and worth nothing to
    a reader deciding whether to act.

    Returns (None, None) where the row carries no figure specific
    enough to test; the card then shows only the event line.
    """
    # The quarter whose results will test this. Without one the
    # sentences cannot say WHEN the trader sees it, so they fall back
    # to "results".
    at = f"{quarter} results" if quarter else "results"

    if signal_type == "forecast":
        pct = meta.get("operating_profit_pct_change")
        revised = _format_jpy_millions(meta.get("operating_profit_revised"))
        if revised is None or pct is None:
            return (None, None)
        if pct > 0:
            return (f"{at} track at or above the raised {revised} forecast",
                    f"{at} fall short of {revised}, or the raise is cut back")
        if pct < 0:
            return (f"{at} land at or below the cut {revised} forecast",
                    f"{at} beat {revised}, suggesting the cut was too cautious")
        return (f"{at} confirm the reaffirmed {revised} forecast",
                f"{at} force a revision away from {revised}")

    if signal_type == "progress":
        # Measured against whichever baseline the card itself used, so
        # the checkpoint tests the same claim the metric made.
        where = quarter or "The next quarter"
        if _usable_progress_baseline(meta) is not None:
            return (f"{where} progress stays ahead of its usual pace",
                    f"{where} progress falls back to its usual pace")
        return (f"{where} progress stays ahead of the share of the year elapsed",
                f"{where} progress falls back to the share of the year elapsed")

    if signal_type == "capacity":
        amount = _format_jpy_millions(meta.get("capex_investment_jpy"))
        if amount:
            return (f"{at} disclose the {amount} investment or raise capex guidance",
                    f"The {amount} investment deferred, scaled back or not mentioned")
        return (f"{at} disclose the investment size or raise capex guidance",
                "Investment deferred, scaled back or not mentioned")

    if signal_type == "buyback":
        size = _format_share_count(meta.get("buyback_program_limit_shares"))
        if size:
            return (f"{at} report shares repurchased under the {size} programme",
                    f"{at} show little or none of the {size} programme used")
        return (f"{at} report shares repurchased under the programme",
                f"{at} show little of the programme used")

    if signal_type == "ownership":
        holder = _short_holder_name(
            meta.get("translated_filer_name") or meta.get("filer_name")
        )
        pct = _format_pct(meta.get("holding_pct"))
        if holder and pct:
            return (f"{holder} files a change report raising its {pct} stake",
                    f"{holder}'s stake falls back below 5%")
        if holder:
            return (f"{holder} files a change report raising its stake",
                    f"{holder}'s stake falls back below 5%")
        return (None, None)

    if signal_type == "press":
        company = meta.get("company")
        if not company:
            return (None, None)
        thing = _press_claim_noun(meta)
        # An unconfirmed report is tested by whether the company
        # confirms it. An already-announced one is not - there is
        # nothing left to confirm, so the test is whether it turns
        # into orders or capacity, which is the part a trader is
        # actually waiting on.
        if meta.get("unconfirmed"):
            if thing:
                return (f"{company} confirms the {thing} in a filing or at {at}",
                        f"No company confirmation by {at}")
            return (f"{company} confirms the report in a filing or at {at}",
                    f"No company confirmation by {at}")
        if thing:
            return (f"{at} cite {thing} orders or capacity",
                    f"No mention of {thing} at {at}")
        return (f"{at} cite the reported business in orders or capacity",
                f"No mention of it at {at}")

    if signal_type == "disclosure":
        return (f"{at} show the disclosed action in earnings or guidance",
                f"{at} show no effect from the disclosed action")

    if signal_type == "missing":
        return (f"A forecast announcement arrives with {at}",
                f"{at} arrive with no forecast announcement")

    if signal_type == "watching":
        company = meta.get("company")
        if company:
            return (f"{company} files a forecast revision with {at}",
                    "Another quarter passes with no revision")
        return (f"A forecast revision arrives with {at}",
                "Another quarter passes with no revision")

    return (None, None)


def _next_seaj_period_label() -> str:
    """The month the next SEAJ release will cover.

    SEAJ publishes around the 20th with the previous month's figures,
    so the next release reports the month before the one it lands in.
    """
    from datetime import date
    release = date.fromisoformat(_next_seaj_release())
    year = release.year - (release.month == 1)
    month = 12 if release.month == 1 else release.month - 1
    return date(year, month, 1).strftime("%B")


def _next_checkpoint(meta: dict[str, Any], signal_type: str,
                     published: str | None = None) -> dict[str, Any] | None:
    """What will next show whether this signal held, and when.

    The company's own next results come first: they are the direct test
    of a forecast, a progress reading or a capacity commitment, and a
    reader asking "when will I know" means this company before anyone
    else. A linked US name's earnings is the fallback, because the
    read-through is a second-order claim.

    An industry reading belongs to no company, so its checkpoint is the
    next monthly SEAJ release.
    """
    # An event whose results are already public has nothing left to
    # confirm it.
    if not _event_is_recent(published):
        return None

    if signal_type == "industry":
        # SEAJ publishes monthly, so the next release is the next read
        # of the same series - the only thing that confirms or revises
        # this month's figure. The release day is not scheduled
        # publicly, so only the period is named.
        baseline = _format_pct(meta.get("industry_baseline_avg_yoy_pct"))
        month = _next_seaj_period_label()
        if baseline:
            supports = f"{month} billings stay well above the {baseline} average"
            weakens = f"{month} billings fall back toward the {baseline} average"
        else:
            supports = f"{month} billings continue in the same direction"
            weakens = f"{month} billings revert to the recent average"
        return {
            "event": "Next SEAJ monthly billings release",
            "date": _next_seaj_release(),
            "periodEnd": None,
            "supports": supports,
            "weakens": weakens,
        }

    ticker = _JAPAN_TICKER_BY_CODE.get(meta.get("code") or "")
    if ticker:
        period = _next_quarter_end(ticker.get("fiscal_year_end"))
        if period:
            end_iso, quarter = period
            supports, weakens = _checkpoint_tests(signal_type, meta, quarter)
            return {
                "event": f"{ticker['company']} {quarter} results",
                # No filed announcement date exists for these companies
                # - see _next_quarter_end.
                "date": None,
                "periodEnd": end_iso,
                "supports": supports,
                "weakens": weakens,
            }

    # No read-through fallback. It only ran for a company absent from
    # _JAPAN_TICKER_BY_CODE, and every tracked company is in it, so the
    # branch above always returned first - unreachable since it was
    # written. A row with no checkpoint returns None.
    return None


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

    # An empty string is not a reason - the filing had a 理由 heading
    # with nothing under it. Send null so the card omits the quote
    # rather than rendering an empty one.
    company_reason = (meta.get("translated_reason") or meta.get("reason") or "").strip() or None

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
        "sourceUrl": _source_url(meta, row.get("source_id"), row.get("published")),
        "nextCheckpoint": _next_checkpoint(meta, signal_type, row.get("published")),
        "evidence": _evidence(meta),
        # Which of this company's own disclosed customers the event's
        # text actually names - computed at classification time and
        # stored, so this just carries the stored value through rather
        # than recomputing it per request.
        #
        # An empty list is the common and correct answer: a forecast
        # revision states figures and names nobody. Only 4 of 394 real
        # rows name a customer, so a consumer must render [] as "no
        # customer named", never as missing data.
        "entities": row.get("entities") or [],
    }
