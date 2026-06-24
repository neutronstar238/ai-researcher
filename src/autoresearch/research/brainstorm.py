"""Temporary miniagent brainstorming over broad inspiration signals."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.inspiration import InspirationItem, InspirationRefreshReport
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
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
            "synthesis": self.synthesis,
            "artifact_path": self.artifact_path.as_posix() if self.artifact_path else None,
            "prompt_set_path": self.prompt_set_path.as_posix() if self.prompt_set_path else None,
            "summary_path": self.summary_path.as_posix() if self.summary_path else None,
            "evidence_policy": (
                "Brainstorm ideas are hypotheses only. Inspiration refs are context signals, "
                "not proof of results, novelty, or publishability."
            ),
        }


BrainstormCompletionRunner = Callable[
    [BrainstormMiniAgentPrompt, list[dict[str, str]], float],
    Mapping[str, object],
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
    completion_runner: BrainstormCompletionRunner | None = None,
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
    selected = _select_ideas(ideas, min_selected=config.min_selected_ideas)
    synthesis = _synthesize_brainstorm(ideas=tuple(ideas), selected=selected)
    status = "selected" if selected else ("ideas_recorded" if ideas else "failed")
    report = BrainstormReport(
        candidate_id=candidate.id,
        status=status,
        prompts=prompts,
        runs=tuple(runs),
        ideas=tuple(ideas),
        selected_ideas=selected,
        synthesis=synthesis,
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
            )
        )
    return ideas


def _select_ideas(
    ideas: list[BrainstormIdea],
    *,
    min_selected: int,
) -> tuple[BrainstormIdea, ...]:
    if not ideas:
        return ()
    sorted_ideas = sorted(
        ideas,
        key=lambda idea: (
            -idea.selection_score,
            -idea.creativity_score,
            -idea.feasibility_score,
            idea.idea_id,
        ),
    )
    selection_count = min(max(min_selected, 1), len(sorted_ideas))
    selected_ids = {idea.idea_id for idea in sorted_ideas[:selection_count]}
    calibrated = [
        BrainstormIdea(
            idea_id=idea.idea_id,
            agent_id=idea.agent_id,
            title=idea.title,
            hypothesis=idea.hypothesis,
            rationale=idea.rationale,
            novelty_angle=idea.novelty_angle,
            experiment_sketch=idea.experiment_sketch,
            inspiration_refs=idea.inspiration_refs,
            risks=idea.risks,
            creativity_score=idea.creativity_score,
            feasibility_score=idea.feasibility_score,
            evidence_binding_score=idea.evidence_binding_score,
            selection_score=idea.selection_score,
            selected=idea.idea_id in selected_ids,
        )
        for idea in ideas
    ]
    ideas[:] = calibrated
    return tuple(idea for idea in calibrated if idea.selected)


def _synthesize_brainstorm(
    *,
    ideas: tuple[BrainstormIdea, ...],
    selected: tuple[BrainstormIdea, ...],
) -> str:
    if not ideas:
        return "No brainstorm ideas were parsed; keep the inspiration search result as input only."
    selected_titles = "; ".join(idea.title for idea in selected) or "none selected"
    return (
        f"Recorded {len(ideas)} temporary-miniagent ideas and selected {len(selected)} "
        f"for research-plan consideration: {selected_titles}. Selection favors high "
        "creativity, feasible first experiments, and explicit inspiration refs. These ideas "
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
        tags=["brainstorm", "temporary-miniagent", "inspiration", "research-ideas"],
        keywords=[candidate.title, *inspiration_report.queries],
        source_refs=[item.url for item in inspiration_report.items],
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
    lines.extend(["", "## Selected Ideas", ""])
    for idea in report.selected_ideas:
        lines.extend(_idea_lines(idea))
    if not report.selected_ideas:
        lines.append("- No idea passed the deterministic feasibility/creativity selection.")
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
