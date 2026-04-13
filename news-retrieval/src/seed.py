"""Seed the database with initial domain and source data.

Run directly to populate a fresh database:

    python seed.py

The script is idempotent — rows that already exist (matched by slug
or URL) are silently skipped.
"""
import logging
from typing import Any

from db import get_db, init_db, transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

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
]

# Keys are domain slugs; list order determines position (1-based).
TAXONOMIES: dict[str, list[str]] = {
    "ai_news": [
        "AI Agents & Automation",
        "AI Models & Research",
        "AI Hardware & Semiconductors",
        "Data Center Infrastructure",
        "Energy & Sustainability",
        "Robotics & Physical AI",
        "Edge & Local AI",
        "Enterprise AI & Productivity",
        "AI Security & Privacy",
        "AI Policy & Governance",
        "AI Funding & Startups",
        "AI in Science & Society",
    ],
    "smart_money": [
        "Agentic Payments & AI Wallets",
        "Machine Economy & AI-to-AI Transactions",
        "Stablecoins & On-Chain Settlement",
        "Cross-Border Payments & Real-Time Settlement",
        "Embedded Finance & API Banking",
        "AI Fraud Detection & Compliance",
        "Treasury Automation & Enterprise Finance",
    ],
}

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
    # Weekly feeds — only polled when days_back >= 7
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
]

# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------


def _insert_or_get_id(
    unique_col: str,
    unique_val: str,
    insert_sql: str,
    select_sql: str,
    params: dict[str, Any],
    label: str,
) -> int:
    """Insert a row (if it does not exist) and return its id.

    Uses ON CONFLICT DO NOTHING so the ambient transaction remains
    valid whether or not the row already exists, then SELECTs the id.

    Args:
        unique_col: Column name used only for log output.
        unique_val: Value of that column, used for log output and SELECT.
        insert_sql: INSERT … ON CONFLICT DO NOTHING statement.
        select_sql: SELECT id … WHERE unique_col = %s statement.
        params: Bind parameters for the INSERT.
        label: Human-readable label used in log output.

    Returns:
        The id of the inserted or pre-existing row.
    """
    with get_db() as conn:
        conn.execute(insert_sql, params)
        row = conn.execute(select_sql, (unique_val,)).fetchone()
        logger.info("Seeded %s: %s", label, unique_val)
        return row["id"]


def seed() -> None:
    """Insert frequencies, domains, taxonomies, and sources.

    Skips rows that already exist. Safe to call multiple times.
    All inserts run in a single transaction; a failure rolls back
    the entire seed run.
    """
    with transaction():
        # Frequencies
        freq_id_map: dict[str, int] = {}
        for freq in FREQUENCIES:
            freq_id_map[freq["name"]] = _insert_or_get_id(
                unique_col="name",
                unique_val=freq["name"],
                insert_sql=(
                    "INSERT INTO frequencies (name, min_days_back)"
                    " VALUES (:name, :min_days_back)"
                    " ON CONFLICT (name) DO NOTHING"
                ),
                select_sql=(
                    "SELECT id FROM frequencies WHERE name = ?"
                ),
                params=freq,
                label="frequency",
            )

        # Domains
        domain_id_map: dict[str, int] = {}
        for domain in DOMAINS:
            domain_id_map[domain["slug"]] = _insert_or_get_id(
                unique_col="slug",
                unique_val=domain["slug"],
                insert_sql=(
                    "INSERT INTO domains (name, slug, description)"
                    " VALUES (:name, :slug, :description)"
                    " ON CONFLICT (slug) DO NOTHING"
                ),
                select_sql=(
                    "SELECT id FROM domains WHERE slug = ?"
                ),
                params=domain,
                label="domain",
            )

        # Taxonomies — position derived from list index
        for domain_slug, categories in TAXONOMIES.items():
            domain_id = domain_id_map[domain_slug]
            for position, category in enumerate(categories, start=1):
                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO taxonomies"
                        " (domain_id, category, position)"
                        " VALUES (?, ?, ?)"
                        " ON CONFLICT (domain_id, category) DO NOTHING",
                        (domain_id, category, position),
                    )
                    logger.info(
                        "Seeded taxonomy: [%s] %s",
                        domain_slug,
                        category,
                    )

        # Sources
        inserted = skipped = 0
        for source in SOURCES:
            domain_id = domain_id_map[source["domain_slug"]]
            frequency_id = freq_id_map[
                source.get("frequency_name", "daily")
            ]
            with get_db() as conn:
                cursor = conn.execute(
                    "INSERT INTO sources"
                    " (url, domain_id, frequency_id, name,"
                    " description)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT (url) DO NOTHING",
                    (
                        source["url"],
                        domain_id,
                        frequency_id,
                        source["name"],
                        source["description"],
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    skipped += 1

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
