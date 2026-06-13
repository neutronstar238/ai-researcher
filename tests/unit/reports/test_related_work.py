import json
from pathlib import Path

from autoresearch.reports import inspect_related_work


def test_inspect_related_work_writes_source_backed_screening_artifact(
    tmp_path: Path,
) -> None:
    summary_path = _write_cycle(tmp_path)

    artifact = inspect_related_work(
        cycle_summary_path=summary_path,
        output_dir=tmp_path / "related-work",
    )

    payload = json.loads(Path(artifact.json_path).read_text(encoding="utf-8"))
    markdown = Path(artifact.markdown_path).read_text(encoding="utf-8")
    assert artifact.inspected_count == 3
    assert artifact.source_backed_count == 2
    assert artifact.abstract_backed_count == 1
    assert artifact.direct_method_count == 1
    assert payload["records"][0]["comparison_status"] == "direct_method_candidate"
    assert payload["records"][0]["evidence_basis"] == "abstract"
    assert "nearest" in payload["records"][0]["method_overlap_terms"]
    assert payload["records"][1]["comparison_status"] == "metadata_only"
    assert payload["records"][2]["comparison_status"] == "blocked_unverified"
    assert "Related Work Inspection" in markdown
    assert "Direct method candidates: `1`" in markdown


def _write_cycle(tmp_path: Path) -> Path:
    cycle_dir = tmp_path / "cycle"
    citations_dir = cycle_dir / "citations"
    run_dir = cycle_dir / "demo" / "run"
    citations_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    metadata_path = citations_dir / "references.metadata.json"
    bib_path = citations_dir / "references.bib"
    metadata_path.write_text(
        json.dumps(
            {
                "citations": [
                    {
                        "document_id": "direct",
                        "title": "Nearest centroid prototype classifiers for Pendigits",
                        "status": "verified_url",
                        "bibtex_key": "direct2026",
                        "url": "https://example.test/direct",
                        "abstract": (
                            "Compares nearest centroid prototype classifiers on the "
                            "Pendigits handwritten digit benchmark."
                        ),
                        "venue": "ExampleConf",
                        "source_uri": "https://example.test/direct",
                        "authors": ["A. Author"],
                        "tags": ["nearest-centroid", "prototype-classifier"],
                    },
                    {
                        "document_id": "metadata",
                        "title": "Prototype classifier notes",
                        "status": "verified_url",
                        "bibtex_key": "metadata2026",
                        "url": "https://example.test/metadata",
                        "abstract": None,
                        "venue": "ExampleConf",
                        "source_uri": "https://example.test/metadata",
                        "authors": ["B. Author"],
                        "tags": ["prototype"],
                    },
                    {
                        "document_id": "blocked",
                        "title": "Unverified note",
                        "status": "blocked",
                        "bibtex_key": None,
                        "url": None,
                        "abstract": None,
                        "venue": None,
                        "source_uri": None,
                        "authors": [],
                        "tags": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    bib_path.write_text("@misc{direct2026,title={Direct}}\n", encoding="utf-8")
    run_record_path = run_dir / "run-record.json"
    run_record_path.write_text(
        json.dumps(
            {
                "task_metadata": {
                    "proposed_method": "nearest centroid prototype classifier",
                    "dataset": "Pendigits handwritten digit benchmark",
                    "baseline": "nearest centroid",
                },
                "run": {"task_id": "pendigits_variance_calibrated_prototypes"},
            }
        ),
        encoding="utf-8",
    )
    summary = {
        "cycle_id": "cycle-test",
        "candidate": {
            "title": "Variance calibrated prototypes for Pendigits",
            "metadata": {
                "method": "nearest centroid prototype classifier",
                "dataset": "Pendigits",
                "baseline": "nearest centroid",
            },
        },
        "citations": {
            "metadata_path": metadata_path.as_posix(),
            "bib_path": bib_path.as_posix(),
        },
        "demo": {
            "demo": "pendigits_variance_calibrated_prototypes",
            "run_record_path": run_record_path.as_posix(),
        },
    }
    summary_path = cycle_dir / "cycle-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary_path
