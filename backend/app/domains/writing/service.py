"""Writing application service (spec §17)."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError
from app.db.models import (
    Asset,
    Citation,
    Document,
    DocumentClaim,
    DocumentSuggestion,
    DocumentVersion,
    EvidenceNode,
    Paper,
    Project,
)
from app.integrations.object_storage.minio import MinioStorage


class WritingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- documents ------------------------------------------------------

    async def create_document(
        self, project_id: uuid.UUID, payload, created_by: uuid.UUID
    ) -> Document:
        document = Document(
            project_id=project_id,
            cycle_id=payload.cycle_id,
            title=payload.title,
            document_type=payload.document_type,
            created_by=created_by,
        )
        self.session.add(document)
        await self.session.commit()
        return document

    async def list_documents(self, project_id: uuid.UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.project_id == project_id, Document.archived_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: uuid.UUID) -> Document:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise NotFoundError("文档不存在")
        return document

    # -- versions -------------------------------------------------------

    async def create_version(
        self, document_id: uuid.UUID, payload, created_by: uuid.UUID
    ) -> DocumentVersion:
        document = await self.get_document(document_id)
        max_no = await self.session.execute(
            select(func.max(DocumentVersion.version_no)).where(
                DocumentVersion.document_id == document_id
            )
        )
        version_no = (max_no.scalar() or 0) + 1
        sha = hashlib.sha256(payload.content_markdown.encode("utf-8")).hexdigest()
        version = DocumentVersion(
            document_id=document_id,
            version_no=version_no,
            content_markdown=payload.content_markdown,
            content_sha256=sha,
            change_summary=payload.change_summary,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.flush()
        document.current_version_id = version.id
        await self.session.commit()
        return version

    async def list_versions(self, document_id: uuid.UUID) -> list[DocumentVersion]:
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: uuid.UUID) -> DocumentVersion:
        version = await self.session.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError("文档版本不存在")
        return version

    # -- claims ---------------------------------------------------------

    async def link_claim(
        self, version_id: uuid.UUID, evidence_node_id: uuid.UUID, anchor: dict | None, support_status: str
    ) -> DocumentClaim:
        await self.get_version(version_id)
        node = await self.session.get(EvidenceNode, evidence_node_id)
        if node is None or node.archived_at is not None:
            raise ValidationAppError("证据节点不存在或已归档", code="EVIDENCE_NODE_INVALID")
        claim = DocumentClaim(
            document_version_id=version_id,
            evidence_node_id=evidence_node_id,
            anchor=anchor,
            support_status=support_status,
        )
        self.session.add(claim)
        await self.session.commit()
        return claim

    # -- integrity ------------------------------------------------------

    async def integrity_check(self, version_id: uuid.UUID) -> dict:
        version = await self.get_version(version_id)
        errors: list[dict] = []
        warnings: list[dict] = []

        claims = (
            await self.session.execute(
                select(DocumentClaim).where(DocumentClaim.document_version_id == version_id)
            )
        ).scalars().all()
        if not claims:
            warnings.append({"code": "NO_CLAIMS", "message": "文档没有关联任何证据主张"})
        for claim in claims:
            node = await self.session.get(EvidenceNode, claim.evidence_node_id)
            if node is None or node.archived_at is not None:
                errors.append(
                    {
                        "code": "EVIDENCE_NODE_MISSING",
                        "claim_id": str(claim.id),
                        "evidence_node_id": str(claim.evidence_node_id),
                    }
                )

        # 未解决的占位文本（§17.2.6）
        for marker in ("TODO", "待补", "TBD", "待补引用"):
            if marker in version.content_markdown:
                warnings.append({"code": "UNRESOLVED_PLACEHOLDER", "marker": marker})

        # 引用完整性（§17.2.3）
        citations = await self.list_citations(version_id)
        keys = [c.citation_key for c in citations]
        if len(keys) != len(set(keys)):
            errors.append({"code": "DUPLICATE_CITATION_KEY"})
        for citation in citations:
            paper = await self.session.get(Paper, citation.paper_id)
            if paper is None:
                errors.append({"code": "CITATION_PAPER_MISSING", "citation_key": citation.citation_key})
            elif paper.publication_year is None:
                warnings.append({"code": "CITATION_MISSING_YEAR", "citation_key": citation.citation_key})

        return {
            "passed": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    # -- suggestions (Agent Diff, spec §17.4) ----------------------------

    async def generate_suggestions(
        self,
        document_id: uuid.UUID,
        base_version_id: uuid.UUID,
        proposed_markdown: str,
        target_section_key: str | None,
        agent_task_id: uuid.UUID | None,
    ) -> DocumentSuggestion:
        document = await self.get_document(document_id)
        base = await self.get_version(base_version_id)
        if base.document_id != document.id:
            raise ValidationAppError("基准版本不属于该文档", code="BASE_VERSION_MISMATCH")
        patch, preview = self._diff(base.content_markdown, proposed_markdown)
        suggestion = DocumentSuggestion(
            document_id=document.id,
            base_version_id=base.id,
            target_section_key=target_section_key,
            patch=patch,
            rendered_preview=preview,
            agent_task_id=agent_task_id,
        )
        self.session.add(suggestion)
        await self.session.commit()
        return suggestion

    async def list_suggestions(self, document_id: uuid.UUID) -> list[DocumentSuggestion]:
        result = await self.session.execute(
            select(DocumentSuggestion)
            .where(DocumentSuggestion.document_id == document_id)
            .order_by(DocumentSuggestion.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_suggestion(self, suggestion_id: uuid.UUID) -> DocumentSuggestion:
        suggestion = await self.session.get(DocumentSuggestion, suggestion_id)
        if suggestion is None:
            raise NotFoundError("写作建议不存在")
        return suggestion

    async def accept_suggestion(self, suggestion_id: uuid.UUID, decided_by: uuid.UUID) -> DocumentVersion:
        suggestion = await self.get_suggestion(suggestion_id)
        if suggestion.status != "pending":
            raise AppError("建议已处理，不可重复决定", code="SUGGESTION_ALREADY_DECIDED", status_code=409)
        proposed = (suggestion.patch or {}).get("proposed_markdown")
        if not proposed:
            raise ValidationAppError("建议缺少提案内容", code="SUGGESTION_EMPTY_PATCH")
        document = await self.get_document(suggestion.document_id)

        # 接受 = 在同一事务创建新 Document Version，不覆盖基准版本（§17.4）
        max_no = await self.session.execute(
            select(func.max(DocumentVersion.version_no)).where(
                DocumentVersion.document_id == document.id
            )
        )
        version_no = (max_no.scalar() or 0) + 1
        sha = hashlib.sha256(proposed.encode("utf-8")).hexdigest()
        version = DocumentVersion(
            document_id=document.id,
            version_no=version_no,
            content_markdown=proposed,
            content_sha256=sha,
            change_summary=f"采纳写作建议 {suggestion.id}",
            source_agent_task_id=suggestion.agent_task_id,
            created_by=decided_by,
        )
        self.session.add(version)
        await self.session.flush()
        document.current_version_id = version.id

        suggestion.status = "accepted"
        suggestion.decided_by = decided_by
        suggestion.decided_at = datetime.now(UTC)

        # 其余待处理建议过期（superseded）
        others = (
            await self.session.execute(
                select(DocumentSuggestion).where(
                    DocumentSuggestion.document_id == document.id,
                    DocumentSuggestion.status == "pending",
                    DocumentSuggestion.id != suggestion.id,
                )
            )
        ).scalars().all()
        for other in others:
            other.status = "superseded"
            other.decided_at = datetime.now(UTC)

        await self.session.commit()
        return version

    async def reject_suggestion(self, suggestion_id: uuid.UUID, decided_by: uuid.UUID) -> DocumentSuggestion:
        suggestion = await self.get_suggestion(suggestion_id)
        if suggestion.status != "pending":
            raise AppError("建议已处理，不可重复决定", code="SUGGESTION_ALREADY_DECIDED", status_code=409)
        suggestion.status = "rejected"
        suggestion.decided_by = decided_by
        suggestion.decided_at = datetime.now(UTC)
        await self.session.commit()
        return suggestion

    @staticmethod
    def _diff(base_markdown: str, proposed_markdown: str) -> tuple[dict, str]:
        base_lines = base_markdown.splitlines()
        proposed_lines = proposed_markdown.splitlines()
        matcher = difflib.SequenceMatcher(a=base_lines, b=proposed_lines, autojunk=False)
        ops: list[dict] = []
        additions = 0
        deletions = 0
        preview: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag == "delete":
                deletions += i2 - i1
                for line_no in range(i1 + 1, i2 + 1):
                    ops.append({"op": "remove", "base_line": line_no, "text": base_lines[line_no - 1]})
                    preview.append(f"-{base_lines[line_no - 1]}")
            elif tag == "insert":
                additions += j2 - j1
                for line_no in range(j1 + 1, j2 + 1):
                    ops.append({"op": "add", "proposed_line": line_no, "text": proposed_lines[line_no - 1]})
                    preview.append(f"+{proposed_lines[line_no - 1]}")
            elif tag == "replace":
                deletions += i2 - i1
                additions += j2 - j1
                for line_no in range(i1 + 1, i2 + 1):
                    ops.append({"op": "remove", "base_line": line_no, "text": base_lines[line_no - 1]})
                    preview.append(f"-{base_lines[line_no - 1]}")
                for line_no in range(j1 + 1, j2 + 1):
                    ops.append({"op": "add", "proposed_line": line_no, "text": proposed_lines[line_no - 1]})
                    preview.append(f"+{proposed_lines[line_no - 1]}")
        patch = {
            "additions": additions,
            "deletions": deletions,
            "ops": ops,
            "proposed_markdown": proposed_markdown,
        }
        return patch, "\n".join(preview)

    # -- citations ------------------------------------------------------

    async def add_citation(
        self,
        version_id: uuid.UUID,
        paper_id: uuid.UUID,
        citation_key: str,
        style_data: dict | None,
        anchors: dict | None,
    ) -> Citation:
        await self.get_version(version_id)
        paper = await self.session.get(Paper, paper_id)
        if paper is None:
            raise ValidationAppError("论文不存在", code="PAPER_NOT_FOUND")
        citation = Citation(
            document_version_id=version_id,
            paper_id=paper_id,
            citation_key=citation_key,
            style_data=style_data,
            anchors=anchors,
        )
        self.session.add(citation)
        await self.session.commit()
        return citation

    async def list_citations(self, version_id: uuid.UUID) -> list[Citation]:
        result = await self.session.execute(
            select(Citation).where(Citation.document_version_id == version_id)
        )
        return list(result.scalars().all())

    # -- export ---------------------------------------------------------

    _EXPORT_MIME = {
        "markdown": "text/markdown",
        "latex": "application/x-latex",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }

    async def export_document(
        self, version_id: uuid.UUID, project_id: uuid.UUID, created_by: uuid.UUID, format: str = "markdown"
    ) -> dict:
        if format not in self._EXPORT_MIME:
            raise ValidationAppError(f"不支持的导出格式：{format}", code="UNSUPPORTED_EXPORT_FORMAT")
        version = await self.get_version(version_id)
        document = await self.session.get(Document, version.document_id)
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")

        markdown = await self._full_markdown(version_id, version.content_markdown)

        storage = MinioStorage()
        ext = "md" if format == "markdown" else format
        object_key = f"exports/{document.id}/{version_id}.{ext}"
        if format == "markdown":
            content = markdown.encode("utf-8")
        else:
            content = await asyncio.to_thread(self._convert, markdown, format)
        storage.put_bytes(object_key, content, self._EXPORT_MIME[format])

        sha = hashlib.sha256(content).hexdigest()
        # 重复导出同一版本时对象键相同：复用已有资产行而非再次插入，避免唯一约束冲突（§17.4）
        existing = await self.session.execute(
            select(Asset).where(Asset.bucket == storage.bucket, Asset.object_key == object_key)
        )
        asset = existing.scalar_one_or_none()
        if asset is None:
            asset = Asset(
                team_id=project.team_id,
                project_id=project_id,
                kind="export",
                bucket=storage.bucket,
                object_key=object_key,
                original_name=f"{document.title[:80]}.{ext}",
                mime_type=self._EXPORT_MIME[format],
                size_bytes=len(content),
                sha256=sha,
                created_by=created_by,
            )
            self.session.add(asset)
        else:
            asset.original_name = f"{document.title[:80]}.{ext}"
            asset.mime_type = self._EXPORT_MIME[format]
            asset.size_bytes = len(content)
            asset.sha256 = sha
            asset.created_by = created_by
        await self.session.commit()
        return {
            "asset_id": str(asset.id),
            "download_url": storage.presign_get(object_key),
            "sha256": sha,
            "format": format,
            "manifest": {"version_sha256": version.content_sha256, "citation_count": await self._citation_count(version_id)},
        }

    async def export_markdown(self, version_id: uuid.UUID, project_id: uuid.UUID, created_by: uuid.UUID) -> dict:
        return await self.export_document(version_id, project_id, created_by, "markdown")

    async def _full_markdown(self, version_id: uuid.UUID, content: str) -> str:
        citations = await self.list_citations(version_id)
        refs = []
        for citation in citations:
            paper = await self.session.get(Paper, citation.paper_id)
            year = f" ({paper.publication_year})" if paper and paper.publication_year else ""
            refs.append(f"- [{citation.citation_key}] {paper.title if paper else '?'}{year}")
        return content + ("\n\n## 参考文献\n" + "\n".join(refs) if refs else "")

    async def _citation_count(self, version_id: uuid.UUID) -> int:
        return len(await self.list_citations(version_id))

    @staticmethod
    def _convert(markdown: str, fmt: str) -> bytes:
        """用 pandoc（PDF 用 lualatex + ctex 支持中英文与数学）把 Markdown 转成目标格式（§17.1）。"""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "document.md"
            src.write_text(markdown, encoding="utf-8")
            out = Path(tmp) / f"document.{fmt}"
            cmd = ["pandoc", str(src), "-o", str(out), "--from", "markdown"]
            if fmt == "pdf":
                header = Path(__file__).parent / "header.tex"
                cmd += ["--pdf-engine=lualatex", "-H", str(header)]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            except subprocess.CalledProcessError as exc:
                raise ValidationAppError(
                    f"导出 {fmt} 失败：{exc.stderr.decode('utf-8', errors='replace')[:300]}",
                    code="EXPORT_FAILED",
                ) from exc
            except FileNotFoundError as exc:
                raise ValidationAppError(
                    f"导出 {fmt} 需要 pandoc（PDF 另需 lualatex）", code="EXPORT_TOOL_MISSING"
                ) from exc
            return out.read_bytes()
