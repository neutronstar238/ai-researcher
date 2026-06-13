"""End-to-end local demo workflows for MVP verification."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.experiments.demos import (
    PENDIGITS_CENTROID_BASELINE_TASK_ID,
    PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID,
    PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
    TABULAR_BASELINE_TASK_ID,
    TEXT_CLASSIFIER_STUB_TASK_ID,
    generate_pendigits_centroid_baseline_demo,
    generate_pendigits_prototype_shrinkage_demo,
    generate_pendigits_variance_calibrated_demo,
    generate_tabular_baseline_demo,
    generate_text_classifier_stub_demo,
)
from autoresearch.experiments.evidence import bind_metrics_to_evidence
from autoresearch.experiments.executor import execute_experiment_task
from autoresearch.experiments.results import collect_result_bundle
from autoresearch.experiments.validation import StatisticalCheck, validate_result_bundle
from autoresearch.reports import (
    ReportContext,
    assert_report_readable,
    generate_markdown_report,
)
from autoresearch.schemas import CostRecord, EvidenceEdge, ExperimentTask, file_hash


@dataclass(frozen=True)
class DemoWorkflowResult:
    """Filesystem outputs from a local end-to-end demo run."""

    demo: str
    experiment_dir: Path
    task: ExperimentTask
    report_path: Path
    evidence_map_path: Path
    run_record_path: Path
    validation_json_path: Path
    validation_markdown_path: Path
    run_id: str


def run_scientistbench_demo(
    demo: str = TABULAR_BASELINE_TASK_ID,
    *,
    output_dir: Path | str = Path("runs/demo"),
    timeout_seconds: int = 30,
    commit_sha: str | None = None,
) -> DemoWorkflowResult:
    """Run one local demo or public benchmark through the local MVP loop."""

    experiment_dir, task = _generate_demo(demo, Path(output_dir), timeout_seconds)
    run = execute_experiment_task(
        experiment_dir,
        task,
        entrypoint="run.py",
        commit_sha=commit_sha or _current_commit_sha(),
    )
    run = run.model_copy(
        update={
            "data_hash": file_hash(_data_path(experiment_dir, demo)),
            "cost_record": _cost_record(run),
            "cost_json": _cost_json(run),
        }
    )
    bundle = collect_result_bundle(experiment_dir, run)
    validation = validate_result_bundle(
        experiment_dir,
        run,
        bundle,
        expected_metrics=task.metrics,
        metric_bounds=_metric_bounds(demo),
        expected_artifacts=_expected_artifacts(task),
        statistical_checks=_statistical_checks(demo, bundle),
    )
    evidence_edges = bind_metrics_to_evidence(
        bundle,
        validation,
        claim_id=f"{task.id}_claim",
    )
    report_context = _report_context(task, run, bundle, validation, evidence_edges, output_dir)
    run_record_path = _write_run_record(
        experiment_dir,
        task,
        run,
        bundle,
        validation,
        report_context,
    )
    evidence_map_path = _write_evidence_map(experiment_dir, task, evidence_edges)
    report_path = experiment_dir / "report" / "report.md"
    report = generate_markdown_report(
        report_context,
        output_path=report_path,
    )
    assert_report_readable(report, base_dir=experiment_dir)
    return DemoWorkflowResult(
        demo=demo,
        experiment_dir=experiment_dir,
        task=task,
        report_path=report_path,
        evidence_map_path=evidence_map_path,
        run_record_path=run_record_path,
        validation_json_path=Path(validation.json_path),
        validation_markdown_path=Path(validation.markdown_path),
        run_id=run.id,
    )


def _generate_demo(
    demo: str,
    output_dir: Path,
    timeout_seconds: int,
) -> tuple[Path, ExperimentTask]:
    if demo == TABULAR_BASELINE_TASK_ID:
        return generate_tabular_baseline_demo(
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    if demo == TEXT_CLASSIFIER_STUB_TASK_ID:
        return generate_text_classifier_stub_demo(
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    if demo == PENDIGITS_CENTROID_BASELINE_TASK_ID:
        return generate_pendigits_centroid_baseline_demo(
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    if demo == PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID:
        return generate_pendigits_prototype_shrinkage_demo(
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    if demo == PENDIGITS_VARIANCE_CALIBRATED_TASK_ID:
        return generate_pendigits_variance_calibrated_demo(
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    msg = f"unknown demo {demo!r}"
    raise ValueError(msg)


def _data_path(experiment_dir: Path, demo: str) -> Path:
    return experiment_dir / "data" / f"{demo}.csv"


def _cost_json(run: Any) -> dict[str, float | int]:
    cpu_time_seconds = 0.0
    if run.start_time is not None and run.end_time is not None:
        cpu_time_seconds = max((run.end_time - run.start_time).total_seconds(), 0.0)
    return {
        "cpu_time_seconds": cpu_time_seconds,
        "gpu_hours": 0.0,
        "human_approval_count": 0,
    }


def _cost_record(run: Any) -> CostRecord:
    cpu_time_seconds = 0.0
    if run.start_time is not None and run.end_time is not None:
        cpu_time_seconds = max((run.end_time - run.start_time).total_seconds(), 0.0)
    return CostRecord(
        model_name="local-runner",
        cpu_time_seconds=cpu_time_seconds,
        gpu_hours=0.0,
        human_approval_count=0,
    )


def _metric_bounds(demo: str) -> dict[str, tuple[float | None, float | None]]:
    if demo == TABULAR_BASELINE_TASK_ID:
        return {
            "accuracy": (0.0, 1.0),
            "test_rows": (1.0, None),
        }
    if demo == PENDIGITS_CENTROID_BASELINE_TASK_ID:
        return {
            "accuracy": (0.0, 1.0),
            "macro_f1": (0.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "class_count": (2.0, None),
            "ablation_accuracy_first8": (0.0, 1.0),
            "accuracy_delta_vs_ablation": (-1.0, 1.0),
            "accuracy_standard_error": (0.0, 1.0),
        }
    if demo == PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID:
        return {
            "accuracy": (0.0, 1.0),
            "macro_f1": (0.0, 1.0),
            "baseline_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_baseline": (-1.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "class_count": (2.0, None),
            "ablation_accuracy_first8": (0.0, 1.0),
            "accuracy_delta_vs_ablation": (-1.0, 1.0),
            "accuracy_standard_error": (0.0, 1.0),
            "prototype_shift_l2_mean": (0.0, None),
            "shrinkage_alpha": (0.0, 1.0),
        }
    if demo == PENDIGITS_VARIANCE_CALIBRATED_TASK_ID:
        return {
            "accuracy": (0.0, 1.0),
            "macro_f1": (0.0, 1.0),
            "baseline_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_baseline": (-1.0, 1.0),
            "zscore_centroid_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_zscore": (-1.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "class_count": (2.0, None),
            "accuracy_standard_error": (0.0, 1.0),
            "variance_shrinkage": (0.0, 1.0),
        }
    return {
        "accuracy": (0.0, 1.0),
        "test_rows": (1.0, None),
        "vocabulary_size": (1.0, None),
    }


def _statistical_checks(demo: str, bundle: Any) -> list[StatisticalCheck]:
    if demo not in {
        PENDIGITS_CENTROID_BASELINE_TASK_ID,
        PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID,
        PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
    }:
        return []
    test_rows = int(float(bundle.metrics.get("test_rows", 0.0) or 0.0))
    accuracy = float(bundle.metrics.get("accuracy", 0.0) or 0.0)
    standard_error = float(bundle.metrics.get("accuracy_standard_error", 0.0) or 0.0)
    baseline_key = (
        "baseline_accuracy"
        if demo
        in {
            PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID,
            PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
        }
        else "ablation_accuracy_first8"
    )
    baseline_accuracy = float(bundle.metrics.get(baseline_key, 0.0) or 0.0)
    return [
        StatisticalCheck(
            metric_name="accuracy",
            sample_size=test_rows,
            mean=accuracy,
            standard_error=standard_error,
            baseline_mean=baseline_accuracy,
            comparison_mean=accuracy,
            min_sample_size=1000,
        )
    ]


def _expected_artifacts(task: ExperimentTask) -> list[Path | str]:
    return [
        output
        for output in task.expected_outputs
        if output.startswith("artifacts/")
    ]


def _write_evidence_map(
    experiment_dir: Path,
    task: ExperimentTask,
    evidence_edges: list[EvidenceEdge],
) -> Path:
    evidence_dir = experiment_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    evidence_map_path = evidence_dir / "evidence-map.json"
    payload = {
        "task_id": task.id,
        "evidence_edges": [
            edge.model_dump(mode="json")
            for edge in evidence_edges
        ],
    }
    evidence_map_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return evidence_map_path


def _write_run_record(
    experiment_dir: Path,
    task: ExperimentTask,
    run: Any,
    bundle: Any,
    validation: Any,
    report_context: ReportContext,
) -> Path:
    run_dir = experiment_dir / "run"
    run_dir.mkdir(exist_ok=True)
    run_record_path = run_dir / "run-record.json"
    payload = {
        "run": run.model_dump(mode="json"),
        "metrics": {
            "path": run.metrics_path,
            "values": bundle.metrics,
        },
        "task_metadata": task.metadata,
        "logs": bundle.logs,
        "artifacts": bundle.artifacts,
        "validation_report": {
            "status": validation.status.value,
            "json_path": validation.json_path,
            "markdown_path": validation.markdown_path,
        },
        "reproducibility": {
            "command": report_context.reproduction_command,
            "python_version": report_context.python_version,
            "dependency_lock_status": report_context.dependency_lock_status,
            "commit_sha": run.commit_sha,
            "config_hash": run.config_hash,
            "data_hash": run.data_hash,
        },
        "cost_record": (
            run.cost_record.model_dump(mode="json")
            if run.cost_record is not None
            else None
        ),
    }
    run_record_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_record_path


def _report_context(
    task: ExperimentTask,
    run: Any,
    bundle: Any,
    validation: Any,
    evidence_edges: list[EvidenceEdge],
    output_dir: Path | str,
) -> ReportContext:
    command = f"airesearcher run-demo --demo {task.id} --output-dir {Path(output_dir)}"
    if task.id == PENDIGITS_VARIANCE_CALIBRATED_TASK_ID:
        return ReportContext(
            title="UCI Pendigits Variance-Calibrated Prototype Report",
            question=(
                "Can AI-Researcher validate a positive-effect prototype-family "
                "method candidate on a real public benchmark while keeping "
                "publication claims gated by method-effect evidence?"
            ),
            literature_summary=(
                "This is an opt-in real benchmark method-candidate check using "
                "the UCI Pendigits train/test files fetched by the experiment "
                "script. It still requires broad online related-work retrieval "
                "and novelty comparison before publication claims."
            ),
            hypothesis=(
                "Diagonal feature-variance calibration may give class prototypes "
                "a better distance model than raw nearest-centroid classification. "
                "The run must record the baseline-vs-candidate delta."
            ),
            experiment_design=task.description,
            run=run,
            results=bundle,
            validation=validation,
            evidence_edges=evidence_edges,
            reproduction_command=command,
            python_version=sys.version.split()[0],
            dependency_lock_status=_dependency_lock_status(),
            limitations=[
                "Single public benchmark and one interpretable method candidate "
                "only; positive effect evidence is necessary but still not enough "
                "for publication without broader novelty and robustness checks.",
            ],
            next_steps=[
                "Use similarity search to compare diagonal variance calibration "
                "against Gaussian discriminant, prototype, and nearest-centroid "
                "calibration literature before claiming novelty.",
            ],
        )
    if task.id == PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID:
        return ReportContext(
            title="UCI Pendigits Prototype Shrinkage Report",
            question=(
                "Can AI-Researcher implement and validate a concrete method "
                "candidate beyond a nearest-centroid baseline while preserving "
                "honest evidence about empirical gain?"
            ),
            literature_summary=(
                "This is an opt-in real benchmark method-candidate check using "
                "the UCI Pendigits train/test files fetched by the experiment "
                "script. It still requires broader online related-work retrieval "
                "and novelty comparison before publication claims."
            ),
            hypothesis=(
                "Shrinking class prototypes toward the global feature mean may "
                "stabilize centroid classification. The run must report whether "
                "the candidate improves, ties, or hurts the baseline."
            ),
            experiment_design=task.description,
            run=run,
            results=bundle,
            validation=validation,
            evidence_edges=evidence_edges,
            reproduction_command=command,
            python_version=sys.version.split()[0],
            dependency_lock_status=_dependency_lock_status(),
            limitations=[
                "Single public benchmark and one simple method candidate only; "
                "empirical gain must be interpreted from the recorded delta, not "
                "assumed from the presence of an innovation artifact.",
            ],
            next_steps=[
                "Use similarity search to compare prototype shrinkage against "
                "existing nearest-centroid and prototype-calibration literature.",
            ],
        )
    if task.id == PENDIGITS_CENTROID_BASELINE_TASK_ID:
        return ReportContext(
            title="UCI Pendigits Centroid Baseline Report",
            question=(
                "Can AI-Researcher run a real public benchmark script, validate "
                "source-backed data and metrics, and preserve enough evidence for "
                "publication-quality auditing?"
            ),
            literature_summary=(
                "This is an opt-in real benchmark check using the UCI Pendigits "
                "train/test files fetched by the experiment script. It does not "
                "replace broader online related-work retrieval or novelty search."
            ),
            hypothesis=(
                "A nearest-centroid baseline should produce bounded metrics on the "
                "official Pendigits test split, while a first-8-features ablation "
                "should provide mechanism-comparison evidence and statistical sanity."
            ),
            experiment_design=task.description,
            run=run,
            results=bundle,
            validation=validation,
            evidence_edges=evidence_edges,
            reproduction_command=command,
            python_version=sys.version.split()[0],
            dependency_lock_status=_dependency_lock_status(),
            limitations=[
                "Single public benchmark and simple baseline only; this is not enough "
                "for a CCF-B/Q3 submission without broader literature positioning, "
                "stronger methods, repeated runs, and manuscript-quality writing.",
            ],
            next_steps=[
                "Use the publication audit output to drive broader source retrieval, "
                "method improvements, and paper-structured drafting.",
            ],
        )
    return ReportContext(
        title=f"ScientistBench-Lite {task.id} Report",
        question=f"Can the local demo task `{task.id}` complete the MVP loop?",
        literature_summary=(
            "This is a local synthetic ScientistBench-Lite check; no external "
            "literature retrieval is used."
        ),
        hypothesis=(
            "A tiny deterministic fixture should produce bounded metrics, "
            "validated artifacts, evidence edges, and a readable report."
        ),
        experiment_design=task.description,
        run=run,
        results=bundle,
        validation=validation,
        evidence_edges=evidence_edges,
        reproduction_command=command,
        python_version=sys.version.split()[0],
        dependency_lock_status=_dependency_lock_status(),
        limitations=[
            "Synthetic fixture only; this checks loop correctness, not model quality.",
        ],
        next_steps=[
            "Connect the same command to candidate selection and vault records.",
        ],
    )


def _dependency_lock_status() -> str:
    return "poetry.lock present" if Path("poetry.lock").exists() else "poetry.lock missing"


def _current_commit_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None
