"""Opt-in live publication-currency audit for Task 263.7.0."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from autoresearch.research.systems_paper_currency_audit import (
    AUDIT_MANIFEST_FILENAME,
    PARENT_GIT_COMMIT,
    PARENT_PACKAGE_HASH,
    PARENT_PDF_SHA256,
    PARENT_SYSTEMS_GATE_HASH,
    PARENT_SYSTEMS_RESULT_HASH,
    FindingSeverity,
    LiteraturePerspective,
    execute_systems_paper_currency_audit,
    load_systems_paper_currency_audit,
)

LIVE_ENV = "AUTORESEARCH_SYSTEMS_PAPER_CURRENCY_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SYSTEMS_PAPER_CURRENCY_OUTPUT"
PARENT_ENV = "AUTORESEARCH_TASK260_PAPER_PACKAGE"
INTERPRETER_A_ENV = "AUTORESEARCH_SYSTEMS_PAPER_AUDITOR_A"
INTERPRETER_B_ENV = "AUTORESEARCH_SYSTEMS_PAPER_AUDITOR_B"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARENT = ROOT / "runs/manual-live/task260-final-paper-v2"
DEFAULT_OUTPUT = ROOT / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
DEFAULT_INTERPRETER_ROOT = ROOT / "runs/manual-live/task26342-clean-baseline-preregistration-v2"
RUNNER = ROOT / "src/autoresearch/research/assets/frozen_systems_paper_currency_probe_v1.py"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to verify the immutable Task 260 package, retain 21 public "
        "primary sources, and replay the task-unit analysis in two clean interpreters"
    ),
)


def test_live_current_field_and_independent_unit_audit() -> None:
    parent_dir = Path(os.getenv(PARENT_ENV, str(DEFAULT_PARENT))).resolve()
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
    if not interpreter_a.is_file() or not interpreter_b.is_file():
        raise AssertionError("two clean interpreter installations are required")
    if not parent_dir.is_dir():
        raise AssertionError("immutable Task 260 v2 package is required")
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{PARENT_GIT_COMMIT}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr

    if (output_dir / AUDIT_MANIFEST_FILENAME).is_file():
        report, manifest = load_systems_paper_currency_audit(output_dir)
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise AssertionError("partial live currency-audit output needs manual inspection")
        from datetime import datetime, timezone

        report, manifest = execute_systems_paper_currency_audit(
            parent_package_dir=parent_dir,
            output_dir=output_dir,
            runner_path=RUNNER,
            interpreters={"auditor-a": interpreter_a, "auditor-b": interpreter_b},
            replay_work_dir=replay_work_dir,
            built_at=datetime.now(timezone.utc),
        )

    audit = report.independent_unit_audit
    assert report.parent.parent_git_commit == PARENT_GIT_COMMIT
    assert report.parent.package_hash == PARENT_PACKAGE_HASH
    assert report.parent.manuscript_pdf_sha256 == PARENT_PDF_SHA256
    assert report.parent.systems_result_hash == PARENT_SYSTEMS_RESULT_HASH
    assert report.parent.systems_gate_hash == PARENT_SYSTEMS_GATE_HASH
    assert len(report.source_registry.sources) == 21
    assert set(report.source_registry.perspective_counts) == set(LiteraturePerspective)
    assert all(count >= 3 for count in report.source_registry.perspective_counts.values())
    assert audit.independent_task_count == 10
    assert audit.seed_cell_pair_count == 30
    assert audit.task_level_differences == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    assert audit.task_level_ci95 == (0.2, 0.8)
    assert audit.sign_test_one_sided_p == 0.03125
    assert audit.sign_test_two_sided_p == 0.0625
    assert audit.family_mean_differences == {"mdbench": 2 / 3, "uci": 0.25}
    assert audit.family_balanced_mean == pytest.approx(11 / 24)
    assert report.severity_counts[FindingSeverity.CRITICAL] >= 3
    assert report.publication_ready is False
    assert report.independent_human_review_complete is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert len(report.replay_certificate.observations) == 2
    assert report.replay_certificate.distinct_interpreter_installations
    assert manifest.report_hash == report.report_hash
