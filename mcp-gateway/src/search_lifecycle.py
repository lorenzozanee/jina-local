"""Lifecycle management for the local native search stack."""

import argparse
import fcntl
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import requests


DEFAULT_IDLE_SECONDS = 600.0
DEFAULT_START_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_SECONDS = 0.2
BASE_IMAGE_PULL_ATTEMPTS = 3


class SearchLifecycleError(RuntimeError):
    pass


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class SearchLifecycle:
    def __init__(
        self,
        root: pathlib.Path | str | None = None,
        state_dir: pathlib.Path | str | None = None,
        idle_seconds: float | None = None,
        start_timeout_seconds: float | None = None,
        runner=None,
        probe=None,
        spawner=None,
        clock=None,
        sleeper=None,
    ):
        self.root = pathlib.Path(root or os.getenv("JINA_LOCAL_DIR", pathlib.Path.home() / "jina-local")).expanduser().resolve()
        self.state_dir = pathlib.Path(state_dir or os.getenv("CACHE_DIR", "/tmp/opencode/jina-local")).expanduser()
        self.idle_seconds = idle_seconds or _positive_float("JINA_LOCAL_SEARCH_IDLE_SECONDS", DEFAULT_IDLE_SECONDS)
        self.start_timeout_seconds = start_timeout_seconds or _positive_float(
            "JINA_LOCAL_SEARCH_START_TIMEOUT_SECONDS", DEFAULT_START_TIMEOUT_SECONDS
        )
        self.runner = runner or subprocess.run
        self.probe = probe or self._default_probe
        self.spawner = spawner or subprocess.Popen
        self.clock = clock or time.time
        self.sleeper = sleeper or time.sleep
        self._lock = threading.RLock()
        self._started = False
        self._watchdog_started = False

    @property
    def state_path(self) -> pathlib.Path:
        return self.state_dir / "search-lifecycle.json"

    @property
    def lock_path(self) -> pathlib.Path:
        return self.state_dir / "search-lifecycle.lock"

    def compose_command(self, action: str) -> list[str]:
        command = ["docker", "compose", "-f", str(self.root / "docker-compose.yml"), "--profile", "search", action]
        if action == "up":
            return [*command, "-d", "search", "search-fetcher", "search-core"]
        if action == "stop":
            return [*command, "--timeout", "1", "search", "search-fetcher", "search-core"]
        return [*command, "search", "search-fetcher", "search-core"]

    def _run_compose(self, action: str) -> None:
        try:
            result = self.runner(
                self.compose_command(action),
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SearchLifecycleError("docker command unavailable") from exc
        if result.returncode:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "docker compose failed").strip()
            raise SearchLifecycleError(f"native search {action} failed: {detail[:500]}")

    def _base_images(self) -> list[str]:
        images: list[str] = []
        for dockerfile in (self.root / "search-fetcher" / "Dockerfile", self.root / "search-core" / "Dockerfile"):
            try:
                lines = dockerfile.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise SearchLifecycleError(f"cannot read native search Dockerfile: {dockerfile}") from exc
            for line in lines:
                match = re.match(r"^\s*FROM\s+(?:--[^\s]+\s+)*([^\s]+)", line, flags=re.IGNORECASE)
                if match and match.group(1) not in images:
                    images.append(match.group(1))
        return images

    def _image_present(self, image: str) -> bool:
        try:
            result = self.runner(["docker", "image", "inspect", image], check=False, capture_output=True, text=True)
        except OSError as exc:
            raise SearchLifecycleError("docker command unavailable") from exc
        return result.returncode == 0

    def _pull_missing_base_images(self) -> None:
        for image in self._base_images():
            if self._image_present(image):
                continue
            for attempt in range(BASE_IMAGE_PULL_ATTEMPTS):
                try:
                    result = self.runner(["docker", "pull", image], check=False, capture_output=True, text=True)
                except OSError as exc:
                    raise SearchLifecycleError("docker command unavailable") from exc
                if result.returncode == 0:
                    break
                if attempt + 1 == BASE_IMAGE_PULL_ATTEMPTS:
                    detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "docker pull failed").strip()
                    raise SearchLifecycleError(f"cannot pull native search base image {image}: {detail[:500]}")
                self.sleeper(float(attempt + 1))

    @staticmethod
    def _default_probe(url: str) -> bool:
        try:
            response = requests.get(url, timeout=1, proxies={"http": None, "https": None})
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _ready(self) -> bool:
        fetcher = os.getenv("JINA_LOCAL_SEARCH_FETCHER_URL", "http://127.0.0.1:8082")
        core = os.getenv("JINA_LOCAL_SEARCH_CORE_URL", "http://127.0.0.1:8083")
        return self.probe(f"{fetcher.rstrip('/')}/readyz") and self.probe(f"{core.rstrip('/')}/healthz")

    def _wait_ready(self) -> None:
        deadline = self.clock() + self.start_timeout_seconds
        while self.clock() < deadline:
            if self._ready():
                return
            self.sleeper(DEFAULT_POLL_SECONDS)
        raise SearchLifecycleError("native search services did not become ready")

    def read_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def write_state(self, state: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def touch(self) -> None:
        self.write_state({"last_activity": self.clock()})

    def should_stop(self) -> bool:
        last_activity = self.read_state().get("last_activity")
        return isinstance(last_activity, (int, float)) and self.clock() - last_activity >= self.idle_seconds

    def _start_watchdog(self) -> None:
        if self._watchdog_started:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.spawner(
            [
                sys.executable,
                str(pathlib.Path(__file__).resolve()),
                "--watch",
                "--root",
                str(self.root),
                "--state-dir",
                str(self.state_dir),
                "--idle-seconds",
                str(self.idle_seconds),
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._watchdog_started = True

    @contextmanager
    def lease(self):
        with self._lock:
            if not self._started or not self._ready():
                self._watchdog_started = False
                self._pull_missing_base_images()
                self._run_compose("up")
                self._wait_ready()
                self._started = True
            self.touch()
            self._start_watchdog()
        try:
            yield
        finally:
            self.touch()

    def watch(self) -> int:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            while True:
                if self.should_stop():
                    self._run_compose("stop")
                    return 0
                state = self.read_state()
                last_activity = state.get("last_activity")
                if not isinstance(last_activity, (int, float)):
                    return 0
                remaining = max(0.1, last_activity + self.idle_seconds - self.clock())
                self.sleeper(min(remaining, 1.0))


_instance: SearchLifecycle | None = None


def get_search_lifecycle() -> SearchLifecycle:
    global _instance
    if _instance is None:
        _instance = SearchLifecycle()
    return _instance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--idle-seconds", type=float, default=DEFAULT_IDLE_SECONDS)
    args = parser.parse_args(argv)
    if not args.watch:
        parser.error("--watch is required")
    return SearchLifecycle(root=args.root, state_dir=args.state_dir, idle_seconds=args.idle_seconds).watch()


if __name__ == "__main__":
    raise SystemExit(main())
