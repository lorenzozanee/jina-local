use axum::{
    Router,
    extract::Json,
    http::StatusCode,
    routing::{get, post},
};
use jina_search_core::{RankRequest, RankResponse, rank};

async fn rank_handler(Json(request): Json<RankRequest>) -> Json<RankResponse> {
    Json(rank(request))
}

async fn health() -> StatusCode {
    StatusCode::OK
}

#[tokio::main]
async fn main() {
    let app = Router::new()
        .route("/healthz", get(health))
        .route("/v1/rank", post(rank_handler));
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8083")
        .await
        .expect("bind search-core");
    axum::serve(listener, app).await.expect("serve search-core");
}
