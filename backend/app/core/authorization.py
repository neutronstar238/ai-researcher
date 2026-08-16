"""Project-role authorization matrix (spec §1.2).

Authorization is evaluated fail-closed. The matrix is a pure, unit-testable
mapping from role to granted capabilities; service-level checks additionally
enforce team/project membership (spec §19.1).
"""

from __future__ import annotations

from typing import Literal

ProjectRole = Literal["owner", "researcher", "reviewer", "guest"]

# Capability keys map directly to the §1.2 matrix rows.
CAPABILITIES = (
    "view",
    "comment",
    "edit_content",
    "upload",
    "run_experiment",
    "launch_agent",
    "approve",
    "manage_members",
    "archive_delete",
)

_ROLE_CAPABILITIES: dict[ProjectRole, frozenset[str]] = {
    "owner": frozenset(CAPABILITIES),
    "researcher": frozenset(
        {
            "view",
            "comment",
            "edit_content",
            "upload",
            "run_experiment",
            "launch_agent",
            "approve",  # 按授权：researcher 经授权可审批
        }
    ),
    "reviewer": frozenset({"view", "comment", "launch_agent", "approve"}),
    "guest": frozenset({"view"}),
}

ROLE_RANK: dict[ProjectRole, int] = {"guest": 0, "reviewer": 1, "researcher": 2, "owner": 3}


def is_role(value: str) -> bool:
    return value in _ROLE_CAPABILITIES


def can(role: ProjectRole, capability: str) -> bool:
    """Return whether ``role`` grants ``capability``. Unknown roles fail closed."""
    return capability in _ROLE_CAPABILITIES.get(role, frozenset())


def capabilities_of(role: ProjectRole) -> frozenset[str]:
    return _ROLE_CAPABILITIES.get(role, frozenset())
