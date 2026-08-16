"""Deterministic document-suggestion diff unit tests (spec §17.4)."""

from __future__ import annotations

from app.domains.writing.service import WritingService


def test_diff_detects_additions() -> None:
    patch, preview = WritingService._diff("第一行", "第一行\n第二行")
    assert patch["additions"] == 1
    assert patch["deletions"] == 0
    assert any(op["op"] == "add" and op["text"] == "第二行" for op in patch["ops"])
    assert "+第二行" in preview
    assert patch["proposed_markdown"] == "第一行\n第二行"


def test_diff_detects_removals() -> None:
    patch, preview = WritingService._diff("第一行\n第二行", "第一行")
    assert patch["additions"] == 0
    assert patch["deletions"] == 1
    assert any(op["op"] == "remove" and op["text"] == "第二行" for op in patch["ops"])
    assert "-第二行" in preview


def test_diff_detects_replacements() -> None:
    patch, preview = WritingService._diff("旧结论", "新结论")
    assert patch["additions"] == 1
    assert patch["deletions"] == 1
    assert "-旧结论" in preview
    assert "+新结论" in preview


def test_diff_identical_content_is_empty() -> None:
    patch, preview = WritingService._diff("同一段文字", "同一段文字")
    assert patch["additions"] == 0
    assert patch["deletions"] == 0
    assert patch["ops"] == []
    assert preview == ""
