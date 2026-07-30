import os
from pathlib import Path

import pytest

from autoresearch.research.confirmatory_evaluation import (
    ConfirmationRevealLedger,
    ConfirmationStatus,
    freeze_confirmatory_evaluation,
    load_confirmatory_evaluation_report,
    run_confirmatory_evaluation,
)

RUN_ENV = "AUTORESEARCH_RUN_TASK2636_LIVE"
OUTPUT_ENV = "AUTORESEARCH_TASK2636_OUTPUT_DIR"
PANEL_ENV = "AUTORESEARCH_TASK26341_PANEL_DIR"
BASELINE_ENV = "AUTORESEARCH_TASK26342_BASELINE_DIR"
DEVELOPMENT_ENV = "AUTORESEARCH_TASK2635_DEVELOPMENT_DIR"


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to execute the one-use confirmatory matrix",
)
def test_live_one_use_independent_confirmatory_evaluation() -> None:
    root = Path(__file__).resolve().parents[2]
    panel_dir = Path(
        os.getenv(
            PANEL_ENV,
            str(root / "runs/manual-live/task26341-open-objective-panel-v1"),
        )
    ).resolve()
    baseline_dir = Path(
        os.getenv(
            BASELINE_ENV,
            str(root / "runs/manual-live/" "task26342-clean-baseline-preregistration-v2"),
        )
    ).resolve()
    development_dir = Path(
        os.getenv(
            DEVELOPMENT_ENV,
            str(root / "runs/manual-live/task2635-development-search-v2"),
        )
    ).resolve()
    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task2636-confirmatory-evaluation-v1"),
        )
    ).resolve()

    freeze = freeze_confirmatory_evaluation(
        panel_dir,
        baseline_dir,
        development_dir,
        output_dir,
    )
    assert len(freeze.assignments) == 1620
    assert freeze.within_unit_seeds == [1729, 3253, 7919]
    assert freeze.surviving_policy_id == "portfolio_memory"
    assert freeze.primary_comparator_policy_id == "linear_self_loop"
    assert len(freeze.frozen_policy_memories) == 9
    assert freeze.claim.frozen_policy_memory_catalogue_hash
    assert all(
        memory.source_partition == "development"
        and memory.clone_per_confirmatory_unit is True
        and memory.cross_confirmatory_unit_updates_allowed is False
        and memory.within_unit_seed_updates_allowed is True
        for memory in freeze.frozen_policy_memories
    )
    assert freeze.clean_environment_lock_verified is True
    assert set(freeze.clean_environment_snapshots) == {"primary", "replay"}
    assert (
        freeze.clean_environment_snapshots["primary"].installed_distributions
        == freeze.clean_environment_snapshots["replay"].installed_distributions
    )
    assert freeze.confirmatory_payloads_downloaded is False
    assert freeze.confirmatory_results_observed is False
    assert freeze.result_record_count == 0
    reveal_path = output_dir / "confirmation-reveal-ledger.json"
    index_path = output_dir / "confirmatory-execution-index.json"
    if reveal_path.exists():
        reveal = ConfirmationRevealLedger.model_validate_json(
            reveal_path.read_text(encoding="utf-8")
        )
        assert reveal.freeze_hash == freeze.freeze_hash
        assert reveal.reveal_ordinal == 1
        assert reveal.previous_reveal_exists is False
    else:
        assert not index_path.exists()

    first = run_confirmatory_evaluation(
        panel_dir,
        baseline_dir,
        output_dir,
    )
    loaded, loaded_freeze, first_manifest = load_confirmatory_evaluation_report(output_dir)
    second = run_confirmatory_evaluation(
        panel_dir,
        baseline_dir,
        output_dir,
    )
    second_loaded, _, second_manifest = load_confirmatory_evaluation_report(output_dir)

    if all(first.validity_checks.values()):
        assert first.status in {
            ConfirmationStatus.POSITIVE_CONFIRMATION,
            ConfirmationStatus.CREDIBLE_NEGATIVE_CONFIRMATION,
        }
    else:
        assert first.status is ConfirmationStatus.INVALID_CONFIRMATION
    assert first.report_hash == loaded.report_hash == second.report_hash
    assert second_loaded.report_hash == first.report_hash
    assert loaded_freeze.freeze_hash == freeze.freeze_hash
    assert second_manifest.manifest_hash == first_manifest.manifest_hash
    assert first.complete_confirmatory_matrix is True
    assert first.all_outcomes_retained is True
    assert first.one_use_reveal_completed is True
    assert len(first.analysis.task_outcomes) == 540
    assert len(first.analysis.policy_summaries) == 9
    assert first.analysis.cost_failure_audit.assignment_count == 1620
    assert first.analysis.cost_failure_audit.null_control_assignment_count == 180
    assert first.analysis.cost_failure_audit.candidate_stage_record_count == 77_760
    assert first.clean_room_replay.scientific_projection_exact is True
    assert first.post_reveal_retuning_authorized is False
    assert first.confirmation_panel_reopen_authorized is False
    assert first.public_release_authorized is False
    assert first.external_submission_authorized is False
