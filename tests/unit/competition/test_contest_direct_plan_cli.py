from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    ContestDirectScientificPlan,
)
from autoresearch.competition.contest_direct_plan_cli import (
    default_question_one_reference_catalog,
    objective_literature_from_locked_catalog,
    plan_payload_for_render,
    run_contest_question_one_delivery,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
)
from autoresearch.competition.contest_question_input import ContestQuestionInput
from autoresearch.competition.manifest import canonical_model_hash


def _question() -> ContestQuestionInput:
    return ContestQuestionInput(
        question_id="science125-q001-0123456789abcdef",
        question_en="What makes prime numbers so special?",
        question_zh="素数为何如此特别？",
        discipline_en="Mathematical Sciences",
        discipline_zh="数学科学",
        source_title="125 Questions: Exploration and Discovery",
        pdf_page_number=7,
        printed_page_number=5,
        source_pdf_path="C:/input/sjtu-booklet.pdf",
        source_file_sha256="a" * 64,
        extracted_page_sha256="b" * 64,
        extraction_evidence=("栏目证据", "问题证据"),
    )


def _artifact() -> ContestDirectPlanArtifact:
    plan = ContestDirectScientificPlan(
        problem_statement="研究素数结构的可检验统计规律。",
        rationale="比较结构假设与随机模型。",
        technical_details="使用筛法和可复现统计检验。",
        datasets="确定性生成的素数与合数对照。",
        source="OEIS和程序生成序列。",
        target="素数间隔与结构统计量。",
        paper_title="素数结构的可证伪计算研究计划",
        paper_abstract="提出数据驱动的素数结构检验方案。",
        methods="预注册假设并执行统计比较。",
        experiments="生成数据，运行基线，比较结果。",
        baselines="随机奇数和半素数。",
        metrics="校准误差和效应量。",
        results="尚未执行实验，本节只给出判定规则。",
        references=("https://oeis.org/A000040",),
    )
    input_hash = "1" * 64
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-research-plan-v1",
        "document_type": "科学假设与研究计划",
        "plan_id": f"direct-plan-{input_hash[:16]}",
        "status": "research_plan_generated",
        "scientific_problem": "素数为何如此特别？",
        "literature_context_provided": True,
        "preexperiment_context_status": "not_provided",
        "plan": plan.model_dump(mode="json"),
        "provider": "test-provider",
        "model_name": "test-model",
        "generation_calls": 1,
        "json_repair_applied": False,
        "input_hash": input_hash,
        "model_response_hash": "2" * 64,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return ContestDirectPlanArtifact.model_validate(payload)


def test_render_projection_contains_every_contest_template_field() -> None:
    payload = plan_payload_for_render(_artifact(), question=_question())

    assert payload["title"] == "素数结构的可证伪计算研究计划"
    assert payload["datasets"]["source"] == "OEIS和程序生成序列。"
    assert payload["datasets"]["target"] == "素数间隔与结构统计量。"
    assert payload["baselines"] == "随机奇数和半素数。"
    assert payload["metrics"] == "校准误差和效应量。"
    assert payload["question"]["ordinal"] == 1
    assert payload["results"].startswith("尚未执行实验")


def test_reference_catalog_is_caller_owned_and_has_identifiable_urls() -> None:
    references = default_question_one_reference_catalog(_question())

    assert len(references) >= 5
    assert all("http" in item or "SHA-256" in item for item in references)
    assert any("AI-Scientist-v2" in item for item in references)
    assert any("A000040" in item for item in references)
    assert any("PhysRevLett.88.174102" in item for item in references)
    assert any("S0025579300016442" in item for item in references)
    assert any("03461238.1995.10413946" in item for item in references)
    assert any("PhysRevE.85.021906" in item for item in references)
    assert any("pnas.1605366113" in item for item in references)
    assert any("s00222-023-01199-0" in item for item in references)


def test_delivery_composes_one_generator_call_and_materializer(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    routing_calls: list[dict[str, Any]] = []
    objective_calls: list[dict[str, Any]] = []

    def extract(_: object) -> ContestQuestionInput:
        return _question()

    def generate(**kwargs: Any) -> ContestDirectPlanArtifact:
        calls.append(kwargs)
        Path(kwargs["output_path"]).write_text("{}\n", encoding="utf-8")
        return _artifact()

    def route(**kwargs: Any) -> Any:
        routing_calls.append(kwargs)
        skill = kwargs["skill_catalog"][0]
        Path(kwargs["output_path"]).write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            selected_skill_ids=(skill.skill_id,),
            selected_skill_hashes={skill.skill_id: skill.content_sha256},
            artifact_hash="c" * 64,
        )

    def run_objective(**kwargs: Any) -> Any:
        objective_calls.append(kwargs)
        kwargs["brainstorm_capability"].revoke()
        kwargs["review_capability"].revoke()
        return SimpleNamespace(
            artifact_relative_path="temporary-agents/research-objective-stage/test.json",
            artifact_hash="d" * 64,
            status="complete",
            candidate_count=3,
            model_call_count=4,
            review_model_call_count=1,
            all_runtime_identities_removed=True,
            plan_context_payload=lambda: {
                "上下文类型": "研究目标形成阶段的独立评审结果",
                "最终研究目标": "检验素数局部顺序是否包含随机基线不能解释的结构。",
            },
        )

    def materialize(**kwargs: Any) -> ContestDirectPlanArtifacts:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        paths = {
            name: output / f"research-plan.{suffix}"
            for name, suffix in (
                ("json", "json"),
                ("markdown", "md"),
                ("tex", "tex"),
                ("pdf", "pdf"),
            )
        }
        for path in paths.values():
            path.write_bytes(b"test")
        manifest = output / "research-plan-manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")
        return ContestDirectPlanArtifacts(
            output_dir=output,
            json_path=paths["json"],
            markdown_path=paths["markdown"],
            tex_path=paths["tex"],
            pdf_path=paths["pdf"],
            manifest_path=manifest,
            source_payload_sha256=hashlib.sha256(b"payload").hexdigest(),
            page_count=1,
            pdf_text_verified=True,
        )

    report = run_contest_question_one_delivery(
        question_pdf=tmp_path / "input.pdf",
        output_dir=tmp_path / "output",
        skills_root=_write_skills_root(tmp_path),
        question_extractor=extract,
        skill_router=route,
        objective_stage_runner=run_objective,
        plan_generator=generate,
        plan_materializer=materialize,
    )

    assert len(routing_calls) == 1
    assert "素数为何如此特别" in routing_calls[0]["question"]
    assert routing_calls[0]["skill_catalog"][0].skill_id == "prime-test"
    assert len(objective_calls) == 1
    assert objective_calls[0]["mode"] == "specified_question"
    assert len(objective_calls[0]["selected_skill_contexts"]) == 1
    assert objective_calls[0]["retrieved_literature_catalog"]
    assert objective_calls[0]["brainstorm_controller"].stage == ("research-objective-brainstorm")
    assert objective_calls[0]["review_controller"].stage == "research-objective-review"
    assert len(calls) == 1
    assert calls[0]["scientific_problem"].startswith("素数为何如此特别？")
    assert calls[0]["preexperiment_context"] is None
    assert calls[0]["method_skills"][0].startswith("---")
    assert "独立评审" in calls[0]["temporary_agent_context"]["上下文类型"]
    assert "最终研究目标" in calls[0]["temporary_agent_context"]
    assert report["status"] == "completed"
    assert report["model_calls"] == 6
    assert report["selected_method_skill_ids"] == ["prime-test"]
    assert report["research_objective_candidate_count"] == 3
    assert report["research_objective_review_model_calls"] == 1
    assert report["formal_experiment_executed"] is False
    persisted = json.loads(
        (tmp_path / "output" / "delivery-report.json").read_text(encoding="utf-8")
    )
    assert persisted["question_id"] == _question().question_id


def test_locked_reference_projection_only_admits_explicit_urls() -> None:
    catalog = objective_literature_from_locked_catalog(
        (
            "Paper A. https://example.org/a",
            "Local note without a network source",
            "Paper B. https://example.org/b; secondary text",
        ),
        retrieved_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    assert [item["url"] for item in catalog] == [
        "https://example.org/a",
        "https://example.org/b",
    ]
    assert all(item["retrieved_at"] == "2026-08-11T00:00:00Z" for item in catalog)


def _write_skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    skill = root / "prime-test" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: prime-test\ndescription: test\n---\n只提供研究方法。\n",
        encoding="utf-8",
    )
    return root
