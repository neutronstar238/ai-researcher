"""Rollback foundations for files and Obsidian knowledge entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from autoresearch.knowledge.entries import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.observability.audit import AuditEvent, AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard


class RollbackTargetType(str, Enum):
    """Rollback target categories supported by the local foundation."""

    CONFIG = "config"
    PROMPT = "prompt"
    WORKFLOW_TEMPLATE = "workflow_template"
    KNOWLEDGE_ENTRY = "knowledge_entry"
    STRATEGY_CARD = "strategy_card"


@dataclass(frozen=True)
class FileVersionSnapshot:
    """Versioned text-file snapshot."""

    version: int
    path: Path
    created_at: datetime
    content: str


@dataclass(frozen=True)
class RollbackResult:
    """Result of restoring a versioned target."""

    target_type: RollbackTargetType
    relative_path: str
    restored_version: int
    path: Path
    metadata: dict[str, str]


@dataclass(frozen=True)
class StrategyKnowledgeRecord:
    """Persisted strategy card knowledge entry."""

    strategy_id: str
    path: Path
    entry: KnowledgeEntry


class VersionedFileStore:
    """Version plain text files such as configs, prompts, and workflow templates."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.version_root = self.root / ".versions" / "files"

    def write_file(self, relative_path: Path | str, content: str) -> Path:
        safe_path = _safe_relative_path(relative_path)
        path = self.root / safe_path
        if path.exists():
            self._preserve_version(safe_path, path.read_text(encoding="utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def list_versions(self, relative_path: Path | str) -> tuple[FileVersionSnapshot, ...]:
        safe_path = _safe_relative_path(relative_path)
        snapshots = self._saved_versions(safe_path)
        current_path = self.root / safe_path
        if current_path.exists():
            snapshots.append(
                FileVersionSnapshot(
                    version=len(snapshots) + 1,
                    path=current_path,
                    created_at=datetime.fromtimestamp(current_path.stat().st_mtime, timezone.utc),
                    content=current_path.read_text(encoding="utf-8"),
                )
            )
        return tuple(snapshots)

    def rollback_file(
        self,
        relative_path: Path | str,
        version: int,
        *,
        target_type: RollbackTargetType = RollbackTargetType.CONFIG,
        reason: str | None = None,
        audit_log: AuditLog | None = None,
        actor: str = "system",
        verification_result: str = "not_run",
        run_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> RollbackResult:
        safe_path = _safe_relative_path(relative_path)
        snapshots = self.list_versions(safe_path)
        old_version = len(snapshots)
        selected = next((snapshot for snapshot in snapshots if snapshot.version == version), None)
        if selected is None:
            msg = f"version {version} does not exist for {safe_path.as_posix()}"
            raise ValueError(msg)

        target = self.root / safe_path
        if target.exists() and target != selected.path:
            self._preserve_version(safe_path, target.read_text(encoding="utf-8"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(selected.content, encoding="utf-8")
        result = RollbackResult(
            target_type=target_type,
            relative_path=safe_path.as_posix(),
            restored_version=version,
            path=target,
            metadata=_rollback_metadata(reason),
        )
        _record_rollback_audit(
            audit_log=audit_log,
            result=result,
            actor=actor,
            old_version=old_version,
            verification_result=verification_result,
            reason=reason,
            run_id=run_id,
            project_id=project_id,
            task_id=task_id,
        )
        return result

    def _preserve_version(self, relative_path: Path, content: str) -> Path:
        version = len(self._saved_versions(relative_path)) + 1
        path = self._version_dir(relative_path) / f"v{version:04d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = yaml.safe_dump(
            {
                "source_path": relative_path.as_posix(),
                "version": version,
                "created_at": _utc_now().isoformat(),
            },
            sort_keys=True,
        )
        path.write_text(f"---\n{metadata}---\n\n{content}", encoding="utf-8")
        return path

    def _saved_versions(self, relative_path: Path) -> list[FileVersionSnapshot]:
        version_dir = self._version_dir(relative_path)
        snapshots: list[FileVersionSnapshot] = []
        if not version_dir.exists():
            return snapshots
        for path in sorted(version_dir.glob("v*.txt")):
            metadata, content = _read_version_file(path)
            snapshots.append(
                FileVersionSnapshot(
                    version=int(str(metadata["version"])),
                    path=path,
                    created_at=datetime.fromisoformat(str(metadata["created_at"])),
                    content=content,
                )
            )
        return snapshots

    def _version_dir(self, relative_path: Path) -> Path:
        return self.version_root.joinpath(*relative_path.with_suffix("").parts)


def write_strategy_card_entry(
    *,
    vault_root: Path | str,
    strategy: StrategyCard,
    relative_path: Path | str | None = None,
    title: str | None = None,
    rationale: str = "",
    linked_refs: tuple[str, ...] = (),
) -> StrategyKnowledgeRecord:
    """Store a strategy card as versioned Obsidian Markdown."""

    store = MarkdownKnowledgeStore(vault_root)
    path = (
        _safe_relative_path(relative_path)
        if relative_path is not None
        else Path("exploration") / "strategy_cards" / f"{strategy.id}.md"
    )
    entry = KnowledgeEntry(
        entry_id=strategy.id,
        entry_type=KnowledgeEntryType.STRATEGY_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title=title or f"{strategy.strategy_type} strategy v{strategy.version}",
        tags=["strategy-card", strategy.strategy_type, strategy.release_status],
        keywords=_strategy_keywords(strategy),
        source_refs=_strategy_source_refs(strategy, linked_refs),
        body=_strategy_body(strategy, rationale, linked_refs),
    )
    written_path = store.write_entry(path, entry)
    return StrategyKnowledgeRecord(
        strategy_id=strategy.id,
        path=written_path,
        entry=store.read_entry(path),
    )


def rollback_knowledge_entry(
    *,
    vault_root: Path | str,
    relative_path: Path | str,
    version: int,
    reason: str | None = None,
    audit_log: AuditLog | None = None,
    actor: str = "system",
    verification_result: str = "not_run",
    run_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
) -> RollbackResult:
    """Rollback any Obsidian knowledge entry to a previous Markdown version."""

    store = MarkdownKnowledgeStore(vault_root)
    safe_path = _safe_relative_path(relative_path)
    old_version = len(store.list_versions(safe_path))
    path = store.rollback(safe_path, version)
    result = RollbackResult(
        target_type=RollbackTargetType.KNOWLEDGE_ENTRY,
        relative_path=safe_path.as_posix(),
        restored_version=version,
        path=path,
        metadata=_rollback_metadata(reason),
    )
    _record_rollback_audit(
        audit_log=audit_log,
        result=result,
        actor=actor,
        old_version=old_version,
        verification_result=verification_result,
        reason=reason,
        run_id=run_id,
        project_id=project_id,
        task_id=task_id,
    )
    return result


def rollback_strategy_card(
    *,
    vault_root: Path | str,
    relative_path: Path | str,
    version: int,
    reason: str | None = None,
    audit_log: AuditLog | None = None,
    actor: str = "system",
    verification_result: str = "not_run",
    run_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
) -> RollbackResult:
    """Rollback an Obsidian strategy card and validate its restored entry type."""

    store = MarkdownKnowledgeStore(vault_root)
    safe_path = _safe_relative_path(relative_path)
    old_version = len(store.list_versions(safe_path))
    path = store.rollback(safe_path, version)
    entry = store.read_entry(safe_path)
    if entry.entry_type is not KnowledgeEntryType.STRATEGY_CARD:
        msg = f"{safe_path.as_posix()} is not a strategy card after rollback"
        raise ValueError(msg)
    result = RollbackResult(
        target_type=RollbackTargetType.STRATEGY_CARD,
        relative_path=safe_path.as_posix(),
        restored_version=version,
        path=path,
        metadata=_rollback_metadata(reason),
    )
    _record_rollback_audit(
        audit_log=audit_log,
        result=result,
        actor=actor,
        old_version=old_version,
        verification_result=verification_result,
        reason=reason,
        run_id=run_id,
        project_id=project_id,
        task_id=task_id,
    )
    return result


def _strategy_body(
    strategy: StrategyCard,
    rationale: str,
    linked_refs: tuple[str, ...],
) -> str:
    lines = [
        f"# Strategy {strategy.id}",
        "",
        f"- Strategy type: `{strategy.strategy_type}`",
        f"- Version: `{strategy.version}`",
        f"- Release status: `{strategy.release_status}`",
        f"- Evaluation score: `{strategy.evaluation_score if strategy.evaluation_score is not None else 'pending'}`",
        f"- Golden test status: `{strategy.golden_test_status.value}`",
        f"- Shadow status: `{strategy.shadow_status.value}`",
        f"- Parent strategy: `{strategy.parent_strategy_id or 'none'}`",
        f"- Rollback target: `{strategy.rollback_target or 'none'}`",
        "",
        "## Content",
        "",
        "```text",
        strategy.content,
        "```",
        "",
        "## Rollback Metadata",
        "",
        f"- Rollback target: `{strategy.rollback_target or 'none'}`",
        f"- Parent strategy: `{strategy.parent_strategy_id or 'none'}`",
        "",
        "## Linked Evidence",
        "",
        *_wiki_lines(linked_refs),
    ]
    if rationale:
        lines.extend(["", "## Rationale", "", rationale])
    return "\n".join(lines).rstrip() + "\n"


def _strategy_keywords(strategy: StrategyCard) -> list[str]:
    return sorted(
        {
            "strategy-card",
            strategy.strategy_type,
            strategy.release_status,
            strategy.golden_test_status.value,
            strategy.shadow_status.value,
            f"version-{strategy.version}",
            *(value for value in (strategy.parent_strategy_id, strategy.rollback_target) if value),
        }
    )


def _strategy_source_refs(strategy: StrategyCard, linked_refs: tuple[str, ...]) -> list[str]:
    refs = [
        *linked_refs,
        *(value for value in (strategy.parent_strategy_id, strategy.rollback_target) if value),
    ]
    return sorted(dict.fromkeys(refs))


def _wiki_lines(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- [[{item.removesuffix('.md')}]]" for item in dict.fromkeys(items)]


def _rollback_metadata(reason: str | None) -> dict[str, str]:
    metadata = {"rolled_back_at": _utc_now().isoformat()}
    if reason:
        metadata["reason"] = reason
    return metadata


def _record_rollback_audit(
    *,
    audit_log: AuditLog | None,
    result: RollbackResult,
    actor: str,
    old_version: int,
    verification_result: str,
    reason: str | None,
    run_id: str | None,
    project_id: str | None,
    task_id: str | None,
) -> None:
    if audit_log is None:
        return
    if not verification_result:
        msg = "verification_result must not be empty when recording rollback audit"
        raise ValueError(msg)

    metadata: dict[str, Any] = {
        "rollback": True,
        "target_type": result.target_type.value,
        "old_version": old_version,
        "new_version": result.restored_version,
        "restored_version": result.restored_version,
        "verification_result": verification_result,
        "path": str(result.path),
    }
    if reason:
        metadata["reason"] = reason

    audit_log.append(
        AuditEvent(
            event_type=AuditEventType.ROLLBACK,
            actor=actor,
            action=f"rollback {result.target_type.value} to version {result.restored_version}",
            resource=result.relative_path,
            run_id=run_id,
            project_id=project_id,
            task_id=task_id,
            metadata=metadata,
        )
    )


def _safe_relative_path(path: Path | str) -> Path:
    value = Path(path)
    if value.is_absolute() or ".." in value.parts or value in {Path("."), Path("")}:
        msg = "relative_path must be a safe relative path"
        raise ValueError(msg)
    return value


def _read_version_file(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        msg = f"version file missing frontmatter: {path}"
        raise ValueError(msg)
    _, metadata_text, content = text.split("---\n", 2)
    metadata = yaml.safe_load(metadata_text) or {}
    if not isinstance(metadata, dict):
        msg = f"version metadata must be a mapping: {path}"
        raise ValueError(msg)
    if content.startswith("\n"):
        content = content[1:]
    return metadata, content


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
