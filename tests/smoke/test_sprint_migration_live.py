"""Opt-in adoption smoke over persisted real Sprint lifecycle evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.campaign import (
    AutonomousResearchSprint,
    SprintMigrationCoordinator,
    SprintOutcome,
    SprintParityReport,
    SprintPromotionLedger,
    rehearse_sprint_rollback,
)

LIVE_ENV = "AUTORESEARCH_SPRINT_MIGRATION_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SPRINT_MIGRATION_OUTPUT"
FORMAL_SPRINT_IDS = (
    "task261-bounded-autonomous-clean-v1",
    "task261-bounded-autonomous-clean-v2",
)
CUTOVER_SPRINT_ID = "task261-bounded-autonomous-live-v1"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to adopt two persisted real Sprints, cut over, "
        "and rehearse rollback"
    ),
)


def _report(migration_root: Path, sprint_id: str) -> SprintParityReport:
    path = next(
        (
            migration_root
            / "sprints"
            / sprint_id
            / "invocations"
        ).glob("*/parity-report.json")
    )
    return SprintParityReport.model_validate_json(path.read_text(encoding="utf-8"))


def test_real_sprint_evidence_promotes_then_rolls_back(tmp_path: Path) -> None:
    """Adopt real persisted evidence without rerunning models or experiments."""

    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "runs" / "manual-live"
    vault_root = repository_root / "autoresearch-vault"
    output_root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    migration_root = output_root / "migration"
    output_root.mkdir(parents=True, exist_ok=True)
    reader = AutonomousResearchSprint(vault_root=vault_root)

    formal_reports: list[SprintParityReport] = []
    for index, sprint_id in enumerate(FORMAL_SPRINT_IDS, start=1):
        sprint_dir = source_root / sprint_id
        legacy = reader.status(sprint_dir)
        assert legacy.outcome is SprintOutcome.COMPLETED

        coordinator = SprintMigrationCoordinator(
            root=migration_root,
            mode="shadow",
            formal_run_id=f"task262-sprint-formal-{index}",
            vault_root=vault_root,
        )
        observed = coordinator.record_result(
            sprint_dir=sprint_dir,
            result=legacy,
            invocation_kind="resume",
        )
        report = _report(migration_root, sprint_id)

        assert observed.model_dump(mode="json") == legacy.model_dump(mode="json")
        assert report.equivalent is True
        assert report.lifecycle_authority == "legacy"
        assert report.legacy.scientific_endpoint == "negative_result"
        formal_reports.append(report)

    ledger = SprintPromotionLedger.model_validate_json(
        (migration_root / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible is True
    assert len(ledger.formal_runs) == 2
    assert {record.scientific_endpoint for record in ledger.formal_runs} == {
        "negative_result"
    }

    cutover_dir = source_root / CUTOVER_SPRINT_ID
    legacy_cutover = reader.status(cutover_dir)
    assert legacy_cutover.outcome is SprintOutcome.BLOCKED
    coordinator = SprintMigrationCoordinator(
        root=migration_root,
        mode="vnext",
        vault_root=vault_root,
    )
    coordinator.assert_mode_allowed()
    vnext = coordinator.record_result(
        sprint_dir=cutover_dir,
        result=legacy_cutover,
        invocation_kind="resume",
    )
    cutover_report = _report(migration_root, CUTOVER_SPRINT_ID)

    assert vnext.model_dump(mode="json") == legacy_cutover.model_dump(mode="json")
    assert cutover_report.equivalent is True
    assert cutover_report.lifecycle_authority == "vnext"
    assert cutover_report.legacy.failure is not None
    assert cutover_report.legacy.failure.category == "legacy_block"

    rollback = rehearse_sprint_rollback(
        sprint_dir=cutover_dir,
        migration_root=migration_root,
        vault_root=vault_root,
        vnext_result=vnext,
        legacy_result=reader.status(cutover_dir),
    )
    assert rollback.passed is True

    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in migration_root.rglob("*.json")
    )
    assert str(repository_root) not in migration_text
    assert repository_root.as_posix() not in migration_text

    summary = {
        "schema_version": 1,
        "service": "sprint",
        "scientific_scope": (
            "adoption of persisted real local Sprint evidence; no model, "
            "literature, experiment, paper, or submission step was rerun"
        ),
        "formal_runs": [
            {
                "sprint_id": report.legacy.sprint_id,
                "scientific_endpoint": report.legacy.scientific_endpoint,
                "source_fingerprint": report.source_fingerprint,
                "lineage_hash": report.journal_lineage_hash,
                "seal_hash": report.journal_seal_hash,
                "equivalent": report.equivalent,
            }
            for report in formal_reports
        ],
        "negative_results_are_formal_evidence": True,
        "promotion_ready": ledger.cutover_eligible,
        "cutover": {
            "sprint_id": cutover_report.legacy.sprint_id,
            "legacy_outcome": cutover_report.legacy.outcome,
            "authority": cutover_report.lifecycle_authority,
            "source_fingerprint": cutover_report.source_fingerprint,
            "lineage_hash": cutover_report.journal_lineage_hash,
            "seal_hash": cutover_report.journal_seal_hash,
            "equivalent": cutover_report.equivalent,
        },
        "rollback": rollback.model_dump(mode="json"),
        "legacy_compatibility_writer_retained": True,
    }
    (output_root / "smoke-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
