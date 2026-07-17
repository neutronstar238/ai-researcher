"""Cycle manifest persistence and causal-chain evidence validation."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from autoresearch.competition.models import (
    AttemptStatus,
    CompetitionSubmission,
    CycleManifest,
    EvidenceGateReport,
    ExperimentProtocol,
    HypothesisProposal,
    TopicCandidate,
)
from autoresearch.schemas import data_hash, file_hash


class ManifestIntegrityError(ValueError):
    """Raised when persisted manifest bytes do not match their recorded hash."""


def canonical_model_hash(model: BaseModel | dict[str, Any]) -> str:
    """Hash a model using the project's canonical JSON provenance helper."""

    return data_hash(model)


def write_json_model(path: Path | str, model: BaseModel | dict[str, Any]) -> Path:
    """Atomically write one deterministic JSON artifact."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return output_path


def write_cycle_manifest(path: Path | str, manifest: CycleManifest) -> CycleManifest:
    """Stamp, hash, and atomically persist a cycle manifest."""

    unstamped = manifest.model_copy(
        update={
            "updated_at": datetime.now(timezone.utc),
            "manifest_hash": None,
        }
    )
    digest = _manifest_digest(unstamped)
    stamped = unstamped.model_copy(update={"manifest_hash": digest})
    write_json_model(path, stamped)
    return stamped


def load_cycle_manifest(path: Path | str) -> CycleManifest:
    """Load a manifest and reject byte-valid but causally altered payloads."""

    manifest = CycleManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    expected = _manifest_digest(manifest.model_copy(update={"manifest_hash": None}))
    if manifest.manifest_hash != expected:
        raise ManifestIntegrityError("cycle manifest hash mismatch")
    return manifest


def validate_cycle_evidence(
    *,
    manifest: CycleManifest,
    topic: TopicCandidate,
    hypothesis: HypothesisProposal,
    protocol: ExperimentProtocol,
) -> EvidenceGateReport:
    """Validate that claims and metrics belong to one executed causal chain."""

    failures: list[str] = []
    warnings: list[str] = []
    _check_identifiers(manifest, topic, hypothesis, protocol, failures)

    expected_plan_hash = canonical_model_hash(protocol)
    if manifest.plan_hash != expected_plan_hash:
        failures.append("plan hash mismatch: executed protocol differs from manifest")

    expected_seeds = set(protocol.seeds)
    attempt_seeds = {attempt.seed for attempt in manifest.attempts}
    if attempt_seeds != expected_seeds:
        failures.append(
            "replication seed mismatch: manifest attempts do not cover the compiled protocol"
        )

    first_attempt_id = manifest.attempts[0].attempt_id if manifest.attempts else None
    for index, attempt in enumerate(manifest.attempts):
        if attempt.topic_id != topic.topic_id:
            failures.append(
                f"attempt {attempt.attempt_id} topic mismatch: candidate was not executed"
            )
        if attempt.hypothesis_id != hypothesis.hypothesis_id:
            failures.append(
                f"attempt {attempt.attempt_id} hypothesis mismatch: plan was not executed"
            )
        if attempt.protocol_id != protocol.protocol_id:
            failures.append(f"attempt {attempt.attempt_id} protocol mismatch")
        if attempt.plan_hash != expected_plan_hash:
            failures.append(f"attempt {attempt.attempt_id} plan hash mismatch")
        if attempt.status is not AttemptStatus.SUCCEEDED:
            failures.append(f"attempt {attempt.attempt_id} did not succeed")
        if attempt.validation_status not in {"passed", "warning"}:
            failures.append(f"attempt {attempt.attempt_id} did not pass result validation")
        if attempt.metrics_hash != data_hash(attempt.metrics):
            failures.append(f"attempt {attempt.attempt_id} metrics hash mismatch")
        if _constant_metric_payload(attempt.metrics):
            failures.append(
                f"attempt {attempt.attempt_id} constant metrics are not admissible evidence"
            )
        if index == 0 and attempt.parent_attempt_id is not None:
            failures.append("first experiment attempt must not have a parent")
        if index > 0 and attempt.parent_attempt_id != first_attempt_id:
            failures.append(
                f"attempt {attempt.attempt_id} is not a replication of the first attempt"
            )
        _check_attempt_files(attempt, failures)

    attempt_by_id = {attempt.attempt_id: attempt for attempt in manifest.attempts}
    for claim in manifest.claims:
        if claim.topic_id != topic.topic_id or claim.hypothesis_id != hypothesis.hypothesis_id:
            failures.append(f"claim {claim.claim_id} topic/hypothesis mismatch")
            continue
        for attempt_id in claim.attempt_ids:
            claim_attempt = attempt_by_id.get(attempt_id)
            if claim_attempt is None:
                failures.append(f"claim {claim.claim_id} references unknown attempt {attempt_id}")
            elif claim.metric_name not in claim_attempt.metrics:
                failures.append(
                    f"claim {claim.claim_id} metric is absent from attempt {attempt_id}"
                )

    if protocol.development_fixture:
        warnings.append(
            "development characterization fixture only; official MDBench matrix not executed"
        )
    if manifest.human_intervention_count != 0:
        warnings.append("research cycle recorded human intervention")

    release_allowed = not failures and _full_gate_a_passed(manifest, protocol)
    if not release_allowed:
        warnings.append(
            "Gate A release is blocked until 10 ODE, 4 PDE, clean/noisy, and three-run "
            "official benchmark evidence is present"
        )
    return EvidenceGateReport(
        passed=not failures,
        release_allowed=release_allowed,
        failures=tuple(dict.fromkeys(failures)),
        warnings=tuple(dict.fromkeys(warnings)),
        checked_attempt_ids=tuple(attempt.attempt_id for attempt in manifest.attempts),
    )


def write_evidence_gate_report(
    path: Path | str,
    report: EvidenceGateReport,
) -> EvidenceGateReport:
    stamped_report = report.model_copy(update={"output_path": Path(path).as_posix()})
    write_json_model(path, stamped_report)
    return stamped_report


def build_competition_submission(
    *,
    manifest_path: Path,
    manifest: CycleManifest,
    topic: TopicCandidate,
    protocol: ExperimentProtocol,
    evidence_gate: EvidenceGateReport,
) -> CompetitionSubmission:
    """Build all required fields while keeping development exports visibly blocked."""

    metric_rows: list[str] = []
    for attempt in manifest.attempts:
        metric_rows.append(
            f"seed={attempt.seed}: derivative_nmse={attempt.metrics.get('derivative_nmse')}, "
            f"structure_f1={attempt.metrics.get('equation_structure_f1')}"
        )
    blocked = (*evidence_gate.failures, *evidence_gate.warnings)
    return CompetitionSubmission(
        run_id=manifest.run_id,
        problem_statement=topic.problem_statement,
        rationale=(
            "Gate A first tests whether the system can bind a model-discovery hypothesis to "
            "real code, metrics, replications, and a causal manifest before costly Gate B work."
        ),
        technical_details=(
            "The current artifact uses sparse polynomial regression, an executed constant "
            "baseline, deterministic seeds, sandbox validation, and hash-chain evidence."
        ),
        datasets=topic.dataset_refs,
        source="generated MDBench-compatible characterization fixture",
        target="known logistic governing equation and derivative field",
        paper_title=topic.title,
        paper_abstract=(
            "Development-only Gate A characterization. Official MDBench acceptance remains "
            "blocked until the full clean/noisy ODE/PDE matrix is executed."
        ),
        methods=(protocol.candidate_method, *protocol.baseline_methods),
        experiments=tuple(task.description for task in protocol.tasks),
        results=tuple(metric_rows),
        references=topic.literature_evidence,
        rubric_evidence=topic.scorecard,
        manifest_path=manifest_path.as_posix(),
        submission_ready=evidence_gate.release_allowed,
        blocked_reasons=blocked if not evidence_gate.release_allowed else (),
    )


def _manifest_digest(manifest: CycleManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"manifest_hash"})
    return data_hash(payload)


def _check_identifiers(
    manifest: CycleManifest,
    topic: TopicCandidate,
    hypothesis: HypothesisProposal,
    protocol: ExperimentProtocol,
    failures: list[str],
) -> None:
    if hypothesis.topic_id != topic.topic_id:
        failures.append("topic/hypothesis mismatch: hypothesis belongs to another candidate")
    if protocol.topic_id != topic.topic_id:
        failures.append("topic/protocol mismatch: experiment belongs to another candidate")
    if protocol.hypothesis_id != hypothesis.hypothesis_id:
        failures.append("hypothesis/protocol mismatch: compiled plan belongs to another hypothesis")
    if manifest.topic_id != topic.topic_id:
        failures.append("manifest topic mismatch")
    if manifest.hypothesis_id != hypothesis.hypothesis_id:
        failures.append("manifest hypothesis mismatch")
    if manifest.protocol_id != protocol.protocol_id:
        failures.append("manifest protocol mismatch")


def _check_attempt_files(attempt: Any, failures: list[str]) -> None:
    if not attempt.metrics_path:
        failures.append(f"attempt {attempt.attempt_id} has no executed metrics path")
        return
    metrics_path = Path(attempt.metrics_path)
    experiment_dir = metrics_path.parent
    paths = {
        "code": experiment_dir / "run.py",
        "data": experiment_dir / "data.json",
        "config": experiment_dir / "config.yaml",
        "metrics": metrics_path,
    }
    for kind, path in paths.items():
        if not path.is_file():
            failures.append(f"attempt {attempt.attempt_id} missing {kind} artifact")
    if paths["code"].is_file() and file_hash(paths["code"]) != attempt.code_hash:
        failures.append(f"attempt {attempt.attempt_id} code hash mismatch")
    if paths["data"].is_file() and file_hash(paths["data"]) != attempt.data_hash:
        failures.append(f"attempt {attempt.attempt_id} data hash mismatch")
    if paths["config"].is_file() and file_hash(paths["config"]) != attempt.config_hash:
        failures.append(f"attempt {attempt.attempt_id} config hash mismatch")
    if paths["metrics"].is_file():
        try:
            payload = json.loads(paths["metrics"].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append(f"attempt {attempt.attempt_id} metrics artifact is invalid JSON")
            return
        persisted_metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(persisted_metrics, dict):
            failures.append(f"attempt {attempt.attempt_id} metrics artifact has no metric map")
        elif data_hash(persisted_metrics) != attempt.metrics_hash:
            failures.append(f"attempt {attempt.attempt_id} metrics artifact hash mismatch")
        for field, expected in (
            ("topic_id", attempt.topic_id),
            ("hypothesis_id", attempt.hypothesis_id),
            ("protocol_id", attempt.protocol_id),
            ("plan_hash", attempt.plan_hash),
        ):
            if not isinstance(payload, dict) or payload.get(field) != expected:
                failures.append(
                    f"attempt {attempt.attempt_id} metrics {field} does not match causal chain"
                )


def _constant_metric_payload(metrics: dict[str, float]) -> bool:
    finite = [value for value in metrics.values() if math.isfinite(value)]
    if len(finite) < 2:
        return True
    first = finite[0]
    return all(math.isclose(value, first, rel_tol=0.0, abs_tol=1e-12) for value in finite[1:])


def _full_gate_a_passed(
    manifest: CycleManifest,
    protocol: ExperimentProtocol,
) -> bool:
    if protocol.development_fixture or len(manifest.attempts) < 3:
        return False
    return all(
        attempt.metrics.get("full_gate_a_passed") == 1.0
        and attempt.metrics.get("ode_system_count", 0.0) >= 10.0
        and attempt.metrics.get("pde_system_count", 0.0) >= 4.0
        for attempt in manifest.attempts
    )
