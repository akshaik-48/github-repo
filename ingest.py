"""Ingest webhook node.

First node in the pipeline.  Validates the incoming event and decides
whether to continue processing (``status = "accepted"``) or short-circuit
(``status = "ignored"`` / ``"rejected"``).
"""
from __future__ import annotations
from app.pr_pipeline.state import settings

class ingest:
    """Validates and filters the incoming webhook envelope.

    Rejects events with an invalid signature, ignores non-PR/MR events,
    and ignores PR actions that do not require analysis (e.g. ``closed``).
    """

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Validates the envelope and returns the state with ``status`` set to
        ``"rejected"``, ``"ignored"``, or ``"accepted"``."""
        state.emit("stage", stage="ingest", status="running")

        if not state.envelope.signature_valid:
            state.status = "rejected"
            state.add_error("Webhook signature validation failed.")
            state.emit("stage", stage="ingest", status="rejected")
            return state

        if state.envelope.event not in {"pull_request", "merge_request"}:
            state.status = "ignored"
            state.emit("stage", stage="ingest", status="ignored", reason="non pr/mr event")
            return state

        if state.envelope.provider == "gitlab":
            allowed_actions = {"open", "update", "reopen", "opened", "synchronize", "reopened"}
        else:
            allowed_actions = {"opened", "synchronize", "reopened"}
        if state.envelope.action not in allowed_actions:
            state.status = "ignored"
            state.emit("stage", stage="ingest", status="ignored", reason="unsupported action")
            return state

        if not self._has_file_changes(state):
            state.status = "ignored"
            state.emit("stage", stage="ingest", status="ignored", reason="no file changes")
            return state

        state.status = "accepted"
        state.emit("stage", stage="ingest", status="done")
        return state

    @staticmethod
    def _has_file_changes(state: PRAgentState) -> bool:
        """Return ``True`` only when the event reflects actual file/commit
        changes, filtering out metadata-only updates (e.g. title/description
        or label edits).

        - GitLab ``update`` events fire on title/description edits too; the
          ``object_attributes.oldrev`` field is set only when the source branch
          received new commits, so we require it for updates.
        - GitHub title/body edits arrive as the ``edited`` action (already
          filtered out), while ``synchronize`` implies new commits; ``opened``
          and ``reopened`` always carry a diff.
        """
        action = state.envelope.action
        if state.envelope.provider == "gitlab" and action == "update":
            obj = state.envelope.payload.get("object_attributes") or {}
            return bool(obj.get("oldrev"))
        return True
