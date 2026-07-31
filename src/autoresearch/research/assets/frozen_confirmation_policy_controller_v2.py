"""Technical-only controller for the consumed Task 263.6 confirmation panel.

This controller preserves the frozen v1 claim, assignments, policies, budgets,
thresholds, labels, and memory rules.  Its only scientific execution change is
to call the certified v2 evaluator, which canonicalizes classification label
tokens and keeps sealed labels physically absent from F1/F2.  Every result is
permanently marked consumed-panel, technical, exploratory, and ineligible for
independent-confirmation or publication gates.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from . import frozen_confirmation_policy_controller_v1 as _legacy
except ImportError:  # pragma: no cover - exercised by clean subprocesses
    _legacy = importlib.import_module("frozen_confirmation_policy_controller_v1")

SCHEMA_VERSION = "frozen-confirmation-policy-controller-v2"
RESULT_SCHEMA_VERSION = "consumed-panel-technical-controller-result-v1"
ASSIGNMENT_RESULT_SCHEMA_VERSION = "consumed-panel-technical-assignment-result-v1"
EVALUATION_SCHEMA_VERSION = "consumed-panel-technical-candidate-evaluation-v1"
NULL_RESULT_SCHEMA_VERSION = "consumed-panel-technical-null-control-result-v1"
REPAIR_FREEZE_SCHEMA_VERSION = "consumed-panel-repair-freeze-v1"
V2_RUNNER_RESULT_SCHEMA_VERSION = "tabular-confirmation-candidate-result-v2"
LEGACY_CONTROLLER_SHA256 = (
    "b6bd15cd1062494ebbf9576f43cb9ea1a009052c57afbbd7f9d846b92f9fd542"
)

_ACTIVE_REPAIR_FREEZE: dict[str, Any] | None = None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _repair_freeze() -> dict[str, Any]:
    if _ACTIVE_REPAIR_FREEZE is None:
        raise RuntimeError("technical repair freeze is not active")
    return _ACTIVE_REPAIR_FREEZE


def _verify_repair_freeze(
    repair: dict[str, Any],
    design: dict[str, Any],
    index: dict[str, Any],
) -> None:
    if repair.get("schema_version") != REPAIR_FREEZE_SCHEMA_VERSION:
        raise ValueError("technical repair-freeze schema mismatch")
    _legacy._verify_object_hash(repair, "repair_freeze_hash")
    if (
        repair.get("source_confirmation_freeze_hash") != design["freeze_hash"]
        or repair.get("source_reveal_hash") != index["reveal_hash"]
        or repair.get("source_panel_consumed") is not True
        or repair.get("technical_only") is not True
        or repair.get("exploratory_only") is not True
        or repair.get("independent_confirmation_eligible") is not False
        or repair.get("publication_evidence_eligible") is not False
        or repair.get("post_reveal_retuning_allowed") is not False
        or repair.get("result_contingent_route_change_allowed") is not False
        or repair.get("public_release_authorized") is not False
        or repair.get("external_submission_authorized") is not False
    ):
        raise ValueError("technical repair-freeze boundary mismatch")
    expected_index_hash = repair["technical_execution_index_hashes"].get(
        index["interpreter_role"]
    )
    if expected_index_hash != index["execution_index_hash"]:
        raise ValueError("technical execution-index hash is not frozen")
    if repair.get("allowed_repair_fields") != [
        "classification-target-token-canonicalization",
        "f1-f2-physical-label-isolation",
        "structured-input-candidate-evaluator-failure-domains",
    ]:
        raise ValueError("technical evaluator repair scope changed")


def _evaluation_id(
    design: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed: int,
    stage: str,
) -> str:
    repair = _repair_freeze()
    digest = _legacy._canonical_sha256(
        {
            "source_confirmation_freeze_hash": design["freeze_hash"],
            "repair_freeze_hash": repair["repair_freeze_hash"],
            "v2_candidate_runner_sha256": repair["v2_candidate_runner_sha256"],
            "unit_id": task["unit_id"],
            "train_sha256": task["train_sha256"],
            "test_sha256": task["test_sha256"],
            "labels_sha256": task["labels_sha256"],
            "candidate_hash": candidate["candidate_hash"],
            "seed": seed,
            "stage": stage,
        }
    )
    return f"technical-repair-eval-{digest[:24]}"


def _runner_payload_valid(payload: dict[str, Any]) -> bool:
    try:
        _legacy._verify_object_hash(payload, "result_hash")
    except ValueError:
        return False
    return payload.get("schema_version") == V2_RUNNER_RESULT_SCHEMA_VERSION


def _scientific_runner_projection(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "failure_domain",
        "failure_code",
        "candidate_hash",
        "stage",
        "family",
        "metric_id",
        "score",
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
        "memory_valid",
        "network_allowed",
    )
    return {key: payload.get(key) for key in keys}


def _payload_bindings_valid(
    payload: dict[str, Any],
    *,
    design: dict[str, Any],
    index: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    evaluation_id: str,
    stage: str,
) -> bool:
    expected_labels_hash = task["labels_sha256"] if stage == "F3" else None
    identity_valid = bool(
        payload.get("execution_id") == evaluation_id
        and payload.get("opaque_unit_id") == task["opaque_unit_id"]
        and payload.get("candidate_id") == candidate["candidate_id"]
        and payload.get("candidate_hash") == candidate["candidate_hash"]
        and payload.get("stage") == stage
        and payload.get("family") == task["family"]
        and payload.get("confirmation_freeze_hash") == design["freeze_hash"]
        and payload.get("reveal_hash") == index["reveal_hash"]
        and payload.get("network_allowed") is False
    )
    if not identity_valid:
        return False
    if (
        payload.get("status") == "failed"
        and payload.get("failure_domain") == "input"
    ):
        labels_accessed = payload.get("labels_accessed")
        labels_hash = payload.get("labels_sha256")
        return bool(
            payload.get("train_sha256") in {None, task["train_sha256"]}
            and payload.get("test_sha256") in {None, task["test_sha256"]}
            and labels_hash in {None, expected_labels_hash}
            and (
                (stage != "F3" and labels_accessed is False and labels_hash is None)
                or (
                    stage == "F3"
                    and (
                        (labels_accessed is False and labels_hash is None)
                        or (
                            labels_accessed is True
                            and labels_hash == expected_labels_hash
                        )
                    )
                )
            )
        )
    return bool(
        payload.get("train_sha256") == task["train_sha256"]
        and payload.get("test_sha256") == task["test_sha256"]
        and payload.get("labels_sha256") == expected_labels_hash
        and payload.get("labels_accessed") is (stage == "F3")
    )


def _run_candidate(
    design: dict[str, Any],
    index: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed: int,
    stage: str,
    root: Path,
    output_dir: Path,
    python_path: Path,
    candidate_runner: Path,
) -> dict[str, Any]:
    repair = _repair_freeze()
    evaluation_id = _evaluation_id(
        design,
        task,
        candidate,
        seed=seed,
        stage=stage,
    )
    cache_dir = output_dir / "evaluation-cache" / evaluation_id
    record_path = cache_dir / "evaluation.json"
    if record_path.exists():
        cached = _legacy._load_json(record_path)
        _legacy._verify_object_hash(cached, "evaluation_hash")
        if (
            cached.get("schema_version") != EVALUATION_SCHEMA_VERSION
            or cached.get("repair_freeze_hash") != repair["repair_freeze_hash"]
        ):
            raise ValueError("cached technical evaluation binding mismatch")
        return cached

    fraction, maximum_seconds = _legacy._stage_budget(design, stage)
    cache_dir.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {
        "schema_version": "tabular-candidate-execution-v1",
        "execution_id": evaluation_id,
        "opaque_unit_id": task["opaque_unit_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "family": task["family"],
        "learner": candidate["learner"],
        "preprocessing": candidate["preprocessing"],
        "hyperparameters": candidate["hyperparameters"],
        "stage": stage,
        "training_fraction": fraction,
        "seed": seed,
        "validation_fraction": 0.20,
        "train_path": task["train_path"],
        "test_path": task["test_path"],
        "train_sha256": task["train_sha256"],
        "test_sha256": task["test_sha256"],
        "maximum_memory_mb": int(design["maximum_memory_mb"]),
        "allowed_root": root.as_posix(),
        "confirmation_freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
    }
    if stage == "F3":
        config["labels_path"] = task["labels_path"]
        config["labels_sha256"] = task["labels_sha256"]
    config_path = cache_dir / "execution-config.json"
    result_path = cache_dir / "runner-result.json"
    replay_path = cache_dir / "runner-replay.json"
    stdout_path = cache_dir / "runner.stdout.log"
    stderr_path = cache_dir / "runner.stderr.log"
    _legacy._write_json_atomic(config_path, config)
    command = [
        python_path.as_posix(),
        candidate_runner.as_posix(),
        "--config",
        config_path.resolve().as_posix(),
        "--output",
        result_path.resolve().as_posix(),
    ]

    stdout = ""
    stderr = ""
    return_code: int | None = None
    timed_out = False
    infrastructure_code: str | None = None
    infrastructure_summary: str | None = None
    runner_payload: dict[str, Any] | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=cache_dir,
            env=_legacy._sanitize_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=maximum_seconds,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        return_code = completed.returncode
        if not result_path.exists():
            infrastructure_code = "runner_artifact_missing"
            infrastructure_summary = "v2 evaluator produced no result artifact"
        else:
            loaded = _legacy._load_json(result_path)
            if not _runner_payload_valid(loaded):
                infrastructure_code = "runner_artifact_invalid"
                infrastructure_summary = "v2 evaluator result hash or schema failed"
            else:
                runner_payload = loaded
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        infrastructure_code = "runner_timeout"
        infrastructure_summary = f"v2 evaluator reached the {maximum_seconds}s cap"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        infrastructure_code = "runner_infrastructure_error"
        infrastructure_summary = f"{type(exc).__name__}: {exc}"
    _legacy._write_text_atomic(stdout_path, stdout)
    _legacy._write_text_atomic(stderr_path, stderr)

    bindings_valid = bool(
        runner_payload is not None
        and _payload_bindings_valid(
            runner_payload,
            design=design,
            index=index,
            task=task,
            candidate=candidate,
            evaluation_id=evaluation_id,
            stage=stage,
        )
        and _file_sha256(candidate_runner)
        == repair["v2_confirmation_runner_sha256"]
    )
    payload_status = runner_payload.get("status") if runner_payload is not None else None
    failure_domain = (
        str(runner_payload.get("failure_domain"))
        if runner_payload is not None and runner_payload.get("failure_domain") is not None
        else None
    )
    payload_failure_code = (
        str(runner_payload.get("failure_code"))
        if runner_payload is not None and runner_payload.get("failure_code") is not None
        else None
    )
    expected_return_code = (
        0
        if payload_status == "succeeded" or failure_domain == "candidate"
        else 2
        if failure_domain in {"input", "evaluator"}
        else None
    )
    process_contract_valid = bool(
        expected_return_code is not None and return_code == expected_return_code
    )
    structured_artifact_valid = bool(
        runner_payload is not None
        and bindings_valid
        and process_contract_valid
        and (
            (payload_status == "succeeded" and failure_domain is None)
            or (
                payload_status == "failed"
                and failure_domain in {"input", "candidate", "evaluator"}
                and payload_failure_code is not None
            )
        )
    )

    replay_exact: bool | None = None
    replay_sha256: str | None = None
    if (
        runner_payload is not None
        and payload_status == "succeeded"
        and structured_artifact_valid
        and stage == "F3"
    ):
        replay_command = [*command[:-1], replay_path.resolve().as_posix()]
        try:
            replay = subprocess.run(
                replay_command,
                cwd=cache_dir,
                env=_legacy._sanitize_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=maximum_seconds,
                check=False,
            )
            _legacy._write_text_atomic(
                cache_dir / "runner-replay.stdout.log",
                replay.stdout,
            )
            _legacy._write_text_atomic(
                cache_dir / "runner-replay.stderr.log",
                replay.stderr,
            )
            if replay.returncode == 0 and replay_path.exists():
                replay_payload = _legacy._load_json(replay_path)
                replay_exact = bool(
                    _runner_payload_valid(replay_payload)
                    and _scientific_runner_projection(replay_payload)
                    == _scientific_runner_projection(runner_payload)
                )
                replay_sha256 = _file_sha256(replay_path)
            else:
                replay_exact = False
        except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
            replay_exact = False

    memory_valid = bool(
        runner_payload is not None and runner_payload.get("memory_valid") is True
    )
    scientific_success = bool(
        runner_payload is not None
        and payload_status == "succeeded"
        and structured_artifact_valid
        and memory_valid
        and (stage != "F3" or replay_exact is True)
    )
    if infrastructure_code is not None:
        failure_domain = "infrastructure"
        failure_code = infrastructure_code
        failure_summary = infrastructure_summary
    elif not bindings_valid:
        failure_domain = "evaluator"
        failure_code = "evaluator_binding_failure"
        failure_summary = "v2 evaluator output failed frozen technical bindings"
    elif not process_contract_valid:
        failure_domain = "evaluator"
        failure_code = "evaluator_process_contract_failure"
        failure_summary = "v2 evaluator process status contradicted its result domain"
    elif payload_status == "failed":
        failure_code = f"{failure_domain}:{payload_failure_code}"
        failure_summary = "v2 evaluator returned a structured failure"
    elif not memory_valid:
        failure_domain = "candidate"
        failure_code = "candidate:memory_budget_exceeded"
        failure_summary = "candidate exceeded the frozen memory cap"
    elif stage == "F3" and replay_exact is not True:
        failure_domain = "evaluator"
        failure_code = "evaluator:prediction_replay_failure"
        failure_summary = "v2 F3 scientific projection replay was not exact"
    else:
        failure_code = None
        failure_summary = None

    evaluator_integrity_valid = bool(
        structured_artifact_valid
        and failure_domain not in {"input", "evaluator", "infrastructure"}
    )
    evaluation: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "repair_freeze_hash": repair["repair_freeze_hash"],
        "source_confirmation_freeze_hash": design["freeze_hash"],
        "consumed_panel": True,
        "technical_only": True,
        "exploratory_only": True,
        "independent_confirmation_eligible": False,
        "publication_evidence_eligible": False,
        "evaluation_id": evaluation_id,
        "unit_id": task["unit_id"],
        "opaque_unit_id": task["opaque_unit_id"],
        "within_unit_seed": seed,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "mechanism_family": candidate["mechanism_family"],
        "stage": stage,
        "status": "succeeded" if scientific_success else "failed",
        "failure_domain": None if scientific_success else failure_domain,
        "config_hash": _legacy._canonical_sha256(config),
        "command_hash": _legacy._canonical_sha256(command),
        "runner_source_hash": repair["v2_confirmation_runner_sha256"],
        "train_sha256": task["train_sha256"],
        "test_sha256": task["test_sha256"],
        "sealed_labels_sha256": task["labels_sha256"],
        "runner_labels_sha256": (
            runner_payload.get("labels_sha256") if runner_payload is not None else None
        ),
        "labels_accessed": (
            runner_payload.get("labels_accessed") if runner_payload is not None else None
        ),
        "metric_id": task["metric_id"],
        "score": (
            float(runner_payload["score"])
            if scientific_success and runner_payload is not None
            else None
        ),
        "prediction_sha256": (
            runner_payload.get("prediction_sha256") if scientific_success else None
        ),
        "prediction_count": (
            int(runner_payload["prediction_count"])
            if scientific_success and runner_payload is not None
            else None
        ),
        "fit_row_count": (
            int(runner_payload["fit_row_count"])
            if scientific_success and runner_payload is not None
            else None
        ),
        "evaluation_row_count": (
            int(runner_payload["evaluation_row_count"])
            if scientific_success and runner_payload is not None
            else None
        ),
        "cpu_seconds": (
            float(runner_payload.get("cpu_seconds", 0.0))
            if runner_payload is not None
            else 0.0
        ),
        "wall_seconds": (
            float(runner_payload.get("wall_seconds", 0.0))
            if runner_payload is not None
            else float(maximum_seconds if timed_out else 0.0)
        ),
        "peak_rss_mb": (
            float(runner_payload.get("peak_rss_mb", 0.0))
            if runner_payload is not None
            else 0.0
        ),
        "maximum_seconds": maximum_seconds,
        "maximum_memory_mb": int(design["maximum_memory_mb"]),
        "artifact_valid": structured_artifact_valid,
        "evaluator_integrity_valid": evaluator_integrity_valid,
        "memory_valid": memory_valid,
        "replay_required": stage == "F3" and payload_status == "succeeded",
        "replay_exact": replay_exact,
        "result_file_sha256": (
            _file_sha256(result_path) if result_path.exists() else None
        ),
        "replay_file_sha256": replay_sha256,
        "stdout_sha256": _file_sha256(stdout_path),
        "stderr_sha256": _file_sha256(stderr_path),
        "return_code": return_code,
        "timed_out": timed_out,
        "failure_code": None if scientific_success else failure_code,
        "failure_summary": None if scientific_success else failure_summary,
    }
    evaluation["evaluation_hash"] = _legacy._canonical_sha256(evaluation)
    _legacy._write_json_atomic(record_path, evaluation)
    return evaluation


def _mark_assignment(
    result: dict[str, Any],
    *,
    repair_freeze_hash: str,
) -> dict[str, Any]:
    result.pop("result_hash", None)
    result["source_schema_version"] = result["schema_version"]
    result["schema_version"] = ASSIGNMENT_RESULT_SCHEMA_VERSION
    result["repair_freeze_hash"] = repair_freeze_hash
    result["partition"] = "consumed_confirmatory_technical"
    result["consumed_panel"] = True
    result["technical_only"] = True
    result["exploratory_only"] = True
    result["independent_confirmation_eligible"] = False
    result["publication_evidence_eligible"] = False
    result["result_hash"] = _legacy._canonical_sha256(result)
    return result


def _mark_null_result(
    result: dict[str, Any],
    *,
    repair_freeze_hash: str,
) -> dict[str, Any]:
    result.pop("result_hash", None)
    result["source_schema_version"] = result["schema_version"]
    result["schema_version"] = NULL_RESULT_SCHEMA_VERSION
    result["repair_freeze_hash"] = repair_freeze_hash
    result["partition"] = "consumed_confirmatory_technical"
    result["consumed_panel"] = True
    result["technical_only"] = True
    result["exploratory_only"] = True
    result["independent_confirmation_eligible"] = False
    result["publication_evidence_eligible"] = False
    result["result_hash"] = _legacy._canonical_sha256(result)
    return result


def run(
    design_path: Path,
    index_path: Path,
    repair_freeze_path: Path,
    output_dir: Path,
    python_path: Path,
    allowed_root: Path,
    *,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    global _ACTIVE_REPAIR_FREEZE

    root = allowed_root.resolve()
    if not root.is_dir():
        raise ValueError("allowed technical-repair root does not exist")
    for path in (
        design_path.resolve(),
        index_path.resolve(),
        repair_freeze_path.resolve(),
        output_dir.resolve(),
    ):
        if not _within(path, root):
            raise ValueError("technical controller path escaped the allowed root")
    design = _legacy._load_json(design_path)
    index = _legacy._load_json(index_path)
    repair = _legacy._load_json(repair_freeze_path)
    _legacy._validate_design(design)
    tasks = _legacy._validate_index(index, design, root)
    _verify_repair_freeze(repair, design, index)
    _ACTIVE_REPAIR_FREEZE = repair

    legacy_path = Path(_legacy.__file__).resolve()
    if _file_sha256(legacy_path) != LEGACY_CONTROLLER_SHA256:
        raise ValueError("frozen v1 controller dependency hash mismatch")
    if (
        _file_sha256(Path(__file__).resolve())
        != repair["v2_policy_controller_sha256"]
    ):
        raise ValueError("technical v2 policy-controller source hash mismatch")
    if (
        _file_sha256(python_path.resolve())
        != design["clean_interpreter_hashes"][index["interpreter_role"]]
    ):
        raise ValueError("technical clean-interpreter hash mismatch")
    candidate_runner = _legacy._confined_path(
        str(root / repair["v2_confirmation_runner_relative_path"]),
        root,
    )
    if (
        _file_sha256(candidate_runner)
        != repair["v2_confirmation_runner_sha256"]
    ):
        raise ValueError("technical v2 candidate-runner source hash mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    controller_result_path = output_dir / "controller-result.json"
    if controller_result_path.exists():
        result = _legacy._load_json(controller_result_path)
        _legacy._verify_object_hash(result, "result_hash")
        if result.get("repair_freeze_hash") != repair["repair_freeze_hash"]:
            raise ValueError("resumed technical controller repair binding mismatch")
        return result

    _legacy._run_candidate = _run_candidate
    policies = {str(item["policy_id"]): item for item in design["policies"]}
    frozen_memory_by_policy = {
        str(item["policy_id"]): item["state"]
        for item in design["frozen_policy_memories"]
    }
    memory_by_policy_unit = {
        (policy_id, unit_id): json.loads(json.dumps(frozen_memory_by_policy[policy_id]))
        for policy_id in policies
        for unit_id in design["confirmatory_unit_ids"]
    }
    seen_evaluations: set[str] = set()
    assignment_hashes: dict[str, str] = {}
    assignment_projections: list[dict[str, Any]] = []
    total = len(design["assignments"])
    for position, assignment in enumerate(design["assignments"], start=1):
        result_path = (
            output_dir
            / "assignments"
            / str(assignment["assignment_id"])
            / "result.json"
        )
        memory = memory_by_policy_unit[
            (str(assignment["policy_id"]), str(assignment["unit_id"]))
        ]
        if result_path.exists():
            result = _legacy._load_json(result_path)
            _legacy._verify_object_hash(result, "result_hash")
            if (
                result.get("schema_version") != ASSIGNMENT_RESULT_SCHEMA_VERSION
                or result.get("repair_freeze_hash") != repair["repair_freeze_hash"]
                or result["assignment_hash"] != assignment["assignment_hash"]
                or result["memory_before_hash"] != _legacy._memory_hash(memory)
            ):
                raise ValueError("resumed technical assignment binding mismatch")
            _legacy._update_memory(
                memory,
                result,
                enabled=bool(
                    policies[str(assignment["policy_id"])][
                        "comparative_memory_enabled"
                    ]
                ),
            )
            if result["memory_after_hash"] != _legacy._memory_hash(memory):
                raise ValueError("resumed technical assignment memory mismatch")
            action = "resumed"
        else:
            result = _legacy._execute_assignment(
                design,
                index,
                assignment,
                tasks[str(assignment["unit_id"])],
                policies[str(assignment["policy_id"])],
                memory,
                root=root,
                output_dir=output_dir,
                python_path=python_path.resolve(),
                candidate_runner=candidate_runner,
                seen_evaluations=seen_evaluations,
            )
            result = _mark_assignment(
                result,
                repair_freeze_hash=repair["repair_freeze_hash"],
            )
            _legacy._write_json_atomic(result_path, result)
            action = "executed"
        for record in result["stage_records"]:
            if record["evaluation_hash"] is not None:
                seen_evaluations.add(str(record["evaluation_hash"]))
        assignment_hashes[str(assignment["assignment_id"])] = result["result_hash"]
        assignment_projections.append(_legacy._assignment_projection(result))
        if progress_path is not None:
            _legacy._write_text_atomic(
                progress_path,
                (
                    f"{position}/{total} {action} {assignment['assignment_id']} "
                    f"technical_success={result['objective_task_success']}\n"
                ),
            )

    null_candidate = next(
        item
        for item in design["candidates"]
        if item["candidate_id"] == design["null_control_candidate_id"]
    )
    null_hashes: dict[str, str] = {}
    null_projections: list[dict[str, Any]] = []
    for unit_id in design["confirmatory_unit_ids"]:
        for seed in design["within_unit_seeds"]:
            control_id = f"null-{unit_id}-{seed}"
            path = output_dir / "null-controls" / control_id / "result.json"
            if path.exists():
                result = _legacy._load_json(path)
                _legacy._verify_object_hash(result, "result_hash")
                if (
                    result.get("schema_version") != NULL_RESULT_SCHEMA_VERSION
                    or result.get("repair_freeze_hash")
                    != repair["repair_freeze_hash"]
                ):
                    raise ValueError("resumed technical null-control binding mismatch")
            else:
                result = _legacy._run_null_control(
                    design,
                    index,
                    tasks[unit_id],
                    null_candidate,
                    seed=int(seed),
                    root=root,
                    output_dir=output_dir,
                    python_path=python_path.resolve(),
                    candidate_runner=candidate_runner,
                )
                result = _mark_null_result(
                    result,
                    repair_freeze_hash=repair["repair_freeze_hash"],
                )
                _legacy._write_json_atomic(path, result)
            null_hashes[control_id] = result["result_hash"]
            null_projections.append(
                {
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
            )
    projection = {
        "source_confirmation_freeze_hash": design["freeze_hash"],
        "repair_freeze_hash": repair["repair_freeze_hash"],
        "source_reveal_hash": index["reveal_hash"],
        "consumed_panel": True,
        "technical_only": True,
        "assignments": assignment_projections,
        "null_controls": null_projections,
    }
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "controller_schema_version": SCHEMA_VERSION,
        "source_confirmation_freeze_hash": design["freeze_hash"],
        "source_reveal_hash": index["reveal_hash"],
        "repair_freeze_hash": repair["repair_freeze_hash"],
        "execution_index_hash": index["execution_index_hash"],
        "interpreter_role": index["interpreter_role"],
        "assignment_result_hashes": dict(sorted(assignment_hashes.items())),
        "null_control_result_hashes": dict(sorted(null_hashes.items())),
        "assignment_count": len(assignment_hashes),
        "null_control_count": len(null_hashes),
        "scientific_projection_hash": _legacy._canonical_sha256(projection),
        "frozen_policy_memory_catalogue_hash": _legacy._canonical_sha256(
            [item["memory_hash"] for item in design["frozen_policy_memories"]]
        ),
        "memory_cloned_per_confirmatory_unit": True,
        "cross_confirmatory_unit_memory_updates_allowed": False,
        "within_unit_seed_memory_updates_allowed": True,
        "full_matrix_complete": True,
        "source_panel_consumed": True,
        "technical_only": True,
        "exploratory_only": True,
        "independent_confirmation_eligible": False,
        "publication_evidence_eligible": False,
        "network_accessed": False,
        "development_trajectory_accessed": False,
        "frozen_development_policy_parameters_used": True,
        "raw_development_outcomes_accessed": False,
        "post_reveal_retuning_authorized": False,
        "result_contingent_route_change_authorized": False,
        "external_submission_authorized": False,
        "public_release_authorized": False,
    }
    result["result_hash"] = _legacy._canonical_sha256(result)
    _legacy._write_json_atomic(controller_result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--input-index", required=True, type=Path)
    parser.add_argument("--repair-freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--allowed-root", required=True, type=Path)
    parser.add_argument("--progress", type=Path)
    args = parser.parse_args()
    result = run(
        args.design.resolve(),
        args.input_index.resolve(),
        args.repair_freeze.resolve(),
        args.output.resolve(),
        args.python.resolve(),
        args.allowed_root.resolve(),
        progress_path=args.progress.resolve() if args.progress else None,
    )
    print(
        json.dumps(
            {
                "assignment_count": result["assignment_count"],
                "null_control_count": result["null_control_count"],
                "scientific_projection_hash": result[
                    "scientific_projection_hash"
                ],
                "technical_only": result["technical_only"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
