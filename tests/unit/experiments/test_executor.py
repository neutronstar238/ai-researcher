from pathlib import Path
from textwrap import dedent

import pytest

from autoresearch.experiments import execute_experiment_task, executor
from autoresearch.schemas import ExecutionStatus, ExperimentTask


def _task(timeout_seconds: int = 5) -> ExperimentTask:
    return ExperimentTask(
        id="task_demo",
        project_id="project-001",
        hypothesis_id="hypothesis_1",
        name="Demo task",
        description="Run a demo experiment.",
        entrypoint="experiments/hypothesis-1/run.py",
        config_path="experiments/hypothesis-1/config.yaml",
        metrics=["demo_score"],
        resource_budget={"cpu_time_seconds": timeout_seconds, "memory_mb": 256},
        timeout_seconds=timeout_seconds,
        expected_outputs=["metrics.json", "logs/run.log"],
    )


def test_execute_experiment_task_records_success(tmp_path: Path) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        from pathlib import Path

        print("hello from experiment")
        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        Path("artifacts").mkdir(exist_ok=True)
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert "hello from experiment" in run.stdout
    assert run.stderr == ""
    assert run.start_time is not None
    assert run.end_time is not None
    assert run.metrics_path == (tmp_path / "metrics.json").as_posix()
    assert run.artifact_uri == (tmp_path / "artifacts").as_posix()


def test_execute_experiment_task_records_nonzero_exit(tmp_path: Path) -> None:
    _write_run_py(
        tmp_path,
        """
        import sys

        sys.stderr.write("bad experiment")
        sys.exit(3)
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.FAILED
    assert run.exit_code == 3
    assert run.error_type == "NonZeroExit"
    assert "bad experiment" in run.stderr


def test_execute_experiment_task_blocks_unapproved_network_import(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        import socket
        from pathlib import Path

        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.FAILED
    assert run.exit_code is None
    assert run.error_type == "NetworkPreflightDenied"
    assert run.limit_violations == ["network_preflight"]
    assert "imports network module socket" in run.stderr
    assert not (tmp_path / "metrics.json").exists()
    assert run.metadata["network_preflight"]["approved"] is False


def test_execute_experiment_task_allows_approved_network_import(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        import socket
        from pathlib import Path

        print(socket.AF_INET)
        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        """,
    )
    task = _task().model_copy(
        update={
            "metadata": {
                "network_access_approved": True,
                "network_access_scope": "approved test socket import",
                "approved_network_domains": ["example.org"],
                "network_source_urls": ["https://example.org/data.csv"],
                "network_approval_mode": "approve-dangerous",
                "network_approval_id": "approval-001",
                "network_approved_by": "unit-test",
            }
        }
    )

    run = execute_experiment_task(tmp_path, task)

    assert run.status is ExecutionStatus.SUCCESS
    assert run.error_type is None
    preflight = run.metadata["network_preflight"]
    assert preflight["approved"] is True
    assert preflight["finding_count"] == 1
    assert preflight["network_access_scope"] == "approved test socket import"
    assert preflight["approved_network_domains"] == ["example.org"]
    assert preflight["network_source_urls"] == ["https://example.org/data.csv"]
    assert preflight["network_approval_mode"] == "approve-dangerous"
    assert preflight["network_approval_id"] == "approval-001"
    assert preflight["network_approved_by"] == "unit-test"


def test_execute_experiment_task_blocks_dangerous_static_finding(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        import subprocess
        from pathlib import Path

        subprocess.run(["curl", "https://example.org"], check=False)
        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.FAILED
    assert run.exit_code is None
    assert run.error_type == "StaticPreflightDenied"
    assert run.limit_violations == ["static_preflight"]
    assert "dangerous_command" in run.stderr
    assert not (tmp_path / "metrics.json").exists()
    assert run.metadata["static_preflight"]["finding_count"] >= 1


def test_execute_experiment_task_blocks_secret_static_finding(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        import os
        from pathlib import Path

        os.getenv("API_KEY")
        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.FAILED
    assert run.error_type == "StaticPreflightDenied"
    assert run.limit_violations == ["static_preflight"]
    assert "secret_read" in run.stderr
    assert not (tmp_path / "metrics.json").exists()


def test_execute_experiment_task_blocks_dynamic_network_import(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import json
        from pathlib import Path

        __import__("socket")
        Path("metrics.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
        """,
    )

    run = execute_experiment_task(tmp_path, _task())

    assert run.status is ExecutionStatus.FAILED
    assert run.error_type == "NetworkPreflightDenied"
    assert run.limit_violations == ["network_preflight"]
    assert "dynamically imports network module socket" in run.stderr
    assert not (tmp_path / "metrics.json").exists()


def test_execute_experiment_task_enforces_timeout_and_cleans_process(
    tmp_path: Path,
) -> None:
    _write_run_py(
        tmp_path,
        """
        import time

        time.sleep(10)
        """,
    )

    run = execute_experiment_task(tmp_path, _task(timeout_seconds=1))

    assert run.status is ExecutionStatus.TIMEOUT
    assert run.error_type == "TimeoutExpired"
    assert "timeout_seconds" in run.limit_violations
    assert run.end_time is not None


def test_execute_experiment_task_rejects_entrypoint_outside_sandbox(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()

    with pytest.raises(PermissionError):
        execute_experiment_task(experiment_dir, _task(), entrypoint=outside)


def test_windows_process_group_hides_child_console(monkeypatch) -> None:
    monkeypatch.setattr(executor.os, "name", "nt")
    monkeypatch.setattr(executor.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(executor.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    kwargs = executor._process_group_kwargs(_task())

    assert kwargs == {"creationflags": 0x08000200}


def _write_run_py(root: Path, source: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.py").write_text(dedent(source).strip() + "\n", encoding="utf-8")
