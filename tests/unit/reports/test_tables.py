import json
from pathlib import Path

import pytest

from autoresearch.reports import (
    MetricsTableInput,
    TableGenerationError,
    generate_ablation_table,
    generate_method_comparison_table,
)


def test_generate_method_comparison_table_matches_metric_sources(
    tmp_path: Path,
) -> None:
    baseline_source = _write_metrics(tmp_path / "baseline.json", accuracy=0.8, loss=0.4)
    method_source = _write_metrics(tmp_path / "method.json", accuracy=0.91, loss=0.12)

    artifact = generate_method_comparison_table(
        [
            MetricsTableInput(
                run_id="run_baseline",
                label="Baseline",
                metrics_source=baseline_source,
                evidence_ids={"accuracy": "evidence_baseline_accuracy"},
            ),
            MetricsTableInput(
                run_id="run_method",
                label="Proposed",
                metrics_source=method_source,
                evidence_ids={"accuracy": "evidence_method_accuracy"},
            ),
        ],
        tmp_path / "tables",
    )

    markdown = Path(artifact.markdown_path).read_text(encoding="utf-8")
    metadata = json.loads(Path(artifact.metadata_path).read_text(encoding="utf-8"))
    assert "| `run_baseline` | Baseline | 0.8 | 0.4 |" in markdown
    assert "| `run_method` | Proposed | 0.91 | 0.12 |" in markdown
    assert metadata["table"]["run_ids"] == ["run_baseline", "run_method"]
    assert metadata["table"]["metric_names"] == ["accuracy", "loss"]
    assert metadata["rows"][0]["source_path"] == baseline_source.resolve().as_posix()
    assert metadata["rows"][1]["metrics"] == {"accuracy": 0.91, "loss": 0.12}
    assert metadata["rows"][1]["evidence_ids"] == {
        "accuracy": "evidence_method_accuracy"
    }


def test_generate_ablation_table_records_table_type_and_sources(
    tmp_path: Path,
) -> None:
    full_source = _write_metrics(tmp_path / "full.json", accuracy=0.91)
    no_feature_source = _write_metrics(tmp_path / "no-feature.json", accuracy=0.86)

    artifact = generate_ablation_table(
        [
            MetricsTableInput("run_full", "Full model", full_source),
            MetricsTableInput("run_no_feature", "No feature", no_feature_source),
        ],
        tmp_path / "tables",
    )

    metadata = json.loads(Path(artifact.metadata_path).read_text(encoding="utf-8"))
    assert metadata["table"]["table_type"] == "ablation"
    assert metadata["table"]["source_paths"] == [
        full_source.resolve().as_posix(),
        no_feature_source.resolve().as_posix(),
    ]


def test_generate_method_comparison_table_rejects_empty_rows(tmp_path: Path) -> None:
    with pytest.raises(TableGenerationError, match="at least one"):
        generate_method_comparison_table([], tmp_path / "tables")


def _write_metrics(path: Path, **metrics: float) -> Path:
    path.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    return path
