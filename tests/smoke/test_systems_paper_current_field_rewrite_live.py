"""Opt-in live verification for the Task 263.7.2 manuscript package."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.research.systems_paper_currency_audit import (
    ParentSystemsPaperEvidence,
)
from autoresearch.research.systems_paper_current_field_rewrite import (
    execute_current_field_manuscript_rewrite,
    load_current_field_manuscript_rewrite,
)

LIVE_ENV = "AUTORESEARCH_SYSTEMS_PAPER_REWRITE_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SYSTEMS_PAPER_REWRITE_OUTPUT"

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "runs/manual-live/task260-final-paper-v2"
AUDIT = ROOT / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
REANALYSIS = ROOT / "runs/manual-live/task26371-independent-task-reanalysis-v1"
DEFAULT_OUTPUT = ROOT / "runs/manual-live/task26372-current-field-manuscript-v1"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to validate the frozen source bindings, compiled PDF, "
        "citation status, visual review, and human-owned publication gates"
    ),
)


def test_live_current_field_manuscript_rewrite() -> None:
    output = Path(os.getenv(OUTPUT_ENV, str(DEFAULT_OUTPUT))).resolve()
    parent_before = ParentSystemsPaperEvidence.from_package(PARENT)

    if not (output / "current-field-manuscript-manifest.json").is_file():
        report, _ = execute_current_field_manuscript_rewrite(
            parent_package_dir=PARENT,
            audit_dir=AUDIT,
            reanalysis_dir=REANALYSIS,
            output_dir=output,
        )
        raise AssertionError(
            "the paper was built successfully but its page-by-page visual review is "
            f"still pending ({report.manuscript_page_count} pages)"
        )

    report, manifest = load_current_field_manuscript_rewrite(output)
    build = json.loads((output / "latex-build.json").read_text(encoding="utf-8"))
    language = json.loads(
        (output / "language-scan.json").read_text(encoding="utf-8")
    )
    latex = json.loads((output / "latex-audit.json").read_text(encoding="utf-8"))
    visual = json.loads((output / "visual-review.json").read_text(encoding="utf-8"))
    review = json.loads(
        (output / "pre-submission-review.json").read_text(encoding="utf-8")
    )

    assert ParentSystemsPaperEvidence.from_package(PARENT) == parent_before
    assert report.rewrite_gate_passed is True
    assert report.resolved_surface_count == 28
    assert report.source_count == 29
    assert language["no_banned_tone_or_em_dash"] is True
    assert language["hits"] == []
    assert latex["passed"] is True
    assert build["passed"] is True
    assert build["figure_count"] == 7
    assert build["overfull_box_count"] == 0
    assert build["undefined_reference_warning_count"] == 0
    assert build["undefined_citation_warning_count"] == 0
    assert visual["status"] == "passed"
    assert visual["inspected_pages"] == list(range(1, report.manuscript_page_count + 1))
    assert review["rewrite_gate_passed"] is True
    assert report.publication_ready is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert manifest.report_hash == report.report_hash
