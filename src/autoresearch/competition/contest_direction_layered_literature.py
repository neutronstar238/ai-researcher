"""Immutable literature view layered over a frozen broad+targeted R1 merge.

The historical merged-v1 artifact is never reinterpreted or upgraded.  This
module derives a separate content-addressed view from that immutable base and
one or more sparse role-gap repair artifacts.  The derived records keep the
existing merged-record schema so downstream migration can remain narrow, while
explicit bindings retain the exact base/repair round and query lineage.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition import contest_direction_merged_literature as merged_module
from autoresearch.competition.contest_direction_gap_repair_retrieval import (
    ContestDirectionGapRepairArtifact,
)
from autoresearch.competition.contest_direction_merged_literature import (
    ContestDirectionMergedLiteratureArtifact,
    ContestMergedLiteratureOrigin,
    ContestMergedLiteratureRecord,
    ContestMergedLiteratureRetrieval,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureRole,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.models import normalize_doi

_SHA256 = r"^[0-9a-f]{64}$"


class ContestDirectionLayeredLiteratureError(RuntimeError):
    """Raised when a layered view cannot be rederived from its exact inputs."""


class ContestDirectionLayeredQueryLineage(StrictFrozenModel):
    """One exact record-to-fetch edge with an explicit retrieval round."""

    round_index: int = Field(ge=1)
    retrieval_kind: Literal[
        "base_broad",
        "base_targeted",
        "gap_repair",
    ]
    role: PlanningLiteratureRole | None = None
    retrieval_artifact_hash: str = Field(pattern=_SHA256)
    query_id: str | None = Field(default=None, min_length=1)
    query_hash: str | None = Field(default=None, pattern=_SHA256)
    logical_query: str | None = Field(default=None, min_length=1)
    executed_query: str = Field(min_length=1)
    source: str = Field(min_length=1)
    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    fetch_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_lineage(self) -> ContestDirectionLayeredQueryLineage:
        is_repair = self.retrieval_kind == "gap_repair"
        if is_repair != (self.round_index >= 2):
            raise ValueError("layered query round and retrieval kind mismatch")
        if is_repair and (
            self.role is None
            or self.query_id is None
            or self.query_hash is None
            or self.logical_query is None
        ):
            raise ValueError("repair query lineage requires role, query ID, and query hash")
        if not is_repair and (
            self.round_index != 1
            or self.role is not None
            or self.query_id is not None
            or self.query_hash is not None
            or self.logical_query is not None
        ):
            raise ValueError("base query lineage cannot claim a repair role/query identity")
        return self


class ContestDirectionLayeredRepairRecordRef(StrictFrozenModel):
    """One repair input record and every real fetch that admitted it."""

    round_index: int = Field(ge=2)
    repair_artifact_hash: str = Field(pattern=_SHA256)
    repair_catalog_hash: str = Field(pattern=_SHA256)
    original_record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
    original_record_hash: str = Field(pattern=_SHA256)
    roles: tuple[PlanningLiteratureRole, ...] = Field(min_length=1)
    query_lineage: tuple[ContestDirectionLayeredQueryLineage, ...] = Field(min_length=1)
    ref_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_ref(self) -> ContestDirectionLayeredRepairRecordRef:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("layered repair-record roles must be unique")
        if any(
            item.round_index != self.round_index
            or item.retrieval_kind != "gap_repair"
            or item.retrieval_artifact_hash != self.repair_artifact_hash
            for item in self.query_lineage
        ):
            raise ValueError("repair-record query lineage has a different round/artifact")
        actual_roles = tuple(dict.fromkeys(item.role for item in self.query_lineage))
        if self.roles != actual_roles:
            raise ValueError("repair-record roles do not match its query lineage")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"ref_hash"}))
        if self.ref_hash != expected:
            raise ValueError("layered repair-record reference hash mismatch")
        return self


class ContestDirectionLayeredRecordBinding(StrictFrozenModel):
    """Many-to-one mapping from immutable R1/R2 inputs to one layered record."""

    layered_record_id: str = Field(pattern=r"^merged-direction-paper-[0-9a-f]{16}$")
    layered_record_hash: str = Field(pattern=_SHA256)
    base_record_ids: tuple[str, ...] = ()
    base_record_hashes: tuple[str, ...] = ()
    repair_records: tuple[ContestDirectionLayeredRepairRecordRef, ...] = ()
    round_query_lineage: tuple[ContestDirectionLayeredQueryLineage, ...] = Field(min_length=1)
    binding_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_binding(self) -> ContestDirectionLayeredRecordBinding:
        if not self.base_record_ids and not self.repair_records:
            raise ValueError("layered record binding has no R1 or repair input")
        if len(self.base_record_ids) != len(self.base_record_hashes):
            raise ValueError("layered base-record ID/hash mapping mismatch")
        if len(self.base_record_ids) != len(set(self.base_record_ids)):
            raise ValueError("layered base-record IDs must be unique")
        lineage_keys = tuple(
            (
                item.retrieval_artifact_hash,
                item.fetch_id,
                item.source,
                item.executed_query,
            )
            for item in self.round_query_lineage
        )
        if len(lineage_keys) != len(set(lineage_keys)):
            raise ValueError("layered round-query lineage must be unique")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected:
            raise ValueError("layered record-binding hash mismatch")
        return self


class ContestDirectionLayeredBaseRecordBinding(StrictFrozenModel):
    """Explicit R1 record identity mapping after cross-layer deduplication."""

    base_record_id: str = Field(pattern=r"^merged-direction-paper-[0-9a-f]{16}$")
    base_record_hash: str = Field(pattern=_SHA256)
    layered_record_id: str = Field(pattern=r"^merged-direction-paper-[0-9a-f]{16}$")
    layered_record_hash: str = Field(pattern=_SHA256)


class ContestDirectionLayeredRepairRound(StrictFrozenModel):
    """Hash binding for one sparse repair artifact in round order."""

    round_index: int = Field(ge=2)
    trigger_coverage_receipt_hash: str = Field(pattern=_SHA256)
    gap_repair_projection_hash: str = Field(pattern=_SHA256)
    plan_hash: str = Field(pattern=_SHA256)
    deficit_roles: tuple[PlanningLiteratureRole, ...] = Field(min_length=1)
    role_query_hashes: tuple[str, ...] = Field(min_length=1)
    repair_artifact_hash: str = Field(pattern=_SHA256)
    repair_catalog_hash: str = Field(pattern=_SHA256)
    retrieval_lineage_hash: str = Field(pattern=_SHA256)
    fetch_count: int = Field(ge=1)
    record_count: int = Field(ge=0)
    binding_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_round(self) -> ContestDirectionLayeredRepairRound:
        if len(self.deficit_roles) != len(set(self.deficit_roles)):
            raise ValueError("layered repair-round roles must be unique")
        if len(self.role_query_hashes) != len(self.deficit_roles):
            raise ValueError("layered repair-round role/query count mismatch")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected:
            raise ValueError("layered repair-round binding hash mismatch")
        return self


class ContestDirectionLayeredLiteratureArtifact(StrictFrozenModel):
    """R1-compatible record interface with explicit sparse-repair lineage."""

    schema_version: Literal["contest-direction-layered-literature-v1"] = (
        "contest-direction-layered-literature-v1"
    )
    parent_direction: str = Field(min_length=1)
    broad_literature_artifact_hash: str = Field(pattern=_SHA256)
    broad_literature_catalog_hash: str = Field(pattern=_SHA256)
    focus_artifact_hash: str = Field(pattern=_SHA256)
    selected_focus_id: str = Field(pattern=r"^direction-focus-[0-9a-f]{16}$")
    focused_direction_cn: str = Field(min_length=1)
    targeted_retrieval_binding_hash: str = Field(pattern=_SHA256)
    targeted_literature_artifact_hash: str = Field(pattern=_SHA256)
    targeted_literature_catalog_hash: str = Field(pattern=_SHA256)
    base_merged_artifact_hash: str = Field(pattern=_SHA256)
    base_merged_catalog_hash: str = Field(pattern=_SHA256)
    repair_rounds: tuple[ContestDirectionLayeredRepairRound, ...] = Field(min_length=1)
    records: tuple[ContestMergedLiteratureRecord, ...] = Field(min_length=1)
    record_ids: tuple[str, ...] = Field(min_length=1)
    record_bindings: tuple[ContestDirectionLayeredRecordBinding, ...] = Field(min_length=1)
    base_to_layered_records: tuple[ContestDirectionLayeredBaseRecordBinding, ...] = Field(
        min_length=1
    )
    base_record_ids: tuple[str, ...] = Field(min_length=1)
    base_record_count: int = Field(ge=1)
    repair_input_record_count: int = Field(ge=0)
    layered_record_count: int = Field(ge=1)
    cross_layer_deduplicated_count: int = Field(ge=0)
    merged_catalog_hash: str = Field(pattern=_SHA256)
    retrieval_semantics: Literal["immutable_r1_base_plus_sparse_role_gap_repair_rounds"] = (
        "immutable_r1_base_plus_sparse_role_gap_repair_rounds"
    )
    selection_semantics: Literal["unfiltered_layered_catalog_for_program_selection"] = (
        "unfiltered_layered_catalog_for_program_selection"
    )
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestDirectionLayeredLiteratureArtifact:
        round_indices = tuple(item.round_index for item in self.repair_rounds)
        if round_indices != tuple(range(2, 2 + len(round_indices))):
            raise ValueError("layered repair rounds must be contiguous and start at round 2")
        actual_ids = tuple(item.record_id for item in self.records)
        if self.record_ids != actual_ids or len(actual_ids) != len(set(actual_ids)):
            raise ValueError("layered literature record IDs mismatch")
        if self.layered_record_count != len(self.records):
            raise ValueError("layered literature record count mismatch")
        if self.base_record_count != len(self.base_record_ids):
            raise ValueError("layered base-record count mismatch")
        expected_repair_count = sum(item.record_count for item in self.repair_rounds)
        if self.repair_input_record_count != expected_repair_count:
            raise ValueError("layered repair input-record count mismatch")
        expected_deduplicated = (
            self.base_record_count + self.repair_input_record_count - self.layered_record_count
        )
        if self.cross_layer_deduplicated_count != expected_deduplicated:
            raise ValueError("layered cross-layer deduplication count mismatch")

        records_by_id = {item.record_id: item for item in self.records}
        bindings_by_id = {item.layered_record_id: item for item in self.record_bindings}
        if len(bindings_by_id) != len(self.record_bindings) or set(bindings_by_id) != set(
            records_by_id
        ):
            raise ValueError("layered record bindings do not cover the record catalog")
        for record_id, binding in bindings_by_id.items():
            record = records_by_id[record_id]
            if binding.layered_record_hash != record.record_hash:
                raise ValueError("layered record binding has a different record hash")
            retrieval_keys = {
                (
                    item.retrieval_artifact_hash,
                    item.fetch_id,
                    item.source,
                    item.query,
                )
                for item in record.retrievals
            }
            lineage_keys = {
                (
                    item.retrieval_artifact_hash,
                    item.fetch_id,
                    item.source,
                    item.executed_query,
                )
                for item in binding.round_query_lineage
            }
            if retrieval_keys != lineage_keys:
                raise ValueError("layered record retrievals differ from round-query lineage")

        base_mappings = {item.base_record_id: item for item in self.base_to_layered_records}
        if (
            len(base_mappings) != len(self.base_to_layered_records)
            or tuple(base_mappings) != self.base_record_ids
        ):
            raise ValueError("layered base-to-record mapping does not preserve R1 order")
        for base_id, mapping in base_mappings.items():
            mapping_binding = bindings_by_id.get(mapping.layered_record_id)
            if (
                mapping_binding is None
                or base_id not in mapping_binding.base_record_ids
                or mapping.layered_record_hash != mapping_binding.layered_record_hash
            ):
                raise ValueError("layered base record maps outside its derived record")

        repair_rounds = {
            (item.round_index, item.repair_artifact_hash): item for item in self.repair_rounds
        }
        repair_refs = [ref for binding in self.record_bindings for ref in binding.repair_records]
        ref_keys = tuple(
            (item.round_index, item.repair_artifact_hash, item.original_record_id)
            for item in repair_refs
        )
        if len(ref_keys) != len(set(ref_keys)) or len(ref_keys) != self.repair_input_record_count:
            raise ValueError("layered repair-record references must cover each input once")
        if any(
            (item.round_index, item.repair_artifact_hash) not in repair_rounds
            or item.repair_catalog_hash
            != repair_rounds[(item.round_index, item.repair_artifact_hash)].repair_catalog_hash
            for item in repair_refs
        ):
            raise ValueError("layered repair-record reference has no matching repair round")

        expected_catalog_hash = canonical_model_hash(
            {"records": [item.model_dump(mode="json") for item in self.records]}
        )
        if self.merged_catalog_hash != expected_catalog_hash:
            raise ValueError("layered literature catalog hash mismatch")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError("layered literature artifact hash mismatch")
        return self

    def objective_retrieval_catalog(self) -> tuple[dict[str, Any], ...]:
        """Project complete records and explicit R1/R2 query lineage."""

        bindings = {item.layered_record_id: item for item in self.record_bindings}
        projected: list[dict[str, Any]] = []
        for record in self.records:
            source_url = (
                record.url
                or merged_module._doi_url(record.doi)
                or merged_module._doi_url(  # noqa: SLF001,E501
                    record.repository_doi
                )
            )
            if not source_url:
                continue
            binding = bindings[record.record_id]
            lineage = binding.round_query_lineage
            retrieved_at = min(item.retrieved_at for item in record.retrievals)
            projected.append(
                {
                    "record_id": record.record_id,
                    "title": record.title,
                    "authors": list(record.authors),
                    "abstract": record.abstract,
                    "publication_date": (
                        record.publication_date.isoformat()
                        if record.publication_date is not None
                        else None
                    ),
                    "venue": record.venue,
                    "doi": record.doi,
                    "publication_doi": record.doi,
                    "repository_doi": record.repository_doi,
                    "url": source_url,
                    "source_url": source_url,
                    "citation_count": record.citation_count,
                    "citation_count_source": record.citation_count_source,
                    "citation_count_as_of": (
                        record.citation_count_as_of.isoformat()
                        if record.citation_count_as_of is not None
                        else None
                    ),
                    "publication_status": record.publication_status,
                    "status_source": record.status_source,
                    "status_as_of": (
                        record.status_as_of.isoformat() if record.status_as_of is not None else None
                    ),
                    "paper_source": ",".join(
                        dict.fromkeys(item.source for item in record.retrievals)
                    ),
                    "retrieved_from": ",".join(
                        dict.fromkeys(item.source for item in record.retrievals)
                    ),
                    "retrieved_at": retrieved_at.isoformat(),
                    "record_sha256": record.record_hash,
                    "source_stages": list(record.source_stages),
                    "retrieval_queries": list(
                        dict.fromkeys(
                            item.logical_query for item in lineage if item.logical_query is not None
                        )
                    ),
                    "retrieval_stage_sources": list(
                        dict.fromkeys(
                            (
                                f"gap_repair_round_{item.round_index}:{item.source}"
                                if item.retrieval_kind == "gap_repair"
                                else f"{record_stage(item.retrieval_kind)}:{item.source}"
                            )
                            for item in lineage
                        )
                    ),
                    "round_query_lineage": [item.model_dump(mode="json") for item in lineage],
                }
            )
        return tuple(projected)

    def objective_literature_catalog(self) -> tuple[str, ...]:
        """Return complete audit context with round and fetch identities."""

        bindings = {item.layered_record_id: item for item in self.record_bindings}
        entries: list[str] = []
        for index, record in enumerate(self.records, start=1):
            lineage = bindings[record.record_id].round_query_lineage
            lineage_text = "；".join(
                (
                    f"round={item.round_index}|kind={item.retrieval_kind}|"
                    f"role={item.role.value if item.role is not None else 'none'}|"
                    f"artifact={item.retrieval_artifact_hash}|source={item.source}|"
                    "logical_query="
                    f"{item.logical_query or 'unavailable_in_base_merged_use_targeted_artifact_binding'}|"
                    f"executed_query={item.executed_query}|"
                    f"fetch={item.fetch_id}|fetch_sha256={item.fetch_hash}"
                )
                for item in lineage
            )
            entries.append(
                "\n".join(
                    (
                        f"[{index}] record_id={record.record_id}",
                        f"题名：{record.title}",
                        f"作者：{'、'.join(record.authors) if record.authors else '作者信息未提供'}",
                        f"日期：{record.publication_date.isoformat() if record.publication_date else '日期未提供'}",
                        f"期刊或会议：{record.venue or '未提供'}",
                        f"正式发表DOI：{record.doi or '未提供'}",
                        f"仓储DOI：{record.repository_doi or '未提供'}",
                        f"发表状态：{record.publication_status}",
                        f"URL：{record.url or merged_module._doi_url(record.doi) or merged_module._doi_url(record.repository_doi) or '未提供'}",  # noqa: SLF001,E501
                        f"完整摘要：{record.abstract or '摘要未提供'}",
                        f"分轮真实检索谱系：{lineage_text}",
                        f"layered_record_sha256={record.record_hash}",
                    )
                )
            )
        return tuple(entries)


def build_contest_direction_layered_literature(
    *,
    base_merged: ContestDirectionMergedLiteratureArtifact,
    repair_artifacts: Sequence[ContestDirectionGapRepairArtifact],
    output_path: Path | str | None = None,
) -> ContestDirectionLayeredLiteratureArtifact:
    """Derive a deterministic union while preserving every R1 and repair input."""

    base = ContestDirectionMergedLiteratureArtifact.model_validate(
        base_merged.model_dump(mode="json")
    )
    repairs = tuple(
        ContestDirectionGapRepairArtifact.model_validate(item.model_dump(mode="json"))
        for item in repair_artifacts
    )
    if not repairs:
        raise ContestDirectionLayeredLiteratureError(
            "layered literature requires at least one sparse repair; use merged-v1 otherwise"
        )
    round_indices = tuple(item.plan.round_index for item in repairs)
    if round_indices != tuple(range(2, 2 + len(repairs))):
        raise ContestDirectionLayeredLiteratureError(
            "repair artifacts must be supplied in contiguous round order starting at 2"
        )
    for repair in repairs:
        if (
            repair.plan.base_merged_artifact_hash != base.artifact_hash
            or repair.plan.base_merged_catalog_hash != base.merged_catalog_hash
        ):
            raise ContestDirectionLayeredLiteratureError(
                "sparse repair does not bind the immutable base merged artifact"
            )

    groups: list[_LayerGroup] = [
        _LayerGroup(base_records=[record], repair_entries=[]) for record in base.records
    ]
    for repair in repairs:
        for record in repair.retrieved_records:
            entry = _RepairEntry(artifact=repair, record=record)
            for group in groups:
                if any(
                    merged_module._same_work(record, candidate)  # noqa: SLF001
                    for candidate in group.all_records()
                ):
                    group.repair_entries.append(entry)
                    break
            else:
                groups.append(_LayerGroup(base_records=[], repair_entries=[entry]))

    records: list[ContestMergedLiteratureRecord] = []
    bindings: list[ContestDirectionLayeredRecordBinding] = []
    base_mappings_by_id: dict[str, ContestDirectionLayeredBaseRecordBinding] = {}
    for group in groups:
        layered_record = _build_layered_record(group)
        binding = _build_record_binding(group, layered_record)
        records.append(layered_record)
        bindings.append(binding)
        for base_record in group.base_records:
            base_mappings_by_id[base_record.record_id] = ContestDirectionLayeredBaseRecordBinding(
                base_record_id=base_record.record_id,
                base_record_hash=base_record.record_hash,
                layered_record_id=layered_record.record_id,
                layered_record_hash=layered_record.record_hash,
            )
    base_mappings = tuple(base_mappings_by_id[item] for item in base.record_ids)
    repair_rounds = tuple(_repair_round_binding(item) for item in repairs)
    catalog_hash = canonical_model_hash(
        {"records": [item.model_dump(mode="json") for item in records]}
    )
    repair_input_count = sum(len(item.retrieved_records) for item in repairs)
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-layered-literature-v1",
        "parent_direction": base.parent_direction,
        "broad_literature_artifact_hash": base.broad_literature_artifact_hash,
        "broad_literature_catalog_hash": base.broad_literature_catalog_hash,
        "focus_artifact_hash": base.focus_artifact_hash,
        "selected_focus_id": base.selected_focus_id,
        "focused_direction_cn": base.focused_direction_cn,
        "targeted_retrieval_binding_hash": base.targeted_retrieval_binding_hash,
        "targeted_literature_artifact_hash": base.targeted_literature_artifact_hash,
        "targeted_literature_catalog_hash": base.targeted_literature_catalog_hash,
        "base_merged_artifact_hash": base.artifact_hash,
        "base_merged_catalog_hash": base.merged_catalog_hash,
        "repair_rounds": [item.model_dump(mode="json") for item in repair_rounds],
        "records": [item.model_dump(mode="json") for item in records],
        "record_ids": [item.record_id for item in records],
        "record_bindings": [item.model_dump(mode="json") for item in bindings],
        "base_to_layered_records": [item.model_dump(mode="json") for item in base_mappings],
        "base_record_ids": list(base.record_ids),
        "base_record_count": len(base.records),
        "repair_input_record_count": repair_input_count,
        "layered_record_count": len(records),
        "cross_layer_deduplicated_count": len(base.records) + repair_input_count - len(records),
        "merged_catalog_hash": catalog_hash,
        "retrieval_semantics": "immutable_r1_base_plus_sparse_role_gap_repair_rounds",
        "selection_semantics": "unfiltered_layered_catalog_for_program_selection",
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    artifact = ContestDirectionLayeredLiteratureArtifact.model_validate(payload)
    if output_path is not None:
        write_json_model(output_path, artifact)
    return artifact


def load_contest_direction_layered_literature(
    path: Path | str,
    *,
    base_merged_path: Path | str,
    repair_artifact_paths: Sequence[Path | str],
) -> ContestDirectionLayeredLiteratureArtifact:
    """Reload every input and reject a self-consistent but non-rederived view."""

    persisted = ContestDirectionLayeredLiteratureArtifact.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    base = ContestDirectionMergedLiteratureArtifact.model_validate_json(
        Path(base_merged_path).read_text(encoding="utf-8")
    )
    repairs = tuple(
        ContestDirectionGapRepairArtifact.model_validate_json(
            Path(item).read_text(encoding="utf-8")
        )
        for item in repair_artifact_paths
    )
    rederived = build_contest_direction_layered_literature(
        base_merged=base,
        repair_artifacts=repairs,
    )
    if persisted != rederived:
        raise ContestDirectionLayeredLiteratureError(
            "layered literature differs from the rederived base + repair lineage"
        )
    return persisted


class _RepairEntry:
    def __init__(
        self,
        *,
        artifact: ContestDirectionGapRepairArtifact,
        record: Any,
    ) -> None:
        self.artifact = artifact
        self.record = record


class _LayerGroup:
    def __init__(
        self,
        *,
        base_records: list[ContestMergedLiteratureRecord],
        repair_entries: list[_RepairEntry],
    ) -> None:
        self.base_records = base_records
        self.repair_entries = repair_entries

    def all_records(self) -> tuple[Any, ...]:
        return (*self.base_records, *(item.record for item in self.repair_entries))


def _build_layered_record(group: _LayerGroup) -> ContestMergedLiteratureRecord:
    metadata_entries: tuple[tuple[bool, Any], ...] = (
        *(("targeted_direction" in record.source_stages, record) for record in group.base_records),
        *((True, entry.record) for entry in group.repair_entries),
    )
    representative = max(
        metadata_entries,
        key=lambda item: (
            bool(item[1].doi or item[1].repository_doi),
            bool(item[1].venue),
            len(item[1].authors),
            bool(item[1].url),
            item[1].publication_date or date.min,
            item[0],
            item[1].record_hash,
        ),
    )[1]
    longest_abstract = max(
        (record.abstract for _targeted, record in metadata_entries if record.abstract),
        key=len,
        default=None,
    )
    citation_candidates = tuple(
        record for _targeted, record in metadata_entries if record.citation_count is not None
    )
    citation_verified = tuple(
        record
        for record in citation_candidates
        if record.citation_count_source and record.citation_count_as_of
    )
    citation_record = max(
        citation_verified or citation_candidates,
        key=lambda record: (
            record.citation_count or 0,
            record.citation_count_as_of or date.min,
            bool(record.citation_count_source),
            record.record_hash,
        ),
        default=None,
    )
    _status_targeted, status_record = max(
        metadata_entries,
        key=lambda item: (
            merged_module._status_priority(item[1].publication_status),  # noqa: SLF001
            item[1].status_as_of or date.min,
            bool(item[1].status_source),
            item[0],
            item[1].record_hash,
        ),
    )
    doi = _consistent_layered_doi(metadata_entries, field="doi")
    repository_doi = _consistent_layered_doi(metadata_entries, field="repository_doi")
    authors = max(
        (record.authors for _targeted, record in metadata_entries),
        key=lambda values: (len(values), sum(len(value) for value in values)),
    )
    publication_date = max(
        (
            record.publication_date
            for _targeted, record in metadata_entries
            if record.publication_date
        ),
        default=None,
    )
    metadata_priority = sorted(
        metadata_entries,
        key=lambda item: (
            item[1].publication_status == "published",
            bool(item[1].doi),
            item[0],
        ),
        reverse=True,
    )
    venue = next((record.venue for _targeted, record in metadata_priority if record.venue), None)
    url = next((record.url for _targeted, record in metadata_priority if record.url), None)
    origins: list[ContestMergedLiteratureOrigin] = []
    retrievals: list[ContestMergedLiteratureRetrieval] = []
    for record in group.base_records:
        origins.extend(record.origins)
        retrievals.extend(record.retrievals)
    for entry in group.repair_entries:
        record = entry.record
        repair = entry.artifact
        origins.append(
            ContestMergedLiteratureOrigin(
                stage="targeted_direction",
                retrieval_artifact_hash=repair.artifact_hash,
                retrieval_catalog_hash=repair.repair_catalog_hash,
                original_record_id=record.record_id,
                original_record_hash=record.record_hash,
                original_paper_hash=record.paper_hash,
                title=record.title,
                doi=record.doi,
                repository_doi=record.repository_doi,
                citation_count=record.citation_count,
                citation_count_source=record.citation_count_source,
                citation_count_as_of=record.citation_count_as_of,
                publication_status=record.publication_status,
                status_source=record.status_source,
                status_as_of=record.status_as_of,
            )
        )
        fetches = {item.fetch_id: item for item in repair.fetches}
        for pointer in record.retrievals:
            fetch = fetches[pointer.fetch_id]
            retrievals.append(
                ContestMergedLiteratureRetrieval(
                    stage="targeted_direction",
                    retrieval_artifact_hash=repair.artifact_hash,
                    fetch_id=pointer.fetch_id,
                    fetch_hash=fetch.fetch_hash,
                    source=pointer.source,
                    query=pointer.query,
                    retrieved_at=pointer.retrieved_at,
                )
            )
    origins = list(
        {
            (item.stage, item.retrieval_artifact_hash, item.original_record_id): item
            for item in origins
        }.values()
    )
    retrievals = list(
        {
            (item.stage, item.retrieval_artifact_hash, item.fetch_id): item for item in retrievals
        }.values()
    )
    stages = tuple(dict.fromkeys(item.stage for item in origins))
    body: dict[str, Any] = {
        "title": representative.title,
        "authors": list(authors),
        "abstract": longest_abstract,
        "publication_date": (
            publication_date.isoformat() if publication_date is not None else None
        ),
        "venue": venue,
        "doi": doi,
        "repository_doi": repository_doi,
        "url": url
        or merged_module._doi_url(doi)  # noqa: SLF001
        or merged_module._doi_url(repository_doi),  # noqa: SLF001
        "citation_count": citation_record.citation_count if citation_record else None,
        "citation_count_source": (
            citation_record.citation_count_source if citation_record else None
        ),
        "citation_count_as_of": (
            citation_record.citation_count_as_of.isoformat()
            if citation_record is not None and citation_record.citation_count_as_of is not None
            else None
        ),
        "publication_status": status_record.publication_status,
        "status_source": status_record.status_source,
        "status_as_of": (
            status_record.status_as_of.isoformat()
            if status_record.status_as_of is not None
            else None
        ),
        "origins": [item.model_dump(mode="json") for item in origins],
        "retrievals": [item.model_dump(mode="json") for item in retrievals],
        "source_stages": list(stages),
    }
    digest = canonical_model_hash(body)
    return ContestMergedLiteratureRecord.model_validate(
        {
            **body,
            "record_id": f"merged-direction-paper-{digest[:16]}",
            "record_hash": digest,
        }
    )


def _consistent_layered_doi(
    entries: Sequence[tuple[bool, Any]],
    *,
    field: Literal["doi", "repository_doi"],
) -> str | None:
    values = {
        normalized
        for _targeted, record in entries
        if (normalized := normalize_doi(getattr(record, field)))
    }
    if len(values) > 1:
        raise ContestDirectionLayeredLiteratureError(
            f"deduplicated layered work has conflicting {field} values"
        )
    return next(iter(values), None)


def _build_record_binding(
    group: _LayerGroup,
    layered: ContestMergedLiteratureRecord,
) -> ContestDirectionLayeredRecordBinding:
    base_lineage: list[ContestDirectionLayeredQueryLineage] = []
    for record in group.base_records:
        for pointer in record.retrievals:
            kind: Literal["base_broad", "base_targeted"] = (
                "base_broad" if pointer.stage == "broad_discovery" else "base_targeted"
            )
            base_lineage.append(
                ContestDirectionLayeredQueryLineage(
                    round_index=1,
                    retrieval_kind=kind,
                    role=None,
                    retrieval_artifact_hash=pointer.retrieval_artifact_hash,
                    query_id=None,
                    query_hash=None,
                    logical_query=None,
                    executed_query=pointer.query,
                    source=pointer.source,
                    fetch_id=pointer.fetch_id,
                    fetch_hash=pointer.fetch_hash,
                )
            )
    repair_refs = tuple(_repair_record_ref(item) for item in group.repair_entries)
    lineage = tuple(
        {
            (
                item.retrieval_artifact_hash,
                item.fetch_id,
                item.source,
                item.executed_query,
            ): item
            for item in (
                *base_lineage,
                *(line for ref in repair_refs for line in ref.query_lineage),
            )
        }.values()
    )
    body: dict[str, Any] = {
        "layered_record_id": layered.record_id,
        "layered_record_hash": layered.record_hash,
        "base_record_ids": [item.record_id for item in group.base_records],
        "base_record_hashes": [item.record_hash for item in group.base_records],
        "repair_records": [item.model_dump(mode="json") for item in repair_refs],
        "round_query_lineage": [item.model_dump(mode="json") for item in lineage],
    }
    body["binding_hash"] = canonical_model_hash(body)
    return ContestDirectionLayeredRecordBinding.model_validate(body)


def _repair_record_ref(entry: _RepairEntry) -> ContestDirectionLayeredRepairRecordRef:
    repair = entry.artifact
    record = entry.record
    bindings_by_fetch = {item.fetch_id: item for item in repair.fetch_bindings}
    fetches = {item.fetch_id: item for item in repair.fetches}
    lineage: list[ContestDirectionLayeredQueryLineage] = []
    for pointer in record.retrievals:
        binding = bindings_by_fetch[pointer.fetch_id]
        fetch = fetches[pointer.fetch_id]
        lineage.append(
            ContestDirectionLayeredQueryLineage(
                round_index=repair.plan.round_index,
                retrieval_kind="gap_repair",
                role=binding.role,
                retrieval_artifact_hash=repair.artifact_hash,
                query_id=binding.repair_query_id,
                query_hash=binding.repair_query_hash,
                logical_query=binding.logical_query,
                executed_query=fetch.query,
                source=fetch.source,
                fetch_id=fetch.fetch_id,
                fetch_hash=fetch.fetch_hash,
            )
        )
    roles = tuple(dict.fromkeys(item.role for item in lineage))
    body: dict[str, Any] = {
        "round_index": repair.plan.round_index,
        "repair_artifact_hash": repair.artifact_hash,
        "repair_catalog_hash": repair.repair_catalog_hash,
        "original_record_id": record.record_id,
        "original_record_hash": record.record_hash,
        "roles": [item.value for item in roles if item is not None],
        "query_lineage": [item.model_dump(mode="json") for item in lineage],
    }
    body["ref_hash"] = canonical_model_hash(body)
    return ContestDirectionLayeredRepairRecordRef.model_validate(body)


def _repair_round_binding(
    repair: ContestDirectionGapRepairArtifact,
) -> ContestDirectionLayeredRepairRound:
    body: dict[str, Any] = {
        "round_index": repair.plan.round_index,
        "trigger_coverage_receipt_hash": repair.plan.trigger_coverage_receipt_hash,
        "gap_repair_projection_hash": repair.plan.gap_repair_projection_hash,
        "plan_hash": repair.plan.artifact_hash,
        "deficit_roles": [item.value for item in repair.plan.deficit_roles],
        "role_query_hashes": [item.query_hash for item in repair.plan.role_queries],
        "repair_artifact_hash": repair.artifact_hash,
        "repair_catalog_hash": repair.repair_catalog_hash,
        "retrieval_lineage_hash": repair.retrieval_lineage_hash,
        "fetch_count": len(repair.fetches),
        "record_count": len(repair.retrieved_records),
    }
    body["binding_hash"] = canonical_model_hash(body)
    return ContestDirectionLayeredRepairRound.model_validate(body)


def record_stage(kind: str) -> str:
    """Return the frozen merged-v1 stage label for a base lineage kind."""

    return "broad_discovery" if kind == "base_broad" else "targeted_direction"


__all__ = [
    "ContestDirectionLayeredBaseRecordBinding",
    "ContestDirectionLayeredLiteratureArtifact",
    "ContestDirectionLayeredLiteratureError",
    "ContestDirectionLayeredQueryLineage",
    "ContestDirectionLayeredRecordBinding",
    "ContestDirectionLayeredRepairRecordRef",
    "ContestDirectionLayeredRepairRound",
    "build_contest_direction_layered_literature",
    "load_contest_direction_layered_literature",
]
