"""Pydantic response models for the PR Agent API.

These schemas define the JSON shapes returned by the ``/webhooks`` and
``/pr-analysis`` endpoints.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WebhookAck(BaseModel):
    """Acknowledgement returned immediately after a webhook is accepted.

    The pipeline runs asynchronously after this response is sent.
    """

    accepted: bool
    delivery_id: str
    event: str
    action: str


class AnalysisFindingResponse(BaseModel):
    """A single rule finding surfaced during risk analysis."""

    rule_id: str
    severity: str
    message: str
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    evidence: dict[str, Any] = Field(default_factory=dict)


class MergeReadinessResponse(BaseModel):
    """Merge readiness assessment attached to an analysis result."""

    score: int
    recommendation: str  # MERGE_READY | REVIEW_REQUIRED | MERGE_BLOCKED
    blocking_findings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """Full analysis result returned by the ``/pr-analysis`` endpoints."""

    id: int
    provider: str = "github"
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    base_sha: str
    files_changed: int
    additions: int
    deletions: int
    risk_score: int
    risk_level: str
    summary: str
    created_at: datetime
    findings: list[AnalysisFindingResponse] = Field(default_factory=list)
    merge_readiness: MergeReadinessResponse | None = None


class RepoContextUpsertRequest(BaseModel):
    context_type: str
    context_key: str
    content: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    created_by: str = "system"


class RepoContextEntryResponse(BaseModel):
    id: int
    context_type: str
    context_key: str
    content: dict[str, Any] = Field(default_factory=dict)
    source: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class ReviewFindingHistoryResponse(BaseModel):
    id: int
    pull_request_id: int
    analysis_id: int
    rule_id: str
    severity: str
    message: str
    file_path: str
    line_start: int
    line_end: int
    evidence: dict[str, Any] = Field(default_factory=dict)
    found_at: datetime


class RepoRulesUpdateRequest(BaseModel):
    rules: dict[str, Any] = Field(default_factory=dict)
    changed_by: str = "system"
    reason: str = ""


class RepoRuleAuditEntryResponse(BaseModel):
    id: int
    config_scope: str
    config_key: str
    old_value: dict[str, Any] = Field(default_factory=dict)
    new_value: dict[str, Any] = Field(default_factory=dict)
    changed_by: str
    changed_at: datetime
    reason: str


class PostCommentsResponse(BaseModel):
    """Result of a manual post-comments request for an existing analysis."""

    analysis_id: int
    provider: str
    owner: str
    repo: str
    pr_number: int
    posted: bool
    rule_comments: int = 0
    llm_comments: int = 0
    detail: str = ""


class PipelineEventResponse(BaseModel):
    seq: int
    event_type: str
    stage: str | None = None
    status: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PipelineEventsResponse(BaseModel):
    provider: str = "github"
    delivery_id: str
    owner: str
    repo: str
    pr_number: int
    final_status: str = ""
    events: list[PipelineEventResponse] = Field(default_factory=list)


class RunSummaryResponse(BaseModel):
    provider: str = "github"
    delivery_id: str
    owner: str
    repo: str
    pr_number: int
    action: str
    event_type: str
    received_at: datetime
    final_status: str = ""
    analysis_id: int | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    event_count: int = 0
    fallback_count: int = 0
    error_count: int = 0
