from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.benchmark_validity_protocol import (
    BenchmarkValidityProtocolFreezeReport,
    build_benchmark_validity_protocol,
    load_benchmark_validity_protocol_freeze,
    run_benchmark_validity_protocol_replay,
    write_benchmark_validity_protocol_freeze,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
RUNNER_PATH = (
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
DEFAULT_INTERPRETER_ROOT = (
    ROOT
    / "runs/manual-live/task26342-clean-baseline-preregistration-v2"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_BENCHMARK_VALIDITY_PROTOCOL_FREEZE_LIVE") != "1",
    reason="set the opt-in environment variable for real clean-interpreter replay",
)
def test_benchmark_validity_protocol_freezes_before_any_search(
    tmp_path: Path,
) -> None:
    interpreter_a = Path(
        os.getenv(
            "AUTORESEARCH_CLEAN_INTERPRETER_A",
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-a/Scripts/python.exe"),
        )
    )
    interpreter_b = Path(
        os.getenv(
            "AUTORESEARCH_CLEAN_INTERPRETER_B",
            str(DEFAULT_INTERPRETER_ROOT / "clean-venv-b/Scripts/python.exe"),
        )
    )
    if not interpreter_a.is_file() or not interpreter_b.is_file():
        pytest.skip("two clean interpreter installations are unavailable")
    parent_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    protocol = build_benchmark_validity_protocol(
        frozen_at=datetime.now(timezone.utc),
        parent_git_commit=parent_commit,
        protocol_source_sha256=_sha256(SOURCE_PATH),
        frozen_runner_sha256=_sha256(RUNNER_PATH),
    )
    projection, certificate = run_benchmark_validity_protocol_replay(
        protocol=protocol,
        runner_path=RUNNER_PATH,
        interpreters={
            "clean-interpreter-a": interpreter_a,
            "clean-interpreter-b": interpreter_b,
        },
        work_dir=tmp_path / "replay",
    )
    report = BenchmarkValidityProtocolFreezeReport.create(
        protocol=protocol,
        projection=projection,
        replay_certificate=certificate,
    )
    output_dir = tmp_path / "formal-freeze"
    manifest = write_benchmark_validity_protocol_freeze(output_dir, report)
    loaded_report, loaded_manifest = load_benchmark_validity_protocol_freeze(
        output_dir
    )

    assert loaded_report.report_hash == report.report_hash
    assert loaded_manifest.manifest_hash == manifest.manifest_hash
    assert len(certificate.observations) == 2
    assert certificate.exact_projection_match
    assert protocol.extracted_record_count == 0
    assert protocol.search_execution_started is False
    assert protocol.benchmark_outcomes_accessed is False
    assert protocol.candidate_model_calls is False
