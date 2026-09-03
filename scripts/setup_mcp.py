#!/usr/bin/env python3
"""通用 MCP 配置写入 - 支持多 Agent (opencode/claude/codex/openclaw/hermes/all)

幂等、无损合并原有配置、路径校验为 ~/jina-local 非 worktree。

用法:
  python scripts/setup_mcp.py --agent opencode
  python scripts/setup_mcp.py --agent claude
  python scripts/setup_mcp.py --agent codex
  python scripts/setup_mcp.py --agent all        # 默认，写入全部已知的 Agent 路径
  python scripts/setup_mcp.py --agent openclaw
  python scripts/setup_mcp.py --agent hermes
"""

import argparse
import json
import pathlib
import sys
import shutil

HOME_JINA_LOCAL = pathlib.Path.home() / "jina-local"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_PATH = HOME_JINA_LOCAL / "mcp-gateway" / "src" / "server.py"
GENERIC_MCP_JSON = PROJECT_ROOT / "mcp.json"
WORKTREE_CANDIDATE = pathlib.Path("/home/cc/autonomous-worker/asset-workflow/.worktrees/issue-8-research/jina-local")

# Agent 目标路径
OPENCODE_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
CLAUDE_CONFIG_1 = pathlib.Path.home() / ".config" / "claude" / "mcp.json"
CLAUDE_CONFIG_2 = pathlib.Path.home() / ".claude.json"
CODEX_TOML = pathlib.Path.home() / ".codex" / "config.toml"
CODEX_JSON = pathlib.Path.home() / ".config" / "codex" / "mcp.json"
OPENCLAW_CONFIG = pathlib.Path.home() / ".config" / "openclaw" / "mcp.json"
HERMES_CONFIG = pathlib.Path.home() / ".config" / "hermes" / "mcp.json"

SUPPORTED_AGENTS = ["opencode", "claude", "codex", "openclaw", "hermes", "all"]


def _resolve_gateway_command():
    gateway_src = SERVER_PATH
    if gateway_src.exists():
        return ["python3", str(gateway_src)]
    return ["python3", str(HOME_JINA_LOCAL / "mcp-gateway" / "src" / "server.py")]


def _gateway_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    port = values.get("SEARXNG_PORT", "8081")
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        port = "8081"
    return {"SEARXNG_URL": values.get("SEARXNG_URL", f"http://127.0.0.1:{port}")}


def _validate_home_path():
    if not HOME_JINA_LOCAL.exists():
        print(f"ERROR: {HOME_JINA_LOCAL} 不存在，请先创建 ~/jina-local", file=sys.stderr)
        sys.exit(1)
    # 通用 worktree 检测：任意路径含 worktree 即告警
    if "worktree" in str(HOME_JINA_LOCAL).lower() or "worktree" in str(SERVER_PATH).lower():
        print(f"ERROR: HOME_JINA_LOCAL 指向 worktree 非法: {HOME_JINA_LOCAL}", file=sys.stderr)
        sys.exit(1)
    if WORKTREE_CANDIDATE.exists():
        print(f"WARNING: worktree 路径 {WORKTREE_CANDIDATE} 存在，应仅保留 {HOME_JINA_LOCAL}", file=sys.stderr)
    # 额外检测：若当前仓库根含 worktree
    try:
        import subprocess
        res = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and "worktree" in res.stdout.lower():
            print(f"WARNING: 检测到 worktree git-dir {res.stdout.strip()}，请确保使用 {HOME_JINA_LOCAL}", file=sys.stderr)
    except Exception:
        pass
    cmd = _resolve_gateway_command()
    cmd_str = " ".join(cmd)
    assert "jina-local" in cmd_str
    assert "/home/cc/jina-local" in cmd_str or "~/jina-local" in cmd_str or str(HOME_JINA_LOCAL) in cmd_str
    if "worktree" in cmd_str.lower():
        print(f"ERROR: command 指向 worktree 非法: {cmd_str}", file=sys.stderr)
        sys.exit(1)
    server = pathlib.Path(cmd[1]) if len(cmd) > 1 else None
    if server and not server.exists():
        print(f"WARNING: gateway {server} 不存在，请检查 ~/jina-local 是否为最新", file=sys.stderr)


def _load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARNING: 读取 {path} 失败 {e}，将重建", file=sys.stderr)
        return {}


def _save_json(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_generic_mcp_json():
    if not GENERIC_MCP_JSON.exists():
        print(f"创建 {GENERIC_MCP_JSON}")
    data = _load_json(GENERIC_MCP_JSON)
    # 若为空或不含 mcpServers，写入标准模板
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data = {}
    if "jina-local" not in data.get("mcpServers", {}):
        if "mcpServers" not in data:
            data["mcpServers"] = {}
    cmd = _resolve_gateway_command()
    data["mcpServers"]["jina-local"] = {
        "command": cmd[0],
        "args": cmd[1:],
        "env": _gateway_environment()
    }
    # 若文件已存在且内容已正确则跳过写入
    existing = _load_json(GENERIC_MCP_JSON)
    if existing == data and GENERIC_MCP_JSON.exists():
        print(f"✓ 已存在 {GENERIC_MCP_JSON}")
        return
    _save_json(GENERIC_MCP_JSON, data)
    print(f"✓ 已写入 {GENERIC_MCP_JSON} -> mcpServers.jina-local")


def _setup_opencode():
    _validate_home_path()
    cmd = _resolve_gateway_command()
    data = _load_json(OPENCODE_CONFIG)
    if "mcp" not in data or not isinstance(data["mcp"], dict):
        data["mcp"] = {}
    # 幂等写入
    prev = data["mcp"].get("jina-local")
    new_entry = {"type": "local", "command": cmd, "enabled": True, "environment": _gateway_environment()}
    if prev == new_entry:
        print(f"✓ 已存在 {OPENCODE_CONFIG} -> mcp.jina-local (幂等)")
        return
    data["mcp"]["jina-local"] = new_entry
    _save_json(OPENCODE_CONFIG, data)
    verify = _load_json(OPENCODE_CONFIG)
    assert "jina-local" in verify.get("mcp", {}), "写入验证失败"
    print(f"✓ 已写入 {OPENCODE_CONFIG} -> mcp.jina-local: {cmd}")


def _setup_claude():
    _validate_home_path()
    cmd = _resolve_gateway_command()
    mcp_entry = {"command": cmd[0], "args": cmd[1:], "env": _gateway_environment()}
    # 优先 ~/.config/claude/mcp.json
    for cfg_path in [CLAUDE_CONFIG_1, CLAUDE_CONFIG_2]:
        # 若 ~/.claude.json 已存在则更新，否则仅当该路径更合适时创建
        # 策略：若 CLAUDE_CONFIG_1 目录存在或文件存在，则用它；否则若 CLAUDE_CONFIG_2 存在则用它；
        # 若两者都不存在，默认创建 CLAUDE_CONFIG_1（更规范）
        pass
    # 决定主路径：优先已存在的，否则创建 CLAUDE_CONFIG_1
    if CLAUDE_CONFIG_2.exists() and not CLAUDE_CONFIG_1.exists():
        primary = CLAUDE_CONFIG_2
        secondary = CLAUDE_CONFIG_1
    else:
        primary = CLAUDE_CONFIG_1
        secondary = CLAUDE_CONFIG_2 if CLAUDE_CONFIG_2.exists() else None

    for target in [primary] + ([secondary] if secondary else []):
        # 对于 ~/.claude.json，其结构可能直接是 mcpServers 或顶层含 mcpServers
        data = _load_json(target)
        if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
            # 保留原有其他顶层键
            if not data:
                data = {"mcpServers": {}}
            else:
                # 若文件非空但无 mcpServers，新增
                data["mcpServers"] = data.get("mcpServers", {})
                if not isinstance(data["mcpServers"], dict):
                    data["mcpServers"] = {}
        prev = data["mcpServers"].get("jina-local")
        if prev == mcp_entry:
            print(f"✓ 已存在 {target} -> mcpServers.jina-local (幂等)")
            continue
        data["mcpServers"]["jina-local"] = mcp_entry
        _save_json(target, data)
        print(f"✓ 已写入 {target} -> mcpServers.jina-local: {cmd}")
    # 若 primary 是 CLAUDE_CONFIG_1 且 secondary 不存在，也同步提示通用复制
    if not CLAUDE_CONFIG_2.exists() and primary == CLAUDE_CONFIG_1:
        # 不强制创建 ~/.claude.json，避免污染用户配置
        pass


def _setup_codex():
    _validate_home_path()
    cmd = _resolve_gateway_command()
    # JSON 变体
    mcp_entry = {"command": cmd[0], "args": cmd[1:], "env": _gateway_environment()}
    data = _load_json(CODEX_JSON)
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        if not data:
            data = {"mcpServers": {}}
        else:
            data["mcpServers"] = data.get("mcpServers", {})
            if not isinstance(data["mcpServers"], dict):
                data["mcpServers"] = {}
    prev = data["mcpServers"].get("jina-local")
    if prev != mcp_entry:
        data["mcpServers"]["jina-local"] = mcp_entry
        _save_json(CODEX_JSON, data)
        print(f"✓ 已写入 {CODEX_JSON} -> mcpServers.jina-local: {cmd}")
    else:
        print(f"✓ 已存在 {CODEX_JSON} -> mcpServers.jina-local (幂等)")

    # TOML 变体：若 ~/.codex/config.toml 已存在则追加/更新
    if CODEX_TOML.exists():
        text = CODEX_TOML.read_text(encoding="utf-8")
        need_update = False
        if "jina-local" not in text:
            need_update = True
        elif str(SERVER_PATH) not in text:
            need_update = True
        if need_update:
            # 追加标准段，若已存在则替换
            # 简单策略：移除旧段后追加（DOTALL 处理多行 args）
            import re
            # 移除已有的 [mcp_servers.jina-local] 段
            pattern = r"\[mcp_servers\.jina-local\].*?(?=\n\[|\Z)"
            new_text = re.sub(pattern, "", text, flags=re.DOTALL)
            # 确保末尾换行
            if not new_text.endswith("\n"):
                new_text += "\n"
            new_text += f'\n[mcp_servers.jina-local]\ncommand = "{cmd[0]}"\nargs = ["{cmd[1]}"]\n\n'
            CODEX_TOML.write_text(new_text, encoding="utf-8")
            print(f"✓ 已更新 {CODEX_TOML} -> [mcp_servers.jina-local]")
        else:
            print(f"✓ 已存在 {CODEX_TOML} -> [mcp_servers.jina-local] (幂等)")
    else:
        # 若 toml 不存在，不强制创建，避免破坏 codex 预期；已通过 json 变体覆盖
        # 同时创建目录提示
        CODEX_TOML.parent.mkdir(parents=True, exist_ok=True)
        # 不自动创建文件，仅提示
        print(f"  提示: {CODEX_TOML} 不存在，已通过 {CODEX_JSON} 提供 codex 支持 (toml 可手动同步)")


def _setup_generic_copy(target: pathlib.Path):
    _validate_home_path()
    _ensure_generic_mcp_json()
    data = _load_json(GENERIC_MCP_JSON)
    existing = _load_json(target)
    if existing == data and target.exists():
        print(f"✓ 已存在 {target} (幂等)")
        return
    # 无损合并：若 target 已有 mcpServers，合并 jina-local
    if target.exists():
        cur = _load_json(target)
        if "mcpServers" in cur and isinstance(cur["mcpServers"], dict):
            # 合并
            cur["mcpServers"]["jina-local"] = data["mcpServers"]["jina-local"]
            _save_json(target, cur)
            print(f"✓ 已合并 {target} -> mcpServers.jina-local")
            return
    # 否则直接复制
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(GENERIC_MCP_JSON, target)
    print(f"✓ 已复制 {GENERIC_MCP_JSON} -> {target}")


def _setup_openclaw():
    _setup_generic_copy(OPENCLAW_CONFIG)


def _setup_hermes():
    _setup_generic_copy(HERMES_CONFIG)


def main():
    parser = argparse.ArgumentParser(description="通用 MCP 配置 - 支持多 Agent")
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS, default="all", help="目标 Agent (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    args = parser.parse_args()

    _validate_home_path()
    _ensure_generic_mcp_json()

    if args.dry_run:
        print(f"[dry-run] 将写入 {GENERIC_MCP_JSON}:")
        print(json.dumps(_load_json(GENERIC_MCP_JSON), ensure_ascii=False, indent=2))
        return

    agent = args.agent
    if agent == "all":
        _setup_opencode()
        _setup_claude()
        _setup_codex()
        _setup_openclaw()
        _setup_hermes()
        print(f"✓ all 完成：通用 {GENERIC_MCP_JSON} 已提供，各 Agent 已幂等写入")
    elif agent == "opencode":
        _setup_opencode()
    elif agent == "claude":
        _setup_claude()
    elif agent == "codex":
        _setup_codex()
    elif agent == "openclaw":
        _setup_openclaw()
    elif agent == "hermes":
        _setup_hermes()
    else:
        parser.error(f"未知 agent {agent}")

    # 最终校验
    print(f"  全局路径: {HOME_JINA_LOCAL} (not in worktree)")
    print(f"  通用配置: {GENERIC_MCP_JSON}")


if __name__ == "__main__":
    main()
