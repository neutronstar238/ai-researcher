"""Permission checks for Obsidian vault zones."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog


class AgentRole(str, Enum):
    MAIN_AGENT = "main_agent"
    FIXED_AGENT = "fixed_agent"
    PROJECT_AGENT = "project_agent"
    VALIDATOR_AGENT = "validator_agent"


class AccessMode(str, Enum):
    READ = "read"
    WRITE = "write"


class PermissionManager:
    """Check and enforce local vault read/write permissions."""

    def __init__(self, vault_root: Path | str, audit_log: AuditLog | None = None) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.audit_log = audit_log

    def can_read(
        self,
        role: AgentRole,
        relative_path: Path | str,
        *,
        project_id: str | None = None,
    ) -> bool:
        return self._can_access(role, AccessMode.READ, relative_path, project_id=project_id)

    def can_write(
        self,
        role: AgentRole,
        relative_path: Path | str,
        *,
        project_id: str | None = None,
    ) -> bool:
        return self._can_access(role, AccessMode.WRITE, relative_path, project_id=project_id)

    def write_text(
        self,
        role: AgentRole,
        relative_path: Path | str,
        content: str,
        *,
        project_id: str | None = None,
        actor: str | None = None,
    ) -> Path:
        target = self._resolve_inside_vault(relative_path)
        if not self.can_write(role, relative_path, project_id=project_id):
            self._record_denial(role, relative_path, AccessMode.WRITE, project_id=project_id, actor=actor)
            msg = f"{role.value} cannot write {Path(relative_path).as_posix()}"
            raise PermissionError(msg)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read_text(
        self,
        role: AgentRole,
        relative_path: Path | str,
        *,
        project_id: str | None = None,
    ) -> str:
        target = self._resolve_inside_vault(relative_path)
        if not self.can_read(role, relative_path, project_id=project_id):
            msg = f"{role.value} cannot read {Path(relative_path).as_posix()}"
            raise PermissionError(msg)

        return target.read_text(encoding="utf-8")

    def _can_access(
        self,
        role: AgentRole,
        mode: AccessMode,
        relative_path: Path | str,
        *,
        project_id: str | None,
    ) -> bool:
        try:
            target = self._resolve_inside_vault(relative_path)
        except ValueError:
            return False

        if role in {AgentRole.MAIN_AGENT, AgentRole.FIXED_AGENT}:
            return True

        zone, target_project_id = self._classify_path(target)
        if role is AgentRole.PROJECT_AGENT:
            if mode is AccessMode.READ and zone == "exploration":
                return True
            return zone == "project" and target_project_id == project_id

        if role is AgentRole.VALIDATOR_AGENT:
            return mode is AccessMode.READ

        return False

    def _resolve_inside_vault(self, relative_path: Path | str) -> Path:
        target = (self.vault_root / relative_path).resolve()
        if not target.is_relative_to(self.vault_root):
            msg = f"path escapes vault root: {relative_path}"
            raise ValueError(msg)
        return target

    def _classify_path(self, target: Path) -> tuple[str | None, str | None]:
        exploration_root = self.vault_root / "exploration"
        projects_root = self.vault_root / "projects"

        if target.is_relative_to(exploration_root):
            return "exploration", None
        if target.is_relative_to(projects_root):
            relative = target.relative_to(projects_root)
            if relative.parts:
                return "project", relative.parts[0]
        return None, None

    def _record_denial(
        self,
        role: AgentRole,
        relative_path: Path | str,
        mode: AccessMode,
        *,
        project_id: str | None,
        actor: str | None,
    ) -> None:
        if self.audit_log is None:
            return

        self.audit_log.append(
            AuditEvent(
                event_type=AuditEventType.PERMISSION_CHECK,
                actor=actor or role.value,
                action=f"denied {mode.value}",
                resource=Path(relative_path).as_posix(),
                project_id=project_id,
                approved=False,
                metadata={"role": role.value},
            )
        )
