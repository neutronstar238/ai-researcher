"""The system authors its own research plan; deterministic graders teach it.

Why this exists
---------------
`P-20260804-086`: `build_official_research_plan` contains no model call. Its
`problem_statement`, `rationale`, `technical_details`, and `expected_results` are
hardcoded string literals, so the scientific FRAMING of every lineage was authored by
an agent rather than by the system. The measured numbers were the system's; the science
around them was not.

This module inverts that. The model authors every prose field. Deterministic graders
decide whether what it wrote is acceptable, and on failure the exact grader findings go
back to the model so it can repair its own plan. Nothing here composes a scientific
claim, suggests a hypothesis, or supplies a sentence the plan can reuse.

The teaching mechanism
---------------------
A grader that only says "no" teaches nothing. Each refusal returns the specific finding
that caused it, so the model converges on the standard rather than guessing at it. This
is the same loop the candidate implementations already use, applied to the plan.

What is deterministic on purpose, and why
-----------------------------------------
* `evidence_refs` are derived from artifacts that EXIST on disk. If the model supplied
  them it could cite a package that was never written, and a plan that cites
  non-existent evidence is worse than one with no citations.
* `project_id` and `candidate_id` are identifiers, not science.
* Every frozen constraint is passed in as context and never re-authored.

Domain-agnostic: this module names no benchmark, stratum, metric, or method family. It
passes whatever frozen evidence it is given and grades whatever comes back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.research_plan_markdown import (
    render_plan_artifact_markdown,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.system_authored_outcome import (
    audit_numeric_traceability,
    collect_evidence_numbers,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus, audit_research_plan

_PLAN_NAME = "system-authored-research-plan.json"
_MAX_AUTHORING_ATTEMPTS = 4

# A plan must admit that its own expectation may fail. Without this a "plan" is an
# announcement of a result, and the preregistration protects nothing.
# A brief that names a script which does not exist is not executable, however
# command-shaped it looks. `P-20260804-089`: an authored brief invoked
# `pytest test_candidate.py` with flags that exist nowhere in the repository, and the
# quality rubric passed it because it contained the word `pytest`.
#
# Only HOST-relative script paths are checked. A brief legitimately references paths
# inside the pinned container (`/harness/runner.py`), which do not exist on the host,
# so absolute and container paths are out of scope for this guard.
_HOST_SCRIPT_PATTERN = re.compile(
    r"(?<![\w./\\-])(?!/)([A-Za-z0-9_][A-Za-z0-9_./\\-]*\.py)\b"
)

# Absolute paths were originally exempt so a brief could reference the pinned
# container. `P-20260804-089` continued: the system then satisfied the guard by
# inventing CONTAINER paths instead (`/app/run_grammar_conditioned_search.py`), so the
# exemption became an escape hatch. An absolute path is now only accepted if the caller
# declared it as a real entry point.
_ABSOLUTE_SCRIPT_PATTERN = re.compile(r"(/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)\b")

_FALSIFIABILITY_MARKERS: tuple[str, ...] = (
    "negative",
    "null",
    "may fail",
    "does not",
    "would refute",
    "if the effect",
    "not yet observed",
    "fails to",
)


class SystemAuthoredPlanError(RuntimeError):
    """Raised when an authored plan cannot be accepted by its own graders."""


class AuthoredPlanGuardReport(StrictFrozenModel):
    """Every deterministic finding about one authored plan."""

    schema_version: Literal["authored-plan-guard-report-v1"] = (
        "authored-plan-guard-report-v1"
    )
    quality_gate_passed: bool
    quality_gate_issues: tuple[str, ...]
    quality_gate_warnings: tuple[str, ...]
    quality_gate_score: float
    # Guards this module adds on top of the shared quality gate.
    all_cited_evidence_exists: bool
    missing_evidence_paths: tuple[str, ...]
    numbers_traceable: bool
    untraceable_numbers: tuple[str, ...]
    states_falsifiable_expectation: bool
    claims_no_unobserved_result: bool
    named_scripts_exist: bool
    missing_script_paths: tuple[str, ...]
    accepted: bool
    findings: tuple[str, ...]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> AuthoredPlanGuardReport:
        if self.accepted != (not self.findings):
            raise SystemAuthoredPlanError(
                "the guard verdict contradicts its own finding list"
            )
        if self.all_cited_evidence_exists != (not self.missing_evidence_paths):
            raise SystemAuthoredPlanError(
                "the evidence verdict contradicts its own missing list"
            )
        if self.numbers_traceable != (not self.untraceable_numbers):
            raise SystemAuthoredPlanError(
                "the traceability verdict contradicts its own untraceable list"
            )
        if self.named_scripts_exist != (not self.missing_script_paths):
            raise SystemAuthoredPlanError(
                "the script verdict contradicts its own missing list"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"report_hash"})
        )
        if self.report_hash != expected:
            raise SystemAuthoredPlanError("authored plan guard report hash mismatch")
        return self


class SystemAuthoredPlanArtifact(StrictFrozenModel):
    """An authored plan plus the graders that accepted it."""

    schema_version: Literal["system-authored-research-plan-v1"] = (
        "system-authored-research-plan-v1"
    )
    lineage_id: str = Field(min_length=1)
    plan: dict[str, Any]
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    guard_report: AuthoredPlanGuardReport
    authoring_attempts: int = Field(ge=1)
    model_name: str = Field(min_length=1)
    reasoning_tokens: int = Field(ge=0)
    authored_by_model: Literal[True] = True
    hand_written_prose_field_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    is_evidence: Literal[False] = False
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SystemAuthoredPlanArtifact:
        if not self.guard_report.accepted:
            raise SystemAuthoredPlanError(
                "a plan artifact cannot be constructed from a refused plan; the "
                "refusal must be raised rather than persisted as an accepted plan"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected:
            raise SystemAuthoredPlanError("system authored plan artifact hash mismatch")
        return self


def plan_reachable_numbers(evidence_numbers: set[str]) -> set[str]:
    """Extend evidence numbers with arithmetic a PLAN may legitimately perform.

    `P-20260804-087`: a plan does budget arithmetic. Writing "6 systems by 3 seeds is
    18 cells" is correct reasoning, but 18 appears nowhere in the frozen evidence, so
    strict traceability refused a sound plan.

    This registers pairwise products and sums of the small integers already present in
    the evidence, plus small ordinals for enumerated steps. It is deliberately NOT
    applied to result interpretation, where every number is a measured value and must
    match exactly.
    """

    integers: set[int] = set()
    for token in evidence_numbers:
        try:
            value = float(token)
        except ValueError:
            continue
        if value.is_integer() and 0 <= abs(value) <= 10_000:
            integers.add(int(value))

    reachable = set(evidence_numbers)
    # Ordinals for enumerated steps and short lists.
    reachable.update(str(index) for index in range(1, 21))
    for left in integers:
        for right in integers:
            for derived in (left * right, left + right, left - right):
                if 0 <= abs(derived) <= 1_000_000:
                    reachable.add(str(derived))
    return reachable


def _existing_evidence_refs(paths: Sequence[Path | str]) -> tuple[list[str], list[str]]:
    """Split candidate references into those that exist and those that do not."""

    present: list[str] = []
    missing: list[str] = []
    for item in paths:
        path = Path(item)
        if path.exists():
            present.append(path.as_posix())
        else:
            missing.append(path.as_posix())
    return present, missing


def guard_authored_plan(
    *,
    plan: ResearchPlan,
    evidence_numbers: set[str],
    cited_evidence: Sequence[Path | str],
    repo_root: Path = Path("."),
    container_entry_points: Sequence[str] = (),
) -> AuthoredPlanGuardReport:
    """Grade an authored plan deterministically. Every finding is actionable.

    Reuses the shared `audit_research_plan` rubric rather than inventing a second
    standard, then adds the three checks that rubric cannot make: that cited evidence
    exists on disk, that every number traces to the frozen evidence, and that the
    expectation is stated falsifiably.
    """

    audit = audit_research_plan(plan)
    findings: list[str] = [f"quality gate: {item}" for item in audit.issues]

    present, missing = _existing_evidence_refs(cited_evidence)
    if missing:
        findings.append(
            "these cited evidence paths do not exist on disk, so they cannot be "
            f"cited: {missing}"
        )

    prose = "\n".join(
        [
            plan.title,
            plan.problem_statement,
            plan.rationale,
            plan.technical_details,
            plan.methods,
            plan.expected_results,
            plan.code_agent_brief,
            *plan.experiments,
            *plan.risks_and_alternatives,
            str(plan.datasets.get("source", "")),
            str(plan.datasets.get("target", "")),
        ]
    )
    traceability = audit_numeric_traceability(
        prose=prose, allowed_numbers=plan_reachable_numbers(evidence_numbers)
    )
    if not traceability.passed:
        findings.append(
            "these numbers appear in the plan but not in the frozen evidence, so "
            "they were invented rather than derived: "
            f"{list(traceability.untraceable_numbers)}"
        )

    expected_lower = plan.expected_results.lower()
    falsifiable = any(marker in expected_lower for marker in _FALSIFIABILITY_MARKERS)
    if not falsifiable:
        findings.append(
            "expected_results must state what outcome would REFUTE the expectation, "
            "and must acknowledge that a negative or null result is a valid outcome; "
            "a plan that only describes success is an announcement, not a plan"
        )

    # A plan is written before observation, so it must not assert an achieved result.
    # Only PAST-TENSE assertions of an achieved result. `P-20260804-087`: an earlier
    # pattern flagged "outperforms", which is how a legitimate expectation is phrased
    # ("is expected to outperform"), so correct plans were refused.
    achieved = re.search(
        r"\b(?:we (?:achieved|obtained|observed|showed|demonstrated)|"
        r"(?:the )?results? (?:showed|demonstrated|confirmed)|"
        r"(?:has|have|had) outperformed|outperformed the)\b",
        prose.lower(),
    )
    claims_no_result = achieved is None
    if achieved:
        findings.append(
            "the plan asserts an achieved result before any measurement exists: "
            f"{achieved.group(0)!r}; state expectations, not outcomes"
        )

    # A brief naming a script that does not exist cannot be run, so the plan is not
    # executable however command-shaped its prose is.
    brief_text = plan.code_agent_brief + " " + " ".join(plan.experiments)
    named_scripts = sorted(set(_HOST_SCRIPT_PATTERN.findall(brief_text)))
    absent_scripts = [
        name
        for name in named_scripts
        if not (repo_root / name).exists() and not Path(name).exists()
    ]
    # An absolute path must be one the caller declared as real, or it is invented.
    allowed_absolute = set(container_entry_points or ())
    absent_scripts.extend(
        sorted(
            name
            for name in set(_ABSOLUTE_SCRIPT_PATTERN.findall(brief_text))
            if name not in allowed_absolute
        )
    )
    briefs_runnable = not absent_scripts
    if absent_scripts:
        findings.append(
            "the plan names these host scripts, none of which exist, so the brief "
            f"cannot be executed as written: {absent_scripts}. Reference an entry "
            "point that exists, or describe the command in terms of the pinned "
            "container path."
        )

    payload: dict[str, Any] = {
        "schema_version": "authored-plan-guard-report-v1",
        "quality_gate_passed": audit.passed,
        "quality_gate_issues": tuple(audit.issues),
        "quality_gate_warnings": tuple(audit.warnings),
        "quality_gate_score": float(audit.score),
        "all_cited_evidence_exists": not missing,
        "missing_evidence_paths": tuple(missing),
        "numbers_traceable": traceability.passed,
        "untraceable_numbers": traceability.untraceable_numbers,
        "states_falsifiable_expectation": falsifiable,
        "claims_no_unobserved_result": claims_no_result,
        "named_scripts_exist": briefs_runnable,
        "missing_script_paths": tuple(absent_scripts),
        "accepted": not findings,
        "findings": tuple(dict.fromkeys(findings)),
    }
    payload["report_hash"] = canonical_model_hash(payload)
    return AuthoredPlanGuardReport.model_validate(payload)


_AUTHORED_FIELDS: tuple[str, ...] = (
    "title",
    "problem_statement",
    "rationale",
    "technical_details",
    "methods",
    "experiments",
    "expected_results",
    "code_agent_brief",
    "risks_and_alternatives",
    "dataset_source",
    "dataset_target",
    "references",
)

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_AUTHORED_FIELDS),
    "properties": {
        "title": {"type": "string"},
        "problem_statement": {"type": "string"},
        "rationale": {"type": "string"},
        "technical_details": {"type": "string"},
        "methods": {"type": "string"},
        "experiments": {"type": "array", "items": {"type": "string"}, "minItems": 3},
        "expected_results": {"type": "string"},
        "code_agent_brief": {"type": "string"},
        "risks_and_alternatives": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        "dataset_source": {"type": "string"},
        "dataset_target": {"type": "string"},
        "references": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
}


def _authoring_messages(
    *,
    frozen_context: Mapping[str, Any],
    prior_findings: Sequence[str],
    container_entry_points: Sequence[str] = (),
) -> list[dict[str, str]]:
    """Give the system its constraints and its own evidence. Supply no science."""

    instruction = (
        "You are the autonomous research system. Author your OWN research plan for the "
        "next lineage. You decide the problem framing, the mechanism you believe is "
        "responsible, what you will test, and what result would refute you.\n\n"
        "Nothing scientific is supplied to you. The context below carries only frozen "
        "constraints you may not change, and evidence retained from your own prior "
        "lineages. Do not restate the constraints as if they were your reasoning.\n\n"
        "Hard requirements, each enforced by a deterministic grader that will return "
        "its exact findings to you if you fail:\n"
        "1. Every number you write must already appear in the supplied evidence. An "
        "invented number is refused.\n"
        "2. expected_results must state what outcome would REFUTE your expectation, "
        "and must acknowledge that a negative or null result is a valid outcome.\n"
        "3. Do not assert any achieved result. No measurement exists yet.\n"
        "4. Name at least one baseline or control, and concrete evaluation metrics.\n"
        "5. code_agent_brief must be COMMAND-ORIENTED and RUNNABLE: it has to contain "
        "an actual command line, and the grader looks for one of the literal words "
        "'python', 'command', 'script', or 'pytest'. It must NOT invent a script name. "
        "EVERY `.py` path you write is checked, host-relative and absolute alike. The "
        "ONLY entry points that exist are listed below; inventing a plausible-looking "
        "path is refused whether it starts with a slash or not: "
        + (json.dumps(list(container_entry_points)) if container_entry_points else "[]")
        + "\n"
        "6. Use no placeholder text and no reference to any contest or organizer.\n\n"
        "Think first, then answer. Your reasoning is process provenance only and is "
        "never scientific evidence.\n"
        "Return exactly one json object satisfying this schema, with no prose outside "
        "it; local strict validation will reject every extra, missing, or invalid "
        "field: " + json.dumps(_PLAN_SCHEMA, ensure_ascii=False, sort_keys=True)
    )
    if prior_findings:
        instruction += (
            "\n\nYour previous attempt was REFUSED by the graders with these exact "
            "findings. Repair each one. Change only what the findings name; keep the "
            "rest of your plan: " + json.dumps(list(prior_findings), ensure_ascii=False)
        )
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(frozen_context, ensure_ascii=False, sort_keys=True),
        },
    ]


def author_research_plan(
    *,
    lineage_id: str,
    project_id: str,
    candidate_id: str,
    frozen_context: Mapping[str, Any],
    evidence_paths: Sequence[Path | str],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_attempts: int = _MAX_AUTHORING_ATTEMPTS,
    container_entry_points: Sequence[str] = (),
) -> SystemAuthoredPlanArtifact:
    """Have the system author its own plan, and let the graders teach it.

    Raises `SystemAuthoredPlanError` if the system cannot satisfy its own graders
    within `max_attempts`. A plan that cannot pass is not quietly downgraded.
    """

    evidence_numbers = collect_evidence_numbers(dict(frozen_context))
    present, missing_inputs = _existing_evidence_refs(evidence_paths)
    if missing_inputs:
        raise SystemAuthoredPlanError(
            f"cannot author a plan against evidence that does not exist: "
            f"{missing_inputs}"
        )
    if not present:
        raise SystemAuthoredPlanError(
            "a plan must cite at least one retained artifact; authoring against no "
            "evidence would produce an unfalsifiable plan"
        )

    findings: list[str] = []
    last_report: AuthoredPlanGuardReport | None = None
    for attempt in range(1, max_attempts + 1):
        result = completion(
            messages=_authoring_messages(
                frozen_context=frozen_context,
                prior_findings=findings,
                container_entry_points=container_entry_points,
            ),
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=300,
            max_tokens=8_000,
            temperature=0.3,
            thinking_mode="enabled",
            thinking_budget=4_000,
            response_schema=None,
            response_schema_name="authored_research_plan",
        )
        authored = result.parsed_json
        absent = [field for field in _AUTHORED_FIELDS if field not in authored]
        if absent:
            findings = [f"your json object omitted required fields: {absent}"]
            continue

        plan = ResearchPlan.model_validate(
            {
                "project_id": project_id,
                "candidate_id": candidate_id,
                "title": authored["title"],
                "problem_statement": authored["problem_statement"],
                "rationale": authored["rationale"],
                "technical_details": authored["technical_details"],
                "datasets": {
                    "source": authored["dataset_source"],
                    "target": authored["dataset_target"],
                },
                "methods": authored["methods"],
                "experiments": list(authored["experiments"]),
                "expected_results": authored["expected_results"],
                "code_agent_brief": authored["code_agent_brief"],
                "risks_and_alternatives": list(authored["risks_and_alternatives"]),
                "references": list(authored["references"]),
                # Derived, never authored: a model cannot cite what does not exist.
                "evidence_refs": present,
                "status": ResearchPlanStatus.DRAFT,
            }
        )
        report = guard_authored_plan(
            plan=plan,
            evidence_numbers=evidence_numbers,
            cited_evidence=present,
            container_entry_points=container_entry_points,
        )
        last_report = report
        if not report.accepted:
            findings = list(report.findings)
            continue

        audit = audit_research_plan(plan)
        graded = plan.model_copy(
            update={
                "quality_gate": audit.to_dict(),
                "status": ResearchPlanStatus.READY_FOR_APPROVAL,
                "validation_status": audit.verdict,
            }
        )
        usage = result.usage if isinstance(result.usage, dict) else {}
        details = usage.get("completion_tokens_details")
        reasoning_tokens = (
            int(details.get("reasoning_tokens") or 0) if isinstance(details, dict) else 0
        )
        plan_payload = graded.model_dump(mode="json")
        output_path = Path(output_dir).resolve() / _PLAN_NAME
        payload: dict[str, Any] = {
            "schema_version": "system-authored-research-plan-v1",
            "lineage_id": lineage_id,
            "plan": plan_payload,
            "plan_hash": canonical_model_hash(plan_payload),
            "guard_report": report.model_dump(mode="json"),
            "authoring_attempts": attempt,
            "model_name": result.model_name,
            "reasoning_tokens": reasoning_tokens,
            "authored_by_model": True,
            "hand_written_prose_field_count": 0,
            "execution_authorized": False,
            "is_evidence": False,
        }
        payload["artifact_hash"] = canonical_model_hash(payload)
        payload["output_path"] = output_path.as_posix()
        artifact = SystemAuthoredPlanArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
        # 同时落盘一份给人读的 Markdown。JSON 仍是唯一权威（plan_hash 绑定它的规范字节），
        # Markdown 由 JSON 单向派生，且头部写明两个哈希，任何引文都能回溯。
        # 渲染失败不能让一份已经通过全部 grader 的计划丢失，所以这里不向外抛。
        try:
            markdown_path = output_path.with_suffix(".md")
            markdown_path.write_text(
                render_plan_artifact_markdown(artifact.model_dump(mode="json")),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
        return artifact

    detail = list(last_report.findings) if last_report else findings
    raise SystemAuthoredPlanError(
        f"the system could not author a plan its own graders accept in {max_attempts} "
        f"attempts; final findings: {detail}"
    )
