"""CHINA_COMPANIES - the single source of truth for what this service
knows about the tracked Chinese universe.

One record per company, keyed by the exchange code an article carries
in ``metadata.code``. Three separate structures used to hold these
facts - a read-through table, a set of platform codes and a set of
accelerator codes - all keyed by the SAME code and all maintained by
hand. Adding a company meant up to three edits, and a missed one
failed silently in the worst way available: a new platform absent from
``_C5_PLATFORM_CODES`` makes C5 never fire for it, with no error and
no empty result to notice - the signal type simply does not apply.
That is the same shape as the cninfo org_id bug this domain already
paid for. There is now one table, and the three views below are
DERIVED from it rather than maintained beside it.

This mirrors what japan_companies.py did for the same reason, after
the same problem - see its docstring.

STATIC FOR NOW - RESEARCH-UNIVERSE BECOMES THE SOURCE LATER.
    Every link here is an analyst judgment, not a filed fact: no
    issuer discloses "our gains come out of Applied Materials". They
    are transcribed from the China Signals spec's own read-through
    tables. research-universe is the intended owner, and this is the
    intended migration unit - but the catalogue cannot express these
    yet. Its customers table carries only SUPPLY relationships
    (customer/distributor/licensee/investee/partner/user_base), none
    of which describes competition, and it has no direction column.
    Columns for both were added on 2026-10-06 and reverted the same
    day: the data is not a customer relationship, and a pair's
    direction is not even a property of the pair (see Baidu below).

WHAT `direction` MEANS
    Which way the US name moves on this company's GOOD news.
    ``opposite`` is the common case here and the defining property of
    this market - Naura winning a tool slot is revenue leaving Applied
    Materials. ``same`` is the supply case: SMIC's capex IS Applied
    Materials' revenue.

WHY direction IS PER (COMPANY, COUNTERPARTY, SIGNAL TYPE)
    Not per pair. SMIC competes with TSMC on every signal type but
    buys from AMAT only when it spends (C3/C5). Baidu is the clearest
    case: ``same`` toward Nvidia under C5 because it buys GPUs, and
    ``opposite`` under C4 because its own accelerator programme
    displaces them. The same pair, opposite signs, decided by the
    signal type - which is why ``categories`` exists and why a flat
    company->ticker mapping cannot express this.

TICKERS ARE NOT VALIDATED AGAINST research-universe, and one is known
absent. Checked 2026-10-06: 21 of the 22 US names referenced here
exist there; HPQ (HP Inc) does not exist under any ticker or name, so
Lenovo's read-through to it resolves to nothing downstream. Two more
are stored under names that do not match the company the spec means -
HPE is "Juniper Networks (HPE)" and INTC is "Intel (Silicon
Photonics)" - which is a catalogue problem, not one this table can fix
by renaming. The ticker is kept anyway: a read-through states which
company the signal reaches, and dropping HPQ because the catalogue has
not got to it yet would silently narrow the signal rather than surface
the gap. A consumer joining these to research-universe should expect a
miss and say so, not assume the link is wrong.

`signal_roles` DRIVES WHICH CLASSIFIERS APPLY
    ``platform``     C5 reads its capital expenditure disclosure.
    ``accelerator``  C4 reads its product milestones.
    A company with neither is still fully tracked - most are, and
    every company participates in C1/C2/C3/C6/C7 regardless.
"""
from typing import Any

# `ALL` as the category means the link holds for every signal type.
CHINA_COMPANIES: dict[str, dict[str, Any]] = {
    # --- Equipment: the substitution front line -----------------------
    "002371": {
        "company": "Naura Technology",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688012": {
        "company": "Amec",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["LRCX", "AMAT"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688082": {
        "company": "ACM Research Shanghai",
        "signal_roles": set(),
        "read_through": [
            # Its parent is US-listed, so the SAME-direction case. This
            # is the module's own control: if a run ever emits OPPOSITE
            # for 688082 -> ACMR, the direction logic is broken.
            {"tickers": ["ACMR"], "direction": "same", "categories": "ALL"},
            {"tickers": ["AMAT", "LRCX"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688072": {
        "company": "Piotech",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT", "LRCX"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688120": {
        "company": "Hwatsing Technology",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    # --- Foundry and memory -------------------------------------------
    "688981": {
        "company": "SMIC",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["TSM", "UMC", "GFS"], "direction": "opposite",
             "categories": "ALL"},
            # It BUYS their tools, so its capex is their revenue.
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "same",
             "categories": ["C3", "C5"]},
        ],
    },
    "688347": {
        "company": "Hua Hong Semiconductor",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["UMC", "GFS"], "direction": "opposite",
             "categories": "ALL"},
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "same",
             "categories": ["C3", "C5"]},
        ],
    },
    "603986": {
        "company": "GigaDevice",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MU", "MCHP"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    # --- Domestic accelerators ----------------------------------------
    "688256": {
        "company": "Cambricon",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["NVDA", "AMD"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688041": {
        "company": "Hygon Information Technology",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["INTC", "AMD", "NVDA"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "688047": {
        "company": "Loongson Technology",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["INTC", "AMD"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    # --- Servers, systems, components ---------------------------------
    "000977": {
        "company": "Inspur Electronic Information",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["SMCI", "DELL", "HPE"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "00992": {
        "company": "Lenovo",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["DELL", "HPQ", "SMCI"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "002475": {
        "company": "Luxshare Precision",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["APH", "TEL", "JBL", "FLEX"], "direction": "opposite",
             "categories": "ALL"},
        ],
    },
    "000725": {
        "company": "BOE Technology",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["GLW"], "direction": "opposite", "categories": "ALL"},
            {"tickers": ["AMAT"], "direction": "same",
             "categories": ["C3", "C5"]},
        ],
    },
    # --- Demand side: the platforms -----------------------------------
    # Their capex IS the US sellers' revenue, so SAME, not opposite.
    "09988": {
        "company": "Alibaba Group",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA", "AMD", "SMCI"], "direction": "same",
             "categories": "ALL"},
        ],
    },
    "00700": {
        "company": "Tencent",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA", "AMD"], "direction": "same",
             "categories": "ALL"},
        ],
    },
    "09888": {
        "company": "Baidu",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA"], "direction": "same",
             "categories": ["C5"]},
            # Its own accelerator programme reads the other way.
            {"tickers": ["NVDA"], "direction": "opposite",
             "categories": ["C4"]},
        ],
    },
    # --- Materials and the retaliation lever --------------------------
    # The spec calls these MIXED, and they are the only rows where the
    # category genuinely flips the sign: a Chinese producer shipping
    # more is competitive pressure on MP (C2), while a Chinese export
    # restriction makes MP one of the few non-Chinese sources (C1).
    "600111": {
        "company": "China Northern Rare Earth",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MP"], "direction": "opposite",
             "categories": ["C2", "C3", "C6"]},
            {"tickers": ["MP"], "direction": "same",
             "categories": ["C1", "C7"]},
        ],
    },
    "300748": {
        "company": "JL MAG Rare-Earth",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MP"], "direction": "opposite",
             "categories": ["C2", "C3", "C6"]},
            {"tickers": ["MP"], "direction": "same",
             "categories": ["C1", "C7"]},
        ],
    },
}


def codes_with_role(role: str) -> set[str]:
    """Codes carrying one role, e.g. "platform" or "accelerator".

    Derived from CHINA_COMPANIES rather than listed separately, so a
    company added to the table above cannot be missed by the
    classifier that needs it - the failure this module was written to
    remove.
    """
    return {code for code, c in CHINA_COMPANIES.items()
            if role in c["signal_roles"]}


def read_through_for(code: str | None,
                     signal_type: str | None) -> list[dict[str, Any]]:
    """The US names one Chinese company's signal reads to.

    Returns a list of ``{"tickers": [...], "direction": "same"|"opposite"}``
    for the given signal category, or [] when the company has no link
    or none applies to this category.
    """
    if not code:
        return []
    out: list[dict[str, Any]] = []
    for link in CHINA_COMPANIES.get(code, {}).get("read_through", []):
        categories = link["categories"]
        if categories != "ALL" and signal_type not in categories:
            continue
        out.append({"tickers": list(link["tickers"]),
                    "direction": link["direction"]})
    return out
