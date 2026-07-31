"""Additive independent-task reanalysis for the immutable Task 260 paper.

Task 263.7.1 does not revise the historical manuscript or replace its original
preregistration. It binds the completed Task 263.7.0 audit to the immutable
Task 260 v2 package, inventories every original machine-readable number and
claim, identifies the LaTeX surfaces that use the repeated task-seed estimate,
and emits a separate task-level analysis note.

The note is a post-audit unit correction. It is not fresh confirmation and it
cannot authorize publication, public release, venue selection, or submission.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .systems_paper_currency_audit import (
    BANNED_AI_TONE_TERMS,
    IndependentUnitAudit,
    ParentSystemsPaperEvidence,
    StatisticalReplayCertificate,
    StatisticalReplayProjection,
    SystemsPaperCurrencyAuditManifest,
    SystemsPaperCurrencyAuditReport,
    build_independent_unit_audit,
    load_systems_paper_currency_audit,
    run_statistical_replay,
)

TASK_ID = "263.7.1"
AUDIT_GIT_COMMIT = "75546eba0ae387abe96635fb6559c4b4003dfa1e"
AUDIT_REPORT_HASH = "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
AUDIT_REPORT_FILE_SHA256 = (
    "037a22cd12118e0592952911ecf16ee36d18a60586c1cedb3a96fc1b4aafdab7"
)
AUDIT_MANIFEST_HASH = "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
AUDIT_MANIFEST_FILE_SHA256 = (
    "21db74f0f498d4e227316e7437272e14a240662f083d6d4314b32c38f2dfb905"
)
AUDIT_UNIT_HASH = "b6a6e2cb59be88ebb4dc747a8c6d36d91a2279568a3c2cde711ac12acb751eb3"
AUDIT_UNIT_FILE_SHA256 = (
    "1ec8a66b57c8a9873ce2f357a9378aa3717a0fba1b260c2bea202b0e1b3e16fa"
)
AUDIT_PROJECTION_HASH = "4247521dab59e0a65318f8391367aa11c26323d04335697be3e1f74f322f9cba"
AUDIT_REPAIR_PLAN_HASH = "4ad117a02defc318646456a9a754e91159756b5f148ae01f36f8ed1ddf36b3ec"
AUDIT_SOURCE_REGISTRY_HASH = (
    "50fbd19ad2a03896988ffa2d66d5b6499cf30c9996e9613a26c1cc4e97067427"
)
AUDIT_PARENT_EVIDENCE_HASH = (
    "61de76e8f74c191849f7b9d9ab88d606859004cd80fc73a9dbefe820d7335811"
)

EXPECTED_PAPER_SURFACE_HASHES: dict[str, str] = {
    "evidence/claim-evidence-map.json": (
        "7fc3dfba0d0578814fe438ed24a25f3390a5a2f38d77b9c1bece72e250e91a4b"
    ),
    "frozen-inputs/paper-values.json": (
        "fc53854a595f33359b4be980b15aacb85af8b7fb99e7689a0d95fa11f06c1201"
    ),
    "paper/source/values.tex": (
        "2e212bb77bc7f8968ebccb8c7ad0865678d32b28934f2567f0607c8d90f60038"
    ),
    "paper/source/tables/mode-results.tex": (
        "ac893fc1074f8325842ab8e2fd87c5056df98102a42cb5eba6887b2d57118c45"
    ),
    "paper/source/tables/route-a-results.tex": (
        "e490ded7e1a339724bb96ecf34fbd9dd82c33d6971ddea48c282782b9c2fc8fe"
    ),
    "paper/source/sections/abstract.tex": (
        "e554ee5853e7937a183a5b4dcd99c2873bddb7ba3f84841176b76f9de1fee561"
    ),
    "paper/source/sections/introduction.tex": (
        "dc217332f2154d001e4678d64bf4f8c54e0175133ce35c6b6e8feb0f38636383"
    ),
    "paper/source/sections/experiments.tex": (
        "053ef63b052c3542480df17820ec27ecfddbc6d2159a12ea335c5d387a593443"
    ),
    "paper/source/sections/results.tex": (
        "1e7f0aa5ac74ebb2ba9f60e9d0b974ddcf2778d02557048c9726507b381a775a"
    ),
    "paper/source/sections/discussion.tex": (
        "e62d3dfab00fc6e0f25b933ea96fb36e53a80620e57241e4413e0a2b9ddbfcc7"
    ),
    "paper/source/sections/limitations.tex": (
        "5d463b0c5a555b5fe1e7cebfadb89c291175cc35dc4ae9654d75ad54240a8082"
    ),
    "paper/source/sections/conclusion.tex": (
        "2a037e985ac24f91d79115f0c473dd59f02a896cc57c0379afd9756a32f7a7e4"
    ),
    "paper/source/sections/appendix.tex": (
        "19fbd15520142fc27cbd0d20ee5a9881f3257b8c89c612b1d5e563eded985261"
    ),
}

CLAIM_MAP_PATH = "evidence/claim-evidence-map.json"
PAPER_VALUES_PATH = "frozen-inputs/paper-values.json"
AUDIT_REPORT_PATH = "systems-paper-currency-audit.json"
AUDIT_MANIFEST_PATH = "systems-paper-currency-audit-manifest.json"
AUDIT_UNIT_PATH = "independent-unit-audit.json"

REANALYSIS_REPORT_FILENAME = "task-unit-reanalysis.json"
REANALYSIS_MARKDOWN_FILENAME = "task-unit-reanalysis.md"
REANALYSIS_PARENT_BINDING_FILENAME = "parent-audit-binding.json"
REANALYSIS_SURFACE_INVENTORY_FILENAME = "paper-surface-inventory.json"
REANALYSIS_CLAIM_LEDGER_FILENAME = "claim-disposition-ledger.json"
REANALYSIS_NOTE_CLAIMS_FILENAME = "note-claims.json"
REANALYSIS_UNIT_AUDIT_FILENAME = "task-level-analysis.json"
REANALYSIS_REPLAY_FILENAME = "statistical-replay.json"
REANALYSIS_SCHEMAS_FILENAME = "task-unit-reanalysis-schemas.json"
REANALYSIS_MANIFEST_FILENAME = "task-unit-reanalysis-manifest.json"

EXPECTED_ORIGINAL_CLAIM_IDS = tuple(f"C{index}" for index in range(1, 9))
SURFACE_SCAN_TERMS = (
    "paired",
    "\\bootstrapresamples",
    "\\seedcount{} seeds",
    "seeds are included in each cell identity",
    "seeds do not provide independent stochastic policies",
    "aggregates ten tasks and three seeds",
    "outperforms execute-once",
    "exceeded execute-once",
)

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, Any])
_JSON_LIST_ADAPTER = TypeAdapter(list[dict[str, Any]])


class TaskUnitReanalysisIntegrityError(ValueError):
    """Raised when a parent, audit, claim, or generated artifact changes."""


class OriginalClaimDisposition(str, Enum):
    REVISE_UNIT_LABEL = "revise-unit-label"
    RETIRE_PUBLICATION_INFERENCE = "retire-publication-inference"
    RETAIN_ENGINEERING_DESCRIPTIVE = "retain-engineering-descriptive"
    RETAIN_ENGINEERING_WITH_HUMAN_CAVEAT = "retain-engineering-with-human-caveat"
    RETAIN_CELL_DESCRIPTIVE = "retain-cell-descriptive"
    RETAIN_CONTROLLED_ABLATION_ONLY = "retain-controlled-ablation-only"
    RETAIN_NEGATIVE_EVIDENCE = "retain-negative-evidence"
    RETAIN_SCOPE_BOUNDARY = "retain-scope-boundary"


class NumericDisposition(str, Enum):
    TASK_INVENTORY = "retain-task-inventory"
    IDEMPOTENCY_ONLY = "retain-idempotency-only"
    ENGINEERING_DESCRIPTIVE = "retain-engineering-descriptive"
    CELL_DESCRIPTIVE = "retain-cell-level-descriptive"
    RETIRE_SEED_CELL_INFERENCE = "retire-seed-cell-publication-inference"
    REANALYZE_AT_TASK_LEVEL = "reanalyze-at-independent-task-level"
    ROUTE_A_PARENT = "retain-route-a-parent-evidence"


class TableDisposition(str, Enum):
    CELL_DESCRIPTIVE = "retain-cell-level-descriptive-with-unit-warning"
    ROUTE_A_NEGATIVE = "retain-route-a-negative-evidence"


class ManuscriptSurfaceDisposition(str, Enum):
    RETIRE_PUBLICATION_INFERENCE = "retire-publication-inference"
    REVISE_TASK_UNIT = "revise-to-independent-task-unit"
    IDEMPOTENCY_ONLY = "label-seeds-as-idempotency-only"
    HISTORICAL_PROTOCOL = "retain-as-historical-protocol-only"


class NoteClaimStatus(str, Enum):
    ADDITIVE_REANALYSIS = "supported-additive-reanalysis"
    HISTORICAL_PARENT = "supported-historical-parent-only"
    LIMITATION = "supported-limitation"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _jsonable(value: Any) -> Any:
    if isinstance(value, KernelContract):
        return value.model_dump(mode="json")
    return value


def _pretty_json_text(value: Any) -> str:
    return (
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _addressed_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    normalized = _JSON_OBJECT_ADAPTER.dump_python(payload, mode="json")
    result = dict(payload)
    result[hash_field] = canonical_sha256(normalized)
    return result


def _escape_json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _numeric_leaves(value: Any, pointer: str = "") -> Iterable[tuple[str, int | float]]:
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{pointer}/{_escape_json_pointer_token(str(key))}"
            yield from _numeric_leaves(value[key], child)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _numeric_leaves(item, f"{pointer}/{index}")
        return
    if isinstance(value, int | float) and not isinstance(value, bool):
        yield pointer, value


def _numeric_disposition(pointer: str) -> tuple[NumericDisposition, bool]:
    if pointer.startswith("/route_a_"):
        return NumericDisposition.ROUTE_A_PARENT, False
    if pointer.startswith("/paired_differences/") or pointer in {
        "/bootstrap_ci95_lower",
        "/bootstrap_ci95_upper",
    }:
        return NumericDisposition.RETIRE_SEED_CELL_INFERENCE, True
    if pointer == "/paired_mean_gain":
        return NumericDisposition.REANALYZE_AT_TASK_LEVEL, True
    if pointer == "/seed_count" or pointer.startswith("/seeds/"):
        return NumericDisposition.IDEMPOTENCY_ONLY, True
    if pointer in {"/task_count", "/task_family_counts/mdbench", "/task_family_counts/uci"}:
        return NumericDisposition.TASK_INVENTORY, True
    if pointer.startswith("/mode_metrics/"):
        return NumericDisposition.CELL_DESCRIPTIVE, pointer in {
            "/mode_metrics/execute_once/task_success_rate",
            "/mode_metrics/full_loop/task_success_rate",
            "/mode_metrics/full_loop/exact_reproduction_rate",
            "/mode_metrics/full_loop/unsupported_claim_count",
        }
    return NumericDisposition.ENGINEERING_DESCRIPTIVE, False


def _surface_disposition(line: str) -> ManuscriptSurfaceDisposition:
    lowered = line.casefold()
    retirement_markers = (
        "pairedcilower",
        "pairedciupper",
        "30 task-seed",
        "paired confidence interval excludes zero",
        "outperforms execute-once",
        "exceeded execute-once",
    )
    if any(marker in lowered for marker in retirement_markers):
        return ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE
    if "seedcount" in lowered or "seeds are included" in lowered or "seeds do not provide" in lowered:
        return ManuscriptSurfaceDisposition.IDEMPOTENCY_ONLY
    if "pairedgain" in lowered or "paired mean gain" in lowered or "principal endpoint" in lowered:
        return ManuscriptSurfaceDisposition.REVISE_TASK_UNIT
    return ManuscriptSurfaceDisposition.HISTORICAL_PROTOCOL


def _surface_requirement(disposition: ManuscriptSurfaceDisposition) -> str:
    return {
        ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE: (
            "Task 263.7.2 must remove this publication-facing use of the 30-cell interval and "
            "replace it with a clearly labelled additive task-level analysis."
        ),
        ManuscriptSurfaceDisposition.REVISE_TASK_UNIT: (
            "Task 263.7.2 must state task as the independent unit and distinguish the unchanged "
            "mean from the corrected uncertainty analysis."
        ),
        ManuscriptSurfaceDisposition.IDEMPOTENCY_ONLY: (
            "The three seeds may be described only as deterministic idempotency checks, not as "
            "independent sampling variation."
        ),
        ManuscriptSurfaceDisposition.HISTORICAL_PROTOCOL: (
            "Retain this only as a description of the original internal protocol or reproduction "
            "path; it cannot support publication inference."
        ),
    }[disposition]


class AuditEvidenceBinding(KernelContract):
    schema_version: Literal["systems-paper-task-unit-audit-binding-v1"] = (
        "systems-paper-task-unit-audit-binding-v1"
    )
    audit_git_commit: StableId = AUDIT_GIT_COMMIT
    audit_package_relative_path: NonEmptyText
    parent_evidence_hash: Sha256
    audit_report_hash: Sha256 = AUDIT_REPORT_HASH
    audit_report_file_sha256: Sha256 = AUDIT_REPORT_FILE_SHA256
    audit_manifest_hash: Sha256 = AUDIT_MANIFEST_HASH
    audit_manifest_file_sha256: Sha256 = AUDIT_MANIFEST_FILE_SHA256
    independent_unit_audit_hash: Sha256 = AUDIT_UNIT_HASH
    independent_unit_file_sha256: Sha256 = AUDIT_UNIT_FILE_SHA256
    statistical_projection_hash: Sha256 = AUDIT_PROJECTION_HASH
    repair_plan_hash: Sha256 = AUDIT_REPAIR_PLAN_HASH
    source_registry_hash: Sha256 = AUDIT_SOURCE_REGISTRY_HASH
    publication_ready: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    binding_hash: Sha256

    @model_validator(mode="after")
    def _validate_binding(self) -> AuditEvidenceBinding:
        expected = {
            "audit_git_commit": AUDIT_GIT_COMMIT,
            "audit_report_hash": AUDIT_REPORT_HASH,
            "audit_report_file_sha256": AUDIT_REPORT_FILE_SHA256,
            "audit_manifest_hash": AUDIT_MANIFEST_HASH,
            "audit_manifest_file_sha256": AUDIT_MANIFEST_FILE_SHA256,
            "independent_unit_audit_hash": AUDIT_UNIT_HASH,
            "independent_unit_file_sha256": AUDIT_UNIT_FILE_SHA256,
            "statistical_projection_hash": AUDIT_PROJECTION_HASH,
            "repair_plan_hash": AUDIT_REPAIR_PLAN_HASH,
            "source_registry_hash": AUDIT_SOURCE_REGISTRY_HASH,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise TaskUnitReanalysisIntegrityError(
                    f"Task 263.7.0 binding changed: {field_name}"
                )
        if self.parent_evidence_hash != AUDIT_PARENT_EVIDENCE_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 parent binding changed")
        if self.binding_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("audit evidence binding hash mismatch")
        return self

    @classmethod
    def from_package(
        cls,
        audit_dir: Path,
        *,
        report: SystemsPaperCurrencyAuditReport,
        manifest: SystemsPaperCurrencyAuditManifest,
        package_relative_path: str = (
            "runs/manual-live/task26370-systems-paper-currency-audit-v1"
        ),
    ) -> AuditEvidenceBinding:
        if report.report_hash != AUDIT_REPORT_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 report hash changed")
        if manifest.manifest_hash != AUDIT_MANIFEST_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 manifest hash changed")
        if report.independent_unit_audit.audit_hash != AUDIT_UNIT_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 unit audit changed")
        if report.replay_certificate.projection_sha256 != AUDIT_PROJECTION_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 projection changed")
        if report.repair_plan.plan_hash != AUDIT_REPAIR_PLAN_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 repair plan changed")
        if report.source_registry.registry_hash != AUDIT_SOURCE_REGISTRY_HASH:
            raise TaskUnitReanalysisIntegrityError("Task 263.7.0 source registry changed")
        expected_files = {
            AUDIT_REPORT_PATH: AUDIT_REPORT_FILE_SHA256,
            AUDIT_MANIFEST_PATH: AUDIT_MANIFEST_FILE_SHA256,
            AUDIT_UNIT_PATH: AUDIT_UNIT_FILE_SHA256,
        }
        for relative_path, expected_hash in expected_files.items():
            path = audit_dir / relative_path
            if not path.is_file() or _file_sha256(path) != expected_hash:
                raise TaskUnitReanalysisIntegrityError(
                    f"Task 263.7.0 file binding changed: {relative_path}"
                )
        payload = {
            "schema_version": "systems-paper-task-unit-audit-binding-v1",
            "audit_git_commit": AUDIT_GIT_COMMIT,
            "audit_package_relative_path": package_relative_path,
            "parent_evidence_hash": report.parent.parent_evidence_hash,
            "audit_report_hash": report.report_hash,
            "audit_report_file_sha256": _file_sha256(audit_dir / AUDIT_REPORT_PATH),
            "audit_manifest_hash": manifest.manifest_hash,
            "audit_manifest_file_sha256": _file_sha256(audit_dir / AUDIT_MANIFEST_PATH),
            "independent_unit_audit_hash": report.independent_unit_audit.audit_hash,
            "independent_unit_file_sha256": _file_sha256(audit_dir / AUDIT_UNIT_PATH),
            "statistical_projection_hash": report.replay_certificate.projection_sha256,
            "repair_plan_hash": report.repair_plan.plan_hash,
            "source_registry_hash": report.source_registry.registry_hash,
            "publication_ready": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        return cls.model_validate(_addressed_payload(payload, "binding_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"binding_hash"}))


class NumericEvidenceBinding(KernelContract):
    schema_version: Literal["systems-paper-original-numeric-binding-v1"] = (
        "systems-paper-original-numeric-binding-v1"
    )
    json_pointer: NonEmptyText
    value: int | float
    disposition: NumericDisposition
    referenced_in_additive_note: bool


class OriginalTableBinding(KernelContract):
    schema_version: Literal["systems-paper-original-table-binding-v1"] = (
        "systems-paper-original-table-binding-v1"
    )
    table_id: StableId
    relative_path: NonEmptyText
    file_sha256: Sha256
    disposition: TableDisposition
    publication_inference_allowed: Literal[False] = False


class ManuscriptSurfaceBinding(KernelContract):
    schema_version: Literal["systems-paper-manuscript-surface-binding-v1"] = (
        "systems-paper-manuscript-surface-binding-v1"
    )
    surface_id: StableId
    relative_path: NonEmptyText
    file_sha256: Sha256
    line_number: int = Field(ge=1)
    line_excerpt: NonEmptyText
    line_sha256: Sha256
    matched_terms: list[NonEmptyText]
    disposition: ManuscriptSurfaceDisposition
    corrected_requirement: NonEmptyText
    publication_inference_allowed: Literal[False] = False


class PaperSurfaceInventory(KernelContract):
    schema_version: Literal["systems-paper-original-surface-inventory-v1"] = (
        "systems-paper-original-surface-inventory-v1"
    )
    parent_evidence_hash: Sha256
    source_file_hashes: dict[NonEmptyText, Sha256]
    claim_map_graph_hash: Sha256
    original_claim_ids: list[StableId]
    numeric_source_relative_path: Literal["frozen-inputs/paper-values.json"] = (
        "frozen-inputs/paper-values.json"
    )
    numeric_source_sha256: Sha256
    numeric_bindings: list[NumericEvidenceBinding]
    table_bindings: list[OriginalTableBinding]
    manuscript_surfaces: list[ManuscriptSurfaceBinding]
    original_claim_count: Literal[8] = 8
    unbound_original_claim_count: Literal[0] = 0
    unbound_numeric_leaf_count: Literal[0] = 0
    unbound_table_count: Literal[0] = 0
    unbound_inference_surface_count: Literal[0] = 0
    inventory_hash: Sha256

    @model_validator(mode="after")
    def _validate_inventory(self) -> PaperSurfaceInventory:
        if self.parent_evidence_hash != AUDIT_PARENT_EVIDENCE_HASH:
            raise TaskUnitReanalysisIntegrityError("surface inventory parent changed")
        if self.source_file_hashes != EXPECTED_PAPER_SURFACE_HASHES:
            raise TaskUnitReanalysisIntegrityError("original paper surface hashes changed")
        if self.original_claim_ids != list(EXPECTED_ORIGINAL_CLAIM_IDS):
            raise TaskUnitReanalysisIntegrityError("original claim inventory changed")
        pointers = [item.json_pointer for item in self.numeric_bindings]
        if len(pointers) != len(set(pointers)):
            raise ValueError("numeric evidence pointers must be unique")
        if {item.relative_path for item in self.table_bindings} != {
            "paper/source/tables/mode-results.tex",
            "paper/source/tables/route-a-results.tex",
        }:
            raise ValueError("original table inventory is incomplete")
        surface_ids = [item.surface_id for item in self.manuscript_surfaces]
        if not surface_ids or len(surface_ids) != len(set(surface_ids)):
            raise ValueError("manuscript inference surface inventory is empty or duplicated")
        if self.inventory_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("paper surface inventory hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaperSurfaceInventory:
        payload = {
            "schema_version": "systems-paper-original-surface-inventory-v1",
            "original_claim_count": 8,
            "unbound_original_claim_count": 0,
            "unbound_numeric_leaf_count": 0,
            "unbound_table_count": 0,
            "unbound_inference_surface_count": 0,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "inventory_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"inventory_hash"}))


def build_paper_surface_inventory(
    package_dir: Path,
    *,
    parent: ParentSystemsPaperEvidence,
) -> PaperSurfaceInventory:
    """Inventory every original claim, numeric leaf, table, and inference surface."""

    observed_hashes: dict[str, str] = {}
    for relative_path, expected_hash in EXPECTED_PAPER_SURFACE_HASHES.items():
        path = package_dir / relative_path
        if not path.is_file():
            raise TaskUnitReanalysisIntegrityError(f"original paper surface missing: {relative_path}")
        observed = _file_sha256(path)
        if observed != expected_hash:
            raise TaskUnitReanalysisIntegrityError(f"original paper surface changed: {relative_path}")
        observed_hashes[relative_path] = observed

    claim_map = json.loads((package_dir / CLAIM_MAP_PATH).read_text(encoding="utf-8"))
    claims = claim_map.get("claims")
    if not isinstance(claims, list):
        raise TaskUnitReanalysisIntegrityError("original claim map has no claim list")
    claim_ids = [str(item.get("claim_id")) for item in claims]
    if claim_ids != list(EXPECTED_ORIGINAL_CLAIM_IDS):
        raise TaskUnitReanalysisIntegrityError("original claim IDs changed")
    graph_hash = str(claim_map.get("graph_hash", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", graph_hash):
        raise TaskUnitReanalysisIntegrityError("original claim graph hash is invalid")

    paper_values = json.loads((package_dir / PAPER_VALUES_PATH).read_text(encoding="utf-8"))
    numeric_bindings = []
    for pointer, value in _numeric_leaves(paper_values):
        numeric_disposition, note_use = _numeric_disposition(pointer)
        numeric_bindings.append(
            NumericEvidenceBinding(
                json_pointer=pointer,
                value=value,
                disposition=numeric_disposition,
                referenced_in_additive_note=note_use,
            )
        )
    if not numeric_bindings:
        raise TaskUnitReanalysisIntegrityError("original paper has no numeric evidence leaves")

    table_bindings = [
        OriginalTableBinding(
            table_id="tab-all-modes",
            relative_path="paper/source/tables/mode-results.tex",
            file_sha256=observed_hashes["paper/source/tables/mode-results.tex"],
            disposition=TableDisposition.CELL_DESCRIPTIVE,
            publication_inference_allowed=False,
        ),
        OriginalTableBinding(
            table_id="tab-route-a",
            relative_path="paper/source/tables/route-a-results.tex",
            file_sha256=observed_hashes["paper/source/tables/route-a-results.tex"],
            disposition=TableDisposition.ROUTE_A_NEGATIVE,
            publication_inference_allowed=False,
        ),
    ]

    surfaces: list[ManuscriptSurfaceBinding] = []
    for relative_path in sorted(observed_hashes):
        if not relative_path.endswith(".tex") or "/tables/" in relative_path:
            continue
        path = package_dir / relative_path
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.casefold()
            matched = sorted(term for term in SURFACE_SCAN_TERMS if term in lowered)
            if not matched:
                continue
            excerpt = line.strip()
            if not excerpt:
                continue
            surface_disposition = _surface_disposition(excerpt)
            surface_id = (
                relative_path.replace("/", "-").replace(".", "-").replace("_", "-")
                + f"-l{line_number}"
            )
            surfaces.append(
                ManuscriptSurfaceBinding(
                    surface_id=surface_id,
                    relative_path=relative_path,
                    file_sha256=observed_hashes[relative_path],
                    line_number=line_number,
                    line_excerpt=excerpt,
                    line_sha256=_sha256_bytes(excerpt.encode("utf-8")),
                    matched_terms=matched,
                    disposition=surface_disposition,
                    corrected_requirement=_surface_requirement(surface_disposition),
                    publication_inference_allowed=False,
                )
            )
    if not any(
        item.disposition is ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE
        for item in surfaces
    ):
        raise TaskUnitReanalysisIntegrityError("no publication-facing seed-cell surface found")

    return PaperSurfaceInventory.create(
        parent_evidence_hash=parent.parent_evidence_hash,
        source_file_hashes=observed_hashes,
        claim_map_graph_hash=graph_hash,
        original_claim_ids=claim_ids,
        numeric_source_relative_path=PAPER_VALUES_PATH,
        numeric_source_sha256=observed_hashes[PAPER_VALUES_PATH],
        numeric_bindings=numeric_bindings,
        table_bindings=table_bindings,
        manuscript_surfaces=surfaces,
    )


class EvidenceLocator(KernelContract):
    schema_version: Literal["systems-paper-additive-evidence-locator-v1"] = (
        "systems-paper-additive-evidence-locator-v1"
    )
    source_kind: Literal["immutable-task260-parent", "task26370-audit"]
    relative_path: NonEmptyText
    file_sha256: Sha256
    json_pointer: NonEmptyText


class OriginalClaimBinding(KernelContract):
    schema_version: Literal["systems-paper-original-claim-disposition-v1"] = (
        "systems-paper-original-claim-disposition-v1"
    )
    original_claim_id: StableId
    original_statement: NonEmptyText
    original_status: NonEmptyText
    original_evidence_id: NonEmptyText
    disposition: OriginalClaimDisposition
    corrected_statement: NonEmptyText
    evidence: list[EvidenceLocator]
    publication_inference_allowed: Literal[False] = False
    binding_hash: Sha256

    @model_validator(mode="after")
    def _validate_binding(self) -> OriginalClaimBinding:
        if not self.evidence:
            raise ValueError("original claim disposition requires evidence")
        if self.binding_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("original claim binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> OriginalClaimBinding:
        payload = {
            "schema_version": "systems-paper-original-claim-disposition-v1",
            "publication_inference_allowed": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "binding_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"binding_hash"}))


_CLAIM_DISPOSITIONS: dict[str, tuple[OriginalClaimDisposition, str]] = {
    "C1": (
        OriginalClaimDisposition.REVISE_UNIT_LABEL,
        "The full loop completed ten task definitions under three deterministic idempotency "
        "repetitions; the design contains ten independent task outcomes, not thirty.",
    ),
    "C2": (
        OriginalClaimDisposition.RETIRE_PUBLICATION_INFERENCE,
        "The unchanged task-level mean difference is 0.50. The additive task bootstrap interval "
        "is [0.20, 0.80], and the exact two-sided sign-test p-value is 0.0625. The original "
        "30-cell interval remains historical internal-gate evidence only.",
    ),
    "C3": (
        OriginalClaimDisposition.RETAIN_ENGINEERING_DESCRIPTIVE,
        "Exact cell replay and the frozen unsupported-claim count remain engineering properties "
        "of the controlled matrix; they do not establish an external scientific effect.",
    ),
    "C4": (
        OriginalClaimDisposition.RETAIN_ENGINEERING_WITH_HUMAN_CAVEAT,
        "No research-decision intervention was recorded after campaign start, but independent "
        "human scientific review has not been completed.",
    ),
    "C5": (
        OriginalClaimDisposition.RETAIN_CELL_DESCRIPTIVE,
        "The 15-of-24 recovery count remains a cell-level description of deterministic repeated "
        "tasks and is not an independent-task effect estimate.",
    ),
    "C6": (
        OriginalClaimDisposition.RETAIN_CONTROLLED_ABLATION_ONLY,
        "The ablation values describe behavior under co-designed controlled faults and cannot be "
        "used as evidence of performance on independently authored research tasks.",
    ),
    "C7": (
        OriginalClaimDisposition.RETAIN_NEGATIVE_EVIDENCE,
        "Both Route A rounds remain negative under their frozen unseen gates.",
    ),
    "C8": (
        OriginalClaimDisposition.RETAIN_SCOPE_BOUNDARY,
        "Previously observed MDBench traces remain workflow-behavior evidence only and are not "
        "new method holdout evidence.",
    ),
}


class ClaimDispositionLedger(KernelContract):
    schema_version: Literal["systems-paper-claim-disposition-ledger-v1"] = (
        "systems-paper-claim-disposition-ledger-v1"
    )
    task_id: Literal["263.7.1"] = "263.7.1"
    parent_evidence_hash: Sha256
    audit_binding_hash: Sha256
    surface_inventory_hash: Sha256
    original_claim_map_sha256: Sha256
    original_claim_bindings: list[OriginalClaimBinding]
    original_claim_count: Literal[8] = 8
    retired_publication_inference_claim_ids: list[Literal["C2"]]
    unbound_original_claim_count: Literal[0] = 0
    original_preregistration_replaced: Literal[False] = False
    parent_manuscript_rewritten: Literal[False] = False
    ledger_hash: Sha256

    @field_validator("original_claim_bindings")
    @classmethod
    def _sort_claims(cls, value: list[OriginalClaimBinding]) -> list[OriginalClaimBinding]:
        normalized = sorted(value, key=lambda item: item.original_claim_id)
        if [item.original_claim_id for item in normalized] != list(EXPECTED_ORIGINAL_CLAIM_IDS):
            raise ValueError("claim disposition ledger must cover C1 through C8 exactly")
        return normalized

    @model_validator(mode="after")
    def _validate_ledger(self) -> ClaimDispositionLedger:
        retired = [
            item.original_claim_id
            for item in self.original_claim_bindings
            if item.disposition is OriginalClaimDisposition.RETIRE_PUBLICATION_INFERENCE
        ]
        if retired != ["C2"] or self.retired_publication_inference_claim_ids != ["C2"]:
            raise ValueError("C2 must be the retired publication-inference claim")
        if self.ledger_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("claim disposition ledger hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ClaimDispositionLedger:
        payload = {
            "schema_version": "systems-paper-claim-disposition-ledger-v1",
            "task_id": TASK_ID,
            "original_claim_count": 8,
            "retired_publication_inference_claim_ids": ["C2"],
            "unbound_original_claim_count": 0,
            "original_preregistration_replaced": False,
            "parent_manuscript_rewritten": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "ledger_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"ledger_hash"}))


def build_claim_disposition_ledger(
    package_dir: Path,
    *,
    parent: ParentSystemsPaperEvidence,
    audit_binding: AuditEvidenceBinding,
    surface_inventory: PaperSurfaceInventory,
) -> ClaimDispositionLedger:
    claim_path = package_dir / CLAIM_MAP_PATH
    claim_map = json.loads(claim_path.read_text(encoding="utf-8"))
    claims = claim_map.get("claims")
    if not isinstance(claims, list):
        raise TaskUnitReanalysisIntegrityError("original claim list is missing")
    observed_ids = [str(item.get("claim_id")) for item in claims]
    if observed_ids != list(EXPECTED_ORIGINAL_CLAIM_IDS):
        raise TaskUnitReanalysisIntegrityError("original claim list changed")
    claim_file_hash = _file_sha256(claim_path)
    bindings = []
    for index, item in enumerate(claims):
        claim_id = str(item["claim_id"])
        disposition, corrected = _CLAIM_DISPOSITIONS[claim_id]
        bindings.append(
            OriginalClaimBinding.create(
                original_claim_id=claim_id,
                original_statement=str(item["text"]),
                original_status=str(item["status"]),
                original_evidence_id=str(item["evidence_id"]),
                disposition=disposition,
                corrected_statement=corrected,
                evidence=[
                    EvidenceLocator(
                        source_kind="immutable-task260-parent",
                        relative_path=CLAIM_MAP_PATH,
                        file_sha256=claim_file_hash,
                        json_pointer=f"/claims/{index}",
                    )
                ],
                publication_inference_allowed=False,
            )
        )
    return ClaimDispositionLedger.create(
        parent_evidence_hash=parent.parent_evidence_hash,
        audit_binding_hash=audit_binding.binding_hash,
        surface_inventory_hash=surface_inventory.inventory_hash,
        original_claim_map_sha256=claim_file_hash,
        original_claim_bindings=bindings,
    )


class AdditiveNoteClaim(KernelContract):
    schema_version: Literal["systems-paper-additive-note-claim-v1"] = (
        "systems-paper-additive-note-claim-v1"
    )
    claim_id: StableId
    status: NoteClaimStatus
    statement: NonEmptyText
    values: dict[str, Any]
    evidence: list[EvidenceLocator]
    fresh_confirmatory_evidence: Literal[False] = False
    publication_effect_claim_allowed: Literal[False] = False
    claim_hash: Sha256

    @model_validator(mode="after")
    def _validate_claim(self) -> AdditiveNoteClaim:
        if not self.evidence:
            raise ValueError("additive note claim requires evidence")
        if self.claim_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("additive note claim hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdditiveNoteClaim:
        payload = {
            "schema_version": "systems-paper-additive-note-claim-v1",
            "fresh_confirmatory_evidence": False,
            "publication_effect_claim_allowed": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "claim_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"claim_hash"}))


def build_additive_note_claims(
    *,
    audit: IndependentUnitAudit,
    audit_binding: AuditEvidenceBinding,
    parent: ParentSystemsPaperEvidence,
) -> list[AdditiveNoteClaim]:
    audit_locator = lambda pointer: EvidenceLocator(  # noqa: E731
        source_kind="task26370-audit",
        relative_path=AUDIT_UNIT_PATH,
        file_sha256=AUDIT_UNIT_FILE_SHA256,
        json_pointer=pointer,
    )
    parent_values_locator = lambda pointer: EvidenceLocator(  # noqa: E731
        source_kind="immutable-task260-parent",
        relative_path=PAPER_VALUES_PATH,
        file_sha256=EXPECTED_PAPER_SURFACE_HASHES[PAPER_VALUES_PATH],
        json_pointer=pointer,
    )
    task_vector = audit.task_level_differences
    claims = [
        AdditiveNoteClaim.create(
            claim_id="R1-independent-unit-count",
            status=NoteClaimStatus.ADDITIVE_REANALYSIS,
            statement=(
                "The original 30 task-seed pairs contain ten independent task outcomes and three "
                "deterministic repetitions per task."
            ),
            values={"seed_cell_pairs": 30, "independent_tasks": 10, "seeds": 3},
            evidence=[
                audit_locator("/seed_cell_pair_count"),
                audit_locator("/independent_task_count"),
                parent_values_locator("/seed_count"),
            ],
        ),
        AdditiveNoteClaim.create(
            claim_id="R2-idempotency-role",
            status=NoteClaimStatus.ADDITIVE_REANALYSIS,
            statement=(
                "Every full-loop and execute-once scientific output is identical across the three "
                "seeds within a task; the repetitions test idempotency rather than sampling variation."
            ),
            values={"duplicate_groups": audit.deterministic_seed_duplicate_group_count},
            evidence=[audit_locator("/deterministic_seed_duplicate_group_count")],
        ),
        AdditiveNoteClaim.create(
            claim_id="R3-task-vector",
            status=NoteClaimStatus.ADDITIVE_REANALYSIS,
            statement="The independent-task paired-difference vector contains ten values.",
            values={"task_differences": task_vector},
            evidence=[audit_locator("/task_level_differences")],
        ),
        AdditiveNoteClaim.create(
            claim_id="R4-task-bootstrap",
            status=NoteClaimStatus.ADDITIVE_REANALYSIS,
            statement=(
                "The task-level mean difference is 0.50, and the frozen 20,000-resample task "
                "bootstrap interval is [0.20, 0.80]."
            ),
            values={
                "mean": audit.task_level_mean,
                "ci95": list(audit.task_level_ci95),
                "resamples": audit.task_level_bootstrap_resamples,
                "seed": audit.task_level_bootstrap_seed,
            },
            evidence=[
                audit_locator("/task_level_mean"),
                audit_locator("/task_level_ci95"),
                audit_locator("/task_level_bootstrap_resamples"),
                audit_locator("/task_level_bootstrap_seed"),
            ],
        ),
        AdditiveNoteClaim.create(
            claim_id="R5-exact-sign-test",
            status=NoteClaimStatus.ADDITIVE_REANALYSIS,
            statement=(
                "The exact sign test has five wins, no losses, five ties, one-sided p=0.03125, "
                "and two-sided p=0.0625."
            ),
            values={
                "wins": audit.sign_test_wins,
                "losses": audit.sign_test_losses,
                "ties": audit.sign_test_ties,
                "one_sided_p": audit.sign_test_one_sided_p,
                "two_sided_p": audit.sign_test_two_sided_p,
            },
            evidence=[
                audit_locator("/sign_test_wins"),
                audit_locator("/sign_test_losses"),
                audit_locator("/sign_test_ties"),
                audit_locator("/sign_test_one_sided_p"),
                audit_locator("/sign_test_two_sided_p"),
            ],
        ),
        AdditiveNoteClaim.create(
            claim_id="R6-family-sensitivity",
            status=NoteClaimStatus.LIMITATION,
            statement=(
                "The UCI mean is 0.25, the MDBench mean is 0.666667, and the family-balanced mean "
                "is 0.458333; two families do not support a broad cross-domain estimate."
            ),
            values={
                "family_counts": audit.family_task_counts,
                "family_means": audit.family_mean_differences,
                "family_balanced_mean": audit.family_balanced_mean,
            },
            evidence=[
                audit_locator("/family_task_counts"),
                audit_locator("/family_mean_differences"),
                audit_locator("/family_balanced_mean"),
            ],
        ),
        AdditiveNoteClaim.create(
            claim_id="R7-original-interval-status",
            status=NoteClaimStatus.HISTORICAL_PARENT,
            statement=(
                "The original 30-cell interval [0.333333, 0.666667] remains evidence for the "
                "historical internal gate and is not valid for independent-task publication inference."
            ),
            values={
                "historical_ci95": list(audit.frozen_seed_pair_ci95),
                "publication_inference_valid": False,
            },
            evidence=[
                parent_values_locator("/bootstrap_ci95_lower"),
                parent_values_locator("/bootstrap_ci95_upper"),
                audit_locator("/original_interval_valid_for_independent_task_inference"),
            ],
        ),
        AdditiveNoteClaim.create(
            claim_id="R8-no-primary-endpoint-substitution",
            status=NoteClaimStatus.LIMITATION,
            statement=(
                "This additive analysis is a post-audit unit correction. It does not replace the "
                "original preregistration and is not fresh confirmatory evidence."
            ),
            values={
                "original_preregistration_replaced": False,
                "fresh_confirmatory_evidence": False,
            },
            evidence=[audit_locator("/original_contribution_gate_reusable_for_publication_inference")],
        ),
        AdditiveNoteClaim.create(
            claim_id="R9-publication-boundary",
            status=NoteClaimStatus.LIMITATION,
            statement=(
                "The corrected analysis does not supply independent task authors, external agents, "
                "new task families, independent scoring, or human scientific review."
            ),
            values={
                "publication_ready": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            },
            evidence=[
                EvidenceLocator(
                    source_kind="task26370-audit",
                    relative_path=AUDIT_REPORT_PATH,
                    file_sha256=AUDIT_REPORT_FILE_SHA256,
                    json_pointer="/publication_ready",
                ),
                EvidenceLocator(
                    source_kind="task26370-audit",
                    relative_path=AUDIT_REPORT_PATH,
                    file_sha256=AUDIT_REPORT_FILE_SHA256,
                    json_pointer="/external_submission_authorized",
                ),
            ],
        ),
    ]
    if parent.parent_evidence_hash != audit_binding.parent_evidence_hash:
        raise TaskUnitReanalysisIntegrityError("note claims are not bound to one parent")
    return claims


class AdditiveNoteMechanicalReview(KernelContract):
    schema_version: Literal["systems-paper-additive-note-mechanical-review-v1"] = (
        "systems-paper-additive-note-mechanical-review-v1"
    )
    scan_scope: list[Literal["full-rendered-markdown"]]
    banned_terms: list[NonEmptyText]
    banned_term_counts: dict[NonEmptyText, int]
    em_dash_count: Literal[0] = 0
    unbound_original_claim_count: Literal[0] = 0
    unbound_numeric_leaf_count: Literal[0] = 0
    unbound_table_count: Literal[0] = 0
    unbound_inference_surface_count: Literal[0] = 0
    venue_fit_certified: Literal[False] = False
    target_venue_unspecified: Literal[True] = True
    passed: Literal[True] = True


class TaskUnitReanalysisReport(KernelContract):
    schema_version: Literal["systems-paper-task-unit-reanalysis-report-v1"] = (
        "systems-paper-task-unit-reanalysis-report-v1"
    )
    task_id: Literal["263.7.1"] = "263.7.1"
    built_at: datetime
    parent: ParentSystemsPaperEvidence
    audit_binding: AuditEvidenceBinding
    surface_inventory: PaperSurfaceInventory
    claim_ledger: ClaimDispositionLedger
    independent_unit_audit: IndependentUnitAudit
    note_claims: list[AdditiveNoteClaim]
    replay_certificate: StatisticalReplayCertificate
    mechanical_review: AdditiveNoteMechanicalReview
    estimand_status: Literal["post-audit-independent-unit-correction"] = (
        "post-audit-independent-unit-correction"
    )
    original_30_cell_gate_status: Literal["historical-internal-engineering-gate-only"] = (
        "historical-internal-engineering-gate-only"
    )
    original_preregistration_replaced: Literal[False] = False
    parent_package_mutated: Literal[False] = False
    fresh_confirmatory_evidence: Literal[False] = False
    publication_ready: Literal[False] = False
    independent_human_review_complete: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator("built_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reanalysis build time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("note_claims")
    @classmethod
    def _sort_note_claims(cls, value: list[AdditiveNoteClaim]) -> list[AdditiveNoteClaim]:
        normalized = sorted(value, key=lambda item: item.claim_id)
        expected = [f"R{index}-" for index in range(1, 10)]
        if len(normalized) != 9 or any(
            not item.claim_id.startswith(prefix)
            for item, prefix in zip(normalized, expected, strict=True)
        ):
            raise ValueError("additive note must contain R1 through R9 exactly")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> TaskUnitReanalysisReport:
        parent_hash = self.parent.parent_evidence_hash
        if any(
            observed != parent_hash
            for observed in (
                self.audit_binding.parent_evidence_hash,
                self.surface_inventory.parent_evidence_hash,
                self.claim_ledger.parent_evidence_hash,
                self.independent_unit_audit.parent_evidence_hash,
            )
        ):
            raise ValueError("reanalysis components do not share one immutable parent")
        if self.claim_ledger.audit_binding_hash != self.audit_binding.binding_hash:
            raise ValueError("claim ledger is not bound to the audit")
        if self.claim_ledger.surface_inventory_hash != self.surface_inventory.inventory_hash:
            raise ValueError("claim ledger is not bound to the paper inventory")
        if (
            self.independent_unit_audit.audit_hash
            != self.audit_binding.independent_unit_audit_hash
        ):
            raise ValueError("independent-unit audit is not bound to Task 263.7.0")
        projection = StatisticalReplayProjection.create_from_tasks(
            self.independent_unit_audit.task_comparisons
        )
        if self.replay_certificate.projection_sha256 != projection.projection_sha256:
            raise ValueError("reanalysis replay does not match task-level data")
        if self.replay_certificate.projection_sha256 != AUDIT_PROJECTION_HASH:
            raise ValueError("reanalysis projection differs from Task 263.7.0")
        if self.report_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("task-unit report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TaskUnitReanalysisReport:
        payload = {
            "schema_version": "systems-paper-task-unit-reanalysis-report-v1",
            "task_id": TASK_ID,
            "estimand_status": "post-audit-independent-unit-correction",
            "original_30_cell_gate_status": "historical-internal-engineering-gate-only",
            "original_preregistration_replaced": False,
            "parent_package_mutated": False,
            "fresh_confirmatory_evidence": False,
            "publication_ready": False,
            "independent_human_review_complete": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class TaskUnitReanalysisManifest(KernelContract):
    schema_version: Literal["systems-paper-task-unit-reanalysis-manifest-v1"] = (
        "systems-paper-task-unit-reanalysis-manifest-v1"
    )
    task_id: Literal["263.7.1"] = "263.7.1"
    parent_evidence_hash: Sha256
    audit_binding_hash: Sha256
    surface_inventory_hash: Sha256
    claim_ledger_hash: Sha256
    independent_unit_audit_hash: Sha256
    replay_certificate_hash: Sha256
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> TaskUnitReanalysisManifest:
        required = {
            REANALYSIS_REPORT_FILENAME,
            REANALYSIS_MARKDOWN_FILENAME,
            REANALYSIS_PARENT_BINDING_FILENAME,
            REANALYSIS_SURFACE_INVENTORY_FILENAME,
            REANALYSIS_CLAIM_LEDGER_FILENAME,
            REANALYSIS_NOTE_CLAIMS_FILENAME,
            REANALYSIS_UNIT_AUDIT_FILENAME,
            REANALYSIS_REPLAY_FILENAME,
            REANALYSIS_SCHEMAS_FILENAME,
        }
        if set(self.files) != required:
            raise ValueError("task-unit reanalysis manifest file set changed")
        if self.manifest_hash != self.calculated_hash():
            raise TaskUnitReanalysisIntegrityError("task-unit manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TaskUnitReanalysisManifest:
        payload = {
            "schema_version": "systems-paper-task-unit-reanalysis-manifest-v1",
            "task_id": TASK_ID,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def render_task_unit_reanalysis_markdown(report: TaskUnitReanalysisReport) -> str:
    audit = report.independent_unit_audit
    lines = [
        "# Task 263.7.1 additive independent-task reanalysis",
        "",
        "## Status and scope",
        "",
        "This note corrects the unit of analysis for the immutable Task 260 v2 Route B study. "
        "It is a post-audit reanalysis, not a replacement preregistration and not fresh "
        "confirmatory evidence. The historical package remains unchanged.",
        "",
        f"- Parent evidence hash: `{report.parent.parent_evidence_hash}`",
        f"- Task 263.7.0 audit binding: `{report.audit_binding.binding_hash}`",
        f"- Original claim ledger: `{report.claim_ledger.ledger_hash}`",
        f"- Statistical replay: `{report.replay_certificate.certificate_hash}`",
        "- Publication, public release, and submission: `false`",
        "",
        "## Unit correction",
        "",
        "| Item | Historical internal analysis | Additive task-level analysis |",
        "|---|---:|---:|",
        f"| Nominal task-seed pairs | {audit.seed_cell_pair_count} | nested idempotency records |",
        f"| Independent tasks | not used | {audit.independent_task_count} |",
        f"| Mean paired difference | {_format_number(audit.frozen_seed_pair_mean)} | {_format_number(audit.task_level_mean)} |",
        f"| 95% bootstrap interval | [{_format_number(audit.frozen_seed_pair_ci95[0])}, {_format_number(audit.frozen_seed_pair_ci95[1])}] | [{_format_number(audit.task_level_ci95[0])}, {_format_number(audit.task_level_ci95[1])}] |",
        f"| Exact sign test | not reported | {audit.sign_test_wins} wins, {audit.sign_test_losses} losses, {audit.sign_test_ties} ties |",
        f"| One-sided / two-sided p | not reported | {_format_number(audit.sign_test_one_sided_p)} / {_format_number(audit.sign_test_two_sided_p)} |",
        "",
        "The unchanged mean does not validate the old uncertainty estimate. Every scientific "
        "output hash is identical across the three seeds within each mode and task. The seed "
        "records therefore test exact idempotency and accidental seed dependence.",
        "",
        "## Independent task table",
        "",
        "| Task | Family | Execute-once | Full loop | Difference |",
        "|---|---|---:|---:|---:|",
    ]
    for task_item in audit.task_comparisons:
        execute_success = int(next(iter(task_item.execute_once_success_by_seed.values())))
        full_success = int(next(iter(task_item.full_loop_success_by_seed.values())))
        lines.append(
            f"| `{task_item.task_id}` | {task_item.family} | {execute_success} | {full_success} | "
            f"{_format_number(task_item.task_difference)} |"
        )
    lines.extend(
        [
            "",
            "Task-level difference vector: `"
            + json.dumps(audit.task_level_differences, separators=(",", ":"))
            + "`.",
            "",
            "## Family sensitivity",
            "",
            "| Family | Task count | Mean difference |",
            "|---|---:|---:|",
        ]
    )
    for family in ("uci", "mdbench"):
        lines.append(
            f"| {family} | {audit.family_task_counts[family]} | "
            f"{_format_number(audit.family_mean_differences[family])} |"
        )
    lines.extend(
        [
            f"| family-balanced | 2 families | {_format_number(audit.family_balanced_mean)} |",
            "",
            "The family contrast is a scope warning. Two families cannot estimate broad "
            "cross-domain variation.",
            "",
            "## Original claim dispositions",
            "",
            "| Claim | Disposition | Publication inference |",
            "|---|---|---|",
        ]
    )
    for claim_item in report.claim_ledger.original_claim_bindings:
        lines.append(
            f"| {claim_item.original_claim_id} | `{claim_item.disposition.value}` | blocked |"
        )
    retired_surfaces = sum(
        item.disposition is ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE
        for item in report.surface_inventory.manuscript_surfaces
    )
    lines.extend(
        [
            "",
            "C2 is retired for publication inference. The other original claims remain only "
            "within their corrected engineering, negative-evidence, or scope boundaries.",
            "",
            "## Manuscript handoff",
            "",
            f"The full LaTeX scan binds {len(report.surface_inventory.manuscript_surfaces)} "
            f"unit-sensitive lines; {retired_surfaces} require removal of publication-facing "
            "30-cell inference in Task 263.7.2. Both original tables and every numeric leaf in "
            "the frozen paper-values object have a machine-readable disposition.",
            "",
            "## Non-compensating boundaries",
            "",
            "This note does not create independent task authors, external research agents, "
            "additional task families, an independent scorer, stochastic policy trajectories, "
            "or human scientific review. It cannot make the paper ready for a venue. The next "
            "text revision may cite this note, but it must preserve the historical internal gate "
            "as history and keep all external actions disabled.",
            "",
        ]
    )
    return "\n".join(lines)


def _scan_note_markdown(markdown: str) -> AdditiveNoteMechanicalReview:
    lowered = markdown.casefold()
    counts = {
        term: lowered.count(term.casefold())
        for term in BANNED_AI_TONE_TERMS
        if lowered.count(term.casefold())
    }
    em_dash_count = markdown.count("—")
    if counts or em_dash_count:
        raise TaskUnitReanalysisIntegrityError(
            f"additive note mechanical scan failed: banned={counts}, em_dash={em_dash_count}"
        )
    return AdditiveNoteMechanicalReview(
        scan_scope=["full-rendered-markdown"],
        banned_terms=list(BANNED_AI_TONE_TERMS),
        banned_term_counts={},
        em_dash_count=0,
        unbound_original_claim_count=0,
        unbound_numeric_leaf_count=0,
        unbound_table_count=0,
        unbound_inference_surface_count=0,
        venue_fit_certified=False,
        target_venue_unspecified=True,
        passed=True,
    )


def task_unit_reanalysis_json_schemas() -> dict[str, dict[str, Any]]:
    models: Sequence[type[KernelContract]] = (
        AuditEvidenceBinding,
        NumericEvidenceBinding,
        OriginalTableBinding,
        ManuscriptSurfaceBinding,
        PaperSurfaceInventory,
        EvidenceLocator,
        OriginalClaimBinding,
        ClaimDispositionLedger,
        AdditiveNoteClaim,
        AdditiveNoteMechanicalReview,
        TaskUnitReanalysisReport,
        TaskUnitReanalysisManifest,
    )
    return {model.__name__: model.model_json_schema() for model in models}


def write_task_unit_reanalysis(
    output_dir: Path,
    report: TaskUnitReanalysisReport,
) -> TaskUnitReanalysisManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise TaskUnitReanalysisIntegrityError("task-unit output directory is not empty")
    artifacts: dict[str, Any] = {
        REANALYSIS_REPORT_FILENAME: report,
        REANALYSIS_PARENT_BINDING_FILENAME: report.audit_binding,
        REANALYSIS_SURFACE_INVENTORY_FILENAME: report.surface_inventory,
        REANALYSIS_CLAIM_LEDGER_FILENAME: report.claim_ledger,
        REANALYSIS_NOTE_CLAIMS_FILENAME: [
            item.model_dump(mode="json") for item in report.note_claims
        ],
        REANALYSIS_UNIT_AUDIT_FILENAME: report.independent_unit_audit,
        REANALYSIS_REPLAY_FILENAME: report.replay_certificate,
        REANALYSIS_SCHEMAS_FILENAME: task_unit_reanalysis_json_schemas(),
    }
    for filename, value in artifacts.items():
        _write_text_atomic(output_dir / filename, _pretty_json_text(value))
    markdown = render_task_unit_reanalysis_markdown(report)
    observed_review = _scan_note_markdown(markdown)
    if observed_review != report.mechanical_review:
        raise TaskUnitReanalysisIntegrityError("rendered note mechanical review is stale")
    _write_text_atomic(output_dir / REANALYSIS_MARKDOWN_FILENAME, markdown)
    files = {
        path.relative_to(output_dir).as_posix(): _file_sha256(path)
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    manifest = TaskUnitReanalysisManifest.create(
        parent_evidence_hash=report.parent.parent_evidence_hash,
        audit_binding_hash=report.audit_binding.binding_hash,
        surface_inventory_hash=report.surface_inventory.inventory_hash,
        claim_ledger_hash=report.claim_ledger.ledger_hash,
        independent_unit_audit_hash=report.independent_unit_audit.audit_hash,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        report_hash=report.report_hash,
        files=files,
    )
    _write_text_atomic(
        output_dir / REANALYSIS_MANIFEST_FILENAME,
        _pretty_json_text(manifest),
    )
    return manifest


def load_task_unit_reanalysis(
    output_dir: Path,
) -> tuple[TaskUnitReanalysisReport, TaskUnitReanalysisManifest]:
    manifest = TaskUnitReanalysisManifest.model_validate_json(
        (output_dir / REANALYSIS_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    actual_files = {
        path.relative_to(output_dir).as_posix(): _file_sha256(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != REANALYSIS_MANIFEST_FILENAME
    }
    if actual_files != manifest.files:
        raise TaskUnitReanalysisIntegrityError("task-unit package file set or hash changed")
    report = TaskUnitReanalysisReport.model_validate_json(
        (output_dir / REANALYSIS_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    if report.report_hash != manifest.report_hash:
        raise TaskUnitReanalysisIntegrityError("manifest/report binding mismatch")
    component_files: tuple[tuple[str, KernelContract], ...] = (
        (REANALYSIS_PARENT_BINDING_FILENAME, report.audit_binding),
        (REANALYSIS_SURFACE_INVENTORY_FILENAME, report.surface_inventory),
        (REANALYSIS_CLAIM_LEDGER_FILENAME, report.claim_ledger),
        (REANALYSIS_UNIT_AUDIT_FILENAME, report.independent_unit_audit),
        (REANALYSIS_REPLAY_FILENAME, report.replay_certificate),
    )
    for filename, expected in component_files:
        observed = json.loads((output_dir / filename).read_text(encoding="utf-8"))
        if observed != expected.model_dump(mode="json"):
            raise TaskUnitReanalysisIntegrityError(f"component/report mismatch: {filename}")
    observed_claims = _JSON_LIST_ADAPTER.validate_json(
        (output_dir / REANALYSIS_NOTE_CLAIMS_FILENAME).read_text(encoding="utf-8")
    )
    if observed_claims != [item.model_dump(mode="json") for item in report.note_claims]:
        raise TaskUnitReanalysisIntegrityError("note claim file/report mismatch")
    markdown = (output_dir / REANALYSIS_MARKDOWN_FILENAME).read_text(encoding="utf-8")
    if markdown != render_task_unit_reanalysis_markdown(report):
        raise TaskUnitReanalysisIntegrityError("rendered additive note changed")
    if _scan_note_markdown(markdown) != report.mechanical_review:
        raise TaskUnitReanalysisIntegrityError("additive note mechanical review changed")
    return report, manifest


def execute_task_unit_reanalysis(
    *,
    parent_package_dir: Path,
    audit_package_dir: Path,
    output_dir: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    replay_work_dir: Path,
    built_at: datetime,
) -> tuple[TaskUnitReanalysisReport, TaskUnitReanalysisManifest]:
    """Build or reload the additive independent-task note from immutable evidence."""

    if (output_dir / REANALYSIS_MANIFEST_FILENAME).is_file():
        report, manifest = load_task_unit_reanalysis(output_dir)
        parent = ParentSystemsPaperEvidence.from_package(parent_package_dir)
        audit_report, audit_manifest = load_systems_paper_currency_audit(audit_package_dir)
        binding = AuditEvidenceBinding.from_package(
            audit_package_dir,
            report=audit_report,
            manifest=audit_manifest,
        )
        if report.parent != parent or report.audit_binding != binding:
            raise TaskUnitReanalysisIntegrityError("persisted note parent binding changed")
        return report, manifest
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TaskUnitReanalysisIntegrityError(
            "partial task-unit reanalysis output requires manual inspection"
        )

    parent_before = ParentSystemsPaperEvidence.from_package(parent_package_dir)
    audit_report, audit_manifest = load_systems_paper_currency_audit(audit_package_dir)
    if audit_report.parent != parent_before:
        raise TaskUnitReanalysisIntegrityError("Task 263.7.0 and Task 260 parents differ")
    audit_binding = AuditEvidenceBinding.from_package(
        audit_package_dir,
        report=audit_report,
        manifest=audit_manifest,
    )
    unit_audit = build_independent_unit_audit(parent_package_dir, parent=parent_before)
    if unit_audit != audit_report.independent_unit_audit:
        raise TaskUnitReanalysisIntegrityError("fresh task-unit analysis differs from audit")
    surface_inventory = build_paper_surface_inventory(
        parent_package_dir,
        parent=parent_before,
    )
    claim_ledger = build_claim_disposition_ledger(
        parent_package_dir,
        parent=parent_before,
        audit_binding=audit_binding,
        surface_inventory=surface_inventory,
    )
    note_claims = build_additive_note_claims(
        audit=unit_audit,
        audit_binding=audit_binding,
        parent=parent_before,
    )
    replay = run_statistical_replay(
        audit=unit_audit,
        runner_path=runner_path,
        interpreters=interpreters,
        work_dir=replay_work_dir,
    )
    provisional_review = AdditiveNoteMechanicalReview(
        scan_scope=["full-rendered-markdown"],
        banned_terms=list(BANNED_AI_TONE_TERMS),
        banned_term_counts={},
        em_dash_count=0,
        unbound_original_claim_count=0,
        unbound_numeric_leaf_count=0,
        unbound_table_count=0,
        unbound_inference_surface_count=0,
        venue_fit_certified=False,
        target_venue_unspecified=True,
        passed=True,
    )
    report = TaskUnitReanalysisReport.create(
        built_at=built_at,
        parent=parent_before,
        audit_binding=audit_binding,
        surface_inventory=surface_inventory,
        claim_ledger=claim_ledger,
        independent_unit_audit=unit_audit,
        note_claims=note_claims,
        replay_certificate=replay,
        mechanical_review=provisional_review,
    )
    _scan_note_markdown(render_task_unit_reanalysis_markdown(report))
    manifest = write_task_unit_reanalysis(output_dir, report)

    parent_after = ParentSystemsPaperEvidence.from_package(parent_package_dir)
    surface_after = build_paper_surface_inventory(parent_package_dir, parent=parent_after)
    audit_after_report, audit_after_manifest = load_systems_paper_currency_audit(
        audit_package_dir
    )
    binding_after = AuditEvidenceBinding.from_package(
        audit_package_dir,
        report=audit_after_report,
        manifest=audit_after_manifest,
    )
    if parent_after != parent_before or surface_after != surface_inventory:
        raise TaskUnitReanalysisIntegrityError("Task 260 changed during additive reanalysis")
    if binding_after != audit_binding:
        raise TaskUnitReanalysisIntegrityError("Task 263.7.0 changed during additive reanalysis")
    return report, manifest
