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


if __name__ == "__main__":
    cli()
