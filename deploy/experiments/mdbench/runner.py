#!/usr/bin/env python3
"""Offline scientific runner for one frozen MDBench matrix cell.

This file intentionally lives in the versioned experiment container rather than
the lightweight core package.  It emits code-computed evidence only; aggregation,
structure scoring, and Gate A decisions remain host-side tasks.
"""

import argparse
import hashlib
import itertools
import json
import os
import resource
import signal
import sys
import time
import traceback
from importlib.metadata import version
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import savgol_filter
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures


class AttemptTimeout(Exception):
    """Raised by the in-container attempt alarm."""


def _alarm_handler(_signum, _frame):
    raise AttemptTimeout("in-container scientific attempt timeout")


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
    temporary = destination.with_name(".%s.tmp" % destination.name)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _load_and_validate_spec(path, runner_path, data_path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    spec_hash = spec.pop("spec_hash", None)
    if spec_hash != _canonical_hash(spec):
        raise ValueError("runner spec content hash mismatch")
    runner_hash = _file_hash(runner_path)
    if spec.get("expected_runner_sha256") != runner_hash:
        raise ValueError("runner bytes do not match the host execution contract")
    attempt = spec["attempt"]
    if _file_hash(data_path) != attempt["artifact_sha256"]:
        raise ValueError("mounted data bytes do not match the frozen artifact hash")
    return spec, spec_hash, runner_hash


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
        raise ValueError("frozen fractions do not produce three non-empty time splits")
    return result


def _time_slice(array, start, end, axis):
    slices = [slice(None)] * array.ndim
    slices[axis] = slice(start, end)
    return array[tuple(slices)]


def _split_data(data, split):
    t = np.asarray(data["t"], dtype=np.float64).reshape(-1)
    u = np.asarray(data["u"], dtype=np.float64)
    du_true = np.asarray(data["du"], dtype=np.float64)
    time_axis = 0 if u.ndim == 2 else u.ndim - 2
    if u.shape[time_axis] != len(t) or du_true.shape != u.shape:
        raise ValueError("MDBench NPZ time/state/derivative shapes are inconsistent")
    pieces = {}
    for name in ("train", "validation", "test"):
        start = split["%s_start" % name]
        end = split["%s_end" % name]
        pieces[name] = {
            "t": t[start:end],
            "u": _time_slice(u, start, end, time_axis),
            "du_true": _time_slice(du_true, start, end, time_axis),
        }
    pieces["train_validation"] = {
        "t": t[: split["validation_end"]],
        "u": _time_slice(u, 0, split["validation_end"], time_axis),
        "du_true": _time_slice(du_true, 0, split["validation_end"], time_axis),
    }
    spatial_grids = [
        np.asarray(data[key], dtype=np.float64).reshape(-1)
        for key in ("x", "y", "z")
        if key in data
    ]
    return pieces, spatial_grids, time_axis


def _finite_difference(u, t, axis):
    if len(t) < 3:
        raise ValueError("split is too short for a local finite-difference derivative")
    return np.gradient(u, t, axis=axis, edge_order=2)


def _nmse(y_true, y_pred):
    truth = np.asarray(y_true, dtype=np.float64)
    prediction = np.asarray(y_pred, dtype=np.float64).reshape(truth.shape)
    if not np.all(np.isfinite(prediction)):
        raise FloatingPointError("non-finite derivative prediction")
    denominator = float(np.sum(truth**2)) + 1e-10
    return float(np.sum((truth - prediction) ** 2) / denominator)


def _fitness(nmse, complexity):
    return 1.0 / (1.0 + float(nmse)) + np.exp(-float(complexity) / 200.0)


def _target_names(dimension):
    return ["u%d_t" % index for index in range(dimension)]


def _baseline_configs(method, data_type):
    parameters = method["parameters"]
    common = {
        "basis_functions": parameters["basis_functions"],
        "optimizer_threshold": parameters["optimizer_threshold"],
        "poly_order": parameters["poly_order"],
    }
    if data_type == "ode":
        common["optimizer_alpha"] = parameters["optimizer_alpha"]
    else:
        common["alpha"] = parameters["optimizer_alpha"]
        common["derivative_order"] = parameters["pde_derivative_order"]
    keys = list(common)
    for values in itertools.product(*(common[key] for key in keys)):
        yield dict(zip(keys, values))


def _new_baseline_model(data_type, config, dimension, spatial_grids, cpu_cores):
    kwargs = dict(config)
    kwargs.update(
        {
            "n_jobs": int(cpu_cores),
            "target_names": ["u%d" % index for index in range(dimension)],
        }
    )
    if data_type == "ode":
        from mdbench.algorithms.ode.sindy.regressor import Estimator
    else:
        from mdbench.algorithms.pde.pdefind.regressor import Estimator
    model = Estimator(**kwargs)
    if data_type == "pde":
        model.set_spatial_grid(spatial_grids)
    return model


def _extract_pysindy_coefficients(model, dimension):
    inner = model.model
    feature_names = [str(name).replace(" ", "*") for name in inner.get_feature_names()]
    matrix = np.asarray(inner.coefficients(), dtype=np.float64)
    targets = []
    for target_index in range(dimension):
        terms = []
        for feature, coefficient in zip(feature_names, matrix[target_index]):
            if abs(float(coefficient)) > 1e-10:
                terms.append({"feature": feature, "coefficient": float(coefficient)})
        targets.append({"target": "u%d_t" % target_index, "terms": terms})
    return targets


def _run_sparse_baseline(spec, pieces, spatial_grids, time_axis):
    attempt = spec["attempt"]
    method = spec["method"]
    data_type = attempt["data_type"]
    train = pieces["train"]
    validation = pieces["validation"]
    train_validation = pieces["train_validation"]
    test = pieces["test"]
    train_dot = _finite_difference(train["u"], train["t"], time_axis)
    validation_dot = _finite_difference(validation["u"], validation["t"], time_axis)
    dimension = train["u"].shape[-1]
    best = None
    errors = []
    for config in _baseline_configs(method, data_type):
        try:
            model = _new_baseline_model(
                data_type,
                config,
                dimension,
                spatial_grids,
                method["max_cpu_cores"],
            )
            model.fit(train["t"], train["u"], train_dot)
            prediction = model.predict(validation["t"], validation["u"])
            validation_nmse = _nmse(validation_dot, prediction)
            complexity = int(model.complexity())
            score = _fitness(validation_nmse, complexity)
            candidate = (score, -validation_nmse, -complexity, config)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
        except Exception as exc:  # one bounded hyperparameter candidate may fail
            errors.append("%s: %s" % (config, exc))
    if best is None:
        raise RuntimeError("every frozen sparse configuration failed: %s" % errors[-3:])
    selected = best[3]
    final_dot = _finite_difference(
        train_validation["u"], train_validation["t"], time_axis
    )
    final_model = _new_baseline_model(
        data_type,
        selected,
        dimension,
        spatial_grids,
        method["max_cpu_cores"],
    )
    final_model.fit(train_validation["t"], train_validation["u"], final_dot)
    test_prediction = final_model.predict(test["t"], test["u"])
    derivative_nmse = _nmse(test["du_true"], test_prediction)
    trajectory_nmse = None
    if data_type == "ode":
        trajectory_nmse = _trajectory_nmse(
            lambda states: final_model.predict(None, states),
            test["t"],
            test["u"],
        )
    return {
        "selected_hyperparameters": _json_safe(selected),
        "discovered_equation": str(final_model.to_str()),
        "coefficients": _extract_pysindy_coefficients(final_model, dimension),
        "validation_nmse": float(-best[1]),
        "derivative_nmse": derivative_nmse,
        "trajectory_extrapolation_nmse_ode": trajectory_nmse,
        "model_complexity": int(final_model.complexity()),
    }


def _savgol_pair(piece, time_axis, window, polyorder):
    n_time = len(piece["t"])
    if window > n_time or window % 2 == 0 or polyorder >= window:
        raise ValueError("Savitzky-Golay window is invalid for this split")
    delta = float(np.median(np.diff(piece["t"])))
    smooth = savgol_filter(
        piece["u"],
        window_length=int(window),
        polyorder=int(polyorder),
        deriv=0,
        axis=time_axis,
        mode="interp",
    )
    derivative = savgol_filter(
        piece["u"],
        window_length=int(window),
        polyorder=int(polyorder),
        deriv=1,
        delta=delta,
        axis=time_axis,
        mode="interp",
    )
    return np.asarray(smooth, dtype=np.float64), np.asarray(derivative, dtype=np.float64)


def _polynomial_matrix(states, degree, names):
    flattened = np.asarray(states, dtype=np.float64).reshape(-1, states.shape[-1])
    library = PolynomialFeatures(degree=int(degree), include_bias=True)
    theta = library.fit_transform(flattened)
    feature_names = [
        str(name).replace(" ", "*")
        for name in library.get_feature_names_out(names)
    ]
    return theta, feature_names, library


def _spatial_derivatives(states, x, derivative_order):
    derivatives = []
    current = np.asarray(states, dtype=np.float64)
    for order in range(1, int(derivative_order) + 1):
        current = np.gradient(current, x, axis=0, edge_order=2)
        derivatives.append((order, np.asarray(current, dtype=np.float64)))
    return derivatives


def _pde_library(states, x, degree, derivative_order):
    dimension = states.shape[-1]
    variable_names = ["u%d" % index for index in range(dimension)]
    polynomial, polynomial_names, _library = _polynomial_matrix(
        states,
        degree,
        variable_names,
    )
    columns = [polynomial]
    names = list(polynomial_names)
    derivatives = _spatial_derivatives(states, x, derivative_order)
    derivative_columns = []
    derivative_names = []
    for order, derivative in derivatives:
        flattened = derivative.reshape(-1, dimension)
        for variable_index in range(dimension):
            derivative_columns.append(flattened[:, variable_index : variable_index + 1])
            derivative_names.append("u%d_%s" % (variable_index, "x" * order))
    if derivative_columns:
        derivative_matrix = np.concatenate(derivative_columns, axis=1)
        columns.append(derivative_matrix)
        names.extend(derivative_names)
        for poly_index, poly_name in enumerate(polynomial_names[1:], start=1):
            products = polynomial[:, poly_index : poly_index + 1] * derivative_matrix
            columns.append(products)
            names.extend(
                ["(%s)*(%s)" % (poly_name, derivative_name) for derivative_name in derivative_names]
            )
    return np.concatenate(columns, axis=1), names


def _candidate_library(states, data_type, degree, derivative_order, spatial_grids):
    if data_type == "ode":
        names = ["u%d" % index for index in range(states.shape[-1])]
        theta, feature_names, _library = _polynomial_matrix(states, degree, names)
        return theta, feature_names
    if len(spatial_grids) != 1:
        raise ValueError("Gate A v1 candidate supports the preregistered 1D PDE panel only")
    return _pde_library(states, spatial_grids[0], degree, derivative_order)


def _stlsq(
    theta,
    targets,
    threshold,
    alpha,
    fixed_mask=None,
    normalize_columns=False,
):
    x = np.asarray(theta, dtype=np.float64)
    y = np.asarray(targets, dtype=np.float64).reshape(-1, targets.shape[-1])
    if x.shape[0] != y.shape[0]:
        raise ValueError("feature and derivative row counts differ")
    column_scales = np.ones(x.shape[1], dtype=np.float64)
    if normalize_columns:
        column_norms = np.linalg.norm(x, axis=0)
        nonzero = column_norms > np.finfo(np.float64).eps
        column_scales[nonzero] = column_norms[nonzero]
        x = x / column_scales
    coefficients = np.zeros((y.shape[1], x.shape[1]), dtype=np.float64)
    for target_index in range(y.shape[1]):
        active = (
            np.ones(x.shape[1], dtype=bool)
            if fixed_mask is None
            else np.asarray(fixed_mask[target_index], dtype=bool).copy()
        )
        for _iteration in range(20):
            if not np.any(active):
                break
            model = Ridge(
                alpha=float(alpha),
                fit_intercept=False,
                solver="lsqr",
                tol=1e-8,
            )
            model.fit(x[:, active], y[:, target_index])
            current = np.asarray(model.coef_, dtype=np.float64)
            keep = np.abs(current) >= float(threshold)
            indices = np.flatnonzero(active)
            next_active = active.copy()
            next_active[indices] = keep
            if np.array_equal(next_active, active):
                coefficients[target_index, indices] = current
                break
            active = next_active
        else:
            if np.any(active):
                model = Ridge(alpha=float(alpha), fit_intercept=False, solver="lsqr")
                model.fit(x[:, active], y[:, target_index])
                coefficients[target_index, np.flatnonzero(active)] = model.coef_
        if np.any(active) and not np.any(coefficients[target_index]):
            model = Ridge(alpha=float(alpha), fit_intercept=False, solver="lsqr")
            model.fit(x[:, active], y[:, target_index])
            coefficients[target_index, np.flatnonzero(active)] = model.coef_
    if normalize_columns:
        coefficients = coefficients / column_scales[np.newaxis, :]
    return coefficients


def _linear_predict(theta, coefficients):
    return np.asarray(theta, dtype=np.float64).dot(np.asarray(coefficients).T)


def _coefficient_payload(coefficients, feature_names):
    targets = []
    for target_index, row in enumerate(coefficients):
        terms = [
            {"feature": feature, "coefficient": float(coefficient)}
            for feature, coefficient in zip(feature_names, row)
            if abs(float(coefficient)) > 1e-10
        ]
        targets.append({"target": "u%d_t" % target_index, "terms": terms})
    return targets


def _equation_text(coefficients, feature_names):
    equations = []
    for target_index, row in enumerate(coefficients):
        terms = []
        for feature, coefficient in zip(feature_names, row):
            if abs(float(coefficient)) > 1e-10:
                terms.append("%+.12g*(%s)" % (float(coefficient), feature))
        rhs = " ".join(terms) if terms else "0"
        equations.append("u%d_t = %s" % (target_index, rhs))
    return "\n".join(equations)


def _model_complexity(coefficients, feature_names):
    complexity = 0
    for row in coefficients:
        for feature, coefficient in zip(feature_names, row):
            if abs(float(coefficient)) > 1e-10:
                complexity += 2 + feature.count("*") + feature.count("^")
    return int(complexity)


def _weak_library_functions(degree):
    if int(degree) not in (1, 2, 3):
        raise ValueError("frozen weak-form polynomial degree must be 1, 2, or 3")
    functions = [
        lambda x: x,
        lambda x, y: x * y,
        lambda x, y, z: x * y * z,
    ]
    function_names = [
        lambda x: x,
        lambda x, y: "%s*%s" % (x, y),
        lambda x, y, z: "%s*%s*%s" % (x, y, z),
    ]
    return functions[: int(degree)], function_names[: int(degree)]


def _weak_feature_names(dimension, degree, derivative_order):
    variable_names = ["u%d" % index for index in range(int(dimension))]
    polynomial = PolynomialFeatures(degree=int(degree), include_bias=True)
    polynomial.fit(np.zeros((1, int(dimension))))
    polynomial_names = [
        str(name).replace(" ", "*")
        for name in polynomial.get_feature_names_out(variable_names)
    ]
    if int(derivative_order) == 0:
        return polynomial_names
    derivative_names = [
        "u%d_%s" % (variable_index, "x" * order)
        for order in range(1, int(derivative_order) + 1)
        for variable_index in range(int(dimension))
    ]
    mixed_names = [
        "(%s)*(u%d_%s)" % (polynomial_name, variable_index, "x" * order)
        for order in range(1, int(derivative_order) + 1)
        for polynomial_name in polynomial_names[1:]
        for variable_index in range(int(dimension))
    ]
    return polynomial_names + derivative_names + mixed_names


def _weak_strong_library(states, data_type, degree, derivative_order, spatial_grids):
    dimension = states.shape[-1]
    variable_names = ["u%d" % index for index in range(dimension)]
    polynomial, polynomial_names, _library = _polynomial_matrix(
        states,
        degree,
        variable_names,
    )
    if data_type == "ode":
        return polynomial, polynomial_names
    if len(spatial_grids) != 1 or states.ndim != 3:
        raise ValueError("weak-form recovery candidate supports one-dimensional PDEs only")
    derivatives = _spatial_derivatives(states, spatial_grids[0], derivative_order)
    columns = [polynomial]
    names = list(polynomial_names)
    flattened_derivatives = []
    for order, derivative in derivatives:
        flattened = derivative.reshape(-1, dimension)
        flattened_derivatives.append((order, flattened))
        for variable_index in range(dimension):
            columns.append(flattened[:, variable_index : variable_index + 1])
            names.append("u%d_%s" % (variable_index, "x" * order))
    for order, flattened in flattened_derivatives:
        for polynomial_index, polynomial_name in enumerate(
            polynomial_names[1:],
            start=1,
        ):
            for variable_index in range(dimension):
                columns.append(
                    polynomial[:, polynomial_index : polynomial_index + 1]
                    * flattened[:, variable_index : variable_index + 1]
                )
                names.append(
                    "(%s)*(u%d_%s)"
                    % (polynomial_name, variable_index, "x" * order)
                )
    expected_names = _weak_feature_names(dimension, degree, derivative_order)
    if names != expected_names:
        raise ValueError("strong evaluation library does not match weak feature ordering")
    return np.concatenate(columns, axis=1), names


def _weak_spatiotemporal_grid(piece, data_type, spatial_grids):
    if data_type == "ode":
        return np.asarray(piece["t"], dtype=np.float64).reshape(-1, 1)
    if len(spatial_grids) != 1 or piece["u"].ndim != 3:
        raise ValueError("weak-form recovery candidate supports one-dimensional PDEs only")
    x_grid, t_grid = np.meshgrid(
        np.asarray(spatial_grids[0], dtype=np.float64),
        np.asarray(piece["t"], dtype=np.float64),
        indexing="ij",
    )
    grid = np.stack((x_grid, t_grid), axis=-1)
    if grid.shape[:-1] != piece["u"].shape[:-1]:
        raise ValueError("weak spatiotemporal grid does not match the state tensor")
    return grid


def _weak_projection(
    piece,
    data_type,
    degree,
    derivative_order,
    spatial_grids,
    subdomains,
    projection_seed,
):
    import pysindy as ps

    functions, function_names = _weak_library_functions(degree)
    grid = _weak_spatiotemporal_grid(piece, data_type, spatial_grids)
    random_state = np.random.get_state()
    try:
        np.random.seed(int(projection_seed))
        library = ps.WeakPDELibrary(
            library_functions=functions,
            function_names=function_names,
            derivative_order=int(derivative_order),
            spatiotemporal_grid=grid,
            interaction_only=False,
            include_bias=True,
            include_interaction=int(derivative_order) > 0,
            K=int(subdomains),
            p=4,
        )
    finally:
        np.random.set_state(random_state)
    design = np.asarray(library.fit_transform(piece["u"]), dtype=np.float64)
    targets = np.asarray(
        library.convert_u_dot_integral(piece["u"]),
        dtype=np.float64,
    )
    feature_names = _weak_feature_names(
        piece["u"].shape[-1],
        degree,
        derivative_order,
    )
    if design.shape != (int(subdomains), len(feature_names)):
        raise ValueError("PySINDy weak design shape does not match the frozen library")
    if targets.shape != (int(subdomains), piece["u"].shape[-1]):
        raise ValueError("PySINDy weak target shape does not match the state dimension")
    if not np.all(np.isfinite(design)) or not np.all(np.isfinite(targets)):
        raise FloatingPointError("PySINDy weak projection produced non-finite values")
    return design, targets, feature_names


def _weak_projection_seed(attempt_seed, split_name):
    split_offsets = {
        "train": 104729,
        "validation": 119087,
        "train_validation": 130363,
    }
    if split_name not in split_offsets:
        raise ValueError("unsupported weak projection split")
    return int((int(attempt_seed) * 1000003 + split_offsets[split_name]) % (2**32 - 1))


def _run_weak_stability_candidate(spec, pieces, spatial_grids, _time_axis):
    attempt = spec["attempt"]
    parameters = spec["method"]["parameters"]
    if parameters.get("mechanisms") != [
        "weak_form_projection",
        "bootstrap_support_stability",
    ]:
        raise ValueError("weak recovery mechanisms differ from the frozen contract")
    if version("pysindy") != "1.7.5":
        raise ValueError("weak recovery candidate requires pinned PySINDy 1.7.5")
    data_type = attempt["data_type"]
    train = pieces["train"]
    validation = pieces["validation"]
    derivative_orders = (
        [0] if data_type == "ode" else parameters["pde_derivative_order"]
    )
    subdomains = int(parameters["weak_subdomains"])
    train_projection_seed = _weak_projection_seed(attempt["seed"], "train")
    validation_projection_seed = _weak_projection_seed(
        attempt["seed"],
        "validation",
    )
    best = None
    errors = []
    for degree, derivative_order in itertools.product(
        parameters["poly_order"],
        derivative_orders,
    ):
        try:
            theta_train, weak_targets, feature_names = _weak_projection(
                train,
                data_type,
                degree,
                derivative_order,
                spatial_grids,
                subdomains,
                train_projection_seed,
            )
            theta_validation, weak_validation_targets, validation_names = _weak_projection(
                validation,
                data_type,
                degree,
                derivative_order,
                spatial_grids,
                subdomains,
                validation_projection_seed,
            )
            if validation_names != feature_names:
                raise ValueError("train and validation weak feature libraries differ")
            for threshold in parameters["optimizer_threshold"]:
                coefficients = _stlsq(
                    theta_train,
                    weak_targets,
                    threshold,
                    1e-5,
                    normalize_columns=True,
                )
                prediction = _linear_predict(theta_validation, coefficients)
                validation_nmse = _nmse(weak_validation_targets, prediction)
                complexity = _model_complexity(coefficients, feature_names)
                key = (
                    validation_nmse,
                    complexity,
                    int(degree),
                    int(derivative_order),
                    float(threshold),
                )
                if best is None or key[:2] < best[:2]:
                    best = key
        except Exception as exc:
            errors.append(
                "degree=%s derivative_order=%s: %s"
                % (degree, derivative_order, exc)
            )
    if best is None:
        raise RuntimeError("every frozen weak-form configuration failed: %s" % errors[-3:])
    validation_nmse, _complexity, degree, derivative_order, threshold = best
    train_validation = pieces["train_validation"]
    final_projection_seed = _weak_projection_seed(
        attempt["seed"],
        "train_validation",
    )
    theta_final, weak_targets, feature_names = _weak_projection(
        train_validation,
        data_type,
        degree,
        derivative_order,
        spatial_grids,
        subdomains,
        final_projection_seed,
    )
    repetitions = int(parameters["bootstrap_repetitions"])
    sample_size = max(
        1,
        int(theta_final.shape[0] * float(parameters["subsample_fraction"])),
    )
    rng = np.random.default_rng(int(attempt["seed"]) + 2597)
    selected_counts = np.zeros(
        (weak_targets.shape[1], theta_final.shape[1]),
        dtype=np.int64,
    )
    for _replicate in range(repetitions):
        indices = rng.choice(theta_final.shape[0], size=sample_size, replace=False)
        coefficients = _stlsq(
            theta_final[indices],
            weak_targets[indices],
            threshold,
            1e-5,
            normalize_columns=True,
        )
        selected_counts += np.abs(coefficients) > 1e-10
    support_frequency = selected_counts / float(repetitions)
    stable_mask = support_frequency >= float(parameters["selection_frequency"])
    coefficients = _stlsq(
        theta_final,
        weak_targets,
        threshold,
        1e-5,
        fixed_mask=stable_mask,
        normalize_columns=True,
    )
    test = pieces["test"]
    theta_test, test_names = _weak_strong_library(
        test["u"],
        data_type,
        degree,
        derivative_order,
        spatial_grids,
    )
    if test_names != feature_names:
        raise ValueError("weak and strong test feature libraries differ")
    prediction = _linear_predict(theta_test, coefficients).reshape(test["du_true"].shape)
    derivative_nmse = _nmse(test["du_true"], prediction)
    trajectory_nmse = None
    if data_type == "ode":
        polynomial = PolynomialFeatures(degree=int(degree), include_bias=True)
        polynomial.fit(np.zeros((1, test["u"].shape[-1])))
        trajectory_nmse = _trajectory_nmse(
            lambda states: polynomial.transform(states).dot(coefficients.T),
            test["t"],
            test["u"],
        )
    selected = {
        "mechanisms": list(parameters["mechanisms"]),
        "pysindy_version": version("pysindy"),
        "pysindy_revision": parameters["pysindy_revision"],
        "weak_library": parameters["weak_library"],
        "weak_subdomains": subdomains,
        "weak_weight_degree": 4,
        "weak_projection_seed": final_projection_seed,
        "validation_objective": "weak_form_derivative_nmse",
        "bootstrap_repetitions": repetitions,
        "subsample_fraction": float(parameters["subsample_fraction"]),
        "selection_frequency": float(parameters["selection_frequency"]),
        "stable_support_size": [int(np.count_nonzero(row)) for row in stable_mask],
        "poly_order": int(degree),
        "derivative_order": int(derivative_order),
        "optimizer_threshold": float(threshold),
        "optimizer_alpha": 1e-5,
        "normalize_columns": True,
    }
    return {
        "selected_hyperparameters": selected,
        "discovered_equation": _equation_text(coefficients, feature_names),
        "coefficients": _coefficient_payload(coefficients, feature_names),
        "validation_nmse": float(validation_nmse),
        "derivative_nmse": derivative_nmse,
        "trajectory_extrapolation_nmse_ode": trajectory_nmse,
        "model_complexity": _model_complexity(coefficients, feature_names),
    }


def _run_stability_candidate(spec, pieces, spatial_grids, time_axis):
    attempt = spec["attempt"]
    method = spec["method"]
    parameters = method["parameters"]
    data_type = attempt["data_type"]
    train = pieces["train"]
    validation = pieces["validation"]
    best = None
    cached = {}
    derivative_orders = (
        [0] if data_type == "ode" else parameters["pde_derivative_order"]
    )
    for window in parameters["savgol_windows"]:
        try:
            cached[("train", window)] = _savgol_pair(
                train, time_axis, window, parameters["savgol_polyorder"]
            )
            cached[("validation", window)] = _savgol_pair(
                validation, time_axis, window, parameters["savgol_polyorder"]
            )
        except ValueError:
            continue
        train_smooth, train_dot = cached[("train", window)]
        validation_smooth, validation_dot = cached[("validation", window)]
        for degree, derivative_order, threshold in itertools.product(
            parameters["poly_order"],
            derivative_orders,
            parameters["optimizer_threshold"],
        ):
            theta_train, names = _candidate_library(
                train_smooth,
                data_type,
                degree,
                derivative_order,
                spatial_grids,
            )
            theta_validation, validation_names = _candidate_library(
                validation_smooth,
                data_type,
                degree,
                derivative_order,
                spatial_grids,
            )
            if validation_names != names:
                raise ValueError("candidate feature library changed across splits")
            coefficients = _stlsq(
                theta_train,
                train_dot,
                threshold,
                1e-5,
            )
            prediction = _linear_predict(theta_validation, coefficients)
            validation_nmse = _nmse(validation_dot, prediction)
            complexity = _model_complexity(coefficients, names)
            key = (validation_nmse, complexity, window, degree, derivative_order, threshold)
            if best is None or key[:2] < best[:2]:
                best = key
    if best is None:
        raise RuntimeError("no valid train-only Savitzky-Golay candidate configuration")
    validation_nmse, _complexity, window, degree, derivative_order, threshold = best
    train_validation = pieces["train_validation"]
    final_smooth, final_dot = _savgol_pair(
        train_validation,
        time_axis,
        window,
        parameters["savgol_polyorder"],
    )
    theta_final, feature_names = _candidate_library(
        final_smooth,
        data_type,
        degree,
        derivative_order,
        spatial_grids,
    )
    y_final = final_dot.reshape(-1, final_dot.shape[-1])
    repetitions = int(parameters["bootstrap_repetitions"])
    sample_size = max(1, int(theta_final.shape[0] * float(parameters["subsample_fraction"])))
    rng = np.random.default_rng(int(attempt["seed"]))
    selected_counts = np.zeros((y_final.shape[1], theta_final.shape[1]), dtype=np.int64)
    for _replicate in range(repetitions):
        indices = rng.choice(theta_final.shape[0], size=sample_size, replace=False)
        coefficients = _stlsq(
            theta_final[indices],
            y_final[indices],
            threshold,
            1e-5,
        )
        selected_counts += np.abs(coefficients) > 1e-10
    stable_mask = selected_counts / float(repetitions) >= float(
        parameters["selection_frequency"]
    )
    coefficients = _stlsq(
        theta_final,
        y_final,
        threshold,
        1e-5,
        fixed_mask=stable_mask,
    )
    test = pieces["test"]
    test_smooth, _test_dot = _savgol_pair(
        test,
        time_axis,
        window,
        parameters["savgol_polyorder"],
    )
    theta_test, test_names = _candidate_library(
        test_smooth,
        data_type,
        degree,
        derivative_order,
        spatial_grids,
    )
    if test_names != feature_names:
        raise ValueError("candidate test feature library does not match final fit")
    prediction = _linear_predict(theta_test, coefficients).reshape(test["du_true"].shape)
    derivative_nmse = _nmse(test["du_true"], prediction)
    trajectory_nmse = None
    if data_type == "ode":
        names = ["u%d" % index for index in range(test["u"].shape[-1])]
        polynomial = PolynomialFeatures(degree=int(degree), include_bias=True)
        polynomial.fit(np.zeros((1, len(names))))
        trajectory_nmse = _trajectory_nmse(
            lambda states: polynomial.transform(states).dot(coefficients.T),
            test["t"],
            test["u"],
        )
    selected = {
        "bootstrap_repetitions": repetitions,
        "subsample_fraction": float(parameters["subsample_fraction"]),
        "selection_frequency": float(parameters["selection_frequency"]),
        "savgol_window": int(window),
        "savgol_polyorder": int(parameters["savgol_polyorder"]),
        "poly_order": int(degree),
        "derivative_order": int(derivative_order),
        "optimizer_threshold": float(threshold),
        "optimizer_alpha": 1e-5,
    }
    return {
        "selected_hyperparameters": selected,
        "discovered_equation": _equation_text(coefficients, feature_names),
        "coefficients": _coefficient_payload(coefficients, feature_names),
        "validation_nmse": float(validation_nmse),
        "derivative_nmse": derivative_nmse,
        "trajectory_extrapolation_nmse_ode": trajectory_nmse,
        "model_complexity": _model_complexity(coefficients, feature_names),
    }


def _operon_inputs(piece, data_type, spatial_grids, time_axis):
    derivative = _finite_difference(piece["u"], piece["t"], time_axis)
    if data_type == "ode":
        states = piece["u"].reshape(-1, piece["u"].shape[-1])
        names = ["u%d" % index for index in range(states.shape[-1])]
        return states, derivative.reshape(-1, derivative.shape[-1]), names
    if len(spatial_grids) != 1:
        raise ValueError("Gate A v1 Operon adapter supports the selected 1D PDE panel only")
    states = piece["u"]
    flattened = states.reshape(-1, states.shape[-1])
    columns = [flattened]
    names = ["u%d" % index for index in range(states.shape[-1])]
    for order, spatial_derivative in _spatial_derivatives(states, spatial_grids[0], 4):
        columns.append(spatial_derivative.reshape(-1, states.shape[-1]))
        names.extend(
            ["u%d_%s" % (index, "x" * order) for index in range(states.shape[-1])]
        )
    return (
        np.concatenate(columns, axis=1),
        derivative.reshape(-1, derivative.shape[-1]),
        names,
    )


def _run_operon(spec, pieces, spatial_grids, time_axis):
    from pyoperon.sklearn import SymbolicRegressor

    attempt = spec["attempt"]
    parameters = spec["method"]["parameters"]
    data_type = attempt["data_type"]
    x_train, y_train, names = _operon_inputs(
        pieces["train"], data_type, spatial_grids, time_axis
    )
    x_validation, y_validation, validation_names = _operon_inputs(
        pieces["validation"], data_type, spatial_grids, time_axis
    )
    x_test, _y_test_approx, test_names = _operon_inputs(
        pieces["test"], data_type, spatial_grids, time_axis
    )
    if names != validation_names or names != test_names:
        raise ValueError("Operon feature names changed across chronological splits")
    x_train = np.asarray(x_train, dtype=np.float64, order="F")
    x_validation = np.asarray(x_validation, dtype=np.float64, order="F")
    x_test = np.asarray(x_test, dtype=np.float64, order="F")
    models = []
    validation_predictions = []
    test_predictions = []
    equation_lines = []
    total_complexity = 0
    selected_front = []
    for target_index in range(y_train.shape[-1]):
        kwargs = {
            "allowed_symbols": "add,sub,mul,aq,sin,constant,variable",
            "brood_size": 10,
            "comparison_factor": 0,
            "crossover_internal_probability": 0.9,
            "crossover_probability": 1.0,
            "epsilon": 1e-5,
            "female_selector": "tournament",
            "generations": int(parameters["generations"]),
            "initialization_max_depth": 5,
            "initialization_max_length": 10,
            "initialization_method": "btc",
            "irregularity_bias": 0.0,
            "local_search_probability": 1.0,
            "lamarckian_probability": 1.0,
            "optimizer_iterations": 1,
            "optimizer": "lm",
            "male_selector": "tournament",
            "max_depth": 10,
            "max_evaluations": int(parameters["max_evaluations"]),
            "max_length": 50,
            "max_selection_pressure": 100,
            "model_selection_criterion": "minimum_description_length",
            "mutation_probability": 0.25,
            "objectives": ["r2", "length"],
            "offspring_generator": "os",
            "pool_size": int(parameters["pool_size"]),
            "population_size": int(parameters["population_size"]),
            "random_state": int(attempt["seed"]) + target_index,
            "reinserter": "keep-best",
            "max_time": int(parameters["max_time_seconds"]),
            "tournament_size": 3,
            "add_model_intercept_term": True,
            "add_model_scale_term": True,
            "n_threads": int(spec["method"]["max_cpu_cores"]),
        }
        model = SymbolicRegressor(**kwargs)
        model.fit(
            x_train,
            np.asarray(y_train[:, target_index], dtype=np.float64),
        )
        front = list(model.pareto_front_)
        if not front:
            raise RuntimeError("Operon returned an empty Pareto front")
        best = None
        for solution in front:
            prediction = model.evaluate_model(solution["tree"], x_validation)
            error = _nmse(y_validation[:, target_index], prediction)
            complexity = int(solution["complexity"])
            score = _fitness(error, complexity)
            candidate = (score, -error, -complexity, solution)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
        selected = best[3]
        model.model_ = selected["tree"]
        validation_predictions.append(model.predict(x_validation))
        test_predictions.append(model.predict(x_test))
        total_complexity += int(selected["complexity"])
        expression = model.get_model_string(
            model.model_, precision=12, names=names
        ).replace("^", "**")
        equation_lines.append("u%d_t = %s" % (target_index, expression))
        selected_front.append(
            {
                "target": "u%d_t" % target_index,
                "validation_nmse": float(-best[1]),
                "complexity": int(selected["complexity"]),
            }
        )
        models.append(model)
    validation_prediction = np.stack(validation_predictions, axis=-1)
    test_prediction = np.stack(test_predictions, axis=-1).reshape(
        pieces["test"]["du_true"].shape
    )
    validation_nmse = _nmse(y_validation, validation_prediction)
    derivative_nmse = _nmse(pieces["test"]["du_true"], test_prediction)
    trajectory_nmse = None
    if data_type == "ode":
        def predict_ode(states):
            inputs = np.array(states, dtype=np.float64, order="F", copy=True)
            return np.stack([model.predict(inputs) for model in models], axis=-1)

        trajectory_nmse = _trajectory_nmse(
            predict_ode,
            pieces["test"]["t"],
            pieces["test"]["u"],
        )
    selected_parameters = dict(parameters)
    selected_parameters["random_state"] = int(attempt["seed"])
    selected_parameters["pareto_selection"] = selected_front
    return {
        "selected_hyperparameters": _json_safe(selected_parameters),
        "discovered_equation": "\n".join(equation_lines),
        "coefficients": [],
        "validation_nmse": validation_nmse,
        "derivative_nmse": derivative_nmse,
        "trajectory_extrapolation_nmse_ode": trajectory_nmse,
        "model_complexity": int(total_complexity),
    }


def _trajectory_nmse(predictor, t_test, u_test):
    times = np.asarray(t_test, dtype=np.float64).reshape(-1)
    truth = np.asarray(u_test, dtype=np.float64)
    if truth.ndim != 2 or len(times) < 2:
        return None

    def rhs(_time, state):
        prediction = np.asarray(predictor(np.asarray(state).reshape(1, -1)), dtype=np.float64)
        derivative = prediction.reshape(-1)
        if derivative.shape != state.shape or not np.all(np.isfinite(derivative)):
            raise FloatingPointError("invalid trajectory derivative")
        return derivative

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


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _peak_rss_mb():
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _base_payload(spec_hash, runner_hash, status, started, elapsed):
    return {
        "schema_version": "mdbench-runner-payload-v1",
        "spec_hash": spec_hash,
        "runner_sha256": runner_hash,
        "status": status,
        "split_indices": None,
        "selected_hyperparameters": {},
        "discovered_equation": None,
        "coefficients": [],
        "validation_nmse": None,
        "derivative_nmse": None,
        "trajectory_extrapolation_nmse_ode": None,
        "model_complexity": None,
        "wall_time_seconds": float(elapsed),
        "peak_rss_mb": _peak_rss_mb(),
        "failure_reason": None,
        "started_unix_seconds": float(started),
    }


def run(spec_path, data_path, output_path):
    started = time.time()
    spec, spec_hash, runner_hash = _load_and_validate_spec(
        spec_path,
        Path(__file__).resolve(),
        data_path,
    )
    timeout_seconds = int(spec["method"]["max_seconds_per_attempt"])
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_seconds)
    payload = _base_payload(spec_hash, runner_hash, "failed", started, 0.0)
    try:
        with np.load(data_path, allow_pickle=False) as archive:
            data = {key: archive[key] for key in archive.files}
        n_time = int(np.asarray(data["t"]).size)
        split = _split_indices(n_time, spec["split_policy"])
        payload["split_indices"] = split
        pieces, spatial_grids, time_axis = _split_data(data, split)
        method_id = spec["attempt"]["method_id"]
        if method_id == "sindy_or_pdefind":
            result = _run_sparse_baseline(spec, pieces, spatial_grids, time_axis)
        elif method_id == "stability_sindy":
            result = _run_stability_candidate(spec, pieces, spatial_grids, time_axis)
        elif method_id == "weak_stability_sindy":
            result = _run_weak_stability_candidate(
                spec,
                pieces,
                spatial_grids,
                time_axis,
            )
        elif method_id == "operon_gp":
            result = _run_operon(spec, pieces, spatial_grids, time_axis)
        else:
            raise ValueError("unsupported frozen method: %s" % method_id)
        payload.update(result)
        payload.update(
            {
                "status": "succeeded",
                "split_indices": split,
                "failure_reason": None,
            }
        )
    except AttemptTimeout as exc:
        payload.update({"status": "timed_out", "failure_reason": str(exc)})
    except Exception as exc:  # terminal scientific failure must be persisted
        traceback.print_exc(file=sys.stderr)
        payload.update(
            {
                "status": "failed",
                "failure_reason": "%s: %s" % (type(exc).__name__, exc),
            }
        )
    finally:
        signal.alarm(0)
        payload["wall_time_seconds"] = float(time.time() - started)
        payload["peak_rss_mb"] = _peak_rss_mb()
        _write_payload(output_path, _json_safe(payload))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.spec, arguments.data, arguments.output)
