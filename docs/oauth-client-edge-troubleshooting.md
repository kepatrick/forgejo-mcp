# OAuth client and reverse-proxy troubleshooting

OAuth connection failures must be diagnosed at the protocol stage where they occur. A successful browser login proves neither Dynamic Client Registration (DCR) nor token exchange, and one working client does not prove that a second client follows the same path.

## Identify the failing stage

| Client symptom | Expected request | What to verify |
| --- | --- | --- |
| The client cannot discover sign-in | `GET /.well-known/oauth-protected-resource/mcp` and `GET /.well-known/oauth-authorization-server` | Public URL, issuer/resource values and proxy routing |
| `Dynamic client registration failed` or registration returns 403 | `POST /register` | Edge security event and App request log |
| The login or consent page does not open | `GET /authorize`, then `GET /oauth/consent` | Redirect URI, PKCE parameters, issuer routing and browser cookies |
| Login/consent form returns 403 | `POST /oauth/login` or `POST /oauth/consent` | Exact issuer `Origin`, CSRF cookie/form value and stale-flow reuse |
| Authorization succeeds in the browser but the client reports token exchange failure | `POST /token` | Edge action, App status, exact redirect URI, PKCE verifier and RFC 8707 resource |
| A previously working connection later returns 401 | `POST /token` using `refresh_token`, or `/mcp` with the access token | Absolute consent expiry, family revocation and refresh/replay audit events |

Correlate the proxy event time and route with the structured App log. If the edge reports a 403 but the App has no matching request, the request was blocked before Forgejo MCP. Do not weaken application OAuth validation to compensate for an edge rejection.

## Claude and OpenAI clients can exercise different paths

A client registration is durable. A previously connected Claude integration may reuse its existing `client_id` and proceed directly to authorization while a new OpenAI or Codex connection still needs `POST /register`. Claude working at that moment therefore does not establish that DCR is reachable.

In one production diagnosis, OAuth discovery was reachable and the browser authorization completed, but a new OpenAI/Codex connection received a 403 on DCR. The edge classified the server-to-server request as automated traffic; the observed HTTP implementation identified itself as Python `aiohttp`, and its egress came from shared cloud infrastructure. Disabling the applicable Cloudflare bot feature allowed DCR and the complete Codex authorization flow to finish. These observations are diagnostic evidence from that deployment, not stable client identifiers or IP ranges.

Named clients, user agents and egress networks can change without notice. Do not authorize OAuth by matching `User-Agent`, cloud-provider ASN or a copied client IP. Test every intended client's current release after proxy or client upgrades.

## Cloudflare controls

Cloudflare products and plan capabilities change. Verify the current zone and plan behavior before applying a rule. In particular, a custom WAF `Skip` or host allow rule may not bypass the separate legacy **Bot Fight Mode** control. On plans where the bot control cannot be skipped for one hostname or route, the practical choices are to:

1. disable that global bot control for the zone and add narrower compensating controls;
2. move the MCP service to a zone or plan that supports a scoped bot exception; or
3. use a reviewed static Bearer-token client configuration instead of OAuth DCR.

Do not expose an unrestricted registration service merely to make one client connect. Keep these compensating controls:

- TLS and the exact public issuer/resource pair;
- application DCR rate limits and request-size limits;
- public clients only, PKCE S256 and exact redirect URIs;
- exact Same-Origin and CSRF validation for browser login/consent;
- the MCP browser-origin allowlist, without wildcards;
- edge rate limits for `POST /register`, `/token`, `/oauth/login` and `/oauth/consent`;
- application and edge log correlation, without recording codes, tokens, cookies or passwords.

Challenges or JavaScript interstitials are not suitable for OAuth metadata, DCR or token endpoints because machine clients cannot complete them reliably. Prefer rate limiting and protocol validation on these routes. Keep interactive challenges, if required, outside the machine-to-machine endpoints and verify the complete client flow afterward.

## Safe checks

The following read-only requests contain no credential:

```bash
curl --fail-with-body https://forgejo-mcp.example/.well-known/oauth-protected-resource/mcp
curl --fail-with-body https://forgejo-mcp.example/.well-known/oauth-authorization-server
```

Do not paste a live `client_id`, authorization URL, callback URL, code, token, cookie, edge request identifier or private address into a public issue. Record only the failing stage, redacted route, status, timestamp and whether the request reached the App.
