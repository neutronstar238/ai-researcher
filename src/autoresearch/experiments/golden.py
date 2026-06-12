"""Golden regression test suites for controlled strategy evolution."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.schemas import StrategyCard, ValidationStatus


class GoldenTestDomain(str, Enum):
    """Regression domains required before strategy comparison."""

    LITERATURE_RETRIEVAL = "literature_retrieval"
    CONFIG_PARSING = "config_parsing"
    SANDBOX_DENIAL = "sandbox_denial"
    RESULT_VALIDATION = "result_validation"
    CITATION_VALIDATION = "citation_validation"
    REPORT_GENERATION = "report_generation"


class GoldenTestCase(BaseModel):
    """One fixed golden task definition."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    domain: GoldenTestDomain
    description: str
    expected_checks: tuple[str, ...] = Field(min_length=1)
    replay_case_id: str | None = None
    required: bool = True


class GoldenTestObservation(BaseModel):
    """Observed result for a golden task under a strategy."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: ValidationStatus
    score: float | None = None
    notes: str = ""


class GoldenTestResult(BaseModel):
    """Evaluation result for one golden task."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    domain: GoldenTestDomain
    status: ValidationStatus
    passed: bool
    notes: str = ""


class GoldenSuite(BaseModel):
    """Fixed golden test suite."""

    model_config = ConfigDict(extra="forbid")

    suite_id: str
    cases: tuple[GoldenTestCase, ...]

    def required_domains(self) -> set[GoldenTestDomain]:
        """Return the domains covered by required cases."""

        return {case.domain for case in self.cases if case.required}


class GoldenSuiteEvaluation(BaseModel):
    """Stable-strategy golden gate result."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    strategy_release_status: str
    suite_id: str
    passed: bool
    results: tuple[GoldenTestResult, ...]
    failed_case_ids: tuple[str, ...]


REQUIRED_GOLDEN_DOMAINS = frozenset(GoldenTestDomain)


def build_default_golden_suite() -> GoldenSuite:
    """Return the fixed MVP golden suite for offline regression checks."""

    return GoldenSuite(
        suite_id="golden_mvp_v1",
        cases=(
            GoldenTestCase(
                case_id="golden_literature_retrieval",
                domain=GoldenTestDomain.LITERATURE_RETRIEVAL,
                description="Fixture literature retrieval returns deduplicated source-backed papers.",
                expected_checks=("deduplication", "source_backing", "rate_limit_safe"),
            ),
            GoldenTestCase(
                case_id="golden_config_parsing",
                domain=GoldenTestDomain.CONFIG_PARSING,
                description="Config parser round-trips supported JSON, YAML, and TOML formats.",
                expected_checks=("round_trip", "schema_validation", "syntax_errors"),
            ),
            GoldenTestCase(
                case_id="golden_sandbox_denial",
                domain=GoldenTestDomain.SANDBOX_DENIAL,
                description="Sandbox policy denies path traversal and unsafe project-root access.",
                expected_checks=("deny_traversal", "deny_secret_access", "audit_block"),
            ),
            GoldenTestCase(
                case_id="golden_result_validation",
                domain=GoldenTestDomain.RESULT_VALIDATION,
                description="Result validation rejects missing metrics and invalid bounds.",
                expected_checks=("metric_presence", "metric_bounds", "artifact_existence"),
            ),
            GoldenTestCase(
                case_id="golden_citation_validation",
                domain=GoldenTestDomain.CITATION_VALIDATION,
                description="Citation validator blocks malformed or unsupported source references.",
                expected_checks=("doi_url_validation", "blocked_status", "bibtex_output"),
            ),
            GoldenTestCase(
                case_id="golden_report_generation",
                domain=GoldenTestDomain.REPORT_GENERATION,
                description="Report generator refuses quantitative claims without evidence binding.",
                expected_checks=("evidence_binding", "claim_trace", "markdown_sections"),
            ),
        ),
    )


def evaluate_golden_suite(
    *,
    strategy: StrategyCard,
    suite: GoldenSuite,
    observations: tuple[GoldenTestObservation, ...],
) -> GoldenSuiteEvaluation:
    """Evaluate whether a stable strategy passes every required golden case."""

    by_case_id = {observation.case_id: observation for observation in observations}
    results: list[GoldenTestResult] = []
    failed_case_ids: list[str] = []
    stable_strategy = strategy.release_status == "stable"

    for case in suite.cases:
        observation = by_case_id.get(case.case_id)
        if observation is None:
            result = GoldenTestResult(
                case_id=case.case_id,
                domain=case.domain,
                status=ValidationStatus.FAILED,
                passed=False,
                notes="missing golden observation",
            )
        else:
            passed = stable_strategy and observation.status is ValidationStatus.PASSED
            result = GoldenTestResult(
                case_id=case.case_id,
                domain=case.domain,
                status=observation.status,
                passed=passed,
                notes=observation.notes,
            )
        results.append(result)
        if case.required and not result.passed:
            failed_case_ids.append(case.case_id)

    return GoldenSuiteEvaluation(
        strategy_id=strategy.id,
        strategy_release_status=strategy.release_status,
        suite_id=suite.suite_id,
        passed=not failed_case_ids,
        results=tuple(results),
        failed_case_ids=tuple(failed_case_ids),
    )
