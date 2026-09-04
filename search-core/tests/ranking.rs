use jina_search_core::{Candidate, RankRequest, rank};

fn candidate(url: &str, source: &str) -> Candidate {
    Candidate {
        title: "OpenCode documentation".into(),
        url: url.into(),
        content: "Retrieved documentation about OpenCode.".into(),
        source: source.into(),
        retrieved_at: "2026-09-04T00:00:00Z".into(),
    }
}

#[test]
fn rank_discards_unprovenanced_and_out_of_site_candidates() {
    let response = rank(RankRequest {
        query: "site:opencode.ai documentation".into(),
        limit: 5,
        candidates: vec![
            candidate("https://opencode.ai/docs/", "searxng"),
            candidate("https://example.com/docs", "searxng"),
            candidate("https://opencode.ai/topics/x", ""),
        ],
    });

    assert_eq!(response.results.len(), 1);
    assert_eq!(response.results[0].url, "https://opencode.ai/docs");
}

#[test]
fn rank_deduplicates_tracking_urls_and_keeps_stable_order() {
    let response = rank(RankRequest {
        query: "OpenCode documentation".into(),
        limit: 5,
        candidates: vec![
            candidate("https://opencode.ai/docs/?utm_source=search", "searxng"),
            candidate("https://opencode.ai/docs/#intro", "bing"),
        ],
    });

    assert_eq!(response.results.len(), 1);
    assert_eq!(response.results[0].url, "https://opencode.ai/docs");
    assert_eq!(response.results[0].source, "searxng");
}
