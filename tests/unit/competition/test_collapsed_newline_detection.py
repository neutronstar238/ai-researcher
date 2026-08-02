"""Task 267.2 follow-up: diagnose source whose newline escapes were lost.

Observed live in run `task2662-scientific-contract-harness-v10`: the model emitted
`source_text` with a bare letter `n` where an escaped newline belonged, so 15,767
bytes of otherwise reasonable PySINDy code parsed as ONE line and `ast.parse`
failed at line 1 with the unhelpful message "invalid syntax".

A strict JSON schema cannot catch this, because `n` and an escaped newline are
both valid string content. Two things therefore have to happen: the failure must
be classified as technical so it does not consume the scientific revision budget,
and the model must receive an actionable diagnosis rather than "invalid syntax".
"""

from __future__ import annotations

from autoresearch.competition.scientific_contract_harness import (
    _looks_like_collapsed_newlines,
    build_scientific_interface_contract,
    classify_revision_failure_kind,
    review_scientific_contract_source,
)

# Shape taken from the real v10 candidate's opening bytes.
COLLAPSED = (
    "import numpy as npnimport pysindynfrom pysindy.feature_library import "
    "PolynomialLibrarynfrom scipy.ndimage import uniform_filter1dnimport jsonnn"
    "def _decode_tensor(t):n    return np.asarray(t['values'])nn"
    "def fit_equations(payload):n    return {}nn"
    "def predict_derivative(payload):n    return {}n" + ("n# padding comment" * 40)
)

HEALTHY = '''import math


def fit_equations(payload):
    """Fit on train-only context."""
    return {"equations": []}


def predict_derivative(payload):
    """Evaluate the frozen artifact only."""
    return {"schema_version": "scientific-predict-response-v1"}
'''


def test_detector_recognises_collapsed_newlines() -> None:
    assert _looks_like_collapsed_newlines(COLLAPSED) is True


def test_detector_leaves_healthy_source_alone() -> None:
    assert _looks_like_collapsed_newlines(HEALTHY) is False


def test_detector_ignores_short_fragments() -> None:
    """A short string must not be flagged just for lacking line breaks."""

    assert _looks_like_collapsed_newlines("import osnimport sys") is False


def test_review_reports_an_actionable_diagnosis() -> None:
    """The model must learn WHAT to fix, not just that syntax was invalid."""

    review = review_scientific_contract_source(COLLAPSED)

    assert not review.approved
    syntax_findings = [item for item in review.findings if item.code == "syntax_error"]
    assert syntax_findings, "collapsed source must produce a syntax finding"
    message = syntax_findings[0].message
    assert "newline escapes" in message
    assert "backslash-n" in message


def test_healthy_source_passes_review() -> None:
    assert review_scientific_contract_source(HEALTHY).approved is True


def test_collapsed_newline_failure_does_not_consume_scientific_budget() -> None:
    """The science never ran, so charging the scientific budget repeats v1-v9."""

    assert classify_revision_failure_kind(["static:syntax_error"]) == "technical"


def test_contract_states_the_newline_escaping_requirement() -> None:
    """The requirement must be explicit, since a strict schema cannot enforce it."""

    transport = build_scientific_interface_contract()["source_transport_contract"]

    assert "source_text_newline_encoding" in transport
    assert "backslash-n" in transport["source_text_newline_encoding"]
    assert "source_text_self_check_before_responding" in transport
