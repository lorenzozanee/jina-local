# Search Integrity Native Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace synthetic web search output with a provenance-preserving Go, Rust, and Python local search pipeline.

**Architecture:** Python remains the MCP/cache boundary. Go exposes a bounded fetch service that returns only retrieved candidates and provider status. Rust exposes a deterministic ranking service that validates provenance, canonicalizes URLs, enforces `site:` filters, de-duplicates, and ranks records.

**Tech Stack:** Python 3.11+, FastMCP, requests; Go standard library; Rust stable with axum, serde, serde_json, url; Docker Compose; pytest, `go test`, Cargo tests.

**Spec:** `docs/superpowers/specs/2026-09-04-search-integrity-native-pipeline-design.md`

## Global Constraints

- Preserve the MCP names `search_web` and `parallel_search_web` and their required input parameters.
- Never fabricate URLs, titles, snippets, or successful search results.
- Do not cache errors, empty result sets, or cache entries without source provenance.
- All outbound fetch work has bounded deadlines and returns backend status.
- Native services run only in the `search` Compose profile and expose loopback-only ports.
- Use no cloud credentials and no automatic restart policy.
- Each behavior change follows RED, GREEN, REFACTOR and ends with a focused commit.

---

### Task 1: Define Python Search Integrity Contract

**Files:**
- Modify: `tests/test_search_extended.py`
- Modify: `tests/test_gateway_contract.py`
- Modify: `mcp-gateway/src/search.py`
- Modify: `mcp-gateway/src/gateway.py`

**Interfaces:**
- Produces `SearchUnavailableError(RuntimeError)` with `NO_RETRIEVAL_BACKEND` in its message.
- Produces cache envelopes with `schema_version=2`, `query`, `created_at`, `expires_at`, and `results`.
- Consumes a result record with `title`, `url`, `content`, `source`, and `retrieved_at`.

- [ ] **Step 1: Write the failing test**

    def test_search_rejects_synthetic_or_unprovenanced_cache(monkeypatch, tmp_path):
        mod = _load_search_module(monkeypatch, tmp_path)
        mod._cache_path("OpenCode docs").write_text(json.dumps([{
            "title": "OpenCode docs", "url": "https://jina.ai/topics/opencode/123",
            "content": "This result discusses OpenCode docs in depth."}]))
        monkeypatch.setattr(mod, "_fetch_candidates", lambda *_: [])
        with pytest.raises(mod.SearchUnavailableError, match="NO_RETRIEVAL_BACKEND"):
            mod.search_web("OpenCode docs")
        assert not mod._cache_path("OpenCode docs").exists()

- [ ] **Step 2: Run the focused test to verify it fails**

    Run: `python -m pytest tests/test_search_extended.py -k synthetic -q`
    Expected: FAIL because current code accepts list-only cache data and emits `_stub_results()`.

- [ ] **Step 3: Write the minimal implementation**

    class SearchUnavailableError(RuntimeError):
        code = "NO_RETRIEVAL_BACKEND"

    def _write_cache(query: str, results: list[dict], now: float) -> None:
        payload = {"schema_version": 2, "query": query, "created_at": now,
                   "expires_at": now + SEARCH_CACHE_TTL_SECONDS, "results": results}
        temporary = _cache_path(query).with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(_cache_path(query))

    Delete `_stub_results()` and every call site. Replace the gateway mock fallback with `SearchUnavailableError`. Reject and delete legacy cache values and cache records without all five result fields.

- [ ] **Step 4: Run focused tests to verify they pass**

    Run: `python -m pytest tests/test_search_extended.py tests/test_gateway_contract.py -q`
    Expected: PASS without live-network access.

- [ ] **Step 5: Commit**

    git add tests/test_search_extended.py tests/test_gateway_contract.py mcp-gateway/src/search.py mcp-gateway/src/gateway.py
    git commit -m "fix: reject synthetic search results"

### Task 2: Add Rust Candidate Processing Service

**Files:**
- Create: `search-core/Cargo.toml`
- Create: `search-core/src/lib.rs`
- Create: `search-core/src/main.rs`
- Create: `search-core/tests/http_contract.rs`
- Create: `search-core/Dockerfile`

**Interfaces:**
- Consumes `POST /v1/rank` JSON `{query, limit, candidates}`.
- Produces `200` JSON `{results}`.
- Candidate fields: `title`, `url`, `content`, `source`, `retrieved_at` strings.

- [ ] **Step 1: Write the failing Rust test**

    #[test]
    fn rank_discards_unprovenanced_and_out_of_site_candidates() {
        let response = rank(RankRequest::new("site:opencode.ai docs", 5, vec![
            candidate("https://opencode.ai/docs/", "searxng"),
            candidate("https://example.com/docs", "searxng"),
            candidate("https://opencode.ai/topics/x", ""),
        ]));
        assert_eq!(response.results.len(), 1);
        assert_eq!(response.results[0].url, "https://opencode.ai/docs");
    }

- [ ] **Step 2: Run Rust tests to verify they fail**

    Run: `cargo test --manifest-path search-core/Cargo.toml`
    Expected: FAIL because the crate does not exist.

- [ ] **Step 3: Write the minimal implementation**

    pub fn rank(request: RankRequest) -> RankResponse {
        let required_host = parse_site_host(&request.query);
        let mut seen = HashSet::new();
        let mut records: Vec<_> = request.candidates.into_iter()
            .filter_map(|candidate| canonicalize(candidate, required_host.as_deref()))
            .filter(|candidate| seen.insert(candidate.url.clone()))
            .collect();
        records.sort_by(|left, right| score(&request.query, right).cmp(&score(&request.query, left))
            .then_with(|| left.url.cmp(&right.url)));
        records.truncate(request.limit.min(20));
        RankResponse { results: records }
    }

    Expose `/healthz` and `/v1/rank` through Axum. Reject non-HTTP(S) URLs, blank provenance, and blank required fields. Make no network request.

- [ ] **Step 4: Run format and tests to verify they pass**

    Run: `cargo fmt --manifest-path search-core/Cargo.toml --check && cargo test --manifest-path search-core/Cargo.toml`
    Expected: PASS.

- [ ] **Step 5: Commit**

    git add search-core
    git commit -m "feat: add rust search ranking core"

### Task 3: Add Go Retrieval Service

**Files:**
- Create: `search-fetcher/go.mod`
- Create: `search-fetcher/cmd/search-fetcher/main.go`
- Create: `search-fetcher/internal/fetcher/fetcher.go`
- Create: `search-fetcher/internal/fetcher/fetcher_test.go`
- Create: `search-fetcher/Dockerfile`

**Interfaces:**
- Consumes `POST /v1/fetch` JSON `{query, limit}`.
- Produces `200` JSON `{candidates, providers}` or `503` JSON `{code: "NO_RETRIEVAL_BACKEND", providers}`.
- Every candidate has a non-empty `source` and RFC3339 `retrieved_at`.

- [ ] **Step 1: Write the failing Go test**

    func TestFetchReturnsOnlyRetrievedCandidates(t *testing.T) {
        upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            json.NewEncoder(w).Encode(map[string]any{"results": []map[string]string{{
                "title": "OpenCode Docs", "url": "https://opencode.ai/docs", "content": "Docs"}}})
        }))
        defer upstream.Close()
        got := New(upstream.URL, nil, time.Second).Fetch(context.Background(), "OpenCode docs", 5)
        if got.Code != "" || len(got.Candidates) != 1 || got.Candidates[0].Source != "searxng" {
            t.Fatalf("unexpected response: %#v", got)
        }
    }

- [ ] **Step 2: Run Go tests to verify they fail**

    Working directory: `search-fetcher`
    Run: `go test ./...`
    Expected: FAIL because the module does not exist.

- [ ] **Step 3: Write the minimal implementation**

    func (f *Fetcher) Fetch(ctx context.Context, query string, limit int) Response {
        ctx, cancel := context.WithTimeout(ctx, f.timeout)
        defer cancel()
        providers := []Provider{f.searxng, f.duckduckgo, f.bing, f.brave}
        results := make(chan ProviderResult, len(providers))
        for _, provider := range providers { go provider.Fetch(ctx, query, limit, results) }
        return collect(ctx, results, len(providers), limit)
    }

    Use `http.MaxBytesReader`, a client timeout, and request-scoped contexts. A provider may fail independently; only verified parsed upstream records enter `Candidates`. Return 503 when all sources are empty or unavailable.

- [ ] **Step 4: Run format and tests to verify they pass**

    Working directory: `search-fetcher`
    Run: `gofmt -w cmd/search-fetcher/main.go internal/fetcher/fetcher.go internal/fetcher/fetcher_test.go && go test ./...`
    Expected: PASS.

- [ ] **Step 5: Commit**

    git add search-fetcher
    git commit -m "feat: add go search fetcher"

### Task 4: Wire Native Services Into Python And Compose

**Files:**
- Modify: `mcp-gateway/src/search.py`
- Modify: `tests/test_search_extended.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `tests/test_docker_compose.py`

**Interfaces:**
- Python fetches `JINA_LOCAL_SEARCH_FETCHER_URL`, default `http://127.0.0.1:8082`.
- Python ranks with `JINA_LOCAL_SEARCH_CORE_URL`, default `http://127.0.0.1:8083`.
- Compose starts both services in profile `search` with loopback host mappings.

- [ ] **Step 1: Write the failing integration test**

    def test_search_calls_fetcher_then_core_and_caches_only_ranked_results(monkeypatch, tmp_path):
        mod = _load_search_module(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(mod.requests, "post", fake_native_post(calls))
        results = mod.search_web("site:opencode.ai docs", num=3)
        assert [call[0] for call in calls] == [
            mod.SEARCH_FETCHER_URL + "/v1/fetch", mod.SEARCH_CORE_URL + "/v1/rank"]
        assert results[0]["source"] == "searxng"

- [ ] **Step 2: Run the focused test to verify it fails**

    Run: `python -m pytest tests/test_search_extended.py tests/test_docker_compose.py -q`
    Expected: FAIL because native endpoints and compose services are absent.

- [ ] **Step 3: Write the minimal integration**

    def _fetch_candidates(query: str, limit: int) -> list[dict]:
        response = requests.post(f"{SEARCH_FETCHER_URL}/v1/fetch",
            json={"query": query, "limit": limit}, timeout=SEARCH_TIMEOUT)
        if response.status_code == 503:
            raise SearchUnavailableError("NO_RETRIEVAL_BACKEND")
        response.raise_for_status()
        return response.json()["candidates"]

    Add a separate `_rank_candidates()` POST to `/v1/rank`. Add `search-fetcher` and `search-core` Compose services with profiles `full` and `search`, `restart: 'no'`, health checks, local build contexts, and loopback mappings `8082` and `8083`.

- [ ] **Step 4: Run focused tests and config validation to verify they pass**

    Run: `python -m pytest tests/test_search_extended.py tests/test_docker_compose.py tests/test_gateway_contract.py -q && docker compose --env-file .env.example config --quiet`
    Expected: PASS.

- [ ] **Step 5: Commit**

    git add mcp-gateway/src/search.py tests/test_search_extended.py docker-compose.yml .env.example tests/test_docker_compose.py
    git commit -m "feat: wire native search pipeline"

### Task 5: Document, Benchmark, And Verify

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/bench-full.md`
- Modify: `docs/jina-vs-jina-local.md`
- Create: `scripts/bench_search_integrity.py`
- Create: `tests/test_search_integrity_bench.py`

**Interfaces:**
- `scripts/bench_search_integrity.py` reports `synthetic_results`, cache status, provider statuses, and latency percentiles as JSON.
- CI builds/tests Go and Rust before Python tests.

- [ ] **Step 1: Write the failing benchmark test**

    def test_integrity_benchmark_rejects_fabricated_results(tmp_path):
        report = bench.evaluate([synthetic_candidate()], query="OpenCode docs")
        assert report["synthetic_results"] == 0
        assert report["accepted_results"] == 0

- [ ] **Step 2: Run it to verify it fails**

    Run: `python -m pytest tests/test_search_integrity_bench.py -q`
    Expected: FAIL because the benchmark module does not exist.

- [ ] **Step 3: Write the minimal benchmark and documentation**

    def evaluate(candidates: list[dict], query: str) -> dict:
        accepted = [item for item in candidates if item.get("source") and item.get("retrieved_at")]
        return {"query": query, "accepted_results": len(accepted),
                "synthetic_results": len(candidates) - len(accepted)}

    Document the three services, failure semantics, cache TTL, health checks, and `--profile search`. Remove every numeric or qualitative claim contradicted by the new truthful failure behavior. Add CI setup/test steps for Go and Rust.

- [ ] **Step 4: Run all independent verification**

    Run: `cargo test --manifest-path search-core/Cargo.toml && (cd search-fetcher && go test ./...) && python -m pytest tests/test_search_extended.py tests/test_search_integrity_bench.py tests/test_gateway_contract.py tests/test_mcp_compatibility.py -q && docker compose --env-file .env.example config --quiet`
    Expected: PASS. Fixed-path deployment checks execute in GitHub Actions from the normal checkout, not the development worktree.

- [ ] **Step 5: Commit**

    git add .github/workflows/ci.yml README.md docs/bench-full.md docs/jina-vs-jina-local.md scripts/bench_search_integrity.py tests/test_search_integrity_bench.py
    git commit -m "docs: document native search integrity"
