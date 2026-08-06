"""Extract diffs node.

Fetches per-file diff information from the GitHub or GitLab API and
populates ``state.files`` with a list of :class:`PRFileDiff` objects.
"""
from __future__ import annotations

from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.pr_pipeline.state import PRAgentState, PRFileDiff


def _gitlab_status(item: dict) -> str:
    """Map a GitLab change dict to a canonical file status string."""
    if item.get("new_file"):
        return "added"
    if item.get("deleted_file"):
        return "removed"
    if item.get("renamed_file"):
        return "renamed"
    return "modified"


def _count_patch_churn(patch: str) -> tuple[int, int]:
    """Counts ``+`` and ``-`` lines in a unified diff patch and returns
    an ``(additions, deletions)`` tuple, ignoring ``+++``/``---`` headers."""
    additions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


class ExtractDiffsNode:
    """Fetches per-file diff information from the VCS provider API.

    Populates ``state.files`` with :class:`PRFileDiff` objects.  On API
    errors the node emits a warning event and falls back to an empty file
    list so the pipeline can continue.
    """

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Calls the GitHub or GitLab API for per-file diffs and returns the
        state with ``state.files`` populated as a list of ``PRFileDiff`` objects."""
        state.emit("stage", stage="diff", status="running")
        if state.status in {"ignored", "rejected"} or not state.metadata:
            state.emit("stage", stage="diff", status="skipped")
            return state

        owner = state.metadata.owner
        repo = state.metadata.repo
        pr_number = state.metadata.pr_number
        files: list[PRFileDiff] = []

        if state.envelope.provider == "gitlab":
            project_id = (state.envelope.payload.get("project") or {}).get("id")
            if project_id and pr_number > 0:
                client = GitLabClient()
                try:
                    remote_files = await client.list_merge_request_changes(project_id, pr_number)
                    for item in remote_files:
                        patch = (item.get("diff") or "")[:12000]
                        additions, deletions = _count_patch_churn(patch)
                        files.append(
                            PRFileDiff(
                                file_path=item.get("new_path") or item.get("old_path") or "",
                                status=_gitlab_status(item),
                                additions=additions,
                                deletions=deletions,
                                patch=patch,
                            )
                        )
                except Exception as exc:
                    state.emit("warning", stage="diff", message=f"GitLab API diff fallback: {exc}")
        elif owner and repo and pr_number > 0:
            client = GitHubClient()
            try:
                remote_files = await client.list_pull_files(owner, repo, pr_number)
                for item in remote_files:
                    files.append(
                        PRFileDiff(
                            file_path=item.get("filename", ""),
                            status=item.get("status", "modified"),
                            additions=int(item.get("additions") or 0),
                            deletions=int(item.get("deletions") or 0),
                            patch=(item.get("patch") or "")[:12000],
                        )
                    )
            except Exception as exc:
                state.emit("warning", stage="diff", message=f"GitHub API diff fallback: {exc}")

        if not files:
            # Webhook payload usually does not include per-file patch; keep empty list if unavailable.
            files = []

        state.files = files
        if state.metadata.changed_files == 0 and files:
            state.metadata.changed_files = len(files)
        if state.metadata.additions == 0 and files:
            state.metadata.additions = sum(f.additions for f in files)
        if state.metadata.deletions == 0 and files:
            state.metadata.deletions = sum(f.deletions for f in files)

        state.emit("stage", stage="diff", status="done", provider=state.envelope.provider, files=len(files))
        return state
