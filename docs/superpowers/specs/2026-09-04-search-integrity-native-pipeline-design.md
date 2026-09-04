# Search Integrity Native Pipeline Design

## Goal

Replace fabricated `search_web` output with a provenance-preserving local pipeline that returns only retrieved documents or a machine-visible failure. Keep the MCP surface stable while separating network I/O, ranking, and agent/model orchestration by their operational strengths.

## Evidence And Scope

The incident reproduction dated 2026-09-03 proves that `mcp-gateway/src/search.py` always mixes `_stub_results()` into retrieved candidates and caches those fabricated documents. `gateway.py` has an additional mock fallback. Existing tests reward keyword echoing and count, so they do not detect invented URLs.

The reference implementations examined are `spider-rs/spider` and `us/crw` for Rust crawler/service boundaries, `quickwit-oss/tantivy` for deterministic local ranking/indexing, `geziyor/geziyor` for Go concurrency, and Firecrawl's separation of search, scrape, crawl, and asynchronous work. This project will adopt only the relevant pattern: bounded components with explicit source status. It will not attempt to build a global crawler or index in this change.

## Decisions

### Public Contract

`search_web(query, num=5)` and `parallel_search_web(queries, num=5)` retain their MCP names and result-list shape. Every returned result has non-empty `title`, `url`, and `content`, plus `source` and `retrieved_at` provenance fields. A query with no successful retrieval raises `SearchUnavailableError` containing the stable code `NO_RETRIEVAL_BACKEND`; it never returns a plausible placeholder.

`site:` operators are strict: a result is retained only when its host equals or is a subdomain of the requested host. Candidate URLs must be HTTP(S), and tracking parameters and fragments are removed before de-duplication.

### Component Ownership

Python remains the MCP boundary, cache owner, Reader/Deep Search integration, and interface to GPU embeddings/reranking. It makes local HTTP calls to the two native services and translates their documented errors into MCP-visible exceptions.

The Go `search-fetcher` service owns parallel bounded external retrieval. It queries SearXNG first and may query DuckDuckGo, Bing, and Brave concurrently when enabled. Each response contains candidates and per-provider status. It enforces request deadlines, response-size limits, and no synthetic fallback.

The Rust `search-core` service owns deterministic candidate processing. It validates provenance, canonicalizes URLs, enforces `site:` filtering, removes duplicate canonical URLs, and ranks the remaining candidates by query token overlap with a stable tie-break. It has no outbound network access and no cache.

### Cache Semantics

Python stores successful responses in schema-versioned cache envelopes: `schema_version`, `query`, `created_at`, `expires_at`, and `results`. The default TTL is five minutes through `JINA_LOCAL_SEARCH_CACHE_TTL_SECONDS`. Empty/error responses are never cached. Legacy list-only cache files and entries lacking provenance are invalid, deleted, and treated as misses. Writes use a temporary file followed by atomic replacement.

### Runtime And Deployment

`docker compose --profile search up -d` starts SearXNG, `search-fetcher`, and `search-core`. Both new services expose loopback-only host ports, health endpoints, and no automatic restart. Their Dockerfiles compile native code in multi-stage builds, so runtime users do not require local Go or Rust toolchains.

CI validates Python on 3.11/3.12, `go test ./...`, `cargo test --manifest-path search-core/Cargo.toml`, and Docker Compose configuration. The baseline suite's fixed-deployment-path assertions remain deployment checks; feature tests must run independently inside the worktree without editing global MCP configuration.

## Data Flow

1. MCP calls Python `search_web`.
2. Python checks a fresh, provenance-valid cache envelope.
3. On a miss, Python posts `{query, limit}` to Go `/v1/fetch`.
4. Go returns only records obtained from a named backend, or HTTP 503 with provider statuses.
5. Python posts candidates to Rust `/v1/rank`.
6. Rust returns validated, de-duplicated, ranked records with provenance.
7. Python writes a success-only cache envelope and returns results.

## Error Handling

The Go service maps invalid input to 400, unavailable providers to 503 with `NO_RETRIEVAL_BACKEND`, and oversized or malformed upstream responses to a failed provider status. Rust maps malformed requests to 400 and returns an empty successful result list when all supplied candidates are rejected. Python raises `SearchUnavailableError` only for fetcher 503 or unusable native-service responses; an empty valid native ranking returns `[]` and is not cached.

`parallel_search_web` preserves query order. It raises the first `SearchUnavailableError` after cancelling outstanding local tasks; it does not replace failed groups with artificial results.

## Verification

Regression tests must prove no `/topics/` fabricated URL or known stub sentence can reach `search_web`; no error/empty response is cached; old cache data is rejected; a `site:` query cannot leak another host; and the gateway cannot fall back to mock search data.

Go tests use `httptest` upstreams to prove deadline, source status, and no-result 503 behavior. Rust tests cover canonicalization, provenance enforcement, site matching, deterministic ranking, and the HTTP contract. Python tests use local request fakes and never depend on live public engines. A compose smoke test verifies both native service declarations and health endpoints when Docker is available.

## Non-Goals

This change does not build a web-scale crawler, scrape JavaScript pages, replace SearXNG with a proprietary index, add cloud credentials, or move embedding/reranking out of Python/TEI. A Tantivy-backed local corpus is a separate, measured follow-up after trustworthy live retrieval is in place.
