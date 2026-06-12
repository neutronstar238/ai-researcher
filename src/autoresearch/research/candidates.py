"""Deterministic research candidate generation from retrieved literature."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
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
DEFAULT_CANDIDATE_VAULT_ROOT = Path("autoresearch-vault")
LEGAL_CANDIDATE_STATUS_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.DRAFT: {
        CandidateStatus.READY_FOR_REVIEW,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
    },
    CandidateStatus.READY_FOR_REVIEW: {
        CandidateStatus.APPROVED,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
    },
    CandidateStatus.APPROVED: {
        CandidateStatus.ACTIVE,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
    },
    CandidateStatus.ACTIVE: {
        CandidateStatus.COMPLETED,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
    },
    CandidateStatus.COMPLETED: {CandidateStatus.ARCHIVED},
    CandidateStatus.REJECTED: {CandidateStatus.ARCHIVED},
    CandidateStatus.ARCHIVED: set(),
}


class CandidateLifecycleError(ValueError):
    """Raised when a candidate lifecycle transition is invalid."""


@dataclass(frozen=True)
class CandidateGenerationConfig:
    """Tuning knobs for deterministic candidate generation."""

    max_candidates: int = 3
    min_ready_evidence_refs: int = 2


@dataclass(frozen=True)
class CandidateVaultLinks:
    """Obsidian links attached to a persisted research candidate."""

    source_papers: tuple[str, ...] = ()
    topic_index_entries: tuple[str, ...] = ()
    prior_failures: tuple[str, ...] = ()
    useful_skills: tuple[str, ...] = ()
    strategy_cards: tuple[str, ...] = ()


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


def transition_candidate_status(
    candidate: ResearchCandidate,
    new_status: CandidateStatus,
) -> ResearchCandidate:
    """Return a candidate with a validated lifecycle status transition."""

    if candidate.status is new_status:
        return candidate
    allowed = LEGAL_CANDIDATE_STATUS_TRANSITIONS[candidate.status]
    if new_status not in allowed:
        msg = (
            f"illegal candidate status transition: "
            f"{candidate.status.value} -> {new_status.value}"
        )
        raise CandidateLifecycleError(msg)
    metadata = dict(candidate.metadata)
    history = list(metadata.get("status_history", []))
    history.append({"from": candidate.status.value, "to": new_status.value})
    metadata["status_history"] = history
    return candidate.model_copy(update={"status": new_status, "metadata": metadata})


def store_candidate_lifecycle_entry(
    candidate: ResearchCandidate,
    *,
    vault_root: Path | str = DEFAULT_CANDIDATE_VAULT_ROOT,
    links: CandidateVaultLinks = CandidateVaultLinks(),
) -> Path:
    """Store a research candidate as an Obsidian-readable vault entry."""

    store = MarkdownKnowledgeStore(vault_root)
    entry = KnowledgeEntry(
        entry_id=candidate.id,
        entry_type=KnowledgeEntryType.RESEARCH_CANDIDATE,
        zone=KnowledgeZone.EXPLORATION,
        title=candidate.title,
        tags=["research-candidate", candidate.status.value],
        keywords=_candidate_keywords(candidate),
        source_refs=sorted(set(candidate.evidence_refs) | set(links.source_papers)),
        related_task_ids=[],
        related_run_ids=[],
        body=_candidate_body(candidate, links),
    )
    relative_path = Path("exploration") / "topics" / f"{candidate.id}.md"
    return store.write_entry(relative_path, entry)


def _candidate_keywords(candidate: ResearchCandidate) -> list[str]:
    keywords = {
        "research-candidate",
        candidate.status.value,
    }
    for key in ("method", "dataset", "limitation"):
        value = candidate.metadata.get(key)
        if isinstance(value, str) and value:
            keywords.add(value)
    return sorted(keywords)


def _candidate_body(
    candidate: ResearchCandidate,
    links: CandidateVaultLinks,
) -> str:
    return "\n".join(
        [
            f"# {candidate.title}",
            "",
            f"- Candidate ID: `{candidate.id}`",
            f"- Status: `{candidate.status.value}`",
            f"- Novelty score: `{candidate.novelty_score}`",
            f"- Feasibility score: `{candidate.feasibility_score}`",
            f"- Impact score: `{candidate.impact_score}`",
            "",
            "## Research Gap",
            "",
            candidate.research_gap,
            "",
            "## Description",
            "",
            candidate.description,
            "",
            "## Evidence",
            "",
            *_link_lines("Source papers", tuple(candidate.evidence_refs) + links.source_papers),
            *_link_lines("Topic indexes", links.topic_index_entries),
            *_link_lines("Prior failures", links.prior_failures),
            *_link_lines("Useful skills", links.useful_skills),
            *_link_lines("Strategy cards", links.strategy_cards),
        ]
    ).rstrip() + "\n"


def _link_lines(label: str, targets: tuple[str, ...]) -> list[str]:
    lines = [f"### {label}", ""]
    unique_targets = tuple(dict.fromkeys(target for target in targets if target))
    if not unique_targets:
        lines.extend(["- None", ""])
        return lines
    lines.extend(f"- [[{target}]]" for target in unique_targets)
    lines.append("")
    return lines


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
