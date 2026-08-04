#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

from forgejo_mcp.tools import list_tools


def load_json(source: str) -> tuple[dict[str, Any], bytes]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:  # noqa: S310
            raw = response.read()
    else:
        raw = Path(source).read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI document must be an object")
    return payload, raw


def verify(source: str, contract_path: Path) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    spec, raw = load_json(source)
    actual_version = spec.get("info", {}).get("version")
    expected_version = contract["forgejo_version"]
    if actual_version != expected_version:
        raise ValueError(
            f"Forgejo version mismatch: expected {expected_version}, got {actual_version}"
        )

    actual_hash = hashlib.sha256(raw).hexdigest()
    expected_hash = contract["swagger_sha256"]
    if actual_hash != expected_hash:
        raise ValueError(
            f"Forgejo OpenAPI checksum mismatch: expected {expected_hash}, got {actual_hash}"
        )

    contract_tools = contract["tools"]
    registry_names = {tool.name for tool in list_tools()}
    if set(contract_tools) != registry_names:
        missing = sorted(registry_names - set(contract_tools))
        stale = sorted(set(contract_tools) - registry_names)
        raise ValueError(f"OpenAPI tool contract mismatch: missing={missing}, stale={stale}")

    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI document has no paths object")
    failures: list[str] = []
    for tool_name, operation in contract_tools.items():
        path = operation["path"]
        method = operation["method"]
        path_item = paths.get(path)
        actual = path_item.get(method) if isinstance(path_item, dict) else None
        actual_operation_id = actual.get("operationId") if isinstance(actual, dict) else None
        if actual_operation_id != operation["operation_id"]:
            failures.append(
                f"{tool_name}: expected {method.upper()} {path} "
                f"({operation['operation_id']}), got {actual_operation_id!r}"
            )
    if failures:
        raise ValueError("Forgejo OpenAPI operations changed:\n- " + "\n- ".join(failures))

    print(
        f"Verified {len(contract_tools)} tools against Forgejo {actual_version} "
        f"OpenAPI ({actual_hash})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the locked Forgejo OpenAPI contract")
    parser.add_argument("source", help="URL or local path to swagger.v1.json")
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("tests/contracts/forgejo-v16-openapi.json"),
    )
    arguments = parser.parse_args()
    try:
        verify(arguments.source, arguments.contract)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"OpenAPI verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
