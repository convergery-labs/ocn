"""DB query functions for category records."""
from db import get_db


def create_categories(
    run_id: int,
    names: list[str],
) -> dict[str, int]:
    """Batch-insert categories for a run and return a name→id map.

    Skips names that already exist for this run (ON CONFLICT DO NOTHING).

    Args:
        run_id: The run these categories belong to.
        names: Category names to insert.

    Returns:
        Dict mapping each category name to its database id.
    """
    if not names:
        return {}
    with get_db() as conn:
        conn.execute_values(
            "INSERT INTO categories (run_id, name) VALUES %s"
            " ON CONFLICT (run_id, name) DO NOTHING",
            [(run_id, name) for name in names],
        )
        rows = conn.execute(
            "SELECT id, name FROM categories"
            " WHERE run_id = ? AND name = ANY(?)",
            (run_id, names),
        ).fetchall()
    return {row["name"]: row["id"] for row in rows}


def list_categories(run_id: int) -> list[dict]:
    """Return all categories for a run, ordered by id."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM categories WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [dict(row) for row in cur.fetchall()]
