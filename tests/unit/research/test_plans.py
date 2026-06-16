import json
from pathlib import Path

from autoresearch.research import audit_research_plan, generate_research_plan
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
