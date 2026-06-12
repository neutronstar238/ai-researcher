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
from .results import ResultCollectionError, collect_result_bundle
from .review import (
    CodeReviewFinding,
    CodeReviewResult,
    quarantine_unsafe_experiment,
    review_generated_code,
)
from .sandbox import SandboxAccessMode, SandboxPathDecision, SandboxPathPolicy
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
    "NetworkDecision",
    "RecurringFailurePattern",
    "ResultCollectionError",
    "RestrictedNetworkPolicy",
    "SandboxAccessMode",
    "SandboxPathDecision",
    "SandboxPathPolicy",
    "StatisticalCheck",
    "StatisticalNote",
    "ValidationIssue",
    "ValidationReport",
    "bind_metrics_to_evidence",
    "classify_failure_category",
    "collect_result_bundle",
    "create_tabular_baseline_task",
    "create_text_classifier_stub_task",
    "default_network_policy",
    "execute_experiment_task",
    "evaluate_budget_gate",
    "generate_tabular_baseline_demo",
    "generate_text_classifier_stub_demo",
    "generate_experiment_directory",
    "network_enforcement_note",
    "plan_ablation_matrix",
    "plan_experiment_tasks",
    "quarantine_unsafe_experiment",
    "record_failed_run_as_knowledge",
    "require_evidence_for_metrics",
    "review_generated_code",
    "reproduce_tabular_baseline",
    "run_mvp_acceptance",
    "run_scientistbench_demo",
    "update_recurring_failure_patterns",
    "validate_result_bundle",
]
