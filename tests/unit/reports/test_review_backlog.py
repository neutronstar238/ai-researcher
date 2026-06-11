import json
from pathlib import Path

from autoresearch.reports import (
    PaperReviewContext,
    ReviewBacklogRecordType,
    ReviewDimension,
    create_review_backlog,
    simulate_paper_review,
)


def test_demo_review_creates_structured_follow_up_records(tmp_path: Path) -> None:
    report = simulate_paper_review(
        PaperReviewContext(
            title="Demo Review",
            core_claim_ids=["claim_accuracy"],
            compliance_checks={
                "has_limitations": True,
                "has_references": True,
            },
        )
    )

    artifact = create_review_backlog(
        report,
        project_id="project-001",
        source_task_id="paper-review-demo",
        output_dir=tmp_path,
    )

    assert artifact.json_path == (tmp_path / "review-backlog.json").as_posix()
    assert artifact.markdown_path == (tmp_path / "review-backlog.md").as_posix()
    assert {
        record.record_type
        for record in artifact.records
    } == {
        ReviewBacklogRecordType.PROBLEM_ENTRY,
        ReviewBacklogRecordType.FOLLOW_UP_TASK,
    }

    technical_problem = next(
        record
        for record in artifact.records
        if record.dimension is ReviewDimension.TECHNICAL_SOUNDNESS
    )
    assert technical_problem.record_type is ReviewBacklogRecordType.PROBLEM_ENTRY
    assert technical_problem.priority == 1
    assert "Attach validated evidence" in technical_problem.action
    assert technical_problem.problem_markdown is not None
    assert "P-REVIEW-DEMO-REVIEW" in technical_problem.problem_markdown

    payload = json.loads((tmp_path / "review-backlog.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "review-backlog.md").read_text(encoding="utf-8")

    assert payload["records"][0]["project_id"] == "project-001"
    assert payload["records"][0]["source_task_id"] == "paper-review-demo"
    assert "# Review Backlog: Demo Review" in markdown
    assert "problem_entry" in markdown
