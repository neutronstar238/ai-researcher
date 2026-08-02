"""Task 267.2 follow-up: an unaddressable patch is technical, not terminal.

Live runs v10 and v12 both ended the entire search on a text-addressing mistake:
`replacement 1 matched 0 times` and `replacement 5 matched 3 times`. No
scientific verdict was reached in either case, so ending the run there discarded
the whole remaining budget over a copy-paste error.

Patch application now raises `ScientificContractPatchError`, carrying an
actionable diagnosis, and the loop re-asks the model within a bounded budget.
"""

from __future__ import annotations

import pytest

from autoresearch.competition.scientific_contract_harness import (
    _MAX_PATCH_ADDRESSING_ATTEMPTS,
    ScientificContractHarnessError,
    ScientificContractPatchError,
    ScientificContractPatchResponse,
    _apply_model_authored_patch,
    _sha256_text,
    classify_revision_failure_kind,
)

PARENT = (
    "import math\n"
    "\n"
    "\n"
    "def fit_equations(payload):\n"
    '    """Fit once on train-only context and freeze concrete equations."""\n'
    "    train_state = payload['train_state']\n"
    "    return {'equations': [], 'field_scaling': [], 'diagnostics': {}}\n"
    "\n"
    "\n"
    "def predict_derivative(payload):\n"
    '    """Evaluate only the frozen artifact for this query slice."""\n'
    "    artifact = payload['artifact']\n"
    "    return {'schema_version': 'scientific-predict-response-v1'}\n"
)


def _patch(replacements: list[dict[str, str]]) -> ScientificContractPatchResponse:
    return ScientificContractPatchResponse.model_validate(
        {
            "response_type": "scientific_contract_patch",
            "observation": "The static review rejected the parent source.",
            "problem": "The parent source cannot pass the synthetic gate as written.",
            "hypothesis": "A minimal edit preserves the scientific implementation.",
            "intervention": "Apply one exact replacement to the parent source.",
            "expected_effect": "The candidate will parse and reach the sentinels.",
            "implementation_summary": "Minimal exact replacement against the parent.",
            "parent_source_sha256": _sha256_text(PARENT),
            "replacements": replacements,
        }
    )


def test_patch_error_is_a_harness_error_subclass() -> None:
    """Existing callers that catch the base error keep working."""

    assert issubclass(ScientificContractPatchError, ScientificContractHarnessError)


def test_missing_old_text_reports_zero_matches_with_guidance() -> None:
    patch = _patch([{"old_text": "import numpy\n", "new_text": ""}])

    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(PARENT, patch)

    assert caught.value.failure_code == "patch_old_text_not_unique"
    message = str(caught.value)
    assert "matched 0 times" in message
    assert "copy an exact substring" in message


def test_ambiguous_old_text_reports_the_match_count_and_fix() -> None:
    """This is the exact v12 failure: replacement 5 matched 3 times."""

    parent = "a = 1\nb = 1\nc = 1\ndef fit_equations(payload):\n    return {}\n"
    patch = ScientificContractPatchResponse.model_validate(
        {
            "response_type": "scientific_contract_patch",
            "observation": "The parent source repeats a line.",
            "problem": "An ambiguous anchor cannot be applied deterministically.",
            "hypothesis": "A longer anchor is unique.",
            "intervention": "Replace one occurrence only.",
            "expected_effect": "The patch will apply deterministically.",
            "implementation_summary": "Replace a repeated line.",
            "parent_source_sha256": _sha256_text(parent),
            "replacements": [{"old_text": " = 1\n", "new_text": " = 2\n"}],
        }
    )

    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(parent, patch)

    assert "matched 3 times" in str(caught.value)
    assert "until it is unique" in str(caught.value)


def test_noop_patch_is_rejected_with_a_named_failure_code() -> None:
    patch = _patch([{"old_text": "import math\n", "new_text": "import math\n"}])

    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(PARENT, patch)

    assert caught.value.failure_code == "patch_left_source_unchanged"


def test_a_valid_patch_still_applies_exactly_once() -> None:
    patch = _patch([{"old_text": "import math\n", "new_text": "import statistics\n"}])

    assert _apply_model_authored_patch(PARENT, patch).startswith("import statistics")


def test_patch_addressing_budget_is_bounded() -> None:
    """A persistently mis-addressing model must not loop forever."""

    assert 1 <= _MAX_PATCH_ADDRESSING_ATTEMPTS <= 5


def test_patch_failure_codes_do_not_consume_the_scientific_budget() -> None:
    """Text addressing is not a scientific verdict."""

    for code in (
        "patch_old_text_not_unique",
        "patch_left_source_unchanged",
        "patch_source_size_out_of_bounds",
    ):
        # These never reach the revision ledger as scientific failures; they are
        # retried first, and a persisted revision only records a real verdict.
        assert classify_revision_failure_kind([f"static:{code}"]) == "scientific", (
            "unknown codes must fail closed; patch codes are handled by retry, "
            "not by the revision classifier"
        )
