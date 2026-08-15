"""Temporary-Qwen contributions for the direct contest research-plan stage.

The adapter intentionally does not issue a stage controller.  The current stage
main agent must supply its live, in-memory dispatch capability.  Three bounded
content workers then run in parallel and disappear after archival; only their
Chinese suggestions and exact authorship receipts remain for the plan author.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveRecord,
    TemporaryAgentInputRef,
    TemporaryAgentTaskKind,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.temporary_qwen_pool import (
    CompletionCallable,
    TemporaryQwenBatchArtifact,
    TemporaryQwenBatchError,
    TemporaryQwenContentTask,
    TemporaryQwenPoolError,
    TemporaryQwenSkillContext,
    run_temporary_qwen_content_batch,
)
from autoresearch.kernel.contracts import Sha256, StableId, canonical_sha256
from autoresearch.llm.client import run_llm_json_completion

ContestTemporaryRole = Literal[
    "hypothesis_candidates",
    "experiment_design",
    "adversarial_critique",
]

_ROLE_ORDER: tuple[ContestTemporaryRole, ...] = (
    "hypothesis_candidates",
    "experiment_design",
    "adversarial_critique",
)


@dataclass(frozen=True)
class _RoleSpec:
    role: ContestTemporaryRole
    task_kind: TemporaryAgentTaskKind
    instruction: str


_ROLE_SPECS = (
    _RoleSpec(
        role="hypothesis_candidates",
        task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
        instruction=(
            "围绕给定科学问题与交付要求，提出一至三个值得最终计划作者考虑的可检验候选假设。"
            "说明为什么值得检验以及什么观察会反驳它；不要撰写完整研究计划，不得声称实验已经完成。"
        ),
    ),
    _RoleSpec(
        role="experiment_design",
        task_kind=TemporaryAgentTaskKind.CONTENT_CHECKLIST,
        instruction=(
            "围绕给定科学问题与交付要求，提出一个普通计算环境可以起步的预实验设计建议。"
            "给出数据、对照、指标和失败判据；不要替最终计划作者作结论，不得虚构实验结果。"
        ),
    ),
    _RoleSpec(
        role="adversarial_critique",
        task_kind=TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
        instruction=(
            "从反方审查给定科学问题可能采用的研究路径，找出最容易造成伪创新、混淆或过度外推的风险。"
            "提出能保留创造性又降低这些风险的修正建议；不要生成完整研究计划。"
        ),
    ),
)


class ContestDirectTemporaryContribution(StrictFrozenModel):
    """One retained contribution from an already-archived runtime identity."""

    role: ContestTemporaryRole
    dispatch_id: StableId
    temporary_agent_id: StableId
    result_hash: Sha256
    output_payload: dict[str, JsonValue] = Field(min_length=1)
    output_payload_sha256: Sha256
    archive_hash: Sha256
    authorship_receipt_hash: Sha256
    runtime_identity_removed: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_output_hash(self) -> ContestDirectTemporaryContribution:
        if self.output_payload_sha256 != canonical_sha256(self.output_payload):
            raise TemporaryQwenPoolError("contest temporary contribution hash mismatch")
        return self


class ContestDirectTemporaryStageArtifact(StrictFrozenModel):
    """Stable hand-off from three archived contributors to the plan author."""

    schema_version: Literal["contest-direct-temporary-stage-v1"] = (
        "contest-direct-temporary-stage-v1"
    )
    question_sha256: Sha256
    requirements_sha256: Sha256
    literature_catalog: tuple[str, ...]
    controller_binding_hash: Sha256
    batch: TemporaryQwenBatchArtifact
    contributions: tuple[ContestDirectTemporaryContribution, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    status: Literal["complete", "degraded"]
    unavailable_roles: tuple[ContestTemporaryRole, ...] = Field(max_length=3)
    artifact_relative_path: str = Field(min_length=1)
    dispatched_by_current_stage_main_agent: Literal[True] = True
    all_runtime_identities_removed: Literal[True] = True
    outputs_and_receipts_retained: Literal[True] = True
    content_is_scientific_evidence: Literal[False] = False
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_stage_binding(self) -> ContestDirectTemporaryStageArtifact:
        if self.batch.controller_binding_hash != self.controller_binding_hash:
            raise TemporaryQwenPoolError("contest temporary batch belongs to another controller")
        if self.batch.dispatched_count != 3:
            raise TemporaryQwenPoolError("contest temporary stage requires three dispatched agents")
        available_roles = tuple(item.role for item in self.contributions)
        expected_available = tuple(
            role for role in _ROLE_ORDER if role not in self.unavailable_roles
        )
        if available_roles != expected_available:
            raise TemporaryQwenPoolError(
                "contest temporary contributions use an invalid role order"
            )
        expected_status = "complete" if self.batch.succeeded_count == 3 else "degraded"
        if self.status != expected_status:
            raise TemporaryQwenPoolError("contest temporary stage status mismatch")
        if len(self.contributions) != self.batch.succeeded_count:
            raise TemporaryQwenPoolError("contest temporary contribution count mismatch")
        if len(self.unavailable_roles) != self.batch.failed_count:
            raise TemporaryQwenPoolError("contest temporary unavailable-role count mismatch")

        records = {item.dispatch_id: item for item in self.batch.task_records}
        outputs = {item.dispatch_id: item for item in self.batch.stable_outputs}
        for contribution in self.contributions:
            record = records.get(contribution.dispatch_id)
            output = outputs.get(contribution.dispatch_id)
            if record is None or output is None:
                raise TemporaryQwenPoolError("contest temporary contribution is absent from batch")
            if (
                record.temporary_agent_id != contribution.temporary_agent_id
                or record.result_hash != contribution.result_hash
                or record.archive_hash != contribution.archive_hash
                or record.authorship_receipt_hash != contribution.authorship_receipt_hash
                or output.output_payload_sha256 != contribution.output_payload_sha256
                or output.output_payload != contribution.output_payload
            ):
                raise TemporaryQwenPoolError("contest temporary contribution binding mismatch")

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise TemporaryQwenPoolError("contest temporary stage artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectTemporaryStageArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)

    def plan_context_payload(self) -> dict[str, JsonValue]:
        """Project retained suggestions without promoting them to evidence or conclusions."""

        return {
            "上下文类型": "当前研究计划阶段的临时子Agent建议",
            "运行状态": self.status,
            "使用边界": (
                "以下内容仅是并行候选意见，不是证据、实验结果或最终结论；"
                "最终计划主Agent应自主取舍并保持与真实来源一致。"
            ),
            "临时建议": [
                {
                    "角色": contribution.role,
                    "内容": {
                        "memo_cn": contribution.output_payload["memo_cn"],
                        "reference_indices": _admitted_reference_indices(
                            contribution.output_payload.get("reference_indices"),
                            catalog_size=len(self.literature_catalog),
                        ),
                    },
                    "内容哈希": contribution.output_payload_sha256,
                }
                for contribution in self.contributions
            ],
            "未获得建议的角色": list(self.unavailable_roles),
        }


def build_contest_first_question_temporary_tasks(
    *,
    question: str,
    requirements: str,
    question_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    selected_skill_contexts: Sequence[TemporaryQwenSkillContext] = (),
    literature_catalog: Sequence[str] = (),
    max_tokens_per_agent: int = 3_000,
    timeout_seconds: int = 300,
) -> tuple[TemporaryQwenContentTask, ...]:
    """Build the exact three content-only assignments selected by the main stage."""

    clean_question = question.strip()
    clean_requirements = requirements.strip()
    if not clean_question or not clean_requirements:
        raise ValueError("contest question and requirements must be non-empty")
    skill_contexts = tuple(selected_skill_contexts)
    clean_literature_catalog = tuple(item.strip() for item in literature_catalog if item.strip())
    input_digest = canonical_sha256(
        {
            "question": clean_question,
            "requirements": clean_requirements,
            "question_ref": question_ref.model_dump(mode="json"),
            "selected_skills": [item.skill_ref.model_dump(mode="json") for item in skill_contexts],
            "literature_catalog": list(clean_literature_catalog),
        }
    )
    tasks: list[TemporaryQwenContentTask] = []
    for index, spec in enumerate(_ROLE_SPECS, start=1):
        schema = _memo_schema()
        role_slug = spec.role.replace("_", "-")
        tasks.append(
            TemporaryQwenContentTask(
                dispatch_id=f"contest-direct-{input_digest[:16]}-{index}-{role_slug}",
                temporary_agent_id=f"temporary-{input_digest[:16]}-{role_slug}",
                parent_task_id=parent_task_id,
                task_kind=spec.task_kind,
                task_instruction=spec.instruction,
                input_refs=(question_ref,),
                input_payload={
                    "科学问题": clean_question,
                    "交付要求": clean_requirements,
                    "可用文献编号目录": [
                        {"index": index, "citation": citation}
                        for index, citation in enumerate(clean_literature_catalog, start=1)
                    ],
                    "文献边界": "如需提及文献，只能返回上述目录中的编号，不得新增文献。",
                    "阶段边界": (
                        "只提供本角色的候选意见；不得执行实验、伪造结果、审批或输出完整计划。"
                    ),
                },
                expected_output_schema=schema,
                chinese_output_fields=("memo_cn",),
                skill_contexts=skill_contexts,
                max_tokens=max_tokens_per_agent,
                timeout_seconds=timeout_seconds,
                max_attempts=1,
            )
        )
    return tuple(tasks)


def run_contest_first_question_temporary_stage(
    *,
    question: str,
    requirements: str,
    question_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    output_dir: Path | str,
    selected_skill_contexts: Sequence[TemporaryQwenSkillContext] = (),
    literature_catalog: Sequence[str] = (),
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_tokens_per_agent: int = 3_000,
    timeout_seconds: int = 300,
    thinking_budget: int = 4_000,
    temperature: float = 0.35,
    clock: datetime | None = None,
) -> ContestDirectTemporaryStageArtifact:
    """Run, archive, and retain the three first-question contributors in parallel."""

    if controller.max_parallel_agents < 3:
        raise TemporaryQwenPoolError(
            "contest temporary stage requires a controller limit of at least three"
        )
    capability.require_valid(controller)
    tasks = build_contest_first_question_temporary_tasks(
        question=question,
        requirements=requirements,
        question_ref=question_ref,
        parent_task_id=parent_task_id,
        selected_skill_contexts=selected_skill_contexts,
        literature_catalog=literature_catalog,
        max_tokens_per_agent=max_tokens_per_agent,
        timeout_seconds=timeout_seconds,
    )
    input_digest = _task_set_digest(tasks)
    try:
        batch = run_temporary_qwen_content_batch(
            batch_id=f"contest-direct-temporary-{input_digest[:20]}",
            controller=controller,
            capability=capability,
            tasks=tasks,
            output_dir=output_dir,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=3,
            thinking_budget=thinking_budget,
            temperature=temperature,
            clock=clock,
        )
    except TemporaryQwenBatchError as exc:
        # A role-level failure is retained negative information.  It does not
        # prevent the current main agent from authoring the research plan.
        batch = exc.artifact
    if capability.active:
        raise TemporaryQwenPoolError("temporary stage capability remained active after archival")

    output_root = Path(output_dir).resolve()
    role_by_dispatch = {
        task.dispatch_id: spec.role for task, spec in zip(tasks, _ROLE_SPECS, strict=True)
    }
    record_by_dispatch = {item.dispatch_id: item for item in batch.task_records}
    output_by_dispatch = {item.dispatch_id: item for item in batch.stable_outputs}
    contributions: list[ContestDirectTemporaryContribution] = []
    unavailable_roles: list[ContestTemporaryRole] = []
    for task, spec in zip(tasks, _ROLE_SPECS, strict=True):
        record = record_by_dispatch[task.dispatch_id]
        archive = _load_archive(output_root, record.archive_relative_path)
        if (
            not archive.runtime_identity_inactive
            or not archive.runtime_identity_removed
            or archive.temporary_agent_id != task.temporary_agent_id
        ):
            raise TemporaryQwenPoolError("temporary runtime identity was not removed")
        stable_output = output_by_dispatch.get(task.dispatch_id)
        if stable_output is None:
            unavailable_roles.append(spec.role)
            continue
        if record.result_hash is None or record.authorship_receipt_hash is None:
            raise TemporaryQwenPoolError(
                "successful temporary result or authorship receipt was not retained"
            )
        contributions.append(
            ContestDirectTemporaryContribution(
                role=role_by_dispatch[task.dispatch_id],
                dispatch_id=task.dispatch_id,
                temporary_agent_id=task.temporary_agent_id,
                result_hash=record.result_hash,
                output_payload=stable_output.output_payload,
                output_payload_sha256=stable_output.output_payload_sha256,
                archive_hash=archive.archive_hash,
                authorship_receipt_hash=record.authorship_receipt_hash,
            )
        )
        if spec.role != role_by_dispatch[task.dispatch_id]:  # pragma: no cover - static binding
            raise TemporaryQwenPoolError("temporary role binding changed during dispatch")

    artifact_relative_path = (
        PurePosixPath("temporary-agents")
        / "contest-direct-stage"
        / f"{batch.artifact_hash[:24]}.json"
    ).as_posix()
    artifact = ContestDirectTemporaryStageArtifact.create(
        schema_version="contest-direct-temporary-stage-v1",
        question_sha256=hashlib.sha256(question.strip().encode("utf-8")).hexdigest(),
        requirements_sha256=hashlib.sha256(requirements.strip().encode("utf-8")).hexdigest(),
        literature_catalog=tuple(item.strip() for item in literature_catalog if item.strip()),
        controller_binding_hash=controller.binding_hash,
        batch=batch,
        contributions=tuple(contributions),
        status="complete" if batch.succeeded_count == 3 else "degraded",
        unavailable_roles=tuple(unavailable_roles),
        artifact_relative_path=artifact_relative_path,
    )
    write_json_model(_resolve_inside(output_root, artifact_relative_path), artifact)
    return artifact


def _memo_schema() -> dict[str, JsonValue]:
    return {
        "type": "object",
        "required": ["memo_cn"],
        "properties": {
            "memo_cn": {"type": "string"},
            "reference_indices": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "additionalProperties": False,
    }


def _admitted_reference_indices(value: JsonValue, *, catalog_size: int) -> list[JsonValue]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and 1 <= item <= catalog_size
    ]


def _task_set_digest(tasks: tuple[TemporaryQwenContentTask, ...]) -> str:
    return canonical_sha256(
        [
            {
                "dispatch_id": task.dispatch_id,
                "temporary_agent_id": task.temporary_agent_id,
                "input_payload": task.input_payload,
                "skill_refs": [
                    item.skill_ref.model_dump(mode="json") for item in task.skill_contexts
                ],
            }
            for task in tasks
        ]
    )


def _load_archive(output_root: Path, relative_path: str) -> TemporaryAgentArchiveRecord:
    path = _resolve_inside(output_root, relative_path)
    return TemporaryAgentArchiveRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_inside(output_root: Path, relative_path: str) -> Path:
    candidate = (output_root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError as exc:
        raise TemporaryQwenPoolError("contest temporary artifact escapes output directory") from exc
    return candidate


__all__ = [
    "ContestDirectTemporaryContribution",
    "ContestDirectTemporaryStageArtifact",
    "ContestTemporaryRole",
    "build_contest_first_question_temporary_tasks",
    "run_contest_first_question_temporary_stage",
]
