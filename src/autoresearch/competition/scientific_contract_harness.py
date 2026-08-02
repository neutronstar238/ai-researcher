"""Model-originated, result-blind scientific-contract Harness for Task 266.2.

The orchestration layer transports frozen synthetic arrays and validates exact
model-authored source.  It never supplies a candidate scientific library,
feature library, coefficient, equation term, or repair patch.  A model may
author exact replacement patches; the orchestrator only applies them
deterministically against a hash-bound parent.  Every repair is another
provider interaction informed only by synthetic Harness observations.
Official MDBench development and confirmation artifacts are outside the
container mount and outside every prompt.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.autonomous_engine import (
    AutonomousModelInteraction,
    JsonCompletion,
    _call_and_record,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.scientific_contract_recovery import (
    ScientificContractRecoveryPlan,
    ScientificSentinelFixture,
    load_scientific_contract_recovery_plan,
)
from autoresearch.competition.sentinel_identifiability import (
    SentinelIdentifiabilityErratum,
    load_corrected_sentinel_fixtures,
    load_sentinel_identifiability_erratum,
)
from autoresearch.kernel import (
    AdapterStep,
    ContextPolicy,
    CostPolicy,
    EntropyInterventionPolicy,
    EpisodeArtifact,
    EpisodePackage,
    EvaluationPolicy,
    ExactFieldGrader,
    FailureAttributionPolicy,
    FailureDomain,
    GraderKind,
    GraderSpec,
    HarnessAdapterError,
    HarnessRunner,
    HarnessRunRequest,
    HarnessSpec,
    JsonFieldType,
    MemoryPolicy,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelPolicy,
    ModelUsage,
    ObservabilityPolicy,
    PermissionPolicy,
    SideEffectLevel,
    StatePolicy,
    StepOutcome,
    StructuredField,
    StructuredOutputContract,
    TaskContract,
    ToolCallRecord,
    ToolDefinition,
    ToolPolicy,
    TrajectoryKind,
    VerificationPolicy,
)
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.kernel.journal import EventJournal
from autoresearch.llm.client import run_llm_json_completion
from autoresearch.schemas import file_hash

_PACKAGE_NAME = "scientific-contract-harness-package.json"
_MARKDOWN_NAME = "scientific-contract-harness-report.md"
_IDENTITY_NAME = "scientific-contract-harness-identity.json"
_RUNNER_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "experiments"
    / "mdbench"
    / "scientific_contract_harness_runner.py"
)
_IMAGE = "autoresearch-mdbench:task260"
_BENCHMARK_REVISION = "f81813e760325589737fe3311ac8199ecc64188a"
_MAX_REVISIONS = 6
# Task 267.2: the six-revision budget is the SCIENTIFIC budget.  Format/transport
# faults get a separate technical budget so a schema mistake can no longer spend
# the search.  Total revisions stay bounded so a broken candidate cannot loop.
_MAX_SCIENTIFIC_REVISIONS = 6
_MAX_TECHNICAL_REVISIONS = 6
_MAX_TOTAL_REVISIONS = _MAX_SCIENTIFIC_REVISIONS + _MAX_TECHNICAL_REVISIONS
# Bounded re-ask budget for a patch whose old_text could not be addressed
# uniquely. This is text addressing, not science, so it does not consume a
# revision; it is bounded so a persistently mis-addressing model cannot loop.
_MAX_PATCH_ADDRESSING_ATTEMPTS = 3
# Stray JSON delimiters the model sometimes interleaves into a line array. None of
# these can be valid Python at statement level, so discarding them cannot alter
# candidate code. Observed live in run v14 between every real source line.
#
# CAUTION: this must stay narrow. An earlier version stripped any line whose
# STRIPPED form was a delimiter, which silently deleted legitimate Python such as
# a closing `    }` of a returned dict literal and truncated candidate source.
# Only an EXACTLY unindented single delimiter qualifies, because real Python at
# statement level is either indented inside a function or is not a bare bracket.
_DELIMITER_ONLY_LINES: frozenset[str] = frozenset({"]", "}", "],", "},"})
_MAX_SOURCE_BYTES = 80_000
_PREFERRED_SOURCE_CHARACTERS = 12_000
_MAX_OPHIS_CHARACTERS = 8_000
_MAX_AST_NODES = 20_000
# Task 267.1: single machine-checkable source of truth for the learned-equation
# contract.  These tuples MUST stay byte-equal to the whitelists enforced by
# `_validate_equations` and `_validate_factor` in
# `deploy/experiments/mdbench/scientific_contract_harness_runner.py`.  The
# prompt-visible contract is generated from them so an advertised key can never
# again diverge from an accepted key.  Historical defect: the contract advertised
# `term_count` and `factor_count`, which the runner rejected as unknown fields,
# so every schema-obedient candidate failed before its science ever ran.
# Task 267.2: a schema/transport fault means no scientific verdict was reached,
# so it must not consume the bounded scientific revision budget.  A genuine
# scientific verdict must stay fully budget-consuming and fail-closed.
_TECHNICAL_FAILURE_SUFFIXES: frozenset[str] = frozenset(
    {
        # Runner-side schema/transport faults: no scientific verdict was reached.
        "contract_execution_error",
        "no_observation",
        # Static-review faults where the candidate is malformed rather than wrong.
        # Observed live in run v10: the model emitted `source_text` with bare `n`
        # instead of escaped newlines, so 15,767 bytes parsed as one line and
        # `ast.parse` failed at line 1. The science never ran, so charging this to
        # the scientific budget would repeat the v1-v9 mistake in a new shape.
        "syntax_error",
        "source_size",
        "markdown_fence",
        "ast_size",
        "missing_interface",
        "invalid_interface",
    }
)
_SCIENTIFIC_FAILURE_SUFFIXES: frozenset[str] = frozenset(
    {
        # Real scientific or safety verdicts. These must stay budget-consuming and
        # fail-closed: leakage, contamination, and sandbox-escape attempts are
        # substantive violations, not formatting accidents.
        "dunder_access",
        "dynamic_execution",
        "dynamic_structure",
        "fit_after_query",
        "frozen_target_marker",
        "import_not_allowlisted",
        "module_mutation",
        "query_training_reuse",
        "top_level_effect",
        "unbounded_loop",
        "alternative_coefficient_recovery",
        "alternative_term_support",
        "artifact_training_dependence",
        "equation_prediction_consistency",
        "equation_training_dependence",
        "fit_budget",
        "fit_once_query_many",
        "predict_budget",
        "primary_coefficient_recovery",
        "primary_prediction_nmse",
        "primary_term_support",
        "train_shuffle_degradation",
        "zero_null_improvement",
    }
)
_EQUATION_EXACT_FIELDS: tuple[str, ...] = ("target", "intercept", "terms")
_EQUATION_TERM_EXACT_FIELDS: tuple[str, ...] = ("coefficient", "factors")
_EQUATION_FACTOR_EXACT_FIELDS: tuple[str, ...] = ("field", "derivative_axes", "power")
_FORBIDDEN_EQUATION_CONTRACT_KEYS: tuple[str, ...] = ("factor_count", "term_count")
_SOURCE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "response_type",
        "observation",
        "problem",
        "hypothesis",
        "intervention",
        "expected_effect",
        "implementation_summary",
        "source_lines",
    ],
    "properties": {
        "response_type": {"type": "string", "enum": ["scientific_contract_source"]},
        "observation": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "problem": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "hypothesis": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "intervention": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "expected_effect": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "implementation_summary": {
            "type": "string",
            "minLength": 10,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        # Task 267.2 transport repair. Source arrives as one array element per
        # physical line, so a newline escape is never written and therefore can
        # never be lost. Runs v10 and v11 both failed because the model emitted a
        # bare letter `n` where an escaped newline belonged, collapsing 15,767 and
        # 11,059 bytes onto one line; explicit instruction did not fix it, so the
        # transport is changed to make the error structurally impossible.
        "source_lines": {
            "type": "array",
            "minItems": 8,
            "maxItems": 4_000,
            "items": {"type": "string", "maxLength": 2_000},
        },
    },
}
_PATCH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "response_type",
        "observation",
        "problem",
        "hypothesis",
        "intervention",
        "expected_effect",
        "implementation_summary",
        "parent_source_sha256",
        "function_replacements",
    ],
    "properties": {
        "response_type": {"type": "string", "enum": ["scientific_contract_patch"]},
        "observation": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "problem": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "hypothesis": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "intervention": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "expected_effect": {
            "type": "string",
            "minLength": 5,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "implementation_summary": {
            "type": "string",
            "minLength": 10,
            "maxLength": _MAX_OPHIS_CHARACTERS,
        },
        "parent_source_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        # Task 267.2 repair. Text-anchor patching failed live three times in a row
        # (v10 `matched 0 times`, v12 `matched 3 times`, v13 `matched 2 times` on
        # `    n_fields = state.shape[-1]`), each ending the whole search on a
        # copy-paste error. A top-level function name is unique by Python's own
        # rules, so addressing a whole function makes the ambiguity structurally
        # impossible instead of merely less likely.
        "function_replacements": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["function_name", "new_source_lines"],
                "properties": {
                    "function_name": {
                        "type": "string",
                        "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                        "maxLength": 120,
                    },
                    "new_source_lines": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2_000,
                        "items": {"type": "string", "maxLength": 2_000},
                    },
                },
            },
        },
    },
}
_REPAIR_RESPONSE_SCHEMA: dict[str, Any] = _PATCH_RESPONSE_SCHEMA
_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "functools",
    "itertools",
    "math",
    "numpy",
    "pyoperon",
    "pysindy",
    "scipy",
    "sklearn",
    "statistics",
    "typing",
}
_BLOCKED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "print",
    "quit",
    "setattr",
    "vars",
}
_FORBIDDEN_SOURCE_MARKERS = {
    "confirmation",
    "expected_derivative",
    "official_development",
    "task2653",
    "task2661",
    "task26611",
    "764f851f58302e5507ad6f5c3da2f0d6457f91f5eb90e4515c74e3a9e16095a3",
    "4ce5c07ea5fc6af1269a77ae94c582e20891c57236c106ec0e09fee81b38fd07",
    "25085c7803aca04cd4b9ef3c4f317cd03539150d944ef84460744e4895353231",
    "ode-linear-2field",
    "pde-advection-1d",
    "pde-diffusion-1d",
    "pde-advection-diffusion-2d",
    "pde-heat-3d",
    "pde-diffusion-1d-2field",
}


class ScientificContractHarnessError(RuntimeError):
    """Raised when a Task 266.2 evidence boundary cannot be proved."""


class ScientificContractPatchError(ScientificContractHarnessError):
    """A model-authored patch could not be applied deterministically.

    Task 267.2 follow-up. This is a TECHNICAL fault: the candidate's science was
    never reached, so it must be fed back to the model as actionable repair
    context instead of terminating the run. Live runs v10 and v12 both died here
    (`replacement 1 matched 0 times`, `replacement 5 matched 3 times`), which
    ended the whole search on a text-addressing mistake rather than on any
    scientific verdict.
    """

    def __init__(self, message: str, *, failure_code: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class ScientificContractSourceResponse(StrictFrozenModel):
    """Exact model response following an OPHIS-shaped repair cycle."""

    response_type: Literal["scientific_contract_source"]
    observation: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    problem: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    hypothesis: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    intervention: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    expected_effect: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    implementation_summary: str = Field(
        min_length=10,
        max_length=_MAX_OPHIS_CHARACTERS,
    )
    # One element per physical line; see `_SOURCE_RESPONSE_SCHEMA` for why.
    source_lines: tuple[str, ...] = Field(min_length=8, max_length=4_000)

    @property
    def source_text(self) -> str:
        """Reassemble exact model source from its per-line transport.

        Delimiter-only elements are transport artifacts, not code; see
        `ScientificContractFunctionReplacement.normalized_source_lines`.
        """

        return "\n".join(
            line for line in self.source_lines if not _is_transport_delimiter(line)
        )


class ScientificContractFunctionReplacement(StrictFrozenModel):
    """One model-authored whole-function replacement, addressed by name.

    A top-level function name is unique by Python's own rules, so this cannot be
    ambiguous the way a text anchor was.
    """

    function_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=120)
    new_source_lines: tuple[str, ...] = Field(min_length=2, max_length=2_000)

    @property
    def new_source(self) -> str:
        """Reassemble the replacement body from its per-line transport."""

        return "\n".join(self.normalized_source_lines)

    @property
    def normalized_source_lines(self) -> tuple[str, ...]:
        """Drop delimiter-only transport artifacts from the line array.

        Observed live in run v14: the model interleaved a bare `]` between every
        real line, producing `[']', 'def fit_equations(payload):', ']', '    import
        numpy as np', ']', ...]`. The Python itself was intact; only the array
        carried stray JSON delimiters. A line consisting solely of `]`, `}`, `[`,
        `{`, or `,` cannot be valid Python at statement level, so removing such
        elements changes no candidate code while making the transport robust.

        This mirrors the existing `response_transport_normalization` precedent,
        which already discards trailing closing delimiters as transport noise.
        """

        return tuple(
            line for line in self.new_source_lines if not _is_transport_delimiter(line)
        )


class ScientificContractPatchResponse(StrictFrozenModel):
    """A compact model-authored repair bound to the exact previous source."""

    response_type: Literal["scientific_contract_patch"]
    observation: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    problem: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    hypothesis: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    intervention: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    expected_effect: str = Field(min_length=5, max_length=_MAX_OPHIS_CHARACTERS)
    implementation_summary: str = Field(
        min_length=10,
        max_length=_MAX_OPHIS_CHARACTERS,
    )
    parent_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    function_replacements: tuple[ScientificContractFunctionReplacement, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def _validate_unique_targets(self) -> ScientificContractPatchResponse:
        names = [item.function_name for item in self.function_replacements]
        if len(names) != len(set(names)):
            raise ValueError("a patch cannot replace the same function twice")
        return self


class ScientificContractSourceDerivation(StrictFrozenModel):
    """Proof that final source is the deterministic result of a model patch."""

    schema_version: Literal["scientific-contract-source-derivation-v1"] = (
        "scientific-contract-source-derivation-v1"
    )
    parent_revision_id: str = Field(pattern=r"^scientific-contract-r[0-9]{2}$")
    parent_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement_count: int = Field(ge=1, le=16)
    final_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_derivation(self) -> ScientificContractSourceDerivation:
        if self.derivation_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"derivation_hash"})
        ):
            raise ValueError("scientific source derivation hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        parent_revision_id: str,
        parent_source_sha256: str,
        patch_response: ScientificContractPatchResponse,
        final_source_sha256: str,
    ) -> ScientificContractSourceDerivation:
        payload: dict[str, Any] = {
            "schema_version": "scientific-contract-source-derivation-v1",
            "parent_revision_id": parent_revision_id,
            "parent_source_sha256": parent_source_sha256,
            "patch_payload_sha256": canonical_model_hash(
                patch_response.model_dump(mode="json")
            ),
            "replacement_count": len(patch_response.function_replacements),
            "final_source_sha256": final_source_sha256,
        }
        payload["derivation_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)


class ScientificContractSecurityFinding(StrictFrozenModel):
    """One deterministic finding over exact model-authored bytes."""

    code: str
    message: str
    line: int | None = Field(default=None, ge=1)


class ScientificContractStaticReview(StrictFrozenModel):
    """Fail-closed interface, isolation, and targeting review."""

    schema_version: Literal["scientific-contract-static-review-v1"] = (
        "scientific-contract-static-review-v1"
    )
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported_roots: tuple[str, ...]
    function_names: tuple[str, ...]
    findings: tuple[ScientificContractSecurityFinding, ...]
    approved: bool
    exact_source_reviewed: Literal[True] = True
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_review(self) -> ScientificContractStaticReview:
        if self.approved != (not self.findings):
            raise ValueError("scientific static-review verdict contradicts findings")
        if self.report_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"report_hash"})
        ):
            raise ValueError("scientific static-review hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        source_sha256: str,
        imported_roots: Sequence[str],
        function_names: Sequence[str],
        findings: Sequence[ScientificContractSecurityFinding],
    ) -> ScientificContractStaticReview:
        """Sort findings and bind the verdict to exact source bytes."""

        unique_findings = {
            (item.code, item.message, item.line): item for item in findings
        }
        ordered = tuple(
            unique_findings[key]
            for key in sorted(
                unique_findings,
                key=lambda item: (item[0], item[2] or 0, item[1]),
            )
        )
        payload: dict[str, Any] = {
            "schema_version": "scientific-contract-static-review-v1",
            "source_sha256": source_sha256,
            "imported_roots": sorted(set(imported_roots)),
            "function_names": sorted(set(function_names)),
            "findings": [item.model_dump(mode="json") for item in ordered],
            "approved": not ordered,
            "exact_source_reviewed": True,
        }
        payload["report_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)


class ScientificContractRuntimeEnvironment(StrictFrozenModel):
    """Exact no-network container identity used by every revision."""

    image: Literal["autoresearch-mdbench:task260"] = "autoresearch-mdbench:task260"
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    benchmark_revision: Literal[
        "f81813e760325589737fe3311ac8199ecc64188a"
    ] = "f81813e760325589737fe3311ac8199ecc64188a"
    python_version: Literal["3.9.23"] = "3.9.23"
    cpu_cores: Literal[2] = 2
    memory_mb: Literal[512] = 512
    pids_limit: Literal[64] = 64
    read_only_root: Literal[True] = True
    network_default_deny: Literal[True] = True
    cap_drop_all: Literal[True] = True
    no_new_privileges: Literal[True] = True
    environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_environment(self) -> ScientificContractRuntimeEnvironment:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"environment_hash"})
        )
        if self.environment_hash != expected:
            raise ValueError("scientific runtime environment hash mismatch")
        return self

    @classmethod
    def create(cls, *, image_id: str) -> ScientificContractRuntimeEnvironment:
        """Create a hash-bound environment after inspecting the local image."""

        payload: dict[str, Any] = {
            "image": _IMAGE,
            "image_id": image_id,
            "benchmark_revision": _BENCHMARK_REVISION,
            "python_version": "3.9.23",
            "cpu_cores": 2,
            "memory_mb": 512,
            "pids_limit": 64,
            "read_only_root": True,
            "network_default_deny": True,
            "cap_drop_all": True,
            "no_new_privileges": True,
        }
        payload["environment_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)


class ScientificContractHarnessObservation(StrictFrozenModel):
    """Evaluator-owned observation from six corrected synthetic sentinels."""

    schema_version: Literal["scientific-contract-harness-observation-v1"] = (
        "scientific-contract-harness-observation-v1"
    )
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    erratum_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrected_sentinel_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    network_used: Literal[False] = False
    official_development_artifact_reads: Literal[0] = 0
    confirmation_identity_reads: Literal[0] = 0
    confirmation_result_reads: Literal[0] = 0
    sentinel_results: tuple[dict[str, Any], ...]
    sentinel_count: Literal[6] = 6
    passed_sentinel_count: int = Field(ge=0, le=6)
    fit_call_count: int = Field(ge=0, le=18)
    predict_call_count: int = Field(ge=0, le=36)
    passed: bool
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_observation(self) -> ScientificContractHarnessObservation:
        if len(self.sentinel_results) != self.sentinel_count:
            raise ValueError("scientific observation sentinel count mismatch")
        passed_count = sum(item.get("passed") is True for item in self.sentinel_results)
        if self.passed_sentinel_count != passed_count:
            raise ValueError("scientific observation passed count mismatch")
        if self.passed != (passed_count == self.sentinel_count):
            raise ValueError("scientific observation verdict mismatch")
        if self.observation_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"observation_hash"})
        ):
            raise ValueError("scientific observation hash mismatch")
        return self


class ScientificContractRunIdentity(StrictFrozenModel):
    """Result-blind identity frozen before the first model call."""

    schema_version: Literal["scientific-contract-harness-identity-v1"] = (
        "scientific-contract-harness-identity-v1"
    )
    plan_path: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    erratum_path: str
    erratum_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrected_sentinel_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_source_path: str
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    packaged_runner_relative_path: Literal[
        "runner/scientific_contract_harness_runner.py"
    ] = "runner/scientific_contract_harness_runner.py"
    runtime: ScientificContractRuntimeEnvironment
    maximum_model_only_revisions: Literal[6] = 6
    official_development_payload_count: Literal[0] = 0
    confirmation_identity_read_count: Literal[0] = 0
    confirmation_result_count: Literal[0] = 0
    created_at: datetime
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> ScientificContractRunIdentity:
        if self.identity_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"identity_hash"})
        ):
            raise ValueError("scientific Harness identity hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        plan_path: Path,
        plan: ScientificContractRecoveryPlan,
        erratum_path: Path,
        erratum: SentinelIdentifiabilityErratum,
        runner_sha256: str,
        runtime: ScientificContractRuntimeEnvironment,
        created_at: datetime,
    ) -> ScientificContractRunIdentity:
        """Freeze the complete pre-generation identity."""

        payload: dict[str, Any] = {
            "schema_version": "scientific-contract-harness-identity-v1",
            "plan_path": plan_path.as_posix(),
            "plan_hash": plan.plan_hash,
            "erratum_path": erratum_path.as_posix(),
            "erratum_hash": erratum.erratum_hash,
            "corrected_sentinel_registry_hash": (
                erratum.corrected_sentinel_registry_hash
            ),
            "runner_source_path": _RUNNER_SOURCE.as_posix(),
            "runner_sha256": runner_sha256,
            "packaged_runner_relative_path": (
                "runner/scientific_contract_harness_runner.py"
            ),
            "runtime": runtime.model_dump(mode="json"),
            "maximum_model_only_revisions": _MAX_REVISIONS,
            "official_development_payload_count": 0,
            "confirmation_identity_read_count": 0,
            "confirmation_result_count": 0,
            "created_at": (
                created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
        }
        payload["identity_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)


class ScientificContractRevision(StrictFrozenModel):
    """One exact provider source, review, Harness episode, and outcome."""

    revision_number: int = Field(ge=1, le=_MAX_TOTAL_REVISIONS)
    revision_id: str = Field(pattern=r"^scientific-contract-r[0-9]{2}$")
    stage: Literal[
        "scientific_contract_implementation", "scientific_contract_repair"
    ]
    ophis_response: ScientificContractSourceResponse | ScientificContractPatchResponse = (
        Field(discriminator="response_type")
    )
    model_interaction: AutonomousModelInteraction
    interaction_relative_path: str
    source_relative_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    static_review_relative_path: str
    static_review: ScientificContractStaticReview
    harness_spec_relative_path: str
    harness_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    episode_relative_path: str
    episode_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_relative_path: str | None = None
    observation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_codes: tuple[str, ...]
    # Task 267.2: "technical" means a schema/transport fault reached no scientific
    # verdict, so this revision does not consume the scientific budget.
    failure_kind: Literal["none", "technical", "scientific"] = "none"
    passed: bool
    source_derivation: ScientificContractSourceDerivation | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    exact_model_source_unmodified: bool = True
    official_development_result_count: Literal[0] = 0
    confirmation_read_count: Literal[0] = 0
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_revision(self) -> ScientificContractRevision:
        expected_id = f"scientific-contract-r{self.revision_number:02d}"
        if self.revision_id != expected_id:
            raise ValueError("scientific revision ID changed")
        expected_stage = (
            "scientific_contract_implementation"
            if self.revision_number == 1
            else "scientific_contract_repair"
        )
        if self.stage != expected_stage or self.model_interaction.stage != expected_stage:
            raise ValueError("scientific revision stage changed")
        # The interaction must belong to this revision. A bounded patch-addressing
        # re-ask appends a `.patch-retry-NN` suffix, which stays bound to the same
        # revision while keeping every attempt individually auditable.
        interaction_id = self.model_interaction.interaction_id
        if interaction_id != self.revision_id and not interaction_id.startswith(
            f"{self.revision_id}.patch-retry-"
        ):
            raise ValueError("scientific revision interaction changed")
        if self.model_interaction.parsed_payload != self.ophis_response.model_dump(
            mode="json"
        ):
            raise ValueError("scientific revision response differs from interaction")
        if isinstance(self.ophis_response, ScientificContractSourceResponse):
            if not self.exact_model_source_unmodified or self.source_derivation is not None:
                raise ValueError("complete-source revision has patch derivation metadata")
            if self.source_sha256 != _sha256_text(self.ophis_response.source_text):
                raise ValueError("scientific revision source differs from model bytes")
        else:
            derivation = self.source_derivation
            if self.exact_model_source_unmodified or derivation is None:
                raise ValueError("patch revision lacks source derivation metadata")
            if self.revision_number <= 1:
                raise ValueError("initial scientific revision cannot be a patch")
            if (
                derivation.parent_revision_id
                != f"scientific-contract-r{self.revision_number - 1:02d}"
                or
                self.ophis_response.parent_source_sha256
                != derivation.parent_source_sha256
                or canonical_model_hash(self.ophis_response.model_dump(mode="json"))
                != derivation.patch_payload_sha256
                or len(self.ophis_response.function_replacements)
                != derivation.replacement_count
                or self.source_sha256 != derivation.final_source_sha256
            ):
                raise ValueError("scientific patch derivation changed")
        if self.static_review.source_sha256 != self.source_sha256:
            raise ValueError("scientific revision review source mismatch")
        if (self.observation_relative_path is None) != (self.observation_hash is None):
            raise ValueError("scientific revision observation path/hash mismatch")
        if self.passed != (
            self.static_review.approved
            and self.observation_hash is not None
            and not self.failure_codes
        ):
            raise ValueError("scientific revision verdict contradicts evidence")
        # Task 267.2: the persisted classification must be recomputable from the
        # exact failure codes, so an audit can prove no scientific failure was
        # reclassified into the refunded technical bucket.
        if self.failure_kind != classify_revision_failure_kind(self.failure_codes):
            raise ValueError("scientific revision failure kind contradicts failure codes")
        if self.revision_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"revision_hash"})
        ):
            raise ValueError("scientific revision hash mismatch")
        return self


class ScientificContractFileArtifact(StrictFrozenModel):
    """One non-package artifact in the exact-file-set manifest."""

    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class ScientificContractHarnessPackage(StrictFrozenModel):
    """Complete Task 266.2 model-origin and synthetic-gate evidence package."""

    schema_version: Literal["scientific-contract-harness-package-v1"] = (
        "scientific-contract-harness-package-v1"
    )
    identity: ScientificContractRunIdentity
    revisions: tuple[ScientificContractRevision, ...] = Field(
        min_length=1,
        max_length=_MAX_TOTAL_REVISIONS,
    )
    selected_revision_id: str | None = None
    selected_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    synthetic_contract_gate_passed: bool
    task_266_3_authorized: bool
    generic_scientific_method_insertions: Literal[0] = 0
    generic_coefficient_insertions: Literal[0] = 0
    generic_equation_term_insertions: Literal[0] = 0
    model_only_repair_count: int = Field(ge=0, le=_MAX_TOTAL_REVISIONS - 1)
    scientific_revision_count: int = Field(default=0, ge=0, le=_MAX_SCIENTIFIC_REVISIONS)
    technical_revision_count: int = Field(default=0, ge=0, le=_MAX_TECHNICAL_REVISIONS)
    model_authored_patch_count: int = Field(
        default=0,
        ge=0,
        le=_MAX_TOTAL_REVISIONS - 1,
        exclude_if=lambda value: value == 0,
    )
    official_development_result_count: Literal[0] = 0
    official_development_artifact_read_count: Literal[0] = 0
    confirmation_identity_read_count: Literal[0] = 0
    confirmation_result_count: Literal[0] = 0
    system_generated_manuscript_count: Literal[0] = 0
    publication_ready: Literal[False] = False
    next_required_task: Literal["266.2", "266.3"]
    file_manifest: tuple[ScientificContractFileArtifact, ...]
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_package(self) -> ScientificContractHarnessPackage:
        numbers = tuple(item.revision_number for item in self.revisions)
        if numbers != tuple(range(1, len(numbers) + 1)):
            raise ValueError("scientific revisions are not contiguous")
        passed = tuple(item for item in self.revisions if item.passed)
        if len(passed) > 1 or (passed and passed[0] != self.revisions[-1]):
            raise ValueError("scientific Harness continued after a passing revision")
        gate_passed = bool(passed)
        if self.synthetic_contract_gate_passed != gate_passed:
            raise ValueError("scientific package gate contradicts revisions")
        if self.task_266_3_authorized != gate_passed:
            raise ValueError("Task 266.3 authorization is not fail-closed")
        expected_selected_id = passed[0].revision_id if passed else None
        expected_source = passed[0].source_sha256 if passed else None
        if (
            self.selected_revision_id != expected_selected_id
            or self.selected_source_sha256 != expected_source
        ):
            raise ValueError("scientific package selection changed")
        if self.model_only_repair_count != max(len(self.revisions) - 1, 0):
            raise ValueError("scientific package repair count changed")
        # Task 267.2: budget accounting must be recomputable from the revisions.
        expected_scientific = sum(
            item.failure_kind == "scientific" for item in self.revisions
        )
        expected_technical = sum(
            item.failure_kind == "technical" for item in self.revisions
        )
        if self.scientific_revision_count != expected_scientific:
            raise ValueError("scientific package scientific-revision count changed")
        if self.technical_revision_count != expected_technical:
            raise ValueError("scientific package technical-revision count changed")
        expected_patch_count = sum(
            isinstance(item.ophis_response, ScientificContractPatchResponse)
            for item in self.revisions
        )
        if self.model_authored_patch_count != expected_patch_count:
            raise ValueError("scientific package patch count changed")
        expected_next = "266.3" if gate_passed else "266.2"
        if self.next_required_task != expected_next:
            raise ValueError("scientific package next task changed")
        paths = [item.relative_path for item in self.file_manifest]
        if paths != sorted(set(paths)):
            raise ValueError("scientific package manifest paths are not unique and sorted")
        if self.package_hash != canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        ):
            raise ValueError("scientific Harness package hash mismatch")
        return self


HarnessExecution = Callable[..., ScientificContractHarnessObservation]


class _ScientificContractSandboxAdapter:
    """Execute one exact candidate against evaluator-owned synthetic fixtures."""

    adapter_id = "scientific.contract.synthetic.sandbox"
    adapter_version = "1"

    def __init__(
        self,
        *,
        candidate_path: Path,
        runner_path: Path,
        fixtures: Sequence[ScientificSentinelFixture],
        plan: ScientificContractRecoveryPlan,
        erratum: SentinelIdentifiabilityErratum,
        runtime: ScientificContractRuntimeEnvironment,
        static_review: ScientificContractStaticReview,
        timeout_seconds: int,
        executor: HarnessExecution,
    ) -> None:
        self.candidate_path = candidate_path
        self.runner_path = runner_path
        self.fixtures = tuple(fixtures)
        self.plan = plan
        self.erratum = erratum
        self.runtime = runtime
        self.static_review = static_review
        self.timeout_seconds = timeout_seconds
        self.executor = executor
        self.last_observation: ScientificContractHarnessObservation | None = None

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Run the exact bytes or return a fail-closed Harness failure."""

        source_sha256 = file_hash(self.candidate_path)
        expected = {
            "candidate_source_sha256": source_sha256,
            "plan_hash": self.plan.plan_hash,
            "erratum_hash": self.erratum.erratum_hash,
            "corrected_sentinel_registry_hash": (
                self.erratum.corrected_sentinel_registry_hash
            ),
            "official_development_payload_count": 0,
        }
        if any(request.task_input.get(key) != value for key, value in expected.items()):
            raise HarnessAdapterError(
                "Harness request does not bind the frozen scientific identity.",
                domain=FailureDomain.SECURITY,
                code="scientific_identity_mismatch",
                component_id=self.adapter_id,
                retryable=False,
                blocked=True,
            )
        if not self.static_review.approved:
            code = (
                self.static_review.findings[0].code
                if self.static_review.findings
                else "scientific_static_review_failed"
            )
            raise HarnessAdapterError(
                "Exact model source failed scientific-contract static review.",
                domain=FailureDomain.SECURITY,
                code=code,
                component_id=self.adapter_id,
                retryable=False,
                blocked=True,
            )
        started = datetime.now(timezone.utc)
        observation = self.executor(
            candidate_path=self.candidate_path,
            runner_path=self.runner_path,
            fixtures=self.fixtures,
            plan=self.plan,
            erratum=self.erratum,
            runtime=self.runtime,
            timeout_seconds=self.timeout_seconds,
        )
        self.last_observation = observation
        elapsed = max((datetime.now(timezone.utc) - started).total_seconds(), 0.0)
        if not observation.passed:
            raise HarnessAdapterError(
                "Exact model source failed one or more synthetic scientific-contract gates.",
                domain=FailureDomain.TOOL,
                code="scientific_contract_gate_failed",
                component_id=self.adapter_id,
                retryable=False,
                blocked=False,
            )
        artifact_id = f"artifact-{request.episode_id}-observation"
        return ModelInvocationResult(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            provider_ref="local.docker.offline",
            model_ref="model.generated.scientific.contract.source",
            capabilities=["sandboxed_code_execution", "structured_output"],
            attempts=1,
            structured_output={
                "candidate_source_sha256": source_sha256,
                "sentinel_count": observation.sentinel_count,
                "passed_sentinel_count": observation.passed_sentinel_count,
                "network_used": observation.network_used,
                "official_development_artifact_reads": (
                    observation.official_development_artifact_reads
                ),
                "confirmation_result_reads": observation.confirmation_result_reads,
                "status": "ok",
            },
            usage=ModelUsage(
                total_tokens=0,
                estimated_cost_usd=0.0,
                cost_known=True,
                wall_time_seconds=elapsed,
            ),
            uncertainty=0.0,
            steps=[
                AdapterStep(
                    step_id="scientific-contract-sandbox-1",
                    kind=TrajectoryKind.TOOL,
                    outcome=StepOutcome.SUCCEEDED,
                    summary=(
                        "Exact model-authored source passed six corrected fit/freeze/predict "
                        "sentinels and all null, leakage, shape, consistency, and resource gates."
                    ),
                    output_artifact_ids=[artifact_id],
                )
            ],
            tool_calls=[
                ToolCallRecord(
                    call_id="scientific-contract-tool-1",
                    tool_id="docker.scientific_contract.execute",
                    outcome=StepOutcome.SUCCEEDED,
                    arguments_hash=canonical_sha256(expected),
                    output_artifact_ids=[artifact_id],
                    summary="Execute exact model source with no official or confirmation mount.",
                )
            ],
            artifacts=[
                EpisodeArtifact(
                    artifact_id=artifact_id,
                    artifact_type="application.json",
                    sha256=observation.observation_hash,
                    media_type="application/json",
                )
            ],
        )


def review_scientific_contract_source(
    source_text: str,
) -> ScientificContractStaticReview:
    """Reject source that can target fixtures, escape isolation, or change interfaces."""

    findings: list[ScientificContractSecurityFinding] = []
    source_sha256 = _sha256_text(source_text)
    imported_roots: list[str] = []
    function_names: list[str] = []
    if len(source_text.encode("utf-8")) > _MAX_SOURCE_BYTES:
        findings.append(
            _finding(
                "source_size",
                f"source exceeds {_MAX_SOURCE_BYTES} bytes",
            )
        )
    if "```" in source_text:
        findings.append(_finding("markdown_fence", "source contains a Markdown fence"))
    normalized = source_text.casefold()
    for marker in sorted(_FORBIDDEN_SOURCE_MARKERS):
        if marker in normalized:
            findings.append(
                _finding(
                    "frozen_target_marker",
                    f"source embeds forbidden evaluator/benchmark marker {marker}",
                )
            )
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        message = exc.msg
        if _looks_like_collapsed_newlines(source_text):
            # Give the model an actionable diagnosis instead of "invalid syntax".
            message = (
                f"{exc.msg}; the source appears to have lost its newline escapes: "
                f"{len(source_text)} characters span only "
                f"{source_text.count(chr(10)) + 1} line(s). Emit each line break "
                "inside source_text as the two-character JSON escape backslash-n, "
                "not as a bare letter n."
            )
        findings.append(_finding("syntax_error", message, line=exc.lineno))
        return ScientificContractStaticReview.create(
            source_sha256=source_sha256,
            imported_roots=(),
            function_names=(),
            findings=findings,
        )
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        findings.append(_finding("ast_size", "source exceeds 20000 AST nodes"))
    top_functions = {
        item.name: item for item in tree.body if isinstance(item, ast.FunctionDef)
    }
    function_names.extend(top_functions)
    for name in ("fit_equations", "predict_derivative"):
        function = top_functions.get(name)
        if function is None:
            findings.append(_finding("missing_interface", f"source must define {name}"))
            continue
        if (
            len(function.args.args) != 1
            or function.args.posonlyargs
            or function.args.kwonlyargs
            or function.args.vararg is not None
            or function.args.kwarg is not None
            or function.decorator_list
        ):
            findings.append(
                _finding(
                    "invalid_interface",
                    f"{name} must accept exactly one undecorated positional payload",
                    line=function.lineno,
                )
            )
    predict = top_functions.get("predict_derivative")
    if predict is not None:
        predict_strings = {
            item.value.casefold()
            for item in ast.walk(predict)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        for marker in ("train_state", "train_derivative", "training_context_hash"):
            if marker in predict_strings:
                findings.append(
                    _finding(
                        "query_training_reuse",
                        f"predict_derivative references train-only field {marker}",
                        line=predict.lineno,
                    )
                )
        if any(
            isinstance(item, ast.Call)
            and _call_name(item.func).split(".")[-1] == "fit_equations"
            for item in ast.walk(predict)
        ):
            findings.append(
                _finding(
                    "fit_after_query",
                    "predict_derivative calls fit_equations",
                    line=predict.lineno,
                )
            )
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", maxsplit=1)[0]
                imported_roots.append(root)
                if root not in _ALLOWED_IMPORT_ROOTS:
                    findings.append(
                        _finding(
                            "import_not_allowlisted",
                            f"import root {root} is not allowlisted",
                            line=node.lineno,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", maxsplit=1)[0]
            imported_roots.append(root)
            if node.level or root not in _ALLOWED_IMPORT_ROOTS:
                findings.append(
                    _finding(
                        "import_not_allowlisted",
                        f"import root {root or '<relative>'} is not allowlisted",
                        line=node.lineno,
                    )
                )
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.ClassDef | ast.Lambda):
            findings.append(
                _finding(
                    "dynamic_structure",
                    f"{type(node).__name__} is forbidden",
                    line=getattr(node, "lineno", None),
                )
            )
        if isinstance(node, ast.While):
            findings.append(
                _finding(
                    "unbounded_loop",
                    "while loops are forbidden in bounded scientific candidates",
                    line=node.lineno,
                )
            )
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name.split(".")[-1] in _BLOCKED_CALLS:
                findings.append(
                    _finding(
                        "dynamic_execution",
                        f"call {name} is forbidden",
                        line=node.lineno,
                    )
                )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            findings.append(
                _finding(
                    "dunder_access",
                    f"dunder attribute {node.attr} is forbidden",
                    line=node.lineno,
                )
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            findings.append(
                _finding(
                    "dunder_access",
                    f"dunder name {node.id} is forbidden",
                    line=node.lineno,
                )
            )
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
            findings.append(
                _finding(
                    "module_mutation",
                    "attribute mutation is forbidden",
                    line=node.lineno,
                )
            )
    for statement in tree.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        if not isinstance(
            statement,
            ast.Import | ast.ImportFrom | ast.Assign | ast.AnnAssign | ast.FunctionDef,
        ):
            findings.append(
                _finding(
                    "top_level_effect",
                    f"top-level {type(statement).__name__} is forbidden",
                    line=getattr(statement, "lineno", None),
                )
            )
        if isinstance(statement, ast.Assign | ast.AnnAssign) and any(
            isinstance(item, ast.Call) for item in ast.walk(statement)
        ):
            findings.append(
                _finding(
                    "top_level_effect",
                    "top-level assignments cannot call functions",
                    line=statement.lineno,
                )
            )
    return ScientificContractStaticReview.create(
        source_sha256=source_sha256,
        imported_roots=imported_roots,
        function_names=function_names,
        findings=findings,
    )


def _parse_scientific_model_response(
    payload: object,
    *,
    allow_patch: bool,
) -> ScientificContractSourceResponse | ScientificContractPatchResponse:
    if not isinstance(payload, dict):
        raise ScientificContractHarnessError("scientific model response is not a mapping")
    response_type = payload.get("response_type")
    if response_type == "scientific_contract_source":
        return ScientificContractSourceResponse.model_validate(payload)
    if response_type == "scientific_contract_patch" and allow_patch:
        return ScientificContractPatchResponse.model_validate(payload)
    raise ScientificContractHarnessError(
        "scientific model response type is invalid for this revision"
    )


def _apply_model_authored_patch(
    parent_source: str,
    patch_response: ScientificContractPatchResponse,
) -> str:
    original_source = parent_source
    if patch_response.parent_source_sha256 != _sha256_text(original_source):
        raise ScientificContractHarnessError("scientific patch parent hash changed")

    spans = _top_level_function_spans(original_source)
    if not spans:
        raise ScientificContractPatchError(
            "the parent source defines no top-level function to replace; return a "
            "complete scientific_contract_source response instead.",
            failure_code="patch_parent_has_no_function",
        )

    for replacement in patch_response.function_replacements:
        if replacement.function_name not in spans:
            available = ", ".join(sorted(spans))
            raise ScientificContractPatchError(
                f"scientific patch targets unknown top-level function "
                f"'{replacement.function_name}'. The parent defines: {available}. "
                "Target one of those exact names.",
                failure_code="patch_unknown_function",
            )
        normalized = replacement.normalized_source_lines
        if not normalized:
            raise ScientificContractPatchError(
                f"the replacement for '{replacement.function_name}' contained no "
                "source lines after transport normalization.",
                failure_code="patch_replacement_empty",
            )
        first_line = normalized[0]
        if not first_line.lstrip().startswith(("def ", "async def ")):
            raise ScientificContractPatchError(
                f"the replacement for '{replacement.function_name}' must begin with "
                f"its own 'def' line, but began with '{first_line[:80]}'.",
                failure_code="patch_replacement_missing_def",
            )
        if first_line.startswith((" ", "\t")):
            raise ScientificContractPatchError(
                f"the replacement for '{replacement.function_name}' must be a "
                "top-level function, so its 'def' line cannot be indented.",
                failure_code="patch_replacement_indented_def",
            )

    # Apply bottom-up so line numbers of not-yet-applied spans stay valid.
    resolved = original_source
    ordered = sorted(
        patch_response.function_replacements,
        key=lambda item: spans[item.function_name][0],
        reverse=True,
    )
    for replacement in ordered:
        start_line, end_line = spans[replacement.function_name]
        lines = resolved.split("\n")
        resolved = "\n".join(
            [
                *lines[: start_line - 1],
                *replacement.normalized_source_lines,
                *lines[end_line:],
            ]
        )

    if resolved == original_source:
        raise ScientificContractPatchError(
            "scientific patch left source unchanged; every function replacement was "
            "byte-identical to the parent. Emit at least one real change.",
            failure_code="patch_left_source_unchanged",
        )
    encoded_size = len(resolved.encode("utf-8"))
    if not 200 <= encoded_size <= _MAX_SOURCE_BYTES:
        raise ScientificContractPatchError(
            f"scientific patched source is {encoded_size} bytes, outside the frozen "
            f"bounds of 200..{_MAX_SOURCE_BYTES}.",
            failure_code="patch_source_size_out_of_bounds",
        )
    return resolved


def build_scientific_contract_harness_package(
    plan_path: Path | str,
    erratum_path: Path | str,
    output_dir: Path | str,
    *,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 180,
    container_timeout_seconds: int = 480,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
    runtime_environment: ScientificContractRuntimeEnvironment | None = None,
    harness_executor: HarnessExecution | None = None,
) -> ScientificContractHarnessPackage:
    """Generate and repair exact source using synthetic evidence only."""

    output_root = Path(output_dir).resolve()
    package_path = output_root / _PACKAGE_NAME
    if package_path.is_file():
        return load_scientific_contract_harness_package(package_path)
    resolved_plan_path = Path(plan_path).resolve()
    resolved_erratum_path = Path(erratum_path).resolve()
    plan = load_scientific_contract_recovery_plan(resolved_plan_path)
    erratum = load_sentinel_identifiability_erratum(resolved_erratum_path)
    _validate_parent_boundary(plan, erratum, resolved_plan_path)
    fixtures = load_corrected_sentinel_fixtures(resolved_erratum_path)
    if not _RUNNER_SOURCE.is_file():
        raise ScientificContractHarnessError(
            f"scientific Harness runner is missing: {_RUNNER_SOURCE}"
        )
    runtime = runtime_environment or inspect_scientific_contract_runtime(_IMAGE)
    if (
        runtime.image_id != plan.baseline_probe.image_id
        or runtime.benchmark_revision != plan.baseline_probe.benchmark_revision
    ):
        raise ScientificContractHarnessError("scientific runtime differs from Task 266.1")
    now = clock or (lambda: datetime.now(timezone.utc))
    output_root.mkdir(parents=True, exist_ok=True)
    runner_path = output_root / "runner" / _RUNNER_SOURCE.name
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    source_runner_hash = file_hash(_RUNNER_SOURCE)
    if runner_path.is_file():
        if file_hash(runner_path) != source_runner_hash:
            raise ScientificContractHarnessError("packaged scientific runner changed")
    else:
        shutil.copyfile(_RUNNER_SOURCE, runner_path)
    identity_path = output_root / _IDENTITY_NAME
    if identity_path.is_file():
        identity = ScientificContractRunIdentity.model_validate_json(
            identity_path.read_text(encoding="utf-8")
        )
        _validate_resumed_identity(
            identity,
            plan=plan,
            erratum=erratum,
            runtime=runtime,
            runner_sha256=source_runner_hash,
        )
    else:
        identity = ScientificContractRunIdentity.create(
            plan_path=resolved_plan_path,
            plan=plan,
            erratum_path=resolved_erratum_path,
            erratum=erratum,
            runner_sha256=source_runner_hash,
            runtime=runtime,
            created_at=now(),
        )
        write_json_model(identity_path, identity)
    revisions: list[ScientificContractRevision] = []
    executor = harness_executor or execute_scientific_contract_container
    for revision_number in range(1, _MAX_TOTAL_REVISIONS + 1):
        # Task 267.2: stop on whichever bounded budget is exhausted first.  A
        # format-only fault refunds the scientific budget but still consumes the
        # technical budget, so a broken candidate cannot loop forever.
        if revisions:
            scientific_used = sum(
                item.failure_kind == "scientific" for item in revisions
            )
            technical_used = sum(item.failure_kind == "technical" for item in revisions)
            if scientific_used >= _MAX_SCIENTIFIC_REVISIONS:
                break
            if technical_used >= _MAX_TECHNICAL_REVISIONS:
                break
        revision_root = output_root / "revisions" / f"revision-{revision_number:02d}"
        revision_path = revision_root / "revision.json"
        if revision_path.is_file():
            revision = ScientificContractRevision.model_validate_json(
                revision_path.read_text(encoding="utf-8")
            )
            _validate_revision_files(output_root, revision)
            revisions.append(revision)
            if revision.passed:
                break
            continue
        revision_id = f"scientific-contract-r{revision_number:02d}"
        stage: Literal[
            "scientific_contract_implementation", "scientific_contract_repair"
        ] = (
            "scientific_contract_implementation"
            if revision_number == 1
            else "scientific_contract_repair"
        )
        # Task 267.2 follow-up: a patch that cannot be addressed uniquely is a
        # TECHNICAL fault, so re-ask the model with the exact addressing error
        # instead of ending the search. Live runs v10 and v12 both died here.
        patch_failure_feedback: str | None = None
        source_derivation: ScientificContractSourceDerivation | None = None
        source_text: str | None = None
        exact_model_source_unmodified = True
        completion_result = None
        interaction = None
        response = None
        for patch_attempt in range(1, _MAX_PATCH_ADDRESSING_ATTEMPTS + 1):
            messages = _generation_messages(
                plan=plan,
                erratum=erratum,
                fixtures=fixtures,
                runtime=runtime,
                previous_revision=revisions[-1] if revisions else None,
                output_root=output_root,
                patch_failure_feedback=patch_failure_feedback,
            )
            attempt_suffix = "" if patch_attempt == 1 else f".patch-retry-{patch_attempt:02d}"
            try:
                response_schema = (
                    _SOURCE_RESPONSE_SCHEMA
                    if revision_number == 1
                    else _REPAIR_RESPONSE_SCHEMA
                )
                completion_result, interaction = _call_and_record(
                    completion=completion,
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=provider_timeout_seconds,
                    max_tokens=12_000,
                    response_schema=response_schema,
                    response_schema_name=(
                        "scientific_contract_source"
                        if revision_number == 1
                        else "scientific_contract_repair"
                    ),
                    interaction_id=f"{revision_id}{attempt_suffix}",
                    stage=stage,
                    candidate_id="scientific-contract-candidate",
                    output_root=output_root,
                    now=now,
                )
                response = _parse_scientific_model_response(
                    completion_result.parsed_json,
                    allow_patch=revision_number > 1,
                )
            except (ValidationError, OSError, RuntimeError) as exc:
                raise ScientificContractHarnessError(
                    f"cannot obtain exact model source for {revision_id}: {exc}"
                ) from exc

            if isinstance(response, ScientificContractSourceResponse):
                source_text = response.source_text
                exact_model_source_unmodified = True
                break

            if not revisions:
                raise ScientificContractHarnessError(
                    "scientific patch has no previous revision"
                )
            parent_revision = revisions[-1]
            parent_source_path = _inside(
                output_root,
                parent_revision.source_relative_path,
            )
            parent_source = parent_source_path.read_bytes().decode("utf-8")
            try:
                source_text = _apply_model_authored_patch(parent_source, response)
            except ScientificContractPatchError as exc:
                patch_failure_feedback = str(exc)
                if patch_attempt == _MAX_PATCH_ADDRESSING_ATTEMPTS:
                    raise
                continue
            exact_model_source_unmodified = False
            break

        if source_text is None or interaction is None or response is None:
            raise ScientificContractHarnessError(
                f"scientific revision produced no source: {revision_id}"
            )
        if not isinstance(response, ScientificContractSourceResponse):
            parent_revision = revisions[-1]
            final_source_sha256 = _sha256_text(source_text)
            source_derivation = ScientificContractSourceDerivation.create(
                parent_revision_id=parent_revision.revision_id,
                parent_source_sha256=parent_revision.source_sha256,
                patch_response=response,
                final_source_sha256=final_source_sha256,
            )
            exact_model_source_unmodified = False
        revision_root.mkdir(parents=True, exist_ok=True)
        source_path = revision_root / "candidate.py"
        if source_path.is_file():
            if source_path.read_bytes().decode("utf-8") != source_text:
                raise ScientificContractHarnessError(
                    f"checkpoint source differs from model derivation: {revision_id}"
                )
        else:
            with source_path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(source_text)
        source_sha256 = file_hash(source_path)
        if source_sha256 != _sha256_text(source_text):
            raise ScientificContractHarnessError("persisted source encoding changed")
        static_review = review_scientific_contract_source(source_text)
        static_path = revision_root / "static-review.json"
        write_json_model(static_path, static_review)
        spec, episode, observation = _run_scientific_harness(
            run_id=f"task2662-{identity.identity_hash[:16]}",
            episode_id=f"task2662-{revision_id}",
            output_dir=revision_root / "harness",
            candidate_path=source_path,
            runner_path=runner_path,
            fixtures=fixtures,
            plan=plan,
            erratum=erratum,
            runtime=runtime,
            static_review=static_review,
            timeout_seconds=container_timeout_seconds,
            executor=executor,
            clock=now(),
        )
        observation_path: Path | None = None
        if observation is not None:
            observation_path = revision_root / "harness" / "observation.json"
            write_json_model(observation_path, observation)
        failures = _revision_failures(static_review, observation)
        revision_payload: dict[str, Any] = {
            "revision_number": revision_number,
            "revision_id": revision_id,
            "stage": stage,
            "ophis_response": response.model_dump(mode="json"),
            "model_interaction": interaction.model_dump(mode="json"),
            "interaction_relative_path": (
                Path("interactions") / f"{interaction.interaction_id}.json"
            ).as_posix(),
            "source_relative_path": source_path.relative_to(output_root).as_posix(),
            "source_sha256": source_sha256,
            "static_review_relative_path": static_path.relative_to(output_root).as_posix(),
            "static_review": static_review.model_dump(mode="json"),
            "harness_spec_relative_path": (
                revision_root / "harness" / "harness-spec.json"
            ).relative_to(output_root).as_posix(),
            "harness_spec_hash": spec.spec_hash,
            "episode_relative_path": (
                revision_root / "harness" / "episode.json"
            ).relative_to(output_root).as_posix(),
            "episode_hash": episode.episode_hash,
            "observation_relative_path": (
                observation_path.relative_to(output_root).as_posix()
                if observation_path is not None
                else None
            ),
            "observation_hash": (
                observation.observation_hash if observation is not None else None
            ),
            "failure_codes": failures,
            "failure_kind": classify_revision_failure_kind(failures),
            "passed": bool(static_review.approved and observation and observation.passed),
            "exact_model_source_unmodified": exact_model_source_unmodified,
            "official_development_result_count": 0,
            "confirmation_read_count": 0,
        }
        if source_derivation is not None:
            revision_payload["source_derivation"] = source_derivation.model_dump(
                mode="json"
            )
        revision_payload["revision_hash"] = canonical_model_hash(revision_payload)
        revision = ScientificContractRevision.model_validate(revision_payload)
        write_json_model(revision_path, revision)
        revisions.append(revision)
        if revision.passed:
            break
    if not revisions:
        raise ScientificContractHarnessError("scientific Harness produced no revision")
    passed = revisions[-1].passed
    report_path = output_root / _MARKDOWN_NAME
    report_path.write_text(
        _render_markdown(identity, revisions, passed),
        encoding="utf-8",
    )
    manifest = _build_file_manifest(output_root)
    selected = revisions[-1] if passed else None
    package_payload: dict[str, Any] = {
        "schema_version": "scientific-contract-harness-package-v1",
        "identity": identity.model_dump(mode="json"),
        "revisions": [item.model_dump(mode="json") for item in revisions],
        "selected_revision_id": selected.revision_id if selected else None,
        "selected_source_sha256": selected.source_sha256 if selected else None,
        "synthetic_contract_gate_passed": passed,
        "task_266_3_authorized": passed,
        "generic_scientific_method_insertions": 0,
        "generic_coefficient_insertions": 0,
        "generic_equation_term_insertions": 0,
        "model_only_repair_count": max(len(revisions) - 1, 0),
        "scientific_revision_count": sum(
            item.failure_kind == "scientific" for item in revisions
        ),
        "technical_revision_count": sum(
            item.failure_kind == "technical" for item in revisions
        ),
        "official_development_result_count": 0,
        "official_development_artifact_read_count": 0,
        "confirmation_identity_read_count": 0,
        "confirmation_result_count": 0,
        "system_generated_manuscript_count": 0,
        "publication_ready": False,
        "next_required_task": "266.3" if passed else "266.2",
        "file_manifest": [item.model_dump(mode="json") for item in manifest],
        "output_path": package_path.as_posix(),
    }
    patch_count = sum(
        isinstance(item.ophis_response, ScientificContractPatchResponse)
        for item in revisions
    )
    if patch_count:
        package_payload["model_authored_patch_count"] = patch_count
    package_payload["package_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in package_payload.items()
            if key not in {"package_hash", "output_path"}
        }
    )
    package = ScientificContractHarnessPackage.model_validate(package_payload)
    write_json_model(package_path, package)
    return load_scientific_contract_harness_package(package_path)


def load_scientific_contract_harness_package(
    path: Path | str,
) -> ScientificContractHarnessPackage:
    """Strictly reload parents, exact files, nested hashes, and authorization."""

    package_path = Path(path).resolve()
    try:
        package = ScientificContractHarnessPackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ScientificContractHarnessError(
            f"cannot load scientific Harness package: {exc}"
        ) from exc
    if Path(package.output_path).resolve() != package_path:
        raise ScientificContractHarnessError("scientific package output path changed")
    root = package_path.parent
    plan = load_scientific_contract_recovery_plan(package.identity.plan_path)
    erratum = load_sentinel_identifiability_erratum(package.identity.erratum_path)
    _validate_parent_boundary(plan, erratum, Path(package.identity.plan_path).resolve())
    if (
        package.identity.plan_hash != plan.plan_hash
        or package.identity.erratum_hash != erratum.erratum_hash
        or package.identity.corrected_sentinel_registry_hash
        != erratum.corrected_sentinel_registry_hash
    ):
        raise ScientificContractHarnessError("scientific package parent identity changed")
    expected_files = {_PACKAGE_NAME}
    for artifact in package.file_manifest:
        artifact_path = _inside(root, artifact.relative_path)
        if (
            not artifact_path.is_file()
            or file_hash(artifact_path) != artifact.sha256
            or artifact_path.stat().st_size != artifact.size_bytes
        ):
            raise ScientificContractHarnessError(
                f"scientific package artifact changed: {artifact.relative_path}"
            )
        expected_files.add(artifact.relative_path)
    actual_files = {
        item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()
    }
    if actual_files != expected_files:
        raise ScientificContractHarnessError(
            "scientific package file set changed: "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    runner_path = _inside(root, package.identity.packaged_runner_relative_path)
    if file_hash(runner_path) != package.identity.runner_sha256:
        raise ScientificContractHarnessError("packaged scientific runner changed")
    for revision in package.revisions:
        _validate_revision_files(root, revision)
    expected_markdown = _render_markdown(
        package.identity,
        package.revisions,
        package.synthetic_contract_gate_passed,
    )
    if (root / _MARKDOWN_NAME).read_text(encoding="utf-8") != expected_markdown:
        raise ScientificContractHarnessError("scientific Harness Markdown changed")
    return package


def inspect_scientific_contract_runtime(
    image: str = _IMAGE,
) -> ScientificContractRuntimeEnvironment:
    """Inspect and bind the exact local offline image without running candidates."""

    if image != _IMAGE:
        raise ScientificContractHarnessError("scientific Harness image changed")
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        records = json.loads(completed.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Docker image inspection returned an invalid record set")
        image_record = records[0]
        image_id = str(image_record["Id"])
        labels = image_record.get("Config", {}).get("Labels", {}) or {}
        revision = str(labels.get("org.opencontainers.image.revision", ""))
    except (
        FileNotFoundError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        raise ScientificContractHarnessError(
            f"cannot inspect scientific Harness runtime: {exc}"
        ) from exc
    if revision != _BENCHMARK_REVISION:
        raise ScientificContractHarnessError("scientific Harness image revision changed")
    return ScientificContractRuntimeEnvironment.create(image_id=image_id)


def execute_scientific_contract_container(
    *,
    candidate_path: Path,
    runner_path: Path,
    fixtures: Sequence[ScientificSentinelFixture],
    plan: ScientificContractRecoveryPlan,
    erratum: SentinelIdentifiabilityErratum,
    runtime: ScientificContractRuntimeEnvironment,
    timeout_seconds: int,
) -> ScientificContractHarnessObservation:
    """Run the evaluator with only runner/source mounts and fixture JSON on stdin."""

    if file_hash(runner_path) != file_hash(_RUNNER_SOURCE):
        raise ScientificContractHarnessError("container runner differs from reviewed source")
    payload = {
        "schema_version": "scientific-contract-harness-input-v1",
        "expected_runner_sha256": file_hash(runner_path),
        "candidate_source_sha256": file_hash(candidate_path),
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "fixtures": [item.model_dump(mode="json") for item in fixtures],
    }
    command = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "2",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "OMP_NUM_THREADS=2",
        "--env",
        "OPENBLAS_NUM_THREADS=2",
        "--mount",
        _bind_mount(runner_path, "/harness/scientific_contract_harness_runner.py"),
        "--mount",
        _bind_mount(candidate_path, "/candidate/candidate.py"),
        "--entrypoint",
        "python",
        runtime.image,
        "/harness/scientific_contract_harness_runner.py",
        "--candidate",
        "/candidate/candidate.py",
    ]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, allow_nan=False, sort_keys=True),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ScientificContractHarnessError(
            f"cannot execute scientific Harness container: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-4_000:]
        raise ScientificContractHarnessError(
            f"scientific Harness container failed ({completed.returncode}): {detail}"
        )
    if completed.stderr:
        raise ScientificContractHarnessError("scientific Harness container wrote stderr")
    try:
        observation = ScientificContractHarnessObservation.model_validate_json(
            completed.stdout
        )
    except ValidationError as exc:
        raise ScientificContractHarnessError(
            f"scientific Harness observation is invalid: {exc}"
        ) from exc
    expected = {
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "candidate_source_sha256": file_hash(candidate_path),
        "runner_sha256": file_hash(runner_path),
    }
    if any(getattr(observation, key) != value for key, value in expected.items()):
        raise ScientificContractHarnessError("scientific observation identity changed")
    return observation


def _run_scientific_harness(
    *,
    run_id: str,
    episode_id: str,
    output_dir: Path,
    candidate_path: Path,
    runner_path: Path,
    fixtures: Sequence[ScientificSentinelFixture],
    plan: ScientificContractRecoveryPlan,
    erratum: SentinelIdentifiabilityErratum,
    runtime: ScientificContractRuntimeEnvironment,
    static_review: ScientificContractStaticReview,
    timeout_seconds: int,
    executor: HarnessExecution,
    clock: datetime,
) -> tuple[
    HarnessSpec,
    EpisodePackage,
    ScientificContractHarnessObservation | None,
]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_sha256 = file_hash(candidate_path)
    spec = _build_harness_spec(source_sha256=source_sha256, timeout_seconds=timeout_seconds)
    adapter = _ScientificContractSandboxAdapter(
        candidate_path=candidate_path,
        runner_path=runner_path,
        fixtures=fixtures,
        plan=plan,
        erratum=erratum,
        runtime=runtime,
        static_review=static_review,
        timeout_seconds=timeout_seconds,
        executor=executor,
    )
    journal = EventJournal.create(output_dir / "journal", run_id=run_id, created_at=clock)
    runner = HarnessRunner(
        spec=spec,
        journal=journal,
        model_adapter=adapter,
        graders={
            "grader.scientific.source": ExactFieldGrader(
                grader_id="grader.scientific.source",
                grader_version="1",
                field_name="candidate_source_sha256",
                expected_value=source_sha256,
            ),
            "grader.scientific.sentinels": ExactFieldGrader(
                grader_id="grader.scientific.sentinels",
                grader_version="1",
                field_name="passed_sentinel_count",
                expected_value=6,
            ),
            "grader.scientific.status": ExactFieldGrader(
                grader_id="grader.scientific.status",
                grader_version="1",
                field_name="status",
                expected_value="ok",
            ),
            "grader.scientific.network": ExactFieldGrader(
                grader_id="grader.scientific.network",
                grader_version="1",
                field_name="network_used",
                expected_value=False,
            ),
            "grader.scientific.official": ExactFieldGrader(
                grader_id="grader.scientific.official",
                grader_version="1",
                field_name="official_development_artifact_reads",
                expected_value=0,
            ),
            "grader.scientific.confirmation": ExactFieldGrader(
                grader_id="grader.scientific.confirmation",
                grader_version="1",
                field_name="confirmation_result_reads",
                expected_value=0,
            ),
        },
        clock=lambda: clock,
    )
    episode = runner.run(
        HarnessRunRequest(
            run_id=run_id,
            episode_id=episode_id,
            task_input={
                "candidate_source_sha256": source_sha256,
                "plan_hash": plan.plan_hash,
                "erratum_hash": erratum.erratum_hash,
                "corrected_sentinel_registry_hash": (
                    erratum.corrected_sentinel_registry_hash
                ),
                "official_development_payload_count": 0,
            },
            context_artifact_ids=[],
            available_tool_ids=["docker.scientific_contract.execute"],
        )
    )
    write_json_model(output_dir / "harness-spec.json", spec)
    write_json_model(output_dir / "episode.json", episode)
    return spec, episode, adapter.last_observation


def _build_harness_spec(*, source_sha256: str, timeout_seconds: int) -> HarnessSpec:
    output_contract = StructuredOutputContract(
        fields=[
            StructuredField(
                name="candidate_source_sha256",
                value_type=JsonFieldType.STRING,
                enum_values=[source_sha256],
            ),
            StructuredField(name="sentinel_count", value_type=JsonFieldType.INTEGER),
            StructuredField(
                name="passed_sentinel_count",
                value_type=JsonFieldType.INTEGER,
                enum_values=[6],
            ),
            StructuredField(
                name="network_used",
                value_type=JsonFieldType.BOOLEAN,
                enum_values=[False],
            ),
            StructuredField(
                name="official_development_artifact_reads",
                value_type=JsonFieldType.INTEGER,
                enum_values=[0],
            ),
            StructuredField(
                name="confirmation_result_reads",
                value_type=JsonFieldType.INTEGER,
                enum_values=[0],
            ),
            StructuredField(
                name="status",
                value_type=JsonFieldType.STRING,
                enum_values=["ok"],
            ),
        ]
    )
    grader_ids = [
        "grader.scientific.source",
        "grader.scientific.sentinels",
        "grader.scientific.status",
        "grader.scientific.network",
        "grader.scientific.official",
        "grader.scientific.confirmation",
    ]
    return HarnessSpec.create(
        spec_id=f"scientific-contract-{source_sha256[:16]}",
        version="1",
        task_contract=TaskContract(
            policy_id="task.scientific_contract.synthetic",
            version="1",
            task_id="scientific_contract_synthetic",
            instructions=(
                "Run exact model-authored fit/freeze/predict source against six corrected "
                "known-law synthetic sentinels without official or confirmation artifacts."
            ),
            output_contract=output_contract,
            success_criteria=[
                "All six corrected ODE/PDE sentinels pass exact term and coefficient recovery.",
                "Frozen equations and candidate predictions agree within 1e-9.",
                "Null, shuffled-target, alternate-training, shape, and fit-once/query-many gates pass.",
                "No network, official development, confirmation, or unrestricted execution occurs.",
            ],
            forbidden_actions=[
                "Do not access official development or confirmation artifacts.",
                "Do not fit after a query or reuse query/validation/test state.",
                "Do not alter model-authored source after review.",
                "Do not treat synthetic success as publication evidence.",
            ],
            stop_conditions=[
                "Stop after one bounded container.",
                "Block before execution when exact source fails static review.",
            ],
            required_permission_ids=["code.execute.sandbox"],
            required_tool_ids=["docker.scientific_contract.execute"],
        ),
        context_policy=ContextPolicy(
            policy_id="context.scientific_contract.synthetic",
            version="1",
            allowed_source_ids=["task2661.corrected.synthetic.sentinels"],
            max_context_tokens=0,
            max_context_bytes=25_000_000,
            compression_allowed=False,
            reset_between_trials=True,
            contamination_domains=[
                "mdbench.development.values",
                "mdbench.confirmation",
            ],
        ),
        model_policy=ModelPolicy(
            policy_id="model.scientific_contract.synthetic",
            version="1",
            adapter_id=_ScientificContractSandboxAdapter.adapter_id,
            model_ref="model.generated.scientific.contract.source",
            required_capabilities=["sandboxed_code_execution", "structured_output"],
            max_attempts=1,
            max_output_tokens=128,
            temperature=0.0,
            structured_output_required=True,
            deliberation="disabled",
        ),
        tool_policy=ToolPolicy(
            policy_id="tools.scientific_contract.synthetic",
            version="1",
            tools=[
                ToolDefinition(
                    tool_id="docker.scientific_contract.execute",
                    version="1",
                    input_schema={"type": "object", "additionalProperties": False},
                    side_effect_level=SideEffectLevel.LOCAL_REVERSIBLE,
                    required_permission_id="code.execute.sandbox",
                    requires_sandbox=True,
                    allowed_network_domains=[],
                )
            ],
            default_deny=True,
            sandbox_required=True,
            network_default_deny=True,
            max_tool_calls=1,
        ),
        memory_policy=MemoryPolicy(
            policy_id="memory.scientific_contract.synthetic",
            version="1",
            vault_read=False,
            vault_write=False,
            allowed_vault_prefixes=[],
            short_term_state=True,
            run_cache=False,
            long_term_experience_write=False,
        ),
        state_policy=StatePolicy(
            policy_id="state.scientific_contract.synthetic",
            version="1",
            append_only_events=True,
            checkpoint_every_events=1,
            resume_allowed=False,
            max_mutable_state_bytes=30_000_000,
            terminal_is_immutable=True,
        ),
        permission_policy=PermissionPolicy(
            policy_id="permissions.scientific_contract.synthetic",
            version="1",
            granted_permission_ids=["code.execute.sandbox"],
            approval_required_permission_ids=[],
            forbidden_permission_ids=[
                "code.execute.unrestricted",
                "network.access",
                "secret.read",
                "official.development.read",
                "confirmation.read",
            ],
            deny_unknown=True,
            permission_expansion_allowed=False,
        ),
        verification_policy=VerificationPolicy(
            policy_id="verification.scientific_contract.synthetic",
            version="1",
            required_grader_ids=grader_ids,
            require_output_artifact_hashes=True,
            fail_closed_on_grader_error=True,
            require_journal_seal=True,
        ),
        observability_policy=ObservabilityPolicy(
            policy_id="observability.scientific_contract.synthetic",
            version="1",
            record_events=True,
            record_full_trajectory=True,
            record_costs=True,
            record_failures=True,
            record_interventions=True,
            store_raw_model_text=False,
            local_only=True,
            max_step_summary_chars=512,
        ),
        failure_attribution_policy=FailureAttributionPolicy(
            policy_id="failure.scientific_contract.synthetic",
            version="1",
        ),
        cost_policy=CostPolicy(
            policy_id="cost.scientific_contract.synthetic",
            version="1",
            max_total_tokens=128,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=float(timeout_seconds),
            max_tool_calls=1,
            require_known_cost=True,
        ),
        entropy_intervention_policy=EntropyInterventionPolicy(
            policy_id="entropy.scientific_contract.synthetic",
            version="1",
            max_uncertainty=0.0,
            stop_when_uncertainty_exceeded=True,
            max_retries=0,
            max_human_interventions=0,
            allowed_interventions=[],
        ),
        evaluation_policy=EvaluationPolicy(
            policy_id="evaluation.scientific_contract.synthetic",
            version="1",
            trial_count=1,
            graders=[
                GraderSpec(
                    grader_id=grader_id,
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                )
                for grader_id in grader_ids
            ],
            require_environment_outcome=True,
            require_all_graders=True,
            promotion_threshold=1.0,
        ),
        change_prediction=(
            "Model-originated source will learn concrete physical-unit laws once from training "
            "context and reuse only the frozen artifact for multiple unseen queries."
        ),
        evaluation_scope=(
            "Corrected synthetic known-law admission only; no official score, significance, "
            "novelty, competition superiority, manuscript, or publication claim."
        ),
    )


def build_scientific_interface_contract() -> dict[str, Any]:
    """Return the prompt-visible scientific interface contract.

    Exposed separately from message assembly so a parity test can assert that
    every advertised equation key set matches the runner whitelist exactly.
    """

    return _scientific_interface_contract()


def _scientific_interface_contract() -> dict[str, Any]:
    interface: dict[str, Any] = {
        "required_functions": ["fit_equations(payload)", "predict_derivative(payload)"],
        "source_transport_contract": {
            "entire_response_is_one_json_object": True,
            "response_first_character": "{",
            "response_last_character": "}",
            # Runs v10 and v11 both failed because the model emitted a bare letter
            # `n` where an escaped newline belonged, collapsing the whole program
            # onto one line. Explicit instruction did not fix it, so source now
            # arrives as an array of lines and no newline escape is ever written.
            "source_field_name": "source_lines",
            "source_lines_contract": (
                "Emit source as a JSON array of strings named source_lines, with "
                "exactly one array element per physical line of Python. Do NOT emit "
                "a single source_text string and do NOT write newline escapes "
                "anywhere. The orchestrator joins your array elements with newlines "
                "to reconstruct the file byte-for-byte."
            ),
            "source_lines_example": [
                "import numpy as np",
                "",
                "",
                "def fit_equations(payload):",
                "    train_state = payload['train_state']",
                "    return {}",
            ],
            "source_lines_rules": {
                "one_element_per_line": True,
                "no_trailing_newline_inside_an_element": True,
                "preserve_leading_indentation_spaces_in_each_element": True,
                "empty_string_element_means_a_blank_line": True,
            },
            "regenerate_whole_object_never_continue_a_prior_fragment": True,
            "preferred_source_character_count_maximum": _PREFERRED_SOURCE_CHARACTERS,
            "hard_source_byte_count_maximum": _MAX_SOURCE_BYTES,
            "hard_each_ophis_narrative_character_count_maximum": (
                _MAX_OPHIS_CHARACTERS
            ),
            "repair_modes": {
                "required": (
                    "scientific_contract_patch with parent_source_sha256 and 1..8 "
                    "function_replacements, each naming a top-level function and "
                    "supplying its complete replacement as new_source_lines"
                ),
                "why_function_addressing": (
                    "A top-level function name is unique, so the orchestrator can "
                    "locate it exactly. Do not send text anchors."
                ),
                "whole_source_rewrite": (
                    "to rewrite everything, return a complete "
                    "scientific_contract_source response with source_lines instead "
                    "of a patch"
                ),
                "function_replacement_requirements": [
                    "function_name must be an existing top-level function",
                    "new_source_lines[0] must be that function's own unindented "
                    "'def' line",
                    "new_source_lines carries the COMPLETE function, one element "
                    "per physical line, with no newline escapes",
                    "at most one replacement per function name",
                ],
                "patch_content_origin": "every replacement line is model-authored",
                "orchestrator_role": (
                    "hash verification and deterministic whole-function substitution only"
                ),
            },
        },
        "static_source_contract": {
            "allowed_import_roots": sorted(_ALLOWED_IMPORT_ROOTS),
            "required_top_level_functions": [
                "fit_equations(payload)",
                "predict_derivative(payload)",
            ],
            "top_level_allowed": [
                "imports",
                "literal constant assignments without calls",
                "ordinary function definitions",
            ],
            "forbidden_constructs": [
                "classes",
                "async or await",
                "lambdas",
                "while loops",
                "attribute writes",
                "dunder access",
                "top-level calls or other effects",
                "file, network, subprocess, reflection, or dynamic execution",
                "stdout or stderr writes",
                "cross-call mutable state",
            ],
        },
        "json_transport": {
            "tensor_exact_fields": ["shape", "values"],
            "tensor_decode_semantics": (
                "np.asarray(tensor['values'], dtype=float).reshape(tuple(tensor['shape']))"
            ),
            "tensor_encode_semantics": (
                "{'shape': list(array.shape), 'values': array.reshape(-1).tolist()}"
            ),
            "tensor_bound_fields": [
                "fit.train_state",
                "fit.train_derivative",
                "predict.state",
                "predict_response.derivative_prediction",
            ],
            "spatial_coordinates_type": (
                "mapping from present axis names x/y/z to finite numeric lists"
            ),
            "train_times_type": "finite numeric list",
            "axis_layout": {
                "ode": ["time", "field"],
                "pde": ["zero_to_three_spatial_axes_in_x_y_z_order", "time", "field"],
                "time_axis_index": -2,
                "field_axis_index": -1,
                "spatial_axis_indices_start_at": 0,
                "train_state_and_train_derivative_have_identical_shape": True,
            },
            "query_state_already_has_penultimate_time_axis": True,
            "candidate_must_not_add_a_time_axis": True,
        },
        "fit_request_fields": [
            "schema_version",
            "fit_id",
            "candidate_source_sha256",
            "sentinel_id",
            "data_type",
            "field_names",
            "spatial_coordinates",
            "train_times",
            "train_state",
            "train_derivative",
            "training_context_hash",
        ],
        "fit_response_exact_fields": [
            "equations",
            "equation_coordinate_system",
            "field_scaling",
            "diagnostics",
        ],
        "fit_response_rules": {
            "additional_fields_allowed": False,
            "equation_coordinate_system_exact_value": "physical-unscaled-v1",
            "candidate_returns_private_artifact": False,
            "orchestrator_freezes_standard_artifact_from_exact_fit_response": True,
        },
        "equation": {
            "container": "list with exactly one equation per field_names item, in order",
            "equation_exact_fields": list(_EQUATION_EXACT_FIELDS),
            "equation_term_exact_fields": list(_EQUATION_TERM_EXACT_FIELDS),
            "equation_factor_exact_fields": list(_EQUATION_FACTOR_EXACT_FIELDS),
            "additional_fields_allowed": False,
            "count_fields_are_forbidden": (
                "Do not emit any count field. The evaluator rejects every key outside the "
                "exact field lists above, including term_count and factor_count."
            ),
            "target": "uN_t",
            "intercept": "finite numeric",
            "terms": (
                "list of 1..64 term mappings; represent a constant only with intercept; "
                "no two terms may repeat an identical factor support"
            ),
            "term": {
                "coefficient": "finite numeric",
                "factors": "list of 1..6 factor mappings",
            },
            "factor": {
                "field": "uN",
                "derivative_axes": (
                    "JSON list[str]; [] for an undifferentiated field; each item "
                    "must be a present x/y/z axis; repeat an item for a higher "
                    "derivative, for example ['x', 'x']"
                ),
                "power": "integer 1..6",
            },
            "minimal_valid_example": {
                "target": "u0_t",
                "intercept": 0.0,
                "terms": [
                    {
                        "coefficient": -0.1,
                        "factors": [
                            {"field": "u0", "derivative_axes": ["x"], "power": 1}
                        ],
                    }
                ],
            },
        },
        "field_scaling": {
            "container": (
                "list with exactly one mapping per field_names item, in field_names order"
            ),
            "exact_fields": [
                "field",
                "state_offset",
                "state_scale",
                "derivative_offset",
                "derivative_scale",
            ],
            "physical_equations_required": True,
        },
        "fit_diagnostics_exact_fields": [
            "solver_id",
            "design_feature_count",
            "warnings",
        ],
        "fit_diagnostics_types": {
            "solver_id": "non-empty string up to 128 characters",
            "design_feature_count": "positive integer",
            "warnings": "list of at most 32 strings",
        },
        "predict_request_exact_fields": [
            "schema_version",
            "query_id",
            "artifact",
            "time",
            "spatial_coordinates",
            "state",
            "expected_derivative_present",
        ],
        "predict_request_rules": {
            "state_time_slices": 1,
            "contains_target_or_train_arrays": False,
            "expected_derivative_present_exact_value": False,
        },
        "frozen_artifact_exact_fields_visible_to_predict": [
            "schema_version",
            "fit_id",
            "candidate_source_sha256",
            "training_context_hash",
            "data_type",
            "field_names",
            "equations",
            "equation_coordinate_system",
            "field_scaling",
            "diagnostics",
            "fit_call_count",
            "fit_completed_before_query",
            "free_symbol_count",
            "artifact_hash",
        ],
        "frozen_artifact_rules": {
            "schema_version_exact_value": "frozen-equation-artifact-v1",
            "contains_candidate_private_state": False,
            "prediction_must_evaluate_standard_equations": True,
        },
        "predict_response_exact_fields": [
            "schema_version",
            "query_id",
            "artifact_hash",
            "derivative_prediction",
            "fit_calls_during_prediction",
            "artifact_mutation_count",
            "equation_evaluator_id",
        ],
        "predict_response_rules": {
            "additional_fields_allowed": False,
            "schema_version_exact_value": "scientific-predict-response-v1",
            "query_id_must_copy_request": True,
            "artifact_hash_must_copy_artifact": True,
            "fit_calls_during_prediction_exact_value": 0,
            "artifact_mutation_count_exact_value": 0,
            "equation_evaluator_id_exact_value": "trusted-equation-evaluator-v1",
        },
        "periodic_grid": "spatial coordinate arrays include a duplicated endpoint",
        # Fairness disclosure. The trusted evaluator re-derives every spatial
        # derivative itself when it scores your equations, using the operator named
        # here. Live run v15 showed why this must be stated: candidates fit
        # coefficients with finite differences, then the evaluator re-scored the
        # same equations with a spectral operator, producing training NMSE around
        # 15..34 on all five PDE sentinels even though each candidate's own fit was
        # internally consistent. Withholding the scoring operator made the gate
        # unpassable for reasons that had nothing to do with scientific quality.
        "evaluator_spatial_derivative_operator": {
            "method": "spectral_fft_on_the_periodic_axis",
            "detail": (
                "For each derivative_axes entry the evaluator drops the duplicated "
                "endpoint, applies a real FFT along that axis, multiplies by "
                "(1j*k)**1 per requested order using k = 2*pi*fftfreq(n, period/n), "
                "inverts, and re-appends the endpoint. Repeated axis entries are "
                "applied one order at a time."
            ),
            "implication": (
                "Fit your coefficients against THIS operator, not against a finite "
                "difference stencil, or your equation will be scored with a "
                "different derivative than the one you fitted."
            ),
            "axis_requirements": "uniform spacing and at least five samples per axis",
        },
        "state_layout": (
            "zero to three spatial axes in x/y/z order, then time, then field"
        ),
        "trusted_evaluator_id": "trusted-equation-evaluator-v1",
    }
    return interface


def _generation_messages(
    *,
    plan: ScientificContractRecoveryPlan,
    erratum: SentinelIdentifiabilityErratum,
    fixtures: Sequence[ScientificSentinelFixture],
    runtime: ScientificContractRuntimeEnvironment,
    previous_revision: ScientificContractRevision | None,
    output_root: Path,
    patch_failure_feedback: str | None = None,
) -> list[dict[str, str]]:
    interface = _scientific_interface_contract()
    frozen_gates = plan.contract_gate.model_dump(mode="json")
    capability_metadata = [
        {
            "data_type": item.data_type,
            "spatial_dimensions": item.spatial_dimensions,
            "field_count": len(item.field_names),
            "train_shape": list(item.train_state.shape),
            "query_shape": list(item.queries[0].state.shape),
        }
        for item in fixtures
    ]
    source_evidence = [
        {
            "title": item.title,
            "url": item.final_url,
            "supports_claim": item.supports_claim,
            "content_sha256": item.content_sha256,
        }
        for item in plan.sources
        if item.kind in {"paper", "implementation"}
    ]
    system_message = {
        "role": "system",
        "content": (
            "You are the autonomous scientist and sole author of the candidate scientific "
            "method. Your entire response must be exactly one JSON object: start with '{', "
            "end with '}', and never emit raw Python, a fragment, a continuation, Markdown, "
            "or surrounding prose. On the initial turn, encode exact standalone Python as "
            "the JSON array source_lines, with exactly one array element per physical line "
            "of Python and no newline escapes anywhere. Regenerate the whole JSON object on "
            "every attempt. Keep the joined source compact, preferably at most "
            f"{_PREFERRED_SOURCE_CHARACTERS} characters. "
            "On repair turns, return only a scientific_contract_patch object with the exact "
            "parent hash and 1..8 function_replacements. Each names ONE existing top-level "
            "function and supplies that function's COMPLETE replacement as new_source_lines, "
            "one array element per physical line, starting with its own unindented 'def' "
            "line. Never send text anchors or line numbers as edit targets. The orchestrator "
            "substitutes whole functions by name and will never author a repair. If a whole "
            "rewrite is necessary, return a complete scientific_contract_source response "
            "instead. "
            "Use Observation→Problem→Hypothesis→Intervention→expected effect explicitly, then "
            "implement your own general train-dependent equation-discovery method. The "
            "orchestrator will either persist your joined source_lines byte-for-byte or "
            "substitute your named functions verbatim. Do not "
            "target fixture IDs, embed coefficients/equations, inspect files/processes/call "
            "stacks, use network/subprocess/dynamic execution, print, or store state between "
            "calls. Each fit/predict runs in a fresh process. Derive equations only from fit "
            "payload training arrays. predict_derivative must evaluate only the frozen "
            "artifact and current query, with no fitting. Choose the scientific library, "
            "candidate feature construction, estimator, sparsification, and thresholds "
            "yourself; none are supplied by the orchestration layer. Output no Markdown."
        ),
    }
    user_payload: dict[str, Any] = {
        "task": "author a general fit-freeze-predict scientific equation-discovery candidate",
        "immutable_plan_hash": plan.plan_hash,
        "immutable_erratum_hash": erratum.erratum_hash,
        "corrected_registry_hash": erratum.corrected_sentinel_registry_hash,
        "interface_contract": interface,
        "synthetic_gate_contract": frozen_gates,
        "capability_metadata_without_ids_values_or_truth": capability_metadata,
        "available_environment_dependencies": plan.baseline_probe.dependencies,
        "runtime": runtime.model_dump(mode="json"),
        "primary_source_evidence": source_evidence,
        "official_development_values_visible": False,
        "confirmation_identity_visible": False,
        "expected_synthetic_equations_visible": False,
        "generic_method_supplied_by_orchestrator": False,
    }
    messages = [
        system_message,
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
        },
    ]
    if previous_revision is not None:
        source_path = _inside(output_root, previous_revision.source_relative_path)
        feedback = {
            "previous_revision_id": previous_revision.revision_id,
            "previous_source_sha256": previous_revision.source_sha256,
            "previous_exact_source": source_path.read_bytes().decode("utf-8"),
            "previous_static_findings": [
                item.model_dump(mode="json")
                for item in previous_revision.static_review.findings
            ],
            "previous_synthetic_observation": _condensed_observation(
                output_root,
                previous_revision,
            ),
            # Numbered source and an explicit name list remove the guesswork that
            # made text-anchor patching fail in live runs v10, v12, and v13.
            "previous_exact_source_numbered": _numbered_source(
                source_path.read_bytes().decode("utf-8")
            ),
            "replaceable_top_level_function_names": sorted(
                _top_level_function_spans(source_path.read_bytes().decode("utf-8"))
            ),
            "repair_rule": (
                "Use only this synthetic evidence to form a mechanism-level hypothesis and "
                "return one scientific_contract_patch object with the supplied parent "
                "source hash and 1..8 function_replacements. Each must name one function "
                "from replaceable_top_level_function_names and supply that function's "
                "COMPLETE replacement as new_source_lines, one element per physical line, "
                "beginning with its own unindented 'def' line. The line numbers shown are "
                "for your reading only; address edits by function name. If a whole rewrite "
                "is needed, return a complete scientific_contract_source response instead. "
                "Do not merely tune a fixture-specific constant and do not ask the "
                "orchestrator to invent or edit scientific code."
            ),
        }
        messages.append(
            {
                "role": "user",
                "content": json.dumps(feedback, ensure_ascii=False, sort_keys=True),
            }
        )
    if patch_failure_feedback:
        # Task 267.2 follow-up: a patch that could not be applied is a technical
        # fault. Feed the exact addressing error back instead of ending the run.
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "previous_patch_rejected": True,
                        "patch_failure": patch_failure_feedback,
                        "patch_addressing_rule": (
                            "Address every edit by an existing top-level function "
                            "name from replaceable_top_level_function_names, and "
                            "supply that function's COMPLETE replacement as "
                            "new_source_lines beginning with its own unindented "
                            "'def' line. Do not send text anchors, and do not emit "
                            "a replacement identical to the parent."
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return messages


def _condensed_observation(
    output_root: Path,
    revision: ScientificContractRevision,
) -> dict[str, Any] | None:
    if revision.observation_relative_path is None:
        return None
    path = _inside(output_root, revision.observation_relative_path)
    observation = ScientificContractHarnessObservation.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    results: list[dict[str, Any]] = []
    for item in observation.sentinel_results:
        results.append(
            {
                key: item.get(key)
                for key in (
                    "data_type",
                    "spatial_dimensions",
                    "field_count",
                    "query_shape",
                    "primary_prediction_nmse",
                    "shuffled_prediction_nmse",
                    "shuffle_nmse_ratio",
                    "zero_null_relative_improvement",
                    "primary_term_support_f1",
                    "alternative_term_support_f1",
                    "primary_coefficient_relative_error",
                    "alternative_coefficient_relative_error",
                    "maximum_equation_prediction_delta",
                    "artifact_changed_on_alternative_training",
                    "equation_changed_on_alternative_training",
                    "maximum_fit_seconds",
                    "maximum_predict_seconds",
                    "nonfinite_metrics",
                    "failure_codes",
                    "error_type",
                    "error_message",
                    "passed",
                )
                if key in item
            }
        )
    return {
        "passed_sentinel_count": observation.passed_sentinel_count,
        "sentinel_count": observation.sentinel_count,
        "results_without_ids_expected_values_or_expected_equations": results,
    }


def _revision_failures(
    review: ScientificContractStaticReview,
    observation: ScientificContractHarnessObservation | None,
) -> tuple[str, ...]:
    failures = [f"static:{item.code}" for item in review.findings]
    if review.approved and observation is None:
        failures.append("harness:no_observation")
    if observation is not None:
        for index, result in enumerate(observation.sentinel_results, start=1):
            for code in result.get("failure_codes", []):
                failures.append(f"synthetic-{index}:{code}")
    return tuple(dict.fromkeys(failures))


def classify_revision_failure_kind(failure_codes: Sequence[str]) -> str:
    """Classify a revision failure as technical, scientific, or none.

    Task 267.2.  A schema/transport `ContractError` means the candidate never
    reached a scientific verdict, so it must not consume the bounded scientific
    revision budget.  Only a genuine scientific failure -- zero-null
    equivalence, absent training dependence, equation/prediction disagreement,
    leakage, or shuffle non-degradation -- is budget-consuming and fail-closed.

    Precedence is deliberate: if any scientific failure is present the revision
    counts as scientific, because a real scientific verdict was reached.
    """

    if not failure_codes:
        return "none"
    if any(_is_scientific_failure_code(code) for code in failure_codes):
        return "scientific"
    if all(_is_technical_failure_code(code) for code in failure_codes):
        return "technical"
    return "scientific"


def _is_technical_failure_code(code: str) -> bool:
    """Return True for a format/transport fault with no scientific verdict."""

    suffix = code.split(":", 1)[-1]
    return suffix in _TECHNICAL_FAILURE_SUFFIXES


def _is_scientific_failure_code(code: str) -> bool:
    """Return True for a fault that represents a real scientific verdict."""

    suffix = code.split(":", 1)[-1]
    return suffix in _SCIENTIFIC_FAILURE_SUFFIXES


def _validate_parent_boundary(
    plan: ScientificContractRecoveryPlan,
    erratum: SentinelIdentifiabilityErratum,
    plan_path: Path,
) -> None:
    if Path(erratum.parent_plan_path).resolve() != plan_path:
        raise ScientificContractHarnessError("erratum does not bind the requested plan")
    if erratum.parent_plan_hash != plan.plan_hash:
        raise ScientificContractHarnessError("erratum parent plan hash changed")
    zero_values = (
        plan.new_official_development_result_count,
        plan.candidate_answer_count,
        plan.model_interaction_count,
        plan.confirmation_identity_read_count,
        plan.confirmation_result_count,
        erratum.new_official_development_result_count,
        erratum.candidate_answer_count,
        erratum.model_interaction_count,
        erratum.confirmation_identity_read_count,
        erratum.confirmation_result_count,
    )
    if any(zero_values):
        raise ScientificContractHarnessError("Task 266.2 parent is no longer result-blind")
    if not plan.harness_implementation_authorized or not erratum.harness_implementation_authorized:
        raise ScientificContractHarnessError("Task 266.2 Harness was not authorized")
    if (
        plan.official_development_execution_authorized
        or plan.confirmation_authorized
        or plan.publication_ready
        or erratum.official_development_execution_authorized
        or erratum.confirmation_authorized
        or erratum.publication_ready
    ):
        raise ScientificContractHarnessError("Task 266.2 parent authorization broadened")


def _validate_resumed_identity(
    identity: ScientificContractRunIdentity,
    *,
    plan: ScientificContractRecoveryPlan,
    erratum: SentinelIdentifiabilityErratum,
    runtime: ScientificContractRuntimeEnvironment,
    runner_sha256: str,
) -> None:
    if (
        identity.plan_hash != plan.plan_hash
        or identity.erratum_hash != erratum.erratum_hash
        or identity.corrected_sentinel_registry_hash
        != erratum.corrected_sentinel_registry_hash
        or identity.runtime != runtime
        or identity.runner_sha256 != runner_sha256
    ):
        raise ScientificContractHarnessError("resumed scientific identity changed")


def _validate_revision_files(root: Path, revision: ScientificContractRevision) -> None:
    source_path = _inside(root, revision.source_relative_path)
    if not source_path.is_file() or file_hash(source_path) != revision.source_sha256:
        raise ScientificContractHarnessError(
            f"scientific revision source changed: {revision.revision_id}"
        )
    source_text = source_path.read_bytes().decode("utf-8")
    if isinstance(revision.ophis_response, ScientificContractSourceResponse):
        expected_source = revision.ophis_response.source_text
    else:
        derivation = revision.source_derivation
        if derivation is None:
            raise ScientificContractHarnessError(
                "scientific patch revision lost its derivation"
            )
        parent_revision_path = _inside(
            root,
            Path("revisions") / derivation.parent_revision_id.replace(
                "scientific-contract-r",
                "revision-",
            ) / "revision.json",
        )
        if not parent_revision_path.is_file():
            raise ScientificContractHarnessError("scientific patch parent is missing")
        parent_revision = ScientificContractRevision.model_validate_json(
            parent_revision_path.read_text(encoding="utf-8")
        )
        parent_source_path = _inside(root, parent_revision.source_relative_path)
        parent_source = parent_source_path.read_bytes().decode("utf-8")
        if (
            parent_revision.revision_id != derivation.parent_revision_id
            or parent_revision.source_sha256 != derivation.parent_source_sha256
            or file_hash(parent_source_path) != derivation.parent_source_sha256
        ):
            raise ScientificContractHarnessError("scientific patch parent changed")
        expected_source = _apply_model_authored_patch(
            parent_source,
            revision.ophis_response,
        )
    if source_text != expected_source:
        raise ScientificContractHarnessError(
            f"scientific revision source derivation changed: {revision.revision_id}"
        )
    interaction_path = _inside(root, revision.interaction_relative_path)
    if not interaction_path.is_file():
        raise ScientificContractHarnessError("scientific interaction is missing")
    interaction = AutonomousModelInteraction.model_validate_json(
        interaction_path.read_text(encoding="utf-8")
    )
    if interaction != revision.model_interaction:
        raise ScientificContractHarnessError("scientific interaction changed")
    static_path = _inside(root, revision.static_review_relative_path)
    static_review = ScientificContractStaticReview.model_validate_json(
        static_path.read_text(encoding="utf-8")
    )
    if static_review != revision.static_review:
        raise ScientificContractHarnessError("scientific static review changed")
    spec = HarnessSpec.model_validate_json(
        _inside(root, revision.harness_spec_relative_path).read_text(encoding="utf-8")
    )
    episode = EpisodePackage.model_validate_json(
        _inside(root, revision.episode_relative_path).read_text(encoding="utf-8")
    )
    if spec.spec_hash != revision.harness_spec_hash or episode.episode_hash != revision.episode_hash:
        raise ScientificContractHarnessError("scientific Harness episode changed")
    if revision.observation_relative_path is not None:
        observation = ScientificContractHarnessObservation.model_validate_json(
            _inside(root, revision.observation_relative_path).read_text(encoding="utf-8")
        )
        if observation.observation_hash != revision.observation_hash:
            raise ScientificContractHarnessError("scientific observation changed")


def _build_file_manifest(root: Path) -> tuple[ScientificContractFileArtifact, ...]:
    artifacts = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == _PACKAGE_NAME or path.name.startswith("."):
            continue
        artifacts.append(
            ScientificContractFileArtifact(
                relative_path=relative,
                sha256=file_hash(path),
                size_bytes=path.stat().st_size,
            )
        )
    return tuple(artifacts)


def _render_markdown(
    identity: ScientificContractRunIdentity,
    revisions: Sequence[ScientificContractRevision],
    passed: bool,
) -> str:
    patch_count = sum(
        isinstance(item.ophis_response, ScientificContractPatchResponse)
        for item in revisions
    )
    if patch_count:
        rows = "\n".join(
            "| "
            + " | ".join(
                (
                    item.revision_id,
                    item.source_sha256,
                    (
                        "exact-patch"
                        if isinstance(
                            item.ophis_response,
                            ScientificContractPatchResponse,
                        )
                        else "complete-source"
                    ),
                    str(item.static_review.approved).lower(),
                    str(item.observation_hash or "none"),
                    ", ".join(item.failure_codes) or "none",
                    str(item.passed).lower(),
                )
            )
            + " |"
            for item in revisions
        )
        patch_line = f"- Model-authored exact patches: `{patch_count}`\n"
        table_header = (
            "| Revision | Exact source SHA-256 | Source mode | Static review | "
            "Observation | Failures | Passed |\n"
            "|---|---|---|---:|---|---|---:|"
        )
    else:
        rows = "\n".join(
            "| "
            + " | ".join(
                (
                    item.revision_id,
                    item.source_sha256,
                    str(item.static_review.approved).lower(),
                    str(item.observation_hash or "none"),
                    ", ".join(item.failure_codes) or "none",
                    str(item.passed).lower(),
                )
            )
            + " |"
            for item in revisions
        )
        patch_line = ""
        table_header = (
            "| Revision | Exact source SHA-256 | Static review | Observation | "
            "Failures | Passed |\n"
            "|---|---|---:|---|---|---:|"
        )
    return f"""# Task 266.2 — model-originated scientific-contract Harness

- Plan hash: `{identity.plan_hash}`
- Identifiability erratum hash: `{identity.erratum_hash}`
- Corrected sentinel registry: `{identity.corrected_sentinel_registry_hash}`
- Runner hash: `{identity.runner_sha256}`
- Runtime image ID: `{identity.runtime.image_id}`
- Model-only revisions used: `{len(revisions)}` of `{identity.maximum_model_only_revisions}`
{patch_line}\
- Synthetic contract gate passed: `{str(passed).lower()}`
- Official development results/reads: `0/0`
- Confirmation identity/results reads: `0/0`
- Publication ready: `false`

{table_header}
{rows}

## Boundary

The configured model authored every candidate and repair byte. Generic orchestration transported
arrays, froze artifacts, evaluated equations, and enforced isolation; it inserted zero scientific
methods, coefficients, or equation terms. Synthetic success authorizes only Task 266.3 bounded
development evaluation. It is not a benchmark improvement, significance, novelty, competition,
manuscript, or publication claim.
"""


def _is_transport_delimiter(line: str) -> bool:
    """True only for an exactly unindented bare JSON delimiter line.

    Deliberately strict. Matching the STRIPPED form would delete legitimate Python
    such as the closing `    }` of a returned dict literal, which silently
    truncated candidate source during development of this repair.
    """

    return line in _DELIMITER_ONLY_LINES


def _top_level_function_spans(source_text: str) -> dict[str, tuple[int, int]]:
    """Map each top-level function name to its inclusive 1-based line span.

    Uses the AST rather than text search, so a decorator, a nested function, or a
    docstring containing `def ` cannot confuse the span. A top-level function name
    is unique by Python's own rules, which is precisely why addressing a patch by
    name removes the ambiguity that ended live runs v10, v12, and v13.
    """

    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return {}
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        start = node.lineno
        for decorator in node.decorator_list:
            # A decorator belongs to the function, so include it in the span.
            start = min(start, decorator.lineno)
        end = node.end_lineno or node.lineno
        spans[node.name] = (start, end)
    return spans


def _numbered_source(source_text: str) -> str:
    """Render source with 1-based line numbers for model-facing feedback."""

    lines = source_text.split("\n")
    width = len(str(len(lines)))
    return "\n".join(
        f"{index:>{width}} | {line}" for index, line in enumerate(lines, start=1)
    )


def _looks_like_collapsed_newlines(source_text: str) -> bool:
    """Detect source whose newline escapes were emitted as a bare letter n.

    Observed live in run v10. Heuristic: substantial source, almost no real line
    breaks, and recognisable Python keywords immediately followed by `n`, as in
    `import numpy as npnimport pysindy`.
    """

    if len(source_text) < 400:
        return False
    if source_text.count("\n") > 2:
        return False
    markers = ("npnimport", "nimport ", "ndef ", "nreturn ", ")nn", ":n    ")
    return sum(marker in source_text for marker in markers) >= 2


def _finding(
    code: str,
    message: str,
    *,
    line: int | None = None,
) -> ScientificContractSecurityFinding:
    return ScientificContractSecurityFinding(code=code, message=message, line=line)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ScientificContractHarnessError(
            f"scientific artifact path escapes package: {relative_path}"
        ) from exc
    return candidate


def _bind_mount(source: Path, destination: str) -> str:
    return f"type=bind,src={source.resolve().as_posix()},dst={destination},readonly"


__all__ = [
    "ScientificContractHarnessError",
    "ScientificContractHarnessObservation",
    "ScientificContractHarnessPackage",
    "ScientificContractRunIdentity",
    "ScientificContractRuntimeEnvironment",
    "ScientificContractSourceResponse",
    "ScientificContractStaticReview",
    "build_scientific_contract_harness_package",
    "execute_scientific_contract_container",
    "inspect_scientific_contract_runtime",
    "load_scientific_contract_harness_package",
    "review_scientific_contract_source",
]
