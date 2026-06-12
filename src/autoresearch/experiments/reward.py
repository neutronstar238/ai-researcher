"""Strategy reward calculation for controlled self-evolution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrategyRewardInput(BaseModel):
    """Normalized inputs used to compare a candidate strategy."""

    model_config = ConfigDict(extra="forbid")

    baseline_quality: float = Field(ge=0.0)
    candidate_quality: float = Field(ge=0.0)
    reproducibility_score: float = Field(ge=0.0, le=1.0)
    evidence_completeness: float = Field(ge=0.0, le=1.0)
    baseline_cost: float = Field(default=0.0, ge=0.0)
    candidate_cost: float = Field(default=0.0, ge=0.0)
    baseline_human_interventions: int = Field(default=0, ge=0)
    candidate_human_interventions: int = Field(default=0, ge=0)
    risk_penalty: float = Field(default=0.0, ge=0.0, le=1.0)


class StrategyRewardWeights(BaseModel):
    """Weights for reward components."""

    model_config = ConfigDict(extra="forbid")

    quality_gain: float = 1.0
    reproducibility: float = 0.25
    evidence_completeness: float = 0.25
    cost_increase: float = 0.2
    human_intervention: float = 0.1
    risk_penalty: float = 0.8


class StrategyRewardResult(BaseModel):
    """Reward score and component breakdown."""

    model_config = ConfigDict(extra="forbid")

    reward: float
    quality_gain: float
    cost_increase_ratio: float
    human_intervention_increase: int
    components: dict[str, float]


def calculate_strategy_reward(
    inputs: StrategyRewardInput,
    weights: StrategyRewardWeights | None = None,
) -> StrategyRewardResult:
    """Calculate candidate strategy reward from quality, cost, evidence, and risk."""

    resolved_weights = weights or StrategyRewardWeights()
    quality_gain = inputs.candidate_quality - inputs.baseline_quality
    cost_increase_ratio = _cost_increase_ratio(inputs.baseline_cost, inputs.candidate_cost)
    human_intervention_increase = max(
        inputs.candidate_human_interventions - inputs.baseline_human_interventions,
        0,
    )
    components = {
        "quality_gain": quality_gain * resolved_weights.quality_gain,
        "reproducibility": inputs.reproducibility_score * resolved_weights.reproducibility,
        "evidence_completeness": inputs.evidence_completeness
        * resolved_weights.evidence_completeness,
        "cost_increase": -(cost_increase_ratio * resolved_weights.cost_increase),
        "human_intervention": -(
            human_intervention_increase * resolved_weights.human_intervention
        ),
        "risk_penalty": -(inputs.risk_penalty * resolved_weights.risk_penalty),
    }
    reward = round(sum(components.values()), 6)
    return StrategyRewardResult(
        reward=reward,
        quality_gain=round(quality_gain, 6),
        cost_increase_ratio=round(cost_increase_ratio, 6),
        human_intervention_increase=human_intervention_increase,
        components={key: round(value, 6) for key, value in components.items()},
    )


def _cost_increase_ratio(baseline_cost: float, candidate_cost: float) -> float:
    increase = max(candidate_cost - baseline_cost, 0.0)
    if increase == 0.0:
        return 0.0
    if baseline_cost > 0.0:
        return increase / baseline_cost
    return increase
