"""Opt-in real-parent smoke for the Task 263.7.1 additive reanalysis."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.systems_paper_currency_audit import PARENT_GIT_COMMIT
from autoresearch.research.systems_paper_task_unit_reanalysis import (
    AUDIT_GIT_COMMIT,
    AUDIT_MANIFEST_HASH,
    AUDIT_PROJECTION_HASH,
    AUDIT_REPORT_HASH,
    REANALYSIS_MANIFEST_FILENAME,
    ManuscriptSurfaceDisposition,
    OriginalClaimDisposition,
    execute_task_unit_reanalysis,
    load_task_unit_reanalysis,
)

LIVE_ENV = "AUTORESEARCH_SYSTEMS_PAPER_TASK_UNIT_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SYSTEMS_PAPER_TASK_UNIT_OUTPUT"
PARENT_ENV = "AUTORESEARCH_TASK260_PAPER_PACKAGE"
AUDIT_ENV = "AUTORESEARCH_TASK26370_CURRENCY_AUDIT_PACKAGE"
INTERPRETER_A_ENV = "AUTORESEARCH_SYSTEMS_PAPER_TASK_UNIT_AUDITOR_A"
INTERPRETER_B_ENV = "AUTORESEARCH_SYSTEMS_PAPER_TASK_UNIT_AUDITOR_B"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARENT = ROOT / "runs/manual-live/task260-final-paper-v2"
DEFAULT_AUDIT = ROOT / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
DEFAULT_OUTPUT = ROOT / "runs/manual-live/task26371-independent-task-reanalysis-v1"
DEFAULT_INTERPRETER_ROOT = ROOT / "runs/manual-live/task26342-clean-baseline-preregistration-v2"
RUNNER = ROOT / "src/autoresearch/research/assets/frozen_systems_paper_currency_probe_v1.py"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to bind the immutable Task 260 and Task 263.7.0 packages "
        "and replay the task-level analysis in two clean interpreters"
    ),
)


def _require_commit(commit: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_live_additive_independent_task_reanalysis() -> None:
    parent_dir = Path(os.getenv(PARENT_ENV, str(DEFAULT_PARENT))).resolve()
    audit_dir = Path(os.getenv(AUDIT_ENV, str(DEFAULT_AUDIT))).resolve()
    output_dir = Path(os.getenv(OUTPUT_ENV, str(DEFAULT_OUTPUT))).resolve()
    replay_work_dir = output_dir.parent / f"{output_dir.name}-replay-work"
    interpreter_a = Path(
        os.getenv(
            INTERPRETER_A_ENV,
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-a/Scripts/python.exe"),
        )
    ).resolve()
    interpreter_b = Path(
        os.getenv(
            INTERPRETER_B_ENV,
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-b/Scripts/python.exe"),
        )
    ).resolve()
    if not parent_dir.is_dir() or not audit_dir.is_dir():
        raise AssertionError("immutable Task 260 and Task 263.7.0 packages are required")
    if not interpreter_a.is_file() or not interpreter_b.is_file():
        raise AssertionError("two clean interpreter installations are required")
    if not RUNNER.is_file():
        raise AssertionError("frozen statistical runner is required")
    _require_commit(PARENT_GIT_COMMIT)
    _require_commit(AUDIT_GIT_COMMIT)

    report, manifest = execute_task_unit_reanalysis(
        parent_package_dir=parent_dir,
        audit_package_dir=audit_dir,
        output_dir=output_dir,
        runner_path=RUNNER,
        interpreters={"auditor-a": interpreter_a, "auditor-b": interpreter_b},
        replay_work_dir=replay_work_dir,
        built_at=datetime.now(timezone.utc),
    )

    audit = report.independent_unit_audit
    retired_surfaces = [
        item
        for item in report.surface_inventory.manuscript_surfaces
        if item.disposition is ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE
    ]
    retired_claims = [
        item.original_claim_id
        for item in report.claim_ledger.original_claim_bindings
        if item.disposition is OriginalClaimDisposition.RETIRE_PUBLICATION_INFERENCE
    ]
    assert report.audit_binding.audit_report_hash == AUDIT_REPORT_HASH
    assert report.audit_binding.audit_manifest_hash == AUDIT_MANIFEST_HASH
    assert report.audit_binding.statistical_projection_hash == AUDIT_PROJECTION_HASH
    assert len(report.surface_inventory.numeric_bindings) == 138
    assert len(report.surface_inventory.manuscript_surfaces) == 28
    assert len(retired_surfaces) == 8
    assert retired_claims == ["C2"]
    assert len(report.note_claims) == 9
    assert audit.independent_task_count == 10
    assert audit.seed_cell_pair_count == 30
    assert audit.task_level_differences == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    assert audit.task_level_ci95 == (0.2, 0.8)
    assert audit.sign_test_one_sided_p == 0.03125
    assert audit.sign_test_two_sided_p == 0.0625
    assert audit.family_mean_differences == {"mdbench": 2 / 3, "uci": 0.25}
    assert audit.family_balanced_mean == pytest.approx(11 / 24)
    assert len(report.replay_certificate.observations) == 2
    assert report.replay_certificate.distinct_interpreter_installations
    assert report.original_preregistration_replaced is False
    assert report.parent_package_mutated is False
    assert report.fresh_confirmatory_evidence is False
    assert report.publication_ready is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert manifest.report_hash == report.report_hash
    assert (output_dir / REANALYSIS_MANIFEST_FILENAME).is_file()
    assert load_task_unit_reanalysis(output_dir) == (report, manifest)
