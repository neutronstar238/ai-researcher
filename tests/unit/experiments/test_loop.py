import json
from pathlib import Path

from autoresearch.experiments import (
    LoopDecisionPolicy,
    LoopFailureCategory,
    build_closed_loop_campaign,
    classify_loop_failure,
    create_loop_iteration_from_cycle_summary,
    select_loop_candidate,
    write_loop_report_artifact,
)
from autoresearch.schemas import ResearchCandidate, ValidationStatus


def test_closed_loop_campaign_builds_doe_candidate_space() -> None:
    campaign = build_closed_loop_campaign(
        candidate=_candidate(),
        project_id="project_1",
        cycle_id="cycle_1",
        research_plan=_research_plan_payload(),
    )

    assert campaign.project_id == "project_1"
    assert campaign.target_metric == "accuracy"
    assert campaign.candidate_space[0].candidate_id == "arm_baseline_reproduction"
    assert "run record" in campaign.evidence_requirements
    assert campaign.protocol_refs == ["runs/cycle/research-plan.json", "vault/plan.md"]


def test_loop_selector_uses_doe_first_then_repair_on_failure(tmp_path: Path) -> None:
    campaign = build_closed_loop_campaign(
        candidate=_candidate(),
        project_id="project_1",
        cycle_id="cycle_1",
        research_plan=_research_plan_payload(),
    )
    first = select_loop_candidate(campaign)
    failed = create_loop_iteration_from_cycle_summary(
        campaign=campaign,
        decision=first,
        summary=_cycle_summary(tmp_path, validation_status="failed"),
        base_dir=tmp_path,
    )

    repair = select_loop_candidate(campaign, previous_iterations=(failed,))

    assert first.decision_policy is LoopDecisionPolicy.DOE_GRID
    assert failed.failure_category is LoopFailureCategory.VALIDATION
    assert repair.decision_policy is LoopDecisionPolicy.REPAIR_OR_FREEZE
    assert repair.frozen_dimensions


def test_loop_report_writes_json_markdown_and_vault_note(tmp_path: Path) -> None:
    campaign = build_closed_loop_campaign(
        candidate=_candidate(),
        project_id="project_1",
        cycle_id="cycle_1",
        research_plan=_research_plan_payload(),
    )
    decision = select_loop_candidate(campaign)
    summary = _cycle_summary(tmp_path)
    iteration = create_loop_iteration_from_cycle_summary(
        campaign=campaign,
        decision=decision,
        summary=summary,
        base_dir=tmp_path,
    )

    artifact = write_loop_report_artifact(
        campaign=campaign,
        iterations=(iteration,),
        output_dir=tmp_path / "loop",
        vault_root=tmp_path / "vault",
        project_id="project_1",
    )

    assert artifact.quality_gate.passed is True
    assert artifact.metrics.metadata_completeness == 1.0
    assert artifact.metrics.evidence_coverage == 1.0
    assert artifact.metrics.reproduction_delta == 0.0
    assert artifact.metrics.enhancement_factor > 1.0
    assert artifact.json_path.is_file()
    assert artifact.markdown_path.is_file()
    assert artifact.vault_path is not None
    assert artifact.vault_path.is_file()
    payload = json.loads(artifact.json_path.read_text(encoding="utf-8"))
    assert payload["quality_gate"]["passed"] is True
    assert payload["iterations"][0]["validation_status"] == ValidationStatus.PASSED.value
    assert "Loop Engineering Report" in artifact.markdown_path.read_text(encoding="utf-8")


def test_loop_failure_classification_uses_engineering_categories() -> None:
    assert classify_loop_failure("Semantic Scholar 429 rate limit") is LoopFailureCategory.SOURCE
    assert classify_loop_failure("metrics.json missing bounds") is LoopFailureCategory.METRIC
    assert classify_loop_failure("approval required for secret access") is LoopFailureCategory.SAFETY


def _candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_1",
        title="Variance-Calibrated Prototype Evaluation",
        description="Compare a variance-calibrated prototype method with a centroid baseline.",
        research_gap="Prototype calibration needs reproducible evidence on public data.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["https://example.test/paper"],
        metadata={
            "method": "variance-calibrated prototype classifier",
            "baseline": "nearest centroid baseline",
            "baseline_metric": 0.75,
        },
    )


def _research_plan_payload() -> dict[str, object]:
    return {
        "json_path": "runs/cycle/research-plan.json",
        "markdown_path": "vault/plan.md",
        "plan": {
            "problem_statement": "Can calibration improve accuracy on a public benchmark?",
            "technical_details": "Primary metric: accuracy with baseline and ablation.",
            "methods": "Compare method with a baseline using accuracy.",
            "experiments": ["Run baseline.", "Run proposed method.", "Run ablation."],
            "evidence_refs": ["https://example.test/paper", "runs/literature.md"],
        },
    }


def _cycle_summary(tmp_path: Path, *, validation_status: str = "passed") -> dict[str, object]:
    run_record = tmp_path / "demo" / "run" / "run-record.json"
    validation = tmp_path / "demo" / "validation" / "validation-report.json"
    evidence_map = tmp_path / "demo" / "evidence" / "evidence-map.json"
    report = tmp_path / "demo" / "report" / "report.md"
    reproduction = tmp_path / "reproduction" / "reproduction-check.json"
    for path in (run_record, validation, evidence_map, report, reproduction):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    run_record.write_text(
        json.dumps(
            {
                "run": {
                    "id": "run_1",
                    "status": "success" if validation_status == "passed" else "failed",
                    "config_hash": "config_hash_1",
                    "data_hash": "data_hash_1",
                },
                "metrics": {
                    "values": {
                        "accuracy": 0.80,
                        "baseline_accuracy": 0.75,
                    }
                },
                "validation_report": {"status": validation_status},
            }
        ),
        encoding="utf-8",
    )
    return {
        "cycle_id": "cycle_1",
        "candidate": {"evidence_refs": ["https://example.test/paper"]},
        "literature": {"summary_path": (tmp_path / "literature.md").as_posix()},
        "similarity": {"summary_path": (tmp_path / "similarity.md").as_posix()},
        "research_plan": {"json_path": (tmp_path / "research-plan.json").as_posix()},
        "demo": {
            "run_record_path": run_record.as_posix(),
            "validation_json_path": validation.as_posix(),
            "evidence_map_path": evidence_map.as_posix(),
            "report_path": report.as_posix(),
        },
        "reproduction_check": {
            "status": "passed",
            "json_path": reproduction.as_posix(),
        },
    }
