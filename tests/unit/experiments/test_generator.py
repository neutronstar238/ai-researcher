import json
import subprocess
import sys
from pathlib import Path

from autoresearch.experiments import generate_experiment_directory
from autoresearch.schemas import ExperimentTask


def _task() -> ExperimentTask:
    return ExperimentTask(
        id="task_demo",
        project_id="project-001",
        hypothesis_id="hypothesis_1",
        name="Demo task",
        description="Run a demo experiment.",
        entrypoint="experiments/hypothesis-1/run.py",
        config_path="experiments/hypothesis-1/config.yaml",
        metrics=["demo_score"],
        resource_budget={"cpu_time_seconds": 30, "memory_mb": 256},
        timeout_seconds=30,
        expected_outputs=["metrics.json", "logs/run.log"],
        metadata={
            "dataset_assumptions": {"dataset_ref": "local demo", "baseline": "baseline"},
            "validation_checks": ["metrics.json exists"],
        },
    )


def test_generate_experiment_directory_writes_required_files(tmp_path: Path) -> None:
    experiment_dir = generate_experiment_directory(tmp_path, _task())

    assert (experiment_dir / "README.md").is_file()
    assert (experiment_dir / "config.yaml").is_file()
    assert (experiment_dir / "requirements.txt").is_file()
    assert (experiment_dir / "run.py").is_file()
    assert (experiment_dir / "logs").is_dir()
    assert (experiment_dir / "artifacts").is_dir()
    assert "pyyaml" in (experiment_dir / "requirements.txt").read_text(
        encoding="utf-8"
    )


def test_generated_demo_experiment_runs_and_writes_metrics(tmp_path: Path) -> None:
    experiment_dir = generate_experiment_directory(tmp_path, _task())

    completed = subprocess.run(
        [sys.executable, "run.py"],
        cwd=experiment_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metrics = json.loads((experiment_dir / "metrics.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert metrics["status"] == "success"
    assert metrics["task_id"] == "task_demo"
    assert metrics["execution_scope"] == "regression_fixture"
    assert metrics["metrics"] == {"demo_score": 1.0}
    assert (experiment_dir / "logs" / "run.log").read_text(encoding="utf-8")


def test_generated_demo_experiment_writes_metrics_on_failure(tmp_path: Path) -> None:
    experiment_dir = generate_experiment_directory(tmp_path, _task())
    (experiment_dir / "config.yaml").write_text("metrics: [", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "run.py"],
        cwd=experiment_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metrics = json.loads((experiment_dir / "metrics.json").read_text(encoding="utf-8"))

    assert completed.returncode == 1
    assert metrics["status"] == "failed"
    assert metrics["error_type"]
    assert (experiment_dir / "logs" / "run.log").read_text(encoding="utf-8")
