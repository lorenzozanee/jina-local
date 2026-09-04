import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_search_integrity.py"


def _load():
    spec = importlib.util.spec_from_file_location("bench_search_integrity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integrity_benchmark_rejects_fabricated_results():
    bench = _load()
    report = bench.evaluate([{
        "title": "synthetic",
        "url": "https://example.com/topics/fake",
        "content": "This result discusses fake in depth.",
    }], query="OpenCode docs")
    assert report["synthetic_results"] == 1
    assert report["accepted_results"] == 0
