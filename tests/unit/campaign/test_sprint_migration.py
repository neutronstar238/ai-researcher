from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.campaign.sprint import SprintOutcome
from autoresearch.campaign.sprint_migration import (
    SprintCutoverNotReadyError,
    SprintMigrationCoordinator,
    SprintMigrationError,
    SprintMigrationMode,
    SprintParityReport,
    SprintPromotionLedger,
    rehearse_sprint_rollback,
    resolve_sprint_migration_mode,
)
from autoresearch.kernel import EventJournal
from tests.sprint_migration_support import DeterministicSprintFixture

CORPUS_PATH = Path("tests/fixtures/migrations/sprint-v1.json")


def test_corpus_is_frozen_and_default_legacy_mode_has_no_side_effects(
    tmp_path: Path,
) -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == "sprint-migration-characterization-v1"
    assert list(corpus["cases"]) == [
        "complete",
        "negative_result",
        "blocked",
        "failed",
        "resumed",
        "terminal_idempotent",
    ]
    assert corpus["parity_dimensions"] == [
        "events",
        "terminal_state",
        "scientific_endpoint",
        "gate",
        "artifacts",
        "failure_semantics",
        "intervention_counts",
    ]

    fixture = DeterministicSprintFixture(tmp_path, "legacy-sprint")
    result = fixture.service().run(fixture.build_spec())

    assert result.outcome is SprintOutcome.COMPLETED
    assert not fixture.migration_root.exists()


def test_shadow_complete_and_negative_result_preserve_scientific_meaning(
    tmp_path: Path,
) -> None:
    complete_fixture = DeterministicSprintFixture(
        tmp_path / "complete",
        "sprint-complete",
        endpoint_passed=True,
    )
    negative_fixture = DeterministicSprintFixture(
        tmp_path / "negative",
        "sprint-negative",
        endpoint_passed=False,
    )

    complete_result = complete_fixture.service(
        mode=SprintMigrationMode.SHADOW
    ).run(complete_fixture.build_spec())
    negative_result = negative_fixture.service(
        mode=SprintMigrationMode.SHADOW
    ).run(negative_fixture.build_spec())

    complete = _reports(complete_fixture)[0]
    negative = _reports(negative_fixture)[0]
    _assert_case("complete", complete)
    _assert_case("negative_result", negative)
    assert complete_result.endpoint_passed is True
    assert negative_result.outcome is SprintOutcome.COMPLETED
    assert negative_result.endpoint_passed is False
    assert complete.equivalent and negative.equivalent
    assert all(check.passed for check in complete.checks)
    assert all(check.passed for check in negative.checks)
    assert complete.legacy.gate.autonomy_level == "bounded_autonomous"
    assert negative.legacy.gate.autonomy_level == "bounded_autonomous"
    assert all(
        not Path(item.logical_path).is_absolute()
        for item in (*complete.legacy.artifacts, *negative.legacy.artifacts)
    )


def test_blocked_sprint_resumes_through_a_child_journal(
    tmp_path: Path,
) -> None:
    fixture = DeterministicSprintFixture(
        tmp_path,
        "sprint-blocked-resumed",
        topic_blocked=True,
    )
    spec = fixture.build_spec()
    blocked = fixture.service(mode=SprintMigrationMode.SHADOW).run(spec)
    first_report = _reports(fixture)[0]

    assert blocked.outcome is SprintOutcome.BLOCKED
    _assert_case("blocked", first_report)
    first_journal = EventJournal.open(
        fixture.migration_root / first_report.journal_path
    )

    fixture.topic_blocked = False
    resumed = fixture.service(mode=SprintMigrationMode.SHADOW).resume(
        blocked.sprint_dir
    )
    reports = _reports(fixture)
    second_report = reports[1]
    second_journal = EventJournal.open(
        fixture.migration_root / second_report.journal_path
    )

    assert resumed.outcome is SprintOutcome.COMPLETED
    assert len(reports) == 2
    assert second_journal.metadata.fork_anchor is not None
    assert (
        second_journal.metadata.fork_anchor.parent_run_id
        == first_journal.metadata.run_id
    )
    assert fixture.calls.count("literature") == 3
    assert fixture.calls.count("experiment") == 1
    assert second_report.legacy.failure is None
    assert second_report.equivalent


def test_preflight_integrity_failure_is_redacted_and_distinct_from_blocked(
    tmp_path: Path,
) -> None:
    fixture = DeterministicSprintFixture(
        tmp_path,
        "sprint-failed",
        topic_blocked=True,
    )
    blocked = fixture.service(mode=SprintMigrationMode.SHADOW).run(
        fixture.build_spec()
    )
    original_route = fixture.route_manifest_path.read_text(encoding="utf-8")
    fixture.route_manifest_path.write_text(
        '{"changed":"do-not-persist-this-raw-value"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="imported Route A manifest changed"):
        fixture.service(mode=SprintMigrationMode.SHADOW).resume(
            blocked.sprint_dir
        )

    reports = _reports(fixture)
    failed = reports[-1]
    _assert_case("failed", failed)
    assert failed.legacy.failure is not None
    assert failed.legacy.failure.category == "legacy_exception"
    assert failed.legacy.failure.error_type == "ValueError"
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in fixture.migration_root.rglob("*.json")
    )
    assert "imported Route A manifest changed after sprint start" not in migration_text
    assert "do-not-persist-this-raw-value" not in migration_text
    fixture.route_manifest_path.write_text(original_route, encoding="utf-8")


def test_same_terminal_observation_writes_no_second_invocation(
    tmp_path: Path,
) -> None:
    fixture = DeterministicSprintFixture(tmp_path, "sprint-idempotent")
    result = fixture.service(mode=SprintMigrationMode.SHADOW).run(
        fixture.build_spec()
    )
    first = _reports(fixture)[0]
    journal = EventJournal.open(fixture.migration_root / first.journal_path)
    before = journal.snapshot()

    coordinator = SprintMigrationCoordinator(
        root=fixture.migration_root,
        mode=SprintMigrationMode.SHADOW,
        vault_root=fixture.vault_root,
    )
    repeated = coordinator.record_result(
        sprint_dir=result.sprint_dir,
        result=fixture.service().status(result.sprint_dir),
        invocation_kind="resume",
    )
    after = journal.snapshot()
    idempotency_path = next(
        (
            fixture.migration_root
            / "sprints"
            / fixture.sprint_id
            / "terminal-idempotency"
        ).glob("*.json")
    )
    idempotency = json.loads(idempotency_path.read_text(encoding="utf-8"))

    assert repeated.model_dump(mode="json") == result.model_dump(mode="json")
    assert len(_reports(fixture)) == 1
    assert before == after
    assert idempotency["passed"] is True
    assert idempotency["semantic_manifest_unchanged"] is True
    assert idempotency["autonomy_ledger_unchanged"] is True


def test_vnext_is_rejected_before_work_and_mode_parsing_fails_closed(
    tmp_path: Path,
) -> None:
    fixture = DeterministicSprintFixture(tmp_path, "premature-vnext")
    spec = fixture.build_spec()

    with pytest.raises(SprintCutoverNotReadyError):
        fixture.service(mode=SprintMigrationMode.VNEXT).run(spec)

    assert not (fixture.output_root / fixture.sprint_id).exists()
    assert resolve_sprint_migration_mode(
        env={"AUTORESEARCH_SPRINT_MIGRATION_MODE": "ShAdOw"}
    ) is SprintMigrationMode.SHADOW
    with pytest.raises(SprintMigrationError):
        resolve_sprint_migration_mode(
            env={"AUTORESEARCH_SPRINT_MIGRATION_MODE": "unsafe"}
        )


def test_two_formal_sprints_enable_cutover_tamper_block_and_rollback(
    tmp_path: Path,
) -> None:
    shared_migration = tmp_path / "shared-migration"
    formal_fixtures = [
        DeterministicSprintFixture(
            tmp_path / f"formal-{index}",
            f"sprint-formal-{index}",
            endpoint_passed=index == 1,
            shared_migration_root=shared_migration,
        )
        for index in (1, 2)
    ]
    formal_reports = []
    for index, fixture in enumerate(formal_fixtures, start=1):
        fixture.service(
            mode=SprintMigrationMode.SHADOW,
            formal_run_id=f"sprint-formal-{index}",
        ).run(fixture.build_spec())
        formal_reports.append(_reports(fixture)[0])

    ledger = SprintPromotionLedger.model_validate_json(
        (shared_migration / "promotion-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger.cutover_eligible
    assert len(ledger.formal_runs) == 2
    assert {item.scientific_endpoint for item in ledger.formal_runs} == {
        "task_level_gate_passed",
        "negative_result",
    }

    first_formal_path = (
        shared_migration / ledger.formal_runs[0].parity_report_path
    )
    original = first_formal_path.read_bytes()
    payload = json.loads(original)
    payload["equivalent"] = False
    first_formal_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cutover_fixture = DeterministicSprintFixture(
        tmp_path / "cutover",
        "sprint-vnext-cutover",
        shared_migration_root=shared_migration,
    )
    cutover_spec = cutover_fixture.build_spec()
    with pytest.raises(SprintMigrationError, match="formal Sprint parity report changed"):
        cutover_fixture.service(mode=SprintMigrationMode.VNEXT).run(cutover_spec)
    assert not (cutover_fixture.output_root / cutover_fixture.sprint_id).exists()
    first_formal_path.write_bytes(original)

    vnext_result = cutover_fixture.service(
        mode=SprintMigrationMode.VNEXT
    ).run(cutover_spec)
    vnext_report = _reports(cutover_fixture)[0]
    legacy_result = cutover_fixture.service().status(vnext_result.sprint_dir)
    rollback = rehearse_sprint_rollback(
        sprint_dir=vnext_result.sprint_dir,
        migration_root=shared_migration,
        vault_root=cutover_fixture.vault_root,
        vnext_result=vnext_result,
        legacy_result=legacy_result,
    )

    assert vnext_result.outcome is SprintOutcome.COMPLETED
    assert vnext_report.lifecycle_authority == "vnext"
    assert vnext_report.equivalent
    assert rollback.passed
    assert rollback.lifecycle_result_equal
    assert rollback.projection_equal
    assert rollback.journal_unchanged
    assert rollback.compatibility_files_preserved
    assert all(report.equivalent for report in formal_reports)


def _reports(fixture: DeterministicSprintFixture) -> list[SprintParityReport]:
    root = (
        fixture.migration_root
        / "sprints"
        / fixture.sprint_id
        / "invocations"
    )
    return [
        SprintParityReport.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/parity-report.json"))
    ]


def _assert_case(name: str, report: SprintParityReport) -> None:
    case: dict[str, Any] = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))[
        "cases"
    ][name]
    assert report.legacy.outcome == case["legacy_outcome"]
    assert report.legacy.stage == case["legacy_stage"]
    assert report.legacy.terminal_status.value == case["terminal_status"]
    if "scientific_endpoint" in case:
        assert report.legacy.scientific_endpoint == case["scientific_endpoint"]
    else:
        assert report.legacy.scientific_endpoint.startswith(
            case["scientific_endpoint_prefix"]
        )
    expected_failure = case["failure_category"]
    assert (
        report.legacy.failure.category if report.legacy.failure is not None else None
    ) == expected_failure
