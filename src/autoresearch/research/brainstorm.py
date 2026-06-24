"""Temporary miniagent brainstorming over broad inspiration signals."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from autoresearch.inspiration import (
    GitHubRepositorySearchClient,
    HackerNewsSearchClient,
    HuggingFaceDatasetClient,
    InspirationItem,
    InspirationRefreshConfig,
    InspirationRefreshReport,
    run_inspiration_refresh,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import (
    AcademicPaper,
    LiteratureRefreshConfig,
    LiteratureRefreshReport,
    run_daily_literature_refresh,
)
from autoresearch.llm import LLMClientError, run_llm_json_completion
from autoresearch.schemas import ResearchCandidate


@dataclass(frozen=True)
class BrainstormConfig:
    """Configuration for high-divergence temporary miniagent brainstorming."""

    max_miniagents: int = 5
    ideas_per_agent: int = 2
    temperature: float = 1.2
    min_selected_ideas: int = 2


@dataclass(frozen=True)
class BrainstormEvidenceReviewConfig:
    """Configuration for the evidence-backed second-stage brainstorm reviewer."""

    max_reviewed_ideas: int = 10
    max_queries_per_idea: int = 2
    max_results_per_source: int = 2
    min_total_evidence: int = 1
    require_dataset_or_code_for_promote: bool = False
    medium_duplicate_overlap: float = 0.50
    high_duplicate_overlap: float = 0.68


@dataclass(frozen=True)
class BrainstormEvidenceSignal:
    """One source-backed signal used by the second-stage brainstorm reviewer."""

    source: str
    source_type: str
    title: str
    url: str
    query: str
    summary: str
    relevance_score: float

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "query": self.query,
            "summary": self.summary,
            "relevance_score": self.relevance_score,
        }


@dataclass(frozen=True)
class BrainstormEvidenceFetch:
    """One source fetch attempted by the second-stage brainstorm reviewer."""

    source: str
    source_type: str
    query: str
    result_count: int
    rate_limit_seconds: float
    cache_hit: bool | None = None
    error: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "query": self.query,
            "result_count": self.result_count,
            "rate_limit_seconds": self.rate_limit_seconds,
            "cache_hit": self.cache_hit,
            "error": self.error,
        }


@dataclass(frozen=True)
class BrainstormIdeaEvidenceReview:
    """Deterministic reviewer verdict for one brainstorm idea."""

    idea_id: str
    queries: tuple[str, ...]
    signals: tuple[BrainstormEvidenceSignal, ...]
    literature_count: int
    dataset_count: int
    code_count: int
    forum_count: int
    duplicate_risk: str
    verifiability: str
    doability: str
    decision: str
    score_adjustment: float
    reason: str
    fetches: tuple[BrainstormEvidenceFetch, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "idea_id": self.idea_id,
            "queries": list(self.queries),
            "signals": [signal.to_json_dict() for signal in self.signals],
            "literature_count": self.literature_count,
            "dataset_count": self.dataset_count,
            "code_count": self.code_count,
            "forum_count": self.forum_count,
            "duplicate_risk": self.duplicate_risk,
            "verifiability": self.verifiability,
            "doability": self.doability,
            "decision": self.decision,
            "score_adjustment": self.score_adjustment,
            "reason": self.reason,
            "fetches": [fetch.to_json_dict() for fetch in self.fetches],
        }


@dataclass(frozen=True)
class BrainstormMiniAgentPrompt:
    """Prompt contract for one throwaway creative miniagent."""

    agent_id: str
    role: str
    perspective: str
    temperature_offset: float
    prompt_template: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "perspective": self.perspective,
            "temperature_offset": self.temperature_offset,
            "prompt_template": self.prompt_template,
        }


@dataclass(frozen=True)
class BrainstormMiniAgentRun:
    """Auditable raw record for one temporary miniagent call."""

    agent_id: str
    role: str
    perspective: str
    temperature: float
    status: str
    raw_response: str | None = None
    error: str | None = None
    usage: Mapping[str, object] | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "perspective": self.perspective,
            "temperature": self.temperature,
            "status": self.status,
            "raw_response": self.raw_response,
            "error": self.error,
            "usage": dict(self.usage or {}),
        }


@dataclass(frozen=True)
class BrainstormIdea:
    """One proposed idea from a temporary miniagent."""

    idea_id: str
    agent_id: str
    title: str
    hypothesis: str
    rationale: str
    novelty_angle: str
    experiment_sketch: str
    inspiration_refs: tuple[str, ...]
    risks: tuple[str, ...]
    creativity_score: float
    feasibility_score: float
    evidence_binding_score: float
    selection_score: float
    selected: bool = False
    selection_reason: str = "Pending deterministic screening."

    def to_json_dict(self) -> dict[str, object]:
        return {
            "idea_id": self.idea_id,
            "agent_id": self.agent_id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "rationale": self.rationale,
            "novelty_angle": self.novelty_angle,
            "experiment_sketch": self.experiment_sketch,
            "inspiration_refs": list(self.inspiration_refs),
            "risks": list(self.risks),
            "creativity_score": self.creativity_score,
            "feasibility_score": self.feasibility_score,
            "evidence_binding_score": self.evidence_binding_score,
            "selection_score": self.selection_score,
            "selected": self.selected,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True)
class BrainstormReport:
    """Brainstorm output with raw ideas and deterministic synthesis."""

    candidate_id: str
    status: str
    prompts: tuple[BrainstormMiniAgentPrompt, ...]
    runs: tuple[BrainstormMiniAgentRun, ...]
    ideas: tuple[BrainstormIdea, ...]
    selected_ideas: tuple[BrainstormIdea, ...]
    synthesis: str
    evidence_reviews: tuple[BrainstormIdeaEvidenceReview, ...] = ()
    artifact_path: Path | None = None
    prompt_set_path: Path | None = None
    summary_path: Path | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "prompts": [prompt.to_json_dict() for prompt in self.prompts],
            "runs": [run.to_json_dict() for run in self.runs],
            "ideas": [idea.to_json_dict() for idea in self.ideas],
            "selected_ideas": [idea.to_json_dict() for idea in self.selected_ideas],
            "evidence_reviews": [review.to_json_dict() for review in self.evidence_reviews],
            "synthesis": self.synthesis,
            "artifact_path": self.artifact_path.as_posix() if self.artifact_path else None,
            "prompt_set_path": self.prompt_set_path.as_posix() if self.prompt_set_path else None,
            "summary_path": self.summary_path.as_posix() if self.summary_path else None,
            "evidence_policy": (
                "Brainstorm ideas are hypotheses only. Inspiration refs are context signals, "
                "not proof of results, novelty, or publishability. Evidence reviews record "
                "retrieval metadata for screening duplicate, unverifiable, or hard-to-execute ideas; "
                "they are not benchmark outcomes."
            ),
        }


BrainstormCompletionRunner = Callable[
    [BrainstormMiniAgentPrompt, list[dict[str, str]], float],
    Mapping[str, object],
]
BrainstormEvidenceReviewRunner = Callable[
    [
        ResearchCandidate,
        tuple[BrainstormIdea, ...],
        Path,
        Path,
        BrainstormEvidenceReviewConfig,
    ],
    tuple[BrainstormIdeaEvidenceReview, ...],
]


DEFAULT_BRAINSTORM_MINIAGENTS: tuple[BrainstormMiniAgentPrompt, ...] = (
    BrainstormMiniAgentPrompt(
        agent_id="cross_pollinator",
        role="Cross-pollination miniagent",
        perspective="Borrow mechanisms from adjacent tools, datasets, and communities.",
        temperature_offset=0.05,
        prompt_template=(
            "Combine at least two inspiration signals or one signal plus one candidate "
            "constraint. Prefer surprising but scriptable method or evaluation ideas."
        ),
    ),
    BrainstormMiniAgentPrompt(
        agent_id="failure_inverter",
        role="Failure-inversion miniagent",
        perspective="Treat limitations, source gaps, and negative signals as design material.",
        temperature_offset=0.15,
        prompt_template=(
            "Turn missing evidence, source sparsity, or likely failure modes into a concrete "
            "research hypothesis that can be falsified by a small experiment."
        ),
    ),
    BrainstormMiniAgentPrompt(
        agent_id="dataset_opportunist",
        role="Dataset opportunist miniagent",
        perspective="Search for measurement angles enabled by public datasets or benchmarks.",
        temperature_offset=0.0,
        prompt_template=(
            "Propose dataset-grounded ideas that can be tested with public data, clear metrics, "
            "and a baseline rerun before any paper claim is written."
        ),
    ),
    BrainstormMiniAgentPrompt(
        agent_id="systems_builder",
        role="Systems-builder miniagent",
        perspective="Convert research workflow pain points into systems experiments.",
        temperature_offset=0.1,
        prompt_template=(
            "Favor ideas that improve loop automation, provenance, retrieval breadth, "
            "or evidence binding, while remaining measurable in a local benchmark."
        ),
    ),
    BrainstormMiniAgentPrompt(
        agent_id="skeptical_reviewer",
        role="Skeptical reviewer miniagent",
        perspective="Ask what would be novel, falsifiable, and hard for prior work to dismiss.",
        temperature_offset=-0.05,
        prompt_template=(
            "Generate bolder variants, but include the first experiment that could disprove "
            "the idea and the closest duplicate risk to check."
        ),
    ),
)


def run_inspiration_brainstorm(
    *,
    candidate: ResearchCandidate,
    inspiration_report: InspirationRefreshReport,
    vault_root: Path | str,
    output_dir: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    config: BrainstormConfig = BrainstormConfig(),
    evidence_review_config: BrainstormEvidenceReviewConfig = BrainstormEvidenceReviewConfig(),
    completion_runner: BrainstormCompletionRunner | None = None,
    evidence_review_runner: BrainstormEvidenceReviewRunner | None = None,
    enable_evidence_review: bool = False,
    evidence_cache_root: Path | str | None = None,
    write_summary: bool = True,
) -> BrainstormReport:
    """Run high-temperature temporary miniagents and synthesize feasible creative ideas."""

    if config.max_miniagents < 1:
        msg = "max_miniagents must be at least 1"
        raise ValueError(msg)
    if config.ideas_per_agent < 1:
        msg = "ideas_per_agent must be at least 1"
        raise ValueError(msg)
    prompts = DEFAULT_BRAINSTORM_MINIAGENTS[: config.max_miniagents]
    item_refs = _inspiration_item_refs(inspiration_report.items)
    known_refs = set(item_refs)
    runs: list[BrainstormMiniAgentRun] = []
    ideas: list[BrainstormIdea] = []
    for prompt in prompts:
        temperature = _clamp(config.temperature + prompt.temperature_offset, 0.0, 2.0)
        messages = _brainstorm_messages(
            candidate=candidate,
            inspiration_report=inspiration_report,
            item_refs=item_refs,
            prompt=prompt,
            ideas_per_agent=config.ideas_per_agent,
        )
        try:
            if completion_runner is None:
                result = run_llm_json_completion(
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                payload: Mapping[str, object] = result.parsed_json
                raw_response = result.response_text
                usage = result.usage
            else:
                payload = completion_runner(prompt, messages, temperature)
                raw_response = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                usage = {}
            runs.append(
                BrainstormMiniAgentRun(
                    agent_id=prompt.agent_id,
                    role=prompt.role,
                    perspective=prompt.perspective,
                    temperature=temperature,
                    status="completed",
                    raw_response=raw_response,
                    usage=usage,
                )
            )
            ideas.extend(
                _ideas_from_payload(
                    payload,
                    prompt=prompt,
                    known_refs=known_refs,
                    ideas_per_agent=config.ideas_per_agent,
                )
            )
        except (LLMClientError, ValueError) as exc:
            runs.append(
                BrainstormMiniAgentRun(
                    agent_id=prompt.agent_id,
                    role=prompt.role,
                    perspective=prompt.perspective,
                    temperature=temperature,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    evidence_reviews: tuple[BrainstormIdeaEvidenceReview, ...] = ()
    if ideas and evidence_review_runner is not None:
        evidence_reviews = evidence_review_runner(
            candidate,
            tuple(ideas),
            Path(vault_root),
            Path(evidence_cache_root or Path(output_dir) / "evidence-cache"),
            evidence_review_config,
        )
    elif ideas and enable_evidence_review:
        evidence_reviews = run_brainstorm_evidence_review(
            candidate=candidate,
            ideas=tuple(ideas),
            vault_root=Path(vault_root),
            cache_root=Path(evidence_cache_root or Path(output_dir) / "evidence-cache"),
            config=evidence_review_config,
        )
    selected = _select_ideas(
        ideas,
        min_selected=config.min_selected_ideas,
        evidence_reviews=evidence_reviews,
    )
    synthesis = _synthesize_brainstorm(
        ideas=tuple(ideas),
        selected=selected,
        evidence_reviews=evidence_reviews,
    )
    status = "selected" if selected else ("ideas_recorded" if ideas else "failed")
    report = BrainstormReport(
        candidate_id=candidate.id,
        status=status,
        prompts=prompts,
        runs=tuple(runs),
        ideas=tuple(ideas),
        selected_ideas=selected,
        synthesis=synthesis,
        evidence_reviews=evidence_reviews,
    )
    return _write_brainstorm_report(
        report=report,
        candidate=candidate,
        inspiration_report=inspiration_report,
        vault_root=Path(vault_root),
        output_dir=Path(output_dir),
        write_summary=write_summary,
    )


def _brainstorm_messages(
    *,
    candidate: ResearchCandidate,
    inspiration_report: InspirationRefreshReport,
    item_refs: Mapping[str, InspirationItem],
    prompt: BrainstormMiniAgentPrompt,
    ideas_per_agent: int,
) -> list[dict[str, str]]:
    item_lines = []
    for ref, item in item_refs.items():
        item_lines.append(
            f"- {ref}: {item.title} | source={item.source} | type={item.source_type} | "
            f"url={item.url} | summary={item.summary}"
        )
    if not item_lines:
        item_lines.append("- none: no broad inspiration item was returned; be explicit about this gap.")
    query_lines = [f"- {query}" for query in inspiration_report.queries] or ["- none recorded"]
    return [
        {
            "role": "system",
            "content": (
                "You are a temporary high-divergence AI-Researcher brainstorm miniagent. "
                "You expire after this run. Return only one valid JSON object, no markdown. "
                "Use provided inspiration refs only; do not invent URLs, papers, benchmark "
                "scores, or completed results. Ideas are hypotheses, not conclusions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Miniagent role: {prompt.role}\n"
                f"Perspective: {prompt.perspective}\n"
                f"Instruction: {prompt.prompt_template}\n\n"
                f"Candidate id: {candidate.id}\n"
                f"Candidate title: {candidate.title}\n"
                f"Research gap: {candidate.research_gap}\n"
                f"Description: {candidate.description}\n"
                f"Metadata: {json.dumps(dict(candidate.metadata), ensure_ascii=False, sort_keys=True)}\n\n"
                "Inspiration queries:\n"
                + "\n".join(query_lines)
                + "\n\nInspiration items:\n"
                + "\n".join(item_lines)
                + "\n\nReturn this JSON shape exactly:\n"
                '{"ideas":[{"title":"...","hypothesis":"...","rationale":"...",'
                '"novelty_angle":"...","experiment_sketch":"...",'
                '"inspiration_refs":["inspiration_item_1"],"risks":["..."],'
                '"creativity_score":0.0,"feasibility_score":0.0}]}. '
                f"Return {ideas_per_agent} ideas. Scores must be numbers from 0 to 1. "
                "The experiment_sketch must name a baseline, dataset or data source, metric, "
                "and first falsification check."
            ),
        },
    ]


def _ideas_from_payload(
    payload: Mapping[str, object],
    *,
    prompt: BrainstormMiniAgentPrompt,
    known_refs: set[str],
    ideas_per_agent: int,
) -> list[BrainstormIdea]:
    rows = payload.get("ideas")
    if not isinstance(rows, list):
        msg = f"miniagent {prompt.agent_id} response missing ideas list"
        raise ValueError(msg)
    ideas: list[BrainstormIdea] = []
    for index, row in enumerate(rows[:ideas_per_agent], start=1):
        if not isinstance(row, Mapping):
            continue
        title = _short_text(row.get("title"))
        hypothesis = _short_text(row.get("hypothesis"))
        experiment = _short_text(row.get("experiment_sketch"))
        if not (title and hypothesis and experiment):
            continue
        refs = tuple(
            str(ref).strip()
            for ref in row.get("inspiration_refs", [])
            if isinstance(ref, str) and ref.strip()
        )
        evidence_score = _evidence_binding_score(refs, known_refs)
        creativity = _number_score(row.get("creativity_score"), default=0.5)
        feasibility = _number_score(row.get("feasibility_score"), default=0.5)
        selection_score = round(0.42 * creativity + 0.38 * feasibility + 0.20 * evidence_score, 3)
        ideas.append(
            BrainstormIdea(
                idea_id=f"{prompt.agent_id}_{index}",
                agent_id=prompt.agent_id,
                title=title,
                hypothesis=hypothesis,
                rationale=_short_text(row.get("rationale")) or "No rationale supplied.",
                novelty_angle=_short_text(row.get("novelty_angle")) or "Novelty angle pending.",
                experiment_sketch=experiment,
                inspiration_refs=refs,
                risks=tuple(_string_list(row.get("risks"))) or ("Risk analysis pending.",),
                creativity_score=creativity,
                feasibility_score=feasibility,
                evidence_binding_score=evidence_score,
                selection_score=selection_score,
                selection_reason="Pending deterministic screening.",
            )
        )
    return ideas


def _select_ideas(
    ideas: list[BrainstormIdea],
    *,
    min_selected: int,
    evidence_reviews: tuple[BrainstormIdeaEvidenceReview, ...] = (),
) -> tuple[BrainstormIdea, ...]:
    if not ideas:
        return ()
    reviews_by_id = {review.idea_id: review for review in evidence_reviews}
    adjusted_ideas = [
        replace(
            idea,
            selection_score=_review_adjusted_selection_score(idea, reviews_by_id.get(idea.idea_id)),
        )
        for idea in ideas
    ]
    sorted_ideas = sorted(
        adjusted_ideas,
        key=lambda idea: (
            -idea.selection_score,
            -idea.creativity_score,
            -idea.feasibility_score,
            idea.idea_id,
        ),
    )
    if reviews_by_id:
        eligible_ideas = [
            idea
            for idea in sorted_ideas
            if reviews_by_id.get(idea.idea_id) is None
            or reviews_by_id[idea.idea_id].decision != "defer"
        ]
    else:
        eligible_ideas = sorted_ideas
    selection_count = min(max(min_selected, 1), len(eligible_ideas)) if eligible_ideas else 0
    selected_ids = {idea.idea_id for idea in eligible_ideas[:selection_count]}
    calibrated = [
        replace(
            idea,
            selected=idea.idea_id in selected_ids,
            selection_reason=_screening_reason(
                idea,
                selected=idea.idea_id in selected_ids,
                selection_count=selection_count,
                review=reviews_by_id.get(idea.idea_id),
            ),
        )
        for idea in adjusted_ideas
    ]
    ideas[:] = calibrated
    return tuple(idea for idea in calibrated if idea.selected)


def run_brainstorm_evidence_review(
    *,
    candidate: ResearchCandidate,
    ideas: tuple[BrainstormIdea, ...],
    vault_root: Path | str,
    cache_root: Path | str,
    config: BrainstormEvidenceReviewConfig = BrainstormEvidenceReviewConfig(),
) -> tuple[BrainstormIdeaEvidenceReview, ...]:
    """Screen brainstorm ideas against live source signals without requiring prior clones."""

    if config.max_reviewed_ideas < 1:
        msg = "max_reviewed_ideas must be at least 1"
        raise ValueError(msg)
    if config.max_queries_per_idea < 1:
        msg = "max_queries_per_idea must be at least 1"
        raise ValueError(msg)
    if config.max_results_per_source < 1:
        msg = "max_results_per_source must be at least 1"
        raise ValueError(msg)
    reviewed_ideas = ideas[: config.max_reviewed_ideas]
    if not reviewed_ideas:
        return ()

    queries_by_idea = {
        idea.idea_id: _review_queries(candidate, idea, limit=config.max_queries_per_idea)
        for idea in reviewed_ideas
    }
    all_queries = _ordered_unique(
        query for queries in queries_by_idea.values() for query in queries
    )
    literature_report = _review_literature_sources(
        vault_root=Path(vault_root),
        cache_root=Path(cache_root) / "literature",
        queries=all_queries,
        config=config,
    )
    ecosystem_report = _review_ecosystem_sources(
        vault_root=Path(vault_root),
        queries=all_queries,
        config=config,
    )
    return tuple(
        _review_one_idea(
            candidate=candidate,
            idea=idea,
            queries=queries_by_idea[idea.idea_id],
            literature_report=literature_report,
            ecosystem_report=ecosystem_report,
            config=config,
        )
        for idea in reviewed_ideas
    )


def _review_literature_sources(
    *,
    vault_root: Path,
    cache_root: Path,
    queries: tuple[str, ...],
    config: BrainstormEvidenceReviewConfig,
) -> LiteratureRefreshReport:
    return run_daily_literature_refresh(
        vault_root=vault_root,
        cache_root=cache_root,
        config=LiteratureRefreshConfig(
            max_queries=max(1, len(queries)),
            min_query_floor=0,
            max_results_per_source=config.max_results_per_source,
            seed_queries=queries,
        ),
        write_summary=False,
    )


def _review_ecosystem_sources(
    *,
    vault_root: Path,
    queries: tuple[str, ...],
    config: BrainstormEvidenceReviewConfig,
) -> InspirationRefreshReport:
    return run_inspiration_refresh(
        vault_root=vault_root,
        queries=queries,
        clients={
            "huggingface_datasets": HuggingFaceDatasetClient(),
            "github_repositories": GitHubRepositorySearchClient(),
            "hacker_news": HackerNewsSearchClient(),
        },
        config=InspirationRefreshConfig(
            max_queries=max(1, len(queries)),
            max_results_per_source=config.max_results_per_source,
        ),
        write_summary=False,
    )


def _review_one_idea(
    *,
    candidate: ResearchCandidate,
    idea: BrainstormIdea,
    queries: tuple[str, ...],
    literature_report: LiteratureRefreshReport,
    ecosystem_report: InspirationRefreshReport,
    config: BrainstormEvidenceReviewConfig,
) -> BrainstormIdeaEvidenceReview:
    literature_signals = _literature_signals_for_idea(
        idea=idea,
        queries=queries,
        papers=literature_report.papers,
        limit=config.max_results_per_source * 2,
    )
    ecosystem_signals = _ecosystem_signals_for_idea(
        idea=idea,
        queries=queries,
        items=ecosystem_report.items,
        limit=config.max_results_per_source * 3,
    )
    signals = tuple(
        sorted(
            [*literature_signals, *ecosystem_signals],
            key=lambda signal: (-signal.relevance_score, signal.source_type, signal.title.casefold()),
        )
    )
    fetches = _fetches_for_idea(
        queries=queries,
        literature_report=literature_report,
        ecosystem_report=ecosystem_report,
    )
    literature_count = sum(1 for signal in signals if signal.source_type == "literature")
    dataset_count = sum(1 for signal in signals if signal.source_type == "dataset_signal")
    code_count = sum(1 for signal in signals if signal.source_type == "code_signal")
    forum_count = sum(1 for signal in signals if signal.source_type == "forum_signal")
    duplicate_score = _duplicate_score(idea=idea, papers=literature_report.papers)
    duplicate_risk = _duplicate_risk(score=duplicate_score, config=config)
    capability = _idea_capability_profile(candidate=candidate, idea=idea)
    doability = _doability_from_capability(
        capability=capability,
        dataset_count=dataset_count,
        code_count=code_count,
    )
    verifiability = _verifiability_from_capability(
        capability=capability,
        total_signal_count=len(signals),
    )
    decision = _review_decision(
        duplicate_risk=duplicate_risk,
        doability=doability,
        verifiability=verifiability,
        total_signal_count=len(signals),
        dataset_count=dataset_count,
        code_count=code_count,
        config=config,
    )
    score_adjustment = _review_score_adjustment(
        duplicate_risk=duplicate_risk,
        doability=doability,
        verifiability=verifiability,
        total_signal_count=len(signals),
        dataset_count=dataset_count,
        code_count=code_count,
    )
    return BrainstormIdeaEvidenceReview(
        idea_id=idea.idea_id,
        queries=queries,
        signals=signals,
        literature_count=literature_count,
        dataset_count=dataset_count,
        code_count=code_count,
        forum_count=forum_count,
        duplicate_risk=duplicate_risk,
        verifiability=verifiability,
        doability=doability,
        decision=decision,
        score_adjustment=score_adjustment,
        reason=_review_reason(
            duplicate_score=duplicate_score,
            duplicate_risk=duplicate_risk,
            doability=doability,
            verifiability=verifiability,
            capability=capability,
            total_signal_count=len(signals),
            dataset_count=dataset_count,
            code_count=code_count,
            fetch_count=len(fetches),
        ),
        fetches=fetches,
    )


def _fetches_for_idea(
    *,
    queries: tuple[str, ...],
    literature_report: LiteratureRefreshReport,
    ecosystem_report: InspirationRefreshReport,
) -> tuple[BrainstormEvidenceFetch, ...]:
    query_keys = {query.casefold() for query in queries}
    fetches: list[BrainstormEvidenceFetch] = []
    for literature_fetch in literature_report.fetches:
        if literature_fetch.query.casefold() not in query_keys:
            continue
        fetches.append(
            BrainstormEvidenceFetch(
                source=literature_fetch.source,
                source_type="literature",
                query=literature_fetch.query,
                result_count=literature_fetch.paper_count,
                rate_limit_seconds=literature_fetch.rate_limit_seconds,
                cache_hit=literature_fetch.cache_hit,
                error=literature_fetch.error,
            )
        )
    for inspiration_fetch in ecosystem_report.fetches:
        if inspiration_fetch.query.casefold() not in query_keys:
            continue
        fetches.append(
            BrainstormEvidenceFetch(
                source=inspiration_fetch.source,
                source_type=inspiration_fetch.source_type,
                query=inspiration_fetch.query,
                result_count=inspiration_fetch.result_count,
                rate_limit_seconds=inspiration_fetch.rate_limit_seconds,
                error=inspiration_fetch.error,
            )
        )
    return tuple(fetches)


def _review_queries(
    candidate: ResearchCandidate,
    idea: BrainstormIdea,
    *,
    limit: int,
) -> tuple[str, ...]:
    metadata_terms = " ".join(str(value) for value in candidate.metadata.values())
    core = _compact_query(
        " ".join(
            [
                idea.title,
                idea.hypothesis,
                idea.novelty_angle,
                candidate.title,
                metadata_terms,
            ]
        )
    )
    queries = [
        _compact_query(idea.title),
        core,
        _compact_query(f"{core} dataset benchmark"),
        _compact_query(f"{core} code implementation"),
    ]
    return _ordered_unique(query for query in queries if len(_text_tokens(query)) >= 2)[:limit]


def _literature_signals_for_idea(
    *,
    idea: BrainstormIdea,
    queries: tuple[str, ...],
    papers: tuple[AcademicPaper, ...],
    limit: int,
) -> tuple[BrainstormEvidenceSignal, ...]:
    signals: list[BrainstormEvidenceSignal] = []
    for paper in papers:
        text = " ".join(filter(None, [paper.title, paper.abstract or "", paper.venue or ""]))
        relevance = _relevance_score(_idea_review_text(idea), text)
        if relevance < 0.08:
            continue
        signals.append(
            BrainstormEvidenceSignal(
                source=paper.source,
                source_type="literature",
                title=paper.title,
                url=paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else ""),
                query=_best_query_for_text(queries, paper.title),
                summary=_short_text(paper.abstract)
                or "Literature metadata signal; inspect the paper before citing claims.",
                relevance_score=relevance,
            )
        )
    return tuple(
        sorted(signals, key=lambda signal: (-signal.relevance_score, signal.title.casefold()))[:limit]
    )


def _ecosystem_signals_for_idea(
    *,
    idea: BrainstormIdea,
    queries: tuple[str, ...],
    items: tuple[InspirationItem, ...],
    limit: int,
) -> tuple[BrainstormEvidenceSignal, ...]:
    query_keys = {query.casefold() for query in queries}
    signals: list[BrainstormEvidenceSignal] = []
    for item in items:
        direct_query_match = item.query.casefold() in query_keys
        relevance = _relevance_score(_idea_review_text(idea), f"{item.title} {item.summary}")
        if not direct_query_match and relevance < 0.06:
            continue
        signals.append(
            BrainstormEvidenceSignal(
                source=item.source,
                source_type=item.source_type,
                title=item.title,
                url=item.url,
                query=item.query,
                summary=item.summary,
                relevance_score=max(relevance, 0.05 if direct_query_match else 0.0),
            )
        )
    return tuple(
        sorted(signals, key=lambda signal: (-signal.relevance_score, signal.source, signal.title))[
            :limit
        ]
    )


def _review_adjusted_selection_score(
    idea: BrainstormIdea,
    review: BrainstormIdeaEvidenceReview | None,
) -> float:
    if review is None:
        return idea.selection_score
    return round(_clamp(idea.selection_score + review.score_adjustment, 0.0, 1.0), 3)


def _duplicate_score(*, idea: BrainstormIdea, papers: tuple[AcademicPaper, ...]) -> float:
    if not papers:
        return 0.0
    idea_text = _idea_review_text(idea)
    scores = []
    for paper in papers:
        title_similarity = _sequence_similarity(idea.title, paper.title)
        title_overlap = _token_overlap(idea.title, paper.title)
        abstract_overlap = _token_overlap(idea_text, paper.abstract or "")
        scores.append(max(title_similarity, 0.75 * title_overlap + 0.25 * abstract_overlap))
    return round(max(scores), 3)


def _duplicate_risk(*, score: float, config: BrainstormEvidenceReviewConfig) -> str:
    if score >= config.high_duplicate_overlap:
        return "high"
    if score >= config.medium_duplicate_overlap:
        return "medium"
    return "low"


def _idea_capability_profile(
    *,
    candidate: ResearchCandidate,
    idea: BrainstormIdea,
) -> dict[str, bool]:
    text = _idea_review_text(idea, candidate=candidate)
    metadata_text = " ".join(str(value) for value in candidate.metadata.values()).casefold()
    combined = f"{text} {metadata_text}"
    return {
        "data": _contains_any(
            combined,
            (
                "data",
                "dataset",
                "benchmark",
                "corpus",
                "uci",
                "huggingface",
                "source",
                "logs",
                "records",
            ),
        ),
        "baseline": _contains_any(
            combined,
            ("baseline", "control", "compare", "comparison", "ablation", "rerun"),
        ),
        "metric": _contains_any(
            combined,
            (
                "metric",
                "accuracy",
                "f1",
                "auc",
                "precision",
                "recall",
                "latency",
                "cost",
                "score",
                "delta",
                "error",
            ),
        ),
        "falsification": _contains_any(
            combined,
            ("falsify", "falsification", "fail if", "if no", "does not", "negative", "reject"),
        ),
    }


def _doability_from_capability(
    *,
    capability: Mapping[str, bool],
    dataset_count: int,
    code_count: int,
) -> str:
    required_hits = sum(1 for key in ("data", "baseline", "metric", "falsification") if capability[key])
    if all(capability[key] for key in ("data", "baseline", "metric", "falsification")):
        return "strong"
    if required_hits >= 3 and (dataset_count or code_count):
        return "strong"
    if required_hits >= 3:
        return "moderate"
    if required_hits >= 2 and capability["metric"]:
        return "moderate"
    return "blocked"


def _verifiability_from_capability(
    *,
    capability: Mapping[str, bool],
    total_signal_count: int,
) -> str:
    if capability["data"] and capability["metric"] and capability["falsification"]:
        return "strong"
    if capability["baseline"] and capability["metric"]:
        return "moderate"
    if total_signal_count > 0 and capability["metric"]:
        return "moderate"
    return "weak"


def _review_decision(
    *,
    duplicate_risk: str,
    doability: str,
    verifiability: str,
    total_signal_count: int,
    dataset_count: int,
    code_count: int,
    config: BrainstormEvidenceReviewConfig,
) -> str:
    if duplicate_risk == "high" or doability == "blocked":
        return "defer"
    if duplicate_risk == "medium" or verifiability == "weak":
        return "revise"
    if total_signal_count < config.min_total_evidence:
        return "revise"
    if config.require_dataset_or_code_for_promote and not (dataset_count or code_count):
        return "revise"
    return "promote"


def _review_score_adjustment(
    *,
    duplicate_risk: str,
    doability: str,
    verifiability: str,
    total_signal_count: int,
    dataset_count: int,
    code_count: int,
) -> float:
    duplicate_delta = {"low": 0.06, "medium": -0.16, "high": -0.48}[duplicate_risk]
    doability_delta = {"strong": 0.14, "moderate": 0.04, "blocked": -0.34}[doability]
    verifiability_delta = {"strong": 0.10, "moderate": 0.03, "weak": -0.12}[verifiability]
    source_delta = min(total_signal_count, 4) * 0.015 + min(dataset_count + code_count, 2) * 0.025
    return round(duplicate_delta + doability_delta + verifiability_delta + source_delta, 3)


def _review_reason(
    *,
    duplicate_score: float,
    duplicate_risk: str,
    doability: str,
    verifiability: str,
    capability: Mapping[str, bool],
    total_signal_count: int,
    dataset_count: int,
    code_count: int,
    fetch_count: int,
) -> str:
    capability_text = ", ".join(key for key, value in capability.items() if value) or "none"
    return (
        f"Duplicate risk is {duplicate_risk} from literature similarity score "
        f"{duplicate_score:.3f}; doability is {doability} from self-contained plan checks "
        f"({capability_text}); verifiability is {verifiability}. Retrieved {total_signal_count} "
        f"screening signals from {fetch_count} source fetches, including {dataset_count} "
        f"dataset and {code_count} code signals. "
        "Absence of a close prior-work match is treated as novelty potential, not a feasibility failure."
    )


def _synthesize_brainstorm(
    *,
    ideas: tuple[BrainstormIdea, ...],
    selected: tuple[BrainstormIdea, ...],
    evidence_reviews: tuple[BrainstormIdeaEvidenceReview, ...] = (),
) -> str:
    if not ideas:
        return "No brainstorm ideas were parsed; keep the inspiration search result as input only."
    selected_titles = "; ".join(idea.title for idea in selected) or "none selected"
    review_text = (
        f" The evidence reviewer screened {len(evidence_reviews)} ideas against live "
        "literature, dataset, code, and community signals."
        if evidence_reviews
        else ""
    )
    return (
        f"Recorded {len(ideas)} temporary-miniagent ideas and selected {len(selected)} "
        f"for research-plan consideration: {selected_titles}. Selection favors high "
        "creativity, feasible first experiments, explicit inspiration refs, and a documented "
        f"selection argument.{review_text} These ideas "
        "remain hypotheses until literature, similarity, experiment, and reproduction evidence support them."
    )


def _write_brainstorm_report(
    *,
    report: BrainstormReport,
    candidate: ResearchCandidate,
    inspiration_report: InspirationRefreshReport,
    vault_root: Path,
    output_dir: Path,
    write_summary: bool,
) -> BrainstormReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "brainstorm-ideas.json"
    prompt_set_path = _write_prompt_set(vault_root, report.prompts)
    summary_path: Path | None = None
    updated = BrainstormReport(
        candidate_id=report.candidate_id,
        status=report.status,
        prompts=report.prompts,
        runs=report.runs,
        ideas=report.ideas,
        selected_ideas=report.selected_ideas,
        synthesis=report.synthesis,
        evidence_reviews=report.evidence_reviews,
        artifact_path=artifact_path,
        prompt_set_path=prompt_set_path,
        summary_path=None,
    )
    artifact_path.write_text(
        json.dumps(updated.to_json_dict(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    if write_summary:
        summary_path = _write_brainstorm_summary(
            vault_root,
            candidate=candidate,
            inspiration_report=inspiration_report,
            report=updated,
        )
    updated = BrainstormReport(
        candidate_id=updated.candidate_id,
        status=updated.status,
        prompts=updated.prompts,
        runs=updated.runs,
        ideas=updated.ideas,
        selected_ideas=updated.selected_ideas,
        synthesis=updated.synthesis,
        evidence_reviews=updated.evidence_reviews,
        artifact_path=artifact_path,
        prompt_set_path=prompt_set_path,
        summary_path=summary_path,
    )
    artifact_path.write_text(
        json.dumps(updated.to_json_dict(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return updated


def _write_prompt_set(root: Path, prompts: tuple[BrainstormMiniAgentPrompt, ...]) -> Path:
    body_lines = [
        "# Brainstorm Miniagent Prompt Set",
        "",
        "These prompts create temporary high-divergence miniagents. They are not persistent Agent profiles.",
        "Each run must record raw ideas first, then select feasible creative ideas with evidence refs.",
        "",
    ]
    for prompt in prompts:
        body_lines.extend(
            [
                f"## {prompt.agent_id}",
                "",
                f"- Role: {prompt.role}",
                f"- Perspective: {prompt.perspective}",
                f"- Temperature offset: `{prompt.temperature_offset}`",
                "",
                prompt.prompt_template,
                "",
            ]
        )
    entry = KnowledgeEntry(
        entry_id="brainstorm_miniagent_prompt_set",
        entry_type=KnowledgeEntryType.STRATEGY_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title="Brainstorm Miniagent Prompt Set",
        tags=["brainstorm", "miniagent", "prompt-set", "temporary-agent"],
        keywords=[prompt.agent_id for prompt in prompts],
        source_refs=[],
        body="\n".join(body_lines).rstrip() + "\n",
    )
    return MarkdownKnowledgeStore(root).write_entry(
        Path("strategy_library") / "prompts" / "brainstorm-miniagents.md",
        entry,
    )


def _write_brainstorm_summary(
    root: Path,
    *,
    candidate: ResearchCandidate,
    inspiration_report: InspirationRefreshReport,
    report: BrainstormReport,
) -> Path:
    timestamp = datetime.now(timezone.utc)
    date_id = timestamp.strftime("%Y%m%d")
    entry = KnowledgeEntry(
        entry_id=f"brainstorm_{_slug(candidate.id)}_{date_id}",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Brainstorm ideas for {candidate.title}",
        tags=["brainstorm", "temporary-miniagent", "inspiration", "research-ideas", "evidence-review"],
        keywords=[candidate.title, *inspiration_report.queries],
        source_refs=[
            *[item.url for item in inspiration_report.items],
            *[signal.url for review in report.evidence_reviews for signal in review.signals],
        ],
        body=_brainstorm_summary_body(
            candidate=candidate,
            inspiration_report=inspiration_report,
            report=report,
        ),
    )
    return MarkdownKnowledgeStore(root).write_entry(
        Path("exploration")
        / "brainstorm"
        / f"brainstorm_{_slug(candidate.id)}_{date_id}.md",
        entry,
    )


def _brainstorm_summary_body(
    *,
    candidate: ResearchCandidate,
    inspiration_report: InspirationRefreshReport,
    report: BrainstormReport,
) -> str:
    lines = [
        f"# Brainstorm Ideas for {candidate.title}",
        "",
        "Temporary miniagents generated high-temperature hypotheses from broad inspiration data.",
        "These ideas are not evidence of novelty, results, or publication readiness.",
        "",
        f"- Candidate: `{candidate.id}`",
        f"- Status: `{report.status}`",
        f"- Prompt set: `{report.prompt_set_path}`",
        f"- JSON artifact: `{report.artifact_path}`",
        "",
        "## Inspiration Inputs",
        "",
    ]
    for item in inspiration_report.items:
        lines.append(f"- [{item.title}]({item.url}) - `{item.source_type}` `{item.source}`")
    if not inspiration_report.items:
        lines.append("- No inspiration items were available; ideas must be treated as weakly grounded.")
    lines.extend(["", "## Evidence Reviewer", ""])
    if report.evidence_reviews:
        lines.append(
            "Second-stage reviewer results use live retrieval metadata to down-rank duplicate, "
            "unverifiable, or hard-to-execute ideas. These records are screening evidence, not results."
        )
        lines.append("")
        for review in report.evidence_reviews:
            lines.append(
                f"- `{review.idea_id}` decision `{review.decision}`; duplicate risk "
                f"`{review.duplicate_risk}`; verifiability `{review.verifiability}`; "
                f"doability `{review.doability}`; score adjustment `{review.score_adjustment:+.3f}`."
            )
            lines.append(f"  - Reason: {review.reason}")
            for fetch in review.fetches:
                error = f", error `{fetch.error}`" if fetch.error else ""
                cache = "" if fetch.cache_hit is None else f", cache_hit `{fetch.cache_hit}`"
                lines.append(
                    f"  - Fetch `{fetch.source}` `{fetch.source_type}` query `{fetch.query}` -> "
                    f"`{fetch.result_count}` results{cache}{error}."
                )
            for signal in review.signals[:5]:
                lines.append(
                    f"  - [{signal.title}]({signal.url}) - `{signal.source_type}` "
                    f"`{signal.source}`, relevance `{signal.relevance_score:.3f}`, "
                    f"query `{signal.query}`."
                )
    else:
        lines.append("- Evidence reviewer was not enabled for this brainstorm run.")
    lines.extend(["", "## Selected Ideas", ""])
    for idea in report.selected_ideas:
        lines.extend(_idea_lines(idea))
    if not report.selected_ideas:
        lines.append("- No idea passed the deterministic feasibility/creativity selection.")
    lines.extend(["", "## Selection Argument", ""])
    for idea in report.selected_ideas:
        lines.append(f"- `{idea.idea_id}`: {idea.selection_reason}")
    if not report.selected_ideas:
        lines.append("- No selected idea has a screening argument.")
    deferred = [idea for idea in report.ideas if not idea.selected]
    lines.extend(["", "## Deferred Ideas", ""])
    for idea in deferred:
        lines.append(f"- `{idea.idea_id}`: {idea.selection_reason}")
    if not deferred:
        lines.append("- No deferred idea in this run.")
    lines.extend(["", "## All Recorded Ideas", ""])
    for idea in report.ideas:
        lines.extend(_idea_lines(idea))
    lines.extend(["", "## Synthesis", "", report.synthesis])
    return "\n".join(lines).rstrip() + "\n"


def _idea_lines(idea: BrainstormIdea) -> list[str]:
    refs = ", ".join(f"`{ref}`" for ref in idea.inspiration_refs) or "`none`"
    return [
        f"### {idea.title}",
        "",
        f"- Idea ID: `{idea.idea_id}`; miniagent: `{idea.agent_id}`; selected: `{idea.selected}`",
        f"- Scores: creativity `{idea.creativity_score:.2f}`, feasibility `{idea.feasibility_score:.2f}`, "
        f"evidence binding `{idea.evidence_binding_score:.2f}`, selection `{idea.selection_score:.3f}`",
        f"- Inspiration refs: {refs}",
        f"- Screening: {idea.selection_reason}",
        f"- Hypothesis: {idea.hypothesis}",
        f"- Novelty angle: {idea.novelty_angle}",
        f"- Experiment sketch: {idea.experiment_sketch}",
        f"- Risks: {'; '.join(idea.risks)}",
        "",
    ]


def _inspiration_item_refs(items: tuple[InspirationItem, ...]) -> dict[str, InspirationItem]:
    return {f"inspiration_item_{index}": item for index, item in enumerate(items, start=1)}


def _evidence_binding_score(refs: tuple[str, ...], known_refs: set[str]) -> float:
    if not known_refs:
        return 0.25
    if not refs:
        return 0.0
    known_count = sum(1 for ref in refs if ref in known_refs)
    return round(known_count / len(refs), 3)


def _screening_reason(
    idea: BrainstormIdea,
    *,
    selected: bool,
    selection_count: int,
    review: BrainstormIdeaEvidenceReview | None = None,
) -> str:
    strengths: list[str] = []
    caveats: list[str] = []
    if idea.creativity_score >= 0.75:
        strengths.append("high creative divergence")
    elif idea.creativity_score < 0.45:
        caveats.append("weak creative divergence")
    if idea.feasibility_score >= 0.70:
        strengths.append("feasible first experiment")
    elif idea.feasibility_score < 0.50:
        caveats.append("feasibility needs repair")
    if idea.evidence_binding_score >= 0.75:
        strengths.append("explicit inspiration binding")
    elif idea.evidence_binding_score < 0.50:
        caveats.append("weak or missing inspiration refs")
    if review is not None:
        if review.decision == "promote":
            strengths.append("evidence reviewer promoted")
        elif review.decision == "revise":
            caveats.append("evidence reviewer requested revision")
        else:
            caveats.append("evidence reviewer deferred")
    action = "Selected" if selected else "Deferred"
    basis = ", ".join(strengths) if strengths else "balanced but not dominant scores"
    risk_text = "; ".join(idea.risks[:2]) if idea.risks else "risk analysis pending"
    review_text = ""
    if review is not None:
        review_text = (
            f" Evidence review: decision `{review.decision}`, duplicate risk "
            f"`{review.duplicate_risk}`, doability `{review.doability}`, "
            f"verifiability `{review.verifiability}`; {review.reason}"
        )
    if selected:
        return (
            f"{action} within top {selection_count} by score {idea.selection_score:.3f}: "
            f"{basis}. First falsification path: {idea.experiment_sketch[:220]}. "
            f"Risks to check: {risk_text}.{review_text}"
        )
    caveat_text = ", ".join(caveats) if caveats else "ranked below selected ideas"
    return (
        f"{action} for now with score {idea.selection_score:.3f}: {caveat_text}. "
        f"Keep as future inspiration if new evidence or a cheaper dataset path appears. "
        f"Risks to check: {risk_text}.{review_text}"
    )


def _idea_review_text(idea: BrainstormIdea, *, candidate: ResearchCandidate | None = None) -> str:
    parts = [
        idea.title,
        idea.hypothesis,
        idea.rationale,
        idea.novelty_angle,
        idea.experiment_sketch,
        " ".join(idea.risks),
    ]
    if candidate is not None:
        parts.extend(
            [
                candidate.title,
                candidate.description,
                candidate.research_gap,
                " ".join(str(value) for value in candidate.metadata.values()),
            ]
        )
    return " ".join(part for part in parts if part)


def _compact_query(value: str, *, max_terms: int = 9) -> str:
    tokens = _text_tokens(value)
    return " ".join(tokens[:max_terms])


def _text_tokens(value: str) -> list[str]:
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", value.casefold())
    stopwords = {
        "and",
        "are",
        "can",
        "for",
        "from",
        "into",
        "the",
        "this",
        "that",
        "with",
        "using",
    }
    return [
        token
        for token in normalized.split()
        if len(token) > 2 and token not in stopwords
    ]


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return tuple(result)


def _best_query_for_text(queries: tuple[str, ...], text: str) -> str:
    if not queries:
        return ""
    return max(queries, key=lambda query: _token_overlap(query, text))


def _relevance_score(left: str, right: str) -> float:
    token_score = _token_overlap(left, right)
    sequence_score = _sequence_similarity(left[:280], right[:280])
    return round(max(token_score, sequence_score * 0.35), 3)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(_text_tokens(left))
    right_tokens = set(_text_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    denominator = min(len(left_tokens), len(right_tokens))
    return round(len(left_tokens & right_tokens) / denominator, 3)


def _sequence_similarity(left: str, right: str) -> float:
    left_clean = " ".join(_text_tokens(left))
    right_clean = " ".join(_text_tokens(right))
    if not left_clean or not right_clean:
        return 0.0
    return round(SequenceMatcher(None, left_clean, right_clean).ratio(), 3)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _number_score(value: object, *, default: float) -> float:
    if isinstance(value, int | float):
        return round(_clamp(float(value), 0.0, 1.0), 3)
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _short_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:800]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "candidate"
