"""PostgreSQL persistence layer.

Provides schema initialisation and CRUD helpers for the core tables:
- ``pr_events``          -- raw webhook delivery records.
- ``pr_analyses``        -- computed risk analysis results.
- ``pr_findings``        -- individual rule findings linked to an analysis.
- ``repo_rules``         -- per-repository rule overrides.
- ``pr_pipeline_events`` -- per-stage pipeline execution trail (status/telemetry).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from  import Any
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.config import settings

_ENGINE: Engine | None = None

def _get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    return _ENGINE

def _run_script(engine: Engine, script_text: str) -> None:
    statements = [chunk.strip() for chunk in script_text.split(";") if chunk.strip()]
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)

def _apply_migrations() -> None:
    migrations_path = Path(__file__).resolve().parent / "migrations"
    engine = _get_engine()

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied_rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    applied = {str(row[0]) for row in applied_rows}

    if not migrations_path.exists():
        return

    migration_files = sorted(path for path in migrations_path.glob("*.sql") if path.is_file())
    for migration in migration_files:
        version = migration.stem
        if version in applied:
            continue
        script = migration.read_text(encoding="utf-8")
        _run_script(engine, script)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": version},
            )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _json_load(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _upsert_repository(owner: str, repo: str, provider: str = "github") -> int:
    full_name = f"{owner}/{repo}".strip("/")
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO repositories(provider, owner, name, full_name, created_at, updated_at)
                VALUES (:provider, :owner, :name, :full_name, NOW(), NOW())
                ON CONFLICT (provider, owner, name)
                DO UPDATE SET updated_at = NOW(), full_name = EXCLUDED.full_name
                RETURNING id
                """
            ),
            {
                "provider": provider,
                "owner": owner,
                "name": repo,
                "full_name": full_name,
            },
        ).fetchone()
    return int(row[0])


def _upsert_pull_request(
    repository_id: int,
    pr_number: int,
    head_sha: str,
    base_sha: str,
    title: str = "",
    body: str = "",
    author: str = "",
    state: str = "open",
) -> int:
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO pull_requests(
                    repository_id, pr_number, title, body, author, base_sha, head_sha,
                    state, first_seen_at, last_seen_at, created_at, updated_at
                )
                VALUES (
                    :repository_id, :pr_number, :title, :body, :author, :base_sha, :head_sha,
                    :state, NOW(), NOW(), NOW(), NOW()
                )
                ON CONFLICT (repository_id, pr_number)
                DO UPDATE SET
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), pull_requests.title),
                    body = COALESCE(NULLIF(EXCLUDED.body, ''), pull_requests.body),
                    author = COALESCE(NULLIF(EXCLUDED.author, ''), pull_requests.author),
                    base_sha = COALESCE(NULLIF(EXCLUDED.base_sha, ''), pull_requests.base_sha),
                    head_sha = COALESCE(NULLIF(EXCLUDED.head_sha, ''), pull_requests.head_sha),
                    state = EXCLUDED.state,
                    last_seen_at = NOW(),
                    updated_at = NOW()
                RETURNING id
                """
            ),
            {
                "repository_id": repository_id,
                "pr_number": pr_number,
                "title": title,
                "body": body,
                "author": author,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "state": state,
            },
        ).fetchone()
    return int(row[0])


def _insert_analysis_events(analysis_id: int, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analysis_events(analysis_id, event_type, stage, status, details_json, created_at)
                VALUES (:analysis_id, :event_type, :stage, :status, CAST(:details_json AS JSONB), NOW())
                """
            ),
            [
                {
                    "analysis_id": analysis_id,
                    "event_type": str(event.get("type") or "stage"),
                    "stage": str(event.get("stage") or ""),
                    "status": str(event.get("status") or ""),
                    "details_json": _json_dump(event),
                }
                for event in events
            ],
        )


def _insert_finding_history(
    repository_id: int,
    pull_request_id: int,
    analysis_id: int,
    finding: dict[str, Any],
) -> None:
    fingerprint_material = "|".join(
        [
            str(finding.get("rule_id") or ""),
            str(finding.get("severity") or ""),
            str(finding.get("message") or ""),
            str(finding.get("file_path") or ""),
            str(int(finding.get("line_start") or 0)),
            str(int(finding.get("line_end") or 0)),
        ]
    )
    fingerprint = _hash_text(fingerprint_material)

    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO review_findings_history(
                    repository_id,
                    pull_request_id,
                    analysis_id,
                    fingerprint,
                    rule_id,
                    severity,
                    message,
                    file_path,
                    line_start,
                    line_end,
                    evidence_json,
                    found_at
                ) VALUES (
                    :repository_id,
                    :pull_request_id,
                    :analysis_id,
                    :fingerprint,
                    :rule_id,
                    :severity,
                    :message,
                    :file_path,
                    :line_start,
                    :line_end,
                    CAST(:evidence_json AS JSONB),
                    NOW()
                )
                ON CONFLICT (repository_id, fingerprint)
                DO UPDATE SET
                    analysis_id = EXCLUDED.analysis_id,
                    pull_request_id = EXCLUDED.pull_request_id,
                    severity = EXCLUDED.severity,
                    message = EXCLUDED.message,
                    evidence_json = EXCLUDED.evidence_json,
                    found_at = NOW()
                """
            ),
            {
                "repository_id": repository_id,
                "pull_request_id": pull_request_id,
                "analysis_id": analysis_id,
                "fingerprint": fingerprint,
                "rule_id": str(finding.get("rule_id") or ""),
                "severity": str(finding.get("severity") or "medium"),
                "message": str(finding.get("message") or ""),
                "file_path": str(finding.get("file_path") or ""),
                "line_start": int(finding.get("line_start") or 0),
                "line_end": int(finding.get("line_end") or 0),
                "evidence_json": _json_dump(finding.get("evidence") or {}),
            },
        )


def cleanup_old_records() -> None:
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pr_events
                SET raw_payload_json = NULL,
                    payload_redacted_at = NOW()
                WHERE raw_payload_json IS NOT NULL
                  AND received_at < NOW() - (:retention_days * INTERVAL '1 day')
                """
            ),
            {"retention_days": settings.webhook_payload_retention_days},
        )
        conn.execute(
            text(
                """
                DELETE FROM analysis_events
                WHERE created_at < NOW() - (:retention_days * INTERVAL '1 day')
                """
            ),
            {"retention_days": settings.analysis_log_retention_days},
        )
        conn.execute(
            text(
                """
                DELETE FROM ai_response_cache
                WHERE expires_at IS NOT NULL AND expires_at < NOW()
                """
            )
        )
        conn.execute(
            text(
                """
                DELETE FROM prompt_cache
                WHERE (expires_at IS NOT NULL AND expires_at < NOW())
                   OR (created_at < NOW() - (:retention_days * INTERVAL '1 day'))
                """
            ),
            {"retention_days": settings.ai_cache_retention_days},
        )


def _ensure_pipeline_events_table() -> None:
    with _get_engine().begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS pr_pipeline_events (
                id BIGSERIAL PRIMARY KEY,
                provider TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                owner TEXT NOT NULL DEFAULT '',
                repo TEXT NOT NULL DEFAULT '',
                pr_number INTEGER NOT NULL DEFAULT 0,
                final_status TEXT NOT NULL DEFAULT '',
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL DEFAULT '',
                stage TEXT,
                status TEXT,
                detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(delivery_id, seq)
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_pr_pipeline_events_delivery ON pr_pipeline_events(delivery_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_pr_pipeline_events_repo_pr ON pr_pipeline_events(provider, owner, repo, pr_number)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_pr_pipeline_events_created_at ON pr_pipeline_events(created_at)"
        )

def init_db() -> None:
    _apply_migrations()
    _ensure_pipeline_events_table()
    cleanup_old_records()


def insert_pipeline_events(
    provider: str,
    delivery_id: str,
    owner: str,
    repo: str,
    pr_number: int,
    final_status: str,
    events: list[dict[str, Any]],
) -> None:
    _ensure_pipeline_events_table()
    normalized_events = events or [{"type": "stage", "stage": "ingest", "status": final_status or "done"}]

    with _get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM pr_pipeline_events WHERE delivery_id = :delivery_id"),
            {"delivery_id": delivery_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO pr_pipeline_events(
                    provider,
                    delivery_id,
                    owner,
                    repo,
                    pr_number,
                    final_status,
                    seq,
                    event_type,
                    stage,
                    status,
                    detail_json,
                    created_at
                ) VALUES (
                    :provider,
                    :delivery_id,
                    :owner,
                    :repo,
                    :pr_number,
                    :final_status,
                    :seq,
                    :event_type,
                    :stage,
                    :status,
                    CAST(:detail_json AS JSONB),
                    NOW()
                )
                """
            ),
            [
                {
                    "provider": provider,
                    "delivery_id": delivery_id,
                    "owner": owner,
                    "repo": repo,
                    "pr_number": pr_number,
                    "final_status": final_status,
                    "seq": idx,
                    "event_type": str(event.get("type") or "stage"),
                    "stage": str(event.get("stage") or "") or None,
                    "status": str(event.get("status") or "") or None,
                    "detail_json": _json_dump(event),
                }
                for idx, event in enumerate(normalized_events, start=1)
            ],
        )


def insert_event(
    delivery_id: str,
    event_type: str,
    action: str,
    owner: str,
    repo: str,
    pr_number: int,
    payload: dict[str, Any],
    provider: str = "github",
) -> None:
    repository_id = None
    pull_request_id = None
    if owner and repo:
        repository_id = _upsert_repository(owner, repo, provider)
        if pr_number > 0:
            pull_request_id = _upsert_pull_request(
                repository_id=repository_id,
                pr_number=pr_number,
                head_sha="",
                base_sha="",
                state="open",
            )

    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO pr_events(
                    delivery_id,
                    provider,
                    event_type,
                    action,
                    repository_id,
                    pull_request_id,
                    owner,
                    repo,
                    pr_number,
                    received_at,
                    raw_payload_json
                ) VALUES (
                    :delivery_id,
                    :provider,
                    :event_type,
                    :action,
                    :repository_id,
                    :pull_request_id,
                    :owner,
                    :repo,
                    :pr_number,
                    NOW(),
                    CAST(:raw_payload_json AS JSONB)
                )
                ON CONFLICT (delivery_id) DO NOTHING
                """
            ),
            {
                "delivery_id": delivery_id,
                "provider": provider,
                "event_type": event_type,
                "action": action,
                "repository_id": repository_id,
                "pull_request_id": pull_request_id,
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "raw_payload_json": _json_dump(payload),
            },
        )


def insert_analysis(
    provider: str,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    base_sha: str,
    files_changed: int,
    additions: int,
    deletions: int,
    risk_score: int,
    risk_level: str,
    summary: str,
    files: list[dict[str, Any]] | None = None,
    risk_factors: list[dict[str, Any]] | None = None,
    state_events: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    merge_readiness: dict[str, Any] | None = None,
) -> int:
    repository_id = _upsert_repository(owner, repo, provider)
    pr_title = ""
    pr_body = ""
    pr_author = ""
    if metadata:
        pr_title = str(metadata.get("title") or "")
        pr_body = str(metadata.get("body") or "")
        pr_author = str(metadata.get("author") or "")
    pull_request_id = _upsert_pull_request(
        repository_id=repository_id,
        pr_number=pr_number,
        head_sha=head_sha,
        base_sha=base_sha,
        title=pr_title,
        body=pr_body,
        author=pr_author,
        state="open",
    )

    with _get_engine().begin() as conn:
        analysis_row = conn.execute(
            text(
                """
                INSERT INTO pr_analyses(
                    repository_id,
                    pull_request_id,
                    owner,
                    repo,
                    pr_number,
                    head_sha,
                    base_sha,
                    files_changed,
                    additions,
                    deletions,
                    summary,
                    created_at
                ) VALUES (
                    :repository_id,
                    :pull_request_id,
                    :owner,
                    :repo,
                    :pr_number,
                    :head_sha,
                    :base_sha,
                    :files_changed,
                    :additions,
                    :deletions,
                    :summary,
                    NOW()
                )
                RETURNING id
                """
            ),
            {
                "repository_id": repository_id,
                "pull_request_id": pull_request_id,
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "files_changed": files_changed,
                "additions": additions,
                "deletions": deletions,
                "summary": summary,
            },
        ).fetchone()
        analysis_id = int(analysis_row[0])

        conn.execute(
            text(
                """
                INSERT INTO risk_scores(analysis_id, score, level, factors_json, created_at)
                VALUES (:analysis_id, :score, :level, CAST(:factors_json AS JSONB), NOW())
                ON CONFLICT (analysis_id)
                DO UPDATE SET
                    score = EXCLUDED.score,
                    level = EXCLUDED.level,
                    factors_json = EXCLUDED.factors_json,
                    created_at = NOW()
                """
            ),
            {
                "analysis_id": analysis_id,
                "score": risk_score,
                "level": risk_level,
                "factors_json": _json_dump(risk_factors or []),
            },
        )

        if merge_readiness:
            conn.execute(
                text(
                    """
                    INSERT INTO pr_analyses_merge_readiness(
                        analysis_id, score, recommendation,
                        blocking_findings_json, reasons_json, created_at
                    ) VALUES (
                        :analysis_id, :score, :recommendation,
                        CAST(:blocking_json AS JSONB),
                        CAST(:reasons_json AS JSONB),
                        NOW()
                    )
                    ON CONFLICT (analysis_id) DO UPDATE SET
                        score = EXCLUDED.score,
                        recommendation = EXCLUDED.recommendation,
                        blocking_findings_json = EXCLUDED.blocking_findings_json,
                        reasons_json = EXCLUDED.reasons_json,
                        created_at = NOW()
                    """
                ),
                {
                    "analysis_id": analysis_id,
                    "score": merge_readiness.get("score", 0),
                    "recommendation": merge_readiness.get("recommendation", "UNKNOWN"),
                    "blocking_json": _json_dump(merge_readiness.get("blocking_findings") or []),
                    "reasons_json": _json_dump(merge_readiness.get("reasons") or []),
                },
            )

        if files:
            conn.execute(
                text(
                    """
                    INSERT INTO pr_diffs(
                        analysis_id,
                        pull_request_id,
                        file_path,
                        status,
                        additions,
                        deletions,
                        patch_text,
                        patch_hash,
                        created_at
                    ) VALUES (
                        :analysis_id,
                        :pull_request_id,
                        :file_path,
                        :status,
                        :additions,
                        :deletions,
                        :patch_text,
                        :patch_hash,
                        NOW()
                    )
                    """
                ),
                [
                    {
                        "analysis_id": analysis_id,
                        "pull_request_id": pull_request_id,
                        "file_path": str(file_item.get("file_path") or ""),
                        "status": str(file_item.get("status") or "modified"),
                        "additions": int(file_item.get("additions") or 0),
                        "deletions": int(file_item.get("deletions") or 0),
                        "patch_text": str(file_item.get("patch") or ""),
                        "patch_hash": _hash_text(str(file_item.get("patch") or "")),
                    }
                    for file_item in files
                ],
            )

    if state_events:
        _insert_analysis_events(analysis_id, state_events)

    if metadata:
        upsert_repo_context(
            owner=owner,
            repo=repo,
            context_type="pr_summary",
            context_key=f"pr-{pr_number}-{head_sha[:12] or 'unknown'}",
            content={
                "pr_number": pr_number,
                "title": pr_title,
                "summary": summary,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "head_sha": head_sha,
                "base_sha": base_sha,
            },
            source="pipeline",
            created_by="system",
            provider=provider,
        )

    return analysis_id


def insert_findings(analysis_id: int, findings: list[dict[str, Any]]) -> None:
    """Bulk-insert rule findings associated with an analysis record.

    No-ops when *findings* is empty.
    """
    if not findings:
        return
    with _get_engine().begin() as conn:
        analysis_refs = conn.execute(
            text("SELECT repository_id, pull_request_id FROM pr_analyses WHERE id = :analysis_id"),
            {"analysis_id": analysis_id},
        ).fetchone()
        if not analysis_refs:
            return

        repository_id = int(analysis_refs[0])
        pull_request_id = int(analysis_refs[1])

        conn.execute(
            text(
                """
                INSERT INTO pr_findings(
                    analysis_id,
                    rule_id,
                    severity,
                    message,
                    file_path,
                    line_start,
                    line_end,
                    evidence_json,
                    created_at
                ) VALUES (
                    :analysis_id,
                    :rule_id,
                    :severity,
                    :message,
                    :file_path,
                    :line_start,
                    :line_end,
                    CAST(:evidence_json AS JSONB),
                    NOW()
                )
                """
            ),
            [
                {
                    "analysis_id": analysis_id,
                    "rule_id": str(f.get("rule_id") or ""),
                    "severity": str(f.get("severity") or "medium"),
                    "message": str(f.get("message") or ""),
                    "file_path": str(f.get("file_path") or ""),
                    "line_start": int(f.get("line_start") or 0),
                    "line_end": int(f.get("line_end") or 0),
                    "evidence_json": _json_dump(f.get("evidence") or {}),
                }
                for f in findings
            ],
        )

    for finding in findings:
        _insert_finding_history(repository_id, pull_request_id, analysis_id, finding)


def get_repo_rules(owner: str, repo: str) -> dict[str, Any] | None:
    with _get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT rules_json FROM repo_rules WHERE owner = :owner AND repo = :repo"),
            {"owner": owner, "repo": repo},
        ).fetchone()
    if not row:
        return None
    return _json_load(row[0], None)


def set_repo_rules(
    owner: str,
    repo: str,
    rules: dict[str, Any],
    changed_by: str,
    reason: str = "",
    provider: str = "github",
) -> None:
    existing = get_repo_rules(owner, repo) or {}
    repository_id = _upsert_repository(owner, repo, provider)

    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO repo_rules(owner, repo, repository_id, rules_json, updated_at)
                VALUES (:owner, :repo, :repository_id, CAST(:rules_json AS JSONB), NOW())
                ON CONFLICT (owner, repo)
                DO UPDATE SET
                    repository_id = EXCLUDED.repository_id,
                    rules_json = EXCLUDED.rules_json,
                    updated_at = NOW()
                """
            ),
            {
                "owner": owner,
                "repo": repo,
                "repository_id": repository_id,
                "rules_json": _json_dump(rules),
            },
        )

        if existing.get("weights") != rules.get("weights"):
            conn.execute(
                text(
                    """
                    INSERT INTO config_audit_logs(
                        repository_id,
                        config_scope,
                        config_key,
                        old_value_json,
                        new_value_json,
                        changed_by,
                        changed_at,
                        reason
                    ) VALUES (
                        :repository_id,
                        :config_scope,
                        :config_key,
                        CAST(:old_value_json AS JSONB),
                        CAST(:new_value_json AS JSONB),
                        :changed_by,
                        NOW(),
                        :reason
                    )
                    """
                ),
                {
                    "repository_id": repository_id,
                    "config_scope": "repo_rules",
                    "config_key": "weights",
                    "old_value_json": _json_dump(existing.get("weights") or {}),
                    "new_value_json": _json_dump(rules.get("weights") or {}),
                    "changed_by": changed_by,
                    "reason": reason,
                },
            )


def get_repo_rule_audit(owner: str, repo: str, limit: int = 50) -> list[dict[str, Any]]:
    query_limit = max(1, min(limit, 500))
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    a.id,
                    a.config_scope,
                    a.config_key,
                    a.old_value_json,
                    a.new_value_json,
                    a.changed_by,
                    a.changed_at,
                    a.reason
                FROM config_audit_logs a
                JOIN repositories r ON r.id = a.repository_id
                WHERE r.owner = :owner AND r.name = :repo
                ORDER BY a.changed_at DESC
                LIMIT :query_limit
                """
            ),
            {"owner": owner, "repo": repo, "query_limit": query_limit},
        ).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "id": int(row[0]),
                "config_scope": str(row[1]),
                "config_key": str(row[2]),
                "old_value": _json_load(row[3], {}),
                "new_value": _json_load(row[4], {}),
                "changed_by": str(row[5] or ""),
                "changed_at": row[6],
                "reason": str(row[7] or ""),
            }
        )
    return output


def upsert_repo_context(
    owner: str,
    repo: str,
    context_type: str,
    context_key: str,
    content: dict[str, Any],
    source: str,
    created_by: str,
    provider: str = "github",
) -> None:
    repository_id = _upsert_repository(owner, repo, provider)
    content_json = _json_dump(content)
    content_hash = _hash_text(content_json)
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO repo_context_entries(
                    repository_id,
                    context_type,
                    context_key,
                    content_json,
                    content_hash,
                    source,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (
                    :repository_id,
                    :context_type,
                    :context_key,
                    CAST(:content_json AS JSONB),
                    :content_hash,
                    :source,
                    :created_by,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (repository_id, context_type, context_key)
                DO UPDATE SET
                    content_json = EXCLUDED.content_json,
                    content_hash = EXCLUDED.content_hash,
                    source = EXCLUDED.source,
                    created_by = EXCLUDED.created_by,
                    updated_at = NOW()
                """
            ),
            {
                "repository_id": repository_id,
                "context_type": context_type,
                "context_key": context_key,
                "content_json": content_json,
                "content_hash": content_hash,
                "source": source,
                "created_by": created_by,
            },
        )


def get_repo_context(owner: str, repo: str, limit: int = 100) -> list[dict[str, Any]]:
    query_limit = max(1, min(limit, 1000))
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    c.id,
                    c.context_type,
                    c.context_key,
                    c.content_json,
                    c.source,
                    c.created_by,
                    c.created_at,
                    c.updated_at
                FROM repo_context_entries c
                JOIN repositories r ON r.id = c.repository_id
                WHERE r.owner = :owner AND r.name = :repo
                ORDER BY c.updated_at DESC
                LIMIT :query_limit
                """
            ),
            {"owner": owner, "repo": repo, "query_limit": query_limit},
        ).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "id": int(row[0]),
                "context_type": str(row[1]),
                "context_key": str(row[2]),
                "content": _json_load(row[3], {}),
                "source": str(row[4] or ""),
                "created_by": str(row[5] or ""),
                "created_at": row[6],
                "updated_at": row[7],
            }
        )
    return output


def get_previous_review_findings(owner: str, repo: str, limit: int = 100) -> list[dict[str, Any]]:
    query_limit = max(1, min(limit, 1000))
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    h.id,
                    h.pull_request_id,
                    h.analysis_id,
                    h.rule_id,
                    h.severity,
                    h.message,
                    h.file_path,
                    h.line_start,
                    h.line_end,
                    h.evidence_json,
                    h.found_at
                FROM review_findings_history h
                JOIN repositories r ON r.id = h.repository_id
                WHERE r.owner = :owner AND r.name = :repo
                ORDER BY h.found_at DESC
                LIMIT :query_limit
                """
            ),
            {"owner": owner, "repo": repo, "query_limit": query_limit},
        ).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "id": int(row[0]),
                "pull_request_id": int(row[1]),
                "analysis_id": int(row[2]),
                "rule_id": str(row[3] or ""),
                "severity": str(row[4] or ""),
                "message": str(row[5] or ""),
                "file_path": str(row[6] or ""),
                "line_start": int(row[7] or 0),
                "line_end": int(row[8] or 0),
                "evidence": _json_load(row[9], {}),
                "found_at": row[10],
            }
        )
    return output


def cache_prompt_request(
    prompt: str,
    model: str,
    request_payload: dict[str, Any],
    owner: str,
    repo: str,
    pr_number: int | None,
    created_by: str,
    ttl_seconds: int,
    provider: str = "github",
) -> int:
    repository_id = _upsert_repository(owner, repo, provider)
    pull_request_id = None
    if pr_number is not None and pr_number > 0:
        pull_request_id = _upsert_pull_request(
            repository_id=repository_id,
            pr_number=pr_number,
            head_sha="",
            base_sha="",
            state="open",
        )

    prompt_hash = _hash_text(f"{model}::{prompt}")
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO prompt_cache(
                    repository_id,
                    pull_request_id,
                    prompt_hash,
                    model,
                    request_payload_json,
                    created_by,
                    created_at,
                    last_used_at,
                    use_count,
                    expires_at
                ) VALUES (
                    :repository_id,
                    :pull_request_id,
                    :prompt_hash,
                    :model,
                    CAST(:request_payload_json AS JSONB),
                    :created_by,
                    NOW(),
                    NOW(),
                    1,
                    NOW() + (:ttl_seconds * INTERVAL '1 second')
                )
                ON CONFLICT (prompt_hash)
                DO UPDATE SET
                    repository_id = EXCLUDED.repository_id,
                    pull_request_id = EXCLUDED.pull_request_id,
                    request_payload_json = EXCLUDED.request_payload_json,
                    last_used_at = NOW(),
                    use_count = prompt_cache.use_count + 1,
                    expires_at = EXCLUDED.expires_at
                RETURNING id
                """
            ),
            {
                "repository_id": repository_id,
                "pull_request_id": pull_request_id,
                "prompt_hash": prompt_hash,
                "model": model,
                "request_payload_json": _json_dump(request_payload),
                "created_by": created_by,
                "ttl_seconds": ttl_seconds,
            },
        ).fetchone()
    return int(row[0])


def get_cached_ai_response(prompt: str, model: str) -> dict[str, Any] | None:
    prompt_hash = _hash_text(f"{model}::{prompt}")
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    r.response_payload_json,
                    r.token_usage_json,
                    r.response_hash,
                    r.expires_at
                FROM ai_response_cache r
                JOIN prompt_cache p ON p.id = r.prompt_cache_id
                WHERE p.prompt_hash = :prompt_hash
                  AND (r.expires_at IS NULL OR r.expires_at > NOW())
                ORDER BY r.created_at DESC
                LIMIT 1
                """
            ),
            {"prompt_hash": prompt_hash},
        ).fetchone()
        if not row:
            return None

        conn.execute(
            text(
                """
                UPDATE prompt_cache
                SET last_used_at = NOW(), use_count = use_count + 1
                WHERE prompt_hash = :prompt_hash
                """
            ),
            {"prompt_hash": prompt_hash},
        )

        return {
            "response": _json_load(row[0], {}),
            "token_usage": _json_load(row[1], {}),
            "response_hash": str(row[2] or ""),
            "expires_at": row[3],
        }


def cache_ai_response(
    prompt_cache_id: int,
    response_payload: dict[str, Any],
    token_usage: dict[str, Any] | None,
    ttl_seconds: int,
) -> None:
    response_json = _json_dump(response_payload)
    response_hash = _hash_text(response_json)
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ai_response_cache(
                    prompt_cache_id,
                    response_hash,
                    response_payload_json,
                    token_usage_json,
                    created_at,
                    last_used_at,
                    expires_at
                ) VALUES (
                    :prompt_cache_id,
                    :response_hash,
                    CAST(:response_payload_json AS JSONB),
                    CAST(:token_usage_json AS JSONB),
                    NOW(),
                    NOW(),
                    NOW() + (:ttl_seconds * INTERVAL '1 second')
                )
                ON CONFLICT (prompt_cache_id)
                DO UPDATE SET
                    response_hash = EXCLUDED.response_hash,
                    response_payload_json = EXCLUDED.response_payload_json,
                    token_usage_json = EXCLUDED.token_usage_json,
                    last_used_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                """
            ),
            {
                "prompt_cache_id": prompt_cache_id,
                "response_hash": response_hash,
                "response_payload_json": response_json,
                "token_usage_json": _json_dump(token_usage or {}),
                "ttl_seconds": ttl_seconds,
            },
        )


def get_latest_analysis(
    owner: str,
    repo: str,
    pr_number: int,
    provider: str | None = None,
) -> dict[str, Any] | None:
    provider_clause = ""
    params: dict[str, Any] = {"owner": owner, "repo": repo, "pr_number": pr_number}
    if provider:
        provider_clause = " AND re.provider = :provider"
        params["provider"] = provider

    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    a.id,
                    re.provider,
                    a.owner,
                    a.repo,
                    a.pr_number,
                    a.head_sha,
                    a.base_sha,
                    a.files_changed,
                    a.additions,
                    a.deletions,
                    a.summary,
                    a.created_at,
                    r.score AS risk_score,
                    r.level AS risk_level
                FROM pr_analyses a
                JOIN repositories re ON re.id = a.repository_id
                JOIN risk_scores r ON r.analysis_id = a.id
                WHERE a.owner = :owner AND a.repo = :repo AND a.pr_number = :pr_number
                """
                + provider_clause
                +
                """
                ORDER BY a.id DESC
                LIMIT 1
                """
            ),
            params,
        ).mappings().fetchone()
    return dict(row) if row else None


def get_analysis_by_id(analysis_id: int) -> dict[str, Any] | None:
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    a.id,
                    a.owner,
                    a.repo,
                    a.pr_number,
                    a.head_sha,
                    a.base_sha,
                    a.files_changed,
                    a.additions,
                    a.deletions,
                    a.summary,
                    a.created_at,
                    r.score AS risk_score,
                    r.level AS risk_level,
                    repos.provider,
                    pr.title AS pr_title,
                    pr.author AS pr_author
                FROM pr_analyses a
                JOIN risk_scores r ON r.analysis_id = a.id
                JOIN repositories repos ON repos.id = a.repository_id
                JOIN pull_requests pr ON pr.id = a.pull_request_id
                WHERE a.id = :analysis_id
                """
            ),
            {"analysis_id": analysis_id},
        ).mappings().fetchone()
    return dict(row) if row else None


def get_analysis_diffs(analysis_id: int) -> list[dict[str, Any]]:
    """Return the stored per-file diff records for a given analysis.

    Each row has ``file_path``, ``status``, ``additions``, ``deletions``,
    and ``patch_text``, matching the shape of :class:`PRFileDiff`.
    """
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT file_path, status, additions, deletions, patch_text AS patch
                FROM pr_diffs
                WHERE analysis_id = :analysis_id
                ORDER BY id ASC
                """
            ),
            {"analysis_id": analysis_id},
        ).mappings().fetchall()
    return [dict(row) for row in rows]


def get_findings(analysis_id: int) -> list[dict[str, Any]]:
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    id,
                    analysis_id,
                    rule_id,
                    severity,
                    message,
                    file_path,
                    line_start,
                    line_end,
                    evidence_json
                FROM pr_findings
                WHERE analysis_id = :analysis_id
                ORDER BY id ASC
                """
            ),
            {"analysis_id": analysis_id},
        ).mappings().fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["evidence"] = _json_load(rec.pop("evidence_json"), {})
        output.append(rec)
    return output


def get_merge_readiness(analysis_id: int) -> dict[str, Any] | None:
    """Return the merge readiness assessment for an analysis, if one exists."""
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    score,
                    recommendation,
                    blocking_findings_json,
                    reasons_json
                FROM pr_analyses_merge_readiness
                WHERE analysis_id = :analysis_id
                """
            ),
            {"analysis_id": analysis_id},
        ).mappings().fetchone()
    if not row:
        return None
    rec = dict(row)
    return {
        "score": int(rec.get("score") or 0),
        "recommendation": rec.get("recommendation") or "UNKNOWN",
        "blocking_findings": _json_load(rec.get("blocking_findings_json"), []),
        "reasons": _json_load(rec.get("reasons_json"), []),
    }


def get_recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    query_limit = max(1, min(limit, 200))
    _ensure_pipeline_events_table()
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    pe.provider,
                    pe.delivery_id,
                    pe.owner,
                    pe.repo,
                    pe.pr_number,
                    COALESCE(e.action, '') AS action,
                    COALESCE(e.event_type, '') AS event_type,
                    COALESCE(e.received_at, pe.created_at) AS received_at,
                    a.id AS analysis_id,
                    r.score AS risk_score,
                    r.level AS risk_level,
                    pe.final_status,
                    agg.event_count,
                    agg.fallback_count,
                    agg.error_count
                FROM (
                    SELECT DISTINCT ON (delivery_id)
                        provider,
                        delivery_id,
                        owner,
                        repo,
                        pr_number,
                        final_status,
                        created_at
                    FROM pr_pipeline_events
                    ORDER BY delivery_id, seq DESC
                ) pe
                JOIN (
                    SELECT
                        delivery_id,
                        COUNT(*) AS event_count,
                        COUNT(*) FILTER (WHERE status = 'fallback') AS fallback_count,
                        COUNT(*) FILTER (WHERE event_type = 'error') AS error_count
                    FROM pr_pipeline_events
                    GROUP BY delivery_id
                ) agg ON agg.delivery_id = pe.delivery_id
                LEFT JOIN pr_events e ON e.delivery_id = pe.delivery_id
                LEFT JOIN pr_analyses a ON a.pull_request_id = e.pull_request_id
                LEFT JOIN risk_scores r ON r.analysis_id = a.id
                ORDER BY received_at DESC
                LIMIT :query_limit
                """
            ),
            {"query_limit": query_limit},
        ).mappings().fetchall()

    return [
        {
            "provider": str(row.get("provider") or "github"),
            "delivery_id": str(row.get("delivery_id") or ""),
            "owner": str(row.get("owner") or ""),
            "repo": str(row.get("repo") or ""),
            "pr_number": int(row.get("pr_number") or 0),
            "action": str(row.get("action") or ""),
            "event_type": str(row.get("event_type") or ""),
            "received_at": row.get("received_at"),
            "analysis_id": int(row.get("analysis_id")) if row.get("analysis_id") is not None else None,
            "risk_score": int(row.get("risk_score")) if row.get("risk_score") is not None else None,
            "risk_level": str(row.get("risk_level")) if row.get("risk_level") is not None else None,
            "final_status": str(row.get("final_status") or ""),
            "event_count": int(row.get("event_count") or 0),
            "fallback_count": int(row.get("fallback_count") or 0),
            "error_count": int(row.get("error_count") or 0),
        }
        for row in rows
    ]


def get_pipeline_events_by_delivery(delivery_id: str) -> list[dict[str, Any]]:
    _ensure_pipeline_events_table()
    with _get_engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    provider,
                    delivery_id,
                    owner,
                    repo,
                    pr_number,
                    seq,
                    event_type,
                    stage,
                    status,
                    detail_json AS detail,
                    created_at,
                    final_status
                FROM pr_pipeline_events
                WHERE delivery_id = :delivery_id
                ORDER BY seq ASC
                """
            ),
            {"delivery_id": delivery_id},
        ).mappings().fetchall()

    return [
        {
            "provider": str(row.get("provider") or "github"),
            "delivery_id": str(row.get("delivery_id") or ""),
            "owner": str(row.get("owner") or ""),
            "repo": str(row.get("repo") or ""),
            "pr_number": int(row.get("pr_number") or 0),
            "seq": int(row.get("seq") or 0),
            "event_type": str(row.get("event_type") or ""),
            "stage": row.get("stage"),
            "status": row.get("status"),
            "detail": _json_load(row.get("detail"), {}),
            "created_at": str(row.get("created_at")),
            "final_status": str(row.get("final_status") or ""),
        }
        for row in rows
    ]


def get_pipeline_events(
    owner: str,
    repo: str,
    pr_number: int,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_pipeline_events_table()
    provider_clause = ""
    params: dict[str, Any] = {"owner": owner, "repo": repo, "pr_number": pr_number}
    if provider:
        provider_clause = " AND provider = :provider"
        params["provider"] = provider

    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT delivery_id
                FROM pr_pipeline_events
                WHERE owner = :owner AND repo = :repo AND pr_number = :pr_number
                """
                + provider_clause
                +
                """
                ORDER BY created_at DESC, seq DESC
                LIMIT 1
                """
            ),
            params,
        ).fetchone()

    if not row:
        return []
    return get_pipeline_events_by_delivery(str(row[0]))
