from pathlib import Path

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    RollbackTargetType,
    VersionedFileStore,
    rollback_knowledge_entry,
    rollback_strategy_card,
    write_strategy_card_entry,
)
from autoresearch.observability import AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_versioned_file_store_rolls_back_config(tmp_path: Path) -> None:
    store = VersionedFileStore(tmp_path)
    relative_path = "configs/system.yaml"

    store.write_file(relative_path, "model: small\n")
    store.write_file(relative_path, "model: large\n")

    versions = store.list_versions(relative_path)
    result = store.rollback_file(
        relative_path,
        1,
        target_type=RollbackTargetType.CONFIG,
        reason="restore stable config",
    )

    assert len(versions) == 2
    assert versions[0].content == "model: small\n"
    assert result.target_type is RollbackTargetType.CONFIG
    assert result.metadata["reason"] == "restore stable config"
    assert (tmp_path / relative_path).read_text(encoding="utf-8") == "model: small\n"


def test_rollback_writes_audit_event_to_canonical_journal(tmp_path: Path) -> None:
    store = VersionedFileStore(tmp_path)
    audit_log = AuditLog(tmp_path / "audit" / "audit.jsonl")
    relative_path = "configs/system.yaml"

    store.write_file(relative_path, "model: small\n")
    store.write_file(relative_path, "model: large\n")

    store.rollback_file(
        relative_path,
        1,
        target_type=RollbackTargetType.CONFIG,
        reason="restore stable config",
        audit_log=audit_log,
        actor="rollback-agent",
        verification_result="passed",
        run_id="run_rollback_1",
        task_id="25.2",
    )

    events = audit_log.read_all()

    assert audit_log.journal_root.is_dir()
    assert not audit_log.path.exists()
    assert len(events) == 1
    assert events[0].event_type is AuditEventType.ROLLBACK
    assert events[0].actor == "rollback-agent"
    assert events[0].resource == relative_path
    assert events[0].run_id == "run_rollback_1"
    assert events[0].task_id == "25.2"
    assert events[0].metadata["rollback"] is True
    assert events[0].metadata["reason"] == "restore stable config"
    assert events[0].metadata["old_version"] == 2
    assert events[0].metadata["new_version"] == 1
    assert events[0].metadata["verification_result"] == "passed"
    assert events[0].metadata["target_type"] == RollbackTargetType.CONFIG.value


def test_strategy_card_versions_and_rolls_back_with_metadata(tmp_path: Path) -> None:
    relative_path = "exploration/strategy_cards/retrieval_policy.md"

    write_strategy_card_entry(
        vault_root=tmp_path,
        relative_path=relative_path,
        strategy=StrategyCard(
            id="strategy_retrieval_policy",
            strategy_type="retrieval_policy",
            version=1,
            content="Use conservative query expansion.",
            release_status="stable",
            shadow_status=ValidationStatus.PASSED,
        ),
        rationale="Stable baseline.",
        linked_refs=("exploration/failure_patterns/recurring_failure_citation",),
    )
    write_strategy_card_entry(
        vault_root=tmp_path,
        relative_path=relative_path,
        strategy=StrategyCard(
            id="strategy_retrieval_policy",
            strategy_type="retrieval_policy",
            version=2,
            content="Use aggressive query expansion.",
            parent_strategy_id="strategy_retrieval_policy_v1",
            rollback_target="strategy_retrieval_policy_v1",
            release_status="shadow",
            shadow_status=ValidationStatus.FAILED,
        ),
        rationale="Shadow candidate.",
    )

    result = rollback_strategy_card(
        vault_root=tmp_path,
        relative_path=relative_path,
        version=1,
        reason="shadow regression",
    )
    entry = MarkdownKnowledgeStore(tmp_path).read_entry(relative_path)

    assert result.target_type is RollbackTargetType.STRATEGY_CARD
    assert result.metadata["reason"] == "shadow regression"
    assert entry.entry_type is KnowledgeEntryType.STRATEGY_CARD
    assert "Use conservative query expansion." in entry.body
    assert "## Rollback Metadata" in entry.body
    assert "[[exploration/failure_patterns/recurring_failure_citation]]" in entry.body


def test_knowledge_entry_rollback_restores_fixture_note(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    relative_path = "projects/project_1/knowledge/note.md"

    store.write_entry(relative_path, _knowledge_entry("original finding"))
    store.write_entry(relative_path, _knowledge_entry("updated finding"))

    result = rollback_knowledge_entry(
        vault_root=tmp_path,
        relative_path=relative_path,
        version=1,
        reason="restore verified note",
    )
    entry = store.read_entry(relative_path)

    assert result.target_type is RollbackTargetType.KNOWLEDGE_ENTRY
    assert result.restored_version == 1
    assert entry.body == "original finding"


def _knowledge_entry(body: str) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id="knowledge_note",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id="project_1",
        title="Knowledge note",
        body=body,
    )
