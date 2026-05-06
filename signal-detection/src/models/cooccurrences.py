"""Repository for concept co-occurrence counts."""
from itertools import combinations

from db import get_db


def upsert_cooccurrences(concepts: list[str], domain: str) -> None:
    """Upsert all canonical concept pairs extracted from one article.

    Increments co_occurrence_count by 1 for each pair on conflict.
    Counts are partitioned by domain. No-ops when fewer than 2 concepts
    are provided.
    """
    if len(concepts) < 2:
        return
    pairs = list(combinations(sorted(concepts), 2))
    with get_db() as conn:
        for concept_a, concept_b in pairs:
            conn.execute(
                """
                INSERT INTO concept_cooccurrences
                    (concept_a, concept_b, domain,
                     co_occurrence_count, last_updated_at)
                VALUES (:a, :b, :domain, 1, now())
                ON CONFLICT (concept_a, concept_b, domain)
                DO UPDATE SET
                    co_occurrence_count =
                        concept_cooccurrences.co_occurrence_count + 1,
                    last_updated_at = now()
                """,
                {"a": concept_a, "b": concept_b, "domain": domain},
            )


def get_cooccurrence_counts(
    pairs: list[tuple[str, str]],
    domain: str,
) -> dict[tuple[str, str], int]:
    """Return co-occurrence counts for the given canonical concept pairs.

    Pairs must be in canonical order (a < b). Only counts within the
    given domain are returned. Missing pairs return 0.
    """
    if not pairs:
        return {}
    pair_set = set(pairs)
    a_values = list({a for a, _ in pairs})
    b_values = list({b for _, b in pairs})
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT concept_a, concept_b, co_occurrence_count
            FROM concept_cooccurrences
            WHERE concept_a = ANY(:a_values)
              AND concept_b = ANY(:b_values)
              AND domain = :domain
            """,
            {"a_values": a_values, "b_values": b_values, "domain": domain},
        ).fetchall()
    counts = {
        (r["concept_a"], r["concept_b"]): r["co_occurrence_count"]
        for r in rows
        if (r["concept_a"], r["concept_b"]) in pair_set
    }
    return {pair: counts.get(pair, 0) for pair in pairs}
