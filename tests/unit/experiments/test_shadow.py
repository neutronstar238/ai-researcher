import json
from pathlib import Path

from autoresearch.experiments import (
    ReplayCase,
    run_shadow_evaluation,
    write_shadow_evaluation,
)
from autoresearch.schemas import StrategyCard


def test_shadow_output_is_recorded_separately_and_production_unchanged(
    tmp_path: Path,
) -> None:
    replay_case = ReplayCase(
        case_id="replay_literature_1",
        task_id="task_literature_1",
        run_id="run_literature_1",
        baseline_metric="accuracy",
        baseline_score=0.9,
        inputs={"query": "evidence grounded retrieval"},
        outputs={
            "metrics": {"accuracy": 0.9},
            "decision": "production_result",
        },
        evidence=[],
        costs={"cost_json": {"total_cost": 1.0}},
        validation={"status": "passed"},
    )
    strategy = StrategyCard(
        id="strategy_retrieval_shadow_v2",
        strategy_type="retrieval_policy",
        content="Try broader query expansion in shadow mode.",
        release_status="shadow",
    )
    production_before = replay_case.outputs.copy()

    record = run_shadow_evaluation(
        strategy=strategy,
        replay_case=replay_case,
        propose_output=_candidate_proposal,
    )
    path = write_shadow_evaluation(tmp_path / "shadow" / "record.json", record)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert replay_case.outputs == production_before
    assert record.production_unchanged is True
    assert record.production_output["metrics"]["accuracy"] == 0.9
    assert record.shadow_output["metrics"]["accuracy"] == 0.93
    assert record.shadow_output["decision"] == "shadow_candidate"
    assert payload["shadow_output"]["decision"] == "shadow_candidate"
    assert payload["production_output"]["decision"] == "production_result"


def _candidate_proposal(strategy: StrategyCard, replay_case: ReplayCase) -> dict[str, object]:
    replay_case.outputs["metrics"]["accuracy"] = 0.93
    replay_case.outputs["decision"] = "shadow_candidate"
    return {
        "strategy_id": strategy.id,
        "metrics": {"accuracy": 0.93},
        "decision": replay_case.outputs["decision"],
    }
