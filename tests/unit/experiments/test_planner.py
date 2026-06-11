from autoresearch.experiments import (
    AblationPlanningConfig,
    AblationVariable,
    ExperimentPlanningConfig,
    plan_ablation_matrix,
    plan_experiment_tasks,
)
from autoresearch.schemas import Hypothesis, TaskStatus


def _hypothesis(metric: str = "reproducibility_rate") -> Hypothesis:
    return Hypothesis(
        id="hypothesis_1",
        candidate_id="candidate_1",
        statement="Method A improves the metric.",
        prediction="The metric improves.",
        metric=metric,
        baseline="baseline_a",
        dataset_ref="benchmark_a",
        evidence_refs=["doc_1"],
    )


def test_plan_experiment_tasks_creates_required_fields() -> None:
    tasks = plan_experiment_tasks(project_id="project-001", hypotheses=[_hypothesis()])

    assert len(tasks) == 1
    task = tasks[0]
    assert task.project_id == "project-001"
    assert task.hypothesis_id == "hypothesis_1"
    assert task.entrypoint == "experiments/hypothesis-1/run.py"
    assert task.config_path == "experiments/hypothesis-1/config.yaml"
    assert task.metrics == ["reproducibility_rate"]
    assert "metrics.json" in task.expected_outputs
    assert task.metadata["dataset_assumptions"] == {
        "dataset_ref": "benchmark_a",
        "baseline": "baseline_a",
    }
    assert "metric reproducibility_rate exists" in task.metadata["validation_checks"]
    assert task.status is TaskStatus.DRAFT


def test_plan_experiment_tasks_respects_budget_limits() -> None:
    tasks = plan_experiment_tasks(
        project_id="project-001",
        hypotheses=[_hypothesis("latency_seconds")],
        config=ExperimentPlanningConfig(
            max_cpu_time_seconds=2400,
            max_memory_mb=2048,
            max_gpu_hours=0.5,
            max_storage_mb=256,
            timeout_seconds=1200,
        ),
    )
    budget = tasks[0].resource_budget

    assert budget["cpu_time_seconds"] == 1200
    assert budget["memory_mb"] == 2048
    assert budget["gpu_hours"] == 0.5
    assert budget["storage_mb"] == 256
    assert tasks[0].timeout_seconds == 1200
    assert "metric direction is lower_is_better" in tasks[0].metadata["validation_checks"]


def test_plan_ablation_matrix_creates_one_factor_tasks_from_variables() -> None:
    tasks = plan_ablation_matrix(
        project_id="project-001",
        hypothesis=_hypothesis(),
        variables=[
            AblationVariable(
                name="retrieval memory",
                control_value=True,
                ablated_value=False,
            ),
            AblationVariable(
                name="reranker top_k",
                control_value=8,
                ablated_value=0,
            ),
        ],
        config=AblationPlanningConfig(
            max_experiments=3,
            max_total_cpu_time_seconds=1200,
            per_experiment_cpu_time_seconds=300,
            timeout_seconds=300,
        ),
    )

    assert [task.id for task in tasks] == [
        "ablation_hypothesis-1_retrieval-memory",
        "ablation_hypothesis-1_reranker-top-k",
    ]
    assert tasks[0].entrypoint == "experiments/hypothesis-1/ablations/retrieval-memory/run.py"
    assert tasks[0].resource_budget["cpu_time_seconds"] == 300
    assert tasks[0].metadata["ablation"] == {
        "matrix_kind": "one_factor_at_a_time",
        "variable": "retrieval memory",
        "control_value": True,
        "ablated_value": False,
        "index": 1,
    }
    assert "baseline reproduction exists" in tasks[0].metadata["validation_checks"]
    assert tasks[0].status is TaskStatus.DRAFT


def test_plan_ablation_matrix_respects_max_experiment_and_cost_budget() -> None:
    tasks = plan_ablation_matrix(
        project_id="project-001",
        hypothesis=_hypothesis("latency_seconds"),
        variables=[
            AblationVariable(name="memory", control_value=True, ablated_value=False),
            AblationVariable(name="reranker", control_value=True, ablated_value=False),
            AblationVariable(name="cache", control_value=True, ablated_value=False),
            AblationVariable(name="prompt", control_value="full", ablated_value="short"),
        ],
        config=AblationPlanningConfig(
            max_experiments=3,
            max_total_cpu_time_seconds=500,
            per_experiment_cpu_time_seconds=200,
            timeout_seconds=200,
        ),
    )

    assert len(tasks) == 2
    assert sum(task.resource_budget["cpu_time_seconds"] for task in tasks) <= 500
    assert all(task.resource_budget["gpu_hours"] == 0.0 for task in tasks)
    assert [task.metadata["ablation"]["variable"] for task in tasks] == [
        "memory",
        "reranker",
    ]
