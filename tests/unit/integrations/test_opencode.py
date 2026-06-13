import json
from pathlib import Path

import pytest

from autoresearch.integrations.opencode import (
    get_opencode_code_agent_backend,
    iter_opencode_code_agent_backends,
    opencode_code_agent_manifest_payload,
    write_opencode_code_agent_manifest,
)


def test_opencode_backends_keep_airesearcher_as_validator() -> None:
    backends = {backend.backend_id: backend for backend in iter_opencode_code_agent_backends()}

    backend = backends["opencode-direct"]

    assert backend.runner_command == "opencode"
    assert backend.license == "MIT"
    assert "opencode run" in backend.execution_modes[0]
    assert "AI-Researcher owns merge" in " ".join(backend.validation_gates)


def test_opencode_manifest_payload_records_permissioned_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "opencode" / "code-agent.json"

    write_opencode_code_agent_manifest(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == opencode_code_agent_manifest_payload()
    assert payload["execution_contract"]["generation_owner"] == "OpenCode direct"
    assert payload["execution_contract"]["validation_owner"] == "AI-Researcher"
    assert payload["opencode_project_contract"]["server_command"] == "opencode serve"
    assert payload["opencode_project_contract"]["acp_command"] == "opencode acp"
    assert payload["opencode_project_contract"]["recommended_permission"]["*"] == "ask"
    assert payload["backends"][0]["backend_id"] == "opencode-direct"


def test_get_opencode_backend_accepts_case_insensitive_ids() -> None:
    backend = get_opencode_code_agent_backend("OpenCode-Direct")

    assert backend.runner_command == "opencode"


def test_get_opencode_backend_rejects_unknown_id() -> None:
    with pytest.raises(KeyError) as exc:
        get_opencode_code_agent_backend("unknown")

    assert "unknown opencode code-agent backend" in str(exc)


def test_opencode_manifest_contains_no_secret_placeholders(tmp_path: Path) -> None:
    output = tmp_path / "code-agent.json"

    write_opencode_code_agent_manifest(output)

    text = output.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "api_key" in text
    assert "Never write provider API keys" in text
