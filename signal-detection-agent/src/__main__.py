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


if __name__ == "__main__":
    cli()
