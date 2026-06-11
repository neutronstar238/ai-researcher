"""JSON-backed claim-evidence-source graph for MVP evidence tracing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.schemas import ValidationStatus


class EvidenceGraphError(RuntimeError):
    """Raised when evidence graph references are missing or inconsistent."""


class ClaimNode(BaseModel):
    """A claim that must be traced to artifact-backed evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    project_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceNode(BaseModel):
    """Evidence connecting a claim to a source artifact."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    supports_claim: bool = True


class SourceNode(BaseModel):
    """A source behind one or more evidence artifacts."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    source_type: str = "experiment_run"


class EvidenceArtifact(BaseModel):
    """An artifact with a validation status used by evidence traces."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    artifact_type: str = "metrics"
    validation_status: ValidationStatus = ValidationStatus.PENDING


class EvidenceTrace(BaseModel):
    """Resolved path from a claim to an artifact and validation state."""

    model_config = ConfigDict(extra="forbid")

    claim: ClaimNode
    evidence: EvidenceNode
    source: SourceNode
    artifact: EvidenceArtifact
    validation_status: ValidationStatus


class EvidenceGraph(BaseModel):
    """In-memory evidence graph with JSON persistence for the MVP."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    claims: dict[str, ClaimNode] = Field(default_factory=dict)
    evidence: dict[str, EvidenceNode] = Field(default_factory=dict)
    sources: dict[str, SourceNode] = Field(default_factory=dict)
    artifacts: dict[str, EvidenceArtifact] = Field(default_factory=dict)

    def add_claim(self, claim: ClaimNode) -> None:
        """Add a claim node."""

        self._ensure_unique(self.claims, claim.id, "claim")
        self.claims[claim.id] = claim

    def add_source(self, source: SourceNode) -> None:
        """Add a source node."""

        self._ensure_unique(self.sources, source.id, "source")
        self.sources[source.id] = source

    def add_artifact(self, artifact: EvidenceArtifact) -> None:
        """Add an artifact node linked to an existing source."""

        if artifact.source_id not in self.sources:
            msg = f"artifact {artifact.id} references missing source {artifact.source_id}"
            raise EvidenceGraphError(msg)
        self._ensure_unique(self.artifacts, artifact.id, "artifact")
        self.artifacts[artifact.id] = artifact

    def link_evidence(self, evidence: EvidenceNode) -> None:
        """Add evidence and link it to its claim."""

        claim = self._get_claim(evidence.claim_id)
        source = self._get_source(evidence.source_id)
        artifact = self._get_artifact(evidence.artifact_id)
        if artifact.source_id != source.id:
            msg = (
                f"evidence {evidence.id} links source {source.id} to artifact "
                f"{artifact.id}, but the artifact belongs to source {artifact.source_id}"
            )
            raise EvidenceGraphError(msg)

        self._ensure_unique(self.evidence, evidence.id, "evidence")
        self.evidence[evidence.id] = evidence
        if evidence.id not in claim.evidence_ids:
            claim.evidence_ids.append(evidence.id)

    def trace_claim(self, claim_id: str) -> list[EvidenceTrace]:
        """Resolve all evidence paths for one claim."""

        claim = self._get_claim(claim_id)
        traces: list[EvidenceTrace] = []
        for evidence_id in sorted(claim.evidence_ids):
            evidence = self._get_evidence(evidence_id)
            source = self._get_source(evidence.source_id)
            artifact = self._get_artifact(evidence.artifact_id)
            if artifact.source_id != source.id:
                msg = (
                    f"artifact {artifact.id} belongs to source {artifact.source_id}, "
                    f"not evidence source {source.id}"
                )
                raise EvidenceGraphError(msg)
            traces.append(
                EvidenceTrace(
                    claim=claim,
                    evidence=evidence,
                    source=source,
                    artifact=artifact,
                    validation_status=artifact.validation_status,
                )
            )
        return traces

    def save_json(self, path: Path | str) -> Path:
        """Persist the graph as deterministic JSON."""

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output_path

    @classmethod
    def load_json(cls, path: Path | str) -> EvidenceGraph:
        """Load a graph from JSON."""

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def _get_claim(self, claim_id: str) -> ClaimNode:
        try:
            return self.claims[claim_id]
        except KeyError as exc:
            msg = f"missing claim {claim_id}"
            raise EvidenceGraphError(msg) from exc

    def _get_evidence(self, evidence_id: str) -> EvidenceNode:
        try:
            return self.evidence[evidence_id]
        except KeyError as exc:
            msg = f"missing evidence {evidence_id}"
            raise EvidenceGraphError(msg) from exc

    def _get_source(self, source_id: str) -> SourceNode:
        try:
            return self.sources[source_id]
        except KeyError as exc:
            msg = f"missing source {source_id}"
            raise EvidenceGraphError(msg) from exc

    def _get_artifact(self, artifact_id: str) -> EvidenceArtifact:
        try:
            return self.artifacts[artifact_id]
        except KeyError as exc:
            msg = f"missing artifact {artifact_id}"
            raise EvidenceGraphError(msg) from exc

    @staticmethod
    def _ensure_unique(collection: Mapping[str, object], node_id: str, kind: str) -> None:
        if node_id in collection:
            msg = f"duplicate {kind} id {node_id}"
            raise EvidenceGraphError(msg)
