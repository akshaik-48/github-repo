"""Persist result node.

Final node in the pipeline.  Writes the raw webhook event and the
computed analysis result (including findings) to SQLite.
"""
from __future__ import annotations

from  import insert_analysis, insert_event, insert_findings
from  import PRAgentState


class PersistResultNode:
    """Persists the pipeline result to the database.

    Always writes the raw ``pr_events`` row (even for ignored/rejected
    events).  For accepted and completed events it also inserts a
    ``pr_analyses`` row and associated ``pr_findings`` rows.
    """

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Writes the event and analysis results to SQLite and returns the
        state with ``state.persisted = True`` and ``state.analysis_id`` set."""
        state.emit("stage", stage="persist", status="running")

        payload = state.envelope.payload
        owner = ""
        repo = ""
        pr_number = 0
        if state.metadata:
            owner = state.metadata.owner
            repo = state.metadata.repo
            pr_number = state.metadata.pr_number

        insert_event(
            provider=state.envelope.provider,
            delivery_id=state.envelope.delivery_id,
            event_type=state.envelope.event,
            action=state.envelope.action,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            payload=payload,
        )

        if state.status in {"ignored", "rejected"} or not state.metadata:
            state.persisted = True
            state.emit("stage", stage="persist", status="done", skipped_analysis=True)
            return state

        summary = (state.llm_summary or "").strip() or (
            f"PR #{state.metadata.pr_number} in {state.metadata.owner}/{state.metadata.repo} "
            f"scored {state.risk.score} ({state.risk.level})."
        )
        analysis_id = insert_analysis(
            provider=state.envelope.provider,
            owner=state.metadata.owner,
            repo=state.metadata.repo,
            pr_number=state.metadata.pr_number,
            head_sha=state.metadata.head_sha,
            base_sha=state.metadata.base_sha,
            files_changed=state.metadata.changed_files,
            additions=state.metadata.additions,
            deletions=state.metadata.deletions,
            risk_score=state.risk.score,
            risk_level=state.risk.level,
            summary=summary,
            files=[f.model_dump() for f in state.files],
            risk_factors=state.risk.factors,
            state_events=state.events,
            metadata=state.metadata.model_dump(),
            merge_readiness=state.merge_readiness.model_dump(),
        )

        insert_findings(analysis_id, [f.model_dump() for f in state.findings])

        state.analysis_id = analysis_id
        state.persisted = True
        state.status = "completed"
        state.emit("stage", stage="persist", status="done", analysis_id=analysis_id)
        return state
