import asyncio
import base64
import binascii
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

import httpx

from forgejo_mcp.application.errors import ExternalServiceUnavailable, NotFound, ValidationFailed
from forgejo_mcp.forgejo.models import (
    BranchSummary,
    CommentSummary,
    CommitDetail,
    CommitSummary,
    CompareSummary,
    FileContent,
    GitTreeSummary,
    IssueSummary,
    PullRequestSummary,
    RepositoryLabelSummary,
    RepositoryMilestoneSummary,
    RepositorySummary,
    parse_branches,
    parse_comment,
    parse_comments,
    parse_commit,
    parse_commits,
    parse_compare,
    parse_git_tree,
    parse_issue,
    parse_issues,
    parse_pull_request,
    parse_pull_requests,
    parse_repositories,
    parse_repository,
    parse_repository_labels,
    parse_repository_milestones,
)
from forgejo_mcp.observability.metrics import (
    FORGEJO_DURATION,
    FORGEJO_REQUESTS,
    FORGEJO_RETRIES,
)

MAX_VERSION_RESPONSE_BYTES = 64 * 1024
MAX_USER_RESPONSE_BYTES = 256 * 1024
MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FILE_CONTENT_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ForgejoVersion:
    version: str


@dataclass(frozen=True)
class ForgejoUser:
    id: int
    username: str


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    page: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class BoundedList[T]:
    items: list[T]
    truncated: bool


@dataclass(frozen=True)
class DiffContent:
    number: int
    format: str
    size: int
    sha256: str
    content: str


def normalize_base_url(value: str) -> str:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError as error:
        raise ValidationFailed("invalid Forgejo base URL") from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValidationFailed("Forgejo base URL must use http or https")
    if parsed.username or parsed.password:
        raise ValidationFailed("Forgejo base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValidationFailed("Forgejo base URL must not contain query or fragment")

    path = parsed.path.rstrip("/")
    normalized = SplitResult(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        query="",
        fragment="",
    )
    return urlunsplit(normalized)


_REPOSITORY_ORDER_VALUES = {
    "name",
    "id",
    "newest",
    "oldest",
    "recentupdate",
    "leastupdate",
    "alphabetically",
    "reversealphabetically",
    "size",
    "reversesize",
    "moststars",
    "feweststars",
    "mostforks",
    "fewestforks",
}


class ForgejoClient:
    def __init__(
        self,
        *,
        connect_timeout_seconds: float,
        read_timeout_seconds: float = 30.0,
        write_timeout_seconds: float = 30.0,
        pool_timeout_seconds: float = 5.0,
        safe_retry_attempts: int = 0,
        retry_max_delay_seconds: float = 2.0,
        commit_max_files: int = 100,
        commit_max_total_bytes: int = 10 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=write_timeout_seconds,
            pool=pool_timeout_seconds,
        )
        self.safe_retry_attempts = safe_retry_attempts
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.commit_max_files = commit_max_files
        self.commit_max_total_bytes = commit_max_total_bytes
        self.transport = transport

    async def list_repositories(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        page: int,
        limit: int,
        order_by: str,
    ) -> Page[RepositorySummary]:
        _validate_page(page, limit)
        if order_by not in _REPOSITORY_ORDER_VALUES:
            raise ValidationFailed("repository order is invalid")
        payload = await self._get_json(
            endpoint=f"{base_url}/api/v1/user/repos",
            token=token,
            verify_tls=verify_tls,
            params={"page": page, "limit": limit, "order_by": order_by},
            resource="repository list",
        )
        items = parse_repositories(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def get_repository(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
    ) -> RepositorySummary:
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        payload = await self._get_json(
            endpoint=f"{base_url}/api/v1/repos/{owner_path}/{repo_path}",
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="repository",
        )
        return parse_repository(payload)

    async def list_branches(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        page: int,
        limit: int,
    ) -> Page[BranchSummary]:
        _validate_page(page, limit)
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        payload = await self._get_json(
            endpoint=f"{base_url}/api/v1/repos/{owner_path}/{repo_path}/branches",
            token=token,
            verify_tls=verify_tls,
            params={"page": page, "limit": limit},
            resource="branch list",
        )
        items = parse_branches(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def list_repository_contents(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        path: str | None,
        ref: str | None,
    ) -> BoundedList[dict[str, Any]]:
        suffix = "contents"
        if path is not None:
            suffix += f"/{quote(_file_path(path), safe='/')}"
        params = {"ref": _ref_value(ref, "ref")} if ref is not None else None
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, suffix),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="repository contents",
        )
        records = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(item, dict) for item in records):
            raise ExternalServiceUnavailable("Forgejo returned invalid repository contents")
        items = [_content_summary(item) for item in records[:100]]
        return BoundedList(items=items, truncated=len(records) > 100)

    async def create_branch(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        branch: str,
        from_ref: str | None,
    ) -> BranchSummary:
        data: dict[str, Any] = {"new_branch_name": _ref_value(branch, "branch")}
        if from_ref is not None:
            data["old_ref_name"] = _ref_value(from_ref, "source ref")
        payload = await self._write_json(
            "POST",
            self._repo_endpoint(base_url, owner, repo, "branches"),
            token,
            verify_tls,
            data,
            "branch",
            201,
        )
        return parse_branches([payload])[0]

    async def list_commits(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        ref: str | None,
        path: str | None,
        page: int,
        limit: int,
    ) -> Page[CommitSummary]:
        _validate_page(page, limit)
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        params: dict[str, str | int | float | bool | None] = {
            "page": page,
            "limit": limit,
            "stat": True,
            "verification": False,
            "files": False,
        }
        if ref is not None:
            params["sha"] = _ref_value(ref, "ref")
        if path is not None:
            params["path"] = _file_path(path)
        payload = await self._get_json(
            endpoint=f"{base_url}/api/v1/repos/{owner_path}/{repo_path}/commits",
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="commit list",
        )
        items = parse_commits(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def get_commit(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        sha: str,
    ) -> CommitDetail:
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        commit_path = quote(_ref_value(sha, "commit SHA", max_length=64), safe="")
        payload = await self._get_json(
            endpoint=f"{base_url}/api/v1/repos/{owner_path}/{repo_path}/git/commits/{commit_path}",
            token=token,
            verify_tls=verify_tls,
            params={"stat": True, "verification": False, "files": True},
            resource="commit",
        )
        return parse_commit(payload)

    async def compare_refs(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        base: str,
        head: str,
    ) -> CompareSummary:
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        base_path = quote(_ref_value(base, "base ref"), safe="")
        head_path = quote(_ref_value(head, "head ref"), safe="")
        payload = await self._get_json(
            endpoint=(
                f"{base_url}/api/v1/repos/{owner_path}/{repo_path}/compare/"
                f"{base_path}...{head_path}"
            ),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="comparison",
        )
        return parse_compare(payload, base=base, head=head)

    async def get_git_tree(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        sha: str,
        recursive: bool,
        page: int,
        limit: int,
    ) -> GitTreeSummary:
        _validate_page(page, limit)
        tree_sha = quote(_ref_value(sha, "tree SHA or ref"), safe="")
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"git/trees/{tree_sha}"),
            token=token,
            verify_tls=verify_tls,
            params={"recursive": recursive, "page": page, "per_page": limit},
            resource="git tree",
        )
        return parse_git_tree(payload, page=page, limit=limit)

    async def list_labels(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        sort: str | None,
        page: int,
        limit: int,
    ) -> Page[RepositoryLabelSummary]:
        _validate_page(page, limit)
        if sort not in {None, "mostissues", "leastissues", "reversealphabetically"}:
            raise ValidationFailed("label sort is invalid")
        params: dict[str, str | int | float | bool | None] = {"page": page, "limit": limit}
        if sort is not None:
            params["sort"] = sort
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, "labels"),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="label list",
        )
        items = parse_repository_labels(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def list_milestones(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        state: str,
        name: str | None,
        page: int,
        limit: int,
    ) -> Page[RepositoryMilestoneSummary]:
        _validate_page(page, limit)
        if state not in {"open", "closed", "all"}:
            raise ValidationFailed("milestone state is invalid")
        params: dict[str, str | int | float | bool | None] = {
            "state": state,
            "page": page,
            "limit": limit,
        }
        if name is not None:
            params["name"] = _search_value(name)
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, "milestones"),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="milestone list",
        )
        items = parse_repository_milestones(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def list_issues(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        state: str,
        labels: list[str] | None,
        milestones: list[str] | None,
        query: str | None,
        since: str | None,
        before: str | None,
        sort: str,
        page: int,
        limit: int,
    ) -> Page[IssueSummary]:
        _validate_page(page, limit)
        if state not in {"open", "closed", "all"}:
            raise ValidationFailed("issue state is invalid")
        if sort not in {
            "relevance",
            "latest",
            "oldest",
            "recentupdate",
            "leastupdate",
            "mostcomment",
            "leastcomment",
        }:
            raise ValidationFailed("issue sort is invalid")
        params: dict[str, str | int | float | bool | None] = {
            "type": "issues",
            "state": state,
            "sort": sort,
            "page": page,
            "limit": limit,
        }
        if labels is not None:
            params["labels"] = ",".join(_string_list(labels, "labels", 50))
        if milestones is not None:
            params["milestones"] = ",".join(_string_list(milestones, "milestones", 50))
        if query is not None:
            params["q"] = _search_value(query)
        if since is not None:
            params["since"] = _timestamp(since, "since")
        if before is not None:
            params["before"] = _timestamp(before, "before")
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, "issues"),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="issue list",
        )
        items = parse_issues(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def get_issue(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
    ) -> IssueSummary:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"issues/{_number(number)}"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="issue",
        )
        return parse_issue(payload)

    async def list_issue_comments(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        since: str | None,
        before: str | None,
    ) -> BoundedList[CommentSummary]:
        params: dict[str, str | int | float | bool | None] = {}
        if since is not None:
            params["since"] = _timestamp(since, "since")
        if before is not None:
            params["before"] = _timestamp(before, "before")
        payload = await self._get_json(
            endpoint=self._repo_endpoint(
                base_url, owner, repo, f"issues/{_number(number)}/comments"
            ),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="issue comments",
        )
        items = parse_comments(payload)
        return BoundedList(items=items[:100], truncated=len(items) > 100)

    async def list_pull_requests(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        state: str,
        base: str | None,
        head: str | None,
        label_ids: list[int] | None,
        milestone_id: int | None,
        sort: str,
        page: int,
        limit: int,
    ) -> Page[PullRequestSummary]:
        _validate_page(page, limit)
        if state not in {"open", "closed", "all"}:
            raise ValidationFailed("pull request state is invalid")
        if sort not in {
            "oldest",
            "recentupdate",
            "recentclose",
            "leastupdate",
            "mostcomment",
            "leastcomment",
            "priority",
        }:
            raise ValidationFailed("pull request sort is invalid")
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "page": page,
            "limit": limit,
        }
        if base is not None:
            params["base"] = _ref_value(base, "base ref")
        if head is not None:
            params["head"] = _ref_value(head, "head ref")
        if label_ids is not None:
            params["labels"] = _id_list(label_ids, "label IDs", 50)
        if milestone_id is not None:
            params["milestone"] = _positive_id(milestone_id, "milestone ID")
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, "pulls"),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="pull request list",
        )
        items = parse_pull_requests(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def get_pull_request(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
    ) -> PullRequestSummary:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="pull request",
        )
        return parse_pull_request(payload)

    async def list_pull_request_commits(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        page: int,
        limit: int,
    ) -> Page[CommitSummary]:
        _validate_page(page, limit)
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/commits"),
            token=token,
            verify_tls=verify_tls,
            params={"page": page, "limit": limit, "verification": False, "files": False},
            resource="pull request commit list",
        )
        items = parse_commits(payload)
        return Page(items=items, page=page, limit=limit, has_more=len(items) == limit)

    async def get_pull_request_diff(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
    ) -> DiffContent:
        response = await self._request(
            method="GET",
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}.diff"),
            token=token,
            verify_tls=verify_tls,
            params={"binary": False},
            json_body=None,
            resource="pull request diff",
            expected_status=200,
            accept="text/plain, application/octet-stream",
        )
        if len(response.content) > MAX_DIFF_BYTES:
            raise ExternalServiceUnavailable("Forgejo pull request diff is too large")
        try:
            content = response.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ExternalServiceUnavailable(
                "Forgejo returned an invalid pull request diff"
            ) from error
        return DiffContent(
            number=number,
            format="diff",
            size=len(response.content),
            sha256=hashlib.sha256(response.content).hexdigest(),
            content=content,
        )

    async def get_file_content(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        path: str,
        ref: str | None,
    ) -> FileContent:
        normalized_path = _file_path(path)
        params: dict[str, str | int | float | bool | None] | None = (
            {"ref": _ref_value(ref, "ref")} if ref is not None else None
        )
        payload = await self._get_json(
            endpoint=self._repo_endpoint(
                base_url, owner, repo, f"contents/{quote(normalized_path, safe='/')}"
            ),
            token=token,
            verify_tls=verify_tls,
            params=params,
            resource="file content",
        )
        if not isinstance(payload, dict):
            raise ExternalServiceUnavailable("Forgejo returned an invalid file content response")
        encoded = payload.get("content")
        if not isinstance(encoded, str) or payload.get("encoding") != "base64":
            raise ExternalServiceUnavailable("Forgejo returned an invalid file content response")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ExternalServiceUnavailable(
                "Forgejo returned an invalid file content response"
            ) from error
        if len(decoded) > MAX_FILE_CONTENT_BYTES:
            raise ExternalServiceUnavailable("Forgejo file content is too large")
        try:
            output_content = decoded.decode("utf-8")
            output_encoding = "utf-8"
        except UnicodeDecodeError:
            output_content = base64.b64encode(decoded).decode("ascii")
            output_encoding = "base64"
        name, sha, size = payload.get("name"), payload.get("sha"), payload.get("size")
        html_url = payload.get("html_url")
        if not isinstance(name, str) or not isinstance(sha, str) or not isinstance(size, int):
            raise ExternalServiceUnavailable("Forgejo returned an invalid file content response")
        if size != len(decoded) or (html_url is not None and not isinstance(html_url, str)):
            raise ExternalServiceUnavailable("Forgejo returned an invalid file content response")
        return FileContent(
            path=normalized_path,
            name=name,
            sha=sha,
            ref=ref,
            size=size,
            encoding=output_encoding,
            content=output_content,
            html_url=html_url,
        )

    async def commit_changes(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        branch: str | None,
        new_branch: str | None,
        message: str,
        changes: list[dict[str, Any]],
        signoff: bool,
    ) -> dict[str, Any]:
        if not changes or len(changes) > self.commit_max_files:
            raise ValidationFailed(
                f"changes must contain between 1 and {self.commit_max_files} operations"
            )
        files = [_change_file_operation(change) for change in changes]
        if sum(_change_content_size(change) for change in changes) > self.commit_max_total_bytes:
            raise ValidationFailed("combined file change content is too large")
        data: dict[str, Any] = {
            "files": files,
            "message": _commit_message(message),
            "signoff": signoff,
        }
        if branch is not None:
            data["branch"] = _ref_value(branch, "branch")
        if new_branch is not None:
            data["new_branch"] = _ref_value(new_branch, "new branch")
        payload = await self._write_json(
            "POST",
            self._repo_endpoint(base_url, owner, repo, "contents"),
            token,
            verify_tls,
            data,
            "file changes",
            201,
        )
        if not isinstance(payload, dict):
            raise ExternalServiceUnavailable("Forgejo returned invalid file changes")
        commit = payload.get("commit")
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        files_payload = payload.get("files", [])
        if not isinstance(commit_sha, str) or not isinstance(files_payload, list):
            raise ExternalServiceUnavailable("Forgejo returned invalid file changes")
        files = [_content_summary(item) for item in files_payload if isinstance(item, dict)]
        if len(files) != len(files_payload):
            raise ExternalServiceUnavailable("Forgejo returned invalid file changes")
        return {"commit_sha": commit_sha, "files": files[:100]}

    async def list_pull_request_files(
        self, *, base_url: str, token: str, verify_tls: bool, owner: str, repo: str, number: int
    ) -> BoundedList[dict[str, Any]]:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/files"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="pull request files",
        )
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ExternalServiceUnavailable("Forgejo returned invalid pull request files")
        return BoundedList(
            items=[_changed_file_summary(item) for item in payload[:100]],
            truncated=len(payload) > 100,
        )

    async def change_pull_request_reviewers(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        reviewers: list[str] | None,
        team_reviewers: list[str] | None,
        remove: bool,
    ) -> dict[str, list[str]]:
        data = {
            "reviewers": _string_list(reviewers or [], "reviewers", 20),
            "team_reviewers": _string_list(team_reviewers or [], "team reviewers", 20),
        }
        if not data["reviewers"] and not data["team_reviewers"]:
            raise ValidationFailed("at least one reviewer or team reviewer is required")
        await self._request(
            method="DELETE" if remove else "POST",
            endpoint=self._repo_endpoint(
                base_url, owner, repo, f"pulls/{_number(number)}/requested_reviewers"
            ),
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=data,
            resource="pull request reviewers",
            expected_status={200, 201, 204},
            accept="application/json",
        )
        return data

    async def list_pull_request_reviews(
        self, *, base_url: str, token: str, verify_tls: bool, owner: str, repo: str, number: int
    ) -> BoundedList[dict[str, Any]]:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/reviews"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="pull request reviews",
        )
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ExternalServiceUnavailable("Forgejo returned invalid pull request reviews")
        return BoundedList(
            items=[_review_summary(item) for item in payload[:100]], truncated=len(payload) > 100
        )

    async def get_pull_request_review(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        review_id: int,
    ) -> dict[str, Any]:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(
                base_url,
                owner,
                repo,
                f"pulls/{_number(number)}/reviews/{_positive_id(review_id, 'review ID')}",
            ),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="pull request review",
        )
        return _review_summary(payload)

    async def submit_pull_request_review(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        event: str,
        body: str | None,
        commit_id: str | None,
        comments: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if event not in {"APPROVED", "REQUEST_CHANGES", "COMMENT"}:
            raise ValidationFailed("review event is invalid")
        data: dict[str, Any] = {"event": event}
        if body is not None:
            data["body"] = _comment_body(body)
        if commit_id is not None:
            data["commit_id"] = _ref_value(commit_id, "commit ID", max_length=64)
        if comments is not None:
            if len(comments) > 100:
                raise ValidationFailed("review has too many comments")
            data["comments"] = [_review_comment(item) for item in comments]
        payload = await self._write_json(
            "POST",
            self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/reviews"),
            token,
            verify_tls,
            data,
            "pull request review",
            200,
        )
        return _review_summary(payload)

    async def merge_pull_request(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        method: str,
        title: str | None,
        message: str | None,
        head_sha: str | None,
        delete_branch: bool,
    ) -> None:
        if method not in {"merge", "rebase", "rebase-merge", "squash", "manually-merged"}:
            raise ValidationFailed("merge method is invalid")
        data: dict[str, Any] = {"Do": method, "delete_branch_after_merge": delete_branch}
        if title is not None:
            data["MergeTitleField"] = _title(title)
        if message is not None:
            data["MergeMessageField"] = _body(message)
        if head_sha is not None:
            data["head_commit_id"] = _ref_value(head_sha, "head SHA", max_length=64)
        await self._request(
            method="POST",
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/merge"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=data,
            resource="pull request merge",
            expected_status={200, 201, 204},
            accept="application/json",
        )

    async def get_pull_request_merge_status(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
    ) -> bool:
        await self.get_pull_request(
            base_url=base_url,
            token=token,
            verify_tls=verify_tls,
            owner=owner,
            repo=repo,
            number=number,
        )
        response = await self._request(
            method="GET",
            endpoint=self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}/merge"),
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=None,
            resource="pull request merge status",
            expected_status={204, 404},
            accept="application/json",
        )
        return response.status_code == 204

    async def get_commit_status(
        self, *, base_url: str, token: str, verify_tls: bool, owner: str, repo: str, ref: str
    ) -> dict[str, Any]:
        payload = await self._get_json(
            endpoint=self._repo_endpoint(
                base_url, owner, repo, f"commits/{quote(_ref_value(ref, 'ref'), safe='')}/status"
            ),
            token=token,
            verify_tls=verify_tls,
            params=None,
            resource="commit status",
        )
        return _combined_status(payload)

    async def dispatch_workflow(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str] | None,
    ) -> None:
        data: dict[str, Any] = {"ref": _ref_value(ref, "ref")}
        if inputs is not None:
            if len(inputs) > 50 or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in inputs.items()
            ):
                raise ValidationFailed("workflow inputs are invalid")
            data["inputs"] = inputs
        await self._request(
            method="POST",
            endpoint=self._repo_endpoint(
                base_url,
                owner,
                repo,
                f"actions/workflows/{quote(_ref_value(workflow, 'workflow'), safe='')}/dispatches",
            ),
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=data,
            resource="workflow dispatch",
            expected_status={200, 204},
            accept="application/json",
        )

    async def create_tag(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        tag: str,
        target: str | None,
        message: str | None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"tag_name": _ref_value(tag, "tag")}
        if target is not None:
            data["target"] = _ref_value(target, "target")
        if message is not None:
            data["message"] = _body(message)
        payload = await self._write_json(
            "POST",
            self._repo_endpoint(base_url, owner, repo, "tags"),
            token,
            verify_tls,
            data,
            "tag",
            201,
        )
        return _tag_summary(payload)

    async def create_release(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        tag: str,
        target: str | None,
        name: str | None,
        body: str | None,
        draft: bool,
        prerelease: bool,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "tag_name": _ref_value(tag, "tag"),
            "draft": draft,
            "prerelease": prerelease,
        }
        if target is not None:
            data["target_commitish"] = _ref_value(target, "target")
        if name is not None:
            data["name"] = _title(name)
        if body is not None:
            data["body"] = _body(body)
        payload = await self._write_json(
            "POST",
            self._repo_endpoint(base_url, owner, repo, "releases"),
            token,
            verify_tls,
            data,
            "release",
            201,
        )
        return _release_summary(payload)

    async def create_issue(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        title: str,
        body: str | None,
        assignees: list[str] | None,
        label_ids: list[int] | None,
        milestone_id: int | None,
    ) -> IssueSummary:
        data: dict[str, Any] = {"title": _title(title)}
        if body is not None:
            data["body"] = _body(body)
        if assignees is not None:
            data["assignees"] = _string_list(assignees, "assignees", 20)
        if label_ids is not None:
            data["labels"] = _id_list(label_ids, "label IDs", 50)
        if milestone_id is not None:
            data["milestone"] = _positive_id(milestone_id, "milestone ID")
        return parse_issue(
            await self._write_json(
                "POST",
                self._repo_endpoint(base_url, owner, repo, "issues"),
                token,
                verify_tls,
                data,
                "issue",
                201,
            )
        )

    async def update_issue(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        changes: dict[str, Any],
    ) -> IssueSummary:
        data = _issue_changes(changes)
        return parse_issue(
            await self._write_json(
                "PATCH",
                self._repo_endpoint(base_url, owner, repo, f"issues/{_number(number)}"),
                token,
                verify_tls,
                data,
                "issue",
                201,
            )
        )

    async def comment_issue(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        body: str,
    ) -> CommentSummary:
        data = {"body": _comment_body(body)}
        return parse_comment(
            await self._write_json(
                "POST",
                self._repo_endpoint(base_url, owner, repo, f"issues/{_number(number)}/comments"),
                token,
                verify_tls,
                data,
                "comment",
                201,
            )
        )

    async def create_pull_request(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None,
        draft: bool | None,
    ) -> PullRequestSummary:
        data: dict[str, Any] = {
            "title": _title(title),
            "head": _ref_value(head, "head ref"),
            "base": _ref_value(base, "base ref"),
        }
        if body is not None:
            data["body"] = _body(body)
        if draft is not None:
            data["draft"] = draft
        return parse_pull_request(
            await self._write_json(
                "POST",
                self._repo_endpoint(base_url, owner, repo, "pulls"),
                token,
                verify_tls,
                data,
                "pull request",
                201,
            )
        )

    async def update_pull_request(
        self,
        *,
        base_url: str,
        token: str,
        verify_tls: bool,
        owner: str,
        repo: str,
        number: int,
        changes: dict[str, Any],
    ) -> PullRequestSummary:
        data = _pull_changes(changes)
        return parse_pull_request(
            await self._write_json(
                "PATCH",
                self._repo_endpoint(base_url, owner, repo, f"pulls/{_number(number)}"),
                token,
                verify_tls,
                data,
                "pull request",
                201,
            )
        )

    def _repo_endpoint(self, base_url: str, owner: str, repo: str, suffix: str) -> str:
        owner_path = _repository_segment(owner, "owner")
        repo_path = _repository_segment(repo, "repository")
        return f"{base_url}/api/v1/repos/{owner_path}/{repo_path}/{suffix}"

    async def _write_json(
        self,
        method: str,
        endpoint: str,
        token: str,
        verify_tls: bool,
        data: dict[str, Any],
        resource: str,
        expected_status: int,
    ) -> Any:
        response = await self._request(
            method=method,
            endpoint=endpoint,
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=data,
            resource=resource,
            expected_status=expected_status,
            accept="application/json",
        )
        if len(response.content) > MAX_JSON_RESPONSE_BYTES:
            raise ExternalServiceUnavailable(f"Forgejo {resource} response is too large")
        try:
            return response.json()
        except ValueError as error:
            raise ExternalServiceUnavailable(
                f"Forgejo returned an invalid {resource} response"
            ) from error

    async def _get_json(
        self,
        *,
        endpoint: str,
        token: str,
        verify_tls: bool,
        params: Any,
        resource: str,
    ) -> Any:
        response = await self._request(
            method="GET",
            endpoint=endpoint,
            token=token,
            verify_tls=verify_tls,
            params=params,
            json_body=None,
            resource=resource,
            expected_status=200,
            accept="application/json",
        )
        if len(response.content) > MAX_JSON_RESPONSE_BYTES:
            raise ExternalServiceUnavailable(f"Forgejo {resource} response is too large")
        try:
            return response.json()
        except ValueError as error:
            raise ExternalServiceUnavailable(
                f"Forgejo returned an invalid {resource} response"
            ) from error

    async def _request(
        self,
        *,
        method: str,
        endpoint: str,
        token: str | None,
        verify_tls: bool,
        params: Any,
        json_body: dict[str, Any] | None,
        resource: str,
        expected_status: int | set[int],
        accept: str,
    ) -> httpx.Response:
        method = method.upper()
        retries = self.safe_retry_attempts if method in {"GET", "HEAD", "OPTIONS"} else 0
        headers = {"Authorization": f"token {token}"} if token is not None else None
        response: httpx.Response | None = None
        for attempt in range(retries + 1):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    verify=verify_tls,
                    follow_redirects=False,
                    headers={"Accept": accept, "User-Agent": "forgejo-mcp/0.1.0"},
                    transport=self.transport,
                ) as client:
                    response = await client.request(
                        method,
                        endpoint,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ) as error:
                FORGEJO_REQUESTS.labels(method=method, status="transport_error").inc()
                FORGEJO_DURATION.labels(method=method).observe(time.monotonic() - started)
                if attempt < retries:
                    FORGEJO_RETRIES.labels(reason="transport_error").inc()
                    await asyncio.sleep(self._retry_delay(attempt, None))
                    continue
                raise ExternalServiceUnavailable("unable to connect to Forgejo") from error
            except httpx.HTTPError as error:
                FORGEJO_REQUESTS.labels(method=method, status="transport_error").inc()
                FORGEJO_DURATION.labels(method=method).observe(time.monotonic() - started)
                raise ExternalServiceUnavailable("unable to connect to Forgejo") from error
            FORGEJO_REQUESTS.labels(method=method, status=str(response.status_code)).inc()
            FORGEJO_DURATION.labels(method=method).observe(time.monotonic() - started)
            if response.status_code in {429, 502, 503, 504} and attempt < retries:
                FORGEJO_RETRIES.labels(reason=str(response.status_code)).inc()
                await asyncio.sleep(self._retry_delay(attempt, response))
                continue
            break
        if response is None:
            raise ExternalServiceUnavailable("unable to connect to Forgejo")
        if response.is_redirect:
            raise ExternalServiceUnavailable(f"Forgejo {resource} endpoint returned a redirect")
        expected_statuses = (
            expected_status if isinstance(expected_status, set) else {expected_status}
        )
        if response.status_code in expected_statuses:
            return response
        if response.status_code == 401:
            raise ValidationFailed("Forgejo rejected the personal access token")
        if response.status_code == 403:
            raise ValidationFailed(f"Forgejo PAT does not permit access to the {resource}")
        if response.status_code == 404:
            raise NotFound(f"Forgejo {resource} not found")
        if response.status_code == 422:
            raise ValidationFailed(f"Forgejo rejected the {resource} request")
        if response.status_code == 409:
            raise ExternalServiceUnavailable(f"Forgejo reported a conflict for the {resource}")
        if response.status_code == 429:
            raise ExternalServiceUnavailable("Forgejo rate limit was exceeded")
        raise ExternalServiceUnavailable(
            f"Forgejo {resource} endpoint returned HTTP {response.status_code}"
        )

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after: str | None = (
            response.headers.get("Retry-After") if response is not None else None
        )
        requested_delay = _retry_after_seconds(retry_after)
        exponential_delay = 0.25 * (2**attempt)
        return float(min(self.retry_max_delay_seconds, max(requested_delay, exponential_delay)))

    async def get_version(self, *, base_url: str, verify_tls: bool) -> ForgejoVersion:
        response = await self._request(
            method="GET",
            endpoint=f"{base_url}/api/v1/version",
            token=None,
            verify_tls=verify_tls,
            params=None,
            json_body=None,
            resource="version",
            expected_status=200,
            accept="application/json",
        )
        if len(response.content) > MAX_VERSION_RESPONSE_BYTES:
            raise ExternalServiceUnavailable("Forgejo version response is too large")
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalServiceUnavailable(
                "Forgejo returned an invalid version response"
            ) from error
        version = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(version, str) or not version.strip() or len(version) > 120:
            raise ExternalServiceUnavailable("Forgejo returned an invalid version response")
        return ForgejoVersion(version=version.strip())

    async def get_current_user(self, *, base_url: str, token: str, verify_tls: bool) -> ForgejoUser:
        response = await self._request(
            method="GET",
            endpoint=f"{base_url}/api/v1/user",
            token=token,
            verify_tls=verify_tls,
            params=None,
            json_body=None,
            resource="user",
            expected_status=200,
            accept="application/json",
        )
        if len(response.content) > MAX_USER_RESPONSE_BYTES:
            raise ExternalServiceUnavailable("Forgejo user response is too large")
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalServiceUnavailable("Forgejo returned an invalid user response") from error
        user_id = payload.get("id") if isinstance(payload, dict) else None
        username = payload.get("login") if isinstance(payload, dict) else None
        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id < 1
            or not isinstance(username, str)
            or not username.strip()
            or len(username) > 255
        ):
            raise ExternalServiceUnavailable("Forgejo returned an invalid user response")
        return ForgejoUser(id=user_id, username=username.strip())


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _validate_page(page: int, limit: int) -> None:
    if isinstance(page, bool) or page < 1 or page > 100_000:
        raise ValidationFailed("page must be between 1 and 100000")
    if isinstance(limit, bool) or limit < 1 or limit > 100:
        raise ValidationFailed("limit must be between 1 and 100")


def _ref_value(value: str, label: str, *, max_length: int = 255) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValidationFailed(f"{label} is invalid")
    return normalized


def _file_path(value: str) -> str:
    normalized = value.strip()
    segments = normalized.split("/")
    if (
        not normalized
        or len(normalized) > 1024
        or normalized.startswith("/")
        or any(segment == ".." for segment in segments)
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValidationFailed("path is invalid")
    return normalized


def _repository_segment(value: str, label: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 255
        or "/" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValidationFailed(f"{label} is invalid")
    return quote(normalized, safe="")


def _number(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ValidationFailed("number must be a positive integer")
    return value


def _positive_id(value: int, label: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise ValidationFailed(f"{label} must be a positive integer")
    return value


def _timestamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationFailed(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValidationFailed(f"{label} must include a timezone")
    return value


def _search_value(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 256:
        raise ValidationFailed("query is invalid")
    return normalized


def _string_list(values: list[str], label: str, maximum: int) -> list[str]:
    if len(values) > maximum:
        raise ValidationFailed(f"{label} contains too many items")
    result = []
    for value in values:
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise ValidationFailed(f"{label} contains an invalid value")
        result.append(normalized)
    return result


def _id_list(values: list[int], label: str, maximum: int) -> list[int]:
    if len(values) > maximum:
        raise ValidationFailed(f"{label} contains too many items")
    return [_positive_id(value, label) for value in values]


def _title(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValidationFailed("title is invalid")
    return normalized


def _body(value: str) -> str:
    if len(value) > 65_536:
        raise ValidationFailed("body is too large")
    return value


def _comment_body(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(value) > 32_768:
        raise ValidationFailed("comment body is invalid")
    return value


def _required_string(payload: dict[str, Any], key: str, resource: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ExternalServiceUnavailable(f"Forgejo returned an invalid {resource} response")
    return value


def _optional_string(payload: dict[str, Any], key: str, resource: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise ExternalServiceUnavailable(f"Forgejo returned an invalid {resource} response")
    return value


def _content_summary(payload: dict[str, Any]) -> dict[str, Any]:
    kind = _required_string(payload, "type", "repository contents")
    if kind not in {"file", "dir", "symlink", "submodule"}:
        raise ExternalServiceUnavailable("Forgejo returned invalid repository contents")
    size = payload.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ExternalServiceUnavailable("Forgejo returned invalid repository contents")
    return {
        "name": _required_string(payload, "name", "repository contents"),
        "path": _required_string(payload, "path", "repository contents"),
        "sha": _required_string(payload, "sha", "repository contents"),
        "type": kind,
        "size": size,
        "html_url": _optional_string(payload, "html_url", "repository contents"),
    }


def _changed_file_summary(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _required_string(payload, "filename", "pull request files"),
        "previous_path": _optional_string(payload, "previous_filename", "pull request files"),
        "status": _required_string(payload, "status", "pull request files"),
    }
    for key in ("additions", "deletions", "changes"):
        value = payload.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ExternalServiceUnavailable("Forgejo returned invalid pull request files")
        result[key] = value
    return result


def _review_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceUnavailable("Forgejo returned an invalid pull request review")
    review_id, user = payload.get("id"), payload.get("user")
    username = user.get("login") if isinstance(user, dict) else None
    if (
        not isinstance(review_id, int)
        or isinstance(review_id, bool)
        or not isinstance(username, str)
    ):
        raise ExternalServiceUnavailable("Forgejo returned an invalid pull request review")
    count = payload.get("comments_count", 0)
    if not isinstance(count, int) or isinstance(count, bool):
        raise ExternalServiceUnavailable("Forgejo returned an invalid pull request review")
    return {
        "id": review_id,
        "user": username,
        "state": _required_string(payload, "state", "pull request review"),
        "body": _optional_string(payload, "body", "pull request review"),
        "commit_id": _optional_string(payload, "commit_id", "pull request review"),
        "submitted_at": _optional_string(payload, "submitted_at", "pull request review"),
        "stale": bool(payload.get("stale", False)),
        "dismissed": bool(payload.get("dismissed", False)),
        "comments_count": count,
    }


def _combined_status(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceUnavailable("Forgejo returned an invalid commit status")
    statuses_value = payload.get("statuses")
    statuses = [] if statuses_value is None else statuses_value
    if not isinstance(statuses, list) or not all(isinstance(item, dict) for item in statuses):
        raise ExternalServiceUnavailable("Forgejo returned an invalid commit status")
    normalized = [
        {
            "context": str(item.get("context", "")),
            "state": str(item.get("status", item.get("state", ""))),
            "description": item.get("description")
            if isinstance(item.get("description"), str)
            else None,
            "target_url": item.get("target_url")
            if isinstance(item.get("target_url"), str)
            else None,
        }
        for item in statuses[:100]
    ]
    total = payload.get("total_count", len(statuses))
    if not isinstance(total, int) or isinstance(total, bool):
        raise ExternalServiceUnavailable("Forgejo returned an invalid commit status")
    state = _required_string(payload, "state", "commit status") or "pending"
    return {
        "sha": _required_string(payload, "sha", "commit status"),
        "state": state,
        "total_count": total,
        "statuses": normalized,
        "truncated": len(statuses) > 100,
    }


def _tag_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceUnavailable("Forgejo returned an invalid tag response")
    commit = payload.get("commit")
    commit_sha = commit.get("sha", commit.get("id")) if isinstance(commit, dict) else None
    if not isinstance(commit_sha, str):
        raise ExternalServiceUnavailable("Forgejo returned an invalid tag response")
    return {
        "name": _required_string(payload, "name", "tag"),
        "id": _optional_string(payload, "id", "tag"),
        "commit_sha": commit_sha,
        "message": _optional_string(payload, "message", "tag"),
    }


def _release_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceUnavailable("Forgejo returned an invalid release response")
    release_id = payload.get("id")
    if not isinstance(release_id, int) or isinstance(release_id, bool):
        raise ExternalServiceUnavailable("Forgejo returned an invalid release response")
    return {
        "id": release_id,
        "tag_name": _required_string(payload, "tag_name", "release"),
        "name": str(payload.get("name", "")),
        "html_url": _optional_string(payload, "html_url", "release"),
        "draft": bool(payload.get("draft", False)),
        "prerelease": bool(payload.get("prerelease", False)),
    }


def _change_file_operation(change: dict[str, Any]) -> dict[str, Any]:
    operation = change.get("operation")
    if operation not in {"create", "update", "delete"}:
        raise ValidationFailed("file operation is invalid")
    data: dict[str, Any] = {"operation": operation, "path": _file_path(change.get("path", ""))}
    if "sha" in change:
        data["sha"] = _ref_value(change["sha"], "file SHA", max_length=64)
    if operation in {"update", "delete"} and "sha" not in data:
        raise ValidationFailed("file SHA is required for update or delete")
    if "from_path" in change:
        data["from_path"] = _file_path(change["from_path"])
    if operation != "delete":
        content, encoding = change.get("content"), change.get("encoding", "utf-8")
        if not isinstance(content, str):
            raise ValidationFailed("file content is required")
        if encoding == "utf-8":
            decoded = content.encode()
            encoded = base64.b64encode(decoded).decode()
        elif encoding == "base64":
            try:
                decoded = base64.b64decode(content, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValidationFailed("file content is not valid base64") from error
            encoded = content
        else:
            raise ValidationFailed("file encoding is invalid")
        if len(decoded) > MAX_FILE_CONTENT_BYTES:
            raise ValidationFailed("file content is too large")
        data["content"] = encoded
    return data


def _change_content_size(change: dict[str, Any]) -> int:
    if change.get("operation") == "delete":
        return 0
    content = change.get("content")
    if not isinstance(content, str):
        raise ValidationFailed("file content is required")
    if change.get("encoding", "utf-8") == "utf-8":
        return len(content.encode())
    try:
        return len(base64.b64decode(content, validate=True))
    except (ValueError, binascii.Error) as error:
        raise ValidationFailed("file content is not valid base64") from error


def _review_comment(comment: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": _file_path(comment.get("path", "")),
        "body": _comment_body(comment.get("body", "")),
    }
    for key in ("old_position", "new_position"):
        if key in comment:
            value = comment[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationFailed("review comment position is invalid")
            data[key] = value
    if "old_position" not in data and "new_position" not in data:
        raise ValidationFailed("review comment requires a position")
    return data


def _commit_message(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 65_536:
        raise ValidationFailed("commit message is invalid")
    return normalized


def _issue_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "body", "state", "assignees", "label_ids", "milestone_id"}
    if not changes or not set(changes) <= allowed:
        raise ValidationFailed("issue update fields are invalid")
    data: dict[str, Any] = {}
    if "title" in changes:
        data["title"] = _title(changes["title"])
    if "body" in changes:
        data["body"] = None if changes["body"] is None else _body(changes["body"])
    if "state" in changes:
        if changes["state"] not in {"open", "closed"}:
            raise ValidationFailed("issue state is invalid")
        data["state"] = changes["state"]
    if "assignees" in changes:
        data["assignees"] = _string_list(changes["assignees"], "assignees", 20)
    if "label_ids" in changes:
        data["labels"] = _id_list(changes["label_ids"], "label IDs", 50)
    if "milestone_id" in changes:
        data["milestone"] = (
            None
            if changes["milestone_id"] is None
            else _positive_id(changes["milestone_id"], "milestone ID")
        )
    return data


def _pull_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "body", "state", "base"}
    if not changes or not set(changes) <= allowed:
        raise ValidationFailed("pull request update fields are invalid")
    data: dict[str, Any] = {}
    if "title" in changes:
        data["title"] = _title(changes["title"])
    if "body" in changes:
        data["body"] = None if changes["body"] is None else _body(changes["body"])
    if "state" in changes:
        if changes["state"] not in {"open", "closed"}:
            raise ValidationFailed("pull request state is invalid")
        data["state"] = changes["state"]
    if "base" in changes:
        data["base"] = _ref_value(changes["base"], "base ref")
    return data
