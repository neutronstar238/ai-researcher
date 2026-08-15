"""Sparse real retrieval for planning-literature role deficits.

This module deliberately does not generate queries.  It consumes a frozen set
of role-specific repair queries and executes only the Cartesian product of
those deficit roles and the caller's real search sources.  The ordinary
four-role direction-literature artifact remains unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition import contest_direction_literature as literature_module
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionFetchRecord,
    ContestDirectionLiteratureRecord,
    ContestDirectionRetrievalPointer,
    DirectionSearchCallable,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureRole,
    PlanningLiteratureRoleQuery,
)
from autoresearch.competition.contest_planning_literature_gap_repair import (
    PlanningLiteratureGapRepairProjection,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.models import AcademicPaper, PublicationStatus

_SHA256 = r"^[0-9a-f]{64}$"
_REQUIRED_ROLES = frozenset(
    {
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.METHOD_FOUNDATION,
        PlanningLiteratureRole.MECHANISM_OR_NULL,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    }
)
_COMPILER_VERSION: Literal["source-query-compiler-v4"] = "source-query-compiler-v4"
_ROLE_MAXIMUM_MISSING_SLOTS = {
    PlanningLiteratureRole.DIRECT_CORE: 2,
    PlanningLiteratureRole.METHOD_FOUNDATION: 1,
    PlanningLiteratureRole.MECHANISM_OR_NULL: 1,
    PlanningLiteratureRole.COUNTEREVIDENCE: 1,
}


class ContestDirectionGapRepairError(RuntimeError):
    """Raised when a sparse repair request or its persisted lineage is invalid."""


class ContestDirectionGapRepairRoleQuery(StrictFrozenModel):
    """One diagnosed role deficit and its exact R1-to-repair query binding."""

    role: PlanningLiteratureRole
    missing_slots: int = Field(ge=1)
    parent_role_query: PlanningLiteratureRoleQuery
    repair_role_query: PlanningLiteratureRoleQuery
    query_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_query(self) -> ContestDirectionGapRepairRoleQuery:
        if self.role not in _REQUIRED_ROLES:
            raise ValueError("gap repair is allowed only for required planning roles")
        if (
            self.parent_role_query.role is not self.role
            or self.repair_role_query.role is not self.role
        ):
            raise ValueError("gap-repair parent and repair query roles must match the deficit role")
        if self.missing_slots > _ROLE_MAXIMUM_MISSING_SLOTS[self.role]:
            raise ValueError("gap-repair missing slots exceed the frozen role quota")
        if self.parent_role_query.query_id == self.repair_role_query.query_id:
            raise ValueError("repair query ID must be distinct from its parent query ID")
        if (
            len(self.parent_role_query.must_groups) != 2
            or len(self.repair_role_query.must_groups) != 2
            or self.parent_role_query.must_groups[0] != self.repair_role_query.must_groups[0]
            or self.parent_role_query.must_groups[1] == self.repair_role_query.must_groups[1]
        ):
            raise ValueError(
                "repair query must preserve the R1 first group and replace its second group"
            )
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"query_hash"}))
        if self.query_hash != expected:
            raise ValueError("gap-repair role-query hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionGapRepairRoleQuery:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, query_hash="0" * 64)
        payload["query_hash"] = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"query_hash"})
        )
        return cls.model_validate(payload)


class ContestDirectionGapRepairPlan(StrictFrozenModel):
    """Content-addressed sparse execution plan derived from one failed coverage round."""

    schema_version: Literal["contest-direction-gap-repair-plan-v1"] = (
        "contest-direction-gap-repair-plan-v1"
    )
    base_merged_artifact_hash: str = Field(pattern=_SHA256)
    base_merged_catalog_hash: str = Field(pattern=_SHA256)
    trigger_coverage_receipt_hash: str = Field(pattern=_SHA256)
    gap_repair_projection_hash: str = Field(pattern=_SHA256)
    round_index: int = Field(ge=2)
    deficit_roles: tuple[PlanningLiteratureRole, ...] = Field(min_length=1, max_length=4)
    role_queries: tuple[ContestDirectionGapRepairRoleQuery, ...] = Field(
        min_length=1,
        max_length=4,
    )
    query_count: int = Field(ge=1, le=4)
    total_missing_slots: int = Field(ge=1)
    query_plan_hash: str = Field(pattern=_SHA256)
    query_model_calls: Literal[0] = 0
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_plan(self) -> ContestDirectionGapRepairPlan:
        if len(self.deficit_roles) != len(set(self.deficit_roles)):
            raise ValueError("gap-repair deficit roles must be unique")
        if any(role not in _REQUIRED_ROLES for role in self.deficit_roles):
            raise ValueError("gap-repair plan contains a non-required role")
        query_roles = tuple(item.role for item in self.role_queries)
        if query_roles != self.deficit_roles:
            raise ValueError("gap-repair role queries must exactly match deficit roles")
        query_ids = tuple(item.repair_role_query.query_id for item in self.role_queries)
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("gap-repair query IDs must be unique")
        if self.query_count != len(self.role_queries):
            raise ValueError("gap-repair query count mismatch")
        if self.total_missing_slots != sum(item.missing_slots for item in self.role_queries):
            raise ValueError("gap-repair missing-slot count mismatch")
        expected_plan_hash = canonical_model_hash(
            {
                "base_merged_artifact_hash": self.base_merged_artifact_hash,
                "base_merged_catalog_hash": self.base_merged_catalog_hash,
                "trigger_coverage_receipt_hash": self.trigger_coverage_receipt_hash,
                "gap_repair_projection_hash": self.gap_repair_projection_hash,
                "round_index": self.round_index,
                "deficit_roles": [item.value for item in self.deficit_roles],
                "role_queries": [item.model_dump(mode="json") for item in self.role_queries],
            }
        )
        if self.query_plan_hash != expected_plan_hash:
            raise ValueError("gap-repair query-plan hash mismatch")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError("gap-repair plan artifact hash mismatch")
        return self


class ContestDirectionGapRepairFetchBinding(StrictFrozenModel):
    """Exact role/query/source edge for one real fetch receipt."""

    round_index: int = Field(ge=2)
    role: PlanningLiteratureRole
    query_index: int = Field(ge=1, le=4)
    repair_query_id: str = Field(min_length=1)
    repair_query_hash: str = Field(pattern=_SHA256)
    logical_query: str = Field(min_length=1)
    source: str = Field(min_length=1)
    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    fetch_hash: str = Field(pattern=_SHA256)


class ContestDirectionGapRepairPaperPayload(StrictFrozenModel):
    """Frozen public metadata for one normalized source result."""

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
    source: str = Field(min_length=1)

    def to_academic_paper(self) -> AcademicPaper:
        """Reconstruct the shared normalized paper model for deterministic replay."""

        return AcademicPaper.model_validate(self.model_dump(mode="json"))


class ContestDirectionGapRepairFetchPayload(StrictFrozenModel):
    """Exact normalized papers returned by one source call, including empty calls."""

    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    fetch_hash: str = Field(pattern=_SHA256)
    status: Literal["succeeded", "failed"]
    papers: tuple[ContestDirectionGapRepairPaperPayload, ...] = ()
    result_hash: str | None = Field(default=None, pattern=_SHA256)
    payload_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_payload(self) -> ContestDirectionGapRepairFetchPayload:
        expected_result = (
            canonical_model_hash(
                {"papers": [paper.model_dump(mode="json") for paper in self.papers]}
            )
            if self.status == "succeeded"
            else None
        )
        if self.status == "failed" and self.papers:
            raise ValueError("failed gap-repair fetch cannot retain returned papers")
        if self.result_hash != expected_result:
            raise ValueError("gap-repair fetch-payload result hash mismatch")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"payload_hash"}))
        if self.payload_hash != expected_hash:
            raise ValueError("gap-repair fetch-payload hash mismatch")
        return self


class ContestDirectionGapRepairArtifact(StrictFrozenModel):
    """Fully replayable sparse retrieval output, including empty and failed calls."""

    schema_version: Literal["contest-direction-gap-repair-retrieval-v1"] = (
        "contest-direction-gap-repair-retrieval-v1"
    )
    plan: ContestDirectionGapRepairPlan
    plan_hash: str = Field(pattern=_SHA256)
    query_compiler_version: Literal["source-query-compiler-v4"] = _COMPILER_VERSION
    retriever_sources: tuple[str, ...] = Field(min_length=1)
    source_count: int = Field(ge=1)
    query_count: int = Field(ge=1, le=4)
    fetch_pair_count: int = Field(ge=1)
    fetches: tuple[ContestDirectionFetchRecord, ...] = Field(min_length=1)
    fetch_bindings: tuple[ContestDirectionGapRepairFetchBinding, ...] = Field(min_length=1)
    fetch_payloads: tuple[ContestDirectionGapRepairFetchPayload, ...] = Field(min_length=1)
    retrieved_records: tuple[ContestDirectionLiteratureRecord, ...] = ()
    raw_hit_count: int = Field(ge=0)
    deduplicated_count: int = Field(ge=0)
    repair_catalog_hash: str = Field(pattern=_SHA256)
    retrieval_lineage_hash: str = Field(pattern=_SHA256)
    repair_outcome: Literal["records_retrieved", "no_valid_records"]
    query_model_calls: Literal[0] = 0
    retrieval_scope: Literal["deficit_roles_only_sparse_source_matrix"] = (
        "deficit_roles_only_sparse_source_matrix"
    )
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestDirectionGapRepairArtifact:
        if self.plan_hash != self.plan.artifact_hash:
            raise ValueError("gap-repair retrieval plan hash mismatch")
        if len(self.retriever_sources) != len(set(self.retriever_sources)):
            raise ValueError("gap-repair retriever sources must be unique")
        if self.source_count != len(self.retriever_sources):
            raise ValueError("gap-repair source count mismatch")
        if self.query_count != self.plan.query_count:
            raise ValueError("gap-repair retrieval query count mismatch")
        expected_pair_count = self.source_count * self.query_count
        if self.fetch_pair_count != expected_pair_count:
            raise ValueError("gap-repair fetch-pair count mismatch")
        if (
            len(self.fetches) != expected_pair_count
            or len(self.fetch_bindings) != len(self.fetches)
            or len(self.fetch_payloads) != len(self.fetches)
        ):
            raise ValueError("gap-repair sparse fetch matrix is incomplete")

        expected_pairs = {
            (query_index, source)
            for query_index in range(1, self.query_count + 1)
            for source in self.retriever_sources
        }
        actual_pairs = {(item.query_index, item.source) for item in self.fetches}
        binding_pairs = {(item.query_index, item.source) for item in self.fetch_bindings}
        if (
            actual_pairs != expected_pairs
            or binding_pairs != expected_pairs
            or len(actual_pairs) != len(self.fetches)
            or len(binding_pairs) != len(self.fetch_bindings)
        ):
            raise ValueError("gap-repair fetches must cover deficit queries x sources once")

        fetches_by_pair = {(item.query_index, item.source): item for item in self.fetches}
        payloads_by_id = {item.fetch_id: item for item in self.fetch_payloads}
        if len(payloads_by_id) != len(self.fetch_payloads):
            raise ValueError("gap-repair fetch payload IDs must be unique")
        for binding in self.fetch_bindings:
            role_query = self.plan.role_queries[binding.query_index - 1]
            fetch = fetches_by_pair[(binding.query_index, binding.source)]
            expected_query = literature_module._compile_source_query(  # noqa: SLF001
                binding.source,
                role_query.repair_role_query.raw_query,
                compiler_version=self.query_compiler_version,
            )
            if (
                binding.round_index != self.plan.round_index
                or binding.role is not role_query.role
                or binding.repair_query_id != role_query.repair_role_query.query_id
                or binding.repair_query_hash != role_query.query_hash
                or binding.logical_query != role_query.repair_role_query.raw_query
                or binding.fetch_id != fetch.fetch_id
                or binding.fetch_hash != fetch.fetch_hash
                or fetch.query != expected_query
            ):
                raise ValueError("gap-repair fetch binding does not match its exact query/fetch")

        replay_hits: list[tuple[AcademicPaper, ContestDirectionRetrievalPointer]] = []
        for fetch in self.fetches:
            fetch_payload = payloads_by_id.get(fetch.fetch_id)
            if fetch_payload is None or (
                fetch_payload.fetch_hash != fetch.fetch_hash
                or fetch_payload.status != fetch.status
                or fetch_payload.result_hash != fetch.result_hash
                or len(fetch_payload.papers) != fetch.returned_count
            ):
                raise ValueError("gap-repair fetch payload does not match its fetch receipt")
            pointer = ContestDirectionRetrievalPointer(
                fetch_id=fetch.fetch_id,
                source=fetch.source,
                query=fetch.query,
                retrieved_at=fetch.retrieved_at,
            )
            replay_hits.extend(
                (paper.to_academic_paper(), pointer) for paper in fetch_payload.papers
            )
        replay_records = (
            literature_module._deduplicate_hits(replay_hits)  # noqa: SLF001
            if replay_hits
            else ()
        )
        if self.retrieved_records != replay_records:
            raise ValueError("gap-repair records do not replay from frozen fetch payloads")

        fetches_by_id = {item.fetch_id: item for item in self.fetches}
        for record in self.retrieved_records:
            for pointer in record.retrievals:
                pointer_fetch = fetches_by_id.get(pointer.fetch_id)
                if pointer_fetch is None or (
                    pointer.source != pointer_fetch.source
                    or pointer.query != pointer_fetch.query
                    or pointer.retrieved_at != pointer_fetch.retrieved_at
                ):
                    raise ValueError("gap-repair record points outside the real fetch matrix")
        if self.raw_hit_count != sum(
            item.returned_count for item in self.fetches if item.status == "succeeded"
        ):
            raise ValueError("gap-repair raw-hit count mismatch")
        if self.deduplicated_count != self.raw_hit_count - len(self.retrieved_records):
            raise ValueError("gap-repair deduplicated count mismatch")
        expected_outcome = "records_retrieved" if self.retrieved_records else "no_valid_records"
        if self.repair_outcome != expected_outcome:
            raise ValueError("gap-repair outcome mismatch")
        expected_catalog_hash = canonical_model_hash(
            {"records": [item.model_dump(mode="json") for item in self.retrieved_records]}
        )
        if self.repair_catalog_hash != expected_catalog_hash:
            raise ValueError("gap-repair catalog hash mismatch")
        expected_lineage_hash = canonical_model_hash(
            {
                "fetches": [item.model_dump(mode="json") for item in self.fetches],
                "fetch_bindings": [item.model_dump(mode="json") for item in self.fetch_bindings],
                "fetch_payloads": [item.model_dump(mode="json") for item in self.fetch_payloads],
            }
        )
        if self.retrieval_lineage_hash != expected_lineage_hash:
            raise ValueError("gap-repair retrieval-lineage hash mismatch")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError("gap-repair retrieval artifact hash mismatch")
        return self


def build_contest_direction_gap_repair_plan(
    *,
    base_merged_artifact_hash: str,
    base_merged_catalog_hash: str,
    trigger_coverage_receipt_hash: str,
    gap_repair_projection_hash: str,
    round_index: int,
    deficit_roles: Sequence[PlanningLiteratureRole | str],
    role_queries: Sequence[ContestDirectionGapRepairRoleQuery],
) -> ContestDirectionGapRepairPlan:
    """Freeze the exact diagnosed-role subset selected from a repair projection."""

    normalized_roles = tuple(PlanningLiteratureRole(item) for item in deficit_roles)
    normalized_queries = tuple(role_queries)
    if tuple(item.role for item in normalized_queries) != normalized_roles:
        raise ContestDirectionGapRepairError(
            "gap-repair role queries must exactly match the diagnosed deficit roles"
        )
    plan_payload = {
        "base_merged_artifact_hash": base_merged_artifact_hash,
        "base_merged_catalog_hash": base_merged_catalog_hash,
        "trigger_coverage_receipt_hash": trigger_coverage_receipt_hash,
        "gap_repair_projection_hash": gap_repair_projection_hash,
        "round_index": round_index,
        "deficit_roles": [item.value for item in normalized_roles],
        "role_queries": [item.model_dump(mode="json") for item in normalized_queries],
    }
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-gap-repair-plan-v1",
        **plan_payload,
        "query_count": len(normalized_queries),
        "total_missing_slots": sum(item.missing_slots for item in normalized_queries),
        "query_plan_hash": canonical_model_hash(plan_payload),
        "query_model_calls": 0,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    try:
        return ContestDirectionGapRepairPlan.model_validate(payload)
    except ValueError as exc:
        raise ContestDirectionGapRepairError(str(exc)) from exc


def build_contest_direction_gap_repair_plan_from_projection(
    *,
    base_merged_artifact_hash: str,
    base_merged_catalog_hash: str,
    projection: PlanningLiteratureGapRepairProjection,
    round_index: int = 2,
) -> ContestDirectionGapRepairPlan:
    """Select only diagnosed roles from a fully replayed four-role R2 projection."""

    validated = PlanningLiteratureGapRepairProjection.model_validate(
        projection.model_dump(mode="json")
    )
    diagnosis = validated.diagnosis
    if not diagnosis.supplemental_retrieval_allowed or not diagnosis.repairable_roles:
        raise ContestDirectionGapRepairError(
            "gap-repair projection does not authorize supplemental retrieval"
        )
    parent_by_role = {item.role: item for item in diagnosis.coverage_receipt.role_queries}
    repair_by_role = {item.role: item for item in validated.r2_role_queries}
    diagnostic_by_role = {item.role: item for item in diagnosis.role_diagnostics}
    role_queries: list[ContestDirectionGapRepairRoleQuery] = []
    for role in diagnosis.repairable_roles:
        parent = parent_by_role.get(role)
        repair = repair_by_role.get(role)
        role_diagnosis = diagnostic_by_role.get(role)
        if parent is None or repair is None or role_diagnosis is None:
            raise ContestDirectionGapRepairError(
                f"gap-repair projection omitted the diagnosed {role.value} lineage"
            )
        if role_diagnosis.missing_anchor_count < 1:
            raise ContestDirectionGapRepairError(
                f"diagnosed repair role {role.value} has no missing anchor slot"
            )
        if repair.query_id == parent.query_id:
            raise ContestDirectionGapRepairError(
                f"R2 query ID for {role.value} does not differ from R1"
            )
        if (
            len(parent.must_groups) != 2
            or len(repair.must_groups) != 2
            or repair.must_groups[0] != parent.must_groups[0]
            or repair.must_groups[1] == parent.must_groups[1]
        ):
            raise ContestDirectionGapRepairError(
                f"R2 query for {role.value} must preserve the first group and replace the second"
            )
        role_queries.append(
            ContestDirectionGapRepairRoleQuery.create(
                role=role,
                missing_slots=role_diagnosis.missing_anchor_count,
                parent_role_query=parent,
                repair_role_query=repair,
            )
        )
    return build_contest_direction_gap_repair_plan(
        base_merged_artifact_hash=base_merged_artifact_hash,
        base_merged_catalog_hash=base_merged_catalog_hash,
        trigger_coverage_receipt_hash=validated.coverage_receipt_hash,
        gap_repair_projection_hash=validated.projection_hash,
        round_index=round_index,
        deficit_roles=diagnosis.repairable_roles,
        role_queries=tuple(role_queries),
    )


def retrieve_contest_direction_gap_repair(
    *,
    plan: ContestDirectionGapRepairPlan,
    searchers: Mapping[str, DirectionSearchCallable],
    max_results_per_search: int = 20,
    retrieved_at: datetime | None = None,
    output_path: Path | str | None = None,
) -> ContestDirectionGapRepairArtifact:
    """Execute only ``plan.role_queries x searchers`` and retain every real attempt."""

    validated_plan = ContestDirectionGapRepairPlan.model_validate(plan.model_dump(mode="json"))
    if max_results_per_search < 1:
        raise ContestDirectionGapRepairError("max_results_per_search must be positive")
    try:
        normalized_searchers = literature_module._normalize_searchers(searchers)  # noqa: SLF001
    except Exception as exc:
        raise ContestDirectionGapRepairError(str(exc)) from exc
    timestamp = literature_module._normalize_datetime(retrieved_at)  # noqa: SLF001
    compiled_search_plan: list[
        tuple[
            int,
            ContestDirectionGapRepairRoleQuery,
            str,
            DirectionSearchCallable,
            str,
        ]
    ] = []
    for query_index, role_query in enumerate(validated_plan.role_queries, start=1):
        logical_query = role_query.repair_role_query.raw_query
        for source, searcher in normalized_searchers.items():
            try:
                executed_query = literature_module._compile_source_query(  # noqa: SLF001
                    source,
                    logical_query,
                    compiler_version=_COMPILER_VERSION,
                )
            except Exception as exc:
                raise ContestDirectionGapRepairError(
                    "gap-repair query compilation failed before any source call: "
                    f"role={role_query.role.value}, source={source}: {exc}"
                ) from exc
            compiled_search_plan.append((query_index, role_query, source, searcher, executed_query))

    fetches: list[ContestDirectionFetchRecord] = []
    bindings: list[ContestDirectionGapRepairFetchBinding] = []
    fetch_payloads: list[ContestDirectionGapRepairFetchPayload] = []
    hits: list[tuple[AcademicPaper, ContestDirectionRetrievalPointer]] = []
    for query_index, role_query, source, searcher, executed_query in compiled_search_plan:
        logical_query = role_query.repair_role_query.raw_query
        normalized_papers: list[AcademicPaper] = []
        try:
            normalized_papers = literature_module._normalize_search_results(  # noqa: SLF001
                searcher(executed_query, limit=max_results_per_search)
            )
        except Exception as exc:  # noqa: BLE001 - each real source degrades separately.
            fetch = literature_module._build_fetch_record(  # noqa: SLF001
                source=source,
                query=executed_query,
                query_index=query_index,
                retrieved_at=timestamp,
                papers=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            fetch = literature_module._build_fetch_record(  # noqa: SLF001
                source=source,
                query=executed_query,
                query_index=query_index,
                retrieved_at=timestamp,
                papers=normalized_papers,
                error=None,
            )
            pointer = ContestDirectionRetrievalPointer(
                fetch_id=fetch.fetch_id,
                source=source,
                query=executed_query,
                retrieved_at=timestamp,
            )
            hits.extend((paper, pointer) for paper in normalized_papers)
        fetches.append(fetch)
        fetch_payload_body: dict[str, Any] = {
            "fetch_id": fetch.fetch_id,
            "fetch_hash": fetch.fetch_hash,
            "status": fetch.status,
            "papers": [item.model_dump(mode="json") for item in normalized_papers],
            "result_hash": fetch.result_hash,
        }
        fetch_payload_body["payload_hash"] = canonical_model_hash(fetch_payload_body)
        fetch_payloads.append(
            ContestDirectionGapRepairFetchPayload.model_validate(fetch_payload_body)
        )
        bindings.append(
            ContestDirectionGapRepairFetchBinding(
                round_index=validated_plan.round_index,
                role=role_query.role,
                query_index=query_index,
                repair_query_id=role_query.repair_role_query.query_id,
                repair_query_hash=role_query.query_hash,
                logical_query=logical_query,
                source=source,
                fetch_id=fetch.fetch_id,
                fetch_hash=fetch.fetch_hash,
            )
        )
    records = literature_module._deduplicate_hits(hits) if hits else ()  # noqa: SLF001
    catalog_hash = canonical_model_hash(
        {"records": [item.model_dump(mode="json") for item in records]}
    )
    lineage_hash = canonical_model_hash(
        {
            "fetches": [item.model_dump(mode="json") for item in fetches],
            "fetch_bindings": [item.model_dump(mode="json") for item in bindings],
            "fetch_payloads": [item.model_dump(mode="json") for item in fetch_payloads],
        }
    )
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-gap-repair-retrieval-v1",
        "plan": validated_plan.model_dump(mode="json"),
        "plan_hash": validated_plan.artifact_hash,
        "query_compiler_version": _COMPILER_VERSION,
        "retriever_sources": list(normalized_searchers),
        "source_count": len(normalized_searchers),
        "query_count": validated_plan.query_count,
        "fetch_pair_count": len(fetches),
        "fetches": [item.model_dump(mode="json") for item in fetches],
        "fetch_bindings": [item.model_dump(mode="json") for item in bindings],
        "fetch_payloads": [item.model_dump(mode="json") for item in fetch_payloads],
        "retrieved_records": [item.model_dump(mode="json") for item in records],
        "raw_hit_count": sum(item.returned_count for item in fetches if item.status == "succeeded"),
        "deduplicated_count": sum(
            item.returned_count for item in fetches if item.status == "succeeded"
        )
        - len(records),
        "repair_catalog_hash": catalog_hash,
        "retrieval_lineage_hash": lineage_hash,
        "repair_outcome": "records_retrieved" if records else "no_valid_records",
        "query_model_calls": 0,
        "retrieval_scope": "deficit_roles_only_sparse_source_matrix",
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    artifact = ContestDirectionGapRepairArtifact.model_validate(payload)
    if output_path is not None:
        write_json_model(output_path, artifact)
    return artifact


def load_contest_direction_gap_repair(
    path: Path | str,
    *,
    expected_plan: ContestDirectionGapRepairPlan | None = None,
) -> ContestDirectionGapRepairArtifact:
    """Load and fully validate a repair artifact without re-running any source."""

    artifact = ContestDirectionGapRepairArtifact.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    if expected_plan is not None:
        validated_plan = ContestDirectionGapRepairPlan.model_validate(
            expected_plan.model_dump(mode="json")
        )
        if artifact.plan != validated_plan:
            raise ContestDirectionGapRepairError(
                "gap-repair artifact does not bind the expected sparse plan"
            )
    return artifact


__all__ = [
    "ContestDirectionGapRepairArtifact",
    "ContestDirectionGapRepairError",
    "ContestDirectionGapRepairFetchBinding",
    "ContestDirectionGapRepairFetchPayload",
    "ContestDirectionGapRepairPaperPayload",
    "ContestDirectionGapRepairPlan",
    "ContestDirectionGapRepairRoleQuery",
    "build_contest_direction_gap_repair_plan",
    "build_contest_direction_gap_repair_plan_from_projection",
    "load_contest_direction_gap_repair",
    "retrieve_contest_direction_gap_repair",
]
