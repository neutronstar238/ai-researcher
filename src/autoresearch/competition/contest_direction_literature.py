"""Evidence-bound literature retrieval for a user-specified research direction.

The configured model is used only to translate a broad direction into a small set
of search queries.  Papers can enter the artifact only through caller-injected
search callables.  This keeps query formulation flexible while making the
bibliography, abstracts, failures, timestamps, identifiers, and hashes entirely
program-derived and auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCoverageError,
    PlanningLiteratureRole,
    role_query_from_boolean,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.clients import (
    OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX,
    ArxivClient,
    OpenAlexClient,
    SemanticScholarClient,
    semantic_scholar_enabled,
)
from autoresearch.literature.models import (
    AcademicPaper,
    PublicationStatus,
    deduplicate_papers,
    normalize_doi,
)
from autoresearch.literature.privacy import normalize_untrusted_scholarly_papers
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_SHA256 = r"^[0-9a-f]{64}$"
_QUERY_COMPILER_VERSION = "source-query-compiler-v4"
_QUERY_RESPONSE_SCHEMA_NAME = "contest_direction_query_list"
_SUPPORTED_QUERY_COMPILER_VERSIONS = frozenset(
    {
        "source-query-compiler-v1",
        "source-query-compiler-v2",
        "source-query-compiler-v3",
        "source-query-compiler-v4",
    }
)
_ARXIV_MAX_QUERY_CHARS = 512
_ARXIV_MAX_GROUPS = 4
_ARXIV_MAX_ALTERNATIVES_PER_GROUP = 4
_ARXIV_MAX_TERM_CHARS = 72
_OPENALEX_MAX_QUERY_CHARS = 240
_OPENALEX_MAX_TERMS = 12
_OPENALEX_V2_MAX_QUERY_CHARS = 1_200
_OPENALEX_V2_MAX_GROUPS = 4
_OPENALEX_V2_MAX_ALTERNATIVES_PER_GROUP = 4
_OPENALEX_V2_MAX_TERM_CHARS = 72
_BOOLEAN_OPERATOR = re.compile(
    r"\b(AND\s+NOT|ANDNOT|AND|NOT)\b",
    flags=re.IGNORECASE,
)
_ENRICHED_RECORD_FIELDS = frozenset(
    {
        "repository_doi",
        "citation_count_source",
        "citation_count_as_of",
        "publication_status",
        "status_source",
        "status_as_of",
    }
)


def _query_response_schema() -> dict[str, Any]:
    """Return the provider transport shape; semantic checks remain local."""

    return {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    }


class ContestDirectionLiteratureError(RuntimeError):
    """Raised when direction retrieval cannot yield a real literature catalog."""

    def __init__(
        self,
        message: str,
        *,
        fetches: Sequence[ContestDirectionFetchRecord] = (),
    ) -> None:
        super().__init__(message)
        self.fetches = tuple(fetches)


class DirectionSearchCallable(Protocol):
    """Provider-neutral boundary for one real academic search implementation."""

    def __call__(self, query: str, *, limit: int) -> Sequence[AcademicPaper]:
        """Search one external or local scholarly source."""


class ContestDirectionMethodSkill(StrictFrozenModel):
    """Exact main-agent-selected Skill content injected after the direction."""

    skill_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256)

    @field_validator("skill_id", "content")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Skill text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_content_hash(self) -> ContestDirectionMethodSkill:
        expected = _sha256_text(self.content)
        if self.content_sha256 != expected:
            raise ValueError("Skill content hash mismatch")
        return self


class ContestDirectionFetchRecord(StrictFrozenModel):
    """One source/query attempt, including empty results and source failures."""

    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    source: str = Field(min_length=1, max_length=256)
    query: str = Field(min_length=1, max_length=2_000)
    query_index: int = Field(ge=1, le=4)
    retrieved_at: datetime
    status: Literal["succeeded", "failed"]
    returned_count: int = Field(ge=0)
    result_hash: str | None = Field(default=None, pattern=_SHA256)
    error: str | None = None
    fetch_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_program_fields(self) -> ContestDirectionFetchRecord:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.status == "failed":
            if not self.error or self.returned_count != 0 or self.result_hash is not None:
                raise ValueError("failed fetch must retain an error and no result payload")
        elif self.error is not None or self.result_hash is None:
            raise ValueError("successful fetch must retain its result hash and no error")
        expected_id = _fetch_id(
            source=self.source,
            query=self.query,
            query_index=self.query_index,
            retrieved_at=self.retrieved_at,
        )
        if self.fetch_id != expected_id:
            raise ValueError("fetch ID mismatch")
        expected_hash = canonical_model_hash(self.model_dump(mode="json", exclude={"fetch_hash"}))
        if self.fetch_hash != expected_hash:
            raise ValueError("fetch hash mismatch")
        return self


class ContestDirectionRetrievalPointer(StrictFrozenModel):
    """Provenance edge from a deduplicated paper back to a real fetch."""

    fetch_id: str = Field(pattern=r"^direction-fetch-[0-9a-f]{16}$")
    source: str = Field(min_length=1)
    query: str = Field(min_length=1)
    retrieved_at: datetime


class ContestDirectionLiteratureRecord(StrictFrozenModel):
    """One deduplicated full-metadata paper returned by real search callables."""

    record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
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
    paper_source: str = Field(min_length=1)
    retrievals: tuple[ContestDirectionRetrievalPointer, ...] = Field(min_length=1)
    paper_hash: str = Field(pattern=_SHA256)
    record_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_program_fields(self) -> ContestDirectionLiteratureRecord:
        legacy_paper_payload = _legacy_record_paper_payload(self)
        enriched_paper_payload = _enriched_record_paper_payload(self)
        legacy_paper_hash = canonical_model_hash(legacy_paper_payload)
        enriched_paper_hash = canonical_model_hash(enriched_paper_payload)
        if self.paper_hash == legacy_paper_hash:
            expected_paper_hash = legacy_paper_hash
        elif self.paper_hash == enriched_paper_hash:
            expected_paper_hash = enriched_paper_hash
        else:
            raise ValueError("paper metadata hash mismatch")
        if self.record_id != f"direction-paper-{expected_paper_hash[:16]}":
            raise ValueError("paper record ID mismatch")
        if len({item.fetch_id for item in self.retrievals}) != len(self.retrievals):
            raise ValueError("paper retrieval pointers must be unique")
        expected_record_hash = canonical_model_hash(_record_dump_for_hash(self))
        if self.record_hash != expected_record_hash:
            raise ValueError("paper record hash mismatch")
        return self


class ContestDirectionLiteratureArtifact(StrictFrozenModel):
    """Complete query-generation and real-retrieval receipt for one direction."""

    schema_version: Literal[
        "contest-direction-literature-v1",
        "contest-direction-literature-v2",
    ] = "contest-direction-literature-v2"
    input_mode: Literal["specified_direction"] = "specified_direction"
    direction: str = Field(min_length=1)
    requirements: tuple[str, ...] = ()
    method_skills: tuple[ContestDirectionMethodSkill, ...] = ()
    messages: tuple[dict[str, str], ...] = Field(min_length=3, max_length=3)
    messages_hash: str = Field(pattern=_SHA256)
    input_hash: str = Field(pattern=_SHA256)
    queries: tuple[str, ...] = Field(min_length=1, max_length=4)
    query_plan_hash: str = Field(pattern=_SHA256)
    query_model_response_hash: str = Field(pattern=_SHA256)
    query_compiler_version: (
        Literal[
            "source-query-compiler-v1",
            "source-query-compiler-v2",
            "source-query-compiler-v3",
            "source-query-compiler-v4",
        ]
        | None
    ) = None
    query_generation_provider: str = Field(min_length=1)
    query_generation_model: str = Field(min_length=1)
    query_model_calls: Literal[1] = 1
    retriever_sources: tuple[str, ...] = Field(min_length=1)
    fetches: tuple[ContestDirectionFetchRecord, ...] = Field(min_length=1)
    retrieved_records: tuple[ContestDirectionLiteratureRecord, ...] = Field(min_length=1)
    raw_hit_count: int = Field(ge=1)
    deduplicated_count: int = Field(ge=0)
    literature_catalog_hash: str = Field(pattern=_SHA256)
    qwen_authored_literature: Literal[False] = False
    literature_entry_boundary: Literal["injected_search_callables_only"] = (
        "injected_search_callables_only"
    )
    output_path: str | None = None
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _validate_program_bindings(self) -> ContestDirectionLiteratureArtifact:
        if self.schema_version == "contest-direction-literature-v1":
            if self.query_compiler_version is not None:
                raise ValueError("v1 literature artifacts cannot declare a query compiler")
        elif self.query_compiler_version not in _SUPPORTED_QUERY_COMPILER_VERSIONS:
            raise ValueError("v2 literature artifacts must bind a supported query compiler")
        if len(set(self.queries)) != len(self.queries):
            raise ValueError("search queries must be unique")
        if self.query_compiler_version == "source-query-compiler-v3" and len(self.queries) == 4:
            _validate_v3_query_plan(self.queries)
        if self.query_compiler_version == "source-query-compiler-v4":
            _validate_v4_query_plan(self.queries)
        if len(set(self.retriever_sources)) != len(self.retriever_sources):
            raise ValueError("retriever source names must be unique")
        selected_skills = {item.skill_id: item.content for item in self.method_skills}
        accepted_messages: tuple[tuple[dict[str, str], ...], ...]
        if self.schema_version == "contest-direction-literature-v1":
            accepted_messages = (
                tuple(
                    _build_quality_expansion_v1_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
                tuple(
                    _build_legacy_contest_direction_literature_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
            )
        elif self.query_compiler_version == "source-query-compiler-v1":
            accepted_messages = (
                tuple(
                    _build_source_query_compiler_v1_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
            )
        elif self.query_compiler_version == "source-query-compiler-v2":
            accepted_messages = (
                tuple(
                    _build_source_query_compiler_v2_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
            )
        elif self.query_compiler_version == "source-query-compiler-v3":
            accepted_messages = (
                tuple(
                    _build_source_query_compiler_v3_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
            )
        else:
            accepted_messages = (
                tuple(
                    build_contest_direction_literature_messages(
                        direction=self.direction,
                        requirements=self.requirements,
                        selected_method_skills=selected_skills,
                    )
                ),
            )
        if self.messages not in accepted_messages:
            raise ValueError("direction literature messages mismatch")
        if self.messages_hash != canonical_model_hash({"messages": list(self.messages)}):
            raise ValueError("direction literature messages hash mismatch")
        expected_input_hash = canonical_model_hash(
            _direction_input_payload(
                direction=self.direction,
                requirements=self.requirements,
                method_skills=self.method_skills,
            )
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("direction literature input hash mismatch")
        query_plan_payload: dict[str, Any] = {
            "input_hash": self.input_hash,
            "queries": list(self.queries),
            "query_model_response_hash": self.query_model_response_hash,
        }
        if self.schema_version == "contest-direction-literature-v2":
            query_plan_payload["query_compiler_version"] = self.query_compiler_version
        expected_query_hash = canonical_model_hash(query_plan_payload)
        if self.query_plan_hash != expected_query_hash:
            raise ValueError("direction query plan hash mismatch")
        expected_pairs = {
            (source, query_index)
            for query_index, _query in enumerate(self.queries, start=1)
            for source in self.retriever_sources
        }
        actual_pairs = {(fetch.source, fetch.query_index) for fetch in self.fetches}
        if actual_pairs != expected_pairs or len(actual_pairs) != len(self.fetches):
            raise ValueError("fetch receipts do not cover every source/query pair exactly once")
        for fetch in self.fetches:
            logical_query = self.queries[fetch.query_index - 1]
            if self.schema_version == "contest-direction-literature-v1":
                if fetch.query != logical_query:
                    raise ValueError("fetch query does not match the frozen query plan")
            elif fetch.query != _compile_source_query(
                fetch.source,
                logical_query,
                compiler_version=self.query_compiler_version,
            ):
                raise ValueError("fetch query does not match the compiled source query")
        fetches_by_id = {fetch.fetch_id: fetch for fetch in self.fetches}
        for record in self.retrieved_records:
            for pointer in record.retrievals:
                referenced_fetch = fetches_by_id.get(pointer.fetch_id)
                if referenced_fetch is None:
                    raise ValueError("paper record references an unknown fetch")
                if (
                    pointer.source != referenced_fetch.source
                    or pointer.query != referenced_fetch.query
                    or pointer.retrieved_at != referenced_fetch.retrieved_at
                ):
                    raise ValueError("paper retrieval pointer does not match its fetch receipt")
        if self.raw_hit_count != sum(
            fetch.returned_count for fetch in self.fetches if fetch.status == "succeeded"
        ):
            raise ValueError("raw literature hit count mismatch")
        if self.deduplicated_count != self.raw_hit_count - len(self.retrieved_records):
            raise ValueError("deduplicated literature count mismatch")
        expected_catalog_hash = canonical_model_hash(
            {"catalog": list(self.objective_literature_catalog())}
        )
        if self.literature_catalog_hash != expected_catalog_hash:
            raise ValueError("objective literature catalog hash mismatch")
        artifact_payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        if self.schema_version == "contest-direction-literature-v1":
            artifact_payload.pop("query_compiler_version", None)
        artifact_payload["retrieved_records"] = [
            {**_record_dump_for_hash(record), "record_hash": record.record_hash}
            for record in self.retrieved_records
        ]
        expected_artifact_hash = canonical_model_hash(artifact_payload)
        if self.artifact_hash != expected_artifact_hash:
            raise ValueError("direction literature artifact hash mismatch")
        return self

    def objective_literature_catalog(self) -> tuple[str, ...]:
        """Project full real-search records into immutable objective-stage entries."""

        entries: list[str] = []
        for index, record in enumerate(self.retrieved_records, start=1):
            authors = "、".join(record.authors) if record.authors else "作者信息未提供"
            publication_date = (
                record.publication_date.isoformat()
                if record.publication_date is not None
                else "日期未提供"
            )
            retrievals = "；".join(
                f"{item.source}|{item.query}|{item.retrieved_at.isoformat()}"
                for item in record.retrievals
            )
            lines: tuple[str, ...]
            if not _record_has_enriched_metadata(record):
                # Preserve byte-for-byte catalog projection for existing v1 artifacts.
                lines = (
                    f"[{index}] record_id={record.record_id}",
                    f"题名：{record.title}",
                    f"作者：{authors}",
                    f"日期：{publication_date}",
                    f"期刊或会议：{record.venue or '未提供'}",
                    f"DOI：{record.doi or '未提供'}",
                    f"URL：{record.url or '未提供'}",
                    f"论文来源字段：{record.paper_source}",
                    f"被引次数：{record.citation_count}",
                    f"完整摘要：{record.abstract or '摘要未提供'}",
                    f"真实检索谱系：{retrievals}",
                    f"record_sha256={record.record_hash}",
                )
            else:
                citation_text = "未知（上游来源未提供；不得解释为0）"
                if record.citation_count is not None:
                    citation_source = record.citation_count_source or "来源未标注"
                    citation_as_of = (
                        record.citation_count_as_of.isoformat()
                        if record.citation_count_as_of is not None
                        else "日期未标注"
                    )
                    citation_text = f"{record.citation_count}（来源：{citation_source}；截至：{citation_as_of}）"
                status_as_of = (
                    record.status_as_of.isoformat()
                    if record.status_as_of is not None
                    else "日期未标注"
                )
                lines = (
                    f"[{index}] record_id={record.record_id}",
                    f"题名：{record.title}",
                    f"作者：{authors}",
                    f"日期：{publication_date}",
                    f"期刊或会议：{record.venue or '未提供'}",
                    f"正式发表DOI：{record.doi or '未提供'}",
                    f"仓储DOI：{record.repository_doi or '未提供'}",
                    f"发表状态：{record.publication_status}（来源：{record.status_source or '未标注'}；截至：{status_as_of}）",
                    f"URL：{record.url or '未提供'}",
                    f"论文来源字段：{record.paper_source}",
                    f"被引次数：{citation_text}",
                    "期刊影响因子：未知（当前检索API未提供可核验数值，不按刊名推断）",
                    f"完整摘要：{record.abstract or '摘要未提供'}",
                    f"真实检索谱系：{retrievals}",
                    f"record_sha256={record.record_hash}",
                )
            entries.append("\n".join(lines))
        return tuple(entries)

    def objective_retrieval_catalog(self) -> tuple[dict[str, Any], ...]:
        """Return the mapping projection consumed by the research-objective stage.

        A retrieved item without a real landing-page URL or DOI remains preserved in
        ``retrieved_records`` but cannot be cited by the objective stage.  No synthetic
        URL is manufactured to make such an item pass downstream validation.
        """

        catalog: list[dict[str, Any]] = []
        for record in self.retrieved_records:
            source_url = record.url
            if not source_url and record.doi:
                source_url = f"https://doi.org/{record.doi}"
            if not source_url and record.repository_doi:
                source_url = f"https://doi.org/{record.repository_doi}"
            if not source_url:
                continue
            item: dict[str, Any] = {
                "record_id": record.record_id,
                "title": record.title,
                "authors": list(record.authors),
                "abstract": record.abstract,
                "doi": record.doi,
                "url": source_url,
                "source_url": source_url,
                "retrieved_from": ",".join(
                    dict.fromkeys(item.source for item in record.retrievals)
                ),
                "retrieved_at": min(item.retrieved_at for item in record.retrievals).isoformat(),
                "paper_source": record.paper_source,
                "record_sha256": record.record_hash,
            }
            if _record_has_enriched_metadata(record):
                item.update(
                    {
                        "publication_date": (
                            record.publication_date.isoformat()
                            if record.publication_date is not None
                            else None
                        ),
                        "venue": record.venue,
                        "publication_doi": record.doi,
                        "repository_doi": record.repository_doi,
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
                            record.status_as_of.isoformat()
                            if record.status_as_of is not None
                            else None
                        ),
                        "journal_impact_factor": None,
                        "journal_impact_factor_source": None,
                    }
                )
            catalog.append(item)
        if not catalog:
            raise ContestDirectionLiteratureError(
                "retrieved papers have no real URL or DOI usable by the objective stage"
            )
        return tuple(catalog)

    def objective_literature_record_catalog(self) -> tuple[dict[str, Any], ...]:
        """Backward-compatible alias for :meth:`objective_retrieval_catalog`."""

        return self.objective_retrieval_catalog()


def _build_source_query_compiler_v1_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Reconstruct the source-query-compiler-v1 prompt for artifact replay."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "可由不同学术源分别编译的源中立逻辑查询。必须恰好输出四条，并严格按"
                "以下顺序：1）核心研究对象与直接现象；2）方法基础、测量与数据；3）同一"
                "核心对象的机制、理论基线或零模型；4）同一核心对象的反证、失败结果、争议"
                "或替代解释。第1、3、4条必须逐字复用完全相同的核心研究对象 OR 组，并把它"
                "作为独立的必需命中组；该对象组不得只写 generic model、system、method，"
                "也不得用泛化的模型、系统或方法代替具体研究对象。每条必须简洁，通常仅用"
                "两个左右顶层 AND 概念组，组内只保留"
                "少量高价值 OR 同义表述。不得使用字段语法、站点过滤、通配符 * ? ~ 或特定数据库"
                "语法。第三条必须用科学内容概念表达，不得另加文献类型标签，不得把"
                "review、survey、foundational、综述或奠基作为必须命中的独立 AND 概念组。"
                "但不要回答研究问题，不要生成研究目标、假设、论文、作者、DOI、URL、"
                "引用或任何检索结果。只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {
                        "queries": [
                            "核心对象OR组 AND 直接现象检索式",
                            "方法、测量与数据或定义基础检索式",
                            "同一核心对象OR组 AND 机制、理论基线或零模型检索式",
                            "同一核心对象OR组 AND 反证、失败或替代解释检索式",
                        ]
                    },
                }
            ),
        },
    ]


def _build_source_query_compiler_v2_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Reconstruct the source-query-compiler-v2 prompt for artifact replay."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "可由不同学术源分别编译的源中立逻辑查询。必须恰好输出四条，并严格按"
                "以下顺序：1）核心研究对象与直接现象；2）方法族与方法定义、估计、偏差或"
                "验证；3）同一"
                "核心对象的机制、理论基线或零模型；4）同一核心对象的反证、失败结果、争议"
                "或替代解释。第1、3、4条必须逐字复用完全相同的核心研究对象 OR 组，并把它"
                "作为独立的必需命中组；该对象组不得只写 generic model、system、method，"
                "也不得用泛化的模型、系统或方法代替具体研究对象。第2条必须写成“方法族 OR"
                "组 AND 定义、估计、偏差或验证 OR 组”，不得强制包含具体研究对象，也不得把"
                "拟议的专用零模型、干预组合或自造术语当作方法基础。每条只用两个顶层 AND"
                "概念组；每组保留2至4个短而常用、可能原样出现在论文题名或摘要中的 OR 术语。"
                "用括号表示 OR 组，多词术语用英文双引号；不得使用字段语法、站点过滤、"
                "通配符 * ? ~、NOT 或特定数据库语法。第三条必须用科学内容概念表达，不得另加"
                "文献类型标签，不得把"
                "review、survey、foundational、综述或奠基作为必须命中的独立 AND 概念组。"
                "但不要回答研究问题，不要生成研究目标、假设、论文、作者、DOI、URL、"
                "引用或任何检索结果。只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {
                        "queries": [
                            "核心对象OR组 AND 直接现象检索式",
                            "方法族OR组 AND 定义、估计、偏差或验证OR组检索式",
                            "同一核心对象OR组 AND 机制、理论基线或零模型检索式",
                            "同一核心对象OR组 AND 反证、失败或替代解释检索式",
                        ]
                    },
                }
            ),
        },
    ]


def _build_source_query_compiler_v3_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Reconstruct the source-query-compiler-v3 prompt for artifact replay."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "可由不同学术源分别编译的源中立逻辑查询。必须恰好输出四条，并严格按"
                "以下顺序：1）核心研究对象与直接现象；2）方法族与方法定义、估计、偏差或"
                "验证；3）同一核心研究对象的机制、理论基线或零模型；4）同一核心研究对象"
                "的真正反证证据。第1、3、4条必须逐字复用完全相同的核心研究对象 OR 组，"
                "并把它作为独立的必需命中组；该对象组不得只写 generic model、system、"
                "method，也不得用泛化的模型、系统或方法代替具体研究对象。第2条必须写成"
                "“方法族 OR组 AND 定义、估计、偏差或验证 OR 组”，不得强制包含具体研究"
                "对象，也不得把拟议的专用零模型、干预组合或自造术语当作方法基础。第4条"
                "的第二个必需组必须包含可能推翻、限制或替代正向解释的概念，使用短而常用"
                "的英文检索术语，例如 limitations、failure modes、artifacts、null "
                "explanations、negative results、bias 或 confounding。仅由 anomalies、"
                "deviations、counterexamples、irregularities 组成的弱概念组不合格；也不得"
                "把 no、zero、without 或 not 与 counterexample 等概念组成否定式命中。"
                "每条只用两个顶层 AND 概念组；每组保留2至4个短而常用、可能原样出现在"
                "论文题名或摘要中的 OR 术语。用括号表示 OR 组，多词术语用英文双引号；"
                "不得使用字段语法、站点过滤、通配符 * ? ~、NOT 或特定数据库语法。第三条"
                "必须用科学内容概念表达，不得另加文献类型标签，不得把 review、survey、"
                "foundational、综述或奠基作为必须命中的独立 AND 概念组。但不要回答研究"
                "问题，不要生成研究目标、假设、论文、作者、DOI、URL、引用或任何检索结果。"
                "只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {
                        "queries": [
                            "核心对象OR组 AND 直接现象检索式",
                            "方法族OR组 AND 定义、估计、偏差或验证OR组检索式",
                            "同一核心对象OR组 AND 机制、理论基线或零模型检索式",
                            "同一核心对象OR组 AND 真正反证概念OR组检索式",
                        ]
                    },
                }
            ),
        },
    ]


def build_contest_direction_literature_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Build the v4 query plan with explicit, mechanically enforced bounds."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "可由不同学术源分别编译的源中立逻辑查询。必须恰好输出四条，并严格按"
                "以下顺序：1）核心研究对象与直接现象；2）方法族与方法定义、估计、偏差或"
                "验证；3）同一核心研究对象的机制、理论基线或零模型；4）同一核心研究对象"
                "的真正反证证据。第1、3、4条必须逐字复用完全相同的核心研究对象 OR 组，"
                "并把它作为独立的必需命中组；该对象组不得只写 generic model、system、"
                "method，也不得用泛化的模型、系统或方法代替具体研究对象。第2条必须写成"
                "“方法族 OR组 AND 定义、估计、偏差或验证 OR 组”，不得强制包含具体研究"
                "对象，也不得把拟议的专用零模型、干预组合或自造术语当作方法基础。为保证"
                "方法文献能建立『不可变焦点桥』，第2条的第一必需组（方法族 OR 组）必须"
                "至少包含一个与第1条第二必需组（直接现象 OR 组）逐字相同的焦点桥接术语；"
                "若方法族确实无法复用直接现象术语，则必须复用第1条第一必需组（核心对象"
                "OR 组）中的某个对象术语，但不得用该对象术语取代真正的方法族词。第4条"
                "的第二个必需组必须包含可能推翻、限制或替代正向解释的概念，使用短而常用"
                "的英文检索术语。第二个必需组必须至少包含下列完整强反证词表中的一个概念："
                "limitation、limitations、failure mode、failure modes、artifact、artifacts、"
                "bias、biases、confounder、confounders、confounding、negative result、"
                "negative results、null explanation、null explanations、false positive、"
                "false positives、spurious effect、spurious effects、alternative explanation、"
                "alternative explanations。仅由"
                "anomalies、deviations、counterexamples、irregularities 组成的弱概念组不合格；也不得"
                "把 no、zero、without 或 not 与 counterexample 等概念组成否定式命中。"
                "每条恰好使用两个顶层 AND 概念组；每个 OR 组使用2至4个短而常用、可能原样出现在"
                "论文题名或摘要中的不同术语。每个 OR 组的不同术语数量上限固定为4个；"
                "第5个术语会使整个查询计划失效，系统不会截断、放宽上限或自动重试。"
                "用括号表示 OR 组，多词术语用英文双引号；不得使用字段语法、站点过滤、"
                "通配符 * ? ~、NOT 或特定数据库语法。第三条必须用科学内容概念表达，不得另加"
                "文献类型标签，不得把 review、survey、foundational、综述或奠基作为必须命中的独立 AND 概念组。"
                "但不要回答研究问题，不要生成研究目标、假设、论文、作者、DOI、URL、"
                "引用或任何检索结果。只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {
                        "queries": [
                            "核心对象OR组 AND 直接现象检索式",
                            "方法族OR组 AND 定义、估计、偏差或验证OR组检索式",
                            "同一核心对象OR组 AND 机制、理论基线或零模型检索式",
                            "同一核心对象OR组 AND 真正反证概念OR组检索式",
                        ],
                        "query_shape": {
                            "top_level_must_groups_per_query": 2,
                            "minimum_alternatives_per_group": 2,
                            "maximum_alternatives_per_group": 4,
                            "over_limit_policy": (
                                "reject_entire_plan_before_search_no_truncation_or_retry"
                            ),
                        },
                    },
                }
            ),
        },
    ]


def _build_quality_expansion_v1_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Reconstruct the four-role quality-expansion prompt used by later v1 runs."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "四条互补且可直接交给学术检索器的检索式；若方向信息确实不足，允许少于"
                "四条而不得编造专有名词。四条查询应分别覆盖：研究对象及核心机制；可验证"
                "机制的方法、测量或数据；该方向的权威综述、奠基工作或高影响证据；反证、"
                "失败结果、争议或替代解释。每条查询应展开常用同义词、术语变体及相邻学科"
                "表述，宽窄查询并存，不要把年份、期刊名、作者名或最低引用次数写成硬门槛。"
                "但不要回答研究问题，不要生成研究目标、假设、论文、作者、DOI、URL、"
                "引用或任何检索结果。只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {
                        "queries": [
                            "核心对象与机制检索式",
                            "方法、测量与数据检索式",
                            "权威综述、奠基工作与高影响证据检索式",
                            "反证、争议与替代解释检索式",
                        ]
                    },
                }
            ),
        },
    ]


def _build_legacy_contest_direction_literature_messages(
    *,
    direction: str,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Reconstruct pre-quality-expansion v1 prompts for artifact replay only."""

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    return [
        {
            "role": "system",
            "content": (
                "你是跨学科科研检索规划智能体。你的唯一任务是把给定研究方向转换为"
                "一至四条有区分度、可直接交给学术检索器的检索式。允许宽窄查询并存，"
                "但不要回答研究问题，不要生成研究目标、假设、论文、作者、DOI、URL、"
                "引用或任何检索结果。只输出JSON对象，内容仅为queries字符串数组。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "specified_research_direction_and_requirements",
                    "direction": normalized_direction,
                    "requirements": list(normalized_requirements),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "main_agent_selected_method_skills",
                    "boundary_zh": (
                        "以下SKILL.md只提供检索方法和学科研究路径，不是事实证据、"
                        "题目答案、文献记录或预定结论。"
                    ),
                    "selected_method_skills": [item.model_dump(mode="json") for item in skills],
                    "output_contract": {"queries": ["一至四条检索式"]},
                }
            ),
        },
    ]


def retrieve_contest_direction_literature(
    *,
    direction: str,
    searchers: Mapping[str, DirectionSearchCallable] | None = None,
    requirements: Sequence[str] = (),
    selected_method_skills: Mapping[str, str] | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    output_path: Path | str | None = None,
    timeout_seconds: int | None = None,
    max_tokens: int | None = 768,
    max_results_per_search: int = 20,
    retrieved_at: datetime | None = None,
    llm_call: Any = run_llm_json_completion,
) -> ContestDirectionLiteratureArtifact:
    """Generate queries once, run real injected searchers, and freeze the catalog.

    Source exceptions are recorded and isolated.  The call fails only after all
    source/query attempts finish and none returns a valid paper.
    """

    normalized_direction = _normalize_direction(direction)
    normalized_requirements = _normalize_requirements(requirements)
    skills = _normalize_method_skills(selected_method_skills)
    source_searchers = _normalize_searchers(
        default_contest_direction_searchers() if searchers is None else searchers
    )
    if max_results_per_search < 1:
        raise ContestDirectionLiteratureError("max_results_per_search must be positive")
    timestamp = _normalize_datetime(retrieved_at)
    messages = _build_messages_for_query_compiler(
        direction=normalized_direction,
        requirements=normalized_requirements,
        selected_method_skills={item.skill_id: item.content for item in skills},
        compiler_version=_QUERY_COMPILER_VERSION,
    )
    completion: LLMJsonCompletionResult = llm_call(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=0.2,
        thinking_mode="disabled",
        thinking_budget=None,
        response_schema=_query_response_schema(),
        response_schema_name=_QUERY_RESPONSE_SCHEMA_NAME,
    )
    queries = _project_queries(
        completion.parsed_json,
        compiler_version=_QUERY_COMPILER_VERSION,
    )
    compiled_search_plan: list[tuple[int, str, str, DirectionSearchCallable, str]] = []
    for query_index, query in enumerate(queries, start=1):
        for source, searcher in source_searchers.items():
            try:
                executed_query = _compile_source_query(
                    source,
                    query,
                    compiler_version=_QUERY_COMPILER_VERSION,
                )
            except ContestDirectionLiteratureError as exc:
                raise ContestDirectionLiteratureError(
                    f"{_QUERY_COMPILER_VERSION} query {query_index} for source {source!r} "
                    f"failed compilation: {exc}"
                ) from exc
            compiled_search_plan.append((query_index, query, source, searcher, executed_query))
    hits: list[tuple[AcademicPaper, ContestDirectionRetrievalPointer]] = []
    fetches: list[ContestDirectionFetchRecord] = []
    for query_index, _query, source, searcher, executed_query in compiled_search_plan:
        try:
            papers = _normalize_search_results(
                searcher(executed_query, limit=max_results_per_search)
            )
        except Exception as exc:  # noqa: BLE001 - per-source degradation is intentional.
            fetch = _build_fetch_record(
                source=source,
                query=executed_query,
                query_index=query_index,
                retrieved_at=timestamp,
                papers=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            fetch = _build_fetch_record(
                source=source,
                query=executed_query,
                query_index=query_index,
                retrieved_at=timestamp,
                papers=papers,
                error=None,
            )
            pointer = ContestDirectionRetrievalPointer(
                fetch_id=fetch.fetch_id,
                source=source,
                query=executed_query,
                retrieved_at=timestamp,
            )
            hits.extend((paper, pointer) for paper in papers)
        fetches.append(fetch)

    if not hits:
        failures = sum(fetch.status == "failed" for fetch in fetches)
        raise ContestDirectionLiteratureError(
            "all configured literature searches returned no papers "
            f"({len(fetches)} attempts, {failures} source failures)",
            fetches=fetches,
        )

    records = _deduplicate_hits(hits)
    input_hash = canonical_model_hash(
        _direction_input_payload(
            direction=normalized_direction,
            requirements=normalized_requirements,
            method_skills=skills,
        )
    )
    response_hash = canonical_model_hash({"response_text": completion.response_text})
    query_plan_hash = canonical_model_hash(
        {
            "input_hash": input_hash,
            "queries": list(queries),
            "query_model_response_hash": response_hash,
            "query_compiler_version": _QUERY_COMPILER_VERSION,
        }
    )
    destination = Path(output_path) if output_path is not None else None
    base_payload: dict[str, Any] = {
        "schema_version": "contest-direction-literature-v2",
        "input_mode": "specified_direction",
        "direction": normalized_direction,
        "requirements": list(normalized_requirements),
        "method_skills": [item.model_dump(mode="json") for item in skills],
        "messages": messages,
        "messages_hash": canonical_model_hash({"messages": messages}),
        "input_hash": input_hash,
        "queries": list(queries),
        "query_plan_hash": query_plan_hash,
        "query_model_response_hash": response_hash,
        "query_compiler_version": _QUERY_COMPILER_VERSION,
        "query_generation_provider": completion.provider,
        "query_generation_model": completion.model_name,
        "query_model_calls": 1,
        "retriever_sources": list(source_searchers),
        "fetches": [item.model_dump(mode="json") for item in fetches],
        "retrieved_records": [item.model_dump(mode="json") for item in records],
        "raw_hit_count": len(hits),
        "deduplicated_count": len(hits) - len(records),
        "qwen_authored_literature": False,
        "literature_entry_boundary": "injected_search_callables_only",
        "output_path": destination.as_posix() if destination is not None else None,
    }
    preview_payload = {
        **base_payload,
        "method_skills": skills,
        "fetches": tuple(fetches),
        "retrieved_records": records,
    }
    preview = ContestDirectionLiteratureArtifact.model_construct(
        **preview_payload,
        literature_catalog_hash="0" * 64,
        artifact_hash="0" * 64,
    )
    base_payload["literature_catalog_hash"] = canonical_model_hash(
        {"catalog": list(preview.objective_literature_catalog())}
    )
    base_payload["artifact_hash"] = canonical_model_hash(base_payload)
    artifact = ContestDirectionLiteratureArtifact.model_validate(base_payload)
    if destination is not None:
        write_json_model(destination, artifact)
    return artifact


def default_contest_direction_searchers() -> dict[str, DirectionSearchCallable]:
    """Return the repository's configured live scholarly search boundaries."""

    searchers: dict[str, DirectionSearchCallable] = {
        "arxiv": ArxivClient().search,
        "openalex": OpenAlexClient().search,
    }
    if semantic_scholar_enabled():
        searchers["semantic_scholar"] = SemanticScholarClient().search
    return searchers


def _normalize_direction(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ContestDirectionLiteratureError("direction must not be blank")
    return normalized


def _normalize_requirements(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def _normalize_method_skills(
    values: Mapping[str, str] | None,
) -> tuple[ContestDirectionMethodSkill, ...]:
    skills: list[ContestDirectionMethodSkill] = []
    for skill_id, content in (values or {}).items():
        normalized_id = skill_id.strip()
        normalized_content = content.strip()
        if not normalized_id or not normalized_content:
            raise ContestDirectionLiteratureError("selected Skill IDs/content cannot be blank")
        skills.append(
            ContestDirectionMethodSkill(
                skill_id=normalized_id,
                content=normalized_content,
                content_sha256=_sha256_text(normalized_content),
            )
        )
    return tuple(skills)


def _normalize_searchers(
    values: Mapping[str, DirectionSearchCallable],
) -> dict[str, DirectionSearchCallable]:
    normalized: dict[str, DirectionSearchCallable] = {}
    for source, searcher in values.items():
        source_name = source.strip()
        if not source_name:
            raise ContestDirectionLiteratureError("retriever source name cannot be blank")
        if not callable(searcher):
            raise ContestDirectionLiteratureError(
                f"retriever source {source_name!r} is not callable"
            )
        normalized[source_name] = searcher
    if not normalized:
        raise ContestDirectionLiteratureError(
            "at least one real literature search callable is required"
        )
    return normalized


def _build_messages_for_query_compiler(
    *,
    direction: str,
    requirements: Sequence[str],
    selected_method_skills: Mapping[str, str] | None,
    compiler_version: str,
) -> list[dict[str, str]]:
    if compiler_version == "source-query-compiler-v1":
        return _build_source_query_compiler_v1_messages(
            direction=direction,
            requirements=requirements,
            selected_method_skills=selected_method_skills,
        )
    if compiler_version == "source-query-compiler-v2":
        return _build_source_query_compiler_v2_messages(
            direction=direction,
            requirements=requirements,
            selected_method_skills=selected_method_skills,
        )
    if compiler_version == "source-query-compiler-v3":
        return _build_source_query_compiler_v3_messages(
            direction=direction,
            requirements=requirements,
            selected_method_skills=selected_method_skills,
        )
    if compiler_version == "source-query-compiler-v4":
        return build_contest_direction_literature_messages(
            direction=direction,
            requirements=requirements,
            selected_method_skills=selected_method_skills,
        )
    raise ContestDirectionLiteratureError(
        f"unsupported source query compiler version: {compiler_version}"
    )


def _strip_stray_json_delimiters(query: str) -> str:
    """Strip JSON array/object delimiters a model may leak into a query string.

    The v4 query grammar uses only parentheses and double quotes, never square
    or curly brackets or commas, so leading/trailing occurrences of those
    characters are model formatting artifacts (e.g. a leaked ``]`` closing a
    JSON array inside the last string) rather than part of a valid Boolean term.
    """

    stripped = query.strip()
    while stripped and stripped[0] in "[{":
        stripped = stripped[1:].lstrip()
    while stripped and stripped[-1] in "]},;":
        stripped = stripped[:-1].rstrip()
    return stripped


def _project_queries(
    payload: Mapping[str, Any],
    *,
    compiler_version: str,
) -> tuple[str, ...]:
    raw: Any = payload.get("queries")
    if raw is None:
        raw = payload.get("search_queries", payload.get("query"))
    if isinstance(raw, str):
        raw_values: Sequence[Any] = raw.splitlines() or (raw,)
    elif isinstance(raw, Sequence) and not isinstance(raw, bytes | bytearray):
        raw_values = raw
    else:
        raise ContestDirectionLiteratureError(
            "query model response must contain queries or search_queries"
        )
    queries: list[str] = []
    for value in raw_values:
        if not isinstance(value, str):
            continue
        query = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", value).strip()
        query = _strip_stray_json_delimiters(query)
        if query and query not in queries:
            queries.append(query)
        if compiler_version != "source-query-compiler-v4" and len(queries) == 4:
            break
    if not queries:
        raise ContestDirectionLiteratureError("query model produced no usable search query")
    projected = tuple(queries)
    if compiler_version == "source-query-compiler-v3" and len(projected) == 4:
        _validate_v3_query_plan(projected)
    if compiler_version == "source-query-compiler-v4":
        _validate_v4_query_plan(projected)
    return projected


_STRONG_COUNTEREVIDENCE_TERMS = frozenset(
    {
        "limitation",
        "limitations",
        "failure mode",
        "failure modes",
        "artifact",
        "artifacts",
        "null explanation",
        "null explanations",
        "negative result",
        "negative results",
        "bias",
        "biases",
        "confounder",
        "confounders",
        "confounding",
        "false positive",
        "false positives",
        "spurious effect",
        "spurious effects",
        "alternative explanation",
        "alternative explanations",
    }
)
_WEAK_COUNTEREVIDENCE_TERMS = frozenset(
    {
        "anomaly",
        "anomalies",
        "deviation",
        "deviations",
        "counterexample",
        "counterexamples",
        "irregularity",
        "irregularities",
    }
)
_NEGATED_COUNTER_TERM = re.compile(
    r"^(?:no|zero|without|not)\s+(?:evidence\s+of\s+)?",
    flags=re.IGNORECASE,
)


def _counterevidence_term_strength(term: str) -> Literal["strong", "weak", "none"]:
    """Classify one counterevidence alternative deterministically.

    The gate recognizes a falsifying concept both as an exact lexicon phrase and
    inside a longer evidence-bound phrase (e.g. ``a finite-size artifact``
    carries the strong concept ``artifact``).  Exact membership remains the
    primary signal; containment keeps evidence-copied multi-word phrases from
    being misclassified as concept-free.
    """

    normalized = " ".join(term.casefold().split())
    if not normalized:
        return "none"
    for phrase in _STRONG_COUNTEREVIDENCE_PHRASES_SORTED:
        if phrase in normalized:
            return "strong"
    for phrase in _WEAK_COUNTEREVIDENCE_PHRASES_SORTED:
        if phrase in normalized:
            return "weak"
    return "none"


_STRONG_COUNTEREVIDENCE_PHRASES_SORTED = tuple(
    sorted(_STRONG_COUNTEREVIDENCE_TERMS, key=len, reverse=True)
)
_WEAK_COUNTEREVIDENCE_PHRASES_SORTED = tuple(
    sorted(_WEAK_COUNTEREVIDENCE_TERMS, key=len, reverse=True)
)


def _counterevidence_gate_detail(counter_terms: tuple[str, ...]) -> str | None:
    strengths = tuple(_counterevidence_term_strength(term) for term in counter_terms)
    if any(strength == "strong" for strength in strengths):
        return None
    if strengths and all(strength == "weak" for strength in strengths):
        return "weak-only group"
    return "missing a falsifying concept"


def _validate_v3_query_plan(queries: tuple[str, ...]) -> None:
    """Reject a fourth query that cannot retrieve genuine counterevidence."""

    try:
        parsed = tuple(
            role_query_from_boolean(role, f"source-v3-q{index}", query)
            for index, (role, query) in enumerate(
                zip(
                    (
                        PlanningLiteratureRole.DIRECT_CORE,
                        PlanningLiteratureRole.METHOD_FOUNDATION,
                        PlanningLiteratureRole.MECHANISM_OR_NULL,
                        PlanningLiteratureRole.COUNTEREVIDENCE,
                    ),
                    queries,
                    strict=True,
                ),
                start=1,
            )
        )
    except (PlanningLiteratureCoverageError, ValueError) as exc:
        raise ContestDirectionLiteratureError(
            f"source-query-compiler-v3 produced an invalid role query: {exc}"
        ) from exc
    if any(len(item.must_groups) != 2 for item in parsed):
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v3 requires exactly two must-groups per role query"
        )
    if not (parsed[0].must_groups[0] == parsed[2].must_groups[0] == parsed[3].must_groups[0]):
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v3 requires one exact object group in Q1, Q3, and Q4"
        )
    counter_terms = tuple(" ".join(term.casefold().split()) for term in parsed[3].must_groups[1])
    if any(_NEGATED_COUNTER_TERM.match(term) for term in counter_terms):
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v3 counterevidence terms must not be negated"
        )
    detail = _counterevidence_gate_detail(counter_terms)
    if detail is not None:
        raise ContestDirectionLiteratureError(f"source-query-compiler-v3 counterevidence {detail}")


def _validate_v4_query_plan(queries: tuple[str, ...]) -> None:
    """Fail closed on the exact v4 query shape before any source compilation."""

    if len(queries) != 4:
        raise ContestDirectionLiteratureError(
            f"source-query-compiler-v4 requires exactly 4 queries; received {len(queries)}"
        )
    roles = (
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.METHOD_FOUNDATION,
        PlanningLiteratureRole.MECHANISM_OR_NULL,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    try:
        parsed = tuple(
            role_query_from_boolean(role, f"source-v4-q{index}", query)
            for index, (role, query) in enumerate(zip(roles, queries, strict=True), start=1)
        )
    except (PlanningLiteratureCoverageError, ValueError) as exc:
        raise ContestDirectionLiteratureError(
            f"source-query-compiler-v4 produced an invalid role query: {exc}"
        ) from exc
    for query_index, role_query in enumerate(parsed, start=1):
        if len(role_query.must_groups) != 2:
            raise ContestDirectionLiteratureError(
                "source-query-compiler-v4 "
                f"query {query_index} requires exactly 2 must-groups; "
                f"received {len(role_query.must_groups)}"
            )
        for group_index, alternatives in enumerate(role_query.must_groups, start=1):
            alternative_count = len(alternatives)
            if not 2 <= alternative_count <= _OPENALEX_V2_MAX_ALTERNATIVES_PER_GROUP:
                raise ContestDirectionLiteratureError(
                    "source-query-compiler-v4 "
                    f"query {query_index} group {group_index} has {alternative_count} "
                    "alternatives; minimum is 2 and maximum is 4"
                )
    if not (parsed[0].must_groups[0] == parsed[2].must_groups[0] == parsed[3].must_groups[0]):
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v4 requires one exact object group in Q1, Q3, and Q4"
        )
    counter_terms = tuple(" ".join(term.casefold().split()) for term in parsed[3].must_groups[1])
    if any(_NEGATED_COUNTER_TERM.match(term) for term in counter_terms):
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v4 counterevidence terms must not be negated"
        )
    detail = _counterevidence_gate_detail(counter_terms)
    if detail is not None:
        raise ContestDirectionLiteratureError(f"source-query-compiler-v4 counterevidence {detail}")


def _compile_source_query(
    source: str,
    logical_query: str,
    *,
    compiler_version: str | None = None,
) -> str:
    """Compile one logical query into the exact string sent to a source."""

    version = compiler_version or _QUERY_COMPILER_VERSION
    if version not in _SUPPORTED_QUERY_COMPILER_VERSIONS:
        raise ContestDirectionLiteratureError(
            f"unsupported source query compiler version: {version}"
        )
    source_key = source.strip().casefold()
    if source_key == "arxiv":
        if version == "source-query-compiler-v4":
            return _compile_arxiv_query_v2(logical_query)
        return _compile_arxiv_query_v1(logical_query)
    if source_key == "openalex":
        if version == "source-query-compiler-v1":
            return _compile_openalex_query_v1(logical_query)
        return _compile_openalex_query_v2(logical_query, compiler_version=version)
    return logical_query


def _compile_arxiv_query_v1(logical_query: str) -> str:
    clauses: list[tuple[str, str]] = []
    for operator, group in _split_boolean_groups(logical_query):
        alternatives: list[str] = []
        alternative_keys: set[str] = set()
        for raw_alternative in re.split(r"\bOR\b", group, flags=re.IGNORECASE):
            term = _normalize_query_term(raw_alternative, max_chars=_ARXIV_MAX_TERM_CHARS)
            term_key = term.casefold()
            if term and term_key not in alternative_keys:
                alternatives.append(term)
                alternative_keys.add(term_key)
        if not alternatives:
            continue
        alternatives = _select_evenly_spaced(
            alternatives,
            limit=_ARXIV_MAX_ALTERNATIVES_PER_GROUP,
        )
        fields = [f'all:"{term}"' for term in alternatives]
        clause = fields[0] if len(fields) == 1 else f"({' OR '.join(fields)})"
        joiner = "ANDNOT" if "NOT" in operator.upper() else "AND"
        clauses.append((joiner, clause))
        if len(clauses) == _ARXIV_MAX_GROUPS:
            break

    compiled = ""
    for joiner, clause in clauses:
        candidate = clause if not compiled else f"{compiled} {joiner} {clause}"
        if len(candidate) > _ARXIV_MAX_QUERY_CHARS:
            break
        compiled = candidate
    if compiled:
        return compiled
    fallback = _normalize_query_term(logical_query, max_chars=_ARXIV_MAX_TERM_CHARS)
    if not fallback:
        raise ContestDirectionLiteratureError("logical query has no arXiv-searchable terms")
    return f'all:"{fallback}"'


def _compile_arxiv_query_v2(logical_query: str) -> str:
    """Compile v4 queries without dropping groups, alternatives, or term bytes."""

    try:
        parsed = role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "source-compiler-v4-arxiv",
            logical_query,
        )
    except PlanningLiteratureCoverageError as exc:
        raise ContestDirectionLiteratureError(
            f"logical query is not a legal source-neutral Boolean expression: {exc}"
        ) from exc
    if parsed.prefix_terms:
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v4 does not accept wildcard terms"
        )
    if len(parsed.must_groups) > _ARXIV_MAX_GROUPS:
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v4 query has too many required groups"
        )

    clauses: list[str] = []
    for alternatives in parsed.must_groups:
        if len(alternatives) > _ARXIV_MAX_ALTERNATIVES_PER_GROUP:
            raise ContestDirectionLiteratureError(
                "source-query-compiler-v4 group has too many alternatives"
            )
        if any(len(term) > _ARXIV_MAX_TERM_CHARS for term in alternatives):
            raise ContestDirectionLiteratureError(
                "source-query-compiler-v4 term exceeds the bounded term length"
            )
        fields = tuple(f'all:"{term}"' for term in alternatives)
        clauses.append(f"({' OR '.join(fields)})")

    compiled = " AND ".join(clauses)
    if len(compiled) > _ARXIV_MAX_QUERY_CHARS:
        raise ContestDirectionLiteratureError(
            "source-query-compiler-v4 arXiv query exceeds the bounded request length"
        )
    return compiled


def _compile_openalex_query_v1(logical_query: str) -> str:
    groups: list[list[str]] = []
    for operator, source_group in _split_boolean_groups(logical_query):
        if "NOT" in operator.upper():
            continue
        alternatives: list[str] = []
        alternative_keys: set[str] = set()
        for raw_alternative in re.split(r"\bOR\b", source_group, flags=re.IGNORECASE):
            alternative = _normalize_query_term(
                raw_alternative,
                max_chars=_ARXIV_MAX_TERM_CHARS,
            )
            key = alternative.casefold()
            if alternative and key not in alternative_keys:
                alternatives.append(alternative)
                alternative_keys.add(key)
        if alternatives:
            groups.append(alternatives)

    terms: list[str] = []
    seen: set[str] = set()
    alternative_index = 0
    while any(alternative_index < len(alternatives_group) for alternatives_group in groups):
        for alternatives_group in groups:
            if alternative_index >= len(alternatives_group):
                continue
            chunk_terms = [
                term
                for term in re.findall(
                    r"[\w]+(?:[./+-][\w]+)*",
                    alternatives_group[alternative_index],
                )
                if term.casefold() not in seen
            ]
            candidate_terms = [*terms, *chunk_terms]
            if (
                not chunk_terms
                or len(candidate_terms) > _OPENALEX_MAX_TERMS
                or len(" ".join(candidate_terms)) > _OPENALEX_MAX_QUERY_CHARS
            ):
                continue
            terms.extend(chunk_terms)
            seen.update(term.casefold() for term in chunk_terms)
        alternative_index += 1
    if not terms:
        raise ContestDirectionLiteratureError("logical query has no OpenAlex-searchable terms")
    return " ".join(terms)


def _compile_openalex_query_v2(
    logical_query: str,
    *,
    compiler_version: str = "source-query-compiler-v2",
) -> str:
    """Compile a bounded AND-of-OR query for title-and-abstract retrieval.

    Unlike v1, this compiler never flattens Boolean groups or silently drops
    alternatives.  Unsupported or overlong plans fail before a source request.
    """

    try:
        parsed = role_query_from_boolean(
            PlanningLiteratureRole.DIRECT_CORE,
            "source-compiler-v2",
            logical_query,
        )
    except PlanningLiteratureCoverageError as exc:
        raise ContestDirectionLiteratureError(
            f"logical query is not a legal source-neutral Boolean expression: {exc}"
        ) from exc
    if parsed.prefix_terms:
        raise ContestDirectionLiteratureError(f"{compiler_version} does not accept wildcard terms")
    if len(parsed.must_groups) > _OPENALEX_V2_MAX_GROUPS:
        raise ContestDirectionLiteratureError(
            f"{compiler_version} query has too many required groups"
        )

    clauses: list[str] = []
    for alternatives in parsed.must_groups:
        if len(alternatives) > _OPENALEX_V2_MAX_ALTERNATIVES_PER_GROUP:
            raise ContestDirectionLiteratureError(
                f"{compiler_version} group has too many alternatives"
            )
        if any(len(term) > _OPENALEX_V2_MAX_TERM_CHARS for term in alternatives):
            raise ContestDirectionLiteratureError(
                f"{compiler_version} term exceeds the bounded term length"
            )
        quoted = tuple(f'"{term}"' for term in alternatives)
        clauses.append(f"({' OR '.join(quoted)})")

    expression = " AND ".join(clauses)
    compiled = f"{OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX}{expression}"
    if len(compiled) > _OPENALEX_V2_MAX_QUERY_CHARS:
        raise ContestDirectionLiteratureError(
            f"{compiler_version} OpenAlex query exceeds the bounded request length"
        )
    return compiled


def _split_boolean_groups(logical_query: str) -> tuple[tuple[str, str], ...]:
    normalized = logical_query.replace("“", '"').replace("”", '"')
    groups: list[tuple[str, str]] = []
    pending_operator = "AND"
    quote_open = False
    group_start = 0
    index = 0
    while index < len(normalized):
        if normalized[index] == '"':
            quote_open = not quote_open
            index += 1
            continue
        match = None if quote_open else _BOOLEAN_OPERATOR.match(normalized, index)
        if match is None:
            index += 1
            continue
        group = normalized[group_start:index].strip()
        if group:
            groups.append((pending_operator, group))
        pending_operator = re.sub(r"\s+", " ", match.group(1).strip()).upper()
        index = match.end()
        group_start = index
    final_group = normalized[group_start:].strip()
    if final_group:
        groups.append((pending_operator, final_group))
    return tuple(groups)


def _select_evenly_spaced(values: list[str], *, limit: int) -> list[str]:
    if len(values) <= limit:
        return values
    if limit == 1:
        return values[:1]
    last_index = len(values) - 1
    indices = [(offset * last_index) // (limit - 1) for offset in range(limit)]
    return [values[index] for index in indices]


def _normalize_query_term(value: str, *, max_chars: int) -> str:
    normalized = re.sub(r"[*?~]", "", value)
    normalized = re.sub(
        r"\b(?:all|ti|title|abs|abstract|au|author|cat|category):",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.strip().strip("()[]{}\"'")
    normalized = re.sub(r"[^\w\s./+-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[: max_chars + 1].rsplit(" ", 1)[0].strip()
    return shortened or normalized[:max_chars].strip()


def _normalize_search_results(values: Sequence[AcademicPaper]) -> list[AcademicPaper]:
    if isinstance(values, str | bytes | bytearray) or not isinstance(values, Sequence):
        raise TypeError("search callable must return a sequence of AcademicPaper records")
    papers = [
        item if isinstance(item, AcademicPaper) else AcademicPaper.model_validate(item)
        for item in values
    ]
    normalized, _receipt = normalize_untrusted_scholarly_papers(papers)
    return list(normalized)


def _build_fetch_record(
    *,
    source: str,
    query: str,
    query_index: int,
    retrieved_at: datetime,
    papers: Sequence[AcademicPaper] | None,
    error: str | None,
) -> ContestDirectionFetchRecord:
    result_hash = (
        canonical_model_hash({"papers": [paper.model_dump(mode="json") for paper in papers]})
        if papers is not None
        else None
    )
    payload: dict[str, Any] = {
        "fetch_id": _fetch_id(
            source=source,
            query=query,
            query_index=query_index,
            retrieved_at=retrieved_at,
        ),
        "source": source,
        "query": query,
        "query_index": query_index,
        "retrieved_at": _canonical_datetime_text(retrieved_at),
        "status": "succeeded" if papers is not None else "failed",
        "returned_count": len(papers) if papers is not None else 0,
        "result_hash": result_hash,
        "error": error,
    }
    payload["fetch_hash"] = canonical_model_hash(payload)
    return ContestDirectionFetchRecord.model_validate(payload)


def _fetch_id(*, source: str, query: str, query_index: int, retrieved_at: datetime) -> str:
    digest = canonical_model_hash(
        {
            "source": source,
            "query": query,
            "query_index": query_index,
            "retrieved_at": _canonical_datetime_text(retrieved_at),
        }
    )
    return f"direction-fetch-{digest[:16]}"


def _deduplicate_hits(
    hits: Sequence[tuple[AcademicPaper, ContestDirectionRetrievalPointer]],
) -> tuple[ContestDirectionLiteratureRecord, ...]:
    unique_papers = deduplicate_papers([paper for paper, _pointer in hits])
    records: list[ContestDirectionLiteratureRecord] = []
    for canonical in unique_papers:
        members = [(paper, pointer) for paper, pointer in hits if _same_paper(canonical, paper)]
        merged = _merge_papers(canonical, [paper for paper, _pointer in members])
        pointers_by_id: dict[str, ContestDirectionRetrievalPointer] = {}
        for _paper, pointer in members:
            pointers_by_id.setdefault(pointer.fetch_id, pointer)
        pointers = tuple(pointers_by_id.values())
        paper_payload = merged.model_dump(mode="json")
        paper_hash = canonical_model_hash(paper_payload)
        record_payload: dict[str, Any] = {
            "record_id": f"direction-paper-{paper_hash[:16]}",
            "title": merged.title,
            "authors": merged.authors,
            "abstract": merged.abstract,
            "publication_date": (
                merged.publication_date.isoformat() if merged.publication_date is not None else None
            ),
            "venue": merged.venue,
            "doi": merged.doi,
            "repository_doi": merged.repository_doi,
            "url": merged.url,
            "citation_count": merged.citation_count,
            "citation_count_source": merged.citation_count_source,
            "citation_count_as_of": (
                merged.citation_count_as_of.isoformat()
                if merged.citation_count_as_of is not None
                else None
            ),
            "publication_status": merged.publication_status,
            "status_source": merged.status_source,
            "status_as_of": (
                merged.status_as_of.isoformat() if merged.status_as_of is not None else None
            ),
            "paper_source": merged.source,
            "retrievals": [item.model_dump(mode="json") for item in pointers],
            "paper_hash": paper_hash,
        }
        record_payload["record_hash"] = canonical_model_hash(record_payload)
        records.append(ContestDirectionLiteratureRecord.model_validate(record_payload))
    return tuple(records)


def _same_paper(left: AcademicPaper, right: AcademicPaper) -> bool:
    return len(deduplicate_papers([left, right])) == 1


def _merge_papers(
    canonical: AcademicPaper,
    members: Sequence[AcademicPaper],
) -> AcademicPaper:
    abstracts = [
        item.abstract.strip() for item in members if item.abstract and item.abstract.strip()
    ]
    citation_members = [item for item in members if item.citation_count is not None]
    citation_member = (
        max(citation_members, key=lambda item: item.citation_count or 0)
        if citation_members
        else None
    )
    status_priority = {
        "unknown": 0,
        "preprint": 1,
        "published": 2,
        "withdrawn": 3,
        "retracted": 4,
    }
    status_member = max(
        members,
        key=lambda item: status_priority.get(item.publication_status, 0),
    )
    return AcademicPaper(
        title=canonical.title,
        authors=canonical.authors or next((item.authors for item in members if item.authors), []),
        abstract=max(abstracts, key=len) if abstracts else None,
        publication_date=canonical.publication_date
        or next((item.publication_date for item in members if item.publication_date), None),
        venue=canonical.venue or next((item.venue for item in members if item.venue), None),
        doi=normalize_doi(canonical.doi)
        or next((normalize_doi(item.doi) for item in members if normalize_doi(item.doi)), None),
        repository_doi=normalize_doi(canonical.repository_doi)
        or next(
            (
                normalize_doi(item.repository_doi)
                for item in members
                if normalize_doi(item.repository_doi)
            ),
            None,
        ),
        url=canonical.url or next((item.url for item in members if item.url), None),
        citation_count=citation_member.citation_count if citation_member is not None else None,
        citation_count_source=(
            citation_member.citation_count_source if citation_member is not None else None
        ),
        citation_count_as_of=(
            citation_member.citation_count_as_of if citation_member is not None else None
        ),
        publication_status=status_member.publication_status,
        status_source=status_member.status_source,
        status_as_of=status_member.status_as_of,
        source=canonical.source,
    )


def _record_paper_payload(record: ContestDirectionLiteratureRecord) -> dict[str, Any]:
    if _record_has_enriched_metadata(record):
        return _enriched_record_paper_payload(record)
    return _legacy_record_paper_payload(record)


def _legacy_record_paper_payload(
    record: ContestDirectionLiteratureRecord,
) -> dict[str, Any]:
    return {
        "title": record.title,
        "authors": list(record.authors),
        "abstract": record.abstract,
        "publication_date": (
            record.publication_date.isoformat() if record.publication_date is not None else None
        ),
        "venue": record.venue,
        "doi": record.doi,
        "url": record.url,
        "citation_count": record.citation_count,
        "source": record.paper_source,
    }


def _enriched_record_paper_payload(
    record: ContestDirectionLiteratureRecord,
) -> dict[str, Any]:
    payload = _legacy_record_paper_payload(record)
    payload.update(
        {
            "repository_doi": record.repository_doi,
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
        }
    )
    return payload


def _record_has_enriched_metadata(record: ContestDirectionLiteratureRecord) -> bool:
    legacy_hash = canonical_model_hash(_legacy_record_paper_payload(record))
    if record.paper_hash == legacy_hash:
        return False
    enriched_hash = canonical_model_hash(_enriched_record_paper_payload(record))
    if record.paper_hash == enriched_hash:
        return True
    return bool(_ENRICHED_RECORD_FIELDS.intersection(record.model_fields_set))


def _record_dump_for_hash(record: ContestDirectionLiteratureRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json", exclude={"record_hash"})
    if not _record_has_enriched_metadata(record):
        for field in _ENRICHED_RECORD_FIELDS:
            payload.pop(field, None)
    return payload


def _direction_input_payload(
    *,
    direction: str,
    requirements: Sequence[str],
    method_skills: Sequence[ContestDirectionMethodSkill],
) -> dict[str, Any]:
    return {
        "input_mode": "specified_direction",
        "direction": direction,
        "requirements": list(requirements),
        "selected_method_skill_sha256": {
            item.skill_id: item.content_sha256 for item in method_skills
        },
    }


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _canonical_datetime_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ContestDirectionFetchRecord",
    "ContestDirectionLiteratureArtifact",
    "ContestDirectionLiteratureError",
    "ContestDirectionLiteratureRecord",
    "ContestDirectionMethodSkill",
    "ContestDirectionRetrievalPointer",
    "DirectionSearchCallable",
    "build_contest_direction_literature_messages",
    "default_contest_direction_searchers",
    "retrieve_contest_direction_literature",
]
