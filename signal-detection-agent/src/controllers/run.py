"""Orchestration - fetch articles from news-retrieval, classify via LLM, persist."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import config
from adapters.news_client import (
    NewsRetrievalError,
    fetch_latest_run,
    get_article,
    get_run_articles,
    list_completed_runs,
    poll_run_until_done,
    trigger_run,
)
from models.geopolitical_signal_companies import (
    get_companies_for_name_matching,
    get_tickers_for_categories,
)
from models.jobs import (
    count_geopolitical_signal_stage_b_calls_today,
    count_geopolitical_signal_stage_c_calls_today,
    create_job,
    get_completed_job_for_run,
    get_existing_geopolitical_signal_article_ids,
    get_existing_taiwan_source_ids,
    get_taiwan_revenue_rows_for_periods,
    get_ungraded_geopolitical_signal_tagged_articles,
    get_untagged_geopolitical_signal_high_articles,
    get_waiting_geopolitical_signal_articles,
    insert_geopolitical_signal_classification,
    insert_taiwan_signal_classification,
    update_geopolitical_signal_classification,
    update_geopolitical_signal_stage_c_tags,
    update_geopolitical_signal_stage_d_grade,
    update_job_status,
    update_taiwan_revenue_rank,
)
from pipeline.classifier import has_usable_body
from pipeline.dispatch import get_domain_config, known_domains
from pipeline.geopolitical_signal_classifier import classify_geopolitical_signal_stage_a
from pipeline.geopolitical_signal_layer1 import find_direct_company_matches
from pipeline.geopolitical_signal_layer2 import classify_geopolitical_signal_tags
from pipeline.geopolitical_signal_overrides import apply_overrides
from pipeline.geopolitical_signal_stage_b import (
    classify_geopolitical_signal_headline,
    load_stage_b_prompt,
)
from pipeline.geopolitical_signal_stage_d import grade_geopolitical_signal_article
from pipeline.taiwan_signal_classifier import classify_taiwan_signal_batch

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.CLASSIFY_CONCURRENCY)


async def resolve_news_run_id(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
) -> int:
    """Resolve which news-retrieval run to classify against."""
    if run_id is not None:
        await poll_run_until_done(run_id)
        return run_id
    if use_latest_run:
        existing = await fetch_latest_run(domain)
        if existing is not None:
            return existing
    resolved = await trigger_run(domain, days_back)
    await poll_run_until_done(resolved)
    return resolved


async def submit_run(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
    force: bool,
) -> tuple[int, int, bool]:
    """Resolve news_run_id, check cache, create job if needed.

    Returns (job_id, news_run_id, cached) where cached=True means an existing
    completed job was found and no new classification run is needed.
    """
    news_run_id = await resolve_news_run_id(domain, run_id, days_back, use_latest_run)
    if not force:
        existing = get_completed_job_for_run(news_run_id)
        if existing:
            return int(existing["id"]), news_run_id, True
    job_id = create_job(domain=domain, news_run_id=news_run_id)
    return job_id, news_run_id, False


def _is_period_in_active_filing_window(period_gregorian: str) -> bool:
    """A revenue period is only re-ranked against newly-arrived stragglers
    while it's the current or previous calendar month (UTC) - TWSE/TPEx
    monthly filings land within roughly the first 2-3 weeks after
    month-end, so anything older than that is treated as closed: no more
    re-ranking, no more update_taiwan_revenue_rank calls for it, ever.

    This bounds how long a stored row can change after the fact to a
    known, short window, rather than every row being mutable forever -
    the tradeoff decided over rank correctness vs. mutable history: fix
    the field size while filings are still trickling in for a period, but
    don't reopen a period that's long since settled.
    """
    try:
        period = datetime.strptime(period_gregorian, "%Y-%m").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    today = datetime.now(timezone.utc)
    months_diff = (today.year - period.year) * 12 + (today.month - period.month)
    return 0 <= months_diff <= 1


async def run_taiwan_signal_classification(job_id: int, from_date: str, to_date: str) -> None:
    """Classify taiwan_market_signal items across ALL of news-retrieval's
    completed runs in [from_date, to_date] - not just the latest run.

    news-retrieval polls this domain every 30 minutes, so a single day can
    have ~30 separate completed runs; fetch_latest_run/get_run_articles
    (built for the single-run news/sec_filing paths) would
    silently see only the most recent one. This function instead lists
    every completed run in the window and pools their articles before
    classifying, so a twice-daily pass sees the full day's fetched data.

    Only classifies items not already classified - checked via
    get_existing_taiwan_source_ids against the (ticker+period or
    ticker+timestamp) source_id classify_taiwan_signal_batch derives, not
    against article id, since the same underlying fact can legitimately
    appear in multiple news-retrieval runs (re-fetched, not yet superseded)
    and must still only be classified once.

    Revenue ranking is period-scoped, not just today's-batch-scoped: for
    every mops_revenue period present in today's pooled articles, this
    also pulls the already-stored rows for that period (if it's still in
    the active filing window - see _is_period_in_active_filing_window) as
    read-only ranking context, so a late-arriving filing gets ranked
    against the true known field instead of just itself. Any already-
    stored row whose rank/signal changes as a result is updated in place
    via update_taiwan_revenue_rank - see that function and
    rank_revenue_by_yoy's docstrings for why this is the one place
    taiwan_market_signal data is allowed to change after insert.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.TAIWAN_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch taiwan_market_signal articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    revenue_periods = {
        a["metadata"]["period_gregorian"]
        for a in all_articles
        if (a.get("metadata") or {}).get("source_category") == "mops_revenue"
        and a["metadata"].get("period_gregorian")
    }
    active_periods = [p for p in revenue_periods if _is_period_in_active_filing_window(p)]
    revenue_context = get_taiwan_revenue_rows_for_periods(active_periods)
    # get_taiwan_revenue_rows_for_periods returns {id, source_id, metadata}
    # rows shaped for the DB, not news-retrieval's article shape -
    # rank_revenue_by_yoy only ever reads/writes article["metadata"], so a
    # thin wrapper is enough; "id" being present is how it tells a context
    # row apart from a freshly-fetched article (see its docstring).
    context_wrapped = [
        {"id": r["id"], "source_id": r["source_id"], "metadata": r["metadata"]}
        for r in revenue_context
    ]

    # Rank/classify/translate needs the FULL pooled set together (ranking
    # spans all tickers for a period), so this runs before the
    # already-classified filter below - filtering first would rank against
    # a partial set and produce wrong ranks, same reasoning as
    # news-retrieval's original per-poll ranking gap.
    classified, changed_context = classify_taiwan_signal_batch(
        all_articles, revenue_context=context_wrapped,
    )

    candidate_source_ids = [c["result"]["source_id"] for c in classified]
    already_done = get_existing_taiwan_source_ids(candidate_source_ids)
    to_insert = [c for c in classified if c["result"]["source_id"] not in already_done]

    update_job_status(job_id, "running", article_count=len(to_insert))

    inserted = 0
    for c in to_insert:
        try:
            insert_taiwan_signal_classification(job_id, c["article"], c["result"])
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert taiwan_market_signal classification for"
                " source_id=%s (job %d)",
                c["result"]["source_id"], job_id,
            )

    revised = 0
    for row in changed_context:
        meta = row["metadata"]
        try:
            update_taiwan_revenue_rank(
                row["source_id"],
                revenue_rank_signal=meta["revenue_rank_signal"],
                signal_reason=meta["revenue_rank_reason"],
                metadata=meta,
            )
            revised += 1
        except Exception:
            logger.exception(
                "Failed to update revised taiwan_market_signal rank for"
                " source_id=%s (job %d)",
                row["source_id"], job_id,
            )

    logger.info(
        "[TAIWAN_SIGNAL] job=%d runs=%d pooled_articles=%d classified=%d"
        " already_done=%d inserted=%d revenue_context=%d revised=%d",
        job_id, len(run_ids), len(all_articles), len(classified),
        len(already_done), inserted, len(context_wrapped), revised,
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


async def run_geopolitical_signal_stage_a(job_id: int, from_date: str, to_date: str) -> None:
    """Stage A only: pool all of news-retrieval's completed geopolitical_news
    runs in [from_date, to_date], apply the free rule-based filters, persist.

    Pools across every completed run in the window rather than just the
    latest (same reasoning as run_taiwan_signal_classification) - a single
    run isn't guaranteed to be "today's everything" for this domain either.

    Only classifies articles not already classified - checked via
    get_existing_geopolitical_signal_article_ids against article_id
    (Stage A rule 1, "already classified: skip"), unlike Taiwan's
    source_id-based check, since geopolitical_signal's natural key really
    is the news-retrieval article_id (no ticker+period/ticker+timestamp
    concept here). No model call anywhere in this function - see
    pipeline/geopolitical_signal_classifier.py's module docstring.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.GEOPOLITICAL_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch geopolitical_news articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_done = get_existing_geopolitical_signal_article_ids(
        [a["id"] for a in all_articles if a.get("id") is not None],
    )
    to_classify = [a for a in all_articles if a.get("id") not in already_done]

    update_job_status(job_id, "running", article_count=len(to_classify))

    outcome_counts: dict[str, int] = {"DROPPED": 0, "WEAK": 0, "WAITING": 0}
    inserted = 0
    for article in to_classify:
        result = classify_geopolitical_signal_stage_a(article)
        outcome_counts[result["outcome"]] = outcome_counts.get(result["outcome"], 0) + 1
        try:
            insert_geopolitical_signal_classification(job_id, article, result)
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert geopolitical_signal Stage A result for"
                " article_id=%s (job %d)",
                article.get("id"), job_id,
            )

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_A] job=%d runs=%d pooled_articles=%d"
        " already_done=%d classified=%d inserted=%d dropped=%d weak=%d waiting=%d",
        job_id, len(run_ids), len(all_articles), len(already_done),
        len(to_classify), inserted, outcome_counts["DROPPED"],
        outcome_counts["WEAK"], outcome_counts["WAITING"],
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


async def run_geopolitical_signal_stage_b(job_id: int) -> None:
    """Stage B: one Haiku-class HIGH/WEAK call per Stage A survivor
    (signal_detection='waiting'), update each row in place. Rows are
    classified concurrently (bounded by CLASSIFY_CONCURRENCY, the same
    thread pool the news domain and Stage C share), not one at a time.

    No fetch from news-retrieval here - Stage B's entire input is already
    sitting in agent_classifications from Stage A (get_waiting_geopolitical_
    signal_articles), so this never re-reads news-retrieval at all.

    Daily cap (config.GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP, default 1000)
    is a safety tripwire against a bug flooding the worklist, not a cost
    control (even a 10x normal day costs under $1 per the spec's own cost
    math) - once hit, remaining waiting rows are left untouched for the
    next run, never forced through and never dropped.
    """
    update_job_status(job_id, "running")

    waiting = get_waiting_geopolitical_signal_articles()
    if not waiting:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_today = count_geopolitical_signal_stage_b_calls_today()
    remaining_cap = max(0, config.GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP - already_today)
    to_classify = waiting[:remaining_cap]
    capped = len(waiting) - len(to_classify)

    update_job_status(job_id, "running", article_count=len(to_classify))

    system_prompt = load_stage_b_prompt()
    model = config.GEOPOLITICAL_SIGNAL_MODEL
    api_key = config.OPENAI_API_KEY
    base_url = config.OPENAI_BASE_URL
    timeout = config.OPENAI_TIMEOUT

    # Reuses the module-level _executor/CLASSIFY_CONCURRENCY that
    # run_agent_pipeline (news) and Stage C both share, rather than a
    # dedicated pool - same kind of blocking single-call HTTP classification,
    # no reason to double the thread pools in this process for it.
    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(row: dict[str, Any]) -> str | None:
        """Classify + persist one row; returns its outcome, or None on failure."""
        async with semaphore:
            outcome = await loop.run_in_executor(
                _executor,
                lambda: classify_geopolitical_signal_headline(
                    row["title"] or "",
                    system_prompt=system_prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                ),
            )
            try:
                update_geopolitical_signal_classification(row["id"], outcome=outcome)
                return outcome
            except Exception:
                logger.exception(
                    "Failed to update geopolitical_signal Stage B result for"
                    " row id=%s article_id=%s (job %d)",
                    row["id"], row.get("article_id"), job_id,
                )
                return None

    outcomes = await asyncio.gather(*[classify_one(row) for row in to_classify])
    outcome_counts: dict[str, int] = {"HIGH": 0, "WEAK": 0}
    updated = 0
    for outcome in outcomes:
        if outcome is not None:
            outcome_counts[outcome] += 1
            updated += 1

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_B] job=%d waiting=%d already_today=%d"
        " capped=%d classified=%d updated=%d high=%d weak=%d",
        job_id, len(waiting), already_today, capped, len(to_classify),
        updated, outcome_counts["HIGH"], outcome_counts["WEAK"],
    )
    update_job_status(job_id, "completed", article_count=updated, set_completed_at=True)


async def run_geopolitical_signal_stage_c(job_id: int) -> None:
    """Stage C: tag every untagged HIGH article - channel, actors, assets,
    impacted_categories, one_line, impacted_companies_direct.

    Flow per article, matching the locked Stage C plan:
      Layer 1 (free) -> Layer 2 (1 model call) -> deterministic overrides
      (free) -> Layer 3 (free, cache read) -> update in place.
    Rows are classified concurrently (bounded by CLASSIFY_CONCURRENCY,
    same pool as Stage B and the news domain), not one at a time - each
    row's flow above runs as a single unit in the shared thread pool.

    No fetch from news-retrieval - Stage C's input is entirely rows
    already in this table (get_untagged_geopolitical_signal_high_articles).
    Layer 1's company list is loaded ONCE for the whole run, not once per
    article (see get_companies_for_name_matching's docstring) - this was a
    deliberate fix during design review, not the naive per-article refetch
    the original plan implied.

    Daily cap (config.GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP, default 50) is
    a safety tripwire, same reasoning as Stage B's cap - once hit,
    remaining untagged rows are left untouched for the next run.
    """
    update_job_status(job_id, "running")

    untagged = get_untagged_geopolitical_signal_high_articles()
    if not untagged:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_today = count_geopolitical_signal_stage_c_calls_today()
    remaining_cap = max(0, config.GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP - already_today)
    to_classify = untagged[:remaining_cap]
    capped = len(untagged) - len(to_classify)

    update_job_status(job_id, "running", article_count=len(to_classify))

    companies = get_companies_for_name_matching()
    system_prompt = config.GEOPOLITICAL_SIGNAL_STAGE_C_PROMPT.read_text(encoding="utf-8")
    model = config.GEOPOLITICAL_SIGNAL_STAGE_C_MODEL
    api_key = config.OPENAI_API_KEY
    base_url = config.OPENAI_BASE_URL
    timeout = config.OPENAI_TIMEOUT

    # Runs each row's whole Layer1->Layer2->overrides->Layer3->DB-write body
    # as one executor job, not split across separate awaits - Layer 3's
    # get_tickers_for_categories is a blocking DB call, so splitting it out
    # into its own run_in_executor would still block the event loop for
    # nothing (no other awaitable work happens between it and the model
    # call). Reuses the same _executor/CLASSIFY_CONCURRENCY pool Stage B
    # and the news domain already share.
    def _tag_one_sync(row: dict[str, Any]) -> dict[str, Any] | None:
        title = row["title"] or ""

        # Layer 1 - free, always kept regardless of what Layer 2 returns.
        direct_matches = find_direct_company_matches(title, companies)

        # Layer 2 - one model call; fail-open on any parse/shape failure.
        layer2_result = classify_geopolitical_signal_tags(
            title,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        # Deterministic overrides - only ever add categories.
        final_categories = apply_overrides(
            channel=layer2_result["channel"],
            actors=layer2_result["actors"],
            assets=layer2_result["assets"],
            impacted_categories=layer2_result["impacted_categories"],
        )

        # Layer 3 - free cache lookup, only for the categories actually
        # chosen. Already [{ticker, company_name, matched_categories}] -
        # one entry per ticker, not per ticker-category pair (see
        # get_tickers_for_categories' docstring).
        category_matches = get_tickers_for_categories(final_categories)

        tags = {
            "channel": layer2_result["channel"],
            "actors": layer2_result["actors"],
            "assets": layer2_result["assets"],
            "impacted_categories": final_categories or None,
            "impacted_companies_direct": direct_matches or None,
            "impacted_companies_by_category": category_matches or None,
            "one_line": layer2_result["one_line"],
        }
        try:
            update_geopolitical_signal_stage_c_tags(row["id"], tags=tags)
            return tags
        except Exception:
            logger.exception(
                "Failed to update geopolitical_signal Stage C tags for"
                " row id=%s article_id=%s (job %d)",
                row["id"], row.get("article_id"), job_id,
            )
            return None

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def tag_one(row: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            return await loop.run_in_executor(_executor, _tag_one_sync, row)

    results = await asyncio.gather(*[tag_one(row) for row in to_classify])
    updated = sum(1 for r in results if r is not None)

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_C] job=%d untagged=%d already_today=%d"
        " capped=%d classified=%d updated=%d",
        job_id, len(untagged), already_today, capped, len(to_classify), updated,
    )
    update_job_status(job_id, "completed", article_count=updated, set_completed_at=True)


async def run_geopolitical_signal_stage_d(job_id: int) -> None:
    """Stage D: grade every Stage-C-tagged HIGH article into TOP/STRONG/
    STANDARD via three free checks (see pipeline/geopolitical_signal_
    stage_d.py's module docstring for the exact rules).

    No model call, no daily cap (unlike Stage B/C - there's no external
    API cost here to tripwire against). One news-retrieval call per
    article (GET /articles/{id}) to read metadata.also_reported_by, which
    only ever lives on the source article, never copied into this
    service's own rows. Fetches run concurrently (bounded by
    CLASSIFY_CONCURRENCY) via asyncio.gather - no thread pool needed since
    get_article is already async and grading itself does no I/O.
    """
    update_job_status(job_id, "running")

    ungraded = get_ungraded_geopolitical_signal_tagged_articles()
    if not ungraded:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    update_job_status(job_id, "running", article_count=len(ungraded))

    # get_article is already async (its own httpx.AsyncClient per call), and
    # grade_geopolitical_signal_article is pure/local (no I/O) - no thread
    # pool needed here, just gather the news-retrieval fetches behind the
    # same concurrency cap the other stages use.
    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)

    async def grade_one(row: dict[str, Any]) -> bool:
        async with semaphore:
            article = await get_article(row["article_id"])
            also_reported_by = (
                (article.get("metadata") or {}).get("also_reported_by") if article else None
            )

            grade_fields = grade_geopolitical_signal_article(
                url=row["url"],
                title=row["title"],
                also_reported_by=also_reported_by,
                impacted_companies_direct=row.get("impacted_companies_direct"),
            )

            try:
                update_geopolitical_signal_stage_d_grade(row["id"], grade_fields=grade_fields)
                return True
            except Exception:
                logger.exception(
                    "Failed to update geopolitical_signal Stage D grade for"
                    " row id=%s article_id=%s (job %d)",
                    row["id"], row.get("article_id"), job_id,
                )
                return False

    outcomes = await asyncio.gather(*[grade_one(row) for row in ungraded])
    graded = sum(outcomes)

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_D] job=%d ungraded=%d graded=%d",
        job_id, len(ungraded), graded,
    )
    update_job_status(job_id, "completed", article_count=graded, set_completed_at=True)


async def run_agent_pipeline(job_id: int, domain: str, news_run_id: int, limit: int | None = None) -> None:
    """Background task: fetch → classify → persist.

    Routing is entirely dispatch.get_domain_config(domain) - sec_filing and
    taiwan_market_signal never reach this function (they have their own
    entry points: controllers/filing_run.py, run_taiwan_signal_classification
    above), so an unregistered domain here is either a caller error (typo,
    stale domain string) or a genuinely new domain that hasn't been
    registered in pipeline/dispatch.py yet - either way, fail the job loudly
    rather than silently classifying it against the wrong domain's prompt
    and schema.
    """
    update_job_status(job_id, "running")
    try:
        articles = await get_run_articles(news_run_id)
    except NewsRetrievalError:
        logger.exception("Pre-classification pipeline failed for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    usable = [a for a in articles if has_usable_body(a)]
    if limit is not None:
        usable = usable[:limit]
    update_job_status(job_id, "running", article_count=len(usable))

    domain_config = get_domain_config(domain)
    if domain_config is None:
        logger.error(
            "No classifier registered for domain=%r (job %d) - known domains: %s",
            domain, job_id, ", ".join(known_domains()),
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    batch_context = [
        {"title": a.get("title", ""), "url": a.get("url", "")}
        for a in usable[:20]
    ]

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(article: dict[str, Any]) -> bool:
        """Classify a single article; returns True if skipped."""
        async with semaphore:
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda a=article: domain_config.classify_one(a, batch_context=batch_context),
                )
                domain_config.insert_fn(job_id, article, result)
                return False
            except Exception:
                logger.exception(
                    "Classification failed for article %s (job %d, domain=%s)",
                    article.get("url"), job_id, domain,
                )
                return True

    outcomes = await asyncio.gather(*[classify_one(a) for a in usable])
    skipped = sum(outcomes)

    if skipped == len(usable) and usable:
        update_job_status(job_id, "failed", set_completed_at=True)
    else:
        update_job_status(job_id, "completed", set_completed_at=True)
