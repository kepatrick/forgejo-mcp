# Forgejo version compatibility

[繁體中文](compatibility.zh-TW.md)

Forgejo MCP and Forgejo have independent version numbers. A Forgejo MCP release supports only the Forgejo versions explicitly listed below. A version used as a CI comparison baseline is not a supported deployment target.

## Compatibility matrix

| Forgejo MCP version | Supported Forgejo version | Comparison baseline | Status |
| --- | --- | --- | --- |
| `v0.1.0` | `16.0.2+gitea-1.22.0` | None | Historical release |
| `v0.2.0` | `16.0.3+gitea-1.22.0` | `16.0.2+gitea-1.22.0` | Current release line |

Until the `v0.2.0` tag is published, its row describes the reviewed release target on `main`. For the v0.2.0 release line, Forgejo 16.0.3 is the minimum and only supported deployment target. Forgejo 16.0.2 remains in CI solely to detect regressions relative to the previous MCP release.

Versions not listed as supported may happen to work, but are not covered by the support policy. A matching Swagger checksum confirms only that the tested API document has not drifted; it does not by itself extend support to another Forgejo or Forgejo MCP release.

## Evidence and release policy

- The detailed 16.0.2-to-16.0.3 API and E2E assessment is in the [Forgejo 16.0.3 compatibility report](forgejo-16.0.3-compatibility.md).
- Pull-request and release CI run the locked OpenAPI comparison and the complete Docker E2E against the supported version and retained baseline.
- Each GitHub Release and changelog section records the compatibility promise for that immutable MCP release.
- Supporting a newer Forgejo version requires reviewed contract evidence, E2E coverage, an updated matrix and a new Forgejo MCP release. Compatibility is never inferred only from a newer patch or minor version number.
