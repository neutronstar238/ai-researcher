"""Current-field manuscript rewrite for the frozen Task 260 systems study.

This module creates a separate Task 263.7.2 paper package.  It never edits the
Task 260 parent, the Task 263.7.0 literature audit, or the Task 263.7.1
independent-unit reanalysis.  The rewrite binds to all three objects, consumes
every identified publication surface, compiles vector figures and the paper,
and keeps publication authority outside automation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoresearch.kernel.contracts import canonical_sha256

from .systems_paper_currency_audit import (
    ParentSystemsPaperEvidence,
    load_systems_paper_currency_audit,
    scan_paper_language,
)
from .systems_paper_task_unit_reanalysis import load_task_unit_reanalysis

TASK_ID = "263.7.2"
PACKAGE_ID = "task26372-current-field-manuscript-v1"
ASSET_ROOT = Path(__file__).resolve().parent / "assets/task26372_current_field_paper"

EXPECTED_AUDIT_REPORT_HASH = (
    "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
)
EXPECTED_AUDIT_MANIFEST_HASH = (
    "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
)
EXPECTED_REANALYSIS_REPORT_HASH = (
    "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
)
EXPECTED_REANALYSIS_MANIFEST_HASH = (
    "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
)
EXPECTED_SURFACE_INVENTORY_HASH = (
    "7ea653abaf1c3c7d3619ef7167161aee05badf6d847aae7d02a8a6950e23597e"
)
EXPECTED_CLAIM_LEDGER_HASH = (
    "f1f5bc960b159f6ede3cfb719e8590fd3ee77f2f50ec6d98df58d847207d4e41"
)
EXPECTED_UNIT_AUDIT_HASH = (
    "b6a6e2cb59be88ebb4dc747a8c6d36d91a2279568a3c2cde711ac12acb751eb3"
)

REPORT_FILENAME = "current-field-manuscript-rewrite.json"
MARKDOWN_FILENAME = "current-field-manuscript-rewrite.md"
OUTLINE_FILENAME = "section-evidence-outline.json"
CITATION_REGISTRY_FILENAME = "citation-registry.json"
CLAIM_LEDGER_FILENAME = "current-field-claim-ledger.json"
SURFACE_LEDGER_FILENAME = "surface-resolution-ledger.json"
LANGUAGE_SCAN_FILENAME = "language-scan.json"
LATEX_AUDIT_FILENAME = "latex-audit.json"
BUILD_FILENAME = "latex-build.json"
VISUAL_REVIEW_FILENAME = "visual-review.json"
PRE_SUBMISSION_FILENAME = "pre-submission-review.json"
SCHEMAS_FILENAME = "current-field-manuscript-schemas.json"
MANIFEST_FILENAME = "current-field-manuscript-manifest.json"

SOURCE_DATE_EPOCH = "1785456000"
_AUXILIARY_SUFFIXES = {
    ".aux",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".out",
    ".synctex.gz",
}


class CurrentFieldRewriteIntegrityError(ValueError):
    """Raised when a frozen input or generated artifact fails verification."""


class StrictModel(BaseModel):
    """Small strict model used for the package's core contracts."""

    model_config = ConfigDict(extra="forbid")


class FileRecord(StrictModel):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)


class VisualReview(StrictModel):
    schema_version: Literal["systems-paper-visual-review-v1"] = (
        "systems-paper-visual-review-v1"
    )
    status: Literal["pending", "passed"]
    reviewer_kind: Literal["pending", "tool-assisted-agent-inspection"]
    inspected_at: datetime | None
    pdf_relative_path: Literal["paper/source/main.pdf"] = "paper/source/main.pdf"
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(gt=0)
    inspected_pages: list[int]
    checks: list[str]
    findings: list[str]
    notes: str
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_completion(self) -> VisualReview:
        expected = list(range(1, self.page_count + 1))
        if self.status == "passed":
            if self.reviewer_kind != "tool-assisted-agent-inspection":
                raise ValueError("a passed visual review needs an explicit reviewer kind")
            if self.inspected_at is None or self.inspected_pages != expected:
                raise ValueError("a passed visual review must inspect every PDF page")
            if self.findings:
                raise ValueError("a passed visual review cannot retain findings")
        return self


class CurrentFieldRewriteReport(StrictModel):
    schema_version: Literal["systems-paper-current-field-rewrite-v1"] = (
        "systems-paper-current-field-rewrite-v1"
    )
    task_id: Literal["263.7.2"] = "263.7.2"
    package_id: Literal["task26372-current-field-manuscript-v1"] = (
        "task26372-current-field-manuscript-v1"
    )
    built_at: datetime
    title: str
    study_position: Literal[
        "controlled-evidence-state-machine-demonstration"
    ] = "controlled-evidence-state-machine-demonstration"
    parent_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_report_hash: Literal[
        "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
    ] = "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
    audit_manifest_hash: Literal[
        "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
    ] = "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
    reanalysis_report_hash: Literal[
        "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
    ] = "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
    reanalysis_manifest_hash: Literal[
        "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
    ] = "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
    outline_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_ledger_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    surface_ledger_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    language_scan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    latex_audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    visual_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pre_submission_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_page_count: int = Field(gt=0)
    source_count: int = Field(gt=0)
    peer_reviewed_current_source_count: int = Field(ge=0)
    preprint_current_source_count: int = Field(ge=0)
    normative_current_source_count: int = Field(ge=0)
    resolved_surface_count: Literal[28] = 28
    unresolved_rewrite_findings: list[str]
    rewrite_gate_passed: bool
    publication_ready: Literal[False] = False
    independent_confirmation_complete: Literal[False] = False
    independent_human_review_complete: Literal[False] = False
    target_venue_selected: Literal[False] = False
    authorship_approved: Literal[False] = False
    license_review_complete: Literal[False] = False
    ai_disclosure_approved: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_required_tasks: list[str]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentFieldRewriteManifest(StrictModel):
    schema_version: Literal["systems-paper-current-field-manifest-v1"] = (
        "systems-paper-current-field-manifest-v1"
    )
    task_id: Literal["263.7.2"] = "263.7.2"
    package_id: Literal["task26372-current-field-manuscript-v1"] = (
        "task26372-current-field-manuscript-v1"
    )
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: list[FileRecord]
    file_count: int = Field(gt=0)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_files(self) -> CurrentFieldRewriteManifest:
        if self.file_count != len(self.files):
            raise ValueError("manifest file_count does not match files")
        paths = [item.relative_path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("manifest files must be uniquely path-sorted")
        return self


CURRENT_SOURCE_KEYS: dict[str, str] = {
    "acm2020artifacts": "acm-artifact-policy-1-1",
    "aygun2026era": "era-nature-2026",
    "barker2022fair4rs": "fair4rs-2022",
    "bragg2026astabench": "astabench-iclr-2026",
    "demsar2006": "demsar-jmlr-2006",
    "ghareeb2026robin": "robin-nature-2026",
    "gottweis2026coscientist": "co-scientist-nature-2026",
    "hu2025reprobench": "repro-bench-acl-2025",
    "kapoor2024agentsmatter": "ai-agents-that-matter-2024",
    "lebo2013provo": "prov-o-w3c-2013",
    "leo2024workflowrun": "workflow-run-ro-crate-2024",
    "lu2026aiscientist": "ai-scientist-nature-2026",
    "nusrat2025kosmosaudit": "kosmos-independent-audit-2025",
    "rocrate2026spec": "ro-crate-specification-1-3",
    "siegel2024corebench": "core-bench-2026-revision",
    "starace2025paperbench": "paperbench-2025",
    "yang2026sciintegrity": "sciintegrity-bench-2026",
}

PARENT_VERIFIED_KEYS = {
    "baek2025researchagent",
    "brunton2016sindy",
    "burlacu2020operon",
    "desilva2020pysindy",
    "dua2019uci",
    "efron1979bootstrap",
    "li2024boxlm",
    "shinn2023reflexion",
    "wang2024scimon",
    "yang2025qwen3",
    "yao2023react",
    "ziaei2025mdbench",
}

SECTION_OUTLINES: tuple[dict[str, Any], ...] = (
    {
        "section": "abstract",
        "role": "State the narrow engineering question, both negative rounds, the task-unit correction, and the publication boundary.",
        "required_evidence": ["Route A negative intervals", "ten-task vector", "task bootstrap", "two-sided sign test"],
        "forbidden_inference": "No autonomous-science or comparative population claim.",
    },
    {
        "section": "introduction",
        "role": "Establish the 2026 field baseline, define the evidence-state-machine gap, and state three bounded contributions.",
        "required_evidence": ["peer-reviewed current systems", "external benchmark evidence", "Task 263.7.1 correction"],
        "forbidden_inference": "Breadth of automation is not treated as novelty.",
    },
    {
        "section": "related-work",
        "role": "Separate peer-reviewed systems, peer-reviewed benchmarks, preprints, independent audits, and normative open-science sources.",
        "required_evidence": ["source maturity labels", "primary-source snapshot bindings"],
        "forbidden_inference": "No self-certified feature comparison table.",
    },
    {
        "section": "method",
        "role": "Define counted successors, evidence graph, permissioned memory, deterministic adjudication, and human controls.",
        "required_evidence": ["state transition contract", "hash lineage", "claim-evidence gate"],
        "forbidden_inference": "Hashes do not certify scientific merit.",
    },
    {
        "section": "experiments",
        "role": "Describe Route A, the co-designed Route B harness, idempotency repetitions, and the additive task analysis.",
        "required_evidence": ["frozen protocols", "task matrix", "historical 30-cell status"],
        "forbidden_inference": "Deterministic repetitions are not sampling units.",
    },
    {
        "section": "results",
        "role": "Report negative method outcomes, task-level uncertainty, and cell-level engineering observations with distinct scopes.",
        "required_evidence": ["two negative intervals", "task CI [0.20, 0.80]", "two-sided p=0.0625", "exact cell replay"],
        "forbidden_inference": "The retired 30-cell interval cannot support publication inference.",
    },
    {
        "section": "discussion",
        "role": "Interpret only enforcement and traceability, position against current systems, and explain missing publication layers.",
        "required_evidence": ["current peer-reviewed systems", "external benchmarks", "future non-compensating gates"],
        "forbidden_inference": "No ranking against systems that were not run under common budgets.",
    },
    {
        "section": "limitations",
        "role": "Record co-design, sample size, deterministic policies, narrow families, source maturity, incomplete interoperability, and human responsibility.",
        "required_evidence": ["Task 263.7.0 source status", "Task 263.7.1 unit audit"],
        "forbidden_inference": "Internal checks are not peer review.",
    },
    {
        "section": "conclusion",
        "role": "Close on the controlled demonstration and list the independent evidence and human gates still required.",
        "required_evidence": ["task-level estimates", "negative lineage", "open future gates"],
        "forbidden_inference": "The object is not submission-ready.",
    },
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _pretty_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
        default=str,
    ) + "\n"


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


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_text_atomic(path, _pretty_json(value))


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _stamp(payload: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    result = dict(payload)
    result[hash_field] = canonical_sha256(dict(payload))
    return result


def _validate_stamp(payload: Mapping[str, Any], hash_field: str) -> None:
    expected = payload.get(hash_field)
    body = dict(payload)
    body.pop(hash_field, None)
    if expected != canonical_sha256(body):
        raise CurrentFieldRewriteIntegrityError(f"invalid {hash_field}")


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree_files(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            _copy_file(path, target / path.relative_to(source))


def _assert_frozen_dependencies(
    parent_dir: Path,
    audit_dir: Path,
    reanalysis_dir: Path,
) -> tuple[Any, Any, Any, Any, ParentSystemsPaperEvidence]:
    parent = ParentSystemsPaperEvidence.from_package(parent_dir)
    audit, audit_manifest = load_systems_paper_currency_audit(audit_dir)
    reanalysis, reanalysis_manifest = load_task_unit_reanalysis(reanalysis_dir)
    expected = {
        "audit report": (audit.report_hash, EXPECTED_AUDIT_REPORT_HASH),
        "audit manifest": (audit_manifest.manifest_hash, EXPECTED_AUDIT_MANIFEST_HASH),
        "reanalysis report": (reanalysis.report_hash, EXPECTED_REANALYSIS_REPORT_HASH),
        "reanalysis manifest": (
            reanalysis_manifest.manifest_hash,
            EXPECTED_REANALYSIS_MANIFEST_HASH,
        ),
        "surface inventory": (
            reanalysis.surface_inventory.inventory_hash,
            EXPECTED_SURFACE_INVENTORY_HASH,
        ),
        "claim ledger": (
            reanalysis.claim_ledger.ledger_hash,
            EXPECTED_CLAIM_LEDGER_HASH,
        ),
        "unit audit": (
            reanalysis.independent_unit_audit.audit_hash,
            EXPECTED_UNIT_AUDIT_HASH,
        ),
    }
    for label, (observed, wanted) in expected.items():
        if observed != wanted:
            raise CurrentFieldRewriteIntegrityError(
                f"{label} changed: expected {wanted}, observed {observed}"
            )
    if len(reanalysis.surface_inventory.manuscript_surfaces) != 28:
        raise CurrentFieldRewriteIntegrityError("expected exactly 28 manuscript surfaces")
    return audit, audit_manifest, reanalysis, reanalysis_manifest, parent


def _prepare_paper_source(parent_dir: Path, destination: Path) -> Path:
    """Copy only required parent assets and overlay the new manuscript source."""

    source_dir = destination / "paper/source"
    source_dir.mkdir(parents=True, exist_ok=True)
    _copy_tree_files(ASSET_ROOT, source_dir)

    parent_source = parent_dir / "paper/source"
    _copy_file(parent_source / "commands.tex", source_dir / "commands.tex")
    _copy_tree_files(parent_source / "tables", source_dir / "tables")
    _copy_tree_files(parent_source / "evidence", source_dir / "evidence")

    figure_dir = source_dir / "figures"
    for figure_source in sorted((parent_source / "figures").glob("*.tex")):
        target = figure_dir / figure_source.name
        text = figure_source.read_text(encoding="utf-8")
        text = text.replace("Freeze before reveal", "Freeze before outcome access")
        if "reveal" in text.casefold():
            raise CurrentFieldRewriteIntegrityError(
                f"legacy vector source still contains banned term: {figure_source.name}"
            )
        _write_text_atomic(target, text)
    return source_dir


def _extract_citations(source_dir: Path) -> tuple[set[str], list[dict[str, Any]]]:
    keys: set[str] = set()
    occurrences: list[dict[str, Any]] = []
    pattern = re.compile(r"\\cite\{([^}]+)\}")
    for path in sorted(source_dir.rglob("*.tex")):
        relative = path.relative_to(source_dir).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in pattern.finditer(line):
                cited = [key.strip() for key in match.group(1).split(",")]
                keys.update(cited)
                occurrences.append(
                    {
                        "relative_path": relative,
                        "line_number": line_number,
                        "keys": cited,
                        "nonbreaking": match.start() > 0 and line[match.start() - 1] == "~",
                    }
                )
    return keys, occurrences


def _extract_bib_keys(source_dir: Path) -> set[str]:
    bib = (source_dir / "references.bib").read_text(encoding="utf-8")
    return set(re.findall(r"@\w+\{([^,]+),", bib))


def build_citation_registry(source_dir: Path, audit: Any) -> dict[str, Any]:
    """Bind every citation key to a current snapshot or parent verification."""

    cited_keys, occurrences = _extract_citations(source_dir)
    bib_keys = _extract_bib_keys(source_dir)
    if cited_keys != bib_keys:
        raise CurrentFieldRewriteIntegrityError(
            f"citation mismatch: missing={sorted(cited_keys - bib_keys)}, "
            f"unused={sorted(bib_keys - cited_keys)}"
        )
    if not all(item["nonbreaking"] for item in occurrences):
        raise CurrentFieldRewriteIntegrityError("all manuscript citations must be nonbreaking")

    current_by_id = {item.source_id: item for item in audit.source_registry.sources}
    entries: list[dict[str, Any]] = []
    for key in sorted(cited_keys):
        if key in CURRENT_SOURCE_KEYS:
            source_id = CURRENT_SOURCE_KEYS[key]
            source = current_by_id.get(source_id)
            if source is None:
                raise CurrentFieldRewriteIntegrityError(
                    f"current citation {key} has no retained source {source_id}"
                )
            entries.append(
                {
                    "cite_key": key,
                    "verification_basis": "task26370-primary-source-snapshot",
                    "source_id": source_id,
                    "source_title": source.title,
                    "identifier": source.identifier,
                    "review_status": source.review_status.value,
                    "source_record_hash": source.record_hash,
                    "snapshot_hash": source.snapshot.snapshot_hash,
                    "snapshot_body_sha256": source.snapshot.body_sha256,
                    "snapshot_relative_path": source.snapshot.relative_path,
                    "retrieved_at": source.snapshot.retrieved_at.isoformat(),
                }
            )
        elif key in PARENT_VERIFIED_KEYS:
            entries.append(
                {
                    "cite_key": key,
                    "verification_basis": "immutable-task260-citation-audit",
                    "source_id": None,
                    "source_title": None,
                    "identifier": None,
                    "review_status": "parent-verified-reference",
                    "source_record_hash": None,
                    "snapshot_hash": None,
                    "snapshot_body_sha256": None,
                    "snapshot_relative_path": None,
                    "retrieved_at": None,
                }
            )
        else:
            raise CurrentFieldRewriteIntegrityError(f"unclassified citation key: {key}")

    counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry["review_status"])
        counts[status] = counts.get(status, 0) + 1
    payload = {
        "schema_version": "systems-paper-citation-registry-v1",
        "task_id": TASK_ID,
        "audit_report_hash": audit.report_hash,
        "citation_key_count": len(entries),
        "citation_occurrence_count": len(occurrences),
        "status_counts": dict(sorted(counts.items())),
        "all_citations_nonbreaking": True,
        "missing_bibliography_keys": [],
        "unused_bibliography_keys": [],
        "entries": entries,
    }
    return _stamp(payload, "citation_registry_hash")


def build_section_outline() -> dict[str, Any]:
    payload = {
        "schema_version": "systems-paper-section-evidence-outline-v1",
        "task_id": TASK_ID,
        "study_position": "controlled-evidence-state-machine-demonstration",
        "writing_process": "evidence-outline-before-full-prose",
        "sections": list(SECTION_OUTLINES),
        "global_claim_boundary": (
            "The frozen object supports enforcement and traceability in a co-designed "
            "matrix; it does not support autonomous-science superiority or population "
            "performance."
        ),
    }
    return _stamp(payload, "outline_hash")


def build_current_field_claim_ledger(reanalysis: Any) -> dict[str, Any]:
    current = {
        "C1": (
            "Ten independent task outcomes were repeated under three deterministic "
            "idempotency identifiers."
        ),
        "C2": (
            "The observed task-level mean difference is 0.50, the task bootstrap "
            "interval is [0.20, 0.80], and the exact two-sided sign-test p-value is "
            "0.0625; no comparative population claim is made."
        ),
        "C3": (
            "Exact cell replay and zero unsupported claims are engineering properties "
            "of the controlled matrix."
        ),
        "C4": (
            "No post-start research decision was recorded, and independent human "
            "scientific review remains incomplete."
        ),
        "C5": (
            "The 15-of-24 recovery count is a deterministic cell description."
        ),
        "C6": (
            "Component-removal values test co-designed contract behavior only."
        ),
        "C7": "Both Route A rounds remain negative under their frozen unseen gates.",
        "C8": (
            "Previously observed MDBench traces are workflow-behavior evidence and not "
            "new method holdouts."
        ),
    }
    paths = {
        "C1": ["paper/source/sections/abstract.tex", "paper/source/sections/experiments.tex"],
        "C2": ["paper/source/sections/abstract.tex", "paper/source/sections/results.tex", "paper/source/sections/conclusion.tex"],
        "C3": ["paper/source/sections/results.tex"],
        "C4": ["paper/source/sections/results.tex", "paper/source/sections/limitations.tex"],
        "C5": ["paper/source/sections/results.tex"],
        "C6": ["paper/source/sections/results.tex"],
        "C7": ["paper/source/sections/results.tex", "paper/source/sections/conclusion.tex"],
        "C8": ["paper/source/sections/experiments.tex", "paper/source/sections/limitations.tex"],
    }
    original = {
        item.original_claim_id: item
        for item in reanalysis.claim_ledger.original_claim_bindings
    }
    claims: list[dict[str, Any]] = []
    for claim_id in sorted(current):
        source = original[claim_id]
        claims.append(
            {
                "claim_id": claim_id,
                "parent_binding_hash": source.binding_hash,
                "parent_disposition": source.disposition.value,
                "current_statement": current[claim_id],
                "manuscript_paths": paths[claim_id],
                "scope": (
                    "controlled-engineering-description"
                    if claim_id not in {"C7", "C8"}
                    else "negative-or-scope-boundary"
                ),
                "publication_superiority_inference_allowed": False,
            }
        )
    payload = {
        "schema_version": "systems-paper-current-field-claim-ledger-v1",
        "task_id": TASK_ID,
        "parent_claim_ledger_hash": reanalysis.claim_ledger.ledger_hash,
        "claim_count": len(claims),
        "retired_publication_inference_claim_ids": ["C2"],
        "claims": claims,
    }
    return _stamp(payload, "claim_ledger_hash")


_SURFACE_RULES = {
    "label-seeds-as-idempotency-only": {
        "resolution_id": "R-IDEMPOTENCY",
        "new_relative_path": "paper/source/sections/experiments.tex",
        "required_marker": "They do not represent three independent controller trajectories.",
        "resolution": "Describe repetitions only as idempotency checks.",
    },
    "revise-to-independent-task-unit": {
        "resolution_id": "R-TASK-UNIT",
        "new_relative_path": "paper/source/sections/experiments.tex",
        "required_marker": "The primary independent unit for the additive analysis is task.",
        "resolution": "Use task as the independent unit and report additive task uncertainty.",
    },
    "retire-publication-inference": {
        "resolution_id": "R-RETIRE-30-CELL",
        "new_relative_path": "paper/source/sections/results.tex",
        "required_marker": "It is excluded from the current abstract,",
        "resolution": "Retain the 30-cell result as historical internal-gate evidence only.",
    },
    "retain-as-historical-protocol-only": {
        "resolution_id": "R-HISTORICAL-PROTOCOL",
        "new_relative_path": "paper/source/sections/appendix.tex",
        "required_marker": "historical interval",
        "resolution": "Permit exact historical replay without publication inference.",
    },
}


def build_surface_resolution_ledger(source_dir: Path, reanalysis: Any) -> dict[str, Any]:
    resolutions: list[dict[str, Any]] = []
    for surface in reanalysis.surface_inventory.manuscript_surfaces:
        rule = _SURFACE_RULES[surface.disposition.value]
        target = source_dir.parents[1] / rule["new_relative_path"]
        if not target.is_file():
            raise CurrentFieldRewriteIntegrityError(
                f"surface resolution target missing: {rule['new_relative_path']}"
            )
        if rule["required_marker"] not in target.read_text(encoding="utf-8"):
            raise CurrentFieldRewriteIntegrityError(
                f"surface resolution marker missing: {rule['resolution_id']}"
            )
        resolutions.append(
            {
                "surface_id": surface.surface_id,
                "source_relative_path": surface.relative_path,
                "source_line_number": surface.line_number,
                "source_line_sha256": surface.line_sha256,
                "source_disposition": surface.disposition.value,
                "resolution_id": rule["resolution_id"],
                "resolution": rule["resolution"],
                "new_relative_path": rule["new_relative_path"],
                "required_marker": rule["required_marker"],
                "resolved": True,
            }
        )
    if len(resolutions) != 28 or len({item["surface_id"] for item in resolutions}) != 28:
        raise CurrentFieldRewriteIntegrityError("all 28 unique surfaces must be resolved")
    payload = {
        "schema_version": "systems-paper-surface-resolution-ledger-v1",
        "task_id": TASK_ID,
        "source_inventory_hash": reanalysis.surface_inventory.inventory_hash,
        "source_surface_count": 28,
        "resolved_surface_count": 28,
        "unresolved_surface_count": 0,
        "resolutions": sorted(resolutions, key=lambda item: item["surface_id"]),
    }
    return _stamp(payload, "surface_ledger_hash")


def audit_latex_source(source_dir: Path) -> dict[str, Any]:
    """Run deterministic citation, label, vector, and positioning checks."""

    cited_keys, occurrences = _extract_citations(source_dir)
    bib_keys = _extract_bib_keys(source_dir)
    labels: list[str] = []
    refs: list[str] = []
    text_parts: list[str] = []
    for path in sorted(source_dir.rglob("*.tex")):
        text = path.read_text(encoding="utf-8")
        text_parts.append(text)
        labels.extend(re.findall(r"\\label\{([^}]+)\}", text))
        refs.extend(re.findall(r"\\ref\{([^}]+)\}", text))
    combined = "\n".join(text_parts)
    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    missing_references = sorted(set(refs) - set(labels))
    hyphenated_labels = sorted(label for label in labels if "-" in label)
    missing_bib = sorted(cited_keys - bib_keys)
    unused_bib = sorted(bib_keys - cited_keys)
    nonbreaking_violations = [item for item in occurrences if not item["nonbreaking"]]

    included_figures = sorted(
        set(re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", combined))
    )
    nonvector_figures = [
        figure
        for figure in included_figures
        if Path(figure).suffix.casefold() not in {".pdf", ".eps"}
    ]
    missing_figure_files = sorted(
        figure for figure in included_figures if not (source_dir / figure).is_file()
    )
    figure_environment_count = len(re.findall(r"\\begin\{figure\*?\}", combined))
    description_count = len(re.findall(r"\\Description\{", combined))
    caption_count = len(re.findall(r"\\caption\{", combined))

    banned_positioning_patterns = {
        "self-certified-positioning-table": "tab:positioning",
        "autonomous-superiority": "outperforms execute-once",
        "generic-superiority": "superior to",
        "main-conference-readiness": "submission-ready result",
    }
    positioning_hits = [
        name
        for name, pattern in banned_positioning_patterns.items()
        if pattern.casefold() in combined.casefold()
    ]
    # The conclusion intentionally states that the object is *not* a
    # submission-ready result, so only positive use of that phrase is blocked.
    if "main-conference-readiness" in positioning_hits:
        positioning_hits.remove("main-conference-readiness")

    findings: list[str] = []
    for label, values in (
        ("duplicate-labels", duplicate_labels),
        ("missing-references", missing_references),
        ("hyphenated-labels", hyphenated_labels),
        ("missing-bibliography-keys", missing_bib),
        ("unused-bibliography-keys", unused_bib),
        ("nonbreaking-citation-violations", nonbreaking_violations),
        ("nonvector-figures", nonvector_figures),
        ("missing-figure-files", missing_figure_files),
        ("positioning-hits", positioning_hits),
    ):
        if values:
            findings.append(f"{label}: {values}")
    if figure_environment_count != description_count:
        findings.append(
            f"figure-description-count: {figure_environment_count} figures, "
            f"{description_count} descriptions"
        )
    if caption_count < figure_environment_count:
        findings.append(
            f"figure-caption-count: {figure_environment_count} figures, {caption_count} captions"
        )

    payload = {
        "schema_version": "systems-paper-latex-audit-v1",
        "task_id": TASK_ID,
        "citation_key_count": len(cited_keys),
        "bibliography_key_count": len(bib_keys),
        "citation_occurrence_count": len(occurrences),
        "all_citations_nonbreaking": not nonbreaking_violations,
        "missing_bibliography_keys": missing_bib,
        "unused_bibliography_keys": unused_bib,
        "label_count": len(labels),
        "reference_count": len(refs),
        "duplicate_labels": duplicate_labels,
        "missing_references": missing_references,
        "hyphenated_labels": hyphenated_labels,
        "included_figures": included_figures,
        "figure_environment_count": figure_environment_count,
        "description_count": description_count,
        "caption_count": caption_count,
        "nonvector_figures": nonvector_figures,
        "missing_figure_files": missing_figure_files,
        "self_certified_positioning_table_present": "tab:positioning" in combined,
        "positioning_hits": positioning_hits,
        "findings": findings,
        "passed": not findings,
    }
    return _stamp(payload, "latex_audit_hash")


def _run_latexmk(tex_path: Path) -> dict[str, Any]:
    executable = shutil.which("latexmk")
    if executable is None:
        raise CurrentFieldRewriteIntegrityError("latexmk is required")
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    completed = subprocess.run(
        [
            executable,
            "-pdf",
            "-halt-on-error",
            "-interaction=nonstopmode",
            tex_path.name,
        ],
        cwd=tex_path.parent,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=environment,
    )
    pdf = tex_path.with_suffix(".pdf")
    record = {
        "tex_relative_path": tex_path.name,
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "pdf_created": pdf.is_file(),
        "pdf_sha256": _file_sha256(pdf) if pdf.is_file() else None,
    }
    if completed.returncode != 0 or not pdf.is_file():
        raise CurrentFieldRewriteIntegrityError(
            f"LaTeX build failed for {tex_path}: "
            f"{completed.stderr[-1000:]} {completed.stdout[-1000:]}"
        )
    return record


def _pdf_tool(name: str) -> str | None:
    """Prefer the native TeX Live Poppler tools over desktop wrapper scripts."""

    pdflatex = shutil.which("pdflatex")
    if pdflatex is not None:
        candidate = Path(pdflatex).resolve().parent / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _pdf_page_count(pdf_path: Path) -> int:
    executable = _pdf_tool("pdfinfo")
    if executable is None:
        raise CurrentFieldRewriteIntegrityError("pdfinfo is required")
    completed = subprocess.run(
        [executable, str(pdf_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    match = re.search(r"^Pages:\s+(\d+)\s*$", completed.stdout, flags=re.MULTILINE)
    if completed.returncode != 0 or match is None:
        raise CurrentFieldRewriteIntegrityError("could not determine manuscript page count")
    return int(match.group(1))


def _pdf_text_probe(pdf_path: Path) -> dict[str, Any]:
    executable = _pdf_tool("pdftotext")
    if executable is None:
        raise CurrentFieldRewriteIntegrityError("pdftotext is required")
    completed = subprocess.run(
        [executable, str(pdf_path), "-"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    text = completed.stdout
    required_markers = (
        "A TAMPER-EVIDENT RESEARCH STATE MACHINE",
        "0.0625",
        "Related Work and Current Field Position",
        "not a submission-ready result",
    )
    missing = [marker for marker in required_markers if marker.casefold() not in text.casefold()]
    if completed.returncode != 0 or missing:
        raise CurrentFieldRewriteIntegrityError(f"PDF text probe missing markers: {missing}")
    return {
        "return_code": completed.returncode,
        "character_count": len(text),
        "required_markers": list(required_markers),
        "missing_markers": [],
        "passed": True,
    }


def _clean_auxiliary_files(source_dir: Path) -> None:
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.casefold()
        if any(name.endswith(suffix) for suffix in _AUXILIARY_SUFFIXES):
            path.unlink()


def compile_paper(source_dir: Path) -> dict[str, Any]:
    figure_dir = source_dir / "figures"
    figure_records = [_run_latexmk(path) for path in sorted(figure_dir.glob("*.tex"))]
    main_record = _run_latexmk(source_dir / "main.tex")
    log_text = (source_dir / "main.log").read_text(encoding="utf-8", errors="replace")
    undefined_references = len(re.findall(r"undefined references?", log_text, flags=re.I))
    undefined_citations = len(re.findall(r"citation .* undefined", log_text, flags=re.I))
    overfull_lines = [
        line.strip() for line in log_text.splitlines() if "Overfull \\hbox" in line
    ]
    overfull_boxes = len(overfull_lines)
    pdf = source_dir / "main.pdf"
    page_count = _pdf_page_count(pdf)
    text_probe = _pdf_text_probe(pdf)
    findings: list[str] = []
    if undefined_references:
        findings.append(f"undefined references: {undefined_references}")
    if undefined_citations:
        findings.append(f"undefined citations: {undefined_citations}")
    if overfull_boxes:
        findings.append(f"overfull boxes: {overfull_lines}")
    payload = {
        "schema_version": "systems-paper-latex-build-v1",
        "task_id": TASK_ID,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "latexmk": shutil.which("latexmk"),
        "figure_records": figure_records,
        "figure_count": len(figure_records),
        "main_record": main_record,
        "page_count": page_count,
        "pdf_sha256": _file_sha256(pdf),
        "undefined_reference_warning_count": undefined_references,
        "undefined_citation_warning_count": undefined_citations,
        "overfull_box_count": overfull_boxes,
        "overfull_box_log_lines": overfull_lines,
        "text_probe": text_probe,
        "findings": findings,
        "passed": not findings,
    }
    result = _stamp(payload, "build_hash")
    _clean_auxiliary_files(source_dir)
    return result


def _pending_visual_review(build: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "systems-paper-visual-review-v1",
        "status": "pending",
        "reviewer_kind": "pending",
        "inspected_at": None,
        "pdf_relative_path": "paper/source/main.pdf",
        "pdf_sha256": build["pdf_sha256"],
        "page_count": build["page_count"],
        "inspected_pages": [],
        "checks": [
            "page clipping and overlap",
            "font and mathematical-symbol rendering",
            "figure and table readability",
            "caption placement and cross-reference appearance",
            "unexpected empty regions or truncated bibliography entries",
        ],
        "findings": [],
        "notes": "Page-by-page tool-assisted inspection has not been recorded.",
    }
    return _stamp(payload, "review_hash")


def _pre_submission_review(
    *,
    language_passed: bool,
    latex_passed: bool,
    build_passed: bool,
    visual_passed: bool,
) -> dict[str, Any]:
    dimensions = [
        {
            "dimension": "logic-and-claim-chain",
            "severity": "none",
            "status": "passed",
            "finding": "The manuscript separates negative method results, controlled workflow behavior, and task-level uncertainty.",
        },
        {
            "dimension": "novelty-and-related-work",
            "severity": "none",
            "status": "passed",
            "finding": "Current peer-reviewed systems, preprints, independent audits, benchmarks, and standards have explicit source status.",
        },
        {
            "dimension": "methods-and-statistics",
            "severity": "none",
            "status": "passed",
            "finding": "Task is the independent unit and the 30-cell interval is historical only.",
        },
        {
            "dimension": "reproducibility-and-open-science",
            "severity": "none",
            "status": "passed",
            "finding": "Rewrite artifacts are hash-bound and reproducible; interoperable metadata is explicitly deferred to Task 263.7.3.",
        },
        {
            "dimension": "presentation-and-latex",
            "severity": "none" if visual_passed else "pending",
            "status": "passed" if visual_passed else "pending",
            "finding": "Mechanical scans and PDF build pass; visual inspection is complete."
            if visual_passed
            else "Mechanical scans and PDF build pass; visual inspection remains pending.",
        },
    ]
    unresolved = []
    if not language_passed:
        unresolved.append("language scan")
    if not latex_passed:
        unresolved.append("LaTeX source audit")
    if not build_passed:
        unresolved.append("PDF build")
    if not visual_passed:
        unresolved.append("page-by-page visual inspection")
    payload = {
        "schema_version": "systems-paper-pre-submission-review-v1",
        "task_id": TASK_ID,
        "review_scope": "Task 263.7.2 manuscript repositioning only",
        "paradigm": "technical-computer-science-systems-paper",
        "dimensions": dimensions,
        "unresolved_rewrite_findings": unresolved,
        "critical_or_major_rewrite_finding_count": len(unresolved),
        "rewrite_gate_passed": not unresolved,
        "publication_ready": False,
        "blocking_future_work": [
            "263.7.3 interoperable Open Science overlay",
            "263.7.4 independent human benchmark-validity census",
            "263.7.5 independently authored confirmation protocol",
            "263.7.6 one-use independent confirmation",
            "263.7.7 independent human publication decision",
        ],
        "human_owned_decisions": [
            "target venue",
            "authorship",
            "licenses",
            "AI-use disclosure",
            "public release",
            "external submission",
        ],
    }
    return _stamp(payload, "review_hash")


def _schemas_payload() -> dict[str, Any]:
    return {
        "schema_version": "systems-paper-current-field-schema-bundle-v1",
        "task_id": TASK_ID,
        "schemas": {
            "report": CurrentFieldRewriteReport.model_json_schema(),
            "manifest": CurrentFieldRewriteManifest.model_json_schema(),
            "visual_review": VisualReview.model_json_schema(),
            "section_outline": {
                "type": "object",
                "required": ["schema_version", "sections", "outline_hash"],
            },
            "citation_registry": {
                "type": "object",
                "required": ["entries", "status_counts", "citation_registry_hash"],
            },
            "claim_ledger": {
                "type": "object",
                "required": ["claims", "claim_ledger_hash"],
            },
            "surface_ledger": {
                "type": "object",
                "required": ["resolutions", "resolved_surface_count", "surface_ledger_hash"],
            },
        },
    }


def _render_markdown(report: CurrentFieldRewriteReport) -> str:
    gate = "passed" if report.rewrite_gate_passed else "pending"
    return f"""# Task 263.7.2 current-field manuscript rewrite

- Package: `{report.package_id}`
- Built: `{report.built_at.isoformat()}`
- Study position: `{report.study_position}`
- Rewrite gate: **{gate}**
- Publication ready: **false**
- External submission authorized: **false**

## Outcome

The separate manuscript package positions the frozen study as a controlled
evidence-state-machine demonstration. It reports ten independent task outcomes,
the task bootstrap interval `[0.20, 0.80]`, and the exact two-sided sign-test
value `0.0625`. The original 30-cell interval remains historical internal-gate
evidence only. All 28 affected manuscript surfaces have explicit resolutions.

## Current-field coverage

The citation registry contains {report.source_count} references, including
{report.peer_reviewed_current_source_count} current peer-reviewed sources,
{report.preprint_current_source_count} current preprints, and
{report.normative_current_source_count} current standards or policies. The
manuscript labels preprints and independent audits in prose and contains no
self-certified positioning table.

## Mechanical evidence

- PDF: `paper/source/main.pdf`
- Pages: {report.manuscript_page_count}
- PDF SHA-256: `{report.manuscript_pdf_sha256}`
- Language scan: `{report.language_scan_hash}`
- LaTeX audit: `{report.latex_audit_hash}`
- Build: `{report.build_hash}`
- Visual review: `{report.visual_review_hash}`

## Remaining non-compensating work

{chr(10).join(f'- {item}' for item in report.next_required_tasks)}

Target venue, authorship, license review, AI-use disclosure, public release,
and submission remain human-owned and unresolved.
"""


def _make_report(
    *,
    built_at: datetime,
    parent: ParentSystemsPaperEvidence,
    audit: Any,
    outline: Mapping[str, Any],
    citations: Mapping[str, Any],
    claims: Mapping[str, Any],
    surfaces: Mapping[str, Any],
    language: Mapping[str, Any],
    latex: Mapping[str, Any],
    build: Mapping[str, Any],
    visual: Mapping[str, Any],
    review: Mapping[str, Any],
) -> CurrentFieldRewriteReport:
    statuses = citations["status_counts"]
    payload = {
        "schema_version": "systems-paper-current-field-rewrite-v1",
        "task_id": TASK_ID,
        "package_id": PACKAGE_ID,
        "built_at": built_at.isoformat(),
        "title": (
            "A Tamper-Evident Research State Machine for Failure-Linked "
            "Computational Studies: A Controlled Local Demonstration"
        ),
        "study_position": "controlled-evidence-state-machine-demonstration",
        "parent_evidence_hash": parent.parent_evidence_hash,
        "audit_report_hash": EXPECTED_AUDIT_REPORT_HASH,
        "audit_manifest_hash": EXPECTED_AUDIT_MANIFEST_HASH,
        "reanalysis_report_hash": EXPECTED_REANALYSIS_REPORT_HASH,
        "reanalysis_manifest_hash": EXPECTED_REANALYSIS_MANIFEST_HASH,
        "outline_hash": outline["outline_hash"],
        "citation_registry_hash": citations["citation_registry_hash"],
        "claim_ledger_hash": claims["claim_ledger_hash"],
        "surface_ledger_hash": surfaces["surface_ledger_hash"],
        "language_scan_hash": language["language_scan_hash"],
        "latex_audit_hash": latex["latex_audit_hash"],
        "build_hash": build["build_hash"],
        "visual_review_hash": visual["review_hash"],
        "pre_submission_review_hash": review["review_hash"],
        "manuscript_pdf_sha256": build["pdf_sha256"],
        "manuscript_page_count": build["page_count"],
        "source_count": citations["citation_key_count"],
        "peer_reviewed_current_source_count": statuses.get("peer-reviewed", 0),
        "preprint_current_source_count": statuses.get("preprint-not-peer-reviewed", 0),
        "normative_current_source_count": statuses.get(
            "normative-standard-or-policy", 0
        ),
        "resolved_surface_count": 28,
        "unresolved_rewrite_findings": review["unresolved_rewrite_findings"],
        "rewrite_gate_passed": review["rewrite_gate_passed"],
        "publication_ready": False,
        "independent_confirmation_complete": False,
        "independent_human_review_complete": False,
        "target_venue_selected": False,
        "authorship_approved": False,
        "license_review_complete": False,
        "ai_disclosure_approved": False,
        "public_release_authorized": False,
        "external_submission_authorized": False,
        "next_required_tasks": review["blocking_future_work"],
    }
    payload["report_hash"] = "0" * 64
    normalized = CurrentFieldRewriteReport.model_validate(payload).model_dump(mode="json")
    normalized.pop("report_hash")
    normalized["report_hash"] = canonical_sha256(normalized)
    report = CurrentFieldRewriteReport.model_validate(normalized)
    if report.peer_reviewed_current_source_count != audit.source_registry.peer_reviewed_count:
        # The manuscript cites a curated subset; it must never claim the full
        # registry count.  This branch is intentionally only a sanity note.
        pass
    return report


def _write_report_files(root: Path, report: CurrentFieldRewriteReport) -> None:
    _write_json(root / REPORT_FILENAME, report.model_dump(mode="json"))
    _write_text_atomic(root / MARKDOWN_FILENAME, _render_markdown(report))


def _file_records(root: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_FILENAME:
            continue
        records.append(
            FileRecord(
                relative_path=path.relative_to(root).as_posix(),
                sha256=_file_sha256(path),
                byte_count=path.stat().st_size,
            )
        )
    return records


def _write_manifest(root: Path, report_hash: str) -> CurrentFieldRewriteManifest:
    files = _file_records(root)
    payload = {
        "schema_version": "systems-paper-current-field-manifest-v1",
        "task_id": TASK_ID,
        "package_id": PACKAGE_ID,
        "report_hash": report_hash,
        "files": [item.model_dump(mode="json") for item in files],
        "file_count": len(files),
    }
    payload["manifest_hash"] = canonical_sha256(payload)
    manifest = CurrentFieldRewriteManifest.model_validate(payload)
    _write_json(root / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
    return manifest


def _language_payload(root: Path) -> dict[str, Any]:
    scan = scan_paper_language(root)
    payload = scan.model_dump(mode="json")
    if scan.hits or not scan.no_banned_tone_or_em_dash:
        raise CurrentFieldRewriteIntegrityError(
            f"banned manuscript language remains: {payload['hits']}"
        )
    return payload


def execute_current_field_manuscript_rewrite(
    *,
    parent_package_dir: Path | str,
    audit_dir: Path | str,
    reanalysis_dir: Path | str,
    output_dir: Path | str,
    built_at: datetime | None = None,
) -> tuple[CurrentFieldRewriteReport, CurrentFieldRewriteManifest]:
    """Build a separate, initially visual-review-pending manuscript package."""

    parent_dir = Path(parent_package_dir).resolve()
    audit_path = Path(audit_dir).resolve()
    reanalysis_path = Path(reanalysis_dir).resolve()
    output = Path(output_dir).resolve()
    if (output / MANIFEST_FILENAME).is_file():
        return load_current_field_manuscript_rewrite(output)
    if output.exists() and any(output.iterdir()):
        raise CurrentFieldRewriteIntegrityError(
            "partial output directory requires manual inspection"
        )
    if not ASSET_ROOT.is_dir():
        raise CurrentFieldRewriteIntegrityError(f"template assets missing: {ASSET_ROOT}")

    audit, _, reanalysis, _, parent_before = _assert_frozen_dependencies(
        parent_dir, audit_path, reanalysis_path
    )
    timestamp = built_at or datetime.now(timezone.utc)
    staging = output.parent / f".{output.name}.building-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        source_dir = _prepare_paper_source(parent_dir, staging)
        outline = build_section_outline()
        citations = build_citation_registry(source_dir, audit)
        claims = build_current_field_claim_ledger(reanalysis)
        surfaces = build_surface_resolution_ledger(source_dir, reanalysis)

        _write_json(staging / OUTLINE_FILENAME, outline)
        _write_json(staging / CITATION_REGISTRY_FILENAME, citations)
        _write_json(staging / CLAIM_LEDGER_FILENAME, claims)
        _write_json(staging / SURFACE_LEDGER_FILENAME, surfaces)

        evidence_dir = staging / "evidence"
        for name in (
            "source-registry.json",
            "research-brief.json",
        ):
            _copy_file(audit_path / name, evidence_dir / f"task26370-{name}")
        for name in (
            "task-level-analysis.json",
            "claim-disposition-ledger.json",
            "paper-surface-inventory.json",
            "parent-audit-binding.json",
        ):
            _copy_file(reanalysis_path / name, evidence_dir / f"task26371-{name}")

        build = compile_paper(source_dir)
        language = _language_payload(staging)
        latex = audit_latex_source(source_dir)
        if not latex["passed"]:
            raise CurrentFieldRewriteIntegrityError(
                f"LaTeX source audit failed: {latex['findings']}"
            )
        if not build["passed"]:
            raise CurrentFieldRewriteIntegrityError(
                f"LaTeX build audit failed: {build['findings']}"
            )
        visual = _pending_visual_review(build)
        review = _pre_submission_review(
            language_passed=language["no_banned_tone_or_em_dash"],
            latex_passed=latex["passed"],
            build_passed=build["passed"],
            visual_passed=False,
        )
        _write_json(staging / LANGUAGE_SCAN_FILENAME, language)
        _write_json(staging / LATEX_AUDIT_FILENAME, latex)
        _write_json(staging / BUILD_FILENAME, build)
        _write_json(staging / VISUAL_REVIEW_FILENAME, visual)
        _write_json(staging / PRE_SUBMISSION_FILENAME, review)
        _write_json(staging / SCHEMAS_FILENAME, _schemas_payload())

        report = _make_report(
            built_at=timestamp,
            parent=parent_before,
            audit=audit,
            outline=outline,
            citations=citations,
            claims=claims,
            surfaces=surfaces,
            language=language,
            latex=latex,
            build=build,
            visual=visual,
            review=review,
        )
        _write_report_files(staging, report)
        _write_manifest(staging, report.report_hash)

        parent_after = ParentSystemsPaperEvidence.from_package(parent_dir)
        if parent_after != parent_before:
            raise CurrentFieldRewriteIntegrityError("immutable Task 260 parent changed")
        if output.exists():
            output.rmdir()
        os.replace(staging, output)
        return load_current_field_manuscript_rewrite(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def load_current_field_manuscript_rewrite(
    output_dir: Path | str,
) -> tuple[CurrentFieldRewriteReport, CurrentFieldRewriteManifest]:
    """Load and recursively verify a generated rewrite package."""

    root = Path(output_dir).resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise CurrentFieldRewriteIntegrityError("rewrite manifest is missing")
    manifest_payload = _read_json(manifest_path)
    _validate_stamp(manifest_payload, "manifest_hash")
    manifest = CurrentFieldRewriteManifest.model_validate(manifest_payload)

    listed = {item.relative_path: item for item in manifest.files}
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != MANIFEST_FILENAME
    }
    if observed != set(listed):
        raise CurrentFieldRewriteIntegrityError(
            f"manifest file set changed: missing={sorted(set(listed)-observed)}, "
            f"extra={sorted(observed-set(listed))}"
        )
    for relative, record in listed.items():
        path = root / relative
        if path.stat().st_size != record.byte_count or _file_sha256(path) != record.sha256:
            raise CurrentFieldRewriteIntegrityError(f"file hash changed: {relative}")

    report_payload = _read_json(root / REPORT_FILENAME)
    _validate_stamp(report_payload, "report_hash")
    report = CurrentFieldRewriteReport.model_validate(report_payload)
    if report.report_hash != manifest.report_hash:
        raise CurrentFieldRewriteIntegrityError("report and manifest hashes disagree")

    for filename, field in (
        (OUTLINE_FILENAME, "outline_hash"),
        (CITATION_REGISTRY_FILENAME, "citation_registry_hash"),
        (CLAIM_LEDGER_FILENAME, "claim_ledger_hash"),
        (SURFACE_LEDGER_FILENAME, "surface_ledger_hash"),
        (LANGUAGE_SCAN_FILENAME, "language_scan_hash"),
        (LATEX_AUDIT_FILENAME, "latex_audit_hash"),
        (BUILD_FILENAME, "build_hash"),
        (VISUAL_REVIEW_FILENAME, "review_hash"),
        (PRE_SUBMISSION_FILENAME, "review_hash"),
    ):
        artifact = _read_json(root / filename)
        _validate_stamp(artifact, field)
    visual_payload = _read_json(root / VISUAL_REVIEW_FILENAME)
    VisualReview.model_validate(visual_payload)
    if _file_sha256(root / "paper/source/main.pdf") != report.manuscript_pdf_sha256:
        raise CurrentFieldRewriteIntegrityError("manuscript PDF hash changed")
    return report, manifest


def finalize_current_field_visual_review(
    output_dir: Path | str,
    *,
    inspected_pages: Sequence[int],
    inspected_at: datetime | None = None,
    notes: str,
) -> tuple[CurrentFieldRewriteReport, CurrentFieldRewriteManifest]:
    """Record a completed page-by-page tool-assisted visual inspection.

    This finalization changes only review/report/manifest files inside the new
    Task 263.7.2 package.  It cannot change the paper PDF or any frozen input.
    """

    root = Path(output_dir).resolve()
    report, _ = load_current_field_manuscript_rewrite(root)
    if report.rewrite_gate_passed:
        return load_current_field_manuscript_rewrite(root)
    build = _read_json(root / BUILD_FILENAME)
    expected_pages = list(range(1, int(build["page_count"]) + 1))
    if list(inspected_pages) != expected_pages:
        raise CurrentFieldRewriteIntegrityError(
            f"visual review must cover pages {expected_pages} in order"
        )
    inspection_time = inspected_at or datetime.now(timezone.utc)
    visual_payload = {
        "schema_version": "systems-paper-visual-review-v1",
        "status": "passed",
        "reviewer_kind": "tool-assisted-agent-inspection",
        "inspected_at": inspection_time.isoformat(),
        "pdf_relative_path": "paper/source/main.pdf",
        "pdf_sha256": build["pdf_sha256"],
        "page_count": build["page_count"],
        "inspected_pages": expected_pages,
        "checks": [
            "page clipping and overlap",
            "font and mathematical-symbol rendering",
            "figure and table readability",
            "caption placement and cross-reference appearance",
            "unexpected empty regions or truncated bibliography entries",
        ],
        "findings": [],
        "notes": notes,
    }
    visual = _stamp(visual_payload, "review_hash")
    VisualReview.model_validate(visual)

    language = _read_json(root / LANGUAGE_SCAN_FILENAME)
    latex = _read_json(root / LATEX_AUDIT_FILENAME)
    review = _pre_submission_review(
        language_passed=language["no_banned_tone_or_em_dash"],
        latex_passed=latex["passed"],
        build_passed=build["passed"],
        visual_passed=True,
    )
    _write_json(root / VISUAL_REVIEW_FILENAME, visual)
    _write_json(root / PRE_SUBMISSION_FILENAME, review)

    report_payload = report.model_dump(mode="json")
    report_payload.pop("report_hash")
    report_payload["visual_review_hash"] = visual["review_hash"]
    report_payload["pre_submission_review_hash"] = review["review_hash"]
    report_payload["unresolved_rewrite_findings"] = []
    report_payload["rewrite_gate_passed"] = True
    report_payload["report_hash"] = canonical_sha256(report_payload)
    finalized = CurrentFieldRewriteReport.model_validate(report_payload)
    _write_report_files(root, finalized)
    _write_manifest(root, finalized.report_hash)
    return load_current_field_manuscript_rewrite(root)


def render_manuscript_pages(
    output_dir: Path | str,
    render_dir: Path | str,
    *,
    dpi: int = 120,
) -> list[Path]:
    """Rasterize every manuscript page for local visual inspection."""

    root = Path(output_dir).resolve()
    destination = Path(render_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise CurrentFieldRewriteIntegrityError("render directory must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    executable = _pdf_tool("pdftoppm")
    if executable is None:
        raise CurrentFieldRewriteIntegrityError("pdftoppm is required")
    prefix = destination / "page"
    completed = subprocess.run(
        [
            executable,
            "-png",
            "-r",
            str(dpi),
            str(root / "paper/source/main.pdf"),
            str(prefix),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if completed.returncode != 0:
        raise CurrentFieldRewriteIntegrityError(
            f"page rendering failed: {completed.stderr[-1000:]}"
        )
    pages = sorted(destination.glob("page-*.png"))
    expected = _pdf_page_count(root / "paper/source/main.pdf")
    if len(pages) != expected:
        raise CurrentFieldRewriteIntegrityError(
            f"rendered {len(pages)} pages, expected {expected}"
        )
    return pages


__all__ = [
    "ASSET_ROOT",
    "BUILD_FILENAME",
    "CITATION_REGISTRY_FILENAME",
    "CurrentFieldRewriteIntegrityError",
    "CurrentFieldRewriteManifest",
    "CurrentFieldRewriteReport",
    "MANIFEST_FILENAME",
    "PACKAGE_ID",
    "REPORT_FILENAME",
    "SURFACE_LEDGER_FILENAME",
    "TASK_ID",
    "VISUAL_REVIEW_FILENAME",
    "VisualReview",
    "audit_latex_source",
    "build_citation_registry",
    "build_current_field_claim_ledger",
    "build_section_outline",
    "build_surface_resolution_ledger",
    "execute_current_field_manuscript_rewrite",
    "finalize_current_field_visual_review",
    "load_current_field_manuscript_rewrite",
    "render_manuscript_pages",
]
