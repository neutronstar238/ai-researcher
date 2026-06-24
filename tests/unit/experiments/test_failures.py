from pathlib import Path
from textwrap import dedent

import pytest

from autoresearch.experiments import (
    classify_failure_category,
    classify_loop_engineering_failure_category,
    execute_experiment_task,
    record_failed_run_as_knowledge,
    update_recurring_failure_patterns,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
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


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("ModuleNotFoundError missing package", "dependency"),
        ("dataset csv schema mismatch", "data"),
        ("TimeoutExpired stderr exception", "runtime"),
        ("metric_presence missing metrics.json", "metric"),
        ("citation DOI reference mismatch", "citation"),
        ("sandbox permission access denied", "permission"),
        ("budget token GPU cost exceeded", "cost"),
        ("validation artifact_existence failed", "validation"),
        ("unlabeled issue", "unknown"),
    ],
)
def test_classify_failure_category_covers_representative_causes(
    text: str,
    category: str,
) -> None:
    assert classify_failure_category(text) == category


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Semantic Scholar 429 rate limit during retrieval", "source"),
        ("protocol schema missing research plan artifact", "protocol"),
        ("TimeoutExpired stderr exception", "execution"),
        ("metrics.json contains NaN outside bounds", "metric"),
        ("reproduction validator failed evidence check", "validation"),
        ("LLM review returned needs_revision", "review"),
        ("GPU budget and token quota exceeded", "cost"),
        ("sandbox approval required for secret access", "safety"),
        ("ModuleNotFoundError missing package", "execution"),
    ],
)
def test_classify_loop_engineering_failure_category_uses_plan_taxonomy(
    text: str,
    category: str,
) -> None:
    assert classify_loop_engineering_failure_category(text) == category


def test_update_recurring_failure_patterns_writes_shared_note(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    _write_failure_entry(
        store,
        "exploration/failure_patterns/failure_run_1.md",
        "failure_run_1",
        "TimeoutExpired in task",
        "Runtime timeout in stderr during experiment.",
    )
    _write_failure_entry(
        store,
        "exploration/failure_patterns/failure_run_2.md",
        "failure_run_2",
        "Runtime exception in task",
        "NonZeroExit stderr exception while running experiment.",
    )
    _write_failure_entry(
        store,
        "exploration/failure_patterns/failure_run_3.md",
        "failure_run_3",
        "Dataset issue",
        "CSV schema mismatch in dataset.",
    )

    patterns = update_recurring_failure_patterns(vault_root=tmp_path, min_occurrences=2)

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.category == "runtime"
    assert pattern.failure_entry_ids == ("failure_run_1", "failure_run_2")
    markdown = pattern.note_path.read_text(encoding="utf-8")
    assert "[[exploration/failure_patterns/failure_run_1]]" in markdown
    assert "[[exploration/failure_patterns/failure_run_2]]" in markdown
    assert "## Skill Extraction Feed" in markdown
    assert "## Strategy Proposal Feed" in markdown


def _write_failure_entry(
    store: MarkdownKnowledgeStore,
    relative_path: str,
    entry_id: str,
    title: str,
    body: str,
) -> None:
    store.write_entry(
        relative_path,
        KnowledgeEntry(
            entry_id=entry_id,
            entry_type=KnowledgeEntryType.FAILURE_CASE,
            zone=KnowledgeZone.EXPLORATION,
            title=title,
            tags=["failure-case"],
            keywords=["failure"],
            body=body,
        ),
    )
