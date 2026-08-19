"""aiohttp REST API and local Chinese web UI for AutoResearch."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic import ValidationError

from autoresearch.api.adapters import (
    ContestDirectionSkillEvolutionAdapter,
    Science125BatchAdapter,
)
from autoresearch.api.research_service import (
    BatchCreateRequest,
    ResearchApiError,
    ResearchApiService,
    RunCreateRequest,
)

_logger = logging.getLogger(__name__)

SERVICE_KEY: web.AppKey[ResearchApiService] = web.AppKey(
    "autoresearch_service", ResearchApiService
)
# The functional console lives at the repository-root ``web/`` folder so the
# UI can be edited and served from one canonical location.  The packaged
# ``static`` copy remains the fallback for non-repository deployments.
_REPO_WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
_STATIC_ROOT = (
    _REPO_WEB_ROOT if (_REPO_WEB_ROOT / "index.html").is_file() else Path(__file__).with_name("static")
)


def create_app(*, service: ResearchApiService | None = None) -> web.Application:
    """Build the local application; dependency injection keeps tests provider-free."""

    app = web.Application(client_max_size=2 * 1024 * 1024)
    app[SERVICE_KEY] = service or ResearchApiService()
    app.add_routes(
        [
            web.get("/", _index),
            web.get("/static/{name}", _static_asset),
            web.get("/api/health", _health),
            web.get("/api/runs", _list_runs),
            web.post("/api/runs", _create_run),
            web.post("/api/batches", _create_batch),
            web.get("/api/batches", _list_batches),
            web.get("/api/batches/{batch_id}", _get_batch),
            web.get("/api/runs/{run_id}", _get_run),
            web.get("/api/runs/{run_id}/stages", _get_stages),
            web.get("/api/runs/{run_id}/artifacts", _get_artifacts),
            web.get("/api/runs/{run_id}/skills", _get_skills),
            web.get("/api/runs/{run_id}/evolution", _get_evolution),
            web.post("/api/runs/{run_id}/evolution", _start_evolution),
            web.post("/api/runs/{run_id}/resume", _resume_run),
            web.post("/api/runs/{run_id}/cancel", _cancel_run),
            web.get("/api/skills/candidates", _skill_candidates),
            web.get("/api/runs/{run_id}/artifacts/{tail:.*}", _download_artifact),
        ]
    )
    app.on_cleanup.append(_cleanup)
    return app


async def _index(_request: web.Request) -> web.StreamResponse:
    return web.FileResponse(_STATIC_ROOT / "index.html")


async def _static_asset(request: web.Request) -> web.StreamResponse:
    name = request.match_info["name"]
    if name not in {"app.js", "styles.css"}:
        raise web.HTTPNotFound()
    return web.FileResponse(_STATIC_ROOT / name)


async def _health(request: web.Request) -> web.Response:
    service = request.app[SERVICE_KEY]
    return web.json_response(
        {
            "status": "ok",
            "service": "autoresearch-local-api",
            "deployment_scope": "local_single_user",
            "authentication_enabled": False,
            "formal_experiment_enabled": False,
            "result_paper_enabled": False,
            "self_evolution_execution_enabled": service.evolution_service is not None,
            "self_evolution_service_configured": service.evolution_service is not None,
            "automatic_skill_activation_enabled": False,
            "batch_execution_configured": service.batch_service is not None,
        }
    )


async def _list_runs(request: web.Request) -> web.Response:
    return web.json_response({"runs": request.app[SERVICE_KEY].list_runs()})


async def _create_run(request: web.Request) -> web.Response:
    try:
        payload = RunCreateRequest.model_validate(await request.json())
        result = await request.app[SERVICE_KEY].create_run(payload)
    except ValidationError as exc:
        return _validation_error(exc)
    except json.JSONDecodeError as exc:
        return web.json_response(
            {"error": "invalid_json", "message": str(exc)}, status=400
        )
    except (ValueError, ResearchApiError) as exc:
        return _service_error(exc)
    except Exception as exc:  # unexpected: surface a real message, never a bare 500
        _logger.exception("unexpected error while creating a run")
        return _service_error(exc)
    return web.json_response(result, status=201)


async def _create_batch(request: web.Request) -> web.Response:
    try:
        payload = BatchCreateRequest.model_validate(await request.json())
        result = await request.app[SERVICE_KEY].create_batch(payload)
    except ValidationError as exc:
        return _validation_error(exc)
    except json.JSONDecodeError as exc:
        return web.json_response(
            {"error": "invalid_json", "message": str(exc)}, status=400
        )
    except (ValueError, ResearchApiError) as exc:
        return _service_error(exc, unavailable="unavailable" in str(exc).casefold())
    except Exception as exc:  # unexpected: surface a real message, never a bare 500
        _logger.exception("unexpected error while creating a batch")
        return _service_error(exc)
    return web.json_response(result, status=201)


async def _list_batches(request: web.Request) -> web.Response:
    return web.json_response({"batches": request.app[SERVICE_KEY].list_batches()})


async def _get_batch(request: web.Request) -> web.Response:
    try:
        result = request.app[SERVICE_KEY].get_batch(request.match_info["batch_id"])
    except ResearchApiError as exc:
        return _service_error(exc, not_found="not found" in str(exc).casefold())
    return web.json_response(result)


async def _get_run(request: web.Request) -> web.Response:
    return _read_response(request, "run")


async def _get_stages(request: web.Request) -> web.Response:
    return _read_response(request, "stages")


async def _get_artifacts(request: web.Request) -> web.Response:
    return _read_response(request, "artifacts")


async def _get_skills(request: web.Request) -> web.Response:
    return _read_response(request, "skills")


async def _get_evolution(request: web.Request) -> web.Response:
    return _read_response(request, "evolution")


async def _start_evolution(request: web.Request) -> web.Response:
    try:
        result = await request.app[SERVICE_KEY].start_evolution(
            request.match_info["run_id"]
        )
    except ResearchApiError as exc:
        return _service_error(
            exc,
            unavailable="unavailable" in str(exc).casefold(),
            not_found="not found" in str(exc).casefold(),
        )
    return web.json_response(result, status=201)


def _read_response(request: web.Request, kind: str) -> web.Response:
    service = request.app[SERVICE_KEY]
    run_id = request.match_info["run_id"]
    try:
        if kind == "run":
            payload: Any = service.get_run(run_id)
        elif kind == "stages":
            payload = {"run_id": run_id, "stages": service.stage_status(run_id)}
        elif kind == "artifacts":
            payload = {"run_id": run_id, "artifacts": service.artifacts(run_id)}
        elif kind == "skills":
            payload = service.selected_skills(run_id)
        else:
            payload = service.evolution_status(run_id)
    except ResearchApiError as exc:
        return _service_error(exc, not_found="not found" in str(exc).casefold())
    return web.json_response(payload)


async def _resume_run(request: web.Request) -> web.Response:
    try:
        result = await request.app[SERVICE_KEY].resume_run(request.match_info["run_id"])
    except ResearchApiError as exc:
        return _service_error(exc, not_found="not found" in str(exc).casefold())
    return web.json_response(result, status=202)


async def _cancel_run(request: web.Request) -> web.Response:
    try:
        result = await request.app[SERVICE_KEY].cancel_run(request.match_info["run_id"])
    except ResearchApiError as exc:
        return _service_error(exc, not_found="not found" in str(exc).casefold())
    return web.json_response(result, status=202)


async def _skill_candidates(request: web.Request) -> web.Response:
    service = request.app[SERVICE_KEY]
    return web.json_response(
        {
            "candidates": service.skill_candidates(),
            "promotion_authorized": False,
            "mode": "query_only",
        }
    )


async def _download_artifact(request: web.Request) -> web.StreamResponse:
    service = request.app[SERVICE_KEY]
    try:
        path = service.artifact_path(
            request.match_info["run_id"], request.match_info.get("tail", "")
        )
    except ResearchApiError as exc:
        return _service_error(exc, not_found=True)
    response = web.FileResponse(path)
    response.headers["Content-Disposition"] = f'inline; filename="{path.name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


async def _cleanup(app: web.Application) -> None:
    await app[SERVICE_KEY].close()


def _validation_error(exc: ValidationError) -> web.Response:
    return web.json_response(
        {"error": "validation_error", "details": json.loads(exc.json(include_url=False))},
        status=422,
    )


def _service_error(
    exc: Exception, *, unavailable: bool = False, not_found: bool = False
) -> web.Response:
    status = 404 if not_found else 503 if unavailable else 409
    return web.json_response(
        {"error": "not_found" if not_found else "service_error", "message": str(exc)},
        status=status,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AutoResearch local API and web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--work-root", type=Path, default=Path("runs/research-api"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--vault-root", type=Path, default=Path("autoresearch-vault"))
    parser.add_argument("--skills-root", type=Path, default=Path("skills"))
    args = parser.parse_args(argv)
    try:
        _validate_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    service = ResearchApiService(
        work_root=args.work_root,
        config_path=args.config,
        env_path=args.env,
        vault_root=args.vault_root,
        batch_service=Science125BatchAdapter(skills_root=args.skills_root),
        evolution_service=ContestDirectionSkillEvolutionAdapter(
            skills_root=args.skills_root
        ),
    )
    web.run_app(create_app(service=service), host=args.host, port=args.port)
    return 0


def _validate_bind_host(host: str) -> None:
    if host.casefold() not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("the unauthenticated local API may bind only to a loopback host")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["SERVICE_KEY", "create_app", "main"]
