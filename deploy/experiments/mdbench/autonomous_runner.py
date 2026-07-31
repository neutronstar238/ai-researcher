#!/usr/bin/env python3
"""Offline runner for one autonomous MDBench development cell.

The host owns candidate selection and aggregation.  This runner only validates
hash-bound inputs, exposes a train-only context plus one query time slice at a
time, executes the exact model-authored source, and computes objective metrics.
The candidate never receives MDBench true derivatives.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import resource
import signal
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp


class AttemptTimeout(Exception):
    """Raised when the immutable per-cell scientific budget expires."""


class CandidateContractError(ValueError):
    """Raised when exact candidate output violates the public adapter."""


def _alarm_handler(_signum, _frame):
    raise AttemptTimeout("in-container autonomous development cell timeout")


def _canonical_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_payload(path, payload):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _load_spec(path, runner_path, data_path, candidate_path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    spec_hash = spec.pop("spec_hash", None)
    if spec_hash != _canonical_hash(spec):
        raise ValueError("autonomous runner spec content hash mismatch")
    if spec.get("expected_runner_sha256") != _file_hash(runner_path):
        raise ValueError("autonomous runner bytes differ from host contract")
    attempt = spec["attempt"]
    if attempt["artifact_sha256"] != _file_hash(data_path):
        raise ValueError("mounted MDBench bytes differ from frozen artifact")
    if attempt["method_kind"] == "candidate":
        if candidate_path is None or not Path(candidate_path).is_file():
            raise ValueError("candidate cell is missing exact source")
        if attempt["source_sha256"] != _file_hash(candidate_path):
            raise ValueError("mounted candidate bytes differ from frozen source")
    return spec, spec_hash


def _split_indices(n_time, policy):
    train_end = int(n_time * float(policy["train"][1]))
    validation_end = int(n_time * float(policy["validation"][1]))
    result = {
        "time_axis_size": int(n_time),
        "train_start": 0,
        "train_end": train_end,
        "validation_start": train_end,
        "validation_end": validation_end,
        "test_start": validation_end,
        "test_end": int(n_time),
    }
    if not (0 < train_end < validation_end < n_time):
        raise ValueError("frozen fractions do not create three non-empty splits")
    return result


def _time_slice(array, start, end, axis):
    slices = [slice(None)] * array.ndim
    slices[axis] = slice(start, end)
    return array[tuple(slices)]


def _selected_indices(start, end, maximum):
    count = end - start
    if maximum is None or count <= int(maximum):
        return list(range(start, end))
    maximum = int(maximum)
    if maximum < 1:
        raise ValueError("fidelity query count must be positive")
    if maximum == 1:
        return [start + count // 2]
    raw = np.linspace(start, end - 1, num=maximum)
    selected = []
    for value in raw:
        index = int(round(float(value)))
        if index not in selected:
            selected.append(index)
    for index in range(start, end):
        if len(selected) >= maximum:
            break
        if index not in selected:
            selected.append(index)
    return sorted(selected[:maximum])


def _nested_shape(value):
    if not isinstance(value, list):
        return (  # noqa: UP038 - the pinned scientific image runs Python 3.9
            ()
            if isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: UP038
            else None
        )
    if not value:
        return (0,)
    child_shapes = [_nested_shape(item) for item in value]
    if any(item is None for item in child_shapes) or len(set(child_shapes)) != 1:
        return None
    return (len(value),) + tuple(child_shapes[0])


def _flatten(value):
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_flatten(item))
        return result
    return [float(value)]


def _reshape_row_major(flat_values, shape):
    expected = int(np.prod(shape, dtype=np.int64))
    if not isinstance(flat_values, list) or len(flat_values) != expected:
        raise CandidateContractError(
            "derivative_prediction_flat length does not match query shape"
        )
    normalized = []
    for value in flat_values:
        if not isinstance(value, (int, float)) or isinstance(value, bool):  # noqa: UP038
            raise CandidateContractError("candidate prediction contains a non-number")
        number = float(value)
        if not math.isfinite(number):
            raise CandidateContractError("candidate prediction contains a non-finite value")
        normalized.append(number)
    return np.asarray(normalized, dtype=np.float64).reshape(tuple(shape))


def _coordinate_axes(data, indices):
    result = {"t": np.asarray(data["t"], dtype=np.float64)[indices].tolist()}
    for key in ("x", "y", "z"):
        if key in data:
            result[key] = np.asarray(data[key], dtype=np.float64).reshape(-1).tolist()
    return result


def _load_candidate(path):
    spec = importlib.util.spec_from_file_location("autonomous_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create exact candidate import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    discover = getattr(module, "discover_equations", None)
    if not callable(discover):
        raise CandidateContractError("candidate does not expose discover_equations")
    return discover


def _candidate_payload(
    data,
    states,
    time_axis,
    query_index,
    train_end,
    validation_end,
    phase,
    attempt,
    *,
    perturbed_train=False,
):
    query = _time_slice(states, query_index, query_index + 1, time_axis)
    train = _time_slice(states, 0, train_end, time_axis).copy()
    if perturbed_train:
        flat_train = train.reshape(-1)
        if flat_train.size:
            flat_train[0] = flat_train[0] + 0.001 * (1.0 + abs(float(flat_train[0])))
    validation = _time_slice(states, train_end, validation_end, time_axis)
    query_values = query.tolist()
    train_values = train.tolist()
    validation_values = validation.tolist()
    spatial_dimensions = sum(key in data for key in ("x", "y", "z"))
    field_count = int(states.shape[-1])
    capability_id = "ode"
    if attempt["data_type"] == "pde":
        capability_id = "multi_field" if field_count > 1 else "pde_%dd" % spatial_dimensions
    return {
        "schema_version": "official-autonomous-equation-discovery-input-v1",
        "capability_id": capability_id,
        "data_type": attempt["data_type"],
        "spatial_dimensions": spatial_dimensions,
        "field_count": field_count,
        "seed": int(attempt["seed"]),
        "phase": phase,
        "values": query_values,
        "flat_values": _flatten(query_values),
        "value_shape": list(query.shape),
        "coordinate_axes": _coordinate_axes(data, [query_index]),
        "train_values": train_values,
        "train_flat_values": _flatten(train_values),
        "train_value_shape": list(train.shape),
        "train_coordinate_axes": _coordinate_axes(data, list(range(0, train_end))),
        "validation_values": validation_values,
        "validation_flat_values": _flatten(validation_values),
        "validation_value_shape": list(validation.shape),
        "validation_coordinate_axes": _coordinate_axes(
            data,
            list(range(train_end, validation_end)),
        ),
        "query_temporal_context_count": 1,
        "true_derivative_exposed": False,
        "adapter_id": "official-single-time-query-v1",
    }


def _call_candidate(discover, payload):
    result = discover(payload)
    if not isinstance(result, dict):
        raise CandidateContractError("candidate output must be a mapping")
    prediction = _reshape_row_major(
        result.get("derivative_prediction_flat"),
        payload["value_shape"],
    )
    equations = result.get("equations")
    if not isinstance(equations, list) or len(equations) != payload["field_count"]:
        raise CandidateContractError("candidate must return one equation per field")
    if not all(isinstance(item, str) and item.strip() for item in equations):
        raise CandidateContractError("candidate equation text must be non-empty")
    complexity = result.get("complexity")
    if (
        not isinstance(complexity, int)
        or isinstance(complexity, bool)
        or not 1 <= complexity <= 100000
    ):
        raise CandidateContractError("candidate complexity is outside the contract")
    return prediction, equations, complexity


def _nmse(expected, predicted):
    truth = np.asarray(expected, dtype=np.float64)
    prediction = np.asarray(predicted, dtype=np.float64).reshape(truth.shape)
    denominator = float(np.sum(truth**2)) + 1e-10
    return float(np.sum((truth - prediction) ** 2) / denominator)


def _prediction_for_indices(
    discover,
    data,
    states,
    time_axis,
    indices,
    train_end,
    validation_end,
    phase,
    attempt,
):
    predictions = []
    equations = None
    complexities = []
    for query_index in indices:
        payload = _candidate_payload(
            data,
            states,
            time_axis,
            query_index,
            train_end,
            validation_end,
            phase,
            attempt,
        )
        prediction, current_equations, complexity = _call_candidate(discover, payload)
        if equations is None:
            equations = current_equations
        elif equations != current_equations:
            raise CandidateContractError("candidate equations changed across query slices")
        predictions.append(prediction)
        complexities.append(complexity)
    if not predictions:
        raise CandidateContractError("fidelity policy selected no query slices")
    return np.concatenate(predictions, axis=time_axis), equations, max(complexities)


def _training_sensitivity(
    discover,
    data,
    states,
    time_axis,
    query_index,
    train_end,
    validation_end,
    attempt,
):
    original_payload = _candidate_payload(
        data,
        states,
        time_axis,
        query_index,
        train_end,
        validation_end,
        "validation",
        attempt,
    )
    perturbed_payload = _candidate_payload(
        data,
        states,
        time_axis,
        query_index,
        train_end,
        validation_end,
        "validation",
        attempt,
        perturbed_train=True,
    )
    original, _, _ = _call_candidate(discover, original_payload)
    perturbed, _, _ = _call_candidate(discover, perturbed_payload)
    return float(np.max(np.abs(original - perturbed)))


def _trajectory_nmse(
    discover,
    data,
    states,
    time_axis,
    split,
    attempt,
):
    if attempt["data_type"] != "ode" or states.ndim != 2:
        return None
    times = np.asarray(data["t"], dtype=np.float64)[split["test_start"] : split["test_end"]]
    truth = states[split["test_start"] : split["test_end"]]
    if len(times) < 2:
        return None

    def rhs(current_time, state):
        payload = _candidate_payload(
            data,
            states,
            time_axis,
            split["test_start"],
            split["train_end"],
            split["validation_end"],
            "trajectory",
            attempt,
        )
        nested = np.asarray(state, dtype=np.float64).reshape(1, -1).tolist()
        payload["values"] = nested
        payload["flat_values"] = _flatten(nested)
        payload["value_shape"] = [1, int(len(state))]
        payload["coordinate_axes"] = {"t": [float(current_time)]}
        prediction, _, _ = _call_candidate(discover, payload)
        return prediction.reshape(-1)

    try:
        solution = solve_ivp(
            rhs,
            (float(times[0]), float(times[-1])),
            truth[0],
            t_eval=times,
            rtol=1e-6,
            atol=1e-8,
        )
        if not solution.success or solution.y.T.shape != truth.shape:
            return None
        return _nmse(truth, solution.y.T)
    except Exception:
        return None


def _run_candidate(spec, data, candidate_path):
    attempt = spec["attempt"]
    fidelity = spec["fidelity"]
    states = np.asarray(data["u"], dtype=np.float64)
    true_derivative = np.asarray(data["du"], dtype=np.float64)
    times = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    time_axis = 0 if states.ndim == 2 else states.ndim - 2
    if states.shape != true_derivative.shape or states.shape[time_axis] != len(times):
        raise ValueError("MDBench state/derivative/time shapes are inconsistent")
    split = _split_indices(len(times), spec["split_policy"])
    validation_indices = _selected_indices(
        split["validation_start"],
        split["validation_end"],
        fidelity.get("maximum_validation_query_points"),
    )
    test_indices = _selected_indices(
        split["test_start"],
        split["test_end"],
        fidelity.get("maximum_test_query_points"),
    )
    discover = _load_candidate(candidate_path)
    validation_prediction, _validation_equations, validation_complexity = (
        _prediction_for_indices(
            discover,
            data,
            states,
            time_axis,
            validation_indices,
            split["train_end"],
            split["validation_end"],
            "validation",
            attempt,
        )
    )
    test_prediction, equations, test_complexity = _prediction_for_indices(
        discover,
        data,
        states,
        time_axis,
        test_indices,
        split["train_end"],
        split["validation_end"],
        "test",
        attempt,
    )
    validation_truth = np.take(true_derivative, validation_indices, axis=time_axis)
    test_truth = np.take(true_derivative, test_indices, axis=time_axis)
    sensitivity = _training_sensitivity(
        discover,
        data,
        states,
        time_axis,
        validation_indices[0],
        split["train_end"],
        split["validation_end"],
        attempt,
    )
    trajectory = None
    if fidelity.get("compute_full_ode_trajectory") is True:
        trajectory = _trajectory_nmse(
            discover,
            data,
            states,
            time_axis,
            split,
            attempt,
        )
    return {
        "split_indices": split,
        "selected_hyperparameters": {
            "adapter_id": "official-single-time-query-v1",
            "fidelity": fidelity,
            "validation_query_indices": validation_indices,
            "test_query_indices": test_indices,
        },
        "discovered_equation": "\n".join(equations),
        "validation_nmse": _nmse(validation_truth, validation_prediction),
        "derivative_nmse": _nmse(test_truth, test_prediction),
        "trajectory_extrapolation_nmse_ode": trajectory,
        "model_complexity": int(max(validation_complexity, test_complexity)),
        "training_context_sensitivity_max_abs": sensitivity,
        "validation_query_count": len(validation_indices),
        "test_query_count": len(test_indices),
        "true_derivative_exposed_to_candidate": False,
        "query_temporal_context_count": 1,
        "candidate_output_numeric_transform_count": 0,
    }


def _run_operon_baseline(spec, data):
    baseline_path = Path("/opt/autoresearch-mdbench/runner.py")
    if _file_hash(baseline_path) != spec["expected_baseline_runner_sha256"]:
        raise ValueError("pinned Operon runner bytes differ from host contract")
    module_spec = importlib.util.spec_from_file_location("mdbench_gate_a_runner", baseline_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("cannot import pinned MDBench baseline runner")
    baseline = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baseline)
    states = np.asarray(data["u"], dtype=np.float64)
    times = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    time_axis = 0 if states.ndim == 2 else states.ndim - 2
    split = _split_indices(len(times), spec["split_policy"])
    pieces, spatial_grids, base_time_axis = baseline._split_data(data, split)
    if base_time_axis != time_axis:
        raise ValueError("baseline and autonomous runner disagree on the time axis")
    base_spec = {
        "attempt": spec["attempt"],
        "method": spec["baseline_method"],
        "split_policy": spec["split_policy"],
    }
    result = baseline._run_operon(base_spec, pieces, spatial_grids, time_axis)
    result.update(
        {
            "split_indices": split,
            "training_context_sensitivity_max_abs": None,
            "validation_query_count": split["validation_end"] - split["validation_start"],
            "test_query_count": split["test_end"] - split["test_start"],
            "true_derivative_exposed_to_candidate": False,
            "query_temporal_context_count": 1,
            "candidate_output_numeric_transform_count": 0,
        }
    )
    return result


def _peak_rss_mb():
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _base_payload(spec_hash, status, started):
    return {
        "schema_version": "autonomous-development-runner-payload-v1",
        "spec_hash": spec_hash,
        "status": status,
        "split_indices": None,
        "selected_hyperparameters": {},
        "discovered_equation": None,
        "validation_nmse": None,
        "derivative_nmse": None,
        "trajectory_extrapolation_nmse_ode": None,
        "model_complexity": None,
        "training_context_sensitivity_max_abs": None,
        "validation_query_count": 0,
        "test_query_count": 0,
        "true_derivative_exposed_to_candidate": False,
        "query_temporal_context_count": 1,
        "candidate_output_numeric_transform_count": 0,
        "wall_time_seconds": float(time.time() - started),
        "peak_rss_mb": _peak_rss_mb(),
        "failure_reason": None,
    }


def run(spec_path, data_path, candidate_path, output_path):
    started = time.time()
    spec = None
    spec_hash = "0" * 64
    payload = _base_payload(spec_hash, "failed", started)
    try:
        spec, spec_hash = _load_spec(
            spec_path,
            Path(__file__).resolve(),
            data_path,
            candidate_path,
        )
        payload = _base_payload(spec_hash, "failed", started)
        timeout_seconds = int(spec["maximum_seconds"])
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(timeout_seconds)
        with np.load(data_path, allow_pickle=False) as archive:
            data = {key: archive[key] for key in archive.files}
        if spec["attempt"]["method_kind"] == "candidate":
            result = _run_candidate(spec, data, candidate_path)
        elif spec["attempt"]["method_kind"] == "operon_gp":
            result = _run_operon_baseline(spec, data)
        else:
            raise ValueError("unknown autonomous development method kind")
        payload.update(result)
        payload.update({"status": "succeeded", "failure_reason": None})
    except AttemptTimeout as exc:
        payload.update({"status": "timed_out", "failure_reason": str(exc)})
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        payload.update(
            {
                "status": "failed",
                "failure_reason": type(exc).__name__ + ": " + str(exc),
            }
        )
    finally:
        signal.alarm(0)
        payload["wall_time_seconds"] = float(time.time() - started)
        payload["peak_rss_mb"] = _peak_rss_mb()
        _write_payload(output_path, payload)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.spec, arguments.data, arguments.candidate, arguments.output)
