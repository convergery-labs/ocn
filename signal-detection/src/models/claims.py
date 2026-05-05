"""Repository functions for the claims table."""
from db import get_db


def get_claims_for_classification(
    classification_id: int,
) -> list[dict[str, str]]:
    """Return claim rows for a classification as a list of dicts.

    Each dict has keys ``claim_embedding_id`` and ``claim_text``.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT claim_embedding_id, claim_text"
            " FROM claims"
            " WHERE classification_id = :id",
            {"id": classification_id},
        ).fetchall()
    return [dict(r) for r in rows]


def insert_claim(
    classification_id: int,
    claim_text: str,
    claim_embedding_id: str,
    embedding_model: str,
) -> None:
    """Insert a claim row linked to a classification."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO claims
                (classification_id, claim_text,
                 claim_embedding_id, embedding_model)
            VALUES
                (:classification_id, :claim_text,
                 :claim_embedding_id, :embedding_model)
            """,
            {
                "classification_id": classification_id,
                "claim_text": claim_text,
                "claim_embedding_id": claim_embedding_id,
                "embedding_model": embedding_model,
            },
        )
