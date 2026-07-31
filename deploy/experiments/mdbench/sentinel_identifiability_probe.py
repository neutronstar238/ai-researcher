#!/usr/bin/env python3
"""Offline rank/support audit for Task 266 analytic sentinels.

The complete probe input arrives on stdin.  No benchmark artifact or network
resource is mounted.  The script evaluates whether every frozen expected term
is identifiable inside a candidate-neutral linear state/first-/second-spatial-
derivative feature universe.
"""

import hashlib
import json
import math
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _spectral_derivative(values, coordinates, axis, order):
    coordinate_array = np.asarray(coordinates, dtype=np.float64)
    if coordinate_array.ndim != 1 or coordinate_array.size < 5:
        raise ValueError("periodic sentinel axis is too short")
    differences = np.diff(coordinate_array)
    if not np.allclose(differences, differences[0], rtol=1e-12, atol=1e-12):
        raise ValueError("periodic sentinel axis is not uniform")
    period = float(coordinate_array[-1] - coordinate_array[0])
    if not math.isfinite(period) or period <= 0:
        raise ValueError("periodic sentinel axis has an invalid period")
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


def _factor_label(factor):
    if int(factor.get("power", 1)) != 1:
        raise ValueError("identifiability universe supports only first-power factors")
    axes = tuple(factor.get("derivative_axes", []))
    if not axes:
        return str(factor["field"])
    return f'{factor["field"]}_{"".join(axes)}'


def _feature_universe(fixture):
    shape = tuple(int(item) for item in fixture["train_state"]["shape"])
    state = np.asarray(
        fixture["train_state"]["values"],
        dtype=np.float64,
    ).reshape(shape)
    field_names = tuple(str(item) for item in fixture["field_names"])
    spatial_axes = [
        name
        for name in ("x", "y", "z")
        if name in fixture["spatial_coordinates"]
    ]
    labels = ["1"]
    columns = [np.ones(state.shape[:-1], dtype=np.float64).reshape(-1)]
    for field_index, field_name in enumerate(field_names):
        field_values = state[..., field_index]
        labels.append(field_name)
        columns.append(field_values.reshape(-1))
        for axis_index, axis_name in enumerate(spatial_axes):
            first = _spectral_derivative(
                field_values,
                fixture["spatial_coordinates"][axis_name],
                axis_index,
                1,
            )
            second = _spectral_derivative(
                field_values,
                fixture["spatial_coordinates"][axis_name],
                axis_index,
                2,
            )
            labels.extend(
                [
                    f"{field_name}_{axis_name}",
                    f"{field_name}_{axis_name}{axis_name}",
                ]
            )
            columns.extend([first.reshape(-1), second.reshape(-1)])
    return labels, np.column_stack(columns)


def _expected_support(equation):
    support = []
    coefficients = []
    intercept = float(equation.get("intercept", 0.0))
    if intercept != 0.0:
        support.append("1")
        coefficients.append(intercept)
    for term in equation["terms"]:
        factors = term["factors"]
        if len(factors) != 1:
            raise ValueError("identifiability universe does not contain product terms")
        support.append(_factor_label(factors[0]))
        coefficients.append(float(term["coefficient"]))
    if len(support) != len(set(support)):
        raise ValueError("expected equation repeats a feature support")
    return support, coefficients


def _relative_nmse(expected, observed):
    numerator = float(np.sum((expected - observed) ** 2))
    denominator = float(np.sum(expected**2)) + 1e-30
    return numerator / denominator


def _audit_target(fixture, labels, matrix, target_index, equation):
    derivative_shape = tuple(int(item) for item in fixture["train_derivative"]["shape"])
    derivatives = np.asarray(
        fixture["train_derivative"]["values"],
        dtype=np.float64,
    ).reshape(derivative_shape)
    target = derivatives[..., target_index].reshape(-1)
    support, expected_coefficients = _expected_support(equation)
    label_to_index = {label: index for index, label in enumerate(labels)}
    missing = sorted(set(support) - set(label_to_index))
    if missing:
        raise ValueError(f"expected support is outside the audit universe: {missing}")

    norms = np.linalg.norm(matrix, axis=0)
    nonzero_indices = np.flatnonzero(norms > 1e-12)
    nonzero_labels = [labels[int(index)] for index in nonzero_indices]
    normalized = matrix[:, nonzero_indices] / norms[nonzero_indices]
    singular_values = np.linalg.svd(normalized, compute_uv=False)
    tolerance = (
        max(normalized.shape)
        * np.finfo(np.float64).eps
        * (float(singular_values[0]) if singular_values.size else 0.0)
    )
    rank = int(np.sum(singular_values > tolerance))
    _u, _s, right = np.linalg.svd(normalized, full_matrices=True)
    null_space = right[rank:, :]

    active_nonzero_indices = []
    for label in support:
        if label not in nonzero_labels:
            raise ValueError(
                f"expected support has a numerically zero column: {label}"
            )
        active_nonzero_indices.append(nonzero_labels.index(label))
    maximum_active_null_component = 0.0
    if null_space.size:
        maximum_active_null_component = float(
            np.max(np.abs(null_space[:, active_nonzero_indices]))
        )

    active_original_indices = [label_to_index[label] for label in support]
    active_matrix = matrix[:, active_original_indices]
    fitted_coefficients, _residuals, _rank, _singular = np.linalg.lstsq(
        active_matrix,
        target,
        rcond=None,
    )
    reconstruction = active_matrix @ fitted_coefficients
    reconstruction_nmse = _relative_nmse(target, reconstruction)
    relative_errors = [
        abs(float(observed) - float(expected)) / max(abs(float(expected)), 1e-12)
        for observed, expected in zip(  # noqa: B905 - pinned image is Python 3.9
            fitted_coefficients,
            expected_coefficients,
        )
    ]
    coefficient_error = max(relative_errors, default=0.0)

    leave_out_ratios = []
    for active_index in active_original_indices:
        competitor_indices = [
            index
            for index in nonzero_indices.tolist()
            if int(index) != int(active_index)
        ]
        competitor = matrix[:, competitor_indices]
        competitor_coefficients, _residuals, _rank, _singular = np.linalg.lstsq(
            competitor,
            target,
            rcond=None,
        )
        competitor_prediction = competitor @ competitor_coefficients
        leave_out_ratios.append(_relative_nmse(target, competitor_prediction))
    minimum_leave_out_ratio = min(leave_out_ratios, default=1.0)
    active_condition_number = float(np.linalg.cond(active_matrix))
    active_identifiable = bool(
        maximum_active_null_component <= 1e-8
        and minimum_leave_out_ratio > 1e-10
    )
    passed = bool(
        active_identifiable
        and reconstruction_nmse <= 1e-20
        and coefficient_error <= 1e-8
        and math.isfinite(active_condition_number)
        and active_condition_number <= 1e10
    )
    return {
        "target": str(equation["target"]),
        "feature_labels": labels,
        "feature_count": int(len(labels)),
        "nonzero_feature_count": int(len(nonzero_indices)),
        "feature_matrix_rank": rank,
        "expected_support": support,
        "expected_coefficients": expected_coefficients,
        "fitted_expected_support_coefficients": [
            float(item) for item in fitted_coefficients
        ],
        "expected_reconstruction_nmse": float(reconstruction_nmse),
        "maximum_expected_coefficient_relative_error": float(coefficient_error),
        "maximum_active_null_component": float(maximum_active_null_component),
        "minimum_leave_active_out_nmse": float(minimum_leave_out_ratio),
        "expected_support_condition_number": active_condition_number,
        "expected_support_identifiable": active_identifiable,
        "passed": passed,
    }


def _audit_fixture(fixture):
    labels, matrix = _feature_universe(fixture)
    equations = fixture["expected_equations"]
    targets = [
        _audit_target(fixture, labels, matrix, index, equation)
        for index, equation in enumerate(equations)
    ]
    return {
        "sentinel_id": str(fixture["sentinel_id"]),
        "fixture_hash": str(fixture["fixture_hash"]),
        "target_audits": targets,
        "passed": bool(targets and all(item["passed"] for item in targets)),
    }


def main():
    payload = json.loads(sys.stdin.read())
    if payload.get("schema_version") != "sentinel-identifiability-probe-input-v1":
        raise ValueError("identifiability probe input schema changed")
    if payload.get("expected_runner_sha256") != _file_hash(__file__):
        raise ValueError("identifiability probe runner bytes changed")
    original = [_audit_fixture(item) for item in payload["original_fixtures"]]
    corrected = [_audit_fixture(item) for item in payload["corrected_fixtures"]]
    output = {
        "schema_version": "sentinel-identifiability-probe-output-v1",
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "dependencies": {"numpy": version("numpy")},
        "network_used": False,
        "official_artifact_reads": 0,
        "original_audits": original,
        "corrected_audits": corrected,
    }
    print(json.dumps(output, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
