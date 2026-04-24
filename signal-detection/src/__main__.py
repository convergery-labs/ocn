"""Entry point for the signal-detection service."""
import logging

import click
import uvicorn

from app import app
from db import init_db
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """signal-detection service CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8002)
def serve(host: str, port: int) -> None:
    """Start the uvicorn server."""
    logger.info("Initialising database...")
    init_db()
    logger.info("Seeding database...")
    seed()
    logger.info("Startup complete.")
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--domain", required=True, help="Domain slug to bootstrap.")
@click.option(
    "--days-back",
    default=180,
    show_default=True,
    help="Number of days of historical articles to fetch.",
)
@click.option(
    "--k",
    default=8,
    show_default=True,
    help="Number of topic clusters (k-means k).",
)
def bootstrap(domain: str, days_back: int, k: int) -> None:
    """Embed and cluster historical articles to seed the corpus."""
    from controllers.bootstrap import run_bootstrap

    logger.info("Initialising database...")
    init_db()
    run_bootstrap(domain=domain, days_back=days_back, k=k)


@cli.command("promote-corpus")
def promote_corpus() -> None:
    """Process deferred corpus promotions (nightly job)."""
    from controllers.promote import promote_deferred_corpus

    logger.info("Initialising database...")
    init_db()
    stats = promote_deferred_corpus()
    logger.info("promote-corpus complete: %s", stats)


if __name__ == "__main__":
    cli()
