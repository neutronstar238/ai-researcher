"""User-facing project authorization roles and permissions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProjectRole(str, Enum):
    """User role inside a project or across the local installation."""

    OWNER = "owner"
    MAINTAINER = "maintainer"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class ProjectPermission(str, Enum):
    """Permission names used by project-level authorization gates."""

    PROJECT_READ = "project_read"
    PROJECT_WRITE = "project_write"
    APPROVE_HIGH_COST_RUN = "approve_high_cost_run"
    APPROVE_FULL_PERMISSION_RUN = "approve_full_permission_run"
    APPROVE_PUBLICATION = "approve_publication"
    MANAGE_STRATEGIES = "manage_strategies"


_ROLE_PERMISSIONS: dict[ProjectRole, frozenset[ProjectPermission]] = {
    ProjectRole.OWNER: frozenset(ProjectPermission),
    ProjectRole.ADMIN: frozenset(ProjectPermission),
    ProjectRole.MAINTAINER: frozenset(
        {
            ProjectPermission.PROJECT_READ,
            ProjectPermission.PROJECT_WRITE,
            ProjectPermission.APPROVE_HIGH_COST_RUN,
            ProjectPermission.APPROVE_FULL_PERMISSION_RUN,
            ProjectPermission.MANAGE_STRATEGIES,
        }
    ),
    ProjectRole.RESEARCHER: frozenset(
        {
            ProjectPermission.PROJECT_READ,
            ProjectPermission.PROJECT_WRITE,
        }
    ),
    ProjectRole.REVIEWER: frozenset(
        {
            ProjectPermission.PROJECT_READ,
            ProjectPermission.APPROVE_PUBLICATION,
        }
    ),
}


@dataclass(frozen=True)
class ProjectMembership:
    """A user's role assignment for one project, or global admin access."""

    user_id: str
    role: ProjectRole
    project_id: str | None

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            msg = "user_id is required"
            raise ValueError(msg)
        if self.role is not ProjectRole.ADMIN and not self.project_id:
            msg = "non-admin roles require project_id"
            raise ValueError(msg)
        if self.project_id is not None and not self.project_id.strip():
            msg = "project_id cannot be blank"
            raise ValueError(msg)

    def applies_to(self, project_id: str) -> bool:
        """Return whether this membership applies to the target project."""

        if not project_id.strip():
            msg = "project_id is required"
            raise ValueError(msg)
        if self.role is ProjectRole.ADMIN and self.project_id is None:
            return True
        return self.project_id == project_id


@dataclass(frozen=True)
class ProjectAuthorizationPolicy:
    """Authorize project operations against explicit user memberships."""

    memberships: tuple[ProjectMembership, ...] = ()

    def can(
        self,
        user_id: str,
        permission: ProjectPermission,
        *,
        project_id: str,
    ) -> bool:
        """Return whether the user may perform the permission on the project."""

        return any(
            membership.user_id == user_id
            and membership.applies_to(project_id)
            and permission in permissions_for_role(membership.role)
            for membership in self.memberships
        )

    def authorize(
        self,
        user_id: str,
        permission: ProjectPermission,
        *,
        project_id: str,
    ) -> ProjectMembership:
        """Return the matching membership or raise PermissionError."""

        for membership in self.memberships:
            if (
                membership.user_id == user_id
                and membership.applies_to(project_id)
                and permission in permissions_for_role(membership.role)
            ):
                return membership

        msg = f"{user_id} cannot {permission.value} on project {project_id}"
        raise PermissionError(msg)


def permissions_for_role(role: ProjectRole) -> frozenset[ProjectPermission]:
    """Return the default permission set for a project role."""

    return _ROLE_PERMISSIONS[role]
