"""Opt-in real API capability smoke for Task 263.6.7.2.

This test sends four one-page known-item probes.  It deliberately does not run
the frozen 28-query census or inspect any benchmark outcome.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.benchmark_validity_harness import (
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH,
    HARNESS_MANIFEST_FILENAME,
    SearchPurpose,
    SearchRunStatus,
    execute_benchmark_validity_capability_harness,
    load_benchmark_validity_harness,
)
from autoresearch.research.benchmark_validity_protocol import (
    SearchSourceId,
    build_benchmark_validity_protocol,
)

LIVE_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_HARNESS_LIVE"
OUTPUT_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_HARNESS_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_B"

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
PROTOCOL_RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
HARNESS_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_harness.py"
HARNESS_RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_harness_probe_v1.py"
)
DEFAULT_INTERPRETER_ROOT = (
    ROOT / "runs/manual-live/task26342-clean-baseline-preregistration-v2"
)

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to probe the four real bibliographic APIs, preserve "
        "raw responses, and replay the result-blind projection"
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def test_real_bibliographic_api_capabilities_preserve_result_blindness() -> None:
    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                ROOT
                / "runs/manual-live/task263672-benchmark-validity-harness-v2"
            ),
        )
    ).resolve()
    replay_work_dir = output_dir.parent / f"{output_dir.name}-replay-work"
    interpreter_a = Path(
        os.getenv(
            INTERPRETER_A_ENV,
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-a/Scripts/python.exe"),
        )
    ).resolve()
    interpreter_b = Path(
        os.getenv(
            INTERPRETER_B_ENV,
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-b/Scripts/python.exe"),
        )
    ).resolve()
    if not interpreter_a.is_file() or not interpreter_b.is_file():
        raise AssertionError("two clean interpreter installations are required")

    manifest_path = output_dir / HARNESS_MANIFEST_FILENAME
    if manifest_path.is_file():
        report, manifest = load_benchmark_validity_harness(output_dir)
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise AssertionError("partial live Harness output must be audited manually")
        protocol = build_benchmark_validity_protocol(
            frozen_at=datetime(
                2026,
                7,
                31,
                9,
                38,
                52,
                843137,
                tzinfo=timezone.utc,
            ),
            parent_git_commit="b890aef4b5f254275f9edb2509fe6f1b4a0ae9f2",
            protocol_source_sha256=_sha256(PROTOCOL_SOURCE),
            frozen_runner_sha256=_sha256(PROTOCOL_RUNNER),
        )
        assert protocol.protocol_hash == FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH
        report, manifest = execute_benchmark_validity_capability_harness(
            protocol=protocol,
            output_dir=output_dir,
            protocol_source_path=PROTOCOL_SOURCE,
            harness_source_path=HARNESS_SOURCE,
            runner_path=HARNESS_RUNNER,
            interpreters={
                "reviewer-a": interpreter_a,
                "reviewer-b": interpreter_b,
            },
            replay_work_dir=replay_work_dir,
            parent_git_commit=_git_head(),
            built_at=datetime.now(timezone.utc),
        )

    assert manifest.report_hash == report.report_hash
    assert {item.source_id for item in report.capability_runs} == set(SearchSourceId)
    assert all(
        item.purpose is SearchPurpose.API_CAPABILITY_SMOKE
        and item.status is SearchRunStatus.CAPABILITY_ONLY
        for item in report.capability_runs
    )
    assert len(report.journal_snapshot.raw_response_hashes) >= 4
    assert report.formal_search_execution_count == 0
    assert report.admission_card_count == 0
    assert report.benchmark_outcomes_accessed is False
    assert report.candidate_model_calls is False
    assert report.known_item_recall.formal_recall_claim is False
    assert (
        "crossref-last-cursor-termination-mismatch"
        in report.projection.formal_blocker_ids
    )
    assert len(report.replay_certificate.observations) == 2
    assert report.replay_certificate.distinct_interpreter_installations
