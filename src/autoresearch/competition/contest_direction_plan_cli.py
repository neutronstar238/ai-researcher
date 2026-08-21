"""One-command specified-direction delivery backed by real literature retrieval.

The configured model first sees the direction and delivery requirements, then a
metadata-only Skill catalog.  Exact bodies of the selected Skills are loaded only
after routing and are passed as independent read-only context to real-query
planning, temporary objective agents, and the final plan author.  Literature can
enter the plan only through the repository's live academic search callables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

from autoresearch.agents.temporary import (
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    issue_stage_controller,
)
from autoresearch.competition.contest_direct_plan import (
    contest_direct_plan_template_payload,
    generate_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_cli import (
    discover_contest_method_skills,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectSkillRoutingArtifact,
    route_contest_direct_plan_skills,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    ContestDirectionLiteratureError,
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    validate_locked_bibliography,
)
from autoresearch.competition.contest_research_objective_stage import (
    run_contest_research_objective_stage,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenSkillContext
from autoresearch.literature.clients import ArxivClient
from autoresearch.literature.models import AcademicPaper, PublicationStatus

_DEFAULT_OUTPUT = Path("runs/contest-delivery/specified-direction-plan")
_DEFAULT_SKILLS_ROOT = Path("skills")
_MAX_PDF_PAGES = 20
_MAX_PLANNING_LITERATURE_CHARACTERS = 64_000
_FINALIST_STATUS_CONTEXT_RESERVE = 256
_LEXICAL_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "for",
        "from",
        "higher",
        "in",
        "is",
        "not",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_LEXICAL_TOKEN_ALIASES = {
    "baselines": "baseline",
    "blocks": "block",
    "densities": "density",
    "entropies": "entropy",
    "gaps": "gap",
    "methods": "method",
    "models": "model",
    "numbers": "number",
    "patterns": "pattern",
    "primes": "prime",
    "probabilities": "probability",
    "residues": "residue",
    "sequences": "sequence",
    "values": "value",
}
_DIRECTION_REQUIREMENTS = (
    "生成完整中文《科学假设与研究计划》并满足榜题标准字段",
    "先基于真实检索文献形成并独立评审研究目标，再围绕一个可证伪主假设设计路径",
    "引用只能来自本次真实检索目录，保留来源、检索时间、摘要及URL或DOI",
    "Results须以“本交付范围为研究计划”说明边界并给出预期结果与判定标准，不虚构观察结果、数值或正式实验结论",
    "输出计划而非论文；普通工作站可起步，允许负结果和替代解释",
)


class ContestDirectionPlanDeliveryError(RuntimeError):
    """Raised when a direction cannot yield one evidence-bound plan delivery."""


class _PlanReferenceView(Protocol):
    @property
    def plan(self) -> Any: ...


def run_contest_direction_plan_delivery(
    *,
    direction: str,
    output_dir: Path | str = _DEFAULT_OUTPUT,
    skills_root: Path | str = _DEFAULT_SKILLS_ROOT,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_results_per_search: int = 20,
    skill_routing_max_tokens: int = 1_024,
    query_max_tokens: int = 768,
    brainstorm_max_tokens: int = 2_600,
    review_max_tokens: int = 3_200,
    plan_max_tokens: int = 12_000,
    timeout_seconds: int = 900,
    thinking_budget: int = 3_000,
    render_timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Run Skill routing, live retrieval, objective review, and plan materialization.

    The production entry deliberately exposes neither search callables nor a
    caller-chosen retrieval timestamp.  ``retrieve_contest_direction_literature``
    therefore uses its repository-default Arxiv/OpenAlex boundaries (and optional
    configured Semantic Scholar) and records the actual retrieval timestamp.
    """

    clean_direction = direction.strip()
    if not clean_direction:
        raise ContestDirectionPlanDeliveryError("specified direction must not be blank")
    if max_results_per_search < 1:
        raise ContestDirectionPlanDeliveryError("max_results_per_search must be positive")
    if timeout_seconds < 1 or render_timeout_seconds < 1:
        raise ContestDirectionPlanDeliveryError("timeouts must be positive")

    output_root = Path(output_dir).expanduser().resolve()
    _prepare_empty_output(output_root)
    direction_input_hash = canonical_model_hash(
        {
            "input_mode": "specified_direction",
            "direction": clean_direction,
            "requirements": list(_DIRECTION_REQUIREMENTS),
        }
    )
    direction_id = f"specified-direction-{direction_input_hash[:20]}"
    direction_input_path = output_root / "direction-input.json"
    _write_new_json(
        direction_input_path,
        {
            "schema_version": "contest-specified-direction-input-v1",
            "direction_id": direction_id,
            "input_mode": "specified_direction",
            "direction": clean_direction,
            "requirements": list(_DIRECTION_REQUIREMENTS),
            "input_hash": direction_input_hash,
        },
    )

    skill_catalog, skill_bodies = discover_contest_method_skills(skills_root)
    routing_path = output_root / "skill-routing.json"
    routing = route_contest_direct_plan_skills(
        question=clean_direction,
        requirements=_DIRECTION_REQUIREMENTS,
        skill_catalog=skill_catalog,
        config_path=config_path,
        env_path=env_path,
        output_path=routing_path,
        timeout_seconds=timeout_seconds,
        max_tokens=skill_routing_max_tokens,
    )
    _verify_internal_hash_file(
        routing_path,
        field="artifact_hash",
        expected=routing.artifact_hash,
    )
    selected_skills = _load_selected_skills(routing, skill_bodies)
    selected_skill_manifest_path = output_root / "selected-method-skills.json"
    _write_new_json(
        selected_skill_manifest_path,
        {
            "schema_version": "contest-direction-selected-skills-v1",
            "routing_artifact_path": routing_path.as_posix(),
            "routing_artifact_hash": routing.artifact_hash,
            "selected_by_configured_model_after_direction": True,
            "skill_bodies_visible_to_selector": False,
            "skills": [
                {
                    "skill_id": item["skill_id"],
                    "path": item["path"].as_posix(),
                    "content_sha256": item["content_sha256"],
                    "file_sha256": _sha256_file(item["path"]),
                }
                for item in selected_skills
            ],
        },
    )

    literature_path = output_root / "literature" / "direction-literature.json"
    try:
        literature = retrieve_contest_direction_literature(
            direction=clean_direction,
            searchers=None,
            requirements=_DIRECTION_REQUIREMENTS,
            selected_method_skills={item["skill_id"]: item["content"] for item in selected_skills},
            config_path=config_path,
            env_path=env_path,
            output_path=literature_path,
            timeout_seconds=timeout_seconds,
            max_tokens=query_max_tokens,
            max_results_per_search=max_results_per_search,
        )
    except ContestDirectionLiteratureError as exc:
        failure_path = _write_literature_failure(
            output_root=output_root,
            direction=clean_direction,
            stage="real_retrieval",
            error=exc,
            fetches=exc.fetches,
        )
        raise ContestDirectionPlanDeliveryError(
            "real literature retrieval yielded no usable paper; " f"failure receipt: {failure_path}"
        ) from exc

    try:
        retrieval_catalog, literature_context, excluded_records = _eligible_literature(literature)
    except ContestDirectionPlanDeliveryError as exc:
        failure_path = _write_literature_failure(
            output_root=output_root,
            direction=clean_direction,
            stage="catalog_validation",
            error=exc,
            fetches=literature.fetches,
        )
        raise ContestDirectionPlanDeliveryError(
            f"retrieved literature lacks required provenance; failure receipt: {failure_path}"
        ) from exc
    _verify_internal_hash_file(
        literature_path,
        field="artifact_hash",
        expected=literature.artifact_hash,
    )
    (
        planning_catalog,
        planning_literature_context,
        finalist_status_verifications,
    ) = _select_planning_literature_with_status(
        retrieval_catalog,
        literature_context,
        queries=literature.queries,
        arxiv_status_verifier=ArxivClient().verify_status,
        minimum_records=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_records=MAX_RESEARCH_PLAN_REFERENCES,
    )
    finalist_status_path = output_root / "literature" / "finalist-status-verification.json"
    finalist_status_payload: dict[str, Any] = {
        "schema_version": "contest-direction-finalist-status-verification-v1",
        "scope": "shortlisted_arxiv_records_only",
        "all_candidate_status_requests_forbidden": True,
        "verification_count": sum(
            item["verification_attempted"] for item in finalist_status_verifications
        ),
        "records": finalist_status_verifications,
    }
    finalist_status_payload["artifact_hash"] = canonical_model_hash(finalist_status_payload)
    _write_new_json(finalist_status_path, finalist_status_payload)

    controller_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_input_hash,
            "skill_routing_artifact_hash": routing.artifact_hash,
            "selected_skill_hashes": routing.selected_skill_hashes,
            "literature_artifact_hash": literature.artifact_hash,
            "eligible_literature_hash": canonical_model_hash({"catalog": list(retrieval_catalog)}),
            "planning_literature_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
        }
    )
    brainstorm_controller, brainstorm_capability = issue_stage_controller(
        lineage_id=direction_id,
        stage="direction-objective-brainstorm",
        stage_attempt=1,
        controller_agent_id="contest-direction-main-agent",
        stage_input_hash=controller_input_hash,
        max_parallel_agents=3,
    )
    review_controller, review_capability = issue_stage_controller(
        lineage_id=direction_id,
        stage="direction-objective-review",
        stage_attempt=1,
        controller_agent_id="contest-direction-main-agent",
        stage_input_hash=controller_input_hash,
        max_parallel_agents=1,
    )
    temporary_skill_contexts = tuple(
        TemporaryQwenSkillContext(
            skill_ref=TemporaryAgentSkillRef(
                skill_id=item["skill_id"],
                source_ref=item["path"].as_posix(),
                content_sha256=item["content_sha256"],
            ),
            content=item["content"],
        )
        for item in selected_skills
    )
    objective = run_contest_research_objective_stage(
        mode="specified_direction",
        seed_text=clean_direction,
        requirements="\n".join(_DIRECTION_REQUIREMENTS),
        seed_ref=TemporaryAgentInputRef(
            artifact_id=direction_id,
            source_ref=direction_input_path.as_posix(),
            sha256=direction_input_hash,
        ),
        parent_task_id=f"{direction_id}-research-plan",
        brainstorm_controller=brainstorm_controller,
        brainstorm_capability=brainstorm_capability,
        review_controller=review_controller,
        review_capability=review_capability,
        output_dir=output_root,
        selected_skill_contexts=temporary_skill_contexts,
        retrieved_literature_catalog=planning_catalog,
        config_path=config_path,
        env_path=env_path,
        max_tokens_per_brainstorm_agent=brainstorm_max_tokens,
        max_tokens_for_review=review_max_tokens,
        timeout_seconds=timeout_seconds,
        thinking_budget=thinking_budget,
        temperature=0.35,
    )
    if not objective.all_runtime_identities_removed or not objective.outputs_and_receipts_retained:
        raise ContestDirectionPlanDeliveryError(
            "temporary research-objective identities/outputs were not fully archived"
        )
    if brainstorm_capability.active or review_capability.active:
        raise ContestDirectionPlanDeliveryError(
            "research-objective dispatch capabilities remain active after archival"
        )
    objective_path = _inside_output(output_root, objective.artifact_relative_path)
    _verify_internal_hash_file(
        objective_path,
        field="artifact_hash",
        expected=objective.artifact_hash,
    )

    system_plan_path = output_root / "system-authored-research-plan.json"
    plan = generate_contest_direct_plan(
        scientific_problem=clean_direction,
        literature_context=planning_literature_context,
        preexperiment_context=None,
        method_skills=tuple(item["content"] for item in selected_skills),
        temporary_agent_context=objective.plan_context_payload(),
        config_path=config_path,
        env_path=env_path,
        output_path=system_plan_path,
        timeout_seconds=timeout_seconds,
        max_tokens=plan_max_tokens,
        thinking_budget=thinking_budget,
        temperature=0.2,
    )
    _verify_internal_hash_file(
        system_plan_path,
        field="artifact_hash",
        expected=plan.artifact_hash,
    )
    _verify_plan_references(
        plan,
        literature_context=planning_literature_context,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    if "本交付范围为研究计划" not in plan.plan.results:
        raise ContestDirectionPlanDeliveryError(
            "direction plan must state the completed research-plan delivery boundary"
        )

    render_payload = contest_direct_plan_template_payload(plan)
    render_payload.update(
        {
            "document_type": plan.document_type,
            "status": plan.status,
            "specified_direction": clean_direction,
            "generation": {
                "provider": plan.provider,
                "model_name": plan.model_name,
                "generation_calls": plan.generation_calls,
                "input_hash": plan.input_hash,
                "model_response_hash": plan.model_response_hash,
                "artifact_hash": plan.artifact_hash,
            },
            "literature_provenance": {
                "artifact_path": literature_path.as_posix(),
                "artifact_hash": literature.artifact_hash,
                "eligible_catalog_hash": canonical_model_hash({"catalog": list(retrieval_catalog)}),
                "eligible_record_count": len(retrieval_catalog),
                "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
                "planning_record_count": len(planning_catalog),
                "planning_subset_selected_for_context_budget": (
                    len(planning_catalog) < len(retrieval_catalog)
                ),
            },
            "research_objective": {
                "artifact_path": objective_path.as_posix(),
                "artifact_hash": objective.artifact_hash,
                "status": objective.status,
                "temporary_runtime_identities_removed": True,
            },
        }
    )
    rendered = materialize_contest_direct_plan(
        payload=render_payload,
        output_dir=output_root / "plan",
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )
    verified_page_count, page_count_method = _verify_rendered_pdf(rendered)

    main_artifacts = {
        "direction_input": _file_binding(direction_input_path),
        "skill_routing": {
            **_file_binding(routing_path),
            "artifact_hash": routing.artifact_hash,
        },
        "selected_method_skills": _file_binding(selected_skill_manifest_path),
        "literature": {
            **_file_binding(literature_path),
            "artifact_hash": literature.artifact_hash,
        },
        "finalist_status_verification": {
            **_file_binding(finalist_status_path),
            "artifact_hash": finalist_status_payload["artifact_hash"],
        },
        "research_objective": {
            **_file_binding(objective_path),
            "artifact_hash": objective.artifact_hash,
        },
        "system_authored_plan": {
            **_file_binding(system_plan_path),
            "artifact_hash": plan.artifact_hash,
        },
        "rendered_plan": _rendered_bindings(rendered),
    }
    inventory = _file_inventory(output_root)
    report: dict[str, Any] = {
        "schema_version": "contest-direction-plan-delivery-v1",
        "status": "completed",
        "input_mode": "specified_direction",
        "direction_id": direction_id,
        "direction": clean_direction,
        "direction_input_hash": direction_input_hash,
        "requirements": list(_DIRECTION_REQUIREMENTS),
        "requirements_hash": canonical_model_hash({"requirements": list(_DIRECTION_REQUIREMENTS)}),
        "model_calls": (
            routing.model_calls
            + literature.query_model_calls
            + objective.model_call_count
            + plan.generation_calls
        ),
        "skill_routing_model_calls": routing.model_calls,
        "literature_query_model_calls": literature.query_model_calls,
        "research_objective_model_calls": objective.model_call_count,
        "plan_generation_model_calls": plan.generation_calls,
        "selected_skill_ids": list(routing.selected_skill_ids),
        "selected_skill_hashes": routing.selected_skill_hashes,
        "selected_skill_files": [
            {
                "skill_id": item["skill_id"],
                "content_sha256": item["content_sha256"],
                **_file_binding(item["path"]),
            }
            for item in selected_skills
        ],
        "literature": {
            "retriever_sources": list(literature.retriever_sources),
            "query_count": len(literature.queries),
            "fetch_count": len(literature.fetches),
            "failed_fetch_count": sum(item.status == "failed" for item in literature.fetches),
            "raw_hit_count": literature.raw_hit_count,
            "retrieved_record_count": len(literature.retrieved_records),
            "eligible_record_count": len(retrieval_catalog),
            "planning_record_count": len(planning_catalog),
            "excluded_records": excluded_records,
            "catalog_hash": canonical_model_hash({"catalog": list(retrieval_catalog)}),
            "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
            "planning_selection_method": (
                "soft_relevance_citation_age_venue_publication_source_topic_diversity_then_budget"
            ),
            "planning_reference_target_minimum": MIN_RESEARCH_PLAN_REFERENCES,
            "planning_reference_target_maximum": MAX_RESEARCH_PLAN_REFERENCES,
            "hard_minimum_citation_count_used": False,
            "journal_impact_factor_inferred_from_venue_name": False,
            "journal_impact_factor_used_only_when_value_and_source_are_present": True,
            "citation_unknown_distinct_from_zero": True,
            "finalist_status_verification_path": finalist_status_path.as_posix(),
            "finalist_status_verification_count": finalist_status_payload["verification_count"],
            "withdrawn_or_retracted_excluded_from_positive_planning": True,
            "planning_context_character_budget": _MAX_PLANNING_LITERATURE_CHARACTERS,
            "planning_context_character_count": sum(
                len(json.dumps(item, ensure_ascii=False, sort_keys=True)) + len(context)
                for item, context in zip(
                    planning_catalog,
                    planning_literature_context,
                    strict=True,
                )
            ),
            "eligible_catalog_truncated_for_model_context": (
                len(planning_catalog) < len(retrieval_catalog)
            ),
            "projection_timestamp_invented": False,
            "entries_from_real_search_only": True,
        },
        "research_objective": {
            "status": objective.status,
            "candidate_count": objective.candidate_count,
            "review_model_calls": objective.review_model_call_count,
            "temporary_runtime_identities_removed": True,
            "content_is_scientific_evidence": False,
        },
        "plan": {
            "plan_id": plan.plan_id,
            "title": plan.plan.paper_title,
            "references_from_real_retrieval_only": True,
            "preexperiment_executed": False,
            "formal_experiment_executed": False,
            "paper_claimed": False,
        },
        "pdf": {
            "path": rendered.pdf_path.resolve().as_posix(),
            "readable_text_verified": rendered.pdf_text_verified,
            "verified_page_count": verified_page_count,
            "page_count_method": page_count_method,
            "maximum_allowed_pages": _MAX_PDF_PAGES,
        },
        "main_artifacts": main_artifacts,
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
        "preexperiment_executed": False,
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    report_path = output_root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_selected_skills(
    routing: ContestDirectSkillRoutingArtifact,
    skill_bodies: Mapping[str, tuple[Path, str]],
) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    for skill_id in routing.selected_skill_ids:
        try:
            skill_path, content = skill_bodies[skill_id]
        except KeyError as exc:
            raise ContestDirectionPlanDeliveryError(
                f"router selected unavailable Skill: {skill_id}"
            ) from exc
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if routing.selected_skill_hashes.get(skill_id) != content_hash:
            raise ContestDirectionPlanDeliveryError(
                f"selected Skill changed after metadata routing: {skill_id}"
            )
        if hashlib.sha256(skill_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != (
            content_hash
        ):
            raise ContestDirectionPlanDeliveryError(
                f"selected Skill bytes changed before downstream injection: {skill_id}"
            )
        selected.append(
            {
                "skill_id": skill_id,
                "path": skill_path.resolve(),
                "content": content,
                "content_sha256": content_hash,
            }
        )
    return tuple(selected)


def _eligible_literature(
    artifact: ContestDirectionLiteratureArtifact,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], list[dict[str, str]]]:
    try:
        projected = artifact.objective_retrieval_catalog()
    except ContestDirectionLiteratureError as exc:
        raise ContestDirectionPlanDeliveryError(str(exc)) from exc
    projected_by_id = {str(item.get("record_id")): dict(item) for item in projected}
    full_entries = artifact.objective_literature_catalog()
    full_by_id = {
        record.record_id: entry
        for record, entry in zip(artifact.retrieved_records, full_entries, strict=True)
    }
    eligible: list[dict[str, Any]] = []
    contexts: list[str] = []
    excluded: list[dict[str, str]] = []
    for record in artifact.retrieved_records:
        projected_record = projected_by_id.get(record.record_id)
        reasons: list[str] = []
        publication_status = str(
            getattr(record, "publication_status", "unknown") or "unknown"
        ).casefold()
        if publication_status in {"withdrawn", "retracted"}:
            reasons.append(f"publication_status_{publication_status}")
        if projected_record is None:
            reasons.append("missing_url_or_doi")
        else:
            abstract = str(projected_record.get("abstract") or "").strip()
            source_url = str(
                projected_record.get("source_url") or projected_record.get("url") or ""
            ).strip()
            retrieved_from = str(projected_record.get("retrieved_from") or "").strip()
            retrieved_at = str(projected_record.get("retrieved_at") or "").strip()
            if not abstract:
                reasons.append("missing_abstract")
            if not source_url.lower().startswith(("https://", "http://")):
                reasons.append("missing_real_url_or_doi")
            if not retrieved_from:
                reasons.append("missing_retrieval_source")
            if not _is_aware_timestamp(retrieved_at):
                reasons.append("missing_or_naive_retrieval_time")
        if reasons:
            excluded.append({"record_id": record.record_id, "reason": ",".join(reasons)})
            continue
        assert projected_record is not None
        eligible.append(projected_record)
        contexts.append(full_by_id[record.record_id])
    if not eligible:
        raise ContestDirectionPlanDeliveryError(
            "no retrieved paper has source, retrieval time, abstract, and URL or DOI"
        )
    return tuple(eligible), tuple(contexts), excluded


def _select_planning_literature(
    eligible_catalog: Sequence[Mapping[str, Any]],
    literature_context: Sequence[str],
    *,
    queries: Sequence[str],
    priority_queries: Sequence[str] = (),
    priority_query_groups: Sequence[Sequence[str]] = (),
    minimum_records: int = 1,
    maximum_records: int = MAX_RESEARCH_PLAN_REFERENCES,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Select a quality-ranked complete-record subset without live enrichment."""

    selected, contexts, _verifications = _select_planning_literature_with_status(
        eligible_catalog,
        literature_context,
        queries=queries,
        priority_queries=priority_queries,
        priority_query_groups=priority_query_groups,
        arxiv_status_verifier=None,
        minimum_records=minimum_records,
        maximum_records=maximum_records,
    )
    return selected, contexts


def _select_planning_literature_with_status(
    eligible_catalog: Sequence[Mapping[str, Any]],
    literature_context: Sequence[str],
    *,
    queries: Sequence[str],
    priority_queries: Sequence[str] = (),
    priority_query_groups: Sequence[Sequence[str]] = (),
    arxiv_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
    minimum_records: int = 1,
    maximum_records: int = MAX_RESEARCH_PLAN_REFERENCES,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], list[dict[str, Any]]]:
    """Fit quality-ranked records into the planning context budget.

    The full retrieval artifact remains untouched.  This projection only ranks
    records by a soft, deterministic blend: query relevance dominates; citation
    counts are age-normalized; verified journal impact factor, publication/DOI
    metadata, cross-source corroboration, and source/topic novelty add smaller
    bonuses.  The delivery catalog targets five to ten complete records when the
    retrieved evidence and context budget permit.  There is no minimum citation
    threshold. Unknown citations remain unknown.

    Immediately before admitting an arXiv finalist, the production caller may
    verify only that finalist against its abstract page. Withdrawn/retracted
    records are retained in the full artifact but excluded from positive planning,
    and the next ranked candidate is considered. Abstracts are never truncated.
    """

    if len(eligible_catalog) != len(literature_context):
        raise ContestDirectionPlanDeliveryError(
            "eligible literature catalog and human-readable context differ in size"
        )
    if not eligible_catalog:
        raise ContestDirectionPlanDeliveryError("no eligible literature is available for planning")
    if minimum_records < 1 or maximum_records < minimum_records:
        raise ContestDirectionPlanDeliveryError("invalid planning bibliography bounds")

    effective_queries = tuple(dict.fromkeys((*queries, *priority_queries)))
    query_token_counts = Counter(_lexical_token_sequence(" ".join(effective_queries)))
    priority_token_counts = Counter(_lexical_token_sequence(" ".join(priority_queries)))
    query_tokens = frozenset(query_token_counts)
    query_theme_tokens = tuple(_lexical_tokens(query) for query in effective_queries)
    priority_theme_tokens = tuple(_lexical_tokens(query) for query in priority_queries)
    priority_group_themes = tuple(
        tuple(_lexical_tokens(query) for query in group if _lexical_tokens(query))
        for group in priority_query_groups
        if group
    )
    document_tokens = [
        _lexical_tokens(
            " ".join(
                (
                    str(item.get("title") or ""),
                    str(item.get("abstract") or ""),
                )
            )
        )
        for item in eligible_catalog
    ]
    document_title_tokens = [
        _lexical_tokens(str(item.get("title") or "")) for item in eligible_catalog
    ]
    document_count = len(document_tokens)
    document_frequency = {
        token: sum(token in tokens for tokens in document_tokens) for token in query_tokens
    }
    lexical_scores: list[float] = []
    priority_lexical_scores: list[float] = []
    priority_coherence_scores: list[float] = []
    priority_bridge_scores: list[float] = []
    for item, tokens in zip(eligible_catalog, document_tokens, strict=True):
        item_title_tokens = _lexical_tokens(str(item.get("title") or ""))
        score = 0.0
        priority_score = 0.0
        for token, query_weight in query_token_counts.items():
            if token not in tokens:
                continue
            inverse_frequency = (
                math.log((document_count + 1) / (document_frequency[token] + 1)) + 1.0
            )
            score += query_weight * inverse_frequency * (2.0 if token in item_title_tokens else 1.0)
        for token, query_weight in priority_token_counts.items():
            if token not in tokens:
                continue
            inverse_frequency = (
                math.log((document_count + 1) / (document_frequency[token] + 1)) + 1.0
            )
            priority_score += (
                query_weight * inverse_frequency * (2.0 if token in item_title_tokens else 1.0)
            )
        lexical_scores.append(score)
        priority_lexical_scores.append(priority_score)
        priority_coherence_scores.append(
            max(
                (
                    len(tokens & theme_tokens) / max(1, len(theme_tokens))
                    for theme_tokens in priority_theme_tokens
                    if theme_tokens
                ),
                default=0.0,
            )
        )
        group_scores = tuple(
            max(len(tokens & theme_tokens) / max(1, len(theme_tokens)) for theme_tokens in group)
            for group in priority_group_themes
            if group
        )
        priority_bridge_scores.append(min(group_scores, default=0.0))

    max_lexical = max(lexical_scores, default=0.0)
    max_priority_lexical = max(priority_lexical_scores, default=0.0)
    citation_signals = [_age_normalized_citation_signal(item) for item in eligible_catalog]
    max_citation_signal = max(citation_signals, default=0.0)
    impact_signals = [_verified_impact_factor_signal(item) for item in eligible_catalog]
    max_impact_signal = max(impact_signals, default=0.0)
    base_scores: list[float] = []
    for index, item in enumerate(eligible_catalog):
        broad_relevance = lexical_scores[index] / max_lexical if max_lexical > 0 else 0.0
        priority_relevance = (
            priority_lexical_scores[index] / max_priority_lexical
            if max_priority_lexical > 0
            else broad_relevance
        )
        if priority_group_themes:
            relevance = (
                (0.25 * broad_relevance)
                + (0.20 * priority_relevance)
                + (0.15 * priority_coherence_scores[index])
                + (0.40 * priority_bridge_scores[index])
            )
        else:
            relevance = (
                (0.45 * broad_relevance)
                + (0.30 * priority_relevance)
                + (0.25 * priority_coherence_scores[index])
            )
        citation = citation_signals[index] / max_citation_signal if max_citation_signal > 0 else 0.0
        impact = impact_signals[index] / max_impact_signal if max_impact_signal > 0 else 0.0
        publication = _publication_quality_signal(item)
        corroboration = min(1.0, len(_retrieval_sources(item)) / 2.0)
        base_scores.append(
            (0.70 * relevance)
            + (0.10 * citation)
            + (0.03 * impact)
            + (0.14 * publication)
            + (0.03 * corroboration)
            - _bibliographic_anomaly_penalty(item)
        )

    relevant_indices = {
        index
        for index, lexical_score in enumerate(lexical_scores)
        if lexical_score > 0
        and _has_disambiguated_query_relevance(
            eligible_catalog[index],
            query_tokens=query_tokens,
            queries=effective_queries,
        )
    }
    if not relevant_indices:
        raise ContestDirectionPlanDeliveryError(
            "retrieval produced no paper with positive query relevance; refusing to pad the plan "
            "with high-citation but off-topic records"
        )
    if len(relevant_indices) < minimum_records:
        raise ContestDirectionPlanDeliveryError(
            f"retrieval produced fewer than {minimum_records} query-relevant, "
            "provenance-complete papers; "
            "broaden the real search instead of padding or inventing references"
        )

    distinct_work_families = {
        _planning_budget_identity(eligible_catalog[index]) for index in relevant_indices
    }
    if len(distinct_work_families) < minimum_records:
        raise ContestDirectionPlanDeliveryError(
            f"retrieval produced fewer than {minimum_records} distinct query-relevant work "
            "families after exact-metadata duplicate-candidate suppression; broaden the real "
            "search instead of spending multiple reference slots on an unverified work family"
        )

    selected_indices: list[int] = []
    selected_records: dict[int, dict[str, Any]] = {}
    selected_contexts: dict[int, str] = {}
    remaining_indices = set(relevant_indices)
    covered_sources: set[str] = set()
    covered_query_themes: set[int] = set()
    covered_priority_themes: set[int] = set()
    selected_title_tokens: list[frozenset[str]] = []
    used_characters = 0
    oversized_record_indices: set[int] = set()
    verifications: list[dict[str, Any]] = []
    estimated_record_characters = [
        len(json.dumps(item, ensure_ascii=False, sort_keys=True))
        + len(context)
        + (
            _FINALIST_STATUS_CONTEXT_RESERVE
            if arxiv_status_verifier is not None
            and "arxiv" in _retrieval_sources(item)
            and str(item.get("publication_status") or "unknown").casefold() == "preprint"
            else 0
        )
        for item, context in zip(eligible_catalog, literature_context, strict=True)
    ]
    minimum_target = min(minimum_records, len(relevant_indices))
    while remaining_indices and len(selected_indices) < maximum_records:
        ranked_indices = sorted(
            remaining_indices,
            key=lambda candidate: (
                base_scores[candidate]
                + _planning_diversity_bonus(
                    candidate=candidate,
                    eligible_catalog=eligible_catalog,
                    title_tokens=document_title_tokens,
                    query_theme_tokens=query_theme_tokens,
                    priority_theme_tokens=priority_theme_tokens,
                    document_tokens=document_tokens,
                    covered_sources=covered_sources,
                    covered_query_themes=covered_query_themes,
                    covered_priority_themes=covered_priority_themes,
                    selected_title_tokens=selected_title_tokens,
                ),
                -candidate,
            ),
            reverse=True,
        )
        next_index = _next_budget_feasible_candidate(
            ranked_indices,
            estimated_record_characters=estimated_record_characters,
            used_characters=used_characters,
            selected_count=len(selected_indices),
            minimum_target=minimum_target,
        )
        if next_index is None:
            oversized_record_indices.update(
                candidate
                for candidate in remaining_indices
                if estimated_record_characters[candidate] > _MAX_PLANNING_LITERATURE_CHARACTERS
            )
            break
        index = next_index
        remaining_indices.remove(index)
        record_characters = len(
            json.dumps(eligible_catalog[index], ensure_ascii=False, sort_keys=True)
        ) + len(literature_context[index])
        if record_characters > _MAX_PLANNING_LITERATURE_CHARACTERS:
            oversized_record_indices.add(index)
            continue
        if used_characters + record_characters > _MAX_PLANNING_LITERATURE_CHARACTERS:
            continue
        record = dict(eligible_catalog[index])
        context = literature_context[index]
        record, context, verification = _verify_arxiv_finalist(
            record,
            context,
            verifier=arxiv_status_verifier,
        )
        verifications.append(verification)
        if str(record.get("publication_status") or "unknown").casefold() in {
            "withdrawn",
            "retracted",
        }:
            continue
        verified_record_characters = len(
            json.dumps(record, ensure_ascii=False, sort_keys=True)
        ) + len(context)
        if verified_record_characters > _MAX_PLANNING_LITERATURE_CHARACTERS:
            oversized_record_indices.add(index)
            continue
        if used_characters + verified_record_characters > _MAX_PLANNING_LITERATURE_CHARACTERS:
            continue
        selected_indices.append(index)
        selected_records[index] = record
        selected_contexts[index] = context
        covered_sources.update(_retrieval_sources(record))
        theme = _best_query_theme(document_tokens[index], query_theme_tokens)
        if theme is not None:
            covered_query_themes.add(theme)
        priority_theme = _best_query_theme(document_tokens[index], priority_theme_tokens)
        if (
            priority_theme is not None
            and document_tokens[index] & priority_theme_tokens[priority_theme]
        ):
            covered_priority_themes.add(priority_theme)
        selected_title_tokens.append(document_title_tokens[index])
        used_characters += verified_record_characters
        selected_family = _planning_work_family_key(record)
        if selected_family is not None:
            remaining_indices = {
                candidate
                for candidate in remaining_indices
                if _planning_work_family_key(eligible_catalog[candidate]) != selected_family
            }

    if not selected_indices:
        if len(oversized_record_indices) == len(relevant_indices):
            raise ContestDirectionPlanDeliveryError(
                "every complete planning literature record exceeds the character budget; "
                "records are never truncated"
            )
        raise ContestDirectionPlanDeliveryError(
            "no planning paper remains after shortlisted publication-status verification"
        )
    if len(selected_indices) < minimum_records:
        raise ContestDirectionPlanDeliveryError(
            f"fewer than {minimum_records} query-relevant papers remain after complete-record "
            "context fitting "
            "and publication-status verification"
        )
    return (
        tuple(selected_records[index] for index in selected_indices),
        tuple(selected_contexts[index] for index in selected_indices),
        verifications,
    )


def _next_budget_feasible_candidate(
    ranked_indices: Sequence[int],
    *,
    estimated_record_characters: Sequence[int],
    used_characters: int,
    selected_count: int,
    minimum_target: int,
) -> int | None:
    """Prefer rank while reserving enough context room to reach five records."""

    remaining_budget = _MAX_PLANNING_LITERATURE_CHARACTERS - used_characters
    fitting = [
        index for index in ranked_indices if estimated_record_characters[index] <= remaining_budget
    ]
    if not fitting:
        return None
    needed_after = max(0, minimum_target - selected_count - 1)
    if needed_after == 0:
        return fitting[0]
    for index in fitting:
        smallest_other_records = sorted(
            estimated_record_characters[candidate] for candidate in fitting if candidate != index
        )[:needed_after]
        if len(smallest_other_records) != needed_after:
            continue
        if estimated_record_characters[index] + sum(smallest_other_records) <= remaining_budget:
            return index
    # Return the best remaining complete record so the caller can produce a
    # precise insufficient-context failure after exhausting feasible choices;
    # abstracts are never truncated to manufacture the minimum count.
    return fitting[0]


def _planning_diversity_bonus(
    *,
    candidate: int,
    eligible_catalog: Sequence[Mapping[str, Any]],
    title_tokens: Sequence[frozenset[str]],
    query_theme_tokens: Sequence[frozenset[str]],
    priority_theme_tokens: Sequence[frozenset[str]],
    document_tokens: Sequence[frozenset[str]],
    covered_sources: set[str],
    covered_query_themes: set[int],
    covered_priority_themes: set[int],
    selected_title_tokens: Sequence[frozenset[str]],
) -> float:
    """Return a small source/topic novelty bonus; relevance remains dominant."""

    bonus = 0.0
    if _retrieval_sources(eligible_catalog[candidate]) - covered_sources:
        bonus += 0.025
    theme = _best_query_theme(document_tokens[candidate], query_theme_tokens)
    if theme is not None and theme not in covered_query_themes:
        bonus += 0.02
    if priority_theme_tokens:
        priority_theme = _best_query_theme(document_tokens[candidate], priority_theme_tokens)
        if (
            priority_theme is not None
            and priority_theme not in covered_priority_themes
            and document_tokens[candidate] & priority_theme_tokens[priority_theme]
        ):
            bonus += 0.025
    if selected_title_tokens:
        maximum_overlap = max(
            _jaccard(title_tokens[candidate], selected) for selected in selected_title_tokens
        )
        bonus += 0.015 * (1.0 - maximum_overlap)
    else:
        bonus += 0.015
    return bonus


def _planning_work_family_key(item: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Return a strict, domain-neutral *selection-only* work-family key.

    Different identifiers are never merged or declared to be the same publication.
    Exact normalized title, author order, and non-empty abstract only justify
    preventing content-identical mirrors from consuming separate planning budgets.
    Venue and date may differ across repository and publisher metadata, so requiring
    them would let the same content occupy multiple slots. Independent identities and
    provenance remain in the merged retrieval artifact; a registered relationship
    would need separate source metadata.
    """

    title = _normalize_exact_metadata(str(item.get("title") or ""))
    abstract = _normalize_exact_metadata(str(item.get("abstract") or ""))
    raw_authors = item.get("authors")
    if (
        not title
        or not abstract
        or not isinstance(raw_authors, Sequence)
        or isinstance(raw_authors, str | bytes | bytearray)
        or not raw_authors
    ):
        return None
    authors = tuple(_normalize_exact_metadata(str(author)) for author in raw_authors)
    if not all(authors):
        return None
    return (
        "unverified-exact-metadata-work-family",
        title,
        authors,
        abstract,
    )


def _planning_budget_identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
    family = _planning_work_family_key(item)
    if family is not None:
        return family
    record_id = str(item.get("record_id") or "").strip()
    if record_id:
        return ("independent-record", record_id)
    return ("independent-record-payload", canonical_model_hash(dict(item)))


def _planning_work_family_suppressions(
    candidate_catalog: Sequence[Mapping[str, Any]],
    selected_catalog: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Explain budget suppression without collapsing bibliographic identity."""

    selected_by_family = {
        family: item
        for item in selected_catalog
        if (family := _planning_work_family_key(item)) is not None
    }
    selected_ids = {str(item.get("record_id") or "") for item in selected_catalog}
    suppressions: list[dict[str, Any]] = []
    for item in candidate_catalog:
        record_id = str(item.get("record_id") or "")
        family = _planning_work_family_key(item)
        representative = selected_by_family.get(family) if family is not None else None
        if representative is None or record_id in selected_ids:
            continue
        suppressions.append(
            {
                "suppressed_record_id": record_id,
                "suppressed_record_sha256": item.get("record_sha256"),
                "suppressed_publication_doi": item.get("publication_doi") or item.get("doi"),
                "representative_record_id": str(representative.get("record_id") or ""),
                "representative_record_sha256": representative.get("record_sha256"),
                "representative_publication_doi": (
                    representative.get("publication_doi") or representative.get("doi")
                ),
                "reason": "same_exact_title_authors_abstract_candidate",
                "identity_merged": False,
                "registered_relation_verified": False,
                "interpretation": (
                    "selection-budget duplicate candidate only; publication relationship "
                    "remains unverified"
                ),
            }
        )
    return tuple(suppressions)


def _normalize_exact_metadata(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _best_query_theme(
    document: frozenset[str],
    query_themes: Sequence[frozenset[str]],
) -> int | None:
    if not query_themes:
        return None
    return max(
        range(len(query_themes)),
        key=lambda index: (
            len(document & query_themes[index]) / max(1, len(query_themes[index])),
            -index,
        ),
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _age_normalized_citation_signal(item: Mapping[str, Any]) -> float:
    count = item.get("citation_count")
    if isinstance(count, bool) or not isinstance(count, int | float) or count < 0:
        return 0.0
    publication_date = _parse_iso_date(item.get("publication_date"))
    as_of = _parse_iso_date(item.get("citation_count_as_of"))
    if as_of is None:
        retrieved_dates = [
            parsed
            for source_date in (item.get("retrieved_at"),)
            if (parsed := _parse_iso_date(source_date)) is not None
        ]
        as_of = max(retrieved_dates, default=None)
    if publication_date is None or as_of is None:
        age_years = 5.0
    else:
        age_years = max(0.5, (as_of - publication_date).days / 365.2425)
    return math.log1p(float(count) / age_years)


def _verified_impact_factor_signal(item: Mapping[str, Any]) -> float:
    value = item.get("journal_impact_factor")
    source = str(item.get("journal_impact_factor_source") or "").strip()
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0 or not source:
        return 0.0
    return math.log1p(float(value))


def _publication_quality_signal(item: Mapping[str, Any]) -> float:
    status = str(item.get("publication_status") or "unknown").casefold()
    status_signal = {"published": 0.6, "unknown": 0.25, "preprint": 0.05}.get(
        status,
        0.0,
    )
    publication_doi = str(item.get("publication_doi") or item.get("doi") or "").strip()
    venue = str(item.get("venue") or "").strip()
    repository_doi = str(item.get("repository_doi") or "").strip()
    return min(
        1.0,
        status_signal
        + (0.25 if publication_doi else 0.0)
        + (0.1 if venue else 0.0)
        + (0.05 if repository_doi else 0.0),
    )


def _bibliographic_anomaly_penalty(item: Mapping[str, Any]) -> float:
    """Softly downrank incomplete reviews and table-of-contents metadata.

    Bibliographic APIs sometimes attach a book's entire table of contents and
    citation count to an authorless review record.  Such a record may be broadly
    relevant but should not outrank focused primary/method papers.  The signal is
    deliberately a penalty, not an exclusion, so sparse domains can still retain
    the source as background evidence.
    """

    penalty = 0.0
    authors = item.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, str) or not authors:
        penalty += 0.08
    venue = str(item.get("venue") or "").casefold()
    if "review" in venue or "choice reviews" in venue:
        penalty += 0.12
    abstract = str(item.get("abstract") or "")
    numbered_sections = len(re.findall(r"(?:^|[.\-]\s)(?:\d+\.){1,2}\d*\s", abstract))
    if len(abstract) >= 2_000 and numbered_sections >= 12:
        penalty += 0.18
    return penalty


def _retrieval_sources(item: Mapping[str, Any]) -> set[str]:
    raw = str(item.get("retrieved_from") or item.get("paper_source") or "")
    return {source.strip().casefold() for source in raw.split(",") if source.strip()}


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _is_transport_error(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in {"TimeoutError", "ConnectionError", "URLError", "socket.timeout"}:
        return True
    if isinstance(exc, OSError):
        return exc.errno in {
            10060,  # WinError: connection timed out
            10061,  # WinError: connection refused
            110,  # ETIMEDOUT
            101,  # ENETUNREACH
        }
    message = str(exc).casefold()
    return any(
        token in message
        for token in ("timed out", "timeout", "unreachable", "refused", "name or service")
    )


def _finalist_status_cache_path() -> Path:
    return Path(".cache/autoresearch/arxiv-finalist-status-cache.json")


def _load_finalist_status_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _store_finalist_status_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        # The cache is a bounded convenience; a write failure never blocks the run.
        return


def _verification_transport_retry_seconds() -> float:
    return 1.5


def _verify_arxiv_finalist(
    record: dict[str, Any],
    context: str,
    *,
    verifier: Callable[[AcademicPaper], AcademicPaper] | None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    sources = _retrieval_sources(record)
    original_status = str(record.get("publication_status") or "unknown")
    arxiv_status_url = _arxiv_status_url(record)
    catalog_source_url = str(record.get("source_url") or record.get("url") or "")
    receipt: dict[str, Any] = {
        "record_id": str(record.get("record_id") or ""),
        "source_url": catalog_source_url,
        "original_status": original_status,
        "verification_attempted": False,
        "verified_status": original_status,
        "status_source": record.get("status_source"),
        "status_as_of": record.get("status_as_of"),
        "outcome": "not_arxiv_or_verifier_disabled",
        "error": None,
    }
    if verifier is None or "arxiv" not in sources or original_status.casefold() != "preprint":
        return record, context, receipt
    if arxiv_status_url is None:
        receipt["outcome"] = "arxiv_shortlist_missing_verifiable_arxiv_url"
        return record, context, receipt

    receipt["verification_attempted"] = True
    paper = AcademicPaper(
        title=str(record.get("title") or "untitled shortlisted record"),
        authors=[str(author) for author in record.get("authors") or ()],
        abstract=str(record.get("abstract") or "") or None,
        publication_date=_parse_iso_date(record.get("publication_date")),
        venue=str(record.get("venue") or "") or None,
        doi=str(record.get("publication_doi") or record.get("doi") or "") or None,
        repository_doi=str(record.get("repository_doi") or "") or None,
        url=arxiv_status_url,
        citation_count=(
            record.get("citation_count")
            if isinstance(record.get("citation_count"), int)
            and not isinstance(record.get("citation_count"), bool)
            else None
        ),
        citation_count_source=str(record.get("citation_count_source") or "") or None,
        citation_count_as_of=_parse_iso_date(record.get("citation_count_as_of")),
        publication_status=cast(
            PublicationStatus,
            original_status
            if original_status in {"unknown", "preprint", "published", "withdrawn", "retracted"}
            else "unknown",
        ),
        status_source=str(record.get("status_source") or "") or None,
        status_as_of=_parse_iso_date(record.get("status_as_of")),
        source="arxiv",
    )
    cache_path = _finalist_status_cache_path()
    cache_key = hashlib.sha256(
        f"{arxiv_status_url}\n{original_status}".encode()
    ).hexdigest()
    cache = _load_finalist_status_cache(cache_path)
    cached = cache.get(cache_key)
    cached_age_days: float | None = None
    if isinstance(cached, dict) and cached.get("cached_at"):
        try:
            cached_at = datetime.fromisoformat(str(cached["cached_at"]))
            cached_age_days = (datetime.now(timezone.utc) - cached_at).total_seconds() / 86_400
        except ValueError:
            pass
    verified: AcademicPaper | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            verified = verifier(paper)
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001 - bounded retry for transport only
            last_error = exc
            if not _is_transport_error(exc):
                break
            if attempt == 0:
                time.sleep(_verification_transport_retry_seconds())
    if verified is None:
        assert last_error is not None
        if (
            _is_transport_error(last_error)
            and cached is not None
            and cached.get("verified_status") in {"published", "preprint", "unknown"}
            and cached_age_days is not None
            and 0 <= cached_age_days <= 7
        ):
            record.update(
                {
                    "publication_status": cached["verified_status"],
                    "status_source": cached.get("status_source"),
                    "status_as_of": cached.get("status_as_of"),
                }
            )
            receipt["outcome"] = "verification_served_from_cache"
            receipt["verified_status"] = cached["verified_status"]
            receipt["status_source"] = cached.get("status_source")
            receipt["status_as_of"] = cached.get("status_as_of")
            receipt["error"] = f"{type(last_error).__name__}: {last_error}"
            receipt["cache_key"] = cache_key
            verification_line = (
                "最终候选状态复核（跨运行缓存，不改变原检索record_sha256）："
                f"{cached['verified_status']}；来源={cached.get('status_source') or 'unknown'}；"
                f"截至={cached.get('status_as_of') or 'unknown'}"
            )
            return record, f"{context}\n{verification_line}", receipt
        outcome = (
            "verification_failed_transport_preserved"
            if _is_transport_error(last_error)
            else "verification_failed_preserved_as_non_authoritative"
        )
        receipt["outcome"] = outcome
        receipt["error"] = f"{type(last_error).__name__}: {last_error}"
        return record, context, receipt

    cache[cache_key] = {
        "source_url": arxiv_status_url,
        "original_status": original_status,
        "verified_status": verified.publication_status,
        "status_source": verified.status_source,
        "status_as_of": (
            verified.status_as_of.isoformat() if verified.status_as_of is not None else None
        ),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _store_finalist_status_cache(cache_path, cache)

    record.update(
        {
            "publication_status": verified.publication_status,
            "status_source": verified.status_source,
            "status_as_of": (
                verified.status_as_of.isoformat() if verified.status_as_of is not None else None
            ),
        }
    )
    receipt.update(
        {
            "verified_status": verified.publication_status,
            "status_source": verified.status_source,
            "status_as_of": record["status_as_of"],
            "outcome": (
                "excluded_from_positive_planning"
                if verified.publication_status in {"withdrawn", "retracted"}
                else "eligible_after_verification"
            ),
        }
    )
    verification_line = (
        "最终候选状态复核（不改变原检索record_sha256）："
        f"{verified.publication_status}；来源={verified.status_source or 'unknown'}；"
        f"截至={record['status_as_of'] or 'unknown'}"
    )
    return record, f"{context}\n{verification_line}", receipt


def _arxiv_status_url(record: Mapping[str, Any]) -> str | None:
    for field in ("source_url", "url"):
        value = str(record.get(field) or "").strip()
        if re.match(
            r"^https?://(?:(?:www|export)\.)?arxiv\.org/(?:abs|pdf)/",
            value,
            flags=re.IGNORECASE,
        ):
            return value
    repository_doi = str(record.get("repository_doi") or "").strip()
    match = re.fullmatch(
        r"10\.48550/arxiv\.([A-Za-z0-9._/-]+)",
        repository_doi,
        flags=re.IGNORECASE,
    )
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"
    return None


def _has_disambiguated_query_relevance(
    item: Mapping[str, Any],
    *,
    query_tokens: frozenset[str],
    queries: Sequence[str],
) -> bool:
    """Reject ambiguous one-word homonyms without imposing a citation gate.

    A record is query-relevant when it either shares at least three independent
    concepts from the *same* query theme, contains a multi-token phrase from one
    Boolean query clause, or answers a genuinely one/two-concept query.  Requiring
    within-theme coherence prevents unrelated records from accumulating generic
    tokens across several broad queries.  Thus an old, uncited but directly
    relevant paper remains eligible, while highly cited biology or cognition
    papers containing isolated homonyms cannot enter a number-theory bibliography.
    """

    document_sequence = _lexical_token_sequence(
        " ".join((str(item.get("title") or ""), str(item.get("abstract") or "")))
    )
    document_tokens = frozenset(document_sequence)
    overlap_count = len(document_tokens & query_tokens)
    if len(query_tokens) <= 2:
        return overlap_count >= 1
    query_theme_overlap = max(
        (len(document_tokens & _lexical_tokens(query)) for query in queries),
        default=0,
    )
    if overlap_count >= 3 and query_theme_overlap >= 3:
        return True
    return any(
        _contains_token_sequence(document_sequence, phrase)
        for phrase in _query_clause_phrases(queries)
    )


def _query_clause_phrases(queries: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    phrases: list[tuple[str, ...]] = []
    for query in queries:
        for clause in re.split(r"\b(?:AND|OR|NOT)\b|[()]", query, flags=re.IGNORECASE):
            tokens = _lexical_token_sequence(clause)
            for size in range(len(tokens), 1, -1):
                for start in range(len(tokens) - size + 1):
                    phrase = tokens[start : start + size]
                    if phrase not in phrases:
                        phrases.append(phrase)
    return tuple(phrases)


def _contains_token_sequence(
    document: Sequence[str],
    phrase: Sequence[str],
) -> bool:
    if not phrase or len(phrase) > len(document):
        return False
    size = len(phrase)
    return any(
        tuple(document[index : index + size]) == tuple(phrase)
        for index in range(len(document) - size + 1)
    )


def _lexical_tokens(value: str) -> frozenset[str]:
    return frozenset(_lexical_token_sequence(value))


def _lexical_token_sequence(value: str) -> tuple[str, ...]:
    return tuple(
        _LEXICAL_TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in _LEXICAL_STOP_WORDS
    )


def _verify_plan_references(
    artifact: _PlanReferenceView,
    *,
    literature_context: Sequence[str],
    minimum_references: int = MIN_RESEARCH_PLAN_REFERENCES,
    maximum_references: int = MAX_RESEARCH_PLAN_REFERENCES,
) -> None:
    references = artifact.plan.references
    reference_projection = getattr(artifact, "reference_projection", None)
    try:
        validate_locked_bibliography(
            references,
            literature_context,
            minimum=minimum_references,
            maximum=maximum_references,
            require_exact_catalog=(
                reference_projection is not None
                and getattr(reference_projection, "policy", None) == "locked-catalog-exact-order-v2"
            ),
        )
    except ValueError as exc:
        raise ContestDirectionPlanDeliveryError(
            f"direction plan bibliography failed the locked real-catalog contract: {exc}"
        ) from exc


def _verify_rendered_pdf(
    rendered: ContestDirectPlanArtifacts,
) -> tuple[int, str]:
    pdf_path = rendered.pdf_path.resolve()
    if not rendered.pdf_text_verified or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise ContestDirectionPlanDeliveryError(
            "materialized research-plan PDF is missing or not text-readable"
        )
    if rendered.page_count is not None:
        page_count = rendered.page_count
        method = "renderer"
    else:
        page_count, method = _independent_pdf_page_count(pdf_path)
    if page_count < 1:
        raise ContestDirectionPlanDeliveryError("research-plan PDF has no readable page")
    if page_count > _MAX_PDF_PAGES:
        raise ContestDirectionPlanDeliveryError(
            f"research-plan PDF has {page_count} pages; maximum is {_MAX_PDF_PAGES}"
        )
    return page_count, method


def _independent_pdf_page_count(path: Path) -> tuple[int, str]:
    # On Windows the Codex runtime may prepend a nonfunctional ``pdfinfo.CMD``
    # override ahead of the real TeX Live binary.  Ask for the executable first.
    pdfinfo = shutil.which("pdfinfo.exe") or shutil.which("pdfinfo")
    if pdfinfo:
        try:
            completed = subprocess.run(
                [pdfinfo, str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            pass
        else:
            match = re.search(r"(?im)^Pages:\s*(\d+)\s*$", completed.stdout)
            if match:
                return int(match.group(1)), "pdfinfo"
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name, fromlist=["PdfReader"])
            reader = module.PdfReader(str(path))
            return len(reader.pages), module_name
        except (ImportError, OSError, ValueError):
            continue
    raise ContestDirectionPlanDeliveryError(
        "renderer returned no page count and independent PDF page counting failed"
    )


def _write_literature_failure(
    *,
    output_root: Path,
    direction: str,
    stage: str,
    error: Exception,
    fetches: Sequence[Any],
) -> Path:
    fetch_payloads = [_model_payload(item) for item in fetches]
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-literature-failure-v1",
        "status": "failed",
        "input_mode": "specified_direction",
        "direction": direction,
        "failure_stage": stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "fetches": fetch_payloads,
        "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "static_catalog_fallback_used": False,
    }
    payload["failure_hash"] = canonical_model_hash(payload)
    path = output_root / "direction-literature-failure.json"
    _write_new_json(path, payload)
    return path


def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
        if isinstance(result, dict):
            return result
    return {"unstructured_record": str(value)}


def _is_aware_timestamp(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _inside_output(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ContestDirectionPlanDeliveryError(
            f"generated artifact escapes output directory: {candidate}"
        ) from exc
    return candidate


def _verify_internal_hash_file(path: Path, *, field: str, expected: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectionPlanDeliveryError(
            f"cannot read generated artifact: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or payload.get(field) != expected:
        raise ContestDirectionPlanDeliveryError(
            f"generated artifact internal hash mismatch: {path}"
        )


def _rendered_bindings(rendered: ContestDirectPlanArtifacts) -> dict[str, Any]:
    return {
        "json": _file_binding(rendered.json_path),
        "markdown": _file_binding(rendered.markdown_path),
        "tex": _file_binding(rendered.tex_path),
        "pdf": _file_binding(rendered.pdf_path),
        "manifest": _file_binding(rendered.manifest_path),
        "source_payload_sha256": rendered.source_payload_sha256,
        "renderer_page_count": rendered.page_count,
        "pdf_text_verified": rendered.pdf_text_verified,
    }


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    report_path = (root / "delivery-report.json").resolve()
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if not resolved.is_file() or resolved == report_path:
            continue
        files.append(
            {
                "relative_path": resolved.relative_to(root).as_posix(),
                **_file_binding(resolved),
            }
        )
    return files


def _file_binding(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContestDirectionPlanDeliveryError(f"bound file does not exist: {resolved}")
    return {
        "path": resolved.as_posix(),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _prepare_empty_output(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ContestDirectionPlanDeliveryError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise ContestDirectionPlanDeliveryError(
                f"output directory must be new or empty: {path}"
            )
    else:
        path.mkdir(parents=True, exist_ok=False)


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ContestDirectionPlanDeliveryError(
            f"refusing to overwrite delivery artifact: {path}"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从指定研究方向经真实学术检索、目标评审，一次生成中文研究计划。"
    )
    parser.add_argument("--direction", required=True)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--skills-root", type=Path, default=_DEFAULT_SKILLS_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--max-results-per-search", type=int, default=20)
    parser.add_argument("--skill-routing-max-tokens", type=int, default=1_024)
    parser.add_argument("--query-max-tokens", type=int, default=768)
    parser.add_argument("--brainstorm-max-tokens", type=int, default=2_600)
    parser.add_argument("--review-max-tokens", type=int, default=3_200)
    parser.add_argument("--plan-max-tokens", type=int, default=12_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--thinking-budget", type=int, default=3_000)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_direction_plan_delivery(
        direction=args.direction,
        output_dir=args.output_dir,
        skills_root=args.skills_root,
        config_path=args.config,
        env_path=args.env,
        max_results_per_search=args.max_results_per_search,
        skill_routing_max_tokens=args.skill_routing_max_tokens,
        query_max_tokens=args.query_max_tokens,
        brainstorm_max_tokens=args.brainstorm_max_tokens,
        review_max_tokens=args.review_max_tokens,
        plan_max_tokens=args.plan_max_tokens,
        timeout_seconds=args.timeout_seconds,
        thinking_budget=args.thinking_budget,
        render_timeout_seconds=args.render_timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - module smoke covers parser wiring
    raise SystemExit(main())


__all__ = [
    "ContestDirectionPlanDeliveryError",
    "main",
    "run_contest_direction_plan_delivery",
]
