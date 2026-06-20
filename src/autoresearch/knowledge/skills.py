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
class ExternalSkillCandidate:
    """External skill idea held in quarantine before any promotion."""

    candidate_id: str
    name: str
    purpose: str
    source_refs: tuple[str, ...]
    license_status: str
    adoption_stage: str
    expected_benefit: str
    risk_notes: tuple[str, ...]
    validation_gates: tuple[str, ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExternalSkillWatchlist:
    """Persisted Obsidian watchlist for external research-skill candidates."""

    path: Path
    relative_path: str
    entry: KnowledgeEntry
    candidate_ids: tuple[str, ...]


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


def default_external_research_skill_candidates() -> tuple[ExternalSkillCandidate, ...]:
    """Return the default external research-skill watchlist candidates."""

    return (
        ExternalSkillCandidate(
            candidate_id="ccfa_skill_quality_gate",
            name="CCFA-Skill",
            purpose="Full-flow venue-quality automation direction from the user screenshot.",
            source_refs=("user screenshot 2026-06-15: research skill discoveries",),
            license_status="unverified screenshot-derived idea; no upstream content adopted",
            adoption_stage="taxonomy-only",
            expected_benefit="Adds a named quality-gate bucket for CCF-A/B-style checks.",
            risk_notes=(
                "Venue labels are not evidence by themselves.",
                "Do not inflate publication-readiness claims without reviewer evidence.",
            ),
            validation_gates=(
                "Run publication audit on held-out cycles.",
                "Require source-backed venue fit and reviewer-style rejection reasons.",
            ),
            tags=("quality-gate", "venue-fit"),
        ),
        ExternalSkillCandidate(
            candidate_id="paper_skill_writing_library",
            name="Paper-Skill",
            purpose="Academic writing skill-library direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/zsyggg/paper-craft-skills",
            ),
            license_status="paper-craft-skills is MIT; screenshot name remains unverified",
            adoption_stage="reference-only",
            expected_benefit="Improves paper-to-figure, paper-to-deck, and paper analysis planning.",
            risk_notes=(
                "Do not copy third-party skill prompt text or generated examples.",
                "Visual polish must not hide weak evidence.",
            ),
            validation_gates=(
                "Run figure/table quality gates on generated manuscripts.",
                "Verify all paper claims against local evidence and citations.",
            ),
            tags=("paper-writing", "visualization"),
        ),
        ExternalSkillCandidate(
            candidate_id="question_validator_topic_gate",
            name="Question-Validator",
            purpose="Research-question validation direction from the user screenshot.",
            source_refs=("user screenshot 2026-06-15: research skill discoveries",),
            license_status="unverified screenshot-derived idea; no upstream content adopted",
            adoption_stage="candidate-gate",
            expected_benefit="Strengthens topic novelty, feasibility, and evidence-readiness checks.",
            risk_notes=(
                "A question can sound novel while already existing under different terminology.",
                "Broad web and academic cross-search is required before approval.",
            ),
            validation_gates=(
                "Require similarity-check evidence across scholarly and non-scholarly sources.",
                "Block topics with no executable experiment path.",
            ),
            tags=("topic-validation", "novelty"),
        ),
        ExternalSkillCandidate(
            candidate_id="empirical_paper_pipeline",
            name="Empirical-Paper",
            purpose="Empirical-paper automation direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/brycewang-stanford/Auto-Empirical-Research-Skills",
            ),
            license_status="AERS shows a CC BY-SA 4.0 license badge; review before copying",
            adoption_stage="reference-only",
            expected_benefit="Adds a stage taxonomy for data cleaning, identification, estimation, robustness, tables, and draft checks.",
            risk_notes=(
                "Social-science empirical workflows may not transfer directly to ML benchmark papers.",
                "Share-alike or mixed-license constraints need review before adaptation.",
            ),
            validation_gates=(
                "Recompute numeric benchmark values from raw or fetched data.",
                "Audit license metadata before using any external skill content.",
            ),
            tags=("empirical", "statistics"),
        ),
        ExternalSkillCandidate(
            candidate_id="paper_to_patent_prior_art",
            name="Paper-to-Patent",
            purpose="Paper-to-patent/prior-art direction from the user screenshot.",
            source_refs=("user screenshot 2026-06-15: research skill discoveries",),
            license_status="unverified screenshot-derived idea; no upstream content adopted",
            adoption_stage="legal-sensitive-watchlist",
            expected_benefit="Could convert method claims into prior-art search plans.",
            risk_notes=(
                "Patent analysis is legal-adjacent and must avoid legal advice claims.",
                "Requires external prior-art evidence and human review.",
            ),
            validation_gates=(
                "Label output as prior-art research support, not legal advice.",
                "Require source URLs, dates, and claim-to-evidence mapping.",
            ),
            tags=("prior-art", "patent"),
        ),
        ExternalSkillCandidate(
            candidate_id="in_depth_research_workflow",
            name="In-depth-Research",
            purpose="Deep investigation direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/Weizhena/Deep-Research-skills",
                "https://github.com/bytedance/deer-flow/blob/main/skills/public/deep-research/SKILL.md",
            ),
            license_status="Deep-Research-skills is MIT; deer-flow skill content requires separate review",
            adoption_stage="reference-only",
            expected_benefit="Improves outline-first, source-broad, multi-pass research before writing.",
            risk_notes=(
                "Human-in-the-loop assumptions may conflict with always-on operation.",
                "Deep research must still obey rate limits and source-claim discipline.",
            ),
            validation_gates=(
                "Require source diversity and freshness metadata.",
                "Block unsupported synthesis without citations.",
            ),
            tags=("deep-research", "source-breadth"),
        ),
        ExternalSkillCandidate(
            candidate_id="paper_to_storyboard_publication_web",
            name="Paper-to-Storyboard",
            purpose="Paper-to-web/storyboard direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/zsyggg/paper-craft-skills",
            ),
            license_status="paper-craft-skills is MIT; screenshot name remains unverified",
            adoption_stage="reference-only",
            expected_benefit="Turns accepted evidence into public-facing explainer pages.",
            risk_notes=(
                "Explainers can over-simplify negative or uncertain results.",
                "Generated web assets need license and source audits.",
            ),
            validation_gates=(
                "Map every visual or storyboard claim back to paper evidence.",
                "Run asset license scan before publishing.",
            ),
            tags=("storyboard", "paper-web"),
        ),
        ExternalSkillCandidate(
            candidate_id="source_tracing_citation_provenance",
            name="Source-Tracing",
            purpose="Citation and source-provenance direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/benchflow-ai/skillsbench/blob/main/tasks/citation-check/environment/skills/citation-management/SKILL.md",
            ),
            license_status="referenced citation-management skill declares MIT License",
            adoption_stage="candidate-gate",
            expected_benefit="Supports DOI/BibTeX verification and source-backed claims.",
            risk_notes=(
                "Google Scholar scraping may violate terms or be unstable.",
                "Citation metadata must be verified against primary APIs where possible.",
            ),
            validation_gates=(
                "Use Crossref, PubMed, arXiv, OpenAlex, or publisher metadata before final bibliography.",
                "Fail paper build when references contain pseudo-labels.",
            ),
            tags=("citation", "provenance"),
        ),
        ExternalSkillCandidate(
            candidate_id="paper2beamer_presentation_export",
            name="Paper2Beamer",
            purpose="Paper-to-PPT/Beamer direction from the user screenshot.",
            source_refs=(
                "user screenshot 2026-06-15: research skill discoveries",
                "https://github.com/zsyggg/paper-craft-skills",
            ),
            license_status="paper-craft-skills is MIT; screenshot name remains unverified",
            adoption_stage="reference-only",
            expected_benefit="Adds a future presentation export path after paper evidence gates pass.",
            risk_notes=(
                "Slides are secondary artifacts and must not precede evidence validation.",
                "Template and image assets need attribution checks.",
            ),
            validation_gates=(
                "Generate slides only from a passing paper/evidence bundle.",
                "Render and visually QA PPTX/PDF outputs.",
            ),
            tags=("slides", "beamer"),
        ),
        ExternalSkillCandidate(
            candidate_id="research_genealogy_prior_work_graph",
            name="Research-Genealogy",
            purpose="Paper genealogy and prior-work lineage direction from the user screenshot.",
            source_refs=("user screenshot 2026-06-15: research skill discoveries",),
            license_status="unverified screenshot-derived idea; no upstream content adopted",
            adoption_stage="candidate-gate",
            expected_benefit="Builds contribution lineage graphs to reduce duplicate novelty claims.",
            risk_notes=(
                "Citation graph incompleteness can hide close prior work.",
                "Needs cross-source deduplication and evidence confidence labels.",
            ),
            validation_gates=(
                "Search title, method, dataset, task, and metric variants.",
                "Store lineage graph and overlap classification in Obsidian.",
            ),
            tags=("lineage", "novelty"),
        ),
        ExternalSkillCandidate(
            candidate_id="simplemem_memory_substrate",
            name="Omni-SimpleMem / SimpleMem",
            purpose="Long-horizon memory architecture reference for the Obsidian memory layer.",
            source_refs=(
                "https://github.com/aiming-lab/SimpleMem",
                "https://arxiv.org/abs/2604.01007",
            ),
            license_status="SimpleMem is MIT",
            adoption_stage="architecture-reference",
            expected_benefit="Provides compression-first and progressive-retrieval ideas for vault experiments.",
            risk_notes=(
                "Claims require reproduction before being used as product benchmarks.",
                "Direct dependency would add vector/search infrastructure complexity.",
            ),
            validation_gates=(
                "Benchmark against existing Obsidian retrieval on local historical cycles.",
                "Require rollback-safe memory index builds before production use.",
            ),
            tags=("memory", "retrieval"),
        ),
        ExternalSkillCandidate(
            candidate_id="skillclaw_collective_skill_evolution",
            name="SkillClaw",
            purpose="Collective skill evolution architecture reference.",
            source_refs=(
                "https://github.com/AMAP-ML/SkillClaw",
                "https://huggingface.co/papers/2604.08377",
            ),
            license_status="SkillClaw is MIT",
            adoption_stage="architecture-reference",
            expected_benefit="Separates local skill capture, shared storage, and optional evolution server.",
            risk_notes=(
                "Automatic skill mutation must not bypass AI-Researcher approval gates.",
                "Shared multi-user storage raises privacy and provenance concerns.",
            ),
            validation_gates=(
                "Keep skill candidates in shadow mode until audit passes.",
                "Record every promoted skill with source refs, rejected edits, and rollback target.",
            ),
            tags=("skill-evolution", "collective-learning"),
        ),
        ExternalSkillCandidate(
            candidate_id="meta_harness_harness_search_reference",
            name="Meta-Harness",
            purpose=(
                "Harness-search reference for controlled self-evolution: keep "
                "the base model fixed while searching over retrieval, memory, "
                "context construction, planning, and tool-use scaffolding."
            ),
            source_refs=(
                "https://github.com/stanford-iris-lab/meta-harness",
                "https://arxiv.org/abs/2603.28052",
                "https://raw.githubusercontent.com/stanford-iris-lab/meta-harness/main/ONBOARDING.md",
            ),
            license_status="MIT; reviewed 2026-06-19; no upstream code or prompt text adopted",
            adoption_stage="harness-search-reference",
            expected_benefit=(
                "Adds a domain-spec-first candidate harness loop with full "
                "trace archive evidence, anti-leakage checks, and Pareto-aware "
                "promotion criteria."
            ),
            risk_notes=(
                "Harness search can overfit when search-set and held-out evidence are mixed.",
                "Full proposer traces may contain secrets, credentials, or unsafe commands.",
                "Candidate harness code must stay in shadow evaluation until release gates pass.",
            ),
            validation_gates=(
                "Write a domain_spec-style plan before implementation: fixed base model, allowed harness surface, budget, metrics, and baselines.",
                "Store candidate source, scores, proposer logs, execution traces, config hashes, and data splits in an auditable trace archive.",
                "Keep search-set feedback separate from held-out evaluation and block promotion if held-out data leaks into proposer context.",
                "Promote only through skill-evolve, shadow evaluation, publication audit, evidence gate, and rollback records.",
            ),
            tags=("harness-search", "self-evolution", "trace-archive", "anti-leakage"),
        ),
        ExternalSkillCandidate(
            candidate_id="lightagent_lightflow_trace_reference",
            name="LightAgent / LightFlow",
            purpose=(
                "Lightweight agent-runtime reference for Skills, deterministic "
                "DAG-style workflow steps, opt-in trace observability, and "
                "memory/trace/delegation boundaries."
            ),
            source_refs=(
                "https://github.com/wanxingai/LightAgent",
                "https://raw.githubusercontent.com/wanxingai/LightAgent/main/LICENSE",
                "https://raw.githubusercontent.com/wanxingai/LightAgent/main/docs/lightflow.md",
                "https://raw.githubusercontent.com/wanxingai/LightAgent/main/docs/tracing.md",
                "https://raw.githubusercontent.com/wanxingai/LightAgent/main/docs/memory_trace_swarm_boundaries.md",
                "https://raw.githubusercontent.com/wanxingai/LightAgent/main/docs/multi_agent_failure_map.md",
            ),
            license_status=(
                "Apache-2.0; reviewed 2026-06-20; no upstream code, docs text, "
                "examples, traces, or assets adopted"
            ),
            adoption_stage="lightweight-agent-runtime-reference",
            expected_benefit=(
                "Gives small, auditable patterns for explicit step dependencies, "
                "step-local retries, trace IDs/events, memory provenance filters, "
                "and multi-agent failure diagnostics."
            ),
            risk_notes=(
                "Lightweight runtime examples must not bypass AI-Researcher evidence gates.",
                "Trace events and tool logs can contain secrets or sensitive source data.",
                "Self-learning memory can pollute Obsidian if user, trace, reflection, and delegation scopes are mixed.",
            ),
            validation_gates=(
                "Do not add LightAgent as a runtime dependency or copy its examples by default.",
                "If a LightFlow-style idea is adapted, map it onto AI-Researcher's existing lifecycle trace, approval gate, and release gate.",
                "Separate trace, user/project memory, reflection memory, and delegation state with provenance before Obsidian ingestion.",
                "Add failure-map checks for role drift, shared-memory pollution, hidden hand-off loops, and unreadable agent logs.",
                "Scrub secrets from trace events and store only evidence-safe summaries in the vault.",
            ),
            tags=(
                "agent-runtime",
                "lightflow",
                "trace-observability",
                "memory-boundary",
                "multi-agent-diagnostics",
            ),
        ),
        ExternalSkillCandidate(
            candidate_id="oh_my_openagent_agent_harness",
            name="oh-my-openagent / LazyCodex",
            purpose=(
                "Agent-harness reference for OpenCode/Codex orchestration, Team "
                "Mode, LSP/AST tooling, hash-anchored edits, and long-running "
                "coding loops."
            ),
            source_refs=(
                "https://github.com/code-yeongyu/oh-my-openagent",
                "https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/dev/LICENSE.md",
                "https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/dev/docs/guide/installation.md",
            ),
            license_status=(
                "SUL-1.0 / Sustainable Use License; not OSI-style permissive; "
                "no adoption without legal review"
            ),
            adoption_stage="reference-only-license-risk",
            expected_benefit=(
                "Provides ideas for external coding-agent harness contracts, "
                "hash-anchored edit validation, team visualization, and "
                "tool-scoped skills."
            ),
            risk_notes=(
                "The SUL-1.0 license includes non-commercial/internal-use limitations.",
                "Installer can modify global Codex/OpenCode configuration and "
                "autonomous permission settings.",
                "Telemetry is documented as enabled by default upstream.",
            ),
            validation_gates=(
                "Do not install or vendor it in AI-Researcher by default.",
                "If evaluated, run only in an isolated test home and record exact "
                "config mutations.",
                "Adopt concepts only after license review and AI-Researcher "
                "validation/rollback gates.",
            ),
            tags=("agent-harness", "opencode", "codex", "code-agent"),
        ),
        ExternalSkillCandidate(
            candidate_id="page_agent_browser_source_adapter",
            name="PageAgent",
            purpose=(
                "Browser-source acquisition reference for non-API Horizon-style "
                "inspiration and search sources, using in-page JavaScript DOM "
                "actions plus optional extension/MCP control."
            ),
            source_refs=(
                "https://github.com/alibaba/page-agent",
                "https://raw.githubusercontent.com/alibaba/page-agent/main/LICENSE",
                "https://alibaba.github.io/page-agent/",
            ),
            license_status=(
                "MIT; upstream README acknowledges browser-use-derived DOM "
                "processing and prompt components under MIT"
            ),
            adoption_stage="browser-source-reference",
            expected_benefit=(
                "Extends future broad-inspiration acquisition beyond public APIs "
                "by capturing interactive web pages with structured DOM snapshots "
                "and action logs."
            ),
            risk_notes=(
                "Upstream positions PageAgent as client-side web enhancement, not "
                "server-side automation.",
                "Interactive pages require robots/ToS, rate-limit, consent, login, "
                "and reproducible snapshot checks.",
                "Browser actions must use allowlists, sandboxed profiles, and "
                "approval for state-changing clicks or forms.",
            ),
            validation_gates=(
                "Do not use PageAgent as the default crawler for V1.0.",
                "Evaluate only in an isolated browser profile against allowed test "
                "sites or public pages.",
                "Persist URL, timestamp, DOM snapshot, screenshot/hash, action "
                "trace, source terms, and extraction confidence before Obsidian "
                "ingestion.",
                "Promotion requires rate-limit, robots/terms review, and evidence "
                "gate integration.",
            ),
            tags=("browser-agent", "source-acquisition", "horizon", "web-retrieval"),
        ),
    )


def write_external_skill_watchlist(
    *,
    vault_root: Path | str,
    candidates: tuple[ExternalSkillCandidate, ...],
    source_note: str = "",
    watchlist_id: str = "external_research_skill_watchlist",
) -> ExternalSkillWatchlist:
    """Write external skill candidates as a quarantined Obsidian watchlist."""

    if not candidates:
        msg = "at least one external skill candidate is required"
        raise ValueError(msg)
    _validate_skill_id(watchlist_id)
    for candidate in candidates:
        _validate_external_skill_candidate(candidate)

    candidate_ids = _ordered_unique(candidate.candidate_id for candidate in candidates)
    source_refs = _ordered_unique(ref for candidate in candidates for ref in candidate.source_refs)
    tags = _ordered_unique(
        [
            "skill",
            "external-skill",
            "skill-watchlist",
            "quarantine",
            *(tag for candidate in candidates for tag in candidate.tags),
        ]
    )
    keywords = _ordered_unique(
        [
            "external-skill",
            "skill-watchlist",
            "reference-only",
            *candidate_ids,
            *(candidate.name for candidate in candidates),
            *(tag for candidate in candidates for tag in candidate.tags),
        ]
    )
    entry = KnowledgeEntry(
        entry_id=watchlist_id,
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title="External research skill watchlist",
        tags=list(tags),
        keywords=list(keywords),
        source_refs=list(source_refs),
        body=_external_skill_watchlist_body(candidates=candidates, source_note=source_note),
    )
    relative_path = Path("exploration") / "skills" / "external-research-skill-watchlist.md"
    store = MarkdownKnowledgeStore(vault_root)
    path = store.write_entry(relative_path, entry)
    stored_entry = store.read_entry(relative_path)
    return ExternalSkillWatchlist(
        path=path,
        relative_path=relative_path.as_posix(),
        entry=stored_entry,
        candidate_ids=tuple(candidate_ids),
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


def _validate_external_skill_candidate(candidate: ExternalSkillCandidate) -> None:
    _validate_skill_id(_required_text(candidate.candidate_id, "candidate.candidate_id"))
    _required_text(candidate.name, "candidate.name")
    _required_text(candidate.purpose, "candidate.purpose")
    _required_text(candidate.license_status, "candidate.license_status")
    _required_text(candidate.adoption_stage, "candidate.adoption_stage")
    _required_text(candidate.expected_benefit, "candidate.expected_benefit")
    if not candidate.source_refs:
        msg = "candidate.source_refs must not be empty"
        raise ValueError(msg)
    if not candidate.risk_notes:
        msg = "candidate.risk_notes must not be empty"
        raise ValueError(msg)
    if not candidate.validation_gates:
        msg = "candidate.validation_gates must not be empty"
        raise ValueError(msg)
    for source_ref in candidate.source_refs:
        _required_text(source_ref, "candidate.source_ref")
    for risk_note in candidate.risk_notes:
        _required_text(risk_note, "candidate.risk_note")
    for validation_gate in candidate.validation_gates:
        _required_text(validation_gate, "candidate.validation_gate")


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


def _external_skill_watchlist_body(
    *,
    candidates: tuple[ExternalSkillCandidate, ...],
    source_note: str,
) -> str:
    lines = [
        "# External research skill watchlist",
        "",
        "## Intake Policy",
        "",
        "- Status: `quarantine` until license, source, security, and live validation gates pass.",
        "- Do not copy, vendor, adapt, or enable third-party skill text, prompts, code, screenshots, or generated assets from this watchlist.",
        "- Use candidates as retrieval cues, peer references, and future validation-gate ideas only.",
        "- Promotion requires a separate bounded `skill-evolve` candidate, `skill-polish-audit`, live evidence, and rollback plan.",
        "",
    ]
    if source_note.strip():
        lines.extend(["## Source Note", "", source_note.strip(), ""])
    lines.extend(["## Candidates", ""])
    for candidate in candidates:
        lines.extend(
            [
                f"### {candidate.name}",
                "",
                f"- Candidate ID: `{candidate.candidate_id}`",
                f"- Purpose: {candidate.purpose}",
                f"- Adoption stage: `{candidate.adoption_stage}`",
                f"- License status: {candidate.license_status}",
                f"- Expected benefit: {candidate.expected_benefit}",
                f"- Source refs: {_inline_items(candidate.source_refs)}",
                f"- Tags: {_inline_items(candidate.tags)}",
                "",
                "Risk notes:",
                "",
                *_bullet_lines(candidate.risk_notes),
                "",
                "Validation gates:",
                "",
                *_bullet_lines(candidate.validation_gates),
                "",
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
