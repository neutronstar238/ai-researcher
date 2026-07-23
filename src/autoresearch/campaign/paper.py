"""Final paper-package builder for task 260.5.

The builder is deliberately evidence-driven.  It reads the immutable Route A
campaign and the preregistered Route B systems benchmark, renders a paper from
those values, compiles the paper in ACM two-column format, and launches a
self-contained reproduction script in a fresh directory.  No paper artifact or
internal quality gate authorizes external submission.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import Field

from autoresearch.campaign.models import StrictCampaignModel
from autoresearch.campaign.service import validate_campaign_directory
from autoresearch.campaign.systems import (
    SystemsBenchmarkResult,
    SystemsContributionGate,
    SystemsPreregistration,
    systems_benchmark_status,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.process import windows_no_window_kwargs
from autoresearch.schemas import data_hash, file_hash

_ASSET_ROOT = Path(__file__).with_name("paper_assets")
_SOURCE_DATE_EPOCH = "1784736000"  # 2026-07-23 00:00:00 UTC
_MIN_REFERENCE_COUNT = 30
_MIN_MAIN_PAGES = 8
_EXPECTED_FIGURES = (
    "running-example",
    "campaign-pipeline",
    "main-results",
    "ablation-results",
    "route-a-results",
)
_CITATION_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)")
_CITE_COMMAND = re.compile(r"\\cite[pt]?\{([^}]+)\}")
_UNRESOLVED_LATEX = (
    re.compile(r"LaTeX Warning: Citation .+ undefined", re.IGNORECASE),
    re.compile(r"There were undefined references", re.IGNORECASE),
    re.compile(r"LaTeX Warning: Reference .+ undefined", re.IGNORECASE),
)


class PaperPackageAudit(StrictCampaignModel):
    """Deterministic final quality and evidence audit."""

    schema_version: str = "task260-paper-package-audit-v1"
    checked_at: datetime
    checks: dict[str, bool]
    critical_issues: tuple[str, ...] = ()
    major_issues: tuple[str, ...] = ()
    minor_issues: tuple[str, ...] = ()
    verdict: Literal["ready_for_human_submission_review", "not_ready"]
    external_submission_authorized: bool = False
    audit_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PaperPackageManifest(StrictCampaignModel):
    """Hash-bound manifest for the complete local paper dossier."""

    schema_version: str = "task260-paper-package-manifest-v1"
    package_id: str
    created_at: datetime
    route_a_campaign_path: str
    route_a_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    systems_benchmark_path: str
    systems_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    systems_gate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_tex_path: str
    manuscript_pdf_path: str | None
    arxiv_source_path: str
    citation_audit_path: str
    evidence_graph_path: str
    review_path: str
    reproduction_report_path: str
    environment_lock_path: str
    artifact_hashes_path: str
    artifact_hashes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deliverables_index_path: str
    paper_audit_path: str
    paper_audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_submission_authorized: bool = False
    package_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PaperPackageResult(StrictCampaignModel):
    """User-facing result returned by build and status operations."""

    package_dir: str
    manifest_path: str
    manuscript_pdf_path: str | None
    deliverables_index_path: str
    reproduction_report_path: str
    verdict: Literal["ready_for_human_submission_review", "not_ready"]
    package_hash: str
    external_submission_authorized: bool = False


def build_task260_paper_package(
    *,
    route_a_campaign_dir: Path | str,
    systems_benchmark_dir: Path | str,
    output_dir: Path | str,
    reproduction_dir: Path | str,
    vault_root: Path | str = Path("autoresearch-vault"),
    live_citation_check: bool = True,
    compile_pdf: bool = True,
    copy_dossier: bool = True,
) -> PaperPackageResult:
    """Build, reproduce, and audit the task 260 final paper package."""

    route_root = Path(route_a_campaign_dir).resolve()
    systems_root = Path(systems_benchmark_dir).resolve()
    package_root = Path(output_dir).resolve()
    fresh_root = Path(reproduction_dir).resolve()
    if package_root == fresh_root:
        raise ValueError("primary package and reproduction directories must differ")
    if fresh_root.exists() and any(fresh_root.iterdir()):
        raise ValueError("independent reproduction directory must be absent or empty")

    _, route_manifest, route_rounds = validate_campaign_directory(route_root)
    status = systems_benchmark_status(systems_root)
    if not status.completed or status.result_hash is None:
        raise ValueError("systems benchmark must be complete before paper build")
    systems_result = SystemsBenchmarkResult.model_validate_json(
        (systems_root / "benchmark-result.json").read_text(encoding="utf-8")
    )
    systems_gate = SystemsContributionGate.model_validate_json(
        (systems_root / "contribution-gate.json").read_text(encoding="utf-8")
    )
    preregistration = SystemsPreregistration.model_validate_json(
        (systems_root / "preregistration.json").read_text(encoding="utf-8")
    )
    _validate_paper_inputs(
        route_manifest=route_manifest.model_dump(mode="json"),
        route_round_count=len(route_rounds),
        systems_result=systems_result,
        systems_gate=systems_gate,
        preregistration=preregistration,
    )

    if package_root.exists():
        existing_manifest = package_root / "paper-package.json"
        if existing_manifest.is_file():
            return validate_task260_paper_package(package_root)
        raise ValueError("paper output directory exists without a valid package manifest")
    package_root.mkdir(parents=True)

    inputs = _collect_frozen_inputs(
        route_root=route_root,
        systems_root=systems_root,
        route_manifest=route_manifest.model_dump(mode="json"),
        systems_result=systems_result,
        systems_gate=systems_gate,
        preregistration=preregistration,
    )
    frozen_dir = package_root / "frozen-inputs"
    frozen_dir.mkdir()
    _write_json(frozen_dir / "paper-values.json", inputs["paper_values"])
    _copy_required_input_files(route_root, systems_root, frozen_dir)

    paper_source = package_root / "paper" / "source"
    shutil.copytree(_ASSET_ROOT, paper_source)
    _write_text(paper_source / "values.tex", _values_tex(inputs["paper_values"]))
    _write_generated_tables(paper_source / "tables", inputs)
    _write_generated_figures(paper_source / "figures", inputs["paper_values"])
    _write_json(
        paper_source / "evidence" / "paper-values.json",
        inputs["paper_values"],
    )

    compile_records = _compile_paper_sources(paper_source, enabled=compile_pdf)
    _write_json(package_root / "paper" / "compile-records.json", compile_records)
    main_pdf = paper_source / "main.pdf"

    citation_audit = _audit_citations(
        paper_source,
        live_check=live_citation_check,
    )
    citation_audit_path = _write_json(
        package_root / "audit" / "citation-audit.json",
        citation_audit,
    )
    claim_evidence = _build_claim_evidence_map(
        package_root=package_root,
        route_root=route_root,
        systems_root=systems_root,
        inputs=inputs,
    )
    evidence_graph_path = _write_json(
        package_root / "evidence" / "claim-evidence-map.json",
        claim_evidence,
    )
    _write_text(
        package_root / "evidence" / "claim-evidence-map.md",
        _claim_evidence_markdown(claim_evidence),
    )

    environment_lock_path = _write_json(
        package_root / "reproduction" / "environment-lock.json",
        _environment_lock(route_root, systems_root),
    )
    reproduce_script = package_root / "reproduction" / "reproduce.py"
    _write_text(reproduce_script, _standalone_reproduction_script())
    _write_text(
        package_root / "reproduction" / "commands.md",
        _reproduction_commands(package_root, fresh_root),
    )

    if copy_dossier:
        _copy_complete_dossier(route_root, systems_root, package_root / "dossier")
    _write_arxiv_archive(paper_source, package_root / "paper" / "arxiv-source.zip")

    reproduction_report = _run_independent_reproduction(
        package_root=package_root,
        reproduction_root=fresh_root,
        enabled=compile_pdf,
    )
    reproduction_report_path = _write_json(
        package_root / "reproduction" / "independent-reproduction.json",
        reproduction_report,
    )

    review_payload = _deterministic_review(
        paper_source=paper_source,
        inputs=inputs,
        citation_audit=citation_audit,
        claim_evidence=claim_evidence,
        compile_records=compile_records,
        reproduction_report=reproduction_report,
    )
    review_path = _write_json(
        package_root / "review" / "pre-submission-review.json",
        review_payload,
    )
    _write_text(
        package_root / "review" / "pre-submission-review.md",
        _review_markdown(review_payload),
    )

    audit = _build_final_audit(
        paper_source=paper_source,
        main_pdf=main_pdf,
        route_round_count=len(route_rounds),
        systems_gate=systems_gate,
        citation_audit=citation_audit,
        claim_evidence=claim_evidence,
        compile_records=compile_records,
        reproduction_report=reproduction_report,
        review_payload=review_payload,
        compile_pdf=compile_pdf,
    )
    stamped_audit = _stamp_audit(audit)
    audit_path = package_root / "audit" / "paper-package-audit.json"
    write_json_model(audit_path, stamped_audit)
    _write_text(
        package_root / "audit" / "paper-package-audit.md",
        _paper_audit_markdown(stamped_audit),
    )

    index_path = _write_text(
        package_root / "deliverables" / "index.md",
        _deliverables_index(stamped_audit),
    )
    _write_text(
        package_root / "deliverables" / "EXTERNAL-SUBMISSION-BLOCKED.md",
        "# External submission is blocked\n\n"
        "This package is ready only for human submission review. No upload, public "
        "release, or venue submission is authorized without an explicit human approval.\n",
    )

    hash_path = package_root / "artifact-hashes.json"
    _write_json(hash_path, _artifact_hash_payload(package_root))
    manifest = PaperPackageManifest(
        package_id=package_root.name,
        created_at=datetime.now(timezone.utc),
        route_a_campaign_path=route_root.as_posix(),
        route_a_lineage_hash=str(inputs["paper_values"]["route_a_lineage_hash"]),
        systems_benchmark_path=systems_root.as_posix(),
        systems_result_hash=_required_hash(systems_result.result_hash, "systems result"),
        systems_gate_hash=_required_hash(systems_gate.gate_hash, "systems gate"),
        manuscript_tex_path=(paper_source / "main.tex").as_posix(),
        manuscript_pdf_path=main_pdf.as_posix() if main_pdf.is_file() else None,
        arxiv_source_path=(package_root / "paper" / "arxiv-source.zip").as_posix(),
        citation_audit_path=citation_audit_path.as_posix(),
        evidence_graph_path=evidence_graph_path.as_posix(),
        review_path=review_path.as_posix(),
        reproduction_report_path=reproduction_report_path.as_posix(),
        environment_lock_path=environment_lock_path.as_posix(),
        artifact_hashes_path=hash_path.as_posix(),
        artifact_hashes_sha256=file_hash(hash_path),
        deliverables_index_path=index_path.as_posix(),
        paper_audit_path=audit_path.as_posix(),
        paper_audit_hash=_required_hash(stamped_audit.audit_hash, "paper audit"),
    )
    stamped_manifest = _stamp_manifest(manifest)
    manifest_path = package_root / "paper-package.json"
    write_json_model(manifest_path, stamped_manifest)
    _write_text(
        package_root / "paper-package.md",
        _package_manifest_markdown(stamped_manifest, stamped_audit),
    )
    _write_vault_note(
        Path(vault_root),
        package_root,
        stamped_manifest,
        stamped_audit,
    )
    return PaperPackageResult(
        package_dir=package_root.as_posix(),
        manifest_path=manifest_path.as_posix(),
        manuscript_pdf_path=stamped_manifest.manuscript_pdf_path,
        deliverables_index_path=index_path.as_posix(),
        reproduction_report_path=reproduction_report_path.as_posix(),
        verdict=stamped_audit.verdict,
        package_hash=_required_hash(stamped_manifest.package_hash, "paper package"),
    )


def validate_task260_paper_package(package_dir: Path | str) -> PaperPackageResult:
    """Validate all recorded package hashes without rebuilding or submitting."""

    root = Path(package_dir).resolve()
    manifest_path = root / "paper-package.json"
    manifest = PaperPackageManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    expected = canonical_model_hash(manifest.model_copy(update={"package_hash": None}))
    if manifest.package_hash != expected:
        raise ValueError("paper package manifest hash mismatch")
    audit = PaperPackageAudit.model_validate_json(
        Path(manifest.paper_audit_path).read_text(encoding="utf-8")
    )
    audit_expected = canonical_model_hash(audit.model_copy(update={"audit_hash": None}))
    if audit.audit_hash != audit_expected or manifest.paper_audit_hash != audit.audit_hash:
        raise ValueError("paper audit hash mismatch")
    hash_payload = json.loads(Path(manifest.artifact_hashes_path).read_text(encoding="utf-8"))
    if file_hash(manifest.artifact_hashes_path) != manifest.artifact_hashes_sha256:
        raise ValueError("paper artifact hash manifest mismatch")
    for item in hash_payload.get("files", []):
        candidate = root / item["relative_path"]
        if not candidate.is_file() or file_hash(candidate) != item["sha256"]:
            raise ValueError(f"paper artifact hash mismatch: {item['relative_path']}")
    if manifest.external_submission_authorized:
        raise ValueError("paper package must not authorize external submission")
    return PaperPackageResult(
        package_dir=root.as_posix(),
        manifest_path=manifest_path.as_posix(),
        manuscript_pdf_path=manifest.manuscript_pdf_path,
        deliverables_index_path=manifest.deliverables_index_path,
        reproduction_report_path=manifest.reproduction_report_path,
        verdict=audit.verdict,
        package_hash=_required_hash(manifest.package_hash, "paper package"),
    )


def _validate_paper_inputs(
    *,
    route_manifest: Mapping[str, Any],
    route_round_count: int,
    systems_result: SystemsBenchmarkResult,
    systems_gate: SystemsContributionGate,
    preregistration: SystemsPreregistration,
) -> None:
    if route_round_count < 2 or int(route_manifest["experimental_round_count"]) < 2:
        raise ValueError("paper build requires at least two new Route A rounds")
    if int(route_manifest["human_intervention_count"]) != 0:
        raise ValueError("Route A contains research-decision human intervention")
    if systems_result.result_hash is None or systems_gate.gate_hash is None:
        raise ValueError("systems result and contribution gate must be hash-stamped")
    if not systems_gate.passed:
        raise ValueError("systems contribution gate did not pass")
    if systems_gate.external_submission_authorized:
        raise ValueError("systems gate unexpectedly authorizes external submission")
    if systems_result.preregistration_hash != preregistration.preregistration_hash:
        raise ValueError("systems result is not bound to the frozen preregistration")
    if systems_result.campaign_research_decision_human_interventions != 0:
        raise ValueError("systems benchmark contains research-decision intervention")


def _collect_frozen_inputs(
    *,
    route_root: Path,
    systems_root: Path,
    route_manifest: Mapping[str, Any],
    systems_result: SystemsBenchmarkResult,
    systems_gate: SystemsContributionGate,
    preregistration: SystemsPreregistration,
) -> dict[str, Any]:
    route_rounds: list[dict[str, Any]] = []
    for round_number in (1, 2):
        round_dir = route_root / "rounds" / f"round-{round_number:03d}"
        development = _read_json(round_dir / "development_result.json")
        unseen = _read_json(round_dir / "unseen_evaluation.json")
        hypothesis = _read_json(round_dir / "hypothesis.json")
        decision = _read_json(round_dir / "round_decision.json")
        route_rounds.append(
            {
                "round_id": f"round-{round_number:03d}",
                "mechanism_family": hypothesis["mechanism_family"],
                "development_improvement": development["metrics"][
                    "median_relative_improvement"
                ],
                "unseen_improvement": unseen["metrics"][
                    "median_relative_improvement"
                ],
                "ci95_lower": unseen["metrics"]["bootstrap_ci95_lower"],
                "ci95_upper": unseen["metrics"]["bootstrap_ci95_upper"],
                "candidate_success_rate": unseen["metrics"]["candidate_success_rate"],
                "idempotent_reproduction": unseen["metrics"][
                    "idempotent_reproduction"
                ],
                "outcome": unseen["outcome"],
                "decision": decision["decision"],
                "result_hash": unseen["result_hash"],
            }
        )
    modes = {
        key: value.model_dump(mode="json")
        for key, value in systems_result.mode_metrics.items()
    }
    paper_values = {
        "benchmark_id": systems_result.benchmark_id,
        "route_a_lineage_hash": route_manifest["lineage_hash"],
        "route_a_rounds": route_rounds,
        "task_count": len(preregistration.tasks),
        "task_family_counts": {
            "uci": sum(task.family.value == "uci" for task in preregistration.tasks),
            "mdbench": sum(
                task.family.value == "mdbench" for task in preregistration.tasks
            ),
        },
        "seed_count": len(preregistration.seeds),
        "seeds": list(preregistration.seeds),
        "main_cell_count": systems_result.main_cell_count,
        "ablation_cell_count": systems_result.ablation_cell_count,
        "cell_count": systems_result.cell_count,
        "paired_mean_gain": systems_result.paired_mean_gain_vs_execute_once,
        "bootstrap_ci95_lower": systems_result.bootstrap_ci95_lower,
        "bootstrap_ci95_upper": systems_result.bootstrap_ci95_upper,
        "bootstrap_resamples": preregistration.bootstrap_resamples,
        "mode_metrics": modes,
        "paired_differences": list(systems_result.paired_differences),
        "local_model_request_count": systems_result.local_model_request_count,
        "local_model_fallback_count": systems_result.local_model_fallback_count,
        "local_model_wall_time_seconds": systems_result.local_model_wall_time_seconds,
        "external_cost_usd": systems_result.external_cost_usd,
        "research_decision_human_interventions": (
            systems_result.campaign_research_decision_human_interventions
        ),
        "systems_result_hash": systems_result.result_hash,
        "systems_gate_hash": systems_gate.gate_hash,
        "preregistration_hash": preregistration.preregistration_hash,
        "external_submission_authorized": False,
    }
    return {
        "paper_values": paper_values,
        "route_manifest": dict(route_manifest),
        "systems_result": systems_result.model_dump(mode="json"),
        "systems_gate": systems_gate.model_dump(mode="json"),
        "preregistration": preregistration.model_dump(mode="json"),
        "route_root": route_root.as_posix(),
        "systems_root": systems_root.as_posix(),
    }


def _copy_required_input_files(
    route_root: Path,
    systems_root: Path,
    frozen_dir: Path,
) -> None:
    mappings = {
        route_root / "campaign-manifest.json": frozen_dir / "route-a-campaign-manifest.json",
        systems_root / "benchmark-result.json": frozen_dir / "systems-benchmark-result.json",
        systems_root / "contribution-gate.json": frozen_dir / "systems-contribution-gate.json",
        systems_root / "preregistration.json": frozen_dir / "systems-preregistration.json",
        systems_root / "matrix-manifest.json": frozen_dir / "systems-matrix-manifest.json",
    }
    for round_number in (1, 2):
        source = (
            route_root
            / "rounds"
            / f"round-{round_number:03d}"
            / "unseen_evaluation.json"
        )
        mappings[source] = frozen_dir / f"route-a-round-{round_number}-unseen.json"
    for source, destination in mappings.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    frozen_files = [
        {
            "relative_path": path.relative_to(frozen_dir).as_posix(),
            "sha256": file_hash(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(frozen_dir.rglob("*"))
        if path.is_file() and path.name != "frozen-input-hashes.json"
    ]
    _write_json(
        frozen_dir / "frozen-input-hashes.json",
        {
            "schema_version": "task260-frozen-input-hashes-v1",
            "files": frozen_files,
            "manifest_hash": data_hash({"files": frozen_files}),
        },
    )


def _values_tex(values: Mapping[str, Any]) -> str:
    modes = values["mode_metrics"]
    route_rounds = values["route_a_rounds"]
    macros = {
        "TaskCount": values["task_count"],
        "UciTaskCount": values["task_family_counts"]["uci"],
        "MDBenchTaskCount": values["task_family_counts"]["mdbench"],
        "SeedCount": values["seed_count"],
        "CellCount": values["cell_count"],
        "MainCellCount": values["main_cell_count"],
        "AblationCellCount": values["ablation_cell_count"],
        "BootstrapResamples": values["bootstrap_resamples"],
        "OneShotSuccess": _fmt(modes["one_shot"]["task_success_rate"]),
        "ExecuteOnceSuccess": _fmt(modes["execute_once"]["task_success_rate"]),
        "FullLoopSuccess": _fmt(modes["full_loop"]["task_success_rate"]),
        "FullLoopRecovery": _fmt(
            modes["full_loop"]["negative_result_recovery_rate"]
        ),
        "FullLoopReproduction": _fmt(
            modes["full_loop"]["exact_reproduction_rate"]
        ),
        "FullLoopUnsupported": modes["full_loop"]["unsupported_claim_count"],
        "PairedGain": _fmt(values["paired_mean_gain"]),
        "PairedCILower": _fmt(values["bootstrap_ci95_lower"], digits=6),
        "PairedCIUpper": _fmt(values["bootstrap_ci95_upper"], digits=6),
        "NoVaultSuccess": _fmt(
            modes["full_loop_no_vault"]["task_success_rate"]
        ),
        "NoFeedbackSuccess": _fmt(
            modes["full_loop_no_failure_feedback"]["task_success_rate"]
        ),
        "NoPreregSuccess": _fmt(
            modes["full_loop_no_preregistration"]["task_success_rate"]
        ),
        "NoGateSuccess": _fmt(
            modes["full_loop_no_evidence_gate"]["task_success_rate"]
        ),
        "NoGateUnsupported": modes["full_loop_no_evidence_gate"][
            "unsupported_claim_count"
        ],
        "HumanInterventions": values["research_decision_human_interventions"],
        "LocalRequests": values["local_model_request_count"],
        "LocalFallbacks": values["local_model_fallback_count"],
        "RouteOneDevelopment": _fmt(
            route_rounds[0]["development_improvement"], digits=6
        ),
        "RouteOneCILower": _fmt(route_rounds[0]["ci95_lower"], digits=6),
        "RouteOneCIUpper": _fmt(route_rounds[0]["ci95_upper"], digits=6),
        "RouteTwoDevelopment": _fmt(
            route_rounds[1]["development_improvement"], digits=6
        ),
        "RouteTwoCILower": _fmt(route_rounds[1]["ci95_lower"], digits=6),
        "RouteTwoCIUpper": _fmt(route_rounds[1]["ci95_upper"], digits=6),
    }
    return "\n".join(
        [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()]
        + [
            "\\newcommand{\\ExternalSubmissionAuthorized}{false}",
            "",
        ]
    )


def _write_generated_tables(table_dir: Path, inputs: Mapping[str, Any]) -> None:
    table_dir.mkdir(parents=True, exist_ok=True)
    values = inputs["paper_values"]
    modes = values["mode_metrics"]
    rows = [
        ("One-shot", modes["one_shot"]),
        ("Execute-once", modes["execute_once"]),
        ("Full loop", modes["full_loop"]),
        ("No Vault memory", modes["full_loop_no_vault"]),
        ("No failure feedback", modes["full_loop_no_failure_feedback"]),
        ("No preregistration", modes["full_loop_no_preregistration"]),
        ("No evidence gate", modes["full_loop_no_evidence_gate"]),
    ]
    body = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Controller & Success & Recovery & Reproduction & Unsupported \\",
        r"\midrule",
    ]
    for label, metric in rows:
        body.append(
            f"{label} & {_fmt(metric['task_success_rate'])} & "
            f"{_fmt(metric['negative_result_recovery_rate'])} & "
            f"{_fmt(metric['exact_reproduction_rate'])} & "
            f"{metric['unsupported_claim_count']} \\\\"
        )
    body.extend([r"\bottomrule", r"\end{tabular}", ""])
    _write_text(table_dir / "mode-results.tex", "\n".join(body))

    route_rows = [
        r"\begin{tabular}{llrrrl}",
        r"\toprule",
        r"Round & Mechanism & Dev. gain & CI lower & CI upper & Decision \\",
        r"\midrule",
    ]
    for index, item in enumerate(values["route_a_rounds"], start=1):
        mechanism = str(item["mechanism_family"]).replace("_", r"\_")
        route_rows.append(
            f"{index} & \\texttt{{{mechanism}}} & "
            f"{_fmt(item['development_improvement'], digits=3)} & "
            f"{_fmt(item['ci95_lower'], digits=3)} & "
            f"{_fmt(item['ci95_upper'], digits=3)} & negative \\\\"
        )
    route_rows.extend([r"\bottomrule", r"\end{tabular}", ""])
    _write_text(table_dir / "route-a-results.tex", "\n".join(route_rows))


def _write_generated_figures(figure_dir: Path, values: Mapping[str, Any]) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    modes = values["mode_metrics"]
    _write_text(figure_dir / "running-example.tex", _running_example_figure())
    _write_text(figure_dir / "campaign-pipeline.tex", _pipeline_figure())
    _write_text(
        figure_dir / "main-results.tex",
        _bar_figure(
            title="Main controller comparison",
            labels=("One-shot", "Execute-once", "Full loop"),
            values=(
                modes["one_shot"]["task_success_rate"],
                modes["execute_once"]["task_success_rate"],
                modes["full_loop"]["task_success_rate"],
            ),
            colors=("gray", "orange", "blue"),
        ),
    )
    _write_text(
        figure_dir / "ablation-results.tex",
        _bar_figure(
            title="Preregistered component ablations",
            labels=("Full", "No vault", "No feedback", "No prereg.", "No gate"),
            values=(
                modes["full_loop"]["task_success_rate"],
                modes["full_loop_no_vault"]["task_success_rate"],
                modes["full_loop_no_failure_feedback"]["task_success_rate"],
                modes["full_loop_no_preregistration"]["task_success_rate"],
                modes["full_loop_no_evidence_gate"]["task_success_rate"],
            ),
            colors=("blue", "gray", "gray", "gray", "gray"),
        ),
    )
    _write_text(
        figure_dir / "route-a-results.tex",
        _route_a_figure(values["route_a_rounds"]),
    )


def _compile_paper_sources(source_dir: Path, *, enabled: bool) -> dict[str, Any]:
    records: dict[str, Any] = {"enabled": enabled, "figures": {}, "paper": {}}
    if not enabled:
        records["status"] = "skipped"
        return records
    for name in _EXPECTED_FIGURES:
        tex_path = source_dir / "figures" / f"{name}.tex"
        records["figures"][name] = _run_latexmk(tex_path, tex_path.parent)
    records["paper"] = _run_latexmk(source_dir / "main.tex", source_dir)
    records["status"] = (
        "passed"
        if records["paper"]["exit_code"] == 0
        and all(item["exit_code"] == 0 for item in records["figures"].values())
        else "failed"
    )
    return records


def _run_latexmk(tex_path: Path, cwd: Path) -> dict[str, Any]:
    executable = shutil.which("latexmk")
    if executable is None:
        return {
            "command": [],
            "exit_code": 127,
            "stdout_tail": "",
            "stderr_tail": "latexmk is not installed",
            "pdf_path": None,
        }
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = _SOURCE_DATE_EPOCH
    env["FORCE_SOURCE_DATE"] = "1"
    command = [
        executable,
        "-pdf",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        tex_path.name,
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        **windows_no_window_kwargs(),
    )
    pdf_path = tex_path.with_suffix(".pdf")
    return {
        "command": [Path(command[0]).name, *command[1:]],
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "pdf_path": pdf_path.as_posix() if pdf_path.is_file() else None,
        "log_path": tex_path.with_suffix(".log").as_posix(),
    }


def _audit_citations(source_dir: Path, *, live_check: bool) -> dict[str, Any]:
    bib_path = source_dir / "references.bib"
    bib_text = bib_path.read_text(encoding="utf-8")
    defined = set(_CITATION_KEY.findall(bib_text))
    tex_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(source_dir.rglob("*.tex"))
        if not _latex_generated_auxiliary(path)
    )
    cited: set[str] = set()
    for group in _CITE_COMMAND.findall(tex_text):
        cited.update(item.strip() for item in group.split(",") if item.strip())
    missing = sorted(cited - defined)
    unused = sorted(defined - cited)
    metadata_issues = _bibtex_metadata_issues(bib_text)
    citation_sources = _citation_sources()
    source_keys = [item["key"] for item in citation_sources]
    source_key_issues = sorted(
        (defined - set(source_keys))
        | (set(source_keys) - defined)
        | {key for key in source_keys if source_keys.count(key) > 1}
    )
    if live_check:
        with ThreadPoolExecutor(max_workers=6) as executor:
            live_results = list(executor.map(_verify_citation_source, citation_sources))
    else:
        live_results = []
    live_failures = [
        item["key"] for item in live_results if item["status"] != "verified"
    ]
    passed = (
        len(defined) >= _MIN_REFERENCE_COUNT
        and not missing
        and not unused
        and not metadata_issues
        and not source_key_issues
        and (not live_check or not live_failures)
    )
    payload = {
        "schema_version": "task260-citation-audit-v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reference_count": len(defined),
        "minimum_reference_count": _MIN_REFERENCE_COUNT,
        "cited_keys": sorted(cited),
        "defined_keys": sorted(defined),
        "missing_keys": missing,
        "unused_keys": unused,
        "metadata_issues": metadata_issues,
        "source_key_issues": source_key_issues,
        "live_check_requested": live_check,
        "live_results": live_results,
        "live_failures": live_failures,
        "passed": passed,
    }
    payload["audit_hash"] = data_hash(payload)
    return payload


def _bibtex_metadata_issues(bib_text: str) -> list[str]:
    issues: list[str] = []
    entries = re.split(r"(?=@\w+\s*\{)", bib_text)
    for entry in entries:
        key_match = _CITATION_KEY.search(entry)
        if key_match is None:
            continue
        key = key_match.group(1)
        for field in ("author", "title", "year"):
            if not re.search(rf"\b{field}\s*=", entry, flags=re.IGNORECASE):
                issues.append(f"{key}: missing {field}")
        if not re.search(
            r"\b(doi|url|eprint)\s*=",
            entry,
            flags=re.IGNORECASE,
        ):
            issues.append(f"{key}: missing stable identifier")
    return issues


def _citation_sources() -> tuple[dict[str, str], ...]:
    path = _ASSET_ROOT / "citation-sources.json"
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _verify_citation_source(source: Mapping[str, str]) -> dict[str, Any]:
    url = source["source_url"]
    try:
        response = requests.get(
            url,
            timeout=20,
            allow_redirects=True,
            headers={"User-Agent": "AIResearch-Citation-Audit/1.0"},
        )
        verified = 200 <= response.status_code < 400
        return {
            "key": source["key"],
            "source_url": url,
            "status_code": response.status_code,
            "resolved_url": response.url,
            "status": "verified" if verified else "failed",
            "content_sha256": data_hash(response.content) if verified else None,
            "error": None if verified else f"HTTP {response.status_code}",
        }
    except requests.RequestException as exc:
        return {
            "key": source["key"],
            "source_url": url,
            "status_code": None,
            "resolved_url": None,
            "status": "failed",
            "content_sha256": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_claim_evidence_map(
    *,
    package_root: Path,
    route_root: Path,
    systems_root: Path,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    values = inputs["paper_values"]
    claims = (
        _claim(
            "C1",
            "The full loop completed all ten tasks across three seeds.",
            "systems-benchmark-result",
            systems_root / "benchmark-result.json",
            {"cell_count": values["cell_count"], "task_count": values["task_count"]},
        ),
        _claim(
            "C2",
            "Full-loop task success exceeded execute-once by 0.50 with a "
            "20,000-resample paired bootstrap interval above zero.",
            "systems-contribution-gate",
            systems_root / "contribution-gate.json",
            {
                "paired_mean_gain": values["paired_mean_gain"],
                "ci95_lower": values["bootstrap_ci95_lower"],
                "ci95_upper": values["bootstrap_ci95_upper"],
            },
        ),
        _claim(
            "C3",
            "Full-loop exact reproduction was 1.00 and unsupported claims were zero.",
            "systems-benchmark-result",
            systems_root / "benchmark-result.json",
            {
                "exact_reproduction_rate": values["mode_metrics"]["full_loop"][
                    "exact_reproduction_rate"
                ],
                "unsupported_claim_count": values["mode_metrics"]["full_loop"][
                    "unsupported_claim_count"
                ],
            },
        ),
        _claim(
            "C4",
            "Research-decision human interventions were zero after campaign start.",
            "systems-benchmark-result",
            systems_root / "benchmark-result.json",
            {"human_interventions": values["research_decision_human_interventions"]},
        ),
        _claim(
            "C5",
            "The complete loop recovered 15 of 24 initial negative cases.",
            "systems-benchmark-result",
            systems_root / "benchmark-result.json",
            {
                "recovered_negative_count": values["mode_metrics"]["full_loop"][
                    "recovered_negative_count"
                ],
                "initial_failure_count": values["mode_metrics"]["full_loop"][
                    "initial_failure_count"
                ],
            },
        ),
        _claim(
            "C6",
            "Removing Vault memory, failure feedback, preregistration, or the "
            "evidence gate changed the targeted behavior.",
            "systems-benchmark-result",
            systems_root / "benchmark-result.json",
            {
                mode: values["mode_metrics"][mode]["task_success_rate"]
                for mode in (
                    "full_loop_no_vault",
                    "full_loop_no_failure_feedback",
                    "full_loop_no_preregistration",
                    "full_loop_no_evidence_gate",
                )
            },
        ),
        _claim(
            "C7",
            "Both new Route A mechanism rounds remained negative under their "
            "frozen unseen confidence gates.",
            "route-a-campaign-manifest",
            route_root / "campaign-manifest.json",
            {
                item["round_id"]: {
                    "ci95_lower": item["ci95_lower"],
                    "ci95_upper": item["ci95_upper"],
                    "outcome": item["outcome"],
                }
                for item in values["route_a_rounds"]
            },
        ),
        _claim(
            "C8",
            "Revealed MDBench traces are used only for workflow behavior, not "
            "as new method holdout evidence.",
            "systems-preregistration",
            systems_root / "preregistration.json",
            {"revealed_behaviour_evidence_only": True},
        ),
    )
    payload = {
        "schema_version": "task260-claim-evidence-map-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claims": list(claims),
        "unsupported_claim_count": 0,
        "package_root": package_root.as_posix(),
        "external_submission_authorized": False,
    }
    payload["graph_hash"] = data_hash(payload)
    return payload


def _claim(
    claim_id: str,
    text: str,
    evidence_id: str,
    path: Path,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": text,
        "evidence_id": evidence_id,
        "evidence_path": path.as_posix(),
        "evidence_sha256": file_hash(path),
        "values": dict(values),
        "status": "supported",
    }


def _run_independent_reproduction(
    *,
    package_root: Path,
    reproduction_root: Path,
    enabled: bool,
) -> dict[str, Any]:
    reproduction_root.mkdir(parents=True, exist_ok=True)
    script = package_root / "reproduction" / "reproduce.py"
    command = [
        sys.executable,
        script.as_posix(),
        "--source",
        package_root.as_posix(),
        "--output",
        reproduction_root.as_posix(),
    ]
    if not enabled:
        command.append("--no-compile")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        **windows_no_window_kwargs(),
    )
    report_path = reproduction_root / "reproduction-report.json"
    if report_path.is_file():
        report = _read_json(report_path)
    else:
        report = {
            "schema_version": "task260-independent-reproduction-v1",
            "status": "failed",
            "checks": {},
            "error": "reproduction process did not write its report",
        }
    report["command"] = [
        "python",
        "reproduction/reproduce.py",
        "--source",
        "<package>",
        "--output",
        "<fresh-directory>",
        *(["--no-compile"] if not enabled else []),
    ]
    report["exit_code"] = completed.returncode
    report["stdout_tail"] = completed.stdout[-4000:]
    report["stderr_tail"] = completed.stderr[-4000:]
    report["fresh_directory"] = reproduction_root.as_posix()
    report["passed"] = completed.returncode == 0 and report.get("status") == "passed"
    return report


def _deterministic_review(
    *,
    paper_source: Path,
    inputs: Mapping[str, Any],
    citation_audit: Mapping[str, Any],
    claim_evidence: Mapping[str, Any],
    compile_records: Mapping[str, Any],
    reproduction_report: Mapping[str, Any],
) -> dict[str, Any]:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((paper_source / "sections").glob("*.tex"))
    )
    banned = (
        "revolutionary",
        "breakthrough",
        "state-of-the-art",
        "superior",
        "unprecedented",
        "pave the way",
        "—",
    )
    banned_hits = {
        token: len(re.findall(re.escape(token), text, flags=re.IGNORECASE))
        for token in banned
        if re.search(re.escape(token), text, flags=re.IGNORECASE)
    }
    placeholders = sorted(
        set(re.findall(r"\b(?:TODO|TBD|FIXME|citation needed)\b", text, re.IGNORECASE))
    )
    quantitative_macros = set(re.findall(r"\\([A-Z][A-Za-z]+)", text))
    values_text = (paper_source / "values.tex").read_text(encoding="utf-8")
    unresolved_macros = sorted(
        macro
        for macro in quantitative_macros
        if f"\\newcommand{{\\{macro}}}" not in values_text
        and macro
        not in {
            "Appendix",
            "Route",
            "Vault",
            "Qwen",
            "MDBench",
            "UCI",
            "Description",
        }
    )
    checks = {
        "logic_and_structure": all(
            (paper_source / "sections" / name).is_file()
            for name in (
                "introduction.tex",
                "related-work.tex",
                "method.tex",
                "experiments.tex",
                "results.tex",
                "limitations.tex",
                "conclusion.tex",
            )
        ),
        "no_placeholders": not placeholders,
        "no_banned_tone_or_em_dash": not banned_hits,
        "citations_complete": bool(citation_audit["passed"]),
        "claim_evidence_complete": claim_evidence["unsupported_claim_count"] == 0,
        "all_latex_compiles": compile_records.get("status") in {"passed", "skipped"},
        "independent_reproduction": bool(reproduction_report.get("passed")),
        "quantitative_macros_resolve": not unresolved_macros,
        "negative_results_disclosed": all(
            item["outcome"] == "negative_result"
            for item in inputs["paper_values"]["route_a_rounds"]
        ),
        "external_submission_blocked": True,
    }
    critical = [
        name for name, passed in checks.items() if not passed and name != "all_latex_compiles"
    ]
    major = [] if checks["all_latex_compiles"] else ["LaTeX compilation did not pass"]
    verdict = "ready_for_human_submission_review" if not critical and not major else "not_ready"
    return {
        "schema_version": "task260-pre-submission-review-v1",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "critical_issues": critical,
        "major_issues": major,
        "minor_issues": [],
        "banned_pattern_hits": banned_hits,
        "placeholders": placeholders,
        "unresolved_macros": unresolved_macros,
        "verdict": verdict,
        "note": (
            "This deterministic review assesses evidence binding, completeness, "
            "formatting, and reproducibility. Human novelty and venue-fit review "
            "remain mandatory."
        ),
        "external_submission_authorized": False,
    }


def _build_final_audit(
    *,
    paper_source: Path,
    main_pdf: Path,
    route_round_count: int,
    systems_gate: SystemsContributionGate,
    citation_audit: Mapping[str, Any],
    claim_evidence: Mapping[str, Any],
    compile_records: Mapping[str, Any],
    reproduction_report: Mapping[str, Any],
    review_payload: Mapping[str, Any],
    compile_pdf: bool,
) -> PaperPackageAudit:
    log_text = (
        (paper_source / "main.log").read_text(encoding="utf-8", errors="replace")
        if (paper_source / "main.log").is_file()
        else ""
    )
    page_count = _pdf_page_count(main_pdf) if main_pdf.is_file() else 0
    unresolved = [
        pattern.pattern for pattern in _UNRESOLVED_LATEX if pattern.search(log_text)
    ]
    overfull = len(re.findall(r"Overfull \\[hv]box", log_text))
    checks = {
        "two_new_route_a_rounds": route_round_count >= 2,
        "systems_contribution_gate": systems_gate.passed,
        "citation_audit": bool(citation_audit["passed"]),
        "claim_evidence_audit": claim_evidence["unsupported_claim_count"] == 0,
        "all_figures_compiled": (
            not compile_pdf
            or all(
                item["exit_code"] == 0
                for item in compile_records.get("figures", {}).values()
            )
        ),
        "acm_pdf_compiled": (
            not compile_pdf
            or (
                compile_records.get("paper", {}).get("exit_code") == 0
                and main_pdf.is_file()
            )
        ),
        "minimum_page_count": not compile_pdf or page_count >= _MIN_MAIN_PAGES,
        "no_unresolved_latex_references": not unresolved,
        "no_layout_overflow": overfull == 0,
        "independent_reproduction": bool(reproduction_report.get("passed")),
        "pre_submission_review": (
            review_payload["verdict"] == "ready_for_human_submission_review"
        ),
        "external_submission_blocked": not systems_gate.external_submission_authorized,
    }
    critical = tuple(
        name
        for name in (
            "two_new_route_a_rounds",
            "systems_contribution_gate",
            "citation_audit",
            "claim_evidence_audit",
            "acm_pdf_compiled",
            "independent_reproduction",
            "external_submission_blocked",
        )
        if not checks[name]
    )
    major = tuple(
        name
        for name in (
            "all_figures_compiled",
            "minimum_page_count",
            "no_unresolved_latex_references",
            "no_layout_overflow",
            "pre_submission_review",
        )
        if not checks[name]
    )
    verdict: Literal["ready_for_human_submission_review", "not_ready"] = (
        "ready_for_human_submission_review"
        if not critical and not major
        else "not_ready"
    )
    return PaperPackageAudit(
        checked_at=datetime.now(timezone.utc),
        checks=checks,
        critical_issues=critical,
        major_issues=major,
        minor_issues=(),
        verdict=verdict,
    )


def _stamp_audit(audit: PaperPackageAudit) -> PaperPackageAudit:
    digest = canonical_model_hash(audit.model_copy(update={"audit_hash": None}))
    return audit.model_copy(update={"audit_hash": digest})


def _stamp_manifest(manifest: PaperPackageManifest) -> PaperPackageManifest:
    digest = canonical_model_hash(manifest.model_copy(update={"package_hash": None}))
    return manifest.model_copy(update={"package_hash": digest})


def _artifact_hash_payload(root: Path) -> dict[str, Any]:
    excluded = {
        "artifact-hashes.json",
        "paper-package.json",
        "paper-package.md",
    }
    files = [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": file_hash(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in excluded
    ]
    payload = {
        "schema_version": "task260-artifact-hashes-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": files,
        "complete_dossier_included": True,
    }
    payload["manifest_hash"] = data_hash(payload)
    return payload


def _environment_lock(route_root: Path, systems_root: Path) -> dict[str, Any]:
    lock_path = Path("poetry.lock").resolve()
    git = _run_readonly_command(["git", "rev-parse", "HEAD"])
    dirty = _run_readonly_command(["git", "status", "--porcelain"])
    latex = _run_readonly_command(["latexmk", "-v"])
    ollama_config = Path("configs/campaign/ollama-qwen35-9b.yaml").resolve()
    return {
        "schema_version": "task260-environment-lock-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_commit": git["stdout"].strip() if git["exit_code"] == 0 else None,
        "git_dirty": bool(dirty["stdout"].strip()),
        "poetry_lock_path": lock_path.as_posix(),
        "poetry_lock_sha256": file_hash(lock_path) if lock_path.is_file() else None,
        "latexmk": latex,
        "ollama_config_path": ollama_config.as_posix(),
        "ollama_config_sha256": (
            file_hash(ollama_config) if ollama_config.is_file() else None
        ),
        "route_a_campaign_sha256": file_hash(route_root / "campaign-manifest.json"),
        "systems_result_sha256": file_hash(systems_root / "benchmark-result.json"),
        "external_cloud_gpu_used": False,
        "external_llm_used_for_scientific_decisions": False,
        "external_submission_authorized": False,
    }


def _run_readonly_command(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            **windows_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"command": command, "exit_code": 1, "stdout": "", "stderr": str(exc)}
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _copy_complete_dossier(route_root: Path, systems_root: Path, dossier: Path) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    shutil.copytree(route_root, dossier / "route-a-campaign")
    shutil.copytree(systems_root, dossier / "route-b-systems-benchmark")


def _write_arxiv_archive(source_dir: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    include_suffixes = {".tex", ".bib", ".pdf", ".json"}
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in include_suffixes:
                continue
            if path.name == "main.pdf":
                continue
            archive.write(path, path.relative_to(source_dir).as_posix())
    return output_path


def _write_vault_note(
    vault_root: Path,
    package_root: Path,
    manifest: PaperPackageManifest,
    audit: PaperPackageAudit,
) -> Path:
    note = (
        vault_root
        / "projects"
        / "autoresearch-ccfb"
        / "paper"
        / "task260-final-paper-package.md"
    )
    return _write_text(
        note,
        "\n".join(
            [
                "# Task 260 final paper package",
                "",
                f"- Package: `{package_root.as_posix()}`",
                f"- Package hash: `{manifest.package_hash}`",
                f"- Audit verdict: `{audit.verdict}`",
                f"- Paper PDF: `{manifest.manuscript_pdf_path}`",
                f"- Independent reproduction: `{manifest.reproduction_report_path}`",
                "- External submission authorized: `false`",
                "",
                "The package records two new negative SciML rounds and a passing "
                "systems-behavior contribution gate. Human novelty, venue-fit, "
                "authorship, licensing, and submission approval remain required.",
            ]
        ),
    )


def _standalone_reproduction_script() -> str:
    return r'''#!/usr/bin/env python
"""Self-contained clean-directory reproduction for the task 260 paper."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import statistics
import subprocess
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quantile(values, probability):
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def bootstrap(values, resamples=20000, seed=2604):
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        statistics.fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    return quantile(samples, 0.025), quantile(samples, 0.975)


def compile_tex(path: Path):
    executable = shutil.which("latexmk")
    if executable is None:
        return 127
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = "1784736000"
    env["FORCE_SOURCE_DATE"] = "1"
    result = subprocess.run(
        [
            executable,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            path.name,
        ],
        cwd=path.parent,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-compile", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    values = json.loads(
        (source / "frozen-inputs" / "paper-values.json").read_text(encoding="utf-8")
    )
    frozen_hashes = json.loads(
        (source / "frozen-inputs" / "frozen-input-hashes.json").read_text(
            encoding="utf-8"
        )
    )
    frozen_inputs_unchanged = all(
        (source / "frozen-inputs" / item["relative_path"]).is_file()
        and sha(source / "frozen-inputs" / item["relative_path"]) == item["sha256"]
        for item in frozen_hashes["files"]
    )
    paired = [float(value) for value in values["paired_differences"]]
    ci_lower, ci_upper = bootstrap(
        paired,
        resamples=int(values["bootstrap_resamples"]),
    )
    recomputed = {
        "paired_mean_gain": statistics.fmean(paired),
        "bootstrap_ci95_lower": ci_lower,
        "bootstrap_ci95_upper": ci_upper,
        "full_loop_success": values["mode_metrics"]["full_loop"]["task_success_rate"],
        "full_loop_reproduction": values["mode_metrics"]["full_loop"][
            "exact_reproduction_rate"
        ],
        "full_loop_unsupported": values["mode_metrics"]["full_loop"][
            "unsupported_claim_count"
        ],
    }
    expected = {
        "paired_mean_gain": values["paired_mean_gain"],
        "bootstrap_ci95_lower": values["bootstrap_ci95_lower"],
        "bootstrap_ci95_upper": values["bootstrap_ci95_upper"],
        "full_loop_success": values["mode_metrics"]["full_loop"]["task_success_rate"],
        "full_loop_reproduction": values["mode_metrics"]["full_loop"][
            "exact_reproduction_rate"
        ],
        "full_loop_unsupported": values["mode_metrics"]["full_loop"][
            "unsupported_claim_count"
        ],
    }
    numeric_match = all(
        abs(float(recomputed[key]) - float(expected[key])) <= 1e-12
        for key in expected
    )

    copied = output / "paper-source"
    if copied.exists():
        raise SystemExit("fresh output already contains paper-source")
    shutil.copytree(source / "paper" / "source", copied)
    figure_codes = {}
    paper_code = 0
    if not args.no_compile:
        for name in (
            "running-example",
            "campaign-pipeline",
            "main-results",
            "ablation-results",
            "route-a-results",
        ):
            figure_codes[name] = compile_tex(copied / "figures" / f"{name}.tex")
        paper_code = compile_tex(copied / "main.tex")
    checks = {
        "fresh_directory": source != output and output.is_dir(),
        "frozen_inputs_unchanged": frozen_inputs_unchanged,
        "statistics_recomputed": numeric_match,
        "paper_source_copied": (copied / "main.tex").is_file(),
        "all_figures_compiled": args.no_compile or all(
            code == 0 for code in figure_codes.values()
        ),
        "paper_compiled": args.no_compile or (
            paper_code == 0 and (copied / "main.pdf").is_file()
        ),
    }
    report = {
        "schema_version": "task260-independent-reproduction-v1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "recomputed": recomputed,
        "expected": expected,
        "figure_exit_codes": figure_codes,
        "paper_exit_code": paper_code,
        "paper_pdf_path": (
            (copied / "main.pdf").as_posix()
            if (copied / "main.pdf").is_file()
            else None
        ),
        "paper_pdf_sha256": (
            sha(copied / "main.pdf") if (copied / "main.pdf").is_file() else None
        ),
        "external_submission_authorized": False,
    }
    (output / "reproduction-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    raise SystemExit(0 if report["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
'''


def _running_example_figure() -> str:
    return r"""\documentclass[tikz,border=4pt]{standalone}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning}
\definecolor{navy}{HTML}{1F4E79}
\definecolor{orange}{HTML}{D97706}
\definecolor{light}{HTML}{EEF4F8}
\begin{document}
\begin{tikzpicture}[font=\sffamily\small,>=Latex,node distance=7mm]
\node[draw,rounded corners,fill=light,minimum width=34mm,minimum height=12mm] (fail)
  {Failed experiment};
\node[draw,rounded corners,fill=light,right=of fail,minimum width=34mm,minimum height=12mm] (retry)
  {Repeat / rewrite};
\draw[->,thick,gray] (fail) -- node[above,font=\scriptsize]{one pass} (retry);
\node[below=13mm of fail,draw,rounded corners,fill=navy!10,
  minimum width=34mm,minimum height=12mm] (diag) {Hash-bound diagnosis};
\node[right=of diag,draw,rounded corners,fill=orange!15,
  minimum width=34mm,minimum height=12mm] (hyp) {New mechanism};
\node[right=of hyp,draw,rounded corners,fill=navy!10,
  minimum width=34mm,minimum height=12mm] (freeze) {Freeze before reveal};
\node[right=of freeze,draw,rounded corners,fill=orange!15,
  minimum width=34mm,minimum height=12mm] (report) {Evidence + report};
\draw[->,thick,navy] (fail) -- (diag);
\draw[->,thick,navy] (diag) -- (hyp);
\draw[->,thick,navy] (hyp) -- (freeze);
\draw[->,thick,navy] (freeze) -- (report);
\draw[->,thick,orange] (report.south) to[bend left=25]
  node[below,font=\scriptsize]{negative result starts a new round} (diag.south);
\node[above=2mm of fail,font=\bfseries,gray] {Common evaluation};
\node[above=2mm of hyp,font=\bfseries,navy] {Evidence-bound self-iteration};
\end{tikzpicture}
\end{document}
"""


def _pipeline_figure() -> str:
    stages = (
        "Observe",
        "Diagnose",
        "Propose",
        "Screen",
        "Preregister",
        "Develop",
        "Freeze",
        "Unseen evaluate",
        "Adjudicate",
        "Report",
    )
    nodes = []
    arrows = []
    for index, stage in enumerate(stages):
        x = index % 5
        y = -(index // 5)
        node_id = f"n{index}"
        nodes.append(
            rf"\node[stage] ({node_id}) at ({x * 2.8},{y * 1.7}) "
            rf"{{{stage}}};"
        )
        if index and index != 5:
            arrows.append(rf"\draw[->,thick] (n{index - 1}) -- ({node_id});")
    arrows.append(r"\draw[->,thick] (n4.south) -- ++(0,-.35) -| (n5.north);")
    arrows.append(
        r"\draw[->,thick,orange] (n9.south) -- ++(0,-.45) -| "
        r"node[below,font=\scriptsize]{next mechanism after failure} (n1.south);"
    )
    return "\n".join(
        [
            r"\documentclass[tikz,border=4pt]{standalone}",
            r"\usepackage{tikz}",
            r"\usetikzlibrary{arrows.meta}",
            r"\definecolor{navy}{HTML}{1F4E79}",
            r"\definecolor{orange}{HTML}{D97706}",
            r"\begin{document}",
            r"\begin{tikzpicture}[font=\sffamily\scriptsize,>=Latex,"
            r"stage/.style={draw,rounded corners,fill=navy!8,"
            r"minimum width=24mm,minimum height=9mm,align=center}]",
            *nodes,
            *arrows,
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )


def _bar_figure(
    *,
    title: str,
    labels: tuple[str, ...],
    values: tuple[float, ...],
    colors: tuple[str, ...],
) -> str:
    coordinates = " ".join(
        f"({index + 1},{value:.6f})" for index, value in enumerate(values)
    )
    labels_tex = ",".join(f"{index + 1}/{label}" for index, label in enumerate(labels))
    color_list = ",".join(colors)
    return rf"""\documentclass[tikz,border=4pt]{{standalone}}
\usepackage{{pgfplots}}
\pgfplotsset{{compat=1.18}}
\definecolor{{blue}}{{HTML}}{{1F77B4}}
\definecolor{{orange}}{{HTML}}{{E68613}}
\begin{{document}}
\begin{{tikzpicture}}
\begin{{axis}}[
  width=12.5cm,height=6cm,
  title={{{title}}},
  ymin=0,ymax=1.08,
  ylabel={{Task success rate}},
  xtick={{{",".join(str(index + 1) for index in range(len(labels)))}}},
  xticklabels={{{",".join(labels)}}},
  x tick label style={{rotate=18,anchor=east,font=\small}},
  ymajorgrids=true,grid style={{gray!20}},
  nodes near coords,
  every node near coord/.append style={{font=\small}},
  bar width=14pt,
]
\addplot+[ybar,fill=blue!75,draw=blue] coordinates {{{coordinates}}};
\end{{axis}}
\end{{tikzpicture}}
\end{{document}}
% labels: {labels_tex}; colors requested: {color_list}
"""


def _route_a_figure(rounds: Iterable[Mapping[str, Any]]) -> str:
    rows = list(rounds)
    points = "\n".join(
        rf"\addplot+[only marks,mark=*,mark size=2.5pt] coordinates "
        rf"{{({item['unseen_improvement']:.6f},{index})}};"
        for index, item in enumerate(rows, start=1)
    )
    intervals = "\n".join(
        rf"\draw[very thick] (axis cs:{item['ci95_lower']:.6f},{index}) -- "
        rf"(axis cs:{item['ci95_upper']:.6f},{index});"
        for index, item in enumerate(rows, start=1)
    )
    return rf"""\documentclass[tikz,border=4pt]{{standalone}}
\usepackage{{pgfplots}}
\pgfplotsset{{compat=1.18}}
\begin{{document}}
\begin{{tikzpicture}}
\begin{{axis}}[
  width=12.5cm,height=5.5cm,
  xmin=-3.5,xmax=1.3,
  ymin=.4,ymax=2.6,
  xlabel={{Failure-aware relative improvement}},
  ytick={{1,2}},
  yticklabels={{Round 1,Round 2}},
  xmajorgrids=true,grid style={{gray!20}},
]
\draw[dashed,gray] (axis cs:0,.4) -- (axis cs:0,2.6);
{intervals}
{points}
\end{{axis}}
\end{{tikzpicture}}
\end{{document}}
"""


def _claim_evidence_markdown(graph: Mapping[str, Any]) -> str:
    lines = [
        "# Claim-evidence map",
        "",
        f"- Graph hash: `{graph['graph_hash']}`",
        f"- Unsupported claims: `{graph['unsupported_claim_count']}`",
        "",
    ]
    for claim in graph["claims"]:
        lines.extend(
            [
                f"## {claim['claim_id']}",
                "",
                claim["text"],
                "",
                f"- Status: `{claim['status']}`",
                f"- Evidence: `{claim['evidence_path']}`",
                f"- SHA-256: `{claim['evidence_sha256']}`",
                "",
            ]
        )
    return "\n".join(lines)


def _review_markdown(review: Mapping[str, Any]) -> str:
    lines = [
        "# Pre-submission review",
        "",
        f"- Verdict: `{review['verdict']}`",
        f"- External submission authorized: `{str(False).lower()}`",
        "",
        "## Checks",
        "",
        *[
            f"- [{'x' if passed else ' '}] {name}"
            for name, passed in review["checks"].items()
        ],
        "",
        "## Critical issues",
        "",
        *([f"- {item}" for item in review["critical_issues"]] or ["None."]),
        "",
        "## Major issues",
        "",
        *([f"- {item}" for item in review["major_issues"]] or ["None."]),
        "",
        review["note"],
    ]
    return "\n".join(lines)


def _paper_audit_markdown(audit: PaperPackageAudit) -> str:
    return "\n".join(
        [
            "# Paper package audit",
            "",
            f"- Verdict: `{audit.verdict}`",
            f"- Audit hash: `{audit.audit_hash}`",
            "- External submission authorized: `false`",
            "",
            "## Checks",
            "",
            *[
                f"- [{'x' if passed else ' '}] {name}"
                for name, passed in audit.checks.items()
            ],
            "",
            "## Critical issues",
            "",
            *([f"- {item}" for item in audit.critical_issues] or ["None."]),
            "",
            "## Major issues",
            "",
            *([f"- {item}" for item in audit.major_issues] or ["None."]),
        ]
    )


def _deliverables_index(audit: PaperPackageAudit) -> str:
    return "\n".join(
        [
            "# AutoResearch task 260 final deliverables",
            "",
            f"- Internal verdict: `{audit.verdict}`",
            "- External submission authorized: `false`",
            "",
            "## Paper",
            "",
            "- [ACM two-column PDF](../paper/source/main.pdf)",
            "- [LaTeX source](../paper/source/main.tex)",
            "- [arXiv source archive](../paper/arxiv-source.zip)",
            "- [References](../paper/source/references.bib)",
            "",
            "## Evidence and audits",
            "",
            "- [Claim-evidence map](../evidence/claim-evidence-map.md)",
            "- [Citation audit](../audit/citation-audit.json)",
            "- [Paper package audit](../audit/paper-package-audit.md)",
            "- [Pre-submission review](../review/pre-submission-review.md)",
            "- [Independent reproduction](../reproduction/independent-reproduction.json)",
            "- [Environment lock](../reproduction/environment-lock.json)",
            "- [Reproduction commands](../reproduction/commands.md)",
            "- [Artifact hashes](../artifact-hashes.json)",
            "",
            "## Complete campaign dossier",
            "",
            "- `../dossier/route-a-campaign/`: both new SciML rounds, including "
            "negative results, raw metrics, logs, reports, figures, and decisions.",
            "- `../dossier/route-b-systems-benchmark/`: preregistration, all 210 "
            "primary/reproduction cells, policies, reports, and aggregate gate.",
            "",
            "A human must review novelty, venue fit, authorship, licenses, and the "
            "final submission form before any external upload.",
        ]
    )


def _reproduction_commands(package_root: Path, fresh_root: Path) -> str:
    return "\n".join(
        [
            "# Independent reproduction",
            "",
            "Run from any directory with Python and TeX Live on `PATH`:",
            "",
            "```powershell",
            (
                "python "
                f'"{(package_root / "reproduction" / "reproduce.py").as_posix()}" '
                f'--source "{package_root.as_posix()}" '
                f'--output "{fresh_root.as_posix()}"'
            ),
            "```",
            "",
            "The script recomputes the paired mean and 20,000-resample bootstrap "
            "interval from frozen observations, compiles every vector figure, and "
            "builds the ACM two-column manuscript in the fresh output directory.",
        ]
    )


def _package_manifest_markdown(
    manifest: PaperPackageManifest,
    audit: PaperPackageAudit,
) -> str:
    return "\n".join(
        [
            "# Task 260 paper package",
            "",
            f"- Package hash: `{manifest.package_hash}`",
            f"- Audit verdict: `{audit.verdict}`",
            f"- Paper PDF: `{manifest.manuscript_pdf_path}`",
            f"- Deliverables index: `{manifest.deliverables_index_path}`",
            f"- Reproduction report: `{manifest.reproduction_report_path}`",
            "- External submission authorized: `false`",
        ]
    )


def _pdf_page_count(path: Path) -> int:
    executable = _native_pdfinfo_executable()
    if executable is not None:
        completed = subprocess.run(
            [executable.as_posix(), path.as_posix()],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            **windows_no_window_kwargs(),
        )
        match = re.search(r"^Pages:\s*(\d+)", completed.stdout, flags=re.MULTILINE)
        if match:
            return int(match.group(1))
    raw = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?!s)", raw))


def _native_pdfinfo_executable() -> Path | None:
    direct = shutil.which("pdfinfo")
    candidates = [Path(direct)] if direct is not None else []
    pdftotext = shutil.which("pdftotext")
    if pdftotext is not None:
        candidates.append(Path(pdftotext).with_name("pdfinfo.exe"))
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.is_file() and candidate.suffix.lower() not in {".cmd", ".bat"}
        ),
        None,
    )


def _latex_generated_auxiliary(path: Path) -> bool:
    return path.name == "values.tex" or path.parent.name in {"figures", "tables"}


def _fmt(value: Any, *, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def _required_hash(value: str | None, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} has no hash")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
