"""Entry point for the signal-detection service."""
import logging

import click
import uvicorn

from app import app
from db import init_db
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    @click.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8002)
    def main(host: str, port: int) -> None:
        """Start the uvicorn server."""
        logger.info("Initialising database...")
        init_db()
        logger.info("Seeding database...")
        seed()
        logger.info("Startup complete.")
        uvicorn.run(app, host=host, port=port)

    main()
