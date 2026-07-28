from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

import pytest

from autoresearch.campaign import (
    CAMPAIGN_MIGRATION_MODE_ENV,
    AutonomousResearchCampaign,
    CampaignCutoverNotReadyError,
    CampaignMigrationError,
    CampaignMigrationMode,
    CampaignOutcome,
    CampaignParityReport,
    CampaignPromotionLedger,
    CampaignRollbackReport,
    CampaignStage,
    CampaignTerminalIdempotencyReport,
    ContributionGateResult,
    FailureDiagnosis,
    FrozenRoundProtocol,
    HypothesisProposal,
    Preregistration,
    RoundDevelopmentContext,
    RoundOutcome,
    UnseenEvaluation,
    load_campaign_manifest,
    rehearse_campaign_rollback,
    resolve_campaign_migration_mode,
)
from autoresearch.campaign.cli import _development_campaign_spec
from autoresearch.campaign.development import DevelopmentFixtureCampaignAdapter
from autoresearch.campaign.service import _write_campaign_manifest
from autoresearch.kernel import EventStatus

NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
CORPUS_PATH = Path("tests/fixtures/migrations/campaign-v1.json")


class PassingMigrationFixtureAdapter(DevelopmentFixtureCampaignAdapter):
    """Generated lifecycle fixture; it is not an official scientific result."""

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


class ExplodingProposalAdapter(DevelopmentFixtureCampaignAdapter):
    def propose(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
    ) -> NoReturn:
        del context, diagnosis
        raise RuntimeError("frozen Campaign proposal failure")


def _required(value: str | None) -> str:
    assert value is not None
    return value


def _spec(
    campaign_id: str,
    *,
    deadline: datetime | None = None,
):
    return _development_campaign_spec(
        campaign_id=campaign_id,
        project_id="task262-campaign-migration",
        deadline=deadline or NOW + timedelta(days=7),
        adapter_id=DevelopmentFixtureCampaignAdapter.adapter_id,
    )


def _adapter(
    output_root: Path,
    campaign_id: str,
    *,
    passing: bool,
) -> DevelopmentFixtureCampaignAdapter:
    adapter_type = (
        PassingMigrationFixtureAdapter
        if passing
        else DevelopmentFixtureCampaignAdapter
    )
    return adapter_type(output_root / campaign_id / "adapter-evidence")


def _corpus() -> dict[str, dict[str, Any]]:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {item["case_id"]: item["expected"] for item in payload["cases"]}


def _reports(root: Path, campaign_id: str) -> list[CampaignParityReport]:
    paths = sorted(
        (root / "campaigns" / campaign_id / "invocations").glob(
            "*/parity-report.json"
        )
    )
    return [
        CampaignParityReport.model_validate_json(path.read_text(encoding="utf-8"))
        for path in paths
    ]


def _event_types(root: Path, report: CampaignParityReport) -> list[str]:
    paths = sorted((root / report.journal_path / "events").glob("*.json"))
    return [json.loads(path.read_text(encoding="utf-8"))["event_type"] for path in paths]


def _assert_case(
    expected: dict[str, Any],
    *,
    root: Path,
    report: CampaignParityReport,
) -> None:
    snapshot = report.legacy
    assert report.equivalent is True
    assert [check.name for check in report.checks] == [
        "events",
        "terminal_state",
        "scientific_endpoint",
        "gate",
        "artifacts",
        "failure_semantics",
        "intervention_counts",
    ]
    assert _event_types(root, report) == expected["event_types"]
    assert snapshot.outcome == expected["legacy_outcome"]
    assert snapshot.terminal_status.value == expected["terminal_status"]
    assert snapshot.completed_round_count == expected["completed_round_count"]
    assert snapshot.experimental_round_count == expected["experimental_round_count"]
    assert snapshot.human_intervention_count == expected["human_intervention_count"]
    assert snapshot.gate.emitted_round_count == expected["emitted_gate_count"]
    if "passed_gate_count" in expected:
        assert snapshot.gate.passed_round_count == expected["passed_gate_count"]
    if "failed_gate_count" in expected:
        assert snapshot.gate.failed_round_count == expected["failed_gate_count"]
    roles = {item.role for item in snapshot.artifacts if item.exists}
    assert set(expected["required_artifact_roles"]) <= roles


def test_campaign_characterization_corpus_is_frozen_and_complete() -> None:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["service"] == "campaign"
    assert [item["case_id"] for item in payload["cases"]] == [
        "complete",
        "negative-result",
        "blocked",
        "failed",
        "resumed",
        "terminal-idempotent",
    ]


def test_default_legacy_mode_has_zero_migration_side_effects(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "runs"
    campaign_id = "campaign-legacy-only"
    service = AutonomousResearchCampaign(
        adapter=_adapter(output_root, campaign_id, passing=False),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    )

    result = service.run(_spec(campaign_id))

    assert result.outcome is CampaignOutcome.STOPPED
    assert service.migration_mode is CampaignMigrationMode.LEGACY
    assert not (output_root / ".vnext-migration").exists()


def test_shadow_complete_and_negative_results_match_frozen_corpus(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    output_root = tmp_path / "runs"
    migration_root = tmp_path / "migration"
    complete_id = "campaign-migration-complete"
    negative_id = "campaign-migration-negative"

    complete = AutonomousResearchCampaign(
        adapter=_adapter(output_root, complete_id, passing=True),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
        migration_mode="shadow",
        migration_root=migration_root,
    ).run(_spec(complete_id))
    negative = AutonomousResearchCampaign(
        adapter=_adapter(output_root, negative_id, passing=False),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
        migration_mode="shadow",
        migration_root=migration_root,
    ).run(_spec(negative_id))

    assert complete.outcome is CampaignOutcome.CONTRIBUTION_READY
    assert negative.outcome is CampaignOutcome.STOPPED
    _assert_case(
        corpus["complete"],
        root=migration_root,
        report=_reports(migration_root, complete_id)[0],
    )
    _assert_case(
        corpus["negative-result"],
        root=migration_root,
        report=_reports(migration_root, negative_id)[0],
    )


def test_shadow_retained_blocked_manifest_matches_frozen_reader_contract(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    output_root = tmp_path / "runs"
    migration_root = tmp_path / "migration"
    campaign_id = "campaign-migration-blocked"
    legacy = AutonomousResearchCampaign(
        adapter=_adapter(output_root, campaign_id, passing=False),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
    ).run(_spec(campaign_id, deadline=NOW))
    manifest_path = Path(legacy.manifest_path)
    manifest = load_campaign_manifest(manifest_path)
    _write_campaign_manifest(
        manifest_path,
        manifest.model_copy(
            update={
                "outcome": CampaignOutcome.BLOCKED,
                "stage": CampaignStage.STOP,
            }
        ),
        NOW,
    )

    blocked = AutonomousResearchCampaign(
        adapter=_adapter(output_root, campaign_id, passing=False),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
        migration_mode="shadow",
        migration_root=migration_root,
    ).resume(manifest_path.parent)

    assert blocked.outcome is CampaignOutcome.BLOCKED
    report = _reports(migration_root, campaign_id)[0]
    _assert_case(corpus["blocked"], root=migration_root, report=report)
    assert report.legacy.terminal_status is EventStatus.BLOCKED


def test_failed_checkpoint_resumes_as_fork_and_terminal_is_idempotent(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    output_root = tmp_path / "runs"
    migration_root = tmp_path / "migration"
    campaign_id = "campaign-migration-resume"
    evidence_root = output_root / campaign_id / "adapter-evidence"
    failing = AutonomousResearchCampaign(
        adapter=ExplodingProposalAdapter(evidence_root),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
        migration_mode="shadow",
        migration_root=migration_root,
    )

    with pytest.raises(RuntimeError, match="frozen Campaign proposal failure"):
        failing.run(_spec(campaign_id))

    failed_report = _reports(migration_root, campaign_id)[0]
    _assert_case(corpus["failed"], root=migration_root, report=failed_report)
    assert failed_report.legacy.failure is not None
    assert failed_report.legacy.failure.error_type == corpus["failed"]["error_type"]
    assert (
        failed_report.legacy.failure.persisted_stage
        == corpus["failed"]["persisted_stage"]
    )
    terminal_event = json.loads(
        sorted((migration_root / failed_report.journal_path / "events").glob("*.json"))[
            -1
        ].read_text(encoding="utf-8")
    )
    assert "frozen Campaign proposal failure" not in json.dumps(terminal_event)

    healthy = AutonomousResearchCampaign(
        adapter=PassingMigrationFixtureAdapter(evidence_root),
        output_root=output_root,
        vault_root=tmp_path / "vault",
        clock=lambda: NOW,
        migration_mode="shadow",
        migration_root=migration_root,
    )
    resumed = healthy.resume(output_root / campaign_id)
    reports = _reports(migration_root, campaign_id)

    assert resumed.outcome is CampaignOutcome.CONTRIBUTION_READY
    assert len(reports) == 2
    resumed_expected = corpus["resumed"]
    assert reports[1].invocation_kind == resumed_expected["invocation_kind"]
    assert reports[1].legacy.completed_round_count == 2
    assert reports[1].legacy.experimental_round_count == 2
    assert reports[1].legacy.human_intervention_count == 0
    assert reports[1].legacy.terminal_status is EventStatus.SUCCEEDED
    second_metadata = json.loads(
        (migration_root / reports[1].journal_path / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert second_metadata["fork_anchor"]["parent_run_id"].endswith("000001")
    assert second_metadata["fork_anchor"]["checkpoint_event_hash"]

    repeated = healthy.resume(output_root / campaign_id)
    assert repeated == resumed
    assert len(_reports(migration_root, campaign_id)) == 2
    idempotency_path = next(
        (
            migration_root
            / "campaigns"
            / campaign_id
            / "terminal-idempotency"
        ).glob("*.json")
    )
    idempotency = CampaignTerminalIdempotencyReport.model_validate_json(
        idempotency_path.read_text(encoding="utf-8")
    )
    assert idempotency.passed is True
    assert (
        idempotency.new_invocation_created
        is corpus["terminal-idempotent"]["new_invocation_created"]
    )


def test_vnext_cutover_requires_two_formal_runs_and_rollback_is_reversible(
    tmp_path: Path,
) -> None:
    migration_root = tmp_path / "migration"
    output_root = tmp_path / "runs"
    vault_root = tmp_path / "vault"
    premature_id = "campaign-premature-cutover"
    premature = AutonomousResearchCampaign(
        adapter=_adapter(output_root, premature_id, passing=True),
        output_root=output_root,
        vault_root=vault_root,
        clock=lambda: NOW,
        migration_mode="vnext",
        migration_root=migration_root,
    )
    with pytest.raises(CampaignCutoverNotReadyError, match="two distinct"):
        premature.run(_spec(premature_id))
    assert not (output_root / premature_id).exists()

    for index in (1, 2):
        campaign_id = f"campaign-formal-vertical-{index}"
        result = AutonomousResearchCampaign(
            adapter=_adapter(output_root, campaign_id, passing=True),
            output_root=output_root,
            vault_root=vault_root,
            clock=lambda: NOW,
            migration_mode="shadow",
            migration_root=migration_root,
            migration_formal_run_id=f"campaign-formal-{index}",
        ).run(_spec(campaign_id))
        assert result.outcome is CampaignOutcome.CONTRIBUTION_READY

    ledger = CampaignPromotionLedger.model_validate_json(
        (migration_root / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible is True
    assert len(ledger.formal_runs) == 2
    assert len({item.legacy_campaign_id for item in ledger.formal_runs}) == 2

    cutover_id = "campaign-vnext-cutover"
    vnext_result = AutonomousResearchCampaign(
        adapter=_adapter(output_root, cutover_id, passing=True),
        output_root=output_root,
        vault_root=vault_root,
        clock=lambda: NOW,
        migration_mode="vnext",
        migration_root=migration_root,
    ).run(_spec(cutover_id))
    vnext_report = _reports(migration_root, cutover_id)[0]
    assert vnext_report.lifecycle_authority == "vnext"
    assert vnext_report.legacy_compatibility_files_retained is True
    assert vnext_report.equivalent is True

    legacy_result = AutonomousResearchCampaign(
        adapter=_adapter(output_root, cutover_id, passing=True),
        output_root=output_root,
        vault_root=vault_root,
        clock=lambda: NOW,
        migration_mode="legacy",
    ).resume(Path(vnext_result.campaign_dir))
    rollback = rehearse_campaign_rollback(
        campaign_dir=vnext_result.campaign_dir,
        migration_root=migration_root,
        vnext_result=vnext_result,
        legacy_result=legacy_result,
    )

    assert rollback.passed is True
    assert rollback.lifecycle_result_equal is True
    loaded = CampaignRollbackReport.model_validate_json(
        next((migration_root / "rollback-rehearsals").glob("*.json")).read_text(
            encoding="utf-8"
        )
    )
    assert loaded == rollback

    formal_report_path = migration_root / ledger.formal_runs[0].parity_report_path
    tampered = json.loads(formal_report_path.read_text(encoding="utf-8"))
    tampered["legacy_compatibility_files_retained"] = False
    formal_report_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(CampaignMigrationError, match="report hash changed"):
        tampered_id = "campaign-tampered-promotion-cutover"
        AutonomousResearchCampaign(
            adapter=_adapter(output_root, tampered_id, passing=True),
            output_root=output_root,
            vault_root=vault_root,
            clock=lambda: NOW,
            migration_mode="vnext",
            migration_root=migration_root,
        ).run(_spec(tampered_id))
    assert not (output_root / "campaign-tampered-promotion-cutover").exists()


def test_campaign_migration_flags_are_explicit_and_fail_closed() -> None:
    assert (
        resolve_campaign_migration_mode(env={})
        is CampaignMigrationMode.LEGACY
    )
    assert (
        resolve_campaign_migration_mode(
            env={CAMPAIGN_MIGRATION_MODE_ENV: "shadow"}
        )
        is CampaignMigrationMode.SHADOW
    )
    with pytest.raises(CampaignMigrationError, match="must be one of"):
        resolve_campaign_migration_mode(
            env={CAMPAIGN_MIGRATION_MODE_ENV: "automatic"}
        )
