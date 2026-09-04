package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/lorenzozanee/jina-local/search-fetcher/internal/fetcher"
)

func TestReadyzReturnsJSON200AfterRetrievedCandidate(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"results": []map[string]string{{"title": "Docs", "url": "https://example.com", "content": "content"}}})
	}))
	defer upstream.Close()

	handler := newHandler(fetcher.New(upstream.URL, time.Second), "docs")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if recorder.Code != http.StatusOK || !strings.HasPrefix(recorder.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("unexpected response: code=%d content-type=%q body=%s", recorder.Code, recorder.Header().Get("Content-Type"), recorder.Body.String())
	}
	var result fetcher.Response
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil || len(result.Candidates) != 1 {
		t.Fatalf("unexpected JSON response: err=%v body=%s", err, recorder.Body.String())
	}
}

func TestReadyzReturns503JSONWhenProviderUnavailable(t *testing.T) {
	handler := newHandler(fetcher.New("http://127.0.0.1:1", time.Millisecond), "docs")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if recorder.Code != http.StatusServiceUnavailable || !strings.HasPrefix(recorder.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("unexpected response: code=%d content-type=%q body=%s", recorder.Code, recorder.Header().Get("Content-Type"), recorder.Body.String())
	}
	var result fetcher.Response
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil || result.Code != "NO_RETRIEVAL_BACKEND" || len(result.Candidates) != 0 {
		t.Fatalf("unexpected JSON response: err=%v body=%s", err, recorder.Body.String())
	}
}
