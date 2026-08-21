from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

from autoresearch.api.app import _validate_bind_host, create_app
from autoresearch.api.research_service import ResearchApiService
from autoresearch.competition.contest_direction_stage_checkpoint import (
    record_completed_stage,
)
from autoresearch.competition.contest_human_delivery_validator import (
    HumanDeliveryValidationReport,
)


class FakeDirectionRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        output = Path(kwargs["output_dir"])
        direction_input = output / "direction-input.json"
        direction_input.parent.mkdir(parents=True, exist_ok=True)
        direction_input.write_text('{"direction":"fake"}\n', encoding="utf-8")
        evidence = output / "literature" / "broad" / "direction-literature.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"source":"fake-no-network"}\n', encoding="utf-8")
        plan = output / "plan" / "research-plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# 测试研究计划\n", encoding="utf-8")
        (output / "plan" / "research-plan.json").write_text("{}\n", encoding="utf-8")
        private_source = output / "plan" / "_private" / "research-plan-source.json"
        private_source.parent.mkdir(parents=True, exist_ok=True)
        private_source.write_text(
            '{"artifact_path":"C:/private/metrics.json","run_id":"secret"}\n',
            encoding="utf-8",
        )
        (output / "system-authored-final-research-plan.json").write_text(
            '{"artifact_hash":"internal"}\n', encoding="utf-8"
        )
        (output / "plan" / "research-plan-manifest.json").write_text(
            '{"source_payload_sha256":"internal"}\n', encoding="utf-8"
        )
        (output / "checkpoints" / "provider-responses").mkdir(parents=True, exist_ok=True)
        (output / "checkpoints" / "provider-responses" / "private.json").write_text(
            "{}\n", encoding="utf-8"
        )
        record_completed_stage(
            root=output,
            ordinal=1,
            stage_name="broad-literature-query",
            stage_input_hash="a" * 64,
            artifacts=(evidence,),
        )
        return {
            "schema_version": "contest-direction-research-loop-delivery-v2",
            "literature_protocol": "two_stage_literature_v5",
            "status": "completed",
            "independent_scientific_review": {"recommendation": "pass"},
            "preexperiment_executed": True,
            "delivery_report_path": plan.as_posix(),
        }


class FakeEvolutionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def evolve_run(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "status": "shadow_validated",
            "candidate_skill_ids": ["candidate_a"],
            "promotion_authorized": False,
        }


class FakeBatchService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "schema_version": "science125-batch-report-v2",
            "literature_protocol": "two_stage_literature_v5",
            "status": "dry_run" if kwargs["dry_run"] else "completed",
            "question_count": kwargs["limit"],
            "provider_calls": 0 if kwargs["dry_run"] else 1,
        }


def _accept_fake_delivery(**_kwargs: Any) -> HumanDeliveryValidationReport:
    return HumanDeliveryValidationReport(
        reference_count=5,
        pilot_executed=True,
        table_count=1,
        figure_count=1,
        provenance_binding_count=2,
        bibliography_binding="manifest-source-projection",
    )


async def _wait_for_status(
    client: TestClient, run_id: str, expected: str, *, attempts: int = 100
) -> dict[str, Any]:
    for _ in range(attempts):
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status == 200
        payload: dict[str, Any] = await response.json()
        if payload["status"] == expected:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}")


_FRONTEND_ROUTES = (
    "/",
    "/projects",
    "/literature",
    "/experiments",
    "/assets",
    "/knowledge",
    "/writing",
    "/reflections",
    "/agents",
    "/approvals",
    "/settings",
)


@pytest.mark.asyncio
async def test_frontend_spa_serves_root_and_every_navigation_deep_link(
    tmp_path: Path,
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        for route in _FRONTEND_ROUTES:
            response = await client.get(route)
            assert response.status == 200, route
            assert response.content_type == "text/html", route
            document = await response.text()
            assert '<div id="root"></div>' in document, route
            assert "研启智链 / AI-Researcher - 研究指挥中心" in document, route
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_frontend_spa_query_string_does_not_change_deep_link_routing(
    tmp_path: Path,
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get("/projects?run=run%2Fwith%2Fslashes&q=alpha")
        assert response.status == 200
        assert response.content_type == "text/html"
        assert '<div id="root"></div>' in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/does-not-exist",
        "/API",
        "/API/does-not-exist",
        "/%61pi",
        "/%61pi/does-not-exist",
        "/api%2Fdoes-not-exist",
        "/%2561pi",
        "/static%252Fdoes-not-exist.js",
        "/%2Fapi",
        "/%2e/api",
        "/x/%2e%2e/static/does-not-exist.js",
        "/api/%2e%2e/projects",
        "/api/x/%2e%2e/%2e%2e/projects",
        "/static/%2e%2e/projects",
        "/static/x/%2e%2e/%2e%2e/projects",
        "/%61pi/%2e%2e/projects",
        "/%73tatic/%2e%2e/projects",
        "/x/%2e%2e/api",
        "/static",
        "/static/does-not-exist.js",
        "/STATIC",
        "/STATIC/does-not-exist.js",
        "/%73tatic",
        "/%73tatic/does-not-exist.js",
        "/static%2Fdoes-not-exist.js",
    ],
)
async def test_frontend_spa_fallback_fails_closed_for_api_and_static_prefixes(
    tmp_path: Path, path: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get(URL(path, encoded=True))
        assert response.status == 404
        assert response.content_type != "text/html"
        assert '<div id="root"></div>' not in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/apiary", "/statician", "/caf%C3%A9"])
async def test_frontend_spa_preserves_non_reserved_prefix_boundaries(
    tmp_path: Path, path: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get(URL(path, encoded=True))
        assert response.status == 200
        assert response.content_type == "text/html"
        assert '<div id="root"></div>' in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/index.html",
        "/favicon.ico",
        "/app.js",
        "/.env",
        "/assets/chunk.js",
    ],
)
async def test_frontend_spa_rejects_unknown_file_shaped_requests(
    tmp_path: Path, path: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get(path)
        assert response.status == 404
        assert response.content_type != "text/html"
        assert '<div id="root"></div>' not in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/%",
        "/%2",
        "/%GG",
        "/%25252561pi",
        "/%00",
        "/%C2%80",
        "/%C2%85",
        "/%C2%9F",
        "/x%5Capi",
        "/" + "x" * 4097,
    ],
)
async def test_frontend_spa_fails_closed_for_malformed_or_ambiguous_raw_paths(
    tmp_path: Path, path: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get(URL(path, encoded=True))
        assert response.status in {400, 404}
        assert response.content_type != "text/html"
        assert '<div id="root"></div>' not in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/static/unknown.js",
        "/static/index.html",
        "/static/%2e%2e/index.html",
        "/static/%2e%2e/api/health",
        "/static/app.js/extra",
    ],
)
async def test_frontend_static_allowlist_rejects_unknown_and_traversal(
    tmp_path: Path, path: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.get(URL(path, encoded=True))
        assert response.status == 404
        assert '<div id="root"></div>' not in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def test_frontend_unknown_non_get_methods_never_receive_spa_html(
    tmp_path: Path, method: str
) -> None:
    client = TestClient(
        TestServer(create_app(service=ResearchApiService(work_root=tmp_path / "api")))
    )
    await client.start_server()
    try:
        response = await client.request(method, "/projects")
        assert response.status != 200
        assert response.content_type != "text/html"
        assert '<div id="root"></div>' not in await response.text()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_frontend_explicit_routes_keep_precedence_and_content_types(
    tmp_path: Path,
) -> None:
    service = ResearchApiService(
        work_root=tmp_path / "api",
        runner=FakeDirectionRunner(),
        delivery_validator=_accept_fake_delivery,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        health = await client.get("/api/health")
        assert health.status == 200
        assert health.content_type == "application/json"
        assert (await health.json())["status"] == "ok"

        created = await (
            await client.post("/api/runs", json={"direction": "路由优先级测试"})
        ).json()
        completed = await _wait_for_status(client, created["run_id"], "completed")
        run = await client.get(f"/api/runs/{completed['run_id']}")
        assert run.status == 200
        assert run.content_type == "application/json"

        artifact = await client.get(
            f"/api/runs/{completed['run_id']}/artifacts/plan/research-plan.md"
        )
        assert artifact.status == 200
        assert artifact.content_type == "text/markdown"
        assert "测试研究计划" in await artifact.text()

        script = await client.get("/static/app.js")
        assert script.status == 200
        assert script.content_type in {"application/javascript", "text/javascript"}
        stylesheet = await client.get("/static/styles.css")
        assert stylesheet.status == 200
        assert stylesheet.content_type == "text/css"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_local_api_runs_existing_loop_and_resumes_without_paid_provider(
    tmp_path: Path,
) -> None:
    runner = FakeDirectionRunner()
    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        vault_root=tmp_path / "vault",
        runner=runner,
        delivery_validator=_accept_fake_delivery,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created_response = await client.post(
            "/api/runs", json={"direction": "第一个科学问题", "dry_run": False}
        )
        assert created_response.status == 201
        created = await created_response.json()
        completed = await _wait_for_status(client, created["run_id"], "completed")

        assert len(runner.calls) == 1
        assert runner.calls[0]["resume_existing"] is False
        assert completed["stages"][0]["status"] == "completed"
        assert completed["stages"][0]["stage_name"] == "broad-literature-query"
        assert completed["stages"][1]["status"] == "pending"
        assert completed["stages"][1]["stage_name"] == "focus-selection"
        assert completed["stages"][-1]["ordinal"] == 12
        assert completed["delivery_validation"]["reference_count"] == 5
        paths = {artifact["relative_path"] for artifact in completed["artifacts"]}
        assert "literature/broad/direction-literature.json" in paths
        assert "plan/research-plan.md" in paths
        assert not any("provider-responses" in path for path in paths)
        assert "plan/_private/research-plan-source.json" not in paths
        categories = {
            artifact["relative_path"]: artifact["category"] for artifact in completed["artifacts"]
        }
        assert categories["plan/research-plan.json"] == "plan"
        assert categories["plan/research-plan.md"] == "plan"
        assert categories["system-authored-final-research-plan.json"] == "internal"
        assert categories["plan/research-plan-manifest.json"] == "internal"

        plan_response = await client.get(
            f"/api/runs/{created['run_id']}/artifacts/plan/research-plan.md"
        )
        assert plan_response.status == 200
        assert "测试研究计划" in await plan_response.text()

        private_response = await client.get(
            f"/api/runs/{created['run_id']}/artifacts/plan/_private/research-plan-source.json"
        )
        assert private_response.status == 404

        resumed_response = await client.post(f"/api/runs/{created['run_id']}/resume")
        assert resumed_response.status == 202
        resumed = await _wait_for_status(client, created["run_id"], "completed")
        assert resumed["resume_count"] == 1
        assert len(runner.calls) == 2
        assert runner.calls[1]["resume_existing"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_active_run_marks_first_incomplete_stage_as_running(tmp_path: Path) -> None:
    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        vault_root=tmp_path / "vault",
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created_response = await client.post(
            "/api/runs", json={"direction": "阶段状态测试", "dry_run": True}
        )
        created = await created_response.json()
        job = service._jobs[created["run_id"]]
        job["status"] = "running"
        output = Path(job["output_dir"])
        evidence = output / "literature" / "broad" / "direction-literature.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"source":"test"}\n', encoding="utf-8")
        record_completed_stage(
            root=output,
            ordinal=1,
            stage_name="broad-literature-query",
            stage_input_hash="a" * 64,
            artifacts=(evidence,),
        )

        response = await client.get(f"/api/runs/{created['run_id']}/stages")
        assert response.status == 200
        stages = (await response.json())["stages"]
        assert stages[0]["status"] == "completed"
        assert stages[1]["status"] == "running"
        assert stages[2]["status"] == "pending"
        assert sum(stage["status"] == "running" for stage in stages) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_never_marks_an_unvalidated_runner_result_completed(tmp_path: Path) -> None:
    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        runner=FakeDirectionRunner(),
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created = await (await client.post("/api/runs", json={"direction": "无效伪交付"})).json()

        failed = await _wait_for_status(client, created["run_id"], "failed")

        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "HumanDeliveryValidationError"
        assert "runner delivery report" in failed["error"]["message"]
        assert failed["delivery_validation"] is None
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("recommendation", ["major_revision", "reject", "unclear"])
async def test_api_never_marks_a_scientifically_blocked_result_completed(
    tmp_path: Path,
    recommendation: str,
) -> None:
    class ScientificallyBlockedRunner(FakeDirectionRunner):
        def __call__(self, **kwargs: Any) -> dict[str, Any]:
            result = super().__call__(**kwargs)
            result["independent_scientific_review"] = {
                "recommendation": recommendation,
            }
            return result

    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        runner=ScientificallyBlockedRunner(),
        delivery_validator=_accept_fake_delivery,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created = await (
            await client.post("/api/runs", json={"direction": "通用终审阻断测试"})
        ).json()
        failed = await _wait_for_status(client, created["run_id"], "failed")

        assert failed["error"]["type"] == "ResearchApiError"
        assert "scientific review" in failed["error"]["message"]
        assert failed["delivery_validation"] is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_accepts_explicit_minor_review_completion(tmp_path: Path) -> None:
    class MinorReviewRunner(FakeDirectionRunner):
        def __call__(self, **kwargs: Any) -> dict[str, Any]:
            result = super().__call__(**kwargs)
            result["status"] = "completed_with_minor_issues"
            result["independent_scientific_review"] = {
                "recommendation": "minor_revision",
            }
            return result

    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        runner=MinorReviewRunner(),
        delivery_validator=_accept_fake_delivery,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created = await (
            await client.post("/api/runs", json={"direction": "通用小修终审测试"})
        ).json()
        completed = await _wait_for_status(client, created["run_id"], "completed")

        assert completed["result"]["status"] == "completed_with_minor_issues"
        assert completed["result"]["independent_scientific_review"]["recommendation"] == (
            "minor_revision"
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_rejects_legacy_direction_delivery_even_with_permissive_validator(
    tmp_path: Path,
) -> None:
    class LegacyRunner(FakeDirectionRunner):
        def __call__(self, **kwargs: Any) -> dict[str, Any]:
            result = super().__call__(**kwargs)
            result["schema_version"] = "contest-direction-research-loop-delivery-v1"
            result.pop("literature_protocol")
            return result

    service = ResearchApiService(
        work_root=tmp_path / "api-runs",
        runner=LegacyRunner(),
        delivery_validator=_accept_fake_delivery,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created = await (await client.post("/api/runs", json={"direction": "旧链路"})).json()
        failed = await _wait_for_status(client, created["run_id"], "failed")
        assert failed["error"]["type"] == "ResearchApiError"
        assert "legacy or unknown direction delivery" in failed["error"]["message"]
        assert failed["delivery_validation"] is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_dry_run_and_batch_preview_make_zero_runner_calls(tmp_path: Path) -> None:
    runner = FakeDirectionRunner()
    service = ResearchApiService(work_root=tmp_path / "api", runner=runner)
    question_pdf = tmp_path / "questions.pdf"
    question_pdf.write_bytes(b"%PDF-1.4\n% test-only placeholder\n")
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        single_response = await client.post(
            "/api/runs", json={"direction": "只做输入预览", "dry_run": True}
        )
        assert single_response.status == 201
        single = await single_response.json()
        assert single["status"] == "dry_run"

        batch_response = await client.post(
            "/api/batches",
            json={
                "question_pdf": question_pdf.as_posix(),
                "start": 1,
                "limit": 2,
                "dry_run": True,
            },
        )
        assert batch_response.status == 201
        batch = await batch_response.json()
        assert batch["question_count"] == 2
        assert batch["provider_calls"] == 0
        assert runner.calls == []
        persisted_batch = await client.get(f"/api/batches/{batch['batch_id']}")
        assert persisted_batch.status == 200
        assert (await persisted_batch.json())["question_pdf"] == question_pdf.as_posix()
        batches = await (await client.get("/api/batches")).json()
        assert batches["batches"][0]["batch_id"] == batch["batch_id"]

        unavailable = await client.post(
            "/api/batches",
            json={"question_pdf": question_pdf.as_posix(), "dry_run": False},
        )
        assert unavailable.status == 503
        payload = await unavailable.json()
        assert "BatchRunService" in payload["message"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_configured_batch_service_retains_pdf_dry_run_semantics(
    tmp_path: Path,
) -> None:
    batch_service = FakeBatchService()
    question_pdf = tmp_path / "science125.pdf"
    question_pdf.write_bytes(b"%PDF-1.4\n")
    service = ResearchApiService(work_root=tmp_path / "api", batch_service=batch_service)
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        response = await client.post(
            "/api/batches",
            json={
                "question_pdf": question_pdf.as_posix(),
                "start": 1,
                "limit": 125,
                "dry_run": True,
            },
        )
        assert response.status == 201
        receipt = await response.json()
        assert receipt["status"] == "dry_run"
        assert receipt["dry_run"] is True
        assert receipt["question_count"] == 125
        assert batch_service.calls[0]["question_pdf"] == question_pdf.resolve()
        assert batch_service.calls[0]["dry_run"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_rejects_legacy_batch_service_report(tmp_path: Path) -> None:
    class LegacyBatchService(FakeBatchService):
        def submit_batch(self, **kwargs: Any) -> dict[str, Any]:
            result = super().submit_batch(**kwargs)
            result.pop("schema_version")
            result.pop("literature_protocol")
            return result

    question_pdf = tmp_path / "science125.pdf"
    question_pdf.write_bytes(b"%PDF-1.4\n")
    service = ResearchApiService(work_root=tmp_path / "api", batch_service=LegacyBatchService())
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        response = await client.post(
            "/api/batches",
            json={"question_pdf": question_pdf.as_posix(), "limit": 1, "dry_run": True},
        )
        assert response.status == 409
        assert "legacy or unknown Science125 batch report" in (await response.json())["message"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_frontend_health_and_read_only_evolution_status(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    candidate = vault / "exploration" / "skills" / "candidates" / "candidate-a.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "\n".join(
            [
                "# Candidate",
                "",
                "- Candidate skill ID: `candidate_a`",
                "- Parent skill: `parent_a`",
                "- Status: `shadow_evaluation`",
            ]
        ),
        encoding="utf-8",
    )
    service = ResearchApiService(
        work_root=tmp_path / "api", vault_root=vault, runner=FakeDirectionRunner()
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        index = await client.get("/")
        assert index.status == 200
        assert "研启智链 / AI-Researcher - 研究指挥中心" in await index.text()
        script = await client.get("/static/app.js")
        assert script.status == 200
        assert "/api/runs" in await script.text()
        health = await (await client.get("/api/health")).json()
        assert health["status"] == "ok"
        assert health["authentication_enabled"] is False
        assert health["self_evolution_execution_enabled"] is False

        created = await (
            await client.post("/api/runs", json={"direction": "预览", "dry_run": True})
        ).json()
        evolution_response = await client.get(f"/api/runs/{created['run_id']}/evolution")
        assert evolution_response.status == 200
        evolution = await evolution_response.json()
        assert evolution["mode"] == "query_only"
        assert evolution["promotion_authorized"] is False
        assert evolution["skill_candidates"][0]["candidate_status"] == "shadow_evaluation"
        assert evolution["skill_candidates"][0]["promotion_authorized"] is False

        blocked_start = await client.post(f"/api/runs/{created['run_id']}/evolution")
        assert blocked_start.status == 409

        traversal = await client.get(f"/api/runs/{created['run_id']}/artifacts/%2e%2e/api-run.json")
        assert traversal.status == 404
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_completed_run_can_invoke_injected_frozen_evolution_once(
    tmp_path: Path,
) -> None:
    evolution_service = FakeEvolutionService()
    service = ResearchApiService(
        work_root=tmp_path / "api",
        runner=FakeDirectionRunner(),
        delivery_validator=_accept_fake_delivery,
        evolution_service=evolution_service,
    )
    client = TestClient(TestServer(create_app(service=service)))
    await client.start_server()
    try:
        created = await (
            await client.post("/api/runs", json={"direction": "完成后提炼经验"})
        ).json()
        await _wait_for_status(client, created["run_id"], "completed")

        response = await client.post(f"/api/runs/{created['run_id']}/evolution")
        assert response.status == 201
        receipt = await response.json()
        assert receipt["result"]["status"] == "shadow_validated"
        assert receipt["promotion_authorized"] is False
        assert len(evolution_service.calls) == 1
        assert evolution_service.calls[0]["run_id"] == created["run_id"]

        replay = await client.post(f"/api/runs/{created['run_id']}/evolution")
        assert replay.status == 201
        assert await replay.json() == receipt
        assert len(evolution_service.calls) == 1
    finally:
        await client.close()


def test_process_restart_marks_nonterminal_job_interrupted(tmp_path: Path) -> None:
    work_root = tmp_path / "api"
    run_id = "run-20260813t0000-abcdef1234567890"
    manifest = work_root / run_id / "api-run.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "autoresearch-api-run-v1",
                "run_id": run_id,
                "kind": "single",
                "direction": "恢复测试",
                "status": "running",
                "dry_run": False,
                "output_dir": (manifest.parent / "delivery").as_posix(),
                "created_at": "2026-08-13T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = ResearchApiService(work_root=work_root, runner=FakeDirectionRunner())

    loaded = service.get_run(run_id)
    assert loaded["status"] == "interrupted"
    assert loaded["error"]["type"] == "ApiProcessRestart"


def test_process_restart_downgrades_legacy_completed_job(tmp_path: Path) -> None:
    work_root = tmp_path / "api"
    run_id = "run-20260813t0000-fedcba9876543210"
    manifest = work_root / run_id / "api-run.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "autoresearch-api-run-v1",
                "run_id": run_id,
                "kind": "single",
                "direction": "旧完成态",
                "status": "completed",
                "dry_run": False,
                "output_dir": (manifest.parent / "delivery").as_posix(),
                "created_at": "2026-08-13T00:00:00+00:00",
                "result": {
                    "schema_version": "contest-direction-research-loop-delivery-v1",
                    "status": "completed",
                },
                "delivery_validation": {"reference_count": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = ResearchApiService(work_root=work_root, runner=FakeDirectionRunner())

    loaded = service.get_run(run_id)
    assert loaded["status"] == "failed"
    assert loaded["error"]["type"] == "LegacyDeliveryContract"
    assert loaded["delivery_validation"] is None


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
def test_unauthenticated_api_accepts_only_loopback_hosts(host: str) -> None:
    _validate_bind_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.2", "example.com"])
def test_unauthenticated_api_rejects_nonlocal_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        _validate_bind_host(host)
