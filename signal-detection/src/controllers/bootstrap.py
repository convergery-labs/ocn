"""Orchestration for the corpus bootstrap pipeline."""
import logging
import os
import time
import uuid
from datetime import date, timedelta
from typing import Iterator

import httpx
import numpy as np
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)
from sklearn.cluster import MiniBatchKMeans

from models.clusters import upsert_corpus_centroid, upsert_topic_cluster

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 50
_FETCH_PAGE_SIZE = 100
_VECTOR_SIZE = 3072
_SCROLL_PAGE_SIZE = 256


def _news_retrieval_url() -> str:
    """Return the news-retrieval base URL from env."""
    return os.environ.get(
        "NEWS_RETRIEVAL_URL", "http://news-retrieval:8000"
    )


def _embedding_model() -> str:
    """Return the configured embedding model name."""
    return os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-large")


def _openai_client() -> OpenAI:
    """Return an OpenAI client configured for OpenRouter."""
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


def _qdrant_client() -> QdrantClient:
    """Return a Qdrant client from env config."""
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "qdrant"),
        port=int(os.environ.get("QDRANT_PORT", "6333")),
    )


def _url_to_point_id(url: str) -> str:
    """Return a deterministic UUID for a URL."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


def _fetch_articles(
    domain: str,
    days_back: int,
) -> Iterator[dict]:
    """Yield unique articles from news-retrieval for a domain.

    Paginates through completed runs then their articles. Skips
    articles without a body.
    """
    from_date = (date.today() - timedelta(days=days_back)).isoformat()
    base = _news_retrieval_url()
    seen_urls: set[str] = set()

    with httpx.Client(timeout=30.0) as client:
        run_cursor: str | None = None
        while True:
            params: dict = {
                "domain": domain,
                "from_date": from_date,
                "status": "completed",
                "limit": _FETCH_PAGE_SIZE,
            }
            if run_cursor:
                params["cursor"] = run_cursor

            resp = client.get(f"{base}/runs", params=params)
            resp.raise_for_status()
            data = resp.json()
            runs = data.get("runs", [])

            for run in runs:
                article_cursor: str | None = None
                while True:
                    art_params: dict = {
                        "limit": _FETCH_PAGE_SIZE,
                        "include_body": "true",
                    }
                    if article_cursor:
                        art_params["cursor"] = article_cursor

                    art_resp = client.get(
                        f"{base}/runs/{run['id']}/articles",
                        params=art_params,
                    )
                    art_resp.raise_for_status()
                    art_data = art_resp.json()
                    articles = art_data.get("articles", [])

                    for article in articles:
                        url = article.get("url")
                        body = article.get("body")
                        if not url or not body:
                            continue
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        yield article

                    article_cursor = art_data.get("next_cursor")
                    if not article_cursor:
                        break

            run_cursor = data.get("next_cursor")
            if not run_cursor:
                break


_MAX_BODY_CHARS = 30_000


def _embed_batch(
    client: OpenAI,
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """Return embeddings for a batch of texts.

    Truncates each text to _MAX_BODY_CHARS to stay within the
    8191-token context limit of text-embedding-3-large.
    """
    truncated = [t[:_MAX_BODY_CHARS] for t in texts]
    response = client.embeddings.create(model=model, input=truncated)
    return [item.embedding for item in response.data]


def _ensure_collection(
    qdrant: QdrantClient,
    name: str,
) -> None:
    """Create a Qdrant collection if it does not exist."""
    existing = {c.name for c in qdrant.get_collections().collections}
    if name not in existing:
        qdrant.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )


def run_bootstrap(
    domain: str,
    days_back: int,
    k: int,
) -> None:
    """Run the full corpus bootstrap pipeline for a domain.

    Fetches articles from news-retrieval, embeds them into Qdrant
    (idempotent), clusters via MiniBatchKMeans, then persists
    topic_clusters and corpus_centroids rows to Postgres.
    """
    model = _embedding_model()
    bootstrap_collection = f"bootstrap_{domain}"

    qdrant = _qdrant_client()
    openai_client = _openai_client()

    _ensure_collection(qdrant, bootstrap_collection)

    logger.info(
        "Fetching articles for domain=%s days_back=%d", domain, days_back
    )
    articles = list(_fetch_articles(domain, days_back))
    total = len(articles)
    logger.info("Found %d unique articles with body", total)

    if total == 0:
        logger.warning("No articles found; nothing to bootstrap.")
        return

    existing_ids = {
        str(p.id)
        for p in qdrant.retrieve(
            collection_name=bootstrap_collection,
            ids=[_url_to_point_id(a["url"]) for a in articles],
            with_vectors=False,
        )
    }

    to_embed = [a for a in articles if _url_to_point_id(a["url"]) not in existing_ids]
    logger.info(
        "%d already embedded, %d new to embed",
        len(existing_ids),
        len(to_embed),
    )

    embedded = 0
    start = time.monotonic()
    for i in range(0, len(to_embed), _EMBED_BATCH_SIZE):
        batch = to_embed[i: i + _EMBED_BATCH_SIZE]
        vectors = _embed_batch(openai_client, [a["body"] for a in batch], model)
        points = [
            PointStruct(
                id=_url_to_point_id(a["url"]),
                vector=v,
                payload={"url": a["url"]},
            )
            for a, v in zip(batch, vectors)
        ]
        qdrant.upsert(collection_name=bootstrap_collection, points=points)
        embedded += len(batch)
        elapsed = time.monotonic() - start
        rate = embedded / elapsed if elapsed > 0 else 0
        remaining = (len(to_embed) - embedded) / rate if rate > 0 else 0
        logger.info(
            "Embedded %d/%d articles (%.0fs remaining)",
            embedded,
            len(to_embed),
            remaining,
        )

    logger.info("Scrolling all vectors for clustering...")
    all_ids: list[str] = []
    all_vectors: list[list[float]] = []
    scroll_offset = None
    while True:
        result, scroll_offset = qdrant.scroll(
            collection_name=bootstrap_collection,
            limit=_SCROLL_PAGE_SIZE,
            offset=scroll_offset,
            with_vectors=True,
        )
        for point in result:
            all_ids.append(str(point.id))
            all_vectors.append(point.vector)
        if scroll_offset is None:
            break

    logger.info("Running MiniBatchKMeans(k=%d) on %d vectors", k, len(all_vectors))
    matrix = np.array(all_vectors, dtype=np.float32)
    kmeans = MiniBatchKMeans(n_clusters=k, random_state=42, n_init="auto")
    labels = kmeans.fit_predict(matrix)

    for cluster_i in range(k):
        mask = labels == cluster_i
        cluster_ids = [pid for pid, m in zip(all_ids, mask) if m]
        cluster_vectors = matrix[mask]
        doc_count = len(cluster_ids)

        cluster_collection = f"corpus_{domain}_{cluster_i}"
        _ensure_collection(qdrant, cluster_collection)

        points = [
            PointStruct(id=pid, vector=vec.tolist(), payload={})
            for pid, vec in zip(cluster_ids, cluster_vectors)
        ]
        for j in range(0, len(points), _SCROLL_PAGE_SIZE):
            qdrant.upsert(
                collection_name=cluster_collection,
                points=points[j: j + _SCROLL_PAGE_SIZE],
            )

        slug = f"{domain}-{cluster_i}"
        cluster_id = upsert_topic_cluster(
            name=f"{domain} cluster {cluster_i}",
            slug=slug,
            collection=cluster_collection,
        )
        upsert_corpus_centroid(
            cluster_id=cluster_id,
            embedding_model=model,
            document_count=doc_count,
        )
        logger.info(
            "Cluster %s: %d documents → collection %s",
            slug,
            doc_count,
            cluster_collection,
        )

    logger.info("Bootstrap complete for domain=%s", domain)
