"""Compose evidence-bound publication manuscripts from cycle artifacts."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    evidence_refs: tuple[str, ...]


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
    markdown = _render_manuscript(evidence)
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
        evidence_refs=evidence.evidence_refs,
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
    evidence_refs = tuple(
        path.as_posix()
        for path in (
            summary_path,
            run_record_path,
            validation_path,
            evidence_map_path,
            literature_path,
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
        evidence_refs=evidence_refs,
    )


def _render_manuscript(evidence: _ManuscriptEvidence) -> str:
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
        *_related_work(evidence),
        "",
        "## Method",
        "",
        *_method(evidence),
        "",
        "## Experiments",
        "",
        *_experiments(evidence),
        "",
        "## Results",
        "",
        *_results(evidence),
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
            f"This manuscript is an evidence-bound report generated from one AI-Researcher "
            f"autonomous cycle for the candidate '{_clean_text(_text(candidate.get('title')))}'. "
            f"The executed method is {_article(method)} evaluated on {dataset}, with {baseline} "
            f"kept as the recorded baseline and a separate ablation retained when available. "
            f"The run reports accuracy {_fmt(accuracy)}, baseline accuracy "
            f"{_fmt(baseline_accuracy)}, and an accuracy delta of {_fmt(delta)} over "
            f"{_fmt(test_rows)} test rows. These figures are not free-form claims: they are "
            f"copied from the local run record, validation report, and evidence map. The "
            f"literature and similarity sections describe online retrieval breadth and "
            f"remaining novelty uncertainty rather than asserting that the idea is new. "
            f"The resulting manuscript is therefore a reproducible research artifact, not a "
            f"submission claim; publication readiness still depends on the separate audit, "
            f"paper quality, evidence gate, and human review."
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
            "the negative evidence, the exact baseline, the ablation design, or the "
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


def _related_work(evidence: _ManuscriptEvidence) -> list[str]:
    doc_lines = _literature_doc_lines(evidence.literature_docs[:8])
    finding_lines = _similarity_finding_lines(evidence.similarity_findings[:8])
    return [
        (
            "The literature context comes from the live retrieval stage, not from a "
            "language-model memory. Exact fetch counts, source names, cache status, and "
            "document counts remain in the runtime literature note and compact review "
            "context. This prose uses that retrieval only to establish that a search "
            "trail exists and that expert related-work writing is still required."
        ),
        (
            "The first normalized records are treated only as title-level search hits. "
            "Their titles suggest which abstracts need later inspection, but this "
            "manuscript does not infer a validated research family, benchmark result, "
            "or baseline obligation from a title alone. The useful next step is to "
            "check whether any retrieved abstract or full bibliographic record directly "
            "describes diagonal variance calibration as a prototype distance mechanism "
            "on comparable handwritten benchmark tasks. Until that happens, retrieved "
            "titles remain search evidence rather than supporting claims."
        ),
        *doc_lines,
        (
            "The similarity search is narrower and more adversarial. It queried the "
            "candidate title, the method-plus-dataset phrase, the baseline-plus-dataset "
            "phrase, and the limitation-risk phrase. Exact classification counts, "
            "source responses, and cache details are stored in the "
            "similarity note and compact review context rather than promoted into this "
            "paper prose. The distribution is a warning signal rather than a novelty "
            "claim. When findings remain unknown, the safe interpretation is that the "
            "system needs deeper abstract inspection and more adjacent-work classification "
            "before any submission-quality originality statement can be written."
        ),
        *finding_lines,
        (
            "This related-work section is intentionally conservative. It does not state "
            "that the retrieved papers do or do not outperform the current method, and "
            "it does not infer code availability, benchmark scores, venue status, or "
            "acceptance status from absent metadata. Its only role is to make the search "
            "trail visible and to define the next literature tasks: classify the unknown "
            "findings, separate direct duplicates from adjacent work, add stronger "
            "prototype and metric-learning baselines, and convert validated sources into "
            "BibTeX records before any external submission."
        ),
        (
            "For submission-oriented use, the related-work evidence must eventually be "
            "split into direct duplicates, adjacent mechanisms, benchmark precedents, "
            "baseline obligations, and out-of-scope noise. That split is not merely a "
            "writing preference. It decides whether the next cycle should stop the idea, "
            "strengthen the comparison set, or continue collecting evidence. A direct "
            "duplicate should block novelty claims. An adjacent mechanism should create "
            "a positioning paragraph and likely a baseline. A benchmark precedent should "
            "verify the dataset protocol and metrics. Out-of-scope noise should be kept "
            "visible so the system does not repeatedly rediscover the same weak search "
            "hits."
        ),
        (
            "The current manuscript therefore treats source classification as a research "
            "object. It records how many findings were classified, how many remain "
            "unknown, which databases responded, and which query families produced "
            "evidence. This is a stronger artifact than a generic survey paragraph "
            "because it tells the next autonomous loop exactly where the literature "
            "model is weak. If a later reviewer asks why a baseline is missing, the "
            "answer should be recoverable from the similarity findings and follow-up "
            "tasks rather than from an author's memory."
        ),
    ]


def _method(evidence: _ManuscriptEvidence) -> list[str]:
    metadata = _task_metadata(evidence)
    method = _method_name(evidence)
    baseline = _baseline_name(evidence)
    dataset = _dataset(evidence)
    split_policy = _clean_text(_text(metadata.get("split_policy"))) or "the recorded data split"
    return [
        (
            f"The executed method is described in the run metadata as {method}. In this "
            f"cycle it is not treated as a black-box model family. The available run "
            f"metadata exposes class-level prototype statistics and a recorded variance "
            f"calibration distance rule; this is an implementation trace, not a broad "
            f"interpretability claim. The baseline label is {baseline}, and the ablation "
            f"is treated as a recorded artifact or metric rather than named as a separate "
            f"algorithm family in prose. This structure gives the validator three separate "
            f"handles: the candidate effect relative to the baseline, the candidate effect "
            f"relative to the ablation artifact, and the sanity of the metric ranges on "
            f"the official test split."
        ),
        (
            f"The dataset layer is {dataset}. The split policy is {split_policy}. The "
            f"method does not sample hidden private data and does not rely on an "
            f"unverifiable benchmark. The run record stores the data hash, configuration "
            f"hash, commit identifier, metrics path, artifact directory, and command used "
            f"for reproduction. These provenance fields are more important than prose "
            f"style because they let a later validator decide whether the same data and "
            f"code path produced the reported numbers."
        ),
        (
            "The script-level algorithm is not reconstructed as a separate prose truth "
            "source. The executable `run.py`, run record, metrics file, validation "
            "report, and evidence map remain the authoritative artifacts for step order "
            "and implementation detail. This manuscript therefore describes only the "
            "audited method boundary: public data source, recorded baseline, recorded "
            "candidate metric, recorded ablation artifact, written metrics, and "
            "validator-readable evidence edges. If a later paper needs a formal algorithm "
            "listing, the listing should be generated from the script and then reviewed "
            "as its own evidence artifact."
        ),
        (
            "This method description deliberately excludes unexecuted variants. It does "
            "not claim that the same calibration will improve neural embeddings, other "
            "handwriting datasets, other prototype learners, or streaming classifiers. "
            "Those hypotheses can be added as follow-up tasks only after the current "
            "cycle has recorded enough related-work classification and after the evidence "
            "gate has accepted the supporting artifacts. The method section therefore "
            "serves as a precise reproduction map rather than a broad theory of prototype "
            "learning."
        ),
        (
            "For a conference-style manuscript, the method also needs to state what the "
            "system is not allowed to vary. The current cycle fixes the data source, "
            "the split policy, the baseline family, the ablation role, and the validator "
            "that reads the produced artifacts. The autonomous loop may choose a topic, "
            "retrieve sources, run the script, and draft the paper, but it may not "
            "silently relabel the benchmark, replace a failed baseline, or convert a "
            "single positive metric into a general theory. That constraint is especially "
            "important when the same manuscript is compiled under compact ACM or IEEE "
            "templates, because visual polish can otherwise hide a thin evidence model."
        ),
        (
            "The implementation-level invariants are therefore part of the contribution. "
            "Input data must be discoverable from recorded source metadata; the feature "
            "pipeline must be represented in the executable script rather than only in "
            "prose; metrics must be written before any publication audit reads them; and "
            "paper generation must consume the audited cycle summary rather than a private "
            "language-model transcript. These invariants make the method section longer "
            "than a minimal algorithm sketch, but they are the checks that allow later "
            "agents to rerun, reject, or extend the claim without guessing what happened."
        ),
        (
            "The design also supports self-looping refinement. If the publication audit "
            "finds that novelty evidence is thin, the system can schedule a retrieval "
            "task without rewriting the experiment result. If the paper-quality gate "
            "finds that a section is short, the manuscript composer can regenerate from "
            "new evidence without changing metrics. If a future strategy proposes a "
            "different search prompt or a different baseline, that proposal must be "
            "evaluated in shadow mode before promotion. In short, the method is coupled "
            "to evidence, and the surrounding workflow is coupled to rollback."
        ),
        (
            "The implementation boundary is also part of the method. The experiment "
            "agent may generate or execute code, but the acceptance path is owned by "
            "validators that read artifacts after execution. A metric is not accepted "
            "because the code agent says it ran; it is accepted only when the metrics "
            "file exists, the validation report reads it, the evidence map binds it to "
            "a claim, and the cycle summary keeps the path reachable. This separation "
            "prevents the manuscript composer from becoming a second, uncontrolled "
            "source of truth. It can explain the evidence, but it cannot manufacture a "
            "new score, silently change a baseline, or erase a failed audit check."
        ),
        (
            "The method is also organized around an evidence-to-claim map. Dataset claims "
            "must point to source metadata and data hashes. Execution claims must point "
            "to the run record and command line. Metric claims must point to the metrics "
            "object and validation notes. Novelty claims must point to literature and "
            "similarity summaries. Paper-readiness claims must point to the compiled PDF, "
            "the paper-quality object, and the stability matrix. This map is what lets "
            "the system produce a paper-like artifact while still behaving like an "
            "auditable research workflow."
        ),
        (
            "The same map prevents self-evolution from corrupting the scientific record. "
            "A future skill can propose better retrieval prompts, stronger baselines, or "
            "a more detailed manuscript composer, but those changes must improve the "
            "gate evidence rather than overwrite the old run. The old cycle remains a "
            "frozen datum: its metrics, source coverage, and review status stay available "
            "for comparison. Self-improvement is therefore expressed as a new strategy "
            "candidate with validation evidence, not as retroactive editing of the "
            "reported result."
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
            f"{_clean_text(_text(run.get('exit_code')))}. The metrics file reports "
            f"{len(metrics)} numeric fields, including accuracy, macro F1 when available, "
            f"test rows, train rows, dataset rows, baseline metrics, ablation metrics, "
            f"and standard-error information. Because the metrics are loaded from the "
            f"run record, the manuscript does not need to reinterpret console output or "
            f"copy numbers from a screenshot."
        ),
        (
            f"The run preserved {len(artifacts)} artifact references and {len(logs)} log "
            f"references. Artifact names include {', '.join(artifacts[:5]) or 'none recorded'}. "
            f"The important point is not that every artifact is visually inspected in this "
            f"section, but that the evidence gate can locate the prediction file, summary "
            f"file, ablation file, dataset-source file, innovation-evidence file, validation "
            f"report, evidence map, and run record. The manuscript therefore reports the "
            f"existence and role of these files while leaving exact path verification to "
            f"the machine-readable gates."
        ),
        (
            "The experimental protocol is intentionally written as a sequence of gates "
            "rather than as an informal notebook narrative. The first gate is source "
            "integrity: the data file and source metadata must be present and hashable. "
            "The second gate is executable integrity: the run command must finish with "
            "exit code zero and leave a structured run record. The third gate is metric "
            "integrity: candidate, baseline, ablation, and uncertainty fields must be "
            "readable from the same metrics object. The fourth gate is report integrity: "
            "the validation report and evidence map must bind reported numbers to local "
            "files. The fifth gate is reproduction integrity: a fresh command-line rerun "
            "must produce a new run record and validation report."
        ),
        (
            "This protocol is stricter than a typical demonstration script because it is "
            "designed for autonomous operation. A human author can remember which cached "
            "file was used, why a warning was harmless, or which failed experiment was "
            "discarded. A long-running research agent cannot rely on that memory. The "
            "experiment section therefore records enough operational detail for the next "
            "cycle to distinguish an empirical weakness from a missing-artifact weakness. "
            "If the same method later runs on another benchmark, the matrix can compare "
            "release gates across cycles instead of comparing prose descriptions."
        ),
        (
            f"Validation status is {_clean_text(_text(validation.get('status')))}. The "
            f"validation report records {_int(len(_list(validation.get('issues'))))} "
            f"issues and {len(_list(validation.get('statistical_notes')))} statistical "
            f"notes. These checks matter because a paper-style document can otherwise "
            f"make an experiment look more polished than it is. Here, the validation "
            f"stage is part of the manuscript evidence: if metrics fall outside expected "
            f"bounds, if artifacts are missing, or if statistical notes are absent when "
            f"required, the publication audit must fail even if the prose is fluent."
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
            "Conference-template compatibility is treated as an experimental artifact, "
            "not a cosmetic export. Compact two-column layouts reveal problems that a "
            "single-column draft can hide: thin method sections collapse to too few pages, "
            "machine identifiers can create overfull boxes, and missing technical detail "
            "becomes visible when the paper is compressed. The paper build gate therefore "
            "checks page count, word count, required sections, technical term coverage, "
            "and layout overflow after LaTeX compilation. A PDF is not release evidence "
            "unless those checks pass under the selected template."
        ),
        (
            "The experiment also records why a passing local run can still be rejected. "
            "If source preflight fails, the system should not spend tokens on paper "
            "generation. If reproduction fails, the metrics cannot be trusted as a "
            "release claim. If LLM review fails, unsupported prose or missing evidence "
            "must become an issue note. If publication audit fails, the candidate may "
            "remain useful as a negative or partial result, but it is not publishable. "
            "If LaTeX quality fails, the scientific result may remain valid while the "
            "paper artifact requires more technical detail or layout repair. Treating "
            "these failures separately is what keeps the loop debuggable."
        ),
        (
            "For compact conference templates, the paper build is rerun after manuscript "
            "changes rather than assumed from the Markdown word count. This matters "
            "because double-column classes can compress a manuscript by several pages "
            "and can expose long machine identifiers that never overflow in a generic "
            "article layout. The experimental evidence for template readiness is the "
            "compiled template-specific PDF plus the parsed quality report, not the "
            "existence of a `.tex` file."
        ),
    ]


def _results(evidence: _ManuscriptEvidence) -> list[str]:
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
    standard_error = _metric(metrics, "accuracy_standard_error")
    return [
        (
            f"The main result is an accuracy of {_fmt(accuracy)} on {_fmt(test_rows)} "
            f"test rows. Macro F1 is {_fmt(macro_f1)}. The recorded baseline accuracy is "
            f"{_fmt(baseline_accuracy)}, so the candidate-minus-baseline delta is "
            f"{_fmt(delta)}. The z-score centroid comparison is {_fmt(zscore)}, with "
            f"a candidate-minus-z-score delta of {_fmt(zscore_delta)}. The full dataset "
            f"metadata records {_fmt(train_rows)} train rows, {_fmt(test_rows)} test rows, "
            f"{_fmt(dataset_rows)} total rows, and {_fmt(class_count)} classes."
        ),
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
            "Publication audit and paper build outcomes are deliberately evaluated after "
            "this manuscript is composed and reviewed. Those gate outcomes are part of "
            "the release record, not claims this draft should pre-announce. A good "
            "experimental score is not enough for release if novelty classification, "
            "paper depth, layout quality, or evidence binding fails."
        ),
        (
            "The safest interpretation is therefore constructive but not promotional. "
            "The cycle produced real metrics, real validation, real reproduction evidence, "
            "and a positive candidate delta. The same cycle also exposed the remaining "
            "publication blockers. That combination is exactly what an evidence-first "
            "autonomous research system should produce: a result that can be improved "
            "or rejected by the next loop, not a polished unsupported success story."
        ),
        (
            "The evidence pattern is more valuable than the absolute score at this stage. "
            "A baseline, an ablation, a candidate delta, a standard error, a reproduction "
            "record, and a publication audit are all present in the same cycle. That "
            "combination lets the next iteration decide what kind of work is missing. "
            "If the score is promising but related work is unresolved, the next action "
            "is retrieval and classification. If related work is strong but the score "
            "is weak, the next action is method redesign. If both are strong but the "
            "paper build fails, the next action is manuscript and layout repair. The "
            "result section therefore reports not just performance, but also the control "
            "signals that keep the autonomous loop from overclaiming."
        ),
        (
            "A second result is negative but operationally important: manuscript and "
            "template gates can fail even when the empirical run succeeds. When that "
            "happens, the system should not weaken the empirical claim or hide the paper "
            "failure. It should keep the metrics fixed, repair the manuscript using "
            "existing evidence, rebuild the template, and rerun the release gate. This "
            "separation lets the research loop improve communication quality without "
            "touching data or metrics that have already been audited."
        ),
        (
            "The result should also be read as a matrix cell, not as an isolated paper. "
            "A single release-allowed cycle demonstrates that one topic, one dataset, "
            "one manuscript, and one template survived the gates. Stable CCF-B/Q3 output "
            "requires several such cells with different datasets and template families. "
            "That is why the stability auditor counts release pass rate, dataset diversity, "
            "template diversity, external conference coverage, external journal coverage, "
            "warning budgets, and paper quality together. The matrix is deliberately "
            "harder to pass than a single paper build."
        ),
        (
            "This framing changes how the numbers should be used. The accuracy delta is "
            "evidence for the method candidate in this benchmark. The publication score "
            "is evidence for this cycle's readiness under the configured audit target. "
            "The stability score is evidence for repeated pipeline behavior. None of "
            "these scores should be substituted for the others. A strong metric with a "
            "weak stability matrix is an experiment, not a stable paper-production "
            "capability; a strong matrix with weak novelty is a reproducibility pipeline, "
            "not a new scientific contribution."
        ),
    ]


def _limitations(_evidence: _ManuscriptEvidence) -> list[str]:
    return [
        (
            "The novelty boundary is still incomplete. The similarity stage has parsed "
            "and classified part of the nearby-work trail, but current metadata rules "
            "are not a substitute for source-backed abstract inspection and method "
            "comparison. Until those comparisons are attached, the manuscript must not "
            "claim that the contribution is new."
        ),
        (
            "The experiment uses one public benchmark and one primary method candidate. "
            "This is enough to test the AI-Researcher evidence loop, but it is not enough "
            "for a mature CCF-B or Q3 paper. A submission-oriented study would need more "
            "datasets, stronger external baselines, multiple runs, clearer error analysis, "
            "and explicit failure cases."
        ),
        (
            "The manuscript composer is deterministic and evidence-bound. That improves "
            "auditability, but it also means the prose can only be as strong as the "
            "available artifacts. Missing abstracts, missing citation records, missing "
            "figures, or missing reviewer evidence remain visible as gaps rather than "
            "being filled by plausible-sounding text."
        ),
        (
            "The current LLM review, when present, is bound to the experiment report and "
            "evidence artifacts. A later release-quality process should also review this "
            "expanded manuscript and verify that every new sentence is supported by the "
            "same artifacts or by newly attached sources."
        ),
        (
            "Venue coverage is also incomplete until both conference-style and "
            "journal-style templates have passing evidence. A Springer Nature build "
            "shows that the manuscript can survive one external journal template, but it "
            "does not prove ACM or IEEE conference readiness. Conversely, an ACM or IEEE "
            "build does not prove journal readiness. The stability matrix must keep these "
            "families separate so the system cannot overclaim broad CCF-B/Q3 readiness "
            "from a single external template."
        ),
        (
            "Another limitation is that this generated manuscript still lacks human "
            "disciplinary taste. It can enforce evidence, report uncertainty, and avoid "
            "fabricated claims, but it cannot know whether a community would find the "
            "contribution important without stronger venue-specific review signals. A "
            "future system should attach reviewer-style rubrics, target-conference "
            "scope checks, and baseline expectations for each domain. Until those checks "
            "exist, the correct claim is that the system can produce audited submission "
            "candidates, not that it can guarantee acceptance."
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


def _conclusion(evidence: _ManuscriptEvidence) -> list[str]:
    metrics = _metrics(evidence)
    delta = _metric(metrics, "accuracy_delta_vs_baseline")
    return [
        (
            f"This cycle shows that AI-Researcher can turn a real autonomous run into a "
            f"paper-style artifact without inventing unsupported claims. The experiment "
            f"records a candidate accuracy delta of {_fmt(delta)} over the recorded "
            f"baseline, preserves validation and reproduction artifacts, and exposes "
            f"the unresolved novelty and manuscript-readiness gates. The manuscript is "
            f"therefore useful as a research-loop artifact and as input to the next "
            f"self-loop iteration."
        ),
        (
            "The next system action should not be to submit the paper. It should be to "
            "classify more adjacent work, add stronger baselines, review this expanded "
            "manuscript against local evidence, and rerun the physical paper-quality "
            "gate. Only after those steps pass should the system describe the output as "
            "publication-ready."
        ),
        (
            "That boundary is the main contribution of the generated artifact: it gives "
            "future agents a complete, inspectable starting point while keeping rejection "
            "paths explicit."
        ),
        (
            "The practical next step is to rerun the same evidence chain under multiple "
            "publication templates and datasets. When the cycle can pass empirical, "
            "novelty, manuscript, LaTeX, and stability gates across those settings, the "
            "system has a defensible basis for saying it can produce submission-candidate "
            "drafts. Until then, the correct status is not failure; it is controlled "
            "iteration with the remaining blockers preserved as machine-readable tasks."
        ),
    ]


def _references(_evidence: _ManuscriptEvidence) -> list[str]:
    return [
        "- [Cycle summary] AI-Researcher cycle summary JSON for this run.",
        "- [Run record] Local execution record with command, hashes, metrics, artifacts, and logs.",
        "- [Validation] Validation report with metric bounds, issues, and statistical notes.",
        "- [Evidence map] Metric-to-evidence binding record generated by the experiment pipeline.",
        "- [Literature refresh] Runtime Obsidian summary of online ArXiv and OpenAlex retrieval.",
        "- [Similarity check] Runtime Obsidian summary of project-start novelty and adjacent-work search.",
        "- [Reproduction check] Command-line rerun record generated inside the cycle directory.",
        "- [Publication audit] Deterministic publication-readiness gate when present in the cycle.",
        "- [Paper build] LaTeX and PDF build quality gate when present in the cycle.",
    ]


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
            "refresh note. This draft does not list title-level hits as formal references "
            "until a citation validator has attached complete bibliographic records."
        )
    ]


def _similarity_finding_lines(findings: tuple[dict[str, str], ...]) -> list[str]:
    if not findings:
        return [
            (
                "No parsed similarity findings were available. This is a novelty-risk "
                "blocker, because absence of parsed findings is not evidence of absence."
            )
        ]
    return [
        (
            "Representative similarity findings are retained in the runtime similarity "
            "note. This manuscript summarizes their role without promoting individual "
            "metadata hits into validated related-work claims."
        )
    ]


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
