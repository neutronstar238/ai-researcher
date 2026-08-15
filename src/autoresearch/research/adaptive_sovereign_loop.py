"""Adaptive, memory-sovereign research exploration with stage-local strictness.

This module deliberately separates two concerns that fixed research pipelines
often conflate:

* the exploration loop may branch, retrieve, analogise, delegate, run bounded
  probes, criticise, mutate its *workflow proposal*, or abandon a branch in any
  order chosen by the configured model; and
* evidence promotion remains deterministic and fail-closed, with external
  feedback, independent verification, safety, execution, and publication
  authority kept outside the model.

The orchestrator supplies capabilities and mechanical gates, never a scientific
hypothesis or a pre-written research plan.  Every visible model response and
reasoning payload is appended to the private raw-memory store before it can
change loop state.  Derived branch state is content-addressed and rebuildable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import Field, JsonValue, StringConstraints, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemoryCapture,
    RawMemoryError,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_MIN_REASONING_CHARACTERS = 200
_DEFAULT_THINKING_BUDGET = 4_000
_MAX_RECENT_EVENTS_IN_PROMPT = 8
_MAX_BRANCHES_IN_PROMPT = 24
_RETRIEVAL_QUERY_BODY_PATTERN = re.compile(
    r"^检索查询\s*[：:]\s*(?P<query>[^\r\n]+)(?:\r?\n(?P<prose>[\s\S]*))?$"
)
_RETRIEVAL_QUERY_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]*")
_RETRIEVAL_QUERY_PHRASE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.+-]*(?: [A-Za-z][A-Za-z0-9_.+-]*){0,3}$"
)
_MAX_RETRIEVAL_QUERY_TERM_CHARACTERS = 80
_MAX_RETRIEVAL_QUERY_TOTAL_CHARACTERS = 320
_LATIN_LETTER_RUN_PATTERN = re.compile(r"[A-Za-z]+")
_MAX_DISCOUNTED_LATIN_RUN_CHARACTERS = 16
_DISCOUNTED_LATIN_RUN_WEIGHT = 4
_MEMORY_CONTROL_USE_BOUNDARY_CN = (
    "只报告历史是否已离开最近八轮窗口、距上次记忆复核的轮数及"
    "既有暴露/消费计数；不含科研正文、不指定下一算子，也不证明"
    "应当使用记忆或记忆带来收益。你仍需在多个可用算子中自主决定。"
)
_WORKFLOW_PROPOSAL_HISTORY_BOUNDARY_CN = (
    "这是配置Qwen此前自行提出的只追加工作流候选，不是编排器指令。每条中的“本轮”或"
    "“下一轮”只相对于authored_step_index解释，不能自动延续到当前轮；必须结合最新反馈"
    "重新判断，可保留、修改、搁置或推翻。原文永久保留不等于当前仍应服从。"
)
_MEMORY_RECALL_CAPABILITY_BOUNDARY_CN = (
    "该契约只说明consolidate_dreaming能做什么及其成本，不说明本轮应当选择它。"
    "主Agent只有在完整历史中的早期约束、失败、纠错或来源可能影响当前判断时才自行权衡；"
    "保存、召回、显式消费与任务收益仍是四个不同门。"
)

RetrievalQueryPhrase = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=_MAX_RETRIEVAL_QUERY_TERM_CHARACTERS,
        pattern=_RETRIEVAL_QUERY_PHRASE_PATTERN.pattern,
    ),
]


class AdaptiveResearchLoopError(RuntimeError):
    """Raised when the adaptive loop cannot preserve its process contract."""


class ResearchLoopZone(str, Enum):
    """Epistemic zones with intentionally different levels of strictness."""

    OPEN_EXPLORATION = "open_exploration"
    EVIDENCE_PROMOTION = "evidence_promotion"
    FORMAL_VERIFICATION = "formal_verification"
    WAITING_HUMAN_SCOPE = "waiting_human_scope"
    TERMINAL = "terminal"


class AdaptiveLoopRunStatus(str, Enum):
    """Durable controller outcomes; only one is an execution authorization."""

    RUNNING = "running"
    PAUSED_HUMAN_SCOPE = "paused_human_scope"
    PAUSED_BUDGET = "paused_budget"
    PAUSED_PLATEAU = "paused_plateau"
    PAUSED_VERIFIER_REQUIRED = "paused_verifier_required"
    STOPPED_BY_MODEL = "stopped_by_model"
    BLOCKED = "blocked"


class ResearchBranchStatus(str, Enum):
    """Lifecycle of one retained exploration branch."""

    ACTIVE = "active"
    ABANDONED = "abandoned"
    PROMOTION_REJECTED = "promotion_rejected"
    PENDING_VERIFICATION = "pending_verification"
    VERIFICATION_REJECTED = "verification_rejected"
    READY_FOR_HUMAN_SCOPE = "ready_for_human_scope"


class ResearchOperator(str, Enum):
    """Capability vocabulary exposed to the model, not a fixed step order."""

    RETRIEVE_EVIDENCE = "retrieve_evidence"
    BRANCH_HYPOTHESIS = "branch_hypothesis"
    ANALOGICAL_TRANSFER = "analogical_transfer"
    REFRAME_QUESTION = "reframe_question"
    DECOMPOSE_UNCERTAINTY = "decompose_uncertainty"
    CONSULT_TEMPORARY_AGENTS = "consult_temporary_agents"
    RUN_SANDBOX_PROBE = "run_sandbox_probe"
    ADVERSARIAL_CRITIQUE = "adversarial_critique"
    MUTATE_WORKFLOW_PROPOSAL = "mutate_workflow_proposal"
    CONSOLIDATE_DREAMING = "consolidate_dreaming"
    PROMOTE_BRANCH = "promote_branch"
    ABANDON_BRANCH = "abandon_branch"
    STOP_EXPLORATION = "stop_exploration"


class FeedbackOrigin(str, Enum):
    """Origin of feedback returned to the next model turn."""

    ORCHESTRATOR = "orchestrator"
    EXTERNAL_RETRIEVAL = "external_retrieval"
    SANDBOX_TOOL = "sandbox_tool"
    TEMPORARY_AGENT = "temporary_agent"
    INDEPENDENT_VERIFIER = "independent_verifier"
    DREAMING_PROJECTION = "dreaming_projection"


class FeedbackStatus(str, Enum):
    """Outcome of one capability invocation."""

    SUCCEEDED = "succeeded"
    NEGATIVE_RESULT = "negative_result"
    FAILED = "failed"
    BLOCKED = "blocked"


def _contains_chinese(value: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or character == "\u3007"
        for character in value
    )


def _chinese_and_latin_language_loads(value: str) -> tuple[int, int]:
    """Measure Chinese prose without treating one technical identifier as a paragraph.

    Short Latin runs are capped individually, so a hyphenated Skill identifier remains a
    bounded technical annotation.  Pathologically long runs retain their full weight;
    this preserves the adversarial guard against hiding arbitrarily large English payloads
    in one token.
    """

    chinese_count = sum(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or character == "\u3007"
        for character in value
    )
    latin_load = sum(
        len(run)
        if len(run) > _MAX_DISCOUNTED_LATIN_RUN_CHARACTERS
        else min(len(run), _DISCOUNTED_LATIN_RUN_WEIGHT)
        for run in _LATIN_LETTER_RUN_PATTERN.findall(value)
    )
    return chinese_count, latin_load


def _require_chinese(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not _contains_chinese(normalized):
        raise ValueError(f"{field_name} 必须包含中文")
    return normalized


def _require_chinese_dominant(value: str, *, field_name: str) -> str:
    normalized = _require_chinese(value, field_name=field_name)
    chinese_count, latin_load = _chinese_and_latin_language_loads(normalized)
    if latin_load > chinese_count:
        raise ValueError(f"{field_name} 必须以中文为主；技术标识、公式和论文原题可保留原文")
    return normalized


def _split_retrieval_action_body(value: str) -> tuple[tuple[str, ...], str] | None:
    """Split a model-authored retrieval payload without inventing query content."""

    normalized = value.strip()
    matched = _RETRIEVAL_QUERY_BODY_PATTERN.fullmatch(normalized)
    if matched is None:
        return None
    query = matched.group("query").strip()
    tokens = tuple(_RETRIEVAL_QUERY_TOKEN_PATTERN.findall(query))
    if not tokens or query != " ".join(tokens):
        return None
    return tokens, (matched.group("prose") or "").strip()


def _require_retrieval_action_body(value: str) -> str:
    """Validate a technical query line separately from optional Chinese prose."""

    normalized = value.strip()
    parsed = _split_retrieval_action_body(normalized)
    if parsed is None:
        raise ValueError(
            "action_body_cn 在 retrieve_evidence 下必须以“检索查询：”和ASCII学术词开头"
        )
    tokens, prose = parsed
    if not _retrieval_query_tokens_are_valid(tokens, require_unique=False):
        raise ValueError("retrieve_evidence 的检索查询必须包含3至10个ASCII学术词")
    if not _retrieval_query_tokens_are_valid(tokens):
        raise ValueError("retrieve_evidence 的检索查询词必须互异")
    if prose:
        _require_chinese_dominant(prose, field_name="action_body_cn 检索说明")
    return normalized


def _retrieval_query_tokens_are_valid(
    tokens: Sequence[str],
    *,
    require_unique: bool = True,
) -> bool:
    if not 3 <= len(tokens) <= 10:
        return False
    return not require_unique or len({token.casefold() for token in tokens}) == len(tokens)


def _retrieval_query_terms_are_valid(
    values: Any,
    *,
    require_bounded_count: bool = True,
) -> bool:
    """Validate model-selected structured search phrases without rewriting them."""

    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        return False
    if require_bounded_count and not 3 <= len(values) <= 10:
        return False
    if any(
        item != item.strip()
        or _RETRIEVAL_QUERY_PHRASE_PATTERN.fullmatch(item) is None
        or len(item) > _MAX_RETRIEVAL_QUERY_TERM_CHARACTERS
        for item in values
    ):
        return False
    if sum(len(item) for item in values) + max(0, len(values) - 1) > (
        _MAX_RETRIEVAL_QUERY_TOTAL_CHARACTERS
    ):
        return False
    return len({item.casefold() for item in values}) == len(values)


def _ordered_unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if item.strip()))


class AdaptiveLoopPolicy(KernelContract):
    """Budget and invariant policy; it does not prescribe scientific content."""

    schema_version: Literal[
        "adaptive-sovereign-loop-policy-v1",
        "adaptive-sovereign-loop-policy-v2",
        "adaptive-sovereign-loop-policy-v3",
    ] = "adaptive-sovereign-loop-policy-v1"
    policy_id: StableId
    max_steps: int = Field(default=24, ge=1, le=500)
    max_model_calls: int = Field(default=24, ge=1, le=500)
    max_external_actions: int = Field(default=12, ge=0, le=500)
    max_temporary_agents: int = Field(default=14, ge=0, le=224)
    max_active_branches: int = Field(default=12, ge=1, le=128)
    max_consecutive_stalls: int = Field(default=4, ge=1, le=50)
    maximum_skill_contexts: int = Field(default=5, ge=0, le=12)
    minimum_reasoning_characters: int = Field(
        default=_MIN_REASONING_CHARACTERS,
        ge=_MIN_REASONING_CHARACTERS,
        le=100_000,
    )
    thinking_budget: int = Field(default=_DEFAULT_THINKING_BUDGET, ge=256, le=32_000)
    open_operator_order: Literal[True] = True
    raw_memory_required: Literal[True] = True
    archive_all_branches: Literal[True] = True
    exploration_outputs_are_evidence: Literal[False] = False
    external_feedback_required_for_promotion: Literal[True] = True
    independent_verification_required: Literal[True] = True
    sandbox_only_execution: Literal[True] = True
    human_scope_approval_required_before_formal_execution: Literal[True] = True
    model_may_approve_or_publish: Literal[False] = False
    permission_expansion_allowed: Literal[False] = False


class AdaptiveMemoryControlObservationContent(KernelContract):
    """Text-free memory availability state; it never selects the next action."""

    schema_version: Literal["adaptive-memory-control-observation-v1"] = (
        "adaptive-memory-control-observation-v1"
    )
    retained_event_count: int = Field(ge=0, le=500)
    recent_prompt_event_window_size: Literal[8] = 8
    retained_events_outside_recent_prompt: int = Field(ge=0, le=500)
    selected_branch_retained_event_count: int = Field(ge=0, le=500)
    selected_branch_events_outside_recent_prompt: int = Field(ge=0, le=500)
    turns_since_any_memory_review: int = Field(ge=0, le=500)
    selected_branch_turns_since_memory_review: int = Field(ge=0, le=500)
    prior_memory_review_count: int = Field(ge=0, le=500)
    prior_memory_exposure_count: int = Field(ge=0, le=6_000)
    prior_model_declared_consumption_count: int = Field(ge=0, le=6_000)
    reviewable_history_outside_recent_prompt_exists: bool
    memory_review_operator_available: bool
    memory_review_remains_optional: Literal[True] = True
    observation_does_not_select_an_operator: Literal[True] = True
    observation_contains_research_text: Literal[False] = False
    observation_is_scientific_evidence: Literal[False] = False
    memory_benefit_verified: Literal[False] = False

    @model_validator(mode="after")
    def _validate_counts(self) -> AdaptiveMemoryControlObservationContent:
        expected_outside = max(
            0,
            self.retained_event_count - self.recent_prompt_event_window_size,
        )
        if self.retained_events_outside_recent_prompt != expected_outside:
            raise ValueError("memory-control outside-window event count mismatch")
        if self.selected_branch_retained_event_count > self.retained_event_count:
            raise ValueError("memory-control branch event count exceeds retained history")
        if (
            self.selected_branch_events_outside_recent_prompt
            > self.selected_branch_retained_event_count
            or self.selected_branch_events_outside_recent_prompt
            > self.retained_events_outside_recent_prompt
        ):
            raise ValueError("memory-control branch outside-window count is impossible")
        if self.turns_since_any_memory_review > self.retained_event_count:
            raise ValueError("memory-control review distance exceeds retained history")
        if (
            self.selected_branch_turns_since_memory_review
            > self.selected_branch_retained_event_count
        ):
            raise ValueError("memory-control branch review distance exceeds branch history")
        if self.prior_memory_review_count > self.retained_event_count:
            raise ValueError("memory-control review count exceeds retained history")
        if self.reviewable_history_outside_recent_prompt_exists != bool(expected_outside):
            raise ValueError("memory-control reviewable-history flag mismatch")
        return self


class AdaptiveMemoryControlObservation(AdaptiveMemoryControlObservationContent):
    """Content-addressed projection of memory state made visible to the model."""

    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveMemoryControlObservation:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"observation_hash"}))
        if self.observation_hash != expected:
            raise ValueError("adaptive memory-control observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveMemoryControlObservation:
        content = AdaptiveMemoryControlObservationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, observation_hash=canonical_sha256(payload))


class AdaptiveWorkflowProposalContextContent(KernelContract):
    """Temporally scoped view of one retained model-authored workflow proposal."""

    schema_version: Literal["adaptive-workflow-proposal-context-v1"] = (
        "adaptive-workflow-proposal-context-v1"
    )
    authored_step_index: int = Field(ge=1, le=500)
    age_in_turns: int = Field(ge=1, le=500)
    source_interaction_hash: Sha256
    proposal_cn: str = Field(min_length=1, max_length=16_000)
    proposal_sha256: Sha256
    authored_by_configured_model: Literal[True] = True
    retained_append_only: Literal[True] = True
    advisory_history_not_current_instruction: Literal[True] = True
    relative_turn_language_scoped_to_authored_step: Literal[True] = True
    may_be_reconsidered_or_superseded: Literal[True] = True
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("proposal_cn")
    @classmethod
    def _validate_proposal_cn(cls, value: str) -> str:
        return _require_chinese_dominant(value, field_name="proposal_cn")

    @model_validator(mode="after")
    def _validate_proposal_hash(self) -> AdaptiveWorkflowProposalContextContent:
        expected = hashlib.sha256(self.proposal_cn.encode("utf-8")).hexdigest()
        if self.proposal_sha256 != expected:
            raise ValueError("adaptive workflow proposal text hash mismatch")
        return self


class AdaptiveWorkflowProposalContext(AdaptiveWorkflowProposalContextContent):
    """Content-addressed prompt projection; the underlying proposal is never rewritten."""

    context_hash: Sha256

    @model_validator(mode="after")
    def _validate_context_hash(self) -> AdaptiveWorkflowProposalContext:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"context_hash"}))
        if self.context_hash != expected:
            raise ValueError("adaptive workflow proposal context hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveWorkflowProposalContext:
        content = AdaptiveWorkflowProposalContextContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, context_hash=canonical_sha256(payload))


class AdaptiveMemoryRecallCapabilityContractContent(KernelContract):
    """Text-free affordance contract for optional sovereign-memory review."""

    schema_version: Literal["adaptive-memory-recall-capability-contract-v1"] = (
        "adaptive-memory-recall-capability-contract-v1"
    )
    operator_id: Literal["consolidate_dreaming"] = "consolidate_dreaming"
    query_authored_by_current_main_agent: Literal[True] = True
    reads_private_append_only_raw_history: Literal[True] = True
    searches_complete_retained_history: Literal[True] = True
    returns_exact_source_excerpts_and_hashes: Literal[True] = True
    writes_only_rebuildable_derived_projection: Literal[True] = True
    mutates_or_deletes_raw_records: Literal[False] = False
    external_action_cost: Literal[1] = 1
    selection_remains_optional: Literal[True] = True
    establishes_memory_consumption: Literal[False] = False
    establishes_task_benefit: Literal[False] = False
    is_scientific_evidence: Literal[False] = False


class AdaptiveMemoryRecallCapabilityContract(AdaptiveMemoryRecallCapabilityContractContent):
    """Content-addressed capability facts, separate from any action recommendation."""

    contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_contract_hash(self) -> AdaptiveMemoryRecallCapabilityContract:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"contract_hash"}))
        if self.contract_hash != expected:
            raise ValueError("adaptive memory-recall capability contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveMemoryRecallCapabilityContract:
        content = AdaptiveMemoryRecallCapabilityContractContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, contract_hash=canonical_sha256(payload))


class LoopSkillContext(KernelContract):
    """One separately injected, read-only skill; never a scientific source."""

    skill_id: StableId
    source_ref: str = Field(min_length=1, max_length=2048)
    content: str = Field(min_length=1, max_length=80_000)
    content_sha256: Sha256
    read_only: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_content_hash(self) -> LoopSkillContext:
        expected = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("adaptive-loop skill content hash mismatch")
        return self


class AdaptiveExternalTurnContextContent(KernelContract):
    """One preregistered exogenous observation injected before a model turn."""

    schema_version: Literal["adaptive-external-turn-context-v1"] = (
        "adaptive-external-turn-context-v1"
    )
    context_id: StableId
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1, le=500)
    source_ref: str = Field(min_length=1, max_length=2_048)
    content_cn: str = Field(min_length=1, max_length=8_000)
    content_sha256: Sha256
    raw_binding: RawMemoryBinding
    controller_visible: Literal[True] = True
    provider_generated_context: Literal[True] = True
    contains_required_operator: Literal[False] = False
    contains_hidden_evaluation: Literal[False] = False
    human_authored_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("content_cn")
    @classmethod
    def _validate_chinese_content(cls, value: str) -> str:
        return _require_chinese(value, field_name="content_cn")

    @model_validator(mode="after")
    def _validate_content_hash(self) -> AdaptiveExternalTurnContextContent:
        expected = hashlib.sha256(self.content_cn.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("external turn context content hash mismatch")
        return self


class AdaptiveExternalTurnContext(AdaptiveExternalTurnContextContent):
    context_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveExternalTurnContext:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"context_hash"}))
        if self.context_hash != expected:
            raise ValueError("external turn context hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveExternalTurnContext:
        content = AdaptiveExternalTurnContextContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, context_hash=canonical_sha256(payload))


class AdaptiveResearchSeed(KernelContract):
    """A human may set scope and objective, but supplies no scientific answer."""

    schema_version: Literal["adaptive-research-seed-v1"] = "adaptive-research-seed-v1"
    loop_id: StableId
    project_id: StableId
    objective_cn: str = Field(min_length=1, max_length=8_000)
    scope_cn: str = Field(min_length=1, max_length=8_000)
    raw_seed_binding: RawMemoryBinding
    supplied_hypothesis: Literal[None] = None
    supplied_method: Literal[None] = None
    supplied_research_plan: Literal[None] = None
    human_authored_scientific_prose_count: Literal[0] = 0

    @field_validator("objective_cn", "scope_cn")
    @classmethod
    def _validate_chinese_seed(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)


class TemporaryResearchTask(KernelContract):
    """A bounded content-only task requested by the current main agent."""

    task_id: StableId
    role_cn: str = Field(min_length=1, max_length=256)
    question_cn: str = Field(min_length=1, max_length=4_000)
    selected_skill_ids: list[StableId] = Field(default_factory=list, max_length=5)
    can_delegate: Literal[False] = False
    can_execute: Literal[False] = False
    can_approve: Literal[False] = False
    can_publish: Literal[False] = False

    @field_validator("role_cn", "question_cn")
    @classmethod
    def _validate_chinese_task(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)

    @field_validator("selected_skill_ids")
    @classmethod
    def _normalize_skills(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("temporary task skill IDs must be unique and non-empty")
        return normalized


class PromotionDraft(KernelContract):
    """Model-authored request to leave exploration; it is not an approval."""

    research_question_cn: str = Field(min_length=1, max_length=8_000)
    hypothesis_cn: str = Field(min_length=1, max_length=8_000)
    mechanism_cn: str = Field(min_length=1, max_length=8_000)
    falsifier_cn: str = Field(min_length=1, max_length=8_000)
    decisive_test_cn: str = Field(min_length=1, max_length=8_000)
    baseline_and_control_cn: str = Field(min_length=1, max_length=8_000)
    novelty_boundary_cn: str = Field(min_length=1, max_length=8_000)
    known_uncertainties_cn: list[str] = Field(min_length=1, max_length=16)
    source_refs: list[str] = Field(default_factory=list, max_length=64)
    requested_cpu_count: int = Field(default=1, ge=1, le=64)
    requested_memory_mb: int = Field(default=1_024, ge=128, le=262_144)
    requested_walltime_seconds: int = Field(default=60, ge=1, le=86_400)
    innovation_verified: Literal[False] = False
    scientific_evidence_established: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator(
        "research_question_cn",
        "hypothesis_cn",
        "mechanism_cn",
        "falsifier_cn",
        "decisive_test_cn",
        "baseline_and_control_cn",
        "novelty_boundary_cn",
    )
    @classmethod
    def _validate_chinese_fields(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)

    @field_validator("known_uncertainties_cn")
    @classmethod
    def _validate_uncertainties(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("known uncertainties must be unique and non-empty")
        for item in normalized:
            _require_chinese_dominant(item, field_name="known_uncertainties_cn")
        return normalized

    @field_validator("source_refs")
    @classmethod
    def _normalize_source_refs(cls, value: list[str]) -> list[str]:
        return _ordered_unique(value)


class ModelMemoryExposure(KernelContract):
    """One exact Dreaming excerpt made visible to a later model turn."""

    schema_version: Literal["adaptive-model-memory-exposure-v1"] = (
        "adaptive-model-memory-exposure-v1"
    )
    dreaming_step_index: int = Field(ge=1, le=500)
    selection_hash: Sha256
    record_id: StableId
    payload_sha256: Sha256
    excerpt_sha256: Sha256
    excerpt_text: str = Field(min_length=1, max_length=8_000)
    controller_visible: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_excerpt_hash(self) -> ModelMemoryExposure:
        expected = hashlib.sha256(self.excerpt_text.encode("utf-8")).hexdigest()
        if self.excerpt_sha256 != expected:
            raise ValueError("model memory exposure excerpt hash mismatch")
        return self


class ModelMemoryConsumptionClaim(KernelContract):
    """A model-authored, source-grounded claim that it used one recalled fact."""

    schema_version: Literal["adaptive-model-memory-consumption-claim-v1"] = (
        "adaptive-model-memory-consumption-claim-v1"
    )
    dreaming_step_index: int = Field(ge=1, le=500)
    selection_hash: Sha256
    record_id: StableId
    payload_sha256: Sha256
    excerpt_sha256: Sha256
    fact_cn: str = Field(min_length=4, max_length=8_000)
    application_cn: str = Field(min_length=4, max_length=8_000)
    model_declared_consumption_only: Literal[True] = True
    establishes_causal_memory_benefit: Literal[False] = False
    is_scientific_evidence: Literal[False] = False

    @field_validator("fact_cn", "application_cn")
    @classmethod
    def _validate_chinese_claim(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)


class ModelResearchActionDraft(KernelContract):
    """The only scientific action content accepted from the configured model."""

    schema_version: Literal[
        "adaptive-research-action-draft-v1",
        "adaptive-research-action-draft-v2",
        "adaptive-research-action-draft-v3",
    ] = "adaptive-research-action-draft-v3"
    step_index: int = Field(ge=1)
    branch_id: StableId
    operator: ResearchOperator
    action_title_cn: str = Field(min_length=1, max_length=1_000)
    action_body_cn: str = Field(min_length=1, max_length=16_000)
    retrieval_query_terms: list[RetrievalQueryPhrase] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Only for retrieve_evidence: 3-10 unique model-selected ASCII search phrases; "
            "each phrase contains 1-4 whitespace-separated technical tokens."
        ),
    )
    reason_for_choice_cn: str = Field(min_length=1, max_length=8_000)
    expected_information_gain_cn: str = Field(min_length=1, max_length=8_000)
    working_hypothesis_cn: str | None = Field(default=None, max_length=8_000)
    selected_skill_ids: list[StableId] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=64)
    memory_consumption_claims: list[ModelMemoryConsumptionClaim] = Field(
        default_factory=list,
        max_length=12,
    )
    temporary_tasks: list[TemporaryResearchTask] = Field(
        default_factory=list,
        max_length=7,
    )
    promotion_draft: PromotionDraft | None = None
    scientific_content_generated_by_model: Literal[True] = True
    human_authored_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("action_title_cn", "reason_for_choice_cn", "expected_information_gain_cn")
    @classmethod
    def _validate_chinese_action(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)

    @field_validator("action_body_cn")
    @classmethod
    def _validate_action_body(cls, value: str, info: Any) -> str:
        if (
            info.data.get("operator") is ResearchOperator.RETRIEVE_EVIDENCE
            and info.data.get("schema_version") != "adaptive-research-action-draft-v3"
        ):
            return _require_retrieval_action_body(value)
        return _require_chinese_dominant(value, field_name=info.field_name)

    @field_validator("retrieval_query_terms")
    @classmethod
    def _validate_retrieval_query_terms(
        cls,
        value: list[str],
    ) -> list[str]:
        if value and not _retrieval_query_terms_are_valid(
            value,
            require_bounded_count=False,
        ):
            raise ValueError("retrieval_query_terms 必须是互异的ASCII检索短语；每项含1至4个技术词")
        return value

    @field_validator("working_hypothesis_cn")
    @classmethod
    def _validate_optional_hypothesis(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_chinese_dominant(value, field_name="working_hypothesis_cn")

    @field_validator("selected_skill_ids", "source_refs")
    @classmethod
    def _normalize_unique_lists(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("adaptive action lists must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def _validate_operator_shape(self) -> ModelResearchActionDraft:
        if self.memory_consumption_claims and self.schema_version == (
            "adaptive-research-action-draft-v1"
        ):
            raise ValueError("memory consumption claims require action draft v2 or newer")
        retrieval = self.operator is ResearchOperator.RETRIEVE_EVIDENCE
        if self.schema_version == "adaptive-research-action-draft-v3":
            if retrieval and not _retrieval_query_terms_are_valid(self.retrieval_query_terms):
                raise ValueError(
                    "retrieve_evidence 在动作契约v3下必须提供3至10个互异的" "retrieval_query_terms"
                )
            if not retrieval and self.retrieval_query_terms:
                raise ValueError("retrieval_query_terms 只允许用于 retrieve_evidence")
        elif self.retrieval_query_terms:
            raise ValueError("structured retrieval_query_terms require action draft v3")
        claimed_records = [item.record_id for item in self.memory_consumption_claims]
        if len(claimed_records) != len(set(claimed_records)):
            raise ValueError("adaptive action repeats a consumed memory record")
        temporary = self.operator is ResearchOperator.CONSULT_TEMPORARY_AGENTS
        if temporary != bool(self.temporary_tasks):
            raise ValueError("temporary tasks are required only for consult_temporary_agents")
        promotion = self.operator is ResearchOperator.PROMOTE_BRANCH
        if promotion != (self.promotion_draft is not None):
            raise ValueError("promotion_draft is required only for promote_branch")
        if (
            self.operator
            in {
                ResearchOperator.BRANCH_HYPOTHESIS,
                ResearchOperator.ANALOGICAL_TRANSFER,
                ResearchOperator.REFRAME_QUESTION,
            }
            and self.working_hypothesis_cn is None
        ):
            raise ValueError("branching operators require working_hypothesis_cn")
        return self


class ExternalResearchFeedbackContent(KernelContract):
    """Feedback from a capability outside the model's intrinsic self-critique."""

    feedback_id: StableId
    branch_id: StableId
    operator: ResearchOperator
    origin: FeedbackOrigin
    status: FeedbackStatus
    summary_cn: str = Field(min_length=1, max_length=12_000)
    findings_cn: list[str] = Field(default_factory=list, max_length=64)
    source_refs: list[str] = Field(default_factory=list, max_length=128)
    artifact_refs: list[str] = Field(default_factory=list, max_length=128)
    metrics: dict[str, int | float | str | bool] = Field(default_factory=dict)
    memory_exposures: list[ModelMemoryExposure] = Field(
        default_factory=list,
        max_length=12,
        exclude_if=lambda value: not value,
    )
    tool_calls: int = Field(default=0, ge=0, le=10_000)
    temporary_agent_count: int = Field(default=0, ge=0, le=224)
    independent_of_action_author: bool = False
    is_scientific_evidence: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_publication: Literal[False] = False

    @field_validator("summary_cn")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _require_chinese(value, field_name="summary_cn")

    @field_validator("findings_cn")
    @classmethod
    def _validate_findings(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("feedback findings must be unique and non-empty")
        for item in normalized:
            _require_chinese(item, field_name="findings_cn")
        return normalized

    @field_validator("source_refs", "artifact_refs")
    @classmethod
    def _normalize_refs(cls, value: list[str]) -> list[str]:
        return _ordered_unique(value)

    @model_validator(mode="after")
    def _validate_memory_exposures(self) -> ExternalResearchFeedbackContent:
        if self.memory_exposures and self.origin is not FeedbackOrigin.DREAMING_PROJECTION:
            raise ValueError("only Dreaming feedback may expose recalled memory")
        exposure_keys = [(item.selection_hash, item.record_id) for item in self.memory_exposures]
        if len(exposure_keys) != len(set(exposure_keys)):
            raise ValueError("Dreaming feedback repeats a memory exposure")
        if self.memory_exposures:
            selection_hashes = {item.selection_hash for item in self.memory_exposures}
            if len(selection_hashes) != 1:
                raise ValueError("Dreaming feedback mixes recall selections")
            selection_hash = next(iter(selection_hashes))
            if f"artifact:{selection_hash}" not in self.artifact_refs:
                raise ValueError("Dreaming feedback does not bind its recall selection")
            if any(item.record_id not in self.source_refs for item in self.memory_exposures):
                raise ValueError("Dreaming feedback exposure is absent from source refs")
        return self


class ExternalResearchFeedback(ExternalResearchFeedbackContent):
    """Content-addressed external feedback returned to a later model turn."""

    feedback_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> ExternalResearchFeedback:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"feedback_hash"}))
        if self.feedback_hash != expected:
            raise ValueError("external research feedback hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ExternalResearchFeedback:
        content = ExternalResearchFeedbackContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, feedback_hash=canonical_sha256(payload))


class TemporaryAgentContribution(KernelContract):
    """One archived temporary-agent output retained after its identity disappears."""

    dispatch_id: StableId
    result_hash: Sha256
    archive_hash: Sha256
    summary_cn: str = Field(min_length=1, max_length=8_000)
    runtime_identity_removed: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @field_validator("summary_cn")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _require_chinese(value, field_name="summary_cn")


class TemporaryAgentBatchOutcomeContent(KernelContract):
    """Stable merged result of a main-agent-dispatched temporary batch."""

    batch_id: StableId
    contributions: list[TemporaryAgentContribution] = Field(min_length=1, max_length=7)
    all_assignments_archived: Literal[True] = True
    all_runtime_identities_removed: Literal[True] = True
    main_agent_retains_stage_control: Literal[True] = True
    output_retained: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_contributions(self) -> TemporaryAgentBatchOutcomeContent:
        ids = [item.dispatch_id for item in self.contributions]
        if len(ids) != len(set(ids)):
            raise ValueError("temporary batch repeats a dispatch ID")
        return self


class TemporaryAgentBatchOutcome(TemporaryAgentBatchOutcomeContent):
    """Content-addressed temporary-agent batch outcome."""

    batch_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TemporaryAgentBatchOutcome:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"batch_hash"}))
        if self.batch_hash != expected:
            raise ValueError("temporary-agent batch outcome hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TemporaryAgentBatchOutcome:
        content = TemporaryAgentBatchOutcomeContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, batch_hash=canonical_sha256(payload))


class PromotionGateAssessmentContent(KernelContract):
    """Mechanical promotion gate; passing still does not verify innovation."""

    branch_id: StableId
    source_traceable: bool
    multiple_sources_present: bool
    falsifiable: bool
    decisive_test_present: bool
    baseline_and_control_present: bool
    uncertainty_declared: bool
    external_feedback_present: bool
    resource_request_bounded: bool
    no_authority_claim: bool
    findings_cn: list[str]
    passed: bool
    innovation_verified: Literal[False] = False
    scientific_evidence_established: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("findings_cn")
    @classmethod
    def _validate_findings(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("promotion findings must be unique and non-empty")
        for item in normalized:
            _require_chinese(item, field_name="findings_cn")
        return normalized

    @model_validator(mode="after")
    def _validate_passed(self) -> PromotionGateAssessmentContent:
        checks = (
            self.source_traceable,
            self.multiple_sources_present,
            self.falsifiable,
            self.decisive_test_present,
            self.baseline_and_control_present,
            self.uncertainty_declared,
            self.external_feedback_present,
            self.resource_request_bounded,
            self.no_authority_claim,
        )
        if self.passed != (all(checks) and not self.findings_cn):
            raise ValueError("promotion gate passed flag does not match all checks")
        return self


class PromotionGateAssessment(PromotionGateAssessmentContent):
    """Content-addressed mechanical promotion result."""

    assessment_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> PromotionGateAssessment:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"assessment_hash"}))
        if self.assessment_hash != expected:
            raise ValueError("promotion assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PromotionGateAssessment:
        content = PromotionGateAssessmentContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, assessment_hash=canonical_sha256(payload))


class FormalPromotionVerificationContent(KernelContract):
    """Independent pre-execution verification of one promotion request."""

    branch_id: StableId
    promotion_assessment_hash: Sha256
    verifier_id: StableId
    independent_of_action_author: Literal[True] = True
    exact_sources_rechecked: bool
    objective_checks_replayed: bool
    falsifier_is_operational: bool
    control_is_discriminating: bool
    resource_scope_feasible: bool
    no_direct_prior_work_copy: bool
    findings_cn: list[str]
    passed: bool
    novelty_claim_scope: Literal["未执行候选；仅表示当前检索与检查未发现直接重复"] = (
        "未执行候选；仅表示当前检索与检查未发现直接重复"
    )
    innovation_verified: Literal[False] = False
    scientific_evidence_established: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("findings_cn")
    @classmethod
    def _validate_findings(cls, value: list[str]) -> list[str]:
        normalized = _ordered_unique(value)
        if len(normalized) != len(value):
            raise ValueError("verification findings must be unique and non-empty")
        for item in normalized:
            _require_chinese(item, field_name="findings_cn")
        return normalized

    @model_validator(mode="after")
    def _validate_passed(self) -> FormalPromotionVerificationContent:
        checks = (
            self.exact_sources_rechecked,
            self.objective_checks_replayed,
            self.falsifier_is_operational,
            self.control_is_discriminating,
            self.resource_scope_feasible,
            self.no_direct_prior_work_copy,
        )
        if self.passed != (all(checks) and not self.findings_cn):
            raise ValueError("formal verification passed flag does not match checks")
        return self


class FormalPromotionVerification(FormalPromotionVerificationContent):
    """Content-addressed independent verification result."""

    verification_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalPromotionVerification:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"verification_hash"}))
        if self.verification_hash != expected:
            raise ValueError("formal promotion verification hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalPromotionVerification:
        content = FormalPromotionVerificationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, verification_hash=canonical_sha256(payload))


class AdaptiveResearchBranch(KernelContract):
    """A retained branch in the open-ended archive."""

    branch_id: StableId
    parent_branch_id: StableId | None = None
    created_step: int = Field(ge=0)
    title_cn: str = Field(min_length=1, max_length=1_000)
    working_hypothesis_cn: str = Field(min_length=1, max_length=8_000)
    status: ResearchBranchStatus = ResearchBranchStatus.ACTIVE
    action_hashes: list[Sha256] = Field(default_factory=list)
    feedback_hashes: list[Sha256] = Field(default_factory=list)
    promotion_assessment_hash: Sha256 | None = None
    formal_verification_hash: Sha256 | None = None

    @field_validator("title_cn", "working_hypothesis_cn")
    @classmethod
    def _validate_chinese_branch(cls, value: str, info: Any) -> str:
        return _require_chinese_dominant(value, field_name=info.field_name)

    @field_validator("action_hashes", "feedback_hashes")
    @classmethod
    def _validate_hash_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("branch hash lists must be unique")
        return value


class AdaptiveActionModelCallRegistrationContent(KernelContract):
    """Pre-call reservation that survives transport and validation failures."""

    schema_version: Literal["adaptive-action-model-call-registration-v1"] = (
        "adaptive-action-model-call-registration-v1"
    )
    registration_id: StableId
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1, le=500)
    attempt_index: int = Field(ge=1, le=3)
    messages_sha256: Sha256
    response_schema_sha256: Sha256
    request_parameters: dict[str, JsonValue]
    registered_at: datetime
    may_have_contacted_external_provider: Literal[True] = True
    conservatively_consumes_model_budget: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_registration(self) -> AdaptiveActionModelCallRegistrationContent:
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("adaptive model-call registration timestamp lacks timezone")
        expected_id = (
            f"adaptive:{self.loop_id}:step:{self.step_index}:attempt:" f"{self.attempt_index}"
        )
        if self.registration_id != expected_id:
            raise ValueError("adaptive model-call registration ID mismatch")
        return self


class AdaptiveActionModelCallRegistration(AdaptiveActionModelCallRegistrationContent):
    registration_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveActionModelCallRegistration:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"registration_hash"}))
        if self.registration_hash != expected:
            raise ValueError("adaptive model-call registration hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveActionModelCallRegistration:
        content = AdaptiveActionModelCallRegistrationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, registration_hash=canonical_sha256(payload))


class AdaptiveSkillRoutingCallRegistrationContent(KernelContract):
    """Pre-call reservation for one model-backed skill-routing decision."""

    schema_version: Literal["adaptive-skill-routing-call-registration-v1"] = (
        "adaptive-skill-routing-call-registration-v1"
    )
    registration_id: StableId
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1, le=500)
    call_index: int = Field(ge=1, le=8)
    routing_input_hash: Sha256
    registered_at: datetime
    may_have_contacted_external_provider: Literal[True] = True
    conservatively_consumes_model_budget: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_registration(self) -> AdaptiveSkillRoutingCallRegistrationContent:
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("adaptive skill-call registration timestamp lacks timezone")
        expected_id = (
            f"adaptive:{self.loop_id}:step:{self.step_index}:skill-routing:" f"{self.call_index}"
        )
        if self.registration_id != expected_id:
            raise ValueError("adaptive skill-call registration ID mismatch")
        return self


class AdaptiveSkillRoutingCallRegistration(AdaptiveSkillRoutingCallRegistrationContent):
    registration_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveSkillRoutingCallRegistration:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"registration_hash"}))
        if self.registration_hash != expected:
            raise ValueError("adaptive skill-call registration hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveSkillRoutingCallRegistration:
        content = AdaptiveSkillRoutingCallRegistrationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, registration_hash=canonical_sha256(payload))


class AdaptiveActionModelAttemptContent(KernelContract):
    """One provider response rejected before it could become a loop action."""

    attempt_index: int = Field(ge=1, le=3)
    messages: list[dict[Literal["role", "content"], str]] = Field(min_length=2)
    messages_sha256: Sha256
    provider: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=512)
    response_binding: RawMemoryBinding
    reasoning_binding: RawMemoryBinding
    reasoning_character_count: int = Field(ge=0, le=200_000)
    parsed_payload: dict[str, JsonValue]
    rejection_findings: list[str] = Field(min_length=1, max_length=32)
    accepted: Literal[False] = False

    @model_validator(mode="after")
    def _validate_attempt(self) -> AdaptiveActionModelAttemptContent:
        if self.messages_sha256 != canonical_sha256(self.messages):
            raise ValueError("adaptive rejected-attempt messages hash mismatch")
        if any(not item.strip() for item in self.rejection_findings):
            raise ValueError("adaptive rejected-attempt findings must be non-empty")
        return self


class AdaptiveActionModelAttempt(AdaptiveActionModelAttemptContent):
    """Content-addressed rejected action attempt retained for Qwen repair audit."""

    attempt_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveActionModelAttempt:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"attempt_hash"}))
        if self.attempt_hash != expected:
            raise ValueError("adaptive rejected-attempt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveActionModelAttempt:
        content = AdaptiveActionModelAttemptContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, attempt_hash=canonical_sha256(payload))


class AdaptiveLoopModelInteractionContent(KernelContract):
    """Exact prompt plus raw-memory bindings for one model-selected action."""

    interaction_id: StableId
    step_index: int = Field(ge=1)
    messages: list[dict[Literal["role", "content"], str]] = Field(min_length=2)
    messages_sha256: Sha256
    model_name: str = Field(min_length=1, max_length=512)
    provider: str = Field(min_length=1, max_length=512)
    model_call_registrations: list[AdaptiveActionModelCallRegistration] = Field(
        min_length=1,
        max_length=3,
    )
    external_turn_contexts: list[AdaptiveExternalTurnContext] = Field(
        default_factory=list,
        max_length=8,
        exclude_if=lambda value: not value,
    )
    response_binding: RawMemoryBinding
    reasoning_binding: RawMemoryBinding
    reasoning_character_count: int = Field(ge=_MIN_REASONING_CHARACTERS)
    rejected_attempts: list[AdaptiveActionModelAttempt] = Field(
        default_factory=list,
        max_length=2,
        exclude_if=lambda value: not value,
    )
    proposal: ModelResearchActionDraft
    reasoning_is_scientific_evidence: Literal[False] = False
    hand_written_scientific_prose_count: Literal[0] = 0

    @model_validator(mode="after")
    def _validate_content(self) -> AdaptiveLoopModelInteractionContent:
        if self.messages_sha256 != canonical_sha256(self.messages):
            raise ValueError("adaptive-loop messages hash mismatch")
        if self.proposal.step_index != self.step_index:
            raise ValueError("model proposal step does not match interaction step")
        if [message["role"] for message in self.messages].count("system") != 1:
            raise ValueError("adaptive loop requires exactly one system message")
        context_ids = [item.context_id for item in self.external_turn_contexts]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("adaptive loop repeats an external turn context")
        if any(item.step_index != self.step_index for item in self.external_turn_contexts):
            raise ValueError("external turn context step does not match interaction")
        attempt_indices = [item.attempt_index for item in self.rejected_attempts]
        if attempt_indices != list(range(1, len(self.rejected_attempts) + 1)):
            raise ValueError("adaptive rejected attempts must be contiguous")
        registration_indices = [item.attempt_index for item in self.model_call_registrations]
        if registration_indices != list(range(1, len(self.model_call_registrations) + 1)):
            raise ValueError("adaptive model-call registrations must be contiguous")
        if any(item.step_index != self.step_index for item in self.model_call_registrations):
            raise ValueError("adaptive model-call registration step mismatch")
        if len(self.model_call_registrations) != len(self.rejected_attempts) + 1:
            raise ValueError(
                "adaptive interaction must bind every rejected and accepted provider call"
            )
        for registration, attempt in zip(
            self.model_call_registrations,
            self.rejected_attempts,
            strict=False,
        ):
            if registration.messages_sha256 != attempt.messages_sha256:
                raise ValueError("adaptive rejected attempt differs from its pre-call registration")
        if self.model_call_registrations[-1].messages_sha256 != self.messages_sha256:
            raise ValueError("adaptive accepted interaction differs from its pre-call registration")
        return self


class AdaptiveLoopModelInteraction(AdaptiveLoopModelInteractionContent):
    """Content-addressed model interaction."""

    interaction_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopModelInteraction:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"interaction_hash"}))
        if self.interaction_hash != expected:
            raise ValueError("adaptive-loop interaction hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopModelInteraction:
        content = AdaptiveLoopModelInteractionContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, interaction_hash=canonical_sha256(payload))


class AdaptiveLoopEventContent(KernelContract):
    """One immutable loop transition."""

    schema_version: Literal["adaptive-sovereign-loop-event-v1"] = "adaptive-sovereign-loop-event-v1"
    loop_id: StableId
    step_index: int = Field(ge=1)
    zone_before: ResearchLoopZone
    zone_after: ResearchLoopZone
    branch_id: StableId
    interaction: AdaptiveLoopModelInteraction
    feedback: ExternalResearchFeedback
    temporary_batch: TemporaryAgentBatchOutcome | None = None
    promotion_assessment: PromotionGateAssessment | None = None
    formal_verification: FormalPromotionVerification | None = None
    created_branch_id: StableId | None = None
    strategy_note_cn: str | None = Field(default=None, max_length=8_000)
    event_payload_binding: RawMemoryBinding
    scientific_content_authored_by_model: Literal[True] = True
    orchestrator_scientific_prose_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adaptive-loop event timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("strategy_note_cn")
    @classmethod
    def _validate_strategy_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_chinese_dominant(value, field_name="strategy_note_cn")

    @model_validator(mode="after")
    def _validate_bindings(self) -> AdaptiveLoopEventContent:
        if self.interaction.step_index != self.step_index:
            raise ValueError("event interaction step mismatch")
        if self.interaction.proposal.branch_id != self.branch_id:
            raise ValueError("event proposal branch mismatch")
        if self.feedback.branch_id != self.branch_id:
            raise ValueError("event feedback branch mismatch")
        if self.feedback.operator is not self.interaction.proposal.operator:
            raise ValueError("event feedback operator mismatch")
        if any(
            registration.loop_id != self.loop_id
            for registration in self.interaction.model_call_registrations
        ):
            raise ValueError("event model-call registration loop mismatch")
        promotion = self.interaction.proposal.operator is ResearchOperator.PROMOTE_BRANCH
        if promotion != (self.promotion_assessment is not None):
            raise ValueError("promotion event assessment presence mismatch")
        if self.formal_verification is not None and self.promotion_assessment is None:
            raise ValueError("formal verification requires a promotion assessment")
        return self


class AdaptiveLoopEvent(AdaptiveLoopEventContent):
    """Content-addressed durable transition."""

    event_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopEvent:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"event_hash"}))
        if self.event_hash != expected:
            raise ValueError("adaptive-loop event hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopEvent:
        content = AdaptiveLoopEventContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, event_hash=canonical_sha256(payload))


class AdaptiveResearchLoopSnapshotContent(KernelContract):
    """Rebuildable controller snapshot; raw records remain authoritative inputs."""

    schema_version: Literal["adaptive-sovereign-loop-snapshot-v2"] = (
        "adaptive-sovereign-loop-snapshot-v2"
    )
    seed: AdaptiveResearchSeed
    policy: AdaptiveLoopPolicy
    zone: ResearchLoopZone
    status: AdaptiveLoopRunStatus
    next_step_index: int = Field(ge=1)
    branches: list[AdaptiveResearchBranch] = Field(min_length=1)
    events: list[AdaptiveLoopEvent] = Field(default_factory=list)
    strategy_notes_cn: list[str] = Field(default_factory=list, max_length=128)
    model_call_count: int = Field(ge=0)
    skill_routing_model_call_count: int = Field(default=0, ge=0)
    unresolved_model_call_count: int = Field(default=0, ge=0, le=12)
    external_action_count: int = Field(ge=0)
    temporary_agent_count: int = Field(ge=0)
    consecutive_stalls: int = Field(ge=0)
    human_scope_approval_recorded: Literal[False] = False
    formal_execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("strategy_notes_cn")
    @classmethod
    def _validate_strategy_notes(cls, value: list[str]) -> list[str]:
        for item in value:
            _require_chinese_dominant(item, field_name="strategy_notes_cn")
        return value

    @model_validator(mode="after")
    def _validate_state(self) -> AdaptiveResearchLoopSnapshotContent:
        branch_ids = [branch.branch_id for branch in self.branches]
        if len(branch_ids) != len(set(branch_ids)):
            raise ValueError("adaptive-loop snapshot repeats a branch ID")
        event_steps = [event.step_index for event in self.events]
        if event_steps != list(range(1, len(self.events) + 1)):
            raise ValueError("adaptive-loop event steps must be contiguous")
        if self.next_step_index != len(self.events) + 1:
            raise ValueError("adaptive-loop next step does not follow events")
        registered_action_calls = sum(
            len(event.interaction.model_call_registrations) for event in self.events
        )
        if self.model_call_count != (
            registered_action_calls
            + self.skill_routing_model_call_count
            + self.unresolved_model_call_count
        ):
            raise ValueError(
                "adaptive-loop model calls must equal all registered action and skill calls"
            )
        if self.unresolved_model_call_count and (
            self.status is not AdaptiveLoopRunStatus.BLOCKED
            or self.zone is not ResearchLoopZone.TERMINAL
        ):
            raise ValueError("unresolved model calls require a blocked terminal snapshot")
        if any(event.loop_id != self.seed.loop_id for event in self.events):
            raise ValueError("adaptive-loop event belongs to another loop")
        if any(
            registration.project_id != self.seed.project_id
            for event in self.events
            for registration in event.interaction.model_call_registrations
        ):
            raise ValueError("adaptive model-call registration belongs to another project")
        known = set(branch_ids)
        if any(event.branch_id not in known for event in self.events):
            raise ValueError("adaptive-loop event references an absent branch")
        for branch in self.branches:
            if branch.parent_branch_id is not None and branch.parent_branch_id not in known:
                raise ValueError("adaptive-loop branch parent is absent")
        ready = any(
            branch.status is ResearchBranchStatus.READY_FOR_HUMAN_SCOPE for branch in self.branches
        )
        if self.status is AdaptiveLoopRunStatus.PAUSED_HUMAN_SCOPE and not ready:
            raise ValueError("human-scope pause requires one verified branch")
        if self.zone is ResearchLoopZone.WAITING_HUMAN_SCOPE and not ready:
            raise ValueError("human-scope zone requires one verified branch")
        return self


class AdaptiveResearchLoopSnapshot(AdaptiveResearchLoopSnapshotContent):
    """Content-addressed loop state written after every transition."""

    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveResearchLoopSnapshot:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))
        if self.snapshot_hash != expected:
            raise ValueError("adaptive-loop snapshot hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveResearchLoopSnapshot:
        content = AdaptiveResearchLoopSnapshotContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, snapshot_hash=canonical_sha256(payload))


def build_adaptive_memory_control_observation(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    selected_branch_id: str,
    available_operator_ids: Sequence[str],
) -> AdaptiveMemoryControlObservation:
    """Project neutral memory availability without recommending an operator."""

    events = list(snapshot.events)
    branch_events = [event for event in events if event.branch_id == selected_branch_id]
    outside_count = max(0, len(events) - _MAX_RECENT_EVENTS_IN_PROMPT)
    outside_events = events[:outside_count]
    branch_outside_count = sum(event.branch_id == selected_branch_id for event in outside_events)

    def turns_since_review(history: Sequence[AdaptiveLoopEvent]) -> int:
        distance = 0
        for event in reversed(history):
            if event.interaction.proposal.operator is ResearchOperator.CONSOLIDATE_DREAMING:
                return distance
            distance += 1
        return distance

    return AdaptiveMemoryControlObservation.create(
        retained_event_count=len(events),
        retained_events_outside_recent_prompt=outside_count,
        selected_branch_retained_event_count=len(branch_events),
        selected_branch_events_outside_recent_prompt=branch_outside_count,
        turns_since_any_memory_review=turns_since_review(events),
        selected_branch_turns_since_memory_review=turns_since_review(branch_events),
        prior_memory_review_count=sum(
            event.interaction.proposal.operator is ResearchOperator.CONSOLIDATE_DREAMING
            for event in events
        ),
        prior_memory_exposure_count=sum(len(event.feedback.memory_exposures) for event in events),
        prior_model_declared_consumption_count=sum(
            len(event.interaction.proposal.memory_consumption_claims) for event in events
        ),
        reviewable_history_outside_recent_prompt_exists=bool(outside_count),
        memory_review_operator_available=(
            ResearchOperator.CONSOLIDATE_DREAMING.value in available_operator_ids
        ),
    )


def build_adaptive_workflow_proposal_contexts(
    snapshot: AdaptiveResearchLoopSnapshot,
) -> tuple[AdaptiveWorkflowProposalContext, ...]:
    """Recover temporal scope for retained proposals without deleting or summarising them."""

    proposal_events = [
        event
        for event in snapshot.events
        if event.interaction.proposal.operator is ResearchOperator.MUTATE_WORKFLOW_PROPOSAL
    ]
    if len(proposal_events) != len(snapshot.strategy_notes_cn):
        raise AdaptiveResearchLoopError(
            "adaptive workflow proposal history differs from retained strategy notes"
        )
    contexts: list[AdaptiveWorkflowProposalContext] = []
    for event, retained_text in zip(
        proposal_events,
        snapshot.strategy_notes_cn,
        strict=True,
    ):
        if retained_text != event.interaction.proposal.action_body_cn:
            raise AdaptiveResearchLoopError(
                "adaptive workflow proposal text differs from its model-authored event"
            )
        contexts.append(
            AdaptiveWorkflowProposalContext.create(
                authored_step_index=event.step_index,
                age_in_turns=snapshot.next_step_index - event.step_index,
                source_interaction_hash=event.interaction.interaction_hash,
                proposal_cn=retained_text,
                proposal_sha256=hashlib.sha256(retained_text.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(contexts)


def build_adaptive_memory_recall_capability_contract() -> AdaptiveMemoryRecallCapabilityContract:
    """Describe the wired review capability without recommending that it be used."""

    return AdaptiveMemoryRecallCapabilityContract.create()


class ResearchActionEnvironment(Protocol):
    """Executes retrieval/probe/Dreaming capabilities outside model self-judgment."""

    def supported_operators(self) -> frozenset[ResearchOperator]:
        """Return only capabilities backed by a concrete runtime adapter."""
        ...

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback: ...


class OperatorCatalogProvider(Protocol):
    """Restrict one turn's mechanically reachable operators without adding any."""

    def __call__(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
        mechanically_available_operator_ids: Sequence[str],
    ) -> Sequence[str]: ...


class ExternalTurnContextProvider(Protocol):
    """Supplies frozen exogenous observations without choosing an operator."""

    def contexts_for_turn(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> Sequence[AdaptiveExternalTurnContext]: ...


class TemporaryResearchDispatcher(Protocol):
    """Main-agent adapter over the existing ephemeral temporary-agent pool."""

    def dispatch(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        tasks: Sequence[TemporaryResearchTask],
    ) -> TemporaryAgentBatchOutcome: ...


class PromotionVerifier(Protocol):
    """Independent reviewer/tool boundary invoked only after mechanical promotion."""

    def verify(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        assessment: PromotionGateAssessment,
    ) -> FormalPromotionVerification: ...


SkillProvider = Callable[
    [AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot, AdaptiveResearchBranch],
    Sequence[LoopSkillContext],
]


def initialize_adaptive_research_loop(
    *,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    raw_memory_store: RawMemoryStore,
) -> AdaptiveResearchLoopSnapshot:
    """Create a root branch only after rechecking the exact user seed memory."""

    _verify_raw_binding(raw_memory_store, seed.raw_seed_binding, seed.project_id)
    root = AdaptiveResearchBranch(
        branch_id="branch_root",
        created_step=0,
        title_cn="初始研究目标",
        working_hypothesis_cn="尚未形成假设，由系统在开放探索中自主提出。",
    )
    return AdaptiveResearchLoopSnapshot.create(
        seed=seed,
        policy=policy,
        zone=ResearchLoopZone.OPEN_EXPLORATION,
        status=AdaptiveLoopRunStatus.RUNNING,
        next_step_index=1,
        branches=[root],
        events=[],
        strategy_notes_cn=[],
        model_call_count=0,
        skill_routing_model_call_count=0,
        external_action_count=0,
        temporary_agent_count=0,
        consecutive_stalls=0,
    )


def create_adaptive_research_seed(
    *,
    loop_id: str,
    project_id: str,
    objective_cn: str,
    scope_cn: str,
    raw_memory_store: RawMemoryStore,
    captured_at: datetime | None = None,
) -> AdaptiveResearchSeed:
    """Capture the exact human scope once and return a non-scientific seed.

    The human supplies only the objective and scope.  This helper deliberately
    has no hypothesis, method, expected-result, or plan parameter, so callers
    cannot quietly turn orchestration into ghost-written scientific content.
    """

    seed_payload = {
        "schema_version": "adaptive-research-seed-source-v1",
        "loop_id": loop_id,
        "project_id": project_id,
        "objective_cn": _require_chinese_dominant(objective_cn, field_name="objective_cn"),
        "scope_cn": _require_chinese_dominant(scope_cn, field_name="scope_cn"),
        "supplied_hypothesis": None,
        "supplied_method": None,
        "supplied_research_plan": None,
    }
    exact_text = json.dumps(
        seed_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    source_digest = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    capture = raw_memory_store.capture_text(
        exact_text,
        project_id=project_id,
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="自主科研循环用户目标与范围",
        source_ref=f"adaptive-loop:{loop_id}:user-seed",
        original_name=f"adaptive-seed-{source_digest[:16]}.json",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=captured_at,
    )
    return AdaptiveResearchSeed(
        loop_id=loop_id,
        project_id=project_id,
        objective_cn=objective_cn,
        scope_cn=scope_cn,
        raw_seed_binding=capture.binding(raw_memory_store.vault_root),
    )


def run_adaptive_research_loop(
    *,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    raw_memory_store: RawMemoryStore,
    output_dir: Path | str,
    environment: ResearchActionEnvironment,
    operator_catalog_provider: OperatorCatalogProvider | None = None,
    external_turn_context_provider: ExternalTurnContextProvider | None = None,
    temporary_dispatcher: TemporaryResearchDispatcher | None = None,
    promotion_verifier: PromotionVerifier | None = None,
    skill_provider: SkillProvider | None = None,
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    initial_snapshot: AdaptiveResearchLoopSnapshot | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AdaptiveResearchLoopSnapshot:
    """Run multiple model-selected actions without intermediate user instructions.

    The function returns only when a budget/plateau/model stop is reached, an
    independent verifier is unavailable, or a verified branch requires explicit
    human scope approval.  It never executes a formal experiment or authorizes
    publication.
    """

    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    snapshot = initial_snapshot or initialize_adaptive_research_loop(
        seed=seed,
        policy=policy,
        raw_memory_store=raw_memory_store,
    )
    _validate_resume_snapshot(
        snapshot=snapshot,
        seed=seed,
        policy=policy,
        raw_memory_store=raw_memory_store,
    )
    _write_snapshot_once(output_root, snapshot)

    now = clock or (lambda: datetime.now(timezone.utc))
    while snapshot.status is AdaptiveLoopRunStatus.RUNNING:
        budget_status = _budget_status(snapshot)
        if budget_status is not None:
            snapshot = _replace_snapshot(
                snapshot,
                status=budget_status,
                zone=ResearchLoopZone.TERMINAL,
            )
            _write_snapshot_once(output_root, snapshot)
            break

        unresolved_count = _load_current_step_unresolved_model_call_count(
            output_root=output_root,
            snapshot=snapshot,
            raw_memory_store=raw_memory_store,
        )
        if unresolved_count:
            snapshot = _block_snapshot_for_unresolved_model_calls(
                snapshot,
                unresolved_count=unresolved_count,
            )
            _write_snapshot_once(output_root, snapshot)
            break

        branch = _default_branch(snapshot)
        required_skill_calls = _required_skill_provider_calls(
            skill_provider,
            seed=seed,
            snapshot=snapshot,
            branch=branch,
        )
        if snapshot.model_call_count + required_skill_calls + 1 > policy.max_model_calls:
            snapshot = _replace_snapshot(
                snapshot,
                status=AdaptiveLoopRunStatus.PAUSED_BUDGET,
                zone=ResearchLoopZone.TERMINAL,
            )
            _write_snapshot_once(output_root, snapshot)
            break
        external_turn_contexts = list(
            external_turn_context_provider.contexts_for_turn(
                seed=seed,
                snapshot=snapshot,
                branch=branch,
            )
            if external_turn_context_provider is not None
            else ()
        )
        _validate_external_turn_contexts(
            external_turn_contexts,
            seed=seed,
            snapshot=snapshot,
            raw_memory_store=raw_memory_store,
        )
        _write_skill_routing_call_registrations(
            output_root=output_root,
            raw_memory_store=raw_memory_store,
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            required_model_calls=required_skill_calls,
            registered_at=now(),
        )
        skills = list((skill_provider or _no_skills)(seed, snapshot, branch))[
            : policy.maximum_skill_contexts
        ]
        skill_model_calls = _last_skill_provider_calls(skill_provider)
        if skill_model_calls != required_skill_calls:
            raise AdaptiveResearchLoopError(
                "skill provider actual model-call count differs from its reservation"
            )
        _require_unique_skill_ids(skills)
        mechanically_available_operator_ids = _available_operator_descriptions(
            snapshot,
            environment=environment,
            temporary_dispatcher=temporary_dispatcher,
        )
        available_operator_ids = _apply_operator_catalog_provider(
            operator_catalog_provider,
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanically_available_operator_ids,
        )
        messages = build_adaptive_research_messages(
            seed=seed,
            snapshot=snapshot,
            selected_branch=branch,
            skill_contexts=skills,
            external_turn_contexts=external_turn_contexts,
            available_operator_ids=available_operator_ids,
        )
        completed = _complete_model_selected_action(
            seed=seed,
            snapshot=snapshot,
            messages=messages,
            skill_contexts=skills,
            available_operator_ids=available_operator_ids,
            raw_memory_store=raw_memory_store,
            output_root=output_root,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            minimum_reasoning_characters=policy.minimum_reasoning_characters,
            thinking_budget=policy.thinking_budget,
            maximum_attempts=min(
                3,
                policy.max_model_calls - snapshot.model_call_count - skill_model_calls,
            ),
            clock=now,
        )
        result = completed.result
        proposal = completed.proposal
        interaction = AdaptiveLoopModelInteraction.create(
            interaction_id=f"adaptive:{seed.loop_id}:step:{snapshot.next_step_index}",
            step_index=snapshot.next_step_index,
            messages=completed.messages,
            messages_sha256=canonical_sha256(completed.messages),
            model_name=result.model_name,
            provider=result.provider,
            model_call_registrations=list(completed.model_call_registrations),
            external_turn_contexts=external_turn_contexts,
            response_binding=completed.response_binding,
            reasoning_binding=completed.reasoning_binding,
            reasoning_character_count=len(completed.reasoning),
            rejected_attempts=list(completed.rejected_attempts),
            proposal=proposal,
        )

        transition = _execute_model_selected_action(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
            environment=environment,
            temporary_dispatcher=temporary_dispatcher,
            promotion_verifier=promotion_verifier,
        )
        event_payload_binding = _capture_event_payload(
            raw_memory_store=raw_memory_store,
            seed=seed,
            step_index=snapshot.next_step_index,
            interaction=interaction,
            transition=transition,
            captured_at=now(),
        )
        event = AdaptiveLoopEvent.create(
            loop_id=seed.loop_id,
            step_index=snapshot.next_step_index,
            zone_before=snapshot.zone,
            zone_after=transition.zone_after,
            branch_id=proposal.branch_id,
            interaction=interaction,
            feedback=transition.feedback,
            temporary_batch=transition.temporary_batch,
            promotion_assessment=transition.promotion_assessment,
            formal_verification=transition.formal_verification,
            created_branch_id=transition.created_branch_id,
            strategy_note_cn=transition.strategy_note_cn,
            event_payload_binding=event_payload_binding,
            created_at=now(),
        )
        _write_event_once(output_root, event)
        snapshot = _advance_snapshot(
            snapshot,
            event,
            transition,
            skill_model_call_increment=skill_model_calls,
            action_model_call_increment=len(completed.model_call_registrations),
        )
        _write_snapshot_once(output_root, snapshot)

    return snapshot


class _ActionTransition(KernelContract):
    feedback: ExternalResearchFeedback
    zone_after: ResearchLoopZone
    status_after: AdaptiveLoopRunStatus
    temporary_batch: TemporaryAgentBatchOutcome | None = None
    promotion_assessment: PromotionGateAssessment | None = None
    formal_verification: FormalPromotionVerification | None = None
    created_branch_id: StableId | None = None
    strategy_note_cn: str | None = None
    external_action_increment: int = Field(default=0, ge=0, le=1)
    temporary_agent_increment: int = Field(default=0, ge=0, le=7)
    stalled: bool = False


@dataclass(frozen=True)
class _CompletedModelAction:
    result: LLMJsonCompletionResult
    proposal: ModelResearchActionDraft
    messages: list[dict[str, str]]
    response_binding: RawMemoryBinding
    reasoning_binding: RawMemoryBinding
    reasoning: str
    rejected_attempts: tuple[AdaptiveActionModelAttempt, ...]
    model_call_registrations: tuple[AdaptiveActionModelCallRegistration, ...]


def _complete_model_selected_action(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    messages: list[dict[str, str]],
    skill_contexts: Sequence[LoopSkillContext],
    available_operator_ids: Sequence[str],
    raw_memory_store: RawMemoryStore,
    output_root: Path,
    completion: CompletionCallable,
    config_path: Path | str,
    env_path: Path | str,
    minimum_reasoning_characters: int,
    thinking_budget: int,
    maximum_attempts: int,
    clock: Callable[[], datetime],
) -> _CompletedModelAction:
    """Capture every response, then allow only bounded Qwen contract repair."""

    if maximum_attempts < 1:
        raise AdaptiveResearchLoopError("adaptive action has no provider-call budget remaining")
    response_schema = _action_response_schema(
        available_operator_ids,
        visible_memory_exposures=_visible_memory_exposures(snapshot),
    )
    current_response_schema = response_schema
    current_messages = messages
    rejected: list[AdaptiveActionModelAttempt] = []
    registrations: list[AdaptiveActionModelCallRegistration] = []
    frozen_fields: dict[str, JsonValue] | None = None
    original_memory_claims: list[JsonValue] | None = None
    for attempt_index in range(1, maximum_attempts + 1):
        attempt_temperature = 0.7 if attempt_index == 1 else 0.0
        registration = AdaptiveActionModelCallRegistration.create(
            registration_id=(
                f"adaptive:{seed.loop_id}:step:{snapshot.next_step_index}:"
                f"attempt:{attempt_index}"
            ),
            loop_id=seed.loop_id,
            project_id=seed.project_id,
            step_index=snapshot.next_step_index,
            attempt_index=attempt_index,
            messages_sha256=canonical_sha256(current_messages),
            response_schema_sha256=canonical_sha256(current_response_schema),
            request_parameters={
                "timeout_seconds": 300,
                "max_tokens": 8_000,
                "temperature": attempt_temperature,
                "thinking_mode": "enabled",
                "thinking_budget": thinking_budget,
                "response_schema_name": "adaptive_research_action",
            },
            registered_at=clock().astimezone(timezone.utc),
        )
        _write_action_call_registration_once(
            output_root=output_root,
            raw_memory_store=raw_memory_store,
            registration=registration,
        )
        registrations.append(registration)
        result = completion(
            messages=current_messages,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=300,
            max_tokens=8_000,
            temperature=attempt_temperature,
            thinking_mode="enabled",
            thinking_budget=thinking_budget,
            response_schema=current_response_schema,
            response_schema_name="adaptive_research_action",
        )
        captured_at = clock().astimezone(timezone.utc)
        response_binding = _capture_model_text(
            raw_memory_store=raw_memory_store,
            seed=seed,
            step_index=snapshot.next_step_index,
            attempt_index=attempt_index,
            label="可见模型动作响应",
            suffix="response",
            text=result.response_text,
            captured_at=captured_at,
        )
        reasoning = str(result.reasoning_text or "").strip()
        reasoning_binding = _capture_model_text(
            raw_memory_store=raw_memory_store,
            seed=seed,
            step_index=snapshot.next_step_index,
            attempt_index=attempt_index,
            label="模型有界思考过程",
            suffix="reasoning",
            text=reasoning or "本次模型动作尝试未返回可用思考过程。",
            captured_at=captured_at,
        )
        proposal, findings = _validate_action_attempt(
            result=result,
            reasoning=reasoning,
            minimum_reasoning_characters=minimum_reasoning_characters,
            snapshot=snapshot,
            skill_contexts=skill_contexts,
            available_operator_ids=available_operator_ids,
            frozen_fields=frozen_fields,
            original_memory_claims=original_memory_claims,
        )
        if proposal is not None:
            return _CompletedModelAction(
                result=result,
                proposal=proposal,
                messages=current_messages,
                response_binding=response_binding,
                reasoning_binding=reasoning_binding,
                reasoning=reasoning,
                rejected_attempts=tuple(rejected),
                model_call_registrations=tuple(registrations),
            )

        attempt = AdaptiveActionModelAttempt.create(
            attempt_index=attempt_index,
            messages=current_messages,
            messages_sha256=canonical_sha256(current_messages),
            provider=result.provider,
            model_name=result.model_name,
            response_binding=response_binding,
            reasoning_binding=reasoning_binding,
            reasoning_character_count=len(reasoning),
            parsed_payload=result.parsed_json,
            rejection_findings=findings,
        )
        _write_action_attempt_once(
            output_root=output_root,
            step_index=snapshot.next_step_index,
            attempt=attempt,
        )
        if not _action_findings_are_repairable(findings):
            raise AdaptiveResearchLoopError(findings[0])
        if attempt_index >= maximum_attempts:
            raise AdaptiveResearchLoopError(
                "configured Qwen action remained structurally invalid after "
                f"{maximum_attempts} bounded attempts: {findings[0]}"
            )
        rejected.append(attempt)
        if frozen_fields is None:
            frozen_fields = _repair_frozen_fields(result.parsed_json)
            original_memory_claims = _repair_original_memory_claims(result.parsed_json)
        if original_memory_claims is None:
            raise AdaptiveResearchLoopError("contract repair lost its original provenance set")
        current_messages = _action_repair_messages(
            original_messages=messages,
            previous_response=result.response_text,
            findings=findings,
            frozen_fields=frozen_fields,
            original_memory_claims=original_memory_claims,
            step_index=snapshot.next_step_index,
            branch_id=_default_branch(snapshot).branch_id,
            available_operator_ids=available_operator_ids,
        )
        current_response_schema = _action_repair_response_schema(
            response_schema,
            frozen_fields=frozen_fields,
            step_index=snapshot.next_step_index,
            branch_id=_default_branch(snapshot).branch_id,
        )
    raise AdaptiveResearchLoopError("adaptive action repair loop exited unexpectedly")


def _action_findings_are_repairable(findings: Sequence[str]) -> bool:
    nonrepairable_markers = (
        "must use action draft v3",
        "wrong loop step",
        "absent research branch",
        "inactive research branch",
        "skill that was not injected",
        "operator whose branch or resource budget is unavailable",
        "more temporary agents than the remaining loop budget",
    )
    return not any(marker in finding for finding in findings for marker in nonrepairable_markers)


def _validate_raw_memory_claim_provenance(
    payload: dict[str, Any],
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> None:
    claims = payload.get("memory_consumption_claims", [])
    if not isinstance(claims, list):
        return
    exposures = _visible_memory_exposures(snapshot)
    if claims and not exposures:
        raise AdaptiveResearchLoopError(
            "memory_consumption_claims必须为空：当前提示没有任何Dreaming "
            "memory_exposures；Skill消息只是方法论，不是记忆暴露。"
        )
    allowed = {
        (
            item.dreaming_step_index,
            item.selection_hash,
            item.record_id,
            item.payload_sha256,
            item.excerpt_sha256,
        )
        for item in exposures
    }
    invalid_indices: list[int] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        identity = (
            claim.get("dreaming_step_index"),
            claim.get("selection_hash"),
            claim.get("record_id"),
            claim.get("payload_sha256"),
            claim.get("excerpt_sha256"),
        )
        if identity not in allowed:
            invalid_indices.append(index)
    if invalid_indices:
        raise AdaptiveResearchLoopError(
            "memory_consumption_claims中的五键身份未逐字命中本轮可见Dreaming "
            "memory_exposures，非法索引：" + ",".join(str(index) for index in invalid_indices)
        )


def _validate_action_attempt(
    *,
    result: LLMJsonCompletionResult,
    reasoning: str,
    minimum_reasoning_characters: int,
    snapshot: AdaptiveResearchLoopSnapshot,
    skill_contexts: Sequence[LoopSkillContext],
    available_operator_ids: Sequence[str],
    frozen_fields: dict[str, JsonValue] | None,
    original_memory_claims: list[JsonValue] | None,
) -> tuple[ModelResearchActionDraft | None, list[str]]:
    try:
        if len(reasoning) < minimum_reasoning_characters:
            raise AdaptiveResearchLoopError("reasoning_content shorter than the configured minimum")
        visible_payload = json.loads(result.response_text)
        if visible_payload != result.parsed_json:
            raise AdaptiveResearchLoopError(
                "visible model action response differs from the parsed payload"
            )
        if result.parsed_json.get("schema_version") != ("adaptive-research-action-draft-v3"):
            raise AdaptiveResearchLoopError("new adaptive model actions must use action draft v3")
        _validate_raw_memory_claim_provenance(
            result.parsed_json,
            snapshot=snapshot,
        )
        if frozen_fields is not None:
            changed = [
                key
                for key, value in frozen_fields.items()
                if not _repair_field_is_equivalent(
                    key,
                    original=value,
                    repaired=result.parsed_json.get(key),
                    frozen_operator=frozen_fields.get("operator"),
                )
            ]
            if changed:
                raise AdaptiveResearchLoopError(
                    "contract repair changed frozen scientific fields: " + ", ".join(changed)
                )
            if original_memory_claims is None:
                raise AdaptiveResearchLoopError("contract repair lacks its original provenance set")
            if not _memory_claim_repair_is_conservative(
                original=original_memory_claims,
                repaired=result.parsed_json.get("memory_consumption_claims", []),
            ):
                raise AdaptiveResearchLoopError(
                    "contract repair added or changed memory consumption claims"
                )
        proposal = ModelResearchActionDraft.model_validate(result.parsed_json)
        _validate_proposal_against_state(
            proposal=proposal,
            snapshot=snapshot,
            skill_contexts=skill_contexts,
            available_operator_ids=available_operator_ids,
        )
    except (ValueError, AdaptiveResearchLoopError) as exc:
        finding = f"{type(exc).__name__}: {str(exc).strip()}"[:4_000]
        return None, [finding or type(exc).__name__]
    return proposal, []


def _repair_frozen_fields(payload: dict[str, Any]) -> dict[str, JsonValue]:
    fields = (
        "schema_version",
        "operator",
        "action_title_cn",
        "action_body_cn",
        "retrieval_query_terms",
        "reason_for_choice_cn",
        "expected_information_gain_cn",
        "working_hypothesis_cn",
        "selected_skill_ids",
        "source_refs",
    )
    frozen = {
        field: _detached_json_value(payload[field])
        for field in fields
        if field in payload and payload[field] is not None
    }
    frozen.setdefault("retrieval_query_terms", [])
    return frozen


_REPAIR_TYPOGRAPHIC_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "＇": "'",
        "“": '"',
        "”": '"',
        "＂": '"',
    }
)
_REPAIR_CHINESE_PROSE_FIELDS = frozenset(
    {
        "action_title_cn",
        "action_body_cn",
        "reason_for_choice_cn",
        "expected_information_gain_cn",
        "working_hypothesis_cn",
    }
)
_REPAIR_MODEL_REAUTHORED_CHINESE_FIELDS = frozenset({"action_body_cn"})


def _requires_model_chinese_reauthoring(
    field_name: str,
    *,
    value: JsonValue,
    frozen_operator: JsonValue | None,
) -> bool:
    """Identify a prose field Qwen may reauthor without changing the action decision."""

    if (
        field_name not in _REPAIR_MODEL_REAUTHORED_CHINESE_FIELDS
        or frozen_operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        or not isinstance(value, str)
    ):
        return False
    try:
        _require_chinese_dominant(value, field_name=field_name)
    except ValueError:
        return True
    return False


def _repair_field_is_equivalent(
    field_name: str,
    *,
    original: JsonValue,
    repaired: Any,
    frozen_operator: JsonValue | None,
) -> bool:
    """Allow only declared mechanical projections, never scientific rewriting."""

    if (
        field_name == "action_body_cn"
        and frozen_operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and isinstance(original, str)
        and isinstance(repaired, str)
        and _retrieval_query_repair_is_conservative(original=original, repaired=repaired)
    ):
        return True

    if (
        field_name == "retrieval_query_terms"
        and frozen_operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and _retrieval_query_term_repair_is_conservative(
            original=original,
            repaired=repaired,
        )
    ):
        return True

    if _requires_model_chinese_reauthoring(
        field_name,
        value=original,
        frozen_operator=frozen_operator,
    ) and isinstance(repaired, str):
        try:
            _require_chinese_dominant(repaired, field_name=field_name)
        except ValueError:
            return False
        return True

    if (
        field_name in _REPAIR_CHINESE_PROSE_FIELDS
        and isinstance(original, str)
        and isinstance(repaired, str)
    ):
        return original.translate(_REPAIR_TYPOGRAPHIC_QUOTE_TRANSLATION) == repaired.translate(
            _REPAIR_TYPOGRAPHIC_QUOTE_TRANSLATION
        )
    return bool(original == repaired)


def _retrieval_query_repair_is_conservative(*, original: str, repaired: str) -> bool:
    """Permit Qwen to shrink an invalid query only to an ordered source-token subset."""

    original_parts = _split_retrieval_action_body(original)
    repaired_parts = _split_retrieval_action_body(repaired)
    if original_parts is None or repaired_parts is None:
        return False
    original_tokens, original_prose = original_parts
    repaired_tokens, repaired_prose = repaired_parts
    original_is_valid = _retrieval_query_tokens_are_valid(original_tokens)
    repaired_is_valid = _retrieval_query_tokens_are_valid(repaired_tokens)
    if original_is_valid or not repaired_is_valid:
        return False
    cursor = 0
    for token in repaired_tokens:
        while cursor < len(original_tokens) and original_tokens[cursor] != token:
            cursor += 1
        if cursor >= len(original_tokens):
            return False
        cursor += 1
    return original_prose.translate(_REPAIR_TYPOGRAPHIC_QUOTE_TRANSLATION) == (
        repaired_prose.translate(_REPAIR_TYPOGRAPHIC_QUOTE_TRANSLATION)
    )


def _retrieval_query_term_repair_is_conservative(
    *,
    original: JsonValue,
    repaired: Any,
) -> bool:
    """Allow only an order-preserving subset of the model's original query phrases."""

    if not isinstance(original, list) or not isinstance(repaired, list):
        return False
    if _retrieval_query_terms_are_valid(original) or not _retrieval_query_terms_are_valid(repaired):
        return False
    cursor = 0
    for term in repaired:
        while cursor < len(original) and original[cursor] != term:
            cursor += 1
        if cursor >= len(original):
            return False
        cursor += 1
    return True


def _repair_original_memory_claims(payload: dict[str, Any]) -> list[JsonValue]:
    claims = payload.get("memory_consumption_claims", [])
    if not isinstance(claims, list):
        return []
    return [_detached_json_value(item) for item in claims]


def _detached_json_value(value: Any) -> JsonValue:
    """Freeze a model JSON value so later in-process mutation cannot rewrite the baseline."""

    return cast(JsonValue, json.loads(canonical_json(value)))


def _memory_claim_repair_is_conservative(
    *,
    original: Sequence[JsonValue],
    repaired: Any,
) -> bool:
    """A repair may retract provenance claims, but may not invent or rewrite one."""

    if repaired is None:
        repaired_items: list[Any] = []
    elif isinstance(repaired, list):
        repaired_items = repaired
    else:
        return False
    cursor = 0
    for repaired_item in repaired_items:
        while cursor < len(original) and original[cursor] != repaired_item:
            cursor += 1
        if cursor >= len(original):
            return False
        cursor += 1
    return True


def _action_repair_messages(
    *,
    original_messages: list[dict[str, str]],
    previous_response: str,
    findings: Sequence[str],
    frozen_fields: dict[str, JsonValue],
    original_memory_claims: Sequence[JsonValue],
    step_index: int,
    branch_id: str,
    available_operator_ids: Sequence[str],
) -> list[dict[str, str]]:
    exact_fields = dict(frozen_fields)
    mechanically_repairable_fields: dict[str, JsonValue] = {}
    original_operator = frozen_fields.get("operator")
    model_reauthored_chinese_fields = {
        field_name: exact_fields.pop(field_name)
        for field_name in tuple(exact_fields)
        if _requires_model_chinese_reauthoring(
            field_name,
            value=exact_fields[field_name],
            frozen_operator=original_operator,
        )
    }
    original_body = frozen_fields.get("action_body_cn")
    original_query_terms = frozen_fields.get("retrieval_query_terms", [])
    original_body_parts = (
        _split_retrieval_action_body(original_body) if isinstance(original_body, str) else None
    )
    if (
        original_operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and original_body_parts is not None
        and not _retrieval_query_tokens_are_valid(original_body_parts[0])
    ):
        mechanically_repairable_fields["action_body_cn"] = exact_fields.pop("action_body_cn")
    if (
        original_operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and isinstance(original_query_terms, list)
        and original_query_terms
        and not _retrieval_query_terms_are_valid(original_query_terms)
    ):
        mechanically_repairable_fields["retrieval_query_terms"] = exact_fields.pop(
            "retrieval_query_terms"
        )
    repair = {
        "context_kind": "adaptive_research_action_contract_repair",
        "repair_scope": (
            "只修复结构、字段依赖和当前状态绑定；仅显式列出的中文正文字段可由Qwen"
            "重新表述，但不得重做被冻结的科研判断"
        ),
        "deterministic_findings": list(findings),
        "required_step_index": step_index,
        "required_branch_id": branch_id,
        "available_operator_ids": list(available_operator_ids),
        "scientific_fields_that_must_remain_exact": exact_fields,
        "scientific_text_equivalence": (
            "只允许中文弯引号与对应ASCII引号之间的排版等价，以及下述显式检索查询机械投影；"
            "不得增删或改写任何被冻结的科研语义。"
        ),
        "original_memory_consumption_claims": list(original_memory_claims),
        "memory_claim_repair_rules": (
            "memory_consumption_claims只能保留原列表中的逐字原项或撤回原项，"
            "不得新增、改写，且不得把本轮external_turn_context的raw_binding或"
            "selected_project_method_skill消息冒充为此前Dreaming反馈中的"
            "memory_exposure。若deterministic_findings说明本轮没有可见"
            "memory_exposures，必须撤回全部原项并输出空数组。"
        ),
        "operator_field_rules": {
            "consult_temporary_agents": (
                "只有该算子允许且必须提供1至7个temporary_tasks；其他算子必须为空数组"
            ),
            "promote_branch": ("只有该算子允许且必须提供promotion_draft；其他算子必须为null"),
            "branching_operators": (
                "branch_hypothesis、analogical_transfer、reframe_question必须提供中文"
                "working_hypothesis_cn；其他算子可为null"
            ),
            "retrieve_evidence": (
                "该算子在动作契约v3下必须填写3至10项retrieval_query_terms；"
                "每项是1至4个ASCII技术词组成的短语，action_body_cn只写中文检索意图。"
            ),
        },
        "authority_boundary": ("不得新增实验结果、创新证明、执行或发表授权；不得捏造来源。"),
        "output_requirement": "仅返回修复后的完整JSON对象，不返回解释或补丁数组",
    }
    if model_reauthored_chinese_fields:
        repair["model_reauthored_chinese_fields"] = model_reauthored_chinese_fields
        repair["model_reauthored_chinese_rules"] = (
            "这些字段的原始值未通过中文表达门，由配置Qwen在本次调用中自行重新表述；"
            "只可把已冻结的算子、选择理由、预期信息增益与假设展开成完整中文动作，"
            "不得改变算子或研究判断，不得新增来源、数据、实验结果、数值阈值、执行或发表授权。"
            "修复前后响应均永久留存，修复后内容仍是模型生成的开放探索内容而非科学证据。"
        )
    if mechanically_repairable_fields:
        repair["mechanically_repairable_fields"] = mechanically_repairable_fields
        allowed_repairs: dict[str, str] = {}
        if "action_body_cn" in mechanically_repairable_fields:
            allowed_repairs["legacy_retrieve_evidence_query"] = (
                "旧动作契约的action_body_cn不属于上面的逐字冻结字段。只从其原查询中"
                "按原顺序选择3至10个互异词；不得新增词、改写词、重排词，也不得新增、"
                "删除或改写查询行之后的中文说明。"
            )
        if "retrieval_query_terms" in mechanically_repairable_fields:
            allowed_repairs["structured_retrieve_evidence_query"] = (
                "只从原retrieval_query_terms列表按原顺序保留3至10项互异短语；"
                "不得新增、改写或重排任何短语，其他科研字段必须逐字保持。"
            )
        repair["allowed_mechanical_projection_repairs"] = allowed_repairs
    return [
        *original_messages,
        {"role": "assistant", "content": previous_response},
        {"role": "user", "content": canonical_json(repair)},
    ]


def _action_repair_response_schema(
    base_schema: dict[str, Any],
    *,
    frozen_fields: dict[str, JsonValue],
    step_index: int,
    branch_id: str,
) -> dict[str, Any]:
    """Make the provider schema reflect the same narrow mechanical repair envelope."""

    schema = cast(dict[str, Any], json.loads(canonical_json(base_schema)))
    try:
        properties = schema["properties"]
        operator_schema = schema["$defs"]["ResearchOperator"]
    except (KeyError, TypeError) as exc:
        raise AdaptiveResearchLoopError("adaptive action repair schema is incomplete") from exc
    if not isinstance(properties, dict) or not isinstance(operator_schema, dict):
        raise AdaptiveResearchLoopError("adaptive action repair schema has invalid properties")
    operator = frozen_fields.get("operator")
    if not isinstance(operator, str):
        raise AdaptiveResearchLoopError("adaptive action repair lost the frozen operator")
    operator_schema["enum"] = [operator]
    for field_name, exact_value in (
        ("step_index", step_index),
        ("branch_id", branch_id),
        ("selected_skill_ids", frozen_fields.get("selected_skill_ids", [])),
        ("source_refs", frozen_fields.get("source_refs", [])),
    ):
        field_schema = properties.get(field_name)
        if not isinstance(field_schema, dict):
            raise AdaptiveResearchLoopError(f"adaptive action repair schema lacks {field_name}")
        field_schema["const"] = exact_value
    original_query_terms = frozen_fields.get("retrieval_query_terms", [])
    mechanical_fields: set[str] = {
        field_name
        for field_name, value in frozen_fields.items()
        if _requires_model_chinese_reauthoring(
            field_name,
            value=value,
            frozen_operator=operator,
        )
    }
    for field_name in mechanical_fields:
        field_schema = properties.get(field_name)
        if isinstance(field_schema, dict):
            field_schema["description"] = (
                "由配置Qwen重新表述为中文；其他冻结字段定义的科研动作不得改变。"
            )
    original_body = frozen_fields.get("action_body_cn")
    parts = _split_retrieval_action_body(original_body) if isinstance(original_body, str) else None
    if (
        operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and parts is not None
        and not _retrieval_query_tokens_are_valid(parts[0])
    ):
        mechanical_fields.add("action_body_cn")
        tokens, prose = parts
        longest_ten = sorted((len(token) for token in tokens), reverse=True)[:10]
        maximum_query_length = len("检索查询：") + sum(longest_ten) + max(0, len(longest_ten) - 1)
        maximum_body_length = maximum_query_length + (1 + len(prose) if prose else 0)
        body_schema = properties.get("action_body_cn")
        if not isinstance(body_schema, dict):
            raise AdaptiveResearchLoopError("adaptive action repair schema lacks action_body_cn")
        body_schema["maxLength"] = min(
            int(body_schema.get("maxLength", maximum_body_length)),
            maximum_body_length,
        )
    if (
        operator == ResearchOperator.RETRIEVE_EVIDENCE.value
        and isinstance(original_query_terms, list)
        and original_query_terms
        and not _retrieval_query_terms_are_valid(original_query_terms)
    ):
        mechanical_fields.add("retrieval_query_terms")
        query_schema = properties.get("retrieval_query_terms")
        if not isinstance(query_schema, dict):
            raise AdaptiveResearchLoopError(
                "adaptive action repair schema lacks retrieval_query_terms"
            )
        query_schema["minItems"] = 3
        query_schema["maxItems"] = 10
        query_schema["uniqueItems"] = True
    for field_name, exact_value in frozen_fields.items():
        if field_name in mechanical_fields or field_name == "operator":
            continue
        field_schema = properties.get(field_name)
        if isinstance(field_schema, dict):
            field_schema["const"] = exact_value
    return schema


def _write_action_attempt_once(
    *,
    output_root: Path,
    step_index: int,
    attempt: AdaptiveActionModelAttempt,
) -> None:
    path = (
        output_root
        / "action-attempts"
        / f"step-{step_index:04d}"
        / f"attempt-{attempt.attempt_index:02d}-{attempt.attempt_hash}.json"
    )
    _write_once(path, (canonical_json(attempt) + "\n").encode("utf-8"))


def _write_action_call_registration_once(
    *,
    output_root: Path,
    raw_memory_store: RawMemoryStore,
    registration: AdaptiveActionModelCallRegistration,
) -> None:
    raw_payload = canonical_json(registration)
    raw_capture = raw_memory_store.capture_text(
        raw_payload,
        project_id=registration.project_id,
        source_kind=RawMemorySourceKind.TOOL_OUTPUT,
        source_label=(f"自适应科研循环第{registration.step_index}步动作模型调用预约"),
        source_ref=(
            f"adaptive-loop:{registration.loop_id}:step:{registration.step_index}:"
            f"action-call-registration:{registration.attempt_index}"
        ),
        original_name=(
            f"adaptive-action-call-registration-{registration.step_index:04d}-"
            f"{registration.attempt_index:02d}.json"
        ),
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=registration.registered_at,
    )
    raw_memory_store.verify_capture(raw_capture)
    path = (
        output_root
        / "action-call-registrations"
        / f"step-{registration.step_index:04d}"
        / (f"attempt-{registration.attempt_index:02d}-" f"{registration.registration_hash}.json")
    )
    _write_once(path, (canonical_json(registration) + "\n").encode("utf-8"))


def _load_current_step_call_registrations(
    *,
    output_root: Path,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> list[AdaptiveActionModelCallRegistration]:
    directory = output_root / "action-call-registrations" / f"step-{snapshot.next_step_index:04d}"
    if not directory.exists():
        return []
    registrations: list[AdaptiveActionModelCallRegistration] = []
    paths = sorted(directory.iterdir())
    if any(not path.is_file() or path.suffix != ".json" for path in paths):
        raise AdaptiveResearchLoopError(
            "adaptive model-call registration directory contains an unexpected entry"
        )
    for path in paths:
        try:
            raw = path.read_bytes()
            registration = AdaptiveActionModelCallRegistration.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptiveResearchLoopError(
                f"cannot replay adaptive model-call registration: {exc}"
            ) from exc
        if raw != (canonical_json(registration) + "\n").encode("utf-8"):
            raise AdaptiveResearchLoopError(
                "adaptive model-call registration JSON is not canonical"
            )
        expected_name = (
            f"attempt-{registration.attempt_index:02d}-" f"{registration.registration_hash}.json"
        )
        if path.name != expected_name:
            raise AdaptiveResearchLoopError("adaptive model-call registration filename mismatch")
        if (
            registration.loop_id != snapshot.seed.loop_id
            or registration.project_id != snapshot.seed.project_id
            or registration.step_index != snapshot.next_step_index
        ):
            raise AdaptiveResearchLoopError(
                "adaptive model-call registration belongs to another run"
            )
        registrations.append(registration)
    attempt_indices = [item.attempt_index for item in registrations]
    if attempt_indices != list(range(1, len(registrations) + 1)):
        raise AdaptiveResearchLoopError(
            "adaptive model-call registrations are missing, repeated, or reordered"
        )
    return registrations


def _write_skill_routing_call_registrations(
    *,
    output_root: Path,
    raw_memory_store: RawMemoryStore,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
    required_model_calls: int,
    registered_at: datetime,
) -> None:
    if not 0 <= required_model_calls <= 8:
        raise AdaptiveResearchLoopError("skill-routing model-call reservation count is invalid")
    routing_input_hash = canonical_sha256(
        {
            "seed": seed.model_dump(mode="json"),
            "snapshot_hash": snapshot.snapshot_hash,
            "branch": branch.model_dump(mode="json"),
            "maximum_skill_contexts": snapshot.policy.maximum_skill_contexts,
        }
    )
    for call_index in range(1, required_model_calls + 1):
        registration = AdaptiveSkillRoutingCallRegistration.create(
            registration_id=(
                f"adaptive:{seed.loop_id}:step:{snapshot.next_step_index}:"
                f"skill-routing:{call_index}"
            ),
            loop_id=seed.loop_id,
            project_id=seed.project_id,
            step_index=snapshot.next_step_index,
            call_index=call_index,
            routing_input_hash=routing_input_hash,
            registered_at=registered_at.astimezone(timezone.utc),
        )
        raw_capture = raw_memory_store.capture_text(
            canonical_json(registration),
            project_id=registration.project_id,
            source_kind=RawMemorySourceKind.TOOL_OUTPUT,
            source_label=(f"自适应科研循环第{registration.step_index}步技能路由调用预约"),
            source_ref=(
                f"adaptive-loop:{registration.loop_id}:step:"
                f"{registration.step_index}:skill-routing-call-registration:"
                f"{registration.call_index}"
            ),
            original_name=(
                f"adaptive-skill-call-registration-{registration.step_index:04d}-"
                f"{registration.call_index:02d}.json"
            ),
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=registration.registered_at,
        )
        raw_memory_store.verify_capture(raw_capture)
        path = (
            output_root
            / "skill-routing-call-registrations"
            / f"step-{snapshot.next_step_index:04d}"
            / (f"call-{call_index:02d}-{registration.registration_hash}.json")
        )
        _write_once(
            path,
            (canonical_json(registration) + "\n").encode("utf-8"),
        )


def _load_current_step_skill_call_registrations(
    *,
    output_root: Path,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> list[AdaptiveSkillRoutingCallRegistration]:
    directory = (
        output_root / "skill-routing-call-registrations" / f"step-{snapshot.next_step_index:04d}"
    )
    if not directory.exists():
        return []
    registrations: list[AdaptiveSkillRoutingCallRegistration] = []
    paths = sorted(directory.iterdir())
    if any(not path.is_file() or path.suffix != ".json" for path in paths):
        raise AdaptiveResearchLoopError(
            "adaptive skill-call registration directory contains an unexpected entry"
        )
    for path in paths:
        try:
            raw = path.read_bytes()
            registration = AdaptiveSkillRoutingCallRegistration.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptiveResearchLoopError(
                f"cannot replay adaptive skill-call registration: {exc}"
            ) from exc
        if raw != (canonical_json(registration) + "\n").encode("utf-8"):
            raise AdaptiveResearchLoopError(
                "adaptive skill-call registration JSON is not canonical"
            )
        expected_name = (
            f"call-{registration.call_index:02d}-" f"{registration.registration_hash}.json"
        )
        if path.name != expected_name:
            raise AdaptiveResearchLoopError("adaptive skill-call registration filename mismatch")
        if (
            registration.loop_id != snapshot.seed.loop_id
            or registration.project_id != snapshot.seed.project_id
            or registration.step_index != snapshot.next_step_index
        ):
            raise AdaptiveResearchLoopError(
                "adaptive skill-call registration belongs to another run"
            )
        registrations.append(registration)
    call_indices = [item.call_index for item in registrations]
    if call_indices != list(range(1, len(registrations) + 1)):
        raise AdaptiveResearchLoopError(
            "adaptive skill-call registrations are missing, repeated, or reordered"
        )
    return registrations


def _load_current_step_unresolved_model_call_count(
    *,
    output_root: Path,
    snapshot: AdaptiveResearchLoopSnapshot,
    raw_memory_store: RawMemoryStore,
) -> int:
    action_mirror = _load_current_step_call_registrations(
        output_root=output_root,
        snapshot=snapshot,
    )
    raw_captures = _project_raw_captures(
        raw_memory_store,
        project_id=snapshot.seed.project_id,
    )
    action_raw = _load_raw_action_call_registrations(
        raw_captures=raw_captures,
        snapshot=snapshot,
    )
    skill_mirror = _load_current_step_skill_call_registrations(
        output_root=output_root,
        snapshot=snapshot,
    )
    skill_raw = _load_raw_skill_call_registrations(
        raw_captures=raw_captures,
        snapshot=snapshot,
    )
    return len(_merge_action_registration_mirrors(action_mirror, action_raw)) + len(
        _merge_skill_registration_mirrors(skill_mirror, skill_raw)
    )


def _project_raw_captures(
    raw_memory_store: RawMemoryStore,
    *,
    project_id: str,
) -> list[RawMemoryCapture]:
    """Replay every project record so a renamed registration cannot disappear."""

    record_root = raw_memory_store.private_root / "projects" / project_id / "records"
    if not record_root.exists():
        return []
    captures: list[RawMemoryCapture] = []
    for path in sorted(record_root.glob("*/*/*.json")):
        try:
            captures.append(
                raw_memory_store.load_record(
                    path.resolve().relative_to(raw_memory_store.vault_root),
                    project_id=project_id,
                )
            )
        except (OSError, ValueError, RawMemoryError) as exc:
            raise AdaptiveResearchLoopError(
                "adaptive-loop raw-memory verification failed while replaying "
                f"the project ledger: {exc}"
            ) from exc
    return captures


def _load_raw_action_call_registrations(
    *,
    raw_captures: Sequence[RawMemoryCapture],
    snapshot: AdaptiveResearchLoopSnapshot,
) -> list[AdaptiveActionModelCallRegistration]:
    prefix = (
        f"adaptive-loop:{snapshot.seed.loop_id}:step:{snapshot.next_step_index}:"
        "action-call-registration:"
    )
    registrations: list[AdaptiveActionModelCallRegistration] = []
    for capture in raw_captures:
        envelope = capture.record.envelope
        if not envelope.source_ref.startswith(prefix):
            continue
        try:
            raw = capture.blob_path.read_bytes()
            registration = AdaptiveActionModelCallRegistration.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptiveResearchLoopError(
                f"cannot replay raw action-call registration: {exc}"
            ) from exc
        expected_ref = f"{prefix}{registration.attempt_index}"
        expected_name = (
            f"adaptive-action-call-registration-{registration.step_index:04d}-"
            f"{registration.attempt_index:02d}.json"
        )
        if (
            raw != canonical_json(registration).encode("utf-8")
            or envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
            or envelope.source_ref != expected_ref
            or envelope.source_label
            != f"自适应科研循环第{registration.step_index}步动作模型调用预约"
            or envelope.original_name != expected_name
            or envelope.media_type != "text/plain"
            or registration.loop_id != snapshot.seed.loop_id
            or registration.project_id != snapshot.seed.project_id
            or registration.step_index != snapshot.next_step_index
        ):
            raise AdaptiveResearchLoopError(
                "raw action-call registration provenance or payload mismatch"
            )
        registrations.append(registration)
    registrations.sort(key=lambda item: item.attempt_index)
    indices = [item.attempt_index for item in registrations]
    if indices != list(range(1, len(registrations) + 1)):
        raise AdaptiveResearchLoopError(
            "raw action-call registrations are missing, repeated, or reordered"
        )
    return registrations


def _load_raw_skill_call_registrations(
    *,
    raw_captures: Sequence[RawMemoryCapture],
    snapshot: AdaptiveResearchLoopSnapshot,
) -> list[AdaptiveSkillRoutingCallRegistration]:
    prefix = (
        f"adaptive-loop:{snapshot.seed.loop_id}:step:{snapshot.next_step_index}:"
        "skill-routing-call-registration:"
    )
    registrations: list[AdaptiveSkillRoutingCallRegistration] = []
    for capture in raw_captures:
        envelope = capture.record.envelope
        if not envelope.source_ref.startswith(prefix):
            continue
        try:
            raw = capture.blob_path.read_bytes()
            registration = AdaptiveSkillRoutingCallRegistration.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptiveResearchLoopError(
                f"cannot replay raw skill-call registration: {exc}"
            ) from exc
        expected_ref = f"{prefix}{registration.call_index}"
        expected_name = (
            f"adaptive-skill-call-registration-{registration.step_index:04d}-"
            f"{registration.call_index:02d}.json"
        )
        if (
            raw != canonical_json(registration).encode("utf-8")
            or envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
            or envelope.source_ref != expected_ref
            or envelope.source_label
            != f"自适应科研循环第{registration.step_index}步技能路由调用预约"
            or envelope.original_name != expected_name
            or envelope.media_type != "text/plain"
            or registration.loop_id != snapshot.seed.loop_id
            or registration.project_id != snapshot.seed.project_id
            or registration.step_index != snapshot.next_step_index
        ):
            raise AdaptiveResearchLoopError(
                "raw skill-call registration provenance or payload mismatch"
            )
        registrations.append(registration)
    registrations.sort(key=lambda item: item.call_index)
    indices = [item.call_index for item in registrations]
    if indices != list(range(1, len(registrations) + 1)):
        raise AdaptiveResearchLoopError(
            "raw skill-call registrations are missing, repeated, or reordered"
        )
    return registrations


def _merge_action_registration_mirrors(
    disk: Sequence[AdaptiveActionModelCallRegistration],
    raw: Sequence[AdaptiveActionModelCallRegistration],
) -> list[AdaptiveActionModelCallRegistration]:
    merged: dict[int, AdaptiveActionModelCallRegistration] = {}
    for registration in [*disk, *raw]:
        previous = merged.get(registration.attempt_index)
        if previous is not None and previous != registration:
            raise AdaptiveResearchLoopError("action-call registration mirrors disagree")
        merged[registration.attempt_index] = registration
    indices = sorted(merged)
    if indices != list(range(1, len(indices) + 1)):
        raise AdaptiveResearchLoopError(
            "action-call registration mirrors have a non-contiguous union"
        )
    return [merged[index] for index in indices]


def _merge_skill_registration_mirrors(
    disk: Sequence[AdaptiveSkillRoutingCallRegistration],
    raw: Sequence[AdaptiveSkillRoutingCallRegistration],
) -> list[AdaptiveSkillRoutingCallRegistration]:
    merged: dict[int, AdaptiveSkillRoutingCallRegistration] = {}
    for registration in [*disk, *raw]:
        previous = merged.get(registration.call_index)
        if previous is not None and previous != registration:
            raise AdaptiveResearchLoopError("skill-call registration mirrors disagree")
        merged[registration.call_index] = registration
    indices = sorted(merged)
    if indices != list(range(1, len(indices) + 1)):
        raise AdaptiveResearchLoopError(
            "skill-call registration mirrors have a non-contiguous union"
        )
    return [merged[index] for index in indices]


def _visible_memory_exposures(
    snapshot: AdaptiveResearchLoopSnapshot,
) -> list[ModelMemoryExposure]:
    return [
        exposure
        for event in snapshot.events[-_MAX_RECENT_EVENTS_IN_PROMPT:]
        for exposure in event.feedback.memory_exposures
    ]


def build_adaptive_research_messages(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    selected_branch: AdaptiveResearchBranch,
    skill_contexts: Sequence[LoopSkillContext],
    external_turn_contexts: Sequence[AdaptiveExternalTurnContext] = (),
    available_operator_ids: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Build the generic controller prompt; discipline skills stay separate."""

    instruction = (
        "你是自主科研循环当前环节的主Agent。科研目标与范围来自用户，但假设、机制、"
        "检索策略、下一动作、分支取舍和晋级草案必须由你生成。你不按固定步骤填空，"
        "而是在开放探索区从给定算子中自主选择最能增加信息量的一项；允许提出大胆但"
        "明确标为未验证的猜想，也允许放弃失败分支。不要为了通过门禁伪造引用、实验、"
        "创新或确定性。检索、工具、临时Agent和独立验证返回的反馈优先于自我评价。"
        "只有主动选择 promote_branch 时才填写完整晋级草案；晋级不等于创新已证实、"
        "不授权实验或发表。学科方法只来自后续独立技能消息，不得把技能当事实证据。"
        "本调用启用有界思考，reasoning_content 只作过程审计，不是科学证据。"
        "全部科研散文必须使用简体中文，技术标识、论文原题和路径可保留原文。"
        "只返回符合所附 JSON Schema 的一个对象。"
    )
    operator_descriptions = list(
        available_operator_ids
        if available_operator_ids is not None
        else _available_operator_descriptions(snapshot)
    )
    temporally_scoped_memory = snapshot.policy.schema_version == "adaptive-sovereign-loop-policy-v3"
    operator_explanations = {
        ResearchOperator.RETRIEVE_EVIDENCE.value: "主动补查原始文献、数据或反证",
        ResearchOperator.BRANCH_HYPOTHESIS.value: "从当前分支派生不同机制假设",
        ResearchOperator.ANALOGICAL_TRANSFER.value: "从相邻领域迁移可检验机制",
        ResearchOperator.REFRAME_QUESTION.value: "改变问题表述但保留目标边界",
        ResearchOperator.DECOMPOSE_UNCERTAINTY.value: "拆开当前未知量和关键判别点",
        ResearchOperator.CONSULT_TEMPORARY_AGENTS.value: "由本环节主Agent并行分配临时内容任务",
        ResearchOperator.RUN_SANDBOX_PROBE.value: "运行不构成正式证据的低成本沙箱探针",
        ResearchOperator.ADVERSARIAL_CRITIQUE.value: "主动寻找当前机制的反例和混杂",
        ResearchOperator.MUTATE_WORKFLOW_PROPOSAL.value: "提出下一轮策略改动但不改安全与证据门",
        ResearchOperator.CONSOLIDATE_DREAMING.value: (
            "由当前主Agent提出中文复核问题，从私有只追加原始层的完整历史中检索精确原文"
            "与哈希，并写可重建Dreaming投影；不改原始记录、不自动证明消费或收益"
            if temporally_scoped_memory
            else "整理可重建派生记忆而不改原始记录"
        ),
        ResearchOperator.PROMOTE_BRANCH.value: "申请进入严格证据晋级与独立验证",
        ResearchOperator.ABANDON_BRANCH.value: "保留记录并停止投入当前分支",
        ResearchOperator.STOP_EXPLORATION.value: "在预算内无合理下一步时主动结束",
    }
    recent_events = [
        {
            "step_index": event.step_index,
            "branch_id": event.branch_id,
            "operator": event.interaction.proposal.operator.value,
            "feedback_status": event.feedback.status.value,
            "feedback_summary_cn": event.feedback.summary_cn,
            "feedback_findings_cn": event.feedback.findings_cn,
            "memory_exposures": [
                item.model_dump(mode="json") for item in event.feedback.memory_exposures
            ],
            "created_branch_id": event.created_branch_id,
        }
        for event in snapshot.events[-_MAX_RECENT_EVENTS_IN_PROMPT:]
    ]
    active_branches = [
        {
            "branch_id": branch.branch_id,
            "parent_branch_id": branch.parent_branch_id,
            "title_cn": branch.title_cn,
            "working_hypothesis_cn": branch.working_hypothesis_cn,
            "status": branch.status.value,
        }
        for branch in snapshot.branches[-_MAX_BRANCHES_IN_PROMPT:]
    ]
    visible_memory_exposures = _visible_memory_exposures(snapshot)
    response_schema = _action_response_schema(
        operator_descriptions,
        visible_memory_exposures=visible_memory_exposures,
    )
    memory_control_observation = (
        build_adaptive_memory_control_observation(
            snapshot=snapshot,
            selected_branch_id=selected_branch.branch_id,
            available_operator_ids=operator_descriptions,
        )
        if snapshot.policy.schema_version
        in {
            "adaptive-sovereign-loop-policy-v2",
            "adaptive-sovereign-loop-policy-v3",
        }
        else None
    )
    task_payload = {
        "context_kind": "adaptive_research_next_action",
        "step_index": snapshot.next_step_index,
        "loop_id": seed.loop_id,
        "project_id": seed.project_id,
        "objective_cn": seed.objective_cn,
        "scope_cn": seed.scope_cn,
        "selected_branch": selected_branch.model_dump(mode="json"),
        "branch_archive": active_branches,
        "recent_external_feedback": recent_events,
        "available_operators": {
            operator: operator_explanations[operator] for operator in operator_descriptions
        },
        "available_skill_ids": [skill.skill_id for skill in skill_contexts],
        "operator_field_contract": {
            "memory_consumption_claims": (
                "只有在本轮确实使用此前Dreaming反馈中的结构化memory_exposures时才填写；"
                "必须逐字复制dreaming_step_index、selection_hash、record_id、"
                "payload_sha256与excerpt_sha256，fact_cn必须是对应excerpt_text中的"
                "中文原文片段，application_cn用中文说明该事实如何改变本轮决策。"
                "未使用时必须为空数组；本轮external_turn_context即使带有raw_binding也"
                "不是Dreaming memory_exposure，独立Skill消息也只是方法而不是"
                "memory_exposure，严禁据此填写本字段；若recent_external_feedback中"
                "没有任何memory_exposures，output_schema会令maxItems=0，此时本字段"
                "必须为空数组。该声明不证明记忆带来因果收益。"
            ),
            "temporary_tasks": (
                "仅当operator=consult_temporary_agents时必须为1至7项；"
                "其他所有operator必须为空数组。"
            ),
            "promotion_draft": (
                "仅当operator=promote_branch时必须为完整对象；" "其他所有operator必须为null。"
            ),
            "retrieve_evidence": (
                "当operator=retrieve_evidence时，由你在retrieval_query_terms中填写"
                "3至10个互异的ASCII学术检索短语，每项含1至4个技术词；"
                "action_body_cn只用中文说明检索目的。其他operator必须令该列表为空。"
            ),
            "working_hypothesis_cn": (
                "当operator为branch_hypothesis、analogical_transfer或"
                "reframe_question时必须为中文；其他operator允许为null。"
            ),
            "single_operator": "每轮只能选择一个operator，不得同时填充另一算子的专属字段。",
        },
        "strictness_boundary": {
            "exploration": (
                "可自由分支、类比、反驳、检索和低成本探针；猜想必须保持未验证，"
                "无需预先满足正式发表门。"
            ),
            "promotion": (
                "必须给出至少两个可追溯来源、可证伪机制、判别性测试、基线/对照、"
                "不确定性和有界资源；还必须已有外部反馈。"
            ),
            "execution_and_publication": (
                "本循环无权批准；正式执行、证据提升与发表仍需独立重放和人工签名。"
            ),
        },
        "output_schema": response_schema,
    }
    if temporally_scoped_memory:
        task_payload["workflow_proposal_history"] = [
            item.model_dump(mode="json")
            for item in build_adaptive_workflow_proposal_contexts(snapshot)
        ]
        task_payload["memory_recall_capability_contract"] = (
            build_adaptive_memory_recall_capability_contract().model_dump(mode="json")
        )
        field_contract = cast(
            dict[str, str],
            task_payload["operator_field_contract"],
        )
        field_contract["workflow_proposal_history"] = _WORKFLOW_PROPOSAL_HISTORY_BOUNDARY_CN
        field_contract["memory_recall_capability_contract"] = _MEMORY_RECALL_CAPABILITY_BOUNDARY_CN
    else:
        task_payload["strategy_notes_cn"] = snapshot.strategy_notes_cn
    if memory_control_observation is not None:
        task_payload["memory_control_observation"] = memory_control_observation.model_dump(
            mode="json"
        )
        field_contract = cast(
            dict[str, str],
            task_payload["operator_field_contract"],
        )
        field_contract["memory_control_observation"] = _MEMORY_CONTROL_USE_BOUNDARY_CN
    messages: list[dict[str, str]] = [{"role": "system", "content": instruction}]
    for context in external_turn_contexts:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    _external_turn_context_message_payload(context),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    for skill in skill_contexts:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "selected_project_method_skill",
                        "skill_id": skill.skill_id,
                        "source_ref": skill.source_ref,
                        "content_sha256": skill.content_sha256,
                        "skill_content": skill.content,
                        "use_boundary": ("仅作为解决问题的方法论，不是事实、文献、结果或审批。"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps(task_payload, ensure_ascii=False, sort_keys=True),
        }
    )
    return messages


def _action_response_schema(
    available_operator_ids: Sequence[str],
    *,
    visible_memory_exposures: Sequence[ModelMemoryExposure] = (),
) -> dict[str, Any]:
    """Constrain provider output to this turn's operators and exact memory exposure."""

    allowed = list(available_operator_ids)
    if not allowed or len(set(allowed)) != len(allowed):
        raise AdaptiveResearchLoopError(
            "adaptive action response schema needs unique available operators"
        )
    known = {operator.value for operator in ResearchOperator}
    if any(operator_id not in known for operator_id in allowed):
        raise AdaptiveResearchLoopError(
            "adaptive action response schema contains an unknown operator"
        )
    schema = ModelResearchActionDraft.model_json_schema()
    try:
        operator_schema = schema["$defs"]["ResearchOperator"]
        declared = operator_schema["enum"]
    except (KeyError, TypeError) as exc:
        raise AdaptiveResearchLoopError(
            "adaptive action response schema lacks the operator enum"
        ) from exc
    if set(declared) != known:
        raise AdaptiveResearchLoopError("adaptive action response schema operator enum drifted")
    operator_schema["enum"] = allowed
    try:
        claim_list_schema = schema["properties"]["memory_consumption_claims"]
        claim_schema = schema["$defs"]["ModelMemoryConsumptionClaim"]
        claim_properties = claim_schema["properties"]
    except (KeyError, TypeError) as exc:
        raise AdaptiveResearchLoopError(
            "adaptive action response schema lacks memory-consumption fields"
        ) from exc
    if not isinstance(claim_list_schema, dict) or not isinstance(claim_properties, dict):
        raise AdaptiveResearchLoopError(
            "adaptive action response schema memory-consumption shape drifted"
        )
    unique_record_count = len({item.record_id for item in visible_memory_exposures})
    claim_list_schema["maxItems"] = min(12, unique_record_count)
    claim_list_schema["description"] = (
        "Only exact Dreaming memory_exposures visible in recent_external_feedback may "
        "be claimed; selected Skill messages and external contexts are never exposures."
    )
    if visible_memory_exposures:
        exposure_fields: dict[str, Sequence[int | str]] = {
            "dreaming_step_index": [item.dreaming_step_index for item in visible_memory_exposures],
            "selection_hash": [item.selection_hash for item in visible_memory_exposures],
            "record_id": [item.record_id for item in visible_memory_exposures],
            "payload_sha256": [item.payload_sha256 for item in visible_memory_exposures],
            "excerpt_sha256": [item.excerpt_sha256 for item in visible_memory_exposures],
        }
        for field_name, values in exposure_fields.items():
            field_schema = claim_properties.get(field_name)
            if not isinstance(field_schema, dict):
                raise AdaptiveResearchLoopError(f"adaptive memory-claim schema lacks {field_name}")
            field_schema["enum"] = list(dict.fromkeys(values))
    schema_version = schema.get("properties", {}).get("schema_version")
    if not isinstance(schema_version, dict):
        raise AdaptiveResearchLoopError("adaptive action response schema lacks schema_version")
    schema_version["const"] = "adaptive-research-action-draft-v3"
    required = schema.get("required")
    if not isinstance(required, list):
        raise AdaptiveResearchLoopError("adaptive action response schema lacks required fields")
    for field_name in ("schema_version", "retrieval_query_terms"):
        if field_name not in required:
            required.append(field_name)
    return schema


def load_adaptive_research_loop_snapshot(
    path: Path | str,
    *,
    raw_memory_store: RawMemoryStore,
) -> AdaptiveResearchLoopSnapshot:
    """Load a canonical snapshot and recheck every referenced raw-memory record."""

    snapshot_path = Path(path).resolve()
    try:
        raw = snapshot_path.read_bytes()
        snapshot = AdaptiveResearchLoopSnapshot.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise AdaptiveResearchLoopError(f"cannot load adaptive-loop snapshot: {exc}") from exc
    expected = (canonical_json(snapshot) + "\n").encode("utf-8")
    if raw != expected:
        raise AdaptiveResearchLoopError("adaptive-loop snapshot JSON is not canonical")
    try:
        _verify_snapshot_raw_bindings(raw_memory_store, snapshot)
    except RawMemoryError as exc:
        raise AdaptiveResearchLoopError(
            f"adaptive-loop raw-memory verification failed: {exc}"
        ) from exc
    return snapshot


def _execute_model_selected_action(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
    environment: ResearchActionEnvironment,
    temporary_dispatcher: TemporaryResearchDispatcher | None,
    promotion_verifier: PromotionVerifier | None,
) -> _ActionTransition:
    operator = proposal.operator
    if operator in {
        ResearchOperator.RETRIEVE_EVIDENCE,
        ResearchOperator.RUN_SANDBOX_PROBE,
        ResearchOperator.CONSOLIDATE_DREAMING,
    }:
        feedback = environment.execute(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
        )
        _validate_environment_feedback(feedback, proposal)
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.OPEN_EXPLORATION,
            status_after=AdaptiveLoopRunStatus.RUNNING,
            external_action_increment=1,
            stalled=feedback.status is not FeedbackStatus.SUCCEEDED,
        )

    if operator is ResearchOperator.CONSULT_TEMPORARY_AGENTS:
        if temporary_dispatcher is None:
            feedback = _orchestrator_feedback(
                proposal,
                status=FeedbackStatus.BLOCKED,
                summary_cn="当前运行未配置临时Agent调度器，任务未执行且未丢失。",
                findings_cn=["需要由当前环节主Agent持有调度能力后再尝试。"],
            )
            return _ActionTransition(
                feedback=feedback,
                zone_after=ResearchLoopZone.OPEN_EXPLORATION,
                status_after=AdaptiveLoopRunStatus.RUNNING,
                stalled=True,
            )
        batch = temporary_dispatcher.dispatch(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
            tasks=proposal.temporary_tasks,
        )
        summaries = [item.summary_cn for item in batch.contributions]
        feedback = ExternalResearchFeedback.create(
            feedback_id=f"feedback:temporary:{snapshot.next_step_index}",
            branch_id=proposal.branch_id,
            operator=proposal.operator,
            origin=FeedbackOrigin.TEMPORARY_AGENT,
            status=FeedbackStatus.SUCCEEDED,
            summary_cn="临时Agent已并行完成任务并在归档后移除运行时身份。",
            findings_cn=summaries,
            artifact_refs=[f"archive:{item.archive_hash}" for item in batch.contributions],
            temporary_agent_count=len(batch.contributions),
            independent_of_action_author=True,
        )
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.OPEN_EXPLORATION,
            status_after=AdaptiveLoopRunStatus.RUNNING,
            temporary_batch=batch,
            external_action_increment=1,
            temporary_agent_increment=len(batch.contributions),
        )

    if operator is ResearchOperator.PROMOTE_BRANCH:
        assessment = assess_branch_promotion(snapshot=snapshot, proposal=proposal)
        if not assessment.passed:
            feedback = ExternalResearchFeedback.create(
                feedback_id=f"feedback:promotion:{snapshot.next_step_index}",
                branch_id=proposal.branch_id,
                operator=proposal.operator,
                origin=FeedbackOrigin.ORCHESTRATOR,
                status=FeedbackStatus.NEGATIVE_RESULT,
                summary_cn="该分支尚未满足证据晋级条件，已返回精确缺口供下一轮自主处理。",
                findings_cn=assessment.findings_cn,
            )
            return _ActionTransition(
                feedback=feedback,
                zone_after=ResearchLoopZone.OPEN_EXPLORATION,
                status_after=AdaptiveLoopRunStatus.RUNNING,
                promotion_assessment=assessment,
                stalled=True,
            )
        if promotion_verifier is None:
            feedback = ExternalResearchFeedback.create(
                feedback_id=f"feedback:verification:{snapshot.next_step_index}",
                branch_id=proposal.branch_id,
                operator=proposal.operator,
                origin=FeedbackOrigin.ORCHESTRATOR,
                status=FeedbackStatus.BLOCKED,
                summary_cn="机械晋级门已通过，但缺少独立验证器，正式执行继续被阻断。",
                findings_cn=["配置独立验证器并重放来源、可证伪性、对照和资源检查。"],
            )
            return _ActionTransition(
                feedback=feedback,
                zone_after=ResearchLoopZone.FORMAL_VERIFICATION,
                status_after=AdaptiveLoopRunStatus.PAUSED_VERIFIER_REQUIRED,
                promotion_assessment=assessment,
                stalled=True,
            )
        verification = promotion_verifier.verify(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
            assessment=assessment,
        )
        _validate_formal_verification(verification, proposal, assessment)
        if verification.passed:
            feedback = ExternalResearchFeedback.create(
                feedback_id=f"feedback:verification:{snapshot.next_step_index}",
                branch_id=proposal.branch_id,
                operator=proposal.operator,
                origin=FeedbackOrigin.INDEPENDENT_VERIFIER,
                status=FeedbackStatus.SUCCEEDED,
                summary_cn="分支通过独立的执行前验证，现等待人工范围审批；尚未执行实验。",
                artifact_refs=[f"verification:{verification.verification_hash}"],
                independent_of_action_author=True,
            )
            return _ActionTransition(
                feedback=feedback,
                zone_after=ResearchLoopZone.WAITING_HUMAN_SCOPE,
                status_after=AdaptiveLoopRunStatus.PAUSED_HUMAN_SCOPE,
                promotion_assessment=assessment,
                formal_verification=verification,
                external_action_increment=1,
            )
        feedback = ExternalResearchFeedback.create(
            feedback_id=f"feedback:verification:{snapshot.next_step_index}",
            branch_id=proposal.branch_id,
            operator=proposal.operator,
            origin=FeedbackOrigin.INDEPENDENT_VERIFIER,
            status=FeedbackStatus.NEGATIVE_RESULT,
            summary_cn="独立验证否决了本次晋级，反馈已回流开放探索而不改写原分支历史。",
            findings_cn=verification.findings_cn,
            artifact_refs=[f"verification:{verification.verification_hash}"],
            independent_of_action_author=True,
        )
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.OPEN_EXPLORATION,
            status_after=AdaptiveLoopRunStatus.RUNNING,
            promotion_assessment=assessment,
            formal_verification=verification,
            external_action_increment=1,
            stalled=True,
        )

    if operator is ResearchOperator.MUTATE_WORKFLOW_PROPOSAL:
        feedback = _orchestrator_feedback(
            proposal,
            status=FeedbackStatus.SUCCEEDED,
            summary_cn=("工作流候选已加入后续提示上下文；安全、权限、证据和发表门没有改变。"),
        )
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.OPEN_EXPLORATION,
            status_after=AdaptiveLoopRunStatus.RUNNING,
            strategy_note_cn=proposal.action_body_cn,
        )

    if operator is ResearchOperator.ABANDON_BRANCH:
        feedback = _orchestrator_feedback(
            proposal,
            status=FeedbackStatus.SUCCEEDED,
            summary_cn="当前分支已停止投入，但其完整历史仍保留在开放分支档案中。",
        )
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.OPEN_EXPLORATION,
            status_after=AdaptiveLoopRunStatus.RUNNING,
        )

    if operator is ResearchOperator.STOP_EXPLORATION:
        feedback = _orchestrator_feedback(
            proposal,
            status=FeedbackStatus.SUCCEEDED,
            summary_cn="主Agent自主判断当前预算内没有更高价值动作，循环有证据地停止。",
        )
        return _ActionTransition(
            feedback=feedback,
            zone_after=ResearchLoopZone.TERMINAL,
            status_after=AdaptiveLoopRunStatus.STOPPED_BY_MODEL,
        )

    created_branch_id: str | None = None
    if operator in {
        ResearchOperator.BRANCH_HYPOTHESIS,
        ResearchOperator.ANALOGICAL_TRANSFER,
        ResearchOperator.REFRAME_QUESTION,
    }:
        created_branch_id = _derived_branch_id(snapshot, proposal)
    feedback = _orchestrator_feedback(
        proposal,
        status=FeedbackStatus.SUCCEEDED,
        summary_cn=("模型选择的开放探索动作已记录；其内容保持未验证，并将在后续外部反馈中检验。"),
    )
    return _ActionTransition(
        feedback=feedback,
        zone_after=ResearchLoopZone.OPEN_EXPLORATION,
        status_after=AdaptiveLoopRunStatus.RUNNING,
        created_branch_id=created_branch_id,
    )


def assess_branch_promotion(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
) -> PromotionGateAssessment:
    """Apply strict checks only when the model requests branch promotion."""

    draft = proposal.promotion_draft
    if draft is None:
        raise AdaptiveResearchLoopError("promotion assessment requires promotion_draft")
    source_refs = _ordered_unique([*proposal.source_refs, *draft.source_refs])
    branch_feedback = [
        event.feedback for event in snapshot.events if event.branch_id == proposal.branch_id
    ]
    external_feedback = any(
        feedback.origin
        in {
            FeedbackOrigin.EXTERNAL_RETRIEVAL,
            FeedbackOrigin.SANDBOX_TOOL,
            FeedbackOrigin.TEMPORARY_AGENT,
            FeedbackOrigin.INDEPENDENT_VERIFIER,
            FeedbackOrigin.DREAMING_PROJECTION,
        }
        and feedback.status in {FeedbackStatus.SUCCEEDED, FeedbackStatus.NEGATIVE_RESULT}
        for feedback in branch_feedback
    )
    checks = {
        "source_traceable": all(_looks_traceable_ref(item) for item in source_refs),
        "multiple_sources_present": len(source_refs) >= 2,
        "falsifiable": _contains_chinese(draft.falsifier_cn),
        "decisive_test_present": _contains_chinese(draft.decisive_test_cn),
        "baseline_and_control_present": _contains_chinese(draft.baseline_and_control_cn),
        "uncertainty_declared": bool(draft.known_uncertainties_cn),
        "external_feedback_present": external_feedback,
        "resource_request_bounded": (
            draft.requested_cpu_count <= 64
            and draft.requested_memory_mb <= 262_144
            and draft.requested_walltime_seconds <= 86_400
        ),
        "no_authority_claim": (
            not draft.innovation_verified
            and not draft.scientific_evidence_established
            and not draft.execution_authorized
            and not draft.publication_authorized
        ),
    }
    finding_by_check = {
        "source_traceable": "存在不可追溯来源引用，必须使用原始记录、文献或工具产物标识。",
        "multiple_sources_present": "晋级草案至少需要两个互异来源，避免单一来源锚定。",
        "falsifiable": "晋级草案缺少可导致假设失败的明确反例条件。",
        "decisive_test_present": "晋级草案缺少能区分机制的判别性测试。",
        "baseline_and_control_present": "晋级草案缺少有效基线或判别性对照。",
        "uncertainty_declared": "晋级草案必须保留至少一项已知不确定性。",
        "external_feedback_present": "当前分支尚未获得检索、工具、临时Agent或派生记忆的外部反馈。",
        "resource_request_bounded": "晋级草案资源请求超出有界本地审查范围。",
        "no_authority_claim": "晋级草案越权声称已创新、已有证据、可执行或可发表。",
    }
    findings = [finding_by_check[key] for key, passed in checks.items() if not passed]
    return PromotionGateAssessment.create(
        branch_id=proposal.branch_id,
        **checks,
        findings_cn=findings,
        passed=all(checks.values()) and not findings,
    )


def _advance_snapshot(
    snapshot: AdaptiveResearchLoopSnapshot,
    event: AdaptiveLoopEvent,
    transition: _ActionTransition,
    *,
    skill_model_call_increment: int = 0,
    action_model_call_increment: int = 1,
) -> AdaptiveResearchLoopSnapshot:
    branches = [branch.model_copy(deep=True) for branch in snapshot.branches]
    branch_by_id = {branch.branch_id: branch for branch in branches}
    selected = branch_by_id[event.branch_id]
    selected.action_hashes.append(event.interaction.interaction_hash)
    selected.feedback_hashes.append(event.feedback.feedback_hash)
    operator = event.interaction.proposal.operator

    if transition.created_branch_id is not None:
        active_count = sum(branch.status is ResearchBranchStatus.ACTIVE for branch in branches)
        if active_count >= snapshot.policy.max_active_branches:
            raise AdaptiveResearchLoopError("adaptive branch archive reached active limit")
        proposal = event.interaction.proposal
        branches.append(
            AdaptiveResearchBranch(
                branch_id=transition.created_branch_id,
                parent_branch_id=proposal.branch_id,
                created_step=event.step_index,
                title_cn=proposal.action_title_cn,
                working_hypothesis_cn=str(proposal.working_hypothesis_cn),
                action_hashes=[event.interaction.interaction_hash],
                feedback_hashes=[event.feedback.feedback_hash],
            )
        )
    elif operator is ResearchOperator.ABANDON_BRANCH:
        selected.status = ResearchBranchStatus.ABANDONED
    elif event.promotion_assessment is not None:
        selected.promotion_assessment_hash = event.promotion_assessment.assessment_hash
        if event.formal_verification is None:
            selected.status = (
                ResearchBranchStatus.PENDING_VERIFICATION
                if event.promotion_assessment.passed
                else ResearchBranchStatus.ACTIVE
            )
        else:
            selected.formal_verification_hash = event.formal_verification.verification_hash
            selected.status = (
                ResearchBranchStatus.READY_FOR_HUMAN_SCOPE
                if event.formal_verification.passed
                else ResearchBranchStatus.VERIFICATION_REJECTED
            )
            if not event.formal_verification.passed:
                selected.status = ResearchBranchStatus.ACTIVE

    strategy_notes = [*snapshot.strategy_notes_cn]
    if transition.strategy_note_cn is not None:
        strategy_notes.append(transition.strategy_note_cn)
    stalls = snapshot.consecutive_stalls + 1 if transition.stalled else 0
    status = transition.status_after
    zone = transition.zone_after
    if status is AdaptiveLoopRunStatus.RUNNING and stalls >= snapshot.policy.max_consecutive_stalls:
        status = AdaptiveLoopRunStatus.PAUSED_PLATEAU
        zone = ResearchLoopZone.TERMINAL
    if status is AdaptiveLoopRunStatus.RUNNING and not any(
        branch.status is ResearchBranchStatus.ACTIVE for branch in branches
    ):
        status = AdaptiveLoopRunStatus.STOPPED_BY_MODEL
        zone = ResearchLoopZone.TERMINAL
    return AdaptiveResearchLoopSnapshot.create(
        seed=snapshot.seed,
        policy=snapshot.policy,
        zone=zone,
        status=status,
        next_step_index=snapshot.next_step_index + 1,
        branches=branches,
        events=[*snapshot.events, event],
        strategy_notes_cn=strategy_notes,
        model_call_count=(
            snapshot.model_call_count + action_model_call_increment + skill_model_call_increment
        ),
        skill_routing_model_call_count=(
            snapshot.skill_routing_model_call_count + skill_model_call_increment
        ),
        external_action_count=(
            snapshot.external_action_count + transition.external_action_increment
        ),
        temporary_agent_count=(
            snapshot.temporary_agent_count + transition.temporary_agent_increment
        ),
        consecutive_stalls=stalls,
    )


def _replace_snapshot(
    snapshot: AdaptiveResearchLoopSnapshot,
    *,
    status: AdaptiveLoopRunStatus,
    zone: ResearchLoopZone,
) -> AdaptiveResearchLoopSnapshot:
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload.update({"status": status, "zone": zone})
    return AdaptiveResearchLoopSnapshot.create(**payload)


def _block_snapshot_for_unresolved_model_calls(
    snapshot: AdaptiveResearchLoopSnapshot,
    *,
    unresolved_count: int,
) -> AdaptiveResearchLoopSnapshot:
    if not 1 <= unresolved_count <= 12:
        raise AdaptiveResearchLoopError(
            "unresolved adaptive model-call registration count is invalid"
        )
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    payload.update(
        {
            "status": AdaptiveLoopRunStatus.BLOCKED,
            "zone": ResearchLoopZone.TERMINAL,
            "model_call_count": snapshot.model_call_count + unresolved_count,
            "unresolved_model_call_count": unresolved_count,
        }
    )
    return AdaptiveResearchLoopSnapshot.create(**payload)


def _budget_status(
    snapshot: AdaptiveResearchLoopSnapshot,
) -> AdaptiveLoopRunStatus | None:
    policy = snapshot.policy
    completed_steps = snapshot.next_step_index - 1
    if completed_steps >= policy.max_steps or snapshot.model_call_count >= policy.max_model_calls:
        return AdaptiveLoopRunStatus.PAUSED_BUDGET
    return None


def _required_skill_provider_calls(
    provider: SkillProvider | None,
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
) -> int:
    if provider is None:
        return 0
    required = getattr(provider, "required_model_calls", None)
    if not callable(required):
        return 0
    value = required(seed=seed, snapshot=snapshot, branch=branch)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AdaptiveResearchLoopError(
            "skill provider returned an invalid required model-call count"
        )
    return value


def _last_skill_provider_calls(provider: SkillProvider | None) -> int:
    if provider is None:
        return 0
    value = getattr(provider, "last_model_call_count", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AdaptiveResearchLoopError("skill provider exposed an invalid actual model-call count")
    return value


def _default_branch(snapshot: AdaptiveResearchLoopSnapshot) -> AdaptiveResearchBranch:
    active = [
        branch for branch in snapshot.branches if branch.status is ResearchBranchStatus.ACTIVE
    ]
    if not active:
        raise AdaptiveResearchLoopError("adaptive loop has no active research branch")
    return active[-1]


def _validate_proposal_against_state(
    *,
    proposal: ModelResearchActionDraft,
    snapshot: AdaptiveResearchLoopSnapshot,
    skill_contexts: Sequence[LoopSkillContext],
    available_operator_ids: Sequence[str] | None = None,
) -> None:
    if proposal.step_index != snapshot.next_step_index:
        raise AdaptiveResearchLoopError("model selected an action for the wrong loop step")
    branches = {branch.branch_id: branch for branch in snapshot.branches}
    if proposal.branch_id not in branches:
        raise AdaptiveResearchLoopError("model selected an absent research branch")
    if branches[proposal.branch_id].status is not ResearchBranchStatus.ACTIVE:
        raise AdaptiveResearchLoopError("model selected an inactive research branch")
    allowed_skills = {skill.skill_id for skill in skill_contexts}
    selected_skills = set(proposal.selected_skill_ids)
    if not selected_skills.issubset(allowed_skills):
        raise AdaptiveResearchLoopError("model selected a skill that was not injected")
    for task in proposal.temporary_tasks:
        if not set(task.selected_skill_ids).issubset(allowed_skills):
            raise AdaptiveResearchLoopError("temporary task selected a skill that was not injected")
    allowed_operators = set(
        available_operator_ids
        if available_operator_ids is not None
        else _available_operator_descriptions(snapshot)
    )
    if proposal.operator.value not in allowed_operators:
        raise AdaptiveResearchLoopError(
            "model selected an operator whose branch or resource budget is unavailable"
        )
    if proposal.temporary_tasks and (
        snapshot.temporary_agent_count + len(proposal.temporary_tasks)
        > snapshot.policy.max_temporary_agents
    ):
        raise AdaptiveResearchLoopError(
            "model requested more temporary agents than the remaining loop budget"
        )
    visible_exposures = {
        (
            exposure.dreaming_step_index,
            exposure.selection_hash,
            exposure.record_id,
            exposure.payload_sha256,
            exposure.excerpt_sha256,
        ): exposure
        for event in snapshot.events[-_MAX_RECENT_EVENTS_IN_PROMPT:]
        for exposure in event.feedback.memory_exposures
    }
    for claim in proposal.memory_consumption_claims:
        key = (
            claim.dreaming_step_index,
            claim.selection_hash,
            claim.record_id,
            claim.payload_sha256,
            claim.excerpt_sha256,
        )
        exposure = visible_exposures.get(key)
        if exposure is None:
            raise AdaptiveResearchLoopError(
                "model claimed memory that was not exposed in the current prompt"
            )
        if claim.fact_cn not in exposure.excerpt_text:
            raise AdaptiveResearchLoopError(
                "model memory fact is not an exact span of its recalled excerpt"
            )


def _available_operator_descriptions(
    snapshot: AdaptiveResearchLoopSnapshot,
    *,
    environment: ResearchActionEnvironment | None = None,
    temporary_dispatcher: TemporaryResearchDispatcher | None = None,
) -> list[str]:
    """Return capability IDs still reachable under local branch/resource budgets."""

    operators = [
        ResearchOperator.DECOMPOSE_UNCERTAINTY,
        ResearchOperator.ADVERSARIAL_CRITIQUE,
        ResearchOperator.MUTATE_WORKFLOW_PROPOSAL,
        ResearchOperator.ABANDON_BRANCH,
        ResearchOperator.STOP_EXPLORATION,
    ]
    active_count = sum(branch.status is ResearchBranchStatus.ACTIVE for branch in snapshot.branches)
    if active_count < snapshot.policy.max_active_branches:
        operators.extend(
            [
                ResearchOperator.BRANCH_HYPOTHESIS,
                ResearchOperator.ANALOGICAL_TRANSFER,
                ResearchOperator.REFRAME_QUESTION,
            ]
        )
    external_budget_remains = snapshot.external_action_count < snapshot.policy.max_external_actions
    if external_budget_remains:
        supported = _environment_supported_operators(environment)
        operators.extend(
            operator
            for operator in (
                ResearchOperator.RETRIEVE_EVIDENCE,
                ResearchOperator.RUN_SANDBOX_PROBE,
                ResearchOperator.CONSOLIDATE_DREAMING,
            )
            if operator in supported
        )
        operators.append(ResearchOperator.PROMOTE_BRANCH)
        if snapshot.temporary_agent_count < snapshot.policy.max_temporary_agents and (
            environment is None or temporary_dispatcher is not None
        ):
            operators.append(ResearchOperator.CONSULT_TEMPORARY_AGENTS)
    return [operator.value for operator in operators]


def _apply_operator_catalog_provider(
    provider: OperatorCatalogProvider | None,
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
    mechanically_available_operator_ids: Sequence[str],
) -> list[str]:
    mechanical = list(mechanically_available_operator_ids)
    if provider is None:
        return mechanical
    try:
        proposed = list(
            provider(
                seed=seed,
                snapshot=snapshot,
                branch=branch,
                mechanically_available_operator_ids=tuple(mechanical),
            )
        )
    except TypeError as exc:
        raise AdaptiveResearchLoopError(
            "operator catalog provider returned a non-iterable catalog"
        ) from exc
    if not proposed:
        raise AdaptiveResearchLoopError(
            "operator catalog provider removed every mechanically available operator"
        )
    if any(not isinstance(item, str) for item in proposed):
        raise AdaptiveResearchLoopError(
            "operator catalog provider returned a non-string operator ID"
        )
    if len(proposed) != len(set(proposed)):
        raise AdaptiveResearchLoopError("operator catalog provider repeated an operator ID")
    mechanical_set = set(mechanical)
    if any(item not in mechanical_set for item in proposed):
        raise AdaptiveResearchLoopError(
            "operator catalog provider may only remove mechanically available operators"
        )
    proposed_set = set(proposed)
    if proposed != [item for item in mechanical if item in proposed_set]:
        raise AdaptiveResearchLoopError(
            "operator catalog provider changed the mechanical operator order"
        )
    return proposed


def _environment_supported_operators(
    environment: ResearchActionEnvironment | None,
) -> frozenset[ResearchOperator]:
    capability_operators = frozenset(
        {
            ResearchOperator.RETRIEVE_EVIDENCE,
            ResearchOperator.RUN_SANDBOX_PROBE,
            ResearchOperator.CONSOLIDATE_DREAMING,
        }
    )
    if environment is None:
        return capability_operators
    provider = getattr(environment, "supported_operators", None)
    if provider is None:
        return capability_operators
    value = provider() if callable(provider) else provider
    try:
        normalized = frozenset(ResearchOperator(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise AdaptiveResearchLoopError(
            "research environment exposed invalid operator capabilities"
        ) from exc
    if not normalized.issubset(capability_operators):
        raise AdaptiveResearchLoopError("research environment exposed a non-capability operator")
    return normalized


def _validate_environment_feedback(
    feedback: ExternalResearchFeedback,
    proposal: ModelResearchActionDraft,
) -> None:
    if feedback.branch_id != proposal.branch_id:
        raise AdaptiveResearchLoopError("environment feedback branch mismatch")
    if feedback.operator is not proposal.operator:
        raise AdaptiveResearchLoopError("environment feedback operator mismatch")
    allowed_origins = {
        ResearchOperator.RETRIEVE_EVIDENCE: {FeedbackOrigin.EXTERNAL_RETRIEVAL},
        ResearchOperator.RUN_SANDBOX_PROBE: {FeedbackOrigin.SANDBOX_TOOL},
        ResearchOperator.CONSOLIDATE_DREAMING: {FeedbackOrigin.DREAMING_PROJECTION},
    }
    if feedback.origin not in allowed_origins[proposal.operator]:
        raise AdaptiveResearchLoopError("environment feedback origin mismatch")


def _validate_formal_verification(
    verification: FormalPromotionVerification,
    proposal: ModelResearchActionDraft,
    assessment: PromotionGateAssessment,
) -> None:
    if verification.branch_id != proposal.branch_id:
        raise AdaptiveResearchLoopError("formal verification branch mismatch")
    if verification.promotion_assessment_hash != assessment.assessment_hash:
        raise AdaptiveResearchLoopError("formal verification assessment hash mismatch")


def _orchestrator_feedback(
    proposal: ModelResearchActionDraft,
    *,
    status: FeedbackStatus,
    summary_cn: str,
    findings_cn: Sequence[str] = (),
) -> ExternalResearchFeedback:
    return ExternalResearchFeedback.create(
        feedback_id=f"feedback:orchestrator:{proposal.step_index}",
        branch_id=proposal.branch_id,
        operator=proposal.operator,
        origin=FeedbackOrigin.ORCHESTRATOR,
        status=status,
        summary_cn=summary_cn,
        findings_cn=list(findings_cn),
    )


def _derived_branch_id(
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
) -> str:
    digest = canonical_sha256(
        {
            "loop_id": snapshot.seed.loop_id,
            "step_index": snapshot.next_step_index,
            "parent_branch_id": proposal.branch_id,
            "proposal": proposal.model_dump(mode="json"),
        }
    )
    return f"branch_{digest[:24]}"


def _looks_traceable_ref(value: str) -> bool:
    normalized = value.strip()
    if len(normalized) < 8 or any(character.isspace() for character in normalized):
        return False
    return bool(
        re.match(
            r"^(rawmem_[0-9a-f]{64}|https?://|doi:|arxiv:|artifact:|sha256:|"
            r"tool:|archive:|verification:)",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _capture_model_text(
    *,
    raw_memory_store: RawMemoryStore,
    seed: AdaptiveResearchSeed,
    step_index: int,
    attempt_index: int,
    label: str,
    suffix: str,
    text: str,
    captured_at: datetime,
) -> RawMemoryBinding:
    capture = raw_memory_store.capture_text(
        text,
        project_id=seed.project_id,
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label=(f"自适应科研循环第{step_index}步第{attempt_index}次动作尝试：{label}"),
        source_ref=(
            f"adaptive-loop:{seed.loop_id}:step:{step_index}:" f"attempt:{attempt_index}:{suffix}"
        ),
        original_name=(
            f"adaptive-loop-step-{step_index:04d}-attempt-{attempt_index:02d}-" f"{suffix}.txt"
        ),
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=captured_at.astimezone(timezone.utc),
    )
    return capture.binding(raw_memory_store.vault_root)


def _capture_event_payload(
    *,
    raw_memory_store: RawMemoryStore,
    seed: AdaptiveResearchSeed,
    step_index: int,
    interaction: AdaptiveLoopModelInteraction,
    transition: _ActionTransition,
    captured_at: datetime,
) -> RawMemoryBinding:
    payload = canonical_json(
        {
            "interaction": interaction.model_dump(mode="json"),
            "transition": transition.model_dump(mode="json"),
        }
    )
    capture = raw_memory_store.capture_text(
        payload,
        project_id=seed.project_id,
        source_kind=RawMemorySourceKind.TOOL_OUTPUT,
        source_label=f"自适应科研循环第{step_index}步机械转移记录",
        source_ref=f"adaptive-loop:{seed.loop_id}:step:{step_index}:transition",
        original_name=f"adaptive-loop-step-{step_index:04d}-transition.json.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=captured_at.astimezone(timezone.utc),
    )
    return capture.binding(raw_memory_store.vault_root)


def _verify_raw_binding(
    store: RawMemoryStore,
    binding: RawMemoryBinding,
    project_id: str,
) -> None:
    capture = store.load_record(binding.record_relative_path, project_id=project_id)
    actual = capture.binding(store.vault_root)
    if actual != binding:
        raise AdaptiveResearchLoopError("adaptive-loop raw-memory binding mismatch")


def _verify_snapshot_raw_bindings(
    store: RawMemoryStore,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> None:
    project_id = snapshot.seed.project_id
    _verify_raw_binding(store, snapshot.seed.raw_seed_binding, project_id)
    raw_captures = _project_raw_captures(store, project_id=project_id)
    transitions: list[_ActionTransition] = []
    verified_skill_model_call_count = 0
    for event_index, event in enumerate(snapshot.events):
        prior_events = snapshot.events[:event_index]
        _verify_memory_control_observation_message_projection(
            event.interaction.messages,
            snapshot=snapshot,
            event=event,
            prior_events=prior_events,
        )
        for context in event.interaction.external_turn_contexts:
            _verify_external_turn_context_against_raw(
                context,
                seed=snapshot.seed,
                expected_step=event.step_index,
                raw_memory_store=store,
            )
        _verify_external_turn_context_message_projection(
            event.interaction.messages,
            event.interaction.external_turn_contexts,
        )
        for attempt in event.interaction.rejected_attempts:
            _verify_memory_control_observation_message_projection(
                attempt.messages,
                snapshot=snapshot,
                event=event,
                prior_events=prior_events,
            )
            _verify_external_turn_context_message_projection(
                attempt.messages,
                event.interaction.external_turn_contexts,
            )
            _verify_raw_binding(store, attempt.response_binding, project_id)
            _verify_raw_binding(store, attempt.reasoning_binding, project_id)
        _verify_raw_binding(store, event.interaction.response_binding, project_id)
        _verify_raw_binding(store, event.interaction.reasoning_binding, project_id)
        _verify_raw_binding(store, event.event_payload_binding, project_id)
        transitions.append(_verify_event_payload_projection(store, event, project_id=project_id))
        step_snapshot = snapshot.model_copy(update={"next_step_index": event.step_index})
        raw_action_registrations = _load_raw_action_call_registrations(
            raw_captures=raw_captures,
            snapshot=step_snapshot,
        )
        if raw_action_registrations != event.interaction.model_call_registrations:
            raise AdaptiveResearchLoopError(
                "completed action calls differ from their sovereign raw reservations"
            )
        verified_skill_model_call_count += len(
            _load_raw_skill_call_registrations(
                raw_captures=raw_captures,
                snapshot=step_snapshot,
            )
        )
    if verified_skill_model_call_count != snapshot.skill_routing_model_call_count:
        raise AdaptiveResearchLoopError(
            "snapshot skill-routing call count differs from sovereign raw reservations"
        )
    _verify_snapshot_transition_replay(
        snapshot,
        transitions,
        verified_skill_model_call_count=verified_skill_model_call_count,
    )


def _verify_event_payload_projection(
    store: RawMemoryStore,
    event: AdaptiveLoopEvent,
    *,
    project_id: str,
) -> _ActionTransition:
    capture = store.load_record(
        event.event_payload_binding.record_relative_path,
        project_id=project_id,
    )
    try:
        raw = capture.blob_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdaptiveResearchLoopError(
            f"adaptive event payload is not canonical UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or raw != canonical_json(payload).encode("utf-8"):
        raise AdaptiveResearchLoopError("adaptive event payload JSON is not canonical")
    envelope = capture.record.envelope
    expected_ref = f"adaptive-loop:{event.loop_id}:step:{event.step_index}:transition"
    expected_label = f"自适应科研循环第{event.step_index}步机械转移记录"
    expected_name = f"adaptive-loop-step-{event.step_index:04d}-transition.json.txt"
    if (
        envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
        or envelope.source_ref != expected_ref
        or envelope.source_label != expected_label
        or envelope.original_name != expected_name
        or envelope.media_type != "text/plain"
    ):
        raise AdaptiveResearchLoopError(
            "adaptive event payload raw-memory provenance is not canonical"
        )
    if set(payload) != {"interaction", "transition"}:
        raise AdaptiveResearchLoopError(
            "adaptive event payload contains an undeclared top-level field"
        )
    if payload.get("interaction") != event.interaction.model_dump(mode="json"):
        raise AdaptiveResearchLoopError(
            "adaptive event interaction differs from its raw transition payload"
        )
    transition = payload.get("transition")
    if not isinstance(transition, dict):
        raise AdaptiveResearchLoopError("adaptive event raw transition is absent")
    try:
        parsed_transition = _ActionTransition.model_validate(transition)
    except ValueError as exc:
        raise AdaptiveResearchLoopError(
            f"adaptive event raw transition violates its exact schema: {exc}"
        ) from exc
    if transition != parsed_transition.model_dump(mode="json"):
        raise AdaptiveResearchLoopError(
            "adaptive event raw transition differs from its canonical typed form"
        )
    expected_fields: dict[str, JsonValue] = {
        "feedback": event.feedback.model_dump(mode="json"),
        "zone_after": event.zone_after.value,
        "temporary_batch": (
            event.temporary_batch.model_dump(mode="json")
            if event.temporary_batch is not None
            else None
        ),
        "promotion_assessment": (
            event.promotion_assessment.model_dump(mode="json")
            if event.promotion_assessment is not None
            else None
        ),
        "formal_verification": (
            event.formal_verification.model_dump(mode="json")
            if event.formal_verification is not None
            else None
        ),
        "created_branch_id": event.created_branch_id,
        "strategy_note_cn": event.strategy_note_cn,
    }
    if any(transition.get(key) != value for key, value in expected_fields.items()):
        raise AdaptiveResearchLoopError(
            "adaptive event fields differ from their raw transition payload"
        )
    return parsed_transition


def _verify_snapshot_transition_replay(
    snapshot: AdaptiveResearchLoopSnapshot,
    transitions: Sequence[_ActionTransition],
    *,
    verified_skill_model_call_count: int,
) -> None:
    """Rebuild derived state from exact raw transitions and reject rebinding."""

    if len(transitions) != len(snapshot.events):
        raise AdaptiveResearchLoopError(
            "adaptive transition count differs from retained event count"
        )
    root = AdaptiveResearchBranch(
        branch_id="branch_root",
        created_step=0,
        title_cn="初始研究目标",
        working_hypothesis_cn="尚未形成假设，由系统在开放探索中自主提出。",
    )
    replay = AdaptiveResearchLoopSnapshot.create(
        seed=snapshot.seed,
        policy=snapshot.policy,
        zone=ResearchLoopZone.OPEN_EXPLORATION,
        status=AdaptiveLoopRunStatus.RUNNING,
        next_step_index=1,
        branches=[root],
        events=[],
        strategy_notes_cn=[],
        model_call_count=0,
        skill_routing_model_call_count=0,
        external_action_count=0,
        temporary_agent_count=0,
        consecutive_stalls=0,
    )
    for event, transition in zip(snapshot.events, transitions, strict=True):
        if (
            event.loop_id != replay.seed.loop_id
            or event.step_index != replay.next_step_index
            or event.zone_before is not replay.zone
        ):
            raise AdaptiveResearchLoopError(
                "adaptive event order or pre-transition zone cannot be replayed"
            )
        replay = _advance_snapshot(
            replay,
            event,
            transition,
            skill_model_call_increment=0,
            action_model_call_increment=len(event.interaction.model_call_registrations),
        )

    # Skill-routing calls are reserved outside the action transition.  The
    # supplied count was independently replayed from sovereign raw reservations;
    # no self-declared snapshot counter is admitted here.
    replay_payload = replay.model_dump(mode="json", exclude={"snapshot_hash"})
    replay_payload.update(
        {
            "skill_routing_model_call_count": verified_skill_model_call_count,
            "model_call_count": (replay.model_call_count + verified_skill_model_call_count),
        }
    )
    replay = AdaptiveResearchLoopSnapshot.create(**replay_payload)
    if snapshot.unresolved_model_call_count:
        replay = _block_snapshot_for_unresolved_model_calls(
            replay,
            unresolved_count=snapshot.unresolved_model_call_count,
        )
    elif snapshot.status is AdaptiveLoopRunStatus.PAUSED_BUDGET:
        if _budget_status(replay) is not AdaptiveLoopRunStatus.PAUSED_BUDGET:
            raise AdaptiveResearchLoopError(
                "adaptive snapshot claims a budget stop that replay cannot reach"
            )
        replay = _replace_snapshot(
            replay,
            status=AdaptiveLoopRunStatus.PAUSED_BUDGET,
            zone=ResearchLoopZone.TERMINAL,
        )
    if replay != snapshot:
        raise AdaptiveResearchLoopError("adaptive snapshot differs from full raw-transition replay")


def _validate_external_turn_contexts(
    contexts: Sequence[AdaptiveExternalTurnContext],
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    raw_memory_store: RawMemoryStore,
) -> None:
    if len(contexts) > 8:
        raise AdaptiveResearchLoopError(
            "adaptive loop accepts at most eight external contexts per turn"
        )
    context_ids = [context.context_id for context in contexts]
    context_hashes = [context.context_hash for context in contexts]
    if len(context_ids) != len(set(context_ids)):
        raise AdaptiveResearchLoopError("external turn context IDs must be unique")
    if len(context_hashes) != len(set(context_hashes)):
        raise AdaptiveResearchLoopError("external turn context hashes must be unique")
    expected_step = snapshot.next_step_index
    for context in contexts:
        _verify_external_turn_context_against_raw(
            context,
            seed=seed,
            expected_step=expected_step,
            raw_memory_store=raw_memory_store,
        )


def _verify_external_turn_context_against_raw(
    context: AdaptiveExternalTurnContext,
    *,
    seed: AdaptiveResearchSeed,
    expected_step: int,
    raw_memory_store: RawMemoryStore,
) -> None:
    """Replay one context from immutable raw bytes, not self-declared flags."""

    if context.loop_id != seed.loop_id or context.project_id != seed.project_id:
        raise AdaptiveResearchLoopError("external turn context belongs to another loop or project")
    if context.step_index != expected_step:
        raise AdaptiveResearchLoopError("external turn context belongs to another step")
    expected_ref = (
        f"adaptive-loop:{seed.loop_id}:step:{expected_step}:"
        f"external-context:{context.context_id}"
    )
    if context.source_ref != expected_ref:
        raise AdaptiveResearchLoopError("external turn context source reference is not canonical")
    try:
        capture = raw_memory_store.load_record(
            context.raw_binding.record_relative_path,
            project_id=seed.project_id,
        )
    except RawMemoryError as exc:
        raise AdaptiveResearchLoopError(
            f"external turn context raw-memory verification failed: {exc}"
        ) from exc
    if capture.binding(raw_memory_store.vault_root) != context.raw_binding:
        raise AdaptiveResearchLoopError("external turn context raw-memory binding mismatch")
    envelope = capture.record.envelope
    if (
        envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
        or envelope.source_ref != context.source_ref
    ):
        raise AdaptiveResearchLoopError("external turn context raw-memory provenance mismatch")
    try:
        raw_text = capture.blob_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AdaptiveResearchLoopError(
            f"external turn context must be exact UTF-8 text: {exc}"
        ) from exc
    if raw_text != context.content_cn:
        raise AdaptiveResearchLoopError("external turn context differs from its exact raw payload")


def _external_turn_context_message_payload(
    context: AdaptiveExternalTurnContext,
) -> dict[str, JsonValue]:
    return {
        "context_kind": "adaptive_external_turn_context",
        "context_id": context.context_id,
        "loop_id": context.loop_id,
        "project_id": context.project_id,
        "step_index": context.step_index,
        "source_ref": context.source_ref,
        "content_cn": context.content_cn,
        "content_sha256": context.content_sha256,
        "raw_binding": context.raw_binding.model_dump(mode="json"),
        "context_hash": context.context_hash,
        "use_boundary": (
            "这是环境在本轮给出的、已冻结且可追溯的外生观察；"
            "它不指定下一算子、不包含隐藏评分答案，也不是科学证据。"
        ),
    }


def _verify_external_turn_context_message_projection(
    messages: Sequence[dict[Literal["role", "content"], str]],
    contexts: Sequence[AdaptiveExternalTurnContext],
) -> None:
    actual: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("context_kind") == "adaptive_external_turn_context"
        ):
            actual.append(payload)
    expected = [_external_turn_context_message_payload(item) for item in contexts]
    if actual != expected:
        raise AdaptiveResearchLoopError(
            "external turn context messages differ from retained context objects"
        )


def _adaptive_action_task_payload(
    messages: Sequence[dict[Literal["role", "content"], str]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("context_kind") == "adaptive_research_next_action"
        ):
            candidates.append(payload)
    if len(candidates) != 1:
        raise AdaptiveResearchLoopError(
            "adaptive interaction must contain exactly one next-action task"
        )
    return candidates[0]


def _verify_memory_control_observation_message_projection(
    messages: Sequence[dict[Literal["role", "content"], str]],
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    event: AdaptiveLoopEvent,
    prior_events: Sequence[AdaptiveLoopEvent],
) -> None:
    task = _adaptive_action_task_payload(messages)
    selected_branch = task.get("selected_branch")
    available_operators = task.get("available_operators")
    field_contract = task.get("operator_field_contract")
    if (
        task.get("step_index") != event.step_index
        or task.get("loop_id") != snapshot.seed.loop_id
        or task.get("project_id") != snapshot.seed.project_id
        or task.get("objective_cn") != snapshot.seed.objective_cn
        or task.get("scope_cn") != snapshot.seed.scope_cn
        or not isinstance(selected_branch, dict)
        or selected_branch.get("branch_id") != event.branch_id
        or not isinstance(available_operators, dict)
        or not all(isinstance(key, str) for key in available_operators)
        or event.interaction.proposal.operator.value not in available_operators
        or not isinstance(field_contract, dict)
    ):
        raise AdaptiveResearchLoopError(
            "adaptive next-action task differs from its retained loop identity"
        )

    observation_payload = task.get("memory_control_observation")
    boundary = field_contract.get("memory_control_observation")
    prefix_strategy_notes = [
        prior_event.interaction.proposal.action_body_cn
        for prior_event in prior_events
        if prior_event.interaction.proposal.operator is ResearchOperator.MUTATE_WORKFLOW_PROPOSAL
    ]
    prefix_snapshot = snapshot.model_copy(
        update={
            "events": list(prior_events),
            "next_step_index": event.step_index,
            "strategy_notes_cn": prefix_strategy_notes,
        },
        deep=True,
    )
    if snapshot.policy.schema_version == "adaptive-sovereign-loop-policy-v1":
        if observation_payload is not None or boundary is not None:
            raise AdaptiveResearchLoopError(
                "legacy adaptive policy unexpectedly contains memory-control state"
            )
        if task.get("strategy_notes_cn") != prefix_strategy_notes:
            raise AdaptiveResearchLoopError(
                "legacy adaptive strategy-note prompt differs from retained history"
            )
        return

    if boundary != _MEMORY_CONTROL_USE_BOUNDARY_CN:
        raise AdaptiveResearchLoopError("adaptive memory-control use boundary mismatch")
    try:
        actual = AdaptiveMemoryControlObservation.model_validate(observation_payload)
    except ValueError as exc:
        raise AdaptiveResearchLoopError(
            f"adaptive memory-control observation is invalid: {exc}"
        ) from exc
    expected = build_adaptive_memory_control_observation(
        snapshot=prefix_snapshot,
        selected_branch_id=event.branch_id,
        available_operator_ids=list(available_operators),
    )
    if actual != expected:
        raise AdaptiveResearchLoopError(
            "adaptive memory-control observation differs from retained history"
        )
    if snapshot.policy.schema_version == "adaptive-sovereign-loop-policy-v2":
        if (
            task.get("strategy_notes_cn") != prefix_strategy_notes
            or task.get("workflow_proposal_history") is not None
            or task.get("memory_recall_capability_contract") is not None
        ):
            raise AdaptiveResearchLoopError(
                "adaptive v2 strategy-note prompt differs from retained history"
            )
        return

    if task.get("strategy_notes_cn") is not None:
        raise AdaptiveResearchLoopError("adaptive v3 prompt exposes unscoped legacy strategy notes")
    if field_contract.get("workflow_proposal_history") != (_WORKFLOW_PROPOSAL_HISTORY_BOUNDARY_CN):
        raise AdaptiveResearchLoopError("adaptive workflow proposal history boundary mismatch")
    if field_contract.get("memory_recall_capability_contract") != (
        _MEMORY_RECALL_CAPABILITY_BOUNDARY_CN
    ):
        raise AdaptiveResearchLoopError("adaptive memory-recall capability boundary mismatch")
    history_payload = task.get("workflow_proposal_history")
    if not isinstance(history_payload, list):
        raise AdaptiveResearchLoopError("adaptive workflow proposal history is absent")
    try:
        actual_history = tuple(
            AdaptiveWorkflowProposalContext.model_validate(item) for item in history_payload
        )
        actual_capability = AdaptiveMemoryRecallCapabilityContract.model_validate(
            task.get("memory_recall_capability_contract")
        )
    except ValueError as exc:
        raise AdaptiveResearchLoopError(
            f"adaptive temporally scoped memory context is invalid: {exc}"
        ) from exc
    if actual_history != build_adaptive_workflow_proposal_contexts(prefix_snapshot):
        raise AdaptiveResearchLoopError(
            "adaptive workflow proposal history differs from retained events"
        )
    if actual_capability != build_adaptive_memory_recall_capability_contract():
        raise AdaptiveResearchLoopError("adaptive memory-recall capability contract mismatch")


def _validate_resume_snapshot(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    raw_memory_store: RawMemoryStore,
) -> None:
    if snapshot.seed != seed:
        raise AdaptiveResearchLoopError("resume snapshot belongs to another seed")
    if snapshot.policy != policy:
        raise AdaptiveResearchLoopError("resume snapshot uses another loop policy")
    _verify_snapshot_raw_bindings(raw_memory_store, snapshot)


def _write_event_once(output_root: Path, event: AdaptiveLoopEvent) -> None:
    event_dir = output_root / "events"
    path = event_dir / f"step-{event.step_index:04d}-{event.event_hash}.json"
    _write_once(path, (canonical_json(event) + "\n").encode("utf-8"))


def _write_snapshot_once(
    output_root: Path,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> None:
    snapshot_dir = output_root / "snapshots"
    path = snapshot_dir / (f"step-{snapshot.next_step_index - 1:04d}-{snapshot.snapshot_hash}.json")
    _write_once(path, (canonical_json(snapshot) + "\n").encode("utf-8"))


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveResearchLoopError(
                f"immutable adaptive-loop artifact already exists with other bytes: {path}"
            ) from None


def _require_unique_skill_ids(skills: Sequence[LoopSkillContext]) -> None:
    ids = [skill.skill_id for skill in skills]
    if len(ids) != len(set(ids)):
        raise AdaptiveResearchLoopError("skill provider returned duplicate skill IDs")


def _no_skills(
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
) -> Sequence[LoopSkillContext]:
    del seed, snapshot, branch
    return ()


__all__ = [
    "AdaptiveActionModelCallRegistration",
    "AdaptiveActionModelAttempt",
    "AdaptiveExternalTurnContext",
    "AdaptiveLoopPolicy",
    "AdaptiveLoopRunStatus",
    "AdaptiveMemoryControlObservation",
    "AdaptiveMemoryRecallCapabilityContract",
    "AdaptiveResearchBranch",
    "AdaptiveResearchLoopError",
    "AdaptiveResearchLoopSnapshot",
    "AdaptiveResearchSeed",
    "AdaptiveWorkflowProposalContext",
    "ExternalResearchFeedback",
    "ExternalTurnContextProvider",
    "FeedbackOrigin",
    "FeedbackStatus",
    "FormalPromotionVerification",
    "LoopSkillContext",
    "ModelMemoryConsumptionClaim",
    "ModelMemoryExposure",
    "ModelResearchActionDraft",
    "OperatorCatalogProvider",
    "PromotionDraft",
    "PromotionGateAssessment",
    "ResearchActionEnvironment",
    "ResearchBranchStatus",
    "ResearchLoopZone",
    "ResearchOperator",
    "TemporaryAgentBatchOutcome",
    "TemporaryAgentContribution",
    "TemporaryResearchDispatcher",
    "TemporaryResearchTask",
    "assess_branch_promotion",
    "build_adaptive_memory_control_observation",
    "build_adaptive_memory_recall_capability_contract",
    "build_adaptive_research_messages",
    "build_adaptive_workflow_proposal_contexts",
    "create_adaptive_research_seed",
    "initialize_adaptive_research_loop",
    "load_adaptive_research_loop_snapshot",
    "run_adaptive_research_loop",
]
