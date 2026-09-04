package main

import (
	"encoding/json"
	"net/http"
	"os"
	"time"

	"github.com/lorenzozanee/jina-local/search-fetcher/internal/fetcher"
)

func main() {
	service := fetcher.New(env("SEARXNG_URL", "http://127.0.0.1:8081"), 5*time.Second)
	http.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	http.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		result := service.Probe(r.Context(), env("SEARCH_READINESS_QUERY", "OpenCode docs"))
		if result.Code != "" || len(result.Candidates) == 0 {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(result)
	})
	http.HandleFunc("/v1/fetch", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var input struct {
			Query string `json:"query"`
			Limit int    `json:"limit"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)).Decode(&input) != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		result := service.Fetch(r.Context(), input.Query, input.Limit)
		if result.Code != "" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(result)
	})
	_ = http.ListenAndServe(env("SEARCH_FETCHER_BIND_ADDR", "127.0.0.1")+":"+env("SEARCH_FETCHER_PORT", "8082"), nil)
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
