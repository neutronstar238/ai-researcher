from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoresearch.competition.science125_batch as batch_module
from autoresearch.competition.contest_direction_stage_checkpoint import (
    replayable_literature_searchers,
    replayable_stage_completion,
)
from autoresearch.competition.contest_human_delivery_validator import (
    HumanDeliveryValidationError,
    HumanDeliveryValidationReport,
)
from autoresearch.competition.contest_question_input import (
    Science125QuestionInput,
    Science125QuestionSet,
)
from autoresearch.competition.science125_batch import (
    Science125BatchError,
    run_science125_batch,
    select_science125_questions,
)
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

_DISCIPLINES = (
    ("Mathematical Sciences", "数学科学", 3),
    ("Chemistry", "化学", 9),
    ("Medicine & Health", "医学与健康", 11),
    ("Biology", "生物学", 22),
    ("Astronomy", "天文学", 23),
    ("Physics", "物理学", 18),
    ("Engineering & Materials Science", "工程与材料科学", 4),
    ("Information Science", "信息科学", 4),
    ("Neuroscience", "神经科学", 12),
    ("Ecology", "生态学", 8),
    ("Energy Science", "能源科学", 3),
    ("Artificial Intelligence", "人工智能", 8),
)


@pytest.fixture(autouse=True)
def _deterministic_human_delivery_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    def validate(**kwargs: object) -> HumanDeliveryValidationReport:
        result = kwargs["result"]
        assert isinstance(result, dict)
        if result.get("force_invalid_human_delivery") is True:
            raise HumanDeliveryValidationError("deterministic invalid human delivery")
        return HumanDeliveryValidationReport(
            reference_count=5,
            pilot_executed=bool(result.get("preexperiment_executed")),
            table_count=1 if result.get("preexperiment_executed") is True else 0,
            figure_count=1 if result.get("preexperiment_executed") is True else 0,
            provenance_binding_count=2 if result.get("preexperiment_executed") is True else 0,
            bibliography_binding="manifest-source-projection",
        )

    monkeypatch.setattr(batch_module, "validate_runner_human_delivery", validate)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _question_set(pdf: Path) -> Science125QuestionSet:
    source_hash = "a" * 64
    questions: list[Science125QuestionInput] = []
    ordinal = 0
    for page_offset, (discipline_en, discipline_zh, count) in enumerate(_DISCIPLINES):
        for _ in range(count):
            ordinal += 1
            if ordinal == 1:
                text = "What makes prime numbers so special?"
                text_zh = "素数为何如此特别？"
            elif ordinal == 125:
                text = "Can robots or AIs have human creativity?"
                text_zh = None
            else:
                text = f"What is deterministic fixture question {ordinal}?"
                text_zh = None
            page = 7 + page_offset
            digest = _hash(f"{source_hash}\n{page}\n{text}")
            questions.append(
                Science125QuestionInput(
                    question_id=f"science125-q{ordinal:03d}-{digest[:16]}",
                    ordinal=ordinal,
                    question_en=text,
                    question_zh=text_zh,
                    discipline_en=discipline_en,
                    discipline_zh=discipline_zh,
                    pdf_page_number=page,
                    printed_page_number=page - 2,
                    source_pdf_path=pdf.resolve().as_posix(),
                    source_file_sha256=source_hash,
                    page_text_layer_sha256=_hash(f"page-{page}"),
                    question_text_sha256=_hash(text),
                    original_text_fragments=(text,),
                    extraction_evidence=(f"page {page}", text),
                    translation_provenance=(
                        "仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF标题层"
                        if ordinal == 1
                        else "未提供未经核验的中文翻译；英文问题逐字提取自PDF标题层"
                    ),
                )
            )
    payload = {
        "schema_version": "science125-question-set-v1",
        "source_title": "125 Questions: Exploration and Discovery",
        "source_year": 2021,
        "source_pdf_path": pdf.resolve().as_posix(),
        "source_file_sha256": source_hash,
        "extraction_backend": "poppler-pdftohtml-xml",
        "question_count": 125,
        "questions": [item.model_dump(mode="json") for item in questions],
    }
    return Science125QuestionSet(
        **payload,
        manifest_hash=batch_module.canonical_model_hash(payload),
    )


def _install_question_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Science125QuestionSet:
    pdf = tmp_path / "booklet.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfixture")
    question_set = _question_set(pdf)
    monkeypatch.setattr(
        batch_module,
        "extract_all_science_125_questions",
        lambda _path: question_set,
    )
    return question_set


def _completed_delivery(output_dir: Path, *, preexperiment: bool = True) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = output_dir / "delivery-report.json"
    report.write_text('{"status":"completed"}\n', encoding="utf-8")
    return {
        "schema_version": "contest-direction-research-loop-delivery-v2",
        "literature_protocol": "two_stage_literature_v5",
        "status": "completed",
        "independent_scientific_review": {"recommendation": "pass"},
        "preexperiment_executed": preexperiment,
        "delivery_report_path": report.as_posix(),
    }


def _plan_only_delivery(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = output_dir / "research-plan.pdf"
    plan.write_bytes(b"%PDF-1.7\nplan")
    report = output_dir / "delivery-report.json"
    report.write_text('{"status":"completed_plan_only"}\n', encoding="utf-8")
    return {
        "schema_version": "science125-plan-only-delivery-v2",
        "literature_protocol": "two_stage_literature_v5",
        "status": "completed_plan_only",
        "preexperiment_executed": False,
        "plan_pdf_path": plan.as_posix(),
        "delivery_report_path": report.as_posix(),
    }


def test_selects_by_source_slice_and_stable_ids(tmp_path: Path) -> None:
    question_set = _question_set(tmp_path / "booklet.pdf")

    assert [
        item.ordinal for item in select_science125_questions(question_set, start=3, limit=2)
    ] == [
        3,
        4,
    ]
    selected = select_science125_questions(
        question_set,
        include_question_ids=(question_set.questions[4].question_id, 2),
        limit=None,
    )
    assert [item.ordinal for item in selected] == [2, 5]

    with pytest.raises(Science125BatchError, match="unknown or malformed"):
        select_science125_questions(question_set, include_question_ids=("q999",))


def test_dry_run_extracts_manifest_without_calling_a_model_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_set = _install_question_set(monkeypatch, tmp_path)

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        start=2,
        limit=3,
        dry_run=True,
        direction_loop_runner=lambda **_kwargs: pytest.fail("runner must not be called"),
    )

    assert report["status"] == "dry_run"
    assert report["selected_count"] == 3
    assert [item["ordinal"] for item in report["results"]] == [2, 3, 4]
    persisted = json.loads(
        (tmp_path / "batch" / "science125-question-set.json").read_text(encoding="utf-8")
    )
    assert persisted["manifest_hash"] == question_set.manifest_hash


def test_serial_batch_requires_real_pilot_for_q1_then_falls_back_to_plan_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_question_set(monkeypatch, tmp_path)
    calls: list[tuple[int, str]] = []
    sleeps: list[float] = []
    hooks: list[int] = []

    def direction_runner(**kwargs: object) -> dict[str, object]:
        direction = str(kwargs["direction"])
        ordinal = 1 if "第1题" in direction else 2
        calls.append((ordinal, str(kwargs["preexperiment_policy"])))
        output = Path(kwargs["output_dir"])
        if ordinal == 1:
            delivery = _completed_delivery(output, preexperiment=True)
            delivery["source_accounting"] = {"surface": "success"}
            return delivery
        output.mkdir(parents=True, exist_ok=True)
        report = output / "delivery-report.json"
        report.write_text('{"status":"no_adapter"}\n', encoding="utf-8")
        return {
            "schema_version": "contest-direction-research-loop-delivery-v2",
            "literature_protocol": "two_stage_literature_v5",
            "status": "completed_without_preexperiment_no_compatible_adapter",
            "preexperiment_executed": False,
            "delivery_report_path": report.as_posix(),
        }

    def fallback(**kwargs: object) -> dict[str, object]:
        return _plan_only_delivery(Path(kwargs["output_dir"]))

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=2,
        min_interval_seconds=2.5,
        direction_loop_runner=direction_runner,
        plan_only_runner=fallback,
        sleep_fn=sleeps.append,
        per_question_hook=lambda question, _result: hooks.append(question.ordinal),
    )

    assert report["status"] == "completed"
    assert calls == [(1, "required"), (2, "if_supported")]
    assert sleeps == [2.5]
    assert hooks == [1, 2]
    assert report["results"][0]["preexperiment_executed"] is True
    assert report["results"][0]["source_accounting"] == {"surface": "success"}
    assert report["results"][1]["plan_only_fallback_used"] is True
    assert report["results"][1]["formal_experiment_executed"] is False


def test_plan_only_fallback_consumes_focused_two_stage_lock_without_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = _question_set(tmp_path / "booklet.pdf").questions[1]
    parent_direction = batch_module._question_direction(question)
    focused_direction = "聚焦方向：检验可证伪的局部结构假设"
    source_root = tmp_path / "research-loop"
    output_root = tmp_path / "plan-only"
    source_root.mkdir(parents=True)
    (source_root / "direction-input.json").write_text(
        json.dumps(
            {
                "schema_version": "contest-direction-research-loop-input-v2",
                "literature_protocol": "two_stage_literature_v5",
                "direction": parent_direction,
                "direction_id": "direction-loop-" + "a" * 20,
                "input_hash": "a" * 64,
                "source_accounting_protocol": "physical-source-http-attempt-ledger-v1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source_root / "selected-method-skills.json").write_text('{"skills": []}\n', encoding="utf-8")
    paths = {
        "broad_path": source_root / "literature" / "broad" / "direction-literature.json",
        "focus_path": source_root / "literature" / "refinement" / "direction-focus.json",
        "targeted_path": source_root / "literature" / "refinement" / "targeted-literature.json",
        "targeted_binding_path": source_root
        / "literature"
        / "refinement"
        / "direction-targeted-retrieval.json",
        "base_merged_path": source_root / "literature" / "merged-literature.json",
        "merged_path": source_root / "literature" / "layered-literature.json",
        "planning_lock_path": source_root / "literature" / "planning-literature.json",
        "r1_planning_coverage_path": source_root
        / "literature"
        / "planning-literature-coverage-r1.json",
        "r2_planning_coverage_path": source_root
        / "literature"
        / "planning-literature-coverage-r2.json",
        "planning_coverage_path": source_root / "literature" / "planning-literature-coverage.json",
        "gap_diagnosis_path": source_root / "literature" / "gap-repair" / "diagnosis.json",
        "gap_response_path": source_root / "literature" / "gap-repair" / "query-response.json",
        "gap_projection_path": source_root / "literature" / "gap-repair" / "query-projection.json",
        "gap_retrieval_path": source_root / "literature" / "gap-repair" / "retrieval.json",
        "finalist_status_path": source_root / "literature" / "finalist-status-verification.json",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    routing_path = source_root / "skill-routing.json"
    routing_path.write_text("{}\n", encoding="utf-8")
    hypothesis_path = source_root / "hypothesis-stage" / "direction-hypothesis-brainstorm.json"
    hypothesis_path.parent.mkdir(parents=True)
    hypothesis_path.write_text("{}\n", encoding="utf-8")

    planning_catalog = tuple(
        {"record_id": f"merged-direction-paper-{index:016x}"} for index in range(1, 6)
    )
    planning_context = tuple(f"[{index}] 真实文献{index}" for index in range(1, 6))
    broad = SimpleNamespace(
        direction=parent_direction,
        method_skills=(),
        artifact_hash="b" * 64,
        query_model_calls=1,
    )
    focus = SimpleNamespace(
        focused_direction_cn=focused_direction,
        artifact_hash="c" * 64,
        selected_focus_id="direction-focus-" + "d" * 16,
        model_call_count_at_creation=2,
    )
    targeted = SimpleNamespace(method_skills=(), artifact_hash="e" * 64, query_model_calls=1)
    targeted_binding = SimpleNamespace(artifact_hash="f" * 64)
    base_merged = SimpleNamespace(artifact_hash="0" * 64, merged_catalog_hash="9" * 64)
    merged = SimpleNamespace(artifact_hash="1" * 64, merged_catalog_hash="2" * 64)
    literature_state = SimpleNamespace(
        broad=broad,
        focus=focus,
        targeted=targeted,
        targeted_binding=targeted_binding,
        base_merged=base_merged,
        merged=merged,
        planning_catalog=planning_catalog,
        planning_context=planning_context,
        planning_lock_payload={"artifact_hash": "3" * 64},
        r1_planning_coverage=SimpleNamespace(receipt_hash="a" * 64),
        r2_planning_coverage=SimpleNamespace(receipt_hash="0" * 64),
        planning_coverage=SimpleNamespace(receipt_hash="b" * 64),
        gap_diagnosis=SimpleNamespace(diagnosis_hash="c" * 64),
        gap_response=SimpleNamespace(model_calls=1, receipt_hash="d" * 64),
        gap_projection=SimpleNamespace(projection_hash="e" * 64),
        gap_retrieval=SimpleNamespace(artifact_hash="f" * 64),
        **paths,
    )
    monkeypatch.setattr(
        batch_module,
        "_load_completed_two_stage_literature",
        lambda _root: literature_state,
    )
    routing_subset = (
        planning_catalog[4]["record_id"],
        planning_catalog[0]["record_id"],
        planning_catalog[2]["record_id"],
    )
    routing = SimpleNamespace(
        schema_version="contest-direct-skill-routing-v3",
        question=focused_direction,
        broad_literature_artifact_hash=broad.artifact_hash,
        focus_artifact_hash=focus.artifact_hash,
        selected_focus_id=focus.selected_focus_id,
        targeted_retrieval_binding_hash=targeted_binding.artifact_hash,
        targeted_literature_artifact_hash=targeted.artifact_hash,
        merged_literature_artifact_hash=merged.artifact_hash,
        merged_literature_catalog_hash=merged.merged_catalog_hash,
        literature_evidence_context=SimpleNamespace(record_ids=routing_subset),
        literature_evidence_record_ids=routing_subset,
        selected_skill_ids=("method-a",),
        selected_skill_hashes={"method-a": "4" * 64},
        artifact_hash="5" * 64,
        model_calls=1,
    )
    monkeypatch.setattr(batch_module, "load_contest_direct_skill_routing", lambda _path: routing)
    monkeypatch.setattr(batch_module, "_load_bound_skill_bodies", lambda *_args: ("技能正文",))
    hypotheses = SimpleNamespace(
        direction=focused_direction,
        artifact_hash="6" * 64,
        model_call_count=3,
        plan_context_payload=lambda: {"candidate": "模型候选"},
    )
    monkeypatch.setattr(
        batch_module,
        "load_contest_direction_hypothesis_brainstorm",
        lambda *_args, **_kwargs: hypotheses,
    )

    class FakeRuntime:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def verify_official_capability(self, **_kwargs: Any) -> None:
            pass

        @contextmanager
        def checkpointed_stage(self, *_args: Any, **_kwargs: Any):
            yield lambda **_call: None

    monkeypatch.setattr(batch_module, "ContestDirectionContextRuntime", FakeRuntime)
    captured: dict[str, Any] = {}
    fake_plan = SimpleNamespace(
        plan=SimpleNamespace(results="尚未执行预实验；以下仅为待验证预期。"),
        artifact_hash="7" * 64,
        generation_calls=1,
    )

    def generate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_text("{}\n", encoding="utf-8")
        return fake_plan

    monkeypatch.setattr(batch_module, "generate_contest_direct_plan", generate)
    monkeypatch.setattr(batch_module, "_verify_plan_references", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        batch_module,
        "contest_direct_plan_template_payload",
        lambda _plan: {"title": "测试计划", "references": list(planning_context)},
    )

    def materialize(**kwargs: Any) -> Any:
        plan_dir = Path(kwargs["output_dir"])
        plan_dir.mkdir(parents=True, exist_ok=True)
        files = {
            name: plan_dir / filename
            for name, filename in {
                "json_path": "research-plan.json",
                "markdown_path": "research-plan.md",
                "tex_path": "research-plan.tex",
                "pdf_path": "research-plan.pdf",
                "manifest_path": "research-plan-manifest.json",
            }.items()
        }
        for path in files.values():
            path.write_bytes(b"fixture")
        return SimpleNamespace(
            **files,
            source_payload_sha256="8" * 64,
            pdf_text_verified=True,
            page_count=4,
        )

    monkeypatch.setattr(batch_module, "materialize_contest_direct_plan", materialize)
    physical_attempts = {
        "broad-literature-query": 1,
        "focus-selection": 2,
        "targeted-literature-query": 1,
        "planning-literature-gap-repair-query": 1,
        "skill-routing": 1,
        "hypothesis-brainstorm": 3,
        "plan-only-final-plan": 2,
    }

    def provider_accounting(_root: Path, *, stage_name: str) -> dict[str, int]:
        attempts = physical_attempts[stage_name]
        transport_failures = 1 if stage_name == "plan-only-final-plan" else 0
        return {
            "attempt_count": attempts,
            "completed_count": attempts - transport_failures,
            "parse_failed_count": 0,
            "transport_failed_count": transport_failures,
            "terminal_failed_count": 0,
            "outcome_unknown_count": 0,
        }

    monkeypatch.setattr(batch_module, "provider_checkpoint_accounting", provider_accounting)

    result = batch_module.continue_plan_without_preexperiment(
        question=question,
        direction=parent_direction,
        direction_run_dir=source_root,
        output_dir=output_root,
    )

    assert captured["scientific_problem"] == focused_direction
    assert captured["literature_context"] == planning_context
    assert captured["temporary_agent_context"]["science125_parent_problem_zh"] == parent_direction
    assert result["schema_version"] == "science125-plan-only-delivery-v2"
    assert result["literature_protocol"] == "two_stage_literature_v5"
    assert result["source_accounting"]["checkpoint_status"] == ("verified_local_checkpoints")
    assert (
        result["source_accounting"]["physical_http_attempts"]["accounting_status"]
        == "verified_current_protocol"
    )
    assert result["focused_direction"] == focused_direction
    assert result["planning_reference_count"] == 5
    assert result["upstream_reused_without_repeat_retrieval"] is True
    assert result["model_call_accounting"]["planning_literature_gap_repair_calls"] == 1
    assert result["model_call_accounting"]["historical_source_provider_request_attempts"] == 9
    assert result["model_call_accounting"]["this_loop_observed_provider_request_attempts"] == 1
    assert result["model_call_accounting"]["total_provenance_provider_request_attempts"] == 10
    assert result["model_call_accounting"]["physical_provider_attempt_total"] == 11
    assert result["model_call_accounting"]["physical_provider_attempts_by_stage"] == (
        physical_attempts
    )
    assert (
        result["model_call_accounting"]["provider_checkpoint_accounting_by_stage"][
            "plan-only-final-plan"
        ]["transport_failed_count"]
        == 1
    )
    assert result["model_call_accounting"]["physical_provider_attempt_semantics"] == (
        "lifetime_durable_attempt_reservations_deduplicated_by_canonical_stage_owner"
    )
    assert {
        "base_merged_literature",
        "effective_merged_literature",
        "layered_literature",
        "planning_literature_coverage_r1",
        "planning_literature_coverage_r2",
        "planning_literature_coverage",
        "planning_literature_gap_diagnosis",
        "planning_literature_gap_query_response",
        "planning_literature_gap_query_projection",
        "planning_literature_gap_retrieval",
    }.issubset(result["artifacts"])
    assert "literature_artifact" not in result


def test_current_plan_only_report_cannot_downgrade_to_legacy_missing_source_accounting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delivery-report.json"
    payload: dict[str, Any] = {
        "schema_version": "science125-plan-only-delivery-v2",
        "status": "completed_plan_only",
        "source_accounting": {"checkpoint_status": "verified_local_checkpoints"},
    }
    payload["report_hash"] = batch_module.canonical_model_hash(payload)
    batch_module._write_or_verify_plan_only_report(
        path,
        payload,
        require_source_accounting=True,
    )
    legacy = dict(payload)
    legacy.pop("source_accounting")
    legacy["report_hash"] = batch_module.canonical_model_hash(
        {key: value for key, value in legacy.items() if key != "report_hash"}
    )
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.raises(Science125BatchError, match="source accounting differs"):
        batch_module._write_or_verify_plan_only_report(
            path,
            payload,
            require_source_accounting=True,
        )
    assert (
        batch_module._write_or_verify_plan_only_report(
            path,
            payload,
            require_source_accounting=False,
        )
        == legacy
    )


def test_failed_question_is_isolated_and_resume_retries_only_that_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_question_set(monkeypatch, tmp_path)
    first_calls: list[int] = []

    def first_runner(**kwargs: object) -> dict[str, object]:
        ordinal = 1 if "第1题" in str(kwargs["direction"]) else 2
        first_calls.append(ordinal)
        if ordinal == 1:
            Path(kwargs["output_dir"]).mkdir(parents=True, exist_ok=True)
            raise RuntimeError("isolated fixture failure")
        return _completed_delivery(Path(kwargs["output_dir"]))

    first = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=2,
        preexperiment_policy="required",
        min_interval_seconds=0,
        direction_loop_runner=first_runner,
    )
    assert first["completed_count"] == 1
    assert first["failed_count"] == 1
    assert first_calls == [1, 2]

    resumed_calls: list[tuple[int, bool]] = []

    def resumed_runner(**kwargs: object) -> dict[str, object]:
        ordinal = 1 if "第1题" in str(kwargs["direction"]) else 2
        resumed_calls.append((ordinal, bool(kwargs["resume_existing"])))
        return _completed_delivery(Path(kwargs["output_dir"]))

    resumed = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=2,
        resume=True,
        preexperiment_policy="required",
        min_interval_seconds=0,
        direction_loop_runner=resumed_runner,
    )

    assert resumed["status"] == "completed"
    assert resumed_calls == [(1, True)]
    assert resumed["results"][1]["resume_action"] == "already_complete_no_model_call"
    attempts = tmp_path / "batch" / "questions"
    q1 = next(path for path in attempts.iterdir() if path.name.startswith("q001-"))
    assert (q1 / "attempts" / "attempt-001" / "completed-receipt.json").is_file()
    assert (q1 / "attempts" / "attempt-001" / "failed-receipt-001.json").is_file()


def test_failed_attempt_binds_verified_gap_escrow_and_literature_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_question_set(monkeypatch, tmp_path)

    def failing_runner(**kwargs: object) -> dict[str, object]:
        root = Path(str(kwargs["output_dir"]))
        completion = replayable_stage_completion(
            root=root,
            stage_name="planning-literature-gap-repair-query",
            stage_input_hash="a" * 64,
            completion=lambda **_call: LLMJsonCompletionResult(
                provider="test",
                base_url="https://provider.example/v1",
                model_name="test-model",
                endpoint="https://provider.example/v1/chat/completions",
                response_text='{"repairs": []}',
                parsed_json={"repairs": []},
                temperature=0.2,
            ),
        )
        completion(
            messages=[{"role": "user", "content": "synthetic repair"}],
            max_tokens=100,
            temperature=0.2,
        )
        paper = AcademicPaper(
            title="Synthetic observation",
            authors=("A",),
            abstract="A synthetic source record.",
            url="https://example.org/synthetic-observation",
            source="openalex",
        )
        searchers = replayable_literature_searchers(
            root=root / "literature" / "gap-repair",
            searchers={
                "openalex": lambda _query, *, limit: [paper][:limit],
                "arxiv": lambda _query, *, limit: (_ for _ in ()).throw(
                    RuntimeError(f"synthetic source failure {limit}")
                ),
            },
        )
        searchers["openalex"]("synthetic observation", limit=5)
        with pytest.raises(RuntimeError, match="synthetic source failure"):
            searchers["arxiv"]("synthetic counterevidence", limit=5)
        raise RuntimeError("downstream failure after durable checkpoints")

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=failing_runner,
    )

    failure = report["results"][0]
    assert report["failed_count"] == 1
    assert failure["model_call_accounting"]["outer_provider_escrow_count"] == 1
    assert (
        failure["model_call_accounting"]["outer_provider_escrow_count_by_stage"][
            "planning-literature-gap-repair-query"
        ]
        == 1
    )
    assert failure["source_accounting"]["literature_searches"] == {
        "request_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "by_source": {
            "arxiv": {"request_count": 1, "completed_count": 0, "failed_count": 1},
            "openalex": {"request_count": 1, "completed_count": 1, "failed_count": 0},
        },
    }
    assert failure["source_accounting"]["paper_status_verifications"] == {
        "requested_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "by_verifier": {},
    }
    assert (
        failure["source_accounting"]["physical_http_attempts"]["accounting_status"]
        == "legacy_unavailable"
    )
    assert (
        failure["source_accounting"]["physical_http_attempts"]["literature_searches"][
            "requested_count"
        ]
        is None
    )
    research_loop = failure["artifacts"]["research_loop"]
    assert research_loop["relative_path"] == "research-loop"
    assert research_loop["file_inventory"]
    assert research_loop["file_inventory_hash"] == batch_module.canonical_model_hash(
        {"files": research_loop["file_inventory"]}
    )


def test_failed_model_call_accounting_distinguishes_completed_and_parse_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero = {
        "attempt_count": 0,
        "completed_count": 0,
        "parse_failed_count": 0,
        "outcome_unknown_count": 0,
    }

    def accounting(_root: Path, *, stage_name: str) -> dict[str, int]:
        if stage_name == "hypothesis-brainstorm":
            return {
                "attempt_count": 1,
                "completed_count": 0,
                "parse_failed_count": 1,
                "outcome_unknown_count": 0,
            }
        if stage_name == "focus-selection":
            return {
                "attempt_count": 1,
                "completed_count": 1,
                "parse_failed_count": 0,
                "outcome_unknown_count": 0,
            }
        return dict(zero)

    monkeypatch.setattr(batch_module, "provider_checkpoint_accounting", accounting)

    result = batch_module._failed_model_call_accounting(tmp_path)

    assert result["this_attempt_observed_provider_request_attempts"] == 2
    assert result["outer_provider_escrow_count"] == 1
    assert result["outer_provider_parse_failed_count"] == 1
    assert result["outer_provider_transport_failed_count"] == 0
    assert result["outer_provider_terminal_failed_count"] == 0
    assert result["outer_provider_outcome_unknown_count"] == 0
    assert result["outer_provider_physical_attempt_count"] == 2
    assert result["outer_provider_response_accounting_by_stage"]["hypothesis-brainstorm"] == {
        "attempt_count": 1,
        "completed_count": 0,
        "parse_failed_count": 1,
        "outcome_unknown_count": 0,
    }


def test_failed_attempt_resume_preserves_nested_literature_request_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_question_set(monkeypatch, tmp_path)
    source_calls = 0

    def failing_runner(**kwargs: object) -> dict[str, object]:
        nonlocal source_calls
        root = Path(str(kwargs["output_dir"]))

        def source(_query: str, *, limit: int) -> list[AcademicPaper]:
            nonlocal source_calls
            source_calls += 1
            return [
                AcademicPaper(
                    title="Synthetic durable evidence",
                    authors=("A",),
                    abstract="A source-backed synthetic abstract.",
                    url="https://example.org/synthetic-durable-evidence",
                    source="openalex",
                )
            ][:limit]

        replayable_literature_searchers(
            root=root / "literature" / "broad",
            searchers={"openalex": source},
        )["openalex"]("synthetic durable request", limit=5)
        raise RuntimeError("synthetic downstream failure")

    first = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=failing_runner,
    )
    resumed = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        resume=True,
        min_interval_seconds=0,
        direction_loop_runner=failing_runner,
    )

    assert source_calls == 1
    assert first["results"][0]["source_accounting"]["literature_searches"]["request_count"] == 1
    assert resumed["results"][0]["source_accounting"]["literature_searches"] == {
        "request_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "by_source": {"openalex": {"request_count": 1, "completed_count": 1, "failed_count": 0}},
    }
    attempt = (
        tmp_path
        / "batch"
        / "questions"
        / next((tmp_path / "batch" / "questions").iterdir()).name
        / "attempts"
        / "attempt-001"
    )
    assert (attempt / "failed-receipt-001.json").is_file()
    assert (attempt / "failed-receipt-002.json").is_file()


def test_false_human_completion_is_isolated_as_a_failed_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_question_set(monkeypatch, tmp_path)

    def invalid_runner(**kwargs: object) -> dict[str, object]:
        delivery = _completed_delivery(Path(kwargs["output_dir"]))
        delivery["force_invalid_human_delivery"] = True
        return delivery

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=invalid_runner,
    )

    assert report["completed_count"] == 0
    assert report["failed_count"] == 1
    assert report["results"][0]["error_type"] == "Science125BatchError"
    assert "human delivery contract" in report["results"][0]["error"]


@pytest.mark.parametrize("recommendation", ["major_revision", "reject", "unclear"])
def test_batch_never_completes_a_scientifically_blocked_direction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recommendation: str,
) -> None:
    _install_question_set(monkeypatch, tmp_path)

    def blocked_runner(**kwargs: object) -> dict[str, object]:
        delivery = _completed_delivery(Path(kwargs["output_dir"]))
        delivery["independent_scientific_review"] = {
            "recommendation": recommendation,
        }
        return delivery

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=blocked_runner,
    )

    assert report["completed_count"] == 0
    assert report["failed_count"] == 1
    assert report["results"][0]["error_type"] == "Science125BatchError"
    assert "scientific review" in report["results"][0]["error"]


def test_batch_accepts_minor_review_only_with_explicit_minor_completion_status() -> None:
    result = {
        "schema_version": "contest-direction-research-loop-delivery-v2",
        "literature_protocol": "two_stage_literature_v5",
        "status": "completed_with_minor_issues",
        "independent_scientific_review": {"recommendation": "minor_revision"},
    }

    batch_module._validate_direction_delivery_protocol(result, allow_plan_only=False)
    result["status"] = "completed"
    with pytest.raises(batch_module.Science125BatchError, match="disagrees"):
        batch_module._validate_direction_delivery_protocol(result, allow_plan_only=False)


def test_batch_rejects_legacy_single_retrieval_delivery_before_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_question_set(monkeypatch, tmp_path)

    def legacy_runner(**kwargs: object) -> dict[str, object]:
        output = Path(kwargs["output_dir"])
        delivery = _completed_delivery(output)
        delivery["schema_version"] = "contest-direction-research-loop-delivery-v1"
        delivery.pop("literature_protocol")
        return delivery

    report = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=legacy_runner,
    )

    assert report["completed_count"] == 0
    assert report["failed_count"] == 1
    assert report["results"][0]["error_type"] == "Science125BatchError"
    assert "legacy or unknown direction delivery" in report["results"][0]["error"]


def test_resume_revalidates_and_retries_an_old_invalid_completed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_set = _install_question_set(monkeypatch, tmp_path)
    output_root = tmp_path / "batch"
    first = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=output_root,
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=lambda **kwargs: _completed_delivery(Path(kwargs["output_dir"])),
    )
    assert first["completed_count"] == 1

    question_root = batch_module._question_root(output_root, question_set.questions[0])
    state_path = question_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["force_invalid_human_delivery"] = True
    state["receipt_hash"] = batch_module.canonical_model_hash(
        {key: value for key, value in state.items() if key != "receipt_hash"}
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    resumed_calls: list[bool] = []

    def resumed_runner(**kwargs: object) -> dict[str, object]:
        resumed_calls.append(bool(kwargs["resume_existing"]))
        return _completed_delivery(Path(kwargs["output_dir"]))

    resumed = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=output_root,
        limit=1,
        resume=True,
        min_interval_seconds=0,
        direction_loop_runner=resumed_runner,
    )

    assert resumed["completed_count"] == 1
    assert resumed_calls == [False]
    assert (question_root / "attempts" / "attempt-002" / "completed-receipt.json").is_file()


def test_resume_rejects_rehashed_current_source_accounting_that_differs_from_local_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_set = _install_question_set(monkeypatch, tmp_path)
    output_root = tmp_path / "batch"
    current_accounting = {
        "checkpoint_status": "verified_local_checkpoints",
        "physical_http_attempts": {
            "literature_searches": {"requested_count": 1},
        },
    }
    monkeypatch.setattr(
        batch_module,
        "research_loop_source_checkpoint_accounting",
        lambda _root: current_accounting,
    )

    def current_runner(**kwargs: object) -> dict[str, object]:
        output = Path(kwargs["output_dir"])
        delivery = _completed_delivery(output)
        (output / "direction-input.json").write_text(
            json.dumps({"source_accounting_protocol": ("physical-source-http-attempt-ledger-v1")}),
            encoding="utf-8",
        )
        delivery["source_accounting"] = current_accounting
        Path(str(delivery["delivery_report_path"])).write_text(
            json.dumps(
                {
                    "status": "completed",
                    "source_accounting": current_accounting,
                }
            ),
            encoding="utf-8",
        )
        return delivery

    first = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=output_root,
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=current_runner,
    )
    assert first["completed_count"] == 1

    question = question_set.questions[0]
    question_root = batch_module._question_root(output_root, question)
    state_path = question_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["source_accounting"]["physical_http_attempts"]["literature_searches"][
        "requested_count"
    ] = 999
    state["receipt_hash"] = batch_module.canonical_model_hash(
        {key: value for key, value in state.items() if key != "receipt_hash"}
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(Science125BatchError, match="source accounting differs"):
        batch_module._load_completed_question_state(question_root, question)


def test_resume_does_not_upgrade_a_legacy_completed_receipt_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_set = _install_question_set(monkeypatch, tmp_path)
    output_root = tmp_path / "batch"
    first = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=output_root,
        limit=1,
        min_interval_seconds=0,
        direction_loop_runner=lambda **kwargs: _completed_delivery(Path(kwargs["output_dir"])),
    )
    assert first["completed_count"] == 1
    question_root = batch_module._question_root(output_root, question_set.questions[0])
    state_path = question_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = "science125-question-completion-v1"
    state.pop("literature_protocol")
    state.pop("direction_delivery_schema")
    state["receipt_hash"] = batch_module.canonical_model_hash(
        {key: value for key, value in state.items() if key != "receipt_hash"}
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    calls: list[bool] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(bool(kwargs["resume_existing"]))
        return _completed_delivery(Path(kwargs["output_dir"]))

    resumed = run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=output_root,
        limit=1,
        resume=True,
        min_interval_seconds=0,
        direction_loop_runner=runner,
    )

    assert resumed["completed_count"] == 1
    assert calls == [False]
    assert (question_root / "attempts" / "attempt-002" / "completed-receipt.json").is_file()


def test_resume_rejects_a_different_question_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_question_set(monkeypatch, tmp_path)
    run_science125_batch(
        question_pdf=tmp_path / "booklet.pdf",
        output_root=tmp_path / "batch",
        limit=1,
        dry_run=True,
    )

    with pytest.raises(Science125BatchError, match="existing checkpoint differs"):
        run_science125_batch(
            question_pdf=tmp_path / "booklet.pdf",
            output_root=tmp_path / "batch",
            start=2,
            limit=1,
            resume=True,
            direction_loop_runner=lambda **_kwargs: {},
        )
