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
        "native_name": "北方华创",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688012": {
        "company": "Amec",
        "native_name": "中微公司",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["LRCX", "AMAT"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688082": {
        "company": "ACM Research Shanghai",
        "native_name": "盛美上海",
        "signal_roles": set(),
        "read_through": [
            # Its parent is US-listed, so the SAME-direction case. This
            # is the module's own control: if a run ever emits OPPOSITE
            # for 688082 -> ACMR, the direction logic is broken.
            {"tickers": ["ACMR"], "direction": "same", "relationship": "parent", "categories": "ALL"},
            {"tickers": ["AMAT", "LRCX"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688072": {
        "company": "Piotech",
        "native_name": "拓荆科技",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT", "LRCX"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688120": {
        "company": "Hwatsing Technology",
        "native_name": "华海清科",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["AMAT"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    # --- Foundry and memory -------------------------------------------
    "688981": {
        "company": "SMIC",
        "native_name": "中芯国际",
        "hk_code": "00981",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["TSM", "UMC", "GFS"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
            # It BUYS their tools, so its capex is their revenue.
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "same",
             "relationship": "customer", "categories": ["C3", "C5"]},
        ],
    },
    "688347": {
        "company": "Hua Hong Semiconductor",
        "native_name": "华虹宏力",
        "hk_code": "01347",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["UMC", "GFS"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
            {"tickers": ["AMAT", "LRCX", "KLAC"], "direction": "same",
             "relationship": "customer", "categories": ["C3", "C5"]},
        ],
    },
    "603986": {
        "company": "GigaDevice",
        "native_name": "兆易创新",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MU", "MCHP"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    # --- Domestic accelerators ----------------------------------------
    "688256": {
        "company": "Cambricon",
        "native_name": "寒武纪",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["NVDA", "AMD"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688041": {
        "company": "Hygon Information Technology",
        "native_name": "海光信息",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["INTC", "AMD", "NVDA"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "688047": {
        "company": "Loongson Technology",
        "native_name": "龙芯中科",
        "signal_roles": {"accelerator"},
        "read_through": [
            {"tickers": ["INTC", "AMD"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    # --- Servers, systems, components ---------------------------------
    "000977": {
        "company": "Inspur Electronic Information",
        "native_name": "浪潮信息",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["SMCI", "DELL", "HPE"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "00992": {
        "company": "Lenovo",
        "native_name": "联想集团",
        "hk_code": "00992",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["DELL", "HPQ", "SMCI"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "002475": {
        "company": "Luxshare Precision",
        "native_name": "立讯精密",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["APH", "TEL", "JBL", "FLEX"], "direction": "opposite",
             "relationship": "competitor", "categories": "ALL"},
        ],
    },
    "000725": {
        "company": "BOE Technology",
        "native_name": "京东方A",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["GLW"], "direction": "opposite", "relationship": "competitor", "categories": "ALL"},
            {"tickers": ["AMAT"], "direction": "same",
             "relationship": "customer", "categories": ["C3", "C5"]},
        ],
    },
    # --- Demand side: the platforms -----------------------------------
    # Their capex IS the US sellers' revenue, so SAME, not opposite.
    "09988": {
        "company": "Alibaba Group",
        "native_name": "阿里巴巴",
        "hk_code": "09988",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA", "AMD", "SMCI"], "direction": "same",
             "relationship": "customer", "categories": "ALL"},
        ],
    },
    "00700": {
        "company": "Tencent",
        "native_name": "腾讯控股",
        "hk_code": "00700",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA", "AMD"], "direction": "same",
             "relationship": "customer", "categories": "ALL"},
        ],
    },
    "09888": {
        "company": "Baidu",
        "native_name": "百度",
        "hk_code": "09888",
        "signal_roles": {"platform"},
        "read_through": [
            {"tickers": ["NVDA"], "direction": "same",
             "relationship": "customer", "categories": ["C5"]},
            # Its own accelerator programme reads the other way.
            {"tickers": ["NVDA"], "direction": "opposite",
             "relationship": "competitor", "categories": ["C4"]},
        ],
    },
    # --- Materials and the retaliation lever --------------------------
    # The spec calls these MIXED, and they are the only rows where the
    # category genuinely flips the sign: a Chinese producer shipping
    # more is competitive pressure on MP (C2), while a Chinese export
    # restriction makes MP one of the few non-Chinese sources (C1).
    "600111": {
        "company": "China Northern Rare Earth",
        "native_name": "北方稀土",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MP"], "direction": "opposite",
             "relationship": "competitor", "categories": ["C2", "C3", "C6"]},
            {"tickers": ["MP"], "direction": "same",
             "relationship": "competitor", "categories": ["C1", "C7"]},
        ],
    },
    "300748": {
        "company": "JL MAG Rare-Earth",
        "native_name": "金力永磁",
        "signal_roles": set(),
        "read_through": [
            {"tickers": ["MP"], "direction": "opposite",
             "relationship": "competitor", "categories": ["C2", "C3", "C6"]},
            {"tickers": ["MP"], "direction": "same",
             "relationship": "competitor", "categories": ["C1", "C7"]},
        ],
    },
}


def china_company_universe() -> list[dict[str, Any]]:
    """The tracked universe as reference data, for GET
    /china-signals/universe.

    A derived view over CHINA_COMPANIES, the same way
    ``codes_with_role`` is - a company added to the table above
    appears here without a second edit.

    `native_name` and `hk_code` are DUPLICATED from news-retrieval's
    CHINA_TICKER_UNIVERSE, which is the fetcher's own list and stays
    the source of truth for fetching. Recorded plainly because this
    module's whole premise is that duplicated company facts drift: the
    two lists are checked equal at 20 companies as of 2026-10-09, and
    research-universe is the intended owner of both. The alternative
    was a runtime HTTP call to news-retrieval for static reference
    data, which buys a network dependency to avoid a copy.

    Built field by field rather than spread from the record, same
    reason japan-signals/universe does: spreading leaks whatever the
    table happens to hold - `signal_roles` is a set and not JSON
    serialisable, and `categories` is an internal routing detail.
    """
    out: list[dict[str, Any]] = []
    for code, c in CHINA_COMPANIES.items():
        out.append({
            "code": code,
            "company": c["company"],
            "native_name": c.get("native_name"),
            "hk_code": c.get("hk_code"),
            # Sorted so the response is stable between calls - a set's
            # iteration order is not, and a consumer diffing this
            # would see phantom changes.
            "signal_roles": sorted(c["signal_roles"]),
            # Every US name this company reads to, across all signal
            # types, each with why they are linked and which way it
            # moves. `categories` is deliberately not exposed: which
            # classifier a link applies to is this service's routing
            # detail, and a consumer joining by code does not need it.
            "read_through": [
                {"tickers": list(link["tickers"]),
                 "direction": link["direction"],
                 "relationship": link["relationship"]}
                for link in c["read_through"]
            ],
        })
    return out


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

    Returns a list of ``{"tickers": [...], "direction":
    "same"|"opposite", "relationship": "competitor"|"supplier"|
    "customer"|"parent"}`` for the given signal category, or [] when
    the company has no link or none applies to this category.

    `direction` and `relationship` answer different questions and both
    are needed. Direction says which way the US name moves on this
    signal; relationship says WHY the two are linked, which direction
    alone cannot express - a foundry buying tools and a rival losing a
    socket both read `opposite` on some signal types, and only the
    relationship distinguishes "lost a customer" from "lost a sale".
    It is also stable where direction is not: MP Materials is a
    competitor to both rare-earth names whether the signal type makes
    the read `same` (C1/C7, policy that lifts the whole sector) or
    `opposite` (C2/C3/C6, output that displaces it).
    """
    if not code:
        return []
    out: list[dict[str, Any]] = []
    for link in CHINA_COMPANIES.get(code, {}).get("read_through", []):
        categories = link["categories"]
        if categories != "ALL" and signal_type not in categories:
            continue
        out.append({"tickers": list(link["tickers"]),
                    "direction": link["direction"],
                    "relationship": link["relationship"]})
    return out
