"""
taxonomy_rules.py — Single source of truth for all taxonomy definitions,
validation rules, and constraints used across the AI Economy Universe.

USAGE
-----
Any prompt, tool, or discovery job that needs category/subcategory context
imports from here. Make changes in ONE place; everything else picks them up.

    from taxonomy_rules import (
        CATEGORY_DEFINITIONS,
        COMMERCIAL_COMPANY_RULE,
        SUBCATEGORY_RULES,
        get_category_definition,
        get_valid_subcategories,
        validate_subcategory_parent,
    )
"""
from __future__ import annotations

from typing import Any


# ── Commercial company filter ────────────────────────────────────────────────
# Used in every prompt that asks Claude to propose or classify companies.
COMMERCIAL_COMPANY_RULE = """\
COMMERCIAL COMPANIES ONLY — strictly exclude:
- Universities, research labs, academic institutions, government agencies
- Non-profit organisations, investment funds, ETFs, holding companies without operations
- Companies that are acquired, dissolved, delisted, or bankrupt
- Companies where the connection to this sector requires more than ONE hop of logic
  (e.g. a utility that "powers AI data centers" is NOT a Raw Materials company)
A company must derive PRIMARY revenue from this sector — not a subsidiary division or research project.\
"""

# ── One-line category cheat-sheet (used in SYSTEM_PROMPT) ────────────────────
# Short enough to fit in the system prompt without bloating token count.
# Each line states what IS and what IS NOT in the category.
CATEGORY_CHEATSHEET = """\
01. Raw Materials & Critical Minerals — mining, extraction, processing of lithium/copper/rare earths/graphite/specialty metals. NOT energy utilities, NOT chip designers.
02. Energy & Grid Infrastructure — electricity generation, grid, storage, power electronics, EV charging. NOT nuclear-specific, NOT data center builders.
03. Nuclear & Advanced Energy — nuclear power, SMRs, fusion, long-duration storage. NOT conventional utilities or renewables.
04. Semiconductor Manufacturing — chip design, foundries, OSAT, EDA, lithography, semiconductor equipment & materials. NOT server assemblers, NOT cloud.
05. Compute Hardware & Edge Systems — AI servers, GPUs, edge devices, ODMs, EMS, robotics hardware. NOT chip fabs, NOT cloud services.
06. Networking, Optical & Interconnect — switches, optical transceivers, silicon photonics, high-speed interconnects. NOT telecom operators, NOT data center builders.
07. Data Centers & Physical Infrastructure — colocation, cooling, power distribution, data center construction & REITs. NOT cloud software, NOT networking chips.
08. Telecom & Connectivity — mobile operators, fixed-line, satellite internet, 5G/6G network operators. NOT equipment makers (that is Networking), NOT cloud.
09. Cloud & Compute Platforms — cloud IaaS/PaaS, GPU cloud, sovereign compute platforms. NOT SaaS applications, NOT on-premise hardware.
10. AI Software Infrastructure — MLOps, AI dev tools, vector DBs, AI security, orchestration, enterprise AI platforms. NOT consumer apps, NOT hardware.
11. AI Data Infrastructure — data pipelines, labeling, annotation, synthetic data, data quality for AI. NOT general BI tools.
12. AI Models & Intelligence Layer — foundation model providers, LLM APIs as core product. NOT companies that only USE AI.
13. Robotics & Physical AI — industrial robots, humanoids, drones, autonomous vehicles as primary product. NOT pure software for robotics.
14. Quantum Computing & Sensing — quantum computers, quantum networking, quantum sensing as primary business. NOT companies with only a quantum research division.
15. Life Sciences & Healthcare AI — AI-core products in drug discovery, medical imaging, genomics, diagnostics. NOT general pharma or hospitals.
16. Defense, Aerospace & Sovereign AI — primary revenue from defense contracts, military AI, sovereign AI, space with defense application. NOT commercial aerospace.
17. Financial Infrastructure & AI Capital — AI-core fintech, capital markets technology, AI lending/payments. NOT general banks or traditional asset managers.
18. Water & Resource Infrastructure — water treatment, resource efficiency, environmental tech with AI as core. NOT general utilities.
19. Applications & Digital Economy — end-user AI apps, vertical SaaS with AI at core, consumer AI products. NOT infrastructure layers.\
"""

# ── Full category definitions (used in DISCOVERY_PROMPT per-category) ────────
# Verbose enough for Claude to make precise inclusion/exclusion decisions.
CATEGORY_DEFINITIONS: dict[str, str] = {
    "01. Raw Materials & Critical Minerals": (
        "Companies whose PRIMARY revenue comes from mining, extraction, processing, or trading "
        "of physical raw materials — lithium, cobalt, copper, nickel, rare earth elements, graphite, "
        "silica, specialty gases, and other minerals essential to AI hardware supply chains. "
        "EXCLUDES: energy utilities, electricity generators, chip designers, software companies, "
        "steel manufacturers whose primary product is structural steel (not specialty metals), "
        "and any company whose link to this sector is 'we supply energy to AI data centers'."
    ),
    "02. Energy & Grid Infrastructure": (
        "Companies that generate, transmit, distribute, or store electricity and power — "
        "utilities, renewable energy producers (wind, solar, hydro, geothermal), grid operators, "
        "battery storage, power electronics, EV charging infrastructure, and energy management. "
        "EXCLUDES: nuclear-specific companies (those are category 03), data center builders, "
        "mining/extraction companies, and software-only energy management platforms."
    ),
    "03. Nuclear & Advanced Energy": (
        "Companies focused specifically on nuclear power generation, small modular reactors (SMRs), "
        "fusion energy, uranium enrichment, long-duration energy storage beyond batteries, "
        "and next-generation advanced energy technologies. "
        "EXCLUDES: conventional renewable utilities, standard battery storage, "
        "and companies whose nuclear involvement is limited to a single research program."
    ),
    "04. Semiconductor Manufacturing": (
        "Companies that design, fabricate, package, test, or supply equipment and materials for "
        "semiconductors — chip designers (fabless or IDM), foundries, OSAT, EDA software, "
        "lithography systems, semiconductor equipment, wafer/substrate suppliers, and metrology. "
        "EXCLUDES: server/hardware assemblers (category 05), cloud providers (category 09), "
        "and companies that only buy chips rather than make or design them."
    ),
    "05. Compute Hardware & Edge Systems": (
        "Companies that design or manufacture physical computing hardware — AI servers, GPU systems, "
        "edge devices, embedded systems, ODMs, EMS/contract manufacturers, and hardware systems "
        "integrators. Also includes edge AI inference hardware, industrial IoT hardware, and "
        "robotics hardware components. "
        "EXCLUDES: chip fabs and designers (category 04), cloud software services (category 09), "
        "and pure software companies."
    ),
    "06. Networking, Optical & Interconnect": (
        "Companies that make networking hardware and optical components — switches, routers, "
        "optical transceivers, silicon photonics, fiber cables, optical modules, load balancers, "
        "and high-speed interconnects for data centers and telecoms. "
        "EXCLUDES: telecom network operators (category 08), data center builders (category 07), "
        "and cloud software networking (category 09)."
    ),
    "07. Data Centers & Physical Infrastructure": (
        "Companies that build, own, or operate data center facilities and physical infrastructure — "
        "colocation providers, hyperscaler facilities, cooling/thermal management, power distribution "
        "units, construction/engineering for data centers, and REITs owning digital infrastructure. "
        "EXCLUDES: cloud software services, networking equipment makers, and telecom operators."
    ),
    "08. Telecom & Connectivity": (
        "Companies that operate telecommunications networks — mobile operators, fixed-line providers, "
        "satellite internet operators, submarine cable operators, and 5G/6G network operators. "
        "Revenue must come from operating networks and selling connectivity, not from making equipment. "
        "EXCLUDES: networking equipment makers (category 06), cloud providers (category 09), "
        "and data center builders (category 07)."
    ),
    "09. Cloud & Compute Platforms": (
        "Companies that sell cloud computing services, managed infrastructure, or GPU cloud — "
        "hyperscalers, neoclouds, sovereign cloud providers, cloud-native platforms offering "
        "IaaS or PaaS. "
        "EXCLUDES: SaaS application vendors (category 10 or 19), on-premise hardware makers (05), "
        "and telecom operators that resell cloud (category 08)."
    ),
    "10. AI Software Infrastructure": (
        "Companies that build the software layer enabling AI development and deployment — "
        "MLOps platforms, AI development tools, vector databases, AI security and observability, "
        "orchestration frameworks, and enterprise AI middleware platforms. "
        "EXCLUDES: consumer-facing AI apps (category 19), data pipeline tools (category 11), "
        "foundation model providers (category 12), and pure hardware."
    ),
    "11. AI Data Infrastructure": (
        "Companies that provide data pipelines, labeling, annotation, synthetic data generation, "
        "data integration, data quality, and data observability tools specifically for AI training "
        "and inference workloads. "
        "EXCLUDES: general BI and analytics tools that are not AI-specific, "
        "and AI model providers (category 12)."
    ),
    "12. AI Models & Intelligence Layer": (
        "Companies that develop and commercialise foundation models, large language models, "
        "multimodal models, or AI APIs as their primary commercial product. "
        "EXCLUDES: companies that only use AI rather than build and sell AI models, "
        "and MLOps/tooling companies (category 10)."
    ),
    "13. Robotics & Physical AI": (
        "Companies that build physical robots, autonomous systems, drones, or physical AI hardware "
        "as their primary commercial product — industrial robots, humanoids, warehouse automation "
        "systems, autonomous vehicles (full stack), and drone platforms. "
        "EXCLUDES: pure software for robotics, component-only suppliers (category 05), "
        "and defense-primary companies (category 16)."
    ),
    "14. Quantum Computing & Sensing": (
        "Companies developing quantum computers, quantum processors, quantum networking hardware, "
        "or quantum sensing devices as a primary commercial business. "
        "EXCLUDES: companies that only have a quantum research lab as a side project, "
        "classical computing companies with quantum branding, and pure quantum software "
        "without hardware (those belong in category 10)."
    ),
    "15. Life Sciences & Healthcare AI": (
        "Companies applying AI as a core, revenue-generating part of their product in drug discovery, "
        "medical imaging, clinical trials, genomics, diagnostics, or healthcare operations. "
        "EXCLUDES: general pharmaceutical companies without a direct AI product, "
        "hospital systems, general biotech, and health insurance companies."
    ),
    "16. Defense, Aerospace & Sovereign AI": (
        "Companies with primary revenue from defense contracts, military AI systems, sovereign AI "
        "programmes, intelligence systems, or space technology with defense applications. "
        "EXCLUDES: commercial aerospace without defense contracts, "
        "and companies whose defense revenue is under 20% of total revenue."
    ),
    "17. Financial Infrastructure & AI Capital": (
        "Companies providing financial infrastructure for AI — AI-focused fintech platforms, "
        "capital markets technology using AI as core product, AI-powered payments, "
        "and lending platforms built on AI. "
        "EXCLUDES: general banks and traditional asset managers without a direct AI product, "
        "and investment funds (ETFs, VCs) that invest in AI companies."
    ),
    "18. Water & Resource Infrastructure": (
        "Companies focused on water treatment, water technology, resource efficiency, "
        "or environmental infrastructure using AI or advanced technology as a core product. "
        "EXCLUDES: general utilities (category 02) and general environmental services."
    ),
    "19. Applications & Digital Economy": (
        "Companies building end-user AI applications, vertical SaaS with AI at the core, "
        "consumer AI products, or digital platforms whose primary revenue comes from "
        "AI-powered application services. "
        "EXCLUDES: all infrastructure layers (categories 01–11), foundation model providers (12), "
        "and hardware companies."
    ),
}


# ── Helper functions ─────────────────────────────────────────────────────────

def get_category_definition(category_name: str) -> str:
    """Return the full definition for a category, or a generic fallback."""
    return CATEGORY_DEFINITIONS.get(
        category_name,
        "Companies whose PRIMARY revenue comes from this sector only.",
    )


def get_valid_subcategories(category_id: int) -> list[str]:
    """Return seeded (non-agent-proposed) subcategory names for a category.

    Imports taxonomy_model lazily to avoid circular imports at module load time.
    """
    import models.taxonomy as taxonomy_model  # local import — avoids circular deps
    rows = taxonomy_model.list_subcategories(category_id)
    return [r["name"] for r in rows if not r.get("agent_proposed")]


def validate_subcategory_parent(subcategory_id: int, category_id: int) -> bool:
    """Return True if the subcategory's parent_id matches the given category_id.

    Prevents a subcategory from one category being assigned to a company
    in a different category.
    """
    from db import get_db  # local import
    with get_db() as conn:
        cur = conn.execute(
            "SELECT parent_id FROM universe_taxonomy"
            " WHERE id = :id AND type = 'subcategory'",
            {"id": subcategory_id},
        )
        row = cur.fetchone()
    return row is not None and row["parent_id"] == category_id
