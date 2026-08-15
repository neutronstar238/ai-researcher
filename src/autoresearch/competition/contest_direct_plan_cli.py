"""Delivery-first entry point for one Chinese contest research plan.

This module intentionally bypasses the formal multi-stage competition lineage.  It
reuses three small, independently testable pieces:

* deterministic extraction of question 1 from the user-supplied Science booklet;
* one metadata-only configured-model call that selects relevant project Skills;
* three temporary brainstormers plus one independently dispatched objective reviewer;
* one configured-model call that authors all plan prose after Skill loading and review;
* presentation-only materialization to JSON, Markdown, TeX, and a real PDF.

There is no opportunity-grid coverage quota, enum rubric, prose-length threshold,
multi-round reviewer, or experiment claim in this path.  The resulting document is
a research plan.  When no pre-experiment context is supplied, its Results section
must say that no experiment has been run rather than inventing observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from autoresearch.agents.temporary import (
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    issue_stage_controller,
)
from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    generate_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectSkillMetadata,
    ContestDirectSkillRoutingArtifact,
    route_contest_direct_plan_skills,
)
from autoresearch.competition.contest_question_input import (
    ContestQuestionInput,
    extract_first_science_125_question,
)
from autoresearch.competition.contest_research_objective_stage import (
    ContestResearchObjectiveStageArtifact,
    run_contest_research_objective_stage,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenSkillContext

_DEFAULT_PDF = Path(r"C:\Users\Z\Downloads\sjtu-booklet.pdf")
_DEFAULT_OUTPUT = Path("runs/contest-delivery/science125-question-001")
_DEFAULT_SKILLS_ROOT = Path("skills")
_DIRECT_PLAN_REQUIREMENTS = (
    "生成符合榜题模板的完整中文《科学假设与研究计划》",
    "质量优先，围绕一个可证伪主假设形成可执行研究路径",
    "引用只使用提供的真实来源",
    "无预实验输入时明确尚未执行，不虚构结果或数值",
)
_URL_PATTERN = re.compile(r"https?://[^\s;]+")


def default_question_one_reference_catalog(question: ContestQuestionInput) -> tuple[str, ...]:
    """Return a caller-owned catalog of real, directly identifiable sources.

    Qwen may use these entries but cannot add bibliography records: the one-shot core
    replaces its bibliography with this exact tuple.  The automation references are
    methodological precedents supplied by the user; the number-theory and dataset
    entries support the actual first-question plan.
    """

    return (
        (
            "Science/AAAS. 125 Questions: Exploration and Discovery (2021), "
            f"question 1: {question.question_en}. Local source SHA-256: "
            f"{question.source_file_sha256}; source: {question.source_pdf_path}; "
            "https://www.science.org/cms/asset/"
            "b09620dc-2937-45bd-9c29-3ea07c1f4a04/sjtu-booklet.pdf"
        ),
        (
            "Agrawal M, Kayal N, Saxena N. PRIMES is in P. Annals of Mathematics "
            "160(2), 2004, 781-793. https://annals.math.princeton.edu/2004/160-2/p12"
        ),
        (
            "Green B, Tao T. The primes contain arbitrarily long arithmetic "
            "progressions. Annals of Mathematics 167(2), 2008, 481-547. "
            "https://annals.math.princeton.edu/2008/167-2/p01"
        ),
        (
            "Rivest RL, Shamir A, Adleman L. A method for obtaining digital signatures "
            "and public-key cryptosystems. Communications of the ACM 21(2), 1978, "
            "120-126. https://dl.acm.org/doi/10.1145/359340.359342"
        ),
        (
            "OEIS Foundation. A000040: The prime numbers. https://oeis.org/A000040; "
            "A001223: prime gaps. https://oeis.org/A001223"
        ),
        (
            "Bandt C, Pompe B. Permutation Entropy: A Natural Complexity Measure "
            "for Time Series. Physical Review Letters 88, 174102 (2002). "
            "https://doi.org/10.1103/PhysRevLett.88.174102"
        ),
        (
            "Gallagher PX. On the distribution of primes in short intervals. "
            "Mathematika 23(1), 1976, 4-9. "
            "https://doi.org/10.1112/S0025579300016442"
        ),
        (
            "Granville A. Harald Cramer and the distribution of prime numbers. "
            "Scandinavian Actuarial Journal 1995(1), 12-28. "
            "https://doi.org/10.1080/03461238.1995.10413946"
        ),
        (
            "Chagas ETC, Frery AC, Gambini J, Lucini MM, Ramos HS, Rey AA. "
            "Statistical properties of the entropy from ordinal patterns. "
            "Chaos 32, 113118 (2022). https://doi.org/10.1063/5.0118706"
        ),
        (
            "Bian C, Qin C, Ma QDY, Shen Q. Modified permutation-entropy analysis "
            "of heartbeat dynamics. Physical Review E 85, 021906 (2012). "
            "https://doi.org/10.1103/PhysRevE.85.021906"
        ),
        (
            "Lemke Oliver RJ, Soundararajan K. Unexpected biases in the distribution "
            "of consecutive primes. Proceedings of the National Academy of Sciences "
            "113(31), E4446-E4454 (2016). "
            "https://doi.org/10.1073/pnas.1605366113"
        ),
        (
            "Banks W, Ford K, Tao T. Large prime gaps and probabilistic models. "
            "Inventiones Mathematicae 233, 1471-1518 (2023). "
            "https://doi.org/10.1007/s00222-023-01199-0"
        ),
        (
            "Phipson B, Smyth GK. Permutation P-values Should Never Be Zero: "
            "Calculating Exact P-values When Permutations Are Randomly Drawn. "
            "Statistical Applications in Genetics and Molecular Biology 9(1), "
            "Article 39 (2010). https://doi.org/10.2202/1544-6115.1585"
        ),
        (
            "Paninski L. Estimation of Entropy and Mutual Information. Neural "
            "Computation 15(6), 1191-1253 (2003). "
            "https://doi.org/10.1162/089976603321780272"
        ),
        (
            "StarWhisper Telescope: an AI framework for automating end-to-end "
            "astronomical observations. Nature, 2025. "
            "https://www.nature.com/articles/s44172-025-00520-4"
        ),
        (
            "Automated synthesis of oxygen-producing catalysts from Martian meteorites "
            "by a robotic AI chemist. Nature Synthesis, 2023. "
            "https://www.nature.com/articles/s44160-023-00424-1"
        ),
        (
            "SakanaAI. The AI Scientist: Towards Fully Automated Open-Ended Scientific "
            "Discovery. https://github.com/SakanaAI/AI-Scientist"
        ),
        (
            "SakanaAI. The AI Scientist-v2: Workshop-Level Automated Scientific "
            "Discovery via Agentic Tree Search. "
            "https://github.com/SakanaAI/AI-Scientist-v2"
        ),
    )


def objective_literature_from_locked_catalog(
    references: Sequence[str],
    *,
    retrieved_at: datetime | None = None,
) -> tuple[dict[str, str], ...]:
    """Project caller-locked references into provenance-bearing objective inputs.

    This helper never invents a bibliography entry.  It only admits entries that
    already contain an explicit HTTP(S) source URL; the objective stage can then
    expose catalog numbers while keeping candidate agents unable to add sources.
    """

    timestamp = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retrieved_at_text = timestamp.isoformat().replace("+00:00", "Z")
    catalog: list[dict[str, str]] = []
    for reference in references:
        match = _URL_PATTERN.search(reference)
        if match is None:
            continue
        catalog.append(
            {
                "title": reference,
                "url": match.group(0).rstrip(".,)"),
                "retrieved_from": "caller_locked_contest_reference_catalog",
                "retrieved_at": retrieved_at_text,
            }
        )
    return tuple(catalog)


def plan_payload_for_render(
    artifact: ContestDirectPlanArtifact,
    *,
    question: ContestQuestionInput,
) -> dict[str, Any]:
    """Map the one-shot artifact to the contest template without rewriting prose."""

    plan = artifact.plan
    return {
        "title": plan.paper_title,
        "abstract": plan.paper_abstract,
        "problem_statement": plan.problem_statement,
        "rationale": plan.rationale,
        "technical_details": plan.technical_details,
        "datasets": {
            "description": plan.datasets,
            "source": plan.source,
            "target": plan.target,
        },
        "methods": plan.methods,
        "experiments": plan.experiments,
        "baselines": plan.baselines,
        "metrics": plan.metrics,
        "results": plan.results,
        "references": list(plan.references),
        "document_type": artifact.document_type,
        "status": artifact.status,
        "question": question.model_dump(mode="json"),
        "generation": {
            "provider": artifact.provider,
            "model_name": artifact.model_name,
            "generation_calls": artifact.generation_calls,
            "input_hash": artifact.input_hash,
            "model_response_hash": artifact.model_response_hash,
            "artifact_hash": artifact.artifact_hash,
            "json_repair_applied": artifact.json_repair_applied,
        },
    }


def discover_contest_method_skills(
    skills_root: Path | str,
) -> tuple[tuple[ContestDirectSkillMetadata, ...], dict[str, tuple[Path, str]]]:
    """Discover project Skills while exposing only frontmatter metadata to Qwen."""

    root = Path(skills_root).resolve()
    catalog: list[ContestDirectSkillMetadata] = []
    bodies: dict[str, tuple[Path, str]] = {}
    for skill_path in sorted(root.glob("*/SKILL.md")):
        content = skill_path.read_text(encoding="utf-8")
        metadata = _skill_frontmatter(content, skill_path=skill_path)
        skill_id = skill_path.parent.name
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        catalog.append(
            ContestDirectSkillMetadata(
                skill_id=skill_id,
                name=metadata["name"],
                description=metadata["description"],
                content_sha256=digest,
            )
        )
        bodies[skill_id] = (skill_path, content)
    if not catalog:
        raise ValueError(f"没有在 {root} 发现可用的 */SKILL.md")
    return tuple(catalog), bodies


def _skill_frontmatter(content: str, *, skill_path: Path) -> dict[str, str]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError(f"Skill 缺少 YAML frontmatter: {skill_path}")
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError(f"Skill frontmatter 未闭合: {skill_path}")
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            values[key.strip()] = value.strip().strip("\"'")
    if not values.get("name") or not values.get("description"):
        raise ValueError(f"Skill 必须包含 name 与 description: {skill_path}")
    return values


def run_contest_question_one_delivery(
    *,
    question_pdf: Path | str = _DEFAULT_PDF,
    output_dir: Path | str = _DEFAULT_OUTPUT,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    preexperiment_context: Any | None = None,
    skills_root: Path | str = _DEFAULT_SKILLS_ROOT,
    max_tokens: int | None = 12_000,
    timeout_seconds: int | None = 900,
    overwrite: bool = True,
    question_extractor: Callable[..., ContestQuestionInput] = (extract_first_science_125_question),
    skill_router: Callable[..., ContestDirectSkillRoutingArtifact] = (
        route_contest_direct_plan_skills
    ),
    objective_stage_runner: Callable[..., ContestResearchObjectiveStageArtifact] = (
        run_contest_research_objective_stage
    ),
    plan_generator: Callable[..., ContestDirectPlanArtifact] = generate_contest_direct_plan,
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
) -> dict[str, Any]:
    """Route Skills after seeing question 1, then generate without a review loop."""

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    question = question_extractor(question_pdf)
    question_path = output / "question-input.json"
    question_path.write_text(
        json.dumps(question.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    catalog, skill_bodies = discover_contest_method_skills(skills_root)
    routing_path = output / "skill-routing.json"
    routing = skill_router(
        question=(
            f"{question.question_zh}\n原始英文问题：{question.question_en}\n"
            f"来源：《{question.source_title}》第{question.ordinal}题。"
        ),
        requirements=_DIRECT_PLAN_REQUIREMENTS,
        skill_catalog=catalog,
        config_path=config_path,
        env_path=env_path,
        output_path=routing_path,
        timeout_seconds=timeout_seconds,
        max_tokens=1_024,
    )
    selected_skills: list[tuple[str, Path, str, str]] = []
    for skill_id in routing.selected_skill_ids:
        skill_path, skill_content = skill_bodies[skill_id]
        digest = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        if routing.selected_skill_hashes[skill_id] != digest:
            raise ValueError(f"选中 Skill 在路由后发生变化: {skill_id}")
        selected_skills.append((skill_id, skill_path, skill_content, digest))

    references = default_question_one_reference_catalog(question)
    question_binding_hash = canonical_model_hash(question.model_dump(mode="json"))
    objective_stage_input_hash = canonical_model_hash(
        {
            "question_binding_hash": question_binding_hash,
            "skill_routing_hash": routing.artifact_hash,
            "selected_skill_hashes": routing.selected_skill_hashes,
            "requirements": list(_DIRECT_PLAN_REQUIREMENTS),
            "literature_catalog": list(references),
        }
    )
    brainstorm_controller, brainstorm_capability = issue_stage_controller(
        lineage_id=question.question_id,
        stage="research-objective-brainstorm",
        stage_attempt=1,
        controller_agent_id="contest-direct-main-agent",
        stage_input_hash=objective_stage_input_hash,
        max_parallel_agents=3,
    )
    review_controller, review_capability = issue_stage_controller(
        lineage_id=question.question_id,
        stage="research-objective-review",
        stage_attempt=1,
        controller_agent_id="contest-direct-main-agent",
        stage_input_hash=objective_stage_input_hash,
        max_parallel_agents=1,
    )
    temporary_skill_contexts = tuple(
        TemporaryQwenSkillContext(
            skill_ref=TemporaryAgentSkillRef(
                skill_id=skill_id,
                source_ref=skill_path.as_posix(),
                content_sha256=digest,
            ),
            content=content,
        )
        for skill_id, skill_path, content, digest in selected_skills
    )
    objective_stage = objective_stage_runner(
        mode="specified_question",
        seed_text=(
            f"{question.question_zh}\n原始英文问题：{question.question_en}\n"
            f"来源：《{question.source_title}》第{question.ordinal}题。"
        ),
        requirements="\n".join(_DIRECT_PLAN_REQUIREMENTS),
        seed_ref=TemporaryAgentInputRef(
            artifact_id=question.question_id,
            source_ref=question_path.as_posix(),
            sha256=question_binding_hash,
        ),
        parent_task_id=f"{question.question_id}-direct-plan",
        brainstorm_controller=brainstorm_controller,
        brainstorm_capability=brainstorm_capability,
        review_controller=review_controller,
        review_capability=review_capability,
        output_dir=output,
        selected_skill_contexts=temporary_skill_contexts,
        retrieved_literature_catalog=objective_literature_from_locked_catalog(references),
        config_path=config_path,
        env_path=env_path,
        max_tokens_per_brainstorm_agent=2_200,
        max_tokens_for_review=2_800,
        timeout_seconds=min(timeout_seconds or 300, 300),
        thinking_budget=2_000,
        temperature=0.35,
    )
    skill_manifest_path = output / "selected-method-skills.json"
    skill_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "contest-direct-selected-skills-v1",
                "skills": [
                    {
                        "skill_id": skill_id,
                        "path": skill_path.as_posix(),
                        "content_sha256": digest,
                    }
                    for skill_id, skill_path, _content, digest in selected_skills
                ],
                "routing_artifact_path": routing_path.as_posix(),
                "routing_artifact_hash": routing.artifact_hash,
                "selected_by_configured_model_after_question": True,
                "injected_as_independent_user_message": True,
                "is_scientific_evidence": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    system_artifact_path = output / "system-authored-research-plan.json"
    artifact = plan_generator(
        scientific_problem=(
            f"{question.question_zh}\n"
            f"原始英文问题：{question.question_en}\n"
            f"来源：《{question.source_title}》第{question.ordinal}题。"
        ),
        literature_context=references,
        preexperiment_context=preexperiment_context,
        method_skills=tuple(content for _id, _path, content, _digest in selected_skills),
        temporary_agent_context=objective_stage.plan_context_payload(),
        config_path=config_path,
        env_path=env_path,
        output_path=system_artifact_path,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    render_payload = plan_payload_for_render(artifact, question=question)
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=output / "plan",
        overwrite=overwrite,
        timeout_seconds=180,
    )

    report = {
        "schema_version": "contest-question-one-delivery-v1",
        "status": "completed",
        "model_calls": 1 + objective_stage.model_call_count + 1,
        "skill_routing_model_calls": 1,
        "temporary_agent_model_calls": objective_stage.model_call_count,
        "research_objective_brainstorm_model_calls": 3,
        "research_objective_review_model_calls": objective_stage.review_model_call_count,
        "plan_generation_model_calls": 1,
        "question_id": question.question_id,
        "question_zh": question.question_zh,
        "question_en": question.question_en,
        "system_authored_plan_path": system_artifact_path.as_posix(),
        "skill_routing_path": routing_path.as_posix(),
        "skill_routing_hash": routing.artifact_hash,
        "selected_method_skills_path": skill_manifest_path.as_posix(),
        "selected_method_skill_ids": list(routing.selected_skill_ids),
        "selected_method_skill_sha256": routing.selected_skill_hashes,
        "research_objective_stage_path": (
            output / Path(*PurePosixPath(objective_stage.artifact_relative_path).parts)
        ).as_posix(),
        "research_objective_stage_hash": objective_stage.artifact_hash,
        "research_objective_stage_status": objective_stage.status,
        "research_objective_candidate_count": objective_stage.candidate_count,
        "temporary_runtime_identities_removed": objective_stage.all_runtime_identities_removed,
        "rendered": rendered.to_dict(),
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    report_path = output / "delivery-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report["delivery_report_path"] = report_path.as_posix()
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从《Science》125问题首题一次生成中文研究计划及PDF。"
    )
    parser.add_argument("--question-pdf", type=Path, default=_DEFAULT_PDF)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--max-tokens", type=int, default=12_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--skills-root", type=Path, default=_DEFAULT_SKILLS_ROOT)
    parser.add_argument("--no-overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_question_one_delivery(
        question_pdf=args.question_pdf,
        output_dir=args.output_dir,
        config_path=args.config,
        env_path=args.env,
        skills_root=args.skills_root,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
        overwrite=not args.no_overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through module smoke
    raise SystemExit(main())


__all__ = [
    "default_question_one_reference_catalog",
    "discover_contest_method_skills",
    "main",
    "plan_payload_for_render",
    "run_contest_question_one_delivery",
]
