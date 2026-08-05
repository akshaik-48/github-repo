"""Pipeline state models.

All Pydantic models that flow through the PR analysis pipeline are defined
here.  A single :class:`PRAgentState` instance is created per webhook
delivery and mutated by each pipeline node in turn.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("pr_agent.pipeline")


class PRWebhookEnvelope(BaseModel):
    """Raw webhook delivery metadata, provider-agnostic.

    Wraps the incoming request headers and payload before any parsing.
    ``signature_valid`` is set by the router based on HMAC / token validation.
    """
    provider: str = "github"
    delivery_id: str
    event: str
    action: str
    signature_valid: bool
    received_at: datetime
    payload: dict[str, Any]


class PRMetadata(BaseModel):
    """Structured pull/merge request metadata collected from the provider API."""
    owner: str
    repo: str
    pr_number: int
    title: str = ""
    body: str = ""
    author: str = ""
    base_branch: str = ""
    head_branch: str = ""
    base_sha: str = ""
    head_sha: str = ""
    target_branch_sha: str = ""
    commits: int = 0
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    labels: list[str] = Field(default_factory=list)
    is_draft: bool = False
    html_url: str = ""


class PRFileDiff(BaseModel):
    """Diff summary for a single file changed in the pull/merge request."""
    file_path: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: str = ""


class RuleFinding(BaseModel):
    """A single rule violation detected during risk analysis."""
    rule_id: str
    severity: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0


class RiskScore(BaseModel):
    """Computed risk score and its contributing factors."""
    score: int = 0
    level: str = "low"
    factors: list[dict[str, Any]] = Field(default_factory=list)


class ReviewComment(BaseModel):
    """A single review comment to be shown/posted for the pull/merge request."""
    source: str = "rule"  # "rule" (deterministic) or "llm" (narrative)
    rule_id: str = ""
    severity: str = "info"
    message: str
    file_path: str = ""
    line: int = 0
    posted: bool = False


class MergeReadiness(BaseModel):
    """Merge readiness assessment produced by MergeReadinessNode."""
    score: int = 0                    # 0–100, higher = safer to merge
    recommendation: str = "UNKNOWN"   # MERGE_READY | REVIEW_REQUIRED | MERGE_BLOCKED
    blocking_findings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    posted: bool = False


class PRAgentState(BaseModel):
    """Shared mutable state object that flows through every pipeline node.

    Created once per webhook delivery.  Each node reads from and writes to
    this object, progressively enriching it until :class:`PersistResultNode`
    saves the final result to the database.

    Key lifecycle fields:
    - ``status``: tracks overall processing state
      (``"received"`` → ``"accepted"`` / ``"ignored"`` / ``"rejected"`` → ``"completed"``).
    - ``events``: append-only structured log of stage transitions.
    - ``errors``: non-fatal error messages accumulated during processing.
    """
    envelope: PRWebhookEnvelope
    metadata: PRMetadata | None = None
    files: list[PRFileDiff] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)
    findings: list[RuleFinding] = Field(default_factory=list)
    risk: RiskScore = Field(default_factory=RiskScore)
    review_comments: list[ReviewComment] = Field(default_factory=list)
    analysis_id: int | None = None
    persisted: bool = False
    status: str = "received"
    change_class: str = ""
    merged: bool = False
    checks_passed: bool = False
    llm_summary: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    merge_readiness: MergeReadiness = Field(default_factory=MergeReadiness)
    errors: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)

    def emit(self, event_type: str, **kwargs: Any) -> None:
        """Append a structured event to the events log and log it for live
        pipeline visibility on the server console."""
        self.events.append({"type": event_type, **kwargs})
        stage = kwargs.get("stage", event_type)
        status = kwargs.get("status", "")
        extra = " ".join(
            f"{k}={v}" for k, v in kwargs.items() if k not in {"stage", "status"}
        )
        delivery = self.envelope.delivery_id[:8] if self.envelope else "--------"
        logger.info("[%s] %s: %s %s", delivery, stage, status, extra)

    def add_error(self, message: str) -> None:
        """Record a non-fatal error message and emit a corresponding event."""
        self.errors.append(message)
        logger.warning("[%s] error: %s", self.envelope.delivery_id[:8] if self.envelope else "--------", message)
        self.emit("error", message=message)
