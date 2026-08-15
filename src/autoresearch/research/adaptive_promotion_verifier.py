"""Independent Qwen review invoked only when an adaptive branch asks to advance."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.adaptive_capabilities import (
    AdaptiveLiteratureRetrievalArtifact,
    AdaptiveRetrievedPaper,
)
from autoresearch.research.adaptive_skill_router import (
    load_repository_skill_contexts,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    FeedbackOrigin,
    FormalPromotionVerification,
    ModelResearchActionDraft,
    PromotionGateAssessment,
    PromotionVerifier,
    assess_branch_promotion,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]
_MIN_REASONING_CHARACTERS = 200
_MAX_PROMPT_CHARACTERS = 100_000


class AdaptivePromotionVerificationError(AdaptiveResearchLoopError):
    """Raised when independent promotion evidence cannot be replayed exactly."""


def _require_chinese(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not any("\u3400" <= character <= "\u9fff" for character in normalized):
        raise ValueError(f"{field_name} 必须包含中文")
    return normalized


class AdaptivePriorWorkComparison(KernelContract):
    """One abstract-level comparison; it is deliberately weaker than novelty proof."""

    source_ref: str = Field(min_length=1, max_length=4_000)
    overlap_cn: str = Field(min_length=1, max_length=8_000)
    difference_cn: str = Field(min_length=1, max_length=8_000)
    direct_method_copy: bool
    insufficient_abstract: bool

    @field_validator("overlap_cn", "difference_cn")
    @classmethod
    def _chinese_comparison(cls, value: str, info: Any) -> str:
        return _require_chinese(value, info.field_name)


class AdaptivePromotionReviewDraft(KernelContract):
    """Structured scientific judgment returned by an independent Qwen call."""

    schema_version: Literal["adaptive-promotion-review-draft-v1"] = (
        "adaptive-promotion-review-draft-v1"
    )
    question_hypothesis_mechanism_coherent: bool
    decisive_test_targets_falsifier: bool
    falsifier_is_operational: bool
    control_is_discriminating: bool
    resource_scope_feasible: bool
    prior_work_comparisons: list[AdaptivePriorWorkComparison] = Field(
        min_length=2,
        max_length=64,
    )
    findings_cn: list[str] = Field(default_factory=list, max_length=64)
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("findings_cn")
    @classmethod
    def _chinese_findings(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(normalized) != len(
            set(normalized)
        ):
            raise ValueError("independent promotion findings must be unique and non-empty")
        return [_require_chinese(item, "findings_cn") for item in normalized]

    @model_validator(mode="after")
    def _false_checks_require_findings(self) -> AdaptivePromotionReviewDraft:
        checks = (
            self.question_hypothesis_mechanism_coherent,
            self.decisive_test_targets_falsifier,
            self.falsifier_is_operational,
            self.control_is_discriminating,
            self.resource_scope_feasible,
        )
        prior_clear = all(
            not item.direct_method_copy and not item.insufficient_abstract
            for item in self.prior_work_comparisons
        )
        if (not all(checks) or not prior_clear) and not self.findings_cn:
            raise ValueError("a declined independent promotion review needs findings")
        return self


class AdaptivePromotionVerifierArtifactContent(KernelContract):
    """Replayable interaction and decision retained around the loop's compact result."""

    schema_version: Literal["adaptive-promotion-verification-artifact-v1"] = (
        "adaptive-promotion-verification-artifact-v1"
    )
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1)
    branch_id: StableId
    snapshot_hash: Sha256
    proposal_hash: Sha256
    promotion_assessment_hash: Sha256
    selected_papers: list[AdaptiveRetrievedPaper] = Field(min_length=2, max_length=64)
    messages: list[dict[str, str]] = Field(min_length=2, max_length=16)
    messages_sha256: Sha256
    provider: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=512)
    response_binding: RawMemoryBinding
    reasoning_binding: RawMemoryBinding
    reasoning_character_count: int = Field(ge=_MIN_REASONING_CHARACTERS)
    review: AdaptivePromotionReviewDraft
    verification: FormalPromotionVerification
    output_relative_path: str = Field(min_length=1, max_length=1_024)
    created_at: datetime
    scientific_evidence_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def _utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("promotion verification timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("output_relative_path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or ":" in normalized:
            raise ValueError("promotion verification path escapes its run root")
        return path.as_posix()

    @model_validator(mode="after")
    def _cross_bind(self) -> AdaptivePromotionVerifierArtifactContent:
        if self.messages_sha256 != canonical_sha256(self.messages):
            raise ValueError("promotion verifier messages hash mismatch")
        refs = [paper.source_ref for paper in self.selected_papers]
        comparison_refs = [
            comparison.source_ref for comparison in self.review.prior_work_comparisons
        ]
        if refs != comparison_refs or len(refs) != len(set(refs)):
            raise ValueError("promotion review did not compare every selected source once")
        if self.verification.branch_id != self.branch_id:
            raise ValueError("promotion verification branch mismatch")
        if self.verification.promotion_assessment_hash != (
            self.promotion_assessment_hash
        ):
            raise ValueError("promotion verification assessment mismatch")
        return self


class AdaptivePromotionVerifierArtifact(
    AdaptivePromotionVerifierArtifactContent
):
    """Content-addressed independent review artifact."""

    artifact_hash: Sha256

    @model_validator(mode="after")
    def _verify_hash(self) -> AdaptivePromotionVerifierArtifact:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected:
            raise ValueError("promotion verifier artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptivePromotionVerifierArtifact:
        content = AdaptivePromotionVerifierArtifactContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, artifact_hash=canonical_sha256(payload))


class IndependentQwenPromotionVerifier(PromotionVerifier):
    """Replay sources and obtain a separate Qwen decision at the promotion boundary."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        raw_memory_store: RawMemoryStore,
        skill_root: Path | str,
        completion: CompletionCallable = run_llm_json_completion,
        config_path: Path | str = Path("config.yaml"),
        env_path: Path | str = Path(".env"),
        maximum_cpu_count: int = 16,
        maximum_memory_mb: int = 65_536,
        maximum_walltime_seconds: int = 7_200,
        thinking_budget: int = 2_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if min(
            maximum_cpu_count,
            maximum_memory_mb,
            maximum_walltime_seconds,
        ) < 1:
            raise AdaptivePromotionVerificationError(
                "promotion verifier resource limits must be positive"
            )
        self._output_root = Path(output_dir).resolve()
        self._raw_memory_store = raw_memory_store
        self._skill_root = Path(skill_root)
        self._completion = completion
        self._config_path = Path(config_path)
        self._env_path = Path(env_path)
        self._maximum_cpu_count = maximum_cpu_count
        self._maximum_memory_mb = maximum_memory_mb
        self._maximum_walltime_seconds = maximum_walltime_seconds
        self._thinking_budget = thinking_budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def verify(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        assessment: PromotionGateAssessment,
    ) -> FormalPromotionVerification:
        replayed = assess_branch_promotion(snapshot=snapshot, proposal=proposal)
        replay_matches = replayed == assessment and assessment.passed
        papers = _load_selected_papers(
            output_root=self._output_root,
            raw_memory_store=self._raw_memory_store,
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
        )
        skills = load_repository_skill_contexts(
            self._skill_root,
            proposal.selected_skill_ids,
        )
        messages = _review_messages(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
            assessment=assessment,
            papers=papers,
            skills=skills,
        )
        if sum(len(item["content"]) for item in messages) > _MAX_PROMPT_CHARACTERS:
            raise AdaptivePromotionVerificationError(
                "promotion review context exceeds its exact-input budget"
            )
        result = self._completion(
            messages=messages,
            config_path=self._config_path,
            env_path=self._env_path,
            timeout_seconds=300,
            max_tokens=8_000,
            temperature=0.1,
            thinking_mode="enabled",
            thinking_budget=self._thinking_budget,
            response_schema=AdaptivePromotionReviewDraft.model_json_schema(),
            response_schema_name="adaptive_promotion_review",
        )
        if "qwen" not in f"{result.provider} {result.model_name}".casefold():
            raise AdaptivePromotionVerificationError(
                "independent promotion reviewer is not the configured Qwen model"
            )
        created_at = self._clock().astimezone(timezone.utc)
        response_capture = self._capture(
            seed=seed,
            step_index=snapshot.next_step_index,
            suffix="response",
            label="自适应科研独立晋级评审可见响应",
            text=result.response_text,
            created_at=created_at,
        )
        reasoning = str(result.reasoning_text or "").strip()
        reasoning_capture = self._capture(
            seed=seed,
            step_index=snapshot.next_step_index,
            suffix="reasoning",
            label="自适应科研独立晋级评审有界思考",
            text=reasoning or "独立晋级评审未返回可用思考过程。",
            created_at=created_at,
        )
        if len(reasoning) < _MIN_REASONING_CHARACTERS:
            raise AdaptivePromotionVerificationError(
                "independent Qwen reviewer returned insufficient reasoning_content"
            )
        review = AdaptivePromotionReviewDraft.model_validate(result.parsed_json)
        try:
            visible_payload = json.loads(result.response_text)
        except json.JSONDecodeError as exc:
            raise AdaptivePromotionVerificationError(
                "independent promotion response is not exact JSON"
            ) from exc
        if visible_payload != review.model_dump(mode="json"):
            raise AdaptivePromotionVerificationError(
                "visible promotion response differs from the parsed review"
            )
        expected_refs = [paper.source_ref for paper in papers]
        actual_refs = [item.source_ref for item in review.prior_work_comparisons]
        if actual_refs != expected_refs:
            raise AdaptivePromotionVerificationError(
                "independent reviewer did not compare every selected source in order"
            )

        draft = proposal.promotion_draft
        if draft is None:
            raise AdaptivePromotionVerificationError("promotion draft disappeared")
        abstract_gaps = [
            paper.source_ref
            for paper, comparison in zip(
                papers,
                review.prior_work_comparisons,
                strict=True,
            )
            if not paper.abstract and not comparison.insufficient_abstract
        ]
        resources_bounded = (
            draft.requested_cpu_count <= self._maximum_cpu_count
            and draft.requested_memory_mb <= self._maximum_memory_mb
            and draft.requested_walltime_seconds <= self._maximum_walltime_seconds
        )
        scientific_core_clear = (
            review.question_hypothesis_mechanism_coherent
            and review.decisive_test_targets_falsifier
        )
        prior_work_clear = not abstract_gaps and all(
            not item.direct_method_copy and not item.insufficient_abstract
            for item in review.prior_work_comparisons
        )
        findings = list(review.findings_cn)
        if not replay_matches:
            findings.append("机械晋级门重放结果与传入评估不一致。")
        if abstract_gaps:
            findings.append("至少一项先前工作缺少摘要且评审未如实标记证据不足。")
        if not resources_bounded:
            findings.append("请求资源超出本次独立晋级评审的本地上限。")
        findings = list(dict.fromkeys(findings))
        verification = FormalPromotionVerification.create(
            branch_id=proposal.branch_id,
            promotion_assessment_hash=assessment.assessment_hash,
            verifier_id=f"qwen-independent-{snapshot.next_step_index:04d}",
            exact_sources_rechecked=(len(papers) >= 2 and not abstract_gaps),
            objective_checks_replayed=(replay_matches and scientific_core_clear),
            falsifier_is_operational=review.falsifier_is_operational,
            control_is_discriminating=review.control_is_discriminating,
            resource_scope_feasible=(
                review.resource_scope_feasible and resources_bounded
            ),
            no_direct_prior_work_copy=prior_work_clear,
            findings_cn=findings,
            passed=(
                replay_matches
                and scientific_core_clear
                and review.falsifier_is_operational
                and review.control_is_discriminating
                and review.resource_scope_feasible
                and resources_bounded
                and prior_work_clear
                and not findings
            ),
        )
        relative_path = (
            Path("verification")
            / f"step-{snapshot.next_step_index:04d}"
            / "adaptive-promotion-verification.json"
        )
        artifact = AdaptivePromotionVerifierArtifact.create(
            loop_id=seed.loop_id,
            project_id=seed.project_id,
            step_index=snapshot.next_step_index,
            branch_id=proposal.branch_id,
            snapshot_hash=snapshot.snapshot_hash,
            proposal_hash=canonical_sha256(proposal),
            promotion_assessment_hash=assessment.assessment_hash,
            selected_papers=papers,
            messages=messages,
            messages_sha256=canonical_sha256(messages),
            provider=result.provider,
            model_name=result.model_name,
            response_binding=response_capture,
            reasoning_binding=reasoning_capture,
            reasoning_character_count=len(reasoning),
            review=review,
            verification=verification,
            output_relative_path=relative_path.as_posix(),
            created_at=created_at,
        )
        _write_once(
            self._output_root / relative_path,
            (canonical_json(artifact) + "\n").encode("utf-8"),
        )
        return verification

    def _capture(
        self,
        *,
        seed: AdaptiveResearchSeed,
        step_index: int,
        suffix: str,
        label: str,
        text: str,
        created_at: datetime,
    ) -> RawMemoryBinding:
        capture = self._raw_memory_store.capture_text(
            text,
            project_id=seed.project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label=label,
            source_ref=(
                f"adaptive-loop:{seed.loop_id}:promotion-verifier:"
                f"{step_index}:{suffix}"
            ),
            original_name=(
                f"promotion-verifier-step-{step_index:04d}-{suffix}.txt"
            ),
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=created_at,
        )
        return capture.binding(self._raw_memory_store.vault_root)


def _load_selected_papers(
    *,
    output_root: Path,
    raw_memory_store: RawMemoryStore,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
) -> list[AdaptiveRetrievedPaper]:
    paper_by_ref: dict[str, AdaptiveRetrievedPaper] = {}
    for event in snapshot.events:
        if event.branch_id != proposal.branch_id:
            continue
        if event.feedback.origin is not FeedbackOrigin.EXTERNAL_RETRIEVAL:
            continue
        path = (
            output_root
            / "capabilities"
            / f"step-{event.step_index:04d}"
            / "retrieval"
            / "adaptive-literature-retrieval.json"
        )
        try:
            raw = path.read_bytes()
            artifact = AdaptiveLiteratureRetrievalArtifact.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptivePromotionVerificationError(
                f"cannot replay retained literature artifact: {type(exc).__name__}"
            ) from exc
        if raw != (canonical_json(artifact) + "\n").encode("utf-8"):
            raise AdaptivePromotionVerificationError(
                "retained literature artifact is not canonical"
            )
        if (
            artifact.loop_id != seed.loop_id
            or artifact.project_id != seed.project_id
            or artifact.step_index != event.step_index
            or artifact.branch_id != proposal.branch_id
            or f"artifact:{artifact.artifact_hash}"
            not in event.feedback.artifact_refs
        ):
            raise AdaptivePromotionVerificationError(
                "retained literature artifact lineage mismatch"
            )
        if event.feedback.source_refs != [paper.source_ref for paper in artifact.papers]:
            raise AdaptivePromotionVerificationError(
                "retained literature feedback differs from its paper catalogue"
            )
        capture = raw_memory_store.load_record(
            artifact.normalized_catalog_binding.record_relative_path,
            project_id=seed.project_id,
        )
        if capture.binding(raw_memory_store.vault_root) != (
            artifact.normalized_catalog_binding
        ):
            raise AdaptivePromotionVerificationError(
                "retained literature raw-memory binding mismatch"
            )
        for paper in artifact.papers:
            previous = paper_by_ref.get(paper.source_ref)
            if previous is not None and previous != paper:
                raise AdaptivePromotionVerificationError(
                    "one literature source reference resolves to different records"
                )
            paper_by_ref[paper.source_ref] = paper

    draft = proposal.promotion_draft
    if draft is None:
        raise AdaptivePromotionVerificationError("promotion draft is required")
    requested_refs = list(
        dict.fromkeys([*proposal.source_refs, *draft.source_refs])
    )
    try:
        return [paper_by_ref[source_ref] for source_ref in requested_refs]
    except KeyError as exc:
        raise AdaptivePromotionVerificationError(
            "promotion cites a source absent from retained retrieval artifacts"
        ) from exc


def _review_messages(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
    assessment: PromotionGateAssessment,
    papers: Sequence[AdaptiveRetrievedPaper],
    skills: Sequence[Any],
) -> list[dict[str, str]]:
    system = (
        "你是与动作作者分离的Qwen晋级评审。只判断候选是否值得离开开放探索、"
        "进入人工范围审批；不得声称已经创新、已经形成科学证据、可执行或可发表。"
        "逐篇比较所有可见摘要；摘要缺失或不足时必须标记insufficient_abstract。"
        "反例、判别性对照、资源和假设—机制衔接任一不成立就给出中文finding。"
        "学科方法技能只作为审查方法，不是事实来源。输出必须严格符合JSON Schema。"
    )
    context = {
        "artifact_kind": "adaptive_promotion_review_input_v1",
        "研究目标": seed.objective_cn,
        "研究范围": seed.scope_cn,
        "当前状态哈希": snapshot.snapshot_hash,
        "当前分支": next(
            branch.model_dump(mode="json")
            for branch in snapshot.branches
            if branch.branch_id == proposal.branch_id
        ),
        "模型自主晋级动作": proposal.model_dump(mode="json"),
        "机械晋级评估": assessment.model_dump(mode="json"),
        "逐字保留的检索记录": [paper.model_dump(mode="json") for paper in papers],
        "严格边界": {
            "当前只看元数据与摘要": True,
            "全文创新性已验证": False,
            "实验已执行": False,
            "允许批准或发表": False,
        },
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": canonical_json(context)},
    ]
    messages.extend(
        {
            "role": "user",
            "content": canonical_json(
                {
                    "artifact_kind": "selected_project_method_skill",
                    "skill_id": skill.skill_id,
                    "source_ref": skill.source_ref,
                    "content_sha256": skill.content_sha256,
                    "read_only": True,
                    "is_scientific_evidence": False,
                    "content": skill.content,
                }
            ),
        }
        for skill in skills
    )
    return messages


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptivePromotionVerificationError(
                f"immutable promotion verification changed: {path}"
            ) from None


__all__ = [
    "AdaptivePriorWorkComparison",
    "AdaptivePromotionReviewDraft",
    "AdaptivePromotionVerificationError",
    "AdaptivePromotionVerifierArtifact",
    "IndependentQwenPromotionVerifier",
]
