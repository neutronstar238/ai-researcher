"""Task 267.2: format faults must not consume the scientific revision budget.

Historical defect: a schema `ContractError` was recorded as
`synthetic-N:contract_execution_error` and counted as a scientific failure, so
all six bounded model-only revisions were spent on formatting across
`task2662-scientific-contract-harness-v1`..`v9` while `fit_call_count` stayed 0.
A format fault means no scientific verdict was ever reached.
"""

from __future__ import annotations

import pytest

from autoresearch.competition.scientific_contract_harness import (
    _SCIENTIFIC_FAILURE_SUFFIXES,
    _TECHNICAL_FAILURE_SUFFIXES,
    classify_revision_failure_kind,
)


def test_no_failure_is_classified_as_none() -> None:
    assert classify_revision_failure_kind([]) == "none"


@pytest.mark.parametrize(
    "codes",
    [
        ["synthetic-1:contract_execution_error"],
        [f"synthetic-{index}:contract_execution_error" for index in range(1, 7)],
        ["harness:no_observation"],
    ],
)
def test_format_only_failures_are_technical(codes: list[str]) -> None:
    """These are exactly the codes that consumed the v1..v9 budget."""

    assert classify_revision_failure_kind(codes) == "technical"


@pytest.mark.parametrize(
    "code",
    [
        "synthetic-1:zero_null_improvement",
        "synthetic-1:train_shuffle_degradation",
        "synthetic-1:equation_prediction_consistency",
        "synthetic-1:artifact_training_dependence",
        "synthetic-1:primary_coefficient_recovery",
    ],
)
def test_real_scientific_verdicts_are_scientific(code: str) -> None:
    assert classify_revision_failure_kind([code]) == "scientific"


def test_mixed_failure_is_scientific_because_a_verdict_was_reached() -> None:
    """Precedence: any scientific failure makes the whole revision scientific."""

    codes = [
        "synthetic-1:contract_execution_error",
        "synthetic-2:zero_null_improvement",
    ]
    assert classify_revision_failure_kind(codes) == "scientific"


def test_unknown_code_fails_closed_as_scientific() -> None:
    """An unrecognized code must never silently refund the budget."""

    assert classify_revision_failure_kind(["static:blocked_import"]) == "scientific"
    assert classify_revision_failure_kind(["synthetic-1:brand_new_code"]) == "scientific"


def test_technical_and_scientific_suffix_sets_are_disjoint() -> None:
    """A code must never be both budget-refunding and budget-consuming."""

    assert not (_TECHNICAL_FAILURE_SUFFIXES & _SCIENTIFIC_FAILURE_SUFFIXES)


@pytest.mark.parametrize(
    "code",
    [
        "static:syntax_error",
        "static:source_size",
        "static:markdown_fence",
        "static:ast_size",
        "static:missing_interface",
        "static:invalid_interface",
    ],
)
def test_malformed_source_is_technical_not_scientific(code: str) -> None:
    """Regression for live run v10.

    The model emitted `source_text` with bare `n` instead of escaped newlines, so
    15,767 bytes parsed as a single line and `ast.parse` failed at line 1. The
    candidate's science never ran, so this must not consume the scientific budget.
    """

    assert classify_revision_failure_kind([code]) == "technical"


@pytest.mark.parametrize(
    "code",
    [
        "static:frozen_target_marker",
        "static:query_training_reuse",
        "static:fit_after_query",
        "static:import_not_allowlisted",
        "static:dynamic_execution",
        "static:dunder_access",
        "static:module_mutation",
        "static:unbounded_loop",
        "static:top_level_effect",
        "static:dynamic_structure",
    ],
)
def test_leakage_and_sandbox_violations_stay_scientific(code: str) -> None:
    """Leakage, contamination, and escape attempts are substantive violations."""

    assert classify_revision_failure_kind([code]) == "scientific"
