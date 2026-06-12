from autoresearch.experiments import (
    REQUIRED_GOLDEN_DOMAINS,
    GoldenTestObservation,
    build_default_golden_suite,
    evaluate_golden_suite,
)
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_default_golden_suite_covers_required_regression_domains() -> None:
    suite = build_default_golden_suite()

    assert suite.required_domains() == set(REQUIRED_GOLDEN_DOMAINS)
    assert len(suite.cases) == 6
    assert all(case.expected_checks for case in suite.cases)


def test_current_stable_strategy_passes_all_golden_tests_before_comparison() -> None:
    suite = build_default_golden_suite()
    strategy = StrategyCard(
        id="strategy_stable_retrieval_v1",
        strategy_type="retrieval_policy",
        content="Stable evidence-first retrieval policy.",
        release_status="stable",
        golden_test_status=ValidationStatus.PASSED,
    )
    observations = tuple(
        GoldenTestObservation(case_id=case.case_id, status=ValidationStatus.PASSED)
        for case in suite.cases
    )

    evaluation = evaluate_golden_suite(
        strategy=strategy,
        suite=suite,
        observations=observations,
    )

    assert evaluation.passed is True
    assert evaluation.failed_case_ids == ()
    assert all(result.passed for result in evaluation.results)


def test_golden_suite_fails_for_missing_or_nonpassing_cases() -> None:
    suite = build_default_golden_suite()
    strategy = StrategyCard(
        id="strategy_stable_retrieval_v1",
        strategy_type="retrieval_policy",
        content="Stable evidence-first retrieval policy.",
        release_status="stable",
    )
    observations = tuple(
        GoldenTestObservation(
            case_id=case.case_id,
            status=ValidationStatus.WARNING
            if case.case_id == "golden_citation_validation"
            else ValidationStatus.PASSED,
        )
        for case in suite.cases
        if case.case_id != "golden_report_generation"
    )

    evaluation = evaluate_golden_suite(
        strategy=strategy,
        suite=suite,
        observations=observations,
    )

    assert evaluation.passed is False
    assert set(evaluation.failed_case_ids) == {
        "golden_citation_validation",
        "golden_report_generation",
    }


def test_golden_suite_fails_for_candidate_before_stable_release() -> None:
    suite = build_default_golden_suite()
    strategy = StrategyCard(
        id="strategy_candidate_retrieval_v2",
        strategy_type="retrieval_policy",
        content="Candidate evidence-first retrieval policy.",
        release_status="shadow",
    )
    observations = tuple(
        GoldenTestObservation(case_id=case.case_id, status=ValidationStatus.PASSED)
        for case in suite.cases
    )

    evaluation = evaluate_golden_suite(
        strategy=strategy,
        suite=suite,
        observations=observations,
    )

    assert evaluation.passed is False
    assert evaluation.failed_case_ids == tuple(case.case_id for case in suite.cases)
