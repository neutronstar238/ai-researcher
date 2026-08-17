"""Literature application service (spec §13)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import tempfile
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError
from app.core.config import get_settings
from app.core.job_events import publish_job_event
from app.db.models import (
    Asset,
    EvidenceNode,
    LiteratureSearchRun,
    Paper,
    PaperChunk,
    Project,
    ProjectPaper,
)
from app.integrations.embeddings.hash import get_provider as get_embedding_provider
from app.integrations.literature._util import is_medical_query
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import available_providers, get_provider
from app.integrations.llm.base import get_provider as get_llm_provider
from app.integrations.object_storage.minio import MinioStorage
from app.integrations.vector_store.milvus import MilvusVectorStore


class LiteratureService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, query: str, provider_name: str, max_results: int) -> list[PaperResult]:
        if provider_name == "all":
            return await self._search_all(query, max_results)
        provider = get_provider(provider_name)
        try:
            return await provider.search(query, max_results)
        except httpx.HTTPError as exc:
            raise AppError(
                f"文献源 {provider_name} 检索失败：{exc}",
                code="LITERATURE_SOURCE_ERROR",
                status_code=502,
            ) from exc

    async def _search_all(self, query: str, max_results: int) -> list[PaperResult]:
        """并发检索所有文献源（PubMed 仅在医药问题时启用）。单个源失败不影响其余。"""
        sources = [name for name in available_providers() if name != "pubmed"]
        if is_medical_query(query):
            sources.append("pubmed")

        async def _one(name: str) -> list[PaperResult]:
            try:
                return await get_provider(name).search(query, max_results)
            except Exception:  # noqa: BLE001 - 单源失败降级为 0 条，不阻断整批
                return []

        batches = await asyncio.gather(*(_one(name) for name in sources))
        merged: list[PaperResult] = []
        for batch in batches:
            merged.extend(batch)
        return merged

    # -- 异步检索 Job（§13.6/§3.3 202+Job） -----------------------------

    async def create_run(
        self,
        project_id: uuid.UUID,
        query: str,
        provider: str,
        max_results: int,
        requested_by: uuid.UUID,
    ) -> LiteratureSearchRun:
        run = LiteratureSearchRun(
            project_id=project_id,
            query=query,
            provider=provider,
            max_results=max_results,
            requested_by=requested_by,
        )
        self.session.add(run)
        await self.session.commit()
        return run

    async def execute_run(self, run_id: uuid.UUID) -> LiteratureSearchRun:
        run = await self.get_run(run_id)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await self.session.commit()
        await publish_job_event(
            str(run.project_id),
            {"type": "job", "kind": "literature_search", "run_id": str(run.id), "status": "running"},
        )
        try:
            results = await self.search(run.query, run.provider, run.max_results)
            result_payload: dict = {
                "query": run.query,
                "provider": run.provider,
                "count": len(results),
                "results": [
                    {
                        "title": r.title,
                        "source": r.source,
                        "doi": r.doi,
                        "publication_year": r.publication_year,
                        "venue": r.venue,
                        "abstract": (r.abstract or "")[:500],
                        "external_id": r.external_id,
                    }
                    for r in results
                ],
            }
            # PubMed 领域门控说明（非医药问题自动跳过）
            if run.provider in {"pubmed", "all"} and not is_medical_query(run.query):
                result_payload["note"] = "查询非医药相关问题，已跳过 PubMed 源（PubMed 仅对医药问题生效）"
            run.result = result_payload
            run.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - 结构化记录失败
            run.status = "failed"
            run.error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        finally:
            run.finished_at = datetime.now(UTC)
            await self.session.commit()
        await publish_job_event(
            str(run.project_id),
            {"type": "job", "kind": "literature_search", "run_id": str(run.id), "status": run.status},
        )
        return run

    async def get_run(self, run_id: uuid.UUID) -> LiteratureSearchRun:
        run = await self.session.get(LiteratureSearchRun, run_id)
        if run is None:
            raise NotFoundError("检索 Job 不存在")
        return run

    async def list_runs(self, project_id: uuid.UUID) -> list[LiteratureSearchRun]:
        result = await self.session.execute(
            select(LiteratureSearchRun)
            .where(LiteratureSearchRun.project_id == project_id)
            .order_by(LiteratureSearchRun.created_at.desc())
        )
        return list(result.scalars().all())

    async def save_paper(self, project_id: uuid.UUID, payload, added_by: uuid.UUID) -> Paper:
        paper = await self._find_or_create_paper(payload)
        existing = (
            await self.session.execute(
                select(ProjectPaper).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.paper_id == paper.id,
                    ProjectPaper.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationAppError("该论文已加入项目", code="PAPER_ALREADY_IN_PROJECT")
        self.session.add(
            ProjectPaper(project_id=project_id, paper_id=paper.id, added_by=added_by)
        )
        await self.session.commit()
        return paper

    async def list_papers(self, project_id: uuid.UUID) -> list[Paper]:
        result = await self.session.execute(
            select(Paper)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id, ProjectPaper.archived_at.is_(None))
            .order_by(Paper.created_at.desc())
        )
        return list(result.scalars().all())

    async def paper_count(self, project_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id, ProjectPaper.archived_at.is_(None)
            )
        )
        return len(result.scalars().all())

    async def _find_or_create_paper(self, payload) -> Paper:
        if payload.doi:
            existing = (
                await self.session.execute(select(Paper).where(Paper.doi == payload.doi))
            ).scalar_one_or_none()
        else:
            existing = (
                await self.session.execute(select(Paper).where(Paper.title == payload.title))
            ).scalar_one_or_none()
        if existing is not None:
            return existing
        paper = Paper(
            doi=payload.doi,
            title=payload.title,
            abstract=payload.abstract,
            publication_year=payload.publication_year,
            venue=payload.venue,
            external_ids={"source": payload.source, "external_id": payload.external_id}
            if payload.external_id
            else None,
            metadata_source=payload.source,
        )
        self.session.add(paper)
        await self.session.flush()
        return paper

    # -- PDF 解析 / chunk / embedding（spec §13.x）------------------------

    async def ingest_pdf(
        self, project_id: uuid.UUID, paper_id: uuid.UUID, asset_id: uuid.UUID
    ) -> dict:
        paper = await self.session.get(Paper, paper_id)
        if paper is None:
            raise NotFoundError("论文不存在")
        asset = await self.session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError("资产不存在")
        if asset.mime_type != "application/pdf":
            raise ValidationAppError("资产不是 PDF", code="NOT_PDF")

        text = await asyncio.to_thread(self._extract_pdf_text, asset.object_key)
        chunks = self._chunk_text(text)

        embedding = get_embedding_provider(get_settings().embedding_provider)
        store = MilvusVectorStore(dimension=embedding.dimension)
        store.ensure_collection()

        for index, chunk_text in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            store.insert(
                chunk_id, str(project_id), str(paper_id), embedding.embed(chunk_text), embedding.name
            )
            self.session.add(
                PaperChunk(
                    id=uuid.UUID(chunk_id),
                    paper_id=paper_id,
                    chunk_index=index,
                    content=chunk_text,
                    content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                    token_count=len(chunk_text.split()),
                    embedding_model=embedding.name,
                    embedding_status="embedded",
                )
            )
        await self.session.commit()
        return {"paper_id": str(paper_id), "chunks": len(chunks), "embedding_model": embedding.name}

    @staticmethod
    def _extract_pdf_text(object_key: str) -> str:
        import fitz  # pymupdf

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            MinioStorage().download_to_file(object_key, tmp_path)
            doc = fitz.open(tmp_path)
            try:
                text = "\n\n".join(page.get_text() for page in doc)
                if text.strip():
                    return text
                # 无文本层（扫描件）→ OCR
                return LiteratureService._ocr_pages(doc)
            finally:
                doc.close()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    @staticmethod
    def _ocr_pages(doc) -> str:
        """渲染页面 → RapidOCR 识别（§13.x 扫描件 OCR）。缺 OCR 引擎时返回空串并记录。"""
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            return ""
        engine = RapidOCR()
        parts: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            result, _ = engine(img)
            if result:
                parts.append("\n".join(str(item[1]) for item in result))
        return "\n\n".join(parts)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        words = text.split()
        chunks: list[str] = []
        current: list[str] = []
        length = 0
        for word in words:
            current.append(word)
            length += len(word) + 1
            if length >= chunk_size:
                chunks.append(" ".join(current))
                current = []
                length = 0
        if current:
            chunks.append(" ".join(current))
        return chunks

    # -- 自动证据抽取（§13.x：LLM 抽取主张 → 证据节点）--------------------

    EXTRACT_SCHEMA = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "node_type": {"type": "string", "enum": ["claim", "evidence", "hypothesis"]},
                    },
                    "required": ["text"],
                },
            }
        },
        "required": ["claims"],
    }

    async def extract_evidence(
        self, project_id: uuid.UUID, paper_id: uuid.UUID, created_by: uuid.UUID
    ) -> dict:
        paper = await self.session.get(Paper, paper_id)
        if paper is None:
            raise NotFoundError("论文不存在")
        project = await self.session.get(Project, project_id)
        if project is None or project.current_cycle_id is None:
            raise ValidationAppError("项目无当前周期", code="NO_CURRENT_CYCLE")

        # 幂等：同一论文在当前周期已抽取过证据则直接返回，避免重复节点与唯一约束冲突（§13.x）
        existing_nodes = (
            await self.session.execute(
                select(EvidenceNode).where(
                    EvidenceNode.cycle_id == project.current_cycle_id,
                    EvidenceNode.code.like(f"X-{paper_id.hex[:6]}-%"),
                    EvidenceNode.archived_at.is_(None),
                )
            )
        ).scalars().all()
        if existing_nodes:
            return {
                "paper_id": str(paper_id),
                "extracted": len(existing_nodes),
                "nodes": [
                    {"id": str(n.id), "node_type": n.node_type, "title": n.title}
                    for n in existing_nodes
                ],
            }

        chunks = (
            await self.session.execute(
                select(PaperChunk)
                .where(PaperChunk.paper_id == paper_id)
                .order_by(PaperChunk.chunk_index)
            )
        ).scalars().all()
        text = "\n".join(c.content for c in chunks) if chunks else (paper.abstract or paper.title)

        provider = get_llm_provider()
        response = await provider.complete(
            f"从以下论文内容抽取 2-5 条可验证的主张（每条一句话，中英均可）：\n\n{text[:4000]}",
            json_schema=self.EXTRACT_SCHEMA,
        )
        claims = (response.structured or {}).get("claims", [])
        if not isinstance(claims, list):
            claims = []

        nodes: list[EvidenceNode] = []
        for index, claim in enumerate(claims):
            title = str(claim.get("text", "")).strip()[:200] if isinstance(claim, dict) else ""
            if not title:
                continue
            node = EvidenceNode(
                project_id=project_id,
                cycle_id=project.current_cycle_id,
                node_type=str(claim.get("node_type", "claim")) if isinstance(claim, dict) else "claim",
                code=f"X-{paper_id.hex[:6]}-{index}",
                title=title,
                status="draft",
                created_by=created_by,
            )
            self.session.add(node)
            nodes.append(node)
        await self.session.commit()
        return {
            "paper_id": str(paper_id),
            "extracted": len(nodes),
            "nodes": [
                {"id": str(n.id), "node_type": n.node_type, "title": n.title} for n in nodes
            ],
        }
