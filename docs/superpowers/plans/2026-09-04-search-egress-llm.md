# Search Egress and Evidence-Aware LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore real proxy-routed local web search, add behavioral readiness, and add optional evidence-preserving LLM enhancement with a real live evaluation suite.

**Architecture:** SearXNG and the Go fetcher use Linux Docker host networking so they can reach the host loopback proxy. A generated container-local SearXNG configuration injects the configured proxy. The fetcher owns live readiness; Python owns query fusion and optional LLM orchestration; Rust remains the provenance and ranking boundary.

**Tech Stack:** Docker Compose, SearXNG, Go standard library, Rust/Axum, Python `requests`, pytest, OpenAI-compatible Chat Completions.

**Spec:** `docs/superpowers/specs/2026-09-04-search-egress-llm-design.md`

## Global Constraints

- Preserve only real candidates with non-empty `title`, `url`, `content`, `source`, and `retrieved_at`.
- Return `NO_RETRIEVAL_BACKEND` for unavailable retrieval; never synthesize a result or cache a failure.
- Keep keys and proxy URLs in ignored `.env`; do not emit them in logs, fixtures, commits, or docs.
- `search` and `search-fetcher` target the supported Linux host-network deployment and bind service APIs to loopback.
- LLM output may only select supplied candidate IDs or supply query strings; it cannot supply evidence fields.
- Live tests require `JINA_LOCAL_LIVE_SEARCH=1`; CI stays deterministic and never needs an external proxy or API key.
- Run full fixed-path tests only from `/home/cc/jina-local`; linked worktrees intentionally fail their path-location assertions.

---

### Task 1: Proxy-Aware Host-Network Search and Behavioral Readiness

**Files:**
- Create: `searxng/entrypoint.sh`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `search-fetcher/cmd/search-fetcher/main.go`
- Modify: `search-fetcher/internal/fetcher/fetcher.go`
- Modify: `search-fetcher/internal/fetcher/fetcher_test.go`
- Modify: `tests/test_docker_compose.py`

**Interfaces:**
- Consumes: `JINA_LOCAL_SEARCH_PROXY_URL`, `JINA_LOCAL_SEARCH_READINESS_QUERY`, `SEARXNG_PORT`.
- Produces: `GET /healthz` returning process liveness and `GET /readyz` returning `200` only after a real successful fetch, otherwise `503` JSON with `NO_RETRIEVAL_BACKEND`.
- Produces: a `search` and `search-fetcher` Compose topology that does not expose either service beyond host loopback.

- [ ] **Step 1: Write the failing Go tests**

Add `TestReadinessReturnsProviderStatusAfterRetrievedCandidate` and
`TestReadinessRejectsUnavailableProviderWithoutCandidates` in
`search-fetcher/internal/fetcher/fetcher_test.go`. Construct `httptest` SearXNG responses and
assert `Probe(context.Context, query)` returns one candidate/status in the success case and
`Code == "NO_RETRIEVAL_BACKEND"` with zero candidates in the unavailable case.

- [ ] **Step 2: Run the Go tests to verify RED**

Run: `env GOCACHE=/tmp/jina-local-go-cache /tmp/jina-local-go/go/bin/go test ./internal/fetcher -run 'Readiness|Unavailable' -v`

Expected: compile failure because `Fetcher.Probe` does not exist.

- [ ] **Step 3: Write the failing Compose contract tests**

Extend `tests/test_docker_compose.py` with a test that asserts:

```python
assert 'network_mode: host' in search_service
assert 'network_mode: host' in fetcher_service
assert 'JINA_LOCAL_SEARCH_PROXY_URL' in compose_text
assert 'SEARCH_FETCHER_BIND_ADDR: 127.0.0.1' in compose_text
assert 'search-config:/etc/searxng' in compose_text
```

Use parsed YAML through `yaml.safe_load`, not substring-only service selection. Also assert the
tracked `searxng/entrypoint.sh` is executable and references only
`JINA_LOCAL_SEARCH_PROXY_URL`, not a literal proxy endpoint.

- [ ] **Step 4: Run the Compose contract test to verify RED**

Run: `python -m pytest tests/test_docker_compose.py -q -k 'host_network or proxy or readiness'`

Expected: FAIL because the current `search` and `search-fetcher` services use bridge networking.

- [ ] **Step 5: Implement the smallest network and readiness change**

Implement `Fetcher.Probe(ctx, query)` as `Fetch(ctx, query, 1)`. Add `/readyz` to
`main.go`; load `SEARCH_READINESS_QUERY`; encode the `Response`; use `503` whenever the probe
contains an error code or has no candidates. Bind `http.ListenAndServe` to
`SEARCH_FETCHER_BIND_ADDR + ":" + SEARCH_FETCHER_PORT`, defaulting to `127.0.0.1`.

Create `searxng/entrypoint.sh` that copies `/etc/searxng-template/settings.yml` into the named
config volume, appends a YAML `outgoing.proxies.all://` value only from
`JINA_LOCAL_SEARCH_PROXY_URL`, then `exec`s `/usr/local/searxng/entrypoint.sh`.

Update Compose so `search` mounts the template read-only and `search-config` writable volume,
runs the wrapper as entrypoint, uses host networking, and binds SearXNG to the configured
`SEARXNG_PORT`. Make `search-fetcher` use host networking, `SEARXNG_URL` at host loopback, and
the loopback bind address. Remove incompatible `ports:` mappings from those two host-network
services. Add non-secret defaults and explanations to `.env.example`.

- [ ] **Step 6: Run GREEN tests and static Compose validation**

Run:

```bash
env GOCACHE=/tmp/jina-local-go-cache /tmp/jina-local-go/go/bin/go test ./...
python -m pytest tests/test_docker_compose.py -q -k 'native_search or host_network or proxy or readiness'
docker compose --env-file .env.example config --quiet
```

Expected: all selected tests pass and Compose validates without a proxy value being logged.

- [ ] **Step 7: Commit Task 1**

```bash
git add searxng/entrypoint.sh docker-compose.yml .env.example search-fetcher tests/test_docker_compose.py
git commit -m "feat: route search through host proxy"
```

### Task 2: Strict OpenAI-Compatible Search LLM Client

**Files:**
- Create: `mcp-gateway/src/search_llm.py`
- Create: `tests/test_search_llm.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `is_enabled() -> bool`, `plan_queries(query: str) -> list[str]`, and
  `rerank_ids(query: str, candidates: list[dict]) -> list[str] | None`.
- Consumes: `JINA_LOCAL_LLM_BASE_URL`, `JINA_LOCAL_LLM_MODEL`, `JINA_LOCAL_LLM_API_KEY`.
- Returns: original-safe behavior (`[]` or `None`) for every API, schema, HTTP, or timeout error.

- [ ] **Step 1: Write failing Python tests**

Add tests that monkeypatch `requests.post` and prove:

```python
assert module.is_enabled() is False
assert module.plan_queries("complex retrieval question") == []
assert module.rerank_ids("q", candidates) is None
```

when credentials are absent. With three env values present, assert the request uses the
`/chat/completions` URL, Bearer authentication, JSON Schema `response_format`, and returned
query strings are deduplicated/non-empty. For reranking, assert unknown or duplicated IDs cause
`None`, while a valid permutation is returned exactly once per supplied candidate.

- [ ] **Step 2: Run the tests to verify RED**

Run: `python -m pytest tests/test_search_llm.py -q`

Expected: FAIL because `search_llm.py` does not exist.

- [ ] **Step 3: Implement the client**

Use only `requests`, `os`, `json`, and standard-library validation. Normalize the base URL with
one trailing slash removed. Set a bounded request timeout from
`JINA_LOCAL_LLM_TIMEOUT_SECONDS`. Send only query text and the candidate fields needed for
ranking. Parse the Chat Completions content as JSON. Do not log request headers, keys, or model
content. Catch `requests.RequestException`, JSON errors, and schema errors and return the safe
fallbacks defined above.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest tests/test_search_llm.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add mcp-gateway/src/search_llm.py tests/test_search_llm.py .env.example
git commit -m "feat: add constrained search LLM client"
```

### Task 3: Deep Search Query Fusion and Evidence-Only LLM Reranking

**Files:**
- Modify: `mcp-gateway/src/search_deep.py`
- Modify: `tests/test_search_deep.py`
- Modify: `tests/test_gateway_contract.py`

**Interfaces:**
- Consumes: `search_llm.plan_queries`, `search_llm.rerank_ids`, and existing `search_web`.
- Produces: `search_web_deep` output whose documents always originate from `search_web` and
  retain all provenance fields.
- Preserves: default behavior when LLM configuration is absent or invalid.

- [ ] **Step 1: Write failing deep-search tests**

Add tests that patch the LLM module and the local search function. Assert that planned variants
are searched alongside the original query, duplicate canonical URLs are fused with reciprocal
rank fusion, and only result IDs returned by a valid LLM permutation change order. Add separate
tests proving an LLM exception, malformed JSON, or unknown ID preserves the baseline Rust/local
order and never introduces a new candidate.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `python -m pytest tests/test_search_deep.py -q -k 'query_fusion or llm_rerank'`

Expected: FAIL because no query fusion or LLM integration exists.

- [ ] **Step 3: Implement minimal deep-search orchestration**

Add a focused helper in `search_deep.py` that constructs `[original_query, *planned_queries]`,
calls existing search APIs, deduplicates using the existing canonical URL behavior, and assigns
reciprocal-rank fusion scores. After readers/rerankers select the bounded evidence set, call
`rerank_ids`; if it returns a complete valid permutation, reorder those same records. Otherwise
return the existing order. Do not alter the MCP public signature.

- [ ] **Step 4: Run GREEN regression tests**

Run:

```bash
python -m pytest tests/test_search_deep.py tests/test_search_extended.py tests/test_gateway_contract.py tests/test_search_llm.py -q
```

Expected: all tests pass with no network or API key required.

- [ ] **Step 5: Commit Task 3**

```bash
git add mcp-gateway/src/search_deep.py tests/test_search_deep.py tests/test_gateway_contract.py
git commit -m "feat: enhance deep search with constrained LLM ranking"
```

### Task 4: Live Complex-Query Evaluation, Documentation, and CI Boundaries

**Files:**
- Create: `scripts/bench_search_live.py`
- Create: `tests/test_bench_search_live.py`
- Modify: `README.md`
- Modify: `docs/bench-full.md`
- Modify: `docs/jina-vs-jina-local.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `JINA_LOCAL_LIVE_SEARCH=1`, local endpoint URLs, and optionally LLM credentials.
- Produces: `/tmp/opencode/jina-local/search-live-<timestamp>.json` with raw candidate evidence,
  provider states, latency, target-source labels, MRR, nDCG@5, and comparison to baseline.
- Preserves: CI runs deterministic contract tests only; live evaluation is an explicit operator
  command and fails closed when prerequisites are absent.

- [ ] **Step 1: Write failing evaluator tests**

Add pure tests for a corpus evaluator that rejects unprovenanced results, computes reciprocal
rank and nDCG@5 from labeled canonical URLs, and marks a result `FAIL` when an unavailable query
is presented as successful. Include Chinese/English labels and multi-source requirements without
performing HTTP requests.

- [ ] **Step 2: Run evaluator tests to verify RED**

Run: `python -m pytest tests/test_bench_search_live.py -q`

Expected: FAIL because `bench_search_live.py` does not exist.

- [ ] **Step 3: Implement the evaluator and live runner**

Define a small versioned corpus with stable official-documentation targets, one `site:` target,
one multi-source research query, and one Chinese/English query. Require three runs, persist
sanitized raw evidence to the configured cache path, and compare LLM-disabled and LLM-enabled
scores only when LLM credentials are present. Refuse to execute network requests unless
`JINA_LOCAL_LIVE_SEARCH=1`; otherwise print the exact opt-in requirement and exit nonzero.

Update documentation to remove stale claims that search uses synthetic/direct fallbacks or that
historical PASS values prove current quality. Document host-network requirements, proxy setup,
the LLM variables, the live benchmark command, and that Jina/Firecrawl/Exa quality comparisons
remain unmeasured without comparable accounts and conditions. Keep the CI workflow's selected
reproducible suite and add the new pure evaluator test.

- [ ] **Step 4: Run GREEN test, build, and configuration verification**

Run:

```bash
python -m pytest tests/test_bench_search_live.py tests/test_search_llm.py tests/test_search_deep.py tests/test_search_extended.py tests/test_gateway_contract.py tests/test_docker_compose.py -q
env GOCACHE=/tmp/jina-local-go-cache /tmp/jina-local-go/go/bin/go test ./...
cargo test --manifest-path search-core/Cargo.toml
docker compose --env-file .env.example config --quiet
```

Expected: all branch-reproducible tests pass; only fixed-deployment-path tests remain excluded
inside the linked worktree.

- [ ] **Step 5: Run the real live acceptance suite from `/home/cc/jina-local` after merge**

Run:

```bash
docker compose --profile search up -d search search-fetcher search-core
curl --fail http://127.0.0.1:8082/readyz
JINA_LOCAL_LIVE_SEARCH=1 python scripts/bench_search_live.py
```

Expected: archived evidence proves all corpus results are real/provenanced; failures remain
explicit `NO_RETRIEVAL_BACKEND` with no synthetic candidates.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/bench_search_live.py tests/test_bench_search_live.py README.md docs/bench-full.md docs/jina-vs-jina-local.md .github/workflows/ci.yml
git commit -m "test: add live search quality evaluation"
```

## Plan Self-Review

- Spec coverage: Task 1 implements host egress and behavioral readiness; Task 2 implements
  constrained LLM API handling; Task 3 preserves evidence while using it; Task 4 supplies the
  real complex-query acceptance evidence and updates operational claims.
- Task interface check: Task 1 exports `/readyz`; Task 2 exports `plan_queries` and
  `rerank_ids`; Task 3 consumes only those helpers; Task 4 calls the public service and pure
  evaluator, not private fixture behavior.
- Ruling: existing path-location tests intentionally fail in a linked worktree. They remain
  unchanged because their deployment invariant is valid; CI and branch verification use the
  project-selected reproducible tests, while post-merge live verification runs from the fixed
  deployment checkout.
