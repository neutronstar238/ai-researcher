"""Let the system interpret its OWN result, with a guard against invented numbers.

Why this exists
---------------
Task `267.7` requires the system to author its own outcome. It did author the
candidates, the revisions, the protocol decisions, and every number. But the narrative
around those numbers was hand-written by an agent: `build_official_research_plan` makes
no model call at all and carries hardcoded prose, and the first Route P2 report was
written by hand. So the RESULT was the system's and the INTERPRETATION was not.

This module closes that gap for the interpretation. The model receives the signed
package's numbers and the frozen thresholds, and writes the interpretation itself:
what the result supports, what it does not, and whether the evidence warrants the
claim.

The guard is the whole point
----------------------------
"System-authored" is worthless if the system can invent a number. Every numeric token
the model emits is extracted and checked against the numbers actually present in the
signed package and the frozen estimand. An unmatched number is a REFUSAL, not a
warning. The model may choose the words; it may not choose the evidence.

Two further refusals matter as much:

* A model that claims success while the frozen gate failed is refused. The gate is
  deterministic and it outranks any narrative.
* A model that omits the stated limitations is refused, because an interpretation that
  only lists strengths is advocacy rather than analysis.

Domain-agnostic on purpose: nothing here names a benchmark, a stratum, or a metric.
It takes whatever numbers the package carries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_OUTCOME_NAME = "system-authored-outcome.json"

# Numbers with this many significant digits or more must be traceable. Small integers
# like "3 of 12" are structural and are checked separately against the package.
# A digit must FOLLOW a decimal point. `P-20260804-087`: an earlier pattern allowed a
# trailing point, so sentence-ending text like "... step 7." produced the token "7."
# which can never appear in evidence, and the guard penalised correct prose.
_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

VERDICT_KINDS: tuple[str, ...] = (
    "claim_supported",
    "claim_not_supported",
    "inconclusive_underpowered",
)

# A genuine counter-reading names a specific weakness. Restating the conclusion in
# different words is not a counter-reading, however fluently it is written.
#
# `P-20260807-092`: these were originally matched as literal substrings, which failed
# twice over.
#
# 1. LEXICALLY. The list holds "few systems" and "few members", but a correct
#    counter-reading that wrote "rests on only 2 systems" was REFUSED. Identical
#    meaning, absent vocabulary. A guard that grades word choice rather than substance
#    penalises correct reasoning, which is the `P-20260804-087` defect class.
#
# 2. DIRECTIONALLY. Every phrase below argues that a POSITIVE claim is overstated
#    ("crosses zero", "may not generalise", "wide interval"). When the verdict is
#    already `claim_not_supported`, the adversarial direction INVERTS: the strongest
#    case against that conclusion is that the result is HARSHER than warranted, for
#    example that one capped failure dominates a stratum. The original list could not
#    express that at all, so a negative verdict could not satisfy its own guard except
#    by accident.
#
# These are now CONCEPT GROUPS. A counter-reading satisfies the guard by hitting any
# group, and each group holds several surface forms of the same idea. This still
# refuses a bare restatement, because a restatement hits no group, while accepting the
# many legitimate ways to name a specific weakness.
_COUNTER_READING_CONCEPTS: tuple[tuple[str, ...], ...] = (
    # An interval or estimate that fails to exclude the null.
    (
        "crosses zero",
        "includes zero",
        "close to zero",
        "spans zero",
        "straddles zero",
        "contains zero",
        "overlaps",
        "wide interval",
        "wide confidence",
        "substantial uncertainty",
        "far below zero",
    ),
    # A stratum or sample too thin to carry the weight placed on it.
    (
        "too few",
        "few systems",
        "few members",
        "small sample",
        "underpowered",
        "only 2",
        "only two",
        "only 3",
        "only three",
        "single system",
        "one system",
        "a single failure",
        "single failure",
        "rests on only",
        "not representative",
        "sensitive to a single",
        "driven almost entirely",
        "driven entirely",
        "dominated by",
        "dominates",
    ),
    # A competing explanation that the evidence cannot eliminate.
    (
        "confound",
        "selection effect",
        "alternative explanation",
        "cannot rule out",
        "could argue",
        "one could",
        "a reader could",
        "not decisive",
        "may not generalis",
        "may not generaliz",
        "did not transfer",
        "questioning the reliability",
        "artefact",
        "artifact",
    ),
    # For a NEGATIVE verdict: the case that the result is harsher than warranted,
    # or that the measurement rather than the method produced the number.
    (
        "capped",
        "failure loss",
        "infrastructure",
        "wall-time",
        "wall time",
        "timeout",
        "timed out",
        "would be less negative",
        "excluding",
        "if that system",
        "harsher",
        "overstates the failure",
        "not a scientific failure",
    ),
)


class SystemAuthoredOutcomeError(RuntimeError):
    """Raised when an authored interpretation cannot be trusted as authored."""


class NumericTraceabilityAudit(StrictFrozenModel):
    """Deterministic check that every number in the prose exists in the evidence."""

    schema_version: Literal["numeric-traceability-audit-v1"] = (
        "numeric-traceability-audit-v1"
    )
    checked_number_count: int = Field(ge=0)
    traceable_number_count: int = Field(ge=0)
    untraceable_numbers: tuple[str, ...]
    passed: bool
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> NumericTraceabilityAudit:
        if self.traceable_number_count > self.checked_number_count:
            raise SystemAuthoredOutcomeError(
                "traceable count cannot exceed the checked count"
            )
        if self.passed != (not self.untraceable_numbers):
            raise SystemAuthoredOutcomeError(
                "the audit verdict contradicts its own untraceable list"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise SystemAuthoredOutcomeError("traceability audit hash mismatch")
        return self


class AuthoredInterpretation(StrictFrozenModel):
    """The model's OWN reading of its own result."""

    schema_version: Literal["authored-interpretation-v1"] = "authored-interpretation-v1"
    verdict: str
    what_the_evidence_supports: str = Field(min_length=80, max_length=6_000)
    what_the_evidence_does_not_support: str = Field(min_length=80, max_length=6_000)
    strongest_counter_reading: str = Field(min_length=40, max_length=4_000)
    limitations: tuple[str, ...] = Field(min_length=2)
    # The model must state this itself, so the guard can compare it against the
    # deterministic gate rather than trusting the narrative.
    claims_frozen_gate_passed: bool

    @model_validator(mode="after")
    def _validate(self) -> AuthoredInterpretation:
        if self.verdict not in VERDICT_KINDS:
            raise SystemAuthoredOutcomeError(f"unsupported verdict: {self.verdict}")
        return self


class SystemAuthoredOutcome(StrictFrozenModel):
    """An authored interpretation plus the audits that make it trustworthy."""

    schema_version: Literal["system-authored-outcome-v1"] = "system-authored-outcome-v1"
    lineage_id: str = Field(min_length=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpretation: AuthoredInterpretation
    traceability: NumericTraceabilityAudit
    frozen_gate_passed: bool
    verdict_consistent_with_gate: bool
    accepted: bool
    refusal_reasons: tuple[str, ...]
    model_name: str = Field(min_length=1)
    reasoning_tokens: int = Field(ge=0)
    authored_by_model: Literal[True] = True
    hand_written_prose_count: Literal[0] = 0
    is_evidence: Literal[False] = False
    publication_ready: Literal[False] = False
    created_at: datetime
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SystemAuthoredOutcome:
        if self.accepted != (
            self.traceability.passed
            and self.verdict_consistent_with_gate
            and not self.refusal_reasons
        ):
            raise SystemAuthoredOutcomeError(
                "the acceptance flag contradicts its own audits"
            )
        # A narrative claiming success while the deterministic gate failed is refused.
        # The gate outranks the prose, always.
        if (
            self.interpretation.claims_frozen_gate_passed
            and not self.frozen_gate_passed
            and self.accepted
        ):
            raise SystemAuthoredOutcomeError(
                "an interpretation claiming the gate passed cannot be accepted while "
                "the deterministic gate failed"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"outcome_hash", "output_path"})
        )
        if self.outcome_hash != expected:
            raise SystemAuthoredOutcomeError("system authored outcome hash mismatch")
        return self


def collect_evidence_numbers(*sources: Mapping[str, Any]) -> set[str]:
    """Every number appearing anywhere in the evidence, in several renderings.

    A model legitimately writes `-0.8449` for a recorded `-0.8448548894388439`, so each
    evidence number is registered at full precision and at 2 through 6 decimal places,
    plus its integer form. Anything the model writes that is not in this set was not in
    the evidence.
    """

    allowed: set[str] = set()

    def register(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float):
            number = float(value)
            allowed.add(str(value))
            allowed.add(repr(number))
            if number.is_integer():
                allowed.add(str(int(number)))
            for places in range(2, 7):
                allowed.add(f"{number:.{places}f}")
                allowed.add(f"{number:+.{places}f}")
            allowed.add(f"{number:g}")
            allowed.add(f"{number:e}")
            return
        if isinstance(value, str):
            # Numbers embedded in recorded strings count as evidence too.
            for token in _NUMBER_PATTERN.findall(value):
                if token not in {"-", "", "+"}:
                    allowed.add(token)
            return
        if isinstance(value, Mapping):
            for item in value.values():
                register(item)
            return
        if isinstance(value, Sequence):
            for item in value:
                register(item)

    for source in sources:
        register(source)
    return allowed


def audit_numeric_traceability(
    *, prose: str, allowed_numbers: set[str]
) -> NumericTraceabilityAudit:
    """Refuse any number in the prose that is absent from the evidence.

    This is what makes "system-authored" mean something. Without it the model could
    write a plausible narrative around numbers that were never measured.
    """

    found = [
        token
        for token in _NUMBER_PATTERN.findall(prose)
        if token not in {"-", "+", ""}
    ]
    untraceable: list[str] = []
    for token in found:
        if token in allowed_numbers:
            continue
        # Tolerate a trailing-zero or sign rendering difference only.
        try:
            value = float(token)
        except ValueError:
            continue
        variants = {
            str(value),
            f"{value:g}",
            f"{value:+g}",
            str(int(value)) if value.is_integer() else str(value),
        }
        for places in range(0, 7):
            variants.add(f"{value:.{places}f}")
            variants.add(f"{value:+.{places}f}")
        if variants & allowed_numbers:
            continue
        untraceable.append(token)

    payload: dict[str, Any] = {
        "schema_version": "numeric-traceability-audit-v1",
        "checked_number_count": len(found),
        "traceable_number_count": len(found) - len(untraceable),
        "untraceable_numbers": tuple(dict.fromkeys(untraceable)),
        "passed": not untraceable,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return NumericTraceabilityAudit.model_validate(payload)


def _messages(
    *, package: Mapping[str, Any], estimand: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Hand the model its own numbers and ask for its own reading. No steer."""

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "verdict",
            "what_the_evidence_supports",
            "what_the_evidence_does_not_support",
            "strongest_counter_reading",
            "limitations",
            "claims_frozen_gate_passed",
        ],
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICT_KINDS)},
            "what_the_evidence_supports": {"type": "string"},
            "what_the_evidence_does_not_support": {"type": "string"},
            "strongest_counter_reading": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "claims_frozen_gate_passed": {"type": "boolean"},
        },
    }
    context = {
        "your_own_measurement": {
            key: package.get(key)
            for key in (
                "selected_candidate_id",
                "selection_basis",
                "overall_median_log_effect",
                "bootstrap_lower",
                "bootstrap_upper",
                "ode_stratum_median",
                "pde_stratum_median",
                "gate_checks",
                "search_freeze_receipt",
                "system_effects",
            )
            if key in package
        },
        "frozen_thresholds_committed_before_you_saw_any_number": dict(estimand),
        "instruction": (
            "This is YOUR result: you authored the method, revised it, and produced "
            "these numbers. Write your own interpretation. State what this evidence "
            "supports, what it does not support, and the strongest reading that "
            "argues AGAINST your own conclusion. Report whether the frozen gate "
            "passed."
        ),
        "what_strongest_counter_reading_means": (
            "It is the best case someone could make that your conclusion is WRONG or "
            "overstated. It must cite a specific quantity that WEAKENS your reading, "
            "and that quantity must not be merely the same numbers you used to "
            "support the conclusion. Examples of the shape required: an interval bound "
            "that crosses the threshold, a stratum resting on few members, a confound "
            "you cannot rule out, or a reason the result may not generalise. "
            "Restating your conclusion in different words will be REFUSED."
        ),
        "hard_constraints": [
            "Every number you write must already appear in the evidence above. A "
            "number that is not there will be detected and your interpretation "
            "refused.",
            "The frozen gate is deterministic and outranks your narrative. Do not "
            "claim it passed if it did not.",
            "A null or negative result is a valid outcome. Do not argue around it.",
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are the autonomous research system interpreting your own "
                "measured result. Be accurate rather than favourable: an "
                "interpretation that overstates its own evidence is worse than a "
                "negative one, because it cannot be trusted again.\n\n"
                "Think first, then answer. Your reasoning is process provenance only "
                "and is never scientific evidence.\n"
                "Return exactly one json object satisfying this schema, with no prose "
                "outside it; local strict validation will reject any extra, missing, "
                "or invalid field: " + json.dumps(schema, ensure_ascii=False, sort_keys=True)
            ),
        },
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, sort_keys=True),
        },
    ]


def author_outcome_interpretation(
    *,
    lineage_id: str,
    package_path: Path | str,
    frozen_plan_path: Path | str,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
) -> SystemAuthoredOutcome:
    """Ask the system to interpret its own result, then audit what it wrote."""

    package = json.loads(Path(package_path).read_text(encoding="utf-8"))
    estimand = json.loads(Path(frozen_plan_path).read_text(encoding="utf-8"))["estimand"]
    gate = package.get("gate_checks") or {}
    if not gate:
        raise SystemAuthoredOutcomeError(
            "the package carries no gate checks, so no interpretation can be audited "
            "against a deterministic verdict"
        )
    gate_passed = all(bool(value) for value in gate.values())

    result = completion(
        messages=_messages(package=package, estimand=estimand),
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=240,
        max_tokens=6_000,
        temperature=0.2,
        thinking_mode="enabled",
        thinking_budget=4_000,
        response_schema=None,
        response_schema_name="authored_interpretation",
    )
    interpretation = AuthoredInterpretation.model_validate(
        {"schema_version": "authored-interpretation-v1", **result.parsed_json}
    )

    prose = "\n".join(
        [
            interpretation.what_the_evidence_supports,
            interpretation.what_the_evidence_does_not_support,
            interpretation.strongest_counter_reading,
            *interpretation.limitations,
        ]
    )
    traceability = audit_numeric_traceability(
        prose=prose,
        allowed_numbers=collect_evidence_numbers(package, estimand),
    )

    reasons: list[str] = []
    if not traceability.passed:
        reasons.append(
            "the interpretation states numbers absent from its own evidence: "
            f"{list(traceability.untraceable_numbers)}"
        )
    # `P-20260804-086`: the counter-reading field is meant to hold the strongest
    # argument AGAINST the model's own conclusion, and the first live run satisfied it
    # with a restatement of the conclusion instead. A field satisfiable by restatement
    # is not an adversarial check, so it now has to cite a specific quantity that
    # WEAKENS the reading, and cannot simply repeat the supporting section's numbers.
    counter = interpretation.strongest_counter_reading
    counter_numbers = {
        token for token in _NUMBER_PATTERN.findall(counter) if token not in {"-", "+", ""}
    }
    support_numbers = {
        token
        for token in _NUMBER_PATTERN.findall(interpretation.what_the_evidence_supports)
        if token not in {"-", "+", ""}
    }
    if not counter_numbers:
        reasons.append(
            "the counter-reading cites no quantity, so it cannot be checked; it must "
            "name a specific number that weakens the conclusion"
        )
    elif counter_numbers <= support_numbers:
        reasons.append(
            "the counter-reading cites only the same quantities as the supporting "
            "section, so it restates the conclusion rather than arguing against it"
        )
    counter_lower = counter.lower()
    matched_concepts = [
        index
        for index, group in enumerate(_COUNTER_READING_CONCEPTS)
        if any(phrase in counter_lower for phrase in group)
    ]
    if not matched_concepts:
        reasons.append(
            "the counter-reading does not argue against the conclusion; it must "
            "identify a specific weakness such as an interval that fails to exclude "
            "zero, a stratum too thin to carry the conclusion, a confound that cannot "
            "be ruled out, or (for a negative verdict) a reason the measured result is "
            "harsher than the method warrants"
        )

    consistent = interpretation.claims_frozen_gate_passed == gate_passed
    if not consistent:
        reasons.append(
            f"the interpretation claims gate_passed="
            f"{interpretation.claims_frozen_gate_passed} while the deterministic gate "
            f"is {gate_passed}"
        )
    # A verdict of success while the gate failed is a contradiction, not a reading.
    if interpretation.verdict == "claim_supported" and not gate_passed:
        reasons.append(
            "the interpretation claims the method claim is supported while the frozen "
            "gate failed; the gate outranks the narrative"
        )

    usage = result.usage if isinstance(result.usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning_tokens = 0
    if isinstance(details, dict):
        reasoning_tokens = int(details.get("reasoning_tokens") or 0)

    now = clock or datetime.now(timezone.utc)
    output_path = Path(output_dir).resolve() / _OUTCOME_NAME
    payload: dict[str, Any] = {
        "schema_version": "system-authored-outcome-v1",
        "lineage_id": lineage_id,
        "package_hash": str(package["package_hash"]),
        "interpretation": interpretation.model_dump(mode="json"),
        "traceability": traceability.model_dump(mode="json"),
        "frozen_gate_passed": gate_passed,
        "verdict_consistent_with_gate": consistent,
        "accepted": traceability.passed and consistent and not reasons,
        "refusal_reasons": tuple(reasons),
        "model_name": result.model_name,
        "reasoning_tokens": reasoning_tokens,
        "authored_by_model": True,
        "hand_written_prose_count": 0,
        "is_evidence": False,
        "publication_ready": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["outcome_hash"] = canonical_model_hash(payload)
    payload["output_path"] = output_path.as_posix()
    outcome = SystemAuthoredOutcome.model_validate(payload)
    write_json_model(output_path, outcome)
    return outcome
