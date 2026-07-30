import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research.evaluator_compatibility import (
    EXPECTED_CERTIFICATE_CHECKS,
    REQUIRED_FIXTURE_PROPERTIES,
    RESULT_FREE_SOURCE_RELATIVE_PATHS,
    V2_CONFIRMATION_RUNNER_SOURCE_PATH,
    EvaluatorCompatibilityArtifactManifest,
    EvaluatorCompatibilityFixture,
    EvaluatorCompatibilityProbe,
    EvaluatorCompatibilityReport,
    EvaluatorCompatibilityStatus,
    _scientific_projection_hash,
    compatibility_fixture_definitions,
    materialize_compatibility_fixture,
)
from autoresearch.research.portfolio import PortfolioIntegrityError

SHA = "a" * 64


def _fixture(index: int) -> EvaluatorCompatibilityFixture:
    return EvaluatorCompatibilityFixture.create(
        fixture_id=f"fixture-{index}",
        family=(
            "tabular_regression"
            if index == 3
            else "tabular_classification"
        ),
        source_encoding="sparse" if index == 1 else "dense",
        covered_properties=[f"property-{index}"],
        source_arff_sha256=f"{index + 1:x}" * 64,
        split_sha256=f"{index + 2:x}" * 64,
        train_sha256=f"{index + 3:x}" * 64,
        test_sha256=f"{index + 4:x}" * 64,
        labels_sha256=f"{index + 5:x}" * 64,
        input_manifest_sha256=f"{index + 6:x}" * 64,
        train_row_count=36,
        test_row_count=12,
        feature_columns=["x-0000", "x-0001"],
        label_token_contract=(
            "finite-float-label-v1"
            if index == 3
            else "canonical-string-label-v2"
        ),
    )


def _probe(index: int) -> EvaluatorCompatibilityProbe:
    expected_failure = index < 4
    return EvaluatorCompatibilityProbe.create(
        probe_id=f"probe-{index:03d}",
        interpreter_role="primary" if index % 2 == 0 else "replay",
        repeat_index=1 if index % 4 < 2 else 2,
        fixture_id=f"fixture-{index % 4}",
        candidate_id=(
            "invalid-schema-probe" if expected_failure else f"candidate-{index % 10}"
        ),
        learner="invalid_probe" if expected_failure else "linear",
        preprocessing="none" if expected_failure else "impute",
        stage="F3",
        expected_status="failed" if expected_failure else "succeeded",
        expected_failure_domain="candidate" if expected_failure else None,
        actual_status="failed" if expected_failure else "succeeded",
        failure_domain="candidate" if expected_failure else None,
        failure_code="intentional_invalid_probe" if expected_failure else None,
        return_code=0,
        labels_accessed=True,
        label_token_contract="canonical-string-label-v2",
        score=None if expected_failure else 0.5,
        prediction_count=0 if expected_failure else 12,
        prediction_sha256=None if expected_failure else SHA,
        memory_valid=None if expected_failure else True,
        result_relative_path=f"attempts/probe-{index:03d}/result.json",
        result_file_sha256=SHA,
        result_hash="b" * 64,
        scientific_projection_hash="c" * 64,
    )


def _report() -> EvaluatorCompatibilityReport:
    source_hashes = {
        "src/autoresearch/research/confirmatory_evaluation.py": SHA,
    }
    return EvaluatorCompatibilityReport.create(
        status=EvaluatorCompatibilityStatus.CERTIFIED,
        source_confirmation_freeze_hash=SHA,
        source_confirmation_orchestrator_sha256="b" * 64,
        source_accessed_relative_paths=list(RESULT_FREE_SOURCE_RELATIVE_PATHS),
        candidate_catalog_hash="c" * 64,
        candidate_ids=[f"candidate-{index}" for index in range(10)],
        allowed_learners=[
            "dummy",
            "extra_tree",
            "hist_gb",
            "invalid_probe",
            "lgbm",
            "lgbm_xgboost_ensemble",
            "linear",
            "rf",
            "xgboost",
        ],
        fixture_properties=sorted(REQUIRED_FIXTURE_PROPERTIES),
        fixtures=[_fixture(index) for index in range(4)],
        probes=[_probe(index) for index in range(152)],
        null_prior_integrity_failure_count=0,
        unexpected_candidate_failure_count=0,
        evaluator_failure_count=0,
        input_failure_count=0,
        checks={key: True for key in EXPECTED_CERTIFICATE_CHECKS},
        protected_v1_source_hashes_before=source_hashes,
        protected_v1_source_hashes_after=source_hashes,
        execution_asset_hashes={
            "candidate_runner_v1_sha256": SHA,
            "candidate_runner_v2_sha256": "b" * 64,
            "confirmation_runner_v2_sha256": "c" * 64,
        },
        clean_interpreter_hashes={"primary": SHA, "replay": SHA},
        clean_environment_snapshot_hashes={"primary": SHA, "replay": SHA},
        schema_bundle_sha256="d" * 64,
        orchestrator_source_sha256="e" * 64,
        created_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )


def test_fixture_corpus_covers_all_cross_serialization_properties() -> None:
    definitions = compatibility_fixture_definitions()

    properties = {
        prop for definition in definitions for prop in definition.covered_properties
    }
    assert len(definitions) == 4
    assert properties == REQUIRED_FIXTURE_PROPERTIES
    assert {definition.source_encoding for definition in definitions} == {
        "dense",
        "sparse",
    }
    assert {definition.family for definition in definitions} == {
        "tabular_classification",
        "tabular_regression",
    }
    assert any(b"'red,blue'" in definition.arff_bytes for definition in definitions)
    assert any(b"{0 " in definition.arff_bytes for definition in definitions)


def test_materialized_fixture_resume_reconstructs_and_verifies_features(
    tmp_path: Path,
) -> None:
    definition = compatibility_fixture_definitions()[2]
    first = materialize_compatibility_fixture(
        definition,
        tmp_path,
        confirmation_freeze_hash=SHA,
        reveal_hash="b" * 64,
    )
    second = materialize_compatibility_fixture(
        definition,
        tmp_path,
        confirmation_freeze_hash=SHA,
        reveal_hash="b" * 64,
    )

    assert first.feature_columns == second.feature_columns == (
        "x-0000",
        "x-0001",
        "x-0002",
    )
    assert first.fixture.fixture_hash == second.fixture.fixture_hash
    assert first.fixture.train_row_count == 36
    assert first.fixture.test_row_count == 12
    labels = json.loads(first.labels_path.read_text(encoding="utf-8"))
    assert all(isinstance(value, str) for value in labels["labels"])
    assert "green" in first.test_path.read_text(encoding="utf-8")


def test_materialized_fixture_resume_rejects_hash_tamper(tmp_path: Path) -> None:
    definition = compatibility_fixture_definitions()[0]
    bundle = materialize_compatibility_fixture(
        definition,
        tmp_path,
        confirmation_freeze_hash=SHA,
        reveal_hash="b" * 64,
    )
    bundle.train_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(PortfolioIntegrityError, match="file hash mismatch"):
        materialize_compatibility_fixture(
            definition,
            tmp_path,
            confirmation_freeze_hash=SHA,
            reveal_hash="b" * 64,
        )


def test_v2_runner_source_enforces_label_token_and_blind_stage_contracts() -> None:
    source = V2_CONFIRMATION_RUNNER_SOURCE_PATH.read_text(encoding="utf-8")

    assert 'dtype={"target": "string"}' in source
    assert "encoder.transform(raw_test_labels)" in source
    assert "inverse_transform" not in source
    assert "non_f3_labels_exposed" in source
    assert '"labels_accessed": labels_accessed' in source
    assert "candidate_fit_or_predict_failure" in source
    assert "objective_evaluation_failure" in source


def test_scientific_projection_ignores_runtime_but_binds_predictions() -> None:
    result: dict[str, object] = {
        field: None
        for field in (
            "schema_version",
            "runner_schema_version",
            "development_runner_v2_sha256",
            "status",
            "failure_domain",
            "failure_code",
            "failure_error_type",
            "opaque_unit_id",
            "candidate_id",
            "candidate_hash",
            "stage",
            "family",
            "metric_id",
            "score",
            "higher_is_better",
            "evaluation_split",
            "fit_row_count",
            "evaluation_row_count",
            "feature_count",
            "prediction_count",
            "prediction_sha256",
            "train_sha256",
            "test_sha256",
            "labels_sha256",
            "labels_accessed",
            "label_token_contract",
            "confirmation_freeze_hash",
            "reveal_hash",
            "seed",
            "training_fraction",
            "maximum_memory_mb",
            "memory_valid",
            "network_allowed",
        )
    }
    result.update(
        {
            "prediction_sha256": SHA,
            "score": 0.5,
            "execution_id": "first",
            "cpu_seconds": 1.0,
            "wall_seconds": 2.0,
            "peak_rss_mb": 3.0,
        }
    )
    changed_runtime = {
        **result,
        "execution_id": "second",
        "cpu_seconds": 10.0,
        "wall_seconds": 20.0,
        "peak_rss_mb": 30.0,
    }
    changed_prediction = {**result, "prediction_sha256": "b" * 64}

    assert _scientific_projection_hash(result) == _scientific_projection_hash(
        changed_runtime
    )
    assert _scientific_projection_hash(result) != _scientific_projection_hash(
        changed_prediction
    )


def test_report_is_fail_closed_on_check_or_hash_tamper() -> None:
    report = _report()
    assert report.status is EvaluatorCompatibilityStatus.CERTIFIED
    assert len(report.probes) == 152

    tampered_check = report.model_dump(mode="json")
    tampered_check["checks"]["network-disabled"] = False
    tampered_check["report_hash"] = report.report_hash
    with pytest.raises(ValidationError):
        EvaluatorCompatibilityReport.model_validate(tampered_check)

    tampered_source = report.model_dump(mode="json")
    tampered_source["protected_v1_source_hashes_after"][
        "src/autoresearch/research/confirmatory_evaluation.py"
    ] = "f" * 64
    with pytest.raises(ValidationError):
        EvaluatorCompatibilityReport.model_validate(tampered_source)


def test_manifest_binds_exact_sorted_recursive_inventory() -> None:
    manifest = EvaluatorCompatibilityArtifactManifest.create(
        status=EvaluatorCompatibilityStatus.CERTIFIED,
        report_hash=SHA,
        source_confirmation_freeze_hash="b" * 64,
        artifact_hashes={"z.json": "c" * 64, "a.json": "d" * 64},
    )

    assert list(manifest.artifact_hashes) == ["a.json", "z.json"]
    assert manifest.artifact_count == 2
    tampered = manifest.model_dump(mode="json")
    tampered["artifact_hashes"]["a.json"] = "e" * 64
    with pytest.raises(ValidationError):
        EvaluatorCompatibilityArtifactManifest.model_validate(tampered)


def test_result_free_source_inventory_excludes_consumed_outcomes() -> None:
    joined = "\n".join(RESULT_FREE_SOURCE_RELATIVE_PATHS)

    assert "confirmatory-evaluation-freeze.json" in joined
    assert "confirmatory-evaluation-report.json" not in joined
    assert "confirmatory-execution-index.json" not in joined
    assert "task-bundles" not in joined
    assert "primary-execution" not in joined
