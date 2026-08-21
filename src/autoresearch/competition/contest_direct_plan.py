"""One-shot, delivery-first Chinese research-plan generation.

This module is intentionally independent from the formal competition lineage.  It is
the smallest useful path from one scientific question to a complete research plan:
the configured model authors the scientific fields once, while the program supplies
only document metadata, identifiers, provenance hashes, and persistence.

There is no portfolio-coverage rule, enum rubric, prose-length quota, or scientific
rewrite loop here.  Common JSON/key-shape variations are normalized locally.  If the
provider returned an almost-valid JSON object, one deterministic parsing repair is
allowed; the model is never asked to rewrite the science merely to satisfy formatting.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    LockedReferenceProjection,
    project_locked_reference_selection,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)

_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", flags=re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

_SCIENTIFIC_FIELDS = (
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "source",
    "target",
    "paper_title",
    "paper_abstract",
    "methods",
    "experiments",
    "baselines",
    "metrics",
    "results",
)

_KEY_ALIASES: dict[str, str] = {
    "problemstatement": "problem_statement",
    "待研究问题": "problem_statement",
    "问题陈述": "problem_statement",
    "rationale": "rationale",
    "解决思路": "rationale",
    "研究思路": "rationale",
    "technicaldetails": "technical_details",
    "必要的技术手段": "technical_details",
    "技术细节": "technical_details",
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
    "references": "references",
    "reference": "references",
    "参考文献": "references",
}


class ContestDirectPlanError(RuntimeError):
    """Raised when a one-shot plan cannot be projected into the minimal contract."""


def _contains_chinese(text: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in text)


class ContestDirectScientificPlan(StrictFrozenModel):
    """Scientific fields authored by the configured model.

    Only presence and Chinese report language are checked.  English paper titles,
    method names, dataset identifiers, formulae, URLs, and bibliography entries are
    explicitly allowed.
    """

    problem_statement: str
    rationale: str
    technical_details: str
    datasets: str
    source: str
    target: str
    paper_title: str
    paper_abstract: str
    methods: str
    experiments: str
    baselines: str
    metrics: str
    results: str
    references: tuple[str, ...] = ()

    @field_validator(*_SCIENTIFIC_FIELDS)
    @classmethod
    def _require_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("research-plan fields must not be blank")
        return normalized

    @field_validator(
        "problem_statement",
        "rationale",
        "technical_details",
        "datasets",
        "paper_abstract",
        "methods",
        "experiments",
        "results",
    )
    @classmethod
    def _require_chinese_report_prose(cls, value: str) -> str:
        if not _contains_chinese(value):
            raise ValueError("research-plan prose must contain Chinese")
        return value

    @field_validator("references")
    @classmethod
    def _normalize_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
        return normalized


class ContestReferenceProjectionAudit(StrictFrozenModel):
    """Distinguish model-selected references from deterministic supplementation."""

    policy: Literal[
        "locked-ranked-catalog-model-preference-then-backfill-v1",
        "locked-catalog-exact-order-v2",
    ] = "locked-ranked-catalog-model-preference-then-backfill-v1"
    catalog_count: int = Field(ge=0)
    model_selected_indices: tuple[int, ...] = ()
    program_supplemented_indices: tuple[int, ...] = ()
    final_reference_count: int = Field(ge=0, le=MAX_RESEARCH_PLAN_REFERENCES)
    catalog_entries_invented: Literal[False] = False

    @model_validator(mode="after")
    def _validate_projection(self) -> ContestReferenceProjectionAudit:
        indices = (*self.model_selected_indices, *self.program_supplemented_indices)
        if len(indices) != self.final_reference_count or len(set(indices)) != len(indices):
            raise ValueError("reference projection indices do not match final bibliography")
        if any(index < 1 or index > self.catalog_count for index in indices):
            raise ValueError("reference projection index escapes locked catalog")
        if self.policy == "locked-catalog-exact-order-v2":
            expected_count = min(self.catalog_count, MAX_RESEARCH_PLAN_REFERENCES)
            if self.final_reference_count != expected_count:
                raise ValueError("exact-order projection count differs from the bounded catalog")
            if set(indices) != set(range(1, expected_count + 1)):
                raise ValueError("exact-order projection does not cover the bounded catalog")
        return self


class ContestDirectPlanArtifact(StrictFrozenModel):
    """Program-addressed result of one direct research-plan generation call."""

    schema_version: Literal["contest-direct-research-plan-v1"] = "contest-direct-research-plan-v1"
    document_type: Literal["科学假设与研究计划"] = "科学假设与研究计划"
    plan_id: str = Field(pattern=r"^direct-plan-[0-9a-f]{16}$")
    status: Literal["research_plan_generated"] = "research_plan_generated"
    scientific_problem: str
    literature_context_provided: bool
    preexperiment_context_status: Literal["not_provided", "provided_as_input_context"]
    plan: ContestDirectScientificPlan
    reference_projection: ContestReferenceProjectionAudit | None = None
    provider: str
    model_name: str
    generation_calls: Literal[1] = 1
    json_repair_applied: bool
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_program_projection(self) -> ContestDirectPlanArtifact:
        expected_id = f"direct-plan-{self.input_hash[:16]}"
        if self.plan_id != expected_id:
            raise ValueError("plan_id does not match the program-computed input hash")
        hash_payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        expected_hashes = {canonical_model_hash(hash_payload)}
        if self.reference_projection is None:
            legacy_payload = dict(hash_payload)
            legacy_payload.pop("reference_projection", None)
            expected_hashes.add(canonical_model_hash(legacy_payload))
        if self.artifact_hash not in expected_hashes:
            raise ValueError("direct research-plan artifact hash mismatch")
        return self


def build_contest_direct_plan_messages(
    *,
    scientific_problem: str,
    literature_context: Sequence[str] | None = None,
    preexperiment_context: Any | None = None,
    method_skills: Sequence[str] | None = None,
    temporary_agent_context: Any | None = None,
) -> list[dict[str, str]]:
    """Build the one-shot Chinese authoring prompt without prescribing the solution."""

    problem = scientific_problem.strip()
    if not problem:
        raise ContestDirectPlanError("scientific_problem must not be blank")
    literature = _normalize_literature(literature_context)
    skills = _normalize_literature(method_skills)
    preexperiment = _render_context(preexperiment_context)
    temporary_context = _render_context(temporary_agent_context)
    literature_block = (
        "\n".join(f"[{index}] {item}" for index, item in enumerate(literature, start=1))
        if literature
        else "未提供文献；不要虚构参考文献。"
    )
    preexperiment_block = preexperiment or (
        "本次交付范围止于研究计划。Results 第一行必须写“本交付范围为研究计划”，"
        "随后仅写预期结果、可检验判据和可能的负结果，禁止捏造已执行数据或数值。"
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是自主科研智能体。遵循证据优先的方法：区分已知事实、推断、"
                "待验证假设和实际观察；围绕一个可反驳的主假设组织研究，明确主要"
                "结局、对照、失败判据和复现路径；不要用方法堆砌代替科学问题。"
                "你自主完成科学推理，但不输出隐含思考过程，只输出任务要求的结果。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "research_question_and_delivery_requirements",
                    "scientific_problem": problem,
                    "requirements_zh": [
                        "输出完整中文《科学假设与研究计划》",
                        "报告标题和说明文字使用中文，技术名、公式与真实论文题名可保留英文",
                        "这是研究计划而非已完成论文",
                        "围绕一个可证伪主假设形成可执行研究路径",
                        "交付范围止于研究计划时不得虚构结果或数值",
                        "不得把有限计算写成开放数学问题的证明",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    if skills:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "system_selected_project_method_skills",
                        "boundary_zh": (
                            "以下SKILL.md只提供学科方法和优秀研究路径，不是题目答案、"
                            "事实证据、实验结果或指定结论。"
                        ),
                        "selected_method_skills": [
                            {
                                "content": content,
                                "content_sha256": hashlib.sha256(
                                    content.encode("utf-8")
                                ).hexdigest(),
                            }
                            for content in skills
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if temporary_context:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "archived_temporary_agent_advice",
                        "boundary_zh": (
                            "以下内容由当前主阶段Agent派发的一次性临时子Agent产生，"
                            "其运行身份已经归档并消失。它们只是可自由采纳、合并、改写或"
                            "全部拒绝的研究建议，不要求逐条覆盖，不是事实证据、实验结果、"
                            "审批结论或强制答案。"
                        ),
                        "advice": temporary_context,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": (
                f"可用真实文献：\n{literature_block}\n\n"
                f"可用预实验上下文：\n{preexperiment_block}\n\n"
                "请一次性输出一个 JSON 对象，科学内容全部由你生成。对象字段为："
                "problem_statement、rationale、technical_details、datasets、source、"
                "target、paper_title、paper_abstract、methods、experiments、baselines、"
                "metrics、results、references。references 只输出所选文献编号数组；"
                f"目录足够时建议选择{MIN_RESEARCH_PLAN_REFERENCES}–"
                f"{MAX_RESEARCH_PLAN_REFERENCES}条实际支持本计划的文献。"
                "若你只返回少量关键编号，程序会从同一锁定真实目录按既定相关性排序"
                "补足书目，不会新增目录外文献。paper_title 和除 references 外的字段"
                "均使用中文说明；不要"
                "为凑长度重复内容。每个字段必须是语义完整的句子，不能在句中截断。"
                "Experiments 要写清可执行步骤，"
                "Baselines 和 Metrics 要能检验假设。References 只能逐项使用上面提供"
                "的真实文献，不得新增或猜测条目。若有预实验上下文，只能复述其中"
                "真实出现的结果；若交付范围止于研究计划，paper_abstract 必须使用将来时或计划语气，"
                "不得写成‘已经发现、已经验证、结果表明’，results 第一行必须明确"
                "‘本交付范围为研究计划’，并只给可检验判据、支持/反驳/不确定三种判定。"
                "没有先验证据时不要臆造预期效应量、p值或确定的胜负结论。资源规模"
                "必须能在普通工作站上完成；不要声称解决黎曼猜想等开放难题。"
                "Datasets/Source/Target 与 Technical Details、Methods、Experiments 中的"
                "数据规模必须完全一致，同一数值区间不得在不同字段写成不同上界。"
                "不得把微弱或未解释的效应归因到任何命名的数学猜想或机制"
                "（Hardy-Littlewood、黎曼、Cramér、k-tuple、二级项、猜想等），"
                "即使以「可能是」方式提及也禁止；只能用描述性表述（如更高阶模算术约束、"
                "有限样本偏差），并明确这些只是待检验假设而非已证实机制。"
            ),
        }
    )
    return messages


def generate_contest_direct_plan(
    *,
    scientific_problem: str,
    literature_context: Sequence[str] | None = None,
    preexperiment_context: Any | None = None,
    method_skills: Sequence[str] | None = None,
    temporary_agent_context: Any | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    output_path: Path | str | None = None,
    markdown_path: Path | str | None = None,
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    thinking_mode: Literal["enabled", "disabled"] = "enabled",
    thinking_budget: int | None = 4_000,
    temperature: float = 0.2,
    llm_call: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
) -> ContestDirectPlanArtifact:
    """Generate, project, and optionally persist one Chinese research plan.

    Exactly one provider call is made.  Scientific-schema failures are returned as an
    error instead of triggering a rewrite loop.  The sole recovery path repairs the
    already-returned JSON text locally.
    """

    literature = _normalize_literature(literature_context)
    skills = _normalize_literature(method_skills)
    rendered_preexperiment = _render_context(preexperiment_context)
    rendered_temporary_context = _render_context(temporary_agent_context)
    input_payload = {
        "scientific_problem": scientific_problem.strip(),
        "literature_context": list(literature),
        "preexperiment_context": rendered_preexperiment,
        "temporary_agent_context": rendered_temporary_context,
        "method_skill_sha256": [
            hashlib.sha256(content.encode("utf-8")).hexdigest() for content in skills
        ],
    }
    if not input_payload["scientific_problem"]:
        raise ContestDirectPlanError("scientific_problem must not be blank")
    if thinking_mode == "enabled" and (thinking_budget is None or thinking_budget < 1):
        raise ContestDirectPlanError("thinking_budget must be positive when thinking is enabled")
    if thinking_mode == "disabled" and thinking_budget is not None:
        raise ContestDirectPlanError("thinking_budget must be None when thinking is disabled")
    input_hash = canonical_model_hash(input_payload)
    messages = build_contest_direct_plan_messages(
        scientific_problem=scientific_problem,
        literature_context=literature,
        preexperiment_context=preexperiment_context,
        method_skills=skills,
        temporary_agent_context=temporary_agent_context,
    )

    repaired = False
    try:
        completion = llm_call(
            messages=messages,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_mode=thinking_mode,
            thinking_budget=thinking_budget,
        )
        raw_response = completion.response_text
        parsed = completion.parsed_json
        provider = completion.provider
        model_name = completion.model_name
    except LLMClientError as exc:
        if not exc.response_text:
            raise ContestDirectPlanError(str(exc)) from exc
        try:
            parsed = _repair_json_object_once(exc.response_text)
        except (json.JSONDecodeError, ValueError) as repair_exc:
            raise ContestDirectPlanError(
                "model response was not a recoverable JSON object"
            ) from repair_exc
        raw_response = exc.response_text
        provider, model_name = _configured_model_identity(config_path)
        repaired = True

    response_hash = canonical_model_hash({"response_text": raw_response})
    if output_path is not None:
        response_path = (
            Path(output_path).expanduser().resolve().parent
            / "responses"
            / f"direct-plan-{input_hash[:16]}-{response_hash[:12]}.txt"
        )
        _write_immutable_bytes(response_path, raw_response.encode("utf-8"))

    normalized_payload, reference_projection = _normalize_scientific_payload(
        parsed, literature=literature
    )
    try:
        scientific_plan = ContestDirectScientificPlan.model_validate(normalized_payload)
    except ValidationError as exc:
        raise ContestDirectPlanError(
            "one-shot model response omitted required Chinese research-plan content: " f"{exc}"
        ) from exc

    artifact_payload: dict[str, Any] = {
        "schema_version": "contest-direct-research-plan-v1",
        "document_type": "科学假设与研究计划",
        "plan_id": f"direct-plan-{input_hash[:16]}",
        "status": "research_plan_generated",
        "scientific_problem": scientific_problem.strip(),
        "literature_context_provided": bool(literature),
        "preexperiment_context_status": (
            "provided_as_input_context" if rendered_preexperiment else "not_provided"
        ),
        "plan": scientific_plan.model_dump(mode="json"),
        "reference_projection": ContestReferenceProjectionAudit(
            policy="locked-catalog-exact-order-v2",
            catalog_count=reference_projection.catalog_count,
            model_selected_indices=reference_projection.model_selected_indices,
            program_supplemented_indices=reference_projection.program_supplemented_indices,
            final_reference_count=len(reference_projection.references),
        ).model_dump(mode="json"),
        "provider": provider,
        "model_name": model_name,
        "generation_calls": 1,
        "json_repair_applied": repaired,
        "input_hash": input_hash,
        "model_response_hash": response_hash,
    }
    artifact_payload["artifact_hash"] = canonical_model_hash(artifact_payload)
    artifact = ContestDirectPlanArtifact.model_validate(artifact_payload)

    if output_path is not None:
        write_json_model(output_path, artifact)
    if markdown_path is not None:
        destination = Path(markdown_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_contest_direct_plan_markdown(artifact), encoding="utf-8")
    return artifact


def load_contest_direct_plan(path: Path | str) -> ContestDirectPlanArtifact:
    """Load a persisted direct plan and re-check its program-computed hash."""

    return ContestDirectPlanArtifact.model_validate_json(Path(path).read_text(encoding="utf-8"))


def render_contest_direct_plan_markdown(artifact: ContestDirectPlanArtifact) -> str:
    """Render the competition template fields in Chinese Markdown."""

    plan = artifact.plan
    references = (
        "\n".join(f"{index}. {item}" for index, item in enumerate(plan.references, start=1))
        if plan.references
        else "未提供可核验参考文献。"
    )
    return (
        "\n\n".join(
            (
                f"# {plan.paper_title}",
                f"> 文档类型：{artifact.document_type}（不是已完成论文）",
                f"## 待研究问题（Problem Statement）\n\n{plan.problem_statement}",
                f"## 解决思路（Rationale）\n\n{plan.rationale}",
                f"## 必要的技术手段（Technical Details）\n\n{plan.technical_details}",
                f"## 数据集（Datasets）\n\n{plan.datasets}",
                f"### Source\n\n{plan.source}",
                f"### Target\n\n{plan.target}",
                f"## 标题（Paper Title）\n\n{plan.paper_title}",
                f"## 摘要（Paper Abstract）\n\n{plan.paper_abstract}",
                f"## 方法论（Methods）\n\n{plan.methods}",
                f"## 实验设计（Experiments）\n\n{plan.experiments}",
                f"### 基线（Baselines）\n\n{plan.baselines}",
                f"### 评估指标（Metrics）\n\n{plan.metrics}",
                f"## 实验结果（Results）\n\n{plan.results}",
                f"## 参考论文（References）\n\n{references}",
            )
        )
        + "\n"
    )


def contest_direct_plan_template_payload(
    artifact: ContestDirectPlanArtifact,
) -> dict[str, Any]:
    """Project an artifact into the flat payload consumed by contest renderers."""

    plan = artifact.plan
    return {
        "title": plan.paper_title,
        "abstract": plan.paper_abstract,
        "problem_statement": plan.problem_statement,
        "rationale": plan.rationale,
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
        "results": plan.results,
        "references": list(plan.references),
    }


def _normalize_key(key: str) -> str:
    for candidate in (
        key,
        re.sub(r"[（(][^）)]*[）)]", "", key),
    ):
        compact = re.sub(r"[\s_()（）:：/\-]+", "", candidate).casefold()
        if compact in _KEY_ALIASES:
            return _KEY_ALIASES[compact]
    return key.strip().casefold().replace(" ", "_")


def _normalize_scientific_payload(
    payload: Mapping[str, Any],
    *,
    literature: tuple[str, ...],
) -> tuple[dict[str, Any], LockedReferenceProjection]:
    normalized = {_normalize_key(str(key)): value for key, value in payload.items()}
    discovered: dict[str, Any] = {}
    _collect_scientific_candidates(payload, discovered)
    for field, value in discovered.items():
        if normalized.get(field) is None:
            normalized[field] = value

    datasets = normalized.get("datasets")
    if isinstance(datasets, Mapping):
        dataset_mapping = {_normalize_key(str(key)): value for key, value in datasets.items()}
        normalized["datasets"] = _first_text(
            dataset_mapping,
            ("datasets", "description", "说明", "name", "名称"),
        ) or _text_value(datasets)
        normalized.setdefault("source", dataset_mapping.get("source"))
        normalized.setdefault("target", dataset_mapping.get("target"))

    experiments = normalized.get("experiments")
    if isinstance(experiments, Mapping):
        experiment_mapping = {_normalize_key(str(key)): value for key, value in experiments.items()}
        normalized["experiments"] = _first_text(
            experiment_mapping,
            ("experiments", "design", "procedure", "步骤", "说明"),
        ) or _text_value(experiments)
        normalized.setdefault("baselines", experiment_mapping.get("baselines"))
        normalized.setdefault("metrics", experiment_mapping.get("metrics"))

    for field in _SCIENTIFIC_FIELDS:
        if field in normalized:
            normalized[field] = _text_value(normalized[field])

    # Bibliographic provenance comes only from caller-supplied real literature.  The
    # model selects catalog indices; the program projects their locked full metadata.
    reference_projection = project_locked_reference_selection(
        normalized.get("references"), literature
    )
    normalized["references"] = reference_projection.references
    return (
        {field: normalized.get(field) for field in (*_SCIENTIFIC_FIELDS, "references")},
        reference_projection,
    )


def _collect_scientific_candidates(
    value: Any,
    discovered: dict[str, Any],
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = _normalize_key(str(key))
            if normalized_key in (*_SCIENTIFIC_FIELDS, "references"):
                discovered.setdefault(normalized_key, item)
            _collect_scientific_candidates(item, discovered)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            _collect_scientific_candidates(item, discovered)


def _first_text(values: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        if key in values and values[key] is not None:
            text = _text_value(values[key])
            if text:
                return text
    return ""


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}：{_text_value(item)}" for key, item in value.items() if item is not None
        )
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return "；".join(_text_value(item) for item in value if item is not None)
    return "" if value is None else str(value).strip()


def _normalize_literature(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _project_reference_selection(value: Any, literature: tuple[str, ...]) -> tuple[str, ...]:
    return project_locked_reference_selection(value, literature).references


def _render_context(value: Any | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _repair_json_object_once(text: str) -> dict[str, Any]:
    candidate = _JSON_FENCE.sub("", text.strip()).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    candidate = _TRAILING_COMMA.sub(r"\1", candidate[start : end + 1])
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("top-level JSON value is not an object")
    return parsed


def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != payload:
            raise ContestDirectPlanError(
                f"existing raw model response differs from retained bytes: {path}"
            ) from None


def _configured_model_identity(config_path: Path | str) -> tuple[str, str]:
    path = Path(config_path)
    config = (
        ConfigParser().parse_file(path, model_type=SystemConfig)
        if path.exists()
        else SystemConfig()
    )
    if not isinstance(config, SystemConfig):
        raise ContestDirectPlanError("configured LLM settings are not a SystemConfig")
    return config.deployment.llm.provider, config.deployment.llm.model_name


__all__ = [
    "ContestDirectPlanArtifact",
    "ContestDirectPlanError",
    "ContestDirectScientificPlan",
    "build_contest_direct_plan_messages",
    "contest_direct_plan_template_payload",
    "generate_contest_direct_plan",
    "load_contest_direct_plan",
    "render_contest_direct_plan_markdown",
]
