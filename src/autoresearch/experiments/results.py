"""Collect experiment outputs into result bundles."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from autoresearch.experiments.sandbox import SandboxAccessMode, SandboxPathPolicy
from autoresearch.schemas import ExecutionRun, ExecutionStatus, ResultBundle, ValidationStatus


class ResultCollectionError(RuntimeError):
    """Raised when experiment outputs are incomplete or invalid."""


def collect_result_bundle(
    experiment_dir: Path | str,
    run: ExecutionRun,
    *,
    csv_outputs: list[Path | str] | None = None,
) -> ResultBundle:
    """Collect metrics, logs, and artifacts from an experiment directory."""

    root = Path(experiment_dir).resolve()
    policy = SandboxPathPolicy(root)
    metrics_path = policy.require_access(_metrics_path(root, run), SandboxAccessMode.READ)
    metrics = _collect_metrics(metrics_path, run)
    artifacts = _collect_artifacts(root)
    logs = _collect_logs(root)

    for csv_output in csv_outputs or []:
        csv_path = policy.require_access(csv_output, SandboxAccessMode.READ)
        if not csv_path.exists():
            if _run_explicitly_failed(run):
                continue
            msg = f"configured CSV output is missing: {Path(csv_output).as_posix()}"
            raise ResultCollectionError(msg)
        metrics.update(_metrics_from_csv(csv_path))
        artifacts.append(_relative_path(root, csv_path))

    return ResultBundle(
        run_id=run.id,
        metrics=metrics,
        artifacts=sorted(set(artifacts)),
        logs=logs,
        summary=_summary_text(root),
        validation_status=(
            ValidationStatus.PASSED
            if run.status is ExecutionStatus.SUCCESS
            else ValidationStatus.FAILED
        ),
    )


def _metrics_path(root: Path, run: ExecutionRun) -> Path:
    if run.metrics_path is None:
        return root / "metrics.json"
    path = Path(run.metrics_path)
    return path if path.is_absolute() else root / path


def _collect_metrics(metrics_path: Path, run: ExecutionRun) -> dict[str, float]:
    if not metrics_path.exists():
        if _run_explicitly_failed(run):
            return {}
        msg = f"metrics file is missing: {metrics_path.as_posix()}"
        raise ResultCollectionError(msg)

    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"metrics file is not valid JSON: {metrics_path.as_posix()}"
        raise ResultCollectionError(msg) from exc

    metric_payload = payload.get("metrics", payload) if isinstance(payload, dict) else {}
    if not isinstance(metric_payload, dict):
        msg = "metrics payload must be a JSON object"
        raise ResultCollectionError(msg)
    return _coerce_metrics(metric_payload)


def _metrics_from_csv(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    metrics: dict[str, float] = {}
    for row in rows:
        metric_name = row.get("metric")
        value = row.get("value")
        if metric_name and value is not None:
            metrics[metric_name] = _coerce_metric_value(metric_name, value)
    return metrics


def _collect_artifacts(root: Path) -> list[str]:
    artifacts_dir = root / "artifacts"
    if not artifacts_dir.exists():
        return []
    return [
        _relative_path(root, path)
        for path in artifacts_dir.rglob("*")
        if path.is_file()
    ]


def _collect_logs(root: Path) -> list[str]:
    logs_dir = root / "logs"
    if not logs_dir.exists():
        return []
    return sorted(
        _relative_path(root, path)
        for path in logs_dir.rglob("*")
        if path.is_file()
    )


def _summary_text(root: Path) -> str | None:
    summary_path = root / "artifacts" / "summary.md"
    if not summary_path.exists():
        return None
    return summary_path.read_text(encoding="utf-8")


def _coerce_metrics(payload: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            metrics[name] = float(value)
    return metrics


def _coerce_metric_value(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        msg = f"CSV metric {name!r} is not numeric"
        raise ResultCollectionError(msg) from exc


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _run_explicitly_failed(run: ExecutionRun) -> bool:
    return run.status in {
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.CANCELLED,
    }
