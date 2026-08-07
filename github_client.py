"""GitHub REST API client.

Thin async wrapper around the GitHub API used by the pipeline to fetch
pull request metadata and per-file diff information.
"""
from __future__ import annotations
from typing import
import httpx
from app.config import settings


class GithubClient:
    """Async HTTP client for the GitHub REST API.

    Authentication is optional; when ``settings.github_api_token`` is set,
    requests are sent with a ``Bearer`` token header.
    """

    def __init__(self) -> None:
        """Initialise the client with the base URL and auth headers from settings."""
        self._base = settings.github_api_base_url.rstrip("/")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.github_api_token:
            self._headers["Authorization"] = f"Bearer {settings.github_api_token}"

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Fetches a single PR from ``GET /repos/{owner}/{repo}/pulls/{pr_number}``
        and returns the raw GitHub API response dict."""
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.json()

    async def list_pull_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetches all changed files for a PR across paginated API responses
        and returns a flat list of file-change dicts."""
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                response = await client.get(
                    url,
                    params={"per_page": 100, "page": page},
                    headers=self._headers,
                )
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                files.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        return files

    async def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        comments: list[dict[str, Any]],
        commit_id: str = "",
        event: str = "COMMENT",
    ) -> dict[str, Any]:
        """Create a PR review with inline (line-level) comments in one request.

        Posts to ``POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews``.
        Each entry in ``comments`` must contain ``path``, ``line`` and ``body``
        (``side`` defaults to ``"RIGHT"``, i.e. the new version of the file).
        ``body`` is the optional overall review summary.
        """
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload: dict[str, Any] = {"event": event, "comments": comments}
        if body:
            payload["body"] = body
        if commit_id:
            payload["commit_id"] = commit_id
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        sha: str = "",
        merge_method: str = "merge",
    ) -> dict[str, Any]:
        """Merge a pull request via ``PUT /repos/{owner}/{repo}/pulls/{n}/merge``.

        ``merge_method`` is one of ``"merge"``, ``"squash"``, or ``"rebase"``.
        When ``sha`` is provided, GitHub only merges if the PR head still points
        at that commit (guards against merging newer, unreviewed commits).
        Raises ``httpx.HTTPStatusError`` if the PR is not mergeable.
        """
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}/merge"
        payload: dict[str, Any] = {"merge_method": merge_method}
        if sha:
            payload["sha"] = sha
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.put(url, headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def create_issue_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        """Post a general comment on a PR (issue comment endpoint) and return
        the created comment dict."""
        url = f"{self._base}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=self._headers, json={"body": body})
            response.raise_for_status()
            return response.json()

    async def list_issue_comments(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """List the issue/PR comments via
        ``GET /repos/{owner}/{repo}/issues/{n}/comments``."""
        url = f"{self._base}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"per_page": 100}, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, list) else []

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        """Edit an existing issue/PR comment via
        ``PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}``."""
        url = f"{self._base}/repos/{owner}/{repo}/issues/comments/{comment_id}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.patch(url, headers=self._headers, json={"body": body})
            response.raise_for_status()
            return response.json()

    async def list_pull_commits(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch the commits of a PR via ``GET /repos/{owner}/{repo}/pulls/{n}/commits``
        and return the list of commit dicts (each has ``commit.message``)."""
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"per_page": 100}, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, list) else []

    async def get_readme(self, owner: str, repo: str, ref: str = "") -> str:
        """Return the raw README text via ``GET /repos/{owner}/{repo}/readme``.

        Returns an empty string if the repo has no README or it can't be read.
        """
        url = f"{self._base}/repos/{owner}/{repo}/readme"
        headers = dict(self._headers)
        headers["Accept"] = "application/vnd.github.raw"
        params = {"ref": ref} if ref else {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code >= 400:
                return ""
            return response.text

    async def get_file(self, owner: str, repo: str, path: str, ref: str = "") -> str:
        """Return the raw content of a repo file via
        ``GET /repos/{owner}/{repo}/contents/{path}`` (Accept: raw).

        Returns an empty string if the file is missing or can't be read.
        """
        url = f"{self._base}/repos/{owner}/{repo}/contents/{path}"
        headers = dict(self._headers)
        headers["Accept"] = "application/vnd.github.raw"
        params = {"ref": ref} if ref else {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code >= 400:
                return ""
            return response.text

    async def get_repo_tree(self, owner: str, repo: str, ref: str) -> list[str]:
        """Return the list of file paths in the repo via the git trees API
        (``GET /repos/{owner}/{repo}/git/trees/{ref}?recursive=1``)."""
        url = f"{self._base}/repos/{owner}/{repo}/git/trees/{ref or 'HEAD'}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=self._headers, params={"recursive": "1"})
            if response.status_code >= 400:
                return []
            data = response.json()
        tree = data.get("tree") if isinstance(data, dict) else None
        if not isinstance(tree, list):
            return []
        return [str(item.get("path") or "") for item in tree if item.get("type") == "blob"]
