#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.yml"

printf '[jina-local-idle-stop] checking established connections on ports 3001 and 3002\n'
connections=$(ss -Htan state established '( sport = :3001 or sport = :3002 )' || true)
if [[ -n "$connections" ]]; then
  printf '%s\n' '[jina-local-idle-stop] active model connection found; skipping stop'
  exit 0
fi

running=$(docker compose -f "$COMPOSE_FILE" ps -q --status running embeddings reranker)
if [[ -z "$running" ]]; then
  printf '%s\n' '[jina-local-idle-stop] embeddings/reranker are not running; nothing to stop'
  exit 0
fi

printf '%s\n' '[jina-local-idle-stop] no active model connections; stopping embeddings and reranker'
docker compose -f "$COMPOSE_FILE" stop embeddings reranker
printf '%s\n' '[jina-local-idle-stop] embeddings and reranker stopped'
