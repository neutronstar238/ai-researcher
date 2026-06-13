"""Source-backed related-work inspection artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELATED_WORK_STOPWORDS = frozenset(
    {
        "about",
        "across",
        "algorithm",
        "analysis",
        "approach",
        "based",
        "benchmark",
        "benchmarks",
        "class",
        "classes",
        "classification",
        "classifier",
        "data",
        "dataset",
        "datasets",
        "demo",
        "evidence",
        "experiment",
        "experiments",
        "for",
        "from",
        "method",
        "methods",
        "model",
        "models",
        "paper",
        "research",
        "result",
        "results",
        "source",
        "study",
        "task",
        "tasks",
        "test",
        "using",
        "with",
    }
)

DIRECT_METHOD_TOKENS = frozenset(
    {
        "calibrated",
        "calibration",
        "centroid",
        "diagonal",
        "distance",
        "mahalanobi",
        "mahalanobis",
        "nearest",
        "prototype",
        "shrinkage",
        "variance",
        "zscore",
    }
)


@dataclass(frozen=True)
class RelatedWorkInspectionRecord:
    """One source-backed related-work inspection row."""

    document_id: str
    title: str
    citation_status: str
    bibtex_key: str | None
    locator: str | None
    comparison_status: str
    evidence_basis: str
    evidence_snippet: str
    method_overlap_terms: tuple[str, ...]
    dataset_overlap_terms: tuple[str, ...]
    baseline_overlap_terms: tuple[str, ...]
    source_backed: bool
    abstract_backed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "citation_status": self.citation_status,
            "bibtex_key": self.bibtex_key,
            "locator": self.locator,
            "comparison_status": self.comparison_status,
            "evidence_basis": self.evidence_basis,
            "evidence_snippet": self.evidence_snippet,
            "method_overlap_terms": list(self.method_overlap_terms),
            "dataset_overlap_terms": list(self.dataset_overlap_terms),
            "baseline_overlap_terms": list(self.baseline_overlap_terms),
            "source_backed": self.source_backed,
            "abstract_backed": self.abstract_backed,
        }


@dataclass(frozen=True)
class RelatedWorkInspectionArtifact:
    """Paths and summary counts for a related-work inspection artifact."""

    generated_at: str
    cycle_summary_path: str
    json_path: str
    markdown_path: str
    citation_metadata_path: str | None
    inspected_count: int
    source_backed_count: int
    abstract_backed_count: int
    direct_method_count: int
    contextual_count: int
    records: tuple[RelatedWorkInspectionRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "cycle_summary_path": self.cycle_summary_path,
            "json_path": self.json_path,
            "markdown_path": self.markdown_path,
            "citation_metadata_path": self.citation_metadata_path,
            "inspected_count": self.inspected_count,
            "source_backed_count": self.source_backed_count,
            "abstract_backed_count": self.abstract_backed_count,
            "direct_method_count": self.direct_method_count,
            "contextual_count": self.contextual_count,
            "records": [record.to_dict() for record in self.records],
        }


def inspect_related_work(
    *,
    cycle_summary_path: Path | str,
    output_dir: Path | str | None = None,
) -> RelatedWorkInspectionArtifact:
    """Inspect verified citation metadata against the executed candidate context."""

    summary_path = Path(cycle_summary_path).resolve()
    summary = _read_json(summary_path)
    base_dir = summary_path.parent
    root = Path(output_dir).resolve() if output_dir is not None else base_dir / "related-work"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "related-work-inspection.json"
    markdown_path = root / "related-work-inspection.md"

    citations = _dict(summary.get("citations"))
    citation_metadata_path = _resolve_path(citations.get("metadata_path"), base_dir)
    metadata = _read_json_if_exists(citation_metadata_path)
    if not metadata:
        metadata = citations
    rows = _dict_list(metadata.get("citations"))
    context = _inspection_context(summary, base_dir)
    records = tuple(_inspect_row(row, context) for row in rows)
    artifact = RelatedWorkInspectionArtifact(
        generated_at=datetime.now(timezone.utc).isoformat(),
        cycle_summary_path=summary_path.as_posix(),
        json_path=json_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        citation_metadata_path=(
            citation_metadata_path.as_posix()
            if citation_metadata_path is not None
            else None
        ),
        inspected_count=len(records),
        source_backed_count=sum(1 for record in records if record.source_backed),
        abstract_backed_count=sum(1 for record in records if record.abstract_backed),
        direct_method_count=sum(
            1 for record in records if record.comparison_status == "direct_method_candidate"
        ),
        contextual_count=sum(
            1
            for record in records
            if record.comparison_status
            in {"direct_method_candidate", "benchmark_or_baseline_context", "method_term_context"}
        ),
        records=records,
    )
    json_path.write_text(json.dumps(artifact.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    return artifact


def _inspect_row(
    row: dict[str, Any],
    context: dict[str, set[str]],
) -> RelatedWorkInspectionRecord:
    citation_status = _text(row.get("status"))
    abstract = _text(row.get("abstract")).strip()
    title = _text(row.get("title")).strip() or "untitled source"
    locator = _text(row.get("doi") or row.get("url") or row.get("source_uri")).strip() or None
    source_backed = citation_status in {"verified_doi", "verified_url"} and locator is not None
    abstract_backed = source_backed and bool(abstract)
    text = _row_text(row)
    tokens = set(_semantic_tokens(text))
    method_overlap = tokens & context["method_tokens"]
    dataset_overlap = tokens & context["dataset_tokens"]
    baseline_overlap = tokens & context["baseline_tokens"]
    comparison_status = _comparison_status(
        source_backed=source_backed,
        abstract_backed=abstract_backed,
        method_overlap=method_overlap,
        dataset_overlap=dataset_overlap,
        baseline_overlap=baseline_overlap,
    )
    evidence_basis = "abstract" if abstract else "title_metadata"
    return RelatedWorkInspectionRecord(
        document_id=_text(row.get("document_id")) or "unknown_document",
        title=title,
        citation_status=citation_status or "unknown",
        bibtex_key=_text(row.get("bibtex_key")) or None,
        locator=locator,
        comparison_status=comparison_status,
        evidence_basis=evidence_basis,
        evidence_snippet=_evidence_snippet(abstract or title),
        method_overlap_terms=tuple(sorted(method_overlap))[:16],
        dataset_overlap_terms=tuple(sorted(dataset_overlap))[:16],
        baseline_overlap_terms=tuple(sorted(baseline_overlap))[:16],
        source_backed=source_backed,
        abstract_backed=abstract_backed,
    )


def _comparison_status(
    *,
    source_backed: bool,
    abstract_backed: bool,
    method_overlap: set[str],
    dataset_overlap: set[str],
    baseline_overlap: set[str],
) -> str:
    if not source_backed:
        return "blocked_unverified"
    if not abstract_backed:
        return "metadata_only"
    direct_overlap = method_overlap & DIRECT_METHOD_TOKENS
    if len(direct_overlap) >= 2:
        return "direct_method_candidate"
    if direct_overlap and (dataset_overlap or baseline_overlap):
        return "direct_method_candidate"
    if dataset_overlap or baseline_overlap:
        return "benchmark_or_baseline_context"
    if method_overlap:
        return "method_term_context"
    return "unrelated"


def _inspection_context(summary: dict[str, Any], base_dir: Path) -> dict[str, set[str]]:
    candidate = _dict(summary.get("candidate"))
    candidate_metadata = _dict(candidate.get("metadata"))
    demo = _dict(summary.get("demo"))
    run_record_path = _run_record_path(summary, base_dir)
    run_record = _read_json_if_exists(run_record_path)
    task_metadata = _dict(run_record.get("task_metadata"))
    run = _dict(run_record.get("run"))

    method_texts = (
        *_context_values(candidate_metadata, ("method", "proposed_method", "method_contribution", "mechanism")),
        *_context_values(task_metadata, ("method", "proposed_method", "method_contribution", "mechanism")),
        *_context_values(run, ("task_id",)),
        *_context_values(demo, ("demo",)),
    )
    dataset_texts = (
        *_context_values(candidate_metadata, ("dataset", "benchmark", "demo")),
        *_context_values(task_metadata, ("dataset", "benchmark", "demo")),
        *_context_values(candidate, ("title", "description", "research_gap")),
        *_context_values(demo, ("demo",)),
    )
    baseline_texts = (
        *_context_values(candidate_metadata, ("baseline", "ablation", "limitation")),
        *_context_values(task_metadata, ("baseline", "ablation", "baseline_comparison")),
    )
    return {
        "method_tokens": _anchor_tokens(method_texts),
        "dataset_tokens": _anchor_tokens(dataset_texts),
        "baseline_tokens": _anchor_tokens(baseline_texts),
    }


def _render_markdown(artifact: RelatedWorkInspectionArtifact) -> str:
    lines = [
        "# Related Work Inspection",
        "",
        f"- Cycle summary: `{artifact.cycle_summary_path}`",
        f"- Citation metadata: `{artifact.citation_metadata_path or 'missing'}`",
        f"- Inspected records: `{artifact.inspected_count}`",
        f"- Source-backed records: `{artifact.source_backed_count}`",
        f"- Abstract-backed records: `{artifact.abstract_backed_count}`",
        f"- Direct method candidates: `{artifact.direct_method_count}`",
        f"- Contextual records: `{artifact.contextual_count}`",
        "",
        "## Records",
        "",
    ]
    for record in artifact.records[:40]:
        method = ", ".join(record.method_overlap_terms) or "none"
        dataset = ", ".join(record.dataset_overlap_terms) or "none"
        baseline = ", ".join(record.baseline_overlap_terms) or "none"
        lines.extend(
            [
                f"### {record.title}",
                "",
                f"- Document ID: `{record.document_id}`",
                f"- Citation status: `{record.citation_status}`",
                f"- Comparison status: `{record.comparison_status}`",
                f"- Evidence basis: `{record.evidence_basis}`",
                f"- Locator: `{record.locator or 'missing'}`",
                f"- Method overlap: `{method}`",
                f"- Dataset overlap: `{dataset}`",
                f"- Baseline overlap: `{baseline}`",
                f"- Evidence snippet: {record.evidence_snippet}",
                "",
            ]
        )
    if len(artifact.records) > 40:
        lines.append(f"_Additional records omitted from Markdown: {len(artifact.records) - 40}._")
    return "\n".join(lines).rstrip() + "\n"


def _row_text(row: dict[str, Any]) -> str:
    parts = [
        _text(row.get("title")),
        _text(row.get("abstract")),
        _text(row.get("venue")),
        _text(row.get("source_uri")),
        " ".join(_text(author) for author in _list(row.get("authors"))),
        " ".join(_text(tag) for tag in _list(row.get("tags"))),
    ]
    return "\n".join(part for part in parts if part)


def _context_values(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for field in fields:
        value = payload.get(field)
        if isinstance(value, dict):
            values.extend(_text(item) for item in value.values())
            continue
        if isinstance(value, list | tuple | set):
            values.extend(_text(item) for item in value)
            continue
        text = _text(value).strip()
        if text:
            values.append(text)
    return tuple(values)


def _anchor_tokens(texts: tuple[str, ...]) -> set[str]:
    return {
        token
        for text in texts
        for token in _semantic_tokens(text)
        if token not in RELATED_WORK_STOPWORDS
    }


def _semantic_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in re.findall(r"[a-z0-9]+", text.casefold().replace("_", " ")):
        if len(raw_token) < 3:
            continue
        token = _normalise_token(raw_token)
        if token:
            tokens.append(token)
    return tuple(tokens)


def _normalise_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 5:
        return f"{token[:-3]}y"
    if token.endswith("ss"):
        return token
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _evidence_snippet(text: str, *, limit: int = 280) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return "No source text was available."
    sentence_end = re.search(r"(?<=[.!?])\s+", collapsed)
    snippet = collapsed[: sentence_end.start()] if sentence_end else collapsed
    if len(snippet) > limit:
        return f"{snippet[: limit - 3].rstrip()}..."
    return snippet


def _run_record_path(summary: dict[str, Any], base_dir: Path) -> Path | None:
    demo = _dict(summary.get("demo"))
    explicit = _resolve_path(demo.get("run_record_path"), base_dir)
    if explicit is not None and explicit.exists():
        return explicit
    experiment_dir = _resolve_path(demo.get("experiment_dir"), base_dir)
    if experiment_dir is None:
        return explicit
    candidate = experiment_dir / "run" / "run-record.json"
    if candidate.exists():
        return candidate
    return explicit


def _resolve_path(value: object, base_dir: Path) -> Path | None:
    if not isinstance(value, str | Path):
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = (base_dir / path, Path.cwd() / path, path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return base_dir / path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_json_if_exists(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))
