"""The tracked Japanese universe, read from research-universe.

Every company this pipeline follows - identity, fiscal calendar,
weight in the Tokyo market, and its disclosed customers - is defined
once in research-universe and read from there. This module is the
reader, not a second copy.

NOTHING IS HARDCODED HERE, DELIBERATELY
    A static table of the same 19 companies used to sit in this file
    as a fallback. It was deleted rather than kept, because by the
    time it was a fallback it had already drifted: the database said
    Kioxia Holdings, Fujikura and Murata Manufacturing where the table
    still said Kioxia, Fujikura Ltd and Murata. A fallback that serves
    names corrected months earlier is not a safety net.

    So a failure to load raises UniverseUnavailable. A Japan job is a
    one-off scheduled task; one that exits non-zero is noticed, one
    that quietly classifies against stale companies is not.

WHAT A DISCLOSED PERCENTAGE MEANS
    Japanese issuers must name a customer in the annual report once it
    passes 10% of sales. So a percentage here is a filed fact with a
    date on it - and its ABSENCE is also a fact: it means no customer
    reached 10%, not that nobody looked. ``pct_of_sales`` is therefore
    None rather than 0 when undisclosed, and the two are never
    conflated.

    ``period`` matters for the same reason. Ibiden's AMD share was
    11.0% in FY3/25 and fell below the threshold in FY3/26, so the
    period is what tells a reader the figure is not current.

WHAT IS AND IS NOT A READ-THROUGH
    A large disclosed customer is not automatically a tradable link.
    SUMCO's largest is Sumitomo Corporation at 27% of sales and
    Renesas's is WT Microelectronics at 17.1% - both DISTRIBUTORS. A
    trader reading "SUMCO's biggest customer just guided down" would
    be misled: a trading house's results say nothing about wafer
    demand. Those carry ``is_distributor=True`` and are excluded from
    read-through while still being shown as what they are.

    ``ticker`` is the customer's own listing wherever it trades -
    NASDAQ, the TSE, Taiwan, Korea, Frankfurt. It is NOT a
    US-tradability marker: a consumer that needs one should check the
    exchange, not the presence of a ticker. Customers with no ticker
    are genuinely unlisted (Arm China, CXMT, SiEn Qingdao), private
    (Robert Bosch GmbH), subsidiaries of a listed parent (Sony
    Semiconductor Solutions), delisted (Toshiba), or not companies at
    all (a subscriber base, "US hyperscalers (unnamed)").

MARKET CAP IS A DATED SNAPSHOT
    Market figures move daily, and three of these companies ran stock
    splits on the very day theirs were taken - which is how a stored
    price goes quietly wrong. Each company carries its own
    ``market_data_as_of``, and ``is_stale()`` exists so a consumer
    decides rather than discovers. Index weight and rank move monthly;
    the sales and customer percentages hold until the next annual
    report.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# Beyond this, the valuation figures are old enough that presenting
# them without a caveat misleads. One quarter: Japanese issuers report
# quarterly, so a figure older than that predates the most recent set
# of results and the market has had a full cycle to reprice.
_VALUATION_STALE_DAYS = 92


# What one party is to the other. "customer" covers 100 of the 112
# relationships here and is the default; the rest exist because a
# single label would misdescribe them.
#
#   customer    buys what this company sells. The ordinary case.
#   distributor a trading house that resells. A real disclosed
#               counterparty, but its own results say nothing about
#               end demand, so it is not a read-through.
#   licensee    licenses IP from a subsidiary - Arm's licensees are
#               not SoftBank Group's customers.
#   investee    this company invests in THEM. Money flows the other
#               way, so "customer" inverts the relationship.
#   user_base   a subscriber base, not a company at all.
#   partner     joint development or research, with no sales implied.
RELATIONSHIPS = ("customer", "distributor", "licensee",
                 "investee", "user_base", "partner")


def _customer(name: str, pct: float | None, period: str | None,
              *, ticker: str | None = None, aliases: tuple[str, ...] = (),
              relationship: str = "customer",
              is_distributor: bool = False) -> dict[str, Any]:
    """One customer of one tracked company.

    ``pct`` is None where the company discloses no figure - the common
    case, since only customers above 10% of sales must be named. None
    means "not disclosed", never "zero" or "unknown".
    """
    if relationship not in RELATIONSHIPS:
        raise ValueError(
            f"{name}: unknown relationship {relationship!r}; "
            f"expected one of {RELATIONSHIPS}"
        )
    return {
        "name": name,
        "ticker": ticker,
        "pct_of_sales": pct,
        "period": period,
        # Every written form this customer appears under, the stored
        # `name` included. Japanese filings and press write エヌビディア
        # and ホンダ where an English card writes Nvidia and Honda, so
        # matching on `name` alone misses roughly half of real
        # occurrences (measured on the stored text).
        #
        # Repeated per relationship rather than held once per company:
        # Samsung is a customer of twelve suppliers here, so its
        # aliases are written twelve times. That is deliberate for now
        # - these records move to research-universe, where a customer
        # resolves to its own company row and the aliases live there
        # once. Normalising into a second Python table first would mean
        # transcribing them twice.
        "aliases": tuple(dict.fromkeys((name, *aliases))),
        "relationship": relationship,
        # Kept alongside `relationship` because a consumer filtering
        # read-through links cares about exactly this one distinction
        # and should not have to know the whole vocabulary. Derived,
        # never set independently - see the assertion below.
        "is_distributor": is_distributor or relationship == "distributor",
    }


# code -> everything known about one company. Ordered by Japan market
# -cap rank, which is also roughly how a reader thinks about them.
#
# "japan_sales_pct" is sales booked inside Japan as a share of the
# total - a different question from where the company is listed:
# Advantest is Tokyo-listed with 2.2% of sales in Japan, Resonac has
# 43.4%. A domestic shock reaches the second far harder.




# ---------------------------------------------------------------- #
# research-universe owns the tracked universe. There is no second    #
# copy of it here.                                                   #
#                                                                     #
# A hardcoded table used to sit above this as a fallback, and it      #
# was removed rather than kept, because by the time it was a          #
# fallback it had already stopped being the same data: the DB said    #
# Kioxia Holdings, Fujikura and Murata Manufacturing where the table  #
# still said Kioxia, Fujikura Ltd and Murata. "Falling back" meant    #
# serving names that had been corrected months earlier, silently.     #
#                                                                     #
# So a failure here raises. A Japan run is a one-off task on a        #
# schedule: a task that exits non-zero is visible within the hour,    #
# where a task that quietly classifies against stale companies is     #
# not visible at all.                                                 #
#                                                                     #
# Fetched once per process and held. This is reference data that      #
# changes when someone edits a company, not per-request data, and     #
# the classify/refresh tasks are short-lived enough that each run     #
# fetches fresh by definition.                                        #
# ---------------------------------------------------------------- #
_remote_companies: dict[str, dict[str, Any]] | None = None

_UNIVERSE_TIMEOUT_SECONDS = 30.0


class UniverseUnavailable(RuntimeError):
    """The tracked universe could not be loaded from research-universe."""


def _load_remote_companies() -> dict[str, dict[str, Any]]:
    """The tracked Japanese companies, from research-universe.

    Raises UniverseUnavailable rather than returning anything partial.
    Every caller below is asking "which companies do we track, and what
    is known about them" - a question with no safe approximate answer.

    Field names are passed through. They were once translated here -
    local_name read as native_name, local_code as code - and the one
    time that mapping went stale it failed in the worst available way:
    the request returned 200, every name came back None, and the
    service fell through to its built-in table. The names now match on
    both sides, and the validation below catches it if they stop.
    """
    import logging
    import os

    import httpx

    log = logging.getLogger(__name__)
    base = os.environ.get("RESEARCH_UNIVERSE_URL")
    if not base:
        raise UniverseUnavailable(
            "RESEARCH_UNIVERSE_URL is not set; the Japan company universe "
            "has no other source")
    try:
        key = os.environ.get("RESEARCH_UNIVERSE_API_KEY")
        resp = httpx.get(
            f"{base}/companies",
            params={"country": "Japan", "tracked": "true",
                    "include_customers": "true", "limit": 10000},
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=_UNIVERSE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:                                # noqa: BLE001
        raise UniverseUnavailable(
            f"research-universe unreachable: {exc}") from exc

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = (r.get("code") or "").strip()
        if not code:
            continue
        out[code] = {
            "code": code,
            "company": r.get("company_name"),
            "native_name": r.get("native_name"),
            "fiscal_year_end": r.get("fiscal_year_end"),
            "tse_prime_pct": r.get("index_weight_pct"),
            "japan_rank": r.get("home_market_rank"),
            "japan_sales_pct": r.get("domestic_sales_pct"),
            "market_cap_jpy_tn": r.get("market_cap_local"),
            "market_cap_usd_bn": r.get("market_cap_usd_bn"),
            "market_data_as_of": r.get("market_data_as_of"),
            "customers": [
                {
                    "name": c.get("customer_name"),
                    "ticker": c.get("customer_ticker"),
                    "pct_of_sales": c.get("pct_of_sales"),
                    "period": c.get("period"),
                    "aliases": tuple(c.get("aliases") or ()),
                    "relationship": c.get("relationship"),
                    "is_distributor": c.get("relationship") == "distributor",
                }
                for c in (r.get("customers") or [])
            ],
        }

    if not out:
        raise UniverseUnavailable(
            "research-universe returned no tracked Japanese companies")
    # A response can be structurally fine and still useless. The field
    # rename that prompted this check returned 200 with every row
    # present and every name null, which reads as success everywhere
    # except the output. Checking that the fields are POPULATED, not
    # merely that the request worked, is what catches that class of
    # failure.
    for field in ("company", "native_name"):
        if not any(c.get(field) for c in out.values()):
            raise UniverseUnavailable(
                f"research-universe returned {len(out)} Japanese companies "
                f"with no {field} on any of them - the response shape has "
                f"changed")
    log.info("[UNIVERSE] %d Japanese companies from research-universe",
             len(out))
    return out


def _companies() -> dict[str, dict[str, Any]]:
    """The tracked universe every accessor below reads.

    Raises UniverseUnavailable on the first call if research-universe
    cannot be reached. Not caught here and not caught by any caller:
    every function in this module answers a question about which
    companies are tracked, and there is nothing truthful to return
    when that is unknown.
    """
    global _remote_companies
    if _remote_companies is None:
        _remote_companies = _load_remote_companies()
    return _remote_companies


def reset_universe_cache() -> None:
    """Drop the fetched universe so the next read re-fetches it."""
    global _remote_companies
    _remote_companies = None


def japan_ticker_universe() -> list[dict[str, Any]]:
    """Every tracked Japanese company.

    A function rather than the module-level list it replaced: that list
    was bound at import time in four modules, so a universe fetched
    afterwards could never reach them.
    """
    return list(_companies().values())


def company_for(code: str | None) -> dict[str, Any] | None:
    """Everything known about one tracked company."""
    if not code:
        return None
    return _companies().get(code)


def _measured_on(code: str | None = None) -> date | None:
    """The date this company's market figures were measured.

    research-universe stamps each company with its own
    ``market_data_as_of``, so a company refreshed today is not reported
    stale because its neighbours are.

    None where the company carries no date. Undated figures used to
    fall back on a single hardcoded date that belonged to the removed
    built-in table, which presented every unstamped figure as having
    been measured that day - a date the data never claimed.
    """
    record = company_for(code) if code else None
    stamped = (record or {}).get("market_data_as_of")
    if isinstance(stamped, date):
        return stamped
    if isinstance(stamped, str):
        try:
            return date.fromisoformat(stamped[:10])
        except ValueError:
            pass
    return None


def is_stale(as_of: date | None = None, code: str | None = None) -> bool:
    """True when the valuation figures need a caveat.

    Governs the market figures alone - the customer percentages are
    filed facts that only change with the next annual report.
    """
    measured = _measured_on(code)
    if measured is None:
        # Undated. A figure that cannot be shown to be current is
        # treated as stale, so the caveat appears rather than being
        # skipped on the strength of a date nobody recorded.
        return True
    return ((as_of or date.today()) - measured).days > _VALUATION_STALE_DAYS


def valuation_for(code: str | None,
                  as_of: date | None = None) -> dict[str, Any] | None:
    """Market weight, with its own date attached.

    The date and staleness flag travel with the figures rather than
    being documented elsewhere: a consumer that forgets to check
    cannot then present a months-old market cap as current.
    """
    record = company_for(code)
    if not record:
        return None
    return {
        "marketCapJpyTn": record["market_cap_jpy_tn"],
        "marketCapUsdBn": record["market_cap_usd_bn"],
        "tsePrimePct": record["tse_prime_pct"],
        "japanRank": record["japan_rank"],
        "japanSalesPct": record["japan_sales_pct"],
        "asOf": (_measured_on(code).isoformat()
                 if _measured_on(code) else None),
        "isStale": is_stale(as_of, code),
    }


def mentioned_customers(code: str | None, text: str | None) -> list[dict[str, str]]:
    """Customers of ``code`` that ``text`` actually names.

    The question a reader's "Direct vs Inferred" badge asks: did this
    filing or article name the customer, or is it a standing
    relationship that happens to exist? A forecast revision stating
    figures names nobody; a press report saying who the new capacity
    is for does.

    Matched against this company's own customer list rather than
    extracted freely - the candidate set is known, so this is a lookup
    and needs no model call. That also bounds the failure mode: a
    missed alias loses a link, where free extraction could invent one
    and put it behind a "Direct" badge on a trading card.

    Latin names are matched on a word boundary, since "ASE" sits
    inside "PHASE" and "AMD" inside plenty of tokens. Japanese has no
    word breaks, so those forms match as plain substrings.

    Returns the agent_classifications entity shape, ``{name, type}``,
    so the result can be stored in entities_json alongside every other
    domain's extracted entities.
    """
    import re

    record = company_for(code)
    if not record or not text:
        return []

    out: list[dict[str, str]] = []
    for customer in record["customers"]:
        # No ticker means nothing a reader can look up, so a mention
        # of it is not actionable - "US hyperscalers (unnamed)" being
        # the clearest case.
        if not customer["ticker"]:
            continue
        for alias in customer["aliases"]:
            if alias.isascii():
                hit = re.search(rf"\b{re.escape(alias)}", text, re.IGNORECASE)
            else:
                hit = alias in text
            if hit:
                out.append({"name": customer["name"], "type": "company"})
                break
    return out
