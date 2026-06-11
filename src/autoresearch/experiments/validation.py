"""Validation reports for collected experiment results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

from autoresearch.schemas import (
    ExecutionRun,
    ExecutionStatus,
    ResultBundle,
    ValidationStatus,
    file_hash,
)

MetricBounds = dict[str, tuple[float | None, float | None]]
StatisticalDetails = dict[str, float | int | str]


@dataclass(frozen=True)
class StatisticalCheck:
    """Statistical sanity inputs for one reported metric."""

    metric_name: str
    sample_size: int
    mean: float | None = None
    standard_error: float | None = None
    baseline_mean: float | None = None
    comparison_mean: float | None = None
    min_sample_size: int = 30
    confidence_level: float = 0.95


@dataclass(frozen=True)
class StatisticalNote:
    """One non-blocking statistical note included in a validation report."""

    metric_name: str
    check: str
    message: str
    details: StatisticalDetails

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "check": self.check,
            "message": self.message,
            "details": self.details,
        }


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
    statistical_notes: tuple[StatisticalNote, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "json_path": self.json_path,
            "markdown_path": self.markdown_path,
            "statistical_notes": [note.to_dict() for note in self.statistical_notes],
        }


def validate_result_bundle(
    experiment_dir: Path | str,
    run: ExecutionRun,
    bundle: ResultBundle,
    *,
    expected_metrics: list[str] | None = None,
    metric_bounds: MetricBounds | None = None,
    expected_artifacts: list[Path | str] | None = None,
    statistical_checks: list[StatisticalCheck] | None = None,
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
    statistical_issues, statistical_notes = _validate_statistical_checks(
        statistical_checks or []
    )
    issues.extend(statistical_issues)

    status = _overall_status(issues)
    json_path = validation_dir / "validation-report.json"
    markdown_path = validation_dir / "validation-report.md"
    report = ValidationReport(
        run_id=run.id,
        status=status,
        issues=tuple(issues),
        json_path=json_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        statistical_notes=tuple(statistical_notes),
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


def _validate_statistical_checks(
    checks: list[StatisticalCheck],
) -> tuple[list[ValidationIssue], list[StatisticalNote]]:
    issues: list[ValidationIssue] = []
    notes: list[StatisticalNote] = []
    for check in checks:
        input_issues = _validate_statistical_check_input(check)
        if input_issues:
            issues.extend(input_issues)
            continue

        if check.sample_size < check.min_sample_size:
            issues.append(
                ValidationIssue(
                    ValidationStatus.WARNING,
                    "statistical_power",
                    (
                        f"metric {check.metric_name} comparison is underpowered: "
                        f"sample size {check.sample_size} below minimum "
                        f"{check.min_sample_size}; do not overstate significance"
                    ),
                )
            )
            notes.append(
                StatisticalNote(
                    metric_name=check.metric_name,
                    check="statistical_power",
                    message=(
                        f"underpowered comparison; n={check.sample_size}, "
                        f"minimum={check.min_sample_size}"
                    ),
                    details={
                        "sample_size": check.sample_size,
                        "min_sample_size": check.min_sample_size,
                    },
                )
            )

        if check.mean is not None and check.standard_error is not None:
            lower, upper = _confidence_interval(
                check.mean,
                check.standard_error,
                check.confidence_level,
            )
            percent = round(check.confidence_level * 100, 2)
            notes.append(
                StatisticalNote(
                    metric_name=check.metric_name,
                    check="confidence_interval",
                    message=(
                        f"{percent:g}% CI for {check.metric_name} mean: "
                        f"[{lower:.6g}, {upper:.6g}]"
                    ),
                    details={
                        "sample_size": check.sample_size,
                        "confidence_level": check.confidence_level,
                        "mean": check.mean,
                        "standard_error": check.standard_error,
                        "lower": lower,
                        "upper": upper,
                    },
                )
            )

        if check.baseline_mean is not None and check.comparison_mean is not None:
            delta = round(check.comparison_mean - check.baseline_mean, 6)
            notes.append(
                StatisticalNote(
                    metric_name=check.metric_name,
                    check="repeated_run_delta",
                    message=(
                        f"repeated-run comparison delta for {check.metric_name}: "
                        f"{delta:.6g}"
                    ),
                    details={
                        "sample_size": check.sample_size,
                        "baseline_mean": check.baseline_mean,
                        "comparison_mean": check.comparison_mean,
                        "delta": delta,
                    },
                )
            )
    return issues, notes


def _validate_statistical_check_input(
    check: StatisticalCheck,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not check.metric_name:
        issues.append(_statistical_input_issue("metric name is missing"))
    if check.sample_size <= 0:
        issues.append(
            _statistical_input_issue(
                f"metric {check.metric_name} sample_size must be positive"
            )
        )
    if check.min_sample_size <= 0:
        issues.append(
            _statistical_input_issue(
                f"metric {check.metric_name} min_sample_size must be positive"
            )
        )
    if not 0.0 < check.confidence_level < 1.0:
        issues.append(
            _statistical_input_issue(
                f"metric {check.metric_name} confidence_level must be between 0 and 1"
            )
        )
    if check.standard_error is not None and check.standard_error < 0.0:
        issues.append(
            _statistical_input_issue(
                f"metric {check.metric_name} standard_error must be non-negative"
            )
        )
    return issues


def _statistical_input_issue(message: str) -> ValidationIssue:
    return ValidationIssue(
        ValidationStatus.FAILED,
        "statistical_input",
        message,
    )


def _confidence_interval(
    mean: float,
    standard_error: float,
    confidence_level: float,
) -> tuple[float, float]:
    z_value = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    margin = z_value * standard_error
    return round(mean - margin, 6), round(mean + margin, 6)


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
    statistical_lines = [
        f"- `{note.metric_name}` `{note.check}`: {note.message}"
        for note in report.statistical_notes
    ] or ["- None"]
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
            "## Statistical Sanity",
            "",
            *statistical_lines,
            "",
            "## Artifacts",
            "",
            *artifact_lines,
            "",
        ]
    )
