from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    CompetitionRunSpec,
    PlanCompilationError,
    PlanCompiler,
    TopicFeasibility,
    TopicMode,
    TopicSelectionEngine,
    competition_topic_candidates,
    hypothesis_from_topic,
)


def test_auto_topic_selection_runs_top_three_smokes_and_uses_rubric_order() -> None:
    spec = CompetitionRunSpec(run_id="selection-test")
    candidates = competition_topic_candidates(spec)
    probed: list[str] = []

    def probe(candidate):
        probed.append(candidate.topic_id)
        return TopicFeasibility(
            topic_id=candidate.topic_id,
            passed=True,
            metric_name="relative_nmse_improvement",
            metric_value=0.5,
            evidence_path=f"feasibility/{candidate.topic_id}/metrics.json",
        )

    report = TopicSelectionEngine().select(
        spec=spec,
        candidates=candidates,
        probe=probe,
    )

    assert probed == [candidate.topic_id for candidate in candidates]
    assert report.selected_topic_id == "topic_mdbench_noise_robust_sparse"
    assert len(report.feasibility) == 3
    assert all(not failures for failures in report.hard_filter_failures.values())
    assert "40/30/30" in report.decision_policy


def test_seeded_mode_is_optional_but_requires_at_least_one_seed() -> None:
    with pytest.raises(ValidationError, match="seeded topic mode requires"):
        CompetitionRunSpec(run_id="seedless", topic_mode=TopicMode.SEEDED)

    spec = CompetitionRunSpec(
        run_id="seeded",
        topic_mode=TopicMode.SEEDED,
        topic="Operator-constrained equation discovery",
        guidance=("Keep the official MDBench metrics.",),
    )
    candidates = competition_topic_candidates(spec)

    assert candidates[0].title == "Operator-constrained equation discovery"
    assert candidates[0].topic_id == "topic_seeded_mdbench"
    assert candidates[0].hard_filter_failures() == ()


def test_plan_compiler_binds_topic_hypothesis_and_existing_planner() -> None:
    topic = competition_topic_candidates(CompetitionRunSpec(run_id="plan"))[0]
    hypothesis = hypothesis_from_topic(topic)
    protocol = PlanCompiler().compile(
        project_id="project-gate-a",
        topic=topic,
        hypothesis=hypothesis,
        timeout_seconds=20,
    )

    assert hypothesis.topic_id == topic.topic_id
    assert hypothesis.metric == "derivative_nmse"
    assert protocol.topic_id == topic.topic_id
    assert protocol.hypothesis_id == hypothesis.hypothesis_id
    assert protocol.seeds == (11, 23, 37)
    assert [task.operation.value for task in protocol.tasks] == [
        "implement",
        "implement",
        "replicate",
        "stop",
    ]
    assert protocol.development_fixture is True


def test_plan_compiler_rejects_candidate_hypothesis_mismatch() -> None:
    topics = competition_topic_candidates(CompetitionRunSpec(run_id="mismatch"))
    hypothesis = hypothesis_from_topic(topics[0]).model_copy(
        update={"topic_id": topics[1].topic_id}
    )

    with pytest.raises(PlanCompilationError, match="topic/hypothesis mismatch"):
        PlanCompiler().compile(
            project_id="project-gate-a",
            topic=topics[0],
            hypothesis=hypothesis,
            timeout_seconds=20,
        )
