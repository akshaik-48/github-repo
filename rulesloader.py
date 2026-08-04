"""Rule loading helpers.

Rules are resolved in this priority order:
1. Per-repository overrides stored in the ``repo_rules`` database table.
2. A JSON file at ``settings.default_rules_file``.
3. The hard-coded ``DEFAULT_RULES`` dict below.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from app.config import settings
from app.database import get_repo_rules

DEFAULT_RULES: dict[str, Any] = {
    "weights": {
        "high_file_count": 15,
        "high_churn": 15,
        "sensitive_paths": 25,
        "no_tests_changed": 15,
    },
    "thresholds": {
        "high_file_count": 20,
        "high_churn_lines": 800,
    },
    "sensitive_path_prefixes": [
        "auth/",
        "security/",
        "payments/",
        "infra/",
        ".github/workflows/",
    ],
    "test_path_markers": ["test", "tests", "spec"],
    "pr_title_check": {
        "enabled": False,
        "pattern": "",
        "severity": "high",
        "message": "PR title does not match the repository title policy.",
    },
    "commit_message_check": {
        "enabled": False,
        "pattern": "",
        "severity": "medium",
        "message": "Commit message does not match the repository commit policy.",
    },
}


def _load_default_rules_file() -> dict[str, Any]:
    """Load rules from the JSON file configured in settings.

    Falls back to ``DEFAULT_RULES`` if the file does not exist or cannot
    be parsed.
    """
    path = Path(settings.default_rules_file)
    if not path.exists():
        return DEFAULT_RULES
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_RULES


def load_rules(owner: str, repo: str) -> dict[str, Any]:
    """Return the effective rule set for a repository.

    Checks the database for a repo-specific override first; if none is found,
    falls back to the default rules file (or the built-in defaults).
    """
    repo_rules = get_repo_rules(owner, repo)
    if repo_rules:
        return repo_rules
    return _load_default_rules_file()


def load_review_guidelines() -> str:
    """Return the prose review guidelines fed to the LLM reviewer.

    Reads the markdown file configured in ``settings.review_guidelines_file``.
    Returns an empty string if the file is missing or unreadable.
    """
    path = Path(settings.review_guidelines_file)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
