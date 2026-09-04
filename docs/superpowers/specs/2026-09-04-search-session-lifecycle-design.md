# Search Session Lifecycle Design

## Goal

Start the native local search stack only when an uncached search needs it and stop it ten minutes after the final search activity in an Agent session.

## Scope

- `search_web` and every caller that reaches it use the same lifecycle controller.
- Cache hits do not start Docker services or refresh the idle timer.
- The controller starts `search`, `search-fetcher`, and `search-core`, waits for the two native health endpoints, then permits retrieval.
- A single detached watchdog persists the latest activity timestamp in `/tmp/opencode/jina-local`; it stops the three services only when no activity has occurred for `JINA_LOCAL_SEARCH_IDLE_SECONDS` (default `600`).
- Search failures remain explicit `NO_RETRIEVAL_BACKEND` failures. No cloud fallback or generated results are introduced.
- `web-task-router` documents the lifecycle as mandatory for every agent that invokes `jina-local` search tools.

## Design

`mcp-gateway/src/search_lifecycle.py` owns Docker commands, readiness polling, activity state, and watchdog coordination. `search.py` opens a lifecycle lease immediately before the native fetcher/core request and closes it in `finally`; this covers direct, parallel, gateway, and deep-search paths without duplicate wrappers. A process-local lock prevents simultaneous calls from issuing duplicate `docker compose up` commands. The detached watchdog holds an advisory file lock, so only one process monitors a session state file; a newer timestamp always wins over an older timer.

The controller invokes Compose from `JINA_LOCAL_DIR` (default `~/jina-local`) and reads the deployment `.env`. Tests inject command runners, HTTP probes, clock, and process spawners, so no Docker daemon is needed for unit coverage.

## Build Reliability

The prior BuildKit failure was an observed Docker Hub token/network reset. A direct authenticated `docker pull golang:1.27-bookworm` subsequently succeeded on September 4, 2026. The project will not add a machine-specific Docker daemon or registry-mirror configuration. Instead, real verification builds both native service images and proves the deployed stack can start through the existing Docker configuration.

## Verification

- Unit tests prove startup/readiness, one-time concurrent startup, cache-hit behavior, lease activity refresh, and stale watchdog shutdown decisions.
- Compose tests assert the search stack remains opt-in and has no automatic restart policy.
- Runtime test pulls/builds the Go/Rust images, starts all three services with the configured proxy, verifies `/readyz` and `/healthz`, runs a real provenance-producing search, then verifies idle shutdown with a test-only short interval.
- Full Python, Go, Rust, and Compose configuration suites run from `/home/cc/jina-local` after integration.
