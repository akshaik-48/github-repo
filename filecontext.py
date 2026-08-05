"""Changed-file context extraction.

To review "what the PR/MR changes vs. what already exists", the LLM needs to see
the *current* content of the files being modified -- not just the diff hunks.
This module fetches the full head-ref content of the most-changed files (capped
by :mod:`app.config` settings) so the reviewer can reason about surrounding
code: imports, sibling functions, class definitions and call sites.

Fetching is best-effort and per-PR (not cached): any failure yields an empty
string so the review continues normally.
"""
from __future__ import annotations

from app.config import settings
from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.pr_pipeline.state import PRAgentState

# Files whose full content is not useful to a reviewer (or too large / binary).
_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2", ".ttf",
)


def _rank_files(state: PRAgentState) -> list[str]:
    """Return the changed file paths ranked by churn (additions+deletions),
    excluding deleted and non-reviewable files, capped by config."""
    candidates = []
    for file in state.files:
        if file.status == "removed":
            continue
        path = file.file_path
        if not path or path.lower().endswith(_SKIP_SUFFIXES):
            continue
        candidates.append((file.additions + file.deletions, path))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[: settings.review_context_max_files]]


def _make_file_fetcher(state: PRAgentState, ref: str):
    """Return an async ``fetch(path) -> str`` for the active provider, or
    ``None`` when file fetching isn't available."""
    metadata = state.metadata
    if metadata is None:
        return None
    if state.envelope.provider == "github":
        client = GitHubClient()

        async def _gh(path: str) -> str:
            return await client.get_file(metadata.owner, metadata.repo, path, ref)

        return _gh
    if state.envelope.provider == "gitlab":
        project_id = (state.envelope.payload.get("project") or {}).get("id")
        if not project_id:
            return None
        client = GitLabClient()

        async def _gl(path: str) -> str:
            return await client.get_file_raw(project_id, path, ref)

        return _gl
    return None


async def build_changed_file_context(state: PRAgentState) -> str:
    """Fetch and format the current content of the top changed files.

    Returns a markdown block (one section per file, each truncated to
    ``review_context_max_file_chars``) or an empty string when disabled,
    unavailable or on any failure.
    """
    if not settings.review_context_enabled or not state.metadata:
        return ""

    ref = state.metadata.head_branch or state.metadata.head_sha or "HEAD"
    fetch_file = _make_file_fetcher(state, ref)
    if fetch_file is None:
        return ""

    max_chars = settings.review_context_max_file_chars
    blocks: list[str] = []
    for path in _rank_files(state):
        try:
            content = await fetch_file(path)
        except Exception as exc:  # best-effort; never break the review
            state.emit("warning", stage="review_comments", message=f"file context fetch failed for {path}: {exc}")
            continue
        if not content.strip():
            continue
        truncated = content[:max_chars]
        if len(content) > max_chars:
            truncated += "\n... [truncated]"
        blocks.append(f"### FILE: {path}\n{truncated}")

    return "\n\n".join(blocks).strip()
