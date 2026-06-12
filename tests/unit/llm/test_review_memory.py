from pathlib import Path
from typing import Any

from autoresearch.knowledge import KnowledgeEntry, KnowledgeEntryType, KnowledgeZone
from autoresearch.llm import LLMEvidenceArtifact, LLMReviewQuality, LLMReviewResult
from autoresearch.llm.review_memory import write_llm_review_issue_notes, write_llm_review_note


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
    assert "Issue fingerprint:" in first_issue.body
    assert "[[projects/project_1/review/llm-review-report-aaaaaaaaaaaa|LLM evidence review]]" in first_issue.body
    assert "The model quality claim needs another artifact." in second_issue.body
    assert "`missing`" in second_issue.body


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
        response_text='{"verdict":"needs_revision"}',
        quality=LLMReviewQuality(
            score=1.0,
            checks={"finding_refs_present": True, "finding_refs_known": True},
            parsed_output=structured_output,
        ),
    )
