"""Research candidate and hypothesis workflow helpers."""

from .approval import ApprovalRecord, ProjectAgentContext, create_project_from_approved_candidate
from .candidates import (
    CandidateGenerationConfig,
    CandidateLifecycleError,
    CandidateVaultLinks,
    TrendGapAnalysisConfig,
    TrendGapUpdate,
    analyze_trends_and_gaps,
    generate_research_candidates,
    store_candidate_lifecycle_entry,
    transition_candidate_status,
)
from .hypotheses import HypothesisGenerationConfig, generate_hypotheses

__all__ = [
    "ApprovalRecord",
    "CandidateGenerationConfig",
    "CandidateLifecycleError",
    "CandidateVaultLinks",
    "HypothesisGenerationConfig",
    "ProjectAgentContext",
    "TrendGapAnalysisConfig",
    "TrendGapUpdate",
    "analyze_trends_and_gaps",
    "create_project_from_approved_candidate",
    "generate_hypotheses",
    "generate_research_candidates",
    "store_candidate_lifecycle_entry",
    "transition_candidate_status",
]
