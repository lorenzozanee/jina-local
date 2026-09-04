package fetcher

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Candidate struct {
	Title       string `json:"title"`
	URL         string `json:"url"`
	Content     string `json:"content"`
	Source      string `json:"source"`
	RetrievedAt string `json:"retrieved_at"`
}
type ProviderStatus struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Error  string `json:"error,omitempty"`
}
type Response struct {
	Candidates []Candidate      `json:"candidates"`
	Providers  []ProviderStatus `json:"providers"`
	Code       string           `json:"code,omitempty"`
}
type Fetcher struct {
	searxngURL string
	client     *http.Client
}

func New(searxngURL string, timeout time.Duration) *Fetcher {
	return &Fetcher{strings.TrimRight(searxngURL, "/"), &http.Client{Timeout: timeout}}
}

func (f *Fetcher) Probe(ctx context.Context, query string) Response {
	return f.Fetch(ctx, query, 1)
}

func (f *Fetcher) Fetch(ctx context.Context, query string, limit int) Response {
	if strings.TrimSpace(query) == "" {
		return Response{Code: "INVALID_QUERY", Providers: []ProviderStatus{{Name: "searxng", Status: "skipped", Error: "query is required"}}}
	}
	if limit < 1 {
		limit = 5
	}
	if limit > 20 {
		limit = 20
	}
	endpoint := f.searxngURL + "/search?q=" + url.QueryEscape(query) + "&format=json&categories=general&language=en"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return unavailable(err)
	}
	resp, err := f.client.Do(req)
	if err != nil {
		return unavailable(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return unavailable(fmt.Errorf("status %d", resp.StatusCode))
	}
	var payload struct {
		Results []struct {
			Title   string `json:"title"`
			URL     string `json:"url"`
			Content string `json:"content"`
		} `json:"results"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(nil, resp.Body, 2<<20)).Decode(&payload); err != nil {
		return unavailable(err)
	}
	result := Response{Providers: []ProviderStatus{{Name: "searxng", Status: "ok"}}}
	for _, item := range payload.Results {
		if strings.TrimSpace(item.Title) == "" || strings.TrimSpace(item.URL) == "" {
			continue
		}
		content := strings.TrimSpace(item.Content)
		if content == "" {
			content = item.Title
		}
		result.Candidates = append(result.Candidates, Candidate{item.Title, item.URL, content, "searxng", time.Now().UTC().Format(time.RFC3339)})
		if len(result.Candidates) == limit {
			break
		}
	}
	if len(result.Candidates) == 0 {
		result.Code = "NO_RETRIEVAL_BACKEND"
		result.Providers[0].Status = "empty"
	}
	return result
}

func unavailable(err error) Response {
	return Response{Code: "NO_RETRIEVAL_BACKEND", Providers: []ProviderStatus{{Name: "searxng", Status: "unavailable", Error: err.Error()}}}
}
