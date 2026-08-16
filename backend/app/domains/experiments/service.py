"""Experiment application service + local runner (spec §15).

Phase 4 slice A: real subprocess execution with timeout + captured output + exit
code, transitioning the run through the §15.2 state machine. This is NOT a timer
simulation (§23.4). The isolated container runner (§15.3) replaces ``_execute``
in a later slice; Celery replaces the background asyncio task (§3.3).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError
from app.core.job_events import publish_job_event
from app.core.observability import EXPERIMENT_RUNS
from app.db.models import (
    Asset,
    DatasetVersion,
    Experiment,
    ExperimentArtifact,
    ExperimentMetric,
    ExperimentRun,
    ExperimentRunDataset,
)
from app.domains.audit.service import record_audit
from app.integrations.execution.container_runner import ContainerRunner


class ExperimentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- definitions ----------------------------------------------------

    async def create_experiment(self, project_id: uuid.UUID, payload, created_by: uuid.UUID) -> Experiment:
        duplicate = (
            await self.session.execute(
                select(Experiment).where(
                    Experiment.cycle_id == payload.cycle_id, Experiment.code == payload.code
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ValidationAppError("实验 code 在该周期已存在", code="EXPERIMENT_CODE_EXISTS")
        experiment = Experiment(
            project_id=project_id,
            cycle_id=payload.cycle_id,
            code=payload.code,
            name=payload.name,
            objective=payload.objective,
            entrypoint=payload.entrypoint,
            container_image=payload.container_image,
            created_by=created_by,
        )
        self.session.add(experiment)
        await self.session.commit()
        return experiment

    async def list_experiments(self, project_id: uuid.UUID) -> list[Experiment]:
        result = await self.session.execute(
            select(Experiment).where(
                Experiment.project_id == project_id, Experiment.archived_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def get_experiment(self, experiment_id: uuid.UUID) -> Experiment:
        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None:
            raise NotFoundError("实验不存在")
        return experiment

    # -- runs -----------------------------------------------------------

    async def create_run(self, experiment_id: uuid.UUID, payload, requested_by: uuid.UUID) -> ExperimentRun:
        experiment = await self.get_experiment(experiment_id)
        max_no = await self.session.execute(
            select(func.max(ExperimentRun.run_no)).where(ExperimentRun.experiment_id == experiment_id)
        )
        run_no = (max_no.scalar() or 0) + 1
        run = ExperimentRun(
            experiment_id=experiment_id,
            run_no=run_no,
            parameters=payload.parameters,
            random_seed=payload.random_seed,
            resource_request=payload.resource_request,
            requested_by=requested_by,
        )
        self.session.add(run)
        await self.session.flush()
        record_audit(
            self.session,
            action="experiment.run.created",
            actor_id=requested_by,
            project_id=experiment.project_id,
            target_type="experiment_run",
            target_id=run.id,
        )
        await self.session.commit()
        # 同步真实执行。Celery 队列（app/workers/tasks.py）已就绪但未接入热路径：
        # TestClient 环境下 kombu .delay() 与异步事件循环存在 Windows 交互问题，
        # 需在真实 worker + live 服务器集成测试后再切换（spec §3.3）。
        return await self._execute(run.id)

    async def get_run(self, run_id: uuid.UUID) -> ExperimentRun:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None:
            raise NotFoundError("运行不存在")
        return run

    async def list_runs(self, experiment_id: uuid.UUID) -> list[ExperimentRun]:
        result = await self.session.execute(
            select(ExperimentRun)
            .where(ExperimentRun.experiment_id == experiment_id)
            .order_by(ExperimentRun.run_no.desc())
        )
        return list(result.scalars().all())

    async def cancel_run(self, run_id: uuid.UUID) -> ExperimentRun:
        run = await self.get_run(run_id)
        if run.status == "queued":
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            experiment = await self.session.get(Experiment, run.experiment_id)
            record_audit(
                self.session,
                action="experiment.run.cancelled",
                project_id=experiment.project_id if experiment else None,
                target_type="experiment_run",
                target_id=run.id,
            )
            await self.session.commit()
        elif run.status in {"running", "preparing"}:
            raise AppError("运行中的实验在本地 dev runner 下无法安全取消", code="RUN_NOT_CANCELLABLE", status_code=409)
        else:
            raise AppError(f"状态 {run.status} 不可取消", code="RUN_NOT_CANCELLABLE", status_code=409)
        return run

    # -- metrics / reproducibility -------------------------------------

    async def record_metrics(self, run_id: uuid.UUID, records) -> list[ExperimentMetric]:
        await self.get_run(run_id)
        metrics = [
            ExperimentMetric(run_id=run_id, name=r.name, step=r.step, value=r.value) for r in records
        ]
        self.session.add_all(metrics)
        await self.session.commit()
        return metrics

    async def list_metrics(self, run_id: uuid.UUID) -> list[ExperimentMetric]:
        result = await self.session.execute(
            select(ExperimentMetric)
            .where(ExperimentMetric.run_id == run_id)
            .order_by(ExperimentMetric.step)
        )
        return list(result.scalars().all())

    async def reproducibility(self, run_id: uuid.UUID) -> dict:
        run = await self.get_run(run_id)
        experiment = await self.get_experiment(run.experiment_id)
        metrics = await self.list_metrics(run_id)
        artifacts = (
            await self.session.execute(
                select(ExperimentArtifact, Asset)
                .join(Asset, Asset.id == ExperimentArtifact.asset_id)
                .where(ExperimentArtifact.run_id == run_id)
            )
        ).all()
        run_datasets = (
            await self.session.execute(
                select(ExperimentRunDataset, DatasetVersion)
                .join(DatasetVersion, DatasetVersion.id == ExperimentRunDataset.dataset_version_id)
                .where(ExperimentRunDataset.run_id == run_id)
            )
        ).all()
        return {
            "schema_version": "experiment-reproducibility-v1",
            "run_id": str(run.id),
            "experiment": {"code": experiment.code, "name": experiment.name},
            "entrypoint": experiment.entrypoint,
            "parameters": run.parameters,
            "random_seed": run.random_seed,
            "code_sha256": run.code_sha256,
            "image_digest": run.image_digest,
            "resource_request": run.resource_request,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "exit_code": run.exit_code,
            "metrics": [{"name": m.name, "step": m.step, "value": m.value} for m in metrics],
            "artifacts": [
                {"name": ea.name, "role": ea.role, "sha256": asset.sha256} for ea, asset in artifacts
            ],
            "datasets": [
                {
                    "dataset_version_id": str(dv.id),
                    "mount_path": rd.mount_path,
                    "access_mode": rd.access_mode,
                    "manifest_sha256": dv.manifest_sha256,
                }
                for rd, dv in run_datasets
            ],
        }

    # -- run dataset/artifact bindings -----------------------------------

    async def bind_dataset(
        self,
        run_id: uuid.UUID,
        dataset_version_id: uuid.UUID,
        mount_path: str,
        access_mode: str,
    ) -> ExperimentRunDataset:
        await self.get_run(run_id)
        version = await self.session.get(DatasetVersion, dataset_version_id)
        if version is None:
            raise NotFoundError("数据集版本不存在")
        binding = ExperimentRunDataset(
            run_id=run_id,
            dataset_version_id=dataset_version_id,
            mount_path=mount_path,
            access_mode=access_mode,
        )
        self.session.add(binding)
        await self.session.commit()
        return binding

    async def bind_artifact(
        self, run_id: uuid.UUID, asset_id: uuid.UUID, role: str | None, name: str
    ) -> ExperimentArtifact:
        await self.get_run(run_id)
        asset = await self.session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError("资产不存在")
        binding = ExperimentArtifact(run_id=run_id, asset_id=asset_id, role=role, name=name)
        self.session.add(binding)
        await self.session.commit()
        return binding

    # -- execution ------------------------------------------------------

    async def _execute(self, run_id: uuid.UUID) -> ExperimentRun:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None:
            raise NotFoundError("运行不存在")
        experiment = await self.session.get(Experiment, run.experiment_id)
        if experiment is None:
            raise NotFoundError("实验不存在")

        run.status = "running"
        run.started_at = datetime.now(UTC)
        await self.session.commit()
        await publish_job_event(
            str(experiment.project_id),
            {"type": "job", "kind": "experiment_run", "run_id": str(run.id), "status": "running"},
        )

        process = None
        try:
            if experiment.container_image:
                exit_code, output = await self._run_in_container(experiment)
                run.image_digest = await self._image_digest(experiment.container_image)
            else:
                exit_code, output = await self._run_local_streaming(experiment, run.id)
                run.code_sha256 = hashlib.sha256(experiment.entrypoint.encode("utf-8")).hexdigest()
            run.exit_code = exit_code
            run.log_output = output.decode("utf-8", errors="replace")[:100_000]
            run.status = "succeeded" if exit_code == 0 else "failed"
            if exit_code != 0:
                run.error = {"exit_code": exit_code}
        except TimeoutError:
            run.status = "failed"
            run.error = {"type": "TIMEOUT", "message": "运行超过 60 秒被终止"}
            if process is not None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
        except Exception as exc:  # noqa: BLE001 - 记录结构化失败
            run.status = "failed"
            run.error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            run.finished_at = datetime.now(UTC)
            EXPERIMENT_RUNS.labels(status=run.status).inc()
            await self.session.commit()
        await publish_job_event(
            str(experiment.project_id),
            {"type": "job", "kind": "experiment_run", "run_id": str(run.id), "status": run.status},
        )
        return run

    async def _run_in_container(self, experiment: Experiment) -> tuple[int, bytes]:
        # 资源限制默认 512m / 1 核；隔离：无网络、no-new-privileges、非 root（§15.3/§19.5）
        runner = ContainerRunner(
            experiment.container_image or "",
            experiment.entrypoint,
            timeout=120,
            memory="512m",
            cpus="1.0",
        )
        return await runner.run()

    async def _image_digest(self, image: str) -> str | None:
        """取容器镜像 digest（§15.5 复现：image_digest 绑定运行）。"""
        process = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{index .RepoDigests 0}}", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        digest = stdout.decode("utf-8", errors="replace").strip()
        return digest or None

    async def _run_local_streaming(self, experiment: Experiment, run_id: uuid.UUID) -> tuple[int, bytes]:
        """本地子进程执行并**逐行**把日志推到 WebSocket（§15 实时日志流）。"""
        process = await asyncio.create_subprocess_shell(
            experiment.entrypoint,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        parts: list[bytes] = []
        deadline = time.monotonic() + 60
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    raise TimeoutError("运行超过 60 秒被终止")
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                except TimeoutError as exc:
                    process.kill()
                    raise TimeoutError("运行超过 60 秒被终止") from exc
                if not line:
                    break
                parts.append(line)
                await publish_job_event(
                    str(experiment.project_id),
                    {
                        "type": "log",
                        "kind": "experiment_run",
                        "run_id": str(run_id),
                        "line": line.decode("utf-8", errors="replace"),
                    },
                )
            exit_code = await process.wait()
        finally:
            with contextlib.suppress(ProcessLookupError):
                if process.returncode is None:
                    process.kill()
        return exit_code, b"".join(parts)
