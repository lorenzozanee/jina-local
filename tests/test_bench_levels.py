"""test_bench_levels.py: 多层次评测四层验证（L1-L4）

校验 docs/bench-full.md 已显式分为四层：
- L1 工具级（22 工具逐项）
- L2 维度级（5 维度雷达）
- L3 系统级（125 测试 + MCP 全兼容）
- L4 硬件级（GPU 显存/并发 + 空间占用）

对应 AGENTS.md 第7节与 issue-4 要求，若缺 L4 需追加硬件级章节引用 docs/gpu-optimization.md 与 space 数据。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "bench-full.md"
GPU_DOC = ROOT / "docs" / "gpu-optimization.md"
SPACE_DOC = ROOT / "docs" / "space-optimization.md"

# 22 工具名单（与 bench-full.md 一致）
ALL_22 = [
    "primer",
    "read_url",
    "capture_screenshot_url",
    "guess_datetime_url",
    "search_web",
    "search_web_deep",
    "search_arxiv",
    "search_ssrn",
    "search_images",
    "search_jina_blog",
    "search_bibtex",
    "expand_query",
    "parallel_read_url",
    "parallel_search_web",
    "parallel_search_arxiv",
    "parallel_search_ssrn",
    "sort_by_relevance",
    "classify_text",
    "deduplicate_strings",
    "deduplicate_images",
    "extract_pdf",
    "embeddings",
]


def _text():
    assert DOC.exists(), f"{DOC} 不存在"
    return DOC.read_text(encoding="utf-8")


def test_l1_tool_level_present():
    """L1 工具级：含 22 工具表与 22/22、L1 标记"""
    t = _text()
    assert "L1" in t and "工具级" in t, "bench-full.md 缺 L1 工具级标题"
    assert "22" in t and "工具" in t, "bench-full.md 缺 22 工具说明"
    assert "22/22" in t, "bench-full.md 缺 22/22 通过标记"
    # 22 工具表存在：表头与至少前5个工具名
    assert "22 工具" in t or "22工具" in t or "工具总体对比" in t
    for name in ["primer", "read_url", "search_web", "sort_by_relevance", "extract_pdf"]:
        assert name in t, f"bench-full.md 22 工具表缺 {name}"
    hit = sum(1 for n in ALL_22 if n in t)
    assert hit == len(ALL_22), f"bench-full.md 22 工具命中仅 {hit}/{len(ALL_22)}"


def test_l2_dimension_level_present():
    """L2 维度级：含 5 维度表、雷达、L2 标记"""
    t = _text()
    assert "L2" in t and "维度级" in t, "bench-full.md 缺 L2 维度级标题"
    assert "5 维度" in t or "5维度" in t or "5/5" in t, "bench-full.md 缺 5 维度说明"
    assert "5/5" in t, "bench-full.md 缺 5/5 维度通过标记"
    # 5 维度表头与雷达关键词
    assert "雷达" in t, "bench-full.md 缺 雷达图/雷达关键词"
    for dim in ["延迟", "相关性", "成功率", "成本", "离线"]:
        assert dim in t, f"bench-full.md 5 维度表缺 {dim}"
    # 分数对标本地 vs jina
    assert "9.74" in t or "9.2" in t, "bench-full.md 缺本地分数"
    assert "jina" in t.lower(), "bench-full.md 缺 jina 对标"


def test_l3_system_level_present():
    """L3 系统级：含 125 测试 + MCP 全兼容、L3 标记"""
    t = _text()
    assert "L3" in t and "系统级" in t, "bench-full.md 缺 L3 系统级标题"
    assert "125" in t, "bench-full.md 缺 125 测试数"
    assert "passed" in t or "通过" in t, "bench-full.md 缺 passed/通过说明"
    # MCP 全兼容关键词
    assert "MCP" in t, "bench-full.md L3 缺 MCP 关键词"
    assert "全兼容" in t or "兼容" in t, "bench-full.md L3 缺 全兼容/兼容关键词"
    # 提及测试覆盖或 pytest
    assert "pytest" in t or "测试" in t, "bench-full.md L3 缺 pytest/测试关键词"


def test_l4_hardware_level_present():
    """L4 硬件级：含 GPU 显存/并发 + 空间占用、L4 标记，引用 gpu-optimization.md 与 space 数据"""
    t = _text()
    assert "L4" in t and "硬件级" in t, "bench-full.md 缺 L4 硬件级标题"
    # GPU 显存/并发关键词
    assert "GPU" in t, "bench-full.md L4 缺 GPU 关键词"
    assert "显存" in t, "bench-full.md L4 缺 显存关键词"
    assert "并发" in t, "bench-full.md L4 缺 并发关键词"
    # 空间占用关键词
    assert "空间" in t, "bench-full.md L4 缺 空间关键词"
    assert "space" in t.lower() or "空间占用" in t, "bench-full.md L4 缺 space/空间占用关键词"
    # 引用 docs
    assert "gpu-optimization.md" in t, "bench-full.md L4 未引用 docs/gpu-optimization.md"
    assert "space-optimization.md" in t or "bench-space" in t or "/tmp/jina-local-bench-space" in t, "bench-full.md L4 未引用 space 数据"
    # 硬件数值：RTX 5070 / 12GB / ~5GB 常驻
    assert "5070" in t or "12GB" in t or "5GB" in t or "RTX" in t, "bench-full.md L4 缺硬件数值（RTX 5070/12GB/5GB）"


def test_four_levels_structure_complete():
    """四层结构完整性：bench-full.md 同时含 L1-L4 且硬件级引用两份 docs 存在"""
    t = _text()
    for lv in ["L1", "L2", "L3", "L4"]:
        assert lv in t, f"bench-full.md 缺 {lv}"
    for kw in ["工具级", "维度级", "系统级", "硬件级"]:
        assert kw in t, f"bench-full.md 缺 {kw}"
    assert GPU_DOC.exists(), f"{GPU_DOC} 不存在"
    assert SPACE_DOC.exists(), f"{SPACE_DOC} 不存在"
    # 四层与实现文件的闭环
    assert "bench_full.py" in t or "scripts/bench_full.py" in t, "bench-full.md 缺实现文件引用"
