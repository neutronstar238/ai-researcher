"""Research candidate and hypothesis workflow helpers."""

from .approval import ApprovalRecord, ProjectAgentContext, create_project_from_approved_candidate
from .candidates import CandidateGenerationConfig, generate_research_candidates
from .hypotheses import HypothesisGenerationConfig, generate_hypotheses

__all__ = [
    "ApprovalRecord",
    "CandidateGenerationConfig",
    "HypothesisGenerationConfig",
    "ProjectAgentContext",
    "create_project_from_approved_candidate",
    "generate_hypotheses",
    "generate_research_candidates",
]
