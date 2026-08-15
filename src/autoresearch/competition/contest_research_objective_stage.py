"""Flexible research-objective formation before a contest research plan.

The stage has two caller-selected entry modes:

* ``specified_question`` asks several temporary agents to explore falsifiable
  hypotheses for one concrete scientific question.
* ``specified_direction`` requires a caller-supplied, provenance-bearing
  literature catalog and asks the same agents to derive research objectives from
  that retrieved evidence boundary.

Both modes finish with a separate temporary reviewer.  The language model only
returns Chinese scientific content and catalog numbers.  Candidate identifiers,
hashes, lifecycle state, and number-to-identifier projection are computed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    issue_stage_controller,
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

ContestResearchObjectiveMode = Literal["specified_question", "specified_direction"]
ContestResearchObjectiveRole = Literal[
    "falsifiable_hypothesis_explorer",
    "method_bridge_explorer",
    "assumption_challenger",
]

_ROLE_SPECS: tuple[tuple[ContestResearchObjectiveRole, str], ...] = (
    (
        "falsifiable_hypothesis_explorer",
        "自由探索一个或多个可证伪假设，说明可能支持它们的观察以及能够推翻它们的观察。"
        "优先寻找真正有信息增益的问题，不要撰写完整研究计划，也不得声称实验已经执行。",
    ),
    (
        "method_bridge_explorer",
        "结合题目、已选方法技能与允许使用的真实检索目录，寻找可操作的研究目标或方法桥接。"
        "同时给出普通工作站能够起步的最小预实验建议，明确可用数据、必要对照、主要指标"
        "与失败判据。可以提出与常规路线不同的方案，但不得虚构来源或结果。",
    ),
    (
        "assumption_challenger",
        "挑战该问题或方向中的默认假设，尝试提出竞争解释、反直觉假设或跨领域类比。"
        "保留创造性，同时说明如何通过数据或实验将其与替代解释区分开。",
    ),
)


class ContestResearchObjectiveStageError(RuntimeError):
    """Raised when the objective stage cannot produce a trusted reviewed result."""

    def __init__(
        self,
        message: str,
        *,
        review_attempt_batches: tuple[TemporaryQwenBatchArtifact, ...] = (),
    ) -> None:
        self.review_attempt_batches = review_attempt_batches
        super().__init__(message)


class ContestRetrievedLiteratureEntry(StrictFrozenModel):
    """One normalized entry copied from a caller-owned real retrieval record."""

    catalog_index: int = Field(ge=1)
    record_id: StableId
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    retrieved_from: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)
    abstract_or_excerpt: str | None = None
    authors: tuple[str, ...] = ()
    doi: str | None = None
    source_payload_sha256: Sha256

    @model_validator(mode="after")
    def _validate_program_identity(self) -> ContestRetrievedLiteratureEntry:
        payload = self.model_dump(
            mode="json",
            exclude={"catalog_index", "record_id", "source_payload_sha256"},
        )
        expected_hash = canonical_sha256(payload)
        if self.source_payload_sha256 != expected_hash:
            raise ContestResearchObjectiveStageError("retrieved literature hash mismatch")
        expected_id = f"retrieved-literature-{expected_hash[:24]}"
        if self.record_id != expected_id:
            raise ContestResearchObjectiveStageError("retrieved literature id mismatch")
        return self


class ContestResearchObjectiveCandidate(StrictFrozenModel):
    """One accepted model-authored candidate with a program-computed identity."""

    candidate_number: int = Field(ge=1)
    candidate_id: StableId
    role: ContestResearchObjectiveRole
    dispatch_id: StableId
    output_payload: dict[str, JsonValue] = Field(min_length=1)
    output_payload_sha256: Sha256
    reference_indices: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _validate_candidate_identity(self) -> ContestResearchObjectiveCandidate:
        if self.output_payload_sha256 != canonical_sha256(self.output_payload):
            raise ContestResearchObjectiveStageError("research candidate output hash mismatch")
        expected_id = _candidate_id(
            role=self.role,
            dispatch_id=self.dispatch_id,
            output_payload_sha256=self.output_payload_sha256,
        )
        if self.candidate_id != expected_id:
            raise ContestResearchObjectiveStageError("research candidate id mismatch")
        return self


class ContestResearchObjectiveReview(StrictFrozenModel):
    """The independently authored selection/synthesis retained for plan authoring."""

    dispatch_id: StableId
    temporary_agent_id: StableId
    result_hash: Sha256
    output_payload: dict[str, JsonValue] = Field(min_length=1)
    output_payload_sha256: Sha256
    selected_candidate_numbers: tuple[int, ...]
    selected_candidate_ids: tuple[StableId, ...]
    reference_indices: tuple[int, ...]
    archive_hash: Sha256
    authorship_receipt_hash: Sha256
    runtime_identity_removed: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_output_hash(self) -> ContestResearchObjectiveReview:
        if self.output_payload_sha256 != canonical_sha256(self.output_payload):
            raise ContestResearchObjectiveStageError("research review output hash mismatch")
        return self


class ContestResearchObjectiveStageArtifact(StrictFrozenModel):
    """Stable hand-off from brainstorming and independent review to plan authoring."""

    schema_version: Literal["contest-research-objective-stage-v1"] = (
        "contest-research-objective-stage-v1"
    )
    mode: ContestResearchObjectiveMode
    seed_text: str = Field(min_length=1)
    seed_sha256: Sha256
    seed_ref: TemporaryAgentInputRef
    literature_catalog: tuple[ContestRetrievedLiteratureEntry, ...]
    selected_skill_refs: tuple[TemporaryAgentSkillRef, ...]
    brainstorm_controller_binding_hash: Sha256
    review_controller_binding_hash: Sha256
    brainstorm_batch: TemporaryQwenBatchArtifact
    review_attempt_controllers: tuple[StageControllerBinding, ...] = Field(
        min_length=1,
        max_length=2,
    )
    review_attempt_batches: tuple[TemporaryQwenBatchArtifact, ...] = Field(
        min_length=1,
        max_length=2,
    )
    review_batch: TemporaryQwenBatchArtifact
    review_model_call_count: int = Field(ge=1, le=2)
    model_call_count: int = Field(ge=4, le=5)
    candidates: tuple[ContestResearchObjectiveCandidate, ...]
    rejected_candidate_dispatch_ids: tuple[StableId, ...]
    review: ContestResearchObjectiveReview
    status: Literal["complete", "degraded"]
    artifact_relative_path: str = Field(min_length=1)
    all_runtime_identities_removed: Literal[True] = True
    outputs_and_receipts_retained: Literal[True] = True
    content_is_scientific_evidence: Literal[False] = False
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestResearchObjectiveStageArtifact:
        if self.seed_sha256 != canonical_sha256({"seed_text": self.seed_text}):
            raise ContestResearchObjectiveStageError("research objective seed hash mismatch")
        if self.mode == "specified_direction" and not self.literature_catalog:
            raise ContestResearchObjectiveStageError(
                "specified direction requires a real retrieved literature catalog"
            )
        if self.brainstorm_controller_binding_hash == self.review_controller_binding_hash:
            raise ContestResearchObjectiveStageError(
                "brainstorm and review must use independently issued capabilities"
            )
        if (
            self.brainstorm_batch.controller_binding_hash != self.brainstorm_controller_binding_hash
            or self.review_batch.controller_binding_hash != self.review_controller_binding_hash
        ):
            raise ContestResearchObjectiveStageError("objective stage controller binding mismatch")
        if self.brainstorm_batch.dispatched_count != len(_ROLE_SPECS):
            raise ContestResearchObjectiveStageError("brainstorm dispatch count mismatch")
        if self.review_batch.dispatched_count != 1 or self.review_batch.succeeded_count != 1:
            raise ContestResearchObjectiveStageError("independent reviewer did not succeed")
        if self.review_attempt_batches[-1].artifact_hash != self.review_batch.artifact_hash:
            raise ContestResearchObjectiveStageError("final review batch is not the last attempt")
        if len(self.review_attempt_controllers) != len(self.review_attempt_batches):
            raise ContestResearchObjectiveStageError("review controller/attempt count mismatch")
        for controller, batch in zip(
            self.review_attempt_controllers,
            self.review_attempt_batches,
            strict=True,
        ):
            if controller.binding_hash != batch.controller_binding_hash:
                raise ContestResearchObjectiveStageError(
                    "review attempt batch belongs to another controller"
                )
        if self.review_model_call_count != len(self.review_attempt_batches):
            raise ContestResearchObjectiveStageError("review model-call count mismatch")
        if self.model_call_count != (
            self.brainstorm_batch.dispatched_count + self.review_model_call_count
        ):
            raise ContestResearchObjectiveStageError("objective-stage model-call count mismatch")
        for attempt_index, batch in enumerate(self.review_attempt_batches, start=1):
            if batch.dispatched_count != 1:
                raise ContestResearchObjectiveStageError("review attempt dispatch count mismatch")
            is_final = attempt_index == len(self.review_attempt_batches)
            if is_final != (batch.succeeded_count == 1 and batch.failed_count == 0):
                raise ContestResearchObjectiveStageError("review attempt outcome order mismatch")
        if len(self.review_attempt_batches) == 2:
            first, second = self.review_attempt_batches
            first_controller, second_controller = self.review_attempt_controllers
            if not _is_retryable_review_transport_failure(first):
                raise ContestResearchObjectiveStageError(
                    "review retry was not caused by an explicit transport failure"
                )
            if first.controller_binding_hash == second.controller_binding_hash:
                raise ContestResearchObjectiveStageError(
                    "review transport retry reused its controller capability"
                )
            if first.batch_id == second.batch_id:
                raise ContestResearchObjectiveStageError(
                    "review transport retry reused its batch id"
                )
            if (
                first_controller.lineage_id != second_controller.lineage_id
                or first_controller.stage != second_controller.stage
                or first_controller.controller_agent_id != second_controller.controller_agent_id
                or first_controller.stage_input_hash != second_controller.stage_input_hash
                or second_controller.stage_attempt != first_controller.stage_attempt + 1
            ):
                raise ContestResearchObjectiveStageError(
                    "review transport retry controller lineage or attempt is invalid"
                )
        expected_numbers = tuple(range(1, len(self.candidates) + 1))
        if tuple(item.candidate_number for item in self.candidates) != expected_numbers:
            raise ContestResearchObjectiveStageError("research candidate numbering mismatch")
        candidate_ids = {item.candidate_number: item.candidate_id for item in self.candidates}
        expected_selected_ids = tuple(
            candidate_ids[number] for number in self.review.selected_candidate_numbers
        )
        if self.review.selected_candidate_ids != expected_selected_ids:
            raise ContestResearchObjectiveStageError("review candidate projection mismatch")
        allowed_references = {item.catalog_index for item in self.literature_catalog}
        if any(
            index not in allowed_references
            for candidate in self.candidates
            for index in candidate.reference_indices
        ) or any(index not in allowed_references for index in self.review.reference_indices):
            raise ContestResearchObjectiveStageError(
                "objective stage contains an unknown reference"
            )
        if self.mode == "specified_direction" and not self.review.reference_indices:
            raise ContestResearchObjectiveStageError(
                "direction review did not use the retrieved literature catalog"
            )
        expected_status = (
            "complete"
            if self.brainstorm_batch.failed_count == 0 and not self.rejected_candidate_dispatch_ids
            else "degraded"
        )
        if self.status != expected_status:
            raise ContestResearchObjectiveStageError("objective stage status mismatch")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected_hash:
            raise ContestResearchObjectiveStageError("objective stage artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestResearchObjectiveStageArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)

    @property
    def candidate_count(self) -> int:
        """Number of accepted brainstorm candidates available to the reviewer."""

        return len(self.candidates)

    def plan_context_payload(self) -> dict[str, JsonValue]:
        """Return reviewed Chinese content without promoting it to experiment evidence."""

        review_payload = self.review.output_payload
        literature_by_index = {item.catalog_index: item for item in self.literature_catalog}
        return {
            "上下文类型": "研究目标形成阶段的独立评审结果",
            "输入模式": "指定科学问题" if self.mode == "specified_question" else "指定研究方向",
            "原始输入": self.seed_text,
            "运行状态": self.status,
            "评审模型调用次数": self.review_model_call_count,
            "最终研究目标": review_payload["research_objective_cn"],
            "核心假设": review_payload.get("main_hypothesis_cn", ""),
            "可证伪条件": review_payload.get("falsification_cn", ""),
            "独立评审意见": review_payload["review_cn"],
            "入选候选编号": list(self.review.selected_candidate_numbers),
            "入选候选ID": list(self.review.selected_candidate_ids),
            "候选构思": [
                {
                    "候选编号": candidate.candidate_number,
                    "候选ID": candidate.candidate_id,
                    "探索角色": candidate.role,
                    "内容": candidate.output_payload,
                    "真实文献目录编号": list(candidate.reference_indices),
                }
                for candidate in self.candidates
            ],
            "采用的真实文献": [
                {
                    "目录编号": index,
                    "题名": literature_by_index[index].title,
                    "来源链接": literature_by_index[index].source_url,
                    "检索来源": literature_by_index[index].retrieved_from,
                    "检索时间": literature_by_index[index].retrieved_at,
                }
                for index in self.review.reference_indices
            ],
            "使用边界": (
                "以上内容由临时构思代理与独立评审代理形成，只是研究计划的候选科学判断；"
                "它不是已执行实验、观察结果或正式科学证据。文献只能来自所列真实检索目录。"
            ),
        }


def run_contest_research_objective_stage(
    *,
    mode: ContestResearchObjectiveMode,
    seed_text: str,
    requirements: str,
    seed_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    brainstorm_controller: StageControllerBinding,
    brainstorm_capability: StageDispatchCapability,
    review_controller: StageControllerBinding,
    review_capability: StageDispatchCapability,
    output_dir: Path | str,
    selected_skill_contexts: Sequence[TemporaryQwenSkillContext] = (),
    retrieved_literature_catalog: Sequence[Mapping[str, Any]] = (),
    brainstorm_completion: CompletionCallable = run_llm_json_completion,
    review_completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_tokens_per_brainstorm_agent: int = 3_000,
    max_tokens_for_review: int = 4_000,
    timeout_seconds: int = 300,
    thinking_budget: int = 4_000,
    temperature: float = 0.35,
    clock: datetime | None = None,
) -> ContestResearchObjectiveStageArtifact:
    """Run parallel brainstorming followed by a separately authorized reviewer."""

    clean_seed = seed_text.strip()
    clean_requirements = requirements.strip()
    if not clean_seed or not clean_requirements:
        raise ValueError("research seed and requirements must be non-empty")
    if brainstorm_controller.binding_hash == review_controller.binding_hash:
        raise ContestResearchObjectiveStageError(
            "brainstorm and review require independently issued stage capabilities"
        )
    if brainstorm_controller.max_parallel_agents < len(_ROLE_SPECS):
        raise ContestResearchObjectiveStageError(
            "brainstorm controller lacks enough parallel temporary-agent slots"
        )
    brainstorm_capability.require_valid(brainstorm_controller)
    review_capability.require_valid(review_controller)
    literature_catalog = _normalize_literature_catalog(retrieved_literature_catalog)
    if mode == "specified_direction" and not literature_catalog:
        raise ContestResearchObjectiveStageError(
            "specified direction requires caller-provided real retrieved literature"
        )
    skills = tuple(selected_skill_contexts)
    brainstorm_tasks = _build_brainstorm_tasks(
        mode=mode,
        seed_text=clean_seed,
        requirements=clean_requirements,
        seed_ref=seed_ref,
        parent_task_id=parent_task_id,
        selected_skill_contexts=skills,
        literature_catalog=literature_catalog,
        max_tokens=max_tokens_per_brainstorm_agent,
        timeout_seconds=timeout_seconds,
    )
    input_digest = _task_digest(brainstorm_tasks)
    try:
        brainstorm_batch = run_temporary_qwen_content_batch(
            batch_id=f"research-objective-brainstorm-{input_digest[:20]}",
            controller=brainstorm_controller,
            capability=brainstorm_capability,
            tasks=brainstorm_tasks,
            output_dir=output_dir,
            completion=brainstorm_completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=len(_ROLE_SPECS),
            thinking_budget=thinking_budget,
            temperature=temperature,
            clock=clock,
        )
    except TemporaryQwenBatchError as exc:
        brainstorm_batch = exc.artifact
    if brainstorm_capability.active:
        raise ContestResearchObjectiveStageError("brainstorm capability was not finalized")

    role_by_dispatch = {
        task.dispatch_id: role
        for task, (role, _) in zip(brainstorm_tasks, _ROLE_SPECS, strict=True)
    }
    candidates: list[ContestResearchObjectiveCandidate] = []
    rejected_dispatch_ids: list[str] = []
    for output in brainstorm_batch.stable_outputs:
        if not _optional_chinese_fields_valid(
            output.output_payload,
            fields=("hypothesis_cn", "research_objective_cn", "falsification_cn"),
        ):
            rejected_dispatch_ids.append(output.dispatch_id)
            continue
        try:
            references = _validated_indices(
                output.output_payload.get("reference_indices", []),
                upper_bound=len(literature_catalog),
                label="brainstorm literature reference",
            )
        except ContestResearchObjectiveStageError:
            rejected_dispatch_ids.append(output.dispatch_id)
            continue
        role = role_by_dispatch[output.dispatch_id]
        candidates.append(
            ContestResearchObjectiveCandidate(
                candidate_number=len(candidates) + 1,
                candidate_id=_candidate_id(
                    role=role,
                    dispatch_id=output.dispatch_id,
                    output_payload_sha256=output.output_payload_sha256,
                ),
                role=role,
                dispatch_id=output.dispatch_id,
                output_payload=output.output_payload,
                output_payload_sha256=output.output_payload_sha256,
                reference_indices=references,
            )
        )

    review_attempt_batches: list[TemporaryQwenBatchArtifact] = []
    review_attempt_controllers = [review_controller]
    active_review_controller = review_controller
    active_review_capability = review_capability
    review_batch: TemporaryQwenBatchArtifact | None = None
    for review_attempt in (1, 2):
        review_task = _build_review_task(
            mode=mode,
            seed_text=clean_seed,
            requirements=clean_requirements,
            seed_ref=seed_ref,
            parent_task_id=parent_task_id,
            selected_skill_contexts=skills,
            literature_catalog=literature_catalog,
            candidates=tuple(candidates),
            brainstorm_batch=brainstorm_batch,
            max_tokens=max_tokens_for_review,
            timeout_seconds=timeout_seconds,
            attempt_number=review_attempt,
        )
        try:
            attempt_batch = run_temporary_qwen_content_batch(
                batch_id=(
                    f"research-objective-review-{input_digest[:16]}-attempt-{review_attempt}"
                ),
                controller=active_review_controller,
                capability=active_review_capability,
                tasks=(review_task,),
                output_dir=output_dir,
                completion=review_completion,
                config_path=config_path,
                env_path=env_path,
                max_workers=1,
                thinking_budget=thinking_budget,
                temperature=min(temperature, 0.25),
                clock=clock,
            )
        except TemporaryQwenBatchError as exc:
            attempt_batch = exc.artifact
            review_attempt_batches.append(attempt_batch)
            if active_review_capability.active:
                raise ContestResearchObjectiveStageError(
                    "failed review attempt capability was not finalized",
                    review_attempt_batches=tuple(review_attempt_batches),
                ) from exc
            retryable_transport = _is_retryable_review_transport_failure(attempt_batch)
            if review_attempt == 1 and retryable_transport:
                active_review_controller, active_review_capability = issue_stage_controller(
                    lineage_id=review_controller.lineage_id,
                    stage=review_controller.stage,
                    stage_attempt=review_controller.stage_attempt + 1,
                    controller_agent_id=review_controller.controller_agent_id,
                    stage_input_hash=review_controller.stage_input_hash,
                    max_parallel_agents=review_controller.max_parallel_agents,
                    claimed_at=clock,
                )
                review_attempt_controllers.append(active_review_controller)
                continue
            message = (
                "independent research-objective reviewer failed after one transport retry"
                if review_attempt == 2 and retryable_transport
                else "independent research-objective reviewer failed without a retryable transport error"
            )
            raise ContestResearchObjectiveStageError(
                message,
                review_attempt_batches=tuple(review_attempt_batches),
            ) from exc
        review_attempt_batches.append(attempt_batch)
        review_batch = attempt_batch
        break
    if review_batch is None:  # pragma: no cover - failed attempts raise above
        raise ContestResearchObjectiveStageError(
            "independent research-objective reviewer did not produce a batch",
            review_attempt_batches=tuple(review_attempt_batches),
        )
    if active_review_capability.active:
        raise ContestResearchObjectiveStageError("review capability was not finalized")
    review = _build_review(
        review_batch=review_batch,
        candidates=tuple(candidates),
        literature_catalog=literature_catalog,
        mode=mode,
    )

    output_root = Path(output_dir).resolve()
    artifact_relative_path = (
        PurePosixPath("temporary-agents", "research-objective-stage")
        / f"{canonical_sha256({'brainstorm': brainstorm_batch.artifact_hash, 'review_attempts': [item.artifact_hash for item in review_attempt_batches]})[:24]}.json"
    ).as_posix()
    artifact = ContestResearchObjectiveStageArtifact.create(
        schema_version="contest-research-objective-stage-v1",
        mode=mode,
        seed_text=clean_seed,
        seed_sha256=canonical_sha256({"seed_text": clean_seed}),
        seed_ref=seed_ref,
        literature_catalog=literature_catalog,
        selected_skill_refs=tuple(item.skill_ref for item in skills),
        brainstorm_controller_binding_hash=brainstorm_controller.binding_hash,
        review_controller_binding_hash=active_review_controller.binding_hash,
        brainstorm_batch=brainstorm_batch,
        review_attempt_controllers=tuple(review_attempt_controllers),
        review_attempt_batches=tuple(review_attempt_batches),
        review_batch=review_batch,
        review_model_call_count=len(review_attempt_batches),
        model_call_count=brainstorm_batch.dispatched_count + len(review_attempt_batches),
        candidates=tuple(candidates),
        rejected_candidate_dispatch_ids=tuple(rejected_dispatch_ids),
        review=review,
        status=(
            "complete"
            if brainstorm_batch.failed_count == 0 and not rejected_dispatch_ids
            else "degraded"
        ),
        artifact_relative_path=artifact_relative_path,
    )
    write_json_model(_resolve_inside(output_root, artifact_relative_path), artifact)
    return artifact


def _build_brainstorm_tasks(
    *,
    mode: ContestResearchObjectiveMode,
    seed_text: str,
    requirements: str,
    seed_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    selected_skill_contexts: tuple[TemporaryQwenSkillContext, ...],
    literature_catalog: tuple[ContestRetrievedLiteratureEntry, ...],
    max_tokens: int,
    timeout_seconds: int,
) -> tuple[TemporaryQwenContentTask, ...]:
    seed_hash = canonical_sha256(
        {
            "mode": mode,
            "seed_text": seed_text,
            "requirements": requirements,
            "seed_ref": seed_ref.model_dump(mode="json"),
            "literature_hashes": [item.source_payload_sha256 for item in literature_catalog],
            "skill_hashes": [item.skill_ref.content_sha256 for item in selected_skill_contexts],
        }
    )
    tasks: list[TemporaryQwenContentTask] = []
    for ordinal, (_role, instruction) in enumerate(_ROLE_SPECS, start=1):
        tasks.append(
            TemporaryQwenContentTask(
                dispatch_id=f"objective-brainstorm-{seed_hash[:16]}-{ordinal}",
                temporary_agent_id=f"temporary-objective-{seed_hash[:16]}-{ordinal}",
                parent_task_id=parent_task_id,
                task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
                task_instruction=instruction,
                input_refs=(seed_ref,),
                input_payload=_seed_input_payload(
                    mode=mode,
                    seed_text=seed_text,
                    requirements=requirements,
                    literature_catalog=literature_catalog,
                ),
                expected_output_schema=_brainstorm_schema(len(literature_catalog)),
                chinese_output_fields=("memo_cn",),
                skill_contexts=selected_skill_contexts,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                max_attempts=1,
            )
        )
    return tuple(tasks)


def _build_review_task(
    *,
    mode: ContestResearchObjectiveMode,
    seed_text: str,
    requirements: str,
    seed_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    selected_skill_contexts: tuple[TemporaryQwenSkillContext, ...],
    literature_catalog: tuple[ContestRetrievedLiteratureEntry, ...],
    candidates: tuple[ContestResearchObjectiveCandidate, ...],
    brainstorm_batch: TemporaryQwenBatchArtifact,
    max_tokens: int,
    timeout_seconds: int,
    attempt_number: int,
) -> TemporaryQwenContentTask:
    digest = canonical_sha256(
        {
            "mode": mode,
            "seed_text": seed_text,
            "candidate_hashes": [item.output_payload_sha256 for item in candidates],
            "brainstorm_batch_hash": brainstorm_batch.artifact_hash,
            "attempt_number": attempt_number,
        }
    )
    brainstorm_ref = TemporaryAgentInputRef(
        artifact_id=brainstorm_batch.batch_id,
        source_ref=brainstorm_batch.output_relative_path,
        sha256=brainstorm_batch.artifact_hash,
    )
    input_payload = _seed_input_payload(
        mode=mode,
        seed_text=seed_text,
        requirements=requirements,
        literature_catalog=literature_catalog,
    )
    input_payload["待评审候选"] = [
        {
            "候选编号": item.candidate_number,
            "探索角色": item.role,
            "候选内容": item.output_payload,
            "引用的真实文献目录编号": list(item.reference_indices),
        }
        for item in candidates
    ]
    input_payload["候选缺失时的处理"] = (
        "若候选因临时失败而为空，可直接依据原始输入与真实目录形成保守的研究目标，"
        "但必须在评审意见中如实说明，不能假装已经筛选了候选。"
    )
    return TemporaryQwenContentTask(
        dispatch_id=f"objective-review-{digest[:20]}-attempt-{attempt_number}",
        temporary_agent_id=(f"temporary-objective-review-{digest[:20]}-attempt-{attempt_number}"),
        parent_task_id=parent_task_id,
        task_kind=TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
        task_instruction=(
            "你是与头脑风暴角色分离的独立评审者。比较候选的可证伪性、证据边界、"
            "可执行性与潜在创新价值，选择一个或综合少数候选，形成明确的中文研究目标。"
            "不要打分、不要为了覆盖而选择；若更好的目标需要改写候选，可以改写并解释。"
            "不得新增目录外文献，不得把预期结果写成已观察结果。"
        ),
        input_refs=(seed_ref, brainstorm_ref),
        input_payload=input_payload,
        expected_output_schema=_review_schema(
            candidate_count=len(candidates),
            literature_count=len(literature_catalog),
        ),
        chinese_output_fields=("research_objective_cn", "review_cn"),
        skill_contexts=selected_skill_contexts,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_attempts=1,
    )


def _build_review(
    *,
    review_batch: TemporaryQwenBatchArtifact,
    candidates: tuple[ContestResearchObjectiveCandidate, ...],
    literature_catalog: tuple[ContestRetrievedLiteratureEntry, ...],
    mode: ContestResearchObjectiveMode,
) -> ContestResearchObjectiveReview:
    if len(review_batch.stable_outputs) != 1 or len(review_batch.task_records) != 1:
        raise ContestResearchObjectiveStageError("independent review output is missing")
    output = review_batch.stable_outputs[0]
    record = review_batch.task_records[0]
    if not _optional_chinese_fields_valid(
        output.output_payload,
        fields=("main_hypothesis_cn", "falsification_cn"),
    ):
        raise ContestResearchObjectiveStageError(
            "optional reviewer scientific content must be Chinese"
        )
    selected_numbers = _validated_indices(
        output.output_payload.get("selected_candidate_numbers", []),
        upper_bound=len(candidates),
        label="review candidate",
    )
    reference_indices = _validated_indices(
        output.output_payload.get("reference_indices", []),
        upper_bound=len(literature_catalog),
        label="review literature reference",
    )
    if mode == "specified_direction" and not reference_indices:
        raise ContestResearchObjectiveStageError(
            "direction reviewer must cite at least one retrieved catalog entry"
        )
    if record.result_hash is None or record.authorship_receipt_hash is None:
        raise ContestResearchObjectiveStageError("review result or receipt was not retained")
    candidate_ids = {item.candidate_number: item.candidate_id for item in candidates}
    return ContestResearchObjectiveReview(
        dispatch_id=record.dispatch_id,
        temporary_agent_id=record.temporary_agent_id,
        result_hash=record.result_hash,
        output_payload=output.output_payload,
        output_payload_sha256=output.output_payload_sha256,
        selected_candidate_numbers=selected_numbers,
        selected_candidate_ids=tuple(candidate_ids[number] for number in selected_numbers),
        reference_indices=reference_indices,
        archive_hash=record.archive_hash,
        authorship_receipt_hash=record.authorship_receipt_hash,
    )


def _normalize_literature_catalog(
    records: Sequence[Mapping[str, Any]],
) -> tuple[ContestRetrievedLiteratureEntry, ...]:
    catalog: list[ContestRetrievedLiteratureEntry] = []
    seen_hashes: set[str] = set()
    for record in records:
        title = str(record.get("title") or "").strip()
        source_url = str(record.get("source_url") or record.get("url") or "").strip()
        retrieved_from = str(record.get("retrieved_from") or "").strip()
        raw_retrieved_at = record.get("retrieved_at")
        retrieved_at = (
            raw_retrieved_at.isoformat()
            if isinstance(raw_retrieved_at, datetime)
            else str(raw_retrieved_at or "").strip()
        )
        if not title or not source_url or not retrieved_from or not retrieved_at:
            raise ContestResearchObjectiveStageError(
                "retrieved literature requires title, url, retrieved_from, and retrieved_at"
            )
        if not source_url.lower().startswith(("https://", "http://")):
            raise ContestResearchObjectiveStageError(
                "retrieved literature source url must be http(s)"
            )
        abstract_or_excerpt = str(
            record.get("abstract") or record.get("excerpt") or record.get("relevance_to_plan") or ""
        ).strip()
        raw_authors = record.get("authors") or ()
        authors = (
            tuple(str(item).strip() for item in raw_authors if str(item).strip())
            if isinstance(raw_authors, list | tuple)
            else (str(raw_authors).strip(),)
        )
        doi_text = str(record.get("doi") or "").strip() or None
        payload = {
            "title": title,
            "source_url": source_url,
            "retrieved_from": retrieved_from,
            "retrieved_at": retrieved_at,
            "abstract_or_excerpt": abstract_or_excerpt or None,
            "authors": list(authors),
            "doi": doi_text,
        }
        payload_hash = canonical_sha256(payload)
        if payload_hash in seen_hashes:
            continue
        seen_hashes.add(payload_hash)
        catalog.append(
            ContestRetrievedLiteratureEntry(
                catalog_index=len(catalog) + 1,
                record_id=f"retrieved-literature-{payload_hash[:24]}",
                title=title,
                source_url=source_url,
                retrieved_from=retrieved_from,
                retrieved_at=retrieved_at,
                abstract_or_excerpt=abstract_or_excerpt or None,
                authors=authors,
                doi=doi_text,
                source_payload_sha256=payload_hash,
            )
        )
    return tuple(catalog)


def _seed_input_payload(
    *,
    mode: ContestResearchObjectiveMode,
    seed_text: str,
    requirements: str,
    literature_catalog: tuple[ContestRetrievedLiteratureEntry, ...],
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "输入模式": "指定科学问题" if mode == "specified_question" else "指定研究方向",
        "指定问题" if mode == "specified_question" else "指定方向": seed_text,
        "交付要求": requirements,
        "真实检索文献目录": [
            {
                "目录编号": item.catalog_index,
                "题名": item.title,
                "作者": list(item.authors),
                "来源链接": item.source_url,
                "DOI": item.doi,
                "检索来源": item.retrieved_from,
                "检索时间": item.retrieved_at,
                "摘要或检索摘录": item.abstract_or_excerpt,
            }
            for item in literature_catalog
        ],
        "文献边界": "如需引用文献，只能返回目录编号；不得自行补写或猜测目录外文献。",
        "阶段边界": "当前只形成候选假设与研究目标，不执行实验，也不声称存在实验结果。",
    }
    return payload


def _brainstorm_schema(literature_count: int) -> dict[str, JsonValue]:
    reference_items: dict[str, JsonValue] = {"type": "integer", "minimum": 1}
    if literature_count:
        reference_items["maximum"] = literature_count
    return {
        "type": "object",
        "required": ["memo_cn"],
        "properties": {
            "memo_cn": {"type": "string"},
            "hypothesis_cn": {"type": "string"},
            "research_objective_cn": {"type": "string"},
            "falsification_cn": {"type": "string"},
            "reference_indices": {
                "type": "array",
                "items": reference_items,
                "maxItems": literature_count,
            },
        },
        "additionalProperties": False,
    }


def _review_schema(*, candidate_count: int, literature_count: int) -> dict[str, JsonValue]:
    candidate_items: dict[str, JsonValue] = {"type": "integer", "minimum": 1}
    if candidate_count:
        candidate_items["maximum"] = candidate_count
    reference_items: dict[str, JsonValue] = {"type": "integer", "minimum": 1}
    if literature_count:
        reference_items["maximum"] = literature_count
    return {
        "type": "object",
        "required": [
            "research_objective_cn",
            "review_cn",
            "selected_candidate_numbers",
            "reference_indices",
        ],
        "properties": {
            "research_objective_cn": {"type": "string"},
            "main_hypothesis_cn": {"type": "string"},
            "falsification_cn": {"type": "string"},
            "review_cn": {"type": "string"},
            "selected_candidate_numbers": {
                "type": "array",
                "items": candidate_items,
                "maxItems": candidate_count,
            },
            "reference_indices": {
                "type": "array",
                "items": reference_items,
                "maxItems": literature_count,
            },
        },
        "additionalProperties": False,
    }


def _validated_indices(
    value: JsonValue,
    *,
    upper_bound: int,
    label: str,
) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ContestResearchObjectiveStageError(f"{label} indices must be a list")
    indices: list[int] = []
    for item in value:
        if (
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 1
            or item > upper_bound
            or item in indices
        ):
            raise ContestResearchObjectiveStageError(f"{label} contains an unknown index")
        indices.append(item)
    return tuple(indices)


def _is_retryable_review_transport_failure(batch: TemporaryQwenBatchArtifact) -> bool:
    """Recognize one archived LLM transport failure without retrying content defects."""

    if batch.dispatched_count != 1 or batch.failed_count != 1 or batch.succeeded_count != 0:
        return False
    record = batch.task_records[0]
    if record.failure_type != "LLMClientError" or not record.failure_message:
        return False
    message = record.failure_message.casefold()
    content_failure_markers = (
        "not valid json",
        "top-level value is not an object",
        "response was not json",
        "schema",
        "reasoning_content",
    )
    if any(marker in message for marker in content_failure_markers):
        return False
    transport_failure_markers = (
        "winerror 10060",
        "timed out",
        "timeout",
        "transport",
        "network",
        "connection",
        "request failed:",
        "temporarily unavailable",
        "remote end closed",
        "getaddrinfo",
        "name or service not known",
    )
    return any(marker in message for marker in transport_failure_markers)


def _optional_chinese_fields_valid(
    payload: Mapping[str, JsonValue],
    *,
    fields: tuple[str, ...],
) -> bool:
    for field in fields:
        value = payload.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str) or not any("\u4e00" <= char <= "\u9fff" for char in value):
            return False
    return True


def _candidate_id(
    *,
    role: ContestResearchObjectiveRole,
    dispatch_id: str,
    output_payload_sha256: str,
) -> str:
    digest = canonical_sha256(
        {
            "role": role,
            "dispatch_id": dispatch_id,
            "output_payload_sha256": output_payload_sha256,
        }
    )
    return f"research-candidate-{digest[:24]}"


def _task_digest(tasks: tuple[TemporaryQwenContentTask, ...]) -> str:
    return canonical_sha256(
        [
            {
                "dispatch_id": item.dispatch_id,
                "input_payload": item.input_payload,
                "skill_hashes": [skill.skill_ref.content_sha256 for skill in item.skill_contexts],
            }
            for item in tasks
        ]
    )


def _resolve_inside(output_root: Path, relative_path: str) -> Path:
    candidate = (output_root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError as exc:
        raise TemporaryQwenPoolError("objective-stage artifact escapes output directory") from exc
    return candidate


__all__ = [
    "ContestResearchObjectiveCandidate",
    "ContestResearchObjectiveMode",
    "ContestResearchObjectiveReview",
    "ContestResearchObjectiveStageArtifact",
    "ContestResearchObjectiveStageError",
    "ContestRetrievedLiteratureEntry",
    "run_contest_research_objective_stage",
]
