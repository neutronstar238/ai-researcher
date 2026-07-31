from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition import build_autonomous_development_search_package


def test_autonomous_development_live_search(tmp_path: Path) -> None:
    if os.getenv("AUTORESEARCH_TASK2653_LIVE") != "1":
        pytest.skip("set AUTORESEARCH_TASK2653_LIVE=1 for real model/container execution")
    repository = Path(__file__).resolve().parents[2]
    plan_path = repository / (
        "runs/manual-live/task2651-autonomous-recovery-plan-v1/"
        "autonomous-research-plan.json"
    )
    branch_engine_path = repository / (
        "runs/manual-live/task2652-autonomous-branch-engine-v22/"
        "autonomous-branch-engine-package.json"
    )
    output_override = os.getenv("AUTORESEARCH_TASK2653_OUTPUT_DIR")
    output_dir = (
        Path(output_override)
        if output_override
        else tmp_path / "live-autonomous-development"
    )
    package = build_autonomous_development_search_package(
        plan_path,
        branch_engine_path,
        output_dir,
        image=os.getenv("AUTORESEARCH_TASK2653_IMAGE", "autoresearch-mdbench:task260"),
        config_path=repository / "config.yaml",
        env_path=repository / ".env",
        model_timeout_seconds=180,
    )

    assert len(package.candidates) == 12
    assert package.official_development_result_count == 348
    assert package.baseline_result_count == 84
    assert package.executed_mechanism_cycle_count == 4
    assert package.unsupported_mechanism_claim_count == 0
    assert package.confirmation_identity_read_count == 0
    assert package.confirmation_result_count == 0
    assert package.post_start_human_scientific_decision_count == 0
    assert package.system_generated_manuscript_count == 0
    assert package.publication_ready is False
    assert package.public_release_authorized is False
    assert package.submission_authorized is False
    if package.selection.qualified_for_confirmation:
        assert package.selection.decision == "search_frozen"
        assert package.search_freeze_receipt_created is True
        assert package.next_required_task == "265.4"
    else:
        assert package.selection.decision == "autonomous_development_negative_stop"
        assert package.search_freeze_receipt_created is False
        assert package.next_required_task == "new_result_blind_recovery_cycle"
