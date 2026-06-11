from pathlib import Path

import pytest

from autoresearch.experiments import (
    RestrictedNetworkPolicy,
    default_network_policy,
    network_enforcement_note,
)
from autoresearch.observability import AuditEventType, AuditLog


@pytest.mark.parametrize(
    "url",
    [
        "https://export.arxiv.org/api/query?search_query=cat:cs.AI",
        "https://api.semanticscholar.org/graph/v1/paper/search",
        "https://pypi.org/simple/pyyaml/",
        "https://files.pythonhosted.org/packages/example.tar.gz",
        "https://github.com/openai/openai-python",
        "https://raw.githubusercontent.com/org/repo/main/file.py",
    ],
)
def test_default_network_policy_allows_academic_and_package_sources(url: str) -> None:
    decision = default_network_policy().check(url)

    assert decision.allowed
    assert decision.reason is None


def test_restricted_network_policy_blocks_non_allowlisted_domain() -> None:
    decision = default_network_policy().check("https://example.com/data.json")

    assert not decision.allowed
    assert decision.domain == "example.com"
    assert decision.reason == "domain is not in the sandbox allowlist"


def test_restricted_network_policy_audits_blocked_request(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path / "audit" / "audit.jsonl")
    policy = RestrictedNetworkPolicy(allowed_domains=("arxiv.org",))

    with pytest.raises(PermissionError):
        policy.require_allowed(
            "https://example.com/data.json",
            audit_log=audit_log,
            actor="executor",
            project_id="project-001",
            task_id="task-001",
            run_id="run-001",
        )

    events = audit_log.read_all()
    assert len(events) == 1
    assert events[0].event_type is AuditEventType.SANDBOX_DENIAL
    assert events[0].approved is False
    assert events[0].resource == "example.com"
    assert events[0].metadata["enforcement"] == "preflight_only"
    assert events[0].metadata["os_enforcement_supported"] is False


def test_network_enforcement_note_documents_mvp_boundary() -> None:
    note = network_enforcement_note()

    assert "preflight/audit only" in note
    assert "OS-level" in note
