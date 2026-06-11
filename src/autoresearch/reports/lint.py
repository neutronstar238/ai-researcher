"""Deterministic readability checks for generated Markdown reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_HEADING_ORDER = (
    "## Question",
    "## Literature Summary",
    "## Hypothesis",
    "## Experiment Design",
    "## Run Metadata",
    "## Results",
    "## Validation",
    "## Limitations",
    "## Next Steps",
)


@dataclass(frozen=True)
class ReportLintIssue:
    """One deterministic report readability issue."""

    check: str
    message: str
    line: int | None = None


class ReportLintError(RuntimeError):
    """Raised when a generated report fails readability checks."""


def lint_markdown_report(
    markdown: str,
    *,
    base_dir: Path | str | None = None,
) -> list[ReportLintIssue]:
    """Return deterministic readability issues for a generated report."""

    lines = markdown.splitlines()
    issues: list[ReportLintIssue] = []
    issues.extend(_check_heading_order(lines))
    issues.extend(_check_tables(lines))
    issues.extend(_check_links(markdown, Path(base_dir) if base_dir is not None else None))
    issues.extend(_check_evidence_references(lines))
    return issues


def assert_report_readable(
    markdown: str,
    *,
    base_dir: Path | str | None = None,
) -> None:
    """Raise if a generated report fails readability checks."""

    issues = lint_markdown_report(markdown, base_dir=base_dir)
    if issues:
        details = "; ".join(f"{issue.check}: {issue.message}" for issue in issues)
        raise ReportLintError(details)


def _check_heading_order(lines: list[str]) -> list[ReportLintIssue]:
    issues: list[ReportLintIssue] = []
    positions: dict[str, int] = {}
    for index, line in enumerate(lines, start=1):
        if line in REQUIRED_HEADING_ORDER:
            positions[line] = index

    previous_position = 0
    for heading in REQUIRED_HEADING_ORDER:
        position = positions.get(heading)
        if position is None:
            issues.append(ReportLintIssue("heading_order", f"missing heading {heading}"))
            continue
        if position < previous_position:
            issues.append(
                ReportLintIssue(
                    "heading_order",
                    f"heading {heading} is out of order",
                    line=position,
                )
            )
        previous_position = position
    return issues


def _check_tables(lines: list[str]) -> list[ReportLintIssue]:
    issues: list[ReportLintIssue] = []
    table_indices = [
        (index, line)
        for index, line in enumerate(lines, start=1)
        if line.strip().startswith("|")
    ]
    if not table_indices:
        return issues

    index = 0
    while index < len(table_indices):
        block: list[tuple[int, str]] = [table_indices[index]]
        index += 1
        while (
            index < len(table_indices)
            and table_indices[index][0] == block[-1][0] + 1
        ):
            block.append(table_indices[index])
            index += 1
        issues.extend(_check_table_block(block))
    return issues


def _check_table_block(block: list[tuple[int, str]]) -> list[ReportLintIssue]:
    issues: list[ReportLintIssue] = []
    if len(block) < 2 or not _is_separator_row(block[1][1]):
        return [
            ReportLintIssue(
                "table_format",
                "table must include a Markdown separator row after the header",
                line=block[0][0],
            )
        ]
    expected_columns = _column_count(block[0][1])
    for line_number, row in block:
        if _column_count(row) != expected_columns:
            issues.append(
                ReportLintIssue(
                    "table_format",
                    "table rows must have consistent column counts",
                    line=line_number,
                )
            )
    return issues


def _check_links(markdown: str, base_dir: Path | None) -> list[ReportLintIssue]:
    if base_dir is None:
        return []
    issues: list[ReportLintIssue] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        target = match.group(1)
        if _is_external_or_anchor_link(target):
            continue
        path_text = target.split("#", maxsplit=1)[0]
        if not path_text:
            continue
        path = Path(path_text)
        resolved = path if path.is_absolute() else base_dir / path
        if not resolved.exists():
            issues.append(
                ReportLintIssue(
                    "link_exists",
                    f"linked artifact does not exist: {target}",
                )
            )
    return issues


def _check_evidence_references(lines: list[str]) -> list[ReportLintIssue]:
    issues: list[ReportLintIssue] = []
    metric_line_pattern = re.compile(r"^- `[^`]+` = `[-+]?\d+(\.\d+)?`")
    for index, line in enumerate(lines, start=1):
        if metric_line_pattern.search(line) and "[evidence `" not in line:
            issues.append(
                ReportLintIssue(
                    "evidence_reference",
                    "quantitative metric line is missing an evidence link",
                    line=index,
                )
            )
    return issues


def _is_separator_row(row: str) -> bool:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _column_count(row: str) -> int:
    return len(row.strip().strip("|").split("|"))


def _is_external_or_anchor_link(target: str) -> bool:
    parsed = urlparse(target)
    return bool(parsed.scheme) or target.startswith("#")
