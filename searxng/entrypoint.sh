#!/bin/sh
set -eu

proxy=${JINA_LOCAL_SEARCH_PROXY_URL:-}
if [ -z "$(printf '%s' "$proxy" | tr -d '[:space:]')" ]; then
    printf '%s\n' 'JINA_LOCAL_SEARCH_PROXY_URL must be set' >&2
    exit 1
fi

config=/etc/searxng/settings.yml
cp /etc/searxng-template/settings.yml "$config"
sed -i "/^server:/a\\  port: ${SEARXNG_PORT:-8081}" "$config"
printf '\noutgoing:\n  proxies:\n    all://: "%s"\n' "$proxy" >> "$config"

exec /usr/local/searxng/entrypoint.sh "$@"
