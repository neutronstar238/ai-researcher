"""Physical evidence gate for autonomous research cycle release decisions."""

from __future__ import annotations

import json
import re
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


class EvidenceGateVerdict(str, Enum):
    """Release decision for a completed research cycle."""

    PASS = "pass"
    BLOCKED = "blocked"


class EvidenceGateCheckStatus(str, Enum):
    """Status for one physical evidence check."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class EvidenceGateCheck:
    """One file-backed release gate check."""

    check_id: str
    status: EvidenceGateCheckStatus
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
class EvidenceLifecycleStage:
    """One SCALE-lite lifecycle stage backed by physical artifacts."""

    stage_id: str
    label: str
    status: EvidenceGateCheckStatus
    required: bool
    evidence_refs: tuple[str, ...] = ()
    missing_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "label": self.label,
            "status": self.status.value,
            "required": self.required,
            "evidence_refs": list(self.evidence_refs),
            "missing_refs": list(self.missing_refs),
        }


@dataclass(frozen=True)
class EvidenceGateReport:
    """Physical evidence gate output."""

    verdict: EvidenceGateVerdict
    checks: tuple[EvidenceGateCheck, ...]
    cycle_summary_path: str
    output_path: str
    markdown_path: str
    review_path: str | None
    publication_audit_path: str | None
    paper_build_path: str | None
    lifecycle_trace: tuple[EvidenceLifecycleStage, ...] = ()
    vault_review_path: str | None = None
    vault_issue_path: str | None = None

    @property
    def release_allowed(self) -> bool:
        return self.verdict is EvidenceGateVerdict.PASS

    @property
    def failed_check_count(self) -> int:
        return sum(1 for check in self.checks if check.status is EvidenceGateCheckStatus.FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "release_allowed": self.release_allowed,
            "failed_check_count": self.failed_check_count,
            "cycle_summary_path": self.cycle_summary_path,
            "review_path": self.review_path,
            "publication_audit_path": self.publication_audit_path,
            "paper_build_path": self.paper_build_path,
            "lifecycle_trace": [stage.to_dict() for stage in self.lifecycle_trace],
            "output_path": self.output_path,
            "markdown_path": self.markdown_path,
            "vault_review_path": self.vault_review_path,
            "vault_issue_path": self.vault_issue_path,
            "checks": [check.to_dict() for check in self.checks],
        }


def run_evidence_gate(
    *,
    cycle_summary_path: Path | str,
    output_dir: Path | str | None = None,
    review_path: Path | str | None = None,
    publication_audit_path: Path | str | None = None,
    paper_build_path: Path | str | None = None,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
    require_review_pass: bool = True,
    require_publication_pass: bool = True,
    require_paper_build: bool = True,
) -> EvidenceGateReport:
    """Run a file-backed release gate over a completed autonomous cycle."""

    summary_path = Path(cycle_summary_path)
    base_dir = summary_path.parent
    resolved_output_dir = Path(output_dir) if output_dir is not None else base_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = resolved_output_dir / "evidence-gate.json"
    markdown_path = resolved_output_dir / "evidence-gate.md"

    checks: list[EvidenceGateCheck] = []
    summary, summary_error = _read_json_if_exists(summary_path)
    if summary_error:
        checks.append(
            EvidenceGateCheck(
                "cycle_summary_readable",
                EvidenceGateCheckStatus.FAIL,
                "blocking",
                f"Cycle summary could not be read as a JSON object: {summary_error}",
                (summary_path.as_posix(),),
                "Rerun the cycle or provide the correct cycle-summary.json path.",
            )
        )
    else:
        checks.append(
            EvidenceGateCheck(
                "cycle_summary_readable",
                EvidenceGateCheckStatus.PASS,
                "blocking",
                "Cycle summary is a readable JSON object.",
                (summary_path.as_posix(),),
            )
        )
        checks.extend(_cycle_artifact_checks(summary, base_dir))
        checks.extend(
            _review_checks(
                summary,
                base_dir,
                review_path=review_path,
                require_review_pass=require_review_pass,
            )
        )

    resolved_review_path = _review_artifact_path(summary, review_path)
    audit_path = _publication_audit_path(summary, publication_audit_path)
    checks.extend(
        _publication_audit_checks(
            audit_path,
            base_dir,
            summary,
            require_publication_pass=require_publication_pass,
        )
    )
    build_path = _paper_build_path(summary, paper_build_path)
    checks.extend(
        _paper_build_checks(
            build_path,
            base_dir,
            require_paper_build=require_paper_build,
        )
    )
    lifecycle_trace: tuple[EvidenceLifecycleStage, ...] = ()
    if not summary_error:
        lifecycle_trace = _lifecycle_trace(
            summary,
            base_dir,
            publication_audit_path=audit_path,
            paper_build_path=build_path,
            review_path=review_path,
            require_review_pass=require_review_pass,
            require_publication_pass=require_publication_pass,
            require_paper_build=require_paper_build,
        )
        checks.append(_lifecycle_trace_check(lifecycle_trace))

    verdict = _gate_verdict(checks)
    report = EvidenceGateReport(
        verdict=verdict,
        checks=tuple(checks),
        cycle_summary_path=summary_path.as_posix(),
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        review_path=_path_text(resolved_review_path),
        publication_audit_path=_path_text(audit_path),
        paper_build_path=_path_text(build_path),
        lifecycle_trace=lifecycle_trace,
    )
    if vault_root is not None and project_id:
        review_path, issue_path = _vault_gate_paths(report, Path(vault_root), project_id)
        report = EvidenceGateReport(
            verdict=report.verdict,
            checks=report.checks,
            cycle_summary_path=report.cycle_summary_path,
            output_path=report.output_path,
            markdown_path=report.markdown_path,
            review_path=report.review_path,
            publication_audit_path=report.publication_audit_path,
            paper_build_path=report.paper_build_path,
            lifecycle_trace=report.lifecycle_trace,
            vault_review_path=review_path.as_posix(),
            vault_issue_path=issue_path.as_posix() if issue_path is not None else None,
        )
    _write_report_files(report)

    if vault_root is not None and project_id:
        _write_vault_gate(report, Path(vault_root), project_id)
    return report


def _cycle_artifact_checks(
    summary: dict[str, Any],
    base_dir: Path,
) -> list[EvidenceGateCheck]:
    demo = _dict(summary.get("demo"))
    literature = _dict(summary.get("literature"))
    similarity = _dict(summary.get("similarity"))
    experiment_dir = _nested(summary, ("demo", "experiment_dir"))
    run_record = _nested(summary, ("demo", "run_record_path"))
    if not _text(run_record) and _text(experiment_dir):
        run_record = Path(_text(experiment_dir)) / "run" / "run-record.json"

    checks = [
        _artifact_check("candidate_record", summary.get("candidate_path"), base_dir),
        _artifact_check("literature_summary", literature.get("summary_path"), base_dir),
        _artifact_check("similarity_summary", similarity.get("summary_path"), base_dir),
        _artifact_check("experiment_directory", experiment_dir, base_dir, kind="dir"),
        _artifact_check("experiment_report", demo.get("report_path"), base_dir),
        _artifact_check("validation_report", demo.get("validation_json_path"), base_dir),
        _artifact_check("evidence_map", demo.get("evidence_map_path"), base_dir),
        _artifact_check("run_record", run_record, base_dir),
    ]
    checks.extend(_reproduction_checks(summary, base_dir))
    return checks


def _reproduction_checks(
    summary: dict[str, Any],
    base_dir: Path,
) -> list[EvidenceGateCheck]:
    reproduction = _dict(summary.get("reproduction_check"))
    checks = [
        _artifact_check("reproduction_report", reproduction.get("json_path"), base_dir),
        _artifact_check("reproduction_markdown", reproduction.get("markdown_path"), base_dir),
    ]
    status_text = _text(reproduction.get("status"))
    exit_code = reproduction.get("exit_code")
    run_records = tuple(
        _resolve_path(path_text, base_dir)
        for path_text in _text_sequence(reproduction.get("run_record_paths"))
    )
    validation_reports = tuple(
        _resolve_path(path_text, base_dir)
        for path_text in _text_sequence(reproduction.get("validation_json_paths"))
    )
    run_records_ok = bool(run_records) and all(
        path is not None and path.exists() and path.is_file() for path in run_records
    )
    validation_reports_ok = bool(validation_reports) and all(
        path is not None and path.exists() and path.is_file() for path in validation_reports
    )
    passed = (
        status_text == "passed"
        and exit_code == 0
        and run_records_ok
        and validation_reports_ok
    )
    evidence_refs = tuple(
        ref
        for ref in (
            _path_text(reproduction.get("json_path")) or "cycle_summary.reproduction_check",
            *[
                path.as_posix() if path is not None else "missing_reproduction_run_record"
                for path in run_records
            ],
            *[
                path.as_posix()
                if path is not None
                else "missing_reproduction_validation_report"
                for path in validation_reports
            ],
        )
        if ref
    )
    checks.append(
        EvidenceGateCheck(
            "reproduction_rerun_gate",
            EvidenceGateCheckStatus.PASS if passed else EvidenceGateCheckStatus.FAIL,
            "blocking",
            (
                "Reproduction rerun gate "
                f"status={status_text or 'missing'}, exit_code={exit_code}, "
                f"run_records={len(run_records)}, "
                f"validation_reports={len(validation_reports)}, "
                f"run_records_exist={str(run_records_ok).lower()}, "
                f"validation_reports_exist={str(validation_reports_ok).lower()}."
            ),
            evidence_refs,
            None
            if passed
            else (
                "Rerun the experiment from a command-line entry point and preserve "
                "fresh run-record and validation-report artifacts before release."
            ),
        )
    )
    return checks


def _review_checks(
    summary: dict[str, Any],
    base_dir: Path,
    *,
    review_path: Path | str | None,
    require_review_pass: bool,
) -> list[EvidenceGateCheck]:
    review = _review_gate_info(summary, review_path, base_dir)
    review_source = _path_text(_review_artifact_path(summary, review_path)) or "cycle_summary.review"
    status = _text(review.get("status"))
    verdict = _text(review.get("verdict"))
    quality = review.get("quality_score")
    passed = status == "passed" and verdict == "pass"
    severity = "blocking" if require_review_pass else "medium"
    check_status = EvidenceGateCheckStatus.PASS if passed else EvidenceGateCheckStatus.FAIL
    if not require_review_pass and not passed:
        check_status = EvidenceGateCheckStatus.WARNING
    checks = [
        EvidenceGateCheck(
            "review_gate",
            check_status,
            severity,
            (
                "LLM evidence review gate "
                f"status={status or 'missing'}, verdict={verdict or 'missing'}, "
                f"quality_score={quality if quality is not None else 'missing'}."
            ),
            (review_source,),
            None
            if passed
            else "Run an evidence-constrained review and resolve fail/needs_revision verdicts.",
        )
    ]
    output_path = _review_artifact_path(summary, review_path)
    if status == "passed" or require_review_pass:
        checks.append(_artifact_check("review_artifact", output_path, base_dir))
    return checks


def _lifecycle_trace(
    summary: dict[str, Any],
    base_dir: Path,
    *,
    publication_audit_path: Path | str | None,
    paper_build_path: Path | str | None,
    review_path: Path | str | None,
    require_review_pass: bool,
    require_publication_pass: bool,
    require_paper_build: bool,
) -> tuple[EvidenceLifecycleStage, ...]:
    demo = _dict(summary.get("demo"))
    literature = _dict(summary.get("literature"))
    similarity = _dict(summary.get("similarity"))
    reproduction = _dict(summary.get("reproduction_check"))
    experiment_dir = _resolve_path(_nested(summary, ("demo", "experiment_dir")), base_dir)
    review_artifact_path = _review_artifact_path(summary, review_path)
    paper_pdf_path = _paper_pdf_path(paper_build_path, base_dir)

    stage_specs: tuple[tuple[str, str, bool, tuple[tuple[object, str], ...]], ...] = (
        (
            "define",
            "Requirements and novelty context",
            True,
            (
                (summary.get("candidate_path"), "candidate record"),
                (literature.get("summary_path"), "literature summary"),
                (similarity.get("summary_path"), "similarity summary"),
            ),
        ),
        (
            "plan",
            "Experiment plan and configuration",
            True,
            (
                (_experiment_child(experiment_dir, "README.md"), "experiment README"),
                (_experiment_child(experiment_dir, "config.yaml"), "experiment config"),
            ),
        ),
        (
            "build",
            "Runnable experiment code",
            True,
            ((_experiment_child(experiment_dir, "run.py"), "experiment entrypoint"),),
        ),
        (
            "verify",
            "Test and validation evidence",
            True,
            (
                (demo.get("validation_json_path"), "validation report"),
                (demo.get("evidence_map_path"), "evidence map"),
                (reproduction.get("json_path"), "reproduction report"),
            ),
        ),
        (
            "review",
            "Review and publication audit evidence",
            require_review_pass or require_publication_pass,
            (
                (review_artifact_path, "LLM evidence review"),
                (publication_audit_path, "publication audit"),
            ),
        ),
        (
            "ship",
            "Release and paper artifact evidence",
            require_paper_build,
            (
                (paper_build_path, "paper build JSON"),
                (paper_pdf_path, "compiled paper PDF"),
            ),
        ),
    )

    return tuple(
        _lifecycle_stage(stage_id, label, required, specs, base_dir)
        for stage_id, label, required, specs in stage_specs
    )


def _lifecycle_stage(
    stage_id: str,
    label: str,
    required: bool,
    specs: tuple[tuple[object, str], ...],
    base_dir: Path,
) -> EvidenceLifecycleStage:
    evidence_refs: list[str] = []
    missing_refs: list[str] = []
    for path_value, description in specs:
        resolved = _resolve_path(path_value, base_dir)
        ref = _path_text(path_value) or description
        if resolved is not None and resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            evidence_refs.append(resolved.as_posix())
        else:
            missing_refs.append(ref)
    if not missing_refs:
        status = EvidenceGateCheckStatus.PASS
    elif required:
        status = EvidenceGateCheckStatus.FAIL
    else:
        status = EvidenceGateCheckStatus.WARNING
    return EvidenceLifecycleStage(
        stage_id=stage_id,
        label=label,
        status=status,
        required=required,
        evidence_refs=tuple(evidence_refs),
        missing_refs=tuple(missing_refs),
    )


def _lifecycle_trace_check(
    stages: tuple[EvidenceLifecycleStage, ...],
) -> EvidenceGateCheck:
    missing_required = tuple(
        stage for stage in stages if stage.required and stage.status is EvidenceGateCheckStatus.FAIL
    )
    warning_stages = tuple(
        stage for stage in stages if stage.status is EvidenceGateCheckStatus.WARNING
    )
    if missing_required:
        status = EvidenceGateCheckStatus.FAIL
        severity = "blocking"
    elif warning_stages:
        status = EvidenceGateCheckStatus.WARNING
        severity = "medium"
    else:
        status = EvidenceGateCheckStatus.PASS
        severity = "blocking"
    stage_summary = "; ".join(
        f"{stage.stage_id}={stage.status.value}"
        + (f" missing({', '.join(stage.missing_refs)})" if stage.missing_refs else "")
        for stage in stages
    )
    evidence_refs = tuple(ref for stage in stages for ref in stage.evidence_refs)
    return EvidenceGateCheck(
        "lifecycle_trace_gate",
        status,
        severity,
        f"SCALE-lite lifecycle trace: {stage_summary}.",
        evidence_refs,
        None
        if status is EvidenceGateCheckStatus.PASS
        else (
            "Restore the missing define/plan/build/verify/review/ship evidence files "
            "before release or paper-ready claims."
        ),
    )


def _publication_audit_checks(
    path_value: Path | str | None,
    base_dir: Path,
    summary: dict[str, Any],
    *,
    require_publication_pass: bool,
) -> list[EvidenceGateCheck]:
    checks = [_artifact_check("publication_audit_artifact", path_value, base_dir)]
    audit_path = _resolve_path(path_value, base_dir)
    audit_payload = _dict(summary.get("publication_audit"))
    if audit_path is not None and audit_path.exists():
        payload, error = _read_json_if_exists(audit_path)
        if error:
            checks.append(
                EvidenceGateCheck(
                    "publication_audit_readable",
                    EvidenceGateCheckStatus.FAIL,
                    "blocking",
                    f"Publication audit is not readable JSON: {error}",
                    (audit_path.as_posix(),),
                    "Regenerate publication-audit.json before release.",
                )
            )
        else:
            checks.append(
                EvidenceGateCheck(
                    "publication_audit_readable",
                    EvidenceGateCheckStatus.PASS,
                    "blocking",
                    "Publication audit JSON is readable.",
                    (audit_path.as_posix(),),
                )
            )
            audit_payload = payload

    publishable = audit_payload.get("publishable") is True
    verdict = _text(audit_payload.get("verdict"))
    passed = publishable and verdict == "pass"
    status = EvidenceGateCheckStatus.PASS if passed else EvidenceGateCheckStatus.FAIL
    severity = "blocking" if require_publication_pass else "medium"
    if not require_publication_pass and not passed:
        status = EvidenceGateCheckStatus.WARNING
    checks.append(
        EvidenceGateCheck(
            "publication_release_gate",
            status,
            severity,
            (
                "Publication audit gate "
                f"verdict={verdict or 'missing'}, publishable={str(publishable).lower()}."
            ),
            (_path_text(path_value) or "cycle_summary.publication_audit",),
            None
            if passed
            else "Do not release as paper-ready until publication-audit reports pass/publishable.",
        )
    )
    return checks


def _paper_build_checks(
    path_value: Path | str | None,
    base_dir: Path,
    *,
    require_paper_build: bool,
) -> list[EvidenceGateCheck]:
    if not _text(path_value) and not require_paper_build:
        return [
            EvidenceGateCheck(
                "paper_build_gate",
                EvidenceGateCheckStatus.WARNING,
                "medium",
                "No paper-build JSON was provided; paper artifact gate was not enforced.",
                ("paper_build_path",),
                "Provide --paper-build-json before paper-level release.",
            )
        ]
    checks = [_artifact_check("paper_build_artifact", path_value, base_dir)]
    build_path = _resolve_path(path_value, base_dir)
    build_payload: dict[str, Any] = {}
    if build_path is not None and build_path.exists():
        payload, error = _read_json_if_exists(build_path)
        if error:
            checks.append(
                EvidenceGateCheck(
                    "paper_build_readable",
                    EvidenceGateCheckStatus.FAIL,
                    "blocking",
                    f"Paper build JSON is not readable: {error}",
                    (build_path.as_posix(),),
                    "Regenerate paper-build.json before release.",
                )
            )
        else:
            checks.append(
                EvidenceGateCheck(
                    "paper_build_readable",
                    EvidenceGateCheckStatus.PASS,
                    "blocking",
                    "Paper build JSON is readable.",
                    (build_path.as_posix(),),
                )
            )
            build_payload = payload

    status_text = _text(build_payload.get("status"))
    pdf_path = _resolve_path(build_payload.get("pdf_path"), base_dir)
    pdf_exists = pdf_path is not None and pdf_path.exists() and pdf_path.is_file()
    compiled = status_text == "compiled" and pdf_exists
    status = EvidenceGateCheckStatus.PASS if compiled else EvidenceGateCheckStatus.FAIL
    severity = "blocking" if require_paper_build else "medium"
    if not require_paper_build and not compiled:
        status = EvidenceGateCheckStatus.WARNING
    checks.append(
        EvidenceGateCheck(
            "paper_pdf_gate",
            status,
            severity,
            (
                "Paper build gate "
                f"status={status_text or 'missing'}, pdf_exists={str(pdf_exists).lower()}."
            ),
            (
                build_path.as_posix() if build_path is not None else "paper_build_path",
                pdf_path.as_posix() if pdf_path is not None else "missing_pdf_path",
            ),
            None
            if compiled
            else "Compile the selected LaTeX template to PDF before paper-level release.",
        )
    )
    return checks


def _artifact_check(
    check_id: str,
    path_value: object,
    base_dir: Path,
    *,
    kind: str = "file",
) -> EvidenceGateCheck:
    path = _resolve_path(path_value, base_dir)
    if path is None:
        return EvidenceGateCheck(
            check_id,
            EvidenceGateCheckStatus.FAIL,
            "blocking",
            f"Required {check_id} path is missing from cycle evidence.",
            (_path_text(path_value) or check_id,),
            "Regenerate the cycle and preserve all required evidence artifacts.",
        )
    exists = path.exists()
    kind_ok = (path.is_dir() if kind == "dir" else path.is_file())
    size_ok = kind == "dir" or (exists and path.stat().st_size > 0)
    passed = exists and kind_ok and size_ok
    return EvidenceGateCheck(
        check_id,
        EvidenceGateCheckStatus.PASS if passed else EvidenceGateCheckStatus.FAIL,
        "blocking",
        (
            f"Required {check_id} "
            f"path={path.as_posix()} exists={str(exists).lower()} kind={kind}."
        ),
        (path.as_posix(),),
        None if passed else "Create or restore this evidence artifact before release.",
    )


def _publication_audit_path(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
) -> Path | str | None:
    if explicit_path is not None:
        return explicit_path
    audit = _dict(summary.get("publication_audit"))
    return audit.get("output_path")


def _review_artifact_path(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
) -> Path | str | None:
    if explicit_path is not None:
        return explicit_path
    review = _dict(summary.get("review"))
    return review.get("output_path")


def _review_gate_info(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
    base_dir: Path,
) -> dict[str, Any]:
    if explicit_path is None:
        return _dict(summary.get("review"))

    resolved_path = _resolve_path(explicit_path, base_dir)
    payload, error = _read_json_if_exists(resolved_path or explicit_path)
    if error:
        return {"status": "unreadable", "output_path": _path_text(explicit_path), "error": error}

    quality = _dict(payload.get("quality"))
    parsed = _dict(quality.get("parsed_output"))
    quality_score = quality.get("score")
    if not isinstance(quality_score, int | float):
        quality_score = payload.get("quality_score")
    status = _text(payload.get("status"))
    if not status and isinstance(quality_score, int | float):
        status = "passed" if quality_score >= 0.85 else "below_threshold"
    verdict = _text(payload.get("verdict")) or _text(parsed.get("verdict"))
    return {
        "status": status,
        "verdict": verdict,
        "quality_score": quality_score,
        "output_path": _path_text(explicit_path),
    }


def _paper_build_path(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
) -> Path | str | None:
    if explicit_path is not None:
        return explicit_path
    paper_build = _dict(summary.get("paper_build"))
    return paper_build.get("json_path") or paper_build.get("output_path")


def _paper_pdf_path(path_value: Path | str | None, base_dir: Path) -> Path | str | None:
    build_path = _resolve_path(path_value, base_dir)
    if build_path is None or not build_path.exists():
        return None
    payload, error = _read_json_if_exists(build_path)
    if error:
        return None
    return payload.get("pdf_path")


def _gate_verdict(checks: list[EvidenceGateCheck]) -> EvidenceGateVerdict:
    hard_fail = any(
        check.status is EvidenceGateCheckStatus.FAIL and check.severity == "blocking"
        for check in checks
    )
    return EvidenceGateVerdict.BLOCKED if hard_fail else EvidenceGateVerdict.PASS


def _write_report_files(report: EvidenceGateReport) -> None:
    Path(report.output_path).write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(report.markdown_path).write_text(_markdown(report), encoding="utf-8")


def _markdown(report: EvidenceGateReport) -> str:
    lines = [
        "# Evidence Release Gate",
        "",
        f"- Verdict: `{report.verdict.value}`",
        f"- Release allowed: `{str(report.release_allowed).lower()}`",
        f"- Failed checks: `{report.failed_check_count}`",
        f"- Cycle summary: `{report.cycle_summary_path}`",
        f"- Review: `{report.review_path or 'not provided'}`",
        f"- Publication audit: `{report.publication_audit_path or 'not provided'}`",
        f"- Paper build: `{report.paper_build_path or 'not provided'}`",
        f"- JSON: `{report.output_path}`",
        f"- Vault review: `{report.vault_review_path or 'not written'}`",
        f"- Vault issue: `{report.vault_issue_path or 'not written'}`",
        "",
        "## Policy",
        "",
        "- No release without local evidence artifacts.",
        "- No release without a physical define -> plan -> build -> verify -> review -> ship trace.",
        "- No release without a fresh command-line reproduction rerun.",
        "- No paper-ready claim without a passing publication audit.",
        "- No paper-level artifact claim without a compiled LaTeX PDF.",
        "- Failed gates are blockers, not suggestions.",
        "",
        "## Lifecycle Trace",
        "",
        "| Stage | Status | Required | Evidence | Missing |",
        "| --- | --- | --- | --- | --- |",
    ]
    for stage in report.lifecycle_trace:
        evidence = ", ".join(f"`{ref}`" for ref in stage.evidence_refs) or "`none`"
        missing = ", ".join(f"`{ref}`" for ref in stage.missing_refs) or "`none`"
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{stage.stage_id}`",
                    f"`{stage.status.value}`",
                    f"`{str(stage.required).lower()}`",
                    evidence,
                    missing,
                )
            )
            + " |"
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
            "| "
            + " | ".join(
                (
                    f"`{check.check_id}`",
                    f"`{check.status.value}`",
                    f"`{check.severity}`",
                    evidence,
                    _escape_table(check.message),
                    _escape_table(check.next_action or "None"),
                )
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_vault_gate(
    report: EvidenceGateReport,
    vault_root: Path,
    project_id: str,
) -> tuple[Path, Path | None]:
    store = MarkdownKnowledgeStore(vault_root)
    now = datetime.now(timezone.utc)
    review_path, issue_path = _vault_gate_paths(report, vault_root, project_id)
    slug = _gate_slug(report)
    review_entry = KnowledgeEntry(
        entry_id=f"evidence_gate_{project_id}_{slug}",
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title=f"Evidence release gate {slug}",
        tags=["evidence-gate", report.verdict.value],
        keywords=["evidence-gate", "release-gate", report.verdict.value],
        source_refs=[
            ref
            for ref in (
                report.cycle_summary_path,
                report.review_path,
                report.publication_audit_path,
                report.paper_build_path,
                report.output_path,
                report.markdown_path,
            )
            if ref
        ],
        related_task_ids=["72.1", "74.1"],
        body=_markdown(report),
        created_at=now,
        updated_at=now,
    )
    review_path = store.write_entry(review_path.relative_to(vault_root), review_entry)
    if report.verdict is EvidenceGateVerdict.BLOCKED:
        failed_checks = tuple(
            check for check in report.checks if check.status is EvidenceGateCheckStatus.FAIL
        )
        issue_entry = KnowledgeEntry(
            entry_id=f"evidence_gate_issue_{project_id}_{slug}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            project_id=project_id,
            title=f"Evidence release gate blockers {slug}",
            tags=["open", "evidence-gate", report.verdict.value],
            keywords=["evidence-gate", "release-blocker", "quality-gate"],
            source_refs=[report.output_path, report.markdown_path],
            links=[review_entry.entry_id],
            related_task_ids=["72.1", "74.1"],
            body=_issue_body(report, review_entry.entry_id, failed_checks),
            created_at=now,
            updated_at=now,
        )
        if issue_path is not None:
            issue_path = store.write_entry(issue_path.relative_to(vault_root), issue_entry)
    return review_path, issue_path


def _vault_gate_paths(
    report: EvidenceGateReport,
    vault_root: Path,
    project_id: str,
) -> tuple[Path, Path | None]:
    slug = _gate_slug(report)
    review_path = vault_root / "projects" / project_id / "review" / f"evidence-gate-{slug}.md"
    issue_path = None
    if report.verdict is EvidenceGateVerdict.BLOCKED:
        issue_path = vault_root / "projects" / project_id / "issues" / f"evidence-gate-{slug}.md"
    return review_path, issue_path


def _gate_slug(report: EvidenceGateReport) -> str:
    return _slug(Path(report.cycle_summary_path).parent.name or "cycle")


def _issue_body(
    report: EvidenceGateReport,
    review_entry_id: str,
    failed_checks: tuple[EvidenceGateCheck, ...],
) -> str:
    lines = [
        f"# Evidence release gate blockers for {Path(report.cycle_summary_path).parent.name}",
        "",
        f"- Review note: [[{review_entry_id}]]",
        f"- Verdict: `{report.verdict.value}`",
        f"- Release allowed: `{str(report.release_allowed).lower()}`",
        f"- Issue fingerprint: `evidence-gate:{Path(report.cycle_summary_path).parent.name}`",
        "",
        "## Failed Checks",
        "",
    ]
    for check in failed_checks:
        lines.extend(
            [
                f"### {check.check_id}",
                "",
                f"- Severity: `{check.severity}`",
                f"- Evidence refs: {', '.join(f'`{ref}`' for ref in check.evidence_refs) or '`none`'}",
                f"- Message: {check.message}",
                f"- Next action: {check.next_action or 'None'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _read_json_if_exists(path: Path | str) -> tuple[dict[str, Any], str | None]:
    resolved = Path(path)
    if not resolved.exists():
        return {}, f"{resolved.as_posix()} does not exist"
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(exc)
    if not isinstance(payload, dict):
        return {}, f"expected JSON object in {resolved.as_posix()}"
    return payload, None


def _resolve_path(path_value: object, base_dir: Path) -> Path | None:
    text = _text(path_value)
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend((base_dir / path, Path.cwd() / path))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _nested(payload: dict[str, Any], keys: tuple[str, ...]) -> object:
    value: object = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _experiment_child(experiment_dir: Path | None, name: str) -> Path | None:
    if experiment_dir is None:
        return None
    return experiment_dir / name


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _text_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _path_text(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    return Path(text).as_posix()


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "evidence-gate"
