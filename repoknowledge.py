"""Repository knowledge extraction.

Auto-extracts lightweight repo knowledge -- the README, the tech stack, the key
dependencies and the directory structure -- and injects it into the LLM review
prompt so comments are grounded in what the repository actually is and does
(in-context learning, not fine-tuning). This lets the reviewer understand the
project before judging a change.

The extracted knowledge is cached in the ``repo_context_entries`` table and
refreshed only after ``settings.repo_knowledge_ttl_seconds`` to avoid fetching
on every PR. Fetching is best-effort: any failure returns an empty string so
the review continues normally.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone

from app.config import settings
from app.database import get_repo_context, upsert_repo_context
from app.github_client import GitHubClient
from app.gitlab_client import GitLabClient
from app.pr_pipeline.state import PRAgentState

_CONTEXT_TYPE = "repo_knowledge"
_CONTEXT_KEY = "summary"

# File extension -> human-readable language/tech, used to infer the stack from
# the repo file tree.
_EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript/React",
    ".ts": "TypeScript", ".tsx": "TypeScript/React", ".java": "Java",
    ".kt": "Kotlin", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".cpp": "C++", ".cc": "C++", ".c": "C", ".rs": "Rust",
    ".swift": "Swift", ".scala": "Scala", ".sh": "Shell", ".sql": "SQL",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".vue": "Vue",
    ".tf": "Terraform", ".yaml": "YAML", ".yml": "YAML",
}

# Marker file -> framework/tooling hint.
_MARKER_TECH = {
    "requirements.txt": "Python (pip)", "pyproject.toml": "Python (pyproject)",
    "pipfile": "Python (pipenv)", "package.json": "Node.js",
    "go.mod": "Go modules", "pom.xml": "Java (Maven)",
    "build.gradle": "Java/Kotlin (Gradle)", "gemfile": "Ruby (Bundler)",
    "cargo.toml": "Rust (Cargo)", "composer.json": "PHP (Composer)",
    "dockerfile": "Docker", "docker-compose.yml": "Docker Compose",
    ".github/workflows": "GitHub Actions CI", ".gitlab-ci.yml": "GitLab CI",
}

# Manifest files whose contents we fetch to extract the key dependencies.
_DEP_MANIFESTS = (
    "requirements.txt", "pyproject.toml", "package.json",
    "go.mod", "Gemfile", "pom.xml", "build.gradle", "Cargo.toml",
)


async def load_repo_knowledge(state: PRAgentState) -> str:
    """Return a compact repo-knowledge string for the review prompt.

    Uses the cached entry when it is still fresh; otherwise fetches the README
    and file structure from the provider, caches the result, and returns it.
    Returns an empty string when disabled or unavailable.
    """
    if not settings.repo_knowledge_enabled or not state.metadata:
        return ""

    owner = state.metadata.owner
    repo = state.metadata.repo

    cached = await asyncio.to_thread(_read_fresh_cache, owner, repo)
    if cached is not None:
        return cached

    knowledge = await _fetch_knowledge(state)
    if knowledge:
        try:
            await asyncio.to_thread(
                upsert_repo_context,
                owner=owner,
                repo=repo,
                context_type=_CONTEXT_TYPE,
                context_key=_CONTEXT_KEY,
                content={"text": knowledge},
                source="auto",
                created_by="system",
                provider=state.envelope.provider,
            )
        except Exception as exc:  # cache write is best-effort
            state.emit("warning", stage="review_comments", message=f"repo knowledge cache failed: {exc}")
    return knowledge


def _read_fresh_cache(owner: str, repo: str) -> str | None:
    """Return the cached knowledge text if present and within TTL, else ``None``
    (signalling a (re)fetch is needed)."""
    try:
        entries = get_repo_context(owner, repo, limit=100)
    except Exception:
        return None

    for entry in entries:
        if entry.get("context_type") == _CONTEXT_TYPE and entry.get("context_key") == _CONTEXT_KEY:
            if _is_fresh(entry.get("updated_at")):
                return str((entry.get("content") or {}).get("text") or "")
            return None
    return None


def _is_fresh(updated_at: object) -> bool:
    """Return True when ``updated_at`` is within the configured TTL."""
    if not isinstance(updated_at, datetime):
        return False
    now = datetime.now(timezone.utc)
    reference = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    return (now - reference).total_seconds() < settings.repo_knowledge_ttl_seconds


async def _fetch_knowledge(state: PRAgentState) -> str:
    """Fetch README + file structure from the provider and build a summary."""
    metadata = state.metadata
    assert metadata is not None
    ref = metadata.head_branch or metadata.base_branch or "HEAD"
    readme = ""
    files: list[str] = []
    manifests: dict[str, str] = {}

    try:
        fetch_file = _make_file_fetcher(state, ref)
        if state.envelope.provider == "github":
            client = GitHubClient()
            readme = await client.get_readme(metadata.owner, metadata.repo, ref)
            files = await client.get_repo_tree(metadata.owner, metadata.repo, ref)
        elif state.envelope.provider == "gitlab":
            project_id = (state.envelope.payload.get("project") or {}).get("id")
            if project_id:
                client = GitLabClient()
                readme = await client.get_file_raw(project_id, "README.md", ref)
                files = await client.get_repo_tree(project_id, ref)
        if fetch_file is not None:
            manifests = await _fetch_manifests(fetch_file, files)
    except Exception as exc:  # best-effort; never break the review
        state.emit("warning", stage="review_comments", message=f"repo knowledge fetch failed: {exc}")

    return _build_summary(readme, files, manifests)


def _make_file_fetcher(state: PRAgentState, ref: str):
    """Return an async ``fetch(path) -> str`` for the active provider, or ``None``
    when file fetching isn't available (e.g. missing GitLab project id)."""
    metadata = state.metadata
    assert metadata is not None
    if state.envelope.provider == "github":
        client = GitHubClient()

        async def _gh(path: str) -> str:
            return await client.get_file(metadata.owner, metadata.repo, path, ref)

        return _gh
    if state.envelope.provider == "gitlab":
        project_id = (state.envelope.payload.get("project") or {}).get("id")
        if not project_id:
            return None
        client = GitLabClient()

        async def _gl(path: str) -> str:
            return await client.get_file_raw(project_id, path, ref)

        return _gl
    return None


async def _fetch_manifests(fetch_file, files: list[str]) -> dict[str, str]:
    """Fetch the contents of any known dependency-manifest files present at the
    repo root, so we can extract the key dependencies."""
    present = {f for f in files if "/" not in f}
    result: dict[str, str] = {}
    for name in _DEP_MANIFESTS:
        if name in present:
            try:
                content = await fetch_file(name)
            except Exception:
                content = ""
            if content.strip():
                result[name] = content
    return result


def _detect_stack(files: list[str]) -> list[str]:
    """Infer the primary languages and tooling from the repo file tree."""
    lang_counts: Counter[str] = Counter()
    markers: list[str] = []
    lower_files = [f.lower() for f in files]
    for path in files:
        dot = path.rfind(".")
        if dot != -1:
            lang = _EXT_LANG.get(path[dot:].lower())
            if lang:
                lang_counts[lang] += 1
    for marker, tech in _MARKER_TECH.items():
        if any(marker in f for f in lower_files) and tech not in markers:
            markers.append(tech)
    top_langs = [lang for lang, _ in lang_counts.most_common(5)]
    return top_langs + [m for m in markers if m not in top_langs]


def _extract_dependencies(manifests: dict[str, str]) -> list[str]:
    """Extract a capped, de-duplicated list of dependency names from the
    fetched manifest files."""
    deps: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = name.strip().strip("\"',")
        if name and name.lower() not in seen:
            seen.add(name.lower())
            deps.append(name)

    for name, content in manifests.items():
        lower = name.lower()
        if lower == "requirements.txt":
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    _add(re.split(r"[=<>!~;\[ ]", line, 1)[0])
        elif lower == "pyproject.toml":
            for match in re.findall(r'"([A-Za-z0-9_.\-]+)\s*[=<>~!]', content):
                _add(match)
        elif lower == "package.json":
            try:
                data = json.loads(content)
                for section in ("dependencies", "devDependencies"):
                    for dep in (data.get(section) or {}):
                        _add(dep)
            except (json.JSONDecodeError, ValueError):
                pass
        elif lower == "go.mod":
            for match in re.findall(r"^\s+([\w./\-]+)\s+v", content, re.MULTILINE):
                _add(match)
        elif lower == "gemfile":
            for match in re.findall(r"gem\s+['\"]([^'\"]+)['\"]", content):
                _add(match)
        elif lower == "pom.xml":
            for match in re.findall(r"<artifactId>([^<]+)</artifactId>", content):
                _add(match)
        elif lower == "build.gradle":
            for match in re.findall(r"['\"]([\w.\-]+:[\w.\-]+):", content):
                _add(match)
        elif lower == "cargo.toml":
            in_deps = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_deps = "dependencies" in stripped
                elif in_deps and "=" in stripped:
                    _add(stripped.split("=", 1)[0])
    return deps[: settings.repo_knowledge_max_deps]


def _structure_summary(files: list[str]) -> str:
    """Summarise the repo layout by top-level directory with file counts and a
    few example entries, instead of a flat, truncated file list."""
    top_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    root_files: list[str] = []
    for path in files:
        if "/" in path:
            top = path.split("/", 1)[0]
            top_counts[top] += 1
            examples.setdefault(top, [])
            if len(examples[top]) < 3:
                examples[top].append(path)
        else:
            root_files.append(path)

    lines: list[str] = []
    for top, count in top_counts.most_common(15):
        sample = ", ".join(examples.get(top, [])[:3])
        lines.append(f"- {top}/ ({count} files) e.g. {sample}")
    if root_files:
        lines.append("- (root): " + ", ".join(sorted(root_files)[:12]))
    return "\n".join(lines)


def _build_summary(readme: str, files: list[str], manifests: dict[str, str] | None = None) -> str:
    """Assemble the compact knowledge string: purpose (README), tech stack, key
    dependencies and directory structure."""
    manifests = manifests or {}
    parts: list[str] = []

    if readme.strip():
        excerpt = readme.strip()[: settings.repo_knowledge_max_readme_chars]
        parts.append("## Repository purpose (README excerpt)\n" + excerpt)

    stack = _detect_stack(files)
    if stack:
        parts.append("## Tech stack\n" + ", ".join(stack))

    deps = _extract_dependencies(manifests)
    if deps:
        parts.append("## Key dependencies\n" + ", ".join(deps))

    if files:
        structure = _structure_summary(files)
        if structure:
            parts.append("## Repository structure\n" + structure)

    return "\n\n".join(parts).strip()

