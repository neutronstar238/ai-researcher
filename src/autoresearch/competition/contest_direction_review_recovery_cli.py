"""Generic one-shot recovery after a blocking independent plan review.

The blocked research-loop root is immutable evidence.  Recovery therefore writes
to a distinct root and has a fixed shape: verify the source bytes, perform exactly
one complete plan revision, render that revision, and request exactly one fresh
non-rewriting scientific review.  A second blocking verdict is terminal for this
recovery; there is no hidden best-of-N loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    _public_plan_projection,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
    revise_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_scientific_review import (
    ContestDirectPlanScientificReviewArtifact,
    load_contest_direct_plan_scientific_review,
    review_contest_direct_plan_science,
)
from autoresearch.competition.contest_direction_gap_repair_retrieval import (
    build_contest_direction_gap_repair_plan_from_projection,
    load_contest_direction_gap_repair,
)
from autoresearch.competition.contest_direction_layered_literature import (
    load_contest_direction_layered_literature,
)
from autoresearch.competition.contest_direction_merged_literature import (
    ContestDirectionMergedLiteratureArtifact,
)
from autoresearch.competition.contest_direction_research_loop_cli import (
    _load_rendered_plan,
    _read_json,
    _verify_rendered_pdf,
    _verify_revision_sidecars,
    _write_new_json,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    load_completed_stage,
    provider_checkpoint_accounting,
    provider_checkpoint_count,
    record_completed_stage,
    replayable_stage_completion,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    ContestPlanEmbeddedEvidenceBundle,
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    load_planning_literature_coverage_receipt,
)
from autoresearch.competition.contest_planning_literature_gap_repair import (
    load_planning_literature_gap_diagnosis,
    load_planning_literature_gap_repair_projection,
)
from autoresearch.competition.contest_planning_literature_gap_repair_runner import (
    load_planning_literature_gap_repair_response,
)
from autoresearch.competition.contest_reference_policy import validate_locked_bibliography
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_INPUT_SCHEMA = "contest-direction-review-recovery-input-v1"
_REPORT_SCHEMA = "contest-direction-review-recovery-report-v1"
_INPUT_NAME = "review-recovery-input.json"
_REPORT_NAME = "review-recovery-report.json"
_REVISION_STAGE = "review-driven-plan-revision"
_RENDER_STAGE = "render-review-driven-plan"
_REVIEW_STAGE = "fresh-independent-scientific-rereview"
_PROVIDER_STAGES = (_REVISION_STAGE, _REVIEW_STAGE)
_NONBLOCKING = {"pass": "completed", "minor_revision": "completed_with_minor_issues"}
_BLOCKING = frozenset({"major_revision", "reject", "unclear"})
_LEGACY_REFERENCE_STATUS = "legacy_unverified_against_review_prose"
_VERIFIED_REFERENCE_STATUS = "verified_exact_union"
_P = ParamSpec("_P")
_R = TypeVar("_R")


class ContestDirectionReviewRecoveryError(RuntimeError):
    """Raised when a blocked plan cannot be recovered without changing evidence."""


@dataclass(frozen=True)
class _BlockedReviewBundle:
    """Hash-verified inputs reused by the one-shot recovery."""

    root: Path
    direction: str
    focused_direction: str
    source_literature_protocol: str
    source_plan_path: Path
    source_plan: ContestDirectPlanRevisionArtifact | Any
    source_render_manifest_path: Path
    source_render_source_payload_sha256: str
    prior_review_path: Path
    prior_review: ContestDirectPlanScientificReviewArtifact | Any
    block_receipt_path: Path
    block_receipt_hash: str
    preexperiment_path: Path
    preexperiment_root: Path
    reference_catalog: tuple[str, ...]
    selected_skill_contexts: tuple[dict[str, str], ...]
    source_inventory: tuple[dict[str, Any], ...]


def run_contest_direction_review_recovery(
    *,
    source_blocked_dir: Path | str,
    output_dir: Path | str,
    resume_existing: bool = False,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    review_config_path: Path | str | None = None,
    review_env_path: Path | str | None = None,
    plan_max_tokens: int = 14_000,
    review_max_tokens: int = 8_000,
    timeout_seconds: int = 900,
    render_timeout_seconds: int = 180,
    source_loader: Callable[[Path], _BlockedReviewBundle] | None = None,
    revision_runner: Callable[..., ContestDirectPlanRevisionArtifact] = (
        revise_contest_direct_plan
    ),
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
    review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact] = (
        review_contest_direct_plan_science
    ),
    revision_completion: Callable[..., LLMJsonCompletionResult] = (run_llm_json_completion),
    review_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    embedded_evidence_builder: Callable[..., ContestPlanEmbeddedEvidenceBundle | None] = (
        build_contest_plan_embedded_evidence
    ),
    render_verifier: Callable[[ContestDirectPlanArtifacts], tuple[int, str]] = (
        _verify_rendered_pdf
    ),
) -> dict[str, Any]:
    """Apply one review-driven revision and one fresh review in a new root."""

    if min(plan_max_tokens, review_max_tokens, timeout_seconds, render_timeout_seconds) < 1:
        raise ContestDirectionReviewRecoveryError("budgets and timeouts must be positive")
    source_root = Path(source_blocked_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    _require_disjoint_roots(source_root, root)
    if source_loader is None:
        bundle = _load_blocked_review_bundle(source_root)
    else:
        bundle = source_loader(source_root)
    if bundle.root.resolve() != source_root:
        raise ContestDirectionReviewRecoveryError("source loader returned another root")
    _verify_inventory(bundle.root, bundle.source_inventory)
    revision_runner = _source_guarded_callback(bundle, revision_runner)
    plan_materializer = _source_guarded_callback(bundle, plan_materializer)
    review_runner = _source_guarded_callback(bundle, review_runner)
    revision_completion = _source_guarded_callback(bundle, revision_completion)
    review_completion = _source_guarded_callback(bundle, review_completion)
    embedded_evidence_builder = _source_guarded_callback(bundle, embedded_evidence_builder)
    render_verifier = _source_guarded_callback(bundle, render_verifier)

    reviewer_config = review_config_path if review_config_path is not None else config_path
    reviewer_env = review_env_path if review_env_path is not None else env_path
    feedback = _review_feedback_payload(bundle.prior_review)
    recovery_input = _recovery_input_payload(
        bundle=bundle,
        feedback=feedback,
        config_path=config_path,
        env_path=env_path,
        review_config_path=reviewer_config,
        review_env_path=reviewer_env,
        plan_max_tokens=plan_max_tokens,
        review_max_tokens=review_max_tokens,
        timeout_seconds=timeout_seconds,
        render_timeout_seconds=render_timeout_seconds,
    )
    input_hash = str(recovery_input["input_hash"])
    input_path = root / _INPUT_NAME
    report_path = root / _REPORT_NAME
    if resume_existing:
        if not root.is_dir() or not input_path.is_file():
            raise ContestDirectionReviewRecoveryError(
                "resume output does not contain a recovery input receipt"
            )
        if _read_json(input_path) != recovery_input:
            raise ContestDirectionReviewRecoveryError(
                "resume recovery input differs from the frozen source or call contract"
            )
    else:
        if root.exists() and any(root.iterdir()):
            raise ContestDirectionReviewRecoveryError(
                f"recovery output directory must be empty: {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        _write_new_json(input_path, recovery_input)

    physical_attempts_before = _provider_physical_attempts(root)

    if report_path.is_file():
        report = _load_completed_report(
            report_path,
            expected_input_hash=input_hash,
            root=root,
        )
        _verify_inventory(bundle.root, bundle.source_inventory)
        returned = dict(report)
        accounting = dict(returned["model_call_accounting"])
        accounting["current_invocation_provider_requests"] = 0
        if "current_invocation_provider_physical_attempts" in accounting:
            accounting["current_invocation_provider_physical_attempts"] = 0
        returned["model_call_accounting"] = accounting
        returned["resume_action"] = "already_complete_no_model_call"
        returned["report_path"] = report_path.as_posix()
        returned["report_sha256"] = _sha256_file(report_path)
        return returned

    revision_stage_hash = canonical_model_hash(
        {
            "recovery_input_hash": input_hash,
            "source_plan_artifact_hash": bundle.source_plan.artifact_hash,
            "source_review_artifact_hash": bundle.prior_review.artifact_hash,
            "review_feedback_hash": feedback["feedback_hash"],
        }
    )
    revision_checkpoint_before = provider_checkpoint_count(root, stage_name=_REVISION_STAGE)
    _reject_multiple_provider_escrows(
        stage_name=_REVISION_STAGE,
        count=revision_checkpoint_before,
    )
    amended_path = root / "system-authored-review-revised-research-plan.json"
    revision_root = root / "revision"
    if amended_path.is_file():
        if revision_checkpoint_before != 1:
            raise ContestDirectionReviewRecoveryError(
                "retained revision artifact lacks its unique provider escrow"
            )
        amended = ContestDirectPlanRevisionArtifact.model_validate_json(
            amended_path.read_text(encoding="utf-8")
        )
    else:
        checkpointed_revision = _single_invocation_stage_completion(
            root=root,
            stage_name=_REVISION_STAGE,
            stage_input_hash=revision_stage_hash,
            completion=revision_completion,
            existing_escrow_count=revision_checkpoint_before,
        )
        amended = revision_runner(
            original_plan=bundle.source_plan,
            scientific_problem=bundle.source_plan.scientific_problem,
            requirements=_revision_requirements(),
            selected_skill_contexts=tuple(
                {"name": item["skill_id"], "content": item["content"]}
                for item in bundle.selected_skill_contexts
            ),
            reference_catalog=bundle.reference_catalog,
            preexperiment_artifact=bundle.preexperiment_path,
            preexperiment_metrics=None,
            preexperiment_root=bundle.preexperiment_root,
            verified_revision_context=feedback,
            derived_memory_context=None,
            output_dir=revision_root,
            output_path=amended_path,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=plan_max_tokens,
            temperature=0.2,
            llm_call=checkpointed_revision,
        )
    _validate_amended_plan(bundle=bundle, amended=amended, feedback=feedback)
    _verify_revision_sidecars(revision_root, amended)
    revision_receipt = _verify_revision_feedback_receipt(
        revision_root=revision_root,
        amended=amended,
        feedback=feedback,
    )
    revision_artifacts = [amended_path]
    revision_artifacts.extend(_revision_sidecar_paths(revision_root, amended))
    record_completed_stage(
        root=root,
        ordinal=1,
        stage_name=_REVISION_STAGE,
        stage_input_hash=revision_stage_hash,
        artifacts=revision_artifacts,
    )
    revision_checkpoint_after = provider_checkpoint_count(root, stage_name=_REVISION_STAGE)
    if revision_checkpoint_after != 1:
        raise ContestDirectionReviewRecoveryError(
            "review-driven revision must retain exactly one provider response"
        )
    _verify_provider_escrow_binding(
        root=root,
        stage_name=_REVISION_STAGE,
        stage_input_hash=revision_stage_hash,
        receipt=revision_receipt,
    )

    render_stage_hash = canonical_model_hash(
        {
            "recovery_input_hash": input_hash,
            "amended_plan_artifact_hash": amended.artifact_hash,
        }
    )
    plan_root = root / "plan"
    embedded = embedded_evidence_builder(
        bundle.preexperiment_path,
        artifact_path=bundle.preexperiment_path,
        preexperiment_root=bundle.preexperiment_root,
    )
    if embedded is None:
        raise ContestDirectionReviewRecoveryError(
            "verified exploratory evidence could not be embedded in the revised plan"
        )
    if (plan_root / "research-plan-manifest.json").is_file():
        rendered = _load_rendered_plan(plan_root)
    else:
        render_payload = amended.flat_payload()
        render_payload["embedded_evidence"] = embedded.payload
        render_payload.update(
            {
                "document_type": "独立终审后修订的科学假设与研究计划",
                "status": "one_shot_review_revision_pending_fresh_rereview",
                "specified_direction": bundle.direction,
                "focused_direction": bundle.focused_direction,
                "review_recovery": {
                    "recovery_input_hash": input_hash,
                    "source_plan_artifact_hash": bundle.source_plan.artifact_hash,
                    "source_review_artifact_hash": bundle.prior_review.artifact_hash,
                    "amended_plan_artifact_hash": amended.artifact_hash,
                    "revision_calls": 1,
                    "retrieval_calls": 0,
                    "preexperiment_calls": 0,
                },
                "preexperiment": {
                    "artifact_hash": bundle.prior_review.preexperiment_artifact_hash,
                    "study_phase": "exploratory_pilot",
                    "reexecuted_for_recovery": False,
                    "formal_experiment_executed": False,
                },
            }
        )
        rendered = plan_materializer(
            payload=render_payload,
            output_dir=plan_root,
            evidence_bindings=embedded.manifest_bindings,
            overwrite=False,
            timeout_seconds=render_timeout_seconds,
        )
    page_count, page_count_method = render_verifier(rendered)
    _validate_recovery_render(
        amended=amended,
        rendered=rendered,
        embedded=embedded,
    )
    record_completed_stage(
        root=root,
        ordinal=2,
        stage_name=_RENDER_STAGE,
        stage_input_hash=render_stage_hash,
        artifacts=_render_artifact_paths(rendered),
    )

    review_stage_hash = canonical_model_hash(
        {
            "recovery_input_hash": input_hash,
            "amended_plan_artifact_hash": amended.artifact_hash,
            "rendered_source_payload_sha256": rendered.source_payload_sha256,
            "preexperiment_artifact_hash": bundle.prior_review.preexperiment_artifact_hash,
            "locked_reference_catalog": list(bundle.reference_catalog),
            "selected_skill_sha256": list(bundle.prior_review.selected_skill_sha256),
            "prior_review_context_supplied": False,
        }
    )
    review_checkpoint_before = provider_checkpoint_count(root, stage_name=_REVIEW_STAGE)
    _reject_multiple_provider_escrows(
        stage_name=_REVIEW_STAGE,
        count=review_checkpoint_before,
    )
    review_root = root / "fresh-independent-scientific-review"
    review_path = review_root / "system-plan-scientific-review.json"
    if review_path.is_file():
        if review_checkpoint_before != 1:
            raise ContestDirectionReviewRecoveryError(
                "retained fresh review lacks its unique provider escrow"
            )
        fresh_review = load_contest_direct_plan_scientific_review(
            review_path,
            verify_files=True,
        )
    else:
        checkpointed_review = _single_invocation_stage_completion(
            root=root,
            stage_name=_REVIEW_STAGE,
            stage_input_hash=review_stage_hash,
            completion=review_completion,
            existing_escrow_count=review_checkpoint_before,
        )
        fresh_review = review_runner(
            final_plan=rendered.json_path,
            preexperiment_artifact=bundle.preexperiment_path,
            reference_catalog=bundle.reference_catalog,
            selected_skill_contexts=tuple(
                {"name": item["skill_id"], "content": item["content"]}
                for item in bundle.selected_skill_contexts
            ),
            required_audit_findings=(),
            derived_memory_context=None,
            preexperiment_metrics=None,
            preexperiment_root=bundle.preexperiment_root,
            output_dir=review_root,
            config_path=reviewer_config,
            env_path=reviewer_env,
            timeout_seconds=timeout_seconds,
            max_tokens=review_max_tokens,
            temperature=0.2,
            require_exact_reference_catalog=True,
            llm_call=checkpointed_review,
        )
    fresh_review_receipt = _validate_fresh_review(
        bundle=bundle,
        amended=amended,
        rendered=rendered,
        review_root=review_root,
        review_path=review_path,
        review=fresh_review,
    )
    record_completed_stage(
        root=root,
        ordinal=3,
        stage_name=_REVIEW_STAGE,
        stage_input_hash=review_stage_hash,
        artifacts=_review_artifact_paths(review_root, review_path, fresh_review),
    )
    review_checkpoint_after = provider_checkpoint_count(root, stage_name=_REVIEW_STAGE)
    if review_checkpoint_after != 1:
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview must retain exactly one provider response"
        )
    _verify_provider_escrow_binding(
        root=root,
        stage_name=_REVIEW_STAGE,
        stage_input_hash=review_stage_hash,
        receipt=fresh_review_receipt,
    )

    recommendation = str(fresh_review.review.recommendation)
    status = _NONBLOCKING.get(
        recommendation,
        "blocked_after_fresh_independent_review",
    )
    _verify_inventory(bundle.root, bundle.source_inventory)
    current_provider_requests = (
        revision_checkpoint_after
        - revision_checkpoint_before
        + review_checkpoint_after
        - review_checkpoint_before
    )
    physical_attempts_after = _provider_physical_attempts(root)
    current_provider_physical_attempts = sum(physical_attempts_after.values()) - sum(
        physical_attempts_before.values()
    )
    if current_provider_physical_attempts < 0:
        raise ContestDirectionReviewRecoveryError(
            "review-recovery physical provider attempt count regressed"
        )
    report = _report_payload(
        root=root,
        bundle=bundle,
        recovery_input_path=input_path,
        recovery_input_hash=input_hash,
        amended_path=amended_path,
        amended=amended,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        fresh_review_path=review_path,
        fresh_review=fresh_review,
        status=status,
        current_provider_requests=current_provider_requests,
        provider_physical_attempts_by_stage=physical_attempts_after,
        current_provider_physical_attempts=current_provider_physical_attempts,
    )
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["report_path"] = report_path.as_posix()
    returned["report_sha256"] = _sha256_file(report_path)
    return returned


def _load_blocked_review_bundle(root: Path) -> _BlockedReviewBundle:
    """Load a hash-valid v2/v3/v4/v5 run blocked specifically for major revision."""

    if not root.is_dir():
        raise ContestDirectionReviewRecoveryError(f"blocked source is missing: {root}")
    if (root / "delivery-report.json").exists():
        raise ContestDirectionReviewRecoveryError(
            "a completed research loop is not eligible for blocked-review recovery"
        )
    direction_input = _read_json(root / "direction-input.json")
    base_input = {
        key: value
        for key, value in direction_input.items()
        if key not in {"input_hash", "direction_id"}
    }
    source_literature_protocol = str(direction_input.get("literature_protocol") or "")
    if (
        direction_input.get("schema_version") != "contest-direction-research-loop-input-v2"
        or source_literature_protocol
        not in {
            "two_stage_literature_v2",
            "two_stage_literature_v3",
            "two_stage_literature_v4",
            "two_stage_literature_v5",
        }
        or direction_input.get("input_hash") != canonical_model_hash(base_input)
    ):
        raise ContestDirectionReviewRecoveryError("blocked source direction receipt is invalid")
    direction = str(direction_input.get("direction") or "").strip()
    if not direction:
        raise ContestDirectionReviewRecoveryError("blocked source direction is blank")

    source_stages = [
        (5, "skill-routing"),
        (8, "real-pilot"),
        (10, "final-plan-revision"),
        (11, "render-plan"),
        (12, "independent-scientific-review"),
    ]
    if source_literature_protocol in {
        "two_stage_literature_v4",
        "two_stage_literature_v5",
    }:
        source_stages.insert(0, (4, "planning-literature-lock"))
    for ordinal, stage in source_stages:
        _verify_source_stage(root, ordinal=ordinal, stage_name=stage)

    plan_path = root / "system-authored-revised-research-plan.json"
    try:
        source_plan = ContestDirectPlanRevisionArtifact.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ContestDirectionReviewRecoveryError("blocked source plan is invalid") from exc
    _verify_revision_sidecars(root / "revision", source_plan)

    rendered = _load_rendered_plan(root / "plan")
    rendered_payload = _read_json(rendered.json_path)
    rendered_source_path = rendered.source_path or (root / "plan" / "research-plan-source.json")
    rendered_source = _read_json(rendered_source_path)
    generation = rendered_source.get("generation")
    if (
        not isinstance(generation, Mapping)
        or generation.get("artifact_hash") != source_plan.artifact_hash
        or generation.get("final_revision_id") != source_plan.revision_id
    ):
        raise ContestDirectionReviewRecoveryError(
            "blocked source render is not bound to the source revision"
        )

    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    prior_review = load_contest_direct_plan_scientific_review(review_path, verify_files=True)
    if prior_review.review.recommendation != "major_revision":
        raise ContestDirectionReviewRecoveryError(
            "one-shot recovery is allowed only for an explicit major_revision verdict"
        )
    rendered_payload_hash = canonical_model_hash(rendered_payload)
    question = rendered_payload.get("question")
    question_zh = question.get("question_zh") if isinstance(question, Mapping) else None
    rendered_problem = str(question_zh or rendered_payload.get("problem_statement") or "").strip()
    if (
        prior_review.final_plan_source_kind != "materialized_final_plan"
        or prior_review.final_plan_id != f"materialized-final-plan-{rendered_payload_hash[:16]}"
        or prior_review.final_plan_artifact_hash != rendered_payload_hash
        or prior_review.final_plan_payload_sha256 != rendered_payload_hash
        or prior_review.final_plan_source_file_sha256 != _sha256_file(rendered.json_path)
        or prior_review.scientific_problem != rendered_problem
    ):
        raise ContestDirectionReviewRecoveryError(
            "blocking review is not bound to the rendered source plan"
        )

    block_path = root / "scientific-review-blocked-receipt.json"
    block = _read_json(block_path)
    focused_direction = str(block.get("focused_direction") or "").strip()
    expected_block = _source_block_receipt_payload(
        direction=direction,
        focused_direction=focused_direction,
        final_review=prior_review,
        review_path=review_path,
        literature_protocol=source_literature_protocol,
    )
    if block != expected_block:
        raise ContestDirectionReviewRecoveryError(
            "scientific review block receipt is invalid or stale"
        )
    if not focused_direction or source_plan.scientific_problem != focused_direction:
        raise ContestDirectionReviewRecoveryError(
            "blocked plan and focused direction are not the same lineage"
        )

    preexperiment_path = _find_preexperiment_path(
        root,
        expected_artifact_hash=prior_review.preexperiment_artifact_hash,
    )
    preexperiment_payload = _read_json(preexperiment_path)
    preexperiment_payload_hash = canonical_model_hash(preexperiment_payload)
    preexperiment_artifact_hash = canonical_model_hash(
        {key: value for key, value in preexperiment_payload.items() if key != "artifact_hash"}
    )
    if (
        preexperiment_payload.get("status") != "completed"
        or preexperiment_payload.get("study_phase") != "exploratory_pilot"
        or preexperiment_payload.get("formal_experiment_executed") not in (None, False)
        or preexperiment_artifact_hash != prior_review.preexperiment_artifact_hash
        or preexperiment_payload_hash != prior_review.preexperiment_artifact_payload_sha256
    ):
        raise ContestDirectionReviewRecoveryError(
            "blocked source preexperiment is invalid or outside the exploratory boundary"
        )
    _verify_review_evidence_files(prior_review, preexperiment_path.parent)

    references = tuple(prior_review.locked_reference_catalog)
    reference_status = _review_reference_integrity_status(prior_review)
    if reference_status not in {
        _LEGACY_REFERENCE_STATUS,
        _VERIFIED_REFERENCE_STATUS,
    }:
        raise ContestDirectionReviewRecoveryError(
            "blocking review has an unsupported reference-integrity status"
        )
    if source_literature_protocol == "two_stage_literature_v5":
        _verify_v5_reference_lock(
            root=root,
            references=references,
            source_plan=source_plan,
            prior_review=prior_review,
        )
    elif source_literature_protocol == "two_stage_literature_v4":
        _verify_v4_reference_lock(
            root=root,
            references=references,
            source_plan=source_plan,
            prior_review=prior_review,
        )
    else:
        validate_locked_bibliography(source_plan.plan.references, references)
    skill_contexts = _load_source_skill_contexts(
        root / "selected-method-skills.json",
        review_root=review_path.parent,
        review=prior_review,
        expected_hashes=prior_review.selected_skill_sha256,
    )
    inventory = tuple(_snapshot_inventory(root))
    return _BlockedReviewBundle(
        root=root,
        direction=direction,
        focused_direction=focused_direction,
        source_literature_protocol=source_literature_protocol,
        source_plan_path=plan_path,
        source_plan=source_plan,
        source_render_manifest_path=rendered.manifest_path,
        source_render_source_payload_sha256=rendered.source_payload_sha256,
        prior_review_path=review_path,
        prior_review=prior_review,
        block_receipt_path=block_path,
        block_receipt_hash=str(block["receipt_hash"]),
        preexperiment_path=preexperiment_path,
        preexperiment_root=preexperiment_path.parent,
        reference_catalog=references,
        selected_skill_contexts=skill_contexts,
        source_inventory=inventory,
    )


def _verify_v4_reference_lock(
    *,
    root: Path,
    references: Sequence[str],
    source_plan: ContestDirectPlanRevisionArtifact,
    prior_review: ContestDirectPlanScientificReviewArtifact,
) -> None:
    lock = _read_json(root / "literature" / "planning-literature.json")
    coverage = load_planning_literature_coverage_receipt(
        root / "literature" / "planning-literature-coverage.json"
    ).require_pass()
    _validate_v4_reference_lock_payload(
        lock,
        references=references,
        coverage_receipt_hash=coverage.receipt_hash,
        coverage_selected_record_ids=coverage.selected_record_ids,
    )
    if (
        source_plan.reference_projection is None
        or source_plan.reference_projection.policy != "locked-catalog-exact-order-v2"
        or prior_review.reference_catalog_binding_policy != "locked-catalog-exact-order-v2"
    ):
        raise ContestDirectionReviewRecoveryError(
            "v4 source did not enforce the exact locked reference identity/order"
        )
    validate_locked_bibliography(
        source_plan.plan.references,
        references,
        require_exact_catalog=True,
    )


def _validate_v4_reference_lock_payload(
    lock: Mapping[str, Any],
    *,
    references: Sequence[str],
    coverage_receipt_hash: str,
    coverage_selected_record_ids: Sequence[str],
) -> None:
    payload = dict(lock)
    artifact_hash = payload.pop("artifact_hash", None)
    catalog = payload.get("planning_catalog")
    if not isinstance(catalog, Sequence) or isinstance(catalog, str | bytes | bytearray):
        raise ContestDirectionReviewRecoveryError("v4 planning literature catalog is invalid")
    catalog_items = [dict(item) for item in catalog if isinstance(item, Mapping)]
    selected_record_ids = [str(item.get("record_id") or "") for item in catalog_items]
    if (
        lock.get("schema_version") != "contest-direction-planning-literature-v4"
        or lock.get("literature_protocol") != "two_stage_literature_v4"
        or artifact_hash != canonical_model_hash(payload)
        or lock.get("planning_catalog_hash") != canonical_model_hash({"catalog": catalog_items})
        or lock.get("selected_record_ids") != selected_record_ids
        or tuple(selected_record_ids) != tuple(coverage_selected_record_ids)
        or lock.get("planning_coverage_receipt_hash") != coverage_receipt_hash
        or lock.get("planning_context_hash") != canonical_model_hash({"context": list(references)})
    ):
        raise ContestDirectionReviewRecoveryError(
            "v4 planning literature lock is invalid or differs from the review catalog"
        )


def _verify_v5_reference_lock(
    *,
    root: Path,
    references: Sequence[str],
    source_plan: ContestDirectPlanRevisionArtifact,
    prior_review: ContestDirectPlanScientificReviewArtifact,
) -> None:
    """Replay the bounded zero/one-round v5 evidence chain before recovery."""

    literature_root = root / "literature"
    try:
        lock = _read_json(literature_root / "planning-literature.json")
        r1_coverage = load_planning_literature_coverage_receipt(
            literature_root / "planning-literature-coverage-r1.json"
        )
        coverage = load_planning_literature_coverage_receipt(
            literature_root / "planning-literature-coverage.json"
        ).require_pass()
        if (
            r1_coverage.schema_version != "contest-planning-literature-coverage-v5"
            or coverage.schema_version != "contest-planning-literature-coverage-v5"
        ):
            raise ContestDirectionReviewRecoveryError(
                "v5 protocol requires v5 R1 and final coverage receipts"
            )
        base_merged = ContestDirectionMergedLiteratureArtifact.model_validate_json(
            (literature_root / "merged-literature.json").read_text(encoding="utf-8")
        )
        (
            expected_gap_chain,
            merged_artifact_hash,
            merged_catalog_hash,
        ) = _replay_v5_gap_chain(
            literature_root=literature_root,
            lock=lock,
            base_merged=base_merged,
            r1_coverage=r1_coverage,
            final_coverage=coverage,
        )
        _validate_v5_reference_lock_payload(
            lock,
            references=references,
            base_merged_artifact_hash=base_merged.artifact_hash,
            base_merged_catalog_hash=base_merged.merged_catalog_hash,
            merged_artifact_hash=merged_artifact_hash,
            merged_catalog_hash=merged_catalog_hash,
            r1_coverage_schema_version=r1_coverage.schema_version,
            r1_coverage_receipt_hash=r1_coverage.receipt_hash,
            coverage_schema_version=coverage.schema_version,
            coverage_receipt_hash=coverage.receipt_hash,
            coverage_selected_record_ids=coverage.selected_record_ids,
            coverage_thresholds=coverage.thresholds.model_dump(mode="json"),
            coverage_selected_role_counts=(coverage.selected_role_counts.model_dump(mode="json")),
            coverage_role_query_ids=tuple(item.query_id for item in coverage.role_queries),
            method_focus_basis_query_ids=tuple(
                item.query_id for item in coverage.method_focus_basis_queries
            ),
            eligible_role_family_counts=(
                coverage.eligible_role_family_counts.model_dump(mode="json")
            ),
            coverage_anchor_assignments=tuple(
                item.model_dump(mode="json") for item in coverage.anchor_assignments
            ),
            expected_gap_chain=expected_gap_chain,
        )
    except ContestDirectionReviewRecoveryError:
        raise
    except Exception as exc:
        raise ContestDirectionReviewRecoveryError(
            "v5 planning literature evidence chain is invalid"
        ) from exc
    if (
        source_plan.reference_projection is None
        or source_plan.reference_projection.policy != "locked-catalog-exact-order-v2"
        or prior_review.reference_catalog_binding_policy != "locked-catalog-exact-order-v2"
    ):
        raise ContestDirectionReviewRecoveryError(
            "v5 source did not enforce the exact locked reference identity/order"
        )
    validate_locked_bibliography(
        source_plan.plan.references,
        references,
        require_exact_catalog=True,
    )


def _replay_v5_gap_chain(
    *,
    literature_root: Path,
    lock: Mapping[str, Any],
    base_merged: ContestDirectionMergedLiteratureArtifact,
    r1_coverage: Any,
    final_coverage: Any,
) -> tuple[dict[str, Any], str, str]:
    chain = lock.get("gap_repair_chain")
    if not isinstance(chain, Mapping):
        raise ContestDirectionReviewRecoveryError("v5 gap-repair chain is missing")
    round_count = chain.get("repair_round_count")
    if round_count not in {0, 1}:
        raise ContestDirectionReviewRecoveryError(
            "v5 gap-repair chain must contain zero or one repair round"
        )
    gap_root = literature_root / "gap-repair"
    diagnosis_path = gap_root / "gap-diagnosis.json"
    response_path = gap_root / "gap-query-response.json"
    projection_path = gap_root / "gap-query-projection.json"
    retrieval_path = gap_root / "gap-repair-literature.json"
    layered_path = literature_root / "layered-literature.json"
    r2_coverage_path = literature_root / "planning-literature-coverage-r2.json"
    repair_paths = (
        diagnosis_path,
        response_path,
        projection_path,
        retrieval_path,
        layered_path,
        r2_coverage_path,
    )
    if round_count == 0:
        if not r1_coverage.passed:
            raise ContestDirectionReviewRecoveryError(
                "v5 zero-round chain requires passing R1 coverage"
            )
        r1_role_queries = tuple(r1_coverage.role_queries)
        r1_method_focus_basis_queries = tuple(r1_coverage.method_focus_basis_queries)
        if (
            tuple(final_coverage.role_queries) != r1_role_queries
            or tuple(final_coverage.method_focus_basis_queries) != r1_method_focus_basis_queries
        ):
            raise ContestDirectionReviewRecoveryError(
                "v5 zero-round coverage does not preserve the exact R1 query lineage"
            )
        if any(path.exists() for path in repair_paths):
            raise ContestDirectionReviewRecoveryError(
                "v5 zero-round chain contains undeclared repair artifacts"
            )
        return (
            {
                "repair_round_count": 0,
                "gap_diagnosis_hash": None,
                "gap_query_response_receipt_hash": None,
                "gap_query_projection_hash": None,
                "gap_retrieval_artifact_hash": None,
                "gap_retrieval_catalog_hash": None,
                "layered_literature_artifact_hash": None,
                "r2_pre_status_coverage_receipt_hash": None,
            },
            base_merged.artifact_hash,
            base_merged.merged_catalog_hash,
        )

    missing = [path for path in repair_paths if not path.is_file()]
    if missing:
        raise ContestDirectionReviewRecoveryError(
            "v5 one-round chain is missing declared repair artifacts"
        )
    if r1_coverage.passed:
        raise ContestDirectionReviewRecoveryError(
            "v5 one-round chain cannot repair already-passing R1 coverage"
        )
    diagnosis = load_planning_literature_gap_diagnosis(diagnosis_path)
    response = load_planning_literature_gap_repair_response(response_path)
    projection = load_planning_literature_gap_repair_projection(projection_path)
    expected_plan = build_contest_direction_gap_repair_plan_from_projection(
        base_merged_artifact_hash=base_merged.artifact_hash,
        base_merged_catalog_hash=base_merged.merged_catalog_hash,
        projection=projection,
    )
    retrieval = load_contest_direction_gap_repair(
        retrieval_path,
        expected_plan=expected_plan,
    )
    layered = load_contest_direction_layered_literature(
        layered_path,
        base_merged_path=literature_root / "merged-literature.json",
        repair_artifact_paths=(retrieval_path,),
    )
    r2_coverage = load_planning_literature_coverage_receipt(r2_coverage_path).require_pass()
    if r2_coverage.schema_version != "contest-planning-literature-coverage-v5":
        raise ContestDirectionReviewRecoveryError(
            "v5 one-round chain requires a v5 R2 coverage receipt"
        )
    projected_role_queries = tuple(projection.r2_role_queries)
    r1_method_focus_basis_queries = tuple(r1_coverage.method_focus_basis_queries)
    if (
        diagnosis.coverage_receipt != r1_coverage
        or projection.diagnosis != diagnosis
        or response.projection != projection
        or retrieval.plan.trigger_coverage_receipt_hash != r1_coverage.receipt_hash
        or retrieval.plan.gap_repair_projection_hash != projection.projection_hash
        or retrieval.plan.base_merged_artifact_hash != base_merged.artifact_hash
        or retrieval.plan.base_merged_catalog_hash != base_merged.merged_catalog_hash
        or layered.base_merged_artifact_hash != base_merged.artifact_hash
        or layered.base_merged_catalog_hash != base_merged.merged_catalog_hash
        or len(layered.repair_rounds) != 1
        or tuple(r2_coverage.role_queries) != projected_role_queries
        or tuple(final_coverage.role_queries) != projected_role_queries
        or tuple(r2_coverage.method_focus_basis_queries) != r1_method_focus_basis_queries
        or tuple(final_coverage.method_focus_basis_queries) != r1_method_focus_basis_queries
    ):
        raise ContestDirectionReviewRecoveryError(
            "v5 one-round repair artifacts do not form one exact R1-to-R2 lineage"
        )
    return (
        {
            "repair_round_count": 1,
            "gap_diagnosis_hash": diagnosis.diagnosis_hash,
            "gap_query_response_receipt_hash": response.receipt_hash,
            "gap_query_projection_hash": projection.projection_hash,
            "gap_retrieval_artifact_hash": retrieval.artifact_hash,
            "gap_retrieval_catalog_hash": retrieval.repair_catalog_hash,
            "layered_literature_artifact_hash": layered.artifact_hash,
            "r2_pre_status_coverage_receipt_hash": r2_coverage.receipt_hash,
        },
        layered.artifact_hash,
        layered.merged_catalog_hash,
    )


def _validate_v5_reference_lock_payload(
    lock: Mapping[str, Any],
    *,
    references: Sequence[str],
    base_merged_artifact_hash: str,
    base_merged_catalog_hash: str,
    merged_artifact_hash: str,
    merged_catalog_hash: str,
    r1_coverage_schema_version: str,
    r1_coverage_receipt_hash: str,
    coverage_schema_version: str,
    coverage_receipt_hash: str,
    coverage_selected_record_ids: Sequence[str],
    coverage_thresholds: Mapping[str, Any],
    coverage_selected_role_counts: Mapping[str, Any],
    coverage_role_query_ids: Sequence[str],
    method_focus_basis_query_ids: Sequence[str],
    eligible_role_family_counts: Mapping[str, Any],
    coverage_anchor_assignments: Sequence[Mapping[str, Any]],
    expected_gap_chain: Mapping[str, Any],
) -> None:
    payload = dict(lock)
    artifact_hash = payload.pop("artifact_hash", None)
    catalog = payload.get("planning_catalog")
    if not isinstance(catalog, Sequence) or isinstance(catalog, str | bytes | bytearray):
        raise ContestDirectionReviewRecoveryError("v5 planning literature catalog is invalid")
    catalog_items = [dict(item) for item in catalog if isinstance(item, Mapping)]
    if not catalog_items or len(catalog_items) != len(catalog):
        raise ContestDirectionReviewRecoveryError("v5 planning literature catalog is invalid")
    selected_record_ids = [str(item.get("record_id") or "") for item in catalog_items]
    gap_chain = lock.get("gap_repair_chain")
    if (
        lock.get("schema_version") != "contest-direction-planning-literature-v5"
        or lock.get("literature_protocol") != "two_stage_literature_v5"
        or artifact_hash != canonical_model_hash(payload)
        or lock.get("base_merged_literature_artifact_hash") != base_merged_artifact_hash
        or lock.get("base_merged_literature_catalog_hash") != base_merged_catalog_hash
        or lock.get("merged_literature_artifact_hash") != merged_artifact_hash
        or lock.get("merged_literature_catalog_hash") != merged_catalog_hash
        or gap_chain != expected_gap_chain
        or lock.get("gap_repair_chain_hash") != canonical_model_hash(dict(expected_gap_chain))
        or lock.get("planning_catalog_hash") != canonical_model_hash({"catalog": catalog_items})
        or lock.get("selected_record_ids") != selected_record_ids
        or tuple(selected_record_ids) != tuple(coverage_selected_record_ids)
        or lock.get("r1_planning_coverage_schema_version") != r1_coverage_schema_version
        or lock.get("r1_planning_coverage_receipt_hash") != r1_coverage_receipt_hash
        or lock.get("planning_coverage_schema_version") != coverage_schema_version
        or lock.get("planning_coverage_receipt_hash") != coverage_receipt_hash
        or lock.get("planning_coverage_thresholds") != dict(coverage_thresholds)
        or lock.get("planning_coverage_selected_role_counts") != dict(coverage_selected_role_counts)
        or lock.get("planning_coverage_role_query_ids") != list(coverage_role_query_ids)
        or lock.get("planning_coverage_method_focus_basis_query_ids")
        != list(method_focus_basis_query_ids)
        or lock.get("planning_coverage_eligible_role_family_counts")
        != dict(eligible_role_family_counts)
        or lock.get("planning_coverage_anchor_assignments")
        != [dict(item) for item in coverage_anchor_assignments]
        or lock.get("planning_context_hash") != canonical_model_hash({"context": list(references)})
    ):
        raise ContestDirectionReviewRecoveryError(
            "v5 planning literature lock is invalid or differs from the review/gap chain"
        )


def _verify_source_stage(root: Path, *, ordinal: int, stage_name: str) -> dict[str, Any]:
    path = root / "checkpoints" / "completed-stages" / f"{ordinal:02d}-{stage_name}.json"
    receipt = _read_json(path)
    stage_hash = str(receipt.get("stage_input_hash") or "")
    loaded = load_completed_stage(
        root=root,
        ordinal=ordinal,
        stage_name=stage_name,
        stage_input_hash=stage_hash,
    )
    if loaded is None:
        raise ContestDirectionReviewRecoveryError(f"source stage is absent: {stage_name}")
    return loaded


def _source_block_receipt_payload(
    *,
    direction: str,
    focused_direction: str,
    final_review: ContestDirectPlanScientificReviewArtifact,
    review_path: Path,
    literature_protocol: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-scientific-review-block-v1",
        "status": "blocked_by_independent_scientific_review",
        "direction": direction,
        "focused_direction": focused_direction,
        "literature_protocol": literature_protocol,
        "recommendation": final_review.review.recommendation,
        "recommendation_text": final_review.review.recommendation_text,
        "reason": (
            "The independent non-rewriting scientific review did not authorize final "
            "delivery. The review and rendered plan are preserved; no automatic revision "
            "or review loop was started."
        ),
        "review_artifact": _artifact_binding(
            review_path,
            artifact_hash=final_review.artifact_hash,
        ),
        "delivery_report_created": False,
        "automatic_revision_performed": False,
        "rendered_plan_preserved": True,
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    return payload


def _find_preexperiment_path(root: Path, *, expected_artifact_hash: str) -> Path:
    receipt = _verify_source_stage(root, ordinal=8, stage_name="real-pilot")
    candidates: list[Path] = []
    for binding in receipt.get("artifacts", []):
        if not isinstance(binding, Mapping):
            continue
        relative = str(binding.get("relative_path") or "")
        path = (root / relative).resolve()
        if path.suffix.casefold() != ".json":
            continue
        try:
            payload = _read_json(path)
        except Exception:
            continue
        if payload.get("artifact_hash") == expected_artifact_hash:
            candidates.append(path)
    if len(candidates) != 1:
        raise ContestDirectionReviewRecoveryError(
            "real-pilot stage does not identify one bound preexperiment artifact"
        )
    return candidates[0]


def _verify_review_evidence_files(
    review: ContestDirectPlanScientificReviewArtifact,
    preexperiment_root: Path,
) -> None:
    root = preexperiment_root.resolve()
    for item in review.verified_files:
        path = Path(item.path)
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ContestDirectionReviewRecoveryError(
                "review evidence file escapes the preexperiment root"
            ) from exc
        if (
            not path.is_file()
            or path.stat().st_size != item.size_bytes
            or _sha256_file(path) != item.sha256
        ):
            raise ContestDirectionReviewRecoveryError("review-bound preexperiment evidence changed")


def _load_source_skill_contexts(
    manifest_path: Path,
    *,
    review_root: Path,
    review: ContestDirectPlanScientificReviewArtifact,
    expected_hashes: Sequence[str],
) -> tuple[dict[str, str], ...]:
    manifest = _read_json(manifest_path)
    expected_manifest_hash = canonical_model_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    if manifest.get("manifest_hash") != expected_manifest_hash:
        raise ContestDirectionReviewRecoveryError("selected Skill manifest hash mismatch")
    rows = manifest.get("skills")
    if not isinstance(rows, list) or not rows:
        raise ContestDirectionReviewRecoveryError("selected Skill manifest is empty")
    manifest_skill_ids = tuple(
        str(row.get("skill_id") or "").strip() for row in rows if isinstance(row, Mapping)
    )
    if len(manifest_skill_ids) != len(rows) or any(not item for item in manifest_skill_ids):
        raise ContestDirectionReviewRecoveryError("selected Skill record is invalid")
    relative = Path(review.authorship_receipt_relative_path)
    receipt_path = (
        relative.resolve() if relative.is_absolute() else (review_root / relative).resolve()
    )
    try:
        receipt_path.relative_to(review_root.resolve())
        receipt = ModelAuthorshipReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ContestDirectionReviewRecoveryError(
            "blocking review authorship receipt is invalid"
        ) from exc
    if receipt.receipt_hash != review.authorship_receipt_hash:
        raise ContestDirectionReviewRecoveryError(
            "blocking review authorship receipt hash mismatch"
        )
    contexts: list[dict[str, str]] = []
    hashes: list[str] = []
    for message in receipt.messages:
        try:
            payload = json.loads(message.get("content", ""))
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("context_kind") != "system_selected_project_method_skill"
        ):
            continue
        skill_id = str(payload.get("skill_name") or "").strip()
        content = str(payload.get("content") or "").strip()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not skill_id or not content or payload.get("content_sha256") != digest:
            raise ContestDirectionReviewRecoveryError(
                "blocking review contains an invalid Skill context"
            )
        hashes.append(digest)
        contexts.append({"skill_id": skill_id, "content": content})
    if tuple(item["skill_id"] for item in contexts) != manifest_skill_ids:
        raise ContestDirectionReviewRecoveryError(
            "blocking review Skill contexts differ from the routed Skill manifest"
        )
    if tuple(hashes) != tuple(expected_hashes):
        raise ContestDirectionReviewRecoveryError(
            "selected Skill bytes differ from the blocking review context"
        )
    return tuple(contexts)


def _review_feedback_payload(
    review: ContestDirectPlanScientificReviewArtifact | Any,
) -> dict[str, Any]:
    content = _model_payload(review.review)
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-review-feedback-v1",
        "source_review_id": review.review_id,
        "source_review_artifact_hash": review.artifact_hash,
        "source_review_input_hash": review.input_hash,
        "recommendation": content.get("recommendation"),
        "review_content": content,
        "epistemic_boundary_zh": (
            "该终审是需要逐项响应的模型批评，不是新增科学事实、文献或实验观察。"
        ),
    }
    payload["feedback_hash"] = canonical_model_hash(payload)
    return payload


def _revision_requirements() -> tuple[str, ...]:
    return (
        "只执行一次完整研究计划修订；不得输出补丁，不得启动新检索或新实验。",
        "逐项响应终审的全部重大问题，并在不损害证据边界时处理次要问题。",
        "评审批评不是新增科学事实；真实观察只能来自原先已核验的探索性预实验。",
        "保留锁定参考目录，未执行工作必须使用计划语气，截止到研究计划。",
    )


def _recovery_input_payload(
    *,
    bundle: _BlockedReviewBundle,
    feedback: Mapping[str, Any],
    config_path: Path | str,
    env_path: Path | str,
    review_config_path: Path | str,
    review_env_path: Path | str,
    plan_max_tokens: int,
    review_max_tokens: int,
    timeout_seconds: int,
    render_timeout_seconds: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": _INPUT_SCHEMA,
        "source_blocked_root": bundle.root.as_posix(),
        "source_literature_protocol": bundle.source_literature_protocol,
        "literature_protocol_migration_performed": False,
        "source_inventory": list(bundle.source_inventory),
        "source_inventory_hash": canonical_model_hash({"files": list(bundle.source_inventory)}),
        "source_plan": _artifact_binding(
            bundle.source_plan_path,
            artifact_hash=bundle.source_plan.artifact_hash,
        ),
        "source_render_manifest": _artifact_binding(bundle.source_render_manifest_path),
        "source_render_payload_sha256": bundle.source_render_source_payload_sha256,
        "source_review": _artifact_binding(
            bundle.prior_review_path,
            artifact_hash=bundle.prior_review.artifact_hash,
        ),
        "source_review_reference_structure": {
            "status": _review_reference_integrity_status(bundle.prior_review),
            "accepted_as_immutable_revision_input": True,
            "silently_upgraded": False,
        },
        "locked_reference_catalog": list(bundle.reference_catalog),
        "locked_reference_catalog_sha256": canonical_model_hash(
            {"references": list(bundle.reference_catalog)}
        ),
        "selected_skill_sha256": list(bundle.prior_review.selected_skill_sha256),
        "source_block_receipt": _artifact_binding(
            bundle.block_receipt_path,
            artifact_hash=bundle.block_receipt_hash,
        ),
        "preexperiment": _artifact_binding(
            bundle.preexperiment_path,
            artifact_hash=bundle.prior_review.preexperiment_artifact_hash,
        ),
        "review_feedback_hash": feedback["feedback_hash"],
        "call_contract": {
            "plan_revision_calls": 1,
            "fresh_independent_review_calls": 1,
            "render_calls": 1,
            "retrieval_calls": 0,
            "skill_routing_calls": 0,
            "hypothesis_calls": 0,
            "preexperiment_calls": 0,
            "additional_revision_after_rereview_calls": 0,
        },
        "revision_runtime": _runtime_contract(
            config_path=config_path,
            env_path=env_path,
            max_tokens=plan_max_tokens,
            timeout_seconds=timeout_seconds,
        ),
        "review_runtime": _runtime_contract(
            config_path=review_config_path,
            env_path=review_env_path,
            max_tokens=review_max_tokens,
            timeout_seconds=timeout_seconds,
        ),
        "render_timeout_seconds": render_timeout_seconds,
        "fresh_review_boundary": {
            "prior_review_context_supplied": False,
            "prior_audit_context_supplied": False,
            "scope": "fresh_interaction_not_model_family_independence",
        },
    }
    payload["input_hash"] = canonical_model_hash(payload)
    return payload


def _runtime_contract(
    *,
    config_path: Path | str,
    env_path: Path | str,
    max_tokens: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    config = Path(config_path).expanduser().resolve()
    env = Path(env_path).expanduser().resolve()
    return {
        "config_path": config.as_posix(),
        "config_sha256": _sha256_file(config) if config.is_file() else None,
        "env_path": env.as_posix(),
        "env_secret_bytes_logged": False,
        "max_tokens": max_tokens,
        "timeout_seconds": timeout_seconds,
    }


def _validate_amended_plan(
    *,
    bundle: _BlockedReviewBundle,
    amended: ContestDirectPlanRevisionArtifact | Any,
    feedback: Mapping[str, Any],
) -> None:
    if amended.generation_calls != 1:
        raise ContestDirectionReviewRecoveryError("recovery revision must contain one model call")
    if (
        amended.original_plan_id != bundle.source_plan.revision_id
        or amended.original_plan_artifact_hash != bundle.source_plan.artifact_hash
        or amended.scientific_problem != bundle.source_plan.scientific_problem
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery revision is not derived from the blocked source plan"
        )
    validate_locked_bibliography(
        amended.plan.references,
        bundle.reference_catalog,
        require_exact_catalog=True,
    )
    if _model_payload(amended.plan) == _model_payload(bundle.source_plan.plan):
        raise ContestDirectionReviewRecoveryError(
            "review-driven revision returned the unchanged scientific plan"
        )
    expected_context_hash = canonical_model_hash(dict(feedback))
    if getattr(amended, "verified_revision_context_sha256", None) != expected_context_hash:
        raise ContestDirectionReviewRecoveryError(
            "recovery revision is not hash-bound to the structured review feedback"
        )
    if isinstance(amended, ContestDirectPlanRevisionArtifact) and not str(
        feedback["source_review_artifact_hash"]
    ):
        raise ContestDirectionReviewRecoveryError("source review feedback is unbound")


def _verify_revision_feedback_receipt(
    *,
    revision_root: Path,
    amended: ContestDirectPlanRevisionArtifact | Any,
    feedback: Mapping[str, Any],
) -> ModelAuthorshipReceipt | None:
    if not isinstance(amended, ContestDirectPlanRevisionArtifact):
        return None
    relative = Path(amended.authorship_receipt_relative_path)
    receipt_path = (
        relative.resolve() if relative.is_absolute() else (revision_root / relative).resolve()
    )
    try:
        receipt_path.relative_to(revision_root.resolve())
        receipt = ModelAuthorshipReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ContestDirectionReviewRecoveryError(
            "recovery revision authorship receipt is invalid"
        ) from exc
    if (
        receipt.artifact_kind != "research_plan"
        or receipt.receipt_hash != amended.authorship_receipt_hash
        or receipt.response_sha256 != amended.model_response_hash
        or receipt.provider != amended.provider
        or receipt.model_name != amended.model_name
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery revision authorship receipt is not bound to the revision"
        )
    serialized_messages = json.dumps(list(receipt.messages), ensure_ascii=False, sort_keys=True)
    required_bindings = (
        str(feedback["source_review_artifact_hash"]),
        str(feedback["feedback_hash"]),
    )
    if any(binding not in serialized_messages for binding in required_bindings):
        raise ContestDirectionReviewRecoveryError(
            "recovery revision prompt omitted the immutable review feedback binding"
        )
    return receipt


def _validate_fresh_review(
    *,
    bundle: _BlockedReviewBundle,
    amended: ContestDirectPlanRevisionArtifact | Any,
    rendered: ContestDirectPlanArtifacts,
    review_root: Path,
    review_path: Path,
    review: ContestDirectPlanScientificReviewArtifact | Any,
) -> ModelAuthorshipReceipt | None:
    public_payload = _read_json(rendered.json_path)
    public_payload_hash = canonical_model_hash(public_payload)
    source_path = rendered.source_path
    if source_path is None:
        raise ContestDirectionReviewRecoveryError(
            "recovery render omitted its private source payload"
        )
    source_payload = _read_json(source_path)
    if rendered.source_payload_sha256 != canonical_model_hash(source_payload):
        raise ContestDirectionReviewRecoveryError("recovery render source-payload hash is stale")
    expected_plan_payload = amended.flat_payload()
    if any(source_payload.get(key) != value for key, value in expected_plan_payload.items()):
        raise ContestDirectionReviewRecoveryError(
            "recovery render scientific content differs from the amended plan"
        )
    recovery_binding = source_payload.get("review_recovery")
    if (
        not isinstance(recovery_binding, Mapping)
        or recovery_binding.get("amended_plan_artifact_hash") != amended.artifact_hash
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery render is not bound to the amended plan artifact"
        )
    if review.generation_calls != 1 or review.plan_rewrite_performed:
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview must be one non-rewriting model call"
        )
    recommendation = str(review.review.recommendation)
    if recommendation not in {*_NONBLOCKING, *_BLOCKING}:
        raise ContestDirectionReviewRecoveryError("fresh rereview recommendation is unsupported")
    if (
        review.prior_audit_context_supplied
        or review.required_audit_findings_sha256 is not None
        or review.input_hash == bundle.prior_review.input_hash
        or review.artifact_hash == bundle.prior_review.artifact_hash
    ):
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview inherited or replayed the blocking review"
        )
    if review.independence_scope != "fresh_interaction_not_model_family_independence":
        raise ContestDirectionReviewRecoveryError("fresh rereview independence scope changed")
    question = public_payload.get("question")
    question_zh = question.get("question_zh") if isinstance(question, Mapping) else None
    expected_problem = str(question_zh or public_payload.get("problem_statement") or "").strip()
    expected_plan_id = f"materialized-final-plan-{public_payload_hash[:16]}"
    if (
        review.final_plan_source_kind != "materialized_final_plan"
        or review.final_plan_id != expected_plan_id
        or review.final_plan_artifact_hash != public_payload_hash
        or review.final_plan_payload_sha256 != public_payload_hash
        or review.final_plan_source_file_sha256 != _sha256_file(rendered.json_path)
        or review.scientific_problem != expected_problem
    ):
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview is not bound to this recovery's rendered public plan"
        )
    if (
        review.preexperiment_artifact_hash != bundle.prior_review.preexperiment_artifact_hash
        or review.preexperiment_artifact_payload_sha256
        != bundle.prior_review.preexperiment_artifact_payload_sha256
        or review.preexperiment_metrics_payload_sha256
        != bundle.prior_review.preexperiment_metrics_payload_sha256
        or review.verified_files_sha256 != bundle.prior_review.verified_files_sha256
    ):
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview changed the inherited preexperiment evidence binding"
        )
    if _review_reference_integrity_status(review) != _VERIFIED_REFERENCE_STATUS:
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview did not pass strict reference-index normalization"
        )
    if tuple(review.locked_reference_catalog) != bundle.reference_catalog:
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview changed the inherited locked reference catalog"
        )
    if tuple(review.selected_skill_sha256) != tuple(bundle.prior_review.selected_skill_sha256):
        raise ContestDirectionReviewRecoveryError(
            "fresh rereview changed the inherited Skill context"
        )
    if isinstance(review, ContestDirectPlanScientificReviewArtifact):
        loaded = load_contest_direct_plan_scientific_review(review_path, verify_files=True)
        if loaded != review or review_path.parent.resolve() != review_root.resolve():
            raise ContestDirectionReviewRecoveryError(
                "fresh rereview sidecars are not bound to the accepted review artifact"
            )
        receipt_path = review_root / review.authorship_receipt_relative_path
        return ModelAuthorshipReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    return None


def _validate_recovery_render(
    *,
    amended: ContestDirectPlanRevisionArtifact | Any,
    rendered: ContestDirectPlanArtifacts,
    embedded: ContestPlanEmbeddedEvidenceBundle,
) -> None:
    if rendered.source_path is None:
        raise ContestDirectionReviewRecoveryError(
            "recovery render omitted its private source payload"
        )
    source_payload = _read_json(rendered.source_path)
    public_payload = _read_json(rendered.json_path)
    manifest = _read_json(rendered.manifest_path)
    expected_source_hash = canonical_model_hash(source_payload)
    expected_public_payload = _public_plan_projection(source_payload)
    expected_public_hash = canonical_model_hash(expected_public_payload)
    if (
        rendered.source_payload_sha256 != expected_source_hash
        or manifest.get("source_payload_sha256") != expected_source_hash
        or public_payload != expected_public_payload
        or manifest.get("public_payload_sha256") != expected_public_hash
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery public/private render projections are inconsistent"
        )
    expected_plan_payload = amended.flat_payload()
    recovery_binding = source_payload.get("review_recovery")
    if (
        any(source_payload.get(key) != value for key, value in expected_plan_payload.items())
        or source_payload.get("embedded_evidence") != embedded.payload
        or not isinstance(recovery_binding, Mapping)
        or recovery_binding.get("amended_plan_artifact_hash") != amended.artifact_hash
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery private render is not bound to the amended plan and evidence"
        )
    expected_bindings = sorted(
        (dict(item) for item in embedded.manifest_bindings),
        key=lambda item: (str(item.get("path")), str(item.get("role"))),
    )
    manifest_embedded = manifest.get("embedded_evidence")
    if (
        not isinstance(manifest_embedded, Mapping)
        or manifest_embedded.get("present") is not True
        or manifest_embedded.get("content_sha256") != canonical_model_hash(embedded.payload)
        or manifest_embedded.get("provenance_bindings") != expected_bindings
        or manifest_embedded.get("provenance_bindings_sha256")
        != canonical_model_hash({"evidence_bindings": expected_bindings})
    ):
        raise ContestDirectionReviewRecoveryError(
            "recovery render manifest changed the embedded-evidence bindings"
        )


def _report_payload(
    *,
    root: Path,
    bundle: _BlockedReviewBundle,
    recovery_input_path: Path,
    recovery_input_hash: str,
    amended_path: Path,
    amended: ContestDirectPlanRevisionArtifact | Any,
    rendered: ContestDirectPlanArtifacts,
    page_count: int,
    page_count_method: str,
    fresh_review_path: Path,
    fresh_review: ContestDirectPlanScientificReviewArtifact | Any,
    status: str,
    current_provider_requests: int,
    provider_physical_attempts_by_stage: Mapping[str, int],
    current_provider_physical_attempts: int,
) -> dict[str, Any]:
    inventory = _snapshot_inventory(root, exclude={root / _REPORT_NAME})
    payload: dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA,
        "status": status,
        "recovery_input_hash": recovery_input_hash,
        "source_blocked_run": {
            "path": bundle.root.as_posix(),
            "literature_protocol": bundle.source_literature_protocol,
            "literature_protocol_migration_performed": False,
            "inventory_hash": canonical_model_hash({"files": list(bundle.source_inventory)}),
            "source_plan_artifact_hash": bundle.source_plan.artifact_hash,
            "source_review_artifact_hash": bundle.prior_review.artifact_hash,
            "source_block_receipt_hash": bundle.block_receipt_hash,
            "source_review_reference_structure": {
                "status": _review_reference_integrity_status(bundle.prior_review),
                "accepted_as_immutable_revision_input": True,
                "silently_upgraded": False,
            },
            "mutated_by_recovery": False,
        },
        "locked_reference_catalog": list(bundle.reference_catalog),
        "locked_reference_catalog_sha256": canonical_model_hash(
            {"references": list(bundle.reference_catalog)}
        ),
        "revision": {
            "path": amended_path.as_posix(),
            "revision_id": amended.revision_id,
            "artifact_hash": amended.artifact_hash,
            "original_plan_artifact_hash": amended.original_plan_artifact_hash,
            "generation_calls": amended.generation_calls,
        },
        "render": {
            "pdf": _artifact_binding(rendered.pdf_path),
            "manifest": _artifact_binding(rendered.manifest_path),
            "source_payload_sha256": rendered.source_payload_sha256,
            "page_count": page_count,
            "page_count_method": page_count_method,
            "pdf_text_verified": rendered.pdf_text_verified,
        },
        "fresh_independent_review": {
            "path": fresh_review_path.as_posix(),
            "review_id": fresh_review.review_id,
            "artifact_hash": fresh_review.artifact_hash,
            "recommendation": fresh_review.review.recommendation,
            "generation_calls": fresh_review.generation_calls,
            "prior_review_context_supplied": False,
            "prior_audit_context_supplied": False,
            "independence_scope": fresh_review.independence_scope,
            "reference_index_integrity_status": _review_reference_integrity_status(fresh_review),
            "locked_reference_catalog_inherited_exactly": True,
        },
        "model_call_accounting": {
            "recovery_lifetime_provider_responses": 2,
            "review_driven_revision_provider_responses": 1,
            "fresh_rereview_provider_responses": 1,
            "current_invocation_provider_requests": current_provider_requests,
            "provider_physical_attempts_by_stage": dict(provider_physical_attempts_by_stage),
            "provider_physical_attempts_lifetime": sum(
                provider_physical_attempts_by_stage.values()
            ),
            "current_invocation_provider_physical_attempts": (current_provider_physical_attempts),
            "retrieval_provider_requests": 0,
            "preexperiment_requests": 0,
        },
        "automatic_additional_revision_performed": False,
        "preexperiment_reexecuted": False,
        "formal_experiment_executed": False,
        "paper_claimed": False,
        "publication_authorized": False,
        "external_submission_authorized": False,
        "artifacts": {
            "recovery_input": _artifact_binding(recovery_input_path),
            "amended_plan": _artifact_binding(
                amended_path,
                artifact_hash=amended.artifact_hash,
            ),
            "rendered_pdf": _artifact_binding(rendered.pdf_path),
            "render_manifest": _artifact_binding(rendered.manifest_path),
            "fresh_review": _artifact_binding(
                fresh_review_path,
                artifact_hash=fresh_review.artifact_hash,
            ),
        },
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
    }
    payload["report_hash"] = canonical_model_hash(payload)
    return payload


def _load_completed_report(
    path: Path,
    *,
    expected_input_hash: str,
    root: Path,
) -> dict[str, Any]:
    report = _read_json(path)
    expected_report_hash = canonical_model_hash(
        {key: value for key, value in report.items() if key != "report_hash"}
    )
    inventory = report.get("file_inventory")
    if (
        report.get("schema_version") != _REPORT_SCHEMA
        or report.get("recovery_input_hash") != expected_input_hash
        or report.get("report_hash") != expected_report_hash
        or not isinstance(inventory, list)
        or report.get("file_inventory_hash") != canonical_model_hash({"files": inventory})
        or inventory != _snapshot_inventory(root, exclude={path})
    ):
        raise ContestDirectionReviewRecoveryError("completed recovery report is invalid")
    accounting = report.get("model_call_accounting")
    if not isinstance(accounting, Mapping):
        raise ContestDirectionReviewRecoveryError("completed recovery report is invalid")
    physical_keys = {
        "provider_physical_attempts_by_stage",
        "provider_physical_attempts_lifetime",
        "current_invocation_provider_physical_attempts",
    }
    present_physical_keys = physical_keys.intersection(accounting)
    if present_physical_keys:
        expected_by_stage = _provider_physical_attempts(root)
        current_attempts = accounting.get("current_invocation_provider_physical_attempts")
        if (
            present_physical_keys != physical_keys
            or accounting.get("provider_physical_attempts_by_stage") != expected_by_stage
            or accounting.get("provider_physical_attempts_lifetime")
            != sum(expected_by_stage.values())
            or isinstance(current_attempts, bool)
            or not isinstance(current_attempts, int)
            or not 0 <= current_attempts <= sum(expected_by_stage.values())
        ):
            raise ContestDirectionReviewRecoveryError(
                "completed recovery physical provider accounting is invalid"
            )
    return report


def _provider_physical_attempts(root: Path) -> dict[str, int]:
    return {
        stage: provider_checkpoint_accounting(root, stage_name=stage)["attempt_count"]
        for stage in _PROVIDER_STAGES
    }


def _review_artifact_paths(
    review_root: Path,
    review_path: Path,
    review: ContestDirectPlanScientificReviewArtifact | Any,
) -> tuple[Path, ...]:
    paths = [review_path]
    for relative in (
        review.raw_response_relative_path,
        review.authorship_receipt_relative_path,
        review.markdown_relative_path,
    ):
        path = Path(relative)
        paths.append(path.resolve() if path.is_absolute() else (review_root / path).resolve())
    return tuple(dict.fromkeys(paths))


def _revision_sidecar_paths(
    revision_root: Path,
    revision: ContestDirectPlanRevisionArtifact | Any,
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for relative in (
        revision.raw_response_relative_path,
        revision.authorship_receipt_relative_path,
    ):
        path = Path(relative)
        paths.append(path.resolve() if path.is_absolute() else (revision_root / path).resolve())
    return tuple(paths)


def _render_artifact_paths(rendered: ContestDirectPlanArtifacts) -> tuple[Path, ...]:
    return (
        rendered.json_path,
        *((rendered.source_path,) if rendered.source_path is not None else ()),
        rendered.markdown_path,
        rendered.tex_path,
        rendered.pdf_path,
        rendered.manifest_path,
    )


def _snapshot_inventory(
    root: Path,
    *,
    exclude: set[Path] | None = None,
) -> list[dict[str, Any]]:
    resolved_root = root.resolve()
    excluded = {path.resolve() for path in (exclude or set())}
    records: list[dict[str, Any]] = []
    for path in sorted(resolved_root.rglob("*")):
        resolved = path.resolve()
        if not resolved.is_file() or resolved in excluded:
            continue
        records.append(
            {
                "relative_path": resolved.relative_to(resolved_root).as_posix(),
                "size_bytes": resolved.stat().st_size,
                "sha256": _sha256_file(resolved),
            }
        )
    return records


def _verify_inventory(root: Path, inventory: Sequence[Mapping[str, Any]]) -> None:
    expected = [dict(item) for item in inventory]
    if _snapshot_inventory(root) != expected:
        raise ContestDirectionReviewRecoveryError("blocked source bytes changed")


def _source_guarded_callback(
    bundle: _BlockedReviewBundle,
    callback: Callable[_P, _R],
) -> Callable[_P, _R]:
    @wraps(callback)
    def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return callback(*args, **kwargs)
        finally:
            _verify_inventory(bundle.root, bundle.source_inventory)

    return invoke


def _artifact_binding(path: Path, *, artifact_hash: str | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ContestDirectionReviewRecoveryError(f"bound artifact is missing: {resolved}")
    payload: dict[str, Any] = {
        "path": resolved.as_posix(),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }
    if artifact_hash is not None:
        payload["artifact_hash"] = artifact_hash
    return payload


def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json")
        if isinstance(payload, dict):
            return payload
    if hasattr(value, "__dict__"):
        return {str(key): item for key, item in vars(value).items() if not str(key).startswith("_")}
    raise ContestDirectionReviewRecoveryError("scientific artifact is not serializable")


def _review_reference_integrity_status(review: Any) -> str:
    status = getattr(review, "reference_index_integrity_status", None)
    if status is None:
        return _LEGACY_REFERENCE_STATUS
    return str(status)


def _reject_multiple_provider_escrows(*, stage_name: str, count: int) -> None:
    if count > 1:
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} already contains more than one provider response"
        )


def _single_invocation_stage_completion(
    *,
    root: Path,
    stage_name: str,
    stage_input_hash: str,
    completion: Callable[..., LLMJsonCompletionResult],
    existing_escrow_count: int,
) -> Callable[..., LLMJsonCompletionResult]:
    def forbid_new_provider_call(**_kwargs: Any) -> LLMJsonCompletionResult:
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} resume request differs from its retained provider response"
        )

    replay = replayable_stage_completion(
        root=root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        completion=(completion if existing_escrow_count == 0 else forbid_new_provider_call),
    )
    invocation_count = 0

    def invoke(**kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal invocation_count
        if invocation_count >= 1:
            raise ContestDirectionReviewRecoveryError(
                f"{stage_name} attempted more than one completion invocation"
            )
        invocation_count += 1
        return replay(**kwargs)

    return invoke


def _verify_provider_escrow_binding(
    *,
    root: Path,
    stage_name: str,
    stage_input_hash: str,
    receipt: ModelAuthorshipReceipt | None,
) -> None:
    if receipt is None:
        return
    escrow_root = root / "checkpoints" / "provider-responses" / stage_name
    paths = sorted(escrow_root.glob("*.json")) if escrow_root.is_dir() else []
    if len(paths) != 1:
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} does not contain exactly one provider escrow"
        )
    payload = _read_json(paths[0])
    request = payload.get("request")
    completion_payload = payload.get("completion")
    expected_checkpoint_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    if (
        payload.get("schema_version") != "contest-direction-provider-response-checkpoint-v1"
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("checkpoint_hash") != expected_checkpoint_hash
        or not isinstance(request, Mapping)
        or not isinstance(completion_payload, Mapping)
        or payload.get("completion_hash") != canonical_model_hash(dict(completion_payload))
    ):
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} provider escrow identity or hash is invalid"
        )
    messages = request.get("messages")
    if (
        not isinstance(messages, list)
        or not all(isinstance(item, Mapping) for item in messages)
        or tuple(dict(item) for item in messages) != receipt.messages
    ):
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} provider request differs from its authorship receipt"
        )
    try:
        completion = LLMJsonCompletionResult.model_validate(completion_payload)
    except ValueError as exc:
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} provider completion is invalid"
        ) from exc
    if (
        completion.provider != receipt.provider
        or completion.base_url != receipt.base_url
        or completion.model_name != receipt.model_name
        or completion.endpoint != receipt.endpoint
        or completion.response_text != receipt.response_text
        or completion.parsed_json != receipt.parsed_payload
        or completion.usage != receipt.usage
        or completion.temperature != receipt.temperature
    ):
        raise ContestDirectionReviewRecoveryError(
            f"{stage_name} provider completion differs from its authorship receipt"
        )


def _require_disjoint_roots(source: Path, output: Path) -> None:
    if source == output or _is_within(output, source) or _is_within(source, output):
        raise ContestDirectionReviewRecoveryError(
            "source and recovery output roots must be distinct and non-overlapping"
        )


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stdout_json(payload: Mapping[str, Any]) -> str:
    """Serialize CLI output safely even when the Windows console is not UTF-8."""

    return json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one major-revision-blocked direction run, perform exactly one "
            "plan revision, rerender it, and obtain exactly one fresh review."
        )
    )
    parser.add_argument("--source-blocked-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--review-config", type=Path)
    parser.add_argument("--review-env", type=Path)
    parser.add_argument("--plan-max-tokens", type=int, default=14_000)
    parser.add_argument("--review-max-tokens", type=int, default=8_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_contest_direction_review_recovery(
        source_blocked_dir=args.source_blocked_dir,
        output_dir=args.output_dir,
        resume_existing=args.resume_existing,
        config_path=args.config,
        env_path=args.env,
        review_config_path=args.review_config,
        review_env_path=args.review_env,
        plan_max_tokens=args.plan_max_tokens,
        review_max_tokens=args.review_max_tokens,
        timeout_seconds=args.timeout_seconds,
        render_timeout_seconds=args.render_timeout_seconds,
    )
    print(_stdout_json(result))
    return 0 if result.get("status") in set(_NONBLOCKING.values()) else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ContestDirectionReviewRecoveryError",
    "run_contest_direction_review_recovery",
]
