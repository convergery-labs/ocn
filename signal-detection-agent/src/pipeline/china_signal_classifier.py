"""Classification for china_market_signal items read from news-retrieval.

STATUS: Gate 1 only. Nothing here assigns a Signal/Weak/Noise judgment
that depends on a numeric threshold, and that is deliberate - see
"WHY NO THRESHOLDS YET" below.

WHAT GATE 1 DOES
    Mainland filings are overwhelmingly corporate-governance housekeeping.
    Measured against the 73 distinct filings stored on 2026-10-05: 68 of
    them (93%) are shareholder-meeting resolutions, law-firm opinions,
    employee share schemes, articles-of-association amendments, dividend
    mechanics, convertible-bond notices and routine exchange returns.
    None carries a tradable fact.

    Gate 1 discards those by title pattern before any figure extraction,
    LLM call or body parse runs. What survives is a candidate, carrying a
    category that says WHICH downstream rule should look at it.

WHY NO THRESHOLDS YET
    The China Signals spec proposes rules like "a capital budget change
    of more than twenty percent" and "revenue growth more than two
    spreads above its own trailing pattern". Neither can be implemented
    honestly yet, for a reason the real data makes plain: only 5 of 73
    stored filings are signal-bearing at all, and of those exactly ONE
    (ACM Shanghai's orders-on-hand disclosure) is the kind of filing
    those rules describe. There is no distribution to derive a threshold
    from.

    This service already holds the precedent for how that is handled.
    Japan's classifier does not trust a company's habit until it has
    three genuine revisions spanning three fiscal years
    (_MIN_REVISIONS_FOR_TRUSTED_HABIT / _MIN_FISCAL_YEAR_SPAN_...), and
    Korea's export-surprise rule needs twelve periods before it will
    judge anything. Below those floors both fall through to WEAK rather
    than fabricate a baseline. China gets the same treatment: extract and
    store first, derive the rule from what accumulated, and only then
    judge.

    A number lifted from the spec and hardcoded here would look like a
    working rule while being an untested guess. That is the specific
    failure this module is written to avoid.

HOW THE CATEGORIES WERE BUILT
    By reading all stored titles, not from the spec. Three consequences
    worth recording:
      - Several filing types the spec implies would exist (capex
        announcements, forecast revisions) do not appear in the real
        mainland data at all over this window.
      - One that does appear was NOT in the spec's list: a joint-venture
        formation (Hua Hong, 有关成立合营企业的补充公告, and its English
        counterpart on HKEX).
      - HKEX filings are in ENGLISH by listing requirement. A first
        version of this table had Chinese patterns only, and all 20
        stored HKEX rows fell to `unclassified` - which is exactly what
        that bucket is for, and is how the gap was found rather than
        shipped. English patterns were added from the 14 distinct HKEX
        titles observed.
    So the category list is evidence, and it will need revisiting as more
    data lands - `unclassified` exists precisely to surface that.

WHY THERE IS A WEAK TIER AND NOT JUST candidate/noise
    A binary split was losing real corporate actions. Reading the
    discarded bucket showed two kinds of filing that are not signals
    under any current rule but are not housekeeping either: a share
    placement (向特定对象发行), which is the company raising money that
    may fund capacity, and a related-party transaction quota
    (日常关联交易额度), an annual commercial commitment with a figure.
    Calling those noise throws away the only visible trace of an action
    whose consequence appears in a later filing. `weak` keeps the row
    and its category without putting untested items in front of the
    extractor.

C1 MODEL CALL (§9.1) - MEASURED
    Of the 6 relevant rows, 1 resolves from patterns alone and 5 go to
    the model, at temperature 0 on anthropic/claude-sonnet-4-6.

    TWO real problems were found by testing, not predicted:

    1. The model invented an effective date. On the 2027 vehicle
       export-licensing notice it returned the 发文日期 (issue date,
       2026-09-29) as the effective date, which the spec explicitly
       forbids. Fixed in two places - the prompt now spells out that
       发文日期/发布日期 are issue dates, AND a guard drops any model
       effective_date the pattern matcher did not independently
       corroborate with a literal 自...起 match. Prompt wording alone is
       not a guard; the check is. `effective_date_disputed` records when
       it fires.

    2. The verdict was not stable. The same export-licensing notice
       returned BINDING three times and NON-BINDING twice across five
       consecutive calls. An earlier stability test had passed only
       because all six rows happened to agree on that one round - a
       single sample, over-read.

       That document is genuinely borderline: a PROCEDURAL notice about
       applying for an already-existing licence (it cites 商产发〔2012〕
       318号 as its authority) that nonetheless imposes dated
       obligations with sanctions. The spec's answer for exactly that
       case is UNCLEAR, and the prompt offers it - but a single call
       will not produce it, because each individual reading is
       confident.

       So every model verdict is now confirmed by a second call, and a
       disagreement becomes UNCLEAR (`binding_source='model_unstable'`)
       rather than letting a coin-flip decide between signal and weak.
       Verified: three consecutive full runs now give the same six
       verdicts, with the borderline row UNCLEAR each time.

C7 - MEASURED
    A name match, no threshold, no history. 5 synthetic cases pass
    including the spec's floor (a naming without an action context is
    WEAK, never Noise). 0 of the 6 real relevant rows name a US company
    in this window, which is the expected answer rather than a failure -
    no stored announcement is about one.

    US company aliases are transliterations (英伟达, 美光, 应用材料), not
    English names: Chinese official text almost never writes the English
    form, so matching on it alone would find nothing.

C1 MEASURED RESULT (2026-10-05, 160 stored policy rows)
    relevant 6 | irrelevant 154
    Only 4% of what the five policy sources publish touches this
    programme at all. SAMR files food-safety guidance, driving-school
    cartel penalties and holiday inspection notices; MIIT files
    industrial policy across every industry; Xinhua files general news.
    The sources are right; their output is mostly not about us.

    Two passing-mention bugs were found and fixed by reading the
    relevant bucket, both the same shape as the press layer's:
      - A first version matched sector vocabulary anywhere in 4,000
        characters of body and returned 15 rows, most wrong: an APEC
        ministerial press conference matched on a minister's quoted
        mention of 算力 and 人工智能芯片; a provincial quality story
        matched on a metrology centre's 钨与稀土 capability list.
        General vocabulary now counts only in the title or opening 600
        characters; strong vocabulary (出口管制, 反倾销, 实体清单 …)
        counts anywhere, because nothing says those in passing.
      - A binding export-licensing notice was labelled NON-BINDING
        because its body CITES 《汽车行业境外竞争行为与合规建设指引》 and
        建设指引 was being matched anywhere. Non-binding markers are now
        read from the title and opening only; binding markers stay wide,
        since an effective date legitimately appears at the end.

    Of the 6 relevant rows, exactly one carries a clear verdict from
    patterns alone (SAMR's 修订草案 公开征求意见 → NON-BINDING). The other
    five are `hint=None` and are what the §9.1 model call is for. That
    ratio is the argument for the two-gate design: 160 rows become 5
    model calls, not 160.

WHY A YEAR OF HISTORY WAS BACKFILLED, AND WHAT IT CHANGED
    The first version of this table was built from a two-week window: 94
    filings, 7 candidates, 0 unclassified. Backfilling a full year
    (`--days-back 365` on cninfo and HKEX, which are both date-RANGE
    queries so this costs one request per company, not one per day) gave
    631 filings and showed that window had been badly unrepresentative:

      two weeks:  94 filings,  7 candidates,   0 unclassified
      one year:  631 filings, 94 candidates, 108 unclassified

    The reason is cadence. Quarterly reporting simply did not happen
    inside the two-week window, so EVERY earnings filing was invisible -
    the single largest candidate category (64 of 94) did not exist in
    the sample the table was built from. SMIC's quarterly results, Hua
    Hong's interim results and Baidu's interim report all sat in
    `unclassified`, each a C2 signal being silently dropped.

    Other shapes a fortnight could not show: HKEX's monthly
    share-movement return (33 filings, the largest single noise group),
    use-of-proceeds reporting (13), broker continuing-supervision
    reports, and a share-for-assets acquisition.

    This is the argument for backfilling before deriving any rule, not
    after. A threshold fitted to the two-week sample would have been
    fitted to a distribution with no earnings in it at all.

C5 MEASURED
    Found a real Signal: Alibaba's June-quarter 2026 results state
    capital expenditures of RMB67,678 million, +75% against the same
    quarter of 2025 - past the spec's 20% threshold.

    A coverage gap was traced to its cause rather than worked around.
    On the first pass only Alibaba produced anything; Tencent and Baidu
    mentioned capex ZERO times across 54 stored bodies. The reason was
    upstream: Tencent's results announcement is a 50-page PDF whose
    capex line sits at character 19,113, while news-retrieval stored
    only the first 5 pages (7,153 characters). The figure was never
    fetched.

    Fixed on the fetch side, where it belonged - news-retrieval now
    reads 25 pages for results-type filings and 5 for everything else,
    since a results announcement front-loads its financial tables while
    a prospectus of the same length is appendix the whole way down.
    Re-fetching deepened 48 filings.

    That exposed a second, smaller gap here: Tencent reports capex as a
    bare table row ("Capital expenditures (d) 52,784 31,936 19,107")
    whose unit lives in the table header ("RMB in millions"), not beside
    the number. Now read, but only when that header is present.

    Coverage is 2 of 3 platforms: Alibaba (a Signal, with its stated
    +75%) and Tencent (two Weak rows - the table gives the figure but no
    change beside it). Baidu's filings mention capex only in a
    liquidity-boilerplate sentence with no figure, which is a real
    absence rather than a parsing failure.

WHY C4 (ACCELERATOR MILESTONES) IS NOT IMPLEMENTED
    Tested against the stored year, not deferred on a hunch. The three
    listed accelerator makers - Cambricon (688256), Hygon (688041),
    Loongson (688047) - produced 94 articles:

      77  cninfo filings      (governance: meetings, incentive plans,
                               legal opinions, board elections)
      17  English coverage check (headline only, no body)
       0  press_cn

    Searching all 94 for the spec's own C4 vocabulary (product launch
    with specifications, stated volume, named customer, procurement
    award) returned 3 matches, and ALL THREE are false positives: 量产
    and 中标 appearing inside a boilerplate 提质增效重回报 action-plan
    self-assessment, and 客户 inside a use-of-proceeds explanation.

    So the signal the spec describes - "a product launch with stated
    specifications, a stated production volume, or a named customer" -
    does not appear in these companies' regulatory filings at all over
    a full year. That is consistent with what filings ARE: a company
    announces a chip at a conference and files a shareholder-meeting
    resolution.

    Where it would appear is the press layer, and press_cn returned
    ZERO accelerator articles over the year - not because the filter
    is wrong but because the four reachable outlets are thin (see
    news-retrieval's own note on the free-source ceiling). The English
    coverage check does find them ("Alibaba Unveils New AI Chip",
    "Chinese AI Chips Could Flood...") but stores headlines only, with
    no body to extract a volume or customer from.

    Implementing C4 now would mean writing a rule against a source that
    carries no instances of what it looks for. The honest state is: the
    universe and vocabulary are ready, the input is not.

WHY C2 USES THE FILING'S OWN YoY, NOT A TRAILING SERIES
    The spec's C2 rule is "revenue growth more than two spreads above
    its own trailing pattern" - the habit-based approach Japan uses.
    That was attempted and does not work here, for a reason the data
    settled rather than an opinion:

      companies with >=1 revenue observation over a full year:  4
      companies with >=3 (the minimum for any trailing pattern): 0

    Only ~4 filings per company per year carry a labelled revenue
    figure at all, so a per-company series cannot be built from this
    source no matter how far back the backfill goes. Deepening history
    would not fix it; the limit is filing frequency, not window length.

    What IS available is the change the issuer states about ITSELF.
    24 of 64 earnings filings quote a year-on-year figure, and that is
    self-contained - the company has already done the comparison
    against its own prior period, so no stored history is needed.

    Revenue YoY actually extracted over the stored year (n=8):
      +11.6% Loongson   +19.4% SMIC      +27.7% N.RareEarth
      +34.9% AMEC (x2)  +36.8% N.RareEarth
      +107%  N.RareEarth                 +178.7% GigaDevice

    That is a real distribution, and it is the input a Gate 3 threshold
    should be derived from. Note it is not yet enough: eight points
    across five companies cannot separate "unusual for this company"
    from "unusual for the sector", which is the distinction the spec's
    own wording ("its OWN trailing pattern") asks for. More quarters
    will fix this one, because the input accrues per filing rather than
    needing a per-company run.

GATE 2 DISTRIBUTION (1 year, 39 candidates carrying a figure)
    Recorded as the evidence a Gate 3 threshold must be derived FROM -
    not as a threshold. Values are the largest amount in each filing,
    normalised to base currency units:

      capacity       n=5   med 1.5e9   max 8.2e9
      earnings       n=4   med 2.5e9   max 6.7e9
      earnings_en    n=19  med 2.2e10  max 2.4e11
      investment     n=7   med 3.2e9   max 3.7e10
      investment_en  n=3   med 1.0e10  max 8.3e10
      orders         n=1   1.7e10

    Note `orders` is still n=1 after a full year. The spec's C2 rule
    ("two spreads above its own trailing pattern") needs a per-company
    series; one filing in twelve months cannot produce one. That is a
    finding about where the substitution signal actually lives, not a
    gap to be filled by a lower threshold.

    One extraction bug the distribution exposed: an asset-purchase
    filing reported max_amount ¥43 against a category median of ¥1.5bn,
    because 43.34元/股 is a per-SHARE issue price. Per-unit amounts are
    now flagged (`per_unit`) and excluded from max_amount - a real
    disclosed fact, just not a transaction size.

GATE 2 MEASURED (7 candidates)
    5 of 7 carry figures, 2 genuinely do not (a JV supplemental notice
    filed in both languages, which really does just confirm an
    arrangement). Figures are normalised at extraction so a later
    comparison never has to know which unit a row arrived in:

      ACM Shanghai  orders on hand   1.71e10 CNY  +88.2% 同比增加
      Baidu         interim report   5.12e10 RMB  +36% year increase
      AMEC          fund stake       3.20e09 CNY  49% 募资规模
      JL MAG        capital raise    5.00e08 CNY
      JL MAG        progress update  5.50e07 CNY

    Percentages carry their preceding words verbatim, and that turned
    out to matter more than expected. The JL MAG filing yields twelve
    percentages, of which 100% is a subsidiary holding, 43.6163% /
    15.8604% / 11.8953% are limited-partner stakes in a fund table, and
    none is a growth rate. A bare number could not be told apart from
    ACM Shanghai's 88.2% order growth; the context string can. No rule
    guesses which is which - that is Gate 3's job, with the context
    available to it.

MEASURED RESULT (2026-10-05, 94 stored filings)
    candidates 7 | weak 14 | noise 73 | unclassified 0
    The 7 candidates: ACM Shanghai's orders-on-hand disclosure, four
    capital injections / fund participations, a Hua Hong JV formation
    (filed in both languages, so it appears once per source_type), and
    an HKEX interim report.

    Two refinements came from reading the weak bucket after the split,
    neither predicted: HKEX's "Next Day Disclosure Return - Changes in
    issued shares and share buybacks" is a mechanical daily form whose
    title contains "share buybacks" as a standing label, not because a
    buyback happened; and a law firm's compliance opinion ABOUT a share
    placement is paperwork, not the raise. Both are caught by
    _ALWAYS_NOISE_RE, which is tested before every other tier.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.request import Request, urlopen

from pipeline.china_companies import codes_with_role, read_through_for

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate 1: filing-type classification
# ---------------------------------------------------------------------------
#
# Every pattern below is anchored to filings actually observed in the
# stored data on 2026-10-05, with the count it matched. This is a
# starting table built from one window, not a claim of completeness -
# same footing as Taiwan's _CLAUSE_CODE_TABLE.

# WEAK: a real corporate action, but not one of the seven China signal
# types. Kept rather than discarded, for two reasons the stored data
# makes concrete:
#
#   - A share placement (向特定对象发行) IS a company raising money, and
#     what it funds may well be capacity - which is C3. Hwatsing filed
#     three of these in this window. Calling the paperwork noise throws
#     away the only visible trace of a capital raise whose use of
#     proceeds appears in a later filing.
#   - A related-party transaction quota (日常关联交易额度) is a real
#     commercial commitment with a figure attached, filed annually.
#
# These are not candidates - no current rule reads them, and promoting
# them would put untested items in front of the extractor. But they are
# not noise either, and the distinction is cheap to keep: a `weak`
# verdict stores the row with its category so a later rule can reach
# back for it, instead of the row being gone.
_WEAK_PATTERNS: list[tuple[str, str]] = [
    # 3 of 94. Share placements and the custody accounts for their
    # proceeds. The PROCESS, not the use - but the use is downstream of
    # it and this is where the raise becomes visible.
    ("capital_raise", r"向特定对象发行|发行情况|募集资金专户"),
    # 1 of 94. An annual commercial commitment with a figure.
    ("related_party_quota", r"日常关联交易"),
    # 10 of 94 in Chinese, 3 in English. Buybacks, bond conversions,
    # pledges. Real capital actions; the China spec has no rule for them
    # (unlike Japan's J6 buyback rule), so they sit here rather than as
    # candidates - visible if a rule is ever added, not in the way now.
    ("capital_action",
     r"回购|转债|质押|转换价格|可转换"),
    ("capital_action_en",
     r"(?i)\b(share buyback|convertible bonds?|conversion and cancellation)"),
]

# Corporate housekeeping. Carries no tradable fact.
_NOISE_PATTERNS: list[tuple[str, str]] = [
    # 30 of 73. Meeting notices, agendas, resolutions, and the board
    # committee opinions that travel with them.
    ("meeting",
     r"股东(大)?会|董事会|监事会|会议资料|会议材料|议事规则"
     r"|提名委员会|薪酬与考核委员会|审核意见"),
    # Insider share disposals by officers and major holders. Real, but
    # about an individual's holding, not the company's business - and
    # the China spec has no ownership rule (unlike Japan's J6).
    ("shareholding", r"减持|增持|权益变动"),
    # Routine exchange returns and administrative notices with no
    # content of their own. 日常关联交易 was moved OUT of this group to
    # `weak` - it is a commercial commitment with a figure, unlike a
    # mechanical daily return.
    ("routine_return", r"翌日披露报表|责任险|诉讼进展"),
    # 6. Articles of association, registered capital, officer changes.
    ("governance",
     r"公司章程|注册资本|辞任|换届|选举|聘任|董事候选人"),
    # 6. Employee share schemes and their progress reports.
    ("incentive", r"激励计划|持股计划|限制性股票|奖励股份|激励对象"),
    # 5. Law-firm opinions and verification reports accompanying the above.
    ("legal_opinion", r"法律意见|核查意见|验资报告|合规性报告"),
    # 3. Dividends and distributions.
    ("distribution", r"权益分派|现金分红|差异化分红"),
    # --- English, for hkex_filing -------------------------------------
    # Hong Kong listing rules require English, so these titles are in it.
    # Measured against the 14 distinct HKEX titles stored on 2026-10-05:
    # 12 of them are housekeeping in exactly the same categories as the
    # mainland ones, just in another language. Adding the Chinese
    # patterns alone left all 20 HKEX rows `unclassified` - which is the
    # bucket working as intended, and is how this gap was found.
    ("meeting_en",
     r"(?i)\b(general meeting|board meeting|proxy form|poll results"
     r"|voting results|notice of (extraordinary|annual))"),
    ("incentive_en",
     r"(?i)\b(share option scheme|share award|grant of (share )?options)"),
    ("routine_return_mechanical_en",
     r"(?i)\bnext day disclosure return"),
    ("routine_return_en",
     r"(?i)\b(notification letter|reply form"
     r"|has just been published by the issuer"
     # The single largest unclassified group in the year backfill: 33
     # filings, HKEX's standing monthly share-movement return.
     r"|monthly return (of|for) equity issuer"
     r"|证券变动月报表"
     r"|documents on display|closure of register"
     r"|notification of approval of the publication)"),
    # Use-of-proceeds reporting. 13 filings over the year. A company
    # saying where last year's raise went is not a new commitment - the
    # raise itself is already `capital_raise` in the weak tier.
    ("proceeds_report",
     r"募集资金(存放|使用|管理)|闲置募集资金|募投项目.*(进展|变更)"
     r"|预先投入募集资金"),
    # Broker/sponsor continuing-supervision reports and auditor
    # attestations filed alongside a company's own results. 6+ over the
    # year, always third-party paperwork about a filing, never the
    # filing.
    ("sponsor_report",
     r"持续督导|督导.*(报告|意见)|风险评估报告|鉴证报告"
     r"|非经营性资金占用"),
    # A board-mandated "improve quality and returns" action plan and its
    # periodic self-assessment. 4+ over the year, entirely boilerplate.
    ("quality_plan", r"提质增效重回报"),
    # Debt instruments - registration, issuance, notes. Real capital
    # actions but the China spec has no rule for them, same reasoning as
    # the buyback category.
    ("debt_admin",
     r"债务融资工具|中期票据|资产支持商业票据|公司债券.*(注册|发行)"),
    ("corporate_admin_en",
     r"(?i)\b(memorandum and articles|articles of association"
     r"|amendments? of articles|notice of listing"
     r"|grant of awards|restricted share units"
     r"|conversion rate of the convert)"),
    # An overseas regulatory announcement is a mirror of something the
    # company already filed on the other exchange - the original is
    # already in the pool, so classifying the mirror would double-count.
    ("overseas_mirror",
     r"(?i)overseas regulatory announcement|海外监管公告"),
    # Share-option exercise and lock-up expiry mechanics.
    ("share_mechanics",
     r"股票期权.*(行权|上市流通)|限售股.*上市流通|首次公开发行前"),
]

# A tradable fact may be present. These go to Gate 2 for extraction.
_CANDIDATE_PATTERNS: list[tuple[str, str]] = [
    # C2, the substitution read. 1 of 73 (ACM Shanghai's orders on hand).
    ("orders", r"在手订单|订单|中标|重大合同|供货"),
    # C3 capacity. 0 observed in this window - kept because the spec's
    # central substitution signal lives here and its absence so far is
    # itself worth measuring, not a reason to stop looking.
    ("capacity", r"扩产|产能|新建.*生产线|募投项目|建设项目"),
    # C3/C5 investment. 4 of 73 - subsidiary capital injections, fund
    # participation, and the JV formation the spec did not anticipate.
    ("investment",
     r"增资|对外投资|设立.*(基金|公司|子公司)|合营企业|收购"
     # 发行股份购买资产 - a share-for-assets acquisition. Hua Hong filed
     # several over the year; genuine M&A, not the share-issuance
     # paperwork the `capital_raise` weak tier covers.
     r"|购买资产|重大资产(重组|购买)"),
    # The figures themselves. 0 observed in mainland filings - issuers
    # file these on a quarterly cadence this window did not span - but
    # HKEX's INTERIM REPORT 2026 did land, which is why the English
    # pattern below is not speculative.
    ("earnings",
     r"业绩(预告|快报|说明|公告)|营业收入|净利润|年度报告|半年度报告|季度报告"
     # 中期业绩公告 / 中期报告 - the HK-listed names file these in Chinese
     # too, under a 港股公告 prefix. Found in the year backfill.
     r"|中期(业绩|报告)|年度业绩"
     # 截至...止三个月未经审核业绩公布 - SMIC's quarterly, filed in
     # Chinese under a 港股公告 prefix.
     r"|未经审核业绩|业绩公布|利润分配方案"),
    # --- English, for hkex_filing -------------------------------------
    # 2 of the 14 distinct HKEX titles are genuine candidates: a joint
    # venture formation and an interim report.
    ("investment_en",
     r"(?i)\b(joint venture|acquisition|formation of a|subscription of"
     r"|capital (increase|injection))"),
    # A results announcement is the earnings figure itself. Found only
    # after a full year of HKEX history was backfilled: "SMIC REPORTS
    # UNAUDITED RESULTS FOR THE THREE MONTHS ENDED ..." (3 filings),
    # "ANNOUNCEMENT OF 2026 INTERIM RESULTS", "ANNOUNCEMENT OF ANNUAL
    # RESULTS" and "Hua Hong Semiconductor Limited Reports ..." all sat
    # in `unclassified` on the two-week window, because quarterly
    # reporting simply did not happen inside it.
    ("earnings_en",
     r"(?i)\b(interim report|annual report|quarterly report"
     r"|results announcement|profit (warning|alert)"
     # "Reports N..." - Hua Hong's own house style is
     # "... Reports 2026 Second Quarter Results", so the word between
     # Reports and Results is a year or a quarter, not a fixed phrase.
     r"|reports\b.{0,40}\bresults"
     r"|reports (unaudited |audited )?(results|net|revenue)"
     # "ANNOUNCEMENT OF THE RESULTS FOR THE THREE MONTHS ENDED ..."
     r"|announcement of .{0,24}results\b"
     r"|(interim|annual|quarterly) results announcement)"),
    ("orders_en",
     r"(?i)\b(order book|contract award|supply agreement"
     r"|major contract)"),
    ("capacity_en",
     r"(?i)\b(capacity expansion|new (fab|plant|production line)"
     r"|capital expenditure)"),
]

# Checked BEFORE everything else. Two shapes that would otherwise be
# promoted by a pattern meant for something real:
#
#   - "Next Day Disclosure Return - Changes in issued shares and share
#     buybacks" is HKEX's mechanical daily return. Its title contains
#     "share buybacks" as a standing form label, not because a buyback
#     happened, so the capital_action pattern claimed it.
#   - A law firm's or broker's compliance opinion ABOUT a share
#     placement is paperwork about the raise, not the raise. Three of
#     these landed in capital_raise alongside the real filing.
#
# Both were found by reading the weak bucket after the three-tier split,
# not predicted.
_ALWAYS_NOISE_RE: list[tuple[str, re.Pattern[str]]] = [
    ("routine_return_mechanical_en",
     re.compile(r"(?i)^\s*next day disclosure return")),
    ("legal_opinion",
     re.compile(r"法律意见|核查意见|验资报告|合规性报告")),
]

_NOISE_RE = [(name, re.compile(p)) for name, p in _NOISE_PATTERNS]
_WEAK_RE = [(name, re.compile(p)) for name, p in _WEAK_PATTERNS]
_CANDIDATE_RE = [(name, re.compile(p)) for name, p in _CANDIDATE_PATTERNS]


def classify_filing_type(title: str) -> tuple[str, str]:
    """Decide whether one filing title is worth looking at further.

    Returns ``(verdict, category)`` where verdict is one of
    ``candidate`` / ``weak`` / ``noise`` / ``unclassified``.

    Order is candidate, then weak, then noise, and it matters at each
    step. A real signal is still filed as a 公告 and will often also
    match a housekeeping pattern - ACM Shanghai's orders-on-hand
    disclosure is a 自愿性披露公告, and JL MAG's capital injection carries
    关联交易 wording that the routine-return pattern would otherwise
    claim. Checking noise first would discard both.

    Three tiers rather than two, because a binary split was losing real
    corporate actions. A share placement is the company raising money
    that may fund capacity (C3); a related-party transaction quota is a
    commercial commitment with a figure. Neither is a candidate - no
    current rule reads them - but calling them noise throws away the
    only trace of an action whose consequence shows up in a later
    filing. ``weak`` keeps the row and its category without putting
    untested items in front of the extractor.

    ``unclassified`` is NOT a synonym for noise. It means a filing shape
    this table has never seen, which is the one outcome that can silently
    lose a signal, so it is surfaced rather than swallowed. A first
    version of this table had Chinese patterns only and sent all 20
    stored HKEX filings here - which is how that gap was found. A rising
    count is the signal that the table needs revisiting.
    """
    if not title:
        return "unclassified", "-"
    # Forms and third-party paperwork that a real-action pattern would
    # otherwise claim - see _ALWAYS_NOISE_RE for the two cases.
    for name, pattern in _ALWAYS_NOISE_RE:
        if pattern.search(title):
            return "noise", name
    for name, pattern in _CANDIDATE_RE:
        if pattern.search(title):
            return "candidate", name
    for name, pattern in _WEAK_RE:
        if pattern.search(title):
            return "weak", name
    for name, pattern in _NOISE_RE:
        if pattern.search(title):
            return "noise", name
    return "unclassified", "-"


# ---------------------------------------------------------------------------
# C1: policy action
# ---------------------------------------------------------------------------
#
# The spec calls this the highest-impact category in the module, and names
# the hard problem precisely: not detecting an announcement, but judging
# whether it is a BINDING measure or a statement of intent.
#
# WHAT THE REAL DATA SHOWS (160 stored policy rows, 2026-10-05)
#   Only 6 of 160 (4%) touch export control or this universe's sector at
#   all. The rest are genuinely unrelated government business - SAMR
#   publishes food-safety guidance, driving-school cartel penalties and
#   holiday inspection notices; MIIT publishes industrial policy across
#   every industry; Xinhua publishes general news. The ministries are
#   right sources, but their output is overwhelmingly not about us.
#
#   So C1 needs a RELEVANCE gate before the binding call. Sending 160
#   announcements to an LLM to ask "is this binding" would spend 154
#   calls establishing that a concrete-cartel penalty is not a
#   semiconductor export control.
#
#   Only 3 of 160 carry a 【发布文号】 document number - the structured
#   header appears on MOFCOM's 政策发布 filings and essentially nowhere
#   else. It is therefore a strong POSITIVE signal when present, and
#   says nothing when absent.
#
# WHY TWO GATES AND NOT ONE
#   Relevance is cheap and deterministic: does this announcement mention
#   export control, a controlled item, a named company in our read-through
#   set, or a sector we track? Binding-vs-draft is a judgment about
#   document language and is what the spec's §9.1 prompt exists for. The
#   first narrows 160 to a handful; the second runs only on those.

# Vocabulary that marks an announcement as touching this programme. Built
# from the 6 relevant rows found in the stored data plus the measure types
# the spec's §3 names (export licensing, procurement exclusion, antitrust
# against foreign firms, customs measures).
_C1_RELEVANCE_PATTERNS: list[tuple[str, str]] = [
    # Export control proper - the spec's primary concern.
    ("export_control",
     r"出口管制|两用物项|管制清单|管制物项|出口许可|限制出口|技术出口"
     r"|不可靠实体|实体清单|最终用户"),
    # The materials lever. §2.3 calls this the one Chinese signal that
    # reaches outside the AI/semi universe.
    ("critical_minerals",
     r"稀土|稀有金属|钨|锗|镓|锑|石墨|永磁|关键矿产"),
    # The sector itself.
    ("semiconductor",
     r"半导体|芯片|集成电路|晶圆|光刻|刻蚀|先进制程|算力|人工智能芯片"),
    # Trade remedies and tariffs aimed at, or affecting, foreign firms.
    ("trade_remedy",
     r"反倾销|反补贴|保障措施|关税(?:配额|税率|调整)|加征关税"),
    # Procurement exclusion and security review - the 2023 memory template.
    ("procurement_security",
     r"网络安全审查|安全审查|政府采购.*(排除|限制|禁止)|采购禁令"),
]
_C1_RELEVANCE_RE = [(n, re.compile(p)) for n, p in _C1_RELEVANCE_PATTERNS]

# Language that marks a document as NOT yet binding. The spec is explicit
# that a draft for comment and a measure with an effective date are
# completely different events that use similar language.
_C1_NONBINDING_PATTERNS: list[tuple[str, str]] = [
    # A draft published for public comment.
    ("draft_for_comment", r"征求意见|意见稿|公开征求|反馈意见"),
    # Interpretation of a measure published elsewhere - MOFCOM files
    # these under 政策解读 and they restate rather than enact. 5 of the 10
    # stored MOFCOM rows are these.
    ("policy_interpretation", r"政策解读|负责人解读|解读《"),
    # Plans, guidelines and directions that commit to nothing dated.
    ("plan_or_guideline", r"行动方案|指导意见|实施意见|建设指引|规划纲要"),
    # An official's remarks, however senior.
    ("remarks", r"答记者问|新闻发布会|发布会.*介绍|负责人就.*answer"),
]
_C1_NONBINDING_RE = [(n, re.compile(p)) for n, p in _C1_NONBINDING_PATTERNS]

# Language that marks a document as binding. An effective date is the
# strongest marker the spec names.
_C1_BINDING_PATTERNS: list[tuple[str, str]] = [
    ("effective_date", r"自\s*20\d{2}\s*年.{0,12}?日起|自公布之日起|即日起施行"
                       r"|自发布之日起"),
    ("decision", r"决定(?:对|自|如下)|予以(?:批准|禁止|终止)"),
    ("announcement_number", r"公告\s*20\d{2}\s*年第\s*\d+\s*号"),
    ("investigation_opened", r"立案(?:调查|审查)|发起调查|启动调查"),
]
_C1_BINDING_RE = [(n, re.compile(p)) for n, p in _C1_BINDING_PATTERNS]

# 【发文日期】2026年09月22日 - the document's own stated date, present on
# MOFCOM 政策发布 filings. Distinct from the publication date, and the
# spec is explicit that an effective date must never be inferred.
_C1_EFFECTIVE_DATE_RE = re.compile(
    r"自\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日起")


# How much of the body counts as "about" the announcement. A government
# page's opening carries the subject; by 4,000 characters in, a
# conference report is quoting a minister listing every technology China
# works on. Matching that deep produced false positives on every loose
# term - 算力 inside an APEC speech, 稀土 inside a provincial metrology
# centre's capability list, 关税 inside consumer-policy prose.
_C1_BODY_WINDOW = 600
# Entity mentions are matched over a wider window than C7's verdict -
# see attach_named_us_entities. 5000 covers every real hit in the stored
# year (deepest at char 3,764) with headroom, while still stopping well
# short of a 20,000-character annual report's appendices.
_NAMED_IN_TEXT_WINDOW = 5000

# Terms specific enough to stand on their own anywhere in the window.
# An announcement that says 出口管制 or 反倾销 is about export control or
# a trade remedy, full stop.
_C1_STRONG_RE = re.compile(
    r"出口管制|两用物项|管制清单|管制物项|出口许可|限制出口"
    r"|不可靠实体|实体清单|反倾销|反补贴|网络安全审查|加征关税")


def classify_policy_relevance(title: str, body: str) -> tuple[bool, list[str]]:
    """Does this announcement touch export control, controlled materials,
    the semiconductor sector, trade remedies or procurement security?

    Returns ``(is_relevant, matched_categories)``. Deterministic and
    cheap - this runs on every policy row so the expensive binding call
    runs on almost none of them.

    TWO-SPEED MATCHING, and the reason is measured. A first version
    matched any vocabulary term against the first 4,000 characters of
    body and returned 15 of 160 rows, most of them wrong: an APEC
    ministerial press conference matched `semiconductor` because a
    minister's quoted answer mentions 算力 and 人工智能芯片; a provincial
    quality-infrastructure story matched `critical_minerals` because a
    metrology centre's capability list mentions 钨与稀土; consumer-policy
    prose matched `trade_remedy` on a passing 关税. All passing
    mentions - the same failure the press layer showed when matching on
    article bodies instead of headlines.

    So: a STRONG term (出口管制, 反倾销, 实体清单 …) is decisive wherever
    it appears in the window, because nothing says those in passing. A
    general sector term (半导体, 稀土, 算力 …) only counts if it appears
    in the TITLE or the opening 600 characters, which is where a
    government page states its actual subject.
    """
    title = title or ""
    head = f"{title} {(body or '')[:_C1_BODY_WINDOW]}"
    wide = f"{title} {(body or '')[:4000]}"

    matched: list[str] = []
    for name, pattern in _C1_RELEVANCE_RE:
        # General sector vocabulary: title or opening only.
        if pattern.search(head):
            matched.append(name)
            continue
        # Strong vocabulary: anywhere in the window. Only the terms that
        # are themselves strong qualify, so a category matching a loose
        # term deep in the body still does not count.
        for strong in _C1_STRONG_RE.findall(wide):
            if pattern.search(strong):
                matched.append(name)
                break
    return bool(matched), matched


def extract_policy_fields(title: str, body: str) -> dict[str, Any]:
    """The §7.1 data points, pattern-extracted - no model call.

    The spec's §6 observation is what makes this possible: Chinese policy
    language is formulaic, so the recurring phrases can be matched rather
    than the whole document translated.

    ``binding_hint`` is a HINT, never a verdict. Where the markers
    disagree or neither fires, it is None and the LLM call decides - the
    spec's §9.1 prompt allows UNCLEAR as a real answer, and so does this.
    """
    title = title or ""
    # Non-binding markers are read from the TITLE and opening only, for
    # the same reason the relevance gate is: a binding export-licensing
    # notice CITES 《汽车行业境外竞争行为与合规建设指引》 in its body, and
    # matching 建设指引 anywhere labelled that notice NON-BINDING -
    # exactly backwards. A document's own nature is stated at its top; a
    # mention deeper in is usually a reference to a different document.
    head = f"{title} {(body or '')[:_C1_BODY_WINDOW]}"
    # Binding markers stay wide: an effective date or a decision clause
    # legitimately appears at the END of a notice, after the substance.
    blob = f"{title} {(body or '')[:6000]}"

    nonbinding = [n for n, p in _C1_NONBINDING_RE if p.search(head)]
    binding = [n for n, p in _C1_BINDING_RE if p.search(blob)]

    # Never inferred - only taken when the document states it.
    effective_date = None
    m = _C1_EFFECTIVE_DATE_RE.search(blob)
    if m:
        effective_date = (f"{m.group(1)}-{int(m.group(2)):02d}-"
                          f"{int(m.group(3)):02d}")

    # A hint only where the evidence is one-sided. A document carrying
    # both a draft marker and an effective date is exactly the ambiguous
    # case the model is for.
    binding_hint: str | None = None
    if binding and not nonbinding:
        binding_hint = "BINDING"
    elif nonbinding and not binding:
        binding_hint = "NON-BINDING"

    return {
        "binding_markers": binding,
        "nonbinding_markers": nonbinding,
        "binding_hint": binding_hint,
        "effective_date": effective_date,
    }


# The spec's §9.1 prompt, as written. Three constraints in it are
# load-bearing and are repeated here because they are what keep this
# from fabricating: never infer an effective date that is not written,
# never name a company not named in the text, answer UNCLEAR rather than
# guess.
_C1_BINDING_SYSTEM_PROMPT = (
    "You read Chinese government announcements and decide whether each "
    "is a BINDING measure or a NON-BINDING statement.\n\n"
    "BINDING means the announcement creates or changes an obligation:\n"
    "- an export licensing requirement, with or without a date\n"
    "- a restriction, prohibition or quota\n"
    "- an investigation formally opened\n"
    "- a procurement exclusion or security review decision\n"
    "- a tariff or duty change\n\n"
    "NON-BINDING means it does not yet change anything:\n"
    "- a draft published for public comment\n"
    "- a policy direction, plan or guideline\n"
    "- a restatement of an existing measure\n"
    "- an official's remarks, however senior\n\n"
    "Extract, using only what is stated:\n"
    "- issuing body\n"
    "- measure type\n"
    "- named products, materials or technology categories\n"
    "- named foreign companies or countries, if any\n"
    "- effective date, if stated\n\n"
    "Never infer an effective date that is not written.\n"
    "An effective date is the date the measure STARTS TO APPLY, written "
    "as 自...起施行 / 自...起执行 / 自...日起. It is NOT the date the "
    "document was issued or published - 发文日期, 发布日期 and the date in "
    "the document number are issue dates, not effective dates. If the "
    "text gives only an issue date, answer null for effective_date.\n"
    "Never name a company that is not named in the text.\n"
    "If binding status is genuinely unclear, answer UNCLEAR rather than "
    "guessing.\n\n"
    "Answer as JSON and nothing else:\n"
    '{"binding": "BINDING"|"NON-BINDING"|"UNCLEAR", '
    '"issuing_body": str|null, "measure_type": str|null, '
    '"named_items": [str], "named_foreign": [str], '
    '"effective_date": str|null}'
)

# A borderline document gets the same verdict from the model only some of
# the time. Measured live on the 2027 vehicle export-licensing notice:
# five consecutive calls at temperature 0 returned BINDING three times and
# NON-BINDING twice. That document is genuinely borderline - it is a
# PROCEDURAL notice about how to apply for an already-existing licence
# (it cites 商产发〔2012〕318号 as its authority), yet it imposes dated
# obligations with sanctions for non-compliance.
#
# The spec's own answer for that case is UNCLEAR, and the §9.1 prompt
# offers it - but a single call will not produce it, because each
# individual reading is confident. So C1 asks twice and only accepts a
# verdict both calls agree on; a disagreement becomes UNCLEAR, which is
# the honest answer and routes to weak_signal rather than letting a
# coin-flip decide between signal and weak.
#
# Two calls, not three: the cost is per relevant row and there are ~5 of
# those per window, so this is ~10 calls a run. A third would buy a
# majority vote, but a majority on a document the model cannot read
# consistently is still a coin-flip wearing a hat.
_C1_CONFIRMATION_CALLS = 2

_C1_LLM_TIMEOUT = 60.0
# How much of an announcement the model sees. Real bodies run 1-8k
# characters; the binding/non-binding nature is stated at the top and the
# effective date at the bottom, so both ends matter more than the middle.
_C1_LLM_HEAD = 3000
_C1_LLM_TAIL = 1500


def _c1_call_model(title: str, body: str,
                   model: str | None = None) -> dict[str, Any] | None:
    """Ask the model for the §9.1 binding verdict on one announcement.

    Returns None on any failure - a missing verdict leaves the row with
    its pattern-derived hint and is not an error. Fail-open, the same
    convention every classifier in this service uses.
    """
    import config

    api_key = config.OPENAI_API_KEY
    if not api_key:
        logger.warning("[CHINA] c1: OPENAI_API_KEY unset, skipping model call")
        return None

    text = body or ""
    if len(text) > _C1_LLM_HEAD + _C1_LLM_TAIL:
        text = (text[:_C1_LLM_HEAD] + "\n...[middle omitted]...\n"
                + text[-_C1_LLM_TAIL:])

    payload = {
        # CHINA_SIGNAL_MODEL, not OPENAI_MODEL - see its own note in
        # config.py. Every LLM call in this domain uses the same tier.
        "model": model or config.CHINA_SIGNAL_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _C1_BINDING_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"TITLE: {title or ''}\n\nTEXT:\n{text}"},
        ],
    }
    try:
        req = Request(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=_C1_LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = (data.get("choices", [{}])[0]
                   .get("message", {}).get("content", "") or "").strip()
    except Exception as exc:
        logger.warning("[CHINA] c1 model call failed title=%r: %s",
                       (title or "")[:60], exc)
        return None

    # Models sometimes wrap JSON in a fenced block despite the
    # instruction - strip it rather than failing the row.
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    try:
        parsed = json.loads(content)
    except Exception:
        logger.warning("[CHINA] c1 model returned non-JSON: %r",
                       content[:120])
        return None
    if parsed.get("binding") not in ("BINDING", "NON-BINDING", "UNCLEAR"):
        logger.warning("[CHINA] c1 model returned bad verdict: %r",
                       parsed.get("binding"))
        return None
    return parsed


def classify_policy_binding(
    relevant: list[dict[str, Any]], model: str | None = None,
) -> list[dict[str, Any]]:
    """Attach a binding verdict to each relevant policy row.

    The pattern hint is used where it exists and the model is called only
    where it does not. Measured on the stored data, that is 5 model calls
    per 160 policy rows rather than 160 - which is the entire reason the
    relevance gate runs first.

    The model's own extracted fields are kept SEPARATE from the
    pattern-extracted ones rather than merged: `effective_date` from the
    patterns is a literal match on 自...日起 in the text, while the
    model's is its own reading. Where they disagree that is worth seeing,
    not silently resolving.
    """
    out: list[dict[str, Any]] = []
    for row in relevant:
        hint = row.get("binding_hint")
        if hint:
            out.append({**row, "binding": hint, "binding_source": "pattern"})
            continue
        # Asked twice - see _C1_CONFIRMATION_CALLS. A verdict the model
        # does not repeat is not a verdict.
        verdicts = [
            _c1_call_model(row.get("title") or "", row.get("body") or "",
                           model=model)
            for _ in range(_C1_CONFIRMATION_CALLS)
        ]
        got = [v for v in verdicts if v]
        if not got:
            # No answer at all is not a verdict either. UNCLEAR routes to
            # weak_signal downstream, never to a guess.
            out.append({**row, "binding": "UNCLEAR",
                        "binding_source": "unavailable"})
            continue

        labels = {v["binding"] for v in got}
        verdict = got[0]
        if len(got) < _C1_CONFIRMATION_CALLS or len(labels) > 1:
            # Disagreed with itself, or one call failed and the other
            # cannot be corroborated. The document's fields are still
            # worth keeping - they are extraction, not judgment - but
            # the binding call is not.
            logger.info(
                "[CHINA] c1 unstable verdict %s title=%r -> UNCLEAR",
                sorted(labels), (row.get("title") or "")[:60])
            verdict = {**verdict, "binding": "UNCLEAR"}
        # The model reported an effective date the document does not
        # state - confirmed live on the 2027 vehicle export-licensing
        # notice, where it returned the 发文日期 (issue date, 2026-09-29)
        # as the effective date. The spec is explicit that an effective
        # date must never be inferred, so a model date is only kept when
        # the pattern matcher independently found 自...起 in the text.
        # Prompt wording alone is not a guard; this is.
        model_eff = verdict.get("effective_date")
        pattern_eff = row.get("effective_date")
        effective_date_disputed = bool(model_eff and not pattern_eff)
        if effective_date_disputed:
            logger.info(
                "[CHINA] c1 dropped model effective_date=%r (no 自...起 in "
                "text) title=%r", model_eff, (row.get("title") or "")[:60])

        out.append({
            **row,
            "binding": verdict["binding"],
            "binding_source": ("model" if len(labels) == 1
                               and len(got) == _C1_CONFIRMATION_CALLS
                               else "model_unstable"),
            "model_issuing_body": verdict.get("issuing_body"),
            "model_measure_type": verdict.get("measure_type"),
            "model_named_items": verdict.get("named_items") or [],
            "model_named_foreign": verdict.get("named_foreign") or [],
            # Kept only when corroborated by the literal text match.
            "model_effective_date": model_eff if not effective_date_disputed
            else None,
            # Recorded rather than silently discarded - a rising count
            # means the prompt is drifting.
            "effective_date_disputed": effective_date_disputed,
        })
    logger.info("[CHINA] c1 binding verdicts: %s",
                {v: sum(1 for r in out if r["binding"] == v)
                 for v in ("BINDING", "NON-BINDING", "UNCLEAR")})
    return out


# ---------------------------------------------------------------------------
# C7: regulatory action against a named US company
# ---------------------------------------------------------------------------
#
# The spec's §7.7 is the simplest rule in the module and the only one with
# no Noise case at all:
#   Signal  - always, when an American company is named in an
#             investigation, a security review, a procurement exclusion or
#             a licensing action
#   Weak    - industry-wide measures that affect an American company
#             without naming it
#   Noise   - never. An action naming a foreign company is always at
#             least Weak.
#
# No threshold, no history, no distribution. It is a name match, which is
# why it ships before anything in C2/C3.
#
# The US names are passed in by the caller rather than hardcoded here -
# they live in research-universe, and this module has no import of it for
# the same reason korea_signal_classifier takes its universe as an
# argument.

# Written forms a Chinese announcement uses for US companies. Chinese
# official text transliterates rather than using the English name, so a
# match on the English alone finds almost nothing.
_C7_US_COMPANY_ALIASES: dict[str, list[str]] = {
    "NVDA": ["英伟达", "辉达", "Nvidia", "NVIDIA"],
    "AMD": ["超威", "AMD"],
    "INTC": ["英特尔", "Intel"],
    "MU": ["美光", "Micron"],
    "AMAT": ["应用材料", "Applied Materials"],
    "LRCX": ["泛林", "拉姆研究", "Lam Research"],
    "KLAC": ["科磊", "KLA"],
    "QCOM": ["高通", "Qualcomm"],
    "TXN": ["德州仪器", "Texas Instruments"],
    "ADI": ["亚德诺", "Analog Devices"],
    "MPWR": ["芯源系统", "Monolithic Power"],
    "MCHP": ["微芯", "Microchip"],
    "ON": ["安森美", "onsemi"],
    "MP": ["MP Materials"],
    "DELL": ["戴尔", "Dell"],
    "HPE": ["慧与", "Hewlett Packard Enterprise"],
    "HPQ": ["惠普", "HP Inc"],
    "SMCI": ["超微电脑", "Supermicro", "Super Micro"],
    "APH": ["安费诺", "Amphenol"],
    "GLW": ["康宁", "Corning"],
    "TEL": ["泰科电子", "TE Connectivity"],
    "ACMR": ["ACM Research"],
}

# Measure types that make a naming an ACTION rather than a mention. The
# spec's §7.7 lists these explicitly.
_C7_ACTION_RE = re.compile(
    r"调查|审查|立案|处罚|禁止|限制|排除|列入|清单|许可|管制|约谈|整改"
    r"|反垄断|不可靠实体")


def _alias_in_text(form: str | None, text: str) -> bool:
    """True if `form` occurs in `text` as a name, not as a substring.

    A bare `in` test is right for Chinese, which does not delimit words,
    but wrong for the Latin aliases: confirmed live, "Intel" matched
    inside "Intelligent" and tagged Alibaba's ESG report and a rare-
    earth sustainability report as naming Intel - two false positives
    out of eleven rows, both from the same substring. Latin forms are
    therefore matched on a word boundary; CJK forms keep the plain
    containment test, since \\b does not work before a Chinese
    character (a bug this domain has already paid for once, in the
    filing-type patterns).
    """
    if not form:
        return False
    if _CJK_RE.search(form):
        return form in text
    return re.search(rf"(?<![A-Za-z]){re.escape(form)}(?![A-Za-z])",
                     text) is not None


def attach_named_us_entities(
    results: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    us_aliases: dict[str, list[str]] | None = None,
) -> None:
    """Record every US company a row's own text NAMES, on any row.

    C7 proper (``classify_us_company_action`` below) runs on POLICY rows
    only, because the spec's C7 is a policy signal - "a regulatory
    action naming a foreign company". That scoping is right for the
    signal and wrong for the entity list, and the corpus shows it:
    across a year, the aliases match five times and ALL FIVE are in
    cn_disclosure filings - 英特尔 in Loongson's interim report, 英伟达
    in Cambricon's supervision report, 超微 in a 提质增效 action plan -
    with zero in cn_policy. So the one place the names actually occur
    was the one place nothing looked for them.

    This writes them to ``entities_json`` as ``type: "named_in_text"``,
    deliberately NOT ``ticker``: a ticker entity means "this signal
    READS THROUGH to that company", a modelled relationship, while this
    means only "the document mentions them". Conflating the two would
    let a passing mention in a 200-page interim report look like an
    analysed exposure.

    Matched over a WIDER window than C7's own 600 characters, and the
    corpus forced that: the five real hits sit at character 639, 2010,
    2136, 2629 and 3764. C7's narrow window is right for its question -
    "is this measure ABOUT a US company", where a name buried on page
    four is a list entry - but wrong for this one, which only asks
    whether the document mentions them at all. At 600 characters four
    of the five were invisible.
    """
    aliases = us_aliases or _C7_US_COMPANY_ALIASES
    by_url = {a.get("url"): a for a in articles}
    found = 0
    for result in results:
        url = (result.get("article") or {}).get("url")
        article = by_url.get(url)
        if not article:
            continue
        head = (f"{article.get('title') or ''} "
                f"{(article.get('body') or '')[:_NAMED_IN_TEXT_WINDOW]}")
        named = sorted({
            ticker for ticker, forms in aliases.items()
            if any(_alias_in_text(form, head) for form in forms)
        })
        if not named:
            continue
        res = result.setdefault("result", {})
        ents = list(res.get("entities") or [])
        seen = {(e.get("name"), e.get("type")) for e in ents}
        for ticker in named:
            if (ticker, "named_in_text") not in seen:
                ents.append({"name": ticker, "type": "named_in_text"})
                seen.add((ticker, "named_in_text"))
        res["entities"] = ents
        found += 1
    logger.info("[CHINA] rows naming a US company in their own text: %d",
                found)


def classify_us_company_action(
    policy_rows: list[dict[str, Any]],
    us_aliases: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """C7: find policy rows that NAME a US company.

    Returns only the rows that matched, each carrying ``c7_named_us``
    (the tickers found) and ``c7_label``.

    A naming inside an action context is SIGNAL; a naming without one is
    WEAK, which is the spec's own floor - "an action naming a foreign
    company is always at least Weak", never Noise.

    Matched on title and the opening of the body, not the whole document,
    for the reason the relevance gate and the press layer both showed:
    a US company named deep inside a long government text is usually a
    passing mention in a list, not the subject of the measure.
    """
    aliases = us_aliases or _C7_US_COMPANY_ALIASES
    out: list[dict[str, Any]] = []
    for row in policy_rows:
        title = row.get("title") or ""
        head = f"{title} {(row.get('body') or '')[:_C1_BODY_WINDOW]}"
        named = sorted({
            ticker for ticker, forms in aliases.items()
            if any(form and form in head for form in forms)
        })
        if not named:
            continue
        label = "SIGNAL" if _C7_ACTION_RE.search(head) else "WEAK"
        out.append({**row, "c7_named_us": named, "c7_label": label})
    logger.info("[CHINA] c7 rows naming a US company: %d", len(out))
    return out


def gate_policy(articles: list[dict[str, Any]]) -> dict[str, list[dict]]:
    """Split pooled policy rows into relevant / irrelevant.

    Only ``relevant`` rows carry extracted fields and are worth a binding
    call. ``irrelevant`` is kept as a counted bucket rather than dropped
    silently: if its share ever falls sharply, the relevance vocabulary
    has gone stale, and that is only visible if the denominator is
    recorded.
    """
    buckets: dict[str, list[dict]] = {
        "relevant": [], "irrelevant": [], "other": []}
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("source_category") != "cn_policy":
            buckets["other"].append(article)
            continue
        title = article.get("title") or ""
        body = article.get("body") or ""
        relevant, categories = classify_policy_relevance(title, body)
        if not relevant:
            buckets["irrelevant"].append(article)
            continue
        buckets["relevant"].append({
            **article,
            "policy_categories": categories,
            **extract_policy_fields(title, body),
        })

    logger.info("[CHINA] c1 relevant=%d irrelevant=%d other=%d",
                len(buckets["relevant"]), len(buckets["irrelevant"]),
                len(buckets["other"]))
    return buckets


# ---------------------------------------------------------------------------
# Gate 2: figure extraction
# ---------------------------------------------------------------------------
#
# Extract, do not judge. Every C2-C6 rule in the spec needs a threshold,
# and there is no distribution to derive one from yet (see the module
# docstring). So the figures are pulled out and stored, the rules come
# later, and nothing in between pretends to know what "large" means.
#
# WHAT THE REAL CANDIDATES CONTAIN (7 filings, 2026-10-05)
#   ACM Shanghai orders-on-hand   170.73亿元, +88.20%
#   JL MAG capital injection      3,000万元 / 35,000万元 / 38,000万元
#   AMEC fund participation       30亿元 / 14.7亿元 / 21亿元, 49%
#   Baidu interim report          51.2 billion, 26.1 billion, +36%
#   Hua Hong JV (zh + en)         no figures - a supplemental notice
#   JL MAG progress update        3,000万元 / 5,500万元
#
# So 5 of 7 carry figures and 2 genuinely do not. A filing with no
# figures is not a failure: a JV formation supplement really does just
# confirm an arrangement, and storing an empty extraction records that.

# Chinese financial magnitudes. 亿 = 10^8, 万 = 10^4 - these are the
# units Chinese filings use, and converting at extraction time means a
# downstream comparison never has to know which unit a row came in.
_CN_UNIT_MULTIPLIER = {
    "亿元": 10**8, "亿": 10**8,
    "万元": 10**4, "万": 10**4,
    "元": 1,
}
_CN_AMOUNT_RE = re.compile(
    r"(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>亿元|万元|亿|万|元)"
    # A per-unit price, captured so it can be told apart from a total.
    # Hua Hong's asset-purchase filing states 43.34元/股 (a per-share
    # issue price) and nothing else in 元; without this the row's
    # max_amount was ¥43, three orders of magnitude below every other
    # investment filing and meaningless as a transaction size.
    r"(?P<per>\s*/\s*(?:股|吨|千克|克))?")
# English filings (HKEX) report in billions/millions, usually RMB but
# sometimes USD - the currency is NOT assumed, it is recorded as found.
_EN_AMOUNT_RE = re.compile(
    r"(?:(?P<cur>RMB|US\$|USD|HK\$|HKD)\s*)?"
    r"(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>billion|million)",
    re.I)
_EN_UNIT_MULTIPLIER = {"billion": 10**9, "million": 10**6}
# A percentage, with its surrounding words kept so a consumer can tell a
# growth rate from an ownership stake - 88.20% (order growth) and 49%
# (fund stake) are both "a percent" and mean completely different things.
#
# The number is matched FIRST and the context taken by lookbehind on the
# match position, not by a leading `.{0,24}` group. A greedy context
# group eats its own number: on "同比增加88.20%" it consumed "...88.2"
# and left "0%" to match, recording the value as 0.0 - confirmed by a
# regression case that caught it before this shipped.
_PCT_RE = re.compile(r"(?P<num>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*%")
_PCT_CONTEXT_CHARS = 24

_GATE2_MAX_FIGURES = 12

# A results filing states its unit ONCE in a table header - 单位：元 /
# 单位：万元 - and then prints bare numbers underneath. Confirmed live on
# China Northern Rare Earth's Q1 report: "单位：元 ... 营业收入
# 11,858,916,345.03 9,287,010,012.19 27.69". The amount regex requires a
# unit adjacent to each number, so it extracted nothing from these - and
# they are the most valuable filings in the set, the ones carrying actual
# revenue.
_CN_TABLE_UNIT_RE = re.compile(r"单位\s*[：:]\s*(亿元|万元|千元|元)")
# A labelled financial line inside such a table: the label, then the
# period's figure, then (usually) the prior-year figure and the percent
# change. Only the first number is taken - the second is last year's and
# must not be mistaken for this period's.
#
# The number must be BARE - no unit suffix. A filing that writes
# "营业收入约66.91 亿元" in prose is stating its own unit inline and is
# already handled by _CN_AMOUNT_RE; reading it here and then applying a
# table header's 单位：万元 from elsewhere in the document multiplied it
# into nonsense (AMEC's 业绩预告 reported a flat 1e+04, confirmed live).
_CN_FINANCIAL_LINE_RE = re.compile(
    r"(?P<label>营业(?:总)?收入|利润总额|净利润|营业利润)"
    r"[^0-9\-]{0,40}"
    r"(?P<num>-?[0-9][0-9,]*(?:\.[0-9]+)?)"
    # The number must END here - `\b`-style anchoring via a negative
    # lookahead on more digits. Without it the regex BACKTRACKS: on
    # "66.91 亿元" it matched "66.9", leaving "1 亿元" after the match so
    # the unit check below passed and a prose figure was read as a bare
    # table number (confirmed by a regression case).
    r"(?![0-9.])"
    r"(?!\s*(?:亿|万|千)?元)")
_CN_TABLE_UNIT_MULTIPLIER = {
    "亿元": 10**8, "万元": 10**4, "千元": 10**3, "元": 1}

# A year-on-year change the filing states ITSELF. This is what makes C2
# tractable without a trailing series: the issuer has already done the
# comparison against its own prior period, so no stored history is
# needed to know whether a quarter was unusual.
#
# Measured: 24 of 64 earnings filings state one. The alternative -
# building a per-company revenue series and computing the change - was
# tested and does not work: zero companies reach three revenue
# observations over a full year, because only ~4 filings per company
# carry a labelled revenue figure at all.
#
# Three shapes, all confirmed live:
#   prose   "营业收入约66.91 亿元，同比增长约34.89%"   (AMEC 业绩预告)
#   range   "同比增加112.74%到121.33%"              (N. Rare Earth)
#   table   "营业收入 38,635,115 32,348,049 19.4"   (SMIC, the trailing
#                                                   column IS the YoY)
# The table form accounts for 19 of the 24 and IS read, but only when
# the table's own header states the column order. Checked across every
# such filing in the stored year, the order is invariant:
#   中芯国际   本报告期末 上年度末 ...增减(%)
#   兆易创新   本报告期末 上年度末 ...增减(%)
#   龙芯中科   本报告期末 上年度末 ...增减(%)
#   北方稀土   本报告期  上年同期 ...增减
# [this period] [prior period] [change %]. A filing whose header does
# not match is skipped rather than guessed at - which is the difference
# between reading a documented layout and trusting column position.
_CN_YOY_RE = re.compile(
    r"同比(?P<dir>增长|增加|上升|下降|减少)\s*(?:约)?\s*"
    r"(?P<num>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*%"
    # An optional upper bound: a 业绩预告 forecasts a RANGE, and taking
    # only the lower number would understate every forecast.
    r"(?:\s*(?:到|至|-|~)\s*(?P<hi>[0-9][0-9,]*(?:\.[0-9]+)?)\s*%)?")
_EN_YOY_RE = re.compile(
    r"year[-\s]on[-\s]year\s+(?P<dir>increase|decrease|growth|decline)"
    r"\s+of\s+(?P<num>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*%", re.I)
# Which line the change refers to. Taken from the words BEFORE the
# percentage, because "净利润同比增长15%" and "营业收入同比增长34.89%"
# are different facts and a bare number cannot tell them apart.
#
# TRADITIONAL characters are included alongside simplified. The spec's
# §6 says to configure the mainland path separately from Taiwan's
# because the mainland uses simplified - which is true of mainland
# filings, but NOT of the Hong Kong listings in this same universe.
# SMIC's 中期業績公告 is written in traditional throughout ("本集團實現
# 收入5,511.1百萬美元，同比增加23.7%"), so a simplified-only pattern left
# every HK-filed figure unattributed. Confirmed live: 38 of 67 YoY
# observations had no subject, and this was the largest cause.
_CN_YOY_SUBJECT_RE = re.compile(
    r"(营业(?:总)?收入|營業(?:總)?收入"
    r"|实现收入|實現收入|收入"
    r"|净利润|淨利潤|利润总额|利潤總額|营业利润|營業利潤"
    r"|归属于.{0,12}?净利润|歸屬於.{0,12}?淨利潤)")

# The table header that licenses reading a trailing percent column as a
# YoY change. Required before any table row is read - see the note
# above on why column order is read from the header rather than assumed.
_CN_YOY_TABLE_HEADER_RE = re.compile(
    r"(?:本报告期|项目).{0,60}?(?:同期增减|增减变|增减\s*\(%\)|度末增减|增减幅度)")
# label, this-period figure, prior-period figure, change percent.
_CN_YOY_TABLE_ROW_RE = re.compile(
    r"(?P<label>营业(?:总)?收入|利润总额|净利润|营业利润)\s+"
    r"(?P<cur>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s+"
    r"(?P<prior>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s+"
    r"(?P<pct>-?[0-9][0-9,]*(?:\.[0-9]+)?)")


# Subjects are normalised to a canonical form before storage. The raw
# matches fragment three ways, all confirmed live:
#   script     营业收入 (simplified) vs 營業收入 (traditional, HK filings)
#   wording    营业收入 / 实现收入 / 收入 are the same line
#   PDF breaks "归属于母公 司所有者的净利润" - pdfplumber preserves a line
#              break mid-word, so the same label appears several ways
# Without this a C2 rule comparing "revenue" would see four separate
# small groups instead of one usable one.
# Order matters: the profit patterns are tested FIRST because
# 归属于上市公司股东的净利润 contains no 收入 but the bare revenue pattern
# is permissive, and a mis-ordered table would file every attributed
# profit line as revenue.
_YOY_SUBJECT_CANON: list[tuple[str, re.Pattern[str]]] = [
    ("total_profit", re.compile(r"(利润总额|利潤總額)")),
    ("operating_profit", re.compile(r"(营业利润|營業利潤)")),
    ("net_profit", re.compile(r"(净利润|淨利潤)")),
    ("revenue", re.compile(r"(收入|營業額|营业额)")),
]


def _canonical_yoy_subject(raw: str | None) -> str | None:
    """Map a raw subject match to one canonical name, or None.

    Checked most-specific first: 归属于上市公司股东的净利润 must resolve to
    net_profit rather than being caught by the bare 收入 pattern.
    """
    if not raw:
        return None
    collapsed = re.sub(r"\s+", "", raw)
    for name, pattern in _YOY_SUBJECT_CANON:
        if pattern.search(collapsed):
            return name
    return None


def _extract_yoy_changes(text: str) -> list[dict[str, Any]]:
    """Year-on-year changes the filing states about itself.

    Each entry carries the subject it refers to, because the same
    filing routinely states several - AMEC's 业绩预告 gives revenue
    +34.89% and net profit +282.48% to +310.81% in consecutive
    sentences, and they are different facts.

    A decrease is returned NEGATIVE regardless of how the filing words
    it: 同比下降15% and "a year-on-year decrease of 15%" both become
    -15.0, so a consumer never has to parse the direction word.
    """
    out: list[dict[str, Any]] = []
    seen_subjects: set[str] = set()

    # Table form first - it is the most precise, since the filing's own
    # header names the columns and the row names its subject. Only read
    # when that header is present.
    header = _CN_YOY_TABLE_HEADER_RE.search(text)
    if header:
        for m in _CN_YOY_TABLE_ROW_RE.finditer(text[header.end():]):
            label = m.group("label")
            if label in seen_subjects:
                continue
            try:
                pct = float(m.group("pct").replace(",", ""))
                current = float(m.group("cur").replace(",", ""))
                prior = float(m.group("prior").replace(",", ""))
            except ValueError:
                continue
            # The stated percent must agree with the two figures beside
            # it, or the columns are not what the header says. A 2-point
            # tolerance absorbs the filing's own rounding; anything
            # wider means the row was misread and is dropped.
            if prior:
                implied = (current - prior) / abs(prior) * 100
                if abs(implied - pct) > 2.0:
                    continue
            seen_subjects.add(label)
            out.append({
                "subject": _canonical_yoy_subject(label),
                "subject_raw": label,
                "pct": pct,
                "pct_high": None,
                "raw": m.group(0).strip()[:48],
            })
            if len(out) >= _GATE2_MAX_FIGURES:
                return out

    for m in _CN_YOY_RE.finditer(text):
        try:
            low = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        sign = -1 if m.group("dir") in ("下降", "减少") else 1
        high = None
        if m.group("hi"):
            try:
                high = float(m.group("hi").replace(",", "")) * sign
            except ValueError:
                high = None
        # The nearest subject BEFORE the change, searched back only to
        # the start of the current sentence. A fixed character window
        # was tried first and is wrong in both directions: 60 characters
        # missed "本集團實現收入5,511.1百萬美元，同比增加23.7%" (the subject
        # sits behind the figure and its unit), while widening it let a
        # sentence about net profit inherit the revenue subject from the
        # sentence before. The sentence boundary is the honest limit -
        # a subject in a different sentence is a different fact.
        sentence_start = max(
            text.rfind("。", 0, m.start()),
            text.rfind("；", 0, m.start()),
            text.rfind(". ", 0, m.start()),
        )
        window = text[sentence_start + 1:m.start()]
        subjects = _CN_YOY_SUBJECT_RE.findall(window)
        raw_subject = subjects[-1] if subjects else None
        out.append({
            "subject": _canonical_yoy_subject(raw_subject),
            "subject_raw": raw_subject,
            "pct": low * sign,
            "pct_high": high,
            "raw": m.group(0).strip(),
        })
        if len(out) >= _GATE2_MAX_FIGURES:
            return out

    for m in _EN_YOY_RE.finditer(text):
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        sign = -1 if m.group("dir").lower() in ("decrease", "decline") else 1
        out.append({
            "subject": None,
            "pct": value * sign,
            "pct_high": None,
            "raw": m.group(0).strip(),
        })
        if len(out) >= _GATE2_MAX_FIGURES:
            break

    return out


def extract_filing_figures(body: str) -> dict[str, Any]:
    """Pull the numeric facts out of one candidate filing.

    Returns amounts normalised to their base currency unit plus the
    percentages with their surrounding context. No judgment, no
    threshold, no signal label - that is Gate 3's job once there is
    enough history to derive one.

    Amounts are capped at _GATE2_MAX_FIGURES: a filing body can contain
    dozens of numbers (share counts, registered capital, dates rendered
    with 万), and the ones that matter are near the front where the
    announcement states its subject.
    """
    text = re.sub(r"\s+", " ", body or "")
    amounts: list[dict[str, Any]] = []
    # Labelled financial lines first - these are the figures a results
    # filing exists to report, and they carry a label saying what they
    # are. Everything below is unlabelled numbers found in prose.
    financials: dict[str, dict[str, Any]] = {}

    # Every 单位：X header in the document, with where it sits. A filing
    # contains several tables - income statement, balance sheet, cash
    # flow - each with its own header, so a label must be matched to the
    # NEAREST PRECEDING one rather than to whichever appears first.
    unit_marks = [(m.start(), _CN_TABLE_UNIT_MULTIPLIER[m.group(1)],
                   m.group(0)) for m in _CN_TABLE_UNIT_RE.finditer(text)]
    for m in _CN_FINANCIAL_LINE_RE.finditer(text):
        label = m.group("label")
        if label in financials:
            # First occurrence only. These tables repeat the same labels
            # for prior-period and year-to-date columns, and the first
            # is this period's.
            continue
        preceding = [u for u in unit_marks if u[0] < m.start()]
        if not preceding:
            continue
        _, multiplier, unit_raw = preceding[-1]
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        financials[label] = {
            "value": value * multiplier,
            "raw": m.group(0).strip()[:48],
            "currency": "CNY",
            "unit_source": unit_raw,
            # Which table this came from cannot be read off the label
            # alone - 营业收入 under a 资产负债表 header is not revenue.
            # The preceding text is kept so a consumer can tell, rather
            # than this guessing.
            "table_context": text[max(0, m.start() - 90):m.start()][-60:],
        }

    for m in _CN_AMOUNT_RE.finditer(text):
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        entry = {
            "value": value * _CN_UNIT_MULTIPLIER[m.group("unit")],
            "raw": m.group(0).strip(),
            # Chinese filings quote CNY unless they say otherwise;
            # recorded rather than inferred per-row.
            "currency": "CNY",
        }
        if m.group("per"):
            # A unit price, not a total. Flagged rather than dropped -
            # an issue price is a real disclosed fact, it just must not
            # be compared against transaction sizes.
            entry["per_unit"] = m.group("per").strip().lstrip("/").strip()
        amounts.append(entry)
        if len(amounts) >= _GATE2_MAX_FIGURES:
            break

    if not amounts:
        for m in _EN_AMOUNT_RE.finditer(text):
            try:
                value = float(m.group("num").replace(",", ""))
            except ValueError:
                continue
            amounts.append({
                "value": value * _EN_UNIT_MULTIPLIER[m.group("unit").lower()],
                "raw": m.group(0).strip(),
                "currency": (m.group("cur") or "").upper() or None,
            })
            if len(amounts) >= _GATE2_MAX_FIGURES:
                break

    percentages: list[dict[str, Any]] = []
    for m in _PCT_RE.finditer(text):
        try:
            pct = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        percentages.append({
            "value": pct,
            # The words before the number, kept verbatim: 88.20% after
            # 同比增长 is order growth, 49% after 持股 is a stake. A bare
            # number cannot be told apart and must not be guessed at.
            "context": text[max(0, m.start() - _PCT_CONTEXT_CHARS):
                            m.start()].strip(),
        })
        if len(percentages) >= _GATE2_MAX_FIGURES:
            break

    return {
        "amounts": amounts,
        "percentages": percentages,
        "yoy_changes": _extract_yoy_changes(text),
        # Labelled lines, keyed by what the filing calls them. This is
        # what a C2 rule should compare across periods - 营业收入 against
        # the same company's own 营业收入, never against whichever number
        # in the document happened to be largest.
        "financials": financials,
        # The largest amount, which is almost always the headline figure
        # - ACM Shanghai's 170.73亿元 order book, JL MAG's 38,000万元
        # total commitment. A convenience for a later rule, not a claim
        # that it is the right one.
        #
        # Per-unit prices are excluded: an issue price of 43.34元/股 is
        # not a transaction size, and including it made one asset-purchase
        # filing report a max_amount of ¥43 against a median of ¥1.5bn
        # across its own category.
        "max_amount": max(
            (a["value"] for a in amounts if not a.get("per_unit")),
            default=None),
    }


# ---------------------------------------------------------------------------
# C6: trade data
# ---------------------------------------------------------------------------
#
# The first China rule with enough data behind it to be a real rule
# rather than extraction. Six complete 12-month series (US, Japan,
# Netherlands x HS 8542 ICs, HS 8486 equipment), no gaps.
#
# WHY PER-SERIES AND NOT A FLAT THRESHOLD
#   The spec says "deviate more than two spreads from the trailing
#   twelve-month pattern". Measured month-on-month volatility over the
#   stored year shows why that has to be computed per series rather
#   than fixed:
#
#     Netherlands 8486  median +13.4%  MAD 97.9   (-98% .. +966%)
#     Netherlands 8542  median +41.1%  MAD 80.0
#     United States 8486 median +0.3%  MAD 26.2
#     Japan 8486        median -0.3%   MAD 25.6
#     United States 8542 median +8.5%  MAD  7.7   (-19% .. +22%)
#     Japan 8542        median +3.4%   MAD  4.7
#
#   A flat cutoff anywhere in that range would fire every month on
#   Dutch equipment and never on US ICs. The Netherlands numbers are
#   not noise either - ASML ships a handful of very large machines, so
#   a month with two shipments genuinely is double a month with one.
#   The spread IS the signal's own baseline.
#
# MAD, not standard deviation: these series contain real outliers
# (+966%) that would inflate a standard deviation enough to hide the
# next one. Same reasoning Japan's own classifier records for its
# forecast-revision habit.
_C6_MIN_PERIODS = 6
# Deviations are measured in MADs from the series' own median. 3.0 is
# the spec's "two spreads" translated into MAD terms - for a normal
# distribution 1 MAD is ~0.67 standard deviations, so two SDs is ~3
# MADs. Stated rather than tuned: with 11 month-on-month observations
# per series there is not enough data to fit this, and a fitted value
# would be a false precision.
_C6_SIGNAL_MADS = 3.0
_C6_WEAK_MADS = 2.0
# A MAD floor. Japan 8542 has MAD 4.7, so a 15% move is already 3 MADs
# there - real, but a 15% month in semiconductor trade is ordinary. The
# floor stops a very stable series from flagging its own normal noise.
_C6_MIN_MAD_PCT = 10.0


def classify_trade_deviation(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C6: flag a monthly trade figure that deviates from its own series.

    One series per (reporter, commodity) - never pooled. The series are
    not comparable to each other: Dutch equipment exports move by
    hundreds of percent a month because a single ASML shipment is large
    relative to the total, while US IC exports sit in a +-20% band.

    Only the NEWEST period of each series is judged. The older months
    are the baseline it is judged against, and re-flagging them on every
    run would restate history as news.

    An estimate (`is_reported` false) is never a Signal. Comtrade serves
    recent months as its own estimate and revises them later - see the
    news-retrieval side's note on why the value is part of the dedup
    key. A deviation computed from a number that will change is not a
    finding yet.
    """
    import statistics as _st

    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("source_type") != "comtrade_china_trade":
            continue
        key = (meta.get("reporter") or "?", meta.get("commodity_code") or "?")
        series.setdefault(key, []).append(article)

    results: list[dict[str, Any]] = []
    for (reporter, commodity), rows in sorted(series.items()):
        rows.sort(key=lambda a: (a.get("metadata") or {}).get("period") or "")
        values = [(a.get("metadata") or {}).get("value_usd") for a in rows]
        if len(values) < _C6_MIN_PERIODS or any(v is None for v in values):
            logger.info("[CHINA] c6 %s/%s: %d periods, below floor of %d",
                        reporter, commodity, len(values), _C6_MIN_PERIODS)
            continue

        changes = [(values[i] - values[i - 1]) / values[i - 1] * 100
                   for i in range(1, len(values)) if values[i - 1]]
        if len(changes) < _C6_MIN_PERIODS - 1:
            continue

        # The baseline excludes the month being judged, so a large move
        # does not widen the spread it is measured against.
        baseline, latest_change = changes[:-1], changes[-1]
        median = _st.median(baseline)
        mad = max(_st.median([abs(c - median) for c in baseline]),
                  _C6_MIN_MAD_PCT)
        deviation = abs(latest_change - median) / mad

        newest = rows[-1]
        meta = newest.get("metadata") or {}
        is_estimate = not meta.get("is_reported")

        if deviation >= _C6_SIGNAL_MADS and not is_estimate:
            signal = "signal"
        elif deviation >= _C6_WEAK_MADS:
            signal = "weak_signal"
        else:
            continue

        direction = "rose" if latest_change > median else "fell"
        reason = (f"{reporter} {commodity} exports to China {direction} "
                  f"{latest_change:+.1f}% MoM, {deviation:.1f} MADs from "
                  f"its own 12-month median of {median:+.1f}%"
                  + (" (estimate, not yet reported)" if is_estimate else ""))

        results.append({
            "article": newest,
            "result": {
                "signal": signal,
                "reason": reason,
                "metadata": {
                    "source_category": "cn_trade",
                    "signal_type": "C6",
                    "reporter": reporter,
                    "commodity_code": commodity,
                    "period": meta.get("period"),
                    "mom_pct": round(latest_change, 2),
                    "series_median_pct": round(median, 2),
                    "series_mad_pct": round(mad, 2),
                    "deviation_mads": round(deviation, 2),
                    "baseline_periods": len(baseline),
                    "is_estimate": is_estimate,
                },
            },
        })

    logger.info("[CHINA] c6 series=%d flagged=%d", len(series), len(results))
    return results


# ---------------------------------------------------------------------------
# C5: Chinese platform capital spending
# ---------------------------------------------------------------------------
#
# The spec asks for "capital expenditure guidance changed by more than
# twenty percent, or an AI infrastructure commitment with a stated
# figure". Unlike C2, this is tractable from what is filed: the
# platforms report capex quarterly with their own year-on-year
# comparison, in the results announcement body.
#
# Confirmed live on Alibaba's June-quarter 2026 results:
#   "capital expenditures were RMB67,678 million (US$9,975 million), an
#    increase of 75% compared to RMB38,676 million in the same quarter
#    of 2025"
# and in its September-quarter commentary:
#   "over the past four quarters, we have deployed approximately RMB120
#    billion in capital expenditure toward AI and cloud infrastructure"
#
# So the figure AND its change come from the filing itself - no trailing
# series needed, the same property that makes C2's YoY path work.
#
# The 20% threshold is the spec's, used as stated rather than fitted.
# With two observations there is nothing to fit, and inventing a number
# here would be worse than using the one the spec already reasoned
# about. It is recorded as the spec's value so a later recalibration
# knows what it is replacing.
_C5_GUIDANCE_CHANGE_PCT = 20.0

# The three listed platforms. Passed as codes rather than names because
# an article carries metadata.code, and a name match would need the
# alias handling the universe already does upstream.
_C5_PLATFORM_CODES = codes_with_role("platform")

# "capital expenditures were RMB67,678 million ... an increase of 75%"
# Label first, figure after - the order Alibaba's results use. A
# figure-then-label pattern was tried and found only the headline
# commentary sentence, missing the actual quarterly number.
_C5_CAPEX_RE = re.compile(
    r"(?P<label>capital expenditures?|capex|资本开支|资本支出)"
    r"[^.。]{0,80}?"
    r"(?:RMB|US\$|人民币)?\s*(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(?P<unit>billion|million|亿元|亿)",
    re.I)
_C5_CAPEX_UNIT = {
    "billion": 10**9, "million": 10**6, "亿元": 10**8, "亿": 10**8}

# Tencent reports capex as a bare row in its financial-summary table -
# "Capital expenditures (d) 52,784 31,936 19,107" - with no unit beside
# the number. The unit comes from the table's own header ("RMB in
# millions") further up the document. Confirmed live after the PDF page
# budget was raised; before that the row was never fetched at all.
#
# Only read when a unit header is present, and only the FIRST figure on
# the row, which is the current period - the rest are prior periods, the
# same column convention the mainland results tables use.
_C5_TABLE_UNIT_RE = re.compile(
    r"(?i)(?:RMB|US\$|人民币)?\s*in\s+(millions?|billions?|thousands?)")
_C5_TABLE_UNIT_MULTIPLIER = {
    "million": 10**6, "millions": 10**6,
    "billion": 10**9, "billions": 10**9,
    "thousand": 10**3, "thousands": 10**3}
_C5_CAPEX_TABLE_ROW_RE = re.compile(
    r"(?i)capital expenditures?\s*(?:\([a-z]\))?\s*"
    r"(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?)")
# The change the filing states about that figure, within the same
# sentence - "an increase of 75% compared to ...".
_C5_CAPEX_CHANGE_RE = re.compile(
    r"(?P<dir>increase|decrease|growth|decline|增长|增加|下降|减少)"
    r"\s*(?:of)?\s*(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?)\s*%", re.I)


def classify_platform_capex(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C5: a platform's stated capital expenditure and its own change.

    Only the three listed platforms are read. A capex figure from an
    equipment maker is a different fact - it is that company's own
    spending, not demand for accelerators - and pooling them would
    make the category mean two things.

    A stated change at or above the spec's 20% threshold is a Signal; a
    figure with no stated change, or a smaller one, is Weak. There is no
    Noise case: a platform disclosing its AI capex is always at least
    worth recording, which is the same floor the spec gives C7.
    """
    results: list[dict[str, Any]] = []
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("code") not in _C5_PLATFORM_CODES:
            continue
        body = re.sub(r"\s+", " ", article.get("body") or "")
        m = _C5_CAPEX_RE.search(body)
        value = None
        if m:
            try:
                value = (float(m.group("num").replace(",", ""))
                         * _C5_CAPEX_UNIT[m.group("unit").lower()])
            except (ValueError, KeyError):
                value = None
        if value is None:
            # Table form - the unit sits in the table header, not beside
            # the number. See _C5_CAPEX_TABLE_ROW_RE.
            unit_m = _C5_TABLE_UNIT_RE.search(body)
            row_m = _C5_CAPEX_TABLE_ROW_RE.search(body)
            if not (unit_m and row_m):
                continue
            try:
                value = (float(row_m.group("num").replace(",", ""))
                         * _C5_TABLE_UNIT_MULTIPLIER[unit_m.group(1).lower()])
            except (ValueError, KeyError):
                continue
            m = row_m

        # The change, searched only in the remainder of the same
        # sentence - a percentage from the next paragraph is about
        # something else.
        sentence = body[m.end():m.end() + 160].split(". ")[0]
        cm = _C5_CAPEX_CHANGE_RE.search(sentence)
        change_pct = None
        if cm:
            try:
                change_pct = float(cm.group("num").replace(",", ""))
                if cm.group("dir").lower() in ("decrease", "decline",
                                               "下降", "减少"):
                    change_pct = -change_pct
            except ValueError:
                change_pct = None

        if change_pct is not None and abs(change_pct) >= _C5_GUIDANCE_CHANGE_PCT:
            signal = "signal"
            reason = (f"{meta.get('company')} capital expenditure "
                      f"{value / 1e9:.1f}bn, {change_pct:+.0f}% vs prior "
                      f"period (spec threshold {_C5_GUIDANCE_CHANGE_PCT:.0f}%)")
        else:
            signal = "weak_signal"
            reason = (f"{meta.get('company')} capital expenditure "
                      f"{value / 1e9:.1f}bn"
                      + (f", {change_pct:+.0f}%" if change_pct is not None
                         else ", no stated change"))

        capex_meta: dict[str, Any] = {
            "source_category": "cn_disclosure",
            "signal_type": "C5",
            "code": meta.get("code"),
            "company": meta.get("company"),
            "capex_value": value,
            "capex_raw": m.group(0).strip()[:80],
        }
        if change_pct is not None:
            capex_meta["capex_change_pct"] = change_pct
        results.append({
            "article": article,
            "result": {"signal": signal, "reason": reason,
                       "metadata": capex_meta},
        })

    logger.info("[CHINA] c5 platform capex rows: %d", len(results))
    return results


# ---------------------------------------------------------------------------
# C2: substitution progress
# ---------------------------------------------------------------------------
#
# The spec's rule is "revenue growth more than two spreads above its own
# trailing pattern". The per-company form of that was attempted first
# and does not work from this source - see the module docstring: no
# company reaches enough observations, because they report quarterly and
# only some filings carry an extractable figure.
#
# What IS available is the change each filing states about itself, and
# after canonicalising subjects across simplified/traditional/PDF-break
# variants there are enough to form a sector baseline:
#
#   revenue YoY, distinct values over the stored year (n=13):
#     11.6  18.1  18.9  19.4  22.9  23.7  24.9  27.7  34.9  36.8
#     38.7  107.0  178.7
#   median +24.9%   MAD 6.8
#
#   SMIC          18.1 18.9 19.4 22.9 23.7   (tight, five observations)
#   N.RareEarth   27.7 36.8 107.0
#   Loongson      11.6 38.7
#   AMEC 34.9 | GigaDevice 178.7 | Naura 24.9
#
# SECTOR baseline, not per-company, and that is a deliberate compromise
# the data forces: only SMIC has enough points for a baseline of its
# own. The spec asks for "its OWN trailing pattern" and this is one step
# short of that - recorded here so it is a known approximation rather
# than a silent substitution. As per-company counts grow the baseline
# should move; `_C2_MIN_COMPANY_OBSERVATIONS` is where that switch goes.
# C3's ranking floor and bands. Derived from the stored year rather
# than chosen: 14 commitment figures, median 3.35bn, MAD 2.71bn, with a
# clean gap between a long tail of routine fundraising (0.5-8.5bn) and
# three genuine outliers (37.0, 82.9, 93.1bn, at 12.4-33.1 MADs). 3.0
# MADs sits in that gap and is the same band C2 and C6 already use, so
# the three classifiers answer "unusual" the same way.
_C3_MIN_OBSERVATIONS = 8
_C3_SIGNAL_MADS = 3.0
# A floor on the MAD itself, proportional rather than absolute because
# commitments span two orders of magnitude. Without it a batch of
# near-identical figures would make any ordinary commitment look
# extreme - the same failure _C2_MIN_MAD_PCT and _C6_MIN_MAD_PCT guard
# against in percentage space.
_C3_MIN_MAD_FRACTION = 0.25

_C2_MIN_OBSERVATIONS = 8
_C2_SIGNAL_MADS = 3.0
_C2_WEAK_MADS = 2.0
# The same floor reasoning as C6: a tight baseline would otherwise make
# an ordinary quarter look extreme. Semiconductor revenue routinely
# moves 10-20% year on year.
_C2_MIN_MAD_PCT = 10.0


def classify_substitution_progress(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C2: a revenue growth rate far above what this sector is posting.

    Builds the baseline from every revenue YoY in the batch, then judges
    each filing against it. The baseline is computed on DISTINCT values:
    the same figure appears in a company's interim report, its summary
    and its HK mirror, and counting it three times would narrow the
    spread around whichever company filed most.

    Direction matters here in a way it does not elsewhere in this
    module. A Chinese equipment maker posting outsized revenue growth is
    the substitution signal - and per the spec, a NEGATIVE read for the
    US names it competes with. That inversion is carried in the reason
    text rather than inferred downstream.
    """
    import statistics as _st

    observations: list[tuple[float, dict[str, Any], str]] = []
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("source_type") not in ("cninfo_filing", "hkex_filing"):
            continue
        for change in extract_filing_figures(
                article.get("body") or "")["yoy_changes"]:
            if change.get("subject") != "revenue":
                continue
            observations.append(
                (change["pct"], article, meta.get("company") or "?"))

    distinct = sorted({round(p, 2) for p, _, _ in observations})
    if len(distinct) < _C2_MIN_OBSERVATIONS:
        logger.info("[CHINA] c2 %d distinct revenue observations, below "
                    "floor of %d - not judging",
                    len(distinct), _C2_MIN_OBSERVATIONS)
        return []

    median = _st.median(distinct)
    mad = max(_st.median([abs(v - median) for v in distinct]),
              _C2_MIN_MAD_PCT)

    results: list[dict[str, Any]] = []
    # Deduped on (company, figure), not on url. The same quarter's
    # revenue growth is filed several times - a company's interim
    # report, its summary, a broker's tracking report and the HK mirror
    # all carry it, under different urls. Confirmed live: Cambricon's
    # +108.1% appeared under two separate cninfo filings and would
    # otherwise have been reported as two signals.
    seen: set[tuple[str, float]] = set()
    for pct, article, company in observations:
        key = (company, round(pct, 2))
        if key in seen:
            continue
        deviation = (pct - median) / mad
        # One-sided: the spec's C2 is about growth ABOVE the pattern.
        # A company growing slower than its peers is not substitution
        # progress, it is the absence of it.
        if deviation >= _C2_SIGNAL_MADS:
            signal = "signal"
        elif deviation >= _C2_WEAK_MADS:
            signal = "weak_signal"
        else:
            continue
        seen.add(key)
        results.append({
            "article": article,
            "result": {
                "signal": signal,
                "reason": (
                    f"{company} revenue {pct:+.1f}% YoY, {deviation:.1f} "
                    f"MADs above the sector median of {median:+.1f}% - "
                    f"NEGATIVE read for the US names it competes with"),
                "metadata": {
                    "source_category": "cn_disclosure",
                    "signal_type": "C2",
                    "company": company,
                    "code": (article.get("metadata") or {}).get("code"),
                    "revenue_yoy_pct": round(pct, 2),
                    "sector_median_pct": round(median, 2),
                    "sector_mad_pct": round(mad, 2),
                    "deviation_mads": round(deviation, 2),
                    "baseline_observations": len(distinct),
                    # The spec's defining property for this market.
                    "direction": "opposite",
                },
            },
        })

    logger.info("[CHINA] c2 observations=%d distinct=%d flagged=%d",
                len(observations), len(distinct), len(results))
    return results


# ---------------------------------------------------------------------------
# C3: fab capacity and capital spending
# ---------------------------------------------------------------------------
#
# The spec's rule is "a capital budget change of more than twenty
# percent against the previous guided figure, or a new fab announcement
# with a stated capacity", with "restatements of previously announced
# plans" explicitly Noise.
#
# WHAT THE DATA SHOWS, AND WHY RESTATEMENT HANDLING IS THE WHOLE JOB
#   22 candidates across capacity/investment over the stored year. But
#   they are not 22 events. Hua Hong filed THIRTEEN of them tracking a
#   single acquisition from 2025-12-31 to 2026-09-30:
#
#     2025-12-31  UPDATE ANNOUNCEMENT ON (1) MAJOR AND CONNECTED...
#     2026-01-22  (1) MAJOR AND CONNECTED TRANSACTION - ACQUISITION
#     2026-01-22  DESPATCH OF THE CIRCULAR RELATING TO...
#     2026-02-10  (1) MAJOR AND CONNECTED TRANSACTION - ...
#     2026-03-31  FURTHER UPDATE ON (1) MAJOR AND CONNECTED...
#     2026-07-08  FURTHER UPDATE ON THE MAJOR AND CONNECTED...
#     2026-09-05  ...标的资产过户完成的公告
#     2026-09-12  ...发行结果暨股本变动的公告
#     ... and five more
#
#   SMIC filed three on one transaction, AMEC five on its own. So a
#   naive C3 would report one deal as a dozen signals, which is the
#   precise failure the spec's Noise line warns about.
#
# NO THRESHOLD IS APPLIED. The spec's "20% against the previous guided
# figure" needs a PRIOR guided figure to compare against, and these
# filings do not restate one - they announce a transaction size once and
# then track its progress. Deriving a threshold from the sizes
# themselves would answer a different question ("is this a big deal
# relative to other deals") than the spec asks ("did the budget
# change"). The first filing in a chain is reported as a Weak with its
# figure; the rest are collapsed.
#
# The markers must absorb the CONNECTING words too, not just the verb.
# "FURTHER UPDATE ON (1) MAJOR AND..." and "DESPATCH OF THE CIRCULAR
# RELATING TO (1) MAJOR AND..." both wrap the same transaction name, and
# stripping only "further update" / "despatch" left "on..." and
# "ofthecircularrelatingto..." as different keys - confirmed live, Hua
# Hong's single acquisition still split into four chains.
_C3_RESTATEMENT_MARKERS = re.compile(
    r"(?i)(进展|实施情况|实施结果|结果|完成|补充|之|暨"
    r"|further update(?:\s+on)?|update announcement(?:\s+on)?"
    r"|supplemental(?:\s+announcement)?(?:\s+in relation to)?"
    r"|despatch of the circular relating to"
    r"|completion of|results? of)")


def _c3_transaction_key(article: dict[str, Any]) -> tuple[str, str]:
    """Group filings that track the same underlying transaction.

    Keyed on (company, normalised subject) where the subject strips the
    progress wording - "FURTHER UPDATE ON (1) MAJOR AND CONNECTED
    TRANSACTION" and "(1) MAJOR AND CONNECTED TRANSACTION" collapse to
    the same key, as do 发行股份购买资产...的公告 and its 进展公告.
    """
    meta = article.get("metadata") or {}
    title = " ".join((article.get("title") or "").split())
    # Strip the progress/update wording and any leading enumeration.
    subject = _C3_RESTATEMENT_MARKERS.sub("", title)
    subject = re.sub(r"[（(]\s*\d+\s*[）)]|\(\s*[0-9]+\s*\)", "", subject)
    subject = re.sub(r"[^\w一-鿿]+", "", subject).lower()
    # Articles and the issuer's own name are not part of the
    # transaction's identity. "FURTHER UPDATE ON THE MAJOR AND..." left
    # "themajorand..." against "majorand..." from the announcement
    # itself, and Hua Hong prefixes half its Chinese filings with
    # 华虹宏力半导体有限公司 and half with 关于 - three variants of one deal.
    subject = re.sub(r"^(the|a|an)", "", subject)
    subject = re.sub(r"^关于", "", subject)
    if company_name := (article.get("metadata") or {}).get("native_name"):
        subject = subject.replace(company_name, "", 1)
    subject = re.sub(r"^[一-鿿]{2,12}(有限公司|股份有限公司)", "",
                     subject)
    # The first 24 characters carry the transaction's identity; the tail
    # is the per-filing detail that differs between updates.
    return (meta.get("company") or "?", subject[:24])


def classify_capacity_commitment(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C3: a capacity or capital commitment, one row per transaction.

    Returns the EARLIEST filing in each transaction chain - the
    announcement - and drops the progress updates that follow it. The
    spec calls those restatements and labels them Noise.

    Every surviving row is Weak, never Signal: without a previously
    guided figure to compare against there is nothing to apply the
    spec's 20% rule to, and labelling a transaction Signal purely for
    being large would be a different rule than the one asked for.
    """
    chains: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for article in articles:
        category = article.get("filing_category") or ""
        # Exact match, not prefix: `investment`/`investment_en` and
        # `capacity`/`capacity_en` only. A prefix test let earnings rows
        # through on this path during testing.
        if category not in ("capacity", "capacity_en",
                            "investment", "investment_en"):
            continue
        chains.setdefault(_c3_transaction_key(article), []).append(article)

    pending: list[dict[str, Any]] = []
    for (company, _), rows in sorted(chains.items()):
        rows.sort(key=lambda a: str(a.get("published") or ""))
        first = rows[0]
        figures = extract_filing_figures(first.get("body") or "")
        amount = figures["max_amount"]
        # The announcement itself may carry no figure while a later
        # filing in the same chain does - take the first one that does,
        # since it describes the same transaction.
        if amount is None:
            for row in rows[1:]:
                amount = extract_filing_figures(
                    row.get("body") or "")["max_amount"]
                if amount is not None:
                    break

        metadata: dict[str, Any] = {
            "source_category": "cn_disclosure",
            "signal_type": "C3",
            "company": company,
            "code": (first.get("metadata") or {}).get("code"),
            "filing_category": first.get("filing_category"),
            "chain_filings": len(rows),
        }
        if amount is not None:
            metadata["commitment_value"] = amount

        reason = (f"{company} capital commitment"
                  + (f" {amount / 1e9:.2f}bn" if amount else " (no figure stated)")
                  + (f", {len(rows)} filings on this transaction"
                     if len(rows) > 1 else ""))
        pending.append({
            "article": first,
            "result": {"signal": "weak_signal", "reason": reason,
                       "metadata": metadata},
        })

    # ---- Gate 3: rank the commitments against each other ---------------
    #
    # Until now every C3 row was written "weak_signal" unconditionally,
    # so a 93bn Hua Hong commitment and a 0.5bn JL MAG one were rated
    # identically and nothing ever rose. C2 and C6 both already judge
    # against a derived baseline; this is the same machinery, applied to
    # the one classifier that lacked it.
    #
    # The baseline is the batch's own distribution, measured on the
    # stored year (14 figures, 0.50bn - 93.09bn, median 3.35bn,
    # MAD 2.71bn). That cleanly separates three outliers - Naura 12.4,
    # SMIC 29.3, Hua Hong 33.1 MADs - from a long tail of routine
    # fundraising, which is exactly the split a reader needs.
    #
    # KNOWN APPROXIMATION, recorded rather than hidden: this is an
    # ABSOLUTE yen threshold, so it measures "large for this universe",
    # not "large for this company". Japan's J5 equivalent normalises by
    # total assets; China cannot today - 资产总计/总资产 appears in only
    # 28 stored filings covering 11 of 20 companies, so a ratio rule
    # would silently skip the other nine. When that coverage improves,
    # this is where the switch goes.
    amounts = sorted({
        r["result"]["metadata"]["commitment_value"] for r in pending
        if r["result"]["metadata"].get("commitment_value")
    })
    results: list[dict[str, Any]] = []
    if len(amounts) >= _C3_MIN_OBSERVATIONS:
        import statistics as _st
        median = _st.median(amounts)
        mad = max(_st.median([abs(a - median) for a in amounts]),
                  median * _C3_MIN_MAD_FRACTION)
        for row in pending:
            meta = row["result"]["metadata"]
            amount = meta.get("commitment_value")
            if not amount:
                results.append(row)
                continue
            deviation = abs(amount - median) / mad if mad else 0.0
            meta["batch_median_value"] = round(median, 2)
            meta["batch_mad_value"] = round(mad, 2)
            meta["deviation_mads"] = round(deviation, 2)
            if deviation >= _C3_SIGNAL_MADS and amount > median:
                row["result"]["signal"] = "signal"
                row["result"]["reason"] += (
                    f" - {deviation:.1f} MADs above the "
                    f"{median / 1e9:.2f}bn median commitment in this batch")
            results.append(row)
        logger.info("[CHINA] c3 baseline n=%d median=%.2fbn mad=%.2fbn "
                    "signals=%d", len(amounts), median / 1e9, mad / 1e9,
                    sum(1 for r in results
                        if r["result"]["signal"] == "signal"))
    else:
        # Below the floor the classifier declines to rank rather than
        # judging against two or three points - the same refusal
        # _C2_MIN_OBSERVATIONS and _C6_MIN_PERIODS already make.
        results = pending
        logger.info("[CHINA] c3 only %d figure(s), below the %d needed to "
                    "rank - all rows left weak", len(amounts),
                    _C3_MIN_OBSERVATIONS)

    collapsed = sum(len(v) - 1 for v in chains.values())
    logger.info("[CHINA] c3 transactions=%d restatements collapsed=%d",
                len(chains), collapsed)
    return results


# ---------------------------------------------------------------------------
# C4: domestic accelerator milestones
# ---------------------------------------------------------------------------
#
# The spec's rule, and the distinction it insists on:
#   Signal - a product launch with stated specifications, a stated
#            production volume, or a named customer; or a government /
#            state-linked procurement award naming a domestic accelerator
#   Weak   - a product announcement with no volume, no customer and no
#            specification
#   Noise  - commentary and roadmap statements with no dated commitment
#
# "An announced chip and a shipped chip are different events. Chinese
# accelerator announcements frequently lead volume by a long way, and
# treating an announcement as displacement overstates the read against
# Nvidia."
#
# HOW THE INPUT WAS UNBLOCKED
#   This was the last classifier without usable input. The three listed
#   makers file nothing resembling a milestone - 77 cninfo filings over
#   a year, all governance - and press_cn returns zero accelerator
#   articles because the reachable Chinese outlets are thin.
#
#   What DID find them was press_cn_english_check, which searches each
#   company by name. It was storing headlines only: news-retrieval
#   hardcoded `summary: None` while the search backend was returning a
#   publisher snippet on every result. Keeping that snippet turned 0
#   usable rows into 14 for these three companies, and it is the input
#   this classifier reads.
#
#   Two things follow from the input being a SNIPPET rather than an
#   article body. First, a figure in it is a headline figure, not a
#   filed one - so nothing here is a Signal on the strength of a number
#   alone. Second, the search returns market commentary alongside real
#   news ("Chinese shares hit one-year low", "European indexes largely
#   higher at open"), so the relevance gate does most of the work.
#
# WHAT IT ACTUALLY FINDS
#   Snippets alone produced ONE row - a pricing story - and no product
#   milestone at all. news-retrieval now fetches the ARTICLE BODY for
#   these three codes (and only these three), which changed the answer:
#
#     Loongson launches homegrown 16-core server CPU      product launch
#     New homegrown China server chips unveiled, specs    product launch
#     Huawei and Cambricon charging more for AI chips     pricing power
#
#   The two Loongson launches were invisible in snippet form. Bodies run
#   2,748-6,096 characters against a snippet's one truncated sentence,
#   and the figures follow: Cambricon's story yields 110,000 yuan,
#   250,000 yuan, 12 billion, 40%, 30%, 20% where the snippet gave only
#   "50%".
#
#   All three remain WEAK, and the Cambricon body shows why that is
#   right rather than conservative: "Huawei's Ascend 950DT hasn't
#   shipped yet, but it's already listing above 250,000 yuan". A price
#   on an unshipped part is exactly the announced-vs-shipped distinction
#   the spec draws, and promoting it would overstate the read against
#   Nvidia in precisely the way §7.4 warns about.
#
#   Relevance is still judged on headline + snippet only. The body is
#   searched for SUBSTANCE but never for relevance: a full article
#   mentions many companies and says "plans to" about someone else's
#   product, and letting it decide relevance would reintroduce the
#   passing-mention failures the press layer already demonstrated.
#
#   Four filters were needed to get from 17 raw rows to that one, each
#   added after reading what the previous version let through:
#     company named    a "Global supply chain" roundup returned under
#                      Loongson's query was about Firmus and OpenAI
#     not commentary   "Chinese shares hit one-year low", "European
#                      indexes largely higher at open"
#     not a roadmap    "Hygon plots expansion... is set to release a new
#                      chip" is the spec's own Noise case, and was being
#                      returned as a milestone
#     not syndication  the same Hygon story under scmp.com and msn.com
#                      counted twice; keyed on headline, since the
#                      aggregator rewrites the url but not the title
_C4_ACCELERATOR_CODES = codes_with_role("accelerator")

# A milestone names a thing that happened to the product or the company,
# not to its share price.
_C4_MILESTONE_RE = re.compile(
    r"(?i)\b(unveil\w*|launch\w*|ship\w*|volume production|mass produc\w*"
    r"|tape[- ]?out|qualif\w+|deploy\w+|order\w*|contract\w*|procurement"
    r"|award\w*|win\w*|supply agreement|expansion|capacity"
    r"|revenue (?:surge|jump|growth)"
    # Pricing power. Not in the spec's §7.4 list, which names launches,
    # volumes, customers and procurement awards - but a Chinese
    # accelerator raising prices is substitution evidence of the same
    # kind: it can only charge more because buyers have fewer
    # alternatives. Kept as Weak like everything else here, never
    # promoted, so it informs without being read as displacement.
    r"|charging more|hiked? price|price (?:hike|increase|rise))")
# Market commentary. Present in the same search results and must not be
# read as a milestone - these are about the stock, not the chip.
_C4_COMMENTARY_RE = re.compile(
    r"(?i)\b(shares? (?:hit|slump|rose|fell)|stocks? (?:hit|slump|rout)"
    r"|index|indexes|indices|market headlines|daily review|retail investors"
    r"|price target|initiat\w+ coverage|research insights?|analyst"
    r"|one-year low|tech rout)")
# The spec's own bar for Signal: a volume, a named customer, or a
# procurement award. A specification counts too.
# The trailing \b is on the WORD units only, never on `%`. A `\b` after
# "%" can never match - % is a non-word character and so is the space
# after it - so "up to 50%" was silently failing the substance test
# while every other marker worked.
_C4_SUBSTANCE_RE = re.compile(
    r"(?i)(\b\d[\d,.]*\s*%"
    r"|\b\d[\d,.]*\s*(?:units?|wafers?|billion|million|yuan|nm)\b"
    r"|\bprocurement\b|\bstate[- ]linked\b|\bgovernment (?:award|contract)\b"
    r"|\bcustomer\b|\bsupply agreement\b)")

# A plan, not an event. The spec is explicit that "commentary and roadmap
# statements with no dated commitment" are NOISE, and that "an announced
# chip and a shipped chip are different events". Found live: an SCMP
# story headlined "Hygon plots expansion from data centres to robotics"
# whose snippet reads "is set to release a new chip" was being returned
# as a milestone. It is a roadmap.
_C4_ROADMAP_RE = re.compile(
    r"(?i)\b(plots?|plans?|planning|is set to|set to|expects? to|aims? to"
    r"|intends? to|will (?:launch|release|ship|unveil|begin)"
    r"|upcoming|forthcoming|reportedly (?:plans|will)"
    r"|roadmap|in the works|slated to)")


def classify_accelerator_milestone(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C4: a milestone for one of the three listed accelerator makers.

    Reads the search snippet, which is the only source carrying these
    events - see the note above on why the filings do not.

    Never returns a Signal. The spec requires a volume, a named customer
    or a procurement award before an announcement counts as displacement,
    and a publisher's one-sentence snippet cannot establish any of those
    to that standard - it can say a company is "charging more" without
    saying how much to whom. A snippet carrying substance is Weak with
    the substance recorded; one without is dropped. Promoting these to
    Signal would need the article body, which this source does not fetch.
    """
    results: list[dict[str, Any]] = []
    # Syndication, not separate events. The same story is carried by the
    # publisher and by aggregators - confirmed live, one Hygon story
    # appeared under both scmp.com and msn.com and was counted twice.
    # Keyed on the headline rather than the url, since the aggregator
    # rewrites the url but not the title.
    seen_headlines: set[tuple[str, str]] = set()
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("code") not in _C4_ACCELERATOR_CODES:
            continue
        # The article body where news-retrieval fetched one (scoped to
        # these three codes), falling back to the search snippet. The
        # body is what makes a volume or a named customer findable at
        # all - a snippet is one truncated sentence.
        snippet = " ".join((article.get("summary") or "").split())
        body = " ".join((article.get("body") or "").split())
        if not snippet and not body:
            continue
        # The headline as published, with the coverage-check prefix
        # news-retrieval adds stripped off.
        headline = " ".join((article.get("title") or "").split())
        headline = headline.split("]:", 1)[-1].strip()
        # Relevance (is this about the company, is it a milestone, is it
        # a roadmap) is judged on the HEADLINE and SNIPPET only. The body
        # is searched for substance but never for relevance: a full
        # article mentions many companies and uses "plans to" about
        # someone else's product, and letting it decide relevance would
        # reintroduce exactly the passing-mention failures the press
        # layer already demonstrated.
        blob = f"{headline} {snippet}"
        substance_text = f"{blob} {body}" if body else blob

        # The company must actually be named. A per-company search
        # returns results the engine judged relevant to the QUERY, which
        # is not the same as being about the company - a "Global supply
        # chain" roundup surfaced under Loongson's query turned out to
        # be about Firmus and OpenAI. Confirmed live; this check removed
        # it and nothing else.
        company_name = (meta.get("company") or "").split()[0]
        if company_name and company_name.lower() not in blob.lower():
            continue
        if _C4_COMMENTARY_RE.search(blob):
            continue
        if not _C4_MILESTONE_RE.search(blob):
            continue
        # A plan is not a milestone - the spec's own distinction between
        # an announced chip and a shipped one.
        if _C4_ROADMAP_RE.search(blob):
            logger.info("[CHINA] c4 roadmap, not a milestone: %r",
                        headline[:70])
            continue
        headline_key = (meta.get("code") or "", headline.lower()[:60])
        if headline_key in seen_headlines:
            continue
        seen_headlines.add(headline_key)

        substance = sorted({m.group(0).lower()
                            for m in _C4_SUBSTANCE_RE.finditer(
                                substance_text)})
        results.append({
            "article": article,
            "result": {
                "signal": "weak_signal",
                "reason": (
                    f"{meta.get('company')} accelerator milestone: "
                    f"{headline[:70]}"
                    + (f" [{', '.join(substance[:3])}]" if substance
                       else " (no volume, customer or award stated)")),
                "metadata": {
                    "source_category": "cn_press",
                    "signal_type": "C4",
                    "company": meta.get("company"),
                    "code": meta.get("code"),
                    # Recorded so a later rule can promote on it once
                    # article bodies are available for this source.
                    "substance_markers": substance,
                    "has_substance": bool(substance),
                    "direction": "opposite",
                },
            },
        })

    logger.info("[CHINA] c4 accelerator milestones: %d", len(results))
    return results


# ---------------------------------------------------------------------------
# Read-through: which US names a Chinese signal reads to, and how
# ---------------------------------------------------------------------------
#
# The spec's §4 gives every tracked Chinese company a set of US names
# and a DIRECTION, and §1 calls the inversion this market's defining
# property: "a Chinese equipment maker winning share is revenue leaving
# Applied Materials". Without the tickers a result says "this reads
# negatively" without saying for whom, which is half a signal.
#
# DIRECTION IS PER (chinese company, us company, signal category), NOT
# PER COMPANY. That was flagged on the spec and the data bears it out -
# eleven of twenty names are BOTH or MIXED in §4's own tables:
#   SMIC          OPPOSITE to TSMC/UMC/GFS on foundry share, but SAME
#                 for AMAT/LRCX/KLAC, whose tools it buys
#   ACM Shanghai  SAME for its own US-listed parent ACMR, OPPOSITE for
#                 AMAT/LRCX
#   Baidu         SAME for NVDA on purchases, OPPOSITE on its own chips
#   Rare earth    OPPOSITE to MP commercially (C2), SAME politically
#                 (C1) - a Chinese export restriction helps the only
#                 non-Chinese producer
# A single direction column per company would state the opposite of the
# truth on those rows, so the key carries the category.
#
# Read-through, platform/accelerator roles and every other per-company
# fact now live in ONE table, pipeline/china_companies.py - see its
# docstring for why (three code-keyed structures, three chances to miss
# one when adding a company, and a miss fails silently). Imported here
# rather than re-stated.


def attach_read_through(results: list[dict[str, Any]]) -> None:
    """Add read-through tickers and direction to each result, in place.

    Writes ``metadata.read_through`` and, where every link agrees,
    ``metadata.direction``. Where a company's links disagree - SMIC is
    OPPOSITE to TSMC and SAME for AMAT on the same filing - `direction`
    is set to "mixed" and the per-ticker breakdown in `read_through`
    carries the detail. Collapsing that to one value would state the
    opposite of the truth for half the names.
    """
    attached = 0
    for result in results:
        meta = result.get("result", {}).get("metadata") or {}
        links = read_through_for(meta.get("code"), meta.get("signal_type"))
        if not links:
            continue
        meta["read_through"] = links
        directions = {link["direction"] for link in links}
        meta["direction"] = (directions.pop() if len(directions) == 1
                             else "mixed")

        # The same names, also in entities_json - the column that
        # exists for "who does this row name". The Chinese subject
        # first, then every US ticker the signal reaches. `type`
        # distinguishes them so a consumer filtering for US exposure
        # does not pick up the Chinese issuer, and
        # entity_names_normalized (built at insert) makes both
        # filterable without parsing the metadata blob.
        #
        # `metadata.company` stays, and is NOT redundant with this.
        # The two answer different questions: metadata.company is the
        # SUBJECT of the row - the one company the signal is about,
        # which every classifier and the checkpoint prompt read (29
        # call sites) - while entities_json is the flat list of every
        # name the row touches, subject and counterparties together,
        # for filtering. Collapsing them would force every reader to
        # scan a list and guess which entry is the subject.
        res = result.setdefault("result", {})
        ents = list(res.get("entities") or [])
        seen = {(e.get("name"), e.get("type")) for e in ents}
        for name, kind in (
            [(meta.get("company"), "company")] if meta.get("company") else []
        ) + [(t, "ticker")
             for link in links for t in link.get("tickers", [])]:
            if name and (name, kind) not in seen:
                ents.append({"name": name, "type": kind})
                seen.add((name, kind))
        if ents:
            res["entities"] = ents
        attached += 1
    logger.info("[CHINA] read-through attached to %d/%d results",
                attached, len(results))


# ---------------------------------------------------------------------------
# WOULD CONFIRM / WOULD CONTRADICT (spec Section 8)
# ---------------------------------------------------------------------------
#
# Every signal in this domain is an INFERENCE about a US-listed company
# drawn from one Chinese datapoint. "Alibaba's capex rose 75%" is a
# fact; "this is good for Nvidia" is a judgment, and the spec asks each
# signal to name the next observation that would settle it either way.
#
# That matters more here than in any other market because the direction
# is usually INVERTED - a positive Chinese signal is a negative US read
# for most of these names - so a reader who disagrees with the
# inference needs to know what would change the answer.
#
# WHY THE MODEL WRITES THESE, AND WHAT IT IS NOT ALLOWED TO DO
#   A fixed template per signal type was built first and kept as the
#   fallback below. It is honest but generic: the same sentence for
#   every C5 row regardless of what the filing actually said.
#
#   The model is a better fit here than it was for the Japan summary
#   work that failed (see JAPAN_SIGNAL_MODEL's note in config.py): that
#   asked it to RESTATE already-final numbers, where it had nothing to
#   add and every opportunity to drift, and it fabricated figures at
#   temperature 0. This asks for a plausible future observation, where
#   there is no stored value to get wrong.
#
#   The real risk is the opposite one: a test that SOUNDS specific.
#   "Nvidia's China revenue exceeds $4.2bn next quarter" invents a
#   threshold and reads as analysis. So any number or date the signal's
#   own metadata does not already contain is rejected and the row falls
#   back to its template - the same guard C1 already applies to model-
#   supplied effective dates, and for the same reason.
_CHECKPOINT_TIMEOUT = 45.0
_CHECKPOINT_CONCURRENCY = 5

# Digits that are not part of a signal-type code (C1..C7) or an ordinary
# word. Any other number, percentage, currency amount or year in the
# model's output is treated as invented.
_CHECKPOINT_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,.]*\s*%?")
_CHECKPOINT_MONTH_RE = re.compile(
    r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d",
)
# A specific calendar slot is as much an invention as a figure: "by Q3"
# commits the signal to a deadline nothing in the filing supports.
# "the next quarter" is relative and allowed; "Q3", "H1", "FY2027" are
# not. Matched case-insensitively.
_CHECKPOINT_PERIOD_RE = re.compile(r"(?i)\b(?:[QH]\d|FY\s?\d{2,4})\b")
# Quantities the digit pattern cannot see. A model told not to write
# "20%" can still write "twenty percent" or "doubles", which reads just
# as specific to a trader and is just as unsupported. Deliberately does
# NOT include "half" or "double" as bare adjectives in other senses -
# only the quantity spellings.
_CHECKPOINT_WORD_NUMBER_RE = re.compile(
    r"(?i)\b(?:doubl\w+|tripl\w+|quadrupl\w+|halv\w+"
    r"|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|hundred|thousand|million|billion|trillion)\b"
    r"(?!\s*(?:of|the)\b)")

_CHECKPOINT_SYSTEM_PROMPT = (
    "You state how a market signal about a Chinese company could be "
    "checked against future evidence.\n\n"
    "You are given one signal and the US-listed companies it is read to "
    "affect, with a direction:\n"
    "  same      the US company moves WITH the Chinese company's good news\n"
    "  opposite  the US company moves AGAINST it - the Chinese company "
    "is taking its business\n\n"
    "Return ONLY a JSON object:\n"
    '  {"supports": "...", "weakens": "..."}\n\n'
    "supports   one future, observable event that would support this "
    "reading\n"
    "weakens    one that would undermine it\n\n"
    "RULES - these matter more than fluency:\n"
    "- NEVER invent a number, percentage, dollar amount, date, quarter "
    "or year. Say 'rises', 'falls', 'the next quarter' - never "
    "'rises 20%' or 'by Q3 2027'. A specific-sounding fabricated "
    "threshold is worse than a general true statement.\n"
    "- Name only the companies given to you. Do not introduce others.\n"
    "- Each answer is ONE sentence, under 25 words, stating something "
    "that could actually be observed - a disclosed figure, a filing, a "
    "published statistic. Not a feeling or an opinion.\n"
    "- Respect the direction. If it is 'opposite', confirmation means "
    "the US company does WORSE, not better."
)

# Fallback, and the floor on quality. Keyed by (signal_type, direction)
# because direction decides what confirmation even means: under
# `opposite` the US name doing worse is the CONFIRMING observation.
# `mixed` and unknown types fall through to the generic pair.
_CHECKPOINT_TEMPLATES: dict[tuple[str, str], tuple[str, str]] = {
    ("C1", "same"): (
        "The named US companies report improved China access or volumes "
        "after the measure takes effect.",
        "The measure is narrowed, delayed, or applied without affecting "
        "the named companies."),
    ("C1", "opposite"): (
        "The named US companies disclose reduced China revenue or "
        "licence denials after the measure takes effect.",
        "The measure lapses unenforced, or exemptions leave their China "
        "business unchanged."),
    ("C2", "same"): (
        "The named US companies report rising China revenue in the same "
        "period.",
        "Their China revenue falls while this company's rises, breaking "
        "the link."),
    ("C2", "opposite"): (
        "The named US companies report falling China revenue or lost "
        "share in the same product line.",
        "They hold or grow China revenue despite this company's gains, "
        "meaning the market grew rather than shifted."),
    ("C3", "same"): (
        "The named US equipment makers report rising China orders or "
        "backlog in the following quarter.",
        "The commitment is restated downward, delayed, or filled by "
        "domestic suppliers instead."),
    ("C3", "opposite"): (
        "The named US companies report lost orders or reduced China "
        "guidance as this capacity comes online.",
        "The announced capacity slips, is cancelled, or runs at low "
        "utilisation."),
    ("C4", "same"): (
        "The named US companies report design wins alongside this "
        "product.",
        "The product fails to reach volume production or wins no "
        "disclosed customer."),
    ("C4", "opposite"): (
        "A named Chinese customer discloses switching from the US part "
        "to this one, or the US company guides China revenue lower.",
        "The product stays at sampling, or buyers continue to disclose "
        "the US part - a launch is not adoption."),
    ("C5", "same"): (
        "The named US suppliers report rising China data-centre revenue "
        "in the following quarter.",
        "The spending is restated downward, or is disclosed as domestic "
        "accelerator procurement rather than US hardware."),
    ("C5", "opposite"): (
        "The named US suppliers report falling China data-centre revenue "
        "as this spending is absorbed domestically.",
        "They report rising China revenue over the same period, meaning "
        "the spending reached them after all."),
    ("C6", "same"): (
        "The following month's trade figures continue in the same "
        "direction, and the producing country's own data agrees.",
        "The figure is revised back toward its trailing level, or was an "
        "estimate rather than a filed return."),
    ("C6", "opposite"): (
        "Domestic production data rises over the same period the import "
        "figure falls, showing substitution rather than lost demand.",
        "Domestic production is flat or falling too, meaning demand "
        "weakened rather than shifted to local supply."),
    ("C7", "same"): (
        "The US company confirms the action in its own filing or "
        "guidance.",
        "The company denies it, or the action is reversed before taking "
        "effect."),
    ("C7", "opposite"): (
        "The US company discloses reduced China revenue, a licence "
        "denial, or a withdrawn product as a result.",
        "It reports no material China impact, or secures an exemption."),
}

_CHECKPOINT_GENERIC = (
    "The named US companies' next disclosure moves in the direction this "
    "signal implies.",
    "Their next disclosure moves the other way, or the underlying figure "
    "is restated.",
)

# Used where the signal reaches NO US ticker - C1 policy measures and C6
# trade series, which attach to a ministry or a reporting country rather
# than to a company. The templates above all open "The named US
# companies", which on those rows named nobody: confirmed on the first
# full run, 10 of 37 signals promised a specificity they did not carry.
# Rather than leave a dangling reference, these say what can actually be
# watched for a measure or a series.
# WHY THESE NAME NO US COMPANY, and what it would take to.
#   `read_through` is keyed by COMPANY CODE. A MOFCOM announcement has
#   no company code - it carries `policy_categories` (["semiconductor"])
#   and `named_items`, which are Chinese entity CATEGORIES
#   (集成电路设计企业, "IC design enterprises"), not US firms. So no
#   lookup can attach a ticker to a C1 row today, and the text says
#   "a US-listed supplier" because that is the honest scope of the
#   claim. The same holds for C6, which attaches to a reporting
#   country.
#
#   Naming them would mean a second, category-level map
#   (semiconductor -> AMAT/LRCX/KLAC/NVDA, rare_earth -> MP). That is a
#   deliberately looser inference than the company-level read-through,
#   which rests on a specific competitive or supply relationship, and
#   it is not built: a policy measure's real incidence depends on the
#   measure, not on the sector it is filed under.
_CHECKPOINT_UNATTACHED: dict[str, tuple[str, str]] = {
    "C1": (
        "A US-listed supplier discloses a licence denial, reduced China "
        "revenue, or a withdrawn product attributing it to this measure.",
        "The measure lapses unenforced, is narrowed on review, or no "
        "affected party reports a material effect."),
    "C6": (
        "The following month's figure continues in the same direction, and "
        "China's own production data for the period moves the opposite way "
        "- the pattern that separates substitution from lost demand.",
        "The figure is revised back toward its trailing median, or was "
        "served as an estimate rather than a filed return."),
}


def _name_tickers(text: str, tickers: list[str]) -> str:
    """Replace the templates' generic company reference with real names.

    A template reads "The named US companies report..." because it is
    written once per (signal type, direction) and cannot know which
    tickers a given row carries. Where the row does carry them, saying
    "AMAT, LRCX or KLAC" is strictly better than "the named US
    companies" - it is the same claim with the names filled in, and a
    reader can act on it.
    """
    if not tickers:
        return text
    if len(tickers) == 1:
        named = tickers[0]
    elif len(tickers) == 2:
        named = f"{tickers[0]} or {tickers[1]}"
    else:
        named = ", ".join(tickers[:-1]) + f" or {tickers[-1]}"
    for generic, repl in (
        ("The named US companies", named),
        ("The named US suppliers", named),
        ("The named US equipment makers", named),
        ("the named US companies", named),
    ):
        text = text.replace(generic, repl)
    # The templates are written for a plural subject ("companies
    # report"). One ticker makes that subject singular, so the verb has
    # to follow or the sentence reads as a typo in a trader-facing card.
    if len(tickers) == 1:
        text = re.sub(
            r"^(" + re.escape(named) + r") (report|hold|disclose|guide"
            r"|continue|grow|fail|stay|reports a|secures)\b",
            lambda m: f"{m.group(1)} {m.group(2)}s"
            if not m.group(2).endswith(("s", "s a")) else m.group(0),
            text)
    return text


def _checkpoint_template(signal_type: str | None,
                      direction: str | None) -> tuple[str, str]:
    """The fallback pair for one signal type and direction.

    A row with no usable direction - `mixed`, where the links point
    both ways, or none at all - still gets its signal type's OPPOSITE
    pair rather than the generic one. Two reasons: `opposite` is the
    common case in this market, and the type-specific text ("the
    spending is disclosed as domestic accelerator procurement") says
    something real about what to watch, where the generic text says
    almost nothing. The generic pair is the last resort, for a signal
    type this table does not know.
    """
    if signal_type:
        if direction:
            pair = _CHECKPOINT_TEMPLATES.get((signal_type, direction))
            if pair:
                return pair
        pair = _CHECKPOINT_TEMPLATES.get((signal_type, "opposite"))
        if pair:
            return pair
    return _CHECKPOINT_GENERIC


def _checkpoint_fabricates(text: str, allowed: set[str]) -> bool:
    """True if the text states a number, date or period the signal did not.

    `allowed` holds every numeric string already present in the signal's
    own metadata, so a model repeating a figure the filing actually
    stated is fine - inventing a new one is not.

    Covers three spellings of the same offence, all confirmed reachable
    against the live model: a digit ("20%"), a word ("twenty percent",
    "doubles"), and a calendar slot ("Q3", "FY2027"). The first was
    caught by the original guard; the other two passed it, which is why
    they are here.
    """
    if _CHECKPOINT_MONTH_RE.search(text):
        return True
    if _CHECKPOINT_PERIOD_RE.search(text):
        return True
    if _CHECKPOINT_WORD_NUMBER_RE.search(text):
        return True
    for match in _CHECKPOINT_NUMBER_RE.findall(text):
        token = match.strip().rstrip("%").strip().rstrip(".,")
        if token and token not in allowed:
            return True
    return False


# A ticker-shaped token: 1-5 capitals, standing alone. Deliberately
# matches more than real tickers (IT, AI, US and the signal codes all
# look like this) - the allowed set below carries the exclusions, and
# over-matching only ever costs a fallback to the template.
_CHECKPOINT_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")

# Capitalised tokens that are not company references. Without these the
# guard would reject its own correct output: "US" appears in almost
# every sentence, and the signal type is sometimes quoted back.
_CHECKPOINT_TICKER_STOPWORDS = frozenset({
    "US", "USA", "AI", "IT", "A", "I", "THE", "AND", "OR", "IF", "IN",
    "ON", "AT", "TO", "BY", "AS", "IS", "ITS", "NOT", "NO", "CHINA",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "YOY", "HK", "RMB",
    "CEO", "CFO", "GPU", "GPUS", "CPU", "CPUS", "IC", "ICS", "R",
    "D", "EU", "UK", "SEC",
})


def _checkpoint_invents_company(text: str, allowed: set[str]) -> str | None:
    """The first ticker in the text that was not supplied, or None.

    The prompt tells the model to name only the companies it is given.
    This enforces it, because that instruction is the one whose breach
    nothing downstream can catch: a confirmation naming Intel on a
    GigaDevice signal reads as a researched relationship, and a reader
    has no way to tell it was invented. Direction is the same class of
    problem and is never asked of the model at all - it is passed in
    and copied from the read-through table.

    Only all-capital tokens are checked. A model writing "Nvidia" in
    prose rather than "NVDA" is describing a company it was given (the
    prompt supplies tickers), and chasing every company's written forms
    here would duplicate the alias handling the universe already does.

    `allowed` must therefore carry the SUBJECT company's own name as
    well as the US tickers. Confirmed live on the first full run: "MP
    reports lower revenue following JL MAG expansion" was rejected
    because "JL" - a fragment of the Chinese company the signal is
    about - is ticker-shaped. Naming the subject is not invention, and
    rejecting it cost a correct answer its model-written text.
    """
    for token in _CHECKPOINT_TICKER_RE.findall(text):
        if token in _CHECKPOINT_TICKER_STOPWORDS or token in allowed:
            continue
        return token
    return None


def _checkpoint_allowed_numbers(meta: dict[str, Any]) -> set[str]:
    """Every numeric string the signal's own metadata already contains."""
    allowed: set[str] = set()
    for value in meta.values():
        if isinstance(value, (int, float)):
            allowed.add(str(value))
            allowed.add(f"{value:g}")
            if isinstance(value, float) and value.is_integer():
                allowed.add(str(int(value)))
        elif isinstance(value, str):
            allowed.update(t.strip().rstrip("%").rstrip(".,")
                           for t in _CHECKPOINT_NUMBER_RE.findall(value))
    return {a for a in allowed if a}


def _call_checkpoint_model(
    signal_type: str, direction: str, company: str, reason: str,
    tickers: list[str], model: str | None = None,
) -> tuple[str, str] | None:
    """Ask the model for one confirm/contradict pair, or None."""
    import config

    api_key = config.OPENAI_API_KEY
    if not api_key:
        return None

    payload = {
        # CHINA_SIGNAL_MODEL, same tier as every other call in this
        # domain - see its note in config.py.
        "model": model or config.CHINA_SIGNAL_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _CHECKPOINT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"SIGNAL TYPE: {signal_type}\n"
                f"CHINESE COMPANY: {company}\n"
                f"WHAT HAPPENED: {reason}\n"
                f"US COMPANIES AFFECTED: {', '.join(tickers)}\n"
                f"DIRECTION: {direction}"
            )},
        ],
    }
    try:
        req = Request(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=_CHECKPOINT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = (data.get("choices", [{}])[0]
                   .get("message", {}).get("content", "") or "").strip()
    except Exception as exc:
        logger.warning("[CHINA] checkpoint call failed %s/%s: %s",
                       signal_type, company, exc)
        return None

    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    try:
        parsed = json.loads(content)
    except Exception:
        logger.warning("[CHINA] checkpoint returned non-JSON: %r",
                       content[:120])
        return None

    confirm = (parsed.get("supports") or "").strip()
    contradict = (parsed.get("weakens") or "").strip()
    if not confirm or not contradict:
        return None
    return confirm, contradict


def attach_checkpoint(results: list[dict[str, Any]],
                        model: str | None = None) -> None:
    """Add supports / weakens to each result, in place.

    Runs AFTER attach_read_through, which it depends on: the model is
    told which US tickers the signal reaches rather than being asked to
    infer them. Letting it guess would produce confident, wrong
    relationships - and a wrong DIRECTION is the one error nothing
    downstream can catch, since it flips a signal from bullish to
    bearish for a US name.

    Rows with no read-through still get a pair, from the template -
    the question "what would change your mind" is worth answering even
    where no US name is attached yet.

    Every row ends up with both fields. The model's answer is used
    where it passes the fabrication guard; otherwise the template is,
    and `checkpoint_source` records which, so a reader can tell a
    written test from a generic one.
    """
    if not results:
        return

    def _fill(result: dict[str, Any]) -> str:
        meta = result.get("result", {}).get("metadata") or {}
        signal_type = meta.get("signal_type")
        direction = meta.get("direction")
        tickers = sorted({t for link in (meta.get("read_through") or [])
                          for t in link.get("tickers", [])})

        # A `mixed` row reads both ways at once and the model cannot be
        # told one direction for it; the template handles it honestly.
        if tickers and direction in ("same", "opposite"):
            pair = _call_checkpoint_model(
                signal_type or "?", direction,
                meta.get("company") or meta.get("code") or "?",
                result.get("result", {}).get("reason") or "",
                tickers, model=model)
            if pair:
                allowed_nums = _checkpoint_allowed_numbers(meta)
                # The subject company's own name counts as allowed: the
                # model is told which Chinese company the signal is
                # about, so naming it back is not invention.
                allowed_tickers = set(tickers) | {
                    w.upper() for w in
                    re.findall(r"[A-Za-z]+", meta.get("company") or "")}
                bad_figure = any(_checkpoint_fabricates(p, allowed_nums)
                                 for p in pair)
                invented = next(
                    (c for c in (_checkpoint_invents_company(p, allowed_tickers)
                                 for p in pair) if c), None)
                if not bad_figure and invented is None:
                    meta["supports"], meta["weakens"] = pair
                    meta["checkpoint_source"] = "model"
                    return "model"
                logger.info(
                    "[CHINA] checkpoint rejected (%s) %s/%s",
                    "invented figure" if bad_figure
                    else f"invented company {invented}",
                    signal_type, meta.get("company"))

        # No US ticker attached - a policy measure or a trade series.
        # Those get their own pair rather than a template that opens by
        # referring to companies the row does not name.
        if not tickers:
            pair = _CHECKPOINT_UNATTACHED.get(signal_type or "")
            if pair:
                meta["supports"], meta["weakens"] = pair
                meta["checkpoint_source"] = "template"
                return "template"

        confirm, contradict = _checkpoint_template(signal_type, direction)
        # Fill the real tickers into the template's generic reference.
        meta["supports"] = _name_tickers(confirm, tickers)
        meta["weakens"] = _name_tickers(contradict, tickers)
        meta["checkpoint_source"] = "template"
        return "template"

    with ThreadPoolExecutor(max_workers=_CHECKPOINT_CONCURRENCY) as executor:
        sources = list(executor.map(_fill, results))
    logger.info("[CHINA] checkpoint attached: %d model, %d template",
                sources.count("model"), sources.count("template"))


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------
#
# The spec's §6 gives China three properties that make its translation
# setup different from Taiwan's, and all three shape what is below.
#
#   SIMPLIFIED, NOT TRADITIONAL
#     Taiwan's path is configured for traditional characters. Reusing it
#     would translate mainland text with the wrong assumption. This is a
#     separate function with its own prompt for that reason - the spec
#     says so explicitly, and the data agrees: SMIC's HK filings are
#     traditional while its Shanghai filings are simplified, so the two
#     scripts appear in the SAME domain and the prompt must handle both.
#
#   SIX OF TWENTY COMPANIES ARE ALREADY BILINGUAL
#     Hong Kong listing rules require English, so hkex_filing rows are
#     already English and must never be sent to a translator. Neither
#     must press_cn_english_check, which is English by definition.
#     Detected by script, not by source_type, so an English title filed
#     on a Chinese source is also skipped.
#
#   COMPANY NAMES ARE NEVER TRANSLATED
#     They come from the hardcoded universe. Taiwan confirmed live that
#     LLM translation of short Chinese company names produces serious
#     errors - 2383 Elite Material came back as "Taiwan Semiconductor
#     Manufacturing Company". metadata.company already holds the correct
#     English name on every row that has one.
#
# Only the TITLE is translated. A body runs to thousands of characters
# and is read by rules, not people; the title is what a reader sees.
# Bodies stay in their source language, which is also what every
# extraction rule in this module already expects.
_CJK_RE = re.compile(r"[一-鿿]")

_CHINA_TRANSLATE_SYSTEM_PROMPT = (
    "You translate Chinese financial and regulatory headlines into "
    "English. The text may be in SIMPLIFIED characters (mainland "
    "filings and ministry announcements) or TRADITIONAL (Hong Kong "
    "listings) - handle both.\n\n"
    "Translate literally and completely. Do not summarise, interpret, "
    "expand abbreviations, or add context that is not in the source. "
    "Keep every number, date, percentage and document number exactly as "
    "written.\n\n"
    "Keep company names in the form a financial reader would recognise "
    "in English where one is standard (中芯国际 -> SMIC, 北方华创 -> "
    "Naura), and otherwise transliterate rather than inventing a name.\n\n"
    "Output ONLY the translated headline. No quotation marks, no notes, "
    "no explanation."
)

_CHINA_TRANSLATE_TIMEOUT = 45.0
_CHINA_TRANSLATE_CONCURRENCY = 5
# A headline, not a document. Anything longer is a title field that has
# picked up body text and is not worth a model call.
_CHINA_TRANSLATE_MAX_CHARS = 400


def _translate_one(text: str, model: str) -> str | None:
    """One headline, Chinese to English. None on any failure."""
    import config

    api_key = config.OPENAI_API_KEY
    if not api_key:
        return None
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _CHINA_TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": text[:_CHINA_TRANSLATE_MAX_CHARS]},
        ],
    }
    try:
        req = Request(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=_CHINA_TRANSLATE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        out = (data.get("choices", [{}])[0]
               .get("message", {}).get("content", "") or "").strip()
    except Exception as exc:
        logger.warning("[CHINA_TRANSLATE] failed for %r: %s",
                       text[:50], exc)
        return None
    # A translation that still contains CJK did not translate.
    if not out or _CJK_RE.search(out):
        return None
    return out


def translate_china_results(
    results: list[dict[str, Any]], model: str | None = None,
) -> None:
    """Add an English title to every result whose title is Chinese.

    Mutates ``results`` in place, writing ``metadata.translated_title``.
    The original title is never overwritten - a reader may need to check
    the source, and the extraction rules read the Chinese.

    Runs on CLASSIFIED results rather than on every fetched article, so
    the cost tracks what actually gets stored: measured on the stored
    year, 171 of 281 classifications carry a Chinese title, against 935
    pooled articles. Translating at fetch time would have paid for
    hundreds of rows that Gate 1 discards.

    A failure leaves the field absent rather than setting it to None, so
    a consumer can tell "not translated" from "translated to nothing" -
    same convention Taiwan's translator uses.
    """
    import config

    model = model or config.CHINA_SIGNAL_MODEL
    pending = [
        r for r in results
        if _CJK_RE.search((r.get("article") or {}).get("title") or "")
        and not (r.get("result") or {}).get(
            "metadata", {}).get("translated_title")
    ]
    if not pending:
        return

    def _apply(result: dict[str, Any]) -> bool:
        title = (result.get("article") or {}).get("title") or ""
        translated = _translate_one(title, model)
        if translated:
            result["result"].setdefault("metadata", {})
            result["result"]["metadata"]["translated_title"] = translated
            return True
        return False

    with ThreadPoolExecutor(
            max_workers=_CHINA_TRANSLATE_CONCURRENCY) as executor:
        done = sum(executor.map(_apply, pending))
    logger.info("[CHINA_TRANSLATE] %d/%d title(s) translated",
                done, len(pending))

    # The title is not the only Chinese field. C1's model extracts
    # `measure_type` and the product categories in `entities_json`
    # straight from the document, so both come back in Chinese -
    # 出口许可申报通知, 集成电路设计企业 - and a reader who needed the
    # title translated needs these too. Confirmed on the full run: 4
    # measure_type values and 5 rows of entities were left untranslated
    # while every title was done.
    #
    # The English goes in a SEPARATE key rather than replacing the
    # original, the same rule translated_title follows: a figure or a
    # name a reader may need to check against the source document must
    # survive verbatim.
    def _apply_fields(result: dict[str, Any]) -> int:
        meta = result.get("result", {}).get("metadata") or {}
        n = 0
        mt = meta.get("measure_type")
        if mt and _CJK_RE.search(mt) and not meta.get("measure_type_en"):
            t = _translate_one(mt, model)
            if t:
                meta["measure_type_en"] = t
                n += 1
        for ent in result.get("result", {}).get("entities") or []:
            name = ent.get("name") or ""
            if _CJK_RE.search(name) and not ent.get("name_en"):
                t = _translate_one(name, model)
                if t:
                    ent["name_en"] = t
                    n += 1
        return n

    needs = [
        r for r in results
        if _CJK_RE.search(
            str((r.get("result", {}).get("metadata") or {}).get(
                "measure_type") or ""))
        or any(_CJK_RE.search(x.get("name") or "")
               for x in (r.get("result", {}).get("entities") or []))
    ]
    if needs:
        with ThreadPoolExecutor(
                max_workers=_CHINA_TRANSLATE_CONCURRENCY) as executor:
            fields = sum(executor.map(_apply_fields, needs))
        logger.info("[CHINA_TRANSLATE] %d Chinese field(s) translated "
                    "across %d row(s)", fields, len(needs))


def classify_china_signal_batch(
    articles: list[dict[str, Any]],
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Run every implemented China classifier on one pooled batch and
    return ``{"article", "result"}`` dicts for
    insert_china_signal_classification.

    Same top-level shape as classify_korea_signal_batch. What is
    implemented today is C1 (policy action, with the §9.1 binding call),
    C7 (US company named in an action), and Gate 1 (filing triage).

    C2-C6 are NOT here, deliberately. Every one of them depends on a
    numeric threshold the stored data cannot yet support - see this
    module's own docstring. Filings that survive Gate 1 are returned as
    `extracted`, carrying their category but no Signal/Weak/Noise
    judgment, so the distribution those rules need can accumulate
    without a fabricated verdict being written in the meantime.

    Noise is NOT returned. A filing that Gate 1 discarded has no row
    written: the China spec's own signal set has no rule that would ever
    surface it, and storing 73 shareholder-meeting resolutions per run
    to label them noise would bury the handful that matter. The
    `unclassified` bucket IS returned, because an unrecognised filing
    shape is a gap in the table rather than a judgment about the filing.
    """
    results: list[dict[str, Any]] = []

    # --- C1 + C7: policy ------------------------------------------------
    policy = gate_policy(articles)
    relevant = classify_policy_binding(policy["relevant"], model=model)
    c7_hits = {r.get("url"): r for r in classify_us_company_action(relevant)}

    for row in relevant:
        c7 = c7_hits.get(row.get("url"))
        # §7.1: a binding measure is a Signal; a draft, a plan or a
        # restatement is Weak. §7.7 overrides upward - a named US company
        # in an action context is always a Signal regardless of binding
        # status, and is never Noise.
        if c7 and c7["c7_label"] == "SIGNAL":
            signal = "signal"
            reason = (f"Names {', '.join(c7['c7_named_us'])} in a regulatory "
                      f"action ({row['binding']})")
        elif row["binding"] == "BINDING":
            signal = "signal"
            reason = f"Binding measure ({', '.join(row['policy_categories'])})"
        else:
            signal = "weak_signal"
            reason = (f"{row['binding'].title()} "
                      f"({', '.join(row['policy_categories'])})")

        metadata = {
            "source_category": "cn_policy",
            "signal_type": "C7" if c7 else "C1",
            "policy_categories": row["policy_categories"],
            "binding": row["binding"],
            "binding_source": row["binding_source"],
        }
        # Only ever set when the field carries something. An absent key
        # reads as "not stated", which is the honest answer and the
        # convention the rest of this service uses.
        for key, value in (
            ("effective_date", row.get("effective_date")
             or row.get("model_effective_date")),
            ("measure_type", row.get("model_measure_type")),
            ("effective_date_disputed",
             row.get("effective_date_disputed") or None),
        ):
            if value:
                metadata[key] = value

        # Everything this measure NAMES, in one place and in the shape
        # the rest of the service uses. `named_foreign` is included
        # here for the first time: the C1 model has always extracted it
        # (prompt: "named foreign companies or countries, if any") and
        # the persist loop above dropped it on the floor, which is
        # exactly the field a reader asking "who does this measure
        # touch" wants most.
        entities = [
            {"name": n, "type": "ticker"}
            for n in (c7["c7_named_us"] if c7 else [])
        ] + [
            {"name": n, "type": "foreign_named"}
            for n in (row.get("model_named_foreign") or [])
        ] + [
            {"name": n, "type": "product_category"}
            for n in (row.get("model_named_items") or [])
        ]

        results.append({
            "article": row,
            "result": {"signal": signal, "reason": reason,
                       "entities": entities, "metadata": metadata},
        })

    # --- C4: accelerator milestones ----------------------------------------
    results.extend(classify_accelerator_milestone(articles))

    # --- C2: substitution progress ---------------------------------------
    results.extend(classify_substitution_progress(articles))

    # --- C5: platform capex ---------------------------------------------
    results.extend(classify_platform_capex(articles))

    # --- C6: trade data -------------------------------------------------
    results.extend(classify_trade_deviation(articles))

    # --- Gate 1: filings ------------------------------------------------
    filings = gate_filings(articles)

    # --- C3: capacity / capital commitment --------------------------------
    # Runs on gated rows, since it needs filing_category.
    results.extend(classify_capacity_commitment(filings["candidate"]))

    # Every url already claimed by a real classifier - C2, C3, C4, C5,
    # not just C3. `source_id` is the article url and the DB has a
    # partial unique index on it, so a second row for the same url is
    # silently dropped by ON CONFLICT DO NOTHING and WHICH one survives
    # is arbitrary. Measured before this guard existed: 5 collisions in
    # a full run, each a C2 or C5 finding racing its own gate1
    # placeholder - so an earnings filing could persist as "no threshold
    # rule implemented" while its +178% revenue signal was thrown away.
    #
    # Built from the results list rather than per-classifier sets, so a
    # classifier added later is covered without touching this.
    claimed_urls = {r["article"].get("url") for r in results}

    for row in filings["candidate"] + filings["weak"] + filings["unclassified"]:
        if row.get("url") in claimed_urls:
            continue
        verdict = row["filing_verdict"]
        metadata: dict[str, Any] = {
            "source_category": "cn_disclosure",
            "signal_type": "gate1",
            "filing_verdict": verdict,
            "filing_category": row["filing_category"],
        }
        # Gate 2 runs on candidates only. A `weak` filing is a real
        # corporate action no rule reads yet, and an `unclassified` one
        # is a shape the table has never seen - extracting figures from
        # either would store numbers nothing will ever compare.
        if verdict == "candidate":
            figures = extract_filing_figures(row.get("body") or "")
            # Only attached when something was found. A JV supplemental
            # notice genuinely carries no figures, and an empty list
            # would read as "extraction failed" rather than "none
            # stated".
            if figures["amounts"]:
                metadata["amounts"] = figures["amounts"]
                metadata["max_amount"] = figures["max_amount"]
            if figures["percentages"]:
                metadata["percentages"] = figures["percentages"]
            # The C2 input. Kept separate from `percentages` because a
            # stated year-on-year change is a different kind of fact
            # from a percentage found in prose - it is the issuer's own
            # comparison against its own prior period, and is the only
            # form of it available (see the module docstring on why a
            # trailing series cannot be built from these filings).
            if figures["yoy_changes"]:
                metadata["yoy_changes"] = figures["yoy_changes"]
            if figures["financials"]:
                metadata["financials"] = figures["financials"]

        # `extracted` is not a signal label - it says a tradable fact may
        # be present and no rule exists to judge it yet. Stored as
        # weak_signal because agent_classifications has no fourth state
        # and weak is the honest floor: the item is real, unjudged, and
        # must not read as a confirmed signal.
        results.append({
            "article": row,
            "result": {
                "signal": "weak_signal",
                "reason": (f"Filing category '{row['filing_category']}' "
                           f"({verdict}) - no threshold rule implemented"),
                "metadata": metadata,
            },
        })

    # Which US names each signal reaches, and in which direction. Runs
    # before translation so a card has both by the time anything reads
    # it.
    attach_read_through(results)

    # Which US companies each row's own text actually names. Separate
    # from C7 proper, which scopes the SIGNAL to policy rows: across the
    # stored year every single alias hit was in a filing, not a policy
    # page, so scoping the entity list the same way recorded none of
    # them. Runs after read-through so a ticker already attached as a
    # modelled relationship is not duplicated as a bare mention.
    attach_named_us_entities(results, articles)

    # What would support or weaken each signal (spec Section 8).
    # Strictly after attach_read_through: it reads the tickers and
    # direction that call writes, rather than letting the model infer
    # which US company a Chinese signal reaches.
    attach_checkpoint(results, model=model)

    # Last, on the classified set only - see translate_china_results on
    # why this runs here rather than at fetch time.
    translate_china_results(results, model=model)

    logger.info("[CHINA] classify batch: %d results from %d articles",
                len(results), len(articles))
    return results


def gate_filings(articles: list[dict[str, Any]]) -> dict[str, list[dict]]:
    """Split one pooled batch of filings into candidates / noise /
    unclassified.

    Applies only to filing source_types (``cninfo_filing``,
    ``hkex_filing``). Policy, trade and press rows pass through untouched
    in ``other`` - they have their own paths and none of them is a
    corporate filing, so this title table would mean nothing against them.
    """
    buckets: dict[str, list[dict]] = {
        "candidate": [], "weak": [], "noise": [], "unclassified": [],
        "other": []}
    for article in articles:
        meta = article.get("metadata") or {}
        if meta.get("source_type") not in ("cninfo_filing", "hkex_filing"):
            buckets["other"].append(article)
            continue
        verdict, category = classify_filing_type(article.get("title") or "")
        enriched = {**article,
                    "filing_verdict": verdict,
                    "filing_category": category}
        buckets[verdict].append(enriched)

    logger.info(
        "[CHINA] gate1 candidates=%d weak=%d noise=%d unclassified=%d "
        "other=%d",
        len(buckets["candidate"]), len(buckets["weak"]),
        len(buckets["noise"]), len(buckets["unclassified"]),
        len(buckets["other"]))
    if buckets["unclassified"]:
        # Logged individually: each one is a filing shape the table has
        # never seen, and the title is what a human needs to extend it.
        for article in buckets["unclassified"][:20]:
            logger.info("[CHINA] gate1 UNCLASSIFIED title=%r",
                        (article.get("title") or "")[:120])
    return buckets
