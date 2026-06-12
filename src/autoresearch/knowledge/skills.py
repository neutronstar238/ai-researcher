"""Extract reusable successful patterns into Obsidian skill cards."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from autoresearch.knowledge.entries import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)

DEFAULT_MIN_SKILL_EXAMPLES = 2
SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SuccessfulPatternExample:
    """One successful project experience that can support a reusable skill."""

    project_id: str
    experience_ref: str
    summary: str
    trigger_conditions: tuple[str, ...]
    actions: tuple[str, ...]
    success_metrics: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    related_task_ids: tuple[str, ...] = ()
    related_run_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedSkillCard:
    """Persisted skill card details returned after extraction."""

    skill_id: str
    path: Path
    entry: KnowledgeEntry
    example_refs: tuple[str, ...]
    failure_pattern_refs: tuple[str, ...]


def extract_reusable_skill_card(
    *,
    vault_root: Path | str,
    name: str,
    examples: tuple[SuccessfulPatternExample, ...],
    skill_id: str | None = None,
    failure_pattern_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
    min_examples: int = DEFAULT_MIN_SKILL_EXAMPLES,
) -> ExtractedSkillCard:
    """Create or update an Obsidian skill card from repeated successful examples."""

    if min_examples < DEFAULT_MIN_SKILL_EXAMPLES:
        msg = "min_examples must be at least 2 for reusable skill extraction"
        raise ValueError(msg)
    if len(examples) < min_examples:
        msg = f"at least {min_examples} successful examples are required"
        raise ValueError(msg)

    skill_name = _required_text(name, "name")
    resolved_skill_id = skill_id or f"skill_{_slug(skill_name)}"
    _validate_skill_id(resolved_skill_id)
    for example in examples:
        _validate_example(example)

    trigger_conditions = _ordered_unique(
        condition for example in examples for condition in example.trigger_conditions
    )
    actions = _ordered_unique(action for example in examples for action in example.actions)
    success_metrics = _ordered_unique(
        metric for example in examples for metric in example.success_metrics
    )
    example_refs = _ordered_unique(example.experience_ref for example in examples)
    source_refs = _ordered_unique(
        [
            *example_refs,
            *failure_pattern_refs,
            *(ref for example in examples for ref in example.evidence_refs),
        ]
    )
    related_task_ids = _ordered_unique(
        task_id for example in examples for task_id in example.related_task_ids
    )
    related_run_ids = _ordered_unique(
        run_id for example in examples for run_id in example.related_run_ids
    )
    all_tags = _ordered_unique(
        [
            "skill",
            "skill-card",
            "reusable",
            *tags,
            *(tag for example in examples for tag in example.tags),
        ]
    )
    all_keywords = _skill_keywords(
        skill_id=resolved_skill_id,
        name=skill_name,
        trigger_conditions=trigger_conditions,
        actions=actions,
        success_metrics=success_metrics,
        examples=examples,
        failure_pattern_refs=failure_pattern_refs,
        extra_keywords=keywords,
    )

    entry = KnowledgeEntry(
        entry_id=resolved_skill_id,
        entry_type=KnowledgeEntryType.SKILL_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title=skill_name,
        tags=list(all_tags),
        keywords=list(all_keywords),
        source_refs=list(source_refs),
        related_task_ids=list(related_task_ids),
        related_run_ids=list(related_run_ids),
        body=_skill_body(
            skill_id=resolved_skill_id,
            name=skill_name,
            trigger_conditions=trigger_conditions,
            actions=actions,
            success_metrics=success_metrics,
            examples=examples,
            failure_pattern_refs=failure_pattern_refs,
        ),
    )
    relative_path = Path("exploration") / "skills" / f"{resolved_skill_id}.md"
    path = MarkdownKnowledgeStore(vault_root).write_entry(relative_path, entry)
    stored_entry = MarkdownKnowledgeStore(vault_root).read_entry(relative_path)
    return ExtractedSkillCard(
        skill_id=resolved_skill_id,
        path=path,
        entry=stored_entry,
        example_refs=example_refs,
        failure_pattern_refs=failure_pattern_refs,
    )


def _validate_example(example: SuccessfulPatternExample) -> None:
    _required_text(example.project_id, "project_id")
    _required_text(example.experience_ref, "experience_ref")
    _required_text(example.summary, "summary")
    if not _ordered_unique(example.trigger_conditions):
        msg = "each successful example must include at least one trigger condition"
        raise ValueError(msg)
    if not _ordered_unique(example.actions):
        msg = "each successful example must include at least one action"
        raise ValueError(msg)
    if not _ordered_unique(example.success_metrics):
        msg = "each successful example must include at least one success metric"
        raise ValueError(msg)


def _validate_skill_id(skill_id: str) -> None:
    if not SKILL_ID_PATTERN.fullmatch(skill_id):
        msg = "skill_id must be lowercase ASCII and path-safe"
        raise ValueError(msg)


def _required_text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} must be non-empty"
        raise ValueError(msg)
    return text


def _skill_body(
    *,
    skill_id: str,
    name: str,
    trigger_conditions: tuple[str, ...],
    actions: tuple[str, ...],
    success_metrics: tuple[str, ...],
    examples: tuple[SuccessfulPatternExample, ...],
    failure_pattern_refs: tuple[str, ...],
) -> str:
    lines = [
        f"# {name}",
        "",
        f"- Skill ID: `{skill_id}`",
        f"- Example count: `{len(examples)}`",
        "- Status: `extracted`",
        "",
        "## Trigger Conditions",
        "",
        *_bullet_lines(trigger_conditions),
        "",
        "## Actions",
        "",
        *_bullet_lines(actions),
        "",
        "## Success Metrics",
        "",
        *_bullet_lines(success_metrics),
        "",
        "## Project Experience Examples",
        "",
    ]
    for example in examples:
        lines.extend(
            [
                f"- [[{_wiki_target(example.experience_ref)}]] (`{example.project_id}`)",
                f"  - Summary: {example.summary}",
                f"  - Tasks: {_inline_items(example.related_task_ids)}",
                f"  - Runs: {_inline_items(example.related_run_ids)}",
                f"  - Evidence: {_wiki_items(example.evidence_refs)}",
            ]
        )
    lines.extend(
        [
            "",
            "## Failure Pattern Links",
            "",
            *_wiki_bullet_lines(failure_pattern_refs),
            "",
            "## Reuse Notes",
            "",
            "- Apply only when the trigger conditions match the current task context.",
            "- Verify the success metrics on the new project before treating this skill as promoted.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _skill_keywords(
    *,
    skill_id: str,
    name: str,
    trigger_conditions: tuple[str, ...],
    actions: tuple[str, ...],
    success_metrics: tuple[str, ...],
    examples: tuple[SuccessfulPatternExample, ...],
    failure_pattern_refs: tuple[str, ...],
    extra_keywords: tuple[str, ...],
) -> tuple[str, ...]:
    raw_values = [
        "skill",
        "skill-card",
        "reusable",
        skill_id,
        name,
        *trigger_conditions,
        *actions,
        *success_metrics,
        *failure_pattern_refs,
        *extra_keywords,
        *(example.project_id for example in examples),
        *(tag for example in examples for tag in example.tags),
    ]
    tokens = [token for value in raw_values for token in TOKEN_PATTERN.findall(value.casefold())]
    return _ordered_unique([*raw_values, *tokens])


def _ordered_unique(values: Iterable[object]) -> tuple[str, ...]:
    result: dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text:
            result.setdefault(text, None)
    return tuple(result)


def _slug(text: str) -> str:
    tokens = TOKEN_PATTERN.findall(text.casefold())
    return "_".join(tokens) or "reusable_skill"


def _bullet_lines(items: tuple[str, ...]) -> list[str]:
    return [f"- {item}" for item in items] or ["- None"]


def _wiki_bullet_lines(items: tuple[str, ...]) -> list[str]:
    return [f"- [[{_wiki_target(item)}]]" for item in _ordered_unique(items)] or ["- None"]


def _wiki_items(items: tuple[str, ...]) -> str:
    unique_items = _ordered_unique(items)
    if not unique_items:
        return "`none`"
    return ", ".join(f"[[{_wiki_target(item)}]]" for item in unique_items)


def _inline_items(items: tuple[str, ...]) -> str:
    unique_items = _ordered_unique(items)
    if not unique_items:
        return "`none`"
    return ", ".join(f"`{item}`" for item in unique_items)


def _wiki_target(value: str) -> str:
    target = value.strip()
    if target.endswith(".md"):
        return target[:-3]
    return target
