import os
from pathlib import Path

import pytest

from autoresearch.research.technical_confirmation_replay import (
    TechnicalRepairDecision,
    load_consumed_panel_technical_replay,
    run_consumed_panel_technical_replay,
)


@pytest.mark.skipif(
    os.getenv("RUN_TASK26362_TECHNICAL_REPLAY") != "1",
    reason="set RUN_TASK26362_TECHNICAL_REPLAY=1 for the full consumed-panel replay",
)
def test_live_consumed_panel_technical_replay() -> None:
    source_dir = Path(
        "runs/manual-live/task2636-confirmatory-evaluation-v1"
    ).resolve()
    certificate_dir = Path(
        "runs/manual-live/task26361-evaluator-compatibility-v1"
    ).resolve()
    output_dir = Path(
        "runs/manual-live/task26362-consumed-panel-technical-replay-v1"
    ).resolve()

    first = run_consumed_panel_technical_replay(
        source_dir,
        certificate_dir,
        output_dir,
        timeout_seconds=172_800,
    )
    loaded, first_manifest = load_consumed_panel_technical_replay(
        output_dir,
        source_confirmation_dir=source_dir,
        evaluator_certificate_dir=certificate_dir,
    )
    second = run_consumed_panel_technical_replay(
        source_dir,
        certificate_dir,
        output_dir,
        timeout_seconds=172_800,
    )
    second_loaded, second_manifest = load_consumed_panel_technical_replay(
        output_dir,
        source_confirmation_dir=source_dir,
        evaluator_certificate_dir=certificate_dir,
    )

    assert first.report_hash == loaded.report_hash == second.report_hash
    assert second_loaded.report_hash == first.report_hash
    assert first_manifest.manifest_hash == second_manifest.manifest_hash
    assert first.scientific_projection_exact is True
    assert first.analysis.null_control.integrity_failure_count == 0
    assert first.independent_confirmation_eligible is False
    assert first.publication_evidence_eligible is False
    assert first.new_confirmation_authorized is False
    assert first.decision in {
        TechnicalRepairDecision.STOP_PORTFOLIO_MEMORY_CLAIM,
        TechnicalRepairDecision.ELIGIBLE_FOR_NEW_MECHANISM_REVIEW,
    }
