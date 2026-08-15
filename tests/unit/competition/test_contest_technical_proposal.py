"""Focused tests for the deterministic contest technical-proposal builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import autoresearch.competition.contest_technical_proposal as module
from autoresearch.competition.contest_technical_proposal import (
    ContestTechnicalProposalError,
    build_technical_proposal_payload,
    materialize_technical_proposal,
    render_technical_proposal_markdown,
    render_technical_proposal_tex,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_delivery(root: Path) -> dict[str, Any]:
    """Write a minimal but schema-valid contest-mainline delivery."""

    root.mkdir(parents=True, exist_ok=True)
    plan_root = root / "01-plan"
    plan_root.mkdir(exist_ok=True)
    question = {
        "schema_version": "contest-question-input-v1",
        "question_id": "science125-q001-d3a6861ef6c09218",
        "ordinal": 1,
        "question_en": "What makes prime numbers so special?",
        "question_zh": "素数为何如此特别？",
        "discipline_en": "Mathematical Sciences",
        "discipline_zh": "数学科学",
        "source_title": "Science 125 Questions",
        "source_year": 2021,
        "pdf_page_number": 1,
        "source_pdf_path": str(root / "booklet.pdf"),
        "source_file_sha256": _sha(b"x"),
        "extracted_page_sha256": _sha(b"x"),
        "extraction_backend": "poppler-pdftotext-layout",
        "extraction_evidence": ("line-one", "line-two"),
        "translation_provenance": "仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF文本层",
    }
    (plan_root / "question-input.json").write_text(
        json.dumps(question, ensure_ascii=False), encoding="utf-8"
    )
    plan_report_path = plan_root / "delivery-report.json"
    plan_report_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

    pilot_root = root / "02-preexperiment"
    pilot_root.mkdir(exist_ok=True)
    metrics = {
        "aggregate_results": [
            {
                "null_model": "residue_path_conditioned_permutation",
                "observed_mean_entropy": 0.929,
                "null_mean_entropy": 0.930,
                "delta_observed_minus_null": -0.0011,
            }
        ]
    }
    metrics_path = pilot_root / "metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    final_pdf = root / "04-final-plan" / "research-plan.pdf"
    final_pdf.parent.mkdir(exist_ok=True)
    final_pdf.write_bytes(b"%PDF-stub")

    report = {
        "schema_version": "contest-mainline-delivery-v1",
        "status": "completed",
        "question_id": question["question_id"],
        "question_zh": question["question_zh"],
        "question_en": question["question_en"],
        "plan_stage": {
            "report": {
                "path": str(plan_report_path),
                "sha256": _sha(b'{"status": "completed"}'),
            },
            "selected_skill_ids": [],
            "system_authored_plan": {"path": str(root / "x.json"), "sha256": _sha(b"x")},
            "rendered_plan": {"path": str(root / "y.json"), "sha256": _sha(b"x")},
        },
        "preexperiment": {
            "run_id": "pilot-test",
            "status": "completed",
            "study_phase": "exploratory_pilot",
            "artifact": {"path": str(root / "a.json"), "sha256": _sha(b"x")},
            "metrics": {
                "path": str(metrics_path),
                "sha256": _sha(metrics_path.read_bytes()),
            },
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
        },
        "revision": {
            "artifact": {"path": str(root / "r.json"), "sha256": _sha(b"x")},
            "provider": "qwen-dashscope",
            "model_name": "qwen3.7-max",
            "generation_calls": 1,
            "artifact_hash": _sha(b"r"),
            "revision_id": "direct-plan-revision-aaaaaaaaaaaaaaaa",
        },
        "rendered": {
            "artifacts": {
                "pdf": {
                    "path": str(final_pdf),
                    "sha256": _sha(b"%PDF-stub"),
                }
            },
            "page_count": 6,
            "pdf_text_verified": True,
        },
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    (root / "delivery-report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    return report


def test_payload_reads_completed_mainline(tmp_path: Path) -> None:
    report = _write_delivery(tmp_path / "delivery")
    payload = build_technical_proposal_payload(tmp_path / "delivery")
    assert payload["schema_version"] == "contest-technical-proposal-v1"
    assert payload["question_zh"] == "素数为何如此特别？"
    case = payload["case_study"]
    assert case["pilot_run_id"] == "pilot-test"
    assert case["revision_model_name"] == "qwen3.7-max"
    assert case["page_count"] == 6
    assert case["formal_experiment_executed"] is False
    assert len(case["pilot_numbers"]) == 1
    assert case["pilot_numbers"][0][3] == "-0.001100"
    assert report["rendered"]["artifacts"]["pdf"]["sha256"] == case["final_plan_pdf"]["sha256"]
    assert payload["source_inventory"]
    assert all(item["sha256"] for item in payload["source_inventory"])


def test_payload_rejects_non_mainline_delivery(tmp_path: Path) -> None:
    root = tmp_path / "delivery"
    root.mkdir()
    (root / "delivery-report.json").write_text(
        json.dumps({"schema_version": "other", "status": "completed"}), encoding="utf-8"
    )
    with pytest.raises(ContestTechnicalProposalError, match="contest-mainline"):
        build_technical_proposal_payload(root)


def test_payload_rejects_incomplete_delivery(tmp_path: Path) -> None:
    root = tmp_path / "delivery"
    root.mkdir()
    (root / "delivery-report.json").write_text(
        json.dumps(
            {"schema_version": "contest-mainline-delivery-v1", "status": "blocked"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContestTechnicalProposalError, match="not completed"):
        build_technical_proposal_payload(root)


def test_renders_contain_required_sections(tmp_path: Path) -> None:
    _write_delivery(tmp_path / "delivery")
    payload = build_technical_proposal_payload(tmp_path / "delivery")
    markdown = render_technical_proposal_markdown(payload)
    tex = render_technical_proposal_tex(payload)
    for expected in (
        "待研究问题与方法",
        "多智能体 / Skills 架构",
        "真实案例",
        "源码说明",
    ):
        assert expected in markdown
    for expected in (
        "待研究问题与方法",
        "多智能体 / Skills 架构",
        "真实案例",
        "源码说明",
        "pilot-test",
        "qwen3.7-max",
    ):
        assert expected in tex
    assert "开发中" in markdown


def test_materialize_fails_closed_over_page_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_delivery(tmp_path / "delivery")

    def fake_compile(tex_path: Path, **_: Any) -> tuple[str, Path | None, str | None, int | None]:
        pdf = tex_path.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        return "compiled", pdf, None, 21

    monkeypatch.setattr(module, "compile_research_plan_pdf", fake_compile)
    with pytest.raises(ContestTechnicalProposalError, match="21 pages"):
        materialize_technical_proposal(
            tmp_path / "delivery",
            output_dir=tmp_path / "proposal",
        )


def test_materialize_success_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_delivery(tmp_path / "delivery")

    def fake_compile(tex_path: Path, **_: Any) -> tuple[str, Path | None, str | None, int | None]:
        pdf = tex_path.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        return "compiled", pdf, None, 8

    monkeypatch.setattr(module, "compile_research_plan_pdf", fake_compile)
    report = materialize_technical_proposal(
        tmp_path / "delivery",
        output_dir=tmp_path / "proposal",
    )
    assert report["status"] == "completed"
    assert report["page_count"] == 8
    assert report["page_limit_passed"] is True
    assert report["formal_experiment_executed"] is False
    report_path = Path(report["delivery_report_path"])
    assert report_path.is_file()
    artifacts = report["artifacts"]
    assert Path(artifacts["pdf"]["path"]).is_file()
    assert Path(artifacts["tex"]["path"]).is_file()
    assert Path(artifacts["markdown"]["path"]).is_file()
    assert Path(artifacts["json"]["path"]).is_file()


def test_payload_binds_every_source_module(tmp_path: Path) -> None:
    _write_delivery(tmp_path / "delivery")
    payload = build_technical_proposal_payload(tmp_path / "delivery")
    paths = {item["path"] for item in payload["source_inventory"]}
    assert "src/autoresearch/competition/contest_mainline_cli.py" in paths
    assert "src/autoresearch/competition/contest_direction_research_loop_cli.py" in paths
    statuses = {item["status"] for item in payload["source_inventory"]}
    assert {"主线", "能力", "开发中"} <= statuses
