# Search Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make native search services self-starting for Agent search calls and automatically stop them after ten idle minutes.

**Architecture:** A lifecycle controller owns Compose startup, readiness, activity persistence, and a single detached watchdog. `search.py` obtains a lease only for uncached native retrieval, which makes all gateway and deep-search paths inherit the behavior. The global web router documents the same lifecycle rather than asking each agent to hand-roll it.

**Tech Stack:** Python 3.11+, Docker Compose v2, requests, pytest, Go, Rust.

**Spec:** `docs/superpowers/specs/2026-09-04-search-session-lifecycle-design.md`

## Global Constraints

- Deployment path defaults to `~/jina-local` and remains configurable through `JINA_LOCAL_DIR`.
- Default idle interval is exactly `600` seconds via `JINA_LOCAL_SEARCH_IDLE_SECONDS`.
- Search cache hits never start services or refresh lifecycle activity.
- No auto-restart policy, hosted fallback, synthetic search result, or machine-specific Docker daemon setting.

---

### Task 1: Lifecycle Controller

**Files:**
- Create: `mcp-gateway/src/search_lifecycle.py`
- Test: `tests/test_search_lifecycle.py`

- [ ] Write failing tests for command startup/readiness, concurrent leases, activity state, and stale watchdog shutdown.
- [ ] Run `PYTHONPATH=mcp-gateway/src python -m pytest tests/test_search_lifecycle.py -q` and confirm failure because `search_lifecycle` does not exist.
- [ ] Implement the minimal controller and `python -m search_lifecycle --watch` entrypoint with injected seams for tests.
- [ ] Re-run the focused test file and confirm it passes.
- [ ] Commit `feat: add search session lifecycle`.

### Task 2: Search Integration and Router Contract

**Files:**
- Modify: `mcp-gateway/src/search.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `/home/cc/.agents/skills/web-task-router/SKILL.md`
- Test: `tests/test_search_lifecycle.py`
- Test: `tests/test_search_extended.py`

- [ ] Write failing tests proving cache hits do not lease the lifecycle and native retrieval always releases it.
- [ ] Run the focused Python tests and confirm failure.
- [ ] Wrap only `_fetch_candidates` with the lifecycle lease; add documented configuration variables and route all local search calls through the contract.
- [ ] Re-run focused tests and confirm they pass.
- [ ] Commit `feat: manage native search per agent session`.

### Task 3: Runtime Verification and Documentation

**Files:**
- Create: `scripts/test_search_lifecycle_runtime.py`
- Modify: `README.md`
- Modify: `docs/bench-full.md`
- Test: `tests/test_search_lifecycle_runtime.py`
- Test: `tests/test_docker_compose.py`

- [ ] Write failing unit tests for runtime-command construction and short test interval configuration.
- [ ] Run focused tests and confirm failure.
- [ ] Add an opt-in runtime verifier that builds the native images, tests proxy-backed retrieval, and confirms idle stop without leaving services running.
- [ ] Run focused tests and the opt-in runtime verifier.
- [ ] Commit `test: verify native search session lifecycle`.

### Task 4: Whole-Branch Verification

- [ ] Run Python, Go, Rust, Compose validation, image build, and runtime lifecycle verification from `/home/cc/jina-local`.
- [ ] Review the branch for concurrency, secret handling, deployment-path behavior, and router accuracy.
- [ ] Commit any review fixes separately.
