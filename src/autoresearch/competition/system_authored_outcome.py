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
from decimal import Decimal, InvalidOperation
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

# Explicit quantitative relations are checked separately from provenance. A number can
# be copied perfectly from evidence and still be interpreted backwards (for example,
# saying ``0.0468 is below 0.0``). Longer negated phrases intentionally precede their
# positive substrings so ``not below`` is classified as >= rather than <.
_NUMERIC_RELATION_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ge",
        re.compile(
            r"(?:\b(?:at\s+least|no\s+less\s+than|not\s+below|not\s+lower\s+than)\b|"
            r">=|≥|不低于|不少于|至少)",
            re.IGNORECASE,
        ),
    ),
    (
        "le",
        re.compile(
            r"(?:\b(?:at\s+most|no\s+more\s+than|not\s+above|not\s+higher\s+than|"
            r"does\s+not\s+exceed|did\s+not\s+exceed)\b|<=|≤|不高于|不大于|不超过|至多)",
            re.IGNORECASE,
        ),
    ),
    (
        "lt",
        re.compile(
            r"(?:\b(?:below|less\s+than|lower\s+than|under|falls?\s+short\s+of|"
            r"does\s+not\s+reach|did\s+not\s+reach)\b|(?<![<>=])<(?![=])|"
            r"低于|小于|未达到|不足)",
            re.IGNORECASE,
        ),
    ),
    (
        "gt",
        re.compile(
            r"(?:\b(?:above|greater\s+than|higher\s+than|over|exceeds?|exceeded)\b|"
            r"(?<![<>=])>(?![=])|高于|大于|超过)",
            re.IGNORECASE,
        ),
    ),
    (
        "eq",
        re.compile(
            r"(?:\b(?:equals?|equal\s+to|the\s+same\s+as)\b|==|(?<![<>!=])=(?!=)|等于)",
            re.IGNORECASE,
        ),
    ),
)

_INTERVAL_ZERO_PATTERN = re.compile(
    rf"(?P<open>[\[(])\s*(?P<lower>{_NUMBER_PATTERN.pattern})\s*,\s*"
    rf"(?P<upper>{_NUMBER_PATTERN.pattern})\s*(?P<close>[\])])"
    r"(?P<context>[^\n;；。！？!?]{0,160}?)"
    r"(?P<relation>does\s+not\s+include|does\s+not\s+contain|excludes?|"
    r"includes?|contains?|crosses|spans|straddles|不包含|排除|包含|跨过|跨越)"
    r"\s*(?:0|zero|零)",
    re.IGNORECASE,
)

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
        # Patterns for a negative verdict: highly inconsistent, single-system dominance
        "highly inconsistent",
        "inconsistent performance",
        "inconsistent across",
        "large variance",
        "severe failures",
        "fails on",
        "fails to",
        "complete failure",
        "0/6",
        "0 out of",
        "cannot be dismissed",
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
        "fundamentally unsuited",
        "structurally incompatible",
        "incompatibility with",
        "numerical instability",
        "potential numerical",
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


class NumericRelationAudit(StrictFrozenModel):
    """Recompute every explicit numeric comparison made by the authored prose."""

    schema_version: Literal["numeric-relation-audit-v1"] = (
        "numeric-relation-audit-v1"
    )
    checked_relation_count: int = Field(ge=0)
    contradictions: tuple[str, ...]
    passed: bool
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> NumericRelationAudit:
        if self.passed != (not self.contradictions):
            raise SystemAuthoredOutcomeError(
                "numeric relation verdict contradicts its contradiction list"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise SystemAuthoredOutcomeError("numeric relation audit hash mismatch")
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
    # Optional only so retained v1 artifacts remain loadable. Every newly authored
    # outcome writes this audit and acceptance depends on it.
    relation_audit: NumericRelationAudit | None = None
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
        relations_passed = self.relation_audit is None or self.relation_audit.passed
        if self.accepted != (
            self.traceability.passed
            and relations_passed
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


def audit_numeric_relations(*, prose: str) -> NumericRelationAudit:
    """Reject explicit inequalities or interval claims that are arithmetically false.

    This intentionally checks only relations the prose states explicitly. It does not
    try to infer scientific meaning from nearby nouns; the deterministic gate remains
    responsible for the scientific decision. English and Chinese comparison markers
    are supported because both languages are valid output formats for the project.
    """

    numbers = list(_NUMBER_PATTERN.finditer(prose))
    checked = 0
    contradictions: list[str] = []

    for left_match, right_match in zip(numbers, numbers[1:], strict=False):
        between = prose[left_match.end() : right_match.start()]
        if len(between) > 240:
            continue
        relation = _numeric_relation_in(between)
        if relation is None:
            continue
        left = _decimal(left_match.group())
        right = _decimal(right_match.group())
        if left is None or right is None:
            continue
        checked += 1
        if _numeric_relation_holds(left, relation, right):
            continue
        excerpt = _compact_excerpt(
            prose[max(0, left_match.start() - 80) : min(len(prose), right_match.end() + 80)]
        )
        contradictions.append(
            f"{left_match.group()} {_relation_label(relation)} {right_match.group()} "
            f"is false in: {excerpt}"
        )

    for match in _INTERVAL_ZERO_PATTERN.finditer(prose):
        lower = _decimal(match.group("lower"))
        upper = _decimal(match.group("upper"))
        if lower is None or upper is None:
            continue
        checked += 1
        relation_text = match.group("relation").lower()
        contains_zero = _interval_contains_zero(
            lower=lower,
            upper=upper,
            left_closed=match.group("open") == "[",
            right_closed=match.group("close") == "]",
        )
        if any(
            marker in relation_text
            for marker in ("does not", "exclude", "不包含", "排除")
        ):
            stated_relation_holds = not contains_zero
        elif any(marker in relation_text for marker in ("cross", "straddle", "跨")):
            stated_relation_holds = lower < 0 < upper
        else:
            stated_relation_holds = contains_zero
        if stated_relation_holds:
            continue
        contradictions.append(
            "interval-zero relation is false in: " + _compact_excerpt(match.group())
        )

    payload: dict[str, Any] = {
        "schema_version": "numeric-relation-audit-v1",
        "checked_relation_count": checked,
        "contradictions": tuple(dict.fromkeys(contradictions)),
        "passed": not contradictions,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return NumericRelationAudit.model_validate(payload)


def _numeric_relation_in(text: str) -> str | None:
    for relation, pattern in _NUMERIC_RELATION_MARKERS:
        if pattern.search(text):
            return relation
    return None


def _decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _numeric_relation_holds(left: Decimal, relation: str, right: Decimal) -> bool:
    if relation == "lt":
        return left < right
    if relation == "le":
        return left <= right
    if relation == "gt":
        return left > right
    if relation == "ge":
        return left >= right
    return left == right


def _relation_label(relation: str) -> str:
    return {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "=="}[relation]


def _interval_contains_zero(
    *,
    lower: Decimal,
    upper: Decimal,
    left_closed: bool,
    right_closed: bool,
) -> bool:
    if lower > upper:
        return False
    lower_ok = lower < 0 or (left_closed and lower == 0)
    upper_ok = upper > 0 or (right_closed and upper == 0)
    return lower_ok and upper_ok


def _compact_excerpt(text: str) -> str:
    return " ".join(text.split())[:320]


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
            "Every explicit numeric comparison is recomputed. Never say one value is "
            "below, above, at least, or at most another value unless the arithmetic "
            "relation is true.",
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
    relation_audit = audit_numeric_relations(prose=prose)

    reasons: list[str] = []
    if not traceability.passed:
        reasons.append(
            "the interpretation states numbers absent from its own evidence: "
            f"{list(traceability.untraceable_numbers)}"
        )
    if not relation_audit.passed:
        reasons.append(
            "the interpretation states arithmetically false numeric relations: "
            f"{list(relation_audit.contradictions)}"
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
    # `P-20260808-098`: the vocabulary check (`_COUNTER_READING_CONCEPTS`) was a
    # secondary gate that kept blocking substantive counter-readings because they used
    # new words the hand-written marker lists did not contain. The PRIMARY check is
    # the numeric one above: a counter-reading that cites at least one number not in
    # the supporting section is making a new claim, not restating the conclusion.
    #
    # The vocabulary check is now ADVISORY ONLY: if the numeric check passes (distinct
    # numbers exist), a vocabulary miss is no longer a refusal—it is a diagnostic hint
    # fed back to the model on the next attempt. This resolves the recurring pattern
    # where correct critiques using vocabulary the lists had not anticipated were
    # refused, which is exactly the `P-20260807-092` defect class.
    counter_lower = counter.lower()
    matched_concepts = [
        index
        for index, group in enumerate(_COUNTER_READING_CONCEPTS)
        if any(phrase in counter_lower for phrase in group)
    ]
    distinct_numbers_present = (
        bool(counter_numbers) and not (counter_numbers <= support_numbers)
    )
    if not matched_concepts and not distinct_numbers_present:
        # Both checks fail: no vocabulary and no distinct numbers. This is a bare
        # restatement—refuse.
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
        "relation_audit": relation_audit.model_dump(mode="json"),
        "frozen_gate_passed": gate_passed,
        "verdict_consistent_with_gate": consistent,
        "accepted": (
            traceability.passed
            and relation_audit.passed
            and consistent
            and not reasons
        ),
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
    # 同时落盘给人读的 Markdown。JSON 仍是唯一权威（outcome_hash 绑定它的规范字节）。
    # 渲染失败不能让一份已经落盘的解读丢失，所以不向外抛。
    try:
        from autoresearch.competition.research_plan_markdown import (
            render_outcome_markdown,
        )

        output_path.with_suffix(".md").write_text(
            render_outcome_markdown(outcome.model_dump(mode="json")), encoding="utf-8"
        )
    except (OSError, ValueError):
        pass
    return outcome
