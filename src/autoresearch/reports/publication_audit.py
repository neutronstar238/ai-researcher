"""Publication-level quality audit for autonomous research cycles."""

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
from autoresearch.schemas import file_hash


class PublicationAuditVerdict(str, Enum):
    """Conservative publication-readiness states."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    FAIL = "fail"


class PublicationAuditCheckStatus(str, Enum):
    """One audit check state."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class PublicationQualityTarget:
    """Minimum bar for a publication-readiness audit."""

    name: str
    display_name: str
    min_score: float
    min_literature_queries: int
    min_literature_documents: int
    min_successful_sources: int
    min_similarity_queries: int
    min_similarity_findings: int
    min_test_rows: int
    require_real_dataset: bool
    require_baseline: bool
    require_ablation: bool
    require_statistical_sanity: bool
    require_novel_contribution: bool
    min_llm_review_quality: float


@dataclass(frozen=True)
class PublicationAuditCheck:
    """One evidence-backed quality check."""

    check_id: str
    status: PublicationAuditCheckStatus
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
class PublicationAuditReport:
    """Publication-readiness audit output."""

    target: PublicationQualityTarget
    verdict: PublicationAuditVerdict
    score: float
    checks: tuple[PublicationAuditCheck, ...]
    cycle_summary_path: str
    output_path: str
    markdown_path: str
    vault_review_path: str | None = None
    vault_issue_path: str | None = None

    @property
    def publishable(self) -> bool:
        return self.verdict is PublicationAuditVerdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {
                "name": self.target.name,
                "display_name": self.target.display_name,
                "min_score": self.target.min_score,
                "min_literature_queries": self.target.min_literature_queries,
                "min_literature_documents": self.target.min_literature_documents,
                "min_successful_sources": self.target.min_successful_sources,
                "min_similarity_queries": self.target.min_similarity_queries,
                "min_similarity_findings": self.target.min_similarity_findings,
                "min_test_rows": self.target.min_test_rows,
                "require_real_dataset": self.target.require_real_dataset,
                "require_baseline": self.target.require_baseline,
                "require_ablation": self.target.require_ablation,
                "require_statistical_sanity": self.target.require_statistical_sanity,
                "require_novel_contribution": self.target.require_novel_contribution,
                "min_llm_review_quality": self.target.min_llm_review_quality,
            },
            "verdict": self.verdict.value,
            "publishable": self.publishable,
            "score": self.score,
            "checks": [check.to_dict() for check in self.checks],
            "cycle_summary_path": self.cycle_summary_path,
            "output_path": self.output_path,
            "markdown_path": self.markdown_path,
            "vault_review_path": self.vault_review_path,
            "vault_issue_path": self.vault_issue_path,
        }


TARGETS: dict[str, PublicationQualityTarget] = {
    "ccf-b": PublicationQualityTarget(
        name="ccf-b",
        display_name="CCF-B-level conference target",
        min_score=0.82,
        min_literature_queries=4,
        min_literature_documents=20,
        min_successful_sources=2,
        min_similarity_queries=4,
        min_similarity_findings=10,
        min_test_rows=1000,
        require_real_dataset=True,
        require_baseline=True,
        require_ablation=True,
        require_statistical_sanity=True,
        require_novel_contribution=True,
        min_llm_review_quality=0.85,
    ),
    "q3-journal": PublicationQualityTarget(
        name="q3-journal",
        display_name="Q3 journal target",
        min_score=0.78,
        min_literature_queries=4,
        min_literature_documents=20,
        min_successful_sources=2,
        min_similarity_queries=4,
        min_similarity_findings=10,
        min_test_rows=1000,
        require_real_dataset=True,
        require_baseline=True,
        require_ablation=True,
        require_statistical_sanity=True,
        require_novel_contribution=True,
        min_llm_review_quality=0.85,
    ),
    "mvp-demo": PublicationQualityTarget(
        name="mvp-demo",
        display_name="MVP loop correctness target",
        min_score=0.70,
        min_literature_queries=1,
        min_literature_documents=1,
        min_successful_sources=1,
        min_similarity_queries=1,
        min_similarity_findings=1,
        min_test_rows=1,
        require_real_dataset=False,
        require_baseline=False,
        require_ablation=False,
        require_statistical_sanity=False,
        require_novel_contribution=False,
        min_llm_review_quality=0.85,
    ),
}

REQUIRED_PAPER_SECTIONS = (
    "abstract",
    "introduction",
    "related work",
    "method",
    "experiments",
    "results",
    "limitations",
    "conclusion",
    "references",
)


def audit_publication_quality(
    *,
    cycle_summary_path: Path | str,
    target: str = "ccf-b",
    output_dir: Path | str | None = None,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
) -> PublicationAuditReport:
    """Audit whether one autonomous cycle is ready to claim publication-level output."""

    summary_path = Path(cycle_summary_path)
    summary = _read_json(summary_path)
    target_config = _target(target)
    resolved_output_dir = Path(output_dir) if output_dir is not None else summary_path.parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    checks = (
        *_literature_checks(summary, target_config),
        *_similarity_checks(summary, summary_path.parent, target_config),
        *_script_and_data_checks(summary, summary_path.parent, target_config),
        *_review_checks(summary, target_config),
        *_manuscript_checks(summary, summary_path.parent),
    )
    verdict = _verdict(checks, target_config)
    score = _score(checks)

    output_path = resolved_output_dir / "publication-audit.json"
    markdown_path = resolved_output_dir / "publication-audit.md"
    report = PublicationAuditReport(
        target=target_config,
        verdict=verdict,
        score=score,
        checks=tuple(checks),
        cycle_summary_path=summary_path.as_posix(),
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")

    if vault_root is not None and project_id:
        review_path, issue_path = _write_vault_audit(report, Path(vault_root), project_id)
        report = PublicationAuditReport(
            target=report.target,
            verdict=report.verdict,
            score=report.score,
            checks=report.checks,
            cycle_summary_path=report.cycle_summary_path,
            output_path=report.output_path,
            markdown_path=report.markdown_path,
            vault_review_path=review_path.as_posix(),
            vault_issue_path=issue_path.as_posix() if issue_path is not None else None,
        )
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")

    return report


def _target(name: str) -> PublicationQualityTarget:
    key = name.strip().lower().replace("_", "-")
    if key in {"ccfb", "ccf-b-level"}:
        key = "ccf-b"
    if key in {"三区", "third-quartile-journal", "q3"}:
        key = "q3-journal"
    try:
        return TARGETS[key]
    except KeyError as exc:
        valid = ", ".join(sorted(TARGETS))
        raise ValueError(f"unknown publication quality target {name!r}; expected one of {valid}") from exc


def _literature_checks(
    summary: dict[str, Any],
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    literature = _dict(summary.get("literature"))
    fetches = _dict_list(literature.get("fetches"))
    successful_sources = _successful_sources(fetches)
    source_errors = [fetch for fetch in fetches if _text(fetch.get("error"))]
    query_count = _int(literature.get("query_count"))
    document_count = _int(literature.get("document_count"))

    checks = [
        _threshold_check(
            "literature_query_breadth",
            query_count,
            target.min_literature_queries,
            "blocking",
            f"Literature query breadth is {query_count}; target requires at least {target.min_literature_queries}.",
            "Expand query variants from title, gap, methods, datasets, baselines, negative evidence, and vault context.",
            ("cycle_summary.literature.query_count",),
        ),
        _threshold_check(
            "literature_document_breadth",
            document_count,
            target.min_literature_documents,
            "blocking",
            f"Retrieved normalized literature documents: {document_count}; target requires at least {target.min_literature_documents}.",
            "Run broader ArXiv/Semantic Scholar searches and preserve every source-backed paper before novelty claims.",
            ("cycle_summary.literature.document_count",),
        ),
        _threshold_check(
            "literature_source_breadth",
            len(successful_sources),
            target.min_successful_sources,
            "blocking",
            f"Successful literature sources: {', '.join(successful_sources) or 'none'}; target requires {target.min_successful_sources}.",
            "Resolve source failures or add another public academic source before publication-level novelty claims.",
            ("cycle_summary.literature.fetches",),
        ),
    ]
    if source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}" for fetch in source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "literature_source_errors",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Some literature sources failed: {errors}",
                ("cycle_summary.literature.fetches",),
                "Treat failed source coverage as a novelty-risk blocker until rerun with rate limits/API keys.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "literature_source_errors",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No literature source errors were recorded.",
                ("cycle_summary.literature.fetches",),
            )
        )
    return checks


def _similarity_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    similarity = _dict(summary.get("similarity"))
    fetches = _dict_list(similarity.get("fetches"))
    successful_sources = _successful_sources(fetches)
    source_errors = [fetch for fetch in fetches if _text(fetch.get("error"))]
    query_count = len({_text(fetch.get("query")) for fetch in fetches if _text(fetch.get("query"))})
    finding_count = _int(similarity.get("finding_count"))
    classifications = _similarity_classifications(similarity, base_dir)
    direct_duplicates = classifications.get("direct_duplicate", 0)
    adjacent_work = classifications.get("adjacent_work", 0)
    unknown_findings = classifications.get("unknown", 0)
    classified_findings = sum(
        count for classification, count in classifications.items() if classification != "unknown"
    )

    checks = [
        _threshold_check(
            "similarity_query_breadth",
            query_count,
            target.min_similarity_queries,
            "blocking",
            f"Similarity-check query breadth is {query_count}; target requires at least {target.min_similarity_queries}.",
            "Search candidate title, research gap, method/dataset terms, baselines, negative results, and vault context.",
            ("cycle_summary.similarity.fetches",),
        ),
        _threshold_check(
            "similarity_finding_breadth",
            finding_count,
            target.min_similarity_findings,
            "blocking",
            f"Similarity findings: {finding_count}; target requires at least {target.min_similarity_findings}.",
            "Collect enough adjacent-work evidence before claiming novelty or cross-validation coverage.",
            ("cycle_summary.similarity.finding_count",),
        ),
        _threshold_check(
            "similarity_source_breadth",
            len(successful_sources),
            target.min_successful_sources,
            "blocking",
            f"Successful similarity-check sources: {', '.join(successful_sources) or 'none'}; target requires {target.min_successful_sources}.",
            "Resolve source failures or add another source before publication-level novelty claims.",
            ("cycle_summary.similarity.fetches",),
        ),
    ]
    if source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}" for fetch in source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "similarity_source_errors",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Some similarity-check sources failed: {errors}",
                ("cycle_summary.similarity.fetches",),
                "Rerun cross-search after rate-limit cooldown/API-key setup; do not treat missing sources as negative evidence.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_source_errors",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No similarity-check source errors were recorded.",
                ("cycle_summary.similarity.fetches",),
            )
        )
    if target.require_novel_contribution and finding_count > 0 and classified_findings <= 0:
        checks.append(
            PublicationAuditCheck(
                "similarity_classification_coverage",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Similarity findings are all unclassified or unknown: unknown={unknown_findings}, classified={classified_findings}.",
                ("cycle_summary.similarity.summary_path",),
                "Resolve unknown similarity classifications into direct_duplicate, adjacent_work, or another supported evidence-backed category before claiming novelty.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_classification_coverage",
                PublicationAuditCheckStatus.PASS,
                "info",
                f"Similarity classification coverage includes {classified_findings} non-unknown findings and {unknown_findings} unknown findings.",
                ("cycle_summary.similarity.summary_path",),
            )
        )
    if direct_duplicates:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                f"Similarity check found {direct_duplicates} direct duplicate candidates.",
                ("cycle_summary.similarity.summary_path",),
                "Reject or substantially reposition the candidate before further experiments.",
            )
        )
    elif adjacent_work:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.WARNING,
                "high",
                f"Similarity check found {adjacent_work} adjacent-work findings that need positioning.",
                ("cycle_summary.similarity.summary_path",),
                "Write a related-work comparison before publication review.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No direct duplicate was detected in the current similarity metadata.",
                ("cycle_summary.similarity.summary_path",),
            )
        )
    return checks


def _script_and_data_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    demo = _dict(summary.get("demo"))
    experiment_dir = _resolve_path(demo.get("experiment_dir"), base_dir)
    run_record_path = experiment_dir / "run" / "run-record.json" if experiment_dir else None
    if run_record_path is None or not run_record_path.exists():
        return [
            PublicationAuditCheck(
                "script_data_verification",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                "Run record is missing, so the audit cannot verify that code executed on data.",
                ("cycle_summary.demo.experiment_dir",),
                "Rerun the experiment and preserve run/run-record.json.",
            )
        ]

    run_record = _read_json(run_record_path)
    run = _dict(run_record.get("run"))
    metrics = _dict(_dict(run_record.get("metrics")).get("values"))
    validation = _dict(run_record.get("validation_report"))
    artifacts = _list(run_record.get("artifacts"))
    logs = _list(run_record.get("logs"))
    entrypoint = _resolve_path(_dict(run.get("metadata")).get("entrypoint"), base_dir)
    metrics_path = _resolve_path(run.get("metrics_path"), base_dir)
    data_path = _detect_data_path(experiment_dir, _text(run.get("task_id")))
    artifact_paths_ok = _relative_paths_exist(experiment_dir, artifacts)
    log_paths_ok = _relative_paths_exist(experiment_dir, logs)
    data_hash_ok = bool(
        data_path
        and data_path.exists()
        and _text(run.get("data_hash"))
        and file_hash(data_path) == _text(run.get("data_hash"))
    )
    script_data_ok = all(
        [
            _text(run.get("status")) == "success",
            _int(run.get("exit_code"), default=-1) == 0,
            entrypoint is not None and entrypoint.exists(),
            metrics_path is not None and metrics_path.exists(),
            _text(validation.get("status")) == "passed",
            artifact_paths_ok,
            log_paths_ok,
            data_hash_ok,
        ]
    )
    test_rows = int(float(metrics.get("test_rows", 0) or 0))
    synthetic = _is_synthetic_demo(run_record, experiment_dir)
    baseline_present = _has_baseline_evidence(run_record)
    ablation_present = _has_ablation_evidence(run_record)
    statistical_sanity = _has_statistical_sanity(run_record)
    innovation_present = _has_innovation_evidence(run_record, experiment_dir)
    method_effect_check = _method_effect_check(
        run_record,
        experiment_dir,
        target,
        run_record_path.as_posix(),
    )

    checks = [
        PublicationAuditCheck(
            "script_data_verification",
            PublicationAuditCheckStatus.PASS if script_data_ok else PublicationAuditCheckStatus.FAIL,
            "blocking",
            _script_data_message(script_data_ok, entrypoint, data_path, metrics_path),
            (
                run_record_path.as_posix(),
                entrypoint.as_posix() if entrypoint else "missing_entrypoint",
                data_path.as_posix() if data_path else "missing_data",
                metrics_path.as_posix() if metrics_path else "missing_metrics",
            ),
            None if script_data_ok else "Verify run.py, data hash, metrics, logs, artifacts, and validation output.",
        ),
        _threshold_check(
            "data_strength",
            test_rows,
            target.min_test_rows,
            "blocking",
            f"Validated test rows: {test_rows}; target requires at least {target.min_test_rows}.",
            "Use a real benchmark or a sufficiently sized dataset before claiming publication-level empirical support.",
            (run_record_path.as_posix(),),
        ),
    ]
    if target.require_real_dataset and synthetic:
        checks.append(
            PublicationAuditCheck(
                "dataset_realism",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                "The experiment uses a synthetic or ScientistBench-Lite fixture; this cannot prove a CCF-B/Q3-level paper claim.",
                (run_record_path.as_posix(),),
                "Run on a real benchmark dataset with documented splits, preprocessing, and baseline comparability.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "dataset_realism",
                PublicationAuditCheckStatus.PASS,
                "info",
                "Dataset realism requirement is satisfied for this target.",
                (run_record_path.as_posix(),),
            )
        )
    checks.extend(
        [
            _boolean_requirement_check(
                "baseline_reproduction",
                baseline_present or not target.require_baseline,
                "high",
                "Baseline reproduction evidence is present.",
                "Baseline reproduction evidence is missing.",
                "Run and validate at least one credible baseline with comparable settings.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "ablation_coverage",
                ablation_present or not target.require_ablation,
                "high",
                "Ablation evidence is present.",
                "Ablation evidence is missing.",
                "Run ablations for the proposed mechanism before publication review.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "statistical_sanity",
                statistical_sanity or not target.require_statistical_sanity,
                "high",
                "Statistical sanity checks are present.",
                "Statistical sanity checks are missing.",
                "Add sample-size, variance/confidence, repeated-run, or significance checks.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "method_innovation_evidence",
                innovation_present or not target.require_novel_contribution,
                "high",
                "File-backed method innovation evidence is present.",
                "File-backed method innovation evidence is missing or baseline-only.",
                (
                    "Record a proposed mechanism/contribution in task metadata and "
                    "preserve an innovation/mechanism artifact before publication review."
                ),
                (run_record_path.as_posix(),),
            ),
            method_effect_check,
        ]
    )
    return checks


def _review_checks(
    summary: dict[str, Any],
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    review = _dict(summary.get("review"))
    quality = float(review.get("quality_score", 0.0) or 0.0)
    status = _text(review.get("status"))
    verdict = _text(review.get("verdict"))
    passed = status == "passed" and quality >= target.min_llm_review_quality
    checks = [
        PublicationAuditCheck(
            "llm_evidence_review",
            PublicationAuditCheckStatus.PASS if passed else PublicationAuditCheckStatus.FAIL,
            "high",
            (
                f"LLM evidence review status={status or 'missing'}, verdict={verdict or 'missing'}, "
                f"quality_score={quality:.3f}; target requires >= {target.min_llm_review_quality:.2f}."
            ),
            ("cycle_summary.review",),
            None if passed else "Run evidence-constrained LLM review and fix unsupported claims before publication audit.",
        )
    ]
    if verdict not in {"pass", "needs_revision"}:
        checks.append(
            PublicationAuditCheck(
                "review_verdict_strength",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Reviewer verdict is `{verdict or 'missing'}`, not publication-ready.",
                ("cycle_summary.review.verdict",),
                "Treat fail/missing reviewer verdicts as blockers.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "review_verdict_strength",
                PublicationAuditCheckStatus.PASS if verdict == "pass" else PublicationAuditCheckStatus.WARNING,
                "medium",
                f"Reviewer verdict is `{verdict}`.",
                ("cycle_summary.review.verdict",),
                None if verdict == "pass" else "Resolve reviewer revision items before submission.",
            )
        )
    return checks


def _manuscript_checks(
    summary: dict[str, Any],
    base_dir: Path,
) -> list[PublicationAuditCheck]:
    report_path = _resolve_path(_dict(summary.get("demo")).get("report_path"), base_dir)
    if report_path is None or not report_path.exists():
        return [
            PublicationAuditCheck(
                "manuscript_structure",
                PublicationAuditCheckStatus.FAIL,
                "high",
                "No Markdown report or paper draft was found for manuscript-structure audit.",
                ("cycle_summary.demo.report_path",),
                "Generate a paper draft with required academic sections.",
            )
        ]
    text = report_path.read_text(encoding="utf-8").casefold()
    present = tuple(section for section in REQUIRED_PAPER_SECTIONS if _has_markdown_heading(text, section))
    missing = tuple(section for section in REQUIRED_PAPER_SECTIONS if section not in present)
    if missing:
        return [
            PublicationAuditCheck(
                "manuscript_structure",
                PublicationAuditCheckStatus.FAIL,
                "high",
                "The current report is not a publication-style manuscript; missing sections: "
                + ", ".join(missing),
                (report_path.as_posix(),),
                "Generate an evidence-backed paper draft with abstract, related work, method, experiments, limitations, and references.",
            )
        ]
    return [
        PublicationAuditCheck(
            "manuscript_structure",
            PublicationAuditCheckStatus.PASS,
            "info",
            "All required manuscript sections are present.",
            (report_path.as_posix(),),
        )
    ]


def _threshold_check(
    check_id: str,
    actual: int,
    minimum: int,
    severity: str,
    message: str,
    next_action: str,
    evidence_refs: tuple[str, ...],
) -> PublicationAuditCheck:
    return PublicationAuditCheck(
        check_id,
        PublicationAuditCheckStatus.PASS if actual >= minimum else PublicationAuditCheckStatus.FAIL,
        severity,
        message,
        evidence_refs,
        None if actual >= minimum else next_action,
    )


def _boolean_requirement_check(
    check_id: str,
    passed: bool,
    severity: str,
    pass_message: str,
    fail_message: str,
    next_action: str,
    evidence_refs: tuple[str, ...],
) -> PublicationAuditCheck:
    return PublicationAuditCheck(
        check_id,
        PublicationAuditCheckStatus.PASS if passed else PublicationAuditCheckStatus.FAIL,
        severity,
        pass_message if passed else fail_message,
        evidence_refs,
        None if passed else next_action,
    )


def _score(checks: tuple[PublicationAuditCheck, ...] | list[PublicationAuditCheck]) -> float:
    if not checks:
        return 0.0
    weight_by_severity = {
        "blocking": 2.0,
        "high": 1.5,
        "medium": 1.0,
        "info": 0.5,
    }
    total = 0.0
    earned = 0.0
    for check in checks:
        weight = weight_by_severity.get(check.severity, 1.0)
        total += weight
        if check.status is PublicationAuditCheckStatus.PASS:
            earned += weight
        elif check.status is PublicationAuditCheckStatus.WARNING:
            earned += weight * 0.5
    if total <= 0.0:
        return 0.0
    return round(earned / total, 4)


def _verdict(
    checks: tuple[PublicationAuditCheck, ...] | list[PublicationAuditCheck],
    target: PublicationQualityTarget,
) -> PublicationAuditVerdict:
    score = _score(checks)
    blocking_fail = any(
        check.status is PublicationAuditCheckStatus.FAIL and check.severity == "blocking"
        for check in checks
    )
    hard_fail = any(
        check.status is PublicationAuditCheckStatus.FAIL and check.severity in {"blocking", "high"}
        for check in checks
    )
    if blocking_fail:
        return PublicationAuditVerdict.FAIL
    if hard_fail or score < target.min_score:
        return PublicationAuditVerdict.NEEDS_REVISION
    return PublicationAuditVerdict.PASS


def _markdown(report: PublicationAuditReport) -> str:
    lines = [
        "# Publication Quality Audit",
        "",
        f"- Target: `{report.target.display_name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Publishable: `{str(report.publishable).lower()}`",
        f"- Score: `{report.score:.3f}`",
        f"- Cycle summary: `{report.cycle_summary_path}`",
        f"- JSON: `{report.output_path}`",
        f"- Vault review: `{report.vault_review_path or 'not written'}`",
        f"- Vault issue: `{report.vault_issue_path or 'not written'}`",
        "",
        "## Target Gates",
        "",
        f"- Minimum score: `{report.target.min_score}`",
        f"- Literature: `{report.target.min_literature_queries}` queries, `{report.target.min_literature_documents}` documents, `{report.target.min_successful_sources}` successful sources",
        f"- Similarity: `{report.target.min_similarity_queries}` queries, `{report.target.min_similarity_findings}` findings, `{report.target.min_successful_sources}` successful sources",
        f"- Data: at least `{report.target.min_test_rows}` validated test rows; real dataset required: `{str(report.target.require_real_dataset).lower()}`",
        f"- Experiment: baseline `{report.target.require_baseline}`, ablation `{report.target.require_ablation}`, statistical sanity `{report.target.require_statistical_sanity}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Severity | Evidence | Message | Next action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for check in report.checks:
        evidence = ", ".join(f"`{ref}`" for ref in check.evidence_refs) or "`none`"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{check.check_id}`",
                    f"`{check.status.value}`",
                    f"`{check.severity}`",
                    evidence,
                    _escape_table(check.message),
                    _escape_table(check.next_action or "None"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `pass` means this audit did not find publication-readiness blockers for the configured target.",
            "- `needs_revision` means the cycle is evidence-bearing but not ready for submission.",
            "- `fail` means the system must not describe the output as CCF-B/Q3-publication-level.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_vault_audit(
    report: PublicationAuditReport,
    vault_root: Path,
    project_id: str,
) -> tuple[Path, Path | None]:
    store = MarkdownKnowledgeStore(vault_root)
    now = datetime.now(timezone.utc)
    slug = _slug(Path(report.cycle_summary_path).parent.name or "cycle")
    review_entry = KnowledgeEntry(
        entry_id=f"publication_audit_{project_id}_{slug}",
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title=f"Publication audit {slug}",
        tags=["publication-audit", report.verdict.value],
        keywords=["publication-audit", report.target.name, report.verdict.value],
        source_refs=[report.cycle_summary_path, report.output_path, report.markdown_path],
        related_task_ids=["publication-audit"],
        body=_markdown(report),
        created_at=now,
        updated_at=now,
    )
    review_path = store.write_entry(
        Path("projects") / project_id / "review" / f"publication-audit-{slug}.md",
        review_entry,
    )
    issue_path = None
    if report.verdict is not PublicationAuditVerdict.PASS:
        failed_checks = [check for check in report.checks if check.status is PublicationAuditCheckStatus.FAIL]
        issue_entry = KnowledgeEntry(
            entry_id=f"publication_audit_issue_{project_id}_{slug}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            project_id=project_id,
            title=f"Publication audit blockers {slug}",
            tags=["open", "publication-audit", report.verdict.value],
            keywords=["publication-audit", "quality-gate", report.target.name],
            source_refs=[report.output_path, report.markdown_path],
            links=[review_entry.entry_id],
            related_task_ids=["publication-audit"],
            body=_issue_body(report, review_entry.entry_id, failed_checks),
            created_at=now,
            updated_at=now,
        )
        issue_path = store.write_entry(
            Path("projects") / project_id / "issues" / f"publication-audit-{slug}.md",
            issue_entry,
        )
    return review_path, issue_path


def _issue_body(
    report: PublicationAuditReport,
    review_entry_id: str,
    failed_checks: list[PublicationAuditCheck],
) -> str:
    lines = [
        f"# Publication audit blockers for {Path(report.cycle_summary_path).parent.name}",
        "",
        f"- Review note: [[{review_entry_id}]]",
        f"- Target: `{report.target.display_name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Score: `{report.score:.3f}`",
        f"- Issue fingerprint: `publication-audit:{Path(report.cycle_summary_path).parent.name}`",
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


def _similarity_classifications(similarity: dict[str, Any], base_dir: Path) -> dict[str, int]:
    summary_path = _resolve_path(similarity.get("summary_path"), base_dir)
    if summary_path is None or not summary_path.exists():
        return {}
    text = summary_path.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for match in re.finditer(r"Classification:\s*`([^`]+)`", text):
        classification = match.group(1).strip()
        counts[classification] = counts.get(classification, 0) + 1
    return counts


def _successful_sources(fetches: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _text(fetch.get("source"))
                for fetch in fetches
                if _int(fetch.get("paper_count")) > 0 and not _text(fetch.get("error"))
            }
        )
    )


def _script_data_message(
    script_data_ok: bool,
    entrypoint: Path | None,
    data_path: Path | None,
    metrics_path: Path | None,
) -> str:
    if script_data_ok:
        return (
            "Execution record confirms run.py existed, data hash matched the local data file, "
            "metrics were written, artifacts/logs existed, exit_code was 0, and validation passed."
        )
    return (
        "Could not prove script/data execution from local artifacts. "
        f"entrypoint={entrypoint}, data={data_path}, metrics={metrics_path}"
    )


def _detect_data_path(experiment_dir: Path | None, task_id: str) -> Path | None:
    if experiment_dir is None:
        return None
    data_dir = experiment_dir / "data"
    candidates = [data_dir / f"{task_id}.csv"]
    if data_dir.exists():
        candidates.extend(sorted(data_dir.glob("*.csv")))
    for path in candidates:
        if path.exists():
            return path
    return None


def _is_synthetic_demo(run_record: dict[str, Any], experiment_dir: Path | None) -> bool:
    run = _dict(run_record.get("run"))
    task_metadata = _dict(run_record.get("task_metadata"))
    metrics_json = _read_json_if_exists(_dict(run_record.get("metrics")).get("path"))
    metrics_metadata = _dict(metrics_json.get("metadata"))
    if task_metadata.get("real_dataset") is True or metrics_metadata.get("real_dataset") is True:
        return False
    task_id = _text(run.get("task_id")).casefold()
    project_id = _text(run.get("project_id")).casefold()
    if "scientistbench-lite" in project_id or task_id in {"tabular_baseline", "text_classifier_stub"}:
        return True
    if experiment_dir is None:
        return False
    readme = experiment_dir / "README.md"
    report = experiment_dir / "report" / "report.md"
    text = ""
    for path in (readme, report):
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore").casefold()
    return "synthetic" in text or "fixture" in text


def _has_baseline_evidence(run_record: dict[str, Any]) -> bool:
    run = _dict(run_record.get("run"))
    task_id = _text(run.get("task_id")).casefold()
    if task_id.endswith("baseline"):
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return "baseline" in text


def _has_ablation_evidence(run_record: dict[str, Any]) -> bool:
    task_metadata = _dict(run_record.get("task_metadata"))
    if _text(task_metadata.get("ablation")):
        return True
    artifacts = " ".join(_text(path) for path in _list(run_record.get("artifacts"))).casefold()
    if "ablation" in artifacts:
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return "ablation" in text


def _has_statistical_sanity(run_record: dict[str, Any]) -> bool:
    validation = _read_json_if_exists(_dict(run_record.get("validation_report")).get("json_path"))
    if _list(validation.get("statistical_notes")):
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return any(term in text for term in ("confidence interval", "p_value", "standard deviation"))


def _has_innovation_evidence(
    run_record: dict[str, Any],
    experiment_dir: Path | None,
) -> bool:
    task_metadata = _dict(run_record.get("task_metadata"))
    run = _dict(run_record.get("run"))
    task_id = _text(run.get("task_id")).casefold()
    explicit_baseline_only = task_metadata.get("baseline_only") is True
    if explicit_baseline_only or task_id.endswith("baseline"):
        return False

    contribution_fields = (
        "novel_contribution",
        "proposed_method",
        "method_contribution",
        "mechanism",
        "contribution",
    )
    has_contribution_metadata = any(
        _text(task_metadata.get(field)).strip() for field in contribution_fields
    )
    if not has_contribution_metadata:
        return False

    innovation_artifacts = _innovation_artifact_paths(run_record)
    if not innovation_artifacts:
        return False
    return _relative_paths_exist(experiment_dir, list(innovation_artifacts))


def _method_effect_check(
    run_record: dict[str, Any],
    experiment_dir: Path | None,
    target: PublicationQualityTarget,
    run_record_ref: str,
) -> PublicationAuditCheck:
    if not target.require_novel_contribution:
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.PASS,
            "info",
            "Positive method-effect evidence is not required for this target.",
            (run_record_ref,),
        )

    artifact_paths = _innovation_artifact_paths(run_record)
    resolved_paths = _existing_relative_paths(experiment_dir, artifact_paths)
    refs = (run_record_ref, *[path.as_posix() for path in resolved_paths])
    if not resolved_paths:
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.FAIL,
            "high",
            "Method-effect evidence is missing because no readable innovation artifact exists.",
            refs,
            "Preserve a JSON innovation artifact with baseline and candidate metrics before publication review.",
        )

    for path in resolved_paths:
        payload = _read_json_if_exists(path)
        delta = _method_effect_delta(payload)
        if delta is None:
            continue
        if delta > 0:
            return PublicationAuditCheck(
                "method_effect_evidence",
                PublicationAuditCheckStatus.PASS,
                "high",
                f"Method candidate improved over baseline with recorded delta={delta:.6f}.",
                refs,
            )
        relation = "tied" if delta == 0 else "underperformed"
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.FAIL,
            "high",
            f"Method candidate {relation} the baseline with recorded delta={delta:.6f}.",
            refs,
            (
                "Do not claim empirical gain; treat this as negative evidence or "
                "validate a stronger method candidate."
            ),
        )

    return PublicationAuditCheck(
        "method_effect_evidence",
        PublicationAuditCheckStatus.FAIL,
        "high",
        "Innovation artifacts exist but do not report a baseline-vs-candidate effect delta.",
        refs,
        "Add a numeric delta such as accuracy_delta_vs_baseline or candidate/baseline metrics.",
    )


def _innovation_artifact_paths(run_record: dict[str, Any]) -> tuple[str, ...]:
    artifact_paths = tuple(_text(path) for path in _list(run_record.get("artifacts")))
    return tuple(
        path_text
        for path_text in artifact_paths
        if any(term in path_text.casefold() for term in ("innovation", "mechanism", "contribution"))
    )


def _existing_relative_paths(root: Path | None, paths: tuple[str, ...]) -> tuple[Path, ...]:
    if root is None:
        return ()
    resolved: list[Path] = []
    for path_text in paths:
        path = Path(path_text)
        candidate = path if path.is_absolute() else root / path
        if candidate.exists():
            resolved.append(candidate)
    return tuple(resolved)


def _method_effect_delta(payload: dict[str, Any]) -> float | None:
    for key in (
        "accuracy_delta_vs_baseline",
        "delta_vs_baseline",
        "metric_delta_vs_baseline",
        "candidate_minus_baseline",
    ):
        delta = _float_or_none(payload.get(key))
        if delta is not None:
            return delta
    candidate = _float_or_none(payload.get("candidate_accuracy"))
    baseline = _float_or_none(payload.get("baseline_accuracy"))
    if candidate is not None and baseline is not None:
        return candidate - baseline
    return None


def _relative_paths_exist(root: Path | None, paths: list[Any]) -> bool:
    if root is None or not paths:
        return False
    for path_text in paths:
        path = Path(_text(path_text))
        resolved = path if path.is_absolute() else root / path
        if not resolved.exists():
            return False
    return True


def _has_markdown_heading(text: str, heading: str) -> bool:
    escaped = re.escape(heading)
    return re.search(rf"(?m)^#+\s+{escaped}\s*$", text) is not None


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _read_json_if_exists(path_value: object) -> dict[str, Any]:
    path = Path(_text(path_value))
    if not path.exists():
        return {}
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _resolve_path(path_value: object, base_dir: Path) -> Path | None:
    text = _text(path_value)
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([base_dir / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _int(value: object, *, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "publication-audit"
