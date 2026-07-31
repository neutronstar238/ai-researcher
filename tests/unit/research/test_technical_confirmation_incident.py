from copy import deepcopy

import pytest
from pydantic import ValidationError

from autoresearch.research.technical_confirmation_incident import (
    TechnicalProjectionDifference,
    _difference_paths,
    _label_boundary_anomaly_kind,
    _projection_differences,
    technical_incident_json_schemas,
)

SHA = "a" * 64


def _assignment_result() -> dict[str, object]:
    return {
        "result_hash": SHA,
        "unit_id": "task-1",
        "within_unit_seed": 1729,
        "policy_id": "portfolio_memory",
        "selected_candidate_id": "lgbm-shallow",
        "selected_candidate_family": "gradient_boosting",
        "policy_score": 0.8,
        "baseline_score": 0.5,
        "minimum_gain": 0.1,
        "normalized_margin": 0.2,
        "objective_task_success": True,
        "artifact_valid": True,
        "prediction_replay_valid": True,
        "budget_valid": True,
        "evaluator_integrity_valid": True,
        "failure_codes": [],
        "memory_before_hash": "b" * 64,
        "memory_after_hash": "c" * 64,
        "stage_records": [
            {
                "candidate_id": "xgb-deep",
                "stage": "F1",
                "status": "succeeded",
                "objective_score": 0.7,
                "selection_score": 0.7,
                "memory_correction": 0.0,
                "promoted": True,
                "failure_code": None,
            }
        ],
        "cost": {"newly_executed_wall_seconds": 12.0},
    }


def test_difference_paths_reports_nested_scientific_changes() -> None:
    primary = {"stage_records": [{"status": "succeeded", "score": 0.9}]}
    replay = {"stage_records": [{"status": "failed", "score": None}]}

    assert _difference_paths(primary, replay) == [
        "stage_records[0].score",
        "stage_records[0].status",
    ]


def test_projection_difference_ignores_cost_but_detects_stage_timeout() -> None:
    primary = _assignment_result()
    replay = deepcopy(primary)
    replay["result_hash"] = "d" * 64
    replay["cost"] = {"newly_executed_wall_seconds": 60.0}

    assert _projection_differences({"assignment": primary}, {"assignment": replay}) == []

    replay_stage = replay["stage_records"]
    assert isinstance(replay_stage, list)
    assert isinstance(replay_stage[0], dict)
    replay_stage[0]["status"] = "failed"
    replay_stage[0]["objective_score"] = None
    replay_stage[0]["selection_score"] = None
    replay_stage[0]["promoted"] = False
    replay_stage[0]["failure_code"] = "runner_timeout"

    differences = _projection_differences(
        {"assignment": primary},
        {"assignment": replay},
    )

    assert len(differences) == 1
    assert differences[0].assignment_id == "assignment"
    assert "stage_records[0].status" in differences[0].differing_paths
    assert "stage_records[0].failure_code" in differences[0].differing_paths
    assert differences[0].primary_selected_candidate_id == "lgbm-shallow"
    assert differences[0].replay_selected_candidate_id == "lgbm-shallow"


def test_timeout_with_bound_f3_labels_is_incomplete_attestation_not_leakage() -> None:
    assert (
        _label_boundary_anomaly_kind(
            stage="F3",
            config_labels_path_bound=True,
            config_labels_hash_bound=True,
            labels_path_present=True,
            labels_hash_present=True,
            labels_accessed=None,
            runner_labels_sha256=None,
        )
        == "f3-label-attestation-unavailable"
    )
    assert (
        _label_boundary_anomaly_kind(
            stage="F2",
            config_labels_path_bound=False,
            config_labels_hash_bound=False,
            labels_path_present=False,
            labels_hash_present=False,
            labels_accessed=False,
            runner_labels_sha256=None,
        )
        is None
    )
    assert (
        _label_boundary_anomaly_kind(
            stage="F1",
            config_labels_path_bound=False,
            config_labels_hash_bound=False,
            labels_path_present=True,
            labels_hash_present=False,
            labels_accessed=False,
            runner_labels_sha256=None,
        )
        == "pre-f3-label-exposure"
    )


def test_incident_schemas_lock_every_claim_and_release_gate_closed() -> None:
    schemas = technical_incident_json_schemas()
    report_properties = schemas["TechnicalReplayIncidentReport"]["properties"]
    manifest_properties = schemas["TechnicalReplayIncidentManifest"]["properties"]

    for field in (
        "formal_technical_report_generated",
        "inferential_confirmation_claim_allowed",
        "new_confirmation_authorized",
        "independent_confirmation_eligible",
        "publication_evidence_eligible",
        "post_reveal_retuning_authorized",
        "result_contingent_route_change_authorized",
        "public_release_authorized",
        "external_submission_authorized",
    ):
        assert report_properties[field]["const"] is False
    for field in (
        "independent_confirmation_eligible",
        "publication_evidence_eligible",
        "public_release_authorized",
        "external_submission_authorized",
    ):
        assert manifest_properties[field]["const"] is False


def test_projection_difference_rejects_hash_tamper() -> None:
    difference = TechnicalProjectionDifference.create(
        assignment_id="assignment",
        differing_paths=["stage_records[0].status"],
        primary_result_hash=SHA,
        replay_result_hash="b" * 64,
        primary_projection_hash="c" * 64,
        replay_projection_hash="d" * 64,
        primary_selected_candidate_id="lgbm-shallow",
        replay_selected_candidate_id="lgbm-shallow",
        primary_objective_task_success=True,
        replay_objective_task_success=True,
    )
    payload = difference.model_dump(mode="json")
    payload["primary_selected_candidate_id"] = "xgb-deep"

    with pytest.raises(ValidationError, match="difference_hash"):
        TechnicalProjectionDifference.model_validate(payload)
