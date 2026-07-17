#!/usr/bin/env python3
"""Deterministic in-image checks for the frozen weak-form candidate path."""

import numpy as np
import runner


def _parameters():
    return {
        "mechanisms": ["weak_form_projection", "bootstrap_support_stability"],
        "pysindy_revision": "4c32d2603cbf1aa476efae72bc78436cb1e6fc75",
        "weak_library": "WeakPDELibrary",
        "weak_subdomains": 24,
        "bootstrap_repetitions": 6,
        "subsample_fraction": 0.75,
        "selection_frequency": 0.5,
        "optimizer_threshold": [1e-5, 1e-3],
        "poly_order": [1, 2],
        "pde_derivative_order": [1, 2],
    }


def _run_case(data_type, data):
    split = runner._split_indices(
        len(data["t"]),
        {
            "train": [0.0, 0.64],
            "validation": [0.64, 0.8],
            "test": [0.8, 1.0],
        },
    )
    pieces, spatial_grids, time_axis = runner._split_data(data, split)
    result = runner._run_weak_stability_candidate(
        {
            "attempt": {"data_type": data_type, "seed": 13},
            "method": {"parameters": _parameters()},
        },
        pieces,
        spatial_grids,
        time_axis,
    )
    assert np.isfinite(result["validation_nmse"])
    assert np.isfinite(result["derivative_nmse"])
    assert result["model_complexity"] >= 0
    assert result["selected_hyperparameters"]["mechanisms"] == [
        "weak_form_projection",
        "bootstrap_support_stability",
    ]
    assert result["selected_hyperparameters"]["normalize_columns"] is True
    assert result["discovered_equation"]
    return result


def main():
    t = np.linspace(0.0, 6.0, 120)
    ode_u = np.stack((np.sin(t), np.cos(t)), axis=-1)
    ode_du = np.stack((np.cos(t), -np.sin(t)), axis=-1)
    ode_result = _run_case("ode", {"t": t, "u": ode_u, "du": ode_du})
    assert ode_result["derivative_nmse"] < 1e-8
    assert ode_result["trajectory_extrapolation_nmse_ode"] < 1e-8
    assert ode_result["model_complexity"] == 4

    x = np.linspace(0.0, 2.0 * np.pi, 96)
    x_grid, t_grid = np.meshgrid(x, t, indexing="ij")
    pde_u = np.sin(x_grid - t_grid)[..., np.newaxis]
    pde_du = -np.cos(x_grid - t_grid)[..., np.newaxis]
    pde_result = _run_case("pde", {"t": t, "x": x, "u": pde_u, "du": pde_du})
    assert pde_result["derivative_nmse"] < 1e-5
    assert pde_result["model_complexity"] == 2
    print("weak runner self-test passed for synthetic ODE and 1D PDE")


if __name__ == "__main__":
    main()
