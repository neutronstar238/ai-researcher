"""Task 269.4: the second frozen contradiction must be decided by the system.

Honestly repairing the baseline-coverage contradiction (`P-20260802-070`) narrowed the
panel, and the narrowed panel can no longer supply the frozen pilot breadth. That is a
scientific and protocol decision, so it follows the `268.2` contract: deterministic
observation, deterministic diagnosis, model-authored proposal, deterministic guard.

These tests pin the parts that must not depend on what the model happens to choose:

* the observation is arithmetic over the frozen plan and the policy, and its
  satisfiability flags cannot disagree with its own counts;
* the guard classifies the route the model ACTUALLY chose, not the route it claims;
* every unsafe route is refused, including the one that merely misreports itself;
* a proposal is never an authorization.

The guard's refusal path is tested explicitly. In the live runs the model chose the
honest route, so the refusal path would otherwise never execute, and an untested
guard is not a guard.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.pilot_breadth_contradiction import (
    DECLARE_UNSATISFIABLE,
    DRAW_UNNARROWED,
    REDUCE_BREADTH,
    RESOLUTION_KINDS,
    SUBSTITUTE_ODE,
    PilotBreadthContradictionError,
    PilotBreadthObservation,
    PilotBreadthProposal,
    audit_pilot_breadth_proposal,
    observe_pilot_breadth_contradiction,
    run_pilot_breadth_self_correction,
)
from autoresearch.llm.client import LLMJsonCompletionResult

# The real official panel shape: 10 ODE, 4 PDE.
_PANEL: dict[str, Any] = {
    "systems": [
        *({"system_name": f"ode-{i}", "data_type": "ode"} for i in range(10)),
        {"system_name": "reaction_diffusion_cylinder", "data_type": "pde"},
        {"system_name": "heat_laser", "data_type": "pde"},
        {"system_name": "navier_stokes_cylinder", "data_type": "pde"},
        {"system_name": "heat_soil_uniform_2d_p1", "data_type": "pde"},
    ],
    "seeds": [101, 211, 307],
    "conditions": ["clean", "snr_20"],
}
# The real frozen Task 266.1 pilot breadth.
_BUDGET: dict[str, Any] = {
    "pilot_ode_system_count": 3,
    "pilot_pde_system_count": 3,
    "pilot_seed_count": 1,
}
_EXCLUDED = ("heat_laser", "heat_soil_uniform_2d_p1")
_POLICY_HASH = "f" * 64


def _observe(**overrides: Any) -> PilotBreadthObservation:
    kwargs: dict[str, Any] = {
        "policy_hash": _POLICY_HASH,
        "excluded_system_names": _EXCLUDED,
        "panel": _PANEL,
        "budget": _BUDGET,
        "frozen_pilot_system_count": 6,
    }
    kwargs.update(overrides)
    return observe_pilot_breadth_contradiction(**kwargs)


def _proposal(kind: str, **overrides: Any) -> PilotBreadthProposal:
    """Build a proposal whose self-report is HONEST for the given route."""

    payload: dict[str, Any] = {
        "schema_version": "pilot-breadth-proposal-v1",
        "contradiction_statement": (
            "The preregistered exclusion leaves two PDE systems while the frozen "
            "budget requires three pilot PDE systems."
        ),
        "resolution_kind": kind,
        "justification": (
            "Chosen because it is the route consistent with the rules that bind this "
            "lineage, given the deterministic observation supplied."
        ),
        "edits_frozen_budget_parameter": kind in {REDUCE_BREADTH, SUBSTITUTE_ODE},
        "contaminates_finalist_selection": kind == DRAW_UNNARROWED,
        "requires_new_preregistration": kind == DECLARE_UNSATISFIABLE,
    }
    payload.update(overrides)
    return PilotBreadthProposal.model_validate(payload)


# --------------------------------------------------------------------------
# The deterministic observation
# --------------------------------------------------------------------------


def test_the_contradiction_is_stated_arithmetically() -> None:
    observation = _observe()
    assert observation.parent_pde_count == 4
    assert observation.narrowed_pde_count == 2
    assert observation.frozen_pilot_pde_required == 3
    # The ODE stratum is untouched, so only the PDE stratum is unsatisfiable.
    assert observation.ode_breadth_satisfiable is True
    assert observation.pde_breadth_satisfiable is False
    assert observation.frozen_pilot_breadth_satisfiable is False


def test_the_observation_names_both_strata_and_the_frozen_count() -> None:
    text = " ".join(_observe().observations)
    assert "PDE stratum falls from 4 to 2" in text
    assert "pilot_system_count=6" in text


def test_an_unsatisfiable_flag_cannot_disagree_with_the_counts() -> None:
    payload = _observe().model_dump(mode="json")
    payload["pde_breadth_satisfiable"] = True
    with pytest.raises(PilotBreadthContradictionError, match="PDE satisfiability"):
        PilotBreadthObservation.model_validate(payload)


def test_the_overall_flag_requires_both_strata() -> None:
    payload = _observe().model_dump(mode="json")
    payload["frozen_pilot_breadth_satisfiable"] = True
    with pytest.raises(PilotBreadthContradictionError, match="overall satisfiability"):
        PilotBreadthObservation.model_validate(payload)


def test_the_observation_hash_covers_its_content() -> None:
    payload = _observe().model_dump(mode="json")
    payload["observations"] = ("a rewritten observation that was never made",)
    with pytest.raises(PilotBreadthContradictionError, match="hash mismatch"):
        PilotBreadthObservation.model_validate(payload)


def test_no_exclusion_means_no_contradiction() -> None:
    with pytest.raises(PilotBreadthContradictionError, match="no pilot-breadth"):
        _observe(excluded_system_names=())


def test_a_panel_that_still_supplies_the_breadth_is_satisfiable() -> None:
    """Excluding a single ODE system leaves both frozen breadths reachable."""

    observation = _observe(excluded_system_names=("ode-0",))
    assert observation.narrowed_pde_count == 4
    assert observation.frozen_pilot_breadth_satisfiable is True


# --------------------------------------------------------------------------
# The guard, over every route in the closed set
# --------------------------------------------------------------------------


def test_the_honest_route_is_accepted() -> None:
    audit = audit_pilot_breadth_proposal(_proposal(DECLARE_UNSATISFIABLE))
    assert audit.guard_accepted is True
    assert audit.refusal_reasons == ()
    assert audit.edits_frozen_budget_parameter is False
    assert audit.contaminates_finalist_selection is False


def test_rewriting_a_frozen_budget_parameter_is_refused() -> None:
    for kind in (REDUCE_BREADTH, SUBSTITUTE_ODE):
        audit = audit_pilot_breadth_proposal(_proposal(kind))
        assert audit.guard_accepted is False
        assert audit.edits_frozen_budget_parameter is True
        assert any("frozen Task 266.1 budget parameter" in r for r in audit.refusal_reasons)


def test_contaminating_finalist_selection_is_refused() -> None:
    """Piloting over excluded systems would rank finalists on unmeasured evidence."""

    audit = audit_pilot_breadth_proposal(_proposal(DRAW_UNNARROWED))
    assert audit.guard_accepted is False
    assert audit.contaminates_finalist_selection is True
    assert any("excluded from the effect" in r for r in audit.refusal_reasons)


def test_every_route_in_the_closed_set_is_classified() -> None:
    """No route may fall through the guard unclassified."""

    for kind in RESOLUTION_KINDS:
        audit = audit_pilot_breadth_proposal(_proposal(kind))
        assert audit.resolution_kind == kind
        assert audit.self_report_matches_route is True


def test_a_route_outside_the_closed_set_is_refused() -> None:
    with pytest.raises(PilotBreadthContradictionError, match="unsupported resolution"):
        _proposal("quietly_reshape_the_pilot_and_say_nothing")


def test_a_proposal_that_misreports_its_own_risk_is_refused() -> None:
    """THE self-report guard. A route is classified by what it IS, not what it claims.

    A proposal that picks the frozen-parameter-editing route while declaring itself
    safe must be refused twice: once for the route, once for the misdescription.
    """

    dishonest = _proposal(REDUCE_BREADTH, edits_frozen_budget_parameter=False)
    audit = audit_pilot_breadth_proposal(dishonest)
    assert audit.guard_accepted is False
    assert audit.self_report_matches_route is False
    assert audit.edits_frozen_budget_parameter is True
    assert len(audit.refusal_reasons) == 2


def test_a_route_understating_contamination_is_refused() -> None:
    dishonest = _proposal(DRAW_UNNARROWED, contaminates_finalist_selection=False)
    audit = audit_pilot_breadth_proposal(dishonest)
    assert audit.guard_accepted is False
    assert audit.self_report_matches_route is False


def test_an_accepted_verdict_cannot_carry_refusal_reasons() -> None:
    payload = audit_pilot_breadth_proposal(_proposal(DECLARE_UNSATISFIABLE)).model_dump(
        mode="json"
    )
    payload["refusal_reasons"] = ["a reason smuggled onto an accepted verdict"]
    with pytest.raises(PilotBreadthContradictionError, match="contradicts its own"):
        type(
            audit_pilot_breadth_proposal(_proposal(DECLARE_UNSATISFIABLE))
        ).model_validate(payload)


# --------------------------------------------------------------------------
# The full cycle
# --------------------------------------------------------------------------


class _StubCompletion:
    """Return one fixed authored proposal, and record what was sent."""

    def __init__(self, kind: str, *, reasoning_tokens: int = 2_500) -> None:
        self.kind = kind
        self.reasoning_tokens = reasoning_tokens
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = _proposal(self.kind).model_dump(mode="json")
        payload.pop("schema_version")
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload),
            parsed_json=payload,
            usage={
                "prompt_tokens": 900,
                "completion_tokens": 300,
                "completion_tokens_details": {
                    "reasoning_tokens": self.reasoning_tokens
                },
            },
            temperature=0.2,
            reasoning_text="weighing each route against the binding rules",
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(tmp_path: Path, completion: _StubCompletion) -> Any:
    return run_pilot_breadth_self_correction(
        lineage_id="task2693-unified-lineage-v1",
        policy_hash=_POLICY_HASH,
        excluded_system_names=_EXCLUDED,
        panel=_PANEL,
        budget=_BUDGET,
        frozen_pilot_system_count=6,
        output_dir=tmp_path,
        completion=completion,
        clock=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def test_the_cycle_persists_an_accepted_proposal(tmp_path: Path) -> None:
    package = _run(tmp_path, _StubCompletion(DECLARE_UNSATISFIABLE))
    assert package.guard_audit.guard_accepted is True
    assert package.proposal.resolution_kind == DECLARE_UNSATISFIABLE
    assert package.reasoning_tokens == 2_500
    written = tmp_path / "pilot-breadth-contradiction-package.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["package_hash"] == (
        package.package_hash
    )


def test_the_cycle_records_a_refusal_without_hiding_it(tmp_path: Path) -> None:
    """A refused proposal is retained as evidence, not discarded and retried."""

    package = _run(tmp_path, _StubCompletion(REDUCE_BREADTH))
    assert package.guard_audit.guard_accepted is False
    assert package.guard_audit.refusal_reasons
    assert package.execution_authorized is False


def test_a_proposal_is_never_an_authorization(tmp_path: Path) -> None:
    package = _run(tmp_path, _StubCompletion(DECLARE_UNSATISFIABLE))
    assert package.execution_authorized is False
    assert package.human_scientific_decision_count == 0
    assert package.publication_ready is False


def test_the_prompt_offers_the_closed_set_without_steering(tmp_path: Path) -> None:
    """The model must see every route, including the dangerous ones, unranked."""

    completion = _StubCompletion(DECLARE_UNSATISFIABLE)
    _run(tmp_path, completion)
    sent = json.dumps(completion.calls[0]["messages"]).casefold()

    # Every route is offered, so the model is choosing rather than confirming.
    for kind in RESOLUTION_KINDS:
        assert kind in sent
    # The prompt carries an explicit anti-steer.
    assert "do not assume any option is preferred" in sent

    # The real property: no single route is singled out. Checking substrings against
    # prose is unreliable, since the anti-steer sentence itself contains "preferred",
    # so this asserts that no route NAME is adjacent to steering language.
    for kind in RESOLUTION_KINDS:
        for steer in ("recommended", "preferred", "best", "should choose", "correct"):
            assert f"{kind} is {steer}" not in sent
            assert f"{steer} route is {kind}" not in sent
            assert f"{steer}: {kind}" not in sent


def test_the_prompt_carries_the_literal_word_json(tmp_path: Path) -> None:
    """Regression for a real live failure.

    The first live run of this cycle was rejected with
    `InternalError.Algo.InvalidParameter: 'messages' must contain the word 'json' in
    some form, to use 'response_format' of type 'json_object'`. Task `267.3.1`
    established that enabling reasoning downgrades transport-level `json_schema` to
    `json_object` on DashScope-shaped providers, and that mode requires the literal
    lowercase word. Without this test the same defect returns silently.
    """

    completion = _StubCompletion(DECLARE_UNSATISFIABLE)
    _run(tmp_path, completion)
    assert any("json" in item["content"] for item in completion.calls[0]["messages"])
    # And the schema is stated, since strict conformance moved to local validation.
    sent = json.dumps(completion.calls[0]["messages"])
    assert "resolution_kind" in sent
    assert completion.calls[0]["response_schema"] is None


def test_the_cycle_sends_bounded_reasoning(tmp_path: Path) -> None:
    completion = _StubCompletion(DECLARE_UNSATISFIABLE)
    _run(tmp_path, completion)
    assert completion.calls[0]["thinking_mode"] == "enabled"
    assert 0 < completion.calls[0]["thinking_budget"] <= 32_000


def test_the_package_refuses_a_guard_that_audited_another_route(tmp_path: Path) -> None:
    package = _run(tmp_path, _StubCompletion(DECLARE_UNSATISFIABLE))
    payload = json.loads(package.model_dump_json())
    payload["proposal"]["resolution_kind"] = DRAW_UNNARROWED
    with pytest.raises(PilotBreadthContradictionError, match="different route"):
        type(package).model_validate(payload)


def test_a_satisfiable_panel_refuses_to_run_the_cycle(tmp_path: Path) -> None:
    """No model call is spent when there is no contradiction."""

    completion = _StubCompletion(DECLARE_UNSATISFIABLE)
    with pytest.raises(PilotBreadthContradictionError, match="no contradiction"):
        run_pilot_breadth_self_correction(
            lineage_id="task2693-unified-lineage-v1",
            policy_hash=_POLICY_HASH,
            excluded_system_names=("ode-0",),
            panel=_PANEL,
            budget=_BUDGET,
            frozen_pilot_system_count=6,
            output_dir=tmp_path,
            completion=completion,
        )
    assert completion.calls == []
