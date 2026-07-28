"""Deterministic local Sprint fixture shared by migration unit and smoke tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.campaign.sprint import (
    AutonomousResearchSprint,
    SprintTopicCandidate,
    build_sprint_spec,
    installed_sprint_programs,
)
from autoresearch.campaign.sprint_migration import SprintMigrationMode
from autoresearch.campaign.systems import (
    SystemsBenchmarkResult,
    SystemsCellResult,
    SystemsMode,
    SystemsPreregistration,
    SystemsTaskFamily,
    SystemsTaskSpec,
    WorkflowFault,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.literature import AcademicPaper
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult
from autoresearch.reports.figures import FigureArtifact
from autoresearch.reports.latex_templates import (
    LatexTemplateDependencyResolution,
    LatexTemplateDependencyStatus,
    generic_latex_templates,
)
from autoresearch.reports.paper_build import (
    LatexPaperBuildArtifact,
    LatexPaperBuildStatus,
    LatexPaperQualityReport,
)


@dataclass
class DeterministicSprintFixture:
    """Small, fully executable Sprint with controllable block/result semantics."""

    root: Path
    sprint_id: str
    endpoint_passed: bool = True
    topic_blocked: bool = False
    shared_migration_root: Path | None = None
    calls: list[str] = field(default_factory=list)
    _preregistration: SystemsPreregistration | None = None

    @property
    def output_root(self) -> Path:
        return self.root / "sprints"

    @property
    def vault_root(self) -> Path:
        return self.root / "vault"

    @property
    def migration_root(self) -> Path:
        return self.shared_migration_root or (self.root / "migration")

    @property
    def route_manifest_path(self) -> Path:
        return self.root / "route-a" / "campaign-manifest.json"

    def build_spec(self) -> Any:
        route = self.root / "route-a"
        route.mkdir(parents=True, exist_ok=True)
        self.route_manifest_path.write_text(
            json.dumps(
                {
                    "campaign_id": "route-a",
                    "completed_round_count": 2,
                    "human_intervention_count": 0,
                    "lineage_hash": "a" * 64,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        llm = self.root / "ollama.yaml"
        llm.write_text(
            "deployment:\n"
            "  llm:\n"
            "    provider: ollama-openai-compatible\n"
            "    base_url: http://127.0.0.1:11434/v1\n"
            "    model_name: qwen3.5-sprint:9b-8k\n"
            "    api_key_env: AUTORESEARCH_LOCAL_OLLAMA_API_KEY\n",
            encoding="utf-8",
        )
        return build_sprint_spec(
            sprint_id=self.sprint_id,
            project_id="task262-sprint-migration",
            high_level_brief=(
                "Select a falsifiable local systems experiment and generate a complete "
                "evidence-bound report without post-start manual research decisions."
            ),
            deadline=datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc),
            route_a_campaign_path=route,
            llm_config_path=llm,
        )

    def service(
        self,
        *,
        mode: SprintMigrationMode | str | None = None,
        formal_run_id: str | None = None,
    ) -> AutonomousResearchSprint:
        return AutonomousResearchSprint(
            output_root=self.output_root,
            vault_root=self.vault_root,
            completion=self._completion,
            literature_search=self._literature_search,
            preregister=self._preregister,
            systems_run=self._systems_run,
            figure_build=self._figure_build,
            paper_build=self._paper_build,
            migration_mode=mode,
            migration_root=self.migration_root,
            migration_formal_run_id=formal_run_id,
        )

    def _completion(self, **kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        if "topic-selection controller" in messages[0]["content"]:
            self.calls.append("topic")
            if self.topic_blocked:
                raise LLMClientError("fixture local model unavailable")
            programs = installed_sprint_programs()
            candidates = [
                _candidate(
                    f"C{index:03d}",
                    program.program_id,
                    f"L{index:03d}",
                ).model_dump(mode="json")
                for index, program in enumerate(programs, start=1)
            ]
            return _completion_result(
                {
                    "candidates": candidates,
                    "selected_candidate_id": "C001",
                    "selection_rationale": (
                        "The selected executable program has ten independent tasks, "
                        "a direct falsification rule, and bounded local execution."
                    ),
                }
            )
        self.calls.append("manuscript")
        paragraph = (
            "Evidence from the controlled benchmark supports careful analysis of the "
            "research loop, artifact provenance, task-level statistical inference, "
            "reproduction, validation, hypothesis falsification, ablation boundaries, "
            "and claim calibration. "
        )
        long_section = paragraph * 45
        disposition = "gate_passed" if self.endpoint_passed else "gate_failed"
        return _completion_result(
            {
                "title": "Task-Level Evidence for Bounded Autonomous Research Loops",
                "abstract": paragraph * 18,
                "introduction": (
                    f"Prior work motivates this question [@L001]. {long_section}"
                ),
                "related_work": (
                    "Retrieved literature frames autonomous research agents [@L002]. "
                    + long_section
                ),
                "method": long_section,
                "experiments": long_section,
                "result_disposition": disposition,
                "citation_ids": ["L001", "L002"],
            }
        )

    def _literature_search(
        self,
        query: str,
        limit: int,
    ) -> Sequence[AcademicPaper]:
        del limit
        self.calls.append("literature")
        if '"autonomous research"' in query:
            title, suffix = "Evidence-Bound Autonomous Research Loops", 101
        elif '"AI scientist"' in query:
            title, suffix = "Benchmarking Artificial Intelligence Scientists", 102
        else:
            title, suffix = "Agents for Reproducible Scientific Discovery", 103
        return [
            AcademicPaper(
                title=title,
                authors=["Ada Researcher", "Ben Validator"],
                abstract=(
                    "A source-backed study of autonomous research agents, evidence "
                    "gates, benchmarks, and reproducibility."
                ),
                publication_date=date(2026, 1, 1),
                venue="arXiv",
                url=f"https://arxiv.org/abs/2601.{suffix:04d}",
                source="arxiv",
            )
        ]

    def _preregister(
        self,
        benchmark_dir: Path,
        **_kwargs: Any,
    ) -> SystemsPreregistration:
        self.calls.append("preregister")
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        tasks = tuple(
            SystemsTaskSpec(
                task_id=f"task-{index:02d}",
                family=(
                    SystemsTaskFamily.UCI
                    if index < 4
                    else SystemsTaskFamily.MDBENCH
                ),
                source_evidence_path=(
                    benchmark_dir / f"source-{index}.json"
                ).as_posix(),
                source_evidence_sha256="a" * 64,
                source_evidence_hash="b" * 64,
                initial_fault=(
                    WorkflowFault.NONE
                    if index < 5
                    else WorkflowFault.FAILED_EXPERIMENT_CELL
                ),
                plan_detectable=False,
                requires_vault_memory=False,
                repair_action="repair",
            )
            for index in range(10)
        )
        prereg = SystemsPreregistration(
            benchmark_id=benchmark_dir.name,
            project_id="task262-sprint-migration",
            created_at=datetime.now(timezone.utc),
            deadline=datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc),
            route_a_campaign_path=(self.root / "route-a").as_posix(),
            route_a_manifest_sha256="c" * 64,
            route_a_lineage_hash="d" * 64,
            route_a_completed_rounds=2,
            llm_config_path=(self.root / "ollama.yaml").as_posix(),
            llm_config_sha256="e" * 64,
            tasks=tasks,
            controlled_fault_policy_hash="f" * 64,
            evaluator_code_sha256="0" * 64,
            preregistration_hash="1" * 64,
        )
        write_json_model(benchmark_dir / "preregistration.json", prereg)
        self._preregistration = prereg
        return prereg

    def _systems_run(self, benchmark_dir: Path) -> SystemsBenchmarkResult:
        self.calls.append("experiment")
        if self._preregistration is None:
            raise RuntimeError("fixture preregistration was not created")
        cells = _cells(
            self._preregistration,
            endpoint_passed=self.endpoint_passed,
        )
        return _benchmark_result(benchmark_dir, cells, persist=True)

    def _figure_build(
        self,
        _metrics_path: Path,
        output_dir: Path,
        **_kwargs: Any,
    ) -> FigureArtifact:
        self.calls.append("figure")
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf = output_dir / "endpoint.pdf"
        png = output_dir / "endpoint.png"
        metadata = output_dir / "endpoint.json"
        pdf.write_bytes(b"%PDF-1.7\n")
        png.write_bytes(b"PNG")
        metadata.write_text(
            json.dumps(
                {
                    "figure_type": "metric_bar",
                    "style": {"orientation": "horizontal"},
                    "metrics": [{"name": "paired_mean_gain", "label": "Gain"}],
                }
            ),
            encoding="utf-8",
        )
        return FigureArtifact(
            title="Endpoint",
            source_path=Path(_metrics_path).as_posix(),
            pdf_path=pdf.resolve().as_posix(),
            png_path=png.resolve().as_posix(),
            metadata_path=metadata.resolve().as_posix(),
            metric_names=("paired_mean_gain",),
        )

    def _paper_build(
        self,
        markdown_path: Path | str,
        output_dir: Path | str,
        **_kwargs: Any,
    ) -> LatexPaperBuildArtifact:
        self.calls.append("paper")
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        tex = root / "main.tex"
        pdf = root / "main.pdf"
        log = root / "compile.log"
        summary = root / "paper-build.md"
        build_json = root / "paper-build.json"
        tex.write_text("\\documentclass{article}\n", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.7\n")
        log.write_text("compiled\n", encoding="utf-8")
        summary.write_text("# Paper build\n", encoding="utf-8")
        artifact = LatexPaperBuildArtifact(
            status=LatexPaperBuildStatus.COMPILED,
            generated_at=datetime.now(timezone.utc).isoformat(),
            template=generic_latex_templates()[0],
            source_markdown_path=Path(markdown_path).resolve().as_posix(),
            tex_path=tex.resolve().as_posix(),
            pdf_path=pdf.resolve().as_posix(),
            log_path=log.resolve().as_posix(),
            markdown_path=summary.resolve().as_posix(),
            json_path=build_json.resolve().as_posix(),
            vault_markdown_path=None,
            missing_sections=(),
            engine="pdflatex",
            command=("pdflatex", "main.tex"),
            dependency_resolution=LatexTemplateDependencyResolution(
                status=LatexTemplateDependencyStatus.NOT_REQUIRED,
                checked_at=datetime.now(timezone.utc).isoformat(),
                class_file=None,
                message="deterministic migration fixture",
            ),
            quality=_passing_quality(),
        )
        build_json.write_text(
            json.dumps(artifact.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return artifact


def _candidate(
    candidate_id: str,
    program_id: str,
    literature_ref: str,
) -> SprintTopicCandidate:
    return SprintTopicCandidate(
        candidate_id=candidate_id,
        title=f"Executable research candidate {candidate_id}",
        research_question=(
            "Does the selected evidence-bound program improve the frozen task-level "
            "endpoint relative to its preregistered comparison?"
        ),
        hypothesis=(
            "The selected program yields a positive paired task-level gain whose "
            "bootstrap confidence interval excludes zero."
        ),
        program_id=program_id,
        mechanism_rationale=(
            "Failure feedback, evidence binding, and deterministic adjudication may "
            "recover controlled workflow failures."
        ),
        novelty_risk=(
            "Close autonomous-research benchmarks may test related loop designs."
        ),
        falsification_conditions=(
            "The task-level interval includes zero.",
            "Exact reproduction or claim support fails.",
        ),
        literature_refs=(literature_ref,),
    )


def _cells(
    prereg: SystemsPreregistration,
    *,
    endpoint_passed: bool,
) -> tuple[SystemsCellResult, ...]:
    cells: list[SystemsCellResult] = []
    for task_index, task in enumerate(prereg.tasks):
        for seed in prereg.seeds:
            for mode in (SystemsMode.EXECUTE_ONCE, SystemsMode.FULL_LOOP):
                if endpoint_passed:
                    success = mode is SystemsMode.FULL_LOOP or task_index < 5
                else:
                    success = task_index < 5
                draft = SystemsCellResult(
                    cell_id=f"{mode.value}-{seed}-{task.task_id}",
                    task_id=task.task_id,
                    family=task.family,
                    mode=mode,
                    seed=seed,
                    source_evidence_hash=task.source_evidence_hash,
                    policy_evidence_path="policy.json",
                    initial_fault=task.initial_fault,
                    initial_failure_codes=(
                        () if task_index < 5 else ("failure",)
                    ),
                    final_failure_codes=(() if success else ("failure",)),
                    attempted_actions=(
                        ("repair",)
                        if mode is SystemsMode.FULL_LOOP and endpoint_passed
                        else ()
                    ),
                    attempt_count=(
                        2
                        if mode is SystemsMode.FULL_LOOP and endpoint_passed
                        else 1
                    ),
                    task_success=success,
                    negative_result_recovered=(
                        endpoint_passed
                        and mode is SystemsMode.FULL_LOOP
                        and task_index >= 5
                    ),
                    exact_reproduction=True,
                    claim_supported=True,
                    unsupported_claim_count=0,
                    preregistration_complete=True,
                    evidence_gate_enforced=mode is SystemsMode.FULL_LOOP,
                    vault_memory_used=False,
                    failure_feedback_used=mode is SystemsMode.FULL_LOOP,
                    research_decision_human_interventions=0,
                    report_claim="Evidence-bound task claim.",
                    scientific_result_hash="2" * 64,
                    reproduction_result_hash="2" * 64,
                    wall_time_seconds=0.01,
                    external_cost_usd=0.0,
                )
                cells.append(_stamp_result(draft))
    return tuple(cells)


def _benchmark_result(
    root: Path,
    cells: Sequence[SystemsCellResult],
    *,
    persist: bool,
) -> SystemsBenchmarkResult:
    root.mkdir(parents=True, exist_ok=True)
    matrix_path = root / "matrix-manifest.json"
    cell_items = []
    for cell in cells:
        cell_path = root / "cells" / cell.cell_id / "cell-result.json"
        write_json_model(cell_path, cell)
        cell_items.append(
            {
                "cell_id": cell.cell_id,
                "path": cell_path.resolve().as_posix(),
                "result_hash": cell.result_hash,
                "scientific_result_hash": cell.scientific_result_hash,
            }
        )
    matrix_path.write_text(
        json.dumps(
            {
                "schema_version": "test-matrix-v1",
                "evaluated_result_hash": "3" * 64,
                "cell_count": len(cells),
                "cells": cell_items,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    draft = SystemsBenchmarkResult(
        benchmark_id=root.name,
        preregistration_hash="1" * 64,
        completed_at=datetime.now(timezone.utc),
        cell_count=len(cells),
        main_cell_count=len(cells),
        ablation_cell_count=0,
        mode_metrics={},
        paired_differences=tuple(0.0 for _ in range(30)),
        paired_mean_gain_vs_execute_once=0.0,
        bootstrap_ci95_lower=0.0,
        bootstrap_ci95_upper=0.0,
        local_model_request_count=0,
        local_model_fallback_count=0,
        local_model_wall_time_seconds=0.0,
        external_cost_usd=0.0,
        campaign_research_decision_human_interventions=0,
        contribution_gate_path=(root / "contribution-gate.json").as_posix(),
        report_path=(root / "report.md").as_posix(),
        failure_report_path=(root / "failure.md").as_posix(),
        loop_report_path=(root / "loop.md").as_posix(),
        evidence_map_path=(root / "evidence.json").as_posix(),
        table_path=(root / "table.md").as_posix(),
        figure_path=(root / "figure.svg").as_posix(),
        manuscript_path=(root / "manuscript.md").as_posix(),
        matrix_manifest_path=matrix_path.resolve().as_posix(),
    )
    result = _stamp_result(draft)
    if persist:
        write_json_model(root / "benchmark-result.json", result)
    return result


def _stamp_result(model: Any) -> Any:
    from autoresearch.campaign.sprint import _stamp_model

    return _stamp_model(model, "result_hash")


def _completion_result(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="ollama-openai-compatible",
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5-sprint:9b-8k",
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={},
        temperature=0.0,
    )


def _passing_quality() -> LatexPaperQualityReport:
    return LatexPaperQualityReport(
        passed=True,
        page_count=8,
        min_pages=6,
        word_count=3_000,
        min_word_count=2_500,
        technical_term_count=18,
        min_technical_terms=15,
        section_word_counts={
            "Abstract": 100,
            "Introduction": 300,
            "Related Work": 300,
            "Method": 500,
            "Experiments": 500,
            "Results": 400,
            "Limitations": 200,
            "Conclusion": 150,
        },
        section_min_words={},
        short_sections=(),
        overfull_hbox_count=0,
        max_overfull_hbox_count=0,
        max_overfull_hbox_points=0.0,
        max_allowed_overfull_hbox_points=0.0,
        figure_count=1,
        min_figures=1,
        table_count=1,
        min_tables=1,
        bibliography_item_count=2,
        min_bibliography_items=1,
        invalid_reference_label_count=0,
        figure_readability_issue_count=0,
        figure_readability_issues=(),
        failures=(),
    )
