"""Provider-neutral application service for direction research runs.

This module is deliberately a thin boundary around the existing competition
direction loop.  It owns API job metadata and background scheduling, but it does
not duplicate literature, Skill routing, pilot, memory, checkpoint, or plan
logic.  A batch implementation can be injected through ``BatchRunService``;
until one is configured, batch dry-runs remain available while paid batch
execution fails explicitly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autoresearch.competition.contest_direction_research_loop_cli import (
    run_contest_direction_research_loop,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    ContestDirectionStageCheckpointError,
    load_completed_stage,
)
from autoresearch.competition.contest_human_delivery_validator import (
    HumanDeliveryValidationReport,
    validate_runner_human_delivery,
)

RunStatus = Literal[
    "dry_run",
    "queued",
    "running",
    "cancel_requested",
    "canceled",
    "completed",
    "failed",
    "interrupted",
]

STAGES: tuple[tuple[int, str, str], ...] = (
    (1, "broad-literature-query", "原始问题广泛真实检索"),
    (2, "focus-selection", "证据约束的研究方向选择"),
    (3, "targeted-literature-query", "聚焦方向定向真实检索"),
    (4, "planning-literature-lock", "合并核验与五至十篇文献锁定"),
    (5, "skill-routing", "文献后 Skill 路由"),
    (6, "hypothesis-brainstorm", "候选假设构思"),
    (7, "provisional-plan", "内部候选计划"),
    (8, "real-pilot", "真实预实验"),
    (9, "postpilot-objective-review", "预实验后目标评审"),
    (10, "final-plan-revision", "研究计划修订"),
    (11, "render-plan", "计划制品渲染"),
    (12, "independent-scientific-review", "独立科学评审"),
)

_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,80}$")
_SAFE_ARTIFACT_SUFFIXES = frozenset(
    {".csv", ".json", ".log", ".md", ".pdf", ".tex", ".txt", ".yaml", ".yml"}
)
_PRIVATE_PARTS = frozenset(
    {
        ".git",
        ".private",
        "_private",
        "context-memory",
        "provider-responses",
        "raw-memory",
        "responses",
    }
)
_HUMAN_PLAN_FILENAMES = frozenset(
    {"research-plan.json", "research-plan.md", "research-plan.tex", "research-plan.pdf"}
)
_TWO_STAGE_LITERATURE_PROTOCOL = "two_stage_literature_v4"
_DIRECTION_DELIVERY_SCHEMA = "contest-direction-research-loop-delivery-v2"
_BATCH_REPORT_SCHEMA = "science125-batch-report-v2"


class ResearchApiError(RuntimeError):
    """Raised when an API service operation is invalid or unavailable."""


class RunCreateRequest(BaseModel):
    """One direction-loop request. Provider credentials remain in config/env files."""

    model_config = ConfigDict(extra="forbid")

    direction: str = Field(min_length=1, max_length=20_000)
    dry_run: bool = False
    preexperiment_policy: Literal["required", "if_supported"] = "if_supported"
    dreaming_recall_enabled: bool = True

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("direction must not be blank")
        return normalized


class BatchCreateRequest(BaseModel):
    """Batch request consumed by a stable injected batch service."""

    model_config = ConfigDict(extra="forbid")

    question_pdf: str = Field(min_length=1, max_length=4_096)
    start: int = Field(default=1, ge=1, le=125)
    limit: int = Field(default=125, ge=1, le=125)
    include_question_ids: list[int] = Field(default_factory=list, max_length=125)
    resume: bool = False
    dry_run: bool = True
    preexperiment_policy: Literal["required", "plan_only_on_unsupported"] = (
        "plan_only_on_unsupported"
    )
    dreaming_recall_enabled: bool = True

    @field_validator("question_pdf")
    @classmethod
    def normalize_pdf(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question_pdf must not be blank")
        return normalized

    @field_validator("include_question_ids")
    @classmethod
    def normalize_question_ids(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 125 for value in values):
            raise ValueError("question IDs must be between 1 and 125")
        if len(values) != len(set(values)):
            raise ValueError("question IDs must be unique")
        return sorted(values)


class BatchRunService(Protocol):
    """Stable seam for the separately owned 125-question batch scheduler."""

    def submit_batch(
        self,
        *,
        question_pdf: Path,
        output_root: Path,
        start: int,
        limit: int,
        include_question_ids: Sequence[int],
        resume: bool,
        dry_run: bool,
        config_path: Path,
        env_path: Path,
        preexperiment_policy: str,
        dreaming_recall_enabled: bool,
    ) -> Mapping[str, Any]:
        """Submit one non-dry batch and return its durable service receipt."""


class SkillEvolutionService(Protocol):
    """Frozen seam for evidence-to-Skill candidate extraction and validation."""

    def evolve_run(
        self,
        *,
        run_id: str,
        delivery_root: Path,
        vault_root: Path,
        config_path: Path,
        env_path: Path,
    ) -> Mapping[str, Any]:
        """Create/validate a shadow candidate without promoting production Skills."""


DirectionRunner = Callable[..., Mapping[str, Any]]
HumanDeliveryValidator = Callable[..., HumanDeliveryValidationReport | Mapping[str, Any]]


class ResearchApiService:
    """Persisted local job registry and dependency-injected loop scheduler."""

    def __init__(
        self,
        *,
        work_root: Path | str = Path("runs/research-api"),
        config_path: Path | str = Path("config.yaml"),
        env_path: Path | str = Path(".env"),
        vault_root: Path | str = Path("autoresearch-vault"),
        runner: DirectionRunner = run_contest_direction_research_loop,
        delivery_validator: HumanDeliveryValidator = validate_runner_human_delivery,
        batch_service: BatchRunService | None = None,
        evolution_service: SkillEvolutionService | None = None,
    ) -> None:
        self.work_root = Path(work_root).expanduser().resolve()
        self.config_path = Path(config_path).expanduser().resolve()
        self.env_path = Path(env_path).expanduser().resolve()
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.runner = runner
        self.delivery_validator = delivery_validator
        self.batch_service = batch_service
        self.evolution_service = evolution_service
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._load_existing_jobs()

    async def create_run(self, request: RunCreateRequest) -> dict[str, Any]:
        """Create a dry-run preview or schedule one real direction loop."""

        async with self._lock:
            run_id = self._new_id("run", {"direction": request.direction})
            run_root = self.work_root / run_id
            output_dir = run_root / "delivery"
            run_root.mkdir(parents=True, exist_ok=False)
            now = _utc_now()
            job: dict[str, Any] = {
                "schema_version": "autoresearch-api-run-v1",
                "run_id": run_id,
                "kind": "single",
                "direction": request.direction,
                "status": "dry_run" if request.dry_run else "queued",
                "dry_run": request.dry_run,
                "preexperiment_policy": request.preexperiment_policy,
                "dreaming_recall_enabled": request.dreaming_recall_enabled,
                "output_dir": output_dir.as_posix(),
                "created_at": now,
                "started_at": None,
                "finished_at": now if request.dry_run else None,
                "resume_count": 0,
                "cancel_requested": False,
                "error": None,
                "result": None,
                "delivery_validation": None,
                "execution_boundary": {
                    "formal_experiment_enabled": False,
                    "result_paper_enabled": False,
                    "self_evolution_execution_enabled": False,
                    "api_owns_scientific_logic": False,
                },
            }
            self._jobs[run_id] = job
            self._write_job(job)
            if not request.dry_run:
                self._tasks[run_id] = asyncio.create_task(
                    self._execute(run_id, resume_existing=False),
                    name=f"research-api-{run_id}",
                )
            return self._public_job(job)

    async def create_batch(self, request: BatchCreateRequest) -> dict[str, Any]:
        """Preview a batch or delegate non-dry execution to the injected service."""

        question_pdf = Path(request.question_pdf).expanduser().resolve()
        if not question_pdf.is_file() or question_pdf.suffix.casefold() != ".pdf":
            raise ResearchApiError("question_pdf must be an existing local PDF file")
        batch_id = self._new_id(
            "batch",
            {
                "question_pdf": question_pdf.as_posix(),
                "start": request.start,
                "limit": request.limit,
                "include_question_ids": request.include_question_ids,
            },
        )
        batch_root = self.work_root / "batches" / batch_id
        if self.batch_service is None and not request.dry_run:
            raise ResearchApiError(
                "non-dry batch execution is unavailable until a BatchRunService is configured"
            )
        batch_root.mkdir(parents=True, exist_ok=False)
        if self.batch_service is None:
            receipt: dict[str, Any] = {
                "schema_version": "autoresearch-api-batch-preview-v1",
                "batch_id": batch_id,
                "status": "dry_run",
                "dry_run": True,
                "question_pdf": question_pdf.as_posix(),
                "start": request.start,
                "limit": request.limit,
                "include_question_ids": request.include_question_ids,
                "question_count": (
                    len(request.include_question_ids)
                    if request.include_question_ids
                    else request.limit
                ),
                "items": [],
                "batch_service_configured": False,
                "provider_calls": 0,
                "created_at": _utc_now(),
            }
            _atomic_json(batch_root / "batch.json", receipt)
            return receipt
        result = await asyncio.to_thread(
            self.batch_service.submit_batch,
            question_pdf=question_pdf,
            output_root=batch_root,
            start=request.start,
            limit=request.limit,
            include_question_ids=tuple(request.include_question_ids),
            resume=request.resume,
            dry_run=request.dry_run,
            config_path=self.config_path,
            env_path=self.env_path,
            preexperiment_policy=request.preexperiment_policy,
            dreaming_recall_enabled=request.dreaming_recall_enabled,
        )
        _validate_current_batch_result(result, dry_run=request.dry_run)
        receipt = {
            "schema_version": "autoresearch-api-batch-submission-v1",
            "batch_id": batch_id,
            "status": str(result.get("status") or "submitted"),
            "dry_run": request.dry_run,
            "question_count": int(
                result.get("question_count") or len(request.include_question_ids) or request.limit
            ),
            "batch_service_receipt": dict(result),
            "created_at": _utc_now(),
        }
        _atomic_json(batch_root / "batch.json", receipt)
        return receipt

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        """Resume the existing checkpoint directory from its first missing stage."""

        async with self._lock:
            job = self._required_job(run_id)
            if job["status"] in {"queued", "running", "cancel_requested"}:
                raise ResearchApiError(f"run cannot resume while status is {job['status']}")
            if job["status"] == "dry_run":
                raise ResearchApiError("a dry-run preview has no checkpoint to resume")
            job["status"] = "queued"
            job["cancel_requested"] = False
            job["error"] = None
            job["finished_at"] = None
            job["delivery_validation"] = None
            job["resume_count"] = int(job.get("resume_count", 0)) + 1
            self._write_job(job)
            has_checkpoint = (Path(job["output_dir"]) / "direction-input.json").is_file()
            self._tasks[run_id] = asyncio.create_task(
                self._execute(run_id, resume_existing=has_checkpoint),
                name=f"research-api-resume-{run_id}",
            )
            return self._public_job(job)

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Cancel a queued job or request cooperative stop for a running sync loop."""

        async with self._lock:
            job = self._required_job(run_id)
            status = str(job["status"])
            if status == "queued":
                job["status"] = "canceled"
                job["cancel_requested"] = True
                job["finished_at"] = _utc_now()
            elif status == "running":
                job["status"] = "cancel_requested"
                job["cancel_requested"] = True
            elif status == "cancel_requested":
                pass
            else:
                raise ResearchApiError(f"run cannot be canceled while status is {status}")
            self._write_job(job)
            response = self._public_job(job)
            response["cancellation_boundary"] = (
                "The current direction loop is synchronous and has no cooperative cancellation "
                "hook. A running worker is not killed; its checkpoints remain resumable, and a "
                "completed scientific result is retained."
            )
            return response

    def list_runs(self) -> list[dict[str, Any]]:
        return [
            self._public_job(job)
            for job in sorted(
                self._jobs.values(), key=lambda item: str(item["created_at"]), reverse=True
            )
        ]

    def list_batches(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        batches_root = self.work_root / "batches"
        if not batches_root.is_dir():
            return rows
        for path in sorted(batches_root.glob("batch-*/batch.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(batch_id) or not batch_id.startswith("batch-"):
            raise ResearchApiError("invalid batch id")
        path = self.work_root / "batches" / batch_id / "batch.json"
        if not path.is_file():
            raise ResearchApiError("batch not found")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchApiError("batch receipt is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("batch_id") != batch_id:
            raise ResearchApiError("batch receipt identity is invalid")
        return payload

    def get_run(self, run_id: str) -> dict[str, Any]:
        job = self._required_job(run_id)
        response = self._public_job(job)
        response["stages"] = self.stage_status(run_id)
        response["artifacts"] = self.artifacts(run_id)
        return response

    def stage_status(self, run_id: str) -> list[dict[str, Any]]:
        job = self._required_job(run_id)
        checkpoint_root = Path(job["output_dir"]) / "checkpoints" / "completed-stages"
        completed: dict[tuple[int, str], Mapping[str, Any]] = {}
        invalid: set[tuple[int, str]] = set()
        if checkpoint_root.is_dir():
            for path in sorted(checkpoint_root.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("schema_version") != "contest-direction-stage-checkpoint-v1":
                    continue
                ordinal = payload.get("ordinal")
                name = payload.get("stage_name")
                if isinstance(ordinal, int) and isinstance(name, str):
                    input_hash = payload.get("stage_input_hash")
                    if not isinstance(input_hash, str):
                        invalid.add((ordinal, name))
                        continue
                    try:
                        verified = load_completed_stage(
                            root=Path(job["output_dir"]),
                            ordinal=ordinal,
                            stage_name=name,
                            stage_input_hash=input_hash,
                        )
                    except ContestDirectionStageCheckpointError:
                        invalid.add((ordinal, name))
                        continue
                    if verified is not None:
                        completed[(ordinal, name)] = verified
        rows: list[dict[str, Any]] = []
        for ordinal, name, label in STAGES:
            receipt = completed.get((ordinal, name))
            rows.append(
                {
                    "ordinal": ordinal,
                    "stage_name": name,
                    "label_zh": label,
                    "status": (
                        "completed"
                        if receipt is not None
                        else "invalid"
                        if (ordinal, name) in invalid
                        else "pending"
                    ),
                    "artifact_count": (
                        len(receipt.get("artifacts", [])) if receipt is not None else 0
                    ),
                    "checkpoint_hash": (
                        receipt.get("checkpoint_hash") if receipt is not None else None
                    ),
                }
            )
        return rows

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        job = self._required_job(run_id)
        output_dir = Path(job["output_dir"]).resolve()
        if not output_dir.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(output_dir.rglob("*")):
            if not self._is_public_artifact(output_dir, path):
                continue
            try:
                relative = path.relative_to(output_dir).as_posix()
                binding = {
                    "relative_path": relative,
                    "category": _artifact_category(relative),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                    "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "url": f"/api/runs/{run_id}/artifacts/{relative}",
                }
            except OSError:
                # A live log can be rotated between discovery and hashing.
                continue
            rows.append(binding)
            if len(rows) >= 500:
                break
        return rows

    def artifact_path(self, run_id: str, relative_path: str) -> Path:
        job = self._required_job(run_id)
        output_dir = Path(job["output_dir"]).resolve()
        candidate = (output_dir / relative_path).resolve()
        try:
            candidate.relative_to(output_dir)
        except ValueError as exc:
            raise ResearchApiError("artifact path escapes the run output directory") from exc
        if not self._is_public_artifact(output_dir, candidate):
            raise ResearchApiError("artifact is unavailable or private")
        return candidate

    def selected_skills(self, run_id: str) -> dict[str, Any]:
        job = self._required_job(run_id)
        output_dir = Path(job["output_dir"])
        for name in ("selected-method-skills.json", "skill-routing.json"):
            path = output_dir / name
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                return {
                    "run_id": run_id,
                    "source_artifact": name,
                    "selection": payload,
                    "skill_content_is_scientific_evidence": False,
                }
        return {
            "run_id": run_id,
            "source_artifact": None,
            "selection": None,
            "skill_content_is_scientific_evidence": False,
        }

    def skill_candidates(self) -> list[dict[str, Any]]:
        """Report candidate/shadow state without promoting or editing any Skill."""

        candidates_root = self.vault_root / "exploration" / "skills" / "candidates"
        rows: list[dict[str, Any]] = []
        if not candidates_root.is_dir():
            return rows
        for path in sorted(candidates_root.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")[:262_144]
            except OSError:
                continue
            candidate_id = _markdown_value(content, "Candidate skill ID") or path.stem
            rows.append(
                {
                    "candidate_skill_id": candidate_id,
                    "parent_skill": _markdown_value(content, "Parent skill"),
                    "candidate_status": _markdown_value(content, "Status") or "unknown",
                    "relative_path": path.relative_to(self.vault_root).as_posix(),
                    "promotion_authorized": False,
                    "promotion_boundary": (
                        "A candidate or polish audit is shadow evidence only; this API never "
                        "promotes or overwrites a Skill."
                    ),
                }
            )
        return rows

    def evolution_status(self, run_id: str) -> dict[str, Any]:
        job = self._required_job(run_id)
        receipt_path = Path(job["output_dir"]).parent / "evolution" / "api-receipt.json"
        receipt: Mapping[str, Any] | None = None
        if receipt_path.is_file():
            try:
                loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, Mapping):
                receipt = loaded
        return {
            "run_id": run_id,
            "execution_enabled": self.evolution_service is not None,
            "mode": "frozen_service_available" if self.evolution_service else "query_only",
            "selected_skills": self.selected_skills(run_id),
            "skill_candidates": self.skill_candidates(),
            "run_evolution_receipt": receipt,
            "promotion_authorized": False,
            "boundary": (
                "Skill extraction, shadow validation, and promotion are owned by the evolution "
                "service. This endpoint only exposes persisted state."
            ),
        }

    async def start_evolution(self, run_id: str) -> dict[str, Any]:
        """Invoke the injected frozen evolution entrypoint for one completed run."""

        job = self._required_job(run_id)
        if job["status"] != "completed":
            raise ResearchApiError("Skill evolution requires a completed research run")
        if self.evolution_service is None:
            raise ResearchApiError(
                "Skill evolution execution is unavailable until a SkillEvolutionService "
                "is configured"
            )
        receipt_path = Path(job["output_dir"]).parent / "evolution" / "api-receipt.json"
        if receipt_path.is_file():
            try:
                existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ResearchApiError("existing evolution receipt is unreadable") from exc
            if not isinstance(existing, dict) or existing.get("run_id") != run_id:
                raise ResearchApiError("existing evolution receipt identity is invalid")
            return existing
        result = await asyncio.to_thread(
            self.evolution_service.evolve_run,
            run_id=run_id,
            delivery_root=Path(job["output_dir"]),
            vault_root=self.vault_root,
            config_path=self.config_path,
            env_path=self.env_path,
        )
        receipt: dict[str, Any] = {
            "schema_version": "autoresearch-api-skill-evolution-receipt-v1",
            "run_id": run_id,
            "status": str(result.get("status") or "completed"),
            "result": dict(result),
            "promotion_authorized": False,
            "created_at": _utc_now(),
        }
        _atomic_json(receipt_path, receipt)
        return receipt

    async def close(self) -> None:
        pending = [task for task in self._tasks.values() if not task.done()]
        if pending:
            await asyncio.wait(pending, timeout=1.0)

    async def _execute(self, run_id: str, *, resume_existing: bool) -> None:
        async with self._lock:
            job = self._required_job(run_id)
            if job["status"] == "canceled":
                return
            job["status"] = "running"
            job["started_at"] = _utc_now()
            job["delivery_validation"] = None
            self._write_job(job)
            kwargs = {
                "direction": job["direction"],
                "output_dir": Path(job["output_dir"]),
                "resume_existing": resume_existing,
                "preexperiment_policy": job["preexperiment_policy"],
                "config_path": self.config_path,
                "env_path": self.env_path,
                "context_vault_root": self.vault_root,
                "dreaming_recall_enabled": job["dreaming_recall_enabled"],
            }
        try:
            result = await asyncio.to_thread(self.runner, **kwargs)
            _validate_current_direction_result(result)
            validation = await asyncio.to_thread(
                self.delivery_validator,
                output_dir=Path(kwargs["output_dir"]),
                result=result,
            )
        except Exception as exc:
            async with self._lock:
                job = self._required_job(run_id)
                job["status"] = "failed"
                job["error"] = {"type": type(exc).__name__, "message": str(exc)[:4_000]}
                job["delivery_validation"] = None
                job["finished_at"] = _utc_now()
                self._write_job(job)
            return
        async with self._lock:
            job = self._required_job(run_id)
            job["status"] = "completed"
            job["result"] = _json_safe(dict(result))
            job["delivery_validation"] = _json_safe(
                validation.to_dict()
                if isinstance(validation, HumanDeliveryValidationReport)
                else dict(validation)
            )
            job["finished_at"] = _utc_now()
            self._write_job(job)

    def _required_job(self, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ResearchApiError("invalid run id")
        job = self._jobs.get(run_id)
        if job is None:
            raise ResearchApiError("run not found")
        return job

    def _new_id(self, prefix: str, payload: Mapping[str, Any]) -> str:
        created = _utc_now()
        seed = json.dumps(
            {"created_at": created, "payload": payload, "process": os.getpid()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        compact_time = created.replace("-", "").replace(":", "").replace(".", "")[:15]
        return f"{prefix}-{compact_time.lower()}-{digest}"

    def _write_job(self, job: Mapping[str, Any]) -> None:
        run_id = str(job["run_id"])
        _atomic_json(self.work_root / run_id / "api-run.json", job)

    def _load_existing_jobs(self) -> None:
        for path in sorted(self.work_root.glob("run-*/api-run.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = payload.get("run_id")
            if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
                continue
            if payload.get("status") == "completed":
                result = payload.get("result")
                try:
                    if not isinstance(result, Mapping):
                        raise ResearchApiError("completed API job has no runner result")
                    _validate_current_direction_result(result)
                except ResearchApiError as exc:
                    payload["status"] = "failed"
                    payload["error"] = {
                        "type": "LegacyDeliveryContract",
                        "message": str(exc),
                    }
                    payload["delivery_validation"] = None
                    payload["finished_at"] = _utc_now()
                    _atomic_json(path, payload)
            if payload.get("status") in {"queued", "running", "cancel_requested"}:
                payload["status"] = "interrupted"
                payload["error"] = {
                    "type": "ApiProcessRestart",
                    "message": "API process stopped before terminal status; use resume.",
                }
                payload["finished_at"] = _utc_now()
                _atomic_json(path, payload)
            self._jobs[run_id] = payload

    @staticmethod
    def _public_job(job: Mapping[str, Any]) -> dict[str, Any]:
        public = _json_safe(dict(job))
        if not isinstance(public, dict):  # pragma: no cover - dict input is preserved
            raise ResearchApiError("internal job serialization failed")
        return public

    @staticmethod
    def _is_public_artifact(output_dir: Path, path: Path) -> bool:
        if not path.is_file() or path.suffix.casefold() not in _SAFE_ARTIFACT_SUFFIXES:
            return False
        try:
            relative = path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            return False
        # v3 stores this sidecar under ``_private``.  Refuse the legacy
        # top-level spelling as well so an older run cannot expose model
        # receipts, local paths, hashes, or retrieval internals through the API.
        if relative.name.casefold() == "research-plan-source.json":
            return False
        return not any(part.startswith(".") or part in _PRIVATE_PARTS for part in relative.parts)


def _artifact_category(relative_path: str) -> str:
    lowered = relative_path.casefold()
    if "evolution" in lowered or "skill-candidate" in lowered or "skill_polish" in lowered:
        return "evolution"
    if "review" in lowered:
        return "review"
    if _is_human_plan_artifact(relative_path):
        return "plan"
    if any(
        token in lowered
        for token in (
            "system-authored",
            "revised-research-plan",
            "research-plan-manifest",
            "presentation-render-audit",
        )
    ):
        return "internal"
    if any(
        token in lowered
        for token in ("literature", "preexperiment", "pilot", "metrics", "evidence")
    ):
        return "evidence"
    if "checkpoint" in lowered or "memory" in lowered:
        return "runtime"
    return "other"


def _is_human_plan_artifact(relative_path: str) -> bool:
    parts = tuple(part.casefold() for part in relative_path.replace("\\", "/").split("/") if part)
    if len(parts) < 2 or parts[-1] not in _HUMAN_PLAN_FILENAMES:
        return False
    parent = parts[-2]
    return parent == "plan" or "presentation" in parent or parent.startswith("plan-polished")


def _markdown_value(content: str, label: str) -> str | None:
    pattern = re.compile(rf"^-\s*{re.escape(label)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(content)
    if match is None:
        return None
    value = match.group(1).strip().strip("`")
    return value or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_current_direction_result(result: Mapping[str, Any]) -> None:
    if result.get("schema_version") != _DIRECTION_DELIVERY_SCHEMA:
        raise ResearchApiError(
            "legacy or unknown direction delivery cannot satisfy the API completion contract"
        )
    if result.get("literature_protocol") != _TWO_STAGE_LITERATURE_PROTOCOL:
        raise ResearchApiError("direction delivery lacks the two-stage literature protocol")
    status = str(result.get("status") or "")
    expected_recommendation = {
        "completed": "pass",
        "completed_with_minor_issues": "minor_revision",
    }.get(status)
    review = result.get("independent_scientific_review")
    if expected_recommendation is None:
        raise ResearchApiError(
            "direction delivery is not authorized by a completed scientific review gate"
        )
    if not isinstance(review, Mapping) or review.get("recommendation") != expected_recommendation:
        raise ResearchApiError(
            "direction delivery status disagrees with its independent scientific review"
        )


def _validate_current_batch_result(result: Mapping[str, Any], *, dry_run: bool) -> None:
    if result.get("schema_version") != _BATCH_REPORT_SCHEMA:
        raise ResearchApiError(
            "legacy or unknown Science125 batch report cannot satisfy the API contract"
        )
    if result.get("literature_protocol") != _TWO_STAGE_LITERATURE_PROTOCOL:
        raise ResearchApiError("Science125 batch report lacks the two-stage literature protocol")
    expected_statuses = (
        {"dry_run"}
        if dry_run
        else {
            "completed",
            "completed_with_isolated_failures",
        }
    )
    if result.get("status") not in expected_statuses:
        raise ResearchApiError("Science125 batch report status contradicts the API request")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(_json_safe(dict(payload)), ensure_ascii=False, indent=2, sort_keys=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "BatchCreateRequest",
    "BatchRunService",
    "ResearchApiError",
    "ResearchApiService",
    "RunCreateRequest",
    "SkillEvolutionService",
    "STAGES",
]
