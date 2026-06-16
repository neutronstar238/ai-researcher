import pytest
from pydantic import ValidationError

from autoresearch.schemas import (
    ALLOWED_STRATEGY_TARGETS,
    PROHIBITED_STRATEGY_TARGETS,
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
            evidence_refs=["candidate_evidence"],
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
        CostRecord(
            model_name="qwen-plus",
            token_input=100,
            token_output=50,
            cpu_time_seconds=2.5,
            gpu_hours=0.0,
            storage_artifact_bytes=1024,
            human_approval_count=1,
        ),
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
        payload = record.model_dump_json()

        assert record.id
        assert record.created_at
        assert record.updated_at
        assert "validation" in payload or isinstance(record, ExecutionRun | CostRecord)


def test_strategy_card_bounds_evaluation_score() -> None:
    strategy = StrategyCard(
        strategy_type="workflow",
        content="Replay before shadow evaluation.",
        evaluation_score=1.0,
        golden_test_status=ValidationStatus.PASSED,
    )

    assert strategy.evaluation_score == 1.0
    assert strategy.strategy_type == "workflow_template"
    assert strategy.golden_test_status is ValidationStatus.PASSED


@pytest.mark.parametrize("strategy_type", sorted(ALLOWED_STRATEGY_TARGETS))
def test_strategy_card_accepts_allowed_strategy_targets(strategy_type: str) -> None:
    strategy = StrategyCard(strategy_type=strategy_type, content="Candidate mutation.")

    assert strategy.strategy_type == strategy_type


@pytest.mark.parametrize("strategy_type", sorted(PROHIBITED_STRATEGY_TARGETS))
def test_strategy_card_rejects_prohibited_strategy_targets(strategy_type: str) -> None:
    with pytest.raises(ValidationError, match="prohibited"):
        StrategyCard(strategy_type=strategy_type, content="Do not mutate this policy.")


def test_strategy_card_rejects_unknown_strategy_target() -> None:
    with pytest.raises(ValidationError, match="strategy_type must be one of"):
        StrategyCard(strategy_type="deployment_policy", content="Unknown mutation target.")


def test_cost_record_validates_required_fields_and_bounds() -> None:
    cost = CostRecord(
        model_name="qwen-plus",
        token_input=10,
        token_output=20,
        cpu_time_seconds=1.5,
        gpu_hours=0.25,
        storage_artifact_bytes=2048,
        network_cost_usd_placeholder=0.0,
        human_approval_count=2,
    )
    run = ExecutionRun(project_id="project_1", task_id="task_1", cost_record=cost)

    assert run.cost_record == cost
    assert cost.token_input == 10
    assert cost.human_approval_count == 2

    with pytest.raises(ValidationError):
        CostRecord.model_validate(
            {
                "model_name": "",
                "token_input": -1,
                "token_output": -1,
                "cpu_time_seconds": -0.1,
                "gpu_hours": -0.1,
                "storage_artifact_bytes": -1,
                "network_cost_usd_placeholder": -0.1,
                "human_approval_count": -1,
            }
        )
