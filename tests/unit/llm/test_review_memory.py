import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.knowledge import KnowledgeEntry, KnowledgeEntryType, KnowledgeZone
from autoresearch.llm import LLMEvidenceArtifact, LLMReviewQuality, LLMReviewResult
from autoresearch.llm.review_memory import (
    capture_llm_review_response,
    write_llm_review_issue_notes,
    write_llm_review_note,
)


def test_write_llm_review_note_creates_project_review_entry(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    result = _review_result()

    path = write_llm_review_note(
        result=result,
        vault_root=vault_root,
        project_id="project_1",
        source_task_id="44.1",
    )

    assert path == vault_root / "projects" / "project_1" / "review" / (
        "llm-review-report-" + ("a" * 12) + ".md"
    )
    entry = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
    assert entry.entry_type is KnowledgeEntryType.REVIEW_NOTE
    assert entry.zone is KnowledgeZone.PROJECT
    assert entry.project_id == "project_1"
    assert entry.related_task_ids == ["44.1"]
    assert "needs_revision" in entry.body
    assert "`evidence_1`" in entry.body
    assert "The model quality claim needs another artifact." in entry.body
    assert "评审模型原始响应绑定" in entry.body
    assert "本地私有、只追加的原始记忆层" in entry.body
    assert "```json" not in entry.body
    raw_records = list(
        (vault_root / "_private" / "raw-memory" / "projects" / "project_1").rglob(
            "rawmem_*.json"
        )
    )
    assert len(raw_records) == 1
    assert result.response_text not in path.read_text(encoding="utf-8")


def test_write_llm_review_issue_notes_creates_actionable_project_issues(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    result = _review_result()
    review_note = write_llm_review_note(
        result=result,
        vault_root=vault_root,
        project_id="project_1",
        source_task_id="45.1",
    )

    issue_paths = write_llm_review_issue_notes(
        result=result,
        vault_root=vault_root,
        project_id="project_1",
        source_task_id="46.1",
        review_note_path=review_note,
    )

    assert len(issue_paths) == 2
    first_issue = KnowledgeEntry.from_markdown(issue_paths[0].read_text(encoding="utf-8"))
    second_issue = KnowledgeEntry.from_markdown(issue_paths[1].read_text(encoding="utf-8"))
    assert first_issue.entry_type is KnowledgeEntryType.ISSUE_NOTE
    assert first_issue.zone is KnowledgeZone.PROJECT
    assert first_issue.project_id == "project_1"
    assert first_issue.related_task_ids == ["46.1"]
    assert "The validation status is supported." in first_issue.body
    assert "问题指纹：" in first_issue.body
    assert (
        "[[projects/project_1/review/llm-review-report-aaaaaaaaaaaa|LLM 证据评审]]"
        in first_issue.body
    )
    assert "The model quality claim needs another artifact." in second_issue.body
    assert "`缺失`" in second_issue.body


def test_write_llm_review_issue_notes_uses_stable_issue_fingerprints(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    first_result = _review_result(
        parsed_output={
            "verdict": "needs_revision",
            "summary": "Two actionable issues were found.",
            "findings": [
                {
                    "severity": "warning",
                    "claim": "The validation status is supported.",
                    "evidence_refs": ["evidence_1"],
                },
                {
                    "severity": "high",
                    "claim": "The benchmark comparison is under-evidenced.",
                    "evidence_refs": [],
                },
                {
                    "severity": "warning",
                    "claim": "The validation status is supported.",
                    "evidence_refs": ["evidence_1"],
                },
            ],
            "unsupported_claims": [],
            "next_steps": ["Attach source-backed comparison evidence."],
        }
    )
    second_result = _review_result(
        parsed_output={
            "verdict": "needs_revision",
            "summary": "The same two actionable issues were found in a different order.",
            "findings": [
                {
                    "severity": "high",
                    "claim": "The benchmark comparison is under-evidenced.",
                    "evidence_refs": [],
                },
                {
                    "severity": "warning",
                    "claim": "The validation status is supported.",
                    "evidence_refs": ["evidence_1"],
                },
            ],
            "unsupported_claims": [],
            "next_steps": ["Attach source-backed comparison evidence."],
        }
    )

    first_issue_paths = write_llm_review_issue_notes(
        result=first_result,
        vault_root=vault_root,
        project_id="project_1",
        source_task_id="47.1",
    )
    second_issue_paths = write_llm_review_issue_notes(
        result=second_result,
        vault_root=vault_root,
        project_id="project_1",
        source_task_id="47.1",
    )

    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_files = sorted(issue_dir.glob("llm-review-*.md"))
    assert len(first_issue_paths) == 2
    assert len(second_issue_paths) == 2
    assert {path.name for path in first_issue_paths} == {path.name for path in second_issue_paths}
    assert {path.name for path in issue_files} == {path.name for path in first_issue_paths}


def _review_result(parsed_output: dict[str, Any] | None = None) -> LLMReviewResult:
    structured_output = parsed_output or {
        "verdict": "needs_revision",
        "summary": "The report needs one additional evidence-backed caveat.",
        "findings": [
            {
                "severity": "warning",
                "claim": "The validation status is supported.",
                "evidence_refs": ["evidence_1"],
            }
        ],
        "unsupported_claims": ["The model quality claim needs another artifact."],
        "next_steps": ["Attach the missing metrics artifact."],
    }
    return LLMReviewResult(
        provider="test-provider",
        base_url="https://example.invalid",
        model_name="test-model",
        endpoint="https://example.invalid/chat/completions",
        subject_path="runs/demo/report.md",
        subject_sha256="a" * 64,
        evidence=[
            LLMEvidenceArtifact(
                evidence_id="evidence_1",
                path="runs/demo/validation.json",
                sha256="b" * 64,
                excerpt='{"status":"passed"}',
            )
        ],
        response_text=json.dumps(structured_output),
        quality=LLMReviewQuality(
            score=1.0,
            checks={
                "finding_refs_present": True,
                "finding_refs_known": True,
                "no_secret_leak": True,
            },
            parsed_output=structured_output,
        ),
    )


def test_review_result_rejects_parsed_output_that_diverges_from_raw_response() -> None:
    result = _review_result()
    payload = result.model_dump(mode="json")
    payload["response_text"] = '{"verdict":"pass"}'

    with pytest.raises(ValidationError, match="exact raw response_text"):
        LLMReviewResult.model_validate(payload)


def test_below_threshold_review_response_is_captured_before_note_filtering(
    tmp_path: Path,
) -> None:
    result = _review_result().model_copy(
        update={
            "quality": _review_result().quality.model_copy(update={"score": 0.4})
        }
    )

    binding = capture_llm_review_response(
        result=result,
        vault_root=tmp_path / "vault",
        project_id="project_1",
    )

    assert binding.payload_sha256
    assert binding.record_relative_path.startswith(
        "_private/raw-memory/projects/project_1/records/"
    )
