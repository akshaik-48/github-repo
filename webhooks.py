"""Webhook ingestion router.

Exposes two endpoints:
- ``POST /webhooks/github``  -- receives GitHub webhook deliveries.
- ``POST /webhooks/gitlab``  -- receives GitLab webhook deliveries.

Both endpoints validate the incoming request, build a
:class:`~app.pr_pipeline.state.PRWebhookEnvelope`, fire the pipeline as a
background task, and immediately return a :class:`~app.schemas.WebhookAck`.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.pr_pipeline.graph import run_auto_merge, run_pr_pipeline, run_review_comments
from app.pr_pipeline.state import PRAgentState, PRWebhookEnvelope
from app.schemas import WebhookAck
from app.config import settings
from app.database import insert_pipeline_events

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Strong references to background tasks prevent GC from cancelling them mid-run.
_background_tasks: set[asyncio.Task] = set()


def _validate_signature(secret: str, body: bytes, signature_header: str) -> bool:
    """Verifies the HMAC-SHA256 ``X-Hub-Signature-256`` header against the
    raw body and secret, returning ``True`` on match (or when no secret is set)."""
    if not secret:
        return True
    if not signature_header.startswith("sha256="):
        return False
    their_sig = signature_header.split("=", 1)[1]
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, their_sig)


def _validate_gitlab_token(secret: str, token_header: str) -> bool:
    """Verify a GitLab ``X-Gitlab-Token`` shared-secret header.

    Returns ``True`` when *secret* is empty (token checking disabled).
    """
    if not secret:
        return True
    return hmac.compare_digest(secret, token_header or "")


async def _process(envelope: PRWebhookEnvelope) -> None:
    """Background task: wrap the envelope in state, run the pipeline, then run
    the review-comments step independently.

    Review comments run in their own error-isolated step *after* the pipeline,
    so review feedback is still produced/posted even if the pipeline fails. The
    pipeline event trail is always persisted afterwards (even if a step raises)
    so the per-stage status is queryable via ``/pr-analysis/.../events``.
    """
    state = PRAgentState(envelope=envelope)
    try:
        try:
            await run_pr_pipeline(state)
        except Exception as exc:
            state.add_error(f"pipeline failed: {exc}")
        try:
            await run_auto_merge(state)
        except Exception as exc:
            state.add_error(f"auto-merge failed: {exc}")
        if not state.merged:
            try:
                await run_review_comments(state)
            except Exception as exc:
                state.add_error(f"review comments failed: {exc}")
    finally:
        metadata = state.metadata
        insert_pipeline_events(
            provider=envelope.provider,
            delivery_id=envelope.delivery_id,
            owner=metadata.owner if metadata else "",
            repo=metadata.repo if metadata else "",
            pr_number=metadata.pr_number if metadata else 0,
            final_status=state.status,
            events=state.events,
        )


@router.post("/github", response_model=WebhookAck)
async def github_webhook(request: Request) -> WebhookAck:
    """Accept a GitHub webhook delivery and queue it for async processing.

    Validates required headers (``X-GitHub-Delivery``, ``X-GitHub-Event``)
    and verifies the HMAC signature when a secret is configured.  The
    pipeline runs in the background; this endpoint always returns promptly.
    """
    body = await request.body()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    event_type = request.headers.get("X-GitHub-Event", "")
    signature = request.headers.get("X-Hub-Signature-256", "")
    action = str(payload.get("action") or "")

    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header.")
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header.")

    signature_valid = _validate_signature(settings.github_webhook_secret, body, signature)

    envelope = PRWebhookEnvelope(
        provider="github",
        delivery_id=delivery_id,
        event=event_type,
        action=action,
        signature_valid=signature_valid,
        received_at=datetime.now(timezone.utc),
        payload=payload,
    )

    task = asyncio.create_task(_process(envelope))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return WebhookAck(
        accepted=True,
        delivery_id=delivery_id,
        event=event_type,
        action=action,
    )


@router.post("/gitlab", response_model=WebhookAck)
async def gitlab_webhook(request: Request) -> WebhookAck:
    """Accept a GitLab webhook delivery and queue it for async processing.

    Validates the ``X-Gitlab-Event`` header and verifies the shared token
    when one is configured.  Falls back to a generated UUID for the delivery
    ID when GitLab does not provide one.  The pipeline runs in the background.
    """
    body = await request.body()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

    delivery_id = (
        request.headers.get("X-Gitlab-Event-UUID", "")
        or request.headers.get("X-Request-Id", "")
        or str(uuid4())
    )
    event_header = request.headers.get("X-Gitlab-Event", "")
    token_header = request.headers.get("X-Gitlab-Token", "")
    action = str((payload.get("object_attributes") or {}).get("action") or "")

    if not event_header:
        raise HTTPException(status_code=400, detail="Missing X-Gitlab-Event header.")

    event_type = "merge_request" if event_header == "Merge Request Hook" else event_header.lower().replace(" ", "_")
    signature_valid = _validate_gitlab_token(settings.gitlab_webhook_secret, token_header)

    envelope = PRWebhookEnvelope(
        provider="gitlab",
        delivery_id=delivery_id,
        event=event_type,
        action=action,
        signature_valid=signature_valid,
        received_at=datetime.now(timezone.utc),
        payload=payload,
    )

    task = asyncio.create_task(_process(envelope))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return WebhookAck(
        accepted=True,
        delivery_id=delivery_id,
        event=event_type,
        action=action,
    )
