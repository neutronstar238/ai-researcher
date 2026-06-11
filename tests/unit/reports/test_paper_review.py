from autoresearch.evidence import (
    ClaimNode,
    EvidenceArtifact,
    EvidenceGraph,
    EvidenceNode,
    SourceNode,
)
from autoresearch.reports import (
    PaperReviewContext,
    ReviewDimension,
    simulate_paper_review,
)
from autoresearch.schemas import ValidationStatus


def test_simulate_paper_review_scores_all_dimensions_without_perfect_default() -> None:
    context = _complete_context()

    report = simulate_paper_review(context)

    assert {score.dimension for score in report.scores} == set(ReviewDimension)
    assert all(0.0 <= score.score < 1.0 for score in report.scores)
    assert report.score_for(ReviewDimension.TECHNICAL_SOUNDNESS) <= 0.95
    assert report.findings == ()


def test_missing_evidence_lowers_technical_soundness_and_reproducibility() -> None:
    complete = simulate_paper_review(_complete_context())
    missing = simulate_paper_review(_missing_evidence_context())

    assert missing.score_for(ReviewDimension.TECHNICAL_SOUNDNESS) < complete.score_for(
        ReviewDimension.TECHNICAL_SOUNDNESS
    )
    assert missing.score_for(ReviewDimension.REPRODUCIBILITY) < complete.score_for(
        ReviewDimension.REPRODUCIBILITY
    )
    assert {
        finding.dimension
        for finding in missing.findings
    } >= {
        ReviewDimension.TECHNICAL_SOUNDNESS,
        ReviewDimension.REPRODUCIBILITY,
    }


def _complete_context() -> PaperReviewContext:
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_accuracy",
            statement="The method improves accuracy over the baseline.",
        )
    )
    graph.add_source(SourceNode(id="source_run_001", title="Run run_001", uri="runs/run_001"))
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
            summary="Validated accuracy metric.",
        )
    )
    return PaperReviewContext(
        title="Demo Paper",
        evidence_graph=graph,
        core_claim_ids=["claim_accuracy"],
        novelty_refs=["doc_1", "doc_2"],
        has_baseline=True,
        has_ablation=True,
        has_statistical_sanity=True,
        reproducibility_artifacts=[
            "config.yaml",
            "metrics.json",
            "validation-report.json",
            "evidence-map.json",
            "run.log",
        ],
        section_text=dict.fromkeys(_sections(), "content"),
        compliance_checks={"has_limitations": True, "has_references": True},
    )


def _missing_evidence_context() -> PaperReviewContext:
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_accuracy",
            statement="The method improves accuracy over the baseline.",
        )
    )
    return PaperReviewContext(
        title="Demo Paper",
        evidence_graph=graph,
        core_claim_ids=["claim_accuracy"],
        novelty_refs=["doc_1", "doc_2"],
        has_baseline=True,
        has_ablation=True,
        has_statistical_sanity=True,
        reproducibility_artifacts=[
            "config.yaml",
            "metrics.json",
            "validation-report.json",
            "evidence-map.json",
            "run.log",
        ],
        section_text=dict.fromkeys(_sections(), "content"),
        compliance_checks={"has_limitations": True, "has_references": True},
    )


def _sections() -> tuple[str, ...]:
    return (
        "abstract",
        "introduction",
        "related_work",
        "method",
        "experiments",
        "results",
        "limitations",
        "conclusion",
    )
