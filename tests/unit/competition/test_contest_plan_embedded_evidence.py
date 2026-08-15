from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.contest_plan_embedded_evidence import (
    ContestPlanEmbeddedEvidenceError,
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.manifest import canonical_model_hash


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pilot_fixture(root: Path) -> Path:
    metrics = {
        "scientific_boundary_zh": "固定区间仅作描述性预实验，不是总体随机样本。",
        "aggregate_results": [
            {
                "null_model": "global_permutation",
                "interval_count": 2,
                "draw_count": 199,
                "observed_mean_entropy": 0.91,
                "null_mean_entropy": 0.95,
                "delta_observed_minus_null": -0.04,
                "one_sided_empirical_p_lower": 0.005,
                "holm_adjusted_p_across_null_models": 0.01,
                "fixed_interval_resampling_delta_ci95": [-0.05, -0.03],
            },
            {
                "null_model": "residue_path_conditioned_permutation",
                "interval_count": 2,
                "draw_count": 199,
                "observed_mean_entropy": 0.91,
                "null_mean_entropy": 0.912,
                "delta_observed_minus_null": -0.002,
                "one_sided_empirical_p_lower": 0.02,
                "holm_adjusted_p_across_null_models": 0.04,
                "fixed_interval_resampling_delta_ci95": [-0.003, -0.001],
            },
        ],
        "interval_results": [
            {
                "interval_index": 1,
                "start": 100,
                "stop": 200,
                "prime_count": 25,
                "gap_count": 24,
                "mean_gap": 4.1,
                "observed_metrics": {
                    "tie_aware_normalized_permutation_entropy_m5": 0.92
                },
            },
            {
                "interval_index": 2,
                "start": 500,
                "stop": 600,
                "prime_count": 17,
                "gap_count": 16,
                "mean_gap": 5.8,
                "observed_metrics": {
                    "tie_aware_normalized_permutation_entropy_m5": 0.90
                },
            },
        ],
    }
    metrics_path = root / "metrics.json"
    _write_json(metrics_path, metrics)
    raw_path = root / "raw" / "observations.csv"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("x,value\n1,0.92\n2,0.90\n", encoding="utf-8")
    manifest = {
        "files": [
            {
                "relative_path": "metrics.json",
                "sha256": _sha256(metrics_path),
                "bytes": metrics_path.stat().st_size,
                "kind": "metrics",
            },
            {
                "relative_path": "raw/observations.csv",
                "sha256": _sha256(raw_path),
                "bytes": raw_path.stat().st_size,
                "kind": "raw_observations",
            },
        ]
    }
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, manifest)
    artifact: dict[str, Any] = {
        "schema_version": "generic-pilot-v1",
        "status": "completed",
        "study_phase": "exploratory_pilot",
        "metrics_relative_path": "metrics.json",
        "metrics_sha256": _sha256(metrics_path),
        "manifest_relative_path": "manifest.json",
        "manifest_sha256": _sha256(manifest_path),
    }
    artifact["artifact_hash"] = canonical_model_hash(artifact)
    artifact_path = root / "preexperiment.json"
    _write_json(artifact_path, artifact)
    return artifact_path


def test_verified_pilot_is_projected_to_self_contained_tables_and_figure(
    tmp_path: Path,
) -> None:
    artifact_path = _pilot_fixture(tmp_path / "pilot")

    bundle = build_contest_plan_embedded_evidence(artifact_path)

    assert bundle is not None
    assert len(bundle.payload["tables"]) == 2
    assert len(bundle.payload["figures"]) == 1
    assert bundle.payload["tables"][0]["rows"][0]["delta_observed_minus_null"] == -0.04
    aggregate_labels = {
        item["key"]: item["label_zh"]
        for item in bundle.payload["tables"][0]["columns"]
    }
    assert all(key not in label for key, label in aggregate_labels.items())
    assert "绝对差值最大" in bundle.payload["analysis_zh"]
    assert "不是总体随机样本" in bundle.payload["scope_note_zh"]
    public_text = json.dumps(bundle.payload, ensure_ascii=False)
    assert ".json" not in public_text
    assert ".csv" not in public_text
    assert not any(binding["path"] in public_text for binding in bundle.manifest_bindings)
    roles = {binding["role"] for binding in bundle.manifest_bindings}
    assert {
        "preexperiment_artifact",
        "preexperiment_manifest",
        "preexperiment_metrics",
        "preexperiment_raw_observations",
    } <= roles


def test_declared_metric_tampering_fails_instead_of_rendering(tmp_path: Path) -> None:
    artifact_path = _pilot_fixture(tmp_path / "pilot")
    (artifact_path.parent / "metrics.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ContestPlanEmbeddedEvidenceError, match="SHA-256 mismatch"):
        build_contest_plan_embedded_evidence(artifact_path)


def test_completed_metadata_without_numeric_evidence_produces_no_fake_table() -> None:
    assert (
        build_contest_plan_embedded_evidence(
            {"status": "completed", "study_phase": "exploratory_pilot"}
        )
        is None
    )


def test_generic_adapter_never_exposes_unknown_machine_field_in_chinese_header() -> None:
    bundle = build_contest_plan_embedded_evidence(
        {
            "status": "completed",
            "study_phase": "preexperiment",
            "metrics": {
                "future_adapter_rows": [
                    {"interval_count": 3, "vendor_specific_metric_xyz": 0.72}
                ]
            },
        }
    )

    assert bundle is not None
    labels = {
        item["key"]: item["label_zh"]
        for item in bundle.payload["tables"][0]["columns"]
    }
    assert labels["interval_count"] == "固定分析单元数"
    assert labels["vendor_specific_metric_xyz"] == "预实验数值指标"
