"""Task 266.3 follow-up: a persistent cross-stage spend ledger.

Why this exists
---------------
`P-20260802-066`: the first Task `266.3` search overran three frozen limits from the
Task `266.1` plan. Candidate count reached 15 against a maximum of 12, official
candidate cells reached 420 against 380, and official cells total reached 504 against
464. The engine capped each stage individually in `build_official_cell_specs`, but
nothing accumulated spend ACROSS stages and re-runs, so executing the pilot twice
(once before and once after the baseline-routing fix) plus a revised pilot silently
consumed the budget.

The consequence was not a false positive -- the gate failed honestly either way --
but an overrun search is not a protocol-conformant search, so that evidence cannot
be presented as satisfying the frozen contract.

This ledger is append-only and persisted, so spend survives process restarts and
accumulates across every stage in a lineage. A stage that would cross a frozen limit
is refused BEFORE any cell executes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_LEDGER_NAME = "official-spend-ledger.json"


class OfficialSpendLimitExceeded(RuntimeError):
    """Raised when a requested stage would cross a frozen budget limit."""

    def __init__(self, message: str, *, limit_name: str) -> None:
        super().__init__(message)
        self.limit_name = limit_name


class SpendEntry(StrictFrozenModel):
    """One recorded, irreversible spend event."""

    stage: str
    candidate_count: int = Field(default=0, ge=0)
    candidate_cells: int = Field(default=0, ge=0)
    baseline_cells: int = Field(default=0, ge=0)
    model_interactions: int = Field(default=0, ge=0)
    recorded_at: datetime
    entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_entry(self) -> SpendEntry:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"entry_hash"})
        )
        if self.entry_hash != expected:
            raise ValueError("spend entry hash mismatch")
        return self


class OfficialSpendLedger(StrictFrozenModel):
    """Append-only accumulated spend for one preregistered lineage."""

    schema_version: Literal["official-spend-ledger-v1"] = "official-spend-ledger-v1"
    lineage_id: str = Field(min_length=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    maximum_total_candidate_count: int = Field(ge=1)
    maximum_official_candidate_cells: int = Field(ge=1)
    maximum_official_cells_total: int = Field(ge=1)
    maximum_model_interactions: int = Field(ge=1)
    maximum_generations: int = Field(ge=1)
    entries: tuple[SpendEntry, ...] = ()

    @property
    def spent_candidate_count(self) -> int:
        return sum(item.candidate_count for item in self.entries)

    @property
    def spent_candidate_cells(self) -> int:
        return sum(item.candidate_cells for item in self.entries)

    @property
    def spent_baseline_cells(self) -> int:
        return sum(item.baseline_cells for item in self.entries)

    @property
    def spent_total_cells(self) -> int:
        return self.spent_candidate_cells + self.spent_baseline_cells

    @property
    def spent_model_interactions(self) -> int:
        return sum(item.model_interactions for item in self.entries)

    def remaining(self) -> dict[str, int]:
        """Report headroom on every frozen limit."""

        return {
            "candidate_count": self.maximum_total_candidate_count
            - self.spent_candidate_count,
            "candidate_cells": self.maximum_official_candidate_cells
            - self.spent_candidate_cells,
            "total_cells": self.maximum_official_cells_total - self.spent_total_cells,
            "model_interactions": self.maximum_model_interactions
            - self.spent_model_interactions,
        }

    @property
    def spent_generations(self) -> int:
        """Distinct generations already spent, derived from recorded stage names."""

        return len(
            {
                entry.stage
                for entry in self.entries
                if entry.candidate_count > 0
            }
        )

    def check(
        self,
        *,
        candidate_count: int = 0,
        candidate_cells: int = 0,
        baseline_cells: int = 0,
        model_interactions: int = 0,
        new_generation: bool = False,
    ) -> None:
        """Refuse a request that would cross a frozen limit. Call BEFORE executing.

        `new_generation=True` declares that this request opens another generation.
        The generation limit was previously STORED but never enforced, which is the
        same class of hole that produced the cell overrun in `P-20260802-066`.
        """

        if new_generation and self.spent_generations >= self.maximum_generations:
            raise OfficialSpendLimitExceeded(
                f"maximum_generations would reach {self.spent_generations + 1} against "
                f"a frozen limit of {self.maximum_generations}; a further generation "
                "requires a new preregistered lineage, not another revision here",
                limit_name="maximum_generations",
            )
        checks = (
            (
                "maximum_total_candidate_count",
                self.spent_candidate_count + candidate_count,
                self.maximum_total_candidate_count,
            ),
            (
                "maximum_official_candidate_cells",
                self.spent_candidate_cells + candidate_cells,
                self.maximum_official_candidate_cells,
            ),
            (
                "maximum_official_cells_total",
                self.spent_total_cells + candidate_cells + baseline_cells,
                self.maximum_official_cells_total,
            ),
            (
                "maximum_model_interactions",
                self.spent_model_interactions + model_interactions,
                self.maximum_model_interactions,
            ),
        )
        for name, would_be, limit in checks:
            if would_be > limit:
                raise OfficialSpendLimitExceeded(
                    f"{name} would reach {would_be} against a frozen limit of {limit}; "
                    "this stage is refused before any cell executes",
                    limit_name=name,
                )

    def record(
        self,
        *,
        stage: str,
        candidate_count: int = 0,
        candidate_cells: int = 0,
        baseline_cells: int = 0,
        model_interactions: int = 0,
        new_generation: bool = False,
        now: datetime | None = None,
    ) -> OfficialSpendLedger:
        """Check, then append. Returns the updated ledger; never mutates in place."""

        self.check(
            candidate_count=candidate_count,
            candidate_cells=candidate_cells,
            baseline_cells=baseline_cells,
            model_interactions=model_interactions,
            new_generation=new_generation,
        )
        payload: dict[str, Any] = {
            "stage": stage,
            "candidate_count": candidate_count,
            "candidate_cells": candidate_cells,
            "baseline_cells": baseline_cells,
            "model_interactions": model_interactions,
            "recorded_at": (now or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        payload["entry_hash"] = canonical_model_hash(payload)
        entry = SpendEntry.model_validate(payload)
        return self.model_copy(update={"entries": (*self.entries, entry)})


def load_or_create_ledger(
    *,
    output_dir: Path | str,
    lineage_id: str,
    plan_hash: str,
    budget: dict[str, Any],
) -> OfficialSpendLedger:
    """Load a persisted ledger, or create an empty one bound to the frozen budget."""

    path = Path(output_dir).resolve() / _LEDGER_NAME
    if path.is_file():
        ledger = OfficialSpendLedger.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if ledger.lineage_id != lineage_id or ledger.plan_hash != plan_hash:
            raise OfficialSpendLimitExceeded(
                "existing spend ledger belongs to a different lineage or plan; "
                "a new lineage needs a new directory",
                limit_name="lineage_identity",
            )
        return ledger
    return OfficialSpendLedger(
        lineage_id=lineage_id,
        plan_hash=plan_hash,
        maximum_total_candidate_count=int(budget["maximum_total_candidate_count"]),
        maximum_official_candidate_cells=int(
            budget["maximum_official_candidate_cells"]
        ),
        maximum_official_cells_total=int(budget["maximum_official_cells_total"]),
        maximum_model_interactions=int(budget["maximum_model_interactions"]),
        maximum_generations=int(budget["maximum_generations"]),
    )


def persist_ledger(*, ledger: OfficialSpendLedger, output_dir: Path | str) -> Path:
    """Write the ledger so spend survives a process restart."""

    path = Path(output_dir).resolve() / _LEDGER_NAME
    write_json_model(path, ledger)
    return path


def audit_prior_lineage(*, run_dirs: list[Path | str]) -> dict[str, int]:
    """Recount actual spend across finished run directories, for a post-hoc audit.

    Used to establish what the overrun lineage actually consumed, so a replacement
    lineage starts from a truthful baseline rather than an assumed one.
    """

    candidate_cells = 0
    baseline_cells = 0
    candidate_ids: set[str] = set()
    for directory in run_dirs:
        cells_dir = Path(directory) / "cells"
        if not cells_dir.is_dir():
            continue
        for path in cells_dir.glob("*-results.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for record in payload.get("results", []):
                if record.get("method_kind") == "baseline":
                    baseline_cells += 1
                else:
                    candidate_cells += 1
                    candidate_ids.add(str(record.get("candidate_id")))
    return {
        "candidate_cells": candidate_cells,
        "baseline_cells": baseline_cells,
        "total_cells": candidate_cells + baseline_cells,
        "distinct_candidates": len(candidate_ids),
    }
