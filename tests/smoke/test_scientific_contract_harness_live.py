from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition.scientific_contract_harness import (
    build_scientific_contract_harness_package,
)


@pytest.mark.skipif(
    os.environ.get("AUTORESEARCH_RUN_SCIENTIFIC_CONTRACT_HARNESS_LIVE") != "1",
    reason="set AUTORESEARCH_RUN_SCIENTIFIC_CONTRACT_HARNESS_LIVE=1 for provider/container smoke",
)
def test_scientific_contract_harness_live() -> None:
    """Generate exact source with the configured provider and run the pinned container."""

    root = Path(__file__).resolve().parents[2]
    package = build_scientific_contract_harness_package(
        root
        / "runs"
        / "manual-live"
        / "task2661-scientific-contract-recovery-plan-v1"
        / "scientific-contract-recovery-plan.json",
        root
        / "runs"
        / "manual-live"
        / "task26611-sentinel-identifiability-erratum-v1"
        / "sentinel-identifiability-erratum.json",
        root
        / "runs"
        / "manual-live"
        / "task2662-scientific-contract-harness-v9",
        config_path=root / "config.yaml",
        env_path=root / ".env",
        provider_timeout_seconds=300,
        container_timeout_seconds=480,
    )
    assert package.synthetic_contract_gate_passed
    assert package.task_266_3_authorized
    assert package.official_development_result_count == 0
    assert package.official_development_artifact_read_count == 0
    assert package.confirmation_identity_read_count == 0
    assert package.confirmation_result_count == 0
    assert package.system_generated_manuscript_count == 0
    assert not package.publication_ready
