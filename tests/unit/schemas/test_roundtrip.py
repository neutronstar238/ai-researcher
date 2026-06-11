import pytest
from pydantic import ValidationError

from autoresearch.schemas import (
    CostRecord,
    DocumentRecord,
    EvidenceEdge,
    ExecutionRun,
    ExperimentTask,
    Hypothesis,
    KnowledgeNode,
    PaperDraft,
    ResearchCandidate,
    ResultBundle,
    StrategyCard,
)


def test_core_schemas_round_trip_through_json() -> None:
    records = [
        DocumentRecord(title="Paper", source_uri="https://example.com/paper"),
        KnowledgeNode(
            title="Topic",
            node_type="topic",
            vault_path="autoresearch-vault/exploration/topics/topic.md",
            zone="exploration",
            metadata={"owner": "main_agent"},
        ),
        ResearchCandidate(
            title="Candidate",
            description="A possible direction",
            research_gap="A validated gap",
            novelty_score=0.7,
            feasibility_score=0.8,
            impact_score=0.6,
            evidence_refs=["doc_1"],
        ),
        Hypothesis(
            candidate_id="candidate_1",
            statement="Method A improves metric B.",
            prediction="Metric B increases.",
            metric="macro_f1",
            baseline="baseline_b",
            evidence_refs=["doc_1"],
        ),
        ExperimentTask(
            project_id="project_1",
            hypothesis_id="hypothesis_1",
            name="Run baseline",
            description="Run a baseline experiment.",
            entrypoint="run.py",
            config_path="config.yaml",
            metrics=["macro_f1"],
        ),
        CostRecord(model_name="qwen-plus", token_input=100, token_output=50),
        ExecutionRun(
            project_id="project_1",
            task_id="task_1",
            cost_record=CostRecord(model_name="qwen-plus", token_input=100),
        ),
        ResultBundle(run_id="run_1", metrics={"macro_f1": 0.8}),
        EvidenceEdge(
            claim_id="claim_1",
            evidence_ref="metric_macro_f1",
            source_artifact="metrics.json",
        ),
        PaperDraft(
            project_id="project_1",
            title="Draft",
            draft_path="paper/main.tex",
            evidence_map_path="evidence_map.json",
        ),
        StrategyCard(strategy_type="prompt", content="Use evidence first."),
    ]

    for record in records:
        round_tripped = type(record).model_validate_json(record.model_dump_json())

        assert round_tripped == record


@pytest.mark.parametrize(
    ("model_type", "payload"),
    [
        (
            ResearchCandidate,
            {
                "title": "Candidate",
                "description": "A possible direction",
                "research_gap": "A validated gap",
                "novelty_score": 0.7,
                "feasibility_score": 0.8,
                "impact_score": 0.6,
            },
        ),
        (
            Hypothesis,
            {
                "candidate_id": "candidate_1",
                "statement": "Method A improves metric B.",
                "prediction": "Metric B increases.",
                "metric": "macro_f1",
                "baseline": "baseline_b",
            },
        ),
    ],
)
def test_schema_validation_rejects_missing_evidence_refs(
    model_type: type[ResearchCandidate] | type[Hypothesis],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model_type.model_validate(payload)


def test_schemas_reject_unknown_fields_but_preserve_metadata() -> None:
    with pytest.raises(ValidationError):
        KnowledgeNode.model_validate(
            {
                "title": "Topic",
                "node_type": "topic",
                "vault_path": "autoresearch-vault/exploration/topics/topic.md",
                "zone": "exploration",
                "unknown": "not allowed",
            }
        )

    node = KnowledgeNode(
        title="Topic",
        node_type="topic",
        vault_path="autoresearch-vault/exploration/topics/topic.md",
        zone="exploration",
        metadata={"unknown": "allowed here"},
    )

    assert node.metadata == {"unknown": "allowed here"}
