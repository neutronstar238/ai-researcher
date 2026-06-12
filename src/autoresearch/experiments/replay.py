"""Offline replay datasets for strategy evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.experiments.validation import ValidationReport
from autoresearch.schemas import (
    EvidenceEdge,
    ExecutionRun,
    ExperimentTask,
    ResultBundle,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReplayCase(BaseModel):
    """A historical task snapshot that can be replayed offline."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    task_id: str
    run_id: str
    baseline_metric: str
    baseline_score: float
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    costs: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any]


class ReplayDataset(BaseModel):
    """Serializable replay fixture assembled from historical runs."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    cases: tuple[ReplayCase, ...]
    created_at: datetime = Field(default_factory=_utc_now)

    def baseline_score(self, metric_name: str) -> float:
        """Return the mean baseline score for usable cases with the metric."""

        scores = [
            case.baseline_score
            for case in self.cases
            if case.baseline_metric == metric_name
            and case.validation.get("status") in {"passed", "warning"}
        ]
        if not scores:
            msg = f"no replay cases with usable baseline metric {metric_name!r}"
            raise ValueError(msg)
        return round(sum(scores) / len(scores), 6)


def build_replay_case(
    *,
    task: ExperimentTask,
    run: ExecutionRun,
    results: ResultBundle,
    validation: ValidationReport,
    baseline_metric: str,
    evidence_edges: tuple[EvidenceEdge, ...] = (),
) -> ReplayCase:
    """Capture enough historical state to replay a strategy decision offline."""

    if run.task_id != task.id:
        msg = f"run task_id {run.task_id!r} does not match task id {task.id!r}"
        raise ValueError(msg)
    if results.run_id != run.id:
        msg = f"result run_id {results.run_id!r} does not match run id {run.id!r}"
        raise ValueError(msg)
    if validation.run_id != run.id:
        msg = f"validation run_id {validation.run_id!r} does not match run id {run.id!r}"
        raise ValueError(msg)
    if baseline_metric not in results.metrics:
        msg = f"baseline metric {baseline_metric!r} missing from result metrics"
        raise ValueError(msg)

    return ReplayCase(
        case_id=f"replay_{task.id}_{run.id}",
        task_id=task.id,
        run_id=run.id,
        baseline_metric=baseline_metric,
        baseline_score=results.metrics[baseline_metric],
        inputs={
            "task": task.model_dump(mode="json"),
            "run": run.model_dump(mode="json"),
        },
        outputs={
            "result": results.model_dump(mode="json"),
            "metrics": dict(results.metrics),
            "artifacts": list(results.artifacts),
            "logs": list(results.logs),
            "summary": results.summary,
        },
        evidence=[edge.model_dump(mode="json") for edge in evidence_edges],
        costs={
            "cost_record": run.cost_record.model_dump(mode="json")
            if run.cost_record is not None
            else None,
            "cost_json": dict(run.cost_json),
        },
        validation=validation.to_dict(),
    )


def write_replay_dataset(path: Path | str, dataset: ReplayDataset) -> Path:
    """Persist a replay dataset as deterministic JSON."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dataset.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_replay_dataset(path: Path | str) -> ReplayDataset:
    """Load a replay dataset from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ReplayDataset.model_validate(payload)
