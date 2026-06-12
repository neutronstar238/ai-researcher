"""Extract reusable successful patterns into Obsidian skill cards."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from autoresearch.knowledge.entries import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    extract_wiki_links,
)

DEFAULT_MIN_SKILL_EXAMPLES = 2
SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_TOKENS = frozenset(
    {
        "and",
        "card",
        "for",
        "from",
        "into",
        "new",
        "project",
        "skill",
        "task",
        "the",
        "use",
        "with",
    }
)


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


@dataclass(frozen=True)
class SkillRetrievalQuery:
    """New task context used to retrieve relevant skill cards."""

    title: str
    description: str = ""
    metadata: Mapping[str, object] | None = None
    tags: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillMatch:
    """Ranked skill match for a new task context."""

    skill_id: str
    score: float
    reasons: tuple[str, ...]
    relative_path: str
    entry: KnowledgeEntry


@dataclass(frozen=True)
class _SkillEntryRow:
    relative_path: str
    entry: KnowledgeEntry
    links: tuple[str, ...]
    backlinks: tuple[str, ...]


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


def retrieve_relevant_skills(
    *,
    vault_root: Path | str,
    query: SkillRetrievalQuery,
    limit: int = 5,
    min_score: float = 1.0,
) -> list[SkillMatch]:
    """Retrieve skill cards that match a new task's metadata and Obsidian links."""

    if limit < 1:
        msg = "limit must be at least 1"
        raise ValueError(msg)
    if min_score < 0:
        msg = "min_score must be non-negative"
        raise ValueError(msg)

    _required_text(query.title, "query.title")
    query_values = _query_values(query)
    query_terms = _search_terms(query_values)
    query_tags = _normalized_values(query.tags)
    query_keywords = _normalized_values([*query.keywords, *_metadata_values(query.metadata)])
    query_links = _normalized_targets([*query.links, *_link_like_values(query.metadata)])

    matches: list[SkillMatch] = []
    for row in _skill_rows(Path(vault_root)):
        score, reasons = _score_skill(
            row=row,
            query_terms=query_terms,
            query_tags=query_tags,
            query_keywords=query_keywords,
            query_links=query_links,
        )
        if score >= min_score:
            matches.append(
                SkillMatch(
                    skill_id=row.entry.entry_id,
                    score=score,
                    reasons=reasons,
                    relative_path=row.relative_path,
                    entry=row.entry,
                )
            )

    return sorted(
        matches,
        key=lambda match: (-match.score, match.entry.title.casefold(), match.skill_id),
    )[:limit]


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


def _score_skill(
    *,
    row: _SkillEntryRow,
    query_terms: set[str],
    query_tags: set[str],
    query_keywords: set[str],
    query_links: set[str],
) -> tuple[float, tuple[str, ...]]:
    entry = row.entry
    reasons: list[str] = []
    score = 0.0

    structured_targets = _normalized_targets(
        [entry.entry_id, row.relative_path, row.relative_path.removesuffix(".md")]
    )
    if structured_targets & query_links or entry.entry_id.casefold() in query_keywords:
        score += 20.0
        reasons.append("matched skill id or direct skill wiki-link")

    entry_tags = _normalized_values(entry.tags)
    matched_tags = sorted(entry_tags & query_tags)
    if matched_tags:
        score += 5.0 * len(matched_tags)
        reasons.append(f"matched frontmatter tags: {', '.join(matched_tags)}")

    entry_keywords = _normalized_values(entry.keywords)
    matched_keywords = sorted(entry_keywords & query_keywords)
    if matched_keywords:
        score += 4.0 * len(matched_keywords)
        reasons.append(f"matched frontmatter keywords: {', '.join(matched_keywords)}")

    structured_terms = _search_terms(
        [
            entry.entry_id,
            entry.title,
            *entry.tags,
            *entry.keywords,
            *entry.source_refs,
            *entry.related_task_ids,
            *entry.related_run_ids,
        ]
    )
    matched_structured_terms = sorted(structured_terms & query_terms)
    if matched_structured_terms:
        score += min(8.0, 1.0 * len(matched_structured_terms))
        reasons.append(
            "matched structured metadata terms: "
            + ", ".join(matched_structured_terms[:8])
        )

    skill_links = _normalized_targets([*row.links, *entry.source_refs])
    matched_links = sorted(skill_links & query_links)
    if matched_links:
        score += 6.0 * len(matched_links)
        reasons.append(f"matched Obsidian links: {', '.join(matched_links)}")

    backlinks = _normalized_targets(row.backlinks)
    matched_backlinks = sorted(backlinks & query_links)
    if matched_backlinks:
        score += 6.0 * len(matched_backlinks)
        reasons.append(f"matched Obsidian backlinks: {', '.join(matched_backlinks)}")

    body_terms = _search_terms([entry.body])
    matched_body_terms = sorted(body_terms & query_terms)
    if matched_body_terms:
        score += min(5.0, 0.5 * len(matched_body_terms))
        reasons.append(f"matched body terms: {', '.join(matched_body_terms[:8])}")

    return score, tuple(reasons)


def _skill_rows(vault_root: Path) -> tuple[_SkillEntryRow, ...]:
    entries = _all_entries(vault_root)
    target_index: dict[str, str] = {}
    for relative_path, entry in entries:
        target_index[_normalize_target(entry.entry_id)] = relative_path
        target_index[_normalize_target(relative_path)] = relative_path
        target_index[_normalize_target(relative_path.removesuffix(".md"))] = relative_path

    backlinks: dict[str, set[str]] = {relative_path: set() for relative_path, _ in entries}
    for source_path, source_entry in entries:
        for link in extract_wiki_links(source_entry.body):
            target_path = target_index.get(_normalize_target(link))
            if target_path is not None and target_path != source_path:
                backlinks[target_path].add(source_entry.entry_id)
                backlinks[target_path].add(source_path)
                backlinks[target_path].add(source_path.removesuffix(".md"))

    rows: list[_SkillEntryRow] = []
    for relative_path, entry in entries:
        if entry.entry_type is not KnowledgeEntryType.SKILL_CARD:
            continue
        links = _ordered_unique([*entry.links, *extract_wiki_links(entry.body)])
        row_backlinks = _ordered_unique([*entry.backlinks, *backlinks[relative_path]])
        rows.append(
            _SkillEntryRow(
                relative_path=relative_path,
                entry=entry,
                links=links,
                backlinks=row_backlinks,
            )
        )
    return tuple(rows)


def _all_entries(vault_root: Path) -> tuple[tuple[str, KnowledgeEntry], ...]:
    if not vault_root.exists():
        return ()
    entries: list[tuple[str, KnowledgeEntry]] = []
    for path in sorted(vault_root.rglob("*.md")):
        relative_path = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        try:
            entry = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError):
            continue
        entries.append((relative_path.as_posix(), entry))
    return tuple(entries)


def _query_values(query: SkillRetrievalQuery) -> tuple[str, ...]:
    return _ordered_unique(
        [
            query.title,
            query.description,
            *query.tags,
            *query.keywords,
            *query.links,
            *_metadata_values(query.metadata),
        ]
    )


def _metadata_values(metadata: Mapping[str, object] | None) -> tuple[str, ...]:
    if metadata is None:
        return ()
    values: list[str] = []
    for key, value in metadata.items():
        values.append(key)
        values.extend(_flatten_metadata_value(value))
    return _ordered_unique(values)


def _flatten_metadata_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, item in value.items():
            values.append(str(key))
            values.extend(_flatten_metadata_value(item))
        return _ordered_unique(values)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        values = []
        for item in value:
            values.extend(_flatten_metadata_value(item))
        return _ordered_unique(values)
    return (str(value),)


def _link_like_values(metadata: Mapping[str, object] | None) -> tuple[str, ...]:
    if metadata is None:
        return ()
    links: list[str] = []
    for key, value in metadata.items():
        if "link" in key.casefold() or key.casefold().endswith("_ref"):
            links.extend(_flatten_metadata_value(value))
    return _ordered_unique(links)


def _search_terms(values: Iterable[object]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        text = str(value).strip().casefold()
        if text:
            terms.add(text)
        for token in TOKEN_PATTERN.findall(text):
            if token not in STOP_TOKENS and len(token) > 1:
                terms.add(token)
    return terms


def _normalized_values(values: Iterable[object]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _normalized_targets(values: Iterable[object]) -> set[str]:
    return {_normalize_target(str(value)) for value in values if str(value).strip()}


def _normalize_target(value: str) -> str:
    return _wiki_target(value).strip().casefold()


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
