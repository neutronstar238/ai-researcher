"""Experiment planning and execution helpers."""

from .acceptance import AcceptanceRunResult, run_mvp_acceptance
from .baselines import BaselineReproductionResult, reproduce_tabular_baseline
from .budget import (
    BudgetGateConfig,
    BudgetGateDecision,
    BudgetGateStatus,
    evaluate_budget_gate,
)
from .demo_workflow import DemoWorkflowResult, run_scientistbench_demo
from .demos import (
    create_tabular_baseline_task,
    create_text_classifier_stub_task,
    generate_tabular_baseline_demo,
    generate_text_classifier_stub_demo,
)
from .evidence import (
    EvidenceBindingError,
    bind_metrics_to_evidence,
    require_evidence_for_metrics,
)
from .executor import execute_experiment_task
from .failures import (
    FailureKnowledgeRecord,
    RecurringFailurePattern,
    classify_failure_category,
    record_failed_run_as_knowledge,
    update_recurring_failure_patterns,
)
from .generator import generate_experiment_directory
from .golden import (
    REQUIRED_GOLDEN_DOMAINS,
    GoldenSuite,
    GoldenSuiteEvaluation,
    GoldenTestCase,
    GoldenTestDomain,
    GoldenTestObservation,
    GoldenTestResult,
    build_default_golden_suite,
    evaluate_golden_suite,
)
from .network import (
    NetworkDecision,
    RestrictedNetworkPolicy,
    default_network_policy,
    network_enforcement_note,
)
from .planner import (
    AblationPlanningConfig,
    AblationPlanningError,
    AblationVariable,
    ExperimentPlanningConfig,
    plan_ablation_matrix,
    plan_experiment_tasks,
)
from .promotion import (
    StrategyPromotionApproval,
    StrategyPromotionDecision,
    StrategyPromotionInput,
    StrategyPromotionStatus,
    promote_strategy_to_gray_release,
)
from .replay import (
    ReplayCase,
    ReplayDataset,
    build_replay_case,
    load_replay_dataset,
    write_replay_dataset,
)
from .results import ResultCollectionError, collect_result_bundle
from .review import (
    CodeReviewFinding,
    CodeReviewResult,
    quarantine_unsafe_experiment,
    review_generated_code,
)
from .reward import (
    StrategyRewardInput,
    StrategyRewardResult,
    StrategyRewardWeights,
    calculate_strategy_reward,
)
from .sandbox import SandboxAccessMode, SandboxPathDecision, SandboxPathPolicy
from .shadow import (
    ShadowEvaluationRecord,
    ShadowProposal,
    run_shadow_evaluation,
    write_shadow_evaluation,
)
from .validation import (
    StatisticalCheck,
    StatisticalNote,
    ValidationIssue,
    ValidationReport,
    validate_result_bundle,
)

__all__ = [
    "AcceptanceRunResult",
    "AblationPlanningConfig",
    "AblationPlanningError",
    "AblationVariable",
    "BaselineReproductionResult",
    "BudgetGateConfig",
    "BudgetGateDecision",
    "BudgetGateStatus",
    "CodeReviewFinding",
    "CodeReviewResult",
    "DemoWorkflowResult",
    "EvidenceBindingError",
    "ExperimentPlanningConfig",
    "FailureKnowledgeRecord",
    "GoldenSuite",
    "GoldenSuiteEvaluation",
    "GoldenTestCase",
    "GoldenTestDomain",
    "GoldenTestObservation",
    "GoldenTestResult",
    "NetworkDecision",
    "REQUIRED_GOLDEN_DOMAINS",
    "RecurringFailurePattern",
    "ReplayCase",
    "ReplayDataset",
    "ResultCollectionError",
    "RestrictedNetworkPolicy",
    "SandboxAccessMode",
    "SandboxPathDecision",
    "SandboxPathPolicy",
    "ShadowEvaluationRecord",
    "ShadowProposal",
    "StatisticalCheck",
    "StatisticalNote",
    "StrategyPromotionApproval",
    "StrategyPromotionDecision",
    "StrategyPromotionInput",
    "StrategyPromotionStatus",
    "StrategyRewardInput",
    "StrategyRewardResult",
    "StrategyRewardWeights",
    "ValidationIssue",
    "ValidationReport",
    "bind_metrics_to_evidence",
    "build_replay_case",
    "build_default_golden_suite",
    "calculate_strategy_reward",
    "classify_failure_category",
    "collect_result_bundle",
    "create_tabular_baseline_task",
    "create_text_classifier_stub_task",
    "default_network_policy",
    "execute_experiment_task",
    "evaluate_budget_gate",
    "evaluate_golden_suite",
    "generate_tabular_baseline_demo",
    "generate_text_classifier_stub_demo",
    "generate_experiment_directory",
    "network_enforcement_note",
    "load_replay_dataset",
    "plan_ablation_matrix",
    "plan_experiment_tasks",
    "promote_strategy_to_gray_release",
    "quarantine_unsafe_experiment",
    "record_failed_run_as_knowledge",
    "require_evidence_for_metrics",
    "review_generated_code",
    "reproduce_tabular_baseline",
    "run_mvp_acceptance",
    "run_scientistbench_demo",
    "run_shadow_evaluation",
    "update_recurring_failure_patterns",
    "validate_result_bundle",
    "write_replay_dataset",
    "write_shadow_evaluation",
]
