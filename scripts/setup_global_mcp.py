#!/usr/bin/env python3
"""自动写入 ~/.config/opencode/opencode.json 的 mcp.jina-local 配置
路径固定为 ~/jina-local 非 worktree，确保系统全局可用。
"""
import json
import pathlib
import sys

HOME_JINA_LOCAL = pathlib.Path.home() / "jina-local"
GLOBAL_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
# 兼容备用路径（早期版本）
ALT_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"


def _resolve_gateway_command():
    """生成 local MCP command，指向 ~/jina-local/mcp-gateway"""
    gateway_src = HOME_JINA_LOCAL / "mcp-gateway" / "src" / "server.py"
    # 优先用 python3 直接启动 server.py，最通用
    # 若存在 mcp 可用则使用 python3；否则保留可执行性
    if gateway_src.exists():
        return ["python3", str(gateway_src)]
    # fallback: 尝试指向 mcp-gateway 目录
    return ["python3", str(HOME_JINA_LOCAL / "mcp-gateway" / "src" / "server.py")]


def main():
    # 确保路径为 ~/jina-local 非 worktree
    if not HOME_JINA_LOCAL.exists():
        print(f"ERROR: {HOME_JINA_LOCAL} 不存在，请先创建 ~/jina-local", file=sys.stderr)
        sys.exit(1)
    # 防止在 worktree 下错误运行（检测当前 cwd 是否在 worktree）
    worktree_candidate = pathlib.Path("/home/cc/autonomous-worker/asset-workflow/.worktrees/issue-8-research/jina-local")
    if worktree_candidate.exists():
        print(f"WARNING: worktree 路径 {worktree_candidate} 存在，应仅保留 {HOME_JINA_LOCAL}", file=sys.stderr)

    # 确保全局配置目录存在
    GLOBAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有配置或创建空
    if GLOBAL_CONFIG.exists():
        try:
            data = json.loads(GLOBAL_CONFIG.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARNING: 读取 {GLOBAL_CONFIG} 失败 {e}，将重建", file=sys.stderr)
            data = {}
    else:
        data = {}

    if "mcp" not in data or not isinstance(data["mcp"], dict):
        data["mcp"] = {}

    # 配置 jina-local 为 local 类型，指向 ~/jina-local/mcp-gateway
    cmd = _resolve_gateway_command()
    # 确保路径为绝对 ~/jina-local 而非 worktree
    cmd_str = " ".join(cmd)
    assert "jina-local" in cmd_str, "command 必须包含 jina-local"
    assert "/home/cc/jina-local" in cmd_str or "~/jina-local" in cmd_str or str(HOME_JINA_LOCAL) in cmd_str

    data["mcp"]["jina-local"] = {
        "type": "local",
        "command": cmd,
        "enabled": True,
        "environment": {},
    }

    # 写入（保留原有其它 mcp 配置）
    GLOBAL_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 已写入 {GLOBAL_CONFIG} -> mcp.jina-local: {cmd}")
    # 验证
    verify = json.loads(GLOBAL_CONFIG.read_text(encoding="utf-8"))
    assert "jina-local" in verify.get("mcp", {}), "写入验证失败"
    assert verify["mcp"]["jina-local"]["type"] == "local"
    # 输出路径校验
    resolved = pathlib.Path(verify["mcp"]["jina-local"]["command"][1]) if len(verify["mcp"]["jina-local"]["command"]) > 1 else None
    if resolved:
        print(f"  gateway: {resolved} exists={resolved.exists() if resolved else 'N/A'}")
    print(f"  全局路径: {HOME_JINA_LOCAL} (not in worktree)")


if __name__ == "__main__":
    main()
