"""Opt-in real local vertical for Competition shadow promotion and rollback."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.competition import (
    CompetitionParityReport,
    CompetitionPromotionLedger,
    CompetitionRunSpec,
    CycleOutcome,
    ResearchCycleService,
    rehearse_competition_rollback,
)

LIVE_ENV = "AUTORESEARCH_COMPETITION_MIGRATION_LIVE"
OUTPUT_ENV = "AUTORESEARCH_COMPETITION_MIGRATION_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to run two formal verticals and rollback",
)


def _report(migration_root: Path, run_id: str) -> CompetitionParityReport:
    path = next(
        (migration_root / "cycles" / run_id / "invocations").glob(
            "*/parity-report.json"
        )
    )
    return CompetitionParityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def test_real_competition_vertical_promotes_then_rolls_back(tmp_path: Path) -> None:
    output_root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    runs_root = output_root / "runs"
    vault_root = output_root / "vault"
    migration_root = output_root / "migration"
    output_root.mkdir(parents=True, exist_ok=True)

    formal_reports: list[CompetitionParityReport] = []
    for index in (1, 2):
        run_id = f"task262-competition-formal-{index}"
        result = ResearchCycleService(
            output_root=runs_root,
            vault_root=vault_root,
            migration_mode="shadow",
            migration_root=migration_root,
            migration_formal_run_id=f"task262-formal-{index}",
        ).run(
            CompetitionRunSpec(
                run_id=run_id,
                project_id="task262-competition-migration",
                timeout_seconds=30,
            )
        )
        assert result.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
        report = _report(migration_root, run_id)
        assert report.equivalent is True
        assert report.lifecycle_authority == "legacy"
        formal_reports.append(report)

    ledger = CompetitionPromotionLedger.model_validate_json(
        (migration_root / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible is True
    assert len(ledger.formal_runs) == 2

    cutover_run_id = "task262-competition-vnext-cutover"
    vnext = ResearchCycleService(
        output_root=runs_root,
        vault_root=vault_root,
        migration_mode="vnext",
        migration_root=migration_root,
    ).run(
        CompetitionRunSpec(
            run_id=cutover_run_id,
            project_id="task262-competition-migration",
            timeout_seconds=30,
        )
    )
    assert vnext.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    cutover_report = _report(migration_root, cutover_run_id)
    assert cutover_report.equivalent is True
    assert cutover_report.lifecycle_authority == "vnext"

    legacy = ResearchCycleService(
        output_root=runs_root,
        vault_root=vault_root,
        migration_mode="legacy",
    ).resume(Path(vnext.cycle_dir))
    rollback = rehearse_competition_rollback(
        cycle_dir=vnext.cycle_dir,
        migration_root=migration_root,
        vnext_result=vnext,
        legacy_result=legacy,
    )
    assert rollback.passed is True

    summary = {
        "schema_version": 1,
        "service": "competition",
        "scientific_scope": (
            "generated characterization fixture; not official MDBench Gate A"
        ),
        "formal_runs": [
            {
                "run_id": report.legacy.run_id,
                "source_fingerprint": report.source_fingerprint,
                "lineage_hash": report.journal_lineage_hash,
                "seal_hash": report.journal_seal_hash,
                "equivalent": report.equivalent,
            }
            for report in formal_reports
        ],
        "promotion_ready": ledger.cutover_eligible,
        "cutover": {
            "run_id": cutover_report.legacy.run_id,
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
