"""Evaluate search-result provenance without contacting external search providers."""
from __future__ import annotations

import json
from pathlib import Path


REQUIRED_FIELDS = ("title", "url", "content", "source", "retrieved_at")


def evaluate(candidates: list[dict], query: str) -> dict:
    accepted = [candidate for candidate in candidates if all(candidate.get(field) for field in REQUIRED_FIELDS)]
    return {
        "query": query,
        "candidate_results": len(candidates),
        "accepted_results": len(accepted),
        "synthetic_results": len(candidates) - len(accepted),
    }


if __name__ == "__main__":
    report = evaluate([], "")
    Path("/tmp/jina-local-search-integrity.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
