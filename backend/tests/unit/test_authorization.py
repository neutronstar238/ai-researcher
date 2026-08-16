"""Authorization matrix tests (spec §1.2/§24 Phase 1 verification)."""

from __future__ import annotations

import pytest

from app.core.authorization import CAPABILITIES, can, capabilities_of, is_role


def test_owner_has_all_capabilities() -> None:
    assert capabilities_of("owner") == frozenset(CAPABILITIES)


def test_guest_is_view_only() -> None:
    assert can("guest", "view") is True
    assert can("guest", "edit_content") is False
    assert can("guest", "upload") is False
    assert can("guest", "run_experiment") is False
    assert can("guest", "launch_agent") is False
    assert can("guest", "approve") is False
    assert can("guest", "manage_members") is False
    assert can("guest", "archive_delete") is False


def test_researcher_can_edit_upload_run() -> None:
    for cap in ("view", "comment", "edit_content", "upload", "run_experiment", "launch_agent"):
        assert can("researcher", cap) is True, cap
    for cap in ("manage_members", "archive_delete"):
        assert can("researcher", cap) is False, cap


def test_reviewer_can_approve_but_not_edit() -> None:
    assert can("reviewer", "approve") is True
    assert can("reviewer", "launch_agent") is True
    assert can("reviewer", "edit_content") is False
    assert can("reviewer", "upload") is False
    assert can("reviewer", "run_experiment") is False
    assert can("reviewer", "manage_members") is False


def test_unknown_role_fails_closed() -> None:
    assert can("superuser", "view") is False  # type: ignore[arg-type]
    assert is_role("superuser") is False


def test_role_names_are_valid() -> None:
    for role in ("owner", "researcher", "reviewer", "guest"):
        assert is_role(role) is True


@pytest.mark.parametrize(
    ("role", "capability", "expected"),
    [
        ("owner", "archive_delete", True),
        ("researcher", "approve", True),
        ("reviewer", "comment", True),
        ("guest", "view", True),
        ("guest", "run_experiment", False),
        ("researcher", "manage_members", False),
    ],
)
def test_matrix_examples(role: str, capability: str, expected: bool) -> None:
    assert can(role, capability) is expected  # type: ignore[arg-type]
