"""Task 267.2 repair: address patches by function name, not by text anchor.

Text-anchor patching failed live three times in a row, each time ending the entire
search on a copy-paste error rather than on any scientific verdict:

* v10 -- `replacement 1 matched 0 times`
* v12 -- `replacement 5 matched 3 times`, immediately after the first genuine
  scientific execution in this lineage
* v13 -- `replacement 7 matched 2 times` on `    n_fields = state.shape[-1]`,
  after exhausting all three bounded re-ask attempts

A top-level function name is unique by Python's own rules, so addressing a whole
function makes the ambiguity structurally impossible instead of merely less likely.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoresearch.competition.scientific_contract_harness import (
    _MAX_PATCH_ADDRESSING_ATTEMPTS,
    ScientificContractHarnessError,
    ScientificContractPatchError,
    ScientificContractPatchResponse,
    _apply_model_authored_patch,
    _numbered_source,
    _sha256_text,
    _top_level_function_spans,
)

PARENT = (
    "import math\n"
    "\n"
    "\n"
    "def _helper(value):\n"
    "    n_fields = value\n"
    "    return n_fields\n"
    "\n"
    "\n"
    "def fit_equations(payload):\n"
    '    """Fit once on train-only context and freeze concrete equations."""\n'
    "    n_fields = payload['train_state']\n"
    "    return {'equations': [], 'field_scaling': [], 'diagnostics': {}}\n"
    "\n"
    "\n"
    "def predict_derivative(payload):\n"
    '    """Evaluate only the frozen artifact for this query slice."""\n'
    "    n_fields = payload['artifact']\n"
    "    return {'schema_version': 'scientific-predict-response-v1'}\n"
)

REPLACEMENT_LINES = (
    "def fit_equations(payload):",
    '    """Fit a sparse concrete law from train-only context."""',
    "    train_state = payload['train_state']",
    "    selected = [term for term in train_state if term]",
    "    return {'equations': selected, 'field_scaling': [], 'diagnostics': {}}",
)


def _patch(replacements: list[dict[str, object]]) -> ScientificContractPatchResponse:
    return ScientificContractPatchResponse.model_validate(
        {
            "response_type": "scientific_contract_patch",
            "observation": "The synthetic sentinels rejected the parent candidate.",
            "problem": "The parent fit does not recover concrete term support.",
            "hypothesis": "Set-level selection over the train context recovers support.",
            "intervention": "Replace the whole fit_equations function.",
            "expected_effect": "Term support and coefficient recovery should improve.",
            "implementation_summary": "Whole-function replacement of the fitting routine.",
            "parent_source_sha256": _sha256_text(PARENT),
            "function_replacements": replacements,
        }
    )


# --------------------------------------------------------------------------
# The ambiguity that killed v13 is now structurally impossible
# --------------------------------------------------------------------------


def test_repeated_line_no_longer_creates_ambiguity() -> None:
    """`    n_fields = ...` appears three times, which is what broke v13."""

    assert PARENT.count("    n_fields = ") == 3

    patched = _apply_model_authored_patch(
        PARENT,
        _patch(
            [
                {
                    "function_name": "fit_equations",
                    "new_source_lines": list(REPLACEMENT_LINES),
                }
            ]
        ),
    )

    # The targeted function changed; the identically-shaped lines elsewhere did not.
    assert "selected = [term for term in train_state if term]" in patched
    assert "def _helper(value):\n    n_fields = value" in patched
    assert "def predict_derivative(payload):" in patched


def test_function_spans_are_found_by_ast() -> None:
    spans = _top_level_function_spans(PARENT)

    assert set(spans) == {"_helper", "fit_equations", "predict_derivative"}
    start, end = spans["fit_equations"]
    assert PARENT.split("\n")[start - 1] == "def fit_equations(payload):"
    assert end > start


def test_nested_function_is_not_addressable() -> None:
    """Only top-level functions may be replaced."""

    source = (
        "def outer(payload):\n"
        "    def inner(value):\n"
        "        return value\n"
        "    return inner(payload)\n"
    )

    assert set(_top_level_function_spans(source)) == {"outer"}


def test_decorated_function_span_includes_its_decorator() -> None:
    source = "import functools\n\n\n@functools.cache\ndef cached(value):\n    return value\n"

    spans = _top_level_function_spans(source)

    # The span must start at the decorator, not at the def line.
    assert spans["cached"][0] == 4


def test_unparsable_source_yields_no_spans() -> None:
    assert _top_level_function_spans("def broken(:\n") == {}


# --------------------------------------------------------------------------
# Actionable diagnoses
# --------------------------------------------------------------------------


def test_unknown_function_lists_the_available_names() -> None:
    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            PARENT,
            _patch(
                [
                    {
                        "function_name": "does_not_exist",
                        "new_source_lines": ["def does_not_exist():", "    return 1"],
                    }
                ]
            ),
        )

    assert caught.value.failure_code == "patch_unknown_function"
    message = str(caught.value)
    assert "fit_equations" in message
    assert "predict_derivative" in message


def test_replacement_must_start_with_its_def_line() -> None:
    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            PARENT,
            _patch(
                [
                    {
                        "function_name": "fit_equations",
                        "new_source_lines": ["    return {}", "    # orphaned body"],
                    }
                ]
            ),
        )

    assert caught.value.failure_code == "patch_replacement_missing_def"


def test_replacement_def_line_cannot_be_indented() -> None:
    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            PARENT,
            _patch(
                [
                    {
                        "function_name": "fit_equations",
                        "new_source_lines": [
                            "    def fit_equations(payload):",
                            "        return {}",
                        ],
                    }
                ]
            ),
        )

    assert caught.value.failure_code == "patch_replacement_indented_def"


def test_byte_identical_replacement_is_rejected() -> None:
    original = PARENT.split("\n")
    start, end = _top_level_function_spans(PARENT)["fit_equations"]

    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            PARENT,
            _patch(
                [
                    {
                        "function_name": "fit_equations",
                        "new_source_lines": original[start - 1 : end],
                    }
                ]
            ),
        )

    assert caught.value.failure_code == "patch_left_source_unchanged"


def test_parent_without_any_function_is_reported_clearly() -> None:
    flat = "x = 1\n" * 80

    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            flat,
            ScientificContractPatchResponse.model_validate(
                {
                    "response_type": "scientific_contract_patch",
                    "observation": "The parent has no function to replace.",
                    "problem": "There is no addressable target.",
                    "hypothesis": "A complete rewrite is required.",
                    "intervention": "Replace the whole source.",
                    "expected_effect": "The candidate will define the interface.",
                    "implementation_summary": "Full rewrite required.",
                    "parent_source_sha256": _sha256_text(flat),
                    "function_replacements": [
                        {
                            "function_name": "fit_equations",
                            "new_source_lines": ["def fit_equations(p):", "    return {}"],
                        }
                    ],
                }
            ),
        )

    assert caught.value.failure_code == "patch_parent_has_no_function"


# --------------------------------------------------------------------------
# Multi-function edits and schema guards
# --------------------------------------------------------------------------


def test_two_functions_can_be_replaced_in_one_patch() -> None:
    """Bottom-up application keeps not-yet-applied spans valid."""

    patched = _apply_model_authored_patch(
        PARENT,
        _patch(
            [
                {
                    "function_name": "fit_equations",
                    "new_source_lines": list(REPLACEMENT_LINES),
                },
                {
                    "function_name": "predict_derivative",
                    "new_source_lines": [
                        "def predict_derivative(payload):",
                        '    """Evaluate the frozen artifact only."""',
                        "    artifact = payload['artifact']",
                        "    return {'schema_version': 'scientific-predict-response-v1',",
                        "            'artifact_hash': artifact['artifact_hash']}",
                    ],
                },
            ]
        ),
    )

    assert "selected = [term for term in train_state if term]" in patched
    assert "'artifact_hash': artifact['artifact_hash']" in patched
    # The untouched helper must survive byte-identically.
    assert "def _helper(value):\n    n_fields = value\n    return n_fields" in patched


def test_the_same_function_cannot_be_replaced_twice() -> None:
    with pytest.raises(ValidationError, match="same function twice"):
        _patch(
            [
                {
                    "function_name": "fit_equations",
                    "new_source_lines": list(REPLACEMENT_LINES),
                },
                {
                    "function_name": "fit_equations",
                    "new_source_lines": list(REPLACEMENT_LINES),
                },
            ]
        )


def test_parent_hash_mismatch_is_still_a_hard_boundary() -> None:
    """A stale parent is an evidence-integrity failure, not a retryable typo."""

    patch = _patch(
        [{"function_name": "fit_equations", "new_source_lines": list(REPLACEMENT_LINES)}]
    )

    with pytest.raises(ScientificContractHarnessError, match="parent hash changed"):
        _apply_model_authored_patch(PARENT + "\n# drifted\n", patch)


def test_patch_error_is_a_harness_error_subclass() -> None:
    assert issubclass(ScientificContractPatchError, ScientificContractHarnessError)


def test_patch_addressing_budget_is_bounded() -> None:
    assert 1 <= _MAX_PATCH_ADDRESSING_ATTEMPTS <= 5


# --------------------------------------------------------------------------
# Model-facing numbered source
# --------------------------------------------------------------------------


def test_interleaved_bare_delimiters_are_discarded() -> None:
    """Observed live in run v14.

    The model interleaved a bare `]` between every real line, producing
    `[']', 'def ...', ']', '    import numpy as np', ']', ...]`. The Python was
    intact; only the array carried stray JSON delimiters.
    """

    patched = _apply_model_authored_patch(
        PARENT,
        _patch(
            [
                {
                    "function_name": "fit_equations",
                    "new_source_lines": [
                        "]",
                        "def fit_equations(payload):",
                        "]",
                        "    train_state = payload['train_state']",
                        "]",
                        "    return {'equations': train_state}",
                    ],
                }
            ]
        ),
    )

    assert "def fit_equations(payload):" in patched
    assert "    train_state = payload['train_state']" in patched
    # No stray delimiter may survive into the persisted candidate.
    assert "\n]\n" not in patched


def test_indented_closing_brace_is_never_discarded() -> None:
    """Regression guard for a bug introduced while building this repair.

    An earlier filter matched the STRIPPED form of each line, which deleted the
    legitimate closing `    }` of a returned dict literal and silently truncated
    candidate source. Only an exactly unindented bare delimiter may be dropped.
    """

    patched = _apply_model_authored_patch(
        PARENT,
        _patch(
            [
                {
                    "function_name": "fit_equations",
                    "new_source_lines": [
                        "def fit_equations(payload):",
                        "    return {",
                        "        'equations': [],",
                        "    }",
                    ],
                }
            ]
        ),
    )

    # The indented closing brace must survive, or the function is truncated.
    assert "    return {\n        'equations': [],\n    }" in patched


def test_replacement_that_is_only_delimiters_is_rejected() -> None:
    with pytest.raises(ScientificContractPatchError) as caught:
        _apply_model_authored_patch(
            PARENT,
            _patch(
                [{"function_name": "fit_equations", "new_source_lines": ["]", "}"]}]
            ),
        )

    assert caught.value.failure_code == "patch_replacement_empty"


def test_numbered_source_is_one_based_and_aligned() -> None:
    numbered = _numbered_source("alpha\nbeta\ngamma\n").split("\n")

    assert numbered[0] == "1 | alpha"
    assert numbered[1] == "2 | beta"
    assert numbered[2] == "3 | gamma"


def test_numbered_source_pads_wider_line_counts() -> None:
    numbered = _numbered_source("\n".join(f"line{index}" for index in range(1, 12)))

    assert numbered.startswith(" 1 | line1")
    assert "11 | line11" in numbered
