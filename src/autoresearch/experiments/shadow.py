"""Shadow evaluation for candidate strategies."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.experiments.replay import ReplayCase
from autoresearch.schemas import StrategyCard


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShadowEvaluationRecord(BaseModel):
    """A candidate strategy output recorded outside production state."""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    strategy_id: str
    replay_case_id: str
    production_output: dict[str, Any]
    shadow_output: dict[str, Any]
    production_unchanged: bool
    created_at: datetime = Field(default_factory=_utc_now)


ShadowProposal = Callable[[StrategyCard, ReplayCase], Mapping[str, Any]]


def run_shadow_evaluation(
    *,
    strategy: StrategyCard,
    replay_case: ReplayCase,
    propose_output: ShadowProposal,
) -> ShadowEvaluationRecord:
    """Run a candidate proposal against a copy of production replay data."""

    production_before = deepcopy(replay_case.outputs)
    shadow_case = replay_case.model_copy(deep=True)
    shadow_output = dict(propose_output(strategy, shadow_case))
    production_unchanged = replay_case.outputs == production_before

    return ShadowEvaluationRecord(
        evaluation_id=f"shadow_{strategy.id}_{replay_case.case_id}",
        strategy_id=strategy.id,
        replay_case_id=replay_case.case_id,
        production_output=production_before,
        shadow_output=shadow_output,
        production_unchanged=production_unchanged,
    )


def write_shadow_evaluation(path: Path | str, record: ShadowEvaluationRecord) -> Path:
    """Persist a shadow record separately from production outputs."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
