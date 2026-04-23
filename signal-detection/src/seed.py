"""Seed the database with initial lookup data.

Idempotent — rows that already exist are silently skipped.
"""
import logging

from db import get_db, transaction

logger = logging.getLogger(__name__)

CLASSIFICATION_STATUSES: list[str] = ["processing", "completed", "failed"]


def seed() -> None:
    """Insert classification statuses.

    Safe to call multiple times; all inserts use ON CONFLICT DO NOTHING.
    """
    with transaction():
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO classification_statuses (name)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(s,) for s in CLASSIFICATION_STATUSES],
            )
    logger.info(
        "Seeded %d classification statuses.",
        len(CLASSIFICATION_STATUSES),
    )
