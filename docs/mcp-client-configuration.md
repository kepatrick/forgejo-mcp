# MCP client configuration

[繁體中文版](mcp-client-configuration.zh-TW.md)

This guide describes the connection values required by Forgejo MCP. MCP clients use different configuration schemas, so map these values to the equivalent fields in your client rather than assuming that one JSON shape works everywhere.

> v0.1.0 supports authenticated MCP Streamable HTTP. Client-specific examples should be added only after they have been tested with the named client and version.

## Before you connect

You need:

- the Forgejo MCP base URL from your administrator;
- an active, verified Forgejo credential in the Dashboard;
- either an OAuth-capable MCP client or an unexpired static MCP token beginning with `fmcp_`;
- at least one tool granted globally, to your user and to that token;
- an MCP client that supports Streamable HTTP and custom authorization headers.

See the [user guide](user-guide.md) to create and maintain the credential and token.

## OAuth 2.1 connection (preferred when supported)

Configure only the MCP resource URL in a client that supports OAuth authorization-code discovery:

```text
https://forgejo-mcp.example/mcp
```

The server advertises RFC 9728 protected-resource metadata and authorization-server metadata. The client dynamically registers as a public client or supplies an allowlisted Client ID Metadata Document, creates a PKCE S256 challenge, opens the Forgejo MCP login/consent page, and exchanges the one-time code for a short-lived access token and rotating refresh token. CIMD support is advertised only when the deployment has configured at least one exact CIMD origin; DCR remains available when that allowlist is empty.

The user signs in with the **local Forgejo MCP Dashboard account** linked to their Forgejo identity. Do not enter the Forgejo PAT in the OAuth page or in the MCP client. The PAT remains encrypted server-side and OAuth cannot add tools: each access token receives only the intersection of globally enabled tools and the user's existing allowance.

Do not construct or paste an `/authorize` URL manually. Values such as `client_id`, `redirect_uri`, `code_challenge`, `state` and `resource` are generated and validated by the MCP client. A placeholder or stale authorization URL normally produces `Not Found`, `invalid_request` or `invalid_grant`.

OAuth access tokens use the same `fmcp_...` opaque format internally, expire automatically, are never placed in query strings, and are not displayed in the Dashboard. Refresh tokens rotate on every use; reuse of an older refresh token revokes the complete authorization family.

Client-specific OAuth behavior changes independently of this server. Generic DCR and allowlisted CIMD are covered by automated tests, including an Anthropic-shaped metadata document, but a named client should be considered production-approved only after its current release has completed a live connection test.

## Static Bearer token connection

For clients without OAuth support, each user adds the show-once `fmcp_...` token created in the Dashboard to their own MCP client or agent configuration. Put it in the `Authorization` header of the Forgejo MCP server entry:

```json
{
  "mcpServers": {
    "forgejo": {
      "url": "https://forgejo-mcp.example/mcp",
      "headers": {
        "Authorization": "Bearer fmcp_replace_with_your_token"
      }
    }
  }
}
```

This is a generic structure; clients may use different property names for the server, transport or HTTP type. The essential values are the `/mcp` URL and this header:

```http
Authorization: Bearer fmcp_...
```

The MCP client automatically sends the header when connecting, listing tools and invoking tools against the shared Forgejo MCP server. The agent model does not need to know or read the token; it sees only the tools made available for that token's identity and permissions. Every user must configure their own token and must not share one token between users.

## Required connection values

```text
Server name:   forgejo-mcp
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
HTTP header:   Authorization: Bearer fmcp_...
```

Replace the example hostname and token with the values provided by your deployment. The endpoint path is `/mcp`, not the Dashboard root or a Forgejo API path.

Conceptually, the client configuration must express:

```yaml
name: forgejo-mcp
transport: streamable-http
url: https://forgejo-mcp.example/mcp
headers:
  Authorization: Bearer fmcp_...
```

This YAML is a field map, not a file that can be copied into every client. Follow your client's documentation for its exact property names and secret-storage mechanism.

## Token handling

- Store the token in the client's secret or credential storage when available.
- Do not put it in source control, screenshots, chat, issue comments or a query string.
- Prefer environment-variable or secret references over plaintext configuration if the client supports them.
- Use a separate MCP token for each client or device so one client can be revoked independently.
- If the token is lost, revoke it in the Dashboard and create another one; it cannot be displayed again.

Forgejo MCP rejects query-string authentication. The token must be sent as a Bearer token in the `Authorization` request header.

Requests carrying an HTTP `Origin` header are rejected unless that exact normalized origin is present in the deployment's `FMCP_MCP_ALLOWED_ORIGINS` JSON list. Native MCP clients normally omit this header. Configure the allowlist only for an intentional browser-based client; wildcard origins are not supported.

## Confirm the connection

After saving the configuration:

1. restart or reload the MCP client if required;
2. connect to the Forgejo MCP server;
3. ask the client to list the available tools;
4. confirm that the expected `forgejo_...` tools appear;
5. start with a read-only operation such as inspecting the current user or listing an authorized repository.

A successful Dashboard login does not verify MCP connectivity. Dashboard sessions and MCP Bearer tokens are separate authentication mechanisms.

## Why a tool may not appear

A tool is listed only when every layer permits it:

```text
globally enabled
    + allowed for the user
    + granted to this MCP token
    + active verified Forgejo PAT
    = visible to the client
```

Forgejo repository permissions and PAT scopes are also enforced when the tool runs. Forgejo MCP cannot grant access that Forgejo denies.

## Troubleshooting

### The client does not support Streamable HTTP

Use a client or compatible integration that supports MCP Streamable HTTP with custom HTTP headers. The v0.1.0 server does not document a stdio endpoint.

### The client connects to the Dashboard instead of MCP

Ensure the URL ends with `/mcp`. The Dashboard root, `/api` routes and Forgejo's own URL are not MCP endpoints.

### The server returns 401

Check that:

- the header name is `Authorization`;
- the value starts with `Bearer ` followed by the complete `fmcp_...` token;
- the token is not expired, disabled or revoked;
- the client did not place the token in the URL query string.

For OAuth, also confirm that OAuth is enabled and the access token has not expired or been replaced by refresh rotation. If the client sends an RFC 8707 `resource` parameter, it must be the exact advertised `/mcp` URL.

### OAuth returns `invalid_request`

Confirm that the client uses PKCE S256, its exact registered redirect URI and the single `mcp:tools` scope. An explicit RFC 8707 `resource` value must be the exact advertised `/mcp` URL; omission is supported because this authorization server exposes one fixed MCP resource and binds every issued token to it.

### OAuth opens the login page but rejects the form

The browser request must originate from the exact configured issuer origin. Restart the flow rather than reusing an old consent URL. Sign in with the local user account, not the administrator account and not the Forgejo account password.

### The connection succeeds but no tools are listed

Confirm in the Dashboard that the Forgejo credential is active and verified. Ask an administrator to review the global tool setting, user allowance and token grant.

### A tool is listed but Forgejo rejects the operation

The Forgejo PAT may lack the required scope, or the Forgejo account may lack access to the target repository. Update the Forgejo permissions or replace the PAT with an appropriately scoped one.

### The server returns 429

Wait for the `Retry-After` period. Repeated reconnects can continue consuming the per-token or per-user request allowance.

### The client disconnects after an App restart

Active MCP transport sessions are process-local in v0.1.0. Reconnect the client after the App restarts.

## Security reminder

The MCP token authenticates the client to Forgejo MCP. It is not the user's Forgejo PAT. Forgejo MCP applies its authorization rules and then uses the user's encrypted PAT for allowed Forgejo operations.

An MCP token neither contains nor reveals the Forgejo PAT and cannot be used to access the Forgejo API directly. If only an MCP token is exposed, revoke that token immediately in the Dashboard and review the audit history; the Forgejo PAT normally does not need to be rotated. Until revocation, however, the exposed MCP token can still invoke its granted tools through Forgejo MCP.

Review the [credential security notes](security/credentials.md) and [known limitations](known-limitations.md) before deployment.
