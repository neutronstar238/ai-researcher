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
from .similarity import (
    ProjectSimilarityReport,
    SimilarityCheckConfig,
    SimilarityFetchRecord,
    SimilarityFinding,
    SimilarityQuery,
    UnsupportedSimilarityClaimError,
    generate_similarity_queries,
    link_similarity_report_to_project,
    run_project_similarity_check,
    validate_similarity_findings,
    validate_similarity_report_for_candidate,
)

__all__ = [
    "ApprovalRecord",
    "CandidateGenerationConfig",
    "CandidateLifecycleError",
    "CandidateVaultLinks",
    "HypothesisGenerationConfig",
    "ProjectAgentContext",
    "ProjectSimilarityReport",
    "SimilarityCheckConfig",
    "SimilarityFetchRecord",
    "SimilarityFinding",
    "SimilarityQuery",
    "TrendGapAnalysisConfig",
    "TrendGapUpdate",
    "UnsupportedSimilarityClaimError",
    "analyze_trends_and_gaps",
    "create_project_from_approved_candidate",
    "generate_similarity_queries",
    "generate_hypotheses",
    "generate_research_candidates",
    "link_similarity_report_to_project",
    "run_project_similarity_check",
    "store_candidate_lifecycle_entry",
    "transition_candidate_status",
    "validate_similarity_findings",
    "validate_similarity_report_for_candidate",
]
