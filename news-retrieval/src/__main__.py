"""Entry point for the News Aggregator service."""
import logging

import click
import uvicorn

from app import app
from db import init_db
from models.runs import fail_orphaned_runs
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    @click.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8000)
    def main(host: str, port: int) -> None:
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

    main()
