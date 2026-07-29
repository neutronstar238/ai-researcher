from __future__ import annotations

import json
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.portfolio import (
    BaselineReproductionEvidence,
    BaselineReproductionPlan,
    BranchBudget,
    FidelityKind,
    FidelityStageSpec,
    MetricDirection,
    NearestWorkDelta,
    OpportunityStage,
    PortfolioArmKind,
    PortfolioBranch,
    PortfolioIntegrityError,
    PortfolioSpec,
    PrimaryMetricSpec,
    ProspectivePowerPlan,
    PublicationEndpoint,
    ResearchBudget,
    ResearchDataSplit,
    ResearchOpportunity,
    ResearchQuestionCertificate,
    ResearchSource,
    SourceMaturity,
    assess_portfolio,
    assess_research_opportunity,
    portfolio_contract_json_schemas,
)


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _sources() -> list[ResearchSource]:
    return [
        ResearchSource(
            source_id=f"source-{index:03d}",
            title=f"Verified adjacent work {index}",
            year=2026,
            locator=f"arXiv:2607.{index:05d}",
            source_url=f"https://arxiv.org/abs/2607.{index:05d}",
            maturity=(
                SourceMaturity.PEER_REVIEWED
                if index == 1
                else SourceMaturity.PREPRINT
            ),
            source_fingerprint=_sha(f"source-{index}"),
        )
        for index in range(1, 4)
    ]


def _certificate() -> ResearchQuestionCertificate:
    return ResearchQuestionCertificate.create(
        certificate_id="certificate-search-policy-v1",
        literature_cutoff=date(2026, 7, 29),
        question=(
            "Does a diversity-constrained, multi-fidelity research portfolio "
            "improve confirmed task-level scientific success at equal budget?"
        ),
        primitives=[
            "A branch is one executable and falsifiable mechanism delta.",
            "A scientific unit is a task, not a repeated seed.",
        ],
        assumptions=[
            "The objective evaluator is frozen and shared by all policy arms."
        ],
        mechanism_model=(
            "Diverse branches reduce premature commitment while multi-fidelity "
            "screens reserve full budget for evidence-bearing candidates."
        ),
        nearest_work_tension=(
            "Existing tree-search systems report gains without a result-blind, "
            "budget-matched causal decomposition of certificate, diversity, and memory."
        ),
        main_claim=(
            "The portfolio policy increases confirmed task-level success over "
            "a budget-matched linear self-loop."
        ),
        falsifier=(
            "The preregistered confirmatory interval does not clear the meaningful "
            "effect threshold or any hard evidence gate fails."
        ),
        failure_update=(
            "A failed endpoint rejects this portfolio policy under the frozen task "
            "distribution and retains branch-level diagnostics for a new certificate."
        ),
        minimal_decisive_test=(
            "Run budget-matched policies on disjoint development and confirmatory tasks."
        ),
        primary_metric=PrimaryMetricSpec(
            metric_id="confirmed-task-success",
            name="Confirmed scientific task success rate",
            direction=MetricDirection.MAXIMIZE,
            unit="proportion",
            meaningful_effect_threshold=0.10,
            evaluator_description=(
                "Deterministic conjunction of effect, reproduction, evidence, and null gates."
            ),
        ),
        strong_baseline_ids=["linear-self-loop"],
        null_or_control_ids=["rule-only-null"],
        required_ablation_ids=[
            "without-certificate",
            "without-diversity",
            "without-memory",
        ],
        source_ids=["source-003", "source-001", "source-002"],
        power_plan=ProspectivePowerPlan(
            analysis_unit="independent research task",
            confirmatory_independent_unit_count=6,
            within_unit_repeat_count=3,
            target_power=0.80,
            alpha=0.05,
            minimum_detectable_effect=0.10,
            uncertainty_method="paired task-level bootstrap",
            bootstrap_resamples=20_000,
            heterogeneity_plan=(
                "Report task-level effects and a failure-aware aggregate interval."
            ),
            analysis_artifact_hash=_sha("prospective-power-analysis"),
        ),
        data_split=ResearchDataSplit(
            development_unit_ids=["dev-003", "dev-001", "dev-002"],
            confirmatory_unit_ids=[
                "confirm-006",
                "confirm-001",
                "confirm-004",
                "confirm-002",
                "confirm-005",
                "confirm-003",
            ],
            confirmatory_access_policy=(
                "Only the independent confirmatory runner may reveal each task once."
            ),
        ),
        budget=ResearchBudget(
            max_cost_usd=100.0,
            max_walltime_minutes=1_000,
            max_model_tokens=100_000,
            max_trials=100,
        ),
        publication_endpoint=PublicationEndpoint.SYSTEM_CONTRIBUTION,
        endpoint_rationale=(
            "The main claim concerns the causal effect of a research-system policy."
        ),
    )


def _baseline_plan() -> BaselineReproductionPlan:
    return BaselineReproductionPlan.create(
        baseline_id="linear-self-loop",
        source_ids=["source-002", "source-001"],
        expected_metric_id="confirmed-task-success",
        reproduction_tolerance=0.01,
        exact_command_hash=_sha("baseline-command"),
        environment_hash=_sha("baseline-environment"),
    )


def _baseline_evidence(
    plan: BaselineReproductionPlan,
) -> BaselineReproductionEvidence:
    return BaselineReproductionEvidence.create(
        plan_hash=plan.plan_hash,
        baseline_id=plan.baseline_id,
        metric_id=plan.expected_metric_id,
        observed_value=0.25,
        within_tolerance=True,
        artifact_hashes=[
            _sha("baseline-code"),
            _sha("baseline-metrics"),
            _sha("baseline-raw"),
        ],
        reproduction_passed=True,
    )


def _opportunity(
    *,
    with_reproduction: bool = True,
    license_clear: bool = True,
) -> ResearchOpportunity:
    certificate = _certificate()
    plan = _baseline_plan()
    return ResearchOpportunity.create(
        opportunity_id="opportunity-search-policy-v1",
        certificate=certificate,
        sources=list(reversed(_sources())),
        nearest_work=[
            NearestWorkDelta(
                source_id=f"source-{index:03d}",
                shared_scope="Automated research policy search.",
                claimed_delta=(
                    "Adds a result-blind, budget-matched causal portfolio comparison."
                ),
                overlap_risk="Search operators and task suites may partially overlap.",
                decisive_comparison=(
                    "Compare confirmed task-level success under the same evaluator and budget."
                ),
            )
            for index in (3, 1, 2)
        ],
        objective_evaluator_hash=_sha("objective-evaluator"),
        baseline_plan=plan,
        baseline_smoke_passed=True,
        baseline_reproduction=(
            _baseline_evidence(plan) if with_reproduction else None
        ),
        data_available=True,
        license_clear=license_clear,
        compute_feasible=True,
        source_snapshot_complete=True,
    )


def _branches() -> list[PortfolioBranch]:
    families = (
        "certificate-gate",
        "diversity-search",
        "multi-fidelity",
        "cross-branch-memory",
        "certificate-gate",
        "diversity-search",
        "multi-fidelity",
        "null-rule",
    )
    branches: list[PortfolioBranch] = []
    for index, family in enumerate(families, start=1):
        arm_kind = (
            PortfolioArmKind.NULL_OR_RULE
            if family == "null-rule"
            else PortfolioArmKind.MECHANISM
        )
        branches.append(
            PortfolioBranch(
                branch_id=f"branch-{index:02d}",
                mechanism_family=family,
                arm_kind=arm_kind,
                hypothesis=f"Branch {index} has an executable frozen delta.",
                exact_delta=(
                    "Use the rule-only baseline without a learned research delta."
                    if arm_kind is PortfolioArmKind.NULL_OR_RULE
                    else f"Apply only the {family} intervention variant {index}."
                ),
                source_ids=["source-001", "source-002"],
                generation_evidence_hash=_sha(f"branch-generation-{index}"),
                budget=BranchBudget(
                    max_cost_usd=1.0,
                    max_walltime_minutes=10,
                    max_model_tokens=100,
                    max_trials=1,
                ),
            )
        )
    return branches


def _stages() -> list[FidelityStageSpec]:
    return [
        FidelityStageSpec(
            kind=FidelityKind.F0_STATIC,
            max_survivors=8,
            minimum_independent_units=0,
            budget_fraction=0.10,
            promotion_rule="Pass source, license, security, and static contract checks.",
        ),
        FidelityStageSpec(
            kind=FidelityKind.F1_MINIMAL,
            max_survivors=6,
            minimum_independent_units=1,
            budget_fraction=0.20,
            promotion_rule="Pass one bounded executable development unit.",
        ),
        FidelityStageSpec(
            kind=FidelityKind.F2_MULTI_TASK,
            max_survivors=3,
            minimum_independent_units=3,
            budget_fraction=0.30,
            promotion_rule="Rank three-unit evidence under the frozen metric.",
        ),
        FidelityStageSpec(
            kind=FidelityKind.F3_FULL_DEVELOPMENT,
            max_survivors=1,
            minimum_independent_units=3,
            budget_fraction=0.40,
            promotion_rule="Require full development replication, null, and ablation evidence.",
        ),
    ]


def _portfolio() -> PortfolioSpec:
    opportunity = _opportunity()
    assessment = assess_research_opportunity(
        opportunity,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )
    return PortfolioSpec.create(
        portfolio_id="portfolio-search-policy-v1",
        opportunity=opportunity,
        opportunity_assessment=assessment,
        branches=_branches(),
        fidelity_stages=_stages(),
        total_budget=ResearchBudget(
            max_cost_usd=10.0,
            max_walltime_minutes=100,
            max_model_tokens=1_000,
            max_trials=20,
        ),
        exploration_quota=2,
        survival_rule=(
            "Promote by frozen objective evidence while reserving two F1 slots "
            "for mechanism-family diversity."
        ),
        selection_metric_id="confirmed-task-success",
    )


def test_certificate_is_result_blind_content_addressed_and_round_trips() -> None:
    certificate = _certificate()

    assert certificate.source_ids == ["source-001", "source-002", "source-003"]
    assert certificate.data_split.development_unit_ids == [
        "dev-001",
        "dev-002",
        "dev-003",
    ]
    assert certificate.certificate_hash == certificate.calculated_hash()
    assert not certificate.result_observed
    assert not certificate.external_submission_authorized
    assert (
        ResearchQuestionCertificate.model_validate_json(
            certificate.model_dump_json()
        )
        == certificate
    )


@given(
    st.permutations(["source-001", "source-002", "source-003"]),
    st.permutations(["without-certificate", "without-diversity", "without-memory"]),
)
def test_certificate_hash_is_invariant_to_set_like_input_order(
    source_ids: list[str],
    ablation_ids: list[str],
) -> None:
    certificate = _certificate()
    values = certificate.model_dump(mode="python", exclude={"certificate_hash"})
    values["source_ids"] = source_ids
    values["required_ablation_ids"] = ablation_ids

    reordered = ResearchQuestionCertificate.create(**values)

    assert reordered == certificate
    assert reordered.certificate_hash == certificate.certificate_hash


def test_certificate_rejects_overlap_count_drift_and_external_actions() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        ResearchDataSplit(
            development_unit_ids=["shared", "dev-002", "dev-003"],
            confirmatory_unit_ids=[
                "shared",
                "confirm-002",
                "confirm-003",
                "confirm-004",
                "confirm-005",
                "confirm-006",
            ],
            confirmatory_access_policy="Reveal once.",
        )

    payload = _certificate().model_dump(mode="json")
    payload["power_plan"]["confirmatory_independent_unit_count"] = 7
    payload["certificate_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "certificate_hash"}
    )
    with pytest.raises(ValidationError, match="must match"):
        ResearchQuestionCertificate.model_validate(payload)

    payload = _certificate().model_dump(mode="json")
    payload["external_submission_authorized"] = True
    with pytest.raises(ValidationError):
        ResearchQuestionCertificate.model_validate(payload)


def test_nested_certificate_tampering_is_detected_on_load() -> None:
    payload = json.loads(_certificate().model_dump_json())
    payload["primary_metric"]["meaningful_effect_threshold"] = 0.001

    with pytest.raises(ValidationError, match="certificate_hash mismatch"):
        ResearchQuestionCertificate.model_validate(payload)


def test_opportunity_separates_track_selection_from_novelty_readiness() -> None:
    opportunity = _opportunity(with_reproduction=False)
    track = assess_research_opportunity(
        opportunity,
        stage=OpportunityStage.TRACK_SELECTION,
    )
    novelty = assess_research_opportunity(
        opportunity,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )

    assert track.admitted
    assert not novelty.admitted
    assert novelty.blockers == [
        "baseline_clean_room",
        "baseline_reproduced",
    ]
    assert not novelty.weighted_score_used
    assert not novelty.llm_review_can_override


def test_opportunity_is_conjunctive_and_binds_baseline_evidence() -> None:
    blocked = _opportunity(license_clear=False)
    blocked_assessment = assess_research_opportunity(
        blocked,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )
    admitted = _opportunity()
    admitted_assessment = assess_research_opportunity(
        admitted,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )

    assert blocked_assessment.blockers == ["license_clear"]
    assert not blocked_assessment.admitted
    assert admitted_assessment.admitted
    assert admitted_assessment.blockers == []
    assert admitted.baseline_reproduction is not None
    assert (
        admitted.baseline_reproduction.plan_hash
        == admitted.baseline_plan.plan_hash
    )


def test_in_memory_contract_mutation_is_rejected_before_assessment() -> None:
    opportunity = _opportunity()
    tampered_opportunity = opportunity.model_copy(
        update={"license_clear": False}
    )
    with pytest.raises(
        PortfolioIntegrityError,
        match="opportunity_hash mismatch",
    ):
        assess_research_opportunity(
            tampered_opportunity,
            stage=OpportunityStage.NOVELTY_SEARCH,
        )

    portfolio = _portfolio()
    tampered_branches = list(portfolio.branches)
    tampered_branches[0] = tampered_branches[0].model_copy(
        update={"hypothesis": "Changed after the portfolio freeze."}
    )
    tampered_portfolio = portfolio.model_copy(
        update={"branches": tampered_branches}
    )
    with pytest.raises(PortfolioIntegrityError, match="portfolio_hash mismatch"):
        assess_portfolio(tampered_portfolio)


def test_opportunity_rejects_unknown_sources_and_nested_tampering() -> None:
    values = _opportunity().model_dump(
        mode="python",
        exclude={"opportunity_hash"},
    )
    values["nearest_work"][0] = NearestWorkDelta(
        source_id="source-unknown",
        shared_scope="Unknown source.",
        claimed_delta="Unknown delta.",
        overlap_risk="Unknown risk.",
        decisive_comparison="Unknown comparison.",
    )
    with pytest.raises(ValidationError, match="unknown opportunity sources"):
        ResearchOpportunity.create(**values)

    payload = json.loads(_opportunity().model_dump_json())
    payload["certificate"]["main_claim"] = "Tampered claim."
    with pytest.raises(ValidationError, match="certificate_hash mismatch"):
        ResearchOpportunity.model_validate(payload)


def test_valid_portfolio_has_diversity_null_arm_fidelity_and_hard_audit() -> None:
    portfolio = _portfolio()
    assessment = assess_portfolio(portfolio)

    assert len(portfolio.branches) == 8
    assert [stage.kind for stage in portfolio.fidelity_stages] == list(
        FidelityKind
    )
    assert assessment.admitted
    assert assessment.blockers == []
    assert all(assessment.checks.values())
    assert not assessment.weighted_score_used
    assert not portfolio.sealed_confirmatory_evidence_visible
    assert portfolio.portfolio_hash == portfolio.calculated_hash()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("homogeneous", "three distinct mechanism families"),
        ("no-null", "null/rule branch"),
        ("insufficient-budget", "cost reservations"),
        ("wrong-stage", "ordered F0 through F3"),
    ],
)
def test_portfolio_rejects_invalid_search_design(
    mutation: str,
    message: str,
) -> None:
    portfolio = _portfolio()
    values = portfolio.model_dump(mode="python", exclude={"portfolio_hash"})
    if mutation == "homogeneous":
        values["branches"] = [
            branch.model_copy(
                update={
                    "mechanism_family": (
                        "null-rule"
                        if branch.arm_kind is PortfolioArmKind.NULL_OR_RULE
                        else "one-family"
                    )
                }
            )
            for branch in portfolio.branches
        ]
    elif mutation == "no-null":
        values["branches"] = [
            branch.model_copy(
                update={
                    "arm_kind": PortfolioArmKind.MECHANISM,
                    "mechanism_family": f"family-{index % 3}",
                }
            )
            for index, branch in enumerate(portfolio.branches)
        ]
    elif mutation == "insufficient-budget":
        values["total_budget"] = portfolio.total_budget.model_copy(
            update={"max_cost_usd": 1.0}
        )
    else:
        stages = list(portfolio.fidelity_stages)
        stages[1], stages[2] = stages[2], stages[1]
        values["fidelity_stages"] = stages

    with pytest.raises(ValidationError, match=message):
        PortfolioSpec.create(**values)


def test_portfolio_rejects_blocked_opportunity_and_confirmatory_visibility() -> None:
    blocked_opportunity = _opportunity(license_clear=False)
    blocked_assessment = assess_research_opportunity(
        blocked_opportunity,
        stage=OpportunityStage.NOVELTY_SEARCH,
    )
    values = _portfolio().model_dump(mode="python", exclude={"portfolio_hash"})
    values["opportunity"] = blocked_opportunity
    values["opportunity_assessment"] = blocked_assessment
    with pytest.raises(ValidationError, match="blocked research opportunity"):
        PortfolioSpec.create(**values)

    payload = _portfolio().model_dump(mode="json")
    payload["sealed_confirmatory_evidence_visible"] = True
    with pytest.raises(ValidationError):
        PortfolioSpec.model_validate(payload)


def test_portfolio_tampering_and_endpoint_route_changes_fail_closed() -> None:
    payload = json.loads(_portfolio().model_dump_json())
    payload["branches"][0]["hypothesis"] = "Post-result rewritten hypothesis."
    with pytest.raises(ValidationError, match="portfolio_hash mismatch"):
        PortfolioSpec.model_validate(payload)

    payload = json.loads(_portfolio().model_dump_json())
    payload["opportunity"]["certificate"]["publication_endpoint"] = (
        PublicationEndpoint.DIAGNOSTIC_NEGATIVE.value
    )
    with pytest.raises(ValidationError, match="certificate_hash mismatch"):
        PortfolioSpec.model_validate(payload)


def test_portfolio_json_schemas_are_complete_and_deterministic() -> None:
    first = portfolio_contract_json_schemas()
    second = portfolio_contract_json_schemas()

    assert first == second
    assert set(first) >= {
        "ResearchQuestionCertificate",
        "ResearchOpportunity",
        "OpportunityAssessment",
        "PortfolioSpec",
        "PortfolioAssessment",
    }
    assert first["ResearchQuestionCertificate"]["additionalProperties"] is False
    assert first["PortfolioSpec"]["additionalProperties"] is False
    json.dumps(first, sort_keys=True)
