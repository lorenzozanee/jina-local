#!/bin/sh
set -eu

config=/etc/searxng/settings.yml
cp /etc/searxng-template/settings.yml "$config"

if [ -n "${JINA_LOCAL_SEARCH_PROXY_URL:-}" ]; then
    printf '\noutgoing:\n  proxies:\n    all://: "%s"\n' "$JINA_LOCAL_SEARCH_PROXY_URL" >> "$config"
fi

exec /usr/local/searxng/entrypoint.sh "$@"
