"""Strategy evolution report generation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StrategyEvolutionReportContext(BaseModel):
    """Structured inputs for one strategy evolution report."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1)
    strategy_card_refs: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    evaluation_summary: str = Field(min_length=1)
    reward_delta: float
    risks: tuple[str, ...] = ()
    release_history: tuple[str, ...] = Field(min_length=1)
    rollback_target: str | None = None
    final_decision: str = Field(min_length=1)


class StrategyEvolutionReportArtifact(BaseModel):
    """Generated strategy evolution report artifact."""

    model_config = ConfigDict(extra="forbid")

    context: StrategyEvolutionReportContext
    markdown: str
    markdown_path: str | None = None
    json_path: str | None = None


def generate_strategy_evolution_report(
    context: StrategyEvolutionReportContext,
    *,
    output_dir: Path | str | None = None,
) -> StrategyEvolutionReportArtifact:
    """Generate a Markdown report for a strategy change."""

    markdown = _render_markdown(context)
    if output_dir is None:
        return StrategyEvolutionReportArtifact(context=context, markdown=markdown)

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = target_dir / "strategy-evolution-report.md"
    json_path = target_dir / "strategy-evolution-report.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "context": context.model_dump(mode="json"),
                "markdown_path": markdown_path.as_posix(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return StrategyEvolutionReportArtifact(
        context=context,
        markdown=markdown,
        markdown_path=markdown_path.as_posix(),
        json_path=json_path.as_posix(),
    )


def _render_markdown(context: StrategyEvolutionReportContext) -> str:
    lines = [
        f"# Strategy Evolution Report: {context.strategy_id}",
        "",
        "## Strategy Cards",
        "",
        *_bullet_links(context.strategy_card_refs),
        "",
        "## Reason",
        "",
        context.reason,
        "",
        "## Evidence",
        "",
        *_bullet_links(context.evidence_refs),
        "",
        "## Evaluation",
        "",
        context.evaluation_summary,
        "",
        "## Reward Delta",
        "",
        f"- Reward delta: `{context.reward_delta:+.6f}`",
        "",
        "## Risks",
        "",
        *_bullet_text(context.risks),
        "",
        "## Release History",
        "",
        *_bullet_text(context.release_history),
        "",
        "## Rollback Target",
        "",
        _rollback_target_line(context.rollback_target),
        "",
        "## Final Decision",
        "",
        context.final_decision,
    ]
    return "\n".join(lines).rstrip() + "\n"


def _bullet_links(refs: tuple[str, ...]) -> list[str]:
    return [f"- {_wiki_link(ref)}" for ref in refs]


def _bullet_text(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _rollback_target_line(rollback_target: str | None) -> str:
    if rollback_target is None:
        return "- None"
    return f"- {_wiki_link(rollback_target)}"


def _wiki_link(ref: str) -> str:
    return f"[[{ref.removesuffix('.md')}]]"
