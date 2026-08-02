"""Task 267.1: the advertised equation contract must equal the enforced whitelist.

Historical defect this test locks out: the prompt-visible contract advertised
``term_count`` and ``factor_count`` while the sandbox runner rejected every key
outside ``{target, intercept, terms}`` and ``{field, derivative_axes, power}``.
A schema-obedient model answer was therefore rejected as a scientific failure,
and runs ``task2662-scientific-contract-harness-v1..v9`` all ended with
``passed_sentinel_count=0/6`` and ``fit_call_count=0``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from autoresearch.competition.scientific_contract_harness import (
    _EQUATION_EXACT_FIELDS,
    _EQUATION_FACTOR_EXACT_FIELDS,
    _EQUATION_TERM_EXACT_FIELDS,
    _FORBIDDEN_EQUATION_CONTRACT_KEYS,
)

ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = (
    ROOT / "deploy" / "experiments" / "mdbench" / "scientific_contract_harness_runner.py"
)


def _enforced_key_sets(source: str) -> list[frozenset[str]]:
    """Extract every ``set(x) - {...}`` whitelist literal from the runner."""

    enforced: list[frozenset[str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Sub):
            continue
        if not isinstance(node.right, ast.Set):
            continue
        keys = {
            element.value
            for element in node.right.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if keys:
            enforced.append(frozenset(keys))
    return enforced


@pytest.fixture(scope="module")
def runner_source() -> str:
    assert RUNNER_PATH.is_file(), f"runner missing at {RUNNER_PATH}"
    return RUNNER_PATH.read_text(encoding="utf-8")


def test_equation_and_factor_whitelists_match_the_runner(runner_source: str) -> None:
    enforced = _enforced_key_sets(runner_source)
    assert frozenset(_EQUATION_EXACT_FIELDS) in enforced, (
        "advertised equation keys are not enforced by the runner: "
        f"{sorted(_EQUATION_EXACT_FIELDS)}"
    )
    assert frozenset(_EQUATION_FACTOR_EXACT_FIELDS) in enforced, (
        "advertised factor keys are not enforced by the runner: "
        f"{sorted(_EQUATION_FACTOR_EXACT_FIELDS)}"
    )


def test_term_whitelist_matches_the_runner_equality_check(runner_source: str) -> None:
    # The runner enforces term keys with `set(term) != {"coefficient", "factors"}`.
    expected = "!= {\"coefficient\", \"factors\"}"
    normalized = runner_source.replace("'", '"')
    assert expected in normalized, "runner term whitelist changed shape"
    assert set(_EQUATION_TERM_EXACT_FIELDS) == {"coefficient", "factors"}


def test_forbidden_count_keys_are_never_advertised() -> None:
    advertised = (
        set(_EQUATION_EXACT_FIELDS)
        | set(_EQUATION_TERM_EXACT_FIELDS)
        | set(_EQUATION_FACTOR_EXACT_FIELDS)
    )
    for forbidden in _FORBIDDEN_EQUATION_CONTRACT_KEYS:
        assert forbidden not in advertised


def test_prompt_contract_does_not_mention_forbidden_count_keys() -> None:
    """The rendered prompt contract must not reintroduce the fatal keys."""

    harness_path = (
        ROOT
        / "src"
        / "autoresearch"
        / "competition"
        / "scientific_contract_harness.py"
    )
    source = harness_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    advertised_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    advertised_literals.add(key.value)
    for forbidden in _FORBIDDEN_EQUATION_CONTRACT_KEYS:
        assert forbidden not in advertised_literals, (
            f"prompt contract reintroduced the runner-rejected key {forbidden!r}"
        )
