import json
from pathlib import Path

import pytest

from autoresearch.agents import (
    AgentMcpServerBinding,
    AgentProfile,
    McpApprovalPolicy,
    McpInvocationStatus,
    append_mcp_invocation_evidence,
    build_mcp_invocation_evidence,
    load_mcp_invocation_evidence,
    validate_mcp_invocation_evidence,
)


def test_mcp_invocation_evidence_records_hashes_without_raw_payload(
    tmp_path: Path,
) -> None:
    profile = _profile()
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    request_path.write_text(json.dumps({"query": "prototype classifier"}), encoding="utf-8")
    response_path.write_text(json.dumps({"records": 3}), encoding="utf-8")

    evidence = build_mcp_invocation_evidence(
        profile=profile,
        project_id="project_1",
        cycle_id="cycle_1",
        server_id="page-agent",
        tool_name="browser.search",
        status=McpInvocationStatus.SUCCESS,
        request_artifact=request_path,
        response_artifact=response_path,
        base_dir=tmp_path,
        runtime_approval_request_id="approval_1",
        result_summary="Search returned three source candidates.",
    )
    ledger = append_mcp_invocation_evidence(tmp_path / "ledger.jsonl", evidence)
    loaded = load_mcp_invocation_evidence(ledger)

    assert loaded == (evidence,)
    assert evidence.request_artifact_ref == "request.json"
    assert evidence.response_artifact_ref == "response.json"
    assert evidence.request_sha256
    assert evidence.response_sha256
    ledger_text = ledger.read_text(encoding="utf-8")
    assert "prototype classifier" not in ledger_text
    assert "records" not in ledger_text
    assert "scientific claims" in evidence.evidence_policy.casefold()


def test_mcp_invocation_validation_blocks_unassigned_tool(tmp_path: Path) -> None:
    profile = _profile()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    evidence = build_mcp_invocation_evidence(
        profile=profile,
        project_id="project_1",
        cycle_id="cycle_1",
        server_id="page-agent",
        tool_name="browser.search",
        status=McpInvocationStatus.BLOCKED,
        request_artifact=request_path,
        base_dir=tmp_path,
        result_summary="Blocked before execution.",
    ).model_copy(update={"tool_name": "browser.delete"})

    validation = validate_mcp_invocation_evidence(evidence, profile)

    assert validation.passed is False
    assert "allowlist" in validation.issues[0]


def test_mcp_invocation_success_requires_response_hash(tmp_path: Path) -> None:
    profile = _profile()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="response artifact hash"):
        build_mcp_invocation_evidence(
            profile=profile,
            project_id="project_1",
            cycle_id="cycle_1",
            server_id="page-agent",
            tool_name="browser.search",
            status=McpInvocationStatus.SUCCESS,
            request_artifact=request_path,
            base_dir=tmp_path,
            result_summary="No response should fail.",
        )


def test_allow_all_mcp_invocation_requires_operator_identity(tmp_path: Path) -> None:
    profile = AgentProfile(
        agent_id="operator-agent",
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="local-admin",
                command=("npx", "-y", "local-admin-mcp"),
                allowed_tools=("run_task",),
                approval_policy=McpApprovalPolicy.ALLOW_ALL,
            ),
        ),
    )
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    request_path.write_text("{}", encoding="utf-8")
    response_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="approval or operator identity"):
        build_mcp_invocation_evidence(
            profile=profile,
            project_id="project_1",
            cycle_id="cycle_1",
            server_id="local-admin",
            tool_name="run_task",
            status=McpInvocationStatus.SUCCESS,
            request_artifact=request_path,
            response_artifact=response_path,
            base_dir=tmp_path,
            result_summary="Admin action completed.",
        )


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="literature-agent",
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="page-agent",
                command=("npx", "-y", "page-agent"),
                allowed_tools=("browser.search", "browser.open"),
            ),
        ),
    )
