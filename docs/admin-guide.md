# Forgejo MCP Administrator Guide

[繁體中文版](admin-guide.zh-TW.md)

This guide covers the v0.1.0 Dashboard workflow for connecting Forgejo, onboarding users and controlling MCP tools. To install and start the service first, follow [Getting started](getting-started.md).

## Administrative model

Forgejo MCP does not replace Forgejo authorization. It adds a second control layer in front of Forgejo:

```text
MCP token authentication
        +
global tool setting
        +
user tool allowance
        +
token-specific grant
        +
Forgejo account and PAT permission
        =
tool available to the MCP client
```

Administrators manage local access but never receive users' Forgejo PAT plaintext or show-once MCP token plaintext.

## Before you begin

Complete [Getting started](getting-started.md) and confirm that `/health/ready` succeeds before continuing. The React Dashboard is included in the App image; operators do not start separate frontend and backend servers.

## 1. Bootstrap the administrator

The first administrator is created from:

- `FMCP_BOOTSTRAP_ADMIN_USERNAME`;
- the file referenced by `FMCP_BOOTSTRAP_ADMIN_PASSWORD_FILE`.

On first sign-in:

1. retrieve the bootstrap password from the protected secret file;
2. sign in to the Dashboard;
3. change the password immediately;
4. keep the secret file protected and out of source control.

After bootstrap, any authenticated account can change its password from the **Change password** button in the Dashboard header. The new password must contain at least 12 characters. A successful change keeps the current session and revokes every other active session for that account.

## 2. Configure the Forgejo instance

Enter the company Forgejo base URL in the Dashboard. Forgejo MCP normalizes the URL and verifies `/api/v1/version` before saving it. If Forgejo is configured to allow API calls only for signed-in users, the App accepts only Forgejo's exact signed-in-only response and derives the advertised version from the same-origin login page without sending a PAT. Redirects remain disabled and the response is size bounded.

For normal deployments:

- use HTTPS;
- do not include credentials, query strings or fragments in the URL;
- ensure the App can reach the Forgejo API;
- pin the exact URL out of band with `FMCP_FORGEJO_ALLOWED_BASE_URLS`;
- keep `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=false`;
- keep `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=false`.

HTTP is supported only for the local test profile when explicitly enabled.

Production refuses to start without a non-empty `FMCP_FORGEJO_ALLOWED_BASE_URLS` JSON list. In development and test, an empty list also permits no outbound Forgejo connection. The Dashboard can test and save only URLs in the configured list. This prevents a compromised local administrator account from redirecting user PAT verification to an attacker-controlled endpoint.

The reference Compose publishes the App on loopback. Put public deployments behind HTTPS and keep the App on a private Docker network when possible. When a reverse proxy supplies client IPs for login, invitation and OAuth registration limits, configure only its exact networks in `FMCP_TRUSTED_PROXY_CIDRS`. The App ignores `X-Forwarded-For` from every other peer and walks trusted chains from right to left. Do not use `0.0.0.0/0` or enable Uvicorn's unrestricted proxy-header trust.

Repository migration accepts only `http`, `https`, `ssh` and `git` URLs with a host. Local paths, URL credentials, query strings, fragments and private/special hosts are rejected by default. Set `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS=true` only when a trusted private migration source is required, and retain Forgejo's own migration allow/deny policy.

v0.1.0 is contract-tested against Forgejo `16.0.2+gitea-1.22.0` and `16.0.3+gitea-1.22.0`. See [Known limitations](known-limitations.md) before connecting another version.

## 3. Configure global tools

Review the 50-tool catalog and enable only the tools the organization intends to expose. Global disable is the top-level kill switch: a disabled tool is unavailable to every user and token.

Suggested rollout policy:

- enable read tools first;
- enable write tools only for the repositories and users that require them;
- review merge, workflow, tag and release grants explicitly.

Tool risk and schemas are documented in the [v1 tool catalog](tools/v1-tool-catalog.md). Tools added by an upgrade remain globally disabled and are not automatically added to existing user allowances or token grants; review their risk before enabling each permission layer.

## 4. Create and invite a user

1. Create a local user in the Dashboard.
2. Set the expected Forgejo username exactly.
3. Generate the 30-minute, one-time invitation link.
4. Deliver the link through an approved private channel.
5. Ask the user to accept it and create a local password.

The local Dashboard username and expected Forgejo username serve different purposes. The Forgejo username is used to verify PAT ownership and must match Forgejo's current-user response after normalization.

If an invitation expires or is consumed incorrectly, create a new invitation rather than reusing the old URL.

## 5. Set the user allowance

The user allowance defines the maximum tool set that the user may grant to their own MCP tokens.

For least privilege:

- grant only tools required by the user's role;
- separate read-only users from users permitted to write or merge;
- review release and workflow tools separately;
- remove grants when a role or project changes.

## 6. User credential and MCP token setup

The user must:

1. sign in to the Dashboard;
2. submit a scoped Forgejo PAT;
3. pass username verification;
4. create a show-once MCP token;
5. select tools for that token within their allowance.

The administrator can see status and metadata but not PAT or MCP token plaintext.

## 7. Optional OAuth 2.1 authorization

OAuth is disabled by default and static Bearer authentication remains available. OAuth does not alter Forgejo PAT scopes or bypass the global/user permission ceiling.

For a public deployment at `https://forge-mcp.example.com`, set:

```dotenv
FMCP_OAUTH_ENABLED=true
FMCP_OAUTH_ISSUER_URL=https://forge-mcp.example.com
FMCP_OAUTH_RESOURCE_URL=https://forge-mcp.example.com/mcp
FMCP_OAUTH_CIMD_ALLOWED_ORIGINS=[]
```

The issuer must be the public HTTPS origin without a path. The resource must be the same origin followed by exactly `/mcp`. Keep `FMCP_OAUTH_CIMD_ALLOWED_ORIGINS=[]` for DCR-only operation. If a reviewed client uses an HTTPS URL as its client ID, add only that metadata document's exact origin; wildcards, redirects, private addresses and non-HTTPS fetches are rejected.

Before enabling OAuth:

1. back up PostgreSQL and the credential-encryption key separately;
2. confirm the reverse proxy exposes the issuer and `/mcp` under the same HTTPS origin;
3. retain normal CSRF and security-header handling rather than intercepting `/oauth/*`;
4. add an origin to `FMCP_MCP_ALLOWED_ORIGINS` only if the MCP transport itself sends that browser `Origin` header;
5. apply the database migration and verify both metadata endpoints;
6. run a live connection with each intended client before approving it for users.

Useful checks:

```text
GET /.well-known/oauth-authorization-server
GET /.well-known/oauth-protected-resource/mcp
```

Disabling `FMCP_OAUTH_ENABLED` immediately makes OAuth access tokens unusable while leaving historical static Bearer tokens unchanged. A database downgrade deletes OAuth-created MCP access records before removing their linkage, preventing them from becoming static tokens. See [OAuth 2.1 security and operations](security/oauth-2.1.md) for the threat analysis and rollback behavior.

## 8. Review audit records

Tool invocation records include:

- user and MCP token identity;
- Forgejo username;
- tool name, version and risk;
- authorization decision and denial reason;
- redacted arguments and extracted target;
- status, duration and bounded result summary;
- error classification without credential plaintext.

Credentials embedded in remote URLs are removed before persistence. Multi-file commit contents are represented only by byte length and SHA-256 digest; file content is not retained in invocation arguments.

Use the request ID and invocation ID to correlate Dashboard records with structured application logs.

Audit records show Forgejo MCP activity, but they do not replace Forgejo's own audit and repository history.

## 9. Disable or revoke access

Use the narrowest effective response:

- revoke one MCP token when one client or device is affected;
- revoke an OAuth access token to revoke its complete refresh-token family;
- remove a token grant when only one capability should be removed;
- remove a user allowance when the role changes;
- deactivate the Forgejo credential when its PAT is invalid or exposed;
- disable the user for immediate broad suspension.

Disabling a user revokes active local sessions and prevents their MCP tokens from authenticating.

## Operational endpoints

- `/health/live` confirms that the process is running.
- `/health/ready` confirms PostgreSQL availability and MCP acceptance state.
- `/metrics` exposes Prometheus metrics and should be restricted before production use.
- `/api/system/version` reports the application version.

Logs are JSON by default and include request, user and invocation correlation fields. They must not be treated as a secret store.

## v0.1.0 deployment status

v0.1.0 is a self-hosted open-source release whose production deployment capabilities are not yet complete. Operators remain responsible for TLS termination and infrastructure operations; backup/restore automation and production incident runbooks are not included. Review [Known limitations](known-limitations.md) before production use.
