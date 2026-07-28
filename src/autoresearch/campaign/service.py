"""Persistent autonomous research campaign state machine."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

from autoresearch.campaign.migration import (
    CampaignMigrationCoordinator,
    CampaignMigrationError,
    CampaignMigrationMode,
    resolve_campaign_formal_run_id,
    resolve_campaign_migration_mode,
)
from autoresearch.campaign.models import (
    CampaignManifest,
    CampaignOutcome,
    CampaignResult,
    CampaignRoundDesign,
    CampaignSpec,
    CampaignStage,
    ContributionGateResult,
    DevelopmentResult,
    FailureDiagnosis,
    FreezeInputs,
    FrozenRoundProtocol,
    HypothesisProposal,
    HypothesisScreening,
    Preregistration,
    PreregistrationInputs,
    RoundDecision,
    RoundDecisionKind,
    RoundDevelopmentContext,
    RoundManifest,
    RoundObservation,
    RoundOutcome,
    StageTransition,
    UnseenEvaluation,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    create_vault_layout,
)
from autoresearch.schemas import data_hash, file_hash

_PATH_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_STATE_TRANSITIONS = 64
ModelT = TypeVar("ModelT", bound=BaseModel)


class CampaignIntegrityError(ValueError):
    """Raised when persisted campaign evidence no longer matches its hash chain."""


class CampaignResearchAdapter(Protocol):
    """Scientific implementation boundary used by the deterministic campaign policy."""

    adapter_id: str

    def observe(self, context: RoundDevelopmentContext) -> RoundObservation:
        """Summarize historical evidence without receiving current unseen references."""

    def diagnose(
        self,
        context: RoundDevelopmentContext,
        observation: RoundObservation,
    ) -> FailureDiagnosis:
        """Diagnose the parent result and identify a required mechanism change."""

    def propose(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
    ) -> HypothesisProposal:
        """Propose one falsifiable hypothesis using development-visible context only."""

    def screen(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
        proposal: HypothesisProposal,
    ) -> HypothesisScreening:
        """Run a development-only feasibility and novelty screen."""

    def preregistration_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        screening: HypothesisScreening,
    ) -> PreregistrationInputs:
        """Return result-blind parameter, implementation, and adjudicator identities."""

    def develop(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
    ) -> DevelopmentResult:
        """Execute bounded development selection without current unseen data."""

    def freeze_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        development: DevelopmentResult,
    ) -> FreezeInputs:
        """Return selected code/config identities before unseen execution."""

    def evaluate_unseen(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
    ) -> UnseenEvaluation:
        """Execute the unchanged frozen protocol on current unseen references."""

    def adjudicate(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
        evaluation: UnseenEvaluation,
    ) -> ContributionGateResult:
        """Apply deterministic scientific and contribution checks."""


class AutonomousResearchCampaign:
    """Run or resume a recursively linked, result-blind research campaign."""

    def __init__(
        self,
        *,
        adapter: CampaignResearchAdapter,
        output_root: Path | str = Path("runs/campaigns"),
        vault_root: Path | str = Path("autoresearch-vault"),
        clock: Callable[[], datetime] | None = None,
        migration_mode: CampaignMigrationMode | str | None = None,
        migration_root: Path | str | None = None,
        migration_formal_run_id: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.output_root = Path(output_root).resolve()
        self.vault_root = Path(vault_root).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.migration_mode = resolve_campaign_migration_mode(migration_mode)
        formal_run_id = resolve_campaign_formal_run_id(migration_formal_run_id)
        if self.migration_mode is CampaignMigrationMode.LEGACY:
            if formal_run_id is not None:
                raise CampaignMigrationError(
                    "formal Campaign runs require shadow migration mode"
                )
            self._migration: CampaignMigrationCoordinator | None = None
        else:
            root = (
                Path(migration_root)
                if migration_root is not None
                else self.output_root / ".vnext-migration" / "campaign"
            )
            self._migration = CampaignMigrationCoordinator(
                root=root,
                mode=self.migration_mode,
                formal_run_id=formal_run_id,
            )

    def run(self, spec: CampaignSpec) -> CampaignResult:
        """Start a new campaign or idempotently resume the same campaign ID."""

        self._assert_migration_mode_allowed()
        _validate_path_safe_id(spec.campaign_id, "campaign_id")
        _validate_path_safe_id(spec.project_id, "project_id")
        campaign_dir = self.output_root / spec.campaign_id
        manifest_path = campaign_dir / "campaign-manifest.json"
        if manifest_path.exists():
            return self.resume(campaign_dir)

        try:
            campaign_dir.mkdir(parents=True, exist_ok=False)
            spec_path = _write_json_model(campaign_dir / "campaign-spec.json", spec)
            manifest = CampaignManifest(
                campaign_id=spec.campaign_id,
                project_id=spec.project_id,
                spec_hash=data_hash(spec),
                lineage_hash=_lineage_hash(spec.root_result_hash, ()),
                artifact_paths={"campaign_spec": spec_path.name},
            )
            manifest = _write_campaign_manifest(manifest_path, manifest, self.clock())
            result = self._drive(spec, campaign_dir, manifest)
        except Exception as exc:
            self._record_migration_failure(
                campaign_dir=campaign_dir,
                campaign_id=spec.campaign_id,
                invocation_kind="run",
                error=exc,
            )
            raise
        return self._record_migration_result(
            campaign_dir=campaign_dir,
            result=result,
            invocation_kind="run",
        )

    def resume(self, campaign_dir: Path | str) -> CampaignResult:
        """Resume from the last verified stage without repeating completed stages."""

        self._assert_migration_mode_allowed()
        resolved = Path(campaign_dir).resolve()
        if resolved.is_file():
            resolved = resolved.parent
        spec = CampaignSpec.model_validate_json(
            (resolved / "campaign-spec.json").read_text(encoding="utf-8")
        )
        manifest = load_campaign_manifest(resolved / "campaign-manifest.json")
        if manifest.spec_hash != data_hash(spec):
            raise CampaignIntegrityError("campaign spec hash does not match manifest")
        self._validate_lineage(resolved, spec, manifest)
        if manifest.outcome is not CampaignOutcome.RUNNING:
            result = _campaign_result(resolved, manifest)
        else:
            try:
                result = self._drive(spec, resolved, manifest)
            except Exception as exc:
                self._record_migration_failure(
                    campaign_dir=resolved,
                    campaign_id=spec.campaign_id,
                    invocation_kind="resume",
                    error=exc,
                )
                raise
        return self._record_migration_result(
            campaign_dir=resolved,
            result=result,
            invocation_kind="resume",
        )

    def status(self, campaign_dir: Path | str) -> CampaignResult:
        """Read and validate status without advancing the campaign."""

        resolved = Path(campaign_dir).resolve()
        manifest = load_campaign_manifest(resolved / "campaign-manifest.json")
        spec = CampaignSpec.model_validate_json(
            (resolved / "campaign-spec.json").read_text(encoding="utf-8")
        )
        if manifest.spec_hash != data_hash(spec):
            raise CampaignIntegrityError("campaign spec hash does not match manifest")
        self._validate_lineage(resolved, spec, manifest)
        return _campaign_result(resolved, manifest)

    def _assert_migration_mode_allowed(self) -> None:
        if self._migration is not None:
            self._migration.assert_mode_allowed()

    def _record_migration_result(
        self,
        *,
        campaign_dir: Path,
        result: CampaignResult,
        invocation_kind: Literal["run", "resume"],
    ) -> CampaignResult:
        if self._migration is None:
            return result
        return self._migration.record_result(
            campaign_dir=campaign_dir,
            result=result,
            invocation_kind=invocation_kind,
        )

    def _record_migration_failure(
        self,
        *,
        campaign_dir: Path,
        campaign_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> None:
        if self._migration is None:
            return
        manifest_path = campaign_dir / "campaign-manifest.json"
        if not manifest_path.is_file():
            return
        self._migration.record_failure(
            campaign_dir=campaign_dir,
            campaign_id=campaign_id,
            invocation_kind=invocation_kind,
            error=error,
        )

    def _drive(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        manifest: CampaignManifest,
    ) -> CampaignResult:
        transitions = 0
        while manifest.outcome is CampaignOutcome.RUNNING:
            transitions += 1
            if transitions > _MAX_STATE_TRANSITIONS:
                raise RuntimeError("campaign exceeded bounded state-transition budget")

            if manifest.current_round_id is None:
                if self.clock() >= spec.deadline:
                    manifest = _write_campaign_manifest(
                        campaign_dir / "campaign-manifest.json",
                        manifest.model_copy(
                            update={
                                "stage": CampaignStage.STOP,
                                "outcome": CampaignOutcome.DEADLINE_REACHED,
                            }
                        ),
                        self.clock(),
                    )
                    break
                if len(manifest.round_manifest_paths) >= len(spec.round_designs):
                    manifest = _write_campaign_manifest(
                        campaign_dir / "campaign-manifest.json",
                        manifest.model_copy(
                            update={
                                "stage": CampaignStage.STOP,
                                "outcome": CampaignOutcome.STOPPED,
                            }
                        ),
                        self.clock(),
                    )
                    break
                manifest = self._create_round(spec, campaign_dir, manifest)

            manifest = self._advance_current_round(spec, campaign_dir, manifest)

        return _campaign_result(campaign_dir, manifest)

    def _create_round(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        manifest: CampaignManifest,
    ) -> CampaignManifest:
        round_number = len(manifest.round_manifest_paths) + 1
        design = spec.round_designs[round_number - 1]
        round_id = f"round-{round_number:03d}"
        parent_round: RoundManifest | None = None
        parent_result_hash = spec.root_result_hash
        if manifest.round_manifest_paths:
            parent_round = load_round_manifest(
                campaign_dir / manifest.round_manifest_paths[-1]
            )
            parent_result_hash = self._load_round_decision(
                campaign_dir,
                parent_round,
            ).result_hash

        round_dir = campaign_dir / "rounds" / round_id
        round_dir.mkdir(parents=True, exist_ok=False)
        round_manifest_path = round_dir / "round-manifest.json"
        round_manifest = RoundManifest(
            round_id=round_id,
            campaign_id=spec.campaign_id,
            round_number=round_number,
            track=design.track,
            parent_round_id=parent_round.round_id if parent_round else None,
            parent_round_manifest_hash=parent_round.manifest_hash if parent_round else None,
            parent_result_hash=parent_result_hash,
            design_hash=data_hash(design),
            stage_history=(StageTransition(stage=CampaignStage.OBSERVE),),
        )
        round_manifest = _write_round_manifest(round_manifest_path, round_manifest)
        relative_path = round_manifest_path.relative_to(campaign_dir).as_posix()
        next_paths = (*manifest.round_manifest_paths, relative_path)
        next_hashes = (*manifest.round_manifest_hashes, _required_hash(round_manifest))
        updated = manifest.model_copy(
            update={
                "stage": CampaignStage.OBSERVE,
                "current_round_id": round_id,
                "round_manifest_paths": next_paths,
                "round_manifest_hashes": next_hashes,
                "lineage_hash": _lineage_hash(spec.root_result_hash, next_hashes),
            }
        )
        return _write_campaign_manifest(
            campaign_dir / "campaign-manifest.json",
            updated,
            self.clock(),
        )

    def _advance_current_round(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
    ) -> CampaignManifest:
        round_manifest = self._current_round(campaign_dir, campaign_manifest)
        design = spec.round_designs[round_manifest.round_number - 1]
        if round_manifest.design_hash != data_hash(design):
            raise CampaignIntegrityError("round design hash mismatch")
        context = self._development_context(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            design,
        )

        if round_manifest.stage is CampaignStage.OBSERVE:
            observation = self.adapter.observe(context)
            _require_round_parent(
                round_manifest,
                observation.round_id,
                observation.parent_result_hash,
            )
            observation = _stamp_model(observation, "observation_hash")
            return self._record_and_transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "observation",
                observation,
                CampaignStage.DIAGNOSE,
            )

        if round_manifest.stage is CampaignStage.DIAGNOSE:
            observation = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "observation",
                RoundObservation,
                "observation_hash",
            )
            diagnosis = self.adapter.diagnose(context, observation)
            _require_round_parent(
                round_manifest,
                diagnosis.round_id,
                diagnosis.parent_result_hash,
            )
            diagnosis = _stamp_model(diagnosis, "diagnosis_hash")
            return self._record_and_transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "failure_diagnosis",
                diagnosis,
                CampaignStage.PROPOSE,
            )

        if round_manifest.stage is CampaignStage.PROPOSE:
            diagnosis = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "failure_diagnosis",
                FailureDiagnosis,
                "diagnosis_hash",
            )
            proposal = self.adapter.propose(context, diagnosis)
            self._validate_proposal(
                campaign_dir,
                round_manifest,
                design,
                proposal,
            )
            proposal = _stamp_model(proposal, "proposal_hash")
            return self._record_and_transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "hypothesis",
                proposal,
                CampaignStage.SCREEN,
            )

        if round_manifest.stage is CampaignStage.SCREEN:
            diagnosis = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "failure_diagnosis",
                FailureDiagnosis,
                "diagnosis_hash",
            )
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            screening = self.adapter.screen(context, diagnosis, proposal)
            if (
                screening.round_id != round_manifest.round_id
                or screening.hypothesis_id != proposal.hypothesis_id
            ):
                raise ValueError("screening does not belong to current hypothesis")
            screening = _stamp_model(screening, "screening_hash")
            campaign_manifest, round_manifest = self._record_artifact(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "screening",
                screening,
            )
            if not screening.passed:
                return self._close_pre_unseen_failure(
                    spec,
                    campaign_dir,
                    campaign_manifest,
                    round_manifest,
                    result_hash=_required_model_hash(screening, "screening_hash"),
                    failure="hypothesis failed development-only screening",
                    check_name="development_screen_passed",
                )
            return self._transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                CampaignStage.PREREGISTER,
            )

        if round_manifest.stage is CampaignStage.PREREGISTER:
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            screening = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "screening",
                HypothesisScreening,
                "screening_hash",
            )
            inputs = self.adapter.preregistration_inputs(context, proposal, screening)
            preregistration = Preregistration(
                round_id=round_manifest.round_id,
                hypothesis_id=proposal.hypothesis_id,
                proposal_hash=_required_model_hash(proposal, "proposal_hash"),
                track=design.track,
                development_data_refs=design.development_data_refs,
                unseen_data_refs=design.unseen_data_refs,
                seeds=design.seeds,
                primary_metric=design.primary_metric,
                acceptance_criteria=design.acceptance_criteria,
                parameter_space=inputs.parameter_space,
                parameter_space_hash=data_hash(inputs.parameter_space),
                stop_rules=inputs.stop_rules,
                implementation_family_hashes=inputs.implementation_family_hashes,
                adjudicator_hash=inputs.adjudicator_hash,
                frozen_at=self.clock(),
            )
            preregistration = _stamp_model(preregistration, "preregistration_hash")
            return self._record_and_transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "preregistration",
                preregistration,
                CampaignStage.DEVELOP,
            )

        if round_manifest.stage is CampaignStage.DEVELOP:
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            preregistration = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "preregistration",
                Preregistration,
                "preregistration_hash",
            )
            development = self.adapter.develop(context, proposal, preregistration)
            if (
                development.round_id != round_manifest.round_id
                or development.hypothesis_id != proposal.hypothesis_id
                or development.preregistration_hash
                != _required_model_hash(preregistration, "preregistration_hash")
            ):
                raise ValueError("development result does not match frozen causal chain")
            development = _stamp_model(development, "result_hash")
            campaign_manifest, round_manifest = self._record_artifact(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "development_result",
                development,
            )
            if not development.passed:
                return self._close_pre_unseen_failure(
                    spec,
                    campaign_dir,
                    campaign_manifest,
                    round_manifest,
                    result_hash=_required_model_hash(development, "result_hash"),
                    failure="candidate failed preregistered development gate",
                    check_name="development_gate_passed",
                )
            return self._transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                CampaignStage.FREEZE,
            )

        if round_manifest.stage is CampaignStage.FREEZE:
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            preregistration = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "preregistration",
                Preregistration,
                "preregistration_hash",
            )
            development = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "development_result",
                DevelopmentResult,
                "result_hash",
            )
            freeze_inputs = self.adapter.freeze_inputs(
                context,
                proposal,
                preregistration,
                development,
            )
            if freeze_inputs.adjudicator_hash != preregistration.adjudicator_hash:
                raise ValueError("freeze attempted to change the preregistered adjudicator")
            if freeze_inputs.selected_config_hash != data_hash(
                development.selected_configuration
            ):
                raise ValueError("freeze config hash does not match development selection")
            frozen = FrozenRoundProtocol(
                round_id=round_manifest.round_id,
                hypothesis_id=proposal.hypothesis_id,
                preregistration_hash=_required_model_hash(
                    preregistration,
                    "preregistration_hash",
                ),
                development_result_hash=_required_model_hash(development, "result_hash"),
                selected_config_hash=freeze_inputs.selected_config_hash,
                code_hashes=freeze_inputs.code_hashes,
                adjudicator_hash=freeze_inputs.adjudicator_hash,
                unseen_data_refs=preregistration.unseen_data_refs,
                frozen_at=self.clock(),
            )
            frozen = _stamp_model(frozen, "frozen_hash")
            return self._record_and_transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "frozen_protocol",
                frozen,
                CampaignStage.UNSEEN_EVALUATE,
            )

        if round_manifest.stage is CampaignStage.UNSEEN_EVALUATE:
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            preregistration = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "preregistration",
                Preregistration,
                "preregistration_hash",
            )
            frozen = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "frozen_protocol",
                FrozenRoundProtocol,
                "frozen_hash",
            )
            evaluation = self.adapter.evaluate_unseen(proposal, preregistration, frozen)
            if (
                evaluation.round_id != round_manifest.round_id
                or evaluation.hypothesis_id != proposal.hypothesis_id
                or evaluation.frozen_hash != _required_model_hash(frozen, "frozen_hash")
            ):
                raise ValueError("unseen evaluation does not match frozen protocol")
            evaluation = _stamp_model(evaluation, "result_hash")
            updated_round = round_manifest.model_copy(
                update={"human_intervention_count": evaluation.human_intervention_count}
            )
            campaign_manifest, updated_round = self._record_artifact(
                spec,
                campaign_dir,
                campaign_manifest,
                updated_round,
                "unseen_evaluation",
                evaluation,
            )
            return self._transition(
                spec,
                campaign_dir,
                campaign_manifest,
                updated_round,
                CampaignStage.ADJUDICATE,
            )

        if round_manifest.stage is CampaignStage.ADJUDICATE:
            proposal = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "hypothesis",
                HypothesisProposal,
                "proposal_hash",
            )
            preregistration = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "preregistration",
                Preregistration,
                "preregistration_hash",
            )
            frozen = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "frozen_protocol",
                FrozenRoundProtocol,
                "frozen_hash",
            )
            evaluation = self._load_round_artifact(
                campaign_dir,
                round_manifest,
                "unseen_evaluation",
                UnseenEvaluation,
                "result_hash",
            )
            gate = self.adapter.adjudicate(
                proposal,
                preregistration,
                frozen,
                evaluation,
            )
            evaluation_hash = _required_model_hash(evaluation, "result_hash")
            if (
                gate.round_id != round_manifest.round_id
                or gate.track is not round_manifest.track
                or gate.evaluated_result_hash != evaluation_hash
            ):
                raise ValueError("contribution gate does not match unseen result")
            if gate.passed and evaluation.outcome is not RoundOutcome.POSITIVE_RESULT:
                raise ValueError("non-positive unseen outcome cannot pass contribution gate")
            if gate.passed and (
                not evaluation.mandatory_evidence_complete
                or evaluation.human_intervention_count != 0
            ):
                raise ValueError(
                    "incomplete or human-directed unseen evidence cannot pass contribution gate"
                )
            gate = _stamp_model(gate, "gate_hash")
            campaign_manifest, round_manifest = self._record_artifact(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "contribution_gate",
                gate,
            )
            decision = self._policy_decision(
                spec,
                campaign_manifest,
                round_manifest,
                evaluation.outcome,
                evaluation_hash,
                gate,
                experimental_round=True,
            )
            decision = _stamp_model(decision, "decision_hash")
            campaign_manifest, round_manifest = self._record_artifact(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                "round_decision",
                decision,
            )
            return self._transition(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
                CampaignStage.REPORT,
            )

        if round_manifest.stage is CampaignStage.REPORT:
            return self._finalize_round(
                spec,
                campaign_dir,
                campaign_manifest,
                round_manifest,
            )

        raise CampaignIntegrityError(
            f"current round is at unsupported stage {round_manifest.stage.value}"
        )

    def _close_pre_unseen_failure(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        *,
        result_hash: str,
        failure: str,
        check_name: str,
    ) -> CampaignManifest:
        gate = ContributionGateResult(
            round_id=round_manifest.round_id,
            track=round_manifest.track,
            evaluated_result_hash=result_hash,
            passed=False,
            checks={check_name: False},
            failures=(failure,),
        )
        gate = _stamp_model(gate, "gate_hash")
        campaign_manifest, round_manifest = self._record_artifact(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            "contribution_gate",
            gate,
        )
        decision = self._policy_decision(
            spec,
            campaign_manifest,
            round_manifest,
            RoundOutcome.NEGATIVE_RESULT,
            result_hash,
            gate,
            experimental_round=False,
        )
        decision = _stamp_model(decision, "decision_hash")
        campaign_manifest, round_manifest = self._record_artifact(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            "round_decision",
            decision,
        )
        return self._transition(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            CampaignStage.REPORT,
        )

    def _policy_decision(
        self,
        spec: CampaignSpec,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        outcome: RoundOutcome,
        result_hash: str,
        gate: ContributionGateResult,
        *,
        experimental_round: bool,
    ) -> RoundDecision:
        completed_after = campaign_manifest.experimental_round_count + int(
            experimental_round
        )
        another_design_exists = round_manifest.round_number < len(spec.round_designs)
        if gate.passed and completed_after >= spec.min_experimental_rounds:
            return RoundDecision(
                round_id=round_manifest.round_id,
                decision=RoundDecisionKind.PAPER_BUILD,
                outcome=outcome,
                result_hash=result_hash,
                contribution_gate_hash=_required_model_hash(gate, "gate_hash"),
                reason=(
                    "deterministic contribution gate passed after the required number "
                    "of new experimental rounds"
                ),
            )
        if another_design_exists:
            trigger = (
                "confirmation round required before paper build"
                if gate.passed
                else "; ".join(gate.failures)
            )
            return RoundDecision(
                round_id=round_manifest.round_id,
                decision=RoundDecisionKind.NEXT_ROUND,
                outcome=outcome,
                result_hash=result_hash,
                contribution_gate_hash=_required_model_hash(gate, "gate_hash"),
                reason=trigger,
                next_round_trigger=trigger,
            )
        return RoundDecision(
            round_id=round_manifest.round_id,
            decision=RoundDecisionKind.STOP,
            outcome=outcome,
            result_hash=result_hash,
            contribution_gate_hash=_required_model_hash(gate, "gate_hash"),
            reason=(
                "no unused result-blind round design remains; gates are not lowered "
                "to manufacture a contribution"
            ),
        )

    def _finalize_round(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
    ) -> CampaignManifest:
        from autoresearch.campaign.reporting import CampaignRoundReporter

        decision = self._load_round_decision(campaign_dir, round_manifest)
        round_manifest = CampaignRoundReporter().write_round_reports(
            campaign_dir=campaign_dir,
            spec=spec,
            round_manifest=round_manifest,
            decision=decision,
        )
        round_manifest = self._write_vault_round_note(
            spec,
            round_manifest,
            decision,
        )
        finalized_round = round_manifest.model_copy(
            update={
                "outcome": decision.outcome,
                "completed_at": self.clock(),
            }
        )
        finalized_round = _write_round_manifest(
            campaign_dir / self._round_manifest_relative_path(campaign_manifest),
            finalized_round,
        )
        campaign_manifest = self._replace_round_hash(
            spec,
            campaign_dir,
            campaign_manifest,
            finalized_round,
        )

        experimental_increment = int("unseen_evaluation" in finalized_round.artifact_paths)
        updates: dict[str, object] = {
            "completed_round_count": campaign_manifest.completed_round_count + 1,
            "experimental_round_count": (
                campaign_manifest.experimental_round_count + experimental_increment
            ),
            "human_intervention_count": (
                campaign_manifest.human_intervention_count
                + finalized_round.human_intervention_count
            ),
            "current_round_id": None,
        }
        if decision.decision is RoundDecisionKind.NEXT_ROUND:
            updates.update(
                {
                    "stage": CampaignStage.NEXT_ROUND,
                    "outcome": CampaignOutcome.RUNNING,
                }
            )
        elif decision.decision is RoundDecisionKind.PAPER_BUILD:
            updates.update(
                {
                    "stage": CampaignStage.PAPER_BUILD,
                    "outcome": CampaignOutcome.CONTRIBUTION_READY,
                }
            )
        else:
            updates.update(
                {
                    "stage": CampaignStage.STOP,
                    "outcome": CampaignOutcome.STOPPED,
                }
            )
        return _write_campaign_manifest(
            campaign_dir / "campaign-manifest.json",
            campaign_manifest.model_copy(update=updates),
            self.clock(),
        )

    def _record_and_transition(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        artifact_name: str,
        model: BaseModel,
        next_stage: CampaignStage,
    ) -> CampaignManifest:
        campaign_manifest, round_manifest = self._record_artifact(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            artifact_name,
            model,
        )
        return self._transition(
            spec,
            campaign_dir,
            campaign_manifest,
            round_manifest,
            next_stage,
        )

    def _record_artifact(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        artifact_name: str,
        model: BaseModel,
    ) -> tuple[CampaignManifest, RoundManifest]:
        relative_path = (
            Path("rounds") / round_manifest.round_id / f"{artifact_name}.json"
        )
        artifact_path = _write_json_model(campaign_dir / relative_path, model)
        paths = dict(round_manifest.artifact_paths)
        hashes = dict(round_manifest.artifact_hashes)
        paths[artifact_name] = relative_path.as_posix()
        hashes[artifact_name] = file_hash(artifact_path)
        updated_round = round_manifest.model_copy(
            update={"artifact_paths": paths, "artifact_hashes": hashes}
        )
        updated_round = _write_round_manifest(
            campaign_dir / self._round_manifest_relative_path(campaign_manifest),
            updated_round,
        )
        updated_campaign = self._replace_round_hash(
            spec,
            campaign_dir,
            campaign_manifest,
            updated_round,
        )
        return updated_campaign, updated_round

    def _transition(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        next_stage: CampaignStage,
    ) -> CampaignManifest:
        updated_round = round_manifest.model_copy(
            update={
                "stage": next_stage,
                "stage_history": (
                    *round_manifest.stage_history,
                    StageTransition(stage=next_stage, entered_at=self.clock()),
                ),
            }
        )
        updated_round = _write_round_manifest(
            campaign_dir / self._round_manifest_relative_path(campaign_manifest),
            updated_round,
        )
        updated_campaign = self._replace_round_hash(
            spec,
            campaign_dir,
            campaign_manifest,
            updated_round,
        )
        updated_campaign = updated_campaign.model_copy(update={"stage": next_stage})
        return _write_campaign_manifest(
            campaign_dir / "campaign-manifest.json",
            updated_campaign,
            self.clock(),
        )

    def _replace_round_hash(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
    ) -> CampaignManifest:
        paths = list(campaign_manifest.round_manifest_paths)
        hashes = list(campaign_manifest.round_manifest_hashes)
        relative_path = (
            Path("rounds") / round_manifest.round_id / "round-manifest.json"
        ).as_posix()
        try:
            index = paths.index(relative_path)
        except ValueError as exc:
            raise CampaignIntegrityError("current round is absent from campaign lineage") from exc
        hashes[index] = _required_hash(round_manifest)
        updated = campaign_manifest.model_copy(
            update={
                "round_manifest_hashes": tuple(hashes),
                "lineage_hash": _lineage_hash(spec.root_result_hash, tuple(hashes)),
            }
        )
        return _write_campaign_manifest(
            campaign_dir / "campaign-manifest.json",
            updated,
            self.clock(),
        )

    def _development_context(
        self,
        spec: CampaignSpec,
        campaign_dir: Path,
        campaign_manifest: CampaignManifest,
        round_manifest: RoundManifest,
        design: CampaignRoundDesign,
    ) -> RoundDevelopmentContext:
        historical = list(spec.root_evidence_refs)
        for relative_path in campaign_manifest.round_manifest_paths[
            : round_manifest.round_number - 1
        ]:
            prior = load_round_manifest(campaign_dir / relative_path)
            historical.extend(prior.artifact_paths.values())
        return RoundDevelopmentContext(
            campaign_id=spec.campaign_id,
            round_id=round_manifest.round_id,
            round_number=round_manifest.round_number,
            track=design.track,
            parent_result_hash=round_manifest.parent_result_hash,
            historical_evidence_refs=tuple(dict.fromkeys(historical)),
            development_data_refs=design.development_data_refs,
            seeds=design.seeds,
            candidate_mechanism_families=design.candidate_mechanism_families,
            primary_metric=design.primary_metric,
            deadline=spec.deadline,
        )

    def _validate_proposal(
        self,
        campaign_dir: Path,
        round_manifest: RoundManifest,
        design: CampaignRoundDesign,
        proposal: HypothesisProposal,
    ) -> None:
        _require_round_parent(
            round_manifest,
            proposal.round_id,
            proposal.parent_result_hash,
        )
        if proposal.mechanism_family not in design.candidate_mechanism_families:
            raise ValueError("proposal mechanism family is outside the result-blind design")
        serialized = json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False)
        leaked = [ref for ref in design.unseen_data_refs if ref and ref in serialized]
        if leaked:
            raise ValueError("proposal contains current-round unseen data references")
        if round_manifest.parent_round_id is None:
            return
        parent_path = (
            campaign_dir
            / "rounds"
            / round_manifest.parent_round_id
            / "round-manifest.json"
        )
        parent = load_round_manifest(parent_path)
        if parent.outcome is not RoundOutcome.NEGATIVE_RESULT:
            return
        previous = self._load_round_artifact(
            campaign_dir,
            parent,
            "hypothesis",
            HypothesisProposal,
            "proposal_hash",
        )
        if previous.mechanism_family == proposal.mechanism_family:
            raise ValueError(
                "negative-result child round must change the scientific mechanism family"
            )

    def _write_vault_round_note(
        self,
        spec: CampaignSpec,
        round_manifest: RoundManifest,
        decision: RoundDecision,
    ) -> RoundManifest:
        layout = create_vault_layout(self.vault_root, spec.project_id)
        parent_link = (
            f"[[{spec.campaign_id}-{round_manifest.parent_round_id}]]"
            if round_manifest.parent_round_id
            else "None (campaign root)"
        )
        body = "\n".join(
            [
                f"# Campaign {spec.campaign_id} / {round_manifest.round_id}",
                "",
                f"- Track: `{round_manifest.track.value}`",
                f"- Parent round: {parent_link}",
                f"- Parent result hash: `{round_manifest.parent_result_hash or 'none'}`",
                f"- Outcome: `{decision.outcome.value}`",
                f"- Decision: `{decision.decision.value}`",
                f"- Decision hash: `{_required_model_hash(decision, 'decision_hash')}`",
                f"- Human interventions: {round_manifest.human_intervention_count}",
                "",
                "## Runtime artifacts",
                "",
                *[
                    f"- `{name}`: `{path}`"
                    for name, path in sorted(round_manifest.artifact_paths.items())
                ],
                "",
                "This note is runtime-owned evidence. It does not authorize external submission.",
            ]
        )
        entry_type = (
            KnowledgeEntryType.FAILURE_CASE
            if decision.outcome is RoundOutcome.NEGATIVE_RESULT
            else KnowledgeEntryType.EXPERIMENT_RECORD
        )
        relative_path = (
            Path("projects")
            / spec.project_id
            / "experiments"
            / f"{spec.campaign_id}-{round_manifest.round_id}.md"
        )
        entry = KnowledgeEntry(
            entry_id=f"{spec.campaign_id}-{round_manifest.round_id}",
            entry_type=entry_type,
            zone=KnowledgeZone.PROJECT,
            title=f"{spec.campaign_id} {round_manifest.round_id}",
            project_id=spec.project_id,
            tags=["autonomous-campaign", round_manifest.track.value, decision.outcome.value],
            keywords=["autonomous research campaign", "research iteration"],
            source_refs=list(round_manifest.artifact_paths.values()),
            links=(
                [f"{spec.campaign_id}-{round_manifest.parent_round_id}"]
                if round_manifest.parent_round_id
                else []
            ),
            related_run_ids=[spec.campaign_id],
            body=body,
        )
        note_path = layout.root / relative_path
        _write_text_atomic(note_path, entry.to_markdown())
        _write_campaign_project_index(layout.project, spec.campaign_id)
        return round_manifest.model_copy(
            update={"vault_note_path": note_path.resolve().as_posix()}
        )

    def _load_round_artifact(
        self,
        campaign_dir: Path,
        round_manifest: RoundManifest,
        artifact_name: str,
        model_type: type[ModelT],
        hash_field: str,
    ) -> ModelT:
        try:
            raw_path = round_manifest.artifact_paths[artifact_name]
            expected_file_hash = round_manifest.artifact_hashes[artifact_name]
        except KeyError as exc:
            raise CampaignIntegrityError(
                f"round artifact {artifact_name} is missing from manifest"
            ) from exc
        path = _resolve_artifact_path(campaign_dir, raw_path)
        if not path.is_file() or file_hash(path) != expected_file_hash:
            raise CampaignIntegrityError(f"round artifact {artifact_name} file hash mismatch")
        return _load_stamped_model(path, model_type, hash_field)

    def _load_round_decision(
        self,
        campaign_dir: Path,
        round_manifest: RoundManifest,
    ) -> RoundDecision:
        return self._load_round_artifact(
            campaign_dir,
            round_manifest,
            "round_decision",
            RoundDecision,
            "decision_hash",
        )

    def _current_round(
        self,
        campaign_dir: Path,
        manifest: CampaignManifest,
    ) -> RoundManifest:
        if manifest.current_round_id is None:
            raise CampaignIntegrityError("campaign has no current round")
        expected = (
            Path("rounds") / manifest.current_round_id / "round-manifest.json"
        ).as_posix()
        if expected not in manifest.round_manifest_paths:
            raise CampaignIntegrityError("current round path is absent from campaign manifest")
        return load_round_manifest(campaign_dir / expected)

    def _round_manifest_relative_path(self, manifest: CampaignManifest) -> str:
        if manifest.current_round_id is None:
            raise CampaignIntegrityError("campaign has no current round")
        return (
            Path("rounds") / manifest.current_round_id / "round-manifest.json"
        ).as_posix()

    def _validate_lineage(
        self,
        campaign_dir: Path,
        spec: CampaignSpec,
        manifest: CampaignManifest,
    ) -> None:
        validated_spec, validated_manifest, _ = validate_campaign_directory(campaign_dir)
        if validated_spec != spec or validated_manifest != manifest:
            raise CampaignIntegrityError("validated campaign differs from loaded contracts")

def load_campaign_manifest(path: Path | str) -> CampaignManifest:
    """Load and verify a top-level campaign manifest."""

    return _load_stamped_model(
        Path(path),
        CampaignManifest,
        "manifest_hash",
    )


def load_round_manifest(path: Path | str) -> RoundManifest:
    """Load and verify one round manifest."""

    return _load_stamped_model(
        Path(path),
        RoundManifest,
        "manifest_hash",
    )


def validate_campaign_directory(
    campaign_dir: Path | str,
) -> tuple[CampaignSpec, CampaignManifest, tuple[RoundManifest, ...]]:
    """Validate the full campaign lineage and every managed artifact."""

    resolved = Path(campaign_dir).resolve()
    spec = CampaignSpec.model_validate_json(
        (resolved / "campaign-spec.json").read_text(encoding="utf-8")
    )
    manifest = load_campaign_manifest(resolved / "campaign-manifest.json")
    if manifest.spec_hash != data_hash(spec):
        raise CampaignIntegrityError("campaign spec hash does not match manifest")
    if manifest.campaign_id != spec.campaign_id:
        raise CampaignIntegrityError("campaign manifest does not match campaign spec")
    if len(manifest.round_manifest_paths) > len(spec.round_designs):
        raise CampaignIntegrityError("campaign has more rounds than frozen designs")

    actual_hashes: list[str] = []
    rounds: list[RoundManifest] = []
    previous: RoundManifest | None = None
    previous_decision: RoundDecision | None = None
    for index, (relative_path, expected_hash) in enumerate(
        zip(
            manifest.round_manifest_paths,
            manifest.round_manifest_hashes,
            strict=True,
        )
    ):
        round_manifest = load_round_manifest(resolved / relative_path)
        if round_manifest.campaign_id != manifest.campaign_id:
            raise CampaignIntegrityError("round belongs to another campaign")
        if round_manifest.manifest_hash != expected_hash:
            raise CampaignIntegrityError("campaign records a stale round manifest hash")
        if round_manifest.round_number != index + 1:
            raise CampaignIntegrityError("round number does not match lineage position")
        if round_manifest.design_hash != data_hash(spec.round_designs[index]):
            raise CampaignIntegrityError("round design hash mismatch")
        if previous is None:
            if round_manifest.parent_round_id is not None:
                raise CampaignIntegrityError("first round unexpectedly has a parent round")
            if round_manifest.parent_result_hash != spec.root_result_hash:
                raise CampaignIntegrityError("first round parent result does not match spec root")
        else:
            if (
                round_manifest.parent_round_id != previous.round_id
                or round_manifest.parent_round_manifest_hash != previous.manifest_hash
            ):
                raise CampaignIntegrityError("round parent manifest link is invalid")
            if (
                previous_decision is None
                or round_manifest.parent_result_hash != previous_decision.result_hash
            ):
                raise CampaignIntegrityError("round parent result link is invalid")

        if round_manifest.artifact_paths.keys() != round_manifest.artifact_hashes.keys():
            raise CampaignIntegrityError("round artifact paths and hashes do not align")
        for name, raw_path in round_manifest.artifact_paths.items():
            path = _resolve_artifact_path(resolved, raw_path)
            if not path.is_file() or file_hash(path) != round_manifest.artifact_hashes[name]:
                raise CampaignIntegrityError(f"round artifact {name} file hash mismatch")

        decision_path = round_manifest.artifact_paths.get("round_decision")
        previous_decision = (
            _load_stamped_model(
                _resolve_artifact_path(resolved, decision_path),
                RoundDecision,
                "decision_hash",
            )
            if decision_path is not None
            else None
        )
        actual_hashes.append(expected_hash)
        rounds.append(round_manifest)
        previous = round_manifest

    expected_lineage = _lineage_hash(spec.root_result_hash, tuple(actual_hashes))
    if manifest.lineage_hash != expected_lineage:
        raise CampaignIntegrityError("campaign lineage hash mismatch")
    return spec, manifest, tuple(rounds)


def _write_campaign_manifest(
    path: Path,
    manifest: CampaignManifest,
    now: datetime,
) -> CampaignManifest:
    updated = manifest.model_copy(update={"updated_at": now, "manifest_hash": None})
    stamped = _stamp_model(updated, "manifest_hash")
    _write_json_model(path, stamped)
    return stamped


def _write_round_manifest(path: Path, manifest: RoundManifest) -> RoundManifest:
    stamped = _stamp_model(
        manifest.model_copy(update={"manifest_hash": None}),
        "manifest_hash",
    )
    _write_json_model(path, stamped)
    return stamped


def _write_json_model(path: Path, model: BaseModel | dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _write_text_atomic(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _write_campaign_project_index(project_root: Path, campaign_id: str) -> None:
    experiment_dir = project_root / "experiments"
    notes = sorted(experiment_dir.glob(f"{campaign_id}-round-*.md"))
    start_marker = f"<!-- AUTORESEARCH-CAMPAIGN:{campaign_id}:START -->"
    end_marker = f"<!-- AUTORESEARCH-CAMPAIGN:{campaign_id}:END -->"
    block = "\n".join(
        [
            start_marker,
            f"## Campaign {campaign_id}",
            "",
            *[f"- [[{path.stem}]]" for path in notes],
            "",
            "External submission remains human-gated.",
            end_marker,
        ]
    )
    index_path = project_root / "index.md"
    existing = (
        index_path.read_text(encoding="utf-8")
        if index_path.is_file()
        else "\n".join(
            [
                f"# {campaign_id}",
                "",
                "Project knowledge index for AI-Researcher.",
            ]
        )
    )
    if start_marker in existing and end_marker in existing:
        prefix, remainder = existing.split(start_marker, maxsplit=1)
        _, suffix = remainder.split(end_marker, maxsplit=1)
        content = f"{prefix.rstrip()}\n\n{block}{suffix}"
    else:
        content = "\n".join(
            [
                existing.rstrip(),
                "",
                block,
            ]
        )
    _write_text_atomic(index_path, content)


def _stamp_model(model: ModelT, hash_field: str) -> ModelT:
    payload = model.model_dump(mode="json", exclude={hash_field})
    digest = data_hash(payload)
    return model.model_copy(update={hash_field: digest})


def _load_stamped_model(
    path: Path,
    model_type: type[ModelT],
    hash_field: str,
) -> ModelT:
    try:
        model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CampaignIntegrityError(f"missing campaign artifact: {path}") from exc
    stored = getattr(model, hash_field)
    expected = data_hash(model.model_dump(mode="json", exclude={hash_field}))
    if stored != expected:
        raise CampaignIntegrityError(f"{path.name} {hash_field} mismatch")
    return model


def _required_model_hash(model: BaseModel, hash_field: str) -> str:
    value = getattr(model, hash_field)
    if not isinstance(value, str):
        raise CampaignIntegrityError(f"{model.__class__.__name__} is missing {hash_field}")
    return value


def _required_hash(manifest: RoundManifest) -> str:
    if manifest.manifest_hash is None:
        raise CampaignIntegrityError("round manifest has no content hash")
    return manifest.manifest_hash


def _lineage_hash(root_result_hash: str | None, round_hashes: tuple[str, ...]) -> str:
    return data_hash(
        {
            "root_result_hash": root_result_hash,
            "round_manifest_hashes": round_hashes,
        }
    )


def _resolve_artifact_path(campaign_dir: Path, raw_path: str) -> Path:
    root = campaign_dir.resolve()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CampaignIntegrityError(
            "managed campaign artifact escapes the campaign directory"
        ) from exc
    return candidate


def _require_round_parent(
    manifest: RoundManifest,
    round_id: str,
    parent_result_hash: str | None,
) -> None:
    if round_id != manifest.round_id:
        raise ValueError("artifact does not belong to current round")
    if parent_result_hash != manifest.parent_result_hash:
        raise ValueError("artifact parent result hash does not match round lineage")


def _validate_path_safe_id(value: str, field_name: str) -> None:
    if not _PATH_SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{field_name} must be a path-safe identifier")


def _campaign_result(campaign_dir: Path, manifest: CampaignManifest) -> CampaignResult:
    return CampaignResult(
        campaign_dir=campaign_dir.as_posix(),
        manifest_path=(campaign_dir / "campaign-manifest.json").as_posix(),
        outcome=manifest.outcome,
        stage=manifest.stage,
        completed_round_count=manifest.completed_round_count,
        experimental_round_count=manifest.experimental_round_count,
        human_intervention_count=manifest.human_intervention_count,
        current_round_id=manifest.current_round_id,
    )
