"""Deterministic experiment task planning from hypotheses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from autoresearch.schemas import ExperimentTask, Hypothesis, TaskStatus

AblationValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class ExperimentPlanningConfig:
    """Resource limits for generated experiment tasks."""

    max_cpu_time_seconds: int = 1800
    max_memory_mb: int = 4096
    max_gpu_hours: float = 0.0
    max_storage_mb: int = 512
    timeout_seconds: int = 1800


@dataclass(frozen=True)
class AblationVariable:
    """One hypothesis variable to ablate."""

    name: str
    control_value: AblationValue
    ablated_value: AblationValue


@dataclass(frozen=True)
class AblationPlanningConfig:
    """Budget limits for one-factor ablation planning."""

    max_experiments: int = 4
    max_total_cpu_time_seconds: int = 3600
    max_total_gpu_hours: float = 0.0
    per_experiment_cpu_time_seconds: int = 600
    per_experiment_memory_mb: int = 2048
    per_experiment_gpu_hours: float = 0.0
    per_experiment_storage_mb: int = 256
    timeout_seconds: int = 600


class AblationPlanningError(RuntimeError):
    """Raised when ablation planning inputs or budgets are invalid."""


def plan_experiment_tasks(
    *,
    project_id: str,
    hypotheses: list[Hypothesis],
    config: ExperimentPlanningConfig = ExperimentPlanningConfig(),
) -> list[ExperimentTask]:
    """Create deterministic experiment task records for hypotheses."""

    return [_task_from_hypothesis(project_id, hypothesis, config) for hypothesis in hypotheses]


def plan_ablation_matrix(
    *,
    project_id: str,
    hypothesis: Hypothesis,
    variables: list[AblationVariable],
    config: AblationPlanningConfig = AblationPlanningConfig(),
) -> list[ExperimentTask]:
    """Create a budget-limited one-factor-at-a-time ablation matrix."""

    _validate_ablation_config(config)
    planned_count = min(len(variables), _budget_limited_count(config))
    return [
        _ablation_task(project_id, hypothesis, variable, config, index=index)
        for index, variable in enumerate(variables[:planned_count], start=1)
    ]


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


def _ablation_task(
    project_id: str,
    hypothesis: Hypothesis,
    variable: AblationVariable,
    config: AblationPlanningConfig,
    *,
    index: int,
) -> ExperimentTask:
    hypothesis_slug = _slug(hypothesis.id)
    variable_slug = _slug(variable.name)
    return ExperimentTask(
        id=f"ablation_{hypothesis_slug}_{variable_slug}",
        project_id=project_id,
        hypothesis_id=hypothesis.id,
        name=f"Ablate {variable.name} for {hypothesis.id}",
        description=(
            f"Run one-factor ablation {index} for hypothesis {hypothesis.id}: "
            f"set {variable.name} from {variable.control_value!r} to "
            f"{variable.ablated_value!r}."
        ),
        entrypoint=f"experiments/{hypothesis_slug}/ablations/{variable_slug}/run.py",
        config_path=f"experiments/{hypothesis_slug}/ablations/{variable_slug}/config.yaml",
        metrics=[hypothesis.metric],
        resource_budget={
            "cpu_time_seconds": config.per_experiment_cpu_time_seconds,
            "memory_mb": config.per_experiment_memory_mb,
            "gpu_hours": config.per_experiment_gpu_hours,
            "storage_mb": config.per_experiment_storage_mb,
        },
        timeout_seconds=config.timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
        ],
        dependencies=["python>=3.10"],
        priority=6,
        status=TaskStatus.DRAFT,
        metadata={
            "ablation": {
                "matrix_kind": "one_factor_at_a_time",
                "variable": variable.name,
                "control_value": variable.control_value,
                "ablated_value": variable.ablated_value,
                "index": index,
            },
            "budget_limits": {
                "max_experiments": config.max_experiments,
                "max_total_cpu_time_seconds": config.max_total_cpu_time_seconds,
                "max_total_gpu_hours": config.max_total_gpu_hours,
            },
            "dataset_assumptions": {
                "dataset_ref": hypothesis.dataset_ref or "local demo dataset",
                "baseline": hypothesis.baseline,
            },
            "validation_checks": [
                "baseline reproduction exists",
                "metrics.json exists",
                f"metric {hypothesis.metric} exists",
                "ablation uses exactly one changed variable",
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


def _validate_ablation_config(config: AblationPlanningConfig) -> None:
    if config.max_experiments < 0:
        msg = "max_experiments must be non-negative"
        raise AblationPlanningError(msg)
    if config.max_total_cpu_time_seconds < 0:
        msg = "max_total_cpu_time_seconds must be non-negative"
        raise AblationPlanningError(msg)
    if config.max_total_gpu_hours < 0:
        msg = "max_total_gpu_hours must be non-negative"
        raise AblationPlanningError(msg)
    if config.per_experiment_cpu_time_seconds <= 0:
        msg = "per_experiment_cpu_time_seconds must be positive"
        raise AblationPlanningError(msg)
    if config.per_experiment_gpu_hours < 0:
        msg = "per_experiment_gpu_hours must be non-negative"
        raise AblationPlanningError(msg)
    if config.timeout_seconds <= 0:
        msg = "timeout_seconds must be positive"
        raise AblationPlanningError(msg)


def _budget_limited_count(config: AblationPlanningConfig) -> int:
    cpu_limited_count = config.max_total_cpu_time_seconds // config.per_experiment_cpu_time_seconds
    limits = [config.max_experiments, cpu_limited_count]
    if config.per_experiment_gpu_hours > 0:
        limits.append(int(config.max_total_gpu_hours // config.per_experiment_gpu_hours))
    return max(min(limits), 0)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "variable"
