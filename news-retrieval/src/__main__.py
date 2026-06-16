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


if __name__ == "__main__":
    cli()
