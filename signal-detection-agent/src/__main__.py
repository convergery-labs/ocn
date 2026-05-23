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


if __name__ == "__main__":
    cli()
