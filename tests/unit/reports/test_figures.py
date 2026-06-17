import json
from pathlib import Path

import pytest

from autoresearch.reports import FigureGenerationError, generate_metric_bar_figure


def test_generate_metric_bar_figure_writes_artifacts_and_records_source(
    tmp_path: Path,
) -> None:
    metrics_source = tmp_path / "metrics.json"
    metrics_source.write_text(
        json.dumps({"metrics": {"accuracy": 0.91, "loss": 0.12}}),
        encoding="utf-8",
    )

    artifact = generate_metric_bar_figure(
        metrics_source,
        tmp_path / "figures",
        title="Demo Metrics",
        figure_id="demo-metrics",
    )

    pdf_path = Path(artifact.pdf_path)
    png_path = Path(artifact.png_path)
    metadata_path = Path(artifact.metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert metadata["source_path"] == metrics_source.resolve().as_posix()
    assert metadata["figure"]["source_path"] == metrics_source.resolve().as_posix()
    assert metadata["figure"]["pdf_path"] == pdf_path.as_posix()
    assert metadata["figure"]["png_path"] == png_path.as_posix()
    assert metadata["figure"]["metric_names"] == ["accuracy", "loss"]
    assert metadata["style"]["name"] == "autoresearch-default"
    assert metadata["style"]["orientation"] == "horizontal"


def test_generate_metric_bar_figure_uses_readable_labels_for_long_metric_keys(
    tmp_path: Path,
) -> None:
    metrics_source = tmp_path / "metrics.json"
    metrics_source.write_text(
        json.dumps(
            {
                "metrics": {
                    "accuracy_delta_vs_baseline": 0.0457,
                    "zscore_centroid_accuracy": 0.785,
                    "baseline_accuracy": 0.7776,
                    "accuracy": 0.8233,
                }
            }
        ),
        encoding="utf-8",
    )

    artifact = generate_metric_bar_figure(
        metrics_source,
        tmp_path / "figures",
        title="Readable Metrics",
        figure_id="readable-metrics",
    )

    pdf_bytes = Path(artifact.pdf_path).read_bytes()
    metadata = json.loads(Path(artifact.metadata_path).read_text(encoding="utf-8"))
    labels = [metric["label"] for metric in metadata["metrics"]]
    assert labels == [
        "Accuracy",
        "Baseline accuracy",
        "Z-score centroid accuracy",
        "Delta vs baseline",
    ]
    assert b"Delta vs baseline" in pdf_bytes
    assert b"Z-score centroid accuracy" in pdf_bytes
    assert b"accuracy_delta_vs" not in pdf_bytes


def test_generate_metric_bar_figure_rejects_source_without_numeric_metrics(
    tmp_path: Path,
) -> None:
    metrics_source = tmp_path / "metrics.json"
    metrics_source.write_text(json.dumps({"metrics": {"passed": True}}), encoding="utf-8")

    with pytest.raises(FigureGenerationError, match="numeric metrics"):
        generate_metric_bar_figure(metrics_source, tmp_path / "figures")
