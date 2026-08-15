"""One-shot field-local scientific repair after two preserved amendment failures.

The repair call may replace only the seven fields that contain the remaining
scientific defects.  Every other plan field is copied byte-for-byte at the model
value level.  A deterministic seven-finding audit runs before rendering or review;
there is no content retry loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
    ContestDirectPlanRevisionError,
    ContestDirectRevisedScientificPlan,
    _guard_observed_numbers,
)
from autoresearch.competition.contest_direct_plan_scientific_review import (
    ContestDirectPlanScientificReviewArtifact,
    load_contest_direct_plan_scientific_review,
    review_contest_direct_plan_science,
)
from autoresearch.competition.contest_direction_research_loop_cli import (
    _file_binding,
    _file_inventory,
    _read_json,
    _sha256_file,
    _verify_rendered_pdf,
    _verify_revision_sidecars,
    _write_new_json,
)
from autoresearch.competition.contest_direction_scientific_amendment_cli import (
    _audit_amended_plan,
    _build_red_team_findings,
    _load_prior_amendment_attempt,
    _load_source_bundle,
    _PriorAmendmentAttempt,
    _SourceBundle,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_reference_policy import validate_locked_bibliography
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_DEFAULT_SOURCE = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v1")
_DEFAULT_V2 = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v2")
_DEFAULT_V3 = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v3")
_DEFAULT_V4 = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v4")
_DEFAULT_OUTPUT = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v4")
_REPAIR_FIELDS = (
    "paper_abstract",
    "technical_details",
    "methods",
    "experiments",
    "baselines",
    "results",
    "limitations",
)
_RT06_REPAIR_FIELDS = ("paper_abstract", "results", "limitations")
_ALL_PLAN_FIELDS = (
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
    "references",
    "main_hypothesis",
    "limitations",
)
_FROZEN_FIELDS = (
    "problem_statement",
    "rationale",
    "datasets",
    "source",
    "target",
    "paper_title",
    "metrics",
    "references",
    "main_hypothesis",
)


class ContestDirectionTargetedScientificRepairError(RuntimeError):
    """Raised when the one-shot local scientific repair cannot be delivered."""


@dataclass(frozen=True)
class _RepairSources:
    v1: _SourceBundle
    v2: _PriorAmendmentAttempt
    v3: _PriorAmendmentAttempt
    v3_review: ContestDirectPlanScientificReviewArtifact


@dataclass(frozen=True)
class _V4RepairAttempt:
    root: Path
    report_path: Path
    report: dict[str, Any]
    plan_path: Path
    plan: ContestDirectPlanRevisionArtifact
    audit_path: Path
    audit: dict[str, Any]


def run_contest_direction_targeted_scientific_repair(
    *,
    source_delivery_dir: Path | str,
    v2_attempt_dir: Path | str,
    v3_attempt_dir: Path | str,
    output_dir: Path | str,
    v4_attempt_dir: Path | str | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    repair_max_tokens: int = 7_000,
    review_max_tokens: int = 8_000,
    timeout_seconds: int = 900,
    render_timeout_seconds: int = 180,
    sources_loader: Callable[[Path, Path, Path], _RepairSources] | None = None,
    v4_loader: Callable[[Path, _RepairSources], _V4RepairAttempt] | None = None,
    repair_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
    review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact] = (
        review_contest_direct_plan_science
    ),
) -> dict[str, Any]:
    """Repair seven fields once, then render/review only if all RT checks pass."""

    source_root = Path(source_delivery_dir).expanduser().resolve()
    v2_root = Path(v2_attempt_dir).expanduser().resolve()
    v3_root = Path(v3_attempt_dir).expanduser().resolve()
    v4_root = Path(v4_attempt_dir).expanduser().resolve() if v4_attempt_dir is not None else None
    root = Path(output_dir).expanduser().resolve()
    roots = {source_root, v2_root, v3_root, root}
    if v4_root is not None:
        roots.add(v4_root)
    if len(roots) != (5 if v4_root is not None else 4):
        raise ContestDirectionTargetedScientificRepairError(
            "v1, v2, v3, and v4 roots must all be distinct"
        )
    if root.exists() and any(root.iterdir()):
        raise ContestDirectionTargetedScientificRepairError(
            f"targeted repair output directory must be empty: {root}"
        )
    root.mkdir(parents=True, exist_ok=True)
    sources = (sources_loader or _load_repair_sources)(source_root, v2_root, v3_root)
    v4 = (v4_loader or _load_v4_repair_attempt)(v4_root, sources) if v4_root is not None else None
    amendment_version = "v5" if v4 is not None else "v4"
    original_plan = v4.plan if v4 is not None else sources.v3.plan
    repair_fields = _RT06_REPAIR_FIELDS if v4 is not None else _REPAIR_FIELDS
    frozen_fields = tuple(field for field in _ALL_PLAN_FIELDS if field not in repair_fields)

    findings = _build_red_team_findings(sources.v1, prior_attempt=sources.v3)
    active_ids = {"RT-06"} if v4 is not None else {"RT-02", "RT-05", "RT-06"}
    active_findings = tuple(
        item for item in findings["findings"] if item["finding_id"] in active_ids
    )
    repair_context: dict[str, Any] = {
        "schema_version": "contest-direction-targeted-scientific-repair-context-v1",
        "amendment_version": amendment_version,
        "direction": sources.v1.direction,
        "immediate_prior_revision_id": original_plan.revision_id,
        "immediate_prior_artifact_hash": original_plan.artifact_hash,
        "verified_pilot_artifact_hash": sources.v1.pilot.artifact_hash,
        "verified_metrics_sha256": sources.v1.pilot.metrics_sha256,
        "verified_runner_code_sha256": sources.v1.source_code_sha256,
        "repair_fields": list(repair_fields),
        "frozen_fields": list(frozen_fields),
        "active_findings": list(active_findings),
        "pilot_facts": findings["pilot_facts"],
        "formal_protocol_correction": findings["formal_protocol_correction"],
        "failed_attempts": {
            "v2_plan_artifact_hash": sources.v2.plan.artifact_hash,
            "v2_audit_artifact_hash": sources.v2.audit["artifact_hash"],
            "v2_review_response_sha256": _sha256_file(sources.v2.review_response_path),
            "v3_plan_artifact_hash": sources.v3.plan.artifact_hash,
            "v3_audit_artifact_hash": sources.v3.audit["artifact_hash"],
            "v3_review_artifact_hash": sources.v3_review.artifact_hash,
        },
    }
    if v4 is not None:
        repair_context["failed_attempts"]["v4_plan_artifact_hash"] = v4.plan.artifact_hash
        repair_context["failed_attempts"]["v4_audit_artifact_hash"] = v4.audit["artifact_hash"]
    repair_context["context_hash"] = canonical_model_hash(repair_context)
    context_path = root / "targeted-repair-input.json"
    _write_new_json(context_path, repair_context)

    messages = _build_repair_messages(
        plan=original_plan.plan,
        repair_context=repair_context,
        repair_fields=repair_fields,
        frozen_fields=frozen_fields,
        amendment_version=amendment_version,
    )
    input_hash = canonical_model_hash(
        {
            "immediate_prior_artifact_hash": original_plan.artifact_hash,
            "pilot_artifact_hash": sources.v1.pilot.artifact_hash,
            "repair_context_hash": repair_context["context_hash"],
            "repair_fields": list(repair_fields),
            "frozen_fields": list(frozen_fields),
        }
    )
    completion = repair_completion(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=repair_max_tokens,
        temperature=0.1,
        response_schema=_repair_response_schema(repair_fields=repair_fields),
        response_schema_name="contest_direction_targeted_scientific_repair",
    )
    repair_id = f"direct-plan-revision-{input_hash[:16]}"
    response_hash = hashlib.sha256(completion.response_text.encode("utf-8")).hexdigest()
    interaction_id = f"{repair_id}-{response_hash[:12]}"
    repair_root = root / "repair"
    response_path = repair_root / "responses" / f"{interaction_id}.txt"
    _write_immutable(response_path, completion.response_text.encode("utf-8"))
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id=interaction_id,
        attempt=1,
        messages=messages,
        completion=completion,
        output_dir=repair_root,
    )
    receipt_path = Path(receipt.output_path).resolve()

    replacements = _normalize_repair_payload(
        completion.parsed_json,
        repair_fields=repair_fields,
    )
    merged_plan = _merge_frozen_plan(
        original_plan.plan,
        replacements,
        frozen_fields=frozen_fields,
    )
    pilot_payload = _read_json(sources.v1.pilot_path)
    metrics_path = sources.v1.pilot_root / sources.v1.pilot.metrics_relative_path
    metrics_payload = _read_json(metrics_path)
    try:
        _guard_observed_numbers(
            merged_plan,
            original=original_plan,
            preexperiment_artifact=pilot_payload,
            preexperiment_metrics=metrics_payload,
            verified_file_contents={},
            verified_revision_context=repair_context,
        )
    except ContestDirectPlanRevisionError as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"targeted repair failed the existing numeric evidence guard: {exc}"
        ) from exc

    repaired = _build_repair_artifact(
        repair_root=repair_root,
        repair_id=repair_id,
        input_hash=input_hash,
        response_hash=response_hash,
        receipt_path=receipt_path,
        receipt_hash=receipt.receipt_hash,
        completion=completion,
        plan=merged_plan,
        original=original_plan,
        repair_context_hash=str(repair_context["context_hash"]),
        response_path=response_path,
    )
    repaired_path = root / "system-authored-targeted-research-plan.json"
    _write_new_json(repaired_path, repaired.model_dump(mode="json"))
    try:
        validate_locked_bibliography(repaired.plan.references, sources.v1.references)
    except ValueError as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"{amendment_version} bibliography failed the locked 5–10 reference contract: {exc}"
        ) from exc

    checks = _audit_amended_plan(repaired)
    audit_payload: dict[str, Any] = {
        "schema_version": "contest-direction-targeted-scientific-repair-audit-v1",
        "repaired_artifact_hash": repaired.artifact_hash,
        "repair_context_hash": repair_context["context_hash"],
        "checks": [check.__dict__ for check in checks],
        "all_required_corrections_passed": all(check.passed for check in checks),
        "frozen_fields_verified": all(
            getattr(repaired.plan, field) == getattr(original_plan.plan, field)
            for field in frozen_fields
        ),
        "provider_calls_so_far": 1,
    }
    audit_payload["artifact_hash"] = canonical_model_hash(audit_payload)
    audit_path = root / "targeted-scientific-repair-audit.json"
    _write_new_json(audit_path, audit_payload)
    if not audit_payload["all_required_corrections_passed"]:
        return _write_blocked_report(
            root=root,
            sources=sources,
            context_path=context_path,
            repaired_path=repaired_path,
            repaired=repaired,
            audit_path=audit_path,
            audit=audit_payload,
            amendment_version=amendment_version,
            v4=v4,
        )

    render_payload = repaired.flat_payload()
    embedded_evidence = build_contest_plan_embedded_evidence(
        sources.v1.pilot,
        artifact_path=sources.v1.pilot_path,
        preexperiment_root=sources.v1.pilot_root,
    )
    if embedded_evidence is not None:
        render_payload["embedded_evidence"] = embedded_evidence.payload
    render_payload.update(
        {
            "document_type": (
                f"含真实探索性预实验结果的科学研究计划（定向科学修订{amendment_version}）"
            ),
            "status": f"versioned_targeted_scientific_repair_{amendment_version}",
            "specified_direction": sources.v1.direction,
            "repair": {
                "immediate_prior_revision_id": original_plan.revision_id,
                "immediate_prior_artifact_hash": original_plan.artifact_hash,
                "repaired_revision_id": repaired.revision_id,
                "repaired_artifact_hash": repaired.artifact_hash,
                "frozen_fields": list(frozen_fields),
                "replaced_fields": list(repair_fields),
                "audit_artifact_hash": audit_payload["artifact_hash"],
            },
            "preexperiment": {
                "run_id": sources.v1.pilot.run_id,
                "artifact_hash": sources.v1.pilot.artifact_hash,
                "study_phase": sources.v1.pilot.study_phase,
                "reexecuted_for_repair": False,
                "formal_experiment_executed": False,
            },
        }
    )
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=root / "plan",
        evidence_bindings=(
            embedded_evidence.manifest_bindings
            if embedded_evidence is not None
            else ()
        ),
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )
    page_count, page_count_method = _verify_rendered_pdf(rendered)
    review_findings = tuple(
        {
            "finding_id": item["finding_id"],
            "question_zh": item["review_question_zh"],
            "required_correction_zh": item["required_correction_zh"],
            "deterministic_audit_passed": True,
        }
        for item in active_findings
    )
    final_review = review_runner(
        final_plan=rendered.json_path,
        preexperiment_artifact=sources.v1.pilot_path,
        reference_catalog=sources.v1.references,
        selected_skill_contexts=sources.v1.skill_contexts,
        preexperiment_metrics=None,
        preexperiment_root=sources.v1.pilot_root,
        required_audit_findings=review_findings,
        output_dir=root / "independent-scientific-review",
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=review_max_tokens,
        temperature=0.2,
    )
    if final_review.generation_calls != 1 or final_review.plan_rewrite_performed:
        raise ContestDirectionTargetedScientificRepairError(
            f"{amendment_version} requires exactly one fresh non-rewriting scientific review"
        )
    status: Literal["completed", "blocked_after_independent_review"] = (
        "completed"
        if final_review.review.recommendation == "pass"
        else "blocked_after_independent_review"
    )
    return _write_completed_report(
        root=root,
        status=status,
        sources=sources,
        context_path=context_path,
        repaired_path=repaired_path,
        repaired=repaired,
        audit_path=audit_path,
        audit=audit_payload,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        final_review=final_review,
        amendment_version=amendment_version,
        v4=v4,
    )


def finalize_existing_contest_direction_targeted_repair(
    *,
    source_delivery_dir: Path | str,
    v2_attempt_dir: Path | str,
    v3_attempt_dir: Path | str,
    v4_attempt_dir: Path | str,
    v5_attempt_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    review_max_tokens: int = 8_000,
    timeout_seconds: int = 900,
    render_timeout_seconds: int = 180,
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
    review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact] = (
        review_contest_direct_plan_science
    ),
) -> dict[str, Any]:
    """Re-audit immutable v5 bytes, then render and review without a repair call."""

    v1_root = Path(source_delivery_dir).expanduser().resolve()
    v2_root = Path(v2_attempt_dir).expanduser().resolve()
    v3_root = Path(v3_attempt_dir).expanduser().resolve()
    v4_root = Path(v4_attempt_dir).expanduser().resolve()
    root = Path(v5_attempt_dir).expanduser().resolve()
    if len({v1_root, v2_root, v3_root, v4_root, root}) != 5:
        raise ContestDirectionTargetedScientificRepairError(
            "v1 through v5 roots must be distinct for finalization"
        )
    sources = _load_repair_sources(v1_root, v2_root, v3_root)
    v4 = _load_v4_repair_attempt(v4_root, sources)
    v5 = _load_v5_blocked_attempt(root, sources, v4)
    reserved = (
        root / "targeted-scientific-repair-audit-v2.json",
        root / "delivery-report-v2.json",
        root / "plan",
        root / "independent-scientific-review",
    )
    if any(path.exists() for path in reserved):
        raise ContestDirectionTargetedScientificRepairError(
            "v5 finalization outputs already exist; refusing a second review"
        )

    checks = _audit_amended_plan(v5.plan)
    if not all(check.passed for check in checks):
        raise ContestDirectionTargetedScientificRepairError(
            "existing v5 bytes still fail the corrected semantic audit"
        )
    try:
        validate_locked_bibliography(v5.plan.plan.references, sources.v1.references)
    except ValueError as exc:
        raise ContestDirectionTargetedScientificRepairError(
            "existing v5 bibliography failed the locked 5–10 reference contract: " f"{exc}"
        ) from exc
    audit_payload: dict[str, Any] = {
        "schema_version": "contest-direction-targeted-scientific-repair-audit-v2",
        "repaired_artifact_hash": v5.plan.artifact_hash,
        "previous_audit": {
            **_file_binding(v5.audit_path),
            "artifact_hash": v5.audit["artifact_hash"],
            "recorded_false_negative_ids": ["RT-05", "RT-06"],
        },
        "checks": [check.__dict__ for check in checks],
        "all_required_corrections_passed": True,
        "frozen_fields_verified": True,
        "provider_calls_so_far": 1,
        "repair_provider_replayed": False,
        "reaudit_reason": (
            "semantic audit now recognizes substantive unit wording and the plan-level metric "
            "definition of finite-simulation z as non-population effect"
        ),
    }
    audit_payload["artifact_hash"] = canonical_model_hash(audit_payload)
    audit_path = root / "targeted-scientific-repair-audit-v2.json"
    _write_new_json(audit_path, audit_payload)

    render_payload = v5.plan.flat_payload()
    embedded_evidence = build_contest_plan_embedded_evidence(
        sources.v1.pilot,
        artifact_path=sources.v1.pilot_path,
        preexperiment_root=sources.v1.pilot_root,
    )
    if embedded_evidence is not None:
        render_payload["embedded_evidence"] = embedded_evidence.payload
    render_payload.update(
        {
            "document_type": "含真实探索性预实验结果的科学研究计划（定向科学修订v5）",
            "status": "versioned_targeted_scientific_repair_v5_reaudited",
            "specified_direction": sources.v1.direction,
            "repair": {
                "source_v4_revision_id": v4.plan.revision_id,
                "source_v4_artifact_hash": v4.plan.artifact_hash,
                "v5_revision_id": v5.plan.revision_id,
                "v5_artifact_hash": v5.plan.artifact_hash,
                "repair_provider_replayed": False,
                "audit_artifact_hash": audit_payload["artifact_hash"],
            },
            "preexperiment": {
                "run_id": sources.v1.pilot.run_id,
                "artifact_hash": sources.v1.pilot.artifact_hash,
                "study_phase": sources.v1.pilot.study_phase,
                "reexecuted_for_repair": False,
                "formal_experiment_executed": False,
            },
        }
    )
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=root / "plan",
        evidence_bindings=(
            embedded_evidence.manifest_bindings
            if embedded_evidence is not None
            else ()
        ),
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )
    page_count, page_count_method = _verify_rendered_pdf(rendered)
    findings = _build_red_team_findings(sources.v1, prior_attempt=sources.v3)
    rt06 = next(item for item in findings["findings"] if item["finding_id"] == "RT-06")
    final_review = review_runner(
        final_plan=rendered.json_path,
        preexperiment_artifact=sources.v1.pilot_path,
        reference_catalog=sources.v1.references,
        selected_skill_contexts=sources.v1.skill_contexts,
        preexperiment_metrics=None,
        preexperiment_root=sources.v1.pilot_root,
        required_audit_findings=(
            {
                "finding_id": "RT-06",
                "question_zh": rt06["review_question_zh"],
                "required_correction_zh": rt06["required_correction_zh"],
                "deterministic_audit_passed": True,
            },
        ),
        output_dir=root / "independent-scientific-review",
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=review_max_tokens,
        temperature=0.2,
    )
    if final_review.generation_calls != 1 or final_review.plan_rewrite_performed:
        raise ContestDirectionTargetedScientificRepairError(
            "v5 finalization requires one fresh non-rewriting review"
        )
    status: Literal["completed", "blocked_after_independent_review"] = (
        "completed"
        if final_review.review.recommendation == "pass"
        else "blocked_after_independent_review"
    )
    report = _finalized_v5_report(
        root=root,
        status=status,
        sources=sources,
        v4=v4,
        v5=v5,
        audit_path=audit_path,
        audit=audit_payload,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        final_review=final_review,
    )
    report_path = root / "delivery-report-v2.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_repair_sources(v1_root: Path, v2_root: Path, v3_root: Path) -> _RepairSources:
    v1 = _load_source_bundle(v1_root)
    v2 = _load_prior_amendment_attempt(v2_root, v1)
    v3 = _load_failed_attempt(
        root=v3_root,
        bundle=v1,
        original=v2.plan,
        expected_version="v3",
    )
    review_path = v3_root / "independent-scientific-review" / "system-plan-scientific-review.json"
    try:
        v3_review = load_contest_direct_plan_scientific_review(review_path, verify_files=True)
    except Exception as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"v3 free-form review artifact does not replay: {exc}"
        ) from exc
    rendered_plan = v3_root / "plan" / "research-plan.json"
    if (
        v3_review.review.recommendation != "pass"
        or v3_review.final_plan_source_file_sha256 != _sha256_file(rendered_plan)
        or v3_review.prior_audit_context_supplied is not True
    ):
        raise ContestDirectionTargetedScientificRepairError(
            "v3 review is not the preserved rubber-stamp failure under program audit"
        )
    return _RepairSources(v1=v1, v2=v2, v3=v3, v3_review=v3_review)


def _load_v4_repair_attempt(root: Path, sources: _RepairSources) -> _V4RepairAttempt:
    report_path = root / "delivery-report.json"
    plan_path = root / "system-authored-targeted-research-plan.json"
    audit_path = root / "targeted-scientific-repair-audit.json"
    try:
        report = _read_json(report_path)
        plan = ContestDirectPlanRevisionArtifact.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
        audit = _read_json(audit_path)
    except Exception as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"v4 targeted repair cannot be replayed: {exc}"
        ) from exc
    if (
        report.get("schema_version") != "contest-direction-targeted-scientific-repair-delivery-v1"
        or report.get("status") != "blocked_after_targeted_scientific_audit"
        or report.get("amendment_version") != "v4"
        or report.get("model_call_accounting", {}).get("total_new_provider_requests") != 1
    ):
        raise ContestDirectionTargetedScientificRepairError(
            "v4 is not the expected one-call audit-blocked repair"
        )
    inventory = _file_inventory(root)
    inventory_without_report = [
        item for item in inventory if item.get("relative_path") != "delivery-report.json"
    ]
    if inventory_without_report != report.get("file_inventory") or canonical_model_hash(
        {"files": inventory_without_report}
    ) != report.get("file_inventory_hash"):
        raise ContestDirectionTargetedScientificRepairError("v4 inventory does not replay")
    if (
        plan.original_plan_id != sources.v3.plan.revision_id
        or plan.original_plan_artifact_hash != sources.v3.plan.artifact_hash
        or plan.scientific_problem != sources.v1.direction
    ):
        raise ContestDirectionTargetedScientificRepairError(
            "v4 repair is not bound to the verified v3 revision"
        )
    _verify_revision_sidecars(root / "repair", plan)
    if (
        audit.get("artifact_hash")
        != canonical_model_hash(
            {key: value for key, value in audit.items() if key != "artifact_hash"}
        )
        or audit.get("repaired_artifact_hash") != plan.artifact_hash
    ):
        raise ContestDirectionTargetedScientificRepairError("v4 audit hash mismatch")
    current_checks = _audit_amended_plan(plan)
    current_failures = {item.finding_id for item in current_checks if not item.passed}
    if not current_failures.issubset({"RT-06"}):
        raise ContestDirectionTargetedScientificRepairError(
            "v4 has a scientific failure outside the authorized RT-06 repair scope"
        )
    return _V4RepairAttempt(
        root=root,
        report_path=report_path,
        report=report,
        plan_path=plan_path,
        plan=plan,
        audit_path=audit_path,
        audit=audit,
    )


def _load_v5_blocked_attempt(
    root: Path,
    sources: _RepairSources,
    v4: _V4RepairAttempt,
) -> _V4RepairAttempt:
    report_path = root / "delivery-report.json"
    plan_path = root / "system-authored-targeted-research-plan.json"
    audit_path = root / "targeted-scientific-repair-audit.json"
    try:
        report = _read_json(report_path)
        plan = ContestDirectPlanRevisionArtifact.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
        audit = _read_json(audit_path)
    except Exception as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"v5 blocked attempt cannot be replayed: {exc}"
        ) from exc
    if (
        report.get("status") != "blocked_after_targeted_scientific_audit"
        or report.get("amendment_version") != "v5"
        or report.get("model_call_accounting", {}).get("total_new_provider_requests") != 1
        or plan.original_plan_id != v4.plan.revision_id
        or plan.original_plan_artifact_hash != v4.plan.artifact_hash
        or plan.scientific_problem != sources.v1.direction
    ):
        raise ContestDirectionTargetedScientificRepairError(
            "v5 is not the expected one-call repair derived from v4"
        )
    inventory = _file_inventory(root)
    inventory_without_report = [
        item for item in inventory if item.get("relative_path") != "delivery-report.json"
    ]
    if inventory_without_report != report.get("file_inventory") or canonical_model_hash(
        {"files": inventory_without_report}
    ) != report.get("file_inventory_hash"):
        raise ContestDirectionTargetedScientificRepairError("v5 inventory does not replay")
    _verify_revision_sidecars(root / "repair", plan)
    if (
        audit.get("artifact_hash")
        != canonical_model_hash(
            {key: value for key, value in audit.items() if key != "artifact_hash"}
        )
        or audit.get("repaired_artifact_hash") != plan.artifact_hash
    ):
        raise ContestDirectionTargetedScientificRepairError("v5 original audit hash mismatch")
    return _V4RepairAttempt(
        root=root,
        report_path=report_path,
        report=report,
        plan_path=plan_path,
        plan=plan,
        audit_path=audit_path,
        audit=audit,
    )


def _load_failed_attempt(
    *,
    root: Path,
    bundle: _SourceBundle,
    original: ContestDirectPlanRevisionArtifact,
    expected_version: str,
) -> _PriorAmendmentAttempt:
    input_path = root / "amendment-input.json"
    plan_path = root / "system-authored-amended-research-plan.json"
    audit_path = root / "scientific-amendment-audit.json"
    findings_path = root / "scientific-red-team-findings.json"
    try:
        input_payload = _read_json(input_path)
        plan = ContestDirectPlanRevisionArtifact.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
        audit = _read_json(audit_path)
        findings = _read_json(findings_path)
    except Exception as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"failed amendment cannot be replayed: {exc}"
        ) from exc
    if input_payload.get("input_hash") != canonical_model_hash(
        {key: value for key, value in input_payload.items() if key != "input_hash"}
    ):
        raise ContestDirectionTargetedScientificRepairError("failed attempt input hash mismatch")
    if input_payload.get("amendment_version") != expected_version:
        raise ContestDirectionTargetedScientificRepairError("failed attempt version mismatch")
    if (
        plan.original_plan_id != original.revision_id
        or plan.original_plan_artifact_hash != original.artifact_hash
        or plan.scientific_problem != bundle.direction
    ):
        raise ContestDirectionTargetedScientificRepairError(
            "failed attempt is not bound to the expected prior revision"
        )
    _verify_revision_sidecars(root / "revision", plan)
    if (
        audit.get("artifact_hash")
        != canonical_model_hash(
            {key: value for key, value in audit.items() if key != "artifact_hash"}
        )
        or audit.get("amendment_artifact_hash") != plan.artifact_hash
    ):
        raise ContestDirectionTargetedScientificRepairError("failed attempt audit hash mismatch")
    if audit.get("all_required_corrections_passed") is not False:
        raise ContestDirectionTargetedScientificRepairError("prior attempt was not audit-blocked")
    if findings.get("artifact_hash") != canonical_model_hash(
        {key: value for key, value in findings.items() if key != "artifact_hash"}
    ):
        raise ContestDirectionTargetedScientificRepairError("failed findings hash mismatch")
    responses = tuple(sorted((root / "independent-scientific-review" / "responses").glob("*.txt")))
    interactions = tuple(
        sorted((root / "independent-scientific-review" / "interactions").glob("*.json"))
    )
    if len(responses) != 1 or len(interactions) != 1:
        raise ContestDirectionTargetedScientificRepairError(
            "failed attempt must retain exactly one review response and receipt"
        )
    return _PriorAmendmentAttempt(
        root=root,
        input_path=input_path,
        plan_path=plan_path,
        plan=plan,
        audit_path=audit_path,
        audit=audit,
        findings_path=findings_path,
        findings=findings,
        review_response_path=responses[0],
        review_interaction_path=interactions[0],
    )


def _build_repair_messages(
    *,
    plan: ContestDirectRevisedScientificPlan,
    repair_context: Mapping[str, Any],
    repair_fields: Sequence[str] = _REPAIR_FIELDS,
    frozen_fields: Sequence[str] = _FROZEN_FIELDS,
    amendment_version: str = "v4",
) -> list[dict[str, str]]:
    if amendment_version == "v5":
        mandatory_corrections = [
            "在paper_abstract、results、limitations中明确写出：每个standardized_effect/z"
            "只是在本次有限simulation null SD下的模拟诊断，非population effect size，"
            "也不是总体效应估计。",
            "把‘大部分结构可由模30/210解释’等因果式表述改为：在更强约束零模型下，"
            "描述性熵缺口大幅缩小，这与算术约束有贡献相容，但不能作因果分解、"
            "解释比例或证明残差机制。",
            "limitations中的正式协议只写四模型各999 draws、+1 Monte Carlo p、"
            "four-model Holm与目标adjusted p<0.01；不得混称Bonferroni/Holm。",
            "保持所有真实数字不变；不得改写已冻结的wheel、分析单位、方法、指标、"
            "假设、数据或文献字段。",
        ]
    else:
        mandatory_corrections = [
            "删除七字段中所有‘仅保留模算术约束’、‘消除所有其他结构’、"
            "‘解释力边界/上限’等错误断言。wheel-210只准确描述每100000宽"
            "数轴段保留观察点数和首末端点、从与210互素候选点无放回抽取；"
            "它还保留这些非模结构，不是纯模零模型，也不保持原gap频率。",
            "明确说明pilot分析单位是5个宽10^6的固定数轴整数区间、每区间"
            "56359—70434个gap；正式实验另行定义的每块10^6个连续素数是"
            "不同分析单位，二者不能混同或互换。",
            "在结果与局限中明确：z只是在有限simulation null SD下的模拟诊断，"
            "不是population effect size或总体效应量；不得出现90%解释断言。",
            "保留199 draws、raw p=0.005、四模型Holm=0.02和alpha=0.05"
            "探索性边界；正式协议仍是四模型各999 draws、+1 p、Holm、"
            "目标adjusted p<0.01，不能写成已经执行。",
        ]
    return [
        {
            "role": "system",
            "content": (
                "你是证据优先的科研计划修订者。本次只修复已经定位的科学错误，不重写"
                "题目、假设、数据、指标或文献。逐字段返回完整替换文本，不输出思考过程。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "complete_prior_plan_with_program_frozen_fields",
                    "complete_plan": plan.model_dump(mode="json"),
                    "replace_exactly_these_fields": list(repair_fields),
                    "program_frozen_fields": list(frozen_fields),
                    "boundary_zh": (
                        "只返回指定替换字段；每个字段都必须是可直接替换原字段的完整中文"
                        "文本。不得更改或重复返回冻结字段。"
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
                    "context_kind": "exact_verified_scientific_repair_context",
                    **dict(repair_context),
                    "mandatory_corrections_zh": mandatory_corrections,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "single_local_repair_output_contract",
                    "required_fields": list(repair_fields),
                    "instructions_zh": [
                        "所有值均为非空字符串，不要返回补丁、数组或额外字段",
                        "这是唯一一次修订调用；直接输出一个JSON object",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _repair_response_schema(
    *,
    repair_fields: Sequence[str] = _REPAIR_FIELDS,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {field: {"type": "string", "minLength": 1} for field in repair_fields},
        "required": list(repair_fields),
        "additionalProperties": False,
    }


def _normalize_repair_payload(
    payload: Mapping[str, Any],
    *,
    repair_fields: Sequence[str] = _REPAIR_FIELDS,
) -> dict[str, str]:
    aliases = {
        "摘要": "paper_abstract",
        "技术细节": "technical_details",
        "方法": "methods",
        "实验设计": "experiments",
        "基线": "baselines",
        "结果": "results",
        "局限": "limitations",
    }
    projected: dict[str, Any] = dict(payload)
    for alias, field in aliases.items():
        if field not in projected and alias in projected:
            projected[field] = projected[alias]
    result: dict[str, str] = {}
    for field in repair_fields:
        value = projected.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ContestDirectionTargetedScientificRepairError(
                f"one-shot local repair omitted nonempty field: {field}"
            )
        result[field] = value.strip()
    return result


def _merge_frozen_plan(
    original: ContestDirectRevisedScientificPlan,
    replacements: Mapping[str, str],
    *,
    frozen_fields: Sequence[str] = _FROZEN_FIELDS,
) -> ContestDirectRevisedScientificPlan:
    payload = original.model_dump(mode="json")
    payload.update(replacements)
    try:
        merged = ContestDirectRevisedScientificPlan.model_validate(payload)
    except ValidationError as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"local repair fields are not valid Chinese plan prose: {exc}"
        ) from exc
    if any(getattr(merged, field) != getattr(original, field) for field in frozen_fields):
        raise ContestDirectionTargetedScientificRepairError(
            "program merge changed a frozen scientific field"
        )
    return merged


def _build_repair_artifact(
    *,
    repair_root: Path,
    repair_id: str,
    input_hash: str,
    response_hash: str,
    receipt_path: Path,
    receipt_hash: str,
    completion: LLMJsonCompletionResult,
    plan: ContestDirectRevisedScientificPlan,
    original: ContestDirectPlanRevisionArtifact,
    repair_context_hash: str,
    response_path: Path,
) -> ContestDirectPlanRevisionArtifact:
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-plan-revision-v1",
        "document_type": "含真实预实验结果的科学假设与研究计划",
        "revision_id": repair_id,
        "status": "revised_from_verified_preexperiment",
        "scientific_problem": original.scientific_problem,
        "original_plan_id": original.revision_id,
        "original_plan_artifact_hash": original.artifact_hash,
        "preexperiment_artifact_sha256": original.preexperiment_artifact_sha256,
        "preexperiment_metrics_sha256": original.preexperiment_metrics_sha256,
        "verified_files": [item.model_dump(mode="json") for item in original.verified_files],
        "verified_files_sha256": original.verified_files_sha256,
        "verified_revision_context_sha256": repair_context_hash,
        "plan": plan.model_dump(mode="json"),
        "provider": completion.provider,
        "model_name": completion.model_name,
        "generation_calls": 1,
        "input_hash": input_hash,
        "model_response_hash": response_hash,
        "raw_response_relative_path": response_path.relative_to(repair_root).as_posix(),
        "authorship_receipt_relative_path": receipt_path.relative_to(repair_root).as_posix(),
        "authorship_receipt_hash": receipt_hash,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    artifact = ContestDirectPlanRevisionArtifact.model_validate(payload)
    if artifact.raw_response_relative_path.startswith("../"):
        raise ContestDirectionTargetedScientificRepairError("repair response escaped repair root")
    return artifact


def _write_blocked_report(
    *,
    root: Path,
    sources: _RepairSources,
    context_path: Path,
    repaired_path: Path,
    repaired: ContestDirectPlanRevisionArtifact,
    audit_path: Path,
    audit: Mapping[str, Any],
    amendment_version: str = "v4",
    v4: _V4RepairAttempt | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "contest-direction-targeted-scientific-repair-delivery-v1",
        "status": "blocked_after_targeted_scientific_audit",
        "amendment_version": amendment_version,
        "direction": sources.v1.direction,
        "model_call_accounting": {
            "targeted_repair_calls": 1,
            "fresh_independent_review_calls": 0,
            "total_new_provider_requests": 1,
            "content_retry_calls": 0,
        },
        "prior_attempt_provider_calls_replayed": 0,
        "preexperiment_rerun": False,
        "artifacts": {
            "repair_input": _file_binding(context_path),
            "repaired_plan": {
                **_file_binding(repaired_path),
                "revision_id": repaired.revision_id,
                "artifact_hash": repaired.artifact_hash,
            },
            "deterministic_audit": {
                **_file_binding(audit_path),
                "artifact_hash": audit["artifact_hash"],
            },
        },
        "failed_finding_ids": [
            item["finding_id"] for item in audit["checks"] if not item["passed"]
        ],
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    if v4 is not None:
        report["source_v4"] = {
            "report": _file_binding(v4.report_path),
            "plan": _file_binding(v4.plan_path),
            "plan_artifact_hash": v4.plan.artifact_hash,
            "audit": _file_binding(v4.audit_path),
            "provider_calls_replayed": 0,
        }
    report["file_inventory"] = _file_inventory(root)
    report["file_inventory_hash"] = canonical_model_hash({"files": report["file_inventory"]})
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _write_completed_report(
    *,
    root: Path,
    status: str,
    sources: _RepairSources,
    context_path: Path,
    repaired_path: Path,
    repaired: ContestDirectPlanRevisionArtifact,
    audit_path: Path,
    audit: Mapping[str, Any],
    rendered: ContestDirectPlanArtifacts,
    page_count: int,
    page_count_method: str,
    final_review: ContestDirectPlanScientificReviewArtifact,
    amendment_version: str = "v4",
    v4: _V4RepairAttempt | None = None,
) -> dict[str, Any]:
    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    report: dict[str, Any] = {
        "schema_version": "contest-direction-targeted-scientific-repair-delivery-v1",
        "status": status,
        "amendment_version": amendment_version,
        "direction": sources.v1.direction,
        "source_lineage": {
            "v1_revision_id": sources.v1.plan.revision_id,
            "v2_failed_revision_id": sources.v2.plan.revision_id,
            "v3_failed_revision_id": sources.v3.plan.revision_id,
            "v4_failed_revision_id": v4.plan.revision_id if v4 is not None else None,
            f"{amendment_version}_repaired_revision_id": repaired.revision_id,
            "pilot_run_id": sources.v1.pilot.run_id,
            "pilot_artifact_hash": sources.v1.pilot.artifact_hash,
            "retrieval_rerun": False,
            "skill_routing_rerun": False,
            "hypothesis_rerun": False,
            "preexperiment_rerun": False,
            "prior_provider_calls_replayed": 0,
        },
        "model_call_accounting": {
            "targeted_repair_calls": repaired.generation_calls,
            "fresh_independent_review_calls": final_review.generation_calls,
            "total_new_provider_requests": repaired.generation_calls
            + final_review.generation_calls,
            "content_retry_calls": 0,
        },
        "scientific_audit": {
            "artifact_hash": audit["artifact_hash"],
            "all_required_corrections_passed": audit["all_required_corrections_passed"],
            "frozen_fields_verified": audit["frozen_fields_verified"],
            "review_recommendation": final_review.review.recommendation,
            "review_received_red_team_findings": final_review.prior_audit_context_supplied,
            "finding_ids_program_bound": (
                ["RT-06"] if amendment_version == "v5" else ["RT-02", "RT-05", "RT-06"]
            ),
            "reviewer_id_echo_required": False,
        },
        "artifacts": {
            "repair_input": _file_binding(context_path),
            "repaired_plan": {
                **_file_binding(repaired_path),
                "revision_id": repaired.revision_id,
                "artifact_hash": repaired.artifact_hash,
            },
            "deterministic_audit": {
                **_file_binding(audit_path),
                "artifact_hash": audit["artifact_hash"],
            },
            "rendered_plan": {
                "json": _file_binding(rendered.json_path),
                "markdown": _file_binding(rendered.markdown_path),
                "tex": _file_binding(rendered.tex_path),
                "pdf": _file_binding(rendered.pdf_path),
                "manifest": _file_binding(rendered.manifest_path),
            },
            "independent_scientific_review": {
                **_file_binding(review_path),
                "artifact_hash": final_review.artifact_hash,
            },
        },
        "pdf": {
            "path": rendered.pdf_path.as_posix(),
            "verified_page_count": page_count,
            "page_count_method": page_count_method,
            "maximum_allowed_pages": 20,
        },
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    report["file_inventory"] = _file_inventory(root)
    report["file_inventory_hash"] = canonical_model_hash({"files": report["file_inventory"]})
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _finalized_v5_report(
    *,
    root: Path,
    status: str,
    sources: _RepairSources,
    v4: _V4RepairAttempt,
    v5: _V4RepairAttempt,
    audit_path: Path,
    audit: Mapping[str, Any],
    rendered: ContestDirectPlanArtifacts,
    page_count: int,
    page_count_method: str,
    final_review: ContestDirectPlanScientificReviewArtifact,
) -> dict[str, Any]:
    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    inventory = _file_inventory(root)
    return {
        "schema_version": "contest-direction-targeted-scientific-repair-delivery-v2",
        "status": status,
        "amendment_version": "v5",
        "direction": sources.v1.direction,
        "source_lineage": {
            "v1_revision_id": sources.v1.plan.revision_id,
            "v2_failed_revision_id": sources.v2.plan.revision_id,
            "v3_failed_revision_id": sources.v3.plan.revision_id,
            "v4_failed_revision_id": v4.plan.revision_id,
            "v5_revision_id": v5.plan.revision_id,
            "pilot_run_id": sources.v1.pilot.run_id,
            "pilot_artifact_hash": sources.v1.pilot.artifact_hash,
            "retrieval_rerun": False,
            "skill_routing_rerun": False,
            "hypothesis_rerun": False,
            "preexperiment_rerun": False,
            "repair_provider_replayed_during_reaudit": False,
        },
        "model_call_accounting": {
            "targeted_repair_calls": 1,
            "fresh_independent_review_calls": final_review.generation_calls,
            "total_v5_provider_requests": 1 + final_review.generation_calls,
            "finalization_new_provider_requests": final_review.generation_calls,
            "content_retry_calls": 0,
        },
        "scientific_audit": {
            "artifact_hash": audit["artifact_hash"],
            "all_required_corrections_passed": True,
            "review_recommendation": final_review.review.recommendation,
            "review_received_red_team_findings": final_review.prior_audit_context_supplied,
            "finding_ids_program_bound": ["RT-06"],
            "reviewer_id_echo_required": False,
            "previous_false_negative_preserved": _file_binding(v5.audit_path),
        },
        "artifacts": {
            "v5_model_authored_plan": {
                **_file_binding(v5.plan_path),
                "revision_id": v5.plan.revision_id,
                "artifact_hash": v5.plan.artifact_hash,
            },
            "deterministic_reaudit": {
                **_file_binding(audit_path),
                "artifact_hash": audit["artifact_hash"],
            },
            "rendered_plan": {
                "json": _file_binding(rendered.json_path),
                "markdown": _file_binding(rendered.markdown_path),
                "tex": _file_binding(rendered.tex_path),
                "pdf": _file_binding(rendered.pdf_path),
                "manifest": _file_binding(rendered.manifest_path),
            },
            "independent_scientific_review": {
                **_file_binding(review_path),
                "artifact_hash": final_review.artifact_hash,
            },
            "historical_blocked_report": _file_binding(v5.report_path),
        },
        "pdf": {
            "path": rendered.pdf_path.as_posix(),
            "verified_page_count": page_count,
            "page_count_method": page_count_method,
            "maximum_allowed_pages": 20,
        },
        "formal_experiment_executed": False,
        "paper_claimed": False,
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
    }


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ContestDirectionTargetedScientificRepairError(
            f"refusing to overwrite immutable repair evidence: {path}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从失败v3执行一次七字段科学修订；全RT审计通过后才物化与独立评审。"
    )
    parser.add_argument("--source-delivery", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument("--v2-attempt", type=Path, default=_DEFAULT_V2)
    parser.add_argument("--v3-attempt", type=Path, default=_DEFAULT_V3)
    parser.add_argument(
        "--v4-attempt",
        type=Path,
        default=None,
        help=f"可选的失败v4目录；提供时只修RT-06（常用路径：{_DEFAULT_V4}）。",
    )
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--repair-max-tokens", type=int, default=7_000)
    parser.add_argument("--review-max-tokens", type=int, default=8_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help="不调用repair模型；对现有v5字节重新科学审计、物化并做一次独立评审。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.finalize_existing:
        report = finalize_existing_contest_direction_targeted_repair(
            source_delivery_dir=args.source_delivery,
            v2_attempt_dir=args.v2_attempt,
            v3_attempt_dir=args.v3_attempt,
            v4_attempt_dir=args.v4_attempt or _DEFAULT_V4,
            v5_attempt_dir=args.output_dir,
            config_path=args.config,
            env_path=args.env,
            review_max_tokens=args.review_max_tokens,
            timeout_seconds=args.timeout_seconds,
            render_timeout_seconds=args.render_timeout_seconds,
        )
    else:
        report = run_contest_direction_targeted_scientific_repair(
            source_delivery_dir=args.source_delivery,
            v2_attempt_dir=args.v2_attempt,
            v3_attempt_dir=args.v3_attempt,
            v4_attempt_dir=args.v4_attempt,
            output_dir=args.output_dir,
            config_path=args.config,
            env_path=args.env,
            repair_max_tokens=args.repair_max_tokens,
            review_max_tokens=args.review_max_tokens,
            timeout_seconds=args.timeout_seconds,
            render_timeout_seconds=args.render_timeout_seconds,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ContestDirectionTargetedScientificRepairError",
    "finalize_existing_contest_direction_targeted_repair",
    "main",
    "run_contest_direction_targeted_scientific_repair",
]
