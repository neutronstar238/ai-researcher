"""cc-switch / Claude Code external code-agent integration metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CCSwitchCodeAgentBackend:
    """Repository-tracked metadata for an external code-generation backend."""

    backend_id: str
    label: str
    runner_command: str
    upstream: str
    license: str
    provider_mode: str
    managed_tools: tuple[str, ...]
    handoff_commands: tuple[str, ...]
    validation_gates: tuple[str, ...]
    approval_gates: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        data = asdict(self)
        for field in (
            "managed_tools",
            "handoff_commands",
            "validation_gates",
            "approval_gates",
            "notes",
        ):
            data[field] = list(data[field])
        return data


CCSWITCH_CODE_AGENT_BACKENDS: tuple[CCSwitchCodeAgentBackend, ...] = (
    CCSwitchCodeAgentBackend(
        backend_id="claude-code-via-cc-switch",
        label="Claude Code through cc-switch provider routing",
        runner_command="claude",
        upstream="https://github.com/farion1231/cc-switch",
        license="MIT",
        provider_mode="cc-switch Universal Provider or local proxy",
        managed_tools=("Claude Code", "Codex", "OpenClaw", "Gemini CLI", "OpenCode"),
        handoff_commands=(
            "cc-switch: create or select a Universal Provider for the AI-Researcher model endpoint",
            "cc-switch: sync the provider to Claude Code",
            "claude: run the code-writing task inside an isolated AI-Researcher worktree",
            "airesearcher: capture the resulting diff, run validation gates, and decide acceptance",
        ),
        validation_gates=(
            "git diff must be captured before acceptance",
            "ruff, mypy, and focused tests must pass for touched Python code",
            "dangerous command use must be routed through runtime approval",
            "result claims must cite local evidence artifacts before reports are accepted",
            "AI-Researcher owns merge, rollback, Obsidian issue notes, and Agent.md logging",
        ),
        approval_gates=(
            "full-permission shell commands require `airesearcher runtime approve`",
            "provider/profile writes require operator confirmation during first deployment",
            "generated code cannot bypass publication audit or reproducibility checks",
        ),
        notes=(
            "Do not vendor cc-switch source code in this repository for this integration.",
            "Keep `.env` and AI-Researcher config as the source of truth for model base URL, key, and model name.",
            "cc-switch may mirror provider routing for Claude Code, but AI-Researcher remains the validator.",
            "Claude Code endpoint routing and model selection must be checked separately when using gateways.",
        ),
    ),
)


def iter_ccswitch_code_agent_backends() -> tuple[CCSwitchCodeAgentBackend, ...]:
    """Return cc-switch code-agent backend entries in deterministic order."""

    return CCSWITCH_CODE_AGENT_BACKENDS


def get_ccswitch_code_agent_backend(backend_id: str) -> CCSwitchCodeAgentBackend:
    """Return one cc-switch backend by backend ID."""

    normalized = backend_id.casefold()
    for backend in CCSWITCH_CODE_AGENT_BACKENDS:
        if normalized == backend.backend_id.casefold():
            return backend
    msg = f"unknown cc-switch code-agent backend: {backend_id}"
    raise KeyError(msg)


def ccswitch_code_agent_manifest_payload() -> dict[str, object]:
    """Build the checked-in cc-switch/Claude Code execution contract payload."""

    return {
        "schema_version": 1,
        "generated_for": "AI-Researcher",
        "purpose": (
            "Reference execution contract for using cc-switch provider routing and "
            "Claude Code as an external code-generation backend while keeping "
            "AI-Researcher responsible for validation and acceptance."
        ),
        "model_bridge": {
            "source_of_truth": "AI-Researcher config/.env",
            "provider_fields": ("base_url", "api_key", "model_name"),
            "cc_switch_role": (
                "Mirror or proxy the configured provider into Claude Code through a "
                "Universal Provider or local proxy."
            ),
            "claude_code_caveat": (
                "Endpoint routing and model selection are separate concerns; verify "
                "the selected model after cc-switch sync."
            ),
        },
        "execution_contract": {
            "generation_owner": "Claude Code via cc-switch",
            "validation_owner": "AI-Researcher",
            "acceptance_policy": "generated diffs are proposals until AI-Researcher gates pass",
            "merge_policy": "AI-Researcher-owned commit after tests, logs, and Agent.md update",
            "rollback_policy": "AI-Researcher rollback or follow-up issue note on failed gates",
            "memory_policy": "write accepted findings and failures into the Obsidian vault",
        },
        "approval_bridge": {
            "local_state": ".airesearcher/runtime-approvals.json",
            "approve_command": "airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json",
            "list_command": "airesearcher runtime list --state .airesearcher/runtime-approvals.json",
            "runtime_command": "airesearcher serve --permission-mode approve-dangerous",
        },
        "security_notes": [
            "This manifest records integration metadata; it does not execute Claude Code or cc-switch.",
            "Never write provider API keys, cc-switch exports, or Claude Code credentials to git.",
            "Run Claude Code in a dedicated worktree or sandbox and inspect generated diffs before acceptance.",
            "Treat provider sync, proxy takeover, shell execution, and public release as approval-gated actions.",
        ],
        "backends": [backend.to_json_dict() for backend in CCSWITCH_CODE_AGENT_BACKENDS],
    }


def write_ccswitch_code_agent_manifest(output_path: Path | str) -> Path:
    """Write the cc-switch code-agent manifest to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ccswitch_code_agent_manifest_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
