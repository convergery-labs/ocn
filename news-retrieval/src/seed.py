"""Seed the database with initial domain and source data.

Run directly to populate a fresh database:

    python seed.py

The script is idempotent - rows that already exist (matched by slug
or URL) are silently skipped.
"""
import json
import logging
from typing import Any

from db import get_db, init_db, transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

RUN_STATUSES: list[str] = ["running", "completed", "failed"]

FREQUENCIES: list[dict[str, Any]] = [
    {"name": "daily",   "min_days_back": 1},
    {"name": "weekly",  "min_days_back": 7},
    {"name": "monthly", "min_days_back": 30},
]

DOMAINS: list[dict[str, Any]] = [
    {
        "name": "AI News",
        "slug": "ai_news",
        "description": (
            "Covers AI models, hardware, semiconductors, data centre"
            " infrastructure, energy, robotics, enterprise AI,"
            " security, policy, funding, and applied science."
        ),
    },
    {
        "name": "Smart Money",
        "slug": "smart_money",
        "description": (
            "Covers agentic payments, stablecoins, digital assets,"
            " embedded finance, cross-border settlement, AI fraud"
            " detection, and enterprise treasury automation."
        ),
    },
    {
        "name": "Adverse Media",
        "slug": "adverse_media",
        "description": (
            "Covers corporate misconduct, fraud, short-seller research,"
            " regulatory actions, and investigative journalism targeting"
            " companies in the AI economy universe."
        ),
    },
    {
        "name": "VC Commentary",
        "slug": "vc_commentary",
        "description": (
            "Covers venture capital theses, startup investing, AI economy"
            " market dynamics, and operator insights from leading VCs and"
            " founders."
        ),
    },
    {
        "name": "Company News",
        "slug": "company_news",
        "description": (
            "Company-specific news for entities in the AI economy universe,"
            " fetched via Alpha Vantage News & Sentiments API by ticker symbol."
        ),
    },
    {
        "name": "Geopolitical News",
        "slug": "geopolitical_news",
        "description": (
            "Covers geopolitical developments via U.S. federal actions:"
            " sanctions, export controls, tariffs, executive orders, and"
            " presidential documents affecting foreign policy and trade."
        ),
    },
    {
        "name": "Taiwan Market Signal",
        "slug": "taiwan_market_signal",
        "description": (
            "Monthly revenue and material announcements for Taiwan"
            " AI-supply-chain companies, fetched via the TWSE and TPEx"
            " OpenData APIs."
        ),
    },
    {
        "name": "Korea Market Signal",
        "slug": "korea_market_signal",
        "description": (
            "Regulator filings, Korean-language trade press, and"
            " semiconductor export statistics for Korea AI-supply-chain"
            " companies, fetched via DART (Financial Supervisory"
            " Service), GDELT/RSS, and a Korea Customs Service"
            " press-release scrape (see KOREA_CUSTOMS_EXPORT_SOURCE"
            " below - the data.go.kr structured API is blocked behind"
            " Korean-phone-verified signup, so this is a no-login"
            " fallback)."
        ),
    },
]

# P0 core universe (spec Section 14.1), hardcoded pending research-universe
# integration for Taiwan. Ticker codes are as listed on their exchange —
# 公司代號/SecuritiesCompanyCode in the TWSE/TPEx API responses.
# NOTE: 3324 (Auras Technology) is TPEx, not TWSE as some reference material
# states — verified live against both revenue dumps on 2026-08-19.
# native_name is the Chinese company name used for GDELT queries (native-
# language press generally refers to companies by this name, not the English
# one) — sourced from spec Section 14.1.
TAIWAN_TICKER_UNIVERSE: list[dict[str, str]] = [
    {"ticker": "2330", "company": "TSMC", "native_name": "台積電", "exchange": "TWSE"},
    {"ticker": "2317", "company": "Hon Hai / Foxconn", "native_name": "鴻海", "exchange": "TWSE"},
    {"ticker": "2382", "company": "Quanta", "native_name": "廣達", "exchange": "TWSE"},
    {"ticker": "3231", "company": "Wistron", "native_name": "緯創", "exchange": "TWSE"},
    {"ticker": "6669", "company": "Wiwynn", "native_name": "緯穎", "exchange": "TWSE"},
    {"ticker": "2356", "company": "Inventec", "native_name": "英業達", "exchange": "TWSE"},
    {"ticker": "3017", "company": "Asia Vital Components", "native_name": "奇鋐", "exchange": "TWSE"},
    {"ticker": "3324", "company": "Auras Technology", "native_name": "雙鴻", "exchange": "TPEx"},
    {"ticker": "2308", "company": "Delta Electronics", "native_name": "台達電", "exchange": "TWSE"},
    {"ticker": "3665", "company": "BizLink", "native_name": "貿聯-KY", "exchange": "TWSE"},
    {"ticker": "3533", "company": "Lotes", "native_name": "嘉澤", "exchange": "TWSE"},
    {"ticker": "2059", "company": "King Slide", "native_name": "川湖", "exchange": "TWSE"},
    {"ticker": "8210", "company": "Chenbro", "native_name": "勤誠", "exchange": "TWSE"},
    {"ticker": "2368", "company": "Gold Circuit Electronics", "native_name": "金像電", "exchange": "TWSE"},
    {"ticker": "2383", "company": "Elite Material", "native_name": "台光電", "exchange": "TWSE"},
    {"ticker": "3037", "company": "Unimicron", "native_name": "欣興", "exchange": "TWSE"},
    {"ticker": "3711", "company": "ASE Technology", "native_name": "日月光投控", "exchange": "TWSE"},
    {"ticker": "2449", "company": "King Yuan Electronics", "native_name": "京元電子", "exchange": "TWSE"},
    {"ticker": "3661", "company": "Alchip", "native_name": "世芯-KY", "exchange": "TWSE"},
    {"ticker": "5274", "company": "Aspeed Technology", "native_name": "信驊", "exchange": "TPEx"},
]


# Korea Signals spec, Section 3. stock_code is KRX's 6-character listing
# code, stored as a string everywhere — DART and KRX both return it as a
# zero-padded string (e.g. SK Hynix is "000660"), and coercing it to an int
# anywhere in the pipeline silently drops the leading zeros and produces a
# code that matches no company ("660" instead of "000660").
#
# group_prefix + exclude_terms exist because Korean business groups (재벌)
# share a name across many unrelated listed entities — e.g. multiple
# "Samsung"-branded companies exist that are not Samsung Electronics. The
# news-matching step (GDELT/RSS company-name filter) needs these to avoid
# attributing an unrelated group company's news to the tracked ticker.
#
# corp_code (DART's own 8-digit company identifier, distinct from
# stock_code) is intentionally omitted here — it is resolved at fetch time
# from DART's corpCode.xml bulk mapping (see src/dart_corp_code.py), not
# hardcoded, since DART's own filing-list API takes corp_code, not
# stock_code, and a wrong hardcoded value would fail silently (empty
# result, not an error).
KOREA_TICKER_UNIVERSE: list[dict[str, Any]] = [
    # Tier 1
    {"ticker": "000660", "company": "SK Hynix", "korean_name": "SK하이닉스", "group_prefix": "SK", "exclude_terms": []},
    {"ticker": "005930", "company": "Samsung Electronics", "korean_name": "삼성전자", "group_prefix": "Samsung", "exclude_terms": ["Samsung C&T", "Samsung Life", "Samsung SDI", "Samsung Fire"]},
    # Tier 2 — memory stacking chain
    {"ticker": "042700", "company": "Hanmi Semiconductor", "korean_name": "한미반도체", "group_prefix": "Hanmi", "exclude_terms": []},
    # Hanwha Semitech (한화세미텍) has NO public ticker - verified live
    # against four independent Korean financial sources (alphasquare,
    # Hankyung, FnGuide, Thinkpool) on 2026-09-22. It is a wholly-owned,
    # unlisted subsidiary of Hanwha Industrial Solutions, renamed from
    # 한화정밀기계 (Hanwha Precision Machinery) to 한화세미텍 in Feb 2025.
    # Ticker 272210 belongs to a DIFFERENT, unrelated company - 한화시스템
    # (Hanwha System, defense electronics/radar), not this one. This is
    # exactly the mistake the source spec's "check the code" warning was
    # flagging. Since it has no stock_code, DART's corp_code lookup and the
    # customs/filing fetchers below (which are keyed by listed ticker) do
    # not apply - this entry is a placeholder for the news-only fetchers
    # (GDELT/RSS), which can still query it by name.
    {"ticker": None, "company": "Hanwha Semitech", "korean_name": "한화세미텍", "group_prefix": "Hanwha", "exclude_terms": ["Hanwha Solutions", "Hanwha Aerospace", "Hanwha Life", "Hanwha Ocean", "Hanwha System"], "unlisted": True},
    {"ticker": "089030", "company": "Techwing", "korean_name": "테크윙", "group_prefix": "Techwing", "exclude_terms": []},
    {"ticker": "058470", "company": "Leeno Industrial", "korean_name": "리노공업", "group_prefix": "Leeno", "exclude_terms": []},
    {"ticker": "067310", "company": "Hana Micron", "korean_name": "하나마이크론", "group_prefix": "Hana", "exclude_terms": ["Hana Financial", "Hana Bank", "Hana Tour"]},
    {"ticker": "222800", "company": "Simmtech", "korean_name": "심텍", "group_prefix": "Simmtech", "exclude_terms": []},
    {"ticker": "007660", "company": "Isu Petasys", "korean_name": "이수페타시스", "group_prefix": "Isu", "exclude_terms": []},
    {"ticker": "353200", "company": "Daeduck Electronics", "korean_name": "대덕전자", "group_prefix": "Daeduck", "exclude_terms": ["Daeduck GDS"]},
    # Tier 3 — equipment, materials, chip making and power
    {"ticker": "402340", "company": "SK Square", "korean_name": "SK스퀘어", "group_prefix": "SK", "exclude_terms": []},
    {"ticker": "000990", "company": "DB HiTek", "korean_name": "DB하이텍", "group_prefix": "DB", "exclude_terms": ["DB Insurance", "DB Financial"]},
    {"ticker": "009150", "company": "Samsung Electro-Mechanics", "korean_name": "삼성전기", "group_prefix": "Samsung", "exclude_terms": ["Samsung C&T", "Samsung Life", "Samsung SDI", "Samsung Fire"]},
    {"ticker": "011070", "company": "LG Innotek", "korean_name": "LG이노텍", "group_prefix": "LG", "exclude_terms": ["LG Electronics", "LG Chem", "LG Display", "LG Energy Solution", "LG Uplus"]},
    {"ticker": "036930", "company": "Jusung Engineering", "korean_name": "주성엔지니어링", "group_prefix": "Jusung", "exclude_terms": []},
    {"ticker": "240810", "company": "Wonik IPS", "korean_name": "원익IPS", "group_prefix": "Wonik", "exclude_terms": ["Wonik Materials", "Wonik Holdings"]},
    {"ticker": "319660", "company": "PSK", "korean_name": "피에스케이", "group_prefix": "PSK", "exclude_terms": []},
    {"ticker": "357780", "company": "Soulbrain", "korean_name": "솔브레인", "group_prefix": "Soulbrain", "exclude_terms": []},
    {"ticker": "267260", "company": "HD Hyundai Electric", "korean_name": "HD현대일렉트릭", "group_prefix": "HD Hyundai", "exclude_terms": ["HD Hyundai Heavy Industries", "HD Hyundai Marine"]},
    {"ticker": "010120", "company": "LS Electric", "korean_name": "LS일렉트릭", "group_prefix": "LS", "exclude_terms": ["LS Cable", "LS Materials"]},
]


NEWSAPI_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "ai_news",
        "url": "newsapi:top-headlines",
        "name": "NewsAPI",
        "source_type": "newsapi",
        "frequency_name": "daily",
        "description": "Top headlines from technology, science, and business categories.",
        "config": {
            "endpoint": "top-headlines",
            "categories": ["technology", "science", "business"],
            "language": "en",
        },
    },
]

GOOGLE_NEWS_SOURCE: dict[str, Any] = {
    "domain_slug": "ai_news",
    "url": "google_news",
    "name": "Google News",
    "source_type": "google_news",
    "frequency_name": "daily",
    "description": "Google News search across AI topics via SerpAPI.",
    "config": {
        "queries": [
            "artificial intelligence",
            "AI chips GPU semiconductors",
            "AI regulation policy",
            "AI data training datasets",
            "AI stocks rally",
            "semiconductor stocks tariffs",
            "AI stocks market correction",
            "AI stocks regulation policy",
        ],
    },
}

SUBSTACK_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "ai_news",
        "url": "https://importai.substack.com/feed",
        "name": "Import AI",
        "frequency_name": "weekly",
        "description": "Weekly analysis of cutting-edge AI research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://simonw.substack.com/feed",
        "name": "Simon Willison's Newsletter",
        "frequency_name": "weekly",
        "description": "Hands-on AI/devtools/open-source analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://decision.substack.com/feed",
        "name": "Decision Intelligence",
        "frequency_name": "weekly",
        "description": "Cassie Kozyrkov on AI, decision science, and management.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://artificialintelligencemadesimple.substack.com/feed",
        "name": "Artificial Intelligence Made Simple",
        "frequency_name": "weekly",
        "description": "Technical, social and economic angles on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://berkeleyrdi.substack.com/feed",
        "name": "Agentic AI Weekly",
        "frequency_name": "weekly",
        "description": "AI agents and research updates.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://artificialintelligenceact.substack.com/feed",
        "name": "EU AI Act Newsletter",
        "frequency_name": "weekly",
        "description": "EU AI Act and regulation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiguide.substack.com/feed",
        "name": "AI: A Guide for Thinking Humans",
        "frequency_name": "weekly",
        "description": "Melanie Mitchell on AI for thoughtful readers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiagentssimplified.substack.com/feed",
        "name": "AI Agents Simplified",
        "frequency_name": "weekly",
        "description": "Practical explainers on AI agents.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://diamantai.substack.com/feed",
        "name": "DiamantAI",
        "frequency_name": "weekly",
        "description": "Agentic AI and engineering resources.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://wrk3.substack.com/feed",
        "name": "Work3 - The Future of Work",
        "frequency_name": "weekly",
        "description": "AI and work transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thezvi.substack.com/feed",
        "name": "Don't Worry About the Vase",
        "frequency_name": "weekly",
        "description": "Zvi on AI discourse and developments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://addyo.substack.com/feed",
        "name": "Elevate",
        "frequency_name": "weekly",
        "description": "Addy Osmani on AI and software development.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://jamwithai.substack.com/feed",
        "name": "Jam with AI",
        "frequency_name": "weekly",
        "description": "AI tools and workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://substack.jurgenappelo.com/feed",
        "name": "The Maverick Mapmaker",
        "frequency_name": "weekly",
        "description": "AI and management/future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cosmosinstitute.substack.com/feed",
        "name": "Cosmos Institute",
        "frequency_name": "weekly",
        "description": "AI and ideas.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thenuancedperspective.substack.com/feed",
        "name": "The Nuanced Perspective",
        "frequency_name": "weekly",
        "description": "Nuanced AI analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aixeducation.substack.com/feed",
        "name": "AI x Education",
        "frequency_name": "weekly",
        "description": "AI and education.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://nickpotkalitsky.substack.com/feed",
        "name": "Educating AI",
        "frequency_name": "weekly",
        "description": "Teaching and education with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://designingwithai.substack.com/feed",
        "name": "Designing with AI",
        "frequency_name": "weekly",
        "description": "Design workflows with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://epochai.substack.com/feed",
        "name": "Epoch AI",
        "frequency_name": "weekly",
        "description": "Benchmarks, scaling and research data.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaileadershipedge.substack.com/feed",
        "name": "The AI Leadership Edge",
        "frequency_name": "weekly",
        "description": "Leadership and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thedigitalleader.substack.com/feed",
        "name": "The Digital Leader",
        "frequency_name": "weekly",
        "description": "Digital strategy and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aifrontiersmedia.substack.com/feed",
        "name": "AI Frontiers",
        "frequency_name": "weekly",
        "description": "Frontier AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theagentarchitect.substack.com/feed",
        "name": "The AI Agent Architect",
        "frequency_name": "weekly",
        "description": "Architecting AI agents.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://oliverpatel.substack.com/feed",
        "name": "Enterprise AI Governance",
        "frequency_name": "weekly",
        "description": "Governance in enterprise AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://futureworklife.substack.com/feed",
        "name": "Ollie on Work",
        "frequency_name": "weekly",
        "description": "Work, management, AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aimaker.substack.com/feed",
        "name": "The AI Maker",
        "frequency_name": "weekly",
        "description": "Maker-focused AI building and workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://amistrongeryet.substack.com/feed",
        "name": "Second Thoughts",
        "frequency_name": "weekly",
        "description": "Thoughtful AI and product commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://frontierai.substack.com/feed",
        "name": "The AI Frontier",
        "frequency_name": "weekly",
        "description": "Frontier AI systems and economics.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://themediabrain.substack.com/feed",
        "name": "Peter Csathy's the brAIn",
        "frequency_name": "weekly",
        "description": "AI and media intelligence.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiblewmymind.substack.com/feed",
        "name": "AI blew my mind",
        "frequency_name": "weekly",
        "description": "Accessible AI insights.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://stevenadler.substack.com/feed",
        "name": "Clear-Eyed AI",
        "frequency_name": "weekly",
        "description": "Grounded AI policy and safety commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://msukhareva.substack.com/feed",
        "name": "AI Realist",
        "frequency_name": "weekly",
        "description": "Pragmatic view of AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thestrategystack.substack.com/feed",
        "name": "The Strategy Stack",
        "frequency_name": "weekly",
        "description": "Strategy thinking with AI lens.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaimonitor.substack.com/feed",
        "name": "The AI Monitor",
        "frequency_name": "weekly",
        "description": "Monitoring AI developments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiagenteconomy.substack.com/feed",
        "name": "The AI Agent Economy",
        "frequency_name": "weekly",
        "description": "Agent economy and startups.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aicentral.substack.com/feed",
        "name": "AI Central",
        "frequency_name": "weekly",
        "description": "General AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://unhypedai.substack.com/feed",
        "name": "Unhyped AI",
        "frequency_name": "weekly",
        "description": "Low-hype AI analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaiphilosopher.substack.com/feed",
        "name": "The AI Philosopher",
        "frequency_name": "weekly",
        "description": "Philosophical takes on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thehumanplaybook.substack.com/feed",
        "name": "The Human Playbook",
        "frequency_name": "weekly",
        "description": "Human skills in AI era.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://honestai.substack.com/feed",
        "name": "Honest AI",
        "frequency_name": "weekly",
        "description": "Honest takes on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://kaystoner.substack.com/feed",
        "name": "What Good Is AI?",
        "frequency_name": "weekly",
        "description": "Critical practical commentary on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://rafebrena.substack.com/feed",
        "name": "The Skeptic AI Enthusiast",
        "frequency_name": "weekly",
        "description": "Skeptical but interested AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://utopiainbeta.substack.com/feed",
        "name": "Utopia in Beta",
        "frequency_name": "weekly",
        "description": "AI and future concepts.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://engineeringharmony.substack.com/feed",
        "name": "Engineering Harmony",
        "frequency_name": "weekly",
        "description": "AI and engineering thinking.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aihumanity.substack.com/feed",
        "name": "AI for Humanity",
        "frequency_name": "weekly",
        "description": "AI for social good and society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://diamantinoalmeida.substack.com/feed",
        "name": "Leadership as a Verb",
        "frequency_name": "weekly",
        "description": "Leadership and AI transition.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://futurebraining.substack.com/feed",
        "name": "Futurebraining",
        "frequency_name": "weekly",
        "description": "Future-oriented AI commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://haridutt.substack.com/feed",
        "name": "The Turing Pilgrim",
        "frequency_name": "weekly",
        "description": "AI and broader reflection.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thepromptisthenovel.substack.com/feed",
        "name": "The Prompt Is the Novel",
        "frequency_name": "weekly",
        "description": "Prompting and generative writing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aicloudweekly.substack.com/feed",
        "name": "AI & Cloud Weekly",
        "frequency_name": "weekly",
        "description": "AI and cloud weekly roundup.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aigovernancelead.substack.com/feed",
        "name": "AI Governance Ethics and Leadership",
        "frequency_name": "weekly",
        "description": "Governance and leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://pascalbornet.substack.com/feed",
        "name": "IRREPLACEABLE with AI",
        "frequency_name": "weekly",
        "description": "Human + AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://solrashidi.substack.com/feed",
        "name": "The Sol of AI",
        "frequency_name": "weekly",
        "description": "Pragmatic AI for technologists and non-technologists.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://ruben.substack.com/feed",
        "name": "How to AI",
        "frequency_name": "weekly",
        "description": "Step-by-step AI workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://mitgenerationai.substack.com/feed",
        "name": "Generation AI",
        "frequency_name": "weekly",
        "description": "MIT Working Group on Generative AI and the future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiedusimplified.substack.com/feed",
        "name": "AI + Education = Simplified",
        "frequency_name": "weekly",
        "description": "AI and education for teachers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiandhowweteach.substack.com/feed",
        "name": "AI & How We Teach",
        "frequency_name": "weekly",
        "description": "AI-aware teaching and literacy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://wonderingaboutai.substack.com/feed",
        "name": "Wondering About AI",
        "frequency_name": "weekly",
        "description": "Leadership and AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://taoofai.substack.com/feed",
        "name": "Tao of AI",
        "frequency_name": "weekly",
        "description": "AI strategy and philosophy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://nextplayso.substack.com/feed",
        "name": "next play",
        "frequency_name": "weekly",
        "description": "Curated opportunities and deep tech content.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://metatrends.substack.com/feed",
        "name": "Metatrends",
        "frequency_name": "weekly",
        "description": "Future-facing technology trends.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://linas.substack.com/feed",
        "name": "Linas's Newsletter",
        "frequency_name": "weekly",
        "description": "Finance x AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thechipletter.substack.com/feed",
        "name": "The Chip Letter",
        "frequency_name": "weekly",
        "description": (
            "Computer history and architecture with semiconductor"
            " relevance."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://marklapedus.substack.com/feed",
        "name": "Semiecosystem",
        "frequency_name": "weekly",
        "description": "Semiconductor ecosystem commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://metacircuits.substack.com/feed",
        "name": "The Circuit",
        "frequency_name": "weekly",
        "description": "Helping business leaders become better AI operators.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theunchartedalgorithm.substack.com/feed",
        "name": "The Uncharted Algorithm",
        "frequency_name": "weekly",
        "description": "AI, enterprise, culture, future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://interestingengineering.substack.com/feed",
        "name": "Interesting Engineering++",
        "frequency_name": "weekly",
        "description": "Engineering/tech commentary with AI relevance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://dataintelligenceplatform.substack.com/feed",
        "name": "Data Intelligence Platform",
        "frequency_name": "weekly",
        "description": "Data platform and infrastructure recommendations.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cloudsecurityguy.substack.com/feed",
        "name": "The Cloud Security Guy",
        "frequency_name": "weekly",
        "description": "Cloud security with AI chip/infrastructure links.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://connectingai.substack.com/feed",
        "name": "ConnectingAI",
        "frequency_name": "weekly",
        "description": "Hardware enables the future of AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://anastasiintech.substack.com/feed",
        "name": "Deep in Tech Newsletter",
        "frequency_name": "weekly",
        "description": "AI data centers, optics, power systems.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://iamfabian.substack.com/feed",
        "name": "Fabian's Substack",
        "frequency_name": "weekly",
        "description": (
            "Product and technology deep dives in optics and AI infra."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://gadallon.substack.com/feed",
        "name": "Gadallon",
        "frequency_name": "weekly",
        "description": "AI infrastructure boom and supply chain.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://axautikgroupllc.substack.com/feed",
        "name": "Patrick Kennedy's Axautik Group",
        "frequency_name": "weekly",
        "description": "Server and hardware analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thefiddler.substack.com/feed",
        "name": "Fiddler on the Proof",
        "frequency_name": "weekly",
        "description": "Science/math with AI adjacency.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theneurotechnewsletter.substack.com/feed",
        "name": "The Neurotech Newsletter",
        "frequency_name": "weekly",
        "description": "Neurotechnology with AI relevance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://mariannanakos.substack.com/feed",
        "name": "A2S | Automate to Scale",
        "frequency_name": "weekly",
        "description": "Automation and AI integration for scaling.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://harrybloom.substack.com/feed",
        "name": "The Financial Philosopher",
        "frequency_name": "weekly",
        "description": "Financial philosophy with tech lenses.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://khanfk.substack.com/feed",
        "name": "Technicity",
        "frequency_name": "weekly",
        "description": "Technology, business and AI intersections.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://oneusefulthing.substack.com/feed",
        "name": "One Useful Thing",
        "frequency_name": "weekly",
        "description": "Ethan Mollick on practical AI applications and research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://understandingai.substack.com/feed",
        "name": "Understanding AI",
        "frequency_name": "weekly",
        "description": "Timothy Lee on AI research and policy analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://magazine.sebastianraschka.com/feed",
        "name": "Ahead of AI",
        "frequency_name": "weekly",
        "description": "Sebastian Raschka on ML research and engineering.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.safe.ai/feed",
        "name": "AI Safety Newsletter",
        "frequency_name": "weekly",
        "description": "Center for AI Safety - AI alignment and safety research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaiopportunities.com/feed",
        "name": "The AI Opportunity",
        "frequency_name": "weekly",
        "description": "AI business opportunities and market analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://brief.montrealethics.ai/feed",
        "name": "The AI Ethics Brief",
        "frequency_name": "weekly",
        "description": "Montreal AI Ethics Institute - AI ethics and governance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://blog.ai-futures.org/feed",
        "name": "AI Futures Project",
        "frequency_name": "weekly",
        "description": "Long-range AI futures and scenario planning.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://whytryai.com/feed",
        "name": "Why Try AI",
        "frequency_name": "weekly",
        "description": "Practical AI tool introductions and guides.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiadopters.club/feed",
        "name": "AI Adopters Club",
        "frequency_name": "weekly",
        "description": "AI adoption strategies for organisations.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aidisruption.ai/feed",
        "name": "AI Disruption",
        "frequency_name": "weekly",
        "description": "AI strategy and disruption for business leaders.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://workfutures.io/feed",
        "name": "workfutures.io",
        "frequency_name": "weekly",
        "description": "Future of work and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://connectedideasproject.com/feed",
        "name": "The Connected Ideas Project",
        "frequency_name": "weekly",
        "description": "Technology and AI ideas synthesis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://2ndorderthinkers.com/feed",
        "name": "2nd Order Thinkers",
        "frequency_name": "weekly",
        "description": "Second-order effects of AI on management and society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.forethought.org/feed",
        "name": "ForeWord",
        "frequency_name": "weekly",
        "description": "Forethought Institute - AI research and policy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://academy.shiftbase.info/feed",
        "name": "Shift*Academy",
        "frequency_name": "weekly",
        "description": "Organisational change and AI leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://phiand.ai/feed",
        "name": "Phi / AI",
        "frequency_name": "weekly",
        "description": "AI philosophy, ideas, and cultural commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://effthealgorithm.com/feed",
        "name": "Eff the Algorithm",
        "frequency_name": "weekly",
        "description": "Critical perspectives on algorithms and AI in society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://pseudorandombits.io/feed",
        "name": "Pseudorandom Bits",
        "frequency_name": "weekly",
        "description": "AI and computing commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.aipolicybulletin.org/feed",
        "name": "AI Policy Bulletin Newsletter",
        "frequency_name": "weekly",
        "description": "AI policy tracking and regulatory updates.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aitidbits.ai/feed",
        "name": "AI Tidbits",
        "frequency_name": "weekly",
        "description": "Curated AI news and tidbits.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://brennanmcdonald.com/feed",
        "name": "Brennan McDonald\'s Newsletter",
        "frequency_name": "weekly",
        "description": "AI and software engineering commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://humanandmachine.com/feed",
        "name": "Human and Machine",
        "frequency_name": "weekly",
        "description": "Humans and AI working together - practical perspectives.",
    },

    {
        "domain_slug": "ai_news",
        "url": "https://readings.ramisayar.com/feed",
        "name": "Rami\'s Readings",
        "frequency_name": "weekly",
        "description": "Curated AI and technology readings.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://writing.antonleicht.me/feed",
        "name": "Threading the Needle",
        "frequency_name": "weekly",
        "description": "AI and engineering.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiweekender.substack.com/feed",
        "name": "AI Weekender",
        "frequency_name": "weekly",
        "description": "Weekly AI news digest.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://tylerfolkman.substack.com/feed",
        "name": "The AI Architect",
        "frequency_name": "weekly",
        "description": "AI architecture and coding tools.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://airabbithole.substack.com/feed",
        "name": "The AI Rabbit Hole",
        "frequency_name": "weekly",
        "description": "Deep dives into AI topics and experiments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://shmulc.substack.com/feed",
        "name": "AI Superhero",
        "frequency_name": "weekly",
        "description": "AI tools and productivity tips.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://the-ai-corner.com/feed",
        "name": "The AI Corner",
        "frequency_name": "weekly",
        "description": "AI tools, workflows, and use cases.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://creatoreconomy.so/feed",
        "name": "Behind the Craft",
        "frequency_name": "weekly",
        "description": "AI tools for creators and the creator economy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thevccorner.com/feed",
        "name": "The VC Corner",
        "frequency_name": "weekly",
        "description": "Venture capital and AI startup landscape.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cfooffice.io/feed",
        "name": "AI CFO Office",
        "frequency_name": "weekly",
        "description": "AI in finance and CFO office automation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.mkt1.co/feed",
        "name": "MKT1 Newsletter",
        "frequency_name": "weekly",
        "description": "AI in startup marketing and growth.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://sebastianbarros.substack.com/feed",
        "name": "Sebastian Barros Newsletter",
        "frequency_name": "weekly",
        "description": "Cloud, AI, and connectivity trends.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.globaldatacenterhub.com/feed",
        "name": "Global Data Center Hub",
        "frequency_name": "weekly",
        "description": "Data centre infrastructure and AI compute.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://datacenterfervor.substack.com/feed",
        "name": "Data Center Fervor",
        "frequency_name": "weekly",
        "description": "Data centre industry news and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://dirttodata.substack.com/feed",
        "name": "Dirt to Data",
        "frequency_name": "weekly",
        "description": "Data centre development, land, and power strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://sharongoldman.substack.com/feed",
        "name": "AI Side Notes with Sharon Goldman",
        "frequency_name": "weekly",
        "description": "Fortune reporter on AI industry notes and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://techsoda.substack.com/feed",
        "name": "TechSoda",
        "frequency_name": "weekly",
        "description": "Semiconductors, optical, and AI infrastructure.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.technostatecraft.com/feed",
        "name": "Techno-Statecraft",
        "frequency_name": "weekly",
        "description": "Technology and statecraft - geopolitics of AI and semis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://semifundamental.substack.com/feed",
        "name": "Semi Fundamental",
        "frequency_name": "weekly",
        "description": "AI and semiconductor supply chain fundamentals.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://chipinsights.net/feed",
        "name": "Chip Insights",
        "frequency_name": "weekly",
        "description": "Semiconductor industry insights and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.22ndcenturyfrontier.com/feed",
        "name": "22nd Century Frontier",
        "frequency_name": "weekly",
        "description": "Frontier technology and deep tech investing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.augmentedswe.com/feed",
        "name": "The AI-Augmented Engineer",
        "frequency_name": "weekly",
        "description": "AI tools for software engineers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://businessengineer.ai/feed",
        "name": "The Business Engineer",
        "frequency_name": "weekly",
        "description": "Business strategy and engineering with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://scsp222.substack.com/feed",
        "name": "Special Competitive Studies Project",
        "frequency_name": "weekly",
        "description": "US technology competitiveness and AI strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://tarotcapital.substack.com/feed",
        "name": "Tarot Capital",
        "frequency_name": "weekly",
        "description": "Incentive-driven technology investing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://arushisharmafrank.substack.com/feed",
        "name": "Teach What I Know",
        "frequency_name": "weekly",
        "description": "Energy markets, grid policy, and AI infrastructure power.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cozora.substack.com/feed",
        "name": "Cozora",
        "frequency_name": "weekly",
        "description": "AI creator tools and workshops.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thoughtforms.substack.com/feed",
        "name": "Thoughtforms",
        "frequency_name": "weekly",
        "description": "Technology, business, design, and culture futures.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theslowai.substack.com/feed",
        "name": "Slow AI",
        "frequency_name": "weekly",
        "description": "Critical AI literacy and thoughtful AI engagement.",
    },

    {
        "domain_slug": "ai_news",
        "url": "https://mackcollier.substack.com/feed",
        "name": "Backstage Pass",
        "frequency_name": "weekly",
        "description": "AI in social media and community strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thehumanco.substack.com/feed",
        "name": "The Human Stack",
        "frequency_name": "weekly",
        "description": "AI, future of work, and HR/L&D leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://fafi25.substack.com/feed",
        "name": "Lights On",
        "frequency_name": "weekly",
        "description": "AI business and productivity.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiinuse.substack.com/feed",
        "name": "Operating",
        "frequency_name": "weekly",
        "description": "AI in operational business contexts.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://3foldoutcomes.substack.com/feed",
        "name": "3Fold Outcomes",
        "frequency_name": "weekly",
        "description": "M&A, organisational design, and AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://vickyho.substack.com/feed",
        "name": "VK 科技閱讀時間",
        "frequency_name": "weekly",
        "description": "Chinese-language technology and AI reading curation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://purposefulai.substack.com/feed",
        "name": "Purposeful AI",
        "frequency_name": "weekly",
        "description": "AI in higher education and nonprofits.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiinfrastructure.substack.com/feed",
        "name": "AI Infrastructure Digest",
        "frequency_name": "weekly",
        "description": "AI infrastructure news and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://inferenceatscale.substack.com/feed",
        "name": "Inference at Scale",
        "frequency_name": "weekly",
        "description": "AI inference infrastructure and deployment.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://llmengineer.substack.com/feed",
        "name": "LLM Engineer Weekly",
        "frequency_name": "weekly",
        "description": "LLM engineering tools and techniques.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.promptengineering.org/feed",
        "name": "Prompt Engineering Daily",
        "frequency_name": "weekly",
        "description": "Prompt engineering techniques and research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "name": "CNBC Finance",
        "frequency_name": "daily",
        "description": "CNBC finance and markets coverage, including AI-stock moves and market corrections.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.ft.com/markets?format=rss",
        "name": "FT Markets",
        "frequency_name": "daily",
        "description": "Financial Times markets coverage, including AI-stock moves and market corrections.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://feeds.npr.org/1006/rss.xml",
        "name": "NPR Business",
        "frequency_name": "daily",
        "description": "NPR business coverage, including AI-stock moves and market corrections.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.economist.com/finance-and-economics/rss.xml",
        "name": "The Economist Finance",
        "frequency_name": "daily",
        "description": "The Economist finance and economics coverage, including AI-market analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "name": "Bloomberg Markets",
        "frequency_name": "daily",
        "description": "Bloomberg markets coverage, including AI-stock moves and market corrections.",
    },
]

# Company-specific news via Alpha Vantage News & Sentiments API.
# Tickers are sourced from the AI economy universe.
# Fetcher (source_type: "alpha_vantage") implemented in pipeline.py.
COMPANY_NEWS_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "company_news",
        "url": "alpha_vantage:company_news",
        "name": "Alpha Vantage Company News",
        "source_type": "alpha_vantage",
        "frequency_name": "daily",
        "description": (
            "Company-specific news and sentiment for AI economy universe"
            " entities, fetched by ticker symbol via Alpha Vantage."
        ),
        # Tickers are now managed via get_tracked_ticker_universe() in pipeline.py,
        # fetched live from research-universe. This config is kept empty — the
        # source row is required for domain registration.
        "config": {},
    },
]

# Federal Register documents (sanctions, export controls, tariffs, executive
# orders) — free public REST API, no key required.
# Fetcher (source_type: "federal_register") implemented in pipeline.py.
FEDERAL_REGISTER_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "geopolitical_news",
        "url": "federal_register:geopolitical",
        "name": "Federal Register",
        "source_type": "federal_register",
        "frequency_name": "daily",
        "description": (
            "U.S. Federal Register documents: sanctions actions,"
            " export controls, tariffs, executive orders, and"
            " presidential documents."
        ),
        "config": {
            "agencies": [
                "treasury-department",
                "foreign-assets-control-office",
                "industry-and-security-bureau",
                "trade-representative-office-of-united-states",
                "executive-office-of-the-president",
            ],
            "type": ["PRESDOCU", "RULE", "PRORULE", "NOTICE"],
        },
    },
]

# TWSE / TPEx OpenData monthly revenue (t187ap05_L / mopsfin_t187ap05_O).
# Both are full-dump, keyless JSON endpoints with no ticker query param -
# the fetcher pulls the whole dataset and filters to TAIWAN_TICKER_UNIVERSE.
# Fetchers (source_type: "twse_revenue" / "tpex_revenue") in pipeline.py.
TAIWAN_REVENUE_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "taiwan_market_signal",
        "url": "twse_revenue:monthly",
        "name": "TWSE Monthly Revenue",
        "source_type": "twse_revenue",
        "frequency_name": "daily",
        "description": (
            "TWSE OpenAPI monthly revenue (t187ap05_L) for TWSE-listed"
            " tickers in the Taiwan universe, with MoM/YoY deltas."
        ),
        "config": {
            "tickers": [
                t["ticker"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TWSE"
            ],
            # Known-correct English company names, keyed by ticker - used
            # by the fetcher to set metadata.translated_company_name
            # directly, rather than asking an LLM to translate the raw
            # Chinese name (confirmed live: this produced serious errors,
            # e.g. 2383 Elite Material mistranslated as "Taiwan
            # Semiconductor Manufacturing Company", 8210 Chenbro translated
            # literally as "Diligence and sincerity"). We already have the
            # ground truth here; no reason to let a model guess it.
            "ticker_names": {
                t["ticker"]: t["company"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TWSE"
            },
        },
    },
    {
        "domain_slug": "taiwan_market_signal",
        "url": "tpex_revenue:monthly",
        "name": "TPEx Monthly Revenue",
        "source_type": "tpex_revenue",
        "frequency_name": "daily",
        "description": (
            "TPEx OpenAPI monthly revenue (mopsfin_t187ap05_O) for"
            " TPEx/OTC-listed tickers in the Taiwan universe, with"
            " MoM/YoY deltas."
        ),
        "config": {
            "tickers": [
                t["ticker"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TPEx"
            ],
            "ticker_names": {
                t["ticker"]: t["company"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TPEx"
            },
        },
    },
]

# TWSE / TPEx OpenData material announcements (t187ap04_L / mopsfin_t187ap04_O).
# Same full-dump-then-filter shape as revenue above. TPEx's feed uses a
# different keyset (Date/SecuritiesCompanyCode/CompanyName vs TWSE's
# 出表日期/公司代號/公司名稱) - normalized to a common shape in the fetcher.
# Fetchers (source_type: "twse_material" / "tpex_material") in pipeline.py.
TAIWAN_MATERIAL_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "taiwan_market_signal",
        "url": "twse_material:announcements",
        "name": "TWSE Material Announcements",
        "source_type": "twse_material",
        "frequency_name": "daily",
        "description": (
            "TWSE OpenAPI material announcements (t187ap04_L, 重大訊息)"
            " for TWSE-listed tickers in the Taiwan universe."
        ),
        "config": {
            "tickers": [
                t["ticker"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TWSE"
            ],
            "ticker_names": {
                t["ticker"]: t["company"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TWSE"
            },
        },
    },
    {
        "domain_slug": "taiwan_market_signal",
        "url": "tpex_material:announcements",
        "name": "TPEx Material Announcements",
        "source_type": "tpex_material",
        "frequency_name": "daily",
        "description": (
            "TPEx OpenAPI material announcements (mopsfin_t187ap04_O)"
            " for TPEx/OTC-listed tickers in the Taiwan universe."
        ),
        "config": {
            "tickers": [
                t["ticker"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TPEx"
            ],
            "ticker_names": {
                t["ticker"]: t["company"] for t in TAIWAN_TICKER_UNIVERSE
                if t["exchange"] == "TPEx"
            },
        },
    },
]

# GDELT DOC 2.0 API scoped to Taiwan-language press for the Taiwan universe,
# reusing the existing gdelt fetcher (source_type: "gdelt", implemented in
# pipeline.py — same _fetch_gdelt/_fetch_one_gdelt code path already used by
# geopolitical_news, just with different queries).
#
# Verified live that "<name> sourcelang:chinese sourcecountry:TW" returns
# genuine Taiwan financial press (SETN, DigiTimes) with real signal (revenue
# prints, order news), NOT pre-translated to English (GDELT's "language"
# field on these results is "Chinese" and titles are in Chinese — contrary
# to the original spec's claim of "already translated"; a translation step
# is required downstream, not optional).
#
# GDELT rejects any query keyword of 2 CJK characters or fewer with a
# distinct ("keyword too short") response — confirmed live, HTTP 200 with a
# non-JSON plain-text body, which is NOT the same failure as a 429 and is
# not currently retried/handled specially by the fetcher (it would parse-
# error and log a generic warning every poll). 11 of the 20 tickers have
# exactly 2-character native names (鴻海, 廣達, 緯創, 緯穎, 奇鋐, 雙鴻, 嘉澤,
# 川湖, 勤誠, 欣興, 信驊). Two attempts to pad these to 3+ characters with a
# generic suffix were tested live and BOTH failed to surface results even
# for Hon Hai (2317), a company confirmed to have heavy Chinese-language
# coverage: "鴻海集團" (+Group) and "鴻海精密" (+Precision, its own formal
# name) both returned a clean empty response, not an error — meaning
# suffix-padding is unreliable per-company and would silently look
# identical to "no news" if shipped. Bare ticker-code queries were also
# tested and ruled out the same way (2330/TSMC returned empty despite
# known heavy coverage).
#
# Given no verified-working padding scheme, native-name querying is
# dropped for these 11 tickers; only the English-name query is used for
# them (already confirmed working and ≥3 chars for all 20 companies). The
# other 9 tickers with 3+ character native names keep both queries.
_GDELT_MIN_QUERY_CHARS = 3

TAIWAN_GDELT_SOURCE: dict[str, Any] = {
    "domain_slug": "taiwan_market_signal",
    "url": "gdelt:taiwan_market_signal",
    "name": "GDELT DOC API (Taiwan)",
    "source_type": "gdelt",
    "frequency_name": "daily",
    "description": (
        "Taiwan-language financial press coverage via GDELT DOC 2.0,"
        " scoped to sourcelang:chinese sourcecountry:TW, queried per"
        " ticker by native Chinese name (when >=3 characters) and"
        " English name."
    ),
    "config": {
        "queries": [
            q
            for t in TAIWAN_TICKER_UNIVERSE
            for q in (
                [f"{t['native_name']} sourcelang:chinese sourcecountry:TW"]
                if len(t["native_name"]) >= _GDELT_MIN_QUERY_CHARS
                else []
            ) + [f"{t['company']} sourcelang:chinese sourcecountry:TW"]
        ],
        # Maps each query string back to its ticker, since GDELT queries by
        # company name (there is no ticker query param) and the fetcher
        # otherwise has no way to know which company a result belongs to.
        # Used for the title-similarity dedup, which is scoped per-ticker.
        "query_ticker": {
            q: t["ticker"]
            for t in TAIWAN_TICKER_UNIVERSE
            for q in (
                ([f"{t['native_name']} sourcelang:chinese sourcecountry:TW"]
                 if len(t["native_name"]) >= _GDELT_MIN_QUERY_CHARS else [])
                + [f"{t['company']} sourcelang:chinese sourcecountry:TW"]
            )
        },
        # Maps each query string to the ticker's English name, regardless of
        # whether the query itself used the native or English name - lets
        # the company-name-in-title filter accept an English-language
        # headline even for a native-name query (confirmed live: GDELT's
        # sourcelang:chinese scope still returns some English-language
        # articles, e.g. Taipei Times/Focus Taiwan syndication, which were
        # being dropped even though they genuinely name the company).
        "query_english_name": {
            q: t["company"]
            for t in TAIWAN_TICKER_UNIVERSE
            for q in (
                ([f"{t['native_name']} sourcelang:chinese sourcecountry:TW"]
                 if len(t["native_name"]) >= _GDELT_MIN_QUERY_CHARS else [])
                + [f"{t['company']} sourcelang:chinese sourcecountry:TW"]
            )
        },
    },
}

# DART (Financial Supervisory Service) filing list + document body fetch,
# scoped to the 19 listed companies in KOREA_TICKER_UNIVERSE (Hanwha
# Semitech is excluded - confirmed unlisted, no stock_code, no DART
# corp_code exists for it under either its current or former name).
# Fetcher (source_type: "dart_filing") implemented in pipeline.py.
#
# Covers Korea Signals spec Section 4 S2 (supply contract), S3 (capacity
# commitment), S4 (preliminary earnings), S5 (guidance disclosure), and S6
# (rumour adjudication - confirmed live 2026-09-22 that DART carries both
# the exchange's demand and the company's answer as distinct filings; see
# the _DART_TARGET_REPORT_PATTERNS comment in pipeline.py for the precision
# caveat on "hours between the two"). Does NOT cover S1 (Korea Customs,
# separate source).
KOREA_DART_SOURCE: dict[str, Any] = {
    "domain_slug": "korea_market_signal",
    "url": "dart_filing:korea_market_signal",
    "name": "DART Filings (Korea)",
    "source_type": "dart_filing",
    "frequency_name": "daily",
    "description": (
        "Exchange-mandated disclosures (supply contracts, capacity"
        " investment, preliminary earnings, guidance, rumour adjudication)"
        " for Korea AI-supply-chain companies, via DART's list.json +"
        " document.xml, filtered to report_nm patterns matching those"
        " signal types."
    ),
    "config": {
        "companies": [
            {"ticker": t["ticker"], "company": t["company"]}
            for t in KOREA_TICKER_UNIVERSE
            if t["ticker"] is not None
        ],
    },
}

# KOREA_CUSTOMS_SOURCE_STATUS: covers Korea Signals spec Section 4 S1
# (export surprise), the doc's headline signal.
#
# THE ORIGINAL BLOCKER (still true, kept for context): the clean
# structured REST API for this data is data.go.kr, dataset 15157908
# ("관세청_수출 주요품목별 10일 단위 잠정치 통계") - endpoint, params
# (serviceKey/strtYymm/endYymm), and response fields confirmed live
# 2026-09-22. Getting a serviceKey requires a personal data.go.kr account,
# and that signup's "정보입력" step has a REQUIRED 휴대전화번호 (mobile
# phone) field wired to Korea's national identity-verification system
# (NICE/KCB) - it validates the phone's carrier subscription is tied to a
# real Korean identity credential (for a foreigner, an Alien Registration
# Card). No foreigner-specific signup track exists. A non-resident
# without an ARC-linked Korean phone number cannot complete this signup.
# KOSIS is residency-gated the same way; KITA gates the same data behind
# paid Korean corporate trade-registration membership (harder, not
# easier); tradedata.go.kr's own API layer routes back through the same
# data.go.kr account system.
#
# RESOLVED 2026-09-23 via a 4th option not in the original list: Korea
# Customs Service's own public press-release board
# (customs.go.kr/kcs/na/ntt/..., bbsId=1362, mi=2891) publishes the same
# underlying figure with NO login required at all - confirmed live. This
# is what KOREA_CUSTOMS_EXPORT_SOURCE below scrapes (fetcher:
# source_type "kr_customs_export" in pipeline.py).
#
# Confirmed live 2026-09-23: this board has no RSS feed, and post IDs
# (nttSn) are a global auto-increment across ~6,600+ unrelated posts, not
# usable as a date pattern - the fetcher instead uses the board's own
# title-search (a POST, not GET query params - a GET-param guess 404'd)
# to isolate the recurring "수출입 현황" report family and take the
# newest match.
#
# What the source actually gives us, confirmed live against real 10-day
# and 20-day releases: a dollar figure plus a superlative record/streak
# claim (e.g. "반도체(341억 달러) 수출 동기간 역대최대" - semiconductor
# exports of $34.1bn, a period record) - NOT a year-over-year percentage
# and NOT a share-of-total-exports percentage (checked every mention of
# "반도체" on a real page and searched for "차지"/share-of, found neither
# at 10-day/20-day granularity; a %-growth figure does appear on the
# separate monthly "확정치"/confirmed release, ~15th-18th of the
# following month, a 4th release type this board also carries).
#
# This means Section 5.1's "change against the same period one year
# earlier" and "spread over the last 12 equivalent periods" cannot come
# from the source's own text at 10-day granularity - this pipeline must
# compute both itself from its own stored history of these dollar
# figures, exactly matching the doc's own build note that "this rule
# needs two years of stored history before it means anything." That
# history is not backfilled, and S1 is now PERMANENTLY OUT OF SCOPE
# (decided 2026-09-23) rather than pending - Bank of Korea ECOS was the
# agreed backfill source, but its real signup flow was confirmed live to
# require the same Korean mobile-carrier identity verification (PASS,
# run by NICE) that already blocked data.go.kr - the earlier research
# calling ECOS "no Korean phone required" was wrong. No Korean contact is
# available to register on our behalf, and a paid vendor route (e.g.
# CEIC) was considered and explicitly not pursued. classify_export_
# surprise() is not implemented anywhere in signal-detection-agent as a
# result - see that service's korea_signal_classifier.py module docstring
# for the full record. This source (KOREA_CUSTOMS_EXPORT_SOURCE) stays
# seeded regardless - it still fetches the newest release's raw figure
# for the record and for the cross-check note below, even with no
# classifier ever consuming it for S1's own arithmetic rule.
#
# Also agreed but not yet built: cross-checking this scrape against
# same-day Korean wire coverage (Yonhap/Hankyung/ETNews all report this
# figure within minutes of release) as a disagreement detector - if the
# scraped number and the wire coverage disagree, that is a signal the
# parser broke, not a signal to silently publish. This would reuse the
# Korean news layer already being built for S7, not a new source type.
KOREA_CUSTOMS_EXPORT_SOURCE: dict[str, Any] = {
    "domain_slug": "korea_market_signal",
    "url": "kr_customs_export:korea_market_signal",
    "name": "Korea Customs Export Press Release",
    "source_type": "kr_customs_export",
    "frequency_name": "daily",
    "description": (
        "Semiconductor export figures scraped from Korea Customs"
        " Service's public press-release board (no login required) -"
        " fallback for the data.go.kr structured API, which is blocked"
        " behind Korean-phone-verified account signup. Publishes the"
        " newest 10-day/20-day/monthly release's dollar figure; YoY% is"
        " computed downstream from this pipeline's own stored history,"
        " not read from the source."
    ),
}

# Korean-language trade/business press RSS feeds - plain rss source_type
# (no config needed beyond the feed url itself), same as SUBSTACK_SOURCES.
# Covers Korea Signals spec Section 4 S7 (qualification news), upstream of
# the three-filter + LLM classification pipeline that lives in
# signal-detection-agent (see that service's CLAUDE.md) - this service's
# job is fetch/dedup only.
#
# Only THE ELEC (below) has a dedicated semiconductor/materials-equipment
# section feed - ZDNet Korea, BusinessPost, and DigitalDaily do not;
# semiconductor coverage appears as one recurring topic within their
# general business/industry feeds, not an isolated stream. This is a known
# tradeoff, not an oversight - broader feeds mean more volume for
# signal-detection-agent's classification filters to work through.
# (ETNews was also tried and dropped - see the comment further down where
# it used to sit, kept as a record of why.)
KOREA_RSS_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "korea_market_signal",
        "url": "https://www.thelec.kr/rss/S1N2.xml",
        "name": "THE ELEC - Semiconductors",
        "frequency_name": "daily",
        "description": (
            "디일렉 (THE ELEC), Korean specialist electronics-component"
            " trade press - semiconductors section. Closest Korean"
            " equivalent to DIGITIMES; founded specifically to cover"
            " Korea's component/equipment industry, which general/economic"
            " media under-covers."
        ),
    },
    {
        "domain_slug": "korea_market_signal",
        "url": "https://www.thelec.kr/rss/S1N3.xml",
        "name": "THE ELEC - Materials & Equipment",
        "frequency_name": "daily",
        "description": (
            "디일렉 (THE ELEC) materials & equipment section - directly"
            " relevant to the Tier 2 memory-stacking-chain companies in"
            " KOREA_TICKER_UNIVERSE."
        ),
    },
    # ETNews (전자신문) was tried and DROPPED - both candidate section feeds
    # (06061/장비/equipment, 06062/부품/components; ETNews has no dedicated
    # semiconductor section at all, confirmed against the site's own RSS
    # hub taxonomy) worked cleanly when first live-tested 2026-09-22, but a
    # second check hours later returned the EXACT SAME 50 entries, same
    # timestamps, all dated 2026-06-25 - a ~3-month-old snapshot, not a
    # live feed. Confirmed stuck, not a transient delay: two independent
    # fetches produced identical stale output rather than any forward
    # movement. Decision 2026-09-23: drop rather than keep flagged, since a
    # frozen "daily" source would silently stop contributing without any
    # error to notice - not worth the false confidence of a source entry
    # that looks live in seed.py but isn't. Revisit by re-testing
    # http://rss.etnews.com/06061.xml directly if ETNews coverage is
    # wanted again later.
    {
        "domain_slug": "korea_market_signal",
        "url": "https://feeds.feedburner.com/zdkorea",
        "name": "ZDNet Korea",
        "frequency_name": "daily",
        "description": (
            "지디넷코리아 (ZDNet Korea), general Korean tech/IT news -"
            " broader audience than THE ELEC, general feed (no"
            " dedicated semiconductor section)."
        ),
    },
    {
        "domain_slug": "korea_market_signal",
        "url": "https://www.businesspost.co.kr/rss/Article_3.xml",
        "name": "BusinessPost - Corporate & Industry",
        "frequency_name": "daily",
        "description": (
            "비즈니스포스트 (BusinessPost), Korean business news -"
            " Corporate & Industry (기업과산업) section, general feed"
            " with tech/industry crossover (no dedicated semiconductor"
            " section)."
        ),
    },
    {
        "domain_slug": "korea_market_signal",
        "url": "https://www.ddaily.co.kr/rss.xml",
        "name": "DigitalDaily",
        "frequency_name": "daily",
        "description": (
            "디지털데일리 (DigitalDaily), Korean IT/tech trade press -"
            " general feed (no dedicated semiconductor section)."
        ),
    },
    # Yonhap's only confirmed-working feed (en.yna.co.kr/RSS/news.xml) is
    # its general English-language wire, not a business/economy section -
    # no section-specific feed URL exists (checked economy.xml,
    # business.xml, industry.xml, markets.xml, all 404; no category field
    # or URL-encoded section code found on individual entries either, so
    # there's no structured field to filter on). Live-tested 2026-09-23: a
    # title-keyword regex against a real 102-entry sample matched 15
    # (16%) with zero false positives - correctly excluded all Asian
    # Games/politics/court content while catching every genuinely
    # business/economy-relevant headline (Seoul stocks, BOK, growth
    # forecast, consumer sentiment, Naver labor action, etc.). Applied via
    # config.title_filter (see _parse_feed in pipeline.py) rather than
    # dropping the source outright the way ETNews was, since the content
    # that DOES pass is real, fresh (today's timestamps), and on-target -
    # unlike ETNews, this isn't a dead/stale source, just an unfiltered
    # one without this regex.
    {
        "domain_slug": "korea_market_signal",
        "url": "https://en.yna.co.kr/RSS/news.xml",
        "name": "Yonhap News (business/economy filtered)",
        "frequency_name": "daily",
        "description": (
            "연합뉴스 (Yonhap News Agency), English-language wire -"
            " general/mixed feed (no business-specific section feed"
            " exists), filtered post-fetch to business/economy/markets"
            " headlines via config.title_filter since there is no"
            " structured category field to filter on instead."
        ),
        "config": {
            "title_filter": (
                r"\b(stocks?|won\b|\bBOK\b|econom|GDP|growth forecast|"
                r"chip(s|maker)?|semiconductor|exports?|imports?|"
                r"trade (deficit|surplus|balance|talks|war)|"
                r"market (woes|slowdown|data)|inflation|"
                r"consumer (sentiment|price)|investment|manufactur|"
                r"Samsung|SK Hynix|\bLG\b|Hyundai|Naver|Kakao|earnings|"
                r"profit|revenue|billion|trillion|fiscal|monetary policy|"
                r"\bADB\b|\bIMF\b|insurance|loan|delinquency|debt|"
                r"power plant|acquisition|stake\b|\bFTC\b|antitrust|"
                r"banknotes)"
            ),
        },
    },
]

# GDELT DOC 2.0 API scoped to Korean-language press for the Korea universe,
# reusing the existing gdelt fetcher (source_type: "gdelt", same
# _fetch_gdelt/_fetch_one_gdelt code path as geopolitical_news and
# TAIWAN_GDELT_SOURCE) - just different queries.
#
# Confirmed live 2026-09-22: "sourcelang:korean sourcecountry:KS" (KS, not
# KR - GDELT's sourcecountry operator uses FIPS 10-4 codes, not ISO 3166;
# KR is not a valid FIPS code) returns genuine Korean-language, Korea-
# domiciled results including real trade press (etnews.com).
#
# Short-native-name rejection (same GDELT quirk documented in
# TAIWAN_GDELT_SOURCE above, for CJK-script queries under ~3 characters)
# was NOT independently re-confirmed for Korean/Hangul specifically - live
# testing was blocked by GDELT's own rate limit (429, "limit requests to
# one every 5 seconds") persisting well past that stated window across
# multiple spaced-out retries on 2026-09-22, so this could not be verified
# before this was written. Applying the same defensive threshold Taiwan
# already uses is low-cost even if unnecessary here (worst case: one extra,
# redundant English-name query for the one affected company), so it is
# applied rather than assumed unneeded. Of the 19 listed companies, only
# Simmtech's Korean name (심텍, 2 characters) falls under the threshold -
# a much smaller exposure than Taiwan's 11/20, since almost all Korean
# company names in this universe are naturally 3+ characters.
_KOREA_GDELT_MIN_QUERY_CHARS = 3

KOREA_GDELT_SOURCE: dict[str, Any] = {
    "domain_slug": "korea_market_signal",
    "url": "gdelt:korea_market_signal",
    "name": "GDELT DOC API (Korea)",
    "source_type": "gdelt",
    "frequency_name": "daily",
    "description": (
        "Korean-language press coverage via GDELT DOC 2.0, scoped to"
        " sourcelang:korean sourcecountry:KS, queried per company by"
        " Korean name (when >=3 characters) and English name."
    ),
    "config": {
        "queries": [
            q
            for t in KOREA_TICKER_UNIVERSE
            for q in (
                [f"{t['korean_name']} sourcelang:korean sourcecountry:KS"]
                if len(t["korean_name"]) >= _KOREA_GDELT_MIN_QUERY_CHARS
                else []
            ) + [f"{t['company']} sourcelang:korean sourcecountry:KS"]
        ],
        # Maps each query string back to its ticker (or, for the one
        # unlisted company, its name) - GDELT queries by company name, not
        # ticker, so the fetcher otherwise has no way to attribute a result.
        # Used for the title-similarity dedup, scoped per-company.
        "query_ticker": {
            q: (t["ticker"] or t["company"])
            for t in KOREA_TICKER_UNIVERSE
            for q in (
                ([f"{t['korean_name']} sourcelang:korean sourcecountry:KS"]
                 if len(t["korean_name"]) >= _KOREA_GDELT_MIN_QUERY_CHARS else [])
                + [f"{t['company']} sourcelang:korean sourcecountry:KS"]
            )
        },
        "query_english_name": {
            q: t["company"]
            for t in KOREA_TICKER_UNIVERSE
            for q in (
                ([f"{t['korean_name']} sourcelang:korean sourcecountry:KS"]
                 if len(t["korean_name"]) >= _KOREA_GDELT_MIN_QUERY_CHARS else [])
                + [f"{t['company']} sourcelang:korean sourcecountry:KS"]
            )
        },
    },
}

# GDELT DOC 2.0 API scoped to ENGLISH-language coverage of the same Korea
# universe, for the English-coverage check (Korea Signals spec Section 7
# Step 5: "run the same search in English and record whether anything was
# found, and when"; displayed per-item in Section 6.4 as "English press:
# None found at time of retrieval"). This service's job is only to fetch
# and store this data - the actual comparison (does an English article
# exist, and if so was it published before/after the Korean one) is
# signal-detection-agent's job, computed from these rows plus
# KOREA_GDELT_SOURCE's rows, not done here.
#
# Deliberately does NOT share ticker keys with KOREA_GDELT_SOURCE's
# query_ticker, even though both ultimately concern the same companies -
# _fetch_gdelt's title-similarity dedup (pipeline.py) is scoped per ticker
# key across ALL merged GDELT sources in one run, and a same-ticker-key
# collision here would let the dedup logic silently drop a genuine English
# article as a "near-duplicate" of the Korean one, defeating the entire
# point of fetching both. Ticker keys are suffixed "-en" so the two
# languages' articles are dedup-scoped separately while both still get
# stored, with metadata.ticker letting a downstream reader join them back
# to the same company by stripping the suffix.
KOREA_GDELT_ENGLISH_SOURCE: dict[str, Any] = {
    "domain_slug": "korea_market_signal",
    "url": "gdelt:korea_market_signal_english",
    "name": "GDELT DOC API (Korea - English coverage check)",
    "source_type": "gdelt",
    "frequency_name": "daily",
    "description": (
        "English-language press coverage of the same Korea AI-supply-chain"
        " companies via GDELT DOC 2.0, scoped to sourcelang:english."
        " Exists solely to test whether/when English coverage of a fact"
        " exists, for comparison against the Korean-language sources -"
        " not a primary signal source itself."
    ),
    "config": {
        "queries": [
            f"{t['company']} sourcelang:english"
            for t in KOREA_TICKER_UNIVERSE
        ],
        "query_ticker": {
            f"{t['company']} sourcelang:english": f"{t['ticker'] or t['company']}-en"
            for t in KOREA_TICKER_UNIVERSE
        },
        "query_english_name": {
            f"{t['company']} sourcelang:english": t["company"]
            for t in KOREA_TICKER_UNIVERSE
        },
    },
}

# GDELT DOC 2.0 API, queried once per individual theme code (not OR-joined -
# only single bare "theme:X" queries are confirmed working against the live
# API; multi-theme "(theme:X OR theme:Y)" queries could not be verified and
# are avoided until confirmed). English-only. No API key required.
# Fetcher (source_type: "gdelt") implemented in pipeline.py.
GDELT_SOURCE: dict[str, Any] = {
    "domain_slug": "geopolitical_news",
    "url": "gdelt:geopolitical",
    "name": "GDELT DOC API",
    "source_type": "gdelt",
    "frequency_name": "daily",
    "description": (
        "Global conflict, terrorism, sanctions, and unrest coverage via"
        " the GDELT Project's DOC 2.0 API, English-language, US-sourced"
        " outlets only (sourcecountry:US - used as a proxy for events"
        " involving or affecting the US), queried per individual theme code."
    ),
    "config": {
        "queries": [
            "theme:ARMEDCONFLICT sourcelang:english sourcecountry:US",
            "theme:MILITARY sourcelang:english sourcecountry:US",
            "theme:CEASEFIRE sourcelang:english sourcecountry:US",
            "theme:TERROR sourcelang:english sourcecountry:US",
            "theme:WB_2467_TERRORISM sourcelang:english sourcecountry:US",
            "theme:REBELLION sourcelang:english sourcecountry:US",
            "theme:REBELS sourcelang:english sourcecountry:US",
            "theme:INSURGENCY sourcelang:english sourcecountry:US",
            "theme:SEPARATISTS sourcelang:english sourcecountry:US",
            "theme:SANCTIONS sourcelang:english sourcecountry:US",
            "theme:BLOCKADE sourcelang:english sourcecountry:US",
            "theme:PROTEST sourcelang:english sourcecountry:US",
            "theme:VIOLENT_UNREST sourcelang:english sourcecountry:US",
            "theme:KILL sourcelang:english sourcecountry:US",
            "theme:ASSASSINATION sourcelang:english sourcecountry:US",
            "theme:HUMAN_RIGHTS_ABUSES sourcelang:english sourcecountry:US",
            "theme:WB_2509_GENOCIDE sourcelang:english sourcecountry:US",
            "theme:WB_2510_WAR_CRIMES sourcelang:english sourcecountry:US",
            "theme:DISPLACED sourcelang:english sourcecountry:US",
            "theme:REFUGEES sourcelang:english sourcecountry:US",
            "theme:PEACEKEEPING sourcelang:english sourcecountry:US",
            "theme:RELEASE_HOSTAGE sourcelang:english sourcecountry:US",
            "theme:WB_2503_WEAPONS_PROLIFERATION_AND_ARMS_CONTROL sourcelang:english sourcecountry:US",
            "theme:WB_2505_WEAPONS_OF_MASS_DESTRUCTION sourcelang:english sourcecountry:US",
            "theme:CYBER_ATTACK sourcelang:english sourcecountry:US",
            "theme:BORDER sourcelang:english sourcecountry:US",
            "theme:MILITARY_COOPERATION sourcelang:english sourcecountry:US",
        ],
    },
}

# Google News search for geopolitical_news via SerpAPI.
GEOPOLITICAL_GOOGLE_NEWS_SOURCE: dict[str, Any] = {
    "domain_slug": "geopolitical_news",
    "url": "google_news:geopolitical",
    "name": "Google News",
    "source_type": "google_news",
    "frequency_name": "daily",
    "description": "Google News search across geopolitics topics via SerpAPI.",
    "config": {
        "queries": [
            "geopolitics",
            "sanctions",
            "export controls",
            "trade war tariffs",
            "military conflict",
            "diplomatic relations",
            "territorial dispute",
        ],
    },
}

# VC commentary / investor blogs.
VC_COMMENTARY_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "vc_commentary",
        "url": "https://medium.com/feed/mayfield-perspectives",
        "name": "Mayfield Viewpoints",
        "frequency_name": "daily",
        "description": "Navin Chaddha / Mayfield on AI-economy theses and founder leadership.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://techcrunch.com/author/navin-chaddha/feed/",
        "name": "Navin Chaddha (TechCrunch)",
        "frequency_name": "daily",
        "description": "Op-eds on AI, startups, and markets from Mayfield Managing Partner.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://www.mayfield.com/feed",
        "name": "Mayfield",
        "frequency_name": "daily",
        "description": "Mayfield Fund firm perspectives and portfolio insights.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "http://avc.com/feed/",
        "name": "AVC",
        "frequency_name": "daily",
        "description": "Fred Wilson (USV) — daily VC commentary since 2003.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://abovethecrowd.com/feed",
        "name": "Above the Crowd",
        "frequency_name": "daily",
        "description": "Bill Gurley (Benchmark) on platforms, valuations, and regulation.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://andrewchen.com/feed",
        "name": "Andrew Chen",
        "frequency_name": "daily",
        "description": "Andrew Chen (a16z) on growth, consumer, and AI products.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://tomtunguz.com/index.xml",
        "name": "Tomasz Tunguz",
        "frequency_name": "daily",
        "description": "Tomasz Tunguz (Theory) — data-driven SaaS and AI market analysis.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://blog.eladgil.com/feed",
        "name": "Elad Gil",
        "frequency_name": "daily",
        "description": "Elad Gil on startups, AI, and high-growth company building.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://www.saastr.com/feed",
        "name": "SaaStr",
        "frequency_name": "daily",
        "description": "Jason Lemkin on SaaS and AI GTM strategies.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://www.lennysnewsletter.com/feed",
        "name": "Lenny's Newsletter",
        "frequency_name": "daily",
        "description": "Lenny Rachitsky on product, growth, and AI product strategy.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://www.newcomer.co/feed",
        "name": "Newcomer",
        "frequency_name": "daily",
        "description": "Eric Newcomer on VC, tech politics, and startup industry news.",
    },
    {
        "domain_slug": "vc_commentary",
        "url": "https://feld.com/feed",
        "name": "Feld Thoughts",
        "frequency_name": "daily",
        "description": "Brad Feld (Foundry) on VC, startups, and entrepreneurship.",
    },
]

# Adverse media / investigative sources.
# Kept separate so they can be toggled independently for testing.
# To enable: uncomment the *ADVERSE_SOURCES line at the bottom of SOURCES.
ADVERSE_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "adverse_media",
        "url": "https://thebearcave.substack.com/feed",
        "name": "The Bear Cave",
        "frequency_name": "daily",
        "description": "Edwin Dorsey's investigative research exposing corporate misconduct and short-sell targets.",
    },
    {
        "domain_slug": "adverse_media",
        "url": "https://hntrbrk.com/feed",
        "name": "Hunterbrook",
        "frequency_name": "daily",
        "description": "Investigative journalism uncovering corporate and financial misconduct.",
    },
]


SOURCES: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # AI News
    # ------------------------------------------------------------------
    {
        "domain_slug": "ai_news",
        "url": "https://venturebeat.com/category/ai/feed/",
        "name": "VentureBeat AI",
        "frequency_name": "daily",
        "description": (
            "The leading source for transformative tech news with"
            " deep AI, machine learning, and data coverage for"
            " business leaders."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://www.theverge.com/rss/ai-artificial-intelligence"
            "/index.xml"
        ),
        "name": "The Verge AI",
        "frequency_name": "daily",
        "description": (
            "Technology news, reviews, and culture covering gadgets,"
            " platforms, AI tools, and how tech shapes everyday life."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://techcrunch.com/category/artificial-intelligence"
            "/feed/"
        ),
        "name": "TechCrunch AI",
        "frequency_name": "daily",
        "description": (
            "AI-focused startup and technology news covering funding,"
            " launches, and innovation from TechCrunch."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "name": "Wired AI",
        "frequency_name": "daily",
        "description": (
            "Covers how AI affects culture, economy, and politics,"
            " from model releases to societal implications."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.technologyreview.com/feed/",
        "name": "MIT Technology Review",
        "frequency_name": "daily",
        "description": (
            "Covers emerging technologies and their impact on"
            " society, business, and the future, published by MIT."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.nextplatform.com/feed/",
        "name": "The Next Platform",
        "frequency_name": "daily",
        "description": (
            "In-depth coverage of high-end computing at large"
            " enterprises, supercomputing centres, hyperscale data"
            " centres, and public clouds."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://semiengineering.com/feed/",
        "name": "Semiconductor Engineering",
        "frequency_name": "daily",
        "description": (
            "Deep technical coverage of semiconductor design,"
            " manufacturing, verification, and EDA for chip"
            " engineers."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.servethehome.com/feed/",
        "name": "ServeTheHome",
        "frequency_name": "daily",
        "description": (
            "Covers servers, storage, networking, and high-end"
            " workstation hardware for IT professionals and"
            " enthusiasts."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.datacenterdynamics.com/en/rss/",
        "name": "Data Center Dynamics",
        "frequency_name": "daily",
        "description": (
            "News and analysis on data centre infrastructure,"
            " hyperscale cloud, colocation, AI workloads, and"
            " energy."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://news.crunchbase.com/feed/",
        "name": "Crunchbase News",
        "frequency_name": "daily",
        "description": (
            "Startup funding trends, investment rounds, and private"
            " company intelligence from Crunchbase."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://siliconangle.com/feed/",
        "name": "SiliconAngle",
        "frequency_name": "daily",
        "description": (
            "The trusted voice of enterprise technology, reporting"
            " on AI, cloud, security, and data infrastructure for"
            " IT leaders."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://feeds.arstechnica.com/arstechnica/technology-lab"
        ),
        "name": "Ars Technica",
        "frequency_name": "daily",
        "description": (
            "In-depth technology journalism covering science, policy,"
            " hardware, and software with academic-level rigour."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://spectrum.ieee.org/feeds/feed.rss",
        "name": "IEEE Spectrum",
        "frequency_name": "daily",
        "description": (
            "The flagship publication of IEEE, covering engineering,"
            " electronics, AI, robotics, and emerging technology."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.therobotreport.com/feed/",
        "name": "The Robot Report",
        "frequency_name": "daily",
        "description": (
            "News and analysis on commercial robotics, autonomous"
            " systems, AI for robots, and industrial automation."
        ),
    },
    # Weekly feeds - only polled when days_back >= 7
    {
        "domain_slug": "ai_news",
        "url": "https://huggingface.co/blog/feed.xml",
        "name": "Hugging Face Blog",
        "frequency_name": "weekly",
        "description": (
            "Covers machine learning research, open-source AI tools,"
            " transformers, and practical implementation guides."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.canarymedia.com/rss.xml",
        "name": "Canary Media",
        "frequency_name": "weekly",
        "description": (
            "Nonprofit journalism covering the clean energy"
            " transition, decarbonisation, and climate technology"
            " markets."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.hackster.io/feed",
        "name": "Hackster.io",
        "frequency_name": "weekly",
        "description": (
            "Community platform for hardware developers covering ML,"
            " IoT, robotics, and maker projects with emerging tech."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.quantamagazine.org/feed/",
        "name": "Quanta Magazine",
        "frequency_name": "weekly",
        "description": (
            "Science journalism covering mathematics, theoretical"
            " physics, computer science, and the basic life"
            " sciences."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.lawfaremedia.org/feed",
        "name": "Lawfare",
        "frequency_name": "weekly",
        "description": (
            "Non-partisan analysis of national security law,"
            " cybersecurity, executive powers, content moderation,"
            " and AI governance."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.eff.org/rss/updates.xml",
        "name": "EFF",
        "frequency_name": "weekly",
        "description": (
            "The Electronic Frontier Foundation covers digital civil"
            " liberties, privacy, surveillance, and technology"
            " policy."
        ),
    },
    # ------------------------------------------------------------------
    # Smart Money
    # ------------------------------------------------------------------
    {
        "domain_slug": "smart_money",
        "url": "https://www.pymnts.com/feed/",
        "name": "PYMNTS",
        "frequency_name": "daily",
        "description": (
            "Global data, news, and insights on innovation in"
            " payments and the connected economy."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.finextra.com/rss/rss.aspx",
        "name": "Finextra",
        "frequency_name": "daily",
        "description": (
            "The leading global newswire for financial technology"
            " professionals, covering fintech, payments, banking,"
            " and crypto."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://techcrunch.com/category/fintech/feed/",
        "name": "TechCrunch Fintech",
        "frequency_name": "daily",
        "description": (
            "Fintech-focused coverage of startups, funding, and"
            " innovation in payments and financial services."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "name": "CoinDesk",
        "frequency_name": "daily",
        "description": (
            "Leading cryptocurrency and blockchain news, with market"
            " data, policy analysis, and DeFi coverage."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.theblock.co/rss.xml",
        "name": "The Block",
        "frequency_name": "daily",
        "description": (
            "Breaking news, research, and analysis on Bitcoin,"
            " Ethereum, and digital assets for crypto professionals."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://decrypt.co/feed",
        "name": "Decrypt",
        "frequency_name": "daily",
        "description": (
            "Independent crypto and AI news covering blockchain,"
            " digital assets, culture, and emerging technology."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://a16z.com/feed/",
        "name": "a16z",
        "frequency_name": "daily",
        "description": (
            "Andreessen Horowitz publishes analysis, research, and"
            " opinion on technology, crypto, AI, and venture"
            " investing."
        ),
    },
    # ------------------------------------------------------------------
    # Substack newsletters (free tier - full body in RSS)
    # ------------------------------------------------------------------
    *SUBSTACK_SOURCES,
    # ------------------------------------------------------------------
    # SerpAPI Google News
    # ------------------------------------------------------------------
    GOOGLE_NEWS_SOURCE,
    # ------------------------------------------------------------------
    # NewsAPI top-headlines
    # ------------------------------------------------------------------
    *NEWSAPI_SOURCES,
    # ------------------------------------------------------------------
    # Adverse media / investigative 
    # ------------------------------------------------------------------
     *ADVERSE_SOURCES,
    # ------------------------------------------------------------------
    # VC commentary / investor blogs
    # ------------------------------------------------------------------
    *VC_COMMENTARY_SOURCES,
    # ------------------------------------------------------------------
    # Company-specific news (Alpha Vantage)
    # ------------------------------------------------------------------
    *COMPANY_NEWS_SOURCES,
    # ------------------------------------------------------------------
    # Geopolitical news (Federal Register + Google News)
    # ------------------------------------------------------------------
    *FEDERAL_REGISTER_SOURCES,
    GEOPOLITICAL_GOOGLE_NEWS_SOURCE,
    GDELT_SOURCE,
    # ------------------------------------------------------------------
    # Taiwan market signal (TWSE + TPEx OpenData)
    # ------------------------------------------------------------------
    *TAIWAN_REVENUE_SOURCES,
    *TAIWAN_MATERIAL_SOURCES,
    TAIWAN_GDELT_SOURCE,
    # ------------------------------------------------------------------
    # Korea market signal (DART + Korean-language trade press RSS + GDELT
    # + Customs export press-release scrape)
    # ------------------------------------------------------------------
    KOREA_DART_SOURCE,
    *KOREA_RSS_SOURCES,
    KOREA_GDELT_SOURCE,
    KOREA_GDELT_ENGLISH_SOURCE,
    KOREA_CUSTOMS_EXPORT_SOURCE,
]

# VC commentary / investor blogs.
# Kept separate so they can be toggled independently for testing.
# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------


def seed() -> None:
    """Insert frequencies, domains, taxonomies, and sources.

    Skips rows that already exist. Safe to call multiple times.
    All inserts run in a single transaction; a failure rolls back
    the entire seed run.
    """
    with transaction():
        # Run statuses (must be seeded before runs table is used)
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO run_statuses (name)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(s,) for s in RUN_STATUSES],
            )
        logger.info("Seeded %d run statuses.", len(RUN_STATUSES))

        # Frequencies
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO frequencies (name, min_days_back)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(f["name"], f["min_days_back"]) for f in FREQUENCIES],
            )
            rows = conn.execute(
                "SELECT id, name FROM frequencies"
                " WHERE name = ANY(?)",
                ([f["name"] for f in FREQUENCIES],),
            ).fetchall()
        freq_id_map = {row["name"]: row["id"] for row in rows}
        logger.info("Seeded %d frequencies.", len(freq_id_map))

        # Domains
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO domains (name, slug, description)"
                " VALUES %s ON CONFLICT (slug) DO NOTHING",
                [
                    (d["name"], d["slug"], d["description"])
                    for d in DOMAINS
                ],
            )
            rows = conn.execute(
                "SELECT id, slug FROM domains WHERE slug = ANY(?)",
                ([d["slug"] for d in DOMAINS],),
            ).fetchall()
        domain_id_map = {row["slug"]: row["id"] for row in rows}
        logger.info("Seeded %d domains.", len(domain_id_map))

        # Sources
        source_rows = [
            (
                s["url"],
                domain_id_map[s["domain_slug"]],
                freq_id_map[s.get("frequency_name", "daily")],
                s["name"],
                s["description"],
                s.get("no_fetch", False),
                s.get("source_type", "rss"),
                json.dumps(s["config"]) if s.get("config") else None,
            )
            for s in SOURCES
        ]
        with get_db() as conn:
            cur = conn.execute_values(
                "INSERT INTO sources"
                " (url, domain_id, frequency_id, name, description,"
                " no_fetch, source_type, config)"
                " VALUES %s ON CONFLICT (url) DO NOTHING RETURNING id",
                source_rows,
            )
            inserted = len(cur.fetchall())
        skipped = len(source_rows) - inserted
        logger.info(
            "Seed complete: %d sources inserted,"
            " %d already existed.",
            inserted,
            skipped,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    seed()
