"""Local Markdown status report export for monitoring snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.observability.metrics import SystemMetricSnapshot


@dataclass(frozen=True)
class ProjectStatusSummary:
    """Reader-facing active project state for the local status report."""

    project_id: str
    title: str
    status: str
    active_task_ids: tuple[str, ...] = ()
    open_issue_count: int = 0
    last_run_id: str | None = None
    evidence_coverage: float | None = None


@dataclass(frozen=True)
class LocalStatusReport:
    """Written local status report artifact."""

    path: Path
    report_format: str
    project_states: tuple[ProjectStatusSummary, ...]


def export_local_status_report(
    *,
    metrics: SystemMetricSnapshot,
    output_path: Path | str,
    project_states: tuple[ProjectStatusSummary, ...] = (),
    title: str = "AI-Researcher Local Status",
    generated_at: datetime | None = None,
) -> LocalStatusReport:
    """Write a static Markdown status report from computed system metrics."""

    timestamp = generated_at or datetime.now(timezone.utc)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_markdown(
            title=title,
            generated_at=timestamp,
            metrics=metrics,
            project_states=project_states,
        ),
        encoding="utf-8",
    )
    return LocalStatusReport(
        path=path,
        report_format="markdown",
        project_states=project_states,
    )


def _render_markdown(
    *,
    title: str,
    generated_at: datetime,
    metrics: SystemMetricSnapshot,
    project_states: tuple[ProjectStatusSummary, ...],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Generated at: `{generated_at.isoformat()}`",
        f"- Total runs: `{metrics.total_runs}`",
        f"- Total tasks: `{metrics.total_tasks}`",
        "",
        "## System Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Task success rate | {_percent(metrics.task_success_rate)} |",
        f"| Task failure rate | {_percent(1.0 - metrics.task_success_rate)} |",
        f"| Experiment reproduction rate | {_percent(metrics.experiment_reproduction_rate)} |",
        f"| Validator rejection rate | {_percent(metrics.validator_rejection_rate)} |",
        f"| Citation error rate | {_percent(metrics.citation_error_rate)} |",
        f"| Evidence coverage | {_percent(metrics.evidence_coverage)} |",
        f"| Agent loop depth | {metrics.agent_loop_depth:.2f} |",
        f"| Rollback count | {metrics.rollback_count} |",
        "",
        "## Cost And Intervention",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total cost | {metrics.total_cost:.6f} |",
        f"| Average cost per success | {metrics.avg_cost_per_success:.6f} |",
        f"| Human intervention count | {metrics.human_intervention_count} |",
        f"| Average human interventions | {metrics.avg_human_interventions:.6f} |",
        "",
        "## Active Projects",
        "",
    ]
    lines.extend(_project_lines(project_states))
    return "\n".join(lines).rstrip() + "\n"


def _project_lines(project_states: tuple[ProjectStatusSummary, ...]) -> list[str]:
    if not project_states:
        return ["- No active projects recorded."]

    lines = [
        "| Project ID | Title | Status | Active Tasks | Open Issues | Last Run | Evidence Coverage |",
        "|---|---|---|---|---:|---|---:|",
    ]
    for project in project_states:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(project.project_id),
                    _cell(project.title),
                    _cell(project.status),
                    _cell(", ".join(project.active_task_ids) or "none"),
                    str(project.open_issue_count),
                    _cell(project.last_run_id or "none"),
                    _percent(project.evidence_coverage) if project.evidence_coverage is not None else "unknown",
                ]
            )
            + " |"
        )
    return lines


def _percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2%}"


def _cell(value: str) -> str:
    return value.replace("|", "\\|")
