# Organization Repository Creation — Security Review

## Scope

`forgejo_create_organization_repository` creates one repository in an existing Forgejo organization through `POST /api/v1/orgs/{organization}/repos`. It cannot create organizations, alter membership or permissions, update/delete repositories, or select another Forgejo base URL.

## Threats and controls

- **Unauthorized creation:** the normal MCP token, global/user tool grants, default-disabled tool permission, and stored Forgejo PAT checks all apply. Forgejo remains the authority for organization membership and repository-creation permission.
- **Unexpected public exposure:** `private` is explicit in the audited arguments. It defaults to Forgejo-compatible `false`; operators who require private repositories should disable the tool or grant it only to trusted users.
- **Path injection / SSRF:** `organization` is validated as one bounded path segment and URL-encoded. The base URL comes only from administrator configuration.
- **Abusive or oversized input:** repository name, description and default branch are bounded; control characters and slash-based repository-name ambiguity are rejected. Response size uses the existing bounded JSON guard.
- **Duplicate/replayed writes:** POST requests are not retried. Forgejo conflict/error mapping is returned through the standard sanitized application errors.
- **Audit failure:** this is a `write` tool and therefore uses the existing fail-closed invocation audit pipeline. The audit target includes the organization; arguments include the requested name and visibility but never the PAT.

## Residual risk

A permitted user can consume organization namespace/storage and can create a public repository when `private=false`. Forgejo-side quotas, naming policy, membership, and PAT scope remain deployment responsibilities. Administrators should keep this tool disabled unless repository provisioning is intended.
