from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition import build_autonomous_branch_engine_package


def test_autonomous_branch_engine_live_provider(tmp_path: Path) -> None:
    if os.getenv("AUTORESEARCH_TASK2652_LIVE") != "1":
        pytest.skip("set AUTORESEARCH_TASK2652_LIVE=1 for the real provider/source smoke")
    repository = Path(__file__).resolve().parents[2]
    plan_path = repository / (
        "runs/manual-live/task2651-autonomous-recovery-plan-v1/"
        "autonomous-research-plan.json"
    )
    output_override = os.getenv("AUTORESEARCH_TASK2652_OUTPUT_DIR")
    output_dir = Path(output_override) if output_override else tmp_path / "live-branch-engine"

    package = build_autonomous_branch_engine_package(
        plan_path,
        output_dir,
        config_path=repository / "config.yaml",
        env_path=repository / ".env",
        timeout_seconds=180,
        source_timeout_seconds=30,
    )

    assert len(package.literature_snapshots) == 12
    assert package.generated_candidate_count == 8
    assert package.mechanism_family_count >= 3
    assert package.model_interaction_count >= 17
    assert package.provenance_gate_passed
    assert package.capability_gate_passed
    assert package.development_execution_authorized
    assert package.confirmation_identity_read_count == 0
    assert package.objective_official_development_result_count == 0
    assert package.search_freeze_receipt_created is False
    assert package.confirmation_access_authorized is False
    assert package.publication_ready is False
