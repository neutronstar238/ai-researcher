from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition.sentinel_identifiability import (
    freeze_sentinel_identifiability_erratum,
)


@pytest.mark.skipif(
    os.environ.get("AUTORESEARCH_TASK26611_LIVE") != "1",
    reason="set AUTORESEARCH_TASK26611_LIVE=1 for the real Docker rank audit",
)
def test_sentinel_identifiability_erratum_live() -> None:
    plan = Path(
        os.environ.get(
            "AUTORESEARCH_TASK26611_PLAN",
            "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
            "scientific-contract-recovery-plan.json",
        )
    ).resolve()
    output_dir = Path(
        os.environ.get(
            "AUTORESEARCH_TASK26611_OUTPUT_DIR",
            "runs/manual-live/task26611-sentinel-identifiability-erratum-v1",
        )
    ).resolve()
    erratum = freeze_sentinel_identifiability_erratum(
        plan,
        output_dir,
        image=os.environ.get(
            "AUTORESEARCH_TASK26611_IMAGE",
            "autoresearch-mdbench:task260",
        ),
    )

    assert erratum.parent_plan_hash == (
        "764f851f58302e5507ad6f5c3da2f0d6457f91f5eb90e4515c74e3a9e16095a3"
    )
    assert erratum.probe.original_non_identifiable_ids == (
        "pde-advection-diffusion-2d",
    )
    assert erratum.probe.corrected_all_identifiable
    assert erratum.modified_sentinel_ids == ("pde-advection-diffusion-2d",)
    assert erratum.new_official_development_result_count == 0
    assert erratum.candidate_answer_count == 0
    assert erratum.model_interaction_count == 0
    assert erratum.confirmation_identity_read_count == 0
    assert erratum.confirmation_result_count == 0
    assert erratum.harness_implementation_authorized
    assert not erratum.official_development_execution_authorized
    assert not erratum.confirmation_authorized
    assert not erratum.publication_ready
