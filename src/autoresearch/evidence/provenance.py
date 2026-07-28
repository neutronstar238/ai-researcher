"""Evidence v2 projections and campaign provenance adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel

from autoresearch.campaign.models import (
    ContributionGateResult,
    FrozenRoundProtocol,
    HypothesisProposal,
    Preregistration,
    RoundDecision,
    RoundManifest,
    UnseenEvaluation,
)
from autoresearch.campaign.service import (
    CampaignIntegrityError,
    validate_campaign_directory,
)
from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    Counterevidence,
    Decision,
    Derivation,
    Entity,
    EntityKind,
    Evidence,
    EvidenceDirection,
    Generation,
    InvocationStatus,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBundle,
    SourceSnapshot,
    ToolInvocation,
    Usage,
    Validation,
    VersionedRecord,
)
from autoresearch.kernel.contracts import KernelContract, StableId
from autoresearch.schemas import ValidationStatus, data_hash

from .graph import (
    ClaimNode,
    EvidenceArtifact,
    EvidenceGraph,
    EvidenceNode,
    SourceNode,
)

CampaignModel = TypeVar("CampaignModel", bound=BaseModel)
ProvenanceRecord = TypeVar("ProvenanceRecord", bound=VersionedRecord)


class CampaignRoundProvenance(KernelContract):
    """A real campaign round projected into evidence v2."""

    bundle: ProvenanceBundle
    core_claim_id: StableId
    hypothesis_claim_id: StableId
    approved_record_ids: list[StableId]


def project_evidence_v1(bundle: ProvenanceBundle) -> EvidenceGraph:
    """Project current evidence-v2 records into the unchanged v1 graph."""

    bundle.verify_integrity()
    graph = EvidenceGraph()
    current_claims = _current_records(bundle.claims, "claim_id")
    current_evidence = cast(
        list[Evidence | Counterevidence],
        _current_records(
            [*bundle.evidence, *bundle.counterevidence],
            "evidence_id",
        ),
    )
    current_claim_ids = {claim.claim_id for claim in current_claims}
    snapshots = {snapshot.snapshot_id: snapshot for snapshot in bundle.source_snapshots}
    entities = {entity.entity_id: entity for entity in bundle.entities}

    for claim in current_claims:
        graph.add_claim(
            ClaimNode(
                id=claim.claim_id,
                statement=claim.statement,
                project_id=claim.project_id,
            )
        )

    for item in current_evidence:
        if item.claim_id not in current_claim_ids or item.invalidated_at is not None:
            continue
        snapshot = snapshots[item.source_snapshot_id]
        source = entities[item.source_entity_id]
        artifact = entities[item.artifact_entity_id]
        if source.entity_id not in graph.sources:
            graph.add_source(
                SourceNode(
                    id=source.entity_id,
                    title=source.label,
                    uri=snapshot.source_uri,
                    source_type=source.kind.value,
                )
            )
        if artifact.entity_id not in graph.artifacts:
            graph.add_artifact(
                EvidenceArtifact(
                    id=artifact.entity_id,
                    source_id=source.entity_id,
                    uri=artifact.source_uri or f"urn:sha256:{artifact.content_digest}",
                    artifact_type=artifact.kind.value,
                    validation_status=bundle.latest_validation(item.evidence_id).status,
                )
            )
        graph.link_evidence(
            EvidenceNode(
                id=item.evidence_id,
                claim_id=item.claim_id,
                source_id=source.entity_id,
                artifact_id=artifact.entity_id,
                summary=item.summary,
                supports_claim=item.direction is EvidenceDirection.SUPPORTS,
            )
        )
    return graph


def build_campaign_round_provenance(
    campaign_dir: Path | str,
    round_id: str,
) -> CampaignRoundProvenance:
    """Build a fail-closed provenance bundle from one validated campaign round."""

    root = Path(campaign_dir).resolve()
    spec, campaign_manifest, rounds = validate_campaign_directory(root)
    round_manifest = next(
        (candidate for candidate in rounds if candidate.round_id == round_id),
        None,
    )
    if round_manifest is None:
        raise CampaignIntegrityError(f"campaign has no round {round_id}")

    hypothesis = _load_round_artifact(
        root,
        round_manifest,
        "hypothesis",
        HypothesisProposal,
        "proposal_hash",
    )
    preregistration = _load_round_artifact(
        root,
        round_manifest,
        "preregistration",
        Preregistration,
        "preregistration_hash",
    )
    frozen = _load_round_artifact(
        root,
        round_manifest,
        "frozen_protocol",
        FrozenRoundProtocol,
        "frozen_hash",
    )
    unseen = _load_round_artifact(
        root,
        round_manifest,
        "unseen_evaluation",
        UnseenEvaluation,
        "result_hash",
    )
    gate = _load_round_artifact(
        root,
        round_manifest,
        "contribution_gate",
        ContributionGateResult,
        "gate_hash",
    )
    round_decision = _load_round_artifact(
        root,
        round_manifest,
        "round_decision",
        RoundDecision,
        "decision_hash",
    )
    _require_round_alignment(
        round_manifest,
        hypothesis,
        preregistration,
        frozen,
        unseen,
        gate,
        round_decision,
    )

    created_at = _as_utc(spec.created_at)
    proposal_start = _stage_time(round_manifest, "propose")
    proposal_end = _stage_time(round_manifest, "screen")
    evaluation_start = _as_utc(unseen.started_at)
    evaluation_end = _as_utc(unseen.completed_at)
    adjudication_start = max(
        _stage_time(round_manifest, "adjudicate"),
        evaluation_end,
    )
    decision_time = _as_utc(round_decision.decided_at)
    round_end = max(
        _as_utc(round_manifest.completed_at or round_decision.decided_at),
        decision_time,
    )

    prefix = f"{spec.campaign_id}.{round_id}"
    core_claim_id = f"claim.{prefix}.gate-result"
    hypothesis_claim_id = f"claim.{prefix}.hypothesis"
    prereg_entity_id = f"entity.{prefix}.preregistration"
    hypothesis_entity_id = f"entity.{prefix}.hypothesis"
    frozen_entity_id = f"entity.{prefix}.frozen-protocol"
    unseen_entity_id = f"entity.{prefix}.unseen-evaluation"
    gate_entity_id = f"entity.{prefix}.contribution-gate"
    decision_entity_id = f"entity.{prefix}.round-decision"
    code_entity_id = f"entity.{prefix}.official-executor"
    proposal_activity_id = f"activity.{prefix}.proposal"
    evaluation_activity_id = f"activity.{prefix}.unseen-evaluation"
    gate_activity_id = f"activity.{prefix}.contribution-gate"
    decision_activity_id = f"activity.{prefix}.decision"
    proposal_agent_id = f"agent.{prefix}.proposal-producer"
    executor_agent_id = f"agent.{prefix}.official-executor"
    adjudicator_agent_id = f"agent.{prefix}.adjudicator"
    plan_id = f"plan.{prefix}.preregistration"
    core_evidence_id = f"evidence.{prefix}.failed-gate"
    counterevidence_id = f"evidence.{prefix}.hypothesis-counter"
    limiting_evidence_id = f"evidence.{prefix}.hypothesis-limit"
    core_validation_id = f"validation.{prefix}.failed-gate"
    counter_validation_id = f"validation.{prefix}.hypothesis-counter"
    limit_validation_id = f"validation.{prefix}.hypothesis-limit"
    decision_id = f"decision.{prefix}.next-round"

    prereg_file_digest = _artifact_digest(round_manifest, "preregistration")
    hypothesis_file_digest = _artifact_digest(round_manifest, "hypothesis")
    frozen_file_digest = _artifact_digest(round_manifest, "frozen_protocol")
    unseen_file_digest = _artifact_digest(round_manifest, "unseen_evaluation")
    gate_file_digest = _artifact_digest(round_manifest, "contribution_gate")
    decision_file_digest = _artifact_digest(round_manifest, "round_decision")
    proposal_hash = _required_digest(hypothesis.proposal_hash, "hypothesis proposal")
    prereg_hash = _required_digest(
        preregistration.preregistration_hash, "preregistration"
    )
    frozen_hash = _required_digest(frozen.frozen_hash, "frozen protocol")
    unseen_hash = _required_digest(unseen.result_hash, "unseen evaluation")
    gate_hash = _required_digest(gate.gate_hash, "contribution gate")
    decision_hash = _required_digest(round_decision.decision_hash, "round decision")
    executor_hash = (
        frozen.code_hashes.get("official_executor")
        or frozen.code_hashes.get("runner")
        or frozen.code_hashes[sorted(frozen.code_hashes)[0]]
    )
    proposal_agent_hash = (
        frozen.code_hashes.get("llm_config")
        or frozen.code_hashes.get("campaign_adapter")
        or executor_hash
    )
    proposal_agent_kind = (
        ProvenanceAgentKind.MODEL
        if "llm_config" in frozen.code_hashes
        else ProvenanceAgentKind.SOFTWARE
    )
    proposal_agent_label = (
        "Configured local proposal model"
        if proposal_agent_kind is ProvenanceAgentKind.MODEL
        else "Campaign proposal adapter"
    )

    entities = [
        Entity(
            entity_id=prereg_entity_id,
            kind=EntityKind.SOURCE_SNAPSHOT,
            label=f"{round_id} frozen preregistration",
            content_digest=prereg_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "preregistration"),
            media_type="application/json",
            valid_from=_as_utc(preregistration.frozen_at),
            event_ids=[f"event.{prefix}.preregistered"],
            attributes={
                "domain_hash": prereg_hash,
                "result_blind": preregistration.result_blind,
                "approved": True,
            },
        ),
        Entity(
            entity_id=hypothesis_entity_id,
            kind=EntityKind.HYPOTHESIS,
            label=hypothesis.title,
            content_digest=hypothesis_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "hypothesis"),
            media_type="application/json",
            valid_from=proposal_end,
            event_ids=[f"event.{prefix}.proposed"],
            attributes={
                "approved": True,
                "domain_hash": proposal_hash,
                "statement": hypothesis.statement,
                "mechanism_family": hypothesis.mechanism_family,
            },
        ),
        Entity(
            entity_id=frozen_entity_id,
            kind=EntityKind.INPUT,
            label=f"{round_id} frozen execution protocol",
            content_digest=frozen_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "frozen_protocol"),
            media_type="application/json",
            valid_from=_as_utc(frozen.frozen_at),
            event_ids=[f"event.{prefix}.frozen"],
            attributes={"domain_hash": frozen_hash, "approved": True},
        ),
        Entity(
            entity_id=unseen_entity_id,
            kind=EntityKind.SOURCE_SNAPSHOT,
            label=f"{round_id} unseen evaluation",
            content_digest=unseen_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "unseen_evaluation"),
            media_type="application/json",
            valid_from=evaluation_end,
            event_ids=[f"event.{prefix}.unseen-completed"],
            attributes={
                "approved": True,
                "domain_hash": unseen_hash,
                "outcome": unseen.outcome.value,
            },
        ),
        Entity(
            entity_id=gate_entity_id,
            kind=EntityKind.ARTIFACT,
            label=f"{round_id} deterministic contribution gate",
            content_digest=gate_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "contribution_gate"),
            media_type="application/json",
            valid_from=adjudication_start,
            event_ids=[f"event.{prefix}.gate-evaluated"],
            attributes={
                "approved": True,
                "domain_hash": gate_hash,
                "passed": gate.passed,
                "failures": list(gate.failures),
            },
        ),
        Entity(
            entity_id=decision_entity_id,
            kind=EntityKind.DECISION,
            label=f"{round_id} deterministic next-step decision",
            content_digest=decision_file_digest,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "round_decision"),
            media_type="application/json",
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.decision"],
            attributes={
                "approved": True,
                "domain_hash": decision_hash,
                "outcome": round_decision.outcome.value,
                "decision": round_decision.decision.value,
            },
        ),
        Entity(
            entity_id=code_entity_id,
            kind=EntityKind.CODE,
            label="Frozen official campaign executor",
            content_digest=executor_hash,
            source_uri=f"urn:sha256:{executor_hash}",
            valid_from=_as_utc(frozen.frozen_at),
            event_ids=[f"event.{prefix}.frozen"],
            attributes={"approved": True},
        ),
    ]
    activities = [
        Activity(
            activity_id=proposal_activity_id,
            kind=ActivityKind.PROPOSAL,
            label=f"{round_id} local hypothesis proposal",
            started_at=proposal_start,
            ended_at=proposal_end,
            valid_from=proposal_start,
            event_ids=[f"event.{prefix}.proposed"],
        ),
        Activity(
            activity_id=evaluation_activity_id,
            kind=ActivityKind.EXECUTION,
            label=f"{round_id} frozen unseen evaluation",
            started_at=evaluation_start,
            ended_at=evaluation_end,
            valid_from=evaluation_start,
            event_ids=[f"event.{prefix}.unseen-completed"],
        ),
        Activity(
            activity_id=gate_activity_id,
            kind=ActivityKind.VALIDATION,
            label=f"{round_id} deterministic contribution gate",
            started_at=evaluation_end,
            ended_at=decision_time,
            valid_from=evaluation_end,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
        Activity(
            activity_id=decision_activity_id,
            kind=ActivityKind.DECISION,
            label=f"{round_id} deterministic transition decision",
            started_at=decision_time,
            ended_at=round_end,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.decision"],
        ),
    ]
    agents = [
        Agent(
            agent_id=proposal_agent_id,
            kind=proposal_agent_kind,
            label=proposal_agent_label,
            implementation_hash=proposal_agent_hash,
            valid_from=created_at,
            attributes={
                "role_boundary": "proposal_only",
                "gate_authority": False,
                "release_authority": False,
            },
        ),
        Agent(
            agent_id=executor_agent_id,
            kind=ProvenanceAgentKind.SOFTWARE,
            label="Frozen official campaign executor",
            implementation_hash=executor_hash,
            valid_from=_as_utc(frozen.frozen_at),
        ),
        Agent(
            agent_id=adjudicator_agent_id,
            kind=ProvenanceAgentKind.DETERMINISTIC_POLICY,
            label="Frozen deterministic contribution adjudicator",
            implementation_hash=frozen.adjudicator_hash,
            valid_from=_as_utc(preregistration.frozen_at),
            attributes={"model_override_allowed": False},
        ),
    ]
    plan = Plan(
        plan_id=plan_id,
        title=f"{round_id} result-blind preregistration",
        description="Frozen data, seeds, acceptance criteria, stop rules, code, and adjudicator.",
        content_digest=prereg_hash,
        valid_from=_as_utc(preregistration.frozen_at),
        event_ids=[f"event.{prefix}.preregistered"],
    )
    usages = [
        Usage(
            usage_id=f"usage.{prefix}.proposal-prereg",
            activity_id=proposal_activity_id,
            entity_id=prereg_entity_id,
            role="proposal context",
            at_time=proposal_start,
            valid_from=proposal_start,
        ),
        Usage(
            usage_id=f"usage.{prefix}.evaluation-protocol",
            activity_id=evaluation_activity_id,
            entity_id=frozen_entity_id,
            role="frozen protocol",
            at_time=evaluation_start,
            valid_from=evaluation_start,
        ),
        Usage(
            usage_id=f"usage.{prefix}.evaluation-code",
            activity_id=evaluation_activity_id,
            entity_id=code_entity_id,
            role="frozen code",
            at_time=evaluation_start,
            valid_from=evaluation_start,
        ),
        Usage(
            usage_id=f"usage.{prefix}.gate-result",
            activity_id=gate_activity_id,
            entity_id=unseen_entity_id,
            role="evaluated unseen result",
            at_time=evaluation_end,
            valid_from=evaluation_end,
        ),
        Usage(
            usage_id=f"usage.{prefix}.gate-plan",
            activity_id=gate_activity_id,
            entity_id=prereg_entity_id,
            role="frozen acceptance criteria",
            at_time=evaluation_end,
            valid_from=evaluation_end,
        ),
        Usage(
            usage_id=f"usage.{prefix}.decision-gate",
            activity_id=decision_activity_id,
            entity_id=gate_entity_id,
            role="validated contribution gate",
            at_time=decision_time,
            valid_from=decision_time,
        ),
    ]
    generations = [
        Generation(
            generation_id=f"generation.{prefix}.hypothesis",
            entity_id=hypothesis_entity_id,
            activity_id=proposal_activity_id,
            at_time=proposal_end,
            valid_from=proposal_end,
        ),
        Generation(
            generation_id=f"generation.{prefix}.unseen-result",
            entity_id=unseen_entity_id,
            activity_id=evaluation_activity_id,
            at_time=evaluation_end,
            valid_from=evaluation_end,
        ),
        Generation(
            generation_id=f"generation.{prefix}.gate",
            entity_id=gate_entity_id,
            activity_id=gate_activity_id,
            at_time=adjudication_start,
            valid_from=adjudication_start,
        ),
        Generation(
            generation_id=f"generation.{prefix}.decision",
            entity_id=decision_entity_id,
            activity_id=decision_activity_id,
            at_time=decision_time,
            valid_from=decision_time,
        ),
    ]
    associations = [
        Association(
            association_id=f"association.{prefix}.proposal-producer",
            activity_id=proposal_activity_id,
            agent_id=proposal_agent_id,
            role="proposal",
            plan_id=plan_id,
            at_time=proposal_start,
            valid_from=proposal_start,
        ),
        Association(
            association_id=f"association.{prefix}.evaluation-executor",
            activity_id=evaluation_activity_id,
            agent_id=executor_agent_id,
            role="frozen execution",
            plan_id=plan_id,
            at_time=evaluation_start,
            valid_from=evaluation_start,
        ),
        Association(
            association_id=f"association.{prefix}.gate-adjudicator",
            activity_id=gate_activity_id,
            agent_id=adjudicator_agent_id,
            role="deterministic validation",
            plan_id=plan_id,
            at_time=evaluation_end,
            valid_from=evaluation_end,
        ),
        Association(
            association_id=f"association.{prefix}.decision-policy",
            activity_id=decision_activity_id,
            agent_id=adjudicator_agent_id,
            role="deterministic transition",
            plan_id=plan_id,
            at_time=decision_time,
            valid_from=decision_time,
        ),
    ]
    snapshots = [
        SourceSnapshot(
            snapshot_id=f"snapshot.{prefix}.preregistration",
            entity_id=prereg_entity_id,
            source_uri=_campaign_uri(spec.campaign_id, round_manifest, "preregistration"),
            retrieved_at=_as_utc(preregistration.frozen_at),
            content_digest=prereg_file_digest,
            valid_from=_as_utc(preregistration.frozen_at),
        ),
        SourceSnapshot(
            snapshot_id=f"snapshot.{prefix}.unseen-evaluation",
            entity_id=unseen_entity_id,
            source_uri=_campaign_uri(
                spec.campaign_id, round_manifest, "unseen_evaluation"
            ),
            retrieved_at=evaluation_end,
            content_digest=unseen_file_digest,
            valid_from=evaluation_end,
        ),
    ]
    claims = [
        Claim(
            claim_id=core_claim_id,
            statement=(
                f"{round_id} did not pass its frozen contribution gate and the "
                "deterministic decision advanced to the next round."
            ),
            project_id=spec.project_id,
            confidence=1.0,
            core=True,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.decision"],
        ),
        Claim(
            claim_id=hypothesis_claim_id,
            statement=hypothesis.statement,
            project_id=spec.project_id,
            confidence=0.5,
            core=False,
            valid_from=proposal_end,
            event_ids=[f"event.{prefix}.proposed"],
        ),
    ]
    validations = [
        Validation(
            validation_id=core_validation_id,
            subject_id=core_evidence_id,
            activity_id=gate_activity_id,
            agent_id=adjudicator_agent_id,
            status=ValidationStatus.PASSED,
            summary=(
                "Artifact integrity and the frozen deterministic gate confirm that "
                f"the gate failed: {', '.join(gate.failures)}."
            ),
            checked_at=decision_time,
            artifact_entity_id=gate_entity_id,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
        Validation(
            validation_id=counter_validation_id,
            subject_id=counterevidence_id,
            activity_id=gate_activity_id,
            agent_id=adjudicator_agent_id,
            status=ValidationStatus.PASSED,
            summary="The frozen gate rejects the hypothesis under its preregistered criteria.",
            checked_at=decision_time,
            artifact_entity_id=unseen_entity_id,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
        Validation(
            validation_id=limit_validation_id,
            subject_id=limiting_evidence_id,
            activity_id=gate_activity_id,
            agent_id=adjudicator_agent_id,
            status=ValidationStatus.PASSED,
            summary=(
                "The median improvement is positive, but its confidence interval "
                "crosses zero and the frozen ablation requirement is incomplete."
            ),
            checked_at=decision_time,
            artifact_entity_id=unseen_entity_id,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
    ]
    evidence = [
        Evidence(
            evidence_id=core_evidence_id,
            claim_id=core_claim_id,
            artifact_entity_id=gate_entity_id,
            source_entity_id=unseen_entity_id,
            source_snapshot_id=f"snapshot.{prefix}.unseen-evaluation",
            generating_activity_id=gate_activity_id,
            responsible_agent_ids=[adjudicator_agent_id],
            validation_ids=[core_validation_id],
            summary=(
                "The frozen contribution gate failed and names the failed checks; "
                "the round decision therefore records next_round."
            ),
            confidence=1.0,
            direction=EvidenceDirection.SUPPORTS,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
        Evidence(
            evidence_id=limiting_evidence_id,
            claim_id=hypothesis_claim_id,
            artifact_entity_id=unseen_entity_id,
            source_entity_id=prereg_entity_id,
            source_snapshot_id=f"snapshot.{prefix}.preregistration",
            generating_activity_id=evaluation_activity_id,
            responsible_agent_ids=[executor_agent_id],
            validation_ids=[limit_validation_id],
            summary=(
                "Observed median relative improvement was positive, but uncertainty "
                "and incomplete ablations limit generalization."
            ),
            confidence=1.0,
            direction=EvidenceDirection.LIMITS,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        ),
    ]
    counterevidence = [
        Counterevidence(
            evidence_id=counterevidence_id,
            claim_id=hypothesis_claim_id,
            artifact_entity_id=unseen_entity_id,
            source_entity_id=prereg_entity_id,
            source_snapshot_id=f"snapshot.{prefix}.preregistration",
            generating_activity_id=evaluation_activity_id,
            responsible_agent_ids=[executor_agent_id],
            validation_ids=[counter_validation_id],
            summary=(
                "The bootstrap lower confidence bound was not positive and the "
                "three-ablation requirement was incomplete."
            ),
            confidence=1.0,
            valid_from=decision_time,
            event_ids=[f"event.{prefix}.gate-evaluated"],
        )
    ]
    decision = Decision(
        decision_id=decision_id,
        claim_ids=[core_claim_id, hypothesis_claim_id],
        activity_id=decision_activity_id,
        responsible_agent_id=adjudicator_agent_id,
        validation_ids=[core_validation_id, counter_validation_id],
        artifact_entity_id=decision_entity_id,
        outcome=round_decision.decision.value,
        rationale=round_decision.reason,
        decided_at=decision_time,
        valid_from=decision_time,
        event_ids=[f"event.{prefix}.decision"],
    )
    tool_invocation = ToolInvocation(
        invocation_id=f"invocation.{prefix}.official-executor",
        activity_id=evaluation_activity_id,
        agent_id=executor_agent_id,
        tool_name="official_campaign_executor",
        request_digest=frozen_hash,
        response_digest=unseen_hash,
        input_entity_ids=[frozen_entity_id, code_entity_id],
        output_entity_ids=[unseen_entity_id],
        status=InvocationStatus.SUCCEEDED,
        started_at=evaluation_start,
        completed_at=evaluation_end,
        valid_from=evaluation_start,
        event_ids=[f"event.{prefix}.unseen-completed"],
    )
    derivations = [
        Derivation(
            derivation_id=f"derivation.{prefix}.hypothesis-from-plan",
            generated_entity_id=hypothesis_entity_id,
            used_entity_id=prereg_entity_id,
            activity_id=proposal_activity_id,
            valid_from=proposal_end,
        ),
        Derivation(
            derivation_id=f"derivation.{prefix}.unseen-from-protocol",
            generated_entity_id=unseen_entity_id,
            used_entity_id=frozen_entity_id,
            activity_id=evaluation_activity_id,
            valid_from=evaluation_end,
        ),
        Derivation(
            derivation_id=f"derivation.{prefix}.gate-from-result",
            generated_entity_id=gate_entity_id,
            used_entity_id=unseen_entity_id,
            activity_id=gate_activity_id,
            valid_from=adjudication_start,
        ),
        Derivation(
            derivation_id=f"derivation.{prefix}.decision-from-gate",
            generated_entity_id=decision_entity_id,
            used_entity_id=gate_entity_id,
            activity_id=decision_activity_id,
            valid_from=decision_time,
        ),
    ]
    approved_record_ids = sorted(
        [
            hypothesis_entity_id,
            frozen_entity_id,
            unseen_entity_id,
            gate_entity_id,
            decision_entity_id,
            code_entity_id,
            core_claim_id,
            hypothesis_claim_id,
            core_evidence_id,
            counterevidence_id,
            limiting_evidence_id,
            decision_id,
        ]
    )
    bundle = ProvenanceBundle.create(
        bundle_id=f"provenance.{prefix}",
        project_id=spec.project_id,
        run_id=spec.campaign_id,
        created_at=round_end,
        entities=entities,
        activities=activities,
        agents=agents,
        plans=[plan],
        usages=usages,
        generations=generations,
        derivations=derivations,
        associations=associations,
        source_snapshots=snapshots,
        claims=claims,
        evidence=evidence,
        counterevidence=counterevidence,
        validations=validations,
        decisions=[decision],
        tool_invocations=[tool_invocation],
        metadata={
            "campaign_manifest_hash": campaign_manifest.manifest_hash or "",
            "campaign_lineage_hash": campaign_manifest.lineage_hash or "",
            "round_manifest_hash": round_manifest.manifest_hash or "",
            "adapter_id": spec.adapter_id,
            "source_validation": "validate_campaign_directory",
            "approved_record_ids": approved_record_ids,
            "private_paths_included": False,
        },
    )
    bundle.require_claim_trace(core_claim_id)
    return CampaignRoundProvenance(
        bundle=bundle,
        core_claim_id=core_claim_id,
        hypothesis_claim_id=hypothesis_claim_id,
        approved_record_ids=approved_record_ids,
    )


def _current_records(
    records: list[ProvenanceRecord],
    id_field: str,
) -> list[ProvenanceRecord]:
    superseded = {
        record.supersedes_id
        for record in records
        if record.supersedes_id is not None
    }
    return [
        record
        for record in records
        if str(getattr(record, id_field)) not in superseded
        and record.invalidated_at is None
    ]


def _load_round_artifact(
    root: Path,
    manifest: RoundManifest,
    artifact_name: str,
    model_type: type[CampaignModel],
    hash_field: str,
) -> CampaignModel:
    path = _managed_artifact_path(root, manifest, artifact_name)
    try:
        model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CampaignIntegrityError(
            f"cannot load managed {artifact_name} artifact"
        ) from exc
    stored = getattr(model, hash_field)
    expected = data_hash(model.model_dump(mode="json", exclude={hash_field}))
    if stored != expected:
        raise CampaignIntegrityError(f"{artifact_name} {hash_field} mismatch")
    return model


def _managed_artifact_path(
    root: Path,
    manifest: RoundManifest,
    artifact_name: str,
) -> Path:
    try:
        raw_path = manifest.artifact_paths[artifact_name]
    except KeyError as exc:
        raise CampaignIntegrityError(
            f"round is missing managed artifact {artifact_name}"
        ) from exc
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CampaignIntegrityError(
            f"managed artifact {artifact_name} escapes campaign directory"
        ) from exc
    return candidate


def _artifact_digest(manifest: RoundManifest, artifact_name: str) -> str:
    try:
        return manifest.artifact_hashes[artifact_name]
    except KeyError as exc:
        raise CampaignIntegrityError(
            f"round is missing artifact digest {artifact_name}"
        ) from exc


def _required_digest(value: str | None, label: str) -> str:
    if value is None:
        raise CampaignIntegrityError(f"{label} has no content digest")
    return value


def _campaign_uri(
    campaign_id: str,
    manifest: RoundManifest,
    artifact_name: str,
) -> str:
    path = manifest.artifact_paths[artifact_name]
    return f"campaign://{campaign_id}/{path}"


def _stage_time(manifest: RoundManifest, stage: str) -> datetime:
    transition = next(
        (item for item in manifest.stage_history if item.stage.value == stage),
        None,
    )
    if transition is None:
        raise CampaignIntegrityError(
            f"round {manifest.round_id} has no {stage} transition"
        )
    return _as_utc(transition.entered_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CampaignIntegrityError("campaign timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_round_alignment(
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    preregistration: Preregistration,
    frozen: FrozenRoundProtocol,
    unseen: UnseenEvaluation,
    gate: ContributionGateResult,
    decision: RoundDecision,
) -> None:
    if {
        hypothesis.round_id,
        preregistration.round_id,
        frozen.round_id,
        unseen.round_id,
        gate.round_id,
        decision.round_id,
    } != {manifest.round_id}:
        raise CampaignIntegrityError("managed artifacts do not belong to the selected round")
    if len(
        {
            hypothesis.hypothesis_id,
            preregistration.hypothesis_id,
            frozen.hypothesis_id,
            unseen.hypothesis_id,
        }
    ) != 1:
        raise CampaignIntegrityError("managed artifacts disagree on hypothesis identity")
    if frozen.unseen_data_refs != preregistration.unseen_data_refs:
        raise CampaignIntegrityError("frozen protocol changed preregistered unseen data")
    if gate.evaluated_result_hash != unseen.result_hash:
        raise CampaignIntegrityError("contribution gate does not evaluate the unseen result")
    if decision.result_hash != unseen.result_hash or decision.contribution_gate_hash != gate.gate_hash:
        raise CampaignIntegrityError("round decision is not bound to its result and gate")
