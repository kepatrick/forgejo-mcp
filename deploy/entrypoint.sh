#!/bin/sh
set -eu

secret_dir=/run/forgejo-mcp-secrets
install -d -m 0700 -o app -g app "$secret_dir"

copy_secret() {
    source_path=$1
    target_name=$2
    if [ ! -r "$source_path" ]; then
        echo "Forgejo MCP secret is missing or unreadable: $source_path" >&2
        exit 1
    fi
    install -m 0400 -o app -g app "$source_path" "$secret_dir/$target_name"
}

copy_secret "${FMCP_BOOTSTRAP_ADMIN_PASSWORD_FILE:-/run/secrets/admin_password}" admin_password
copy_secret "${FMCP_CREDENTIAL_ENCRYPTION_KEY_FILE:-/run/secrets/credential_key}" credential_key

export FMCP_BOOTSTRAP_ADMIN_PASSWORD_FILE="$secret_dir/admin_password"
export FMCP_CREDENTIAL_ENCRYPTION_KEY_FILE="$secret_dir/credential_key"
export HOME=/app
export USER=app
export LOGNAME=app

exec setpriv --reuid=app --regid=app --init-groups -- "$@"
