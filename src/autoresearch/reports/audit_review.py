"""Human-readable audit reviews for strategy promotion."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StrategyPromotionAuditReviewContext(BaseModel):
    """Compact maintainer review context before strategy promotion."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1)
    strategy_card_ref: str = Field(min_length=1)
    gate_summary: tuple[str, ...] = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    reward_summary: str = Field(min_length=1)
    risk_summary: str = Field(min_length=1)
    rollback_plan: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    maintainer_decision: str = "pending human approval"


class StrategyPromotionAuditReviewArtifact(BaseModel):
    """Generated promotion audit review artifact."""

    model_config = ConfigDict(extra="forbid")

    context: StrategyPromotionAuditReviewContext
    markdown: str
    review_ref: str
    markdown_path: str | None = None
    json_path: str | None = None


def generate_strategy_promotion_audit_review(
    context: StrategyPromotionAuditReviewContext,
    *,
    output_dir: Path | str | None = None,
) -> StrategyPromotionAuditReviewArtifact:
    """Generate a compact maintainer review before strategy promotion."""

    markdown = _render_markdown(context)
    if output_dir is None:
        return StrategyPromotionAuditReviewArtifact(
            context=context,
            markdown=markdown,
            review_ref=f"audit-review/{context.strategy_id}",
        )

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = target_dir / "strategy-promotion-audit-review.md"
    json_path = target_dir / "strategy-promotion-audit-review.json"
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
    return StrategyPromotionAuditReviewArtifact(
        context=context,
        markdown=markdown,
        review_ref=markdown_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        json_path=json_path.as_posix(),
    )


def _render_markdown(context: StrategyPromotionAuditReviewContext) -> str:
    lines = [
        f"# Strategy Promotion Audit Review: {context.strategy_id}",
        "",
        f"- Strategy card: {_wiki_link(context.strategy_card_ref)}",
        f"- Recommendation: {context.recommendation}",
        f"- Maintainer decision: {context.maintainer_decision}",
        "",
        "## Gate Summary",
        "",
        *_bullet_text(context.gate_summary),
        "",
        "## Evidence Summary",
        "",
        context.evidence_summary,
        "",
        "## Reward Summary",
        "",
        context.reward_summary,
        "",
        "## Risk Summary",
        "",
        context.risk_summary,
        "",
        "## Rollback Plan",
        "",
        context.rollback_plan,
    ]
    return "\n".join(lines).rstrip() + "\n"


def _bullet_text(items: tuple[str, ...]) -> list[str]:
    return [f"- {item}" for item in items]


def _wiki_link(ref: str) -> str:
    return f"[[{ref.removesuffix('.md')}]]"
