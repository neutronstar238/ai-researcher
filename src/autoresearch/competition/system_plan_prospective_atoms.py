"""Literature-supported prospective single-component interventions.

The existing component-atom catalog records components observed in signed prior
candidate summaries.  Those records are useful baselines, but they cannot by
themselves express a new experiment.  This sibling module lets the current-stage
main Qwen propose one to three *prospective* interventions while keeping four
boundaries structural:

* papers are exact selected-survey records joined back to complete abstracts;
* target names are replaced by opaque keys in every model message;
* every proposal changes one observed baseline component under a frozen interface
  and resource request; and
* an independent Qwen compares every proposal with every selected abstract.

Accepted proposals remain unexecuted, non-evidence candidates.  In particular,
``innovation_verified`` is always false: abstract comparison can reject obvious
reuse, but it cannot prove publication-level novelty.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.plan_literature_survey import PlanLiteratureSurveyArtifact
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtomBinding,
)
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    EvidenceFact,
    ResearchFeasibilityEnvelope,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_OUTPUT_NAME = "system-plan-prospective-atoms.json"
_MAX_ATOMS = 3
_MAX_ROUNDS = 5
_MAX_AUTHOR_TRANSPORT_ATTEMPTS_PER_ROUND = 3
_MAX_REVIEWER_ATTEMPTS_PER_AUTHOR = 3
_MIN_REASONING_CHARACTERS = 1
_THINKING_BUDGET = 4_000
# Complete selected abstracts are scientific inputs and must not be silently
# truncated to satisfy an arbitrary 64 KiB application envelope.  Qwen's configured
# context window is substantially larger, so retain a bounded 96 KiB engineering
# envelope while continuing to fail closed for anomalously large surveys.
_DEFAULT_MAX_PROMPT_UTF8_BYTES = 98_304
_PUBLIC_HOOK_ORDER = ("fit_equations", "predict_derivative")
_REVIEW_GATE_LABELS = {
    "single_component_identifiable": "单组件可识别性未通过",
    "abstract_support_exact": "摘要支持未精确闭合",
    "facts_support_scope": "事实支持范围未闭合",
    "no_system_name_inference": "存在真实系统名推断",
    "target_type_valid": "目标数据类型不适用",
    "interface_valid": "公开接口不可执行",
    "budget_valid": "资源预算不可执行",
    "not_direct_prior_method_copy": "可能直接复制既有方法或摘要不足",
    "falsifiable_counterfactual": "缺少可反驳对照",
}
_FROZEN_DIMENSIONS = (
    "输入数据",
    "实验条件",
    "随机种子",
    "估计目标",
    "基线方法",
    "评估指标",
    "公开接口",
    "资源上限",
    "基线组件之外的候选行为",
)

PublicHook = Literal["fit_equations", "predict_derivative"]
DataType = Literal["ode", "pde"]
ChangeMode = Literal["替换", "消融", "参数化"]
AttemptStage = Literal["author", "reviewer"]
AttemptOutcome = Literal[
    "author_call_failed",
    "author_rejected",
    "author_forwarded",
    "reviewer_call_failed",
    "reviewer_rejected",
    "reviewer_declined",
    "reviewer_accepted",
]
FrozenDimension = Literal[
    "输入数据",
    "实验条件",
    "随机种子",
    "估计目标",
    "基线方法",
    "评估指标",
    "公开接口",
    "资源上限",
    "基线组件之外的候选行为",
]


class SystemPlanProspectiveAtomError(RuntimeError):
    """Raised when a prospective intervention cannot be proved from its inputs."""


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_utf8_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _contains_chinese_text(value: str) -> bool:
    return bool(value.strip()) and any("\u3400" <= character <= "\u9fff" for character in value)


class ProspectiveExecutionInterfaceContract(StrictFrozenModel):
    """Small local execution surface and its frozen per-cell ceilings."""

    schema_version: Literal["prospective-execution-interface-contract-v1"] = (
        "prospective-execution-interface-contract-v1"
    )
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)
    maximum_seconds_per_cell: int = Field(ge=1)
    maximum_memory_mb_per_cell: int = Field(ge=128)
    maximum_cpu_cores_per_cell: int = Field(ge=1)
    maximum_public_fit_calls_per_cell: int = Field(ge=1)
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_contract(self) -> ProspectiveExecutionInterfaceContract:
        expected_hooks = tuple(
            hook for hook in _PUBLIC_HOOK_ORDER if hook in set(self.public_hooks)
        )
        if self.public_hooks != expected_hooks:
            raise SystemPlanProspectiveAtomError("前瞻组件公开接口必须唯一并按固定顺序排列")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"contract_hash"})
        )
        if self.contract_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("前瞻组件执行接口合同哈希不符")
        return self


def build_prospective_execution_interface_contract(
    feasibility_envelope: ResearchFeasibilityEnvelope,
    *,
    public_hooks: Sequence[PublicHook] = (
        "fit_equations",
        "predict_derivative",
    ),
    maximum_public_fit_calls_per_cell: int = 1,
) -> ProspectiveExecutionInterfaceContract:
    """Bind the narrow public hooks to the envelope's official-cell budget."""

    official = feasibility_envelope.execution_semantics.get("official_development_cell_budget")
    if not isinstance(official, Mapping):
        raise SystemPlanProspectiveAtomError("可行性边界缺少正式开发单元预算")
    required = (
        "maximum_seconds_per_cell",
        "maximum_memory_mb_per_cell",
        "maximum_cpu_cores_per_cell",
    )
    values: dict[str, int] = {}
    for field_name in required:
        value = official.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SystemPlanProspectiveAtomError(f"正式开发单元预算字段无效：{field_name}")
        values[field_name] = value
    payload: dict[str, Any] = {
        "schema_version": "prospective-execution-interface-contract-v1",
        "public_hooks": list(public_hooks),
        **values,
        "maximum_public_fit_calls_per_cell": maximum_public_fit_calls_per_cell,
    }
    payload["contract_hash"] = canonical_model_hash(payload)
    return ProspectiveExecutionInterfaceContract.model_validate(payload)


class SelectedAbstractEvidence(StrictFrozenModel):
    """One selected reference joined to its complete retrieved abstract."""

    reference_index: int = Field(ge=1)
    retrieval_index: int = Field(ge=0)
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    abstract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    abstract_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_abstract(self) -> SelectedAbstractEvidence:
        if not self.abstract_text.strip():
            raise SystemPlanProspectiveAtomError("入选文献完整摘要不得为空白")
        if self.abstract_sha256 != _text_sha256(self.abstract_text):
            raise SystemPlanProspectiveAtomError("入选文献完整摘要哈希不符")
        return self


class ProspectiveTargetAliasBinding(StrictFrozenModel):
    """Private deterministic mapping; never serialized into a model message."""

    target_key: str = Field(pattern=r"^T[0-9]{3}$")
    system_name: str = Field(min_length=1)
    data_type: DataType
    required_fact_ids: tuple[str, ...] = Field(min_length=4)


class AnonymousTargetEvidence(StrictFrozenModel):
    """System-name-free target ledger exposed to Qwen."""

    target_key: str = Field(pattern=r"^T[0-9]{3}$")
    data_type: DataType
    required_fact_ids: tuple[str, ...] = Field(min_length=4)


class AnonymousEvidenceFact(StrictFrozenModel):
    """Hash-bound fact projection with every real system name replaced by an alias."""

    fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    fact_kind: str = Field(min_length=1)
    full_fact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    anonymized_value: Any


class ProspectiveAtomContext(StrictFrozenModel):
    """Exact model-facing context; it deliberately contains no titles or system names."""

    schema_version: Literal["prospective-atom-context-v1"] = "prospective-atom-context-v1"
    survey_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_references_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_component_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_skill_selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    interface_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_alias_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_abstracts: tuple[SelectedAbstractEvidence, ...] = Field(min_length=3)
    anonymous_targets: tuple[AnonymousTargetEvidence, ...] = Field(min_length=3)
    evidence_facts: tuple[AnonymousEvidenceFact, ...] = Field(min_length=4)
    interface_contract: ProspectiveExecutionInterfaceContract
    maximum_prompt_utf8_bytes: int = Field(ge=1)
    context_payload_utf8_bytes: int = Field(ge=1)
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_context(self) -> ProspectiveAtomContext:
        if self.interface_contract.contract_hash != self.interface_contract_hash:
            raise SystemPlanProspectiveAtomError("匿名上下文的执行接口合同不一致")
        reference_indices = tuple(item.reference_index for item in self.selected_abstracts)
        if reference_indices != tuple(range(1, len(reference_indices) + 1)):
            raise SystemPlanProspectiveAtomError("匿名上下文文献编号必须从一连续递增")
        retrieval_indices = tuple(item.retrieval_index for item in self.selected_abstracts)
        if len(set(retrieval_indices)) != len(retrieval_indices):
            raise SystemPlanProspectiveAtomError("匿名上下文检索编号不得重复")
        target_keys = tuple(item.target_key for item in self.anonymous_targets)
        expected_keys = tuple(f"T{index:03d}" for index in range(1, len(target_keys) + 1))
        if target_keys != expected_keys:
            raise SystemPlanProspectiveAtomError("匿名目标编号必须从 T001 连续递增")
        fact_ids = tuple(item.fact_id for item in self.evidence_facts)
        if len(set(fact_ids)) != len(fact_ids):
            raise SystemPlanProspectiveAtomError("匿名事实编号不得重复")
        unknown = sorted(
            {
                fact_id
                for target in self.anonymous_targets
                for fact_id in target.required_fact_ids
                if fact_id not in set(fact_ids)
            }
        )
        if unknown:
            raise SystemPlanProspectiveAtomError(f"匿名目标引用了未投影事实：{unknown}")
        base = self.model_dump(mode="json", exclude={"context_payload_utf8_bytes", "context_hash"})
        actual_size = _json_utf8_size(base)
        if self.context_payload_utf8_bytes != actual_size:
            raise SystemPlanProspectiveAtomError("匿名上下文 UTF-8 字节数不符")
        if actual_size > self.maximum_prompt_utf8_bytes:
            raise SystemPlanProspectiveAtomError("匿名上下文超过提示大小上限，拒绝静默截断")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"context_hash"}))
        if self.context_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("匿名前瞻组件上下文哈希不符")
        return self


class ProspectiveLiteratureSupport(StrictFrozenModel):
    """An exact abstract span used by one prospective proposal."""

    reference_index: int = Field(ge=1)
    retrieval_index: int = Field(ge=0)
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    abstract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_support_span: str = Field(min_length=8, max_length=800)
    support_span_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    support_role: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _validate_span_hash(self) -> ProspectiveLiteratureSupport:
        if self.exact_support_span != self.exact_support_span.strip():
            raise SystemPlanProspectiveAtomError("摘要支持片段不得含首尾空白")
        if self.support_span_sha256 != _text_sha256(self.exact_support_span):
            raise SystemPlanProspectiveAtomError("摘要支持片段哈希不符")
        if self.support_role != self.support_role.strip():
            raise SystemPlanProspectiveAtomError("摘要支持作用不得含首尾空白")
        if not _contains_chinese_text(self.support_role) or non_chinese_prose_fields(
            {"support_role": self.support_role}
        ):
            raise SystemPlanProspectiveAtomError("摘要支持作用应使用中文自然表述")
        return self


class ProspectiveResourceRequest(StrictFrozenModel):
    """Structured, mechanically bounded request; it is not a measured runtime."""

    seconds_per_cell: int = Field(ge=1)
    memory_mb_per_cell: int = Field(ge=128)
    cpu_cores_per_cell: int = Field(ge=1)
    public_fit_calls_per_cell: int = Field(ge=1)


class ProspectiveComponentAtom(StrictFrozenModel):
    """One Qwen-authored treatment/control proposal for one observed component."""

    atom_id: str = Field(pattern=r"^P00[1-3]$")
    origin_kind: Literal["prospective_literature_derived"] = "prospective_literature_derived"
    baseline_observed_atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    baseline_observed_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_zh: str = Field(min_length=2, max_length=100)
    change_mode: ChangeMode
    control_level_zh: str = Field(min_length=1, max_length=800)
    intervention_level_zh: str = Field(min_length=1, max_length=800)
    single_factor_rationale_zh: str = Field(min_length=1, max_length=1_200)
    literature_synthesis_zh: str = Field(min_length=1, max_length=1_200)
    delta_from_prior_work_zh: str = Field(min_length=1, max_length=1_200)
    falsifiable_single_factor_contrast_zh: str = Field(min_length=1, max_length=1_200)
    implementation_anchor: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)
    # Five targets is still a bounded cross-system probe and avoids forcing Qwen to
    # discard a scientifically coherent fifth system merely to satisfy an arbitrary
    # formatting cap.  Later pilot/full budgets remain independently frozen.
    target_keys: tuple[str, ...] = Field(min_length=3, max_length=5)
    applicable_data_types: tuple[DataType, ...] = Field(min_length=1, max_length=2)
    supporting_fact_ids: tuple[str, ...] = Field(min_length=8)
    # One exact source is sufficient to motivate a candidate because the independent
    # reviewer below still compares that candidate against *every* selected abstract.
    # Requiring two here made Qwen pad duplicate citations and added no novelty proof.
    literature_supports: tuple[ProspectiveLiteratureSupport, ...] = Field(
        min_length=1, max_length=3
    )
    frozen_dimensions: tuple[FrozenDimension, ...] = Field(
        min_length=len(_FROZEN_DIMENSIONS), max_length=len(_FROZEN_DIMENSIONS)
    )
    resource_request: ProspectiveResourceRequest
    single_factor_intervention: Literal[True] = True
    candidate_differences_jointly_confounded: Literal[True] = True
    is_scientific_evidence: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_atom_shape(self) -> ProspectiveComponentAtom:
        for label, values in (
            ("公开接口", self.public_hooks),
            ("匿名目标", self.target_keys),
            ("适用类型", self.applicable_data_types),
            ("支持事实", self.supporting_fact_ids),
            (
                "支持文献",
                tuple(item.reference_index for item in self.literature_supports),
            ),
        ):
            if len(set(values)) != len(values):
                raise SystemPlanProspectiveAtomError(f"{self.atom_id} 的{label}不得重复")
        expected_hooks = tuple(
            hook for hook in _PUBLIC_HOOK_ORDER if hook in set(self.public_hooks)
        )
        if self.public_hooks != expected_hooks:
            raise SystemPlanProspectiveAtomError(f"{self.atom_id} 的公开接口顺序不稳定")
        if tuple(sorted(self.applicable_data_types)) != self.applicable_data_types:
            raise SystemPlanProspectiveAtomError(f"{self.atom_id} 的适用类型必须按 ode、pde 排序")
        if self.frozen_dimensions != _FROZEN_DIMENSIONS:
            raise SystemPlanProspectiveAtomError(f"{self.atom_id} 未冻结单因子实验的全部其余维度")
        label_language_failures = non_chinese_prose_fields(
            {"label_zh": self.label_zh},
            minimum_ratio=0.30,
            exempt_identifiers=(
                self.baseline_observed_atom_id,
                self.implementation_anchor,
                *self.public_hooks,
            ),
        )
        language_failures = non_chinese_prose_fields(
            {
                "control_level_zh": self.control_level_zh,
                "intervention_level_zh": self.intervention_level_zh,
                "single_factor_rationale_zh": self.single_factor_rationale_zh,
                "literature_synthesis_zh": self.literature_synthesis_zh,
                "delta_from_prior_work_zh": self.delta_from_prior_work_zh,
                "falsifiable_single_factor_contrast_zh": (
                    self.falsifiable_single_factor_contrast_zh
                ),
            },
            exempt_identifiers=(
                self.baseline_observed_atom_id,
                self.implementation_anchor,
                *self.public_hooks,
            ),
        )
        if label_language_failures or language_failures:
            raise SystemPlanProspectiveAtomError(
                f"{self.atom_id} 的前瞻组件散文不是中文："
                f"{list(label_language_failures + language_failures)}"
            )
        required_prose = {
            "label_zh": self.label_zh,
            "control_level_zh": self.control_level_zh,
            "intervention_level_zh": self.intervention_level_zh,
            "single_factor_rationale_zh": self.single_factor_rationale_zh,
            "literature_synthesis_zh": self.literature_synthesis_zh,
            "delta_from_prior_work_zh": self.delta_from_prior_work_zh,
            "falsifiable_single_factor_contrast_zh": (self.falsifiable_single_factor_contrast_zh),
        }
        missing = tuple(
            field_name
            for field_name, value in required_prose.items()
            if not _contains_chinese_text(value)
        )
        if missing:
            raise SystemPlanProspectiveAtomError(
                f"{self.atom_id} 的前瞻组件散文缺少有效中文：{list(missing)}"
            )
        return self


class ProspectiveAtomPortfolio(StrictFrozenModel):
    """One to three proposals; variable cardinality prevents low-quality padding."""

    schema_version: Literal["prospective-atom-portfolio-v1"] = "prospective-atom-portfolio-v1"
    atoms: tuple[ProspectiveComponentAtom, ...] = Field(min_length=1, max_length=_MAX_ATOMS)

    @model_validator(mode="after")
    def _validate_portfolio(self) -> ProspectiveAtomPortfolio:
        expected_ids = tuple(f"P{index:03d}" for index in range(1, len(self.atoms) + 1))
        if tuple(item.atom_id for item in self.atoms) != expected_ids:
            raise SystemPlanProspectiveAtomError("前瞻组件编号必须从 P001 连续递增")
        return self


class ProspectivePriorWorkComparison(StrictFrozenModel):
    """Independent comparison against one complete selected abstract."""

    reference_index: int = Field(ge=1)
    abstract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    overlap_zh: str = Field(min_length=1, max_length=800)
    difference_zh: str = Field(min_length=1, max_length=800)
    residual_risk_zh: str = Field(min_length=1, max_length=800)
    direct_method_copy: bool
    abstract_insufficient: bool

    @model_validator(mode="after")
    def _validate_language(self) -> ProspectivePriorWorkComparison:
        failures = non_chinese_prose_fields(
            {
                "overlap_zh": self.overlap_zh,
                "difference_zh": self.difference_zh,
                "residual_risk_zh": self.residual_risk_zh,
            }
        )
        if failures:
            raise SystemPlanProspectiveAtomError(f"前瞻组件文献比较不是中文：{list(failures)}")
        values = {
            "overlap_zh": self.overlap_zh,
            "difference_zh": self.difference_zh,
            "residual_risk_zh": self.residual_risk_zh,
        }
        missing = tuple(
            field_name for field_name, value in values.items() if not _contains_chinese_text(value)
        )
        if missing:
            raise SystemPlanProspectiveAtomError(f"前瞻组件文献比较缺少有效中文：{list(missing)}")
        return self


class ProspectiveAtomReview(StrictFrozenModel):
    """Independent all-gates verdict bound to one exact proposal hash."""

    atom_id: str = Field(pattern=r"^P00[1-3]$")
    atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_work_comparisons: tuple[ProspectivePriorWorkComparison, ...] = Field(min_length=1)
    single_component_identifiable: bool
    abstract_support_exact: bool
    facts_support_scope: bool
    no_system_name_inference: bool
    target_type_valid: bool
    interface_valid: bool
    budget_valid: bool
    not_direct_prior_method_copy: bool
    falsifiable_counterfactual: bool
    accepted: bool
    findings_zh: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_review(self) -> ProspectiveAtomReview:
        comparisons_clear = all(
            not item.direct_method_copy and not item.abstract_insufficient
            for item in self.prior_work_comparisons
        )
        if self.not_direct_prior_method_copy != comparisons_clear:
            raise SystemPlanProspectiveAtomError(f"{self.atom_id} 的既有方法排除门与逐篇比较矛盾")
        gates = (
            self.single_component_identifiable,
            self.abstract_support_exact,
            self.facts_support_scope,
            self.no_system_name_inference,
            self.target_type_valid,
            self.interface_valid,
            self.budget_valid,
            self.not_direct_prior_method_copy,
            self.falsifiable_counterfactual,
        )
        if self.accepted != all(gates):
            raise SystemPlanProspectiveAtomError(
                f"{self.atom_id} 的 accepted 必须是全部硬门的机械合取"
            )
        failures = non_chinese_prose_fields({"findings_zh": self.findings_zh})
        if failures:
            raise SystemPlanProspectiveAtomError(
                f"{self.atom_id} 的审查 findings 不是中文：{list(failures)}"
            )
        return self


class ProspectiveAtomReviewPortfolio(StrictFrozenModel):
    """Independent reviewer output; exact coverage is checked separately."""

    schema_version: Literal["prospective-atom-review-portfolio-v1"] = (
        "prospective-atom-review-portfolio-v1"
    )
    reviews: tuple[ProspectiveAtomReview, ...] = Field(min_length=1, max_length=_MAX_ATOMS)


class ProspectiveAtomRound(StrictFrozenModel):
    """One complete author/reviewer transaction pair."""

    round_index: int = Field(ge=1, le=_MAX_ROUNDS)
    author_feedback_zh: tuple[str, ...]
    author_portfolio: ProspectiveAtomPortfolio
    author_receipt: ModelAuthorshipReceipt
    author_receipt_relative_path: str = Field(min_length=1)
    reviewer_attempt_index: int = Field(ge=1, le=_MAX_REVIEWER_ATTEMPTS_PER_AUTHOR)
    reviewer_feedback_zh: tuple[str, ...]
    review_portfolio: ProspectiveAtomReviewPortfolio
    reviewer_receipt: ModelAuthorshipReceipt
    reviewer_receipt_relative_path: str = Field(min_length=1)
    accepted: bool
    round_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_round(self) -> ProspectiveAtomRound:
        if self.accepted != all(item.accepted for item in self.review_portfolio.reviews):
            raise SystemPlanProspectiveAtomError("前瞻组件轮次接受状态与逐项审查不一致")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"round_hash"}))
        if self.round_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("前瞻组件轮次哈希不符")
        return self


class ProspectiveModelAttempt(StrictFrozenModel):
    """One invoked author/reviewer call, including failures omitted from rounds."""

    schema_version: Literal["prospective-model-attempt-v1"] = "prospective-model-attempt-v1"
    stage: AttemptStage
    round_index: int = Field(ge=1, le=_MAX_ROUNDS)
    stage_attempt_index: int = Field(ge=1, le=_MAX_REVIEWER_ATTEMPTS_PER_AUTHOR)
    input_feedback_zh: tuple[str, ...]
    messages_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: AttemptOutcome
    failure_summary_zh: tuple[str, ...]
    receipt: ModelAuthorshipReceipt | None
    receipt_relative_path: str | None
    receipt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    no_progress_fuse_triggered: bool = False
    attempt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_attempt(self) -> ProspectiveModelAttempt:
        is_call_failure = self.outcome in {
            "author_call_failed",
            "reviewer_call_failed",
        }
        receipt_fields_absent = (
            self.receipt is None
            and self.receipt_relative_path is None
            and self.receipt_hash is None
        )
        receipt_fields_present = (
            self.receipt is not None
            and self.receipt_relative_path is not None
            and self.receipt_hash is not None
        )
        if is_call_failure != receipt_fields_absent or (
            not is_call_failure and not receipt_fields_present
        ):
            raise SystemPlanProspectiveAtomError(
                "调用失败不得伪造回执，已返回响应的尝试必须绑定完整回执"
            )
        if self.receipt is not None and self.receipt_hash != self.receipt.receipt_hash:
            raise SystemPlanProspectiveAtomError("前瞻模型尝试的回执哈希不符")
        if self.stage == "author" and not self.outcome.startswith("author_"):
            raise SystemPlanProspectiveAtomError("作者尝试混入审查者结果")
        if (
            self.stage == "author"
            and self.stage_attempt_index > _MAX_AUTHOR_TRANSPORT_ATTEMPTS_PER_ROUND
        ):
            raise SystemPlanProspectiveAtomError("每轮作者传输重试超过冻结上限")
        if self.stage == "reviewer" and not self.outcome.startswith("reviewer_"):
            raise SystemPlanProspectiveAtomError("审查者尝试混入作者结果")
        requires_failure = self.outcome not in {
            "author_forwarded",
            "reviewer_accepted",
        }
        if requires_failure != bool(self.failure_summary_zh):
            raise SystemPlanProspectiveAtomError("前瞻模型尝试的失败摘要与结果矛盾")
        if self.no_progress_fuse_triggered and self.outcome in {
            "author_forwarded",
            "reviewer_accepted",
        }:
            raise SystemPlanProspectiveAtomError("有进展的模型尝试不得标记熔断")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"attempt_hash"}))
        if self.attempt_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("前瞻模型尝试哈希不符")
        return self


class ProspectiveInterventionIdentity(StrictFrozenModel):
    """Direct plan-to-code identity; the hash is exactly the full atom hash."""

    atom_id: str = Field(pattern=r"^P00[1-3]$")
    origin_kind: Literal["prospective_literature_derived"] = "prospective_literature_derived"
    intervention_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_observed_atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    baseline_observed_atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_anchor: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
    public_hooks: tuple[PublicHook, ...] = Field(min_length=1, max_length=2)


class ProspectiveAtomBinding(StrictFrozenModel):
    """Minimal future routing input; still non-evidence and execution-disabled."""

    schema_version: Literal["prospective-atom-binding-v1"] = "prospective-atom-binding-v1"
    prospective_atom_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    survey_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_component_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_skill_selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    interface_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_aliases: tuple[ProspectiveTargetAliasBinding, ...] = Field(min_length=3)
    atoms: tuple[ProspectiveComponentAtom, ...] = Field(min_length=1, max_length=3)
    intervention_identities: tuple[ProspectiveInterventionIdentity, ...] = Field(
        min_length=1, max_length=3
    )
    independent_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_scientific_evidence: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> ProspectiveAtomBinding:
        expected_identities = tuple(
            ProspectiveInterventionIdentity(
                atom_id=atom.atom_id,
                origin_kind=atom.origin_kind,
                intervention_hash=canonical_model_hash(atom),
                baseline_observed_atom_id=atom.baseline_observed_atom_id,
                baseline_observed_atom_hash=atom.baseline_observed_atom_hash,
                implementation_anchor=atom.implementation_anchor,
                public_hooks=atom.public_hooks,
            )
            for atom in self.atoms
        )
        if self.intervention_identities != expected_identities:
            raise SystemPlanProspectiveAtomError("前瞻组件干预身份必须是完整 atom 的规范哈希投影")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("前瞻组件绑定哈希不符")
        return self


class ComponentExperimentBindingV2(StrictFrozenModel):
    """Explicit observed/prospective distinction for a later routing upgrade."""

    schema_version: Literal["component-experiment-binding-v2"] = "component-experiment-binding-v2"
    observed_components: SystemPlanComponentAtomBinding
    prospective_components: ProspectiveAtomBinding
    is_scientific_evidence: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> ComponentExperimentBindingV2:
        if (
            self.prospective_components.observed_component_binding_hash
            != self.observed_components.binding_hash
        ):
            raise SystemPlanProspectiveAtomError("前瞻组件没有绑定同一 observed baseline 目录")
        if (
            self.prospective_components.method_skill_selection_artifact_hash
            != self.observed_components.method_skill_selection_artifact_hash
        ):
            raise SystemPlanProspectiveAtomError(
                "observed/prospective 组件没有绑定同一方法技能选择"
            )
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("组件实验联合绑定哈希不符")
        return self


class SystemPlanProspectiveAtomArtifact(StrictFrozenModel):
    """Complete source objects, model receipts, strict review, and safety bounds."""

    schema_version: Literal["system-plan-prospective-atom-artifact-v1"] = (
        "system-plan-prospective-atom-artifact-v1"
    )
    lineage_id: str = Field(min_length=1)
    literature_survey: PlanLiteratureSurveyArtifact
    feasibility_envelope: ResearchFeasibilityEnvelope
    observed_component_binding: SystemPlanComponentAtomBinding
    method_skill_selection: SystemPlanMethodSkillSelectionBinding
    interface_contract: ProspectiveExecutionInterfaceContract
    target_aliases: tuple[ProspectiveTargetAliasBinding, ...] = Field(min_length=3)
    context: ProspectiveAtomContext
    attempt_manifest: tuple[ProspectiveModelAttempt, ...] = Field(
        min_length=2,
        max_length=(1 + _MAX_REVIEWER_ATTEMPTS_PER_AUTHOR) * _MAX_ROUNDS,
    )
    attempt_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rounds: tuple[ProspectiveAtomRound, ...] = Field(min_length=1, max_length=3)
    final_portfolio: ProspectiveAtomPortfolio
    final_review: ProspectiveAtomReviewPortfolio
    authored_by_main_qwen: Literal[True] = True
    independently_reviewed_by_qwen: Literal[True] = True
    reasoning_required: Literal[True] = True
    reasoning_is_evidence: Literal[False] = False
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    approval_granted: Literal[False] = False
    release_authorized: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanProspectiveAtomArtifact:
        expected_context, expected_aliases = _build_context_and_aliases(
            survey=self.literature_survey,
            feasibility_envelope=self.feasibility_envelope,
            observed_component_binding=self.observed_component_binding,
            method_skill_selection=self.method_skill_selection,
            interface_contract=self.interface_contract,
            maximum_prompt_utf8_bytes=self.context.maximum_prompt_utf8_bytes,
        )
        if self.context != expected_context or self.target_aliases != expected_aliases:
            raise SystemPlanProspectiveAtomError("前瞻组件上下文或匿名映射不是源制品的确定性投影")
        output_root = Path(self.output_path).resolve().parent
        expected_attempt_manifest_hash = canonical_model_hash(
            {"attempt_manifest": [item.model_dump(mode="json") for item in self.attempt_manifest]}
        )
        if self.attempt_manifest_hash != expected_attempt_manifest_hash:
            raise SystemPlanProspectiveAtomError("前瞻模型尝试清单哈希不符")
        _validate_attempt_manifest(self, output_root=output_root)
        for item in self.rounds:
            author_messages = _author_messages(
                context=self.context,
                observed_component_binding=self.observed_component_binding,
                method_skill_selection=self.method_skill_selection,
                target_aliases=self.target_aliases,
                literature_survey=self.literature_survey,
                prior_feedback=item.author_feedback_zh,
            )
            _validate_receipt_provenance(
                item.author_receipt,
                artifact_kind="plan_opportunity_map",
                interaction_id=f"system-plan-prospective-atoms-author-{item.round_index:02d}",
                attempt=item.round_index,
                messages=author_messages,
            )
            if _derive_author_support_bindings(
                item.author_receipt.parsed_payload,
                context=self.context,
                observed_component_binding=self.observed_component_binding,
            ) != item.author_portfolio.model_dump(mode="json"):
                raise SystemPlanProspectiveAtomError(
                    "前瞻组件作者回执不能机械投影为已持久化 portfolio"
                )
            _validate_persisted_receipt(
                output_root, item.author_receipt_relative_path, item.author_receipt
            )
            author_findings = prospective_atom_portfolio_findings(
                portfolio=item.author_portfolio,
                context=self.context,
                target_aliases=self.target_aliases,
                observed_component_binding=self.observed_component_binding,
                literature_survey=self.literature_survey,
            )
            if author_findings:
                raise SystemPlanProspectiveAtomError(
                    "已持久化前瞻组件未通过机械门：" + "；".join(author_findings)
                )
            reviewer_messages = _reviewer_messages(
                context=self.context,
                portfolio=item.author_portfolio,
                method_skill_selection=self.method_skill_selection,
                prior_feedback=item.reviewer_feedback_zh,
            )
            _validate_receipt_provenance(
                item.reviewer_receipt,
                artifact_kind="plan_opportunity_map_review",
                interaction_id=(
                    f"system-plan-prospective-atoms-reviewer-{item.round_index:02d}"
                    f"-{item.reviewer_attempt_index:02d}"
                ),
                attempt=item.reviewer_attempt_index,
                messages=reviewer_messages,
            )
            if _derive_reviewer_bindings(
                item.reviewer_receipt.parsed_payload,
                portfolio=item.author_portfolio,
                context=self.context,
            ) != item.review_portfolio.model_dump(mode="json"):
                raise SystemPlanProspectiveAtomError(
                    "前瞻组件审查回执不能机械投影为已持久化 review"
                )
            _validate_persisted_receipt(
                output_root, item.reviewer_receipt_relative_path, item.reviewer_receipt
            )
            if item.author_receipt.receipt_hash == item.reviewer_receipt.receipt_hash:
                raise SystemPlanProspectiveAtomError("前瞻组件作者与审查者不得共用回执")
            review_findings = prospective_atom_review_findings(
                review=item.review_portfolio,
                portfolio=item.author_portfolio,
                context=self.context,
            )
            if review_findings:
                raise SystemPlanProspectiveAtomError(
                    "前瞻组件审查未精确覆盖作者输出：" + "；".join(review_findings)
                )
        if any(item.accepted for item in self.rounds[:-1]):
            raise SystemPlanProspectiveAtomError("前瞻组件通过后不得继续改写")
        last = self.rounds[-1]
        if (
            not last.accepted
            or self.final_portfolio != last.author_portfolio
            or self.final_review != last.review_portfolio
        ):
            raise SystemPlanProspectiveAtomError("最终前瞻组件不是最后通过轮次的原文")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_hash:
            raise SystemPlanProspectiveAtomError("前瞻组件制品哈希不符")
        return self

    def binding(self) -> ProspectiveAtomBinding:
        payload: dict[str, Any] = {
            "schema_version": "prospective-atom-binding-v1",
            "prospective_atom_artifact_hash": self.artifact_hash,
            "survey_hash": self.literature_survey.survey_hash,
            "feasibility_envelope_hash": self.feasibility_envelope.envelope_hash,
            "observed_component_binding_hash": (self.observed_component_binding.binding_hash),
            "method_skill_selection_artifact_hash": (
                self.method_skill_selection.selection_artifact_hash
            ),
            "interface_contract_hash": self.interface_contract.contract_hash,
            "context_hash": self.context.context_hash,
            "target_aliases": [item.model_dump(mode="json") for item in self.target_aliases],
            "atoms": [item.model_dump(mode="json") for item in self.final_portfolio.atoms],
            "intervention_identities": [
                ProspectiveInterventionIdentity(
                    atom_id=item.atom_id,
                    origin_kind=item.origin_kind,
                    intervention_hash=canonical_model_hash(item),
                    baseline_observed_atom_id=item.baseline_observed_atom_id,
                    baseline_observed_atom_hash=item.baseline_observed_atom_hash,
                    implementation_anchor=item.implementation_anchor,
                    public_hooks=item.public_hooks,
                ).model_dump(mode="json")
                for item in self.final_portfolio.atoms
            ],
            "independent_review_hash": canonical_model_hash(self.final_review),
            "is_scientific_evidence": False,
            "innovation_verified": False,
            "execution_authorized": False,
        }
        payload["binding_hash"] = canonical_model_hash(payload)
        return ProspectiveAtomBinding.model_validate(payload)


def build_component_experiment_binding(
    observed_components: SystemPlanComponentAtomBinding,
    prospective_components: ProspectiveAtomBinding,
) -> ComponentExperimentBindingV2:
    """Join the two explicitly different atom classes without rewriting either."""

    payload: dict[str, Any] = {
        "schema_version": "component-experiment-binding-v2",
        "observed_components": observed_components.model_dump(mode="json"),
        "prospective_components": prospective_components.model_dump(mode="json"),
        "is_scientific_evidence": False,
        "innovation_verified": False,
        "execution_authorized": False,
    }
    payload["binding_hash"] = canonical_model_hash(payload)
    return ComponentExperimentBindingV2.model_validate(payload)


def _selected_references_hash(
    selected_references: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_model_hash(
        {"selected_references": [dict(item) for item in selected_references]}
    )


def _validate_method_skill_binding(
    binding: SystemPlanMethodSkillSelectionBinding,
) -> None:
    if not binding.selected_skills:
        raise SystemPlanProspectiveAtomError("前瞻组件缺少独立项目方法技能")
    for skill in binding.selected_skills:
        if _text_sha256(skill.content) != skill.content_sha256:
            raise SystemPlanProspectiveAtomError(f"前瞻组件方法技能内容哈希不符：{skill.skill_id}")


def _method_skill_context_message(
    binding: SystemPlanMethodSkillSelectionBinding,
) -> dict[str, str]:
    _validate_method_skill_binding(binding)
    return {
        "role": "user",
        "content": json.dumps(
            {
                "context_kind": "selected_project_method_skills",
                "selection_artifact_hash": binding.selection_artifact_hash,
                "system_authored_skill_selection": binding.selection.model_dump(mode="json"),
                "selected_method_skills": [
                    item.model_dump(mode="json") for item in binding.selected_skills
                ],
                "use_boundary": ("技能只约束原子化与审查方法，不是事实、科研结论或实验结果。"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def _selected_abstracts(
    survey: PlanLiteratureSurveyArtifact,
) -> tuple[SelectedAbstractEvidence, ...]:
    catalog_by_index: dict[int, Mapping[str, Any]] = {}
    for expected_index, raw in enumerate(survey.retrieved_catalog):
        retrieval_index = raw.get("retrieval_index")
        if (
            isinstance(retrieval_index, bool)
            or not isinstance(retrieval_index, int)
            or retrieval_index != expected_index
            or retrieval_index in catalog_by_index
        ):
            raise SystemPlanProspectiveAtomError(
                "真实文献目录 retrieval_index 必须从零连续、唯一且稳定"
            )
        catalog_by_index[retrieval_index] = raw
    records: list[SelectedAbstractEvidence] = []
    seen: set[int] = set()
    for reference_index, selected in enumerate(survey.selected_references, 1):
        retrieval_index = selected.get("retrieval_index")
        if (
            isinstance(retrieval_index, bool)
            or not isinstance(retrieval_index, int)
            or retrieval_index in seen
        ):
            raise SystemPlanProspectiveAtomError("入选文献检索编号无效或重复")
        seen.add(retrieval_index)
        source = catalog_by_index.get(retrieval_index)
        if source is None:
            raise SystemPlanProspectiveAtomError("入选文献不在完整真实检索目录中")
        for field_name in ("title", "doi", "url"):
            if selected.get(field_name) != source.get(field_name):
                raise SystemPlanProspectiveAtomError(
                    f"入选文献 {retrieval_index} 的 {field_name} 与目录不符"
                )
        abstract = source.get("abstract")
        if not isinstance(abstract, str) or not abstract.strip():
            raise SystemPlanProspectiveAtomError(f"入选文献 {retrieval_index} 缺少完整真实摘要")
        records.append(
            SelectedAbstractEvidence(
                reference_index=reference_index,
                retrieval_index=retrieval_index,
                source_record_hash=canonical_model_hash(dict(source)),
                abstract_sha256=_text_sha256(abstract),
                abstract_text=abstract,
            )
        )
    if len(records) < 3:
        raise SystemPlanProspectiveAtomError("前瞻组件要求至少三篇真实入选文献")
    return tuple(records)


def _fact_mapping(fact: EvidenceFact) -> dict[str, Any]:
    return dict(fact.value) if isinstance(fact.value, Mapping) else {}


def _target_alias_bindings(
    envelope: ResearchFeasibilityEnvelope,
) -> tuple[ProspectiveTargetAliasBinding, ...]:
    matrix_facts = tuple(
        item for item in envelope.evidence_facts if item.fact_kind == "cross_lineage_effect_matrix"
    )
    if len(matrix_facts) != 1:
        raise SystemPlanProspectiveAtomError("匿名目标上下文要求恰好一个跨谱系效果矩阵事实")
    try:
        matrix = CrossLineageSystemEffectMatrix.model_validate(matrix_facts[0].value)
    except (ValidationError, RuntimeError, ValueError) as exc:
        raise SystemPlanProspectiveAtomError("跨谱系效果矩阵无效") from exc
    eligible_types = {item.system_name: item.data_type for item in envelope.eligible_systems}
    profiles: dict[str, EvidenceFact] = {}
    effects: dict[tuple[str, str], EvidenceFact] = {}
    for fact in envelope.evidence_facts:
        value = _fact_mapping(fact)
        system_name = value.get("system_name")
        if fact.fact_kind == "data_profile" and isinstance(system_name, str):
            if system_name in profiles:
                raise SystemPlanProspectiveAtomError(f"系统 {system_name} 有重复数据画像事实")
            profiles[system_name] = fact
        if fact.fact_kind == "system_effect" and isinstance(system_name, str):
            lineage_id = value.get("lineage_id")
            if not isinstance(lineage_id, str) or not lineage_id:
                continue
            if value.get("baseline_available") is not True or value.get(
                "candidate_success_count"
            ) != value.get("candidate_cell_count"):
                continue
            key = (system_name, lineage_id)
            if key in effects:
                raise SystemPlanProspectiveAtomError(
                    f"系统 {system_name} 在谱系 {lineage_id} 有重复完整效果"
                )
            effects[key] = fact
    bindings: list[ProspectiveTargetAliasBinding] = []
    for row in matrix.comparable_system_rows:
        if row.system_name not in eligible_types:
            raise SystemPlanProspectiveAtomError(f"矩阵目标不在冻结可研究集合：{row.system_name}")
        if eligible_types[row.system_name] != row.data_type:
            raise SystemPlanProspectiveAtomError(f"矩阵目标类型与冻结白名单不符：{row.system_name}")
        profile = profiles.get(row.system_name)
        if profile is None:
            raise SystemPlanProspectiveAtomError(f"矩阵目标缺少冻结数据画像：{row.system_name}")
        effect_facts: list[EvidenceFact] = []
        for observation in row.observations:
            effect_fact = effects.get((row.system_name, observation.lineage_id))
            if effect_fact is None:
                raise SystemPlanProspectiveAtomError(
                    f"矩阵目标缺少完整谱系效果：{row.system_name}/" f"{observation.lineage_id}"
                )
            value = _fact_mapping(effect_fact)
            if (
                value.get("selected_candidate_id") != observation.selected_candidate_id
                or value.get("package_hash") != observation.package_hash
                or value.get("paired_log_effect") != observation.paired_log_effect
            ):
                raise SystemPlanProspectiveAtomError(
                    f"矩阵与逐系统效果事实不一致：{row.system_name}/" f"{observation.lineage_id}"
                )
            effect_facts.append(effect_fact)
        required = tuple(
            sorted(
                {
                    profile.fact_id,
                    matrix_facts[0].fact_id,
                    *(item.fact_id for item in effect_facts),
                }
            )
        )
        bindings.append(
            ProspectiveTargetAliasBinding(
                target_key=f"T{len(bindings) + 1:03d}",
                system_name=row.system_name,
                data_type=row.data_type,
                required_fact_ids=required,
            )
        )
    if len(bindings) < 3:
        raise SystemPlanProspectiveAtomError("前瞻单组件实验至少需要三个完整可比较匿名目标")
    return tuple(bindings)


def _anonymize(value: Any, aliases: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _anonymize(item, aliases) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_anonymize(item, aliases) for item in value]
    if isinstance(value, str):
        anonymized = value
        for system_name, target_key in sorted(
            aliases.items(), key=lambda item: len(item[0]), reverse=True
        ):
            anonymized = anonymized.replace(system_name, target_key)
        return anonymized
    return value


def _anonymous_fact_projection(
    fact: EvidenceFact,
    *,
    aliases: Mapping[str, str],
) -> Any:
    """Remove matrix rows duplicated by separately hash-bound system-effect facts."""

    if fact.fact_kind == "data_profile" and isinstance(fact.value, Mapping):
        channels = fact.value.get("channels")
        if isinstance(channels, list):
            metric_names = (
                "clean_state_root_mean_square",
                "clean_derivative_root_mean_square",
                "snr20_state_noise_relative_rms",
                "snr20_derivative_noise_relative_rms",
                "state_derivative_correlation",
                "boundary_to_interior_derivative_rms",
            )
            metric_ranges: dict[str, dict[str, float]] = {}
            for metric_name in metric_names:
                values: list[float] = []
                for item in channels:
                    if not isinstance(item, Mapping):
                        continue
                    raw_value = item.get(metric_name)
                    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                        continue
                    values.append(float(raw_value))
                if values:
                    metric_ranges[metric_name] = {
                        "minimum": min(values),
                        "maximum": max(values),
                    }
            profile_fields = (
                "system_name",
                "data_type",
                "array_shapes",
                "channel_count",
                "conditions_profiled",
                "coordinates",
                "sample_axis_count",
                "state_channel_max_abs_correlation",
                "derivative_channel_max_abs_correlation",
            )
            compact = {key: fact.value[key] for key in profile_fields if key in fact.value}
            compact["channel_metric_ranges"] = metric_ranges
            compact["projection_note_zh"] = (
                "逐通道重复统计压缩为各指标范围；完整数据画像由事实哈希绑定。"
            )
            return _anonymize(compact, aliases)
    if fact.fact_kind == "system_effect" and isinstance(fact.value, Mapping):
        effect_fields = (
            "system_name",
            "data_type",
            "lineage_id",
            "paired_log_effect",
            "candidate_cell_count",
            "candidate_success_count",
            "baseline_available",
        )
        compact = {key: fact.value[key] for key in effect_fields if key in fact.value}
        compact["projection_note_zh"] = (
            "候选标识、包哈希和重复损失字段由完整事实哈希绑定，不在提示中重复。"
        )
        return _anonymize(compact, aliases)
    if fact.fact_kind != "cross_lineage_effect_matrix":
        return _anonymize(fact.value, aliases)
    try:
        matrix = CrossLineageSystemEffectMatrix.model_validate(fact.value)
    except (ValidationError, RuntimeError, ValueError) as exc:
        raise SystemPlanProspectiveAtomError("跨谱系效果矩阵无法生成匿名去重投影") from exc
    return {
        "comparability_rule": matrix.comparability_rule,
        "candidate_differences_jointly_confounded": (
            matrix.candidate_differences_jointly_confounded
        ),
        "component_attribution_authorized": matrix.component_attribution_authorized,
        "confirmatory_use_requires_model_authored_component_ablation": (
            matrix.confirmatory_use_requires_model_authored_component_ablation
        ),
        "lineage_ids": [item.lineage_id for item in matrix.candidates],
        "complete_target_keys": [
            aliases[item.system_name] for item in matrix.comparable_system_rows
        ],
        "projection_note_zh": (
            "逐目标逐谱系数值由单独的哈希绑定系统效果事实完整提供；此处不重复矩阵行。"
        ),
    }


def _redact_observed_payload(
    value: Any,
    *,
    aliases: Mapping[str, str],
    titles: Mapping[str, str],
) -> Any:
    redacted = _anonymize(value, aliases)
    if isinstance(redacted, Mapping):
        return {
            str(key): _redact_observed_payload(
                item,
                aliases={},
                titles=titles,
            )
            for key, item in redacted.items()
        }
    if isinstance(redacted, list | tuple):
        return [_redact_observed_payload(item, aliases={}, titles=titles) for item in redacted]
    if isinstance(redacted, str):
        for title, reference_key in sorted(
            titles.items(), key=lambda item: len(item[0]), reverse=True
        ):
            redacted = redacted.replace(title, reference_key)
    return redacted


def _validate_interface_against_envelope(
    interface: ProspectiveExecutionInterfaceContract,
    envelope: ResearchFeasibilityEnvelope,
) -> None:
    expected = build_prospective_execution_interface_contract(
        envelope,
        public_hooks=interface.public_hooks,
        maximum_public_fit_calls_per_cell=(interface.maximum_public_fit_calls_per_cell),
    )
    if interface != expected:
        raise SystemPlanProspectiveAtomError("前瞻执行接口合同未精确绑定正式开发单元预算")


def _build_context_and_aliases(
    *,
    survey: PlanLiteratureSurveyArtifact,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    observed_component_binding: SystemPlanComponentAtomBinding,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    interface_contract: ProspectiveExecutionInterfaceContract,
    maximum_prompt_utf8_bytes: int,
) -> tuple[ProspectiveAtomContext, tuple[ProspectiveTargetAliasBinding, ...]]:
    if maximum_prompt_utf8_bytes < 1:
        raise SystemPlanProspectiveAtomError("提示大小上限必须为正整数")
    if observed_component_binding.feasibility_envelope_hash != feasibility_envelope.envelope_hash:
        raise SystemPlanProspectiveAtomError("observed baseline 与前瞻组件可行性边界不一致")
    _validate_method_skill_binding(method_skill_selection)
    if (
        observed_component_binding.method_skill_selection_artifact_hash
        != method_skill_selection.selection_artifact_hash
    ):
        raise SystemPlanProspectiveAtomError("observed baseline 与前瞻组件没有绑定同一方法技能选择")
    _validate_interface_against_envelope(interface_contract, feasibility_envelope)
    abstracts = _selected_abstracts(survey)
    target_aliases = _target_alias_bindings(feasibility_envelope)
    abstract_target_leaks = sorted(
        {
            alias.system_name
            for alias in target_aliases
            for abstract in abstracts
            if alias.system_name in abstract.abstract_text
        }
    )
    if abstract_target_leaks:
        raise SystemPlanProspectiveAtomError(
            "完整摘要含真实目标名，无法同时保留逐字摘要与匿名目标上下文："
            f"{abstract_target_leaks}"
        )
    skill_payload = json.dumps(
        method_skill_selection.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    skill_target_leaks = sorted(
        {alias.system_name for alias in target_aliases if alias.system_name in skill_payload}
    )
    selected_titles = tuple(str(item.get("title") or "") for item in survey.selected_references)
    skill_title_leaks = sorted(
        {title for title in selected_titles if title and title in skill_payload}
    )
    if skill_target_leaks or skill_title_leaks:
        raise SystemPlanProspectiveAtomError(
            "方法技能消息泄漏真实目标名或入选论文题名，不能进入匿名前瞻阶段："
            f"targets={skill_target_leaks}, titles={skill_title_leaks}"
        )
    alias_lookup = {item.system_name: item.target_key for item in target_aliases}
    required_fact_ids = {fact_id for item in target_aliases for fact_id in item.required_fact_ids}
    projections = tuple(
        AnonymousEvidenceFact(
            fact_id=fact.fact_id,
            fact_kind=fact.fact_kind,
            full_fact_sha256=canonical_model_hash(fact),
            anonymized_value=_anonymous_fact_projection(
                fact,
                aliases=alias_lookup,
            ),
        )
        for fact in feasibility_envelope.evidence_facts
        if fact.fact_id in required_fact_ids
    )
    if {item.fact_id for item in projections} != required_fact_ids:
        raise SystemPlanProspectiveAtomError("冻结事实投影没有完整覆盖匿名目标")
    alias_hash = canonical_model_hash(
        {"target_aliases": [item.model_dump(mode="json") for item in target_aliases]}
    )
    payload: dict[str, Any] = {
        "schema_version": "prospective-atom-context-v1",
        "survey_hash": survey.survey_hash,
        "selected_references_hash": _selected_references_hash(survey.selected_references),
        "feasibility_envelope_hash": feasibility_envelope.envelope_hash,
        "observed_component_binding_hash": observed_component_binding.binding_hash,
        "method_skill_selection_artifact_hash": (method_skill_selection.selection_artifact_hash),
        "interface_contract_hash": interface_contract.contract_hash,
        "target_alias_binding_hash": alias_hash,
        "selected_abstracts": [item.model_dump(mode="json") for item in abstracts],
        "anonymous_targets": [
            AnonymousTargetEvidence(
                target_key=item.target_key,
                data_type=item.data_type,
                required_fact_ids=item.required_fact_ids,
            ).model_dump(mode="json")
            for item in target_aliases
        ],
        "evidence_facts": [item.model_dump(mode="json") for item in projections],
        "interface_contract": interface_contract.model_dump(mode="json"),
        "maximum_prompt_utf8_bytes": maximum_prompt_utf8_bytes,
    }
    payload["context_payload_utf8_bytes"] = _json_utf8_size(payload)
    payload["context_hash"] = canonical_model_hash(payload)
    return ProspectiveAtomContext.model_validate(payload), target_aliases


def build_prospective_atom_context(
    *,
    survey: PlanLiteratureSurveyArtifact,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    observed_component_binding: SystemPlanComponentAtomBinding,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    interface_contract: ProspectiveExecutionInterfaceContract,
    maximum_prompt_utf8_bytes: int = _DEFAULT_MAX_PROMPT_UTF8_BYTES,
) -> ProspectiveAtomContext:
    """Build the exact anonymous, full-abstract model context."""

    context, _ = _build_context_and_aliases(
        survey=survey,
        feasibility_envelope=feasibility_envelope,
        observed_component_binding=observed_component_binding,
        method_skill_selection=method_skill_selection,
        interface_contract=interface_contract,
        maximum_prompt_utf8_bytes=maximum_prompt_utf8_bytes,
    )
    return context


def _atom_prose(atom: ProspectiveComponentAtom) -> tuple[str, ...]:
    return (
        atom.label_zh,
        atom.control_level_zh,
        atom.intervention_level_zh,
        atom.single_factor_rationale_zh,
        atom.literature_synthesis_zh,
        atom.delta_from_prior_work_zh,
        atom.falsifiable_single_factor_contrast_zh,
    )


def prospective_atom_portfolio_findings(
    *,
    portfolio: ProspectiveAtomPortfolio,
    context: ProspectiveAtomContext,
    target_aliases: Sequence[ProspectiveTargetAliasBinding],
    observed_component_binding: SystemPlanComponentAtomBinding,
    literature_survey: PlanLiteratureSurveyArtifact,
) -> tuple[str, ...]:
    """Return deterministic provenance, scope, interface, and budget failures."""

    findings: list[str] = []
    abstracts = {item.reference_index: item for item in context.selected_abstracts}
    targets = {item.target_key: item for item in context.anonymous_targets}
    observed = {item.atom_id: item for item in observed_component_binding.atoms}
    forbidden_system_names = tuple(item.system_name for item in target_aliases)
    forbidden_titles = tuple(
        str(item.get("title") or "")
        for item in literature_survey.selected_references
        if str(item.get("title") or "")
    )
    interface = context.interface_contract
    for atom in portfolio.atoms:
        baseline = observed.get(atom.baseline_observed_atom_id)
        if baseline is None:
            findings.append(f"{atom.atom_id} 引用了未知 observed baseline atom")
        elif atom.baseline_observed_atom_hash != canonical_model_hash(baseline):
            findings.append(f"{atom.atom_id} 的 observed baseline atom 哈希不符")
        unknown_targets = sorted(set(atom.target_keys) - set(targets))
        if unknown_targets:
            findings.append(f"{atom.atom_id} 引用了未知匿名目标：{unknown_targets}")
            continue
        expected_facts = tuple(
            sorted(
                {
                    fact_id
                    for target_key in atom.target_keys
                    for fact_id in targets[target_key].required_fact_ids
                }
            )
        )
        if atom.supporting_fact_ids != expected_facts:
            findings.append(f"{atom.atom_id} 的支持事实不是全部目标必需事实的稳定并集")
        expected_types = tuple(
            sorted({targets[target_key].data_type for target_key in atom.target_keys})
        )
        if atom.applicable_data_types != expected_types:
            findings.append(f"{atom.atom_id} 的目标类型与匿名目标不一致")
        if baseline is not None and not set(expected_types).issubset(
            baseline.applicable_data_types
        ):
            findings.append(f"{atom.atom_id} 的 observed baseline 不支持所选匿名目标类型")
        invalid_hooks = sorted(set(atom.public_hooks) - set(interface.public_hooks))
        if invalid_hooks:
            findings.append(f"{atom.atom_id} 使用了合同外公开接口：{invalid_hooks}")
        request = atom.resource_request
        exceeded = []
        if request.seconds_per_cell > interface.maximum_seconds_per_cell:
            exceeded.append("seconds_per_cell")
        if request.memory_mb_per_cell > interface.maximum_memory_mb_per_cell:
            exceeded.append("memory_mb_per_cell")
        if request.cpu_cores_per_cell > interface.maximum_cpu_cores_per_cell:
            exceeded.append("cpu_cores_per_cell")
        if request.public_fit_calls_per_cell > interface.maximum_public_fit_calls_per_cell:
            exceeded.append("public_fit_calls_per_cell")
        if exceeded:
            findings.append(f"{atom.atom_id} 的资源请求超过冻结预算：{exceeded}")
        for support in atom.literature_supports:
            record = abstracts.get(support.reference_index)
            if record is None:
                findings.append(f"{atom.atom_id} 引用了未知入选摘要：{support.reference_index}")
                continue
            if (
                support.retrieval_index != record.retrieval_index
                or support.source_record_hash != record.source_record_hash
                or support.abstract_sha256 != record.abstract_sha256
            ):
                findings.append(
                    f"{atom.atom_id} 的摘要支持来源哈希或检索编号不符："
                    f"{support.reference_index}"
                )
            if support.exact_support_span not in record.abstract_text:
                findings.append(
                    f"{atom.atom_id} 的支持片段不是完整摘要逐字子串：" f"{support.reference_index}"
                )
        for prose in _atom_prose(atom):
            leaked_systems = [name for name in forbidden_system_names if name in prose]
            leaked_titles = [title for title in forbidden_titles if title in prose]
            if leaked_systems:
                findings.append(f"{atom.atom_id} 的作者散文泄漏真实系统名：{leaked_systems}")
            if leaked_titles:
                findings.append(
                    f"{atom.atom_id} 的作者散文复述论文题名而非摘要证据：{leaked_titles}"
                )
    return tuple(dict.fromkeys(findings))


def prospective_atom_review_findings(
    *,
    review: ProspectiveAtomReviewPortfolio,
    portfolio: ProspectiveAtomPortfolio,
    context: ProspectiveAtomContext,
) -> tuple[str, ...]:
    """Check exact atom coverage and all-selected-abstract comparison coverage."""

    findings: list[str] = []
    expected_ids = tuple(item.atom_id for item in portfolio.atoms)
    if tuple(item.atom_id for item in review.reviews) != expected_ids:
        findings.append("独立审查没有按原顺序完整覆盖全部前瞻 atom")
    atom_hashes = {item.atom_id: canonical_model_hash(item) for item in portfolio.atoms}
    expected_comparisons = tuple(
        (item.reference_index, item.abstract_sha256) for item in context.selected_abstracts
    )
    for item in review.reviews:
        if item.atom_hash != atom_hashes.get(item.atom_id):
            findings.append(f"独立审查篡改了 {item.atom_id} 的 atom_hash")
        actual = tuple(
            (comparison.reference_index, comparison.abstract_sha256)
            for comparison in item.prior_work_comparisons
        )
        if actual != expected_comparisons:
            findings.append(f"{item.atom_id} 未按顺序比较全部真实入选摘要")
    return tuple(findings)


def _author_messages(
    *,
    context: ProspectiveAtomContext,
    observed_component_binding: SystemPlanComponentAtomBinding,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    target_aliases: Sequence[ProspectiveTargetAliasBinding],
    literature_survey: PlanLiteratureSurveyArtifact,
    prior_feedback: Sequence[str],
) -> list[dict[str, str]]:
    example = {
        "schema_version": "prospective-atom-portfolio-v1",
        "atoms": [
            {
                "atom_id": "P001",
                "origin_kind": "prospective_literature_derived",
                "baseline_observed_atom_id": "A001",
                "label_zh": "中文前瞻组件名称",
                "change_mode": "替换",
                "control_level_zh": "简洁清楚的中文对照水平",
                "intervention_level_zh": "简洁清楚的中文处理水平",
                "single_factor_rationale_zh": "中文单因子理由",
                "literature_synthesis_zh": "中文文献综合",
                "delta_from_prior_work_zh": "中文差异边界",
                "falsifiable_single_factor_contrast_zh": "中文反驳条件",
                "implementation_anchor": "prospective_component",
                "public_hooks": ["fit_equations"],
                "target_keys": ["T001", "T002", "T003"],
                "applicable_data_types": [],
                "supporting_fact_ids": [],
                "literature_supports": [
                    {
                        "reference_index": 1,
                        "exact_support_span": "逐字复制完整摘要中的连续片段",
                        "support_role": "问题动机",
                    }
                ],
                "frozen_dimensions": list(_FROZEN_DIMENSIONS),
                "resource_request": {
                    "seconds_per_cell": 1,
                    "memory_mb_per_cell": 128,
                    "cpu_cores_per_cell": 1,
                    "public_fit_calls_per_cell": 1,
                },
                "single_factor_intervention": True,
                "candidate_differences_jointly_confounded": True,
                "is_scientific_evidence": False,
                "innovation_verified": False,
                "execution_authorized": False,
            }
        ],
    }
    instruction = (
        "你是阶段主 Qwen。仅依据完整真实摘要、匿名事实、已审查 observed atoms 与冻结接口，"
        "提出一至三个前瞻单组件对照；不得写计划、执行实验或声称结果/创新成立，科研散文用"
        "简体中文。未提供论文题名和真实系统名，T001 等仅为匿名目标。每项绑定一个 observed "
        "atom，定义 control/intervention，并逐字冻结其余九类维度。文献支持取一至三篇互异"
        "摘要，不得为凑数量重复同一篇；exact_support_span 必须为摘要连续子串；你只选"
        "reference_index、片段与自拟中文 support_role；“方法参照”“方法基础”等清楚同义表达"
        "均可。所有编号、来源映射和 SHA 由编排器机械派生，不要计算或输出哈希。不得把论文"
        "已有方法改名为创新，delta 必须写明实验"
        "差异且 innovation_verified=false。target_keys 选三至五个且必须来自所绑定 observed "
        "atom 的 allowed_target_keys；applicable_data_types 与"
        "supporting_fact_ids 留空数组，由编排器依据所选目标机械派生；hook、资源不得越界。"
        "reasoning_content 须逐项核对文献复用、单因子、事实、接口、类型和预算，内容非空且"
        "不作证据；不要为满足字数而扩写。只返回"
        "严格 JSON 值，不返回说明或 Markdown。值骨架："
        + json.dumps(example, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
    if prior_feedback:
        instruction += (
            "上一轮未通过；这些是最低修复集，必须重新审计全部输出，不得删除安全边界或把"
            "既有方法包装成创新："
            + json.dumps(list(prior_feedback), ensure_ascii=False, separators=(",", ":"))
        )
    observed_payload = []
    aliases = {item.system_name: item.target_key for item in target_aliases}
    titles = {
        str(item.get("title")): f"R{index:03d}"
        for index, item in enumerate(literature_survey.selected_references, 1)
        if str(item.get("title") or "")
    }
    for atom in observed_component_binding.atoms:
        value = atom.model_dump(mode="json")
        value["atom_hash"] = canonical_model_hash(atom)
        projected = _redact_observed_payload(value, aliases=aliases, titles=titles)
        # The binding hash and atom_hash already commit these provenance identifiers.
        # They are not scientific content needed to choose a baseline, so repeating
        # them seven times wastes prompt budget while contributing no reasoning signal.
        for redundant_key in (
            "source_lineage_id",
            "source_summary_sha256",
            "source_clause_id",
        ):
            projected.pop(redundant_key, None)
        projected["allowed_target_keys"] = [
            item.target_key
            for item in target_aliases
            if item.data_type in set(atom.applicable_data_types)
        ]
        observed_payload.append(projected)
    return [
        {"role": "system", "content": instruction},
        _method_skill_context_message(method_skill_selection),
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "observed_component_baselines",
                    "observed_component_binding_hash": (observed_component_binding.binding_hash),
                    "observed_atoms": observed_payload,
                    "boundary": "这些是观察到的候选摘要组件，不是组件级因果证据。",
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "anonymous_full_abstract_prospective_context",
                    "prospective_context": context.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def _reviewer_messages(
    *,
    context: ProspectiveAtomContext,
    portfolio: ProspectiveAtomPortfolio,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    prior_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    atoms = [item.model_dump(mode="json") for item in portfolio.atoms]
    example = {
        "schema_version": "prospective-atom-review-portfolio-v1",
        "reviews": [
            {
                "atom_id": atom.atom_id,
                "prior_work_comparisons": [
                    {
                        "reference_index": record.reference_index,
                        "overlap_zh": "中文重叠说明",
                        "difference_zh": "中文差异说明",
                        "residual_risk_zh": "中文残余风险",
                        "direct_method_copy": False,
                        "abstract_insufficient": False,
                    }
                    for record in context.selected_abstracts
                ],
                "single_component_identifiable": True,
                "abstract_support_exact": True,
                "facts_support_scope": True,
                "no_system_name_inference": True,
                "target_type_valid": True,
                "interface_valid": True,
                "budget_valid": True,
                "falsifiable_counterfactual": True,
                "findings_zh": [],
            }
            for atom in portfolio.atoms
        ],
    }
    instruction = (
        "你是独立 Qwen 前瞻组件审查者，不得读取作者 reasoning，也不得替作者补写方案。对每个"
        " atom 按原顺序审查，并对用户消息中的全部 selected_abstracts 按 reference_index 原顺序"
        "逐篇输出 comparison；不得只比较作者选择的支持文献。若处理水平实质复制任一摘要已描述"
        "方法，direct_method_copy=true；若摘要不足以排除复制，abstract_insufficient=true。还要"
        "审查单组件可识别性、摘要逐字支持、"
        "事实范围、匿名目标、目标类型、公开接口、预算和可反驳对照。accepted 必须为九项硬门"
        "机械合取，但 not_direct_prior_method_copy、accepted、atom_hash 与全部 SHA 都由编排器"
        "根据你的逐篇判断确定，不要计算或输出。通过时 findings_zh 可为空，拒绝时尽量给出中文"
        "具体问题。仅能评价其为未执行候选，"
        "不得把摘要排重说成可发表创新。必须开启 thinking，在 reasoning_content 中逐篇逐门"
        "检查且内容非空；reasoning 不是证据，不要为满足字数而扩写。所有评审散文使用简体中文，"
        "只返回严格 JSON 值，逐篇 comparison 只写 reference_index，不写摘要哈希。值骨架："
        + json.dumps(
            example,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if prior_feedback:
        instruction += (
            "你上一审查响应存在传输、JSON 或机械覆盖问题；作者候选保持逐字不变。"
            "只修复审查响应，不得改写作者 atom。最低修复集："
            + json.dumps(
                list(prior_feedback),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return [
        {"role": "system", "content": instruction},
        _method_skill_context_message(method_skill_selection),
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "independent_prospective_atom_review",
                    "prospective_context": context.model_dump(mode="json"),
                    "author_atoms": atoms,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def _review_retry_feedback(
    review: ProspectiveAtomReviewPortfolio,
) -> tuple[str, ...]:
    return tuple(
        f"{item.atom_id} 独立审查未通过：" + "；".join(item.findings_zh)
        for item in review.reviews
        if not item.accepted
    )


def _ensure_message_budget(messages: Sequence[Mapping[str, str]], *, maximum_bytes: int) -> None:
    size = _json_utf8_size([dict(item) for item in messages])
    if size > maximum_bytes:
        raise SystemPlanProspectiveAtomError(
            f"前瞻组件完整模型提示为 {size} 字节，超过 {maximum_bytes}；拒绝静默截断"
        )


def _validate_receipt(
    receipt: ModelAuthorshipReceipt,
    *,
    artifact_kind: Literal["plan_opportunity_map", "plan_opportunity_map_review"],
    interaction_id: str,
    attempt: int,
    messages: Sequence[Mapping[str, str]],
    parsed_payload: Mapping[str, Any],
) -> None:
    _validate_receipt_provenance(
        receipt,
        artifact_kind=artifact_kind,
        interaction_id=interaction_id,
        attempt=attempt,
        messages=messages,
    )
    if receipt.parsed_payload != dict(parsed_payload):
        raise SystemPlanProspectiveAtomError("前瞻组件模型回执输出与制品不符")


def _validate_receipt_provenance(
    receipt: ModelAuthorshipReceipt,
    *,
    artifact_kind: Literal["plan_opportunity_map", "plan_opportunity_map_review"],
    interaction_id: str,
    attempt: int,
    messages: Sequence[Mapping[str, str]],
) -> None:
    if (
        receipt.artifact_kind != artifact_kind
        or receipt.interaction_id != interaction_id
        or receipt.attempt != attempt
    ):
        raise SystemPlanProspectiveAtomError("前瞻组件模型回执身份或轮次不符")
    if receipt.messages != tuple(dict(item) for item in messages):
        raise SystemPlanProspectiveAtomError("前瞻组件模型回执消息不符")
    identity = f"{receipt.provider} {receipt.model_name}".casefold()
    if "qwen" not in identity:
        raise SystemPlanProspectiveAtomError("前瞻组件作者与审查者必须是 Qwen")
    if len(str(receipt.reasoning_content or "").strip()) < _MIN_REASONING_CHARACTERS:
        raise SystemPlanProspectiveAtomError("前瞻组件 Qwen 回执缺少非空 reasoning_content")
    if receipt.reasoning_transport != "dashscope_enable_thinking":
        raise SystemPlanProspectiveAtomError("前瞻组件 Qwen 回执未证明 thinking 已开启")


def _derive_author_support_bindings(
    payload: Mapping[str, Any],
    *,
    context: ProspectiveAtomContext,
    observed_component_binding: SystemPlanComponentAtomBinding,
) -> dict[str, Any]:
    """Fill non-scientific literature provenance from Qwen's chosen exact span.

    Qwen owns the reference choice, exact abstract substring and support role.  SHA
    values and the selected-to-retrieved index join are deterministic bookkeeping,
    not scientific judgment.  Deriving them here both removes an impossible mental
    SHA task and leaves the resulting portfolio fully hash-bound and replayable.
    """

    decoded = json.loads(json.dumps(dict(payload), ensure_ascii=False, allow_nan=False))
    if not isinstance(decoded, dict):  # pragma: no cover - dict input guarantees this
        raise SystemPlanProspectiveAtomError("前瞻组件作者输出必须是对象")
    normalized: dict[str, Any] = decoded
    normalized["schema_version"] = "prospective-atom-portfolio-v1"
    atoms = normalized.get("atoms")
    if not isinstance(atoms, list):
        raise SystemPlanProspectiveAtomError("前瞻组件作者输出缺少 atoms 数组")
    abstracts = {item.reference_index: item for item in context.selected_abstracts}
    targets = {item.target_key: item for item in context.anonymous_targets}
    observed_atoms = {item.atom_id: item for item in observed_component_binding.atoms}
    for atom_index, atom in enumerate(atoms, 1):
        if not isinstance(atom, dict):
            raise SystemPlanProspectiveAtomError("前瞻组件 atom 必须是对象")
        atom["atom_id"] = f"P{atom_index:03d}"
        atom["origin_kind"] = "prospective_literature_derived"
        baseline_atom_id = atom.get("baseline_observed_atom_id")
        if not isinstance(baseline_atom_id, str):
            raise SystemPlanProspectiveAtomError("前瞻组件缺少观察基线 atom ID")
        baseline_atom = observed_atoms.get(baseline_atom_id)
        if baseline_atom is None:
            raise SystemPlanProspectiveAtomError(
                f"前瞻组件引用了未知观察基线 atom：{baseline_atom_id}"
            )
        atom["baseline_observed_atom_hash"] = canonical_model_hash(baseline_atom)
        target_keys = atom.get("target_keys")
        if not isinstance(target_keys, list) or not target_keys:
            raise SystemPlanProspectiveAtomError("前瞻组件缺少 target_keys 数组")
        if any(not isinstance(item, str) for item in target_keys):
            raise SystemPlanProspectiveAtomError("前瞻组件 target_keys 必须为字符串数组")
        unknown_target_keys = sorted(set(target_keys) - set(targets))
        if unknown_target_keys:
            raise SystemPlanProspectiveAtomError(
                f"前瞻组件引用了未知匿名目标：{unknown_target_keys}"
            )
        # Qwen owns the scientific target choice.  Target types and fact IDs are a
        # closed deterministic projection, so derive them instead of asking the model
        # to copy dozens of opaque identifiers.  Artifact replay repeats this step.
        atom["applicable_data_types"] = sorted(
            {targets[target_key].data_type for target_key in target_keys},
            key=("ode", "pde").index,
        )
        atom["supporting_fact_ids"] = sorted(
            {
                fact_id
                for target_key in target_keys
                for fact_id in targets[target_key].required_fact_ids
            }
        )
        supports = atom.get("literature_supports")
        if not isinstance(supports, list):
            raise SystemPlanProspectiveAtomError("前瞻组件缺少 literature_supports 数组")
        derived_supports: list[dict[str, Any]] = []
        seen_reference_indices: set[int] = set()
        for support in supports:
            if not isinstance(support, dict):
                raise SystemPlanProspectiveAtomError("文献支持项必须是对象")
            reference_index = support.get("reference_index")
            if isinstance(reference_index, bool) or not isinstance(reference_index, int):
                raise SystemPlanProspectiveAtomError("文献支持 reference_index 必须为整数")
            record = abstracts.get(reference_index)
            if record is None:
                raise SystemPlanProspectiveAtomError(
                    f"文献支持引用了未知入选摘要：{reference_index}"
                )
            span = support.get("exact_support_span")
            if not isinstance(span, str):
                raise SystemPlanProspectiveAtomError(
                    f"文献支持片段不是完整摘要逐字子串：{reference_index}"
                )
            if span not in record.abstract_text:
                repaired_span = _repair_transport_damaged_exact_span(
                    span,
                    abstract_text=record.abstract_text,
                )
                if repaired_span is None:
                    raise SystemPlanProspectiveAtomError(
                        f"文献支持片段不是完整摘要逐字子串：{reference_index}"
                    )
                span = repaired_span
                support["exact_support_span"] = span
            support["retrieval_index"] = record.retrieval_index
            support["source_record_hash"] = record.source_record_hash
            support["abstract_sha256"] = record.abstract_sha256
            support["support_span_sha256"] = hashlib.sha256(span.encode("utf-8")).hexdigest()
            # A repeated reference adds no scientific support.  Collapse an exact
            # duplicate mechanically while retaining the first Qwen-authored role and
            # span.  Exact all-abstract comparison remains a separate reviewer gate;
            # this normalization makes no new scientific choice.
            if reference_index in seen_reference_indices:
                continue
            seen_reference_indices.add(reference_index)
            derived_supports.append(support)
        atom["literature_supports"] = derived_supports
    return normalized


def _derive_reviewer_bindings(
    payload: Mapping[str, Any],
    *,
    portfolio: ProspectiveAtomPortfolio,
    context: ProspectiveAtomContext,
) -> dict[str, Any]:
    """Derive hashes and logical conjunctions from a reviewer's judgments.

    A reviewer chooses comparisons and scientific gate values.  Atom/abstract hashes,
    the negated direct-copy gate, and the final conjunction are deterministic
    bookkeeping.  They are therefore computed here rather than asking Qwen to copy
    opaque values or to keep redundant booleans synchronized.
    """

    decoded = json.loads(json.dumps(dict(payload), ensure_ascii=False, allow_nan=False))
    if not isinstance(decoded, dict):  # pragma: no cover - dict input guarantees this
        raise SystemPlanProspectiveAtomError("前瞻组件审查输出必须是对象")
    normalized: dict[str, Any] = decoded
    normalized["schema_version"] = "prospective-atom-review-portfolio-v1"
    reviews = normalized.get("reviews")
    if not isinstance(reviews, list):
        raise SystemPlanProspectiveAtomError("前瞻组件审查输出缺少 reviews 数组")
    abstracts = {item.reference_index: item for item in context.selected_abstracts}
    expected_atom_ids = tuple(item.atom_id for item in portfolio.atoms)
    reviews_by_atom_id: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            raise SystemPlanProspectiveAtomError("前瞻组件 review 必须是对象")
        raw_atom_id = review.get("atom_id")
        if raw_atom_id is None and len(portfolio.atoms) == 1:
            raw_atom_id = portfolio.atoms[0].atom_id
        if not isinstance(raw_atom_id, str) or raw_atom_id not in expected_atom_ids:
            raise SystemPlanProspectiveAtomError(f"前瞻组件审查引用了未知 atom：{raw_atom_id}")
        if raw_atom_id in reviews_by_atom_id:
            raise SystemPlanProspectiveAtomError(f"前瞻组件审查重复覆盖 atom：{raw_atom_id}")
        review["atom_id"] = raw_atom_id
        reviews_by_atom_id[raw_atom_id] = review
    if set(reviews_by_atom_id) != set(expected_atom_ids):
        missing_atoms = sorted(set(expected_atom_ids) - set(reviews_by_atom_id))
        raise SystemPlanProspectiveAtomError(f"前瞻组件审查没有完整覆盖作者 atom：{missing_atoms}")
    ordered_reviews: list[dict[str, Any]] = []
    for atom in portfolio.atoms:
        review = reviews_by_atom_id[atom.atom_id]
        review["atom_hash"] = canonical_model_hash(atom)
        comparisons = review.get("prior_work_comparisons")
        if not isinstance(comparisons, list):
            raise SystemPlanProspectiveAtomError("前瞻组件审查缺少逐篇比较数组")
        comparisons_by_reference: dict[int, dict[str, Any]] = {}
        for comparison in comparisons:
            if not isinstance(comparison, dict):
                raise SystemPlanProspectiveAtomError("前瞻组件逐篇比较必须是对象")
            reference_index = comparison.get("reference_index")
            if isinstance(reference_index, bool) or not isinstance(reference_index, int):
                raise SystemPlanProspectiveAtomError("前瞻组件逐篇比较 reference_index 必须为整数")
            abstract = abstracts.get(reference_index)
            if abstract is None:
                raise SystemPlanProspectiveAtomError(
                    f"前瞻组件逐篇比较引用了未知摘要：{reference_index}"
                )
            if reference_index in comparisons_by_reference:
                raise SystemPlanProspectiveAtomError(
                    f"前瞻组件逐篇比较重复引用摘要：{reference_index}"
                )
            comparison["abstract_sha256"] = abstract.abstract_sha256
            comparisons_by_reference[reference_index] = comparison
        if set(comparisons_by_reference) != set(abstracts):
            missing_references = sorted(set(abstracts) - set(comparisons_by_reference))
            raise SystemPlanProspectiveAtomError(
                f"前瞻组件逐篇比较没有完整覆盖入选摘要：{missing_references}"
            )
        ordered_comparisons = [
            comparisons_by_reference[item.reference_index] for item in context.selected_abstracts
        ]
        review["prior_work_comparisons"] = ordered_comparisons
        comparisons_clear = all(
            (
                comparison.get("direct_method_copy") is False
                and comparison.get("abstract_insufficient") is False
            )
            for comparison in ordered_comparisons
        )
        review["not_direct_prior_method_copy"] = comparisons_clear
        review["accepted"] = all(
            review.get(field_name) is True for field_name in _REVIEW_GATE_LABELS
        )
        findings = review.get("findings_zh")
        if not review["accepted"] and (not isinstance(findings, list) or not findings):
            review["findings_zh"] = [
                label
                for field_name, label in _REVIEW_GATE_LABELS.items()
                if review.get(field_name) is not True
            ]
        ordered_reviews.append(review)
    normalized["reviews"] = ordered_reviews
    return normalized


def _repair_transport_damaged_exact_span(
    span: str,
    *,
    abstract_text: str,
) -> str | None:
    """Recover only a unique punctuation-equivalent substring from the source.

    Some provider transports replace an en dash with ``\ufffdC`` or normalize one
    dash glyph to another.  That is an encoding defect rather than a scientific
    paraphrase.  We therefore permit a repair only when the normalized model span
    occurs exactly once in the normalized *full* abstract, and return the original
    source bytes from that location.  Words, letter case, and numbers are never
    normalized, so a paraphrase or invented claim remains invalid.
    """

    def _normalized_with_source_bounds(text: str) -> tuple[str, tuple[tuple[int, int], ...]]:
        normalized: list[str] = []
        bounds: list[tuple[int, int]] = []
        index = 0
        dash_characters = {"\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"}
        while index < len(text):
            if text.startswith("\ufffdC", index):
                normalized.append("-")
                bounds.append((index, index + 2))
                index += 2
                continue
            character = text[index]
            normalized.append("-" if character in dash_characters else character)
            bounds.append((index, index + 1))
            index += 1
        return "".join(normalized), tuple(bounds)

    normalized_span, _ = _normalized_with_source_bounds(span)
    if len(normalized_span) < 24:
        return None
    normalized_abstract, abstract_bounds = _normalized_with_source_bounds(abstract_text)
    matches: list[int] = []
    cursor = 0
    while True:
        match = normalized_abstract.find(normalized_span, cursor)
        if match < 0:
            break
        matches.append(match)
        cursor = match + 1
    if len(matches) != 1:
        return None
    start = matches[0]
    end = start + len(normalized_span) - 1
    source_start = abstract_bounds[start][0]
    source_end = abstract_bounds[end][1]
    repaired = abstract_text[source_start:source_end]
    return repaired if repaired in abstract_text else None


def _assess_author_receipt(
    *,
    receipt: ModelAuthorshipReceipt,
    round_index: int,
    messages: Sequence[Mapping[str, str]],
    context: ProspectiveAtomContext,
    target_aliases: Sequence[ProspectiveTargetAliasBinding],
    observed_component_binding: SystemPlanComponentAtomBinding,
    literature_survey: PlanLiteratureSurveyArtifact,
) -> tuple[ProspectiveAtomPortfolio | None, tuple[str, ...]]:
    try:
        _validate_receipt_provenance(
            receipt,
            artifact_kind="plan_opportunity_map",
            interaction_id=f"system-plan-prospective-atoms-author-{round_index:02d}",
            attempt=round_index,
            messages=messages,
        )
        normalized_payload = _derive_author_support_bindings(
            receipt.parsed_payload,
            context=context,
            observed_component_binding=observed_component_binding,
        )
        portfolio = ProspectiveAtomPortfolio.model_validate(normalized_payload)
        findings = prospective_atom_portfolio_findings(
            portfolio=portfolio,
            context=context,
            target_aliases=target_aliases,
            observed_component_binding=observed_component_binding,
            literature_survey=literature_survey,
        )
        # Scientific choices and prose remain byte-for-byte from the receipt.  Only
        # retrieval/hash fields inside literature_supports are derived from the chosen
        # reference and exact span; asking a language model to calculate SHA-256 made
        # a valid creative proposal mathematically unreachable.
        if _derive_author_support_bindings(
            receipt.parsed_payload,
            context=context,
            observed_component_binding=observed_component_binding,
        ) != portfolio.model_dump(mode="json"):
            raise SystemPlanProspectiveAtomError("前瞻组件机械文献绑定投影不可重放")
    except (ValidationError, RuntimeError, ValueError) as exc:
        return None, (f"主 Qwen 前瞻组件结构、中文或回执无效：{exc}",)
    if findings:
        return None, findings
    return portfolio, ()


def _assess_reviewer_receipt(
    *,
    receipt: ModelAuthorshipReceipt,
    round_index: int,
    reviewer_attempt_index: int,
    messages: Sequence[Mapping[str, str]],
    portfolio: ProspectiveAtomPortfolio,
    context: ProspectiveAtomContext,
) -> tuple[ProspectiveAtomReviewPortfolio | None, tuple[str, ...]]:
    try:
        _validate_receipt_provenance(
            receipt,
            artifact_kind="plan_opportunity_map_review",
            interaction_id=(
                "system-plan-prospective-atoms-reviewer-"
                f"{round_index:02d}-{reviewer_attempt_index:02d}"
            ),
            attempt=reviewer_attempt_index,
            messages=messages,
        )
        normalized_payload = _derive_reviewer_bindings(
            receipt.parsed_payload,
            portfolio=portfolio,
            context=context,
        )
        review = ProspectiveAtomReviewPortfolio.model_validate(normalized_payload)
        findings = prospective_atom_review_findings(
            review=review,
            portfolio=portfolio,
            context=context,
        )
        if _derive_reviewer_bindings(
            receipt.parsed_payload,
            portfolio=portfolio,
            context=context,
        ) != review.model_dump(mode="json"):
            raise SystemPlanProspectiveAtomError("前瞻组件机械审查绑定投影不可重放")
    except (ValidationError, RuntimeError, ValueError) as exc:
        return None, (f"独立 Qwen 前瞻组件审查结构、中文或回执无效：{exc}",)
    if findings:
        return None, findings
    return review, ()


def _validate_persisted_receipt(
    output_root: Path,
    relative_path: str,
    receipt: ModelAuthorshipReceipt,
) -> None:
    path = (output_root / relative_path).resolve()
    try:
        path.relative_to(output_root)
    except ValueError as exc:
        raise SystemPlanProspectiveAtomError("前瞻组件回执路径逃逸输出目录") from exc
    if path != Path(receipt.output_path).resolve() or not path.is_file():
        raise SystemPlanProspectiveAtomError("前瞻组件回执路径或实物不一致")
    persisted = ModelAuthorshipReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    if persisted != receipt:
        raise SystemPlanProspectiveAtomError("前瞻组件回执实物已被替换")


def _call_qwen(
    *,
    completion: Callable[..., LLMJsonCompletionResult],
    messages: Sequence[Mapping[str, str]],
    response_schema_name: str,
    config_path: Path | str,
    env_path: Path | str,
    max_tokens: int,
    temperature: float,
) -> LLMJsonCompletionResult:
    return completion(
        messages=list(messages),
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=300,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_mode="enabled",
        thinking_budget=_THINKING_BUDGET,
        response_schema=None,
        response_schema_name=response_schema_name,
    )


def _relative_receipt_path(output_root: Path, receipt: ModelAuthorshipReceipt) -> str:
    try:
        return Path(receipt.output_path).resolve().relative_to(output_root).as_posix()
    except ValueError as exc:
        raise SystemPlanProspectiveAtomError("前瞻组件回执不在输出目录内") from exc


def _attempt_record(
    *,
    stage: AttemptStage,
    round_index: int,
    stage_attempt_index: int,
    input_feedback: Sequence[str],
    messages: Sequence[Mapping[str, str]],
    outcome: AttemptOutcome,
    failure_summary: Sequence[str],
    output_root: Path,
    receipt: ModelAuthorshipReceipt | None = None,
    no_progress_fuse_triggered: bool = False,
) -> ProspectiveModelAttempt:
    payload: dict[str, Any] = {
        "schema_version": "prospective-model-attempt-v1",
        "stage": stage,
        "round_index": round_index,
        "stage_attempt_index": stage_attempt_index,
        "input_feedback_zh": list(input_feedback),
        "messages_sha256": canonical_model_hash({"messages": [dict(item) for item in messages]}),
        "outcome": outcome,
        "failure_summary_zh": list(failure_summary),
        "receipt": receipt.model_dump(mode="json") if receipt is not None else None,
        "receipt_relative_path": (
            _relative_receipt_path(output_root, receipt) if receipt is not None else None
        ),
        "receipt_hash": receipt.receipt_hash if receipt is not None else None,
        "no_progress_fuse_triggered": no_progress_fuse_triggered,
    }
    payload["attempt_hash"] = canonical_model_hash(payload)
    return ProspectiveModelAttempt.model_validate(payload)


def _persist_attempt_record(
    output_root: Path,
    attempt: ProspectiveModelAttempt,
) -> None:
    path = (
        output_root
        / "prospective-attempts"
        / (f"{attempt.round_index:02d}-{attempt.stage}-" f"{attempt.stage_attempt_index:02d}.json")
    )
    payload = json.dumps(
        attempt.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = ProspectiveModelAttempt.model_validate_json(path.read_text(encoding="utf-8"))
        if existing != attempt:
            raise SystemPlanProspectiveAtomError(f"拒绝覆盖不同的前瞻模型尝试记录：{path}") from exc
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _append_attempt(
    attempts: list[ProspectiveModelAttempt],
    attempt: ProspectiveModelAttempt,
    *,
    output_root: Path,
) -> None:
    _persist_attempt_record(output_root, attempt)
    attempts.append(attempt)


def _no_progress_signature(
    receipt: ModelAuthorshipReceipt,
    findings: Sequence[str],
) -> str:
    return canonical_model_hash(
        {
            "parsed_payload": receipt.parsed_payload,
            "findings": list(findings),
        }
    )


def _validate_attempt_manifest(
    artifact: SystemPlanProspectiveAtomArtifact,
    *,
    output_root: Path,
) -> None:
    attempts = artifact.attempt_manifest
    for attempt in attempts:
        attempt_path = (
            output_root
            / "prospective-attempts"
            / (
                f"{attempt.round_index:02d}-{attempt.stage}-"
                f"{attempt.stage_attempt_index:02d}.json"
            )
        )
        if not attempt_path.is_file():
            raise SystemPlanProspectiveAtomError("前瞻模型尝试记录实物缺失")
        persisted_attempt = ProspectiveModelAttempt.model_validate_json(
            attempt_path.read_text(encoding="utf-8")
        )
        if persisted_attempt != attempt:
            raise SystemPlanProspectiveAtomError("前瞻模型尝试记录实物已被替换")
    feedback: tuple[str, ...] = ()
    attempt_index = 0
    expected_round = 1
    expected_author_attempt_index = 1
    completed_pairs: list[tuple[int, str, str, tuple[str, ...], int, tuple[str, ...]]] = []
    accepted_seen = False
    while attempt_index < len(attempts):
        author_attempt = attempts[attempt_index]
        if (
            author_attempt.stage != "author"
            or author_attempt.round_index != expected_round
            or author_attempt.stage_attempt_index != expected_author_attempt_index
            or author_attempt.input_feedback_zh != feedback
        ):
            raise SystemPlanProspectiveAtomError("前瞻模型尝试清单的作者轮次、顺序或反馈链不连续")
        author_messages = _author_messages(
            context=artifact.context,
            observed_component_binding=artifact.observed_component_binding,
            method_skill_selection=artifact.method_skill_selection,
            target_aliases=artifact.target_aliases,
            literature_survey=artifact.literature_survey,
            prior_feedback=feedback,
        )
        if author_attempt.messages_sha256 != canonical_model_hash(
            {"messages": [dict(item) for item in author_messages]}
        ):
            raise SystemPlanProspectiveAtomError("作者尝试的精确提示哈希不符")
        attempt_index += 1
        if author_attempt.outcome == "author_call_failed":
            if author_attempt.stage_attempt_index < _MAX_AUTHOR_TRANSPORT_ATTEMPTS_PER_ROUND:
                expected_author_attempt_index += 1
                continue
            feedback = author_attempt.failure_summary_zh
            expected_round += 1
            expected_author_attempt_index = 1
            continue
        if author_attempt.receipt is None or author_attempt.receipt_relative_path is None:
            raise SystemPlanProspectiveAtomError("作者响应尝试缺少回执")
        _validate_persisted_receipt(
            output_root,
            author_attempt.receipt_relative_path,
            author_attempt.receipt,
        )
        portfolio, author_failure = _assess_author_receipt(
            receipt=author_attempt.receipt,
            round_index=expected_round,
            messages=author_messages,
            context=artifact.context,
            target_aliases=artifact.target_aliases,
            observed_component_binding=artifact.observed_component_binding,
            literature_survey=artifact.literature_survey,
        )
        if portfolio is None:
            if (
                author_attempt.outcome != "author_rejected"
                or author_attempt.failure_summary_zh != author_failure
            ):
                raise SystemPlanProspectiveAtomError("作者失败响应的机械判定或逐字失败摘要不符")
            feedback = author_failure
            expected_round += 1
            expected_author_attempt_index = 1
            continue
        if author_attempt.outcome != "author_forwarded" or author_attempt.failure_summary_zh:
            raise SystemPlanProspectiveAtomError("合格作者响应未被精确标为送审")
        reviewer_feedback: tuple[str, ...] = ()
        reviewer_attempt_index = 1
        while True:
            if attempt_index >= len(attempts):
                raise SystemPlanProspectiveAtomError("送审作者响应缺少审查者尝试")
            reviewer_attempt = attempts[attempt_index]
            if (
                reviewer_attempt.stage != "reviewer"
                or reviewer_attempt.round_index != expected_round
                or reviewer_attempt.stage_attempt_index != reviewer_attempt_index
                or reviewer_attempt.input_feedback_zh != reviewer_feedback
            ):
                raise SystemPlanProspectiveAtomError(
                    "前瞻模型尝试清单的审查者轮次、顺序或反馈链不符"
                )
            reviewer_messages = _reviewer_messages(
                context=artifact.context,
                portfolio=portfolio,
                method_skill_selection=artifact.method_skill_selection,
                prior_feedback=reviewer_feedback,
            )
            if reviewer_attempt.messages_sha256 != canonical_model_hash(
                {"messages": [dict(item) for item in reviewer_messages]}
            ):
                raise SystemPlanProspectiveAtomError("审查者尝试的精确提示哈希不符")
            attempt_index += 1
            if reviewer_attempt.outcome == "reviewer_call_failed":
                reviewer_feedback = reviewer_attempt.failure_summary_zh
                reviewer_attempt_index += 1
                continue
            if reviewer_attempt.receipt is None or reviewer_attempt.receipt_relative_path is None:
                raise SystemPlanProspectiveAtomError("审查者响应尝试缺少回执")
            _validate_persisted_receipt(
                output_root,
                reviewer_attempt.receipt_relative_path,
                reviewer_attempt.receipt,
            )
            review, reviewer_failure = _assess_reviewer_receipt(
                receipt=reviewer_attempt.receipt,
                round_index=expected_round,
                reviewer_attempt_index=reviewer_attempt_index,
                messages=reviewer_messages,
                portfolio=portfolio,
                context=artifact.context,
            )
            if review is None:
                if (
                    reviewer_attempt.outcome != "reviewer_rejected"
                    or reviewer_attempt.failure_summary_zh != reviewer_failure
                ):
                    raise SystemPlanProspectiveAtomError(
                        "审查者失败响应的机械判定或逐字失败摘要不符"
                    )
                reviewer_feedback = reviewer_failure
                reviewer_attempt_index += 1
                continue
            completed_pairs.append(
                (
                    expected_round,
                    author_attempt.receipt.receipt_hash,
                    reviewer_attempt.receipt.receipt_hash,
                    author_attempt.input_feedback_zh,
                    reviewer_attempt_index,
                    reviewer_attempt.input_feedback_zh,
                )
            )
            review_accepted = all(item.accepted for item in review.reviews)
            if review_accepted:
                if (
                    reviewer_attempt.outcome != "reviewer_accepted"
                    or reviewer_attempt.failure_summary_zh
                ):
                    raise SystemPlanProspectiveAtomError("通过审查的响应结果标记不符")
                accepted_seen = True
                feedback = ()
            else:
                retry_feedback = _review_retry_feedback(review)
                if (
                    reviewer_attempt.outcome != "reviewer_declined"
                    or reviewer_attempt.failure_summary_zh != retry_feedback
                ):
                    raise SystemPlanProspectiveAtomError("未通过审查的逐字重试反馈不符")
                feedback = retry_feedback
            break
        expected_round += 1
        expected_author_attempt_index = 1
        if accepted_seen and attempt_index != len(attempts):
            raise SystemPlanProspectiveAtomError("前瞻组件通过后仍存在额外模型尝试")
    if not accepted_seen:
        raise SystemPlanProspectiveAtomError("成功制品的尝试清单没有通过审查的终局")
    actual_pairs = [
        (
            item.round_index,
            item.author_receipt.receipt_hash,
            item.reviewer_receipt.receipt_hash,
            item.author_feedback_zh,
            item.reviewer_attempt_index,
            item.reviewer_feedback_zh,
        )
        for item in artifact.rounds
    ]
    if completed_pairs != actual_pairs:
        raise SystemPlanProspectiveAtomError("完整作者—审查回执对没有逐项绑定到 rounds")


def _round_record(
    *,
    round_index: int,
    author_feedback: Sequence[str],
    author_portfolio: ProspectiveAtomPortfolio,
    author_receipt: ModelAuthorshipReceipt,
    reviewer_attempt_index: int,
    reviewer_feedback: Sequence[str],
    review_portfolio: ProspectiveAtomReviewPortfolio,
    reviewer_receipt: ModelAuthorshipReceipt,
    output_root: Path,
) -> ProspectiveAtomRound:
    payload: dict[str, Any] = {
        "round_index": round_index,
        "author_feedback_zh": list(author_feedback),
        "author_portfolio": author_portfolio.model_dump(mode="json"),
        "author_receipt": author_receipt.model_dump(mode="json"),
        "author_receipt_relative_path": _relative_receipt_path(output_root, author_receipt),
        "reviewer_attempt_index": reviewer_attempt_index,
        "reviewer_feedback_zh": list(reviewer_feedback),
        "review_portfolio": review_portfolio.model_dump(mode="json"),
        "reviewer_receipt": reviewer_receipt.model_dump(mode="json"),
        "reviewer_receipt_relative_path": _relative_receipt_path(output_root, reviewer_receipt),
        "accepted": all(item.accepted for item in review_portfolio.reviews),
    }
    payload["round_hash"] = canonical_model_hash(payload)
    return ProspectiveAtomRound.model_validate(payload)


def _write_immutable(path: Path, artifact: SystemPlanProspectiveAtomArtifact) -> None:
    payload = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = SystemPlanProspectiveAtomArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if existing != artifact:
            raise SystemPlanProspectiveAtomError(
                f"拒绝覆盖不同的前瞻组件不可变制品：{path}"
            ) from exc
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def run_system_plan_prospective_atoms(
    *,
    lineage_id: str,
    literature_survey: PlanLiteratureSurveyArtifact,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    observed_component_binding: SystemPlanComponentAtomBinding,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    interface_contract: ProspectiveExecutionInterfaceContract,
    output_dir: Path | str,
    author_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    reviewer_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_rounds: int = _MAX_ROUNDS,
    maximum_prompt_utf8_bytes: int = _DEFAULT_MAX_PROMPT_UTF8_BYTES,
    clock: datetime | None = None,
) -> SystemPlanProspectiveAtomArtifact:
    """Run bounded main-Qwen authorship and independent all-abstract review."""

    if not 1 <= max_rounds <= _MAX_ROUNDS:
        raise SystemPlanProspectiveAtomError("前瞻组件作者—审查轮次必须在一至五轮之间")
    if literature_survey.lineage_id != lineage_id:
        raise SystemPlanProspectiveAtomError("前瞻组件与文献调研谱系不一致")
    context, target_aliases = _build_context_and_aliases(
        survey=literature_survey,
        feasibility_envelope=feasibility_envelope,
        observed_component_binding=observed_component_binding,
        method_skill_selection=method_skill_selection,
        interface_contract=interface_contract,
        maximum_prompt_utf8_bytes=maximum_prompt_utf8_bytes,
    )
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    feedback: tuple[str, ...] = ()
    attempt_manifest: list[ProspectiveModelAttempt] = []
    last_rejection_signatures: dict[str, str] = {}
    completed_rounds: list[ProspectiveAtomRound] = []
    final_portfolio: ProspectiveAtomPortfolio | None = None
    final_review: ProspectiveAtomReviewPortfolio | None = None
    for round_index in range(1, max_rounds + 1):
        author_feedback = feedback
        author_messages = _author_messages(
            context=context,
            observed_component_binding=observed_component_binding,
            method_skill_selection=method_skill_selection,
            target_aliases=target_aliases,
            literature_survey=literature_survey,
            prior_feedback=author_feedback,
        )
        _ensure_message_budget(author_messages, maximum_bytes=maximum_prompt_utf8_bytes)
        author_result: LLMJsonCompletionResult | None = None
        author_attempt_index = 0
        for author_attempt_index in range(1, _MAX_AUTHOR_TRANSPORT_ATTEMPTS_PER_ROUND + 1):
            try:
                author_result = _call_qwen(
                    completion=author_completion,
                    messages=author_messages,
                    response_schema_name="system_plan_prospective_atoms_author",
                    config_path=config_path,
                    env_path=env_path,
                    max_tokens=12_000,
                    temperature=0.2,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                transport_failure = (f"主 Qwen 前瞻组件调用或 JSON 解析失败：{exc}",)
                _append_attempt(
                    attempt_manifest,
                    _attempt_record(
                        stage="author",
                        round_index=round_index,
                        stage_attempt_index=author_attempt_index,
                        input_feedback=author_feedback,
                        messages=author_messages,
                        outcome="author_call_failed",
                        failure_summary=transport_failure,
                        output_root=output_root,
                    ),
                    output_root=output_root,
                )
                feedback = transport_failure
                continue
            break
        if author_result is None:
            continue
        author_receipt = record_model_authorship_receipt(
            artifact_kind="plan_opportunity_map",
            interaction_id=f"system-plan-prospective-atoms-author-{round_index:02d}",
            attempt=round_index,
            messages=author_messages,
            completion=author_result,
            output_dir=output_root,
            clock=clock,
        )
        author_portfolio, author_failure = _assess_author_receipt(
            receipt=author_receipt,
            round_index=round_index,
            messages=author_messages,
            context=context,
            target_aliases=target_aliases,
            observed_component_binding=observed_component_binding,
            literature_survey=literature_survey,
        )
        if author_portfolio is None:
            feedback = author_failure
            signature = _no_progress_signature(author_receipt, feedback)
            fuse_triggered = last_rejection_signatures.get("author") == signature
            if fuse_triggered:
                feedback = (
                    *feedback,
                    "主 Qwen 连续返回相同作者载荷和机械问题，触发无进展熔断。",
                )
            last_rejection_signatures["author"] = signature
            _append_attempt(
                attempt_manifest,
                _attempt_record(
                    stage="author",
                    round_index=round_index,
                    stage_attempt_index=author_attempt_index,
                    input_feedback=author_feedback,
                    messages=author_messages,
                    outcome="author_rejected",
                    failure_summary=feedback,
                    output_root=output_root,
                    receipt=author_receipt,
                    no_progress_fuse_triggered=fuse_triggered,
                ),
                output_root=output_root,
            )
            if fuse_triggered:
                raise SystemPlanProspectiveAtomError("；".join(feedback))
            continue
        last_rejection_signatures.pop("author", None)
        _append_attempt(
            attempt_manifest,
            _attempt_record(
                stage="author",
                round_index=round_index,
                stage_attempt_index=author_attempt_index,
                input_feedback=author_feedback,
                messages=author_messages,
                outcome="author_forwarded",
                failure_summary=(),
                output_root=output_root,
                receipt=author_receipt,
            ),
            output_root=output_root,
        )
        reviewer_feedback: tuple[str, ...] = ()
        technical_review_succeeded = False
        for reviewer_attempt_index in range(1, _MAX_REVIEWER_ATTEMPTS_PER_AUTHOR + 1):
            reviewer_messages = _reviewer_messages(
                context=context,
                portfolio=author_portfolio,
                method_skill_selection=method_skill_selection,
                prior_feedback=reviewer_feedback,
            )
            _ensure_message_budget(reviewer_messages, maximum_bytes=maximum_prompt_utf8_bytes)
            try:
                reviewer_result = _call_qwen(
                    completion=reviewer_completion,
                    messages=reviewer_messages,
                    response_schema_name="system_plan_prospective_atoms_reviewer",
                    config_path=config_path,
                    env_path=env_path,
                    max_tokens=12_000,
                    temperature=0.0,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                reviewer_failure: tuple[str, ...] = (
                    f"独立 Qwen 前瞻组件审查调用或 JSON 解析失败：{exc}",
                )
                signature = canonical_model_hash({"reviewer_call_failure": list(reviewer_failure)})
                fuse_triggered = last_rejection_signatures.get("reviewer_technical") == signature
                if fuse_triggered:
                    reviewer_failure = (
                        *reviewer_failure,
                        "独立 Qwen 连续发生相同审查调用失败，触发无进展熔断。",
                    )
                last_rejection_signatures["reviewer_technical"] = signature
                _append_attempt(
                    attempt_manifest,
                    _attempt_record(
                        stage="reviewer",
                        round_index=round_index,
                        stage_attempt_index=reviewer_attempt_index,
                        input_feedback=reviewer_feedback,
                        messages=reviewer_messages,
                        outcome="reviewer_call_failed",
                        failure_summary=reviewer_failure,
                        output_root=output_root,
                        no_progress_fuse_triggered=fuse_triggered,
                    ),
                    output_root=output_root,
                )
                if fuse_triggered:
                    raise SystemPlanProspectiveAtomError("；".join(reviewer_failure)) from exc
                reviewer_feedback = reviewer_failure
                continue
            reviewer_receipt = record_model_authorship_receipt(
                artifact_kind="plan_opportunity_map_review",
                interaction_id=(
                    "system-plan-prospective-atoms-reviewer-"
                    f"{round_index:02d}-{reviewer_attempt_index:02d}"
                ),
                attempt=reviewer_attempt_index,
                messages=reviewer_messages,
                completion=reviewer_result,
                output_dir=output_root,
                clock=clock,
            )
            review_portfolio, reviewer_failure = _assess_reviewer_receipt(
                receipt=reviewer_receipt,
                round_index=round_index,
                reviewer_attempt_index=reviewer_attempt_index,
                messages=reviewer_messages,
                portfolio=author_portfolio,
                context=context,
            )
            if review_portfolio is None:
                signature = _no_progress_signature(reviewer_receipt, reviewer_failure)
                fuse_triggered = last_rejection_signatures.get("reviewer_technical") == signature
                if fuse_triggered:
                    reviewer_failure = (
                        *reviewer_failure,
                        "独立 Qwen 连续返回相同审查载荷和机械问题，触发无进展熔断。",
                    )
                last_rejection_signatures["reviewer_technical"] = signature
                _append_attempt(
                    attempt_manifest,
                    _attempt_record(
                        stage="reviewer",
                        round_index=round_index,
                        stage_attempt_index=reviewer_attempt_index,
                        input_feedback=reviewer_feedback,
                        messages=reviewer_messages,
                        outcome="reviewer_rejected",
                        failure_summary=reviewer_failure,
                        output_root=output_root,
                        receipt=reviewer_receipt,
                        no_progress_fuse_triggered=fuse_triggered,
                    ),
                    output_root=output_root,
                )
                if fuse_triggered:
                    raise SystemPlanProspectiveAtomError("；".join(reviewer_failure))
                reviewer_feedback = reviewer_failure
                continue
            technical_review_succeeded = True
            last_rejection_signatures.pop("reviewer_technical", None)
            record = _round_record(
                round_index=round_index,
                author_feedback=author_feedback,
                author_portfolio=author_portfolio,
                author_receipt=author_receipt,
                reviewer_attempt_index=reviewer_attempt_index,
                reviewer_feedback=reviewer_feedback,
                review_portfolio=review_portfolio,
                reviewer_receipt=reviewer_receipt,
                output_root=output_root,
            )
            completed_rounds.append(record)
            if record.accepted:
                last_rejection_signatures.pop("reviewer_scientific", None)
                _append_attempt(
                    attempt_manifest,
                    _attempt_record(
                        stage="reviewer",
                        round_index=round_index,
                        stage_attempt_index=reviewer_attempt_index,
                        input_feedback=reviewer_feedback,
                        messages=reviewer_messages,
                        outcome="reviewer_accepted",
                        failure_summary=(),
                        output_root=output_root,
                        receipt=reviewer_receipt,
                    ),
                    output_root=output_root,
                )
                final_portfolio = author_portfolio
                final_review = review_portfolio
                break
            feedback = _review_retry_feedback(review_portfolio)
            signature = _no_progress_signature(reviewer_receipt, feedback)
            fuse_triggered = last_rejection_signatures.get("reviewer_scientific") == signature
            if fuse_triggered:
                feedback = (
                    *feedback,
                    "独立 Qwen 连续返回相同审查载荷和 findings，触发无进展熔断。",
                )
            last_rejection_signatures["reviewer_scientific"] = signature
            _append_attempt(
                attempt_manifest,
                _attempt_record(
                    stage="reviewer",
                    round_index=round_index,
                    stage_attempt_index=reviewer_attempt_index,
                    input_feedback=reviewer_feedback,
                    messages=reviewer_messages,
                    outcome="reviewer_declined",
                    failure_summary=feedback,
                    output_root=output_root,
                    receipt=reviewer_receipt,
                    no_progress_fuse_triggered=fuse_triggered,
                ),
                output_root=output_root,
            )
            if fuse_triggered:
                raise SystemPlanProspectiveAtomError("；".join(feedback))
            break
        if not technical_review_succeeded:
            raise SystemPlanProspectiveAtomError(
                "独立 Qwen 审查在同一作者候选上的三次技术重试全部失败；"
                f"最后问题：{list(reviewer_feedback)}"
            )
        if final_portfolio is not None:
            break
    if final_portfolio is None or final_review is None:
        raise SystemPlanProspectiveAtomError(
            f"系统未能在 {max_rounds} 轮内产生通过独立审查的前瞻组件；"
            f"最终反馈：{list(feedback)}"
        )
    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "system-plan-prospective-atom-artifact-v1",
        "lineage_id": lineage_id,
        "literature_survey": literature_survey.model_dump(mode="json"),
        "feasibility_envelope": feasibility_envelope.model_dump(mode="json"),
        "observed_component_binding": observed_component_binding.model_dump(mode="json"),
        "method_skill_selection": method_skill_selection.model_dump(mode="json"),
        "interface_contract": interface_contract.model_dump(mode="json"),
        "target_aliases": [item.model_dump(mode="json") for item in target_aliases],
        "context": context.model_dump(mode="json"),
        "attempt_manifest": [item.model_dump(mode="json") for item in attempt_manifest],
        "rounds": [item.model_dump(mode="json") for item in completed_rounds],
        "final_portfolio": final_portfolio.model_dump(mode="json"),
        "final_review": final_review.model_dump(mode="json"),
        "authored_by_main_qwen": True,
        "independently_reviewed_by_qwen": True,
        "reasoning_required": True,
        "reasoning_is_evidence": False,
        "hand_written_scientific_prose_count": 0,
        "is_scientific_evidence": False,
        "innovation_verified": False,
        "execution_authorized": False,
        "approval_granted": False,
        "release_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["attempt_manifest_hash"] = canonical_model_hash(
        {"attempt_manifest": payload["attempt_manifest"]}
    )
    payload["artifact_hash"] = canonical_model_hash(payload)
    output_path = output_root / _OUTPUT_NAME
    payload["output_path"] = output_path.as_posix()
    artifact = SystemPlanProspectiveAtomArtifact.model_validate(payload)
    _write_immutable(output_path, artifact)
    return artifact


__all__ = [
    "AnonymousEvidenceFact",
    "AnonymousTargetEvidence",
    "ComponentExperimentBindingV2",
    "ProspectiveAtomBinding",
    "ProspectiveAtomContext",
    "ProspectiveAtomReview",
    "ProspectiveInterventionIdentity",
    "ProspectiveModelAttempt",
    "ProspectiveAtomPortfolio",
    "ProspectiveAtomReviewPortfolio",
    "ProspectiveAtomRound",
    "ProspectiveComponentAtom",
    "ProspectiveExecutionInterfaceContract",
    "ProspectiveLiteratureSupport",
    "ProspectivePriorWorkComparison",
    "ProspectiveResourceRequest",
    "ProspectiveTargetAliasBinding",
    "SelectedAbstractEvidence",
    "SystemPlanProspectiveAtomArtifact",
    "SystemPlanProspectiveAtomError",
    "build_component_experiment_binding",
    "build_prospective_atom_context",
    "build_prospective_execution_interface_contract",
    "prospective_atom_portfolio_findings",
    "prospective_atom_review_findings",
    "run_system_plan_prospective_atoms",
]
