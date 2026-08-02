"""Granular feedback: the candidate must see its OWN fit diagnostics.

`arXiv:2605.29184` (IGSR) established that coarse feedback cannot tell a model
WHICH part of a proposal is responsible for an outcome. The Harness already
returned per-sentinel metrics, but it withheld the candidate's own fit
diagnostics, so a candidate was told `primary_term_support` failed without being
able to see that it had selected 12 terms from 12 features on 102 samples.

Live run `v16` revision-05 shows exactly why that matters:

    ode  samples=6     features=6   terms=2   gap=-6.0e-33  passed=True
    pde  samples=102   features=6   terms=6   gap= 1.4e-01  passed=False
    pde  samples=102   features=12  terms=12  gap= 1.5e-02  passed=False

The passing unit used 2 of 6 features with no generalization gap. The failing
units consumed every available feature and generalized worse. That is the
signature of fitting the training data instead of recovering the law, and it is
invisible from failure codes alone.

This forwards only the candidate's OWN metadata. It reveals nothing about the
hidden expected equations, so it cannot be used to reverse-engineer the answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autoresearch.competition.scientific_contract_harness import (
    ScientificContractRevision,
    _condensed_observation,
)

RUN_ROOT = (
    Path(__file__).resolve().parents[3]
    / "runs"
    / "manual-live"
    / "task2662-scientific-contract-harness-v16"
)


def _condensed() -> dict[str, Any]:
    revision = ScientificContractRevision.model_validate_json(
        (RUN_ROOT / "revisions" / "revision-05" / "revision.json").read_text(
            encoding="utf-8"
        )
    )
    condensed = _condensed_observation(RUN_ROOT, revision)
    assert condensed is not None
    return condensed


def _results() -> list[dict[str, Any]]:
    key = "results_without_ids_expected_values_or_expected_equations"
    return _condensed()[key]


def test_own_fit_diagnostics_are_forwarded() -> None:
    results = [item for item in _results() if "your_own_fit_diagnostics" in item]

    assert results, "no sentinel forwarded the candidate's own diagnostics"
    for item in results:
        own = item["your_own_fit_diagnostics"]
        assert own["training_sample_count"] > 0
        assert own["design_feature_count"] > 0
        assert own["selected_term_count"] > 0
        assert isinstance(own["training_nmse"], float)


def test_generalization_gap_is_reported() -> None:
    """Term count alone cannot show that a fit failed to generalize."""

    gaps = [
        item["your_train_to_prediction_nmse_gap"]
        for item in _results()
        if "your_train_to_prediction_nmse_gap" in item
    ]

    assert gaps
    assert all(isinstance(value, float) for value in gaps)


def test_overfitting_signature_is_visible_in_the_feedback() -> None:
    """The passing unit is sparse; the failing units consume every feature."""

    passing = [
        item
        for item in _results()
        if item.get("passed") and "your_own_fit_diagnostics" in item
    ]
    failing = [
        item
        for item in _results()
        if item.get("passed") is False and "your_own_fit_diagnostics" in item
    ]

    assert passing and failing

    for item in passing:
        own = item["your_own_fit_diagnostics"]
        assert own["selected_term_count"] < own["design_feature_count"]

    # At least one failing unit must show a saturated design, which is the
    # observation the candidate previously could not make.
    assert any(
        item["your_own_fit_diagnostics"]["selected_term_count"]
        >= item["your_own_fit_diagnostics"]["design_feature_count"]
        for item in failing
    )


def test_feedback_never_leaks_sentinel_identity_or_expected_equations() -> None:
    """Result-blind boundary: only the candidate's own numbers may be returned.

    Checks the per-sentinel payloads rather than the whole document, because the
    container key is deliberately named
    `results_without_ids_expected_values_or_expected_equations` and would
    otherwise match its own guard.
    """

    flat = json.dumps(_results()).casefold()

    for marker in (
        "sentinel_id",
        "ode-linear-2field",
        "pde-advection-1d",
        "pde-diffusion-1d",
        "pde-heat-3d",
        "expected_equations",
        "expected_derivative",
        "fixture_hash",
    ):
        assert marker not in flat, f"feedback leaked {marker!r}"


def test_forwarded_keys_are_an_explicit_allowlist() -> None:
    """A new observation field must not reach the model just by being added."""

    permitted = {
        "data_type",
        "spatial_dimensions",
        "field_count",
        "query_shape",
        "primary_prediction_nmse",
        "shuffled_prediction_nmse",
        "shuffle_nmse_ratio",
        "zero_null_relative_improvement",
        "primary_term_support_f1",
        "alternative_term_support_f1",
        "primary_coefficient_relative_error",
        "alternative_coefficient_relative_error",
        "maximum_equation_prediction_delta",
        "artifact_changed_on_alternative_training",
        "equation_changed_on_alternative_training",
        "maximum_fit_seconds",
        "maximum_predict_seconds",
        "nonfinite_metrics",
        "failure_codes",
        "error_type",
        "error_message",
        "passed",
        "your_own_fit_diagnostics",
        "your_train_to_prediction_nmse_gap",
    }

    for item in _results():
        unexpected = set(item) - permitted
        assert not unexpected, f"unexpected forwarded keys: {sorted(unexpected)}"


def test_solver_id_is_echoed_so_the_model_can_compare_its_own_attempts() -> None:
    solver_ids = {
        item["your_own_fit_diagnostics"].get("solver_id")
        for item in _results()
        if "your_own_fit_diagnostics" in item
    }

    assert solver_ids
    assert all(isinstance(value, str) and value for value in solver_ids)
