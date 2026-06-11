import shutil
from pathlib import Path

import pytest

from autoresearch.evidence import (
    ClaimNode,
    EvidenceArtifact,
    EvidenceGraph,
    EvidenceNode,
    SourceNode,
)
from autoresearch.reports import LatexDraftContext, generate_latex_skeleton
from autoresearch.schemas import ValidationStatus


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex is unavailable")
def test_generate_latex_skeleton_compiles_for_demo_project(tmp_path: Path) -> None:
    graph = _validated_graph()
    context = LatexDraftContext(
        project_id="project-001",
        title="Demo Evidence Paper",
        authors=["AutoResearch"],
        evidence_graph=graph,
        section_claim_ids={
            "abstract": ["claim_accuracy"],
            "introduction": ["claim_accuracy"],
            "related_work": ["claim_accuracy"],
            "method": ["claim_accuracy"],
            "experiments": ["claim_accuracy"],
            "results": ["claim_accuracy"],
            "limitations": ["claim_accuracy"],
            "conclusion": ["claim_accuracy"],
        },
    )

    artifact = generate_latex_skeleton(
        context,
        tmp_path / "paper",
        compile_pdf=True,
    )

    tex = Path(artifact.tex_path).read_text(encoding="utf-8")
    assert Path(artifact.pdf_path or "").exists()
    assert artifact.placeholder_sections == ()
    assert r"\begin{abstract}" in tex
    assert r"\section{Introduction}" in tex
    assert r"\section{Conclusion}" in tex
    assert "The demo method improves accuracy on the benchmark." in tex
    assert "Validated accuracy metric from run\\_001." in tex
    assert "TODO" not in tex


def test_generate_latex_skeleton_marks_missing_evidence_without_fabrication(
    tmp_path: Path,
) -> None:
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_gap",
            statement="The system may improve evidence coverage.",
        )
    )
    context = LatexDraftContext(
        project_id="project-001",
        title="Draft With Missing Evidence",
        authors=["AutoResearch"],
        evidence_graph=graph,
        section_claim_ids={"introduction": ["claim_gap"]},
    )

    artifact = generate_latex_skeleton(context, tmp_path / "paper")

    tex = Path(artifact.tex_path).read_text(encoding="utf-8")
    assert "abstract" in artifact.placeholder_sections
    assert "introduction" in artifact.placeholder_sections
    assert r"\textbf{TODO: Missing evidence for Abstract.}" in tex
    assert r"\textbf{TODO: Missing validated evidence for claim claim\_gap.}" in tex
    assert "improves evidence coverage by" not in tex


def _validated_graph() -> EvidenceGraph:
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_accuracy",
            statement="The demo method improves accuracy on the benchmark.",
        )
    )
    graph.add_source(
        SourceNode(
            id="source_run_001",
            title="Experiment run run_001",
            uri="runs/run_001",
        )
    )
    graph.add_artifact(
        EvidenceArtifact(
            id="artifact_metrics",
            source_id="source_run_001",
            uri="runs/run_001/metrics.json",
            validation_status=ValidationStatus.PASSED,
        )
    )
    graph.link_evidence(
        EvidenceNode(
            id="evidence_accuracy",
            claim_id="claim_accuracy",
            source_id="source_run_001",
            artifact_id="artifact_metrics",
            summary="Validated accuracy metric from run_001.",
        )
    )
    return graph
