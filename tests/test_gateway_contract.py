"""MCP Gateway 工具契约测试 - 对齐 jina 兼容 schema

验证 mcp-gateway/src/gateway.py 或 server.py 需暴露
read_url / search_web / sort_by_relevance 三大工具，
且输入输出 schema 与 jina 一致。
TDD 红阶段：生产代码尚未实现，全部测试应 FAIL，失败原因为功能缺失。
"""
import importlib.util
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]
PYPROJECT = ROOT / "mcp-gateway" / "pyproject.toml"


def _resolve_gateway_path() -> pathlib.Path | None:
    for p in CANDIDATES:
        if p.exists() and p.is_file():
            return p
    return None


def _load_gateway_module():
    path = _resolve_gateway_path()
    assert path is not None, (
        f"功能缺失: mcp-gateway/src/gateway.py 或 server.py 不存在，"
        f"已检查 {CANDIDATES}，当前仅有 .gitkeep"
    )
    spec = importlib.util.spec_from_file_location("gateway", path)
    assert spec is not None and spec.loader is not None, f"功能缺失: 无法加载 gateway 模块 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gateway"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_gateway_entry_file_exists():
    """网关入口文件必须存在（gateway.py 或 server.py 二选一）"""
    path = _resolve_gateway_path()
    assert path is not None, (
        f"功能缺失: 未找到网关入口文件，期望 {CANDIDATES[0]} 或 {CANDIDATES[1]} 存在"
    )
    assert path.exists()


def test_gateway_module_is_importable():
    """网关模块应可被 import（验证 pyproject 依赖与模块可加载）"""
    # 体现 pyproject dependencies 为空导致 import 将失败的预期
    # 读取 pyproject 验证当前 dependencies 为空，说明实现缺失
    if PYPROJECT.exists():
        text = PYPROJECT.read_text(encoding="utf-8")
        # 当前骨架 dependencies = []，实现后应非空
        assert "dependencies = []" not in text, (
            "功能缺失: mcp-gateway/pyproject.toml dependencies 为空，"
            "网关依赖尚未声明，模块无法正常 import"
        )
    mod = _load_gateway_module()
    assert mod is not None


def test_gateway_exposes_read_url_tool():
    """网关需暴露 read_url 工具（兼容 jina read_url）"""
    mod = _load_gateway_module()
    assert hasattr(mod, "read_url"), "功能缺失: gateway 未暴露 read_url 工具"
    assert callable(getattr(mod, "read_url"))


def test_gateway_exposes_search_web_tool():
    """网关需暴露 search_web 工具（兼容 jina search_web）"""
    mod = _load_gateway_module()
    assert hasattr(mod, "search_web"), "功能缺失: gateway 未暴露 search_web 工具"
    assert callable(getattr(mod, "search_web"))


def test_gateway_surfaces_search_unavailability_without_mock_results(monkeypatch):
    """搜索模块无法加载时，网关必须让调用者看见失败而不是伪造结果。"""
    mod = _load_gateway_module()
    monkeypatch.setattr(mod, "_search_search_web", None)
    with pytest.raises(RuntimeError, match="NO_RETRIEVAL_BACKEND"):
        mod.search_web("OpenCode official documentation")


def test_gateway_exposes_sort_by_relevance_tool():
    """网关需暴露 sort_by_relevance 工具（兼容 jina sort_by_relevance）"""
    mod = _load_gateway_module()
    assert hasattr(mod, "sort_by_relevance"), "功能缺失: gateway 未暴露 sort_by_relevance 工具"
    assert callable(getattr(mod, "sort_by_relevance"))


def test_read_url_input_schema_requires_url():
    """read_url 输入 schema 必须包含必填 url 参数（与 jina 一致）"""
    mod = _load_gateway_module()
    fn = getattr(mod, "read_url")
    sig = inspect.signature(fn)
    assert "url" in sig.parameters, "功能缺失: read_url 缺少必填参数 url"
    param = sig.parameters["url"]
    assert param.default is inspect.Parameter.empty, "功能缺失: read_url 的 url 应为必填（无默认值）"


def test_search_web_input_schema_requires_query():
    """search_web 输入 schema 必须包含必填 query 参数"""
    mod = _load_gateway_module()
    fn = getattr(mod, "search_web")
    sig = inspect.signature(fn)
    assert "query" in sig.parameters, "功能缺失: search_web 缺少必填参数 query"
    assert sig.parameters["query"].default is inspect.Parameter.empty, "功能缺失: search_web 的 query 应为必填"


def test_sort_by_relevance_input_schema_requires_query_and_documents():
    """sort_by_relevance 输入 schema 必须包含必填 query + documents"""
    mod = _load_gateway_module()
    fn = getattr(mod, "sort_by_relevance")
    sig = inspect.signature(fn)
    assert "query" in sig.parameters, "功能缺失: sort_by_relevance 缺少必填参数 query"
    assert "documents" in sig.parameters, "功能缺失: sort_by_relevance 缺少必填参数 documents"
    assert sig.parameters["query"].default is inspect.Parameter.empty
    assert sig.parameters["documents"].default is inspect.Parameter.empty
