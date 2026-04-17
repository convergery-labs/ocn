"""Seed the database with initial domain and source data.

Run directly to populate a fresh database:

    python seed.py

The script is idempotent — rows that already exist (matched by slug
or URL) are silently skipped.
"""
import logging
import os
from typing import Any

from db import get_db, init_db, transaction
from models.api_keys import (
    create_api_key,
    get_by_hash,
    hash_key,
)

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
            )
            for s in SOURCES
        ]
        with get_db() as conn:
            cur = conn.execute_values(
                "INSERT INTO sources"
                " (url, domain_id, frequency_id, name, description)"
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


def seed_admin_key() -> None:
    """Create the admin API key from ADMIN_API_KEY env var if not present.

    Idempotent: skips insertion if the key already exists in the DB.
    """
    key = os.environ["ADMIN_API_KEY"]
    if get_by_hash(hash_key(key)) is not None:
        logger.info("Admin key already exists — skipping seed.")
        return
    create_api_key(key, label="seed-admin", role="admin", created_by=None)
    logger.info("Seed admin key created.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    seed()
    seed_admin_key()
