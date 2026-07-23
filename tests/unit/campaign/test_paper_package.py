from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import autoresearch.campaign.paper as paper_module
from autoresearch.campaign.paper import (
    _ASSET_ROOT,
    PaperPackageAudit,
    PaperPackageManifest,
    _audit_citations,
    _pdf_page_count,
    _run_independent_reproduction,
    _stamp_audit,
    _stamp_manifest,
    _standalone_reproduction_script,
    validate_task260_paper_package,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.schemas import file_hash


def test_paper_assets_have_complete_traceable_bibliography() -> None:
    audit = _audit_citations(_ASSET_ROOT, live_check=False)

    assert audit["passed"] is True
    assert audit["reference_count"] == 40
    assert audit["missing_keys"] == []
    assert audit["unused_keys"] == []
    assert audit["metadata_issues"] == []
    assert audit["source_key_issues"] == []


def test_clean_directory_reproduction_recomputes_frozen_statistics(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    frozen = package / "frozen-inputs"
    source = package / "paper" / "source"
    reproduction = package / "reproduction"
    frozen.mkdir(parents=True)
    source.mkdir(parents=True)
    reproduction.mkdir(parents=True)
    values = {
        "paired_differences": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        * 3,
        "bootstrap_resamples": 20_000,
        "paired_mean_gain": 0.5,
        "bootstrap_ci95_lower": 0.3333333333333333,
        "bootstrap_ci95_upper": 0.6666666666666666,
        "mode_metrics": {
            "full_loop": {
                "task_success_rate": 1.0,
                "exact_reproduction_rate": 1.0,
                "unsupported_claim_count": 0,
            }
        },
    }
    values_path = frozen / "paper-values.json"
    values_path.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")
    (frozen / "frozen-input-hashes.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "relative_path": "paper-values.json",
                        "sha256": _sha256(values_path),
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (source / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}test\\end{document}\n",
        encoding="utf-8",
    )
    (reproduction / "reproduce.py").write_text(
        _standalone_reproduction_script(),
        encoding="utf-8",
    )

    report = _run_independent_reproduction(
        package_root=package,
        reproduction_root=tmp_path / "fresh",
        enabled=False,
    )

    assert report["passed"] is True
    assert report["checks"]["fresh_directory"] is True
    assert report["checks"]["frozen_inputs_unchanged"] is True
    assert report["checks"]["statistics_recomputed"] is True

    values["paired_mean_gain"] = 0.4
    values_path.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")
    tampered = _run_independent_reproduction(
        package_root=package,
        reproduction_root=tmp_path / "fresh-tampered",
        enabled=False,
    )
    assert tampered["passed"] is False
    assert tampered["checks"]["frozen_inputs_unchanged"] is False


def test_package_status_binds_artifact_hash_manifest(tmp_path: Path) -> None:
    root = tmp_path / "paper-package"
    root.mkdir()
    artifact = root / "artifact.txt"
    artifact.write_text("evidence\n", encoding="utf-8")
    audit = _stamp_audit(
        PaperPackageAudit(
            checked_at=datetime.now(timezone.utc),
            checks={"external_submission_blocked": True},
            verdict="ready_for_human_submission_review",
        )
    )
    audit_path = root / "paper-audit.json"
    write_json_model(audit_path, audit)
    hash_path = root / "artifact-hashes.json"
    hash_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "relative_path": artifact.name,
                        "sha256": file_hash(artifact),
                        "size_bytes": artifact.stat().st_size,
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = _stamp_manifest(
        PaperPackageManifest(
            package_id=root.name,
            created_at=datetime.now(timezone.utc),
            route_a_campaign_path="route-a",
            route_a_lineage_hash="a" * 64,
            systems_benchmark_path="route-b",
            systems_result_hash="b" * 64,
            systems_gate_hash="c" * 64,
            manuscript_tex_path="main.tex",
            manuscript_pdf_path=None,
            arxiv_source_path="arxiv.zip",
            citation_audit_path="citation.json",
            evidence_graph_path="evidence.json",
            review_path="review.json",
            reproduction_report_path="reproduction.json",
            environment_lock_path="environment.json",
            artifact_hashes_path=hash_path.as_posix(),
            artifact_hashes_sha256=file_hash(hash_path),
            deliverables_index_path="index.md",
            paper_audit_path=audit_path.as_posix(),
            paper_audit_hash=audit.audit_hash or "",
        )
    )
    write_json_model(root / "paper-package.json", manifest)

    result = validate_task260_paper_package(root)

    assert result.verdict == "ready_for_human_submission_review"
    assert result.external_submission_authorized is False

    hash_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash manifest mismatch"):
        validate_task260_paper_package(root)


def test_pdf_page_count_uses_native_pdfinfo_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr(
        paper_module,
        "_native_pdfinfo_executable",
        lambda: Path("C:/texlive/pdfinfo.exe"),
    )
    monkeypatch.setattr(
        paper_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="Pages:           11\n",
            stderr="",
        ),
    )

    assert _pdf_page_count(pdf) == 11


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
