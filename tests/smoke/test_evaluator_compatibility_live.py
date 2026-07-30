import os
from pathlib import Path

import pytest

from autoresearch.research.evaluator_compatibility import (
    EvaluatorCompatibilityStatus,
    load_evaluator_compatibility_certificate,
    run_evaluator_compatibility_certificate,
)

RUN_ENV = "AUTORESEARCH_RUN_TASK26361_LIVE"
OUTPUT_ENV = "AUTORESEARCH_TASK26361_OUTPUT_DIR"
SOURCE_ENV = "AUTORESEARCH_TASK2636_SOURCE_DIR"


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to execute the two-interpreter compatibility matrix",
)
def test_live_two_interpreter_evaluator_compatibility_certificate() -> None:
    root = Path(__file__).resolve().parents[2]
    source_dir = Path(
        os.getenv(
            SOURCE_ENV,
            str(root / "runs/manual-live/task2636-confirmatory-evaluation-v1"),
        )
    ).resolve()
    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task26361-evaluator-compatibility-v1"),
        )
    ).resolve()

    first = run_evaluator_compatibility_certificate(
        source_dir,
        output_dir,
        progress=print,
    )
    loaded, first_manifest = load_evaluator_compatibility_certificate(
        output_dir,
        source_confirmation_dir=source_dir,
    )
    second = run_evaluator_compatibility_certificate(source_dir, output_dir)
    second_loaded, second_manifest = load_evaluator_compatibility_certificate(
        output_dir,
        source_confirmation_dir=source_dir,
    )

    assert first.status is EvaluatorCompatibilityStatus.CERTIFIED
    assert all(first.checks.values())
    assert first.report_hash == loaded.report_hash == second.report_hash
    assert second_loaded.report_hash == first.report_hash
    assert second_manifest.manifest_hash == first_manifest.manifest_hash
    assert len(first.fixtures) == 4
    assert len(first.probes) == 152
    assert first.f3_valid_probe_count == 144
    assert first.expected_candidate_failure_probe_count == 4
    assert first.f2_label_isolation_probe_count == 4
    assert first.null_prior_integrity_failure_count == 0
    assert first.unexpected_candidate_failure_count == 0
    assert first.evaluator_failure_count == 0
    assert first.input_failure_count == 0
    assert first.source_confirmation_results_accessed is False
    assert first.source_confirmation_task_bundles_accessed is False
    assert first.source_confirmation_panel_reopened is False
    assert first.network_accessed is False
    assert first.public_release_authorized is False
    assert first.external_submission_authorized is False
