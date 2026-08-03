"""Evidence-grounded research-candidate authoring.

Why this module exists
----------------------
`generate_research_candidates` clusters retrieved literature with a fixed keyword
vocabulary (`METHOD_TERMS`, `LIMITATION_TERMS`, `DATASET_PATTERN`). On real abstracts
that vocabulary collapses to its own defaults, producing candidates whose `method` is
literally ``"method"`` and whose `dataset` is ``"available benchmark"``. It also never
produces `baseline`, `metric`, or `target`. `plans._build_plan` then falls back to
placeholder strings that `audit_research_plan` blocks, so a plan for a
system-discovered topic could not pass the gate at all. The only way a plan passed
before was for a human to hand-write the candidate's scientific fields.

This module closes that hole: the configured model reads the *real retrieved
abstracts* and authors the candidate's scientific fields itself. Every field must be
grounded in documents that were actually retrieved.

Discipline
----------
* The model may only cite `document_id` values from the supplied retrieved documents.
  A citation to any other id is rejected, so a fabricated source cannot enter a plan.
* Placeholder and contest terms are rejected here, not just at the plan gate, so a
  degenerate candidate fails early with a readable reason.
* The metric must name a concrete measurable quantity, reusing the plan gate's own
  `CONCRETE_METRIC_TERMS` vocabulary so the two gates cannot drift apart.
* Retrieval provenance (source URI, DOI, `retrieved_at`) is recorded per cited
  document so the evidence trail is auditable after the fact.
* This module authors a *plan input*, never a result. It records no metric values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.llm.client import LLMClientError, run_llm_json_completion
from autoresearch.research.plans import (
    CONCRETE_METRIC_TERMS,
    FORBIDDEN_PLAN_TERMS,
    FORBIDDEN_TITLE_TERMS,
    PLACEHOLDER_PLAN_TERMS,
)
from autoresearch.schemas import (
    CandidateStatus,
    DocumentRecord,
    ResearchCandidate,
    ValidationStatus,
)

MAX_DIGEST_DOCUMENTS = 24
MAX_ABSTRACT_CHARS = 1_200
MIN_CITED_DOCUMENTS = 2
# `plans._build_plan` splices these fields into sentence templates, so they must be
# short noun phrases rather than sentences or the rendered plan reads as broken prose.
MAX_SPLICED_FIELD_CHARS = 160
SPLICED_FIELDS = ("method", "dataset", "baseline")

_REQUIRED_FIELDS = (
    "title",
    "description",
    "research_gap",
    "method",
    "dataset",
    "baseline",
    "metric",
    "target",
    "limitation",
    "evidence_document_ids",
)

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "description",
        "research_gap",
        "method",
        "dataset",
        "baseline",
        "metric",
        "target",
        "limitation",
        "evidence_document_ids",
        "grounding",
    ],
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "research_gap": {"type": "string"},
        # `plans._build_plan` splices `method` into sentence templates such as
        # "whether <method> can improve the measured <metric>". A multi-sentence
        # method turns the rendered plan into ungrammatical prose, so the method
        # must stay a short technique name and elaboration belongs in
        # `description`.
        "method": {"type": "string", "maxLength": 120},
        "dataset": {"type": "string"},
        "baseline": {"type": "string"},
        "metric": {"type": "string"},
        "target": {"type": "string"},
        "limitation": {"type": "string"},
        "evidence_document_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "grounding": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "document_id", "justification"],
                "properties": {
                    "field": {"type": "string"},
                    "document_id": {"type": "string"},
                    "justification": {"type": "string"},
                },
            },
        },
    },
}


class CandidateAuthoringError(RuntimeError):
    """Raised when the model could not author an evidence-grounded candidate."""


@dataclass(frozen=True)
class CitedSource:
    """Retrieval provenance for one document the candidate actually cites."""

    document_id: str
    title: str
    source_uri: str
    doi: str | None
    retrieved_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_uri": self.source_uri,
            "doi": self.doi,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True)
class AuthoredCandidate:
    """A model-authored candidate plus its auditable evidence trail."""

    candidate: ResearchCandidate
    cited_sources: tuple[CitedSource, ...]
    grounding: tuple[Mapping[str, str], ...]
    model_name: str
    provider: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.model_dump(mode="json"),
            "cited_sources": [source.to_dict() for source in self.cited_sources],
            "grounding": [dict(item) for item in self.grounding],
            "model_name": self.model_name,
            "provider": self.provider,
        }


JsonCompletion = Callable[..., Any]


def author_research_candidate(
    documents: Sequence[DocumentRecord],
    *,
    project_id: str,
    research_direction: str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = 2_000,
    completion: JsonCompletion = run_llm_json_completion,
) -> AuthoredCandidate:
    """Have the configured model author a candidate from real retrieved documents."""

    if not documents:
        msg = "candidate authoring requires at least one retrieved document"
        raise CandidateAuthoringError(msg)
    direction = research_direction.strip()
    if not direction:
        msg = "candidate authoring requires a non-empty research direction"
        raise CandidateAuthoringError(msg)

    by_id = {document.id: document for document in documents}
    digest = _evidence_digest(documents)
    try:
        result = completion(
            messages=_authoring_messages(direction=direction, digest=digest),
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=0.0,
            response_schema=CANDIDATE_SCHEMA,
            response_schema_name="research_candidate",
        )
    except LLMClientError as exc:
        msg = f"candidate authoring model call failed: {exc}"
        raise CandidateAuthoringError(msg) from exc

    payload = getattr(result, "parsed_json", None)
    if not isinstance(payload, dict):
        msg = "candidate authoring returned no JSON object"
        raise CandidateAuthoringError(msg)

    fields = _validated_fields(payload)
    cited_ids = _validated_evidence_ids(payload, by_id=by_id)
    _reject_unusable_text(fields)
    _require_concrete_metric(fields["metric"])
    _require_spliceable_phrases(fields)

    cited_sources = tuple(_cited_source(by_id[doc_id]) for doc_id in cited_ids)
    grounding = _validated_grounding(payload, cited_ids=cited_ids)

    candidate = ResearchCandidate(
        id=f"authored_{project_id}",
        title=fields["title"],
        description=fields["description"],
        research_gap=fields["research_gap"],
        # Scores describe how the direction was selected, not an observed outcome.
        # They are deliberately mid-range: no run has happened yet.
        novelty_score=0.5,
        feasibility_score=0.7,
        impact_score=0.5,
        evidence_refs=[source.source_uri or source.document_id for source in cited_sources],
        related_document_ids=list(cited_ids),
        status=CandidateStatus.READY_FOR_REVIEW,
        validation_status=ValidationStatus.PENDING,
        metadata={
            "authored_by": "airesearcher candidate-author",
            "project_id": project_id,
            "research_direction": direction,
            "method": fields["method"],
            "dataset": fields["dataset"],
            "baseline": fields["baseline"],
            "metric": fields["metric"],
            "target": fields["target"],
            "limitation": fields["limitation"],
            "retrieved_document_count": len(documents),
            "cited_sources": [source.to_dict() for source in cited_sources],
        },
    )
    return AuthoredCandidate(
        candidate=candidate,
        cited_sources=cited_sources,
        grounding=grounding,
        model_name=str(getattr(result, "model_name", "")),
        provider=str(getattr(result, "provider", "")),
    )


def _evidence_digest(documents: Sequence[DocumentRecord]) -> str:
    lines: list[str] = []
    for document in list(documents)[:MAX_DIGEST_DOCUMENTS]:
        abstract = (document.abstract or "").strip().replace("\n", " ")
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + "..."
        lines.extend(
            [
                f"document_id: {document.id}",
                f"title: {document.title}",
                f"source_uri: {document.source_uri}",
                f"abstract: {abstract or '(no abstract retrieved)'}",
                "",
            ]
        )
    return "\n".join(lines)


def _authoring_messages(*, direction: str, digest: str) -> list[dict[str, str]]:
    system = (
        "You are a research planning agent. You read only the retrieved documents "
        "given to you and propose ONE concrete, feasible, falsifiable research "
        "direction that a code agent could implement.\n"
        "Hard rules:\n"
        "1. Cite only document_id values that appear in the supplied documents. "
        "Never invent an id, a paper, a DOI, or a URL.\n"
        f"2. Cite at least {MIN_CITED_DOCUMENTS} distinct documents.\n"
        "3. Name a specific, real, publicly obtainable dataset or benchmark, a "
        "specific baseline method, and a specific measurable metric. Vague wording "
        "such as 'available benchmark', 'suitable dataset', 'a strong baseline', or "
        "'task-specific metric' is forbidden.\n"
        "3a. 'method', 'dataset', and 'baseline' must be SHORT noun phrases that read "
        "naturally inside a sentence like 'whether <method> improves <metric> on "
        "<dataset> against <baseline>'. Keep 'method' under 120 characters and put "
        "any elaboration in 'description'. Do not write sentences or imperatives "
        "such as 'Train a network...' in these fields.\n"
        "4. The metric must name a measurable quantity such as accuracy, macro_f1, "
        "AUC, MAE, RMSE, precision, recall, or NMSE.\n"
        "5. Report no experimental results and no numbers you have not been given. "
        "You are authoring a plan input, not findings.\n"
        "6. Do not propose research about AI research assistants, this system, or "
        "any contest. Propose a normal scientific study.\n"
        "7. 'target' must be a concrete held-out validation route, for example a "
        "named official train/test split with a recorded seed.\n"
        "8. For every scientific field, add a grounding entry naming the field, the "
        "document_id supporting it, and a one-sentence justification.\n"
        "Return one JSON object only."
    )
    user = (
        f"Operator research direction: {direction}\n\n"
        "Retrieved documents:\n\n"
        f"{digest}\n"
        "Author the research candidate as JSON."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _validated_fields(payload: Mapping[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in _REQUIRED_FIELDS:
        if key == "evidence_document_ids":
            continue
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            msg = f"candidate authoring omitted required field: {key}"
            raise CandidateAuthoringError(msg)
        fields[key] = value.strip()
    return fields


def _validated_evidence_ids(
    payload: Mapping[str, Any],
    *,
    by_id: Mapping[str, DocumentRecord],
) -> tuple[str, ...]:
    raw = payload.get("evidence_document_ids")
    if not isinstance(raw, list):
        msg = "candidate authoring omitted evidence_document_ids"
        raise CandidateAuthoringError(msg)
    cited = tuple(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    unknown = [doc_id for doc_id in cited if doc_id not in by_id]
    if unknown:
        # A model that cites an id we never retrieved is fabricating a source.
        msg = f"candidate cited documents that were never retrieved: {', '.join(sorted(unknown))}"
        raise CandidateAuthoringError(msg)
    if len(cited) < MIN_CITED_DOCUMENTS:
        msg = (
            f"candidate cited {len(cited)} documents; at least "
            f"{MIN_CITED_DOCUMENTS} retrieved documents are required"
        )
        raise CandidateAuthoringError(msg)
    return cited


def _validated_grounding(
    payload: Mapping[str, Any],
    *,
    cited_ids: tuple[str, ...],
) -> tuple[Mapping[str, str], ...]:
    raw = payload.get("grounding")
    if not isinstance(raw, list) or not raw:
        msg = "candidate authoring omitted per-field grounding"
        raise CandidateAuthoringError(msg)
    grounding: list[Mapping[str, str]] = []
    allowed = set(cited_ids)
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        document_id = str(item.get("document_id", "")).strip()
        field = str(item.get("field", "")).strip()
        justification = str(item.get("justification", "")).strip()
        if not (document_id and field and justification):
            continue
        if document_id not in allowed:
            msg = f"grounding cited an uncited document: {document_id}"
            raise CandidateAuthoringError(msg)
        grounding.append(
            {
                "field": field,
                "document_id": document_id,
                "justification": justification,
            }
        )
    if not grounding:
        msg = "candidate authoring produced no usable grounding entries"
        raise CandidateAuthoringError(msg)
    return tuple(grounding)


def _reject_unusable_text(fields: Mapping[str, str]) -> None:
    """Fail early on the exact wording the plan gate would block later."""

    combined = " ".join(fields.values()).casefold()
    title = fields["title"].casefold()
    for term in PLACEHOLDER_PLAN_TERMS:
        if term in combined:
            msg = f"authored candidate contains placeholder term: {term}"
            raise CandidateAuthoringError(msg)
    for term in FORBIDDEN_PLAN_TERMS:
        if term in combined:
            msg = f"authored candidate contains forbidden contest term: {term}"
            raise CandidateAuthoringError(msg)
    for term in FORBIDDEN_TITLE_TERMS:
        if term in title:
            msg = f"authored candidate title names the system instead of a topic: {term}"
            raise CandidateAuthoringError(msg)


def _require_spliceable_phrases(fields: Mapping[str, str]) -> None:
    """Keep template-spliced fields short enough to read as grammatical prose."""

    for field in SPLICED_FIELDS:
        value = fields[field]
        if len(value) > MAX_SPLICED_FIELD_CHARS:
            msg = (
                f"authored {field} is {len(value)} characters; keep it under "
                f"{MAX_SPLICED_FIELD_CHARS} so the rendered plan stays grammatical"
            )
            raise CandidateAuthoringError(msg)
    return None


def _require_concrete_metric(metric: str) -> None:
    normalized = metric.casefold()
    if not any(term in normalized for term in CONCRETE_METRIC_TERMS):
        msg = f"authored metric is not concrete enough to evaluate: {metric}"
        raise CandidateAuthoringError(msg)


def _cited_source(document: DocumentRecord) -> CitedSource:
    return CitedSource(
        document_id=document.id,
        title=document.title,
        source_uri=document.source_uri,
        doi=document.doi,
        retrieved_at=document.retrieved_at.isoformat(),
    )
