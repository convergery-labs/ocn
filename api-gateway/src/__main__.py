"""Entry point for api-gateway."""
import logging

import click
import uvicorn

from app import app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    @click.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8004)
    def main(host: str, port: int) -> None:
        """Start the api-gateway uvicorn server."""
        logger.info("Starting api-gateway...")
        uvicorn.run(app, host=host, port=port)

    main()
