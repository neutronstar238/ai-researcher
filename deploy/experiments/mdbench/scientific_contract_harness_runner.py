#!/usr/bin/env python3
"""Offline fit/freeze/predict Harness runner for Task 266.2.

The runner receives only corrected synthetic sentinels on stdin, imports exact
model-authored source from a read-only mount, and independently validates
equations, coefficients, predictions, controls, shapes, and call ordering.  No
official MDBench or confirmation artifact is mounted.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np


class ContractError(ValueError):
    """Raised when candidate output violates the frozen scientific contract."""


class CallTimeout(TimeoutError):
    """Raised when a fit or prediction exceeds its frozen wall-time limit."""


_EXPECTED_SENTINEL_IDS = {
    "ode-linear-2field",
    "pde-advection-1d",
    "pde-diffusion-1d",
    "pde-advection-diffusion-2d",
    "pde-heat-3d",
    "pde-diffusion-1d-2field",
}
_EXPECTED_GATE = {
    "artifact_hash_must_change_on_alternative_training": True,
    "clean_coefficient_relative_error_maximum": 0.05,
    "clean_prediction_nmse_maximum": 1e-6,
    "concrete_numeric_equations_required": True,
    "equation_prediction_max_abs_delta": 1e-9,
    "fit_call_count": 1,
    "fit_calls_during_prediction": 0,
    "free_symbol_count_maximum": 0,
    "maximum_fit_seconds_per_sentinel": 20,
    "maximum_memory_mb": 512,
    "maximum_predict_seconds_per_query": 2,
    "minimum_queries_per_fit": 3,
    "network_default_deny": True,
    "official_development_results_allowed": 0,
    "query_contains_target_derivative": False,
    "query_time_slices": 1,
    "required_capabilities": [
        "ode",
        "pde_1d_advection",
        "pde_1d_diffusion",
        "pde_2d",
        "pde_3d",
        "pde_multi_field",
    ],
    "shuffled_nmse_ratio_minimum": 5.0,
    "term_support_f1_minimum": 1.0,
    "zero_null_relative_improvement_minimum": 0.5,
}


def _alarm_handler(_signum, _frame):
    raise CallTimeout("candidate call exceeded its frozen wall-time limit")


@contextlib.contextmanager
def _bounded_call(seconds):
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


def _validate_hex_digest(value, label):
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError(f"{label} is not a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ContractError(f"{label} is not a SHA-256 digest") from exc


def _validate_harness_input(payload):
    required = {
        "schema_version",
        "expected_runner_sha256",
        "candidate_source_sha256",
        "plan_hash",
        "erratum_hash",
        "corrected_sentinel_registry_hash",
        "contract_gate",
        "fixtures",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ContractError("scientific Harness input fields changed")
    if payload["schema_version"] != "scientific-contract-harness-input-v1":
        raise ContractError("scientific Harness input schema changed")
    for field in (
        "expected_runner_sha256",
        "candidate_source_sha256",
        "plan_hash",
        "erratum_hash",
        "corrected_sentinel_registry_hash",
    ):
        _validate_hex_digest(payload[field], field)
    if payload["contract_gate"] != _EXPECTED_GATE:
        raise ContractError("scientific-contract gate changed")
    fixtures = payload["fixtures"]
    if not isinstance(fixtures, list) or len(fixtures) != len(_EXPECTED_SENTINEL_IDS):
        raise ContractError("scientific Harness requires six corrected fixtures")
    sentinel_ids = {item.get("sentinel_id") for item in fixtures if isinstance(item, dict)}
    if sentinel_ids != _EXPECTED_SENTINEL_IDS:
        raise ContractError("scientific Harness sentinel coverage changed")
    for fixture in fixtures:
        if not isinstance(fixture, dict) or "fixture_hash" not in fixture:
            raise ContractError("scientific Harness fixture schema changed")
        expected_hash = _canonical_hash(
            {key: value for key, value in fixture.items() if key != "fixture_hash"}
        )
        if fixture["fixture_hash"] != expected_hash:
            raise ContractError("scientific Harness fixture hash changed")
        fixture_thresholds = {
            "coefficient_relative_error_maximum": 0.05,
            "equation_prediction_max_abs_delta": 1e-9,
            "minimum_query_count": 3,
            "prediction_nmse_maximum": 1e-6,
            "shuffled_nmse_ratio_minimum": 5.0,
            "term_support_f1_minimum": 1.0,
            "zero_null_relative_improvement_minimum": 0.5,
        }
        for field, expected in fixture_thresholds.items():
            if fixture.get(field) != expected:
                raise ContractError(f"scientific Harness fixture threshold changed: {field}")


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _finite_number(value, label, *, minimum=None, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038
        raise ContractError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise ContractError(f"{label} is below its minimum")
    if strictly_positive and number <= 0:
        raise ContractError(f"{label} must be positive")
    return number


def _json_metric(value):
    """Return a JSON number or null while preserving fail-closed metric evidence."""

    number = float(value)
    return number if math.isfinite(number) else None


def _positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{label} must be an integer")
    if value < 1:
        raise ContractError(f"{label} must be positive")
    return int(value)


def _load_module(path, module_name):
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise ContractError("cannot create exact candidate import specification")
    module = importlib.util.module_from_spec(specification)
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with (
        contextlib.redirect_stdout(captured_stdout),
        contextlib.redirect_stderr(captured_stderr),
    ):
        specification.loader.exec_module(module)
    if captured_stdout.getvalue() or captured_stderr.getvalue():
        raise ContractError("candidate import wrote to stdout or stderr")
    fit = getattr(module, "fit_equations", None)
    predict = getattr(module, "predict_derivative", None)
    if not callable(fit) or not callable(predict):
        raise ContractError(
            "candidate must expose fit_equations(payload) and predict_derivative(payload)"
        )
    return module, fit, predict


def _call_candidate(function, payload, seconds):
    before = _canonical_hash(payload)
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    started = time.perf_counter()
    with (
        _bounded_call(seconds),
        contextlib.redirect_stdout(captured_stdout),
        contextlib.redirect_stderr(captured_stderr),
    ):
        result = function(copy.deepcopy(payload))
    elapsed = max(time.perf_counter() - started, 0.0)
    if _canonical_hash(payload) != before:
        raise ContractError("candidate mutated its input payload")
    if captured_stdout.getvalue() or captured_stderr.getvalue():
        raise ContractError("candidate wrote to stdout or stderr")
    if not isinstance(result, dict):
        raise ContractError("candidate response must be a mapping")
    return result, elapsed


def _candidate_error_location(error, candidate_path):
    """Return only candidate-owned stack locations, without locals or fixture values."""

    candidate_resolved = candidate_path.resolve()
    locations = []
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            frame_path = Path(frame.filename).resolve()
        except OSError:
            continue
        if frame_path != candidate_resolved:
            continue
        source_line = (frame.line or "<source unavailable>").strip()
        locations.append(
            f"candidate.py:{frame.lineno} in {frame.name}: {source_line[:500]}"
        )
    return " <- ".join(locations[-4:]) or None


def _invoke_candidate_process(candidate_path, function_name, payload, seconds):
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--candidate",
                str(candidate_path),
                "--worker-function",
                function_name,
                "--worker-timeout-seconds",
                str(float(seconds)),
            ],
            input=json.dumps(payload, allow_nan=False, sort_keys=True),
            capture_output=True,
            text=True,
            check=False,
            timeout=float(seconds) + 5.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise CallTimeout(
            f"candidate {function_name} process exceeded its frozen wall-time limit"
        ) from exc
    if completed.stderr:
        raise ContractError("candidate worker wrote to stderr")
    if len(completed.stdout.encode("utf-8")) > 16 * 1024 * 1024:
        raise ContractError("candidate worker response exceeded 16 MiB")
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("candidate worker did not return one JSON envelope") from exc
    if completed.returncode != 0 or not isinstance(envelope, dict):
        raise ContractError("candidate worker process failed")
    if set(envelope) != {
        "candidate_error_location",
        "elapsed_seconds",
        "error_message",
        "error_type",
        "ok",
        "response",
    }:
        raise ContractError("candidate worker envelope schema changed")
    if envelope["ok"] is not True:
        location = envelope["candidate_error_location"]
        location_suffix = f" | candidate_location={location}" if location else ""
        raise ContractError(
            f"candidate {function_name} failed: "
            f"{envelope['error_type']}: {envelope['error_message']}"
            f"{location_suffix}"
        )
    if (
        envelope["error_type"] is not None
        or envelope["error_message"] is not None
        or envelope["candidate_error_location"] is not None
    ):
        raise ContractError("successful candidate worker retained error fields")
    if not isinstance(envelope["response"], dict):
        raise ContractError("candidate worker response must be a mapping")
    elapsed = _finite_number(
        envelope["elapsed_seconds"],
        "candidate worker elapsed seconds",
        minimum=0.0,
    )
    if elapsed > float(seconds):
        raise CallTimeout(
            f"candidate {function_name} exceeded its frozen function-time limit"
        )
    return envelope["response"], elapsed


def _spectral_derivative(values, coordinates, axis, order):
    coordinate_array = np.asarray(coordinates, dtype=np.float64)
    if coordinate_array.ndim != 1 or coordinate_array.size < 5:
        raise ContractError("periodic query axis is too short")
    differences = np.diff(coordinate_array)
    if not np.allclose(differences, differences[0], rtol=1e-12, atol=1e-12):
        raise ContractError("periodic query axis is not uniform")
    period = float(coordinate_array[-1] - coordinate_array[0])
    if not math.isfinite(period) or period <= 0:
        raise ContractError("periodic query axis has an invalid period")
    unique_size = int(coordinate_array.size - 1)
    core = np.take(values, np.arange(unique_size), axis=axis)
    frequencies = 2.0 * np.pi * np.fft.fftfreq(
        unique_size,
        d=period / unique_size,
    )
    frequency_shape = [1] * core.ndim
    frequency_shape[axis] = unique_size
    multiplier = (1j * frequencies.reshape(frequency_shape)) ** int(order)
    transformed = np.fft.fft(core, axis=axis)
    derivative_core = np.fft.ifft(multiplier * transformed, axis=axis).real
    first = np.take(derivative_core, [0], axis=axis)
    return np.concatenate([derivative_core, first], axis=axis)


def _tensor_array(payload, label):
    if not isinstance(payload, dict) or set(payload) != {"shape", "values"}:
        raise ContractError(f"{label} must contain only shape and values")
    shape = payload["shape"]
    values = payload["values"]
    if not isinstance(shape, list) or not shape:
        raise ContractError(f"{label}.shape must be a non-empty list")
    normalized_shape = tuple(_positive_integer(item, f"{label}.shape") for item in shape)
    if not isinstance(values, list) or len(values) != int(np.prod(normalized_shape)):
        raise ContractError(f"{label} value count differs from shape")
    normalized = np.asarray(
        [_finite_number(item, f"{label}.values") for item in values],
        dtype=np.float64,
    )
    return normalized.reshape(normalized_shape)


def _tensor_payload(values):
    array = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise ContractError("trusted evaluator produced a non-finite tensor")
    return {
        "shape": [int(item) for item in array.shape],
        "values": [float(item) for item in array.reshape(-1)],
    }


def _validate_factor(factor, field_names, spatial_axes):
    if not isinstance(factor, dict):
        raise ContractError("equation factor must be a mapping")
    if set(factor) - {"field", "derivative_axes", "power"}:
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


def _validate_equations(equations, field_names, spatial_axes):
    if not isinstance(equations, list) or len(equations) != len(field_names):
        raise ContractError("candidate must return one equation per field")
    normalized_equations = []
    for field, equation in zip(  # noqa: B905 - pinned image is Python 3.9
        field_names,
        equations,
    ):
        if not isinstance(equation, dict):
            raise ContractError("equation must be a mapping")
        if set(equation) - {"target", "intercept", "terms"}:
            raise ContractError("equation contains an unknown field")
        if equation.get("target") != f"{field}_t":
            raise ContractError("equation target order differs from field order")
        intercept = _finite_number(equation.get("intercept", 0.0), "intercept")
        terms = equation.get("terms")
        if not isinstance(terms, list) or not 1 <= len(terms) <= 64:
            raise ContractError("equation must contain 1-64 concrete terms")
        normalized_terms = []
        supports = []
        for term in terms:
            if not isinstance(term, dict) or set(term) != {"coefficient", "factors"}:
                raise ContractError("equation term schema changed")
            coefficient = _finite_number(term["coefficient"], "term coefficient")
            factors = term["factors"]
            if not isinstance(factors, list) or not 1 <= len(factors) <= 6:
                raise ContractError("equation term factors are invalid")
            normalized_factors = [
                _validate_factor(item, field_names, spatial_axes) for item in factors
            ]
            support = tuple(
                (
                    item["field"],
                    tuple(item["derivative_axes"]),
                    item["power"],
                )
                for item in normalized_factors
            )
            if support in supports:
                raise ContractError("equation repeats an identical term support")
            supports.append(support)
            normalized_terms.append(
                {"coefficient": coefficient, "factors": normalized_factors}
            )
        normalized_equations.append(
            {
                "target": f"{field}_t",
                "intercept": intercept,
                "terms": normalized_terms,
            }
        )
    return normalized_equations


def _validate_scaling(scaling, field_names):
    if not isinstance(scaling, list) or len(scaling) != len(field_names):
        raise ContractError("field scaling count differs from field count")
    normalized = []
    required = {
        "field",
        "state_offset",
        "state_scale",
        "derivative_offset",
        "derivative_scale",
    }
    for field, item in zip(  # noqa: B905 - pinned image is Python 3.9
        field_names,
        scaling,
    ):
        if not isinstance(item, dict) or set(item) != required:
            raise ContractError("field scaling schema changed")
        if item["field"] != field:
            raise ContractError("field scaling order differs from field order")
        normalized.append(
            {
                "field": field,
                "state_offset": _finite_number(item["state_offset"], "state offset"),
                "state_scale": _finite_number(
                    item["state_scale"],
                    "state scale",
                    strictly_positive=True,
                ),
                "derivative_offset": _finite_number(
                    item["derivative_offset"],
                    "derivative offset",
                ),
                "derivative_scale": _finite_number(
                    item["derivative_scale"],
                    "derivative scale",
                    strictly_positive=True,
                ),
            }
        )
    return normalized


def _trusted_equation_prediction(artifact, state_payload, coordinates):
    state = _tensor_array(state_payload, "state")
    field_names = artifact["field_names"]
    if state.shape[-1] != len(field_names):
        raise ContractError("state field dimension differs from artifact")
    spatial_axes = [name for name in ("x", "y", "z") if name in coordinates]
    if state.ndim != len(spatial_axes) + 2:
        raise ContractError("state rank differs from spatial axes plus time and field")
    field_index = {name: index for index, name in enumerate(field_names)}
    outputs = []
    derivative_cache = {}
    for equation in artifact["equations"]:
        value = np.full(state.shape[:-1], float(equation["intercept"]), dtype=np.float64)
        for term in equation["terms"]:
            term_value = np.ones(state.shape[:-1], dtype=np.float64)
            for factor in term["factors"]:
                factor_value = state[..., field_index[factor["field"]]]
                for axis_position, axis_name in enumerate(
                    factor["derivative_axes"],
                    start=1,
                ):
                    cache_key = (
                        factor["field"],
                        tuple(factor["derivative_axes"][:axis_position]),
                    )
                    if cache_key in derivative_cache:
                        factor_value = derivative_cache[cache_key]
                    else:
                        factor_value = _spectral_derivative(
                            factor_value,
                            coordinates[axis_name],
                            spatial_axes.index(axis_name),
                            1,
                        )
                        derivative_cache[cache_key] = factor_value
                term_value *= factor_value ** int(factor["power"])
            value += float(term["coefficient"]) * term_value
        outputs.append(value)
    return np.stack(outputs, axis=-1)


def _equation_support(equation):
    result = []
    if float(equation.get("intercept", 0.0)) != 0.0:
        result.append(("intercept",))
    for term in equation["terms"]:
        result.append(
            tuple(
                (
                    factor["field"],
                    tuple(factor.get("derivative_axes", [])),
                    int(factor.get("power", 1)),
                )
                for factor in term["factors"]
            )
        )
    return tuple(result)


def _equation_coefficients(equation):
    result = []
    if float(equation.get("intercept", 0.0)) != 0.0:
        result.append(float(equation["intercept"]))
    result.extend(float(term["coefficient"]) for term in equation["terms"])
    return tuple(result)


def _equation_recovery(observed, expected):
    true_positive = 0
    observed_count = 0
    expected_count = 0
    coefficient_errors = []
    for observed_equation, expected_equation in zip(  # noqa: B905 - Python 3.9
        observed,
        expected,
    ):
        observed_support = _equation_support(observed_equation)
        expected_support = _equation_support(expected_equation)
        observed_coefficients = _equation_coefficients(observed_equation)
        expected_coefficients = _equation_coefficients(expected_equation)
        observed_map = dict(zip(observed_support, observed_coefficients))  # noqa: B905
        expected_map = dict(zip(expected_support, expected_coefficients))  # noqa: B905
        true_positive += len(set(observed_support) & set(expected_support))
        observed_count += len(observed_support)
        expected_count += len(expected_support)
        for support, expected_coefficient in expected_map.items():
            if support not in observed_map:
                coefficient_errors.append(float("inf"))
            else:
                coefficient_errors.append(
                    abs(observed_map[support] - expected_coefficient)
                    / max(abs(expected_coefficient), 1e-12)
                )
    precision = true_positive / observed_count if observed_count else 0.0
    recall = true_positive / expected_count if expected_count else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return float(f1), float(max(coefficient_errors, default=0.0))


def _nmse(expected, observed):
    expected_array = np.asarray(expected, dtype=np.float64).reshape(-1)
    observed_array = np.asarray(observed, dtype=np.float64).reshape(-1)
    if expected_array.shape != observed_array.shape or not np.all(np.isfinite(observed_array)):
        raise ContractError("prediction is non-finite or shape-incompatible")
    numerator = float(np.sum((expected_array - observed_array) ** 2))
    denominator = float(np.sum(expected_array**2)) + 1e-30
    result = numerator / denominator
    if not math.isfinite(result):
        raise ContractError("prediction NMSE is non-finite")
    return result


def _fit_request(fixture, variant, state_payload, derivative_payload, source_sha256):
    context = {
        "sentinel_id": fixture["sentinel_id"],
        "variant": variant,
        "field_names": fixture["field_names"],
        "spatial_coordinates": fixture["spatial_coordinates"],
        "train_times": fixture["train_times"],
        "train_state": state_payload,
        "train_derivative": derivative_payload,
    }
    request = {
        "schema_version": "scientific-fit-request-v1",
        "fit_id": f'{fixture["sentinel_id"]}-{variant}-fit',
        "candidate_source_sha256": source_sha256,
        "sentinel_id": fixture["sentinel_id"],
        "data_type": fixture["data_type"],
        "field_names": fixture["field_names"],
        "spatial_coordinates": fixture["spatial_coordinates"],
        "train_times": fixture["train_times"],
        "train_state": state_payload,
        "train_derivative": derivative_payload,
        "training_context_hash": _canonical_hash(context),
    }
    return request


def _normalize_fit_result(fixture, request, response, elapsed, expected_training_derivative):
    if set(response) != {
        "equations",
        "equation_coordinate_system",
        "field_scaling",
        "diagnostics",
    }:
        raise ContractError("fit response fields differ from the frozen artifact draft")
    if response["equation_coordinate_system"] != "physical-unscaled-v1":
        raise ContractError("candidate equations are not in physical units")
    field_names = [str(item) for item in fixture["field_names"]]
    spatial_axes = [
        name for name in ("x", "y", "z") if name in fixture["spatial_coordinates"]
    ]
    equations = _validate_equations(response["equations"], field_names, spatial_axes)
    scaling = _validate_scaling(response["field_scaling"], field_names)
    diagnostics = response["diagnostics"]
    if not isinstance(diagnostics, dict) or set(diagnostics) != {
        "solver_id",
        "design_feature_count",
        "warnings",
    }:
        raise ContractError("fit diagnostic draft schema changed")
    solver_id = diagnostics["solver_id"]
    if not isinstance(solver_id, str) or not 1 <= len(solver_id) <= 128:
        raise ContractError("solver_id is invalid")
    design_feature_count = _positive_integer(
        diagnostics["design_feature_count"],
        "design feature count",
    )
    warnings = diagnostics["warnings"]
    if (
        not isinstance(warnings, list)
        or len(warnings) > 32
        or any(not isinstance(item, str) for item in warnings)
    ):
        raise ContractError("fit warnings are invalid")
    artifact = {
        "schema_version": "frozen-equation-artifact-v1",
        "fit_id": request["fit_id"],
        "candidate_source_sha256": request["candidate_source_sha256"],
        "training_context_hash": request["training_context_hash"],
        "data_type": request["data_type"],
        "field_names": field_names,
        "equations": equations,
        "equation_coordinate_system": "physical-unscaled-v1",
        "field_scaling": scaling,
        "diagnostics": {},
        "fit_call_count": 1,
        "fit_completed_before_query": True,
        "free_symbol_count": 0,
    }
    trusted_training = _trusted_equation_prediction(
        artifact,
        request["train_state"],
        request["spatial_coordinates"],
    )
    expected_training = _tensor_array(
        expected_training_derivative,
        "expected training derivative",
    )
    training_nmse = _nmse(expected_training, trusted_training)
    selected_term_count = sum(len(item["terms"]) for item in equations)
    training_sample_count = int(np.prod(expected_training.shape[:-1]))
    artifact["diagnostics"] = {
        "solver_id": solver_id,
        "training_sample_count": training_sample_count,
        "design_feature_count": design_feature_count,
        "selected_term_count": selected_term_count,
        "training_nmse": float(training_nmse),
        "fit_wall_seconds": float(elapsed),
        "warnings": warnings,
    }
    artifact["artifact_hash"] = _canonical_hash(artifact)
    return artifact


def _shuffle_derivative(fixture):
    derivative = _tensor_array(fixture["train_derivative"], "train derivative")
    field_count = derivative.shape[-1]
    rows = derivative.reshape(-1, field_count)
    order = fixture["train_derivative_shuffle_order"]
    if sorted(order) != list(range(rows.shape[0])):
        raise ContractError("frozen shuffle is not a complete row permutation")
    return _tensor_payload(rows[np.asarray(order, dtype=np.int64)].reshape(derivative.shape))


def _predict_queries(candidate_path, artifact, fixture, predict_limit):
    predictions = []
    trusted_predictions = []
    expected_values = []
    elapsed_values = []
    maximum_delta = 0.0
    for query in fixture["queries"]:
        request = {
            "schema_version": "scientific-predict-request-v1",
            "query_id": query["query_id"],
            "artifact": copy.deepcopy(artifact),
            "time": query["time"],
            "spatial_coordinates": fixture["spatial_coordinates"],
            "state": query["state"],
            "expected_derivative_present": False,
        }
        artifact_before = _canonical_hash(request["artifact"])
        response, elapsed = _invoke_candidate_process(
            candidate_path,
            "predict",
            request,
            predict_limit,
        )
        if _canonical_hash(request["artifact"]) != artifact_before:
            raise ContractError("prediction mutated the frozen artifact")
        required_response = {
            "schema_version",
            "query_id",
            "artifact_hash",
            "derivative_prediction",
            "fit_calls_during_prediction",
            "artifact_mutation_count",
            "equation_evaluator_id",
        }
        if set(response) != required_response:
            raise ContractError("predict response fields differ from the frozen schema")
        if response["schema_version"] != "scientific-predict-response-v1":
            raise ContractError("predict response schema version changed")
        if response["query_id"] != query["query_id"]:
            raise ContractError("predict response query ID changed")
        if response["artifact_hash"] != artifact["artifact_hash"]:
            raise ContractError("predict response artifact hash changed")
        if response["fit_calls_during_prediction"] != 0:
            raise ContractError("predict response reports a fit-after-query call")
        if response["artifact_mutation_count"] != 0:
            raise ContractError("predict response reports artifact mutation")
        if response["equation_evaluator_id"] != "trusted-equation-evaluator-v1":
            raise ContractError("predict response evaluator ID changed")
        candidate_prediction = _tensor_array(
            response["derivative_prediction"],
            "candidate derivative prediction",
        )
        query_state = _tensor_array(query["state"], "query state")
        if candidate_prediction.shape != query_state.shape:
            raise ContractError("candidate prediction shape differs from query state")
        trusted = _trusted_equation_prediction(
            artifact,
            query["state"],
            fixture["spatial_coordinates"],
        )
        delta = float(np.max(np.abs(candidate_prediction - trusted)))
        if not math.isfinite(delta):
            raise ContractError("equation-prediction delta is non-finite")
        maximum_delta = max(maximum_delta, delta)
        predictions.extend(float(item) for item in candidate_prediction.reshape(-1))
        trusted_predictions.extend(float(item) for item in trusted.reshape(-1))
        expected = _tensor_array(query["expected_derivative"], "expected derivative")
        expected_values.extend(float(item) for item in expected.reshape(-1))
        elapsed_values.append(float(elapsed))
    return {
        "prediction_values": predictions,
        "trusted_prediction_values": trusted_predictions,
        "expected_values": expected_values,
        "maximum_equation_prediction_delta": maximum_delta,
        "maximum_predict_seconds": max(elapsed_values, default=0.0),
        "query_count": len(elapsed_values),
    }


def _fit_variant(candidate_path, source_sha256, fixture, variant, state, derivative, fit_limit):
    request = _fit_request(fixture, variant, state, derivative, source_sha256)
    response, elapsed = _invoke_candidate_process(
        candidate_path,
        "fit",
        request,
        fit_limit,
    )
    artifact = _normalize_fit_result(
        fixture,
        request,
        response,
        elapsed,
        derivative,
    )
    return artifact, _canonical_hash(request), float(elapsed)


def _run_fixture(candidate_path, source_sha256, fixture, gate):
    fit_limit = float(gate["maximum_fit_seconds_per_sentinel"])
    predict_limit = float(gate["maximum_predict_seconds_per_query"])
    primary, primary_request_hash, primary_fit_seconds = _fit_variant(
        candidate_path,
        source_sha256,
        fixture,
        "primary",
        fixture["train_state"],
        fixture["train_derivative"],
        fit_limit,
    )
    alternative, alternative_request_hash, alternative_fit_seconds = _fit_variant(
        candidate_path,
        source_sha256,
        fixture,
        "alternative",
        fixture["alternative_train_state"],
        fixture["alternative_train_derivative"],
        fit_limit,
    )
    shuffled_derivative = _shuffle_derivative(fixture)
    shuffled, shuffled_request_hash, shuffled_fit_seconds = _fit_variant(
        candidate_path,
        source_sha256,
        fixture,
        "shuffled",
        fixture["train_state"],
        shuffled_derivative,
        fit_limit,
    )
    primary_predictions = _predict_queries(
        candidate_path,
        primary,
        fixture,
        predict_limit,
    )
    shuffled_predictions = _predict_queries(
        candidate_path,
        shuffled,
        fixture,
        predict_limit,
    )
    primary_nmse = _nmse(
        primary_predictions["expected_values"],
        primary_predictions["prediction_values"],
    )
    shuffled_nmse = _nmse(
        shuffled_predictions["expected_values"],
        shuffled_predictions["prediction_values"],
    )
    zero_nmse = _nmse(
        primary_predictions["expected_values"],
        np.zeros(len(primary_predictions["expected_values"]), dtype=np.float64),
    )
    primary_f1, primary_coefficient_error = _equation_recovery(
        primary["equations"],
        fixture["expected_equations"],
    )
    alternative_f1, alternative_coefficient_error = _equation_recovery(
        alternative["equations"],
        fixture["alternative_expected_equations"],
    )
    shuffle_ratio = shuffled_nmse / max(primary_nmse, 1e-30)
    zero_improvement = (zero_nmse - primary_nmse) / max(zero_nmse, 1e-30)
    primary_equation_hash = _canonical_hash(primary["equations"])
    alternative_equation_hash = _canonical_hash(alternative["equations"])
    artifact_changed = primary["artifact_hash"] != alternative["artifact_hash"]
    equation_changed = primary_equation_hash != alternative_equation_hash
    failures = []
    checks = {
        "primary_prediction_nmse": primary_nmse <= float(
            gate["clean_prediction_nmse_maximum"]
        ),
        "primary_term_support": primary_f1 >= float(gate["term_support_f1_minimum"]),
        "primary_coefficient_recovery": primary_coefficient_error <= float(
            gate["clean_coefficient_relative_error_maximum"]
        ),
        "alternative_term_support": alternative_f1
        >= float(gate["term_support_f1_minimum"]),
        "alternative_coefficient_recovery": alternative_coefficient_error
        <= float(gate["clean_coefficient_relative_error_maximum"]),
        "equation_prediction_consistency": max(
            primary_predictions["maximum_equation_prediction_delta"],
            shuffled_predictions["maximum_equation_prediction_delta"],
        )
        <= float(gate["equation_prediction_max_abs_delta"]),
        "train_shuffle_degradation": shuffle_ratio
        >= float(gate["shuffled_nmse_ratio_minimum"]),
        "zero_null_improvement": zero_improvement
        >= float(gate["zero_null_relative_improvement_minimum"]),
        "artifact_training_dependence": artifact_changed,
        "equation_training_dependence": equation_changed,
        "fit_once_query_many": primary_predictions["query_count"]
        >= int(gate["minimum_queries_per_fit"]),
        "fit_budget": max(
            primary_fit_seconds,
            alternative_fit_seconds,
            shuffled_fit_seconds,
        )
        <= fit_limit,
        "predict_budget": max(
            primary_predictions["maximum_predict_seconds"],
            shuffled_predictions["maximum_predict_seconds"],
        )
        <= predict_limit,
    }
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    metric_values = {
        "primary_prediction_nmse": primary_nmse,
        "shuffled_prediction_nmse": shuffled_nmse,
        "shuffle_nmse_ratio": shuffle_ratio,
        "zero_null_nmse": zero_nmse,
        "zero_null_relative_improvement": zero_improvement,
        "primary_term_support_f1": primary_f1,
        "alternative_term_support_f1": alternative_f1,
        "primary_coefficient_relative_error": primary_coefficient_error,
        "alternative_coefficient_relative_error": alternative_coefficient_error,
        "maximum_equation_prediction_delta": max(
            primary_predictions["maximum_equation_prediction_delta"],
            shuffled_predictions["maximum_equation_prediction_delta"],
        ),
    }
    nonfinite_metrics = sorted(
        name for name, value in metric_values.items() if not math.isfinite(float(value))
    )
    failures.extend(f"nonfinite_metric:{name}" for name in nonfinite_metrics)
    result = {
        "sentinel_id": fixture["sentinel_id"],
        "fixture_hash": fixture["fixture_hash"],
        "data_type": fixture["data_type"],
        "spatial_dimensions": int(fixture["spatial_dimensions"]),
        "field_count": len(fixture["field_names"]),
        "query_shape": fixture["queries"][0]["state"]["shape"],
        "primary_fit_request_hash": primary_request_hash,
        "alternative_fit_request_hash": alternative_request_hash,
        "shuffled_fit_request_hash": shuffled_request_hash,
        "primary_artifact_hash": primary["artifact_hash"],
        "alternative_artifact_hash": alternative["artifact_hash"],
        "shuffled_artifact_hash": shuffled["artifact_hash"],
        "primary_equation_hash": primary_equation_hash,
        "alternative_equation_hash": alternative_equation_hash,
        "primary_artifact": primary,
        "alternative_artifact": alternative,
        "shuffled_artifact": shuffled,
        **{name: _json_metric(value) for name, value in metric_values.items()},
        "nonfinite_metrics": nonfinite_metrics,
        "artifact_changed_on_alternative_training": artifact_changed,
        "equation_changed_on_alternative_training": equation_changed,
        "fit_call_count": 3,
        "primary_query_count": int(primary_predictions["query_count"]),
        "shuffled_query_count": int(shuffled_predictions["query_count"]),
        "fit_calls_during_prediction": 0,
        "query_target_derivative_exposed": False,
        "validation_or_test_context_exposed": False,
        "maximum_fit_seconds": float(
            max(primary_fit_seconds, alternative_fit_seconds, shuffled_fit_seconds)
        ),
        "maximum_predict_seconds": float(
            max(
                primary_predictions["maximum_predict_seconds"],
                shuffled_predictions["maximum_predict_seconds"],
            )
        ),
        "checks": checks,
        "failure_codes": failures,
        "passed": not failures,
    }
    result["result_hash"] = _canonical_hash(result)
    return result


def _failure_result(fixture, error):
    result = {
        "sentinel_id": fixture["sentinel_id"],
        "fixture_hash": fixture["fixture_hash"],
        "data_type": fixture["data_type"],
        "spatial_dimensions": int(fixture["spatial_dimensions"]),
        "field_count": len(fixture["field_names"]),
        "query_shape": fixture["queries"][0]["state"]["shape"],
        "error_type": type(error).__name__,
        "error_message": str(error)[:2000],
        "traceback": traceback.format_exc(limit=12)[-8000:],
        "failure_codes": ["contract_execution_error"],
        "passed": False,
    }
    result["result_hash"] = _canonical_hash(result)
    return result


def _run_worker(candidate_path, function_name, timeout_seconds):
    try:
        request = json.loads(sys.stdin.read())
        module, fit, predict = _load_module(
            candidate_path,
            f"scientific_candidate_worker_{function_name}",
        )
        if function_name == "predict":

            def _fit_after_query_blocker(_payload):
                raise ContractError("fit_equations was called during prediction")

            module.fit_equations = _fit_after_query_blocker
            function = predict
        else:
            function = fit
        response, elapsed = _call_candidate(function, request, timeout_seconds)
        envelope = {
            "ok": True,
            "response": response,
            "error_type": None,
            "error_message": None,
            "candidate_error_location": None,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:  # noqa: BLE001 - parent retains typed failure evidence
        envelope = {
            "ok": False,
            "response": None,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:2000],
            "candidate_error_location": _candidate_error_location(
                exc,
                candidate_path,
            ),
            "elapsed_seconds": None,
        }
    print(json.dumps(envelope, allow_nan=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--worker-function", choices=("fit", "predict"))
    parser.add_argument("--worker-timeout-seconds", type=float)
    arguments = parser.parse_args()
    candidate_path = Path(arguments.candidate)
    if arguments.worker_function is not None:
        if arguments.worker_timeout_seconds is None:
            raise ValueError("candidate worker timeout is required")
        _run_worker(
            candidate_path,
            arguments.worker_function,
            arguments.worker_timeout_seconds,
        )
        return
    payload = json.loads(sys.stdin.read())
    _validate_harness_input(payload)
    if payload.get("expected_runner_sha256") != _file_hash(__file__):
        raise ValueError("scientific Harness runner bytes changed")
    if payload.get("candidate_source_sha256") != _file_hash(candidate_path):
        raise ValueError("scientific Harness candidate bytes changed")
    fixtures = payload["fixtures"]
    results = []
    for fixture in fixtures:
        try:
            results.append(
                _run_fixture(
                    candidate_path,
                    payload["candidate_source_sha256"],
                    fixture,
                    payload["contract_gate"],
                )
            )
        except Exception as exc:  # noqa: BLE001 - failures are retained evidence
            results.append(_failure_result(fixture, exc))
    output = {
        "schema_version": "scientific-contract-harness-observation-v1",
        "plan_hash": payload["plan_hash"],
        "erratum_hash": payload["erratum_hash"],
        "corrected_sentinel_registry_hash": payload[
            "corrected_sentinel_registry_hash"
        ],
        "candidate_source_sha256": payload["candidate_source_sha256"],
        "runner_sha256": payload["expected_runner_sha256"],
        "network_used": False,
        "official_development_artifact_reads": 0,
        "confirmation_identity_reads": 0,
        "confirmation_result_reads": 0,
        "sentinel_results": results,
        "sentinel_count": len(results),
        "passed_sentinel_count": sum(item["passed"] for item in results),
        "fit_call_count": sum(item.get("fit_call_count", 0) for item in results),
        "predict_call_count": sum(
            item.get("primary_query_count", 0) + item.get("shuffled_query_count", 0)
            for item in results
        ),
        "passed": bool(results and all(item["passed"] for item in results)),
    }
    output["observation_hash"] = _canonical_hash(output)
    print(json.dumps(output, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
