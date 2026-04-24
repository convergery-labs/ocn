"""Repository functions for the claims table."""
from db import get_db


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
