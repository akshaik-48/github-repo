"""Calculate risk node.

Invokes the scoring engine to produce a numeric risk score, level, and
list of rule findings for the pull/merge request.
"""
from __future__ import annotations
from app.pr_pipeline.state import PRAgentState, RiskScore
from app.scoring import calculate_risk


class CalculateRiskNode:
    """Computes the risk score for the PR using the loaded rules.

    Delegates to :func:`~app.scoring.calculate_risk` and stores the
    results in ``state.risk`` and ``state.findings``.
    """

    async def run(self, state: PRAgentState) -> PRAgentState:
        """Runs the scoring engine and returns the state with ``state.risk``
        and ``state.findings`` populated."""
        state.emit("stage", stage="risk", status="running")
        if state.status in {"ignored", "rejected"} or not state.metadata:
            state.emit("stage", stage="risk", status="skipped")
            return state

        score, level, factors, findings = calculate_risk(state.metadata, state.files, state.rules)
        state.risk = RiskScore(score=score, level=level, factors=factors)
        state.findings = findings
        state.emit("stage", stage="risk", status="done", score=score, level=level)
        return state
