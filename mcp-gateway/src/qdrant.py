import os
from typing import Any

import httpx


QDRANT_URL = os.getenv("JINA_LOCAL_QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_COLLECTION = os.getenv("JINA_LOCAL_QDRANT_COLLECTION", "jina-local")
QDRANT_TIMEOUT = float(os.getenv("JINA_LOCAL_QDRANT_TIMEOUT", "2"))


def _url(path: str) -> str:
    return f"{QDRANT_URL.rstrip('/')}{path}"


def search(vector: list[float], limit: int = 5, collection: str = QDRANT_COLLECTION) -> list[dict] | None:
    try:
        response = httpx.post(
            _url(f"/collections/{collection}/points/search"),
            json={"vector": vector, "limit": limit, "with_payload": True},
            timeout=QDRANT_TIMEOUT,
            trust_env=False,
        )
        response.raise_for_status()
        result = response.json().get("result")
        return result if isinstance(result, list) else []
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


def upsert(points: list[dict], collection: str = QDRANT_COLLECTION) -> bool:
    try:
        response = httpx.put(
            _url(f"/collections/{collection}/points"),
            json={"points": points},
            timeout=QDRANT_TIMEOUT,
            trust_env=False,
        )
        response.raise_for_status()
        return True
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return False


def merge_results(lexical: list[dict], vector: list[dict] | None, limit: int = 5) -> list[dict]:
    combined: dict[str, dict] = {}
    for rank, item in enumerate(lexical):
        key = str(item.get("url", item.get("id", rank)))
        combined[key] = {**item, "hybrid_score": max(0.0, min(1.0, float(item.get("score", 0.0)))) * 0.5}
    for rank, item in enumerate(vector or []):
        key = str(item.get("url", item.get("id", rank)))
        raw_score = float(item.get("score", 0.0))
        vector_score = raw_score if 0.0 <= raw_score <= 1.0 else (raw_score + 1.0) / 2.0
        current = combined.get(key, {**item, "hybrid_score": 0.0})
        current["hybrid_score"] = float(current.get("hybrid_score", 0.0)) + max(0.0, min(1.0, vector_score)) * 0.5
        if key not in combined:
            combined[key] = current
    return sorted(combined.values(), key=lambda item: -float(item.get("hybrid_score", 0.0)))[:limit]


def normalize_results(hits: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for hit in hits or []:
        payload = hit.get("payload") if isinstance(hit, dict) else None
        if not isinstance(payload, dict):
            continue
        title = payload.get("title")
        url = payload.get("url")
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str) or not url.strip():
            continue
        normalized.append({
            "title": title,
            "url": url,
            "content": str(payload.get("content", "")),
            "score": float(hit.get("score", 0.0)),
        })
    return normalized


def health() -> bool:
    try:
        response = httpx.get(_url("/healthz"), timeout=QDRANT_TIMEOUT, trust_env=False)
        response.raise_for_status()
        return True
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return False


def enrich_search_results(lexical: list[dict], vector: list[float], limit: int = 5) -> list[dict]:
    hits = search(vector, limit=limit)
    normalized = normalize_results(hits)
    if not normalized:
        return lexical
    return merge_results(lexical, normalized, limit=limit)
