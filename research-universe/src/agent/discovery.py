"""Universe discovery job - scans categories and proposes missing companies."""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from openai import OpenAI

import models.company as company_model
import models.scan_job as scan_job_model
import models.taxonomy as taxonomy_model
from agent.prompts import DISCOVERY_PROMPT
from taxonomy_rules import get_category_definition, get_valid_subcategories
from agent.tools import _resolve_taxonomy_ids

log = logging.getLogger(__name__)

DUPLICATE_THRESHOLD = 0.7  # match_score above which we consider a company already present
CONCURRENCY = 3  # max categories processed in parallel


def _llm_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


def _call_discovery_llm(
    category_name: str,
    existing_names: list[str],
    valid_subcategories: list[str],
) -> list[dict[str, Any]]:
    """Ask Claude to find companies missing from this category."""
    existing_list = (
        "\n".join(f"- {n}" for n in existing_names) if existing_names else "None yet"
    )
    subcategory_list = (
        "\n".join(f"- {s}" for s in valid_subcategories) if valid_subcategories else "None defined"
    )
    category_definition = get_category_definition(category_name)
    prompt = DISCOVERY_PROMPT.format(
        category_name=category_name,
        category_definition=category_definition,
        valid_subcategories=subcategory_list,
        existing_list=existing_list,
    )
    model = os.environ.get("DISCOVERY_MODEL", "anthropic/claude-haiku-4.5")
    response = _llm_client().chat.completions.create(
        model=model,
        max_tokens=4096,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = (response.choices[0].message.content or "").strip()
    log.info("discovery: LLM response length=%d finish_reason=%s",
             len(raw), response.choices[0].finish_reason)
    log.info("discovery: first 500 chars: %s", raw[:500])

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    log.info("discovery: after strip, length=%d first 200: %s", len(raw), raw[:200])

    # Find the start of the JSON array - skip any preamble text
    array_start = raw.find("[")
    if array_start == -1:
        log.warning("discovery: no JSON array found for '%s'", category_name)
        return []
    raw = raw[array_start:]

    try:
        # raw_decode takes only the first complete JSON value, ignoring trailing content
        parsed, _ = json.JSONDecoder().raw_decode(raw)
        result = parsed if isinstance(parsed, list) else []
        log.info("discovery: parsed %d companies", len(result))
        return result
    except json.JSONDecodeError as exc:
        log.warning("discovery: JSON parse error for '%s': %s | raw start: %s",
                    category_name, exc, raw[:200])
        return []


def _is_duplicate(company_name: str, ticker: str) -> bool:
    """Return True if company is already in the universe."""
    # Check by name
    results = company_model.search_companies(company_name, limit=3)
    for r in results:
        if r.get("match_score", 0) >= DUPLICATE_THRESHOLD:
            return True
    # Check by ticker (exact)
    if ticker and ticker.lower() != "private":
        ticker_results = company_model.search_companies(ticker, limit=1)
        if ticker_results and ticker_results[0].get("match_score", 0) >= 0.95:
            return True
    return False


def _process_category(
    job_id: str,
    category_id: int,
    category_name: str,
    triggered_by: str,
) -> None:
    """Run discovery for one category and update the job record."""
    log.info("[scan %s] Processing category: %s", job_id, category_name)

    # Get existing companies so Claude knows what to skip
    existing = company_model.get_companies_by_category_id(category_id)
    existing_names = [c["company_name"] for c in existing]
    log.info("[scan %s] %d existing companies in category", job_id, len(existing_names))

    # Fetch valid subcategories from taxonomy_rules (single source of truth)
    valid_subcategories = get_valid_subcategories(category_id)
    log.info("[scan %s] %d valid subcategories for category", job_id, len(valid_subcategories))

    # Ask Claude for missing companies
    proposals = _call_discovery_llm(category_name, existing_names, valid_subcategories)
    log.info("[scan %s] Claude proposed %d companies", job_id, len(proposals))

    proposed_count = 0
    skipped_count = 0

    for p in proposals:
        name = (p.get("company_name") or "").strip()
        ticker = (p.get("ticker") or "Private").strip()
        if not name:
            continue

        # Duplicate check
        if _is_duplicate(name, ticker):
            log.debug("[scan %s] Duplicate skipped: %s", job_id, name)
            skipped_count += 1
            continue

        # If Claude flagged this company as not belonging to this category, skip it
        raw_subcategory = p.get("subcategory_name")
        if raw_subcategory is None:
            suggested = p.get("suggested_category", "unknown")
            log.info(
                "[scan %s] Skipping '%s' — does not belong in '%s' (suggested: %s)",
                job_id, name, category_name, suggested,
            )
            skipped_count += 1
            continue

        # Resolve subcategory — must match an existing taxonomy entry
        subcategory_name = str(raw_subcategory).strip()
        cat_ids, sub_ids, errors = _resolve_taxonomy_ids(
            [category_name],
            [subcategory_name] if subcategory_name else [],
        )

        if not cat_ids:
            log.warning("[scan %s] Could not resolve category for '%s'", job_id, name)
            skipped_count += 1
            continue

        # If subcategory doesn't match any existing entry, skip rather than invent
        if subcategory_name and not sub_ids:
            log.warning(
                "[scan %s] Skipping '%s' — subcategory '%s' not in taxonomy",
                job_id, name, subcategory_name,
            )
            skipped_count += 1
            continue

        try:
            company_model.create_company({
                "company_name": name,
                "ticker": ticker,
                "market": p.get("market", "International"),
                "country": p.get("country", ""),
                "website": p.get("website", ""),
                "category_ids": cat_ids,
                "subcategory_ids": sub_ids,
                "multi_category_reason": None,
                "added_by": triggered_by,
            })
            proposed_count += 1
            log.info("[scan %s] Added: %s (%s)", job_id, name, ticker)
        except Exception as exc:
            log.warning("[scan %s] Failed to add '%s': %s", job_id, name, exc)
            skipped_count += 1

    scan_job_model.append_category_result(
        job_id, category_id, category_name, proposed_count, skipped_count
    )
    taxonomy_model.mark_category_enriched(category_id)
    log.info(
        "[scan %s] Category done - proposed=%d skipped=%d",
        job_id, proposed_count, skipped_count,
    )


def run_scan(job_id: str, category_ids: list[int], triggered_by: str) -> None:
    """Background entry point - process categories with bounded concurrency."""
    log.info(
        "[scan %s] Starting discovery job (%d categories, concurrency=%d)",
        job_id, len(category_ids), CONCURRENCY,
    )

    from db import get_db

    # Resolve category IDs → (id, name) pairs up-front
    categories: list[tuple[int, str]] = []
    for cat_id in category_ids:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT id, name FROM universe_taxonomy WHERE id = :id AND type = 'category'",
                {"id": cat_id},
            )
            row = cur.fetchone()
        if not row:
            log.warning("[scan %s] Category id %d not found - skipping", job_id, cat_id)
            scan_job_model.append_category_result(
                job_id, cat_id, f"id={cat_id}", 0, 0, status="skipped"
            )
            continue
        categories.append((row["id"], row["name"]))

    any_failed = False
    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {
                pool.submit(_process_category, job_id, cat_id, cat_name, triggered_by): (cat_id, cat_name)
                for cat_id, cat_name in categories
            }
            for future in as_completed(futures):
                cat_id, cat_name = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    log.exception("[scan %s] Category '%s' failed: %s", job_id, cat_name, exc)
                    scan_job_model.append_category_result(
                        job_id, cat_id, cat_name, 0, 0, status="failed"
                    )
                    any_failed = True

        final_status = "failed" if any_failed else "completed"
        scan_job_model.mark_complete(job_id, final_status)
        log.info("[scan %s] Discovery job %s", job_id, final_status)
    except Exception as exc:
        log.exception("[scan %s] Discovery job failed: %s", job_id, exc)
        scan_job_model.mark_complete(job_id, "failed")
