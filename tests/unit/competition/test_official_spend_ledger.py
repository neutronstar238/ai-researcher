"""The spend ledger must refuse the exact overrun recorded in P-20260802-066.

The first Task 266.3 search crossed three frozen limits: 15 candidates against a
maximum of 12, 420 candidate cells against 380, and 504 total cells against 464. The
engine capped each stage individually but nothing accumulated spend across stages, so
running the pilot twice plus a revised pilot consumed the budget silently.

These tests replay that arithmetic and require a refusal BEFORE any cell executes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.competition.official_spend_ledger import (
    OfficialSpendLedger,
    OfficialSpendLimitExceeded,
    audit_prior_lineage,
    load_or_create_ledger,
    persist_ledger,
)

# The exact frozen budget from the 266.1 plan.
BUDGET = {
    "maximum_total_candidate_count": 12,
    "maximum_official_candidate_cells": 380,
    "maximum_official_cells_total": 464,
    "maximum_model_interactions": 80,
    "maximum_generations": 2,
}
PLAN_HASH = "764f851f58302e5507ad6f5c3da2f0d6457f91f5eb90e4515c74e3a9e16095a3"


def _ledger() -> OfficialSpendLedger:
    return OfficialSpendLedger(
        lineage_id="task2663-replacement-v1",
        plan_hash=PLAN_HASH,
        **BUDGET,
    )


def _now() -> datetime:
    return datetime(2026, 8, 2, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# The historical overrun must now be impossible
# --------------------------------------------------------------------------


def test_replaying_the_overrun_is_refused_at_the_candidate_cell_limit() -> None:
    """Pilot 84 + revised pilot 84 + full 252 = 420 candidate cells against 380."""

    ledger = _ledger()
    ledger = ledger.record(stage="pilot", candidate_cells=84, now=_now())
    ledger = ledger.record(stage="revised-pilot", candidate_cells=84, now=_now())

    assert ledger.spent_candidate_cells == 168

    with pytest.raises(OfficialSpendLimitExceeded) as caught:
        ledger.record(stage="full", candidate_cells=252, now=_now())

    assert caught.value.limit_name == "maximum_official_candidate_cells"
    assert "420" in str(caught.value)
    assert "380" in str(caught.value)


def test_replaying_the_overrun_is_refused_at_the_candidate_count_limit() -> None:
    """8 generation-1 candidates plus 7 revisions is 15 against a maximum of 12."""

    ledger = _ledger().record(stage="generate", candidate_count=8, now=_now())

    with pytest.raises(OfficialSpendLimitExceeded) as caught:
        ledger.record(stage="revise", candidate_count=7, now=_now())

    assert caught.value.limit_name == "maximum_total_candidate_count"
    assert "15" in str(caught.value)


def test_total_cell_limit_counts_baseline_cells_too() -> None:
    """504 total against 464; the baseline cells are part of the same budget."""

    ledger = _ledger()
    ledger = ledger.record(stage="pilot", candidate_cells=336, now=_now())

    with pytest.raises(OfficialSpendLimitExceeded) as caught:
        ledger.record(stage="baseline", baseline_cells=200, now=_now())

    assert caught.value.limit_name == "maximum_official_cells_total"


def test_refusal_happens_before_the_spend_is_recorded() -> None:
    """A refused stage must not consume budget."""

    ledger = _ledger().record(stage="pilot", candidate_cells=300, now=_now())
    before = ledger.spent_candidate_cells

    with pytest.raises(OfficialSpendLimitExceeded):
        ledger.record(stage="full", candidate_cells=200, now=_now())

    assert ledger.spent_candidate_cells == before


# --------------------------------------------------------------------------
# A conformant plan still fits
# --------------------------------------------------------------------------


def test_a_conformant_search_fits_inside_the_frozen_budget() -> None:
    """One pilot plus one full stage plus the baseline must be affordable."""

    ledger = _ledger()
    ledger = ledger.record(stage="generate", candidate_count=8, model_interactions=8)
    ledger = ledger.record(stage="pilot", candidate_cells=48)
    ledger = ledger.record(stage="revise", candidate_count=3, model_interactions=3)
    ledger = ledger.record(stage="baseline", baseline_cells=84)
    ledger = ledger.record(stage="full", candidate_cells=252)

    assert ledger.spent_candidate_count == 11
    assert ledger.spent_candidate_cells == 300
    assert ledger.spent_total_cells == 384
    remaining = ledger.remaining()
    assert all(value >= 0 for value in remaining.values())


def test_remaining_reports_headroom_on_every_limit() -> None:
    ledger = _ledger().record(stage="pilot", candidate_cells=80, baseline_cells=20)

    remaining = ledger.remaining()

    assert remaining["candidate_cells"] == 300
    assert remaining["total_cells"] == 364
    assert remaining["candidate_count"] == 12
    assert remaining["model_interactions"] == 80


def test_model_interaction_budget_is_enforced() -> None:
    ledger = _ledger().record(stage="generate", model_interactions=78)

    with pytest.raises(OfficialSpendLimitExceeded) as caught:
        ledger.record(stage="revise", model_interactions=5)

    assert caught.value.limit_name == "maximum_model_interactions"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_ledger_survives_a_process_restart(tmp_path: Path) -> None:
    """Spend must accumulate across runs, which is what the overrun missed."""

    ledger = load_or_create_ledger(
        output_dir=tmp_path,
        lineage_id="lineage-a",
        plan_hash=PLAN_HASH,
        budget=BUDGET,
    )
    ledger = ledger.record(stage="pilot", candidate_cells=84)
    persist_ledger(ledger=ledger, output_dir=tmp_path)

    reloaded = load_or_create_ledger(
        output_dir=tmp_path,
        lineage_id="lineage-a",
        plan_hash=PLAN_HASH,
        budget=BUDGET,
    )

    assert reloaded.spent_candidate_cells == 84


def test_a_different_lineage_cannot_reuse_a_ledger(tmp_path: Path) -> None:
    """A replacement lineage needs its own directory and its own budget."""

    ledger = load_or_create_ledger(
        output_dir=tmp_path,
        lineage_id="lineage-a",
        plan_hash=PLAN_HASH,
        budget=BUDGET,
    )
    persist_ledger(ledger=ledger, output_dir=tmp_path)

    with pytest.raises(OfficialSpendLimitExceeded, match="different lineage"):
        load_or_create_ledger(
            output_dir=tmp_path,
            lineage_id="lineage-b",
            plan_hash=PLAN_HASH,
            budget=BUDGET,
        )


def test_entries_are_hash_bound() -> None:
    ledger = _ledger().record(stage="pilot", candidate_cells=10)

    assert len(ledger.entries) == 1
    assert len(ledger.entries[0].entry_hash) == 64


# --------------------------------------------------------------------------
# Post-hoc audit of the overrun lineage
# --------------------------------------------------------------------------


def test_audit_recounts_actual_spend_from_run_directories(tmp_path: Path) -> None:
    """A replacement lineage must start from truthful counts, not assumed ones."""

    import json

    cells = tmp_path / "run-a" / "cells"
    cells.mkdir(parents=True)
    (cells / "pilot-results.json").write_text(
        json.dumps(
            {
                "results": [
                    {"method_kind": "candidate", "candidate_id": "c1"},
                    {"method_kind": "candidate", "candidate_id": "c2"},
                    {"method_kind": "baseline", "candidate_id": "b"},
                ]
            }
        ),
        encoding="utf-8",
    )

    audit = audit_prior_lineage(run_dirs=[tmp_path / "run-a"])

    assert audit["candidate_cells"] == 2
    assert audit["baseline_cells"] == 1
    assert audit["total_cells"] == 3
    assert audit["distinct_candidates"] == 2
