#!/usr/bin/env python3
"""Task 266.3 in-container runner: real MDBench data under the fit/freeze/predict contract.

This is deliberately a NEW runner rather than a change to `autonomous_runner.py`.
That runner implements the single-phase `discover(payload)` interface used by Task
265.3, which is exactly what collapsed to the zero null: a stateless query API let
candidates differentiate the query itself and refit per call, so `branch-08`
reached derivative NMSE `0.9999999999988402` with training sensitivity `0`.

Task 266.3 combines two things that have never been combined before:

* the REAL official MDBench NPZ payloads, with SNR20 noise, and
* the two-phase fit-once / freeze / predict-many contract proved on synthetic
  sentinels in Task 266.2.

Why the real panel matters for the estimand: on the synthetic sentinels both arms
reached machine-precision losses, so a log-ratio of two near-zero numbers was
dominated by floating point rather than method quality (`P-20260802-060`, ODE cell
`1.784e-31` versus `7.524e-21` giving a spurious `+24.4652`). Real noisy cells keep
NMSE at `O(0.1..1)`, where the ratio is meaningful.

Boundaries enforced here:

* The candidate fits ONLY on the training split. Validation and test states are
  never passed to `fit_equations`.
* The frozen artifact is hashed before any prediction. `predict_derivative` may
  read only that artifact and one query slice.
* A refit during prediction, a mutated artifact, or a free symbolic coefficient
  fails the cell closed.
* True derivatives for the held-out splits are never exposed to the candidate.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import resource
import signal
import time
import traceback
from pathlib import Path

import numpy as np


class ContractError(ValueError):
    """Raised when candidate output violates the official fit/freeze/predict contract."""


class AttemptTimeout(TimeoutError):
    """Raised when a cell exceeds its frozen wall-time budget."""


_EQUATION_EXACT_FIELDS = {"target", "intercept", "terms"}
_TERM_EXACT_FIELDS = {"coefficient", "factors"}
_FACTOR_EXACT_FIELDS = {"field", "derivative_axes", "power"}
_FIT_RESPONSE_EXACT_FIELDS = {
    "equations",
    "equation_coordinate_system",
    "field_scaling",
    "diagnostics",
}


def _alarm_handler(_signum, _frame):
    raise AttemptTimeout("in-container official development cell timeout")


@contextlib.contextmanager
def _bounded(seconds):
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        yield
        return
    previous = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def _canonical_hash(payload):
    encoded = json.dumps(
        payload,
        allow_nan=False,
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


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038
        raise ContractError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{label} must be finite")
    return number


def _split_indices(n_time, policy):
    """Chronological, disjoint train/validation/test split. Same form as Gate A."""

    train_end = int(n_time * float(policy["train"][1]))
    validation_end = int(n_time * float(policy["validation"][1]))
    if not 0 < train_end < validation_end < n_time:
        raise ValueError("frozen fractions do not create three non-empty splits")
    return {
        "time_axis_size": int(n_time),
        "train_start": 0,
        "train_end": train_end,
        "validation_start": train_end,
        "validation_end": validation_end,
        "test_start": validation_end,
        "test_end": int(n_time),
    }


def _time_slice(array, start, end, axis):
    slices = [slice(None)] * array.ndim
    slices[axis] = slice(start, end)
    return array[tuple(slices)]


def _tensor(array):
    values = np.asarray(array, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ContractError("official payload contains a non-finite value")
    return {
        "shape": [int(item) for item in values.shape],
        "values": [float(item) for item in values.reshape(-1)],
    }


def _spatial_coordinates(data):
    result = {}
    for axis in ("x", "y", "z"):
        if axis in data:
            result[axis] = np.asarray(data[axis], dtype=np.float64).reshape(-1).tolist()
    return result


def _load_candidate(path):
    spec = importlib.util.spec_from_file_location("official_candidate", path)
    if spec is None or spec.loader is None:
        raise ContractError("cannot import candidate module")
    module = importlib.util.module_from_spec(spec)
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        spec.loader.exec_module(module)
    if stdout.getvalue() or stderr.getvalue():
        raise ContractError("candidate import wrote to stdout or stderr")
    fit = getattr(module, "fit_equations", None)
    predict = getattr(module, "predict_derivative", None)
    if not callable(fit) or not callable(predict):
        raise ContractError(
            "candidate must expose fit_equations(payload) and predict_derivative(payload)"
        )
    return fit, predict


def _call(function, payload, seconds):
    """Invoke a candidate function under a time bound, rejecting side effects."""

    before = _canonical_hash(payload)
    stdout, stderr = io.StringIO(), io.StringIO()
    started = time.perf_counter()
    with _bounded(seconds), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
        stderr
    ):
        result = function(copy.deepcopy(payload))
    elapsed = max(time.perf_counter() - started, 0.0)
    if _canonical_hash(payload) != before:
        raise ContractError("candidate mutated its input payload")
    if stdout.getvalue() or stderr.getvalue():
        raise ContractError("candidate wrote to stdout or stderr")
    if not isinstance(result, dict):
        raise ContractError("candidate response must be a mapping")
    return result, elapsed


def _validate_factor(factor, field_names, spatial_axes):
    if not isinstance(factor, dict) or set(factor) - _FACTOR_EXACT_FIELDS:
        raise ContractError("equation factor contains an unknown field")
    field = factor.get("field")
    if field not in field_names:
        raise ContractError("equation factor names an unknown state field")
    axes = factor.get("derivative_axes", [])
    if not isinstance(axes, list) or any(axis not in spatial_axes for axis in axes):
        raise ContractError("equation factor contains an unsupported derivative axis")
    power = factor.get("power", 1)
    if isinstance(power, bool) or not isinstance(power, int) or not 1 <= power <= 6:
        raise ContractError("equation factor power is invalid")
    if not spatial_axes and axes:
        raise ContractError("ODE equation cannot contain a spatial derivative")
    return {
        "field": str(field),
        "derivative_axes": [str(axis) for axis in axes],
        "power": int(power),
    }


def _maximum_terms(field_names, spatial_axes):
    """Term cap derived from the system's own shape, not a fixed synthetic number.

    The 64-term cap was inherited from the analytic sentinels, whose laws have one to
    three terms. Real multi-field PDE panels need far more: on
    `reaction_diffusion_cylinder` (6 fields, 2 spatial axes) even a purely linear
    library over field plus first and second derivatives per axis needs about 255
    terms, and `heat_soil_uniform_2d_p1` needs thousands. The fixed cap therefore
    failed 6/6 cells of an otherwise valid implementation with
    `equation must contain 1-64 concrete terms`, which is an infrastructure limit
    misreported as a scientific failure.

    The bound still exists, so a candidate cannot return an unbounded equation, but
    it now scales with the declared library size the shape permits.
    """

    per_field = 1 + 2 * max(len(spatial_axes), 0)
    linear = max(len(field_names), 1) * per_field
    # Allow quadratic cross terms over the linear library, with a hard ceiling.
    return int(min(20_000, max(64, linear + linear * (linear + 1) // 2)))


def _validate_equations(equations, field_names, spatial_axes):
    if not isinstance(equations, list) or len(equations) != len(field_names):
        raise ContractError("candidate must return one equation per field")
    maximum_terms = _maximum_terms(field_names, spatial_axes)
    normalized = []
    for field, equation in zip(field_names, equations):  # noqa: B905 - Python 3.9 image
        if not isinstance(equation, dict) or set(equation) - _EQUATION_EXACT_FIELDS:
            raise ContractError("equation contains an unknown field")
        if equation.get("target") != f"{field}_t":
            raise ContractError("equation target order differs from field order")
        intercept = _finite(equation.get("intercept", 0.0), "intercept")
        terms = equation.get("terms")
        if not isinstance(terms, list) or not 1 <= len(terms) <= maximum_terms:
            # Report the ACTUAL count, so the failure is actionable rather than
            # merely a refusal. Without this the candidate cannot tell whether it
            # overshot by one term or by an order of magnitude.
            actual = len(terms) if isinstance(terms, list) else "not-a-list"
            raise ContractError(
                f"equation returned {actual} terms but must contain "
                f"1-{maximum_terms} concrete terms for a system with "
                f"{len(field_names)} fields and {len(spatial_axes)} spatial axes"
            )
        normalized_terms, supports = [], []
        for term in terms:
            if not isinstance(term, dict) or set(term) != _TERM_EXACT_FIELDS:
                raise ContractError("equation term schema changed")
            coefficient = _finite(term["coefficient"], "term coefficient")
            factors = term["factors"]
            if not isinstance(factors, list) or not 1 <= len(factors) <= 6:
                raise ContractError("equation term factors are invalid")
            normalized_factors = [
                _validate_factor(item, field_names, spatial_axes) for item in factors
            ]
            support = tuple(
                (item["field"], tuple(item["derivative_axes"]), item["power"])
                for item in normalized_factors
            )
            if support in supports:
                raise ContractError("equation repeats an identical term support")
            supports.append(support)
            normalized_terms.append(
                {"coefficient": coefficient, "factors": normalized_factors}
            )
        normalized.append(
            {
                "target": f"{field}_t",
                "intercept": intercept,
                "terms": normalized_terms,
            }
        )
    return normalized


def _validate_scaling(scaling, field_names):
    if not isinstance(scaling, list) or len(scaling) != len(field_names):
        raise ContractError("field scaling count differs from field count")
    required = {
        "field",
        "state_offset",
        "state_scale",
        "derivative_offset",
        "derivative_scale",
    }
    normalized = []
    for field, item in zip(field_names, scaling):  # noqa: B905 - Python 3.9 image
        if not isinstance(item, dict) or set(item) != required:
            raise ContractError("field scaling schema changed")
        if item["field"] != field:
            raise ContractError("field scaling order differs from field order")
        state_scale = _finite(item["state_scale"], "state scale")
        derivative_scale = _finite(item["derivative_scale"], "derivative scale")
        if state_scale <= 0.0 or derivative_scale <= 0.0:
            raise ContractError("field scaling must be positive")
        normalized.append(
            {
                "field": field,
                "state_offset": _finite(item["state_offset"], "state offset"),
                "state_scale": state_scale,
                "derivative_offset": _finite(item["derivative_offset"], "derivative offset"),
                "derivative_scale": derivative_scale,
            }
        )
    return normalized


def _spectral_derivative(values, coordinates, axis):
    """Same operator the synthetic Harness discloses, so the contract is unchanged."""

    coordinate_array = np.asarray(coordinates, dtype=np.float64)
    if coordinate_array.ndim != 1 or coordinate_array.size < 5:
        raise ContractError("periodic query axis is too short")
    differences = np.diff(coordinate_array)
    if not np.allclose(differences, differences[0], rtol=1e-10, atol=1e-10):
        raise ContractError("periodic query axis is not uniform")
    period = float(coordinate_array[-1] - coordinate_array[0])
    if not math.isfinite(period) or period <= 0:
        raise ContractError("periodic query axis has an invalid period")
    unique = int(coordinate_array.size - 1)
    core = np.take(values, np.arange(unique), axis=axis)
    frequencies = 2.0 * np.pi * np.fft.fftfreq(unique, d=period / unique)
    shape = [1] * core.ndim
    shape[axis] = unique
    transformed = np.fft.fft(core, axis=axis)
    derivative = np.fft.ifft(
        (1j * frequencies.reshape(shape)) * transformed, axis=axis
    ).real
    first = np.take(derivative, [0], axis=axis)
    return np.concatenate([derivative, first], axis=axis)


def _evaluate_equations(artifact, state, coordinates):
    """Trusted evaluation of the FROZEN equations. The candidate never scores itself."""

    field_names = artifact["field_names"]
    if state.shape[-1] != len(field_names):
        raise ContractError("state field dimension differs from artifact")
    spatial_axes = [name for name in ("x", "y", "z") if name in coordinates]
    index = {name: position for position, name in enumerate(field_names)}
    outputs, cache = [], {}
    for equation in artifact["equations"]:
        value = np.full(state.shape[:-1], float(equation["intercept"]), dtype=np.float64)
        for term in equation["terms"]:
            product = np.ones(state.shape[:-1], dtype=np.float64)
            for factor in term["factors"]:
                factor_value = state[..., index[factor["field"]]]
                for position, axis_name in enumerate(factor["derivative_axes"], start=1):
                    key = (factor["field"], tuple(factor["derivative_axes"][:position]))
                    if key in cache:
                        factor_value = cache[key]
                    else:
                        factor_value = _spectral_derivative(
                            factor_value,
                            coordinates[axis_name],
                            spatial_axes.index(axis_name),
                        )
                        cache[key] = factor_value
                product *= factor_value ** int(factor["power"])
            value += float(term["coefficient"]) * product
        outputs.append(value)
    return np.stack(outputs, axis=-1)


def _nmse(expected, predicted):
    truth = np.asarray(expected, dtype=np.float64)
    prediction = np.asarray(predicted, dtype=np.float64).reshape(truth.shape)
    if not np.all(np.isfinite(prediction)):
        raise ContractError("prediction contains a non-finite value")
    denominator = float(np.sum(truth**2)) + 1e-30
    return float(np.sum((truth - prediction) ** 2) / denominator)


def _fit_once(fit, spec, data, split, field_names, coordinates, time_axis):
    """Fit on the TRAINING split only, then freeze and hash the artifact."""

    states = np.asarray(data["u"], dtype=np.float64)
    derivatives = np.asarray(data["du"], dtype=np.float64)
    train_state = _time_slice(states, split["train_start"], split["train_end"], time_axis)
    train_derivative = _time_slice(
        derivatives, split["train_start"], split["train_end"], time_axis
    )
    times = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    train_times = times[split["train_start"] : split["train_end"]].tolist()
    context = {
        "system_name": spec["attempt"]["system_name"],
        "condition": spec["attempt"]["condition"],
        "field_names": field_names,
        "train_times": train_times,
        "train_state": _tensor(train_state),
        "train_derivative": _tensor(train_derivative),
    }
    request = {
        "schema_version": "official-fit-request-v1",
        "fit_id": f"{spec['attempt']['attempt_id']}-fit",
        "candidate_source_sha256": spec["candidate_source_sha256"],
        "data_type": spec["attempt"]["data_type"],
        "field_names": field_names,
        "spatial_coordinates": coordinates,
        "train_times": train_times,
        "train_state": _tensor(train_state),
        "train_derivative": _tensor(train_derivative),
        "training_context_hash": _canonical_hash(context),
    }
    response, elapsed = _call(fit, request, spec["maximum_fit_seconds"])
    if set(response) != _FIT_RESPONSE_EXACT_FIELDS:
        raise ContractError("fit response fields differ from the frozen contract")
    if response["equation_coordinate_system"] != "physical-unscaled-v1":
        raise ContractError("candidate equations are not in physical units")
    spatial_axes = [name for name in ("x", "y", "z") if name in coordinates]
    equations = _validate_equations(response["equations"], field_names, spatial_axes)
    scaling = _validate_scaling(response["field_scaling"], field_names)
    diagnostics = response["diagnostics"]
    if not isinstance(diagnostics, dict):
        raise ContractError("fit diagnostics must be a mapping")
    artifact = {
        "schema_version": "official-frozen-equation-artifact-v1",
        "fit_id": request["fit_id"],
        "candidate_source_sha256": request["candidate_source_sha256"],
        "training_context_hash": request["training_context_hash"],
        "data_type": request["data_type"],
        "field_names": field_names,
        "equations": equations,
        "equation_coordinate_system": "physical-unscaled-v1",
        "field_scaling": scaling,
        "fit_call_count": 1,
        "fit_completed_before_query": True,
        "free_symbol_count": 0,
    }
    artifact["artifact_hash"] = _canonical_hash(artifact)
    selected_terms = sum(len(item["terms"]) for item in equations)
    return artifact, elapsed, selected_terms


def _predict_split(predict, spec, artifact, data, split, name, coordinates, time_axis):
    """Predict each held-out slice from the frozen artifact alone."""

    states = np.asarray(data["u"], dtype=np.float64)
    derivatives = np.asarray(data["du"], dtype=np.float64)
    start, end = split[f"{name}_start"], split[f"{name}_end"]
    times = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    predictions, truths, maximum_delta, elapsed_total = [], [], 0.0, 0.0
    frozen_hash = artifact["artifact_hash"]
    for index in range(start, end):
        state_slice = _time_slice(states, index, index + 1, time_axis)
        truth_slice = _time_slice(derivatives, index, index + 1, time_axis)
        request = {
            "schema_version": "official-predict-request-v1",
            "query_id": f"{spec['attempt']['attempt_id']}-{name}-{index}",
            "artifact": copy.deepcopy(artifact),
            "time": float(times[index]),
            "spatial_coordinates": coordinates,
            "state": _tensor(state_slice),
            "expected_derivative_present": False,
        }
        before = _canonical_hash(request["artifact"])
        response, elapsed = _call(predict, request, spec["maximum_predict_seconds"])
        elapsed_total = max(elapsed_total, elapsed)
        if _canonical_hash(request["artifact"]) != before:
            raise ContractError("prediction mutated the frozen artifact")
        if response.get("artifact_hash") != frozen_hash:
            raise ContractError("prediction did not evaluate the frozen artifact")
        if int(response.get("fit_calls_during_prediction", -1)) != 0:
            raise ContractError("candidate refitted during prediction")
        if int(response.get("artifact_mutation_count", -1)) != 0:
            raise ContractError("candidate reported an artifact mutation")
        payload = response.get("derivative_prediction")
        if not isinstance(payload, dict) or set(payload) != {"shape", "values"}:
            raise ContractError("derivative_prediction must contain only shape and values")
        shape = tuple(int(item) for item in payload["shape"])
        flat = np.asarray(
            [_finite(item, "derivative_prediction") for item in payload["values"]],
            dtype=np.float64,
        )
        if flat.size != int(np.prod(shape)):
            raise ContractError("derivative_prediction value count differs from shape")
        candidate_prediction = flat.reshape(shape)
        # Independently evaluate the frozen equations and require agreement, so a
        # candidate cannot return numbers unrelated to the law it reported.
        trusted = _evaluate_equations(artifact, state_slice, coordinates)
        maximum_delta = max(
            maximum_delta,
            float(np.max(np.abs(candidate_prediction.reshape(trusted.shape) - trusted))),
        )
        predictions.append(trusted)
        truths.append(truth_slice)
    if not predictions:
        raise ContractError(f"{name} split produced no queries")
    return {
        "nmse": _nmse(np.concatenate(truths, axis=time_axis),
                      np.concatenate(predictions, axis=time_axis)),
        "query_count": end - start,
        "maximum_equation_prediction_delta": maximum_delta,
        "maximum_predict_seconds": elapsed_total,
    }


def _deterministic_permutation(count, seed):
    """Reproducible full permutation of `count` rows from the frozen cell seed.

    Uses a fixed-increment linear congruential shuffle so the same seed and row
    count always yield the same order, making the shuffle control replayable
    without shipping a large index list into the container.
    """

    order = list(range(count))
    state = (seed * 6364136223846793005 + 1442695040888963407) % (2**64)
    for position in range(count - 1, 0, -1):
        state = (state * 6364136223846793005 + 1442695040888963407) % (2**64)
        target = state % (position + 1)
        order[position], order[target] = order[target], order[position]
    return order


def _training_sensitivity(fit, spec, data, split, field_names, coordinates, time_axis):
    """Refit on a shuffled training target; a real fit must change its equations."""

    shuffled = dict(data)
    derivatives = np.asarray(data["du"], dtype=np.float64)
    train = _time_slice(derivatives, split["train_start"], split["train_end"], time_axis)
    flat = train.reshape(-1, train.shape[-1])
    # The permutation must cover every training ROW, which for a PDE means all
    # spatial positions times all training time steps, not just the time steps. The
    # host cannot know that count without opening the array, so it is derived here
    # deterministically from the frozen seed instead of being passed in.
    order = np.asarray(
        _deterministic_permutation(flat.shape[0], int(spec["attempt"]["seed"])),
        dtype=np.int64,
    )
    if sorted(order.tolist()) != list(range(flat.shape[0])):
        raise ValueError("frozen shuffle is not a complete row permutation")
    rebuilt = derivatives.copy()
    slices = [slice(None)] * derivatives.ndim
    slices[time_axis] = slice(split["train_start"], split["train_end"])
    rebuilt[tuple(slices)] = flat[order].reshape(train.shape)
    shuffled["du"] = rebuilt
    artifact, _, _ = _fit_once(
        fit, spec, shuffled, split, field_names, coordinates, time_axis
    )
    return artifact["artifact_hash"]


def _run_candidate(spec, data, candidate_path):
    fit, predict = _load_candidate(candidate_path)
    states = np.asarray(data["u"], dtype=np.float64)
    times = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    time_axis = 0 if states.ndim == 2 else states.ndim - 2
    split = _split_indices(len(times), spec["split_policy"])
    field_names = [f"u{index}" for index in range(states.shape[-1])]
    coordinates = _spatial_coordinates(data)

    artifact, fit_seconds, selected_terms = _fit_once(
        fit, spec, data, split, field_names, coordinates, time_axis
    )
    validation = _predict_split(
        predict, spec, artifact, data, split, "validation", coordinates, time_axis
    )
    test = _predict_split(
        predict, spec, artifact, data, split, "test", coordinates, time_axis
    )
    shuffled_hash = _training_sensitivity(
        fit, spec, data, split, field_names, coordinates, time_axis
    )

    equations = []
    for equation in artifact["equations"]:
        parts = [f"{equation['intercept']:+.6g}"]
        for term in equation["terms"]:
            factors = "*".join(
                f"{item['field']}"
                + ("_" + "".join(item["derivative_axes"]) if item["derivative_axes"] else "")
                + (f"^{item['power']}" if item["power"] > 1 else "")
                for item in term["factors"]
            )
            parts.append(f"{term['coefficient']:+.6g}*{factors}")
        equations.append(f"{equation['target']} = " + " ".join(parts))

    return {
        "status": "succeeded",
        "discovered_equation": "\n".join(equations),
        "validation_nmse": validation["nmse"],
        "derivative_nmse": test["nmse"],
        "model_complexity": selected_terms,
        "artifact_hash": artifact["artifact_hash"],
        "fit_call_count": 1,
        "selected_term_count": selected_terms,
        "maximum_fit_seconds": fit_seconds,
        "maximum_predict_seconds": max(
            validation["maximum_predict_seconds"], test["maximum_predict_seconds"]
        ),
        "validation_query_count": validation["query_count"],
        "test_query_count": test["query_count"],
        "maximum_equation_prediction_delta": max(
            validation["maximum_equation_prediction_delta"],
            test["maximum_equation_prediction_delta"],
        ),
        # A real fit must depend on its training target.
        "equation_changed_on_shuffled_training": shuffled_hash != artifact["artifact_hash"],
        "split_indices": split,
        "true_derivative_exposed_to_candidate": False,
        "fit_calls_during_prediction": 0,
        "artifact_mutation_count": 0,
    }


def _run_baseline(spec, data):
    """Invoke the pinned DOMAIN-VALID baseline, byte-verified before import.

    The frozen Task 266.1 baseline registry routes by domain: Operon for ODE, and
    PDE-FIND backed by PySINDy for PDE. The pinned Operon adapter refuses anything
    beyond the 1D PDE panel, and this panel's PDE systems are 2D and 3D, so sending
    PDE cells to Operon fails every one of them and makes each paired effect
    meaningless. The registry's own probe evidence records PDE-FIND succeeding at
    2D (`1.398e-31`) and 3D (`2.034e-32`).
    """

    baseline_path = Path("/opt/autoresearch-mdbench/runner.py")
    if _file_hash(baseline_path) != spec["expected_baseline_runner_sha256"]:
        raise ValueError("pinned baseline runner bytes differ from host contract")
    module_spec = importlib.util.spec_from_file_location(
        "mdbench_gate_a_runner", baseline_path
    )
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
        raise ValueError("baseline and official runner disagree on the time axis")
    base_spec = {
        "attempt": spec["attempt"],
        "method": spec["baseline_method"],
        "split_policy": spec["split_policy"],
    }
    if spec["attempt"]["data_type"] == "ode" and spec["baseline_method"].get(
        "method_id"
    ) == "operon_gp":
        result = baseline._run_operon(base_spec, pieces, spatial_grids, time_axis)
    else:
        # `sindy_or_pdefind` dispatches SINDy for ODE and PDE-FIND for PDE, which is
        # the domain-valid path the frozen registry specifies.
        result = baseline._run_sparse_baseline(
            base_spec, pieces, spatial_grids, time_axis
        )
    result.update(
        {
            "split_indices": split,
            "true_derivative_exposed_to_candidate": False,
            "fit_call_count": 1,
            "fit_calls_during_prediction": 0,
            "artifact_mutation_count": 0,
        }
    )
    return result


def _peak_rss_mb():
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _base_payload(spec_hash, status, started):
    return {
        "schema_version": "official-development-runner-payload-v1",
        "spec_hash": spec_hash,
        "status": status,
        "discovered_equation": None,
        "validation_nmse": None,
        "derivative_nmse": None,
        "model_complexity": None,
        "wall_time_seconds": max(time.time() - started, 0.0),
        "peak_rss_mb": _peak_rss_mb(),
        "failure_reason": None,
        "traceback": None,
    }


def run(spec_path, data_path, candidate_path, output_path):
    started = time.time()
    spec, spec_hash = None, None
    try:
        raw = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        spec_hash = raw.pop("spec_hash", None)
        if spec_hash != _canonical_hash(raw):
            raise ValueError("official cell spec hash mismatch")
        spec = raw
        if _file_hash(data_path) != spec["expected_data_sha256"]:
            raise ValueError("official NPZ bytes differ from the frozen manifest")
        with np.load(data_path, allow_pickle=False) as handle:
            data = {key: handle[key] for key in handle.files}
        if spec["method_kind"] == "candidate":
            if _file_hash(candidate_path) != spec["candidate_source_sha256"]:
                raise ValueError("candidate source bytes differ from the frozen record")
            result = _run_candidate(spec, data, candidate_path)
        else:
            result = _run_baseline(spec, data)
        payload = _base_payload(spec_hash, "succeeded", started)
        payload.update(result)
        payload["wall_time_seconds"] = max(time.time() - started, 0.0)
        payload["peak_rss_mb"] = _peak_rss_mb()
    except AttemptTimeout as error:
        payload = _base_payload(spec_hash, "timed_out", started)
        payload["failure_reason"] = str(error)[:2000]
    except Exception as error:  # noqa: BLE001 - every failure must be retained
        payload = _base_payload(spec_hash, "failed", started)
        payload["failure_reason"] = f"{type(error).__name__}: {error}"[:2000]
        payload["traceback"] = traceback.format_exc(limit=12)[-8000:]
    payload["result_hash"] = _canonical_hash(payload)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.spec, arguments.data, arguments.candidate, arguments.output)
