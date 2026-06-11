"""Validation reports for collected experiment results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.schemas import (
    ExecutionRun,
    ExecutionStatus,
    ResultBundle,
    ValidationStatus,
    file_hash,
)

MetricBounds = dict[str, tuple[float | None, float | None]]


@dataclass(frozen=True)
class ValidationIssue:
    """One validation issue found in a result bundle."""

    severity: ValidationStatus
    check: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "check": self.check,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationReport:
    """Stored validation report for one execution run."""

    run_id: str
    status: ValidationStatus
    issues: tuple[ValidationIssue, ...]
    json_path: str
    markdown_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "json_path": self.json_path,
            "markdown_path": self.markdown_path,
        }


def validate_result_bundle(
    experiment_dir: Path | str,
    run: ExecutionRun,
    bundle: ResultBundle,
    *,
    expected_metrics: list[str] | None = None,
    metric_bounds: MetricBounds | None = None,
    expected_artifacts: list[Path | str] | None = None,
    output_dir: Path | str | None = None,
) -> ValidationReport:
    """Validate an execution run and persist JSON and Markdown reports."""

    root = Path(experiment_dir).resolve()
    validation_dir = Path(output_dir).resolve() if output_dir is not None else root / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    issues: list[ValidationIssue] = []

    issues.extend(_validate_run_completion(run))
    issues.extend(_validate_metric_presence(bundle, expected_metrics or []))
    issues.extend(_validate_metric_bounds(bundle, metric_bounds or {}))
    issues.extend(_validate_artifacts(root, bundle, expected_artifacts or []))
    issues.extend(_validate_config_hash(root, run))
    issues.extend(_validate_data_hash(run))
    issues.extend(_validate_cost_record(run))

    status = _overall_status(issues)
    json_path = validation_dir / "validation-report.json"
    markdown_path = validation_dir / "validation-report.md"
    report = ValidationReport(
        run_id=run.id,
        status=status,
        issues=tuple(issues),
        json_path=json_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    _write_report_files(report, bundle, json_path, markdown_path)
    return report


def _validate_run_completion(run: ExecutionRun) -> list[ValidationIssue]:
    if run.status is ExecutionStatus.SUCCESS and run.end_time is not None:
        return []
    if run.status is ExecutionStatus.SUCCESS:
        return [
            ValidationIssue(
                ValidationStatus.WARNING,
                "run_completion",
                "run succeeded but end_time is missing",
            )
        ]
    return [
        ValidationIssue(
            ValidationStatus.FAILED,
            "run_completion",
            f"run status is {run.status.value}",
        )
    ]


def _validate_metric_presence(
    bundle: ResultBundle,
    expected_metrics: list[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for metric in expected_metrics:
        if metric not in bundle.metrics:
            issues.append(
                ValidationIssue(
                    ValidationStatus.FAILED,
                    "metric_presence",
                    f"missing metric {metric}",
                )
            )
    return issues


def _validate_metric_bounds(
    bundle: ResultBundle,
    metric_bounds: MetricBounds,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for metric, (lower, upper) in metric_bounds.items():
        if metric not in bundle.metrics:
            continue
        value = bundle.metrics[metric]
        if lower is not None and value < lower:
            issues.append(_metric_bound_issue(metric, value, f"below lower bound {lower}"))
        if upper is not None and value > upper:
            issues.append(_metric_bound_issue(metric, value, f"above upper bound {upper}"))
    return issues


def _metric_bound_issue(metric: str, value: float, detail: str) -> ValidationIssue:
    return ValidationIssue(
        ValidationStatus.FAILED,
        "metric_bounds",
        f"metric {metric}={value} is {detail}",
    )


def _validate_artifacts(
    root: Path,
    bundle: ResultBundle,
    expected_artifacts: list[Path | str],
) -> list[ValidationIssue]:
    artifact_set = set(bundle.artifacts)
    issues: list[ValidationIssue] = []
    for artifact in expected_artifacts:
        artifact_path = Path(artifact)
        artifact_key = artifact_path.as_posix()
        resolved = artifact_path if artifact_path.is_absolute() else root / artifact_path
        if artifact_key not in artifact_set or not resolved.exists():
            issues.append(
                ValidationIssue(
                    ValidationStatus.FAILED,
                    "artifact_existence",
                    f"missing artifact {artifact_key}",
                )
            )
    return issues


def _validate_config_hash(root: Path, run: ExecutionRun) -> list[ValidationIssue]:
    config_path = root / "config.yaml"
    if run.config_hash is None:
        return [
            ValidationIssue(
                ValidationStatus.WARNING,
                "config_hash",
                "run config_hash is missing",
            )
        ]
    if not config_path.exists():
        return [
            ValidationIssue(
                ValidationStatus.WARNING,
                "config_hash",
                "config.yaml is missing, so config_hash cannot be checked",
            )
        ]
    actual_hash = file_hash(config_path)
    if actual_hash != run.config_hash:
        return [
            ValidationIssue(
                ValidationStatus.FAILED,
                "config_hash",
                "config_hash does not match config.yaml",
            )
        ]
    return []


def _validate_data_hash(run: ExecutionRun) -> list[ValidationIssue]:
    if run.data_hash:
        return []
    return [
        ValidationIssue(
            ValidationStatus.WARNING,
            "data_hash",
            "run data_hash is missing",
        )
    ]


def _validate_cost_record(run: ExecutionRun) -> list[ValidationIssue]:
    if run.cost_record is not None or run.cost_json:
        return []
    return [
        ValidationIssue(
            ValidationStatus.WARNING,
            "cost_record",
            "run cost record is missing",
        )
    ]


def _overall_status(issues: list[ValidationIssue]) -> ValidationStatus:
    if any(issue.severity is ValidationStatus.FAILED for issue in issues):
        return ValidationStatus.FAILED
    if any(issue.severity is ValidationStatus.WARNING for issue in issues):
        return ValidationStatus.WARNING
    return ValidationStatus.PASSED


def _write_report_files(
    report: ValidationReport,
    bundle: ResultBundle,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report, bundle), encoding="utf-8")


def _markdown_report(report: ValidationReport, bundle: ResultBundle) -> str:
    issue_lines = [
        f"| {issue.severity.value} | {issue.check} | {issue.message} |"
        for issue in report.issues
    ]
    if not issue_lines:
        issue_lines = ["| passed | all | No validation issues. |"]
    metric_lines = [
        f"- `{name}`: {value}"
        for name, value in sorted(bundle.metrics.items())
    ] or ["- None"]
    artifact_lines = [f"- `{path}`" for path in bundle.artifacts] or ["- None"]
    return "\n".join(
        [
            "# Validation Report",
            "",
            f"- Run ID: `{report.run_id}`",
            f"- Status: `{report.status.value}`",
            "",
            "## Issues",
            "",
            "| Severity | Check | Message |",
            "| --- | --- | --- |",
            *issue_lines,
            "",
            "## Metrics",
            "",
            *metric_lines,
            "",
            "## Artifacts",
            "",
            *artifact_lines,
            "",
        ]
    )
