from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoresearch.campaign import (
    AutonomousResearchCampaign,
    CampaignIntegrityError,
    CampaignOutcome,
    CampaignRoundDesign,
    CampaignSpec,
    CampaignStage,
    CampaignTrack,
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
    load_campaign_manifest,
    load_round_manifest,
)
from autoresearch.schemas import data_hash

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


class ScriptedCampaignAdapter:
    adapter_id = "scripted-real-metric-adapter-v1"

    def __init__(
        self,
        outcomes: tuple[RoundOutcome, ...] = (
            RoundOutcome.NEGATIVE_RESULT,
            RoundOutcome.POSITIVE_RESULT,
        ),
        *,
        screening_passes: tuple[bool, ...] = (True, True),
        leak_unseen_ref: str | None = None,
        force_mechanism: str | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.screening_passes = screening_passes
        self.leak_unseen_ref = leak_unseen_ref
        self.force_mechanism = force_mechanism
        self.calls: Counter[tuple[str, str]] = Counter()

    def observe(self, context: RoundDevelopmentContext) -> RoundObservation:
        self.calls[("observe", context.round_id)] += 1
        return RoundObservation(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            evidence_refs=context.historical_evidence_refs,
            summary=f"Observe parent evidence for {context.round_id}.",
            observed_failures=("noise robustness failed",),
        )

    def diagnose(
        self,
        context: RoundDevelopmentContext,
        observation: RoundObservation,
    ) -> FailureDiagnosis:
        self.calls[("diagnose", context.round_id)] += 1
        return FailureDiagnosis(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            failure_kind=(
                FailureKind.ROOT_NEGATIVE_RESULT
                if context.round_number == 1
                else FailureKind.UNSEEN_PERFORMANCE
            ),
            observations=observation.observed_failures or ("confirmation required",),
            causal_hypothesis="Pointwise derivative noise destabilized selected support.",
            required_mechanism_change="Change derivative estimation and support objective.",
            constraints=("do not tune on current unseen data",),
            evidence_refs=observation.evidence_refs,
        )

    def propose(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
    ) -> HypothesisProposal:
        self.calls[("propose", context.round_id)] += 1
        mechanism = self.force_mechanism or context.candidate_mechanism_families[0]
        evidence_refs: tuple[str, ...] = (context.development_data_refs[0],)
        if self.leak_unseen_ref is not None:
            evidence_refs = (*evidence_refs, self.leak_unseen_ref)
        return HypothesisProposal(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            title=f"{mechanism} repair",
            statement="The changed mechanism will improve the preregistered primary metric.",
            mechanism_family=mechanism,
            mechanism_change=diagnosis.required_mechanism_change,
            repair_rationale=diagnosis.causal_hypothesis,
            predicted_effect="At least 15% median relative improvement on development data.",
            primary_metric=context.primary_metric,
            evidence_refs=evidence_refs,
            falsification_conditions=("development gain below 15%", "unseen CI crosses zero"),
        )

    def screen(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
        proposal: HypothesisProposal,
    ) -> HypothesisScreening:
        del diagnosis
        self.calls[("screen", context.round_id)] += 1
        passed = self.screening_passes[context.round_number - 1]
        return HypothesisScreening(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            passed=passed,
            reasons=() if passed else ("development feasibility threshold not met",),
            development_score=0.24 if passed else -0.04,
            duplicate_risk=0.2,
            estimated_wall_time_seconds=12,
        )

    def preregistration_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        screening: HypothesisScreening,
    ) -> PreregistrationInputs:
        del proposal, screening
        self.calls[("preregister", context.round_id)] += 1
        return PreregistrationInputs(
            parameter_space={"smoothing": [0.1, 0.2], "threshold": [0.01, 0.05]},
            stop_rules=("stop after frozen unseen adjudication",),
            implementation_family_hashes={
                "candidate": data_hash(f"candidate:{context.round_id}")
            },
            adjudicator_hash=data_hash("fixed-adjudicator-v1"),
        )

    def develop(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
    ) -> DevelopmentResult:
        self.calls[("develop", context.round_id)] += 1
        return DevelopmentResult(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            preregistration_hash=_required(preregistration.preregistration_hash),
            passed=True,
            selected_configuration={"smoothing": 0.2, "threshold": 0.01},
            metrics={"median_relative_improvement": 0.24, "valid_cell_rate": 1.0},
            evidence_paths=(f"evidence/{context.round_id}/development-metrics.json",),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=3),
        )

    def freeze_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        development: DevelopmentResult,
    ) -> FreezeInputs:
        del proposal
        self.calls[("freeze", context.round_id)] += 1
        return FreezeInputs(
            selected_config_hash=data_hash(development.selected_configuration),
            code_hashes={"runner": data_hash(f"runner:{context.round_id}")},
            adjudicator_hash=preregistration.adjudicator_hash,
        )

    def evaluate_unseen(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
    ) -> UnseenEvaluation:
        del preregistration
        round_number = int(frozen_protocol.round_id.rsplit("-", 1)[1])
        self.calls[("evaluate_unseen", frozen_protocol.round_id)] += 1
        outcome = self.outcomes[round_number - 1]
        effect = -0.12 if outcome is RoundOutcome.NEGATIVE_RESULT else 0.31
        return UnseenEvaluation(
            round_id=frozen_protocol.round_id,
            hypothesis_id=proposal.hypothesis_id,
            frozen_hash=_required(frozen_protocol.frozen_hash),
            outcome=outcome,
            metrics={
                "median_relative_improvement": effect,
                "bootstrap_ci95_lower": effect - 0.05,
                "bootstrap_ci95_upper": effect + 0.05,
            },
            evidence_paths=(
                f"evidence/{frozen_protocol.round_id}/unseen-metrics.json",
            ),
            mandatory_evidence_complete=True,
            human_intervention_count=0,
            started_at=NOW + timedelta(seconds=4),
            completed_at=NOW + timedelta(seconds=8),
        )

    def adjudicate(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
        evaluation: UnseenEvaluation,
    ) -> ContributionGateResult:
        del proposal, preregistration
        self.calls[("adjudicate", frozen_protocol.round_id)] += 1
        passed = evaluation.outcome is RoundOutcome.POSITIVE_RESULT
        return ContributionGateResult(
            round_id=frozen_protocol.round_id,
            track=CampaignTrack.SCIENTIFIC_ML_METHOD,
            evaluated_result_hash=_required(evaluation.result_hash),
            passed=passed,
            checks={
                "bootstrap_ci_lower_above_zero": passed,
                "three_seed_reproducible": True,
                "mandatory_evidence_complete": evaluation.mandatory_evidence_complete,
                "zero_human_intervention": evaluation.human_intervention_count == 0,
            },
            failures=() if passed else ("unseen bootstrap CI did not clear zero",),
            evidence_paths=evaluation.evidence_paths,
        )


def _spec(*, deadline: datetime | None = None, min_rounds: int = 2) -> CampaignSpec:
    return CampaignSpec(
        campaign_id="task260-two-round-campaign",
        project_id="task260-campaign",
        deadline=deadline or NOW + timedelta(days=7),
        min_experimental_rounds=min_rounds,
        root_result_hash=data_hash("immutable-parent-negative-result"),
        root_evidence_refs=("evidence/root-negative-report.json",),
        round_designs=(
            CampaignRoundDesign(
                round_number=1,
                track=CampaignTrack.SCIENTIFIC_ML_METHOD,
                development_data_refs=("mdbench:development:advection1d",),
                unseen_data_refs=("mdbench:sealed:system-a",),
                seeds=(101, 103, 107),
                candidate_mechanism_families=("noise-conditioned-spline-ensemble",),
                primary_metric="failure_aware_relative_improvement",
                acceptance_criteria=("development median improvement >= 0.15",),
            ),
            CampaignRoundDesign(
                round_number=2,
                track=CampaignTrack.SCIENTIFIC_ML_METHOD,
                development_data_refs=("mdbench:development:burgers",),
                unseen_data_refs=("mdbench:sealed:system-b",),
                seeds=(109, 113, 127),
                candidate_mechanism_families=("tv-derivative-stability",),
                primary_metric="failure_aware_relative_improvement",
                acceptance_criteria=("unseen bootstrap CI lower bound > 0",),
            ),
        ),
    )


def _required(value: str | None) -> str:
    assert value is not None
    return value


def test_campaign_runs_negative_to_new_hypothesis_to_paper_gate(
    tmp_path: Path,
) -> None:
    adapter = ScriptedCampaignAdapter()
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    result = service.run(_spec())

    assert result.outcome is CampaignOutcome.CONTRIBUTION_READY
    assert result.stage is CampaignStage.PAPER_BUILD
    assert result.completed_round_count == 2
    assert result.experimental_round_count == 2
    assert result.human_intervention_count == 0

    campaign_dir = Path(result.campaign_dir)
    manifest = load_campaign_manifest(result.manifest_path)
    assert len(manifest.round_manifest_paths) == 2
    first = load_round_manifest(campaign_dir / manifest.round_manifest_paths[0])
    second = load_round_manifest(campaign_dir / manifest.round_manifest_paths[1])
    assert first.outcome is RoundOutcome.NEGATIVE_RESULT
    assert second.outcome is RoundOutcome.POSITIVE_RESULT
    assert second.parent_round_manifest_hash == first.manifest_hash

    first_evaluation = json.loads(
        (campaign_dir / first.artifact_paths["unseen_evaluation"]).read_text(
            encoding="utf-8"
        )
    )
    second_proposal = HypothesisProposal.model_validate_json(
        (campaign_dir / second.artifact_paths["hypothesis"]).read_text(encoding="utf-8")
    )
    first_proposal = HypothesisProposal.model_validate_json(
        (campaign_dir / first.artifact_paths["hypothesis"]).read_text(encoding="utf-8")
    )
    assert second.parent_result_hash == first_evaluation["result_hash"]
    assert second_proposal.parent_result_hash == first_evaluation["result_hash"]
    assert second_proposal.mechanism_family != first_proposal.mechanism_family
    assert "mdbench:sealed:system-b" not in json.dumps(
        second_proposal.model_dump(mode="json")
    )
    assert [transition.stage for transition in second.stage_history] == [
        CampaignStage.OBSERVE,
        CampaignStage.DIAGNOSE,
        CampaignStage.PROPOSE,
        CampaignStage.SCREEN,
        CampaignStage.PREREGISTER,
        CampaignStage.DEVELOP,
        CampaignStage.FREEZE,
        CampaignStage.UNSEEN_EVALUATE,
        CampaignStage.ADJUDICATE,
        CampaignStage.REPORT,
    ]
    assert first.vault_note_path is not None
    assert second.vault_note_path is not None
    assert Path(first.vault_note_path).is_file()
    assert Path(second.vault_note_path).is_file()

    calls_before_resume = adapter.calls.copy()
    resumed = service.resume(campaign_dir)
    assert resumed == result
    assert adapter.calls == calls_before_resume
    assert service.status(campaign_dir) == result


def test_campaign_rejects_current_unseen_reference_in_proposal(tmp_path: Path) -> None:
    adapter = ScriptedCampaignAdapter(leak_unseen_ref="mdbench:sealed:system-a")
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="unseen data references"):
        service.run(_spec())

    campaign_dir = tmp_path / "runs" / "task260-two-round-campaign"
    manifest = load_campaign_manifest(campaign_dir / "campaign-manifest.json")
    round_manifest = load_round_manifest(
        campaign_dir / manifest.round_manifest_paths[0]
    )
    assert round_manifest.stage is CampaignStage.PROPOSE
    assert "hypothesis" not in round_manifest.artifact_paths


def test_campaign_rejects_same_mechanism_after_negative_result(tmp_path: Path) -> None:
    first_mechanism = "noise-conditioned-spline-ensemble"
    designs = _spec().round_designs
    spec = _spec().model_copy(
        update={
            "round_designs": (
                designs[0],
                designs[1].model_copy(
                    update={"candidate_mechanism_families": (first_mechanism,)}
                ),
            )
        }
    )
    adapter = ScriptedCampaignAdapter(force_mechanism=first_mechanism)
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="must change the scientific mechanism"):
        service.run(spec)


def test_campaign_detects_persisted_artifact_tampering(tmp_path: Path) -> None:
    adapter = ScriptedCampaignAdapter()
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )
    result = service.run(_spec())
    campaign_dir = Path(result.campaign_dir)
    manifest = load_campaign_manifest(result.manifest_path)
    first = load_round_manifest(campaign_dir / manifest.round_manifest_paths[0])
    observation_path = campaign_dir / first.artifact_paths["observation"]
    payload = json.loads(observation_path.read_text(encoding="utf-8"))
    payload["summary"] = "tampered after completion"
    observation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CampaignIntegrityError, match="observation file hash mismatch"):
        service.status(campaign_dir)


def test_screen_failure_becomes_negative_round_without_unseen_execution(
    tmp_path: Path,
) -> None:
    adapter = ScriptedCampaignAdapter(screening_passes=(False, True))
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    result = service.run(_spec(min_rounds=1))

    assert result.outcome is CampaignOutcome.CONTRIBUTION_READY
    assert result.completed_round_count == 2
    assert result.experimental_round_count == 1
    assert adapter.calls[("evaluate_unseen", "round-001")] == 0
    assert adapter.calls[("evaluate_unseen", "round-002")] == 1


def test_expired_campaign_stops_before_creating_a_round(tmp_path: Path) -> None:
    adapter = ScriptedCampaignAdapter()
    service = AutonomousResearchCampaign(
        adapter=adapter,
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    result = service.run(_spec(deadline=NOW))

    assert result.outcome is CampaignOutcome.DEADLINE_REACHED
    assert result.stage is CampaignStage.STOP
    assert result.completed_round_count == 0
    assert not adapter.calls
