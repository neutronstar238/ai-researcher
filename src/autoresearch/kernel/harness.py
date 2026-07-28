"""Versioned harness policies, bounded execution, and episode packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from .contracts import (
    ActorKind,
    EventActor,
    EventStatus,
    KernelContract,
    RunEvent,
    Sha256,
    StableId,
    canonical_sha256,
)
from .journal import (
    EventJournal,
    SensitiveContentError,
    validate_persistable_content,
)

LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=12_000),
]
PolicyVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$",
    ),
]


class StructuredOutputValidationError(ValueError):
    """Raised when model output violates the frozen task output contract."""


class HarnessRuntimeError(RuntimeError):
    """Raised when a harness cannot safely start or package an episode."""


class JsonFieldType(str, Enum):
    """Portable JSON value kinds allowed in a structured output contract."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class SideEffectLevel(str, Enum):
    """Declared side-effect class for a tool made visible to a harness."""

    NONE = "none"
    LOCAL_REVERSIBLE = "local_reversible"
    LOCAL_IRREVERSIBLE = "local_irreversible"
    EXTERNAL_REVERSIBLE = "external_reversible"
    EXTERNAL_IRREVERSIBLE = "external_irreversible"


class TrajectoryKind(str, Enum):
    """Kinds of observable steps in one bounded trial trajectory."""

    PREFLIGHT = "preflight"
    MODEL = "model"
    TOOL = "tool"
    VERIFICATION = "verification"
    OUTCOME = "outcome"


class StepOutcome(str, Enum):
    """Truthful result of one trajectory step."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEGATIVE_RESULT = "negative_result"


class EpisodeOutcomeStatus(str, Enum):
    """Final environment outcome, kept distinct from model text."""

    SUCCEEDED = "succeeded"
    NEGATIVE_RESULT = "negative_result"
    FAILED = "failed"
    BLOCKED = "blocked"


class FailureDomain(str, Enum):
    """Component domain responsible for a blocked or failed episode."""

    CONFIGURATION = "configuration"
    MODEL = "model"
    TOOL = "tool"
    PERMISSION = "permission"
    BUDGET = "budget"
    OUTPUT_VALIDATION = "output_validation"
    VERIFICATION = "verification"
    SECURITY = "security"
    SYSTEM = "system"


class GraderKind(str, Enum):
    """Responsibility class of a grader."""

    DETERMINISTIC = "deterministic"
    MODEL = "model"
    HUMAN = "human"


class InterventionKind(str, Enum):
    """Explicit intervention recorded during an episode."""

    RETRY = "retry"
    CONTEXT_RESET = "context_reset"
    HUMAN_APPROVAL = "human_approval"
    ENTROPY_STOP = "entropy_stop"
    MODEL_FALLBACK = "model_fallback"


class ApprovalDecision(str, Enum):
    """Decision attached to a permission approval record."""

    APPROVED = "approved"
    DENIED = "denied"


class VersionedPolicy(KernelContract):
    """Shared identity for one independently versioned harness policy."""

    schema_version: Literal[1] = 1
    policy_id: StableId
    version: PolicyVersion


class StructuredField(KernelContract):
    """One top-level field in a provider-neutral structured output contract."""

    name: StableId
    value_type: JsonFieldType
    required: bool = True
    description: LongText | None = None
    enum_values: list[JsonValue] = Field(default_factory=list)

    @field_validator("enum_values")
    @classmethod
    def _require_unique_enum_values(cls, value: list[JsonValue]) -> list[JsonValue]:
        fingerprints = [canonical_sha256(item) for item in value]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("enum_values must be unique")
        return value

    @model_validator(mode="after")
    def _validate_enum_types(self) -> StructuredField:
        for item in self.enum_values:
            if not _matches_json_field_type(item, self.value_type):
                raise ValueError(
                    f"enum value for {self.name} does not match {self.value_type.value}"
                )
        return self


class StructuredOutputContract(KernelContract):
    """Small strict JSON-object contract that can be sent to any capable adapter."""

    schema_version: Literal[1] = 1
    fields: list[StructuredField] = Field(min_length=1)
    allow_additional_fields: bool = False

    @field_validator("fields")
    @classmethod
    def _normalize_fields(cls, value: list[StructuredField]) -> list[StructuredField]:
        names = [field.name for field in value]
        if len(names) != len(set(names)):
            raise ValueError("structured output field names must be unique")
        return sorted(value, key=lambda field: field.name)

    def json_schema(self) -> dict[str, Any]:
        """Return the strict JSON Schema presented to a compatible model adapter."""

        properties: dict[str, Any] = {}
        required: list[str] = []
        for field in self.fields:
            definition: dict[str, Any] = {"type": field.value_type.value}
            if field.description is not None:
                definition["description"] = field.description
            if field.enum_values:
                definition["enum"] = field.enum_values
            properties[field.name] = definition
            if field.required:
                required.append(field.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": self.allow_additional_fields,
        }

    def validate_output(self, value: object) -> dict[str, JsonValue]:
        """Validate one JSON object and return it without synthesizing missing fields."""

        if not isinstance(value, dict):
            raise StructuredOutputValidationError("structured output must be an object")
        fields = {field.name: field for field in self.fields}
        missing = sorted(
            field.name
            for field in self.fields
            if field.required and field.name not in value
        )
        if missing:
            raise StructuredOutputValidationError(
                "structured output is missing required fields: " + ", ".join(missing)
            )
        extra = sorted(set(value) - set(fields))
        if extra and not self.allow_additional_fields:
            raise StructuredOutputValidationError(
                "structured output has additional fields: " + ", ".join(extra)
            )
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            field = fields.get(key)
            if field is not None:
                if not _matches_json_field_type(item, field.value_type):
                    raise StructuredOutputValidationError(
                        f"structured output field {key} must be {field.value_type.value}"
                    )
                if field.enum_values and canonical_sha256(item) not in {
                    canonical_sha256(candidate) for candidate in field.enum_values
                }:
                    raise StructuredOutputValidationError(
                        f"structured output field {key} is outside its enum"
                    )
            normalized[str(key)] = item
        return normalized


class TaskContract(VersionedPolicy):
    """Frozen task meaning and success boundary presented to the harness."""

    task_id: StableId
    instructions: LongText
    output_contract: StructuredOutputContract
    success_criteria: list[LongText] = Field(min_length=1)
    forbidden_actions: list[LongText] = Field(default_factory=list)
    stop_conditions: list[LongText] = Field(min_length=1)
    required_permission_ids: list[StableId] = Field(default_factory=list)
    required_tool_ids: list[StableId] = Field(default_factory=list)

    @field_validator("required_permission_ids", "required_tool_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="task requirement")


class ContextPolicy(VersionedPolicy):
    """Source selection, capacity, reset, and contamination rules."""

    allowed_source_ids: list[StableId] = Field(default_factory=list)
    max_context_tokens: int = Field(ge=0)
    max_context_bytes: int = Field(ge=0)
    compression_allowed: bool = False
    reset_between_trials: bool = True
    contamination_domains: list[StableId] = Field(default_factory=list)

    @field_validator("allowed_source_ids", "contamination_domains")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="context ID")


class ModelPolicy(VersionedPolicy):
    """Provider-neutral capability and resource requirements for one model."""

    adapter_id: StableId
    model_ref: StableId
    required_capabilities: list[StableId] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1)
    max_output_tokens: int = Field(ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    structured_output_required: bool = True
    deliberation: Literal["provider_default", "disabled"] = "provider_default"

    @field_validator("required_capabilities")
    @classmethod
    def _normalize_capabilities(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="model capability")


class ToolDefinition(KernelContract):
    """One tool made visible through a versioned policy."""

    tool_id: StableId
    version: PolicyVersion
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    side_effect_level: SideEffectLevel
    required_permission_id: StableId | None = None
    requires_sandbox: bool = True
    allowed_network_domains: list[StableId] = Field(default_factory=list)

    @field_validator("allowed_network_domains")
    @classmethod
    def _normalize_domains(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="network domain")


class ToolPolicy(VersionedPolicy):
    """Allowlisted tools, sandbox, network, and side-effect boundary."""

    tools: list[ToolDefinition] = Field(default_factory=list)
    default_deny: bool = True
    sandbox_required: bool = True
    network_default_deny: bool = True
    max_tool_calls: int = Field(default=0, ge=0)

    @field_validator("tools")
    @classmethod
    def _normalize_tools(cls, value: list[ToolDefinition]) -> list[ToolDefinition]:
        ids = [tool.tool_id for tool in value]
        if len(ids) != len(set(ids)):
            raise ValueError("tool IDs must be unique")
        return sorted(value, key=lambda tool: tool.tool_id)


class MemoryPolicy(VersionedPolicy):
    """Read/write boundaries across Vault, transient state, and experience memory."""

    vault_read: bool = True
    vault_write: bool = False
    allowed_vault_prefixes: list[LongText] = Field(default_factory=list)
    short_term_state: bool = True
    run_cache: bool = True
    long_term_experience_write: bool = False

    @field_validator("allowed_vault_prefixes")
    @classmethod
    def _normalize_prefixes(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="Vault prefix")


class StatePolicy(VersionedPolicy):
    """Persistence, checkpoint, resume, and mutable-state limits."""

    append_only_events: bool = True
    checkpoint_every_events: int = Field(default=1, ge=1)
    resume_allowed: bool = True
    max_mutable_state_bytes: int = Field(ge=0)
    terminal_is_immutable: bool = True


class PermissionPolicy(VersionedPolicy):
    """Default-deny execution permissions and human approval boundary."""

    granted_permission_ids: list[StableId] = Field(default_factory=list)
    approval_required_permission_ids: list[StableId] = Field(default_factory=list)
    forbidden_permission_ids: list[StableId] = Field(default_factory=list)
    deny_unknown: bool = True
    permission_expansion_allowed: bool = False

    @field_validator(
        "granted_permission_ids",
        "approval_required_permission_ids",
        "forbidden_permission_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="permission")

    @model_validator(mode="after")
    def _require_disjoint_sets(self) -> PermissionPolicy:
        sets = {
            "granted": set(self.granted_permission_ids),
            "approval": set(self.approval_required_permission_ids),
            "forbidden": set(self.forbidden_permission_ids),
        }
        for left, right in (("granted", "approval"), ("granted", "forbidden"), ("approval", "forbidden")):
            overlap = sorted(sets[left] & sets[right])
            if overlap:
                raise ValueError(
                    f"permission sets {left}/{right} overlap: {', '.join(overlap)}"
                )
        return self


class VerificationPolicy(VersionedPolicy):
    """Required deterministic, model, or human checks over the environment outcome."""

    required_grader_ids: list[StableId] = Field(min_length=1)
    require_output_artifact_hashes: bool = True
    fail_closed_on_grader_error: bool = True
    require_journal_seal: bool = True

    @field_validator("required_grader_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="grader")


class ObservabilityPolicy(VersionedPolicy):
    """What must be present in the local episode trace."""

    record_events: bool = True
    record_full_trajectory: bool = True
    record_costs: bool = True
    record_failures: bool = True
    record_interventions: bool = True
    store_raw_model_text: bool = False
    local_only: bool = True
    max_step_summary_chars: int = Field(default=512, ge=64, le=4096)


class FailureAttributionPolicy(VersionedPolicy):
    """Required attribution fields and handling of unknown failures."""

    allowed_domains: list[FailureDomain] = Field(
        default_factory=lambda: sorted(FailureDomain, key=lambda domain: domain.value)
    )
    require_component_id: bool = True
    require_retryability: bool = True
    unknown_exception_domain: FailureDomain = FailureDomain.SYSTEM

    @field_validator("allowed_domains")
    @classmethod
    def _normalize_domains(
        cls,
        value: list[FailureDomain],
    ) -> list[FailureDomain]:
        if len(value) != len(set(value)):
            raise ValueError("failure domains must be unique")
        return sorted(value, key=lambda domain: domain.value)


class CostPolicy(VersionedPolicy):
    """Token, money, time, and tool-call ceilings for one episode."""

    max_total_tokens: int = Field(ge=0)
    max_estimated_cost_usd: float = Field(ge=0.0)
    max_wall_time_seconds: float = Field(gt=0.0)
    max_tool_calls: int = Field(ge=0)
    require_known_cost: bool = True


class EntropyInterventionPolicy(VersionedPolicy):
    """Uncertainty, retry, and human-intervention bounds."""

    max_uncertainty: float = Field(default=1.0, ge=0.0, le=1.0)
    stop_when_uncertainty_exceeded: bool = True
    max_retries: int = Field(default=0, ge=0)
    max_human_interventions: int = Field(default=0, ge=0)
    allowed_interventions: list[InterventionKind] = Field(default_factory=list)

    @field_validator("allowed_interventions")
    @classmethod
    def _normalize_interventions(
        cls,
        value: list[InterventionKind],
    ) -> list[InterventionKind]:
        if len(value) != len(set(value)):
            raise ValueError("allowed interventions must be unique")
        return sorted(value, key=lambda item: item.value)


class GraderSpec(KernelContract):
    """Frozen grader identity and pass threshold."""

    grader_id: StableId
    version: PolicyVersion
    kind: GraderKind
    threshold: float = Field(ge=0.0, le=1.0)


class EvaluationPolicy(VersionedPolicy):
    """Trial, grader, outcome, and promotion semantics."""

    trial_count: int = Field(default=1, ge=1)
    graders: list[GraderSpec] = Field(min_length=1)
    require_environment_outcome: bool = True
    require_all_graders: bool = True
    promotion_threshold: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("graders")
    @classmethod
    def _normalize_graders(cls, value: list[GraderSpec]) -> list[GraderSpec]:
        ids = [grader.grader_id for grader in value]
        if len(ids) != len(set(ids)):
            raise ValueError("grader IDs must be unique")
        return sorted(value, key=lambda grader: grader.grader_id)


class _HarnessSpecContent(KernelContract):
    schema_version: Literal[1] = 1
    spec_id: StableId
    version: PolicyVersion
    task_contract: TaskContract
    context_policy: ContextPolicy
    model_policy: ModelPolicy
    tool_policy: ToolPolicy
    memory_policy: MemoryPolicy
    state_policy: StatePolicy
    permission_policy: PermissionPolicy
    verification_policy: VerificationPolicy
    observability_policy: ObservabilityPolicy
    failure_attribution_policy: FailureAttributionPolicy
    cost_policy: CostPolicy
    entropy_intervention_policy: EntropyInterventionPolicy
    evaluation_policy: EvaluationPolicy
    change_prediction: LongText
    evaluation_scope: LongText
    parent_spec_hash: Sha256 | None = None
    rollback_spec_hash: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_cross_policy_references(self) -> _HarnessSpecContent:
        tools = {tool.tool_id: tool for tool in self.tool_policy.tools}
        missing_tools = sorted(set(self.task_contract.required_tool_ids) - set(tools))
        if missing_tools:
            raise ValueError(
                "task references tools absent from tool policy: "
                + ", ".join(missing_tools)
            )
        for tool_id in self.task_contract.required_tool_ids:
            tool = tools[tool_id]
            if tool.requires_sandbox and not self.tool_policy.sandbox_required:
                raise ValueError(f"tool {tool_id} requires a sandbox")
        if self.tool_policy.max_tool_calls > self.cost_policy.max_tool_calls:
            raise ValueError("tool policy exceeds the episode tool-call cost ceiling")
        grader_ids = {grader.grader_id for grader in self.evaluation_policy.graders}
        missing_graders = sorted(
            set(self.verification_policy.required_grader_ids) - grader_ids
        )
        if missing_graders:
            raise ValueError(
                "verification references graders absent from evaluation policy: "
                + ", ".join(missing_graders)
            )
        if self.model_policy.max_attempts - 1 > self.entropy_intervention_policy.max_retries:
            raise ValueError("model retry count exceeds entropy/intervention policy")
        if self.evaluation_policy.trial_count != 1:
            raise ValueError("task 262.4 bounded runner supports exactly one trial")
        return self


class HarnessSpec(_HarnessSpecContent):
    """Content-addressed complete harness definition without provider SDK types."""

    spec_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> HarnessSpec:
        expected = self.calculated_hash()
        if self.spec_hash != expected:
            raise ValueError(
                f"spec_hash mismatch for {self.spec_id}: "
                f"expected {expected}, got {self.spec_hash}"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> HarnessSpec:
        """Validate unhashed content, attach its digest, and validate the final spec."""

        content = _HarnessSpecContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["spec_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the digest over all normalized fields except ``spec_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))

    def verify_integrity(self) -> None:
        """Fail closed if nested policy content changed in memory."""

        if self.spec_hash != self.calculated_hash():
            raise HarnessRuntimeError(f"harness spec {self.spec_id} failed integrity check")


class ApprovalGrant(KernelContract):
    """One explicit human or deterministic permission decision supplied to a run."""

    permission_id: StableId
    decision_id: StableId
    decision: ApprovalDecision
    actor_id: StableId
    decided_at: datetime
    reason: LongText

    @field_validator("decided_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, label="approval decided_at")


class HarnessRunRequest(KernelContract):
    """Runtime inputs kept separate from the versioned harness definition."""

    run_id: StableId
    episode_id: StableId
    task_input: dict[str, JsonValue] = Field(default_factory=dict)
    context_artifact_ids: list[StableId] = Field(default_factory=list)
    available_tool_ids: list[StableId] = Field(default_factory=list)
    approvals: list[ApprovalGrant] = Field(default_factory=list)
    prior_tokens: int = Field(default=0, ge=0)
    prior_estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    prior_tool_calls: int = Field(default=0, ge=0)

    @field_validator("context_artifact_ids", "available_tool_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="runtime ID")

    @field_validator("approvals")
    @classmethod
    def _normalize_approvals(cls, value: list[ApprovalGrant]) -> list[ApprovalGrant]:
        ids = [approval.decision_id for approval in value]
        if len(ids) != len(set(ids)):
            raise ValueError("approval decision IDs must be unique")
        return sorted(value, key=lambda approval: approval.decision_id)


class ModelInvocationRequest(KernelContract):
    """Provider-neutral request handed to one model adapter."""

    run_id: StableId
    episode_id: StableId
    trial_id: StableId
    harness_spec_id: StableId
    harness_spec_hash: Sha256
    task_id: StableId
    instructions: LongText
    task_input: dict[str, JsonValue]
    context_artifact_ids: list[StableId] = Field(default_factory=list)
    response_schema: dict[str, JsonValue]
    model_ref: StableId
    max_output_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0.0, le=2.0)
    deliberation: Literal["provider_default", "disabled"]


class ModelUsage(KernelContract):
    """Normalized usage independent of one provider's response object."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    cost_known: bool = False
    wall_time_seconds: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _validate_total(self) -> ModelUsage:
        minimum = self.prompt_tokens + self.completion_tokens
        if self.total_tokens < minimum:
            raise ValueError("total_tokens cannot be below prompt plus completion tokens")
        return self


class EpisodeArtifact(KernelContract):
    """Hash-bound artifact emitted by an adapter or tool."""

    artifact_id: StableId
    artifact_type: StableId
    sha256: Sha256
    media_type: LongText | None = None


class ToolCallRecord(KernelContract):
    """One tool call without raw arguments or unredacted tool output."""

    call_id: StableId
    tool_id: StableId
    outcome: StepOutcome
    arguments_hash: Sha256
    output_artifact_ids: list[StableId] = Field(default_factory=list)
    failure_code: StableId | None = None
    summary: LongText

    @field_validator("output_artifact_ids")
    @classmethod
    def _normalize_artifacts(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="tool output artifact")

    @model_validator(mode="after")
    def _validate_failure_code(self) -> ToolCallRecord:
        if self.outcome == StepOutcome.SUCCEEDED and self.failure_code is not None:
            raise ValueError("successful tool call cannot have a failure_code")
        if self.outcome != StepOutcome.SUCCEEDED and self.failure_code is None:
            raise ValueError("non-successful tool call requires a failure_code")
        return self


class AdapterStep(KernelContract):
    """One normalized model/tool step returned by an adapter."""

    step_id: StableId
    kind: TrajectoryKind
    outcome: StepOutcome
    summary: LongText
    input_artifact_ids: list[StableId] = Field(default_factory=list)
    output_artifact_ids: list[StableId] = Field(default_factory=list)

    @field_validator("input_artifact_ids", "output_artifact_ids")
    @classmethod
    def _normalize_artifacts(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="adapter step artifact")


class ModelInvocationResult(KernelContract):
    """Normalized adapter result; no endpoint, API key, or provider SDK object."""

    adapter_id: StableId
    adapter_version: PolicyVersion
    provider_ref: StableId
    model_ref: StableId
    capabilities: list[StableId] = Field(default_factory=list)
    attempts: int = Field(default=1, ge=1)
    structured_output: dict[str, JsonValue]
    usage: ModelUsage
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    steps: list[AdapterStep] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    artifacts: list[EpisodeArtifact] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def _normalize_capabilities(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="adapter capability")

    @field_validator("steps")
    @classmethod
    def _normalize_steps(cls, value: list[AdapterStep]) -> list[AdapterStep]:
        ids = [step.step_id for step in value]
        if len(ids) != len(set(ids)):
            raise ValueError("adapter step IDs must be unique")
        return value

    @field_validator("tool_calls")
    @classmethod
    def _normalize_tool_calls(cls, value: list[ToolCallRecord]) -> list[ToolCallRecord]:
        ids = [call.call_id for call in value]
        if len(ids) != len(set(ids)):
            raise ValueError("tool call IDs must be unique")
        return value

    @field_validator("artifacts")
    @classmethod
    def _normalize_artifacts(cls, value: list[EpisodeArtifact]) -> list[EpisodeArtifact]:
        ids = [artifact.artifact_id for artifact in value]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact IDs must be unique")
        return sorted(value, key=lambda artifact: artifact.artifact_id)


class ModelAdapter(Protocol):
    """Structural interface implemented by deterministic or live model adapters."""

    adapter_id: str
    adapter_version: str

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Execute one bounded model request and return normalized evidence."""


class GraderResult(KernelContract):
    """One grader result over the final environment output."""

    grader_id: StableId
    grader_version: PolicyVersion
    kind: GraderKind
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: LongText
    evidence_artifact_ids: list[StableId] = Field(default_factory=list)

    @field_validator("evidence_artifact_ids")
    @classmethod
    def _normalize_artifacts(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="grader evidence artifact")


class HarnessGrader(Protocol):
    """Structural interface for a deterministic, model, or human grader."""

    grader_id: str
    grader_version: str
    kind: GraderKind

    def grade(
        self,
        *,
        task: TaskContract,
        task_input: Mapping[str, JsonValue],
        output: Mapping[str, JsonValue],
        artifacts: tuple[EpisodeArtifact, ...],
    ) -> GraderResult:
        """Evaluate the environment output without changing it."""


class HarnessAdapterError(RuntimeError):
    """Categorized adapter failure converted to a truthful terminal episode."""

    def __init__(
        self,
        message: str,
        *,
        domain: FailureDomain,
        code: str,
        component_id: str,
        retryable: bool,
        blocked: bool,
    ) -> None:
        super().__init__(message)
        self.domain = domain
        self.code = code
        self.component_id = component_id
        self.retryable = retryable
        self.blocked = blocked


class DeterministicFixtureAdapter:
    """Small deterministic adapter used to characterize harness semantics."""

    adapter_id = "deterministic.fixture"
    adapter_version = "1"

    def __init__(self, result: ModelInvocationResult) -> None:
        self.result = result
        self.invocations = 0

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Return the frozen result after confirming the requested model identity."""

        self.invocations += 1
        if request.model_ref != self.result.model_ref:
            raise HarnessAdapterError(
                "deterministic fixture model_ref does not match the request",
                domain=FailureDomain.CONFIGURATION,
                code="fixture_model_mismatch",
                component_id=self.adapter_id,
                retryable=False,
                blocked=True,
            )
        return self.result.model_copy(deep=True)


class ExactFieldGrader:
    """Deterministic grader for a frozen expected top-level field value."""

    kind = GraderKind.DETERMINISTIC

    def __init__(
        self,
        *,
        grader_id: str,
        grader_version: str,
        field_name: str,
        expected_value: JsonValue,
    ) -> None:
        self.grader_id = grader_id
        self.grader_version = grader_version
        self.field_name = field_name
        self.expected_value = expected_value

    def grade(
        self,
        *,
        task: TaskContract,
        task_input: Mapping[str, JsonValue],
        output: Mapping[str, JsonValue],
        artifacts: tuple[EpisodeArtifact, ...],
    ) -> GraderResult:
        """Compare one field exactly and explain the deterministic decision."""

        del task, task_input, artifacts
        passed = output.get(self.field_name) == self.expected_value
        return GraderResult(
            grader_id=self.grader_id,
            grader_version=self.grader_version,
            kind=self.kind,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=(
                f"Field {self.field_name} matched the frozen expected value."
                if passed
                else f"Field {self.field_name} did not match the frozen expected value."
            ),
        )


class EpisodeCostRecord(KernelContract):
    """Normalized cost and usage for one trial."""

    cost_id: StableId
    trial_id: StableId
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)
    cost_known: bool
    wall_time_seconds: float = Field(ge=0.0)
    tool_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_total(self) -> EpisodeCostRecord:
        if self.total_tokens < self.prompt_tokens + self.completion_tokens:
            raise ValueError("episode cost total_tokens is inconsistent")
        return self


class InterventionRecord(KernelContract):
    """One explicit retry, approval, reset, fallback, or entropy stop."""

    intervention_id: StableId
    trial_id: StableId
    kind: InterventionKind
    actor_id: StableId
    occurred_at: datetime
    reason: LongText

    @field_validator("occurred_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, label="intervention occurred_at")


class FailureRecord(KernelContract):
    """Attributable reason why an episode blocked or failed."""

    failure_id: StableId
    trial_id: StableId
    domain: FailureDomain
    code: StableId
    component_id: StableId
    retryable: bool
    blocked: bool
    message: LongText


class TrajectoryStep(KernelContract):
    """One ordered, redacted step in the complete episode trajectory."""

    step_id: StableId
    sequence: int = Field(ge=1)
    trial_id: StableId
    kind: TrajectoryKind
    outcome: StepOutcome
    actor_id: StableId
    occurred_at: datetime
    summary: LongText
    source_step_id: StableId | None = None
    input_artifact_ids: list[StableId] = Field(default_factory=list)
    output_artifact_ids: list[StableId] = Field(default_factory=list)

    @field_validator("occurred_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, label="trajectory occurred_at")

    @field_validator("input_artifact_ids", "output_artifact_ids")
    @classmethod
    def _normalize_artifacts(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="trajectory artifact")


class TrialRecord(KernelContract):
    """One trial, distinct from its task, trajectory, and environment outcome."""

    trial_id: StableId
    sequence: int = Field(ge=1)
    status: EpisodeOutcomeStatus
    started_at: datetime
    completed_at: datetime
    provider_ref: StableId | None = None
    model_ref: StableId | None = None
    trajectory_step_ids: list[StableId] = Field(min_length=1)
    tool_call_ids: list[StableId] = Field(default_factory=list)
    grader_ids: list[StableId] = Field(default_factory=list)
    failure_ids: list[StableId] = Field(default_factory=list)
    cost_id: StableId
    output_hash: Sha256 | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, label="trial timestamp")

    @field_validator(
        "trajectory_step_ids",
        "tool_call_ids",
        "grader_ids",
        "failure_ids",
    )
    @classmethod
    def _normalize_references(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("trial references must be unique")
        return value

    @model_validator(mode="after")
    def _validate_outcome_fields(self) -> TrialRecord:
        if self.completed_at < self.started_at:
            raise ValueError("trial completed_at cannot precede started_at")
        successful = self.status in {
            EpisodeOutcomeStatus.SUCCEEDED,
            EpisodeOutcomeStatus.NEGATIVE_RESULT,
        }
        if successful != (self.output_hash is not None):
            raise ValueError("trial output_hash must match its terminal status")
        if self.status in {
            EpisodeOutcomeStatus.FAILED,
            EpisodeOutcomeStatus.BLOCKED,
        } and not self.failure_ids:
            raise ValueError("failed or blocked trial requires a failure reference")
        return self


class EnvironmentOutcome(KernelContract):
    """Final environment result, explicitly separate from a model response."""

    status: EpisodeOutcomeStatus
    summary: LongText
    structured_output: dict[str, JsonValue] | None = None
    output_hash: Sha256 | None = None
    artifact_ids: list[StableId] = Field(default_factory=list)

    @field_validator("artifact_ids")
    @classmethod
    def _normalize_artifacts(cls, value: list[str]) -> list[str]:
        return _sorted_unique(value, label="outcome artifact")

    @model_validator(mode="after")
    def _validate_output(self) -> EnvironmentOutcome:
        has_output = self.structured_output is not None
        successful = self.status in {
            EpisodeOutcomeStatus.SUCCEEDED,
            EpisodeOutcomeStatus.NEGATIVE_RESULT,
        }
        if has_output != successful:
            raise ValueError("only succeeded or negative outcomes may carry output")
        if successful:
            expected = canonical_sha256(self.structured_output)
            if self.output_hash != expected:
                raise ValueError("environment output_hash mismatch")
        elif self.output_hash is not None:
            raise ValueError("blocked or failed outcome cannot have an output_hash")
        return self


class _EpisodePackageContent(KernelContract):
    schema_version: Literal[1] = 1
    episode_id: StableId
    run_id: StableId
    harness_spec_id: StableId
    harness_spec_hash: Sha256
    task_contract: TaskContract
    task_input_hash: Sha256
    started_at: datetime
    completed_at: datetime
    trials: list[TrialRecord] = Field(min_length=1)
    trajectory: list[TrajectoryStep] = Field(min_length=1)
    final_outcome: EnvironmentOutcome
    graders: list[GraderResult] = Field(default_factory=list)
    costs: list[EpisodeCostRecord] = Field(min_length=1)
    interventions: list[InterventionRecord] = Field(default_factory=list)
    approvals: list[ApprovalGrant] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    artifacts: list[EpisodeArtifact] = Field(default_factory=list)
    journal_terminal_event_id: StableId
    journal_terminal_event_hash: Sha256
    journal_lineage_hash: Sha256
    journal_seal_hash: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, label="episode timestamp")

    @model_validator(mode="after")
    def _validate_episode_references(self) -> _EpisodePackageContent:
        if self.completed_at < self.started_at:
            raise ValueError("episode completed_at cannot precede started_at")
        if len(self.trials) != 1 or self.trials[0].sequence != 1:
            raise ValueError("task 262.4 episode package requires exactly trial 1")
        trial = self.trials[0]
        if trial.status != self.final_outcome.status:
            raise ValueError("trial and environment outcome statuses differ")

        step_ids = _unique_model_ids(self.trajectory, "step_id", "trajectory")
        expected_sequences = list(range(1, len(self.trajectory) + 1))
        if [step.sequence for step in self.trajectory] != expected_sequences:
            raise ValueError("trajectory sequences must be contiguous")
        if set(trial.trajectory_step_ids) != step_ids:
            raise ValueError("trial trajectory references are incomplete")

        cost_ids = _unique_model_ids(self.costs, "cost_id", "cost")
        if trial.cost_id not in cost_ids:
            raise ValueError("trial references an unknown cost record")
        grader_ids = _unique_model_ids(self.graders, "grader_id", "grader")
        if set(trial.grader_ids) != grader_ids:
            raise ValueError("trial grader references are incomplete")
        failure_ids = _unique_model_ids(self.failures, "failure_id", "failure")
        if set(trial.failure_ids) != failure_ids:
            raise ValueError("trial failure references are incomplete")
        tool_call_ids = _unique_model_ids(self.tool_calls, "call_id", "tool call")
        if set(trial.tool_call_ids) != tool_call_ids:
            raise ValueError("trial tool-call references are incomplete")
        artifact_ids = _unique_model_ids(self.artifacts, "artifact_id", "artifact")
        if not set(self.final_outcome.artifact_ids).issubset(artifact_ids):
            raise ValueError("environment outcome references an unknown artifact")

        if trial.output_hash != self.final_outcome.output_hash:
            raise ValueError("trial and environment output hashes differ")
        terminal_failure = self.final_outcome.status in {
            EpisodeOutcomeStatus.FAILED,
            EpisodeOutcomeStatus.BLOCKED,
        }
        if terminal_failure != bool(self.failures):
            raise ValueError("failure records must match failed or blocked outcomes")
        return self


class EpisodePackage(_EpisodePackageContent):
    """Content-addressed complete record of one bounded harness episode."""

    episode_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> EpisodePackage:
        expected = self.calculated_hash()
        if self.episode_hash != expected:
            raise ValueError(
                f"episode_hash mismatch for {self.episode_id}: "
                f"expected {expected}, got {self.episode_hash}"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> EpisodePackage:
        """Validate unhashed package content and attach its canonical digest."""

        content = _EpisodePackageContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["episode_hash"] = canonical_sha256(content)
        package = cls.model_validate(payload)
        validate_persistable_content(package.model_dump(mode="json"))
        return package

    def calculated_hash(self) -> str:
        """Calculate the package digest without ``episode_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"episode_hash"}))

    def verify_integrity(self) -> None:
        """Detect nested mutation before export."""

        if self.episode_hash != self.calculated_hash():
            raise HarnessRuntimeError(
                f"episode package {self.episode_id} failed integrity check"
            )


class HarnessRunner:
    """Execute one bounded trial and always preserve a truthful terminal outcome."""

    _ACTOR = EventActor(
        actor_id="harness.runner",
        kind=ActorKind.DETERMINISTIC_POLICY,
        version="1",
    )

    def __init__(
        self,
        *,
        spec: HarnessSpec,
        journal: EventJournal,
        model_adapter: ModelAdapter,
        graders: Mapping[str, HarnessGrader],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.spec = spec
        self.journal = journal
        self.model_adapter = model_adapter
        self.graders = dict(graders)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, request: HarnessRunRequest) -> EpisodePackage:
        """Run one trial without converting blocked or failed execution into output."""

        self.spec.verify_integrity()
        validate_persistable_content(self.spec.model_dump(mode="json"))
        if request.run_id != self.journal.metadata.run_id:
            raise HarnessRuntimeError(
                f"request run {request.run_id} does not match journal "
                f"{self.journal.metadata.run_id}"
            )
        if self.journal.snapshot().events:
            raise HarnessRuntimeError("task 262.4 runner requires an empty episode journal")

        started_at = self._now()
        trial_id = "trial_1"
        trajectory: list[TrajectoryStep] = []
        interventions: list[InterventionRecord] = []
        failures: list[FailureRecord] = []
        grader_results: list[GraderResult] = []
        tool_calls: list[ToolCallRecord] = []
        artifacts: list[EpisodeArtifact] = []
        safe_approvals: list[ApprovalGrant] = []
        provider_ref: str | None = None
        model_ref: str | None = None
        usage = ModelUsage()

        try:
            validate_persistable_content(request.model_dump(mode="json"))
        except SensitiveContentError:
            failures.append(
                self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.SECURITY,
                    code="sensitive_runtime_input",
                    component_id="harness.preflight",
                    retryable=False,
                    blocked=True,
                    message="Runtime input contained content forbidden from persistence.",
                    sequence=1,
                )
            )
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.PREFLIGHT,
                outcome=StepOutcome.BLOCKED,
                actor_id="harness.preflight",
                summary="Sensitive runtime input was blocked before model execution.",
            )
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=EpisodeOutcomeStatus.BLOCKED,
                summary="Harness preflight blocked sensitive runtime input.",
                output=None,
                provider_ref=None,
                model_ref=None,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )

        preflight_failure, safe_approvals, approval_interventions = self._preflight(
            request=request,
            trial_id=trial_id,
        )
        interventions.extend(approval_interventions)
        if preflight_failure is not None:
            failures.append(preflight_failure)
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.PREFLIGHT,
                outcome=StepOutcome.BLOCKED,
                actor_id="harness.preflight",
                summary=preflight_failure.message,
            )
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=EpisodeOutcomeStatus.BLOCKED,
                summary="Harness preflight policy blocked the trial.",
                output=None,
                provider_ref=None,
                model_ref=None,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )

        self._step(
            trajectory,
            trial_id=trial_id,
            kind=TrajectoryKind.PREFLIGHT,
            outcome=StepOutcome.SUCCEEDED,
            actor_id="harness.preflight",
            summary="Permissions, tools, context, and starting budgets passed preflight.",
            input_artifact_ids=request.context_artifact_ids,
        )
        self._append_event(
            request=request,
            status=EventStatus.STARTED,
            event_type="harness.started",
            action="Start bounded harness trial",
            payload={
                "episode_id": request.episode_id,
                "harness_spec_hash": self.spec.spec_hash,
                "task_input_hash": canonical_sha256(request.task_input),
            },
            output_artifact_ids=[],
        )

        invocation = ModelInvocationRequest(
            run_id=request.run_id,
            episode_id=request.episode_id,
            trial_id=trial_id,
            harness_spec_id=self.spec.spec_id,
            harness_spec_hash=self.spec.spec_hash,
            task_id=self.spec.task_contract.task_id,
            instructions=self.spec.task_contract.instructions,
            task_input=request.task_input,
            context_artifact_ids=request.context_artifact_ids,
            response_schema=self.spec.task_contract.output_contract.json_schema(),
            model_ref=self.spec.model_policy.model_ref,
            max_output_tokens=self.spec.model_policy.max_output_tokens,
            temperature=self.spec.model_policy.temperature,
            deliberation=self.spec.model_policy.deliberation,
        )

        try:
            result = self.model_adapter.invoke(invocation)
        except HarnessAdapterError as exc:
            failures.append(
                self._failure_from_adapter(exc, trial_id=trial_id, sequence=1)
            )
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.MODEL,
                outcome=StepOutcome.BLOCKED if exc.blocked else StepOutcome.FAILED,
                actor_id=exc.component_id,
                summary=_safe_error_message(exc),
            )
            status = (
                EpisodeOutcomeStatus.BLOCKED
                if exc.blocked
                else EpisodeOutcomeStatus.FAILED
            )
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=status,
                summary=(
                    "Model adapter was unavailable or policy-blocked."
                    if exc.blocked
                    else "Model adapter failed before a valid environment output."
                ),
                output=None,
                provider_ref=None,
                model_ref=None,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )
        except Exception as exc:
            message = _safe_error_message(exc)
            failures.append(
                self._failure(
                    trial_id=trial_id,
                    domain=self.spec.failure_attribution_policy.unknown_exception_domain,
                    code="unexpected_adapter_error",
                    component_id=self.model_adapter.adapter_id,
                    retryable=False,
                    blocked=False,
                    message=message,
                    sequence=1,
                )
            )
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.MODEL,
                outcome=StepOutcome.FAILED,
                actor_id=self.model_adapter.adapter_id,
                summary=message,
            )
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=EpisodeOutcomeStatus.FAILED,
                summary="Unexpected adapter failure prevented an environment outcome.",
                output=None,
                provider_ref=None,
                model_ref=None,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )

        provider_ref = result.provider_ref
        model_ref = result.model_ref
        usage = result.usage
        try:
            validate_persistable_content(result.model_dump(mode="json"))
            output = self._validate_model_result(result)
        except SensitiveContentError:
            return self._result_failure(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                trajectory=trajectory,
                interventions=interventions,
                approvals=safe_approvals,
                usage=usage,
                provider_ref=provider_ref,
                model_ref=model_ref,
                domain=FailureDomain.SECURITY,
                code="sensitive_model_output",
                component_id=result.adapter_id,
                message="Model output contained content forbidden from persistence.",
                blocked=False,
            )
        except StructuredOutputValidationError as exc:
            return self._result_failure(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                trajectory=trajectory,
                interventions=interventions,
                approvals=safe_approvals,
                usage=usage,
                provider_ref=provider_ref,
                model_ref=model_ref,
                domain=FailureDomain.OUTPUT_VALIDATION,
                code="invalid_structured_output",
                component_id=result.adapter_id,
                message=_safe_error_message(exc),
                blocked=False,
            )
        except HarnessRuntimeError as exc:
            return self._result_failure(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                trajectory=trajectory,
                interventions=interventions,
                approvals=safe_approvals,
                usage=usage,
                provider_ref=provider_ref,
                model_ref=model_ref,
                domain=FailureDomain.CONFIGURATION,
                code="adapter_contract_mismatch",
                component_id=result.adapter_id,
                message=_safe_error_message(exc),
                blocked=False,
            )

        artifacts = list(result.artifacts)
        tool_calls = list(result.tool_calls)
        for step in result.steps:
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=step.kind,
                outcome=step.outcome,
                actor_id=result.adapter_id,
                summary=step.summary,
                source_step_id=step.step_id,
                input_artifact_ids=step.input_artifact_ids,
                output_artifact_ids=step.output_artifact_ids,
            )
        if not result.steps:
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.MODEL,
                outcome=StepOutcome.SUCCEEDED,
                actor_id=result.adapter_id,
                summary="Model adapter returned a schema-valid structured object.",
            )

        policy_failure = self._post_model_policy_failure(
            request=request,
            trial_id=trial_id,
            result=result,
        )
        if result.attempts > 1:
            for index in range(1, result.attempts):
                interventions.append(
                    InterventionRecord(
                        intervention_id=f"intervention_retry_{index}",
                        trial_id=trial_id,
                        kind=InterventionKind.RETRY,
                        actor_id=result.adapter_id,
                        occurred_at=self._now(),
                        reason="Model adapter performed an explicitly bounded retry.",
                    )
                )
        if result.uncertainty > self.spec.entropy_intervention_policy.max_uncertainty:
            interventions.append(
                InterventionRecord(
                    intervention_id="intervention_entropy_stop",
                    trial_id=trial_id,
                    kind=InterventionKind.ENTROPY_STOP,
                    actor_id="harness.entropy",
                    occurred_at=self._now(),
                    reason="Reported uncertainty exceeded the frozen harness threshold.",
                )
            )
        if policy_failure is not None:
            failures.append(policy_failure)
            outcome = (
                StepOutcome.BLOCKED if policy_failure.blocked else StepOutcome.FAILED
            )
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=(
                    TrajectoryKind.TOOL
                    if policy_failure.domain == FailureDomain.TOOL
                    else TrajectoryKind.MODEL
                ),
                outcome=outcome,
                actor_id=policy_failure.component_id,
                summary=policy_failure.message,
            )
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=(
                    EpisodeOutcomeStatus.BLOCKED
                    if policy_failure.blocked
                    else EpisodeOutcomeStatus.FAILED
                ),
                summary="Post-model policy rejected the trial outcome.",
                output=None,
                provider_ref=provider_ref,
                model_ref=model_ref,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )

        grader_failure = self._run_graders(
            request=request,
            output=output,
            artifacts=artifacts,
            results=grader_results,
            trial_id=trial_id,
            trajectory=trajectory,
        )
        if grader_failure is not None:
            failures.append(grader_failure)
            return self._finish(
                request=request,
                trial_id=trial_id,
                started_at=started_at,
                status=EpisodeOutcomeStatus.FAILED,
                summary="A required grader failed to produce a valid decision.",
                output=None,
                provider_ref=provider_ref,
                model_ref=model_ref,
                trajectory=trajectory,
                graders=grader_results,
                usage=usage,
                interventions=interventions,
                approvals=safe_approvals,
                failures=failures,
                tool_calls=tool_calls,
                artifacts=artifacts,
            )

        passed_count = sum(result.passed for result in grader_results)
        pass_ratio = passed_count / len(grader_results)
        all_required = all(result.passed for result in grader_results)
        passed = pass_ratio >= self.spec.evaluation_policy.promotion_threshold
        if self.spec.evaluation_policy.require_all_graders:
            passed = passed and all_required
        status = (
            EpisodeOutcomeStatus.SUCCEEDED
            if passed
            else EpisodeOutcomeStatus.NEGATIVE_RESULT
        )
        self._step(
            trajectory,
            trial_id=trial_id,
            kind=TrajectoryKind.OUTCOME,
            outcome=(
                StepOutcome.SUCCEEDED if passed else StepOutcome.NEGATIVE_RESULT
            ),
            actor_id="harness.evaluation",
            summary=(
                "All frozen environment outcome gates passed."
                if passed
                else "The valid execution produced a negative graded outcome."
            ),
            output_artifact_ids=[artifact.artifact_id for artifact in artifacts],
        )
        return self._finish(
            request=request,
            trial_id=trial_id,
            started_at=started_at,
            status=status,
            summary=(
                "Bounded harness trial satisfied the frozen evaluation policy."
                if passed
                else "Bounded harness trial completed but did not satisfy promotion gates."
            ),
            output=output,
            provider_ref=provider_ref,
            model_ref=model_ref,
            trajectory=trajectory,
            graders=grader_results,
            usage=usage,
            interventions=interventions,
            approvals=safe_approvals,
            failures=failures,
            tool_calls=tool_calls,
            artifacts=artifacts,
        )

    def _preflight(
        self,
        *,
        request: HarnessRunRequest,
        trial_id: str,
    ) -> tuple[
        FailureRecord | None,
        list[ApprovalGrant],
        list[InterventionRecord],
    ]:
        policy = self.spec.permission_policy
        required = set(self.spec.task_contract.required_permission_ids)
        tools = {tool.tool_id: tool for tool in self.spec.tool_policy.tools}
        required_tools = set(self.spec.task_contract.required_tool_ids)
        missing_tools = sorted(required_tools - set(request.available_tool_ids))
        if missing_tools:
            return (
                self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.TOOL,
                    code="required_tool_unavailable",
                    component_id="harness.preflight",
                    retryable=True,
                    blocked=True,
                    message="Required tools are unavailable: " + ", ".join(missing_tools),
                    sequence=1,
                ),
                [],
                [],
            )
        if request.prior_tokens >= self.spec.cost_policy.max_total_tokens:
            return (
                self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.BUDGET,
                    code="token_budget_exhausted",
                    component_id="harness.budget",
                    retryable=False,
                    blocked=True,
                    message="Token budget was exhausted before model execution.",
                    sequence=1,
                ),
                [],
                [],
            )
        if request.prior_estimated_cost_usd > self.spec.cost_policy.max_estimated_cost_usd:
            return (
                self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.BUDGET,
                    code="cost_budget_exhausted",
                    component_id="harness.budget",
                    retryable=False,
                    blocked=True,
                    message="Cost budget was exhausted before model execution.",
                    sequence=1,
                ),
                [],
                [],
            )
        remaining_tool_calls = (
            self.spec.cost_policy.max_tool_calls - request.prior_tool_calls
        )
        if len(required_tools) > remaining_tool_calls:
            return (
                self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.BUDGET,
                    code="tool_call_budget_exhausted",
                    component_id="harness.budget",
                    retryable=False,
                    blocked=True,
                    message="Tool-call budget cannot cover the required tools.",
                    sequence=1,
                ),
                [],
                [],
            )
        for tool_id in required_tools:
            permission = tools[tool_id].required_permission_id
            if permission is not None:
                required.add(permission)

        approvals_by_permission = {
            approval.permission_id: approval for approval in request.approvals
        }
        used_approvals: list[ApprovalGrant] = []
        interventions: list[InterventionRecord] = []
        for permission in sorted(required):
            if permission in policy.forbidden_permission_ids:
                return (
                    self._permission_failure(
                        trial_id,
                        "forbidden_permission",
                        f"Permission {permission} is forbidden by policy.",
                    ),
                    used_approvals,
                    interventions,
                )
            if permission in policy.granted_permission_ids:
                continue
            if permission in policy.approval_required_permission_ids:
                approval = approvals_by_permission.get(permission)
                if approval is None or approval.decision != ApprovalDecision.APPROVED:
                    return (
                        self._permission_failure(
                            trial_id,
                            "approval_missing_or_denied",
                            f"Permission {permission} lacks an approved decision.",
                        ),
                        used_approvals,
                        interventions,
                    )
                if (
                    InterventionKind.HUMAN_APPROVAL
                    not in self.spec.entropy_intervention_policy.allowed_interventions
                ):
                    return (
                        self._permission_failure(
                            trial_id,
                            "human_approval_intervention_forbidden",
                            "Harness policy does not allow human approval interventions.",
                        ),
                        used_approvals,
                        interventions,
                    )
                used_approvals.append(approval)
                interventions.append(
                    InterventionRecord(
                        intervention_id=f"intervention_approval_{len(interventions) + 1}",
                        trial_id=trial_id,
                        kind=InterventionKind.HUMAN_APPROVAL,
                        actor_id=approval.actor_id,
                        occurred_at=approval.decided_at,
                        reason="A frozen permission gate consumed an explicit approval.",
                    )
                )
                continue
            if policy.deny_unknown:
                return (
                    self._permission_failure(
                        trial_id,
                        "unknown_permission",
                        f"Permission {permission} is not granted by policy.",
                    ),
                    used_approvals,
                    interventions,
                )
        if (
            len(used_approvals)
            > self.spec.entropy_intervention_policy.max_human_interventions
        ):
            return (
                self._permission_failure(
                    trial_id,
                    "human_intervention_budget_exhausted",
                    "Human approval count exceeds the frozen intervention budget.",
                ),
                used_approvals,
                interventions,
            )
        return None, used_approvals, interventions

    def _validate_model_result(
        self,
        result: ModelInvocationResult,
    ) -> dict[str, JsonValue]:
        policy = self.spec.model_policy
        if result.adapter_id != policy.adapter_id:
            raise HarnessRuntimeError("model adapter identity differs from model policy")
        if result.model_ref != policy.model_ref:
            raise HarnessRuntimeError("returned model_ref differs from model policy")
        missing_capabilities = sorted(
            set(policy.required_capabilities) - set(result.capabilities)
        )
        if missing_capabilities:
            raise HarnessRuntimeError(
                "model adapter lacks required capabilities: "
                + ", ".join(missing_capabilities)
            )
        if result.attempts > policy.max_attempts:
            raise HarnessRuntimeError("model attempts exceed model policy")
        return self.spec.task_contract.output_contract.validate_output(
            result.structured_output
        )

    def _post_model_policy_failure(
        self,
        *,
        request: HarnessRunRequest,
        trial_id: str,
        result: ModelInvocationResult,
    ) -> FailureRecord | None:
        usage = result.usage
        policy = self.spec.cost_policy
        if request.prior_tokens + usage.total_tokens > policy.max_total_tokens:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="token_budget_exceeded",
                component_id="harness.budget",
                retryable=False,
                blocked=True,
                message="Model usage exceeded the frozen token budget.",
                sequence=1,
            )
        if policy.require_known_cost and not usage.cost_known:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="unknown_model_cost",
                component_id="harness.budget",
                retryable=False,
                blocked=True,
                message="Model cost is unknown under a require-known-cost policy.",
                sequence=1,
            )
        if (
            request.prior_estimated_cost_usd + usage.estimated_cost_usd
            > policy.max_estimated_cost_usd
        ):
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="cost_budget_exceeded",
                component_id="harness.budget",
                retryable=False,
                blocked=True,
                message="Model usage exceeded the frozen cost budget.",
                sequence=1,
            )
        if usage.wall_time_seconds > policy.max_wall_time_seconds:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="wall_time_budget_exceeded",
                component_id="harness.budget",
                retryable=False,
                blocked=True,
                message="Model usage exceeded the frozen wall-time budget.",
                sequence=1,
            )
        tool_count = request.prior_tool_calls + len(result.tool_calls)
        if (
            tool_count > policy.max_tool_calls
            or len(result.tool_calls) > self.spec.tool_policy.max_tool_calls
        ):
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="tool_call_budget_exceeded",
                component_id="harness.budget",
                retryable=False,
                blocked=True,
                message="Tool usage exceeded the frozen tool-call budget.",
                sequence=1,
            )
        allowed_tools = {tool.tool_id for tool in self.spec.tool_policy.tools}
        available_tools = set(request.available_tool_ids)
        for call in result.tool_calls:
            if call.tool_id not in allowed_tools or call.tool_id not in available_tools:
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.PERMISSION,
                    code="unapproved_tool_call",
                    component_id=call.tool_id,
                    retryable=False,
                    blocked=False,
                    message=f"Tool call {call.call_id} used an unavailable or unapproved tool.",
                    sequence=1,
                )
            if call.outcome != StepOutcome.SUCCEEDED:
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.TOOL,
                    code=call.failure_code or "tool_failure",
                    component_id=call.tool_id,
                    retryable=True,
                    blocked=False,
                    message=f"Tool call {call.call_id} failed: {call.summary}",
                    sequence=1,
                )
        called_tools = {call.tool_id for call in result.tool_calls}
        missing_required = sorted(
            set(self.spec.task_contract.required_tool_ids) - called_tools
        )
        if missing_required:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.TOOL,
                code="required_tool_not_called",
                component_id="harness.tools",
                retryable=True,
                blocked=False,
                message="Required tools were not called: " + ", ".join(missing_required),
                sequence=1,
            )
        retry_count = result.attempts - 1
        entropy = self.spec.entropy_intervention_policy
        if retry_count > entropy.max_retries:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="retry_budget_exceeded",
                component_id=result.adapter_id,
                retryable=False,
                blocked=True,
                message="Adapter retries exceeded the frozen retry budget.",
                sequence=1,
            )
        if retry_count and InterventionKind.RETRY not in entropy.allowed_interventions:
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.PERMISSION,
                code="retry_intervention_forbidden",
                component_id=result.adapter_id,
                retryable=False,
                blocked=True,
                message="Adapter retried when retry interventions were forbidden.",
                sequence=1,
            )
        if (
            result.uncertainty > entropy.max_uncertainty
            and entropy.stop_when_uncertainty_exceeded
        ):
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.BUDGET,
                code="uncertainty_threshold_exceeded",
                component_id="harness.entropy",
                retryable=True,
                blocked=True,
                message="Model uncertainty exceeded the frozen threshold.",
                sequence=1,
            )
        if (
            self.spec.verification_policy.require_output_artifact_hashes
            and not result.artifacts
        ):
            return self._failure(
                trial_id=trial_id,
                domain=FailureDomain.VERIFICATION,
                code="output_artifact_hash_missing",
                component_id="harness.verification",
                retryable=True,
                blocked=False,
                message="Verification policy requires at least one hash-bound artifact.",
                sequence=1,
            )
        return None

    def _run_graders(
        self,
        *,
        request: HarnessRunRequest,
        output: dict[str, JsonValue],
        artifacts: list[EpisodeArtifact],
        results: list[GraderResult],
        trial_id: str,
        trajectory: list[TrajectoryStep],
    ) -> FailureRecord | None:
        specs = {
            grader.grader_id: grader
            for grader in self.spec.evaluation_policy.graders
        }
        for grader_id in self.spec.verification_policy.required_grader_ids:
            grader = self.graders.get(grader_id)
            grader_spec = specs[grader_id]
            if grader is None:
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.VERIFICATION,
                    code="grader_unavailable",
                    component_id=grader_id,
                    retryable=True,
                    blocked=False,
                    message=f"Required grader {grader_id} is unavailable.",
                    sequence=len(results) + 1,
                )
            if (
                grader.grader_version != grader_spec.version
                or grader.kind != grader_spec.kind
            ):
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.CONFIGURATION,
                    code="grader_identity_mismatch",
                    component_id=grader_id,
                    retryable=False,
                    blocked=False,
                    message=f"Required grader {grader_id} differs from its frozen spec.",
                    sequence=len(results) + 1,
                )
            try:
                result = grader.grade(
                    task=self.spec.task_contract,
                    task_input=request.task_input,
                    output=output,
                    artifacts=tuple(artifacts),
                )
                validate_persistable_content(result.model_dump(mode="json"))
            except Exception as exc:
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.VERIFICATION,
                    code="grader_error",
                    component_id=grader_id,
                    retryable=True,
                    blocked=False,
                    message=_safe_error_message(exc),
                    sequence=len(results) + 1,
                )
            if (
                result.grader_id != grader_id
                or result.grader_version != grader_spec.version
                or result.kind != grader_spec.kind
            ):
                return self._failure(
                    trial_id=trial_id,
                    domain=FailureDomain.CONFIGURATION,
                    code="grader_result_identity_mismatch",
                    component_id=grader_id,
                    retryable=False,
                    blocked=False,
                    message=f"Grader {grader_id} returned a mismatched identity.",
                    sequence=len(results) + 1,
                )
            passed = result.passed and result.score >= grader_spec.threshold
            result = result.model_copy(update={"passed": passed})
            results.append(result)
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.VERIFICATION,
                outcome=(
                    StepOutcome.SUCCEEDED
                    if passed
                    else StepOutcome.NEGATIVE_RESULT
                ),
                actor_id=grader_id,
                summary=result.reason,
                input_artifact_ids=result.evidence_artifact_ids,
            )
        return None

    def _result_failure(
        self,
        *,
        request: HarnessRunRequest,
        trial_id: str,
        started_at: datetime,
        trajectory: list[TrajectoryStep],
        interventions: list[InterventionRecord],
        approvals: list[ApprovalGrant],
        usage: ModelUsage,
        provider_ref: str,
        model_ref: str,
        domain: FailureDomain,
        code: str,
        component_id: str,
        message: str,
        blocked: bool,
    ) -> EpisodePackage:
        failure = self._failure(
            trial_id=trial_id,
            domain=domain,
            code=code,
            component_id=component_id,
            retryable=False,
            blocked=blocked,
            message=message,
            sequence=1,
        )
        self._step(
            trajectory,
            trial_id=trial_id,
            kind=TrajectoryKind.MODEL,
            outcome=StepOutcome.BLOCKED if blocked else StepOutcome.FAILED,
            actor_id=component_id,
            summary=message,
        )
        return self._finish(
            request=request,
            trial_id=trial_id,
            started_at=started_at,
            status=(
                EpisodeOutcomeStatus.BLOCKED
                if blocked
                else EpisodeOutcomeStatus.FAILED
            ),
            summary="Model result could not pass the frozen harness contract.",
            output=None,
            provider_ref=provider_ref,
            model_ref=model_ref,
            trajectory=trajectory,
            graders=[],
            usage=usage,
            interventions=interventions,
            approvals=approvals,
            failures=[failure],
            tool_calls=[],
            artifacts=[],
        )

    def _finish(
        self,
        *,
        request: HarnessRunRequest,
        trial_id: str,
        started_at: datetime,
        status: EpisodeOutcomeStatus,
        summary: str,
        output: dict[str, JsonValue] | None,
        provider_ref: str | None,
        model_ref: str | None,
        trajectory: list[TrajectoryStep],
        graders: list[GraderResult],
        usage: ModelUsage,
        interventions: list[InterventionRecord],
        approvals: list[ApprovalGrant],
        failures: list[FailureRecord],
        tool_calls: list[ToolCallRecord],
        artifacts: list[EpisodeArtifact],
    ) -> EpisodePackage:
        completed_at = self._now()
        output_hash = canonical_sha256(output) if output is not None else None
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        environment = EnvironmentOutcome(
            status=status,
            summary=summary,
            structured_output=output,
            output_hash=output_hash,
            artifact_ids=artifact_ids,
        )
        if not trajectory or trajectory[-1].kind != TrajectoryKind.OUTCOME:
            self._step(
                trajectory,
                trial_id=trial_id,
                kind=TrajectoryKind.OUTCOME,
                outcome=_step_outcome(status),
                actor_id="harness.outcome",
                summary=summary,
                output_artifact_ids=artifact_ids,
            )
        terminal_status = _event_status(status)
        terminal_event = self._append_event(
            request=request,
            status=terminal_status,
            event_type="harness.terminal",
            action="Record bounded harness terminal outcome",
            payload={
                "episode_id": request.episode_id,
                "outcome_status": status.value,
                "output_hash": output_hash,
                "grader_ids": [grader.grader_id for grader in graders],
                "failure_codes": [failure.code for failure in failures],
                "total_tokens": usage.total_tokens,
                "estimated_cost_usd": usage.estimated_cost_usd,
                "tool_call_count": len(tool_calls),
            },
            output_artifact_ids=artifact_ids,
        )
        snapshot = self.journal.snapshot()
        if snapshot.seal is None:
            raise HarnessRuntimeError("terminal harness event did not produce a journal seal")
        cost = EpisodeCostRecord(
            cost_id="cost_1",
            trial_id=trial_id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
            cost_known=usage.cost_known,
            wall_time_seconds=usage.wall_time_seconds,
            tool_calls=len(tool_calls),
        )
        trial = TrialRecord(
            trial_id=trial_id,
            sequence=1,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            provider_ref=provider_ref,
            model_ref=model_ref,
            trajectory_step_ids=[step.step_id for step in trajectory],
            tool_call_ids=[call.call_id for call in tool_calls],
            grader_ids=[grader.grader_id for grader in graders],
            failure_ids=[failure.failure_id for failure in failures],
            cost_id=cost.cost_id,
            output_hash=output_hash,
        )
        return EpisodePackage.create(
            episode_id=request.episode_id,
            run_id=request.run_id,
            harness_spec_id=self.spec.spec_id,
            harness_spec_hash=self.spec.spec_hash,
            task_contract=self.spec.task_contract,
            task_input_hash=canonical_sha256(request.task_input),
            started_at=started_at,
            completed_at=completed_at,
            trials=[trial],
            trajectory=trajectory,
            final_outcome=environment,
            graders=graders,
            costs=[cost],
            interventions=interventions,
            approvals=approvals,
            failures=failures,
            tool_calls=tool_calls,
            artifacts=artifacts,
            journal_terminal_event_id=terminal_event.event_id,
            journal_terminal_event_hash=terminal_event.event_hash,
            journal_lineage_hash=snapshot.lineage_hash,
            journal_seal_hash=snapshot.seal.seal_hash,
        )

    def _append_event(
        self,
        *,
        request: HarnessRunRequest,
        status: EventStatus,
        event_type: str,
        action: str,
        payload: dict[str, JsonValue],
        output_artifact_ids: list[str],
    ) -> RunEvent:
        snapshot = self.journal.snapshot(require_complete_terminal=False)
        sequence = len(snapshot.events) + 1
        if snapshot.events:
            parent = snapshot.events[-1]
            parent_event_id = parent.event_id
            parent_event_hash = parent.event_hash
            parent_run_id = None
        elif self.journal.metadata.fork_anchor is not None:
            anchor = self.journal.metadata.fork_anchor
            parent_event_id = anchor.checkpoint_event_id
            parent_event_hash = anchor.checkpoint_event_hash
            parent_run_id = anchor.parent_run_id
        else:
            parent_event_id = None
            parent_event_hash = None
            parent_run_id = None
        identity = canonical_sha256(
            {
                "run_id": request.run_id,
                "episode_id": request.episode_id,
                "sequence": sequence,
                "event_type": event_type,
            }
        )
        event = RunEvent.create(
            event_id=f"evt_{identity[:40]}",
            run_id=request.run_id,
            task_id=self.spec.task_contract.task_id,
            sequence=sequence,
            occurred_at=self._now(),
            actor=self._ACTOR,
            event_type=event_type,
            status=status,
            action=action,
            parent_event_id=parent_event_id,
            parent_event_hash=parent_event_hash,
            parent_run_id=parent_run_id,
            input_artifact_ids=request.context_artifact_ids,
            output_artifact_ids=output_artifact_ids,
            idempotency_key=f"idem_{identity}",
            payload=payload,
        )
        self.journal.append(
            event,
            expected_lineage_hash=snapshot.lineage_hash,
        )
        return event

    def _step(
        self,
        trajectory: list[TrajectoryStep],
        *,
        trial_id: str,
        kind: TrajectoryKind,
        outcome: StepOutcome,
        actor_id: str,
        summary: str,
        source_step_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
        output_artifact_ids: list[str] | None = None,
    ) -> None:
        bounded = summary[: self.spec.observability_policy.max_step_summary_chars]
        validate_persistable_content(bounded)
        sequence = len(trajectory) + 1
        trajectory.append(
            TrajectoryStep(
                step_id=f"step_{sequence}",
                sequence=sequence,
                trial_id=trial_id,
                kind=kind,
                outcome=outcome,
                actor_id=actor_id,
                occurred_at=self._now(),
                summary=bounded,
                source_step_id=source_step_id,
                input_artifact_ids=input_artifact_ids or [],
                output_artifact_ids=output_artifact_ids or [],
            )
        )

    def _permission_failure(
        self,
        trial_id: str,
        code: str,
        message: str,
    ) -> FailureRecord:
        return self._failure(
            trial_id=trial_id,
            domain=FailureDomain.PERMISSION,
            code=code,
            component_id="harness.permissions",
            retryable=False,
            blocked=True,
            message=message,
            sequence=1,
        )

    @staticmethod
    def _failure_from_adapter(
        error: HarnessAdapterError,
        *,
        trial_id: str,
        sequence: int,
    ) -> FailureRecord:
        return HarnessRunner._failure(
            trial_id=trial_id,
            domain=error.domain,
            code=error.code,
            component_id=error.component_id,
            retryable=error.retryable,
            blocked=error.blocked,
            message=_safe_error_message(error),
            sequence=sequence,
        )

    @staticmethod
    def _failure(
        *,
        trial_id: str,
        domain: FailureDomain,
        code: str,
        component_id: str,
        retryable: bool,
        blocked: bool,
        message: str,
        sequence: int,
    ) -> FailureRecord:
        validate_persistable_content(message)
        return FailureRecord(
            failure_id=f"failure_{sequence}",
            trial_id=trial_id,
            domain=domain,
            code=code,
            component_id=component_id,
            retryable=retryable,
            blocked=blocked,
            message=message,
        )

    def _now(self) -> datetime:
        return _require_utc(self.clock(), label="harness clock")


def _unique_model_ids(
    values: Sequence[KernelContract],
    field: str,
    label: str,
) -> set[str]:
    ids = [str(getattr(value, field)) for value in values]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} IDs must be unique")
    return set(ids)


def _safe_error_message(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    message = message[:1024]
    try:
        validate_persistable_content(message)
    except SensitiveContentError:
        return "Sensitive error details were suppressed."
    return message


def _event_status(status: EpisodeOutcomeStatus) -> EventStatus:
    mapping = {
        EpisodeOutcomeStatus.SUCCEEDED: EventStatus.SUCCEEDED,
        EpisodeOutcomeStatus.NEGATIVE_RESULT: EventStatus.NEGATIVE_RESULT,
        EpisodeOutcomeStatus.FAILED: EventStatus.FAILED,
        EpisodeOutcomeStatus.BLOCKED: EventStatus.BLOCKED,
    }
    return mapping[status]


def _step_outcome(status: EpisodeOutcomeStatus) -> StepOutcome:
    return StepOutcome(status.value)


def _matches_json_field_type(value: object, expected: JsonFieldType) -> bool:
    if expected == JsonFieldType.STRING:
        return isinstance(value, str)
    if expected == JsonFieldType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == JsonFieldType.NUMBER:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == JsonFieldType.BOOLEAN:
        return isinstance(value, bool)
    if expected == JsonFieldType.OBJECT:
        return isinstance(value, dict)
    return isinstance(value, list)


def _sorted_unique(values: list[str], *, label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")
    return sorted(values)


def _require_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)
