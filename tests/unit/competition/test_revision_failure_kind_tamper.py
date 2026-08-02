"""Task 267.2: a scientific failure must not be relabelled as technical.

The refunded "technical" bucket is the only path that does not consume the
scientific revision budget, so it is the one an over-eager loop would abuse.
The persisted classification must therefore be recomputable from the exact
failure codes and rejected when it disagrees.
"""

from __future__ import annotations

import pytest

from autoresearch.competition.scientific_contract_harness import (
    classify_revision_failure_kind,
)


def test_scientific_failure_cannot_be_relabelled_technical() -> None:
    """The classifier is the single source of truth for budget accounting."""

    codes = ["synthetic-1:zero_null_improvement"]
    assert classify_revision_failure_kind(codes) == "scientific"
    # A caller claiming "technical" for these codes contradicts the classifier,
    # which is exactly what ScientificContractRevision rejects.
    assert classify_revision_failure_kind(codes) != "technical"


def test_format_fault_cannot_be_inflated_to_scientific() -> None:
    """A format fault must not be counted as a scientific verdict either."""

    codes = ["synthetic-1:contract_execution_error"]
    assert classify_revision_failure_kind(codes) == "technical"
    assert classify_revision_failure_kind(codes) != "scientific"


def test_passing_revision_has_no_failure_kind() -> None:
    assert classify_revision_failure_kind(()) == "none"


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["synthetic-1:contract_execution_error"], "technical"),
        (["synthetic-1:primary_term_support"], "scientific"),
        ([], "none"),
    ],
)
def test_classification_is_deterministic(codes: list[str], expected: str) -> None:
    """Repeated calls must return the same verdict for an audit replay."""

    assert classify_revision_failure_kind(codes) == expected
    assert classify_revision_failure_kind(codes) == expected
