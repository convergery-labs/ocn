"""Seed initial reference data for the signal-detection-agent service."""


from db import get_db


def seed() -> None:
    """Seed agent_job_statuses reference data."""
    with get_db() as conn:
        for status in ("pending", "running", "completed", "failed"):
            conn.execute(
                "INSERT INTO agent_job_statuses (status) VALUES (%s) ON CONFLICT DO NOTHING",
                (status,),
            )
