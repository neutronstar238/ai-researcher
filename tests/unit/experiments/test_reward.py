from autoresearch.experiments import StrategyRewardInput, calculate_strategy_reward


def test_strategy_reward_scores_quality_improvement() -> None:
    result = calculate_strategy_reward(
        StrategyRewardInput(
            baseline_quality=0.70,
            candidate_quality=0.82,
            reproducibility_score=0.80,
            evidence_completeness=0.90,
            baseline_cost=1.0,
            candidate_cost=1.0,
        )
    )

    assert result.quality_gain == 0.12
    assert result.cost_increase_ratio == 0.0
    assert result.components["quality_gain"] == 0.12
    assert result.reward == 0.545


def test_strategy_reward_penalizes_cost_increase() -> None:
    baseline = calculate_strategy_reward(
        StrategyRewardInput(
            baseline_quality=0.70,
            candidate_quality=0.82,
            reproducibility_score=0.80,
            evidence_completeness=0.90,
            baseline_cost=1.0,
            candidate_cost=1.0,
        )
    )
    costlier = calculate_strategy_reward(
        StrategyRewardInput(
            baseline_quality=0.70,
            candidate_quality=0.82,
            reproducibility_score=0.80,
            evidence_completeness=0.90,
            baseline_cost=1.0,
            candidate_cost=3.0,
        )
    )

    assert costlier.cost_increase_ratio == 2.0
    assert costlier.components["cost_increase"] == -0.4
    assert costlier.reward < baseline.reward


def test_strategy_reward_penalizes_risk_and_human_intervention() -> None:
    result = calculate_strategy_reward(
        StrategyRewardInput(
            baseline_quality=0.70,
            candidate_quality=0.70,
            reproducibility_score=0.20,
            evidence_completeness=0.20,
            baseline_cost=2.0,
            candidate_cost=4.0,
            baseline_human_interventions=0,
            candidate_human_interventions=2,
            risk_penalty=0.90,
        )
    )

    assert result.human_intervention_increase == 2
    assert result.components["risk_penalty"] == -0.72
    assert result.reward < 0.0
