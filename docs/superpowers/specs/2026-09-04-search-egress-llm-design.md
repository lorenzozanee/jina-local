# Search Egress and Evidence-Aware LLM Design

## Goal

Make local web search retrieve real, attributable results through the host's proxy,
surface egress failure as an operational state, and optionally use an OpenAI-compatible
LLM only to plan query variants and rerank already retrieved evidence.

## Problem

The September 4 live test started SearXNG, the Go fetcher, and the Rust core successfully,
but all search queries returned `NO_RETRIEVAL_BACKEND`. The host proxy at `127.0.0.1:7890`
worked for HTTP and SOCKS, while containers could not reach it because their loopback network
namespace is separate. Service `/healthz` endpoints therefore proved process liveness, not
that SearXNG could retrieve public web results.

## Architecture

`search` and `search-fetcher` use Docker host networking on the supported Linux deployment.
SearXNG accesses the host proxy at a configurable loopback URL. The fetcher accesses SearXNG
through its host-loopback URL and binds its public API only to `127.0.0.1`. `search-core`
continues to validate provenance, canonicalize URLs, apply `site:` filtering, deduplicate, and
rank candidates.

The SearXNG configuration remains source-controlled as a template. A small wrapper copies it
into a container-local named volume at startup and appends the configured `outgoing.proxies`
section there. No proxy URL is committed to the repository.

## Egress Contracts

- `JINA_LOCAL_SEARCH_PROXY_URL` is required when the `search` profile is used and is an HTTP
  or SOCKS proxy URL reachable from host loopback.
- `JINA_LOCAL_SEARCH_READINESS_QUERY` names the live search probe. Its result must contain at
  least one fully provenanced candidate.
- `/healthz` remains a process liveness endpoint.
- `/readyz` invokes the configured live retrieval probe. It returns `200` with provider status
  only when a valid candidate is retrieved, otherwise `503` with `NO_RETRIEVAL_BACKEND` and no
  fabricated candidates.
- The gateway still returns `SearchUnavailableError` with `NO_RETRIEVAL_BACKEND` when the
  fetcher is unavailable or returns no valid candidates. An empty valid Rust ranking remains
  an empty list and is not cached.

## LLM Contracts

The LLM integration uses the existing `requests` dependency and an OpenAI-compatible
`/chat/completions` endpoint. It is enabled only if all three values are present:

- `JINA_LOCAL_LLM_BASE_URL`
- `JINA_LOCAL_LLM_MODEL`
- `JINA_LOCAL_LLM_API_KEY`

The client requests JSON Schema output. Query planning returns a bounded list of non-empty
query strings; candidate reranking returns only identifiers from the supplied candidate list.
Every response is schema-validated locally. Invalid, unavailable, or timed-out LLM calls leave
the original query and Rust order unchanged. The LLM never creates result URLs, titles,
contents, sources, timestamps, citations, or answers.

`search_web_deep` may use planned query variants, merge real candidate lists with reciprocal
rank fusion, and then ask the LLM to rerank the final bounded candidate IDs. `search_web`
remains a low-latency single-query retrieval API.

## Evaluation

Live evaluation is opt-in through `JINA_LOCAL_LIVE_SEARCH=1`; unit and contract tests never
depend on external search engines. The live suite uses real proxy-routed services and a
versioned query corpus covering official documentation, `site:` filtering, multi-source
research, and Chinese/English mixed queries.

Each run archives query, timestamp, provider status, candidate provenance, normalized URLs,
latencies, relevant-source labels, MRR, nDCG@5, read-source coverage, and failure codes under
`/tmp/opencode/jina-local`. It runs the same corpus three times. A run passes only when every
returned candidate is provenanced, every labeled target is retrieved, and no unavailable query
is misreported as a successful search. LLM enhancement is retained only when it preserves
provenance and does not reduce corpus MRR or nDCG@5 versus the Rust baseline.

## Security and Operations

- API keys and proxy URLs exist only in ignored `.env`; docs show variable names, never values.
- The host-network services bind only loopback ports.
- The named generated SearXNG configuration volume is regenerated from the tracked template on
  every start.
- Production readiness and live evaluation report sanitized provider state, never credentials.
- The worktree cannot satisfy the existing fixed-deployment-path assertions; the full
  path-sensitive suite is run from `/home/cc/jina-local` only after the PR is merged. Branch and
  CI verification use the repository's reproducible, path-independent test selection.
