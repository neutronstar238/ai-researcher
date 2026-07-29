from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.campaign.mechanism_confirmatory import (
    MechanismConfirmatoryStatus,
    freeze_task2612_confirmatory,
    load_mechanism_confirmatory,
    run_task2612_confirmatory,
)

RUN_LIVE = os.getenv("AUTORESEARCH_MECHANISM_CONFIRMATORY_LIVE") == "1"


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="set AUTORESEARCH_MECHANISM_CONFIRMATORY_LIVE=1 for the one-shot local run",
)
def test_frozen_v12_mechanism_reaches_a_verified_confirmatory_endpoint() -> None:
    project_root = Path(__file__).resolve().parents[2]
    development = Path(
        os.getenv(
            "AUTORESEARCH_MECHANISM_CONFIRMATORY_DEVELOPMENT",
            project_root
            / "runs"
            / "manual-live"
            / "task2612-mechanism-development-live-v12",
        )
    )
    output = Path(
        os.getenv(
            "AUTORESEARCH_MECHANISM_CONFIRMATORY_OUTPUT",
            project_root
            / "runs"
            / "manual-live"
            / "task2612-mechanism-confirmatory-live-v1",
        )
    )
    if not (output / "preregistration.json").is_file():
        preregistration = freeze_task2612_confirmatory(
            development_dir=development,
            output_dir=output,
            run_id=output.name,
        )
        assert preregistration.confirmatory_results_revealed is False
        assert preregistration.confirmatory_result_artifact_count == 0
        assert preregistration.scientific_result_created is False

    manifest = run_task2612_confirmatory(output_dir=output)
    evaluation = json.loads(
        (output / "evaluation" / "security-report.json").read_text(encoding="utf-8")
    )
    reproduction = json.loads(
        (output / "reproduction" / "report.json").read_text(encoding="utf-8")
    )
    rollback = json.loads(
        (output / "rollback" / "report.json").read_text(encoding="utf-8")
    )

    assert manifest.status in {
        MechanismConfirmatoryStatus.POSITIVE_RESULT,
        MechanismConfirmatoryStatus.NEGATIVE_RESULT,
    }
    assert manifest.task_result_count == 6
    assert manifest.confirmatory_results_revealed is True
    assert manifest.scientific_result_created is True
    assert manifest.endpoint_rewrite_allowed is False
    assert manifest.external_submission_authorized is False
    assert evaluation["passed"] is True
    assert reproduction["passed"] is True
    assert rollback["passed"] is True
    assert len(list((output / "confirmatory").glob("*/task-result.json"))) == 6
    assert load_mechanism_confirmatory(output) == manifest
