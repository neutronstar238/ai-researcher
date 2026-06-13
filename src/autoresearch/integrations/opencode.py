"""OpenCode external code-agent integration metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class OpenCodeCodeAgentBackend:
    """Repository-tracked metadata for an OpenCode code-generation backend."""

    backend_id: str
    label: str
    runner_command: str
    upstream: str
    license: str
    provider_mode: str
    execution_modes: tuple[str, ...]
    project_files: tuple[str, ...]
    handoff_commands: tuple[str, ...]
    validation_gates: tuple[str, ...]
    approval_gates: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        data = asdict(self)
        for field in (
            "execution_modes",
            "project_files",
            "handoff_commands",
            "validation_gates",
            "approval_gates",
            "notes",
        ):
            data[field] = list(data[field])
        return data


OPENCODE_CODE_AGENT_BACKENDS: tuple[OpenCodeCodeAgentBackend, ...] = (
    OpenCodeCodeAgentBackend(
        backend_id="opencode-direct",
        label="OpenCode direct external code-writing backend",
        runner_command="opencode",
        upstream="https://github.com/anomalyco/opencode",
        license="MIT",
        provider_mode="OpenCode auth/env/.env provider configuration",
        execution_modes=(
            "opencode run --dir <workspace> --agent build --model <provider/model> <prompt>",
            "opencode serve with authenticated attach/run clients",
            "opencode acp for editor or process clients speaking Agent Client Protocol",
        ),
        project_files=(
            ".opencode/commands/ai-researcher-implement.md",
            ".opencode/commands/ai-researcher-review.md",
            ".opencode/skills/ai-researcher-evidence-gate/SKILL.md",
            "AGENTS.md",
        ),
        handoff_commands=(
            "airesearcher: create or select a dedicated worktree and task scope",
            "opencode: draft the requested code change using the configured model provider",
            "airesearcher: capture git diff and generated artifacts before acceptance",
            "airesearcher: run focused validation, evidence gates, and release checks",
            "airesearcher: update Agent.md, Problem.md, Obsidian memory, and commit only after gates pass",
        ),
        validation_gates=(
            "git diff must be captured before acceptance",
            "ruff, mypy, and focused tests must pass for touched Python code",
            "real API/data smoke tests are required for external data surfaces",
            "paper/release claims must pass publication-audit and evidence-gate checks",
            "AI-Researcher owns merge, rollback, Obsidian issue notes, and Agent.md logging",
        ),
        approval_gates=(
            "OpenCode permission config should default to ask for bash/edit actions",
            "dangerous commands require `airesearcher runtime approve` in approve-dangerous mode",
            "`--dangerously-skip-permissions` is allowed only under an explicit allow-all operator policy",
            "provider credentials must stay in OpenCode auth storage, environment, or local .env files",
        ),
        notes=(
            "Do not vendor OpenCode source code in this repository for this integration.",
            "Prefer direct OpenCode run/serve/acp integration over cc-switch when OpenCode is the execution backend.",
            "OpenCode may write candidate code, but AI-Researcher remains the validator and release owner.",
            "Keep AI-Researcher config/.env as the deployment model source of truth when bridging providers.",
        ),
    ),
)


def iter_opencode_code_agent_backends() -> tuple[OpenCodeCodeAgentBackend, ...]:
    """Return OpenCode code-agent backend entries in deterministic order."""

    return OPENCODE_CODE_AGENT_BACKENDS


def get_opencode_code_agent_backend(backend_id: str) -> OpenCodeCodeAgentBackend:
    """Return one OpenCode backend by backend ID."""

    normalized = backend_id.casefold()
    for backend in OPENCODE_CODE_AGENT_BACKENDS:
        if normalized == backend.backend_id.casefold():
            return backend
    msg = f"unknown opencode code-agent backend: {backend_id}"
    raise KeyError(msg)


def opencode_code_agent_manifest_payload() -> dict[str, object]:
    """Build the checked-in OpenCode execution contract payload."""

    return {
        "schema_version": 1,
        "generated_for": "AI-Researcher",
        "purpose": (
            "Reference execution contract for using OpenCode directly as an "
            "external code-generation backend while keeping AI-Researcher "
            "responsible for validation, approval, and acceptance."
        ),
        "model_bridge": {
            "source_of_truth": "AI-Researcher config/.env plus OpenCode auth/env/.env",
            "provider_fields": ["base_url", "api_key", "model_name"],
            "opencode_role": (
                "Use OpenCode provider auth, environment variables, or project .env "
                "to call the selected provider/model for code drafting."
            ),
            "operator_caveat": (
                "Verify the provider/model with `opencode models` or a bounded live "
                "smoke before allowing an unattended code-writing loop."
            ),
        },
        "execution_contract": {
            "generation_owner": "OpenCode direct",
            "validation_owner": "AI-Researcher",
            "acceptance_policy": "generated diffs are proposals until AI-Researcher gates pass",
            "merge_policy": "AI-Researcher-owned commit after tests, logs, and Agent.md update",
            "rollback_policy": "AI-Researcher rollback or follow-up issue note on failed gates",
            "memory_policy": "write accepted findings and failures into the Obsidian vault",
        },
        "opencode_project_contract": {
            "install_options": [
                "npm i -g opencode-ai@latest",
                "scoop install opencode",
                "choco install opencode",
            ],
            "noninteractive_command": (
                "opencode run --dir <workspace> --agent build --model <provider/model> "
                "\"<bounded code task>\""
            ),
            "server_command": "opencode serve",
            "acp_command": "opencode acp",
            "recommended_permission": {
                "*": "ask",
                "bash": {
                    "*": "ask",
                    "git diff*": "allow",
                    "git status*": "allow",
                    "poetry run pytest*": "allow",
                    "poetry run ruff*": "allow",
                    "poetry run mypy*": "allow",
                    "rm *": "deny",
                    "Remove-Item *": "deny",
                },
                "edit": "ask",
                "webfetch": "ask",
                "websearch": "ask",
            },
            "project_files": [
                {
                    "path": ".opencode/commands/ai-researcher-implement.md",
                    "purpose": "Draft a scoped code change and stop before merge.",
                },
                {
                    "path": ".opencode/commands/ai-researcher-review.md",
                    "purpose": "Review a generated diff against tests and evidence gates.",
                },
                {
                    "path": ".opencode/skills/ai-researcher-evidence-gate/SKILL.md",
                    "purpose": "Load repository-specific validation, Obsidian, and release-gate rules.",
                },
            ],
        },
        "approval_bridge": {
            "local_state": ".airesearcher/runtime-approvals.json",
            "approve_command": "airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json",
            "list_command": "airesearcher runtime list --state .airesearcher/runtime-approvals.json",
            "runtime_command": "airesearcher serve --permission-mode approve-dangerous",
        },
        "security_notes": [
            "This manifest records integration metadata; it does not execute OpenCode.",
            "Never write provider API keys, OpenCode auth files, transcripts with secrets, or local .env values to git.",
            "Run OpenCode in a dedicated worktree or sandbox and inspect generated diffs before acceptance.",
            "Treat provider setup, shell execution, filesystem writes, and public release as approval-gated actions.",
        ],
        "backends": [backend.to_json_dict() for backend in OPENCODE_CODE_AGENT_BACKENDS],
    }


def write_opencode_code_agent_manifest(output_path: Path | str) -> Path:
    """Write the OpenCode code-agent manifest to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(opencode_code_agent_manifest_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
