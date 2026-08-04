"""PR risk scoring engine.

Computes a numeric risk score (0–100) and a severity level for a pull request
based on configurable rules (file count, churn, sensitive paths, missing tests).
"""
from __future__ import annotations
from typing import Any
from app.pr_pipeline.state import PRFileDiff, PRMetadata, RuleFinding

def _risk_level(score: int) -> str:
    """Map a numeric score to a human-readable risk level.

    Thresholds:
        - >= 75 → ``"critical"``
        - >= 50 → ``"high"``
        - >= 25 → ``"medium"``
        - <  25 → ``"low"``
    """
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def calculate_risk(
    metadata: PRMetadata,
    files: list[PRFileDiff],
    rules: dict[str, Any],
) -> tuple[int, str, list[dict[str, Any]], list[RuleFinding]]:
    """Evaluates the PR against the rule set and returns a 4-tuple of
    ``(score, level, factors, findings)`` where score is 0–100, level is
    ``low/medium/high/critical``, factors lists what contributed to the score,
    and findings are the individual rule violations.

    Checks performed (all configurable via *rules*):
    - **high_file_count**: PR touches too many files.
    - **high_churn**: Total lines added + deleted exceeds the threshold.
    - **sensitive_paths**: One or more files sit under a sensitive directory.
    - **no_tests_changed**: Source files changed but no test files included.
    """
    weights = rules.get("weights", {})
    thresholds = rules.get("thresholds", {})
    sensitive_prefixes = tuple(rules.get("sensitive_path_prefixes", []))
    test_markers = tuple(rules.get("test_path_markers", []))

    score = 0
    factors: list[dict[str, Any]] = []
    findings: list[RuleFinding] = []

    total_churn = metadata.additions + metadata.deletions

    high_file_count_threshold = int(thresholds.get("high_file_count", 20))
    if metadata.changed_files >= high_file_count_threshold:
        points = int(weights.get("high_file_count", 15))
        score += points
        factors.append({"factor": "high_file_count", "points": points, "value": metadata.changed_files})
        findings.append(
            RuleFinding(
                rule_id="high_file_count",
                severity="medium",
                message=f"PR changes {metadata.changed_files} files (threshold {high_file_count_threshold}).",
            )
        )

    high_churn_threshold = int(thresholds.get("high_churn_lines", 800))
    if total_churn >= high_churn_threshold:
        points = int(weights.get("high_churn", 15))
        score += points
        factors.append({"factor": "high_churn", "points": points, "value": total_churn})
        findings.append(
            RuleFinding(
                rule_id="high_churn",
                severity="medium",
                message=f"PR churn is {total_churn} lines (threshold {high_churn_threshold}).",
            )
        )

    sensitive_touched = [f.file_path for f in files if f.file_path.startswith(sensitive_prefixes)] if sensitive_prefixes else []
    if sensitive_touched:
        points = int(weights.get("sensitive_paths", 25))
        score += points
        factors.append({"factor": "sensitive_paths", "points": points, "count": len(sensitive_touched)})
        for file_path in sensitive_touched:
            findings.append(
                RuleFinding(
                    rule_id="sensitive_paths",
                    severity="high",
                    message="Sensitive path changed.",
                    file_path=file_path,
                )
            )

    has_non_test_change = any(
        not any(marker in f.file_path.lower() for marker in test_markers) for f in files
    )
    has_test_change = any(
        any(marker in f.file_path.lower() for marker in test_markers) for f in files
    )
    if has_non_test_change and not has_test_change:
        points = int(weights.get("no_tests_changed", 15))
        score += points
        factors.append({"factor": "no_tests_changed", "points": points})
        findings.append(
            RuleFinding(
                rule_id="no_tests_changed",
                severity="medium",
                message="Source files changed but no test files were changed.",
            )
        )

    score = min(100, max(0, score))
    level = _risk_level(score)
    return score, level, factors, findings
