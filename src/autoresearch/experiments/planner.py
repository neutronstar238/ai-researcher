"""Deterministic experiment task planning from hypotheses."""

from __future__ import annotations

from dataclasses import dataclass

from autoresearch.schemas import ExperimentTask, Hypothesis, TaskStatus


@dataclass(frozen=True)
class ExperimentPlanningConfig:
    """Resource limits for generated experiment tasks."""

    max_cpu_time_seconds: int = 1800
    max_memory_mb: int = 4096
    max_gpu_hours: float = 0.0
    max_storage_mb: int = 512
    timeout_seconds: int = 1800


def plan_experiment_tasks(
    *,
    project_id: str,
    hypotheses: list[Hypothesis],
    config: ExperimentPlanningConfig = ExperimentPlanningConfig(),
) -> list[ExperimentTask]:
    """Create deterministic experiment task records for hypotheses."""

    return [_task_from_hypothesis(project_id, hypothesis, config) for hypothesis in hypotheses]


def _task_from_hypothesis(
    project_id: str,
    hypothesis: Hypothesis,
    config: ExperimentPlanningConfig,
) -> ExperimentTask:
    task_slug = hypothesis.id.replace("_", "-")
    metric_direction = _metric_direction(hypothesis.metric)
    return ExperimentTask(
        project_id=project_id,
        hypothesis_id=hypothesis.id,
        name=f"Evaluate {hypothesis.metric} for {hypothesis.id}",
        description=(
            f"Run a deterministic MVP experiment for hypothesis {hypothesis.id}: "
            f"{hypothesis.statement}"
        ),
        entrypoint=f"experiments/{task_slug}/run.py",
        config_path=f"experiments/{task_slug}/config.yaml",
        metrics=[hypothesis.metric],
        resource_budget={
            "cpu_time_seconds": min(config.max_cpu_time_seconds, config.timeout_seconds),
            "memory_mb": config.max_memory_mb,
            "gpu_hours": config.max_gpu_hours,
            "storage_mb": config.max_storage_mb,
        },
        timeout_seconds=config.timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
        ],
        dependencies=["python>=3.10"],
        priority=5,
        status=TaskStatus.DRAFT,
        metadata={
            "dataset_assumptions": {
                "dataset_ref": hypothesis.dataset_ref or "local demo dataset",
                "baseline": hypothesis.baseline,
            },
            "validation_checks": [
                "metrics.json exists",
                f"metric {hypothesis.metric} exists",
                f"metric direction is {metric_direction}",
                "logs/run.log exists",
            ],
            "evidence_refs": hypothesis.evidence_refs,
        },
    )


def _metric_direction(metric: str) -> str:
    normalized = metric.casefold()
    if "cost" in normalized or "latency" in normalized or "loss" in normalized:
        return "lower_is_better"
    return "higher_is_better"
