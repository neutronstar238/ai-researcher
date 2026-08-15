"""Qwen-authored atomic component catalog bound to complete source clauses.

The cross-lineage matrix proves only jointly-confounded candidate effects.  This
module therefore does not infer components in Python.  It mechanically exposes
complete, exact clauses from every signed ``selected_candidate_summary``; the
current-stage main Qwen authors atomic component records and an independent Qwen
reviews every record.  Accepted output remains non-evidence and execution-disabled.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    ResearchFeasibilityEnvelope,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_OUTPUT_NAME = "system-plan-component-atoms.json"
_MIN_REASONING_CHARACTERS = 200
_THINKING_BUDGET = 4_000
_MAX_ROUNDS = 3
_SCOPE_CONTEXT_SEPARATOR = re.compile(
    r"(?:[\r\n。！？!?；;，,:：]+|\.(?=\s|$))",
    flags=re.IGNORECASE,
)
_COMPONENT_CANDIDATE_SEPARATOR = re.compile(
    r"\s+(?:and|with)\s+",
    flags=re.IGNORECASE,
)
_PDE_SCOPE = re.compile(
    r"(?<![A-Za-z0-9_])pdes?(?![A-Za-z0-9_])|partial\s+differential\s+"
    r"equations?|spatial\s+derivatives?|空间导数|空间微分|偏微分方程",
    flags=re.IGNORECASE,
)
_ODE_SCOPE = re.compile(
    r"(?<![A-Za-z0-9_])odes?(?![A-Za-z0-9_])|ordinary\s+differential\s+"
    r"equations?|常微分方程",
    flags=re.IGNORECASE,
)
_FORBIDDEN_IDENTIFIER_ONLY = frozenset(
    {"pde", "pdes", "ode", "odes", "and", "with", "偏微分方程", "常微分方程"}
)


class SystemPlanComponentAtomError(RuntimeError):
    """Raised when component atom authorship or review cannot be proved."""


class ComponentSourceSummary(StrictFrozenModel):
    """One complete selected-candidate summary copied from the signed matrix."""

    source_lineage_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    source_summary: str = Field(min_length=1)
    source_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_hash(self) -> ComponentSourceSummary:
        if self.source_summary_sha256 != _text_sha256(self.source_summary):
            raise SystemPlanComponentAtomError("候选摘要原文哈希不符")
        return self


class ComponentSourceClause(StrictFrozenModel):
    """One exact, non-rewritten provenance segment from a candidate summary."""

    source_clause_id: str = Field(pattern=r"^SC[0-9]{3}$")
    source_lineage_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    source_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_clause: str = Field(min_length=2)
    source_clause_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_context: str = Field(min_length=2)
    scope_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    explicit_data_types: tuple[Literal["ode", "pde"], ...]

    @model_validator(mode="after")
    def _validate_clause(self) -> ComponentSourceClause:
        if self.source_clause != self.source_clause.strip():
            raise SystemPlanComponentAtomError("组件来源分句不得包含首尾空白")
        if self.source_clause_sha256 != _text_sha256(self.source_clause):
            raise SystemPlanComponentAtomError("组件来源分句哈希不符")
        if self.scope_context != self.scope_context.strip():
            raise SystemPlanComponentAtomError("组件来源范围上下文不得包含首尾空白")
        if self.scope_context_sha256 != _text_sha256(self.scope_context):
            raise SystemPlanComponentAtomError("组件来源范围上下文哈希不符")
        if self.source_clause not in self.scope_context:
            raise SystemPlanComponentAtomError("组件来源分句不在范围上下文中")
        expected_scope = _explicit_data_types(self.scope_context)
        if self.explicit_data_types != expected_scope:
            raise SystemPlanComponentAtomError("组件来源分句的 PDE/ODE 范围不符")
        return self


class ComponentSourceClauseCatalog(StrictFrozenModel):
    """Complete deterministic clause inventory exposed to both Qwen roles."""

    schema_version: Literal["component-source-clause-catalog-v1"] = (
        "component-source-clause-catalog-v1"
    )
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cross_lineage_matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_summaries: tuple[ComponentSourceSummary, ...] = Field(min_length=2)
    source_clauses: tuple[ComponentSourceClause, ...] = Field(min_length=7)
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_catalog(self) -> ComponentSourceClauseCatalog:
        summary_by_lineage = {
            item.source_lineage_id: item for item in self.source_summaries
        }
        if len(summary_by_lineage) != len(self.source_summaries):
            raise SystemPlanComponentAtomError("组件来源摘要谱系不得重复")
        expected_ids = tuple(
            f"SC{index:03d}" for index in range(1, len(self.source_clauses) + 1)
        )
        if tuple(item.source_clause_id for item in self.source_clauses) != expected_ids:
            raise SystemPlanComponentAtomError("组件来源分句编号必须连续且顺序稳定")
        for clause in self.source_clauses:
            summary = summary_by_lineage.get(clause.source_lineage_id)
            if summary is None:
                raise SystemPlanComponentAtomError("组件来源分句引用未知摘要谱系")
            if (
                clause.selected_candidate_id != summary.selected_candidate_id
                or clause.source_summary_sha256 != summary.source_summary_sha256
                or clause.source_clause not in summary.source_summary
                or clause.scope_context not in summary.source_summary
            ):
                raise SystemPlanComponentAtomError("组件来源分句没有逐字绑定候选摘要")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"catalog_hash"})
        )
        if self.catalog_hash != expected_hash:
            raise SystemPlanComponentAtomError("组件来源分句目录哈希不符")
        return self


class SystemPlanComponentAtom(StrictFrozenModel):
    """One atomic component authored by the current-stage main Qwen."""

    atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    source_lineage_id: str = Field(min_length=1)
    source_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_clause_id: str = Field(pattern=r"^SC[0-9]{3}$")
    source_clause: str = Field(min_length=2)
    technical_identifier: str = Field(min_length=2, max_length=160)
    label_zh: str = Field(min_length=2, max_length=80)
    applicable_data_types: tuple[Literal["ode", "pde"], ...] = Field(
        min_length=1, max_length=2
    )
    rationale_zh: str = Field(min_length=30, max_length=800)

    @model_validator(mode="after")
    def _validate_atom(self) -> SystemPlanComponentAtom:
        for label, text in (
            ("来源完整分句", self.source_clause),
            ("技术标识", self.technical_identifier),
            ("中文名称", self.label_zh),
            ("中文理由", self.rationale_zh),
        ):
            if text != text.strip():
                raise SystemPlanComponentAtomError(f"{self.atom_id} 的{label}有首尾空白")
        if len(set(self.applicable_data_types)) != len(self.applicable_data_types):
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 的适用数据类型不得重复"
            )
        if tuple(sorted(self.applicable_data_types)) != self.applicable_data_types:
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 的适用数据类型必须按 ode、pde 稳定排序"
            )
        language_failures = (
            *non_chinese_prose_fields(
                {"label_zh": self.label_zh},
                exempt_identifiers=_technical_label_exemptions(
                    self.technical_identifier
                ),
            ),
            *non_chinese_prose_fields(
                {"rationale_zh": self.rationale_zh},
                exempt_identifiers=(self.technical_identifier,),
            ),
        )
        if language_failures:
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 的作者字段不是中文：{list(language_failures)}"
            )
        return self


class SystemPlanComponentAtomPortfolio(StrictFrozenModel):
    """Exactly seven source-bound atoms in exact main-Qwen order."""

    schema_version: Literal["system-plan-component-atom-portfolio-v1"] = (
        "system-plan-component-atom-portfolio-v1"
    )
    atoms: tuple[SystemPlanComponentAtom, ...] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def _validate_portfolio(self) -> SystemPlanComponentAtomPortfolio:
        expected_ids = tuple(f"A{index:03d}" for index in range(1, len(self.atoms) + 1))
        if tuple(item.atom_id for item in self.atoms) != expected_ids:
            raise SystemPlanComponentAtomError("原子组件编号必须从 A001 连续递增")
        clause_ids = tuple(item.source_clause_id for item in self.atoms)
        if len(set(clause_ids)) != len(clause_ids):
            raise SystemPlanComponentAtomError("每个完整来源分句最多生成一个原子组件")
        identifiers = tuple(item.technical_identifier.casefold() for item in self.atoms)
        if len(set(identifiers)) != len(identifiers):
            raise SystemPlanComponentAtomError("原子组件技术标识不得重复")
        return self


class SystemPlanComponentAtomReview(StrictFrozenModel):
    """Independent Qwen verdict for one exact atom hash."""

    atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    atom_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atomic: bool
    source_bound: bool
    scope_valid: bool
    accepted: bool
    findings_zh: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_review(self) -> SystemPlanComponentAtomReview:
        expected = self.atomic and self.source_bound and self.scope_valid
        if self.accepted != expected:
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 的 accepted 必须由三项审查布尔值机械合取"
            )
        if not self.accepted and not self.findings_zh:
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 审查未通过时必须给出中文 findings"
            )
        failures = non_chinese_prose_fields({"findings_zh": self.findings_zh})
        if failures:
            raise SystemPlanComponentAtomError(
                f"{self.atom_id} 的审查 findings 不是中文：{list(failures)}"
            )
        return self


class SystemPlanComponentAtomReviewPortfolio(StrictFrozenModel):
    """Reviewer output; coverage and order are checked against the author output."""

    schema_version: Literal["system-plan-component-atom-review-v1"] = (
        "system-plan-component-atom-review-v1"
    )
    reviews: tuple[SystemPlanComponentAtomReview, ...] = Field(min_length=1)


class SystemPlanComponentAtomRound(StrictFrozenModel):
    """One complete author/reviewer round and its immutable provider receipts."""

    round_index: int = Field(ge=1, le=_MAX_ROUNDS)
    author_feedback_zh: tuple[str, ...]
    author_portfolio: SystemPlanComponentAtomPortfolio
    author_receipt: ModelAuthorshipReceipt
    author_receipt_relative_path: str = Field(min_length=1)
    review_portfolio: SystemPlanComponentAtomReviewPortfolio
    reviewer_receipt: ModelAuthorshipReceipt
    reviewer_receipt_relative_path: str = Field(min_length=1)
    accepted: bool
    round_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_round(self) -> SystemPlanComponentAtomRound:
        expected_accepted = all(item.accepted for item in self.review_portfolio.reviews)
        if self.accepted != expected_accepted:
            raise SystemPlanComponentAtomError("原子组件轮次接受标记与逐项审查不一致")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"round_hash"})
        )
        if self.round_hash != expected_hash:
            raise SystemPlanComponentAtomError("原子组件轮次哈希不符")
        return self


class SystemPlanComponentAtomBinding(StrictFrozenModel):
    """Minimal immutable input passed to later main-agent routing."""

    schema_version: Literal["system-plan-component-atom-binding-v1"] = (
        "system-plan-component-atom-binding-v1"
    )
    component_atom_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_clause_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_skill_selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atoms: tuple[SystemPlanComponentAtom, ...] = Field(min_length=7)
    independent_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> SystemPlanComponentAtomBinding:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"binding_hash"})
        )
        if self.binding_hash != expected:
            raise SystemPlanComponentAtomError("原子组件绑定哈希不符")
        return self


class SystemPlanComponentAtomArtifact(StrictFrozenModel):
    """Accepted catalog, full retry trace, exact receipts, and safety boundaries."""

    schema_version: Literal["system-plan-component-atom-artifact-v1"] = (
        "system-plan-component-atom-artifact-v1"
    )
    lineage_id: str = Field(min_length=1)
    feasibility_envelope: ResearchFeasibilityEnvelope
    source_clause_catalog: ComponentSourceClauseCatalog
    method_skill_selection: SystemPlanMethodSkillSelectionBinding
    rounds: tuple[SystemPlanComponentAtomRound, ...] = Field(
        min_length=1,
        max_length=_MAX_ROUNDS,
    )
    final_portfolio: SystemPlanComponentAtomPortfolio
    final_review: SystemPlanComponentAtomReviewPortfolio
    authored_by_main_qwen: Literal[True] = True
    independently_reviewed_by_qwen: Literal[True] = True
    reasoning_required: Literal[True] = True
    reasoning_is_evidence: Literal[False] = False
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    approval_granted: Literal[False] = False
    release_authorized: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanComponentAtomArtifact:
        expected_catalog = build_system_plan_component_source_clause_catalog(
            self.feasibility_envelope
        )
        if self.source_clause_catalog != expected_catalog:
            raise SystemPlanComponentAtomError(
                "组件来源分句目录不是可行性边界的完整机械投影"
            )
        _validate_method_skill_binding(self.method_skill_selection)
        round_indices = tuple(item.round_index for item in self.rounds)
        if tuple(sorted(set(round_indices))) != round_indices:
            raise SystemPlanComponentAtomError("原子组件轮次编号必须唯一递增")
        output_root = Path(self.output_path).resolve().parent
        prior_review: SystemPlanComponentAtomReviewPortfolio | None = None
        for item in self.rounds:
            expected_feedback = (
                _review_retry_feedback(prior_review)
                if prior_review is not None
                else item.author_feedback_zh
            )
            if prior_review is not None and item.author_feedback_zh != expected_feedback:
                raise SystemPlanComponentAtomError("作者重试反馈未逐字来自上一轮独立审查")
            author_messages = _author_messages(
                catalog=self.source_clause_catalog,
                method_skill_selection=self.method_skill_selection,
                prior_feedback=item.author_feedback_zh,
            )
            _validate_receipt(
                item.author_receipt,
                artifact_kind="plan_opportunity_map",
                interaction_id=f"system-plan-component-atoms-author-{item.round_index:02d}",
                attempt=item.round_index,
                messages=author_messages,
                parsed_payload=item.author_portfolio.model_dump(mode="json"),
            )
            _validate_relative_receipt_path(
                output_root,
                item.author_receipt_relative_path,
                item.author_receipt,
            )
            author_findings = component_atom_portfolio_findings(
                portfolio=item.author_portfolio,
                catalog=self.source_clause_catalog,
            )
            if author_findings:
                raise SystemPlanComponentAtomError(
                    "已持久化作者组件未通过机械绑定：" + "；".join(author_findings)
                )
            reviewer_messages = _reviewer_messages(
                catalog=self.source_clause_catalog,
                portfolio=item.author_portfolio,
                method_skill_selection=self.method_skill_selection,
            )
            _validate_receipt(
                item.reviewer_receipt,
                artifact_kind="plan_opportunity_map_review",
                interaction_id=(
                    f"system-plan-component-atoms-reviewer-{item.round_index:02d}"
                ),
                attempt=item.round_index,
                messages=reviewer_messages,
                parsed_payload=item.review_portfolio.model_dump(mode="json"),
            )
            _validate_relative_receipt_path(
                output_root,
                item.reviewer_receipt_relative_path,
                item.reviewer_receipt,
            )
            if item.author_receipt.receipt_hash == item.reviewer_receipt.receipt_hash:
                raise SystemPlanComponentAtomError("作者与独立审查者不得共用同一回执")
            review_findings = component_atom_review_findings(
                review=item.review_portfolio,
                portfolio=item.author_portfolio,
            )
            if review_findings:
                raise SystemPlanComponentAtomError(
                    "独立审查未精确覆盖作者组件：" + "；".join(review_findings)
                )
            prior_review = item.review_portfolio
        if any(item.accepted for item in self.rounds[:-1]):
            raise SystemPlanComponentAtomError("已通过的轮次之后不得继续改写组件")
        final_round = self.rounds[-1]
        if (
            not final_round.accepted
            or self.final_portfolio != final_round.author_portfolio
            or self.final_review != final_round.review_portfolio
        ):
            raise SystemPlanComponentAtomError("最终组件与最后通过的作者—审查轮次不一致")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_hash:
            raise SystemPlanComponentAtomError("原子组件制品哈希不符")
        return self

    def binding(self) -> SystemPlanComponentAtomBinding:
        payload: dict[str, Any] = {
            "schema_version": "system-plan-component-atom-binding-v1",
            "component_atom_artifact_hash": self.artifact_hash,
            "feasibility_envelope_hash": self.feasibility_envelope.envelope_hash,
            "source_clause_catalog_hash": self.source_clause_catalog.catalog_hash,
            "method_skill_selection_artifact_hash": (
                self.method_skill_selection.selection_artifact_hash
            ),
            "atoms": [item.model_dump(mode="json") for item in self.final_portfolio.atoms],
            "independent_review_hash": canonical_model_hash(self.final_review),
            "is_scientific_evidence": False,
            "execution_authorized": False,
        }
        payload["binding_hash"] = canonical_model_hash(payload)
        return SystemPlanComponentAtomBinding.model_validate(payload)


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _technical_label_exemptions(identifier: str) -> tuple[str, ...]:
    """Return only machine-like tokens that may remain searchable in a Chinese label."""

    tokens = re.findall(
        r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_.+-]*(?![A-Za-z0-9_])",
        identifier,
    )
    return tuple(
        dict.fromkeys(
            token
            for token in tokens
            if any(char.isupper() for char in token)
            or any(char.isdigit() for char in token)
            or any(not char.isalpha() for char in token)
        )
    )


def _explicit_data_types(text: str) -> tuple[Literal["ode", "pde"], ...]:
    values: list[Literal["ode", "pde"]] = []
    if _ODE_SCOPE.search(text):
        values.append("ode")
    if _PDE_SCOPE.search(text):
        values.append("pde")
    return tuple(values)


def _matrix_from_envelope(
    envelope: ResearchFeasibilityEnvelope,
) -> CrossLineageSystemEffectMatrix:
    facts = tuple(
        item
        for item in envelope.evidence_facts
        if item.fact_kind == "cross_lineage_effect_matrix"
    )
    if len(facts) != 1:
        raise SystemPlanComponentAtomError("原子组件目录要求恰好一个跨谱系效果矩阵事实")
    try:
        return CrossLineageSystemEffectMatrix.model_validate(facts[0].value)
    except (ValidationError, RuntimeError, ValueError) as exc:
        raise SystemPlanComponentAtomError("跨谱系效果矩阵无效") from exc


def _split_exact_source_clauses(summary: str) -> tuple[tuple[str, str], ...]:
    scope_contexts: list[str] = []
    cursor = 0
    for separator in _SCOPE_CONTEXT_SEPARATOR.finditer(summary):
        context = summary[cursor : separator.start()].strip()
        if len(context) >= 2:
            scope_contexts.append(context)
        cursor = separator.end()
    tail = summary[cursor:].strip()
    if len(tail) >= 2:
        scope_contexts.append(tail)
    clauses: list[tuple[str, str]] = []
    for context in scope_contexts:
        component_cursor = 0
        for separator in _COMPONENT_CANDIDATE_SEPARATOR.finditer(context):
            clause = context[component_cursor : separator.start()].strip()
            if len(clause) >= 2:
                clauses.append((context, clause))
            component_cursor = separator.end()
        component_tail = context[component_cursor:].strip()
        if len(component_tail) >= 2:
            clauses.append((context, component_tail))
    return tuple(clauses)


def build_system_plan_component_source_clause_catalog(
    feasibility_envelope: ResearchFeasibilityEnvelope,
) -> ComponentSourceClauseCatalog:
    """Mechanically expose all exact summary clauses without choosing components."""

    matrix = _matrix_from_envelope(feasibility_envelope)
    summaries: list[ComponentSourceSummary] = []
    clauses: list[ComponentSourceClause] = []
    for candidate in matrix.candidates:
        summary_hash = _text_sha256(candidate.selected_candidate_summary)
        summaries.append(
            ComponentSourceSummary(
                source_lineage_id=candidate.lineage_id,
                selected_candidate_id=candidate.selected_candidate_id,
                source_summary=candidate.selected_candidate_summary,
                source_summary_sha256=summary_hash,
            )
        )
        for scope_context, source_clause in _split_exact_source_clauses(
            candidate.selected_candidate_summary
        ):
            clauses.append(
                ComponentSourceClause(
                    source_clause_id=f"SC{len(clauses) + 1:03d}",
                    source_lineage_id=candidate.lineage_id,
                    selected_candidate_id=candidate.selected_candidate_id,
                    source_summary_sha256=summary_hash,
                    source_clause=source_clause,
                    source_clause_sha256=_text_sha256(source_clause),
                    scope_context=scope_context,
                    scope_context_sha256=_text_sha256(scope_context),
                    explicit_data_types=_explicit_data_types(scope_context),
                )
            )
    if len(clauses) < 7:
        raise SystemPlanComponentAtomError(
            "签名候选摘要机械分句少于七条，不能要求主 Qwen 伪造七个原子组件"
        )
    payload: dict[str, Any] = {
        "schema_version": "component-source-clause-catalog-v1",
        "feasibility_envelope_hash": feasibility_envelope.envelope_hash,
        "cross_lineage_matrix_hash": matrix.matrix_hash,
        "source_summaries": [item.model_dump(mode="json") for item in summaries],
        "source_clauses": [item.model_dump(mode="json") for item in clauses],
    }
    payload["catalog_hash"] = canonical_model_hash(payload)
    return ComponentSourceClauseCatalog.model_validate(payload)


def _validate_method_skill_binding(
    binding: SystemPlanMethodSkillSelectionBinding,
) -> None:
    for skill in binding.selected_skills:
        if _text_sha256(skill.content) != skill.content_sha256:
            raise SystemPlanComponentAtomError(
                f"原子组件方法技能内容哈希不符：{skill.skill_id}"
            )


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
                "system_authored_skill_selection": binding.selection.model_dump(
                    mode="json"
                ),
                "selected_method_skills": [
                    item.model_dump(mode="json") for item in binding.selected_skills
                ],
                "use_boundary": (
                    "技能只约束原子化与审查方法，不是事实、科研结论或实验结果。"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def _author_messages(
    *,
    catalog: ComponentSourceClauseCatalog,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    prior_feedback: Sequence[str],
) -> list[dict[str, str]]:
    output_example = {
        "schema_version": "system-plan-component-atom-portfolio-v1",
        "atoms": [
            {
                "atom_id": "A001",
                "source_lineage_id": "逐字复制来源谱系",
                "source_summary_sha256": "逐字复制六十四位小写哈希",
                "source_clause_id": "SC001",
                "source_clause": "逐字复制完整来源分句",
                "technical_identifier": "来源分句中的连续技术标识",
                "label_zh": "中文原子组件名",
                "applicable_data_types": ["ode"],
                "rationale_zh": "至少三十字的中文原子化理由",
            }
        ],
    }
    instruction = (
        "你是当前研究阶段的主 Qwen。你只负责从签名候选摘要的完整来源分句中筛选并识别恰好"
        "七个"
        "原子组件，不得提出研究假设、机制结论、预期结果或实验计划。必须在"
        " reasoning_content 中逐项检查分句、技术标识、PDE/ODE 范围与方法技能，且至少"
        "二百字符；推理仅作过程审计，不是科学证据。source_lineage_id、"
        "source_summary_sha256、source_clause_id 和 source_clause 必须从用户给出的目录逐字"
        "复制；source_clause 必须复制完整分句，禁止截短以隐藏 and、with 或 PDE/ODE 范围。"
        "technical_identifier 必须是该完整分句中的大小写敏感连续子串，且必须指向组件本身，"
        "不能只写 PDE、ODE、and 或 with。目录是待筛选的候选分句清单，不是必须逐条覆盖的"
        "组件清单；不得为结果描述、重写声明、笼统稳定性目标、数据类型名称、连接词或只有"
        "‘正确处理’而没有可独立改变技术操作的分句建立 atom。优先选择技术操作最明确的七"
        "条，超过或少于七条都不合格。每个分句最多一个 atom；atom_id 从 A001 连续递增。"
        "若完整分句所属的 scope_context 显式或以空间导数等结构只限定 PDE/ODE，"
        "applicable_data_types 必须精确复制该范围；"
        "未显式写明时仍须明确给出待独立审查的适用类型。label_zh 与 rationale_zh 必须使用"
        "简体中文。只返回一个 JSON 值对象，严禁返回 JSON Schema、$defs、properties、"
        "字段说明或 Markdown。下面只是值骨架；按实际分句扩展 atoms，不得照抄占位文本："
        + json.dumps(
            output_example,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if prior_feedback:
        instruction += (
            "上一轮机械门禁或独立审查未通过。下列反馈是最低修复集而非穷尽清单；必须重新"
            "审计完整的七项组合，保留仍然有效的项，并删除或替换不构成原子技术操作的项。"
            "反馈里的 atom_id 指上一轮位置，不要求为修复它而继续保留同一来源分句："
        ) + json.dumps(
            list(prior_feedback),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return [
        {"role": "system", "content": instruction},
        _method_skill_context_message(method_skill_selection),
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "complete_signed_component_source_clauses",
                    "source_clause_catalog": catalog.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def _reviewer_messages(
    *,
    catalog: ComponentSourceClauseCatalog,
    portfolio: SystemPlanComponentAtomPortfolio,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
) -> list[dict[str, str]]:
    output_example = {
        "schema_version": "system-plan-component-atom-review-v1",
        "reviews": [
            {
                "atom_id": "A001",
                "atom_hash": "逐字复制六十四位小写哈希",
                "atomic": True,
                "source_bound": True,
                "scope_valid": True,
                "accepted": True,
                "findings_zh": [],
            }
        ],
    }
    instruction = (
        "你是独立的 Qwen 原子组件审查者，不得读取或复述作者的 reasoning_content。必须在你"
        "自己的 reasoning_content 中逐 atom 检查，至少二百字符；推理不是科学证据。按作者"
        " atoms 的原顺序逐项输出且不得遗漏、重排或篡改 atom_id/atom_hash。atomic 只有在完整"
        "来源分句只表达一个可独立改变的技术组件时才为真；用很短 technical_identifier 掩盖"
        "同一分句中的第二组件时必须判假。source_bound 检查完整分句、摘要哈希、技术标识逐字"
        "子串；scope_valid 必须检查 source_clause 所属的完整 scope_context（不是只看拆分后"
        "的短 source_clause）里显式 PDE/ODE 或空间导数等结构限定与适用类型。"
        "accepted 必须是三项"
        "布尔值合取；任一项为假必须给出至少一条具体简体中文 findings。只返回一个 JSON "
        "值对象，严禁返回 JSON Schema、$defs、properties、字段说明或 Markdown。下面只是值"
        "骨架；reviews 必须按实际作者 atoms 逐项完整填写，不得照抄占位哈希："
        + json.dumps(
            output_example,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    atom_payload = []
    for atom in portfolio.atoms:
        value = atom.model_dump(mode="json")
        value["atom_hash"] = canonical_model_hash(atom)
        atom_payload.append(value)
    return [
        {"role": "system", "content": instruction},
        _method_skill_context_message(method_skill_selection),
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "independent_component_atom_review",
                    "source_clause_catalog": catalog.model_dump(mode="json"),
                    "author_atoms_with_hashes": atom_payload,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def component_atom_portfolio_findings(
    *,
    portfolio: SystemPlanComponentAtomPortfolio,
    catalog: ComponentSourceClauseCatalog,
) -> tuple[str, ...]:
    """Return only deterministic provenance and explicit-scope failures."""

    findings: list[str] = []
    clauses = {item.source_clause_id: item for item in catalog.source_clauses}
    for atom in portfolio.atoms:
        clause = clauses.get(atom.source_clause_id)
        if clause is None:
            findings.append(f"{atom.atom_id} 引用未知完整来源分句")
            continue
        if atom.source_lineage_id != clause.source_lineage_id:
            findings.append(f"{atom.atom_id} 的来源谱系与完整分句不一致")
        if atom.source_summary_sha256 != clause.source_summary_sha256:
            findings.append(f"{atom.atom_id} 的候选摘要哈希与完整分句不一致")
        if atom.source_clause != clause.source_clause:
            findings.append(
                f"{atom.atom_id} 未逐字复制完整来源分句，可能截断复合组件或适用范围"
            )
        if atom.technical_identifier not in atom.source_clause:
            findings.append(f"{atom.atom_id} 的技术标识不是完整来源分句的逐字子串")
        if atom.technical_identifier.casefold() in _FORBIDDEN_IDENTIFIER_ONLY:
            findings.append(f"{atom.atom_id} 的技术标识只写了范围词或连接词")
        if clause.explicit_data_types and (
            atom.applicable_data_types != clause.explicit_data_types
        ):
            findings.append(
                f"{atom.atom_id} 隐藏或改写了完整分句中的显式 PDE/ODE 适用范围"
            )
    return tuple(findings)


def component_atom_review_findings(
    *,
    review: SystemPlanComponentAtomReviewPortfolio,
    portfolio: SystemPlanComponentAtomPortfolio,
) -> tuple[str, ...]:
    """Check exact reviewer coverage, order, and author-atom hashes."""

    findings: list[str] = []
    expected_ids = tuple(item.atom_id for item in portfolio.atoms)
    actual_ids = tuple(item.atom_id for item in review.reviews)
    if actual_ids != expected_ids:
        findings.append("独立审查的 atom 覆盖或顺序与作者输出不一致")
    expected_hashes = {
        item.atom_id: canonical_model_hash(item) for item in portfolio.atoms
    }
    for item in review.reviews:
        expected = expected_hashes.get(item.atom_id)
        if expected is None:
            findings.append(f"独立审查引用未知 atom：{item.atom_id}")
        elif item.atom_hash != expected:
            findings.append(f"独立审查篡改了 {item.atom_id} 的 atom_hash")
    return tuple(findings)


def _review_retry_feedback(
    review: SystemPlanComponentAtomReviewPortfolio,
) -> tuple[str, ...]:
    return tuple(
        f"{item.atom_id} 独立审查未通过：" + "；".join(item.findings_zh)
        for item in review.reviews
        if not item.accepted
    )


def _is_qwen_receipt(receipt: ModelAuthorshipReceipt) -> bool:
    return "qwen" in receipt.model_name.casefold()


def _validate_receipt(
    receipt: ModelAuthorshipReceipt,
    *,
    artifact_kind: Literal["plan_opportunity_map", "plan_opportunity_map_review"],
    interaction_id: str,
    attempt: int,
    messages: Sequence[Mapping[str, str]],
    parsed_payload: Mapping[str, Any],
) -> None:
    if (
        receipt.artifact_kind != artifact_kind
        or receipt.interaction_id != interaction_id
        or receipt.attempt != attempt
    ):
        raise SystemPlanComponentAtomError("原子组件模型回执身份或轮次不符")
    if receipt.messages != tuple(dict(item) for item in messages):
        raise SystemPlanComponentAtomError("原子组件模型回执消息不符")
    if receipt.parsed_payload != dict(parsed_payload):
        raise SystemPlanComponentAtomError("原子组件模型回执输出与制品不符")
    if not _is_qwen_receipt(receipt):
        raise SystemPlanComponentAtomError("原子组件作者与审查者必须是 Qwen")
    if len(str(receipt.reasoning_content or "").strip()) < _MIN_REASONING_CHARACTERS:
        raise SystemPlanComponentAtomError("Qwen 回执缺少至少二百字符 reasoning_content")
    if receipt.reasoning_transport != "dashscope_enable_thinking":
        raise SystemPlanComponentAtomError("Qwen 回执未证明 thinking 已开启")


def _validate_relative_receipt_path(
    output_root: Path,
    relative_path: str,
    receipt: ModelAuthorshipReceipt,
) -> None:
    resolved = (output_root / relative_path).resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise SystemPlanComponentAtomError("原子组件回执路径逃逸输出目录") from exc
    if resolved != Path(receipt.output_path).resolve():
        raise SystemPlanComponentAtomError("原子组件回执相对路径与回执输出路径不一致")


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


def _round_record(
    *,
    round_index: int,
    author_feedback: Sequence[str],
    author_portfolio: SystemPlanComponentAtomPortfolio,
    author_receipt: ModelAuthorshipReceipt,
    review_portfolio: SystemPlanComponentAtomReviewPortfolio,
    reviewer_receipt: ModelAuthorshipReceipt,
    output_root: Path,
) -> SystemPlanComponentAtomRound:
    payload: dict[str, Any] = {
        "round_index": round_index,
        "author_feedback_zh": list(author_feedback),
        "author_portfolio": author_portfolio.model_dump(mode="json"),
        "author_receipt": author_receipt.model_dump(mode="json"),
        "author_receipt_relative_path": Path(author_receipt.output_path)
        .resolve()
        .relative_to(output_root)
        .as_posix(),
        "review_portfolio": review_portfolio.model_dump(mode="json"),
        "reviewer_receipt": reviewer_receipt.model_dump(mode="json"),
        "reviewer_receipt_relative_path": Path(reviewer_receipt.output_path)
        .resolve()
        .relative_to(output_root)
        .as_posix(),
        "accepted": all(item.accepted for item in review_portfolio.reviews),
    }
    payload["round_hash"] = canonical_model_hash(payload)
    return SystemPlanComponentAtomRound.model_validate(payload)


def _write_immutable_artifact(
    path: Path,
    artifact: SystemPlanComponentAtomArtifact,
) -> None:
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
        existing = SystemPlanComponentAtomArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if existing != artifact:
            raise SystemPlanComponentAtomError(
                f"拒绝覆盖不同的原子组件不可变制品：{path}"
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


def run_system_plan_component_atom_catalog(
    *,
    lineage_id: str,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    output_dir: Path | str,
    author_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    reviewer_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_rounds: int = _MAX_ROUNDS,
    clock: datetime | None = None,
) -> SystemPlanComponentAtomArtifact:
    """Run at most three bounded author/reviewer attempts."""

    if max_rounds < 1 or max_rounds > _MAX_ROUNDS:
        raise SystemPlanComponentAtomError("原子组件作者—审查轮次必须在一至三轮之间")
    _validate_method_skill_binding(method_skill_selection)
    catalog = build_system_plan_component_source_clause_catalog(feasibility_envelope)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    feedback: tuple[str, ...] = ()
    completed_rounds: list[SystemPlanComponentAtomRound] = []
    final_portfolio: SystemPlanComponentAtomPortfolio | None = None
    final_review: SystemPlanComponentAtomReviewPortfolio | None = None
    for round_index in range(1, max_rounds + 1):
        author_feedback = feedback
        author_messages = _author_messages(
            catalog=catalog,
            method_skill_selection=method_skill_selection,
            prior_feedback=author_feedback,
        )
        try:
            author_result = _call_qwen(
                completion=author_completion,
                messages=author_messages,
                response_schema_name="system_plan_component_atoms_author",
                config_path=config_path,
                env_path=env_path,
                max_tokens=10_000,
                temperature=0.2,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            feedback = (
                "主 Qwen 原子化调用或 JSON 解析失败："
                f"{type(exc).__name__}: {exc}",
            )
            continue
        author_receipt = record_model_authorship_receipt(
            artifact_kind="plan_opportunity_map",
            interaction_id=f"system-plan-component-atoms-author-{round_index:02d}",
            attempt=round_index,
            messages=author_messages,
            completion=author_result,
            output_dir=output_root,
            clock=clock,
        )
        try:
            _validate_receipt(
                author_receipt,
                artifact_kind="plan_opportunity_map",
                interaction_id=(
                    f"system-plan-component-atoms-author-{round_index:02d}"
                ),
                attempt=round_index,
                messages=author_messages,
                parsed_payload=author_result.parsed_json,
            )
            author_portfolio = SystemPlanComponentAtomPortfolio.model_validate(
                author_result.parsed_json
            )
            author_findings = component_atom_portfolio_findings(
                portfolio=author_portfolio,
                catalog=catalog,
            )
        except (ValidationError, RuntimeError, ValueError) as exc:
            feedback = (f"主 Qwen 原子组件结构、中文或回执无效：{exc}",)
            continue
        if author_findings:
            feedback = author_findings
            continue
        reviewer_messages = _reviewer_messages(
            catalog=catalog,
            portfolio=author_portfolio,
            method_skill_selection=method_skill_selection,
        )
        try:
            reviewer_result = _call_qwen(
                completion=reviewer_completion,
                messages=reviewer_messages,
                response_schema_name="system_plan_component_atoms_reviewer",
                config_path=config_path,
                env_path=env_path,
                max_tokens=8_000,
                temperature=0.0,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            feedback = (
                "独立 Qwen 审查调用或 JSON 解析失败："
                f"{type(exc).__name__}: {exc}",
            )
            continue
        reviewer_receipt = record_model_authorship_receipt(
            artifact_kind="plan_opportunity_map_review",
            interaction_id=(
                f"system-plan-component-atoms-reviewer-{round_index:02d}"
            ),
            attempt=round_index,
            messages=reviewer_messages,
            completion=reviewer_result,
            output_dir=output_root,
            clock=clock,
        )
        try:
            _validate_receipt(
                reviewer_receipt,
                artifact_kind="plan_opportunity_map_review",
                interaction_id=(
                    f"system-plan-component-atoms-reviewer-{round_index:02d}"
                ),
                attempt=round_index,
                messages=reviewer_messages,
                parsed_payload=reviewer_result.parsed_json,
            )
            review_portfolio = SystemPlanComponentAtomReviewPortfolio.model_validate(
                reviewer_result.parsed_json
            )
            review_findings = component_atom_review_findings(
                review=review_portfolio,
                portfolio=author_portfolio,
            )
        except (ValidationError, RuntimeError, ValueError) as exc:
            feedback = (f"独立 Qwen 审查结构、中文或回执无效：{exc}",)
            continue
        if review_findings:
            feedback = review_findings
            continue
        record = _round_record(
            round_index=round_index,
            author_feedback=author_feedback,
            author_portfolio=author_portfolio,
            author_receipt=author_receipt,
            review_portfolio=review_portfolio,
            reviewer_receipt=reviewer_receipt,
            output_root=output_root,
        )
        completed_rounds.append(record)
        if record.accepted:
            final_portfolio = author_portfolio
            final_review = review_portfolio
            break
        feedback = _review_retry_feedback(review_portfolio)
    if final_portfolio is None or final_review is None:
        raise SystemPlanComponentAtomError(
            f"系统未能在 {max_rounds} 轮内产生通过独立审查的原子组件目录；最终反馈："
            f"{list(feedback)}"
        )
    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "system-plan-component-atom-artifact-v1",
        "lineage_id": lineage_id,
        "feasibility_envelope": feasibility_envelope.model_dump(mode="json"),
        "source_clause_catalog": catalog.model_dump(mode="json"),
        "method_skill_selection": method_skill_selection.model_dump(mode="json"),
        "rounds": [item.model_dump(mode="json") for item in completed_rounds],
        "final_portfolio": final_portfolio.model_dump(mode="json"),
        "final_review": final_review.model_dump(mode="json"),
        "authored_by_main_qwen": True,
        "independently_reviewed_by_qwen": True,
        "reasoning_required": True,
        "reasoning_is_evidence": False,
        "hand_written_scientific_prose_count": 0,
        "is_scientific_evidence": False,
        "execution_authorized": False,
        "approval_granted": False,
        "release_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    output_path = output_root / _OUTPUT_NAME
    payload["output_path"] = output_path.as_posix()
    artifact = SystemPlanComponentAtomArtifact.model_validate(payload)
    _write_immutable_artifact(output_path, artifact)
    return artifact
