from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "forgejo_mcp_http_requests_total",
    "HTTP requests handled by the application.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "forgejo_mcp_http_request_duration_seconds",
    "HTTP request duration.",
    ("method", "route"),
)
HTTP_REQUEST_BODY_REJECTED = Counter(
    "forgejo_mcp_http_request_body_rejected_total",
    "HTTP request bodies rejected by the size guard.",
    ("route",),
)
MCP_INVOCATIONS = Counter(
    "forgejo_mcp_tool_invocations_total",
    "MCP tool invocations by tool and outcome.",
    ("tool", "status"),
)
MCP_INVOCATION_DURATION = Histogram(
    "forgejo_mcp_tool_invocation_duration_seconds",
    "MCP tool invocation duration.",
    ("tool", "status"),
)
MCP_ACTIVE_INVOCATIONS = Gauge(
    "forgejo_mcp_active_tool_invocations",
    "MCP tool invocations currently executing.",
)
RATE_LIMITED = Counter(
    "forgejo_mcp_rate_limited_total",
    "Requests rejected by a rate limit.",
    ("scope",),
)
FORGEJO_REQUESTS = Counter(
    "forgejo_mcp_forgejo_requests_total",
    "Requests sent to Forgejo.",
    ("method", "status"),
)
FORGEJO_DURATION = Histogram(
    "forgejo_mcp_forgejo_request_duration_seconds",
    "Forgejo request duration.",
    ("method",),
)
FORGEJO_RETRIES = Counter(
    "forgejo_mcp_forgejo_retries_total",
    "Safe Forgejo request retries.",
    ("reason",),
)
DB_POOL_CHECKED_OUT = Gauge(
    "forgejo_mcp_db_pool_checked_out_connections",
    "Currently checked-out database connections.",
)
DB_POOL_SIZE = Gauge(
    "forgejo_mcp_db_pool_size",
    "Configured SQLAlchemy database pool size.",
)
