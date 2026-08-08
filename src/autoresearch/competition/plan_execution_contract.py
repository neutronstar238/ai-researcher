"""Compile an approved research plan into a source-verifiable execution contract.

The plan-confirmation gate historically bound only a hash to an execution record.
That proved which text had been approved, but not that the generated implementation
performed the method described by that text.  A plan could therefore prescribe one
method family while the candidate source implemented another.

This module closes that gap without asking a language model to grade itself:

* the scientific fields of the approved plan are copied verbatim into a hash-bound
  contract;
* the model-authored ``code_agent_brief`` supplies two to eight stable method tokens;
* a deterministic AST audit accepts a token only when it appears in a callable that
  is actually reached from ``fit_equations`` or ``predict_derivative``. Comments,
  docstrings, variable names, implementation summaries, and dead helper functions
  cannot satisfy the gate.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.research.plan_confirmation import compute_plan_hash
from autoresearch.schemas import ResearchPlan

_CONTRACT_NAME = "plan-execution-contract.json"
_SCIENTIFIC_FIELDS: tuple[str, ...] = (
    "title",
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "methods",
    "experiments",
    "baselines",
    "metrics",
    "expected_results",
    "code_agent_brief",
)
_EXPLICIT_TOKEN_PATTERN = re.compile(
    r"required_method_tokens\s*=\s*\[(?P<body>[^\]]+)\]", re.IGNORECASE
)
_CONFIG_VALUE_PATTERN = re.compile(
    r"(?:--config(?:uration)?\s+|\bconfig(?:uration)?\s*[:=]\s*)"
    r"(?P<value>[A-Za-z][A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_CONFIG_FILE_PATTERN = re.compile(
    r"\b(?P<value>[A-Za-z][A-Za-z0-9_-]+)\.(?:yaml|yml|toml|json)\b",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_GENERIC_TOKENS = frozenset(
    {
        "config",
        "configuration",
        "candidate",
        "method",
        "model",
        "official",
        "panel",
        "python",
        "runner",
        "script",
        "spec",
        "test",
        "tests",
        "yaml",
        "yml",
        "toml",
        "json",
    }
)
_EXECUTION_ROOTS = ("fit_equations", "predict_derivative")


class PlanExecutionContractError(ValueError):
    """Raised when plan-to-code alignment cannot be proved."""


class PlanExecutionContract(StrictFrozenModel):
    """Exact approved science plus the code-level method identity it requires."""

    schema_version: Literal["plan-execution-contract-v1"] = "plan-execution-contract-v1"
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_plan: dict[str, Any]
    required_method_tokens: tuple[str, ...] = Field(min_length=2, max_length=8)
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> PlanExecutionContract:
        if set(self.scientific_plan) != set(_SCIENTIFIC_FIELDS):
            raise PlanExecutionContractError(
                "plan execution contract does not carry the exact required scientific fields"
            )
        if len(self.required_method_tokens) != len(set(self.required_method_tokens)):
            raise PlanExecutionContractError("required method tokens must be unique")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"contract_hash"})
        )
        if self.contract_hash != expected:
            raise PlanExecutionContractError("plan execution contract hash mismatch")
        return self


class CandidatePlanAlignmentAudit(StrictFrozenModel):
    """Deterministic proof that one exact source implements the approved method."""

    schema_version: Literal["candidate-plan-alignment-audit-v1"] = (
        "candidate-plan-alignment-audit-v1"
    )
    candidate_id: str = Field(min_length=1)
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_method_tokens: tuple[str, ...] = Field(min_length=2, max_length=8)
    reachable_identifier_evidence: dict[str, tuple[str, ...]]
    missing_method_tokens: tuple[str, ...]
    parse_error: str | None = None
    passed: bool
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> CandidatePlanAlignmentAudit:
        expected_pass = not self.missing_method_tokens and self.parse_error is None
        if self.passed != expected_pass:
            raise PlanExecutionContractError(
                "candidate plan-alignment verdict contradicts its evidence"
            )
        if set(self.reachable_identifier_evidence) != set(self.required_method_tokens):
            raise PlanExecutionContractError(
                "candidate plan-alignment evidence does not cover every required token"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise PlanExecutionContractError("candidate plan-alignment audit hash mismatch")
        return self


def extract_required_method_tokens(code_agent_brief: str) -> tuple[str, ...]:
    """Read stable implementation tokens authored as part of the plan.

    New plans must use ``required_method_tokens=[token_a, token_b]``.  The config-name
    fallback keeps already-retained plans auditable: a brief that names
    ``integral_bayesian_constrained_lars.yaml`` unambiguously commits to those method
    tokens even though it predates the explicit syntax.
    """

    explicit = _EXPLICIT_TOKEN_PATTERN.search(code_agent_brief)
    raw_values: list[str] = []
    if explicit is not None:
        raw_values.extend(_TOKEN_PATTERN.findall(explicit.group("body")))
    else:
        config_values = [
            match.group("value") for match in _CONFIG_VALUE_PATTERN.finditer(code_agent_brief)
        ]
        config_values.extend(
            match.group("value")
            for match in _CONFIG_FILE_PATTERN.finditer(code_agent_brief)
        )
        for value in config_values:
            stem = value.rsplit(".", 1)[0]
            raw_values.extend(_TOKEN_PATTERN.findall(stem.replace("-", "_")))

    tokens: list[str] = []
    for value in raw_values:
        token = value.casefold()
        if len(token) < 4 or token in _GENERIC_TOKENS or token in tokens:
            continue
        tokens.append(token)
    if not 2 <= len(tokens) <= 8:
        raise PlanExecutionContractError(
            "code_agent_brief must author 2-8 distinctive method identifiers using "
            "required_method_tokens=[token_a, token_b]; generic interface names do "
            "not prove which scientific method the code must implement"
        )
    return tuple(tokens)


def compile_plan_execution_contract(
    plan: ResearchPlan | Mapping[str, Any],
) -> PlanExecutionContract:
    """Compile the exact scientific plan into its deterministic execution contract."""

    validated = plan if isinstance(plan, ResearchPlan) else ResearchPlan.model_validate(plan)
    scientific_plan = {
        field: validated.model_dump(mode="json")[field] for field in _SCIENTIFIC_FIELDS
    }
    payload: dict[str, Any] = {
        "schema_version": "plan-execution-contract-v1",
        "approved_plan_hash": compute_plan_hash(validated),
        "scientific_plan": scientific_plan,
        "required_method_tokens": extract_required_method_tokens(
            validated.code_agent_brief
        ),
    }
    payload["contract_hash"] = canonical_model_hash(payload)
    return PlanExecutionContract.model_validate(payload)


def write_plan_execution_contract(
    *, contract: PlanExecutionContract, output_dir: Path | str
) -> Path:
    """Persist the contract once, refusing a different contract in the same lineage."""

    path = Path(output_dir).resolve() / _CONTRACT_NAME
    if path.is_file():
        existing = PlanExecutionContract.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if existing != contract:
            raise PlanExecutionContractError(
                "lineage already contains a different plan execution contract"
            )
        return path
    write_json_model(path, contract)
    return path


def load_plan_execution_contract(output_dir: Path | str) -> PlanExecutionContract:
    path = Path(output_dir).resolve() / _CONTRACT_NAME
    if not path.is_file():
        raise PlanExecutionContractError(
            f"missing plan execution contract at {path}; execution is blocked"
        )
    return PlanExecutionContract.model_validate_json(path.read_text(encoding="utf-8"))


def audit_candidate_plan_alignment(
    *, candidate_id: str, source_text: str, contract: PlanExecutionContract
) -> CandidatePlanAlignmentAudit:
    """Prove required method tokens occur in code reachable from the public API."""

    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    parse_error: str | None = None
    identifiers: set[str] = set()
    try:
        tree = ast.parse(source_text)
        identifiers = _reachable_identifiers(tree)
    except SyntaxError as exc:
        parse_error = f"SyntaxError line {exc.lineno}: {exc.msg}"

    evidence: dict[str, tuple[str, ...]] = {}
    missing: list[str] = []
    for token in contract.required_method_tokens:
        matches = tuple(
            sorted(
                identifier
                for identifier in identifiers
                if token in _identifier_terms(identifier)
            )
        )
        evidence[token] = matches
        if not matches:
            missing.append(token)

    payload: dict[str, Any] = {
        "schema_version": "candidate-plan-alignment-audit-v1",
        "candidate_id": candidate_id,
        "approved_plan_hash": contract.approved_plan_hash,
        "plan_contract_hash": contract.contract_hash,
        "source_sha256": source_sha256,
        "required_method_tokens": contract.required_method_tokens,
        "reachable_identifier_evidence": evidence,
        "missing_method_tokens": tuple(missing),
        "parse_error": parse_error,
        "passed": not missing and parse_error is None,
    }
    payload["audit_hash"] = canonical_model_hash(payload)
    return CandidatePlanAlignmentAudit.model_validate(payload)


def require_candidate_plan_alignment(
    *,
    candidates: Sequence[Any],
    contract: PlanExecutionContract,
) -> None:
    """Fail before execution unless every promoted candidate binds to this contract."""

    if not candidates:
        raise PlanExecutionContractError(
            "no plan-aligned candidate is available for execution"
        )
    failures: list[str] = []
    for candidate in candidates:
        alignment = getattr(candidate, "plan_alignment", None)
        if alignment is None:
            failures.append(f"{candidate.candidate_id}: missing plan-alignment audit")
            continue
        if alignment.approved_plan_hash != contract.approved_plan_hash:
            failures.append(f"{candidate.candidate_id}: approved plan hash mismatch")
        if alignment.plan_contract_hash != contract.contract_hash:
            failures.append(f"{candidate.candidate_id}: plan contract hash mismatch")
        if alignment.source_sha256 != candidate.source_sha256:
            failures.append(f"{candidate.candidate_id}: source hash mismatch")
        if not alignment.passed:
            failures.append(
                f"{candidate.candidate_id}: missing method tokens "
                f"{list(alignment.missing_method_tokens)}"
            )
    if failures:
        raise PlanExecutionContractError(
            "candidate implementation is not aligned with the approved research plan: "
            + "; ".join(failures)
        )


def _reachable_identifiers(tree: ast.Module) -> set[str]:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    queue = [name for name in _EXECUTION_ROOTS if name in functions]
    reachable: set[str] = set()
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called = node.func.id
                if called in functions and called not in reachable:
                    queue.append(called)

    # Only CALLABLE names count. Merely assigning a variable called
    # `integral_bayesian` inside fit_equations is labels, not implementation evidence.
    identifiers = set(reachable)
    for name in reachable:
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                identifiers.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                identifiers.add(node.func.attr)
    return identifiers


def _identifier_terms(identifier: str) -> set[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return {
        item.casefold()
        for item in re.split(r"[^A-Za-z0-9]+", separated)
        if item
    }
