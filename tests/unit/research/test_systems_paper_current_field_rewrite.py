"""Tests for the Task 263.7.2 current-field manuscript rewrite."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research.systems_paper_currency_audit import (
    ParentSystemsPaperEvidence,
    load_systems_paper_currency_audit,
)
from autoresearch.research.systems_paper_current_field_rewrite import (
    ASSET_ROOT,
    CurrentFieldRewriteIntegrityError,
    VisualReview,
    audit_latex_source,
    build_citation_registry,
    build_current_field_claim_ledger,
    build_section_outline,
    build_surface_resolution_ledger,
    execute_current_field_manuscript_rewrite,
    load_current_field_manuscript_rewrite,
)
from autoresearch.research.systems_paper_task_unit_reanalysis import (
    load_task_unit_reanalysis,
)

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "runs/manual-live/task260-final-paper-v2"
AUDIT = ROOT / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
REANALYSIS = ROOT / "runs/manual-live/task26371-independent-task-reanalysis-v1"
PACKAGE = ROOT / "runs/manual-live/task26372-current-field-manuscript-v1"


def test_section_outline_freezes_narrow_claim_boundary() -> None:
    outline = build_section_outline()

    assert len(outline["sections"]) == 9
    assert outline["study_position"] == "controlled-evidence-state-machine-demonstration"
    assert "does not support" in outline["global_claim_boundary"]
    assert all(item["forbidden_inference"] for item in outline["sections"])


def test_citation_registry_has_exact_keys_and_source_maturity() -> None:
    audit, _ = load_systems_paper_currency_audit(AUDIT)

    registry = build_citation_registry(ASSET_ROOT, audit)

    assert registry["citation_key_count"] == 29
    assert registry["missing_bibliography_keys"] == []
    assert registry["unused_bibliography_keys"] == []
    assert registry["all_citations_nonbreaking"] is True
    assert registry["status_counts"]["peer-reviewed"] == 9
    assert registry["status_counts"]["preprint-not-peer-reviewed"] == 5
    assert registry["status_counts"]["normative-standard-or-policy"] == 3
    current = [
        item
        for item in registry["entries"]
        if item["verification_basis"] == "task26370-primary-source-snapshot"
    ]
    assert len(current) == 17
    assert all(item["snapshot_hash"] and item["source_record_hash"] for item in current)


def test_all_claims_and_28_surfaces_are_consumed() -> None:
    reanalysis, _ = load_task_unit_reanalysis(REANALYSIS)
    source_dir = PACKAGE / "paper/source"

    claims = build_current_field_claim_ledger(reanalysis)
    surfaces = build_surface_resolution_ledger(source_dir, reanalysis)

    assert claims["claim_count"] == 8
    assert claims["retired_publication_inference_claim_ids"] == ["C2"]
    assert all(
        item["publication_superiority_inference_allowed"] is False
        for item in claims["claims"]
    )
    assert surfaces["source_surface_count"] == 28
    assert surfaces["resolved_surface_count"] == 28
    assert surfaces["unresolved_surface_count"] == 0
    assert len({item["surface_id"] for item in surfaces["resolutions"]}) == 28


def test_final_source_audit_has_no_positioning_or_latex_findings() -> None:
    latex = audit_latex_source(PACKAGE / "paper/source")

    assert latex["passed"] is True
    assert latex["findings"] == []
    assert latex["self_certified_positioning_table_present"] is False
    assert latex["citation_key_count"] == latex["bibliography_key_count"] == 29
    assert latex["figure_environment_count"] == latex["description_count"] == 7
    assert latex["nonvector_figures"] == []


def test_final_report_passes_rewrite_gate_but_not_publication_gate() -> None:
    report, manifest = load_current_field_manuscript_rewrite(PACKAGE)

    assert report.rewrite_gate_passed is True
    assert report.unresolved_rewrite_findings == []
    assert report.resolved_surface_count == 28
    assert report.manuscript_page_count == 10
    assert report.publication_ready is False
    assert report.independent_confirmation_complete is False
    assert report.independent_human_review_complete is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert manifest.report_hash == report.report_hash


def test_visual_review_fails_closed_when_a_page_is_missing() -> None:
    payload = json.loads((PACKAGE / "visual-review.json").read_text(encoding="utf-8"))
    payload["inspected_pages"] = payload["inspected_pages"][:-1]

    with pytest.raises(ValidationError, match="inspect every PDF page"):
        VisualReview.model_validate(payload)


def test_recursive_manifest_detects_tampering(tmp_path: Path) -> None:
    copied = tmp_path / "rewrite"
    shutil.copytree(PACKAGE, copied)
    target = copied / "section-evidence-outline.json"
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(CurrentFieldRewriteIntegrityError, match="file hash changed"):
        load_current_field_manuscript_rewrite(copied)


def test_partial_output_fails_before_any_parent_write(tmp_path: Path) -> None:
    output = tmp_path / "partial"
    output.mkdir()
    (output / "unexpected.txt").write_text("partial", encoding="utf-8")
    parent_before = ParentSystemsPaperEvidence.from_package(PARENT)

    with pytest.raises(CurrentFieldRewriteIntegrityError, match="partial output"):
        execute_current_field_manuscript_rewrite(
            parent_package_dir=PARENT,
            audit_dir=AUDIT,
            reanalysis_dir=REANALYSIS,
            output_dir=output,
        )

    assert ParentSystemsPaperEvidence.from_package(PARENT) == parent_before
