# Forgejo credential security

Each regular Dashboard User supplies their own scoped Forgejo personal access token (PAT). The Admin can see whether a credential is configured and can revoke it, but cannot submit, retrieve, or decrypt PAT plaintext through the API.

## Verification

Before persistence, the application calls the configured Forgejo instance's `/api/v1/user` endpoint. The returned username must match the normalized Forgejo username assigned by Admin. Rotation must also preserve the immutable Forgejo user ID; otherwise the old credential must be revoked first.

## Encryption

PATs are encrypted with AES-256-GCM using a 32-byte, base64-encoded master key supplied through `FMCP_CREDENTIAL_ENCRYPTION_KEY_FILE`. Associated authenticated data binds each ciphertext to the internal User UUID and key version. Each encryption uses a new 96-bit nonce.

Database rows contain ciphertext, nonce, and key version. Revocation and rotation cryptographically erase old credentials by setting ciphertext and nonce to null. The master key must be backed up separately from PostgreSQL; losing it makes active credentials unrecoverable.

Generate a key with:

```bash
openssl rand -base64 32 > credential_key
chmod 600 credential_key
```

Never commit this file. Incrementing the configured key version without a migration/rotation procedure makes existing credentials unavailable; multi-key online rotation is a future milestone.

## MCP token separation and compromise response

An MCP token and a Forgejo PAT are separate credentials. The MCP token identifies a client to Forgejo MCP and carries only the centrally granted MCP capabilities; it does not contain, return, or expose the encrypted Forgejo PAT and cannot authenticate directly to the Forgejo API.

If only an MCP token is exposed, revoke that token immediately and review its invocation audit history. The user's Forgejo PAT and other MCP tokens normally do not need to be rotated. Until revocation, the exposed token can still invoke every tool granted to it through Forgejo MCP. Rotate the Forgejo PAT as well if the PAT, database and encryption key, or another system containing the PAT may also have been exposed.

## Logging and audit

PATs and Authorization headers must never be written to application logs, audit records, API responses, browser storage, or exception details. Audit records contain only principal IDs/usernames, lifecycle action, result category, and actor.
