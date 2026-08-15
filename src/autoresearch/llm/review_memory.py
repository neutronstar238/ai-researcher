"""Persist evidence-constrained LLM reviews into the Obsidian vault."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
    create_vault_layout,
)

from .client import LLMReviewResult

ACTIONABLE_REVIEW_SEVERITIES = {"blocking", "critical", "high", "warning"}


def capture_llm_review_response(
    *,
    result: LLMReviewResult,
    vault_root: Path | str,
    project_id: str,
) -> RawMemoryBinding:
    """Capture an exact review response before thresholding or derived-note writes."""

    if not project_id.strip():
        raise ValueError("project_id is required to capture an LLM review response")
    no_secret_leak = result.quality.checks.get("no_secret_leak") is True
    if not no_secret_leak:
        raise ValueError(
            "LLM review response cannot enter raw memory until the secret-leak "
            "check passes"
        )
    root = Path(vault_root)
    create_vault_layout(root, project_id)
    raw_store = RawMemoryStore(root)
    subject_stem = Path(result.subject_path).stem or "subject"
    capture = raw_store.capture_text(
        result.response_text,
        project_id=project_id,
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label=f"模型证据评审原始响应：{subject_stem}",
        source_ref=f"llm-review-subject:{result.subject_sha256}",
        original_name=f"llm-review-{result.subject_sha256[:12]}.json",
        source_authorized=True,
        sensitive_content_reviewed=True,
    )
    return capture.binding(root)


def write_llm_review_note(
    *,
    result: LLMReviewResult,
    vault_root: Path | str,
    project_id: str,
    source_task_id: str | None = None,
    raw_binding: RawMemoryBinding | None = None,
) -> Path:
    """Write a model review result as a project-scoped Obsidian review note."""

    if not project_id.strip():
        msg = "project_id is required to write an LLM review note"
        raise ValueError(msg)

    root = Path(vault_root)
    create_vault_layout(root, project_id)
    store = MarkdownKnowledgeStore(root)
    raw_store = RawMemoryStore(root)
    parsed = result.quality.parsed_output if isinstance(result.quality.parsed_output, dict) else {}
    subject_stem = Path(result.subject_path).stem or "subject"
    if raw_binding is None:
        raw_binding = capture_llm_review_response(
            result=result,
            vault_root=root,
            project_id=project_id,
        )
    raw_capture = raw_store.load_record(
        raw_binding.record_relative_path,
        project_id=project_id,
    )
    if raw_capture.binding(root) != raw_binding:
        raise ValueError("supplied raw review binding does not verify")
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
        title=f"LLM 证据评审：{subject_stem}",
        project_id=project_id,
        tags=["llm-review", "evidence-gate", "quality-review"],
        keywords=["llm-review", "review", "evidence", "quality", "validation"],
        source_refs=[
            result.subject_path,
            *(artifact.path for artifact in result.evidence),
            raw_binding.record_id,
        ],
        related_task_ids=[source_task_id] if source_task_id else [],
        body=_review_note_body(result=result, parsed=parsed, raw_binding=raw_binding),
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
    for issue in issues:
        claim = issue["claim"]
        severity = issue["severity"]
        fingerprint = _issue_fingerprint(result=result, claim=claim)
        relative_path = (
            Path("projects")
            / project_id
            / "issues"
            / f"llm-review-{result.subject_sha256[:12]}-{fingerprint[:12]}-{_slug(claim)[:48]}.md"
        )
        source_refs = [
            result.subject_path,
            *(artifact.path for artifact in result.evidence),
        ]
        if review_ref is not None:
            source_refs.append(review_ref)
        entry = KnowledgeEntry(
            entry_id=f"llm_review_issue_{_slug(project_id)}_{fingerprint[:16]}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            title=f"LLM 评审问题：{claim[:80]}",
            project_id=project_id,
            tags=["llm-review", "review-follow-up", "issue"],
            keywords=["llm-review", "review", "issue", severity],
            source_refs=source_refs,
            related_task_ids=[source_task_id] if source_task_id else [],
            body=_issue_note_body(
                result=result,
                claim=claim,
                severity=severity,
                fingerprint=fingerprint,
                evidence_refs=issue["evidence_refs"],
                review_ref=review_ref,
                next_steps=_string_items(parsed.get("next_steps")),
            ),
        )
        written.append(store.write_entry(relative_path, entry))
    return tuple(written)


def _review_note_body(
    *,
    result: LLMReviewResult,
    parsed: dict[str, Any],
    raw_binding: RawMemoryBinding,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    verdict = parsed.get("verdict", "unknown")
    summary = parsed.get("summary", "模型未返回结构化摘要。")
    lines = [
        "# LLM 证据评审",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 模型提供方：`{result.provider}`",
        f"- 模型：`{result.model_name}`",
        f"- 评审对象：`{result.subject_path}`",
        f"- 评审对象 SHA256：`{result.subject_sha256}`",
        f"- 结论：`{verdict}`",
        f"- 质量分：`{result.quality.score:.3f}`",
        "",
        "## 摘要",
        "",
        str(summary),
        "",
        "## 本地证据",
        "",
    ]
    for artifact in result.evidence:
        lines.append(
            f"- `{artifact.evidence_id}`: `{artifact.path}` "
            f"(sha256 `{artifact.sha256}`)"
        )
    lines.extend(["", "## 质量检查", ""])
    for check, passed in result.quality.checks.items():
        lines.append(f"- `{check}`：{'通过' if passed else '未通过'}")

    findings = parsed.get("findings")
    lines.extend(["", "## 发现", ""])
    if isinstance(findings, list) and findings:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = finding.get("severity", "unknown")
            claim = finding.get("claim", "")
            evidence_refs = finding.get("evidence_refs", [])
            refs = ", ".join(f"`{ref}`" for ref in evidence_refs if isinstance(ref, str))
            lines.append(f"- **{severity}**: {claim}")
            lines.append(f"  - 证据引用：{refs or '`缺失`'}")
    else:
        lines.append("- 模型未返回结构化发现。")

    lines.extend(["", "## 无证据支持的论断", ""])
    unsupported_claims = parsed.get("unsupported_claims")
    if isinstance(unsupported_claims, list) and unsupported_claims:
        lines.extend(f"- {claim}" for claim in unsupported_claims)
    else:
        lines.append("- 未报告。")

    lines.extend(["", "## 后续步骤", ""])
    next_steps = parsed.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- 未报告。")

    if result.quality.issues:
        lines.extend(["", "## 确定性门禁问题", ""])
        lines.extend(f"- {issue}" for issue in result.quality.issues)

    lines.extend(
        [
            "",
            "## 评审模型原始响应绑定",
            "",
            "模型的精确原始响应保存在本地私有、只追加的原始记忆层；本评审笔记只是可重建的派生视图。",
            "",
            f"- 原始记录 ID：`{raw_binding.record_id}`",
            f"- 原始记录哈希：`{raw_binding.record_hash}`",
            f"- 精确响应 SHA256：`{raw_binding.payload_sha256}`",
            f"- 私有记录：`{raw_binding.record_relative_path}`",
        ]
    )
    return "\n".join(lines)


def _issue_note_body(
    *,
    result: LLMReviewResult,
    claim: str,
    severity: str,
    fingerprint: str,
    evidence_refs: list[str],
    review_ref: str | None,
    next_steps: list[str],
) -> str:
    lines = [
        "# LLM 评审跟进",
        "",
        "- 状态：待处理",
        f"- 严重程度：`{severity}`",
        f"- 问题指纹：`{fingerprint}`",
        f"- 评审对象：`{result.subject_path}`",
        f"- 评审结论：`{_parsed_verdict(result)}`",
        f"- 评审质量分：`{result.quality.score:.3f}`",
    ]
    if review_ref is not None:
        lines.append(
            f"- 来源评审：[[{review_ref.removesuffix('.md')}|LLM 证据评审]]"
        )
    lines.extend(
        [
            "",
            "## 论断",
            "",
            claim,
            "",
            "## 证据引用",
            "",
        ]
    )
    if evidence_refs:
        lines.extend(f"- `{ref}`" for ref in evidence_refs)
    else:
        lines.append("- `缺失`")
    lines.extend(["", "## 后续行动", ""])
    if next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- 补充有来源支持的证据，或修订该论断。")
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
            normalized_key = normalized_claim.casefold()
            if normalized_key in seen_claims:
                continue
            seen_claims.add(normalized_key)
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


def _issue_fingerprint(*, result: LLMReviewResult, claim: str) -> str:
    normalized_claim = " ".join(claim.casefold().split())
    return sha256(f"{result.subject_sha256}:{normalized_claim}".encode()).hexdigest()


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
