"""Standalone, network-free policy controller for Task 263.6 confirmation.

The controller is intentionally standard-library only.  It receives a
content-addressed design, a post-reveal input index, and one allowed workspace.
It cannot fetch data, import AutoResearch, inspect a repository or development
run, or write outside that workspace.  Policy allocation mirrors the frozen
Task 263.5 controller while every scientific execution is delegated to the
hash-pinned confirmation candidate runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "frozen-confirmation-policy-controller-v1"
DESIGN_SCHEMA_VERSION = "confirmatory-evaluation-freeze-v1"
INDEX_SCHEMA_VERSION = "confirmatory-execution-index-v1"
RESULT_SCHEMA_VERSION = "confirmatory-controller-result-v1"
ASSIGNMENT_RESULT_SCHEMA_VERSION = "confirmatory-assignment-result-v1"
EVALUATION_SCHEMA_VERSION = "confirmatory-candidate-evaluation-v1"
NULL_RESULT_SCHEMA_VERSION = "confirmatory-null-control-result-v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _verify_object_hash(payload: dict[str, Any], field: str) -> None:
    expected = payload.get(field)
    if not isinstance(expected, str):
        raise ValueError(f"{field} is missing")
    body = dict(payload)
    body.pop(field, None)
    if expected != _canonical_sha256(body):
        raise ValueError(f"{field} mismatch")


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _confined_path(value: str, root: Path, *, must_exist: bool = True) -> Path:
    path = Path(value).resolve()
    if not _within(path, root):
        raise ValueError("path escaped the assigned confirmation workspace")
    if must_exist and not path.exists():
        raise ValueError(f"required confirmation path is missing: {path.name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return loaded


def _sanitize_environment() -> dict[str, str]:
    blocked_terms = (
        "API_KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "CREDENTIAL",
        "PROXY",
    )
    blocked_runtime_keys = {
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(term in key.upper() for term in blocked_terms)
        and key.upper() not in blocked_runtime_keys
    }
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _validate_design(design: dict[str, Any]) -> None:
    if design.get("schema_version") != DESIGN_SCHEMA_VERSION:
        raise ValueError("unsupported confirmation design schema")
    _verify_object_hash(design, "freeze_hash")
    candidates = design.get("candidates")
    policies = design.get("policies")
    frozen_memories = design.get("frozen_policy_memories")
    assignments = design.get("assignments")
    units = design.get("confirmatory_unit_ids")
    if not isinstance(candidates, list) or len(candidates) != 12:
        raise ValueError("confirmation design requires 12 candidates")
    if not isinstance(policies, list) or len(policies) != 9:
        raise ValueError("confirmation design requires nine policies")
    if not isinstance(frozen_memories, list) or len(frozen_memories) != 9:
        raise ValueError("confirmation design requires nine frozen policy memories")
    if not isinstance(assignments, list) or len(assignments) != 1620:
        raise ValueError("confirmation design requires 1,620 assignments")
    if not isinstance(units, list) or len(units) != 60 or units != sorted(units):
        raise ValueError("confirmation design requires 60 sorted units")
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    policy_ids = [str(item["policy_id"]) for item in policies]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("confirmation candidate IDs are duplicated")
    if policy_ids != sorted(policy_ids) or len(policy_ids) != len(set(policy_ids)):
        raise ValueError("confirmation policy IDs must be unique and sorted")
    if [str(item["policy_id"]) for item in frozen_memories] != policy_ids:
        raise ValueError("confirmation frozen memories do not cover all policies")
    if [int(item["sequence_index"]) for item in assignments] != list(range(1620)):
        raise ValueError("confirmation assignment sequence is not contiguous")
    if len({str(item["assignment_id"]) for item in assignments}) != 1620:
        raise ValueError("confirmation assignment IDs are duplicated")
    for item in candidates:
        _verify_object_hash(item, "candidate_hash")
    for item in policies:
        _verify_object_hash(item, "policy_hash")
    for item in frozen_memories:
        _verify_object_hash(item, "memory_hash")
        if _canonical_sha256(item["state"]) != item["state_hash"]:
            raise ValueError("confirmation frozen-memory state hash mismatch")
    _verify_object_hash(design["claim"], "claim_hash")
    _verify_object_hash(design["statistical_policy"], "policy_hash")
    memory_catalogue_hash = _canonical_sha256([item["memory_hash"] for item in frozen_memories])
    if design["claim"].get("frozen_policy_memory_catalogue_hash") != memory_catalogue_hash:
        raise ValueError("confirmation claim/frozen-memory catalogue mismatch")
    for item in assignments:
        _verify_object_hash(item, "assignment_hash")
        if item.get("partition") != "confirmatory":
            raise ValueError("confirmation assignment partition changed")
        if item.get("unit_id") not in units or item.get("policy_id") not in policy_ids:
            raise ValueError("confirmation assignment references an unknown key")
    if design.get("surviving_policy_id") != "portfolio_memory":
        raise ValueError("confirmation survivor changed")
    if design.get("primary_comparator_policy_id") != "linear_self_loop":
        raise ValueError("confirmation primary comparator changed")
    if design.get("null_control_candidate_id") != "null-prior":
        raise ValueError("confirmation null control changed")
    if design.get("within_unit_seeds") != [1729, 3253, 7919]:
        raise ValueError("confirmation within-unit seeds changed")
    if (
        design.get("memory_cloned_per_confirmatory_unit") is not True
        or design.get("cross_confirmatory_unit_memory_updates_allowed") is not False
        or design.get("within_unit_seed_memory_updates_allowed") is not True
        or design.get("frozen_development_policy_parameters_exposed_to_runner") is not True
        or design.get("raw_development_outcomes_exposed_to_runner") is not False
    ):
        raise ValueError("confirmation task-independence memory rule changed")
    expected_matrix = {
        (str(item["unit_id"]), int(item["within_unit_seed"]), str(item["policy_id"]))
        for item in assignments
    }
    full_matrix = {
        (unit, seed, policy)
        for unit in units
        for seed in design["within_unit_seeds"]
        for policy in policy_ids
    }
    if expected_matrix != full_matrix:
        raise ValueError("confirmation assignment matrix is incomplete")


def _validate_index(
    index: dict[str, Any],
    design: dict[str, Any],
    root: Path,
) -> dict[str, dict[str, Any]]:
    if index.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise ValueError("unsupported confirmation execution-index schema")
    _verify_object_hash(index, "execution_index_hash")
    if index.get("freeze_hash") != design["freeze_hash"]:
        raise ValueError("execution index binds a different confirmation freeze")
    tasks = index.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 60:
        raise ValueError("execution index must contain 60 task bundles")
    if [str(item["unit_id"]) for item in tasks] != design["confirmatory_unit_ids"]:
        raise ValueError("execution index task order changed")
    task_by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        _verify_object_hash(task, "task_input_hash")
        unit_id = str(task["unit_id"])
        for field, hash_field in (
            ("train_path", "train_sha256"),
            ("test_path", "test_sha256"),
            ("labels_path", "labels_sha256"),
        ):
            path = _confined_path(str(task[field]), root)
            if _file_sha256(path) != task[hash_field]:
                raise ValueError(f"{unit_id} {field} hash mismatch")
        if task.get("baseline_replay_exact") is not True:
            raise ValueError(f"{unit_id} lacks exact baseline replay")
        if task.get("reveal_hash") != index.get("reveal_hash"):
            raise ValueError(f"{unit_id} reveal binding mismatch")
        task_by_id[unit_id] = task
    return task_by_id


def _static_priority(candidate: dict[str, Any], candidates: list[dict[str, Any]]) -> float:
    if bool(candidate["intentional_failure_control"]):
        return 2.0
    index = next(
        offset
        for offset, item in enumerate(candidates)
        if item["candidate_id"] == candidate["candidate_id"]
    )
    return 1.0 - index / 100.0


def _lineage_parent(
    policy: dict[str, Any],
    candidate_id: str,
    candidates: list[dict[str, Any]],
) -> str | None:
    if policy["topology"] != "linear_chain":
        return None
    ids = [str(item["candidate_id"]) for item in candidates]
    index = ids.index(candidate_id)
    return ids[index - 1] if index > 0 else None


def _select_f0(
    policy: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    eligible = [
        item
        for item in candidates
        if not (bool(policy["reviewer_enabled"]) and bool(item["intentional_failure_control"]))
    ]
    ranked = sorted(
        eligible,
        key=lambda item: (-_static_priority(item, candidates), item["candidate_id"]),
    )
    if policy["topology"] != "branching_portfolio" or not bool(policy["diversity_enabled"]):
        return [str(item["candidate_id"]) for item in ranked[:limit]]
    selected: list[dict[str, Any]] = []
    families: set[str] = set()
    for item in ranked:
        family = str(item["mechanism_family"])
        if family in families:
            continue
        selected.append(item)
        families.add(family)
        if len(selected) == limit:
            break
    for item in ranked:
        if len(selected) == limit:
            break
        if item not in selected:
            selected.append(item)
    return [str(item["candidate_id"]) for item in selected]


MemoryState = dict[str, dict[str, list[float]]]


def _empty_memory() -> MemoryState:
    return {"F1": {}, "F2": {}}


def _memory_hash(state: MemoryState) -> str:
    normalized = {
        stage: {family: list(values) for family, values in sorted(families.items())}
        for stage, families in sorted(state.items())
    }
    return _canonical_sha256(normalized)


def _memory_correction(
    state: MemoryState,
    *,
    stage: str,
    mechanism_family: str,
) -> float:
    family_values = state.get(stage, {}).get(mechanism_family, [])
    all_values = [value for values in state.get(stage, {}).values() for value in values]
    values = family_values or all_values
    if not values:
        return 0.0
    return max(-0.25, min(0.25, float(statistics.median(values))))


def _rank_successful(
    candidates: list[dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
    *,
    stage: str,
    policy: dict[str, Any],
    memory: MemoryState,
) -> tuple[list[str], dict[str, float], dict[str, float]]:
    scored: list[tuple[str, float]] = []
    corrections: dict[str, float] = {}
    scores: dict[str, float] = {}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        outcome = outcomes.get(candidate_id)
        if outcome is None or outcome["status"] != "succeeded":
            continue
        correction = (
            _memory_correction(
                memory,
                stage=stage,
                mechanism_family=str(candidate["mechanism_family"]),
            )
            if bool(policy["comparative_memory_enabled"]) and bool(policy["certificate_enabled"])
            else 0.0
        )
        score = (
            float(outcome["score"]) + correction
            if bool(policy["certificate_enabled"])
            else _static_priority(candidate, candidates)
        )
        corrections[candidate_id] = correction
        scores[candidate_id] = score
        scored.append((candidate_id, score))
    initial = {str(item["candidate_id"]): index for index, item in enumerate(candidates)}
    scored.sort(key=lambda row: (-row[1], initial[row[0]], row[0]))
    return [row[0] for row in scored], scores, corrections


def _linear_survivors(
    evaluated: list[str],
    scores: dict[str, float],
    *,
    limit: int,
) -> list[str]:
    incumbent: str | None = None
    history: list[str] = []
    for candidate_id in evaluated:
        if candidate_id not in scores:
            continue
        if incumbent is None or scores[candidate_id] > scores[incumbent]:
            incumbent = candidate_id
            if candidate_id not in history:
                history.append(candidate_id)
    survivors: list[str] = []
    if incumbent is not None:
        survivors.append(incumbent)
    for candidate_id in reversed(history):
        if candidate_id not in survivors:
            survivors.append(candidate_id)
        if len(survivors) == limit:
            return survivors
    remaining = sorted(
        (item for item in scores if item not in survivors),
        key=lambda item: (-scores[item], evaluated.index(item), item),
    )
    return [*survivors, *remaining][:limit]


def _portfolio_survivors(
    ranked: list[str],
    candidates_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
    exploration: bool,
) -> list[str]:
    if not exploration or limit <= 1 or len(ranked) <= limit:
        return ranked[:limit]
    exploit = ranked[: limit - 1]
    families = {str(candidates_by_id[candidate_id]["mechanism_family"]) for candidate_id in exploit}
    exploration_id = next(
        (
            candidate_id
            for candidate_id in ranked[limit - 1 :]
            if str(candidates_by_id[candidate_id]["mechanism_family"]) not in families
        ),
        ranked[limit - 1],
    )
    return [*exploit, exploration_id]


def _promote(
    policy: dict[str, Any],
    evaluated: list[str],
    ranked: list[str],
    scores: dict[str, float],
    candidates_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
    exploration_stage: bool,
) -> list[str]:
    if policy["topology"] == "linear_chain":
        return _linear_survivors(evaluated, scores, limit=limit)
    if policy["topology"] == "branching_portfolio":
        return _portfolio_survivors(
            ranked,
            candidates_by_id,
            limit=limit,
            exploration=bool(policy["diversity_enabled"]) and exploration_stage,
        )
    return ranked[:limit]


def _stage_budget(design: dict[str, Any], stage: str) -> tuple[float, int]:
    row = design["fidelity_budget"][stage]
    return float(row["training_fraction"]), int(row["maximum_seconds"])


def _evaluation_id(
    design: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed: int,
    stage: str,
) -> str:
    digest = _canonical_sha256(
        {
            "freeze_hash": design["freeze_hash"],
            "unit_id": task["unit_id"],
            "train_sha256": task["train_sha256"],
            "test_sha256": task["test_sha256"],
            "labels_sha256": task["labels_sha256"],
            "candidate_hash": candidate["candidate_hash"],
            "seed": seed,
            "stage": stage,
        }
    )
    return f"confirm-eval-{digest[:24]}"


def _runner_result_valid(payload: dict[str, Any]) -> bool:
    try:
        _verify_object_hash(payload, "result_hash")
    except ValueError:
        return False
    return True


def _scientific_runner_projection(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
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
        "confirmation_freeze_hash",
        "reveal_hash",
        "seed",
        "training_fraction",
        "memory_valid",
        "network_allowed",
    )
    return {key: payload.get(key) for key in keys}


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
        cached_evaluation = _load_json(record_path)
        _verify_object_hash(cached_evaluation, "evaluation_hash")
        return cached_evaluation

    fraction, maximum_seconds = _stage_budget(design, stage)
    cache_dir.mkdir(parents=True, exist_ok=True)
    config = {
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
        "labels_path": task["labels_path"],
        "train_sha256": task["train_sha256"],
        "test_sha256": task["test_sha256"],
        "labels_sha256": task["labels_sha256"],
        "maximum_memory_mb": int(design["maximum_memory_mb"]),
        "allowed_root": root.as_posix(),
        "confirmation_freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
    }
    config_path = cache_dir / "execution-config.json"
    result_path = cache_dir / "runner-result.json"
    replay_path = cache_dir / "runner-replay.json"
    stdout_path = cache_dir / "runner.stdout.log"
    stderr_path = cache_dir / "runner.stderr.log"
    _write_json_atomic(config_path, config)
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
    failure_code: str | None = None
    failure_summary: str | None = None
    runner_payload: dict[str, Any] | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=cache_dir,
            env=_sanitize_environment(),
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
        if completed.returncode != 0:
            failure_code = "runner_nonzero_exit"
            failure_summary = f"confirmation runner exited with {completed.returncode}"
        elif not result_path.exists():
            failure_code = "runner_artifact_missing"
            failure_summary = "confirmation runner produced no result artifact"
        else:
            loaded = _load_json(result_path)
            if not _runner_result_valid(loaded):
                failure_code = "runner_artifact_invalid"
                failure_summary = "confirmation result content hash failed"
            else:
                runner_payload = loaded
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        failure_code = "runner_timeout"
        failure_summary = f"confirmation runner reached the {maximum_seconds}s cap"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failure_code = "runner_infrastructure_error"
        failure_summary = f"{type(exc).__name__}: {exc}"
    _write_text_atomic(stdout_path, stdout)
    _write_text_atomic(stderr_path, stderr)

    replay_exact: bool | None = None
    replay_sha256: str | None = None
    if runner_payload is not None and stage == "F3":
        replay_command = [*command[:-1], replay_path.resolve().as_posix()]
        try:
            replay = subprocess.run(
                replay_command,
                cwd=cache_dir,
                env=_sanitize_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=maximum_seconds,
                check=False,
            )
            _write_text_atomic(cache_dir / "runner-replay.stdout.log", replay.stdout)
            _write_text_atomic(cache_dir / "runner-replay.stderr.log", replay.stderr)
            if replay.returncode == 0 and replay_path.exists():
                replay_payload = _load_json(replay_path)
                replay_exact = bool(
                    _runner_result_valid(replay_payload)
                    and _scientific_runner_projection(replay_payload)
                    == _scientific_runner_projection(runner_payload)
                )
                replay_sha256 = _file_sha256(replay_path)
            else:
                replay_exact = False
        except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
            replay_exact = False

    integrity = bool(
        runner_payload is not None
        and runner_payload.get("candidate_hash") == candidate["candidate_hash"]
        and runner_payload.get("train_sha256") == task["train_sha256"]
        and runner_payload.get("test_sha256") == task["test_sha256"]
        and runner_payload.get("labels_sha256") == task["labels_sha256"]
        and runner_payload.get("confirmation_freeze_hash") == design["freeze_hash"]
        and runner_payload.get("reveal_hash") == index["reveal_hash"]
        and runner_payload.get("network_allowed") is False
        and _file_sha256(candidate_runner) == design["execution_assets"]["candidate_runner_sha256"]
    )
    memory_valid = bool(runner_payload is not None and runner_payload.get("memory_valid") is True)
    if runner_payload is not None and not integrity:
        failure_code = "evaluator_integrity_failure"
        failure_summary = "confirmation output failed frozen bindings"
        runner_payload = None
    elif runner_payload is not None and not memory_valid:
        failure_code = "memory_budget_exceeded"
        failure_summary = "confirmation runner exceeded the memory cap"
        runner_payload = None
    elif stage == "F3" and runner_payload is not None and replay_exact is not True:
        failure_code = "prediction_replay_failure"
        failure_summary = "confirmation F3 prediction replay was not exact"
        runner_payload = None

    evaluation: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "unit_id": task["unit_id"],
        "opaque_unit_id": task["opaque_unit_id"],
        "within_unit_seed": seed,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "mechanism_family": candidate["mechanism_family"],
        "stage": stage,
        "status": "succeeded" if runner_payload is not None else "failed",
        "config_hash": _canonical_sha256(config),
        "command_hash": _canonical_sha256(command),
        "runner_source_hash": design["execution_assets"]["candidate_runner_sha256"],
        "train_sha256": task["train_sha256"],
        "test_sha256": task["test_sha256"],
        "labels_sha256": task["labels_sha256"],
        "metric_id": task["metric_id"],
        "score": float(runner_payload["score"]) if runner_payload is not None else None,
        "prediction_sha256": (
            runner_payload["prediction_sha256"] if runner_payload is not None else None
        ),
        "prediction_count": (
            int(runner_payload["prediction_count"]) if runner_payload is not None else None
        ),
        "fit_row_count": (
            int(runner_payload["fit_row_count"]) if runner_payload is not None else None
        ),
        "evaluation_row_count": (
            int(runner_payload["evaluation_row_count"]) if runner_payload is not None else None
        ),
        "cpu_seconds": (
            float(runner_payload["cpu_seconds"]) if runner_payload is not None else 0.0
        ),
        "wall_seconds": (
            float(runner_payload["wall_seconds"])
            if runner_payload is not None
            else float(maximum_seconds if timed_out else 0.0)
        ),
        "peak_rss_mb": (
            float(runner_payload["peak_rss_mb"]) if runner_payload is not None else 0.0
        ),
        "maximum_seconds": maximum_seconds,
        "maximum_memory_mb": int(design["maximum_memory_mb"]),
        "artifact_valid": runner_payload is not None,
        "evaluator_integrity_valid": integrity,
        "memory_valid": memory_valid,
        "replay_required": stage == "F3",
        "replay_exact": replay_exact,
        "result_file_sha256": (_file_sha256(result_path) if result_path.exists() else None),
        "replay_file_sha256": replay_sha256,
        "stdout_sha256": _file_sha256(stdout_path),
        "stderr_sha256": _file_sha256(stderr_path),
        "return_code": return_code,
        "timed_out": timed_out,
        "failure_code": failure_code if runner_payload is None else None,
        "failure_summary": failure_summary if runner_payload is None else None,
    }
    evaluation["evaluation_hash"] = _canonical_sha256(evaluation)
    _write_json_atomic(record_path, evaluation)
    return evaluation


def _nonallocated(
    candidate: dict[str, Any],
    policy: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    stage: str,
    component_disabled: bool = False,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "mechanism_family": candidate["mechanism_family"],
        "stage": stage,
        "status": "component_disabled" if component_disabled else "not_allocated",
        "lineage_parent_id": _lineage_parent(
            policy,
            str(candidate["candidate_id"]),
            candidates,
        ),
        "reviewer_gate_passed": None,
        "objective_score": None,
        "selection_score": None,
        "memory_correction": 0.0,
        "promoted": False,
        "evaluation_hash": None,
        "cache_reused": None,
        "failure_code": None,
    }


def _executed_record(
    candidate: dict[str, Any],
    policy: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    stage: str,
    evaluation: dict[str, Any],
    selection_score: float | None,
    memory_correction: float,
    promoted: bool,
    cache_reused: bool,
) -> dict[str, Any]:
    success = evaluation["status"] == "succeeded"
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "mechanism_family": candidate["mechanism_family"],
        "stage": stage,
        "status": "executed" if success else "failed",
        "lineage_parent_id": _lineage_parent(
            policy,
            str(candidate["candidate_id"]),
            candidates,
        ),
        "reviewer_gate_passed": None,
        "objective_score": float(evaluation["score"]) if success else None,
        "selection_score": selection_score if success else None,
        "memory_correction": memory_correction if success else 0.0,
        "promoted": promoted if success else False,
        "evaluation_hash": evaluation["evaluation_hash"],
        "cache_reused": cache_reused,
        "failure_code": None if success else evaluation["failure_code"],
    }


def _update_memory(memory: MemoryState, result: dict[str, Any], *, enabled: bool) -> None:
    if (
        not enabled
        or result.get("selected_candidate_id") is None
        or result.get("policy_score") is None
    ):
        return
    for stage in ("F1", "F2"):
        rows = [
            record
            for record in result["stage_records"]
            if record["stage"] == stage
            and record["candidate_id"] == result["selected_candidate_id"]
            and record["status"] == "executed"
        ]
        if len(rows) != 1:
            continue
        delta = float(result["policy_score"]) - float(rows[0]["objective_score"])
        family = str(result["selected_candidate_family"])
        memory.setdefault(stage, {}).setdefault(family, []).append(delta)


def _execute_assignment(
    design: dict[str, Any],
    index: dict[str, Any],
    assignment: dict[str, Any],
    task: dict[str, Any],
    policy: dict[str, Any],
    memory: MemoryState,
    *,
    root: Path,
    output_dir: Path,
    python_path: Path,
    candidate_runner: Path,
    seen_evaluations: set[str],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = design["candidates"]
    by_id = {str(item["candidate_id"]): item for item in candidates}
    before = _memory_hash(memory)
    all_evaluations: list[dict[str, Any]] = []
    stage_records: dict[str, list[dict[str, Any]]] = {}

    f0_limit = 6 if bool(policy["multi_fidelity_enabled"]) else 1
    f0_selected = _select_f0(policy, candidates, limit=f0_limit)
    stage_records["F0"] = []
    for candidate in candidates:
        rejected = bool(policy["reviewer_enabled"]) and bool(
            candidate["intentional_failure_control"]
        )
        row = {
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
            "mechanism_family": candidate["mechanism_family"],
            "stage": "F0",
            "status": "static_reject" if rejected else "static_pass",
            "lineage_parent_id": _lineage_parent(
                policy,
                str(candidate["candidate_id"]),
                candidates,
            ),
            "reviewer_gate_passed": not rejected,
            "objective_score": None,
            "selection_score": _static_priority(candidate, candidates),
            "memory_correction": 0.0,
            "promoted": candidate["candidate_id"] in f0_selected,
            "evaluation_hash": None,
            "cache_reused": None,
            "failure_code": "reviewer_schema_reject" if rejected else None,
        }
        stage_records["F0"].append(row)

    f1: dict[str, tuple[dict[str, Any], bool]] = {}
    f2: dict[str, tuple[dict[str, Any], bool]] = {}
    f3: dict[str, tuple[dict[str, Any], bool]] = {}
    f2_selected: list[str] = []
    if bool(policy["multi_fidelity_enabled"]):
        for candidate_id in f0_selected:
            evaluation = _run_candidate(
                design,
                index,
                task,
                by_id[candidate_id],
                seed=int(assignment["within_unit_seed"]),
                stage="F1",
                root=root,
                output_dir=output_dir,
                python_path=python_path,
                candidate_runner=candidate_runner,
            )
            reused = evaluation["evaluation_hash"] in seen_evaluations
            seen_evaluations.add(evaluation["evaluation_hash"])
            f1[candidate_id] = (evaluation, reused)
            all_evaluations.append(evaluation)
        f1_outcomes = {key: value[0] for key, value in f1.items()}
        ranked_f1, scores_f1, corrections_f1 = _rank_successful(
            candidates,
            f1_outcomes,
            stage="F1",
            policy=policy,
            memory=memory,
        )
        f1_selected = _promote(
            policy,
            f0_selected,
            ranked_f1,
            scores_f1,
            by_id,
            limit=3,
            exploration_stage=True,
        )
        stage_records["F1"] = [
            (
                _executed_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F1",
                    evaluation=f1[str(candidate["candidate_id"])][0],
                    selection_score=scores_f1.get(str(candidate["candidate_id"])),
                    memory_correction=corrections_f1.get(
                        str(candidate["candidate_id"]),
                        0.0,
                    ),
                    promoted=str(candidate["candidate_id"]) in f1_selected,
                    cache_reused=f1[str(candidate["candidate_id"])][1],
                )
                if str(candidate["candidate_id"]) in f1
                else _nonallocated(candidate, policy, candidates, stage="F1")
            )
            for candidate in candidates
        ]
        for candidate_id in f1_selected:
            evaluation = _run_candidate(
                design,
                index,
                task,
                by_id[candidate_id],
                seed=int(assignment["within_unit_seed"]),
                stage="F2",
                root=root,
                output_dir=output_dir,
                python_path=python_path,
                candidate_runner=candidate_runner,
            )
            reused = evaluation["evaluation_hash"] in seen_evaluations
            seen_evaluations.add(evaluation["evaluation_hash"])
            f2[candidate_id] = (evaluation, reused)
            all_evaluations.append(evaluation)
        f2_outcomes = {key: value[0] for key, value in f2.items()}
        ranked_f2, scores_f2, corrections_f2 = _rank_successful(
            candidates,
            f2_outcomes,
            stage="F2",
            policy=policy,
            memory=memory,
        )
        f2_selected = _promote(
            policy,
            f1_selected,
            ranked_f2,
            scores_f2,
            by_id,
            limit=1,
            exploration_stage=False,
        )
        stage_records["F2"] = [
            (
                _executed_record(
                    candidate,
                    policy,
                    candidates,
                    stage="F2",
                    evaluation=f2[str(candidate["candidate_id"])][0],
                    selection_score=scores_f2.get(str(candidate["candidate_id"])),
                    memory_correction=corrections_f2.get(
                        str(candidate["candidate_id"]),
                        0.0,
                    ),
                    promoted=str(candidate["candidate_id"]) in f2_selected,
                    cache_reused=f2[str(candidate["candidate_id"])][1],
                )
                if str(candidate["candidate_id"]) in f2
                else _nonallocated(candidate, policy, candidates, stage="F2")
            )
            for candidate in candidates
        ]
    else:
        stage_records["F1"] = [
            _nonallocated(
                candidate,
                policy,
                candidates,
                stage="F1",
                component_disabled=True,
            )
            for candidate in candidates
        ]
        stage_records["F2"] = [
            _nonallocated(
                candidate,
                policy,
                candidates,
                stage="F2",
                component_disabled=True,
            )
            for candidate in candidates
        ]
        f2_selected = f0_selected[:1]

    if f2_selected:
        final_id = f2_selected[0]
        evaluation = _run_candidate(
            design,
            index,
            task,
            by_id[final_id],
            seed=int(assignment["within_unit_seed"]),
            stage="F3",
            root=root,
            output_dir=output_dir,
            python_path=python_path,
            candidate_runner=candidate_runner,
        )
        reused = evaluation["evaluation_hash"] in seen_evaluations
        seen_evaluations.add(evaluation["evaluation_hash"])
        f3[final_id] = (evaluation, reused)
        all_evaluations.append(evaluation)
    stage_records["F3"] = [
        (
            _executed_record(
                candidate,
                policy,
                candidates,
                stage="F3",
                evaluation=f3[str(candidate["candidate_id"])][0],
                selection_score=(
                    float(f3[str(candidate["candidate_id"])][0]["score"])
                    if f3[str(candidate["candidate_id"])][0]["status"] == "succeeded"
                    else None
                ),
                memory_correction=0.0,
                promoted=f3[str(candidate["candidate_id"])][0]["status"] == "succeeded",
                cache_reused=f3[str(candidate["candidate_id"])][1],
            )
            if str(candidate["candidate_id"]) in f3
            else _nonallocated(candidate, policy, candidates, stage="F3")
        )
        for candidate in candidates
    ]
    records = [record for stage in ("F0", "F1", "F2", "F3") for record in stage_records[stage]]
    successful_final = next(
        (evaluation for evaluation, _ in f3.values() if evaluation["status"] == "succeeded"),
        None,
    )
    selected_id = str(successful_final["candidate_id"]) if successful_final is not None else None
    selected_family = (
        str(successful_final["mechanism_family"]) if successful_final is not None else None
    )
    policy_score = float(successful_final["score"]) if successful_final is not None else None
    margin = (
        (policy_score - float(task["baseline_score"])) / float(task["minimum_gain"])
        if policy_score is not None
        else None
    )
    requested = {"F1": len(f1), "F2": len(f2), "F3": len(f3)}
    reserved = sum(
        requested[stage] * _stage_budget(design, stage)[1] for stage in ("F1", "F2", "F3")
    )
    peak = max(
        (float(item["peak_rss_mb"]) for item in all_evaluations),
        default=0.0,
    )
    within_budget = bool(
        reserved <= int(design["maximum_cpu_seconds_per_assignment"])
        and peak <= int(design["maximum_memory_mb"])
    )
    all_executions_valid = bool(all_evaluations) and all(
        item["status"] == "succeeded" for item in all_evaluations
    )
    artifact_valid = successful_final is not None and all_executions_valid
    integrity_valid = successful_final is not None and all(
        bool(item["evaluator_integrity_valid"]) for item in all_evaluations
    )
    replay_valid = bool(
        successful_final is not None
        and successful_final["replay_required"]
        and successful_final["replay_exact"] is True
    )
    failure_codes = sorted(
        {
            str(item["failure_code"])
            for item in all_evaluations
            if item.get("failure_code") is not None
        }
    )
    if successful_final is None:
        failure_codes.append("no_f3_survivor")
    if not within_budget:
        failure_codes.append("assignment_budget_exceeded")
    cost = {
        "requested_evaluations": requested,
        "reserved_cpu_seconds": reserved,
        "observed_logical_cpu_seconds": sum(float(item["cpu_seconds"]) for item in all_evaluations),
        "observed_logical_wall_seconds": sum(
            float(item["wall_seconds"]) for item in all_evaluations
        ),
        "newly_executed_cpu_seconds": sum(
            float(item["cpu_seconds"])
            for item in all_evaluations
            if item["evaluation_hash"] not in seen_evaluations
        ),
        "newly_executed_wall_seconds": sum(
            float(item["wall_seconds"])
            for item in all_evaluations
            if item["evaluation_hash"] not in seen_evaluations
        ),
        "peak_rss_mb": peak,
        "maximum_cpu_seconds": int(design["maximum_cpu_seconds_per_assignment"]),
        "maximum_memory_mb": int(design["maximum_memory_mb"]),
        "within_budget": within_budget,
        "unused_budget_reallocated": False,
    }
    # Physical execution accounting is derived from the stage records because
    # seen_evaluations already includes the current row at this point.
    reused_by_hash = {
        record["evaluation_hash"]: bool(record["cache_reused"])
        for record in records
        if record["evaluation_hash"] is not None
    }
    cost["newly_executed_cpu_seconds"] = sum(
        float(item["cpu_seconds"])
        for item in all_evaluations
        if not reused_by_hash[item["evaluation_hash"]]
    )
    cost["newly_executed_wall_seconds"] = sum(
        float(item["wall_seconds"])
        for item in all_evaluations
        if not reused_by_hash[item["evaluation_hash"]]
    )
    result: dict[str, Any] = {
        "schema_version": ASSIGNMENT_RESULT_SCHEMA_VERSION,
        "assignment_hash": assignment["assignment_hash"],
        "freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
        "unit_id": task["unit_id"],
        "within_unit_seed": int(assignment["within_unit_seed"]),
        "policy_id": policy["policy_id"],
        "stage_records": records,
        "selected_candidate_id": selected_id,
        "selected_candidate_family": selected_family,
        "policy_score": policy_score,
        "baseline_score": float(task["baseline_score"]),
        "minimum_gain": float(task["minimum_gain"]),
        "normalized_margin": margin,
        "objective_task_success": bool(
            margin is not None
            and margin >= 1.0
            and artifact_valid
            and replay_valid
            and within_budget
            and integrity_valid
        ),
        "artifact_valid": artifact_valid,
        "prediction_replay_valid": replay_valid,
        "budget_valid": within_budget,
        "evaluator_integrity_valid": integrity_valid,
        "failure_codes": sorted(set(failure_codes)),
        "memory_before_hash": before,
        "cost": cost,
        "llm_reviewer_score_used": False,
        "intervention_ids": [],
        "partition": "confirmatory",
    }
    if (
        bool(policy["comparative_memory_enabled"])
        and selected_id is not None
        and selected_family is not None
        and policy_score is not None
    ):
        _update_memory(memory, result, enabled=True)
    result["memory_after_hash"] = _memory_hash(memory)
    result["result_hash"] = _canonical_sha256(result)
    return result


def _assignment_projection(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": result["unit_id"],
        "within_unit_seed": result["within_unit_seed"],
        "policy_id": result["policy_id"],
        "selected_candidate_id": result["selected_candidate_id"],
        "selected_candidate_family": result["selected_candidate_family"],
        "policy_score": result["policy_score"],
        "baseline_score": result["baseline_score"],
        "minimum_gain": result["minimum_gain"],
        "normalized_margin": result["normalized_margin"],
        "objective_task_success": result["objective_task_success"],
        "artifact_valid": result["artifact_valid"],
        "prediction_replay_valid": result["prediction_replay_valid"],
        "budget_valid": result["budget_valid"],
        "evaluator_integrity_valid": result["evaluator_integrity_valid"],
        "failure_codes": result["failure_codes"],
        "memory_before_hash": result["memory_before_hash"],
        "memory_after_hash": result["memory_after_hash"],
        "stage_records": [
            {
                "candidate_id": record["candidate_id"],
                "stage": record["stage"],
                "status": record["status"],
                "objective_score": record["objective_score"],
                "selection_score": record["selection_score"],
                "memory_correction": record["memory_correction"],
                "promoted": record["promoted"],
                "failure_code": record["failure_code"],
            }
            for record in result["stage_records"]
        ],
    }


def _run_null_control(
    design: dict[str, Any],
    index: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed: int,
    root: Path,
    output_dir: Path,
    python_path: Path,
    candidate_runner: Path,
) -> dict[str, Any]:
    evaluation = _run_candidate(
        design,
        index,
        task,
        candidate,
        seed=seed,
        stage="F3",
        root=root,
        output_dir=output_dir,
        python_path=python_path,
        candidate_runner=candidate_runner,
    )
    score = float(evaluation["score"]) if evaluation["status"] == "succeeded" else None
    margin = (
        (score - float(task["baseline_score"])) / float(task["minimum_gain"])
        if score is not None
        else None
    )
    result: dict[str, Any] = {
        "schema_version": NULL_RESULT_SCHEMA_VERSION,
        "freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
        "unit_id": task["unit_id"],
        "within_unit_seed": seed,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "score": score,
        "baseline_score": float(task["baseline_score"]),
        "minimum_gain": float(task["minimum_gain"]),
        "normalized_margin": margin,
        "objective_task_success": bool(
            margin is not None
            and margin >= 1.0
            and evaluation["status"] == "succeeded"
            and evaluation["replay_exact"] is True
            and evaluation["evaluator_integrity_valid"] is True
        ),
        "evaluation_hash": evaluation["evaluation_hash"],
        "artifact_valid": evaluation["status"] == "succeeded",
        "prediction_replay_valid": evaluation["replay_exact"] is True,
        "evaluator_integrity_valid": evaluation["evaluator_integrity_valid"],
        "failure_code": evaluation["failure_code"],
    }
    result["result_hash"] = _canonical_sha256(result)
    return result


def run(
    design_path: Path,
    index_path: Path,
    output_dir: Path,
    python_path: Path,
    allowed_root: Path,
    *,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    root = allowed_root.resolve()
    if not root.is_dir():
        raise ValueError("allowed confirmation root does not exist")
    for path in (design_path.resolve(), index_path.resolve(), output_dir.resolve()):
        if not _within(path, root):
            raise ValueError("controller path escaped the allowed confirmation root")
    design = _load_json(design_path)
    index = _load_json(index_path)
    _validate_design(design)
    tasks = _validate_index(index, design, root)
    if (
        _file_sha256(Path(__file__).resolve())
        != design["execution_assets"]["policy_controller_sha256"]
    ):
        raise ValueError("confirmation policy-controller source hash mismatch")
    if (
        _file_sha256(python_path.resolve())
        != design["clean_interpreter_hashes"][index["interpreter_role"]]
    ):
        raise ValueError("confirmation clean-interpreter hash mismatch")
    candidate_runner = _confined_path(
        str(root / design["execution_assets"]["candidate_runner_relative_path"]),
        root,
    )
    if _file_sha256(candidate_runner) != design["execution_assets"]["candidate_runner_sha256"]:
        raise ValueError("confirmation candidate-runner source hash mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    controller_result_path = output_dir / "controller-result.json"
    if controller_result_path.exists():
        result = _load_json(controller_result_path)
        _verify_object_hash(result, "result_hash")
        return result

    policies = {str(item["policy_id"]): item for item in design["policies"]}
    frozen_memory_by_policy = {
        str(item["policy_id"]): item["state"] for item in design["frozen_policy_memories"]
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
        result_path = output_dir / "assignments" / str(assignment["assignment_id"]) / "result.json"
        memory = memory_by_policy_unit[
            (
                str(assignment["policy_id"]),
                str(assignment["unit_id"]),
            )
        ]
        if result_path.exists():
            result = _load_json(result_path)
            _verify_object_hash(result, "result_hash")
            if result["assignment_hash"] != assignment["assignment_hash"]:
                raise ValueError("resumed confirmation assignment hash mismatch")
            if result["memory_before_hash"] != _memory_hash(memory):
                raise ValueError("resumed confirmation memory-before mismatch")
            _update_memory(
                memory,
                result,
                enabled=bool(policies[str(assignment["policy_id"])]["comparative_memory_enabled"]),
            )
            if result["memory_after_hash"] != _memory_hash(memory):
                raise ValueError("resumed confirmation memory-after mismatch")
            action = "resumed"
        else:
            result = _execute_assignment(
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
            _write_json_atomic(result_path, result)
            action = "executed"
        for record in result["stage_records"]:
            if record["evaluation_hash"] is not None:
                seen_evaluations.add(str(record["evaluation_hash"]))
        assignment_hashes[str(assignment["assignment_id"])] = result["result_hash"]
        assignment_projections.append(_assignment_projection(result))
        if progress_path is not None:
            _write_text_atomic(
                progress_path,
                (
                    f"{position}/{total} {action} {assignment['assignment_id']} "
                    f"success={result['objective_task_success']}\n"
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
                result = _load_json(path)
                _verify_object_hash(result, "result_hash")
            else:
                result = _run_null_control(
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
                _write_json_atomic(path, result)
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
        "freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
        "assignments": assignment_projections,
        "null_controls": null_projections,
    }
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "controller_schema_version": SCHEMA_VERSION,
        "freeze_hash": design["freeze_hash"],
        "reveal_hash": index["reveal_hash"],
        "execution_index_hash": index["execution_index_hash"],
        "assignment_result_hashes": dict(sorted(assignment_hashes.items())),
        "null_control_result_hashes": dict(sorted(null_hashes.items())),
        "assignment_count": len(assignment_hashes),
        "null_control_count": len(null_hashes),
        "scientific_projection_hash": _canonical_sha256(projection),
        "frozen_policy_memory_catalogue_hash": _canonical_sha256(
            [item["memory_hash"] for item in design["frozen_policy_memories"]]
        ),
        "memory_cloned_per_confirmatory_unit": True,
        "cross_confirmatory_unit_memory_updates_allowed": False,
        "within_unit_seed_memory_updates_allowed": True,
        "full_matrix_complete": True,
        "network_accessed": False,
        "development_trajectory_accessed": False,
        "frozen_development_policy_parameters_used": True,
        "raw_development_outcomes_accessed": False,
        "external_submission_authorized": False,
        "public_release_authorized": False,
    }
    result["result_hash"] = _canonical_sha256(result)
    _write_json_atomic(controller_result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--input-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--allowed-root", required=True, type=Path)
    parser.add_argument("--progress", type=Path)
    args = parser.parse_args()
    result = run(
        args.design.resolve(),
        args.input_index.resolve(),
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
                "scientific_projection_hash": result["scientific_projection_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
