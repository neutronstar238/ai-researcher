"""Task 268.2: opt-in live run of the frozen-protocol self-correction cycle.

This feature depends on an external provider, so mocked tests alone cannot
complete the task. This smoke reproduces the recorded live run from tracked code:
the deterministic layers read the RETAINED conformant baseline evidence, and the
configured model authors the repair itself.

Run with:
    $env:AUTORESEARCH_TASK2682_LIVE = "1"
    poetry run python -m pytest tests/smoke/test_frozen_protocol_contradiction_live.py -q

The assertions below deliberately do NOT require a particular resolution_kind.
Which repair the system chooses is the system's own scientific decision; the test
only proves the cycle ran live, stayed bound to the retained evidence, and could
not self-authorize.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition.frozen_protocol_contradiction import (
    ALL_ZERO_MODEL,
    FROZEN_PROTOCOL_CONTRADICTION,
    INSUFFICIENT_SAMPLES,
    run_frozen_protocol_self_correction,
)

_LIVE = os.getenv("AUTORESEARCH_TASK2682_LIVE") == "1"


@pytest.mark.skipif(not _LIVE, reason="set AUTORESEARCH_TASK2682_LIVE=1 for a live provider")
def test_frozen_protocol_self_correction_live(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]

    package = run_frozen_protocol_self_correction(
        baseline_results_path=(
            repository
            / "runs/manual-live/task2663-conformant-v1/cells/baseline-results.json"
        ),
        output_dir=tmp_path / "frozen-protocol-self-correction-live",
        config_path=repository / "config.yaml",
        env_path=repository / ".env",
    )

    # The deterministic layer must reproduce the retained evidence exactly.
    assert package.observation.observed_cell_count == 84
    assert package.observation.succeeded_cell_count == 72
    assert package.observation.failed_cell_count == 12
    assert package.observation.frozen_check_is_currently_satisfiable is False

    mechanisms = {
        item.system_name: item.mechanism for item in package.observation.failing_systems
    }
    assert mechanisms["heat_laser"] == INSUFFICIENT_SAMPLES
    assert mechanisms["heat_soil_uniform_2d_p1"] == ALL_ZERO_MODEL

    assert package.diagnosis.failure_kind == FROZEN_PROTOCOL_CONTRADICTION
    assert package.diagnosis.fault_is_in_pinned_baseline_library is True
    assert package.diagnosis.systems_where_completion_would_fabricate_an_effect == (
        "heat_soil_uniform_2d_p1",
    )

    # The repair is model-authored, covers every failing system, and is audited.
    assert package.proposal.authored_by_model is True
    assert {item.system_name for item in package.proposal.per_system_resolutions} == {
        "heat_laser",
        "heat_soil_uniform_2d_p1",
    }

    # A proposal is never an authorization.
    assert package.proposal.human_approval_recorded is False
    assert package.proposal.execution_authorized is False
    assert package.proposal.requires_new_preregistration_lineage is True
    assert package.execution_authorized is False
    assert package.publication_ready is False
    assert package.human_scientific_decision_count == 0

    # The guard verdict is recorded either way; a rejection is a real finding.
    assert package.guard_audit.parent_proposal_hash == package.proposal.proposal_hash
    assert any("guard_verdict" in finding for finding in package.guard_audit.findings)
