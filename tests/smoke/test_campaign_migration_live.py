"""Opt-in local Campaign vertical for shadow promotion and rollback."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.campaign import (
    AutonomousResearchCampaign,
    CampaignOutcome,
    CampaignParityReport,
    CampaignPromotionLedger,
    ContributionGateResult,
    FrozenRoundProtocol,
    HypothesisProposal,
    Preregistration,
    RoundOutcome,
    UnseenEvaluation,
    rehearse_campaign_rollback,
)
from autoresearch.campaign.cli import _development_campaign_spec
from autoresearch.campaign.development import DevelopmentFixtureCampaignAdapter

LIVE_ENV = "AUTORESEARCH_CAMPAIGN_MIGRATION_LIVE"
OUTPUT_ENV = "AUTORESEARCH_CAMPAIGN_MIGRATION_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to run two Campaign formal verticals and rollback",
)


class PassingMigrationFixtureAdapter(DevelopmentFixtureCampaignAdapter):
    """Generated local migration fixture; never an official benchmark claim."""

    def adjudicate(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
        evaluation: UnseenEvaluation,
    ) -> ContributionGateResult:
        if (
            frozen_protocol.round_id == "round-002"
            and evaluation.outcome is RoundOutcome.POSITIVE_RESULT
        ):
            return ContributionGateResult(
                round_id=frozen_protocol.round_id,
                track=preregistration.track,
                evaluated_result_hash=_required(evaluation.result_hash),
                passed=True,
                checks={
                    "generated_migration_fixture_positive": True,
                    "mandatory_evidence_complete": evaluation.mandatory_evidence_complete,
                    "zero_human_intervention": evaluation.human_intervention_count == 0,
                },
                evidence_paths=evaluation.evidence_paths,
                warnings=(
                    "migration characterization only; not an official benchmark result",
                ),
            )
        return super().adjudicate(
            proposal,
            preregistration,
            frozen_protocol,
            evaluation,
        )


def _required(value: str | None) -> str:
    assert value is not None
    return value


def _spec(campaign_id: str):
    return _development_campaign_spec(
        campaign_id=campaign_id,
        project_id="task262-campaign-migration",
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        adapter_id=DevelopmentFixtureCampaignAdapter.adapter_id,
    )


def _service(
    *,
    output_root: Path,
    vault_root: Path,
    migration_root: Path,
    campaign_id: str,
    mode: str,
    formal_run_id: str | None = None,
) -> AutonomousResearchCampaign:
    return AutonomousResearchCampaign(
        adapter=PassingMigrationFixtureAdapter(
            output_root / campaign_id / "adapter-evidence"
        ),
        output_root=output_root,
        vault_root=vault_root,
        migration_mode=mode,
        migration_root=migration_root,
        migration_formal_run_id=formal_run_id,
    )


def _report(migration_root: Path, campaign_id: str) -> CampaignParityReport:
    path = next(
        (migration_root / "campaigns" / campaign_id / "invocations").glob(
            "*/parity-report.json"
        )
    )
    return CampaignParityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def test_real_campaign_vertical_promotes_then_rolls_back(tmp_path: Path) -> None:
    root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    output_root = root / "runs"
    vault_root = root / "vault"
    migration_root = root / "migration"
    root.mkdir(parents=True, exist_ok=True)

    formal_reports: list[CampaignParityReport] = []
    for index in (1, 2):
        campaign_id = f"task262-campaign-formal-{index}"
        result = _service(
            output_root=output_root,
            vault_root=vault_root,
            migration_root=migration_root,
            campaign_id=campaign_id,
            mode="shadow",
            formal_run_id=f"task262-campaign-formal-{index}",
        ).run(_spec(campaign_id))
        assert result.outcome is CampaignOutcome.CONTRIBUTION_READY
        report = _report(migration_root, campaign_id)
        assert report.equivalent is True
        assert report.lifecycle_authority == "legacy"
        formal_reports.append(report)

    ledger = CampaignPromotionLedger.model_validate_json(
        (migration_root / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible is True
    assert len(ledger.formal_runs) == 2

    cutover_id = "task262-campaign-vnext-cutover"
    vnext = _service(
        output_root=output_root,
        vault_root=vault_root,
        migration_root=migration_root,
        campaign_id=cutover_id,
        mode="vnext",
    ).run(_spec(cutover_id))
    assert vnext.outcome is CampaignOutcome.CONTRIBUTION_READY
    cutover_report = _report(migration_root, cutover_id)
    assert cutover_report.equivalent is True
    assert cutover_report.lifecycle_authority == "vnext"

    legacy = _service(
        output_root=output_root,
        vault_root=vault_root,
        migration_root=migration_root,
        campaign_id=cutover_id,
        mode="legacy",
    ).resume(Path(vnext.campaign_dir))
    rollback = rehearse_campaign_rollback(
        campaign_dir=vnext.campaign_dir,
        migration_root=migration_root,
        vnext_result=vnext,
        legacy_result=legacy,
    )
    assert rollback.passed is True

    summary = {
        "schema_version": 1,
        "service": "campaign",
        "scientific_scope": (
            "generated local lifecycle fixture; not an official benchmark or "
            "publication-ready scientific result"
        ),
        "formal_runs": [
            {
                "campaign_id": report.legacy.campaign_id,
                "source_fingerprint": report.source_fingerprint,
                "lineage_hash": report.journal_lineage_hash,
                "seal_hash": report.journal_seal_hash,
                "equivalent": report.equivalent,
            }
            for report in formal_reports
        ],
        "promotion_ready": ledger.cutover_eligible,
        "cutover": {
            "campaign_id": cutover_report.legacy.campaign_id,
            "authority": cutover_report.lifecycle_authority,
            "source_fingerprint": cutover_report.source_fingerprint,
            "lineage_hash": cutover_report.journal_lineage_hash,
            "seal_hash": cutover_report.journal_seal_hash,
            "equivalent": cutover_report.equivalent,
        },
        "rollback": rollback.model_dump(mode="json"),
        "legacy_compatibility_writer_retained": True,
    }
    (root / "smoke-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
