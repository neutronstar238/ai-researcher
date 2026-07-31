from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.competition import freeze_autonomous_mdbench_research_plan

_LIVE = os.getenv("AUTORESEARCH_TASK2651_LIVE") == "1"


@pytest.mark.skipif(not _LIVE, reason="set AUTORESEARCH_TASK2651_LIVE=1 for live sources")
def test_autonomous_recovery_plan_live_primary_sources(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    plan = freeze_autonomous_mdbench_research_plan(
        repository
        / "runs/manual-live/task259-mdbench-official-v1/data/prepared/archive-manifest.json",
        repository / "runs/manual-live/task259-mdbench-official-v1/gate-a-preregistration.json",
        repository
        / "runs/manual-live/task259-mdbench-official-v1/gate-a-v3/gate-a-adjudication.json",
        repository
        / "runs/manual-live/task259-mdbench-recovery-v1/gate-a-recovery-preregistration.json",
        repository
        / "runs/manual-live/task259-mdbench-recovery-v1/gate-a-recovery-matrix.json",
        repository
        / (
            "runs/manual-live/task259-mdbench-recovery-official-v1/"
            "gate-a-v1/gate-a-adjudication.json"
        ),
        tmp_path / "autonomous-plan-live",
        timeout_seconds=30,
    )

    assert len(plan.evidence_sources) == 12
    assert all(source.marker_verified for source in plan.evidence_sources)
    assert plan.generated_candidate_count == 0
    assert plan.result_record_count == 0
    assert plan.confirmation_access_authorized is False
