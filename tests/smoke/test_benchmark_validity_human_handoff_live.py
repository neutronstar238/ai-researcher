"""Opt-in local-only freeze for Task 263.6.7.2.2.

The smoke loads the already-retained pagination erratum and replays an empty
human-review handoff in two clean Python installations.  It performs no
network request, formal search, screening, coding, adjudication, or outcome
access.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.benchmark_validity_human_handoff import (
    HUMAN_HANDOFF_MANIFEST_FILENAME,
    PARENT_ERRATUM_COMMIT,
    PARENT_ERRATUM_HASH,
    PARENT_ERRATUM_MANIFEST_HASH,
    PARENT_ERRATUM_PROJECTION_HASH,
    PARENT_ERRATUM_REPORT_HASH,
    execute_human_review_handoff_freeze,
    load_human_review_handoff,
)
from autoresearch.research.benchmark_validity_pagination_erratum import (
    load_pagination_erratum,
)
from autoresearch.research.benchmark_validity_protocol import (
    build_benchmark_validity_protocol,
)

LIVE_ENV = "AUTORESEARCH_BENCHMARK_HUMAN_HANDOFF_LIVE"
OUTPUT_ENV = "AUTORESEARCH_BENCHMARK_HUMAN_HANDOFF_OUTPUT"
PARENT_ERRATUM_ENV = "AUTORESEARCH_BENCHMARK_PAGINATION_ERRATUM_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_B"

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
PROTOCOL_RUNNER = (
    ROOT / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
HANDOFF_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_human_handoff.py"
HANDOFF_RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_human_handoff_probe_v1.py"
)
DEFAULT_PARENT_ERRATUM = ROOT / "runs/manual-live/task2636721-pagination-erratum-v2"
DEFAULT_OUTPUT = ROOT / "runs/manual-live/task2636722-human-review-handoff-v2"
DEFAULT_INTERPRETER_ROOT = ROOT / "runs/manual-live/task26342-clean-baseline-preregistration-v2"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to bind the real parent erratum and replay the "
        "zero-identity human-review handoff in two clean interpreters"
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_parent_erratum_freezes_zero_identity_human_handoff() -> None:
    output_dir = Path(os.getenv(OUTPUT_ENV, str(DEFAULT_OUTPUT))).resolve()
    parent_erratum_dir = Path(
        os.getenv(PARENT_ERRATUM_ENV, str(DEFAULT_PARENT_ERRATUM))
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

    manifest_path = output_dir / HUMAN_HANDOFF_MANIFEST_FILENAME
    if manifest_path.is_file():
        report, manifest = load_human_review_handoff(output_dir)
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise AssertionError("partial local handoff output must be audited manually")
        parent_report, parent_manifest = load_pagination_erratum(parent_erratum_dir)
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
        report, manifest = execute_human_review_handoff_freeze(
            protocol=protocol,
            parent_erratum_report=parent_report,
            parent_erratum_manifest=parent_manifest,
            output_dir=output_dir,
            handoff_source_path=HANDOFF_SOURCE,
            runner_path=HANDOFF_RUNNER,
            interpreters={
                "clean-runtime-a": interpreter_a,
                "clean-runtime-b": interpreter_b,
            },
            replay_work_dir=replay_work_dir,
            parent_git_commit=PARENT_ERRATUM_COMMIT,
            built_at=datetime.now(timezone.utc),
        )

    assert report.handoff.parent_erratum.erratum_hash == PARENT_ERRATUM_HASH
    assert report.handoff.parent_erratum.report_hash == PARENT_ERRATUM_REPORT_HASH
    assert (
        report.handoff.parent_erratum.projection_sha256
        == PARENT_ERRATUM_PROJECTION_HASH
    )
    assert report.handoff.parent_erratum.manifest_hash == PARENT_ERRATUM_MANIFEST_HASH
    assert report.handoff_source_sha256 == _sha256(HANDOFF_SOURCE)
    assert manifest.report_hash == report.report_hash
    assert len(report.handoff.public_role_slots) == 3
    assert report.actual_human_identity_count == 0
    assert report.role_assignment_count == 0
    assert report.review_lock_count == 0
    assert report.adjudicator_access_count == 0
    assert report.formal_search_execution_count == 0
    assert report.screening_record_count == 0
    assert report.critical_coding_record_count == 0
    assert report.admission_card_count == 0
    assert report.benchmark_outcomes_accessed is False
    assert report.candidate_model_calls is False
    assert report.formal_census_authorized is False
    assert len(report.replay_certificate.observations) == 2
    assert report.replay_certificate.distinct_interpreter_installations
