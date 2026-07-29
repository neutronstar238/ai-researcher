from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentStatus,
    load_mechanism_development,
    run_task2612_mechanism_development,
)

RUN_LIVE = os.getenv("AUTORESEARCH_MECHANISM_DEVELOPMENT_LIVE") == "1"


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="set AUTORESEARCH_MECHANISM_DEVELOPMENT_LIVE=1 for local Qwen execution",
)
def test_local_qwen_generates_and_development_screens_exact_mechanism() -> None:
    root = Path(__file__).resolve().parents[2]
    foundation = Path(
        os.getenv(
            "AUTORESEARCH_MECHANISM_FOUNDATION",
            root
            / "runs"
            / "manual-live"
            / "task2612-mechanism-foundation-live-v3",
        )
    )
    output = Path(
        os.getenv(
            "AUTORESEARCH_MECHANISM_DEVELOPMENT_OUTPUT",
            root
            / "runs"
            / "manual-live"
            / "task2612-mechanism-development-live-v1",
        )
    )
    config = Path(
        os.getenv(
            "AUTORESEARCH_MECHANISM_LLM_CONFIG",
            root / "configs" / "campaign" / "ollama-qwen35-sprint-8k.yaml",
        )
    )
    expected_model = os.getenv(
        "AUTORESEARCH_MECHANISM_EXPECTED_MODEL",
        "qwen3.5-sprint:9b-8k",
    )
    os.environ.setdefault("AUTORESEARCH_LOCAL_OLLAMA_API_KEY", "ollama-local")

    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=foundation,
        llm_config_path=config,
        run_id=output.name,
    )

    assert manifest.status in {
        MechanismDevelopmentStatus.NEGATIVE_DEVELOPMENT,
        MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION,
    }
    assert manifest.diagnosis_hash is not None
    assert manifest.proposal_hash is not None
    assert manifest.generated_source_sha256 is not None
    assert manifest.generated_code_evidence_hash is not None
    assert manifest.round_freeze_hash is not None
    assert manifest.development_screen_hash is not None
    assert len(manifest.model_interaction_hashes) == 2
    assert manifest.confirmatory_payload_executed is False
    assert manifest.confirmatory_result_artifact_count == 0
    assert manifest.scientific_result_created is False
    assert manifest.external_submission_authorized is False

    interactions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((output / "model").glob("*-interaction.json"))
    ]
    assert len(interactions) == 2
    assert all(item["used_fallback"] is False for item in interactions)
    assert all(
        item["model_name"] == expected_model
        for item in interactions
    )
    static_review = json.loads(
        (output / "review" / "static-review.json").read_text(encoding="utf-8")
    )
    code_evidence = json.loads(
        (output / "review" / "generated-code-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    screen = json.loads(
        (output / "development" / "screen.json").read_text(encoding="utf-8")
    )
    assert static_review["approved"] is True
    assert code_evidence["approved_for_development"] is True
    assert code_evidence["source_sha256"] == manifest.generated_source_sha256
    assert screen["confirmatory_results_revealed"] is False
    assert screen["scientific_result_created"] is False
    assert load_mechanism_development(output) == manifest
