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
    ResearchPlan,
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
        ResearchPlan(
            project_id="project_1",
            candidate_id="candidate_1",
            title="Evidence-Calibrated Baseline Study",
            problem_statement="A validated gap needs a plan.",
            rationale="The plan is evidence-bound.",
            technical_details="Use a baseline, metric, and source dataset.",
            datasets={"source": "public dataset", "target": "hold-out split"},
            methods="Compare the method with a baseline using macro_f1 metric.",
            experiments=["Run baseline.", "Run method.", "Run ablation."],
            expected_results="Expected, not yet observed: metric changes require real runs.",
            code_agent_brief="Run python scripts/run_experiment.py and save metrics.json.",
            risks_and_alternatives=["Baseline may fail.", "Dataset license may block use."],
            references=["https://example.com/paper"],
            evidence_refs=["https://example.com/paper"],
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


def test_hypothesis_validation_rejects_missing_metric_and_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(
            candidate_id="candidate_1",
            statement="Method A improves metric B.",
            prediction="Metric B increases.",
            metric="",
            baseline="baseline_b",
            evidence_refs=[],
        )


def test_experiment_task_validation_rejects_missing_required_execution_fields() -> None:
    with pytest.raises(ValidationError):
        ExperimentTask(
            project_id="project_1",
            hypothesis_id="hypothesis_1",
            name="",
            description="Run experiment.",
            entrypoint="",
            config_path="",
            metrics=[],
        )
