"""Idempotent startup seeding for auth-service."""
import logging
import os

import bcrypt

from db import get_db
from models.api_keys import KEY_PREFIX, create_api_key, get_by_hash, hash_key
from models.users import create_user, get_user_by_username

logger = logging.getLogger(__name__)


_CANONICAL_DOMAINS = ["ai_news", "smart_money"]


def seed_domains() -> None:
    """Insert canonical domain slugs if absent.

    Idempotent: ON CONFLICT DO NOTHING skips rows that already exist.
    """
    with get_db() as conn:
        for slug in _CANONICAL_DOMAINS:
            conn.execute(
                "INSERT INTO domains (slug) VALUES (?)"
                " ON CONFLICT (slug) DO NOTHING",
                (slug,),
            )
    logger.info("Domain seed complete.")


def seed_admin_key() -> None:
    """Create the admin API key from AUTH_ADMIN_API_KEY env var if absent.

    Idempotent: skips insertion if the key already exists in the DB.
    """
    key = os.environ["AUTH_ADMIN_API_KEY"]
    if not key.startswith(KEY_PREFIX):
        raise ValueError(
            f"AUTH_ADMIN_API_KEY must start with '{KEY_PREFIX}'"
        )
    if get_by_hash(hash_key(key)) is not None:
        logger.info("Admin key already exists — skipping seed.")
        return
    create_api_key(key, label="seed-admin", role="admin", created_by=None)
    logger.info("Seed admin key created.")


def seed_admin_user() -> None:
    """Create the admin user from ADMIN_USERNAME/ADMIN_PASSWORD env vars.

    Idempotent: skips insertion if the username already exists.
    """
    username = os.environ["ADMIN_USERNAME"]
    email = os.environ["ADMIN_EMAIL"]
    password = os.environ["ADMIN_PASSWORD"]
    if get_user_by_username(username) is not None:
        logger.info("Admin user already exists — skipping seed.")
        return
    password_hash = bcrypt.hashpw(
        password.encode(), bcrypt.gensalt()
    ).decode()
    create_user(
        username=username,
        email=email,
        password_hash=password_hash,
        role="admin",
    )
    logger.info("Seed admin user created.")
