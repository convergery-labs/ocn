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

DUPLICATE_THRESHOLD = 0.65  # trgm score for pure name similarity (word-overlap handles lower-scoring variants)
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


def _word_overlap(a: str, b: str) -> bool:
    """Return True if one name's meaningful words are all contained in the other.

    Catches pairs like 'Zenlayer' / 'Zenlayer Asia', 'Proxim Inc' / 'Proxim Wireless',
    'Runwayml' / 'Runway ML' that score below DUPLICATE_THRESHOLD on trgm.
    """
    _STOP = {"inc", "llc", "ltd", "group", "holdings", "technologies", "technology",
             "corporation", "corp", "co", "company", "gmbh", "ag", "sa", "plc", "bv", "nv",
             "the", "and", "of", "for", "a", "an", "solutions", "systems", "services",
             "networks", "international", "global",
             "adr", "ads", "shs", "ord"}

    def _words(s: str) -> set[str]:
        import re
        # Normalise concatenated names like "runwayml" → "runway ml" via camelCase/lowercase split
        s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
        tokens = re.split(r"[\s\-/&.,()]+", s.lower())
        return {t for t in tokens if t and t not in _STOP and len(t) > 1}

    def _strip_concat(s: str) -> str:
        """Remove all spaces/punctuation for concatenation comparison."""
        import re
        return re.sub(r"[\s\-/&.,()]+", "", s.lower())

    # Direct concatenation match: "runwayml" == "runway ml" stripped
    if _strip_concat(a) == _strip_concat(b):
        return True

    words_a = _words(a)
    words_b = _words(b)
    if not words_a or not words_b:
        return False
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    # All words of the shorter name appear in the longer name
    return shorter.issubset(longer)


def _sig_words(name: str) -> list[str]:
    """Return significant tokens from a company name (strips stopwords, punctuation)."""
    import re as _re
    _SW = {"inc", "llc", "ltd", "group", "holdings", "technologies", "technology",
           "corporation", "corp", "co", "company", "gmbh", "ag", "sa", "plc", "bv", "nv",
           "the", "and", "of", "for", "a", "an", "solutions", "systems", "services",
           "networks", "international", "global",
           "adr", "ads", "shs", "ord"}  # share-class suffixes — not part of company identity
    return [t for t in _re.split(r"[\s\-/&.,()]+", name.lower()) if t and t not in _SW and len(t) > 1]


def _is_duplicate(company_name: str, ticker: str) -> bool:
    """Return True if company is already in the universe."""
    import re as _re

    proposed_sig = _sig_words(company_name)

    # --- Name check 1: full name fuzzy + word-overlap ---
    results = company_model.search_companies(company_name, limit=10)
    for r in results:
        score = r.get("match_score", 0)
        existing_sig = _sig_words(r["company_name"])
        overlap = _word_overlap(company_name, r["company_name"])

        if score >= DUPLICATE_THRESHOLD:
            if len(existing_sig) >= len(proposed_sig):
                # High-confidence same-length match only blocks when names are
                # actually overlapping OR score is very high (≥0.85 catches "TSMC"/"TSM").
                # Avoids "Leonardo AI" being blocked by "Leonardo DRS" at 0.75 (shared first
                # word, but genuinely different companies).
                if overlap or score >= 0.85:
                    return True
            else:
                # Existing is shorter (e.g. "Relativity" vs "Relativity Media") —
                # require very high confidence to block.
                if score >= 0.80:
                    return True

        # Word-overlap fallback for variants like "Zenlayer" / "Zenlayer Asia",
        # "Proxim Inc" / "Proxim Wireless" that score below threshold.
        # Guard: only fire when the existing entry is at least as long as the proposed name.
        # This prevents "Tencent" (1 word) from blocking "Tencent Music" (2 words).
        if overlap and len(existing_sig) >= len(proposed_sig) and score >= 0.40:
            return True

    # --- Name check 2: search each significant token individually ---
    # Catches "Tencent Holdings" when only "Tencent" is in DB,
    # "Eoptolink Technology Corporation" when "Eoptolink" is in DB.
    # Guard: only fire when the existing entry has >= as many significant words as the proposed name.
    # Prevents "Nokia" (1 word) from blocking "Nokia Solutions" (2 words).
    _STOP_SET = {"inc", "llc", "ltd", "group", "holdings", "technologies", "technology",
                 "corporation", "corp", "co", "company", "gmbh", "ag", "sa",
                 "plc", "bv", "nv", "the", "and", "of", "for", "a", "an",
                 "adr", "ads", "shs", "ord", "international", "global", "solutions",
                 "systems", "services", "networks"}
    tokens = [
        t for t in _re.split(r"[\s\-/&.,()]+", company_name.lower())
        if t and t not in _STOP_SET and len(t) > 3
    ]
    for token in tokens:
        token_results = company_model.search_companies(token, limit=5)
        for r in token_results:
            if r.get("match_score", 0) >= 0.85 and _word_overlap(company_name, r["company_name"]):
                existing_sig = _sig_words(r["company_name"])
                if len(existing_sig) >= len(proposed_sig):
                    return True

    # --- Ticker check: case-insensitive, base-ticker prefix match ---
    # "688256" matches "688256.SS"; "AAPL" matches "aapl".
    # Uses a direct LIKE query to handle exchange-suffix variants that exact match misses.
    if ticker and ticker.lower() not in ("private", ""):
        ticker_upper = ticker.upper()
        base_ticker = ticker_upper.split(".")[0]
        if base_ticker:
            from db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "SELECT 1 FROM universe_companies"
                    " WHERE UPPER(ticker) = :full"
                    "    OR UPPER(ticker) LIKE :prefix"
                    " LIMIT 1",
                    {"full": ticker_upper, "prefix": base_ticker + ".%"},
                )
                if cur.fetchone():
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
