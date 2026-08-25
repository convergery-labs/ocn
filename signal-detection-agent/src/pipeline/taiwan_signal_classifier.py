"""Deterministic classification for taiwan_market_signal items (TWSE/TPEx
revenue and material announcements read from news-retrieval).

Moved here from news-retrieval per the decision that news-retrieval stays
fetch/dedup-only, uniformly across every domain - no source type computes a
signal or translates text there. Ranking and clause lookup are pure
arithmetic/lookup (no model call, matching the original design intent);
translation reuses this service's own OpenAI-compatible client rather than
introducing a second LLM provider.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.request import Request, urlopen

import config

logger = logging.getLogger(__name__)

_REVENUE_RANK_TOP_N = 3

# Starter table built from clause codes observed live against the TWSE/TPEx
# material-announcements feed. A real table should be built from ~2 weeks
# of historical data across all tracked tickers (expect ~20-30 distinct
# codes) - this is intentionally a small starting point, not a claim of
# completeness. Unrecognized codes default to WEAK rather than guessing a
# category for a code never observed.
_CLAUSE_CODE_TABLE: dict[str, str] = {
    "第51款": "HIGH",   # observed live: treasury-stock buyback execution - capital action
    "第14款": "WEAK",   # observed live: subsidiary dividend distribution - substantive but once-removed
    "第12款": "NOISE",  # observed live: investor-conference attendance notice - admin
    "第53款": "NOISE",  # observed live: company name change - admin
}
_CLAUSE_CODE_DEFAULT = "WEAK"

# Which metadata/top-level fields need translation, per source_category.
# company_name is deliberately NOT translated here - news-retrieval already
# sets metadata.translated_company_name directly from its own known-correct
# TAIWAN_TICKER_UNIVERSE list (seed.py), because LLM translation of bare
# 2-4 character Taiwan company names was confirmed live to produce serious
# errors (e.g. 2383 Elite Material mistranslated as "Taiwan Semiconductor
# Manufacturing Company"; 8210 Chenbro translated literally as "Diligence
# and sincerity"). Numeric fields never need translation.
#
# GDELT's own API response (mode=artlist) has no body/snippet field - but
# news-retrieval's _fetch_gdelt does NOT rely on GDELT for body text: it
# separately fetches each surviving article's real webpage via Trafilatura
# and sets article["body"] from the extracted page text (confirmed live -
# a real SETN article yielded 1000+ characters of genuine body text this
# way). So GDELT articles that survive Stage A DO have a real body to
# translate, same as material announcements - both title and body are
# translated here.
_TRANSLATION_FIELDS: dict[str, dict[str, str]] = {
    "mops_revenue": {
        "metadata.industry": "translated_industry",
        "metadata.remarks": "translated_remarks",
    },
    "mops_material": {
        "summary": "translated_summary",
        "body": "translated_body",
    },
    "gdelt": {
        "title": "translated_title",
        "body": "translated_body",
    },
}


def _get_nested(article: dict, path: str):
    """Read 'metadata.company_name' or a plain top-level key like 'title'."""
    if path.startswith("metadata."):
        return (article.get("metadata") or {}).get(path.split(".", 1)[1])
    return article.get(path)


def _translate_one(
    text: str, model: str, api_key: str, base_url: str, timeout: int,
) -> str | None:
    """Translate one short native-language string to English via a raw
    HTTP call to the OpenAI-compatible endpoint - matching this service's
    existing pattern in pipeline/classifier.py (urllib.request, not the
    openai SDK, which isn't a dependency here). Returns None on failure or
    blank input - callers must fall back to the native text, never treat
    None as an empty translation.
    """
    if not text or not text.strip():
        return None
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the following text to English. Translate"
                    " exactly what is written - do not add, infer,"
                    " summarize, embellish, or explain anything that is"
                    " not present in the source text. Do not correct,"
                    " complete, or interpret the source text; if it is"
                    " incomplete or ambiguous, translate it as literally"
                    " and faithfully as possible rather than guessing"
                    " the intended meaning."
                    " Output ONLY the translation itself, with no notes,"
                    " no quotation marks, and no explanation."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        req = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        translated = (content or "").strip()
        return translated or None
    except Exception as exc:
        logger.warning("[TAIWAN_TRANSLATE] failed for text=%r: %s", text[:60], exc)
        return None


def rank_revenue_by_yoy(articles: list[dict[str, Any]]) -> None:
    """Rank revenue articles by YoY% within their reporting period and tag
    each with a HIGH/WEAK classification, in place.

    A fixed percentage cutoff doesn't work for this universe - these
    companies routinely post 50-300% YoY as their normal run rate, so a
    flat threshold would flag nearly everyone, nearly every month. Ranking
    is self-calibrating for the top end and guarantees a stable number of
    top-N HIGH signals per period. Never NOISE - a monthly statutory filing
    is never noise by definition.

    The bottom end is NOT rank-based: in a month where every tracked
    company grew, the slowest grower is still just a normal month, not a
    signal. HIGH at the bottom only fires on actual negative YoY - a real
    contraction, not merely "smallest gain in a good month." This means
    the number of HIGH signals per period varies (some months more, some
    fewer, some none at the bottom) - that's correct, not a bug to force
    back to a fixed count.

    Ranks ALL revenue articles passed in together, per period - callers
    are responsible for passing in every article for a given day's
    classification pass so "top 3 of 20" is meaningful, not "top 3 of
    whatever happened to be in this one batch."

    Adds to each qualifying article's ``metadata``, in place:
        - ``revenue_rank_signal``: "HIGH" or "WEAK"
        - ``revenue_yoy_rank``: 1-indexed rank by YoY% within its period
        - ``revenue_rank_reason``: e.g. "rank_2_of_20_yoy"
    """
    by_period: dict[str, list[dict]] = {}
    for a in articles:
        meta = a.get("metadata") or {}
        if meta.get("source_category") != "mops_revenue":
            continue
        if meta.get("yoy_pct") is None:
            continue
        by_period.setdefault(meta["period_gregorian"], []).append(a)

    for period, period_articles in by_period.items():
        ranked = sorted(
            period_articles, key=lambda a: a["metadata"]["yoy_pct"], reverse=True,
        )
        n = len(ranked)
        for i, article in enumerate(ranked):
            rank = i + 1
            yoy_pct = article["metadata"]["yoy_pct"]
            is_top = rank <= _REVENUE_RANK_TOP_N
            is_shrinking = yoy_pct < 0
            signal = "HIGH" if (is_top or is_shrinking) else "WEAK"
            article["metadata"]["revenue_rank_signal"] = signal
            article["metadata"]["revenue_yoy_rank"] = rank
            article["metadata"]["revenue_rank_reason"] = f"rank_{rank}_of_{n}_yoy"
        logger.info(
            "[TAIWAN_RANK] period=%s ranked=%d high=%d",
            period, n,
            sum(1 for a in ranked if a["metadata"]["revenue_rank_signal"] == "HIGH"),
        )


def classify_material_announcements(articles: list[dict[str, Any]]) -> None:
    """Classify material-announcement articles by disclosure clause code, in
    place. Only touches articles with metadata.source_category ==
    "mops_material". Adds ``announcement_materiality_signal`` (HIGH/WEAK/
    NOISE) and ``announcement_materiality_reason`` to metadata.
    """
    counts = {"HIGH": 0, "WEAK": 0, "NOISE": 0}
    for a in articles:
        meta = a.get("metadata") or {}
        if meta.get("source_category") != "mops_material":
            continue
        code = meta.get("disclosure_clause_code")
        signal = _CLAUSE_CODE_TABLE.get(code, _CLAUSE_CODE_DEFAULT)
        a["metadata"]["announcement_materiality_signal"] = signal
        a["metadata"]["announcement_materiality_reason"] = (
            f"clause_{code}" if code in _CLAUSE_CODE_TABLE else "unrecognized_clause"
        )
        counts[signal] += 1
    if any(counts.values()):
        logger.info(
            "[TAIWAN_MATERIALITY] classified high=%d weak=%d noise=%d",
            counts["HIGH"], counts["WEAK"], counts["NOISE"],
        )


def translate_taiwan_articles(
    articles: list[dict[str, Any]],
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> None:
    """Translate the fields that need it, per source_category, in place.

    Only touches articles whose metadata.source_category has an entry in
    _TRANSLATION_FIELDS. Native-language fields are never overwritten;
    translated values are added as new metadata fields (e.g.
    metadata.translated_title). Failed translations leave the
    translated_* field absent rather than set to None/empty.

    Defaults to OPENAI_MODEL_V2 (the cheaper refine-pass model, e.g.
    gpt-4o-mini per infra/CLAUDE.md), not the base OPENAI_MODEL - this is a
    mechanical translation task, not a judgment call, so it doesn't need
    the stronger/pricier base classification model.
    """
    model = model or config.OPENAI_MODEL_V2
    api_key = api_key or config.OPENAI_API_KEY
    base_url = base_url or config.OPENAI_BASE_URL
    timeout = timeout or config.OPENAI_TIMEOUT

    to_translate: list[tuple[dict, str, str]] = []  # (article, source_path, dest_field)
    for a in articles:
        category = (a.get("metadata") or {}).get("source_category")
        field_map = _TRANSLATION_FIELDS.get(category)
        if not field_map:
            continue
        for source_path, dest_field in field_map.items():
            if _get_nested(a, source_path):
                to_translate.append((a, source_path, dest_field))

    translated_count = 0
    for article, source_path, dest_field in to_translate:
        text = _get_nested(article, source_path)
        result = _translate_one(text, model, api_key, base_url, timeout)
        if result is not None:
            article["metadata"][dest_field] = result
            translated_count += 1

    if to_translate:
        logger.info(
            "[TAIWAN_TRANSLATE] %d/%d field(s) translated successfully",
            translated_count, len(to_translate),
        )


# Path 3, Stage B - the one genuine model call in this whole module.
# Returns HIGH/WEAK plus, for HIGH, which of the prompt's own criteria
# triggered it - so signal_reason carries real information instead of a
# fixed "gdelt_relevance_high" string. Still one call, no retry - per the
# original spec's own cost design. Runs only on GDELT articles that already
# survived news-retrieval's Stage A (domain allowlist + company-name-in-title
# check) and title-similarity dedup, so this is judging genuine candidates,
# not raw noise.
_GDELT_RELEVANCE_SYSTEM_PROMPT = """You classify Taiwan stock headlines as HIGH or WEAK.

HIGH means the headline states a specific, checkable fact:
- numeric_fact: a number (revenue, shipments, capacity, price, percentage)
- named_customer_or_contract: a named customer, partner, or contract
- capacity_or_pricing_change: a capacity, production, or pricing change
- company_guidance_change: a guidance or forecast change from the company itself
- regulatory_action: a regulatory or export-control action naming the company

WEAK means anything else:
- analyst opinion, ratings, price targets
- outlook, sentiment, or expectation with no figure
- the company mentioned in passing in a market roundup
- a story mainly about a different company

The source matters. A fact stated by the company or a
regulator is HIGH. The same fact predicted by an analyst
is WEAK.

If unsure, answer WEAK.

Answer with exactly one line, two words separated by a space:
- if HIGH, the category then HIGH, e.g. "numeric_fact HIGH"
- if WEAK, just "WEAK"
"""

# No numeric confidence - the model is forced into a single-word HIGH/WEAK
# call and never asked for (or gives) a real confidence value, so a fixed
# number here would be fabricated precision. NULL means "not measured",
# distinct from the deterministic paths' 1.0 (which reflects certainty in
# an actual computation, not a guess).
_GDELT_RELEVANCE_SCORE = None
_GDELT_HIGH_CATEGORIES = frozenset({
    "numeric_fact",
    "named_customer_or_contract",
    "capacity_or_pricing_change",
    "company_guidance_change",
    "regulatory_action",
})


def _classify_gdelt_relevance(
    company_name: str, title: str, model: str, api_key: str, base_url: str, timeout: int,
) -> tuple[str, str]:
    """HIGH/WEAK classification for a single GDELT article, plus a reason.

    Returns (signal, reason). For HIGH, reason is one of
    _GDELT_HIGH_CATEGORIES; for WEAK, reason is always "gdelt_relevance_weak".

    No retry - per the spec's own reasoning, a repair attempt costs more
    than the value of one extra try on a call this cheap, and failing
    toward WEAK (hiding a possible signal) is the safer direction than
    failing toward HIGH (surfacing noise as if it were checked).

    Any response that isn't a recognized "<category> HIGH" pair is treated
    as WEAK - a model that hedges, explains, or returns something else has
    not given a usable answer, and guessing which way it leaned is worse
    than the safe default.
    """
    user_prompt = f"Company: {company_name}\nHeadline: {title}"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 10,
        "messages": [
            {"role": "system", "content": _GDELT_RELEVANCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        req = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parts = (content or "").strip().split()
        if len(parts) == 2 and parts[1].upper() == "HIGH" and parts[0].lower() in _GDELT_HIGH_CATEGORIES:
            return "HIGH", parts[0].lower()
        return "WEAK", "gdelt_relevance_weak"
    except Exception as exc:
        logger.warning("[GDELT_RELEVANCE] classification failed, defaulting to WEAK: %s", exc)
        return "WEAK", "gdelt_relevance_weak"


def classify_gdelt_articles(
    articles: list[dict[str, Any]], model: str | None = None,
) -> list[dict[str, Any]]:
    """Classify GDELT articles (source_category == "gdelt") one at a time -
    unlike revenue ranking, this needs no batch context, so it's a simple
    per-article loop here; concurrency (if needed) belongs in the caller,
    same as the existing news/geopolitical classifiers in controllers/run.py.

    Only touches articles that already have a translated_title (i.e.
    survived Stage A + dedup + translation) - an article with no
    translated_title has nothing usable to classify.

    source_id is the article's own URL - GDELT articles have no natural
    ticker+period/ticker+timestamp key the way TWSE/TPEx rows do (each is
    a distinct story, not a recurring filing), and news-retrieval has
    already deduplicated by URL (exact match) and by title similarity
    before this point, so the URL is a reliable identifier by the time it
    reaches this function.
    """
    model = model or config.OPENAI_MODEL_V2
    api_key = config.OPENAI_API_KEY
    base_url = config.OPENAI_BASE_URL
    timeout = config.OPENAI_TIMEOUT

    results = []
    for a in articles:
        meta = a.get("metadata") or {}
        if meta.get("source_category") != "gdelt":
            continue
        translated_title = meta.get("translated_title")
        if not translated_title:
            continue  # nothing usable to classify without a translated title

        company_name = meta.get("translated_company_name") or meta.get("ticker") or ""
        signal, reason = _classify_gdelt_relevance(
            company_name, translated_title, model, api_key, base_url, timeout,
        )
        results.append({
            "article": a,
            "result": {
                "signal": signal,
                "signal_score": _GDELT_RELEVANCE_SCORE,
                "source_id": a.get("url"),
                "reason": reason,
                "metadata": meta,
            },
        })
    return results


def classify_taiwan_signal_batch(
    articles: list[dict[str, Any]], model: str | None = None,
) -> list[dict[str, Any]]:
    """Run the full taiwan_market_signal classification pass on a batch of
    articles read from news-retrieval: rank revenue, classify material
    announcements, translate whatever needs it - then build one result dict
    per article for insert_taiwan_signal_classification.

    Must be called with ALL of a period's/day's articles together, not
    per-article - ranking needs the full set to be meaningful. This is why
    this is a batch function, unlike the per-article classifiers in
    dispatch.py's registry (rank_revenue_by_yoy's "top 3 of 20" requirement
    doesn't fit a one-item-at-a-time interface). GDELT articles don't need
    batch context (each is classified independently, per Stage B), but are
    included here too so one call handles the whole domain's classification.
    """
    rank_revenue_by_yoy(articles)
    classify_material_announcements(articles)
    translate_taiwan_articles(articles, model=model)

    results = []
    for a in articles:
        meta = a.get("metadata") or {}
        category = meta.get("source_category")
        if category == "mops_revenue":
            signal = meta.get("revenue_rank_signal")
            reason = meta.get("revenue_rank_reason")
            source_id = f"{meta.get('ticker')}-{meta.get('period_gregorian')}"
        elif category == "mops_material":
            signal = meta.get("announcement_materiality_signal")
            reason = meta.get("announcement_materiality_reason")
            source_id = (
                f"{meta.get('ticker')}-{meta.get('statement_date')}"
                f"-{meta.get('statement_time')}"
            )
        else:
            continue  # gdelt handled separately below (needs a model call
            # per article, not a metadata lookup) - and any other/unknown
            # source_category is correctly skipped here too.

        if signal is None:
            continue  # e.g. revenue row with no yoy_pct, never ranked

        results.append({
            "article": a,
            "result": {
                # Both mops_revenue (rank) and mops_material (clause-code
                # lookup) are deterministic rules, not scored judgments -
                # null is more honest than a fabricated 1.0, and each
                # already has a self-describing reason/rank field to sort
                # or filter on instead. signal_score is reserved for a
                # path where a model genuinely produces one (gdelt).
                "signal": signal,
                "signal_score": None,
                "source_id": source_id,
                "reason": reason,
                "metadata": meta,
            },
        })

    results.extend(classify_gdelt_articles(articles, model=model))
    return results
