import pytest

from autoresearch.knowledge import (
    ProjectAuthorizationPolicy,
    ProjectMembership,
    ProjectPermission,
    ProjectRole,
    permissions_for_role,
)


def test_owner_and_admin_receive_all_project_permissions() -> None:
    all_permissions = set(ProjectPermission)

    assert permissions_for_role(ProjectRole.OWNER) == all_permissions
    assert permissions_for_role(ProjectRole.ADMIN) == all_permissions

    policy = ProjectAuthorizationPolicy(
        memberships=(
            ProjectMembership("owner@example.com", ProjectRole.OWNER, "project-a"),
            ProjectMembership("admin@example.com", ProjectRole.ADMIN, None),
        )
    )

    for permission in ProjectPermission:
        assert policy.can("owner@example.com", permission, project_id="project-a")
        assert policy.can("admin@example.com", permission, project_id="project-b")


def test_researcher_can_read_and_write_but_cannot_approve_sensitive_actions() -> None:
    policy = ProjectAuthorizationPolicy(
        memberships=(ProjectMembership("researcher@example.com", ProjectRole.RESEARCHER, "project-a"),)
    )

    assert policy.can("researcher@example.com", ProjectPermission.PROJECT_READ, project_id="project-a")
    assert policy.can("researcher@example.com", ProjectPermission.PROJECT_WRITE, project_id="project-a")
    assert not policy.can(
        "researcher@example.com",
        ProjectPermission.APPROVE_HIGH_COST_RUN,
        project_id="project-a",
    )
    assert not policy.can(
        "researcher@example.com",
        ProjectPermission.APPROVE_FULL_PERMISSION_RUN,
        project_id="project-a",
    )
    assert not policy.can(
        "researcher@example.com",
        ProjectPermission.APPROVE_PUBLICATION,
        project_id="project-a",
    )
    assert not policy.can(
        "researcher@example.com",
        ProjectPermission.MANAGE_STRATEGIES,
        project_id="project-a",
    )


def test_reviewer_can_read_and_approve_publication_only() -> None:
    policy = ProjectAuthorizationPolicy(
        memberships=(ProjectMembership("reviewer@example.com", ProjectRole.REVIEWER, "project-a"),)
    )

    assert policy.can("reviewer@example.com", ProjectPermission.PROJECT_READ, project_id="project-a")
    assert policy.can(
        "reviewer@example.com",
        ProjectPermission.APPROVE_PUBLICATION,
        project_id="project-a",
    )
    assert not policy.can("reviewer@example.com", ProjectPermission.PROJECT_WRITE, project_id="project-a")
    assert not policy.can(
        "reviewer@example.com",
        ProjectPermission.APPROVE_FULL_PERMISSION_RUN,
        project_id="project-a",
    )


def test_project_membership_is_scoped_to_its_project() -> None:
    policy = ProjectAuthorizationPolicy(
        memberships=(ProjectMembership("owner@example.com", ProjectRole.OWNER, "project-a"),)
    )

    assert policy.can("owner@example.com", ProjectPermission.PROJECT_WRITE, project_id="project-a")
    assert not policy.can("owner@example.com", ProjectPermission.PROJECT_WRITE, project_id="project-b")


def test_authorize_returns_matching_membership_and_rejects_denied_action() -> None:
    membership = ProjectMembership("maintainer@example.com", ProjectRole.MAINTAINER, "project-a")
    policy = ProjectAuthorizationPolicy(memberships=(membership,))

    assert (
        policy.authorize(
            "maintainer@example.com",
            ProjectPermission.MANAGE_STRATEGIES,
            project_id="project-a",
        )
        == membership
    )

    with pytest.raises(PermissionError, match="approve_publication"):
        policy.authorize(
            "maintainer@example.com",
            ProjectPermission.APPROVE_PUBLICATION,
            project_id="project-a",
        )


def test_non_admin_membership_requires_project_id() -> None:
    with pytest.raises(ValueError, match="non-admin roles require project_id"):
        ProjectMembership("owner@example.com", ProjectRole.OWNER, None)
