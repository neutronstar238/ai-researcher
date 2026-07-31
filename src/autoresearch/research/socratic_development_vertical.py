"""Stop-first licensed inventory gate for the Socratic development route.

Task 263.6.5 is deliberately ordered so that dataset provenance and
independent-unit feasibility are decided before an evaluator, model call, or
scientific outcome can exist.  DiscoveryBench exposes 189 provisional
directories, but directories are not automatically independent scientific
units: real raw/processed variants share sources and DB-Synth creates several
difficulty-level datasets from one semantic tree.

This module freezes the official repository revision, audits every directory,
binds answer-key *keys* without retaining gold text, records the exact license
scope, and reproduces the inventory projection in two independent Python
installations.  If the 30-development plus 84-untouched-reserve requirement
cannot be met, it emits a content-addressed stop certificate and refuses to
authorize fault generation, baseline execution, provider configuration,
Research Question issuance, or confirmation-panel creation.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .opportunity_tournament import LiveResourceProbe
from .portfolio import (
    NearestWorkDelta,
    PortfolioIntegrityError,
    ResearchSource,
)
from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

DISCOVERYBENCH_DATASET_ID: Literal["allenai/discoverybench"] = (
    "allenai/discoverybench"
)
DISCOVERYBENCH_METADATA_URL = (
    "https://huggingface.co/api/datasets/allenai/discoverybench"
)
DISCOVERYBENCH_TREE_URL = (
    "https://huggingface.co/api/datasets/allenai/discoverybench/tree/{revision}"
    "?recursive=true&expand=false&limit=1000"
)
DISCOVERYBENCH_RESOLVE_URL = (
    "https://huggingface.co/datasets/allenai/discoverybench/resolve/"
    "{revision}/{path}?download=true"
)
DISCOVERYBENCH_LICENSE_API = (
    "https://api.github.com/repos/allenai/discoverybench/contents/LICENSE"
)
DISCOVERYBENCH_REPOSITORY_API = (
    "https://api.github.com/repos/allenai/discoverybench"
)
ASTABENCH_LICENSE_API = "https://api.github.com/repos/allenai/asta-bench/license"

INVENTORY_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_discoverybench_inventory_probe_v1.py"
)
INVENTORY_REPORT_FILENAME: Literal["socratic-development-inventory.json"] = (
    "socratic-development-inventory.json"
)
INVENTORY_MARKDOWN_FILENAME: Literal["socratic-development-inventory.md"] = (
    "socratic-development-inventory.md"
)
INVENTORY_SCHEMA_FILENAME: Literal[
    "socratic-development-inventory-schemas.json"
] = "socratic-development-inventory-schemas.json"
INVENTORY_MANIFEST_FILENAME = "socratic-development-inventory-manifest.json"
INVENTORY_REPLAY_INPUT_FILENAME: Literal["inventory-replay-input.json"] = (
    "inventory-replay-input.json"
)

REQUIRED_PROVISIONAL_FOLDER_COUNT = 189
REQUIRED_DEVELOPMENT_GROUPS: Literal[30] = 30
REQUIRED_RESERVE_GROUPS: Literal[84] = 84
REQUIRED_TOTAL_GROUPS = REQUIRED_DEVELOPMENT_GROUPS + REQUIRED_RESERVE_GROUPS

SOURCE_FOLDER_RE = re.compile(
    r"^discoverybench/(?P<kind>real|synth)/"
    r"(?P<split>train|test)/(?P<folder>[^/]+)$"
)
SYNTHETIC_FAMILY_RE = re.compile(
    r"^(?P<domain>.+)_(?P<tree_index>[0-9]+)_(?P<level_index>[0-9]+)$"
)
METADATA_FILE_RE = re.compile(r"/metadata_[0-9]+\.json$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40,64}$")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        rendered = value.isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


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


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


class DiscoveryBenchSourceKind(str, Enum):
    REAL = "real"
    SYNTHETIC = "synth"


class DiscoveryBenchSplit(str, Enum):
    TRAIN = "train"
    TEST = "test"


class DerivationKind(str, Enum):
    REAL_SOURCE = "real-source"
    REAL_RAW = "real-raw"
    REAL_PROCESSED_OR_SUBSET = "real-processed-or-subset"
    SYNTHETIC_SEMANTIC_TREE_DERIVATIVE = "synthetic-semantic-tree-derivative"


class LicenseScope(str, Enum):
    DATABASE_RIGHTS = "database-rights"
    SOFTWARE = "software"


class SocraticInventoryStatus(str, Enum):
    STOPPED_AT_INVENTORY = "stopped-at-inventory"
    READY_FOR_EVALUATOR_CONSTRUCTION = "ready-for-evaluator-construction"


class TreeEntry(KernelContract):
    """One normalized Hugging Face repository tree entry."""

    entry_type: Literal["directory", "file"]
    path: NonEmptyText
    oid: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    size: int = Field(ge=0)

    @classmethod
    def from_remote(cls, value: Mapping[str, Any]) -> TreeEntry:
        return cls(
            entry_type=value["type"],
            path=value["path"],
            oid=value["oid"],
            size=int(value.get("size", 0)),
        )


class LicenseScopeEvidence(KernelContract):
    """Content-addressed, non-legal-advice record of an observed license scope."""

    schema_version: Literal["license-scope-evidence-v1"] = (
        "license-scope-evidence-v1"
    )
    resource_id: StableId
    evidence_url: NonEmptyText
    observed_license_id: NonEmptyText
    license_file_object_id: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    license_text_sha256: Sha256
    scope: LicenseScope
    database_use_verified: bool
    software_reuse_verified: bool
    individual_contents_redistribution_verified: bool
    attribution_required: bool
    human_release_review_required: Literal[True] = True
    interpretation: NonEmptyText
    evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_evidence(self) -> LicenseScopeEvidence:
        if self.scope is LicenseScope.DATABASE_RIGHTS and self.software_reuse_verified:
            raise ValueError("a database-rights license cannot authorize software reuse")
        if self.scope is LicenseScope.SOFTWARE and self.database_use_verified:
            raise ValueError("software license evidence cannot authorize database use")
        if self.evidence_hash != self.calculated_hash():
            raise PortfolioIntegrityError("license evidence_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> LicenseScopeEvidence:
        payload = dict(values)
        payload["schema_version"] = "license-scope-evidence-v1"
        payload["human_release_review_required"] = True
        payload["evidence_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_hash"})
        )


class AnswerKeySummary(KernelContract):
    """Answer-key identity and row keys without retaining any gold hypothesis."""

    schema_version: Literal["answer-key-summary-v1"] = "answer-key-summary-v1"
    source_kind: DiscoveryBenchSourceKind
    split: Literal[DiscoveryBenchSplit.TEST] = DiscoveryBenchSplit.TEST
    path: NonEmptyText
    git_object_id: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    raw_sha256: Sha256
    decoded_encoding: Literal["utf-8-sig", "windows-1252"]
    columns: list[StableId]
    row_count: int = Field(ge=1)
    unique_dataset_count: int = Field(ge=1)
    dataset_names: list[StableId]
    key_projection_sha256: Sha256
    gold_hypothesis_text_retained: Literal[False] = False
    summary_hash: Sha256

    @field_validator("columns", "dataset_names")
    @classmethod
    def _normalize_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("answer-key lists must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_summary(self) -> AnswerKeySummary:
        if self.unique_dataset_count != len(self.dataset_names):
            raise ValueError("unique dataset count mismatch")
        if self.columns != sorted(
            ["dataset", "gold_hypo", "metadataid", "query_id"]
        ):
            raise ValueError("unexpected answer-key columns")
        if self.summary_hash != self.calculated_hash():
            raise PortfolioIntegrityError("answer-key summary_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        source_kind: DiscoveryBenchSourceKind,
        path: str,
        git_object_id: str,
        raw_bytes: bytes,
    ) -> AnswerKeySummary:
        try:
            text = raw_bytes.decode("utf-8-sig")
            decoded_encoding: Literal["utf-8-sig", "windows-1252"] = "utf-8-sig"
        except UnicodeDecodeError:
            text = raw_bytes.decode("cp1252")
            decoded_encoding = "windows-1252"
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("answer-key CSV has no header")
        columns = sorted(reader.fieldnames)
        expected = sorted(["dataset", "metadataid", "query_id", "gold_hypo"])
        if columns != expected:
            raise ValueError("unexpected answer-key columns")
        keys: list[tuple[str, str, str]] = []
        dataset_names: set[str] = set()
        for row in reader:
            dataset = (row.get("dataset") or "").strip()
            metadata_id = (row.get("metadataid") or "").strip()
            query_id = (row.get("query_id") or "").strip()
            if not dataset or not metadata_id or not query_id:
                raise ValueError("answer-key key row is incomplete")
            key = (dataset, metadata_id, query_id)
            if key in keys:
                raise ValueError("duplicate answer-key key")
            keys.append(key)
            dataset_names.add(dataset)
        payload = {
            "schema_version": "answer-key-summary-v1",
            "source_kind": source_kind,
            "split": DiscoveryBenchSplit.TEST,
            "path": path,
            "git_object_id": git_object_id,
            "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "decoded_encoding": decoded_encoding,
            "columns": columns,
            "row_count": len(keys),
            "unique_dataset_count": len(dataset_names),
            "dataset_names": sorted(dataset_names),
            "key_projection_sha256": canonical_sha256(
                [list(item) for item in sorted(keys)]
            ),
            "gold_hypothesis_text_retained": False,
        }
        payload["summary_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"summary_hash"})
        )


class DiscoveryBenchFolderAudit(KernelContract):
    """One of the 189 directories, with provenance and label lineage bound."""

    schema_version: Literal["discoverybench-folder-audit-v1"] = (
        "discoverybench-folder-audit-v1"
    )
    folder_path: StableId
    folder_name: StableId
    source_kind: DiscoveryBenchSourceKind
    split: DiscoveryBenchSplit
    source_group_id: StableId
    derivation_kind: DerivationKind
    derivation_level: int | None = Field(default=None, ge=0)
    metadata_files: list[StableId] = Field(min_length=1)
    metadata_object_ids: list[str] = Field(min_length=1)
    data_files: list[StableId] = Field(min_length=1)
    data_object_ids: list[str] = Field(min_length=1)
    exact_duplicate_folder_paths: list[StableId]
    answer_key_path: StableId | None = None
    answer_key_dataset_present: bool
    answer_key_summary_hash: Sha256 | None = None
    gold_hypothesis_text_persisted: Literal[False] = False
    database_license_evidence_hash: Sha256
    individual_contents_license_verified: Literal[False] = False
    folder_hash: Sha256

    @field_validator(
        "metadata_files",
        "metadata_object_ids",
        "data_files",
        "data_object_ids",
        "exact_duplicate_folder_paths",
    )
    @classmethod
    def _normalize_lists(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def _validate_folder(self) -> DiscoveryBenchFolderAudit:
        if len(self.metadata_files) != len(self.metadata_object_ids):
            raise ValueError("metadata path/object counts differ")
        if len(self.data_files) != len(self.data_object_ids):
            raise ValueError("data path/object counts differ")
        if any(not GIT_OBJECT_RE.fullmatch(item) for item in self.metadata_object_ids):
            raise ValueError("invalid metadata object ID")
        if any(not GIT_OBJECT_RE.fullmatch(item) for item in self.data_object_ids):
            raise ValueError("invalid data object ID")
        expected_answer = self.split is DiscoveryBenchSplit.TEST
        if expected_answer != (self.answer_key_path is not None):
            raise ValueError("answer-key path must exist exactly for test folders")
        if self.answer_key_dataset_present and self.answer_key_summary_hash is None:
            raise ValueError("answer-key presence requires a summary hash")
        if self.folder_hash != self.calculated_hash():
            raise PortfolioIntegrityError("folder audit_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DiscoveryBenchFolderAudit:
        payload = dict(values)
        payload["schema_version"] = "discoverybench-folder-audit-v1"
        for field in (
            "metadata_files",
            "metadata_object_ids",
            "data_files",
            "data_object_ids",
            "exact_duplicate_folder_paths",
        ):
            payload[field] = sorted(payload[field])
        payload["gold_hypothesis_text_persisted"] = False
        payload["individual_contents_license_verified"] = False
        payload["folder_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"folder_hash"})
        )


class DiscoveryBenchSnapshot(KernelContract):
    """Frozen identity of the official dataset repository and complete tree."""

    schema_version: Literal["discoverybench-snapshot-v1"] = (
        "discoverybench-snapshot-v1"
    )
    dataset_id: Literal["allenai/discoverybench"] = DISCOVERYBENCH_DATASET_ID
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    last_modified: datetime
    gated: Literal[False] = False
    private: Literal[False] = False
    card_license: Literal["odc-by"] = "odc-by"
    tree_url: NonEmptyText
    tree_entry_count: int = Field(ge=1)
    directory_count: int = Field(ge=1)
    file_count: int = Field(ge=1)
    tree_projection_sha256: Sha256
    provisional_folder_count: int = Field(ge=1)
    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _validate_snapshot(self) -> DiscoveryBenchSnapshot:
        if self.tree_entry_count != self.directory_count + self.file_count:
            raise ValueError("tree entry count mismatch")
        if self.snapshot_hash != self.calculated_hash():
            raise PortfolioIntegrityError("dataset snapshot_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DiscoveryBenchSnapshot:
        payload = dict(values)
        last_modified = payload.get("last_modified")
        if isinstance(last_modified, str):
            payload["last_modified"] = datetime.fromisoformat(
                last_modified.replace("Z", "+00:00")
            )
        payload.update(
            {
                "schema_version": "discoverybench-snapshot-v1",
                "dataset_id": DISCOVERYBENCH_DATASET_ID,
                "gated": False,
                "private": False,
                "card_license": "odc-by",
            }
        )
        payload["snapshot_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"snapshot_hash"})
        )


class InventoryProjection(KernelContract):
    """Result-blind independent-unit projection shared with the frozen runner."""

    schema_version: Literal["discoverybench-inventory-projection-v1"] = (
        "discoverybench-inventory-projection-v1"
    )
    provisional_folder_count: int = Field(ge=1)
    train_folder_count: int = Field(ge=0)
    test_folder_count: int = Field(ge=0)
    real_folder_count: int = Field(ge=0)
    synthetic_folder_count: int = Field(ge=0)
    conservative_source_group_count: int = Field(ge=0)
    conservative_train_group_count: int = Field(ge=0)
    conservative_test_group_count: int = Field(ge=0)
    train_only_group_count: int = Field(ge=0)
    test_only_group_count: int = Field(ge=0)
    cross_split_group_count: int = Field(ge=0)
    maximum_reserve_after_development: int = Field(ge=0)
    optimistic_development_upper_bound: int = Field(ge=0)
    optimistic_reserve_upper_bound: int = Field(ge=0)
    required_development_groups: Literal[30] = REQUIRED_DEVELOPMENT_GROUPS
    required_reserve_groups: Literal[84] = REQUIRED_RESERVE_GROUPS
    test_answer_key_lineage_complete: bool
    missing_test_answer_key_folders: list[StableId]
    source_group_ids: list[StableId]
    blockers: list[StableId]
    projection_sha256: Sha256

    @field_validator(
        "missing_test_answer_key_folders",
        "source_group_ids",
        "blockers",
    )
    @classmethod
    def _normalize_projection_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("projection list contains duplicates")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_projection(self) -> InventoryProjection:
        if self.provisional_folder_count != (
            self.train_folder_count + self.test_folder_count
        ):
            raise ValueError("folder split count mismatch")
        if self.provisional_folder_count != (
            self.real_folder_count + self.synthetic_folder_count
        ):
            raise ValueError("folder kind count mismatch")
        if self.conservative_source_group_count != len(self.source_group_ids):
            raise ValueError("source group count mismatch")
        if self.conservative_train_group_count != (
            self.train_only_group_count + self.cross_split_group_count
        ):
            raise ValueError("train group count mismatch")
        if self.conservative_test_group_count != (
            self.test_only_group_count + self.cross_split_group_count
        ):
            raise ValueError("test group count mismatch")
        if self.maximum_reserve_after_development != (
            self.test_only_group_count + self.cross_split_group_count
        ):
            raise ValueError("maximum reserve count mismatch")
        if self.test_answer_key_lineage_complete == bool(
            self.missing_test_answer_key_folders
        ):
            raise ValueError("answer-key completeness contradicts missing folders")
        if self.projection_sha256 != self.calculated_hash():
            raise PortfolioIntegrityError("inventory projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> InventoryProjection:
        payload = dict(values)
        payload["schema_version"] = "discoverybench-inventory-projection-v1"
        payload["required_development_groups"] = REQUIRED_DEVELOPMENT_GROUPS
        payload["required_reserve_groups"] = REQUIRED_RESERVE_GROUPS
        for field in (
            "missing_test_answer_key_folders",
            "source_group_ids",
            "blockers",
        ):
            payload[field] = sorted(payload[field])
        payload["projection_sha256"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"projection_sha256"})
        )


class InventoryReplayObservation(KernelContract):
    """One independent interpreter execution of the frozen inventory runner."""

    schema_version: Literal["inventory-replay-observation-v1"] = (
        "inventory-replay-observation-v1"
    )
    role_id: StableId
    interpreter_environment_hash: Sha256
    command_hash: Sha256
    input_sha256: Sha256
    runner_sha256: Sha256
    exit_code: Literal[0] = 0
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    projection_sha256: Sha256
    observed_at: datetime
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> InventoryReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise PortfolioIntegrityError("inventory replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> InventoryReplayObservation:
        payload = dict(values)
        payload["schema_version"] = "inventory-replay-observation-v1"
        payload["exit_code"] = 0
        payload["observation_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )


class InventoryReplayCertificate(KernelContract):
    """Exact cross-interpreter reconstruction of the result-blind projection."""

    schema_version: Literal["inventory-replay-certificate-v1"] = (
        "inventory-replay-certificate-v1"
    )
    runner_sha256: Sha256
    input_sha256: Sha256
    interpreter_runtimes: list[InterpreterRuntime] = Field(min_length=2)
    observations: list[InventoryReplayObservation] = Field(min_length=2)
    expected_projection_sha256: Sha256
    exact_cross_interpreter_projection: Literal[True] = True
    retry_count: Literal[0] = 0
    development_outcomes_accessed: Literal[False] = False
    certificate_hash: Sha256

    @model_validator(mode="after")
    def _validate_certificate(self) -> InventoryReplayCertificate:
        roles = [item.role_id for item in self.interpreter_runtimes]
        if len(roles) != len(set(roles)):
            raise ValueError("interpreter roles must be unique")
        if len({item.executable_locator_hash for item in self.interpreter_runtimes}) < 2:
            raise ValueError("two distinct interpreter installations are required")
        if sorted(item.role_id for item in self.observations) != sorted(roles):
            raise ValueError("replay observations must cover every interpreter")
        if any(item.runner_sha256 != self.runner_sha256 for item in self.observations):
            raise ValueError("runner hash drift in replay")
        if any(item.input_sha256 != self.input_sha256 for item in self.observations):
            raise ValueError("input hash drift in replay")
        if {
            item.projection_sha256 for item in self.observations
        } != {self.expected_projection_sha256}:
            raise ValueError("cross-interpreter inventory projection mismatch")
        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("inventory replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> InventoryReplayCertificate:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "inventory-replay-certificate-v1",
                "exact_cross_interpreter_projection": True,
                "retry_count": 0,
                "development_outcomes_accessed": False,
            }
        )
        payload["interpreter_runtimes"] = sorted(
            payload["interpreter_runtimes"], key=lambda item: item.role_id
        )
        payload["observations"] = sorted(
            payload["observations"], key=lambda item: item.role_id
        )
        payload["certificate_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )


class SocraticInventoryDecision(KernelContract):
    """Non-compensating admission or stop decision."""

    schema_version: Literal["socratic-inventory-decision-v1"] = (
        "socratic-inventory-decision-v1"
    )
    status: SocraticInventoryStatus
    blockers: list[StableId]
    independent_unit_gate_passed: bool
    test_answer_key_lineage_gate_passed: bool
    database_license_gate_passed: bool
    public_content_release_gate_passed: Literal[False] = False
    evaluator_construction_authorized: bool
    fault_generator_implemented: Literal[False] = False
    objective_evaluator_implemented: Literal[False] = False
    baseline_execution_authorized: bool
    provider_configuration_collected: Literal[False] = False
    development_scientific_outcomes_accessed: Literal[False] = False
    research_question_certificate_issued: Literal[False] = False
    confirmatory_panel_created_or_read: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_route: Literal["return-to-objective-data-opportunity-tournament"] = (
        "return-to-objective-data-opportunity-tournament"
    )
    decision_hash: Sha256

    @field_validator("blockers")
    @classmethod
    def _normalize_blockers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("decision blockers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_decision(self) -> SocraticInventoryDecision:
        admitted = (
            self.independent_unit_gate_passed
            and self.test_answer_key_lineage_gate_passed
            and self.database_license_gate_passed
        )
        expected_status = (
            SocraticInventoryStatus.READY_FOR_EVALUATOR_CONSTRUCTION
            if admitted
            else SocraticInventoryStatus.STOPPED_AT_INVENTORY
        )
        if self.status is not expected_status:
            raise ValueError("decision status contradicts non-compensating gates")
        if self.evaluator_construction_authorized != admitted:
            raise ValueError("evaluator authorization contradicts admission")
        if self.baseline_execution_authorized:
            raise ValueError("baseline execution is never authorized by inventory alone")
        if not admitted and not self.blockers:
            raise ValueError("a stopped inventory requires blockers")
        if admitted and self.blockers:
            raise ValueError("an admitted inventory cannot retain blockers")
        if self.decision_hash != self.calculated_hash():
            raise PortfolioIntegrityError("inventory decision hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        projection: InventoryProjection,
        database_license_gate_passed: bool,
    ) -> SocraticInventoryDecision:
        independent_gate = (
            projection.conservative_source_group_count >= REQUIRED_TOTAL_GROUPS
            and projection.maximum_reserve_after_development
            >= REQUIRED_RESERVE_GROUPS
            and projection.optimistic_reserve_upper_bound
            >= REQUIRED_RESERVE_GROUPS
        )
        answer_gate = projection.test_answer_key_lineage_complete
        admitted = independent_gate and answer_gate and database_license_gate_passed
        blockers = list(projection.blockers)
        if not database_license_gate_passed:
            blockers.append("database-license-unverified")
        payload = {
            "schema_version": "socratic-inventory-decision-v1",
            "status": (
                SocraticInventoryStatus.READY_FOR_EVALUATOR_CONSTRUCTION
                if admitted
                else SocraticInventoryStatus.STOPPED_AT_INVENTORY
            ),
            "blockers": sorted(set(blockers)),
            "independent_unit_gate_passed": independent_gate,
            "test_answer_key_lineage_gate_passed": answer_gate,
            "database_license_gate_passed": database_license_gate_passed,
            "public_content_release_gate_passed": False,
            "evaluator_construction_authorized": admitted,
            "fault_generator_implemented": False,
            "objective_evaluator_implemented": False,
            "baseline_execution_authorized": False,
            "provider_configuration_collected": False,
            "development_scientific_outcomes_accessed": False,
            "research_question_certificate_issued": False,
            "confirmatory_panel_created_or_read": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "next_route": "return-to-objective-data-opportunity-tournament",
        }
        payload["decision_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"decision_hash"})
        )


class SocraticDevelopmentInventoryReport(KernelContract):
    """Complete Task 263.6.5 stop-first research object."""

    schema_version: Literal["socratic-development-inventory-report-v1"] = (
        "socratic-development-inventory-report-v1"
    )
    study_id: StableId
    created_at: datetime
    literature_cutoff: date
    research_questions: list[NonEmptyText] = Field(min_length=3, max_length=3)
    sources: list[ResearchSource] = Field(min_length=6)
    nearest_work: list[NearestWorkDelta] = Field(min_length=6)
    source_probes: list[LiveResourceProbe] = Field(min_length=6)
    snapshot: DiscoveryBenchSnapshot
    answer_keys: list[AnswerKeySummary] = Field(min_length=2, max_length=2)
    database_license: LicenseScopeEvidence
    harness_license: LicenseScopeEvidence
    folders: list[DiscoveryBenchFolderAudit] = Field(min_length=1)
    projection: InventoryProjection
    replay_certificate: InventoryReplayCertificate
    decision: SocraticInventoryDecision
    result_blind_inventory_only: Literal[True] = True
    consumed_confirmation_accessed: Literal[False] = False
    report_hash: Sha256

    @field_validator("research_questions")
    @classmethod
    def _require_unique_questions(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("research questions must be unique")
        return value

    @field_validator("sources", "nearest_work", "source_probes")
    @classmethod
    def _sort_source_material(cls, value: list[Any]) -> list[Any]:
        key = "source_id" if hasattr(value[0], "source_id") else "resource_id"
        return sorted(value, key=lambda item: getattr(item, key))

    @field_validator("folders")
    @classmethod
    def _sort_folders(
        cls, value: list[DiscoveryBenchFolderAudit]
    ) -> list[DiscoveryBenchFolderAudit]:
        return sorted(value, key=lambda item: item.folder_path)

    @model_validator(mode="after")
    def _validate_report(self) -> SocraticDevelopmentInventoryReport:
        source_ids = {item.source_id for item in self.sources}
        if {item.source_id for item in self.nearest_work} != source_ids:
            raise ValueError("nearest-work audit must cover every source")
        if {item.resource_id for item in self.source_probes} != source_ids:
            raise ValueError("live probes must cover every source")
        if not all(item.reachable for item in self.source_probes):
            raise ValueError("every cited source must be reachable")
        if len(self.folders) != self.snapshot.provisional_folder_count:
            raise ValueError("folder inventory does not match snapshot")
        if len(self.folders) != self.projection.provisional_folder_count:
            raise ValueError("folder inventory does not match projection")
        if len({item.folder_path for item in self.folders}) != len(self.folders):
            raise ValueError("folder paths must be unique")
        if {
            item.source_group_id for item in self.folders
        } != set(self.projection.source_group_ids):
            raise ValueError("folder groups do not match projection")
        if self.replay_certificate.expected_projection_sha256 != (
            self.projection.projection_sha256
        ):
            raise ValueError("replay certificate does not bind the projection")
        if self.database_license.scope is not LicenseScope.DATABASE_RIGHTS:
            raise ValueError("DiscoveryBench evidence must be database-scoped")
        if self.harness_license.scope is not LicenseScope.SOFTWARE:
            raise ValueError("AstaBench evidence must be software-scoped")
        if self.decision.status is not SocraticInventoryStatus.STOPPED_AT_INVENTORY:
            raise ValueError(
                "Task 263.6.5 report cannot continue past the observed inventory"
            )
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("inventory report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SocraticDevelopmentInventoryReport:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "socratic-development-inventory-report-v1",
                "result_blind_inventory_only": True,
                "consumed_confirmation_accessed": False,
            }
        )
        payload["sources"] = sorted(
            payload["sources"], key=lambda item: item.source_id
        )
        payload["nearest_work"] = sorted(
            payload["nearest_work"], key=lambda item: item.source_id
        )
        payload["source_probes"] = sorted(
            payload["source_probes"], key=lambda item: item.resource_id
        )
        payload["folders"] = sorted(
            payload["folders"], key=lambda item: item.folder_path
        )
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class SocraticInventoryArtifactManifest(KernelContract):
    """Hashes for the reader view, schemas, and canonical report."""

    schema_version: Literal["socratic-inventory-artifact-manifest-v1"] = (
        "socratic-inventory-artifact-manifest-v1"
    )
    report_filename: Literal["socratic-development-inventory.json"] = (
        INVENTORY_REPORT_FILENAME
    )
    report_sha256: Sha256
    markdown_filename: Literal["socratic-development-inventory.md"] = (
        INVENTORY_MARKDOWN_FILENAME
    )
    markdown_sha256: Sha256
    schema_filename: Literal["socratic-development-inventory-schemas.json"] = (
        INVENTORY_SCHEMA_FILENAME
    )
    schema_sha256: Sha256
    replay_input_filename: Literal["inventory-replay-input.json"] = (
        INVENTORY_REPLAY_INPUT_FILENAME
    )
    replay_input_sha256: Sha256
    inventory_runner_sha256: Sha256
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> SocraticInventoryArtifactManifest:
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("inventory manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SocraticInventoryArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "socratic-inventory-artifact-manifest-v1",
                "report_filename": INVENTORY_REPORT_FILENAME,
                "markdown_filename": INVENTORY_MARKDOWN_FILENAME,
                "schema_filename": INVENTORY_SCHEMA_FILENAME,
                "replay_input_filename": INVENTORY_REPLAY_INPUT_FILENAME,
            }
        )
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


class SocraticVerticalStopped(RuntimeError):
    """Raised when downstream work is attempted after the inventory stop."""


def require_socratic_evaluator_admission(
    report: SocraticDevelopmentInventoryReport,
) -> None:
    """Fail closed before fault generation, provider config, or baseline calls."""

    report.model_validate(report.model_dump(mode="json"))
    if not report.decision.evaluator_construction_authorized:
        raise SocraticVerticalStopped(
            "Socratic evaluator construction is blocked by the frozen "
            f"inventory: {', '.join(report.decision.blockers)}"
        )


def _real_group(folder: str) -> tuple[str, DerivationKind]:
    if folder.startswith("nls_"):
        kind = (
            DerivationKind.REAL_RAW
            if folder.endswith("_raw")
            else DerivationKind.REAL_PROCESSED_OR_SUBSET
        )
        return "real:nls", kind
    if folder in {"meta_regression", "meta_regression_raw"}:
        kind = (
            DerivationKind.REAL_RAW
            if folder.endswith("_raw")
            else DerivationKind.REAL_PROCESSED_OR_SUBSET
        )
        return "real:meta-regression", kind
    if folder in {
        "worldbank_education_gdp",
        "worldbank_education_gdp_indicators",
    }:
        return (
            "real:worldbank-education-gdp",
            DerivationKind.REAL_PROCESSED_OR_SUBSET,
        )
    return f"real:{folder.replace('_', '-')}", DerivationKind.REAL_SOURCE


def _source_group(
    kind: DiscoveryBenchSourceKind,
    folder: str,
) -> tuple[str, DerivationKind, int | None]:
    if kind is DiscoveryBenchSourceKind.REAL:
        group, derivation = _real_group(folder)
        return group, derivation, None
    match = SYNTHETIC_FAMILY_RE.fullmatch(folder)
    if match is None:
        raise ValueError(f"invalid synthetic folder name: {folder}")
    return (
        f"synth:{match.group('domain')}:"
        f"semantic-tree-{int(match.group('tree_index'))}",
        DerivationKind.SYNTHETIC_SEMANTIC_TREE_DERIVATIVE,
        int(match.group("level_index")),
    )


def _normalized_tree_entries(
    tree_entries: Sequence[Mapping[str, Any] | TreeEntry],
) -> list[TreeEntry]:
    normalized = [
        item if isinstance(item, TreeEntry) else TreeEntry.from_remote(item)
        for item in tree_entries
    ]
    normalized.sort(key=lambda item: (item.path, item.entry_type))
    if len({(item.path, item.entry_type) for item in normalized}) != len(normalized):
        raise ValueError("tree contains duplicate path/type entries")
    return normalized


def _answer_key_by_kind(
    answer_keys: Sequence[AnswerKeySummary],
) -> dict[DiscoveryBenchSourceKind, AnswerKeySummary]:
    material = {item.source_kind: item for item in answer_keys}
    if set(material) != {
        DiscoveryBenchSourceKind.REAL,
        DiscoveryBenchSourceKind.SYNTHETIC,
    }:
        raise ValueError("real and synthetic answer-key summaries are required")
    return material


def build_inventory_replay_payload(
    *,
    tree_entries: Sequence[Mapping[str, Any] | TreeEntry],
    answer_keys: Sequence[AnswerKeySummary],
) -> dict[str, Any]:
    """Build the only input visible to the frozen standalone inventory runner."""

    normalized = _normalized_tree_entries(tree_entries)
    key_by_kind = _answer_key_by_kind(answer_keys)
    return {
        "schema_version": "discoverybench-inventory-replay-input-v1",
        "tree_entries": [
            {
                "type": item.entry_type,
                "path": item.path,
                "oid": item.oid,
                "size": item.size,
            }
            for item in normalized
        ],
        "answer_key_dataset_names": {
            "real": key_by_kind[
                DiscoveryBenchSourceKind.REAL
            ].dataset_names,
            "synth": key_by_kind[
                DiscoveryBenchSourceKind.SYNTHETIC
            ].dataset_names,
        },
        "required_development_groups": REQUIRED_DEVELOPMENT_GROUPS,
        "required_reserve_groups": REQUIRED_RESERVE_GROUPS,
        "gold_hypothesis_text_included": False,
        "scientific_development_outcomes_included": False,
    }


def _folder_audits(
    *,
    tree_entries: Sequence[TreeEntry],
    answer_keys: Sequence[AnswerKeySummary],
    database_license: LicenseScopeEvidence,
) -> list[DiscoveryBenchFolderAudit]:
    directories = {
        item.path
        for item in tree_entries
        if item.entry_type == "directory" and SOURCE_FOLDER_RE.fullmatch(item.path)
    }
    key_by_kind = _answer_key_by_kind(answer_keys)
    preliminary: list[dict[str, Any]] = []
    for folder_path in sorted(directories):
        match = SOURCE_FOLDER_RE.fullmatch(folder_path)
        if match is None:
            raise AssertionError("source folder regex drift")
        kind = DiscoveryBenchSourceKind(match.group("kind"))
        split = DiscoveryBenchSplit(match.group("split"))
        folder_name = match.group("folder")
        source_group_id, derivation_kind, derivation_level = _source_group(
            kind, folder_name
        )
        files = [
            item
            for item in tree_entries
            if item.entry_type == "file"
            and item.path.startswith(f"{folder_path}/")
        ]
        metadata = sorted(
            [item for item in files if METADATA_FILE_RE.search(item.path)],
            key=lambda item: item.path,
        )
        data = sorted(
            [item for item in files if not METADATA_FILE_RE.search(item.path)],
            key=lambda item: item.path,
        )
        if not metadata or not data:
            raise ValueError(f"folder lacks metadata or data files: {folder_path}")
        answer = key_by_kind[kind] if split is DiscoveryBenchSplit.TEST else None
        preliminary.append(
            {
                "folder_path": folder_path,
                "folder_name": folder_name,
                "source_kind": kind,
                "split": split,
                "source_group_id": source_group_id,
                "derivation_kind": derivation_kind,
                "derivation_level": derivation_level,
                "metadata_files": [item.path for item in metadata],
                "metadata_object_ids": [item.oid for item in metadata],
                "data_files": [item.path for item in data],
                "data_object_ids": [item.oid for item in data],
                "answer_key_path": None if answer is None else answer.path,
                "answer_key_dataset_present": (
                    False
                    if answer is None
                    else folder_name in set(answer.dataset_names)
                ),
                "answer_key_summary_hash": (
                    None if answer is None else answer.summary_hash
                ),
                "database_license_evidence_hash": database_license.evidence_hash,
            }
        )

    data_signature_to_paths: dict[tuple[str, ...], list[str]] = {}
    for item in preliminary:
        signature = tuple(sorted(item["data_object_ids"]))
        data_signature_to_paths.setdefault(signature, []).append(item["folder_path"])
    audits = []
    for item in preliminary:
        signature = tuple(sorted(item["data_object_ids"]))
        duplicates = sorted(
            path
            for path in data_signature_to_paths[signature]
            if path != item["folder_path"]
        )
        audits.append(
            DiscoveryBenchFolderAudit.create(
                **item,
                exact_duplicate_folder_paths=duplicates,
            )
        )
    return audits


def _projection_from_folders(
    folders: Sequence[DiscoveryBenchFolderAudit],
) -> InventoryProjection:
    train = [item for item in folders if item.split is DiscoveryBenchSplit.TRAIN]
    test = [item for item in folders if item.split is DiscoveryBenchSplit.TEST]
    train_groups = {item.source_group_id for item in train}
    test_groups = {item.source_group_id for item in test}
    all_groups = train_groups | test_groups
    train_only = train_groups - test_groups
    test_only = test_groups - train_groups
    cross_split = train_groups & test_groups
    optimistic_development = {
        (
            item.source_group_id
            if item.source_kind is DiscoveryBenchSourceKind.REAL
            else f"synth-folder:{item.folder_name}"
        )
        for item in train
    }
    optimistic_reserve = {
        (
            item.source_group_id
            if item.source_kind is DiscoveryBenchSourceKind.REAL
            else f"synth-folder:{item.folder_name}"
        )
        for item in test
    }
    missing_test = sorted(
        item.folder_path for item in test if not item.answer_key_dataset_present
    )
    maximum_reserve = len(test_only) + len(cross_split)
    blockers: list[str] = []
    if len(all_groups) < REQUIRED_TOTAL_GROUPS:
        blockers.append("independent-source-group-total-below-114")
    if maximum_reserve < REQUIRED_RESERVE_GROUPS:
        blockers.append("conservative-reserve-groups-below-84")
    if len(optimistic_reserve) < REQUIRED_RESERVE_GROUPS:
        blockers.append("optimistic-reserve-upper-bound-below-84")
    if missing_test:
        blockers.append("test-answer-key-lineage-incomplete")
    return InventoryProjection.create(
        provisional_folder_count=len(folders),
        train_folder_count=len(train),
        test_folder_count=len(test),
        real_folder_count=sum(
            item.source_kind is DiscoveryBenchSourceKind.REAL for item in folders
        ),
        synthetic_folder_count=sum(
            item.source_kind is DiscoveryBenchSourceKind.SYNTHETIC for item in folders
        ),
        conservative_source_group_count=len(all_groups),
        conservative_train_group_count=len(train_groups),
        conservative_test_group_count=len(test_groups),
        train_only_group_count=len(train_only),
        test_only_group_count=len(test_only),
        cross_split_group_count=len(cross_split),
        maximum_reserve_after_development=maximum_reserve,
        optimistic_development_upper_bound=len(optimistic_development),
        optimistic_reserve_upper_bound=len(optimistic_reserve),
        test_answer_key_lineage_complete=not missing_test,
        missing_test_answer_key_folders=missing_test,
        source_group_ids=sorted(all_groups),
        blockers=blockers,
    )


def build_inventory_projection(
    *,
    tree_entries: Sequence[Mapping[str, Any] | TreeEntry],
    answer_keys: Sequence[AnswerKeySummary],
    database_license: LicenseScopeEvidence,
) -> tuple[list[DiscoveryBenchFolderAudit], InventoryProjection]:
    """Audit every folder and return the local result-blind projection."""

    normalized = _normalized_tree_entries(tree_entries)
    folders = _folder_audits(
        tree_entries=normalized,
        answer_keys=answer_keys,
        database_license=database_license,
    )
    if len(folders) != REQUIRED_PROVISIONAL_FOLDER_COUNT:
        raise ValueError(
            "DiscoveryBench provisional folder count changed; re-audit before use"
        )
    return folders, _projection_from_folders(folders)


def build_socratic_development_inventory(
    *,
    study_id: str,
    created_at: datetime,
    literature_cutoff: date,
    research_questions: list[str],
    sources: list[ResearchSource],
    nearest_work: list[NearestWorkDelta],
    source_probes: list[LiveResourceProbe],
    dataset_metadata: Mapping[str, Any],
    tree_entries: Sequence[Mapping[str, Any] | TreeEntry],
    answer_keys: list[AnswerKeySummary],
    database_license: LicenseScopeEvidence,
    harness_license: LicenseScopeEvidence,
    replay_certificate: InventoryReplayCertificate,
) -> SocraticDevelopmentInventoryReport:
    """Build the formal stop-first inventory without touching task outcomes."""

    normalized = _normalized_tree_entries(tree_entries)
    folders, projection = build_inventory_projection(
        tree_entries=normalized,
        answer_keys=answer_keys,
        database_license=database_license,
    )
    tree_projection = [
        {
            "type": item.entry_type,
            "path": item.path,
            "oid": item.oid,
            "size": item.size,
        }
        for item in normalized
    ]
    revision = str(dataset_metadata.get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("dataset revision must be a 40-character Git SHA")
    card_license = dataset_metadata.get("cardData", {}).get("license")
    if card_license != "odc-by":
        raise ValueError("DiscoveryBench card license changed")
    if bool(dataset_metadata.get("gated")) or bool(dataset_metadata.get("private")):
        raise ValueError("DiscoveryBench is no longer open and ungated")
    snapshot = DiscoveryBenchSnapshot.create(
        revision=revision,
        last_modified=dataset_metadata["lastModified"],
        tree_url=DISCOVERYBENCH_TREE_URL.format(revision=revision),
        tree_entry_count=len(normalized),
        directory_count=sum(
            item.entry_type == "directory" for item in normalized
        ),
        file_count=sum(item.entry_type == "file" for item in normalized),
        tree_projection_sha256=canonical_sha256(tree_projection),
        provisional_folder_count=len(folders),
    )
    if replay_certificate.expected_projection_sha256 != projection.projection_sha256:
        raise ValueError("frozen runner projection differs from local projection")
    decision = SocraticInventoryDecision.create(
        projection=projection,
        database_license_gate_passed=(
            database_license.database_use_verified
            and database_license.observed_license_id == "ODC-By-1.0"
        ),
    )
    return SocraticDevelopmentInventoryReport.create(
        study_id=study_id,
        created_at=created_at,
        literature_cutoff=literature_cutoff,
        research_questions=research_questions,
        sources=sources,
        nearest_work=nearest_work,
        source_probes=source_probes,
        snapshot=snapshot,
        answer_keys=answer_keys,
        database_license=database_license,
        harness_license=harness_license,
        folders=folders,
        projection=projection,
        replay_certificate=replay_certificate,
        decision=decision,
    )


def run_inventory_replay(
    *,
    replay_payload: Mapping[str, Any],
    input_path: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    expected_projection: InventoryProjection,
    observed_at: datetime,
) -> InventoryReplayCertificate:
    """Execute the frozen result-blind projection in two clean interpreters."""

    if len(interpreters) < 2:
        raise ValueError("two independent interpreter installations are required")
    runner_sha256 = _file_sha256(runner_path)
    input_text = _canonical_json_text(replay_payload)
    _write_text_atomic(input_path, input_text)
    input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    runtimes = [
        probe_interpreter_runtime(role_id=role_id, executable=path)
        for role_id, path in sorted(interpreters.items())
    ]
    observations: list[InventoryReplayObservation] = []
    for runtime in runtimes:
        executable = Path(interpreters[runtime.role_id])
        command = [str(executable), str(runner_path), str(input_path)]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"inventory replay failed for {runtime.role_id}: "
                f"{completed.stderr.decode('utf-8', errors='replace')[:1000]}"
            )
        try:
            output = json.loads(completed.stdout.decode("utf-8"))
            observed_projection = InventoryProjection.model_validate(output)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"inventory replay output invalid for {runtime.role_id}"
            ) from exc
        if observed_projection.projection_sha256 != (
            expected_projection.projection_sha256
        ):
            raise RuntimeError(
                f"inventory replay projection mismatch for {runtime.role_id}"
            )
        observations.append(
            InventoryReplayObservation.create(
                role_id=runtime.role_id,
                interpreter_environment_hash=runtime.environment_hash,
                command_hash=canonical_sha256(command),
                input_sha256=input_sha256,
                runner_sha256=runner_sha256,
                stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
                projection_sha256=observed_projection.projection_sha256,
                observed_at=observed_at,
            )
        )
    return InventoryReplayCertificate.create(
        runner_sha256=runner_sha256,
        input_sha256=input_sha256,
        interpreter_runtimes=runtimes,
        observations=observations,
        expected_projection_sha256=expected_projection.projection_sha256,
    )


def _get_json(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: float,
) -> Any:
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def _get_bytes(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: float,
) -> bytes:
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.content


def fetch_discoverybench_inventory_material(
    *,
    session: requests.Session,
    timeout_seconds: float = 60,
) -> tuple[
    Mapping[str, Any],
    list[Mapping[str, Any]],
    list[AnswerKeySummary],
    LicenseScopeEvidence,
    LicenseScopeEvidence,
]:
    """Fetch only official metadata, tree, answer-key keys, and license evidence."""

    metadata = _get_json(
        session,
        DISCOVERYBENCH_METADATA_URL,
        timeout_seconds=timeout_seconds,
    )
    revision = str(metadata.get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("official dataset metadata lacks a valid revision")
    tree_url = DISCOVERYBENCH_TREE_URL.format(revision=revision)
    tree = _get_json(session, tree_url, timeout_seconds=timeout_seconds)
    if not isinstance(tree, list):
        raise ValueError("official dataset tree is not a list")
    normalized = _normalized_tree_entries(tree)
    by_path = {item.path: item for item in normalized}

    answer_specs = {
        DiscoveryBenchSourceKind.REAL: "answer_key/answer_key_real.csv",
        DiscoveryBenchSourceKind.SYNTHETIC: "answer_key/answer_key_synth.csv",
    }
    answer_keys = []
    for kind, path in answer_specs.items():
        entry = by_path.get(path)
        if entry is None or entry.entry_type != "file":
            raise ValueError(f"missing official answer-key artifact: {path}")
        raw = _get_bytes(
            session,
            DISCOVERYBENCH_RESOLVE_URL.format(
                revision=revision,
                path=quote(path, safe="/"),
            ),
            timeout_seconds=timeout_seconds,
        )
        answer_keys.append(
            AnswerKeySummary.create(
                source_kind=kind,
                path=path,
                git_object_id=entry.oid,
                raw_bytes=raw,
            )
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutoResearch-task-263.6.5",
    }
    discovery_license_payload = _get_json(
        session,
        DISCOVERYBENCH_LICENSE_API,
        timeout_seconds=timeout_seconds,
    )
    repository_payload = _get_json(
        session,
        DISCOVERYBENCH_REPOSITORY_API,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(discovery_license_payload, Mapping):
        raise ValueError("DiscoveryBench license response is invalid")
    license_text = base64.b64decode(
        str(discovery_license_payload["content"]).replace("\n", "")
    )
    if b"ODC Attribution License" not in license_text:
        raise ValueError("DiscoveryBench license text is no longer ODC-By")
    repo_spdx = (
        repository_payload.get("license", {}).get("spdx_id")
        if isinstance(repository_payload, Mapping)
        else None
    )
    database_license = LicenseScopeEvidence.create(
        resource_id="discoverybench-database-license",
        evidence_url=DISCOVERYBENCH_LICENSE_API,
        observed_license_id="ODC-By-1.0",
        license_file_object_id=discovery_license_payload["sha"],
        license_text_sha256=hashlib.sha256(license_text).hexdigest(),
        scope=LicenseScope.DATABASE_RIGHTS,
        database_use_verified=True,
        software_reuse_verified=False,
        individual_contents_redistribution_verified=False,
        attribution_required=True,
        interpretation=(
            "The observed ODC-By text authorizes database use with attribution, "
            "but expressly excludes computer programs and does not independently "
            "clear rights in individual contents. GitHub reports "
            f"{repo_spdx or 'NOASSERTION'}; no DiscoveryBench code is reused."
        ),
    )

    asta_response = session.get(
        ASTABENCH_LICENSE_API,
        headers=headers,
        timeout=timeout_seconds,
    )
    asta_response.raise_for_status()
    asta_payload = asta_response.json()
    if asta_payload.get("license", {}).get("spdx_id") != "Apache-2.0":
        raise ValueError("AstaBench software license changed")
    asta_text = base64.b64decode(
        str(asta_payload["content"]).replace("\n", "")
    )
    harness_license = LicenseScopeEvidence.create(
        resource_id="astabench-software-license",
        evidence_url=ASTABENCH_LICENSE_API,
        observed_license_id="Apache-2.0",
        license_file_object_id=asta_payload["sha"],
        license_text_sha256=hashlib.sha256(asta_text).hexdigest(),
        scope=LicenseScope.SOFTWARE,
        database_use_verified=False,
        software_reuse_verified=True,
        individual_contents_redistribution_verified=False,
        attribution_required=True,
        interpretation=(
            "The AstaBench repository software is Apache-2.0. This evidence "
            "does not license DiscoveryBench contents or any gated benchmark data."
        ),
    )
    return metadata, tree, answer_keys, database_license, harness_license


def socratic_inventory_json_schemas() -> dict[str, Any]:
    models: tuple[type[BaseModel], ...] = (
        TreeEntry,
        LicenseScopeEvidence,
        AnswerKeySummary,
        DiscoveryBenchFolderAudit,
        DiscoveryBenchSnapshot,
        InventoryProjection,
        InventoryReplayObservation,
        InventoryReplayCertificate,
        SocraticInventoryDecision,
        SocraticDevelopmentInventoryReport,
        SocraticInventoryArtifactManifest,
    )
    return {
        model.__name__: model.model_json_schema()
        for model in sorted(models, key=lambda item: item.__name__)
    }


def render_socratic_inventory_markdown(
    report: SocraticDevelopmentInventoryReport,
) -> str:
    projection = report.projection
    decision = report.decision
    lines = [
        "# Task 263.6.5 Socratic development inventory gate",
        "",
        f"- Status: `{decision.status.value}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Dataset revision: `{report.snapshot.revision}`",
        f"- Exact replay: `{report.replay_certificate.expected_projection_sha256}`",
        "- Scientific outcomes accessed: `false`",
        "- Evaluator/baseline/model calls entered: `false`",
        "- Confirmation panel created or read: `false`",
        "",
        "## Frozen research questions",
        "",
    ]
    lines.extend(
        f"{index}. {question}"
        for index, question in enumerate(report.research_questions, start=1)
    )
    lines.extend(
        [
            "",
            "## Inventory result",
            "",
            "| Quantity | Observed | Required |",
            "|---|---:|---:|",
            (
                "| Provisional folders | "
                f"{projection.provisional_folder_count} | 189 |"
            ),
            (
                "| Conservative independent source groups | "
                f"{projection.conservative_source_group_count} | "
                f"{REQUIRED_TOTAL_GROUPS} |"
            ),
            (
                "| Conservative maximum untouched reserve | "
                f"{projection.maximum_reserve_after_development} | "
                f"{REQUIRED_RESERVE_GROUPS} |"
            ),
            (
                "| Optimistic reserve upper bound "
                "(every synthetic test folder independent) | "
                f"{projection.optimistic_reserve_upper_bound} | "
                f"{REQUIRED_RESERVE_GROUPS} |"
            ),
            (
                "| Optimistic development upper bound | "
                f"{projection.optimistic_development_upper_bound} | "
                f"{REQUIRED_DEVELOPMENT_GROUPS} |"
            ),
            "",
            (
                "The reserve gate fails even under the optimistic bound. "
                "The conservative family audit gives "
                f"{projection.maximum_reserve_after_development} reserve groups; "
                "the optimistic folder-level audit gives "
                f"{projection.optimistic_reserve_upper_bound}. Neither reaches 84."
            ),
            "",
            "## License boundary",
            "",
            (
                "- DiscoveryBench database: "
                f"`{report.database_license.observed_license_id}`; database use "
                "verified, software reuse false, individual-content redistribution "
                "not independently verified."
            ),
            (
                "- AstaBench harness software: "
                f"`{report.harness_license.observed_license_id}`; software reuse "
                "verified, but this does not extend to DiscoveryBench contents."
            ),
            (
                "- Attribution: Contains information from DiscoveryBench, made "
                "available under the ODC Attribution License."
            ),
            "",
            "## Non-compensating blockers",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in decision.blockers)
    lines.extend(
        [
            "",
            "## Enforced stop",
            "",
            "- Fault generator implemented: `false`",
            "- Objective evaluator implemented: `false`",
            "- Provider configuration collected: `false`",
            "- Baseline execution authorized: `false`",
            "- Research Question Certificate issued: `false`",
            "- Public release or submission authorized: `false`",
            "",
            (
                "Next route: `return-to-objective-data-opportunity-tournament`. "
                "A replacement must have at least 30 disjoint development groups, "
                "84 untouched reserve groups, executable objective labels, and "
                "per-resource license evidence before any model-assisted critic "
                "experiment."
            ),
            "",
            "## Folder-level audit",
            "",
            "| Folder | Split | Kind | Source group | Derivation | Data | Metadata | Key |",
            "|---|---|---|---|---|---:|---:|---|",
        ]
    )
    for folder in report.folders:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{folder.folder_path}`",
                    folder.split.value,
                    folder.source_kind.value,
                    f"`{folder.source_group_id}`",
                    folder.derivation_kind.value,
                    str(len(folder.data_files)),
                    str(len(folder.metadata_files)),
                    (
                        "sealed"
                        if folder.answer_key_dataset_present
                        else "not-separate/train"
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Verified nearest work",
            "",
        ]
    )
    for source in report.sources:
        lines.append(f"- [{source.title}]({source.source_url})")
    return "\n".join(lines) + "\n"


def write_socratic_development_inventory(
    report: SocraticDevelopmentInventoryReport,
    output_root: Path,
    *,
    runner_path: Path,
) -> SocraticInventoryArtifactManifest:
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / INVENTORY_REPORT_FILENAME
    markdown_path = output_root / INVENTORY_MARKDOWN_FILENAME
    schema_path = output_root / INVENTORY_SCHEMA_FILENAME
    replay_input_path = output_root / INVENTORY_REPLAY_INPUT_FILENAME
    if not replay_input_path.is_file():
        raise FileNotFoundError(
            "the result-blind replay input must exist before artifact writing"
        )
    replay_input_sha256 = _file_sha256(replay_input_path)
    if replay_input_sha256 != report.replay_certificate.input_sha256:
        raise PortfolioIntegrityError("inventory replay input file hash mismatch")
    report_text = _canonical_json_text(report.model_dump(mode="json"))
    markdown_text = render_socratic_inventory_markdown(report)
    schema_text = _canonical_json_text(socratic_inventory_json_schemas())
    _write_text_atomic(report_path, report_text)
    _write_text_atomic(markdown_path, markdown_text)
    _write_text_atomic(schema_path, schema_text)
    manifest = SocraticInventoryArtifactManifest.create(
        report_sha256=hashlib.sha256(report_text.encode("utf-8")).hexdigest(),
        markdown_sha256=hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        schema_sha256=hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
        replay_input_sha256=replay_input_sha256,
        inventory_runner_sha256=_file_sha256(runner_path),
        dataset_revision=report.snapshot.revision,
    )
    _write_text_atomic(
        output_root / INVENTORY_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")),
    )
    return manifest


def load_socratic_development_inventory(
    output_root: Path,
) -> tuple[SocraticDevelopmentInventoryReport, SocraticInventoryArtifactManifest]:
    report_path = output_root / INVENTORY_REPORT_FILENAME
    markdown_path = output_root / INVENTORY_MARKDOWN_FILENAME
    schema_path = output_root / INVENTORY_SCHEMA_FILENAME
    replay_input_path = output_root / INVENTORY_REPLAY_INPUT_FILENAME
    manifest_path = output_root / INVENTORY_MANIFEST_FILENAME
    manifest = SocraticInventoryArtifactManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if _file_sha256(report_path) != manifest.report_sha256:
        raise PortfolioIntegrityError("inventory report file hash mismatch")
    if _file_sha256(markdown_path) != manifest.markdown_sha256:
        raise PortfolioIntegrityError("inventory Markdown file hash mismatch")
    if _file_sha256(schema_path) != manifest.schema_sha256:
        raise PortfolioIntegrityError("inventory schema file hash mismatch")
    if _file_sha256(replay_input_path) != manifest.replay_input_sha256:
        raise PortfolioIntegrityError("inventory replay input file hash mismatch")
    report = SocraticDevelopmentInventoryReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if report.snapshot.revision != manifest.dataset_revision:
        raise PortfolioIntegrityError("manifest dataset revision mismatch")
    if (
        report.replay_certificate.input_sha256
        != manifest.replay_input_sha256
    ):
        raise PortfolioIntegrityError("report replay input hash mismatch")
    return report, manifest


__all__ = [
    "ASTABENCH_LICENSE_API",
    "AnswerKeySummary",
    "DISCOVERYBENCH_DATASET_ID",
    "DerivationKind",
    "DiscoveryBenchFolderAudit",
    "DiscoveryBenchSnapshot",
    "DiscoveryBenchSourceKind",
    "DiscoveryBenchSplit",
    "INVENTORY_MANIFEST_FILENAME",
    "INVENTORY_MARKDOWN_FILENAME",
    "INVENTORY_REPLAY_INPUT_FILENAME",
    "INVENTORY_REPORT_FILENAME",
    "INVENTORY_RUNNER_SOURCE_PATH",
    "INVENTORY_SCHEMA_FILENAME",
    "InventoryProjection",
    "InventoryReplayCertificate",
    "InventoryReplayObservation",
    "LicenseScope",
    "LicenseScopeEvidence",
    "REQUIRED_DEVELOPMENT_GROUPS",
    "REQUIRED_PROVISIONAL_FOLDER_COUNT",
    "REQUIRED_RESERVE_GROUPS",
    "REQUIRED_TOTAL_GROUPS",
    "SocraticDevelopmentInventoryReport",
    "SocraticInventoryArtifactManifest",
    "SocraticInventoryDecision",
    "SocraticInventoryStatus",
    "SocraticVerticalStopped",
    "TreeEntry",
    "build_inventory_replay_payload",
    "build_inventory_projection",
    "build_socratic_development_inventory",
    "fetch_discoverybench_inventory_material",
    "load_socratic_development_inventory",
    "render_socratic_inventory_markdown",
    "require_socratic_evaluator_admission",
    "run_inventory_replay",
    "socratic_inventory_json_schemas",
    "write_socratic_development_inventory",
]
