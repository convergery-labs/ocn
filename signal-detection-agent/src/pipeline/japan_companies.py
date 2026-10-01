"""JAPAN_COMPANIES - the single source of truth for the tracked
Japanese universe.

One record per company, holding everything the Japan Signals pipeline
knows about it: identity, fiscal calendar, weight in the Tokyo market,
and its disclosed customers. Three separate modules used to hold these
- a ticker universe, a company profile, and a hand-written read-through
table - which meant a company's name was stored twice, its customers
lived apart from the company they belong to, and the read-through
table could drift out of step with the customer data it was supposed
to reflect. There is now one table, and the read-through view is
DERIVED from it rather than maintained beside it.

STATIC FOR NOW - RESEARCH-UNIVERSE BECOMES THE SOURCE LATER.
    Every figure is hand-entered from a one-off research pass dated
    1 October 2026, transcribed from company annual securities reports
    (有価証券報告書, "yuho"), JPX month-end index data and
    stockanalysis.com. None of it is independently verified against a
    filing, and nothing re-reads those filings when next year's land.
    research-universe is the intended owner: when it can serve this,
    the tables below are deleted rather than maintained.

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
    Market caps are the 1 Oct 2026 close, and three of these companies
    (Tokyo Electron 5:1, Kioxia 3:1, Ibiden 2:1) ran stock splits
    effective that very day - which is how a hardcoded price goes
    quietly wrong. ``AS_OF`` and ``is_stale()`` exist so a consumer
    decides rather than discovers. Index weight and rank move monthly;
    the sales and customer percentages hold until the next annual
    report.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# The date every market figure here was measured on. Market caps are
# the 1 Oct 2026 Tokyo close; TSE Prime share uses the 30 Sep close
# against JPX's month-end Prime total of ¥1,351.2tn.
AS_OF = date(2026, 10, 1)

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

JAPAN_COMPANIES: dict[str, dict[str, Any]] = {
    "9984": {
        "company": 'SoftBank Group',
        "native_name": 'ソフトバンクグループ',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 2.71,
        "japan_rank": 2,
        "japan_sales_pct": None,
        "market_cap_jpy_tn": 38.2,
        "market_cap_usd_bn": 241.4,
        "japan_sales_note": (
            'SoftBank Corp is about 90% of group sales and is mostly domestic, but the group discloses no Japan split'
        ),
        "customers": [
            _customer('SoftBank Corp subscribers', None, 'FY3/26', relationship='user_base'),
            _customer('Arm China', 16.0, 'FY3/26', aliases=('Arm Technology China', 'アームチャイナ'), relationship='licensee'),
            _customer('Apple', None, None, relationship='licensee', ticker='AAPL', aliases=('アップル',)),
            _customer('Qualcomm', None, None, relationship='licensee', ticker='QCOM', aliases=('クアルコム',)),
            _customer('MediaTek', None, None, relationship='licensee', ticker='2454', aliases=('メディアテック', '聯發科')),
            _customer('Amazon ', None, None, relationship='licensee', ticker='AMZN', aliases=('Amazon', 'AWS', 'アマゾン')),
            _customer('Microsoft', None, None, relationship='licensee', ticker='MSFT', aliases=('マイクロソフト',)),
            _customer('Alphabet', None, None, relationship='licensee', ticker='GOOGL', aliases=('Alphabet', 'Google', 'グーグル')),
            _customer('Nvidia ', None, None, ticker='NVDA', aliases=('Nvidia', 'NVIDIA', 'エヌビディア'), relationship='licensee'),
            _customer('OpenAI ', None, '2025', aliases=('OpenAI', 'オープンAI'), relationship='investee'),
        ],
    },
    "285A": {
        "company": 'Kioxia',
        "native_name": 'キオクシア',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 2.2,
        "japan_rank": 4,
        "japan_sales_pct": 11.3,
        "market_cap_jpy_tn": 31.0,
        "market_cap_usd_bn": 195.9,
        "customers": [
            _customer('Apple', 20.4, 'FY3/26', ticker='AAPL', aliases=('アップル',)),
            _customer('Sandisk', 8.0, 'FY3/26', ticker='SNDK', aliases=('SanDisk', 'サンディスク')),
            _customer('Dell', None, 'FY3/25', ticker='DELL', aliases=('デル',)),
            _customer('Microsoft', None, None, ticker='MSFT', aliases=('マイクロソフト',)),
            _customer('HP', None, None, ticker='HPQ', aliases=('Hewlett-Packard', 'ヒューレット・パッカード')),
            _customer('Nvidia', None, '2025', ticker='NVDA', aliases=('NVIDIA', 'エヌビディア')),
        ],
    },
    "8035": {
        "company": 'Tokyo Electron',
        "native_name": '東京エレクトロン',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 1.98,
        "japan_rank": 5,
        "japan_sales_pct": 9.8,
        "market_cap_jpy_tn": 28.56,
        "market_cap_usd_bn": 180.5,
        "customers": [
            _customer('Samsung Electronics', 15.1, 'FY3/26', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('TSMC', 12.9, 'FY3/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Intel', None, 'FY3/23', ticker='INTC', aliases=('インテル',)),
            _customer('Micron Technology', None, 'FY2025', ticker='MU', aliases=('Micron', 'マイクロン')),
            _customer('SK hynix', None, '2026', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Chinese chipmakers (unnamed)', None, 'FY3/26'),
        ],
    },
    "6857": {
        "company": 'Advantest',
        "native_name": 'アドバンテスト',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 1.84,
        "japan_rank": 6,
        "japan_sales_pct": 2.2,
        "market_cap_jpy_tn": 27.23,
        "market_cap_usd_bn": 172.1,
        "customers": [
            _customer('Nvidia', 21.6, 'FY3/26', ticker='NVDA', aliases=('NVIDIA', 'エヌビディア')),
            _customer('TSMC', 11.1, 'FY3/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Samsung Electronics', None, 'FY3/25', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('SK hynix', None, '2026', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Micron Technology', None, '2026', ticker='MU', aliases=('Micron', 'マイクロン')),
        ],
    },
    "6501": {
        "company": 'Hitachi',
        "native_name": '日立製作所',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 1.82,
        "japan_rank": 8,
        "japan_sales_pct": 37.0,
        "market_cap_jpy_tn": 24.68,
        "market_cap_usd_bn": 156.0,
        "customers": [
            _customer('Amprion', None, '2024'),
            _customer('TenneT', None, '2023'),
            _customer('National Grid & SSEN (EGL3)', None, '2026', ticker='NG'),
            _customer('Terna & STEG (ELMED)', None, '2026', ticker='TRN'),
            _customer('WMATA', None, '2021'),
            _customer('Trenitalia', None, '2026'),
            _customer('OpenAI', None, '2025', aliases=('オープンAI',)),
        ],
    },
    "6981": {
        "company": 'Murata Manufacturing',
        "native_name": '村田製作所',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 1.06,
        "japan_rank": 15,
        "japan_sales_pct": 7.3,
        "market_cap_jpy_tn": 15.49,
        "market_cap_usd_bn": 97.9,
        "customers": [
            _customer('Hon Hai (Foxconn)', 10.2, 'FY3/24', ticker='2317', aliases=('Hon Hai', 'Foxconn', '鴻海', 'フォックスコン')),
            _customer('Apple', None, '2024', ticker='AAPL', aliases=('アップル',)),
            _customer('Samsung Electronics', None, '2023', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('Nvidia', None, '2026', ticker='NVDA', aliases=('NVIDIA', 'エヌビディア')),
            _customer('Tesla', None, '2022', ticker='TSLA', aliases=('テスラ',)),
        ],
    },
    "4063": {
        "company": 'Shin-Etsu Chemical',
        "native_name": '信越化学工業',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.82,
        "japan_rank": 24,
        "japan_sales_pct": 21.4,
        "market_cap_jpy_tn": 11.21,
        "market_cap_usd_bn": 70.9,
        "customers": [
            _customer('TSMC', None, '2025', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Samsung Electronics', None, '2023', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('Intel', None, '2024', ticker='INTC', aliases=('インテル',)),
            _customer('Toyota', None, 'FY3/26', ticker='7203', aliases=('Toyota Motor', 'トヨタ', 'トヨタ自動車')),
            # A tracked company in its own right (4186) - the ticker
            # is its TSE code, so a consumer can link one card to the
            # other instead of matching on a name string.
            _customer('Tokyo Ohka Kogyo', None, 'FY3/26', ticker='4186', aliases=('Tokyo Ohka', '東京応化工業')),
            _customer('Kubota', None, 'FY3/26', ticker='6326', aliases=('クボタ',)),
            _customer('Riken Technos', None, 'FY3/26', ticker='4220', aliases=('リケンテクノス',)),
            _customer('Topco Scientific', None, 'FY3/26', ticker='5434', aliases=('崇越科技',)),
        ],
    },
    "5803": {
        "company": 'Fujikura',
        "native_name": 'フジクラ',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.64,
        "japan_rank": 31,
        "japan_sales_pct": 20.4,
        "market_cap_jpy_tn": 8.91,
        "market_cap_usd_bn": 56.3,
        "customers": [
            _customer('Alphabet', None, '2025', ticker='GOOGL', aliases=('Alphabet', 'Google', 'グーグル')),
            _customer('Apple', None, 'FY2022', ticker='AAPL', aliases=('アップル',)),
            _customer('US hyperscalers (unnamed)', None, '2026'),
        ],
    },
    "4062": {
        "company": 'Ibiden',
        "native_name": 'イビデン',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.46,
        "japan_rank": 40,
        "japan_sales_pct": 27.1,
        "market_cap_jpy_tn": 6.7,
        "market_cap_usd_bn": 42.4,
        "customers": [
            _customer('Nvidia', 29.4, 'FY3/26', ticker='NVDA', aliases=('NVIDIA', 'エヌビディア')),
            _customer('Intel', 18.1, 'FY3/26', ticker='INTC', aliases=('インテル',)),
            _customer('AMD', 11.0, 'FY3/25', ticker='AMD', aliases=('エーエムディー',)),
            _customer('Alphabet ', None, '2026', ticker='GOOGL', aliases=('Alphabet', 'Google', 'グーグル')),
            _customer('Amazon ', None, '2026', ticker='AMZN', aliases=('Amazon', 'AWS', 'アマゾン')),
            _customer('Toyota', None, 'FY3/26', ticker='7203', aliases=('Toyota Motor', 'トヨタ', 'トヨタ自動車')),
        ],
    },
    "6723": {
        "company": 'Renesas Electronics',
        "native_name": 'ルネサスエレクトロニクス',
        "fiscal_year_end": '12-31',
        "tse_prime_pct": 0.47,
        "japan_rank": 42,
        "japan_sales_pct": 20.4,
        "market_cap_jpy_tn": 6.62,
        "market_cap_usd_bn": 41.8,
        "customers": [
            _customer('WT Microelectronics', 17.1, 'FY12/25', is_distributor=True, ticker='3036', aliases=('WT Micro', '文曄科技'), relationship='distributor'),
            _customer('Hagiwara Electronics', None, 'FY12/24', is_distributor=True, ticker='7467', aliases=('萩原電気',), relationship='distributor'),
            _customer('Ryosan', None, 'FY12/21', is_distributor=True, ticker='167A', aliases=('菱洋エレクトロ', 'リョーヨーリョーサン'), relationship='distributor'),
            _customer('Toyota', None, '2018', ticker='7203', aliases=('Toyota Motor', 'トヨタ', 'トヨタ自動車')),
            _customer('Denso', None, '2018', ticker='6902', aliases=('デンソー',)),
            _customer('Honda', None, '2025', ticker='7267', aliases=('Honda Motor', 'ホンダ', '本田技研')),
            _customer('Bosch', None, '2024', aliases=('Robert Bosch', 'ボッシュ')),
            _customer('Tesla', None, '2021', ticker='TSLA', aliases=('テスラ',)),
            _customer('TIER IV', None, '2026', aliases=('ティアフォー',)),
        ],
    },
    "6146": {
        "company": 'Disco',
        "native_name": 'ディスコ',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.46,
        "japan_rank": 43,
        "japan_sales_pct": 10.4,
        "market_cap_jpy_tn": 6.56,
        "market_cap_usd_bn": 41.4,
        "customers": [
            _customer('TSMC', 11.0, 'FY3/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Intel', None, '2026', ticker='INTC', aliases=('インテル',)),
            _customer('SK hynix', None, '2026', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Samsung Electronics', None, None, ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('Micron Technology', None, None, ticker='MU', aliases=('Micron', 'マイクロン')),
        ],
    },
    "6762": {
        "company": 'TDK',
        "native_name": 'TDK',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.42,
        "japan_rank": 48,
        "japan_sales_pct": 7.3,
        "market_cap_jpy_tn": 6.08,
        "market_cap_usd_bn": 38.4,
        "customers": [
            _customer('Apple', None, '2026', ticker='AAPL', aliases=('アップル',)),
            _customer('Samsung Electronics', None, '2024', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('Toshiba ', None, '2026', aliases=('Toshiba', '東芝')),
            _customer('Seagate', None, '2026', ticker='STX', aliases=('シーゲイト',)),
            _customer('Western Digital', None, '2026', ticker='WDC', aliases=('WD', 'ウエスタンデジタル')),
        ],
    },
    "6920": {
        "company": 'Lasertec',
        "native_name": 'レーザーテック',
        "fiscal_year_end": '06-30',
        "tse_prime_pct": 0.27,
        "japan_rank": 67,
        "japan_sales_pct": 12.2,
        "market_cap_jpy_tn": 4.1,
        "market_cap_usd_bn": 25.9,
        "customers": [
            _customer('TSMC', 21.4, 'FY6/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Intel', 20.7, 'FY6/26', ticker='INTC', aliases=('インテル',)),
            _customer('Samsung Electronics', 20.2, 'FY6/26', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
        ],
    },
    "4004": {
        "company": 'Resonac Holdings',
        "native_name": 'レゾナック・ホールディングス',
        "fiscal_year_end": '12-31',
        "tse_prime_pct": 0.21,
        "japan_rank": 83,
        "japan_sales_pct": 43.4,
        "market_cap_jpy_tn": 3.02,
        "market_cap_usd_bn": 19.1,
        "customers": [
            _customer('Infineon', None, '2023', ticker='IFX', aliases=('Infineon Technologies', 'インフィニオン')),
            _customer('Denso ', None, '2023', ticker='6902', aliases=('Denso', 'デンソー')),
            _customer('ROHM', None, '2021', ticker='6963', aliases=('Rohm', 'ローム')),
            _customer('Toshiba Electronic Devices', None, '2021', aliases=('Toshiba', '東芝')),
            _customer('Toshiba ', None, '2024', aliases=('Toshiba', '東芝')),
        ],
    },
    "7735": {
        "company": 'Screen Holdings',
        "native_name": 'SCREENホールディングス',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.2,
        "japan_rank": 87,
        "japan_sales_pct": 14.1,
        "market_cap_jpy_tn": 2.95,
        "market_cap_usd_bn": 18.6,
        "customers": [
            _customer('TSMC', 14.6, 'FY3/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('SiEn ', 10.3, 'FY3/24', aliases=('SiEn', '芯恩', '青島芯恩')),
            _customer('Micron Technology', None, '2024', ticker='MU', aliases=('Micron', 'マイクロン')),
            _customer('IBM', None, '2025', ticker='IBM', aliases=('IBM', '日本IBM', 'アイ・ビー・エム'), relationship='partner'),
            _customer('Samsung Electronics', None, '2026', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('SK hynix', None, '2026', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
        ],
    },
    "6525": {
        "company": 'Kokusai Electric',
        "native_name": 'KOKUSAI ELECTRIC',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.16,
        "japan_rank": 102,
        "japan_sales_pct": 9.7,
        "market_cap_jpy_tn": 2.35,
        "market_cap_usd_bn": 14.9,
        "customers": [
            _customer('Samsung Electronics', 21.8, 'FY3/26', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('TSMC', 13.4, 'FY3/26', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('CXMT', 20.4, 'FY3/25', aliases=('ChangXin', '長鑫存儲')),
            _customer('Micron Technology', None, 'FY3/23', ticker='MU', aliases=('Micron', 'マイクロン')),
            _customer('SK hynix', None, '2024', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Intel', None, '2026', ticker='INTC', aliases=('インテル',)),
            _customer('YMTC', None, '2025', aliases=('Yangtze Memory', '長江存儲')),
        ],
    },
    "3436": {
        "company": 'SUMCO',
        "native_name": 'SUMCO',
        "fiscal_year_end": '12-31',
        "tse_prime_pct": 0.09,
        "japan_rank": 181,
        "japan_sales_pct": 19.4,
        "market_cap_jpy_tn": 1.21,
        "market_cap_usd_bn": 7.7,
        "customers": [
            _customer('Sumitomo Corporation', 27.0, 'FY12/25', is_distributor=True, ticker='8053', aliases=('Sumitomo Corp', '住友商事'), relationship='distributor'),
            _customer('Samsung Electronics', None, 'FY12/23', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('TSMC', None, '2025', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Kioxia', None, '2025', ticker='285A', aliases=('キオクシア',)),
            _customer('Sony Semiconductor Solutions', None, '2025', aliases=('Sony', 'ソニー', 'ソニーセミコンダクタ')),
        ],
    },
    "4186": {
        "company": 'Tokyo Ohka Kogyo',
        "native_name": '東京応化工業',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.08,
        "japan_rank": 203,
        "japan_sales_pct": 15.5,
        "market_cap_jpy_tn": 1.07,
        "market_cap_usd_bn": 6.8,
        "customers": [
            _customer('TSMC', 33.6, 'FY12/25', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('Samsung Electronics', None, '2026', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('SK hynix', None, '2026', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Intel', None, '2020', ticker='INTC', aliases=('インテル',)),
        ],
    },
    "6315": {
        "company": 'Towa',
        "native_name": 'TOWA',
        "fiscal_year_end": '03-31',
        "tse_prime_pct": 0.01,
        "japan_rank": 612,
        "japan_sales_pct": 12.7,
        "market_cap_jpy_tn": 0.181,
        "market_cap_usd_bn": 1.1,
        "customers": [
            _customer('SK hynix', None, 'FY3/26', ticker='000660', aliases=('SK Hynix', 'SKハイニックス')),
            _customer('Samsung Electronics', None, 'FY3/13', ticker='005930', aliases=('Samsung', 'サムスン', 'サムスン電子')),
            _customer('TSMC', None, '2026', ticker='TSM', aliases=('台湾積体電路', '台積電')),
            _customer('ASE Group', None, '2026', ticker='3711', aliases=('ASE', '日月光')),
            _customer('Amkor Technology', None, '2026', ticker='AMKR', aliases=('Amkor', 'アムコー')),
            _customer('Micron Technology', None, '2026', ticker='MU', aliases=('Micron', 'マイクロン')),
            _customer('Powertech Technology', None, 'FY3/14', ticker='6239', aliases=('Powertech', '力成科技')),
        ],
    },}


# Ordered view for callers that iterate the universe rather than look
# one company up. Not a second table: `code` is written INTO each
# record at import, so these are the same dict objects JAPAN_COMPANIES
# holds - not copies of them. A field read through this list and the
# same field read through company_for() are the same memory.
for _code, _record in JAPAN_COMPANIES.items():
    _record["code"] = _code

JAPAN_TICKER_UNIVERSE: list[dict[str, Any]] = list(JAPAN_COMPANIES.values())


def company_for(code: str | None) -> dict[str, Any] | None:
    """Everything known about one tracked company."""
    if not code:
        return None
    return JAPAN_COMPANIES.get(code)


def is_stale(as_of: date | None = None) -> bool:
    """True when the valuation figures need a caveat.

    Governs the market figures alone - the customer percentages are
    filed facts that only change with the next annual report.
    """
    return ((as_of or date.today()) - AS_OF).days > _VALUATION_STALE_DAYS


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
        "asOf": AS_OF.isoformat(),
        "isStale": is_stale(as_of),
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
