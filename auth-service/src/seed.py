"""Idempotent startup seeding for auth-service."""
import logging
import os

from models.api_keys import create_api_key, get_by_hash, hash_key

logger = logging.getLogger(__name__)


def seed_admin_key() -> None:
    """Create the admin API key from AUTH_ADMIN_API_KEY env var if absent.

    Idempotent: skips insertion if the key already exists in the DB.
    """
    key = os.environ["AUTH_ADMIN_API_KEY"]
    if get_by_hash(hash_key(key)) is not None:
        logger.info("Admin key already exists — skipping seed.")
        return
    create_api_key(key, label="seed-admin", role="admin", created_by=None)
    logger.info("Seed admin key created.")
