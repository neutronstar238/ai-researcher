"""Versioned scientific amendment of one completed direction-plan delivery.

This command never reruns retrieval, Skill routing, hypothesis generation, or the
real pilot.  It verifies the complete v1 delivery, asks the configured model for
exactly one evidence-bound amendment, materializes it in a new directory, and
dispatches exactly one fresh reviewer with the deterministic red-team findings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
    revise_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_scientific_review import (
    ContestDirectPlanScientificReviewArtifact,
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
from autoresearch.competition.contest_plan_embedded_evidence import (
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    load_contest_prime_preexperiment,
)
from autoresearch.competition.contest_reference_policy import validate_locked_bibliography
from autoresearch.competition.manifest import canonical_model_hash

_DEFAULT_SOURCE = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v1")
_DEFAULT_OUTPUT = Path("runs/contest-delivery/direction-prime-gap-evidence-first-live-v2")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContestDirectionScientificAmendmentError(RuntimeError):
    """Raised when a versioned amendment cannot be produced truthfully."""


@dataclass(frozen=True)
class _SourceBundle:
    root: Path
    report_path: Path
    report: dict[str, Any]
    direction: str
    plan_path: Path
    plan: ContestDirectPlanRevisionArtifact
    pilot_root: Path
    pilot_path: Path
    pilot: ContestPrimePreexperimentArtifact
    references: tuple[str, ...]
    skill_contexts: tuple[dict[str, str], ...]
    source_code_sha256: str


@dataclass(frozen=True)
class _PriorAmendmentAttempt:
    root: Path
    input_path: Path
    plan_path: Path
    plan: ContestDirectPlanRevisionArtifact
    audit_path: Path
    audit: dict[str, Any]
    findings_path: Path
    findings: dict[str, Any]
    review_response_path: Path
    review_interaction_path: Path


@dataclass(frozen=True)
class _AuditCheck:
    finding_id: str
    passed: bool
    assessment: str


def run_contest_direction_scientific_amendment(
    *,
    source_delivery_dir: Path | str,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    plan_max_tokens: int = 12_000,
    review_max_tokens: int = 8_000,
    timeout_seconds: int = 900,
    render_timeout_seconds: int = 180,
    prior_amendment_dir: Path | str | None = None,
    source_loader: Callable[[Path], _SourceBundle] | None = None,
    prior_loader: Callable[[Path, _SourceBundle], _PriorAmendmentAttempt] | None = None,
    revision_runner: Callable[..., ContestDirectPlanRevisionArtifact] = (
        revise_contest_direct_plan
    ),
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
    review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact] = (
        review_contest_direct_plan_science
    ),
) -> dict[str, Any]:
    """Create one immutable v2 amendment from a fully verified v1 delivery."""

    source = Path(source_delivery_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    if source == root:
        raise ContestDirectionScientificAmendmentError(
            "amendment output must not overwrite the source delivery"
        )
    if root.exists() and any(root.iterdir()):
        raise ContestDirectionScientificAmendmentError(
            f"amendment output directory must be empty: {root}"
        )
    prior_root = (
        Path(prior_amendment_dir).expanduser().resolve()
        if prior_amendment_dir is not None
        else None
    )
    if prior_root is not None and prior_root in {source, root}:
        raise ContestDirectionScientificAmendmentError(
            "prior amendment must differ from source and output directories"
        )
    root.mkdir(parents=True, exist_ok=True)
    bundle = (source_loader or _load_source_bundle)(source)
    prior = (
        (prior_loader or _load_prior_amendment_attempt)(prior_root, bundle)
        if prior_root is not None
        else None
    )
    amendment_version = "v3" if prior is not None else "v2"
    original_plan = prior.plan if prior is not None else bundle.plan
    active_finding_ids = (
        ("RT-02", "RT-05", "RT-06")
        if prior is not None
        else tuple(f"RT-{index:02d}" for index in range(1, 8))
    )

    input_payload: dict[str, Any] = {
        "schema_version": "contest-direction-scientific-amendment-input-v1",
        "amendment_version": amendment_version,
        "direction": bundle.direction,
        "source_delivery": _file_binding(bundle.report_path),
        "source_delivery_inventory_hash": bundle.report["file_inventory_hash"],
        "source_v1_plan": {
            **_file_binding(bundle.plan_path),
            "revision_id": bundle.plan.revision_id,
            "artifact_hash": bundle.plan.artifact_hash,
        },
        "verified_pilot": {
            **_file_binding(bundle.pilot_path),
            "run_id": bundle.pilot.run_id,
            "artifact_hash": bundle.pilot.artifact_hash,
            "metrics_sha256": bundle.pilot.metrics_sha256,
            "manifest_sha256": bundle.pilot.manifest_sha256,
            "runner_code_sha256": bundle.source_code_sha256,
        },
        "model_call_contract": {
            "research_plan_amendment_calls": 1,
            "fresh_independent_review_calls": 1,
            "retrieval_calls": 0,
            "skill_routing_calls": 0,
            "hypothesis_calls": 0,
            "preexperiment_calls": 0,
        },
        "active_scientific_finding_ids": list(active_finding_ids),
    }
    if prior is not None:
        input_payload["prior_failed_amendment_attempt"] = {
            "input": _file_binding(prior.input_path),
            "plan": {
                **_file_binding(prior.plan_path),
                "revision_id": prior.plan.revision_id,
                "artifact_hash": prior.plan.artifact_hash,
            },
            "deterministic_audit": {
                **_file_binding(prior.audit_path),
                "artifact_hash": prior.audit["artifact_hash"],
                "failed_finding_ids": [
                    item["finding_id"] for item in prior.audit["checks"] if not item["passed"]
                ],
            },
            "failed_review_response": _file_binding(prior.review_response_path),
            "failed_review_interaction": _file_binding(prior.review_interaction_path),
            "reuse_policy": "evidence_only_no_provider_call_replay",
        }
    input_payload["input_hash"] = canonical_model_hash(input_payload)
    input_path = root / "amendment-input.json"
    _write_new_json(input_path, input_payload)

    findings = _build_red_team_findings(bundle, prior_attempt=prior)
    findings_path = root / "scientific-red-team-findings.json"
    _write_new_json(findings_path, findings)
    findings_for_model = {
        key: value
        for key, value in findings.items()
        if key not in {"artifact_hash", "source_paths"}
    }
    requirements = _amendment_requirements(
        findings,
        active_finding_ids=active_finding_ids,
    )

    amended_path = root / "system-authored-amended-research-plan.json"
    amended = revision_runner(
        original_plan=original_plan,
        scientific_problem=bundle.direction,
        requirements=requirements,
        selected_skill_contexts=bundle.skill_contexts,
        reference_catalog=bundle.references,
        preexperiment_artifact=bundle.pilot_path,
        preexperiment_metrics=None,
        preexperiment_root=bundle.pilot_root,
        verified_revision_context=findings_for_model,
        output_dir=root / "revision",
        output_path=amended_path,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=plan_max_tokens,
        temperature=0.2,
    )
    if amended.generation_calls != 1:
        raise ContestDirectionScientificAmendmentError(
            "scientific amendment must contain exactly one model revision call"
        )
    if amended.original_plan_id != original_plan.revision_id:
        raise ContestDirectionScientificAmendmentError(
            f"{amendment_version} amendment is not bound to its verified prior revision"
        )
    try:
        validate_locked_bibliography(amended.plan.references, bundle.references)
    except ValueError as exc:
        raise ContestDirectionScientificAmendmentError(
            f"{amendment_version} bibliography failed the locked 5–10 reference contract: {exc}"
        ) from exc
    expected_context_hash = canonical_model_hash(findings_for_model)
    if amended.verified_revision_context_sha256 != expected_context_hash:
        raise ContestDirectionScientificAmendmentError(
            "v2 amendment lost the verified red-team context binding"
        )

    checks = _audit_amended_plan(amended)
    audit_payload: dict[str, Any] = {
        "schema_version": "contest-direction-scientific-amendment-audit-v1",
        "amendment_artifact_hash": amended.artifact_hash,
        "red_team_findings_artifact_hash": findings["artifact_hash"],
        "checks": [check.__dict__ for check in checks],
        "all_required_corrections_passed": all(check.passed for check in checks),
        "audit_authorship": "deterministic_program_checks_not_scientific_prose",
    }
    audit_payload["artifact_hash"] = canonical_model_hash(audit_payload)
    audit_path = root / "scientific-amendment-audit.json"
    _write_new_json(audit_path, audit_payload)

    render_payload = amended.flat_payload()
    embedded_evidence = build_contest_plan_embedded_evidence(
        bundle.pilot,
        artifact_path=bundle.pilot_path,
        preexperiment_root=bundle.pilot_root,
    )
    if embedded_evidence is not None:
        render_payload["embedded_evidence"] = embedded_evidence.payload
    render_payload.update(
        {
            "document_type": (
                f"含真实探索性预实验结果的科学研究计划（科学修订{amendment_version}）"
            ),
            "status": f"versioned_scientific_amendment_{amendment_version}",
            "specified_direction": bundle.direction,
            "amendment": {
                "source_v1_revision_id": bundle.plan.revision_id,
                "source_v1_artifact_hash": bundle.plan.artifact_hash,
                "immediate_prior_revision_id": original_plan.revision_id,
                "immediate_prior_artifact_hash": original_plan.artifact_hash,
                "amended_revision_id": amended.revision_id,
                "amended_artifact_hash": amended.artifact_hash,
                "red_team_findings_artifact_hash": findings["artifact_hash"],
                "deterministic_audit_artifact_hash": audit_payload["artifact_hash"],
            },
            "preexperiment": {
                "run_id": bundle.pilot.run_id,
                "artifact_hash": bundle.pilot.artifact_hash,
                "study_phase": bundle.pilot.study_phase,
                "reexecuted_for_amendment": False,
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
            "deterministic_audit_passed": next(
                check.passed for check in checks if check.finding_id == item["finding_id"]
            ),
        }
        for item in findings["findings"]
        if item["finding_id"] in active_finding_ids
    )
    final_review = review_runner(
        final_plan=rendered.json_path,
        preexperiment_artifact=bundle.pilot_path,
        reference_catalog=bundle.references,
        selected_skill_contexts=bundle.skill_contexts,
        preexperiment_metrics=None,
        preexperiment_root=bundle.pilot_root,
        required_audit_findings=review_findings,
        output_dir=root / "independent-scientific-review",
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=review_max_tokens,
        temperature=0.2,
    )
    if final_review.generation_calls != 1 or final_review.plan_rewrite_performed:
        raise ContestDirectionScientificAmendmentError(
            "v2 independent review must be one fresh non-rewriting call"
        )

    audit_passed = bool(audit_payload["all_required_corrections_passed"])
    review_passed = final_review.review.recommendation == "pass"
    if not audit_passed and review_passed:
        raise ContestDirectionScientificAmendmentError(
            "reviewer returned pass although deterministic scientific findings remain"
        )
    status: Literal["completed", "blocked_after_independent_review"] = (
        "completed" if audit_passed and review_passed else "blocked_after_independent_review"
    )
    report = _build_delivery_report(
        root=root,
        status=status,
        bundle=bundle,
        input_path=input_path,
        findings_path=findings_path,
        findings=findings,
        amended_path=amended_path,
        amended=amended,
        audit_path=audit_path,
        audit=audit_payload,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        final_review=final_review,
        amendment_version=amendment_version,
        prior=prior,
        active_finding_ids=active_finding_ids,
    )
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_source_bundle(source: Path) -> _SourceBundle:
    if not source.is_dir():
        raise ContestDirectionScientificAmendmentError(
            f"source delivery directory is missing: {source}"
        )
    report_path = source / "delivery-report.json"
    report = _read_json(report_path)
    if (
        report.get("schema_version") != "contest-direction-research-loop-delivery-v1"
        or report.get("status") != "completed"
        or report.get("preexperiment_executed") is not True
    ):
        raise ContestDirectionScientificAmendmentError(
            "source is not a completed real-preexperiment direction delivery"
        )
    inventory = _file_inventory(source)
    if inventory != report.get("file_inventory") or canonical_model_hash(
        {"files": inventory}
    ) != report.get("file_inventory_hash"):
        raise ContestDirectionScientificAmendmentError("source delivery inventory does not replay")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ContestDirectionScientificAmendmentError("source report lacks artifacts")
    plan_path = _bound_source_path(source, artifacts, "final_revised_plan_artifact")
    pilot_path = _bound_source_path(source, artifacts, "prime_preexperiment")
    skill_manifest_path = _bound_source_path(source, artifacts, "selected_method_skills")
    try:
        plan = ContestDirectPlanRevisionArtifact.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
        pilot = load_contest_prime_preexperiment(pilot_path, verify_files=True)
    except Exception as exc:
        raise ContestDirectionScientificAmendmentError(
            f"source scientific artifact validation failed: {exc}"
        ) from exc
    _verify_revision_sidecars(source / "revision", plan)
    direction = str(report.get("direction") or "").strip()
    if not direction or plan.scientific_problem != direction:
        raise ContestDirectionScientificAmendmentError("source direction and final v1 plan differ")
    if pilot.formal_experiment_executed or pilot.mathematical_proof_claimed:
        raise ContestDirectionScientificAmendmentError(
            "source pilot overstates formal execution or mathematical proof"
        )
    skill_contexts = _load_source_skills(skill_manifest_path)
    references = _merge_references(plan.plan.references, pilot.references)
    source_code_sha256 = _source_code_hash(pilot)
    return _SourceBundle(
        root=source,
        report_path=report_path,
        report=report,
        direction=direction,
        plan_path=plan_path,
        plan=plan,
        pilot_root=pilot_path.parent,
        pilot_path=pilot_path,
        pilot=pilot,
        references=references,
        skill_contexts=skill_contexts,
        source_code_sha256=source_code_sha256,
    )


def _load_prior_amendment_attempt(
    root: Path,
    bundle: _SourceBundle,
) -> _PriorAmendmentAttempt:
    """Replay one immutable failed amendment without treating it as delivery success."""

    if not root.is_dir():
        raise ContestDirectionScientificAmendmentError(
            f"prior amendment directory is missing: {root}"
        )
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
        raise ContestDirectionScientificAmendmentError(
            f"prior amendment scientific artifacts are invalid: {exc}"
        ) from exc
    if input_payload.get("input_hash") != canonical_model_hash(
        {key: value for key, value in input_payload.items() if key != "input_hash"}
    ):
        raise ContestDirectionScientificAmendmentError("prior amendment input hash mismatch")
    if input_payload.get("amendment_version") != "v2":
        raise ContestDirectionScientificAmendmentError(
            "prior attempt is not the expected v2 amendment"
        )
    if (
        plan.original_plan_id != bundle.plan.revision_id
        or plan.original_plan_artifact_hash != bundle.plan.artifact_hash
        or plan.scientific_problem != bundle.direction
    ):
        raise ContestDirectionScientificAmendmentError(
            "prior amendment is not derived from the verified v1 plan"
        )
    _verify_revision_sidecars(root / "revision", plan)
    expected_audit_hash = canonical_model_hash(
        {key: value for key, value in audit.items() if key != "artifact_hash"}
    )
    checks = audit.get("checks")
    if (
        audit.get("schema_version") != "contest-direction-scientific-amendment-audit-v1"
        or audit.get("artifact_hash") != expected_audit_hash
        or audit.get("amendment_artifact_hash") != plan.artifact_hash
        or audit.get("all_required_corrections_passed") is not False
        or not isinstance(checks, list)
        or not any(isinstance(item, Mapping) and item.get("passed") is False for item in checks)
    ):
        raise ContestDirectionScientificAmendmentError(
            "prior amendment is not a hash-valid failed deterministic audit"
        )
    expected_findings_hash = canonical_model_hash(
        {key: value for key, value in findings.items() if key != "artifact_hash"}
    )
    if (
        findings.get("artifact_hash") != expected_findings_hash
        or findings.get("source_v1_plan_artifact_hash") != bundle.plan.artifact_hash
        or findings.get("verified_pilot_artifact_hash") != bundle.pilot.artifact_hash
    ):
        raise ContestDirectionScientificAmendmentError(
            "prior red-team findings do not replay against v1 evidence"
        )
    response_paths = tuple(
        sorted((root / "independent-scientific-review" / "responses").glob("*.txt"))
    )
    interaction_paths = tuple(
        sorted((root / "independent-scientific-review" / "interactions").glob("*.json"))
    )
    if len(response_paths) != 1 or len(interaction_paths) != 1:
        raise ContestDirectionScientificAmendmentError(
            "prior failed review must retain exactly one response and one interaction receipt"
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
        review_response_path=response_paths[0],
        review_interaction_path=interaction_paths[0],
    )


def _bound_source_path(
    source: Path,
    artifacts: Mapping[str, Any],
    name: str,
) -> Path:
    binding = artifacts.get(name)
    if not isinstance(binding, Mapping):
        raise ContestDirectionScientificAmendmentError(
            f"source report lacks artifact binding: {name}"
        )
    raw_path = binding.get("path")
    if not isinstance(raw_path, str):
        raise ContestDirectionScientificAmendmentError(
            f"source artifact binding lacks path: {name}"
        )
    path = Path(raw_path).resolve()
    try:
        path.relative_to(source)
    except ValueError as exc:
        raise ContestDirectionScientificAmendmentError(
            f"source artifact escapes delivery root: {name}"
        ) from exc
    if (
        not path.is_file()
        or binding.get("sha256") != _sha256_file(path)
        or binding.get("size_bytes") != path.stat().st_size
    ):
        raise ContestDirectionScientificAmendmentError(
            f"source artifact binding does not replay: {name}"
        )
    return path


def _load_source_skills(path: Path) -> tuple[dict[str, str], ...]:
    manifest = _read_json(path)
    recorded = manifest.get("manifest_hash")
    expected = canonical_model_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    if recorded != expected:
        raise ContestDirectionScientificAmendmentError("source Skill manifest hash mismatch")
    rows = manifest.get("skills")
    if not isinstance(rows, list) or not rows:
        raise ContestDirectionScientificAmendmentError("source Skill manifest is empty")
    contexts: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ContestDirectionScientificAmendmentError("invalid source Skill row")
        skill_path = Path(str(row.get("path") or "")).resolve()
        content = skill_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != row.get("content_sha256"):
            raise ContestDirectionScientificAmendmentError(
                f"source Skill bytes changed: {row.get('skill_id')}"
            )
        contexts.append(
            {
                "skill_id": str(row.get("skill_id") or ""),
                "content": content,
            }
        )
    return tuple(contexts)


def _merge_references(
    v1_references: Sequence[str],
    pilot_references: Sequence[str],
) -> tuple[str, ...]:
    merged = tuple(
        dict.fromkeys(item.strip() for item in (*v1_references, *pilot_references) if item.strip())
    )
    required = ("Bandt", "Bian", "Lemke Oliver", "Banks", "Phipson")
    if any(not any(name in citation for citation in merged) for name in required):
        raise ContestDirectionScientificAmendmentError(
            "verified source catalogs lack a required primary method reference"
        )
    return merged


def _source_code_hash(pilot: ContestPrimePreexperimentArtifact) -> str:
    for item in pilot.evidence_files:
        if item.kind == "source_code":
            return item.sha256
    raise ContestDirectionScientificAmendmentError(
        "verified pilot does not bind the frozen runner source code"
    )


def _build_red_team_findings(
    bundle: _SourceBundle,
    *,
    prior_attempt: _PriorAmendmentAttempt | None = None,
) -> dict[str, Any]:
    pilot = bundle.pilot
    counts = [item.gap_count for item in pilot.interval_results]
    findings = [
        {
            "finding_id": "RT-01",
            "title": "残基路径条件置换的条件键",
            "required_correction_zh": (
                "逐字按runner说明条件键为(segment,left mod30,right mod30)，不得称其"
                "控制mod210；mod210只属于另一个wheel-210敏感性零模型。"
            ),
            "review_question_zh": "计划是否准确区分mod30残基路径置换与wheel-210？",
        },
        {
            "finding_id": "RT-02",
            "title": "wheel-210生成机制",
            "required_correction_zh": (
                "准确写明每100000宽数轴段保持观察点数、固定首末端点，并从与210互素"
                "的允许候选点中无放回抽取；不得称纯模零模型、保持原gap频率、解释力"
                "上界/边界，也不得声称仅保留模算术约束或消除所有其他结构。"
            ),
            "review_question_zh": "wheel-210的局部点数、端点和候选抽样是否准确？",
        },
        {
            "finding_id": "RT-03",
            "title": "探索性p值与正式Monte Carlo门",
            "required_correction_zh": (
                "pilot每零模型199 draws，aggregate raw p=0.005、四模型Holm=0.02，"
                "只按alpha=0.05探索性描述；正式四模型family采用999 draws、"
                "+1 Monte Carlo p与Holm，目标adjusted p<0.01。"
            ),
            "review_question_zh": "p值、Holm family、alpha和999 draws是否可达且一致？",
        },
        {
            "finding_id": "RT-04",
            "title": "含并列值的弱序秩模式",
            "required_correction_zh": (
                "指标使用由严格大于比较得到的weak-order rank pattern，m=5的模式总数"
                "为ordered Bell/Fubini(5)=541；不得写成ties等概率分摊到普通排列。"
            ),
            "review_question_zh": "weak-order编码、Fubini(5)=541和ties处理是否准确？",
        },
        {
            "finding_id": "RT-05",
            "title": "pilot与formal分析单位",
            "required_correction_zh": (
                f"pilot是5个数轴宽10^6的固定整数区间，每区间{min(counts)}—"
                f"{max(counts)}个gap；正式分析单位必须另行定义并明确不与pilot混同。"
            ),
            "review_question_zh": "是否区分整数区间宽度、gap数与正式分析单位？",
        },
        {
            "finding_id": "RT-06",
            "title": "simulation z诊断与因果边界",
            "required_correction_zh": (
                "standardized_effect字段只能称相对于有限simulation null SD的z诊断，"
                "不是population effect size；删除90%解释，或仅给明确定义的描述性"
                "gap-ratio公式且不得作因果解释。本次要求直接删除90%断言。"
            ),
            "review_question_zh": "z诊断是否被误称总体效应，90%因果断言是否删除？",
        },
        {
            "finding_id": "RT-07",
            "title": "锁定一手方法与素数来源",
            "required_correction_zh": (
                "只能从v1真实检索与pilot锁定目录选文献；至少引用Bandt-Pompe、Bian、"
                "Lemke Oliver-Soundararajan、Banks-Ford-Tao、Phipson-Smyth，"
                "并诚实说明这些来源不直接证明本计划的新残差信号。"
            ),
            "review_question_zh": "关键定义、残基偏差和+1 p是否各有真实直接来源？",
        },
    ]
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-scientific-red-team-findings-v1",
        "direction": bundle.direction,
        "source_v1_plan_artifact_hash": bundle.plan.artifact_hash,
        "verified_pilot_artifact_hash": pilot.artifact_hash,
        "verified_metrics_sha256": pilot.metrics_sha256,
        "verified_runner_code_sha256": bundle.source_code_sha256,
        "pilot_facts": {
            "null_draws_per_model": pilot.parameters.null_draws,
            "alpha": pilot.parameters.alpha,
            "wheel_modulus": pilot.parameters.wheel_modulus,
            "wheel_density_segment_width": pilot.parameters.wheel_density_segment_width,
            "residue_path_segment_size": pilot.parameters.residue_path_segment_size,
            "ordinal_dimension": pilot.parameters.ordinal_dimension,
            "ordered_bell_fubini_m5": 541,
            "aggregate_raw_p": sorted(
                {item.one_sided_empirical_p_lower for item in pilot.aggregate_results}
            ),
            "aggregate_holm_p_across_four_null_models": sorted(
                {item.holm_adjusted_p_across_null_models for item in pilot.aggregate_results}
            ),
            "fixed_number_line_intervals": [
                [item.start, item.stop] for item in pilot.interval_results
            ],
            "gap_count_range": [min(counts), max(counts)],
        },
        "formal_protocol_correction": {
            "null_model_family_size": 4,
            "null_draws_per_model": 999,
            "monte_carlo_p_formula": "(b+1)/(999+1)",
            "multiplicity": "Holm across the four null models",
            "target_adjusted_p": "<0.01",
            "mathematical_minimum_draws_for_strict_bonferroni_bound": 400,
        },
        "reference_catalog": list(bundle.references),
        "findings": findings,
        "source_paths": {
            "v1_plan": bundle.plan_path.as_posix(),
            "pilot": bundle.pilot_path.as_posix(),
        },
    }
    if prior_attempt is not None:
        payload["prior_failed_attempt"] = {
            "plan_revision_id": prior_attempt.plan.revision_id,
            "plan_artifact_hash": prior_attempt.plan.artifact_hash,
            "audit_artifact_hash": prior_attempt.audit["artifact_hash"],
            "program_detected_failures": [
                item["finding_id"] for item in prior_attempt.audit["checks"] if not item["passed"]
            ],
            "additional_human_red_team_failure": {
                "finding_id": "RT-02",
                "evidence": (
                    "prior plan said wheel-210 only retained modular constraints and eliminated "
                    "all other structure / used an explanatory-boundary interpretation"
                ),
            },
            "failed_review_response_sha256": _sha256_file(prior_attempt.review_response_path),
            "policy": "revise_only_RT-02_RT-05_RT-06_and_preserve_other_passed_corrections",
        }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return payload


def _amendment_requirements(
    findings: Mapping[str, Any],
    *,
    active_finding_ids: Sequence[str],
) -> tuple[str, ...]:
    items = findings.get("findings")
    if not isinstance(items, list):
        raise ContestDirectionScientificAmendmentError("red-team findings are malformed")
    requirements = [
        "输出完整中文科学研究计划，不是补丁；保留真实pilot结果但修正方法解释。",
        "只允许引用锁定目录编号，不得生成、改写或猜测目录外文献。",
        "Results只陈述真实pilot；999 draws等均为未来正式协议，不得冒充已执行。",
        "不同零模型回答不同问题，探索性统计不升级为确认性结论或数学证明。",
        "不得把v1终审pass当作事实；逐项实质解决以下RT findings。",
    ]
    active = set(active_finding_ids)
    if active == {"RT-02", "RT-05", "RT-06"}:
        requirements.extend(
            (
                "这是versioned v3：只改正RT-02、RT-05、RT-06的科学缺陷。",
                "冻结并完整保留上一版已经通过的RT-01、RT-03、RT-04、RT-07科学修正，"
                "不得重新引入mod30/210混淆、不可达p值门、错误ties处理或虚构文献。",
                "明确写出正式分析单位与pilot的宽10^6数轴区间是不同定义，不能互换。",
                "明确写出z仅为有限simulation null SD诊断、不是population effect size。",
                "wheel-210不得声称消除所有其他结构、仅保留模结构、纯模零模型、"
                "解释力边界/上限或保持原gap频率。",
            )
        )
    requirements.extend(
        f"[{item['finding_id']}] {item['required_correction_zh']}"
        for item in items
        if isinstance(item, Mapping) and item.get("finding_id") in active
    )
    return tuple(requirements)


def _audit_amended_plan(
    amended: ContestDirectPlanRevisionArtifact,
) -> tuple[_AuditCheck, ...]:
    plan = amended.plan
    all_text = "\n".join(
        str(value) for key, value in plan.model_dump(mode="json").items() if key != "references"
    )
    method_text = "\n".join(
        (
            plan.technical_details,
            plan.methods,
            plan.experiments,
            plan.baselines,
            plan.metrics,
            plan.datasets,
        )
    )
    results_text = "\n".join((plan.paper_abstract, plan.results, plan.limitations, plan.metrics))
    compact = re.sub(r"\s+", "", all_text).casefold()
    method_compact = re.sub(r"\s+", "", method_text).casefold()
    results_compact = re.sub(r"\s+", "", results_text).casefold()

    residue_mechanics = (
        ("segment" in method_compact or "分段" in method_compact)
        and ("left" in method_compact or "左端" in method_compact)
        and ("right" in method_compact or "右端" in method_compact)
        and ("mod30" in method_compact or "模30" in method_compact)
    )
    residue_bad = any(
        "残基路径" in clause
        and ("mod210" in clause.casefold() or "模210" in clause)
        and not any(marker in clause for marker in ("不是", "并非", "不等于", "区别"))
        for clause in re.split(r"[。；;\n]", method_text)
    )
    rt01 = residue_mechanics and not residue_bad

    wheel_clauses = "\n".join(
        clause
        for clause in re.split(r"[。；;\n]", method_text)
        if "wheel-210" in clause.casefold() or "wheel_210" in clause.casefold()
    )
    wheel_compact = re.sub(r"\s+", "", wheel_clauses).casefold()
    rt02 = (
        any(token in wheel_compact for token in ("100000", "100k", "10^5"))
        and "点数" in wheel_compact
        and "端点" in wheel_compact
        and "候选" in wheel_compact
        and any(token in wheel_compact for token in ("无放回", "抽取", "采样"))
        and not any(
            token in wheel_compact
            for token in (
                "纯模零模型",
                "解释力上界",
                "解释力边界",
                "保持原gap频率",
                "保持原始间隙频率",
                "仅保留模算术约束",
                "消除所有其他结构",
                "消除其他结构",
            )
        )
    )

    pilot_stats = (
        "199" in results_compact
        and "0.005" in results_compact
        and "holm" in results_compact
        and "0.02" in results_compact
        and any(token in results_compact for token in ("α=0.05", "alpha=0.05"))
        and "探索性" in results_compact
        and not any(token in results_compact for token in ("α=0.01校正显著", "alpha=0.01校正显著"))
    )
    formal_stats = (
        "999" in method_compact
        and "holm" in method_compact
        and any(token in method_compact for token in ("+1", "加一"))
        and "0.01" in method_compact
        and any(token in method_compact for token in ("四类零模型", "4类零模型", "四模型"))
    )
    formal_draw_contradiction = any(
        ("正式" in clause or "零模型" in clause)
        and re.search(r"(?<!\d)100(?!\d)(?:draws?|次)", re.sub(r"\s+", "", clause).casefold())
        for clause in re.split(r"[。；;\n]", method_text)
    )
    rt03 = pilot_stats and formal_stats and not formal_draw_contradiction

    rt04 = (
        any(token in method_compact for token in ("weak-order", "weakorder", "弱序"))
        and "fubini" in method_compact
        and "541" in method_compact
        and not re.search(r"并列.{0,12}等概率(?:分摊|分配)", method_compact)
    )

    pilot_units = (
        all(token in results_compact for token in ("56359", "70434", "10^6"))
        and any(token in results_compact for token in ("数轴", "整数区间"))
        and "间隙" in results_compact
    )
    formal_unit_boundary = "正式实验" in method_text and any(
        token in method_compact
        for token in (
            "不同于预实验",
            "不与预实验混同",
            "另行定义",
            "与预实验区分",
            "不可混同",
            "二者定义不同",
            "与pilot的固定数轴整数区间不同",
        )
    )
    rt05 = pilot_units and formal_unit_boundary

    z_boundary = (
        "z" in results_compact
        and (
            "模拟诊断" in results_compact
            or ("z诊断" in results_compact and "simulationnullsd" in results_compact)
        )
        and any(
            token in results_compact
            for token in (
                "非总体效应量",
                "不是总体效应量",
                "不代表总体效应量",
                "不是populationeffectsize",
                "非populationeffectsize",
            )
        )
    )
    rt06 = z_boundary and not any(
        token in compact for token in ("90%以上", "90%解释", "约90%", "百分之九十")
    )

    references_text = "\n".join(plan.references)
    required_references = ("Bandt", "Bian", "Lemke Oliver", "Banks", "Phipson")
    rt07 = all(name in references_text for name in required_references) and any(
        marker in all_text for marker in ("不直接证明", "不能直接证明", "不构成证明")
    )
    values = (rt01, rt02, rt03, rt04, rt05, rt06, rt07)
    assessments = (
        "residue-path key is segment/left mod30/right mod30 and not relabelled mod210",
        "wheel-210 preserves 100k-segment counts/endpoints and samples allowed candidates",
        "pilot 199/raw .005/Holm .02/alpha .05 and formal 999/+1/Holm/<.01 are explicit",
        "weak-order ranks use ordered Bell/Fubini(5)=541 without equal tie allocation",
        "five width-1e6 number-line intervals and gap counts differ from formal units",
        "simulation z is not a population effect and the 90-percent causal claim is absent",
        "locked primary method, residue-bias, prime-gap and +1-p sources are cited",
    )
    return tuple(
        _AuditCheck(finding_id=f"RT-{index:02d}", passed=passed, assessment=assessment)
        for index, (passed, assessment) in enumerate(zip(values, assessments, strict=True), start=1)
    )


def _build_delivery_report(
    *,
    root: Path,
    status: str,
    bundle: _SourceBundle,
    input_path: Path,
    findings_path: Path,
    findings: Mapping[str, Any],
    amended_path: Path,
    amended: ContestDirectPlanRevisionArtifact,
    audit_path: Path,
    audit: Mapping[str, Any],
    rendered: ContestDirectPlanArtifacts,
    page_count: int,
    page_count_method: str,
    final_review: ContestDirectPlanScientificReviewArtifact,
    amendment_version: str,
    prior: _PriorAmendmentAttempt | None,
    active_finding_ids: Sequence[str],
) -> dict[str, Any]:
    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    inventory = _file_inventory(root)
    report: dict[str, Any] = {
        "schema_version": "contest-direction-scientific-amendment-delivery-v1",
        "status": status,
        "amendment_version": amendment_version,
        "direction": bundle.direction,
        "source_v1": {
            "delivery_report": _file_binding(bundle.report_path),
            "inventory_hash": bundle.report["file_inventory_hash"],
            "plan_revision_id": bundle.plan.revision_id,
            "plan_artifact_hash": bundle.plan.artifact_hash,
            "pilot_run_id": bundle.pilot.run_id,
            "pilot_artifact_hash": bundle.pilot.artifact_hash,
            "retrieval_rerun": False,
            "skill_routing_rerun": False,
            "hypothesis_rerun": False,
            "preexperiment_rerun": False,
        },
        "model_call_accounting": {
            "scientific_amendment_calls": amended.generation_calls,
            "fresh_independent_review_calls": final_review.generation_calls,
            "total_new_provider_requests": amended.generation_calls + final_review.generation_calls,
            "content_retry_calls": 0,
        },
        "scientific_audit": {
            "artifact_hash": audit["artifact_hash"],
            "all_required_corrections_passed": audit["all_required_corrections_passed"],
            "review_recommendation": final_review.review.recommendation,
            "review_received_red_team_findings": final_review.prior_audit_context_supplied,
            "active_finding_ids": list(active_finding_ids),
        },
        "artifacts": {
            "amendment_input": _file_binding(input_path),
            "red_team_findings": {
                **_file_binding(findings_path),
                "artifact_hash": findings["artifact_hash"],
            },
            "amended_plan": {
                **_file_binding(amended_path),
                "revision_id": amended.revision_id,
                "artifact_hash": amended.artifact_hash,
            },
            "deterministic_scientific_audit": {
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
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
    }
    if prior is not None:
        report["prior_failed_amendment_attempt"] = {
            "root": prior.root.as_posix(),
            "plan": {
                **_file_binding(prior.plan_path),
                "revision_id": prior.plan.revision_id,
                "artifact_hash": prior.plan.artifact_hash,
            },
            "deterministic_audit": {
                **_file_binding(prior.audit_path),
                "artifact_hash": prior.audit["artifact_hash"],
            },
            "review_response": _file_binding(prior.review_response_path),
            "provider_calls_replayed": 0,
        }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从完整验证的v1研究计划与真实pilot生成一次版本化科学修订，并执行一次"
            "收到红队findings的fresh独立终审。"
        )
    )
    parser.add_argument("--source-delivery", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument(
        "--prior-amendment",
        type=Path,
        default=None,
        help="可选的失败v2目录；提供时只读重放并生成versioned v3。",
    )
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--plan-max-tokens", type=int, default=12_000)
    parser.add_argument("--review-max-tokens", type=int, default=8_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_direction_scientific_amendment(
        source_delivery_dir=args.source_delivery,
        output_dir=args.output_dir,
        config_path=args.config,
        env_path=args.env,
        plan_max_tokens=args.plan_max_tokens,
        review_max_tokens=args.review_max_tokens,
        timeout_seconds=args.timeout_seconds,
        render_timeout_seconds=args.render_timeout_seconds,
        prior_amendment_dir=args.prior_amendment,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ContestDirectionScientificAmendmentError",
    "main",
    "run_contest_direction_scientific_amendment",
]
