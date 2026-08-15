from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoresearch.competition.contest_prime_feedback_cli as feedback_cli
from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    ContestDirectScientificPlan,
)
from autoresearch.competition.contest_direct_plan_render import ContestDirectPlanArtifacts
from autoresearch.competition.contest_prime_feedback_cli import (
    ContestPrimeFeedbackDeliveryError,
    run_contest_prime_feedback_delivery,
)
from autoresearch.competition.contest_question_input import ContestQuestionInput
from autoresearch.competition.manifest import canonical_model_hash


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _source_delivery(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source-delivery"
    source.mkdir()
    pdf_path = tmp_path / "booklet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nunit-test-booklet\n%%EOF\n")
    question = ContestQuestionInput(
        question_id="science125-q001-0123456789abcdef",
        question_en="What makes prime numbers so special?",
        question_zh="素数为何如此特别？",
        discipline_en="Mathematical Sciences",
        discipline_zh="数学科学",
        source_title="125 Questions: Exploration and Discovery",
        pdf_page_number=7,
        printed_page_number=5,
        source_pdf_path=pdf_path.as_posix(),
        source_file_sha256=_sha256(pdf_path),
        extracted_page_sha256="1" * 64,
        extraction_evidence=("数学科学栏目", "首个英文问句"),
    )
    _write_json(source / "question-input.json", question.model_dump(mode="json"))

    scientific_plan = ContestDirectScientificPlan(
        problem_statement="研究有限区间素数间隙的局部顺序结构。",
        rationale="以可证伪对照区分密度效应与顺序效应。",
        technical_details="计算含并列处理的排列熵并实施条件置换。",
        datasets="由确定性筛法生成的有限区间素数间隙。",
        source="本地确定性分段筛法输出。",
        target="每个区间的有序素数间隙序列。",
        paper_title="有限尺度素数间隙预实验计划",
        paper_abstract="本计划比较观测序列与多个约束零模型。",
        methods="冻结区间、指标、随机种子与对照。",
        experiments="先执行探索性预实验，再决定正式实验。",
        baselines="局部分块置换与残基路径条件置换。",
        metrics="含并列排列熵、效应量和经验概率。",
        results="尚未执行预实验，不报告观察结果。",
        references=("真实参考文献 https://example.test/reference",),
    )
    plan_payload: dict[str, Any] = {
        "schema_version": "contest-direct-research-plan-v1",
        "document_type": "科学假设与研究计划",
        "plan_id": "direct-plan-" + "2" * 16,
        "status": "research_plan_generated",
        "scientific_problem": "素数为何如此特别？",
        "literature_context_provided": True,
        "preexperiment_context_status": "not_provided",
        "plan": scientific_plan.model_dump(mode="json"),
        "provider": "test-provider",
        "model_name": "test-model",
        "generation_calls": 1,
        "json_repair_applied": False,
        "input_hash": "2" * 64,
        "model_response_hash": "3" * 64,
    }
    plan_payload["artifact_hash"] = canonical_model_hash(plan_payload)
    original = ContestDirectPlanArtifact.model_validate(plan_payload)
    original_path = source / "system-authored-research-plan.json"
    _write_json(original_path, original.model_dump(mode="json"))

    rendered_source_path = source / "plan" / "research-plan.json"
    _write_json(
        rendered_source_path,
        {
            "title": scientific_plan.paper_title,
            "question": question.model_dump(mode="json"),
            "generation": {"artifact_hash": original.artifact_hash},
        },
    )

    skill_path = tmp_path / "skills" / "prime-method" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_content = "---\nname: prime-method\ndescription: 数论方法\n---\n真实方法正文。\n"
    skill_path.write_text(skill_content, encoding="utf-8")
    skill_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
    routing_payload: dict[str, Any] = {
        "schema_version": "test-routing-v1",
        "selected_skill_ids": ["prime-method"],
        "selected_skill_hashes": {"prime-method": skill_hash},
        "skill_bodies_visible_to_selector": False,
    }
    routing_payload["artifact_hash"] = canonical_model_hash(routing_payload)
    routing_path = source / "skill-routing.json"
    _write_json(routing_path, routing_payload)
    _write_json(
        source / "selected-method-skills.json",
        {
            "schema_version": "contest-direct-selected-skills-v1",
            "skills": [
                {
                    "skill_id": "prime-method",
                    "path": skill_path.as_posix(),
                    "content_sha256": skill_hash,
                }
            ],
            "routing_artifact_path": routing_path.as_posix(),
            "routing_artifact_hash": routing_payload["artifact_hash"],
        },
    )
    return source, rendered_source_path, skill_path


def _make_pilot(root: Path, *, source_plan_path: Path) -> Any:
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "raw" / "interval.csv"
    raw_path.parent.mkdir()
    raw_path.write_text("prime_left,prime_right,gap\n11,13,2\n", encoding="utf-8")
    metrics_path = root / "metrics.json"
    _write_json(metrics_path, {"status": "completed", "observed_entropy": 0.91})
    stdout_path = root / "logs" / "stdout.log"
    stdout_path.parent.mkdir()
    stdout_path.write_text("program_status=completed\n", encoding="utf-8")
    stderr_path = root / "logs" / "stderr.log"
    stderr_path.write_text("", encoding="utf-8")
    evidence = tuple(
        SimpleNamespace(
            relative_path=path.relative_to(root).as_posix(),
            sha256=_sha256(path),
            bytes=path.stat().st_size,
            kind=kind,
        )
        for path, kind in (
            (raw_path, "raw_result"),
            (metrics_path, "metrics"),
            (stdout_path, "stdout_log"),
            (stderr_path, "stderr_log"),
        )
    )
    manifest_path = root / "manifest.json"
    _write_json(
        manifest_path,
        {
            "status": "completed",
            "files": [
                {
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "bytes": item.bytes,
                    "kind": item.kind,
                }
                for item in evidence
            ],
        },
    )
    artifact_hash = "4" * 64
    artifact_path = root / "prime-preexperiment.json"
    _write_json(
        artifact_path,
        {
            "run_id": "prime-pilot-0123456789abcdef",
            "status": "completed",
            "artifact_hash": artifact_hash,
        },
    )
    return SimpleNamespace(
        run_id="prime-pilot-0123456789abcdef",
        status="completed",
        study_phase="exploratory_pilot",
        scientific_question="素数为何如此特别？",
        source_plan_sha256=_sha256(source_plan_path),
        formal_experiment_executed=False,
        mathematical_proof_claimed=False,
        artifact_hash=artifact_hash,
        metrics_relative_path="metrics.json",
        metrics_sha256=_sha256(metrics_path),
        manifest_relative_path="manifest.json",
        manifest_sha256=_sha256(manifest_path),
        manifest_hash="5" * 64,
        stdout_log_relative_path="logs/stdout.log",
        stdout_log_sha256=_sha256(stdout_path),
        stderr_log_relative_path="logs/stderr.log",
        stderr_log_sha256=_sha256(stderr_path),
        evidence_files=evidence,
    )


class _FakeRevision:
    document_type = "含真实预实验结果的科学假设与研究计划"
    status = "revised_from_verified_preexperiment"
    revision_id = "direct-plan-revision-" + "6" * 16
    provider = "qwen-test"
    model_name = "qwen-test-model"
    generation_calls = 1
    input_hash = "6" * 64
    model_response_hash: str
    authorship_receipt_hash = "7" * 64
    artifact_hash = "8" * 64
    raw_response_relative_path = "responses/revision.txt"
    authorship_receipt_relative_path = "interactions/revision.json"

    def flat_payload(self) -> dict[str, Any]:
        return {
            "title": "真实预实验反馈后的素数研究计划",
            "abstract": "本计划根据真实预实验结果收窄假设。",
            "problem_statement": "检验有限区间的局部顺序结构。",
            "rationale": "主假设已按预实验反馈修订。",
            "technical_details": "继续使用条件零模型并报告替代解释。",
            "datasets": {
                "description": "真实筛法输出。",
                "source": "原始素数间隙文件。",
                "target": "有序间隙序列。",
            },
            "methods": "冻结协议后实施。",
            "experiments": {
                "steps": "扩大独立区间。",
                "baselines": "多个条件零模型。",
                "metrics": "排列熵和效应量。",
            },
            "results": "预实验观察熵为0.91；这不是正式实验或证明。",
            "references": ["真实参考文献"],
        }


def _dependencies(calls: list[str], pilot_holder: dict[str, Any]) -> dict[str, Any]:
    def runner(*, output_dir: Path, source_plan_path: Path) -> Any:
        calls.append("run-preexperiment")
        pilot = _make_pilot(Path(output_dir), source_plan_path=Path(source_plan_path))
        pilot_holder["pilot"] = pilot
        pilot_holder["path"] = Path(output_dir) / "prime-preexperiment.json"
        return pilot

    def loader(path: Path, *, verify_files: bool) -> Any:
        calls.append("load-preexperiment")
        assert verify_files is True
        assert Path(path).resolve() == Path(pilot_holder["path"]).resolve()
        return pilot_holder["pilot"]

    def revision_runner(**kwargs: Any) -> _FakeRevision:
        calls.append("revise")
        assert kwargs["preexperiment_metrics"] is None
        assert kwargs["selected_skill_contexts"][0]["content"].endswith("真实方法正文。\n")
        assert kwargs["requirements"]
        assert kwargs["temperature"] == 0.2
        output_root = Path(kwargs["output_dir"])
        response_path = output_root / _FakeRevision.raw_response_relative_path
        response_path.parent.mkdir(parents=True)
        response_path.write_text("一次真实结果反馈", encoding="utf-8")
        revision = _FakeRevision()
        revision.model_response_hash = _sha256(response_path)
        receipt_path = output_root / revision.authorship_receipt_relative_path
        _write_json(receipt_path, {"receipt_hash": revision.authorship_receipt_hash})
        _write_json(
            Path(kwargs["output_path"]),
            {"artifact_hash": revision.artifact_hash, "generation_calls": 1},
        )
        return revision

    def materializer(**kwargs: Any) -> ContestDirectPlanArtifacts:
        calls.append("materialize")
        payload = kwargs["payload"]
        assert len(payload["embedded_evidence"]["tables"]) == 1
        assert kwargs["evidence_bindings"]
        assert payload["preexperiment"]["formal_experiment_executed"] is False
        assert payload["generation"]["generation_calls"] == 1
        root = Path(kwargs["output_dir"])
        root.mkdir(parents=True)
        json_path = root / "research-plan.json"
        markdown_path = root / "research-plan.md"
        tex_path = root / "research-plan.tex"
        pdf_path = root / "research-plan.pdf"
        manifest_path = root / "research-plan-manifest.json"
        _write_json(json_path, payload)
        markdown_path.write_text("# 真实预实验反馈后的研究计划\n", encoding="utf-8")
        tex_path.write_text("\\documentclass{article}\n", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4\nfeedback plan\n%%EOF\n")
        _write_json(manifest_path, {"compile_status": "compiled"})
        return ContestDirectPlanArtifacts(
            output_dir=root,
            json_path=json_path,
            markdown_path=markdown_path,
            tex_path=tex_path,
            pdf_path=pdf_path,
            manifest_path=manifest_path,
            source_payload_sha256=canonical_model_hash(payload),
            page_count=4,
            pdf_text_verified=True,
        )

    return {
        "preexperiment_runner": runner,
        "preexperiment_loader": loader,
        "revision_runner": revision_runner,
        "plan_materializer": materializer,
    }


def test_executes_pilot_then_revises_once_and_materializes_all_views(
    tmp_path: Path,
) -> None:
    source, _rendered_source, _skill = _source_delivery(tmp_path)
    output = tmp_path / "new-delivery"
    calls: list[str] = []
    holder: dict[str, Any] = {}

    report = run_contest_prime_feedback_delivery(
        source_delivery_dir=source,
        output_dir=output,
        **_dependencies(calls, holder),
    )

    assert calls == ["run-preexperiment", "load-preexperiment", "revise", "materialize"]
    assert report["preexperiment_executed"] is True
    assert report["preexperiment_executed_in_this_delivery"] is True
    assert report["preexperiment"]["execution_mode"] == "executed_in_this_delivery"
    assert report["plan_revision_model_calls"] == 1
    assert report["formal_experiment_executed"] is False
    assert report["paper_claimed"] is False
    assert Path(report["rendered"]["pdf_path"]).is_file()
    persisted = json.loads((output / "delivery-report.json").read_text(encoding="utf-8"))
    assert persisted["rendered"]["artifacts"]["pdf"]["sha256"] == _sha256(
        output / "plan" / "research-plan.pdf"
    )
    rendered_json = json.loads((output / "plan" / "research-plan.json").read_text(encoding="utf-8"))
    assert rendered_json["preexperiment"]["run_id"] == holder["pilot"].run_id


def test_reuses_fully_verified_pilot_without_calling_runner(tmp_path: Path) -> None:
    source, rendered_source, _skill = _source_delivery(tmp_path)
    prior_root = tmp_path / "prior-pilot"
    prior_pilot = _make_pilot(prior_root, source_plan_path=rendered_source)
    holder = {
        "pilot": prior_pilot,
        "path": prior_root / "prime-preexperiment.json",
    }
    calls: list[str] = []
    dependencies = _dependencies(calls, holder)

    def must_not_run(**_kwargs: Any) -> Any:
        raise AssertionError("runner must not execute when a verified artifact is supplied")

    dependencies["preexperiment_runner"] = must_not_run
    output = tmp_path / "reused-delivery"
    report = run_contest_prime_feedback_delivery(
        source_delivery_dir=source,
        output_dir=output,
        preexperiment_artifact=holder["path"],
        **dependencies,
    )

    assert calls == ["load-preexperiment", "revise", "materialize"]
    assert report["preexperiment_executed"] is True
    assert report["preexperiment_executed_in_this_delivery"] is False
    assert report["preexperiment"]["execution_mode"] == "reused_after_full_hash_verification"
    assert report["preexperiment"]["artifact"]["path"] == Path(holder["path"]).as_posix()


def test_tampered_selected_skill_stops_before_experiment(tmp_path: Path) -> None:
    source, _rendered_source, skill_path = _source_delivery(tmp_path)
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "篡改\n", encoding="utf-8")
    output = tmp_path / "must-not-exist"

    with pytest.raises(ContestPrimeFeedbackDeliveryError, match="content hash mismatch"):
        run_contest_prime_feedback_delivery(
            source_delivery_dir=source,
            output_dir=output,
            preexperiment_runner=lambda **_kwargs: pytest.fail("runner was called"),
        )

    assert not output.exists()


def test_rejects_nonempty_output_before_any_runner_call(tmp_path: Path) -> None:
    source, _rendered_source, _skill = _source_delivery(tmp_path)
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(ContestPrimeFeedbackDeliveryError, match="new or empty"):
        run_contest_prime_feedback_delivery(
            source_delivery_dir=source,
            output_dir=output,
            preexperiment_runner=lambda **_kwargs: pytest.fail("runner was called"),
        )

    assert (output / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_main_forwards_optional_preexperiment_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(feedback_cli, "run_contest_prime_feedback_delivery", fake_run)
    artifact = tmp_path / "prior" / "prime-preexperiment.json"
    assert (
        feedback_cli.main(
            [
                "--source-delivery-dir",
                str(tmp_path / "source"),
                "--output-dir",
                str(tmp_path / "output"),
                "--preexperiment-artifact",
                str(artifact),
                "--max-tokens",
                "4321",
            ]
        )
        == 0
    )

    assert captured["preexperiment_artifact"] == artifact
    assert captured["max_tokens"] == 4321
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
