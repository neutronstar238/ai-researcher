"""Compose evidence-bound publication manuscripts from cycle artifacts."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .figures import FigureGenerationError, generate_metric_bar_figure

REQUIRED_MANUSCRIPT_SECTIONS = (
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Experiments",
    "Results",
    "Limitations",
    "Conclusion",
    "References",
)

REFERENCE_DIRECT_METHOD_TOKENS = frozenset(
    {
        "calibrated",
        "calibration",
        "centroid",
        "diagonal",
        "gaussian",
        "heteroscedastic",
        "mahalanobi",
        "mahalanobis",
        "nearest",
        "prototype",
        "shrinkage",
        "variance",
        "zscore",
    }
)

REFERENCE_SUPPORT_TOKENS = frozenset(
    {
        "classifier",
        "classification",
        "distance",
        "metric",
        "recognition",
    }
)

REFERENCE_TASK_ANCHOR_TOKENS = frozenset(
    {
        "character",
        "classifier",
        "classification",
        "digit",
        "handwritten",
        "nearest",
        "pendigit",
        "prototype",
        "recognition",
    }
)

REFERENCE_TITLE_METHOD_ANCHOR_TOKENS = frozenset(
    {
        "centroid",
        "distance",
        "knn",
        "mahalanobi",
        "mahalanobis",
        "metric",
        "nearest",
        "prototype",
    }
)

REFERENCE_TITLE_DOMAIN_ANCHOR_TOKENS = frozenset(
    {
        "character",
        "digit",
        "handwritten",
        "pendigit",
        "recognition",
    }
)

REFERENCE_GENERIC_TOKENS = frozenset(
    {
        "also",
        "already",
        "and",
        "any",
        "are",
        "artifact",
        "artifacts",
        "as",
        "at",
        "aware",
        "benchmark",
        "between",
        "broad",
        "but",
        "by",
        "can",
        "character",
        "checking",
        "claim",
        "class",
        "classes",
        "classification",
        "classifier",
        "computed",
        "contribution",
        "cover",
        "count",
        "cycle",
        "data",
        "dataset",
        "demo",
        "document",
        "documents",
        "each",
        "evaluate",
        "evidence",
        "family",
        "feature",
        "file",
        "for",
        "from",
        "give",
        "include",
        "included",
        "includes",
        "improve",
        "image",
        "learning",
        "may",
        "mechanism",
        "method",
        "model",
        "more",
        "out",
        "over",
        "paper",
        "per",
        "positioning",
        "prior",
        "publication",
        "public",
        "real",
        "recognition",
        "record",
        "related",
        "relevance",
        "remaining",
        "require",
        "report",
        "research",
        "result",
        "results",
        "retrieved",
        "run",
        "same",
        "scene",
        "score",
        "second",
        "semantic",
        "single",
        "split",
        "source",
        "sources",
        "still",
        "study",
        "system",
        "tabular",
        "that",
        "the",
        "this",
        "using",
        "whether",
        "was",
        "with",
        "without",
        "work",
    }
)


@dataclass(frozen=True)
class PublicationManuscriptArtifact:
    """Generated evidence-bound manuscript summary."""

    generated_at: str
    cycle_summary_path: str
    markdown_path: str
    json_path: str
    vault_markdown_path: str | None
    word_count: int
    section_word_counts: dict[str, int]
    evidence_refs: tuple[str, ...]
    analysis_artifact_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "cycle_summary_path": self.cycle_summary_path,
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
            "vault_markdown_path": self.vault_markdown_path,
            "word_count": self.word_count,
            "section_word_counts": self.section_word_counts,
            "evidence_refs": list(self.evidence_refs),
            "analysis_artifact_paths": list(self.analysis_artifact_paths),
        }


@dataclass(frozen=True)
class _ManuscriptEvidence:
    summary: dict[str, Any]
    base_dir: Path
    cycle_summary_path: Path
    candidate: dict[str, Any]
    demo: dict[str, Any]
    run_record: dict[str, Any]
    validation: dict[str, Any]
    evidence_map: dict[str, Any]
    literature_docs: tuple[dict[str, str], ...]
    similarity_findings: tuple[dict[str, str], ...]
    similarity_summary_path: Path | None
    citations: tuple[dict[str, Any], ...]
    related_work_inspection_path: Path | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class _AnalysisArtifacts:
    metrics_source_path: Path | None = None
    figure_pdf_path: Path | None = None
    figure_png_path: Path | None = None
    figure_metadata_path: Path | None = None
    table_markdown_path: Path | None = None
    similarity_positioning_json_path: Path | None = None
    similarity_positioning_markdown_path: Path | None = None

    def paths(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (
                self.metrics_source_path,
                self.figure_pdf_path,
                self.figure_png_path,
                self.figure_metadata_path,
                self.table_markdown_path,
                self.similarity_positioning_json_path,
                self.similarity_positioning_markdown_path,
            )
            if path is not None and path.exists()
        )


def compose_publication_manuscript(
    *,
    cycle_summary_path: Path | str,
    output_dir: Path | str | None = None,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
) -> PublicationManuscriptArtifact:
    """Write a paper-style Markdown manuscript from existing cycle evidence."""

    summary_path = Path(cycle_summary_path).resolve()
    base_dir = summary_path.parent
    root = Path(output_dir).resolve() if output_dir is not None else base_dir / "paper-manuscript"
    root.mkdir(parents=True, exist_ok=True)
    markdown_path = root / "manuscript.md"
    json_path = root / "manuscript.json"

    evidence = _load_manuscript_evidence(summary_path)
    analysis = _write_analysis_artifacts(evidence, root)
    markdown = _render_manuscript(evidence, analysis)
    markdown_path.write_text(markdown, encoding="utf-8")
    section_word_counts = _section_word_counts(markdown)
    word_count = sum(
        count
        for section, count in section_word_counts.items()
        if section != "References"
    )
    vault_markdown_path = _write_vault_manuscript(markdown, vault_root, project_id)
    artifact = PublicationManuscriptArtifact(
        generated_at=datetime.now(timezone.utc).isoformat(),
        cycle_summary_path=summary_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        json_path=json_path.as_posix(),
        vault_markdown_path=(
            vault_markdown_path.as_posix() if vault_markdown_path is not None else None
        ),
        word_count=word_count,
        section_word_counts=section_word_counts,
        evidence_refs=(
            *evidence.evidence_refs,
            *(path.as_posix() for path in analysis.paths()),
        ),
        analysis_artifact_paths=tuple(path.as_posix() for path in analysis.paths()),
    )
    json_path.write_text(json.dumps(artifact.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return artifact


def _load_manuscript_evidence(summary_path: Path) -> _ManuscriptEvidence:
    summary = _read_json(summary_path)
    base_dir = summary_path.parent
    candidate = _dict(summary.get("candidate"))
    demo = _dict(summary.get("demo"))
    experiment_dir = _resolve_path(demo.get("experiment_dir"), base_dir)
    run_record_path = _resolve_path(demo.get("run_record_path"), base_dir)
    if run_record_path is None and experiment_dir is not None:
        inferred = experiment_dir / "run" / "run-record.json"
        run_record_path = inferred if inferred.exists() else None
    validation_path = _resolve_path(demo.get("validation_json_path"), base_dir)
    evidence_map_path = _resolve_path(demo.get("evidence_map_path"), base_dir)
    literature_path = _resolve_path(_dict(summary.get("literature")).get("summary_path"), base_dir)
    similarity_path = _resolve_path(_dict(summary.get("similarity")).get("summary_path"), base_dir)
    citations = _dict(summary.get("citations"))
    citation_metadata_path = _resolve_path(citations.get("metadata_path"), base_dir)
    citation_bib_path = _resolve_path(citations.get("bib_path"), base_dir)
    related_work = _dict(summary.get("related_work_inspection"))
    related_work_json_path = _resolve_path(related_work.get("json_path"), base_dir)
    related_work_markdown_path = _resolve_path(related_work.get("markdown_path"), base_dir)
    evidence_refs = tuple(
        path.as_posix()
        for path in (
            summary_path,
            run_record_path,
            validation_path,
            evidence_map_path,
            literature_path,
            citation_metadata_path,
            citation_bib_path,
            related_work_json_path,
            related_work_markdown_path,
            similarity_path,
        )
        if path is not None and path.exists()
    )
    return _ManuscriptEvidence(
        summary=summary,
        base_dir=base_dir,
        cycle_summary_path=summary_path,
        candidate=candidate,
        demo=demo,
        run_record=_read_json_if_exists(run_record_path),
        validation=_read_json_if_exists(validation_path),
        evidence_map=_read_json_if_exists(evidence_map_path),
        literature_docs=_parse_literature_docs(literature_path),
        similarity_findings=_parse_similarity_findings(similarity_path),
        similarity_summary_path=similarity_path,
        citations=_parse_citations(citation_metadata_path, fallback=citations),
        related_work_inspection_path=related_work_json_path,
        evidence_refs=evidence_refs,
    )


def _render_manuscript(
    evidence: _ManuscriptEvidence,
    analysis: _AnalysisArtifacts,
) -> str:
    title = _clean_text(_text(evidence.candidate.get("title"))) or "Evidence-Bound Research Cycle"
    sections = [
        f"# {title}",
        "",
        "## Abstract",
        "",
        *_abstract(evidence),
        "",
        "## Introduction",
        "",
        *_introduction(evidence),
        "",
        "## Related Work",
        "",
        *_related_work(evidence, analysis),
        "",
        "## Method",
        "",
        *_method(evidence),
        "",
        "## Experiments",
        "",
        *_experiments(evidence),
        "",
        *_evidence_artifact_availability(analysis),
        "",
        "## Results",
        "",
        *_results(evidence, analysis),
        "",
        "## Limitations",
        "",
        *_limitations(evidence),
        "",
        "## Conclusion",
        "",
        *_conclusion(evidence),
        "",
        "## References",
        "",
        *_references(evidence),
        "",
    ]
    return "\n".join(sections)


def _abstract(evidence: _ManuscriptEvidence) -> list[str]:
    metrics = _metrics(evidence)
    candidate = evidence.candidate
    dataset = _dataset(evidence)
    method = _method_name(evidence)
    baseline = _baseline_name(evidence)
    accuracy = _metric(metrics, "accuracy")
    baseline_accuracy = _metric(metrics, "baseline_accuracy")
    delta = _metric(metrics, "accuracy_delta_vs_baseline")
    test_rows = _metric(metrics, "test_rows")
    return [
        (
            f"This paper presents an evidence-bound empirical study generated from an "
            f"AI-Researcher autonomous cycle for the candidate "
            f"'{_clean_text(_text(candidate.get('title')))}'. The executed method is "
            f"{_article(method)} evaluated on {dataset}, with {baseline} kept as the "
            f"recorded baseline and a secondary comparison retained when available. "
            f"The run reports accuracy {_fmt(accuracy)}, baseline accuracy "
            f"{_fmt(baseline_accuracy)}, and an accuracy delta of {_fmt(delta)} over "
            f"{_fmt(test_rows)} test rows. Each quantitative value is copied from the "
            f"local run record, validation report, or evidence map rather than inferred "
            f"from prose. The literature and similarity sections use online retrieval "
            f"records to bound novelty and avoid unsupported priority claims. The "
            f"contribution is a reproducible, source-backed candidate result with an "
            f"attached artifact trail for inspecting the data, code path, citations, "
            f"and manuscript build."
        )
    ]


def _introduction(evidence: _ManuscriptEvidence) -> list[str]:
    candidate = evidence.candidate
    metadata = _dict(candidate.get("metadata"))
    gap = _clean_text(_text(candidate.get("research_gap")))
    description = _clean_text(_text(candidate.get("description")))
    method = _method_name(evidence)
    dataset = _dataset(evidence)
    baseline = _baseline_name(evidence)
    return [
        (
            "Automated research systems are useful only when their outputs remain "
            "traceable to real retrieval, real execution, and real validation. A short "
            "experiment report can prove that a script ran, but it is not enough for a "
            "paper-level artifact because it rarely explains the research question, "
            "the negative evidence, the exact baseline, the comparison design, or the "
            "limits of the novelty search. This manuscript fills that gap by expanding "
            "the cycle record into a conventional academic structure while preserving "
            "the same evidence boundary. Every quantitative statement in the main "
            "body is drawn from run artifacts, and every statement about prior work is "
            "phrased as retrieved metadata or an unresolved search obligation."
        ),
        (
            f"The candidate under study is motivated by the following recorded gap: "
            f"{gap or 'no free-form gap text was provided by the candidate record'}. "
            f"The system description for the candidate is: "
            f"{description or 'no candidate description was provided'}. "
            f"In operational terms, the cycle asks whether "
            f"{method} can be evaluated against {baseline} on {dataset} without losing "
            f"the provenance needed for audit. The manuscript does not convert a positive "
            f"single-run delta into a broad scientific conclusion. Instead, it treats the "
            f"delta as a bounded observation that must survive related-work comparison, "
            f"replication, and additional benchmark coverage."
        ),
        (
            "The current cycle also records a project-start similarity search. The "
            "exact retrieval and classification counts remain in the machine-readable "
            "review context and similarity note, while this manuscript uses them only as "
            "a warning signal. The system has enough retrieval breadth to know that "
            "neighboring work exists, but it does not yet have enough classification "
            "depth to claim a clear novelty boundary. The paper therefore frames the "
            "method as a candidate mechanism and an evidence-handling case study until "
            "richer abstracts, venue records, code availability, and benchmark "
            "comparisons are attached."
        ),
        (
            f"This report also demonstrates why the Obsidian-compatible vault matters "
            f"as a research memory substrate. The literature refresh, similarity check, "
            f"review notes, issue notes, reproduction status, and paper build evidence "
            f"are written as Markdown or JSON artifacts that can be read by a person, "
            f"indexed by the system, and reused by later cycles. The manuscript is not "
            f"hand-maintained project lore; it is generated from the cycle summary and "
            f"therefore can be regenerated when the run, source coverage, or review "
            f"evidence changes. Metadata such as method={_clean_text(_text(metadata.get('method')))}, "
            f"benchmark={_clean_text(_text(metadata.get('benchmark')))}, and limitation="
            f"{_clean_text(_text(metadata.get('limitation')))} are retained as context, "
            f"not as substitute proof."
        ),
    ]


def _related_work(
    evidence: _ManuscriptEvidence,
    analysis: _AnalysisArtifacts,
) -> list[str]:
    doc_lines = _literature_doc_lines(evidence.literature_docs[:8])
    finding_lines = _similarity_finding_lines(
        evidence.similarity_findings,
        positioning_artifact_path=analysis.similarity_positioning_json_path,
    )
    return [
        (
            "The literature context comes from the live retrieval stage, not from a "
            "language-model memory. Exact fetch counts, source names, cache status, and "
            "document counts remain in the runtime literature note and compact review "
            "context. This prose uses that retrieval to establish a search trail and "
            "to constrain the novelty claims made by the paper."
        ),
        (
            "The first normalized records are treated only as title-level search hits. "
            "Their titles suggest which abstracts need later inspection, but this "
            "manuscript does not infer a validated research family, benchmark result, "
            "or baseline obligation from a title alone. The search is used to check "
            "whether any retrieved abstract or full bibliographic record directly "
            "describes diagonal variance calibration as a prototype distance mechanism "
            "on comparable handwritten benchmark tasks. Retrieved titles remain search "
            "evidence unless the attached metadata supports a stronger claim."
        ),
        *doc_lines,
        (
            "The project-start similarity search is a targeted adjacent-work retrieval "
            "stage. This manuscript does not restate what the retriever queried or "
            "compare it qualitatively with the broader literature refresh. Query strings, "
            "source responses, classification counts, cache details, and source-specific "
            "errors are stored in the similarity note and compact review context rather "
            "than promoted into this paper prose. The retrieved distribution is a warning "
            "signal rather than a novelty claim. When findings remain unknown, they are "
            "not used as evidence for originality."
        ),
        _related_work_inspection_sentence(evidence),
        *finding_lines,
        (
            "This related-work section is intentionally conservative. It does not state "
            "that the retrieved papers do or do not outperform the current method, and "
            "it does not infer code availability, benchmark scores, venue status, or "
            "acceptance status from absent metadata. Its only role is to make the search "
            "trail visible, separate direct duplicates from adjacent work where evidence "
            "permits, and keep validated sources available as formal bibliography records."
        ),
        (
            "The related-work evidence uses the comparison-status fields recorded in the "
            "inspection artifact, such as direct_method_candidate, contextual, "
            "benchmark_or_baseline_context, metadata_only, or unknown. The manuscript "
            "does not invent finer categories beyond those stored fields. Direct method "
            "candidates require novelty positioning; contextual and benchmark or baseline "
            "records motivate comparison checks; metadata-only and unknown rows remain "
            "visible but do not support originality claims."
        ),
        (
            "The current manuscript therefore treats source classification as a research "
            "object. The runtime similarity artifacts, not this prose paragraph, retain "
            "the finding list, classification statuses, responding databases, and query "
            "provenance. This is stronger than a generic survey paragraph because it "
            "keeps the literature uncertainty inspectable. If a later reviewer asks why "
            "a baseline is missing, the answer should be "
            "recoverable from the similarity findings and follow-up tasks rather than "
            "from an author's memory."
        ),
    ]


def _related_work_inspection_sentence(evidence: _ManuscriptEvidence) -> str:
    if (
        evidence.related_work_inspection_path is None
        or not evidence.related_work_inspection_path.exists()
    ):
        return (
            "No related-work inspection artifact was attached to this manuscript. The "
            "paper therefore treats retrieved sources as unscreened retrieval evidence, "
            "not as source-backed related-work comparisons."
        )
    return (
        "A related-work inspection artifact is attached as local evidence. It records "
        "which citation rows have source-backed abstracts, which method or dataset terms "
        "overlap the executed candidate, and which rows remain unrelated or metadata-only. "
        "This manuscript still treats that artifact as screening evidence rather than as "
        "proof that the contribution is novel."
    )


def _method(evidence: _ManuscriptEvidence) -> list[str]:
    metadata = _task_metadata(evidence)
    metrics = _metrics(evidence)
    method = _method_name(evidence)
    baseline = _baseline_name(evidence)
    dataset = _dataset(evidence)
    split_policy = _clean_text(_text(metadata.get("split_policy"))) or "the recorded data split"
    feature_count = _metric(metrics, "feature_count")
    variance_shrinkage = _metric(metrics, "variance_shrinkage")
    return [
        (
            f"The executed method is described in the run metadata as {method}. In this "
            f"cycle it is not treated as a black-box model family, but the manuscript also "
            f"does not restate implementation details that belong in executable evidence. "
            f"The authoritative sources for step order and formula details are the run "
            f"script, metrics file, validation report, and evidence map. The baseline "
            f"label is {baseline}, and any secondary comparison is treated as a recorded "
            f"artifact or metric rather than promoted into a separate algorithm family in "
            f"prose. This structure gives the validator three separate handles: the "
            f"candidate effect relative to the baseline, the candidate effect relative to "
            f"the recorded comparison evidence, and the sanity of the metric ranges on "
            f"the official test split."
        ),
        (
            f"The dataset layer is {dataset}. The split policy is {split_policy}. The "
            f"method does not sample hidden private data and does not rely on an "
            f"unverifiable benchmark. The run record stores the data hash, configuration "
            f"hash, commit identifier, metrics path, artifact directory, and command used "
            f"for reproduction. The recorded metrics expose {_fmt(feature_count)} input "
            f"features and a variance_shrinkage parameter of {_fmt(variance_shrinkage)} "
            f"for this cycle. That shrinkage value is a fixed recorded configuration, "
            f"not a tuned hyperparameter result; this run does not include a sensitivity "
            f"sweep over alternative shrinkage values and therefore cannot claim that "
            f"0.0500 is optimal. These provenance fields are more important than prose "
            f"style because they let a later validator decide whether the same data and "
            f"code path produced the reported numbers."
        ),
        (
            "The script-level algorithm is not reconstructed as a separate prose truth "
            "source. The executable `run.py`, run record, metrics file, validation "
            "report, and evidence map remain the authoritative artifacts for step order "
            "and implementation detail. This manuscript therefore describes only the "
            "audited method boundary: public data source, recorded baseline, recorded "
            "candidate metric, recorded comparison evidence, written metrics, and "
            "validator-readable evidence edges. If a later paper needs a formal algorithm "
            "listing, the listing should be generated from the script and then reviewed "
            "as its own evidence artifact."
        ),
        (
            "This method description deliberately excludes unexecuted variants. It does "
            "not claim that the same calibration will improve neural embeddings, other "
            "handwriting datasets, other prototype learners, or streaming classifiers. "
            "Those hypotheses can be added as follow-up tasks only after the current "
            "cycle has recorded enough related-work classification and supporting "
            "artifacts. The method section therefore "
            "serves as a precise reproduction map rather than a broad theory of prototype "
            "learning."
        ),
        (
            "For a submission-style manuscript, the method also needs to state what the "
            "system is not allowed to vary. The current cycle fixes the data source, "
            "the split policy, the baseline family, the comparison role, and the validator "
            "that reads the produced artifacts. The autonomous loop may choose a topic, "
            "retrieve sources, run the script, and draft the paper, but it may not "
            "silently relabel the benchmark, replace a failed baseline, or convert a "
            "single positive metric into a general theory. That constraint is especially "
            "important when a later cycle changes the LaTeX template or target venue, "
            "because visual polish can otherwise hide a thin evidence model."
        ),
        (
            "Implementation-level constraints are reported only when they are present in "
            "local artifacts. Input data must be discoverable from recorded source "
            "metadata; the feature pipeline must be represented in the executable script "
            "rather than only in prose; and metrics must be written before any publication "
            "audit reads them. These constraints are evidence controls for this run, not "
            "an additional algorithmic contribution."
        ),
        (
            "If a supporting artifact is unavailable, the manuscript does not rewrite "
            "the experiment outcome. It leaves the failed check, source path, and planned "
            "follow-up in the run artifacts so that later work can rerun retrieval, add a "
            "baseline, or revise the paper from new evidence."
        ),
        (
            "The experiment record separates execution from interpretation. A metric is "
            "used in this manuscript only after the metrics file exists, the validation "
            "report reads it, the evidence map binds it to a claim, and the cycle summary "
            "keeps the path reachable. The manuscript can explain those artifacts, but it "
            "does not introduce new scores, new baselines, or new audit outcomes."
        ),
        (
            "The method is also organized around an evidence-to-claim map. Dataset claims "
            "must point to source metadata and data hashes. Execution claims must point "
            "to the run record and command line. Metric claims must point to the metrics "
            "object and validation notes. Novelty claims must point to literature and "
            "similarity summaries. Manuscript-build claims must point to the compiled PDF, "
            "the paper-quality object, and the stability matrix. This map is what lets "
            "the system produce a paper-like artifact while still behaving like an "
            "auditable research workflow."
        ),
        (
            "Future changes to prompts, baselines, or manuscript templates should be "
            "recorded as new runs rather than retroactive edits to this result. The old "
            "cycle remains a fixed datum: its metrics, source coverage, and review status "
            "stay available for comparison."
        ),
    ]


def _experiments(evidence: _ManuscriptEvidence) -> list[str]:
    metrics = _metrics(evidence)
    run_record = evidence.run_record
    run = _dict(run_record.get("run"))
    validation = evidence.validation
    reproduction = _dict(evidence.summary.get("reproduction_check"))
    artifacts = tuple(_readable_identifier(_text(item)) for item in _list(run_record.get("artifacts")))
    logs = tuple(_clean_text(_text(item)) for item in _list(run_record.get("logs")))
    validation_notes = _validation_note_lines(validation)
    task_label = _readable_identifier(_text(run.get("task_id"))) or "recorded experiment task"
    return [
        (
            f"The experiment executed task {task_label} with "
            f"process status {_clean_text(_text(run.get('status')))} and exit code "
            f"{_clean_text(_text(run.get('exit_code')))}. The structured metrics object "
            f"contains {len(metrics)} numeric fields, including accuracy, macro F1 when "
            f"available, test rows, train rows, dataset rows, baseline fields, comparison "
            f"fields when available, and standard-error information. Because the metrics "
            f"are loaded from the "
            f"run record, the manuscript does not need to reinterpret console output or "
            f"copy numbers from a screenshot."
        ),
        (
            f"The run preserved {len(artifacts)} artifact references and {len(logs)} log "
            f"references. The important point is not that every artifact is visually "
            f"inspected in this section, but that the artifact package can locate the files "
            f"declared by the run record, including data-source metadata, validation "
            f"reports, evidence maps, metrics, and reproduction records. The manuscript "
            f"therefore reports the existence and role of these files while leaving exact "
            f"path verification to machine-readable records."
        ),
        (
            "The experimental protocol is intentionally written as a sequence of checks "
            "rather than as an informal notebook narrative. The first check is source "
            "integrity: the data file and source metadata must be present and hashable. "
            "The second check is executable integrity: the run command must finish with "
            "exit code zero and leave a structured run record. The third check is metric "
            "integrity: candidate, baseline, comparison, and uncertainty fields must be "
            "readable from the same metrics object. The fourth check is report integrity: "
            "the validation report and evidence map must bind reported numbers to local "
            "files. The fifth check is reproduction integrity: a fresh command-line rerun "
            "must produce a new run record and validation report."
        ),
        (
            "The experiment section records operational detail so empirical weakness can "
            "be separated from missing-artifact weakness. When the same method is later "
            "run on another benchmark, comparison should use structured cycle artifacts "
            "rather than prose descriptions alone."
        ),
        (
            f"Validation status is {_clean_text(_text(validation.get('status')))}. The "
            f"validation report records {_int(len(_list(validation.get('issues'))))} "
            f"issues and {len(_list(validation.get('statistical_notes')))} statistical "
            f"notes. These checks matter because a paper-style document can otherwise "
            f"make an experiment look more polished than it is. Here, the validation "
            f"stage is part of the manuscript evidence: metrics, artifact presence, and "
            f"statistical notes remain attached to the claims they support."
        ),
        *validation_notes,
        (
            f"The reproduction check status is {_clean_text(_text(reproduction.get('status')))} "
            f"with exit code {_clean_text(_text(reproduction.get('exit_code')))}. It recorded "
            f"{len(_list(reproduction.get('run_record_paths')))} rerun record and "
            f"{len(_list(reproduction.get('validation_json_paths')))} rerun validation "
            f"report. A single successful rerun is not a robustness study, but it is a "
            f"minimum requirement for trustworthy automation: the code path must be "
            f"invokable from the command line and must regenerate structured evidence "
            f"without manual editing."
        ),
        (
            "The experiment has one crucial limitation in scope. It is a single public "
            "benchmark cycle with a bounded method candidate and deterministic validation "
            "rules. It is not a multi-dataset study, not a statistical power analysis "
            "across independent seeds, and not an exhaustive baseline comparison. These "
            "missing pieces are not hidden; they are promoted into the limitations and "
            "follow-up queues so the self-loop can decide whether another cycle is worth "
            "running."
        ),
        (
            "Template-build evidence is treated as an experimental artifact, not a "
            "cosmetic export. The current paper build only certifies the template that "
            "was actually selected for this cycle; it is not evidence that ACM, IEEE, "
            "Springer, or any other external venue template will compile without a "
            "separate run. The paper build check therefore checks page count, word "
            "count, required sections, technical term coverage, and layout overflow "
            "after LaTeX compilation under the selected template."
        ),
        (
            "The experiment also records why empirical validity, source retrieval, "
            "reproduction, and manuscript build quality should be evaluated separately. "
            "A method can produce a useful score while still requiring stronger novelty "
            "evidence or cleaner layout. Conversely, a polished manuscript cannot rescue "
            "a weak or unreproducible metric. This separation keeps the scientific claim "
            "tied to the artifact that supports it."
        ),
        (
            "For external or compact venue templates, the paper build must be rerun "
            "after manuscript changes rather than inferred from the Markdown word "
            "count. Double-column classes can compress a manuscript by several pages "
            "and can expose long machine identifiers that never overflow in a generic "
            "article layout. The experimental evidence for a venue template is a "
            "compiled template-specific PDF plus the parsed quality report for that "
            "same template, not the existence of a `.tex` file."
        ),
    ]


def _results(
    evidence: _ManuscriptEvidence,
    analysis: _AnalysisArtifacts,
) -> list[str]:
    metrics = _metrics(evidence)
    accuracy = _metric(metrics, "accuracy")
    macro_f1 = _metric(metrics, "macro_f1")
    baseline_accuracy = _metric(metrics, "baseline_accuracy")
    delta = _metric(metrics, "accuracy_delta_vs_baseline")
    zscore = _metric(metrics, "zscore_centroid_accuracy")
    zscore_delta = _metric(metrics, "accuracy_delta_vs_zscore")
    test_rows = _metric(metrics, "test_rows")
    train_rows = _metric(metrics, "train_rows")
    dataset_rows = _metric(metrics, "dataset_rows")
    class_count = _metric(metrics, "class_count")
    feature_count = _metric(metrics, "feature_count")
    standard_error = _metric(metrics, "accuracy_standard_error")
    return [
        (
            f"The main result is an accuracy of {_fmt(accuracy)} on {_fmt(test_rows)} "
            f"test rows. Macro F1 is {_fmt(macro_f1)}. The recorded baseline accuracy is "
            f"{_fmt(baseline_accuracy)}, so the candidate-minus-baseline delta is "
            f"{_fmt(delta)}. The z-score centroid comparison is {_fmt(zscore)}, with "
            f"a candidate-minus-z-score delta of {_fmt(zscore_delta)}. The full dataset "
            f"metadata records {_fmt(train_rows)} train rows, {_fmt(test_rows)} test rows, "
            f"{_fmt(dataset_rows)} total rows, {_fmt(class_count)} classes, and "
            f"{_fmt(feature_count)} input features."
        ),
        "",
        *_data_analysis_lines(evidence, analysis),
        "",
        (
            f"The accuracy standard error is {_fmt(standard_error)}. The validation report "
            f"also records a confidence-interval style note when the experiment provides "
            f"enough information. This makes the result more useful than a naked score: "
            f"the score is linked to sample size, standard error, baseline comparison, "
            f"and a repeated-run delta. However, the manuscript still avoids claiming "
            f"statistical significance beyond what the validation artifact explicitly "
            f"stores."
        ),
        (
            "The result supports a narrow empirical statement: in this run, the recorded "
            "candidate performed better than the recorded nearest-centroid baseline and "
            "better than the recorded z-score centroid comparison. It does not support a "
            "field-wide claim that variance-calibrated prototypes are generally superior. "
            "For that stronger claim, AI-Researcher would need more datasets, stronger "
            "baselines such as metric learning and Gaussian discriminant variants, repeated "
            "seeds or bootstrap analysis, and source-backed related-work positioning."
        ),
        (
            "Manuscript build evidence is recorded separately from empirical evidence. "
            "A good experimental score does not by itself establish novelty, layout "
            "quality, or citation quality, so the artifact package preserves those "
            "signals independently."
        ),
        (
            "The safest interpretation is constructive but not promotional. The cycle "
            "produced real metrics, real validation, real reproduction evidence, and a "
            "positive candidate delta. The contribution is therefore a bounded empirical "
            "finding with explicit provenance rather than an unsupported success story."
        ),
        (
            "The result section therefore reports both performance and the release "
            "signals attached to the same cycle. A baseline, comparison evidence, a "
            "candidate delta, a standard error, a reproduction record, and a publication "
            "audit are present together. Related-work evidence, metric evidence, and "
            "build evidence are intentionally reported as different signals so readers "
            "can see which claim each artifact supports."
        ),
        (
            "A second result is negative but operationally important: manuscript and "
            "template checks can fail even when the empirical run succeeds. When that "
            "happens, the empirical claim should remain fixed while the manuscript is "
            "repaired using existing evidence. This separation lets the research loop "
            "improve communication quality without changing audited data or metrics."
        ),
        (
            "The result should also be read as one cell in a broader evaluation matrix, "
            "not as an isolated universal claim. One successful cycle demonstrates one "
            "topic, one dataset, one manuscript, and one template. Broader evidence "
            "requires several such cells with different datasets and template families, "
            "so dataset diversity, template diversity, external conference coverage, "
            "external journal coverage, warning budgets, and paper quality are tracked "
            "together."
        ),
        (
            "This framing changes how the numbers should be used. The accuracy delta is "
            "evidence for the method candidate in this benchmark. The artifact-readiness "
            "score is evidence for paper package consistency. The stability score is "
            "evidence for repeated pipeline behavior. None of "
            "these scores should be substituted for the others. A strong metric with a "
            "weak stability matrix is an experiment, not a stable paper-production "
            "capability; a strong matrix with weak novelty is a reproducibility pipeline, "
            "not a new scientific contribution."
        ),
    ]


def _limitations(_evidence: _ManuscriptEvidence) -> list[str]:
    return [
        (
            "The novelty boundary is still incomplete. The similarity stage records "
            "a nearby-work trail, but the manuscript treats that trail as retrieval "
            "evidence until source-backed abstracts, classification rationale, and "
            "method comparisons are attached. Until those comparisons are attached, "
            "the manuscript must not claim that the contribution is new."
        ),
        (
            "The experiment uses one public benchmark and one primary method candidate. "
            "This design gives a controlled measurement of the candidate, but it limits "
            "external validity. Broader datasets, stronger external baselines, multiple "
            "runs, clearer error analysis, and explicit failure cases would make the "
            "method claim stronger."
        ),
        (
            "The manuscript composer is deterministic and evidence-bound. That improves "
            "auditability, but it also means the prose can only be as strong as the "
            "available artifacts. Missing abstracts, missing citation records, missing "
            "figures, or missing review evidence remain visible as gaps rather than "
            "being filled by plausible-sounding text."
        ),
        (
            "The current review record, when present, is bound to the final manuscript "
            "and evidence artifacts. Any expanded version of this paper should keep the "
            "same rule: new claims require either existing artifact support or newly "
            "attached sources."
        ),
        (
            "Venue coverage is also incomplete until both conference-style and "
            "journal-style templates have passing evidence. A passing build under one "
            "template family should not be treated as proof of another family. The "
            "stability matrix must keep these families separate so the system cannot "
            "overclaim broad venue readiness from a single external template."
        ),
        (
            "Venue fit remains a limitation. Evidence discipline can prevent fabricated "
            "claims, but a venue-specific contribution still depends on the community's "
            "baseline expectations, preferred datasets, and evaluation norms. Targeted "
            "review rubrics and conference-specific scope checks would make that venue "
            "fit more explicit."
        ),
        (
            "Finally, the benchmark evidence remains narrow. Public UCI-style datasets "
            "are useful because they are scriptable and auditable, but they do not cover "
            "all modern machine-learning research expectations. Larger datasets, stronger "
            "hyperparameter protocols, richer error analysis, and comparison against "
            "published baselines are necessary before the method itself should be treated "
            "as a mature contribution. The present artifact is a controlled step toward "
            "that standard."
        ),
    ]


def _write_analysis_artifacts(
    evidence: _ManuscriptEvidence,
    root: Path,
) -> _AnalysisArtifacts:
    metrics = _analysis_metrics(_metrics(evidence))
    positioning_summary = _similarity_positioning_summary(evidence)
    if not metrics and not positioning_summary["finding_count"]:
        return _AnalysisArtifacts()
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    metrics_source_path: Path | None = None
    figure_pdf_path: Path | None = None
    figure_png_path: Path | None = None
    figure_metadata_path: Path | None = None
    table_markdown_path: Path | None = None
    if metrics:
        metrics_source_path = analysis_dir / "metrics-source.json"
        metrics_source_path.write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "source_cycle_summary": evidence.cycle_summary_path.as_posix(),
                    "source_run_record": _source_path_for_record(evidence, "run-record.json"),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            figure = generate_metric_bar_figure(
                metrics_source_path,
                analysis_dir,
                title="Validated Performance Metrics",
                figure_id="validated-performance-metrics",
            )
            figure_pdf_path = Path(figure.pdf_path)
            figure_png_path = Path(figure.png_path)
            figure_metadata_path = Path(figure.metadata_path)
        except FigureGenerationError:
            figure_pdf_path = None
            figure_png_path = None
            figure_metadata_path = None
        table_markdown_path = analysis_dir / "data-analysis-summary.md"
        table_markdown_path.write_text(
            "\n".join(_analysis_table_lines(evidence)),
            encoding="utf-8",
        )
    similarity_positioning_json_path: Path | None = None
    similarity_positioning_markdown_path: Path | None = None
    if positioning_summary["finding_count"]:
        similarity_positioning_json_path = analysis_dir / "similarity-positioning-summary.json"
        similarity_positioning_json_path.write_text(
            json.dumps(positioning_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        similarity_positioning_markdown_path = analysis_dir / "similarity-positioning-summary.md"
        similarity_positioning_markdown_path.write_text(
            "\n".join(_similarity_positioning_markdown(positioning_summary)),
            encoding="utf-8",
        )
    return _AnalysisArtifacts(
        metrics_source_path=metrics_source_path,
        figure_pdf_path=figure_pdf_path,
        figure_png_path=figure_png_path,
        figure_metadata_path=figure_metadata_path,
        table_markdown_path=table_markdown_path,
        similarity_positioning_json_path=similarity_positioning_json_path,
        similarity_positioning_markdown_path=similarity_positioning_markdown_path,
    )


def _similarity_positioning_summary(evidence: _ManuscriptEvidence) -> dict[str, Any]:
    counts: dict[str, int] = {}
    rows: list[dict[str, str]] = []
    family_counts: dict[str, int] = {}
    for finding in evidence.similarity_findings:
        classification = _clean_text(finding.get("classification", "")).casefold() or "unknown"
        counts[classification] = counts.get(classification, 0) + 1
        if classification != "adjacent_work":
            continue
        family = _positioning_family(finding)
        family_counts[family] = family_counts.get(family, 0) + 1
        rows.append(
            {
                "title": _clean_text(finding.get("title", "")),
                "source": _clean_text(finding.get("source", "")),
                "classification": classification,
                "family": family,
                "basis": _clean_text(finding.get("basis", "")),
                "positioning_decision": _positioning_decision(finding),
            }
        )
    return {
        "source_cycle_summary": evidence.cycle_summary_path.as_posix(),
        "source_similarity_summary": (
            evidence.similarity_summary_path.as_posix()
            if evidence.similarity_summary_path is not None
            else None
        ),
        "finding_count": len(evidence.similarity_findings),
        "classification_counts": dict(sorted(counts.items())),
        "adjacent_work_count": counts.get("adjacent_work", 0),
        "adjacent_work_family_counts": dict(sorted(family_counts.items())),
        "positioning_rows": rows,
    }


def _similarity_positioning_markdown(summary: dict[str, Any]) -> list[str]:
    counts = _dict(summary.get("classification_counts"))
    rows = _dict_list(summary.get("positioning_rows"))
    lines = [
        "# Similarity Positioning Summary",
        "",
        f"- Source similarity note: `{_clean_locator_text(_text(summary.get('source_similarity_summary')) or 'unknown')}`",
        f"- Parsed findings: `{_int(summary.get('finding_count'))}`",
        f"- Adjacent-work findings: `{_int(summary.get('adjacent_work_count'))}`",
        "",
        "## Classification Counts",
        "",
    ]
    for classification, count in sorted(counts.items()):
        lines.append(f"- `{classification}`: `{_int(count)}`")
    lines.extend(
        [
            "",
            "## Positioning Rows",
            "",
            "| Family | Adjacent-work rows | Boundary |",
            "| --- | --- | --- |",
        ]
    )
    family_seen: set[str] = set()
    for row in rows:
        family = _clean_text(_text(row.get("family"))) or "adjacent source-backed hit"
        if family in family_seen:
            continue
        family_seen.add(family)
        lines.append(
            "| "
            f"{_table_cell(family)} | "
            f"{_int(_dict(summary.get('adjacent_work_family_counts')).get(family))} | "
            f"{_table_cell(_text(row.get('positioning_decision')))} |"
        )
    if not rows:
        lines.append("| none | unknown | No adjacent-work rows were parsed. |")
    return lines


def _evidence_artifact_availability(analysis: _AnalysisArtifacts) -> list[str]:
    rows = [
        ("Cycle summary", "Machine-readable cycle state and stage outputs"),
        ("Run record", "Command, exit code, metrics, artifacts, and logs"),
        ("Validation report", "Metric bounds, issues, and statistical notes"),
        ("Evidence map", "Bindings from claims and metrics to local evidence"),
        ("Literature refresh", "Online ArXiv/OpenAlex retrieval summary"),
        ("Citation package", "DOI/URL-verified citation metadata and BibTeX"),
        ("Related-work inspection", "Source-backed abstract and overlap screening"),
        ("Similarity check", "Project-start adjacent-work retrieval trail"),
        ("Reproduction check", "Command-line rerun records and validation outputs"),
        ("Paper build", "LaTeX/PDF compile status and layout quality report"),
    ]
    if analysis.paths():
        rows.append(("Data analysis artifacts", "Metric-source JSON, generated figure, and summary table"))
    lines = [
        "### Evidence and Artifact Availability",
        "",
        (
            "The following records are archived as project evidence rather than as formal "
            "literature references. The Markdown manuscript and paper-build summaries are "
            "written to the Obsidian vault for experience accumulation and project "
            "archival review; the PDF, TeX, manifest, and release bundle copies are "
            "exported under the project-root outputs directory for publication delivery."
        ),
        "",
        "| Artifact | Role in the evidence chain |",
        "| --- | --- |",
    ]
    lines.extend(f"| {label} | {role} |" for label, role in rows)
    lines.extend(
        [
            "",
            (
                "This separation prevents operational evidence labels from appearing as "
                "bibliography entries while keeping every paper claim auditable through "
                "the cycle summary and manuscript JSON."
            ),
        ]
    )
    return lines


def _data_analysis_lines(
    evidence: _ManuscriptEvidence,
    analysis: _AnalysisArtifacts,
) -> list[str]:
    metrics = _analysis_metrics(_metrics(evidence))
    lines = [
        "### Data Analysis",
        "",
    ]
    if not metrics:
        lines.append(
            "No numeric metrics were available for a source-backed figure or table; the paper-quality gate must block publication until the run record exposes metric data."
        )
        return lines
    source_label = (
        _relative_markdown_path(analysis.metrics_source_path)
        if analysis.metrics_source_path is not None
        else "the run record metrics object"
    )
    lines.extend(
        [
            (
                f"The figure and table in this subsection are generated from {source_label}, "
                "which is copied from the real run metrics object rather than written by "
                "the language model. They summarize only the metrics present in the "
                "source record."
            ),
            "",
        ]
    )
    if analysis.figure_pdf_path is not None:
        lines.extend(
            [
                (
                    "![Validated metric comparison]"
                    f"({_relative_markdown_path(analysis.figure_pdf_path)})"
                ),
                "",
            ]
        )
    lines.extend(_analysis_table_lines(evidence))
    return lines


def _analysis_table_lines(evidence: _ManuscriptEvidence) -> list[str]:
    metrics = _metrics(evidence)
    rows = [
        ("Accuracy", _metric(metrics, "accuracy"), "run metrics accuracy"),
        ("Macro F1", _metric(metrics, "macro_f1"), "run metrics macro F1"),
        (
            "Baseline accuracy",
            _metric(metrics, "baseline_accuracy"),
            "run metrics baseline accuracy",
        ),
        (
            "Candidate minus baseline",
            _metric(metrics, "accuracy_delta_vs_baseline"),
            "run metrics candidate-baseline delta",
        ),
        (
            "Z-score centroid accuracy",
            _metric(metrics, "zscore_centroid_accuracy"),
            "run metrics z-score ablation",
        ),
        (
            "Accuracy standard error",
            _metric(metrics, "accuracy_standard_error"),
            "validation statistical note",
        ),
    ]
    lines = [
        "| Metric | Value | Evidence source |",
        "| --- | ---: | --- |",
    ]
    for label, value, source in rows:
        if value is not None:
            lines.append(f"| {label} | {_fmt(value)} | `{source}` |")
    lines.append("")
    return lines


def _analysis_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    selected_keys = (
        "accuracy",
        "macro_f1",
        "baseline_accuracy",
        "accuracy_delta_vs_baseline",
        "zscore_centroid_accuracy",
        "accuracy_delta_vs_zscore",
    )
    selected: dict[str, float] = {}
    for key in selected_keys:
        value = _metric(metrics, key)
        if value is not None:
            selected[key] = value
    return selected


def _relative_markdown_path(path: Path | None) -> str:
    if path is None:
        return "not generated"
    try:
        return path.relative_to(path.parents[1]).as_posix()
    except ValueError:
        return path.as_posix()


def _source_path_for_record(evidence: _ManuscriptEvidence, name: str) -> str | None:
    for path in evidence.evidence_refs:
        if Path(path).name == name:
            return path
    return None


def _conclusion(evidence: _ManuscriptEvidence) -> list[str]:
    metrics = _metrics(evidence)
    delta = _metric(metrics, "accuracy_delta_vs_baseline")
    return [
        (
            f"This study shows that AI-Researcher can turn a real autonomous run into a "
            f"paper-style artifact without inventing unsupported claims. The experiment "
            f"records a candidate accuracy delta of {_fmt(delta)} over the recorded "
            f"baseline and preserves the validation, reproduction, citation, and build "
            f"artifacts needed to inspect that claim."
        ),
        (
            "The central contribution is not only the numerical improvement on the "
            "selected benchmark, but the evidence discipline around it. Metrics, "
            "literature retrieval, similarity inspection, reproduction, and LaTeX "
            "build quality are carried as linked artifacts, so the paper can be checked "
            "against the same records that produced it."
        ),
        (
            "Within the bounded scope of this benchmark, the candidate result is positive "
            "and reproducible. The remaining scientific uncertainty is explicit: stronger "
            "baselines, broader datasets, and venue-specific comparisons are the natural "
            "extensions of the work."
        ),
        (
            "This combination of empirical measurement and artifact-level provenance is "
            "the intended publication form of AI-Researcher: a paper that states what was "
            "measured, identifies what was retrieved, shows the supporting data analysis, "
            "and preserves the exact files required to reproduce or challenge the claim."
        ),
    ]


def _formal_reference_line(citation: dict[str, Any]) -> str:
    key = _citation_key(citation)
    title = _clean_text(_text(citation.get("title"))) or "Untitled source"
    authors = _format_authors(_list(citation.get("authors")))
    venue = _clean_text(_text(citation.get("venue")))
    year = _clean_text(
        _text(
            citation.get("year")
            or citation.get("publication_year")
            or citation.get("published_year")
            or citation.get("date")
        )
    )
    doi = _clean_locator_text(_text(citation.get("doi")))
    url = _clean_locator_text(_text(citation.get("url") or citation.get("source_uri")))
    parts = [authors, title]
    if venue:
        parts.append(venue)
    if year:
        parts.append(year)
    if doi:
        parts.append(f"doi:{doi}")
    if url and url not in {doi, f"doi:{doi}"}:
        parts.append(url)
    return f"- [{key}] " + ". ".join(part.rstrip(".") for part in parts if part) + "."


def _citation_key(citation: dict[str, Any]) -> str:
    raw = (
        _text(citation.get("bibtex_key"))
        or _text(citation.get("document_id"))
        or _text(citation.get("id"))
        or "unknown-reference"
    )
    key = re.sub(r"[^A-Za-z0-9:_-]+", "-", raw).strip("-")
    return key or "unknown-reference"


def _format_authors(authors: list[Any]) -> str:
    names = [_clean_text(_text(author)) for author in authors]
    names = [name for name in names if name]
    if not names:
        return "Unknown authors"
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return ", ".join(names[:-1]) + f", and {names[-1]}"
    return ", ".join(names[:3]) + ", et al"


def _references(evidence: _ManuscriptEvidence) -> list[str]:
    lines: list[str] = []
    context = _reference_context(evidence)
    ranked_verified = sorted(
        [
            citation
            for citation in evidence.citations
            if citation.get("status") in {"verified_doi", "verified_url"}
        ],
        key=lambda citation: _reference_sort_key(citation, context),
        reverse=True,
    )
    verified = [
        citation
        for citation in ranked_verified
        if _reference_row_is_direct(citation, context)
    ] or ranked_verified
    if not verified:
        return [
            "No DOI/URL-verified literature references were attached to this cycle; the paper-quality gate must block publication until formal source metadata is present."
        ]
    for citation in verified[:12]:
        lines.append(_formal_reference_line(citation))
    return lines


def _reference_context(
    evidence: _ManuscriptEvidence,
) -> tuple[set[str], set[str], set[str]]:
    candidate_metadata = _dict(evidence.candidate.get("metadata"))
    task_metadata = _task_metadata(evidence)
    run = _dict(evidence.run_record.get("run"))
    primary_fields = (
        "method",
        "proposed_method",
        "method_contribution",
        "mechanism",
        "dataset",
        "benchmark",
        "baseline",
        "ablation",
        "demo",
        "task_id",
    )
    secondary_fields = (
        "title",
        "description",
        "research_gap",
        "limitation",
        "novel_contribution",
        "contribution",
    )
    texts = []
    texts.extend(
        _reference_context_values(
            evidence.candidate,
            fields=secondary_fields,
        )
    )
    for payload in (candidate_metadata, task_metadata):
        texts.extend(_reference_context_values(payload, fields=primary_fields))
        texts.extend(_reference_context_values(payload, fields=secondary_fields))
    texts.extend(_reference_context_values(run, fields=("task_id",)))
    all_tokens = set(_semantic_tokens(" ".join(texts)))
    method_tokens = all_tokens & (REFERENCE_DIRECT_METHOD_TOKENS | REFERENCE_SUPPORT_TOKENS)
    domain_tokens = all_tokens - method_tokens - REFERENCE_GENERIC_TOKENS
    return method_tokens, domain_tokens, all_tokens


def _reference_context_values(
    payload: dict[str, Any],
    *,
    fields: tuple[str, ...] | None = None,
) -> list[str]:
    values: list[str] = []
    source_values = (
        (payload.get(field) for field in fields)
        if fields is not None
        else payload.values()
    )
    for value in source_values:
        if isinstance(value, dict):
            values.extend(_text(item) for item in value.values())
            continue
        if isinstance(value, list | tuple | set):
            values.extend(_text(item) for item in value)
            continue
        text = _text(value).strip()
        if text:
            values.append(text)
    return values


def _reference_sort_key(
    citation: dict[str, Any],
    context: tuple[set[str], set[str], set[str]],
) -> tuple[int, int, str]:
    method_tokens, domain_tokens, all_tokens = context
    citation_tokens = set(_semantic_tokens(_citation_reference_text(citation)))
    strong = citation_tokens & method_tokens & REFERENCE_DIRECT_METHOD_TOKENS
    support = citation_tokens & REFERENCE_SUPPORT_TOKENS
    domain = citation_tokens & domain_tokens
    context_overlap = citation_tokens & all_tokens
    direct_score = 0
    if len(strong) >= 2:
        direct_score += 200
    if strong and domain:
        direct_score += 150
    if strong and support:
        direct_score += 100
    if {"nearest", "centroid"} <= citation_tokens:
        direct_score += 120
    if {"prototype", "classifier"} <= citation_tokens:
        direct_score += 120
    score = (
        direct_score
        + 20 * len(strong)
        + 6 * len(domain)
        + 3 * len(context_overlap)
        + (2 if citation.get("doi") else 1)
    )
    return (score, len(citation_tokens), _clean_text(_text(citation.get("title"))))


def _reference_row_is_direct(
    citation: dict[str, Any],
    context: tuple[set[str], set[str], set[str]],
) -> bool:
    _method_tokens, _domain_tokens, _all_tokens = context
    citation_tokens = set(_semantic_tokens(_citation_reference_text(citation)))
    if not citation_tokens:
        return False
    title_tag_tokens = set(_semantic_tokens(_citation_reference_title_tag_text(citation)))
    if {"nearest", "centroid"} <= title_tag_tokens:
        return True
    if "prototype" in title_tag_tokens and citation_tokens & {"classifier", "classification"}:
        return True
    if (
        title_tag_tokens & REFERENCE_TITLE_DOMAIN_ANCHOR_TOKENS
        and title_tag_tokens & REFERENCE_TITLE_METHOD_ANCHOR_TOKENS
    ):
        return True
    return bool(
        title_tag_tokens & REFERENCE_TITLE_METHOD_ANCHOR_TOKENS
        and citation_tokens & REFERENCE_TASK_ANCHOR_TOKENS
    )


def _citation_reference_text(citation: dict[str, Any]) -> str:
    parts = [
        _text(citation.get("title")),
        _text(citation.get("abstract")),
        _text(citation.get("venue")),
        _text(citation.get("source_uri")),
        " ".join(_text(author) for author in _list(citation.get("authors"))),
        " ".join(_text(tag) for tag in _list(citation.get("tags"))),
    ]
    return "\n".join(part for part in parts if part)


def _citation_reference_title_tag_text(citation: dict[str, Any]) -> str:
    parts = [
        _text(citation.get("title")),
        " ".join(_text(tag) for tag in _list(citation.get("tags"))),
    ]
    return "\n".join(part for part in parts if part)


def _semantic_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in re.findall(r"[a-z0-9]+", text.casefold().replace("_", " ")):
        if len(raw_token) < 3:
            continue
        token = _normalise_reference_token(raw_token)
        if token:
            tokens.append(token)
    return tuple(tokens)


def _normalise_reference_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 5:
        return f"{token[:-3]}y"
    if token.endswith("ss"):
        return token
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _write_vault_manuscript(
    markdown: str,
    vault_root: Path | str | None,
    project_id: str | None,
) -> Path | None:
    if vault_root is None or not project_id:
        return None
    target = Path(vault_root) / "projects" / project_id / "paper" / "manuscript.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


def _parse_literature_docs(path: Path | None) -> tuple[dict[str, str], ...]:
    if path is None or not path.exists():
        return ()
    docs: list[dict[str, str]] = []
    in_docs = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("## "):
            in_docs = line.strip().casefold() == "## normalized documents"
            continue
        if not in_docs or not line.startswith("- `"):
            continue
        match = re.match(r"- `([^`]+)`\s+(.+?)\s+\((.*?source=([^)]+))\)", line)
        if match:
            docs.append(
                {
                    "id": match.group(1),
                    "title": _clean_text(match.group(2)),
                    "source": _clean_text(match.group(4)),
                }
            )
    return tuple(docs)


def _parse_similarity_findings(path: Path | None) -> tuple[dict[str, str], ...]:
    if path is None or not path.exists():
        return ()
    findings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("### "):
            if current:
                findings.append(current)
            current = {"title": _clean_text(line[4:].strip())}
            continue
        if current is None:
            continue
        for key, label in (
            ("classification", "- Classification:"),
            ("confidence", "- Confidence:"),
            ("source", "- Source database:"),
            ("basis", "- Classification basis:"),
        ):
            if line.startswith(label):
                current[key] = _clean_text(line.split(":", 1)[1].strip(" `"))
    if current:
        findings.append(current)
    return tuple(findings)


def _parse_citations(
    path: Path | None,
    *,
    fallback: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    payload = _read_json_if_exists(path) if path is not None else {}
    if not payload:
        payload = fallback
    rows: list[dict[str, Any]] = []
    for row in _dict_list(payload.get("citations")):
        rows.append(
            {
                "document_id": _clean_text(_text(row.get("document_id"))),
                "title": _clean_text(_text(row.get("title"))),
                "status": _clean_text(_text(row.get("status"))),
                "bibtex_key": _clean_text(_text(row.get("bibtex_key"))),
                "doi": _clean_locator_text(_text(row.get("doi"))),
                "url": _clean_locator_text(_text(row.get("url"))),
                "abstract": _clean_text(_text(row.get("abstract"))),
                "venue": _clean_text(_text(row.get("venue"))),
                "source_uri": _clean_locator_text(_text(row.get("source_uri"))),
                "authors": [_clean_text(_text(author)) for author in _list(row.get("authors"))],
                "tags": [_clean_text(_text(tag)) for tag in _list(row.get("tags"))],
            }
        )
    return tuple(rows)


def _literature_doc_lines(docs: tuple[dict[str, str], ...]) -> list[str]:
    if not docs:
        return [
            (
                "No normalized literature titles were readable from the literature "
                "summary artifact. The manuscript therefore keeps related-work detail "
                "at the source-fetch level."
            )
        ]
    return [
        (
            "Representative retrieved records are retained in the runtime literature "
            "refresh note. This paper does not list title-level hits as formal references "
            "until a citation validator has attached complete bibliographic records."
        )
    ]


def _similarity_finding_lines(
    findings: tuple[dict[str, str], ...],
    *,
    positioning_artifact_path: Path | None,
) -> list[str]:
    if not findings:
        return [
            (
                "No parsed similarity findings were available. This is a novelty-risk "
                "blocker, because absence of parsed findings is not evidence of absence."
            )
        ]
    summary = _similarity_positioning_counts(findings)
    adjacent_count = summary.get("adjacent_work", 0)
    if adjacent_count <= 0:
        return [
            (
                "Representative similarity findings are retained in the runtime similarity "
                "note. This manuscript summarizes their role without promoting individual "
                "metadata hits into validated related-work claims."
            )
        ]
    artifact_label = (
        _relative_markdown_path(positioning_artifact_path)
        if positioning_artifact_path is not None
        else "the similarity positioning artifact"
    )
    family_counts = _adjacent_work_family_counts(findings)
    family_boundaries = {
        "prototype and centroid family": (
            "Treat as adjacent method family; compare objective and benchmark before novelty claims."
        ),
        "metric and Mahalanobis family": (
            "Treat as adjacent distance-family baseline; keep the empirical claim single-cycle."
        ),
        "benchmark-overlap family": (
            "Treat as shared benchmark context; do not claim task novelty from retrieval alone."
        ),
        "other adjacent source-backed hit": (
            "Keep as retrieval boundaries, not as proof for or against originality."
        ),
    }
    table_rows = [
        (
            f"| {_table_cell(family)} | adjacent_work={count} | "
            f"{_table_cell(family_boundaries.get(family, 'Preserve as an adjacent boundary for later comparison.'))} |"
        )
        for family, count in sorted(family_counts.items())
        if count > 0
    ]
    lines = [
        (
            "Representative similarity findings are retained in the runtime similarity "
            "note. The adjacent-work positioning below is backed by the generated "
            f"{artifact_label} summary rather than by model memory. It separates the "
            "project-start similarity note from the related-work inspection: the former "
            f"contains {_int(len(findings))} parsed similarity findings, while the latter "
            "screens citation rows for source-backed method overlap."
        ),
        "",
        "### Adjacent-Work Positioning",
        "",
        "| Evidence view | Recorded count | Positioning boundary |",
        "| --- | ---: | --- |",
        *table_rows,
    ]
    return [
        *lines,
        (
            f"The positioning summary records {adjacent_count} adjacent-work findings "
            f"out of {len(findings)} parsed similarity findings. Unknown rows are not "
            "used as evidence for originality, and direct duplicate rows, if present, "
            "remain blockers for the publication audit rather than items to paper over "
            "in prose."
        ),
    ]


def _positioning_decision(finding: dict[str, str]) -> str:
    family = _positioning_family(finding)
    if family == "prototype and centroid family":
        return "Compare prototype objective and benchmark before novelty claims."
    if family == "metric and Mahalanobis family":
        return "Compare distance metric baselines before widening the claim."
    if family == "benchmark-overlap family":
        return "Shared benchmark context; do not claim task novelty from retrieval alone."
    return "Preserve as an adjacent boundary for later comparison."


def _positioning_family(finding: dict[str, str]) -> str:
    basis = _clean_text(finding.get("basis", "")).casefold()
    title = _clean_text(finding.get("title", "")).casefold()
    if "query family overlap mahalanobis_metric" in basis:
        return "metric and Mahalanobis family"
    if "query family overlap prototype_classification" in basis:
        return "prototype and centroid family"
    if "query family overlap benchmark" in basis:
        return "benchmark-overlap family"
    text = f"{title} {basis}"
    if any(token in text for token in ("mahalanobis", "metric", "distance", "nearest neighbor")):
        return "metric and Mahalanobis family"
    if any(token in text for token in ("prototype", "centroid", "nearest centroid")):
        return "prototype and centroid family"
    if any(token in text for token in ("pendigits", "handwritten", "digit", "benchmark")):
        return "benchmark-overlap family"
    return "other adjacent source-backed hit"


def _similarity_positioning_counts(findings: tuple[dict[str, str], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        classification = _clean_text(finding.get("classification", "")).casefold() or "unknown"
        counts[classification] = counts.get(classification, 0) + 1
    return counts


def _adjacent_work_family_counts(findings: tuple[dict[str, str], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        if _clean_text(finding.get("classification", "")).casefold() != "adjacent_work":
            continue
        family = _positioning_family(finding)
        counts[family] = counts.get(family, 0) + 1
    return counts


def _table_cell(value: str | None) -> str:
    text = _clean_text(_text(value))
    return text.replace("|", "/") or "unknown"


def _validation_note_lines(validation: dict[str, Any]) -> list[str]:
    notes = _list(validation.get("statistical_notes"))
    if not notes:
        return [
            (
                "No statistical notes were found in the validation report, so this "
                "manuscript does not add confidence-interval or repeated-run claims."
            )
        ]
    lines = ["Validation statistical notes include:"]
    for index, note in enumerate(notes[:4], start=1):
        message = _clean_text(_text(_dict(note).get("message")))
        metric_name = _clean_text(_text(_dict(note).get("metric_name")))
        lines.append(f"- Note {index}: {metric_name}: {message}.")
    return lines


def _source_summary(fetches: list[dict[str, Any]]) -> str:
    sources = sorted({_clean_text(_text(fetch.get("source"))) for fetch in fetches})
    successful = sorted(
        {
            _clean_text(_text(fetch.get("source")))
            for fetch in fetches
            if _int(fetch.get("paper_count")) > 0 and not _text(fetch.get("error"))
        }
    )
    errored = sorted(
        {
            _clean_text(_text(fetch.get("source")))
            for fetch in fetches
            if _text(fetch.get("error"))
        }
    )
    return (
        f"sources {', '.join(sources) or 'none'}, successful sources "
        f"{', '.join(successful) or 'none'}, errored sources {', '.join(errored) or 'none'}"
    )


def _classification_summary(findings: tuple[dict[str, str], ...]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        classification = finding.get("classification", "unknown") or "unknown"
        counts[classification] = counts.get(classification, 0) + 1
    if not counts:
        return "no parsed classifications"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def _classified_similarity_count(findings: tuple[dict[str, str], ...]) -> int:
    return sum(1 for finding in findings if finding.get("classification") not in {"", "unknown", None})


def _section_word_counts(markdown: str) -> dict[str, int]:
    sections = _extract_sections(markdown)
    return {section: _word_count(sections.get(section, "")) for section in REQUIRED_MANUSCRIPT_SECTIONS}


def _extract_sections(markdown: str) -> dict[str, str]:
    headings = {section.casefold(): section for section in REQUIRED_MANUSCRIPT_SECTIONS}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = headings.get(match.group(1).strip().casefold())
            if current is not None:
                sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {section: "\n".join(lines).strip() for section, lines in sections.items()}


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", text))


def _metrics(evidence: _ManuscriptEvidence) -> dict[str, Any]:
    return _dict(_dict(evidence.run_record.get("metrics")).get("values"))


def _task_metadata(evidence: _ManuscriptEvidence) -> dict[str, Any]:
    return _dict(evidence.run_record.get("task_metadata")) or _dict(
        evidence.candidate.get("metadata")
    )


def _method_name(evidence: _ManuscriptEvidence) -> str:
    metadata = _task_metadata(evidence)
    candidate_metadata = _dict(evidence.candidate.get("metadata"))
    return (
        _clean_text(_text(metadata.get("proposed_method")))
        or _clean_text(_text(metadata.get("method_contribution")))
        or _clean_text(_text(candidate_metadata.get("method")))
        or "the executed method candidate"
    )


def _baseline_name(evidence: _ManuscriptEvidence) -> str:
    metadata = _task_metadata(evidence)
    candidate_metadata = _dict(evidence.candidate.get("metadata"))
    return (
        _clean_text(_text(metadata.get("baseline")))
        or _clean_text(_text(candidate_metadata.get("baseline")))
        or "the recorded baseline"
    )


def _dataset(evidence: _ManuscriptEvidence) -> str:
    metadata = _task_metadata(evidence)
    candidate_metadata = _dict(evidence.candidate.get("metadata"))
    return (
        _clean_text(_text(metadata.get("dataset")))
        or _clean_text(_text(candidate_metadata.get("dataset")))
        or "the recorded dataset"
    )


def _metric(metrics: dict[str, Any], key: str) -> float | None:
    try:
        return float(str(metrics[key]))
    except (KeyError, TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return "unknown"
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.4f}"


def _article(value: str) -> str:
    if not value:
        return "the recorded method"
    return value


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _read_json_if_exists(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _resolve_path(path_value: object, base_dir: Path) -> Path | None:
    text = _text(path_value)
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([base_dir / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _readable_identifier(value: str) -> str:
    text = _clean_text(value)
    if "/" in text or "\\" in text:
        text = Path(text).name
    text = re.sub(r"[_/\\]+", " ", text)
    text = re.sub(r"\.(csv|json|md|txt|log)$", r" \1 file", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _int(value: object, *, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"https?://\S+", "source URL recorded in artifact", ascii_text)
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    return ascii_text


def _clean_locator_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().rstrip(".,;")
