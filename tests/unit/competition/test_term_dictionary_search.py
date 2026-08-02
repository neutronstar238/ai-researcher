"""Task 267.5: dictionary plus set-level selection must recover laws and reject nulls.

Replaces parent-conditioned evolution as the primary search, per
`arXiv:2607.04108`: under matched call budgets, parent-conditioned evolution is
statistically indistinguishable from independent sampling, and set-level
selection over a term dictionary is what carries discovery.

The rejection tests target the exact Task 265.3 failure recorded in
P-20260801-042: selected `branch-08` had derivative NMSE `0.9999999999988402`
with training-context sensitivity `0` -- a fit indistinguishable from zero.
"""

from __future__ import annotations

import math

import pytest

from autoresearch.competition.term_dictionary_search import (
    CandidateTerm,
    MatchedBudgetArm,
    TermDictionary,
    TermDictionaryError,
    extract_term_dictionary,
    normalized_mse,
    select_term_set,
    solve_least_squares,
    term_influence_scores,
    validate_matched_budget,
)


def _term(name: str, axes: tuple[str, ...] = (), power: int = 1) -> CandidateTerm:
    return CandidateTerm(field_name=name, derivative_axes=axes, power=power)


# --------------------------------------------------------------------------
# Dictionary construction
# --------------------------------------------------------------------------


def test_dictionary_pools_terms_across_independent_proposals() -> None:
    """The loop's durable product is the dictionary, not a parent lineage."""

    dictionary = extract_term_dictionary(
        [
            ("proposal-01", [_term("u", ("x",)), _term("u", ("x", "x"))]),
            ("proposal-02", [_term("u", ("x",)), _term("u")]),
        ]
    )

    assert len(dictionary) == 3
    assert dictionary.proposal_count == 2
    shared = next(t for t in dictionary.terms if t.key == ("u", ("x",), 1))
    assert shared.origin_proposal_ids == ("proposal-01", "proposal-02")


def test_dictionary_ordering_is_deterministic() -> None:
    """Selection replay requires a stable dictionary order."""

    first = extract_term_dictionary(
        [("p1", [_term("u", ("x", "x")), _term("u"), _term("u", ("x",))])]
    )
    second = extract_term_dictionary(
        [("p1", [_term("u", ("x",)), _term("u", ("x", "x")), _term("u")])]
    )

    assert [t.key for t in first.terms] == [t.key for t in second.terms]


def test_dictionary_rejects_empty_proposals() -> None:
    with pytest.raises(TermDictionaryError, match="at least one proposal"):
        extract_term_dictionary([])


def test_duplicate_supports_are_rejected_in_a_dictionary() -> None:
    with pytest.raises(TermDictionaryError, match="duplicate supports"):
        TermDictionary(terms=(_term("u", ("x",)), _term("u", ("x",))), proposal_count=1)


def test_term_renders_in_exact_contract_factor_shape() -> None:
    """Must match the Task 267.1 factor whitelist exactly."""

    assert _term("u", ("x", "x"), 2).to_factor() == {
        "field": "u",
        "derivative_axes": ["x", "x"],
        "power": 2,
    }


@pytest.mark.parametrize(("axes", "power"), [(("t",), 1), ((), 0), ((), 7)])
def test_invalid_term_shapes_are_rejected(axes: tuple[str, ...], power: int) -> None:
    with pytest.raises(TermDictionaryError):
        CandidateTerm(field_name="u", derivative_axes=axes, power=power)


# --------------------------------------------------------------------------
# Least squares
# --------------------------------------------------------------------------


def test_least_squares_recovers_exact_coefficients() -> None:
    design = [[1.0, 2.0], [2.0, 1.0], [3.0, 4.0], [4.0, 3.0]]
    target = [1.0 * 2.0 + 2.0 * -3.0, 2.0 * 2.0 + 1.0 * -3.0, 3.0 * 2.0 + 4.0 * -3.0, 4.0 * 2.0 + 3.0 * -3.0]

    coefficients = solve_least_squares(design, target)

    assert coefficients[0] == pytest.approx(2.0, abs=1e-6)
    assert coefficients[1] == pytest.approx(-3.0, abs=1e-6)


def test_least_squares_rejects_mismatched_shapes() -> None:
    with pytest.raises(TermDictionaryError, match="differs from target"):
        solve_least_squares([[1.0], [2.0]], [1.0])


def test_singular_column_does_not_crash_selection() -> None:
    """A degenerate candidate set must be scored, not raise."""

    coefficients = solve_least_squares([[0.0, 1.0], [0.0, 2.0]], [1.0, 2.0])

    assert len(coefficients) == 2
    assert all(math.isfinite(value) for value in coefficients)


# --------------------------------------------------------------------------
# Set-level selection: known-law recovery
# --------------------------------------------------------------------------


def test_set_level_selection_recovers_a_known_sparse_law() -> None:
    """u_t = -0.1*u_x + 0.05*u_xx, with two distractor terms present."""

    dictionary = extract_term_dictionary(
        [
            (
                "proposal-01",
                [
                    _term("u", ("x",)),
                    _term("u", ("x", "x")),
                    _term("u"),
                    _term("u", (), 2),
                ],
            )
        ]
    )
    # Build design columns in DICTIONARY order, which is canonically sorted:
    # ('u',(),1), ('u',(),2), ('u',('x',),1), ('u',('x','x'),1)
    rows = []
    target = []
    for step in range(1, 41):
        u_x = math.sin(step * 0.3)
        u_xx = math.cos(step * 0.17)
        u = 0.5 * step / 40.0
        rows.append([u, u * u, u_x, u_xx])
        target.append(-0.1 * u_x + 0.05 * u_xx)

    result = select_term_set(dictionary, rows, target, max_terms=4)

    assert result.accepted
    assert {t.key for t in result.selected_terms} == {
        ("u", ("x",), 1),
        ("u", ("x", "x"), 1),
    }
    assert result.train_nmse < 1e-6
    assert result.zero_null_relative_improvement > 0.99


def test_selection_prefers_a_sparse_set_over_an_overfitted_one() -> None:
    """BIC must penalize size so distractors are not absorbed."""

    dictionary = extract_term_dictionary(
        [("p1", [_term("u", ("x",)), _term("u"), _term("u", (), 2), _term("u", (), 3)])]
    )
    # Dictionary order: ('u',(),1), ('u',(),2), ('u',(),3), ('u',('x',),1)
    rows = []
    target = []
    for step in range(1, 51):
        u_x = math.sin(step * 0.41)
        u = step / 50.0
        rows.append([u, u**2, u**3, u_x])
        target.append(0.7 * u_x)

    result = select_term_set(dictionary, rows, target, max_terms=4)

    assert result.accepted
    assert {t.key for t in result.selected_terms} == {("u", ("x",), 1)}
    # Only one term was selected, so its coefficient is the single entry.
    assert len(result.coefficients) == 1
    assert result.coefficients[0] == pytest.approx(0.7, abs=1e-6)


# --------------------------------------------------------------------------
# Set-level selection: the Task 265.3 failure modes
# --------------------------------------------------------------------------


def test_zero_null_equivalent_fit_is_rejected() -> None:
    """The exact 265.3 collapse: NMSE ~= 1.0 means predicting nothing."""

    dictionary = extract_term_dictionary([("p1", [_term("u", ("x",))])])
    # Design column is orthogonal to the target, so no fit can help.
    rows = [[1.0], [-1.0], [1.0], [-1.0], [1.0], [-1.0]]
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    result = select_term_set(dictionary, rows, target)

    assert not result.accepted
    assert result.rejected_reason in {
        "fit_is_zero_null_equivalent",
        "no_term_set_improved_on_the_zero_null",
        "fit_is_independent_of_training_data",
    }


def test_train_independent_fit_is_rejected() -> None:
    """The 265.3 companion failure: training-context sensitivity 0."""

    dictionary = extract_term_dictionary([("p1", [_term("u", ("x",))])])
    rows = [[0.0], [0.0], [0.0], [0.0]]
    target = [0.0, 0.0, 0.0, 0.0]

    result = select_term_set(dictionary, rows, target)

    assert not result.accepted


def test_train_dependence_check_can_be_disabled_for_diagnostics() -> None:
    dictionary = extract_term_dictionary([("p1", [_term("u", ("x",))])])
    rows = [[0.0], [0.0], [0.0], [0.0]]
    target = [0.0, 0.0, 0.0, 0.0]

    result = select_term_set(dictionary, rows, target, require_train_dependence=False)

    assert result.rejected_reason != "fit_is_independent_of_training_data"


# --------------------------------------------------------------------------
# Per-term influence (granular feedback)
# --------------------------------------------------------------------------


def test_term_influence_identifies_the_load_bearing_term() -> None:
    """Scalar NMSE cannot attribute credit; influence must."""

    # Dictionary order: ('u',(),1) then ('u',('x',),1), so column 1 is u_x.
    rows = []
    target = []
    for step in range(1, 41):
        u_x = math.sin(step * 0.29)
        u = step / 40.0
        rows.append([u, u_x])
        # u_x dominates; u contributes weakly.
        target.append(1.0 * u_x + 0.001 * u)

    influences = term_influence_scores(rows, target, [0, 1])

    assert len(influences) == 2
    # Dropping the dominant u_x term must hurt more than dropping u.
    assert influences[1] > influences[0]


def test_influence_of_an_empty_selection_is_empty() -> None:
    assert term_influence_scores([[1.0]], [1.0], []) == ()


def test_accepted_result_reports_one_influence_per_selected_term() -> None:
    dictionary = extract_term_dictionary(
        [("p1", [_term("u", ("x",)), _term("u", ("x", "x"))])]
    )
    rows = []
    target = []
    for step in range(1, 31):
        u_x = math.sin(step * 0.33)
        u_xx = math.cos(step * 0.21)
        rows.append([u_x, u_xx])
        target.append(-0.2 * u_x + 0.1 * u_xx)

    result = select_term_set(dictionary, rows, target)

    assert result.accepted
    assert len(result.term_influences) == len(result.selected_terms)


# --------------------------------------------------------------------------
# NMSE convention and guards
# --------------------------------------------------------------------------


def test_nmse_matches_the_runner_convention() -> None:
    assert normalized_mse([1.0, 2.0], [1.0, 2.0]) == pytest.approx(0.0)
    assert normalized_mse([1.0, 1.0], [0.0, 0.0]) == pytest.approx(1.0, abs=1e-9)


def test_selection_rejects_a_design_that_does_not_match_the_dictionary() -> None:
    dictionary = extract_term_dictionary([("p1", [_term("u", ("x",))])])
    with pytest.raises(TermDictionaryError, match="must match dictionary size"):
        select_term_set(dictionary, [[1.0, 2.0]], [1.0])


def test_evaluated_set_budget_is_respected() -> None:
    """A bounded search must stop rather than enumerate combinatorially."""

    dictionary = extract_term_dictionary(
        [("p1", [_term("u", (), power) for power in range(1, 7)])]
    )
    rows = [[float(i + j) for j in range(6)] for i in range(20)]
    target = [float(i) for i in range(20)]

    result = select_term_set(dictionary, rows, target, max_terms=6, max_evaluated_sets=5)

    assert result.evaluated_set_count <= 5


# --------------------------------------------------------------------------
# Matched-budget comparator (Route P2)
# --------------------------------------------------------------------------


def test_matched_budget_requires_identical_call_counts() -> None:
    """The audit result holds only under matched budgets."""

    with pytest.raises(TermDictionaryError, match="identical model-call budget"):
        validate_matched_budget(
            [
                MatchedBudgetArm(
                    arm_id="independent_sampling_set_level",
                    llm_call_count=8,
                    proposal_count=8,
                    generations=1,
                ),
                MatchedBudgetArm(
                    arm_id="parent_conditioned_evolution",
                    llm_call_count=12,
                    proposal_count=8,
                    generations=2,
                ),
            ]
        )


def test_matched_budget_accepts_two_balanced_arms() -> None:
    arms = validate_matched_budget(
        [
            MatchedBudgetArm(
                arm_id="parent_conditioned_evolution",
                llm_call_count=12,
                proposal_count=8,
                generations=2,
            ),
            MatchedBudgetArm(
                arm_id="independent_sampling_set_level",
                llm_call_count=12,
                proposal_count=12,
                generations=1,
            ),
        ]
    )

    assert [arm.arm_id for arm in arms] == [
        "independent_sampling_set_level",
        "parent_conditioned_evolution",
    ]


def test_set_level_arm_must_be_one_generation() -> None:
    """One-generation is the defining property of the replacement search."""

    with pytest.raises(TermDictionaryError, match="one-generation by construction"):
        MatchedBudgetArm(
            arm_id="independent_sampling_set_level",
            llm_call_count=8,
            proposal_count=8,
            generations=2,
        )


def test_evolutionary_arm_must_have_at_least_two_generations() -> None:
    with pytest.raises(TermDictionaryError, match="at least two generations"):
        MatchedBudgetArm(
            arm_id="parent_conditioned_evolution",
            llm_call_count=8,
            proposal_count=8,
            generations=1,
        )


def test_both_named_arms_are_required() -> None:
    with pytest.raises(TermDictionaryError, match="exactly two arms"):
        validate_matched_budget(
            [
                MatchedBudgetArm(
                    arm_id="independent_sampling_set_level",
                    llm_call_count=8,
                    proposal_count=8,
                    generations=1,
                )
            ]
        )
