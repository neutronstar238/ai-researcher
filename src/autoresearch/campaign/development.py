"""Honest local development adapter for campaign lifecycle and CLI smoke tests.

This adapter executes deterministic numerical calculations and writes real
metrics/log files, but its contribution gate always fails because the task is a
generated fixture rather than an official scientific benchmark.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.campaign.models import (
    ContributionGateResult,
    DevelopmentResult,
    FailureDiagnosis,
    FailureKind,
    FreezeInputs,
    FrozenRoundProtocol,
    HypothesisProposal,
    HypothesisScreening,
    Preregistration,
    PreregistrationInputs,
    RoundDevelopmentContext,
    RoundObservation,
    RoundOutcome,
    UnseenEvaluation,
)
from autoresearch.schemas import data_hash, file_hash


class DevelopmentFixtureCampaignAdapter:
    """Run a local, non-publication fixture through every campaign stage."""

    adapter_id = "development-fixture-v1"

    def __init__(self, evidence_root: Path | str) -> None:
        self.evidence_root = Path(evidence_root).resolve()

    def observe(self, context: RoundDevelopmentContext) -> RoundObservation:
        return RoundObservation(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            evidence_refs=context.historical_evidence_refs,
            summary=(
                "Inspect the parent result and fixture evidence without current-round "
                "unseen references."
            ),
            observed_failures=(
                "The previous mechanism did not clear its frozen contribution gate.",
            ),
        )

    def diagnose(
        self,
        context: RoundDevelopmentContext,
        observation: RoundObservation,
    ) -> FailureDiagnosis:
        return FailureDiagnosis(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            failure_kind=(
                FailureKind.ROOT_NEGATIVE_RESULT
                if context.round_number == 1
                else FailureKind.CONTRIBUTION_INSUFFICIENT
            ),
            observations=observation.observed_failures,
            causal_hypothesis=(
                "The current fixture mechanism lacks external-benchmark evidence and "
                "cannot support a scientific contribution claim."
            ),
            required_mechanism_change=(
                "Select the next preregistered mechanism family and a disjoint evaluation set."
            ),
            constraints=(
                "do not inspect current unseen values before freeze",
                "never promote fixture metrics into a publication claim",
            ),
            evidence_refs=observation.evidence_refs,
        )

    def propose(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
    ) -> HypothesisProposal:
        mechanism = context.candidate_mechanism_families[0]
        return HypothesisProposal(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            title=f"Development fixture: {mechanism}",
            statement=(
                "The selected fixture mechanism will reduce deterministic held-out error "
                "relative to the fixture baseline."
            ),
            mechanism_family=mechanism,
            mechanism_change=diagnosis.required_mechanism_change,
            repair_rationale=diagnosis.causal_hypothesis,
            predicted_effect="Non-constant executable metrics with an auditable causal chain.",
            primary_metric=context.primary_metric,
            evidence_refs=(context.development_data_refs[0],),
            falsification_conditions=(
                "development metrics are missing or constant",
                "the frozen fixture evaluation does not improve",
                "official-benchmark evidence remains absent",
            ),
        )

    def screen(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
        proposal: HypothesisProposal,
    ) -> HypothesisScreening:
        del diagnosis
        return HypothesisScreening(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            passed=True,
            reasons=("local deterministic fixture is executable",),
            development_score=0.2 + 0.01 * context.round_number,
            duplicate_risk=0.0,
            estimated_wall_time_seconds=1,
        )

    def preregistration_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        screening: HypothesisScreening,
    ) -> PreregistrationInputs:
        del proposal, screening
        return PreregistrationInputs(
            parameter_space={
                "candidate_scale": [0.75, 0.9],
                "candidate_bias": [0.0, 0.1],
                "selection": "development_mse_only",
            },
            stop_rules=(
                "evaluate exactly one development-selected configuration",
                "stop after the frozen evaluation and retain a negative contribution gate",
            ),
            implementation_family_hashes={"fixture_adapter": file_hash(Path(__file__))},
            adjudicator_hash=data_hash(
                {
                    "adapter_id": self.adapter_id,
                    "policy": "fixture evidence can never pass a scientific contribution gate",
                    "round": context.round_number,
                }
            ),
        )

    def develop(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
    ) -> DevelopmentResult:
        started = datetime.now(timezone.utc)
        baseline_mse = _mean_squared_error(scale=0.7, bias=0.2)
        candidate_scale = 0.9 if context.round_number > 1 else 0.75
        candidate_bias = 0.0 if context.round_number > 1 else 0.1
        candidate_mse = _mean_squared_error(
            scale=candidate_scale,
            bias=candidate_bias,
        )
        improvement = (baseline_mse - candidate_mse) / baseline_mse
        evidence_dir = self._round_evidence_dir(context.round_id)
        metrics_path = _write_json(
            evidence_dir / "development-metrics.json",
            {
                "baseline_mse": baseline_mse,
                "candidate_mse": candidate_mse,
                "relative_improvement": improvement,
                "development_refs": preregistration.development_data_refs,
            },
        )
        log_path = _write_text(
            evidence_dir / "development.log",
            "Executed deterministic linear fixture on development coordinates.\n"
            f"selected scale={candidate_scale}, bias={candidate_bias}\n",
        )
        return DevelopmentResult(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            preregistration_hash=_required(preregistration.preregistration_hash),
            passed=True,
            selected_configuration={
                "candidate_scale": candidate_scale,
                "candidate_bias": candidate_bias,
            },
            metrics={
                "baseline_mse": baseline_mse,
                "candidate_mse": candidate_mse,
                "relative_improvement": improvement,
            },
            evidence_paths=(metrics_path.as_posix(), log_path.as_posix()),
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    def freeze_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        development: DevelopmentResult,
    ) -> FreezeInputs:
        del context, proposal
        return FreezeInputs(
            selected_config_hash=data_hash(development.selected_configuration),
            code_hashes={"fixture_adapter": file_hash(Path(__file__))},
            adjudicator_hash=preregistration.adjudicator_hash,
        )

    def evaluate_unseen(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
    ) -> UnseenEvaluation:
        started = datetime.now(timezone.utc)
        round_number = int(frozen_protocol.round_id.rsplit("-", 1)[1])
        baseline_mse = _mean_squared_error(scale=0.68, bias=0.22, start=10)
        candidate_mse = _mean_squared_error(
            scale=0.88 if round_number > 1 else 0.5,
            bias=0.02 if round_number > 1 else 0.3,
            start=10,
        )
        improvement = (baseline_mse - candidate_mse) / baseline_mse
        evidence_dir = self._round_evidence_dir(frozen_protocol.round_id)
        metrics_path = _write_json(
            evidence_dir / "unseen-metrics.json",
            {
                "baseline_mse": baseline_mse,
                "candidate_mse": candidate_mse,
                "relative_improvement": improvement,
                "unseen_refs": preregistration.unseen_data_refs,
                "seeds": preregistration.seeds,
                "fixture_only": True,
            },
        )
        return UnseenEvaluation(
            round_id=frozen_protocol.round_id,
            hypothesis_id=proposal.hypothesis_id,
            frozen_hash=_required(frozen_protocol.frozen_hash),
            outcome=(
                RoundOutcome.POSITIVE_RESULT
                if improvement > 0.0
                else RoundOutcome.NEGATIVE_RESULT
            ),
            metrics={
                "baseline_mse": baseline_mse,
                "candidate_mse": candidate_mse,
                "relative_improvement": improvement,
                "bootstrap_ci95_lower": improvement - 0.02,
                "bootstrap_ci95_upper": improvement + 0.02,
            },
            evidence_paths=(metrics_path.as_posix(),),
            mandatory_evidence_complete=True,
            human_intervention_count=0,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    def adjudicate(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
        evaluation: UnseenEvaluation,
    ) -> ContributionGateResult:
        del proposal
        return ContributionGateResult(
            round_id=frozen_protocol.round_id,
            track=preregistration.track,
            evaluated_result_hash=_required(evaluation.result_hash),
            passed=False,
            checks={
                "executable_nonconstant_metrics": len(set(evaluation.metrics.values())) > 1,
                "three_seed_protocol": len(preregistration.seeds) >= 3,
                "zero_human_intervention": evaluation.human_intervention_count == 0,
                "official_scientific_benchmark": False,
            },
            failures=(
                "development fixture is not an official scientific benchmark",
                "fixture evidence cannot establish an original CCF-B contribution",
            ),
            evidence_paths=evaluation.evidence_paths,
        )

    def _round_evidence_dir(self, round_id: str) -> Path:
        path = self.evidence_root / round_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def _mean_squared_error(
    *,
    scale: float,
    bias: float,
    start: int = 0,
) -> float:
    squared_errors: list[float] = []
    for index in range(start, start + 12):
        x_value = index / 10.0
        truth = 2.0 * x_value + 1.0
        prediction = 2.0 * scale * x_value + 1.0 + bias
        squared_errors.append((truth - prediction) ** 2)
    return sum(squared_errors) / len(squared_errors)


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    return _write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
    )


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("required persisted hash is missing")
    return value
