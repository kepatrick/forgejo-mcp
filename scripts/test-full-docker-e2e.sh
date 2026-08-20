#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

command -v docker >/dev/null
command -v uv >/dev/null
docker compose version >/dev/null

free_port() {
    uv run python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

project="forgejo-mcp-e2e-$$"
temporary_dir=$(mktemp -d)
export POSTGRES_PASSWORD="Postgres-E2E-pass-123!"
export POSTGRES_HOST_PORT=$(free_port)
export FMCP_HTTP_PORT=$(free_port)
export FORGEJO_TEST_HTTP_PORT=$(free_port)
export FMCP_COOKIE_SECURE=false
export FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true
export FMCP_ENVIRONMENT=test
export FMCP_ADMIN_PASSWORD_FILE="$temporary_dir/admin_password"
export FMCP_CREDENTIAL_KEY_FILE="$temporary_dir/credential_key"
export FMCP_RUNNER_CONFIG_FILE="$temporary_dir/runner-config.yml"
export FMCP_E2E_ADMIN_PASSWORD="Admin-E2E-pass-123!"
export FMCP_E2E_DEVELOPER_PASSWORD="Developer-E2E-pass-123!"
export FMCP_E2E_REVIEWER_PASSWORD="Reviewer-E2E-pass-123!"
export FMCP_E2E_APP_URL="http://127.0.0.1:$FMCP_HTTP_PORT"
export FMCP_E2E_FORGEJO_URL="http://127.0.0.1:$FORGEJO_TEST_HTTP_PORT"
export FMCP_E2E_FORGEJO_INTERNAL_URL="http://forgejo:3000"

printf '%s\n' "$FMCP_E2E_ADMIN_PASSWORD" > "$FMCP_ADMIN_PASSWORD_FILE"
uv run python - <<PY
import base64
import os
from pathlib import Path
Path("$FMCP_CREDENTIAL_KEY_FILE").write_bytes(base64.b64encode(os.urandom(32)) + b"\n")
PY
chmod 0600 "$FMCP_ADMIN_PASSWORD_FILE" "$FMCP_CREDENTIAL_KEY_FILE"

compose() {
    docker compose -p "$project" -f deploy/compose.yaml \
        --profile test-forgejo --profile test-runner "$@"
}

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "Full Docker E2E failed; recent service logs:" >&2
        compose logs --tail=120 app postgres forgejo runner >&2 || true
    fi
    compose down -v --remove-orphans --rmi local >/dev/null 2>&1 || true
    rm -rf "$temporary_dir"
    exit "$status"
}
trap cleanup EXIT INT TERM

compose up -d --build app postgres forgejo

ready=false
for _ in $(seq 1 120); do
    app_status=$(curl -sS -o /dev/null -w '%{http_code}' "$FMCP_E2E_APP_URL/health/ready" || true)
    forgejo_status=$(curl -sS -o /dev/null -w '%{http_code}' \
        "$FMCP_E2E_FORGEJO_URL/api/v1/version" || true)
    if [ "$app_status" = 200 ] && [ "$forgejo_status" = 200 ]; then
        ready=true
        break
    fi
    sleep 2
done
if [ "$ready" != true ]; then
    echo "Full Docker stack did not become ready" >&2
    exit 1
fi

echo "PASS Docker Compose app, PostgreSQL, and Forgejo readiness"

compose restart app >/dev/null
app_restarted=false
for _ in $(seq 1 60); do
    app_status=$(curl -sS -o /dev/null -w '%{http_code}' "$FMCP_E2E_APP_URL/health/ready" || true)
    if [ "$app_status" = 200 ]; then
        app_restarted=true
        break
    fi
    sleep 1
done
if [ "$app_restarted" != true ]; then
    echo "App did not become ready after Docker restart" >&2
    exit 1
fi
curl -fsS "$FMCP_E2E_APP_URL/metrics" | grep -q 'forgejo_mcp_db_pool_size'
echo "PASS graceful Docker app restart, readiness, and metrics"

compose exec -T forgejo forgejo admin user create \
    --username developer \
    --password "$FMCP_E2E_DEVELOPER_PASSWORD" \
    --email developer@example.test \
    --must-change-password=false >/dev/null
compose exec -T forgejo forgejo admin user create \
    --username reviewer \
    --password "$FMCP_E2E_REVIEWER_PASSWORD" \
    --email reviewer@example.test \
    --must-change-password=false >/dev/null

runner_secret=$(uv run python -c 'import secrets; print(secrets.token_hex(20))')
runner_uuid=$(compose exec -T forgejo forgejo forgejo-cli actions register \
    --name full-docker-e2e --secret "$runner_secret" | tr -d '\r\n')
if [ -z "$runner_uuid" ]; then
    echo "Forgejo runner registration did not return a UUID" >&2
    exit 1
fi
cat > "$FMCP_RUNNER_CONFIG_FILE" <<EOF
log:
  level: info
runner:
  capacity: 1
  timeout: 5m
  shutdown_timeout: 30s
  fetch_timeout: 10s
  fetch_interval: 1s
  report_interval: 1s
  labels:
    - docker:docker://docker.io/library/alpine:3.20
container:
  network: ${project}_default
  docker_host: "-"
server:
  connections:
    e2e:
      url: http://forgejo:3000/
      uuid: $runner_uuid
      token: $runner_secret
EOF
chmod 0644 "$FMCP_RUNNER_CONFIG_FILE"
compose up -d runner

uv run python tests/e2e/full_docker_flow.py
