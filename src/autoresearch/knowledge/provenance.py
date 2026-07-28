"""Approved, source-anchored provenance projections for the Obsidian vault."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from autoresearch.kernel import (
    Claim,
    Counterevidence,
    Decision,
    Entity,
    EntityKind,
    Evidence,
    ProvenanceBundle,
    Validation,
    VersionedRecord,
)
from autoresearch.kernel.contracts import KernelContract, StableId

from .entries import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from .vault import create_vault_layout

_PATH_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class VaultProjectionError(RuntimeError):
    """Raised when a requested Vault projection is unsafe or inconsistent."""


class VaultProjectionResult(KernelContract):
    """Deterministic summary of approved provenance notes written to a vault."""

    project_id: StableId
    bundle_id: StableId
    approved_record_ids: list[StableId]
    written_paths: list[str]


def project_provenance_to_vault(
    bundle: ProvenanceBundle,
    vault_root: Path | str,
    *,
    approved_record_ids: Iterable[str],
) -> VaultProjectionResult:
    """Write only explicitly approved provenance records as Obsidian Markdown."""

    bundle.verify_integrity()
    approved = set(approved_record_ids)
    if not approved:
        raise VaultProjectionError("Vault projection requires an explicit approval allow-list")
    projectable = _projectable_records(bundle)
    unknown = approved - set(projectable)
    if unknown:
        raise VaultProjectionError(
            "approval allow-list contains unknown or non-projectable records: "
            + ", ".join(sorted(unknown))
        )

    for claim in bundle.claims:
        if claim.claim_id in approved and claim.core:
            bundle.require_claim_trace(claim.claim_id)

    layout = create_vault_layout(vault_root, bundle.project_id)
    store = MarkdownKnowledgeStore(layout.root)
    written: list[str] = []
    for record_id in sorted(approved):
        record = projectable[record_id]
        entry, relative_path = _entry_for_record(bundle, record)
        written_path = store.write_entry(relative_path, entry)
        written.append(written_path.relative_to(layout.root).as_posix())

    return VaultProjectionResult(
        project_id=bundle.project_id,
        bundle_id=bundle.bundle_id,
        approved_record_ids=sorted(approved),
        written_paths=sorted(written),
    )


def _projectable_records(
    bundle: ProvenanceBundle,
) -> dict[str, Entity | Claim | Evidence | Counterevidence | Decision]:
    records: dict[str, Entity | Claim | Evidence | Counterevidence | Decision] = {}
    for entity in bundle.entities:
        records[entity.entity_id] = entity
    for claim in bundle.claims:
        records[claim.claim_id] = claim
    for evidence_item in bundle.evidence:
        records[evidence_item.evidence_id] = evidence_item
    for counter_item in bundle.counterevidence:
        records[counter_item.evidence_id] = counter_item
    for decision in bundle.decisions:
        records[decision.decision_id] = decision
    return records


def _entry_for_record(
    bundle: ProvenanceBundle,
    record: Entity | Claim | Evidence | Counterevidence | Decision,
) -> tuple[KnowledgeEntry, Path]:
    if isinstance(record, Entity):
        return _entity_entry(bundle, record)
    if isinstance(record, Claim):
        return _claim_entry(bundle, record)
    if isinstance(record, Decision):
        return _decision_entry(bundle, record)
    return _evidence_entry(bundle, record)


def _entity_entry(bundle: ProvenanceBundle, entity: Entity) -> tuple[KnowledgeEntry, Path]:
    entry_type, zone, directory = _entity_destination(entity.kind, bundle.project_id)
    source_refs = [entity.source_uri] if entity.source_uri is not None else []
    confidence = entity.attributes.get("confidence", "not-scored")
    attributes = (
        json.dumps(
            entity.attributes,
            sort_keys=True,
            ensure_ascii=False,
            indent=2,
        )
        if entity.attributes
        else "{}"
    )
    body = "\n".join(
        [
            f"# {entity.label}",
            "",
            "## Source anchor",
            "",
            f"- Record: `{entity.entity_id}`",
            f"- Type: `{entity.kind.value}`",
            f"- Source: `{entity.source_uri or 'not-applicable'}`",
            f"- Artifact hash: `{entity.content_digest or 'not-applicable'}`",
            f"- Confidence: `{confidence}`",
            *_validity_lines(entity),
            *_event_lines(entity.event_ids),
            "",
            "## Structured context",
            "",
            "```json",
            attributes,
            "```",
            *_supersession_links(entity.supersedes_id),
        ]
    )
    entry = _entry(
        bundle=bundle,
        entry_id=entity.entity_id,
        entry_type=entry_type,
        zone=zone,
        title=entity.label,
        source_refs=source_refs,
        keywords=[entity.kind.value, "provenance", "source-anchored"],
        body=body,
        created_at=entity.valid_from,
    )
    return entry, directory / f"{_safe_name(entity.entity_id)}.md"


def _claim_entry(bundle: ProvenanceBundle, claim: Claim) -> tuple[KnowledgeEntry, Path]:
    related_evidence = sorted(
        item.evidence_id
        for item in [*bundle.evidence, *bundle.counterevidence]
        if item.claim_id == claim.claim_id
    )
    link_lines = (
        ["", "## Evidence", ""]
        + [f"- [[{evidence_id}]]" for evidence_id in related_evidence]
        if related_evidence
        else []
    )
    body = "\n".join(
        [
            f"# Claim: {claim.statement}",
            "",
            "## Assertion",
            "",
            claim.statement,
            "",
            "## Provenance",
            "",
            f"- Record: `{claim.claim_id}`",
            f"- Core claim: `{str(claim.core).lower()}`",
            f"- Confidence: `{claim.confidence:.4f}`",
            "- Artifact hash: `not-applicable`",
            *_validity_lines(claim),
            *_event_lines(claim.event_ids),
            *_supersession_links(claim.supersedes_id),
            *link_lines,
        ]
    )
    entry = _entry(
        bundle=bundle,
        entry_id=claim.claim_id,
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title=f"Claim - {claim.statement}",
        source_refs=[bundle.bundle_id],
        keywords=["claim", "evidence", "provenance"],
        body=body,
        created_at=claim.valid_from,
    )
    path = (
        Path("projects")
        / bundle.project_id
        / "evidence"
        / f"{_safe_name(claim.claim_id)}.md"
    )
    return entry, path


def _evidence_entry(
    bundle: ProvenanceBundle,
    evidence: Evidence | Counterevidence,
) -> tuple[KnowledgeEntry, Path]:
    snapshot = next(
        item
        for item in bundle.source_snapshots
        if item.snapshot_id == evidence.source_snapshot_id
    )
    artifact = next(
        entity
        for entity in bundle.entities
        if entity.entity_id == evidence.artifact_entity_id
    )
    validations = [
        validation
        for validation in bundle.validations
        if validation.validation_id in evidence.validation_ids
    ]
    validation_lines = [
        f"- [[{validation.validation_id}]] — `{validation.status.value}`: "
        f"{validation.summary}"
        for validation in sorted(validations, key=lambda item: item.checked_at)
    ]
    body = "\n".join(
        [
            f"# Evidence: {evidence.summary}",
            "",
            "## Directional evidence",
            "",
            f"- Direction: `{evidence.direction.value}`",
            f"- Claim: [[{evidence.claim_id}]]",
            f"- Source entity: [[{evidence.source_entity_id}]]",
            f"- Artifact entity: [[{evidence.artifact_entity_id}]]",
            f"- Source snapshot: `{evidence.source_snapshot_id}`",
            f"- Source URI: `{snapshot.source_uri}`",
            f"- Generating activity: `{evidence.generating_activity_id}`",
            "- Responsible agents: "
            + ", ".join(f"`{agent_id}`" for agent_id in evidence.responsible_agent_ids),
            f"- Artifact hash: `{artifact.content_digest or 'not-applicable'}`",
            f"- Confidence: `{evidence.confidence:.4f}`",
            *_validity_lines(evidence),
            *_event_lines(evidence.event_ids),
            *_supersession_links(evidence.supersedes_id),
            "",
            "## Validation history",
            "",
            *(validation_lines or ["- No validation records."]),
        ]
    )
    entry = _entry(
        bundle=bundle,
        entry_id=evidence.evidence_id,
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title=f"{evidence.direction.value.title()} evidence - {evidence.summary}",
        source_refs=[snapshot.source_uri],
        keywords=[
            "evidence",
            evidence.direction.value,
            "validation-history",
            "provenance",
        ],
        body=body,
        created_at=evidence.valid_from,
    )
    path = (
        Path("projects")
        / bundle.project_id
        / "evidence"
        / f"{_safe_name(evidence.evidence_id)}.md"
    )
    return entry, path


def _decision_entry(
    bundle: ProvenanceBundle,
    decision: Decision,
) -> tuple[KnowledgeEntry, Path]:
    artifact = next(
        entity
        for entity in bundle.entities
        if entity.entity_id == decision.artifact_entity_id
    )
    validations = _validation_records(bundle, decision.validation_ids)
    body = "\n".join(
        [
            f"# Decision: {decision.outcome}",
            "",
            "## Determination",
            "",
            decision.rationale,
            "",
            "## Provenance",
            "",
            f"- Record: `{decision.decision_id}`",
            f"- Outcome: `{decision.outcome}`",
            "- Claims: " + ", ".join(f"[[{claim_id}]]" for claim_id in decision.claim_ids),
            f"- Activity: `{decision.activity_id}`",
            f"- Responsible agent: `{decision.responsible_agent_id}`",
            f"- Decision artifact: [[{decision.artifact_entity_id}]]",
            f"- Artifact hash: `{artifact.content_digest or 'not-applicable'}`",
            "- Confidence: `derived-from-linked-validations`",
            *_validity_lines(decision),
            *_event_lines(decision.event_ids),
            *_supersession_links(decision.supersedes_id),
            "",
            "## Validation history",
            "",
            *[
                f"- [[{validation.validation_id}]] — `{validation.status.value}`: "
                f"{validation.summary}"
                for validation in validations
            ],
        ]
    )
    entry = _entry(
        bundle=bundle,
        entry_id=decision.decision_id,
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        title=f"Decision - {decision.outcome}",
        source_refs=[artifact.source_uri or bundle.bundle_id],
        keywords=["decision", "validation", "provenance"],
        body=body,
        created_at=decision.valid_from,
    )
    path = (
        Path("projects")
        / bundle.project_id
        / "review"
        / f"{_safe_name(decision.decision_id)}.md"
    )
    return entry, path


def _entry(
    *,
    bundle: ProvenanceBundle,
    entry_id: str,
    entry_type: KnowledgeEntryType,
    zone: KnowledgeZone,
    title: str,
    source_refs: list[str],
    keywords: list[str],
    body: str,
    created_at: datetime,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id=entry_id,
        entry_type=entry_type,
        zone=zone,
        title=title,
        project_id=bundle.project_id,
        tags=["provenance-v2", "approved-projection"],
        keywords=keywords,
        source_refs=source_refs,
        related_run_ids=[bundle.run_id],
        created_at=created_at,
        updated_at=bundle.created_at,
        body=body,
    )


def _entity_destination(
    kind: EntityKind,
    project_id: str,
) -> tuple[KnowledgeEntryType, KnowledgeZone, Path]:
    destinations = {
        EntityKind.LITERATURE: (
            KnowledgeEntryType.PAPER_NOTE,
            KnowledgeZone.EXPLORATION,
            Path("exploration") / "topics",
        ),
        EntityKind.HYPOTHESIS: (
            KnowledgeEntryType.RESEARCH_CANDIDATE,
            KnowledgeZone.PROJECT,
            Path("projects") / project_id / "knowledge",
        ),
        EntityKind.FAILURE: (
            KnowledgeEntryType.FAILURE_CASE,
            KnowledgeZone.PROJECT,
            Path("projects") / project_id / "experience",
        ),
        EntityKind.SKILL: (
            KnowledgeEntryType.SKILL_CARD,
            KnowledgeZone.EXPLORATION,
            Path("exploration") / "skills",
        ),
        EntityKind.STRATEGY: (
            KnowledgeEntryType.STRATEGY_CARD,
            KnowledgeZone.EXPLORATION,
            Path("exploration") / "strategy_cards",
        ),
        EntityKind.EXPERIMENT_RECORD: (
            KnowledgeEntryType.EXPERIMENT_RECORD,
            KnowledgeZone.PROJECT,
            Path("projects") / project_id / "experiments",
        ),
        EntityKind.DECISION: (
            KnowledgeEntryType.REVIEW_NOTE,
            KnowledgeZone.PROJECT,
            Path("projects") / project_id / "review",
        ),
    }
    entry_type, zone, directory = destinations.get(
        kind,
        (
            KnowledgeEntryType.EVIDENCE_NOTE,
            KnowledgeZone.PROJECT,
            Path("projects") / project_id / "evidence",
        ),
    )
    return entry_type, zone, directory


def _validity_lines(record: VersionedRecord) -> list[str]:
    valid_from = record.valid_from
    valid_to = record.valid_to
    invalidated_at = record.invalidated_at
    version = record.version
    return [
        f"- Version: `{version}`",
        f"- Valid from: `{valid_from.isoformat()}`",
        f"- Valid to: `{valid_to.isoformat() if valid_to else 'open'}`",
        f"- Invalidated at: `{invalidated_at.isoformat() if invalidated_at else 'active'}`",
    ]


def _event_lines(event_ids: list[str]) -> list[str]:
    if not event_ids:
        return ["- Event IDs: `none`"]
    return ["- Event IDs: " + ", ".join(f"`{event_id}`" for event_id in event_ids)]


def _supersession_links(supersedes_id: str | None) -> list[str]:
    if supersedes_id is None:
        return ["- Supersedes: `none`"]
    return [f"- Supersedes: [[{supersedes_id}]]"]


def _validation_records(
    bundle: ProvenanceBundle,
    validation_ids: list[str],
) -> list[Validation]:
    by_id = {
        validation.validation_id: validation
        for validation in bundle.validations
    }
    return [by_id[validation_id] for validation_id in validation_ids]


def _safe_name(record_id: str) -> str:
    normalized = _PATH_COMPONENT_PATTERN.sub("-", record_id).strip(".-")
    if not normalized:
        raise VaultProjectionError(f"record ID {record_id!r} has no safe path component")
    return normalized
