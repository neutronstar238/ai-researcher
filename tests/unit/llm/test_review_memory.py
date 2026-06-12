from pathlib import Path

from autoresearch.knowledge import KnowledgeEntry, KnowledgeEntryType, KnowledgeZone
from autoresearch.llm import LLMEvidenceArtifact, LLMReviewQuality, LLMReviewResult
from autoresearch.llm.review_memory import write_llm_review_note


def test_write_llm_review_note_creates_project_review_entry(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    result = LLMReviewResult(
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
            parsed_output={
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
            },
        ),
    )

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
