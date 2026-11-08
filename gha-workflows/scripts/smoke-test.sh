#!/usr/bin/env bash

set -euo pipefail

URL="${1:-http://localhost:8080}"
RETRIES="${RETRIES:-30}"
WAIT_TIME="${WAIT_TIME:-5}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
API_PATH="${API_PATH:-/weatherforecast}"

if [[ "$URL" != http://* && "$URL" != https://* ]]; then
  echo "URL must start with http:// or https://" >&2
  exit 2
fi

check_health() {
  local status_code
  status_code="$(curl --silent --show-error --max-time 30 --output /dev/null \
    --write-out '%{http_code}' "${URL%/}$HEALTH_PATH")"
  [[ "$status_code" == "200" ]]
}

check_api() {
  local response_file headers_file status_code
  response_file="$(mktemp)"
  headers_file="$(mktemp)"
  trap 'rm -f "$response_file" "$headers_file"' RETURN

  status_code="$(curl --silent --show-error --max-time 30 \
    --dump-header "$headers_file" --output "$response_file" \
    --write-out '%{http_code}' "${URL%/}$API_PATH")"
  [[ "$status_code" == "200" ]]
  grep -qi '^content-type: application/json' "$headers_file"
  python3 - "$response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response:
    payload = json.load(response)

if not isinstance(payload, (list, dict)) or not payload:
    raise SystemExit("API response must be a non-empty JSON array or object.")
PY
}

echo "Running smoke tests against ${URL%/}"
echo "Waiting for service to be healthy..."

for attempt in $(seq 1 "$RETRIES"); do
  if check_health; then
    echo "Health check passed."
    if check_api; then
      echo "API JSON check passed."
      exit 0
    fi
    echo "Attempt $attempt/$RETRIES: API check failed; waiting ${WAIT_TIME}s..."
  else
    echo "Attempt $attempt/$RETRIES: service is not healthy; waiting ${WAIT_TIME}s..."
  fi
  sleep "$WAIT_TIME"
done

echo "Smoke tests failed after $((RETRIES * WAIT_TIME)) seconds." >&2
exit 1