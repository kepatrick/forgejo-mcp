# MCP client configuration

[繁體中文版](mcp-client-configuration.zh-TW.md)

This guide describes the connection values required by Forgejo MCP. MCP clients use different configuration schemas, so map these values to the equivalent fields in your client rather than assuming that one JSON shape works everywhere.

> v0.1.0 supports authenticated MCP Streamable HTTP. Client-specific examples should be added only after they have been tested with the named client and version.

## Before you connect

You need:

- the Forgejo MCP base URL from your administrator;
- an active, verified Forgejo credential in the Dashboard;
- an unexpired MCP token beginning with `fmcp_`;
- at least one tool granted globally, to your user and to that token;
- an MCP client that supports Streamable HTTP and custom authorization headers.

See the [user guide](user-guide.md) to create and maintain the credential and token.

## Where to configure the token

Each user must add the `fmcp_...` token created in the Dashboard to their own MCP client or agent configuration. Put it in the `Authorization` header of the Forgejo MCP server entry:

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
