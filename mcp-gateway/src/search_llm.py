import json
import os

import requests


_MAX_QUERIES = 5
_DEFAULT_TIMEOUT = 20.0
_MAX_TIMEOUT = 120.0


def _configuration():
    base_url = os.getenv("JINA_LOCAL_LLM_BASE_URL", "").strip()
    model = os.getenv("JINA_LOCAL_LLM_MODEL", "").strip()
    api_key = os.getenv("JINA_LOCAL_LLM_API_KEY", "").strip()
    if not base_url or not model or not api_key:
        return None
    return base_url.rstrip("/"), model, api_key


def is_enabled() -> bool:
    return _configuration() is not None


def _timeout() -> float:
    try:
        value = float(os.getenv("JINA_LOCAL_LLM_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    return min(max(value, 0.1), _MAX_TIMEOUT)


def _request_schema(name, properties, required):
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _completion(configuration, instruction, response_format):
    base_url, model, api_key = configuration
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "user", "content": instruction},
            ],
            "temperature": 0,
            "response_format": response_format,
        },
        timeout=_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("invalid completion content")
    return json.loads(content)


def plan_queries(query: str) -> list[str]:
    configuration = _configuration()
    if configuration is None or not isinstance(query, str) or not query.strip():
        return []
    response_format = _request_schema(
        "search_query_plan",
        {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": _MAX_QUERIES,
            }
        },
        ["queries"],
    )
    try:
        result = _completion(
            configuration,
            f"Generate alternative web search queries for this query only: {query}",
            response_format,
        )
        if not isinstance(result, dict) or set(result) != {"queries"}:
            raise ValueError("invalid query response")
        queries = result["queries"]
        if not isinstance(queries, list) or len(queries) > _MAX_QUERIES:
            raise ValueError("invalid query list")
        normalized = []
        seen = set()
        for item in queries:
            if not isinstance(item, str):
                raise ValueError("invalid query")
            item = item.strip()
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
            if len(normalized) == _MAX_QUERIES:
                break
        return normalized
    except Exception:
        return []


def rerank_ids(query: str, candidates: list[dict]) -> list[str] | None:
    configuration = _configuration()
    if configuration is None or not isinstance(query, str) or not isinstance(candidates, list):
        return None
    candidate_ids = []
    ranking_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            return None
        candidate_id = candidate["id"]
        if candidate_id in candidate_ids:
            return None
        candidate_ids.append(candidate_id)
        ranking_candidates.append(
            {
                key: candidate[key]
                for key in ("id", "title", "url", "content")
                if key in candidate
            }
        )
    response_format = _request_schema(
        "search_candidate_ranking",
        {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": len(candidate_ids),
                "maxItems": len(candidate_ids),
            }
        },
        ["ids"],
    )
    try:
        result = _completion(
            configuration,
            json.dumps(
                {"query": query, "candidates": ranking_candidates},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            response_format,
        )
        if not isinstance(result, dict) or set(result) != {"ids"}:
            return None
        ids = result["ids"]
        if not isinstance(ids, list) or len(ids) != len(candidate_ids):
            return None
        if not all(isinstance(item, str) for item in ids):
            return None
        if set(ids) != set(candidate_ids) or len(set(ids)) != len(candidate_ids):
            return None
        return ids
    except Exception:
        return None
