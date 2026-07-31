import importlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from autoresearch.research.confirmatory_evaluation import (
    ConfirmatoryLabels,
    audit_independent_execution_source,
)
from autoresearch.research.technical_confirmation_replay import (
    EXPECTED_ALLOWED_REPAIRS,
    EXPECTED_STOP_RULE_CHECKS,
    V2_POLICY_CONTROLLER_SOURCE_PATH,
    ConsumedPanelRepairFreeze,
    V1MeasurementFailureSignature,
    technical_replay_json_schemas,
)

SHA = "a" * 64


def _repair_freeze() -> ConsumedPanelRepairFreeze:
    signature = V1MeasurementFailureSignature.create(
        failure_rows_hash="b" * 64,
    )
    return ConsumedPanelRepairFreeze.create(
        source_confirmation_freeze_hash=SHA,
        source_reveal_hash="b" * 64,
        source_report_hash="c" * 64,
        source_manifest_hash="d" * 64,
        source_controller_result_hash="e" * 64,
        source_scientific_projection_hash="f" * 64,
        source_failure_signature=signature,
        evaluator_certificate_report_hash="1" * 64,
        evaluator_certificate_manifest_hash="2" * 64,
        v1_policy_controller_sha256="3" * 64,
        v2_policy_controller_sha256="4" * 64,
        v1_candidate_runner_sha256="5" * 64,
        v2_candidate_runner_sha256="6" * 64,
        v2_confirmation_runner_sha256="7" * 64,
        orchestrator_source_sha256="8" * 64,
        technical_execution_index_hashes={
            "primary": "9" * 64,
            "replay": "0" * 64,
        },
        frozen_candidate_catalog_hash="a" * 64,
        frozen_policy_catalog_hash="b" * 64,
        frozen_assignment_catalog_hash="c" * 64,
        frozen_claim_hash="d" * 64,
        allowed_repair_fields=EXPECTED_ALLOWED_REPAIRS,
        stop_rule_check_ids=sorted(EXPECTED_STOP_RULE_CHECKS),
        frozen_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )


def _load_controller_module() -> ModuleType:
    asset_dir = V2_POLICY_CONTROLLER_SOURCE_PATH.parent.resolve()
    sys.path.insert(0, str(asset_dir))
    try:
        return importlib.import_module(
            "frozen_confirmation_policy_controller_v2"
        )
    finally:
        sys.path.remove(str(asset_dir))


def test_repair_freeze_is_result_free_consumed_and_publication_ineligible() -> None:
    repair = _repair_freeze()

    assert repair.result_record_count_at_freeze == 0
    assert repair.source_panel_consumed is True
    assert repair.technical_only is True
    assert repair.exploratory_only is True
    assert repair.independent_confirmation_eligible is False
    assert repair.publication_evidence_eligible is False
    assert repair.minimum_observed_risk_difference_to_review == 0.10
    assert repair.minimum_confirmatory_claim_risk_difference_unchanged == 0.25
    assert repair.numerical_advance_authorizes_new_confirmation is False
    assert repair.new_mechanism_rationale_required is True
    assert repair.new_development_evidence_required is True
    assert set(repair.stop_rule_check_ids) == EXPECTED_STOP_RULE_CHECKS


def test_repair_freeze_rejects_hash_and_scope_tamper() -> None:
    payload = _repair_freeze().model_dump(mode="json")
    payload["minimum_observed_risk_difference_to_review"] = 0.0

    with pytest.raises(ValidationError):
        ConsumedPanelRepairFreeze.model_validate(payload)

    payload = _repair_freeze().model_dump(mode="json")
    payload["allowed_repair_fields"].append("candidate-retuning")
    with pytest.raises(ValidationError):
        ConsumedPanelRepairFreeze.model_validate(payload)

    payload = _repair_freeze().model_dump(mode="json")
    payload["source_report_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="repair_freeze_hash"):
        ConsumedPanelRepairFreeze.model_validate(payload)


def test_technical_schema_bundle_hard_codes_nonpublication_boundaries() -> None:
    schemas = technical_replay_json_schemas()
    freeze_schema = schemas["ConsumedPanelRepairFreeze"]
    report_schema = schemas["ConsumedPanelTechnicalReport"]

    assert freeze_schema["properties"]["technical_only"]["const"] is True
    assert (
        freeze_schema["properties"]["independent_confirmation_eligible"][
            "const"
        ]
        is False
    )
    assert (
        report_schema["properties"]["publication_evidence_eligible"]["const"]
        is False
    )
    assert report_schema["properties"]["new_confirmation_authorized"]["const"] is False


def test_v2_controller_source_preserves_claim_and_isolates_labels() -> None:
    source = V2_POLICY_CONTROLLER_SOURCE_PATH.read_text(encoding="utf-8")

    assert "source_confirmation_freeze_hash" in source
    assert "repair_freeze_hash" in source
    assert 'if stage == "F3":' in source
    assert 'config["labels_path"] = task["labels_path"]' in source
    assert "consumed_confirmatory_technical" in source
    assert '"independent_confirmation_eligible": False' in source
    assert "post_reveal_retuning_authorized" in source
    assert "result_contingent_route_change_authorized" in source
    assert audit_independent_execution_source(V2_POLICY_CONTROLLER_SOURCE_PATH)


def test_v2_controller_preserves_partial_input_failure_domain() -> None:
    controller = _load_controller_module()
    payload = {
        "status": "failed",
        "failure_domain": "input",
        "execution_id": "technical-evaluation",
        "opaque_unit_id": "opaque-unit",
        "candidate_id": "candidate",
        "candidate_hash": "7" * 64,
        "stage": "F2",
        "family": "tabular_classification",
        "train_sha256": None,
        "test_sha256": None,
        "labels_sha256": None,
        "labels_accessed": False,
        "confirmation_freeze_hash": "1" * 64,
        "reveal_hash": "2" * 64,
        "network_allowed": False,
    }

    assert controller._payload_bindings_valid(
        payload,
        design={"freeze_hash": "1" * 64},
        index={"reveal_hash": "2" * 64},
        task={
            "opaque_unit_id": "opaque-unit",
            "family": "tabular_classification",
            "train_sha256": "3" * 64,
            "test_sha256": "4" * 64,
            "labels_sha256": "5" * 64,
        },
        candidate={
            "candidate_id": "candidate",
            "candidate_hash": "7" * 64,
        },
        evaluation_id="technical-evaluation",
        stage="F2",
    )


def test_v2_controller_integrates_label_isolation_and_f3_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _load_controller_module()
    asset_dir = V2_POLICY_CONTROLLER_SOURCE_PATH.parent.resolve()
    execution_assets = tmp_path / "execution-assets"
    execution_assets.mkdir()
    for name in (
        "frozen_tabular_confirmation_runner_v2.py",
        "frozen_tabular_candidate_runner_v2.py",
        "frozen_tabular_candidate_runner_v1.py",
    ):
        shutil.copy2(asset_dir / name, execution_assets / name)
    runner = execution_assets / "frozen_tabular_confirmation_runner_v2.py"

    train_path = tmp_path / "train.csv"
    test_path = tmp_path / "test.csv"
    labels_path = tmp_path / "labels.json"
    train_rows = ["feature,target"]
    for index in range(40):
        train_rows.append(f"{index / 10:.1f},{index % 2}")
    train_path.write_text("\n".join(train_rows) + "\n", encoding="utf-8")
    test_rows = ["row_id,feature"]
    for index in range(8):
        test_rows.append(f"{index},{index / 10 + 0.05:.2f}")
    test_path.write_text("\n".join(test_rows) + "\n", encoding="utf-8")

    freeze_hash = "1" * 64
    reveal_hash = "2" * 64
    labels = ConfirmatoryLabels.create(
        unit_id="technical-fixture",
        opaque_unit_id="opaque-technical-fixture",
        family="tabular_classification",
        confirmation_freeze_hash=freeze_hash,
        reveal_hash=reveal_hash,
        row_ids=list(range(8)),
        labels=[str(index % 2) for index in range(8)],
        data_sha256="3" * 64,
        split_sha256="4" * 64,
        source_data_md5="5" * 32,
    )
    labels_path.write_text(labels.canonical_json() + "\n", encoding="utf-8")

    def file_hash(path: Path) -> str:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()

    repair_hash = "6" * 64
    controller._ACTIVE_REPAIR_FREEZE = {
        "repair_freeze_hash": repair_hash,
        "v2_candidate_runner_sha256": file_hash(
            execution_assets / "frozen_tabular_candidate_runner_v2.py"
        ),
        "v2_confirmation_runner_sha256": file_hash(runner),
    }
    design = {
        "freeze_hash": freeze_hash,
        "fidelity_budget": {
            "F1": {"training_fraction": 0.50, "maximum_seconds": 60},
            "F2": {"training_fraction": 0.75, "maximum_seconds": 60},
            "F3": {"training_fraction": 1.00, "maximum_seconds": 60},
        },
        "maximum_memory_mb": 4096,
    }
    index = {"reveal_hash": reveal_hash}
    task = {
        "unit_id": "technical-fixture",
        "opaque_unit_id": "opaque-technical-fixture",
        "family": "tabular_classification",
        "train_path": train_path.resolve().as_posix(),
        "test_path": test_path.resolve().as_posix(),
        "labels_path": labels_path.resolve().as_posix(),
        "train_sha256": file_hash(train_path),
        "test_sha256": file_hash(test_path),
        "labels_sha256": file_hash(labels_path),
        "metric_id": "balanced_accuracy",
    }
    candidate = {
        "candidate_id": "null-prior",
        "candidate_hash": "7" * 64,
        "mechanism_family": "null_prior",
        "learner": "dummy",
        "preprocessing": "none",
        "hyperparameters": {},
    }
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("technical-test-interpreter\n", encoding="utf-8")

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        config = json.loads(Path(command[3]).read_text(encoding="utf-8"))
        output_path = Path(command[5])
        payload: dict[str, object] = {
            "schema_version": "tabular-confirmation-candidate-result-v2",
            "runner_schema_version": "frozen-tabular-confirmation-runner-v2",
            "development_runner_v2_sha256": controller._file_sha256(
                execution_assets / "frozen_tabular_candidate_runner_v2.py"
            ),
            "status": "succeeded",
            "failure_domain": None,
            "failure_code": None,
            "failure_error_type": None,
            "execution_id": config["execution_id"],
            "opaque_unit_id": config["opaque_unit_id"],
            "candidate_id": config["candidate_id"],
            "candidate_hash": config["candidate_hash"],
            "stage": config["stage"],
            "family": config["family"],
            "metric_id": "balanced_accuracy",
            "score": 0.5,
            "higher_is_better": True,
            "evaluation_split": (
                "confirmatory_test"
                if config["stage"] == "F3"
                else "internal_validation"
            ),
            "fit_row_count": 30,
            "evaluation_row_count": 8,
            "feature_count": 1,
            "prediction_count": 8,
            "prediction_sha256": "8" * 64,
            "train_sha256": config["train_sha256"],
            "test_sha256": config["test_sha256"],
            "labels_sha256": config.get("labels_sha256"),
            "labels_accessed": config["stage"] == "F3",
            "label_token_contract": "canonical-string-label-v2",
            "confirmation_freeze_hash": config["confirmation_freeze_hash"],
            "reveal_hash": config["reveal_hash"],
            "seed": config["seed"],
            "training_fraction": config["training_fraction"],
            "cpu_seconds": 0.01,
            "wall_seconds": 0.02,
            "peak_rss_mb": 10.0,
            "maximum_memory_mb": config["maximum_memory_mb"],
            "memory_valid": True,
            "network_allowed": False,
        }
        payload["result_hash"] = controller._legacy._canonical_sha256(payload)
        output_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    output_dir = tmp_path / "technical-execution"
    f2 = controller._run_candidate(
        design,
        index,
        task,
        candidate,
        seed=1729,
        stage="F2",
        root=tmp_path.resolve(),
        output_dir=output_dir,
        python_path=fake_python.resolve(),
        candidate_runner=runner.resolve(),
    )
    f3 = controller._run_candidate(
        design,
        index,
        task,
        candidate,
        seed=1729,
        stage="F3",
        root=tmp_path.resolve(),
        output_dir=output_dir,
        python_path=fake_python.resolve(),
        candidate_runner=runner.resolve(),
    )

    f2_attempt = output_dir / "evaluation-cache" / f2["evaluation_id"]
    assert f2["status"] == "succeeded"
    assert f2["labels_accessed"] is False
    assert f2["runner_labels_sha256"] is None
    f2_config = json.loads(
        (
            f2_attempt / "execution-config.json"
        ).read_text(encoding="utf-8")
    )
    assert "labels_path" not in f2_config
    assert "labels_sha256" not in f2_config
    assert f3["status"] == "succeeded"
    assert f3["labels_accessed"] is True
    assert f3["runner_labels_sha256"] == task["labels_sha256"]
    assert f3["replay_exact"] is True
    assert f3["evaluator_integrity_valid"] is True
