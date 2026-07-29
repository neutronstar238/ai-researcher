from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from autoresearch.campaign.mechanism_round import (
    ClaimEvidenceKind,
    ClaimEvidenceLink,
    ClaimEvidenceRequirement,
    ClaimKind,
    GeneratedCodeEvidence,
    LiteratureArea,
    ManuscriptClaimEvidenceAudit,
    MechanismChangeKind,
    MechanismCodeProposal,
    MechanismDiagnosis,
    MechanismPanelSpec,
    MechanismResearchBrief,
    MechanismRoundFreeze,
    MechanismRoundIntegrityError,
    MechanismTaskReference,
    ParentSprintEvidence,
    build_task2612_research_brief,
    freeze_task2612_foundation,
    load_mechanism_foundation,
    load_parent_sprint_evidence,
    task2612_verified_sources,
)
from autoresearch.campaign.sprint import (
    AutonomyLevel,
    SprintAutonomyAudit,
    SprintManifest,
    SprintOutcome,
    SprintStage,
    SprintTopicCandidate,
    SprintTopicSelection,
    TaskLevelEndpointResult,
)
from autoresearch.campaign.systems import SystemsMode
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.schemas import file_hash

UTC_NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
ModelT = TypeVar("ModelT", bound=BaseModel)


def _stamp(model: ModelT, hash_field: str) -> ModelT:
    unstamped = model.model_copy(update={hash_field: None})
    return unstamped.model_copy(update={hash_field: canonical_model_hash(unstamped)})


def _write_parent_sprint(
    root: Path,
    *,
    endpoint_passed: bool = False,
    endpoint_failures: tuple[str, ...] = ("bootstrap_ci_lower_above_zero",),
) -> Path:
    root.mkdir(parents=True)
    sprint_id = root.name
    candidates = tuple(
        SprintTopicCandidate(
            candidate_id=f"C00{index}",
            title=f"Evidence mechanism candidate {index}",
            research_question=(
                f"Can evidence mechanism candidate {index} reduce unsupported claims?"
            ),
            hypothesis=(
                f"Candidate {index} will reduce unsupported claims on independent tasks."
            ),
            program_id="systems-evidence-gate-claims-task-v2",
            mechanism_rationale=(
                f"Candidate {index} changes an executable evidence-control mechanism."
            ),
            novelty_risk="Adjacent evidence gates may already cover part of this change.",
            falsification_conditions=(
                "The lower confidence bound is not above zero.",
                "The minimum coverage target is not met.",
            ),
            literature_refs=("source-001",),
        )
        for index in range(1, 4)
    )
    selection = SprintTopicSelection(
        sprint_id=sprint_id,
        brief_hash=SHA_A,
        literature_snapshot_hash=SHA_B,
        program_catalog_hash=SHA_C,
        candidates=candidates,
        selected_candidate_id="C003",
        selection_rationale=(
            "Candidate C003 directly targets the retained unsupported-claim failure."
        ),
        provider="fixture",
        base_url="http://localhost:8000/v1",
        model_name="fixture-model",
        response_text='{"selected_candidate_id":"C003"}',
        usage={},
        attempt_count=1,
        used_fallback=False,
        created_at=UTC_NOW,
    )
    selection = _stamp(selection, "selection_hash")
    selection_path = write_json_model(root / "topic-selection.json", selection)

    paired = {f"parent-task-{index:02d}": 0.0 for index in range(10)}
    endpoint = TaskLevelEndpointResult(
        sprint_id=sprint_id,
        benchmark_result_hash=SHA_D,
        topic_selection_hash=selection.selection_hash,
        candidate_id="C003",
        program_id="systems-evidence-gate-claims-task-v2",
        endpoint="unsupported_claim",
        candidate_mode=SystemsMode.FULL_LOOP,
        baseline_mode=SystemsMode.NO_EVIDENCE_GATE,
        independent_unit_count=10,
        repeated_seed_count_per_task=3,
        paired_task_differences=paired,
        paired_mean_gain=0.2,
        bootstrap_resamples=20_000,
        bootstrap_ci95_lower=0.0,
        bootstrap_ci95_upper=0.5,
        checks={"bootstrap_ci_lower_above_zero": endpoint_passed},
        passed=endpoint_passed,
        failures=endpoint_failures,
        warnings=(),
        created_at=UTC_NOW,
        external_submission_authorized=False,
    )
    endpoint = _stamp(endpoint, "endpoint_hash")
    endpoint_path = write_json_model(root / "task-level-endpoint.json", endpoint)

    audit = SprintAutonomyAudit(
        sprint_id=sprint_id,
        checked_at=UTC_NOW,
        autonomy_level=AutonomyLevel.BOUNDED_AUTONOMOUS,
        checks={
            "open_ended_experiment_code_generation": False,
            "external_submission": False,
        },
        prelaunch_operator_research_decisions=0,
        post_start_manual_research_decisions=0,
        local_model_fallback_count=0,
        limitations=("The executable catalogue was frozen before the sprint.",),
        allowed_claim="A bounded autonomous sprint completed.",
        prohibited_claims=("Open-ended autonomous science was not demonstrated.",),
        external_submission_authorized=False,
    )
    audit = _stamp(audit, "audit_hash")
    audit_path = write_json_model(root / "autonomy-audit.json", audit)

    artifact_paths = {
        "topic_selection": selection_path.resolve().as_posix(),
        "task_level_endpoint": endpoint_path.resolve().as_posix(),
        "autonomy_audit": audit_path.resolve().as_posix(),
    }
    artifact_sha256 = {
        name: file_hash(path) for name, path in artifact_paths.items()
    }
    manifest = SprintManifest(
        sprint_id=sprint_id,
        spec_hash=SHA_E,
        stage=SprintStage.COMPLETE,
        outcome=SprintOutcome.COMPLETED,
        selected_candidate_id="C003",
        selected_program_id="systems-evidence-gate-claims-task-v2",
        artifact_paths=artifact_paths,
        artifact_sha256=artifact_sha256,
        updated_at=UTC_NOW,
        external_submission_authorized=False,
    )
    manifest = _stamp(manifest, "manifest_hash")
    write_json_model(root / "sprint-manifest.json", manifest)
    return root


def _load_fixture_parent(tmp_path: Path) -> ParentSprintEvidence:
    parent_dir = _write_parent_sprint(tmp_path / "fixture-negative-parent")
    return load_parent_sprint_evidence(
        parent_dir,
        require_formal_clean_v2_identity=False,
    )


def _task(task_id: str, family: str = "synthetic-family") -> MechanismTaskReference:
    return MechanismTaskReference(
        task_id=task_id,
        task_family=family,
        source_fingerprint=SHA_A,
        task_contract_hash=SHA_B,
    )


def _mechanism_chain(
    parent: ParentSprintEvidence,
) -> tuple[
    MechanismResearchBrief,
    MechanismDiagnosis,
    MechanismCodeProposal,
    GeneratedCodeEvidence,
    MechanismPanelSpec,
]:
    brief = build_task2612_research_brief(parent)
    source_ids = ["source-001", "source-002", "source-010"]
    diagnosis = MechanismDiagnosis.create(
        parent=parent,
        brief=brief,
        diagnosis_id="diagnosis-001",
        causal_hypotheses=[
            "The binary gate hides the coverage-risk trade-off.",
            "Intrinsic judgment lacks external executable feedback.",
        ],
        required_mechanism_properties=[
            "Return a calibrated accept-or-abstain decision.",
            "Bind every accepted claim to externally checked evidence.",
        ],
        literature_source_ids=source_ids,
        model_interaction_hash=SHA_C,
    )
    proposal = MechanismCodeProposal.create(
        diagnosis=diagnosis,
        brief=brief,
        proposal_id="proposal-001",
        mechanism_kind=MechanismChangeKind.RISK_SELECTIVE_GATE,
        mechanism_title="Risk-selective evidence controller",
        mechanism_delta=(
            "Replace a binary evidence presence check with an explicit "
            "accept-or-abstain policy constrained by coverage and residual risk."
        ),
        falsification_conditions=[
            "Unsupported-claim risk exceeds the preregistered ceiling.",
            "Coverage falls below the preregistered minimum.",
        ],
        literature_source_ids=source_ids,
        source_text=(
            "def evaluate_claims(claims):\n"
            "    return [{'decision': 'abstain'} for _claim in claims]\n"
        ),
        model_interaction_hash=SHA_D,
    )
    code_evidence = GeneratedCodeEvidence.create(
        proposal_hash=proposal.proposal_hash,
        source_sha256=proposal.source_sha256,
        static_review_report_hash=SHA_A,
        static_review_approved=True,
        blocking_finding_codes=[],
        unit_test_report_hash=SHA_B,
        unit_tests_passed=True,
        property_test_report_hash=SHA_C,
        property_tests_passed=True,
        harness_spec_hash=SHA_D,
        sandbox_episode_hash=SHA_E,
        sandbox_smoke_passed=True,
        network_used=False,
    )
    panel = MechanismPanelSpec.create(
        parent=parent,
        panel_id="panel-001",
        development_tasks=[_task(f"development-{index}") for index in range(3)],
        confirmatory_tasks=[_task(f"confirmatory-{index}") for index in range(6)],
        minimum_coverage=0.6,
        maximum_unsupported_claim_rate=0.1,
        bootstrap_resamples=20_000,
        bootstrap_seed=2612,
    )
    return brief, diagnosis, proposal, code_evidence, panel


def test_freezes_and_reloads_parent_bound_foundation(tmp_path: Path) -> None:
    parent_dir = _write_parent_sprint(tmp_path / "fixture-negative-parent")
    output_dir = tmp_path / "foundation"

    manifest = freeze_task2612_foundation(
        parent_sprint_dir=parent_dir,
        output_dir=output_dir,
        frozen_at=UTC_NOW,
        require_formal_clean_v2_identity=False,
    )
    loaded_manifest, parent, brief = load_mechanism_foundation(output_dir)

    assert loaded_manifest == manifest
    assert parent.scientific_endpoint == "negative_result"
    assert len(parent.revealed_task_ids) == 10
    assert brief.parent_endpoint_hash == parent.endpoint_hash
    assert len(brief.sources) == 14
    assert manifest.external_submission_authorized is False


def test_parent_artifact_tamper_fails_closed(tmp_path: Path) -> None:
    parent_dir = _write_parent_sprint(tmp_path / "fixture-negative-parent")
    with (parent_dir / "topic-selection.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(MechanismRoundIntegrityError, match="changed"):
        load_parent_sprint_evidence(
            parent_dir,
            require_formal_clean_v2_identity=False,
        )


def test_non_negative_parent_is_rejected(tmp_path: Path) -> None:
    parent_dir = _write_parent_sprint(
        tmp_path / "fixture-positive-parent",
        endpoint_passed=True,
        endpoint_failures=(),
    )

    with pytest.raises(MechanismRoundIntegrityError, match="negative parent"):
        load_parent_sprint_evidence(
            parent_dir,
            require_formal_clean_v2_identity=False,
        )


def test_research_brief_has_verified_cross_area_coverage(
    tmp_path: Path,
) -> None:
    parent = _load_fixture_parent(tmp_path)
    brief = build_task2612_research_brief(parent)

    assert all(source.verification_grade == "verified" for source in brief.sources)
    assert all(source.source_url.startswith("https://") for source in brief.sources)
    assert {
        area: sum(area in source.areas for source in brief.sources)
        for area in LiteratureArea
    } == {
        LiteratureArea.SELECTIVE_FACTUALITY: 4,
        LiteratureArea.SCIENTIFIC_AGENT_EVALUATION: 3,
        LiteratureArea.GENERATED_CODE_SECURITY: 3,
        LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT: 5,
    }
    with pytest.raises(ValidationError, match="brief_hash"):
        MechanismResearchBrief.model_validate(
            brief.model_dump(mode="json") | {"angle": "tampered angle"}
        )


def test_panel_rejects_revealed_and_overlapping_tasks(tmp_path: Path) -> None:
    parent = _load_fixture_parent(tmp_path)

    with pytest.raises(ValidationError, match="reuses a revealed parent task"):
        MechanismPanelSpec.create(
            parent=parent,
            panel_id="parent-leakage-panel",
            development_tasks=[
                _task(parent.revealed_task_ids[0]),
                _task("development-1"),
                _task("development-2"),
            ],
            confirmatory_tasks=[_task(f"confirmatory-{index}") for index in range(6)],
            minimum_coverage=0.6,
            maximum_unsupported_claim_rate=0.1,
            bootstrap_resamples=20_000,
            bootstrap_seed=2612,
        )

    with pytest.raises(ValidationError, match="must be disjoint"):
        MechanismPanelSpec.create(
            parent=parent,
            panel_id="partition-leakage-panel",
            development_tasks=[
                _task("shared-task"),
                _task("development-1"),
                _task("development-2"),
            ],
            confirmatory_tasks=[
                _task("shared-task"),
                *[_task(f"confirmatory-{index}") for index in range(5)],
            ],
            minimum_coverage=0.6,
            maximum_unsupported_claim_rate=0.1,
            bootstrap_resamples=20_000,
            bootstrap_seed=2612,
        )


def test_round_freeze_requires_approved_exact_generated_code(
    tmp_path: Path,
) -> None:
    parent = _load_fixture_parent(tmp_path)
    brief, diagnosis, proposal, code_evidence, panel = _mechanism_chain(parent)
    freeze = MechanismRoundFreeze.create(
        round_id="round-001",
        parent=parent,
        brief=brief,
        diagnosis=diagnosis,
        proposal=proposal,
        code_evidence=code_evidence,
        panel=panel,
    )
    assert freeze.generated_source_sha256 == proposal.source_sha256
    assert freeze.model_generated_mechanism_code_verified is True
    assert freeze.confirmatory_results_revealed is False
    assert freeze.external_submission_authorized is False

    rejected = GeneratedCodeEvidence.create(
        proposal_hash=proposal.proposal_hash,
        source_sha256=proposal.source_sha256,
        static_review_report_hash=SHA_A,
        static_review_approved=False,
        blocking_finding_codes=["dangerous-import"],
        unit_test_report_hash=SHA_B,
        unit_tests_passed=True,
        property_test_report_hash=SHA_C,
        property_tests_passed=True,
        harness_spec_hash=SHA_D,
        sandbox_episode_hash=SHA_E,
        sandbox_smoke_passed=True,
        network_used=False,
    )
    assert rejected.approved_for_development is False
    with pytest.raises(MechanismRoundIntegrityError, match="has not passed"):
        MechanismRoundFreeze.create(
            round_id="round-rejected",
            parent=parent,
            brief=brief,
            diagnosis=diagnosis,
            proposal=proposal,
            code_evidence=rejected,
            panel=panel,
        )

    mismatched = code_evidence.model_copy(update={"source_sha256": SHA_F})
    with pytest.raises(MechanismRoundIntegrityError, match="differs"):
        MechanismRoundFreeze.create(
            round_id="round-mismatch",
            parent=parent,
            brief=brief,
            diagnosis=diagnosis,
            proposal=proposal,
            code_evidence=mismatched,
            panel=panel,
        )


def test_claim_audit_is_typed_complete_and_never_grants_submission() -> None:
    requirements = [
        ClaimEvidenceRequirement(
            claim_id="prior-work-claim",
            claim_kind=ClaimKind.NAMED_PRIOR_WORK,
            claim_text="Prior work evaluates citation attribution.",
            required_evidence_kinds=[ClaimEvidenceKind.VERIFIED_LITERATURE],
        ),
        ClaimEvidenceRequirement(
            claim_id="method-claim",
            claim_kind=ClaimKind.METHOD,
            claim_text="The method executes the exact reviewed generated bytes.",
            required_evidence_kinds=[
                ClaimEvidenceKind.GENERATED_CODE,
                ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
            ],
        ),
    ]
    partial_links = [
        ClaimEvidenceLink(
            claim_id="prior-work-claim",
            evidence_kind=ClaimEvidenceKind.VERIFIED_LITERATURE,
            evidence_id="source-014",
            evidence_hash=SHA_A,
            supports_claim=True,
        ),
        ClaimEvidenceLink(
            claim_id="method-claim",
            evidence_kind=ClaimEvidenceKind.GENERATED_CODE,
            evidence_id="generated-code-001",
            evidence_hash=SHA_B,
            supports_claim=True,
        ),
    ]
    partial = ManuscriptClaimEvidenceAudit.create(
        round_freeze_hash=SHA_C,
        manuscript_sha256=SHA_D,
        requirements=requirements,
        links=partial_links,
    )
    assert partial.unsupported_claim_ids == ["method-claim"]
    assert partial.coverage_complete is False

    complete = ManuscriptClaimEvidenceAudit.create(
        round_freeze_hash=SHA_C,
        manuscript_sha256=SHA_D,
        requirements=requirements,
        links=[
            *partial_links,
            ClaimEvidenceLink(
                claim_id="method-claim",
                evidence_kind=ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
                evidence_id="protocol-001",
                evidence_hash=SHA_E,
                supports_claim=True,
            ),
        ],
    )
    assert complete.unsupported_claim_ids == []
    assert complete.coverage_complete is True
    assert complete.submission_readiness_granted is False
    assert complete.external_submission_authorized is False


def test_claim_requirement_rejects_semantically_incomplete_evidence() -> None:
    with pytest.raises(ValidationError, match="missing required evidence"):
        ClaimEvidenceRequirement(
            claim_id="result-claim",
            claim_kind=ClaimKind.RESULT,
            claim_text="The mechanism improves the preregistered endpoint.",
            required_evidence_kinds=[ClaimEvidenceKind.METRIC],
        )


def test_foundation_file_tamper_fails_closed(tmp_path: Path) -> None:
    parent_dir = _write_parent_sprint(tmp_path / "fixture-negative-parent")
    output_dir = tmp_path / "foundation"
    freeze_task2612_foundation(
        parent_sprint_dir=parent_dir,
        output_dir=output_dir,
        frozen_at=UTC_NOW,
        require_formal_clean_v2_identity=False,
    )
    with (output_dir / "research-brief.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(MechanismRoundIntegrityError, match="file hash mismatch"):
        load_mechanism_foundation(output_dir)


def test_verified_source_ids_are_stable() -> None:
    assert [source.source_id for source in task2612_verified_sources()] == [
        f"source-{index:03d}" for index in range(1, 15)
    ]


def test_verified_source_metadata_is_bound_to_official_locators() -> None:
    sources = {
        source.source_id: source for source in task2612_verified_sources()
    }

    assert sources["source-004"].venue == "NeurIPS 2024"
    assert sources["source-004"].locator == "doi:10.52202/079017-2567"
    assert sources["source-005"].authors[-2:] == ["Yu Su", "Huan Sun"]
    assert len(sources["source-005"].authors) == 20
    assert sources["source-005"].locator == "OpenReview:6z4YKr0GK6"
    assert sources["source-006"].authors[2] == "Nitya Nadgir"
    assert sources["source-006"].venue == "Transactions on Machine Learning Research"
    assert sources["source-008"].title == (
        "SecureVibeBench: Benchmarking Secure Vibe Coding of AI Agents via "
        "Reconstructing Vulnerability-Introducing Scenarios"
    )
    assert sources["source-008"].locator == (
        "doi:10.18653/v1/2026.acl-long.1107"
    )
    assert sources["source-009"].title == (
        "Rethinking the Evaluation of Secure Code Generation"
    )
    assert sources["source-009"].venue == "ICSE 2026 Research Track"
    assert sources["source-011"].title == (
        "SCICOQA: Quality Assurance for Scientific Paper-Code Alignment"
    )
    assert sources["source-011"].authors[0] == "Tim Baumgärtner"
    assert sources["source-013"].locator == (
        "doi:10.18653/v1/2026.findings-acl.1699"
    )
