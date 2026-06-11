import pytest

from autoresearch.evidence import (
    ClaimNode,
    ClaimStatus,
    EvidenceArtifact,
    EvidenceCoverageError,
    EvidenceGraph,
    EvidenceGraphError,
    EvidenceNode,
    SourceNode,
)
from autoresearch.schemas import ValidationStatus


def test_evidence_graph_round_trips_and_traces_claim_to_artifact_status(tmp_path):
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_macro_f1",
            statement="The candidate improves macro F1 on the benchmark.",
            project_id="autoresearch-system",
        )
    )
    graph.add_source(
        SourceNode(
            id="source_run_001",
            title="Experiment run run_001",
            uri="runs/run_001",
            source_type="experiment_run",
        )
    )
    graph.add_artifact(
        EvidenceArtifact(
            id="artifact_metrics",
            source_id="source_run_001",
            uri="runs/run_001/metrics.json",
            artifact_type="metrics",
            validation_status=ValidationStatus.PASSED,
        )
    )
    graph.link_evidence(
        EvidenceNode(
            id="evidence_macro_f1",
            claim_id="claim_macro_f1",
            source_id="source_run_001",
            artifact_id="artifact_metrics",
            summary="Validated macro F1 metric from run_001.",
        )
    )

    graph_path = graph.save_json(tmp_path / "evidence-graph.json")
    loaded = EvidenceGraph.load_json(graph_path)
    traces = loaded.trace_claim("claim_macro_f1")

    assert len(traces) == 1
    assert traces[0].claim.statement.startswith("The candidate improves")
    assert traces[0].evidence.supports_claim is True
    assert traces[0].source.uri == "runs/run_001"
    assert traces[0].artifact.uri == "runs/run_001/metrics.json"
    assert traces[0].validation_status is ValidationStatus.PASSED

    loaded.require_core_claim_coverage(["claim_macro_f1"])

    assert loaded.claims["claim_macro_f1"].status is ClaimStatus.SUPPORTED


def test_evidence_graph_marks_unsupported_core_claims_blocked():
    graph = EvidenceGraph()
    graph.add_claim(
        ClaimNode(
            id="claim_macro_f1",
            statement="The candidate improves macro F1 on the benchmark.",
        )
    )

    with pytest.raises(EvidenceCoverageError, match="claim_macro_f1"):
        graph.require_core_claim_coverage(["claim_macro_f1"])

    assert graph.claims["claim_macro_f1"].status is ClaimStatus.BLOCKED


def test_evidence_graph_rejects_orphaned_artifacts():
    graph = EvidenceGraph()

    with pytest.raises(EvidenceGraphError, match="missing source"):
        graph.add_artifact(
            EvidenceArtifact(
                id="artifact_metrics",
                source_id="source_missing",
                uri="metrics.json",
            )
        )
