import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from forgejo_mcp.observability.context import invocation_id, request_id, user_id

_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "database_url",
    "password",
    "secret",
    "token",
)
_MCP_TOKEN_PATTERN = re.compile(r"fmcp_[A-Za-z0-9_-]{43}")
_AUTHORIZATION_PATTERN = re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)(://)[^/@\s:]+:[^/@\s]+@")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_text(record.getMessage()),
            "request_id": request_id(),
            "user_id": user_id(),
            "invocation_id": invocation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and key not in {"message", "asctime"}:
                payload[key] = _redact_value(value, key=key)
        if record.exc_info is not None:
            payload["exception"] = _redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, separators=(",", ":"))


class RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _redact_text(super().format(record))


def configure_logging(level: str, log_format: str = "json") -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            RedactingTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def _redact_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    redacted = _MCP_TOKEN_PATTERN.sub("fmcp_[REDACTED]", value)
    redacted = _AUTHORIZATION_PATTERN.sub(lambda match: f"{match.group(1)} [REDACTED]", redacted)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", redacted)


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)
