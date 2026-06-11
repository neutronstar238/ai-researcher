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


def test_generate_metric_bar_figure_rejects_source_without_numeric_metrics(
    tmp_path: Path,
) -> None:
    metrics_source = tmp_path / "metrics.json"
    metrics_source.write_text(json.dumps({"metrics": {"passed": True}}), encoding="utf-8")

    with pytest.raises(FigureGenerationError, match="numeric metrics"):
        generate_metric_bar_figure(metrics_source, tmp_path / "figures")
