"""
taxonomy_rules.py - Single source of truth for all taxonomy definitions,
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
COMMERCIAL COMPANIES ONLY - strictly exclude:
- Universities, research labs, academic institutions, government agencies
- Non-profit organisations, investment funds, ETFs, holding companies without operations
- Companies that are acquired, dissolved, delisted, or bankrupt

UNIVERSE INCLUSION - a company belongs in the AI Economy Universe if it is a meaningful
enabler or participant in the AI economy stack, even if AI is not their primary business.
Examples: a solar energy company (FSLR) belongs in Energy & Grid because AI data centers
need power; a mining company (FCX) belongs in Raw Materials because AI chips need copper.
The test is: "Does this company play a real role in making AI possible or commercially viable?"

CATEGORY ASSIGNMENT - assign to the category that matches the company's PRIMARY business,
not the category where AI happens to use their output:
- A utility that generates power → Energy & Grid (cat 02), NOT Raw Materials
- A copper miner → Raw Materials (cat 01), NOT Semiconductor Manufacturing
- A cloud provider → Cloud & Compute Platforms (cat 09), NOT Data Centers\
"""

# ── One-line category cheat-sheet (used in SYSTEM_PROMPT) ────────────────────
# Short enough to fit in the system prompt without bloating token count.
# Each line states what IS and what IS NOT in the category.
CATEGORY_CHEATSHEET = """\
01. Raw Materials & Critical Minerals - mining, extraction, or minimal processing of ANY mineral or raw material (lithium/copper/rare earths/potash/salt/graphite/specialty metals). Primary revenue must come from selling the raw or minimally-processed material itself (ore, concentrate, billet, refined metal) — NOT a fabricated product made from it. NOT energy utilities, NOT chip designers, NOT downstream manufacturers (PCB laminates → cat 04, specialty alloys → cat 04, structural steel → cat 07).
02. Energy & Grid Infrastructure - electricity generation, transmission, grid, storage, EV charging. NOT nuclear-specific (cat 03), NOT chip/semiconductor makers (power chips like SiC/GaN/PMICs are cat 04 regardless of "power" in the name), NOT fuel/extraction companies (oil, gas, uranium producers are cat 01 or cat 03 — selling fuel to power plants ≠ operating grid infrastructure), NOT data center builders.
03. Nuclear & Advanced Energy - nuclear power, SMRs, fusion, long-duration storage. NOT conventional utilities or renewables.
04. Semiconductor Manufacturing - chip design, foundries, OSAT, EDA, lithography, semiconductor equipment & materials. NOT server assemblers, NOT cloud.
05. Compute Hardware & Edge Systems - AI servers, GPUs, edge devices, ODMs, EMS, robotics hardware. NOT chip fabs, NOT cloud services.
06. Networking, Optical & Interconnect - switches, optical transceivers, silicon photonics, high-speed interconnects. NOT telecom operators, NOT data center builders.
07. Data Centers & Physical Infrastructure - colocation, cooling, power distribution, data center construction & REITs. NOT cloud software, NOT networking chips.
08. Telecom & Connectivity - mobile operators, fixed-line, satellite internet, 5G/6G network operators. NOT equipment makers (that is Networking), NOT cloud.
09. Cloud & Compute Platforms - cloud IaaS/PaaS, GPU cloud, sovereign compute platforms. NOT SaaS applications, NOT on-premise hardware.
10. AI Software Infrastructure - MLOps, AI dev tools, vector DBs, AI security, orchestration, enterprise AI platforms. NOT consumer apps, NOT hardware.
11. AI Data Infrastructure - data pipelines, labeling, annotation, synthetic data, data quality for AI. NOT general BI tools.
12. AI Models & Intelligence Layer - foundation model providers, LLM APIs as core product. NOT companies that only USE AI.
13. Robotics & Physical AI - industrial robots, humanoids, drones, autonomous vehicles as primary product. NOT pure software for robotics.
14. Quantum Computing & Sensing - quantum computers, quantum networking, quantum sensing as primary business. NOT companies with only a quantum research division.
15. Life Sciences & Healthcare AI - AI-core products in drug discovery, medical imaging, genomics, diagnostics. NOT general pharma or hospitals.
16. Defense, Aerospace & Sovereign AI - primary revenue from defense contracts, military systems, government intelligence, or space with direct defense application. NOT commercial tech companies, NOT telecom operators, NOT solar/energy companies, NOT general Chinese tech giants unless defense contracts are their primary revenue.
17. Financial Infrastructure & AI Capital - AI-core fintech, capital markets technology, AI lending/payments. NOT general banks or traditional asset managers.
18. Water & Resource Infrastructure - water treatment, resource efficiency, environmental tech with AI as core. NOT general utilities.
19. Applications & Digital Economy - end-user AI apps, vertical SaaS with AI at core, consumer AI products. NOT infrastructure layers.\
"""

# ── Full category definitions (used in DISCOVERY_PROMPT per-category) ────────
CATEGORY_DEFINITIONS: dict[str, str] = {
    "01. Raw Materials & Critical Minerals": (
        "Companies whose PRIMARY revenue comes from mining, extracting, or minimally processing "
        "physical raw materials - any mineral, metal, or natural resource including lithium, "
        "cobalt, copper, nickel, rare earth elements, graphite, silica, specialty gases, potash, "
        "salt, agricultural minerals, industrial minerals, and other mined or extracted commodities. "
        "The test is: does the company's primary revenue come from selling the raw or minimally-processed "
        "material itself (ore, concentrate, billet, refined metal)? "
        "CRITICAL DISTINCTION: a company that BUYS raw materials and converts them into a fabricated "
        "product is a downstream manufacturer, NOT a raw materials company - regardless of how "
        "closely the fabricated product is associated with its input material. "
        "Examples of downstream manufacturers that do NOT belong here: "
        "PCB laminate makers (buy copper/fiberglass → make laminates → category 04), "
        "specialty alloy processors (buy titanium/nickel → make alloy components → category 04), "
        "steel manufacturers (mine iron ore but primary product is fabricated steel → category 07). "
        "EXCLUDES: energy utilities and electricity generators (category 02), chip designers (category 04), "
        "software companies, and companies whose only link to this sector is supplying energy or services to miners."
    ),
    "02. Energy & Grid Infrastructure": (
        "Companies that generate, transmit, distribute, or store electricity - "
        "utilities, renewable energy producers (wind, solar, hydro, geothermal), grid operators, "
        "battery storage, EV charging infrastructure, and energy management systems. "
        "CRITICAL EXCLUSION 1 - Power semiconductors: chip and semiconductor companies whose products "
        "relate to power management or conversion (SiC chips, GaN ICs, PMICs, power conversion modules) "
        "are semiconductor manufacturers (category 04), NOT energy companies. The test is: does the "
        "company operate or build energy infrastructure, or does it sell chips? Chip sellers → cat 04. "
        "CRITICAL EXCLUSION 2 - Fuel and extraction: companies that produce fuel (natural gas, oil, "
        "uranium) for power plants do NOT belong here. Selling fuel to grid operators ≠ operating grid "
        "infrastructure. Oil & gas producers → category 01 (extraction). Uranium companies → category 03. "
        "ALSO EXCLUDES: nuclear-specific companies (category 03), data center builders (category 07), "
        "and software-only energy management platforms."
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
        "semiconductors - chip designers (fabless or IDM), foundries, OSAT, EDA software, "
        "lithography systems, semiconductor equipment, wafer/substrate suppliers, and metrology. "
        "EXCLUDES: server/hardware assemblers (category 05), cloud providers (category 09), "
        "and companies that only buy chips rather than make or design them."
    ),
    "05. Compute Hardware & Edge Systems": (
        "Companies that design or manufacture physical computing hardware - AI servers, GPU systems, "
        "edge devices, embedded systems, ODMs, EMS/contract manufacturers, and hardware systems "
        "integrators. Also includes edge AI inference hardware, industrial IoT hardware, and "
        "robotics hardware components. "
        "EXCLUDES: chip fabs and designers (category 04), cloud software services (category 09), "
        "and pure software companies."
    ),
    "06. Networking, Optical & Interconnect": (
        "Companies that make networking hardware and optical components - switches, routers, "
        "optical transceivers, silicon photonics, fiber cables, optical modules, load balancers, "
        "and high-speed interconnects for data centers and telecoms. "
        "EXCLUDES: telecom network operators (category 08), data center builders (category 07), "
        "and cloud software networking (category 09)."
    ),
    "07. Data Centers & Physical Infrastructure": (
        "Companies that build, own, or operate data center facilities and physical infrastructure - "
        "colocation providers, hyperscaler facilities, cooling/thermal management, power distribution "
        "units, construction/engineering for data centers, and REITs owning digital infrastructure. "
        "EXCLUDES: cloud software services, networking equipment makers, and telecom operators."
    ),
    "08. Telecom & Connectivity": (
        "Companies that operate telecommunications networks - mobile operators, fixed-line providers, "
        "satellite internet operators, submarine cable operators, and 5G/6G network operators. "
        "Revenue must come from operating networks and selling connectivity, not from making equipment. "
        "EXCLUDES: networking equipment makers (category 06), cloud providers (category 09), "
        "and data center builders (category 07)."
    ),
    "09. Cloud & Compute Platforms": (
        "Companies that sell cloud computing services, managed infrastructure, or GPU cloud - "
        "hyperscalers, neoclouds, sovereign cloud providers, cloud-native platforms offering "
        "IaaS or PaaS. "
        "EXCLUDES: SaaS application vendors (category 10 or 19), on-premise hardware makers (05), "
        "and telecom operators that resell cloud (category 08)."
    ),
    "10. AI Software Infrastructure": (
        "Companies that build the software layer enabling AI development and deployment - "
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
        "as their primary commercial product - industrial robots, humanoids, warehouse automation "
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
        "Companies whose PRIMARY revenue comes from defense contracts, military AI systems, "
        "government intelligence platforms, border/surveillance technology sold to governments, "
        "or space technology with direct defense/national security applications. "
        "EXCLUDES: commercial aerospace without significant defense contracts, "
        "general telecom operators (category 08), solar/energy companies (category 02), "
        "general technology conglomerates (Tencent, Huawei, Samsung) whose defense revenue "
        "is not their primary business, and companies whose defense revenue is under 20% of total revenue. "
        "'Sovereign AI' means government-contracted AI for national security - NOT simply being "
        "a state-linked tech company or a national champion in a non-defense sector."
    ),
    "17. Financial Infrastructure & AI Capital": (
        "Companies providing financial infrastructure for AI - AI-focused fintech platforms, "
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
    import models.taxonomy as taxonomy_model  # local import - avoids circular deps
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
