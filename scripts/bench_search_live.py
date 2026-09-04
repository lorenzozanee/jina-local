"""Opt-in live evaluation for provenance-aware local search."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

CORPUS_VERSION = "2026-09-04.v1"
RUNS = 3
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/tmp/opencode/jina-local"))
OUTPUT_PREFIX = "search-live-"

CORPUS = [
    {
        "id": "python-official",
        "query": "Python official documentation tutorial",
        "language": "en",
        "targets": ["https://docs.python.org/3/"],
        "required_sources": ["docs.python.org"],
    },
    {
        "id": "docker-site",
        "query": "site:docs.docker.com compose file reference",
        "language": "en",
        "targets": ["https://docs.docker.com/reference/compose-file/"],
        "required_sources": ["docs.docker.com"],
    },
    {
        "id": "multi-source-research",
        "query": "retrieval augmented generation survey research",
        "language": "en",
        "targets": [
            "https://arxiv.org/abs/2005.11401",
            "https://research.google/pubs/retrieval-augmented-generation-for-knowledge-intensive-nlp-tasks/",
        ],
        "required_sources": ["arxiv.org", "research.google"],
    },
    {
        "id": "zh-en",
        "query": "Python 官方文档 official documentation",
        "language": "zh-en",
        "targets": ["https://docs.python.org/3/"],
        "required_sources": ["docs.python.org"],
    },
]


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), host, path, parsed.query, ""))


def _provenanced(candidate: dict) -> bool:
    return all(isinstance(candidate.get(field), str) and candidate[field].strip() for field in ("title", "url", "content", "source", "retrieved_at")) and urlsplit(candidate["url"]).scheme in {"http", "https"}


def evaluate_case(case: dict) -> dict:
    results = case.get("results") or []
    invalid = [item for item in results if not isinstance(item, dict) or not _provenanced(item)]
    valid = [item for item in results if isinstance(item, dict) and _provenanced(item)]
    target_urls = [canonical_url(target) for target in case.get("targets", [])]
    target_set = set(target_urls)
    raw_top = results[:5]
    ranks = [index + 1 for index, item in enumerate(raw_top) if isinstance(item, dict) and _provenanced(item) and canonical_url(item["url"]) in target_set]
    mrr = 1 / ranks[0] if ranks else 0.0
    gains = [1 if isinstance(item, dict) and _provenanced(item) and canonical_url(item["url"]) in target_set else 0 for item in raw_top]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = [1] * min(len(target_set), 5)
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    ndcg = dcg / idcg if idcg else 0.0
    required_sources = {str(source).strip() for source in case.get("required_sources", []) if str(source).strip()}
    found_sources = {item["source"].strip() for item in valid if item["source"].strip()}
    coverage = len(found_sources & required_sources) / len(required_sources) if required_sources else 1.0
    failures = []
    provider_status = case.get("provider_status") or {}
    if provider_status.get("code"):
        failures.append(provider_status["code"])
    if provider_status.get("state") in {"unavailable", "error"} and "NO_RETRIEVAL_BACKEND" not in failures:
        failures.append("NO_RETRIEVAL_BACKEND")
    if invalid:
        failures.append("INVALID_PROVENANCE")
    if not ranks:
        failures.append("TARGET_NOT_RETRIEVED")
    if required_sources and coverage < 1.0:
        failures.append("SOURCE_COVERAGE")
    return {
        "id": case["id"],
        "query": case["query"],
        "language": case["language"],
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": list(dict.fromkeys(failures)),
        "provenance": {"candidate_count": len(results), "valid_candidates": len(valid), "invalid_candidates": len(invalid)},
        "target_hits": len(set(canonical_url(item["url"]) for item in valid) & target_set),
        "target_labels": [{"url": target, "retrieved": target in {canonical_url(item["url"]) for item in valid}} for target in target_urls],
        "mrr": round(mrr, 6),
        "ndcg_at_5": round(ndcg, 6),
        "source_coverage": round(coverage, 6),
    }


def evaluate_corpus(cases: list[dict]) -> dict:
    evaluated = [evaluate_case(case) for case in cases]
    return {
        "status": "PASS" if all(item["status"] == "PASS" for item in evaluated) else "FAIL",
        "case_results": evaluated,
        "languages": sorted({item["language"] for item in cases}),
        "multi_source_cases": sum(1 for item in cases if len(item.get("required_sources", [])) > 1),
        "mrr": round(sum(item["mrr"] for item in evaluated) / len(evaluated), 6) if evaluated else 0.0,
        "ndcg_at_5": round(sum(item["ndcg_at_5"] for item in evaluated) / len(evaluated), 6) if evaluated else 0.0,
        "source_coverage": round(sum(item["source_coverage"] for item in evaluated) / len(evaluated), 6) if evaluated else 0.0,
    }


_SECRET_PATTERN = re.compile(r"(?i)\b(?:bearer\s+|(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|password|secret)\s*[=:]\s*)[^\s,;]+")


def _redacted_text(value: object, limit: int) -> str:
    text = str(value)
    return _SECRET_PATTERN.sub("[REDACTED]", text)[:limit]


def _safe_archive_url(value: object) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    port = parsed.port
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def _sanitized(candidate: dict) -> dict:
    return {"title": _redacted_text(candidate.get("title", ""), 500), "url": _safe_archive_url(candidate.get("url", "")), "content": _redacted_text(candidate.get("content", ""), 2000), "source": _redacted_text(candidate.get("source", ""), 200), "retrieved_at": _redacted_text(candidate.get("retrieved_at", ""), 64)}


def _search_case(case: dict) -> dict:
    from search_deep import search_web_deep

    started = time.perf_counter()
    try:
        results = search_web_deep(case["query"], num=5)
        return {**case, "results": [_sanitized(item) for item in results], "provider_status": {"state": "ok"}, "latency_seconds": round(time.perf_counter() - started, 6)}
    except Exception as exc:
        code = "NO_RETRIEVAL_BACKEND" if "NO_RETRIEVAL_BACKEND" in str(exc) else "SEARCH_ERROR"
        return {**case, "results": [], "provider_status": {"state": "unavailable", "code": code}, "latency_seconds": round(time.perf_counter() - started, 6)}


@contextmanager
def _llm_disabled():
    names = ("JINA_LOCAL_LLM_BASE_URL", "JINA_LOCAL_LLM_MODEL", "JINA_LOCAL_LLM_API_KEY")
    old = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in old.items():
            if value is not None:
                os.environ[name] = value


def _llm_configured() -> bool:
    return all(os.getenv(name) for name in ("JINA_LOCAL_LLM_BASE_URL", "JINA_LOCAL_LLM_MODEL", "JINA_LOCAL_LLM_API_KEY"))


def run_live() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-gateway" / "src"))
    runs = []
    for run_number in range(1, RUNS + 1):
        with _llm_disabled():
            baseline_cases = [_search_case(case) for case in copy.deepcopy(CORPUS)]
        baseline = evaluate_corpus(baseline_cases)
        entry = {"run": run_number, "baseline": baseline, "evidence": baseline_cases}
        if _llm_configured():
            enhanced_cases = [_search_case(case) for case in copy.deepcopy(CORPUS)]
            enhanced = evaluate_corpus(enhanced_cases)
            entry["enhanced"] = enhanced
            entry["comparison"] = {"mrr_delta": round(enhanced["mrr"] - baseline["mrr"], 6), "ndcg_at_5_delta": round(enhanced["ndcg_at_5"] - baseline["ndcg_at_5"], 6), "preserves_baseline": enhanced["mrr"] >= baseline["mrr"] and enhanced["ndcg_at_5"] >= baseline["ndcg_at_5"]}
        runs.append(entry)
    return {"corpus_version": CORPUS_VERSION, "runs_required": RUNS, "llm_enabled": _llm_configured(), "runs": runs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(CACHE_DIR))
    args = parser.parse_args(argv)
    if os.getenv("JINA_LOCAL_LIVE_SEARCH") != "1":
        print("JINA_LOCAL_LIVE_SEARCH=1 is required for live search evaluation")
        return 2
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_live()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"{OUTPUT_PREFIX}{timestamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if report.get("runs") and all(
        run.get("baseline", {}).get("status") == "PASS"
        and run.get("enhanced", {"status": "PASS"}).get("status") == "PASS"
        for run in report["runs"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
