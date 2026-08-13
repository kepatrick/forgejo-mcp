# Forgejo MCP v0.1.0 Known Limitations

[繁體中文版](known-limitations.zh-TW.md)

v0.1.0 is the initial open-source release. It provides the complete Forgejo development workflow and core security model, while some production-readiness capabilities remain incomplete.

## Compatibility

- The API contract is locked to Forgejo `16.0.2+gitea-1.22.0` and the image `codeberg.org/forgejo/forgejo:16.0.2-rootless`.
- Other Forgejo versions may work, but must be checked with `scripts/verify_forgejo_openapi.py` and the local integration suite before use.
- The server supports MCP Streamable HTTP with Bearer authentication. Client-specific configuration examples are not yet validated for every MCP client.

## Deployment

- v0.1.0 supports Docker Compose deployment; the React Dashboard is built into the App image, so separate frontend and backend development servers are not part of the operator workflow.
- A production TLS reverse-proxy example is not included in v0.1.0.
- `/metrics` must be restricted by deployment networking or a reverse proxy before production exposure.
- PostgreSQL backup/restore scripts, credential-key backup procedures and restore drills are deferred.
- Upgrade, rollback and incident-response runbooks are deferred.
- The included Compose configuration is a source-based self-hosting reference, not a complete production infrastructure platform. Operators are responsible for TLS termination, network controls and infrastructure operations.

## Scaling and availability

- The App is designed for a single replica in v0.1.0.
- MCP and login rate-limit state is held in memory and is not shared across replicas.
- Active MCP transport sessions are process-local and clients must reconnect after an App restart.
- Graceful shutdown drains active tool invocations within a configured timeout, but a forced host or database failure can still interrupt work.

## Audit and management

- Invocation audit listing and detail views are available.
- Audit CSV/JSON export, retention automation and cleanup policies are not implemented.
- Advanced Dashboard filtering and a dedicated operational status page are not implemented.
- Forgejo MCP audit records complement but do not replace Forgejo repository history and Forgejo's own audit facilities.

## Tool scope

- The catalog contains 39 workflow-oriented tools; it is not a one-to-one wrapper for every Forgejo API endpoint.
- Repository creation is limited to existing organizations and remains subject to the stored PAT's Forgejo permissions.
- Organization administration, repository deletion, user administration inside Forgejo, SSH key management, package administration and arbitrary API passthrough are intentionally excluded.
- Workflow dispatch requires Forgejo Actions and an existing workflow file in the target repository.
- Forgejo MCP authorization cannot grant repository access or PAT scopes that Forgejo itself denies.

## Testing

- Unit, integration and frontend quality checks are available.
- The real App/PostgreSQL/Forgejo development-flow E2E runs locally with `scripts/test-full-docker-e2e.sh` and is not yet connected to workflow CI.
- Failure-injection, security penetration testing, backup restore drills and multi-version Forgejo compatibility testing are deferred.

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
5. upgrade, rollback and incident-response runbooks;
6. failure-injection and security validation;
7. container publishing and SBOM generation.
