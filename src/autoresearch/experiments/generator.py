"""Generate minimal runnable experiment directories."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any

import yaml

from autoresearch.schemas import ExperimentTask


def generate_experiment_directory(root: Path | str, task: ExperimentTask) -> Path:
    """Generate a regression fixture, never a production scientific experiment.

    The generated runner intentionally emits constant placeholder metrics.  Its
    explicit ``regression_fixture`` scope lets production evidence gates reject
    it even when files exist and the process exits successfully.
    """

    root_path = Path(root)
    experiment_dir = root_path / _experiment_dir_name(task)
    logs_dir = experiment_dir / "logs"
    artifacts_dir = experiment_dir / "artifacts"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    config = _task_config(task)
    _write_text(experiment_dir / "README.md", _readme(task))
    _write_text(experiment_dir / "requirements.txt", "pyyaml>=6.0\n")
    _write_text(experiment_dir / "config.yaml", yaml.safe_dump(config, sort_keys=True))
    _write_text(experiment_dir / "run.py", _run_py())
    return experiment_dir


def _experiment_dir_name(task: ExperimentTask) -> str:
    return Path(task.entrypoint).parent.name or _slugify(task.name)


def _task_config(task: ExperimentTask) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "hypothesis_id": task.hypothesis_id,
        "metrics": task.metrics,
        "dataset_assumptions": task.metadata.get("dataset_assumptions", {}),
        "validation_checks": task.metadata.get("validation_checks", []),
        "resource_budget": task.resource_budget,
        "execution_scope": "regression_fixture",
    }


def _readme(task: ExperimentTask) -> str:
    metrics = "\n".join(f"- `{metric}`" for metric in task.metrics)
    return textwrap.dedent(
        f"""\
        # {task.name}

        {task.description}

        ## Metrics

        {metrics}

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        """
    )


def _run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import json
        import sys
        from datetime import datetime, timezone
        from pathlib import Path

        import yaml


        def main() -> int:
            root = Path(__file__).resolve().parent
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            summary_path = artifacts_dir / "summary.md"

            try:
                config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
                metrics = {metric: 1.0 for metric in config["metrics"]}
                payload = {
                    "status": "success",
                    "task_id": config["task_id"],
                    "execution_scope": config["execution_scope"],
                    "metrics": metrics,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                log_path.write_text("experiment completed successfully\\n", encoding="utf-8")
                summary_path.write_text("# Experiment Summary\\n\\nDemo experiment completed.\\n", encoding="utf-8")
                metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                return 0
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "metrics": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                log_path.write_text(f"experiment failed: {type(exc).__name__}: {exc}\\n", encoding="utf-8")
                metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                return 1


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "experiment"
