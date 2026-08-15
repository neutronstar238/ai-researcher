"""Unified acceptance gate for a human-facing contest research plan.

The renderer owns presentation.  This module owns the final *delivery* decision:
it reopens the stable artifacts, verifies their bindings, and checks the few
semantic invariants that must hold before API or batch code may say
``completed``.  Internal source/provenance remains available under ``_private``;
the four human-facing representations must stay self-contained.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    validate_locked_bibliography,
)
from autoresearch.kernel.contracts import canonical_sha256

_MANIFEST_NAME = "research-plan-manifest.json"
_MANIFEST_SCHEMA = "contest-direct-plan-render-v3"
_REFERENCE_PROJECTION = "bibliographic-display-v2"
_EXPECTED_ARTIFACTS = {
    "json": "research-plan.json",
    "markdown": "research-plan.md",
    "tex": "research-plan.tex",
    "pdf": "research-plan.pdf",
    "source": "_private/research-plan-source.json",
}
_INTERNAL_PUBLIC_KEYS = frozenset(
    {
        "adapter_id",
        "artifact_hash",
        "artifact_path",
        "file",
        "filename",
        "input_hash",
        "manifest_sha256",
        "metrics_sha256",
        "model_response_hash",
        "path",
        "public_payload_sha256",
        "record_id",
        "record_sha256",
        "revision_id",
        "run_id",
        "sha256",
        "source_payload_sha256",
    }
)
_INTERNAL_TOKEN = re.compile(
    r"(?i)\b(?:run_id|adapter_id|record_id|revision_id|artifact_(?:path|hash)|"
    r"input_hash|model_response_hash|(?:source|public|metrics|manifest|record)_sha256)\b"
)
_MACHINE_IDENTIFIER = re.compile(
    r"(?i)\b(?:consecutive_integer_primes|ordered_consecutive_prime_gaps|"
    r"global_permutation|local_block_permutation|"
    r"residue_path_conditioned_permutation|wheel_210|"
    r"hardy_littlewood_ktuple_generative_null|"
    r"tie_aware_normalized_permutation_entropy_m5|"
    r"fixed_interval_resampling_delta_ci95|standardized_effect|"
    r"prime-gap-information-theory-v1)\b"
)
_ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?i)(?:\b[A-Za-z]:[\\/]|(?<!:)\/(?:home|Users|tmp|var\/tmp|mnt|workspace|root)\/)"
)
_EXTERNAL_ARTIFACT_FILE = re.compile(
    r"(?i)(?<![\w./-])(?:[\w.-]+[\\/])*[\w.-]+\."
    r"(?:jsonl?|csv|tsv|log|ya?ml|parquet|npy|npz|tex)(?![\w.-])"
)
_HEX_DIGEST = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_URL = re.compile(r"https?://[^\s；，。,）)\]}>]+", re.IGNORECASE)
_DOI = re.compile(r"10\.\d{4,9}/[^\s；，。,）)\]}>]+", re.IGNORECASE)


class HumanDeliveryValidationError(RuntimeError):
    """Raised when a runner output is not a complete human delivery."""


@dataclass(frozen=True)
class HumanDeliveryValidationReport:
    """Safe, path-free summary suitable for an internal API/batch receipt."""

    reference_count: int
    pilot_executed: bool
    table_count: int
    figure_count: int
    provenance_binding_count: int
    bibliography_binding: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "contest-human-delivery-validation-v1",
            "status": "accepted",
            "reference_count": self.reference_count,
            "pilot_executed": self.pilot_executed,
            "table_count": self.table_count,
            "figure_count": self.figure_count,
            "provenance_binding_count": self.provenance_binding_count,
            "bibliography_binding": self.bibliography_binding,
        }


def validate_runner_human_delivery(
    *,
    output_dir: Path | str,
    result: Mapping[str, Any],
    locked_reference_catalog: Sequence[str] | None = None,
) -> HumanDeliveryValidationReport:
    """Locate and validate the one human plan claimed by a runner result."""

    status = str(result.get("status") or "").strip()
    if not status.startswith("completed"):
        raise HumanDeliveryValidationError(
            f"runner status is not a completed delivery: {status or 'missing'}"
        )
    pilot_executed = result.get("preexperiment_executed")
    if not isinstance(pilot_executed, bool):
        raise HumanDeliveryValidationError(
            "runner delivery must state preexperiment_executed as a boolean"
        )
    plan_dir = _locate_plan_dir(Path(output_dir), result)
    return validate_human_research_plan_delivery(
        plan_dir,
        locked_reference_catalog=locked_reference_catalog,
        pilot_executed=pilot_executed,
    )


def validate_human_research_plan_delivery(
    plan_dir: Path | str,
    *,
    locked_reference_catalog: Sequence[str] | None = None,
    pilot_executed: bool | None = None,
) -> HumanDeliveryValidationReport:
    """Validate one stable v3 plan directory without modifying it."""

    root = Path(plan_dir).expanduser().resolve()
    if not root.is_dir():
        raise HumanDeliveryValidationError(f"human plan directory is missing: {root}")
    manifest = _read_mapping(root / _MANIFEST_NAME, role="render manifest")
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        raise HumanDeliveryValidationError("human delivery requires render manifest v3")
    if manifest.get("compile_status") != "compiled" or manifest.get("pdf_text_verified") is not True:
        raise HumanDeliveryValidationError("human delivery PDF is not compiled and text-verified")

    paths = _validate_artifact_bindings(root, manifest)
    public_payload = _read_mapping(paths["json"], role="public research plan JSON")
    source_payload = _read_mapping(paths["source"], role="private research plan source")
    if manifest.get("public_payload_sha256") != canonical_sha256(dict(public_payload)):
        raise HumanDeliveryValidationError("public research plan hash differs from manifest")
    if manifest.get("source_payload_sha256") != canonical_sha256(dict(source_payload)):
        raise HumanDeliveryValidationError("private source hash differs from manifest")

    bibliography_binding, reference_count = _validate_bibliography(
        public_payload=public_payload,
        source_payload=source_payload,
        manifest=manifest,
        locked_reference_catalog=locked_reference_catalog,
    )

    markdown = _read_text(paths["markdown"], role="research plan Markdown")
    tex = _read_text(paths["tex"], role="research plan TeX")
    pdf_text = _extract_pdf_text(paths["pdf"])
    public_json_text = json.dumps(public_payload, ensure_ascii=False, sort_keys=True)
    _validate_public_key_names(public_payload)
    for role, text in (
        ("JSON", public_json_text),
        ("Markdown", markdown),
        ("TeX", tex),
        ("PDF", pdf_text),
    ):
        _validate_public_text(role, text)
    title = str(public_payload.get("title") or "").strip()
    compact_pdf = re.sub(r"\s+", "", pdf_text)
    if not title or re.sub(r"\s+", "", title) not in compact_pdf or "参考论文" not in compact_pdf:
        raise HumanDeliveryValidationError("PDF text does not contain the plan title and references")

    effective_pilot = _resolve_pilot_state(public_payload, manifest, pilot_executed)
    table_count, figure_count, provenance_count = _validate_evidence_branch(
        root=root,
        public_payload=public_payload,
        source_payload=source_payload,
        manifest=manifest,
        markdown=markdown,
        tex=tex,
        pdf_text=pdf_text,
        pilot_executed=effective_pilot,
    )
    return HumanDeliveryValidationReport(
        reference_count=reference_count,
        pilot_executed=effective_pilot,
        table_count=table_count,
        figure_count=figure_count,
        provenance_binding_count=provenance_count,
        bibliography_binding=bibliography_binding,
    )


def _validate_artifact_bindings(
    root: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Path]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise HumanDeliveryValidationError("render manifest lacks artifact bindings")
    paths: dict[str, Path] = {}
    for kind, expected_name in _EXPECTED_ARTIFACTS.items():
        binding = artifacts.get(kind)
        if not isinstance(binding, Mapping) or binding.get("filename") != expected_name:
            raise HumanDeliveryValidationError(f"render manifest has invalid {kind} filename")
        path = (root / expected_name).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise HumanDeliveryValidationError(f"{kind} artifact escapes the plan directory") from exc
        _verify_file_binding(path, binding, role=f"rendered {kind}")
        paths[kind] = path
    return paths


def _validate_bibliography(
    *,
    public_payload: Mapping[str, Any],
    source_payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    locked_reference_catalog: Sequence[str] | None,
) -> tuple[str, int]:
    public_references = _string_sequence(public_payload.get("references"), "public references")
    source_references = _string_sequence(source_payload.get("references"), "source references")
    display_references = _string_sequence(
        manifest.get("display_references"), "manifest display references"
    )
    for role, references in (
        ("public", public_references),
        ("source", source_references),
        ("manifest display", display_references),
    ):
        if not MIN_RESEARCH_PLAN_REFERENCES <= len(references) <= MAX_RESEARCH_PLAN_REFERENCES:
            raise HumanDeliveryValidationError(f"{role} bibliography must contain 5–10 references")
        if len(set(references)) != len(references):
            raise HumanDeliveryValidationError(f"{role} bibliography contains duplicates")
    if not len(public_references) == len(source_references) == len(display_references):
        raise HumanDeliveryValidationError("public, source, and manifest reference counts differ")
    if manifest.get("reference_projection_version") != _REFERENCE_PROJECTION:
        raise HumanDeliveryValidationError("manifest lacks the supported bibliography projection")
    expected_display_hash = canonical_sha256({"display_references": list(display_references)})
    if manifest.get("display_references_sha256") != expected_display_hash:
        raise HumanDeliveryValidationError("manifest display bibliography hash differs")
    for ordinal, (public, display) in enumerate(
        zip(public_references, display_references, strict=True), start=1
    ):
        public_ids = _public_reference_identifiers(public)
        display_ids = _public_reference_identifiers(display)
        if not public_ids or not display_ids or public_ids.isdisjoint(display_ids):
            raise HumanDeliveryValidationError(
                f"public reference {ordinal} is not bound to its manifest source projection"
            )
    if locked_reference_catalog is not None:
        try:
            validate_locked_bibliography(source_references, locked_reference_catalog)
        except ValueError as exc:
            raise HumanDeliveryValidationError(
                f"bibliography differs from the caller's locked real catalog: {exc}"
            ) from exc
        binding = "caller-locked-catalog"
    else:
        binding = "manifest-source-projection"
    return binding, len(public_references)


def _resolve_pilot_state(
    public_payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    requested: bool | None,
) -> bool:
    summary = public_payload.get("preexperiment_summary")
    if not isinstance(summary, Mapping) or not isinstance(summary.get("executed"), bool):
        raise HumanDeliveryValidationError("public plan lacks a boolean preexperiment summary")
    summary_executed = bool(summary["executed"])
    embedded = manifest.get("embedded_evidence")
    if not isinstance(embedded, Mapping) or not isinstance(embedded.get("present"), bool):
        raise HumanDeliveryValidationError("render manifest lacks embedded-evidence state")
    manifest_executed = bool(embedded["present"])
    if summary_executed != manifest_executed:
        raise HumanDeliveryValidationError("public and manifest preexperiment states disagree")
    if requested is not None and requested != summary_executed:
        raise HumanDeliveryValidationError("runner and human plan preexperiment states disagree")
    return summary_executed


def _validate_evidence_branch(
    *,
    root: Path,
    public_payload: Mapping[str, Any],
    source_payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    markdown: str,
    tex: str,
    pdf_text: str,
    pilot_executed: bool,
) -> tuple[int, int, int]:
    manifest_evidence = manifest["embedded_evidence"]
    assert isinstance(manifest_evidence, Mapping)
    public_evidence = public_payload.get("embedded_evidence")
    source_evidence = source_payload.get("embedded_evidence")
    bindings = manifest_evidence.get("provenance_bindings")
    if not isinstance(bindings, Sequence) or isinstance(bindings, str | bytes):
        raise HumanDeliveryValidationError("manifest evidence bindings must be an array")

    if not pilot_executed:
        results = str(public_payload.get("results") or "")
        if public_evidence is not None or source_evidence is not None:
            raise HumanDeliveryValidationError("no-pilot delivery contains fabricated embedded evidence")
        if (
            manifest_evidence.get("content_sha256") is not None
            or manifest_evidence.get("table_count") != 0
            or manifest_evidence.get("figure_count") != 0
            or bindings
            or "尚未执行预实验" not in results
        ):
            raise HumanDeliveryValidationError(
                "no-pilot delivery must contain no evidence and disclose 尚未执行预实验"
            )
        expected_empty_bindings_hash = canonical_sha256({"evidence_bindings": []})
        if manifest_evidence.get("provenance_bindings_sha256") != expected_empty_bindings_hash:
            raise HumanDeliveryValidationError("no-pilot provenance binding hash is not empty")
        if "<svg" in markdown or r"\begin{tikzpicture}" in tex:
            raise HumanDeliveryValidationError("no-pilot delivery contains a generated result figure")
        return 0, 0, 0

    if not isinstance(public_evidence, Mapping) or not isinstance(source_evidence, Mapping):
        raise HumanDeliveryValidationError("completed pilot lacks embedded public/source evidence")
    if manifest_evidence.get("content_sha256") != canonical_sha256(dict(source_evidence)):
        raise HumanDeliveryValidationError("embedded evidence differs from its private source hash")
    tables = public_evidence.get("tables")
    figures = public_evidence.get("figures")
    if (
        not isinstance(tables, Sequence)
        or isinstance(tables, str | bytes)
        or not isinstance(figures, Sequence)
        or isinstance(figures, str | bytes)
    ):
        raise HumanDeliveryValidationError("completed pilot evidence tables/figures are malformed")
    table_count = len(tables)
    figure_count = len(figures)
    if table_count < 1 or figure_count < 1:
        raise HumanDeliveryValidationError(
            "completed pilot requires at least one summary table and one generated figure"
        )
    if (
        manifest_evidence.get("table_count") != table_count
        or manifest_evidence.get("figure_count") != figure_count
    ):
        raise HumanDeliveryValidationError("manifest evidence counts differ from the public plan")
    if not str(public_evidence.get("analysis_zh") or "").strip():
        raise HumanDeliveryValidationError("completed pilot lacks integrated Chinese analysis")
    valid_tables = [
        table
        for table in tables
        if isinstance(table, Mapping)
        and _nonempty_rows(table.get("rows"))
        and str(table.get("analysis_zh") or "").strip()
    ]
    valid_figures = [
        figure
        for figure in figures
        if isinstance(figure, Mapping)
        and figure.get("kind") == "horizontal_interval_plot"
        and _valid_interval_series(figure.get("series"))
        and str(figure.get("analysis_zh") or "").strip()
    ]
    if not valid_tables or not valid_figures:
        raise HumanDeliveryValidationError(
            "completed pilot table/figure must contain data and accompanying analysis"
        )
    if "### 表" not in markdown or "<svg" not in markdown or "表格分析" not in markdown:
        raise HumanDeliveryValidationError("Markdown does not embed the pilot table, figure, and analysis")
    if r"\begin{table}" not in tex or r"\begin{tikzpicture}" not in tex:
        raise HumanDeliveryValidationError("TeX does not embed the pilot table and generated figure")
    compact_pdf = re.sub(r"\s+", "", pdf_text)
    for item, role in ((valid_tables[0], "table"), (valid_figures[0], "figure")):
        title = str(item.get("title_zh") or "").strip()
        if not title or re.sub(r"\s+", "", title) not in compact_pdf:
            raise HumanDeliveryValidationError(f"PDF text lacks the embedded pilot {role} title")

    if not bindings:
        raise HumanDeliveryValidationError("completed pilot lacks private provenance bindings")
    expected_bindings_hash = canonical_sha256({"evidence_bindings": list(bindings)})
    if manifest_evidence.get("provenance_bindings_sha256") != expected_bindings_hash:
        raise HumanDeliveryValidationError("pilot provenance binding hash differs")
    roles: set[str] = set()
    for ordinal, binding in enumerate(bindings, start=1):
        if not isinstance(binding, Mapping):
            raise HumanDeliveryValidationError(f"pilot provenance binding {ordinal} is malformed")
        role = str(binding.get("role") or "").strip()
        value = str(binding.get("path") or "").strip()
        if not role or not value:
            raise HumanDeliveryValidationError(f"pilot provenance binding {ordinal} lacks role/path")
        path = Path(value).expanduser()
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        _verify_file_binding(path, binding, role=f"pilot provenance {role}")
        roles.add(role)
    if "preexperiment_metrics" not in roles or "preexperiment_artifact" not in roles:
        raise HumanDeliveryValidationError(
            "completed pilot provenance must bind its metrics and execution artifact"
        )
    return table_count, figure_count, len(bindings)


def _locate_plan_dir(output_dir: Path, result: Mapping[str, Any]) -> Path:
    output = output_dir.expanduser().resolve()
    candidates = _plan_dirs_in_payload(result)
    report_path = result.get("delivery_report_path")
    if isinstance(report_path, str) and report_path.strip():
        path = Path(report_path).expanduser().resolve()
        if path.is_file():
            report = _read_mapping(path, role="runner delivery report")
            candidates.update(_plan_dirs_in_payload(report))
    canonical = output / "plan"
    if (canonical / _MANIFEST_NAME).is_file():
        candidates.add(canonical.resolve())
    valid: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(output)
        except ValueError as exc:
            raise HumanDeliveryValidationError(
                "runner human plan is outside its declared output directory"
            ) from exc
        if (resolved / _MANIFEST_NAME).is_file():
            valid.add(resolved)
    if not valid:
        raise HumanDeliveryValidationError("runner result does not bind a v3 human plan directory")
    if len(valid) != 1:
        raise HumanDeliveryValidationError("runner result ambiguously binds multiple human plans")
    return next(iter(valid))


def _plan_dirs_in_payload(value: Any) -> set[Path]:
    found: set[Path] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            found.update(_plan_dirs_in_payload(item))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            found.update(_plan_dirs_in_payload(item))
    elif isinstance(value, str):
        candidate = Path(value).expanduser()
        # Delivery reports also contain inventory-relative names such as
        # ``plan/research-plan.json``.  Resolving those against the process CWD
        # turns harmless inventory rows into apparent out-of-scope plans.  Only
        # absolute runner bindings may nominate a plan directory; the canonical
        # local plan is discovered separately by ``_locate_plan_dir``.
        if candidate.is_absolute() and candidate.name in {
            *_EXPECTED_ARTIFACTS.values(),
            _MANIFEST_NAME,
        }:
            found.add(candidate.resolve().parent)
    return found


def _validate_public_key_names(value: Any, *, prefix: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).casefold()
            if (
                name in _INTERNAL_PUBLIC_KEYS
                or name.endswith("_sha256")
                or name.endswith("_hash")
                or name.endswith("_path")
            ):
                raise HumanDeliveryValidationError(
                    f"public research plan exposes internal field {prefix}.{key}"
                )
            _validate_public_key_names(item, prefix=f"{prefix}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            _validate_public_key_names(item, prefix=f"{prefix}[{index}]")


def _validate_public_text(role: str, text: str) -> None:
    checks = (
        (_INTERNAL_TOKEN, "internal field name"),
        (_MACHINE_IDENTIFIER, "machine identifier"),
        (_ABSOLUTE_LOCAL_PATH, "absolute local path"),
        (_EXTERNAL_ARTIFACT_FILE, "external artifact filename"),
        (_HEX_DIGEST, "raw hash value"),
    )
    for pattern, description in checks:
        match = pattern.search(text)
        if match is not None:
            excerpt = match.group(0)[:80]
            raise HumanDeliveryValidationError(
                f"public {role} exposes {description}: {excerpt}"
            )


def _valid_interval_series(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or not value:
        return False
    for item in value:
        if not isinstance(item, Mapping) or not str(item.get("label") or "").strip():
            return False
        numbers = (item.get("lower"), item.get("value"), item.get("upper"))
        if any(isinstance(number, bool) or not isinstance(number, int | float) for number in numbers):
            return False
        lower, point, upper = (
            float(cast(int | float, number)) for number in numbers
        )
        if not lower <= point <= upper:
            return False
    return True


def _nonempty_rows(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and bool(value)
        and all(isinstance(item, Mapping) and bool(item) for item in value)
    )


def _public_reference_identifiers(reference: str) -> frozenset[str]:
    identifiers = {
        match.group(0).rstrip(".;,，。；").casefold()
        for pattern in (_DOI, _URL)
        for match in pattern.finditer(reference)
    }
    return frozenset(identifiers)


def _string_sequence(value: Any, role: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise HumanDeliveryValidationError(f"{role} must be an array")
    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise HumanDeliveryValidationError(f"{role} contains a blank item")
    return items


def _read_mapping(path: Path, *, role: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HumanDeliveryValidationError(f"cannot read {role}: {path}") from exc
    if not isinstance(value, Mapping):
        raise HumanDeliveryValidationError(f"{role} must contain a JSON object")
    return value


def _read_text(path: Path, *, role: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HumanDeliveryValidationError(f"cannot read {role}: {path}") from exc
    if not text.strip():
        raise HumanDeliveryValidationError(f"{role} is empty")
    return text


def _extract_pdf_text(path: Path) -> str:
    extractor = shutil.which("pdftotext")
    if extractor is None:
        raise HumanDeliveryValidationError("pdftotext is required to validate the public PDF")
    completed = subprocess.run(
        (extractor, "-layout", str(path), "-"),
        cwd=path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise HumanDeliveryValidationError("public PDF is not text-readable")
    return completed.stdout


def _verify_file_binding(path: Path, binding: Mapping[str, Any], *, role: str) -> None:
    if not path.is_file():
        raise HumanDeliveryValidationError(f"{role} file is missing: {path}")
    expected_hash = binding.get("sha256")
    expected_size = binding.get("size_bytes")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise HumanDeliveryValidationError(f"{role} has an invalid SHA-256 binding")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise HumanDeliveryValidationError(f"{role} has an invalid size binding")
    if path.stat().st_size != expected_size or _sha256_file(path) != expected_hash:
        raise HumanDeliveryValidationError(f"{role} differs from its manifest binding")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
