from __future__ import annotations

import hashlib
import inspect
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoresearch.competition.contest_direction_plan_cli as direction_cli
from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    ContestDirectScientificPlan,
    build_contest_direct_plan_messages,
)
from autoresearch.competition.contest_direct_plan_render import ContestDirectPlanArtifacts
from autoresearch.competition.contest_direct_skill_router import (
    build_contest_direct_skill_routing_messages,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureError,
)
from autoresearch.competition.contest_direction_plan_cli import (
    ContestDirectionPlanDeliveryError,
    run_contest_direction_plan_delivery,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.literature.models import AcademicPaper

_DIRECTION = "面向低资源环境的可解释时间序列异常检测"
_RETRIEVED_AT = "2026-08-12T00:00:00+00:00"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    path = root / "time-series-method" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: time-series-method\n"
        "description: 面向时间序列研究的可证伪方法与对照设计。\n"
        "---\n"
        "使用时间切分、强基线、消融和失败判据形成研究路径。\n",
        encoding="utf-8",
    )
    return root


class _Fetch:
    def __init__(self, *, status: str, source: str, error: str | None = None) -> None:
        self.status = status
        self.source = source
        self.error = error

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "status": self.status,
            "source": self.source,
            "error": self.error,
            "retrieved_at": _RETRIEVED_AT,
        }


class _Literature:
    artifact_hash = "4" * 64
    query_model_calls = 1
    retriever_sources = ("arxiv", "openalex")
    queries = ("interpretable time series anomaly detection low resource",)
    fetches = (
        _Fetch(status="succeeded", source="arxiv"),
        _Fetch(status="failed", source="openalex", error="temporary source error"),
    )
    raw_hit_count = 6
    retrieved_records = tuple(
        SimpleNamespace(record_id=f"direction-paper-{index:016d}") for index in range(1, 7)
    )

    def objective_retrieval_catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "record_id": f"direction-paper-{index:016d}",
                "title": f"Interpretable Time-Series Anomaly Detection Study {index}",
                "authors": [f"Researcher {index}"],
                "abstract": (
                    "A real retrieved abstract about interpretable time series anomaly "
                    f"detection methods, low-resource evaluation, and limitation {index}."
                ),
                "doi": f"10.1000/real.{index}",
                "url": f"https://doi.org/10.1000/real.{index}",
                "source_url": f"https://doi.org/10.1000/real.{index}",
                "retrieved_from": "arxiv" if index % 2 else "openalex",
                "retrieved_at": _RETRIEVED_AT,
                "paper_source": "arxiv" if index % 2 else "openalex",
                "record_sha256": str(index) * 64,
            }
            for index in range(1, 6)
        )

    def objective_literature_catalog(self) -> tuple[str, ...]:
        eligible = tuple(
            "\n".join(
                (
                    f"[{index}] record_id=direction-paper-{index:016d}",
                    f"题名：Interpretable Time-Series Anomaly Detection Study {index}",
                    f"DOI：10.1000/real.{index}",
                    f"URL：https://doi.org/10.1000/real.{index}",
                    "完整摘要：A real retrieved abstract about interpretable time series "
                    f"anomaly detection methods, low-resource evaluation, and limitation {index}.",
                    f"真实检索谱系：arxiv|query|{_RETRIEVED_AT}",
                )
            )
            for index in range(1, 6)
        )
        return (
            *eligible,
            "\n".join(
                (
                    "[6] record_id=direction-paper-0000000000000006",
                    "题名：Incomplete Search Record",
                    "URL：未提供",
                    "完整摘要：摘要未提供",
                    f"真实检索谱系：arxiv|query|{_RETRIEVED_AT}",
                )
            ),
        )


class _Objective:
    artifact_hash = "5" * 64
    artifact_relative_path = "temporary-agents/research-objective-stage/objective.json"
    status = "degraded"
    model_call_count = 4
    review_model_call_count = 1
    all_runtime_identities_removed = True
    outputs_and_receipts_retained = True
    content_is_scientific_evidence = False
    candidate_count = 2

    def plan_context_payload(self) -> dict[str, Any]:
        return {
            "上下文类型": "研究目标形成阶段的独立评审结果",
            "最终研究目标": "检验低资源约束下解释性与检测性能的可区分权衡。",
            "核心假设": "稀疏解释约束仅在分布漂移条件下改善稳定性。",
            "采用的真实文献": [
                {
                    "目录编号": 1,
                    "题名": "Interpretable Time-Series Anomaly Detection",
                    "来源链接": "https://doi.org/10.1000/real.1",
                    "检索来源": "arxiv",
                    "检索时间": _RETRIEVED_AT,
                }
            ],
        }


def _plan_artifact(*, references: tuple[str, ...]) -> ContestDirectPlanArtifact:
    scientific_plan = ContestDirectScientificPlan(
        problem_statement="当前方向缺少在低资源和分布漂移条件下的可区分证据。",
        rationale="通过竞争解释和强基线检验解释约束是否带来独立收益。",
        technical_details="采用冻结时间切分、资源预算和可复现实验配置。",
        datasets="使用来源真实且许可清晰的公开时间序列数据。",
        source="公开数据原始时间序列及其来源元数据。",
        target="冻结切分后的异常标签、预测分数和解释稳定性指标。",
        paper_title="低资源时间序列异常检测的解释稳定性研究计划",
        paper_abstract="本研究计划将检验解释约束在分布漂移条件下的稳定性。",
        methods="比较无解释约束、稀疏约束和匹配参数量对照。",
        experiments="按冻结时间切分运行基线、候选方法、消融和失败分析。",
        baselines="无解释约束模型、简单统计检测器和参数量匹配模型。",
        metrics="检测性能、解释稳定性、运行时间和内存占用。",
        results="尚未执行预实验；将按支持、反驳或无法区分三类判据解释。",
        references=references,
    )
    input_hash = "6" * 64
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-research-plan-v1",
        "document_type": "科学假设与研究计划",
        "plan_id": f"direct-plan-{input_hash[:16]}",
        "status": "research_plan_generated",
        "scientific_problem": _DIRECTION,
        "literature_context_provided": True,
        "preexperiment_context_status": "not_provided",
        "plan": scientific_plan.model_dump(mode="json"),
        "provider": "test-provider",
        "model_name": "test-model",
        "generation_calls": 1,
        "json_repair_applied": False,
        "input_hash": input_hash,
        "model_response_hash": "7" * 64,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return ContestDirectPlanArtifact.model_validate(payload)


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[str],
    plan_reference: str | None = None,
    renderer_page_count: int | None = None,
) -> None:
    def route(**kwargs: Any) -> Any:
        calls.append("route")
        assert kwargs["question"] == _DIRECTION
        catalog = kwargs["skill_catalog"]
        assert catalog and not hasattr(catalog[0], "content")
        messages = build_contest_direct_skill_routing_messages(
            question=kwargs["question"],
            requirements=kwargs["requirements"],
            skill_catalog=catalog,
        )
        assert [item["role"] for item in messages] == ["system", "user", "user"]
        assert (
            json.loads(messages[1]["content"])["context_kind"]
            == "research_question_and_delivery_requirements"
        )
        assert (
            json.loads(messages[2]["content"])["context_kind"]
            == "available_method_skill_catalog_metadata"
        )
        artifact_hash = "3" * 64
        output_path = Path(kwargs["output_path"])
        _write_json(output_path, {"artifact_hash": artifact_hash})
        return SimpleNamespace(
            selected_skill_ids=(catalog[0].skill_id,),
            selected_skill_hashes={catalog[0].skill_id: catalog[0].content_sha256},
            artifact_hash=artifact_hash,
            model_calls=1,
        )

    def retrieve(**kwargs: Any) -> _Literature:
        calls.append("retrieve")
        assert kwargs["direction"] == _DIRECTION
        assert kwargs["searchers"] is None
        assert "retrieved_at" not in kwargs
        assert list(kwargs["selected_method_skills"]) == ["time-series-method"]
        _write_json(Path(kwargs["output_path"]), {"artifact_hash": _Literature.artifact_hash})
        return _Literature()

    def objective(**kwargs: Any) -> _Objective:
        calls.append("objective")
        assert kwargs["mode"] == "specified_direction"
        assert kwargs["seed_text"] == _DIRECTION
        assert kwargs["brainstorm_controller"].binding_hash != (
            kwargs["review_controller"].binding_hash
        )
        assert kwargs["brainstorm_capability"].active
        assert kwargs["review_capability"].active
        assert kwargs["selected_skill_contexts"][0].content.startswith("---\n")
        catalog = kwargs["retrieved_literature_catalog"]
        assert len(catalog) == 5
        assert catalog[0]["abstract"]
        assert catalog[0]["retrieved_from"] == "arxiv"
        assert catalog[0]["retrieved_at"] == _RETRIEVED_AT
        assert catalog[0]["source_url"].startswith("https://")
        kwargs["brainstorm_capability"].revoke()
        kwargs["review_capability"].revoke()
        artifact = _Objective()
        path = Path(kwargs["output_dir"]) / Path(*Path(artifact.artifact_relative_path).parts)
        _write_json(path, {"artifact_hash": artifact.artifact_hash})
        return artifact

    def generate(**kwargs: Any) -> ContestDirectPlanArtifact:
        calls.append("plan")
        assert kwargs["scientific_problem"] == _DIRECTION
        assert kwargs["preexperiment_context"] is None
        assert kwargs["method_skills"][0].startswith("---\n")
        messages = build_contest_direct_plan_messages(
            scientific_problem=kwargs["scientific_problem"],
            literature_context=kwargs["literature_context"],
            method_skills=kwargs["method_skills"],
            temporary_agent_context=kwargs["temporary_agent_context"],
        )
        assert [item["role"] for item in messages] == [
            "system",
            "user",
            "user",
            "user",
            "user",
        ]
        assert "system_selected_project_method_skills" in messages[2]["content"]
        assert "archived_temporary_agent_advice" in messages[3]["content"]
        references = tuple(kwargs["literature_context"][:5])
        if plan_reference is not None:
            references = (plan_reference, *references[1:])
        artifact = _plan_artifact(references=references)
        _write_json(Path(kwargs["output_path"]), artifact.model_dump(mode="json"))
        return artifact

    def materialize(**kwargs: Any) -> ContestDirectPlanArtifacts:
        calls.append("materialize")
        payload = kwargs["payload"]
        assert payload["literature_provenance"]["eligible_record_count"] == 5
        assert payload["research_objective"]["temporary_runtime_identities_removed"] is True
        root = Path(kwargs["output_dir"])
        root.mkdir(parents=True)
        json_path = root / "research-plan.json"
        markdown_path = root / "research-plan.md"
        tex_path = root / "research-plan.tex"
        pdf_path = root / "research-plan.pdf"
        manifest_path = root / "research-plan-manifest.json"
        _write_json(json_path, payload)
        markdown_path.write_text("# 方向研究计划\n", encoding="utf-8")
        tex_path.write_text("\\documentclass{article}\n", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4\nmock direction plan\n%%EOF\n")
        _write_json(manifest_path, {"compile_status": "compiled"})
        return ContestDirectPlanArtifacts(
            output_dir=root,
            json_path=json_path,
            markdown_path=markdown_path,
            tex_path=tex_path,
            pdf_path=pdf_path,
            manifest_path=manifest_path,
            source_payload_sha256=canonical_model_hash(payload),
            page_count=renderer_page_count,
            pdf_text_verified=True,
        )

    monkeypatch.setattr(direction_cli, "route_contest_direct_plan_skills", route)
    monkeypatch.setattr(direction_cli, "retrieve_contest_direction_literature", retrieve)
    monkeypatch.setattr(direction_cli, "run_contest_research_objective_stage", objective)
    monkeypatch.setattr(direction_cli, "generate_contest_direct_plan", generate)
    monkeypatch.setattr(direction_cli, "materialize_contest_direct_plan", materialize)


def test_mock_end_to_end_preserves_order_provenance_and_partial_source_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls=calls, renderer_page_count=None)
    monkeypatch.setattr(
        direction_cli,
        "_independent_pdf_page_count",
        lambda _path: (6, "pypdf-test"),
    )
    output = tmp_path / "delivery"

    report = run_contest_direction_plan_delivery(
        direction=_DIRECTION,
        output_dir=output,
        skills_root=_skills_root(tmp_path),
    )

    assert calls == ["route", "retrieve", "objective", "plan", "materialize"]
    assert report["status"] == "completed"
    assert report["literature"]["failed_fetch_count"] == 1
    assert report["literature"]["eligible_record_count"] == 5
    assert report["literature"]["excluded_records"] == [
        {
            "record_id": "direction-paper-0000000000000006",
            "reason": "missing_url_or_doi",
        }
    ]
    assert report["literature"]["projection_timestamp_invented"] is False
    assert report["research_objective"]["temporary_runtime_identities_removed"] is True
    assert report["plan"]["references_from_real_retrieval_only"] is True
    assert report["pdf"] == {
        "path": (output / "plan" / "research-plan.pdf").as_posix(),
        "readable_text_verified": True,
        "verified_page_count": 6,
        "page_count_method": "pypdf-test",
        "maximum_allowed_pages": 20,
    }
    assert report["independent_scientific_review"]["insertion_point_ready"] is True
    assert report["independent_scientific_review"]["must_not_delete_or_rewrite_plan"] is True
    assert report["file_inventory"]
    assert all("sha256" in item for item in report["file_inventory"])
    persisted = json.loads((output / "delivery-report.json").read_text(encoding="utf-8"))
    assert persisted["file_inventory_hash"] == canonical_model_hash(
        {"files": persisted["file_inventory"]}
    )


def test_zero_real_results_writes_failure_receipt_without_static_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls=calls)
    fetches = (
        _Fetch(status="succeeded", source="arxiv"),
        _Fetch(status="failed", source="openalex", error="network"),
    )

    def no_results(**_kwargs: Any) -> Any:
        calls.append("retrieve-zero")
        raise ContestDirectionLiteratureError("all searches returned no papers", fetches=fetches)

    monkeypatch.setattr(direction_cli, "retrieve_contest_direction_literature", no_results)
    output = tmp_path / "zero"

    with pytest.raises(ContestDirectionPlanDeliveryError, match="no usable paper"):
        run_contest_direction_plan_delivery(
            direction=_DIRECTION,
            output_dir=output,
            skills_root=_skills_root(tmp_path),
        )

    assert calls == ["route", "retrieve-zero"]
    failure_path = output / "direction-literature-failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    expected_hash = canonical_model_hash(
        {key: value for key, value in failure.items() if key != "failure_hash"}
    )
    assert failure["failure_hash"] == expected_hash
    assert failure["static_catalog_fallback_used"] is False
    assert len(failure["fetches"]) == 2
    assert not (output / "delivery-report.json").exists()


def test_plan_reference_outside_retrieval_catalog_fails_without_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_pipeline(
        monkeypatch,
        calls=calls,
        plan_reference="Invented paper https://example.invalid/fake",
    )
    output = tmp_path / "bad-reference"

    with pytest.raises(ContestDirectionPlanDeliveryError, match="outside"):
        run_contest_direction_plan_delivery(
            direction=_DIRECTION,
            output_dir=output,
            skills_root=_skills_root(tmp_path),
        )

    assert calls == ["route", "retrieve", "objective", "plan"]
    assert not (output / "plan").exists()
    assert not (output / "delivery-report.json").exists()


def test_page_count_fallback_rejects_more_than_twenty_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls=calls, renderer_page_count=None)
    monkeypatch.setattr(
        direction_cli,
        "_independent_pdf_page_count",
        lambda _path: (21, "pdfinfo-test"),
    )
    output = tmp_path / "too-long"

    with pytest.raises(ContestDirectionPlanDeliveryError, match="maximum is 20"):
        run_contest_direction_plan_delivery(
            direction=_DIRECTION,
            output_dir=output,
            skills_root=_skills_root(tmp_path),
        )

    assert calls[-1] == "materialize"
    assert not (output / "delivery-report.json").exists()


def test_independent_page_count_prefers_real_exe_over_windows_cmd_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "plan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    discovered: list[str] = []

    def which(name: str) -> str | None:
        discovered.append(name)
        if name == "pdfinfo.exe":
            return r"C:\texlive\2026\bin\windows\pdfinfo.exe"
        return r"C:\broken\override\pdfinfo.CMD"

    def run(command: list[str], **kwargs: Any) -> Any:
        assert command[0].endswith("pdfinfo.exe")
        assert kwargs["check"] is True
        return SimpleNamespace(stdout="Title: plan\nPages:          6\n")

    monkeypatch.setattr(direction_cli.shutil, "which", which)
    monkeypatch.setattr(direction_cli.subprocess, "run", run)

    assert direction_cli._independent_pdf_page_count(pdf_path) == (6, "pdfinfo")
    assert discovered == ["pdfinfo.exe"]


def test_format_failure_is_not_retried_or_reported_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls=calls)
    plan_calls = 0

    def invalid_plan(**_kwargs: Any) -> Any:
        nonlocal plan_calls
        plan_calls += 1
        raise ValueError("one-shot plan schema failure")

    monkeypatch.setattr(direction_cli, "generate_contest_direct_plan", invalid_plan)
    output = tmp_path / "format-failure"

    with pytest.raises(ValueError, match="schema failure"):
        run_contest_direction_plan_delivery(
            direction=_DIRECTION,
            output_dir=output,
            skills_root=_skills_root(tmp_path),
        )

    assert plan_calls == 1
    assert calls == ["route", "retrieve", "objective"]
    assert not (output / "delivery-report.json").exists()


def test_production_signature_and_cli_do_not_expose_searchers_or_retrieved_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parameters = inspect.signature(run_contest_direction_plan_delivery).parameters
    assert "searchers" not in parameters
    assert "retrieved_at" not in parameters
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(direction_cli, "run_contest_direction_plan_delivery", fake_run)
    assert (
        direction_cli.main(
            [
                "--direction",
                _DIRECTION,
                "--output-dir",
                str(tmp_path / "cli"),
                "--max-results-per-search",
                "3",
            ]
        )
        == 0
    )
    assert captured["direction"] == _DIRECTION
    assert captured["max_results_per_search"] == 3
    assert "searchers" not in captured
    assert "retrieved_at" not in captured
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_large_real_catalog_is_ranked_and_projected_without_truncating_records() -> None:
    relevant = {
        "record_id": "direction-paper-relevant",
        "title": "Prime gaps and arithmetic residue constraints",
        "abstract": "Prime gaps exhibit residue bias and finite-scale sequential structure.",
        "source_url": "https://arxiv.org/abs/1",
        "retrieved_from": "arxiv",
        "retrieved_at": _RETRIEVED_AT,
    }
    noise = [
        {
            "record_id": f"direction-paper-noise-{index:02d}",
            "title": f"Unrelated application study {index}",
            "abstract": "A broad application paper. " + ("x" * 1_200),
            "source_url": f"https://example.org/{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
        }
        for index in range(30)
    ]
    catalog = tuple(noise[:15] + [relevant] + noise[15:])
    contexts = tuple(json.dumps(item, ensure_ascii=False) for item in catalog)

    selected, selected_contexts = direction_cli._select_planning_literature(
        catalog,
        contexts,
        queries=("prime gaps arithmetic residue sequential structure",),
    )

    assert selected[0]["record_id"] == "direction-paper-relevant"
    assert len(selected) < len(catalog)
    assert selected_contexts[0] == contexts[15]
    assert relevant["abstract"] == selected[0]["abstract"]
    assert (
        sum(
            len(json.dumps(item, ensure_ascii=False, sort_keys=True)) + len(context)
            for item, context in zip(selected, selected_contexts, strict=True)
        )
        <= direction_cli._MAX_PLANNING_LITERATURE_CHARACTERS
    )


def test_soft_quality_ranking_excludes_off_topic_citation_noise_without_citation_gate() -> None:
    relevant_uncited = {
        "record_id": "direction-paper-relevant",
        "title": "Prime gaps arithmetic residue structure",
        "abstract": "Local prime gap structure and arithmetic residue mechanisms.",
        "source_url": "https://arxiv.org/abs/relevant",
        "retrieved_from": "arxiv",
        "retrieved_at": _RETRIEVED_AT,
        "publication_date": "2026-01-01",
        "publication_status": "preprint",
        "citation_count": 0,
        "citation_count_source": "openalex",
        "citation_count_as_of": "2026-08-12",
    }
    highly_cited_noise = {
        "record_id": "direction-paper-noise",
        "title": "Highly cited unrelated clinical intervention",
        "abstract": "Clinical intervention outcomes unrelated to number theory.",
        "source_url": "https://doi.org/10.1000/noise",
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_date": "2000-01-01",
        "publication_status": "published",
        "citation_count": 100_000,
        "citation_count_source": "openalex",
        "citation_count_as_of": "2026-08-12",
        "publication_doi": "10.1000/noise",
        "venue": "Famous Journal",
    }
    catalog = (highly_cited_noise, relevant_uncited)
    contexts = tuple(json.dumps(item, ensure_ascii=False) for item in catalog)

    selected, _contexts = direction_cli._select_planning_literature(
        catalog,
        contexts,
        queries=("prime gaps arithmetic residue local structure",),
    )

    assert selected[0]["record_id"] == "direction-paper-relevant"
    assert [item["record_id"] for item in selected] == ["direction-paper-relevant"]
    assert selected[0]["citation_count"] == 0


def test_q1_like_catalog_yields_bounded_relevant_diverse_planning_bibliography() -> None:
    topics = (
        ("Prime gaps and arithmetic residue constraints", "prime gaps residue patterns", 180),
        ("The distribution of prime numbers", "prime number distribution theory", 900),
        ("Unexpected irregularities in prime numbers", "irregular prime gaps", 49),
        ("Computing prime gaps to large bounds", "empirical prime gap verification", 170),
        ("Prime counting and the Riemann zeta function", "prime density asymptotics", 400),
        (
            "Hardy-Littlewood patterns among prime numbers",
            "prime numbers, tuples, and density patterns",
            None,
        ),
        ("Permutation entropy for discrete sequences", "ordinal entropy methods", 300),
        ("Computational number theory methods", "algorithms for prime numbers", 800),
    )
    relevant = tuple(
        {
            "record_id": f"direction-paper-q1-{index}",
            "title": title,
            "abstract": abstract,
            "source_url": f"https://doi.org/10.1000/q1.{index}",
            "retrieved_from": "openalex" if index % 2 else "arxiv",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": f"10.1000/q1.{index}",
            "citation_count": citations,
            "citation_count_source": "openalex" if citations is not None else None,
            "citation_count_as_of": _RETRIEVED_AT[:10] if citations is not None else None,
        }
        for index, (title, abstract, citations) in enumerate(topics, 1)
    )
    off_topic = {
        "record_id": "direction-paper-t-cell-prime",
        "title": "Signals insufficient to prime resting T lymphocytes",
        "abstract": "T cell receptor zeta activation in tumors.",
        "source_url": "https://doi.org/10.1000/tcell",
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "published",
        "publication_doi": "10.1000/tcell",
        "citation_count": 20_000,
        "citation_count_source": "openalex",
        "citation_count_as_of": _RETRIEVED_AT[:10],
    }
    catalog = (*relevant, off_topic)
    contexts = tuple(json.dumps(item, ensure_ascii=False) for item in catalog)

    selected, selected_contexts = direction_cli._select_planning_literature(
        catalog,
        contexts,
        queries=(
            "prime numbers distribution prime gaps arithmetic residue",
            "prime counting Riemann zeta density",
            "prime sequence entropy computational number theory",
        ),
        minimum_records=5,
        maximum_records=10,
    )

    assert 5 <= len(selected) <= 10
    assert len(selected) == len(selected_contexts)
    assert off_topic["record_id"] not in {item["record_id"] for item in selected}
    assert any(item["citation_count"] is None for item in selected)
    assert all(item["publication_doi"] for item in selected)


def test_zenodo_exact_metadata_family_spends_one_slot_without_merging_doi_identity() -> None:
    def zenodo(record_id: str, doi: str, *, abstract: str) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "record_sha256": ("a" if record_id.endswith("a") else "b") * 64,
            "title": "Prime Signature Diffusion",
            "authors": ["Shutong Hou"],
            "abstract": abstract,
            "venue": "Zenodo",
            "publication_date": "2026-05-31",
            "source_url": f"https://doi.org/{doi}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": doi,
        }

    shared_abstract = (
        "Prime signature metric evidence for consecutive prime gaps and permutation entropy."
    )
    family = (
        zenodo("zenodo-a", "10.5281/zenodo.20206120", abstract=shared_abstract),
        zenodo("zenodo-b", "10.5281/zenodo.20472925", abstract=shared_abstract),
    )
    complements = tuple(
        {
            "record_id": f"method-{index}",
            "title": f"Prime gap entropy null method {index}",
            "authors": [f"Author {index}"],
            "abstract": (
                "Prime gap permutation entropy null model evidence with independent method "
                f"family {index}."
            ),
            "source_url": f"https://doi.org/10.1000/method.{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": f"10.1000/method.{index}",
        }
        for index in range(1, 6)
    )
    catalog = (*family, *complements)
    selected, _contexts = direction_cli._select_planning_literature(
        catalog,
        tuple(json.dumps(item, ensure_ascii=False) for item in catalog),
        queries=("prime gap signature permutation entropy null model",),
        priority_queries=("prime signature gap", "permutation entropy prime gaps"),
        priority_query_groups=(("prime signature gap",), ("permutation entropy prime gaps",)),
        minimum_records=5,
        maximum_records=7,
    )

    zenodo_selected = [
        item for item in selected if str(item.get("publication_doi")).startswith("10.5281/zenodo")
    ]
    assert len(selected) == 6
    assert len(zenodo_selected) == 1
    suppressions = direction_cli._planning_work_family_suppressions(catalog, selected)
    assert len(suppressions) == 1
    assert suppressions[0]["identity_merged"] is False
    assert suppressions[0]["registered_relation_verified"] is False
    assert {
        suppressions[0]["suppressed_publication_doi"],
        suppressions[0]["representative_publication_doi"],
    } == {"10.5281/zenodo.20206120", "10.5281/zenodo.20472925"}

    changed = (
        family[0],
        zenodo(
            "zenodo-b",
            "10.5281/zenodo.20472925",
            abstract=shared_abstract + " Independent validation with a changed observable.",
        ),
        *complements,
    )
    changed_selected, _ = direction_cli._select_planning_literature(
        changed,
        tuple(json.dumps(item, ensure_ascii=False) for item in changed),
        queries=("prime gap signature permutation entropy null model",),
        priority_queries=("prime signature gap", "permutation entropy prime gaps"),
        priority_query_groups=(("prime signature gap",), ("permutation entropy prime gaps",)),
        minimum_records=5,
        maximum_records=7,
    )
    assert len(changed_selected) == 7
    assert not direction_cli._planning_work_family_suppressions(changed, changed_selected)


def test_nearest_method_bridge_beats_separate_subject_and_method_citation_noise() -> None:
    direct = {
        "record_id": "lucas-lacasa-prime-dynamics",
        "title": "On a dynamical approach to some prime number sequences",
        "authors": ["Lucas Lacasa", "Bartolo Luque"],
        "abstract": (
            "Symbolic dynamics reveals Renyi entropy and forbidden block patterns in prime "
            "gap residues, compared with appropriate null models."
        ),
        "source_url": "https://arxiv.org/abs/1802.08349",
        "retrieved_from": "arxiv",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "preprint",
        "publication_doi": "10.3390/e20020131",
        "repository_doi": "10.48550/arxiv.1802.08349",
        "citation_count": 0,
        "citation_count_source": "openalex",
        "citation_count_as_of": _RETRIEVED_AT[:10],
    }
    subject_only = tuple(
        {
            "record_id": f"cramer-{index}",
            "title": f"Cramer model for maximal prime gaps {index}",
            "authors": [f"Number Theorist {index}"],
            "abstract": "Prime gap asymptotics and probabilistic model foundations.",
            "source_url": f"https://doi.org/10.1000/cramer.{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": f"10.1000/cramer.{index}",
            "citation_count": 10_000 - index,
            "citation_count_source": "openalex",
            "citation_count_as_of": _RETRIEVED_AT[:10],
        }
        for index in range(1, 7)
    )
    method_only = tuple(
        {
            "record_id": f"eeg-entropy-{index}",
            "title": f"Permutation entropy for EEG time series {index}",
            "authors": [f"Signal Analyst {index}"],
            "abstract": "Ordinal patterns and surrogate null models for biomedical time series.",
            "source_url": f"https://doi.org/10.1000/eeg.{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": f"10.1000/eeg.{index}",
            "citation_count": 20_000 - index,
            "citation_count_source": "openalex",
            "citation_count_as_of": _RETRIEVED_AT[:10],
        }
        for index in range(1, 7)
    )
    catalog = (*subject_only, *method_only, direct)
    selected, _ = direction_cli._select_planning_literature(
        catalog,
        tuple(json.dumps(item, ensure_ascii=False) for item in catalog),
        queries=(
            "prime gap symbolic dynamics permutation entropy null model",
            "Cramer model prime gap foundations",
        ),
        priority_queries=("prime gap residue structure", "entropy null model prime gaps"),
        priority_query_groups=(
            ("prime gap residue structure",),
            ("entropy null model prime gaps", "symbolic dynamics prime gap"),
        ),
        minimum_records=5,
        maximum_records=5,
    )

    assert direct["record_id"] in {item["record_id"] for item in selected}


def test_budget_identity_suppresses_exact_title_author_abstract_mirrors() -> None:
    shared = {
        "title": "Phase stability in lumen arrays",
        "authors": ["A. Researcher", "B. Researcher"],
        "abstract": "A controlled study of phase stability under repeated measurements.",
    }
    first = {
        **shared,
        "record_id": "mirror-a",
        "venue": "Proceedings collection",
        "publication_date": "2024-01-01",
    }
    second = {
        **shared,
        "record_id": "mirror-b",
        "venue": "Repository mirror",
        "publication_date": "2025-02-02",
    }
    changed = {
        **second,
        "abstract": shared["abstract"] + " An independent intervention is added.",
    }

    assert direction_cli._planning_budget_identity(first) == (
        direction_cli._planning_budget_identity(second)
    )
    assert direction_cli._planning_budget_identity(first) != (
        direction_cli._planning_budget_identity(changed)
    )


def test_authorless_review_with_table_of_contents_is_softly_downranked() -> None:
    focused = tuple(
        {
            "record_id": f"direction-paper-focused-{index}",
            "title": f"Prime gap arithmetic distribution study {index}",
            "authors": [f"Author {index}"],
            "abstract": "Prime gap arithmetic distribution evidence and computational method.",
            "source_url": f"https://doi.org/10.1000/focused.{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
            "publication_status": "published",
            "publication_doi": f"10.1000/focused.{index}",
            "citation_count": 20,
            "citation_count_source": "openalex",
            "citation_count_as_of": _RETRIEVED_AT[:10],
        }
        for index in range(1, 11)
    )
    toc_review = {
        "record_id": "direction-paper-choice-review",
        "title": "Introduction to number theory and prime distribution",
        "authors": [],
        "abstract": " ".join(
            f"{chapter}.{section} Prime numbers and arithmetic distribution."
            for chapter in range(1, 5)
            for section in range(1, 6)
        )
        + (" background" * 300),
        "source_url": "https://doi.org/10.5860/choice.example",
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "published",
        "publication_doi": "10.5860/choice.example",
        "venue": "Choice Reviews Online",
        "citation_count": 10_000,
        "citation_count_source": "openalex",
        "citation_count_as_of": _RETRIEVED_AT[:10],
    }
    catalog = (toc_review, *focused)

    selected, _contexts = direction_cli._select_planning_literature(
        catalog,
        tuple(json.dumps(item, ensure_ascii=False) for item in catalog),
        queries=("prime gaps arithmetic distribution",),
        minimum_records=5,
        maximum_records=10,
    )

    assert toc_review["record_id"] not in {item["record_id"] for item in selected}


def test_final_reference_gate_rejects_duplicate_padding() -> None:
    catalog = tuple(f"真实检索文献{index}" for index in range(1, 6))
    artifact = SimpleNamespace(plan=SimpleNamespace(references=(catalog[0],) * 5))

    with pytest.raises(ContestDirectionPlanDeliveryError, match="duplicate"):
        direction_cli._verify_plan_references(
            artifact,
            literature_context=catalog,
            minimum_references=5,
            maximum_references=10,
        )


def test_oversized_highest_ranked_record_is_skipped_and_short_record_backfills() -> None:
    oversized = {
        "record_id": "direction-paper-oversized",
        "title": "Prime gaps arithmetic residue mechanism",
        "abstract": "Prime gaps arithmetic residue mechanism evidence.",
        "source_url": "https://example.org/oversized",
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
    }
    short = {
        "record_id": "direction-paper-short",
        "title": "Prime gaps computational study",
        "abstract": "A bounded computational study of prime gaps.",
        "source_url": "https://example.org/short",
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
    }
    contexts = (
        json.dumps(oversized, ensure_ascii=False) + ("完整但超出预算的原始文献内容" * 10_000),
        json.dumps(short, ensure_ascii=False),
    )

    selected, selected_contexts = direction_cli._select_planning_literature(
        (oversized, short),
        contexts,
        queries=("prime gaps arithmetic residue mechanism",),
    )

    assert [item["record_id"] for item in selected] == ["direction-paper-short"]
    assert selected_contexts == (contexts[1],)
    assert contexts[0].endswith("原始文献内容")


def test_all_complete_records_over_budget_fail_without_truncation() -> None:
    catalog = tuple(
        {
            "record_id": f"direction-paper-oversized-{index}",
            "title": f"Prime gaps mechanism {index}",
            "abstract": "Prime gaps mechanism evidence.",
            "source_url": f"https://example.org/oversized-{index}",
            "retrieved_from": "openalex",
            "retrieved_at": _RETRIEVED_AT,
        }
        for index in range(2)
    )
    contexts = tuple(
        json.dumps(item, ensure_ascii=False) + ("完整原始文献记录不得截断" * 10_000)
        for item in catalog
    )

    with pytest.raises(
        ContestDirectionPlanDeliveryError,
        match="every complete planning literature record exceeds.*never truncated",
    ):
        direction_cli._select_planning_literature(
            catalog,
            contexts,
            queries=("prime gaps mechanism",),
        )


def test_shortlist_only_arxiv_status_verification_excludes_withdrawn_and_backfills() -> None:
    def candidate(index: int, citations: int) -> dict[str, Any]:
        return {
            "record_id": f"direction-paper-{index}",
            "title": f"Prime gaps mechanism candidate {index}",
            "authors": ["A. Researcher"],
            "abstract": "Prime gaps mechanism evidence.",
            "source_url": f"https://arxiv.org/abs/2401.0000{index}",
            "url": f"https://arxiv.org/abs/2401.0000{index}",
            "retrieved_from": "arxiv",
            "retrieved_at": _RETRIEVED_AT,
            "publication_date": "2024-01-01",
            "publication_status": "preprint",
            "status_source": "arxiv_atom",
            "status_as_of": "2026-08-12",
            "citation_count": citations,
            "citation_count_source": "openalex",
            "citation_count_as_of": "2026-08-12",
            "repository_doi": f"10.48550/arxiv.2401.0000{index}",
        }

    catalog = (candidate(1, 500), candidate(2, 50), candidate(3, 1))
    contexts = tuple(json.dumps(item, ensure_ascii=False) + ("x" * 8_000) for item in catalog)
    verified_titles: list[str] = []

    def verify(paper: AcademicPaper) -> AcademicPaper:
        verified_titles.append(paper.title)
        status = "withdrawn" if paper.title.endswith("1") else "preprint"
        return paper.model_copy(
            update={
                "publication_status": status,
                "status_source": "arxiv_abs",
                "status_as_of": date(2026, 8, 12),
            }
        )

    selected, selected_contexts, receipts = direction_cli._select_planning_literature_with_status(
        catalog,
        contexts,
        queries=("prime gaps mechanism evidence",),
        arxiv_status_verifier=verify,
        maximum_records=1,
    )

    assert [item["record_id"] for item in selected] == ["direction-paper-2"]
    assert verified_titles == [
        "Prime gaps mechanism candidate 1",
        "Prime gaps mechanism candidate 2",
    ]
    assert receipts[0]["outcome"] == "excluded_from_positive_planning"
    assert receipts[1]["outcome"] == "eligible_after_verification"
    assert "最终候选状态复核" in selected_contexts[0]


def test_finalist_status_receipt_keeps_catalog_url_when_repository_doi_has_arxiv_url() -> None:
    catalog_url = "https://doi.org/10.1000/dual-identifier"
    record = {
        "record_id": "dual-identifier-published",
        "title": "A published dual-identifier method paper",
        "authors": ["A. Researcher"],
        "abstract": "A synthetic method record used to test bibliographic identity.",
        "source_url": catalog_url,
        "url": catalog_url,
        "retrieved_from": "openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "published",
        "repository_doi": "10.48550/arxiv.2401.01234",
    }
    verifier_calls: list[str] = []

    _verified, _context, receipt = direction_cli._verify_arxiv_finalist(
        record,
        "synthetic context",
        verifier=lambda paper: verifier_calls.append(str(paper.url)) or paper,
    )

    assert verifier_calls == []
    assert receipt["verification_attempted"] is False
    assert receipt["source_url"] == catalog_url


def test_finalist_status_query_uses_arxiv_url_without_replacing_catalog_identity() -> None:
    catalog_url = "https://doi.org/10.1000/dual-identifier-preprint"
    arxiv_url = "https://arxiv.org/abs/2401.05678"
    record = {
        "record_id": "dual-identifier-preprint",
        "title": "A preprint dual-identifier method paper",
        "authors": ["A. Researcher"],
        "abstract": "A synthetic method record used to test status lookup identity.",
        "source_url": catalog_url,
        "url": catalog_url,
        "retrieved_from": "arxiv,openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "preprint",
        "repository_doi": "10.48550/arxiv.2401.05678",
    }
    verifier_calls: list[str] = []

    def verify(paper: AcademicPaper) -> AcademicPaper:
        verifier_calls.append(str(paper.url))
        return paper.model_copy(
            update={
                "publication_status": "preprint",
                "status_source": "arxiv_atom",
                "status_as_of": date(2026, 8, 15),
            }
        )

    _verified, _context, receipt = direction_cli._verify_arxiv_finalist(
        record,
        "synthetic context",
        verifier=verify,
    )

    assert verifier_calls == [arxiv_url]
    assert receipt["verification_attempted"] is True
    assert receipt["source_url"] == catalog_url


def _preprint_record() -> dict[str, Any]:
    return {
        "record_id": "transport-preprint",
        "title": "A transport-retried preprint method paper",
        "authors": ["A. Researcher"],
        "abstract": "A synthetic preprint used to test transport-failure handling.",
        "source_url": "https://arxiv.org/abs/2401.09999",
        "url": "https://arxiv.org/abs/2401.09999",
        "retrieved_from": "arxiv,openalex",
        "retrieved_at": _RETRIEVED_AT,
        "publication_status": "preprint",
        "repository_doi": "10.48550/arxiv.2401.09999",
    }


def test_finalist_transport_failure_retries_once_then_preserves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def verify(_paper: AcademicPaper) -> AcademicPaper:
        calls.append(1)
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(direction_cli, "_verification_transport_retry_seconds", lambda: 0.0)
    monkeypatch.setattr(
        direction_cli, "_finalist_status_cache_path", lambda: tmp_path / "cache.json"
    )

    _verified, _context, receipt = direction_cli._verify_arxiv_finalist(
        _preprint_record(), "synthetic context", verifier=verify
    )

    assert len(calls) == 2
    assert receipt["outcome"] == "verification_failed_transport_preserved"
    assert "TimeoutError" in receipt["error"]


def test_finalist_transport_failure_served_from_cross_run_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arxiv_url = "https://arxiv.org/abs/2401.09999"
    cache_key = hashlib.sha256(f"{arxiv_url}\npreprint".encode()).hexdigest()
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps(
            {
                cache_key: {
                    "source_url": arxiv_url,
                    "original_status": "preprint",
                    "verified_status": "preprint",
                    "status_source": "arxiv_atom",
                    "status_as_of": "2026-08-15",
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(direction_cli, "_verification_transport_retry_seconds", lambda: 0.0)
    monkeypatch.setattr(direction_cli, "_finalist_status_cache_path", lambda: cache_file)

    def verify(_paper: AcademicPaper) -> AcademicPaper:
        raise TimeoutError("connection timed out")

    record = _preprint_record()
    _verified, context, receipt = direction_cli._verify_arxiv_finalist(
        record, "synthetic context", verifier=verify
    )

    assert receipt["outcome"] == "verification_served_from_cache"
    assert receipt["verified_status"] == "preprint"
    assert record["status_source"] == "arxiv_atom"
    assert "跨运行缓存" in context


def test_finalist_non_transport_failure_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def verify(_paper: AcademicPaper) -> AcademicPaper:
        calls.append(1)
        raise ValueError("unexpected status payload")

    monkeypatch.setattr(direction_cli, "_verification_transport_retry_seconds", lambda: 0.0)
    monkeypatch.setattr(
        direction_cli, "_finalist_status_cache_path", lambda: tmp_path / "cache.json"
    )

    _verified, _context, receipt = direction_cli._verify_arxiv_finalist(
        _preprint_record(), "synthetic context", verifier=verify
    )

    assert len(calls) == 1
    assert receipt["outcome"] == "verification_failed_preserved_as_non_authoritative"


def test_finalist_success_writes_status_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(direction_cli, "_finalist_status_cache_path", lambda: cache_file)

    def verify(paper: AcademicPaper) -> AcademicPaper:
        return paper.model_copy(
            update={
                "publication_status": "preprint",
                "status_source": "arxiv_atom",
                "status_as_of": date(2026, 8, 15),
            }
        )

    _verified, _context, receipt = direction_cli._verify_arxiv_finalist(
        _preprint_record(), "synthetic context", verifier=verify
    )

    assert receipt["outcome"] == "eligible_after_verification"
    assert cache_file.is_file()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert any(
        item.get("source_url") == "https://arxiv.org/abs/2401.09999"
        for item in payload.values()
    )


def test_opt_in_live_direction_delivery(tmp_path: Path) -> None:
    """Paid/provider live smoke; skipped unless the operator explicitly opts in."""

    if os.getenv("RUN_LIVE_CONTEST_DIRECTION_PLAN") != "1":
        pytest.skip("set RUN_LIVE_CONTEST_DIRECTION_PLAN=1 for live retrieval/model/PDF smoke")
    report = run_contest_direction_plan_delivery(
        direction=os.getenv("CONTEST_DIRECTION_PLAN_SEED", _DIRECTION),
        output_dir=tmp_path / "live-direction-plan",
        skills_root=Path("skills"),
        config_path=Path("config.yaml"),
        env_path=Path(".env"),
        max_results_per_search=2,
        timeout_seconds=900,
    )
    assert report["status"] == "completed"
    assert report["literature"]["entries_from_real_search_only"] is True
    assert report["pdf"]["verified_page_count"] <= 20
