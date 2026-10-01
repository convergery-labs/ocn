"""JAPAN_TICKER_UNIVERSE - the 20-company tracked universe for
japan_market_signal classification (Japan Signals spec section 1's
company table).

Duplicated from news-retrieval's src/seed.py rather than imported or
fetched live - same pattern as korea_ticker_universe.py's own duplication
of KOREA_TICKER_UNIVERSE (see that module's own docstring for the
reasoning: each service owns its own copy of a small, rarely-changing
lookup table rather than adding a cross-service dependency for it).

fiscal_year_end (MM-DD) is the field Korea's own universe has no
equivalent of - Japan Signals spec Section 2.4 ("the year does not start
in January... compare everything relative to it, never assume December")
makes this a load-bearing field here, not just descriptive metadata:
J1's habit computation groups a company's own revision history into
FISCAL years using this date, not calendar years, and J2's progress-
against-forecast calculation needs it to know how far through the current
fiscal year "today" actually is.

Kept in sync manually with news-retrieval/src/seed.py's
JAPAN_TICKER_UNIVERSE if that list ever changes (add/remove a tracked
company, correct a name, a fiscal-year-end change following a real
company announcement).

"customers" (added 2026-09-30): read-through major-customer names per
company, for descriptive display alongside a classified signal only
(e.g. "this Advantest capex signal reads through to TSMC/Samsung/
Nvidia") - NOT used in any classification logic (no rule keys off it).
UNVERIFIED against a primary source (an annual report, an
investor-relations disclosure, or an independent filing) as of this
addition - entered from a user-supplied reference table with no
citation trail. Treat as provisional pending a real source check before
relying on it for anything beyond descriptive UI text.

A read-through link carries a relationship, and the vocabulary is the
consuming frontend's, not this module's:

    Customer | Supplier | Competitor | Shared demand

These are the only four values the Japan Signals tab renders, so a link
described any other way (peer, gated, substitute) has no display and is
silently dropped. "Shared demand" is the value for two companies that
move together because they sell into the same end market without
trading with each other - the common case for an equipment maker and
its listed peers, which would otherwise be mislabelled "Competitor".

Each link also needs a US-listed ticker to be actionable: the names
below are the companies a signal reads through to, but several (Samsung
Electronics, SK Hynix, SMIC, Denso, MediaTek) are not US-listed and
cannot be traded on. Resolving these to tickers, with a relationship
from the list above, is the mapping work this field is a placeholder
for.
"""
from typing import Any

JAPAN_TICKER_UNIVERSE: list[dict[str, Any]] = [
    {"code": "6857", "company": "Advantest", "native_name": "アドバンテスト", "fiscal_year_end": "03-31", "customers": ["TSMC", "Samsung Electronics", "AMD", "Nvidia", "Intel"], "role": "tests their chips"},
    {"code": "8035", "company": "Tokyo Electron", "native_name": "東京エレクトロン", "fiscal_year_end": "03-31", "customers": ["TSMC", "Samsung Electronics", "Intel", "SK Hynix", "Micron Technology"], "role": "builds their fabs"},
    {"code": "6146", "company": "Disco", "native_name": "ディスコ", "fiscal_year_end": "03-31", "customers": ["TSMC", "Samsung Electronics", "Texas Instruments", "Lumileds", "SMIC"], "role": "dices their wafers"},
    {"code": "6920", "company": "Lasertec", "native_name": "レーザーテック", "fiscal_year_end": "06-30", "customers": ["TSMC", "Samsung Electronics", "Intel"], "role": "inspects their masks"},
    {"code": "5803", "company": "Fujikura", "native_name": "フジクラ", "fiscal_year_end": "03-31", "customers": ["Apple"], "role": "wires their datacentres"},
    {"code": "4063", "company": "Shin-Etsu Chemical", "native_name": "信越化学工業", "fiscal_year_end": "03-31", "customers": ["TSMC", "Samsung Electronics", "Micron Technology", "Intel"], "role": "makes their wafers"},
    {"code": "3436", "company": "SUMCO", "native_name": "SUMCO", "fiscal_year_end": "12-31", "customers": ["TSMC", "Samsung Electronics", "Kioxia", "Intel", "SK Hynix"], "role": "makes their wafers"},
    {"code": "4062", "company": "Ibiden", "native_name": "イビデン", "fiscal_year_end": "03-31", "customers": ["Intel", "Samsung Electronics", "Nvidia", "Apple"], "role": "packages their chips"},
    {"code": "7735", "company": "Screen Holdings", "native_name": "SCREENホールディングス", "fiscal_year_end": "03-31", "customers": ["TSMC", "Intel", "Samsung Electronics"], "role": "cleans their wafers"},
    {"code": "6525", "company": "Kokusai Electric", "native_name": "KOKUSAI ELECTRIC", "fiscal_year_end": "03-31", "customers": ["Intel", "Samsung Electronics", "SK Hynix", "Micron Technology"], "role": "deposits their films"},
    {"code": "4186", "company": "Tokyo Ohka Kogyo", "native_name": "東京応化工業", "fiscal_year_end": "03-31", "customers": ["Intel", "TSMC", "Samsung Electronics"], "role": "supplies their photoresist"},
    {"code": "4004", "company": "Resonac Holdings", "native_name": "レゾナック・ホールディングス", "fiscal_year_end": "12-31", "customers": ["TSMC", "Samsung Electronics", "Intel"], "role": "supplies their materials"},
    {"code": "6315", "company": "Towa", "native_name": "TOWA", "fiscal_year_end": "03-31", "customers": ["SK Hynix", "TSMC", "Samsung Electronics"], "role": "moulds their packages"},
    {"code": "6981", "company": "Murata Manufacturing", "native_name": "村田製作所", "fiscal_year_end": "03-31", "customers": ["Apple", "Samsung Electronics"], "role": "supplies their components"},
    {"code": "6762", "company": "TDK", "native_name": "TDK", "fiscal_year_end": "03-31", "customers": ["Apple", "Samsung Electronics"], "role": "supplies their components"},
    {"code": "285A", "company": "Kioxia", "native_name": "キオクシア", "fiscal_year_end": "03-31", "customers": ["Apple", "Dell", "HP"], "role": "makes their flash memory"},
    {"code": "6723", "company": "Renesas Electronics", "native_name": "ルネサスエレクトロニクス", "fiscal_year_end": "12-31", "customers": ["Toyota", "Honda", "Denso"], "role": "makes their microcontrollers"},
    {"code": "6501", "company": "Hitachi", "native_name": "日立製作所", "fiscal_year_end": "03-31", "customers": ["Microsoft", "AWS"], "role": "builds their infrastructure"},
    {"code": "9984", "company": "SoftBank Group", "native_name": "ソフトバンクグループ", "fiscal_year_end": "03-31", "customers": ["AMD", "AWS", "Alphabet", "Intel", "MediaTek", "Nvidia", "Qualcomm", "Samsung Electronics"], "role": "owns stakes in them"},
]
