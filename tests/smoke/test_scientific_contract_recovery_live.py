from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition.scientific_contract_recovery import (
    freeze_scientific_contract_recovery_plan,
)


@pytest.mark.skipif(
    os.environ.get("AUTORESEARCH_TASK2661_LIVE") != "1",
    reason="set AUTORESEARCH_TASK2661_LIVE=1 for real sources and Docker baseline probes",
)
def test_scientific_contract_recovery_live() -> None:
    parent = Path(
        os.environ.get(
            "AUTORESEARCH_TASK2661_PARENT",
            "runs/manual-live/task2653-autonomous-development-v1/"
            "autonomous-development-search-package.json",
        )
    ).resolve()
    output_dir = Path(
        os.environ.get(
            "AUTORESEARCH_TASK2661_OUTPUT_DIR",
            "runs/manual-live/task2661-scientific-contract-recovery-plan-v1",
        )
    ).resolve()
    plan = freeze_scientific_contract_recovery_plan(
        parent,
        output_dir,
        image=os.environ.get("AUTORESEARCH_TASK2661_IMAGE", "autoresearch-mdbench:task260"),
        timeout_seconds=int(os.environ.get("AUTORESEARCH_TASK2661_TIMEOUT", "45")),
    )

    assert plan.negative_binding.package_hash == (
        "8f42cbb684b7b02eee5d4e9287e26f3edaebd49b7215f603d274450a58994576"
    )
    assert plan.result_blind_freeze
    assert len(plan.sources) == 9
    assert len(plan.sentinels) == 6
    assert plan.baseline_probe.passed
    assert plan.baseline_probe.official_artifact_reads == 0
    assert plan.new_official_development_result_count == 0
    assert plan.confirmation_identity_read_count == 0
    assert plan.confirmation_result_count == 0
    assert plan.candidate_answer_count == 0
    assert plan.model_interaction_count == 0
    assert plan.harness_implementation_authorized
    assert not plan.official_development_execution_authorized
    assert not plan.confirmation_authorized
    assert not plan.publication_ready
