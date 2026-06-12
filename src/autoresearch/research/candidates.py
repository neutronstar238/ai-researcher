"""Deterministic research candidate generation from retrieved literature."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

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
class TrendGapAnalysisConfig:
    """Tuning knobs for literature-vault gap analysis."""

    max_updates: int = 3
    min_ready_evidence_refs: int = 2


@dataclass(frozen=True)
class TrendGapUpdate:
    """Evidence-backed candidate update produced from literature-vault gaps."""

    candidate: ResearchCandidate
    gap_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    vault_paths: tuple[str, ...]
    missing_vault_paths: tuple[str, ...]


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


@dataclass(frozen=True)
class _VaultReference:
    entry: KnowledgeEntry
    relative_path: str
    searchable_text: str


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


def analyze_trends_and_gaps(
    documents: list[DocumentRecord],
    *,
    vault_root: Path | str = DEFAULT_CANDIDATE_VAULT_ROOT,
    config: TrendGapAnalysisConfig = TrendGapAnalysisConfig(),
) -> list[TrendGapUpdate]:
    """Compare recent literature candidates against Obsidian knowledge gaps."""

    candidates = generate_research_candidates(
        documents,
        config=CandidateGenerationConfig(
            max_candidates=config.max_updates,
            min_ready_evidence_refs=config.min_ready_evidence_refs,
        ),
    )
    root = Path(vault_root)
    references = _load_vault_references(root)
    index_paths = _topic_index_paths(root)

    updates: list[TrendGapUpdate] = []
    for candidate in candidates:
        gap_reasons = _candidate_gap_reasons(candidate, references, root)
        if not gap_reasons:
            continue
        vault_paths = _candidate_vault_paths(candidate, references, index_paths)
        missing_paths = _candidate_missing_vault_paths(candidate, gap_reasons)
        evidence_refs = tuple(candidate.evidence_refs)
        metadata = dict(candidate.metadata)
        metadata["gap_analysis"] = {
            "gap_reasons": list(gap_reasons),
            "evidence_refs": list(evidence_refs),
            "vault_paths": list(vault_paths),
            "missing_vault_paths": list(missing_paths),
        }
        updates.append(
            TrendGapUpdate(
                candidate=candidate.model_copy(update={"metadata": metadata}),
                gap_reasons=gap_reasons,
                evidence_refs=evidence_refs,
                vault_paths=vault_paths,
                missing_vault_paths=missing_paths,
            )
        )

    return updates


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


def _load_vault_references(vault_root: Path) -> tuple[_VaultReference, ...]:
    if not vault_root.exists():
        return ()

    references: list[_VaultReference] = []
    for path in sorted(vault_root.rglob("*.md")):
        relative_path = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        try:
            entry = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError):
            continue
        references.append(
            _VaultReference(
                entry=entry,
                relative_path=relative_path.as_posix(),
                searchable_text=_entry_searchable_text(entry),
            )
        )
    return tuple(references)


def _entry_searchable_text(entry: KnowledgeEntry) -> str:
    return " ".join(
        [
            entry.title,
            *entry.tags,
            *entry.keywords,
            entry.body,
        ]
    ).casefold()


def _topic_index_paths(vault_root: Path) -> tuple[str, ...]:
    exploration_root = vault_root / "exploration"
    candidates = [exploration_root / "index.md"]
    if exploration_root.exists():
        candidates.extend(sorted(exploration_root.glob("**/index.md")))
    return tuple(
        dict.fromkeys(
            path.relative_to(vault_root).as_posix()
            for path in candidates
            if path.exists()
        )
    )


def _candidate_gap_reasons(
    candidate: ResearchCandidate,
    references: tuple[_VaultReference, ...],
    vault_root: Path,
) -> tuple[str, ...]:
    method = _metadata_text(candidate, "method")
    dataset = _metadata_text(candidate, "dataset")
    limitation = _metadata_text(candidate, "limitation")
    reasons: list[str] = []

    if not _has_reference(references, KnowledgeEntryType.METHOD_CARD, method):
        reasons.append(f"missing method card for {method}")
    if not _has_reference(references, KnowledgeEntryType.DATASET_CARD, dataset):
        reasons.append(f"missing dataset card for {dataset}")
    if not _has_project_experience(references, (method, dataset, limitation)):
        reasons.append(f"missing prior project experience for {limitation}")
    if not _topic_index_covers(vault_root, (method, dataset, limitation)):
        reasons.append("topic index lacks candidate gap keywords")

    return tuple(reasons)


def _candidate_vault_paths(
    candidate: ResearchCandidate,
    references: tuple[_VaultReference, ...],
    index_paths: tuple[str, ...],
) -> tuple[str, ...]:
    terms = (
        _metadata_text(candidate, "method"),
        _metadata_text(candidate, "dataset"),
        _metadata_text(candidate, "limitation"),
    )
    matched_paths = [
        reference.relative_path
        for reference in references
        if any(term in reference.searchable_text for term in terms)
    ]
    return tuple(sorted(dict.fromkeys([*index_paths, *matched_paths])))


def _candidate_missing_vault_paths(
    candidate: ResearchCandidate,
    gap_reasons: tuple[str, ...],
) -> tuple[str, ...]:
    method = _metadata_text(candidate, "method")
    dataset = _metadata_text(candidate, "dataset")
    limitation = _metadata_text(candidate, "limitation")
    paths: list[str] = []
    for reason in gap_reasons:
        if reason.startswith("missing method card"):
            paths.append(f"exploration/methodologies/{_slugify(method)}.md")
        elif reason.startswith("missing dataset card"):
            paths.append(f"exploration/datasets/{_slugify(dataset)}.md")
        elif reason.startswith("missing prior project experience"):
            paths.append(f"projects/*/experience/{_slugify(limitation)}.md")
        elif reason.startswith("topic index lacks"):
            paths.append("exploration/index.md")
    return tuple(paths)


def _metadata_text(candidate: ResearchCandidate, key: str) -> str:
    value = candidate.metadata.get(key)
    if isinstance(value, str) and value:
        return value.casefold()
    return key


def _has_reference(
    references: tuple[_VaultReference, ...],
    entry_type: KnowledgeEntryType,
    term: str,
) -> bool:
    return any(
        reference.entry.entry_type == entry_type and term in reference.searchable_text
        for reference in references
    )


def _has_project_experience(
    references: tuple[_VaultReference, ...],
    terms: tuple[str, ...],
) -> bool:
    experience_types = {
        KnowledgeEntryType.EXPERIMENT_RECORD,
        KnowledgeEntryType.FAILURE_CASE,
        KnowledgeEntryType.ISSUE_NOTE,
        KnowledgeEntryType.PROJECT_PROGRESS,
        KnowledgeEntryType.REVIEW_NOTE,
    }
    return any(
        reference.entry.entry_type in experience_types
        and reference.entry.zone == KnowledgeZone.PROJECT
        and any(term in reference.searchable_text for term in terms)
        for reference in references
    )


def _topic_index_covers(vault_root: Path, terms: tuple[str, ...]) -> bool:
    index_path = vault_root / "exploration" / "index.md"
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8").casefold()
    return all(term in text for term in terms)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "entry"


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
