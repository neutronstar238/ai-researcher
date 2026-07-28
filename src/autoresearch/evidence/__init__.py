"""Claim-evidence-source graph helpers."""

from typing import TYPE_CHECKING, Any

from .graph import (
    ClaimNode,
    ClaimStatus,
    EvidenceArtifact,
    EvidenceCoverageError,
    EvidenceGraph,
    EvidenceGraphError,
    EvidenceNode,
    EvidenceTrace,
    SourceNode,
)

if TYPE_CHECKING:
    from .provenance import CampaignRoundProvenance

_PROVENANCE_EXPORTS = {
    "CampaignRoundProvenance",
    "build_campaign_round_provenance",
    "project_evidence_v1",
}


def __getattr__(name: str) -> Any:
    """Load campaign provenance adapters without creating package import cycles."""
    if name in _PROVENANCE_EXPORTS:
        from . import provenance

        return getattr(provenance, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClaimNode",
    "ClaimStatus",
    "CampaignRoundProvenance",
    "EvidenceArtifact",
    "EvidenceCoverageError",
    "EvidenceGraph",
    "EvidenceGraphError",
    "EvidenceNode",
    "EvidenceTrace",
    "SourceNode",
    "build_campaign_round_provenance",
    "project_evidence_v1",
]
