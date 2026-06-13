"""Cross-cycle stability gate for publication-level output claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)


class PublicationStabilityVerdict(str, Enum):
    """Stability decision across a matrix of completed cycles."""

    PASS = "pass"
    BLOCKED = "blocked"


class PublicationStabilityCheckStatus(str, Enum):
    """One stability-matrix check state."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class PublicationStabilityTarget:
    """Minimum cross-cycle evidence needed before claiming stable output."""

    name: str
    display_name: str
    min_cycles: int
    min_release_allowed_cycles: int
    min_release_pass_rate: float
    min_distinct_real_datasets: int
    min_distinct_templates: int
    min_external_templates: int
    min_external_conference_templates: int
    min_external_journal_templates: int
    max_warnings_per_cycle: int


@dataclass(frozen=True)
class PublicationStabilityCheck:
    """One evidence-backed cross-cycle stability check."""

    check_id: str
    status: PublicationStabilityCheckStatus
    severity: str
    message: str
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "severity": self.severity,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class CycleStabilityRecord:
    """Normalized evidence from one completed autonomous cycle."""

    cycle_summary_path: str
    cycle_id: str
    project_id: str
    demo: str
    dataset: str
    real_dataset: bool
    publication_verdict: str
    publishable: bool
    publication_score: float | None
    publication_warning_count: int
    evidence_verdict: str
    release_allowed: bool
    paper_template: str
    paper_template_source_kind: str
    paper_template_venue_kind: str
    paper_quality_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_summary_path": self.cycle_summary_path,
            "cycle_id": self.cycle_id,
            "project_id": self.project_id,
            "demo": self.demo,
            "dataset": self.dataset,
            "real_dataset": self.real_dataset,
            "publication_verdict": self.publication_verdict,
            "publishable": self.publishable,
            "publication_score": self.publication_score,
            "publication_warning_count": self.publication_warning_count,
            "evidence_verdict": self.evidence_verdict,
            "release_allowed": self.release_allowed,
            "paper_template": self.paper_template,
            "paper_template_source_kind": self.paper_template_source_kind,
            "paper_template_venue_kind": self.paper_template_venue_kind,
            "paper_quality_passed": self.paper_quality_passed,
        }


@dataclass(frozen=True)
class PublicationStabilityReport:
    """Cross-cycle stability gate output."""

    target: PublicationStabilityTarget
    verdict: PublicationStabilityVerdict
    checks: tuple[PublicationStabilityCheck, ...]
    cycles: tuple[CycleStabilityRecord, ...]
    output_path: str
    markdown_path: str
    vault_review_path: str | None = None
    vault_issue_path: str | None = None

    @property
    def stable(self) -> bool:
        return self.verdict is PublicationStabilityVerdict.PASS

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        weight = {
            PublicationStabilityCheckStatus.PASS: 1.0,
            PublicationStabilityCheckStatus.WARNING: 0.5,
            PublicationStabilityCheckStatus.FAIL: 0.0,
        }
        return round(sum(weight[check.status] for check in self.checks) / len(self.checks), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {
                "name": self.target.name,
                "display_name": self.target.display_name,
                "min_cycles": self.target.min_cycles,
                "min_release_allowed_cycles": self.target.min_release_allowed_cycles,
                "min_release_pass_rate": self.target.min_release_pass_rate,
                "min_distinct_real_datasets": self.target.min_distinct_real_datasets,
                "min_distinct_templates": self.target.min_distinct_templates,
                "min_external_templates": self.target.min_external_templates,
                "min_external_conference_templates": self.target.min_external_conference_templates,
                "min_external_journal_templates": self.target.min_external_journal_templates,
                "max_warnings_per_cycle": self.target.max_warnings_per_cycle,
            },
            "verdict": self.verdict.value,
            "stable": self.stable,
            "score": self.score,
            "checks": [check.to_dict() for check in self.checks],
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "output_path": self.output_path,
            "markdown_path": self.markdown_path,
            "vault_review_path": self.vault_review_path,
            "vault_issue_path": self.vault_issue_path,
        }


STABILITY_TARGETS = {
    "ccf-b-matrix": PublicationStabilityTarget(
        name="ccf-b-matrix",
        display_name="CCF-B/Q3 stability matrix",
        min_cycles=3,
        min_release_allowed_cycles=3,
        min_release_pass_rate=1.0,
        min_distinct_real_datasets=3,
        min_distinct_templates=2,
        min_external_templates=1,
        min_external_conference_templates=1,
        min_external_journal_templates=1,
        max_warnings_per_cycle=2,
    ),
    "mvp-matrix": PublicationStabilityTarget(
        name="mvp-matrix",
        display_name="MVP stability smoke matrix",
        min_cycles=1,
        min_release_allowed_cycles=1,
        min_release_pass_rate=1.0,
        min_distinct_real_datasets=1,
        min_distinct_templates=1,
        min_external_templates=0,
        min_external_conference_templates=0,
        min_external_journal_templates=0,
        max_warnings_per_cycle=5,
    ),
}


def audit_publication_stability(
    *,
    cycle_summary_paths: tuple[Path | str, ...],
    target: str = "ccf-b-matrix",
    output_dir: Path | str = Path("runs/publication-stability/latest"),
    vault_root: Path | str | None = None,
    project_id: str | None = None,
) -> PublicationStabilityReport:
    """Gate stable publication-output claims across completed cycle summaries."""

    target_config = _target(target)
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = resolved_output_dir / "publication-stability.json"
    markdown_path = resolved_output_dir / "publication-stability.md"

    cycles = tuple(_cycle_record(Path(path)) for path in cycle_summary_paths)
    checks = _stability_checks(cycles, target_config)
    verdict = (
        PublicationStabilityVerdict.BLOCKED
        if any(check.status is PublicationStabilityCheckStatus.FAIL for check in checks)
        else PublicationStabilityVerdict.PASS
    )
    report = PublicationStabilityReport(
        target=target_config,
        verdict=verdict,
        checks=checks,
        cycles=cycles,
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")

    if vault_root is not None and project_id:
        review_path, issue_path = _write_vault_stability(report, Path(vault_root), project_id)
        report = PublicationStabilityReport(
            target=report.target,
            verdict=report.verdict,
            checks=report.checks,
            cycles=report.cycles,
            output_path=report.output_path,
            markdown_path=report.markdown_path,
            vault_review_path=review_path.as_posix(),
            vault_issue_path=issue_path.as_posix() if issue_path is not None else None,
        )
        output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        markdown_path.write_text(_markdown(report), encoding="utf-8")
    return report


def _target(target: str) -> PublicationStabilityTarget:
    try:
        return STABILITY_TARGETS[target]
    except KeyError as exc:
        known = ", ".join(sorted(STABILITY_TARGETS))
        msg = f"unknown publication stability target {target!r}; expected one of {known}"
        raise ValueError(msg) from exc


def _cycle_record(summary_path: Path) -> CycleStabilityRecord:
    summary = _read_json(summary_path)
    base_dir = summary_path.parent
    publication = _artifact_json(summary, base_dir, "publication_audit")
    evidence_gate = _artifact_json(summary, base_dir, "evidence_gate")
    paper_build = _artifact_json_from_gate(
        summary,
        base_dir,
        summary_key="paper_build",
        gate=evidence_gate,
        gate_path_key="paper_build_path",
    )
    run_record = _run_record(summary, base_dir)
    task_metadata = run_record.get("task_metadata", {}) if isinstance(run_record, dict) else {}
    metrics = run_record.get("metrics", {}).get("values", {}) if isinstance(run_record, dict) else {}
    dataset = _text(
        task_metadata.get("dataset")
        or summary.get("candidate", {}).get("metadata", {}).get("dataset")
        or summary.get("candidate", {}).get("metadata", {}).get("benchmark")
        or "unknown"
    )
    real_dataset = bool(task_metadata.get("real_dataset")) or (
        str(task_metadata.get("dataset_realism", "")).casefold() == "real_public_benchmark"
    )
    if not real_dataset and isinstance(metrics, dict):
        real_dataset = float(metrics.get("test_rows", 0) or 0) >= 1000
    paper_quality = paper_build.get("paper_quality", {}) if isinstance(paper_build, dict) else {}
    template = paper_build.get("template", {}) if isinstance(paper_build, dict) else {}
    paper_template = _text(template.get("id") or paper_build.get("template_id") or "unknown")
    paper_template_source_kind = _text(template.get("source_kind") or paper_build.get("template_source_kind") or "unknown")
    return CycleStabilityRecord(
        cycle_summary_path=summary_path.as_posix(),
        cycle_id=_text(summary.get("cycle_id") or summary_path.parent.name),
        project_id=_text(summary.get("project_id") or "unknown"),
        demo=_text(summary.get("demo", {}).get("demo") or task_metadata.get("demo_task") or "unknown"),
        dataset=dataset,
        real_dataset=real_dataset,
        publication_verdict=_text(publication.get("verdict") or summary.get("publication_audit", {}).get("verdict") or "unknown"),
        publishable=bool(publication.get("publishable")),
        publication_score=_float_or_none(publication.get("score")),
        publication_warning_count=_warning_count(publication),
        evidence_verdict=_text(evidence_gate.get("verdict") or summary.get("evidence_gate", {}).get("verdict") or "unknown"),
        release_allowed=bool(evidence_gate.get("release_allowed")),
        paper_template=paper_template,
        paper_template_source_kind=paper_template_source_kind,
        paper_template_venue_kind=_template_venue_kind(template, template_id=paper_template, source_kind=paper_template_source_kind),
        paper_quality_passed=bool(paper_quality.get("passed")),
    )


def _stability_checks(
    cycles: tuple[CycleStabilityRecord, ...],
    target: PublicationStabilityTarget,
) -> tuple[PublicationStabilityCheck, ...]:
    cycle_refs = tuple(cycle.cycle_summary_path for cycle in cycles)
    release_allowed = tuple(cycle for cycle in cycles if cycle.release_allowed)
    real_datasets = {
        cycle.dataset
        for cycle in release_allowed
        if cycle.real_dataset and cycle.dataset != "unknown"
    }
    templates = {cycle.paper_template for cycle in release_allowed if cycle.paper_template != "unknown"}
    external_templates = {
        cycle.paper_template
        for cycle in release_allowed
        if cycle.paper_template != "unknown"
        and cycle.paper_template_source_kind == "external_fetched"
    }
    external_conference_templates = {
        cycle.paper_template
        for cycle in release_allowed
        if cycle.paper_template != "unknown"
        and cycle.paper_template_source_kind == "external_fetched"
        and cycle.paper_template_venue_kind == "conference"
    }
    external_journal_templates = {
        cycle.paper_template
        for cycle in release_allowed
        if cycle.paper_template != "unknown"
        and cycle.paper_template_source_kind == "external_fetched"
        and cycle.paper_template_venue_kind == "journal"
    }
    failed_cycles = tuple(cycle for cycle in cycles if not cycle.release_allowed)
    warning_over_budget = tuple(
        cycle for cycle in release_allowed if cycle.publication_warning_count > target.max_warnings_per_cycle
    )
    checks = [
        _threshold_check(
            "cycle_count",
            len(cycles),
            target.min_cycles,
            "blocking",
            f"Completed cycles in matrix: {len(cycles)}; target requires at least {target.min_cycles}.",
            cycle_refs,
            "Run additional complete autonomous cycles before claiming stable output.",
        ),
        _threshold_check(
            "release_allowed_cycles",
            len(release_allowed),
            target.min_release_allowed_cycles,
            "blocking",
            "Release-allowed cycles: "
            f"{len(release_allowed)}; target requires at least {target.min_release_allowed_cycles}.",
            tuple(cycle.cycle_summary_path for cycle in release_allowed),
            "Fix blocked cycles or add more passing cycles.",
        ),
        _pass_rate_check(cycles, target),
        _threshold_check(
            "distinct_real_datasets",
            len(real_datasets),
            target.min_distinct_real_datasets,
            "blocking",
            "Distinct real public datasets among release-allowed cycles: "
            f"{len(real_datasets)}; target requires at least {target.min_distinct_real_datasets}.",
            tuple(cycle.cycle_summary_path for cycle in release_allowed if cycle.dataset in real_datasets),
            "Add cycles on different public benchmark datasets.",
        ),
        _threshold_check(
            "paper_template_diversity",
            len(templates),
            target.min_distinct_templates,
            "high",
            f"Distinct LaTeX templates among release-allowed cycles: {len(templates)}; "
            f"target requires at least {target.min_distinct_templates}.",
            tuple(cycle.cycle_summary_path for cycle in release_allowed if cycle.paper_template in templates),
            "Compile accepted manuscripts with at least one additional venue-style template.",
        ),
        _threshold_check(
            "external_template_coverage",
            len(external_templates),
            target.min_external_templates,
            "blocking",
            "External venue/publisher LaTeX templates among release-allowed cycles: "
            f"{len(external_templates)}; target requires at least {target.min_external_templates}.",
            tuple(cycle.cycle_summary_path for cycle in release_allowed if cycle.paper_template in external_templates),
            "Run at least one release-allowed cycle with a fetched venue or publisher template such as IEEEtran, ACM acmart, or Springer Nature.",
        ),
        _threshold_check(
            "external_conference_template_coverage",
            len(external_conference_templates),
            target.min_external_conference_templates,
            "blocking",
            "External conference-style LaTeX templates among release-allowed cycles: "
            f"{len(external_conference_templates)}; target requires at least {target.min_external_conference_templates}.",
            tuple(
                cycle.cycle_summary_path
                for cycle in release_allowed
                if cycle.paper_template in external_conference_templates
            ),
            "Run at least one release-allowed cycle with an ACM acmart or IEEEtran conference template.",
        ),
        _threshold_check(
            "external_journal_template_coverage",
            len(external_journal_templates),
            target.min_external_journal_templates,
            "blocking",
            "External journal-style LaTeX templates among release-allowed cycles: "
            f"{len(external_journal_templates)}; target requires at least {target.min_external_journal_templates}.",
            tuple(
                cycle.cycle_summary_path
                for cycle in release_allowed
                if cycle.paper_template in external_journal_templates
            ),
            "Run at least one release-allowed cycle with an external journal template such as Springer Nature.",
        ),
        _failed_cycle_check(failed_cycles),
        _paper_quality_check(release_allowed),
        _warning_budget_check(warning_over_budget, target),
    ]
    return tuple(checks)


def _threshold_check(
    check_id: str,
    actual: int,
    required: int,
    severity: str,
    message: str,
    evidence_refs: tuple[str, ...],
    next_action: str,
) -> PublicationStabilityCheck:
    status = (
        PublicationStabilityCheckStatus.PASS
        if actual >= required
        else PublicationStabilityCheckStatus.FAIL
    )
    return PublicationStabilityCheck(check_id, status, severity, message, evidence_refs, None if status is PublicationStabilityCheckStatus.PASS else next_action)


def _pass_rate_check(
    cycles: tuple[CycleStabilityRecord, ...],
    target: PublicationStabilityTarget,
) -> PublicationStabilityCheck:
    pass_rate = 0.0 if not cycles else sum(1 for cycle in cycles if cycle.release_allowed) / len(cycles)
    status = (
        PublicationStabilityCheckStatus.PASS
        if pass_rate >= target.min_release_pass_rate
        else PublicationStabilityCheckStatus.FAIL
    )
    return PublicationStabilityCheck(
        "release_pass_rate",
        status,
        "blocking",
        f"Release pass rate is {pass_rate:.3f}; target requires at least {target.min_release_pass_rate:.3f}.",
        tuple(cycle.cycle_summary_path for cycle in cycles),
        None if status is PublicationStabilityCheckStatus.PASS else "Resolve every blocked cycle before claiming stable publication output.",
    )


def _failed_cycle_check(
    failed_cycles: tuple[CycleStabilityRecord, ...],
) -> PublicationStabilityCheck:
    status = PublicationStabilityCheckStatus.PASS if not failed_cycles else PublicationStabilityCheckStatus.FAIL
    message = (
        "Every provided cycle is release-allowed."
        if not failed_cycles
        else f"{len(failed_cycles)} provided cycles are not release-allowed."
    )
    return PublicationStabilityCheck(
        "no_failed_cycles",
        status,
        "blocking",
        message,
        tuple(cycle.cycle_summary_path for cycle in failed_cycles),
        None if status is PublicationStabilityCheckStatus.PASS else "Inspect failed publication/evidence gates and rerun the cycle.",
    )


def _paper_quality_check(
    release_allowed: tuple[CycleStabilityRecord, ...],
) -> PublicationStabilityCheck:
    failed = tuple(cycle for cycle in release_allowed if not cycle.paper_quality_passed)
    status = PublicationStabilityCheckStatus.PASS if not failed else PublicationStabilityCheckStatus.FAIL
    return PublicationStabilityCheck(
        "paper_quality_all_releases",
        status,
        "blocking",
        (
            "Every release-allowed cycle has paper_quality.passed=true."
            if not failed
            else f"{len(failed)} release-allowed cycles lack passing paper quality evidence."
        ),
        tuple(cycle.cycle_summary_path for cycle in failed),
        None if status is PublicationStabilityCheckStatus.PASS else "Rebuild manuscripts until paper quality gates pass.",
    )


def _warning_budget_check(
    warning_over_budget: tuple[CycleStabilityRecord, ...],
    target: PublicationStabilityTarget,
) -> PublicationStabilityCheck:
    status = PublicationStabilityCheckStatus.PASS if not warning_over_budget else PublicationStabilityCheckStatus.WARNING
    return PublicationStabilityCheck(
        "publication_warning_budget",
        status,
        "medium",
        (
            f"Every release-allowed cycle has at most {target.max_warnings_per_cycle} publication-audit warnings."
            if not warning_over_budget
            else f"{len(warning_over_budget)} cycles exceed {target.max_warnings_per_cycle} warnings."
        ),
        tuple(cycle.cycle_summary_path for cycle in warning_over_budget),
        None if status is PublicationStabilityCheckStatus.PASS else "Reduce source, novelty, and related-work warnings before broad release claims.",
    )


def _artifact_json(summary: dict[str, Any], base_dir: Path, key: str) -> dict[str, Any]:
    value = summary.get(key, {})
    if not isinstance(value, dict):
        return {}
    for path_key in ("json_path", "output_path"):
        raw_path = value.get(path_key)
        artifact = _artifact_json_from_path(raw_path, base_dir)
        if artifact is not None:
            return artifact
    return value


def _artifact_json_from_gate(
    summary: dict[str, Any],
    base_dir: Path,
    *,
    summary_key: str,
    gate: dict[str, Any],
    gate_path_key: str,
) -> dict[str, Any]:
    gate_artifact = _artifact_json_from_path(gate.get(gate_path_key), base_dir)
    if gate_artifact is not None:
        return gate_artifact
    return _artifact_json(summary, base_dir, summary_key)


def _artifact_json_from_path(raw_path: Any, base_dir: Path) -> dict[str, Any] | None:
    if isinstance(raw_path, str) and raw_path:
        path = _resolve_path(raw_path, base_dir)
        if path.is_file():
            return _read_json(path)
    return None


def _run_record(summary: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    demo = summary.get("demo", {})
    if isinstance(demo, dict):
        raw_path = demo.get("run_record_path")
        if isinstance(raw_path, str):
            path = _resolve_path(raw_path, base_dir)
            if path.is_file():
                return _read_json(path)
        experiment_dir = demo.get("experiment_dir")
        if isinstance(experiment_dir, str):
            path = _resolve_path(experiment_dir, base_dir) / "run" / "run-record.json"
            if path.is_file():
                return _read_json(path)
    return {}


def _warning_count(publication: dict[str, Any]) -> int:
    checks = publication.get("checks", [])
    if not isinstance(checks, list):
        return 0
    return sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "warning")


def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return base_dir / path


def _read_json(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return {str(key): value for key, value in data.items()}


def _text(value: Any) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _template_venue_kind(
    template: dict[str, Any],
    *,
    template_id: str,
    source_kind: str,
) -> str:
    explicit = template.get("venue_kind") or template.get("template_venue_kind")
    if isinstance(explicit, str) and explicit in {"conference", "journal", "generic"}:
        return explicit
    if source_kind == "built_in_generic":
        return "generic"
    haystack = " ".join(
        _text(template.get(key))
        for key in ("id", "display_name", "document_class", "class_file")
    )
    haystack = f"{template_id} {haystack}".casefold()
    if any(marker in haystack for marker in ("conference", "sigconf", "ieeetran", "acmart")):
        return "conference"
    if any(marker in haystack for marker in ("journal", "springer", "sn-jnl", "jnl")):
        return "journal"
    return "unknown"


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _markdown(report: PublicationStabilityReport) -> str:
    lines = [
        "# Publication Stability Matrix",
        "",
        f"- Target: `{report.target.display_name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Stable: `{str(report.stable).lower()}`",
        f"- Score: `{report.score:.3f}`",
        f"- JSON: `{report.output_path}`",
        f"- Vault review: `{report.vault_review_path or 'not written'}`",
        f"- Vault issue: `{report.vault_issue_path or 'not written'}`",
        "",
        "## Target Gates",
        "",
        f"- Minimum cycles: `{report.target.min_cycles}`",
        f"- Minimum release-allowed cycles: `{report.target.min_release_allowed_cycles}`",
        f"- Minimum release pass rate: `{report.target.min_release_pass_rate:.3f}`",
        f"- Minimum distinct real datasets: `{report.target.min_distinct_real_datasets}`",
        f"- Minimum distinct LaTeX templates: `{report.target.min_distinct_templates}`",
        f"- Minimum external venue/publisher templates: `{report.target.min_external_templates}`",
        f"- Minimum external conference templates: `{report.target.min_external_conference_templates}`",
        f"- Minimum external journal templates: `{report.target.min_external_journal_templates}`",
        f"- Maximum publication warnings per cycle: `{report.target.max_warnings_per_cycle}`",
        "",
        "## Cycles",
        "",
        "| Cycle | Demo | Dataset | Real data | Publishable | Release | Template | Source kind | Venue kind | Warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for cycle in report.cycles:
        lines.append(
            f"| `{cycle.cycle_id}` | `{cycle.demo}` | `{cycle.dataset}` | "
            f"`{str(cycle.real_dataset).lower()}` | `{str(cycle.publishable).lower()}` | "
            f"`{str(cycle.release_allowed).lower()}` | `{cycle.paper_template}` | "
            f"`{cycle.paper_template_source_kind}` | "
            f"`{cycle.paper_template_venue_kind}` | "
            f"`{cycle.publication_warning_count}` |"
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Status | Severity | Evidence | Message | Next action |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for check in report.checks:
        evidence = ", ".join(f"`{ref}`" for ref in check.evidence_refs) or "`none`"
        lines.append(
            f"| `{check.check_id}` | `{check.status.value}` | `{check.severity}` | "
            f"{evidence} | {check.message} | {check.next_action or 'None'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `pass` means the provided matrix supports a stable-publication-output claim for the configured target.",
            "- `blocked` means the system must not claim stable CCF-B/Q3 output across topics yet.",
            "- This gate evaluates repeated cycle evidence; it does not replace per-cycle publication audit or evidence gate checks.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_vault_stability(
    report: PublicationStabilityReport,
    vault_root: Path,
    project_id: str,
) -> tuple[Path, Path | None]:
    store = MarkdownKnowledgeStore(vault_root)
    now = datetime.now(timezone.utc)
    review_entry = KnowledgeEntry(
        entry_id=f"publication_stability_{project_id}",
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title="Publication stability matrix",
        tags=["publication-stability", report.verdict.value],
        keywords=["publication-stability", report.target.name, report.verdict.value],
        source_refs=[report.output_path, report.markdown_path, *[cycle.cycle_summary_path for cycle in report.cycles]],
        related_task_ids=["publication-stability"],
        body=_markdown(report),
        created_at=now,
        updated_at=now,
    )
    review_path = store.write_entry(
        Path("projects") / project_id / "review" / "publication-stability.md",
        review_entry,
    )
    issue_path = None
    if report.verdict is PublicationStabilityVerdict.BLOCKED:
        failed_checks = [check for check in report.checks if check.status is PublicationStabilityCheckStatus.FAIL]
        issue_entry = KnowledgeEntry(
            entry_id=f"publication_stability_issue_{project_id}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            project_id=project_id,
            title="Publication stability blockers",
            tags=["open", "publication-stability", report.verdict.value],
            keywords=["publication-stability", "quality-gate", report.target.name],
            source_refs=[report.output_path, report.markdown_path],
            links=[review_entry.entry_id],
            related_task_ids=["publication-stability"],
            body=_issue_body(report, review_entry.entry_id, failed_checks),
            created_at=now,
            updated_at=now,
        )
        issue_path = store.write_entry(
            Path("projects") / project_id / "issues" / "publication-stability.md",
            issue_entry,
        )
    return review_path, issue_path


def _issue_body(
    report: PublicationStabilityReport,
    review_entry_id: str,
    failed_checks: list[PublicationStabilityCheck],
) -> str:
    lines = [
        "# Publication Stability Blockers",
        "",
        f"- Review note: [[{review_entry_id}]]",
        f"- Target: `{report.target.name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Stable: `{str(report.stable).lower()}`",
        "",
        "## Failed Checks",
        "",
    ]
    if not failed_checks:
        lines.append("- No failed checks; inspect warnings.")
    for check in failed_checks:
        lines.append(f"- `{check.check_id}`: {check.message} Next: {check.next_action or 'None'}")
    lines.extend(
        [
            "",
            "## Required Next Action",
            "",
            "- Run additional real public benchmark cycles, include release-allowed external conference and journal LaTeX templates, and rerun this matrix before claiming stable CCF-B/Q3 output.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
