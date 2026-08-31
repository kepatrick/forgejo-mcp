#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


def load_json(source: str) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:  # noqa: S310
            raw = response.read()
    else:
        raw = Path(source).read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI document must be an object")
    return payload


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    differences = _differences(before, after)
    endpoint_changes = [item for item in differences if item["pointer"].startswith("/paths/")]
    schema_changes = [item for item in differences if item["pointer"].startswith("/definitions/")]
    return {
        "source_version": _version(before),
        "target_version": _version(after),
        "summary": {
            "total": len(differences),
            "added": sum(item["kind"] == "added" for item in differences),
            "removed": sum(item["kind"] == "removed" for item in differences),
            "changed": sum(item["kind"] == "changed" for item in differences),
            "endpoint_changes": len(endpoint_changes),
            "schema_changes": len(schema_changes),
            "other_changes": len(differences) - len(endpoint_changes) - len(schema_changes),
        },
        "differences": differences,
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Forgejo OpenAPI comparison",
        "",
        f"- Source: `{result['source_version']}`",
        f"- Target: `{result['target_version']}`",
        f"- Total structural differences: {summary['total']}",
        f"- Endpoint differences: {summary['endpoint_changes']}",
        f"- Schema differences: {summary['schema_changes']}",
        "",
        "| Change | JSON pointer | Before | After |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["differences"]:
        lines.append(
            f"| {item['kind']} | `{item['pointer']}` | "
            f"{_markdown_value(item.get('before'))} | {_markdown_value(item.get('after'))} |"
        )
    if not result["differences"]:
        lines.append("| none | - | - | - |")
    return "\n".join(lines) + "\n"


def _differences(before: Any, after: Any, pointer: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        result: list[dict[str, Any]] = []
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys):
            result.append(
                {"kind": "removed", "pointer": _join(pointer, key), "before": before[key]}
            )
        for key in sorted(after_keys - before_keys):
            result.append({"kind": "added", "pointer": _join(pointer, key), "after": after[key]})
        for key in sorted(before_keys & after_keys):
            result.extend(_differences(before[key], after[key], _join(pointer, key)))
        return result
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [{"kind": "changed", "pointer": pointer or "/", "before": before, "after": after}]
    if before == after:
        return []
    return [{"kind": "changed", "pointer": pointer or "/", "before": before, "after": after}]


def _join(pointer: str, key: str) -> str:
    escaped = key.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _version(document: dict[str, Any]) -> str:
    info = document.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str):
        raise ValueError("OpenAPI document has no info.version string")
    return version


def _markdown_value(value: Any) -> str:
    if value is None:
        return "-"
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"`{rendered.replace('|', '&#124;')}`"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two Forgejo OpenAPI documents")
    parser.add_argument("source", help="Older Swagger URL or local path")
    parser.add_argument("target", help="Newer Swagger URL or local path")
    parser.add_argument("--expect", type=Path, help="Fail unless the complete JSON diff matches")
    parser.add_argument("--output", type=Path, help="Write the report instead of stdout")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument(
        "--fail-on-endpoint-changes",
        action="store_true",
        help="Fail when any JSON pointer below /paths changes",
    )
    arguments = parser.parse_args()
    try:
        result = compare(load_json(arguments.source), load_json(arguments.target))
        if arguments.expect is not None:
            expected = json.loads(arguments.expect.read_text(encoding="utf-8"))
            if result != expected:
                raise ValueError("OpenAPI differences do not match the locked comparison fixture")
        rendered = (
            json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            if arguments.format == "json"
            else render_markdown(result)
        )
        if arguments.output is None:
            print(rendered, end="")
        else:
            arguments.output.write_text(rendered, encoding="utf-8")
        if arguments.fail_on_endpoint_changes and result["summary"]["endpoint_changes"]:
            raise ValueError("Forgejo OpenAPI endpoint changes detected")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"OpenAPI comparison failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
