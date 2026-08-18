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
from __future__ import 

import asyncio as _asyncio
import json
import re

from app.config import settings
from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.llm_agents import LLMAgent, build_llm_kwargs, select_llm_agent
from app.pr_pipeline.state import PRAgentState, RuleFinding
from app.rules_loader import load_rules


def _build_meaning_prompt(title: str, subjects: list[str]) -> str:
    """Prompt asking the LLM to judge whether the title/commits name real work."""
    commit_block = "\n".join(f"- {s}" for s in subjects) or "- (none)"
    return (
        "You are validating that a pull request's title and commit messages describe "
        "REAL, specific functionality — not vague placeholders like 'update', 'fix stuff', "
        "'wip', 'changes', 'misc', or gibberish.\n\n"
        "A title/commit is OK when it names a concrete feature, fix, or component so a "
        "reader understands what changed. It is NOT ok when it is empty, generic, a "
        "placeholder, or meaningless. Ignore any prefix like 'feat(scope):' or '[JIRA-123]' "
        "and judge the descriptive part.\n\n"
        "Respond with STRICT JSON only (no markdown, no prose) in this shape:\n"
        '{"title_ok": <bool>, "title_reason": "<short reason if not ok>", '
        '"commits": [{"subject": "<subject>", "ok": <bool>, "reason": "<short reason if not ok>"}]}\n\n'
        f"PR title: {title or '(not provided)'}\n"
        f"Commit subjects:\n{commit_block}\n"
    )


def _parse_meaning(raw: str) -> dict:
    """Best-effort JSON extraction from the meaning-check LLM response."""
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(data, dict):
            return data
    return {}


async def _run_meaning_llm(agent: LLMAgent, prompt: str) -> str:
    from litellm import acompletion

    response = await acompletion(**build_llm_kwargs(agent, prompt))
    content = response.choices[0].message.content
    return str(content or "").strip()



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
        title_cfg = rules.get("pr_title_check") or {}
        commit_cfg = rules.get("commit_message_check") or {}
        failures: list[str] = []

        title_ok = self._check_title(state, title_cfg, failures)

        # Fetch commit messages once and share them across the format and
        # meaning checks to avoid a duplicate provider round-trip.
        commit_messages: list[str] = []
        if commit_cfg.get("enabled") or commit_cfg.get("semantic_check"):
            commit_messages = await self._fetch_commit_messages(state)
        passing_subjects = self._check_commits(state, commit_cfg, failures, commit_messages)

        # The meaning check only evaluates the title/commits that PASSED the
        # format check, so a misformatted *and* vague message isn't flagged
        # twice (the format failure already tells the author to fix it).
        await self._check_meaning(
            state, title_cfg, commit_cfg, title_ok, passing_subjects, failures
        )

        state.checks_passed = not failures
        if failures:
            if settings.post_comments_enabled:
                await self._post_comment(state, failures)
            await self._publish_status(state, ok=False, failures=failures)
            state.emit("stage", stage="pr_checks", status="failed", failures=len(failures))
        else:
            await self._publish_status(state, ok=True, failures=[])
            state.emit("stage", stage="pr_checks", status="done", passed=True)
        return state

    def _check_title(self, state: PRAgentState, cfg: dict, failures: list[str]) -> bool:
        """Validate the PR title against the configured pattern.

        Returns ``True`` when the title passes (or the check is disabled) and
        ``False`` when it failed the format check.
        """
        if not cfg.get("enabled", False):
            return True
        pattern = cfg.get("pattern") or ""
        if not pattern:
            return True
        title = (state.metadata.title if state.metadata else "") or ""
        try:
            matched = bool(re.fullmatch(pattern, title.strip()))
        except re.error:
            return True  # invalid config regex -> skip rather than block
        if not matched:
            msg = cfg.get("message") or "PR title does not match the repository title policy."
            state.findings.append(
                RuleFinding(rule_id="title_check", severity=cfg.get("severity", "high"), message=msg)
            )
            failures.append(msg)
            return False
        return True

    def _check_commits(
        self, state: PRAgentState, cfg: dict, failures: list[str], messages: list[str]
    ) -> list[str]:
        """Validate each commit's subject against the configured pattern.

        Returns the de-duplicated list of subjects that PASSED the format check
        (the candidates worth running the meaning check on).
        """
        subjects: list[str] = []
        seen: set[str] = set()
        for message in messages:
            subject = (message.splitlines()[0] if message else "").strip()
            if subject and subject not in seen:
                seen.add(subject)
                subjects.append(subject)

        if not cfg.get("enabled", False):
            return subjects
        pattern = cfg.get("pattern") or ""
        if not pattern:
