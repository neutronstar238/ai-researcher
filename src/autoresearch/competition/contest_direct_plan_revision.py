"""One-shot revision of a direct contest plan from verified pilot evidence.

The model authors the revised science.  This module only verifies the immutable
inputs, constructs the ordered context, tolerantly projects the returned JSON, and
retains hashes plus the exact provider receipt.  It never retries or rewrites a
scientific answer merely to satisfy formatting.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    ContestDirectScientificPlan,
    ContestReferenceProjectionAudit,
)
from autoresearch.competition.contest_direction_memory import (
    normalize_optional_dreaming_context,
    optional_dreaming_context_hash,
    optional_dreaming_context_message,
)
from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    LockedReferenceProjection,
    project_locked_reference_selection,
)
from autoresearch.competition.manifest import (
    canonical_model_hash,
    file_hash,
    write_json_model,
)
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_SHA256 = r"^[0-9a-f]{64}$"
_SHA256_TEXT = re.compile(_SHA256)
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?P<number>[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?P<percent>\s*[%％])?"
)
_SCIENTIFIC_MULTIPLICATION = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?P<mantissa>[-+]?(?:\d+(?:\.\d+)?|\.\d+))"
    r"\s*(?:×|·|\*|\\(?:times|cdot)|\x09imes)\s*10\s*\^\s*"
    r"(?:\{\s*)?(?P<exponent>[-+]?\d+)(?:\s*\})?"
    r"(?P<percent>\s*[%％])?"
)
_POWER_OF_TEN = re.compile(
    r"(?<![A-Za-z0-9_.])" r"10\s*\^\s*(?P<exponent>[-+]?\d+)" r"(?P<percent>\s*[%％])?"
)
_MILLION_SUFFIX = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?P<number>[-+]?(?:\d+(?:\.\d+)?|\.\d+))"
    r"\s*(?:[Mm](?![A-Za-z])|million\b|百万)"
    r"(?P<percent>\s*[%％])?",
    flags=re.IGNORECASE,
)
_IDENTIFIER_NUMBER = re.compile(r"(?:[A-Za-z]+)(?P<number>[-+]?\d+(?:\.\d+)?)$")
_SECTION_HEADER = re.compile(r"(【[^】]+】|(?m:^#{1,6}\s+[^\n]+$))")
_CLAUSE_BREAK = re.compile(r"[。！？；;\n]+")
_FUTURE_OR_HYPOTHETICAL_MARKERS = (
    "后续",
    "未来",
    "下一步",
    "正式实验",
    "计划",
    "建议",
    "拟采用",
    "拟加入",
    "将采用",
    "将加入",
    "将扩大",
    "可考虑",
    "候选对照",
    "不能排除",
    "尚不能排除",
    "例如",
    "比如",
    "譬如",
    "可能解释",
    "可能源于",
    "替代解释",
    "另一种解释",
    "若采用",
    "如果采用",
)
_OBSERVED_SECTION_MARKERS = ("预实验结果", "已观察结果", "实测结果")
_TEXT_SUFFIXES = frozenset({".csv", ".json", ".jsonl", ".log", ".md", ".tsv", ".txt"})
_SCIENCE_FIELDS = (
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "source",
    "target",
    "paper_title",
    "paper_abstract",
    "main_hypothesis",
    "methods",
    "experiments",
    "baselines",
    "metrics",
    "results",
    "limitations",
)
_ALIASES = {
    "problemstatement": "problem_statement",
    "问题陈述": "problem_statement",
    "待研究问题": "problem_statement",
    "rationale": "rationale",
    "解决思路": "rationale",
    "研究思路": "rationale",
    "technicaldetails": "technical_details",
    "技术细节": "technical_details",
    "必要的技术手段": "technical_details",
    "datasets": "datasets",
    "dataset": "datasets",
    "数据集": "datasets",
    "source": "source",
    "数据来源": "source",
    "target": "target",
    "目标特征": "target",
    "papertitle": "paper_title",
    "标题": "paper_title",
    "论文标题": "paper_title",
    "paperabstract": "paper_abstract",
    "摘要": "paper_abstract",
    "论文摘要": "paper_abstract",
    "mainhypothesis": "main_hypothesis",
    "hypothesis": "main_hypothesis",
    "主假设": "main_hypothesis",
    "研究假设": "main_hypothesis",
    "methods": "methods",
    "method": "methods",
    "方法论": "methods",
    "experiments": "experiments",
    "experiment": "experiments",
    "实验设计": "experiments",
    "baselines": "baselines",
    "baseline": "baselines",
    "基线": "baselines",
    "基线对比": "baselines",
    "metrics": "metrics",
    "metric": "metrics",
    "评估指标": "metrics",
    "results": "results",
    "result": "results",
    "实验结果": "results",
    "limitations": "limitations",
    "limitation": "limitations",
    "局限": "limitations",
    "局限性": "limitations",
    "研究局限": "limitations",
    "references": "references",
    "reference": "references",
    "参考文献": "references",
}


class ContestDirectPlanRevisionError(RuntimeError):
    """Raised when verified evidence cannot yield one auditable revision."""


@dataclass(frozen=True)
class _ClaimNumber:
    """One numeric literal plus the precision actually claimed by its spelling."""

    raw: str
    value: Decimal
    resolution: Decimal | None
    is_percent: bool


def _contains_chinese(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


class ContestDirectRevisedScientificPlan(ContestDirectScientificPlan):
    """Complete revised plan plus explicit hypothesis and pilot limitations."""

    main_hypothesis: str
    limitations: str

    @field_validator("main_hypothesis", "limitations")
    @classmethod
    def _require_chinese_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not _contains_chinese(normalized):
            raise ValueError("revised hypothesis and limitations must contain Chinese")
        return normalized

    @model_validator(mode="after")
    def _require_pilot_boundary(self) -> ContestDirectRevisedScientificPlan:
        if "预实验" not in self.results:
            raise ValueError("revised Results must explicitly identify the pilot as 预实验")
        if "预实验" not in self.limitations:
            raise ValueError("revised limitations must explicitly discuss the 预实验")
        return self


class ContestVerifiedPilotFile(StrictFrozenModel):
    """One file whose exact bytes were checked before model invocation."""

    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(ge=0)
    media_type: str
    text_supplied_to_model: bool


class ContestDirectPlanRevisionArtifact(StrictFrozenModel):
    """Content-addressed output of exactly one evidence-based revision call."""

    schema_version: Literal["contest-direct-plan-revision-v1"] = "contest-direct-plan-revision-v1"
    document_type: Literal["含真实预实验结果的科学假设与研究计划"] = (
        "含真实预实验结果的科学假设与研究计划"
    )
    revision_id: str = Field(pattern=r"^direct-plan-revision-[0-9a-f]{16}$")
    status: Literal["revised_from_verified_preexperiment"] = "revised_from_verified_preexperiment"
    scientific_problem: str = Field(min_length=1)
    original_plan_id: str
    original_plan_artifact_hash: str = Field(pattern=_SHA256)
    preexperiment_artifact_sha256: str = Field(pattern=_SHA256)
    preexperiment_metrics_sha256: str = Field(pattern=_SHA256)
    verified_files: tuple[ContestVerifiedPilotFile, ...] = Field(min_length=1)
    verified_files_sha256: str = Field(pattern=_SHA256)
    verified_revision_context_sha256: str | None = Field(default=None, pattern=_SHA256)
    derived_memory_context_sha256: str | None = Field(default=None, pattern=_SHA256)
    plan: ContestDirectRevisedScientificPlan
    reference_projection: ContestReferenceProjectionAudit | None = None
    provider: str
    model_name: str
    generation_calls: Literal[1] = 1
    input_hash: str = Field(pattern=_SHA256)
    model_response_hash: str = Field(pattern=_SHA256)
    raw_response_relative_path: str
    authorship_receipt_relative_path: str
    authorship_receipt_hash: str = Field(pattern=_SHA256)
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_program_fields(self) -> ContestDirectPlanRevisionArtifact:
        if self.revision_id != f"direct-plan-revision-{self.input_hash[:16]}":
            raise ValueError("revision_id does not match the program input hash")
        expected_files_hash = canonical_model_hash(
            {"files": [item.model_dump(mode="json") for item in self.verified_files]}
        )
        if self.verified_files_sha256 != expected_files_hash:
            raise ValueError("verified pilot file binding hash mismatch")
        hash_payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        expected_artifact_hashes = {canonical_model_hash(hash_payload)}
        optional_absent = [
            field
            for field, value in (
                ("verified_revision_context_sha256", self.verified_revision_context_sha256),
                ("derived_memory_context_sha256", self.derived_memory_context_sha256),
                ("reference_projection", self.reference_projection),
            )
            if value is None
        ]
        for mask in range(1, 1 << len(optional_absent)):
            legacy_payload = dict(hash_payload)
            for index, field in enumerate(optional_absent):
                if mask & (1 << index):
                    legacy_payload.pop(field, None)
            expected_artifact_hashes.add(canonical_model_hash(legacy_payload))
        if self.artifact_hash not in expected_artifact_hashes:
            raise ValueError("direct plan revision artifact hash mismatch")
        return self

    def flat_payload(self) -> dict[str, Any]:
        """Return the flat mapping accepted by ``materialize_contest_direct_plan``."""

        plan = self.plan
        return {
            "title": plan.paper_title,
            "abstract": plan.paper_abstract,
            "problem_statement": plan.problem_statement,
            "rationale": f"主假设：{plan.main_hypothesis}\n\n{plan.rationale}",
            "technical_details": plan.technical_details,
            "datasets": {
                "description": plan.datasets,
                "source": plan.source,
                "target": plan.target,
            },
            "methods": plan.methods,
            "experiments": {
                "steps": plan.experiments,
                "baselines": plan.baselines,
                "metrics": plan.metrics,
            },
            "results": f"{plan.results}\n\n预实验局限：{plan.limitations}",
            "references": list(plan.references),
        }


def build_contest_direct_plan_revision_messages(
    *,
    scientific_problem: str,
    requirements: Sequence[str] | str,
    selected_skill_contexts: Sequence[str | Mapping[str, Any]],
    original_plan: ContestDirectPlanArtifact | ContestDirectPlanRevisionArtifact,
    reference_catalog: Sequence[str | Mapping[str, Any]],
    preexperiment_artifact: Mapping[str, Any],
    preexperiment_metrics: Mapping[str, Any],
    verified_files: Sequence[ContestVerifiedPilotFile],
    verified_file_contents: Mapping[str, str],
    verified_revision_context: Mapping[str, Any] | None = None,
    derived_memory_context: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build generic-system → task → Skills → plan → evidence → contract messages."""

    problem = scientific_problem.strip()
    if not problem:
        raise ContestDirectPlanRevisionError("scientific_problem must not be blank")
    normalized_requirements = _normalize_requirements(requirements)
    catalog_payload = _normalize_reference_catalog(reference_catalog)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是自主科研智能体，负责根据已经真实执行且可追溯的探索性预实验修订"
                "研究计划。区分原始观察、统计解释、替代解释和待验证外推；证据不支持"
                "原假设时可以收窄、反转或放弃，不得把阴性或矛盾结果包装成正结果。"
                "不要输出隐藏思考过程，只输出要求的最终 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "research_question_requirements_and_locked_references",
                    "scientific_problem": problem,
                    "requirements_zh": list(normalized_requirements),
                    "locked_reference_catalog": catalog_payload,
                    "reference_boundary_zh": ("只能返回目录编号；不得新增、猜测或改写目录外文献。"),
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
                        "boundary_zh": (
                            "该 Skill 只提供学科方法论和优秀研究路径，不是事实、文献、"
                            "实验结果或指定结论。"
                        ),
                        "content": content,
                        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.extend(
        (
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "original_complete_research_plan",
                        "boundary_zh": "这是待修订版本，不是不可改变的结论。",
                        "artifact": original_plan.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "program_verified_exploratory_preexperiment",
                        "evidence_boundary_zh": (
                            "这是 exploratory pilot / protocol amendment，不是确认性、"
                            "预注册主实验或开放数学问题的证明。文件哈希已由程序逐字节核验；"
                            "数值只能引用 artifact、metrics 或所附原始文本中实际出现的值。"
                        ),
                        "artifact": dict(preexperiment_artifact),
                        "metrics": dict(preexperiment_metrics),
                        "verified_files": [
                            {
                                **item.model_dump(mode="json"),
                                "verified_text": verified_file_contents.get(item.path),
                            }
                            for item in verified_files
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
            {
                "role": "user",
                "content": (
                    "请一次性返回修订后的完整 JSON，不要返回补丁。字段为："
                    "problem_statement、rationale、technical_details、datasets、source、"
                    "target、paper_title、paper_abstract、main_hypothesis、methods、"
                    "experiments、baselines、metrics、results、limitations、references。"
                    "references 只返回锁定目录编号数组；目录足够时建议选择"
                    f"{MIN_RESEARCH_PLAN_REFERENCES}–{MAX_RESEARCH_PLAN_REFERENCES}条"
                    "实际支持本计划的文献。若只返回少量关键编号，程序会从同一锁定真实"
                    "目录按既定相关性排序补足书目，绝不新增目录外文献。修订必须实质"
                    "响应预实验：根据证据"
                    "保持、收窄、反转或放弃主假设，并同步修改 Methods、Experiments、"
                    "Metrics、Results 与 limitations。Results 必须明确写‘预实验’，引用"
                    "artifact 中真实数值，同时给出至少一种替代解释；不得把预实验称为"
                    "确认性结果、正式实验或预注册主实验。若更强的局部分块/条件置换对照"
                    "不支持原假设，必须如实反映，不能只强调较弱对照。不同零模型回答"
                    "不同问题：若输入包含 wheel null 与 permutation null，必须分别解释，"
                    "不得合并为同一证据。没有进入输入的数值、文献或实验均不得新增为"
                    "已观察事实；未来正式实验的设计建议必须使用计划语气。中文报告不需"
                    "凑长度，技术名、公式和论文题名可保留原文。"
                ),
            },
        )
    )
    if verified_revision_context is not None:
        messages.insert(
            len(messages) - 1,
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "program_verified_revision_context",
                        "context": dict(verified_revision_context),
                        "context_sha256": canonical_model_hash(dict(verified_revision_context)),
                        "boundary_zh": (
                            "这是由程序从已核验预实验、冻结 runner 和确定性科学反例"
                            "形成的修订约束。它可以支持方法定义、未来协议参数和对既有"
                            "结果的纠错，但不是新增实验观察，不得把其中的计划值写成"
                            "已经执行。"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
    memory_context = normalize_optional_dreaming_context(
        dict(derived_memory_context) if derived_memory_context is not None else None
    )
    if memory_context is not None:
        messages.insert(
            len(messages) - 1,
            optional_dreaming_context_message(memory_context),
        )
    return messages


def revise_contest_direct_plan(
    *,
    original_plan: ContestDirectPlanArtifact
    | ContestDirectPlanRevisionArtifact
    | Mapping[str, Any]
    | Path
    | str,
    scientific_problem: str,
    requirements: Sequence[str] | str,
    selected_skill_contexts: Sequence[str | Mapping[str, Any]],
    reference_catalog: Sequence[str | Mapping[str, Any]],
    preexperiment_artifact: BaseModel | Mapping[str, Any] | Path | str,
    preexperiment_metrics: BaseModel | Mapping[str, Any] | Path | str | None = None,
    raw_file_bindings: Sequence[Mapping[str, Any]] = (),
    verified_revision_context: Mapping[str, Any] | None = None,
    derived_memory_context: Mapping[str, Any] | None = None,
    preexperiment_root: Path | str | None = None,
    output_dir: Path | str,
    output_path: Path | str | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    llm_call: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
) -> ContestDirectPlanRevisionArtifact:
    """Verify one pilot and ask the configured model to revise the plan once."""

    original = _load_original_plan(original_plan)
    artifact_payload, artifact_path = _load_json_mapping(preexperiment_artifact)
    _verify_internal_artifact_hash(artifact_payload)
    _verify_preexperiment_scope(artifact_payload)
    root = _evidence_root(
        explicit_root=preexperiment_root,
        artifact_path=artifact_path,
        artifact_payload=artifact_payload,
    )
    metrics_payload, metrics_path = _load_metrics(
        preexperiment_metrics,
        artifact_payload=artifact_payload,
        root=root,
    )
    binding_specs = [
        *_binding_specs_from_payload(artifact_payload),
        *(_binding_specs_from_manifest(artifact_payload, root=root)),
        *(dict(item) for item in raw_file_bindings),
    ]
    verified_files, text_contents = _verify_file_bindings(
        binding_specs,
        root=root,
        metrics_path=metrics_path,
    )
    if not verified_files:
        raise ContestDirectPlanRevisionError(
            "preexperiment must bind at least one raw result, metric, or log file by SHA-256"
        )

    references = _reference_strings(reference_catalog)
    revision_context = (
        dict(verified_revision_context) if verified_revision_context is not None else None
    )
    revision_context_hash = (
        canonical_model_hash(revision_context) if revision_context is not None else None
    )
    memory_context = normalize_optional_dreaming_context(
        dict(derived_memory_context) if derived_memory_context is not None else None
    )
    memory_context_hash = optional_dreaming_context_hash(memory_context)
    input_payload = {
        "scientific_problem": scientific_problem.strip(),
        "requirements": list(_normalize_requirements(requirements)),
        "original_plan_artifact_hash": original.artifact_hash,
        "preexperiment_artifact_sha256": canonical_model_hash(artifact_payload),
        "preexperiment_metrics_sha256": canonical_model_hash(metrics_payload),
        "verified_files": [item.model_dump(mode="json") for item in verified_files],
        "selected_skill_sha256": [
            hashlib.sha256(_skill_content(item, ordinal=index)[0].encode("utf-8")).hexdigest()
            for index, item in enumerate(selected_skill_contexts, start=1)
        ],
        "reference_catalog": _normalize_reference_catalog(reference_catalog),
    }
    if revision_context_hash is not None:
        input_payload["verified_revision_context_sha256"] = revision_context_hash
    if memory_context_hash is not None:
        input_payload["derived_memory_context_sha256"] = memory_context_hash
    input_hash = canonical_model_hash(input_payload)
    messages = build_contest_direct_plan_revision_messages(
        scientific_problem=scientific_problem,
        requirements=requirements,
        selected_skill_contexts=selected_skill_contexts,
        original_plan=original,
        reference_catalog=reference_catalog,
        preexperiment_artifact=artifact_payload,
        preexperiment_metrics=metrics_payload,
        verified_files=verified_files,
        verified_file_contents=text_contents,
        verified_revision_context=revision_context,
        derived_memory_context=memory_context,
    )
    completion = llm_call(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        response_schema=_revision_response_schema(),
        response_schema_name="contest_direct_plan_revision",
    )
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    revision_id = f"direct-plan-revision-{input_hash[:16]}"
    response_hash = hashlib.sha256(completion.response_text.encode("utf-8")).hexdigest()
    interaction_id = f"{revision_id}-{response_hash[:12]}"
    response_path = output_root / "responses" / f"{interaction_id}.txt"
    _write_immutable_bytes(response_path, completion.response_text.encode("utf-8"))
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id=interaction_id,
        attempt=1,
        messages=messages,
        completion=completion,
        output_dir=output_root,
    )
    receipt_path = Path(receipt.output_path).resolve()

    normalized, reference_projection = _normalize_revision_payload(
        completion.parsed_json, references=references
    )
    try:
        revised_plan = ContestDirectRevisedScientificPlan.model_validate(normalized)
    except ValidationError as exc:
        raise ContestDirectPlanRevisionError(
            f"one-shot revision omitted required Chinese scientific content: {exc}"
        ) from exc
    _guard_observed_numbers(
        revised_plan,
        original=original,
        preexperiment_artifact=artifact_payload,
        preexperiment_metrics=metrics_payload,
        verified_file_contents=text_contents,
        verified_revision_context=revision_context,
    )
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-plan-revision-v1",
        "document_type": "含真实预实验结果的科学假设与研究计划",
        "revision_id": revision_id,
        "status": "revised_from_verified_preexperiment",
        "scientific_problem": scientific_problem.strip(),
        "original_plan_id": _original_plan_id(original),
        "original_plan_artifact_hash": original.artifact_hash,
        "preexperiment_artifact_sha256": canonical_model_hash(artifact_payload),
        "preexperiment_metrics_sha256": canonical_model_hash(metrics_payload),
        "verified_files": [item.model_dump(mode="json") for item in verified_files],
        "verified_files_sha256": canonical_model_hash(
            {"files": [item.model_dump(mode="json") for item in verified_files]}
        ),
        "plan": revised_plan.model_dump(mode="json"),
        "reference_projection": ContestReferenceProjectionAudit(
            policy="locked-catalog-exact-order-v2",
            catalog_count=reference_projection.catalog_count,
            model_selected_indices=reference_projection.model_selected_indices,
            program_supplemented_indices=reference_projection.program_supplemented_indices,
            final_reference_count=len(reference_projection.references),
        ).model_dump(mode="json"),
        "provider": completion.provider,
        "model_name": completion.model_name,
        "generation_calls": 1,
        "input_hash": input_hash,
        "model_response_hash": response_hash,
        "raw_response_relative_path": response_path.relative_to(output_root).as_posix(),
        "authorship_receipt_relative_path": receipt_path.relative_to(output_root).as_posix(),
        "authorship_receipt_hash": receipt.receipt_hash,
    }
    if revision_context_hash is not None:
        payload["verified_revision_context_sha256"] = revision_context_hash
    if memory_context_hash is not None:
        payload["derived_memory_context_sha256"] = memory_context_hash
    payload["artifact_hash"] = canonical_model_hash(payload)
    result = ContestDirectPlanRevisionArtifact.model_validate(payload)
    destination = (
        Path(output_path)
        if output_path is not None
        else output_root / "system-authored-revised-research-plan.json"
    )
    write_json_model(destination, result)
    return result


def _load_original_plan(
    value: ContestDirectPlanArtifact
    | ContestDirectPlanRevisionArtifact
    | Mapping[str, Any]
    | Path
    | str,
) -> ContestDirectPlanArtifact | ContestDirectPlanRevisionArtifact:
    if isinstance(value, ContestDirectPlanArtifact | ContestDirectPlanRevisionArtifact):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        if payload.get("schema_version") == "contest-direct-plan-revision-v1":
            return ContestDirectPlanRevisionArtifact.model_validate(payload)
        return ContestDirectPlanArtifact.model_validate(payload)
    if isinstance(value, Path):
        text = value.read_text(encoding="utf-8")
        payload = json.loads(text)
        if payload.get("schema_version") == "contest-direct-plan-revision-v1":
            return ContestDirectPlanRevisionArtifact.model_validate(payload)
        return ContestDirectPlanArtifact.model_validate(payload)
    text = value.strip()
    if text.startswith("{"):
        payload = json.loads(text)
        if payload.get("schema_version") == "contest-direct-plan-revision-v1":
            return ContestDirectPlanRevisionArtifact.model_validate(payload)
        return ContestDirectPlanArtifact.model_validate(payload)
    return _load_original_plan(Path(text))


def _original_plan_id(
    plan: ContestDirectPlanArtifact | ContestDirectPlanRevisionArtifact,
) -> str:
    if isinstance(plan, ContestDirectPlanRevisionArtifact):
        return plan.revision_id
    return plan.plan_id


def _load_json_mapping(
    value: BaseModel | Mapping[str, Any] | Path | str,
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json"), None
    if isinstance(value, Mapping):
        return dict(value), None
    path = value if isinstance(value, Path) else Path(value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectPlanRevisionError(f"invalid preexperiment JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ContestDirectPlanRevisionError("preexperiment artifact must be a JSON object")
    return payload, path.resolve()


def _verify_internal_artifact_hash(payload: Mapping[str, Any]) -> None:
    recorded = payload.get("artifact_hash")
    if not isinstance(recorded, str) or not re.fullmatch(_SHA256, recorded):
        raise ContestDirectPlanRevisionError("preexperiment artifact lacks a valid artifact_hash")
    variants = (
        {key: value for key, value in payload.items() if key != "artifact_hash"},
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "output_path"}
        },
    )
    if recorded not in {canonical_model_hash(candidate) for candidate in variants}:
        raise ContestDirectPlanRevisionError("preexperiment artifact_hash does not replay")


def _verify_preexperiment_scope(payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    if status is not None and status not in {"completed", "succeeded", "complete"}:
        raise ContestDirectPlanRevisionError("preexperiment artifact is not completed")
    study_phase = payload.get("study_phase")
    if study_phase is not None and study_phase != "exploratory_pilot":
        raise ContestDirectPlanRevisionError("preexperiment artifact is not an exploratory pilot")


def _evidence_root(
    *,
    explicit_root: Path | str | None,
    artifact_path: Path | None,
    artifact_payload: Mapping[str, Any],
) -> Path:
    if explicit_root is not None:
        return Path(explicit_root).resolve()
    if artifact_path is not None:
        return artifact_path.parent.resolve()
    output_path = artifact_payload.get("output_path")
    if isinstance(output_path, str) and output_path.strip():
        return Path(output_path).resolve().parent
    raise ContestDirectPlanRevisionError(
        "preexperiment_root is required when a mapping has no output_path"
    )


def _load_metrics(
    value: BaseModel | Mapping[str, Any] | Path | str | None,
    *,
    artifact_payload: Mapping[str, Any],
    root: Path,
) -> tuple[dict[str, Any], Path | None]:
    candidate: Any = value
    if candidate is None:
        metrics_relative_path = artifact_payload.get("metrics_relative_path")
        if isinstance(metrics_relative_path, str) and metrics_relative_path.strip():
            candidate = metrics_relative_path
    if candidate is None:
        for key in (
            "metrics",
            "aggregate_metrics",
            "aggregate_results",
            "metric_summary",
            "analysis_metrics",
        ):
            if isinstance(artifact_payload.get(key), Mapping):
                candidate = artifact_payload[key]
                break
    if candidate is None:
        raise ContestDirectPlanRevisionError("preexperiment metrics are absent")
    if isinstance(candidate, BaseModel):
        return candidate.model_dump(mode="json"), None
    if isinstance(candidate, Mapping):
        return dict(candidate), None
    path = _resolve_evidence_path(candidate, root=root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectPlanRevisionError(f"invalid metrics JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ContestDirectPlanRevisionError("preexperiment metrics must be a JSON object")
    return payload, path


def _binding_specs_from_manifest(
    artifact_payload: Mapping[str, Any], *, root: Path
) -> list[dict[str, Any]]:
    manifest_value = artifact_payload.get("manifest_relative_path") or artifact_payload.get(
        "manifest_path"
    )
    if not isinstance(manifest_value, str) or not manifest_value.strip():
        return []
    path = _resolve_evidence_path(manifest_value, root=root)
    expected = artifact_payload.get("manifest_sha256")
    if expected is not None and expected != file_hash(path):
        raise ContestDirectPlanRevisionError("preexperiment manifest SHA-256 mismatch")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectPlanRevisionError("preexperiment manifest is invalid JSON") from exc
    if not isinstance(manifest, Mapping):
        raise ContestDirectPlanRevisionError("preexperiment manifest must be an object")
    recorded_manifest_hash = artifact_payload.get("manifest_hash")
    if (
        recorded_manifest_hash is not None
        and manifest.get("manifest_hash") != recorded_manifest_hash
    ):
        raise ContestDirectPlanRevisionError(
            "preexperiment artifact and manifest canonical hashes differ"
        )
    manifest_status = manifest.get("program_status")
    artifact_status = artifact_payload.get("status")
    if manifest_status is not None and manifest_status != artifact_status:
        raise ContestDirectPlanRevisionError("preexperiment artifact and manifest statuses differ")
    return _binding_specs_from_payload(manifest)


def _binding_specs_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []

    def visit(value: Any, *, role: str) -> None:
        if isinstance(value, Mapping):
            for hash_key, hash_value in value.items():
                hash_name = str(hash_key)
                file_prefix = (
                    hash_name[: -len("_file_sha256")] if hash_name.endswith("_file_sha256") else ""
                )
                relative_prefix = (
                    hash_name[: -len("_sha256")]
                    if hash_name.endswith("_sha256") and not hash_name.endswith("_file_sha256")
                    else ""
                )
                path_keys: tuple[str, ...]
                if file_prefix:
                    path_keys = (
                        f"{file_prefix}_relative_path",
                        f"{file_prefix}_path",
                    )
                elif relative_prefix:
                    # Generic ``*_sha256`` is accepted only with an explicitly
                    # relative file.  This intentionally excludes external source
                    # paths and unrelated canonical object hashes.
                    path_keys = (f"{relative_prefix}_relative_path",)
                else:
                    path_keys = ("path", "relative_path", "filename", "file")
                if hash_name in {"sha256", "file_sha256"} or file_prefix or relative_prefix:
                    for path_key in path_keys:
                        if path_key in value and isinstance(value[path_key], str):
                            discovered.append(
                                {
                                    "role": str(value.get("role") or value.get("kind") or role),
                                    "path": value[path_key],
                                    "sha256": hash_value,
                                }
                            )
                            break
            for key, child in value.items():
                visit(child, role=str(key))
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            for child in value:
                visit(child, role=role)

    visit(payload, role="preexperiment_artifact")
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in discovered:
        key = (str(item.get("path")), str(item.get("sha256")))
        unique.setdefault(key, item)
    return list(unique.values())


def _verify_file_bindings(
    specs: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    metrics_path: Path | None,
) -> tuple[tuple[ContestVerifiedPilotFile, ...], dict[str, str]]:
    verified: list[ContestVerifiedPilotFile] = []
    contents: dict[str, str] = {}
    seen: dict[Path, str] = {}
    for ordinal, spec in enumerate(specs, start=1):
        raw_path = spec.get("path") or spec.get("relative_path") or spec.get("filename")
        expected = spec.get("sha256") or spec.get("file_sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise ContestDirectPlanRevisionError("raw file binding requires path and sha256")
        if not re.fullmatch(_SHA256, expected):
            raise ContestDirectPlanRevisionError("raw file binding has invalid sha256")
        path = _resolve_evidence_path(raw_path, root=root)
        if path in seen:
            if seen[path] != expected:
                raise ContestDirectPlanRevisionError(
                    f"conflicting SHA-256 bindings for preexperiment file: {path}"
                )
            continue
        seen[path] = expected
        if not path.is_file():
            raise ContestDirectPlanRevisionError(f"bound preexperiment file is missing: {path}")
        actual = file_hash(path)
        if actual != expected:
            raise ContestDirectPlanRevisionError(
                f"bound preexperiment file SHA-256 mismatch: {path}"
            )
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        binding_role = str(spec.get("role") or f"raw_file_{ordinal}")
        evidence_label = f"{binding_role} {path.name}".casefold()
        include_text = path.suffix.casefold() in _TEXT_SUFFIXES and any(
            marker in evidence_label for marker in ("metric", "log", "stdout", "stderr")
        )
        model_path = path.as_posix()
        if include_text:
            try:
                contents[model_path] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ContestDirectPlanRevisionError(
                    f"declared text evidence is not UTF-8: {path}"
                ) from exc
        verified.append(
            ContestVerifiedPilotFile(
                role=binding_role,
                path=model_path,
                sha256=actual,
                size_bytes=path.stat().st_size,
                media_type=media_type,
                text_supplied_to_model=include_text,
            )
        )
    if metrics_path is not None and metrics_path.resolve() not in seen:
        raise ContestDirectPlanRevisionError(
            "metrics file is not covered by a manifest or explicit SHA-256 binding"
        )
    verified.sort(key=lambda item: (item.path, item.role))
    return tuple(verified), contents


def _resolve_evidence_path(value: Path | str, *, root: Path) -> Path:
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ContestDirectPlanRevisionError("preexperiment file escapes evidence root") from exc
    return path


def _normalize_requirements(value: Sequence[str] | str) -> tuple[str, ...]:
    items = (value,) if isinstance(value, str) else value
    normalized = tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))
    if not normalized:
        raise ContestDirectPlanRevisionError("requirements must not be blank")
    return normalized


def _skill_content(value: str | Mapping[str, Any], *, ordinal: int) -> tuple[str, str]:
    if isinstance(value, str):
        content = value.strip()
        name = f"selected-skill-{ordinal}"
    else:
        content = str(
            value.get("content") or value.get("skill_content") or value.get("body") or ""
        ).strip()
        name = str(value.get("name") or value.get("skill_id") or f"selected-skill-{ordinal}")
    if not content:
        raise ContestDirectPlanRevisionError("selected Skill content must not be blank")
    return content, name


def _normalize_reference_catalog(
    entries: Sequence[str | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            if not entry.strip():
                continue
            payload: dict[str, Any] = {"citation": entry.strip()}
        else:
            payload = {str(key): value for key, value in entry.items()}
            if not any(str(value).strip() for value in payload.values() if value is not None):
                continue
        catalog.append({"catalog_index": len(catalog) + 1, **payload})
    return catalog


def _reference_strings(entries: Sequence[str | Mapping[str, Any]]) -> tuple[str, ...]:
    rendered: list[str] = []
    for entry in _normalize_reference_catalog(entries):
        if "citation" in entry:
            rendered.append(str(entry["citation"]).strip())
            continue
        parts: list[str] = []
        for key in ("title", "authors", "year", "doi", "source_url", "url"):
            value = entry.get(key)
            if value in (None, "", []):
                continue
            if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
                parts.append(", ".join(str(item) for item in value))
            else:
                parts.append(str(value))
        rendered.append(". ".join(parts) or json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return tuple(rendered)


def _normalize_key(value: str) -> str:
    compact = re.sub(r"[\s_()（）:：/\-]+", "", value).casefold()
    return _ALIASES.get(compact, value.strip().casefold().replace(" ", "_"))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return "；".join(f"{key}：{_text(item)}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return "；".join(_text(item) for item in value)
    return "" if value is None else str(value).strip()


def _normalize_revision_payload(
    payload: Mapping[str, Any], *, references: tuple[str, ...]
) -> tuple[dict[str, Any], LockedReferenceProjection]:
    normalized = {_normalize_key(str(key)): value for key, value in payload.items()}
    datasets = normalized.get("datasets")
    if isinstance(datasets, Mapping):
        nested = {_normalize_key(str(key)): value for key, value in datasets.items()}
        normalized["datasets"] = nested.get("description") or nested.get("datasets")
        normalized.setdefault("source", nested.get("source"))
        normalized.setdefault("target", nested.get("target"))
    experiments = normalized.get("experiments")
    if isinstance(experiments, Mapping):
        nested = {_normalize_key(str(key)): value for key, value in experiments.items()}
        normalized["experiments"] = (
            nested.get("steps") or nested.get("design") or nested.get("experiments")
        )
        normalized.setdefault("baselines", nested.get("baselines"))
        normalized.setdefault("metrics", nested.get("metrics"))
    result: dict[str, Any] = {field: _text(normalized.get(field)) for field in _SCIENCE_FIELDS}
    reference_projection = project_locked_reference_selection(
        normalized.get("references"), references
    )
    result["references"] = reference_projection.references
    return result, reference_projection


def _project_references(value: Any, catalog: tuple[str, ...]) -> tuple[str, ...]:
    return project_locked_reference_selection(value, catalog).references


def _guard_observed_numbers(
    plan: ContestDirectRevisedScientificPlan,
    *,
    original: ContestDirectPlanArtifact | ContestDirectPlanRevisionArtifact,
    preexperiment_artifact: Mapping[str, Any],
    preexperiment_metrics: Mapping[str, Any],
    verified_file_contents: Mapping[str, str],
    verified_revision_context: Mapping[str, Any] | None = None,
) -> None:
    evidence_numbers = _source_numbers(
        (
            preexperiment_artifact,
            preexperiment_metrics,
            tuple(verified_file_contents.values()),
        )
    )
    observed_results = _evidence_claim_text(plan.results)
    result_numbers = _claim_numbers(observed_results)
    if not result_numbers:
        raise ContestDirectPlanRevisionError(
            "revised Results must quote at least one verified preexperiment number"
        )
    unsupported_result_numbers = sorted(
        {claim.raw for claim in result_numbers if not _matches_source(claim, evidence_numbers)}
    )
    if unsupported_result_numbers:
        raise ContestDirectPlanRevisionError(
            "revised Results contain numbers absent from verified preexperiment evidence: "
            + ", ".join(unsupported_result_numbers)
        )
    if not any(marker in plan.results for marker in ("替代解释", "另一种解释", "可能解释")):
        raise ContestDirectPlanRevisionError(
            "revised Results must state at least one alternative explanation"
        )
    allowed = evidence_numbers | _source_numbers(
        (
            original.plan.model_dump(mode="json"),
            verified_revision_context or {},
        )
    )
    observed_claim_fields = "\n".join(
        _evidence_claim_text(text)
        for text in (
            plan.paper_abstract,
            plan.rationale,
            plan.results,
            plan.limitations,
        )
    )
    introduced = sorted(
        {
            claim.raw
            for claim in _claim_numbers(observed_claim_fields)
            if not _matches_source(claim, allowed)
        }
    )
    if introduced:
        raise ContestDirectPlanRevisionError(
            "revised evidence claims introduced numbers absent from verified inputs: "
            + ", ".join(introduced)
        )


def _evidence_claim_text(text: str) -> str:
    """Keep clauses that present observations, excluding explicit proposal language.

    This is deliberately lexical and conservative: unmarked prose is evidence-bearing
    by default.  Only an explicit future/proposal/alternative marker exempts a clause,
    and a future section remains exempt until an observed-results header reopens it.
    """

    selected: list[str] = []
    future_section = False
    for chunk in _SECTION_HEADER.split(text):
        normalized = chunk.strip()
        if not normalized:
            continue
        if _SECTION_HEADER.fullmatch(normalized):
            if any(marker in normalized for marker in _OBSERVED_SECTION_MARKERS):
                future_section = False
            elif any(marker in normalized for marker in _FUTURE_OR_HYPOTHETICAL_MARKERS):
                future_section = True
            continue
        if future_section:
            continue
        for clause in _CLAUSE_BREAK.split(normalized):
            clause = clause.strip()
            if not clause:
                continue
            if any(marker in clause for marker in _FUTURE_OR_HYPOTHETICAL_MARKERS):
                continue
            selected.append(clause)
    return "\n".join(selected)


def _claim_numbers(text: str) -> tuple[_ClaimNumber, ...]:
    claims: list[_ClaimNumber] = []
    compound_spans: list[tuple[int, int]] = []
    for match in _SCIENTIFIC_MULTIPLICATION.finditer(text):
        mantissa = match.group("mantissa")
        exponent = int(match.group("exponent"))
        try:
            value = Decimal(mantissa) * (Decimal(10) ** exponent)
        except InvalidOperation:
            continue
        if not value.is_finite():
            continue
        compound_spans.append(match.span())
        claims.append(
            _ClaimNumber(
                raw=match.group(0).strip(),
                value=value,
                resolution=_literal_resolution(f"{mantissa}e{exponent}"),
                is_percent=bool(match.group("percent")),
            )
        )
    for match in _POWER_OF_TEN.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in compound_spans):
            continue
        exponent = int(match.group("exponent"))
        try:
            value = Decimal(10) ** exponent
        except InvalidOperation:
            continue
        if not value.is_finite():
            continue
        compound_spans.append(match.span())
        claims.append(
            _ClaimNumber(
                raw=match.group(0).strip(),
                value=value,
                resolution=_literal_resolution(f"1e{exponent}"),
                is_percent=bool(match.group("percent")),
            )
        )
    for match in _MILLION_SUFFIX.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in compound_spans):
            continue
        literal = match.group("number")
        try:
            value = Decimal(literal) * Decimal(1_000_000)
        except InvalidOperation:
            continue
        if not value.is_finite():
            continue
        compound_spans.append(match.span())
        claims.append(
            _ClaimNumber(
                raw=match.group(0).strip(),
                value=value,
                resolution=_literal_resolution(f"{literal}e6"),
                is_percent=bool(match.group("percent")),
            )
        )
    for match in _NUMBER.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in compound_spans):
            continue
        raw = match.group("number")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        if not value.is_finite():
            continue
        claims.append(
            _ClaimNumber(
                raw=raw,
                value=value,
                resolution=_literal_resolution(raw),
                is_percent=bool(match.group("percent")),
            )
        )
    return tuple(claims)


def _literal_resolution(raw: str) -> Decimal | None:
    """Return one unit in the last explicitly written digit.

    Plain integers normally carry one-unit resolution, so the comparison permits only
    standard rounding within half a unit.  A magnitude-ten-or-larger integer ending in
    zero is conservatively treated as a single trailing-zero (tens-place) report; this
    supports coarse range endpoints such as ``-30`` without making ordinary integers
    such as ``-85`` equally coarse. Decimal and scientific notation retain their
    written precision in the same way.
    """

    unsigned = raw.lstrip("+-")
    mantissa, marker, exponent_text = unsigned.lower().partition("e")
    fractional_digits = len(mantissa.partition(".")[2]) if "." in mantissa else 0
    exponent = int(exponent_text) if marker else 0
    if not marker and fractional_digits == 0 and unsigned.endswith("0"):
        try:
            if abs(Decimal(raw)) >= Decimal(10):
                return Decimal(10)
        except InvalidOperation:
            return None
    return Decimal(10) ** (exponent - fractional_digits)


def _source_numbers(value: Any) -> set[Decimal]:
    """Collect evidence values and numeric labels without treating hashes as science."""

    collected: set[Decimal] = set()

    def add_decimal(candidate: Any) -> None:
        if isinstance(candidate, bool):
            return
        try:
            number = Decimal(str(candidate))
        except (InvalidOperation, ValueError):
            return
        if number.is_finite():
            collected.add(number)

    def add_text(text: str) -> None:
        stripped = text.strip()
        if _SHA256_TEXT.fullmatch(stripped):
            return
        for claim in _claim_numbers(stripped):
            collected.add(claim.value)
            if claim.is_percent:
                collected.add(claim.value / Decimal(100))
        for token in re.split(r"[^A-Za-z0-9.+-]+", stripped):
            if not token or _SHA256_TEXT.fullmatch(token):
                continue
            match = _IDENTIFIER_NUMBER.fullmatch(token)
            if match:
                add_decimal(match.group("number"))
            elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", token):
                add_decimal(token)

    def visit(item: Any) -> None:
        if isinstance(item, BaseModel):
            visit(item.model_dump(mode="json"))
        elif isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                normalized_key = key_text.casefold()
                if "sha256" in normalized_key or normalized_key.endswith("_hash"):
                    continue
                add_text(key_text)
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            add_text(item)
        elif isinstance(item, int | float | Decimal) and not isinstance(item, bool):
            add_decimal(item)

    visit(value)
    return collected


def _matches_source(claim: _ClaimNumber, source_numbers: set[Decimal]) -> bool:
    candidates: list[tuple[Decimal, Decimal | None]] = [(claim.value, claim.resolution)]
    if claim.is_percent:
        candidates.append(
            (
                claim.value / Decimal(100),
                (claim.resolution / Decimal(100) if claim.resolution is not None else None),
            )
        )
    for value, resolution in candidates:
        if value in source_numbers:
            return True
        if resolution is None:
            continue
        tolerance = abs(resolution) / Decimal(2)
        for source in source_numbers:
            if value != 0 and source != 0 and (value > 0) != (source > 0):
                continue
            if abs(source - value) <= tolerance:
                return True
            # This guard establishes numeric provenance; it is not a house-style
            # enforcer for one particular rounding convention.  Models sometimes
            # report a verified value by truncating toward zero at the displayed
            # precision (for example, -7.4658 as -7.4).  Accept that exact decimal
            # bin while still rejecting the neighbouring -7.3 or -7.5 bin when
            # neither ordinary rounding nor truncation supports it.
            try:
                truncated = (source / resolution).to_integral_value(
                    rounding=ROUND_DOWN
                ) * resolution
            except (InvalidOperation, ZeroDivisionError):
                continue
            if truncated == value:
                return True
    return False


def _revision_response_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {field: {"type": "string"} for field in _SCIENCE_FIELDS}
    properties["references"] = {"type": "array", "items": {"type": "integer", "minimum": 1}}
    return {
        "type": "object",
        "required": [*_SCIENCE_FIELDS, "references"],
        "properties": properties,
        "additionalProperties": False,
    }


def _write_immutable_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ContestDirectPlanRevisionError(
                f"refusing to overwrite different raw response bytes: {path}"
            )
        return
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ContestDirectPlanRevisionError(
                f"raw response raced with different bytes: {path}"
            ) from None


__all__ = [
    "ContestDirectPlanRevisionArtifact",
    "ContestDirectPlanRevisionError",
    "ContestDirectRevisedScientificPlan",
    "ContestVerifiedPilotFile",
    "build_contest_direct_plan_revision_messages",
    "revise_contest_direct_plan",
]
