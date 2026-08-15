"""Persistent competition plan-loop adapter over the existing official lineage.

The adapter owns no scientific prompt, hypothesis, plan prose, or experiment.  It
selects one existing official plan entrypoint from verified on-disk checkpoints,
records a durable claim through :mod:`continual_research_harness`, and registers the
already-authored plan, preliminary experiment, critical review, and model receipts
as exact raw memory only after their existing validators pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    load_bound_authorship_receipt,
    plan_authored_fields,
)
from autoresearch.competition.official_development_search import OfficialCellResult
from autoresearch.competition.official_lineage import (
    LineageStageReport,
    OfficialLineageConfig,
    _load_formal_system_plan_artifact,
    exclusive_lineage_lock,
    resume_plan_from_retained_routing,
    run_plan_stage,
)
from autoresearch.competition.system_plan_preexperiment import (
    PreexperimentRawResultEvidence,
    SystemPlanPreexperimentArtifact,
)
from autoresearch.competition.system_plan_review import SystemPlanCriticalReview
from autoresearch.kernel.contracts import KernelContract
from autoresearch.knowledge.raw_memory import RawMemorySourceKind
from autoresearch.runtime.continual_research_harness import (
    ArtifactCompletionEnvelope,
    ContinualResearchHarness,
    LocalRefinementProposal,
    ResearchFailureKind,
    ResearchTaskClaim,
    ResearchTaskStatus,
    VerifiedArtifactBinding,
    VerifiedModelReceiptProjection,
)
from autoresearch.schemas import file_hash

_RETAINED_ROUTING_FILES = (
    "plan-literature-survey.json",
    "system-plan-method-skill-selection.json",
    "system-plan-component-atoms.json",
    "system-plan-prospective-atoms.json",
    "system-plan-opportunity-routing.json",
)
_POST_ROUTING_FILES = (
    "system-plan-opportunity-distributed.json",
    "system-plan-ideation.json",
    "system-plan-preexperiment.json",
    "system-plan-critical-review.json",
    "system-authored-research-plan.json",
)
_RESUME_MANIFEST_NAME = "plan-stage-resume-manifest.json"
_MAX_FORMAT_CONTINUATIONS = 3


class CompetitionPlanLoopError(RuntimeError):
    """Base error for the competition plan-loop adapter."""


class CompetitionPlanLoopFormatError(CompetitionPlanLoopError):
    """Explicit machine-format failure eligible for bounded continuation."""


class CompetitionPlanLoopOperationalError(CompetitionPlanLoopError):
    """Operational or indeterminate failure that is never scientific."""


class PlanLoopCheckpoint(str, Enum):
    """Safe existing entrypoints inferred without mutating official state."""

    FRESH = "fresh"
    RETAINED_ROUTING = "retained_routing"
    COMPLETE = "complete"
    PARTIAL = "partial"


class CompetitionPlanLoopStatus(str, Enum):
    """Terminal status returned by one CLI invocation."""

    COMPLETED = "completed"
    FORMAT_EXHAUSTED = "format_exhausted"
    SCIENTIFIC_PENDING_SHADOW = "scientific_pending_shadow"
    OPERATIONAL_WAIT = "operational_wait"
    IDLE = "idle"


@dataclass(frozen=True)
class CompetitionPlanLoopConfig:
    """Paths and immutable official configuration for one plan-loop task."""

    lineage: OfficialLineageConfig
    state_dir: Path
    vault_root: Path
    config_path: Path = Path("config.yaml")
    env_path: Path = Path(".env")
    worker_id: str = "competition-plan-main-agent"
    max_format_continuations: int = _MAX_FORMAT_CONTINUATIONS


class CompetitionPlanLoopReport(KernelContract):
    """Structured result so the CLI never infers state from human-readable stdout."""

    lineage_id: str
    status: CompetitionPlanLoopStatus
    checkpoint: PlanLoopCheckpoint
    task_status: ResearchTaskStatus
    format_failure_count: int
    claim_count: int
    completed_memory_task_hash: str | None = None
    artifact_envelope_hash: str | None = None
    proposal: LocalRefinementProposal | None = None
    message_cn: str


PlanRunner = Callable[..., LineageStageReport]
ResumeRunner = Callable[..., LineageStageReport]
CompletionLoader = Callable[
    [
        CompetitionPlanLoopConfig,
        ContinualResearchHarness,
        LineageStageReport,
        Path | None,
        datetime,
    ],
    ArtifactCompletionEnvelope,
]


def inspect_plan_loop_checkpoint(work_dir: Path | str) -> PlanLoopCheckpoint:
    """Select only a provably non-overwriting official plan entrypoint."""

    root = Path(work_dir)
    official_plan = root / "plan" / "research-plan.json"
    authored_plan = root / "system-authored-research-plan.json"
    if official_plan.is_file() and authored_plan.is_file():
        return PlanLoopCheckpoint.COMPLETE
    if official_plan.exists() or authored_plan.exists():
        return PlanLoopCheckpoint.PARTIAL

    retained = tuple((root / name).is_file() for name in _RETAINED_ROUTING_FILES)
    if all(retained):
        return PlanLoopCheckpoint.RETAINED_ROUTING
    if any(retained):
        return PlanLoopCheckpoint.PARTIAL

    post_routing_exists = any((root / name).exists() for name in _POST_ROUTING_FILES)
    post_routing_exists = post_routing_exists or any(root.glob("plan-resume-*"))
    return PlanLoopCheckpoint.PARTIAL if post_routing_exists else PlanLoopCheckpoint.FRESH


def run_competition_plan_loop(
    config: CompetitionPlanLoopConfig,
    *,
    plan_runner: PlanRunner = run_plan_stage,
    resume_runner: ResumeRunner = resume_plan_from_retained_routing,
    completion_loader: CompletionLoader | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> CompetitionPlanLoopReport:
    """Claim and drive the existing official plan stage until a safe stop."""

    if config.max_format_continuations != _MAX_FORMAT_CONTINUATIONS:
        raise ValueError("competition plan loop requires exactly three format continuations")
    harness = _build_harness(config)
    _ensure_plan_task(harness, config=config, now=clock())
    load_completion = completion_loader or _load_verified_plan_completion

    while True:
        now = _normalize_datetime(clock())
        checkpoint = inspect_plan_loop_checkpoint(config.lineage.work_dir)
        claim = harness.claim_next(worker_id=config.worker_id, claimed_at=now)
        if claim is None:
            return _report_without_claim(harness, config=config, checkpoint=checkpoint)

        resume_root: Path | None = None
        before_reviews = _review_receipt_fingerprints(
            config.lineage.work_dir,
            additional_root=None,
        )
        try:
            stage_report, resume_root = _invoke_existing_plan_entrypoint(
                config,
                claim=claim,
                checkpoint=checkpoint,
                plan_runner=plan_runner,
                resume_runner=resume_runner,
            )
            envelope = load_completion(
                config,
                harness,
                stage_report,
                resume_root,
                now,
            )
        except Exception as exc:  # noqa: BLE001 - typed classification boundary.
            new_rejected = _new_verified_rejected_review(
                config,
                before=before_reviews,
                additional_root=resume_root,
            )
            if new_rejected is not None:
                failure = harness.fail_task(
                    claim=claim,
                    kind=ResearchFailureKind.SCIENTIFIC,
                    message_cn=_scientific_failure_message(new_rejected),
                    failed_at=now,
                )
                record = harness.get_task(claim.task.task_id)
                return CompetitionPlanLoopReport(
                    lineage_id=config.lineage.lineage_id,
                    status=CompetitionPlanLoopStatus.SCIENTIFIC_PENDING_SHADOW,
                    checkpoint=checkpoint,
                    task_status=record.status,
                    format_failure_count=record.format_failure_count,
                    claim_count=record.claim_count,
                    proposal=record.refinement_proposal,
                    message_cn=failure.message_cn,
                )
            if _is_explicit_format_failure(exc):
                failure = harness.fail_task(
                    claim=claim,
                    kind=ResearchFailureKind.FORMAT,
                    message_cn=_safe_exception_message("计划格式失败", exc),
                    failed_at=now,
                )
                record = harness.get_task(claim.task.task_id)
                if record.format_failure_count < config.max_format_continuations:
                    continue
                return CompetitionPlanLoopReport(
                    lineage_id=config.lineage.lineage_id,
                    status=CompetitionPlanLoopStatus.FORMAT_EXHAUSTED,
                    checkpoint=checkpoint,
                    task_status=record.status,
                    format_failure_count=record.format_failure_count,
                    claim_count=record.claim_count,
                    message_cn=failure.message_cn,
                )
            failure = harness.fail_task(
                claim=claim,
                kind=ResearchFailureKind.OPERATIONAL,
                message_cn=_safe_exception_message("计划运行处于操作性等待", exc),
                failed_at=now,
                # A later command may retry; this invocation always stops here.
                retry_after=now,
            )
            record = harness.get_task(claim.task.task_id)
            return CompetitionPlanLoopReport(
                lineage_id=config.lineage.lineage_id,
                status=CompetitionPlanLoopStatus.OPERATIONAL_WAIT,
                checkpoint=checkpoint,
                task_status=record.status,
                format_failure_count=record.format_failure_count,
                claim_count=record.claim_count,
                message_cn=failure.message_cn,
            )

        completed = harness.complete_artifact_task(
            claim=claim,
            completion=envelope,
            completed_at=now,
        )
        record = harness.get_task(claim.task.task_id)
        return CompetitionPlanLoopReport(
            lineage_id=config.lineage.lineage_id,
            status=CompetitionPlanLoopStatus.COMPLETED,
            checkpoint=checkpoint,
            task_status=record.status,
            format_failure_count=record.format_failure_count,
            claim_count=record.claim_count,
            completed_memory_task_hash=completed.task_hash,
            artifact_envelope_hash=envelope.envelope_hash,
            message_cn="系统计划、真实预实验、独立评审和模型作者回执已验证并登记。",
        )


def _build_harness(config: CompetitionPlanLoopConfig) -> ContinualResearchHarness:
    state_root = config.state_dir.resolve()
    return ContinualResearchHarness(
        journal_path=state_root / "continual-plan-loop.jsonl",
        heartbeat_path=state_root / "continual-plan-heartbeats.json",
        vault_root=config.vault_root,
        project_id=config.lineage.lineage_id,
        conversation_id=f"{config.lineage.lineage_id}-competition-plan-loop",
        max_format_repair_attempts=config.max_format_continuations,
    )


def _ensure_plan_task(
    harness: ContinualResearchHarness,
    *,
    config: CompetitionPlanLoopConfig,
    now: datetime,
) -> None:
    goal_id = f"{config.lineage.lineage_id}-plan-goal"
    harness.ensure_goal(
        goal_id=goal_id,
        objective_cn=(
            "由系统自主完成中文研究计划、真实预实验和独立科学审查；"
            "计划通过后仍等待人类范围批准，不自动执行正式实验或发布。"
        ),
        created_at=now,
    )
    harness.enqueue_task(
        goal_id=goal_id,
        task_id=f"{config.lineage.lineage_id}-plan-stage",
        task_text_cn=("调用既有正式计划链或其保留路由续跑入口，形成并验证系统自产中文研究计划。"),
        request_messages=(
            {
                "role": "system",
                "content": (
                    "你是正式计划持续协调任务；不得替配置模型撰写科研内容，"
                    "只调用既有计划链并保留其真实回执。"
                ),
            },
            {
                "role": "user",
                "content": f"持续完成科研谱系 {config.lineage.lineage_id} 的计划阶段。",
            },
        ),
        enqueued_at=now,
    )


def _invoke_existing_plan_entrypoint(
    config: CompetitionPlanLoopConfig,
    *,
    claim: ResearchTaskClaim,
    checkpoint: PlanLoopCheckpoint,
    plan_runner: PlanRunner,
    resume_runner: ResumeRunner,
) -> tuple[LineageStageReport, Path | None]:
    lineage = config.lineage
    if checkpoint is PlanLoopCheckpoint.COMPLETE:
        return (
            LineageStageReport(
                lineage_id=lineage.lineage_id,
                stage="plan",
                lines=("已发现完整计划；仅执行严格复核和记忆补登记。",),
            ),
            _find_single_resume_root(lineage.work_dir),
        )
    if checkpoint is PlanLoopCheckpoint.PARTIAL:
        raise CompetitionPlanLoopOperationalError(
            "计划 checkpoint 不完整，既不能安全重放 fresh stage，也不能安全续跑"
        )
    if checkpoint is PlanLoopCheckpoint.RETAINED_ROUTING:
        resume_root = lineage.work_dir / f"plan-resume-loop-attempt-{claim.attempt:02d}"
        report = resume_runner(
            lineage,
            output_dir=resume_root,
            config_path=config.config_path,
            env_path=config.env_path,
        )
        return report, resume_root
    if not lineage.work_dir.is_dir():
        raise CompetitionPlanLoopOperationalError(
            "fresh plan stage requires an already initialized official lineage directory"
        )
    with exclusive_lineage_lock(lineage.work_dir, stage="continual-plan-loop"):
        report = plan_runner(
            lineage,
            config_path=config.config_path,
            env_path=config.env_path,
        )
    return report, None


def _load_verified_plan_completion(
    config: CompetitionPlanLoopConfig,
    harness: ContinualResearchHarness,
    report: LineageStageReport,
    resume_root: Path | None,
    completed_at: datetime,
) -> ArtifactCompletionEnvelope:
    """Verify and capture the exact official plan completion artifacts."""

    if report.stage != "plan" or report.lineage_id != config.lineage.lineage_id:
        raise CompetitionPlanLoopOperationalError(
            "existing plan entrypoint returned a mismatched stage report"
        )
    lineage = config.lineage
    artifact, plan, _decision = _load_formal_system_plan_artifact(
        lineage,
        config_path=config.config_path,
        require_decision=False,
    )
    final_receipt = load_bound_authorship_receipt(
        lineage_dir=lineage.work_dir,
        relative_path=artifact.authorship_receipt_relative_path,
        expected_hash=artifact.authorship_receipt_hash,
        artifact_kind="research_plan",
        expected_model_name=artifact.model_name,
        expected_fields=plan_authored_fields(artifact.plan),
    )
    official_plan_path = lineage.plan_dir / "research-plan.json"
    authored_plan_path = lineage.work_dir / "system-authored-research-plan.json"

    manifest_path = _resolve_resume_manifest(lineage.work_dir, resume_root=resume_root)
    if manifest_path is not None:
        manifest = _load_verified_resume_manifest(
            manifest_path,
            lineage_id=lineage.lineage_id,
            official_plan_path=official_plan_path,
            authored_plan_path=authored_plan_path,
        )
        preexperiment_path = _manifest_path_inside_lineage(
            manifest,
            "preexperiment_artifact_path",
            lineage.work_dir,
        )
        critical_review_path = _manifest_path_inside_lineage(
            manifest,
            "critical_review_path",
            lineage.work_dir,
        )
    else:
        preexperiment_path = lineage.work_dir / "system-plan-preexperiment.json"
        critical_review_path = lineage.work_dir / "system-plan-critical-review.json"

    preexperiment = SystemPlanPreexperimentArtifact.model_validate_json(
        preexperiment_path.read_text(encoding="utf-8")
    )
    critical_review = SystemPlanCriticalReview.model_validate_json(
        critical_review_path.read_text(encoding="utf-8")
    )
    _verify_preexperiment(
        preexperiment,
        path=preexperiment_path,
        lineage_id=lineage.lineage_id,
    )
    _verify_critical_review(
        critical_review,
        path=critical_review_path,
        lineage_id=lineage.lineage_id,
        plan_hash=artifact.plan_hash,
    )
    preexperiment_receipt = load_bound_authorship_receipt(
        lineage_dir=preexperiment_path.parent,
        relative_path=preexperiment.interpretation_receipt_relative_path,
        expected_hash=preexperiment.interpretation_receipt_hash,
        artifact_kind="plan_preexperiment_interpretation",
        expected_model_name=preexperiment.model_name,
        expected_fields=preexperiment.interpretation.model_dump(mode="json"),
    )
    critical_receipt = load_bound_authorship_receipt(
        lineage_dir=critical_review_path.parent,
        relative_path=critical_review.authorship_receipt_relative_path,
        expected_hash=critical_review.authorship_receipt_hash,
        artifact_kind="plan_critical_review",
        expected_model_name=critical_review.model_name,
        expected_fields=critical_review.assessment.model_dump(mode="json"),
    )

    paths: list[tuple[str, Path, RawMemorySourceKind]] = [
        ("official_research_plan", official_plan_path, RawMemorySourceKind.LOCAL_FILE),
        ("system_authored_plan", authored_plan_path, RawMemorySourceKind.LOCAL_FILE),
        (
            "plan_authorship_receipt",
            Path(final_receipt.output_path),
            RawMemorySourceKind.MODEL_TRANSCRIPT,
        ),
        ("preexperiment", preexperiment_path, RawMemorySourceKind.TOOL_OUTPUT),
        (
            "preexperiment_interpretation_receipt",
            Path(preexperiment_receipt.output_path),
            RawMemorySourceKind.MODEL_TRANSCRIPT,
        ),
        ("critical_review", critical_review_path, RawMemorySourceKind.LOCAL_FILE),
        (
            "critical_review_receipt",
            Path(critical_receipt.output_path),
            RawMemorySourceKind.MODEL_TRANSCRIPT,
        ),
    ]
    if manifest_path is not None:
        paths.append(("plan_resume_manifest", manifest_path, RawMemorySourceKind.LOCAL_FILE))
    preexperiment_root = preexperiment_path.parent
    for index, evidence in enumerate(preexperiment.cell_evidence, start=1):
        raw_path = _verified_raw_cell_path(preexperiment_root, evidence)
        paths.append(
            (
                f"preexperiment_raw_cell_{index:02d}",
                raw_path,
                RawMemorySourceKind.TOOL_OUTPUT,
            )
        )

    bindings = tuple(
        _capture_artifact(
            harness,
            lineage_root=lineage.work_dir,
            artifact_kind=kind,
            path=path,
            source_kind=source_kind,
            captured_at=completed_at,
        )
        for kind, path, source_kind in paths
    )
    final_binding = next(
        item for item in bindings if item.artifact_kind == "plan_authorship_receipt"
    ).model_copy(update={"artifact_kind": "model_authorship_receipt"})
    # Replace the generic label in the artifact set as well; the source bytes and
    # raw binding remain identical and content addressed.
    bindings = tuple(
        final_binding if item.artifact_kind == "plan_authorship_receipt" else item
        for item in bindings
    )
    projection = _receipt_projection(final_receipt, binding=final_binding)
    return ArtifactCompletionEnvelope.create(
        final_model_receipt=projection,
        artifacts=bindings,
        stage_report=report.model_dump(mode="json"),
        completed_at=completed_at,
    )


def _verify_preexperiment(
    artifact: SystemPlanPreexperimentArtifact,
    *,
    path: Path,
    lineage_id: str,
) -> None:
    if (
        artifact.lineage_id != lineage_id
        or Path(artifact.output_path).resolve() != path.resolve()
        or not artifact.cell_evidence
        or not artifact.preliminary_only
        or artifact.treatment_effect_measured
        or artifact.full_experiment_completed
        or artifact.scientific_hypothesis_validated
        or artifact.publication_ready
    ):
        raise CompetitionPlanLoopOperationalError(
            "preexperiment artifact is not the exact bounded real preliminary run"
        )
    for evidence in artifact.cell_evidence:
        _verified_raw_cell_path(path.parent, evidence)


def _verified_raw_cell_path(
    root: Path,
    evidence: PreexperimentRawResultEvidence,
) -> Path:
    path = (root / evidence.raw_result_relative_path).resolve()
    _require_inside(path, root, label="preexperiment raw cell")
    if not path.is_file() or file_hash(path) != evidence.raw_result_file_sha256:
        raise CompetitionPlanLoopOperationalError(
            "preexperiment raw cell bytes are missing or hash-mismatched"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = OfficialCellResult.model_validate(payload)
    if result != evidence.result:
        raise CompetitionPlanLoopOperationalError(
            "preexperiment raw cell differs from its bound artifact result"
        )
    return path


def _verify_critical_review(
    review: SystemPlanCriticalReview,
    *,
    path: Path,
    lineage_id: str,
    plan_hash: str,
) -> None:
    if (
        review.lineage_id != lineage_id
        or review.plan_hash != plan_hash
        or Path(review.output_path).resolve() != path.resolve()
        or not review.assessment.ready_for_human_scope_review
    ):
        raise CompetitionPlanLoopOperationalError(
            "critical review is not the accepted review bound to the final plan"
        )


def _capture_artifact(
    harness: ContinualResearchHarness,
    *,
    lineage_root: Path,
    artifact_kind: str,
    path: Path,
    source_kind: RawMemorySourceKind,
    captured_at: datetime,
) -> VerifiedArtifactBinding:
    resolved = path.resolve()
    relative = _require_inside(resolved, lineage_root, label=artifact_kind).as_posix()
    capture = harness.raw_memory_store.capture_file(
        resolved,
        project_id=harness.project_id,
        source_kind=source_kind,
        source_label=f"已验证计划制品 {artifact_kind}",
        source_ref=f"lineage:{harness.project_id}:{relative}",
        media_type="application/json",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=captured_at,
    )
    return VerifiedArtifactBinding(
        artifact_kind=artifact_kind,
        source_relative_path=relative,
        source_sha256=file_hash(resolved),
        raw_binding=capture.binding(harness.raw_memory_store.vault_root),
    )


def _receipt_projection(
    receipt: ModelAuthorshipReceipt,
    *,
    binding: VerifiedArtifactBinding,
) -> VerifiedModelReceiptProjection:
    return VerifiedModelReceiptProjection(
        receipt_hash=receipt.receipt_hash,
        receipt_artifact=binding,
        messages=receipt.messages,
        messages_sha256=receipt.messages_sha256,
        provider=receipt.provider,
        base_url=receipt.base_url,
        model_name=receipt.model_name,
        endpoint=receipt.endpoint,
        response_text=receipt.response_text,
        response_sha256=receipt.response_sha256,
        parsed_payload=receipt.parsed_payload,
        parsed_payload_sha256=receipt.parsed_payload_sha256,
        usage=receipt.usage,
        reasoning_content=receipt.reasoning_content,
        reasoning_transport=receipt.reasoning_transport,
    )


def _resolve_resume_manifest(work_dir: Path, *, resume_root: Path | None) -> Path | None:
    if resume_root is not None:
        candidate = resume_root / _RESUME_MANIFEST_NAME
        return candidate if candidate.is_file() else None
    candidates = tuple(
        path for path in work_dir.glob(f"plan-resume-*/{_RESUME_MANIFEST_NAME}") if path.is_file()
    )
    if len(candidates) > 1:
        raise CompetitionPlanLoopOperationalError(
            "multiple completed plan resume manifests make completion provenance ambiguous"
        )
    return candidates[0] if candidates else None


def _find_single_resume_root(work_dir: Path) -> Path | None:
    manifest = _resolve_resume_manifest(work_dir, resume_root=None)
    return manifest.parent if manifest is not None else None


def _load_verified_resume_manifest(
    path: Path,
    *,
    lineage_id: str,
    official_plan_path: Path,
    authored_plan_path: Path,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CompetitionPlanLoopOperationalError("plan resume manifest must be an object")
    stored_hash = payload.get("manifest_hash")
    unhashed = {key: value for key, value in payload.items() if key != "manifest_hash"}
    if (
        stored_hash != canonical_model_hash(unhashed)
        or payload.get("lineage_id") != lineage_id
        or Path(str(payload.get("official_plan_path"))).resolve() != official_plan_path.resolve()
        or Path(str(payload.get("system_authored_plan_artifact_path"))).resolve()
        != authored_plan_path.resolve()
        or payload.get("authored_by_model") is not True
        or payload.get("hand_written_scientific_prose_count") != 0
        or payload.get("execution_authorized") is not False
    ):
        raise CompetitionPlanLoopOperationalError("plan resume manifest binding is invalid")
    return payload


def _manifest_path_inside_lineage(
    manifest: Mapping[str, Any],
    key: str,
    lineage_root: Path,
) -> Path:
    value = manifest.get(key)
    if not isinstance(value, str) or not value:
        raise CompetitionPlanLoopOperationalError(f"resume manifest lacks {key}")
    path = Path(value).resolve()
    _require_inside(path, lineage_root, label=key)
    return path


def _review_receipt_fingerprints(
    work_dir: Path,
    *,
    additional_root: Path | None,
) -> set[tuple[str, str]]:
    roots = [work_dir]
    if additional_root is not None:
        roots.append(additional_root)
    fingerprints: set[tuple[str, str]] = set()
    for root in roots:
        for path in root.glob("**/reviews/system-plan-critical-review-attempt-*.json"):
            try:
                review = SystemPlanCriticalReview.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            fingerprints.add((path.resolve().as_posix(), review.review_hash))
    return fingerprints


def _new_verified_rejected_review(
    config: CompetitionPlanLoopConfig,
    *,
    before: set[tuple[str, str]],
    additional_root: Path | None,
) -> SystemPlanCriticalReview | None:
    roots = [config.lineage.work_dir]
    if additional_root is not None:
        roots.append(additional_root)
    candidates: list[tuple[Path, SystemPlanCriticalReview]] = []
    for root in roots:
        for path in root.glob("**/reviews/system-plan-critical-review-attempt-*.json"):
            try:
                review = SystemPlanCriticalReview.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                fingerprint = (path.resolve().as_posix(), review.review_hash)
                if fingerprint in before or review.assessment.ready_for_human_scope_review:
                    continue
                load_bound_authorship_receipt(
                    lineage_dir=path.parent.parent,
                    relative_path=review.authorship_receipt_relative_path,
                    expected_hash=review.authorship_receipt_hash,
                    artifact_kind="plan_critical_review",
                    expected_model_name=review.model_name,
                    expected_fields=review.assessment.model_dump(mode="json"),
                )
            except (OSError, RuntimeError, ValueError):
                continue
            candidates.append((path, review))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1].authoring_attempt)[1]


def _scientific_failure_message(review: SystemPlanCriticalReview) -> str:
    findings = review.assessment.repair_findings()
    detail = "；".join(findings[:6]) if findings else review.assessment.overall_assessment
    return f"独立科学评审未批准当前计划：{detail}"


def _is_explicit_format_failure(exc: Exception) -> bool:
    return isinstance(
        exc,
        CompetitionPlanLoopFormatError | ValidationError | json.JSONDecodeError,
    )


def _safe_exception_message(prefix: str, exc: Exception) -> str:
    detail = " ".join(str(exc).split())[:2_000]
    return f"{prefix}：{type(exc).__name__}: {detail or '无可用诊断'}"


def _require_inside(path: Path, root: Path, *, label: str) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CompetitionPlanLoopOperationalError(f"{label} escapes the official lineage") from exc


def _report_without_claim(
    harness: ContinualResearchHarness,
    *,
    config: CompetitionPlanLoopConfig,
    checkpoint: PlanLoopCheckpoint,
) -> CompetitionPlanLoopReport:
    record = harness.list_tasks()[0]
    if record.status is ResearchTaskStatus.COMPLETED:
        status = CompetitionPlanLoopStatus.COMPLETED
        message = "计划任务已经完成，未重复调用官方计划链。"
    elif (
        record.status is ResearchTaskStatus.FORMAT_REPAIR
        and record.format_failure_count >= config.max_format_continuations
    ):
        status = CompetitionPlanLoopStatus.FORMAT_EXHAUSTED
        message = "计划格式续跑预算已耗尽，未伪造完成。"
    elif record.status is ResearchTaskStatus.SCIENTIFIC_FAILED:
        status = CompetitionPlanLoopStatus.SCIENTIFIC_PENDING_SHADOW
        message = "科学失败已进入 pending_shadow。"
    elif record.status is ResearchTaskStatus.OPERATIONAL_WAIT:
        status = CompetitionPlanLoopStatus.OPERATIONAL_WAIT
        message = "计划任务等待操作性条件恢复。"
    else:
        status = CompetitionPlanLoopStatus.IDLE
        message = "当前没有可认领的计划任务。"
    return CompetitionPlanLoopReport(
        lineage_id=config.lineage.lineage_id,
        status=status,
        checkpoint=checkpoint,
        task_status=record.status,
        format_failure_count=record.format_failure_count,
        claim_count=record.claim_count,
        completed_memory_task_hash=(
            record.completed_conversation.task_hash
            if record.completed_conversation is not None
            else None
        ),
        artifact_envelope_hash=(
            record.artifact_completion.envelope_hash
            if record.artifact_completion is not None
            else None
        ),
        proposal=record.refinement_proposal,
        message_cn=message,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("plan-loop clock must be timezone-aware")
    return value.astimezone(timezone.utc)
