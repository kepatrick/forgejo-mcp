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

## 2. Configure the Forgejo instance

Enter the company Forgejo base URL in the Dashboard. Forgejo MCP normalizes the URL and verifies `/api/v1/version` before saving it.

For normal deployments:

- use HTTPS;
- do not include credentials, query strings or fragments in the URL;
- ensure the App can reach the Forgejo API;
- keep `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=false`.

HTTP is supported only for the local test profile when explicitly enabled.

v0.1.0 is contract-tested against Forgejo `16.0.2+gitea-1.22.0`. See [Known limitations](known-limitations.md) before connecting another version.

## 3. Configure global tools

Review the 38-tool catalog and enable only the tools the organization intends to expose. Global disable is the top-level kill switch: a disabled tool is unavailable to every user and token.

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

## 7. Review audit records

Tool invocation records include:

- user and MCP token identity;
- Forgejo username;
- tool name, version and risk;
- authorization decision and denial reason;
- redacted arguments and extracted target;
- status, duration and bounded result summary;
- error classification without credential plaintext.

Use the request ID and invocation ID to correlate Dashboard records with structured application logs.

Audit records show Forgejo MCP activity, but they do not replace Forgejo's own audit and repository history.

## 8. Disable or revoke access

Use the narrowest effective response:

- revoke one MCP token when one client or device is affected;
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
