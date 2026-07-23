#!/usr/bin/env python3
"""Deterministic in-image checks for the two task-260 ODE mechanism families."""

import numpy as np
import runner


def _pieces():
    t = np.linspace(0.0, 12.0, 240)
    clean = np.stack((np.sin(t), np.cos(t)), axis=-1)
    noise = 0.01 * np.stack((np.sin(17.0 * t), np.cos(19.0 * t)), axis=-1)
    u = clean + noise
    du = np.stack((np.cos(t), -np.sin(t)), axis=-1)
    split = runner._split_indices(
        len(t),
        {
            "train": [0.0, 0.64],
            "validation": [0.64, 0.8],
            "test": [0.8, 1.0],
        },
    )
    return runner._split_data({"t": t, "u": u, "du": du}, split)


def _ensemble_parameters():
    return {
        "campaign_candidate_kind": "noise_conditioned_ensemble",
        "mechanisms": [
            "noise_conditioned_savgol",
            "bootstrap_coefficient_ensemble",
            "median_coefficient_aggregation",
        ],
        "savgol_windows": [5, 9, 15, 21],
        "savgol_polyorder": 3,
        "optimizer_threshold": [1e-5, 1e-3, 1e-2],
        "poly_order": [1, 2],
        "ensemble_repetitions": 5,
        "subsample_fraction": 0.8,
        "noise_conditioning": True,
        "smoothing": True,
        "ensemble": True,
    }


def _spline_parameters():
    return {
        "campaign_candidate_kind": "spline_group_sparse",
        "mechanisms": [
            "cubic_smoothing_spline_derivative",
            "cross_output_group_sparse_projection",
        ],
        "spline_smoothing_scales": [0.0, 0.25, 1.0],
        "optimizer_threshold": [1e-5, 1e-3, 1e-2],
        "poly_order": [1, 2],
        "group_sparse": True,
        "spline_derivative": True,
        "shared_support": True,
    }


def _assert_result(result, kind):
    assert np.isfinite(result["validation_nmse"])
    assert np.isfinite(result["derivative_nmse"])
    assert result["trajectory_extrapolation_nmse_ode"] is not None
    assert np.isfinite(result["trajectory_extrapolation_nmse_ode"])
    assert result["model_complexity"] >= 0
    assert result["selected_hyperparameters"]["campaign_candidate_kind"] == kind
    assert result["discovered_equation"]


def main():
    pieces, spatial_grids, time_axis = _pieces()
    ensemble = runner._run_noise_conditioned_ensemble(
        {
            "attempt": {"data_type": "ode", "seed": 131},
            "method": {"parameters": _ensemble_parameters()},
        },
        pieces,
        spatial_grids,
        time_axis,
    )
    _assert_result(ensemble, "noise_conditioned_ensemble")

    spline = runner._run_spline_group_sparse(
        {
            "attempt": {"data_type": "ode", "seed": 149},
            "method": {"parameters": _spline_parameters()},
        },
        pieces,
        spatial_grids,
        time_axis,
    )
    _assert_result(spline, "spline_group_sparse")
    print("campaign runner self-test passed for both task-260 ODE mechanisms")


if __name__ == "__main__":
    main()
