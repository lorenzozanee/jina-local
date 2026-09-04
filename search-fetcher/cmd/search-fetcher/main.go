package main

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"time"

	"github.com/lorenzozanee/jina-local/search-fetcher/internal/fetcher"
)

func main() {
	service := fetcher.New(env("SEARXNG_URL", "http://search:8080"), 5*time.Second)
	http.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
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
		result := service.Fetch(context.Background(), input.Query, input.Limit)
		if result.Code != "" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(result)
	})
	_ = http.ListenAndServe(":"+env("SEARCH_FETCHER_PORT", "8082"), nil)
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
