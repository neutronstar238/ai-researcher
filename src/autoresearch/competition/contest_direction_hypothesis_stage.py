"""Evidence-first hypothesis brainstorming and post-pilot objective review.

The two public stages deliberately do not form one hidden review loop:

* brainstorming runs before an experiment and has no reviewer;
* post-pilot review requires a hash-verified real prime preexperiment and runs
  exactly one independent temporary reviewer.

Scientific decisions remain model-authored.  This module computes identifiers,
checks file integrity, and enforces lifecycle/order boundaries; it never turns a
p-value or an effect-size threshold into a scientific verdict.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveRecord,
    TemporaryAgentAssignment,
    TemporaryAgentBatchManifest,
    TemporaryAgentInputRef,
    TemporaryAgentResultArtifact,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
)
from autoresearch.competition.contest_adapter_semantics import (
    assess_adapter_semantic_compatibility,
)
from autoresearch.competition.contest_direction_memory import (
    normalize_optional_dreaming_context,
    optional_dreaming_context_hash,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    load_contest_prime_preexperiment,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.temporary_qwen_pool import (
    CompletionCallable,
    TemporaryQwenBatchArtifact,
    TemporaryQwenBatchError,
    TemporaryQwenContentTask,
    TemporaryQwenPoolError,
    TemporaryQwenSkillContext,
    TemporaryQwenTaskRecord,
    run_temporary_qwen_content_batch,
)
from autoresearch.kernel.contracts import Sha256, StableId, canonical_sha256
from autoresearch.llm.client import run_llm_json_completion

ContestHypothesisRole = Literal[
    "mechanism_explorer",
    "experiment_designer",
    "alternative_explanation_challenger",
]
PostpilotDecision = Literal["retain", "narrow_once", "terminate"]

_ROLE_SPECS: tuple[tuple[ContestHypothesisRole, str], ...] = (
    (
        "mechanism_explorer",
        "依据指定方向、真实检索文献和已选方法技能提出一个可证伪机制假设。"
        "必须明确研究目标、反驳条件、观测量、主要指标、零模型和可执行适配器；"
        "必须具体说明相对最近工作的差异、迁移或改造的方法/基线，以及最强反证；"
        "当前只构思，不评审、不执行实验，也不得把预期写成结果。",
    ),
    (
        "experiment_designer",
        "从可执行预实验出发提出一个可证伪候选，明确科学对象、观测量、主要指标、"
        "必要零模型和失败判据。只能选择列出的适配器或no_adapter；"
        "必须引用真实目录并说明最近工作差异、可迁移方法/基线和最强反证；"
        "当前只构思，不评审、不执行实验，也不得虚构结果。",
    ),
    (
        "alternative_explanation_challenger",
        "寻找能区分默认解释与竞争解释的反直觉候选假设，并明确什么观察会否定它。"
        "候选必须映射到列出的观测量、指标、零模型和适配器，不能映射则写no_adapter；"
        "必须引用真实目录并对最近工作、方法迁移与反证边界作具体比较；"
        "当前只构思，不评审、不执行实验。",
    ),
)

_BRAINSTORM_ARTIFACT_NAME = "direction-hypothesis-brainstorm.json"
_POSTPILOT_ARTIFACT_NAME = "postpilot-objective-review.json"
_PILOT_BRIEF_CONTEXT_CHARACTERS = 2_500
_POSTPILOT_TASK_INPUT_UTF8_BUDGET = 28 * 1_024
_MAX_POSTPILOT_LITERATURE_RECORDS = 5


class ContestDirectionHypothesisStageError(RuntimeError):
    """Raised when a stage cannot produce a trusted artifact."""


class ContestExecutableAdapterDescriptor(StrictFrozenModel):
    """Caller-supplied metadata; it describes execution but does not execute."""

    adapter_id: StableId
    scientific_object: str = Field(min_length=1)
    observable: str = Field(min_length=1)
    supported_metrics: tuple[str, ...] = Field(min_length=1)
    supported_nulls: tuple[str, ...] = Field(min_length=1)
    description: str | None = None
    descriptor_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> ContestExecutableAdapterDescriptor:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"descriptor_hash"}))
        if self.descriptor_hash != expected:
            raise ContestDirectionHypothesisStageError("adapter descriptor hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestExecutableAdapterDescriptor:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, descriptor_hash="0" * 64)
        payload["descriptor_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"descriptor_hash"})
        )
        return cls.model_validate(payload)


class ContestHypothesisCandidate(StrictFrozenModel):
    """One model-authored candidate with a program-computed identity."""

    candidate_number: int = Field(ge=1)
    candidate_id: StableId
    role: ContestHypothesisRole
    dispatch_id: StableId
    hypothesis_cn: str = Field(min_length=1)
    research_objective_cn: str = Field(min_length=1)
    falsification_cn: str = Field(min_length=1)
    # Optional only for byte-compatible loading of pre-v2 live artifacts.  Every
    # newly authored candidate is built from a schema that requires all three.
    nearest_work_difference_cn: str | None = Field(default=None, min_length=1)
    transferred_method_baseline_cn: str | None = Field(default=None, min_length=1)
    strongest_counterevidence_cn: str | None = Field(default=None, min_length=1)
    adapter_id: str = Field(min_length=1)
    scientific_object: str = Field(min_length=1)
    observable: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    null_models: tuple[str, ...] = Field(min_length=1)
    reference_indices: tuple[int, ...] = ()
    output_payload_sha256: Sha256
    result_hash: Sha256
    authorship_receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_identity(self) -> ContestHypothesisCandidate:
        expected_id = _candidate_id(
            role=self.role,
            dispatch_id=self.dispatch_id,
            output_payload_sha256=self.output_payload_sha256,
        )
        if self.candidate_id != expected_id:
            raise ContestDirectionHypothesisStageError("candidate id mismatch")
        return self


class ContestDirectionHypothesisBrainstormArtifact(StrictFrozenModel):
    """Three pre-pilot suggestions, with no scientific review attached."""

    schema_version: Literal["contest-direction-hypothesis-brainstorm-v1"] = (
        "contest-direction-hypothesis-brainstorm-v1"
    )
    direction: str = Field(min_length=1)
    direction_sha256: Sha256
    requirements_sha256: Sha256
    direction_ref: TemporaryAgentInputRef
    selected_skill_refs: tuple[TemporaryAgentSkillRef, ...]
    literature_catalog: tuple[dict[str, JsonValue], ...]
    literature_catalog_sha256: Sha256
    executable_adapters: tuple[ContestExecutableAdapterDescriptor, ...]
    adapter_catalog_sha256: Sha256
    controller_binding_hash: Sha256
    batch: TemporaryQwenBatchArtifact
    candidates: tuple[ContestHypothesisCandidate, ...]
    unavailable_roles: tuple[ContestHypothesisRole, ...]
    status: Literal["complete", "degraded"]
    model_call_count: Literal[3] = 3
    review_performed: Literal[False] = False
    artifact_relative_path: Literal["direction-hypothesis-brainstorm.json"] = (
        "direction-hypothesis-brainstorm.json"
    )
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestDirectionHypothesisBrainstormArtifact:
        if self.direction_sha256 != canonical_sha256({"direction": self.direction}):
            raise ContestDirectionHypothesisStageError("direction hash mismatch")
        if self.literature_catalog_sha256 != canonical_sha256(
            {"catalog": list(self.literature_catalog)}
        ):
            raise ContestDirectionHypothesisStageError("literature catalog hash mismatch")
        if self.adapter_catalog_sha256 != canonical_sha256(
            [item.model_dump(mode="json") for item in self.executable_adapters]
        ):
            raise ContestDirectionHypothesisStageError("adapter catalog hash mismatch")
        if self.batch.controller_binding_hash != self.controller_binding_hash:
            raise ContestDirectionHypothesisStageError("brainstorm controller mismatch")
        if self.batch.dispatched_count != 3:
            raise ContestDirectionHypothesisStageError("brainstorm must dispatch three agents")
        if len(self.candidates) != self.batch.succeeded_count:
            raise ContestDirectionHypothesisStageError("candidate count mismatch")
        if not self.candidates:
            raise ContestDirectionHypothesisStageError("all brainstorm agents failed")
        expected_numbers = tuple(range(1, len(self.candidates) + 1))
        if tuple(item.candidate_number for item in self.candidates) != expected_numbers:
            raise ContestDirectionHypothesisStageError("candidate numbering mismatch")
        expected_status = "complete" if self.batch.failed_count == 0 else "degraded"
        if self.status != expected_status:
            raise ContestDirectionHypothesisStageError("brainstorm status mismatch")
        allowed_adapters = {item.adapter_id for item in self.executable_adapters} | {"no_adapter"}
        adapters = {item.adapter_id: item for item in self.executable_adapters}
        allowed_references = set(range(1, len(self.literature_catalog) + 1))
        for candidate in self.candidates:
            if candidate.adapter_id not in allowed_adapters:
                raise ContestDirectionHypothesisStageError("candidate uses unknown adapter")
            if candidate.adapter_id != "no_adapter":
                compatibility = assess_adapter_semantic_compatibility(
                    adapters[candidate.adapter_id],
                    scope_texts=(self.direction,),
                    candidate=candidate.model_dump(mode="json"),
                )
                if not compatibility.compatible:
                    raise ContestDirectionHypothesisStageError(
                        "candidate adapter binding violates runner semantics"
                    )
            if any(index not in allowed_references for index in candidate.reference_indices):
                raise ContestDirectionHypothesisStageError(
                    "candidate uses unknown literature reference"
                )
        expected_payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        expected_hash = canonical_sha256(expected_payload)
        legacy_payload = json.loads(json.dumps(expected_payload))
        for candidate in legacy_payload["candidates"]:
            candidate.pop("nearest_work_difference_cn", None)
            candidate.pop("transferred_method_baseline_cn", None)
            candidate.pop("strongest_counterevidence_cn", None)
        legacy_hash = canonical_sha256(legacy_payload)
        if self.artifact_hash not in {expected_hash, legacy_hash}:
            raise ContestDirectionHypothesisStageError("brainstorm artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionHypothesisBrainstormArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)

    def plan_context_payload(self) -> dict[str, JsonValue]:
        """Project candidates without presenting them as reviewed or observed."""

        return {
            "上下文类型": "真实检索与方法技能之后、预实验之前的未评审候选",
            "方向": self.direction,
            "状态": self.status,
            "已执行科学评审": False,
            "模型调用次数": self.model_call_count,
            "候选": [
                {
                    "candidate_id": item.candidate_id,
                    "hypothesis_cn": item.hypothesis_cn,
                    "research_objective_cn": item.research_objective_cn,
                    "falsification_cn": item.falsification_cn,
                    "nearest_work_difference_cn": item.nearest_work_difference_cn,
                    "transferred_method_baseline_cn": item.transferred_method_baseline_cn,
                    "strongest_counterevidence_cn": item.strongest_counterevidence_cn,
                    "adapter_id": item.adapter_id,
                    "scientific_object": item.scientific_object,
                    "observable": item.observable,
                    "metric": item.metric,
                    "null_models": list(item.null_models),
                    "reference_indices": list(item.reference_indices),
                }
                for item in self.candidates
            ],
            "使用边界": "这些是预实验前候选，不是证据、评审结论或已验证假设。",
        }


class ContestVerifiedStageInput(StrictFrozenModel):
    """A byte-level input binding retained by the post-pilot review."""

    kind: str = Field(min_length=1)
    absolute_path: str = Field(min_length=1)
    bytes: int = Field(ge=0)
    sha256: Sha256


class ContestPostpilotObjectiveReviewArtifact(StrictFrozenModel):
    """One independent scientific decision made only after a verified pilot."""

    schema_version: Literal["contest-postpilot-objective-review-v1"] = (
        "contest-postpilot-objective-review-v1"
    )
    direction: str = Field(min_length=1)
    direction_sha256: Sha256
    requirements_sha256: Sha256
    direction_ref: TemporaryAgentInputRef
    brainstorm_artifact_hash: Sha256
    brainstorm_artifact_file_sha256: Sha256
    pilot_brief_sha256: Sha256
    preexperiment_artifact_hash: Sha256
    preexperiment_artifact_file_sha256: Sha256
    preexperiment_manifest_hash: Sha256
    preexperiment_manifest_sha256: Sha256
    preexperiment_metrics_sha256: Sha256
    verified_inputs: tuple[ContestVerifiedStageInput, ...] = Field(min_length=1)
    verified_inputs_bundle_sha256: Sha256
    controller_binding_hash: Sha256
    batch: TemporaryQwenBatchArtifact
    dispatch_id: StableId
    temporary_agent_id: StableId
    result_hash: Sha256
    authorship_receipt_hash: Sha256
    output_payload_sha256: Sha256
    decision: PostpilotDecision
    research_objective_cn: str = Field(min_length=1)
    main_hypothesis_cn: str = Field(min_length=1)
    falsification_cn: str = Field(min_length=1)
    pilot_interpretation_cn: str = Field(min_length=1)
    review_cn: str = Field(min_length=1)
    reference_indices: tuple[int, ...]
    evidence_pointers: tuple[str, ...] = Field(min_length=1)
    selected_skill_refs: tuple[TemporaryAgentSkillRef, ...]
    literature_catalog: tuple[dict[str, JsonValue], ...]
    model_call_count: Literal[1] = 1
    task_input_utf8_bytes: int = Field(ge=1, le=_POSTPILOT_TASK_INPUT_UTF8_BUDGET)
    scientific_rethink_count: Literal[1] = 1
    further_scientific_retry_allowed: Literal[False] = False
    raw_csv_read_by_model: Literal[False] = False
    artifact_relative_path: Literal["postpilot-objective-review.json"] = (
        "postpilot-objective-review.json"
    )
    artifact_hash: Sha256

    @model_validator(mode="before")
    @classmethod
    def _derive_legacy_verified_input_bundle(cls, values: Any) -> Mapping[str, Any] | Any:
        """Derive the sole post-v1 field from legacy artifacts' full bindings."""

        if not isinstance(values, Mapping) or "verified_inputs_bundle_sha256" in values:
            return values
        raw_inputs = values.get("verified_inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs:
            return values
        validated_inputs = tuple(
            ContestVerifiedStageInput.model_validate(item) for item in raw_inputs
        )
        payload = dict(values)
        payload["verified_inputs_bundle_sha256"] = canonical_sha256(
            [item.model_dump(mode="json") for item in validated_inputs]
        )
        return payload

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestPostpilotObjectiveReviewArtifact:
        if self.direction_sha256 != canonical_sha256({"direction": self.direction}):
            raise ContestDirectionHypothesisStageError("post-pilot direction hash mismatch")
        if self.batch.controller_binding_hash != self.controller_binding_hash:
            raise ContestDirectionHypothesisStageError("post-pilot controller mismatch")
        if self.batch.dispatched_count != 1 or self.batch.succeeded_count != 1:
            raise ContestDirectionHypothesisStageError("post-pilot review must succeed once")
        if len(self.batch.stable_outputs) != 1 or len(self.batch.task_records) != 1:
            raise ContestDirectionHypothesisStageError("post-pilot output is missing")
        output = self.batch.stable_outputs[0]
        record = self.batch.task_records[0]
        if (
            output.dispatch_id != self.dispatch_id
            or record.dispatch_id != self.dispatch_id
            or record.temporary_agent_id != self.temporary_agent_id
            or record.result_hash != self.result_hash
            or record.authorship_receipt_hash != self.authorship_receipt_hash
            or output.output_payload_sha256 != self.output_payload_sha256
        ):
            raise ContestDirectionHypothesisStageError("post-pilot receipt binding mismatch")
        paths = [item.absolute_path for item in self.verified_inputs]
        if len(paths) != len(set(paths)):
            raise ContestDirectionHypothesisStageError("verified input paths repeat")
        if self.verified_inputs_bundle_sha256 != canonical_sha256(
            [item.model_dump(mode="json") for item in self.verified_inputs]
        ):
            raise ContestDirectionHypothesisStageError("verified input bundle hash mismatch")
        allowed_references = set(range(1, len(self.literature_catalog) + 1))
        if any(index not in allowed_references for index in self.reference_indices):
            raise ContestDirectionHypothesisStageError("review uses unknown reference")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        legacy_hash = canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"artifact_hash", "verified_inputs_bundle_sha256"},
            )
        )
        if self.artifact_hash not in {expected_hash, legacy_hash}:
            raise ContestDirectionHypothesisStageError("post-pilot artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestPostpilotObjectiveReviewArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)

    def plan_context_payload(self) -> dict[str, JsonValue]:
        """Return the single post-pilot decision for final plan authoring."""

        return {
            "上下文类型": "真实预实验后的独立研究目标评审",
            "decision": self.decision,
            "research_objective_cn": self.research_objective_cn,
            "main_hypothesis_cn": self.main_hypothesis_cn,
            "falsification_cn": self.falsification_cn,
            "pilot_interpretation_cn": self.pilot_interpretation_cn,
            "review_cn": self.review_cn,
            "reference_indices": list(self.reference_indices),
            "evidence_pointers": list(self.evidence_pointers),
            "preexperiment_artifact_hash": self.preexperiment_artifact_hash,
            "preexperiment_manifest_hash": self.preexperiment_manifest_hash,
            "verified_inputs_bundle_sha256": self.verified_inputs_bundle_sha256,
            "model_call_count": self.model_call_count,
            "task_input_utf8_bytes": self.task_input_utf8_bytes,
            "scientific_rethink_count": self.scientific_rethink_count,
            "使用边界": (
                "retain或narrow_once只表示本次单次评审的选择；terminate表示当前目标停止。"
                "程序未依据p值替模型作结论，也不允许第二次科学重想。"
            ),
        }


def run_contest_direction_hypothesis_brainstorm(
    *,
    direction: str,
    requirements: str,
    direction_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    output_dir: Path | str,
    selected_skill_contexts: Sequence[TemporaryQwenSkillContext] = (),
    retrieved_literature_catalog: Sequence[Mapping[str, Any]] = (),
    executable_adapters: Sequence[Mapping[str, Any]] = (),
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_tokens_per_agent: int = 3_000,
    timeout_seconds: int = 300,
    thinking_budget: int = 4_000,
    temperature: float = 0.35,
    clock: datetime | None = None,
) -> ContestDirectionHypothesisBrainstormArtifact:
    """Run three parallel, unreviewed, pre-pilot hypothesis contributors."""

    clean_direction = direction.strip()
    clean_requirements = requirements.strip()
    if not clean_direction or not clean_requirements:
        raise ValueError("direction and requirements must be non-empty")
    if controller.max_parallel_agents < 3:
        raise ContestDirectionHypothesisStageError(
            "brainstorm controller must allow three parallel agents"
        )
    output_root = _prepare_empty_output_dir(output_dir)
    literature = _normalize_literature_catalog(retrieved_literature_catalog)
    adapters = _normalize_adapters(executable_adapters)
    skill_contexts = tuple(selected_skill_contexts)
    tasks = _build_brainstorm_tasks(
        direction=clean_direction,
        requirements=clean_requirements,
        direction_ref=direction_ref,
        parent_task_id=parent_task_id,
        selected_skill_contexts=skill_contexts,
        literature_catalog=literature,
        executable_adapters=adapters,
        max_tokens=max_tokens_per_agent,
        timeout_seconds=timeout_seconds,
    )
    try:
        batch = run_temporary_qwen_content_batch(
            batch_id=f"direction-hypothesis-{_tasks_hash(tasks)[:20]}",
            controller=controller,
            capability=capability,
            tasks=tasks,
            output_dir=output_root,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=3,
            thinking_budget=thinking_budget,
            temperature=temperature,
            clock=clock,
        )
    except TemporaryQwenBatchError as exc:
        batch = exc.artifact
    if batch.succeeded_count == 0:
        raise ContestDirectionHypothesisStageError(
            "all brainstorm agents failed after their records were archived"
        )
    candidates = _build_candidates(
        batch,
        tasks,
        literature_count=len(literature),
        direction=clean_direction,
        executable_adapters=adapters,
    )
    available_roles = {item.role for item in candidates}
    unavailable = tuple(role for role, _ in _ROLE_SPECS if role not in available_roles)
    artifact = ContestDirectionHypothesisBrainstormArtifact.create(
        schema_version="contest-direction-hypothesis-brainstorm-v1",
        direction=clean_direction,
        direction_sha256=canonical_sha256({"direction": clean_direction}),
        requirements_sha256=canonical_sha256({"requirements": clean_requirements}),
        direction_ref=direction_ref,
        selected_skill_refs=tuple(item.skill_ref for item in skill_contexts),
        literature_catalog=literature,
        literature_catalog_sha256=canonical_sha256({"catalog": list(literature)}),
        executable_adapters=adapters,
        adapter_catalog_sha256=canonical_sha256(
            [item.model_dump(mode="json") for item in adapters]
        ),
        controller_binding_hash=controller.binding_hash,
        batch=batch,
        candidates=candidates,
        unavailable_roles=unavailable,
        status="complete" if batch.failed_count == 0 else "degraded",
        model_call_count=3,
        review_performed=False,
        artifact_relative_path=_BRAINSTORM_ARTIFACT_NAME,
    )
    write_json_model(output_root / _BRAINSTORM_ARTIFACT_NAME, artifact)
    return artifact


def run_contest_postpilot_objective_review(
    *,
    direction: str,
    requirements: str,
    direction_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    output_dir: Path | str,
    brainstorm_artifact_path: Path | str,
    pilot_brief_path: Path | str,
    preexperiment_artifact_path: Path | str,
    selected_skill_contexts: Sequence[TemporaryQwenSkillContext] = (),
    retrieved_literature_catalog: Sequence[Mapping[str, Any]] = (),
    derived_memory_context: Mapping[str, Any] | None = None,
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_tokens: int = 4_000,
    timeout_seconds: int = 300,
    thinking_budget: int = 4_000,
    temperature: float = 0.2,
    clock: datetime | None = None,
) -> ContestPostpilotObjectiveReviewArtifact:
    """Run exactly one independent objective review after a real verified pilot."""

    clean_direction = direction.strip()
    clean_requirements = requirements.strip()
    if not clean_direction or not clean_requirements:
        raise ValueError("direction and requirements must be non-empty")
    output_root = _prepare_empty_output_dir(output_dir)
    brainstorm_path = Path(brainstorm_artifact_path).expanduser().resolve()
    brainstorm, brainstorm_inputs = _load_and_verify_brainstorm(brainstorm_path)
    if brainstorm.direction != clean_direction:
        raise ContestDirectionHypothesisStageError(
            "brainstorm direction differs from post-pilot direction"
        )
    brief_path = Path(pilot_brief_path).expanduser().resolve()
    if not brief_path.is_file():
        raise ContestDirectionHypothesisStageError("pilot brief does not exist")
    brief_binding = _verified_file("pilot_brief", brief_path)
    brief_text = brief_path.read_text(encoding="utf-8")
    pilot_path = Path(preexperiment_artifact_path).expanduser().resolve()
    pilot = load_contest_prime_preexperiment(pilot_path, verify_files=True)
    pilot_inputs = _verified_preexperiment_inputs(pilot_path, pilot)
    full_literature = (
        _normalize_literature_catalog(retrieved_literature_catalog)
        if retrieved_literature_catalog
        else brainstorm.literature_catalog
    )
    literature = _select_postpilot_literature(
        brainstorm=brainstorm,
        literature_catalog=full_literature,
        pilot_brief_text=brief_text,
    )
    verified_inputs = _deduplicate_verified_inputs(
        (*brainstorm_inputs, brief_binding, *pilot_inputs)
    )
    skill_contexts = tuple(selected_skill_contexts)
    memory_context = normalize_optional_dreaming_context(
        dict(derived_memory_context) if derived_memory_context is not None else None
    )
    memory_context = _project_postpilot_dreaming_context(memory_context)
    while True:
        try:
            task = _build_postpilot_task(
                direction=clean_direction,
                requirements=clean_requirements,
                direction_ref=direction_ref,
                parent_task_id=parent_task_id,
                brainstorm=brainstorm,
                brainstorm_path=brainstorm_path,
                pilot_brief_text=brief_text,
                pilot_brief_binding=brief_binding,
                pilot=pilot,
                pilot_path=pilot_path,
                verified_inputs=verified_inputs,
                selected_skill_contexts=skill_contexts,
                literature_catalog=literature,
                derived_memory_context=memory_context,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except TemporaryQwenPoolError as exc:
            if str(exc) != "temporary task payload is too large":
                raise ContestDirectionHypothesisStageError(
                    "post-pilot task failed validation before model dispatch"
                ) from exc
            if len(literature) <= 1:
                raise ContestDirectionHypothesisStageError(
                    "post-pilot task exceeds its context budget with one whole literature record"
                ) from exc
            literature = _drop_largest_serialized_literature_record(literature)
            continue
        if _task_input_utf8_bytes(task) <= _POSTPILOT_TASK_INPUT_UTF8_BUDGET:
            break
        if len(literature) <= 1:
            raise ContestDirectionHypothesisStageError(
                "post-pilot task exceeds 28 KiB with one whole literature record"
            )
        literature = _drop_largest_serialized_literature_record(literature)
    try:
        batch = run_temporary_qwen_content_batch(
            batch_id=f"postpilot-objective-{canonical_sha256(task.model_dump(mode='json'))[:20]}",
            controller=controller,
            capability=capability,
            tasks=(task,),
            output_dir=output_root,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=1,
            thinking_budget=thinking_budget,
            temperature=temperature,
            clock=clock,
        )
    except TemporaryQwenBatchError as exc:
        raise ContestDirectionHypothesisStageError(
            "post-pilot scientific review failed; a second scientific call is not allowed"
        ) from exc
    output = batch.stable_outputs[0]
    record = batch.task_records[0]
    if record.result_hash is None or record.authorship_receipt_hash is None:
        raise ContestDirectionHypothesisStageError("post-pilot review receipt is missing")
    payload = output.output_payload
    reference_indices = _validated_indices(
        payload.get("reference_indices"), upper_bound=len(literature)
    )
    evidence_pointers = tuple(
        item.absolute_path
        for item in pilot_inputs
        if item.kind
        in {
            "preexperiment_artifact",
            "preexperiment_metrics",
            "preexperiment_manifest",
            "stdout_log",
            "stderr_log",
            "raw_prime_gaps",
            "null_draws",
        }
    )
    artifact = ContestPostpilotObjectiveReviewArtifact.create(
        schema_version="contest-postpilot-objective-review-v1",
        direction=clean_direction,
        direction_sha256=canonical_sha256({"direction": clean_direction}),
        requirements_sha256=canonical_sha256({"requirements": clean_requirements}),
        direction_ref=direction_ref,
        brainstorm_artifact_hash=brainstorm.artifact_hash,
        brainstorm_artifact_file_sha256=_sha256_file(brainstorm_path),
        pilot_brief_sha256=brief_binding.sha256,
        preexperiment_artifact_hash=pilot.artifact_hash,
        preexperiment_artifact_file_sha256=_sha256_file(pilot_path),
        preexperiment_manifest_hash=pilot.manifest_hash,
        preexperiment_manifest_sha256=pilot.manifest_sha256,
        preexperiment_metrics_sha256=pilot.metrics_sha256,
        verified_inputs=verified_inputs,
        verified_inputs_bundle_sha256=canonical_sha256(
            [item.model_dump(mode="json") for item in verified_inputs]
        ),
        controller_binding_hash=controller.binding_hash,
        batch=batch,
        dispatch_id=record.dispatch_id,
        temporary_agent_id=record.temporary_agent_id,
        result_hash=record.result_hash,
        authorship_receipt_hash=record.authorship_receipt_hash,
        output_payload_sha256=output.output_payload_sha256,
        decision=str(payload["decision"]),
        research_objective_cn=str(payload["research_objective_cn"]),
        main_hypothesis_cn=str(payload["main_hypothesis_cn"]),
        falsification_cn=str(payload["falsification_cn"]),
        pilot_interpretation_cn=str(payload["pilot_interpretation_cn"]),
        review_cn=str(payload["review_cn"]),
        reference_indices=reference_indices,
        evidence_pointers=evidence_pointers,
        selected_skill_refs=tuple(item.skill_ref for item in skill_contexts),
        literature_catalog=literature,
        model_call_count=1,
        task_input_utf8_bytes=_task_input_utf8_bytes(task),
        scientific_rethink_count=1,
        further_scientific_retry_allowed=False,
        raw_csv_read_by_model=False,
        artifact_relative_path=_POSTPILOT_ARTIFACT_NAME,
    )
    write_json_model(output_root / _POSTPILOT_ARTIFACT_NAME, artifact)
    return artifact


def load_contest_direction_hypothesis_brainstorm(
    path: Path | str,
    *,
    verify_batch_files: bool = True,
) -> ContestDirectionHypothesisBrainstormArtifact:
    """Load a brainstorming artifact and optionally verify every retained batch file."""

    artifact_path = Path(path).expanduser().resolve()
    artifact = ContestDirectionHypothesisBrainstormArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    if verify_batch_files:
        _verify_brainstorm_batch_files(artifact_path.parent, artifact.batch)
    return artifact


def load_contest_postpilot_objective_review(
    path: Path | str,
    *,
    verify_inputs: bool = True,
) -> ContestPostpilotObjectiveReviewArtifact:
    """Load a post-pilot review and optionally re-hash every bound input."""

    artifact = ContestPostpilotObjectiveReviewArtifact.model_validate_json(
        Path(path).expanduser().resolve().read_text(encoding="utf-8")
    )
    if verify_inputs:
        for item in artifact.verified_inputs:
            candidate = Path(item.absolute_path)
            if (
                not candidate.is_file()
                or candidate.stat().st_size != item.bytes
                or _sha256_file(candidate) != item.sha256
            ):
                raise ContestDirectionHypothesisStageError(
                    f"post-pilot verified input changed: {item.absolute_path}"
                )
    return artifact


def _build_brainstorm_tasks(
    *,
    direction: str,
    requirements: str,
    direction_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    selected_skill_contexts: tuple[TemporaryQwenSkillContext, ...],
    literature_catalog: tuple[dict[str, JsonValue], ...],
    executable_adapters: tuple[ContestExecutableAdapterDescriptor, ...],
    max_tokens: int,
    timeout_seconds: int,
) -> tuple[TemporaryQwenContentTask, ...]:
    seed_hash = canonical_sha256(
        {
            "direction": direction,
            "requirements": requirements,
            "literature": list(literature_catalog),
            "adapters": [item.model_dump(mode="json") for item in executable_adapters],
        }
    )
    payload: dict[str, JsonValue] = {
        "指定方向": direction,
        "交付要求": requirements,
        "真实检索文献目录": list(literature_catalog),
        "可执行适配器目录": [item.model_dump(mode="json") for item in executable_adapters],
        "适配器边界": (
            "只可原样返回目录内adapter_id；无兼容适配器时必须返回no_adapter。"
            "选择具体adapter时，scientific_object、observable、metric必须逐字复制"
            "同一descriptor；null_models只能逐字选取该descriptor的supported_nulls子集，"
            "不得翻译、改写或跨adapter拼接。逐字字段相等仍不充分：整个指定方向和候选"
            "假设的科学语义必须落在descriptor描述的runner执行边界内；若增加表示变换、"
            "诱导距离/间隙、未列出的主指标或其他runner不会计算的步骤，必须返回no_adapter。"
            "不得用对象/观测量关键词掩盖科学语义变化。适配器元数据不是实验结果。"
        ),
        "字段要求": (
            "所有字符串字段必须非空且语义完整。即使 adapter_id=no_adapter，"
            "scientific_object、observable、metric 也必须用你自己的话分别描述"
            "拟研究的科学对象、可观测信号与评估指标，禁止留空或只写占位符。"
        ),
        "阶段边界": "当前只生成未评审候选；没有预实验结果，不得进行科学评审。",
    }
    schema = _brainstorm_schema(
        literature_count=len(literature_catalog),
        adapter_ids=tuple(item.adapter_id for item in executable_adapters),
    )
    return tuple(
        TemporaryQwenContentTask(
            dispatch_id=f"direction-hypothesis-{seed_hash[:16]}-{ordinal}",
            temporary_agent_id=f"temporary-direction-hypothesis-{seed_hash[:16]}-{ordinal}",
            parent_task_id=parent_task_id,
            task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
            task_instruction=instruction,
            input_refs=(direction_ref,),
            input_payload=payload,
            expected_output_schema=schema,
            chinese_output_fields=(
                "hypothesis_cn",
                "research_objective_cn",
                "falsification_cn",
            ),
            skill_contexts=selected_skill_contexts,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_attempts=1,
        )
        for ordinal, (_role, instruction) in enumerate(_ROLE_SPECS, start=1)
    )


def _build_candidates(
    batch: TemporaryQwenBatchArtifact,
    tasks: tuple[TemporaryQwenContentTask, ...],
    *,
    literature_count: int,
    direction: str,
    executable_adapters: tuple[ContestExecutableAdapterDescriptor, ...],
) -> tuple[ContestHypothesisCandidate, ...]:
    roles = {task.dispatch_id: role for task, (role, _) in zip(tasks, _ROLE_SPECS, strict=True)}
    records = {item.dispatch_id: item for item in batch.task_records}
    adapter_by_id = {item.adapter_id: item for item in executable_adapters}
    candidates: list[ContestHypothesisCandidate] = []
    for output in batch.stable_outputs:
        payload = output.output_payload
        record = records[output.dispatch_id]
        raw_null_models = payload.get("null_models")
        if not isinstance(raw_null_models, list) or not raw_null_models:
            raise ContestDirectionHypothesisStageError(
                "candidate null_models must be a non-empty list"
            )
        if record.result_hash is None or record.authorship_receipt_hash is None:
            raise ContestDirectionHypothesisStageError("candidate receipt is missing")
        role = roles[output.dispatch_id]
        projected_adapter_id = str(payload["adapter_id"])
        if projected_adapter_id in adapter_by_id:
            compatibility = assess_adapter_semantic_compatibility(
                adapter_by_id[projected_adapter_id],
                scope_texts=(direction,),
                candidate=payload,
            )
            if not compatibility.compatible:
                # Preserve the model-authored raw response in the batch receipt,
                # but never expose a semantically false executable binding.
                projected_adapter_id = "no_adapter"
        candidates.append(
            ContestHypothesisCandidate(
                candidate_number=len(candidates) + 1,
                candidate_id=_candidate_id(
                    role=role,
                    dispatch_id=output.dispatch_id,
                    output_payload_sha256=output.output_payload_sha256,
                ),
                role=role,
                dispatch_id=output.dispatch_id,
                hypothesis_cn=str(payload["hypothesis_cn"]),
                research_objective_cn=str(payload["research_objective_cn"]),
                falsification_cn=str(payload["falsification_cn"]),
                nearest_work_difference_cn=str(payload["nearest_work_difference_cn"]),
                transferred_method_baseline_cn=str(payload["transferred_method_baseline_cn"]),
                strongest_counterevidence_cn=str(payload["strongest_counterevidence_cn"]),
                adapter_id=projected_adapter_id,
                scientific_object=str(payload["scientific_object"]),
                observable=str(payload["observable"]),
                metric=str(payload["metric"]),
                null_models=tuple(str(item) for item in raw_null_models),
                reference_indices=_validated_indices(
                    payload.get("reference_indices"), upper_bound=literature_count
                ),
                output_payload_sha256=output.output_payload_sha256,
                result_hash=record.result_hash,
                authorship_receipt_hash=record.authorship_receipt_hash,
            )
        )
    return tuple(candidates)


def _build_postpilot_task(
    *,
    direction: str,
    requirements: str,
    direction_ref: TemporaryAgentInputRef,
    parent_task_id: str,
    brainstorm: ContestDirectionHypothesisBrainstormArtifact,
    brainstorm_path: Path,
    pilot_brief_text: str,
    pilot_brief_binding: ContestVerifiedStageInput,
    pilot: ContestPrimePreexperimentArtifact,
    pilot_path: Path,
    verified_inputs: tuple[ContestVerifiedStageInput, ...],
    selected_skill_contexts: tuple[TemporaryQwenSkillContext, ...],
    literature_catalog: tuple[dict[str, JsonValue], ...],
    derived_memory_context: dict[str, Any] | None,
    max_tokens: int,
    timeout_seconds: int,
) -> TemporaryQwenContentTask:
    pilot_root = pilot_path.parent
    metrics_path = (pilot_root / pilot.metrics_relative_path).resolve()
    stdout_path = (pilot_root / pilot.stdout_log_relative_path).resolve()
    stderr_path = (pilot_root / pilot.stderr_log_relative_path).resolve()
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics_projection = _project_preexperiment_metrics(metrics_payload)
    pilot_brief_projection = _project_pilot_brief(pilot_brief_text)
    digest = canonical_sha256(
        {
            "brainstorm": brainstorm.artifact_hash,
            "pilot_brief": pilot_brief_binding.sha256,
            "preexperiment": pilot.artifact_hash,
            "manifest": pilot.manifest_hash,
        }
    )
    brainstorm_ref = TemporaryAgentInputRef(
        artifact_id=f"direction-brainstorm-{brainstorm.artifact_hash[:16]}",
        source_ref=brainstorm_path.as_posix(),
        sha256=brainstorm.artifact_hash,
    )
    brief_ref = TemporaryAgentInputRef(
        artifact_id=f"pilot-brief-{pilot_brief_binding.sha256[:16]}",
        source_ref=pilot_brief_binding.absolute_path,
        sha256=pilot_brief_binding.sha256,
        media_type="text/plain",
    )
    pilot_ref = TemporaryAgentInputRef(
        artifact_id=pilot.run_id,
        source_ref=pilot_path.as_posix(),
        sha256=pilot.artifact_hash,
    )
    input_payload: dict[str, JsonValue] = {
        "指定方向": direction,
        "交付要求": requirements,
        "pilot_brief": {
            "sha256": pilot_brief_binding.sha256,
            "完整字节已验证": True,
            "送审内容投影": pilot_brief_projection,
            "投影边界": (
                "完整文件已做字节哈希验证；只投影程序选中的一个候选、adapter、"
                "冻结协议和输入哈希，不包含其他候选或provisional plan正文。"
            ),
        },
        "真实预实验": {
            "artifact_hash": pilot.artifact_hash,
            "manifest_hash": pilot.manifest_hash,
            "metrics_sha256": pilot.metrics_sha256,
            "study_phase": pilot.study_phase,
            "formal_experiment_executed": False,
            "scientific_boundary_zh": pilot.scientific_boundary_zh,
            "metrics_json关键科学投影": metrics_projection,
            "metrics投影边界": (
                "程序已验证完整metrics文件；模型读取全部aggregate_results及"
                "validation/scientific顶层字段，不读取重复路径或区间明细字段。"
            ),
            "stdout正文": stdout_path.read_text(encoding="utf-8"),
            "stderr正文": stderr_path.read_text(encoding="utf-8"),
        },
        "已验证输入清单投影": _project_verified_input_inventory(
            verified_inputs,
            brainstorm_root=brainstorm_path.parent,
            pilot_root=pilot_root,
            pilot_brief_path=Path(pilot_brief_binding.absolute_path),
        ),
        "原始数据读取边界": (
            "raw与null CSV已由程序逐文件做bytes与SHA-256验证；"
            "本评审模型没有读取CSV逐行正文，不得声称已逐行检查。"
        ),
        "真实检索文献目录": list(literature_catalog),
        "决策规则": (
            "只在本次调用内作一次retain、narrow_once或terminate决定。"
            "若预实验否定原候选，可在narrow_once中收窄一次；不得请求第二次科学重想。"
            "不得由单一p值机械决定，须同时解释对照、效应、边界与替代解释。"
        ),
    }
    memory_context_hash = optional_dreaming_context_hash(derived_memory_context)
    if memory_context_hash is not None:
        input_payload["Dreaming派生导航上下文哈希"] = memory_context_hash
        input_payload["Dreaming边界"] = (
            "该上下文只用于定位原始制品，不是科学证据；所有结论仍须依据本任务"
            "已提供且经程序核验的真实文献与预实验制品。"
        )
    return TemporaryQwenContentTask(
        dispatch_id=f"postpilot-objective-{digest[:20]}",
        temporary_agent_id=f"temporary-postpilot-objective-{digest[:20]}",
        parent_task_id=parent_task_id,
        task_kind=TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
        task_instruction=(
            "你是与预实验前头脑风暴代理分离的独立科学评审者。必须先解释真实预实验"
            "及其零模型和外推边界，再作一次retain、narrow_once或terminate决定。"
            "输出最终研究目标、核心假设、可证伪条件和预实验解释；不得新增实验结果、"
            "不得把探索性预实验写成正式实验，也不得要求第二次科学重想。"
        ),
        input_refs=(direction_ref, brainstorm_ref, brief_ref, pilot_ref),
        input_payload=input_payload,
        expected_output_schema=_postpilot_schema(len(literature_catalog)),
        chinese_output_fields=(
            "research_objective_cn",
            "main_hypothesis_cn",
            "falsification_cn",
            "pilot_interpretation_cn",
            "review_cn",
        ),
        skill_contexts=selected_skill_contexts,
        derived_memory_context=derived_memory_context,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_attempts=1,
    )


def _brainstorm_schema(
    *, literature_count: int, adapter_ids: tuple[str, ...]
) -> dict[str, JsonValue]:
    reference_item: dict[str, JsonValue] = {"type": "integer", "minimum": 1}
    if literature_count:
        reference_item["maximum"] = literature_count
    return {
        "type": "object",
        "required": [
            "hypothesis_cn",
            "research_objective_cn",
            "falsification_cn",
            "nearest_work_difference_cn",
            "transferred_method_baseline_cn",
            "strongest_counterevidence_cn",
            "adapter_id",
            "scientific_object",
            "observable",
            "metric",
            "null_models",
            "reference_indices",
        ],
        "properties": {
            "hypothesis_cn": {"type": "string", "minLength": 1},
            "research_objective_cn": {"type": "string", "minLength": 1},
            "falsification_cn": {"type": "string", "minLength": 1},
            "nearest_work_difference_cn": {"type": "string", "minLength": 1},
            "transferred_method_baseline_cn": {"type": "string", "minLength": 1},
            "strongest_counterevidence_cn": {"type": "string", "minLength": 1},
            "adapter_id": {"type": "string", "enum": [*adapter_ids, "no_adapter"]},
            "scientific_object": {"type": "string", "minLength": 1},
            "observable": {"type": "string", "minLength": 1},
            "metric": {"type": "string", "minLength": 1},
            "null_models": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "reference_indices": {
                "type": "array",
                "items": reference_item,
                "minItems": 1 if literature_count else 0,
                "maxItems": literature_count,
            },
        },
        "additionalProperties": False,
    }


def _postpilot_schema(literature_count: int) -> dict[str, JsonValue]:
    reference_item: dict[str, JsonValue] = {"type": "integer", "minimum": 1}
    if literature_count:
        reference_item["maximum"] = literature_count
    return {
        "type": "object",
        "required": [
            "decision",
            "research_objective_cn",
            "main_hypothesis_cn",
            "falsification_cn",
            "pilot_interpretation_cn",
            "review_cn",
            "reference_indices",
        ],
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["retain", "narrow_once", "terminate"],
            },
            "research_objective_cn": {"type": "string"},
            "main_hypothesis_cn": {"type": "string"},
            "falsification_cn": {"type": "string"},
            "pilot_interpretation_cn": {"type": "string"},
            "review_cn": {"type": "string"},
            "reference_indices": {
                "type": "array",
                "items": reference_item,
                "maxItems": literature_count,
            },
        },
        "additionalProperties": False,
    }


def _project_preexperiment_metrics(payload: Any) -> dict[str, JsonValue]:
    """Keep aggregate validation values and scientific boundaries only."""

    if not isinstance(payload, dict):
        raise ContestDirectionHypothesisStageError("preexperiment metrics must be a JSON object")
    raw_aggregates = payload.get("aggregate_results")
    if not isinstance(raw_aggregates, list):
        raise ContestDirectionHypothesisStageError("preexperiment metrics omit aggregate results")
    return {
        key: payload.get(key)
        for key in (
            "schema_version",
            "run_id",
            "status",
            "study_phase",
            "protocol_status",
            "parameters_hash",
            "primary_metric",
            "primary_null_model",
            "required_sensitivity_null_models",
            "standardized_effect_definition",
            "scientific_boundary_zh",
        )
    } | {
        "aggregate_results": raw_aggregates,
    }


def _project_pilot_brief(text: str) -> dict[str, JsonValue]:
    """Project whole scientific fields from a long brief without slicing a field."""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        if len(text) > _PILOT_BRIEF_CONTEXT_CHARACTERS:
            raise ContestDirectionHypothesisStageError(
                "long pilot brief must be JSON so whole scientific fields can be projected"
            ) from exc
        return {"projection": "complete_text", "content": text}
    schema_version = parsed.get("schema_version") if isinstance(parsed, dict) else None
    if schema_version in {
        "contest-prime-gap-pilot-brief-v1",
        "contest-prime-gap-pilot-brief-v2",
    }:
        literature_binding = (
            "literature_artifact_hash"
            if schema_version == "contest-prime-gap-pilot-brief-v1"
            else "merged_literature_artifact_hash"
        )
        required = (
            "direction",
            "artifact_hash",
            "direction_input_hash",
            "hypothesis_artifact_hash",
            literature_binding,
            "skill_routing_artifact_hash",
            "provisional_plan_artifact_hash",
            "selected_candidate",
            "adapter_descriptor",
            "frozen_parameters_projection",
        )
        if any(key not in parsed for key in required):
            raise ContestDirectionHypothesisStageError(
                "prime pilot brief omits a required selected-candidate field"
            )
        return {
            "projection": "selected_candidate_adapter_protocol_and_hashes",
            **{key: parsed[key] for key in required},
        }
    if len(text) <= _PILOT_BRIEF_CONTEXT_CHARACTERS:
        return {"projection": "complete_json", "content": parsed}
    selected: list[JsonValue] = []
    budget = 0
    terms = (
        "problem",
        "question",
        "objective",
        "hypothesis",
        "fals",
        "experiment",
        "metric",
        "null",
        "baseline",
        "method",
        "问题",
        "目标",
        "假设",
        "证伪",
        "实验",
        "指标",
        "零模型",
        "基线",
        "方法",
    )

    def visit(value: Any, path: str) -> None:
        nonlocal budget
        if budget >= _PILOT_BRIEF_CONTEXT_CHARACTERS:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                lowered = str(key).casefold()
                encoded = json.dumps(child, ensure_ascii=False, separators=(",", ":"))
                if any(term in lowered for term in terms) and len(encoded) <= 2_000:
                    if budget + len(encoded) <= _PILOT_BRIEF_CONTEXT_CHARACTERS:
                        selected.append({"json_path": child_path, "value": child})
                        budget += len(encoded)
                    continue
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(parsed, "")
    return {
        "projection": "selected_complete_fields",
        "selected_fields": selected,
        "unselected_fields_were_not_read_by_model": True,
    }


def _compact_input_path(
    item: ContestVerifiedStageInput,
    *,
    brainstorm_root: Path,
    pilot_root: Path,
    pilot_brief_path: Path,
) -> str:
    path = Path(item.absolute_path)
    if path == pilot_brief_path.resolve():
        return f"pilot-brief/{path.name}"
    for prefix, root in (("brainstorm", brainstorm_root), ("preexperiment", pilot_root)):
        try:
            relative = path.relative_to(root.resolve())
        except ValueError:
            continue
        return (PurePosixPath(prefix) / PurePosixPath(relative.as_posix())).as_posix()
    return f"input/{item.sha256[:16]}/{path.name}"


def _project_verified_input_inventory(
    items: tuple[ContestVerifiedStageInput, ...],
    *,
    brainstorm_root: Path,
    pilot_root: Path,
    pilot_brief_path: Path,
) -> dict[str, JsonValue]:
    """Give the reviewer key files and aggregate CSV bindings, retaining all hashes on disk."""

    def compact(item: ContestVerifiedStageInput) -> dict[str, JsonValue]:
        return {
            "kind": item.kind,
            "path": _compact_input_path(
                item,
                brainstorm_root=brainstorm_root,
                pilot_root=pilot_root,
                pilot_brief_path=pilot_brief_path,
            ),
            "bytes": item.bytes,
            "sha256": item.sha256,
        }

    key_kinds = {
        "brainstorm_artifact",
        "pilot_brief",
        "preexperiment_artifact",
        "preexperiment_manifest",
        "metrics",
        "stdout_log",
        "stderr_log",
    }
    key_files: list[JsonValue] = [compact(item) for item in items if item.kind in key_kinds]
    bulk: dict[str, JsonValue] = {}
    for kind in ("raw_prime_gaps", "null_draws"):
        selected = [item for item in items if item.kind == kind]
        bulk[kind] = {
            "file_count": len(selected),
            "total_bytes": sum(item.bytes for item in selected),
            "bundle_sha256": canonical_sha256([item.model_dump(mode="json") for item in selected]),
        }
    return {
        "verified_inputs_bundle_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in items]
        ),
        "verified_file_count": len(items),
        "verified_total_bytes": sum(item.bytes for item in items),
        "key_files": key_files,
        "bulk_csv_groups": bulk,
        "projection_boundary": (
            "artifact保留全部逐文件路径、bytes和SHA-256；模型只见关键文件及"
            "raw/null CSV的数量、总字节和组哈希。"
        ),
    }


def _select_postpilot_literature(
    *,
    brainstorm: ContestDirectionHypothesisBrainstormArtifact,
    literature_catalog: tuple[dict[str, JsonValue], ...],
    pilot_brief_text: str,
) -> tuple[dict[str, JsonValue], ...]:
    """Select whole records cited by the one candidate compiled into the pilot."""

    try:
        brief = json.loads(pilot_brief_text)
    except json.JSONDecodeError as exc:
        raise ContestDirectionHypothesisStageError(
            "post-pilot literature selection requires a JSON pilot brief"
        ) from exc
    selected_payload = brief.get("selected_candidate") if isinstance(brief, dict) else None
    if not isinstance(selected_payload, dict):
        raise ContestDirectionHypothesisStageError(
            "pilot brief omits the selected executable candidate"
        )
    selected_id = str(selected_payload.get("candidate_id") or "")
    selected_candidate = next(
        (item for item in brainstorm.candidates if item.candidate_id == selected_id),
        None,
    )
    if selected_candidate is None:
        raise ContestDirectionHypothesisStageError(
            "pilot brief selected candidate is absent from brainstorm"
        )
    for field in ("adapter_id", "scientific_object", "observable", "metric"):
        if str(selected_payload.get(field) or "") != str(getattr(selected_candidate, field)):
            raise ContestDirectionHypothesisStageError(
                f"pilot brief selected candidate {field} differs from brainstorm"
            )
    raw_references = selected_payload.get("reference_indices")
    if raw_references != list(selected_candidate.reference_indices):
        raise ContestDirectionHypothesisStageError(
            "pilot brief selected candidate references differ from brainstorm"
        )
    referenced = list(selected_candidate.reference_indices)
    if literature_catalog and not referenced:
        raise ContestDirectionHypothesisStageError(
            "selected hypothesis did not cite any real literature; refusing to fabricate [1]"
        )
    if any(index > len(literature_catalog) for index in referenced):
        raise ContestDirectionHypothesisStageError(
            "brainstorm reference cannot be projected into post-pilot literature"
        )
    selected: list[dict[str, JsonValue]] = []
    for source_index in referenced[:_MAX_POSTPILOT_LITERATURE_RECORDS]:
        record = dict(literature_catalog[source_index - 1])
        record["source_catalog_index"] = source_index
        record["catalog_index"] = len(selected) + 1
        selected.append(record)
    return tuple(selected)


def _task_input_utf8_bytes(task: TemporaryQwenContentTask) -> int:
    """Measure the exact task bundle used by the temporary-pool preflight."""

    payload = {
        "task_instruction": task.task_instruction,
        "input_refs": [item.model_dump(mode="json") for item in task.input_refs],
        "input_payload": task.input_payload,
        "derived_memory_context": task.derived_memory_context,
        "expected_output_schema": task.expected_output_schema,
        "chinese_output_fields": task.chinese_output_fields,
    }
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _normalize_literature_catalog(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, JsonValue], ...]:
    normalized: list[dict[str, JsonValue]] = []
    for index, record in enumerate(records, start=1):
        title = str(record.get("title") or "").strip()
        url = str(record.get("source_url") or record.get("url") or "").strip()
        retrieved_from = str(record.get("retrieved_from") or "").strip()
        retrieved_at = str(record.get("retrieved_at") or "").strip()
        if not title or not url or not retrieved_from or not retrieved_at:
            raise ContestDirectionHypothesisStageError(
                "literature requires title, URL, retrieval source, and retrieval time"
            )
        raw_abstract = str(record.get("abstract") or "").strip()
        normalized.append(
            {
                "catalog_index": index,
                "title": title,
                "source_url": url,
                "retrieved_from": retrieved_from,
                "retrieved_at": retrieved_at,
                "record_id": str(record.get("record_id") or "").strip() or None,
                "source_stages": [
                    str(item).strip()
                    for item in (record.get("source_stages") or [])
                    if str(item).strip()
                ],
                "abstract": _plain_text_literature_abstract(raw_abstract) or None,
                "abstract_projection": (
                    "full_text_after_html_xml_markup_removal_entity_decoding_and_"
                    "whitespace_normalization; no_length_truncation"
                ),
                "doi": str(record.get("doi") or "").strip() or None,
                "record_sha256": canonical_sha256(dict(record)),
            }
        )
    return tuple(normalized)


def _project_postpilot_dreaming_context(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep bounded receipt navigation; full recall bytes remain persisted upstream."""

    normalized = normalize_optional_dreaming_context(value)
    if normalized is None:
        return None
    compact_projections: list[dict[str, Any]] = []
    for projection in normalized["projections"]:
        if not isinstance(projection, Mapping):
            raise ContestDirectionHypothesisStageError(
                "post-pilot Dreaming projection must be an object"
            )
        raw_bindings = projection.get("raw_bindings")
        summary = projection.get("summary")
        if not isinstance(raw_bindings, list) or not isinstance(summary, str):
            raise ContestDirectionHypothesisStageError(
                "post-pilot Dreaming projection lacks persisted source bindings"
            )
        required = (
            "source_stage",
            "stage_receipt_hash",
            "projection_id",
            "projection_hash",
        )
        if any(not isinstance(projection.get(key), str) or not projection[key] for key in required):
            raise ContestDirectionHypothesisStageError(
                "post-pilot Dreaming projection lacks navigation identity"
            )
        compact_projections.append(
            {
                **{key: projection[key] for key in required},
                "summary_sha256": canonical_sha256({"summary": summary}),
                "raw_binding_count": len(raw_bindings),
                "raw_bindings_bundle_sha256": canonical_sha256(raw_bindings),
                "projection_boundary": (
                    "full summary and raw bindings remain in the hash-bound recall receipt; "
                    "model receives identity and bundle hashes only"
                ),
            }
        )
    return {
        key: normalized[key]
        for key in (
            "context_kind",
            "recall_hash",
            "epistemic_boundary_zh",
            "derived_context_is_evidence",
            "model_consumption_proven_by_this_receipt",
        )
    } | {"projections": compact_projections}


class _LiteratureMarkupTextExtractor(HTMLParser):
    """Collect every text node, including MathML annotation and XML CDATA."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.text_nodes: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text_nodes.append(data)

    def handle_starttag(self, _tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        self.text_nodes.append(" ")

    def handle_startendtag(self, _tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        self.text_nodes.append(" ")

    def handle_endtag(self, _tag: str) -> None:
        self.text_nodes.append(" ")

    def handle_entityref(self, name: str) -> None:
        self.text_nodes.append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.text_nodes.append(html.unescape(f"&#{name};"))

    def unknown_decl(self, data: str) -> None:
        if data.startswith("CDATA[") and data.endswith("]"):
            self.text_nodes.append(data[6:-1])


def _plain_text_literature_abstract(value: str) -> str:
    """Project complete abstract text without carrying transport-only markup."""

    cdata_preserved = re.sub(
        r"<!\[CDATA\[(.*?)\]\]>",
        lambda match: html.escape(match.group(1), quote=False),
        value,
        flags=re.DOTALL,
    )
    parser = _LiteratureMarkupTextExtractor()
    parser.feed(cdata_preserved)
    parser.close()
    return re.sub(r"\s+", " ", html.unescape("".join(parser.text_nodes))).strip()


def _drop_largest_serialized_literature_record(
    records: tuple[dict[str, JsonValue], ...],
) -> tuple[dict[str, JsonValue], ...]:
    """Drop the costliest whole projection while preserving source-index identity."""

    if len(records) <= 1:
        raise ContestDirectionHypothesisStageError(
            "cannot shrink a post-pilot literature catalog below one whole record"
        )
    largest_index = max(
        range(len(records)),
        key=lambda index: (
            len(
                json.dumps(
                    records[index],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            index,
        ),
    )
    retained: list[dict[str, JsonValue]] = []
    for record in records[:largest_index] + records[largest_index + 1 :]:
        projected = dict(record)
        projected["catalog_index"] = len(retained) + 1
        retained.append(projected)
    return tuple(retained)


def _normalize_adapters(
    records: Sequence[Mapping[str, Any]],
) -> tuple[ContestExecutableAdapterDescriptor, ...]:
    adapters: list[ContestExecutableAdapterDescriptor] = []
    seen: set[str] = set()
    for record in records:
        adapter_id = str(record.get("adapter_id") or "").strip()
        scientific_object = str(record.get("scientific_object") or "").strip()
        observable = str(record.get("observable") or "").strip()
        raw_metrics = record.get("supported_metrics") or ()
        raw_nulls = record.get("supported_nulls") or ()
        metrics = tuple(str(item).strip() for item in raw_metrics if str(item).strip())
        nulls = tuple(str(item).strip() for item in raw_nulls if str(item).strip())
        if not adapter_id or not scientific_object or not observable or not metrics or not nulls:
            raise ContestDirectionHypothesisStageError("adapter metadata is incomplete")
        if adapter_id == "no_adapter" or adapter_id in seen:
            raise ContestDirectionHypothesisStageError("adapter id is reserved or repeated")
        seen.add(adapter_id)
        adapters.append(
            ContestExecutableAdapterDescriptor.create(
                adapter_id=adapter_id,
                scientific_object=scientific_object,
                observable=observable,
                supported_metrics=metrics,
                supported_nulls=nulls,
                description=str(record.get("description") or "").strip() or None,
            )
        )
    return tuple(adapters)


def _load_and_verify_brainstorm(
    path: Path,
) -> tuple[
    ContestDirectionHypothesisBrainstormArtifact,
    tuple[ContestVerifiedStageInput, ...],
]:
    artifact = load_contest_direction_hypothesis_brainstorm(path, verify_batch_files=True)
    inputs = [_verified_file("brainstorm_artifact", path)]
    inputs.extend(_brainstorm_batch_bindings(path.parent, artifact.batch))
    return artifact, _deduplicate_verified_inputs(tuple(inputs))


def _verify_brainstorm_batch_files(root: Path, batch: TemporaryQwenBatchArtifact) -> None:
    _brainstorm_batch_bindings(root, batch)


def _brainstorm_batch_bindings(
    root: Path, batch: TemporaryQwenBatchArtifact
) -> tuple[ContestVerifiedStageInput, ...]:
    bindings: list[ContestVerifiedStageInput] = []
    batch_path = _inside(root, batch.output_relative_path)
    persisted_batch = TemporaryQwenBatchArtifact.model_validate_json(
        batch_path.read_text(encoding="utf-8")
    )
    if persisted_batch.artifact_hash != batch.artifact_hash:
        raise ContestDirectionHypothesisStageError("brainstorm batch artifact changed")
    bindings.append(_verified_file("brainstorm_batch", batch_path))
    manifest_path = _inside(root, batch.manifest_relative_path)
    manifest = TemporaryAgentBatchManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.batch_hash != batch.manifest_hash:
        raise ContestDirectionHypothesisStageError("brainstorm batch manifest changed")
    bindings.append(_verified_file("brainstorm_manifest", manifest_path))
    for expected in batch.task_records:
        record_path = _inside(root, expected.record_relative_path)
        record = TemporaryQwenTaskRecord.model_validate_json(
            record_path.read_text(encoding="utf-8")
        )
        if record.record_hash != expected.record_hash:
            raise ContestDirectionHypothesisStageError("brainstorm task record changed")
        bindings.append(_verified_file("brainstorm_task_record", record_path))
        bindings.append(
            _verify_typed_file(
                root,
                record.assignment_relative_path,
                "brainstorm_assignment",
                TemporaryAgentAssignment,
                "assignment_hash",
                record.assignment_hash,
            )
        )
        bindings.append(
            _verify_typed_file(
                root,
                record.archive_relative_path,
                "brainstorm_archive",
                TemporaryAgentArchiveRecord,
                "archive_hash",
                record.archive_hash,
            )
        )
        if record.result_relative_path and record.result_hash:
            bindings.append(
                _verify_typed_file(
                    root,
                    record.result_relative_path,
                    "brainstorm_result",
                    TemporaryAgentResultArtifact,
                    "result_hash",
                    record.result_hash,
                )
            )
        if record.authorship_receipt_relative_path and record.authorship_receipt_hash:
            bindings.append(
                _verify_typed_file(
                    root,
                    record.authorship_receipt_relative_path,
                    "brainstorm_authorship_receipt",
                    ModelAuthorshipReceipt,
                    "receipt_hash",
                    record.authorship_receipt_hash,
                )
            )
    return tuple(bindings)


def _verify_typed_file(
    root: Path,
    relative_path: str,
    kind: str,
    model_type: Any,
    hash_field: str,
    expected_hash: str,
) -> ContestVerifiedStageInput:
    path = _inside(root, relative_path)
    model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    if getattr(model, hash_field) != expected_hash:
        raise ContestDirectionHypothesisStageError(f"{kind} changed")
    return _verified_file(kind, path)


def _verified_preexperiment_inputs(
    artifact_path: Path,
    artifact: ContestPrimePreexperimentArtifact,
) -> tuple[ContestVerifiedStageInput, ...]:
    root = artifact_path.parent
    bindings = [_verified_file("preexperiment_artifact", artifact_path)]
    manifest_path = _inside(root, artifact.manifest_relative_path)
    bindings.append(_verified_file("preexperiment_manifest", manifest_path))
    for evidence in artifact.evidence_files:
        bindings.append(_verified_file(evidence.kind, _inside(root, evidence.relative_path)))
    return tuple(bindings)


def _verified_file(kind: str, path: Path) -> ContestVerifiedStageInput:
    if not path.is_file():
        raise ContestDirectionHypothesisStageError(f"required input is missing: {path}")
    return ContestVerifiedStageInput(
        kind=kind,
        absolute_path=path.resolve().as_posix(),
        bytes=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def _deduplicate_verified_inputs(
    items: Sequence[ContestVerifiedStageInput],
) -> tuple[ContestVerifiedStageInput, ...]:
    by_path: dict[str, ContestVerifiedStageInput] = {}
    for item in items:
        existing = by_path.get(item.absolute_path)
        if existing is not None and (
            existing.sha256 != item.sha256 or existing.bytes != item.bytes
        ):
            raise ContestDirectionHypothesisStageError("input path has conflicting hashes")
        by_path.setdefault(item.absolute_path, item)
    return tuple(by_path.values())


def _validated_indices(value: JsonValue, *, upper_bound: int) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ContestDirectionHypothesisStageError("reference_indices must be a list")
    result: list[int] = []
    for item in value:
        if (
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 1
            or item > upper_bound
            or item in result
        ):
            raise ContestDirectionHypothesisStageError("unknown literature reference")
        result.append(item)
    return tuple(result)


def _candidate_id(
    *, role: ContestHypothesisRole, dispatch_id: str, output_payload_sha256: str
) -> str:
    digest = canonical_sha256(
        {
            "role": role,
            "dispatch_id": dispatch_id,
            "output_payload_sha256": output_payload_sha256,
        }
    )
    return f"hypothesis-candidate-{digest[:24]}"


def _tasks_hash(tasks: Sequence[TemporaryQwenContentTask]) -> str:
    return canonical_sha256([item.model_dump(mode="json") for item in tasks])


def _prepare_empty_output_dir(path: Path | str) -> Path:
    root = Path(path).expanduser().resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ContestDirectionHypothesisStageError(
            "stage output_dir must be absent or empty; refusing overwrite"
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _inside(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ContestDirectionHypothesisStageError("artifact path escapes its root") from exc
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ContestDirectionHypothesisBrainstormArtifact",
    "ContestDirectionHypothesisStageError",
    "ContestExecutableAdapterDescriptor",
    "ContestHypothesisCandidate",
    "ContestPostpilotObjectiveReviewArtifact",
    "ContestVerifiedStageInput",
    "PostpilotDecision",
    "load_contest_direction_hypothesis_brainstorm",
    "load_contest_postpilot_objective_review",
    "run_contest_direction_hypothesis_brainstorm",
    "run_contest_postpilot_objective_review",
]
