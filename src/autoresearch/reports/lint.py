"""Deterministic readability checks for generated Markdown reports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_HEADING_ORDER = (
    "## Abstract",
    "## Introduction",
    "## Related Work",
    "## Question",
    "## Literature Summary",
    "## Hypothesis",
    "## Method",
    "## Experiment Design",
    "## Experiments",
    "## Run Metadata",
    "## Reproducibility",
    "## Results",
    "## Validation",
    "## Limitations",
    "## Conclusion",
    "## References",
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


@dataclass(frozen=True)
class _MetricObservation:
    metric_name: str
    value: float
    source_path: str
    line: int


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
    issues.extend(
        lint_metric_consistency(markdown, base_dir=base_dir)
        if base_dir is not None
        else []
    )
    return issues


def lint_metric_consistency(
    markdown: str,
    *,
    base_dir: Path | str,
) -> list[ReportLintIssue]:
    """Check metric values in report text, tables, and figures against sources."""

    return _check_metric_consistency(markdown.splitlines(), Path(base_dir))


def assert_metric_consistency(
    markdown: str,
    *,
    base_dir: Path | str,
) -> None:
    """Raise if report text, table, or figure metric values disagree with sources."""

    issues = lint_metric_consistency(markdown, base_dir=base_dir)
    if issues:
        details = "; ".join(f"{issue.check}: {issue.message}" for issue in issues)
        raise ReportLintError(details)


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


def _check_metric_consistency(
    lines: list[str],
    base_dir: Path | None,
) -> list[ReportLintIssue]:
    if base_dir is None:
        return []

    issues: list[ReportLintIssue] = []
    metric_cache: dict[str, dict[str, float] | None] = {}
    observations = [
        *_metric_observations_from_text(lines),
        *_metric_observations_from_tables(lines),
        *_metric_observations_from_figures(lines),
    ]
    for observation in observations:
        source_metrics = _metrics_for_source(observation.source_path, base_dir, metric_cache)
        if source_metrics is None:
            issues.append(
                ReportLintIssue(
                    "metric_consistency",
                    f"metric source is missing or invalid: {observation.source_path}",
                    line=observation.line,
                )
            )
            continue
        expected_value = source_metrics.get(observation.metric_name)
        if expected_value is None:
            issues.append(
                ReportLintIssue(
                    "metric_consistency",
                    f"metric {observation.metric_name!r} is missing from source "
                    f"{observation.source_path}",
                    line=observation.line,
                )
            )
            continue
        if abs(expected_value - observation.value) > 1e-9:
            issues.append(
                ReportLintIssue(
                    "metric_consistency",
                    f"metric {observation.metric_name!r} value {observation.value} "
                    f"does not match source value {expected_value}",
                    line=observation.line,
                )
            )
    return issues


def _metric_observations_from_text(lines: list[str]) -> list[_MetricObservation]:
    pattern = re.compile(
        r"`(?P<metric>[^`]+)`\s*=\s*`(?P<value>[-+]?\d+(?:\.\d+)?)`"
        r".*?\[evidence `[^`]+`\]\((?P<path>[^)]+)\)"
    )
    observations: list[_MetricObservation] = []
    for index, line in enumerate(lines, start=1):
        match = pattern.search(line)
        if match:
            observations.append(
                _MetricObservation(
                    metric_name=match.group("metric"),
                    value=float(match.group("value")),
                    source_path=match.group("path"),
                    line=index,
                )
            )
    return observations


def _metric_observations_from_figures(lines: list[str]) -> list[_MetricObservation]:
    pattern = re.compile(
        r"!\[[^\]]*?(?P<metric>[A-Za-z][\w.-]*)\s*=\s*"
        r"(?P<value>[-+]?\d+(?:\.\d+)?)[^\]]*\]\([^)]+\)"
        r".*?\[evidence `[^`]+`\]\((?P<path>[^)]+)\)"
    )
    observations: list[_MetricObservation] = []
    for index, line in enumerate(lines, start=1):
        match = pattern.search(line)
        if match:
            observations.append(
                _MetricObservation(
                    metric_name=match.group("metric"),
                    value=float(match.group("value")),
                    source_path=match.group("path"),
                    line=index,
                )
            )
    return observations


def _metric_observations_from_tables(lines: list[str]) -> list[_MetricObservation]:
    observations: list[_MetricObservation] = []
    for block in _table_blocks(lines):
        if len(block) < 3 or not _is_separator_row(block[1][1]):
            continue
        headers = [_normalize_table_cell(cell).lower() for cell in _table_cells(block[0][1])]
        metric_index = _column_index(headers, "metric")
        value_index = _column_index(headers, "value")
        evidence_index = _column_index(headers, "evidence")
        if metric_index is None or value_index is None or evidence_index is None:
            continue
        for line_number, row in block[2:]:
            cells = _table_cells(row)
            if len(cells) != len(headers):
                continue
            metric_name = _normalize_table_cell(cells[metric_index])
            value = _numeric_value(cells[value_index])
            source_path = _evidence_source_path(cells[evidence_index])
            if metric_name and value is not None and source_path is not None:
                observations.append(
                    _MetricObservation(
                        metric_name=metric_name,
                        value=value,
                        source_path=source_path,
                        line=line_number,
                    )
                )
    return observations


def _table_blocks(lines: list[str]) -> list[list[tuple[int, str]]]:
    table_indices = [
        (index, line)
        for index, line in enumerate(lines, start=1)
        if line.strip().startswith("|")
    ]
    blocks: list[list[tuple[int, str]]] = []
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
        blocks.append(block)
    return blocks


def _metrics_for_source(
    source_path: str,
    base_dir: Path,
    cache: dict[str, dict[str, float] | None],
) -> dict[str, float] | None:
    if source_path not in cache:
        cache[source_path] = _load_metric_source(source_path, base_dir)
    return cache[source_path]


def _load_metric_source(source_path: str, base_dir: Path) -> dict[str, float] | None:
    if _is_external_or_anchor_link(source_path):
        return None
    path_text = source_path.split("#", maxsplit=1)[0]
    if not path_text:
        return None
    path = Path(path_text)
    resolved = path if path.is_absolute() else base_dir / path
    if not resolved.exists():
        return None
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    metric_payload = payload.get("metrics", payload) if isinstance(payload, dict) else {}
    if not isinstance(metric_payload, dict):
        return None
    metrics: dict[str, float] = {}
    for name, value in metric_payload.items():
        if isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool):
            metrics[name] = float(value)
    return metrics


def _column_index(headers: list[str], required_text: str) -> int | None:
    for index, header in enumerate(headers):
        if required_text in header:
            return index
    return None


def _table_cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _normalize_table_cell(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _numeric_value(cell: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cell)
    return float(match.group(0)) if match else None


def _evidence_source_path(cell: str) -> str | None:
    match = re.search(r"\[evidence `[^`]+`\]\(([^)]+)\)", cell)
    return match.group(1) if match else None


def _is_separator_row(row: str) -> bool:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _column_count(row: str) -> int:
    return len(row.strip().strip("|").split("|"))


def _is_external_or_anchor_link(target: str) -> bool:
    parsed = urlparse(target)
    return bool(parsed.scheme) or target.startswith("#")
