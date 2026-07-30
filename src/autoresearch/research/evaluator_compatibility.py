"""Result-blind evaluator compatibility certificate for Task 263.6.1.

The certificate is deliberately separate from the consumed Task 263.6 result
tree.  It reads only the result-free confirmation freeze and its frozen
execution assets, builds deterministic synthetic ARFF fixtures, and exercises
the next-version evaluator in both pinned clean interpreters.  It neither
opens confirmation task bundles nor reads any confirmation outcome.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from . import confirmatory_evaluation as confirmation
from .confirmatory_evaluation import (
    CONFIRMATION_FREEZE_FILENAME,
    ConfirmatoryEvaluationFreeze,
    ConfirmatoryLabels,
    audit_independent_execution_source,
    load_confirmatory_freeze,
)
from .development_search import CandidateSpec
from .portfolio import PortfolioIntegrityError

CERTIFICATE_REPORT_FILENAME = "evaluator-compatibility-report.json"
CERTIFICATE_MARKDOWN_FILENAME = "evaluator-compatibility-report.md"
CERTIFICATE_MANIFEST_FILENAME = "evaluator-compatibility-manifest.json"
CERTIFICATE_SCHEMA_FILENAME = "evaluator-compatibility-schemas.json"

V2_CONFIRMATION_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_confirmation_runner_v2.py"
)
V2_CANDIDATE_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v2.py"
)
V1_CANDIDATE_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v1.py"
)
V1_CONFIRMATION_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_tabular_confirmation_runner_v1.py"
)
V1_POLICY_CONTROLLER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_confirmation_policy_controller_v1.py"
)

LABEL_TOKEN_CONTRACT = "canonical-string-label-v2"
REGRESSION_LABEL_CONTRACT = "finite-float-label-v1"
REQUIRED_FIXTURE_PROPERTIES = {
    "dense-arff",
    "sparse-arff",
    "numeric-looking-class-labels",
    "string-class-labels",
    "quoted-comma-tokens",
    "mixed-type-features",
    "unseen-test-category",
    "regression-target",
}
RESULT_FREE_SOURCE_RELATIVE_PATHS = (
    CONFIRMATION_FREEZE_FILENAME,
    "execution-assets/frozen_confirmation_policy_controller_v1.py",
    "execution-assets/frozen_tabular_confirmation_runner_v1.py",
    "execution-assets/frozen_tabular_candidate_runner_v2.py",
    "execution-assets/frozen_tabular_candidate_runner_v1.py",
    "execution-assets/frozen_flaml_baseline_v1.py",
    "execution-assets/objective_evaluators.py",
)
FORBIDDEN_CONFIRMATION_SOURCE_NAMES = {
    "confirmatory-evaluation-report.json",
    "confirmatory-evaluation-manifest.json",
    "confirmatory-execution-index.json",
    "confirmation-reveal-ledger.json",
    "primary-execution",
    "clean-room-replay",
    "task-bundles",
}
REPRESENTATIVE_CANDIDATE_IDS = (
    "null-prior",
    "linear-raw",
    "linear-scaled",
    "lgbm-shallow",
    "xgb-shallow",
    "random-forest",
    "extra-trees",
    "hist-gradient",
    "tree-ensemble",
)
INVALID_CONTROL_CANDIDATE_ID = "invalid-schema-probe"
EXPECTED_ALLOWED_LEARNERS = {
    "dummy",
    "linear",
    "lgbm",
    "xgboost",
    "rf",
    "extra_tree",
    "hist_gb",
    "lgbm_xgboost_ensemble",
    "invalid_probe",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _with_canonical_hash(
    model: type[KernelContract],
    payload: Mapping[str, Any],
    field: str,
) -> dict[str, Any]:
    normalized = model.model_construct(**dict(payload)).model_dump(
        mode="json",
        exclude={field},
    )
    normalized[field] = canonical_sha256(normalized)
    return normalized


def _verify_json_hash(payload: Mapping[str, Any], field: str) -> None:
    expected = payload.get(field)
    if not isinstance(expected, str):
        raise PortfolioIntegrityError(f"{field} is missing")
    body = dict(payload)
    body.pop(field, None)
    if canonical_sha256(body) != expected:
        raise PortfolioIntegrityError(f"{field} mismatch")


def _write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def _csv_data_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


class EvaluatorCompatibilityStatus(str, Enum):
    """Terminal state of the result-blind evaluator certificate."""

    CERTIFIED = "certified"
    INVALID = "invalid"


class EvaluatorCompatibilityFixture(KernelContract):
    """Content-addressed synthetic input spanning one evaluator boundary."""

    schema_version: Literal["evaluator-compatibility-fixture-v1"] = (
        "evaluator-compatibility-fixture-v1"
    )
    fixture_id: StableId
    family: Literal["tabular_classification", "tabular_regression"]
    source_encoding: Literal["dense", "sparse"]
    covered_properties: list[StableId] = Field(min_length=1)
    source_arff_sha256: Sha256
    split_sha256: Sha256
    train_sha256: Sha256
    test_sha256: Sha256
    labels_sha256: Sha256
    input_manifest_sha256: Sha256
    train_row_count: int = Field(ge=12)
    test_row_count: int = Field(ge=4)
    feature_columns: list[StableId] = Field(min_length=1)
    label_token_contract: Literal[
        "canonical-string-label-v2",
        "finite-float-label-v1",
    ]
    fixture_hash: Sha256

    @field_validator("covered_properties")
    @classmethod
    def _normalize_properties(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("fixture properties are duplicated")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> EvaluatorCompatibilityFixture:
        if self.fixture_hash != self.calculated_hash():
            raise PortfolioIntegrityError("evaluator fixture_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EvaluatorCompatibilityFixture:
        payload = dict(values)
        payload["schema_version"] = "evaluator-compatibility-fixture-v1"
        payload["covered_properties"] = sorted(payload["covered_properties"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "fixture_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fixture_hash"}))


class EvaluatorCompatibilityProbe(KernelContract):
    """One exact runner invocation retained by the compatibility matrix."""

    schema_version: Literal["evaluator-compatibility-probe-v1"] = (
        "evaluator-compatibility-probe-v1"
    )
    probe_id: StableId
    interpreter_role: Literal["primary", "replay"]
    repeat_index: Literal[1, 2]
    fixture_id: StableId
    candidate_id: StableId
    learner: StableId
    preprocessing: StableId
    stage: Literal["F2", "F3"]
    expected_status: Literal["succeeded", "failed"]
    expected_failure_domain: Literal["candidate"] | None = None
    actual_status: Literal["succeeded", "failed"]
    failure_domain: Literal["input", "candidate", "evaluator"] | None = None
    failure_code: StableId | None = None
    return_code: int
    labels_accessed: bool
    label_token_contract: Literal[
        "canonical-string-label-v2",
        "finite-float-label-v1",
    ]
    score: float | None = None
    prediction_count: int = Field(ge=0)
    prediction_sha256: Sha256 | None = None
    memory_valid: bool | None = None
    network_allowed: Literal[False] = False
    result_relative_path: NonEmptyText
    result_file_sha256: Sha256
    result_hash: Sha256
    scientific_projection_hash: Sha256
    probe_hash: Sha256

    @model_validator(mode="after")
    def _validate_probe(self) -> EvaluatorCompatibilityProbe:
        if self.actual_status == "succeeded":
            if (
                self.failure_domain is not None
                or self.failure_code is not None
                or self.score is None
                or self.prediction_count < 1
                or self.prediction_sha256 is None
                or self.memory_valid is not True
            ):
                raise ValueError("successful compatibility probe is incomplete")
        elif self.failure_domain is None or self.failure_code is None:
            raise ValueError("failed compatibility probe has no failure attribution")
        if self.expected_status == "failed" and self.expected_failure_domain is None:
            raise ValueError("expected probe failure has no expected domain")
        if self.probe_hash != self.calculated_hash():
            raise PortfolioIntegrityError("evaluator probe_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EvaluatorCompatibilityProbe:
        payload = {
            "schema_version": "evaluator-compatibility-probe-v1",
            **values,
            "network_allowed": False,
        }
        return cls.model_validate(_with_canonical_hash(cls, payload, "probe_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"probe_hash"}))


EXPECTED_CERTIFICATE_CHECKS = {
    "all-allowed-learners-covered",
    "all-fixture-properties-covered",
    "all-valid-probes-succeeded",
    "both-pinned-interpreters-covered",
    "cross-interpreter-scientific-projection-exact",
    "f2-label-isolation-proved",
    "fixture-resume-reconstructed-and-verified",
    "intentional-invalid-probe-candidate-attributed",
    "network-disabled",
    "no-confirmation-result-or-task-bundle-access",
    "null-prior-zero-integrity-failures",
    "package-lock-and-interpreter-hashes-exact",
    "prediction-replay-exact-within-interpreter",
    "runner-static-audit-passed",
    "v1-frozen-sources-preserved",
}


class EvaluatorCompatibilityReport(KernelContract):
    """Fail-closed two-interpreter compatibility certificate."""

    schema_version: Literal["evaluator-compatibility-report-v1"] = (
        "evaluator-compatibility-report-v1"
    )
    certificate_id: Literal["task-263.6.1-evaluator-compatibility-v1"] = (
        "task-263.6.1-evaluator-compatibility-v1"
    )
    status: EvaluatorCompatibilityStatus
    source_confirmation_freeze_hash: Sha256
    source_confirmation_orchestrator_sha256: Sha256
    source_accessed_relative_paths: list[NonEmptyText]
    source_confirmation_results_accessed: Literal[False] = False
    source_confirmation_task_bundles_accessed: Literal[False] = False
    source_confirmation_panel_reopened: Literal[False] = False
    candidate_catalog_hash: Sha256
    candidate_ids: list[StableId] = Field(min_length=10, max_length=10)
    allowed_learners: list[StableId] = Field(min_length=9, max_length=9)
    fixture_properties: list[StableId] = Field(min_length=8)
    fixtures: list[EvaluatorCompatibilityFixture] = Field(min_length=4, max_length=4)
    probes: list[EvaluatorCompatibilityProbe] = Field(min_length=152, max_length=152)
    f3_valid_probe_count: Literal[144] = 144
    expected_candidate_failure_probe_count: Literal[4] = 4
    f2_label_isolation_probe_count: Literal[4] = 4
    null_prior_integrity_failure_count: int = Field(ge=0)
    unexpected_candidate_failure_count: int = Field(ge=0)
    evaluator_failure_count: int = Field(ge=0)
    input_failure_count: int = Field(ge=0)
    checks: dict[StableId, bool]
    protected_v1_source_hashes_before: dict[NonEmptyText, Sha256]
    protected_v1_source_hashes_after: dict[NonEmptyText, Sha256]
    execution_asset_hashes: dict[StableId, Sha256]
    clean_interpreter_hashes: dict[Literal["primary", "replay"], Sha256]
    clean_environment_snapshot_hashes: dict[Literal["primary", "replay"], Sha256]
    schema_bundle_sha256: Sha256
    orchestrator_source_sha256: Sha256
    network_accessed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    created_at: datetime
    report_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("certificate time must be timezone-aware")
        return value

    @field_validator(
        "candidate_ids",
        "allowed_learners",
        "fixture_properties",
        "source_accessed_relative_paths",
    )
    @classmethod
    def _normalize_unique_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("certificate list contains duplicates")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_report(self) -> EvaluatorCompatibilityReport:
        if set(self.checks) != EXPECTED_CERTIFICATE_CHECKS:
            raise ValueError("certificate check inventory changed")
        expected_status = (
            EvaluatorCompatibilityStatus.CERTIFIED
            if all(self.checks.values())
            else EvaluatorCompatibilityStatus.INVALID
        )
        if self.status is not expected_status:
            raise ValueError("certificate status/check conjunction mismatch")
        if len({item.probe_id for item in self.probes}) != len(self.probes):
            raise ValueError("certificate probe IDs are duplicated")
        if self.protected_v1_source_hashes_before != self.protected_v1_source_hashes_after:
            raise PortfolioIntegrityError("protected v1 source changed during certification")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("evaluator report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EvaluatorCompatibilityReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "evaluator-compatibility-report-v1",
                "certificate_id": "task-263.6.1-evaluator-compatibility-v1",
                "f3_valid_probe_count": 144,
                "expected_candidate_failure_probe_count": 4,
                "f2_label_isolation_probe_count": 4,
                "source_confirmation_results_accessed": False,
                "source_confirmation_task_bundles_accessed": False,
                "source_confirmation_panel_reopened": False,
                "network_accessed": False,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        for field in (
            "candidate_ids",
            "allowed_learners",
            "fixture_properties",
            "source_accessed_relative_paths",
        ):
            payload[field] = sorted(payload[field])
        payload["fixtures"] = sorted(payload["fixtures"], key=lambda item: item.fixture_id)
        payload["probes"] = sorted(payload["probes"], key=lambda item: item.probe_id)
        payload["checks"] = dict(sorted(payload["checks"].items()))
        return cls.model_validate(_with_canonical_hash(cls, payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class EvaluatorCompatibilityArtifactManifest(KernelContract):
    """Complete content inventory for the compatibility certificate."""

    schema_version: Literal["evaluator-compatibility-manifest-v1"] = (
        "evaluator-compatibility-manifest-v1"
    )
    certificate_id: Literal["task-263.6.1-evaluator-compatibility-v1"] = (
        "task-263.6.1-evaluator-compatibility-v1"
    )
    status: EvaluatorCompatibilityStatus
    report_hash: Sha256
    source_confirmation_freeze_hash: Sha256
    artifact_hashes: dict[NonEmptyText, Sha256]
    artifact_count: int = Field(ge=1)
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> EvaluatorCompatibilityArtifactManifest:
        if list(self.artifact_hashes) != sorted(self.artifact_hashes):
            raise ValueError("certificate artifact paths must be sorted")
        if self.artifact_count != len(self.artifact_hashes):
            raise ValueError("certificate artifact count mismatch")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("evaluator manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EvaluatorCompatibilityArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "evaluator-compatibility-manifest-v1",
                "certificate_id": "task-263.6.1-evaluator-compatibility-v1",
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["artifact_hashes"] = dict(sorted(payload["artifact_hashes"].items()))
        payload["artifact_count"] = len(payload["artifact_hashes"])
        return cls.model_validate(_with_canonical_hash(cls, payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


@dataclass(frozen=True)
class _FixtureDefinition:
    fixture_id: str
    family: Literal["tabular_classification", "tabular_regression"]
    source_encoding: Literal["dense", "sparse"]
    covered_properties: tuple[str, ...]
    arff_bytes: bytes
    train_row_ids: tuple[int, ...]
    test_row_ids: tuple[int, ...]


@dataclass(frozen=True)
class CompatibilityFixtureBundle:
    """Verified fixture paths plus resume-reconstructed feature metadata."""

    fixture: EvaluatorCompatibilityFixture
    root: Path
    source_path: Path
    split_path: Path
    train_path: Path
    test_path: Path
    labels_path: Path
    manifest_path: Path
    feature_columns: tuple[str, ...]


def _dense_numeric_classification_fixture() -> _FixtureDefinition:
    lines = [
        "@relation numeric_labels",
        "@attribute numeric_a numeric",
        "@attribute numeric_b numeric",
        "@attribute target {0,1}",
        "@data",
    ]
    for index in range(48):
        first = (index % 9) - 4
        second = ((index * 7) % 13) - 6
        label = index % 2
        lines.append(f"{first},{second},{label}")
    return _FixtureDefinition(
        fixture_id="dense-numeric-labels",
        family="tabular_classification",
        source_encoding="dense",
        covered_properties=("dense-arff", "numeric-looking-class-labels"),
        arff_bytes=("\n".join(lines) + "\n").encode(),
        train_row_ids=tuple(range(36)),
        test_row_ids=tuple(range(36, 48)),
    )


def _sparse_string_classification_fixture() -> _FixtureDefinition:
    lines = [
        "@relation sparse_string_labels",
        "@attribute numeric_a numeric",
        "@attribute numeric_b numeric",
        "@attribute target {cat,dog}",
        "@data",
    ]
    for index in range(48):
        entries = [f"0 {(index % 5) + 1}"]
        if index % 3:
            entries.append(f"1 {((index * 2) % 7) + 1}")
        entries.append(f"2 {'cat' if index % 2 == 0 else 'dog'}")
        lines.append("{" + ",".join(entries) + "}")
    return _FixtureDefinition(
        fixture_id="sparse-string-labels",
        family="tabular_classification",
        source_encoding="sparse",
        covered_properties=("sparse-arff", "string-class-labels"),
        arff_bytes=("\n".join(lines) + "\n").encode(),
        train_row_ids=tuple(range(36)),
        test_row_ids=tuple(range(36, 48)),
    )


def _quoted_mixed_classification_fixture() -> _FixtureDefinition:
    lines = [
        "@relation quoted_mixed",
        "@attribute numeric_feature numeric",
        "@attribute color {'red,blue',blue,green}",
        "@attribute note {alpha,'beta,quoted',gamma}",
        "@attribute target {'class,one','class,two'}",
        "@data",
    ]
    for index in range(48):
        numeric = "?" if index in {5, 22, 41} else f"{(index % 11) / 3:.6f}"
        if index >= 36 and index % 3 == 0:
            color = "green"
        else:
            color = "'red,blue'" if index % 2 == 0 else "blue"
        note = "'beta,quoted'" if index % 3 == 0 else ("alpha" if index % 3 == 1 else "gamma")
        label = "'class,one'" if index % 2 == 0 else "'class,two'"
        lines.append(f"{numeric},{color},{note},{label}")
    return _FixtureDefinition(
        fixture_id="dense-quoted-mixed-classification",
        family="tabular_classification",
        source_encoding="dense",
        covered_properties=(
            "dense-arff",
            "string-class-labels",
            "quoted-comma-tokens",
            "mixed-type-features",
            "unseen-test-category",
        ),
        arff_bytes=("\n".join(lines) + "\n").encode(),
        train_row_ids=tuple(range(36)),
        test_row_ids=tuple(range(36, 48)),
    )


def _mixed_regression_fixture() -> _FixtureDefinition:
    lines = [
        "@relation mixed_regression",
        "@attribute numeric_a numeric",
        "@attribute category {base,alternate,unseen}",
        "@attribute numeric_b numeric",
        "@attribute target numeric",
        "@data",
    ]
    for index in range(48):
        first = "?" if index in {4, 19, 38} else f"{(index % 13) / 2:.6f}"
        category = "unseen" if index >= 36 and index % 2 == 0 else (
            "base" if index % 2 == 0 else "alternate"
        )
        second = f"{((index * 5) % 17) / 4:.6f}"
        target = 0.75 * (index % 13) - 0.2 * ((index * 5) % 17) + (index % 3)
        lines.append(f"{first},{category},{second},{target:.6f}")
    return _FixtureDefinition(
        fixture_id="dense-mixed-regression",
        family="tabular_regression",
        source_encoding="dense",
        covered_properties=(
            "dense-arff",
            "mixed-type-features",
            "unseen-test-category",
            "regression-target",
        ),
        arff_bytes=("\n".join(lines) + "\n").encode(),
        train_row_ids=tuple(range(36)),
        test_row_ids=tuple(range(36, 48)),
    )


def compatibility_fixture_definitions() -> tuple[_FixtureDefinition, ...]:
    """Return the fixed result-independent compatibility corpus."""

    return (
        _dense_numeric_classification_fixture(),
        _sparse_string_classification_fixture(),
        _quoted_mixed_classification_fixture(),
        _mixed_regression_fixture(),
    )


def _fixture_manifest_hash(payload: Mapping[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in payload.items() if key != "manifest_hash"})


def _load_verified_fixture_bundle(
    definition: _FixtureDefinition,
    fixture_root: Path,
    *,
    confirmation_freeze_hash: str,
    reveal_hash: str,
) -> CompatibilityFixtureBundle:
    source_path = fixture_root / "source.arff"
    split_path = fixture_root / "split.json"
    train_path = fixture_root / "train.csv"
    test_path = fixture_root / "test.csv"
    labels_path = fixture_root / "labels.json"
    manifest_path = fixture_root / "input-manifest.json"
    required_paths = (
        source_path,
        split_path,
        train_path,
        test_path,
        labels_path,
        manifest_path,
    )
    if not all(path.is_file() for path in required_paths):
        raise PortfolioIntegrityError(
            f"compatibility fixture is only partially materialized: {definition.fixture_id}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise PortfolioIntegrityError("compatibility fixture manifest is not an object")
    _verify_json_hash(manifest, "manifest_hash")
    if (
        manifest.get("schema_version") != "evaluator-compatibility-input-v1"
        or manifest.get("fixture_id") != definition.fixture_id
        or manifest.get("family") != definition.family
        or manifest.get("source_encoding") != definition.source_encoding
        or manifest.get("confirmation_freeze_hash") != confirmation_freeze_hash
        or manifest.get("reveal_hash") != reveal_hash
    ):
        raise PortfolioIntegrityError("compatibility fixture manifest binding changed")
    expected_files = {
        "source_arff_sha256": source_path,
        "split_sha256": split_path,
        "train_sha256": train_path,
        "test_sha256": test_path,
        "labels_sha256": labels_path,
    }
    for field, path in expected_files.items():
        if manifest.get(field) != _file_sha256(path):
            raise PortfolioIntegrityError(
                f"compatibility fixture file hash mismatch: {definition.fixture_id}/{field}"
            )
    if _file_sha256(source_path) != hashlib.sha256(definition.arff_bytes).hexdigest():
        raise PortfolioIntegrityError("compatibility ARFF source changed")
    split_payload = json.loads(split_path.read_text(encoding="utf-8"))
    if not isinstance(split_payload, dict):
        raise PortfolioIntegrityError("compatibility split is not an object")
    _verify_json_hash(split_payload, "split_hash")
    if (
        split_payload.get("train_row_ids") != list(definition.train_row_ids)
        or split_payload.get("test_row_ids") != list(definition.test_row_ids)
    ):
        raise PortfolioIntegrityError("compatibility split membership changed")
    labels = ConfirmatoryLabels.model_validate_json(
        labels_path.read_text(encoding="utf-8")
    )
    if (
        labels.opaque_unit_id != f"opaque-{definition.fixture_id}"
        or labels.confirmation_freeze_hash != confirmation_freeze_hash
        or labels.reveal_hash != reveal_hash
        or labels.row_ids != list(definition.test_row_ids)
    ):
        raise PortfolioIntegrityError("compatibility label binding changed")
    feature_columns = manifest.get("feature_columns")
    if (
        not isinstance(feature_columns, list)
        or not feature_columns
        or not all(isinstance(item, str) for item in feature_columns)
    ):
        raise PortfolioIntegrityError("compatibility feature columns are invalid")
    fixture = EvaluatorCompatibilityFixture.create(
        fixture_id=definition.fixture_id,
        family=definition.family,
        source_encoding=definition.source_encoding,
        covered_properties=list(definition.covered_properties),
        source_arff_sha256=_file_sha256(source_path),
        split_sha256=_file_sha256(split_path),
        train_sha256=_file_sha256(train_path),
        test_sha256=_file_sha256(test_path),
        labels_sha256=_file_sha256(labels_path),
        input_manifest_sha256=_file_sha256(manifest_path),
        train_row_count=_csv_data_row_count(train_path),
        test_row_count=_csv_data_row_count(test_path),
        feature_columns=feature_columns,
        label_token_contract=(
            LABEL_TOKEN_CONTRACT
            if definition.family == "tabular_classification"
            else REGRESSION_LABEL_CONTRACT
        ),
    )
    if (
        manifest.get("train_row_count") != fixture.train_row_count
        or manifest.get("test_row_count") != fixture.test_row_count
    ):
        raise PortfolioIntegrityError("compatibility fixture semantic manifest changed")
    return CompatibilityFixtureBundle(
        fixture=fixture,
        root=fixture_root,
        source_path=source_path,
        split_path=split_path,
        train_path=train_path,
        test_path=test_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
        feature_columns=tuple(feature_columns),
    )


def materialize_compatibility_fixture(
    definition: _FixtureDefinition,
    fixtures_root: Path,
    *,
    confirmation_freeze_hash: str,
    reveal_hash: str,
) -> CompatibilityFixtureBundle:
    """Build or verify one fixture; the existing branch reconstructs metadata."""

    fixture_root = fixtures_root / definition.fixture_id
    source_path = fixture_root / "source.arff"
    split_path = fixture_root / "split.json"
    train_path = fixture_root / "train.csv"
    test_path = fixture_root / "test.csv"
    labels_path = fixture_root / "labels.json"
    manifest_path = fixture_root / "input-manifest.json"
    expected_paths = (
        source_path,
        split_path,
        train_path,
        test_path,
        labels_path,
        manifest_path,
    )
    existing = [path.exists() for path in expected_paths]
    if any(existing):
        if not all(existing):
            raise PortfolioIntegrityError(
                f"compatibility fixture is only partially materialized: {definition.fixture_id}"
            )
        return _load_verified_fixture_bundle(
            definition,
            fixture_root,
            confirmation_freeze_hash=confirmation_freeze_hash,
            reveal_hash=reveal_hash,
        )

    attributes, rows = confirmation._decode_arff(definition.arff_bytes)
    names = [name for name, _ in attributes]
    target_index = next(
        index for index, name in enumerate(names) if name.casefold() == "target"
    )
    feature_indexes = [index for index in range(len(attributes)) if index != target_index]
    feature_columns = [f"x-{position:04d}" for position in range(len(feature_indexes))]
    numeric_columns = [
        feature_columns[position]
        for position, source_index in enumerate(feature_indexes)
        if attributes[source_index][1].casefold() in {"numeric", "real", "integer"}
    ]
    categorical_columns = [
        column for column in feature_columns if column not in numeric_columns
    ]
    all_row_ids = [*definition.train_row_ids, *definition.test_row_ids]
    if not rows or min(all_row_ids) < 0 or max(all_row_ids) >= len(rows):
        raise ValueError("compatibility fixture split references an absent row")
    train_rows = [
        [rows[row_id][index] for index in feature_indexes]
        + [rows[row_id][target_index]]
        for row_id in definition.train_row_ids
    ]
    test_rows = [
        [row_id] + [rows[row_id][index] for index in feature_indexes]
        for row_id in definition.test_row_ids
    ]
    _write_bytes_atomic(source_path, definition.arff_bytes)
    split_body: dict[str, Any] = {
        "schema_version": "evaluator-compatibility-split-v1",
        "fixture_id": definition.fixture_id,
        "train_row_ids": list(definition.train_row_ids),
        "test_row_ids": list(definition.test_row_ids),
    }
    split_body["split_hash"] = canonical_sha256(split_body)
    _write_text_atomic(
        split_path,
        json.dumps(
            split_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    _write_csv(train_path, [*feature_columns, "target"], train_rows)
    _write_csv(test_path, ["row_id", *feature_columns], test_rows)
    raw_labels: list[str | float]
    if definition.family == "tabular_classification":
        raw_labels = [
            str(rows[row_id][target_index]) for row_id in definition.test_row_ids
        ]
    else:
        raw_labels = [
            float(rows[row_id][target_index]) for row_id in definition.test_row_ids
        ]
    labels = ConfirmatoryLabels.create(
        unit_id=f"compatibility-{definition.fixture_id}",
        opaque_unit_id=f"opaque-{definition.fixture_id}",
        family=definition.family,
        confirmation_freeze_hash=confirmation_freeze_hash,
        reveal_hash=reveal_hash,
        row_ids=list(definition.test_row_ids),
        labels=raw_labels,
        data_sha256=_file_sha256(source_path),
        split_sha256=_file_sha256(split_path),
        source_data_md5=hashlib.md5(definition.arff_bytes).hexdigest(),
    )
    _write_text_atomic(labels_path, labels.canonical_json() + "\n")
    label_token_contract = (
        LABEL_TOKEN_CONTRACT
        if definition.family == "tabular_classification"
        else REGRESSION_LABEL_CONTRACT
    )
    manifest: dict[str, Any] = {
        "schema_version": "evaluator-compatibility-input-v1",
        "fixture_id": definition.fixture_id,
        "family": definition.family,
        "source_encoding": definition.source_encoding,
        "covered_properties": sorted(definition.covered_properties),
        "feature_columns": feature_columns,
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "target_column": "target",
        "source_file": "source.arff",
        "split_file": "split.json",
        "train_file": "train.csv",
        "test_file": "test.csv",
        "labels_file": "labels.json",
        "source_arff_sha256": _file_sha256(source_path),
        "split_sha256": _file_sha256(split_path),
        "train_sha256": _file_sha256(train_path),
        "test_sha256": _file_sha256(test_path),
        "labels_sha256": _file_sha256(labels_path),
        "train_row_count": len(definition.train_row_ids),
        "test_row_count": len(definition.test_row_ids),
        "label_token_contract": label_token_contract,
        "confirmation_freeze_hash": confirmation_freeze_hash,
        "reveal_hash": reveal_hash,
    }
    manifest["manifest_hash"] = _fixture_manifest_hash(manifest)
    _write_text_atomic(
        manifest_path,
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    return _load_verified_fixture_bundle(
        definition,
        fixture_root,
        confirmation_freeze_hash=confirmation_freeze_hash,
        reveal_hash=reveal_hash,
    )


def _protected_v1_source_hashes() -> dict[str, str]:
    paths = {
        "src/autoresearch/research/confirmatory_evaluation.py": Path(
            confirmation.__file__
        ).resolve(),
        V1_CONFIRMATION_RUNNER_SOURCE_PATH.as_posix(): (
            V1_CONFIRMATION_RUNNER_SOURCE_PATH.resolve()
        ),
        V2_CANDIDATE_RUNNER_SOURCE_PATH.as_posix(): (
            V2_CANDIDATE_RUNNER_SOURCE_PATH.resolve()
        ),
        V1_CANDIDATE_RUNNER_SOURCE_PATH.as_posix(): (
            V1_CANDIDATE_RUNNER_SOURCE_PATH.resolve()
        ),
        V1_POLICY_CONTROLLER_SOURCE_PATH.as_posix(): (
            V1_POLICY_CONTROLLER_SOURCE_PATH.resolve()
        ),
    }
    return dict(
        sorted((relative, _file_sha256(path)) for relative, path in paths.items())
    )


def _verify_protected_v1_bindings(
    freeze: ConfirmatoryEvaluationFreeze,
    hashes: Mapping[str, str],
) -> None:
    expected = {
        "src/autoresearch/research/confirmatory_evaluation.py": (
            freeze.orchestrator_source_hash
        ),
        V1_CONFIRMATION_RUNNER_SOURCE_PATH.as_posix(): (
            freeze.execution_assets["candidate_runner_sha256"]
        ),
        V2_CANDIDATE_RUNNER_SOURCE_PATH.as_posix(): (
            freeze.execution_assets["candidate_runner_v2_sha256"]
        ),
        V1_CANDIDATE_RUNNER_SOURCE_PATH.as_posix(): (
            freeze.execution_assets["candidate_runner_v1_sha256"]
        ),
        V1_POLICY_CONTROLLER_SOURCE_PATH.as_posix(): (
            freeze.execution_assets["policy_controller_sha256"]
        ),
    }
    if dict(hashes) != expected:
        raise PortfolioIntegrityError("protected v1 scientific source binding changed")


def _copy_execution_assets(
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
) -> dict[str, str]:
    assets_root = output_dir / "execution-assets"
    sources = {
        "confirmation_runner_v2_sha256": V2_CONFIRMATION_RUNNER_SOURCE_PATH.resolve(),
        "candidate_runner_v2_sha256": V2_CANDIDATE_RUNNER_SOURCE_PATH.resolve(),
        "candidate_runner_v1_sha256": V1_CANDIDATE_RUNNER_SOURCE_PATH.resolve(),
    }
    targets = {
        name: assets_root / source.name for name, source in sources.items()
    }
    for name, source in sources.items():
        target = targets[name]
        if target.exists():
            if _file_sha256(target) != _file_sha256(source):
                raise PortfolioIntegrityError(f"compatibility execution asset changed: {name}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    hashes = {name: _file_sha256(path) for name, path in targets.items()}
    if hashes["candidate_runner_v2_sha256"] != freeze.execution_assets[
        "candidate_runner_v2_sha256"
    ]:
        raise PortfolioIntegrityError("compatibility candidate v2 dependency changed")
    if hashes["candidate_runner_v1_sha256"] != freeze.execution_assets[
        "candidate_runner_v1_sha256"
    ]:
        raise PortfolioIntegrityError("compatibility candidate v1 dependency changed")
    if not all(audit_independent_execution_source(path) for path in targets.values()):
        raise PortfolioIntegrityError("compatibility runner static audit failed")
    return dict(sorted(hashes.items()))


def _representative_candidates(
    freeze: ConfirmatoryEvaluationFreeze,
) -> tuple[list[CandidateSpec], CandidateSpec]:
    catalogue = {candidate.candidate_id: candidate for candidate in freeze.candidates}
    if set(REPRESENTATIVE_CANDIDATE_IDS).difference(catalogue) or (
        INVALID_CONTROL_CANDIDATE_ID not in catalogue
    ):
        raise PortfolioIntegrityError("result-free candidate catalogue is incomplete")
    valid = [catalogue[candidate_id] for candidate_id in REPRESENTATIVE_CANDIDATE_IDS]
    invalid = catalogue[INVALID_CONTROL_CANDIDATE_ID]
    learners = {candidate.learner.value for candidate in [*valid, invalid]}
    if learners != EXPECTED_ALLOWED_LEARNERS:
        raise PortfolioIntegrityError("compatibility candidate set misses an allowed learner")
    return valid, invalid


def _runner_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
        }
    )
    for key in list(environment):
        if any(
            token in key.upper()
            for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        ):
            environment.pop(key)
    return environment


def _copy_bound_input(source: Path, target: Path) -> None:
    if target.exists():
        if _file_sha256(target) != _file_sha256(source):
            raise PortfolioIntegrityError(f"compatibility attempt input changed: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


SCIENTIFIC_PROJECTION_FIELDS = (
    "schema_version",
    "runner_schema_version",
    "development_runner_v2_sha256",
    "status",
    "failure_domain",
    "failure_code",
    "failure_error_type",
    "opaque_unit_id",
    "candidate_id",
    "candidate_hash",
    "stage",
    "family",
    "metric_id",
    "score",
    "higher_is_better",
    "evaluation_split",
    "fit_row_count",
    "evaluation_row_count",
    "feature_count",
    "prediction_count",
    "prediction_sha256",
    "train_sha256",
    "test_sha256",
    "labels_sha256",
    "labels_accessed",
    "label_token_contract",
    "confirmation_freeze_hash",
    "reveal_hash",
    "seed",
    "training_fraction",
    "maximum_memory_mb",
    "memory_valid",
    "network_allowed",
)


def _scientific_projection_hash(result: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {field: result.get(field) for field in SCIENTIFIC_PROJECTION_FIELDS}
    )


def _verify_runner_result_hash(result: Mapping[str, Any]) -> None:
    _verify_json_hash(result, "result_hash")
    if result.get("schema_version") != "tabular-confirmation-candidate-result-v2":
        raise PortfolioIntegrityError("compatibility runner result schema changed")
    if result.get("network_allowed") is not False:
        raise PortfolioIntegrityError("compatibility runner enabled network access")


def _run_probe(
    *,
    output_dir: Path,
    runner_path: Path,
    interpreter: Path,
    role: Literal["primary", "replay"],
    repeat_index: Literal[1, 2],
    bundle: CompatibilityFixtureBundle,
    candidate: CandidateSpec,
    stage: Literal["F2", "F3"],
    confirmation_freeze_hash: str,
    reveal_hash: str,
    expected_status: Literal["succeeded", "failed"],
    expected_failure_domain: Literal["candidate"] | None,
) -> EvaluatorCompatibilityProbe:
    probe_id = (
        f"{role}-{bundle.fixture.fixture_id}-{candidate.candidate_id}-"
        f"{stage.lower()}-repeat-{repeat_index}"
    )
    attempt_root = output_dir / "attempts" / probe_id
    input_root = attempt_root / "input"
    train_path = input_root / "train.csv"
    test_path = input_root / "test.csv"
    labels_path = input_root / "labels.json"
    _copy_bound_input(bundle.train_path, train_path)
    _copy_bound_input(bundle.test_path, test_path)
    if stage == "F3":
        _copy_bound_input(bundle.labels_path, labels_path)
    elif labels_path.exists():
        raise PortfolioIntegrityError("F2 compatibility attempt contains a label file")

    config: dict[str, Any] = {
        "schema_version": "tabular-candidate-execution-v1",
        "execution_id": probe_id,
        "opaque_unit_id": f"opaque-{bundle.fixture.fixture_id}",
        "candidate_id": candidate.candidate_id,
        "candidate_hash": candidate.candidate_hash,
        "family": bundle.fixture.family,
        "learner": candidate.learner.value,
        "preprocessing": candidate.preprocessing.value,
        "hyperparameters": candidate.hyperparameters,
        "stage": stage,
        "training_fraction": 1.0,
        "seed": 26361001,
        "validation_fraction": 0.25,
        "train_path": train_path.resolve().as_posix(),
        "test_path": test_path.resolve().as_posix(),
        "train_sha256": _file_sha256(train_path),
        "test_sha256": _file_sha256(test_path),
        "maximum_memory_mb": 4096,
        "allowed_root": attempt_root.resolve().as_posix(),
        "confirmation_freeze_hash": confirmation_freeze_hash,
        "reveal_hash": reveal_hash,
    }
    if stage == "F3":
        config.update(
            {
                "labels_path": labels_path.resolve().as_posix(),
                "labels_sha256": _file_sha256(labels_path),
            }
        )
    config_path = attempt_root / "config.json"
    serialized_config = (
        json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    if config_path.exists():
        if config_path.read_text(encoding="utf-8") != serialized_config:
            raise PortfolioIntegrityError(f"compatibility probe config changed: {probe_id}")
    else:
        _write_text_atomic(config_path, serialized_config)
    result_path = attempt_root / "result.json"
    status_path = attempt_root / "process-status.json"
    stdout_path = attempt_root / "runner.stdout.log"
    stderr_path = attempt_root / "runner.stderr.log"
    if result_path.exists():
        if not status_path.exists():
            raise PortfolioIntegrityError(f"compatibility result has no status: {probe_id}")
        process_status = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(process_status, dict):
            raise PortfolioIntegrityError("compatibility process status is not an object")
        return_code = int(process_status["return_code"])
    else:
        completed = subprocess.run(
            [
                interpreter.as_posix(),
                runner_path.as_posix(),
                "--config",
                config_path.as_posix(),
                "--output",
                result_path.as_posix(),
            ],
            cwd=attempt_root,
            env=_runner_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        return_code = completed.returncode
        _write_text_atomic(stdout_path, completed.stdout)
        _write_text_atomic(stderr_path, completed.stderr)
        _write_text_atomic(
            status_path,
            json.dumps(
                {
                    "return_code": return_code,
                    "result_exists": result_path.exists(),
                    "stdout_sha256": _file_sha256(stdout_path),
                    "stderr_sha256": _file_sha256(stderr_path),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
    if not result_path.exists():
        raise RuntimeError(f"compatibility runner produced no result: {probe_id}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise PortfolioIntegrityError("compatibility runner result is not an object")
    _verify_runner_result_hash(result)
    expected_bindings = {
        "execution_id": probe_id,
        "opaque_unit_id": config["opaque_unit_id"],
        "candidate_id": candidate.candidate_id,
        "candidate_hash": candidate.candidate_hash,
        "stage": stage,
        "family": bundle.fixture.family,
        "train_sha256": config["train_sha256"],
        "test_sha256": config["test_sha256"],
        "confirmation_freeze_hash": confirmation_freeze_hash,
        "reveal_hash": reveal_hash,
    }
    if any(result.get(key) != value for key, value in expected_bindings.items()):
        raise PortfolioIntegrityError(f"compatibility result binding mismatch: {probe_id}")
    if stage == "F3":
        if (
            result.get("labels_accessed") is not True
            or result.get("labels_sha256") != config["labels_sha256"]
        ):
            raise PortfolioIntegrityError("F3 compatibility label binding failed")
    elif (
        result.get("labels_accessed") is not False
        or result.get("labels_sha256") is not None
        or "labels_path" in config
        or "labels_sha256" in config
    ):
        raise PortfolioIntegrityError("F2 compatibility label isolation failed")
    result_status = cast(Literal["succeeded", "failed"], result["status"])
    failure_domain = cast(
        Literal["input", "candidate", "evaluator"] | None,
        result.get("failure_domain"),
    )
    prediction_sha = cast(str | None, result.get("prediction_sha256"))
    return EvaluatorCompatibilityProbe.create(
        probe_id=probe_id,
        interpreter_role=role,
        repeat_index=repeat_index,
        fixture_id=bundle.fixture.fixture_id,
        candidate_id=candidate.candidate_id,
        learner=candidate.learner.value,
        preprocessing=candidate.preprocessing.value,
        stage=stage,
        expected_status=expected_status,
        expected_failure_domain=expected_failure_domain,
        actual_status=result_status,
        failure_domain=failure_domain,
        failure_code=result.get("failure_code"),
        return_code=return_code,
        labels_accessed=bool(result["labels_accessed"]),
        label_token_contract=result["label_token_contract"],
        score=result.get("score"),
        prediction_count=int(result["prediction_count"]),
        prediction_sha256=prediction_sha,
        memory_valid=result.get("memory_valid"),
        result_relative_path=result_path.relative_to(output_dir).as_posix(),
        result_file_sha256=_file_sha256(result_path),
        result_hash=result["result_hash"],
        scientific_projection_hash=_scientific_projection_hash(result),
    )


def _run_probe_matrix(
    *,
    output_dir: Path,
    freeze: ConfirmatoryEvaluationFreeze,
    bundles: Sequence[CompatibilityFixtureBundle],
    valid_candidates: Sequence[CandidateSpec],
    invalid_candidate: CandidateSpec,
    progress: Callable[[str], None] | None,
) -> list[EvaluatorCompatibilityProbe]:
    runner_path = (
        output_dir / "execution-assets/frozen_tabular_confirmation_runner_v2.py"
    ).resolve()
    reveal_hash = canonical_sha256(
        {
            "purpose": "task-263.6.1-result-blind-evaluator-certificate",
            "source_confirmation_freeze_hash": freeze.freeze_hash,
        }
    )
    interpreters = {
        role: Path(path).resolve()
        for role, path in freeze.clean_interpreter_paths.items()
    }
    specifications: list[
        tuple[
            Literal["primary", "replay"],
            Literal[1, 2],
            CompatibilityFixtureBundle,
            CandidateSpec,
            Literal["F2", "F3"],
            Literal["succeeded", "failed"],
            Literal["candidate"] | None,
        ]
    ] = []
    roles: tuple[Literal["primary", "replay"], ...] = ("primary", "replay")
    repeats: tuple[Literal[1, 2], ...] = (1, 2)
    for typed_role in roles:
        for typed_repeat in repeats:
            for bundle in bundles:
                for candidate in valid_candidates:
                    specifications.append(
                        (
                            typed_role,
                            typed_repeat,
                            bundle,
                            candidate,
                            "F3",
                            "succeeded",
                            None,
                        )
                    )
            specifications.append(
                (
                    typed_role,
                    typed_repeat,
                    bundles[2],
                    invalid_candidate,
                    "F3",
                    "failed",
                    "candidate",
                )
            )
            specifications.append(
                (
                    typed_role,
                    typed_repeat,
                    bundles[0],
                    valid_candidates[0],
                    "F2",
                    "succeeded",
                    None,
                )
            )
    if len(specifications) != 152:
        raise AssertionError("compatibility matrix shape changed")
    probes: list[EvaluatorCompatibilityProbe] = []
    for position, (
        role,
        repeat,
        bundle,
        candidate,
        stage,
        expected_status,
        expected_failure_domain,
    ) in enumerate(specifications, start=1):
        probe = _run_probe(
            output_dir=output_dir,
            runner_path=runner_path,
            interpreter=interpreters[role],
            role=role,
            repeat_index=repeat,
            bundle=bundle,
            candidate=candidate,
            stage=stage,
            confirmation_freeze_hash=freeze.freeze_hash,
            reveal_hash=reveal_hash,
            expected_status=expected_status,
            expected_failure_domain=expected_failure_domain,
        )
        probes.append(probe)
        if progress is not None:
            progress(
                f"{position}/152 {probe.interpreter_role} {probe.fixture_id} "
                f"{probe.candidate_id} {probe.stage} r{probe.repeat_index} "
                f"{probe.actual_status}"
            )
    return probes


def _projection_replay_checks(
    probes: Sequence[EvaluatorCompatibilityProbe],
) -> tuple[bool, bool]:
    within: dict[tuple[str, str, str, str], set[str]] = {}
    cross: dict[tuple[str, str, str, int], set[str]] = {}
    for probe in probes:
        within.setdefault(
            (
                probe.interpreter_role,
                probe.fixture_id,
                probe.candidate_id,
                probe.stage,
            ),
            set(),
        ).add(probe.scientific_projection_hash)
        cross.setdefault(
            (
                probe.fixture_id,
                probe.candidate_id,
                probe.stage,
                probe.repeat_index,
            ),
            set(),
        ).add(probe.scientific_projection_hash)
    return (
        bool(within) and all(len(values) == 1 for values in within.values()),
        bool(cross) and all(len(values) == 1 for values in cross.values()),
    )


def _certificate_checks(
    *,
    freeze: ConfirmatoryEvaluationFreeze,
    bundles: Sequence[CompatibilityFixtureBundle],
    probes: Sequence[EvaluatorCompatibilityProbe],
    before_hashes: Mapping[str, str],
    after_hashes: Mapping[str, str],
    execution_asset_hashes: Mapping[str, str],
) -> tuple[dict[str, bool], dict[str, int]]:
    valid_f3 = [
        probe
        for probe in probes
        if probe.stage == "F3" and probe.expected_status == "succeeded"
    ]
    invalid = [
        probe
        for probe in probes
        if probe.candidate_id == INVALID_CONTROL_CANDIDATE_ID
    ]
    f2 = [probe for probe in probes if probe.stage == "F2"]
    null = [probe for probe in probes if probe.candidate_id == "null-prior"]
    within_exact, cross_exact = _projection_replay_checks(probes)
    all_properties = {
        prop for bundle in bundles for prop in bundle.fixture.covered_properties
    }
    all_learners = {probe.learner for probe in probes}
    null_integrity_failures = sum(
        probe.actual_status != "succeeded"
        or probe.failure_domain is not None
        or probe.memory_valid is not True
        for probe in null
    )
    unexpected_candidate_failures = sum(
        probe.failure_domain == "candidate"
        and probe.candidate_id != INVALID_CONTROL_CANDIDATE_ID
        for probe in probes
    )
    evaluator_failures = sum(probe.failure_domain == "evaluator" for probe in probes)
    input_failures = sum(probe.failure_domain == "input" for probe in probes)
    checks = {
        "all-allowed-learners-covered": all_learners == EXPECTED_ALLOWED_LEARNERS,
        "all-fixture-properties-covered": all_properties == REQUIRED_FIXTURE_PROPERTIES,
        "all-valid-probes-succeeded": (
            len(valid_f3) == 144
            and all(
                probe.actual_status == "succeeded"
                and probe.failure_domain is None
                and probe.return_code == 0
                and probe.memory_valid is True
                for probe in valid_f3
            )
        ),
        "both-pinned-interpreters-covered": (
            {probe.interpreter_role for probe in probes} == {"primary", "replay"}
            and set(freeze.clean_interpreter_hashes) == {"primary", "replay"}
        ),
        "cross-interpreter-scientific-projection-exact": cross_exact,
        "f2-label-isolation-proved": (
            len(f2) == 4
            and all(
                probe.actual_status == "succeeded"
                and probe.labels_accessed is False
                and probe.return_code == 0
                for probe in f2
            )
        ),
        "fixture-resume-reconstructed-and-verified": all(
            bool(bundle.feature_columns) for bundle in bundles
        ),
        "intentional-invalid-probe-candidate-attributed": (
            len(invalid) == 4
            and all(
                probe.actual_status == "failed"
                and probe.failure_domain == "candidate"
                and probe.failure_code == "intentional_invalid_probe"
                and probe.return_code == 0
                for probe in invalid
            )
        ),
        "network-disabled": all(probe.network_allowed is False for probe in probes),
        "no-confirmation-result-or-task-bundle-access": (
            all(
                not FORBIDDEN_CONFIRMATION_SOURCE_NAMES.intersection(path.split("/"))
                for path in RESULT_FREE_SOURCE_RELATIVE_PATHS
            )
        ),
        "null-prior-zero-integrity-failures": null_integrity_failures == 0,
        "package-lock-and-interpreter-hashes-exact": (
            set(freeze.clean_interpreter_hashes) == {"primary", "replay"}
            and freeze.clean_environment_snapshots["primary"].installed_distributions
            == freeze.clean_environment_snapshots["replay"].installed_distributions
        ),
        "prediction-replay-exact-within-interpreter": within_exact,
        "runner-static-audit-passed": (
            len(execution_asset_hashes) == 3
            and audit_independent_execution_source(
                V2_CONFIRMATION_RUNNER_SOURCE_PATH.resolve()
            )
            and audit_independent_execution_source(
                V2_CANDIDATE_RUNNER_SOURCE_PATH.resolve()
            )
            and audit_independent_execution_source(
                V1_CANDIDATE_RUNNER_SOURCE_PATH.resolve()
            )
        ),
        "v1-frozen-sources-preserved": dict(before_hashes) == dict(after_hashes),
    }
    counts = {
        "null_prior_integrity_failure_count": null_integrity_failures,
        "unexpected_candidate_failure_count": unexpected_candidate_failures,
        "evaluator_failure_count": evaluator_failures,
        "input_failure_count": input_failures,
    }
    return dict(sorted(checks.items())), counts


def evaluator_compatibility_json_schemas() -> dict[str, Any]:
    """Return the four public contract schemas used by the certificate."""

    return {
        "EvaluatorCompatibilityArtifactManifest": (
            EvaluatorCompatibilityArtifactManifest.model_json_schema()
        ),
        "EvaluatorCompatibilityFixture": EvaluatorCompatibilityFixture.model_json_schema(),
        "EvaluatorCompatibilityProbe": EvaluatorCompatibilityProbe.model_json_schema(),
        "EvaluatorCompatibilityReport": EvaluatorCompatibilityReport.model_json_schema(),
    }


def render_evaluator_compatibility_markdown(
    report: EvaluatorCompatibilityReport,
) -> str:
    """Render a concise human-readable certificate without overclaiming science."""

    checks = "\n".join(
        f"- [{'x' if passed else ' '}] `{check}`"
        for check, passed in sorted(report.checks.items())
    )
    return (
        "# Task 263.6.1 Evaluator Compatibility Certificate\n\n"
        f"- Status: `{report.status.value}`\n"
        f"- Report SHA-256: `{report.report_hash}`\n"
        f"- Source result-free freeze: `{report.source_confirmation_freeze_hash}`\n"
        f"- Synthetic fixtures: {len(report.fixtures)}\n"
        f"- Exact subprocess probes: {len(report.probes)}\n"
        f"- Valid F3 learner probes: {report.f3_valid_probe_count}\n"
        f"- Expected invalid-control probes: "
        f"{report.expected_candidate_failure_probe_count}\n"
        f"- F2 label-isolation probes: {report.f2_label_isolation_probe_count}\n"
        f"- Null-prior integrity failures: "
        f"{report.null_prior_integrity_failure_count}\n"
        f"- Evaluator/input failures: {report.evaluator_failure_count}/"
        f"{report.input_failure_count}\n\n"
        "This is a result-blind measurement-system certificate. It does not reopen "
        "the consumed confirmation panel, repair the v1 endpoint, establish a "
        "scientific effect, authorize publication, or authorize submission.\n\n"
        "## Conjunctive checks\n\n"
        f"{checks}\n"
    )


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative == CERTIFICATE_MANIFEST_FILENAME:
            continue
        hashes[relative] = _file_sha256(path)
    return dict(sorted(hashes.items()))


def load_evaluator_compatibility_certificate(
    output_dir: Path,
    *,
    source_confirmation_dir: Path | None = None,
) -> tuple[EvaluatorCompatibilityReport, EvaluatorCompatibilityArtifactManifest]:
    """Recursively verify an existing certificate and optional source freeze."""

    report = EvaluatorCompatibilityReport.model_validate_json(
        (output_dir / CERTIFICATE_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = EvaluatorCompatibilityArtifactManifest.model_validate_json(
        (output_dir / CERTIFICATE_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    if (
        manifest.report_hash != report.report_hash
        or manifest.status != report.status
        or manifest.source_confirmation_freeze_hash
        != report.source_confirmation_freeze_hash
    ):
        raise PortfolioIntegrityError("certificate report/manifest binding mismatch")
    observed_hashes = _artifact_hashes(output_dir)
    if observed_hashes != manifest.artifact_hashes:
        raise PortfolioIntegrityError("certificate recursive artifact inventory changed")
    if _file_sha256(Path(__file__).resolve()) != report.orchestrator_source_sha256:
        raise PortfolioIntegrityError("certificate orchestrator source changed")
    for probe in report.probes:
        result_path = output_dir / probe.result_relative_path
        if (
            _file_sha256(result_path) != probe.result_file_sha256
            or json.loads(result_path.read_text(encoding="utf-8")).get("result_hash")
            != probe.result_hash
        ):
            raise PortfolioIntegrityError(f"certificate probe result changed: {probe.probe_id}")
    if source_confirmation_dir is not None:
        freeze = load_confirmatory_freeze(source_confirmation_dir)
        if freeze.freeze_hash != report.source_confirmation_freeze_hash:
            raise PortfolioIntegrityError("certificate/source freeze binding mismatch")
    return report, manifest


def run_evaluator_compatibility_certificate(
    source_confirmation_dir: Path,
    output_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> EvaluatorCompatibilityReport:
    """Build the complete Task 263.6.1 result-blind compatibility certificate."""

    source_confirmation_dir = source_confirmation_dir.resolve()
    output_dir = output_dir.resolve()
    if _within(output_dir, source_confirmation_dir):
        raise ValueError("compatibility certificate cannot be written into the v1 result tree")
    report_path = output_dir / CERTIFICATE_REPORT_FILENAME
    if report_path.exists():
        report, _ = load_evaluator_compatibility_certificate(
            output_dir,
            source_confirmation_dir=source_confirmation_dir,
        )
        return report
    output_dir.mkdir(parents=True, exist_ok=True)
    freeze = load_confirmatory_freeze(source_confirmation_dir)
    before_hashes = _protected_v1_source_hashes()
    _verify_protected_v1_bindings(freeze, before_hashes)
    execution_asset_hashes = _copy_execution_assets(output_dir, freeze)
    valid_candidates, invalid_candidate = _representative_candidates(freeze)
    reveal_hash = canonical_sha256(
        {
            "purpose": "task-263.6.1-result-blind-evaluator-certificate",
            "source_confirmation_freeze_hash": freeze.freeze_hash,
        }
    )
    bundles = [
        materialize_compatibility_fixture(
            definition,
            output_dir / "fixtures",
            confirmation_freeze_hash=freeze.freeze_hash,
            reveal_hash=reveal_hash,
        )
        for definition in compatibility_fixture_definitions()
    ]
    # Exercise the already-materialized branch immediately. This is the exact
    # branch that the frozen v1 orchestrator failed to reconstruct.
    resumed = [
        materialize_compatibility_fixture(
            definition,
            output_dir / "fixtures",
            confirmation_freeze_hash=freeze.freeze_hash,
            reveal_hash=reveal_hash,
        )
        for definition in compatibility_fixture_definitions()
    ]
    if [bundle.feature_columns for bundle in resumed] != [
        bundle.feature_columns for bundle in bundles
    ]:
        raise PortfolioIntegrityError("compatibility fixture resume metadata changed")
    schema_payload = evaluator_compatibility_json_schemas()
    _write_text_atomic(
        output_dir / CERTIFICATE_SCHEMA_FILENAME,
        json.dumps(
            schema_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    probes = _run_probe_matrix(
        output_dir=output_dir,
        freeze=freeze,
        bundles=bundles,
        valid_candidates=valid_candidates,
        invalid_candidate=invalid_candidate,
        progress=progress,
    )
    after_hashes = _protected_v1_source_hashes()
    _verify_protected_v1_bindings(freeze, after_hashes)
    checks, counts = _certificate_checks(
        freeze=freeze,
        bundles=bundles,
        probes=probes,
        before_hashes=before_hashes,
        after_hashes=after_hashes,
        execution_asset_hashes=execution_asset_hashes,
    )
    report = EvaluatorCompatibilityReport.create(
        status=(
            EvaluatorCompatibilityStatus.CERTIFIED
            if all(checks.values())
            else EvaluatorCompatibilityStatus.INVALID
        ),
        source_confirmation_freeze_hash=freeze.freeze_hash,
        source_confirmation_orchestrator_sha256=freeze.orchestrator_source_hash,
        source_accessed_relative_paths=list(RESULT_FREE_SOURCE_RELATIVE_PATHS),
        candidate_catalog_hash=freeze.claim.candidate_catalog_hash,
        candidate_ids=[
            candidate.candidate_id
            for candidate in [*valid_candidates, invalid_candidate]
        ],
        allowed_learners=sorted(EXPECTED_ALLOWED_LEARNERS),
        fixture_properties=sorted(REQUIRED_FIXTURE_PROPERTIES),
        fixtures=[bundle.fixture for bundle in bundles],
        probes=probes,
        protected_v1_source_hashes_before=dict(before_hashes),
        protected_v1_source_hashes_after=dict(after_hashes),
        execution_asset_hashes=execution_asset_hashes,
        clean_interpreter_hashes=freeze.clean_interpreter_hashes,
        clean_environment_snapshot_hashes={
            role: snapshot.snapshot_hash
            for role, snapshot in freeze.clean_environment_snapshots.items()
        },
        schema_bundle_sha256=_file_sha256(output_dir / CERTIFICATE_SCHEMA_FILENAME),
        orchestrator_source_sha256=_file_sha256(Path(__file__).resolve()),
        created_at=datetime.now(timezone.utc),
        checks=checks,
        **counts,
    )
    _write_text_atomic(report_path, report.canonical_json() + "\n")
    _write_text_atomic(
        output_dir / CERTIFICATE_MARKDOWN_FILENAME,
        render_evaluator_compatibility_markdown(report),
    )
    manifest = EvaluatorCompatibilityArtifactManifest.create(
        status=report.status,
        report_hash=report.report_hash,
        source_confirmation_freeze_hash=freeze.freeze_hash,
        artifact_hashes=_artifact_hashes(output_dir),
    )
    _write_text_atomic(
        output_dir / CERTIFICATE_MANIFEST_FILENAME,
        manifest.canonical_json() + "\n",
    )
    loaded, _ = load_evaluator_compatibility_certificate(
        output_dir,
        source_confirmation_dir=source_confirmation_dir,
    )
    return loaded
