"""Category candidate pre-step - parked, not wired in v1.

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
        'category': 'Raw Materials & Critical Minerals',
        'description': 'Copper, rare earths, lithium, aluminum, uranium feedstock, specialty metals, mining royalties, PCB substrates, and upstream materials supporting AI infrastructure.',
    },
    {
        'category': 'Energy & Grid Infrastructure',
        'description': 'Power generation, utilities, gas, renewables, backup power, grid transmission, energy storage, and power infrastructure linked to AI data center demand.',
    },
    {
        'category': 'Nuclear & Advanced Energy',
        'description': 'Nuclear power plants, SMRs, advanced reactors, long-duration energy storage, and next-generation energy sources powering AI compute.',
    },
    {
        'category': 'Semiconductor Manufacturing',
        'description': 'Chip design, AI accelerators, GPUs, foundries, HBM and memory, EDA and IP, semiconductor equipment, advanced packaging, OSAT, wafers, and chip materials.',
    },
    {
        'category': 'Compute Hardware & Edge Systems',
        'description': 'AI servers, storage, OEM and ODM hardware, embedded compute, edge hardware, appliances, physical compute systems, sensors, and electronics manufacturing.',
    },
    {
        'category': 'Networking, Optical & Interconnect',
        'description': 'High-speed networking switches, optical transceivers, silicon photonics, InfiniBand, fiber interconnects, optical modules, and AI cluster networking infrastructure.',
    },
    {
        'category': 'Data Centers & Physical Infrastructure',
        'description': 'Colocation, data center REITs, construction, EPC, electrical systems, HVAC, liquid cooling, thermal management, towers, and physical facility infrastructure.',
    },
    {
        'category': 'Telecom & Connectivity',
        'description': 'Mobile network operators, 5G equipment, satellite connectivity, tower infrastructure, fixed wireless, backhaul, and telecom networks enabling AI services.',
    },
    {
        'category': 'Cloud & Compute Platforms',
        'description': 'Hyperscalers, neoclouds, GPU cloud providers, edge cloud, AI compute hosting, sovereign compute, managed cloud AI services, and compute platform operators.',
    },
    {
        'category': 'AI Software Infrastructure',
        'description': 'SaaS, cybersecurity, databases, developer tools, observability, identity, automation, middleware, inference engines, MLOps platforms, and horizontal AI-native software products sold across industries.',
    },
    {
        'category': 'AI Data Infrastructure',
        'description': 'Data annotation, data labeling, data marketplaces, synthetic data, data pipelines, data observability, enterprise data layers, and AI training data infrastructure.',
    },
    {
        'category': 'AI Models & Intelligence Layer',
        'description': 'Frontier model labs, foundation model companies, LLM providers, multimodal models, sovereign AI models, model releases, model APIs, benchmark results, and MLOps tooling.',
    },
    {
        'category': 'Robotics & Physical AI',
        'description': 'Industrial robotics, humanoid robots, autonomous vehicles, drones, ADAS, EV manufacturers, factory automation, and physical AI systems.',
    },
    {
        'category': 'Quantum Computing & Sensing',
        'description': 'Quantum computers, quantum networking, QKD, post-quantum cryptography, quantum sensing, and quantum hardware and software infrastructure.',
    },
    {
        'category': 'Life Sciences & Healthcare AI',
        'description': 'AI drug discovery, medical imaging AI, genomics, clinical AI, diagnostic AI, protein design, healthcare AI platforms, and life sciences AI applications.',
    },
    {
        'category': 'Defense, Aerospace & Sovereign AI',
        'description': 'Defense primes, aerospace AI, geospatial intelligence, government AI contracts, sovereign AI programs, space launch, and national security AI systems.',
    },
    {
        'category': 'Financial Infrastructure & AI Capital',
        'description': 'Fintech AI, AI lending, payments AI, project finance for AI capex, AI-focused investment vehicles, and financial infrastructure supporting AI deployment.',
    },
    {
        'category': 'Water & Resource Infrastructure',
        'description': 'Water treatment, water recycling, waste heat recovery, and resource infrastructure supporting AI data center sustainability and operations.',
    },
    {
        'category': 'Applications & Digital Economy',
        'description': 'Consumer AI, vertical AI applications, retail AI, marketing technology, digital media, gaming, agtech, smart buildings, and AI adoption across the digital economy.',
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
