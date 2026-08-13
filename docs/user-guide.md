# Forgejo MCP User Guide

[繁體中文版](user-guide.zh-TW.md)

This guide is for invited users who want to connect an MCP client to Forgejo through Forgejo MCP.

## What you need

Ask your administrator for:

- the Forgejo MCP Dashboard URL;
- a one-time invitation link;
- the Forgejo username registered for you;
- confirmation of which tools you are allowed to use.

You also need access to the matching Forgejo account and permission to create a personal access token (PAT).

## 1. Accept the invitation

1. Open the one-time invitation link before it expires.
2. Confirm the displayed account information.
3. Create a strong local Dashboard password.
4. Sign in to the Dashboard.

The Dashboard password is separate from your Forgejo password. Administrators cannot recover it; use the normal password-change process while signed in.

## 2. Create a scoped Forgejo PAT

Create a new PAT in Forgejo:

1. Sign in to Forgejo.
2. Select your user avatar in the upper-right corner and open **Settings**.
3. Open **Applications** from the settings page.
4. In **Manage Access Tokens**, enter a recognizable token name such as `forgejo-mcp-laptop`.
5. Select only the permissions required by the Forgejo MCP tools you intend to use.
6. Select **Generate Token**.
7. Copy the generated token immediately; it may not be displayed again after you leave the page.

When selecting permissions, grant only the scopes needed for the tools you intend to use:

- read access for repository, branch, commit, Issue and pull-request inspection;
- write access only when you need commits, Issues, reviews, merge, workflow, tag or release operations;
- identity/current-user access so Forgejo MCP can verify the token owner.

Forgejo scope names can vary by supported release and instance policy. Follow your company's Forgejo guidance instead of copying a broad token from a test environment.

Menu labels may vary slightly by Forgejo version or interface language. The Applications page is normally available at `/user/settings/applications`.

Recommended practices:

- set an expiry date where possible;
- never paste it into chat, source code, screenshots or issue comments;
- use a separate PAT for Forgejo MCP rather than reusing another automation token.

## 3. Submit and verify the PAT

1. Open the credential section in the Dashboard.
2. Paste the Forgejo PAT and submit it.
3. Wait for verification to succeed.

Forgejo MCP calls Forgejo's current-user API and requires the returned username to match the username configured by the administrator. The PAT is encrypted before storage and is not shown again.

If verification fails, check:

- that the PAT belongs to the expected Forgejo account;
- that it has not expired or been revoked;
- that it has identity/current-user access;
- that the configured Forgejo instance is reachable.

## 4. Create an MCP token

1. Open the MCP token section.
2. Choose a descriptive name for the client or device.
3. Add an expiry date if appropriate.
4. Create the token.
5. Copy the `fmcp_...` value immediately.
6. Open the token's tool permissions, select only the tools this client needs from your administrator-approved allowance, and save the grants.

The MCP token is shown only once. Store it in the MCP client's secret storage. If it is lost, revoke it and create another token. A new token does not automatically receive every tool in your user allowance; if step 6 is omitted, the client may connect successfully but list no tools.

An MCP token is not a Forgejo PAT: it authenticates to Forgejo MCP, which then applies central permissions before using your encrypted Forgejo credential. The MCP token neither contains nor returns the Forgejo PAT, so it cannot be used to call the Forgejo API directly.

## 5. Connect an MCP client

Configure a client that supports authenticated MCP Streamable HTTP with these values:

```text
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
Authorization: Bearer fmcp_...
```

Use the exact URL supplied by your administrator and configure your own `fmcp_...` token as an `Authorization: Bearer ...` header on the MCP server entry. The MCP client then sends it automatically when connecting and invoking tools; the agent model does not need to read the token. Store it in the client's secret storage, and ensure every user uses a separate token. Query-string tokens are rejected. Because clients use different configuration schemas, follow [MCP client configuration](mcp-client-configuration.md) for a complete example, field mapping, connection checks and troubleshooting.

After connecting, request the tool list. A tool appears only when all of these are true:

1. the administrator enabled it globally;
2. it is allowed for your user;
3. it is granted to this MCP token;
4. your Forgejo PAT remains active and verified.

## 6. Typical workflow

Depending on your grants, an MCP client can:

1. inspect repositories, git trees, branches, commits, labels, milestones and existing Issues;
2. create an Issue;
3. create a branch;
4. commit multiple file changes atomically;
5. create a pull request and inspect its commits, diff and changed files;
6. request reviewers and submit, list or load a specific review;
7. inspect commit status and dispatch a workflow;
8. check whether a pull request has already been merged, or merge it;
9. create a tag and release.

Write tools change the real Forgejo repository. Review the tool name, repository, branch and proposed arguments before approving a client action. `forgejo_get_pull_request_merge_status` reports only whether a pull request has already been merged; use the `mergeable` field from `forgejo_get_pull_request` to check whether it can be merged.

If a write tool times out or the connection is interrupted, do not retry immediately. First use a read tool to check whether the Issue, commit, pull request, merge, tag or release was created, avoiding duplicate side effects.

The complete schema and behavior of all 39 tools are documented in the [v1 tool catalog](tools/v1-tool-catalog.md).

## Token and credential maintenance

Revoke an MCP token when:

- a device is lost;
- a client configuration is exposed;
- the token is no longer needed;
- its behavior looks suspicious in the audit history.

Replace the Forgejo PAT when:

- it expires;
- its scopes need to change;
- Forgejo reports it as revoked;
- either the PAT or the Forgejo MCP credential key may have been exposed.

Revoking one MCP token does not revoke your Forgejo PAT or other MCP tokens. If only an MCP token is known to be exposed, revoke it immediately and review the audit history; the Forgejo PAT normally does not need to be rotated. Until revocation, the exposed MCP token can still invoke the tools granted to it through Forgejo MCP, so the incident must not be ignored. Revoking the Forgejo PAT stops all Forgejo operations that depend on it.

## Troubleshooting

### The server returns 401

The MCP token is missing, malformed, expired, disabled or revoked. Confirm that the client sends `Authorization: Bearer fmcp_...`.

### A tool is not listed

One of the three permission layers does not grant it, or your Forgejo credential is inactive. First check this MCP token's tool grants in the Dashboard. If the tool is unavailable for selection, ask the administrator to review the global setting and your user allowance.

### Forgejo rejects an operation

The PAT may lack the required Forgejo scope, or the Forgejo account may lack repository permission. Forgejo MCP permissions cannot grant access that Forgejo itself denies.

### The server returns 429

The per-token or per-user request limit was reached. Wait for the `Retry-After` period instead of repeatedly reconnecting.

### The service reports Forgejo unavailable

Forgejo may be timing out, rate-limiting requests or temporarily unavailable. Safe reads may be retried automatically; write operations are not automatically retried.
