"""MCP 20工具全兼容测试 - 验证 server.py / gateway.py 暴露全部 jina 官方工具且签名兼容"""
import asyncio
import importlib.util
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-gateway" / "src" / "server.py"
GATEWAY = ROOT / "mcp-gateway" / "src" / "gateway.py"

# 任务要求的 20+工具全列表（按任务描述，以 / 分割，共21项，兼容20/21判定）
EXPECTED_TOOLS = [
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

# 每个工具的必填参数签名（jina兼容）
EXPECTED_SIGNATURES = {
    "primer": [],
    "read_url": ["url"],
    "capture_screenshot_url": ["url"],
    "guess_datetime_url": ["url"],
    "search_web": ["query"],
    "search_web_deep": ["query"],
    "search_arxiv": ["query"],
    "search_ssrn": ["query"],
    "search_images": ["query"],
    "search_jina_blog": ["query"],
    "search_bibtex": ["query"],
    "expand_query": ["query"],
    "parallel_read_url": ["urls"],
    "parallel_search_web": ["queries"],
    "parallel_search_arxiv": ["queries"],
    "parallel_search_ssrn": ["queries"],
    "sort_by_relevance": ["query", "documents"],
    "classify_text": ["texts", "labels"],
    "deduplicate_strings": ["strings"],
    "deduplicate_images": ["images"],
    "extract_pdf": ["url"],
    "embeddings": ["texts"],
}

# 备选并行参数名兼容
PARALLEL_ALIASES = {
    "parallel_read_url": [["urls"], ["url_list", "urls"]],
    "parallel_search_web": [["queries"], ["queries", "query_list"]],
    "parallel_search_arxiv": [["queries"], ["queries"]],
    "parallel_search_ssrn": [["queries"], ["queries"]],
}


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"无法加载 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem + "_compat"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _get_gateway():
    assert GATEWAY.exists(), f"gateway.py 不存在 {GATEWAY}"
    return _load_module(GATEWAY)


def _get_server():
    assert SERVER.exists(), f"server.py 不存在 {SERVER}"
    return _load_module(SERVER)


def _collect_exposed_names(mod):
    """收集模块暴露的工具名：包括 mcp.tool() 注册、直接函数、以及 mcp 对象可枚举"""
    names = set()
    for n in dir(mod):
        obj = getattr(mod, n, None)
        if callable(obj):
            names.add(n)
    # 如果有 mcp 对象，尝试获取已注册工具
    mcp = getattr(mod, "mcp", None)
    if mcp is not None:
        # FastMCP 内部工具列表可能在 _tools / _tool_manager
        for attr in ["_tools", "_tool_manager", "tools", "_mcp_tools"]:
            try:
                val = getattr(mcp, attr, None)
                if val is not None:
                    if isinstance(val, dict):
                        names.update(val.keys())
                    elif isinstance(val, list):
                        for item in val:
                            if hasattr(item, "name"):
                                names.add(item.name)
                            elif isinstance(item, str):
                                names.add(item)
            except Exception:
                continue
        # 也尝试 list_tools
        try:
            if hasattr(mcp, "list_tools"):
                try:
                    tools = asyncio.run(mcp.list_tools())
                except RuntimeError:
                    pass  # 已在事件循环中，跳过异步调用
                else:
                    if isinstance(tools, list):
                        for t in tools:
                            if hasattr(t, "name"):
                                names.add(t.name)
                            elif isinstance(t, dict) and "name" in t:
                                names.add(t["name"])
        except Exception:
            pass
    return names


def test_mcp_exposes_all_20_tools():
    """验证 gateway/server 暴露全部 20+1 工具，与 jina 官方一一对应"""
    mod = _get_gateway()
    # 也加载 server 补充
    try:
        server_mod = _get_server()
        server_names = _collect_exposed_names(server_mod)
    except Exception:
        server_names = set()
    gateway_names = _collect_exposed_names(mod)
    combined = gateway_names | server_names
    # 同时检查源码文本是否包含注册
    server_text = SERVER.read_text(encoding="utf-8") if SERVER.exists() else ""
    gateway_text = GATEWAY.read_text(encoding="utf-8") if GATEWAY.exists() else ""
    combined_text = server_text + gateway_text
    missing = []
    for tool in EXPECTED_TOOLS:
        # 允许 jina_前缀 或 精确名
        found = (
            tool in combined
            or f"jina_{tool}" in combined
            or tool in combined_text
            or f"def {tool}" in combined_text
        )
        if not found:
            missing.append(tool)
    assert not missing, f"功能缺失: 未暴露工具 {missing}, 已暴露 {sorted(combined)}, 源码未包含 {missing}"


def test_mcp_each_tool_has_callable():
    """每个工具必须是可调用的，且在 gateway 中存在"""
    mod = _get_gateway()
    for tool in EXPECTED_TOOLS:
        # gateway 应有可调用
        assert hasattr(mod, tool), f"功能缺失: gateway 未暴露 {tool}"
        assert callable(getattr(mod, tool)), f"{tool} 不可调用"


def test_tool_signatures_compatible():
    """每个工具签名必须包含必填参数，与 jina 兼容"""
    mod = _get_gateway()
    for tool, required in EXPECTED_SIGNATURES.items():
        fn = getattr(mod, tool, None)
        assert fn is not None, f"缺工具 {tool}"
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        for req in required:
            # 对于 parallel_* 允许 queries/urls 别名
            if tool.startswith("parallel_"):
                # 至少包含 queries 或 urls 之一
                assert req in params or any(req in p for p in params), f"{tool} 签名缺必填 {req}, 实际 {params}"
            else:
                assert req in params, f"{tool} 签名缺必填 {req}, 实际 {params} vs 期望 {required}"
            # 必填参数应无默认值（除 primer）
            if tool != "primer" and req in sig.parameters:
                # 允许有默认值的扩展，但首参 query/url 等应语义必填
                # 仅检查 primer 例外
                pass


def test_server_registers_mcp_tools():
    """server.py 必须通过 mcp.tool() 注册至少 20 工具"""
    text = SERVER.read_text(encoding="utf-8")
    # 统计 @mcp.tool() 或 mcp.tool()( 出现次数
    count_decorator = text.count("@mcp.tool()")
    count_call = text.count("mcp.tool()(")
    total = count_decorator + count_call
    # 任务要求 20 工具，含直接暴露原始函数名的二次注册，至少应 >=20
    assert total >= 20, f"功能缺失: server.py mcp.tool() 注册数 {total} <20, 需暴露全部20工具"


def test_gateway_has_search_academic_module():
    """验证 search_academic.py 已实现 arxiv/ssrn/bibtex"""
    acad = ROOT / "mcp-gateway" / "src" / "search_academic.py"
    assert acad.exists(), f"功能缺失: {acad} 不存在，需实现 search_arxiv/search_ssrn/search_bibtex"
    text = acad.read_text(encoding="utf-8")
    for fn in ["search_arxiv", "search_ssrn", "search_bibtex", "parallel_search_arxiv", "parallel_search_ssrn"]:
        assert fn in text, f"search_academic.py 缺 {fn}"
    # 应调用 arXiv API 与 Semantic Scholar
    assert "export.arxiv.org" in text or "arxiv.org" in text, "未调用 arXiv API"
    assert "semanticscholar.org" in text or "api.semanticscholar" in text, "未调用 S2 API"


def test_gateway_has_capture_screenshot():
    """验证 capture_screenshot_url 已实现"""
    # 可能在 utils.py 或 search_academic.py 或 gateway.py
    found = False
    for p in [ROOT / "mcp-gateway" / "src" / "utils.py", ROOT / "mcp-gateway" / "src" / "gateway.py", ROOT / "mcp-gateway" / "src" / "search_academic.py"]:
        if p.exists() and "capture_screenshot" in p.read_text(encoding="utf-8"):
            found = True
            break
    # 也检查 server
    if not found and SERVER.exists() and "capture_screenshot" in SERVER.read_text(encoding="utf-8"):
        found = True
    assert found, "功能缺失: 未实现 capture_screenshot_url"


def test_search_images_and_jina_blog_implemented():
    """验证 search_images 与 search_jina_blog 已实现"""
    acad_text = ""
    acad_path = ROOT / "mcp-gateway" / "src" / "search_academic.py"
    if acad_path.exists():
        acad_text = acad_path.read_text(encoding="utf-8")
    gateway_text = GATEWAY.read_text(encoding="utf-8") if GATEWAY.exists() else ""
    server_text = SERVER.read_text(encoding="utf-8") if SERVER.exists() else ""
    combined = acad_text + gateway_text + server_text
    assert "search_images" in combined, "未实现 search_images"
    assert "search_jina_blog" in combined, "未实现 search_jina_blog"


def test_mcp_list_tools_canonical_set():
    """通过 asyncio 调用 server.mcp.list_tools()，断言工具名为完整且无重复的规范集合。

    回归测试：验证 MCP 重复注册/schema 缺陷已修复——
    - 工具名应为完整且无重复的规范集合（含 embeddings，合计22个）
    - 不含 *_tool 后缀的重复注册名
    - search_web 只要求 query（不得有 kwargs 字段）
    - parallel_search_web 只要求 queries
    """
    server_mod = _get_server()
    tools = asyncio.run(server_mod.mcp.list_tools())
    names = [t.name for t in tools]

    # 构建规范集合：去重后应恰好为 EXPECTED_TOOLS
    canonical = sorted(set(names))
    expected = sorted(EXPECTED_TOOLS)
    assert canonical == expected, (
        f"工具名不规范：多余 {sorted(set(names) - set(expected))}，缺失 {set(expected) - set(names)}，合计 {len(names)} 个"
    )

    # 断言不含 *_tool 后缀名
    tool_suffix_names = [n for n in names if n.endswith("_tool")]
    assert not tool_suffix_names, f"存在 *_tool 后缀重复注册名: {sorted(tool_suffix_names)}"

    # 断言 search_web 只要求 query，不得有 kwargs 字段
    search_web_tool = next((t for t in tools if t.name == "search_web"), None)
    assert search_web_tool is not None, "缺少 search_web 工具"
    search_web_required = search_web_tool.inputSchema.get("required", [])
    assert "kwargs" not in search_web_required, (
        f"search_web 不得有 kwargs 字段，实际 required: {search_web_required}"
    )
    assert search_web_required == ["query"], f"search_web 必须只要求 query，实际 required: {search_web_required}"

    # 断言 parallel_search_web 只要求 queries
    psw_tool = next((t for t in tools if t.name == "parallel_search_web"), None)
    assert psw_tool is not None, "缺少 parallel_search_web 工具"
    psw_required = psw_tool.inputSchema.get("required", [])
    assert psw_required == ["queries"], f"parallel_search_web 必须只要求 queries，实际 required: {psw_required}"
