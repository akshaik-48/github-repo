"""GitLab REST API client.

Thin async wrapper around the GitLab API used by the pipeline to fetch
merge request metadata and per-file diff information.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

from app.config import settings


class GitLabClient:
    """Async HTTP client for the GitLab REST API.

    Authentication is optional; when ``settings.gitlab_api_token`` is set,
    requests are sent with a ``Bearer`` token header.
    """

    def __init__(self) -> None:
        """Initialise the client with the base URL and auth headers from settings."""
        self._base = settings.gitlab_api_base_url.rstrip("/")
        self._headers = {
            "Accept": "application/json",
        }
        if settings.gitlab_api_token:
            self._headers["Authorization"] = f"Bearer {settings.gitlab_api_token}"

    async def get_merge_request(self, project_id: int | str, mr_iid: int) -> dict[str, Any]:
        """Fetches a single MR from the GitLab API and returns the raw
        response dict."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.json()

    async def list_merge_request_changes(self, project_id: int | str, mr_iid: int) -> list[dict[str, Any]]:
        """Fetches all file changes for a merge request via the diffs endpoint
        (paginated) and returns a list of change dicts.

        Falls back to the /changes endpoint when the diffs endpoint is
        unavailable (404) or errors server-side (5xx, seen on some self-hosted
        GitLab versions), and warns when the overflow flag is set (diff
        truncated).
        """
        project = quote_plus(str(project_id))
        all_changes: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/diffs"
                response = await client.get(
                    url,
                    headers=self._headers,
                    params={"page": page, "per_page": 100},
                )
                if response.status_code == 404 or response.status_code >= 500:
                    # /diffs missing (old GitLab) or failing server-side; fall
                    # back to the legacy /changes endpoint.
                    return await self._list_changes_fallback(client, project, mr_iid)
                response.raise_for_status()
                page_data = response.json()
                if not isinstance(page_data, list):
                    break
                all_changes.extend(page_data)
                if len(page_data) < 100:
                    break
                page += 1
        return all_changes

    async def _list_changes_fallback(
        self, client: httpx.AsyncClient, project: str, mr_iid: int
    ) -> list[dict[str, Any]]:
        """Fetch MR file changes via the legacy
        ``GET /merge_requests/{iid}/changes`` endpoint and return the change
        list. Warns when GitLab reports the diff was truncated (overflow)."""
        fb_url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/changes"
        fb_response = await client.get(fb_url, headers=self._headers)
        fb_response.raise_for_status()
        payload = fb_response.json()
        if isinstance(payload, dict) and payload.get("overflow"):
            import logging
            logging.getLogger("pr_agent.gitlab").warning(
                "MR !%s diff truncated by GitLab (overflow=true); "
                "review will cover partial file list.",
                mr_iid,
            )
        changes = payload.get("changes") if isinstance(payload, dict) else None
        return changes if isinstance(changes, list) else []

    async def create_merge_request_note(self, project_id: int | str, mr_iid: int, body: str) -> dict[str, Any]:
        """Posts a general (non-inline) note/comment on a merge request and
        returns the created note dict."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=self._headers, json={"body": body})
            response.raise_for_status()
            return response.json()

    async def list_merge_request_notes(self, project_id: int | str, mr_iid: int) -> list[dict[str, Any]]:
        """List the notes/comments on a merge request via
        ``GET /projects/{id}/merge_requests/{iid}/notes``."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"per_page": 100}, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, list) else []

    async def update_merge_request_note(
        self, project_id: int | str, mr_iid: int, note_id: int, body: str
    ) -> dict[str, Any]:
        """Edit an existing merge request note via
        ``PUT /projects/{id}/merge_requests/{iid}/notes/{note_id}``."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/notes/{note_id}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.put(url, headers=self._headers, json={"body": body})
            response.raise_for_status()
            return response.json()

    async def merge_merge_request(
        self, project_id: int | str, mr_iid: int, *, squash: bool = False
    ) -> dict[str, Any]:
        """Merge a merge request via ``PUT /projects/{id}/merge_requests/{iid}/merge``.

        Raises ``httpx.HTTPStatusError`` if the MR is not mergeable (e.g. open
        discussions, failing pipeline, or merge conflicts).
        """
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/merge"
        payload: dict[str, Any] = {}
        if squash:
            payload["squash"] = True
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.put(url, headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def list_merge_request_commits(self, project_id: int | str, mr_iid: int) -> list[dict[str, Any]]:
        """Fetch the commits of a merge request via
        ``GET /projects/{id}/merge_requests/{iid}/commits`` and return the list
        of commit dicts (each has ``message`` / ``title``)."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/commits"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"per_page": 100}, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, list) else []

    async def get_file_raw(self, project_id: int | str, file_path: str, ref: str) -> str:
        """Return the raw content of a repo file via
        ``GET /projects/{id}/repository/files/{path}/raw?ref={ref}``.

        Returns an empty string if the file is missing or can't be read.
        """
        project = quote_plus(str(project_id))
        path = quote_plus(file_path)
        url = f"{self._base}/projects/{project}/repository/files/{path}/raw"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=self._headers, params={"ref": ref or "HEAD"})
            if response.status_code >= 400:
                return ""
            return response.text

    async def get_repo_tree(self, project_id: int | str, ref: str) -> list[str]:
        """Return the list of file paths in the repo via
        ``GET /projects/{id}/repository/tree?recursive=true``."""
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/repository/tree"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                url,
                headers=self._headers,
                params={"recursive": "true", "per_page": 100, "ref": ref or "HEAD"},
            )
            if response.status_code >= 400:
                return []
            data = response.json()
        if not isinstance(data, list):
            return []
        return [str(item.get("path") or "") for item in data if item.get("type") == "blob"]

    async def create_merge_request_discussion(
        self,
        project_id: int | str,
        mr_iid: int,
        body: str,
        *,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        new_path: str,
        new_line: int,
    ) -> dict[str, Any]:
        """Posts an inline discussion anchored to a specific new-file line of
        the MR diff and returns the created discussion dict.

        Raises ``httpx.HTTPStatusError`` if GitLab rejects the position (e.g.
        the line is not part of the diff); callers should handle this and fall
        back to a general note.
        """
        project = quote_plus(str(project_id))
        url = f"{self._base}/projects/{project}/merge_requests/{mr_iid}/discussions"
        data = {
            "body": body,
            "position[base_sha]": base_sha,
            "position[start_sha]": start_sha,
            "position[head_sha]": head_sha,
            "position[position_type]": "text",
            "position[new_path]": new_path,
            "position[new_line]": str(new_line),
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=self._headers, data=data)
            response.raise_for_status()
            return response.json()
