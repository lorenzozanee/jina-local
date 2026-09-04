import importlib.util
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bench_search_live", ROOT / "scripts" / "bench_search_live.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def candidate(url, title="result", source="provider"):
    return {
        "title": title,
        "url": url,
        "content": "retrieved content",
        "source": source,
        "retrieved_at": "2026-09-04T00:00:00Z",
    }


def test_evaluator_rejects_unprovenanced_candidates():
    case = {
        "id": "official",
        "query": "Python documentation",
        "language": "en",
        "targets": ["https://docs.python.org/3/"],
        "results": [
            candidate("https://docs.python.org/3/"),
            {"title": "synthetic", "url": "https://example.invalid/"},
        ],
    }

    result = MODULE.evaluate_case(case)

    assert result["status"] == "FAIL"
    assert result["provenance"]["invalid_candidates"] == 1
    assert result["mrr"] == 1.0


def test_evaluator_computes_mrr_ndcg_and_source_coverage_from_canonical_urls():
    case = {
        "id": "multi",
        "query": "retrieval research",
        "language": "en",
        "targets": [
            "https://example.org/paper",
            "https://example.net/report",
        ],
        "required_sources": ["example.org", "example.net"],
        "results": [
            candidate("https://other.test/noise", source="other"),
            candidate("https://example.net/report#section", source="provider-b"),
            candidate("https://example.org/paper", source="provider-a"),
        ],
    }

    result = MODULE.evaluate_case(case)

    assert result["status"] == "PASS"
    assert result["mrr"] == 0.5
    expected_ndcg = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert round(result["ndcg_at_5"], 6) == round(expected_ndcg, 6)
    assert result["source_coverage"] == 1.0
    assert result["target_hits"] == 2
    assert all(label["retrieved"] for label in result["target_labels"])


def test_evaluator_requires_chinese_english_labels_and_multi_source_targets():
    cases = [
        {
            "id": "zh-en",
            "query": "Python 官方文档 official documentation",
            "language": "zh-en",
            "targets": ["https://docs.python.org/3/"],
            "results": [candidate("https://docs.python.org/3/")],
        },
        {
            "id": "multi-source",
            "query": "research",
            "language": "en",
            "targets": ["https://a.test/one", "https://b.test/two"],
            "required_sources": ["a.test", "b.test"],
            "results": [
                candidate("https://a.test/one", source="a"),
                candidate("https://b.test/two", source="b"),
            ],
        },
    ]

    summary = MODULE.evaluate_corpus(cases)

    assert summary["status"] == "PASS"
    assert summary["languages"] == ["en", "zh-en"]
    assert summary["multi_source_cases"] == 1
    assert summary["source_coverage"] == 1.0


def test_unavailable_query_cannot_be_reported_as_success():
    case = {
        "id": "unavailable",
        "query": "missing",
        "language": "en",
        "targets": ["https://docs.example.org/"],
        "provider_status": {"state": "unavailable", "code": "NO_RETRIEVAL_BACKEND"},
        "results": [],
    }

    result = MODULE.evaluate_case(case)

    assert result["status"] == "FAIL"
    assert "NO_RETRIEVAL_BACKEND" in result["failure_codes"]


def test_live_opt_in_is_required_before_runner_can_make_requests(monkeypatch, capsys):
    monkeypatch.delenv("JINA_LOCAL_LIVE_SEARCH", raising=False)

    assert MODULE.main([]) != 0
    assert "JINA_LOCAL_LIVE_SEARCH=1" in capsys.readouterr().out
