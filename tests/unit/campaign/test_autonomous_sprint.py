from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.campaign.sprint import (
    AutonomousResearchSprint,
    AutonomyLevel,
    SprintOutcome,
    SprintTopicCandidate,
    SprintTopicSelection,
    _stamp_model,
    build_sprint_spec,
    compute_task_level_endpoint,
    installed_sprint_programs,
)
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


def test_task_level_endpoint_does_not_treat_seed_repeats_as_independent(
    tmp_path: Path,
) -> None:
    prereg = _preregistration(tmp_path)
    selection = _selection()
    cells = _cells(prereg)
    benchmark = _benchmark_result(tmp_path, cells)

    endpoint = compute_task_level_endpoint(
        sprint_id="sprint-test",
        benchmark=benchmark,
        preregistration=prereg,
        cells=cells,
        selection=selection,
        program=installed_sprint_programs()[0],
    )

    assert endpoint.statistical_unit == "task"
    assert endpoint.independent_unit_count == 10
    assert endpoint.repeated_seed_count_per_task == 3
    assert len(endpoint.paired_task_differences) == 10
    assert endpoint.paired_mean_gain == pytest.approx(0.5)
    assert endpoint.bootstrap_ci95_lower > 0.0
    assert endpoint.checks["minimum_independent_task_count"] is True


def test_local_topic_failure_blocks_without_deterministic_fallback(
    tmp_path: Path,
) -> None:
    spec = _sprint_spec(tmp_path, sprint_id="no-topic-fallback")

    def failed_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        raise LLMClientError("local model unavailable")

    sprint = AutonomousResearchSprint(
        output_root=tmp_path / "sprints",
        vault_root=tmp_path / "vault",
        completion=failed_completion,
        literature_search=_literature_search,
    )

    result = sprint.run(spec)

    assert result.outcome is SprintOutcome.BLOCKED
    root = Path(result.sprint_dir)
    assert not (root / "topic" / "selection.json").exists()
    manifest = json.loads(
        (root / "sprint-manifest.json").read_text(encoding="utf-8")
    )
    assert "LLMClientError" in manifest["failure"]
    ledger = json.loads(
        (root / "autonomy-ledger.json").read_text(encoding="utf-8")
    )
    assert all(event["fallback_used"] is False for event in ledger["events"])


def test_topic_candidates_must_span_three_executable_programs(
    tmp_path: Path,
) -> None:
    spec = _sprint_spec(tmp_path, sprint_id="duplicate-programs")

    def invalid_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        candidates = [
            _candidate(
                f"C{index:03d}",
                "systems-success-recovery-task-v2",
                "L001",
            ).model_dump(mode="json")
            for index in range(1, 4)
        ]
        return _completion(
            {
                "candidates": candidates,
                "selected_candidate_id": "C001",
                "selection_rationale": (
                    "This candidate is falsifiable and fits the deadline while preserving "
                    "a task-level independent unit."
                ),
            }
        )

    result = AutonomousResearchSprint(
        output_root=tmp_path / "sprints",
        completion=invalid_completion,
        literature_search=_literature_search,
    ).run(spec)

    assert result.outcome is SprintOutcome.BLOCKED
    manifest = json.loads(
        (Path(result.sprint_dir) / "sprint-manifest.json").read_text(encoding="utf-8")
    )
    assert "span at least three executable programs" in manifest["failure"]


def test_one_run_selects_executes_writes_manuscript_and_invokes_pdf(
    tmp_path: Path,
) -> None:
    spec = _sprint_spec(tmp_path, sprint_id="one-command-sprint")
    calls: list[str] = []
    topic_attempts = 0

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal topic_attempts
        messages = kwargs["messages"]
        if "topic-selection controller" in messages[0]["content"]:
            calls.append("topic")
            topic_attempts += 1
            if topic_attempts == 1:
                raise LLMClientError("first structured response was malformed")
            programs = installed_sprint_programs()
            candidates = [
                _candidate(
                    f"C{index:03d}",
                    program.program_id,
                    f"L{index:03d}",
                ).model_dump(mode="json")
                for index, program in enumerate(programs, start=1)
            ]
            return _completion(
                {
                    "candidates": candidates,
                    "selected_candidate_id": "C001",
                    "selection_rationale": (
                        "The selected program has ten independent tasks, a direct "
                        "falsification rule, and the smallest execution risk before deadline."
                    ),
                }
            )
        calls.append("manuscript")
        paragraph = (
            "Evidence from the controlled benchmark supports careful analysis of the "
            "research loop, artifact provenance, task-level statistical inference, "
            "reproduction, validation, hypothesis falsification, ablation boundaries, "
            "and claim calibration. "
        )
        long_section = paragraph * 45
        return _completion(
            {
                "title": "Task-Level Evidence for Bounded Autonomous Research Loops",
                "abstract": paragraph * 18,
                "introduction": f"Prior work motivates this question [@L001]. {long_section}",
                "related_work": (
                    "The retrieved literature frames autonomous research agents [@L002]. "
                    + long_section
                ),
                "method": long_section,
                "experiments": long_section,
                "result_disposition": "gate_passed",
                "citation_ids": ["L001", "L002"],
            }
        )

    prereg_holder: dict[str, SystemsPreregistration] = {}

    def preregister(
        benchmark_dir: Path,
        **_kwargs: Any,
    ) -> SystemsPreregistration:
        calls.append("preregister")
        prereg = _preregistration(tmp_path, root=benchmark_dir)
        write_json_model(benchmark_dir / "preregistration.json", prereg)
        prereg_holder["value"] = prereg
        return prereg

    def systems_run(benchmark_dir: Path) -> SystemsBenchmarkResult:
        calls.append("experiment")
        prereg = prereg_holder["value"]
        cells = _cells(prereg)
        return _benchmark_result(benchmark_dir, cells, persist=True)

    def figure_build(
        _metrics_path: Path,
        output_dir: Path,
        **_kwargs: Any,
    ) -> FigureArtifact:
        calls.append("figure")
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf = output_dir / "endpoint.pdf"
        png = output_dir / "endpoint.png"
        metadata = output_dir / "endpoint.metadata.json"
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
            pdf_path=pdf.as_posix(),
            png_path=png.as_posix(),
            metadata_path=metadata.as_posix(),
            metric_names=("paired_mean_gain",),
        )

    def paper_build(
        markdown_path: Path | str,
        output_dir: Path | str,
        **_kwargs: Any,
    ) -> LatexPaperBuildArtifact:
        calls.append("paper")
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
                message="test template",
            ),
            quality=_passing_quality(),
        )
        build_json.write_text(
            json.dumps(artifact.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return artifact

    sprint = AutonomousResearchSprint(
        output_root=tmp_path / "sprints",
        vault_root=tmp_path / "vault",
        completion=completion,
        literature_search=_literature_search,
        preregister=preregister,
        systems_run=systems_run,
        figure_build=figure_build,
        paper_build=paper_build,
    )

    result = sprint.run(spec)
    second = sprint.run(
        spec.model_copy(
            update={"created_at": datetime(2026, 7, 25, tzinfo=timezone.utc)}
        )
    )

    assert result.outcome is SprintOutcome.COMPLETED
    assert result.autonomy_level is AutonomyLevel.BOUNDED_AUTONOMOUS
    assert result.endpoint_passed is True
    assert result.manuscript_pdf_path is not None
    assert Path(result.manuscript_pdf_path).is_file()
    assert second.manifest_path == result.manifest_path
    assert calls == [
        "topic",
        "topic",
        "preregister",
        "experiment",
        "manuscript",
        "figure",
        "paper",
    ]
    selection = json.loads(
        (
            Path(result.sprint_dir) / "topic" / "selection.json"
        ).read_text(encoding="utf-8")
    )
    assert selection["attempt_count"] == 2
    assert selection["used_fallback"] is False
    audit = json.loads(
        (
            Path(result.sprint_dir)
            / "audit"
            / "autonomy-audit.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["checks"]["selected_topic_controls_primary_analysis"] is True
    assert audit["checks"]["route_a_generated_inside_same_sprint"] is False
    assert audit["post_start_manual_research_decisions"] == 0
    ledger = json.loads(
        (
            Path(result.sprint_dir) / "autonomy-ledger.json"
        ).read_text(encoding="utf-8")
    )
    assert any(
        event["action"] == "compile_selected_manuscript_to_pdf"
        for event in ledger["events"]
    )


def _sprint_spec(tmp_path: Path, *, sprint_id: str) -> Any:
    route = tmp_path / "route-a"
    route.mkdir(exist_ok=True)
    (route / "campaign-manifest.json").write_text(
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
    llm = tmp_path / "ollama.yaml"
    llm.write_text(
        "deployment:\n"
        "  llm:\n"
        "    provider: ollama-openai-compatible\n"
        "    base_url: http://127.0.0.1:11434/v1\n"
        "    model_name: qwen3.5:9b\n"
        "    api_key_env: AUTORESEARCH_LOCAL_OLLAMA_API_KEY\n",
        encoding="utf-8",
    )
    return build_sprint_spec(
        sprint_id=sprint_id,
        project_id="test-project",
        high_level_brief=(
            "Select a falsifiable local systems experiment and generate its complete "
            "evidence-bound report without post-start manual research decisions."
        ),
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        route_a_campaign_path=route,
        llm_config_path=llm,
    )


def _literature_search(query: str, limit: int) -> Sequence[AcademicPaper]:
    del limit
    if '"autonomous research"' in query:
        title = "Evidence-Bound Autonomous Research Loops"
        suffix = 101
    elif '"AI scientist"' in query:
        title = "Benchmarking Artificial Intelligence Scientists"
        suffix = 102
    else:
        title = "Agents for Reproducible Scientific Discovery"
        suffix = 103
    return [
        AcademicPaper(
            title=title,
            authors=["Ada Researcher", "Ben Validator"],
            abstract=(
                "A source-backed study of autonomous research agents, evidence gates, "
                "benchmarks, and reproducibility."
            ),
            publication_date=date(2026, 1, 1),
            venue="arXiv",
            url=f"https://arxiv.org/abs/2601.{suffix:04d}",
            source="arxiv",
        )
    ]


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
            "Close autonomous-research benchmarks may already test related loop designs."
        ),
        falsification_conditions=(
            "The task-level interval includes zero.",
            "Exact reproduction or claim support fails.",
        ),
        literature_refs=(literature_ref,),
    )


def _selection() -> SprintTopicSelection:
    programs = installed_sprint_programs()
    draft = SprintTopicSelection(
        sprint_id="sprint-test",
        brief_hash="1" * 64,
        literature_snapshot_hash="2" * 64,
        program_catalog_hash="3" * 64,
        candidates=tuple(
            _candidate(f"C{index:03d}", program.program_id, "L001")
            for index, program in enumerate(programs, start=1)
        ),
        selected_candidate_id="C001",
        selection_rationale=(
            "The selected program has the clearest task-level falsification rule and "
            "fits the local execution deadline."
        ),
        provider="ollama-openai-compatible",
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:9b",
        response_text="{}",
        usage={},
        created_at=datetime.now(timezone.utc),
    )
    return _stamp_model(draft, "selection_hash")


def _preregistration(
    tmp_path: Path,
    *,
    root: Path | None = None,
) -> SystemsPreregistration:
    benchmark_root = root or (tmp_path / "benchmark")
    benchmark_root.mkdir(parents=True, exist_ok=True)
    tasks = tuple(
        SystemsTaskSpec(
            task_id=f"task-{index:02d}",
            family=SystemsTaskFamily.UCI if index < 4 else SystemsTaskFamily.MDBENCH,
            source_evidence_path=(benchmark_root / f"source-{index}.json").as_posix(),
            source_evidence_sha256="a" * 64,
            source_evidence_hash="b" * 64,
            initial_fault=(
                WorkflowFault.NONE if index < 5 else WorkflowFault.FAILED_EXPERIMENT_CELL
            ),
            plan_detectable=False,
            requires_vault_memory=False,
            repair_action="repair",
        )
        for index in range(10)
    )
    return SystemsPreregistration(
        benchmark_id=benchmark_root.name,
        project_id="test-project",
        created_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        route_a_campaign_path=(tmp_path / "route-a").as_posix(),
        route_a_manifest_sha256="c" * 64,
        route_a_lineage_hash="d" * 64,
        route_a_completed_rounds=2,
        llm_config_path=(tmp_path / "ollama.yaml").as_posix(),
        llm_config_sha256="e" * 64,
        tasks=tasks,
        controlled_fault_policy_hash="f" * 64,
        evaluator_code_sha256="0" * 64,
        preregistration_hash="1" * 64,
    )


def _cells(prereg: SystemsPreregistration) -> tuple[SystemsCellResult, ...]:
    cells: list[SystemsCellResult] = []
    for task_index, task in enumerate(prereg.tasks):
        for seed in prereg.seeds:
            for mode in (
                SystemsMode.EXECUTE_ONCE,
                SystemsMode.FULL_LOOP,
            ):
                success = mode is SystemsMode.FULL_LOOP or task_index < 5
                draft = SystemsCellResult(
                    cell_id=f"{mode.value}-{seed}-{task.task_id}",
                    task_id=task.task_id,
                    family=task.family,
                    mode=mode,
                    seed=seed,
                    source_evidence_hash=task.source_evidence_hash,
                    policy_evidence_path="policy.json",
                    initial_fault=task.initial_fault,
                    initial_failure_codes=(() if task_index < 5 else ("failure",)),
                    final_failure_codes=(() if success else ("failure",)),
                    attempted_actions=(("repair",) if mode is SystemsMode.FULL_LOOP else ()),
                    attempt_count=2 if mode is SystemsMode.FULL_LOOP else 1,
                    task_success=success,
                    negative_result_recovered=(
                        mode is SystemsMode.FULL_LOOP and task_index >= 5
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
                cells.append(_stamp_model(draft, "result_hash"))
    return tuple(cells)


def _benchmark_result(
    root: Path,
    cells: Sequence[SystemsCellResult],
    *,
    persist: bool = False,
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
        paired_differences=tuple(
            1.0 if index >= 5 else 0.0
            for _seed in range(3)
            for index in range(10)
        ),
        paired_mean_gain_vs_execute_once=0.5,
        bootstrap_ci95_lower=0.2,
        bootstrap_ci95_upper=0.8,
        local_model_request_count=3,
        local_model_fallback_count=0,
        local_model_wall_time_seconds=0.1,
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
    result = _stamp_model(draft, "result_hash")
    if persist:
        write_json_model(root / "benchmark-result.json", result)
    return result


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="ollama-openai-compatible",
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:9b",
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
