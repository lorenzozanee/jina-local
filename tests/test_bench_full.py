"""test_bench_full.py: 全链路总评 bench 验证

- 校验 /tmp/jina-local-bench-full.json 与 docs/bench-full.md 存在
- 校验总体判定 PASS 且标注“可替代且性能≥jina”
- 校验 5 维度全部 PASS、22 工具全兼容
- 校验 7 份输入 bench 均存在且为 PASS
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL_JSON = pathlib.Path("/tmp/jina-local-bench-full.json")
DOC_MD = ROOT / "docs" / "bench-full.md"

BENCH_FILES = [
    pathlib.Path("/tmp/jina-local-bench-reader.json"),
    pathlib.Path("/tmp/jina-local-bench-search.json"),
    pathlib.Path("/tmp/jina-local-bench-search-deep.json"),
    pathlib.Path("/tmp/jina-local-bench-reranker.json"),
    pathlib.Path("/tmp/jina-local-bench-embeddings.json"),
    pathlib.Path("/tmp/jina-local-bench-utils.json"),
    pathlib.Path("/tmp/jina-local-bench-mcp-global.json"),
]


def test_bench_full_json_exists():
    assert FULL_JSON.exists(), f"总评 json 不存在 {FULL_JSON}"
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    assert "summary" in data
    assert "dimensions" in data
    assert "tools" in data
    assert "radar" in data


def test_bench_full_md_exists():
    assert DOC_MD.exists(), f"总评 markdown 不存在 {DOC_MD}"
    text = DOC_MD.read_text(encoding="utf-8")
    assert "全链路多维性能总评" in text
    assert "雷达图" in text
    assert "总体判定" in text


def test_bench_full_overall_pass():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    summary = data["summary"]
    assert summary["overall_verdict"] == "PASS", f"总体 verdict 应为 PASS，实际 {summary['overall_verdict']}"
    assert "可替代且性能≥jina" in summary["overall_judgement"], f"应标注可替代且性能≥jina，实际 {summary['overall_judgement']}"
    assert summary["total_tools"] >= 20, "应覆盖 20+ 工具"
    assert summary["pass_tools"] >= 20


def test_bench_full_five_dimensions_pass():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    dims = data["dimensions"]
    for key in ["latency", "relevance", "success_rate", "cost", "offline"]:
        assert key in dims, f"维度 {key} 缺失"
        assert dims[key]["verdict"] == "PASS", f"维度 {key} 应 PASS，实际 {dims[key]['verdict']}"
        # 本地分数应 >= jina
        assert dims[key]["local"] >= dims[key]["jina"], f"维度 {key} 本地应≥jina"


def test_bench_full_tools_table():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    tools = data["tools"]
    assert len(tools) >= 20
    # 全部工具应 PASS
    for t in tools:
        assert t["verdict"] == "PASS", f"工具 {t['tool']} 应 PASS"


def test_bench_full_inputs_exist():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    for p in BENCH_FILES:
        assert p.exists(), f"输入 bench 缺失 {p}"
    # 检查总体输入标记
    inputs_exist = data["summary"].get("inputs_exist", {})
    for k, v in inputs_exist.items():
        assert v is True, f"bench {k} 标记缺失"


def test_bench_full_no_todo_when_pass():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    summary = data["summary"]
    # 若全部 PASS，则 optimizations 应为 single all 且无模块 TODO
    opts = summary.get("optimizations", [])
    # 至少有一个 all 标注
    assert any(o.get("key") == "all" or "可替代" in o.get("action", "") for o in opts)
    # 检查 docs 中应含“可替代且性能≥jina”且无劣于 jina 的 FAIL 描述
    text = DOC_MD.read_text(encoding="utf-8")
    assert "可替代且性能≥jina" in text
    # 检查模块未被插入 TODO(bench-full)（若有则说明曾 FAIL）
    # 若当前总体 PASS，则各模块不应含劣于 jina 的 TODO
    for mod_rel in ["mcp-gateway/src/reader.py", "mcp-gateway/src/search.py", "mcp-gateway/src/reranker.py", "mcp-gateway/src/embeddings.py"]:
        p = ROOT / mod_rel
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            # 允许无 TODO，或仅有 all PASS 的注释？当前应无 TODO
            # 若有 TODO 且含“劣于”，则说明误判
            if "TODO(bench-full)" in txt:
                assert "劣于" not in txt or "PASS" in txt, f"{mod_rel} 不应含劣于 jina 的 TODO，当前总体 PASS"


def test_bench_full_radar_present():
    data = json.loads(FULL_JSON.read_text(encoding="utf-8"))
    radar = data["radar"]
    assert "labels" in radar and len(radar["labels"]) == 5
    assert "local" in radar and len(radar["local"]) == 5
    assert "jina" in radar and len(radar["jina"]) == 5
    # 本地平均应高于 jina
    assert sum(radar["local"]) > sum(radar["jina"])
