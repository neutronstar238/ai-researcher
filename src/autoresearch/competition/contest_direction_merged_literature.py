"""Hash-bound merge of broad and direction-targeted literature searches.

The two input searches remain separate evidence events.  This module only builds
an immutable, deduplicated view for later program selection; it never rewrites the
two searches as one retrieval and never applies citation-count, venue, or
publication-status thresholds.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.contest_direction_focus_literature import (
    ContestDirectionFocusArtifact,
    ContestDirectionTargetedRetrievalBinding,
    load_contest_direction_focus_selection,
    load_contest_direction_targeted_retrieval,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    ContestDirectionLiteratureRecord,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.models import PublicationStatus, normalize_doi

_SHA256 = r"^[0-9a-f]{64}$"


class ContestDirectionMergedLiteratureError(RuntimeError):
    """Raised when the two-stage literature lineage cannot be verified."""


class ContestMergedLiteratureOrigin(StrictFrozenModel):
    """One exact upstream record retained inside a merged work."""

    stage: Literal["broad_discovery", "targeted_direction"]
    retrieval_artifact_hash: str = Field(pattern=_SHA256)
    retrieval_catalog_hash: str = Field(pattern=_SHA256)
    original_record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
    original_record_hash: str = Field(pattern=_SHA256)
    original_paper_hash: str = Field(pattern=_SHA256)
    title: str = Field(min_length=1)
    doi: str | None = None
    repository_doi: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    citation_count_source: str | None = None
    citation_count_as_of: date | None = None
    publication_status: PublicationStatus = "unknown"
    status_source: str | None = None
    status_as_of: date | None = None


class ContestMergedLiteratureRetrieval(StrictFrozenModel):
    """A source/query/fetch edge retained with its real retrieval stage."""

    stage: Literal["broad_discovery", "targeted_direction"]
    retrieval_artifact_hash: str = Field(pattern=_SHA256)
    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    fetch_hash: str = Field(pattern=_SHA256)
    source: str = Field(min_length=1)
    query: str = Field(min_length=1)
    retrieved_at: datetime


class ContestMergedLiteratureRecord(StrictFrozenModel):
    """One deduplicated work without losing either search's provenance."""

    record_id: str = Field(pattern=r"^merged-direction-paper-[0-9a-f]{16}$")
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    abstract: str | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    repository_doi: str | None = None
    url: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    citation_count_source: str | None = None
    citation_count_as_of: date | None = None
    publication_status: PublicationStatus = "unknown"
    status_source: str | None = None
    status_as_of: date | None = None
    origins: tuple[ContestMergedLiteratureOrigin, ...] = Field(min_length=1)
    retrievals: tuple[ContestMergedLiteratureRetrieval, ...] = Field(min_length=1)
    source_stages: tuple[Literal["broad_discovery", "targeted_direction"], ...] = Field(
        min_length=1,
        max_length=2,
    )
    record_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_record(self) -> ContestMergedLiteratureRecord:
        expected_stages = tuple(dict.fromkeys(item.stage for item in self.origins))
        if self.source_stages != expected_stages:
            raise ValueError("merged literature source stages mismatch")
        if any(item.stage not in self.source_stages for item in self.retrievals):
            raise ValueError("merged literature retrieval stage has no record origin")
        origin_keys = tuple(
            (item.stage, item.retrieval_artifact_hash, item.original_record_id)
            for item in self.origins
        )
        if len(origin_keys) != len(set(origin_keys)):
            raise ValueError("merged literature origins must be unique")
        retrieval_keys = tuple(
            (item.stage, item.retrieval_artifact_hash, item.fetch_id) for item in self.retrievals
        )
        if len(retrieval_keys) != len(set(retrieval_keys)):
            raise ValueError("merged literature retrieval edges must be unique")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"record_id", "record_hash"})
        )
        if self.record_hash != expected_hash:
            raise ValueError("merged literature record hash mismatch")
        if self.record_id != f"merged-direction-paper-{expected_hash[:16]}":
            raise ValueError("merged literature record ID mismatch")
        return self


class ContestDirectionMergedLiteratureArtifact(StrictFrozenModel):
    """Independent view binding both searches and the intervening focus decision."""

    schema_version: Literal["contest-direction-merged-literature-v1"] = (
        "contest-direction-merged-literature-v1"
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
    records: tuple[ContestMergedLiteratureRecord, ...] = Field(min_length=1)
    record_ids: tuple[str, ...] = Field(min_length=1)
    broad_record_count: int = Field(ge=1)
    targeted_record_count: int = Field(ge=1)
    merged_record_count: int = Field(ge=1)
    cross_stage_deduplicated_count: int = Field(ge=0)
    merged_catalog_hash: str = Field(pattern=_SHA256)
    retrieval_semantics: Literal["two_distinct_searches_not_one_retrieval"] = (
        "two_distinct_searches_not_one_retrieval"
    )
    selection_semantics: Literal["unfiltered_catalog_for_program_selection"] = (
        "unfiltered_catalog_for_program_selection"
    )
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestDirectionMergedLiteratureArtifact:
        actual_ids = tuple(item.record_id for item in self.records)
        if self.record_ids != actual_ids or len(actual_ids) != len(set(actual_ids)):
            raise ValueError("merged literature record IDs mismatch")
        if self.merged_record_count != len(self.records):
            raise ValueError("merged literature record count mismatch")
        expected_deduplicated = (
            self.broad_record_count + self.targeted_record_count - self.merged_record_count
        )
        if self.cross_stage_deduplicated_count != expected_deduplicated:
            raise ValueError("merged literature deduplication count mismatch")
        expected_catalog_hash = canonical_model_hash(
            {"records": [item.model_dump(mode="json") for item in self.records]}
        )
        if self.merged_catalog_hash != expected_catalog_hash:
            raise ValueError("merged literature catalog hash mismatch")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError("merged literature artifact hash mismatch")
        return self

    def objective_retrieval_catalog(self) -> tuple[dict[str, Any], ...]:
        """Project strict merged metadata for the existing planning selector."""

        projected: list[dict[str, Any]] = []
        for record in self.records:
            source_url = record.url or _doi_url(record.doi) or _doi_url(record.repository_doi)
            if not source_url:
                continue
            retrieved_at = min(item.retrieved_at for item in record.retrievals)
            retrieved_from = ",".join(dict.fromkeys(item.source for item in record.retrievals))
            retrieval_stage_sources = tuple(
                dict.fromkeys(f"{item.stage}:{item.source}" for item in record.retrievals)
            )
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
                    "paper_source": retrieved_from,
                    "retrieved_from": retrieved_from,
                    "retrieved_at": retrieved_at.isoformat(),
                    "record_sha256": record.record_hash,
                    "source_stages": list(record.source_stages),
                    "retrieval_stage_sources": list(retrieval_stage_sources),
                }
            )
        return tuple(projected)

    def objective_literature_catalog(self) -> tuple[str, ...]:
        """Return complete human/audit context without collapsing either search."""

        entries: list[str] = []
        for index, record in enumerate(self.records, start=1):
            authors = "、".join(record.authors) if record.authors else "作者信息未提供"
            citation_text = "未知（上游来源未提供；不得解释为0）"
            if record.citation_count is not None:
                citation_text = (
                    f"{record.citation_count}（来源：{record.citation_count_source or '未标注'}；"
                    f"截至：{record.citation_count_as_of.isoformat() if record.citation_count_as_of else '日期未标注'}）"
                )
            status_text = (
                f"{record.publication_status}（来源：{record.status_source or '未标注'}；"
                f"截至：{record.status_as_of.isoformat() if record.status_as_of else '日期未标注'}）"
            )
            origin_lines = "；".join(
                (
                    f"{item.stage}|artifact={item.retrieval_artifact_hash}|"
                    f"catalog={item.retrieval_catalog_hash}|record={item.original_record_id}|"
                    f"record_sha256={item.original_record_hash}"
                )
                for item in record.origins
            )
            retrieval_lines = "；".join(
                (
                    f"{item.stage}|{item.source}|{item.query}|"
                    f"{item.retrieved_at.isoformat()}|fetch={item.fetch_id}|"
                    f"fetch_sha256={item.fetch_hash}"
                )
                for item in record.retrievals
            )
            entries.append(
                "\n".join(
                    (
                        f"[{index}] record_id={record.record_id}",
                        f"题名：{record.title}",
                        f"作者：{authors}",
                        f"日期：{record.publication_date.isoformat() if record.publication_date else '日期未提供'}",
                        f"期刊或会议：{record.venue or '未提供'}",
                        f"正式发表DOI：{record.doi or '未提供'}",
                        f"仓储DOI：{record.repository_doi or '未提供'}",
                        f"发表状态：{status_text}",
                        f"URL：{record.url or _doi_url(record.doi) or _doi_url(record.repository_doi) or '未提供'}",
                        f"被引次数：{citation_text}",
                        "期刊影响因子：未知（合并检索未提供可核验数值，不按刊名推断）",
                        f"完整摘要：{record.abstract or '摘要未提供'}",
                        f"两阶段原始记录：{origin_lines}",
                        f"两阶段真实检索谱系：{retrieval_lines}",
                        f"merged_record_sha256={record.record_hash}",
                    )
                )
            )
        return tuple(entries)


def merge_contest_direction_literature(
    *,
    broad_literature: ContestDirectionLiteratureArtifact,
    focus: ContestDirectionFocusArtifact,
    targeted_binding: ContestDirectionTargetedRetrievalBinding,
    targeted_literature: ContestDirectionLiteratureArtifact,
    output_path: Path | str | None = None,
) -> ContestDirectionMergedLiteratureArtifact:
    """Merge validated broad and targeted catalogs while keeping both lineages."""

    broad, validated_focus, binding, targeted = _validate_inputs(
        broad_literature=broad_literature,
        focus=focus,
        targeted_binding=targeted_binding,
        targeted_literature=targeted_literature,
    )
    records = _merge_records(broad=broad, targeted=targeted)
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-merged-literature-v1",
        "parent_direction": broad.direction,
        "broad_literature_artifact_hash": broad.artifact_hash,
        "broad_literature_catalog_hash": broad.literature_catalog_hash,
        "focus_artifact_hash": validated_focus.artifact_hash,
        "selected_focus_id": validated_focus.selected_focus_id,
        "focused_direction_cn": validated_focus.focused_direction_cn,
        "targeted_retrieval_binding_hash": binding.artifact_hash,
        "targeted_literature_artifact_hash": targeted.artifact_hash,
        "targeted_literature_catalog_hash": targeted.literature_catalog_hash,
        "records": [item.model_dump(mode="json") for item in records],
        "record_ids": [item.record_id for item in records],
        "broad_record_count": len(broad.retrieved_records),
        "targeted_record_count": len(targeted.retrieved_records),
        "merged_record_count": len(records),
        "cross_stage_deduplicated_count": (
            len(broad.retrieved_records) + len(targeted.retrieved_records) - len(records)
        ),
        "merged_catalog_hash": canonical_model_hash(
            {"records": [item.model_dump(mode="json") for item in records]}
        ),
        "retrieval_semantics": "two_distinct_searches_not_one_retrieval",
        "selection_semantics": "unfiltered_catalog_for_program_selection",
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    artifact = ContestDirectionMergedLiteratureArtifact.model_validate(payload)
    if output_path is not None:
        write_json_model(output_path, artifact)
    return artifact


def load_contest_direction_merged_literature(
    path: Path | str,
    *,
    broad_literature_path: Path | str,
    focus_path: Path | str,
    targeted_binding_path: Path | str,
    targeted_literature_path: Path | str,
    executable_adapter_capabilities: Sequence[Mapping[str, Any]] = (),
) -> ContestDirectionMergedLiteratureArtifact:
    """Reload every stage and reject a merged view that cannot be rederived."""

    broad = ContestDirectionLiteratureArtifact.model_validate_json(
        Path(broad_literature_path).read_text(encoding="utf-8")
    )
    focus = load_contest_direction_focus_selection(
        focus_path,
        broad_literature=broad,
        executable_adapter_capabilities=executable_adapter_capabilities,
    )
    binding = load_contest_direction_targeted_retrieval(
        targeted_binding_path,
        focus=focus,
    )
    targeted = ContestDirectionLiteratureArtifact.model_validate_json(
        Path(targeted_literature_path).read_text(encoding="utf-8")
    )
    persisted = ContestDirectionMergedLiteratureArtifact.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    rederived = merge_contest_direction_literature(
        broad_literature=broad,
        focus=focus,
        targeted_binding=binding,
        targeted_literature=targeted,
    )
    if persisted != rederived:
        raise ContestDirectionMergedLiteratureError(
            "merged literature differs from the reloaded two-stage lineage"
        )
    return persisted


def _validate_inputs(
    *,
    broad_literature: ContestDirectionLiteratureArtifact,
    focus: ContestDirectionFocusArtifact,
    targeted_binding: ContestDirectionTargetedRetrievalBinding,
    targeted_literature: ContestDirectionLiteratureArtifact,
) -> tuple[
    ContestDirectionLiteratureArtifact,
    ContestDirectionFocusArtifact,
    ContestDirectionTargetedRetrievalBinding,
    ContestDirectionLiteratureArtifact,
]:
    if not isinstance(broad_literature, ContestDirectionLiteratureArtifact):
        raise ContestDirectionMergedLiteratureError("broad literature has the wrong type")
    if not isinstance(focus, ContestDirectionFocusArtifact):
        raise ContestDirectionMergedLiteratureError("focus artifact has the wrong type")
    if not isinstance(targeted_binding, ContestDirectionTargetedRetrievalBinding):
        raise ContestDirectionMergedLiteratureError("targeted binding has the wrong type")
    if not isinstance(targeted_literature, ContestDirectionLiteratureArtifact):
        raise ContestDirectionMergedLiteratureError("targeted literature has the wrong type")
    broad = ContestDirectionLiteratureArtifact.model_validate(
        broad_literature.model_dump(mode="json")
    )
    validated_focus = ContestDirectionFocusArtifact.model_validate(focus.model_dump(mode="json"))
    binding = ContestDirectionTargetedRetrievalBinding.model_validate(
        targeted_binding.model_dump(mode="json")
    )
    targeted = ContestDirectionLiteratureArtifact.model_validate(
        targeted_literature.model_dump(mode="json")
    )
    if broad.method_skills or targeted.method_skills:
        raise ContestDirectionMergedLiteratureError(
            "two-stage literature must precede Skill body injection"
        )
    if (
        validated_focus.direction != broad.direction
        or validated_focus.broad_literature_artifact_hash != broad.artifact_hash
        or validated_focus.broad_literature_catalog_hash != broad.literature_catalog_hash
    ):
        raise ContestDirectionMergedLiteratureError("focus does not bind the broad search")
    if (
        binding.focus_artifact_hash != validated_focus.artifact_hash
        or binding.selected_focus_id != validated_focus.selected_focus_id
        or binding.broad_literature_artifact_hash != broad.artifact_hash
        or binding.targeted_literature_artifact_hash != targeted.artifact_hash
        or binding.targeted_literature_catalog_hash != targeted.literature_catalog_hash
        or binding.targeted_search_context != targeted.direction
    ):
        raise ContestDirectionMergedLiteratureError(
            "targeted search does not bind the broad-search focus lineage"
        )
    return broad, validated_focus, binding, targeted


def _merge_records(
    *,
    broad: ContestDirectionLiteratureArtifact,
    targeted: ContestDirectionLiteratureArtifact,
) -> tuple[ContestMergedLiteratureRecord, ...]:
    staged: list[
        tuple[
            Literal["broad_discovery", "targeted_direction"],
            ContestDirectionLiteratureArtifact,
            ContestDirectionLiteratureRecord,
        ]
    ] = []
    # Targeted records lead the view because it is the direction-specific retrieval;
    # broad records remain present as discovery context.  This is ordering, not a gate.
    staged.extend(("targeted_direction", targeted, item) for item in targeted.retrieved_records)
    staged.extend(("broad_discovery", broad, item) for item in broad.retrieved_records)
    groups: list[
        list[
            tuple[
                Literal["broad_discovery", "targeted_direction"],
                ContestDirectionLiteratureArtifact,
                ContestDirectionLiteratureRecord,
            ]
        ]
    ] = []
    for entry in staged:
        for group in groups:
            if any(_same_work(entry[2], existing[2]) for existing in group):
                group.append(entry)
                break
        else:
            groups.append([entry])
    return tuple(_merge_group(group) for group in groups)


def _same_work(
    left: ContestDirectionLiteratureRecord,
    right: ContestDirectionLiteratureRecord,
) -> bool:
    left_doi = normalize_doi(left.doi)
    right_doi = normalize_doi(right.doi)
    left_repository_doi = normalize_doi(left.repository_doi)
    right_repository_doi = normalize_doi(right.repository_doi)
    if left_doi and right_doi and left_doi != right_doi:
        return False
    if left_repository_doi and right_repository_doi and left_repository_doi != right_repository_doi:
        return False
    if (left_doi and right_repository_doi and left_doi == right_repository_doi) or (
        left_repository_doi and right_doi and left_repository_doi == right_doi
    ):
        return False
    if left_doi and right_doi and left_doi == right_doi:
        return True
    if left_repository_doi and right_repository_doi and left_repository_doi == right_repository_doi:
        return True
    left_title = _normalize_identity_text(left.title)
    right_title = _normalize_identity_text(right.title)
    if not left_title or not right_title:
        return False
    title_similarity = SequenceMatcher(None, left_title, right_title).ratio()
    if title_similarity < 0.92:
        return False
    left_authors = {
        normalized
        for item in left.authors
        if item.strip() and (normalized := _normalize_author(item))
    }
    right_authors = {
        normalized
        for item in right.authors
        if item.strip() and (normalized := _normalize_author(item))
    }
    return bool(left_authors and right_authors and left_authors.intersection(right_authors))


def _merge_group(
    group: Sequence[
        tuple[
            Literal["broad_discovery", "targeted_direction"],
            ContestDirectionLiteratureArtifact,
            ContestDirectionLiteratureRecord,
        ]
    ],
) -> ContestMergedLiteratureRecord:
    representative = max(
        group,
        key=lambda item: (
            bool(item[2].doi or item[2].repository_doi),
            bool(item[2].venue),
            len(item[2].authors),
            bool(item[2].url),
            item[2].publication_date or date.min,
            item[0] == "targeted_direction",
            item[2].record_hash,
        ),
    )[2]
    longest_abstract = max(
        (item[2].abstract for item in group if item[2].abstract),
        key=len,
        default=None,
    )
    citation_candidates = tuple(item[2] for item in group if item[2].citation_count is not None)
    citation_verified = tuple(
        item
        for item in citation_candidates
        if item.citation_count_source and item.citation_count_as_of
    )
    citation_record = max(
        citation_verified or citation_candidates,
        key=lambda item: (
            item.citation_count or 0,
            item.citation_count_as_of or date.min,
            bool(item.citation_count_source),
            item.record_hash,
        ),
        default=None,
    )
    status_entry = max(
        group,
        key=lambda item: (
            _status_priority(item[2].publication_status),
            item[2].status_as_of or date.min,
            bool(item[2].status_source),
            item[0] == "targeted_direction",
            item[2].record_hash,
        ),
    )
    status_record = status_entry[2]
    doi = _consistent_doi(group, field="doi")
    repository_doi = _consistent_doi(group, field="repository_doi")
    authors = max(
        (item[2].authors for item in group),
        key=lambda values: (len(values), sum(len(value) for value in values)),
    )
    publication_date = max(
        (item[2].publication_date for item in group if item[2].publication_date),
        default=None,
    )
    venue = next(
        (
            item[2].venue
            for item in sorted(
                group,
                key=lambda entry: (
                    entry[2].publication_status == "published",
                    bool(entry[2].doi),
                    entry[0] == "targeted_direction",
                ),
                reverse=True,
            )
            if item[2].venue
        ),
        None,
    )
    url = next(
        (
            item[2].url
            for item in sorted(
                group,
                key=lambda entry: (
                    entry[2].publication_status == "published",
                    bool(entry[2].doi),
                    entry[0] == "targeted_direction",
                ),
                reverse=True,
            )
            if item[2].url
        ),
        None,
    )
    origins: list[ContestMergedLiteratureOrigin] = []
    retrievals: list[ContestMergedLiteratureRetrieval] = []
    for stage, artifact, record in group:
        fetches = {item.fetch_id: item for item in artifact.fetches}
        origins.append(
            ContestMergedLiteratureOrigin(
                stage=stage,
                retrieval_artifact_hash=artifact.artifact_hash,
                retrieval_catalog_hash=artifact.literature_catalog_hash,
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
        for pointer in record.retrievals:
            fetch = fetches.get(pointer.fetch_id)
            if fetch is None:
                raise ContestDirectionMergedLiteratureError(
                    "record points to a fetch outside its retrieval artifact"
                )
            retrievals.append(
                ContestMergedLiteratureRetrieval(
                    stage=stage,
                    retrieval_artifact_hash=artifact.artifact_hash,
                    fetch_id=pointer.fetch_id,
                    fetch_hash=fetch.fetch_hash,
                    source=pointer.source,
                    query=pointer.query,
                    retrieved_at=pointer.retrieved_at,
                )
            )
    # Entries already originate from deduplicated artifacts.  Cross-stage duplicate
    # pointers are retained because their stage/hash differs; exact duplicates cannot
    # occur after the tuple-key validation above.
    source_stages = tuple(dict.fromkeys(item.stage for item in origins))
    payload: dict[str, Any] = {
        "title": representative.title,
        "authors": list(authors),
        "abstract": longest_abstract,
        "publication_date": (
            publication_date.isoformat() if publication_date is not None else None
        ),
        "venue": venue,
        "doi": doi,
        "repository_doi": repository_doi,
        "url": url or _doi_url(doi) or _doi_url(repository_doi),
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
        "source_stages": list(source_stages),
    }
    record_hash = canonical_model_hash(payload)
    payload["record_hash"] = record_hash
    payload["record_id"] = f"merged-direction-paper-{record_hash[:16]}"
    return ContestMergedLiteratureRecord.model_validate(payload)


def _status_priority(status: PublicationStatus) -> int:
    priority: dict[PublicationStatus, int] = {
        "unknown": 0,
        "preprint": 1,
        "published": 2,
        "withdrawn": 3,
        "retracted": 4,
    }
    return priority[status]


def _consistent_doi(
    group: Sequence[
        tuple[
            Literal["broad_discovery", "targeted_direction"],
            ContestDirectionLiteratureArtifact,
            ContestDirectionLiteratureRecord,
        ]
    ],
    *,
    field: Literal["doi", "repository_doi"],
) -> str | None:
    values = {
        normalized
        for _stage, _artifact, record in group
        if (normalized := normalize_doi(getattr(record, field)))
    }
    if len(values) > 1:
        raise ContestDirectionMergedLiteratureError(
            f"deduplicated work has conflicting {field} values"
        )
    return next(iter(values), None)


def _normalize_author(author: str) -> str:
    return _normalize_identity_text(author)


def _normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.replace("_", " ").split())


def _doi_url(value: str | None) -> str | None:
    normalized = normalize_doi(value)
    return f"https://doi.org/{normalized}" if normalized else None


__all__ = [
    "ContestDirectionMergedLiteratureArtifact",
    "ContestDirectionMergedLiteratureError",
    "ContestMergedLiteratureOrigin",
    "ContestMergedLiteratureRecord",
    "ContestMergedLiteratureRetrieval",
    "load_contest_direction_merged_literature",
    "merge_contest_direction_literature",
]
