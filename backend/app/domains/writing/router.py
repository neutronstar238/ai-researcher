"""Writing API routes (spec §17.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.api.errors import ValidationAppError
from app.db.models import User
from app.domains.writing.schemas import (
    CitationCreate,
    CitationOut,
    ClaimLink,
    DocumentCreate,
    DocumentOut,
    SuggestionCreate,
    SuggestionOut,
    VersionCreate,
    VersionOut,
)
from app.domains.writing.service import WritingService

router = APIRouter(tags=["writing"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[DocumentOut]:
    documents = await WritingService(session).list_documents(project_id)
    return [DocumentOut.model_validate(d, from_attributes=True) for d in documents]


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201)
async def create_document(
    project_id: uuid.UUID,
    payload: DocumentCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> DocumentOut:
    document = await WritingService(session).create_document(project_id, payload, user.id)
    return DocumentOut.model_validate(document, from_attributes=True)


@router.get("/projects/{project_id}/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> DocumentOut:
    document = await WritingService(session).get_document(document_id)
    return DocumentOut.model_validate(document, from_attributes=True)


@router.post(
    "/projects/{project_id}/documents/{document_id}/versions",
    response_model=VersionOut,
    status_code=201,
)
async def create_version(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: VersionCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> VersionOut:
    version = await WritingService(session).create_version(document_id, payload, user.id)
    return VersionOut.model_validate(version, from_attributes=True)


@router.get("/projects/{project_id}/documents/{document_id}/versions", response_model=list[VersionOut])
async def list_versions(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[VersionOut]:
    versions = await WritingService(session).list_versions(document_id)
    return [VersionOut.model_validate(v, from_attributes=True) for v in versions]


@router.post("/projects/{project_id}/documents/{document_id}/claims", status_code=201)
async def link_claim(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: ClaimLink,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    document = await WritingService(session).get_document(document_id)
    if document.current_version_id is None:
        from app.api.errors import ValidationAppError

        raise ValidationAppError("文档尚无版本，无法关联主张", code="NO_DOCUMENT_VERSION")
    claim = await WritingService(session).link_claim(
        document.current_version_id, payload.evidence_node_id, payload.anchor, payload.support_status
    )
    return {"id": str(claim.id), "evidence_node_id": str(claim.evidence_node_id)}


@router.post("/projects/{project_id}/documents/{document_id}:integrity-check")
async def integrity_check(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> dict:
    document = await WritingService(session).get_document(document_id)
    if document.current_version_id is None:
        return {"passed": False, "errors": [{"code": "NO_DOCUMENT_VERSION"}], "warnings": []}
    return await WritingService(session).integrity_check(document.current_version_id)


@router.post(
    "/projects/{project_id}/documents/{document_id}/citations",
    response_model=CitationOut,
    status_code=201,
)
async def add_citation(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: CitationCreate,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> CitationOut:
    service = WritingService(session)
    document = await service.get_document(document_id)
    if document.current_version_id is None:
        raise ValidationAppError("文档尚无版本", code="NO_DOCUMENT_VERSION")
    citation = await service.add_citation(
        document.current_version_id, payload.paper_id, payload.citation_key, payload.style_data, payload.anchors
    )
    return CitationOut.model_validate(citation, from_attributes=True)


@router.post("/projects/{project_id}/documents/{document_id}:export")
async def export_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    format: str = Query(default="markdown", pattern="^(markdown|latex|docx|pdf)$"),
    _owner: User = Depends(require_edit),
) -> dict:
    service = WritingService(session)
    document = await service.get_document(document_id)
    if document.current_version_id is None:
        raise ValidationAppError("文档尚无版本", code="NO_DOCUMENT_VERSION")
    return await service.export_document(document.current_version_id, project_id, user.id, format)


# -- suggestions (Agent Diff, spec §17.4) -------------------------------


@router.post(
    "/projects/{project_id}/documents/{document_id}:suggestions",
    response_model=SuggestionOut,
    status_code=201,
)
async def generate_suggestions(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: SuggestionCreate,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> SuggestionOut:
    service = WritingService(session)
    await service.get_document(document_id)
    suggestion = await service.generate_suggestions(
        document_id,
        payload.base_version_id,
        payload.proposed_markdown,
        payload.target_section_key,
        payload.agent_task_id,
    )
    return SuggestionOut.model_validate(suggestion, from_attributes=True)


@router.get(
    "/projects/{project_id}/documents/{document_id}/suggestions",
    response_model=list[SuggestionOut],
)
async def list_suggestions(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[SuggestionOut]:
    suggestions = await WritingService(session).list_suggestions(document_id)
    return [SuggestionOut.model_validate(s, from_attributes=True) for s in suggestions]


@router.post(
    "/projects/{project_id}/documents/{document_id}/suggestions/{suggestion_id}:accept",
    response_model=VersionOut,
)
async def accept_suggestion(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> VersionOut:
    version = await WritingService(session).accept_suggestion(suggestion_id, user.id)
    return VersionOut.model_validate(version, from_attributes=True)


@router.post(
    "/projects/{project_id}/documents/{document_id}/suggestions/{suggestion_id}:reject",
    response_model=SuggestionOut,
)
async def reject_suggestion(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> SuggestionOut:
    suggestion = await WritingService(session).reject_suggestion(suggestion_id, user.id)
    return SuggestionOut.model_validate(suggestion, from_attributes=True)
