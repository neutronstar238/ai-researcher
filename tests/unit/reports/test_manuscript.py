import json
from pathlib import Path

from autoresearch.reports import (
    build_latex_paper_from_markdown,
    compose_publication_manuscript,
)
from autoresearch.reports.manuscript import _positioning_family


def test_compose_publication_manuscript_writes_evidence_bound_draft(
    tmp_path: Path,
) -> None:
    summary_path = _write_cycle(tmp_path)

    artifact = compose_publication_manuscript(
        cycle_summary_path=summary_path,
        output_dir=tmp_path / "paper-manuscript",
        vault_root=tmp_path / "vault",
        project_id="project_1",
    )

    manuscript = Path(artifact.markdown_path).read_text(encoding="utf-8")
    assert Path(artifact.json_path).is_file()
    assert artifact.vault_markdown_path is not None
    assert Path(artifact.vault_markdown_path).is_file()
    assert artifact.word_count >= 3500
    assert artifact.section_word_counts["Method"] >= 260
    assert artifact.section_word_counts["Experiments"] >= 600
    assert "accuracy delta of 0.0400" in manuscript
    assert "reproducible, source-backed candidate result" in manuscript
    assert "The next system action should not be to submit the paper" not in manuscript
    assert "Representative retrieved records are retained" in manuscript
    assert "### Evidence and Artifact Availability" in manuscript
    assert "| Cycle summary | Machine-readable cycle state and stage outputs |" in manuscript
    assert "| Cycle record |" not in manuscript
    assert "| Readiness report |" not in manuscript
    assert "### Data Analysis" in manuscript
    assert "![Validated metric comparison](analysis/validated-performance-metrics.pdf)" in manuscript
    assert "| Metric | Value | Evidence source |" in manuscript
    assert "Markdown manuscript and paper-build summaries are written to the Obsidian vault" in manuscript
    assert "[Cycle summary]" not in manuscript
    assert "[Verified literature references]" not in manuscript
    assert "V. Source. Verified Prototype Source. MethodConf. doi:10.1234/verified" in manuscript
    references_section = manuscript.split("## References", 1)[1]
    assert "https://example.test/verified" in references_section
    assert "source URL recorded in artifact" not in references_section
    assert "[generic2026] Generic Visual Recognition Source" not in manuscript
    assert "[seed2020] Variance function of boolean additive convolution" not in manuscript
    assert "[domain2026] Handwritten Bangla Alphabet Recognition using MLP Classifier" not in manuscript
    assert "not a submission claim" not in manuscript
    assert "12.0000 input features" in manuscript
    assert "variance_shrinkage parameter of 0.0500" in manuscript
    assert "fixed recorded configuration, not a tuned hyperparameter result" in manuscript
    assert "does not include a sensitivity sweep" in manuscript
    assert "bound to the final manuscript" in manuscript
    assert "Conference-template compatibility is treated as an experimental artifact" not in manuscript
    assert "compiled under compact ACM or IEEE templates" not in manuscript
    assert "only certifies the template that was actually selected for this cycle" in manuscript
    assert "not evidence that ACM, IEEE, Springer" in manuscript
    assert "Current finding classifications are:" not in manuscript
    assert "Retrieved record 1:" not in manuscript
    assert "was classified as" not in manuscript
    assert "candidate title, the method-plus-dataset phrase" not in manuscript
    assert "queried the candidate's method, dataset, baseline" not in manuscript
    assert "parsed and classified part of the nearby-work trail" not in manuscript
    assert "records how many findings were classified" not in manuscript
    assert "Representative similarity findings are retained" in manuscript
    assert "### Adjacent-Work Positioning" in manuscript
    assert "| Evidence view | Recorded count | Positioning boundary |" in manuscript
    assert "| prototype and centroid family | adjacent_work=1 |" in manuscript
    assert "| metric and Mahalanobis family | adjacent_work=0 |" not in manuscript
    assert "| other adjacent source-backed hit | adjacent_work=0 |" not in manuscript
    assert "similarity-positioning-summary.json" in manuscript
    assert "1 adjacent-work findings out of 10 parsed similarity findings" in manuscript
    assert "Metric Learning for Digits | unknown" not in manuscript
    assert "narrower and more adversarial" not in manuscript
    assert "split into direct duplicates, adjacent mechanisms" not in manuscript
    assert "comparison-status fields recorded in the inspection artifact" in manuscript
    assert "Prototype Calibration for Digits was retrieved" not in manuscript
    assert "pendigits_variance_calibrated_prototypes" not in manuscript
    assert "pendigits variance calibrated prototypes" in manuscript
    assert artifact.analysis_artifact_paths
    assert any(path.endswith("validated-performance-metrics.pdf") for path in artifact.analysis_artifact_paths)
    assert any(path.endswith("data-analysis-summary.md") for path in artifact.analysis_artifact_paths)
    assert any(
        path.endswith("similarity-positioning-summary.json")
        for path in artifact.analysis_artifact_paths
    )
    positioning_json = next(
        path
        for path in artifact.analysis_artifact_paths
        if path.endswith("similarity-positioning-summary.json")
    )
    positioning_payload = json.loads(Path(positioning_json).read_text(encoding="utf-8"))
    assert positioning_payload["finding_count"] == 10
    assert positioning_payload["adjacent_work_count"] == 1
    assert positioning_payload["adjacent_work_family_counts"] == {
        "prototype and centroid family": 1
    }

    paper_artifact = build_latex_paper_from_markdown(
        artifact.markdown_path,
        tmp_path / "paper-build",
        compile_pdf=False,
    )
    assert paper_artifact.missing_sections == ()
    assert "word_count" not in paper_artifact.quality.failures
    assert "section_depth" not in paper_artifact.quality.failures
    assert "figure_coverage" not in paper_artifact.quality.failures
    assert "table_coverage" not in paper_artifact.quality.failures
    assert "bibliography_depth" not in paper_artifact.quality.failures
    assert "reference_format" not in paper_artifact.quality.failures
    assert "figure_label_readability" not in paper_artifact.quality.failures
    tex = Path(paper_artifact.tex_path).read_text(encoding="utf-8")
    assert r"\includegraphics" in tex
    assert r"\begin{tabular}" in tex
    assert r"\begin{thebibliography}{99}" in tex
    assert r"\bibitem{source2026}" in tex
    assert r"\url{https://example.test/verified}" in tex
    assert "[Cycle summary]" not in tex


def test_positioning_family_prefers_structured_overlap_family() -> None:
    finding = {
        "title": "Clustering and Prototype Based Classification",
        "basis": (
            "query family overlap prototype_classification: document terms prototype, "
            "prototype classifier; source query `mahalanobis distance metric gaussian "
            "prototype classifiers uci pendigits` (limitation_risk_search)"
        ),
    }

    assert _positioning_family(finding) == "prototype and centroid family"


def _write_cycle(tmp_path: Path) -> Path:
    cycle_dir = tmp_path / "cycle"
    experiment_dir = cycle_dir / "demo" / "pendigits"
    (experiment_dir / "run").mkdir(parents=True)
    (experiment_dir / "validation").mkdir()
    (experiment_dir / "evidence").mkdir()
    (experiment_dir / "report").mkdir()
    literature_path = tmp_path / "vault" / "exploration" / "topics" / "literature.md"
    similarity_path = tmp_path / "vault" / "exploration" / "topics" / "similarity.md"
    literature_path.parent.mkdir(parents=True, exist_ok=True)
    similarity_path.parent.mkdir(parents=True, exist_ok=True)
    literature_path.write_text(
        "\n".join(
            [
                "# Literature",
                "",
                "## Normalized Documents",
                "",
                "- `doc_1` Prototype Learning for Handwritten Digits (http://arxiv.org/abs/1; source=arxiv)",
                "- `doc_2` Nearest Centroid Classification Survey (https://doi.org/10.test/example; source=openalex)",
            ]
        ),
        encoding="utf-8",
    )
    similarity_path.write_text(
        "\n".join(
            [
                "# Similarity",
                "",
                "## Findings",
                "",
                *[
                    "\n".join(
                        [
                            f"### Distractor {index}",
                            "",
                            "- Classification: `unknown`",
                            "- Confidence: `0.10`",
                            "- Source database: `arxiv`",
                            "- Classification basis: pending verification",
                        ]
                    )
                    for index in range(8)
                ],
                "### Prototype Calibration for Digits",
                "",
                "- Classification: `adjacent_work`",
                "- Confidence: `0.50`",
                "- Source database: `openalex`",
                "- Classification basis: method token overlap with prototype calibration",
                "",
                "### Metric Learning for Digits",
                "",
                "- Classification: `unknown`",
                "- Confidence: `0.25`",
                "- Source database: `arxiv`",
                "- Classification basis: pending verification",
            ]
        ),
        encoding="utf-8",
    )
    citations_dir = cycle_dir / "citations"
    citations_dir.mkdir(parents=True)
    citation_bib_path = citations_dir / "references.bib"
    citation_metadata_path = citations_dir / "references.metadata.json"
    citation_bib_path.write_text(
        "@article{source2026,\n  title = {Verified Prototype Source}\n}\n",
        encoding="utf-8",
    )
    citation_metadata_path.write_text(
        json.dumps(
            {
                "bib_path": citation_bib_path.as_posix(),
                "metadata_path": citation_metadata_path.as_posix(),
                "blocked_document_ids": [],
                "citations": [
                    {
                        "document_id": "doc_seed",
                        "title": "Variance function of boolean additive convolution",
                        "status": "verified_url",
                        "bibtex_key": "seed2020",
                        "doi": None,
                        "url": "https://example.test/boolean-variance",
                        "reason": None,
                        "abstract": "Boolean additive convolution and probability measure variance functions.",
                        "venue": None,
                        "source_uri": "https://example.test/boolean-variance",
                        "authors": ["S. Seed"],
                        "tags": ["arxiv"],
                    },
                    {
                        "document_id": "doc_generic",
                        "title": "Generic Visual Recognition Source",
                        "status": "verified_doi",
                        "bibtex_key": "generic2026",
                        "doi": "10.1234/generic",
                        "url": "https://example.test/generic",
                        "reason": None,
                        "abstract": "Broad image recognition benchmark paper for generic visual categories.",
                        "venue": "GenericConf",
                        "source_uri": "https://example.test/generic",
                        "authors": ["G. Generic"],
                        "tags": ["recognition"],
                    },
                    {
                        "document_id": "doc_domain_only",
                        "title": "Handwritten Bangla Alphabet Recognition using MLP Classifier",
                        "status": "verified_url",
                        "bibtex_key": "domain2026",
                        "doi": None,
                        "url": "https://example.test/bangla-mlp",
                        "reason": None,
                        "abstract": "Domain-specific handwritten character recognition with a multilayer perceptron.",
                        "venue": "DomainOnlyConf",
                        "source_uri": "https://example.test/bangla-mlp",
                        "authors": ["D. Domain"],
                        "tags": ["handwritten", "recognition", "classifier"],
                    },
                    {
                        "document_id": "doc_verified",
                        "title": "Verified Prototype Source",
                        "status": "verified_doi",
                        "bibtex_key": "source2026",
                        "doi": "10.1234/verified",
                        "url": "https://example.test/verified",
                        "reason": None,
                        "abstract": "Nearest centroid prototype classifier evidence for UCI Pendigits.",
                        "venue": "MethodConf",
                        "source_uri": "https://example.test/verified",
                        "authors": ["V. Source"],
                        "tags": ["pendigits", "nearest-centroid", "prototype-classifier"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    validation_path = experiment_dir / "validation" / "validation-report.json"
    validation_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "issues": [],
                "statistical_notes": [
                    {
                        "metric_name": "accuracy",
                        "message": "95% CI for accuracy mean: [0.80, 0.84]",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence_map_path = experiment_dir / "evidence" / "evidence-map.json"
    evidence_map_path.write_text(json.dumps({"evidence_edges": []}), encoding="utf-8")
    report_path = experiment_dir / "report" / "report.md"
    report_path.write_text("# Short report\n\n## Results\n\n- accuracy = 0.82\n", encoding="utf-8")
    run_record_path = experiment_dir / "run" / "run-record.json"
    run_record_path.write_text(
        json.dumps(
            {
                "run": {
                    "task_id": "pendigits_variance_calibrated_prototypes",
                    "status": "success",
                    "exit_code": 0,
                },
                "metrics": {
                    "values": {
                        "accuracy": 0.82,
                        "macro_f1": 0.81,
                        "baseline_accuracy": 0.78,
                        "accuracy_delta_vs_baseline": 0.04,
                        "zscore_centroid_accuracy": 0.79,
                        "accuracy_delta_vs_zscore": 0.03,
                        "test_rows": 3498,
                        "train_rows": 7494,
                        "dataset_rows": 10992,
                        "class_count": 10,
                        "feature_count": 12,
                        "accuracy_standard_error": 0.006,
                        "variance_shrinkage": 0.05,
                    }
                },
                "task_metadata": {
                    "real_dataset": True,
                    "dataset": "UCI Pendigits",
                    "split_policy": "official train and test split",
                    "baseline": "nearest-centroid classifier",
                    "ablation": "z-score centroid ablation",
                    "proposed_method": "diagonal variance-calibrated class prototypes",
                },
                "artifacts": [
                    "artifacts/ablation.csv",
                    "artifacts/dataset_sources.json",
                    "artifacts/innovation_evidence.json",
                ],
                "logs": ["logs/run.log"],
            }
        ),
        encoding="utf-8",
    )
    summary = {
        "cycle_id": "cycle-test",
        "candidate": {
            "title": "Variance-calibrated prototype classifiers for UCI Pendigits",
            "description": "Evaluate a variance-calibrated prototype candidate.",
            "research_gap": "Nearest-centroid baselines need auditable variance calibration tests.",
            "metadata": {
                "method": "diagonal variance-calibrated prototypes",
                "dataset": "UCI Pendigits",
                "baseline": "nearest centroid classifier",
                "benchmark": "UCI Pendigits",
                "limitation": "single benchmark",
                "seed_document_title": "Variance function of boolean additive convolution",
            },
        },
        "literature": {
            "document_count": 20,
            "fetches": [
                {"source": "arxiv", "paper_count": 10, "error": None},
                {"source": "openalex", "paper_count": 10, "error": None},
            ],
            "summary_path": literature_path.as_posix(),
        },
        "citations": {
            "status": "generated",
            "verified_count": 1,
            "blocked_count": 0,
            "bib_path": citation_bib_path.as_posix(),
            "metadata_path": citation_metadata_path.as_posix(),
            "blocked_document_ids": [],
        },
        "similarity": {
            "finding_count": 2,
            "fetches": [
                {"source": "arxiv", "paper_count": 1, "error": None},
                {"source": "openalex", "paper_count": 1, "error": None},
            ],
            "summary_path": similarity_path.as_posix(),
        },
        "demo": {
            "experiment_dir": experiment_dir.as_posix(),
            "report_path": report_path.as_posix(),
            "run_record_path": run_record_path.as_posix(),
            "validation_json_path": validation_path.as_posix(),
            "evidence_map_path": evidence_map_path.as_posix(),
        },
        "review": {"status": "passed", "quality_score": 1.0, "verdict": "pass"},
        "reproduction_check": {
            "status": "passed",
            "exit_code": 0,
            "run_record_paths": ["rerun/run-record.json"],
            "validation_json_paths": ["rerun/validation-report.json"],
        },
    }
    summary_path = cycle_dir / "cycle-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary_path
