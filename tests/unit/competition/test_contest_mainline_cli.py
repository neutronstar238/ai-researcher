"""Focused tests for the contest mainline delivery CLI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.contest_mainline_cli import (
    ContestMainlineDeliveryError,
    _load_selected_skill_contexts,
    run_contest_mainline_delivery,
)

_FAKE_SHA = "a" * 64


class _Stub:
    """Attribute-only stand-in for typed artifacts the mainline only reads."""

    def __init__(self, **values: Any) -> None:
        for key, value in values.items():
            setattr(self, key, value)


def _pilot_stub(
    run_id: str = "pilot-test",
    metrics_sha256: str = _FAKE_SHA,
) -> _Stub:
    return _Stub(
        status="completed",
        study_phase="exploratory_pilot",
        formal_experiment_executed=False,
        mathematical_proof_claimed=False,
        artifact_hash=_FAKE_SHA,
        run_id=run_id,
        metrics_relative_path="metrics.json",
        metrics_sha256=metrics_sha256,
        manifest_sha256=_FAKE_SHA,
    )


def _revision_stub() -> _Stub:
    return _Stub(
        generation_calls=1,
        document_type="含真实预实验结果的科学假设与研究计划",
        status="revised_from_verified_preexperiment",
        provider="qwen-dashscope",
        model_name="qwen3.7-max",
        input_hash=_FAKE_SHA,
        model_response_hash=_FAKE_SHA,
        artifact_hash=_FAKE_SHA,
        revision_id="direct-plan-revision-aaaaaaaaaaaaaaaa",
        flat_payload=lambda: {"title": "测试标题", "abstract": "测试摘要"},
    )


def _write_question(root: Path) -> Path:
    payload = {
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
        "source_file_sha256": _FAKE_SHA,
        "extracted_page_sha256": _FAKE_SHA,
        "extraction_backend": "poppler-pdftotext-layout",
        "extraction_evidence": ("line-one", "line-two"),
        "translation_provenance": "仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF文本层",
    }
    path = root / "question-input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_plan_stage(root: Path, skill_path: Path) -> dict[str, Any]:
    plan_root = Path(root)
    (plan_root / "plan").mkdir(parents=True, exist_ok=True)
    _write_question(plan_root)
    (plan_root / "system-authored-research-plan.json").write_text(
        json.dumps({"plan_id": "test"}), encoding="utf-8"
    )
    (plan_root / "plan" / "research-plan.json").write_text(
        json.dumps({"title": "渲染计划"}), encoding="utf-8"
    )
    skill_content = skill_path.read_text(encoding="utf-8")
    skill_sha = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": "contest-direct-selected-skills-v1",
        "skills": [
            {
                "skill_id": "prime-structure-computational-number-theory",
                "content_sha256": skill_sha,
                "path": str(skill_path),
            }
        ],
    }
    (plan_root / "selected-method-skills.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (plan_root / "delivery-report.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    return {"status": "completed", "selected_method_skill_ids": ["prime-structure-computational-number-theory"]}


def _materializer_stub(payload: Mapping[str, Any], output_dir: Path, **_: Any) -> _Stub:
    del payload  # the stub intentionally skips payload validation
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in ("research-plan.json", "research-plan.md", "research-plan.tex", "research-plan.pdf", "research-plan-manifest.json"):
        path = output / name
        path.write_text("stub", encoding="utf-8")
        paths[name] = path
    source_path = output / "_private" / "research-plan-source.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("stub", encoding="utf-8")
    return _Stub(
        json_path=paths["research-plan.json"],
        markdown_path=paths["research-plan.md"],
        tex_path=paths["research-plan.tex"],
        pdf_path=paths["research-plan.pdf"],
        manifest_path=paths["research-plan-manifest.json"],
        source_path=source_path,
        to_dict=lambda: {
            "output_dir": str(output),
            "page_count": 3,
            "pdf_text_verified": True,
        },
    )


@pytest.fixture()
def skill_file(tmp_path: Path) -> Path:
    skills = tmp_path / "skills" / "prime-structure-computational-number-theory"
    skills.mkdir(parents=True)
    path = skills / "SKILL.md"
    path.write_text("---\nname: 计算数论\ndescription: 素数结构方法\n---\n正文\n", encoding="utf-8")
    return path


def test_successful_mainline_writes_report(tmp_path: Path, skill_file: Path) -> None:
    def plan_runner(**kwargs: Any) -> dict[str, Any]:
        return _write_plan_stage(Path(kwargs["output_dir"]), skill_file)

    def preexperiment_runner(output_dir: Path, **_: Any) -> _Stub:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "prime-preexperiment.json").write_text("{}", encoding="utf-8")
        (root / "metrics.json").write_text("{}", encoding="utf-8")
        return _pilot_stub(metrics_sha256=hashlib.sha256(b"{}").hexdigest())

    def preexperiment_loader(path: Path, **_: Any) -> _Stub:
        del path  # the stub intentionally skips file verification
        return _pilot_stub(metrics_sha256=hashlib.sha256(b"{}").hexdigest())

    def revision_runner(**kwargs: Any) -> _Stub:
        Path(kwargs["output_dir"]).mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_text("{}", encoding="utf-8")
        return _revision_stub()

    report = run_contest_mainline_delivery(
        question_pdf=tmp_path / "booklet.pdf",
        output_dir=tmp_path / "out",
        plan_runner=plan_runner,
        preexperiment_runner=preexperiment_runner,
        preexperiment_loader=preexperiment_loader,
        revision_runner=revision_runner,
        evidence_builder=lambda *_, **__: None,
        plan_materializer=_materializer_stub,
    )
    assert report["status"] == "completed"
    assert report["schema_version"] == "contest-mainline-delivery-v1"
    assert report["preexperiment"]["run_id"] == "pilot-test"
    assert report["revision"]["generation_calls"] == 1
    assert report["formal_experiment_executed"] is False
    report_path = Path(report["delivery_report_path"])
    assert report_path.is_file()
    assert report_path.parent == (tmp_path / "out").resolve()


def test_plan_stage_failure_propagates(tmp_path: Path) -> None:
    with pytest.raises(ContestMainlineDeliveryError, match="plan stage"):
        run_contest_mainline_delivery(
            question_pdf=tmp_path / "booklet.pdf",
            output_dir=tmp_path / "out",
            plan_runner=lambda **_: {"status": "failed"},
            preexperiment_runner=lambda **_: _pilot_stub(),
            preexperiment_loader=lambda *_, **__: _pilot_stub(),
            revision_runner=lambda **_: _revision_stub(),
            evidence_builder=lambda *_, **__: None,
            plan_materializer=_materializer_stub,
        )


def test_preexperiment_mismatch_rejected(tmp_path: Path, skill_file: Path) -> None:
    def plan_runner(**kwargs: Any) -> dict[str, Any]:
        return _write_plan_stage(Path(kwargs["output_dir"]), skill_file)

    def preexperiment_runner(output_dir: Path, **_: Any) -> _Stub:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "prime-preexperiment.json").write_text("{}", encoding="utf-8")
        return _pilot_stub(run_id="generated-run")

    def preexperiment_loader(path: Path, **_: Any) -> _Stub:
        del path  # the stub intentionally skips file verification
        return _pilot_stub(run_id="different-run")

    with pytest.raises(ContestMainlineDeliveryError, match="differs from the runner"):
        run_contest_mainline_delivery(
            question_pdf=tmp_path / "booklet.pdf",
            output_dir=tmp_path / "out",
            plan_runner=plan_runner,
            preexperiment_runner=preexperiment_runner,
            preexperiment_loader=preexperiment_loader,
            revision_runner=lambda **_: _revision_stub(),
            evidence_builder=lambda *_, **__: None,
            plan_materializer=_materializer_stub,
        )


def test_revision_call_count_enforced(tmp_path: Path, skill_file: Path) -> None:
    def plan_runner(**kwargs: Any) -> dict[str, Any]:
        return _write_plan_stage(Path(kwargs["output_dir"]), skill_file)

    def preexperiment_runner(output_dir: Path, **_: Any) -> _Stub:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "prime-preexperiment.json").write_text("{}", encoding="utf-8")
        (Path(output_dir) / "metrics.json").write_text("{}", encoding="utf-8")
        return _pilot_stub(metrics_sha256=hashlib.sha256(b"{}").hexdigest())

    bad_revision = _revision_stub()
    bad_revision.generation_calls = 2
    with pytest.raises(ContestMainlineDeliveryError, match="exactly one model"):
        run_contest_mainline_delivery(
            question_pdf=tmp_path / "booklet.pdf",
            output_dir=tmp_path / "out",
            plan_runner=plan_runner,
            preexperiment_runner=preexperiment_runner,
            preexperiment_loader=lambda *_, **__: _pilot_stub(),
            revision_runner=lambda **_: bad_revision,
            evidence_builder=lambda *_, **__: None,
            plan_materializer=_materializer_stub,
        )


def test_output_directory_must_be_empty(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "occupied.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ContestMainlineDeliveryError, match="new or empty"):
        run_contest_mainline_delivery(
            question_pdf=tmp_path / "booklet.pdf",
            output_dir=output,
            plan_runner=lambda **_: {"status": "completed"},
            preexperiment_runner=lambda **_: _pilot_stub(),
            preexperiment_loader=lambda *_, **__: _pilot_stub(),
            revision_runner=lambda **_: _revision_stub(),
            evidence_builder=lambda *_, **__: None,
            plan_materializer=_materializer_stub,
        )


def test_skill_manifest_hash_mismatch_rejected(tmp_path: Path, skill_file: Path) -> None:
    plan_root = tmp_path / "01-plan"
    (plan_root / "plan").mkdir(parents=True)
    _write_question(plan_root)
    (plan_root / "system-authored-research-plan.json").write_text(
        json.dumps({"plan_id": "test"}), encoding="utf-8"
    )
    (plan_root / "plan" / "research-plan.json").write_text(
        json.dumps({"title": "渲染计划"}), encoding="utf-8"
    )
    (plan_root / "delivery-report.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    manifest = {
        "schema_version": "contest-direct-selected-skills-v1",
        "skills": [
            {
                "skill_id": "prime-structure-computational-number-theory",
                "content_sha256": "b" * 64,
                "path": str(skill_file),
            }
        ],
    }
    (plan_root / "selected-method-skills.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ContestMainlineDeliveryError, match="hash mismatch"):
        _load_selected_skill_contexts(plan_root / "selected-method-skills.json")


def test_loader_returns_revision_artifact_shape(tmp_path: Path, skill_file: Path) -> None:
    # Sanity: the loader helper returns the exact context shape the revision consumes.
    plan_root = tmp_path / "01-plan"
    plan_root.mkdir()
    manifest = {
        "schema_version": "contest-direct-selected-skills-v1",
        "skills": [
            {
                "skill_id": "prime-structure-computational-number-theory",
                "content_sha256": hashlib.sha256(
                    skill_file.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "path": str(skill_file),
            }
        ],
    }
    (plan_root / "selected-method-skills.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    contexts = _load_selected_skill_contexts(plan_root / "selected-method-skills.json")
    assert len(contexts) == 1
    assert set(contexts[0]) == {"skill_id", "name", "content", "content_sha256"}
    assert contexts[0]["content"].startswith("---\n")


def test_reuse_plan_and_preexperiment_sources(tmp_path: Path, skill_file: Path) -> None:
    # A failed revision must not force a full re-run: reuse both completed stages.
    plan_source = tmp_path / "plan-source"
    _write_plan_stage(plan_source, skill_file)
    pilot_source = tmp_path / "pilot-source"
    pilot_source.mkdir()
    (pilot_source / "prime-preexperiment.json").write_text("{}", encoding="utf-8")
    (pilot_source / "metrics.json").write_text("{}", encoding="utf-8")
    pilot = _pilot_stub(metrics_sha256=hashlib.sha256(b"{}").hexdigest())
    pilot.source_plan_sha256 = hashlib.sha256(
        json.dumps({"title": "渲染计划"}).encode("utf-8")
    ).hexdigest()

    def revision_runner(**kwargs: Any) -> _Stub:
        Path(kwargs["output_dir"]).mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_text("{}", encoding="utf-8")
        return _revision_stub()

    report = run_contest_mainline_delivery(
        question_pdf=tmp_path / "booklet.pdf",
        output_dir=tmp_path / "out",
        plan_source_dir=plan_source,
        preexperiment_source_dir=pilot_source,
        preexperiment_loader=lambda *_, **__: pilot,
        revision_runner=revision_runner,
        evidence_builder=lambda *_, **__: None,
        plan_materializer=_materializer_stub,
    )
    assert report["status"] == "completed"
    assert report["preexperiment"]["run_id"] == "pilot-test"
    # plan stage binding points at the reused source, not at a fresh 01-plan
    assert "plan-source" in report["plan_stage"]["rendered_plan"]["path"]


def test_reused_preexperiment_plan_binding_enforced(tmp_path: Path, skill_file: Path) -> None:
    plan_source = tmp_path / "plan-source"
    _write_plan_stage(plan_source, skill_file)
    pilot_source = tmp_path / "pilot-source"
    pilot_source.mkdir()
    (pilot_source / "prime-preexperiment.json").write_text("{}", encoding="utf-8")
    (pilot_source / "metrics.json").write_text("{}", encoding="utf-8")
    pilot = _pilot_stub(metrics_sha256=hashlib.sha256(b"{}").hexdigest())
    pilot.source_plan_sha256 = "f" * 64  # deliberately wrong plan binding

    with pytest.raises(ContestMainlineDeliveryError, match="verified plan"):
        run_contest_mainline_delivery(
            question_pdf=tmp_path / "booklet.pdf",
            output_dir=tmp_path / "out",
            plan_source_dir=plan_source,
            preexperiment_source_dir=pilot_source,
            preexperiment_loader=lambda *_, **__: pilot,
            revision_runner=lambda **_: _revision_stub(),
            evidence_builder=lambda *_, **__: None,
            plan_materializer=_materializer_stub,
        )
