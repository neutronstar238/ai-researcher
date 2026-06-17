import json
from pathlib import Path

from autoresearch.research import (
    audit_research_plan,
    generate_research_plan,
    render_research_plan_tex,
)
from autoresearch.research.plans import METHOD_ALIGNED_SEED_NOT_FOUND_REF
from autoresearch.schemas import ResearchCandidate, ResearchPlan, ValidationStatus


def _candidate(title: str = "AI-Researcher system proposal") -> ResearchCandidate:
    return ResearchCandidate(
        title=title,
        description="A source-backed direction for improving evidence traceability.",
        research_gap="Existing baselines do not bind metric claims to execution evidence.",
        novelty_score=0.72,
        feasibility_score=0.81,
        impact_score=0.67,
        evidence_refs=["https://example.org/source-paper"],
        metadata={
            "method": "evidence trace adapter",
            "dataset": "UCI Pendigits",
            "baseline": "nearest centroid baseline",
            "metric": "macro_f1",
            "limitation": "weak claim-to-artifact traceability",
        },
    )


def _plan(**overrides: object) -> ResearchPlan:
    payload = {
        "project_id": "project_1",
        "candidate_id": "candidate_1",
        "title": "Evidence Trace Adapter for UCI Pendigits",
        "problem_statement": "A source-backed gap needs a concrete plan.",
        "rationale": "The direction is feasible and evidence-bound.",
        "technical_details": "Use a baseline, macro_f1 metric, and source dataset.",
        "datasets": {"source": "UCI Pendigits", "target": "hold-out split"},
        "methods": "Compare the method with a baseline using macro_f1 metric.",
        "experiments": ["Run baseline.", "Run method.", "Run ablation."],
        "expected_results": "Expected, not yet observed: metric changes require real runs.",
        "code_agent_brief": "Run python scripts/run_experiment.py and save metrics.json.",
        "risks_and_alternatives": ["Baseline may fail.", "Dataset license may block use."],
        "references": ["https://example.org/source-paper"],
        "evidence_refs": ["https://example.org/source-paper"],
    }
    payload.update(overrides)
    return ResearchPlan.model_validate(payload)


def test_generate_research_plan_writes_vault_markdown_and_outputs(tmp_path: Path) -> None:
    artifact = generate_research_plan(
        candidate=_candidate(),
        project_id="project_1",
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "outputs",
        compile_pdf=False,
        similarity_summary=tmp_path / "runs" / "similarity.md",
    )

    markdown_path = Path(artifact.markdown_path)
    json_path = Path(artifact.json_path)
    tex_path = Path(artifact.tex_path)
    markdown = markdown_path.read_text(encoding="utf-8")
    tex = tex_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert artifact.audit.passed is True
    assert artifact.compile_status == "skipped"
    assert artifact.pdf_path is None
    assert markdown_path.is_file()
    assert json_path.is_file()
    assert tex_path.is_file()
    assert "entry_type: research_plan" in markdown
    assert "# Evidence Trace Adapter for UCI Pendigits with Evidence-Calibrated Evaluation" in markdown
    assert "## Code Agent Brief" in markdown
    assert "python scripts/run_experiment.py" in markdown
    assert "XH-202619" not in markdown
    assert "参赛" not in markdown
    assert "AI-Researcher system proposal" not in markdown
    assert "AI-Researcher system proposal" not in tex
    assert payload["audit"]["passed"] is True
    assert payload["plan"]["metadata"]["candidate_title"] == "AI-Researcher system proposal"
    assert payload["plan"]["validation_status"] == ValidationStatus.PASSED.value


def test_generate_research_plan_infers_classification_metric_without_placeholder(
    tmp_path: Path,
) -> None:
    candidate = _candidate("Variance-calibrated prototype classifiers for UCI Pendigits")
    metadata = dict(candidate.metadata)
    metadata.pop("metric")
    candidate = candidate.model_copy(update={"metadata": metadata})

    artifact = generate_research_plan(
        candidate=candidate,
        project_id="project_1",
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "outputs",
        compile_pdf=False,
    )

    markdown = Path(artifact.markdown_path).read_text(encoding="utf-8")
    assert artifact.audit.passed is True
    assert "classification accuracy and macro_f1" in markdown
    assert "primary task metric" not in markdown
    assert "approved hold-out split" not in markdown


def test_generate_research_plan_filters_unmatched_seed_marker_when_context_exists(
    tmp_path: Path,
) -> None:
    candidate = _candidate("Variance-calibrated prototype classifiers for UCI Pendigits")
    candidate = candidate.model_copy(
        update={"evidence_refs": [METHOD_ALIGNED_SEED_NOT_FOUND_REF]}
    )

    artifact = generate_research_plan(
        candidate=candidate,
        project_id="project_1",
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "outputs",
        compile_pdf=False,
        similarity_summary=tmp_path / "runs" / "similarity.md",
        literature_summary=tmp_path / "runs" / "literature.md",
    )

    markdown = Path(artifact.markdown_path).read_text(encoding="utf-8")
    assert artifact.audit.passed is True
    assert METHOD_ALIGNED_SEED_NOT_FOUND_REF not in artifact.plan.evidence_refs
    assert METHOD_ALIGNED_SEED_NOT_FOUND_REF not in markdown
    assert "similarity_summary:" in markdown
    assert "literature_summary:" in markdown


def test_research_plan_audit_blocks_project_title_and_contest_terms() -> None:
    plan = _plan(
        title="AI-Researcher system",
        rationale="XH-202619 参赛方案 should never enter a normal research plan.",
    )

    audit = audit_research_plan(plan)

    assert audit.passed is False
    assert any("title must be a discovered research topic" in issue for issue in audit.issues)
    assert any("forbidden contest" in issue for issue in audit.issues)


def test_research_plan_audit_requires_baseline_metric_and_commands() -> None:
    plan = _plan(
        methods="Use a vague method.",
        experiments=["Run something."],
        code_agent_brief="Implement it later.",
    )

    audit = audit_research_plan(plan)

    assert audit.passed is False
    assert any("baseline" in issue for issue in audit.issues)
    assert any("metrics" in issue for issue in audit.issues)
    assert any("command-oriented" in issue for issue in audit.issues)


def test_research_plan_audit_blocks_placeholder_metric_and_target() -> None:
    plan = _plan(
        technical_details="Use a baseline and primary task metric on a source dataset.",
        datasets={"source": "approved public benchmark", "target": "approved hold-out split"},
        methods="Compare the method with a baseline using the primary task metric.",
        experiments=[
            "Run baseline and record the primary task metric.",
            "Run method and compare the primary task metric.",
            "Run ablation.",
        ],
        expected_results="Expected, not yet observed: primary task metric changes require real runs.",
    )

    audit = audit_research_plan(plan)

    assert audit.passed is False
    assert any("primary task metric" in issue for issue in audit.issues)
    assert any("approved hold-out split" in issue for issue in audit.issues)
    assert any("concrete evaluation metrics" in issue for issue in audit.issues)


def test_research_plan_tex_uses_breakable_references_for_long_artifacts() -> None:
    plan = _plan(
        references=[
            "https://example.org/source-paper",
            "Evidence artifact: similarity_summary:runs/manual-live/task129-plan-layout/vault/exploration/topics/similarity_check_autopilot_task129_plan_layout_20260617150322.md",
            "Evidence artifact: literature_summary:runs/manual-live/task129-plan-layout/vault/exploration/topics/literature_refresh_20260617.md",
        ],
        evidence_refs=["https://example.org/source-paper"],
    )

    tex = render_research_plan_tex(plan=plan, audit=audit_research_plan(plan))

    assert r"\url{https://example.org/source-paper}" in tex
    assert (
        r"Evidence artifact: \url{similarity_summary:runs/manual-live/task129-plan-layout/vault/"
        in tex
    )
    assert r"similarity\_summary:runs/manual-live" not in tex
