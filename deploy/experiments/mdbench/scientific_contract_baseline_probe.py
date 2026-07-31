"""Offline implementation probe for the Task 266 domain baselines.

This script is mounted read-only into the pinned MDBench image.  It uses only
synthetic equations and never opens an official benchmark artifact.
"""

import hashlib
import inspect
import json
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _nmse(truth, prediction):
    expected = np.asarray(truth, dtype=np.float64)
    observed = np.asarray(prediction, dtype=np.float64).reshape(expected.shape)
    if not np.all(np.isfinite(observed)):
        raise FloatingPointError("baseline probe produced a non-finite prediction")
    return float(np.sum((expected - observed) ** 2) / (np.sum(expected**2) + 1e-10))


def _probe_operon():
    import mdbench.algorithms.sr.operon.regressor as operon_module

    parameters = dict(operon_module.default_hyper_params)
    parameters.update(
        {
            "generations": 10,
            "max_evaluations": 2000,
            "population_size": 50,
            "pool_size": 50,
            "max_time": 5,
            "random_state": 17,
        }
    )
    operon_module.default_hyper_params = parameters
    states = np.linspace(-2.0, 2.0, 80, dtype=np.float64).reshape(-1, 1)
    derivatives = (-0.7 * states[:, 0] + 0.2 * states[:, 0] ** 2).reshape(-1, 1)
    estimator = operon_module.Estimator(
        n_jobs=1,
        symbol_names=["u0"],
        target_names=["u0"],
    )
    estimator.fit(np.arange(len(states)), states, derivatives)
    prediction = estimator.predict(None, states)
    equation = estimator.to_str()
    error = _nmse(derivatives, prediction)
    if error >= 0.05 or "u0_t" not in equation or not np.isfinite(error):
        raise RuntimeError("bounded Operon synthetic probe did not recover executable dynamics")
    return {
        "baseline_id": "operon_gp_ode",
        "data_type": "ode",
        "dependency": "pyoperon",
        "dependency_version": version("pyoperon"),
        "implementation_module": "mdbench.algorithms.sr.operon.regressor",
        "implementation_sha256": _sha256_file(inspect.getsourcefile(operon_module)),
        "fit_predict_nmse": error,
        "equation": equation,
        "model_complexity": int(estimator.complexity()),
        "synthetic_only": True,
        "passed": True,
    }


def _heat_state(spatial_dimensions, points, time_points, diffusivity):
    axes = [
        np.linspace(0.0, 2.0 * np.pi, points, dtype=np.float64)
        for _ in range(spatial_dimensions)
    ]
    times = np.linspace(0.0, 1.0, time_points, dtype=np.float64)
    grids = np.meshgrid(*(axes + [times]), indexing="ij")
    state = np.exp(-diffusivity * spatial_dimensions * grids[-1])
    for grid in grids[:-1]:
        state = state * np.sin(grid)
    derivative = -diffusivity * spatial_dimensions * state
    return axes, times, state[..., np.newaxis], derivative[..., np.newaxis]


def _probe_pdefind(spatial_dimensions):
    import mdbench.algorithms.pde.pdefind.regressor as pdefind_module

    axes, times, states, derivatives = _heat_state(
        spatial_dimensions,
        9 if spatial_dimensions == 2 else 5,
        9,
        0.15,
    )
    estimator = pdefind_module.Estimator(
        basis_functions=["polynomial"],
        optimizer_threshold=1e-5,
        derivative_order=2,
        poly_order=1,
        alpha=1e-8,
        target_names=["u0"],
        n_jobs=1,
    )
    estimator.set_spatial_grid(axes)
    estimator.fit(times, states, derivatives)
    prediction = estimator.predict(times, states)
    equation = estimator.to_str()
    error = _nmse(derivatives, prediction)
    if prediction.shape != states.shape or error >= 1e-8 or "u0_t" not in equation:
        raise RuntimeError("PDE-FIND multidimensional fit/predict probe failed")
    return {
        "baseline_id": "pdefind_pde",
        "data_type": "pde",
        "spatial_dimensions": spatial_dimensions,
        "dependency": "pysindy",
        "dependency_version": version("pysindy"),
        "implementation_module": "mdbench.algorithms.pde.pdefind.regressor",
        "implementation_sha256": _sha256_file(inspect.getsourcefile(pdefind_module)),
        "fit_predict_nmse": error,
        "prediction_shape": list(prediction.shape),
        "equation": equation,
        "model_complexity": int(estimator.complexity()),
        "synthetic_only": True,
        "passed": True,
    }


def main():
    probes = [_probe_operon(), _probe_pdefind(2), _probe_pdefind(3)]
    payload = {
        "probe_version": "task266-domain-baseline-probe-v1",
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "dependencies": {
            "numpy": version("numpy"),
            "pyoperon": version("pyoperon"),
            "pysindy": version("pysindy"),
            "scikit_learn": version("scikit-learn"),
            "scipy": version("scipy"),
        },
        "network_used": False,
        "official_artifact_reads": 0,
        "probes": probes,
        "passed": all(item["passed"] for item in probes),
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
