"""Asset application service (spec §9.7)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError, ValidationAppError
from app.core.config import get_settings
from app.core.file_security import magic_bytes_matches
from app.core.malware import scan_file
from app.db.models import Asset, Project
from app.domains.audit.service import record_audit
from app.integrations.object_storage.minio import MinioStorage


class AssetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.storage = MinioStorage()

    async def initiate(self, project_id: uuid.UUID, payload) -> dict:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")
        # 扁平、服务端生成的 object key（无斜杠，便于 {upload_id} 路由）
        object_key = f"p-{project_id.hex[:12]}-{uuid.uuid4().hex}"

        if payload.part_count <= 1:
            url = self.storage.presign_put(object_key, payload.mime_type)
            return {
                "upload_id": object_key,
                "object_key": object_key,
                "upload_url": url,
                "upload_urls": [url],
                "bucket": self.storage.bucket,
                "mode": "single",
            }

        # 分片上传（spec §9.7）：create_multipart_upload + 每片签名 URL
        upload_id = self.storage.create_multipart_upload(object_key)
        urls = [
            self.storage.presign_upload_part(object_key, upload_id, part_no)
            for part_no in range(1, payload.part_count + 1)
        ]
        return {
            "upload_id": upload_id,
            "object_key": object_key,
            "upload_url": None,
            "upload_urls": urls,
            "bucket": self.storage.bucket,
            "mode": "multipart",
        }

    async def complete(self, project_id: uuid.UUID, upload_id: str, payload, created_by: uuid.UUID) -> Asset:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")

        if payload.parts:
            # 分片模式：upload_id 为 multipart upload id，object_key 在载荷中
            object_key = payload.object_key
            if not object_key or not object_key.startswith(f"p-{project_id.hex[:12]}-"):
                raise ValidationAppError("object_key 不属于该项目", code="INVALID_OBJECT_KEY")
            try:
                self.storage.complete_multipart_upload(
                    object_key, upload_id, [p.model_dump() for p in payload.parts]
                )
            except Exception as exc:  # noqa: BLE001 - 分片顺序/ETag 错误 → 中止并报校验失败
                self.storage.abort_multipart_upload(object_key, upload_id)
                raise ValidationAppError(
                    f"分片合并失败：{exc}", code="MULTIPART_COMPLETE_FAILED"
                ) from exc
        else:
            # 单分片模式：upload_id 即 object key（向后兼容）
            object_key = upload_id
            if not object_key.startswith(f"p-{project_id.hex[:12]}-"):
                raise ValidationAppError("upload_id 不属于该项目", code="INVALID_OBJECT_KEY")
            if not self.storage.object_exists(object_key):
                raise ValidationAppError("对象不存在，请先完成上传", code="OBJECT_NOT_FOUND")

        sha256, size = await asyncio.to_thread(self.storage.sha256_and_size, object_key)
        self._validate_upload(object_key, payload.mime_type, size)
        clean, scan_status = await self._scan_object(object_key)
        asset = Asset(
            team_id=project.team_id,
            project_id=project_id,
            kind=payload.kind,
            bucket=self.storage.bucket,
            object_key=object_key,
            original_name=payload.original_name,
            mime_type=payload.mime_type,
            size_bytes=size,
            sha256=sha256,
            status="ready" if clean else "quarantined",
            scan_status=scan_status,
            created_by=created_by,
        )
        self.session.add(asset)
        await self.session.flush()
        record_audit(
            self.session,
            action="asset.uploaded",
            actor_id=created_by,
            team_id=project.team_id,
            project_id=project_id,
            target_type="asset",
            target_id=asset.id,
            after_redacted={"kind": payload.kind, "sha256": sha256, "size_bytes": size},
        )
        await self.session.commit()
        return asset

    async def list_assets(self, project_id: uuid.UUID) -> list[Asset]:
        result = await self.session.execute(
            select(Asset).where(
                Asset.project_id == project_id, Asset.archived_at.is_(None)
            ).order_by(Asset.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_asset(self, asset_id: uuid.UUID) -> Asset:
        asset = await self.session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError("资产不存在")
        return asset

    def download_url(self, asset: Asset) -> str:
        return self.storage.presign_get(asset.object_key)

    # -- file security (spec §19.4) --------------------------------------

    def _validate_upload(self, object_key: str, mime_type: str | None, size: int) -> None:
        max_bytes = get_settings().max_upload_bytes
        if size > max_bytes:
            raise ValidationAppError(
                f"文件超过大小上限 {max_bytes} 字节", code="FILE_TOO_LARGE"
            )
        head = self.storage.read_head(object_key, n=16)
        if not magic_bytes_matches(mime_type, head):
            raise ValidationAppError(
                "文件内容与声明 MIME 不符", code="MAGIC_BYTES_MISMATCH",
                details={"mime_type": mime_type or "", "head_hex": head.hex()},
            )

    async def _scan_object(self, object_key: str) -> tuple[bool, str]:
        """下载到临时文件 → ClamAV 扫描 → 清理（§19.4）。缺 ClamAV 时返回 not_scanned。"""
        fd, tmp_path = tempfile.mkstemp(suffix=".upload")
        os.close(fd)
        try:
            await asyncio.to_thread(self.storage.download_to_file, object_key, tmp_path)
            return await asyncio.to_thread(scan_file, tmp_path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
