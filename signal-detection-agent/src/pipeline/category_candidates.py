"""Category candidate pre-step — parked, not wired in v1.

Builds top-k category shortlists per article using embedding cosine similarity.
Re-enable by passing the result as category_hints into classify_article().
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np

MAX_TITLE_CHARS = 280
MAX_SUMMARY_CHARS = 1200

CATEGORY_SPECS = [
    {
        'category': 'Minerals & Raw Materials',
        'description': 'Copper, rare earths, lithium, aluminum, uranium feedstock, specialty metals, mining royalties, and upstream materials supporting AI infrastructure.',
    },
    {
        'category': 'Energy',
        'description': 'Power generation, utilities, nuclear, gas, renewables, backup power, grid power, and energy storage linked to AI demand.',
    },
    {
        'category': 'Semiconductor Manufacturing',
        'description': 'Chip design, AI accelerators, GPUs, foundries, HBM and memory, EDA and IP, semiconductor equipment, advanced packaging, OSAT, wafers, and chip materials.',
    },
    {
        'category': 'Compute Hardware',
        'description': 'AI servers, storage, OEM and ODM hardware, embedded compute, quantum hardware, edge hardware, robotics hardware, appliances, and physical compute systems.',
    },
    {
        'category': 'Thermal & Cooling',
        'description': 'HVAC, liquid cooling, chillers, thermal management, water systems, and cooling infrastructure for high-density AI data centers.',
    },
    {
        'category': 'Data Center Infrastructure',
        'description': 'Colocation, data center REITs, construction, EPC, electrical systems, networking, fiber, telecom, towers, and facility infrastructure.',
    },
    {
        'category': 'Cloud & Compute Market',
        'description': 'Hyperscalers, neoclouds, GPU cloud providers, edge cloud, AI compute hosting, sovereign compute, and compute platform operators.',
    },
    {
        'category': 'Software / Infrastructure',
        'description': 'SaaS, cybersecurity, databases, developer tools, observability, identity, automation, middleware, infrastructure software, model-serving frameworks, training runtimes, inference engines, MLOps platforms, and horizontal AI-native software products sold across industries.',
    },
    {
        'category': 'AI Data',
        'description': 'Data clouds, data providers, annotation, analytics, geospatial data, knowledge graphs, market data, governance, retrieval systems, vector data, and data infrastructure.',
    },
    {
        'category': 'AI Models',
        'description': 'Frontier model labs, foundation model companies, LLM providers, multimodal model companies, sovereign AI models, model platforms, model releases, embedding models, model checkpoints, model APIs, benchmark results, and direct model capability updates from model providers.',
    },
    {
        'category': 'Applications & Economy',
        'description': 'Applied AI companies in healthcare, fintech, robotics, drones, defense, space, industrial automation, consumer AI, vertical AI, research commercialization, and AI adoption.',
    },
]


def norm(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip())


def _clip_text(value: str, limit: int) -> str:
    value = norm(value)
    if len(value) <= limit:
        return value
    return norm(value[: limit - 1]) + '…'


def build_category_documents() -> list[dict[str, str]]:
    return [
        {
            'category': spec['category'],
            'text': f"{spec['category']}. {norm(spec['description'])}",
        }
        for spec in CATEGORY_SPECS
    ]


def build_query_text(article: dict[str, Any]) -> str:
    title = _clip_text(str(article.get('title') or article.get('headline') or ''), MAX_TITLE_CHARS)
    summary = _clip_text(str(article.get('summary') or ''), MAX_SUMMARY_CHARS)
    parts = [part for part in (title, summary) if part]
    return '\n\n'.join(parts)


def request_embeddings(
    texts: list[str],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: int,
) -> np.ndarray:
    if not api_key:
        raise ValueError('OPENAI_API_KEY is not configured')
    req = Request(
        f'{base_url}/embeddings',
        data=json.dumps({'input': texts, 'model': model}).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
    data = payload.get('data')
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError('Embedding response did not contain the expected data list')
    ordered = sorted(data, key=lambda item: int(item.get('index', 0)) if isinstance(item, dict) else 0)
    vectors: list[list[float]] = []
    for item in ordered:
        if not isinstance(item, dict) or not isinstance(item.get('embedding'), list):
            raise ValueError('Embedding response item missing embedding array')
        vectors.append([float(value) for value in item['embedding']])
    return np.asarray(vectors, dtype='float32')


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    if vectors.ndim != 2:
        raise ValueError('vectors must be a 2D matrix')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def search_candidate_vectors(
    query_vectors: np.ndarray,
    candidate_vectors: np.ndarray,
    *,
    k: int,
) -> tuple[np.ndarray, np.ndarray]:
    normalized_queries = normalize_rows(query_vectors.astype('float32', copy=True))
    normalized_candidates = normalize_rows(candidate_vectors.astype('float32', copy=True))
    similarity = normalized_queries @ normalized_candidates.T
    top_k = max(1, min(int(k), candidate_vectors.shape[0]))
    sorted_indexes = np.argsort(-similarity, axis=1)[:, :top_k]
    sorted_scores = np.take_along_axis(similarity, sorted_indexes, axis=1)
    return sorted_scores.astype('float32'), sorted_indexes.astype('int64')


def build_candidate_hints(
    articles: list[dict[str, Any]],
    *,
    embedding_model: str,
    api_key: str,
    base_url: str,
    timeout: int,
    k: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Return {url: [{"category": ..., "score": ...}, ...]} for each article."""
    category_documents = build_category_documents()
    query_texts = [build_query_text(article) for article in articles]
    category_vectors = request_embeddings(
        [item['text'] for item in category_documents],
        model=embedding_model, api_key=api_key, base_url=base_url, timeout=timeout,
    )
    query_vectors = request_embeddings(
        query_texts,
        model=embedding_model, api_key=api_key, base_url=base_url, timeout=timeout,
    )
    scores, indexes = search_candidate_vectors(query_vectors, category_vectors, k=k)

    hints: dict[str, list[dict[str, Any]]] = {}
    for article, score_row, index_row in zip(articles, scores.tolist(), indexes.tolist()):
        candidates = [
            {'category': category_documents[int(idx)]['category'], 'score': round(float(score), 4)}
            for score, idx in zip(score_row, index_row)
            if int(idx) >= 0
        ]
        hints[str(article.get('url', ''))] = candidates
    return hints
