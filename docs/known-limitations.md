# Forgejo MCP Known Limitations

[繁體中文版](known-limitations.zh-TW.md)

Forgejo MCP provides the complete Forgejo development workflow and core security model, while some production-readiness capabilities remain incomplete.

## Compatibility

- The current source supports Forgejo `16.0.3+gitea-1.22.0`; the development default is the official `data.forgejo.org/forgejo/forgejo:16.0.3-rootless` image.
- Forgejo `16.0.2+gitea-1.22.0` is retained only as a comparative CI baseline. See the [version compatibility matrix](compatibility.md) for release-specific support.
- Other Forgejo versions may work, but OpenAPI verification or local testing does not make them supported; support requires an updated matrix and a new MCP release.
- The server supports MCP Streamable HTTP with Bearer authentication. Client-specific configuration examples are not yet validated for every MCP client.

## Deployment

- The current source supports Docker Compose deployment; the React Dashboard is built into the App image, so separate frontend and backend development servers are not part of the operator workflow.
- A production TLS reverse-proxy example is not included.
- `/metrics` must be restricted by deployment networking or a reverse proxy before production exposure.
- PostgreSQL backup/restore scripts, credential-key backup procedures and restore drills are deferred.
- A security hardening upgrade guide is available, but complete backup/restore and incident-response runbooks are deferred.
- The included Compose configuration is a source-based self-hosting reference, not a complete production infrastructure platform. Operators are responsible for TLS termination, network controls and infrastructure operations.

## Scaling and availability

- The App is designed for a single replica.
- MCP and login rate-limit state is held in memory and is not shared across replicas.
- Active MCP transport sessions are process-local and clients must reconnect after an App restart.
- Graceful shutdown drains active tool invocations within a configured timeout, but a forced host or database failure can still interrupt work.

## Audit and management

- Invocation audit listing and detail views are available.
- Audit CSV/JSON export, retention automation and cleanup policies are not implemented.
- Advanced Dashboard filtering and a dedicated operational status page are not implemented.
- Forgejo MCP audit records complement but do not replace Forgejo repository history and Forgejo's own audit facilities.

## Tool scope

- The catalog contains 50 workflow-oriented tools; it is not a one-to-one wrapper for every Forgejo API endpoint.
- Repository creation and migration target an existing user or organization and remain subject to the stored PAT's Forgejo permissions. Pull mirrors can be created, updated and manually synchronized; push-mirror management is not included.
- Organization administration, repository deletion, user administration inside Forgejo, SSH key management, package administration and arbitrary API passthrough are intentionally excluded.
- Workflow dispatch requires Forgejo Actions and an existing workflow file in the target repository.
- Forgejo MCP authorization cannot grant repository access or PAT scopes that Forgejo itself denies.

## Testing

- Unit, integration and frontend quality checks are available.
- The real App/PostgreSQL/Forgejo development-flow E2E runs locally and in pull-request and release CI against supported Forgejo 16.0.3 and the retained 16.0.2 comparison baseline.
- Failure-injection, security penetration testing and backup restore drills are deferred.

## Security boundary

- Users are responsible for creating appropriately scoped Forgejo PATs.
- Administrators can control tool availability but cannot inspect PAT or MCP token plaintext.
- Loss of the credential encryption key makes stored Forgejo PAT ciphertext unusable; key backup guidance is deferred with the disaster-recovery work.
- Possession of both the database and credential encryption key may expose stored PATs, so a future production deployment must protect them separately.

## Planned production-readiness work

The next production-oriented work package covers:

1. TLS reverse proxy and security headers;
2. monitoring-network restrictions for `/metrics`;
3. PostgreSQL and secret backup/restore automation;
4. a real restore drill;
5. complete rollback and incident-response runbooks;
6. failure-injection and security validation.
