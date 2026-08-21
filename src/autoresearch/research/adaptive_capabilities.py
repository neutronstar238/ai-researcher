"""Concrete, provenance-preserving capabilities for the adaptive research loop.

The adapters in this module deliberately expose only capabilities that really
exist.  Retrieval stores the exact normalized tool catalogue before returning a
compact feedback record.  Dreaming writes a rebuildable, non-authoritative view
without touching raw sources.  Temporary Qwen workers are issued only by the
current step's main-agent controller and are archived before their summaries
return to the loop.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import Field, JsonValue, field_validator, model_validator

from autoresearch.agents.temporary import (
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    issue_stage_controller,
)
from autoresearch.competition.temporary_qwen_pool import (
    TemporaryQwenContentTask,
    TemporaryQwenSkillContext,
    run_temporary_qwen_content_batch,
)
from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    DreamingMemoryContent,
    MemoryClaimAssessment,
    MemoryClaimVerdict,
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.literature.clients import (
    ArxivClient,
    OpenAlexClient,
)
from autoresearch.literature.models import AcademicPaper, deduplicate_papers
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.adaptive_skill_router import (
    load_repository_skill_contexts,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    FeedbackOrigin,
    FeedbackStatus,
    ModelMemoryExposure,
    ModelResearchActionDraft,
    ResearchActionEnvironment,
    ResearchOperator,
    TemporaryAgentBatchOutcome,
    TemporaryAgentContribution,
    TemporaryResearchDispatcher,
    TemporaryResearchTask,
)
from autoresearch.research.adaptive_sovereign_recall import (
    SovereignRawRecallEngine,
    recall_findings_cn,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_MAX_RETRIEVAL_RESULTS_PER_SOURCE = 12
_MAX_RETRIEVAL_QUERY_CHARACTERS = 1_200
_MAX_TEMPORARY_INPUT_CHARACTERS = 28_000
_TECHNICAL_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{2,}")
_EXPLICIT_QUERY_PATTERN = re.compile(
    r"(?:检索查询|search_query)\s*[：:]\s*([^\r\n]+)",
    flags=re.IGNORECASE,
)


class AdaptiveCapabilityError(AdaptiveResearchLoopError):
    """Raised when a concrete adaptive capability cannot preserve provenance."""


class AdaptiveRetrievedPaperContent(KernelContract):
    """Normalized paper metadata returned by one real literature client."""

    paper_id: StableId
    source: StableId
    title: str = Field(min_length=1, max_length=4_000)
    authors: list[str] = Field(default_factory=list, max_length=512)
    abstract: str | None = Field(default=None, max_length=100_000)
    publication_date: date | None = None
    venue: str | None = Field(default=None, max_length=2_000)
    doi: str | None = Field(default=None, max_length=2_000)
    url: str | None = Field(default=None, max_length=4_000)
    citation_count: int = Field(default=0, ge=0)
    source_ref: str = Field(min_length=1, max_length=4_000)


class AdaptiveRetrievedPaper(AdaptiveRetrievedPaperContent):
    """Content-addressed literature metadata, not a full-paper evidence claim."""

    paper_hash: Sha256

    @model_validator(mode="after")
    def _verify_hash(self) -> AdaptiveRetrievedPaper:
        payload = self.model_dump(
            mode="json",
            exclude={"paper_hash", "paper_id"},
        )
        expected = canonical_sha256(payload)
        if self.paper_hash != expected:
            raise ValueError("adaptive retrieved paper hash mismatch")
        if self.paper_id != f"paper_{expected[:24]}":
            raise ValueError("adaptive retrieved paper ID mismatch")
        return self

    @classmethod
    def from_academic_paper(cls, paper: AcademicPaper) -> AdaptiveRetrievedPaper:
        source = _stable_source_id(paper.source)
        source_ref = _paper_source_ref(paper)
        citation_count = paper.citation_count if paper.citation_count is not None else 0
        payload = {
            "source": source,
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract,
            "publication_date": (
                paper.publication_date.isoformat() if paper.publication_date is not None else None
            ),
            "venue": paper.venue,
            "doi": paper.doi,
            "url": paper.url,
            "citation_count": citation_count,
            "source_ref": source_ref,
        }
        digest = canonical_sha256(payload)
        return cls(
            paper_id=f"paper_{digest[:24]}",
            source=source,
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            publication_date=paper.publication_date,
            venue=paper.venue,
            doi=paper.doi,
            url=paper.url,
            citation_count=citation_count,
            source_ref=source_ref,
            paper_hash=digest,
        )


class AdaptiveLiteratureFetch(KernelContract):
    """One source invocation without persisting transport error secrets."""

    source: StableId
    query: str = Field(min_length=1, max_length=_MAX_RETRIEVAL_QUERY_CHARACTERS)
    succeeded: bool
    paper_count: int = Field(ge=0, le=_MAX_RETRIEVAL_RESULTS_PER_SOURCE)
    error_type: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_error_shape(self) -> AdaptiveLiteratureFetch:
        if self.succeeded != (self.error_type is None):
            raise ValueError("adaptive literature fetch error shape mismatch")
        if not self.succeeded and self.paper_count:
            raise ValueError("failed literature fetch cannot report papers")
        return self


class AdaptiveLiteratureRetrievalArtifactContent(KernelContract):
    """Exact normalized result of one model-selected retrieval action."""

    schema_version: Literal["adaptive-literature-retrieval-v1"] = "adaptive-literature-retrieval-v1"
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1)
    branch_id: StableId
    proposal_hash: Sha256
    fetches: list[AdaptiveLiteratureFetch] = Field(min_length=1, max_length=8)
    papers: list[AdaptiveRetrievedPaper] = Field(max_length=96)
    normalized_catalog_binding: RawMemoryBinding
    output_relative_path: str = Field(min_length=1, max_length=1_024)
    tool_call_count: int = Field(ge=1, le=8)
    created_at: datetime
    full_text_verified: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adaptive capability timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("output_relative_path")
    @classmethod
    def _safe_output_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or ":" in normalized:
            raise ValueError("adaptive retrieval output path escapes its run root")
        return path.as_posix()

    @model_validator(mode="after")
    def _validate_counts(self) -> AdaptiveLiteratureRetrievalArtifactContent:
        if self.tool_call_count != len(self.fetches):
            raise ValueError("adaptive retrieval tool-call count mismatch")
        refs = [paper.source_ref for paper in self.papers]
        if len(refs) != len(set(refs)):
            raise ValueError("adaptive retrieval repeats a normalized source")
        return self


class AdaptiveLiteratureRetrievalArtifact(AdaptiveLiteratureRetrievalArtifactContent):
    """Content-addressed retrieval artifact retained outside private raw memory."""

    artifact_hash: Sha256

    @model_validator(mode="after")
    def _verify_hash(self) -> AdaptiveLiteratureRetrievalArtifact:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("adaptive retrieval artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLiteratureRetrievalArtifact:
        content = AdaptiveLiteratureRetrievalArtifactContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, artifact_hash=canonical_sha256(payload))


class AdaptiveTemporaryMemo(KernelContract):
    """Generic content-only response expected from one temporary Qwen worker."""

    schema_version: Literal["adaptive-temporary-memo-v1"] = "adaptive-temporary-memo-v1"
    summary_cn: str = Field(min_length=1, max_length=4_000)
    findings_cn: list[str] = Field(min_length=1, max_length=16)
    uncertainties_cn: list[str] = Field(min_length=1, max_length=16)
    source_refs: list[str] = Field(default_factory=list, max_length=32)
    is_scientific_evidence: Literal[False] = False
    can_approve: Literal[False] = False
    can_execute: Literal[False] = False
    can_publish: Literal[False] = False

    @field_validator("summary_cn")
    @classmethod
    def _summary_is_chinese(cls, value: str) -> str:
        return _require_chinese(value, "summary_cn")

    @field_validator("findings_cn", "uncertainties_cn")
    @classmethod
    def _lists_are_chinese(cls, value: list[str], info: Any) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError(f"{info.field_name} must be unique and non-empty")
        return [_require_chinese(item, info.field_name) for item in normalized]


class AdaptiveResearchCapabilityEnvironment(ResearchActionEnvironment):
    """Real retrieval and Dreaming adapters; no sandbox is advertised yet."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        raw_memory_store: RawMemoryStore,
        literature_clients: Mapping[str, Any] | None = None,
        max_results_per_source: int = 6,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= max_results_per_source <= _MAX_RETRIEVAL_RESULTS_PER_SOURCE:
            raise AdaptiveCapabilityError("literature result bound is outside policy")
        self._output_root = Path(output_dir).resolve()
        self._raw_memory_store = raw_memory_store
        self._clients = dict(
            literature_clients
            or {
                "arxiv": ArxivClient(),
                "openalex": OpenAlexClient(),
            }
        )
        if not self._clients:
            raise AdaptiveCapabilityError("literature client catalogue is empty")
        self._max_results = max_results_per_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset(
            {
                ResearchOperator.RETRIEVE_EVIDENCE,
                ResearchOperator.CONSOLIDATE_DREAMING,
            }
        )

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        if proposal.operator is ResearchOperator.RETRIEVE_EVIDENCE:
            return self._retrieve(seed=seed, snapshot=snapshot, proposal=proposal)
        if proposal.operator is ResearchOperator.CONSOLIDATE_DREAMING:
            return self._dream(seed=seed, snapshot=snapshot, proposal=proposal)
        raise AdaptiveCapabilityError(
            f"adaptive capability is not wired: {proposal.operator.value}"
        )

    def _retrieve(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        plain_query = _model_selected_query(seed, snapshot, proposal)
        fetches: list[AdaptiveLiteratureFetch] = []
        papers: list[AcademicPaper] = []
        for source, client in sorted(self._clients.items()):
            source_id = _stable_source_id(source)
            source_query = _source_query(source_id, plain_query)
            try:
                returned = client.search(source_query, limit=self._max_results)
            except Exception as exc:  # noqa: BLE001 - source failure is data.
                fetches.append(
                    AdaptiveLiteratureFetch(
                        source=source_id,
                        query=source_query,
                        succeeded=False,
                        paper_count=0,
                        error_type=type(exc).__name__,
                    )
                )
                continue
            normalized = [item.model_copy(update={"source": source_id}) for item in returned]
            papers.extend(normalized)
            fetches.append(
                AdaptiveLiteratureFetch(
                    source=source_id,
                    query=source_query,
                    succeeded=True,
                    paper_count=len(normalized),
                )
            )
        unique = deduplicate_papers(papers)
        normalized_papers = [AdaptiveRetrievedPaper.from_academic_paper(paper) for paper in unique]
        created_at = self._clock().astimezone(timezone.utc)
        catalog_payload = {
            "schema_version": "adaptive-normalized-literature-catalog-v1",
            "loop_id": seed.loop_id,
            "project_id": seed.project_id,
            "step_index": snapshot.next_step_index,
            "branch_id": proposal.branch_id,
            "proposal_hash": canonical_sha256(proposal),
            "fetches": [item.model_dump(mode="json") for item in fetches],
            "papers": [item.model_dump(mode="json") for item in normalized_papers],
            "transport_bytes_retained": False,
            "full_text_verified": False,
            "is_scientific_evidence": False,
        }
        capture = self._raw_memory_store.capture_text(
            canonical_json(catalog_payload),
            project_id=seed.project_id,
            source_kind=RawMemorySourceKind.TOOL_OUTPUT,
            source_label="自适应科研外部检索的规范化目录",
            source_ref=(
                f"adaptive-loop:{seed.loop_id}:step:{snapshot.next_step_index}:"
                "literature-catalog"
            ),
            original_name=(f"adaptive-literature-step-{snapshot.next_step_index:04d}.json"),
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=created_at,
        )
        relative_path = (
            Path("capabilities")
            / f"step-{snapshot.next_step_index:04d}"
            / "retrieval"
            / "adaptive-literature-retrieval.json"
        )
        artifact = AdaptiveLiteratureRetrievalArtifact.create(
            loop_id=seed.loop_id,
            project_id=seed.project_id,
            step_index=snapshot.next_step_index,
            branch_id=proposal.branch_id,
            proposal_hash=canonical_sha256(proposal),
            fetches=fetches,
            papers=normalized_papers,
            normalized_catalog_binding=capture.binding(self._raw_memory_store.vault_root),
            output_relative_path=relative_path.as_posix(),
            tool_call_count=len(fetches),
            created_at=created_at,
        )
        _write_once(
            self._output_root / relative_path,
            (canonical_json(artifact) + "\n").encode("utf-8"),
        )
        succeeded_sources = sum(item.succeeded for item in fetches)
        if normalized_papers:
            status = FeedbackStatus.SUCCEEDED
            summary = (
                f"外部文献检索完成，共返回{len(normalized_papers)}条去重元数据；"
                "它们仍需全文核验，不能直接证明创新。"
            )
        elif succeeded_sources:
            status = FeedbackStatus.NEGATIVE_RESULT
            summary = "外部文献源调用成功但没有返回匹配记录；该负结果已保留。"
        else:
            status = FeedbackStatus.FAILED
            summary = "全部外部文献源调用失败；失败类型已保留且未记录潜在凭据文本。"
        findings = [
            f"检索结果{index}：{paper.title}；当前只有来源元数据或摘要。"
            for index, paper in enumerate(normalized_papers[:12], start=1)
        ]
        findings.extend(
            f"来源{fetch.source}调用失败，失败类型为{fetch.error_type}。"
            for fetch in fetches
            if not fetch.succeeded
        )
        if not findings:
            findings = ["当前检索没有形成可核验的全文证据。"]
        return ExternalResearchFeedback.create(
            feedback_id=f"feedback:retrieval:{snapshot.next_step_index}",
            branch_id=proposal.branch_id,
            operator=proposal.operator,
            origin=FeedbackOrigin.EXTERNAL_RETRIEVAL,
            status=status,
            summary_cn=summary,
            findings_cn=findings,
            source_refs=[paper.source_ref for paper in normalized_papers],
            artifact_refs=[f"artifact:{artifact.artifact_hash}"],
            metrics={
                "paper_count": len(normalized_papers),
                "source_count": len(fetches),
                "successful_source_count": succeeded_sources,
            },
            tool_calls=len(fetches),
            independent_of_action_author=True,
        )

    def _dream(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        created_at = self._clock().astimezone(timezone.utc)
        request_capture = self._raw_memory_store.capture_text(
            canonical_json(proposal),
            project_id=seed.project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label="自适应科研主Agent的Dreaming整理请求",
            source_ref=(
                f"adaptive-loop:{seed.loop_id}:step:{snapshot.next_step_index}:" "dreaming-request"
            ),
            original_name=(f"adaptive-dreaming-step-{snapshot.next_step_index:04d}.json"),
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=created_at,
        )
        recall_relative_path = (
            Path("capabilities")
            / f"step-{snapshot.next_step_index:04d}"
            / "dreaming"
            / "sovereign-recall-selection.json"
        )
        recall = SovereignRawRecallEngine(
            raw_memory_store=self._raw_memory_store,
        ).recall(
            snapshot=snapshot,
            proposal=proposal,
            output_path=self._output_root / recall_relative_path,
        )
        recalled_bindings = [excerpt.binding for excerpt in recall.selected_excerpts]
        bindings = _unique_bindings(
            [
                *recalled_bindings,
                request_capture.binding(self._raw_memory_store.vault_root),
            ]
        )
        evidence_refs = [
            f"raw:{binding.record_id}#sha256:{binding.payload_sha256}" for binding in bindings
        ]
        projection = self._raw_memory_store.write_dreaming_projection(
            DreamingMemoryContent(
                project_id=seed.project_id,
                title=proposal.action_title_cn,
                generated_at=created_at,
                generator_identity=(
                    f"adaptive-main-{hashlib.sha256(seed.loop_id.encode()).hexdigest()[:16]}"
                ),
                source_bindings=bindings,
                summary="\n\n".join(recall_findings_cn(recall)),
                claim_assessments=[
                    MemoryClaimAssessment(
                        claim=proposal.action_title_cn,
                        verdict=MemoryClaimVerdict.UNVERIFIED,
                        rationale=(
                            "这是主Agent请求触发的确定性原始记忆召回和派生整理；"
                            "召回只证明这些字节曾被保留，不证明其内容正确、仍然有效"
                            "或具有科学新颖性。"
                        ),
                        evidence_refs=evidence_refs,
                    )
                ],
                design_decisions=[proposal.action_body_cn],
            )
        )
        relative_markdown = projection.markdown_path.relative_to(
            self._raw_memory_store.vault_root
        ).as_posix()
        return ExternalResearchFeedback.create(
            feedback_id=f"feedback:dreaming:{snapshot.next_step_index}",
            branch_id=proposal.branch_id,
            operator=proposal.operator,
            origin=FeedbackOrigin.DREAMING_PROJECTION,
            status=FeedbackStatus.SUCCEEDED,
            summary_cn="Dreaming派生视图已生成；所有原始记录保持不变且可逐项重验。",
            findings_cn=recall_findings_cn(recall),
            source_refs=[binding.record_id for binding in bindings],
            artifact_refs=[
                f"artifact:{recall.selection_hash}",
                f"artifact-path:{recall_relative_path.as_posix()}",
                f"artifact:{projection.projection.projection_hash}",
                f"artifact-path:{relative_markdown}",
            ],
            metrics={
                "candidate_record_count": recall.candidate_record_count,
                "externally_reusable_record_count": (recall.externally_reusable_record_count),
                "privacy_excluded_record_count": recall.privacy_excluded_record_count,
                "recalled_record_count": len(recall.selected_excerpts),
                "omitted_record_count": recall.omitted_record_count,
                "projection_source_record_count": len(bindings),
                "recall_from_complete_history": True,
            },
            memory_exposures=[
                ModelMemoryExposure(
                    dreaming_step_index=snapshot.next_step_index,
                    selection_hash=recall.selection_hash,
                    record_id=excerpt.binding.record_id,
                    payload_sha256=excerpt.binding.payload_sha256,
                    excerpt_sha256=excerpt.excerpt_sha256,
                    excerpt_text=excerpt.excerpt_text,
                )
                for excerpt in recall.selected_excerpts
            ],
            tool_calls=1,
            independent_of_action_author=False,
        )


class TemporaryQwenResearchDispatcher(TemporaryResearchDispatcher):
    """Bridge main-agent-selected content tasks to the ephemeral Qwen pool."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        skill_root: Path | str,
        completion: CompletionCallable = run_llm_json_completion,
        config_path: Path | str = Path("config.yaml"),
        env_path: Path | str = Path(".env"),
        max_workers: int = 4,
        thinking_budget: int = 2_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= max_workers <= 7:
            raise AdaptiveCapabilityError("temporary worker bound is outside policy")
        self._output_root = Path(output_dir).resolve()
        self._skill_root = Path(skill_root)
        self._completion = completion
        self._config_path = Path(config_path)
        self._env_path = Path(env_path)
        self._max_workers = max_workers
        self._thinking_budget = thinking_budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def dispatch(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        tasks: Sequence[TemporaryResearchTask],
    ) -> TemporaryAgentBatchOutcome:
        if proposal.operator is not ResearchOperator.CONSULT_TEMPORARY_AGENTS:
            raise AdaptiveCapabilityError("temporary dispatch requires its operator")
        if not tasks:
            raise AdaptiveCapabilityError("temporary dispatch cannot be empty")
        now = self._clock().astimezone(timezone.utc)
        stage_input_hash = canonical_sha256(
            {
                "seed": seed.model_dump(mode="json"),
                "snapshot_hash": snapshot.snapshot_hash,
                "proposal": proposal.model_dump(mode="json"),
                "tasks": [item.model_dump(mode="json") for item in tasks],
            }
        )
        controller, capability = issue_stage_controller(
            lineage_id=seed.loop_id,
            stage=f"adaptive-step-{snapshot.next_step_index}",
            stage_attempt=1,
            controller_agent_id=f"adaptive-main-{snapshot.next_step_index}",
            stage_input_hash=stage_input_hash,
            max_parallel_agents=min(len(tasks), self._max_workers),
            claimed_at=now,
        )
        pool_tasks = tuple(
            self._pool_task(
                seed=seed,
                snapshot=snapshot,
                proposal=proposal,
                task=task,
                index=index,
            )
            for index, task in enumerate(tasks, start=1)
        )
        batch_id = f"adaptive-batch-{snapshot.next_step_index:04d}"
        artifact = run_temporary_qwen_content_batch(
            batch_id=batch_id,
            controller=controller,
            capability=capability,
            tasks=pool_tasks,
            output_dir=(self._output_root / "temporary" / f"step-{snapshot.next_step_index:04d}"),
            completion=self._completion,
            config_path=self._config_path,
            env_path=self._env_path,
            max_workers=min(len(pool_tasks), self._max_workers),
            thinking_budget=self._thinking_budget,
            clock=now,
        )
        if capability.active:
            raise AdaptiveCapabilityError(
                "temporary stage capability remained active after archival"
            )
        record_by_dispatch = {record.dispatch_id: record for record in artifact.task_records}
        contributions: list[TemporaryAgentContribution] = []
        for output in artifact.stable_outputs:
            memo = AdaptiveTemporaryMemo.model_validate(output.output_payload)
            record = record_by_dispatch[output.dispatch_id]
            summary = _temporary_summary(memo)
            contributions.append(
                TemporaryAgentContribution(
                    dispatch_id=output.dispatch_id,
                    result_hash=output.result_hash,
                    archive_hash=record.archive_hash,
                    summary_cn=summary,
                )
            )
        if len(contributions) != len(tasks):
            raise AdaptiveCapabilityError(
                "temporary batch did not return one archived output per task"
            )
        return TemporaryAgentBatchOutcome.create(
            batch_id=batch_id,
            contributions=contributions,
        )

    def _pool_task(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        task: TemporaryResearchTask,
        index: int,
    ) -> TemporaryQwenContentTask:
        skill_contexts = load_repository_skill_contexts(
            self._skill_root,
            task.selected_skill_ids,
        )
        temporary_skills = tuple(
            TemporaryQwenSkillContext(
                skill_ref=TemporaryAgentSkillRef(
                    skill_id=skill.skill_id,
                    source_ref=skill.source_ref,
                    content_sha256=skill.content_sha256,
                ),
                content=skill.content,
            )
            for skill in skill_contexts
        )
        input_payload: dict[str, JsonValue] = {
            "研究目标": seed.objective_cn,
            "研究范围": seed.scope_cn,
            "当前分支": next(
                branch.model_dump(mode="json")
                for branch in snapshot.branches
                if branch.branch_id == proposal.branch_id
            ),
            "主Agent动作标题": proposal.action_title_cn,
            "主Agent动作内容": proposal.action_body_cn,
            "临时任务角色": task.role_cn,
            "临时任务问题": task.question_cn,
            "权限边界": {
                "可再派工": False,
                "可执行": False,
                "可审批": False,
                "可发表": False,
            },
        }
        serialized_size = len(json.dumps(input_payload, ensure_ascii=False, sort_keys=True))
        if serialized_size > _MAX_TEMPORARY_INPUT_CHARACTERS:
            raise AdaptiveCapabilityError(
                "temporary task context is too large; main agent must request a narrower task"
            )
        digest = canonical_sha256(
            {
                "loop_id": seed.loop_id,
                "step_index": snapshot.next_step_index,
                "task": task.model_dump(mode="json"),
            }
        )
        return TemporaryQwenContentTask(
            dispatch_id=f"adaptive-{snapshot.next_step_index:04d}-{digest[:16]}",
            temporary_agent_id=(
                f"temporary-{snapshot.next_step_index:04d}-{index:02d}-{digest[:12]}"
            ),
            parent_task_id=(
                f"adaptive-parent-{hashlib.sha256(seed.loop_id.encode()).hexdigest()[:20]}-"
                f"{snapshot.next_step_index:04d}"
            ),
            task_kind=_temporary_task_kind(task),
            task_instruction=task.question_cn,
            input_refs=(
                TemporaryAgentInputRef(
                    artifact_id="adaptive-seed",
                    source_ref=seed.raw_seed_binding.record_relative_path,
                    sha256=seed.raw_seed_binding.record_hash,
                ),
                TemporaryAgentInputRef(
                    artifact_id="adaptive-snapshot",
                    source_ref=f"snapshot:{snapshot.snapshot_hash}",
                    sha256=snapshot.snapshot_hash,
                ),
                TemporaryAgentInputRef(
                    artifact_id="adaptive-parent-action",
                    source_ref=f"proposal:{digest}",
                    sha256=canonical_sha256(proposal),
                ),
            ),
            input_payload=input_payload,
            expected_output_schema=cast(
                dict[str, JsonValue],
                AdaptiveTemporaryMemo.model_json_schema(),
            ),
            chinese_output_fields=(
                "summary_cn",
                "findings_cn",
                "uncertainties_cn",
            ),
            skill_contexts=temporary_skills,
            max_tokens=4_000,
            timeout_seconds=300,
            minimum_reasoning_characters=200,
        )


def _stable_source_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.+-]+", "-", value.strip()).strip("-")
    if normalized:
        return normalized[:256]
    return f"source-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _paper_source_ref(paper: AcademicPaper) -> str:
    if paper.url:
        return paper.url.strip()
    if paper.doi:
        return f"doi:{paper.doi.strip()}"
    digest = hashlib.sha256(f"{paper.source}\n{paper.title}".encode()).hexdigest()
    return f"artifact:paper-metadata-{digest}"


def _model_selected_query(
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    proposal: ModelResearchActionDraft,
) -> str:
    if proposal.schema_version == "adaptive-research-action-draft-v3":
        if not proposal.retrieval_query_terms:
            raise AdaptiveCapabilityError(
                "structured retrieval action lost its model-selected query terms"
            )
        query = " ".join(proposal.retrieval_query_terms)
        if len(query) > _MAX_RETRIEVAL_QUERY_CHARACTERS:
            raise AdaptiveCapabilityError("structured retrieval query exceeds capability limit")
        return query
    explicit = _EXPLICIT_QUERY_PATTERN.search(proposal.action_body_cn)
    if explicit is not None:
        explicit_tokens = _TECHNICAL_TOKEN_PATTERN.findall(explicit.group(1))
        explicit_query = " ".join(dict.fromkeys(token.casefold() for token in explicit_tokens[:10]))
        if explicit_query:
            return explicit_query[:_MAX_RETRIEVAL_QUERY_CHARACTERS]
    branch = next(branch for branch in snapshot.branches if branch.branch_id == proposal.branch_id)
    texts = (
        proposal.action_title_cn,
        proposal.action_body_cn,
        branch.working_hypothesis_cn,
        seed.objective_cn,
    )
    tokens: list[str] = []
    for text in texts:
        tokens.extend(_TECHNICAL_TOKEN_PATTERN.findall(text))
    unique_tokens = list(dict.fromkeys(token.casefold() for token in tokens))
    if unique_tokens:
        query = " ".join(unique_tokens[:8])
    else:
        query = " ".join([proposal.action_title_cn, branch.working_hypothesis_cn])
    return query[:_MAX_RETRIEVAL_QUERY_CHARACTERS].strip()


def _source_query(source: str, plain_query: str) -> str:
    if source.casefold() != "arxiv":
        return plain_query
    tokens = plain_query.split()
    if not tokens:
        return f'all:"{plain_query}"'
    return " AND ".join(f"all:{token}" for token in tokens[:3])


def _unique_bindings(bindings: Sequence[RawMemoryBinding]) -> list[RawMemoryBinding]:
    by_id: dict[str, RawMemoryBinding] = {}
    for binding in bindings:
        existing = by_id.get(binding.record_id)
        if existing is not None and existing != binding:
            raise AdaptiveCapabilityError("raw-memory record ID binding collision")
        by_id[binding.record_id] = binding
    return [by_id[key] for key in sorted(by_id)]


def _temporary_task_kind(task: TemporaryResearchTask) -> TemporaryAgentTaskKind:
    text = f"{task.role_cn}{task.question_cn}"
    if "文献" in text or "先前工作" in text:
        return TemporaryAgentTaskKind.LITERATURE_COMPARISON
    if any(marker in text for marker in ("反例", "反方", "混杂", "批判")):
        return TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE
    return TemporaryAgentTaskKind.CONTENT_CHECKLIST


def _temporary_summary(memo: AdaptiveTemporaryMemo) -> str:
    parts = [memo.summary_cn]
    parts.extend(f"主要发现：{item}" for item in memo.findings_cn)
    parts.extend(f"仍有不确定性：{item}" for item in memo.uncertainties_cn)
    summary = "\n".join(parts)
    if len(summary) > 8_000:
        raise AdaptiveCapabilityError("temporary memo exceeds retained summary bound")
    return summary


def _require_chinese(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not any("\u3400" <= character <= "\u9fff" for character in normalized):
        raise ValueError(f"{field_name} 必须包含中文")
    return normalized


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveCapabilityError(
                f"immutable adaptive capability artifact changed: {path}"
            ) from None


__all__ = [
    "AdaptiveCapabilityError",
    "AdaptiveLiteratureFetch",
    "AdaptiveLiteratureRetrievalArtifact",
    "AdaptiveResearchCapabilityEnvironment",
    "AdaptiveRetrievedPaper",
    "AdaptiveTemporaryMemo",
    "TemporaryQwenResearchDispatcher",
]
