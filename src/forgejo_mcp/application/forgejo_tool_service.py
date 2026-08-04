import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import Conflict
from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import ForgejoInstance
from forgejo_mcp.db.repositories import ForgejoInstanceRepository
from forgejo_mcp.forgejo.client import BoundedList, DiffContent, ForgejoUser, Page
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
)


class ForgejoToolService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.credentials = ForgejoCredentialService(session, settings)
        self.instances = ForgejoInstanceRepository(session)

    async def get_current_user(self, user_id: uuid.UUID) -> ForgejoUser:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_current_user(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
        )

    async def list_repositories(
        self,
        user_id: uuid.UUID,
        *,
        page: int,
        limit: int,
        order_by: str,
    ) -> Page[RepositorySummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_repositories(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            page=page,
            limit=limit,
            order_by=order_by,
        )

    async def get_repository(
        self, user_id: uuid.UUID, *, owner: str, repo: str
    ) -> RepositorySummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_repository(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            owner=owner,
            repo=repo,
        )

    async def list_branches(
        self,
        user_id: uuid.UUID,
        *,
        owner: str,
        repo: str,
        page: int,
        limit: int,
    ) -> Page[BranchSummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_branches(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            owner=owner,
            repo=repo,
            page=page,
            limit=limit,
        )

    async def list_repository_contents(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> BoundedList[dict[str, Any]]:
        return cast(
            BoundedList[dict[str, Any]],
            await self._call(user_id, "list_repository_contents", **kwargs),
        )

    async def create_branch(self, user_id: uuid.UUID, **kwargs: Any) -> BranchSummary:
        return cast(BranchSummary, await self._call(user_id, "create_branch", **kwargs))

    async def list_commits(
        self,
        user_id: uuid.UUID,
        *,
        owner: str,
        repo: str,
        ref: str | None,
        path: str | None,
        page: int,
        limit: int,
    ) -> Page[CommitSummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_commits(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            owner=owner,
            repo=repo,
            ref=ref,
            path=path,
            page=page,
            limit=limit,
        )

    async def get_commit(
        self, user_id: uuid.UUID, *, owner: str, repo: str, sha: str
    ) -> CommitDetail:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_commit(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            owner=owner,
            repo=repo,
            sha=sha,
        )

    async def compare_refs(
        self,
        user_id: uuid.UUID,
        *,
        owner: str,
        repo: str,
        base: str,
        head: str,
    ) -> CompareSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.compare_refs(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            owner=owner,
            repo=repo,
            base=base,
            head=head,
        )

    async def get_git_tree(self, user_id: uuid.UUID, **kwargs: Any) -> GitTreeSummary:
        return cast(GitTreeSummary, await self._call(user_id, "get_git_tree", **kwargs))

    async def list_labels(self, user_id: uuid.UUID, **kwargs: Any) -> Page[RepositoryLabelSummary]:
        return cast(
            Page[RepositoryLabelSummary], await self._call(user_id, "list_labels", **kwargs)
        )

    async def list_milestones(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> Page[RepositoryMilestoneSummary]:
        return cast(
            Page[RepositoryMilestoneSummary],
            await self._call(user_id, "list_milestones", **kwargs),
        )

    async def list_issues(self, user_id: uuid.UUID, **kwargs: Any) -> Page[IssueSummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_issues(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def get_issue(self, user_id: uuid.UUID, **kwargs: Any) -> IssueSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_issue(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def list_issue_comments(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> BoundedList[CommentSummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_issue_comments(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def list_pull_requests(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> Page[PullRequestSummary]:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.list_pull_requests(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def get_pull_request(self, user_id: uuid.UUID, **kwargs: Any) -> PullRequestSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_pull_request(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def list_pull_request_commits(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> Page[CommitSummary]:
        return cast(
            Page[CommitSummary],
            await self._call(user_id, "list_pull_request_commits", **kwargs),
        )

    async def get_pull_request_diff(self, user_id: uuid.UUID, **kwargs: Any) -> DiffContent:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_pull_request_diff(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def get_file_content(self, user_id: uuid.UUID, **kwargs: Any) -> FileContent:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.get_file_content(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def commit_changes(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call(user_id, "commit_changes", **kwargs))

    async def list_pull_request_files(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> BoundedList[dict[str, Any]]:
        return cast(
            BoundedList[dict[str, Any]],
            await self._call(user_id, "list_pull_request_files", **kwargs),
        )

    async def change_pull_request_reviewers(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> dict[str, list[str]]:
        return cast(
            dict[str, list[str]],
            await self._call(user_id, "change_pull_request_reviewers", **kwargs),
        )

    async def list_pull_request_reviews(
        self, user_id: uuid.UUID, **kwargs: Any
    ) -> BoundedList[dict[str, Any]]:
        return cast(
            BoundedList[dict[str, Any]],
            await self._call(user_id, "list_pull_request_reviews", **kwargs),
        )

    async def get_pull_request_review(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._call(user_id, "get_pull_request_review", **kwargs),
        )

    async def submit_pull_request_review(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._call(user_id, "submit_pull_request_review", **kwargs),
        )

    async def merge_pull_request(self, user_id: uuid.UUID, **kwargs: Any) -> None:
        await self._call(user_id, "merge_pull_request", **kwargs)

    async def get_pull_request_merge_status(self, user_id: uuid.UUID, **kwargs: Any) -> bool:
        return cast(
            bool,
            await self._call(user_id, "get_pull_request_merge_status", **kwargs),
        )

    async def get_commit_status(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call(user_id, "get_commit_status", **kwargs))

    async def dispatch_workflow(self, user_id: uuid.UUID, **kwargs: Any) -> None:
        await self._call(user_id, "dispatch_workflow", **kwargs)

    async def create_tag(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call(user_id, "create_tag", **kwargs))

    async def create_release(self, user_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call(user_id, "create_release", **kwargs))

    async def create_issue(self, user_id: uuid.UUID, **kwargs: Any) -> IssueSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.create_issue(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def update_issue(self, user_id: uuid.UUID, **kwargs: Any) -> IssueSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.update_issue(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def comment_issue(self, user_id: uuid.UUID, **kwargs: Any) -> CommentSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.comment_issue(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def create_pull_request(self, user_id: uuid.UUID, **kwargs: Any) -> PullRequestSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.create_pull_request(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def update_pull_request(self, user_id: uuid.UUID, **kwargs: Any) -> PullRequestSummary:
        instance, token = await self._connection(user_id)
        return await self.credentials.client.update_pull_request(
            base_url=instance.base_url, token=token, verify_tls=instance.verify_tls, **kwargs
        )

    async def _call(self, user_id: uuid.UUID, method_name: str, **kwargs: Any) -> Any:
        instance, token = await self._connection(user_id)
        function = getattr(self.credentials.client, method_name)
        return await function(
            base_url=instance.base_url,
            token=token,
            verify_tls=instance.verify_tls,
            **kwargs,
        )

    async def _connection(self, user_id: uuid.UUID) -> tuple[ForgejoInstance, str]:
        instance = await self.instances.primary()
        if instance is None:
            raise Conflict("Forgejo instance is not configured")
        token = await self.credentials.decrypted_token_for_user(user_id)
        return instance, token
