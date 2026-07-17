"""Resumable, hash-bound execution of the frozen official MDBench matrix."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchAttemptMetrics,
    MDBenchAttemptResult,
    MDBenchAttemptState,
    MDBenchCoefficientTerm,
    MDBenchContainerEnvironment,
    MDBenchExecutionRecord,
    MDBenchExecutionReport,
    MDBenchExperimentMatrix,
    MDBenchMatrixAttemptSpec,
    MDBenchMethodSpec,
    MDBenchSplitIndices,
    MDBenchTargetCoefficients,
)
from autoresearch.competition.preregistration import validate_mdbench_preregistration

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY_ROOT = _REPOSITORY_ROOT / "deploy" / "experiments" / "mdbench"
_RUNNER_PATH = _DEPLOY_ROOT / "runner.py"
_REQUIREMENTS_PATH = _DEPLOY_ROOT / "requirements-sindy.lock"
_DOCKERFILE_PATH = _DEPLOY_ROOT / "Dockerfile"
_ORCHESTRATOR_PATH = Path(__file__).resolve()
_PREREGISTRATION_PATH = Path(__file__).with_name("preregistration.py").resolve()
_CONTRACT_PATH = Path(__file__).with_name("models.py").resolve()
_CONTAINER_RUNNER_PATH = "/opt/autoresearch-mdbench/runner.py"
_REPORT_NAME = "execution-report.json"
_LOG_LIMIT = 16_000


class MDBenchExecutionError(RuntimeError):
    """Raised when official execution cannot preserve its frozen causal chain."""


@dataclass(frozen=True)
class MDBenchContainerInvocation:
    """Resolved host inputs for one disposable container."""

    attempt: MDBenchMatrixAttemptSpec
    method: MDBenchMethodSpec
    environment: MDBenchContainerEnvironment
    artifact_path: Path
    spec_path: Path
    spec_hash: str
    work_dir: Path


@dataclass(frozen=True)
class MDBenchContainerOutcome:
    """Raw container outcome converted into a host-owned terminal result."""

    return_code: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    payload: dict[str, Any] | None = None
    timed_out: bool = False
    failure_reason: str | None = None


EnvironmentProbe = Callable[[str], MDBenchContainerEnvironment]
AttemptExecutor = Callable[[MDBenchContainerInvocation], MDBenchContainerOutcome]


def probe_mdbench_container(image: str) -> MDBenchContainerEnvironment:
    """Verify the exact local image, pinned revision, and copied runner bytes."""

    for required in (
        _RUNNER_PATH,
        _REQUIREMENTS_PATH,
        _DOCKERFILE_PATH,
        _ORCHESTRATOR_PATH,
        _PREREGISTRATION_PATH,
        _CONTRACT_PATH,
    ):
        if not required.is_file():
            raise MDBenchExecutionError(f"execution source file is missing: {required}")
    try:
        inspected = subprocess.run(
            ["docker", "image", "inspect", image],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(inspected.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MDBenchExecutionError(f"cannot inspect MDBench image {image}: {exc}") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise MDBenchExecutionError("docker image inspect returned an unexpected payload")
    image_payload = payload[0]
    image_id = str(image_payload.get("Id", ""))
    labels = image_payload.get("Config", {}).get("Labels", {}) or {}
    revision = str(labels.get("org.opencontainers.image.revision", ""))
    local_runner_hash = _sha256_file(_RUNNER_PATH)
    try:
        runner_probe = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                image,
                "sha256sum",
                _CONTAINER_RUNNER_PATH,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise MDBenchExecutionError(f"cannot verify runner inside {image}: {exc}") from exc
    container_runner_hash = runner_probe.stdout.strip().split(maxsplit=1)[0]
    if container_runner_hash != local_runner_hash:
        raise MDBenchExecutionError(
            "container runner hash does not match the checked-out execution source"
        )
    requirements_hash = _sha256_file(_REQUIREMENTS_PATH)
    dockerfile_hash = _sha256_file(_DOCKERFILE_PATH)
    orchestrator_hash = _sha256_file(_ORCHESTRATOR_PATH)
    preregistration_hash = _sha256_file(_PREREGISTRATION_PATH)
    contract_hash = _sha256_file(_CONTRACT_PATH)
    code_hash = canonical_model_hash(
        {
            "benchmark_revision": revision,
            "contract_sha256": contract_hash,
            "dockerfile_sha256": dockerfile_hash,
            "orchestrator_sha256": orchestrator_hash,
            "preregistration_sha256": preregistration_hash,
            "requirements_sha256": requirements_hash,
            "runner_sha256": local_runner_hash,
        }
    )
    repo_digests = tuple(sorted(str(item) for item in image_payload.get("RepoDigests", []) or []))
    environment_hash = canonical_model_hash(
        {
            "architecture": image_payload.get("Architecture"),
            "code_hash": code_hash,
            "image_id": image_id,
            "operating_system": image_payload.get("Os"),
            "repo_digests": repo_digests,
            "revision": revision,
        }
    )
    try:
        return MDBenchContainerEnvironment(
            image=image,
            image_id=image_id,
            repo_digests=repo_digests,
            benchmark_revision=revision,
            runner_sha256=local_runner_hash,
            requirements_sha256=requirements_hash,
            dockerfile_sha256=dockerfile_hash,
            orchestrator_sha256=orchestrator_hash,
            preregistration_sha256=preregistration_hash,
            contract_sha256=contract_hash,
            code_hash=code_hash,
            environment_hash=environment_hash,
        )
    except ValidationError as exc:
        raise MDBenchExecutionError(f"invalid MDBench container identity: {exc}") from exc


def execute_mdbench_matrix(
    matrix_path: Path | str,
    archive_manifest_path: Path | str,
    output_dir: Path | str,
    *,
    image: str,
    max_attempts: int | None = None,
    attempt_ids: Sequence[str] | None = None,
    environment_probe: EnvironmentProbe = probe_mdbench_container,
    attempt_executor: AttemptExecutor | None = None,
) -> MDBenchExecutionReport:
    """Execute or resume selected cells without changing the frozen matrix."""

    if max_attempts is not None and max_attempts < 1:
        raise MDBenchExecutionError("max_attempts must be at least one when provided")
    resolved_matrix_path = Path(matrix_path).resolve()
    resolved_manifest_path = Path(archive_manifest_path).resolve()
    try:
        matrix = MDBenchExperimentMatrix.model_validate_json(
            resolved_matrix_path.read_text(encoding="utf-8")
        )
        archive_manifest = MDBenchArchiveManifest.model_validate_json(
            resolved_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise MDBenchExecutionError(f"cannot load official execution inputs: {exc}") from exc
    validate_mdbench_preregistration(matrix)
    _validate_matrix_archive_binding(matrix, archive_manifest)

    environment = environment_probe(image)
    if environment.benchmark_revision != matrix.benchmark_revision:
        raise MDBenchExecutionError("container revision does not match the frozen matrix")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / _REPORT_NAME
    if report_path.is_file():
        previous = load_mdbench_execution_report(report_path)
        if previous.matrix_hash != matrix.matrix_hash:
            raise MDBenchExecutionError("execution checkpoint belongs to another matrix")
        if previous.environment.environment_hash != environment.environment_hash:
            raise MDBenchExecutionError(
                "execution checkpoint belongs to a different container environment"
            )

    selected = _select_attempts(matrix, attempt_ids)
    methods = {method.method_id: method for method in matrix.methods}
    artifacts = {
        (artifact.data_type, artifact.system_name, artifact.condition): artifact
        for artifact in archive_manifest.artifacts
    }
    results: dict[str, MDBenchAttemptResult] = {}
    reused_ids: set[str] = set()
    for attempt in matrix.attempts:
        result_path = _result_path(root, attempt)
        if result_path.is_file():
            result = load_mdbench_attempt_result(result_path)
            _validate_result_binding(result, attempt, matrix, environment)
            results[attempt.attempt_id] = result
            reused_ids.add(attempt.attempt_id)

    _write_execution_report(
        report_path=report_path,
        matrix_path=resolved_matrix_path,
        archive_manifest_path=resolved_manifest_path,
        matrix=matrix,
        archive_manifest=archive_manifest,
        environment=environment,
        results=results,
        reused_ids=reused_ids,
    )
    executor = attempt_executor or run_mdbench_attempt_container
    executed = 0
    for attempt in selected:
        if attempt.attempt_id in results:
            continue
        if max_attempts is not None and executed >= max_attempts:
            break
        method = methods.get(attempt.method_id)
        if method is None:
            raise MDBenchExecutionError(f"method missing from matrix: {attempt.method_id}")
        artifact = artifacts.get((attempt.data_type, attempt.system_name, attempt.condition))
        artifact_path = _verify_attempt_artifact(archive_manifest, attempt, artifact)
        invocation = _prepare_invocation(
            root=root,
            matrix=matrix,
            attempt=attempt,
            method=method,
            environment=environment,
            artifact_path=artifact_path,
        )
        started_at = datetime.now(timezone.utc)
        try:
            outcome = executor(invocation)
        except Exception as exc:  # noqa: BLE001 - terminal infrastructure evidence
            elapsed = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())
            outcome = MDBenchContainerOutcome(
                return_code=None,
                stdout="",
                stderr="",
                elapsed_seconds=elapsed,
                failure_reason=f"attempt executor raised {type(exc).__name__}: {exc}",
            )
        completed_at = datetime.now(timezone.utc)
        result = _persist_attempt_outcome(
            root=root,
            matrix=matrix,
            attempt=attempt,
            environment=environment,
            invocation=invocation,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
        )
        results[attempt.attempt_id] = result
        executed += 1
        _write_execution_report(
            report_path=report_path,
            matrix_path=resolved_matrix_path,
            archive_manifest_path=resolved_manifest_path,
            matrix=matrix,
            archive_manifest=archive_manifest,
            environment=environment,
            results=results,
            reused_ids=reused_ids,
        )
    return _write_execution_report(
        report_path=report_path,
        matrix_path=resolved_matrix_path,
        archive_manifest_path=resolved_manifest_path,
        matrix=matrix,
        archive_manifest=archive_manifest,
        environment=environment,
        results=results,
        reused_ids=reused_ids,
    )


def run_mdbench_attempt_container(
    invocation: MDBenchContainerInvocation,
) -> MDBenchContainerOutcome:
    """Run one attempt in a disposable, offline, resource-bounded container."""

    invocation.work_dir.mkdir(parents=True, exist_ok=True)
    payload_path = invocation.work_dir / "payload.json"
    payload_path.unlink(missing_ok=True)
    container_name = f"autoresearch-mdbench-{invocation.attempt.config_hash[:20]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--cpus",
        str(invocation.method.max_cpu_cores),
        "--memory",
        f"{invocation.method.max_memory_mb}m",
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=512m",
        "--env",
        f"OMP_NUM_THREADS={invocation.method.max_cpu_cores}",
        "--env",
        f"OPENBLAS_NUM_THREADS={invocation.method.max_cpu_cores}",
        "--env",
        f"MKL_NUM_THREADS={invocation.method.max_cpu_cores}",
        "--label",
        f"autoresearch.mdbench.attempt={invocation.attempt.config_hash}",
        "--mount",
        _bind_mount(invocation.spec_path, "/input/spec.json", read_only=True),
        "--mount",
        _bind_mount(invocation.artifact_path, "/input/data.npz", read_only=True),
        "--mount",
        _bind_mount(invocation.work_dir, "/output", read_only=False),
        invocation.environment.image,
        "python",
        _CONTAINER_RUNNER_PATH,
        "--spec",
        "/input/spec.json",
        "--data",
        "/input/data.npz",
        "--output",
        "/output/payload.json",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=invocation.method.max_seconds_per_attempt + 15,
        )
    except subprocess.TimeoutExpired as exc:
        _force_remove_container(container_name)
        return MDBenchContainerOutcome(
            return_code=None,
            stdout=_timeout_text(exc.stdout),
            stderr=_timeout_text(exc.stderr),
            elapsed_seconds=time.monotonic() - started,
            timed_out=True,
            failure_reason=(
                "outer container timeout after "
                f"{invocation.method.max_seconds_per_attempt + 15} seconds"
            ),
        )
    except FileNotFoundError as exc:
        return MDBenchContainerOutcome(
            return_code=None,
            stdout="",
            stderr="",
            elapsed_seconds=time.monotonic() - started,
            failure_reason=f"docker executable is unavailable: {exc}",
        )
    elapsed = time.monotonic() - started
    payload: dict[str, Any] | None = None
    failure_reason: str | None = None
    if payload_path.is_file():
        try:
            loaded = json.loads(payload_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise TypeError("runner payload is not an object")
            payload = loaded
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            failure_reason = f"cannot parse runner payload: {exc}"
    elif completed.returncode != 0:
        failure_reason = f"container exited {completed.returncode} without a payload"
    else:
        failure_reason = "container exited successfully without a payload"
    return MDBenchContainerOutcome(
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=elapsed,
        payload=payload,
        failure_reason=failure_reason,
    )


def load_mdbench_attempt_result(path: Path | str) -> MDBenchAttemptResult:
    """Load one terminal result and reject byte-valid content tampering."""

    resolved = Path(path).resolve()
    try:
        result = MDBenchAttemptResult.model_validate_json(resolved.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise MDBenchExecutionError(f"cannot load MDBench attempt result {resolved}: {exc}") from exc
    if Path(result.output_path).resolve() != resolved:
        raise MDBenchExecutionError(f"attempt result output path mismatch: {resolved}")
    expected = canonical_model_hash(
        result.model_dump(mode="json", exclude={"result_hash", "output_path"})
    )
    if result.result_hash != expected:
        raise MDBenchExecutionError(f"attempt result hash mismatch: {resolved}")
    return result


def load_mdbench_execution_report(path: Path | str) -> MDBenchExecutionReport:
    """Load a matrix checkpoint and reject changed records or counts."""

    resolved = Path(path).resolve()
    try:
        report = MDBenchExecutionReport.model_validate_json(resolved.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise MDBenchExecutionError(f"cannot load MDBench execution report: {exc}") from exc
    if Path(report.output_path).resolve() != resolved:
        raise MDBenchExecutionError("MDBench execution report output path mismatch")
    expected = canonical_model_hash(
        report.model_dump(mode="json", exclude={"report_hash", "output_path"})
    )
    if report.report_hash != expected:
        raise MDBenchExecutionError("MDBench execution report hash mismatch")
    return report


def _validate_matrix_archive_binding(
    matrix: MDBenchExperimentMatrix,
    archive_manifest: MDBenchArchiveManifest,
) -> None:
    expected_inventory_hash = canonical_model_hash(
        {
            "archive_sha256": archive_manifest.archive_sha256,
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in archive_manifest.artifacts
            ],
        }
    )
    if archive_manifest.inventory_hash != expected_inventory_hash:
        raise MDBenchExecutionError("archive inventory content hash mismatch")
    expected = (
        matrix.benchmark_revision,
        matrix.archive_sha256,
        matrix.inventory_hash,
    )
    actual = (
        archive_manifest.benchmark_revision,
        archive_manifest.archive_sha256,
        archive_manifest.inventory_hash,
    )
    if actual != expected:
        raise MDBenchExecutionError("archive manifest does not belong to the frozen matrix")


def _select_attempts(
    matrix: MDBenchExperimentMatrix,
    attempt_ids: Sequence[str] | None,
) -> tuple[MDBenchMatrixAttemptSpec, ...]:
    if attempt_ids is None:
        return matrix.attempts
    requested = tuple(dict.fromkeys(attempt_ids))
    known = {attempt.attempt_id: attempt for attempt in matrix.attempts}
    missing = sorted(set(requested).difference(known))
    if missing:
        raise MDBenchExecutionError(f"unknown frozen attempt IDs: {', '.join(missing)}")
    return tuple(known[attempt_id] for attempt_id in requested)


def _verify_attempt_artifact(
    archive_manifest: MDBenchArchiveManifest,
    attempt: MDBenchMatrixAttemptSpec,
    artifact: Any,
) -> Path:
    if artifact is None:
        raise MDBenchExecutionError(f"archive artifact missing for {attempt.attempt_id}")
    if artifact.relative_path != attempt.artifact_path:
        raise MDBenchExecutionError(f"artifact path mismatch for {attempt.attempt_id}")
    if artifact.sha256 != attempt.artifact_sha256:
        raise MDBenchExecutionError(f"artifact manifest hash mismatch for {attempt.attempt_id}")
    root = Path(archive_manifest.extracted_root).resolve()
    path = (root / Path(attempt.artifact_path)).resolve()
    if not path.is_relative_to(root):
        raise MDBenchExecutionError(f"artifact escapes extracted root: {attempt.artifact_path}")
    if not path.is_file():
        raise MDBenchExecutionError(f"artifact is missing: {path}")
    if _sha256_file(path) != attempt.artifact_sha256:
        raise MDBenchExecutionError(f"artifact bytes changed for {attempt.attempt_id}")
    return path


def _prepare_invocation(
    *,
    root: Path,
    matrix: MDBenchExperimentMatrix,
    attempt: MDBenchMatrixAttemptSpec,
    method: MDBenchMethodSpec,
    environment: MDBenchContainerEnvironment,
    artifact_path: Path,
) -> MDBenchContainerInvocation:
    spec_root = root / "specs"
    work_dir = root / "work" / attempt.config_hash
    spec_path = spec_root / f"{attempt.config_hash}.json"
    base_spec = {
        "schema_version": "mdbench-runner-spec-v1",
        "matrix_hash": matrix.matrix_hash,
        "benchmark_revision": matrix.benchmark_revision,
        "attempt": attempt.model_dump(mode="json"),
        "method": method.model_dump(mode="json"),
        "split_policy": matrix.split_policy.model_dump(mode="json"),
        "expected_runner_sha256": environment.runner_sha256,
        "execution_contract": {
            "fit_derivative": "split-local derivative estimated from observed u",
            "validation_target": "split-local derivative estimated from observed u",
            "test_target": "official stored clean du",
            "trajectory_initial_state": "first chronological test observation for ODE only",
            "post_preregistration_row_subsampling": False,
        },
    }
    spec_hash = canonical_model_hash(base_spec)
    write_json_model(spec_path, {**base_spec, "spec_hash": spec_hash})
    return MDBenchContainerInvocation(
        attempt=attempt,
        method=method,
        environment=environment,
        artifact_path=artifact_path,
        spec_path=spec_path,
        spec_hash=spec_hash,
        work_dir=work_dir,
    )


def _persist_attempt_outcome(
    *,
    root: Path,
    matrix: MDBenchExperimentMatrix,
    attempt: MDBenchMatrixAttemptSpec,
    environment: MDBenchContainerEnvironment,
    invocation: MDBenchContainerInvocation,
    outcome: MDBenchContainerOutcome,
    started_at: datetime,
    completed_at: datetime,
) -> MDBenchAttemptResult:
    log_root = root / "logs"
    stdout_path = log_root / f"{attempt.config_hash}.stdout.log"
    stderr_path = log_root / f"{attempt.config_hash}.stderr.log"
    _write_text_atomic(stdout_path, outcome.stdout[-_LOG_LIMIT:])
    _write_text_atomic(stderr_path, outcome.stderr[-_LOG_LIMIT:])
    stdout_hash = _sha256_file(stdout_path)
    stderr_hash = _sha256_file(stderr_path)
    status, failure_reason = _outcome_status(outcome)
    payload = outcome.payload or {}
    split_indices: MDBenchSplitIndices | None = None
    selected_hyperparameters: dict[str, Any] = {}
    discovered_equation: str | None = None
    coefficients: tuple[MDBenchTargetCoefficients, ...] = ()
    metrics = MDBenchAttemptMetrics(
        wall_time_seconds=max(0.0, outcome.elapsed_seconds),
        peak_rss_mb=0.0,
    )
    if outcome.payload is not None:
        try:
            if payload.get("spec_hash") != invocation.spec_hash:
                raise ValueError("runner payload spec hash mismatch")
            if payload.get("runner_sha256") != environment.runner_sha256:
                raise ValueError("runner payload code hash mismatch")
            payload_status = MDBenchAttemptState(str(payload.get("status")))
            if outcome.return_code not in (0, None) and payload_status is MDBenchAttemptState.SUCCEEDED:
                raise ValueError("non-zero container exit cannot be a successful attempt")
            status = payload_status
            split_payload = payload.get("split_indices")
            if split_payload is not None:
                split_indices = MDBenchSplitIndices.model_validate(split_payload)
            selected = payload.get("selected_hyperparameters", {})
            if not isinstance(selected, dict):
                raise TypeError("selected_hyperparameters must be an object")
            selected_hyperparameters = selected
            equation = payload.get("discovered_equation")
            discovered_equation = str(equation) if equation is not None else None
            coefficients = _parse_coefficients(payload.get("coefficients", []))
            metrics = MDBenchAttemptMetrics(
                derivative_nmse=payload.get("derivative_nmse"),
                validation_nmse=payload.get("validation_nmse"),
                trajectory_extrapolation_nmse_ode=payload.get(
                    "trajectory_extrapolation_nmse_ode"
                ),
                model_complexity=payload.get("model_complexity"),
                wall_time_seconds=float(
                    payload.get("wall_time_seconds", outcome.elapsed_seconds)
                ),
                peak_rss_mb=float(payload.get("peak_rss_mb", 0.0)),
            )
            payload_failure = payload.get("failure_reason")
            failure_reason = str(payload_failure) if payload_failure else None
            if status is MDBenchAttemptState.SUCCEEDED:
                if (
                    discovered_equation is None
                    or metrics.derivative_nmse is None
                    or metrics.validation_nmse is None
                    or metrics.model_complexity is None
                    or split_indices is None
                    or (
                        attempt.data_type == "ode"
                        and metrics.trajectory_extrapolation_nmse_ode is None
                    )
                ):
                    raise ValueError("successful payload is missing required scientific evidence")
                failure_reason = None
            elif failure_reason is None:
                failure_reason = f"runner returned {status.value} without a failure reason"
        except (TypeError, ValueError, ValidationError) as exc:
            status = MDBenchAttemptState.FAILED
            failure_reason = f"invalid runner payload: {exc}"
            split_indices = None
            selected_hyperparameters = {}
            discovered_equation = None
            coefficients = ()
            metrics = MDBenchAttemptMetrics(
                wall_time_seconds=max(0.0, outcome.elapsed_seconds),
                peak_rss_mb=0.0,
            )
    result_path = _result_path(root, attempt)
    unstamped = MDBenchAttemptResult(
        attempt_id=attempt.attempt_id,
        matrix_hash=matrix.matrix_hash,
        benchmark_revision=matrix.benchmark_revision,
        data_type=attempt.data_type,
        system_name=attempt.system_name,
        evaluation_split=attempt.evaluation_split,
        condition=attempt.condition,
        seed=attempt.seed,
        method_id=attempt.method_id,
        status=status,
        artifact_path=attempt.artifact_path,
        data_hash=attempt.artifact_sha256,
        config_hash=attempt.config_hash,
        spec_hash=invocation.spec_hash,
        code_hash=environment.code_hash,
        environment_hash=environment.environment_hash,
        container_image=environment.image,
        container_image_id=environment.image_id,
        split_indices=split_indices,
        selected_hyperparameters=selected_hyperparameters,
        discovered_equation=discovered_equation,
        coefficients=coefficients,
        metrics=metrics,
        failure_reason=failure_reason,
        stdout_path=stdout_path.as_posix(),
        stdout_sha256=stdout_hash,
        stderr_path=stderr_path.as_posix(),
        stderr_sha256=stderr_hash,
        started_at=started_at,
        completed_at=completed_at,
        output_path=result_path.as_posix(),
    )
    result_hash = canonical_model_hash(
        unstamped.model_dump(mode="json", exclude={"result_hash", "output_path"})
    )
    stamped = unstamped.model_copy(update={"result_hash": result_hash})
    write_json_model(result_path, stamped)
    return stamped


def _outcome_status(
    outcome: MDBenchContainerOutcome,
) -> tuple[MDBenchAttemptState, str | None]:
    if outcome.timed_out:
        return MDBenchAttemptState.TIMED_OUT, outcome.failure_reason or "container timed out"
    if outcome.failure_reason:
        return MDBenchAttemptState.FAILED, outcome.failure_reason
    if outcome.payload is None:
        return MDBenchAttemptState.FAILED, "container produced no runner payload"
    return MDBenchAttemptState.FAILED, "runner payload did not contain a terminal status"


def _parse_coefficients(payload: Any) -> tuple[MDBenchTargetCoefficients, ...]:
    if not isinstance(payload, list):
        raise TypeError("coefficients must be a list")
    parsed: list[MDBenchTargetCoefficients] = []
    for target_payload in payload:
        if not isinstance(target_payload, dict):
            raise TypeError("coefficient target must be an object")
        terms_payload = target_payload.get("terms", [])
        if not isinstance(terms_payload, list):
            raise TypeError("coefficient terms must be a list")
        if any(not isinstance(term, dict) for term in terms_payload):
            raise TypeError("each coefficient term must be an object")
        terms = tuple(
            MDBenchCoefficientTerm(
                feature=str(term["feature"]),
                coefficient=float(term["coefficient"]),
            )
            for term in terms_payload
        )
        parsed.append(
            MDBenchTargetCoefficients(target=str(target_payload["target"]), terms=terms)
        )
    return tuple(parsed)


def _validate_result_binding(
    result: MDBenchAttemptResult,
    attempt: MDBenchMatrixAttemptSpec,
    matrix: MDBenchExperimentMatrix,
    environment: MDBenchContainerEnvironment,
) -> None:
    expected = (
        attempt.attempt_id,
        matrix.matrix_hash,
        matrix.benchmark_revision,
        attempt.config_hash,
        attempt.artifact_sha256,
        environment.code_hash,
        environment.environment_hash,
        environment.image_id,
    )
    actual = (
        result.attempt_id,
        result.matrix_hash,
        result.benchmark_revision,
        result.config_hash,
        result.data_hash,
        result.code_hash,
        result.environment_hash,
        result.container_image_id,
    )
    if actual != expected:
        raise MDBenchExecutionError(f"attempt checkpoint causal mismatch: {attempt.attempt_id}")
    result_path = Path(result.output_path).resolve()
    spec_path = result_path.parent.parent / "specs" / f"{attempt.config_hash}.json"
    try:
        spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
        persisted_spec_hash = spec_payload.pop("spec_hash")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise MDBenchExecutionError(f"attempt spec is missing or invalid: {spec_path}") from exc
    if (
        persisted_spec_hash != result.spec_hash
        or canonical_model_hash(spec_payload) != result.spec_hash
    ):
        raise MDBenchExecutionError(f"attempt spec hash mismatch: {spec_path}")
    for log_path, log_hash in (
        (result.stdout_path, result.stdout_sha256),
        (result.stderr_path, result.stderr_sha256),
    ):
        path = Path(log_path)
        if not path.is_file() or _sha256_file(path) != log_hash:
            raise MDBenchExecutionError(f"attempt log hash mismatch: {path}")


def _write_execution_report(
    *,
    report_path: Path,
    matrix_path: Path,
    archive_manifest_path: Path,
    matrix: MDBenchExperimentMatrix,
    archive_manifest: MDBenchArchiveManifest,
    environment: MDBenchContainerEnvironment,
    results: dict[str, MDBenchAttemptResult],
    reused_ids: set[str],
) -> MDBenchExecutionReport:
    records = tuple(
        MDBenchExecutionRecord(
            attempt_id=attempt.attempt_id,
            status=results[attempt.attempt_id].status,
            result_path=results[attempt.attempt_id].output_path,
            result_hash=results[attempt.attempt_id].result_hash or "",
            reused_this_invocation=attempt.attempt_id in reused_ids,
        )
        for attempt in matrix.attempts
        if attempt.attempt_id in results
    )
    succeeded = sum(record.status is MDBenchAttemptState.SUCCEEDED for record in records)
    failed = sum(record.status is MDBenchAttemptState.FAILED for record in records)
    timed_out = sum(record.status is MDBenchAttemptState.TIMED_OUT for record in records)
    terminal = len(records)
    pending = len(matrix.attempts) - terminal
    unstamped = MDBenchExecutionReport(
        matrix_path=matrix_path.as_posix(),
        matrix_hash=matrix.matrix_hash,
        archive_manifest_path=archive_manifest_path.as_posix(),
        inventory_hash=archive_manifest.inventory_hash,
        environment=environment,
        records=records,
        total_attempt_count=len(matrix.attempts),
        terminal_attempt_count=terminal,
        succeeded_count=succeeded,
        failed_count=failed,
        timed_out_count=timed_out,
        pending_count=pending,
        complete=pending == 0,
        updated_at=datetime.now(timezone.utc),
        output_path=report_path.as_posix(),
    )
    report_hash = canonical_model_hash(
        unstamped.model_dump(mode="json", exclude={"report_hash", "output_path"})
    )
    stamped = unstamped.model_copy(update={"report_hash": report_hash})
    write_json_model(report_path, stamped)
    return stamped


def _result_path(root: Path, attempt: MDBenchMatrixAttemptSpec) -> Path:
    return root / "results" / f"{attempt.config_hash}.json"


def _bind_mount(source: Path, target: str, *, read_only: bool) -> str:
    option = f"type=bind,source={source.resolve().as_posix()},target={target}"
    return f"{option},readonly" if read_only else option


def _force_remove_container(container_name: str) -> None:
    try:
        subprocess.run(
            ["docker", "container", "rm", "--force", container_name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
