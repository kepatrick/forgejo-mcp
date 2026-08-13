import hashlib
import json
from dataclasses import dataclass
from typing import Any

_SENSITIVE_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
_TARGET_FIELDS = (
    "organization",
    "owner",
    "repo",
    "number",
    "path",
    "ref",
    "sha",
    "base",
    "head",
)


@dataclass(frozen=True)
class RedactionResult:
    value: dict[str, Any]
    truncated: bool


def redact_arguments(arguments: dict[str, Any], *, text_limit: int = 4096) -> RedactionResult:
    truncated = False

    def redact(value: Any, key: str | None = None) -> Any:
        nonlocal truncated
        if key is not None and _sensitive_key(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(child_key): redact(child_value, str(child_key))
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str) and len(value) > text_limit:
            truncated = True
            return f"{value[:text_limit]}…[TRUNCATED]"
        if value is None or isinstance(value, str | int | float | bool):
            return value
        return "[UNSUPPORTED VALUE]"

    return RedactionResult(value=redact(arguments), truncated=truncated)


def extract_target(arguments: dict[str, Any]) -> dict[str, Any]:
    target: dict[str, Any] = {}
    for field in _TARGET_FIELDS:
        value = arguments.get(field)
        if isinstance(value, str | int) and not isinstance(value, bool):
            target[field] = value
    return target


def summarize_result(result: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    summary: dict[str, Any] = {
        "response_bytes": len(encoded),
        "returned_keys": sorted(result),
    }
    items = result.get("items", result.get("entries"))
    if isinstance(items, list):
        summary["item_count"] = len(items)
    for content_field in ("content", "diff"):
        content = result.get(content_field)
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
            summary[f"{content_field}_bytes"] = len(content_bytes)
            summary[f"{content_field}_sha256"] = hashlib.sha256(content_bytes).hexdigest()
    truncated = any(
        value is True and (key.endswith("_truncated") or key == "truncated")
        for key, value in result.items()
    )
    return summary, truncated


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)
