"""PR checks node.
Validates PR/MR hygiene before merge:

1. **Title check** -- the PR/MR title must match the configured rule.
2. **Commit check** -- every commit message must match the configured rule.

Both checks are fully **customizable per repository** via the rule set
(``pr_title_check`` and ``commit_message_check`` in the repo rules / default
rules file). Any failure records a finding, optionally posts a comment, and
sets ``state.checks_passed = False`` -- which blocks whitespace-only
auto-merge (see :class:`~app.pr_pipeline.nodes.auto_merge.AutoMergeNode`).
"""
from __future__ import annotations

import re

from app.config import settings
from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.pr_pipeline.state import PRAgentState, RuleFinding
from app.rules_loader import load_rules

class PRChecksNode:
    """Runs configurable title and commit-message validation checks."""

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Validate the PR title and commit messages against the repo's
        configurable patterns, recording findings and blocking auto-merge on
        failure."""
        state.emit("stage", stage="pr_checks", status="running")
        if state.status in {"ignored", "rejected"} or not state.metadata:
            state.emit("stage", stage="pr_checks", status="skipped")
            return state

        # Rules may already be loaded by the rules node; fall back to loading
        # them directly so this node is order-independent.
        rules = state.rules or load_rules(state.metadata.owner, state.metadata.repo)
        failures: list[str] = []

        self._check_title(state, rules.get("pr_title_check") or {}, failures)
        await self._check_commits(state, rules.get("commit_message_check") or {}, failures)

        state.checks_passed = not failures
        if failures:
            if settings.post_comments_enabled:
                await self._post_comment(state, failures)
            state.emit("stage", stage="pr_checks", status="failed", failures=len(failures))
        else:
            state.emit("stage", stage="pr_checks", status="done", passed=True)
        return state

    def _check_title(self, state: PRAgentState, cfg: dict, failures: list[str]) -> None:
        """Validate the PR title against the configured pattern."""
        if not cfg.get("enabled", False):
            return
        pattern = cfg.get("pattern") or ""
        if not pattern:
            return
        title = (state.metadata.title if state.metadata else "") or ""
        try:
            matched = bool(re.search(pattern, title))
        except re.error:
            return  # invalid config regex -> skip rather than block
        if not matched:
            msg = cfg.get("message") or "PR title does not match the repository title policy."
            state.findings.append(
                RuleFinding(rule_id="title_check", severity=cfg.get("severity", "high"), message=msg)
            )
            failures.append(msg)

    async def _check_commits(self, state: PRAgentState, cfg: dict, failures: list[str]) -> None:
        """Validate each commit's subject line against the configured pattern."""
        if not cfg.get("enabled", False):
            return
        pattern = cfg.get("pattern") or ""
        if not pattern:
            return
        try:
            regex = re.compile(pattern)
        except re.error:
            return  # invalid config regex -> skip rather than block

        messages = await self._fetch_commit_messages(state)
        if not messages:
            # Could not retrieve commit messages (API down + no payload fallback).
            # Treat as an indeterminate result — do NOT silently pass validation.
            failures.append("Commit messages could not be retrieved; cannot validate commit policy.")
            return
        bad_subjects = []
        for message in messages:
            subject = (message.splitlines()[0] if message else "").strip()
            if not regex.search(subject):
                bad_subjects.append(subject)

        if bad_subjects:
            base = cfg.get("message") or "Commit message does not match the repository commit policy."
            severity = cfg.get("severity", "medium")
            for subject in bad_subjects[:10]:
                state.findings.append(
                    RuleFinding(
                        rule_id="commit_check",
                        severity=severity,
                        message=f"{base} Offending: '{subject}'",
                    )
                )
            failures.append(f"{base} ({len(bad_subjects)} commit(s) failed)")

    async def _fetch_commit_messages(self, state: PRAgentState) -> list[str]:
        """Return the list of commit messages for the PR/MR, falling back to the
        webhook payload's last commit when the API is unavailable."""
        metadata = state.metadata
        assert metadata is not None
        try:
            if state.envelope.provider == "github":
                commits = await GitHubClient().list_pull_commits(
                    metadata.owner, metadata.repo, metadata.pr_number
                )
                return [str((c.get("commit") or {}).get("message") or "") for c in commits]
            if state.envelope.provider == "gitlab":
                project_id = (state.envelope.payload.get("project") or {}).get("id")
                if project_id:
                    commits = await GitLabClient().list_merge_request_commits(
                        project_id, metadata.pr_number
                    )
                    return [str(c.get("message") or c.get("title") or "") for c in commits]
        except Exception as exc:
            state.emit("warning", stage="pr_checks", message=f"commit fetch failed: {exc}")

        # Fallback: GitLab includes the last commit in the webhook payload.
        obj = state.envelope.payload.get("object_attributes") or {}
        last = (obj.get("last_commit") or {}).get("message")
        return [str(last)] if last else []

    async def _post_comment(self, state: PRAgentState, failures: list[str]) -> None:
        """Best-effort comment listing the failed checks; never raises."""
        metadata = state.metadata
        if not metadata or metadata.pr_number <= 0:
            return
        body = (
            "## 🤖 PR Agent — checks failed\n\n"
            + "\n".join(f"- {item}" for item in failures)
            + "\n\nPlease resolve the issues above before merging.\n\n"

        )
        try:
            if state.envelope.provider == "github":
                await GitHubClient().create_issue_comment(
                    metadata.owner, metadata.repo, metadata.pr_number, body
                )
            elif state.envelope.provider == "gitlab":
                project_id = (state.envelope.payload.get("project") or {}).get("id")
                if project_id:
                    await GitLabClient().create_merge_request_note(
                        project_id, metadata.pr_number, body
                    )
        except Exception as exc:
            state.emit("warning", stage="pr_checks", message=f"check comment failed: {exc}")
