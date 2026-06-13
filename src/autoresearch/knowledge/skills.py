"""Extract reusable successful patterns into Obsidian skill cards."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
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
class SkillEvolutionCandidate:
    """Bounded skill edit candidate awaiting shadow validation."""

    candidate_skill_id: str
    path: Path
    entry: KnowledgeEntry
    parent_skill_id: str
    parent_relative_path: str
    issue_refs: tuple[str, ...]
    failure_pattern_refs: tuple[str, ...]
    validation_checks: tuple[str, ...]
    rejected_edit_buffer_path: Path


@dataclass(frozen=True)
class SkillPolishCheck:
    """One deterministic skill-polish gate check."""

    check_id: str
    label: str
    passed: bool
    score: float
    max_score: float
    evidence: tuple[str, ...]
    missing: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "check_id": self.check_id,
            "label": self.label,
            "passed": self.passed,
            "score": self.score,
            "max_score": self.max_score,
            "evidence": list(self.evidence),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class SkillPolishReport:
    """Luban-inspired skill-polish audit report for a skill card."""

    skill_id: str
    relative_path: str
    min_score: float
    score: float
    max_score: float
    score_ratio: float
    passed: bool
    checks: tuple[SkillPolishCheck, ...]
    reference: str = "LearnPrompt/luban-skill methodology reference only"

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "skill_id": self.skill_id,
            "relative_path": self.relative_path,
            "min_score": self.min_score,
            "score": self.score,
            "max_score": self.max_score,
            "score_ratio": self.score_ratio,
            "passed": self.passed,
            "reference": self.reference,
            "checks": [check.to_json_dict() for check in self.checks],
        }

    def to_markdown(self) -> str:
        """Render the report as Obsidian-friendly Markdown."""

        status = "pass" if self.passed else "blocked"
        lines = [
            f"# Skill polish audit - {self.skill_id}",
            "",
            f"- Skill path: [[{self.relative_path.removesuffix('.md')}|{self.skill_id}]]",
            f"- Status: `{status}`",
            f"- Score: `{self.score:.1f}/{self.max_score:.1f}`",
            f"- Minimum ratio: `{self.min_score:.2f}`",
            f"- Score ratio: `{self.score_ratio:.2f}`",
            f"- Reference: `{self.reference}`",
            "",
            "## Checks",
            "",
        ]
        for check in self.checks:
            check_status = "pass" if check.passed else "fail"
            lines.extend(
                [
                    f"### {check.label}",
                    "",
                    f"- Status: `{check_status}`",
                    f"- Score: `{check.score:.1f}/{check.max_score:.1f}`",
                    f"- Evidence: {_inline_items(check.evidence)}",
                    f"- Missing: {_inline_items(check.missing)}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"


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


def create_skill_evolution_candidate(
    *,
    vault_root: Path | str,
    parent_skill_id: str,
    change_summary: str,
    issue_refs: tuple[str, ...],
    proposed_actions: tuple[str, ...],
    validation_checks: tuple[str, ...],
    failure_pattern_refs: tuple[str, ...] = (),
    candidate_skill_id: str | None = None,
) -> SkillEvolutionCandidate:
    """Create a SkillOpt-inspired bounded edit candidate without mutating the parent."""

    parent_id = _required_text(parent_skill_id, "parent_skill_id")
    _validate_skill_id(parent_id)
    summary = _required_text(change_summary, "change_summary")
    issues = _ordered_unique(issue_refs)
    failures = _ordered_unique(failure_pattern_refs)
    actions = _ordered_unique(proposed_actions)
    checks = _ordered_unique(validation_checks)
    if not issues and not failures:
        msg = "at least one issue_ref or failure_pattern_ref is required"
        raise ValueError(msg)
    if not actions:
        msg = "at least one proposed action is required"
        raise ValueError(msg)
    if not checks:
        msg = "at least one validation check is required"
        raise ValueError(msg)

    parent_relative_path, parent_entry = _find_skill_by_id(Path(vault_root), parent_id)
    resolved_candidate_id = candidate_skill_id or _candidate_skill_id(
        parent_id=parent_id,
        change_summary=summary,
        issue_refs=issues,
        failure_pattern_refs=failures,
        proposed_actions=actions,
    )
    _validate_skill_id(resolved_candidate_id)
    if resolved_candidate_id == parent_id:
        msg = "candidate_skill_id must differ from parent_skill_id"
        raise ValueError(msg)

    source_refs = _ordered_unique([parent_relative_path, *issues, *failures])
    keywords = _ordered_unique(
        [
            "skill-evolution",
            "skillopt-inspired",
            "bounded-edit",
            "shadow-evaluation",
            parent_id,
            resolved_candidate_id,
            summary,
            *actions,
            *checks,
            *issues,
            *failures,
        ]
    )
    entry = KnowledgeEntry(
        entry_id=resolved_candidate_id,
        entry_type=KnowledgeEntryType.SKILL_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title=f"{parent_entry.title} evolution candidate",
        tags=[
            "skill",
            "skill-card",
            "skill-evolution",
            "skillopt-inspired",
            "shadow-evaluation",
        ],
        keywords=list(keywords),
        source_refs=list(source_refs),
        related_task_ids=list(parent_entry.related_task_ids),
        related_run_ids=list(parent_entry.related_run_ids),
        body=_skill_evolution_body(
            candidate_skill_id=resolved_candidate_id,
            parent_skill_id=parent_id,
            parent_relative_path=parent_relative_path,
            parent_title=parent_entry.title,
            change_summary=summary,
            issue_refs=issues,
            failure_pattern_refs=failures,
            proposed_actions=actions,
            validation_checks=checks,
        ),
    )
    store = MarkdownKnowledgeStore(vault_root)
    candidate_relative_path = Path("exploration") / "skills" / "candidates" / (
        f"{resolved_candidate_id}.md"
    )
    candidate_path = store.write_entry(candidate_relative_path, entry)
    buffer_path = _write_rejected_edit_buffer(
        store=store,
        candidate_skill_id=resolved_candidate_id,
        parent_skill_id=parent_id,
        candidate_relative_path=candidate_relative_path.as_posix(),
        source_refs=source_refs,
    )
    stored_entry = store.read_entry(candidate_relative_path)
    return SkillEvolutionCandidate(
        candidate_skill_id=resolved_candidate_id,
        path=candidate_path,
        entry=stored_entry,
        parent_skill_id=parent_id,
        parent_relative_path=parent_relative_path,
        issue_refs=issues,
        failure_pattern_refs=failures,
        validation_checks=checks,
        rejected_edit_buffer_path=buffer_path,
    )


def audit_skill_polish_candidate(
    *,
    vault_root: Path | str,
    skill_id: str,
    peer_refs: tuple[str, ...] = (),
    live_evidence_refs: tuple[str, ...] = (),
    install_refs: tuple[str, ...] = (),
    release_refs: tuple[str, ...] = (),
    min_score: float = 0.8,
) -> SkillPolishReport:
    """Audit whether a skill card is ready for promotion or publication."""

    if not 0 <= min_score <= 1:
        msg = "min_score must be between 0 and 1"
        raise ValueError(msg)
    normalized_skill_id = _required_text(skill_id, "skill_id")
    _validate_skill_id(normalized_skill_id)
    relative_path, entry = _find_skill_by_id(Path(vault_root), normalized_skill_id)

    body = entry.body
    source_refs = _ordered_unique(entry.source_refs)
    validation_checks = _section_bullets(body, "Validation Gate")
    checks = (
        _polish_check(
            check_id="material_challenge",
            label="1. Material challenge",
            max_score=10.0,
            requirements=(
                ("skill card entry", entry.entry_type is KnowledgeEntryType.SKILL_CARD),
                ("source evidence refs", bool(source_refs)),
                (
                    "issue or failure evidence",
                    any(_looks_like_issue_or_failure(ref) for ref in source_refs),
                ),
            ),
            evidence=[entry.entry_id, *source_refs],
        ),
        _polish_check(
            check_id="peer_positioning",
            label="2. Peer positioning",
            max_score=10.0,
            requirements=(
                ("at least one peer reference", bool(peer_refs)),
                ("peer references include URLs", any(_looks_like_url(ref) for ref in peer_refs)),
            ),
            evidence=peer_refs,
        ),
        _polish_check(
            check_id="measurement_gate",
            label="3. Measurement gate",
            max_score=10.0,
            requirements=(
                ("validation gate section", "## Validation Gate" in body),
                ("validation checks", bool(validation_checks)),
                ("live or held-out evidence refs", bool(live_evidence_refs)),
            ),
            evidence=[*validation_checks, *live_evidence_refs],
        ),
        _polish_check(
            check_id="bounded_edit",
            label="4. Bounded edit discipline",
            max_score=10.0,
            requirements=(
                ("bounded edit summary", "## Bounded Edit Summary" in body),
                ("shadow evaluation status", "shadow_evaluation" in body),
                ("rollback target", "Rollback target" in body),
                ("rejected edit buffer", "Rejected edit buffer" in body),
            ),
            evidence=[relative_path],
        ),
        _polish_check(
            check_id="installable_asset",
            label="5. Installable or shareable asset",
            max_score=10.0,
            requirements=(
                ("install or export refs", bool(install_refs)),
                (
                    "skill asset path",
                    relative_path.endswith(".md") and "/skills/" in f"/{relative_path}",
                ),
            ),
            evidence=[relative_path, *install_refs],
        ),
        _polish_check(
            check_id="furnace_loop",
            label="6. Furnace loop",
            max_score=10.0,
            requirements=(
                ("shadow evaluation notes", "## Shadow Evaluation Notes" in body),
                ("release or observation refs", bool(release_refs)),
                ("rejected edit buffer stays linked", "rejected" in body.casefold()),
            ),
            evidence=[*release_refs, relative_path],
        ),
    )
    score = sum(check.score for check in checks)
    max_score = sum(check.max_score for check in checks)
    ratio = score / max_score if max_score else 0.0
    passed = ratio >= min_score and all(check.passed for check in checks)
    return SkillPolishReport(
        skill_id=normalized_skill_id,
        relative_path=relative_path,
        min_score=min_score,
        score=score,
        max_score=max_score,
        score_ratio=ratio,
        passed=passed,
        checks=checks,
    )


def _polish_check(
    *,
    check_id: str,
    label: str,
    max_score: float,
    requirements: tuple[tuple[str, bool], ...],
    evidence: Iterable[str],
) -> SkillPolishCheck:
    satisfied = [name for name, passed in requirements if passed]
    missing = [name for name, passed in requirements if not passed]
    score = max_score * (len(satisfied) / len(requirements)) if requirements else 0.0
    return SkillPolishCheck(
        check_id=check_id,
        label=label,
        passed=not missing,
        score=score,
        max_score=max_score,
        evidence=_ordered_unique(item for item in evidence if item),
        missing=tuple(missing),
    )


def _section_bullets(body: str, heading: str) -> tuple[str, ...]:
    lines = body.splitlines()
    in_section = False
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == f"## {heading}":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return _ordered_unique(bullets)


def _looks_like_url(value: str) -> bool:
    lowered = value.strip().casefold()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _looks_like_issue_or_failure(value: str) -> bool:
    lowered = value.casefold()
    return "issue" in lowered or "failure" in lowered or "problem" in lowered


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


def _skill_evolution_body(
    *,
    candidate_skill_id: str,
    parent_skill_id: str,
    parent_relative_path: str,
    parent_title: str,
    change_summary: str,
    issue_refs: tuple[str, ...],
    failure_pattern_refs: tuple[str, ...],
    proposed_actions: tuple[str, ...],
    validation_checks: tuple[str, ...],
) -> str:
    rejection_buffer_ref = (
        f"exploration/skills/rejected/{candidate_skill_id}_rejections"
    )
    lines = [
        f"# {parent_title} evolution candidate",
        "",
        f"- Candidate skill ID: `{candidate_skill_id}`",
        f"- Parent skill: [[{parent_relative_path.removesuffix('.md')}|{parent_skill_id}]]",
        "- Status: `shadow_evaluation`",
        f"- Rollback target: [[{parent_relative_path.removesuffix('.md')}|{parent_skill_id}]]",
        f"- Rejected edit buffer: [[{rejection_buffer_ref}]]",
        "",
        "## Bounded Edit Summary",
        "",
        change_summary,
        "",
        "## Trigger Evidence",
        "",
        "### Issues",
        "",
        *_wiki_bullet_lines(issue_refs),
        "",
        "### Failure Patterns",
        "",
        *_wiki_bullet_lines(failure_pattern_refs),
        "",
        "## Proposed Actions",
        "",
        *_bullet_lines(proposed_actions),
        "",
        "## Validation Gate",
        "",
        *_bullet_lines(validation_checks),
        "",
        "## Shadow Evaluation Notes",
        "",
        "- Run this candidate against held-out tasks before promotion.",
        "- Do not replace the parent skill until validation checks pass.",
        "- Record rejected edits in the linked buffer instead of deleting evidence.",
    ]
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


def _find_skill_by_id(vault_root: Path, skill_id: str) -> tuple[str, KnowledgeEntry]:
    for row in _skill_rows(vault_root):
        if row.entry.entry_id == skill_id:
            return row.relative_path, row.entry
    msg = f"parent skill not found: {skill_id}"
    raise ValueError(msg)


def _candidate_skill_id(
    *,
    parent_id: str,
    change_summary: str,
    issue_refs: tuple[str, ...],
    failure_pattern_refs: tuple[str, ...],
    proposed_actions: tuple[str, ...],
) -> str:
    seed = "|".join(
        [
            parent_id,
            change_summary,
            *issue_refs,
            *failure_pattern_refs,
            *proposed_actions,
        ]
    )
    return f"{parent_id}_candidate_{sha256(seed.encode('utf-8')).hexdigest()[:8]}"


def _write_rejected_edit_buffer(
    *,
    store: MarkdownKnowledgeStore,
    candidate_skill_id: str,
    parent_skill_id: str,
    candidate_relative_path: str,
    source_refs: tuple[str, ...],
) -> Path:
    entry = KnowledgeEntry(
        entry_id=f"{candidate_skill_id}_rejections",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Rejected edits for {candidate_skill_id}",
        tags=["skill-evolution", "rejected-edit-buffer"],
        keywords=[
            "skill-evolution",
            "rejected-edit-buffer",
            candidate_skill_id,
            parent_skill_id,
        ],
        source_refs=[candidate_relative_path, *source_refs],
        body="\n".join(
            [
                f"# Rejected edits for {candidate_skill_id}",
                "",
                f"- Candidate skill: [[{candidate_relative_path.removesuffix('.md')}]]",
                f"- Parent skill ID: `{parent_skill_id}`",
                "",
                "## Rejected Edits",
                "",
                "| Date | Edit | Reason | Evidence |",
                "|---|---|---|---|",
            ]
        ),
    )
    return store.write_entry(
        Path("exploration") / "skills" / "rejected" / f"{candidate_skill_id}_rejections.md",
        entry,
    )


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
