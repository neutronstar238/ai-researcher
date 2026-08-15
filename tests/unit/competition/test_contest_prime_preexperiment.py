"""Tests for the real, bounded prime-gap preexperiment runner."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

import autoresearch.competition.contest_prime_preexperiment as module
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentError,
    ContestPrimePreexperimentParameters,
    PrimeIntervalSpec,
    PrimePreexperimentManifest,
    load_contest_prime_preexperiment,
    run_contest_prime_preexperiment,
)


def _parameters() -> ContestPrimePreexperimentParameters:
    return ContestPrimePreexperimentParameters(
        intervals=tuple(
            PrimeIntervalSpec(start=start, stop=start + 50_000)
            for start in (100_000, 200_000, 300_000, 400_000, 500_000)
        ),
        null_draws=199,
        fixed_interval_resampling_draws=1_000,
        wheel_density_segment_width=10_000,
    )


@pytest.fixture(scope="module")
def completed_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Any, Path]:
    root = tmp_path_factory.mktemp("prime-preexperiment") / "run"
    source_plan = root.parent / "source-plan.json"
    source_plan.write_text(
        json.dumps(
            {
                "title": "有限尺度下素数间隙序列局部顺序结构的信息论检验计划",
                "results": "尚未执行预实验",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artifact = run_contest_prime_preexperiment(
        output_dir=root,
        parameters=_parameters(),
        source_plan_path=source_plan,
    )
    return root, artifact, source_plan


def test_real_run_persists_raw_null_metrics_logs_and_hash_manifest(
    completed_run: tuple[Path, Any, Path],
) -> None:
    root, artifact, source_plan = completed_run

    assert artifact.status == "completed"
    assert artifact.study_phase == "exploratory_pilot"
    assert artifact.protocol_status == "protocol_amended_before_execution"
    assert artifact.protocol_frozen_before_data_generation is True
    assert artifact.formal_experiment_executed is False
    assert artifact.mathematical_proof_claimed is False
    assert artifact.primary_null_model == "residue_path_conditioned_permutation"
    assert artifact.parameters.wheel_modulus == 210
    assert artifact.required_sensitivity_null_models == (
        "local_block_permutation",
        "wheel_210",
    )
    assert artifact.source_plan_path == source_plan.resolve().as_posix()
    assert artifact.source_plan_sha256 == hashlib.sha256(source_plan.read_bytes()).hexdigest()
    assert "而非依据结果调规则" in artifact.protocol_amendment_reason_zh
    assert "不能证明" in artifact.scientific_boundary_zh

    assert len(artifact.interval_results) == 5
    for interval in artifact.interval_results:
        assert interval.prime_count == interval.gap_count + 1
        assert interval.residue_conditioned_variable_position_fraction >= 0.8
        assert len(interval.null_summaries) == 4
        assert {summary.null_model for summary in interval.null_summaries} == {
            "local_block_permutation",
            "global_permutation",
            "residue_path_conditioned_permutation",
            "wheel_210",
        }
        residue = next(
            summary
            for summary in interval.null_summaries
            if summary.null_model == "residue_path_conditioned_permutation"
        )
        assert residue.residue_conditioned_variable_position_fraction == (
            interval.residue_conditioned_variable_position_fraction
        )
        assert 1 / 200 <= residue.one_sided_empirical_p_lower <= 1
        assert residue.holm_adjusted_p_across_intervals >= residue.one_sided_empirical_p_lower

        raw_path = root / interval.raw_relative_path
        with raw_path.open(encoding="utf-8", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
        assert len(raw_rows) == interval.gap_count
        assert int(raw_rows[0]["prime_right"]) - int(raw_rows[0]["prime_left"]) == int(
            raw_rows[0]["gap"]
        )

        null_path = root / interval.null_draws_relative_path
        with null_path.open(encoding="utf-8", newline="") as handle:
            null_rows = list(csv.DictReader(handle))
        assert len(null_rows) == 4 * artifact.parameters.null_draws
        assert {row["null_model"] for row in null_rows} == {
            "local_block_permutation",
            "global_permutation",
            "residue_path_conditioned_permutation",
            "wheel_210",
        }

    assert len(artifact.aggregate_results) == 4
    for aggregate in artifact.aggregate_results:
        assert aggregate.inference_scope.startswith("descriptive_n5_fixed")
        assert aggregate.holm_adjusted_p_across_null_models >= aggregate.one_sided_empirical_p_lower
        lower, upper = aggregate.fixed_interval_resampling_delta_ci95
        assert lower <= upper

    metrics = json.loads((root / artifact.metrics_relative_path).read_text("utf-8"))
    assert isinstance(metrics, dict)
    assert metrics["status"] == "completed"
    assert len(metrics["interval_results"]) == 5
    parameters = json.loads((root / "parameters.json").read_text("utf-8"))
    assert parameters["wheel_modulus"] == 210
    assert (
        (root / artifact.stdout_log_relative_path)
        .read_text("utf-8")
        .endswith("program_status=completed\n")
    )
    assert (root / artifact.stderr_log_relative_path).read_text("utf-8") == ""

    manifest_path = root / artifact.manifest_relative_path
    assert artifact.manifest_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest = PrimePreexperimentManifest.model_validate_json(manifest_path.read_text("utf-8"))
    assert manifest.manifest_hash == artifact.manifest_hash
    assert tuple(manifest.files) == artifact.evidence_files
    assert load_contest_prime_preexperiment(root / "prime-preexperiment.json") == artifact


def test_plan_context_exposes_locked_numbers_and_scope(
    completed_run: tuple[Path, Any, Path],
) -> None:
    _, artifact, _ = completed_run
    context = artifact.plan_context_payload()

    assert context["execution_status"] == "completed"
    assert context["parameters_hash"] == artifact.parameters_hash
    assert context["primary_null_model"] == "residue_path_conditioned_permutation"
    assert context["source_plan"]["sha256"] == artifact.source_plan_sha256
    assert len(context["interval_results"]) == 5
    assert len(context["aggregate_results"]) == 4
    assert context["evidence"]["manifest_sha256"] == artifact.manifest_sha256
    assert context["evidence"]["artifact_hash"] == artifact.artifact_hash
    assert "不得外推" in context["interpretation_rule_zh"]
    assert "强约束对照" in context["interpretation_rule_zh"]


def test_modified_permutation_entropy_maps_equal_values_to_equal_ranks() -> None:
    sequence = np.asarray([2, 2, 4, 4, 6, 2, 2, 4, 4, 6, 2, 2], dtype=np.int64)
    metrics = module._sequence_metrics(sequence, ordinal_dimension=5)
    scaled = module._sequence_metrics(sequence * 11, ordinal_dimension=5)

    assert metrics == scaled
    assert 0 <= metrics.tie_aware_normalized_permutation_entropy_m5 <= 1
    assert module._ordered_bell_number(5) == 541


def test_manifest_verification_detects_raw_file_tampering(
    completed_run: tuple[Path, Any, Path],
) -> None:
    root, artifact, _ = completed_run
    raw_path = root / artifact.interval_results[0].raw_relative_path
    original = raw_path.read_bytes()
    try:
        raw_path.write_bytes(original + b"999983,999979,-4\n")
        with pytest.raises(ContestPrimePreexperimentError, match="mismatch"):
            load_contest_prime_preexperiment(root / "prime-preexperiment.json")
    finally:
        raw_path.write_bytes(original)
    assert load_contest_prime_preexperiment(root / "prime-preexperiment.json") == artifact


def test_runtime_failure_persists_failure_logs_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_sieve(_start: int, _stop: int) -> np.ndarray[Any, np.dtype[np.int64]]:
        raise RuntimeError("injected segmented-sieve failure")

    monkeypatch.setattr(module, "_generate_primes_in_interval", fail_sieve)
    root = tmp_path / "failed"
    with pytest.raises(
        ContestPrimePreexperimentError, match="after evidence persistence"
    ) as captured:
        run_contest_prime_preexperiment(output_dir=root, parameters=_parameters())

    error = captured.value
    assert error.failure_path == root.resolve() / "failure.json"
    assert error.manifest_path == root.resolve() / "manifest.json"
    failure = json.loads((root / "failure.json").read_text("utf-8"))
    assert failure["status"] == "failed"
    assert failure["error_type"] == "RuntimeError"
    assert "injected segmented-sieve failure" in (root / "logs/stderr.log").read_text("utf-8")
    manifest = PrimePreexperimentManifest.model_validate_json(
        (root / "manifest.json").read_text("utf-8")
    )
    assert manifest.program_status == "failed"
    assert any(file.kind == "failure" for file in manifest.files)


def test_parameter_contract_rejects_overlap_or_less_than_199_draws() -> None:
    intervals = tuple(
        PrimeIntervalSpec(start=start, stop=start + 50_000)
        for start in (100_000, 120_000, 300_000, 400_000, 500_000)
    )
    with pytest.raises(ValidationError, match="must not overlap"):
        ContestPrimePreexperimentParameters(intervals=intervals)
    with pytest.raises(ValidationError):
        ContestPrimePreexperimentParameters(null_draws=198)


def test_runner_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "owned-by-user.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ContestPrimePreexperimentError, match="refusing overwrite"):
        run_contest_prime_preexperiment(output_dir=root, parameters=_parameters())
    assert marker.read_text("utf-8") == "keep"
