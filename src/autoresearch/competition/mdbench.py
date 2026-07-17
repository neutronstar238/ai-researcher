"""MDBench-compatible Gate A adapter and deterministic characterization smoke.

The adapter intentionally labels the bundled data as a generated
characterization fixture.  It exercises the real compile/execute/validate/hash
path without pretending that the official 63 ODE / 14 PDE dataset matrix has
already been run.
"""

from __future__ import annotations

import json
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.competition.models import (
    AttemptStatus,
    ExperimentAttempt,
    ExperimentProtocol,
    HypothesisProposal,
    TopicCandidate,
    TopicFeasibility,
)
from autoresearch.experiments import (
    collect_result_bundle,
    execute_experiment_task,
    validate_result_bundle,
)
from autoresearch.schemas import (
    CostRecord,
    ExecutionStatus,
    ExperimentTask,
    ValidationStatus,
    data_hash,
    file_hash,
)

CHARACTERIZATION_SYSTEM_ID = "logistic-equation-characterization"
CHARACTERIZATION_SCOPE = "generated-characterization-fixture-not-official-mdbench-result"
REQUIRED_METRICS = (
    "derivative_nmse",
    "baseline_derivative_nmse",
    "relative_nmse_improvement",
    "equation_structure_f1",
    "trajectory_extrapolation_rmse",
    "model_complexity",
    "noisy_derivative_nmse",
    "runtime_seconds",
    "ode_system_count",
    "pde_system_count",
    "smoke_passed",
    "full_gate_a_passed",
)


@dataclass(frozen=True)
class ExecutedGateAAttempt:
    """Attempt plus paths needed by the manifest hash chain."""

    attempt: ExperimentAttempt
    experiment_dir: Path
    code_path: Path
    data_path: Path
    config_path: Path
    record_path: Path


class MDBenchAdapter:
    """Materialize and execute the Gate A development protocol."""

    adapter_id = "mdbench-model-discovery"
    adapter_version = "0.1.0"

    def run_feasibility_probe(
        self,
        *,
        candidate: TopicCandidate,
        root: Path,
        project_id: str,
        timeout_seconds: int,
    ) -> TopicFeasibility:
        """Run one real sandbox smoke before automatic topic selection."""

        probe_dir = root / candidate.topic_id
        paths = self._materialize(
            experiment_dir=probe_dir,
            candidate=candidate,
            topic_id=candidate.topic_id,
            hypothesis_id=f"feasibility_{candidate.topic_id}",
            protocol_id=f"feasibility_{candidate.topic_id}",
            plan_hash=data_hash({"candidate": candidate.model_dump(mode="json")}),
            seed=5,
        )
        task = self._task(
            project_id=project_id,
            hypothesis_id=f"feasibility_{candidate.topic_id}",
            task_id=f"feasibility_{candidate.topic_id}",
            timeout_seconds=timeout_seconds,
        )
        run = execute_experiment_task(probe_dir, task, entrypoint="run.py")
        metrics_path = probe_dir / "metrics.json"
        metrics = _load_numeric_metrics(metrics_path) if metrics_path.exists() else {}
        passed = (
            run.status is ExecutionStatus.SUCCESS
            and metrics.get("relative_nmse_improvement", 0.0) > 0.0
            and metrics.get("equation_structure_f1", 0.0) >= 0.95
        )
        failure_reason = None
        if not passed:
            failure_reason = run.stderr or run.error_type or "feasibility thresholds failed"
        return TopicFeasibility(
            topic_id=candidate.topic_id,
            passed=passed,
            metric_name="relative_nmse_improvement",
            metric_value=metrics.get("relative_nmse_improvement"),
            evidence_path=metrics_path.as_posix() if metrics_path.exists() else None,
            failure_reason=failure_reason,
            code_hash=file_hash(paths["code"]),
            data_hash=file_hash(paths["data"]),
        )

    def execute_attempt(
        self,
        *,
        cycle_dir: Path,
        project_id: str,
        candidate: TopicCandidate,
        hypothesis: HypothesisProposal,
        protocol: ExperimentProtocol,
        plan_hash: str,
        seed: int,
        parent_attempt_id: str | None,
        timeout_seconds: int,
    ) -> ExecutedGateAAttempt:
        """Execute and validate one seed with full causal identifiers."""

        if protocol.topic_id != candidate.topic_id:
            raise ValueError("candidate/protocol mismatch before experiment materialization")
        if protocol.hypothesis_id != hypothesis.hypothesis_id:
            raise ValueError("hypothesis/protocol mismatch before experiment materialization")

        experiment_dir = cycle_dir / "experiments" / f"seed-{seed}"
        paths = self._materialize(
            experiment_dir=experiment_dir,
            candidate=candidate,
            topic_id=candidate.topic_id,
            hypothesis_id=hypothesis.hypothesis_id,
            protocol_id=protocol.protocol_id,
            plan_hash=plan_hash,
            seed=seed,
        )
        task = self._task(
            project_id=project_id,
            hypothesis_id=hypothesis.hypothesis_id,
            task_id=f"gate_a_{hypothesis.hypothesis_id}_{seed}",
            timeout_seconds=timeout_seconds,
        )
        run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
        cpu_time = 0.0
        if run.start_time is not None and run.end_time is not None:
            cpu_time = max((run.end_time - run.start_time).total_seconds(), 0.0)
        run = run.model_copy(
            update={
                "data_hash": file_hash(paths["data"]),
                "cost_record": CostRecord(
                    model_name="local-deterministic-runner",
                    cpu_time_seconds=cpu_time,
                    human_approval_count=0,
                ),
                "cost_json": {
                    "cpu_time_seconds": cpu_time,
                    "gpu_hours": 0.0,
                    "human_intervention_count": 0,
                },
            }
        )
        bundle = collect_result_bundle(experiment_dir, run)
        validation = validate_result_bundle(
            experiment_dir,
            run,
            bundle,
            expected_metrics=list(REQUIRED_METRICS),
            metric_bounds=_metric_bounds(),
            expected_artifacts=[
                "artifacts/discovered-equation.json",
                "artifacts/summary.md",
            ],
        )
        status = (
            AttemptStatus.SUCCEEDED
            if run.status is ExecutionStatus.SUCCESS
            and validation.status in {ValidationStatus.PASSED, ValidationStatus.WARNING}
            else AttemptStatus.FAILED
        )
        failure_reason = None
        if status is AttemptStatus.FAILED:
            failure_reason = run.stderr or run.error_type or "validation failed"
        attempt = ExperimentAttempt(
            topic_id=candidate.topic_id,
            hypothesis_id=hypothesis.hypothesis_id,
            protocol_id=protocol.protocol_id,
            plan_hash=plan_hash,
            code_hash=file_hash(paths["code"]),
            data_hash=file_hash(paths["data"]),
            config_hash=file_hash(paths["config"]),
            metrics_hash=data_hash(bundle.metrics),
            run_id=run.id,
            seed=seed,
            status=status,
            validation_status=validation.status.value,
            metrics=bundle.metrics,
            metrics_path=(experiment_dir / "metrics.json").as_posix(),
            validation_path=validation.json_path,
            parent_attempt_id=parent_attempt_id,
            failure_reason=failure_reason,
        )
        record_path = experiment_dir / "run" / "attempt.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "attempt": attempt.model_dump(mode="json"),
                    "run": run.model_dump(mode="json"),
                    "validation": validation.to_dict(),
                    "scope": CHARACTERIZATION_SCOPE,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return ExecutedGateAAttempt(
            attempt=attempt,
            experiment_dir=experiment_dir,
            code_path=paths["code"],
            data_path=paths["data"],
            config_path=paths["config"],
            record_path=record_path,
        )

    def _materialize(
        self,
        *,
        experiment_dir: Path,
        candidate: TopicCandidate,
        topic_id: str,
        hypothesis_id: str,
        protocol_id: str,
        plan_hash: str,
        seed: int,
    ) -> dict[str, Path]:
        experiment_dir.mkdir(parents=True, exist_ok=True)
        (experiment_dir / "logs").mkdir(exist_ok=True)
        (experiment_dir / "artifacts").mkdir(exist_ok=True)
        config_path = experiment_dir / "config.yaml"
        data_path = experiment_dir / "data.json"
        code_path = experiment_dir / "run.py"
        config = {
            "topic_id": topic_id,
            "hypothesis_id": hypothesis_id,
            "protocol_id": protocol_id,
            "plan_hash": plan_hash,
            "seed": seed,
            "scope": CHARACTERIZATION_SCOPE,
            "system_id": CHARACTERIZATION_SYSTEM_ID,
            "method_parameters": candidate.method_parameters,
            "required_metrics": list(REQUIRED_METRICS),
        }
        config_path.write_text(
            json.dumps(config, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        data_path.write_text(
            json.dumps(_characterization_data(seed), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        code_path.write_text(_runner_source(), encoding="utf-8")
        (experiment_dir / "requirements.txt").write_text(
            "# Standard-library-only characterization runner.\n",
            encoding="utf-8",
        )
        (experiment_dir / "README.md").write_text(
            _readme(candidate, seed),
            encoding="utf-8",
        )
        return {"config": config_path, "data": data_path, "code": code_path}

    @staticmethod
    def _task(
        *,
        project_id: str,
        hypothesis_id: str,
        task_id: str,
        timeout_seconds: int,
    ) -> ExperimentTask:
        return ExperimentTask(
            id=task_id,
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            name="MDBench-compatible Gate A characterization",
            description=(
                "Execute a real sparse polynomial equation-discovery smoke on a generated "
                "logistic-system fixture."
            ),
            entrypoint="run.py",
            config_path="config.yaml",
            metrics=list(REQUIRED_METRICS),
            resource_budget={
                "cpu_time_seconds": timeout_seconds,
                "memory_mb": 512,
                "gpu_hours": 0.0,
                "storage_mb": 64,
            },
            timeout_seconds=timeout_seconds,
            expected_outputs=[
                "metrics.json",
                "logs/run.log",
                "artifacts/discovered-equation.json",
                "artifacts/summary.md",
            ],
            dependencies=["python>=3.10"],
            metadata={
                "execution_scope": CHARACTERIZATION_SCOPE,
                "dataset_assumptions": {
                    "dataset_ref": CHARACTERIZATION_SYSTEM_ID,
                    "baseline": "constant derivative",
                },
            },
        )


def _characterization_data(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    rows: list[dict[str, float | str]] = []
    for index in range(90):
        x = 0.04 + (0.92 * index / 89.0)
        clean = 2.0 * x - 2.0 * x * x
        noisy = clean + rng.gauss(0.0, 0.006)
        rows.append(
            {
                "split": "train" if index % 5 != 0 else "test",
                "x": x,
                "clean_derivative": clean,
                "observed_derivative": noisy,
            }
        )
    return {
        "scope": CHARACTERIZATION_SCOPE,
        "system_id": CHARACTERIZATION_SYSTEM_ID,
        "governing_equation": "dx/dt = 2*x - 2*x^2",
        "true_active_terms": ["x", "x2"],
        "noise_std": 0.006,
        "rows": rows,
    }


def _metric_bounds() -> dict[str, tuple[float | None, float | None]]:
    return {
        "derivative_nmse": (0.0, None),
        "baseline_derivative_nmse": (0.0, None),
        "relative_nmse_improvement": (-1.0, 1.0),
        "equation_structure_f1": (0.0, 1.0),
        "trajectory_extrapolation_rmse": (0.0, None),
        "model_complexity": (0.0, None),
        "noisy_derivative_nmse": (0.0, None),
        "runtime_seconds": (0.0, None),
        "ode_system_count": (1.0, 1.0),
        "pde_system_count": (0.0, 0.0),
        "smoke_passed": (0.0, 1.0),
        "full_gate_a_passed": (0.0, 0.0),
    }


def _load_numeric_metrics(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw_metrics, dict):
        return {}
    metrics: dict[str, float] = {}
    for name, value in raw_metrics.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            metrics[str(name)] = float(value)
    return metrics


def _readme(candidate: TopicCandidate, seed: int) -> str:
    return textwrap.dedent(
        f"""\
        # Gate A characterization run

        Topic: `{candidate.topic_id}`
        Seed: `{seed}`

        This directory executes a real equation-discovery calculation, but its data is a
        generated characterization fixture. It is not evidence that the official MDBench
        10-ODE/4-PDE acceptance matrix has passed.
        """
    )


def _runner_source() -> str:
    return textwrap.dedent(
        '''\
        from __future__ import annotations

        import json
        import math
        import time
        from pathlib import Path


        def solve_linear(matrix, vector):
            size = len(vector)
            augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
            for column in range(size):
                pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
                augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
                divisor = augmented[column][column]
                if abs(divisor) < 1e-14:
                    raise ValueError("singular normal equation")
                augmented[column] = [value / divisor for value in augmented[column]]
                for row in range(size):
                    if row == column:
                        continue
                    factor = augmented[row][column]
                    augmented[row] = [
                        current - factor * pivot_value
                        for current, pivot_value in zip(augmented[row], augmented[column])
                    ]
            return [augmented[row][-1] for row in range(size)]


        def fit(rows, target, ridge):
            features = [[1.0, row["x"], row["x"] * row["x"]] for row in rows]
            gram = [[0.0 for _ in range(3)] for _ in range(3)]
            rhs = [0.0 for _ in range(3)]
            for feature, row in zip(features, rows):
                for left in range(3):
                    rhs[left] += feature[left] * row[target]
                    for right in range(3):
                        gram[left][right] += feature[left] * feature[right]
            for index in range(3):
                gram[index][index] += ridge
            return solve_linear(gram, rhs)


        def predict(coefficients, x):
            return coefficients[0] + coefficients[1] * x + coefficients[2] * x * x


        def nmse(expected, predicted):
            numerator = sum((truth - guess) ** 2 for truth, guess in zip(expected, predicted))
            denominator = sum(truth * truth for truth in expected) + 1e-10
            return numerator / denominator


        def structure_f1(coefficients, threshold, true_terms):
            names = ["intercept", "x", "x2"]
            active = {name for name, coefficient in zip(names, coefficients) if abs(coefficient) >= threshold}
            truth = set(true_terms)
            true_positive = len(active & truth)
            precision = true_positive / len(active) if active else 0.0
            recall = true_positive / len(truth) if truth else 0.0
            return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


        def trajectory_rmse(coefficients):
            candidate = 0.13
            truth = 0.13
            squared_errors = []
            step = 0.02
            for _ in range(80):
                candidate += step * predict(coefficients, candidate)
                truth += step * (2.0 * truth - 2.0 * truth * truth)
                squared_errors.append((candidate - truth) ** 2)
            return math.sqrt(sum(squared_errors) / len(squared_errors))


        def main():
            started = time.perf_counter()
            root = Path(__file__).resolve().parent
            config = json.loads((root / "config.yaml").read_text(encoding="utf-8"))
            data = json.loads((root / "data.json").read_text(encoding="utf-8"))
            training = [row for row in data["rows"] if row["split"] == "train"]
            testing = [row for row in data["rows"] if row["split"] == "test"]
            ridge = float(config["method_parameters"].get("ridge", 1e-9))
            threshold = float(config["method_parameters"].get("coefficient_threshold", 0.05))
            coefficients = fit(training, "observed_derivative", ridge)
            expected = [row["clean_derivative"] for row in testing]
            observed = [row["observed_derivative"] for row in testing]
            predicted = [predict(coefficients, row["x"]) for row in testing]
            baseline_value = sum(row["observed_derivative"] for row in training) / len(training)
            baseline = [baseline_value for _ in testing]
            derivative_nmse = nmse(expected, predicted)
            baseline_nmse = nmse(expected, baseline)
            relative_improvement = (baseline_nmse - derivative_nmse) / max(baseline_nmse, 1e-12)
            f1 = structure_f1(coefficients, threshold, data["true_active_terms"])
            complexity = sum(1 for coefficient in coefficients if abs(coefficient) >= threshold)
            metrics = {
                "derivative_nmse": derivative_nmse,
                "baseline_derivative_nmse": baseline_nmse,
                "relative_nmse_improvement": relative_improvement,
                "equation_structure_f1": f1,
                "trajectory_extrapolation_rmse": trajectory_rmse(coefficients),
                "model_complexity": float(complexity),
                "noisy_derivative_nmse": nmse(observed, predicted),
                "runtime_seconds": max(time.perf_counter() - started, 0.0),
                "ode_system_count": 1.0,
                "pde_system_count": 0.0,
                "smoke_passed": float(relative_improvement > 0.0 and f1 >= 0.95),
                "full_gate_a_passed": 0.0,
            }
            equation = {
                "equation": "dx/dt = c0 + c1*x + c2*x^2",
                "coefficients": coefficients,
                "threshold": threshold,
                "scope": config["scope"],
                "topic_id": config["topic_id"],
                "hypothesis_id": config["hypothesis_id"],
                "protocol_id": config["protocol_id"],
                "plan_hash": config["plan_hash"],
            }
            (root / "logs" / "run.log").write_text(
                "real sparse polynomial fit completed\\n", encoding="utf-8"
            )
            (root / "artifacts" / "discovered-equation.json").write_text(
                json.dumps(equation, indent=2, sort_keys=True), encoding="utf-8"
            )
            (root / "artifacts" / "summary.md").write_text(
                "# Gate A characterization\\n\\n"
                f"Derivative NMSE: {derivative_nmse:.8f}\\n\\n"
                "This is a generated characterization fixture, not the official MDBench matrix.\\n",
                encoding="utf-8",
            )
            (root / "metrics.json").write_text(
                json.dumps(
                    {
                        "status": "success",
                        "scope": config["scope"],
                        "topic_id": config["topic_id"],
                        "hypothesis_id": config["hypothesis_id"],
                        "protocol_id": config["protocol_id"],
                        "plan_hash": config["plan_hash"],
                        "metrics": metrics,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    )
