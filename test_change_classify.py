"""Tests for change classification, focused on indentation-significant languages.

Re-indentation in Python/YAML changes program meaning and must NOT be treated
as an auto-mergeable whitespace-only change; the same re-indentation in a
brace-delimited language (JS/Go/Java) remains whitespace-only.
"""
from __future__ import annotations

from app.change_classify import CODE_CHANGE, EMPTY, WHITESPACE_ONLY, classify_change
from app.pr_pipeline.state import PRFileDiff


def _file(path: str, patch: str, status: str = "modified") -> PRFileDiff:
    return PRFileDiff(file_path=path, status=status, additions=1, deletions=1, patch=patch)


def test_python_reindentation_is_code_change():
    patch = "@@ -1,1 +1,1 @@\n-    return x\n+        return x\n"
    assert classify_change([_file("app/service.py", patch)]) == CODE_CHANGE


def test_python_blank_line_only_is_whitespace_only():
    patch = "@@ -1,1 +1,2 @@\n+\n"
    assert classify_change([_file("app/service.py", patch)]) == WHITESPACE_ONLY


def test_python_trailing_whitespace_cleanup_is_whitespace_only():
    patch = "@@ -1,1 +1,1 @@\n-def foo():   \n+def foo():\n"
    assert classify_change([_file("app/service.py", patch)]) == WHITESPACE_ONLY

def test_yaml_reindentation_is_code_change():
    patch = "@@ -1,1 +1,1 @@\n-  key: value\n+    key: value\n"
    assert classify_change([_file("config/app.yml", patch)]) == CODE_CHANGE

def test_javascript_reindentation_stays_whitespace_only():
    patch = "@@ -1,1 +1,1 @@\n-  return x\n+    return x\n"
    assert classify_change([_file("web/app.js", patch)]) == WHITESPACE_ONLY

def test_added_file_is_code_change():
    patch = "@@ -0,0 +1,1 @@\n+print('hi')\n"
    assert classify_change([_file("app/new.py", patch, status="added")]) == CODE_CHANGE

def test_no_files_is_empty():
    assert classify_change([]) == EMPTY
