"""Convert review findings into structured follow-up backlog records."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .review import PaperReviewReport, ReviewDimension, ReviewFinding


class ReviewBacklogRecordType(str, Enum):
    """Backlog record categories produced from review findings."""

    FOLLOW_UP_TASK = "follow_up_task"
    PROBLEM_ENTRY = "problem_entry"


@dataclass(frozen=True)
class ReviewBacklogRecord:
    """One structured follow-up record derived from a review finding."""

    record_id: str
    record_type: ReviewBacklogRecordType
    title: str
    description: str
    action: str
    dimension: ReviewDimension
    severity: str
    priority: int
    source_review_title: str
    source_venue: str
    project_id: str | None = None
    source_task_id: str | None = None
    problem_markdown: str | None = None
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type.value,
            "title": self.title,
            "description": self.description,
            "action": self.action,
            "dimension": self.dimension.value,
            "severity": self.severity,
            "priority": self.priority,
            "source_review_title": self.source_review_title,
            "source_venue": self.source_venue,
            "project_id": self.project_id,
            "source_task_id": self.source_task_id,
            "problem_markdown": self.problem_markdown,
            "status": self.status,
        }


@dataclass(frozen=True)
class ReviewBacklogArtifact:
    """Backlog records and optional artifact paths."""

    records: tuple[ReviewBacklogRecord, ...]
    json_path: str | None = None
    markdown_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "json_path": self.json_path,
            "markdown_path": self.markdown_path,
        }


def create_review_backlog(
    report: PaperReviewReport,
    *,
    project_id: str | None = None,
    source_task_id: str | None = None,
    output_dir: Path | str | None = None,
) -> ReviewBacklogArtifact:
    """Create structured follow-up records from actionable review findings."""

    records = tuple(
        _record_from_finding(
            report=report,
            finding=finding,
            index=index,
            project_id=project_id,
            source_task_id=source_task_id,
        )
        for index, finding in enumerate(report.findings, start=1)
    )
    if output_dir is None:
        return ReviewBacklogArtifact(records=records)

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "review-backlog.json"
    markdown_path = target_dir / "review-backlog.md"
    json_path.write_text(
        json.dumps(
            {"records": [record.to_dict() for record in records]},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(_backlog_markdown(report, records), encoding="utf-8")
    return ReviewBacklogArtifact(
        records=records,
        json_path=json_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )


def _record_from_finding(
    *,
    report: PaperReviewReport,
    finding: ReviewFinding,
    index: int,
    project_id: str | None,
    source_task_id: str | None,
) -> ReviewBacklogRecord:
    record_type = _record_type(finding.severity)
    record_id = _record_id(report.title, finding.dimension, index)
    title = f"{finding.dimension.value}: {finding.action}"
    problem_markdown = (
        _problem_markdown(record_id, title, finding, report, project_id, source_task_id)
        if record_type is ReviewBacklogRecordType.PROBLEM_ENTRY
        else None
    )
    return ReviewBacklogRecord(
        record_id=record_id,
        record_type=record_type,
        title=title,
        description=finding.message,
        action=finding.action,
        dimension=finding.dimension,
        severity=finding.severity,
        priority=_priority(finding.severity),
        source_review_title=report.title,
        source_venue=report.criteria.venue,
        project_id=project_id,
        source_task_id=source_task_id,
        problem_markdown=problem_markdown,
    )


def _record_type(severity: str) -> ReviewBacklogRecordType:
    if severity.casefold() in {"critical", "high"}:
        return ReviewBacklogRecordType.PROBLEM_ENTRY
    return ReviewBacklogRecordType.FOLLOW_UP_TASK


def _priority(severity: str) -> int:
    severity_key = severity.casefold()
    if severity_key in {"critical", "high"}:
        return 1
    if severity_key == "medium":
        return 2
    return 3


def _record_id(title: str, dimension: ReviewDimension, index: int) -> str:
    return f"review-{_slug(title)}-{index:02d}-{dimension.value}"


def _problem_markdown(
    record_id: str,
    title: str,
    finding: ReviewFinding,
    report: PaperReviewReport,
    project_id: str | None,
    source_task_id: str | None,
) -> str:
    problem_id = f"P-REVIEW-{record_id.removeprefix('review-').upper()}"
    return "\n".join(
        [
            f"### {problem_id} - {title}",
            "",
            "- Status: Open",
            f"- Severity: {finding.severity.title()}",
            "- Discovered: review simulator backlog conversion",
            f"- Source: `{report.title}` review report",
            f"- Symptom: {finding.message}",
            f"- Impact: {finding.dimension.value} remains below publication readiness.",
            f"- Evidence: Review finding `{record_id}`.",
            "- Root cause: To be confirmed during follow-up work.",
            f"- Workaround: {finding.action}",
            f"- Next action: {finding.action}",
            f"- Linked tasks: {source_task_id or 'None'}",
            f"- Project: {project_id or 'None'}",
            "- Resolution: Pending",
            "- Verification: Pending",
        ]
    )


def _backlog_markdown(
    report: PaperReviewReport,
    records: tuple[ReviewBacklogRecord, ...],
) -> str:
    lines = [
        f"# Review Backlog: {report.title}",
        "",
        f"- Criteria: `{report.criteria.venue}`",
        f"- Overall score: `{report.overall_score}`",
        f"- Meets threshold: `{str(report.meets_acceptance_threshold).lower()}`",
        "",
        "## Records",
        "",
    ]
    if not records:
        lines.append("- No actionable review findings.")
        return "\n".join(lines).rstrip() + "\n"

    for record in records:
        lines.extend(
            [
                f"### {record.record_id}",
                "",
                f"- Type: `{record.record_type.value}`",
                f"- Priority: `{record.priority}`",
                f"- Severity: `{record.severity}`",
                f"- Dimension: `{record.dimension.value}`",
                f"- Action: {record.action}",
                f"- Description: {record.description}",
                "",
            ]
        )
        if record.problem_markdown:
            lines.extend(["#### Problem Entry", "", record.problem_markdown, ""])
    return "\n".join(lines).rstrip() + "\n"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "untitled"
