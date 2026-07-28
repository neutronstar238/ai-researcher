"""Opt-in live smoke for the configured local OpenAI-compatible Qwen harness."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel import (
    EpisodeOutcomeStatus,
    HarnessRunner,
    HarnessRunRequest,
)
from autoresearch.kernel.journal import EventJournal
from autoresearch.llm.harness import (
    OpenAICompatibleHarnessAdapter,
    build_openai_compatible_characterization_spec,
    build_status_ok_grader,
)

MODEL_REF = "qwen3.5-sprint:9b-8k"
CONFIG_PATH = Path("configs/campaign/ollama-qwen35-sprint-8k.yaml")


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_HARNESS_LIVE") != "1",
    reason=(
        "Set AUTORESEARCH_HARNESS_LIVE=1 and the configured local API-key "
        "environment variable to run the live harness smoke."
    ),
)
def test_live_local_qwen_emits_truthful_sealed_harness_episode(
    tmp_path: Path,
) -> None:
    journal = EventJournal.create(
        tmp_path / "journal",
        run_id="run_harness_qwen_live",
        created_at=datetime.now(timezone.utc),
    )
    spec = build_openai_compatible_characterization_spec(model_ref=MODEL_REF)
    runner = HarnessRunner(
        spec=spec,
        journal=journal,
        model_adapter=OpenAICompatibleHarnessAdapter(
            config_path=CONFIG_PATH,
            estimated_cost_usd=0.0,
        ),
        graders={"grader.status_ok": build_status_ok_grader()},
    )

    episode = runner.run(
        HarnessRunRequest(
            run_id="run_harness_qwen_live",
            episode_id="episode_harness_qwen_live",
            task_input={"scope": "local_qwen_harness_characterization"},
        )
    )

    assert episode.final_outcome.status == EpisodeOutcomeStatus.SUCCEEDED
    assert episode.final_outcome.structured_output is not None
    assert episode.final_outcome.structured_output["status"] == "ok"
    assert episode.trials[0].model_ref == MODEL_REF
    assert episode.costs[0].cost_known is True
    assert episode.failures == []
    assert journal.snapshot().seal is not None
