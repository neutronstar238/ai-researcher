"""One independent scientific review of a final contest research plan.

The configured model authors every scientific assessment.  This sibling module only
verifies the frozen plan and exploratory-pilot evidence, prepares independent review
context, tolerantly projects one JSON response, and persists hash-bound JSON,
Markdown, raw-response, and provider-receipt artifacts.  It never rewrites the plan
or retries a response for formatting or scientific content.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from autoresearch.competition.contest_direct_plan import ContestDirectPlanArtifact
from autoresearch.competition.contest_direct_plan_render import (
    project_reference_for_display,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
)
from autoresearch.competition.contest_direction_memory import (
    normalize_optional_dreaming_context,
    optional_dreaming_context_hash,
    optional_dreaming_context_message,
)
from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    validate_locked_bibliography,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_SHA256 = r"^[0-9a-f]{64}$"
_JSON_ARTIFACT_NAME = "system-plan-scientific-review.json"
_MARKDOWN_ARTIFACT_NAME = "scientific-review.md"
_TEXT_EVIDENCE_ROLES = frozenset(
    {
        "environment",
        "metrics",
        "parameters",
        "stderr_log",
        "stdout_log",
    }
)
_TEXT_EVIDENCE_LIMIT = 128_000
_FINAL_PLAN_FIELDS = frozenset(ContestDirectPlanArtifact.model_fields)
_FINAL_REVISION_FIELDS = frozenset(ContestDirectPlanRevisionArtifact.model_fields)
_BRACKETED_REFERENCE_RE = re.compile(r"\[([0-9]+)\]")
_REVIEW_NATURAL_LANGUAGE_FIELDS = (
    "recommendation_text",
    "problem_restatement",
    "strongest_counterevidence",
    "summary",
    "hypothesis_evidence_assessment",
    "null_controls_assessment",
    "analysis_unit_assessment",
    "statistics_assessment",
    "overclaim_assessment",
    "reproducibility_assessment",
    "references_assessment",
    "strengths",
    "major_issues",
    "minor_issues",
)

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "recommendation": (
        "recommendation",
        "verdict",
        "decision",
        "overallrecommendation",
        "评审结论",
        "结论",
        "建议",
    ),
    "summary": (
        "summary",
        "summaryzh",
        "overallassessment",
        "总体评价",
        "评审摘要",
        "摘要",
    ),
    "problem_restatement": (
        "problemrestatement",
        "researchquestionrestatement",
        "restatedproblem",
        "问题重述",
        "研究问题重述",
    ),
    "strongest_counterevidence": (
        "strongestcounterevidence",
        "strongestcounterargument",
        "counterevidence",
        "strongestalternativeexplanation",
        "最强反证",
        "反证",
        "最强替代解释",
    ),
    "hypothesis_evidence_assessment": (
        "hypothesisevidenceassessment",
        "hypothesisevidencefit",
        "hypothesisandevidence",
        "假设证据",
        "假设与证据",
        "假设证据一致性",
    ),
    "null_controls_assessment": (
        "nullcontrolsassessment",
        "nullcontrols",
        "controlsassessment",
        "零模型与对照",
        "零模型",
        "对照设计",
    ),
    "analysis_unit_assessment": (
        "analysisunitassessment",
        "analysisunit",
        "unitofanalysis",
        "分析单位",
        "分析单元",
    ),
    "statistics_assessment": (
        "statisticsassessment",
        "statisticalassessment",
        "statistics",
        "统计评估",
        "统计方法",
        "统计",
    ),
    "overclaim_assessment": (
        "overclaimassessment",
        "claimscopeassessment",
        "overclaim",
        "过度外推",
        "过度声明",
        "结论边界",
    ),
    "reproducibility_assessment": (
        "reproducibilityassessment",
        "reproducibility",
        "replicability",
        "可复现性",
        "复现性",
    ),
    "references_assessment": (
        "referencesassessment",
        "referenceassessment",
        "literatureassessment",
        "参考文献评估",
        "文献评估",
        "参考文献",
    ),
    "strengths": ("strengths", "keystrengths", "优点", "优势", "主要优点"),
    "major_issues": (
        "majorissues",
        "majorcomments",
        "majorconcerns",
        "重大问题",
        "主要问题",
        "大修问题",
    ),
    "minor_issues": (
        "minorissues",
        "minorcomments",
        "minorconcerns",
        "次要问题",
        "小问题",
        "小修问题",
    ),
    "reference_indices": (
        "referenceindices",
        "referencesused",
        "citationindices",
        "引用编号",
        "参考文献编号",
    ),
}


class ContestDirectPlanScientificReviewError(RuntimeError):
    """Raised when one independent review cannot be verified or materialized."""


class ContestDirectScientificReviewContent(StrictFrozenModel):
    """Scientific content authored by the independent reviewer."""

    recommendation: Literal[
        "pass",
        "minor_revision",
        "major_revision",
        "reject",
        "unclear",
    ]
    recommendation_text: str = Field(min_length=1)
    problem_restatement: str = Field(min_length=1)
    strongest_counterevidence: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    hypothesis_evidence_assessment: str = Field(min_length=1)
    null_controls_assessment: str = Field(min_length=1)
    analysis_unit_assessment: str = Field(min_length=1)
    statistics_assessment: str = Field(min_length=1)
    overclaim_assessment: str = Field(min_length=1)
    reproducibility_assessment: str = Field(min_length=1)
    references_assessment: str = Field(min_length=1)
    strengths: tuple[str, ...] = ()
    major_issues: tuple[str, ...] = ()
    minor_issues: tuple[str, ...] = ()
    reference_indices: tuple[int, ...] = ()

    @field_validator(
        "recommendation_text",
        "problem_restatement",
        "strongest_counterevidence",
        "summary",
        "hypothesis_evidence_assessment",
        "null_controls_assessment",
        "analysis_unit_assessment",
        "statistics_assessment",
        "overclaim_assessment",
        "reproducibility_assessment",
        "references_assessment",
    )
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("scientific review fields must not be blank")
        return normalized

    @field_validator("strengths", "major_issues", "minor_issues")
    @classmethod
    def _strip_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))

    @field_validator("reference_indices")
    @classmethod
    def _deduplicate_reference_indices(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(dict.fromkeys(values))


class ContestDirectReviewEvidenceFile(StrictFrozenModel):
    """One preexperiment file whose exact bytes were verified before review."""

    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    text_supplied_to_model: bool


class ContestDirectPlanScientificReviewArtifact(StrictFrozenModel):
    """Hash-bound result of one independent, non-rewriting plan review."""

    schema_version: Literal["contest-direct-plan-scientific-review-v1"] = (
        "contest-direct-plan-scientific-review-v1"
    )
    document_type: Literal["最终研究计划独立科学评审"] = "最终研究计划独立科学评审"
    review_id: str = Field(pattern=r"^direct-plan-scientific-review-[0-9a-f]{16}$")
    status: Literal["completed_single_independent_scientific_review"] = (
        "completed_single_independent_scientific_review"
    )
    scientific_problem: str = Field(min_length=1)
    final_plan_id: str = Field(min_length=1)
    final_plan_source_kind: Literal[
        "direct_artifact",
        "revision_artifact",
        "materialized_final_plan",
    ]
    final_plan_artifact_hash: str = Field(pattern=_SHA256)
    final_plan_payload_sha256: str = Field(pattern=_SHA256)
    final_plan_source_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    preexperiment_artifact_hash: str = Field(pattern=_SHA256)
    preexperiment_artifact_payload_sha256: str = Field(pattern=_SHA256)
    preexperiment_metrics_payload_sha256: str = Field(pattern=_SHA256)
    verified_files: tuple[ContestDirectReviewEvidenceFile, ...] = Field(min_length=1)
    verified_files_sha256: str = Field(pattern=_SHA256)
    locked_reference_catalog: tuple[str, ...] = Field(min_length=1)
    locked_reference_catalog_sha256: str = Field(pattern=_SHA256)
    reference_catalog_binding_policy: Literal[
        "legacy-unverified-subset-v1",
        "locked-catalog-exact-order-v2",
    ] = "legacy-unverified-subset-v1"
    selected_skill_sha256: tuple[str, ...]
    review: ContestDirectScientificReviewContent
    mechanical_normalization_applied: bool
    reference_index_integrity_status: Literal[
        "verified_exact_union",
        "legacy_unverified_against_review_prose",
    ] = "legacy_unverified_against_review_prose"
    evidence_scope: Literal["exploratory_preexperiment"] = "exploratory_preexperiment"
    independence_scope: Literal["fresh_interaction_not_model_family_independence"] = (
        "fresh_interaction_not_model_family_independence"
    )
    formal_experiment_executed: Literal[False] = False
    paper_claimed: Literal[False] = False
    required_audit_findings_sha256: str | None = Field(default=None, pattern=_SHA256)
    derived_memory_context_sha256: str | None = Field(default=None, pattern=_SHA256)
    prior_audit_context_supplied: bool = False
    plan_rewrite_performed: Literal[False] = False
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    generation_calls: Literal[1] = 1
    input_hash: str = Field(pattern=_SHA256)
    model_response_hash: str = Field(pattern=_SHA256)
    raw_response_relative_path: str = Field(min_length=1)
    authorship_receipt_relative_path: str = Field(min_length=1)
    authorship_receipt_hash: str = Field(pattern=_SHA256)
    markdown_relative_path: str = Field(min_length=1)
    markdown_sha256: str = Field(pattern=_SHA256)
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_program_bindings(self) -> ContestDirectPlanScientificReviewArtifact:
        if self.review_id != f"direct-plan-scientific-review-{self.input_hash[:16]}":
            raise ValueError("review_id does not match the program input hash")
        expected_files_hash = canonical_model_hash(
            {"files": [item.model_dump(mode="json") for item in self.verified_files]}
        )
        if self.verified_files_sha256 != expected_files_hash:
            raise ValueError("verified preexperiment file binding hash mismatch")
        expected_catalog_hash = canonical_model_hash(
            {"references": list(self.locked_reference_catalog)}
        )
        if self.locked_reference_catalog_sha256 != expected_catalog_hash:
            raise ValueError("locked reference catalog hash mismatch")
        if self.prior_audit_context_supplied != bool(self.required_audit_findings_sha256):
            raise ValueError("required audit finding hash/context flag mismatch")
        if self.reference_index_integrity_status == "verified_exact_union":
            structured_indices = self.review.reference_indices
            if structured_indices != tuple(sorted(set(structured_indices))):
                raise ValueError("review reference indices are not unique and sorted")
            text_indices = _review_natural_language_reference_indices(self.review)
            all_indices = set(structured_indices) | set(text_indices)
            if any(
                index < 1 or index > len(self.locked_reference_catalog) for index in all_indices
            ):
                raise ValueError("review cited reference indices outside the locked catalog")
            if not set(text_indices).issubset(structured_indices):
                raise ValueError("review prose references are missing from reference_indices")
        artifact_payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        expected_artifact_hashes = {canonical_model_hash(artifact_payload)}
        optional_absent = [
            field
            for field, value in (
                ("required_audit_findings_sha256", self.required_audit_findings_sha256),
                ("derived_memory_context_sha256", self.derived_memory_context_sha256),
            )
            if value is None
        ]
        if "reference_index_integrity_status" not in self.model_fields_set:
            optional_absent.append("reference_index_integrity_status")
        if "reference_catalog_binding_policy" not in self.model_fields_set:
            optional_absent.append("reference_catalog_binding_policy")
        for mask in range(1, 1 << len(optional_absent)):
            legacy_payload = dict(artifact_payload)
            for index, field in enumerate(optional_absent):
                if mask & (1 << index):
                    legacy_payload.pop(field, None)
            expected_artifact_hashes.add(canonical_model_hash(legacy_payload))
        if self.artifact_hash not in expected_artifact_hashes:
            raise ValueError("scientific review artifact hash mismatch")
        return self


@dataclass(frozen=True)
class _FinalPlanProjection:
    plan_id: str
    source_kind: Literal[
        "direct_artifact",
        "revision_artifact",
        "materialized_final_plan",
    ]
    artifact_hash: str
    payload_sha256: str
    source_file_sha256: str | None
    scientific_problem: str
    scientific_plan: dict[str, Any]


@dataclass(frozen=True)
class _VerifiedPreexperiment:
    artifact: dict[str, Any]
    artifact_hash: str
    artifact_payload_sha256: str
    metrics: dict[str, Any]
    metrics_payload_sha256: str
    files: tuple[ContestDirectReviewEvidenceFile, ...]
    text_contents: dict[str, str]


def build_contest_direct_plan_scientific_review_messages(
    *,
    scientific_problem: str,
    final_plan_id: str,
    final_plan_source_kind: str,
    final_plan_artifact_hash: str,
    final_plan_payload_sha256: str,
    final_plan_source_file_sha256: str | None,
    final_scientific_plan: Mapping[str, Any],
    preexperiment_artifact: Mapping[str, Any],
    preexperiment_metrics: Mapping[str, Any],
    verified_files: Sequence[ContestDirectReviewEvidenceFile],
    verified_file_contents: Mapping[str, str],
    reference_catalog: Sequence[str | Mapping[str, Any]],
    selected_skill_contexts: Sequence[str | Mapping[str, Any]] = (),
    required_audit_findings: Sequence[str | Mapping[str, Any]] = (),
    derived_memory_context: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build a fresh review interaction with optional audit-checklist context."""

    problem = scientific_problem.strip()
    if not problem:
        raise ContestDirectPlanScientificReviewError("scientific problem is blank")
    references = _normalize_reference_catalog(reference_catalog)
    if not references:
        raise ContestDirectPlanScientificReviewError("reference catalog must not be empty")
    audit_findings = _normalize_required_audit_findings(required_audit_findings)
    audit_context_supplied = bool(audit_findings)
    system_content = (
        "你是独立科学评审员。只根据本次提供的研究题目、最终研究计划、"
        "已核验探索性预实验和锁定参考目录作出评审；不得假定或寻找任何"
        "先前审计结论。先自行重述研究问题并主动寻找最强反证或替代解释，"
        "再检查假设与证据"
        "的对应关系、零模型与对照、分析单位、统计解释、过度外推、可复现性"
        "和参考文献，明确区分重大"
        "问题与次要问题。探索性预实验不是确认性正式实验，也不是论文。"
        "对计划正文每个[N]附近的具体命题，必须逐条与同编号目录条目的题名、摘要和"
        "限定条件核对；主题相邻、较弱定量结果或条件命题不能支持更强的拓扑、因果或"
        "普适结论。关键命题不受支持或仅部分支持时不得通过。"
        "评审可以通过、建议小修、大修或拒绝，但不得替作者重写研究计划。"
        "不要输出隐藏思考过程，只输出最终 JSON。"
    )
    if audit_context_supplied:
        system_content = (
            "你是独立科学评审员。当前仍是一次全新的独立交互，不继承任何未提供的"
            "过往评审或审计结论。只根据本次提供的研究题目、最终研究计划、已核验"
            "探索性预实验、锁定参考目录和单独提供的红队审计清单作出评审。红队清单"
            "是必须独立核验的检查线索，不是预设结论；请实质评估这些线索，但不需要"
            "逐字复述程序使用的 finding_id。先自行重述研究问题并主动寻找最强反证或"
            "替代解释，再检查假设与证据的对应关系、零模型与对照、分析单位、统计"
            "解释、过度外推、可复现性和参考文献，明确区分重大问题与次要问题。对计划"
            "正文每个[N]附近的具体命题，必须逐条与同编号目录条目的题名、摘要和限定"
            "条件核对；主题相邻、较弱定量结果或条件命题不能支持更强的拓扑、因果或"
            "普适结论。关键命题不受支持或仅部分支持时不得通过。探索"
            "性预实验不是确认性正式实验，也不是论文。评审可以通过、建议小修、大修"
            "或拒绝，但不得替作者重写研究计划。不要输出隐藏思考过程，只输出最终"
            "JSON。"
        )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "original_scientific_question_and_review_requirements",
                    "scientific_problem": problem,
                    "requirements_zh": [
                        "独立重述研究问题并寻找最强反证或替代解释",
                        "评审假设—证据、零模型、分析单位、统计、外推、复现和引用",
                        "区分重大问题与次要问题，不改写研究计划",
                        "探索性预实验不是正式实验，当前没有论文",
                    ],
                    "independence_boundary": {
                        "prior_review_context_supplied": False,
                        "prior_audit_context_supplied": audit_context_supplied,
                        "scope": "fresh_interaction_not_model_family_independence",
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "locked_real_reference_catalog",
                    "locked_reference_catalog": [
                        {"catalog_index": index, "citation": citation}
                        for index, citation in enumerate(references, start=1)
                    ],
                    "reference_boundary_zh": (
                        "本目录的顺序和编号是不可变的引用身份空间。只能使用本目录评价"
                        "引用充分性；如需指代文献，只返回目录编号，不得新增、重排或猜测"
                        "目录外文献。"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "verified_exploratory_preexperiment_evidence",
                    "study_phase": "exploratory_preexperiment",
                    "formal_experiment_executed": False,
                    "paper_claimed": False,
                    "artifact": dict(preexperiment_artifact),
                    "metrics": dict(preexperiment_metrics),
                    "verified_files": [
                        {
                            **item.model_dump(mode="json"),
                            "verified_text": verified_file_contents.get(item.path),
                        }
                        for item in verified_files
                    ],
                    "evidence_boundary_zh": (
                        "文件路径、字节数和 SHA-256 由程序验证；只有 verified_text 非空"
                        "的文件正文实际提供给评审器，其余文件只提供绑定，不得声称已逐行阅读。"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "final_research_plan_for_independent_review",
                    "final_plan_id": final_plan_id,
                    "final_plan_source_kind": final_plan_source_kind,
                    "final_plan_artifact_hash": final_plan_artifact_hash,
                    "final_plan_payload_sha256": final_plan_payload_sha256,
                    "final_plan_source_file_sha256": final_plan_source_file_sha256,
                    "scientific_plan": dict(final_scientific_plan),
                    "boundary_zh": "只评审，不改写计划。",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    for ordinal, skill in enumerate(selected_skill_contexts, start=1):
        content, name = _skill_content(skill, ordinal=ordinal)
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "system_selected_project_method_skill",
                        "skill_ordinal": ordinal,
                        "skill_name": name,
                        "content": content,
                        "content_sha256": _text_hash(content),
                        "boundary_zh": (
                            "该 Skill 仅提供学科方法论和优秀研究路径，不是事实、文献、"
                            "实验结果、先前审计结论或指定评审结论。"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if audit_findings:
        findings_hash = _required_audit_findings_hash(audit_findings)
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "required_red_team_audit_findings",
                        "required_audit_findings": list(audit_findings),
                        "required_audit_findings_sha256": findings_hash,
                        "boundary_zh": (
                            "这是本次全新独立评审必须逐项核验的审计检查线索，不是"
                            "必须接受的既定结论。finding_id 只用于程序绑定；请用自然"
                            "中文作出实质评估，不需要逐字复述 ID。"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    memory_context = normalize_optional_dreaming_context(
        dict(derived_memory_context) if derived_memory_context is not None else None
    )
    if memory_context is not None:
        messages.append(optional_dreaming_context_message(memory_context))
    contract_instructions = [
        "recommendation 明确写通过、小修、大修或拒绝",
        "先用自己的话重述研究问题，再给出最强反证或替代解释",
        "major_issues 与 minor_issues 分开；没有某级问题时返回空数组",
        "每项问题说明为何影响可信度及可执行的修正方向，但不要代写计划",
        "真实观察只来自已核验证据；不同零模型回答不同科学问题",
        (
            "将创新主张与锁定目录中最相邻工作作实质比较，核查具体差异、迁移或改造的"
            "方法/基线及最强反证；没有足够相邻工作时列为major issue并保持创新性未核实，"
            "不得用高被引或泛相关文献替代"
        ),
        "明确探索性预实验、正式实验未执行、论文未形成",
        "reference_indices 只使用锁定目录编号",
        "只调用一次；直接输出一个 JSON object，不输出附加说明",
        (
            "references_assessment 必须覆盖最终计划正文实际使用的每个[N]：逐项写明计划"
            "归因的具体命题、锁定条目明确支持到什么程度，以及 supported/partial/"
            "unsupported 判断；所有这些编号也必须列入 reference_indices"
        ),
        (
            "若核心假设、创新性或方法正当性的关键归因是 partial/unsupported，"
            "recommendation 必须为 major_revision 或 reject；非关键错误至少 minor_revision"
        ),
    ]
    if audit_findings:
        contract_instructions.append(
            "逐项独立核验红队审计清单并自由组织中文评估；finding_id 不属于输出格式要求"
        )
    contract_payload: dict[str, Any] = {
        "context_kind": "single_independent_scientific_review_contract",
        "output_language": "中文为主，技术名与真实论文题名可保留原文",
        "required_fields": [
            "recommendation",
            "problem_restatement",
            "strongest_counterevidence",
            "summary",
            "hypothesis_evidence_assessment",
            "null_controls_assessment",
            "analysis_unit_assessment",
            "statistics_assessment",
            "overclaim_assessment",
            "reproducibility_assessment",
            "references_assessment",
            "strengths",
            "major_issues",
            "minor_issues",
            "reference_indices",
        ],
        "instructions_zh": contract_instructions,
    }
    if audit_findings:
        contract_payload["required_audit_finding_ids"] = [
            item["finding_id"] for item in audit_findings
        ]
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                contract_payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    return messages


def review_contest_direct_plan_science(
    *,
    final_plan: ContestDirectPlanRevisionArtifact
    | ContestDirectPlanArtifact
    | BaseModel
    | Mapping[str, Any]
    | Path
    | str,
    preexperiment_artifact: BaseModel | Mapping[str, Any] | Path | str,
    reference_catalog: Sequence[str | Mapping[str, Any]],
    selected_skill_contexts: Sequence[str | Mapping[str, Any]] = (),
    required_audit_findings: Sequence[str | Mapping[str, Any]] = (),
    derived_memory_context: Mapping[str, Any] | None = None,
    preexperiment_metrics: BaseModel | Mapping[str, Any] | Path | str | None = None,
    evidence_file_bindings: Sequence[Mapping[str, Any]] = (),
    preexperiment_root: Path | str | None = None,
    output_dir: Path | str,
    output_path: Path | str | None = None,
    markdown_output_path: Path | str | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = 900,
    max_tokens: int | None = 8_000,
    temperature: float = 0.2,
    require_exact_reference_catalog: bool = False,
    llm_call: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
) -> ContestDirectPlanScientificReviewArtifact:
    """Perform exactly one configured-model review and never rewrite the plan."""

    final = _load_final_plan(final_plan)
    references = _normalize_reference_catalog(reference_catalog)
    if not references:
        raise ContestDirectPlanScientificReviewError("reference catalog must not be empty")
    if require_exact_reference_catalog:
        plan_references = final.scientific_plan.get("references")
        if not isinstance(plan_references, Sequence) or isinstance(
            plan_references, str | bytes | bytearray
        ):
            raise ContestDirectPlanScientificReviewError("final plan references are not a sequence")
        try:
            normalized_plan_references = tuple(str(item).strip() for item in plan_references)
            if final.source_kind == "materialized_final_plan":
                locked_references = references[:MAX_RESEARCH_PLAN_REFERENCES]
                validate_locked_bibliography(
                    locked_references,
                    references,
                    minimum=min(MIN_RESEARCH_PLAN_REFERENCES, len(references)),
                    maximum=MAX_RESEARCH_PLAN_REFERENCES,
                    require_exact_catalog=True,
                )
                expected_display_references = tuple(
                    project_reference_for_display(item) for item in locked_references
                )
                if normalized_plan_references != expected_display_references:
                    raise ValueError(
                        "materialized bibliography differs from the deterministic locked-catalog "
                        "display projection"
                    )
            else:
                validate_locked_bibliography(
                    normalized_plan_references,
                    references,
                    minimum=min(MIN_RESEARCH_PLAN_REFERENCES, len(references)),
                    maximum=MAX_RESEARCH_PLAN_REFERENCES,
                    require_exact_catalog=True,
                )
        except ValueError as exc:
            raise ContestDirectPlanScientificReviewError(
                f"final plan does not preserve the locked reference identity/order: {exc}"
            ) from exc
    plan_reference_indices = _mapping_natural_language_reference_indices(final.scientific_plan)
    out_of_catalog = tuple(
        index for index in plan_reference_indices if index < 1 or index > len(references)
    )
    if out_of_catalog:
        raise ContestDirectPlanScientificReviewError(
            f"final plan cites reference indices outside the locked catalog: {out_of_catalog}"
        )
    audit_findings = _normalize_required_audit_findings(required_audit_findings)
    audit_findings_hash = _required_audit_findings_hash(audit_findings) if audit_findings else None
    memory_context = normalize_optional_dreaming_context(
        dict(derived_memory_context) if derived_memory_context is not None else None
    )
    memory_context_hash = optional_dreaming_context_hash(memory_context)
    pilot = _verify_preexperiment(
        preexperiment_artifact,
        metrics_source=preexperiment_metrics,
        evidence_file_bindings=evidence_file_bindings,
        explicit_root=preexperiment_root,
    )
    skill_hashes = tuple(
        _text_hash(_skill_content(skill, ordinal=index)[0])
        for index, skill in enumerate(selected_skill_contexts, start=1)
    )
    verified_files_hash = canonical_model_hash(
        {"files": [item.model_dump(mode="json") for item in pilot.files]}
    )
    catalog_hash = canonical_model_hash({"references": list(references)})
    input_payload = {
        "scientific_problem": final.scientific_problem,
        "final_plan_id": final.plan_id,
        "final_plan_source_kind": final.source_kind,
        "final_plan_artifact_hash": final.artifact_hash,
        "final_plan_payload_sha256": final.payload_sha256,
        "final_plan_source_file_sha256": final.source_file_sha256,
        "preexperiment_artifact_hash": pilot.artifact_hash,
        "preexperiment_artifact_payload_sha256": pilot.artifact_payload_sha256,
        "preexperiment_metrics_payload_sha256": pilot.metrics_payload_sha256,
        "verified_files_sha256": verified_files_hash,
        "locked_reference_catalog_sha256": catalog_hash,
        "reference_catalog_binding_policy": (
            "locked-catalog-exact-order-v2"
            if require_exact_reference_catalog
            else "legacy-unverified-subset-v1"
        ),
        "selected_skill_sha256": list(skill_hashes),
        "independence": {
            "prior_audit_context_supplied": bool(audit_findings),
            "prior_review_context_supplied": False,
        },
    }
    if audit_findings_hash is not None:
        input_payload["required_audit_findings_sha256"] = audit_findings_hash
    if memory_context_hash is not None:
        input_payload["derived_memory_context_sha256"] = memory_context_hash
    input_hash = canonical_model_hash(input_payload)
    messages = build_contest_direct_plan_scientific_review_messages(
        scientific_problem=final.scientific_problem,
        final_plan_id=final.plan_id,
        final_plan_source_kind=final.source_kind,
        final_plan_artifact_hash=final.artifact_hash,
        final_plan_payload_sha256=final.payload_sha256,
        final_plan_source_file_sha256=final.source_file_sha256,
        final_scientific_plan=final.scientific_plan,
        preexperiment_artifact=pilot.artifact,
        preexperiment_metrics=pilot.metrics,
        verified_files=pilot.files,
        verified_file_contents=pilot.text_contents,
        reference_catalog=references,
        selected_skill_contexts=selected_skill_contexts,
        required_audit_findings=audit_findings,
        derived_memory_context=memory_context,
    )
    completion = llm_call(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        # The review artifact needs a complete, visible JSON object.  Hidden
        # reasoning can consume the provider output budget and leave an
        # otherwise sound review as a truncated JSON string, so keep this
        # one-shot, non-rewriting review on the visible channel.
        thinking_mode="disabled",
        thinking_budget=None,
        response_schema=_review_response_schema(),
        response_schema_name="contest_direct_plan_scientific_review",
    )

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    review_id = f"direct-plan-scientific-review-{input_hash[:16]}"
    response_hash = _text_hash(completion.response_text)
    interaction_id = f"{review_id}-{response_hash[:12]}"
    response_path = root / "responses" / f"{interaction_id}.txt"
    _write_immutable_bytes(response_path, completion.response_text.encode("utf-8"))
    receipt = record_model_authorship_receipt(
        artifact_kind="plan_critical_review",
        interaction_id=interaction_id,
        attempt=1,
        messages=messages,
        completion=completion,
        output_dir=root,
    )
    receipt_path = Path(receipt.output_path).resolve()

    try:
        review, normalized = _normalize_and_validate_review_content(
            completion.parsed_json,
            catalog_size=len(references),
        )
    except ValidationError as exc:
        raise ContestDirectPlanScientificReviewError(
            f"one-shot reviewer response omitted required scientific assessments: {exc}"
        ) from exc
    reviewed_claim_indices = {
        int(match) for match in _BRACKETED_REFERENCE_RE.findall(review.references_assessment)
    }
    missing_claim_checks = tuple(
        index for index in plan_reference_indices if index not in reviewed_claim_indices
    )
    if missing_claim_checks:
        raise ContestDirectPlanScientificReviewError(
            "one-shot reviewer omitted claim-level source checks for plan citations: "
            f"{missing_claim_checks}"
        )
    json_path = _root_level_output_path(root, output_path, _JSON_ARTIFACT_NAME)
    markdown_path = _inside_output_path(
        root,
        markdown_output_path,
        _MARKDOWN_ARTIFACT_NAME,
    )
    markdown = _render_review_markdown(
        review_id=review_id,
        scientific_problem=final.scientific_problem,
        review=review,
        input_hash=input_hash,
        response_hash=response_hash,
        evidence_file_count=len(pilot.files),
        required_audit_findings_sha256=audit_findings_hash,
    )
    markdown_bytes = markdown.encode("utf-8")
    _write_immutable_bytes(markdown_path, markdown_bytes)

    payload: dict[str, Any] = {
        "schema_version": "contest-direct-plan-scientific-review-v1",
        "document_type": "最终研究计划独立科学评审",
        "review_id": review_id,
        "status": "completed_single_independent_scientific_review",
        "scientific_problem": final.scientific_problem,
        "final_plan_id": final.plan_id,
        "final_plan_source_kind": final.source_kind,
        "final_plan_artifact_hash": final.artifact_hash,
        "final_plan_payload_sha256": final.payload_sha256,
        "final_plan_source_file_sha256": final.source_file_sha256,
        "preexperiment_artifact_hash": pilot.artifact_hash,
        "preexperiment_artifact_payload_sha256": pilot.artifact_payload_sha256,
        "preexperiment_metrics_payload_sha256": pilot.metrics_payload_sha256,
        "verified_files": [item.model_dump(mode="json") for item in pilot.files],
        "verified_files_sha256": verified_files_hash,
        "locked_reference_catalog": list(references),
        "locked_reference_catalog_sha256": catalog_hash,
        "reference_catalog_binding_policy": (
            "locked-catalog-exact-order-v2"
            if require_exact_reference_catalog
            else "legacy-unverified-subset-v1"
        ),
        "selected_skill_sha256": list(skill_hashes),
        "review": review.model_dump(mode="json"),
        "mechanical_normalization_applied": normalized != completion.parsed_json,
        "reference_index_integrity_status": "verified_exact_union",
        "evidence_scope": "exploratory_preexperiment",
        "independence_scope": "fresh_interaction_not_model_family_independence",
        "formal_experiment_executed": False,
        "paper_claimed": False,
        "prior_audit_context_supplied": bool(audit_findings),
        "plan_rewrite_performed": False,
        "authored_by_model": True,
        "hand_written_scientific_prose_count": 0,
        "is_scientific_evidence": False,
        "execution_authorized": False,
        "provider": completion.provider,
        "model_name": completion.model_name,
        "generation_calls": 1,
        "input_hash": input_hash,
        "model_response_hash": response_hash,
        "raw_response_relative_path": response_path.relative_to(root).as_posix(),
        "authorship_receipt_relative_path": receipt_path.relative_to(root).as_posix(),
        "authorship_receipt_hash": receipt.receipt_hash,
        "markdown_relative_path": markdown_path.relative_to(root).as_posix(),
        "markdown_sha256": _bytes_hash(markdown_bytes),
    }
    if audit_findings_hash is not None:
        payload["required_audit_findings_sha256"] = audit_findings_hash
    if memory_context_hash is not None:
        payload["derived_memory_context_sha256"] = memory_context_hash
    payload["artifact_hash"] = canonical_model_hash(payload)
    artifact = ContestDirectPlanScientificReviewArtifact.model_validate(payload)
    artifact_payload = artifact.model_dump(mode="json")
    if artifact.required_audit_findings_sha256 is None:
        artifact_payload.pop("required_audit_findings_sha256", None)
    _write_immutable_bytes(json_path, _json_bytes(artifact_payload))
    return artifact


def load_contest_direct_plan_scientific_review(
    path: Path | str,
    *,
    verify_files: bool = True,
) -> ContestDirectPlanScientificReviewArtifact:
    """Load a review and optionally re-hash its Markdown, response, and receipt."""

    artifact_path = Path(path).expanduser().resolve()
    try:
        artifact = ContestDirectPlanScientificReviewArtifact.model_validate_json(
            artifact_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ContestDirectPlanScientificReviewError(
            f"scientific review artifact is invalid: {artifact_path}"
        ) from exc
    if not verify_files:
        return artifact
    root = artifact_path.parent
    response_path = _resolve_artifact_relative_path(
        root,
        artifact.raw_response_relative_path,
    )
    markdown_path = _resolve_artifact_relative_path(root, artifact.markdown_relative_path)
    receipt_path = _resolve_artifact_relative_path(
        root,
        artifact.authorship_receipt_relative_path,
    )
    if _file_hash(response_path) != artifact.model_response_hash:
        raise ContestDirectPlanScientificReviewError("retained reviewer response hash mismatch")
    if _file_hash(markdown_path) != artifact.markdown_sha256:
        raise ContestDirectPlanScientificReviewError("scientific review Markdown hash mismatch")
    try:
        receipt = ModelAuthorshipReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ContestDirectPlanScientificReviewError("authorship receipt is invalid") from exc
    if receipt.receipt_hash != artifact.authorship_receipt_hash:
        raise ContestDirectPlanScientificReviewError("authorship receipt hash mismatch")
    if receipt.response_sha256 != artifact.model_response_hash:
        raise ContestDirectPlanScientificReviewError("authorship receipt response binding mismatch")
    if receipt.artifact_kind != "plan_critical_review":
        raise ContestDirectPlanScientificReviewError("authorship receipt kind mismatch")
    if artifact.reference_index_integrity_status == "verified_exact_union":
        try:
            expected_review, expected_normalized = _normalize_and_validate_review_content(
                receipt.parsed_payload,
                catalog_size=len(artifact.locked_reference_catalog),
            )
        except (ContestDirectPlanScientificReviewError, ValidationError) as exc:
            raise ContestDirectPlanScientificReviewError(
                "retained authorship receipt cannot reproduce review reference normalization"
            ) from exc
        if expected_review != artifact.review:
            raise ContestDirectPlanScientificReviewError(
                "review reference normalization differs from the retained authorship receipt"
            )
        expected_mechanical_normalization = expected_normalized != receipt.parsed_payload
        if expected_mechanical_normalization != artifact.mechanical_normalization_applied:
            raise ContestDirectPlanScientificReviewError(
                "review mechanical-normalization flag differs from the authorship receipt"
            )
        expected_markdown = _render_review_markdown(
            review_id=artifact.review_id,
            scientific_problem=artifact.scientific_problem,
            review=artifact.review,
            input_hash=artifact.input_hash,
            response_hash=artifact.model_response_hash,
            evidence_file_count=len(artifact.verified_files),
            required_audit_findings_sha256=artifact.required_audit_findings_sha256,
        ).encode("utf-8")
        if markdown_path.read_bytes() != expected_markdown:
            raise ContestDirectPlanScientificReviewError(
                "scientific review Markdown does not match the normalized review artifact"
            )
        if artifact.markdown_sha256 != _bytes_hash(expected_markdown):
            raise ContestDirectPlanScientificReviewError(
                "scientific review Markdown hash does not match normalized content"
            )
    return artifact


def _load_final_plan(
    source: ContestDirectPlanRevisionArtifact
    | ContestDirectPlanArtifact
    | BaseModel
    | Mapping[str, Any]
    | Path
    | str,
) -> _FinalPlanProjection:
    payload, source_path = _load_mapping(source, label="final plan")
    source_file_sha256 = _file_hash(source_path) if source_path is not None else None
    schema_version = str(payload.get("schema_version", ""))
    if schema_version == "contest-direct-plan-revision-v1":
        projected = {key: payload[key] for key in _FINAL_REVISION_FIELDS if key in payload}
        try:
            revision_model = ContestDirectPlanRevisionArtifact.model_validate(projected)
        except ValidationError as exc:
            raise ContestDirectPlanScientificReviewError(
                "final revised plan artifact is invalid"
            ) from exc
        return _FinalPlanProjection(
            plan_id=revision_model.revision_id,
            source_kind="revision_artifact",
            artifact_hash=revision_model.artifact_hash,
            payload_sha256=canonical_model_hash(revision_model.model_dump(mode="json")),
            source_file_sha256=source_file_sha256,
            scientific_problem=revision_model.scientific_problem.strip(),
            scientific_plan=revision_model.plan.model_dump(mode="json"),
        )
    if schema_version == "contest-direct-research-plan-v1":
        projected = {key: payload[key] for key in _FINAL_PLAN_FIELDS if key in payload}
        try:
            plan_model = ContestDirectPlanArtifact.model_validate(projected)
        except ValidationError as exc:
            raise ContestDirectPlanScientificReviewError(
                "final direct plan artifact is invalid"
            ) from exc
        return _FinalPlanProjection(
            plan_id=plan_model.plan_id,
            source_kind="direct_artifact",
            artifact_hash=plan_model.artifact_hash,
            payload_sha256=canonical_model_hash(plan_model.model_dump(mode="json")),
            source_file_sha256=source_file_sha256,
            scientific_problem=plan_model.scientific_problem.strip(),
            scientific_plan=plan_model.plan.model_dump(mode="json"),
        )
    if _looks_like_materialized_final_plan(payload):
        payload_hash = canonical_model_hash(payload)
        question = payload.get("question")
        question_zh = question.get("question_zh") if isinstance(question, Mapping) else None
        problem_statement = _required_materialized_text(payload, "problem_statement")
        scientific_problem = str(question_zh).strip() if question_zh else problem_statement
        datasets = payload.get("datasets")
        experiments = payload.get("experiments")
        assert isinstance(datasets, Mapping)
        assert isinstance(experiments, Mapping)
        references = payload.get("references")
        assert isinstance(references, Sequence) and not isinstance(
            references, str | bytes | bytearray
        )
        scientific_plan = {
            "problem_statement": problem_statement,
            "rationale": _required_materialized_text(payload, "rationale"),
            "technical_details": _required_materialized_text(payload, "technical_details"),
            "datasets": _required_nested_text(datasets, "description", owner="datasets"),
            "source": _required_nested_text(datasets, "source", owner="datasets"),
            "target": _required_nested_text(datasets, "target", owner="datasets"),
            "paper_title": _required_materialized_text(payload, "title"),
            "paper_abstract": _required_materialized_text(payload, "abstract"),
            "methods": _required_materialized_text(payload, "methods"),
            "experiments": _required_nested_text(experiments, "steps", owner="experiments"),
            "baselines": _required_nested_text(
                experiments,
                "baselines",
                owner="experiments",
            ),
            "metrics": _required_nested_text(experiments, "metrics", owner="experiments"),
            "results": _required_materialized_text(payload, "results"),
            "references": [str(item).strip() for item in references if str(item).strip()],
        }
        if not scientific_plan["references"]:
            raise ContestDirectPlanScientificReviewError(
                "materialized final plan has no references"
            )
        return _FinalPlanProjection(
            plan_id=f"materialized-final-plan-{payload_hash[:16]}",
            source_kind="materialized_final_plan",
            artifact_hash=payload_hash,
            payload_sha256=payload_hash,
            source_file_sha256=source_file_sha256,
            scientific_problem=scientific_problem,
            scientific_plan=scientific_plan,
        )
    raise ContestDirectPlanScientificReviewError(
        "final plan must be a complete direct/revised artifact or materialized research-plan.json"
    )


def _looks_like_materialized_final_plan(payload: Mapping[str, Any]) -> bool:
    required = {
        "abstract",
        "datasets",
        "experiments",
        "methods",
        "problem_statement",
        "rationale",
        "references",
        "results",
        "technical_details",
        "title",
    }
    return (
        required.issubset(payload)
        and isinstance(payload.get("datasets"), Mapping)
        and isinstance(payload.get("experiments"), Mapping)
    )


def _required_materialized_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContestDirectPlanScientificReviewError(
            f"materialized final plan field is blank: {field}"
        )
    return value.strip()


def _required_nested_text(payload: Mapping[str, Any], field: str, *, owner: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContestDirectPlanScientificReviewError(
            f"materialized final plan field is blank: {owner}.{field}"
        )
    return value.strip()


def _verify_preexperiment(
    source: BaseModel | Mapping[str, Any] | Path | str,
    *,
    metrics_source: BaseModel | Mapping[str, Any] | Path | str | None,
    evidence_file_bindings: Sequence[Mapping[str, Any]],
    explicit_root: Path | str | None,
) -> _VerifiedPreexperiment:
    artifact, artifact_path = _load_mapping(source, label="preexperiment artifact")
    expected_artifact_hash = artifact.get("artifact_hash")
    if not isinstance(expected_artifact_hash, str) or not re.fullmatch(
        _SHA256, expected_artifact_hash
    ):
        raise ContestDirectPlanScientificReviewError(
            "preexperiment artifact has no valid artifact_hash"
        )
    computed_artifact_hash = canonical_model_hash(
        {key: value for key, value in artifact.items() if key != "artifact_hash"}
    )
    if computed_artifact_hash != expected_artifact_hash:
        raise ContestDirectPlanScientificReviewError("preexperiment artifact hash mismatch")
    if artifact.get("status") != "completed":
        raise ContestDirectPlanScientificReviewError("preexperiment is not completed")
    if artifact.get("study_phase") != "exploratory_pilot":
        raise ContestDirectPlanScientificReviewError(
            "preexperiment is not marked exploratory_pilot"
        )
    if artifact.get("formal_experiment_executed") not in (None, False):
        raise ContestDirectPlanScientificReviewError(
            "review module accepts exploratory evidence only"
        )
    if artifact.get("mathematical_proof_claimed") not in (None, False):
        raise ContestDirectPlanScientificReviewError(
            "preexperiment artifact improperly claims a mathematical proof"
        )
    root = (
        Path(explicit_root).expanduser().resolve()
        if explicit_root is not None
        else artifact_path.parent.resolve()
        if artifact_path is not None
        else None
    )
    if root is None or not root.is_dir():
        raise ContestDirectPlanScientificReviewError(
            "preexperiment_root is required for in-memory artifact verification"
        )

    manifest_path = _artifact_bound_path(
        artifact,
        root=root,
        path_field="manifest_relative_path",
        hash_field="manifest_sha256",
        label="manifest",
    )
    manifest, _ = _load_mapping(manifest_path, label="preexperiment manifest")
    if manifest.get("program_status") != "completed":
        raise ContestDirectPlanScientificReviewError("preexperiment manifest is not completed")
    manifest_hash = manifest.get("manifest_hash")
    if isinstance(manifest_hash, str):
        expected_manifest_hash = canonical_model_hash(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        if manifest_hash != expected_manifest_hash:
            raise ContestDirectPlanScientificReviewError(
                "preexperiment manifest canonical hash mismatch"
            )
        artifact_manifest_hash = artifact.get("manifest_hash")
        if artifact_manifest_hash is not None and artifact_manifest_hash != manifest_hash:
            raise ContestDirectPlanScientificReviewError(
                "artifact and manifest canonical hashes disagree"
            )

    metrics_path = _artifact_bound_path(
        artifact,
        root=root,
        path_field="metrics_relative_path",
        hash_field="metrics_sha256",
        label="metrics",
    )
    metrics, _ = _load_mapping(metrics_path, label="preexperiment metrics")
    if metrics_source is not None:
        supplied_metrics, supplied_path = _load_mapping(
            metrics_source,
            label="supplied preexperiment metrics",
        )
        if canonical_model_hash(supplied_metrics) != canonical_model_hash(metrics):
            raise ContestDirectPlanScientificReviewError(
                "supplied preexperiment metrics differ from artifact-bound metrics"
            )
        if supplied_path is not None and _file_hash(supplied_path) != _file_hash(metrics_path):
            raise ContestDirectPlanScientificReviewError(
                "supplied preexperiment metrics bytes differ from artifact binding"
            )

    entries = _evidence_entries(artifact, manifest)
    verified: dict[Path, ContestDirectReviewEvidenceFile] = {}
    text_contents: dict[str, str] = {}
    for entry in entries:
        _verify_evidence_entry(
            entry,
            root=root,
            verified=verified,
            text_contents=text_contents,
        )
    _add_verified_file(
        path=manifest_path,
        role="manifest",
        expected_hash=str(artifact["manifest_sha256"]),
        expected_size=None,
        verified=verified,
        text_contents=text_contents,
    )
    for binding in evidence_file_bindings:
        path_value = binding.get("path", binding.get("relative_path"))
        sha_value = binding.get("sha256")
        role = str(binding.get("role", binding.get("kind", "evidence"))).strip()
        if not isinstance(path_value, str | Path) or not isinstance(sha_value, str):
            raise ContestDirectPlanScientificReviewError(
                "evidence file binding requires path and sha256"
            )
        path = _resolve_evidence_path(path_value, root=root)
        _add_verified_file(
            path=path,
            role=role or "evidence",
            expected_hash=sha_value,
            expected_size=_optional_int(binding.get("bytes", binding.get("size_bytes"))),
            verified=verified,
            text_contents=text_contents,
        )
    files = tuple(sorted(verified.values(), key=lambda item: (item.path, item.role)))
    if not files:
        raise ContestDirectPlanScientificReviewError(
            "preexperiment verification produced no evidence files"
        )
    return _VerifiedPreexperiment(
        artifact=artifact,
        artifact_hash=expected_artifact_hash,
        artifact_payload_sha256=canonical_model_hash(artifact),
        metrics=metrics,
        metrics_payload_sha256=canonical_model_hash(metrics),
        files=files,
        text_contents=text_contents,
    )


def _evidence_entries(
    artifact: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    collected: list[Mapping[str, Any]] = []
    for owner, field in ((artifact, "evidence_files"), (manifest, "files")):
        value = owner.get(field)
        if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
            raise ContestDirectPlanScientificReviewError(f"preexperiment {field} must be a list")
        for item in value:
            if not isinstance(item, Mapping):
                raise ContestDirectPlanScientificReviewError(
                    f"preexperiment {field} contains a non-object entry"
                )
            collected.append(item)
    return tuple(collected)


def _verify_evidence_entry(
    entry: Mapping[str, Any],
    *,
    root: Path,
    verified: dict[Path, ContestDirectReviewEvidenceFile],
    text_contents: dict[str, str],
) -> None:
    relative = entry.get("relative_path", entry.get("path"))
    sha256 = entry.get("sha256")
    role = str(entry.get("kind", entry.get("role", "evidence"))).strip()
    if not isinstance(relative, str | Path) or not isinstance(sha256, str):
        raise ContestDirectPlanScientificReviewError(
            "preexperiment evidence entry requires relative_path and sha256"
        )
    _add_verified_file(
        path=_resolve_evidence_path(relative, root=root),
        role=role or "evidence",
        expected_hash=sha256,
        expected_size=_optional_int(entry.get("bytes", entry.get("size_bytes"))),
        verified=verified,
        text_contents=text_contents,
    )


def _add_verified_file(
    *,
    path: Path,
    role: str,
    expected_hash: str,
    expected_size: int | None,
    verified: dict[Path, ContestDirectReviewEvidenceFile],
    text_contents: dict[str, str],
) -> None:
    if not re.fullmatch(_SHA256, expected_hash):
        raise ContestDirectPlanScientificReviewError(f"evidence file has invalid SHA-256: {path}")
    if not path.is_file():
        raise ContestDirectPlanScientificReviewError(f"evidence file is missing: {path}")
    actual_hash = _file_hash(path)
    if actual_hash != expected_hash:
        raise ContestDirectPlanScientificReviewError(f"evidence file hash mismatch: {path}")
    size = path.stat().st_size
    if expected_size is not None and size != expected_size:
        raise ContestDirectPlanScientificReviewError(f"evidence file size mismatch: {path}")
    supplied = role in _TEXT_EVIDENCE_ROLES and size <= _TEXT_EVIDENCE_LIMIT
    candidate = ContestDirectReviewEvidenceFile(
        role=role,
        path=path.as_posix(),
        sha256=actual_hash,
        size_bytes=size,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        text_supplied_to_model=supplied,
    )
    existing = verified.get(path)
    if existing is not None:
        if existing.sha256 != candidate.sha256 or existing.size_bytes != candidate.size_bytes:
            raise ContestDirectPlanScientificReviewError(
                f"conflicting evidence bindings for {path}"
            )
        if supplied and not existing.text_supplied_to_model:
            verified[path] = candidate
    else:
        verified[path] = candidate
    if supplied:
        try:
            text_contents[path.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            verified[path] = candidate.model_copy(update={"text_supplied_to_model": False})
            text_contents.pop(path.as_posix(), None)


def _artifact_bound_path(
    artifact: Mapping[str, Any],
    *,
    root: Path,
    path_field: str,
    hash_field: str,
    label: str,
) -> Path:
    relative = artifact.get(path_field)
    expected_hash = artifact.get(hash_field)
    if not isinstance(relative, str) or not isinstance(expected_hash, str):
        raise ContestDirectPlanScientificReviewError(
            f"preexperiment artifact does not bind {label} path/hash"
        )
    path = _resolve_evidence_path(relative, root=root)
    if not path.is_file() or _file_hash(path) != expected_hash:
        raise ContestDirectPlanScientificReviewError(f"{label} file hash mismatch")
    return path


def _load_mapping(
    source: BaseModel | Mapping[str, Any] | Path | str,
    *,
    label: str,
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, BaseModel):
        return dict(source.model_dump(mode="json")), None
    if isinstance(source, Mapping):
        return dict(source), None
    if isinstance(source, Path):
        path = source.expanduser().resolve()
        return _read_json_mapping(path, label=label), path
    value = str(source).strip()
    if value.startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContestDirectPlanScientificReviewError(f"{label} JSON is invalid") from exc
        if not isinstance(payload, Mapping):
            raise ContestDirectPlanScientificReviewError(f"{label} must be a JSON object")
        return dict(payload), None
    path = Path(value).expanduser().resolve()
    return _read_json_mapping(path, label=label), path


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectPlanScientificReviewError(f"{label} file is invalid: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ContestDirectPlanScientificReviewError(f"{label} must contain a JSON object")
    return dict(payload)


def _normalize_reference_catalog(
    values: Sequence[str | Mapping[str, Any]],
) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            candidate = value.get("citation", value.get("reference", value.get("title", "")))
        else:
            candidate = value
        text = str(candidate).strip()
        if text:
            normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _normalize_required_audit_findings(
    values: Sequence[str | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ordinal, value in enumerate(values, start=1):
        if isinstance(value, str):
            finding_text = value.strip()
            if not finding_text:
                raise ContestDirectPlanScientificReviewError(
                    f"required audit finding {ordinal} is blank"
                )
            finding_id = _audit_finding_id_from_text(finding_text)
            candidate: dict[str, Any] = {"finding": finding_text}
        elif isinstance(value, Mapping):
            candidate = _normalize_audit_finding_mapping(value, ordinal=ordinal)
            finding_id = _audit_finding_id_from_mapping(candidate)
        else:
            raise ContestDirectPlanScientificReviewError(
                f"required audit finding {ordinal} must be text or an object"
            )
        if finding_id is None:
            finding_id = _next_generated_audit_finding_id(ordinal, seen_ids)
        finding_id = finding_id.strip()
        if (
            not finding_id
            or len(finding_id) > 128
            or any(character.isspace() for character in finding_id)
        ):
            raise ContestDirectPlanScientificReviewError(
                f"required audit finding {ordinal} has an invalid finding_id"
            )
        identity = finding_id.casefold()
        if identity in seen_ids:
            raise ContestDirectPlanScientificReviewError(
                f"duplicate required audit finding_id: {finding_id}"
            )
        seen_ids.add(identity)
        candidate = {
            "finding_id": finding_id,
            **{
                key: item
                for key, item in candidate.items()
                if _normalize_key(key) not in {"findingid", "auditfindingid"}
                and _normalize_key(key) not in {"id", "编号", "审计项编号", "发现编号"}
            },
        }
        normalized.append(candidate)
    return tuple(sorted(normalized, key=lambda item: str(item["finding_id"]).casefold()))


def _normalize_audit_finding_mapping(
    value: Mapping[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        key_text = str(key).strip()
        if not key_text:
            raise ContestDirectPlanScientificReviewError(
                f"required audit finding {ordinal} has a blank field name"
            )
        normalized[key_text] = _normalize_audit_json_value(
            item,
            label=f"required audit finding {ordinal}.{key_text}",
        )
    return normalized


def _normalize_audit_json_value(value: Any, *, label: str) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return {
            str(key).strip(): _normalize_audit_json_value(
                item,
                label=f"{label}.{str(key).strip()}",
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).strip()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            _normalize_audit_json_value(item, label=f"{label}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ContestDirectPlanScientificReviewError(
        f"{label} contains a non-JSON value of type {type(value).__name__}"
    )


def _audit_finding_id_from_mapping(value: Mapping[str, Any]) -> str | None:
    aliases = {"findingid", "auditfindingid", "id", "编号", "审计项编号", "发现编号"}
    for key, item in value.items():
        if _normalize_key(str(key)) in aliases:
            finding_id = str(item).strip()
            return finding_id or None
    return None


def _audit_finding_id_from_text(value: str) -> str | None:
    match = re.match(
        r"^\s*[\[(]?([A-Za-z][A-Za-z0-9_.:]*-\d{1,8})[\])]?(?=\s|[:：—]|$)",
        value,
    )
    return match.group(1) if match else None


def _next_generated_audit_finding_id(ordinal: int, seen_ids: set[str]) -> str:
    candidate_number = ordinal
    while True:
        candidate = f"RT-{candidate_number:02d}"
        if candidate.casefold() not in seen_ids:
            return candidate
        candidate_number += 1


def _required_audit_findings_hash(findings: Sequence[Mapping[str, Any]]) -> str:
    return canonical_model_hash({"required_audit_findings": [dict(item) for item in findings]})


def _skill_content(
    value: str | Mapping[str, Any],
    *,
    ordinal: int,
) -> tuple[str, str]:
    if isinstance(value, Mapping):
        content = str(value.get("content", value.get("skill_content", ""))).strip()
        name = str(value.get("name", value.get("skill_name", f"skill-{ordinal}"))).strip()
    else:
        content = str(value).strip()
        name = f"selected-skill-{ordinal}"
    if not content:
        raise ContestDirectPlanScientificReviewError(f"selected Skill {ordinal} has no content")
    return content, name or f"selected-skill-{ordinal}"


def _normalize_review_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(payload)
    for key in ("review", "assessment", "scientific_review", "评审"):
        nested = root.get(key)
        if isinstance(nested, Mapping):
            root = {**root, **dict(nested)}
    for key in ("assessments", "dimensions", "专项评估", "分项评估"):
        nested = root.get(key)
        if isinstance(nested, Mapping):
            root = {**root, **dict(nested)}
    lookup = {_normalize_key(str(key)): value for key, value in root.items()}

    def find(field: str) -> Any:
        for alias in _FIELD_ALIASES[field]:
            key = _normalize_key(alias)
            if key in lookup:
                return lookup[key]
        return None

    recommendation_value = find("recommendation")
    recommendation_text = _as_text(recommendation_value)
    normalized: dict[str, Any] = {
        "recommendation": _recommendation_category(recommendation_text),
        "recommendation_text": recommendation_text,
    }
    for field in (
        "problem_restatement",
        "strongest_counterevidence",
        "summary",
        "hypothesis_evidence_assessment",
        "null_controls_assessment",
        "analysis_unit_assessment",
        "statistics_assessment",
        "overclaim_assessment",
        "reproducibility_assessment",
        "references_assessment",
    ):
        normalized[field] = _as_text(find(field))
    for field in ("strengths", "major_issues", "minor_issues"):
        normalized[field] = list(_as_items(find(field)))
    normalized["reference_indices"] = list(_as_reference_indices(find("reference_indices")))
    return normalized


def _normalize_and_validate_review_content(
    payload: Mapping[str, Any],
    *,
    catalog_size: int,
) -> tuple[ContestDirectScientificReviewContent, dict[str, Any]]:
    normalized = _normalize_review_payload(payload)
    review = ContestDirectScientificReviewContent.model_validate(normalized)
    text_indices = _review_natural_language_reference_indices(review)
    exact_union = tuple(sorted(set(review.reference_indices) | set(text_indices)))
    out_of_catalog = tuple(index for index in exact_union if index < 1 or index > catalog_size)
    if out_of_catalog:
        raise ContestDirectPlanScientificReviewError(
            f"review cited reference indices outside the locked catalog: {out_of_catalog}"
        )
    normalized["reference_indices"] = list(exact_union)
    return ContestDirectScientificReviewContent.model_validate(normalized), normalized


def _review_natural_language_reference_indices(
    review: ContestDirectScientificReviewContent,
) -> tuple[int, ...]:
    selected: set[int] = set()
    for field in _REVIEW_NATURAL_LANGUAGE_FIELDS:
        value = getattr(review, field)
        strings = value if isinstance(value, tuple) else (value,)
        for text in strings:
            selected.update(int(match) for match in _BRACKETED_REFERENCE_RE.findall(text))
    return tuple(sorted(selected))


def _mapping_natural_language_reference_indices(value: Mapping[str, Any]) -> tuple[int, ...]:
    """Collect citation markers from plan prose without scanning its bibliography."""

    selected: set[int] = set()

    def visit(node: Any, *, owner: str | None = None) -> None:
        if owner == "references":
            return
        if isinstance(node, str):
            selected.update(int(match) for match in _BRACKETED_REFERENCE_RE.findall(node))
            return
        if isinstance(node, Mapping):
            for key, child in node.items():
                visit(child, owner=str(key))
            return
        if isinstance(node, Sequence) and not isinstance(node, str | bytes | bytearray):
            for child in node:
                visit(child, owner=owner)

    visit(value)
    return tuple(sorted(selected))


def _normalize_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        parts = [_as_text(item) for item in value.values()]
        return "；".join(part for part in parts if part)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        parts = [_as_text(item) for item in value]
        return "；".join(part for part in parts if part)
    return str(value).strip()


def _as_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Mapping):
        if any(
            _normalize_key(str(key))
            in {"title", "issue", "concern", "evidence", "action", "问题", "依据", "建议"}
            for key in value
        ):
            text = _as_text(value)
            return (text,) if text else ()
        return tuple(item for item in (_as_text(child) for child in value.values()) if item)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(item for item in (_as_text(child) for child in value) if item)
    text = _as_text(value)
    return (text,) if text else ()


def _as_reference_indices(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    values: Sequence[Any]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values = value
    else:
        values = (value,)
    selected: list[int] = []
    for item in values:
        if isinstance(item, Mapping):
            item = item.get("reference_index", item.get("index", item.get("编号")))
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            selected.append(item)
            continue
        for match in re.findall(r"\d+", str(item)):
            selected.append(int(match))
    return tuple(dict.fromkeys(selected))


def _recommendation_category(value: str) -> str:
    normalized = _normalize_key(value)
    if any(marker in normalized for marker in ("reject", "拒绝", "不通过")):
        return "reject"
    if any(marker in normalized for marker in ("majorrevision", "大修", "重大修改")):
        return "major_revision"
    if any(marker in normalized for marker in ("minorrevision", "小修", "轻微修改")):
        return "minor_revision"
    if any(marker in normalized for marker in ("pass", "accept", "通过", "接受")):
        return "pass"
    return "unclear"


def _review_response_schema() -> dict[str, Any]:
    text_fields = {
        field: {"type": "string"}
        for field in (
            "recommendation",
            "problem_restatement",
            "strongest_counterevidence",
            "summary",
            "hypothesis_evidence_assessment",
            "null_controls_assessment",
            "analysis_unit_assessment",
            "statistics_assessment",
            "overclaim_assessment",
            "reproducibility_assessment",
            "references_assessment",
        )
    }
    return {
        "type": "object",
        "properties": {
            **text_fields,
            "strengths": {"type": "array", "items": {"type": "string"}},
            "major_issues": {"type": "array", "items": {"type": "string"}},
            "minor_issues": {"type": "array", "items": {"type": "string"}},
            "reference_indices": {"type": "array", "items": {"type": "integer"}},
        },
        "required": list(text_fields),
        "additionalProperties": True,
    }


def _render_review_markdown(
    *,
    review_id: str,
    scientific_problem: str,
    review: ContestDirectScientificReviewContent,
    input_hash: str,
    response_hash: str,
    evidence_file_count: int,
    required_audit_findings_sha256: str | None = None,
) -> str:
    audit_context_line = (
        "- 输入过往评审或审计结论：否"
        if required_audit_findings_sha256 is None
        else "- 提供必审红队审计清单：是（作为待独立核验线索，并非预设结论）"
    )
    sections = [
        "# 最终研究计划独立科学评审",
        "",
        f"- 评审 ID：`{review_id}`",
        f"- 科学问题：{scientific_problem}",
        "- 证据阶段：探索性预实验",
        "- 正式实验已执行：否",
        "- 已形成论文：否",
        audit_context_line,
        *(
            [f"- 红队审计清单哈希：`{required_audit_findings_sha256}`"]
            if required_audit_findings_sha256 is not None
            else []
        ),
        "- 改写研究计划：否",
        f"- 已核验预实验证据文件：{evidence_file_count}",
        f"- 输入哈希：`{input_hash}`",
        f"- 模型响应哈希：`{response_hash}`",
        "",
        "## 总体结论",
        "",
        f"- 规范类别：`{review.recommendation}`",
        f"- 评审器原始建议：{review.recommendation_text}",
        "",
        review.summary,
        "",
        "## 研究问题重述",
        "",
        review.problem_restatement,
        "",
        "## 最强反证或替代解释",
        "",
        review.strongest_counterevidence,
        "",
        "## 假设—证据对应",
        "",
        review.hypothesis_evidence_assessment,
        "",
        "## 零模型与对照",
        "",
        review.null_controls_assessment,
        "",
        "## 分析单位",
        "",
        review.analysis_unit_assessment,
        "",
        "## 统计解释",
        "",
        review.statistics_assessment,
        "",
        "## 过度外推与结论边界",
        "",
        review.overclaim_assessment,
        "",
        "## 可复现性",
        "",
        review.reproducibility_assessment,
        "",
        "## 参考文献",
        "",
        review.references_assessment,
        "",
        "## 优点",
        "",
        *_markdown_items(review.strengths),
        "",
        "## 重大问题",
        "",
        *_markdown_items(review.major_issues),
        "",
        "## 次要问题",
        "",
        *_markdown_items(review.minor_issues),
        "",
        "## 评审器使用的锁定参考目录编号",
        "",
        (
            ", ".join(f"[{index}]" for index in review.reference_indices)
            if review.reference_indices
            else "（响应未列出目录编号）"
        ),
        "",
    ]
    return "\n".join(sections)


def _markdown_items(values: Sequence[str]) -> tuple[str, ...]:
    if not values:
        return ("（响应未列出条目）",)
    return tuple(f"- {value}" for value in values)


def _root_level_output_path(root: Path, value: Path | str | None, default: str) -> Path:
    path = _inside_output_path(root, value, default)
    if path.parent != root:
        raise ContestDirectPlanScientificReviewError(
            "JSON review artifact must be written directly under output_dir"
        )
    return path


def _inside_output_path(root: Path, value: Path | str | None, default: str) -> Path:
    if value is None:
        path = (root / default).resolve()
    else:
        requested = Path(value).expanduser()
        path = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContestDirectPlanScientificReviewError(
            f"review output escapes output_dir: {path}"
        ) from exc
    return path


def _resolve_artifact_relative_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ContestDirectPlanScientificReviewError("artifact file path escapes review root")
    path = (root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContestDirectPlanScientificReviewError(
            "artifact file path escapes review root"
        ) from exc
    if not path.is_file():
        raise ContestDirectPlanScientificReviewError(f"review-bound file is missing: {path}")
    return path


def _resolve_evidence_path(value: Path | str, *, root: Path) -> Path:
    path_value = Path(value)
    path = (
        path_value.expanduser().resolve()
        if path_value.is_absolute()
        else (root / path_value).resolve()
    )
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContestDirectPlanScientificReviewError(
            f"preexperiment evidence escapes its root: {path}"
        ) from exc
    return path


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_immutable_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ContestDirectPlanScientificReviewError(
                f"refusing to overwrite different review bytes: {path}"
            )
        return
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ContestDirectPlanScientificReviewError(
                f"review output raced with different bytes: {path}"
            ) from None


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text_hash(value: str) -> str:
    return _bytes_hash(value.encode("utf-8"))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "ContestDirectPlanScientificReviewArtifact",
    "ContestDirectPlanScientificReviewError",
    "ContestDirectReviewEvidenceFile",
    "ContestDirectScientificReviewContent",
    "build_contest_direct_plan_scientific_review_messages",
    "load_contest_direct_plan_scientific_review",
    "review_contest_direct_plan_science",
]
