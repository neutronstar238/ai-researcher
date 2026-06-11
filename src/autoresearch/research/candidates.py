"""Deterministic research candidate generation from retrieved literature."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from autoresearch.schemas import CandidateStatus, DocumentRecord, ResearchCandidate

METHOD_TERMS = (
    "transformer",
    "retrieval",
    "prompting",
    "graph neural network",
    "diffusion",
    "reinforcement learning",
    "self-supervised",
    "agent",
    "evidence graph",
)
LIMITATION_TERMS = (
    "limited reproducibility",
    "high cost",
    "weak evidence",
    "data scarcity",
    "latency",
    "poor generalization",
    "limited evaluation",
    "citation hallucination",
)
DATASET_PATTERN = re.compile(
    r"\b(?:on|using|with|for)\s+(?:the\s+)?([a-z0-9][a-z0-9 -]{2,40}?)\s+"
    r"(?:dataset|benchmark|corpus)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateGenerationConfig:
    """Tuning knobs for deterministic candidate generation."""

    max_candidates: int = 3
    min_ready_evidence_refs: int = 2


@dataclass(frozen=True)
class _DocumentSignal:
    document: DocumentRecord
    methods: tuple[str, ...]
    limitations: tuple[str, ...]
    datasets: tuple[str, ...]


@dataclass(frozen=True)
class _Cluster:
    key: str
    method: str
    limitation: str
    dataset: str
    signals: tuple[_DocumentSignal, ...]


def generate_research_candidates(
    documents: list[DocumentRecord],
    *,
    config: CandidateGenerationConfig = CandidateGenerationConfig(),
) -> list[ResearchCandidate]:
    """Generate ranked research candidates from retrieved literature metadata."""

    signals = [_extract_signal(document) for document in documents]
    clusters = _cluster_signals(signals)
    candidates = [_candidate_from_cluster(cluster, len(documents), config) for cluster in clusters]
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.metadata["rank_score"],
            candidate.title,
        ),
    )[: config.max_candidates]


def _extract_signal(document: DocumentRecord) -> _DocumentSignal:
    text = f"{document.title} {document.abstract or ''}".casefold()
    methods = tuple(term for term in METHOD_TERMS if term in text)
    limitations = tuple(term for term in LIMITATION_TERMS if term in text)
    datasets = _extract_datasets(text)

    return _DocumentSignal(
        document=document,
        methods=methods or ("method",),
        limitations=limitations or ("open limitation",),
        datasets=datasets or ("available benchmark",),
    )


def _extract_datasets(text: str) -> tuple[str, ...]:
    datasets: set[str] = set()
    for match in DATASET_PATTERN.finditer(text):
        value = match.group(1).strip().casefold()
        if " on " in value:
            value = value.rsplit(" on ", 1)[1]
        value = value.removeprefix("the ")
        datasets.add(value)
    return tuple(sorted(datasets))


def _cluster_signals(signals: list[_DocumentSignal]) -> list[_Cluster]:
    grouped: dict[str, list[_DocumentSignal]] = defaultdict(list)
    labels: dict[str, tuple[str, str, str]] = {}

    for signal in signals:
        method = signal.methods[0]
        limitation = signal.limitations[0]
        dataset = signal.datasets[0]
        key = f"{method}|{limitation}|{dataset}"
        grouped[key].append(signal)
        labels[key] = (method, limitation, dataset)

    clusters = [
        _Cluster(
            key=key,
            method=labels[key][0],
            limitation=labels[key][1],
            dataset=labels[key][2],
            signals=tuple(value),
        )
        for key, value in grouped.items()
    ]
    return sorted(clusters, key=lambda cluster: (-len(cluster.signals), cluster.key))


def _candidate_from_cluster(
    cluster: _Cluster,
    total_documents: int,
    config: CandidateGenerationConfig,
) -> ResearchCandidate:
    evidence_refs = sorted(signal.document.id for signal in cluster.signals)
    related_document_ids = evidence_refs.copy()
    evidence_count = len(evidence_refs)
    coverage = evidence_count / max(total_documents, 1)
    method_frequency = Counter(signal.methods[0] for signal in cluster.signals)[cluster.method]
    dataset_specific = cluster.dataset != "available benchmark"
    limitation_specific = cluster.limitation != "open limitation"
    estimated_cost = _estimate_cost(cluster)

    novelty_score = _clamp(0.45 + 0.15 * limitation_specific + 0.10 * dataset_specific + 0.10 * coverage)
    feasibility_score = _clamp(0.85 - estimated_cost * 0.20 + 0.05 * dataset_specific)
    impact_score = _clamp(0.40 + 0.20 * coverage + 0.10 * min(method_frequency, 3))
    rank_score = _clamp(
        novelty_score * 0.35
        + feasibility_score * 0.25
        + impact_score * 0.25
        + min(coverage, 1.0) * 0.15
        - estimated_cost * 0.05
    )
    status = (
        CandidateStatus.READY_FOR_REVIEW
        if evidence_count >= config.min_ready_evidence_refs
        else CandidateStatus.DRAFT
    )

    return ResearchCandidate(
        title=_candidate_title(cluster),
        description=(
            f"Explore whether {cluster.method} can address {cluster.limitation} "
            f"on {cluster.dataset} using evidence from {evidence_count} retrieved papers."
        ),
        research_gap=(
            f"Repeated literature signals mention {cluster.limitation} around "
            f"{cluster.method} with {cluster.dataset}."
        ),
        novelty_score=novelty_score,
        feasibility_score=feasibility_score,
        impact_score=impact_score,
        evidence_refs=evidence_refs,
        related_document_ids=related_document_ids,
        status=status,
        metadata={
            "cluster_key": cluster.key,
            "dataset": cluster.dataset,
            "method": cluster.method,
            "limitation": cluster.limitation,
            "evidence_coverage": round(coverage, 4),
            "estimated_cost": estimated_cost,
            "rank_score": round(rank_score, 4),
        },
    )


def _candidate_title(cluster: _Cluster) -> str:
    return (
        f"Reduce {cluster.limitation} in {cluster.method} "
        f"on {cluster.dataset}"
    ).title()


def _estimate_cost(cluster: _Cluster) -> float:
    text = f"{cluster.method} {cluster.dataset} {cluster.limitation}"
    if "diffusion" in text or "reinforcement learning" in text:
        return 0.8
    if "transformer" in text or "graph neural network" in text:
        return 0.6
    return 0.3


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)
