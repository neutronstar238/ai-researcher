import json
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.runtime import (
    RuntimeActionRisk,
    RuntimeApprovalStatus,
    RuntimePermissionMode,
    approve_runtime_request,
    ensure_runtime_approval,
    list_runtime_approval_requests,
    network_approval_metadata_from_decision,
)


def test_dangerous_runtime_action_waits_until_approved(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    requested_at = datetime(2026, 6, 12, 1, 2, 3, tzinfo=timezone.utc)

    first_decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        action_id="serve:autopilot-cycle:project_1:tabular_baseline",
        command="airesearcher serve --project-id project_1",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="run online discovery and local experiments",
        requested_at=requested_at,
    )
    second_decision = ensure_runtime_approval(
        state_path=state,
        mode="approve-dangerous",
        action_id="serve:autopilot-cycle:project_1:tabular_baseline",
        command="airesearcher serve --project-id project_1",
        risk="dangerous",
        reason="run online discovery and local experiments",
    )

    assert first_decision.allowed is False
    assert first_decision.request is not None
    assert second_decision.allowed is False
    assert second_decision.request is not None
    assert second_decision.request.request_id == first_decision.request.request_id
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(payload["requests"]) == 1
    assert payload["requests"][0]["status"] == "pending"

    approved = approve_runtime_request(state, "latest", approved_by="tester")
    final_decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        action_id="serve:autopilot-cycle:project_1:tabular_baseline",
        command="airesearcher serve --project-id project_1",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="run online discovery and local experiments",
    )

    assert approved.status is RuntimeApprovalStatus.APPROVED
    assert approved.resolved_by == "tester"
    assert final_decision.allowed is True
    assert final_decision.request is not None
    assert final_decision.request.status is RuntimeApprovalStatus.APPROVED
    assert list_runtime_approval_requests(state) == []
    assert len(list_runtime_approval_requests(state, include_completed=True)) == 1


def test_allow_all_runtime_mode_does_not_write_approval_state(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-approvals.json"

    decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.ALLOW_ALL,
        action_id="serve:autopilot-cycle:project_1:tabular_baseline",
        command="airesearcher serve --project-id project_1",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="trusted local deployment",
    )

    assert decision.allowed is True
    assert decision.request is None
    assert not state.exists()


def test_network_approval_metadata_uses_approved_request(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        action_id="network:uci-pendigits",
        command="download UCI pendigits",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="public benchmark download",
    )
    assert decision.request is not None
    approved = approve_runtime_request(
        state,
        decision.request.request_id,
        approved_by="operator",
    )
    approved_decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        action_id="network:uci-pendigits",
        command="download UCI pendigits",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="public benchmark download",
    )

    metadata = network_approval_metadata_from_decision(
        approved_decision,
        scope="public UCI dataset download",
        approved_network_domains=["archive.ics.uci.edu"],
        network_source_urls=["https://archive.ics.uci.edu/data.csv"],
    )

    assert approved.status is RuntimeApprovalStatus.APPROVED
    assert metadata == {
        "network_access_approved": True,
        "network_access_scope": "public UCI dataset download",
        "network_approval_mode": "approve-dangerous",
        "approved_network_domains": ["archive.ics.uci.edu"],
        "network_source_urls": ["https://archive.ics.uci.edu/data.csv"],
        "network_approval_id": approved.request_id,
        "network_approved_by": "operator",
    }


def test_network_approval_metadata_rejects_pending_decision(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    decision = ensure_runtime_approval(
        state_path=state,
        mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        action_id="network:pending",
        command="download pending dataset",
        risk=RuntimeActionRisk.DANGEROUS,
        reason="public benchmark download",
    )

    try:
        network_approval_metadata_from_decision(
            decision,
            scope="pending network download",
        )
    except ValueError as exc:
        assert "requires an allowed runtime decision" in str(exc)
    else:
        raise AssertionError("pending approval should not produce network metadata")
