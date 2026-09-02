"""多 Agent 通用 MCP 测试 — 承接 server 多传输与 mcp.json

覆盖：
- test_mcp_json_exists_and_valid
- test_server_supports_transports
- test_setup_mcp_script_exists_and_help
- test_setup_mcp_all_agents_idempotent
- test_claude_config_format
- test_opencode_config_format
- test_server_tools_still_exposed
- test_readme_documents_multi_agent
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MCP_JSON = ROOT / "mcp.json"
SERVER = ROOT / "mcp-gateway" / "src" / "server.py"
SETUP_MCP = ROOT / "scripts" / "setup_mcp.py"
SETUP_GLOBAL = ROOT / "scripts" / "setup_global_mcp.py"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
CLAUDE_CONFIG = pathlib.Path.home() / ".config" / "claude" / "mcp.json"
OPENCODE_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"


def test_mcp_json_exists_and_valid():
    """项目根 mcp.json 合法，含 mcpServers.jina-local"""
    assert MCP_JSON.exists(), f"{MCP_JSON} 不存在，需提供通用 mcp.json"
    data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
    assert "mcpServers" in data, "mcp.json 缺 mcpServers"
    assert isinstance(data["mcpServers"], dict)
    assert "jina-local" in data["mcpServers"], f"mcpServers 缺 jina-local, 现有 {list(data['mcpServers'].keys())}"
    entry = data["mcpServers"]["jina-local"]
    assert "command" in entry, "jina-local 缺 command"
    assert entry["command"] == "python3", f"command 应为 python3, 实际 {entry['command']}"
    assert "args" in entry and isinstance(entry["args"], list)
    args_str = " ".join(entry["args"])
    assert "/home/cc/jina-local/mcp-gateway/src/server.py" in args_str, f"args 未指向 ~/jina-local/mcp-gateway/src/server.py, 实际 {entry['args']}"
    # env 可为 {} 允许
    assert "env" in entry
    assert isinstance(entry["env"], dict)


def test_server_supports_transports():
    """server.py --help 含 stdio/sse/http"""
    assert SERVER.exists(), f"{SERVER} 不存在"
    result = subprocess.run([sys.executable, str(SERVER), "--help"], capture_output=True, text=True, timeout=10)
    out = result.stdout + result.stderr
    assert result.returncode == 0, f"server --help 退出非0: {out}"
    for t in ["stdio", "sse", "http"]:
        assert t in out.lower(), f"--help 未包含传输 {t}, 输出: {out[:500]}"
    # 同时校验源码常量
    text = SERVER.read_text(encoding="utf-8")
    assert "SUPPORTED_TRANSPORTS" in text
    assert "stdio" in text and "sse" in text and "http" in text
    # 检查可导入常量
    import importlib.util
    spec = importlib.util.spec_from_file_location("server_universal", SERVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    assert hasattr(mod, "SUPPORTED_TRANSPORTS")
    transports = [x.lower() for x in getattr(mod, "SUPPORTED_TRANSPORTS")]
    for t in ["stdio", "sse", "http"]:
        assert t in transports or "streamable-http" in transports, f"SUPPORTED_TRANSPORTS 缺 {t}: {transports}"
    assert hasattr(mod, "_parse_args")
    assert hasattr(mod, "main")


def test_setup_mcp_script_exists_and_help():
    assert SETUP_MCP.exists(), f"{SETUP_MCP} 不存在"
    text = SETUP_MCP.read_text(encoding="utf-8")
    assert "opencode" in text and "claude" in text and "codex" in text
    result = subprocess.run([sys.executable, str(SETUP_MCP), "--help"], capture_output=True, text=True, timeout=10)
    out = result.stdout + result.stderr
    assert result.returncode == 0, f"setup_mcp --help 失败: {out}"
    assert "--agent" in out
    for a in ["opencode", "claude", "codex", "all"]:
        assert a in out.lower(), f"--help 未包含 agent {a}: {out[:500]}"


def test_setup_mcp_all_agents_idempotent():
    """run 两次不重复"""
    # 第一次
    r1 = subprocess.run([sys.executable, str(SETUP_MCP), "--agent", "all"], capture_output=True, text=True, timeout=15)
    assert r1.returncode == 0, f"第一次 all 失败: {r1.stdout} {r1.stderr}"
    # 快照
    mcp_before = json.loads(MCP_JSON.read_text(encoding="utf-8")) if MCP_JSON.exists() else {}
    opencode_before = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8")) if OPENCODE_CONFIG.exists() else {}
    claude_before = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8")) if CLAUDE_CONFIG.exists() else {}
    # 第二次
    r2 = subprocess.run([sys.executable, str(SETUP_MCP), "--agent", "all"], capture_output=True, text=True, timeout=15)
    assert r2.returncode == 0, f"第二次 all 失败: {r2.stdout} {r2.stderr}"
    mcp_after = json.loads(MCP_JSON.read_text(encoding="utf-8")) if MCP_JSON.exists() else {}
    opencode_after = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8")) if OPENCODE_CONFIG.exists() else {}
    claude_after = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8")) if CLAUDE_CONFIG.exists() else {}
    # mcp.json 不重复：只含一个 jina-local
    assert mcp_before == mcp_after, "mcp.json 两次运行后不一致，幂等失败"
    assert list(mcp_after.get("mcpServers", {}).keys()).count("jina-local") == 1
    # opencode 幂等
    if opencode_before and opencode_after:
        assert opencode_before == opencode_after, "opencode.json 两次运行不一致"
        # 检查无重复键（json dict 本身不会重复，但检查长度稳定）
        assert "jina-local" in opencode_after.get("mcp", {})
    # claude 幂等
    if claude_before and claude_after:
        assert claude_before == claude_after, "claude mcp.json 两次运行不一致"


def test_claude_config_format():
    """写入 ~/.config/claude/mcp.json 后合法"""
    r = subprocess.run([sys.executable, str(SETUP_MCP), "--agent", "claude"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"claude agent 写入失败: {r.stdout} {r.stderr}"
    assert CLAUDE_CONFIG.exists(), f"{CLAUDE_CONFIG} 不存在"
    data = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
    assert "mcpServers" in data, "claude mcp.json 缺 mcpServers"
    assert "jina-local" in data["mcpServers"], f"claude mcpServers 缺 jina-local: {list(data['mcpServers'].keys())}"
    entry = data["mcpServers"]["jina-local"]
    assert entry.get("command") == "python3"
    args_str = " ".join(entry.get("args", []))
    assert "/home/cc/jina-local/mcp-gateway/src/server.py" in args_str
    assert isinstance(entry.get("env", {}), dict)


def test_opencode_config_format():
    """opencode.json 含 jina-local local"""
    r = subprocess.run([sys.executable, str(SETUP_MCP), "--agent", "opencode"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"opencode agent 写入失败: {r.stdout} {r.stderr}"
    assert OPENCODE_CONFIG.exists(), f"{OPENCODE_CONFIG} 不存在"
    data = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    assert "mcp" in data, "opencode.json 缺 mcp"
    assert "jina-local" in data["mcp"], f"mcp 缺 jina-local: {list(data['mcp'].keys())}"
    entry = data["mcp"]["jina-local"]
    assert entry.get("type") == "local", f"type 应为 local, 实际 {entry.get('type')}"
    assert entry.get("enabled") is True
    cmd = entry.get("command", [])
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert "/home/cc/jina-local/mcp-gateway/src/server.py" in cmd_str, f"command 未指向 server.py: {cmd}"
    assert "worktree" not in cmd_str.lower()


def test_server_tools_still_exposed():
    """21 工具仍通过 test_mcp_compatibility"""
    # 直接复用兼容性测试逻辑
    import importlib.util
    GATEWAY = ROOT / "mcp-gateway" / "src" / "gateway.py"
    EXPECTED = [
        "primer", "read_url", "capture_screenshot_url", "guess_datetime_url",
        "search_web", "search_web_deep", "search_arxiv", "search_ssrn",
        "search_images", "search_jina_blog", "search_bibtex", "expand_query",
        "parallel_read_url", "parallel_search_web", "parallel_search_arxiv",
        "parallel_search_ssrn", "sort_by_relevance", "classify_text",
        "deduplicate_strings", "deduplicate_images", "extract_pdf",
    ]
    assert GATEWAY.exists()
    spec = importlib.util.spec_from_file_location("gateway_universal", GATEWAY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    for tool in EXPECTED:
        assert hasattr(mod, tool), f"gateway 缺工具 {tool}"
        assert callable(getattr(mod, tool))
    # server 注册数
    text = SERVER.read_text(encoding="utf-8")
    total = text.count("@mcp.tool()") + text.count("mcp.tool()(")
    assert total >= 20, f"server mcp.tool 注册数 {total} <20"


def test_readme_documents_multi_agent():
    """README 含多 Agent 章节"""
    assert README.exists()
    text = README.read_text(encoding="utf-8")
    # 章节标题
    assert "多 Agent 接入" in text, "README 缺 多 Agent 接入 章节标题"
    # 应提及通用与各 Agent
    for kw in ["mcp.json", "Claude Code", "Codex", "OpenClaw", "Hermes", "Opencode"]:
        assert kw.lower() in text.lower() or kw in text, f"README 多 Agent 章节缺关键词 {kw}"
    # 一键命令示例
    assert "claude mcp add jina-local" in text, "README 缺 claude mcp add 示例"
    assert "python3 /home/cc/jina-local/mcp-gateway/src/server.py" in text
    assert "~/.config/claude/mcp.json" in text or "~/.claude.json" in text
    assert "~/.codex/config.toml" in text or "codex mcp add" in text
    assert "~/.config/openclaw/mcp.json" in text
    assert "python scripts/setup_mcp.py --agent opencode" in text or "python scripts/setup_mcp.py --agent all" in text
    # 通用 mcp.json 示例
    assert "mcpServers" in text and "jina-local" in text
    # 多传输提及（README 或 AGENTS 至少一处）
    assert AGENTS.exists()
    agents_text = AGENTS.read_text(encoding="utf-8")
    combined = text + agents_text
    for t in ["stdio", "sse", "http"]:
        assert t in combined.lower(), f"文档未提及传输 {t}"
    # AGENTS 多 Agent 小节
    assert "多 Agent 通用" in agents_text, "AGENTS.md 缺 多 Agent 通用 小节"
    assert "~/jina-local" in agents_text or "/home/cc/jina-local" in agents_text
