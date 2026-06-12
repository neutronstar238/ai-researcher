import json
from pathlib import Path

from autoresearch.integrations import (
    ccswitch_code_agent_manifest_payload,
    get_ccswitch_code_agent_backend,
    iter_ccswitch_code_agent_backends,
    write_ccswitch_code_agent_manifest,
)


def test_ccswitch_backend_registry_keeps_ai_researcher_as_validator() -> None:
    backends = {backend.backend_id: backend for backend in iter_ccswitch_code_agent_backends()}

    backend = backends["claude-code-via-cc-switch"]

    assert backend.runner_command == "claude"
    assert backend.license == "MIT"
    assert "Claude Code" in backend.managed_tools
    assert "AI-Researcher owns merge" in " ".join(backend.validation_gates)
    assert "runtime approve" in " ".join(backend.approval_gates)


def test_ccswitch_manifest_contains_execution_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "cc-switch" / "code-agent.json"

    write_ccswitch_code_agent_manifest(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_contract"]["generation_owner"] == "Claude Code via cc-switch"
    assert payload["execution_contract"]["validation_owner"] == "AI-Researcher"
    assert payload["approval_bridge"]["runtime_command"] == (
        "airesearcher serve --permission-mode approve-dangerous"
    )
    assert payload["model_bridge"]["source_of_truth"] == "AI-Researcher config/.env"
    assert payload["backends"][0]["backend_id"] == "claude-code-via-cc-switch"


def test_ccswitch_backend_lookup_rejects_unknown_backend() -> None:
    assert get_ccswitch_code_agent_backend("claude-code-via-cc-switch").runner_command == "claude"

    try:
        get_ccswitch_code_agent_backend("missing")
    except KeyError as exc:
        assert "unknown cc-switch code-agent backend" in str(exc)
    else:
        raise AssertionError("missing backend lookup should fail")


def test_ccswitch_manifest_payload_is_json_serialisable() -> None:
    payload = ccswitch_code_agent_manifest_payload()

    text = json.dumps(payload, sort_keys=True)

    assert "cc-switch" in text
    assert "generated diffs are proposals" in text
