"""Opt-in primary-documentation freeze for Task 263.6.7.2.1.

This smoke retrieves only four public API documentation pages. It executes no
bibliographic query, extracts no study, and accesses no benchmark outcome.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.benchmark_validity_harness import (
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH,
    load_benchmark_validity_harness,
)
from autoresearch.research.benchmark_validity_pagination_erratum import (
    PAGINATION_ERRATUM_MANIFEST_FILENAME,
    PARENT_HARNESS_COMMIT,
    PARENT_HARNESS_MANIFEST_HASH,
    PARENT_HARNESS_PROJECTION_HASH,
    PARENT_HARNESS_REPORT_HASH,
    ParentHarnessEvidence,
    execute_pagination_erratum_freeze,
    load_pagination_erratum,
)
from autoresearch.research.benchmark_validity_protocol import (
    SearchSourceId,
    build_benchmark_validity_protocol,
)

LIVE_ENV = "AUTORESEARCH_BENCHMARK_PAGINATION_ERRATUM_LIVE"
OUTPUT_ENV = "AUTORESEARCH_BENCHMARK_PAGINATION_ERRATUM_OUTPUT"
PARENT_HARNESS_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_HARNESS_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_BENCHMARK_VALIDITY_INTERPRETER_B"

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
PROTOCOL_RUNNER = (
    ROOT / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
ERRATUM_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_pagination_erratum.py"
INTEGRATED_HARNESS_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_harness.py"
ERRATUM_RUNNER = (
    ROOT / "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_pagination_erratum_probe_v1.py"
)
DEFAULT_PARENT_HARNESS = ROOT / "runs/manual-live/task263672-benchmark-validity-harness-v2"
DEFAULT_OUTPUT = ROOT / "runs/manual-live/task2636721-pagination-erratum-v2"
DEFAULT_INTERPRETER_ROOT = ROOT / "runs/manual-live/task26342-clean-baseline-preregistration-v2"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to retain four primary API-documentation snapshots "
        "and replay the zero-result pagination erratum"
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_primary_documentation_freezes_zero_result_erratum() -> None:
    output_dir = Path(os.getenv(OUTPUT_ENV, str(DEFAULT_OUTPUT))).resolve()
    parent_harness_dir = Path(os.getenv(PARENT_HARNESS_ENV, str(DEFAULT_PARENT_HARNESS))).resolve()
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

    manifest_path = output_dir / PAGINATION_ERRATUM_MANIFEST_FILENAME
    if manifest_path.is_file():
        report, manifest = load_pagination_erratum(output_dir)
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise AssertionError("partial live erratum output must be audited manually")
        parent_report, parent_manifest = load_benchmark_validity_harness(parent_harness_dir)
        parent_evidence = ParentHarnessEvidence.from_artifacts(
            report=parent_report,
            manifest=parent_manifest,
        )
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
        report, manifest = execute_pagination_erratum_freeze(
            protocol=protocol,
            parent_harness_evidence=parent_evidence,
            output_dir=output_dir,
            integrated_harness_source_path=INTEGRATED_HARNESS_SOURCE,
            erratum_source_path=ERRATUM_SOURCE,
            runner_path=ERRATUM_RUNNER,
            interpreters={
                "reviewer-a": interpreter_a,
                "reviewer-b": interpreter_b,
            },
            replay_work_dir=replay_work_dir,
            parent_git_commit=PARENT_HARNESS_COMMIT,
            built_at=datetime.now(timezone.utc),
        )

    assert manifest.report_hash == report.report_hash
    assert report.erratum.parent_harness_report_hash == PARENT_HARNESS_REPORT_HASH
    assert report.erratum.parent_harness_projection_hash == PARENT_HARNESS_PROJECTION_HASH
    assert report.erratum.parent_harness_manifest_hash == PARENT_HARNESS_MANIFEST_HASH
    assert report.integrated_harness_source_sha256 == _sha256(INTEGRATED_HARNESS_SOURCE)
    assert {item.source_id for item in report.erratum.amendments} == set(SearchSourceId)
    assert len(report.erratum.documentation_snapshots) == 4
    assert report.formal_search_execution_count == 0
    assert report.bibliographic_record_count == 0
    assert report.admission_card_count == 0
    assert report.benchmark_outcomes_accessed is False
    assert report.candidate_model_calls is False
    assert report.erratum.actual_human_identities_assigned is False
    assert report.erratum.publication_claim_authorized is False
    assert len(report.replay_certificate.observations) == 2
    assert report.replay_certificate.distinct_interpreter_installations
