"""Entry point for the signal-detection-agent service."""
import logging

import click
import uvicorn

from db import init_db
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """signal-detection-agent service CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8003)
def serve(host: str, port: int) -> None:
    """Start the uvicorn server."""
    from app import app

    logger.info("Initialising database...")
    init_db()
    logger.info("Seeding database...")
    seed()
    logger.info("Startup complete.")
    uvicorn.run(app, host=host, port=port)


@cli.command("classify-filings")
@click.option(
    "--tickers",
    default=None,
    help="Comma-separated ticker subset for a scoped manual test run "
    "(e.g. AAPL,MSFT). Omit for the normal full tracked-universe run "
    "used by the daily CloudWatch schedule.",
)
def classify_filings(tickers: str | None) -> None:
    """One-shot: fetch tracked tickers' SEC filings, classify what's new, persist.

    Entry point for the daily CloudWatch-triggered scheduled task - runs to
    completion and exits (not a server), mirroring the shape of
    news-retrieval's `poll-market --mode sec_filings` command.
    """
    import asyncio

    from controllers.filing_run import run_filing_classification_job, submit_filing_run

    logger.info("Initialising database...")
    init_db()
    seed()

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None
    job_id = submit_filing_run()
    logger.info("Created SEC filing job_id=%s tickers=%s", job_id, ticker_list or "all-tracked")
    asyncio.run(run_filing_classification_job(job_id, tickers=ticker_list))
    logger.info("SEC filing job_id=%s finished", job_id)


@cli.command("backfill-filing-tickers")
def backfill_filing_tickers_cmd() -> None:
    """One-time migration: add metadata.ticker to sec_filing rows written
    before this field existed. Read-only against news-retrieval and EDGAR
    (no filing text/LLM calls) - safe to run independently of classify-filings.
    """
    import asyncio

    from controllers.filing_run import run_ticker_backfill

    logger.info("Initialising database...")
    init_db()
    seed()

    asyncio.run(run_ticker_backfill())
    logger.info("Ticker backfill finished")


@cli.command("classify-taiwan-signals")
@click.option(
    "--from-date",
    default=None,
    help="Start date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC) - i.e. classify all of today's completed "
    "taiwan_market_signal runs so far.",
)
@click.option(
    "--to-date",
    default=None,
    help="End date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC).",
)
def classify_taiwan_signals(from_date: str | None, to_date: str | None) -> None:
    """One-shot: pool today's completed taiwan_market_signal news-retrieval
    runs, rank/classify/translate, persist. Entry point for the twice-daily
    CloudWatch-triggered scheduled task (post-Asia-close and pre-US-open) -
    runs to completion and exits (not a server).
    """
    import asyncio
    from datetime import datetime, timezone

    import config
    from controllers.run import run_taiwan_signal_classification
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = from_date or today
    to_date = to_date or today

    job_id = create_job(domain=config.TAIWAN_SIGNAL_DOMAIN)
    logger.info(
        "Created taiwan_market_signal job_id=%s from_date=%s to_date=%s",
        job_id, from_date, to_date,
    )
    asyncio.run(run_taiwan_signal_classification(job_id, from_date, to_date))
    logger.info("taiwan_market_signal job_id=%s finished", job_id)


@cli.command("classify-korea-signals")
@click.option(
    "--from-date",
    default=None,
    help="Start date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC) - i.e. classify all of today's completed "
    "korea_market_signal runs so far.",
)
@click.option(
    "--to-date",
    default=None,
    help="End date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC).",
)
def classify_korea_signals(from_date: str | None, to_date: str | None) -> None:
    """One-shot: pool today's completed korea_market_signal news-retrieval
    runs, classify (S2-S7)/translate, persist. Entry point for the scheduled
    task - runs to completion and exits (not a server).
    """
    import asyncio
    from datetime import datetime, timezone

    import config
    from controllers.run import run_korea_signal_classification
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = from_date or today
    to_date = to_date or today

    job_id = create_job(domain=config.KOREA_SIGNAL_DOMAIN)
    logger.info(
        "Created korea_market_signal job_id=%s from_date=%s to_date=%s",
        job_id, from_date, to_date,
    )
    asyncio.run(run_korea_signal_classification(job_id, from_date, to_date))
    logger.info("korea_market_signal job_id=%s finished", job_id)


@cli.command("summarize-korea-signals")
@click.option(
    "--date",
    default=None,
    help="Date (YYYY-MM-DD, UTC) of classified korea_market_signal rows to "
    "summarize. Defaults to today (UTC).",
)
def summarize_korea_signals(date: str | None) -> None:
    """One-shot: read today's already-classified korea_market_signal rows
    from this service's own DB and generate the spec Section 8.4 trader
    summary text. No news-retrieval fetch, no classification - reads only
    (see generate_korea_signal_summary_for_date's own docstring). Runs to
    completion and exits (not a server) - same shape as classify-korea-signals.

    Output goes to the log only (INFO level) - there is no email/delivery
    mechanism wired up yet (see korea_signal_summary.py's own module
    docstring on scope). GET /korea-signals/summary (routes/jobs.py) is
    the on-demand equivalent of this same call, for a caller that wants
    the text back directly rather than reading CloudWatch logs.
    """
    from datetime import datetime, timezone

    from controllers.run import generate_korea_signal_summary_for_date

    logger.info("Initialising database...")
    init_db()
    seed()

    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = generate_korea_signal_summary_for_date(date)
    logger.info("[KOREA_SIGNAL_SUMMARY] date=%s\n%s", date, summary)


@cli.command("classify-geopolitical-signals")
@click.option(
    "--from-date",
    default=None,
    help="Start date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC).",
)
@click.option(
    "--to-date",
    default=None,
    help="End date (YYYY-MM-DD) of the news-retrieval run window to pool. "
    "Defaults to today (UTC).",
)
def classify_geopolitical_signals(from_date: str | None, to_date: str | None) -> None:
    """One-shot: pool completed geopolitical_news news-retrieval runs in the
    given window, apply Stage A's free rule-based filters, persist. Stage A
    only - no model call. Runs to completion and exits (not a server).
    """
    import asyncio
    from datetime import datetime, timezone

    import config
    from controllers.run import run_geopolitical_signal_stage_a
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = from_date or today
    to_date = to_date or today

    job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info(
        "Created geopolitical_signal job_id=%s from_date=%s to_date=%s",
        job_id, from_date, to_date,
    )
    asyncio.run(run_geopolitical_signal_stage_a(job_id, from_date, to_date))
    logger.info("geopolitical_signal job_id=%s finished", job_id)


@cli.command("classify-geopolitical-signals-stage-b")
def classify_geopolitical_signals_stage_b() -> None:
    """One-shot: classify every geopolitical_signal row currently
    signal_detection='waiting' as HIGH/WEAK via one model call each,
    update in place. No news-retrieval fetch - reads only from this
    service's own DB. Runs to completion and exits (not a server).
    """
    import asyncio

    import config
    from controllers.run import run_geopolitical_signal_stage_b
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage B job_id=%s", job_id)
    asyncio.run(run_geopolitical_signal_stage_b(job_id))
    logger.info("geopolitical_signal Stage B job_id=%s finished", job_id)


@cli.command("refresh-geopolitical-category-map")
def refresh_geopolitical_category_map() -> None:
    """One-shot: fetch the current US-listed company universe from
    research-universe, rebuild Stage C's category->ticker cache. Runs on
    its own schedule (independent of Stage C's own runs) - Stage C only
    ever reads this cache, never calls research-universe directly.
    """
    import asyncio

    from controllers.category_map_refresh import refresh_category_ticker_map

    logger.info("Initialising database...")
    init_db()
    seed()

    counts = asyncio.run(refresh_category_ticker_map())
    logger.info("Category map refreshed: %s", counts)


@cli.command("classify-geopolitical-signals-stage-c")
def classify_geopolitical_signals_stage_c() -> None:
    """One-shot: tag every untagged HIGH geopolitical_signal row - channel,
    actors, assets, impacted_categories, impacted companies, one_line.
    No news-retrieval fetch - reads only from this service's own DB and
    its cached company data. Runs to completion and exits (not a server).
    """
    import asyncio

    import config
    from controllers.run import run_geopolitical_signal_stage_c
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage C job_id=%s", job_id)
    asyncio.run(run_geopolitical_signal_stage_c(job_id))
    logger.info("geopolitical_signal Stage C job_id=%s finished", job_id)


@cli.command("classify-geopolitical-signals-stage-d")
def classify_geopolitical_signals_stage_d() -> None:
    """One-shot: grade every Stage-C-tagged HIGH geopolitical_signal row
    into TOP/STRONG/STANDARD (corroboration, primary-source, specificity -
    see pipeline/geopolitical_signal_stage_d.py). No model call; one
    news-retrieval call per row (GET /articles/{id}) for
    also_reported_by. Runs to completion and exits (not a server).
    """
    import asyncio

    import config
    from controllers.run import run_geopolitical_signal_stage_d
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage D job_id=%s", job_id)
    asyncio.run(run_geopolitical_signal_stage_d(job_id))
    logger.info("geopolitical_signal Stage D job_id=%s finished", job_id)


@cli.command("run-geopolitical-signal-pipeline")
@click.option(
    "--from-date",
    default=None,
    help="Start date (YYYY-MM-DD) of the news-retrieval run window Stage A "
    "pools. Defaults to today (UTC).",
)
@click.option(
    "--to-date",
    default=None,
    help="End date (YYYY-MM-DD) of the news-retrieval run window Stage A "
    "pools. Defaults to today (UTC).",
)
def run_geopolitical_signal_pipeline(from_date: str | None, to_date: str | None) -> None:
    """One-shot: Stage A, then Stage B, then Stage C, then Stage D, in
    sequence in one process. Each stage only ever acts on rows the
    previous stage already wrote (A creates rows -> B classifies A's
    'waiting' rows -> C tags B's 'signal'/HIGH rows -> D grades C's
    tagged rows), so running them as separately-scheduled triggers risked
    a later stage firing before the prior stage's run had finished. A
    single combined command removes that race entirely - the stages are
    inherently sequential, not independent jobs. Runs to completion and
    exits (not a server).
    """
    import asyncio
    from datetime import datetime, timezone

    import config
    from controllers.run import (
        run_geopolitical_signal_stage_a,
        run_geopolitical_signal_stage_b,
        run_geopolitical_signal_stage_c,
        run_geopolitical_signal_stage_d,
    )
    from models.jobs import create_job

    logger.info("Initialising database...")
    init_db()
    seed()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = from_date or today
    to_date = to_date or today

    stage_a_job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info(
        "Created geopolitical_signal Stage A job_id=%s from_date=%s to_date=%s",
        stage_a_job_id, from_date, to_date,
    )
    asyncio.run(run_geopolitical_signal_stage_a(stage_a_job_id, from_date, to_date))
    logger.info("geopolitical_signal Stage A job_id=%s finished", stage_a_job_id)

    stage_b_job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage B job_id=%s", stage_b_job_id)
    asyncio.run(run_geopolitical_signal_stage_b(stage_b_job_id))
    logger.info("geopolitical_signal Stage B job_id=%s finished", stage_b_job_id)

    stage_c_job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage C job_id=%s", stage_c_job_id)
    asyncio.run(run_geopolitical_signal_stage_c(stage_c_job_id))
    logger.info("geopolitical_signal Stage C job_id=%s finished", stage_c_job_id)

    stage_d_job_id = create_job(domain=config.GEOPOLITICAL_SIGNAL_DOMAIN)
    logger.info("Created geopolitical_signal Stage D job_id=%s", stage_d_job_id)
    asyncio.run(run_geopolitical_signal_stage_d(stage_d_job_id))
    logger.info("geopolitical_signal Stage D job_id=%s finished", stage_d_job_id)


@cli.command("expire-classifications")
@click.option("--source-type", required=True, help="source_type to expire, e.g. news or sec_filing.")
@click.option("--days", default=30, show_default=True, help="Delete classifications published more than this many days ago.")
def expire_classifications(source_type: str, days: int) -> None:
    """Delete old classifications for one source_type. Runs to completion and exits."""
    from models.jobs import expire_classifications_for_source_type

    init_db()
    deleted = expire_classifications_for_source_type(source_type, days)
    logger.info("[EXPIRE] source_type=%s days=%d deleted=%d", source_type, days, deleted)


if __name__ == "__main__":
    cli()
