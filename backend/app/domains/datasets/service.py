"""Dataset application service (spec §8.4/§11.6)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError, ValidationAppError
from app.db.models import Dataset, DatasetVersion


class DatasetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_dataset(self, project_id: uuid.UUID, payload, created_by: uuid.UUID) -> Dataset:
        duplicate = (
            await self.session.execute(
                select(Dataset).where(Dataset.project_id == project_id, Dataset.name == payload.name)
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ValidationAppError("数据集名称已存在", code="DATASET_NAME_EXISTS")
        dataset = Dataset(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            license=payload.license,
            sensitivity=payload.sensitivity,
            created_by=created_by,
        )
        self.session.add(dataset)
        await self.session.commit()
        return dataset

    async def list_datasets(self, project_id: uuid.UUID) -> list[Dataset]:
        result = await self.session.execute(
            select(Dataset).where(Dataset.project_id == project_id, Dataset.archived_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_dataset(self, dataset_id: uuid.UUID) -> Dataset:
        dataset = await self.session.get(Dataset, dataset_id)
        if dataset is None:
            raise NotFoundError("数据集不存在")
        return dataset

    async def create_version(self, dataset_id: uuid.UUID, payload, created_by: uuid.UUID) -> DatasetVersion:
        await self.get_dataset(dataset_id)
        max_no = await self.session.execute(
            select(func.max(DatasetVersion.version_no)).where(DatasetVersion.dataset_id == dataset_id)
        )
        version_no = (max_no.scalar() or 0) + 1
        version = DatasetVersion(
            dataset_id=dataset_id,
            version_no=version_no,
            manifest_sha256=payload.manifest_sha256,
            schema_json=payload.schema_json,
            statistics=payload.statistics,
            row_count=payload.row_count,
            size_bytes=payload.size_bytes,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.commit()
        return version

    async def list_versions(self, dataset_id: uuid.UUID) -> list[DatasetVersion]:
        result = await self.session.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_no.desc())
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: uuid.UUID) -> DatasetVersion:
        version = await self.session.get(DatasetVersion, version_id)
        if version is None:
            raise NotFoundError("数据集版本不存在")
        return version
