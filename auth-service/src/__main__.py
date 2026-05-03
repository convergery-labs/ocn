"""Entry point for auth-service."""
import logging

import click
import uvicorn

from app import app
from db import init_db
from seed import seed_admin_key, seed_admin_user, seed_domains

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    @click.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8001)
    def main(host: str, port: int) -> None:
        """Start the auth-service uvicorn server."""
        logger.info("Initialising database...")
        init_db()
        logger.info("Seeding domains...")
        seed_domains()
        logger.info("Seeding admin key...")
        seed_admin_key()
        logger.info("Seeding admin user...")
        seed_admin_user()
        logger.info("Startup complete.")
        uvicorn.run(app, host=host, port=port)

    main()
