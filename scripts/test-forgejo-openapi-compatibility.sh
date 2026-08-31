#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

command -v docker >/dev/null
command -v uv >/dev/null

free_port() {
    uv run python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

old_image=${FORGEJO_OLD_IMAGE:-data.forgejo.org/forgejo/forgejo:16.0.2-rootless}
new_image=${FORGEJO_NEW_IMAGE:-data.forgejo.org/forgejo/forgejo:16.0.3-rootless}
old_port=$(free_port)
new_port=$(free_port)
old_container="forgejo-mcp-openapi-old-$$"
new_container="forgejo-mcp-openapi-new-$$"
temporary_dir=$(mktemp -d)

cleanup() {
    status=$?
    docker rm -f "$old_container" "$new_container" >/dev/null 2>&1 || true
    rm -rf "$temporary_dir"
    exit "$status"
}
trap cleanup EXIT INT TERM

start_forgejo() {
    name=$1
    port=$2
    image=$3
    docker run -d --name "$name" \
        -p "127.0.0.1:$port:3000" \
        -e FORGEJO__database__DB_TYPE=sqlite3 \
        -e FORGEJO__database__PATH=/var/lib/gitea/data/forgejo.db \
        -e FORGEJO__security__INSTALL_LOCK=true \
        -e FORGEJO__server__DISABLE_SSH=true \
        "$image" >/dev/null
}

wait_for_forgejo() {
    port=$1
    for _ in $(seq 1 120); do
        status=$(curl -sS -o /dev/null -w '%{http_code}' \
            "http://127.0.0.1:$port/api/v1/version" || true)
        if [ "$status" = 200 ]; then
            return
        fi
        sleep 1
    done
    echo "Forgejo on port $port did not become ready" >&2
    exit 1
}

start_forgejo "$old_container" "$old_port" "$old_image"
start_forgejo "$new_container" "$new_port" "$new_image"
wait_for_forgejo "$old_port"
wait_for_forgejo "$new_port"

curl -fsS "http://127.0.0.1:$old_port/swagger.v1.json" > "$temporary_dir/old.json"
curl -fsS "http://127.0.0.1:$new_port/swagger.v1.json" > "$temporary_dir/new.json"

uv run python scripts/verify_forgejo_openapi.py "$temporary_dir/old.json"
uv run python scripts/verify_forgejo_openapi.py "$temporary_dir/new.json"
uv run python scripts/compare_forgejo_openapi.py \
    "$temporary_dir/old.json" \
    "$temporary_dir/new.json" \
    --expect tests/contracts/forgejo-16.0.2-to-16.0.3-openapi-diff.json \
    --fail-on-endpoint-changes
