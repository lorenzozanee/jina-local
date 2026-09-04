#!/usr/bin/env python3
"""Opt-in end-to-end verification for the native search session lifecycle."""

import argparse
import os
import pathlib
import subprocess
import sys
import time
import uuid

import requests


SERVICES = ("search", "search-fetcher", "search-core")


def compose_command(root: pathlib.Path, action: str) -> list[str]:
    command = ["docker", "compose", "-f", str(root / "docker-compose.yml"), "--profile", "search", action]
    if action == "up":
        return [*command, "-d", *SERVICES]
    return [*command, *SERVICES]


def _run(command: list[str], root: pathlib.Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def _wait_ready(deadline: float) -> None:
    endpoints = ("http://127.0.0.1:8082/readyz", "http://127.0.0.1:8083/healthz")
    while time.monotonic() < deadline:
        try:
            if all(requests.get(endpoint, timeout=1, proxies={"http": None, "https": None}).status_code == 200 for endpoint in endpoints):
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError("native search services did not become ready")


def _stopped(root: pathlib.Path) -> bool:
    result = subprocess.run(
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "ps", "-q", "--status", "running", *SERVICES],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--idle-seconds", type=float, default=3.0)
    parser.add_argument("--start-timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.idle_seconds <= 0:
        parser.error("--idle-seconds must be positive")

    os.environ["JINA_LOCAL_DIR"] = str(root)
    os.environ["JINA_LOCAL_SEARCH_IDLE_SECONDS"] = str(args.idle_seconds)
    sys.path.insert(0, str(root / "mcp-gateway" / "src"))
    import search

    query = f"OpenAI Codex documentation lifecycle {uuid.uuid4().hex}"
    search._cache_path(query).unlink(missing_ok=True)
    try:
        _run(compose_command(root, "build"), root)
        _run(compose_command(root, "up"), root)
        _wait_ready(time.monotonic() + args.start_timeout_seconds)
        results = search.search_web(query, num=3)
        if not results or not all(search._is_provenanced_result(item) for item in results):
            raise RuntimeError("search returned no provenanced results")
        deadline = time.monotonic() + args.idle_seconds + 10
        while time.monotonic() < deadline:
            if _stopped(root):
                print("search lifecycle runtime verification passed")
                return 0
            time.sleep(0.2)
        raise RuntimeError("native search services did not stop after idle timeout")
    finally:
        _run(compose_command(root, "stop"), root)


if __name__ == "__main__":
    raise SystemExit(main())
