"""Fairness: the contract must disclose the operator used to score equations.

Live run `task2662-scientific-contract-harness-v15` exposed an unpassable gate.
The trusted evaluator re-derives every spatial derivative itself, using a spectral
FFT operator, but the contract disclosed only that the grid was periodic with a
duplicated endpoint. Candidates therefore fitted coefficients against a finite
difference stencil and were then scored with a different derivative operator.

The observed consequence, from `revision-08/harness/observation.json`, was
training NMSE far above the zero null on every PDE sentinel:

    pde-advection-1d            train_nmse 2.319e+01   F1 0.00
    pde-diffusion-1d            train_nmse 3.402e+01   F1 0.00
    pde-advection-diffusion-2d  train_nmse 1.482e+01   F1 0.00
    pde-heat-3d                 train_nmse 2.095e+01   F1 0.00
    pde-diffusion-1d-2field     train_nmse 9.077e+00   F1 0.00

Withholding the scoring operator made these failures uninformative about
scientific quality, which is the same class of defect as the Task 266.1.1 sentinel
identifiability erratum: the Harness was punishing something it had not specified.

This does NOT hand the candidate a method. It still chooses its own library,
features, estimator, and sparsification. It is only told how its own output will
be measured.
"""

from __future__ import annotations

import ast
from pathlib import Path

from autoresearch.competition.scientific_contract_harness import (
    build_scientific_interface_contract,
)

RUNNER_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "experiments"
    / "mdbench"
    / "scientific_contract_harness_runner.py"
)


def _disclosure() -> dict[str, str]:
    contract = build_scientific_interface_contract()
    return contract["evaluator_spatial_derivative_operator"]


def test_contract_names_the_scoring_operator() -> None:
    disclosure = _disclosure()

    assert disclosure["method"] == "spectral_fft_on_the_periodic_axis"
    assert "fft" in disclosure["detail"].casefold()


def test_disclosure_warns_against_fitting_a_different_operator() -> None:
    """This is the exact mistake that produced the v15 PDE failures."""

    implication = _disclosure()["implication"].casefold()

    assert "finite difference" in implication


def test_disclosure_states_the_axis_requirements() -> None:
    """The runner rejects short or non-uniform axes, so the candidate must know."""

    requirements = _disclosure()["axis_requirements"].casefold()

    assert "uniform" in requirements
    assert "five" in requirements


def test_disclosure_matches_the_runner_implementation() -> None:
    """Parity guard: the disclosed operator must be the one actually used.

    Prevents this disclosure from drifting away from the runner the way the
    equation key lists once did (Task 267.1).
    """

    source = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    # The evaluator differentiates spectrally, so that helper must exist...
    assert "_spectral_derivative" in functions
    # ...and the prediction path must actually call it.
    prediction = source.split("def _trusted_equation_prediction", 1)[-1]
    assert "_spectral_derivative(" in prediction
    # The disclosed mechanics must be the ones implemented.
    spectral = source.split("def _spectral_derivative", 1)[-1][:2000]
    assert "fft" in spectral
    assert "fftfreq" in spectral


def test_periodic_endpoint_convention_is_still_disclosed() -> None:
    """The duplicated endpoint matters for the FFT period; keep stating it."""

    contract = build_scientific_interface_contract()

    assert "duplicated endpoint" in contract["periodic_grid"]
