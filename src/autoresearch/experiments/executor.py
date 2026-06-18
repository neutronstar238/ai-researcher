"""Local sandbox executor for MVP experiment tasks."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.experiments.review import CodeReviewFinding, review_generated_code
from autoresearch.experiments.sandbox import SandboxAccessMode, SandboxPathPolicy
from autoresearch.schemas import ExecutionRun, ExecutionStatus, ExperimentTask
from autoresearch.schemas.provenance import file_hash

NETWORK_ACCESS_APPROVAL_KEY = "network_access_approved"
STATIC_PREFLIGHT_BLOCK_CATEGORIES = frozenset(
    {"dangerous_command", "path_traversal", "secret_read"}
)


def execute_experiment_task(
    experiment_dir: Path | str,
    task: ExperimentTask,
    *,
    python_executable: str | Path = sys.executable,
    cache_dirs: list[Path | str] | None = None,
    output_dirs: list[Path | str] | None = None,
    project_root: Path | str | None = None,
    entrypoint: str | Path | None = None,
    commit_sha: str | None = None,
) -> ExecutionRun:
    """Execute an experiment task locally with sandbox runtime limits."""

    root = Path(experiment_dir).resolve()
    policy = SandboxPathPolicy(
        root,
        cache_dirs=cache_dirs,
        output_dirs=output_dirs,
        project_root=project_root,
    )
    entrypoint_path = policy.require_access(
        Path(entrypoint) if entrypoint is not None else Path(task.entrypoint).name,
        SandboxAccessMode.READ,
    )
    timeout_seconds = _positive_int(task.timeout_seconds, default=1)
    memory_limit_mb = _optional_positive_int(task.resource_budget.get("memory_mb"))
    run = ExecutionRun(
        project_id=task.project_id,
        task_id=task.id,
        status=ExecutionStatus.RUNNING,
        start_time=datetime.now(timezone.utc),
        commit_sha=commit_sha,
        config_hash=_config_hash_if_present(root),
        metadata={
            "experiment_dir": root.as_posix(),
            "entrypoint": entrypoint_path.as_posix(),
            "timeout_seconds": timeout_seconds,
            "memory_limit_mb": memory_limit_mb,
        },
    )
    preflight_findings = _preflight_findings(root, entrypoint_path)
    static_findings = _static_preflight_findings(preflight_findings)
    if static_findings:
        run = _with_static_preflight_metadata(run, findings=static_findings)
        return _finish_run(
            run,
            root,
            status=ExecutionStatus.FAILED,
            exit_code=None,
            stdout="",
            stderr=_static_preflight_message(static_findings),
            limit_violations=["static_preflight"],
            error_type="StaticPreflightDenied",
        )

    network_findings = _network_preflight_findings(preflight_findings)
    if network_findings:
        approved = task.metadata.get(NETWORK_ACCESS_APPROVAL_KEY) is True
        run = _with_network_preflight_metadata(
            run,
            findings=network_findings,
            approved=approved,
            task_metadata=task.metadata,
        )
        if not approved:
            return _finish_run(
                run,
                root,
                status=ExecutionStatus.FAILED,
                exit_code=None,
                stdout="",
                stderr=_network_preflight_message(network_findings),
                limit_violations=["network_preflight"],
                error_type="NetworkPreflightDenied",
            )

    command = [str(python_executable), str(entrypoint_path)]
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_process_group_kwargs(task),
    )
    deadline = time.monotonic() + timeout_seconds
    limit_violations: list[str] = []

    try:
        stdout, stderr = _communicate_with_limits(
            process,
            deadline,
            memory_limit_mb,
            limit_violations,
        )
    except subprocess.TimeoutExpired:
        limit_violations.append("timeout_seconds")
        _terminate_process_tree(process)
        stdout, stderr = _communicate_after_termination(process)
        return _finish_run(
            run,
            root,
            status=ExecutionStatus.TIMEOUT,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            limit_violations=limit_violations,
            error_type="TimeoutExpired",
        )

    if "memory_mb" in limit_violations:
        return _finish_run(
            run,
            root,
            status=ExecutionStatus.FAILED,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            limit_violations=limit_violations,
            error_type="MemoryLimitExceeded",
        )

    status = ExecutionStatus.SUCCESS if process.returncode == 0 else ExecutionStatus.FAILED
    error_type = None if status is ExecutionStatus.SUCCESS else "NonZeroExit"
    return _finish_run(
        run,
        root,
        status=status,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        limit_violations=limit_violations,
        error_type=error_type,
    )


def _preflight_findings(
    experiment_dir: Path,
    entrypoint_path: Path,
) -> tuple[CodeReviewFinding, ...]:
    entrypoint = entrypoint_path.relative_to(experiment_dir).as_posix()
    result = review_generated_code(experiment_dir, entrypoint=entrypoint)
    return result.findings


def _static_preflight_findings(
    findings: tuple[CodeReviewFinding, ...],
) -> tuple[CodeReviewFinding, ...]:
    return tuple(
        finding
        for finding in findings
        if finding.category in STATIC_PREFLIGHT_BLOCK_CATEGORIES
    )


def _network_preflight_findings(
    findings: tuple[CodeReviewFinding, ...],
) -> tuple[CodeReviewFinding, ...]:
    return tuple(finding for finding in findings if finding.category == "unrestricted_network")


def _with_static_preflight_metadata(
    run: ExecutionRun,
    *,
    findings: tuple[CodeReviewFinding, ...],
) -> ExecutionRun:
    metadata = dict(run.metadata)
    metadata["static_preflight"] = {
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    return run.model_copy(update={"metadata": metadata})


def _with_network_preflight_metadata(
    run: ExecutionRun,
    *,
    findings: tuple[CodeReviewFinding, ...],
    approved: bool,
    task_metadata: dict[str, Any],
) -> ExecutionRun:
    metadata = dict(run.metadata)
    preflight_metadata: dict[str, Any] = {
        "approved": approved,
        "approval_key": NETWORK_ACCESS_APPROVAL_KEY,
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    for key in (
        "network_access_scope",
        "approved_network_domains",
        "network_source_urls",
        "network_approval_mode",
        "network_approval_id",
        "network_approved_by",
    ):
        if key in task_metadata:
            preflight_metadata[key] = task_metadata[key]
    metadata["network_preflight"] = preflight_metadata
    return run.model_copy(update={"metadata": metadata})


def _static_preflight_message(findings: tuple[CodeReviewFinding, ...]) -> str:
    details = "; ".join(
        f"line {finding.line}: {finding.category}: {finding.message}"
        if finding.line is not None
        else f"{finding.category}: {finding.message}"
        for finding in findings
    )
    return (
        "Generated experiment code failed static security preflight. "
        f"Findings: {details}. "
        "Regenerate or quarantine the experiment before local execution."
    )


def _network_preflight_message(findings: tuple[CodeReviewFinding, ...]) -> str:
    details = "; ".join(
        f"line {finding.line}: {finding.message}"
        if finding.line is not None
        else finding.message
        for finding in findings
    )
    return (
        "Generated experiment imports network modules without explicit approval. "
        f"Findings: {details}. "
        f"Set task.metadata[{NETWORK_ACCESS_APPROVAL_KEY!r}]=True only after "
        "human approval or route network operations through RestrictedNetworkPolicy."
    )


def _communicate_with_limits(
    process: subprocess.Popen[str],
    deadline: float,
    memory_limit_mb: int | None,
    limit_violations: list[str],
) -> tuple[str, str]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout=0)

        if _memory_limit_exceeded(process.pid, memory_limit_mb):
            limit_violations.append("memory_mb")
            _terminate_process_tree(process)
            return _communicate_after_termination(process)

        try:
            return process.communicate(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def _finish_run(
    run: ExecutionRun,
    experiment_dir: Path,
    *,
    status: ExecutionStatus,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    limit_violations: list[str],
    error_type: str | None,
) -> ExecutionRun:
    metrics_path = experiment_dir / "metrics.json"
    return run.model_copy(
        update={
            "status": status,
            "end_time": datetime.now(timezone.utc),
            "metrics_path": metrics_path.as_posix() if metrics_path.exists() else None,
            "artifact_uri": (experiment_dir / "artifacts").as_posix(),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "limit_violations": limit_violations,
            "error_type": error_type,
        }
    )


def _process_group_kwargs(task: ExperimentTask) -> dict[str, Any]:
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags}

    preexec_fn = _resource_limiter(task)
    return {"start_new_session": True, "preexec_fn": preexec_fn}


def _resource_limiter(task: ExperimentTask) -> Callable[[], None] | None:
    if os.name == "nt":
        return None

    def limit_resources() -> None:
        try:
            import resource
        except ImportError:
            return

        setrlimit: Any = getattr(resource, "setrlimit", None)
        rlimit_cpu: Any = getattr(resource, "RLIMIT_CPU", None)
        rlimit_as: Any = getattr(resource, "RLIMIT_AS", None)
        cpu_time_seconds = _optional_positive_int(task.resource_budget.get("cpu_time_seconds"))
        memory_mb = _optional_positive_int(task.resource_budget.get("memory_mb"))
        if setrlimit is not None and rlimit_cpu is not None and cpu_time_seconds is not None:
            setrlimit(rlimit_cpu, (cpu_time_seconds, cpu_time_seconds))
        if setrlimit is not None and rlimit_as is not None and memory_mb is not None:
            memory_bytes = memory_mb * 1024 * 1024
            setrlimit(rlimit_as, (memory_bytes, memory_bytes))

    return limit_resources


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    killpg: Any = getattr(os, "killpg", None)
    if killpg is None:
        process.terminate()
        return

    try:
        killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        killpg(process.pid, sigkill)


def _communicate_after_termination(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


def _memory_limit_exceeded(pid: int, memory_limit_mb: int | None) -> bool:
    if memory_limit_mb is None:
        return False
    rss_bytes = _current_rss_bytes(pid)
    if rss_bytes is None:
        return False
    return rss_bytes > memory_limit_mb * 1024 * 1024


def _current_rss_bytes(pid: int) -> int | None:
    if os.name == "nt":
        return _windows_rss_bytes(pid)
    return _proc_rss_bytes(pid)


def _windows_rss_bytes(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    windll: Any = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    process_query_information = 0x0400
    process_vm_read = 0x0010
    handle = windll.kernel32.OpenProcess(process_query_information | process_vm_read, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        ok = windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if not ok:
            return None
        return int(counters.WorkingSetSize)
    finally:
        windll.kernel32.CloseHandle(handle)


def _proc_rss_bytes(pid: int) -> int | None:
    status_path = Path("/proc") / str(pid) / "status"
    if not status_path.exists():
        return None
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1]) * 1024
    return None


def _config_hash_if_present(experiment_dir: Path) -> str | None:
    config_path = experiment_dir / "config.yaml"
    if not config_path.exists():
        return None
    return file_hash(config_path)


def _positive_int(value: int, *, default: int) -> int:
    return value if value > 0 else default


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    return None
