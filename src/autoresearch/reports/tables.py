"""Generate source-backed scientific tables."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TableType = Literal["method_comparison", "ablation"]


class TableGenerationError(RuntimeError):
    """Raised when a table cannot be generated from source metrics."""


@dataclass(frozen=True)
class MetricsTableInput:
    """One source-backed row in a generated metrics table."""

    run_id: str
    label: str
    metrics_source: Path | str
    evidence_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricsTableArtifact:
    """Paths and provenance for a generated metrics table."""

    title: str
    table_type: TableType
    markdown_path: str
    metadata_path: str
    run_ids: tuple[str, ...]
    metric_names: tuple[str, ...]
    source_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "table_type": self.table_type,
            "markdown_path": self.markdown_path,
            "metadata_path": self.metadata_path,
            "run_ids": list(self.run_ids),
            "metric_names": list(self.metric_names),
            "source_paths": list(self.source_paths),
        }


def generate_method_comparison_table(
    rows: list[MetricsTableInput],
    output_dir: Path | str,
    *,
    title: str = "Method Comparison",
    table_id: str = "method-comparison",
) -> MetricsTableArtifact:
    """Generate a method comparison table from metrics source files."""

    return _generate_metrics_table(
        rows,
        output_dir,
        title=title,
        table_id=table_id,
        table_type="method_comparison",
    )


def generate_ablation_table(
    rows: list[MetricsTableInput],
    output_dir: Path | str,
    *,
    title: str = "Ablation Study",
    table_id: str = "ablation-study",
) -> MetricsTableArtifact:
    """Generate an ablation table from metrics source files."""

    return _generate_metrics_table(
        rows,
        output_dir,
        title=title,
        table_id=table_id,
        table_type="ablation",
    )


def _generate_metrics_table(
    rows: list[MetricsTableInput],
    output_dir: Path | str,
    *,
    title: str,
    table_id: str,
    table_type: TableType,
) -> MetricsTableArtifact:
    if not rows:
        msg = "at least one metrics row is required"
        raise TableGenerationError(msg)

    row_records = [_read_row(row) for row in rows]
    metric_names = tuple(sorted({metric for row in row_records for metric in row["metrics"]}))
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    slug = _slugify(table_id)
    markdown_path = output_path / f"{slug}.md"
    metadata_path = output_path / f"{slug}.metadata.json"

    markdown = _render_markdown_table(title, row_records, metric_names)
    markdown_path.write_text(markdown, encoding="utf-8")

    artifact = MetricsTableArtifact(
        title=title,
        table_type=table_type,
        markdown_path=markdown_path.as_posix(),
        metadata_path=metadata_path.as_posix(),
        run_ids=tuple(str(row["run_id"]) for row in row_records),
        metric_names=metric_names,
        source_paths=tuple(str(row["source_path"]) for row in row_records),
    )
    metadata = {
        "table": artifact.to_dict(),
        "rows": row_records,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def _read_row(row: MetricsTableInput) -> dict[str, Any]:
    if not row.run_id:
        msg = "table row run_id is required"
        raise TableGenerationError(msg)
    if not row.label:
        msg = f"table row label is required for run {row.run_id}"
        raise TableGenerationError(msg)
    source_path = Path(row.metrics_source).resolve()
    metrics = _load_metrics(source_path)
    return {
        "run_id": row.run_id,
        "label": row.label,
        "source_path": source_path.as_posix(),
        "metrics": metrics,
        "evidence_ids": dict(row.evidence_ids),
    }


def _load_metrics(source_path: Path) -> dict[str, float]:
    if not source_path.exists():
        msg = f"metrics source file is missing: {source_path.as_posix()}"
        raise TableGenerationError(msg)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"metrics source file is not valid JSON: {source_path.as_posix()}"
        raise TableGenerationError(msg) from exc

    metric_payload = payload.get("metrics", payload) if isinstance(payload, dict) else {}
    if not isinstance(metric_payload, dict):
        msg = "metrics source must contain a JSON object"
        raise TableGenerationError(msg)

    metrics: dict[str, float] = {}
    for name, value in metric_payload.items():
        if isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool):
            metrics[name] = float(value)
    if not metrics:
        msg = "metrics source does not contain numeric metrics"
        raise TableGenerationError(msg)
    return metrics


def _render_markdown_table(
    title: str,
    rows: list[dict[str, Any]],
    metric_names: tuple[str, ...],
) -> str:
    headers = ["Run ID", "Label", *metric_names]
    aligns = ["---", "---", *(["---:"] * len(metric_names))]
    lines = [
        f"## {title}",
        "",
        _markdown_row(headers),
        _markdown_row(aligns),
    ]
    for row in rows:
        metrics = row["metrics"]
        values = [
            f"`{row['run_id']}`",
            str(row["label"]),
            *[
                _format_metric(metrics[metric_name])
                if metric_name in metrics
                else ""
                for metric_name in metric_names
            ],
        ]
        lines.append(_markdown_row(values))
    lines.append("")
    return "\n".join(lines)


def _markdown_row(values: list[str]) -> str:
    escaped = [_escape_markdown_cell(value) for value in values]
    return "| " + " | ".join(escaped) + " |"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _format_metric(value: float) -> str:
    return f"{value:.6g}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "metrics-table"
