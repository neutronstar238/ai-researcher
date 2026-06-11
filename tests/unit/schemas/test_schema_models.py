from autoresearch.schemas import (
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
    ValidationStatus,
)


def test_core_schemas_instantiate_and_serialize_to_json() -> None:
    records = [
        DocumentRecord(title="Paper", source_uri="https://example.com/paper"),
        KnowledgeNode(
            title="Topic",
            node_type="topic",
            vault_path="autoresearch-vault/exploration/topics/topic.md",
            zone="exploration",
        ),
        ResearchCandidate(
            title="Candidate",
            description="A possible direction",
            research_gap="A validated gap",
            novelty_score=0.7,
            feasibility_score=0.8,
            impact_score=0.6,
        ),
        Hypothesis(
            candidate_id="candidate_1",
            statement="Method A improves metric B.",
            prediction="Metric B increases.",
            metric="macro_f1",
            baseline="baseline_b",
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
        ExecutionRun(project_id="project_1", task_id="task_1"),
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
        payload = record.model_dump_json()

        assert record.id
        assert record.created_at
        assert record.updated_at
        assert "validation" in payload or isinstance(record, ExecutionRun)


def test_strategy_card_bounds_evaluation_score() -> None:
    strategy = StrategyCard(
        strategy_type="workflow",
        content="Replay before shadow evaluation.",
        evaluation_score=1.0,
        golden_test_status=ValidationStatus.PASSED,
    )

    assert strategy.evaluation_score == 1.0
    assert strategy.golden_test_status is ValidationStatus.PASSED
