"""Deterministic, serial batch service for the Science 125 plan-only scope.

The source PDF, not a model, defines the 125 questions.  Each selected question
gets an isolated attempt/checkpoint directory.  The default path runs the full
evidence-first direction loop and, when no compatible real pilot adapter exists,
continues from its real retrieval, Skill routing and hypothesis artifacts to a
Chinese plan-only delivery.  Formal experiments and result papers are explicitly
outside this batch contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from autoresearch.competition.contest_direct_plan import (
    contest_direct_plan_template_payload,
    generate_contest_direct_plan,
    load_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_skill_router import (
    load_contest_direct_skill_routing,
)
from autoresearch.competition.contest_direction_context_runtime import (
    ContestDirectionContextRuntime,
)
from autoresearch.competition.contest_direction_hypothesis_stage import (
    load_contest_direction_hypothesis_brainstorm,
)
from autoresearch.competition.contest_direction_plan_cli import (
    _verify_plan_references,
)
from autoresearch.competition.contest_direction_research_loop_cli import (
    _OUTER_MODEL_STAGES,
    _SOURCE_ACCOUNTING_PROTOCOL,
    _load_completed_two_stage_literature,
    _model_call_count,
    _two_stage_literature_artifact_bindings,
    run_contest_direction_research_loop,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    provider_checkpoint_accounting,
    research_loop_source_checkpoint_accounting,
)
from autoresearch.competition.contest_human_delivery_validator import (
    HumanDeliveryValidationError,
    HumanDeliveryValidationReport,
    validate_runner_human_delivery,
)
from autoresearch.competition.contest_question_input import (
    Science125QuestionInput,
    Science125QuestionSet,
    extract_all_science_125_questions,
)
from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
)
from autoresearch.competition.manifest import canonical_model_hash

BatchPreexperimentPolicy = Literal["required", "plan_only_on_unsupported"]
DirectionLoopRunner = Callable[..., Mapping[str, Any]]
PlanOnlyRunner = Callable[..., Mapping[str, Any]]
QuestionPostRunHook = Callable[[Science125QuestionInput, Mapping[str, Any]], None]

_DEFAULT_OUTPUT = Path("runs/contest-delivery/science125-batch")
_SAFE_SHORT_ID = re.compile(r"^q(?P<ordinal>00[1-9]|0[1-9][0-9]|1[01][0-9]|12[0-5])$")
_SAFE_FULL_ID = re.compile(r"^science125-q(?P<ordinal>[0-9]{3})-[0-9a-f]{16}$")
_TWO_STAGE_LITERATURE_PROTOCOL = "two_stage_literature_v5"
_DIRECTION_DELIVERY_SCHEMA = "contest-direction-research-loop-delivery-v2"
_PLAN_ONLY_DELIVERY_SCHEMA = "science125-plan-only-delivery-v2"
_PLAN_ONLY_PROVIDER_STAGES = (
    "broad-literature-query",
    "focus-selection",
    "targeted-literature-query",
    "planning-literature-gap-repair-query",
    "skill-routing",
    "hypothesis-brainstorm",
    "plan-only-final-plan",
)


class Science125BatchError(RuntimeError):
    """Raised when the source or batch checkpoint contract is inconsistent."""


def select_science125_questions(
    question_set: Science125QuestionSet,
    *,
    start: int = 1,
    limit: int | None = 1,
    include_question_ids: Sequence[str | int] = (),
) -> tuple[Science125QuestionInput, ...]:
    """Select a source-ordered slice using stable full IDs or ``qNNN`` aliases."""

    if not 1 <= start <= 125:
        raise Science125BatchError("start must be between 1 and 125")
    if limit is not None and limit < 1:
        raise Science125BatchError("limit must be positive or omitted")
    if include_question_ids and start != 1:
        raise Science125BatchError("start must remain 1 when include_question_ids is used")
    if include_question_ids:
        selected_ordinals: set[int] = set()
        by_id = {item.question_id: item.ordinal for item in question_set.questions}
        for raw in include_question_ids:
            if isinstance(raw, bool):
                raise Science125BatchError(f"unknown or malformed Science 125 question ID: {raw}")
            if isinstance(raw, int):
                if not 1 <= raw <= 125:
                    raise Science125BatchError(
                        f"unknown or malformed Science 125 question ID: {raw}"
                    )
                selected_ordinals.add(raw)
                continue
            value = raw.strip()
            short = _SAFE_SHORT_ID.fullmatch(value)
            full = _SAFE_FULL_ID.fullmatch(value)
            if short is not None:
                ordinal = int(short.group("ordinal"))
            elif full is not None and value in by_id:
                ordinal = by_id[value]
            else:
                raise Science125BatchError(f"unknown or malformed Science 125 question ID: {raw}")
            selected_ordinals.add(ordinal)
        selected = tuple(
            item for item in question_set.questions if item.ordinal in selected_ordinals
        )
    else:
        selected = question_set.questions[start - 1 :]
    return selected if limit is None else selected[:limit]


def run_science125_batch(
    *,
    question_pdf: Path | str,
    output_root: Path | str = _DEFAULT_OUTPUT,
    start: int = 1,
    limit: int | None = 1,
    include_question_ids: Sequence[str | int] = (),
    resume: bool = False,
    dry_run: bool = False,
    min_interval_seconds: float = 1.0,
    preexperiment_policy: BatchPreexperimentPolicy = "plan_only_on_unsupported",
    dreaming_recall_enabled: bool = True,
    per_question_hook: QuestionPostRunHook | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    skills_root: Path | str = Path("skills"),
    direction_loop_runner: DirectionLoopRunner = run_contest_direction_research_loop,
    plan_only_runner: PlanOnlyRunner | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run selected questions serially with independent failure and resume state.

    ``per_question_hook`` is called only after one completed delivery and receives
    the exact question plus the hash-bound result mapping.  This is the intended
    integration seam for a separately governed self-evolution service; the batch
    module does not depend on an unfrozen Skill-evolution implementation.
    """

    if min_interval_seconds < 0:
        raise Science125BatchError("min_interval_seconds must be nonnegative")
    if preexperiment_policy not in {"required", "plan_only_on_unsupported"}:
        raise Science125BatchError("unsupported batch preexperiment policy")
    if resume and dry_run:
        raise Science125BatchError("resume and dry_run cannot be combined")

    question_set = extract_all_science_125_questions(question_pdf)
    selected = select_science125_questions(
        question_set,
        start=start,
        limit=limit,
        include_question_ids=include_question_ids,
    )
    if not selected:
        raise Science125BatchError("question selection is empty")
    root = Path(output_root).expanduser().resolve()
    _prepare_batch_root(root, resume=resume)
    manifest_path = root / "science125-question-set.json"
    _write_or_verify_json(manifest_path, question_set.model_dump(mode="json"))
    request_payload: dict[str, Any] = {
        "schema_version": "science125-batch-request-v2",
        "literature_protocol": _TWO_STAGE_LITERATURE_PROTOCOL,
        "question_set_manifest_hash": question_set.manifest_hash,
        "selected_question_ids": [item.question_id for item in selected],
        "start": start,
        "limit": limit,
        "include_question_ids": list(include_question_ids),
        "execution_order": "strict_serial_source_order",
        "failure_isolation": "per_question_attempt",
        "min_interval_seconds": min_interval_seconds,
        "preexperiment_policy": preexperiment_policy,
        "dreaming_recall_enabled": dreaming_recall_enabled,
        "formal_experiment_executed": False,
        "result_paper_generated": False,
        "scope": "research_plan_delivery_only",
        "config_binding": _optional_file_binding(Path(config_path)),
        "env_binding": _optional_file_binding(Path(env_path)),
    }
    request_payload["request_hash"] = canonical_model_hash(request_payload)
    _write_or_verify_json(root / "batch-request.json", request_payload)

    if dry_run:
        report = _batch_report(
            request=request_payload,
            question_set=question_set,
            selected=selected,
            results=tuple(
                {
                    "question_id": item.question_id,
                    "ordinal": item.ordinal,
                    "status": "planned_not_executed",
                    "output_dir": _question_root(root, item).as_posix(),
                }
                for item in selected
            ),
            dry_run=True,
        )
        _write_atomic_json(root / "batch-report.json", report)
        return {**report, "batch_report_path": (root / "batch-report.json").as_posix()}

    fallback = plan_only_runner or continue_plan_without_preexperiment
    results: list[dict[str, Any]] = []
    previous_executed = False
    for question in selected:
        question_root = _question_root(root, question)
        question_root.mkdir(parents=True, exist_ok=True)
        _write_or_verify_json(
            question_root / "question-input.json", question.model_dump(mode="json")
        )
        existing = _load_completed_question_state(question_root, question)
        if existing is not None:
            results.append(existing)
            continue
        if previous_executed and min_interval_seconds:
            sleep_fn(min_interval_seconds)
        previous_executed = True
        attempt_number = _failed_attempt_number(question_root) or _next_attempt_number(
            question_root
        )
        attempt_root = question_root / "attempts" / f"attempt-{attempt_number:03d}"
        attempt_root.mkdir(parents=True, exist_ok=True)
        direction = _question_direction(question)
        try:
            loop_policy = (
                "required"
                if question.ordinal == 1 or preexperiment_policy == "required"
                else "if_supported"
            )
            research_loop_root = attempt_root / "research-loop"
            loop_checkpoint = attempt_root / "direction-loop-result.json"
            loop_result = _load_direction_loop_result(loop_checkpoint)
            if loop_result is None:
                loop_result = _load_unsupported_direction_delivery(research_loop_root)
            if loop_result is None:
                loop_result = dict(
                    direction_loop_runner(
                        direction=direction,
                        output_dir=research_loop_root,
                        resume_existing=research_loop_root.is_dir(),
                        preexperiment_policy=loop_policy,
                        skills_root=skills_root,
                        config_path=config_path,
                        env_path=env_path,
                        dreaming_recall_enabled=dreaming_recall_enabled,
                    )
                )
            _validate_direction_delivery_protocol(loop_result, allow_plan_only=False)
            _write_or_verify_direction_loop_result(loop_checkpoint, loop_result)
            plan_only_used = False
            if not _result_contains_plan(loop_result):
                if preexperiment_policy != "plan_only_on_unsupported":
                    raise Science125BatchError(
                        "question completed without a research plan under required policy"
                    )
                if loop_result.get("preexperiment_executed") is not False:
                    raise Science125BatchError(
                        "plan-only fallback requires an explicit no-preexperiment result"
                    )
                plan_only_used = True
                loop_result = dict(
                    fallback(
                        question=question,
                        direction=direction,
                        direction_run_dir=attempt_root / "research-loop",
                        output_dir=attempt_root / "plan-only",
                        config_path=config_path,
                        env_path=env_path,
                        skills_root=skills_root,
                    )
                )
                _validate_direction_delivery_protocol(loop_result, allow_plan_only=True)
                if loop_result.get("schema_version") != _PLAN_ONLY_DELIVERY_SCHEMA:
                    raise Science125BatchError(
                        "plan-only fallback did not return the current plan-only delivery schema"
                    )
            result = _completed_question_result(
                question=question,
                attempt_number=attempt_number,
                attempt_root=attempt_root,
                delivery=loop_result,
                plan_only_used=plan_only_used,
            )
            _write_new_json(attempt_root / "completed-receipt.json", result)
            _write_atomic_json(question_root / "state.json", result)
            results.append(result)
            if per_question_hook is not None:
                try:
                    per_question_hook(question, result)
                except Exception as exc:  # hook is isolated from a valid plan delivery
                    hook_receipt = {
                        "schema_version": "science125-post-run-hook-receipt-v1",
                        "question_id": question.question_id,
                        "delivery_status": "completed",
                        "hook_status": "failed_nonblocking",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1_000],
                    }
                    hook_receipt["receipt_hash"] = canonical_model_hash(hook_receipt)
                    _write_new_json(attempt_root / "post-run-hook-receipt.json", hook_receipt)
        except Exception as exc:  # per-question isolation; later questions still run
            failure = {
                "schema_version": "science125-question-attempt-failure-v1",
                "question_id": question.question_id,
                "ordinal": question.ordinal,
                "attempt_number": attempt_number,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:2_000],
                "formal_experiment_executed": False,
                "result_paper_generated": False,
            }
            failure["artifacts"] = {
                "research_loop": _research_loop_failure_binding(
                    attempt_root=attempt_root,
                    research_loop_root=attempt_root / "research-loop",
                )
            }
            try:
                failure["model_call_accounting"] = _failed_model_call_accounting(
                    attempt_root / "research-loop"
                )
                failure["source_accounting"] = research_loop_source_checkpoint_accounting(
                    attempt_root / "research-loop"
                )
            except Exception as accounting_exc:
                failure["checkpoint_accounting_status"] = "unavailable_invalid_local_checkpoint"
                failure["checkpoint_accounting_error_type"] = type(accounting_exc).__name__
            failure["receipt_hash"] = canonical_model_hash(failure)
            _write_new_json(_next_failure_receipt_path(attempt_root), failure)
            _write_atomic_json(question_root / "state.json", failure)
            results.append(failure)

    report = _batch_report(
        request=request_payload,
        question_set=question_set,
        selected=selected,
        results=tuple(results),
        dry_run=False,
    )
    report_path = root / "batch-report.json"
    _write_atomic_json(report_path, report)
    return {
        **report,
        "batch_report_path": report_path.as_posix(),
        "batch_report_sha256": _sha256_file(report_path),
    }


def continue_plan_without_preexperiment(
    *,
    question: Science125QuestionInput,
    direction: str,
    direction_run_dir: Path | str,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    skills_root: Path | str = Path("skills"),
) -> dict[str, Any]:
    """Continue an unsupported real-pilot branch to a truthful Chinese plan.

    This does not repeat retrieval or hypothesis generation.  It strictly reloads
    the broad search, evidence-grounded focus, targeted search, merged catalog and
    verified 5--10 item planning lock before consuming the v3 Skill routing and
    focused temporary-agent hypotheses.  The model is explicitly told that no
    compatible real pilot ran.
    """

    del skills_root  # selected Skill paths are frozen in the upstream manifest
    source_root = Path(direction_run_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    direction_input = _read_json(source_root / "direction-input.json")
    direction_id = str(direction_input.get("direction_id") or "")
    source_accounting_protocol = direction_input.get("source_accounting_protocol")
    if (
        direction_input.get("schema_version") != "contest-direction-research-loop-input-v2"
        or direction_input.get("literature_protocol") != _TWO_STAGE_LITERATURE_PROTOCOL
        or direction_input.get("direction") != direction
        or source_accounting_protocol not in {None, _SOURCE_ACCOUNTING_PROTOCOL}
        or not direction_id
    ):
        raise Science125BatchError("plan-only source direction binding mismatch")
    try:
        literature_state = _load_completed_two_stage_literature(source_root)
    except Exception as exc:
        raise Science125BatchError(
            "plan-only source does not contain a valid completed two-stage literature lineage"
        ) from exc
    if (
        literature_state.broad.direction != direction
        or literature_state.broad.method_skills
        or literature_state.targeted.method_skills
    ):
        raise Science125BatchError(
            "plan-only source broad and targeted retrieval must both be no-Skill searches"
        )
    scientific_direction = literature_state.focus.focused_direction_cn
    planning_catalog = literature_state.planning_catalog
    planning_context = literature_state.planning_context
    if not MIN_RESEARCH_PLAN_REFERENCES <= len(planning_catalog) <= (MAX_RESEARCH_PLAN_REFERENCES):
        raise Science125BatchError("plan-only source has no verified 5--10 reference lock")
    routing_path = source_root / "skill-routing.json"
    routing = load_contest_direct_skill_routing(routing_path)
    planning_record_ids = tuple(str(item.get("record_id")) for item in planning_catalog)
    routing_record_ids = routing.literature_evidence_record_ids
    evidence_context = routing.literature_evidence_context
    planning_positions = {record_id: index for index, record_id in enumerate(planning_record_ids)}
    routing_positions = tuple(
        planning_positions[record_id]
        for record_id in routing_record_ids or ()
        if record_id in planning_positions
    )
    if (
        routing.schema_version != "contest-direct-skill-routing-v3"
        or routing.question != scientific_direction
        or routing.broad_literature_artifact_hash != literature_state.broad.artifact_hash
        or routing.focus_artifact_hash != literature_state.focus.artifact_hash
        or routing.selected_focus_id != literature_state.focus.selected_focus_id
        or routing.targeted_retrieval_binding_hash
        != literature_state.targeted_binding.artifact_hash
        or routing.targeted_literature_artifact_hash != literature_state.targeted.artifact_hash
        or routing.merged_literature_artifact_hash != literature_state.merged.artifact_hash
        or routing.merged_literature_catalog_hash != literature_state.merged.merged_catalog_hash
        or not routing_record_ids
        or evidence_context is None
        or tuple(evidence_context.record_ids) != tuple(routing_record_ids)
        or len(set(routing_record_ids)) != len(routing_record_ids)
        or len(routing_positions) != len(routing_record_ids)
    ):
        raise Science125BatchError(
            "plan-only Skill routing is not bound to the focused two-stage planning lock"
        )
    selected_skill_manifest = _read_json(source_root / "selected-method-skills.json")
    selected_skills = _load_bound_skill_bodies(selected_skill_manifest, routing.selected_skill_ids)
    hypothesis_path = source_root / "hypothesis-stage" / "direction-hypothesis-brainstorm.json"
    hypotheses = load_contest_direction_hypothesis_brainstorm(
        hypothesis_path,
        verify_batch_files=True,
    )
    if hypotheses.direction != scientific_direction:
        raise Science125BatchError("plan-only hypothesis direction mismatch")

    plan_path = output / "system-authored-research-plan.json"
    plan_preexisting = plan_path.is_file()
    plan_input_hash = canonical_model_hash(
        {
            "question_id": question.question_id,
            "direction_input_hash": direction_input.get("input_hash"),
            "broad_literature_artifact_hash": literature_state.broad.artifact_hash,
            "focus_artifact_hash": literature_state.focus.artifact_hash,
            "targeted_literature_artifact_hash": literature_state.targeted.artifact_hash,
            "merged_literature_artifact_hash": literature_state.merged.artifact_hash,
            "planning_literature_artifact_hash": literature_state.planning_lock_payload[
                "artifact_hash"
            ],
            "routing_artifact_hash": routing.artifact_hash,
            "selected_skill_hashes": routing.selected_skill_hashes,
            "hypothesis_artifact_hash": hypotheses.artifact_hash,
            "preexperiment_executed": False,
        }
    )
    if plan_path.is_file():
        plan = load_contest_direct_plan(plan_path)
    else:
        context_runtime = ContestDirectionContextRuntime(
            direction_id=direction_id,
            output_dir=source_root / "context-memory",
        )
        context_runtime.verify_official_capability(config_path=config_path)
        with context_runtime.checkpointed_stage(
            "plan-only-final-plan",
            input_hash=plan_input_hash,
            checkpoint_root=source_root,
        ) as completion:
            plan = generate_contest_direct_plan(
                scientific_problem=scientific_direction,
                literature_context=planning_context,
                preexperiment_context=None,
                method_skills=selected_skills,
                temporary_agent_context={
                    **hypotheses.plan_context_payload(),
                    "science125_parent_problem_zh": direction,
                    "evidence_selected_focus_zh": scientific_direction,
                    "plan_only_boundary_zh": (
                        "系统没有找到兼容的真实预实验适配器。请自主筛选候选形成高质量"
                        "研究计划，但Results必须明确写明尚未执行预实验，禁止虚构数值。"
                    ),
                },
                config_path=config_path,
                env_path=env_path,
                output_path=plan_path,
                max_tokens=14_000,
                timeout_seconds=900,
                thinking_budget=3_000,
                temperature=0.2,
                llm_call=completion,
            )
    _verify_plan_references(
        plan,
        literature_context=planning_context,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    if "尚未执行预实验" not in plan.plan.results:
        raise Science125BatchError("plan-only Results did not disclose the missing preexperiment")
    payload = contest_direct_plan_template_payload(plan)
    payload.update(
        {
            "document_type": "科学假设与研究计划",
            "status": "completed_plan_only_no_compatible_real_preexperiment_adapter",
            "science125_question": question.model_dump(mode="json"),
            "specified_direction": direction,
            "focused_direction": scientific_direction,
            "preexperiment": {
                "executed": False,
                "status_zh": "尚无兼容真实预实验适配器，未执行预实验",
            },
            "formal_experiment_executed": False,
            "result_paper_generated": False,
        }
    )
    rendered = materialize_contest_direct_plan(
        payload=payload,
        output_dir=output / "plan",
        overwrite=False,
        timeout_seconds=180,
    )
    gap_repair_calls = (
        literature_state.gap_response.model_calls
        if literature_state.gap_response is not None
        else 0
    )
    source_stage_calls = {
        "broad-literature-query": literature_state.broad.query_model_calls,
        "focus-selection": literature_state.focus.model_call_count_at_creation,
        "targeted-literature-query": literature_state.targeted.query_model_calls,
        "planning-literature-gap-repair-query": gap_repair_calls,
        "skill-routing": routing.model_calls,
        "hypothesis-brainstorm": _model_call_count(hypotheses),
    }
    historical_source_calls = sum(source_stage_calls.values())
    plan_calls = _model_call_count(plan)
    this_loop_calls = 0 if plan_preexisting else plan_calls
    total_calls = historical_source_calls + plan_calls
    provider_accounting_by_stage = {
        stage: provider_checkpoint_accounting(source_root, stage_name=stage)
        for stage in _PLAN_ONLY_PROVIDER_STAGES
    }
    physical_attempts_by_stage = {
        stage: counts["attempt_count"] for stage, counts in provider_accounting_by_stage.items()
    }
    physical_attempt_total = sum(physical_attempts_by_stage.values())
    if physical_attempt_total < total_calls:
        raise Science125BatchError(
            "plan-only physical provider attempts undercount logical model calls"
        )
    literature_artifacts = _two_stage_literature_artifact_bindings(literature_state)
    report: dict[str, Any] = {
        "schema_version": _PLAN_ONLY_DELIVERY_SCHEMA,
        "literature_protocol": _TWO_STAGE_LITERATURE_PROTOCOL,
        "status": "completed_plan_only",
        "question_id": question.question_id,
        "direction": direction,
        "focused_direction": scientific_direction,
        "preexperiment_executed": False,
        "preexperiment_status_zh": "尚无兼容真实预实验适配器，未执行预实验",
        "formal_experiment_executed": False,
        "result_paper_generated": False,
        "upstream_reused_without_repeat_retrieval": True,
        "source_accounting": research_loop_source_checkpoint_accounting(source_root),
        "model_call_accounting": {
            "broad_retrieval_query_calls": literature_state.broad.query_model_calls,
            "focus_brainstorm_and_selection_calls": (
                literature_state.focus.model_call_count_at_creation
            ),
            "targeted_retrieval_query_calls": literature_state.targeted.query_model_calls,
            "planning_literature_gap_repair_calls": gap_repair_calls,
            "literature_aware_skill_routing_calls": routing.model_calls,
            "hypothesis_brainstorm_calls": _model_call_count(hypotheses),
            "plan_only_final_plan_calls": plan_calls,
            "scientific_model_calls_by_stage": {
                **source_stage_calls,
                "plan-only-final-plan": plan_calls,
            },
            "physical_provider_attempts_by_stage": physical_attempts_by_stage,
            "provider_checkpoint_accounting_by_stage": provider_accounting_by_stage,
            "physical_provider_attempt_total": physical_attempt_total,
            "physical_provider_attempt_semantics": (
                "lifetime_durable_attempt_reservations_deduplicated_by_canonical_stage_owner"
            ),
            "this_loop_observed_provider_request_attempts": this_loop_calls,
            "historical_source_provider_request_attempts": (total_calls - this_loop_calls),
            "total_provenance_provider_request_attempts": total_calls,
        },
        "artifacts": literature_artifacts,
        "broad_literature_artifact": _file_binding(literature_state.broad_path),
        "direction_focus_artifact": _file_binding(literature_state.focus_path),
        "targeted_literature_artifact": _file_binding(literature_state.targeted_path),
        "targeted_retrieval_binding": _file_binding(literature_state.targeted_binding_path),
        "merged_literature_artifact": _file_binding(literature_state.merged_path),
        "planning_literature_artifact": _file_binding(literature_state.planning_lock_path),
        "finalist_status_verification": _file_binding(literature_state.finalist_status_path),
        "planning_reference_count": len(planning_catalog),
        "skill_routing_artifact": _file_binding(routing_path),
        "hypothesis_artifact": _file_binding(hypothesis_path),
        "system_authored_plan": _file_binding(plan_path),
        "plan": _rendered_bindings(rendered),
        "plan_json_path": rendered.json_path.resolve().as_posix(),
        "plan_markdown_path": rendered.markdown_path.resolve().as_posix(),
        "plan_pdf_path": rendered.pdf_path.resolve().as_posix(),
    }
    report["report_hash"] = canonical_model_hash(report)
    report_path = output / "delivery-report.json"
    persisted_report = _write_or_verify_plan_only_report(
        report_path,
        report,
        require_source_accounting=(source_accounting_protocol == _SOURCE_ACCOUNTING_PROTOCOL),
    )
    return {
        **persisted_report,
        "delivery_report_path": report_path.as_posix(),
        "delivery_report_sha256": _sha256_file(report_path),
    }


def _question_direction(question: Science125QuestionInput) -> str:
    if question.ordinal == 1 and question.question_zh:
        return (
            f"{question.question_zh}\n原始英文问题：{question.question_en}\n"
            f"来源：《{question.source_title}》第1题（{question.discipline_zh}）。"
        )
    return (
        f"《{question.source_title}》第{question.ordinal}题（{question.discipline_zh}）："
        f"{question.question_en}\n请以中文形成科学假设与研究计划。"
    )


def _result_contains_plan(result: Mapping[str, Any]) -> bool:
    if (
        result.get("status")
        in {
            "completed",
            "completed_with_minor_issues",
        }
        and result.get("preexperiment_executed") is True
    ):
        return True
    for key in ("plan_pdf_path", "plan_markdown_path", "plan_json_path"):
        value = result.get(key)
        if isinstance(value, str) and Path(value).is_file():
            return True
    artifacts = result.get("artifacts")
    return isinstance(artifacts, Mapping) and any(
        key in artifacts for key in ("rendered_plan", "plan", "final_plan")
    )


def _completed_question_result(
    *,
    question: Science125QuestionInput,
    attempt_number: int,
    attempt_root: Path,
    delivery: Mapping[str, Any],
    plan_only_used: bool,
) -> dict[str, Any]:
    _validate_direction_delivery_protocol(delivery, allow_plan_only=True)
    report_path_value = delivery.get("delivery_report_path")
    if not isinstance(report_path_value, str):
        raise Science125BatchError("completed question delivery lacks delivery_report_path")
    report_path = Path(report_path_value).expanduser().resolve()
    if not report_path.is_file():
        raise Science125BatchError("completed question delivery report is missing")
    if not _result_contains_plan(delivery):
        raise Science125BatchError("completed question delivery does not contain a plan")
    try:
        human_validation = validate_runner_human_delivery(
            output_dir=attempt_root,
            result=delivery,
        )
    except HumanDeliveryValidationError as exc:
        raise Science125BatchError(
            f"completed question failed the human delivery contract: {exc}"
        ) from exc
    result: dict[str, Any] = {
        "schema_version": "science125-question-completion-v2",
        "literature_protocol": _TWO_STAGE_LITERATURE_PROTOCOL,
        "direction_delivery_schema": delivery.get("schema_version"),
        "question_id": question.question_id,
        "ordinal": question.ordinal,
        "status": "completed",
        "attempt_number": attempt_number,
        "attempt_root": attempt_root.resolve().as_posix(),
        "plan_only_fallback_used": plan_only_used,
        "preexperiment_executed": bool(delivery.get("preexperiment_executed") is True),
        "formal_experiment_executed": False,
        "result_paper_generated": False,
        "delivery_report": _file_binding(report_path),
        "delivery_report_path": report_path.as_posix(),
        "plan_json_path": delivery.get("plan_json_path"),
        "plan_markdown_path": delivery.get("plan_markdown_path"),
        "plan_pdf_path": delivery.get("plan_pdf_path") or _find_plan_pdf(delivery),
        "human_delivery_validation": _human_validation_payload(human_validation),
    }
    source_accounting = delivery.get("source_accounting")
    source_accounting_required = _attempt_requires_source_accounting(attempt_root)
    if source_accounting is not None:
        if not isinstance(source_accounting, Mapping):
            raise Science125BatchError("completed delivery source accounting is invalid")
        result["source_accounting"] = dict(source_accounting)
    elif source_accounting_required:
        raise Science125BatchError("current completed delivery lacks required source accounting")
    result["receipt_hash"] = canonical_model_hash(result)
    return result


def _find_plan_pdf(delivery: Mapping[str, Any]) -> str | None:
    pdf = delivery.get("pdf")
    if isinstance(pdf, Mapping) and isinstance(pdf.get("path"), str):
        return str(pdf["path"])
    artifacts = delivery.get("artifacts")
    if isinstance(artifacts, Mapping):
        for key in ("rendered_plan", "plan", "final_plan"):
            item = artifacts.get(key)
            if not isinstance(item, Mapping):
                continue
            for field in ("pdf_path", "pdf", "path"):
                value = item.get(field)
                if isinstance(value, str) and value.lower().endswith(".pdf"):
                    return value
                if isinstance(value, Mapping) and isinstance(value.get("path"), str):
                    return str(value["path"])
    return None


def _attempt_requires_source_accounting(attempt_root: Path) -> bool:
    direction_input_path = attempt_root / "research-loop" / "direction-input.json"
    if not direction_input_path.is_file():
        return False
    direction_input = _read_json(direction_input_path)
    protocol = direction_input.get("source_accounting_protocol")
    if protocol not in {None, _SOURCE_ACCOUNTING_PROTOCOL}:
        raise Science125BatchError("direction source-accounting protocol marker is invalid")
    return protocol == _SOURCE_ACCOUNTING_PROTOCOL


def _load_completed_question_state(
    question_root: Path,
    question: Science125QuestionInput,
) -> dict[str, Any] | None:
    state_path = question_root / "state.json"
    if not state_path.is_file():
        return None
    state = _read_json(state_path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in state.items() if key != "receipt_hash"}
    )
    if state.get("receipt_hash") != expected_hash:
        raise Science125BatchError(f"question state hash mismatch: {question.question_id}")
    if state.get("question_id") != question.question_id:
        raise Science125BatchError("question state belongs to another source question")
    if state.get("status") != "completed":
        return None
    if (
        state.get("schema_version") != "science125-question-completion-v2"
        or state.get("literature_protocol") != _TWO_STAGE_LITERATURE_PROTOCOL
        or state.get("direction_delivery_schema")
        not in {_DIRECTION_DELIVERY_SCHEMA, _PLAN_ONLY_DELIVERY_SCHEMA}
    ):
        # Legacy completion receipts are not upgraded in place.  Returning None
        # forces an isolated fresh attempt under the two-stage contract.
        return None
    report_path = Path(str(state.get("delivery_report_path") or "")).resolve()
    binding = state.get("delivery_report")
    if not report_path.is_file() or not isinstance(binding, Mapping):
        raise Science125BatchError("completed question state lacks its delivery report")
    _verify_file_binding(report_path, binding)
    attempt_root = Path(str(state.get("attempt_root") or "")).expanduser().resolve()
    if _attempt_requires_source_accounting(attempt_root):
        persisted_accounting = state.get("source_accounting")
        if not isinstance(persisted_accounting, Mapping):
            raise Science125BatchError("current completed question state lacks source accounting")
        delivery_accounting = _read_json(report_path).get("source_accounting")
        current_accounting = research_loop_source_checkpoint_accounting(
            attempt_root / "research-loop"
        )
        if (
            not isinstance(delivery_accounting, Mapping)
            or dict(delivery_accounting) != dict(persisted_accounting)
            or any(
                key not in persisted_accounting or persisted_accounting[key] != value
                for key, value in current_accounting.items()
            )
        ):
            raise Science125BatchError(
                "current completed question source accounting differs from its "
                "delivery report or verified local checkpoints"
            )
    try:
        human_validation = validate_runner_human_delivery(
            output_dir=attempt_root,
            result=state,
        )
    except HumanDeliveryValidationError:
        # A legacy or tampered ``completed`` state is not blessed on resume.  By
        # returning None, the serial scheduler creates the next isolated attempt
        # for this question while leaving other valid questions untouched.
        return None
    validation_payload = _human_validation_payload(human_validation)
    if state.get("human_delivery_validation") != validation_payload:
        # Pre-contract receipts are deliberately not upgraded in place: a new
        # attempt must earn a fresh completion receipt under the current gate.
        return None
    returned = dict(state)
    returned["resume_action"] = "already_complete_no_model_call"
    return returned


def _human_validation_payload(
    report: HumanDeliveryValidationReport | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(report, HumanDeliveryValidationReport):
        return report.to_dict()
    return dict(report)


def _next_attempt_number(question_root: Path) -> int:
    attempts = question_root / "attempts"
    if not attempts.is_dir():
        return 1
    numbers = [
        int(path.name.removeprefix("attempt-"))
        for path in attempts.iterdir()
        if path.is_dir() and re.fullmatch(r"attempt-[0-9]{3}", path.name)
    ]
    return max(numbers, default=0) + 1


def _failed_attempt_number(question_root: Path) -> int | None:
    state_path = question_root / "state.json"
    if not state_path.is_file():
        return None
    state = _read_json(state_path)
    if state.get("status") != "failed":
        return None
    value = state.get("attempt_number")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise Science125BatchError("failed question state has an invalid attempt number")
    return value


def _load_direction_loop_result(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = _read_json(path)
    result = payload.get("result")
    if payload.get("schema_version") != "science125-direction-loop-result-v2" or not isinstance(
        result, Mapping
    ):
        raise Science125BatchError("direction-loop result checkpoint is invalid")
    if payload.get("result_hash") != canonical_model_hash(dict(result)):
        raise Science125BatchError("direction-loop result checkpoint hash mismatch")
    validated = dict(result)
    _validate_direction_delivery_protocol(validated, allow_plan_only=False)
    return validated


def _write_or_verify_direction_loop_result(
    path: Path,
    result: Mapping[str, Any],
) -> None:
    payload = {
        "schema_version": "science125-direction-loop-result-v2",
        "result": dict(result),
        "result_hash": canonical_model_hash(dict(result)),
    }
    _write_or_verify_json(path, payload)


def _load_unsupported_direction_delivery(root: Path) -> dict[str, Any] | None:
    """Recover a current two-stage no-adapter terminal branch without rerunning it."""

    path = root / "delivery-report.json"
    if not path.is_file():
        return None
    report = _read_json(path)
    _validate_direction_delivery_protocol(report, allow_plan_only=False)
    if report.get("status") != "completed_without_preexperiment_no_compatible_adapter":
        return None
    if report.get("preexperiment_executed") is not False:
        raise Science125BatchError("unsupported direction receipt overstates preexperiment state")
    return {
        **report,
        "delivery_report_path": path.resolve().as_posix(),
        "delivery_report_sha256": _sha256_file(path),
    }


def _validate_direction_delivery_protocol(
    result: Mapping[str, Any],
    *,
    allow_plan_only: bool,
) -> None:
    schema = result.get("schema_version")
    allowed = {_DIRECTION_DELIVERY_SCHEMA}
    if allow_plan_only:
        allowed.add(_PLAN_ONLY_DELIVERY_SCHEMA)
    if schema not in allowed:
        raise Science125BatchError(
            "legacy or unknown direction delivery cannot satisfy the two-stage batch contract"
        )
    if result.get("literature_protocol") != _TWO_STAGE_LITERATURE_PROTOCOL:
        raise Science125BatchError("direction delivery lacks the two-stage literature protocol")
    if schema == _PLAN_ONLY_DELIVERY_SCHEMA:
        if result.get("status") != "completed_plan_only":
            raise Science125BatchError("plan-only delivery has a non-completed status")
        return
    status = result.get("status")
    if status == "completed_without_preexperiment_no_compatible_adapter":
        return
    expected_recommendation = {
        "completed": "pass",
        "completed_with_minor_issues": "minor_revision",
    }.get(str(status or ""))
    review = result.get("independent_scientific_review")
    if expected_recommendation is None:
        raise Science125BatchError(
            "direction delivery is not authorized by a completed scientific review gate"
        )
    if not isinstance(review, Mapping) or review.get("recommendation") != expected_recommendation:
        raise Science125BatchError(
            "direction delivery status disagrees with its independent scientific review"
        )


def _next_failure_receipt_path(attempt_root: Path) -> Path:
    ordinal = 1
    while True:
        path = attempt_root / f"failed-receipt-{ordinal:03d}.json"
        if not path.exists():
            return path
        ordinal += 1


def _failed_model_call_accounting(research_loop_root: Path) -> dict[str, Any]:
    response_accounting = {
        stage: provider_checkpoint_accounting(research_loop_root, stage_name=stage)
        for stage in _OUTER_MODEL_STAGES
    }
    completed_by_stage = {
        stage: counts["completed_count"] for stage, counts in response_accounting.items()
    }
    parse_failed_by_stage = {
        stage: counts["parse_failed_count"] for stage, counts in response_accounting.items()
    }
    transport_failed_by_stage = {
        stage: counts.get("transport_failed_count", 0)
        for stage, counts in response_accounting.items()
    }
    terminal_failed_by_stage = {
        stage: counts.get("terminal_failed_count", 0)
        for stage, counts in response_accounting.items()
    }
    outcome_unknown_by_stage = {
        stage: counts["outcome_unknown_count"] for stage, counts in response_accounting.items()
    }
    return {
        "checkpoint_status": "verified_local_checkpoints",
        "outer_provider_response_accounting_by_stage": response_accounting,
        "outer_provider_escrow_count_by_stage": completed_by_stage,
        "outer_provider_escrow_count": sum(completed_by_stage.values()),
        "outer_provider_parse_failed_count_by_stage": parse_failed_by_stage,
        "outer_provider_parse_failed_count": sum(parse_failed_by_stage.values()),
        "outer_provider_transport_failed_count_by_stage": transport_failed_by_stage,
        "outer_provider_transport_failed_count": sum(transport_failed_by_stage.values()),
        "outer_provider_terminal_failed_count_by_stage": terminal_failed_by_stage,
        "outer_provider_terminal_failed_count": sum(terminal_failed_by_stage.values()),
        "outer_provider_outcome_unknown_count_by_stage": outcome_unknown_by_stage,
        "outer_provider_outcome_unknown_count": sum(outcome_unknown_by_stage.values()),
        "this_attempt_observed_provider_request_attempts": sum(
            counts["attempt_count"] for counts in response_accounting.values()
        ),
        "outer_provider_physical_attempt_count": sum(
            counts["attempt_count"] for counts in response_accounting.values()
        ),
    }


def _research_loop_failure_binding(
    *,
    attempt_root: Path,
    research_loop_root: Path,
) -> dict[str, Any]:
    attempt = attempt_root.expanduser().resolve()
    research_loop = research_loop_root.expanduser().resolve()
    try:
        relative_root = research_loop.relative_to(attempt).as_posix()
    except ValueError as exc:
        raise Science125BatchError("research-loop failure path escapes its attempt") from exc
    inventory: list[dict[str, Any]] = []
    if research_loop.exists() and not research_loop.is_dir():
        raise Science125BatchError("research-loop failure path is not a directory")
    if research_loop.is_dir():
        for path in sorted(research_loop.rglob("*")):
            resolved = path.resolve()
            if not resolved.is_file():
                continue
            try:
                relative = resolved.relative_to(research_loop).as_posix()
            except ValueError as exc:
                raise Science125BatchError(
                    "research-loop failure inventory escapes its root"
                ) from exc
            binding = _file_binding(resolved)
            inventory.append(
                {
                    "relative_path": relative,
                    "sha256": binding["sha256"],
                    "size_bytes": binding["size_bytes"],
                }
            )
    return {
        "relative_path": relative_root,
        "exists": research_loop.is_dir(),
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
    }


def _batch_report(
    *,
    request: Mapping[str, Any],
    question_set: Science125QuestionSet,
    selected: Sequence[Science125QuestionInput],
    results: Sequence[Mapping[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    completed = sum(item.get("status") == "completed" for item in results)
    failed = sum(item.get("status") == "failed" for item in results)
    report: dict[str, Any] = {
        "schema_version": "science125-batch-report-v2",
        "literature_protocol": _TWO_STAGE_LITERATURE_PROTOCOL,
        "status": (
            "dry_run"
            if dry_run
            else "completed"
            if completed == len(selected)
            else "completed_with_isolated_failures"
        ),
        "request_hash": request["request_hash"],
        "question_set_manifest_hash": question_set.manifest_hash,
        "selected_count": len(selected),
        "completed_count": completed,
        "failed_count": failed,
        "execution_order": "strict_serial_source_order",
        "formal_experiment_executed": False,
        "result_paper_generated": False,
        "all_125_source_questions_available": True,
        "results": [dict(item) for item in results],
    }
    report["report_hash"] = canonical_model_hash(report)
    return report


def _load_bound_skill_bodies(
    manifest: Mapping[str, Any],
    selected_skill_ids: Sequence[str],
) -> tuple[str, ...]:
    raw = manifest.get("skills")
    if not isinstance(raw, list):
        raise Science125BatchError("selected Skill manifest has no skills list")
    by_id = {
        str(item.get("skill_id")): item
        for item in raw
        if isinstance(item, Mapping) and item.get("skill_id")
    }
    bodies: list[str] = []
    for skill_id in selected_skill_ids:
        item = by_id.get(skill_id)
        if item is None:
            raise Science125BatchError(f"selected Skill missing from manifest: {skill_id}")
        path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            raise Science125BatchError(f"selected Skill file is missing: {path}")
        content = path.read_text(encoding="utf-8")
        expected = item.get("content_sha256")
        if expected != hashlib.sha256(content.encode("utf-8")).hexdigest():
            raise Science125BatchError(f"selected Skill changed after routing: {skill_id}")
        bodies.append(content)
    return tuple(bodies)


def _rendered_bindings(rendered: ContestDirectPlanArtifacts) -> dict[str, Any]:
    return {
        "json": _file_binding(rendered.json_path),
        "markdown": _file_binding(rendered.markdown_path),
        "tex": _file_binding(rendered.tex_path),
        "pdf": _file_binding(rendered.pdf_path),
        "manifest": _file_binding(rendered.manifest_path),
        "source_payload_sha256": rendered.source_payload_sha256,
        "pdf_text_verified": rendered.pdf_text_verified,
        "page_count": rendered.page_count,
    }


def _question_root(root: Path, question: Science125QuestionInput) -> Path:
    suffix = question.question_id.rsplit("-", 1)[-1]
    return root / "questions" / f"q{question.ordinal:03d}-{suffix}"


def _prepare_batch_root(root: Path, *, resume: bool) -> None:
    if resume:
        if not root.is_dir():
            raise Science125BatchError("resume batch root does not exist")
        return
    if root.exists() and any(root.iterdir()):
        raise Science125BatchError("batch output root is not empty; use --resume or a new path")
    root.mkdir(parents=True, exist_ok=True)


def _write_or_verify_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.is_file():
        if _read_json(path) != dict(payload):
            raise Science125BatchError(f"existing checkpoint differs from requested bytes: {path}")
        return
    _write_new_json(path, payload)


def _write_or_verify_plan_only_report(
    path: Path,
    payload: Mapping[str, Any],
    *,
    require_source_accounting: bool,
) -> dict[str, Any]:
    if not path.is_file():
        _write_new_json(path, payload)
        return dict(payload)
    existing = _read_json(path)
    if existing == dict(payload):
        return existing
    if require_source_accounting:
        raise Science125BatchError(f"current plan-only report source accounting differs: {path}")
    legacy = dict(payload)
    legacy.pop("source_accounting", None)
    legacy["report_hash"] = canonical_model_hash(
        {key: value for key, value in legacy.items() if key != "report_hash"}
    )
    if existing == legacy:
        return existing
    raise Science125BatchError(f"existing checkpoint differs from requested bytes: {path}")


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise Science125BatchError(f"refusing to overwrite checkpoint: {path}") from exc


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Science125BatchError(f"invalid JSON checkpoint {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Science125BatchError(f"JSON checkpoint is not an object: {path}")
    return payload


def _optional_file_binding(path: Path) -> dict[str, Any] | None:
    resolved = path.expanduser().resolve()
    return _file_binding(resolved) if resolved.is_file() else None


def _file_binding(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise Science125BatchError(f"bound file does not exist: {resolved}")
    return {
        "path": resolved.as_posix(),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _verify_file_binding(path: Path, binding: Mapping[str, Any]) -> None:
    actual = _file_binding(path)
    if (
        binding.get("sha256") != actual["sha256"]
        or binding.get("size_bytes") != actual["size_bytes"]
    ):
        raise Science125BatchError(f"bound file changed: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从用户提供的Science 125 PDF确定性抽题，并严格串行生成相互隔离的中文研究计划。"
        )
    )
    parser.add_argument("--question-pdf", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument(
        "--include-question-id",
        action="append",
        default=[],
        help="可重复；接受q001..q125或当前PDF绑定的完整science125 ID。",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--preexperiment-policy",
        choices=("required", "plan-only-on-unsupported"),
        default="plan-only-on-unsupported",
    )
    parser.add_argument("--disable-dreaming-recall", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--skills-root", type=Path, default=Path("skills"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_science125_batch(
        question_pdf=args.question_pdf,
        output_root=args.output_root,
        start=args.start,
        limit=args.limit,
        include_question_ids=args.include_question_id,
        resume=args.resume,
        dry_run=args.dry_run,
        min_interval_seconds=args.min_interval_seconds,
        preexperiment_policy=args.preexperiment_policy.replace("-", "_"),
        dreaming_recall_enabled=not args.disable_dreaming_recall,
        config_path=args.config,
        env_path=args.env,
        skills_root=args.skills_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed_count"] == 0 else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BatchPreexperimentPolicy",
    "QuestionPostRunHook",
    "Science125BatchError",
    "continue_plan_without_preexperiment",
    "main",
    "run_science125_batch",
    "select_science125_questions",
]
