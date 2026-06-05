"""Seed the database with initial lookup data.

Idempotent - rows that already exist are silently skipped.
"""
import logging

from db import get_db, transaction

logger = logging.getLogger(__name__)

CLASSIFICATION_STATUSES: list[str] = ["processing", "completed", "failed"]

# (slug, display_name, domain_group)
CONCEPT_TAXONOMY: list[tuple[str, str, str]] = [
    ("large-language-models", "Large Language Models", "ai-core"),
    ("computer-vision", "Computer Vision", "ai-core"),
    ("reinforcement-learning", "Reinforcement Learning", "ai-core"),
    ("generative-ai", "Generative AI", "ai-core"),
    ("neural-architecture", "Neural Architecture & Design", "ai-core"),
    ("ai-agents", "AI Agents & Automation", "applied-ai"),
    ("robotics", "Robotics & Physical AI", "applied-ai"),
    ("autonomous-vehicles", "Autonomous Vehicles", "applied-ai"),
    ("speech-audio", "Speech & Audio AI", "applied-ai"),
    ("recommendation-systems", "Recommendation Systems", "applied-ai"),
    ("drug-discovery", "Drug Discovery & Pharma", "science"),
    ("genomics", "Genomics & Bioinformatics", "science"),
    ("climate-science", "Climate Science", "science"),
    ("neuroscience", "Neuroscience & Brain Science", "science"),
    ("materials-science", "Materials Science", "science"),
    ("quantum-computing", "Quantum Computing", "science"),
    ("semiconductor-hardware", "Semiconductor & Hardware", "infrastructure"),
    ("cloud-computing", "Cloud & Distributed Systems", "infrastructure"),
    ("cybersecurity", "Cybersecurity", "infrastructure"),
    ("cryptography", "Cryptography & Zero-Knowledge", "infrastructure"),
    ("edge-computing", "Edge & Embedded Computing", "infrastructure"),
    ("data-infrastructure", "Data Infrastructure & Pipelines", "infrastructure"),
    ("policy-regulation", "Policy & Regulation", "governance"),
    ("ai-safety", "AI Safety & Alignment", "governance"),
    ("privacy", "Privacy & Surveillance", "governance"),
    ("ethics-bias", "Ethics, Bias & Fairness", "governance"),
    ("intellectual-property", "Intellectual Property & Copyright", "governance"),
    ("financial-markets", "Financial Markets & Trading", "finance"),
    ("venture-capital", "Venture Capital & Startups", "finance"),
    ("economic-impact", "Economic Impact & Labor", "finance"),
    ("supply-chain", "Supply Chain & Logistics", "finance"),
    ("fintech", "Fintech & Digital Payments", "finance"),
    ("clinical-medicine", "Clinical Medicine & Diagnostics", "health"),
    ("digital-health", "Digital Health & Wearables", "health"),
    ("biotech", "Biotechnology & Synthetic Biology", "health"),
    ("renewable-energy", "Renewable Energy & Grid", "energy-environment"),
    ("energy-storage", "Energy Storage & Batteries", "energy-environment"),
    ("environmental-monitoring", "Environmental Monitoring", "energy-environment"),
    ("media-disinformation", "Media & Disinformation", "media-society"),
    ("creative-ai", "Creative AI & Art", "media-society"),
]


def seed() -> None:
    """Insert classification statuses and concept taxonomy.

    Safe to call multiple times; all inserts use ON CONFLICT DO NOTHING.
    """
    with transaction():
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO classification_statuses (name)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(s,) for s in CLASSIFICATION_STATUSES],
            )
    logger.info(
        "Seeded %d classification statuses.",
        len(CLASSIFICATION_STATUSES),
    )
    with transaction():
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO concept_taxonomy"
                " (slug, display_name, domain_group)"
                " VALUES %s ON CONFLICT (slug) DO NOTHING",
                CONCEPT_TAXONOMY,
            )
    logger.info("Seeded %d concept taxonomy entries.", len(CONCEPT_TAXONOMY))
