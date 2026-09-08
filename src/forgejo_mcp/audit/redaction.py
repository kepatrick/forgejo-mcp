import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_SENSITIVE_FRAGMENTS = (
    "authorization",
    "api_key",
    "cookie",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s]+@",
)
_AUTHORITY_CANDIDATE = re.compile(
    r"(?<![^\s(/\"'\[<])(?P<authority>[^/:\s\"'()]+:(?!//)[^\s\"']+@"
    r"(?:\[[0-9A-Fa-f:.]+\]|[^/\s\"'(),;\[\]<>?#]+))"
    r"(?P<terminator>/|$|\s|[\"'),;\[\]<>?#])",
)
_AUTHORITY_HOST = re.compile(
    r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?::[A-Za-z0-9._-]+)?\.?",
)
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TARGET_TEXT_LIMIT = 512
_TARGET_FIELDS = (
    "organization",
    "owner",
    "repo",
    "number",
    "run_id",
    "job_id",
    "attempt",
    "workflow_id",
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

    def redact(value: Any, key: str | None = None, path: tuple[str, ...] = ()) -> Any:
        nonlocal truncated
        if key is not None and _sensitive_key(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(child_key): redact(
                    child_value,
                    str(child_key),
                    (*path, str(child_key)),
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [redact(item, path=path) for item in value]
        if isinstance(value, str):
            if path == ("changes", "content"):
                content_bytes = value.encode("utf-8")
                truncated = True
                return {
                    "redacted": True,
                    "bytes": len(content_bytes),
                    "sha256": hashlib.sha256(content_bytes).hexdigest(),
                }
            sanitized = _redact_text(value)
            if len(sanitized) > text_limit:
                truncated = True
                return f"{sanitized[:text_limit]}…[TRUNCATED]"
            return sanitized
        if value is None or isinstance(value, str | int | float | bool):
            return value
        return "[UNSUPPORTED VALUE]"

    return RedactionResult(value=redact(arguments), truncated=truncated)


def extract_target(arguments: dict[str, Any]) -> dict[str, Any]:
    target: dict[str, Any] = {}
    for field in _TARGET_FIELDS:
        value = arguments.get(field)
        if isinstance(value, str | int) and not isinstance(value, bool):
            target[field] = (
                _bounded_text(_redact_text(value), _TARGET_TEXT_LIMIT)
                if isinstance(value, str)
                else value
            )
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
    normalized = _CAMEL_CASE_BOUNDARY.sub("_", key).casefold().replace("-", "_")
    collapsed = normalized.replace("_", "")
    return any(
        fragment in normalized or fragment.replace("_", "") in collapsed
        for fragment in _SENSITIVE_FRAGMENTS
    )


def _redact_text(value: str) -> str:
    sanitized = _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", value)
    return _AUTHORITY_CANDIDATE.sub(_redact_schemeless_authority, sanitized)


def _redact_schemeless_authority(match: re.Match[str]) -> str:
    authority = match.group("authority")
    userinfo, separator, host = authority.rpartition("@")
    username, colon, password = userinfo.partition(":")
    # Explicit prose contexts are not generic numeric-credential exemptions.
    prefix = match.string[: match.start()].rstrip().casefold()
    if (prefix.endswith("ratio") and username.isdecimal() and password.isdecimal()) or (
        username == "release" and re.fullmatch(r"v[0-9]+(?:\.[0-9]+)*", password)
    ):
        return match.group(0)
    if (
        not separator
        or not colon
        or not username
        or not password
        or "@" in username
        # Keep clock-like prose; do not exempt arbitrary numeric credentials.
        or (re.fullmatch(r"(?:[01]?[0-9]|2[0-3]):[0-5][0-9]", userinfo) is not None)
        or _AUTHORITY_HOST.fullmatch(host) is None
    ):
        return match.group(0)
    return f"[REDACTED]@{host}{match.group('terminator')}"


def _bounded_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…[TRUNCATED]"
