"""Local Markdown status report export for monitoring snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
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


@dataclass(frozen=True)
class RunStatusSummary:
    """Reader-facing run row for the local dashboard."""

    run_id: str
    project_id: str
    task_id: str
    status: str
    validation_status: str
    cost: float
    evidence_coverage: float | None = None


@dataclass(frozen=True)
class FailureStatusSummary:
    """Reader-facing failure row for the local dashboard."""

    failure_id: str
    project_id: str
    severity: str
    status: str
    summary: str
    source_ref: str | None = None


@dataclass(frozen=True)
class ApprovalQueueSummary:
    """Reader-facing approval queue row for the local dashboard."""

    approval_id: str
    approval_type: str
    project_id: str
    status: str
    requested_by: str
    summary: str
    source_ref: str | None = None


@dataclass(frozen=True)
class LocalDashboardHtml:
    """Written local HTML dashboard artifact."""

    path: Path
    report_format: str
    project_states: tuple[ProjectStatusSummary, ...]
    runs: tuple[RunStatusSummary, ...]
    failures: tuple[FailureStatusSummary, ...]
    approval_queue: tuple[ApprovalQueueSummary, ...]


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


def export_local_dashboard_html(
    *,
    metrics: SystemMetricSnapshot,
    output_path: Path | str,
    project_states: tuple[ProjectStatusSummary, ...] = (),
    runs: tuple[RunStatusSummary, ...] = (),
    failures: tuple[FailureStatusSummary, ...] = (),
    approval_queue: tuple[ApprovalQueueSummary, ...] = (),
    title: str = "AI-Researcher Dashboard",
    generated_at: datetime | None = None,
) -> LocalDashboardHtml:
    """Write a static operational dashboard that can be opened in a browser."""

    timestamp = generated_at or datetime.now(timezone.utc)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_html(
            title=title,
            generated_at=timestamp,
            metrics=metrics,
            project_states=project_states,
            runs=runs,
            failures=failures,
            approval_queue=approval_queue,
        ),
        encoding="utf-8",
    )
    return LocalDashboardHtml(
        path=path,
        report_format="html",
        project_states=project_states,
        runs=runs,
        failures=failures,
        approval_queue=approval_queue,
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


def _render_html(
    *,
    title: str,
    generated_at: datetime,
    metrics: SystemMetricSnapshot,
    project_states: tuple[ProjectStatusSummary, ...],
    runs: tuple[RunStatusSummary, ...],
    failures: tuple[FailureStatusSummary, ...],
    approval_queue: tuple[ApprovalQueueSummary, ...],
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-strong: #eef2f6;
      --text: #17202a;
      --muted: #5d6b7a;
      --line: #d7dde5;
      --accent: #2563eb;
      --good: #087f5b;
      --warn: #b7791f;
      --bad: #b42318;
      --blocked: #5b21b6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      line-height: 1.5;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      backdrop-filter: blur(12px);
    }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 18px 20px; }}
    .topbar {{ display: flex; gap: 16px; align-items: center; justify-content: space-between; }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.2; letter-spacing: 0; }}
    .timestamp {{ color: var(--muted); font-size: 13px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    nav a {{
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      background: var(--surface);
      font-size: 13px;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px 20px 36px; }}
    section {{ margin-top: 22px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; line-height: 1.3; letter-spacing: 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 14px;
      min-height: 92px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 24px; line-height: 1.1; }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
    }}
    .panel-tools {{
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      padding: 12px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-strong);
    }}
    label {{ color: var(--muted); font-size: 13px; }}
    input {{
      min-width: 240px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      background: var(--surface);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; background: #fafbfc; }}
    tr:last-child td {{ border-bottom: 0; }}
    .status {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      background: var(--surface-strong);
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .status.success, .status.passed, .status.active {{ color: var(--good); }}
    .status.warning, .status.pending {{ color: var(--warn); }}
    .status.failed, .status.error {{ color: var(--bad); }}
    .status.blocked, .status.approval_required {{ color: var(--blocked); }}
    .empty {{ color: var(--muted); padding: 14px; }}
    .source {{ color: var(--accent); font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; }}
    @media (max-width: 760px) {{
      .shell, main {{ padding-left: 14px; padding-right: 14px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .panel {{ overflow-x: auto; }}
      .panel-tools {{ align-items: flex-start; flex-direction: column; }}
      input {{ width: 100%; min-width: 0; }}
      table {{ min-width: 720px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="shell">
      <div class="topbar">
        <h1>{_html(title)}</h1>
        <div class="timestamp">Generated {_html(generated_at.isoformat())}</div>
      </div>
      <nav aria-label="Dashboard sections">
        <a href="#projects">Projects</a>
        <a href="#runs">Runs</a>
        <a href="#failures">Failures</a>
        <a href="#costs">Costs</a>
        <a href="#evidence">Evidence</a>
        <a href="#approvals">Approval Queue</a>
      </nav>
    </div>
  </header>
  <main>
    <section aria-labelledby="overview-title">
      <h2 id="overview-title">Overview</h2>
      <div class="metrics">
        {_metric_card("Project status", f"{len(project_states)} active")}
        {_metric_card("Runs", str(metrics.total_runs))}
        {_metric_card("Failures", _percent(1.0 - metrics.task_success_rate))}
        {_metric_card("Evidence coverage", _percent(metrics.evidence_coverage))}
      </div>
    </section>
    <section id="projects" aria-labelledby="projects-title">
      <h2 id="projects-title">Project Status</h2>
      <div class="panel">{_projects_table(project_states)}</div>
    </section>
    <section id="runs" aria-labelledby="runs-title">
      <h2 id="runs-title">Runs</h2>
      <div class="panel">
        <div class="panel-tools">
          <label for="run-filter">Filter runs by project, task, status, or validation</label>
          <input id="run-filter" data-run-filter type="search" placeholder="Filter runs">
          <span id="run-count">{len(runs)} visible</span>
        </div>
        {_runs_table(runs)}
      </div>
    </section>
    <section id="failures" aria-labelledby="failures-title">
      <h2 id="failures-title">Failures</h2>
      <div class="panel">{_failures_table(failures)}</div>
    </section>
    <section id="costs" aria-labelledby="costs-title">
      <h2 id="costs-title">Costs</h2>
      <div class="metrics">
        {_metric_card("Total cost", f"{metrics.total_cost:.6f}")}
        {_metric_card("Cost per success", f"{metrics.avg_cost_per_success:.6f}")}
        {_metric_card("Human interventions", str(metrics.human_intervention_count))}
        {_metric_card("Avg interventions", f"{metrics.avg_human_interventions:.6f}")}
      </div>
    </section>
    <section id="evidence" aria-labelledby="evidence-title">
      <h2 id="evidence-title">Evidence Coverage</h2>
      <div class="metrics">
        {_metric_card("Covered claims", f"{metrics.covered_claims}/{metrics.total_claims}")}
        {_metric_card("Citation error rate", _percent(metrics.citation_error_rate))}
        {_metric_card("Validator rejection", _percent(metrics.validator_rejection_rate))}
        {_metric_card("Reproduction rate", _percent(metrics.experiment_reproduction_rate))}
      </div>
    </section>
    <section id="approvals" aria-labelledby="approvals-title">
      <h2 id="approvals-title">Approval Queue</h2>
      <div class="panel">{_approval_table(approval_queue)}</div>
    </section>
  </main>
  <script>
    const input = document.querySelector("[data-run-filter]");
    const rows = Array.from(document.querySelectorAll("[data-run-row]"));
    const count = document.getElementById("run-count");
    function applyRunFilter() {{
      const term = input.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach((row) => {{
        const match = row.textContent.toLowerCase().includes(term);
        row.hidden = !match;
        if (match) visible += 1;
      }});
      count.textContent = `${{visible}} visible`;
    }}
    input.addEventListener("input", applyRunFilter);
  </script>
</body>
</html>
"""


def _metric_card(label: str, value: str) -> str:
    return (
        '<article class="metric">'
        f"<span>{_html(label)}</span><strong>{_html(value)}</strong>"
        "</article>"
    )


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


def _projects_table(project_states: tuple[ProjectStatusSummary, ...]) -> str:
    if not project_states:
        return '<p class="empty">No active projects recorded.</p>'
    rows = [
        "<table><thead><tr><th>Project</th><th>Title</th><th>Status</th>"
        "<th>Active Tasks</th><th>Open Issues</th><th>Last Run</th>"
        "<th>Evidence</th></tr></thead><tbody>"
    ]
    for project in project_states:
        rows.append(
            "<tr>"
            f"<td>{_html(project.project_id)}</td>"
            f"<td>{_html(project.title)}</td>"
            f"<td>{_status(project.status)}</td>"
            f"<td>{_html(', '.join(project.active_task_ids) or 'none')}</td>"
            f"<td>{project.open_issue_count}</td>"
            f"<td>{_html(project.last_run_id or 'none')}</td>"
            f"<td>{_html(_percent(project.evidence_coverage))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def _runs_table(runs: tuple[RunStatusSummary, ...]) -> str:
    if not runs:
        return '<p class="empty">No runs recorded.</p>'
    rows = [
        "<table><thead><tr><th>Run</th><th>Project</th><th>Task</th>"
        "<th>Status</th><th>Validation</th><th>Cost</th><th>Evidence</th>"
        "</tr></thead><tbody>"
    ]
    for run in runs:
        rows.append(
            '<tr data-run-row="true">'
            f"<td>{_html(run.run_id)}</td>"
            f"<td>{_html(run.project_id)}</td>"
            f"<td>{_html(run.task_id)}</td>"
            f"<td>{_status(run.status)}</td>"
            f"<td>{_status(run.validation_status)}</td>"
            f"<td>{run.cost:.6f}</td>"
            f"<td>{_html(_percent(run.evidence_coverage))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def _failures_table(failures: tuple[FailureStatusSummary, ...]) -> str:
    if not failures:
        return '<p class="empty">No active failures recorded.</p>'
    rows = [
        "<table><thead><tr><th>Failure</th><th>Project</th><th>Severity</th>"
        "<th>Status</th><th>Summary</th><th>Source</th></tr></thead><tbody>"
    ]
    for failure in failures:
        rows.append(
            "<tr>"
            f"<td>{_html(failure.failure_id)}</td>"
            f"<td>{_html(failure.project_id)}</td>"
            f"<td>{_status(failure.severity)}</td>"
            f"<td>{_status(failure.status)}</td>"
            f"<td>{_html(failure.summary)}</td>"
            f"<td>{_source(failure.source_ref)}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def _approval_table(approval_queue: tuple[ApprovalQueueSummary, ...]) -> str:
    if not approval_queue:
        return '<p class="empty">No approvals waiting.</p>'
    rows = [
        "<table><thead><tr><th>Approval</th><th>Type</th><th>Project</th>"
        "<th>Status</th><th>Requested By</th><th>Summary</th><th>Source</th>"
        "</tr></thead><tbody>"
    ]
    for item in approval_queue:
        rows.append(
            "<tr>"
            f"<td>{_html(item.approval_id)}</td>"
            f"<td>{_html(item.approval_type)}</td>"
            f"<td>{_html(item.project_id)}</td>"
            f"<td>{_status(item.status)}</td>"
            f"<td>{_html(item.requested_by)}</td>"
            f"<td>{_html(item.summary)}</td>"
            f"<td>{_source(item.source_ref)}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def _status(value: str) -> str:
    normalized = value.strip().casefold().replace(" ", "_")
    return f'<span class="status {normalized}">{_html(value)}</span>'


def _source(value: str | None) -> str:
    if value is None:
        return "none"
    return f'<span class="source">{_html(value)}</span>'


def _html(value: str) -> str:
    return escape(value, quote=True)
