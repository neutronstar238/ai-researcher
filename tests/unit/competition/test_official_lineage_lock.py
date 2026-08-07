"""Tests for the exclusive lineage lock (`P-20260807-090`).

Why these tests exist
---------------------
`P-20260807-090`: three `generate` processes ran concurrently against one lineage
directory. Each loaded its own copy of the spend ledger, so the persisted ledger
recorded ONE `generate-gen1` entry of 8 candidates while up to 24 were authored, and
last-writer-wins interleaved `candidate-registry.json` against `candidate.py` so 50 of
80 pilot cells failed with `candidate source bytes differ from the frozen record`.

Nothing in the engine refused the second process. The lock closes that hole, and these
tests pin the behaviour that matters: a second concurrent stage is REFUSED, the lock is
released on both success and failure, and a stale lock from a dead process does not
brick the lineage forever.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from autoresearch.competition.official_lineage import (
    _LOCK_NAME,
    _LOCK_STALE_SECONDS,
    OfficialLineageError,
    exclusive_lineage_lock,
)


def test_lock_creates_and_removes_the_lock_file(tmp_path: Path) -> None:
    """A completed stage leaves no lock behind, so the next stage can run."""

    with exclusive_lineage_lock(tmp_path, stage="generate"):
        assert (tmp_path / _LOCK_NAME).is_file()
    assert not (tmp_path / _LOCK_NAME).exists()


def test_second_concurrent_stage_is_refused(tmp_path: Path) -> None:
    """The exact defect: a second process must not proceed while one holds the lock."""

    with exclusive_lineage_lock(tmp_path, stage="generate"):
        with pytest.raises(OfficialLineageError) as excinfo:
            with exclusive_lineage_lock(tmp_path, stage="pilot"):
                pytest.fail("the second concurrent stage must never enter the body")
    message = str(excinfo.value)
    # The refusal has to be actionable, naming the holder and the budget consequence.
    assert "already running" in message
    assert "generate" in message
    assert "ledger" in message


def test_lock_is_released_when_the_stage_raises(tmp_path: Path) -> None:
    """A crashed stage must not leave the lineage permanently locked."""

    with pytest.raises(RuntimeError):
        with exclusive_lineage_lock(tmp_path, stage="generate"):
            raise RuntimeError("stage blew up")
    assert not (tmp_path / _LOCK_NAME).exists()
    # And the lineage is usable again.
    with exclusive_lineage_lock(tmp_path, stage="pilot"):
        pass


def test_a_fresh_lock_is_never_treated_as_stale(tmp_path: Path) -> None:
    """A just-written lock is a LIVE holder, so it must still refuse a second stage.

    This is the direction that protects the budget. If staleness were mis-detected the
    lock would be decorative and `P-20260807-090` would recur.
    """

    (tmp_path / _LOCK_NAME).write_text(
        '{"pid": 4242, "stage": "generate", "started_at": "x"}', encoding="utf-8"
    )
    with pytest.raises(OfficialLineageError):
        with exclusive_lineage_lock(tmp_path, stage="pilot"):
            pytest.fail("a fresh lock must not be reclaimed")


def test_stale_lock_older_than_the_threshold_is_reclaimed(tmp_path: Path) -> None:
    """An abandoned lock must not brick the lineage forever.

    Staleness is decided by the lock file's age, not by probing a PID: a recorded PID
    can be recycled by the OS, and probing it is not portable. A stage cannot outlive
    the frozen per-cell wall clock by this margin, so an older lock was abandoned by a
    crash or a forced kill.
    """

    lock_path = tmp_path / _LOCK_NAME
    lock_path.write_text(
        '{"pid": 4242, "stage": "generate", "started_at": "x"}', encoding="utf-8"
    )
    # Age the lock well past the threshold.
    old = time.time() - (_LOCK_STALE_SECONDS + 60)
    os.utime(lock_path, (old, old))

    with exclusive_lineage_lock(tmp_path, stage="pilot"):
        payload = lock_path.read_text(encoding="utf-8")
    # The live holder replaced the abandoned record with its own.
    assert str(os.getpid()) in payload


def test_lock_records_the_holding_stage_and_pid(tmp_path: Path) -> None:
    """The lock names who holds it, so a refusal can identify the other process."""

    with exclusive_lineage_lock(tmp_path, stage="baseline"):
        payload = (tmp_path / _LOCK_NAME).read_text(encoding="utf-8")
    assert "baseline" in payload
    assert str(os.getpid()) in payload
