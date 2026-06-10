"""Agent tool definitions and executors for research-universe.

TOOL_DEFINITIONS - OpenAI-format schemas passed to the LLM.
execute_tool()   - dispatches a tool call to the right implementation.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

import models.company as company_model
import models.taxonomy as taxonomy_model
from agent.prompts import FIND_PEERS_PROMPT
from taxonomy_rules import validate_subcategory_parent

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tool definitions (OpenAI function-calling format)                           #
# --------------------------------------------------------------------------- #

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": (
                "Fuzzy search the universe by company name or ticker symbol. "
                "Returns matches with a similarity score (0–1). "
                "Use this before adding a company to check for duplicates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Company name or ticker"},
                    "limit": {"type": "integer", "default": 10, "description": "Max results"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company",
            "description": "Retrieve the full profile of a company by its UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "string", "description": "Company UUID"},
                },
                "required": ["company_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_company",
            "description": (
                "Add a new company to the universe. "
                "Sets agent_added=true and status=pending_review automatically. "
                "Use category_name and subcategory_name - IDs are resolved internally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "ticker": {"type": "string", "description": "Real trading symbol or 'Private'"},
                    "market": {"type": "string", "enum": ["National (US)", "International"]},
                    "country": {"type": "string"},
                    "website": {"type": "string"},
                    "category_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One or more category names from the 19-category taxonomy",
                    },
                    "subcategory_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Subcategory names - must align positionally with category_names",
                    },
                    "multi_category_reason": {
                        "type": "string",
                        "description": "Required when category_names has more than one entry",
                    },
                    "added_by": {"type": "string", "description": "user_name of the person triggering this"},
                },
                "required": ["company_name", "ticker", "market", "country", "website",
                             "category_names", "subcategory_names", "added_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_company",
            "description": "Edit one or more fields on an existing company record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "string"},
                    "fields": {
                        "type": "object",
                        "description": "Key-value pairs of fields to update (company_name, ticker, market, country, website, multi_category_reason)",
                    },
                },
                "required": ["company_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_company",
            "description": "Mark a pending_review company as verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "string"},
                    "verified_by": {"type": "string", "description": "user_name"},
                },
                "required": ["company_id", "verified_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending",
            "description": "Return all companies currently in pending_review status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_taxonomy",
            "description": (
                "Fuzzy search all taxonomy entries (categories and subcategories). "
                "Always call this before creating a new subcategory to check for near-duplicates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_taxonomy_entry",
            "description": "Create a new subcategory or category in the taxonomy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["category", "subcategory"]},
                    "category_name": {
                        "type": "string",
                        "description": "Required when type=subcategory - the parent category name",
                    },
                    "created_by": {"type": "string"},
                },
                "required": ["name", "type", "created_by"],
            },
        },
    },
    # find_peers disabled — re-enable when peer discovery is needed
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "find_peers",
    #         "description": (
    #             "Find companies that belong in the same category/subcategory but are not yet "
    #             "in the universe. Checks existing companies first, then uses Claude's knowledge "
    #             "to suggest missing peers. Call this after every new company addition."
    #         ),
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "company_name": {"type": "string", "description": "The company just added"},
    #                 "category_name": {"type": "string"},
    #                 "subcategory_name": {"type": "string"},
    #                 "country": {"type": "string"},
    #             },
    #             "required": ["company_name", "category_name", "subcategory_name", "country"],
    #         },
    #     },
    # },
]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _llm_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        timeout=120.0,  # discovery calls are longer - allow 2 min per category
    )


def _resolve_taxonomy_ids(
    category_names: list[str],
    subcategory_names: list[str],
) -> tuple[list[int], list[int], list[str]]:
    """Resolve name lists → id lists. Returns (cat_ids, sub_ids, errors).

    Subcategory resolution is constrained to only match subcategories whose
    parent_id matches one of the resolved category IDs — prevents cross-category
    contamination (e.g. an Energy subcategory landing on a Raw Materials company).
    """
    cat_ids, sub_ids, errors = [], [], []

    # ── Resolve categories ────────────────────────────────────────────────────
    for name in category_names:
        row = taxonomy_model.get_taxonomy_by_name(name, "category")
        if not row:
            hits = taxonomy_model.search_taxonomy(name, limit=1)
            row = hits[0] if hits and hits[0]["type"] == "category" else None
        if row:
            cat_ids.append(row["id"])
        else:
            errors.append(f"Category not found: '{name}'")

    # ── Resolve subcategories (constrained to resolved categories) ────────────
    for name in subcategory_names:
        row = taxonomy_model.get_taxonomy_by_name(name, "subcategory")
        if not row:
            hits = taxonomy_model.search_taxonomy(name, limit=3)
            # Only accept a fuzzy match if it belongs to one of our categories
            row = next(
                (h for h in hits
                 if h["type"] == "subcategory" and h.get("parent_id") in cat_ids),
                None,
            )
        if row:
            # Final parent validation — reject if subcategory belongs to a different category
            if cat_ids and not validate_subcategory_parent(row["id"], cat_ids[0]):
                errors.append(
                    f"Subcategory '{name}' belongs to a different category — rejected"
                )
            else:
                sub_ids.append(row["id"])
        else:
            errors.append(f"Subcategory not found in this category: '{name}'")

    return cat_ids, sub_ids, errors


# --------------------------------------------------------------------------- #
# Tool implementations                                                         #
# --------------------------------------------------------------------------- #

def _search_companies(query: str, limit: int = 10) -> dict[str, Any]:
    results = company_model.search_companies(query, limit)
    return {"companies": results, "count": len(results)}


def _get_company(company_id: str) -> dict[str, Any]:
    company = company_model.get_company(company_id)
    if not company:
        return {"error": f"Company '{company_id}' not found"}
    return company


def _create_company(
    company_name: str,
    ticker: str,
    market: str,
    country: str,
    website: str,
    category_names: list[str],
    subcategory_names: list[str],
    added_by: str,
    multi_category_reason: str | None = None,
) -> dict[str, Any]:
    cat_ids, sub_ids, errors = _resolve_taxonomy_ids(category_names, subcategory_names)
    if errors:
        return {"error": "Taxonomy resolution failed", "details": errors}

    return company_model.create_company({
        "company_name": company_name,
        "ticker": ticker,
        "market": market,
        "country": country,
        "website": website,
        "category_ids": cat_ids,
        "subcategory_ids": sub_ids,
        "multi_category_reason": multi_category_reason,
        "added_by": added_by,
    })


def _update_company(company_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    result = company_model.update_company(company_id, fields)
    if not result:
        return {"error": f"Company '{company_id}' not found"}
    return result


def _verify_company(company_id: str, verified_by: str) -> dict[str, Any]:
    success = company_model.verify_company(company_id, verified_by)
    if not success:
        return {"error": "Company not found or already verified"}
    return company_model.get_company(company_id)


def _list_pending() -> dict[str, Any]:
    results = company_model.get_pending_companies()
    return {"companies": results, "count": len(results)}


def _search_taxonomy(query: str, limit: int = 5) -> dict[str, Any]:
    results = taxonomy_model.search_taxonomy(query, limit)
    return {"entries": results, "count": len(results)}


def _create_taxonomy_entry(
    name: str,
    type: str,
    created_by: str,
    category_name: str | None = None,
) -> dict[str, Any]:
    if type == "category":
        return taxonomy_model.create_category(name, created_by)

    if not category_name:
        return {"error": "category_name is required when type=subcategory"}

    parent = taxonomy_model.get_taxonomy_by_name(category_name, "category")
    if not parent:
        return {"error": f"Parent category '{category_name}' not found"}

    result = taxonomy_model.create_subcategory(name, parent["id"], created_by)
    result["is_new_subcategory"] = True
    return result


def _find_peers(
    company_name: str,
    category_name: str,
    subcategory_name: str,
    country: str,
) -> dict[str, Any]:
    # Step 1 - resolve category name → ID, then fetch existing companies correctly
    cat_row = taxonomy_model.get_taxonomy_by_name(category_name, "category")
    if cat_row:
        existing = company_model.get_companies_by_category_id(cat_row["id"])
    else:
        existing = []
    existing_names = [c["company_name"] for c in existing]
    existing_list = "\n".join(f"- {n}" for n in existing_names) or "None yet"

    # Step 2 - ask Claude to find missing peers
    prompt = FIND_PEERS_PROMPT.format(
        company_name=company_name,
        category_name=category_name,
        subcategory_name=subcategory_name,
        country=country,
        existing_list=existing_list,
    )

    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
    response = _llm_client().chat.completions.create(
        model=model,
        max_tokens=2000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = (response.choices[0].message.content or "").strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        peers = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("find_peers: could not parse JSON response: %s", raw[:200])
        return {"error": "Could not parse peer suggestions", "raw": raw}

    return {"peers": peers, "count": len(peers)}


# --------------------------------------------------------------------------- #
# Dispatcher                                                                   #
# --------------------------------------------------------------------------- #

_REGISTRY = {
    "search_companies": _search_companies,
    "get_company": _get_company,
    "create_company": _create_company,
    "update_company": _update_company,
    "verify_company": _verify_company,
    "list_pending": _list_pending,
    "search_taxonomy": _search_taxonomy,
    "create_taxonomy_entry": _create_taxonomy_entry,
    "find_peers": _find_peers,
}


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name, return JSON string result."""
    fn = _REGISTRY.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**args)
        return json.dumps(result, default=str)
    except Exception as exc:
        log.exception("Tool '%s' raised an exception", name)
        return json.dumps({"error": str(exc)})
