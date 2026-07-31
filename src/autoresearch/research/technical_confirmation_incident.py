"""Fail-closed incident adjudication for the Task 263.6.2 technical replay.

The frozen technical replay deliberately refuses to emit a scientific report
when its two interpreter projections differ.  This module does not weaken that
gate or mutate any completed result.  It reads the retained primary/replay
trees, reconstructs the exact mismatch and diagnostic stop decision, and
writes a permanently non-inferential incident research object.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    canonical_sha256,
)

from . import confirmatory_evaluation as confirmation
from . import technical_confirmation_replay as technical
from .portfolio import PortfolioIntegrityError

INCIDENT_REPORT_FILENAME = "consumed-panel-technical-incident.json"
INCIDENT_MARKDOWN_FILENAME = "consumed-panel-technical-incident.md"
INCIDENT_SCHEMA_FILENAME = "consumed-panel-technical-incident-schemas.json"
INCIDENT_MANIFEST_FILENAME = "consumed-panel-technical-incident-manifest.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _with_canonical_hash(
    model: type[KernelContract],
    payload: Mapping[str, Any],
    field: str,
) -> dict[str, Any]:
    normalized = model.model_construct(**dict(payload)).model_dump(
        mode="json",
        exclude={field},
    )
    normalized[field] = canonical_sha256(normalized)
    return normalized


def _load_hashed_json(path: Path, field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PortfolioIntegrityError(f"{path} is not a JSON object")
    expected = payload.get(field)
    if not isinstance(expected, str):
        raise PortfolioIntegrityError(f"{path} lacks {field}")
    body = dict(payload)
    body.pop(field, None)
    if canonical_sha256(body) != expected:
        raise PortfolioIntegrityError(f"{path} has an invalid {field}")
    return payload


class TechnicalReplayIncidentStatus(str, Enum):
    """Terminal class for a completed but non-reproducible technical replay."""

    INVALID_TECHNICAL_REPLAY = "invalid_technical_replay"


class TechnicalProjectionDifference(KernelContract):
    """Minimal content-addressed description of one scientific-path mismatch."""

    schema_version: Literal["technical-projection-difference-v1"] = (
        "technical-projection-difference-v1"
    )
    assignment_id: NonEmptyText
    differing_paths: list[NonEmptyText] = Field(min_length=1)
    primary_result_hash: Sha256
    replay_result_hash: Sha256
    primary_projection_hash: Sha256
    replay_projection_hash: Sha256
    primary_selected_candidate_id: NonEmptyText
    replay_selected_candidate_id: NonEmptyText
    primary_objective_task_success: bool
    replay_objective_task_success: bool
    difference_hash: Sha256

    @model_validator(mode="after")
    def _validate_difference(self) -> TechnicalProjectionDifference:
        if self.primary_projection_hash == self.replay_projection_hash:
            raise ValueError("projection difference has equal projections")
        if self.differing_paths != sorted(set(self.differing_paths)):
            raise ValueError("projection difference paths must be unique and sorted")
        if self.difference_hash != self.calculated_hash():
            raise PortfolioIntegrityError("projection difference_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalProjectionDifference:
        payload = dict(values)
        payload["schema_version"] = "technical-projection-difference-v1"
        payload["differing_paths"] = sorted(set(payload["differing_paths"]))
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "difference_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"difference_hash"})
        )


class TechnicalLabelBoundaryAnomaly(KernelContract):
    """Missing or contradictory label-access attestation in a retained row."""

    schema_version: Literal["technical-label-boundary-anomaly-v1"] = (
        "technical-label-boundary-anomaly-v1"
    )
    interpreter_role: Literal["primary", "replay"]
    evaluation_id: NonEmptyText
    unit_id: NonEmptyText
    within_unit_seed: int
    candidate_id: NonEmptyText
    stage: Literal["F1", "F2", "F3"]
    anomaly_kind: Literal[
        "pre-f3-label-exposure",
        "pre-f3-label-attestation-unavailable",
        "f3-label-binding-mismatch",
        "f3-label-attestation-unavailable",
    ]
    status: NonEmptyText
    failure_domain: NonEmptyText | None = None
    failure_code: NonEmptyText | None = None
    config_labels_path_bound: bool
    config_labels_hash_bound: bool
    labels_accessed: bool | None
    runner_labels_sha256: Sha256 | None = None
    wall_seconds: float = Field(ge=0)
    anomaly_hash: Sha256

    @model_validator(mode="after")
    def _validate_anomaly(self) -> TechnicalLabelBoundaryAnomaly:
        if self.anomaly_hash != self.calculated_hash():
            raise PortfolioIntegrityError("label-boundary anomaly_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalLabelBoundaryAnomaly:
        payload = dict(values)
        payload["schema_version"] = "technical-label-boundary-anomaly-v1"
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "anomaly_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"anomaly_hash"})
        )


class TechnicalReplayIncidentReport(KernelContract):
    """Non-inferential incident object for the failed two-interpreter replay."""

    schema_version: Literal["consumed-panel-technical-incident-v1"] = (
        "consumed-panel-technical-incident-v1"
    )
    incident_id: Literal["task-263.6.2-technical-replay-incident"] = (
        "task-263.6.2-technical-replay-incident"
    )
    status: Literal["invalid_technical_replay"] = "invalid_technical_replay"
    repair_freeze_hash: Sha256
    source_confirmation_freeze_hash: Sha256
    source_report_hash: Sha256
    evaluator_certificate_report_hash: Sha256
    incident_auditor_source_sha256: Sha256
    primary_controller_result_hash: Sha256
    replay_controller_result_hash: Sha256
    primary_scientific_projection_hash: Sha256
    replay_scientific_projection_hash: Sha256
    scientific_projection_exact: Literal[False] = False
    assignment_count_per_interpreter: Literal[1620] = 1620
    null_control_count_per_interpreter: Literal[180] = 180
    projection_differences: list[TechnicalProjectionDifference] = Field(
        min_length=1
    )
    null_projection_difference_ids: list[NonEmptyText]
    label_boundary_anomalies: list[TechnicalLabelBoundaryAnomaly]
    diagnostic_analysis: technical.TechnicalRepairAnalysis
    decision: Literal["stop_portfolio_memory_claim"] = (
        "stop_portfolio_memory_claim"
    )
    next_route: Literal["return_to_objective_opportunity_tournament"] = (
        "return_to_objective_opportunity_tournament"
    )
    formal_technical_report_generated: Literal[False] = False
    inferential_confirmation_claim_allowed: Literal[False] = False
    new_confirmation_authorized: Literal[False] = False
    source_panel_consumed: Literal[True] = True
    technical_only: Literal[True] = True
    exploratory_only: Literal[True] = True
    independent_confirmation_eligible: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    post_reveal_retuning_authorized: Literal[False] = False
    result_contingent_route_change_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    completed_at: datetime
    incident_hash: Sha256

    @field_validator("completed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("incident completion time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_incident(self) -> TechnicalReplayIncidentReport:
        if (
            self.primary_scientific_projection_hash
            == self.replay_scientific_projection_hash
        ):
            raise ValueError("incident requires a scientific projection mismatch")
        if self.projection_differences != sorted(
            self.projection_differences,
            key=lambda item: item.assignment_id,
        ):
            raise ValueError("projection differences must be sorted")
        if self.null_projection_difference_ids != sorted(
            set(self.null_projection_difference_ids)
        ):
            raise ValueError("null projection differences must be unique and sorted")
        if self.label_boundary_anomalies != sorted(
            self.label_boundary_anomalies,
            key=lambda item: (
                item.interpreter_role,
                item.evaluation_id,
            ),
        ):
            raise ValueError("label-boundary anomalies must be sorted")
        if (
            self.diagnostic_analysis.decision
            is not technical.TechnicalRepairDecision.STOP_PORTFOLIO_MEMORY_CLAIM
        ):
            raise ValueError("incident diagnostic must stop the current claim")
        if self.diagnostic_analysis.stop_rule_checks.get(
            "two-interpreter-scientific-projection-exact"
        ):
            raise ValueError("incident cannot claim exact two-interpreter replay")
        if self.incident_hash != self.calculated_hash():
            raise PortfolioIntegrityError("technical incident_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalReplayIncidentReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "consumed-panel-technical-incident-v1",
                "incident_id": "task-263.6.2-technical-replay-incident",
                "status": "invalid_technical_replay",
                "scientific_projection_exact": False,
                "assignment_count_per_interpreter": 1620,
                "null_control_count_per_interpreter": 180,
                "decision": "stop_portfolio_memory_claim",
                "next_route": "return_to_objective_opportunity_tournament",
                "formal_technical_report_generated": False,
                "inferential_confirmation_claim_allowed": False,
                "new_confirmation_authorized": False,
                "source_panel_consumed": True,
                "technical_only": True,
                "exploratory_only": True,
                "independent_confirmation_eligible": False,
                "publication_evidence_eligible": False,
                "post_reveal_retuning_authorized": False,
                "result_contingent_route_change_authorized": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["projection_differences"] = sorted(
            payload["projection_differences"],
            key=lambda item: item.assignment_id,
        )
        payload["null_projection_difference_ids"] = sorted(
            set(payload["null_projection_difference_ids"])
        )
        payload["label_boundary_anomalies"] = sorted(
            payload["label_boundary_anomalies"],
            key=lambda item: (
                item.interpreter_role,
                item.evaluation_id,
            ),
        )
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "incident_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"incident_hash"})
        )


class TechnicalReplayIncidentManifest(KernelContract):
    """Recursive inventory for the failed technical replay and incident."""

    schema_version: Literal["consumed-panel-technical-incident-manifest-v1"] = (
        "consumed-panel-technical-incident-manifest-v1"
    )
    repair_freeze_hash: Sha256
    incident_hash: Sha256
    artifact_hashes: dict[NonEmptyText, Sha256]
    artifact_count: int = Field(ge=1)
    consumed_confirmation_payloads_included: Literal[True] = True
    independent_confirmation_eligible: Literal[False] = False
    publication_evidence_eligible: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> TechnicalReplayIncidentManifest:
        if list(self.artifact_hashes) != sorted(self.artifact_hashes):
            raise ValueError("incident artifact hashes must be sorted")
        if self.artifact_count != len(self.artifact_hashes):
            raise ValueError("incident artifact_count mismatch")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("incident manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TechnicalReplayIncidentManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": (
                    "consumed-panel-technical-incident-manifest-v1"
                ),
                "consumed_confirmation_payloads_included": True,
                "independent_confirmation_eligible": False,
                "publication_evidence_eligible": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["artifact_hashes"] = dict(
            sorted(payload["artifact_hashes"].items())
        )
        payload["artifact_count"] = len(payload["artifact_hashes"])
        return cls.model_validate(
            _with_canonical_hash(cls, payload, "manifest_hash")
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


TECHNICAL_INCIDENT_CONTRACT_MODELS = (
    TechnicalProjectionDifference,
    TechnicalLabelBoundaryAnomaly,
    TechnicalReplayIncidentReport,
    TechnicalReplayIncidentManifest,
)


def technical_incident_json_schemas() -> dict[str, dict[str, Any]]:
    """Return deterministic schemas for the fail-closed incident object."""

    return {
        model.__name__: model.model_json_schema()
        for model in TECHNICAL_INCIDENT_CONTRACT_MODELS
    }


def _difference_paths(
    primary: Any,
    replay: Any,
    *,
    prefix: str = "",
) -> list[str]:
    if isinstance(primary, Mapping) and isinstance(replay, Mapping):
        paths: list[str] = []
        for key in sorted(set(primary).union(replay)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in primary or key not in replay:
                paths.append(child)
            else:
                paths.extend(
                    _difference_paths(
                        primary[key],
                        replay[key],
                        prefix=child,
                    )
                )
        return paths
    if (
        isinstance(primary, Sequence)
        and not isinstance(primary, str | bytes)
        and isinstance(replay, Sequence)
        and not isinstance(replay, str | bytes)
    ):
        paths = []
        for index in range(max(len(primary), len(replay))):
            child = f"{prefix}[{index}]"
            if index >= len(primary) or index >= len(replay):
                paths.append(child)
            else:
                paths.extend(
                    _difference_paths(
                        primary[index],
                        replay[index],
                        prefix=child,
                    )
                )
        return paths
    return [] if primary == replay else [prefix or "$"]


def _null_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in (
            "unit_id",
            "within_unit_seed",
            "candidate_id",
            "score",
            "baseline_score",
            "minimum_gain",
            "normalized_margin",
            "objective_task_success",
            "artifact_valid",
            "prediction_replay_valid",
            "evaluator_integrity_valid",
            "failure_code",
        )
    }


def _load_result_map(
    workspace: Path,
    controller: Mapping[str, Any],
    *,
    kind: Literal["assignments", "null-controls"],
) -> dict[str, dict[str, Any]]:
    mapping_name = (
        "assignment_result_hashes"
        if kind == "assignments"
        else "null_control_result_hashes"
    )
    hash_mapping = controller.get(mapping_name)
    if not isinstance(hash_mapping, dict):
        raise PortfolioIntegrityError(f"controller lacks {mapping_name}")
    results: dict[str, dict[str, Any]] = {}
    for result_id, expected_hash in sorted(hash_mapping.items()):
        path = (
            workspace
            / "technical-execution"
            / kind
            / str(result_id)
            / "result.json"
        )
        result = _load_hashed_json(path, "result_hash")
        if result["result_hash"] != expected_hash:
            raise PortfolioIntegrityError(
                f"{kind} result hash differs: {result_id}"
            )
        results[str(result_id)] = result
    return results


def _label_boundary_anomaly_kind(
    *,
    stage: str,
    config_labels_path_bound: bool,
    config_labels_hash_bound: bool,
    labels_path_present: bool,
    labels_hash_present: bool,
    labels_accessed: bool | None,
    runner_labels_sha256: str | None,
) -> str | None:
    """Classify incomplete label-boundary evidence without inferring leakage."""

    if stage in {"F1", "F2"}:
        exposed = (
            labels_path_present
            or labels_hash_present
            or runner_labels_sha256 is not None
            or labels_accessed is True
        )
        if exposed:
            return "pre-f3-label-exposure"
        if labels_accessed is not False:
            return "pre-f3-label-attestation-unavailable"
        return None
    if stage != "F3":
        return None
    if not config_labels_path_bound or not config_labels_hash_bound:
        return "f3-label-binding-mismatch"
    if labels_accessed is not True:
        return "f3-label-attestation-unavailable"
    return None


def _load_evaluations(
    workspace: Path,
    results: Mapping[str, Mapping[str, Any]],
    null_results: Mapping[str, Mapping[str, Any]],
    index: confirmation.ConfirmatoryExecutionIndex,
    *,
    role: Literal["primary", "replay"],
) -> tuple[list[dict[str, Any]], list[TechnicalLabelBoundaryAnomaly]]:
    referenced = {
        str(record["evaluation_hash"])
        for result in results.values()
        for record in result["stage_records"]
        if record["evaluation_hash"] is not None
    }.union(
        str(result["evaluation_hash"]) for result in null_results.values()
    )
    task_by_id = {task.unit_id: task for task in index.tasks}
    evaluations: dict[str, dict[str, Any]] = {}
    anomalies: list[TechnicalLabelBoundaryAnomaly] = []
    cache_root = workspace / "technical-execution/evaluation-cache"
    for path in sorted(cache_root.glob("*/evaluation.json")):
        evaluation = _load_hashed_json(path, "evaluation_hash")
        evaluation_hash = str(evaluation["evaluation_hash"])
        evaluations[evaluation_hash] = evaluation
        stage = str(evaluation["stage"])
        if stage not in {"F1", "F2", "F3"}:
            continue
        config_payload = json.loads(
            (path.parent / "execution-config.json").read_text(encoding="utf-8")
        )
        if not isinstance(config_payload, dict):
            raise PortfolioIntegrityError(
                f"evaluation config is not an object: {path.parent.name}"
            )
        task = task_by_id[str(evaluation["unit_id"])]
        labels_path_bound = (
            config_payload.get("labels_path") == task.labels_path
        )
        labels_hash_bound = (
            config_payload.get("labels_sha256") == task.labels_sha256
        )
        labels_accessed = evaluation.get("labels_accessed")
        runner_labels_sha256 = evaluation.get("runner_labels_sha256")
        anomaly_kind = _label_boundary_anomaly_kind(
            stage=stage,
            config_labels_path_bound=labels_path_bound,
            config_labels_hash_bound=labels_hash_bound,
            labels_path_present="labels_path" in config_payload,
            labels_hash_present="labels_sha256" in config_payload,
            labels_accessed=labels_accessed,
            runner_labels_sha256=runner_labels_sha256,
        )
        if anomaly_kind is not None:
            anomalies.append(
                TechnicalLabelBoundaryAnomaly.create(
                    interpreter_role=role,
                    evaluation_id=path.parent.name,
                    unit_id=str(evaluation["unit_id"]),
                    within_unit_seed=int(evaluation["within_unit_seed"]),
                    candidate_id=str(evaluation["candidate_id"]),
                    stage=stage,
                    anomaly_kind=anomaly_kind,
                    status=str(evaluation["status"]),
                    failure_domain=evaluation.get("failure_domain"),
                    failure_code=evaluation.get("failure_code"),
                    config_labels_path_bound=labels_path_bound,
                    config_labels_hash_bound=labels_hash_bound,
                    labels_accessed=labels_accessed,
                    runner_labels_sha256=runner_labels_sha256,
                    wall_seconds=float(evaluation["wall_seconds"]),
                )
            )
    if set(evaluations) != referenced:
        raise PortfolioIntegrityError(
            f"{role} incident evaluation inventory differs from references"
        )
    return (
        [evaluations[key] for key in sorted(evaluations)],
        sorted(
            anomalies,
            key=lambda item: (
                item.interpreter_role,
                item.evaluation_id,
            ),
        ),
    )


def _projection_differences(
    primary: Mapping[str, Mapping[str, Any]],
    replay: Mapping[str, Mapping[str, Any]],
) -> list[TechnicalProjectionDifference]:
    if set(primary) != set(replay):
        raise PortfolioIntegrityError(
            "primary/replay assignment inventories differ"
        )
    differences: list[TechnicalProjectionDifference] = []
    for assignment_id in sorted(primary):
        primary_result = primary[assignment_id]
        replay_result = replay[assignment_id]
        primary_projection = technical._assignment_projection(primary_result)
        replay_projection = technical._assignment_projection(replay_result)
        primary_hash = canonical_sha256(primary_projection)
        replay_hash = canonical_sha256(replay_projection)
        if primary_hash == replay_hash:
            continue
        differences.append(
            TechnicalProjectionDifference.create(
                assignment_id=assignment_id,
                differing_paths=_difference_paths(
                    primary_projection,
                    replay_projection,
                ),
                primary_result_hash=str(primary_result["result_hash"]),
                replay_result_hash=str(replay_result["result_hash"]),
                primary_projection_hash=primary_hash,
                replay_projection_hash=replay_hash,
                primary_selected_candidate_id=str(
                    primary_result["selected_candidate_id"]
                ),
                replay_selected_candidate_id=str(
                    replay_result["selected_candidate_id"]
                ),
                primary_objective_task_success=bool(
                    primary_result["objective_task_success"]
                ),
                replay_objective_task_success=bool(
                    replay_result["objective_task_success"]
                ),
            )
        )
    return differences


def _null_projection_differences(
    primary: Mapping[str, Mapping[str, Any]],
    replay: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    if set(primary) != set(replay):
        raise PortfolioIntegrityError("primary/replay null inventories differ")
    return [
        result_id
        for result_id in sorted(primary)
        if canonical_sha256(_null_projection(primary[result_id]))
        != canonical_sha256(_null_projection(replay[result_id]))
    ]


def _build_incident_report(
    source_confirmation_dir: Path,
    evaluator_certificate_dir: Path,
    output_dir: Path,
    *,
    completed_at: datetime,
) -> TechnicalReplayIncidentReport:
    repair = technical.freeze_consumed_panel_repair(
        source_confirmation_dir,
        evaluator_certificate_dir,
        output_dir,
    )
    source_report = confirmation.ConfirmatoryEvaluationReport.model_validate_json(
        (
            source_confirmation_dir
            / confirmation.CONFIRMATION_REPORT_FILENAME
        ).read_text(encoding="utf-8")
    )
    if source_report.report_hash != repair.source_report_hash:
        raise PortfolioIntegrityError("incident source report binding differs")

    primary_workspace = output_dir / technical.PRIMARY_WORKSPACE
    replay_workspace = output_dir / technical.REPLAY_WORKSPACE
    primary_controller = _load_hashed_json(
        primary_workspace / technical.CONTROLLER_RESULT_RELATIVE,
        "result_hash",
    )
    replay_controller = _load_hashed_json(
        replay_workspace / technical.CONTROLLER_RESULT_RELATIVE,
        "result_hash",
    )
    for role, controller in (
        ("primary", primary_controller),
        ("replay", replay_controller),
    ):
        if (
            controller.get("repair_freeze_hash") != repair.repair_freeze_hash
            or controller.get("assignment_count") != 1620
            or controller.get("null_control_count") != 180
            or controller.get("full_matrix_complete") is not True
            or controller.get("technical_only") is not True
            or controller.get("publication_evidence_eligible") is not False
        ):
            raise PortfolioIntegrityError(
                f"{role} incident controller boundary differs"
            )
    if (
        primary_controller["scientific_projection_hash"]
        == replay_controller["scientific_projection_hash"]
    ):
        raise PortfolioIntegrityError(
            "technical replay is exact; an incident is not applicable"
        )

    primary_index = confirmation.ConfirmatoryExecutionIndex.model_validate_json(
        (
            primary_workspace / confirmation.EXECUTION_INDEX_FILENAME
        ).read_text(encoding="utf-8")
    )
    replay_index = confirmation.ConfirmatoryExecutionIndex.model_validate_json(
        (
            replay_workspace / confirmation.EXECUTION_INDEX_FILENAME
        ).read_text(encoding="utf-8")
    )
    if (
        primary_index.execution_index_hash
        != repair.technical_execution_index_hashes["primary"]
        or replay_index.execution_index_hash
        != repair.technical_execution_index_hashes["replay"]
    ):
        raise PortfolioIntegrityError("incident execution-index binding differs")

    primary_results = _load_result_map(
        primary_workspace,
        primary_controller,
        kind="assignments",
    )
    replay_results = _load_result_map(
        replay_workspace,
        replay_controller,
        kind="assignments",
    )
    primary_null = _load_result_map(
        primary_workspace,
        primary_controller,
        kind="null-controls",
    )
    replay_null = _load_result_map(
        replay_workspace,
        replay_controller,
        kind="null-controls",
    )
    differences = _projection_differences(primary_results, replay_results)
    if not differences:
        raise PortfolioIntegrityError(
            "controller projections differ without an assignment difference"
        )
    null_differences = _null_projection_differences(
        primary_null,
        replay_null,
    )

    primary_evaluations, primary_anomalies = _load_evaluations(
        primary_workspace,
        primary_results,
        primary_null,
        primary_index,
        role="primary",
    )
    _, replay_anomalies = _load_evaluations(
        replay_workspace,
        replay_results,
        replay_null,
        replay_index,
        role="replay",
    )
    analysis = technical._analyze_technical_repair(
        source_report,
        repair,
        primary_controller,
        replay_controller,
        (
            primary_index,
            list(primary_results.values()),
            list(primary_null.values()),
            primary_evaluations,
        ),
    )
    if (
        analysis.decision
        is not technical.TechnicalRepairDecision.STOP_PORTFOLIO_MEMORY_CLAIM
    ):
        raise PortfolioIntegrityError(
            "failed replay did not produce the frozen stop decision"
        )
    return TechnicalReplayIncidentReport.create(
        repair_freeze_hash=repair.repair_freeze_hash,
        source_confirmation_freeze_hash=(
            repair.source_confirmation_freeze_hash
        ),
        source_report_hash=repair.source_report_hash,
        evaluator_certificate_report_hash=(
            repair.evaluator_certificate_report_hash
        ),
        incident_auditor_source_sha256=_file_sha256(Path(__file__).resolve()),
        primary_controller_result_hash=primary_controller["result_hash"],
        replay_controller_result_hash=replay_controller["result_hash"],
        primary_scientific_projection_hash=primary_controller[
            "scientific_projection_hash"
        ],
        replay_scientific_projection_hash=replay_controller[
            "scientific_projection_hash"
        ],
        projection_differences=differences,
        null_projection_difference_ids=null_differences,
        label_boundary_anomalies=primary_anomalies + replay_anomalies,
        diagnostic_analysis=analysis,
        completed_at=completed_at,
    )


def render_technical_incident_markdown(
    report: TechnicalReplayIncidentReport,
) -> str:
    """Render the incident without presenting diagnostics as confirmation."""

    comparison = report.diagnostic_analysis.primary_comparison
    summaries = {
        item.policy_id: item
        for item in report.diagnostic_analysis.policy_summaries
    }
    differing_assignments = "\n".join(
        f"- `{item.assignment_id}`: {', '.join(item.differing_paths)}"
        for item in report.projection_differences
    )
    anomaly_counts: dict[str, int] = {}
    for item in report.label_boundary_anomalies:
        anomaly_counts[item.anomaly_kind] = (
            anomaly_counts.get(item.anomaly_kind, 0) + 1
        )
    anomalies = "\n".join(
        f"- `{key}`: `{value}`"
        for key, value in sorted(anomaly_counts.items())
    )
    stop_checks = "\n".join(
        f"- `{key}`: `{value}`"
        for key, value in report.diagnostic_analysis.stop_rule_checks.items()
    )
    return (
        "# Task 263.6.2 consumed-panel technical replay incident\n\n"
        "> **INVALID TECHNICAL REPLAY / CONSUMED PANEL / NON-INFERENTIAL.** "
        "The two frozen interpreters completed the matrix but did not produce "
        "the same scientific projection. This object cannot support an "
        "independent-confirmation or publication claim.\n\n"
        f"- Decision: `{report.decision}`\n"
        f"- Next route: `{report.next_route}`\n"
        f"- Differing assignment projections: "
        f"`{len(report.projection_differences)}/1620`\n"
        f"- Differing null projections: "
        f"`{len(report.null_projection_difference_ids)}/180`\n"
        f"- Label-boundary attestation anomalies: "
        f"`{len(report.label_boundary_anomalies)}`\n"
        f"- `portfolio_memory` diagnostic successes: "
        f"`{summaries['portfolio_memory'].task_success_count}/60`\n"
        f"- `linear_self_loop` diagnostic successes: "
        f"`{summaries['linear_self_loop'].task_success_count}/60`\n"
        f"- Diagnostic risk difference: "
        f"`{comparison.risk_difference_a_minus_b:.6f}`\n"
        f"- Diagnostic exact 95% interval: "
        f"`[{comparison.exact_risk_difference_interval_95[0]:.6f}, "
        f"{comparison.exact_risk_difference_interval_95[1]:.6f}]`\n"
        f"- Diagnostic exact McNemar p: "
        f"`{comparison.exact_mcnemar_p:.12g}`\n\n"
        "## Scientific projection differences\n\n"
        f"{differing_assignments}\n\n"
        "## Label-boundary anomaly classes\n\n"
        f"{anomalies}\n\n"
        "A missing label-access attestation on a timed-out process is not "
        "evidence of label leakage. It is an incomplete execution attestation "
        "and therefore fails the frozen conjunction.\n\n"
        "## Frozen stop checks\n\n"
        f"{stop_checks}\n\n"
        "## Boundary\n\n"
        "The descriptive effect is unfavorable, both benchmark-family risk "
        "differences are negative, favorable tasks do not outnumber "
        "unfavorable tasks, infrastructure/candidate failures remain, and "
        "two-interpreter replay is not exact. The `portfolio_memory` claim is "
        "closed. A new panel is not authorized. Future work must return to an "
        "objective opportunity tournament with a different question or new "
        "mechanism and new development evidence. Public release and external "
        "submission remain unauthorized.\n"
    )


def _incident_artifact_hashes(output_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    excluded = {
        INCIDENT_MANIFEST_FILENAME,
        technical.TECHNICAL_MANIFEST_FILENAME,
    }
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative in excluded or relative.endswith(".tmp"):
            continue
        hashes[relative] = _file_sha256(path)
    return dict(sorted(hashes.items()))


def write_consumed_panel_technical_incident(
    source_confirmation_dir: Path,
    evaluator_certificate_dir: Path,
    output_dir: Path,
    *,
    completed_at: datetime | None = None,
) -> tuple[TechnicalReplayIncidentReport, TechnicalReplayIncidentManifest]:
    """Write or reload the immutable fail-closed incident research object."""

    source_confirmation_dir = source_confirmation_dir.resolve()
    evaluator_certificate_dir = evaluator_certificate_dir.resolve()
    output_dir = output_dir.resolve()
    report_path = output_dir / INCIDENT_REPORT_FILENAME
    manifest_path = output_dir / INCIDENT_MANIFEST_FILENAME
    if report_path.exists() or manifest_path.exists():
        return load_consumed_panel_technical_incident(
            output_dir,
            source_confirmation_dir=source_confirmation_dir,
            evaluator_certificate_dir=evaluator_certificate_dir,
            reconstruct=True,
        )
    if (output_dir / technical.TECHNICAL_REPORT_FILENAME).exists():
        raise PortfolioIntegrityError(
            "a valid technical report exists; incident adjudication is inapplicable"
        )
    report = _build_incident_report(
        source_confirmation_dir,
        evaluator_certificate_dir,
        output_dir,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    _write_text_atomic(report_path, report.canonical_json() + "\n")
    _write_text_atomic(
        output_dir / INCIDENT_MARKDOWN_FILENAME,
        render_technical_incident_markdown(report),
    )
    _write_text_atomic(
        output_dir / INCIDENT_SCHEMA_FILENAME,
        json.dumps(
            technical_incident_json_schemas(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    manifest = TechnicalReplayIncidentManifest.create(
        repair_freeze_hash=report.repair_freeze_hash,
        incident_hash=report.incident_hash,
        artifact_hashes=_incident_artifact_hashes(output_dir),
    )
    _write_text_atomic(
        manifest_path,
        manifest.canonical_json() + "\n",
    )
    return report, manifest


def load_consumed_panel_technical_incident(
    output_dir: Path,
    *,
    source_confirmation_dir: Path | None = None,
    evaluator_certificate_dir: Path | None = None,
    reconstruct: bool = False,
) -> tuple[TechnicalReplayIncidentReport, TechnicalReplayIncidentManifest]:
    """Load, hash-check, and optionally reconstruct the incident object."""

    output_dir = output_dir.resolve()
    report = TechnicalReplayIncidentReport.model_validate_json(
        (output_dir / INCIDENT_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = TechnicalReplayIncidentManifest.model_validate_json(
        (output_dir / INCIDENT_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    if (
        manifest.incident_hash != report.incident_hash
        or manifest.repair_freeze_hash != report.repair_freeze_hash
    ):
        raise PortfolioIntegrityError("incident report/manifest binding differs")
    current_hashes = _incident_artifact_hashes(output_dir)
    if current_hashes != manifest.artifact_hashes:
        raise PortfolioIntegrityError("incident recursive artifact inventory differs")
    if _file_sha256(Path(__file__).resolve()) != report.incident_auditor_source_sha256:
        raise PortfolioIntegrityError("incident auditor source changed")
    repair = technical.ConsumedPanelRepairFreeze.model_validate_json(
        (
            output_dir / technical.REPAIR_FREEZE_FILENAME
        ).read_text(encoding="utf-8")
    )
    if repair.repair_freeze_hash != report.repair_freeze_hash:
        raise PortfolioIntegrityError("incident repair-freeze binding differs")
    for role, expected_hash in (
        ("primary", report.primary_controller_result_hash),
        ("replay", report.replay_controller_result_hash),
    ):
        controller = _load_hashed_json(
            output_dir
            / (
                technical.PRIMARY_WORKSPACE
                if role == "primary"
                else technical.REPLAY_WORKSPACE
            )
            / technical.CONTROLLER_RESULT_RELATIVE,
            "result_hash",
        )
        if controller["result_hash"] != expected_hash:
            raise PortfolioIntegrityError(
                f"incident {role} controller binding differs"
            )
    if reconstruct:
        if source_confirmation_dir is None or evaluator_certificate_dir is None:
            raise ValueError(
                "incident reconstruction requires source and certificate directories"
            )
        rebuilt = _build_incident_report(
            source_confirmation_dir.resolve(),
            evaluator_certificate_dir.resolve(),
            output_dir,
            completed_at=report.completed_at,
        )
        if rebuilt.incident_hash != report.incident_hash:
            raise PortfolioIntegrityError(
                "incident deterministic reconstruction differs"
            )
    return report, manifest
