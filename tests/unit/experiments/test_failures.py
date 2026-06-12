from pathlib import Path
from textwrap import dedent

import pytest

from autoresearch.experiments import execute_experiment_task, record_failed_run_as_knowledge
from autoresearch.knowledge import KnowledgeEntryType, MarkdownKnowledgeStore
from autoresearch.schemas import ExecutionRun, ExecutionStatus, ExperimentTask


def _task() -> ExperimentTask:
    return ExperimentTask(
        id="task_failure",
        project_id="project-001",
        hypothesis_id="hypothesis_1",
        name="Failure task",
        description="Run a failing experiment.",
        entrypoint="run.py",
        config_path="config.yaml",
        metrics=["score"],
        resource_budget={"cpu_time_seconds": 5, "memory_mb": 256},
        timeout_seconds=5,
        expected_outputs=["metrics.json", "logs/run.log"],
    )


def test_failed_demo_run_creates_failure_case_and_project_issue(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    (experiment_dir / "config.yaml").write_text("seed: 1\n", encoding="utf-8")
    (experiment_dir / "run.py").write_text(
        dedent(
            """
            import sys
            from pathlib import Path

            Path("logs").mkdir(exist_ok=True)
            Path("logs/run.log").write_text("model failed before metrics", encoding="utf-8")
            sys.stderr.write("bad experiment")
            raise SystemExit(3)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    task = _task()
    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")

    record = record_failed_run_as_knowledge(
        run=run,
        task=task,
        vault_root=tmp_path / "autoresearch-vault",
        experiment_dir=experiment_dir,
        skill_refs=("skill_failure_triage",),
        strategy_refs=("strategy_retry_budget",),
        environment={"dataset": "synthetic-demo"},
    )

    store = MarkdownKnowledgeStore(tmp_path / "autoresearch-vault")
    global_entry = store.read_entry(
        Path("exploration") / "failure_patterns" / f"{record.failure_id}.md"
    )
    issue_entry = store.read_entry(
        Path("projects") / "project-001" / "issues" / f"{record.failure_id}.md"
    )
    global_markdown = record.global_failure_path.read_text(encoding="utf-8")
    issue_markdown = record.project_issue_path.read_text(encoding="utf-8")

    assert run.status is ExecutionStatus.FAILED
    assert run.error_type == "NonZeroExit"
    assert global_entry.entry_type is KnowledgeEntryType.FAILURE_CASE
    assert issue_entry.entry_type is KnowledgeEntryType.ISSUE_NOTE
    assert record.global_failure_path.is_file()
    assert record.project_issue_path.is_file()
    assert f"[[projects/project-001/issues/{record.failure_id}]]" in global_markdown
    assert f"[[exploration/failure_patterns/{record.failure_id}]]" in issue_markdown
    assert f"[[{run.id}]]" in global_markdown
    assert "[[task_failure]]" in global_markdown
    assert "[[hypothesis_1]]" in global_markdown
    assert "NonZeroExit" in global_markdown
    assert "bad experiment" in global_markdown
    assert "logs/run.log" in global_markdown
    assert "config.yaml" in global_markdown
    assert "synthetic-demo" in global_markdown
    assert "[[skill_failure_triage]]" in global_markdown
    assert "[[strategy_retry_budget]]" in issue_markdown


def test_record_failed_run_rejects_successful_runs() -> None:
    task = _task()
    run = ExecutionRun(
        project_id=task.project_id,
        task_id=task.id,
        status=ExecutionStatus.SUCCESS,
    )

    with pytest.raises(ValueError, match="failed"):
        record_failed_run_as_knowledge(run=run, task=task, vault_root="vault")
