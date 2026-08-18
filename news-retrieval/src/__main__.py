"""Entry point for the News Aggregator service."""
import logging
import sys

import click
import uvicorn

from app import app
from db import init_db
from models.runs import fail_orphaned_runs
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000)
def serve(host: str, port: int) -> None:
    """Start the uvicorn server."""
    logger.info("Initialising database...")
    init_db()
    logger.info("Seeding database...")
    seed()
    cleaned = fail_orphaned_runs()
    if cleaned:
        logger.info("Cleaned up %d orphaned run(s).", cleaned)
    logger.info("Startup complete.")
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--domain", default="company_news", show_default=True)
@click.option("--days-back", default=1, show_default=True)
def trigger(domain: str, days_back: int) -> None:
    """Run the fetch pipeline for a domain and exit."""
    from controllers.run import RunRequest, create_run_record, run_pipeline

    init_db()
    seed()

    request = RunRequest(domain=domain, days_back=days_back, force=True)
    caller = {"role": "admin", "id": None}

    try:
        result = create_run_record(request, caller)
    except Exception as exc:
        logger.error("Failed to create run record: %s", exc)
        sys.exit(1)

    if result["cache_hit"]:
        logger.info("Cache hit — run_id=%d already completed today.", result["run_id"])
        sys.exit(0)

    logger.info("Starting pipeline — domain=%s run_id=%d", domain, result["run_id"])
    run_pipeline(result["run_id"], request, result["domain_config"])
    logger.info("Pipeline complete — run_id=%d", result["run_id"])


@cli.command("expire-articles")
@click.option("--domain", required=True, help="Domain slug to expire articles for, e.g. geopolitical_news.")
@click.option("--days", default=7, show_default=True, help="Delete articles published more than this many days ago.")
def expire_articles(domain: str, days: int) -> None:
    """Delete old articles for one domain. Runs to completion and exits."""
    from models.articles import expire_articles_for_domain

    init_db()
    deleted = expire_articles_for_domain(domain, days)
    logger.info("[EXPIRE] domain=%s days=%d deleted=%d", domain, days, deleted)


@cli.command("poll-market")
@click.option(
    "--mode",
    type=click.Choice(["quotes", "daily", "sec_filings"]),
    required=True,
    help=(
        "quotes: price/indices/status every 15 min. daily: overview/earnings/history once a day. "
        "sec_filings: 8-K/10-Q/10-K metadata + link once a day."
    ),
)
@click.option(
    "--tickers",
    default=None,
    help="Comma-separated ticker list. Falls back to MARKET_POLL_TICKERS env var.",
)
def poll_market(mode: str, tickers: str | None) -> None:
    """Fetch market data from Alpha Vantage / SEC EDGAR and write to DynamoDB."""
    import os
    from poller import run_daily, run_quotes, run_sec_filings

    from pipeline import get_tracked_ticker_universe
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        universe_url = os.environ.get("RESEARCH_UNIVERSE_URL")
        universe_api_key = os.environ.get("RESEARCH_UNIVERSE_API_KEY")
        ticker_list = get_tracked_ticker_universe(universe_url, universe_api_key)
    logger.info("[POLLER] tickers=%d", len(ticker_list))

    if mode == "sec_filings":
        run_sec_filings(ticker_list)
        return

    av_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not av_key:
        logger.error("ALPHA_VANTAGE_API_KEY is not set")
        sys.exit(1)

    if mode == "daily":
        run_daily(ticker_list, av_key)
    else:
        run_quotes(ticker_list, av_key)


if __name__ == "__main__":
    cli()
