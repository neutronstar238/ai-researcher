"""Per-agent research profiles for custom skills and MCP bindings."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

import toml
import yaml
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
PROFILE_RUNTIME_CONTEXT_KIND = "agent_profile_process_metadata"
PROFILE_RUNTIME_EVIDENCE_POLICY: dict[str, tuple[str, ...]] = {
    "can_support": (
        "agent responsibility boundaries",
        "available custom skill context",
        "available MCP tool context",
    ),
    "cannot_support": (
        "scientific results",
        "novelty claims",
        "benchmark metrics",
        "citation validity",
        "publication readiness",
        "tool invocation",
    ),
}
DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS = 12_000
SKILL_MATERIALIZATION_EVIDENCE_POLICY = (
    "Materialized skill context is process metadata for agent behavior only; it cannot "
    "support scientific results, novelty claims, benchmark metrics, citation validity, "
    "publication readiness, or proof that any tool was invoked."
)
MCP_RUNTIME_CONTRACT_KIND = "mcp_runtime_contract_process_metadata"
MCP_RUNTIME_CONTRACT_EVIDENCE_POLICY = (
    "MCP runtime contracts describe allowed tool context and approval requirements only; "
    "they do not prove a tool was invoked or that any scientific result, citation, novelty "
    "claim, benchmark metric, or publication-readiness claim is supported."
)
PROFILE_SET_VALIDATION_KIND = "agent_profile_set_process_metadata"
PROFILE_SET_EVIDENCE_POLICY = (
    "Agent profile set validation proves only that a declared research-agent team has "
    "stage coverage, readiness, and bounded skill/MCP responsibility metadata. It cannot "
    "support scientific results, novelty claims, benchmark metrics, citation validity, "
    "tool invocation, or publication readiness without validated literature, experiment, "
    "reproduction, review, and evidence-gate artifacts."
)
STAGE_CONTEXT_PACKET_KIND = "agent_stage_context_packet_process_metadata"
STAGE_CONTEXT_PACKET_EVIDENCE_POLICY = (
    "Agent stage context packets route bounded skill context and MCP runtime contracts "
    "to agents assigned to one research-loop stage. They can support responsibility "
    "routing and runtime prompting only; they cannot prove scientific results, novelty "
    "claims, benchmark metrics, citation validity, tool invocation, or publication "
    "readiness without validated research artifacts."
)
STAGE_ASSIGNMENT_MANIFEST_KIND = "agent_stage_assignment_manifest_process_metadata"
STAGE_ASSIGNMENT_MANIFEST_EVIDENCE_POLICY = (
    "Agent stage assignment manifests summarize which Agents, custom skills, and MCP "
    "runtime contracts are routed to each research-loop stage. They can support "
    "auditability and responsibility routing only; they cannot prove scientific "
    "results, novelty claims, benchmark metrics, citation validity, tool invocation, "
    "or publication readiness."
)
DEFAULT_AGENT_PROFILE_SET_REQUIRED_STAGES: tuple[str, ...] = (
    "literature",
    "research_plan",
    "loop_campaign",
    "experiment",
    "reproduction",
    "citations",
    "review",
    "publication_audit",
    "evidence_gate",
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


class AgentProfileReadinessStatus(str, Enum):
    """Readiness status for a profile preflight check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class AgentSkillMaterializationStatus(str, Enum):
    """Whether a bound skill source was materialized for runtime context."""

    LOADED = "loaded"
    TRUNCATED = "truncated"
    REFERENCED = "referenced"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class AgentProfileReadinessCheck(BaseModel):
    """One deterministic readiness check for a bound skill or MCP server."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    status: AgentProfileReadinessStatus
    target: str
    message: str
    next_action: str | None = None


class AgentProfileReadinessReport(BaseModel):
    """Preflight report for custom skills and MCP bindings assigned to one agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    profile_path: str | None = None
    passed: bool
    check_count: int
    failed_check_count: int
    warning_count: int
    checks: tuple[AgentProfileReadinessCheck, ...]
    evidence_policy: str = (
        "Readiness checks verify profile inputs only; they do not prove scientific results, "
        "tool invocation, novelty, citation validity, or publication readiness."
    )


class AgentProfileStageCoverage(BaseModel):
    """Coverage details for one research-loop stage in an Agent profile set."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    covered: bool
    agent_ids: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    mcp_server_ids: tuple[str, ...] = ()


class AgentProfileSetValidation(BaseModel):
    """Team-level validation for a set of Agent profiles assigned to loop stages."""

    model_config = ConfigDict(extra="forbid")

    validation_kind: str = PROFILE_SET_VALIDATION_KIND
    passed: bool
    profile_count: int
    required_stages: tuple[str, ...]
    covered_stage_count: int
    missing_stages: tuple[str, ...]
    duplicate_agent_ids: tuple[str, ...] = ()
    readiness_failed_agent_ids: tuple[str, ...] = ()
    allow_all_agent_ids: tuple[str, ...] = ()
    non_scientific_contract_agent_ids: tuple[str, ...] = ()
    stage_coverage: tuple[AgentProfileStageCoverage, ...]
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_policy: str = PROFILE_SET_EVIDENCE_POLICY


class AgentSkillMaterializedContext(BaseModel):
    """Bounded content and provenance for one local skill source."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    source: str
    source_type: SkillSourceType
    import_policy: SkillImportPolicy
    status: AgentSkillMaterializationStatus
    resolved_path: str | None = None
    sha256: str | None = None
    byte_count: int | None = None
    char_count: int | None = None
    max_chars: int
    truncated: bool = False
    content: str | None = None
    message: str
    evidence_policy: str = SKILL_MATERIALIZATION_EVIDENCE_POLICY


class AgentMcpRuntimeContract(BaseModel):
    """Auditable runtime contract for one MCP server bound to an agent."""

    model_config = ConfigDict(extra="forbid")

    server_id: str
    contract_kind: str = MCP_RUNTIME_CONTRACT_KIND
    command_sha256: str
    command_token_count: int
    allowed_tools: tuple[str, ...]
    allowed_tool_count: int
    env_keys: tuple[str, ...] = ()
    env_key_count: int = 0
    env_values_recorded: bool = False
    approval_policy: McpApprovalPolicy
    runtime_approval_required: bool
    operator_isolation_required: bool
    tool_invocation_evidence_required: bool = True
    readiness_check_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    evidence_policy: str = MCP_RUNTIME_CONTRACT_EVIDENCE_POLICY


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


class AgentProfileBundleSkill(BaseModel):
    """Declarative skill entry used by reusable profile bundles."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    source: str
    source_type: SkillSourceType | None = None
    allowed_tasks: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    import_policy: SkillImportPolicy = SkillImportPolicy.READ_ONLY_CONTEXT
    notes: str | None = None


class AgentProfileBundleMcpServer(BaseModel):
    """Declarative MCP entry used by reusable profile bundles."""

    model_config = ConfigDict(extra="forbid")

    server_id: str
    command: str | tuple[str, ...]
    allowed_tools: tuple[str, ...]
    env_keys: tuple[str, ...] = ()
    approval_policy: McpApprovalPolicy = McpApprovalPolicy.APPROVE_DANGEROUS
    evidence_refs: tuple[str, ...] = ()
    notes: str | None = None


class AgentProfileBundle(BaseModel):
    """Reusable Agent profile declaration for JSON/YAML/TOML imports."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: AgentRole = AgentRole.PROJECT_AGENT
    thinking_mode: AgentThinkingMode = AgentThinkingMode.SCIENTIFIC
    publication_target: str = "ccf-b-or-sci-q2"
    description: str | None = None
    assigned_stages: tuple[str, ...] = ()
    thinking_contract_additions: tuple[str, ...] = ()
    skills: tuple[AgentProfileBundleSkill, ...] = ()
    mcp_servers: tuple[AgentProfileBundleMcpServer, ...] = ()

    @model_validator(mode="after")
    def _validate_bundle(self) -> AgentProfileBundle:
        if not self.skills and not self.mcp_servers:
            msg = "agent profile bundle must declare at least one skill or MCP server"
            raise ValueError(msg)
        return self


class AgentProfileSetBundle(BaseModel):
    """Reusable declaration for a stage-covered Agent profile team."""

    model_config = ConfigDict(extra="forbid")

    profile_set_id: str = "research-agent-team"
    description: str | None = None
    required_stages: tuple[str, ...] = DEFAULT_AGENT_PROFILE_SET_REQUIRED_STAGES
    profiles: tuple[AgentProfileBundle, ...]

    @field_validator("profile_set_id")
    @classmethod
    def _validate_profile_set_id(cls, value: str) -> str:
        return _validate_identifier(value, "profile_set_id")

    @field_validator("required_stages")
    @classmethod
    def _validate_required_stages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(normalize_profile_stage(stage) for stage in value))

    @model_validator(mode="after")
    def _validate_profile_set_bundle(self) -> AgentProfileSetBundle:
        if not self.profiles:
            msg = "agent profile set bundle must declare at least one profile"
            raise ValueError(msg)
        duplicate_agent_ids = _duplicate_values(profile.agent_id for profile in self.profiles)
        if duplicate_agent_ids:
            msg = "duplicate agent profile bundles: " + ", ".join(duplicate_agent_ids)
            raise ValueError(msg)
        return self


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

    def to_runtime_context(
        self,
        *,
        base_dir: Path | str | None = None,
        materialize_skills: bool = False,
        max_skill_chars: int = DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS,
    ) -> dict[str, Any]:
        """Return a compact runtime context safe to attach to agent messages."""

        context = {
            "agent_id": self.agent_id,
            "context_kind": PROFILE_RUNTIME_CONTEXT_KIND,
            "evidence_policy": {
                key: list(values)
                for key, values in PROFILE_RUNTIME_EVIDENCE_POLICY.items()
            },
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
            "mcp_runtime_contracts": [
                contract.model_dump(mode="json")
                for contract in build_agent_mcp_runtime_contracts(self)
            ],
        }
        if materialize_skills:
            context["materialized_skills"] = [
                skill_context.model_dump(mode="json")
                for skill_context in materialize_agent_skill_contexts(
                    self,
                    base_dir=base_dir,
                    max_chars=max_skill_chars,
                )
            ]
        return context


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


def parse_skill_policy_specs(specs: Iterable[str]) -> dict[str, SkillImportPolicy]:
    """Parse repeated `skill_id:policy` values for already-bound skills."""

    policies: dict[str, SkillImportPolicy] = {}
    for spec in specs:
        skill_id, policy_text = _split_scoped_value(spec, "skill policy")
        if skill_id in policies:
            msg = f"duplicate skill policy for {skill_id}"
            raise ValueError(msg)
        try:
            policies[skill_id] = SkillImportPolicy(policy_text)
        except ValueError as exc:
            choices = ", ".join(policy.value for policy in SkillImportPolicy)
            msg = f"unknown skill import policy for {skill_id}: {policy_text}; expected one of {choices}"
            raise ValueError(msg) from exc
    return policies


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


def parse_mcp_approval_policy_specs(specs: Iterable[str]) -> dict[str, McpApprovalPolicy]:
    """Parse repeated `server_id:policy` values for already-bound MCP servers."""

    policies: dict[str, McpApprovalPolicy] = {}
    for spec in specs:
        server_id, policy_text = _split_scoped_value(spec, "MCP approval policy")
        if server_id in policies:
            msg = f"duplicate MCP approval policy for {server_id}"
            raise ValueError(msg)
        try:
            policies[server_id] = McpApprovalPolicy(policy_text)
        except ValueError as exc:
            choices = ", ".join(policy.value for policy in McpApprovalPolicy)
            msg = f"unknown MCP approval policy for {server_id}: {policy_text}; expected one of {choices}"
            raise ValueError(msg) from exc
    return policies


def parse_mcp_env_key_specs(specs: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Parse repeated `server_id:ENV_KEY` values for already-bound MCP servers."""

    env_keys: dict[str, list[str]] = {}
    for spec in specs:
        server_id, env_key = _split_scoped_value(spec, "MCP env key")
        if not _ENV_KEY_RE.match(env_key):
            msg = f"MCP env key must be an uppercase environment variable name: {env_key}"
            raise ValueError(msg)
        values = env_keys.setdefault(server_id, [])
        if env_key not in values:
            values.append(env_key)
    return {server_id: tuple(values) for server_id, values in env_keys.items()}


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


def load_agent_profile_bundle(path: Path | str) -> AgentProfileBundle:
    """Load a declarative Agent profile bundle from JSON, YAML, or TOML."""

    bundle_path = Path(path)
    payload = _load_bundle_mapping(bundle_path)
    try:
        return AgentProfileBundle.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid agent profile bundle {bundle_path}: {exc}") from exc


def load_agent_profile_set_bundle(path: Path | str) -> AgentProfileSetBundle:
    """Load a declarative Agent profile-set bundle from JSON, YAML, or TOML."""

    bundle_path = Path(path)
    payload = _load_bundle_mapping(bundle_path)
    try:
        return AgentProfileSetBundle.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid agent profile set bundle {bundle_path}: {exc}") from exc


def build_agent_profile_from_bundle(bundle: AgentProfileBundle) -> AgentProfile:
    """Convert a declarative bundle into a runtime Agent profile."""

    skill_bindings = tuple(
        AgentSkillBinding(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type or infer_skill_source_type(skill.source),
            allowed_tasks=skill.allowed_tasks,
            evidence_refs=skill.evidence_refs,
            import_policy=skill.import_policy,
            notes=skill.notes,
        )
        for skill in bundle.skills
    )
    mcp_servers = tuple(
        AgentMcpServerBinding(
            server_id=server.server_id,
            command=_bundle_command_tokens(server.command),
            allowed_tools=server.allowed_tools,
            env_keys=server.env_keys,
            approval_policy=server.approval_policy,
            evidence_refs=server.evidence_refs,
            notes=server.notes,
        )
        for server in bundle.mcp_servers
    )
    thinking_contract = tuple(
        dict.fromkeys((*DEFAULT_RESEARCH_THINKING_CONTRACT, *bundle.thinking_contract_additions))
    )
    return AgentProfile(
        agent_id=bundle.agent_id,
        role=bundle.role,
        thinking_mode=bundle.thinking_mode,
        publication_target=bundle.publication_target,
        description=bundle.description,
        assigned_stages=bundle.assigned_stages,
        thinking_contract=thinking_contract,
        skills=skill_bindings,
        mcp_servers=mcp_servers,
    )


def build_agent_profiles_from_set_bundle(
    bundle: AgentProfileSetBundle,
) -> tuple[AgentProfile, ...]:
    """Convert a declarative profile-set bundle into runtime Agent profiles."""

    return tuple(build_agent_profile_from_bundle(profile) for profile in bundle.profiles)


def evaluate_agent_profile_readiness(
    profile: AgentProfile,
    *,
    profile_path: Path | str | None = None,
    base_dir: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> AgentProfileReadinessReport:
    """Check whether a profile's declared skill and MCP inputs are locally ready."""

    environment = env or {}
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    checks: list[AgentProfileReadinessCheck] = []
    for skill in profile.skills:
        checks.append(_skill_readiness_check(skill, base_dir=root))
    for server in profile.mcp_servers:
        checks.append(_mcp_env_readiness_check(server, env=environment))
        if server.approval_policy == McpApprovalPolicy.ALLOW_ALL:
            checks.append(
                AgentProfileReadinessCheck(
                    check_id=f"mcp_approval_policy:{server.server_id}",
                    status=AgentProfileReadinessStatus.WARN,
                    target=server.server_id,
                    message="MCP server declares allow_all approval policy.",
                    next_action=(
                        "Use allow_all only on isolated projects where full tool execution "
                        "has explicit operator approval."
                    ),
                )
            )
    failed_count = sum(1 for check in checks if check.status == AgentProfileReadinessStatus.FAIL)
    warning_count = sum(1 for check in checks if check.status == AgentProfileReadinessStatus.WARN)
    return AgentProfileReadinessReport(
        agent_id=profile.agent_id,
        profile_path=Path(profile_path).as_posix() if profile_path is not None else None,
        passed=failed_count == 0,
        check_count=len(checks),
        failed_check_count=failed_count,
        warning_count=warning_count,
        checks=tuple(checks),
    )


def materialize_agent_skill_contexts(
    profile: AgentProfile,
    *,
    base_dir: Path | str | None = None,
    max_chars: int = DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS,
) -> tuple[AgentSkillMaterializedContext, ...]:
    """Load bounded local skill content for a profile without treating it as evidence."""

    root = Path(base_dir) if base_dir is not None else Path.cwd()
    bounded_max_chars = max(0, max_chars)
    return tuple(
        _materialize_skill_context(skill, base_dir=root, max_chars=bounded_max_chars)
        for skill in profile.skills
    )


def build_agent_mcp_runtime_contracts(
    profile: AgentProfile,
) -> tuple[AgentMcpRuntimeContract, ...]:
    """Return process-metadata contracts for MCP servers assigned to one profile."""

    return tuple(_build_mcp_runtime_contract(server) for server in profile.mcp_servers)


def evaluate_agent_profile_set(
    profiles: Iterable[AgentProfile],
    *,
    required_stages: Iterable[str] = DEFAULT_AGENT_PROFILE_SET_REQUIRED_STAGES,
    readiness_reports: Iterable[AgentProfileReadinessReport] = (),
) -> AgentProfileSetValidation:
    """Validate a stage-scoped Agent team before unattended research-loop use."""

    profile_list = tuple(profiles)
    normalized_required_stages = _normalize_unique_stages(required_stages)
    duplicate_agent_ids = _duplicate_values(profile.agent_id for profile in profile_list)
    readiness_by_agent = {report.agent_id: report for report in readiness_reports}
    readiness_failed_agent_ids = tuple(
        profile.agent_id
        for profile in profile_list
        if (report := readiness_by_agent.get(profile.agent_id)) is not None and not report.passed
    )
    allow_all_agent_ids = tuple(
        profile.agent_id
        for profile in profile_list
        if any(server.approval_policy == McpApprovalPolicy.ALLOW_ALL for server in profile.mcp_servers)
    )
    non_scientific_contract_agent_ids = tuple(
        profile.agent_id
        for profile in profile_list
        if not _has_scientific_thinking_contract(profile.thinking_contract)
    )

    stage_coverage = tuple(
        _profile_stage_coverage(stage, profile_list) for stage in normalized_required_stages
    )
    missing_stages = tuple(row.stage for row in stage_coverage if not row.covered)
    failures = _profile_set_failures(
        missing_stages=missing_stages,
        duplicate_agent_ids=duplicate_agent_ids,
        readiness_failed_agent_ids=readiness_failed_agent_ids,
        non_scientific_contract_agent_ids=non_scientific_contract_agent_ids,
    )
    warnings = _profile_set_warnings(
        profiles=profile_list,
        allow_all_agent_ids=allow_all_agent_ids,
        readiness_by_agent=readiness_by_agent,
    )
    return AgentProfileSetValidation(
        passed=not failures,
        profile_count=len(profile_list),
        required_stages=normalized_required_stages,
        covered_stage_count=sum(1 for row in stage_coverage if row.covered),
        missing_stages=missing_stages,
        duplicate_agent_ids=duplicate_agent_ids,
        readiness_failed_agent_ids=readiness_failed_agent_ids,
        allow_all_agent_ids=allow_all_agent_ids,
        non_scientific_contract_agent_ids=non_scientific_contract_agent_ids,
        stage_coverage=stage_coverage,
        failures=failures,
        warnings=warnings,
    )


def normalize_profile_stage(stage: str) -> str:
    """Normalize a loop stage identifier used by an agent profile."""

    return _validate_identifier(stage.replace("-", "_").lower(), "assigned_stage")


def profile_contexts_for_stage(
    profile_contexts: Iterable[Mapping[str, Any]],
    stage: str,
) -> tuple[dict[str, Any], ...]:
    """Return safe runtime contexts assigned to one loop stage."""

    normalized_stage = normalize_profile_stage(stage)
    return tuple(
        dict(context)
        for context in profile_contexts
        if normalized_stage in _context_assigned_stages(context)
    )


def profile_contexts_by_stage(
    profile_contexts: Iterable[Mapping[str, Any]],
    stages: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """Group safe runtime contexts by loop stage."""

    contexts = tuple(profile_contexts)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        normalized_stage = normalize_profile_stage(stage)
        stage_contexts = profile_contexts_for_stage(contexts, normalized_stage)
        if stage_contexts:
            grouped[normalized_stage] = list(stage_contexts)
    return grouped


def build_agent_stage_context_packet(
    profile_contexts: Iterable[Mapping[str, Any]],
    stage: str,
    *,
    project_id: str | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Build a portable context packet for agents assigned to one loop stage."""

    normalized_stage = normalize_profile_stage(stage)
    stage_contexts = profile_contexts_for_stage(profile_contexts, normalized_stage)
    readiness_values = [
        value
        for value in (context.get("readiness") for context in stage_contexts)
        if isinstance(value, Mapping)
    ]
    failed_checks = sum(
        int(value.get("failed_check_count", 0) or 0) for value in readiness_values
    )
    warning_checks = sum(
        int(value.get("warning_count", 0) or 0) for value in readiness_values
    )
    skill_ids = _ordered_unique(
        str(skill.get("skill_id", ""))
        for context in stage_contexts
        for skill in _mapping_items(context.get("skills"))
        if str(skill.get("skill_id", "")).strip()
    )
    materialized_skill_ids = _ordered_unique(
        str(skill.get("skill_id", ""))
        for context in stage_contexts
        for skill in _mapping_items(context.get("materialized_skills"))
        if str(skill.get("skill_id", "")).strip()
    )
    mcp_server_ids = _ordered_unique(
        str(server.get("server_id", ""))
        for context in stage_contexts
        for server in _mapping_items(context.get("mcp_servers"))
        if str(server.get("server_id", "")).strip()
    )
    agent_ids = tuple(str(context.get("agent_id", "")) for context in stage_contexts)
    return {
        "packet_kind": STAGE_CONTEXT_PACKET_KIND,
        "stage": normalized_stage,
        "project_id": project_id,
        "cycle_id": cycle_id,
        "agent_count": len(stage_contexts),
        "agent_ids": list(agent_ids),
        "skill_ids": list(skill_ids),
        "materialized_skill_ids": list(materialized_skill_ids),
        "mcp_server_ids": list(mcp_server_ids),
        "readiness": {
            "passed": failed_checks == 0,
            "failed_check_count": failed_checks,
            "warning_count": warning_checks,
        },
        "agents": [dict(context) for context in stage_contexts],
        "missing_assignment": not stage_contexts,
        "evidence_policy": STAGE_CONTEXT_PACKET_EVIDENCE_POLICY,
    }


def build_agent_stage_assignment_manifest(
    profile_contexts: Iterable[Mapping[str, Any]],
    stages: Iterable[str],
    *,
    project_id: str | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Summarize Agent skill/MCP routing across research-loop stages."""

    contexts = tuple(dict(context) for context in profile_contexts)
    normalized_stages = _normalize_unique_stages(stages)
    stage_rows: list[dict[str, Any]] = []
    for stage in normalized_stages:
        stage_contexts = profile_contexts_for_stage(contexts, stage)
        if not stage_contexts:
            continue
        stage_rows.append(_agent_stage_assignment_row(stage, stage_contexts))

    agent_rows = [_agent_assignment_row(context) for context in contexts]
    return {
        "manifest_kind": STAGE_ASSIGNMENT_MANIFEST_KIND,
        "project_id": project_id,
        "cycle_id": cycle_id,
        "stage_count": len(stage_rows),
        "agent_count": len(contexts),
        "stages": stage_rows,
        "agent_assignments": agent_rows,
        "unassigned_agent_ids": [
            row["agent_id"]
            for row in agent_rows
            if not row["assigned_stages"]
        ],
        "manifest_path": None,
        "evidence_policy": STAGE_ASSIGNMENT_MANIFEST_EVIDENCE_POLICY,
    }


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


def _materialize_skill_context(
    skill: AgentSkillBinding,
    *,
    base_dir: Path,
    max_chars: int,
) -> AgentSkillMaterializedContext:
    if skill.source_type != SkillSourceType.LOCAL_PATH:
        return AgentSkillMaterializedContext(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type,
            import_policy=skill.import_policy,
            status=AgentSkillMaterializationStatus.REFERENCED,
            max_chars=max_chars,
            message=(
                f"{skill.source_type.value} skill source is referenced only; this "
                "local materializer does not fetch external or Obsidian note content."
            ),
        )

    resolved = _resolve_local_skill_source(skill.source, base_dir=base_dir)
    if not resolved.exists():
        return AgentSkillMaterializedContext(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type,
            import_policy=skill.import_policy,
            status=AgentSkillMaterializationStatus.MISSING,
            resolved_path=resolved.as_posix(),
            max_chars=max_chars,
            message=f"Local skill source is missing at {resolved.as_posix()}.",
        )
    if resolved.is_dir():
        skill_md = resolved / "SKILL.md"
        if skill_md.is_file():
            resolved = skill_md
        else:
            return AgentSkillMaterializedContext(
                skill_id=skill.skill_id,
                source=skill.source,
                source_type=skill.source_type,
                import_policy=skill.import_policy,
                status=AgentSkillMaterializationStatus.UNSUPPORTED,
                resolved_path=resolved.as_posix(),
                max_chars=max_chars,
                message=(
                    "Local skill source is a directory without a SKILL.md file, so no "
                    "bounded runtime content was materialized."
                ),
            )
    if not resolved.is_file():
        return AgentSkillMaterializedContext(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type,
            import_policy=skill.import_policy,
            status=AgentSkillMaterializationStatus.UNSUPPORTED,
            resolved_path=resolved.as_posix(),
            max_chars=max_chars,
            message="Local skill source is not a regular file.",
        )

    try:
        raw_content = resolved.read_bytes()
        content_text = raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return AgentSkillMaterializedContext(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type,
            import_policy=skill.import_policy,
            status=AgentSkillMaterializationStatus.UNSUPPORTED,
            resolved_path=resolved.as_posix(),
            max_chars=max_chars,
            message=f"Local skill source is not valid UTF-8: {exc}.",
        )
    digest = hashlib.sha256(raw_content).hexdigest()
    if _SECRETISH_RE.search(content_text):
        return AgentSkillMaterializedContext(
            skill_id=skill.skill_id,
            source=skill.source,
            source_type=skill.source_type,
            import_policy=skill.import_policy,
            status=AgentSkillMaterializationStatus.BLOCKED,
            resolved_path=resolved.as_posix(),
            sha256=digest,
            byte_count=len(raw_content),
            char_count=len(content_text),
            max_chars=max_chars,
            message=(
                "Local skill source contains secret-like text, so content was not "
                "attached to runtime artifacts."
            ),
        )

    truncated = len(content_text) > max_chars
    content = content_text[:max_chars]
    return AgentSkillMaterializedContext(
        skill_id=skill.skill_id,
        source=skill.source,
        source_type=skill.source_type,
        import_policy=skill.import_policy,
        status=(
            AgentSkillMaterializationStatus.TRUNCATED
            if truncated
            else AgentSkillMaterializationStatus.LOADED
        ),
        resolved_path=resolved.as_posix(),
        sha256=digest,
        byte_count=len(raw_content),
        char_count=len(content_text),
        max_chars=max_chars,
        truncated=truncated,
        content=content,
        message=(
            "Local skill source was materialized with bounded content."
            if not truncated
            else "Local skill source was materialized with truncated bounded content."
        ),
    )


def _resolve_local_skill_source(source: str, *, base_dir: Path) -> Path:
    source_path = Path(source)
    if source_path.is_absolute():
        return source_path
    return base_dir / source_path


def _build_mcp_runtime_contract(server: AgentMcpServerBinding) -> AgentMcpRuntimeContract:
    command_payload = json.dumps(
        list(server.command),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    readiness_check_ids = [f"mcp_env_keys:{server.server_id}"]
    if server.approval_policy == McpApprovalPolicy.ALLOW_ALL:
        readiness_check_ids.append(f"mcp_approval_policy:{server.server_id}")
    return AgentMcpRuntimeContract(
        server_id=server.server_id,
        command_sha256=hashlib.sha256(command_payload).hexdigest(),
        command_token_count=len(server.command),
        allowed_tools=server.allowed_tools,
        allowed_tool_count=len(server.allowed_tools),
        env_keys=server.env_keys,
        env_key_count=len(server.env_keys),
        approval_policy=server.approval_policy,
        runtime_approval_required=(
            server.approval_policy == McpApprovalPolicy.APPROVE_DANGEROUS
        ),
        operator_isolation_required=server.approval_policy == McpApprovalPolicy.ALLOW_ALL,
        readiness_check_ids=tuple(readiness_check_ids),
        evidence_refs=server.evidence_refs,
    )


def _mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _ordered_unique(values: Iterable[object]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


def _agent_stage_assignment_row(
    stage: str,
    stage_contexts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    readiness_values = [
        value
        for value in (context.get("readiness") for context in stage_contexts)
        if isinstance(value, Mapping)
    ]
    failed_checks = sum(
        int(value.get("failed_check_count", 0) or 0) for value in readiness_values
    )
    warning_checks = sum(
        int(value.get("warning_count", 0) or 0) for value in readiness_values
    )
    return {
        "stage": normalize_profile_stage(stage),
        "agent_count": len(stage_contexts),
        "agent_ids": [
            str(context.get("agent_id", ""))
            for context in stage_contexts
            if str(context.get("agent_id", "")).strip()
        ],
        "profile_paths": list(_ordered_unique(
            context.get("profile_path", "") for context in stage_contexts
        )),
        "skill_ids": list(_ordered_unique(
            skill.get("skill_id", "")
            for context in stage_contexts
            for skill in _mapping_items(context.get("skills"))
        )),
        "materialized_skills": [
            _compact_materialized_skill(skill)
            for context in stage_contexts
            for skill in _mapping_items(context.get("materialized_skills"))
            if str(skill.get("skill_id", "")).strip()
        ],
        "mcp_server_ids": list(_ordered_unique(
            server.get("server_id", "")
            for context in stage_contexts
            for server in _mapping_items(context.get("mcp_servers"))
        )),
        "mcp_runtime_contracts": [
            _compact_mcp_runtime_contract(contract)
            for context in stage_contexts
            for contract in _mapping_items(context.get("mcp_runtime_contracts"))
            if str(contract.get("server_id", "")).strip()
        ],
        "readiness": {
            "passed": failed_checks == 0,
            "failed_check_count": failed_checks,
            "warning_count": warning_checks,
        },
    }


def _agent_assignment_row(context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": str(context.get("agent_id", "")),
        "role": str(context.get("role", "")),
        "thinking_mode": str(context.get("thinking_mode", "")),
        "assigned_stages": list(_context_assigned_stages(context)),
        "profile_path": str(context.get("profile_path", "")),
        "skill_ids": list(_ordered_unique(
            skill.get("skill_id", "") for skill in _mapping_items(context.get("skills"))
        )),
        "materialized_skill_ids": list(_ordered_unique(
            skill.get("skill_id", "")
            for skill in _mapping_items(context.get("materialized_skills"))
        )),
        "mcp_server_ids": list(_ordered_unique(
            server.get("server_id", "")
            for server in _mapping_items(context.get("mcp_servers"))
        )),
        "readiness": (
            dict(context["readiness"])
            if isinstance(context.get("readiness"), Mapping)
            else {}
        ),
    }


def _compact_materialized_skill(skill: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "skill_id": str(skill.get("skill_id", "")),
        "status": str(skill.get("status", "")),
        "sha256": skill.get("sha256"),
        "byte_count": skill.get("byte_count"),
        "char_count": skill.get("char_count"),
        "max_chars": skill.get("max_chars"),
        "truncated": bool(skill.get("truncated", False)),
        "resolved_path": skill.get("resolved_path"),
    }


def _compact_mcp_runtime_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "server_id": str(contract.get("server_id", "")),
        "contract_kind": str(contract.get("contract_kind", "")),
        "command_sha256": contract.get("command_sha256"),
        "allowed_tools": list(_ordered_unique(contract.get("allowed_tools", ()))),
        "approval_policy": str(contract.get("approval_policy", "")),
        "runtime_approval_required": bool(
            contract.get("runtime_approval_required", False)
        ),
        "operator_isolation_required": bool(
            contract.get("operator_isolation_required", False)
        ),
        "tool_invocation_evidence_required": bool(
            contract.get("tool_invocation_evidence_required", True)
        ),
    }


def _skill_readiness_check(
    skill: AgentSkillBinding,
    *,
    base_dir: Path,
) -> AgentProfileReadinessCheck:
    target = f"skill:{skill.skill_id}"
    if skill.source_type == SkillSourceType.LOCAL_PATH:
        resolved = _resolve_local_skill_source(skill.source, base_dir=base_dir)
        if resolved.exists():
            return AgentProfileReadinessCheck(
                check_id=f"skill_source_exists:{skill.skill_id}",
                status=AgentProfileReadinessStatus.PASS,
                target=target,
                message=f"Local skill source exists at {resolved.as_posix()}.",
            )
        return AgentProfileReadinessCheck(
            check_id=f"skill_source_exists:{skill.skill_id}",
            status=AgentProfileReadinessStatus.FAIL,
            target=target,
            message=f"Local skill source is missing at {resolved.as_posix()}.",
            next_action="Create the skill file or update the profile source before runtime use.",
        )
    if skill.source_type == SkillSourceType.OBSIDIAN_NOTE:
        return AgentProfileReadinessCheck(
            check_id=f"skill_source_declared:{skill.skill_id}",
            status=AgentProfileReadinessStatus.WARN,
            target=target,
            message="Obsidian note skill source is declared but not resolved by this local check.",
            next_action="Ensure the referenced note exists in the project vault before runtime use.",
        )
    return AgentProfileReadinessCheck(
        check_id=f"skill_source_declared:{skill.skill_id}",
        status=AgentProfileReadinessStatus.WARN,
        target=target,
        message=f"{skill.source_type.value} skill source is declared but not fetched by readiness.",
        next_action="Validate external/package skill content before using it in a research stage.",
    )


def _mcp_env_readiness_check(
    server: AgentMcpServerBinding,
    *,
    env: Mapping[str, str],
) -> AgentProfileReadinessCheck:
    target = f"mcp:{server.server_id}"
    if not server.env_keys:
        return AgentProfileReadinessCheck(
            check_id=f"mcp_env_keys:{server.server_id}",
            status=AgentProfileReadinessStatus.PASS,
            target=target,
            message="MCP server declares no required environment variable names.",
        )
    missing = tuple(key for key in server.env_keys if not env.get(key))
    if missing:
        return AgentProfileReadinessCheck(
            check_id=f"mcp_env_keys:{server.server_id}",
            status=AgentProfileReadinessStatus.FAIL,
            target=target,
            message=(
                "MCP server is missing required environment variable names: "
                f"{', '.join(missing)}."
            ),
            next_action="Set the missing variables outside the repository before runtime use.",
        )
    return AgentProfileReadinessCheck(
        check_id=f"mcp_env_keys:{server.server_id}",
        status=AgentProfileReadinessStatus.PASS,
        target=target,
        message=(
            "All required MCP environment variable names are present; values were not "
            "recorded."
        ),
    )


def _split_scoped_value(spec: str, label: str) -> tuple[str, str]:
    if ":" not in spec:
        msg = f"{label} spec must use name:value: {spec}"
        raise ValueError(msg)
    name, value = spec.split(":", 1)
    value = value.strip()
    if not value:
        msg = f"{label} value must be non-empty: {spec}"
        raise ValueError(msg)
    return _validate_identifier(name, f"{label} id"), value


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


def _context_assigned_stages(context: Mapping[str, Any]) -> tuple[str, ...]:
    raw_stages = context.get("assigned_stages", ())
    if isinstance(raw_stages, str):
        stage_values: Iterable[Any] = (raw_stages,)
    elif isinstance(raw_stages, Iterable) and not isinstance(raw_stages, Mapping):
        stage_values = raw_stages
    else:
        stage_values = ()

    normalized: list[str] = []
    seen: set[str] = set()
    for item in stage_values:
        value = str(item).strip()
        if not value:
            continue
        stage = normalize_profile_stage(value)
        if stage not in seen:
            normalized.append(stage)
            seen.add(stage)
    return tuple(normalized)


def _normalize_unique_stages(stages: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for stage in stages:
        normalized_stage = normalize_profile_stage(stage)
        if normalized_stage not in seen:
            normalized.append(normalized_stage)
            seen.add(normalized_stage)
    return tuple(normalized)


def _duplicate_values(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _profile_stage_coverage(
    stage: str,
    profiles: tuple[AgentProfile, ...],
) -> AgentProfileStageCoverage:
    stage_profiles = tuple(profile for profile in profiles if stage in profile.assigned_stages)
    skill_ids = tuple(
        dict.fromkeys(
            skill.skill_id
            for profile in stage_profiles
            for skill in profile.skills
        )
    )
    mcp_server_ids = tuple(
        dict.fromkeys(
            server.server_id
            for profile in stage_profiles
            for server in profile.mcp_servers
        )
    )
    return AgentProfileStageCoverage(
        stage=stage,
        covered=bool(stage_profiles),
        agent_ids=tuple(profile.agent_id for profile in stage_profiles),
        skill_ids=skill_ids,
        mcp_server_ids=mcp_server_ids,
    )


def _has_scientific_thinking_contract(thinking_contract: tuple[str, ...]) -> bool:
    text = " ".join(thinking_contract).casefold()
    return "evidence" in text and (
        "research question" in text
        or "hypothesis" in text
        or "falsifiable" in text
    )


def _profile_set_failures(
    *,
    missing_stages: tuple[str, ...],
    duplicate_agent_ids: tuple[str, ...],
    readiness_failed_agent_ids: tuple[str, ...],
    non_scientific_contract_agent_ids: tuple[str, ...],
) -> tuple[str, ...]:
    failures: list[str] = []
    if missing_stages:
        failures.append(f"missing required stage coverage: {', '.join(missing_stages)}")
    if duplicate_agent_ids:
        failures.append(f"duplicate agent profiles: {', '.join(duplicate_agent_ids)}")
    if readiness_failed_agent_ids:
        failures.append(
            "profile readiness failed for: " + ", ".join(readiness_failed_agent_ids)
        )
    if non_scientific_contract_agent_ids:
        failures.append(
            "profile thinking contract is not research/evidence-first for: "
            + ", ".join(non_scientific_contract_agent_ids)
        )
    return tuple(failures)


def _profile_set_warnings(
    *,
    profiles: tuple[AgentProfile, ...],
    allow_all_agent_ids: tuple[str, ...],
    readiness_by_agent: Mapping[str, AgentProfileReadinessReport],
) -> tuple[str, ...]:
    warnings: list[str] = []
    unassigned = tuple(profile.agent_id for profile in profiles if not profile.assigned_stages)
    if unassigned:
        warnings.append(
            "profile has no assigned stages and will not enter stage contexts: "
            + ", ".join(unassigned)
        )
    if allow_all_agent_ids:
        warnings.append(
            "allow_all MCP approval requires isolated operator approval for: "
            + ", ".join(allow_all_agent_ids)
        )
    warning_agents = tuple(
        report.agent_id
        for report in readiness_by_agent.values()
        if report.warning_count > 0 and report.passed
    )
    if warning_agents:
        warnings.append("profile readiness warnings for: " + ", ".join(warning_agents))
    return tuple(warnings)


def _load_bundle_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read agent profile bundle {path}: {exc}") from exc
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            msg = (
                "Invalid JSON agent profile bundle at line "
                f"{exc.lineno}, column {exc.colno}: {exc.msg}"
            )
            raise ValueError(msg) from exc
    elif suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML agent profile bundle: {exc}") from exc
    elif suffix == ".toml":
        try:
            data = toml.loads(text)
        except toml.TomlDecodeError as exc:
            raise ValueError(f"Invalid TOML agent profile bundle: {exc}") from exc
    else:
        raise ValueError(
            f"Unsupported agent profile bundle extension '{path.suffix}' for {path}. "
            "Expected .json, .yaml, .yml, or .toml."
        )
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Invalid agent profile bundle: top-level value must be a mapping/object.")
    return data


def _bundle_command_tokens(command: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command, posix=False))
    return command


def _safe_path_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    if not safe:
        msg = "project_id must contain at least one safe path character"
        raise ValueError(msg)
    return safe
