import os
from pathlib import Path

import pytest

from autoresearch.research.technical_confirmation_incident import (
    load_consumed_panel_technical_incident,
    write_consumed_panel_technical_incident,
)


@pytest.mark.skipif(
    os.getenv("RUN_TASK26362_TECHNICAL_INCIDENT") != "1",
    reason="set RUN_TASK26362_TECHNICAL_INCIDENT=1 to audit the retained replay",
)
def test_live_consumed_panel_technical_incident() -> None:
    source_dir = Path(
        "runs/manual-live/task2636-confirmatory-evaluation-v1"
    ).resolve()
    certificate_dir = Path(
        "runs/manual-live/task26361-evaluator-compatibility-v1"
    ).resolve()
    output_dir = Path(
        "runs/manual-live/task26362-consumed-panel-technical-replay-v1"
    ).resolve()

    first, first_manifest = write_consumed_panel_technical_incident(
        source_dir,
        certificate_dir,
        output_dir,
    )
    loaded, loaded_manifest = load_consumed_panel_technical_incident(
        output_dir,
        source_confirmation_dir=source_dir,
        evaluator_certificate_dir=certificate_dir,
        reconstruct=True,
    )

    assert first.incident_hash == loaded.incident_hash
    assert first_manifest.manifest_hash == loaded_manifest.manifest_hash
    assert first.status == "invalid_technical_replay"
    assert first.decision == "stop_portfolio_memory_claim"
    assert first.scientific_projection_exact is False
    assert len(first.projection_differences) == 8
    assert len(first.null_projection_difference_ids) == 0
    assert first.diagnostic_analysis.null_control.integrity_failure_count == 0
    assert first.formal_technical_report_generated is False
    assert first.inferential_confirmation_claim_allowed is False
    assert first.new_confirmation_authorized is False
    assert first.independent_confirmation_eligible is False
    assert first.publication_evidence_eligible is False
    assert first.public_release_authorized is False
    assert first.external_submission_authorized is False
