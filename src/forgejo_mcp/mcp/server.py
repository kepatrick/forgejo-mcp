import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import jsonschema
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from forgejo_mcp.application.errors import ApplicationError, NotFound, ValidationFailed
from forgejo_mcp.application.forgejo_tool_service import ForgejoToolService
from forgejo_mcp.application.runtime import InvocationCoordinator, ServiceShuttingDown
from forgejo_mcp.application.tool_invocation_service import ToolInvocationService
from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.auth.mcp_bearer import (
    ForgejoMcpTokenVerifier,
    token_id_from_access_token,
    user_id_from_access_token,
)
from forgejo_mcp.auth.rate_limit import MultiScopeRateLimiter
from forgejo_mcp.authorization.tools import ToolAuthorizationDecision
from forgejo_mcp.config import Settings
from forgejo_mcp.observability.context import (
    reset_invocation_id,
    reset_user_id,
    set_invocation_id,
    set_user_id,
)
from forgejo_mcp.observability.metrics import (
    MCP_INVOCATION_DURATION,
    MCP_INVOCATIONS,
    RATE_LIMITED,
)
from forgejo_mcp.tools import get_tool, list_tools

SessionFactoryProvider = Callable[[], async_sessionmaker[AsyncSession]]


class McpHttpApplication:
    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        coordinator: InvocationCoordinator,
        limiter: MultiScopeRateLimiter,
        settings: Settings,
    ) -> None:
        self.manager = manager
        self.coordinator = coordinator
        self.limiter = limiter
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.coordinator.accepting:
            await JSONResponse({"detail": "service is shutting down"}, status_code=503)(
                scope, receive, send
            )
            return
        access_token = _access_token()
        decision = self.limiter.check(
            [
                (
                    "token",
                    access_token.client_id,
                    self.settings.mcp_token_rate_limit_requests,
                ),
                (
                    "user",
                    access_token.subject or "unknown",
                    self.settings.mcp_user_rate_limit_requests,
                ),
            ]
        )
        if not decision.allowed:
            RATE_LIMITED.labels(scope=decision.scope or "unknown").inc()
            await JSONResponse(
                {"detail": "MCP rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)


@dataclass(frozen=True)
class McpRuntime:
    server: Server[Any, Any]
    manager: StreamableHTTPSessionManager
    route: Route


def build_mcp_runtime(
    session_factory_provider: SessionFactoryProvider,
    settings: Settings,
    coordinator: InvocationCoordinator,
) -> McpRuntime:
    server: Server[Any, Any] = Server(
        "Forgejo MCP",
        version="0.1.0",
        instructions="Use only the tools granted to this MCP token.",
    )

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_tools() -> list[Tool]:
        access_token = _access_token()
        token_id = token_id_from_access_token(access_token)
        visible: list[Tool] = []
        async with session_factory_provider()() as session:
            permissions = ToolPermissionService(session)
            for spec in list_tools():
                decision = await permissions.decision(token_id=token_id, tool_name=spec.name)
                if decision.allowed:
                    visible.append(
                        Tool(
                            name=spec.name,
                            title=spec.title,
                            description=spec.description,
                            inputSchema=spec.input_schema,
                            outputSchema=spec.output_schema,
                            annotations=ToolAnnotations(
                                readOnlyHint=spec.risk != "write",
                                destructiveHint=False,
                                idempotentHint=spec.risk != "write",
                                openWorldHint=True,
                            ),
                        )
                    )
        return visible

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def handle_call_tool(
        name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | CallToolResult:
        started = time.monotonic()
        outcome = "failed"
        spec = get_tool(name)
        metric_tool = spec.name if spec is not None else "__unknown__"
        access_token = _access_token()
        token_id = token_id_from_access_token(access_token)
        user_id = user_id_from_access_token(access_token)
        user_context = set_user_id(str(user_id))
        try:
            async with coordinator.invocation(), session_factory_provider()() as session:
                permissions = ToolPermissionService(session)
                decision = (
                    await permissions.decision(token_id=token_id, tool_name=name)
                    if spec is not None
                    else ToolAuthorizationDecision(allowed=False, reason="unknown_tool")
                )
                audit = ToolInvocationService(session)
                invocation = await audit.record_decision(
                    token_id=token_id,
                    tool_name=name,
                    spec=spec,
                    arguments=arguments,
                    decision=decision,
                )
                invocation_context = set_invocation_id(str(invocation.id))
                try:
                    if not decision.allowed or spec is None:
                        outcome = "denied"
                        return _tool_error("Tool is not available for this token")
                    try:
                        jsonschema.validate(instance=arguments, schema=spec.input_schema)
                        result = await _execute_tool(
                            ForgejoToolService(session, settings),
                            user_id=user_id,
                            name=name,
                            arguments=arguments,
                            audit_event_id=str(invocation.id),
                        )
                    except jsonschema.ValidationError:
                        failure = ValidationFailed("tool arguments failed schema validation")
                        await audit.complete_failure(invocation, failure)
                        outcome = "invalid"
                        return _tool_error("Tool arguments are invalid")
                    except asyncio.CancelledError as error:
                        outcome = "cancelled"
                        await asyncio.shield(audit.complete_failure(invocation, error))
                        raise
                    except Exception as error:
                        await audit.complete_failure(invocation, error)
                        return _tool_error(_safe_error_message(error))
                    await audit.complete_success(invocation, result)
                    outcome = "succeeded"
                    return result
                finally:
                    reset_invocation_id(invocation_context)
        except ServiceShuttingDown:
            outcome = "shutting_down"
            return _tool_error("Service is shutting down")
        finally:
            reset_user_id(user_context)
            MCP_INVOCATIONS.labels(tool=metric_tool, status=outcome).inc()
            MCP_INVOCATION_DURATION.labels(tool=metric_tool, status=outcome).observe(
                time.monotonic() - started
            )

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=False,
        session_idle_timeout=1800,
    )
    verifier = ForgejoMcpTokenVerifier(session_factory_provider)
    limiter = MultiScopeRateLimiter(settings.mcp_rate_limit_window_seconds)
    route = Route(
        "/mcp",
        endpoint=McpHttpApplication(manager, coordinator, limiter, settings),
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
            Middleware(AuthContextMiddleware),
            Middleware(RequireAuthMiddleware, required_scopes=[]),
        ],
    )
    return McpRuntime(server=server, manager=manager, route=route)


def _access_token() -> AccessToken:
    access_token = get_access_token()
    if access_token is None:
        raise RuntimeError("MCP authentication context is unavailable")
    return access_token


async def _execute_tool(
    tools: ForgejoToolService,
    *,
    user_id: uuid.UUID,
    name: str,
    arguments: dict[str, Any],
    audit_event_id: str,
) -> dict[str, Any]:
    if name == "forgejo_get_current_user":
        principal = await tools.get_current_user(user_id)
        return {"id": principal.id, "username": principal.username}
    if name == "forgejo_list_repositories":
        repository_page = await tools.list_repositories(
            user_id,
            page=cast(int, arguments.get("page", 1)),
            limit=cast(int, arguments.get("limit", 30)),
            order_by=cast(str, arguments.get("order_by", "recentupdate")),
        )
        return _page_result(repository_page)
    if name == "forgejo_get_repository":
        repository = await tools.get_repository(
            user_id,
            owner=cast(str, arguments["owner"]),
            repo=cast(str, arguments["repo"]),
        )
        return repository.model_dump(mode="json")
    if name == "forgejo_list_branches":
        branch_page = await tools.list_branches(
            user_id,
            owner=cast(str, arguments["owner"]),
            repo=cast(str, arguments["repo"]),
            page=cast(int, arguments.get("page", 1)),
            limit=cast(int, arguments.get("limit", 30)),
        )
        return _page_result(branch_page)
    if name == "forgejo_list_commits":
        commit_page = await tools.list_commits(
            user_id,
            owner=cast(str, arguments["owner"]),
            repo=cast(str, arguments["repo"]),
            ref=cast(str | None, arguments.get("ref")),
            path=cast(str | None, arguments.get("path")),
            page=cast(int, arguments.get("page", 1)),
            limit=cast(int, arguments.get("limit", 30)),
        )
        return _page_result(commit_page)
    if name == "forgejo_get_commit":
        commit = await tools.get_commit(
            user_id,
            owner=cast(str, arguments["owner"]),
            repo=cast(str, arguments["repo"]),
            sha=cast(str, arguments["sha"]),
        )
        return commit.model_dump(mode="json")
    if name == "forgejo_compare_refs":
        comparison = await tools.compare_refs(
            user_id,
            owner=cast(str, arguments["owner"]),
            repo=cast(str, arguments["repo"]),
            base=cast(str, arguments["base"]),
            head=cast(str, arguments["head"]),
        )
        return comparison.model_dump(mode="json")
    common = {"owner": cast(str, arguments["owner"]), "repo": cast(str, arguments["repo"])}
    if name == "forgejo_get_git_tree":
        tree = await tools.get_git_tree(
            user_id,
            **common,
            sha=cast(str, arguments["sha"]),
            recursive=cast(bool, arguments.get("recursive", False)),
            page=cast(int, arguments.get("page", 1)),
            limit=cast(int, arguments.get("limit", 30)),
        )
        return tree.model_dump(mode="json")
    if name == "forgejo_list_labels":
        return _page_result(
            await tools.list_labels(
                user_id,
                **common,
                sort=cast(str | None, arguments.get("sort")),
                page=cast(int, arguments.get("page", 1)),
                limit=cast(int, arguments.get("limit", 30)),
            )
        )
    if name == "forgejo_list_milestones":
        return _page_result(
            await tools.list_milestones(
                user_id,
                **common,
                state=cast(str, arguments.get("state", "open")),
                name=cast(str | None, arguments.get("name")),
                page=cast(int, arguments.get("page", 1)),
                limit=cast(int, arguments.get("limit", 30)),
            )
        )
    if name == "forgejo_list_issues":
        return _page_result(
            await tools.list_issues(
                user_id,
                **common,
                state=cast(str, arguments.get("state", "open")),
                labels=cast(list[str] | None, arguments.get("labels")),
                milestones=cast(list[str] | None, arguments.get("milestones")),
                query=cast(str | None, arguments.get("query")),
                since=cast(str | None, arguments.get("since")),
                before=cast(str | None, arguments.get("before")),
                sort=cast(str, arguments.get("sort", "latest")),
                page=cast(int, arguments.get("page", 1)),
                limit=cast(int, arguments.get("limit", 30)),
            )
        )
    if name == "forgejo_get_issue":
        return (
            await tools.get_issue(user_id, **common, number=cast(int, arguments["number"]))
        ).model_dump(mode="json")
    if name == "forgejo_list_issue_comments":
        comments_result = await tools.list_issue_comments(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            since=cast(str | None, arguments.get("since")),
            before=cast(str | None, arguments.get("before")),
        )
        return {
            "items": [item.model_dump(mode="json") for item in comments_result.items],
            "truncated": comments_result.truncated,
        }
    if name == "forgejo_list_pull_requests":
        return _page_result(
            await tools.list_pull_requests(
                user_id,
                **common,
                state=cast(str, arguments.get("state", "open")),
                base=cast(str | None, arguments.get("base")),
                head=cast(str | None, arguments.get("head")),
                label_ids=cast(list[int] | None, arguments.get("label_ids")),
                milestone_id=cast(int | None, arguments.get("milestone_id")),
                sort=cast(str, arguments.get("sort", "recentupdate")),
                page=cast(int, arguments.get("page", 1)),
                limit=cast(int, arguments.get("limit", 30)),
            )
        )
    if name == "forgejo_get_pull_request":
        return (
            await tools.get_pull_request(user_id, **common, number=cast(int, arguments["number"]))
        ).model_dump(mode="json")
    if name == "forgejo_list_pull_request_commits":
        return _page_result(
            await tools.list_pull_request_commits(
                user_id,
                **common,
                number=cast(int, arguments["number"]),
                page=cast(int, arguments.get("page", 1)),
                limit=cast(int, arguments.get("limit", 30)),
            )
        )
    if name == "forgejo_get_pull_request_diff":
        diff_result = await tools.get_pull_request_diff(
            user_id, **common, number=cast(int, arguments["number"])
        )
        return {
            "number": diff_result.number,
            "format": diff_result.format,
            "size": diff_result.size,
            "sha256": diff_result.sha256,
            "content": diff_result.content,
        }
    if name == "forgejo_get_file_content":
        return (
            await tools.get_file_content(
                user_id,
                **common,
                path=cast(str, arguments["path"]),
                ref=cast(str | None, arguments.get("ref")),
            )
        ).model_dump(mode="json")
    if name == "forgejo_list_repository_contents":
        contents = await tools.list_repository_contents(
            user_id,
            **common,
            path=cast(str | None, arguments.get("path")),
            ref=cast(str | None, arguments.get("ref")),
        )
        return {"items": contents.items, "truncated": contents.truncated}
    if name == "forgejo_create_branch":
        branch = await tools.create_branch(
            user_id,
            **common,
            branch=cast(str, arguments["branch"]),
            from_ref=cast(str | None, arguments.get("from_ref")),
        )
        return {"branch": branch.model_dump(mode="json"), "audit_event_id": audit_event_id}
    if name == "forgejo_commit_changes":
        result = await tools.commit_changes(
            user_id,
            **common,
            branch=cast(str | None, arguments.get("branch")),
            new_branch=cast(str | None, arguments.get("new_branch")),
            message=cast(str, arguments["message"]),
            changes=cast(list[dict[str, Any]], arguments["changes"]),
            signoff=cast(bool, arguments.get("signoff", False)),
        )
        return {**result, "audit_event_id": audit_event_id}
    if name == "forgejo_get_pull_request_files":
        files = await tools.list_pull_request_files(
            user_id, **common, number=cast(int, arguments["number"])
        )
        return {"items": files.items, "truncated": files.truncated}
    if name in {"forgejo_request_pull_request_reviewers", "forgejo_remove_pull_request_reviewers"}:
        reviewers = await tools.change_pull_request_reviewers(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            reviewers=cast(list[str] | None, arguments.get("reviewers")),
            team_reviewers=cast(list[str] | None, arguments.get("team_reviewers")),
            remove=name == "forgejo_remove_pull_request_reviewers",
        )
        return {**reviewers, "audit_event_id": audit_event_id}
    if name == "forgejo_list_pull_request_reviews":
        reviews = await tools.list_pull_request_reviews(
            user_id, **common, number=cast(int, arguments["number"])
        )
        return {"items": reviews.items, "truncated": reviews.truncated}
    if name == "forgejo_get_pull_request_review":
        return await tools.get_pull_request_review(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            review_id=cast(int, arguments["review_id"]),
        )
    if name == "forgejo_submit_pull_request_review":
        review = await tools.submit_pull_request_review(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            event=cast(str, arguments["event"]),
            body=cast(str | None, arguments.get("body")),
            commit_id=cast(str | None, arguments.get("commit_id")),
            comments=cast(list[dict[str, Any]] | None, arguments.get("comments")),
        )
        return {"review": review, "audit_event_id": audit_event_id}
    if name == "forgejo_merge_pull_request":
        await tools.merge_pull_request(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            method=cast(str, arguments["method"]),
            title=cast(str | None, arguments.get("title")),
            message=cast(str | None, arguments.get("message")),
            head_sha=cast(str | None, arguments.get("head_sha")),
            delete_branch=cast(bool, arguments.get("delete_branch", False)),
        )
        return {"merged": True, "audit_event_id": audit_event_id}
    if name == "forgejo_get_pull_request_merge_status":
        number = cast(int, arguments["number"])
        merged = await tools.get_pull_request_merge_status(user_id, **common, number=number)
        return {"number": number, "merged": merged}
    if name == "forgejo_get_commit_status":
        return await tools.get_commit_status(user_id, **common, ref=cast(str, arguments["ref"]))
    if name == "forgejo_dispatch_workflow":
        await tools.dispatch_workflow(
            user_id,
            **common,
            workflow=cast(str, arguments["workflow"]),
            ref=cast(str, arguments["ref"]),
            inputs=cast(dict[str, str] | None, arguments.get("inputs")),
        )
        return {"dispatched": True, "audit_event_id": audit_event_id}
    if name == "forgejo_create_tag":
        tag = await tools.create_tag(
            user_id,
            **common,
            tag=cast(str, arguments["tag"]),
            target=cast(str | None, arguments.get("target")),
            message=cast(str | None, arguments.get("message")),
        )
        return {"tag": tag, "audit_event_id": audit_event_id}
    if name == "forgejo_create_release":
        release = await tools.create_release(
            user_id,
            **common,
            tag=cast(str, arguments["tag"]),
            target=cast(str | None, arguments.get("target")),
            name=cast(str | None, arguments.get("name")),
            body=cast(str | None, arguments.get("body")),
            draft=cast(bool, arguments.get("draft", False)),
            prerelease=cast(bool, arguments.get("prerelease", False)),
        )
        return {"release": release, "audit_event_id": audit_event_id}
    if name == "forgejo_create_issue":
        issue_result = await tools.create_issue(
            user_id,
            **common,
            title=cast(str, arguments["title"]),
            body=cast(str | None, arguments.get("body")),
            assignees=cast(list[str] | None, arguments.get("assignees")),
            label_ids=cast(list[int] | None, arguments.get("label_ids")),
            milestone_id=cast(int | None, arguments.get("milestone_id")),
        )
        return {"issue": issue_result.model_dump(mode="json"), "audit_event_id": audit_event_id}
    if name == "forgejo_update_issue":
        changes = {
            key: value for key, value in arguments.items() if key not in {"owner", "repo", "number"}
        }
        updated_issue = await tools.update_issue(
            user_id, **common, number=cast(int, arguments["number"]), changes=changes
        )
        return {"issue": updated_issue.model_dump(mode="json"), "audit_event_id": audit_event_id}
    if name == "forgejo_comment_issue":
        comment_result = await tools.comment_issue(
            user_id,
            **common,
            number=cast(int, arguments["number"]),
            body=cast(str, arguments["body"]),
        )
        return {
            "comment": comment_result.model_dump(mode="json"),
            "audit_event_id": audit_event_id,
        }
    if name == "forgejo_create_pull_request":
        pull_result = await tools.create_pull_request(
            user_id,
            **common,
            title=cast(str, arguments["title"]),
            head=cast(str, arguments["head"]),
            base=cast(str, arguments["base"]),
            body=cast(str | None, arguments.get("body")),
            draft=cast(bool | None, arguments.get("draft")),
        )
        return {
            "pull_request": pull_result.model_dump(mode="json"),
            "audit_event_id": audit_event_id,
        }
    if name == "forgejo_update_pull_request":
        changes = {
            key: value for key, value in arguments.items() if key not in {"owner", "repo", "number"}
        }
        updated_pull = await tools.update_pull_request(
            user_id, **common, number=cast(int, arguments["number"]), changes=changes
        )
        return {
            "pull_request": updated_pull.model_dump(mode="json"),
            "audit_event_id": audit_event_id,
        }
    raise NotFound("tool handler is not implemented")


def _safe_error_message(error: Exception) -> str:
    if isinstance(error, ValidationFailed):
        return "Forgejo request failed validation"
    if isinstance(error, NotFound):
        return "Forgejo resource was not found"
    if isinstance(error, ApplicationError):
        return "Forgejo tool request failed"
    return "Internal tool execution error"


def _page_result(result: Any) -> dict[str, Any]:
    return {
        "items": [item.model_dump(mode="json") for item in result.items],
        "page": result.page,
        "limit": result.limit,
        "has_more": result.has_more,
    }


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )
