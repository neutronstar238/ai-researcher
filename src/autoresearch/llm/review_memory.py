"""Persist evidence-constrained LLM reviews into the Obsidian vault."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    create_vault_layout,
)

from .client import LLMReviewResult

ACTIONABLE_REVIEW_SEVERITIES = {"blocking", "critical", "high", "warning"}


def write_llm_review_note(
    *,
    result: LLMReviewResult,
    vault_root: Path | str,
    project_id: str,
    source_task_id: str | None = None,
) -> Path:
    """Write a model review result as a project-scoped Obsidian review note."""

    if not project_id.strip():
        msg = "project_id is required to write an LLM review note"
        raise ValueError(msg)

    root = Path(vault_root)
    create_vault_layout(root, project_id)
    store = MarkdownKnowledgeStore(root)
    parsed = result.quality.parsed_output if isinstance(result.quality.parsed_output, dict) else {}
    subject_stem = Path(result.subject_path).stem or "subject"
    relative_path = (
        Path("projects")
        / project_id
        / "review"
        / f"llm-review-{_slug(subject_stem)}-{result.subject_sha256[:12]}.md"
    )
    entry = KnowledgeEntry(
        entry_id=f"llm_review_{_slug(project_id)}_{result.subject_sha256[:12]}",
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        title=f"LLM evidence review: {subject_stem}",
        project_id=project_id,
        tags=["llm-review", "evidence-gate", "quality-review"],
        keywords=["llm-review", "review", "evidence", "quality", "validation"],
        source_refs=[
            result.subject_path,
            *(artifact.path for artifact in result.evidence),
        ],
        related_task_ids=[source_task_id] if source_task_id else [],
        body=_review_note_body(result=result, parsed=parsed),
    )
    return store.write_entry(relative_path, entry)


def write_llm_review_issue_notes(
    *,
    result: LLMReviewResult,
    vault_root: Path | str,
    project_id: str,
    source_task_id: str | None = None,
    review_note_path: Path | str | None = None,
) -> tuple[Path, ...]:
    """Write actionable LLM review findings as project issue notes."""

    if not project_id.strip():
        msg = "project_id is required to write LLM review issue notes"
        raise ValueError(msg)

    root = Path(vault_root)
    create_vault_layout(root, project_id)
    store = MarkdownKnowledgeStore(root)
    parsed = result.quality.parsed_output if isinstance(result.quality.parsed_output, dict) else {}
    issues = _actionable_issues(parsed)
    written: list[Path] = []
    review_ref = _source_ref(root=root, path=review_note_path) if review_note_path else None
    for index, issue in enumerate(issues, start=1):
        claim = issue["claim"]
        severity = issue["severity"]
        relative_path = (
            Path("projects")
            / project_id
            / "issues"
            / f"llm-review-{result.subject_sha256[:12]}-{index:02d}-{_slug(claim)[:48]}.md"
        )
        source_refs = [
            result.subject_path,
            *(artifact.path for artifact in result.evidence),
        ]
        if review_ref is not None:
            source_refs.append(review_ref)
        entry = KnowledgeEntry(
            entry_id=f"llm_review_issue_{_slug(project_id)}_{result.subject_sha256[:12]}_{index:02d}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            title=f"LLM review issue: {claim[:80]}",
            project_id=project_id,
            tags=["llm-review", "review-follow-up", "issue"],
            keywords=["llm-review", "review", "issue", severity],
            source_refs=source_refs,
            related_task_ids=[source_task_id] if source_task_id else [],
            body=_issue_note_body(
                result=result,
                claim=claim,
                severity=severity,
                evidence_refs=issue["evidence_refs"],
                review_ref=review_ref,
                next_steps=_string_items(parsed.get("next_steps")),
            ),
        )
        written.append(store.write_entry(relative_path, entry))
    return tuple(written)


def _review_note_body(*, result: LLMReviewResult, parsed: dict[str, Any]) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    verdict = parsed.get("verdict", "unknown")
    summary = parsed.get("summary", "No structured summary returned.")
    lines = [
        "# LLM Evidence Review",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Provider: `{result.provider}`",
        f"- Model: `{result.model_name}`",
        f"- Subject: `{result.subject_path}`",
        f"- Subject SHA256: `{result.subject_sha256}`",
        f"- Verdict: `{verdict}`",
        f"- Quality score: `{result.quality.score:.3f}`",
        "",
        "## Summary",
        "",
        str(summary),
        "",
        "## Local Evidence",
        "",
    ]
    for artifact in result.evidence:
        lines.append(
            f"- `{artifact.evidence_id}`: `{artifact.path}` "
            f"(sha256 `{artifact.sha256}`)"
        )
    lines.extend(["", "## Quality Checks", ""])
    for check, passed in result.quality.checks.items():
        lines.append(f"- `{check}`: {'pass' if passed else 'fail'}")

    findings = parsed.get("findings")
    lines.extend(["", "## Findings", ""])
    if isinstance(findings, list) and findings:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = finding.get("severity", "unknown")
            claim = finding.get("claim", "")
            evidence_refs = finding.get("evidence_refs", [])
            refs = ", ".join(f"`{ref}`" for ref in evidence_refs if isinstance(ref, str))
            lines.append(f"- **{severity}**: {claim}")
            lines.append(f"  - Evidence refs: {refs or '`missing`'}")
    else:
        lines.append("- No structured findings returned.")

    lines.extend(["", "## Unsupported Claims", ""])
    unsupported_claims = parsed.get("unsupported_claims")
    if isinstance(unsupported_claims, list) and unsupported_claims:
        lines.extend(f"- {claim}" for claim in unsupported_claims)
    else:
        lines.append("- None reported.")

    lines.extend(["", "## Next Steps", ""])
    next_steps = parsed.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- None reported.")

    if result.quality.issues:
        lines.extend(["", "## Deterministic Gate Issues", ""])
        lines.extend(f"- {issue}" for issue in result.quality.issues)

    lines.extend(
        [
            "",
            "## Raw Reviewer JSON",
            "",
            "```json",
            json.dumps(parsed or {"raw_response": result.response_text}, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    return "\n".join(lines)


def _issue_note_body(
    *,
    result: LLMReviewResult,
    claim: str,
    severity: str,
    evidence_refs: list[str],
    review_ref: str | None,
    next_steps: list[str],
) -> str:
    lines = [
        "# LLM Review Follow-Up",
        "",
        "- Status: Open",
        f"- Severity: `{severity}`",
        f"- Subject: `{result.subject_path}`",
        f"- Reviewer verdict: `{_parsed_verdict(result)}`",
        f"- Review quality score: `{result.quality.score:.3f}`",
    ]
    if review_ref is not None:
        lines.append(f"- Source review: [[{review_ref.removesuffix('.md')}|LLM evidence review]]")
    lines.extend(
        [
            "",
            "## Claim",
            "",
            claim,
            "",
            "## Evidence References",
            "",
        ]
    )
    if evidence_refs:
        lines.extend(f"- `{ref}`" for ref in evidence_refs)
    else:
        lines.append("- `missing`")
    lines.extend(["", "## Next Actions", ""])
    if next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- Add source-backed evidence or revise the claim.")
    return "\n".join(lines)


def _actionable_issues(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    findings = parsed.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity", "")).casefold()
            claim = finding.get("claim")
            if severity not in ACTIONABLE_REVIEW_SEVERITIES or not isinstance(claim, str):
                continue
            normalized_claim = claim.strip()
            if not normalized_claim:
                continue
            seen_claims.add(normalized_claim.casefold())
            issues.append(
                {
                    "claim": normalized_claim,
                    "severity": severity,
                    "evidence_refs": _string_items(finding.get("evidence_refs")),
                }
            )

    for claim in _string_items(parsed.get("unsupported_claims")):
        if claim.casefold() in seen_claims:
            continue
        issues.append({"claim": claim, "severity": "blocking", "evidence_refs": []})
    return issues


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parsed_verdict(result: LLMReviewResult) -> str:
    parsed = result.quality.parsed_output
    verdict = parsed.get("verdict") if isinstance(parsed, dict) else None
    if isinstance(verdict, str):
        return verdict
    return "unknown"


def _source_ref(*, root: Path, path: Path | str | None) -> str | None:
    if path is None:
        return None
    source = Path(path)
    try:
        return source.relative_to(root).as_posix()
    except ValueError:
        return source.as_posix()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug.casefold() or "item"
