"""Per-agent research profiles for custom skills and MCP bindings."""

from __future__ import annotations

import json
import re
import shlex
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autoresearch.knowledge import AgentRole

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SECRETISH_RE = re.compile(r"(sk-[A-Za-z0-9]|api[_-]?key=|secret=|token=)", re.IGNORECASE)

DEFAULT_RESEARCH_THINKING_CONTRACT: tuple[str, ...] = (
    "Start from the research question, falsifiable hypothesis, dataset, baseline, and evidence.",
    "Use engineering abstractions only when they make the scientific protocol more reproducible.",
    "Do not turn missing evidence into architectural language or invented conclusions.",
    "Treat custom skills as bounded methods/context, not as permission to bypass publication gates.",
    "Treat MCP tools as scoped instruments with explicit allowed tools and approval policy.",
)


class AgentThinkingMode(str, Enum):
    """How an agent should frame its reasoning before using tools."""

    SCIENTIFIC = "scientific"
    IMPLEMENTATION_SUPPORT = "implementation_support"
    REVIEWER = "reviewer"


class SkillSourceType(str, Enum):
    """Where a custom skill binding is sourced from."""

    LOCAL_PATH = "local_path"
    OBSIDIAN_NOTE = "obsidian_note"
    URL_REFERENCE = "url_reference"
    PACKAGE = "package"


class SkillImportPolicy(str, Enum):
    """How a skill may influence an agent."""

    READ_ONLY_CONTEXT = "read_only_context"
    SHADOW_EVALUATION = "shadow_evaluation"
    APPROVED_RUNTIME = "approved_runtime"


class McpApprovalPolicy(str, Enum):
    """Permission policy for a bound MCP server."""

    READ_ONLY = "read_only"
    APPROVE_DANGEROUS = "approve_dangerous"
    ALLOW_ALL = "allow_all"


class AgentSkillBinding(BaseModel):
    """One custom skill assigned to one agent profile."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    source: str
    source_type: SkillSourceType = SkillSourceType.LOCAL_PATH
    allowed_tasks: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    import_policy: SkillImportPolicy = SkillImportPolicy.READ_ONLY_CONTEXT
    notes: str | None = None

    @field_validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str) -> str:
        return _validate_identifier(value, "skill_id")

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "skill source must be non-empty"
            raise ValueError(msg)
        if _SECRETISH_RE.search(value):
            msg = "skill source must not contain inline secrets"
            raise ValueError(msg)
        return value

    @field_validator("allowed_tasks", "evidence_refs")
    @classmethod
    def _validate_text_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_text_tuple(value)


class AgentMcpServerBinding(BaseModel):
    """One MCP server assigned to one agent profile."""

    model_config = ConfigDict(extra="forbid")

    server_id: str
    command: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...] = Field(min_length=1)
    env_keys: tuple[str, ...] = ()
    approval_policy: McpApprovalPolicy = McpApprovalPolicy.APPROVE_DANGEROUS
    evidence_refs: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("server_id")
    @classmethod
    def _validate_server_id(cls, value: str) -> str:
        return _validate_identifier(value, "server_id")

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _clean_text_tuple(value)
        for token in cleaned:
            if _SECRETISH_RE.search(token):
                msg = "MCP command must not contain inline secrets; use env_keys instead"
                raise ValueError(msg)
        return cleaned

    @field_validator("allowed_tools")
    @classmethod
    def _validate_allowed_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_identifier(item, "allowed_tool") for item in value)

    @field_validator("env_keys")
    @classmethod
    def _validate_env_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _clean_text_tuple(value)
        for key in cleaned:
            if not _ENV_KEY_RE.match(key):
                msg = f"env key must be an uppercase environment variable name: {key}"
                raise ValueError(msg)
        return cleaned

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_text_tuple(value)


class AgentProfile(BaseModel):
    """Runtime profile that assigns custom skills and MCP tools to one agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: AgentRole = AgentRole.PROJECT_AGENT
    thinking_mode: AgentThinkingMode = AgentThinkingMode.SCIENTIFIC
    publication_target: str = "ccf-b-or-sci-q2"
    description: str | None = None
    assigned_stages: tuple[str, ...] = ()
    thinking_contract: tuple[str, ...] = DEFAULT_RESEARCH_THINKING_CONTRACT
    skills: tuple[AgentSkillBinding, ...] = ()
    mcp_servers: tuple[AgentMcpServerBinding, ...] = ()

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        return _validate_identifier(value, "agent_id")

    @field_validator("publication_target")
    @classmethod
    def _validate_publication_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "publication_target must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("assigned_stages")
    @classmethod
    def _validate_assigned_stages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            _validate_identifier(item.replace("-", "_").lower(), "assigned_stage")
            for item in _clean_text_tuple(value)
        )
        if len(normalized) != len(set(normalized)):
            msg = "assigned_stages must be unique after normalization"
            raise ValueError(msg)
        return normalized

    @field_validator("thinking_contract")
    @classmethod
    def _validate_thinking_contract(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _clean_text_tuple(value)
        if not cleaned:
            msg = "thinking_contract must contain at least one item"
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def _validate_profile(self) -> AgentProfile:
        if not self.skills and not self.mcp_servers:
            msg = "agent profile must bind at least one custom skill or MCP server"
            raise ValueError(msg)
        _reject_duplicates([skill.skill_id for skill in self.skills], "skill_id")
        _reject_duplicates([server.server_id for server in self.mcp_servers], "server_id")
        return self

    def to_runtime_context(self) -> dict[str, Any]:
        """Return a compact runtime context safe to attach to agent messages."""

        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "thinking_mode": self.thinking_mode.value,
            "publication_target": self.publication_target,
            "assigned_stages": list(self.assigned_stages),
            "thinking_contract": list(self.thinking_contract),
            "skills": [skill.model_dump(mode="json") for skill in self.skills],
            "mcp_servers": [
                {
                    "server_id": server.server_id,
                    "command": list(server.command),
                    "allowed_tools": list(server.allowed_tools),
                    "env_keys": list(server.env_keys),
                    "approval_policy": server.approval_policy.value,
                    "evidence_refs": list(server.evidence_refs),
                }
                for server in self.mcp_servers
            ],
        }


def infer_skill_source_type(source: str) -> SkillSourceType:
    """Infer the skill source type from a user-facing source string."""

    normalized = source.strip()
    if normalized.startswith(("http://", "https://")):
        return SkillSourceType.URL_REFERENCE
    if normalized.startswith("[[") and normalized.endswith("]]"):
        return SkillSourceType.OBSIDIAN_NOTE
    if "/" in normalized or "\\" in normalized or normalized.endswith(".md"):
        return SkillSourceType.LOCAL_PATH
    return SkillSourceType.PACKAGE


def parse_skill_spec(spec: str) -> AgentSkillBinding:
    """Parse `skill_id=source` into a skill binding."""

    skill_id, source = _split_assignment(spec, "skill")
    return AgentSkillBinding(
        skill_id=skill_id,
        source=source,
        source_type=infer_skill_source_type(source),
    )


def parse_mcp_spec(
    spec: str,
    *,
    tools_by_server: dict[str, tuple[str, ...]] | None = None,
) -> AgentMcpServerBinding:
    """Parse `server_id=command ...` into an MCP binding."""

    server_id, command_text = _split_assignment(spec, "MCP server")
    command = tuple(shlex.split(command_text, posix=False))
    allowed_tools = (tools_by_server or {}).get(server_id, ())
    return AgentMcpServerBinding(
        server_id=server_id,
        command=command,
        allowed_tools=allowed_tools,
    )


def parse_server_tool_specs(specs: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Parse repeated `server_id:tool_name` values."""

    tools: dict[str, list[str]] = {}
    for spec in specs:
        if ":" not in spec:
            msg = f"MCP tool spec must use server_id:tool_name: {spec}"
            raise ValueError(msg)
        server_id, tool = spec.split(":", 1)
        server_id = _validate_identifier(server_id, "server_id")
        tool = _validate_identifier(tool, "tool_name")
        tools.setdefault(server_id, []).append(tool)
    return {server_id: tuple(values) for server_id, values in tools.items()}


def write_agent_profile(profile: AgentProfile, path: Path | str) -> Path:
    """Write a profile JSON artifact."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_agent_profile(path: Path | str) -> AgentProfile:
    """Load and validate a profile JSON artifact."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return AgentProfile.model_validate(payload)


def render_agent_profile_markdown(profile: AgentProfile) -> str:
    """Render an Obsidian-friendly profile note."""

    lines = [
        f"# Agent Profile: {profile.agent_id}",
        "",
        f"- role: `{profile.role.value}`",
        f"- thinking_mode: `{profile.thinking_mode.value}`",
        f"- publication_target: `{profile.publication_target}`",
        "- assigned_stages: "
        + (", ".join(f"`{stage}`" for stage in profile.assigned_stages) or "`unassigned`"),
    ]
    if profile.description:
        lines.append(f"- description: {profile.description}")
    lines.extend(["", "## Research Thinking Contract", ""])
    lines.extend(f"- {item}" for item in profile.thinking_contract)
    lines.extend(["", "## Custom Skills", ""])
    if profile.skills:
        lines.append("| skill | source | policy | tasks |")
        lines.append("| --- | --- | --- | --- |")
        for skill in profile.skills:
            tasks = ", ".join(skill.allowed_tasks) if skill.allowed_tasks else "any assigned task"
            lines.append(
                f"| `{skill.skill_id}` | `{skill.source}` | `{skill.import_policy.value}` | {tasks} |"
            )
    else:
        lines.append("- No custom skills bound.")
    lines.extend(["", "## MCP Servers", ""])
    if profile.mcp_servers:
        lines.append("| server | command | allowed tools | approval | env keys |")
        lines.append("| --- | --- | --- | --- | --- |")
        for server in profile.mcp_servers:
            command = " ".join(server.command)
            tools = ", ".join(f"`{tool}`" for tool in server.allowed_tools)
            env_keys = ", ".join(f"`{key}`" for key in server.env_keys) or "none"
            lines.append(
                f"| `{server.server_id}` | `{command}` | {tools} | "
                f"`{server.approval_policy.value}` | {env_keys} |"
            )
    else:
        lines.append("- No MCP servers bound.")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- This profile imports context and tool contracts only; it does not alter safety, license, approval, or publication policy.",
            "- MCP secrets must stay in environment variables named in `env_keys`; never store secret values in this note.",
            "- Publication-level claims still require loop, review, publication-audit, evidence-gate, and reproduction gates.",
            "",
        ]
    )
    return "\n".join(lines)


def write_agent_profile_note(
    profile: AgentProfile,
    *,
    vault_root: Path | str,
    project_id: str,
) -> Path:
    """Write the profile into the project Obsidian area."""

    safe_project = _safe_path_part(project_id)
    target = Path(vault_root) / "projects" / safe_project / "agents" / f"{profile.agent_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_agent_profile_markdown(profile), encoding="utf-8")
    return target


def _split_assignment(spec: str, label: str) -> tuple[str, str]:
    if "=" not in spec:
        msg = f"{label} spec must use name=value: {spec}"
        raise ValueError(msg)
    name, value = spec.split("=", 1)
    return _validate_identifier(name, f"{label} id"), value.strip()


def _validate_identifier(value: str, field_name: str) -> str:
    value = value.strip()
    if not _ID_RE.match(value):
        msg = f"{field_name} must start with a letter or digit and contain only letters, digits, _, ., :, or -"
        raise ValueError(msg)
    return value


def _clean_text_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values if value.strip())
    if len(cleaned) != len(set(cleaned)):
        msg = "tuple values must be unique"
        raise ValueError(msg)
    return cleaned


def _reject_duplicates(values: list[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        msg = f"duplicate {field_name} values are not allowed"
        raise ValueError(msg)


def _safe_path_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    if not safe:
        msg = "project_id must contain at least one safe path character"
        raise ValueError(msg)
    return safe
