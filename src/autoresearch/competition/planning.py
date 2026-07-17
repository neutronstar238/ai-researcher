"""Compile a selected topic and hypothesis into an executable experiment DAG."""

from __future__ import annotations

from autoresearch.competition.models import (
    ExperimentProtocol,
    HypothesisProposal,
    ResearchOperation,
    ResearchTaskSpec,
    TopicCandidate,
)
from autoresearch.experiments import ExperimentPlanningConfig, plan_experiment_tasks
from autoresearch.research import generate_hypotheses
from autoresearch.schemas import (
    CandidateStatus,
    Hypothesis,
    ResearchCandidate,
    TaskStatus,
)

MDBENCH_ADAPTER_ID = "mdbench-model-discovery"
MDBENCH_ADAPTER_VERSION = "0.1.0"
MDBENCH_REVISION = "f81813e760325589737fe3311ac8199ecc64188a"
MDBENCH_SOURCE = "https://github.com/gryaklab/mdbench"


class PlanCompilationError(ValueError):
    """Raised when a hypothesis cannot be causally compiled from its topic."""


def hypothesis_from_topic(topic: TopicCandidate) -> HypothesisProposal:
    """Use the existing hypothesis generator and preserve the selected topic ID."""

    candidate = ResearchCandidate(
        id=topic.topic_id,
        title=topic.title,
        description=topic.problem_statement,
        research_gap=topic.innovation_claim,
        novelty_score=min(topic.scorecard.scientific_value / 40.0, 1.0),
        feasibility_score=min(topic.reproducibility_score, 1.0),
        impact_score=min(topic.scorecard.application_potential / 30.0, 1.0),
        evidence_refs=list(topic.literature_evidence),
        related_document_ids=[],
        status=CandidateStatus.APPROVED,
        metadata={
            "method": topic.innovation_claim,
            "dataset": topic.dataset_refs[0],
            "baseline": topic.baseline_methods[0],
            "limitation": topic.problem_statement,
            "metric": topic.metrics[0],
        },
    )
    generated = generate_hypotheses(candidate)
    if len(generated) != 1:
        raise PlanCompilationError("exactly one hypothesis is required for Gate A MVP")
    hypothesis = generated[0]
    return HypothesisProposal(
        hypothesis_id=hypothesis.id,
        topic_id=topic.topic_id,
        statement=hypothesis.statement,
        prediction=(
            f"{topic.metrics[0]} is lower than the strongest executed baseline while "
            "equation_structure_f1 remains high."
        ),
        metric=topic.metrics[0],
        baseline=topic.baseline_methods[0],
        dataset_ref=topic.dataset_refs[0],
        evidence_refs=tuple(hypothesis.evidence_refs),
        falsification_conditions=topic.falsification_conditions,
    )


class PlanCompiler:
    """Compile existing hypothesis/planner records into the competition protocol."""

    def compile(
        self,
        *,
        project_id: str,
        topic: TopicCandidate,
        hypothesis: HypothesisProposal,
        timeout_seconds: int,
    ) -> ExperimentProtocol:
        if hypothesis.topic_id != topic.topic_id:
            raise PlanCompilationError(
                "topic/hypothesis mismatch: hypothesis was not derived from selected topic"
            )
        if hypothesis.metric not in topic.metrics:
            raise PlanCompilationError(
                "topic/hypothesis mismatch: hypothesis metric is outside the topic contract"
            )
        if hypothesis.dataset_ref not in topic.dataset_refs:
            raise PlanCompilationError(
                "topic/hypothesis mismatch: hypothesis dataset is outside the topic contract"
            )

        legacy_hypothesis = Hypothesis(
            id=hypothesis.hypothesis_id,
            candidate_id=topic.topic_id,
            statement=hypothesis.statement,
            prediction=hypothesis.prediction,
            metric=hypothesis.metric,
            baseline=hypothesis.baseline,
            dataset_ref=hypothesis.dataset_ref,
            evidence_refs=list(hypothesis.evidence_refs),
            status=TaskStatus.READY,
        )
        planned_tasks = plan_experiment_tasks(
            project_id=project_id,
            hypotheses=[legacy_hypothesis],
            config=ExperimentPlanningConfig(
                max_cpu_time_seconds=timeout_seconds,
                max_memory_mb=512,
                max_gpu_hours=0.0,
                max_storage_mb=64,
                timeout_seconds=timeout_seconds,
            ),
        )
        primary = planned_tasks[0]
        tasks = (
            ResearchTaskSpec(
                task_id=f"{primary.id}:baseline",
                operation=ResearchOperation.IMPLEMENT,
                description=(
                    "Execute a constant-derivative baseline on the same generated "
                    "characterization data."
                ),
                expected_outputs=("metrics.json", "artifacts/discovered-equation.json"),
                timeout_seconds=primary.timeout_seconds,
            ),
            ResearchTaskSpec(
                task_id=f"{primary.id}:candidate",
                operation=ResearchOperation.IMPLEMENT,
                description=(
                    "Fit the topic-bound sparse polynomial library and compute equation, "
                    "derivative, extrapolation, complexity, and cost metrics."
                ),
                dependency_ids=(f"{primary.id}:baseline",),
                expected_outputs=("metrics.json", "artifacts/discovered-equation.json"),
                timeout_seconds=primary.timeout_seconds,
            ),
            ResearchTaskSpec(
                task_id=f"{primary.id}:replicate",
                operation=ResearchOperation.REPLICATE,
                description="Repeat the same compiled code under three fixed independent seeds.",
                dependency_ids=(f"{primary.id}:candidate",),
                expected_outputs=("validation/validation-report.json",),
                timeout_seconds=primary.timeout_seconds,
                max_attempts=3,
            ),
            ResearchTaskSpec(
                task_id=f"{primary.id}:stop",
                operation=ResearchOperation.STOP,
                description=(
                    "Stop after the bounded smoke and report Gate A as incomplete until the "
                    "official 10 ODE / 4 PDE matrix is executed."
                ),
                dependency_ids=(f"{primary.id}:replicate",),
                timeout_seconds=primary.timeout_seconds,
            ),
        )
        return ExperimentProtocol(
            topic_id=topic.topic_id,
            hypothesis_id=hypothesis.hypothesis_id,
            adapter_id=MDBENCH_ADAPTER_ID,
            adapter_version=MDBENCH_ADAPTER_VERSION,
            benchmark_source=MDBENCH_SOURCE,
            benchmark_revision=MDBENCH_REVISION,
            baseline_methods=topic.baseline_methods,
            candidate_method=topic.innovation_claim,
            metrics=topic.metrics,
            seeds=(11, 23, 37),
            tasks=tasks,
            acceptance_criteria=(
                "candidate derivative_nmse is below the executed constant baseline",
                "equation_structure_f1 is at least 0.95",
                "all three seeded executions preserve the direction of effect",
                "full Gate A additionally requires official MDBench data for 10 ODE and 4 PDE",
            ),
            development_fixture=True,
        )
