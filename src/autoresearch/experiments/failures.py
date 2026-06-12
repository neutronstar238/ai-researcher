"""Persist failed experiment runs as Obsidian knowledge entries."""

from __future__ import annotations

import platform
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from autoresearch.experiments.validation import ValidationReport
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.schemas import ExecutionRun, ExecutionStatus, ExperimentTask

FAILURE_CATEGORIES = (
    "dependency",
    "data",
    "runtime",
    "metric",
    "citation",
    "permission",
    "cost",
    "validation",
    "unknown",
)
CATEGORY_TERMS = {
    "dependency": (
        "importerror",
        "modulenotfounderror",
        "dependency",
        "package",
        "pip",
        "poetry",
    ),
    "data": (
        "csv",
        "data",
        "dataset",
        "file not found",
        "filenotfounderror",
        "schema",
    ),
    "runtime": (
        "nonzeroexit",
        "runtime",
        "timeoutexpired",
        "memorylimitexceeded",
        "exception",
        "stderr",
        "timeout",
    ),
    "metric": (
        "metric",
        "metrics.json",
        "metric_presence",
        "metric_bounds",
    ),
    "citation": (
        "bibtex",
        "citation",
        "doi",
        "reference",
    ),
    "permission": (
        "permission",
        "sandbox",
        "access denied",
        "unauthorized",
    ),
    "cost": (
        "budget",
        "cost",
        "gpu",
        "token",
    ),
    "validation": (
        "validation",
        "validator",
        "artifact_existence",
        "config_hash",
    ),
}


@dataclass(frozen=True)
class FailureKnowledgeRecord:
    """Paths written for one failed run knowledge record."""

    failure_id: str
    global_failure_path: Path
    project_issue_path: Path


@dataclass(frozen=True)
class RecurringFailurePattern:
    """One repeated failure category persisted for skill and strategy extraction."""

    pattern_id: str
    category: str
    failure_entry_ids: tuple[str, ...]
    failure_paths: tuple[str, ...]
    note_path: Path


def record_failed_run_as_knowledge(
    *,
    run: ExecutionRun,
    task: ExperimentTask,
    vault_root: Path | str,
    experiment_dir: Path | str | None = None,
    validation_report: ValidationReport | None = None,
    suspected_cause: str | None = None,
    skill_refs: tuple[str, ...] = (),
    strategy_refs: tuple[str, ...] = (),
    environment: dict[str, str] | None = None,
) -> FailureKnowledgeRecord:
    """Write global and project-local Obsidian notes for a failed run."""

    if run.status is ExecutionStatus.SUCCESS:
        msg = "only failed, timed out, cancelled, or blocked runs can be recorded as failures"
        raise ValueError(msg)
    if run.project_id != task.project_id:
        msg = "run project_id does not match task project_id"
        raise ValueError(msg)
    if run.task_id != task.id:
        msg = "run task_id does not match task id"
        raise ValueError(msg)

    failure_id = _failure_id(run)
    root = Path(vault_root)
    store = MarkdownKnowledgeStore(root)
    experiment_root = Path(experiment_dir) if experiment_dir is not None else None
    log_refs = _log_refs(experiment_root)
    config_ref = _config_ref(experiment_root, task)
    env = _environment(environment)
    cause = suspected_cause or _suspected_cause(run, validation_report)

    global_relative = Path("exploration") / "failure_patterns" / f"{failure_id}.md"
    issue_relative = Path("projects") / task.project_id / "issues" / f"{failure_id}.md"
    source_refs = _source_refs(run, validation_report, log_refs, config_ref)

    global_entry = KnowledgeEntry(
        entry_id=failure_id,
        entry_type=KnowledgeEntryType.FAILURE_CASE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Failure pattern {run.error_type or run.status.value} for {task.id}",
        tags=["failure-case", run.status.value, run.error_type or "unknown-error"],
        keywords=sorted({"failure", task.id, task.hypothesis_id, run.error_type or run.status.value}),
        source_refs=source_refs,
        related_run_ids=[run.id],
        body=_global_failure_body(
            failure_id=failure_id,
            run=run,
            task=task,
            issue_relative=issue_relative,
            log_refs=log_refs,
            config_ref=config_ref,
            validation_report=validation_report,
            suspected_cause=cause,
            environment=env,
            skill_refs=skill_refs,
            strategy_refs=strategy_refs,
        ),
    )
    issue_entry = KnowledgeEntry(
        entry_id=f"{failure_id}_issue",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=task.project_id,
        title=f"Project issue for failed run {run.id}",
        tags=["project-issue", "failure-case", run.status.value],
        keywords=[task.id, run.id, run.error_type or run.status.value],
        source_refs=source_refs,
        related_run_ids=[run.id],
        body=_project_issue_body(
            failure_id=failure_id,
            global_relative=global_relative,
            run=run,
            task=task,
            validation_report=validation_report,
            suspected_cause=cause,
            skill_refs=skill_refs,
            strategy_refs=strategy_refs,
        ),
    )

    global_path = store.write_entry(global_relative, global_entry)
    issue_path = store.write_entry(issue_relative, issue_entry)
    return FailureKnowledgeRecord(
        failure_id=failure_id,
        global_failure_path=global_path,
        project_issue_path=issue_path,
    )


def classify_failure_category(text: str) -> str:
    """Classify a failure note into a coarse recurring-failure category."""

    normalized = text.casefold()
    for category in FAILURE_CATEGORIES:
        if category == "unknown":
            continue
        if any(term in normalized for term in CATEGORY_TERMS[category]):
            return category
    return "unknown"


def update_recurring_failure_patterns(
    *,
    vault_root: Path | str,
    min_occurrences: int = 2,
) -> list[RecurringFailurePattern]:
    """Group failure cases and update shared recurring-pattern notes."""

    if min_occurrences < 2:
        msg = "min_occurrences must be at least 2"
        raise ValueError(msg)

    root = Path(vault_root)
    store = MarkdownKnowledgeStore(root)
    groups: dict[str, list[tuple[str, str, KnowledgeEntry]]] = defaultdict(list)
    for relative_path, entry in _failure_entries(root):
        category = classify_failure_category(_entry_text(entry))
        groups[category].append((relative_path, category, entry))

    patterns: list[RecurringFailurePattern] = []
    for category, rows in sorted(groups.items()):
        if category == "unknown" or len(rows) < min_occurrences:
            continue
        failure_paths = tuple(row[0] for row in rows)
        failure_entry_ids = tuple(row[2].entry_id for row in rows)
        pattern_id = f"recurring_failure_{category}"
        note = KnowledgeEntry(
            entry_id=pattern_id,
            entry_type=KnowledgeEntryType.FAILURE_CASE,
            zone=KnowledgeZone.EXPLORATION,
            title=f"Recurring {category} failure pattern",
            tags=["failure-pattern", "recurring", category],
            keywords=["recurring-failure", category],
            source_refs=list(failure_entry_ids),
            body=_recurring_pattern_body(
                category=category,
                failure_paths=failure_paths,
                failure_entry_ids=failure_entry_ids,
            ),
        )
        relative_note = Path("exploration") / "failure_patterns" / f"{pattern_id}.md"
        note_path = store.write_entry(relative_note, note)
        patterns.append(
            RecurringFailurePattern(
                pattern_id=pattern_id,
                category=category,
                failure_entry_ids=failure_entry_ids,
                failure_paths=failure_paths,
                note_path=note_path,
            )
        )
    return patterns


def _global_failure_body(
    *,
    failure_id: str,
    run: ExecutionRun,
    task: ExperimentTask,
    issue_relative: Path,
    log_refs: tuple[str, ...],
    config_ref: str | None,
    validation_report: ValidationReport | None,
    suspected_cause: str,
    environment: dict[str, str],
    skill_refs: tuple[str, ...],
    strategy_refs: tuple[str, ...],
) -> str:
    lines = [
        f"# Failure pattern {failure_id}",
        "",
        f"- Project issue: [[{issue_relative.with_suffix('').as_posix()}]]",
        f"- Run: [[{run.id}]]",
        f"- Experiment task: [[{task.id}]]",
        f"- Hypothesis: [[{task.hypothesis_id}]]",
        f"- Status: `{run.status.value}`",
        f"- Error type: `{run.error_type or 'unknown'}`",
        f"- Evidence status: `{_evidence_status(run, validation_report)}`",
        "",
        "## Suspected Cause",
        "",
        suspected_cause,
        "",
        "## Logs",
        "",
        *_list_or_none(log_refs),
        "",
        "### Stdout",
        "",
        _code_block(run.stdout),
        "",
        "### Stderr",
        "",
        _code_block(run.stderr),
        "",
        "## Config",
        "",
        f"- Config path: `{task.config_path}`",
        f"- Config hash: `{run.config_hash or 'unknown'}`",
        f"- Config file: `{config_ref or 'unknown'}`",
        "",
        "## Environment",
        "",
        *[f"- `{key}`: `{value}`" for key, value in sorted(environment.items())],
        "",
        "## Task",
        "",
        f"- Entry point: `{task.entrypoint}`",
        f"- Metrics: {', '.join(f'`{metric}`' for metric in task.metrics)}",
        f"- Resource budget: `{task.resource_budget}`",
        "",
        "## Skills And Strategies To Review",
        "",
        *_linked_refs("Skills", skill_refs),
        *_linked_refs("Strategies", strategy_refs),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _project_issue_body(
    *,
    failure_id: str,
    global_relative: Path,
    run: ExecutionRun,
    task: ExperimentTask,
    validation_report: ValidationReport | None,
    suspected_cause: str,
    skill_refs: tuple[str, ...],
    strategy_refs: tuple[str, ...],
) -> str:
    lines = [
        f"# Project issue for failed run {run.id}",
        "",
        f"- Global failure pattern: [[{global_relative.with_suffix('').as_posix()}]]",
        f"- Run: [[{run.id}]]",
        f"- Experiment task: [[{task.id}]]",
        f"- Hypothesis: [[{task.hypothesis_id}]]",
        f"- Failure ID: `{failure_id}`",
        f"- Evidence status: `{_evidence_status(run, validation_report)}`",
        "",
        "## Suspected Cause",
        "",
        suspected_cause,
        "",
        "## Next Review Targets",
        "",
        *_linked_refs("Skills", skill_refs),
        *_linked_refs("Strategies", strategy_refs),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _recurring_pattern_body(
    *,
    category: str,
    failure_paths: tuple[str, ...],
    failure_entry_ids: tuple[str, ...],
) -> str:
    lines = [
        f"# Recurring {category} failure pattern",
        "",
        f"- Category: `{category}`",
        f"- Occurrences: `{len(failure_entry_ids)}`",
        "",
        "## Source Failures",
        "",
        *[f"- [[{path.removesuffix('.md')}]] (`{entry_id}`)" for path, entry_id in zip(failure_paths, failure_entry_ids, strict=True)],
        "",
        "## Skill Extraction Feed",
        "",
        f"- Candidate skill trigger: `{category} failure repeats across runs`",
        "- Candidate skill action: `inspect linked runs, logs, configs, and suspected causes before retrying`",
        "- Status: `pending extraction`",
        "",
        "## Strategy Proposal Feed",
        "",
        f"- Candidate strategy area: `{category}`",
        "- Proposal status: `pending shadow evaluation`",
        "- Safety note: strategy changes still require human review before release.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _failure_entries(vault_root: Path) -> tuple[tuple[str, KnowledgeEntry], ...]:
    root = vault_root / "exploration" / "failure_patterns"
    if not root.exists():
        return ()
    entries: list[tuple[str, KnowledgeEntry]] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(vault_root).as_posix()
        try:
            entry = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if entry.entry_type is KnowledgeEntryType.FAILURE_CASE and not entry.entry_id.startswith(
            "recurring_failure_"
        ):
            entries.append((relative, entry))
    return tuple(entries)


def _entry_text(entry: KnowledgeEntry) -> str:
    return " ".join(
        [
            entry.title,
            *entry.tags,
            *entry.keywords,
            *entry.source_refs,
            entry.body,
        ]
    )


def _failure_id(run: ExecutionRun) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", run.id).strip("_")
    return f"failure_{value or 'run'}"


def _source_refs(
    run: ExecutionRun,
    validation_report: ValidationReport | None,
    log_refs: tuple[str, ...],
    config_ref: str | None,
) -> list[str]:
    refs = [run.id, *log_refs]
    if config_ref is not None:
        refs.append(config_ref)
    if run.metrics_path is not None:
        refs.append(run.metrics_path)
    if validation_report is not None:
        refs.extend([validation_report.json_path, validation_report.markdown_path])
    return sorted(dict.fromkeys(refs))


def _log_refs(experiment_dir: Path | None) -> tuple[str, ...]:
    if experiment_dir is None:
        return ()
    logs_dir = experiment_dir / "logs"
    if not logs_dir.exists():
        return ()
    return tuple(
        path.relative_to(experiment_dir).as_posix()
        for path in sorted(logs_dir.rglob("*"))
        if path.is_file()
    )


def _config_ref(experiment_dir: Path | None, task: ExperimentTask) -> str | None:
    if experiment_dir is None:
        return None
    config_path = experiment_dir / task.config_path
    if not config_path.exists():
        fallback = experiment_dir / Path(task.config_path).name
        if not fallback.exists():
            return None
        config_path = fallback
    return config_path.relative_to(experiment_dir).as_posix()


def _environment(extra: dict[str, str] | None) -> dict[str, str]:
    environment = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    if extra is not None:
        environment.update(extra)
    return environment


def _suspected_cause(
    run: ExecutionRun,
    validation_report: ValidationReport | None,
) -> str:
    if run.error_type == "TimeoutExpired":
        return "The run exceeded `timeout_seconds`; inspect runtime complexity or budget sizing."
    if run.error_type == "MemoryLimitExceeded":
        return "The run exceeded `memory_mb`; inspect data size, batching, or memory budget."
    if run.error_type == "NonZeroExit":
        return "The entrypoint exited with a non-zero code; inspect stderr and generated logs."
    if validation_report is not None and validation_report.issues:
        first_issue = validation_report.issues[0]
        return f"Validation failed at `{first_issue.check}`: {first_issue.message}"
    return "Cause is `unknown`; requires human review."


def _evidence_status(
    run: ExecutionRun,
    validation_report: ValidationReport | None,
) -> str:
    if validation_report is not None:
        return validation_report.status.value
    return run.status.value


def _list_or_none(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- `{item}`" for item in items]


def _linked_refs(label: str, refs: tuple[str, ...]) -> list[str]:
    lines = [f"### {label}", ""]
    if not refs:
        lines.extend(["- None", ""])
        return lines
    lines.extend(f"- [[{ref}]]" for ref in refs)
    lines.append("")
    return lines


def _code_block(text: str) -> str:
    return "```text\n" + (text.strip() or "None") + "\n```"
