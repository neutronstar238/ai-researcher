from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

import pytest

from autoresearch.competition import (
    COMPETITION_MIGRATION_MODE_ENV,
    CapabilityGrant,
    CompetitionCutoverNotReadyError,
    CompetitionMigrationError,
    CompetitionMigrationMode,
    CompetitionParityReport,
    CompetitionPromotionLedger,
    CompetitionRollbackReport,
    CompetitionRunSpec,
    CompetitionTerminalIdempotencyReport,
    CycleOutcome,
    ExperimentProtocol,
    HypothesisProposal,
    MDBenchAdapter,
    ResearchCycleService,
    TopicCandidate,
    TopicFeasibility,
    rehearse_competition_rollback,
    resolve_competition_migration_mode,
)
from autoresearch.kernel import EventStatus

CORPUS_PATH = Path("tests/fixtures/migrations/competition-v1.json")


class NegativeFeasibilityAdapter(MDBenchAdapter):
    def run_feasibility_probe(
        self,
        *,
        candidate: TopicCandidate,
        root: Path,
        project_id: str,
        timeout_seconds: int,
    ) -> TopicFeasibility:
        del root, project_id, timeout_seconds
        return TopicFeasibility(
            topic_id=candidate.topic_id,
            passed=False,
            metric_name="feasibility_probe",
            failure_reason="frozen negative characterization",
        )


class ExplodingAttemptAdapter(MDBenchAdapter):
    def run_feasibility_probe(
        self,
        *,
        candidate: TopicCandidate,
        root: Path,
        project_id: str,
        timeout_seconds: int,
    ) -> TopicFeasibility:
        del root, project_id, timeout_seconds
        return TopicFeasibility(
            topic_id=candidate.topic_id,
            passed=True,
            metric_name="feasibility_probe",
            metric_value=1.0,
        )

    def execute_attempt(
        self,
        *,
        cycle_dir: Path,
        project_id: str,
        candidate: TopicCandidate,
        hypothesis: HypothesisProposal,
        protocol: ExperimentProtocol,
        plan_hash: str,
        seed: int,
        parent_attempt_id: str | None,
        timeout_seconds: int,
    ) -> NoReturn:
        del (
            cycle_dir,
            project_id,
            candidate,
            hypothesis,
            protocol,
            plan_hash,
            seed,
            parent_attempt_id,
            timeout_seconds,
        )
        raise RuntimeError("frozen adapter failure")


def _corpus() -> dict[str, dict[str, Any]]:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {item["case_id"]: item["expected"] for item in payload["cases"]}


def _reports(root: Path, run_id: str) -> list[CompetitionParityReport]:
    paths = sorted((root / "cycles" / run_id / "invocations").glob("*/parity-report.json"))
    return [
        CompetitionParityReport.model_validate_json(path.read_text(encoding="utf-8"))
        for path in paths
    ]


def _event_types(root: Path, report: CompetitionParityReport) -> list[str]:
    journal_root = root / report.journal_path
    paths = sorted((journal_root / "events").glob("*.json"))
    return [json.loads(path.read_text(encoding="utf-8"))["event_type"] for path in paths]


def _assert_case(
    expected: dict[str, Any],
    *,
    root: Path,
    report: CompetitionParityReport,
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
    assert snapshot.attempt_count == expected["attempt_count"]
    assert snapshot.access_request_count == expected["access_request_count"]
    assert snapshot.human_intervention_count == expected["human_intervention_count"]
    assert snapshot.gate.emitted is expected["gate_emitted"]
    if "gate_passed" in expected:
        assert snapshot.gate.passed is expected["gate_passed"]
    if "release_allowed" in expected:
        assert snapshot.gate.release_allowed is expected["release_allowed"]
    roles = {item.role for item in snapshot.artifacts if item.exists}
    assert set(expected["required_artifact_roles"]) <= roles
    for prefix in expected.get("required_artifact_role_prefixes", []):
        assert any(role.startswith(prefix) for role in roles)


def test_competition_characterization_corpus_is_frozen_and_complete() -> None:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["service"] == "competition"
    assert [item["case_id"] for item in payload["cases"]] == [
        "complete",
        "negative-result",
        "blocked",
        "failed",
        "resumed",
        "terminal-idempotent",
    ]


def test_default_legacy_mode_has_zero_migration_side_effects(tmp_path: Path) -> None:
    service = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        adapter=NegativeFeasibilityAdapter(),
    )

    result = service.run(CompetitionRunSpec(run_id="legacy-only"))

    assert result.outcome is CycleOutcome.NEGATIVE_RESULT
    assert service.migration_mode is CompetitionMigrationMode.LEGACY
    assert not (tmp_path / "runs" / ".vnext-migration").exists()


def test_shadow_complete_and_negative_results_match_frozen_corpus(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    migration_root = tmp_path / "migration"
    complete = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        migration_mode="shadow",
        migration_root=migration_root,
    ).run(
        CompetitionRunSpec(
            run_id="migration-complete",
            project_id="migration-complete",
            timeout_seconds=20,
        )
    )
    negative = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        adapter=NegativeFeasibilityAdapter(),
        migration_mode="shadow",
        migration_root=migration_root,
    ).run(
        CompetitionRunSpec(
            run_id="migration-negative",
            project_id="migration-negative",
        )
    )

    assert complete.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    assert negative.outcome is CycleOutcome.NEGATIVE_RESULT
    _assert_case(
        corpus["complete"],
        root=migration_root,
        report=_reports(migration_root, "migration-complete")[0],
    )
    _assert_case(
        corpus["negative-result"],
        root=migration_root,
        report=_reports(migration_root, "migration-negative")[0],
    )


def test_shadow_blocked_resume_and_terminal_idempotency_are_fork_safe(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    migration_root = tmp_path / "migration"
    spec = CompetitionRunSpec(
        run_id="migration-resume",
        project_id="migration-resume",
        capability_grant_id="grant_expected",
        timeout_seconds=20,
    )
    blocked_service = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        migration_mode="shadow",
        migration_root=migration_root,
    )

    blocked = blocked_service.run(spec)
    repeated = blocked_service.resume(Path(blocked.cycle_dir))

    assert blocked.outcome is CycleOutcome.ACCESS_REQUIRED
    assert repeated == blocked
    blocked_reports = _reports(migration_root, spec.run_id)
    assert len(blocked_reports) == 1
    _assert_case(
        corpus["blocked"],
        root=migration_root,
        report=blocked_reports[0],
    )
    idempotency_path = next(
        (migration_root / "cycles" / spec.run_id / "terminal-idempotency").glob(
            "*.json"
        )
    )
    idempotency = CompetitionTerminalIdempotencyReport.model_validate_json(
        idempotency_path.read_text(encoding="utf-8")
    )
    assert idempotency.passed is True
    assert idempotency.new_invocation_created is False

    grant = CapabilityGrant(
        grant_id="grant_expected",
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    resumed = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        capability_grant=grant,
        migration_mode="shadow",
        migration_root=migration_root,
    ).resume(Path(blocked.cycle_dir))
    reports = _reports(migration_root, spec.run_id)
    assert resumed.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    assert len(reports) == 2
    assert reports[1].invocation_kind == corpus["resumed"]["invocation_kind"]
    assert reports[1].legacy.access_request_count == 1
    assert reports[1].legacy.human_intervention_count == 0
    assert reports[1].legacy.terminal_status is EventStatus.SUCCEEDED
    second_metadata = json.loads(
        (migration_root / reports[1].journal_path / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert second_metadata["fork_anchor"]["parent_run_id"].endswith("000001")
    assert second_metadata["fork_anchor"]["checkpoint_event_hash"]


def test_shadow_failed_exception_preserves_last_legacy_stage(
    tmp_path: Path,
) -> None:
    corpus = _corpus()
    migration_root = tmp_path / "migration"
    service = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        adapter=ExplodingAttemptAdapter(),
        migration_mode="shadow",
        migration_root=migration_root,
    )

    with pytest.raises(RuntimeError, match="frozen adapter failure"):
        service.run(
            CompetitionRunSpec(
                run_id="migration-failed",
                project_id="migration-failed",
            )
        )

    report = _reports(migration_root, "migration-failed")[0]
    _assert_case(corpus["failed"], root=migration_root, report=report)
    assert report.legacy.failure is not None
    assert report.legacy.failure.error_type == corpus["failed"]["error_type"]
    assert report.legacy.failure.persisted_stage == corpus["failed"]["persisted_stage"]
    terminal_event = json.loads(
        sorted((migration_root / report.journal_path / "events").glob("*.json"))[
            -1
        ].read_text(encoding="utf-8")
    )
    assert "frozen adapter failure" not in json.dumps(terminal_event)


def test_vnext_cutover_requires_two_formal_runs_and_rollback_is_reversible(
    tmp_path: Path,
) -> None:
    migration_root = tmp_path / "migration"
    output_root = tmp_path / "runs"
    vault_root = tmp_path / "vault"

    premature = ResearchCycleService(
        output_root=output_root,
        vault_root=vault_root,
        migration_mode="vnext",
        migration_root=migration_root,
    )
    with pytest.raises(CompetitionCutoverNotReadyError, match="two distinct"):
        premature.run(CompetitionRunSpec(run_id="premature-cutover"))
    assert not (output_root / "premature-cutover").exists()

    for index in (1, 2):
        result = ResearchCycleService(
            output_root=output_root,
            vault_root=vault_root,
            migration_mode="shadow",
            migration_root=migration_root,
            migration_formal_run_id=f"competition-formal-{index}",
        ).run(
            CompetitionRunSpec(
                run_id=f"formal-vertical-{index}",
                project_id="competition-formal-migration",
                timeout_seconds=20,
            )
        )
        assert result.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED

    ledger = CompetitionPromotionLedger.model_validate_json(
        (migration_root / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible is True
    assert len(ledger.formal_runs) == 2
    assert len({item.legacy_run_id for item in ledger.formal_runs}) == 2

    vnext_result = ResearchCycleService(
        output_root=output_root,
        vault_root=vault_root,
        migration_mode="vnext",
        migration_root=migration_root,
    ).run(
        CompetitionRunSpec(
            run_id="vnext-cutover",
            project_id="competition-vnext-cutover",
            timeout_seconds=20,
        )
    )
    vnext_report = _reports(migration_root, "vnext-cutover")[0]
    assert vnext_report.lifecycle_authority == "vnext"
    assert vnext_report.legacy_compatibility_files_retained is True
    assert vnext_report.equivalent is True

    legacy_result = ResearchCycleService(
        output_root=output_root,
        vault_root=vault_root,
        migration_mode="legacy",
    ).resume(Path(vnext_result.cycle_dir))
    rollback = rehearse_competition_rollback(
        cycle_dir=vnext_result.cycle_dir,
        migration_root=migration_root,
        vnext_result=vnext_result,
        legacy_result=legacy_result,
    )

    assert rollback.passed is True
    assert rollback.lifecycle_result_equal is True
    loaded = CompetitionRollbackReport.model_validate_json(
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
    with pytest.raises(CompetitionMigrationError, match="report hash changed"):
        ResearchCycleService(
            output_root=output_root,
            vault_root=vault_root,
            migration_mode="vnext",
            migration_root=migration_root,
        ).run(CompetitionRunSpec(run_id="tampered-promotion-cutover"))
    assert not (output_root / "tampered-promotion-cutover").exists()


def test_migration_flags_are_explicit_and_fail_closed() -> None:
    assert (
        resolve_competition_migration_mode(env={})
        is CompetitionMigrationMode.LEGACY
    )
    assert (
        resolve_competition_migration_mode(
            env={COMPETITION_MIGRATION_MODE_ENV: "shadow"}
        )
        is CompetitionMigrationMode.SHADOW
    )
    with pytest.raises(CompetitionMigrationError, match="must be one of"):
        resolve_competition_migration_mode(
            env={COMPETITION_MIGRATION_MODE_ENV: "automatic"}
        )
