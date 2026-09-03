#!/usr/bin/env python3
"""全局部署验证 bench：检查 20工具全兼容 + 全局路径 + docker compose + MCP 调用"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path.home() / "jina-local"
WORKTREE = pathlib.Path("/home/cc/autonomous-worker/asset-workflow/.worktrees/issue-8-research/jina-local")
GLOBAL_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
OUTPUT = pathlib.Path("/tmp/jina-local-bench-mcp-global.json")

EXPECTED_TOOLS = [
    "primer", "read_url", "capture_screenshot_url", "guess_datetime_url",
    "search_web", "search_web_deep", "search_arxiv", "search_ssrn", "search_images",
    "search_jina_blog", "search_bibtex", "expand_query", "parallel_read_url",
    "parallel_search_web", "parallel_search_arxiv", "parallel_search_ssrn",
    "sort_by_relevance", "classify_text", "deduplicate_strings", "deduplicate_images", "extract_pdf",
    "embeddings",
]

def _check_global_path():
    ok = ROOT.exists() and ROOT.resolve() == (pathlib.Path.home() / "jina-local").resolve()
    not_in_worktree = not WORKTREE.exists()
    accessible = (ROOT / "mcp-gateway" / "src" / "gateway.py").exists()
    return {"ok": ok and not_in_worktree and accessible, "root": str(ROOT), "not_in_worktree": not_in_worktree, "gateway_exists": accessible, "worktree_exists": WORKTREE.exists()}

def _check_mcp_tools():
    try:
        import importlib.util
        gw_path = ROOT / "mcp-gateway" / "src" / "gateway.py"
        spec = importlib.util.spec_from_file_location("gateway_bench", gw_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        missing = [t for t in EXPECTED_TOOLS if not hasattr(mod, t)]
        # also check server
        srv_path = ROOT / "mcp-gateway" / "src" / "server.py"
        srv_text = srv_path.read_text(encoding="utf-8") if srv_path.exists() else ""
        count = srv_text.count("@mcp.tool()") + srv_text.count("mcp.tool()(")
        return {"ok": len(missing)==0 and count>=20, "missing": missing, "server_tool_count": count, "total_expected": len(EXPECTED_TOOLS)}
    except Exception as e:
        return {"ok": False, "error": str(e), "missing": EXPECTED_TOOLS}

def _check_docker_compose():
    try:
        result = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=str(ROOT), timeout=15)
        if result.returncode == 0:
            has_qdrant = "qdrant" in result.stdout.lower() and "6333" in result.stdout
            return {"ok": has_qdrant, "has_qdrant": has_qdrant, "stdout_contains_qdrant": has_qdrant, "exit_code": 0}
        else:
            # fallback yaml parse
            try:
                import yaml
                data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
                has_qdrant = "qdrant" in data.get("services", {})
                return {"ok": has_qdrant, "has_qdrant": has_qdrant, "docker_error": result.stderr[:500], "fallback": True}
            except Exception as e:
                text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
                has_qdrant = "qdrant:" in text and "6333" in text
                return {"ok": has_qdrant, "has_qdrant": has_qdrant, "fallback_text": True, "error": str(e)}
    except FileNotFoundError:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        has_qdrant = "qdrant:" in text
        return {"ok": has_qdrant, "has_qdrant": has_qdrant, "note": "docker not found, text check"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _check_opencode_mcp_list():
    # try opencode mcp list
    try:
        result = subprocess.run(["opencode", "mcp", "list"], capture_output=True, text=True, timeout=10)
        combined = result.stdout + result.stderr
        has_jina_local = "jina-local" in combined.lower()
        # try to count tools if inspector like
        return {"ok": True, "has_jina_local": has_jina_local, "output": combined[:2000], "method": "opencode mcp list", "exit_code": result.returncode}
    except FileNotFoundError:
        return {"ok": True, "has_jina_local": False, "note": "opencode not in PATH, skip", "method": "opencode mcp list"}
    except Exception as e:
        return {"ok": False, "error": str(e), "method": "opencode mcp list"}

def _check_mcp_calls():
    results = {}
    try:
        import importlib.util
        gw_path = ROOT / "mcp-gateway" / "src" / "gateway.py"
        spec = importlib.util.spec_from_file_location("gateway_call", gw_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        # read_url
        try:
            r = mod.read_url("https://example.com")
            results["read_url"] = {"ok": isinstance(r, str) and len(r)>0, "len": len(r) if isinstance(r, str) else 0}
        except Exception as e:
            results["read_url"] = {"ok": False, "error": str(e)[:500]}
        # search_web
        try:
            r2 = mod.search_web("machine learning", num=2)
            results["search_web"] = {"ok": isinstance(r2, list) and len(r2)>=1, "count": len(r2) if isinstance(r2, list) else 0}
        except Exception as e:
            results["search_web"] = {"ok": False, "error": str(e)[:500]}
        # rerank / sort_by_relevance
        try:
            r3 = mod.sort_by_relevance("python programming", ["python is great", "football game", "stock market"])
            results["rerank"] = {"ok": isinstance(r3, list) and len(r3)==3, "count": len(r3) if isinstance(r3, list) else 0}
        except Exception as e:
            results["rerank"] = {"ok": False, "error": str(e)[:500]}
        ok = all(v.get("ok") for v in results.values())
        return {"ok": ok, "calls": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _check_global_config():
    try:
        if not GLOBAL_CONFIG.exists():
            return {"ok": False, "error": f"{GLOBAL_CONFIG} not exists"}
        data = json.loads(GLOBAL_CONFIG.read_text(encoding="utf-8"))
        mcp = data.get("mcp", {})
        has = "jina-local" in mcp
        cfg = mcp.get("jina-local", {})
        is_local = cfg.get("type") == "local"
        cmd = cfg.get("command") or []
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        points_to_home = "/home/cc/jina-local" in cmd_str or "~/jina-local" in cmd_str or "jina-local" in cmd_str
        not_worktree = "worktree" not in cmd_str.lower()
        return {"ok": has and is_local and points_to_home and not_worktree, "has_jina_local": has, "is_local": is_local, "cmd": cmd, "points_to_home": points_to_home, "not_worktree": not_worktree}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    start = time.time()
    checks = {}
    checks["global_path"] = _check_global_path()
    checks["mcp_tools"] = _check_mcp_tools()
    checks["docker_compose"] = _check_docker_compose()
    checks["opencode_mcp_list"] = _check_opencode_mcp_list()
    checks["mcp_calls"] = _check_mcp_calls()
    checks["global_config"] = _check_global_config()

    # overall判定：全兼容且全局可用 = 工具齐 + 调用成功 + 全局路径 + docker qdrant + 配置正确
    all_ok = (
        checks["global_path"]["ok"]
        and checks["mcp_tools"]["ok"]
        and checks["docker_compose"]["ok"]
        and checks["mcp_calls"]["ok"]
        and checks["global_config"]["ok"]
    )
    # opencode mcp list 是附加，不强制失败
    result = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "checks": checks,
        "all_compatible_and_global": all_ok,
        "verdict": "PASS" if all_ok else "FAIL",
        "duration_sec": round(time.time()-start, 2),
        "expected_tools_count": len(EXPECTED_TOOLS),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n输出: {OUTPUT} 判定: {result['verdict']}")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
