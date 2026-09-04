package fetcher

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestFetchReturnsOnlyRetrievedCandidates(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"results": []map[string]string{{"title": "OpenCode Docs", "url": "https://opencode.ai/docs", "content": "Docs"}}})
	}))
	defer upstream.Close()

	got := New(upstream.URL, time.Second).Fetch(context.Background(), "OpenCode docs", 5)
	if got.Code != "" || len(got.Candidates) != 1 || got.Candidates[0].Source != "searxng" {
		t.Fatalf("unexpected response: %#v", got)
	}
}

func TestFetchReportsUnavailableWithoutSyntheticCandidates(t *testing.T) {
	got := New("http://127.0.0.1:1", time.Millisecond).Fetch(context.Background(), "OpenCode docs", 5)
	if got.Code != "NO_RETRIEVAL_BACKEND" || len(got.Candidates) != 0 || len(got.Providers) != 1 {
		t.Fatalf("unexpected response: %#v", got)
	}
}

func TestReadinessReturnsProviderStatusAfterRetrievedCandidate(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"results": []map[string]string{{"title": "OpenCode Docs", "url": "https://opencode.ai/docs", "content": "Docs"}}})
	}))
	defer upstream.Close()

	got := New(upstream.URL, time.Second).Probe(context.Background(), "OpenCode docs")
	if got.Code != "" || len(got.Candidates) != 1 || len(got.Providers) != 1 || got.Providers[0].Status != "ok" {
		t.Fatalf("unexpected response: %#v", got)
	}
}

func TestReadinessRejectsUnavailableProviderWithoutCandidates(t *testing.T) {
	got := New("http://127.0.0.1:1", time.Millisecond).Probe(context.Background(), "OpenCode docs")
	if got.Code != "NO_RETRIEVAL_BACKEND" || len(got.Candidates) != 0 {
		t.Fatalf("unexpected response: %#v", got)
	}
}
