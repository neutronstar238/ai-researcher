from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import strategies as st

from autoresearch.knowledge import AgentRole, PermissionManager
from autoresearch.observability import AuditEventType, AuditLog

PROJECT_IDS = st.from_regex(r"[a-z][a-z0-9-]{1,12}", fullmatch=True)


@given(other_project_id=PROJECT_IDS.filter(lambda value: value != "own-project"))
def test_project_agent_cannot_write_another_project_directory(
    other_project_id: str,
) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        vault_root = tmp_path / "autoresearch-vault"
        target = vault_root / "projects" / other_project_id / "knowledge" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("original", encoding="utf-8")
        audit_log = AuditLog(tmp_path / "audit" / "audit.jsonl")
        manager = PermissionManager(vault_root, audit_log)

        with pytest.raises(PermissionError):
            manager.write_text(
                AgentRole.PROJECT_AGENT,
                Path("projects") / other_project_id / "knowledge" / "note.md",
                "changed",
                project_id="own-project",
                actor="project-agent",
            )

        events = audit_log.read_all()
        assert target.read_text(encoding="utf-8") == "original"
        assert len(events) == 1
        assert events[0].event_type is AuditEventType.PERMISSION_CHECK
        assert events[0].approved is False


@given(project_id=PROJECT_IDS)
def test_main_agent_has_universal_vault_write_access(project_id: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        vault_root = tmp_path / "autoresearch-vault"
        manager = PermissionManager(vault_root)
        exploration_path = Path("exploration") / "topics" / "note.md"
        project_path = Path("projects") / project_id / "knowledge" / "note.md"

        manager.write_text(AgentRole.MAIN_AGENT, exploration_path, "global")
        manager.write_text(AgentRole.MAIN_AGENT, project_path, "project")

        assert (vault_root / exploration_path).read_text(encoding="utf-8") == "global"
        assert (vault_root / project_path).read_text(encoding="utf-8") == "project"
