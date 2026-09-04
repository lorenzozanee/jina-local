use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use url::Url;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Candidate {
    pub title: String,
    pub url: String,
    pub content: String,
    pub source: String,
    pub retrieved_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RankRequest {
    pub query: String,
    pub limit: usize,
    pub candidates: Vec<Candidate>,
}

#[derive(Debug, Serialize)]
pub struct RankResponse {
    pub results: Vec<Candidate>,
}

fn site_host(query: &str) -> Option<String> {
    query.split_whitespace().find_map(|term| {
        term.strip_prefix("site:")
            .map(|host| {
                host.trim_start_matches("https://")
                    .trim_start_matches("http://")
                    .trim_end_matches('/')
                    .to_ascii_lowercase()
            })
            .filter(|host| !host.is_empty())
    })
}

fn words(value: &str) -> HashSet<String> {
    value
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(|word| word.to_ascii_lowercase())
        .collect()
}

fn score(query: &str, candidate: &Candidate) -> usize {
    let query_words = words(query);
    let title_words = words(&candidate.title);
    let content_words = words(&candidate.content);
    query_words
        .iter()
        .filter(|word| title_words.contains(*word))
        .count()
        * 2
        + query_words
            .iter()
            .filter(|word| content_words.contains(*word))
            .count()
}

fn canonicalize(mut candidate: Candidate, required_host: Option<&str>) -> Option<Candidate> {
    if [
        &candidate.title,
        &candidate.url,
        &candidate.content,
        &candidate.source,
        &candidate.retrieved_at,
    ]
    .iter()
    .any(|value| value.trim().is_empty())
    {
        return None;
    }
    let mut url = Url::parse(&candidate.url).ok()?;
    if !matches!(url.scheme(), "http" | "https") {
        return None;
    }
    let host = url.host_str()?.to_ascii_lowercase();
    if let Some(required_host) = required_host {
        if host != required_host && !host.ends_with(&format!(".{required_host}")) {
            return None;
        }
    }
    url.set_fragment(None);
    let kept: Vec<(String, String)> = url
        .query_pairs()
        .filter(|(key, _)| !key.to_ascii_lowercase().starts_with("utm_"))
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect();
    if kept.is_empty() {
        url.set_query(None);
    } else {
        url.query_pairs_mut()
            .clear()
            .extend_pairs(kept.iter().map(|(key, value)| (key, value)));
    }
    let normalized = url.to_string().trim_end_matches('/').to_string();
    candidate.url = normalized;
    Some(candidate)
}

pub fn rank(request: RankRequest) -> RankResponse {
    let required_host = site_host(&request.query);
    let mut seen = HashSet::new();
    let mut results: Vec<_> = request
        .candidates
        .into_iter()
        .filter_map(|candidate| canonicalize(candidate, required_host.as_deref()))
        .filter(|candidate| seen.insert(candidate.url.clone()))
        .collect();
    results.sort_by(|left, right| {
        score(&request.query, right)
            .cmp(&score(&request.query, left))
            .then_with(|| left.url.cmp(&right.url))
    });
    results.truncate(request.limit.min(20));
    RankResponse { results }
}
