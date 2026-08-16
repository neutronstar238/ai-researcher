"""隔离容器 Runner（spec §15.3）。

在「无网络、有限内存/CPU、no-new-privileges」的容器里执行实验入口，避免直接
在 API 进程主机上跑任意 shell。缺 Docker 或镜像时抛结构化错误，不回退伪造。
"""

from __future__ import annotations

import asyncio

from app.api.errors import ValidationAppError


class ContainerRunner:
    def __init__(
        self,
        image: str,
        entrypoint: str,
        *,
        timeout: int = 60,
        memory: str = "512m",
        cpus: str = "1.0",
    ) -> None:
        self.image = image
        self.entrypoint = entrypoint
        self.timeout = timeout
        self.memory = memory
        self.cpus = cpus

    async def run(self) -> tuple[int, bytes]:
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            "--security-opt", "no-new-privileges",
            "--user", "1000:1000",
            self.image,
            "sh", "-c", self.entrypoint,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise ValidationAppError("容器运行超时", code="CONTAINER_TIMEOUT") from exc
        return process.returncode, stdout + stderr
