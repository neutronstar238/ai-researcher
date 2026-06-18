from pathlib import Path

import pytest

from autoresearch.experiments import (
    generate_experiment_directory,
    quarantine_unsafe_experiment,
    review_generated_code,
)
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
    )


def test_generated_runner_passes_static_review(tmp_path: Path) -> None:
    experiment_dir = generate_experiment_directory(tmp_path, _task())

    result = review_generated_code(experiment_dir)

    assert result.approved
    assert result.findings == ()


@pytest.mark.parametrize(
    ("source", "category"),
    [
        (
            "import subprocess\nsubprocess.run(['rm', '-rf', '/'], check=False)\n"
            "Path('metrics.json').write_text('{}')\n",
            "dangerous_command",
        ),
        (
            "from pathlib import Path\nPath('../secrets.txt').read_text()\n"
            "Path('metrics.json').write_text('{}')\n",
            "path_traversal",
        ),
        (
            "import os\nos.getenv('API_KEY')\n"
            "Path('metrics.json').write_text('{}')\n",
            "secret_read",
        ),
        (
            "import requests\nPath('metrics.json').write_text('{}')\n",
            "unrestricted_network",
        ),
        (
            "__import__('socket')\nPath('metrics.json').write_text('{}')\n",
            "unrestricted_network",
        ),
        (
            "import importlib\nimportlib.import_module('subprocess')\n"
            "Path('metrics.json').write_text('{}')\n",
            "dangerous_command",
        ),
        (
            "command = 'powershell -Command Invoke-WebRequest https://example.org/data.csv'\n"
            "Path('metrics.json').write_text('{}')\n",
            "dangerous_command",
        ),
        ("print('done')\n", "missing_metric_write"),
    ],
)
def test_static_review_blocks_unsafe_generated_code(
    tmp_path: Path,
    source: str,
    category: str,
) -> None:
    (tmp_path / "run.py").write_text(source, encoding="utf-8")

    result = review_generated_code(tmp_path)

    assert not result.approved
    assert category in {finding.category for finding in result.findings}


def test_quarantine_writes_review_findings_for_unsafe_code(tmp_path: Path) -> None:
    (tmp_path / "run.py").write_text("import requests\n", encoding="utf-8")
    result = review_generated_code(tmp_path)

    findings_path = quarantine_unsafe_experiment(tmp_path, result)

    assert findings_path == tmp_path / "quarantine" / "review-findings.json"
    assert findings_path.is_file()
    assert (tmp_path / "QUARANTINED").is_file()
    assert "unrestricted_network" in findings_path.read_text(encoding="utf-8")
