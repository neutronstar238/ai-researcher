"""Evidence graph application service (spec §14).

Nodes and edges are business state in PostgreSQL; writes emit Outbox events in
the same transaction (spec §3.4.1). The relation matrix (§14.2) rejects
meaningless edges server-side. A ``contradicts`` edge flips the target's
``has_unresolved_contradiction`` projection (§14.4).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError
from app.core.evidence import (
    is_node_type,
    is_relation,
    relation_allowed,
    self_loop_allowed,
)
from app.db.models import EvidenceEdge, EvidenceNode, OutboxEvent


class EvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- nodes ----------------------------------------------------------

    async def create_node(self, project_id: uuid.UUID, payload, created_by: uuid.UUID) -> EvidenceNode:
        if not is_node_type(payload.node_type):
            raise ValidationAppError("未知节点类型", code="INVALID_NODE_TYPE")
        node = EvidenceNode(
            project_id=project_id,
            cycle_id=payload.cycle_id,
            node_type=payload.node_type,
            code=payload.code,
            title=payload.title,
            description=payload.description,
            confidence=payload.confidence,
            importance=payload.importance,
            meta=payload.metadata,
            created_by=created_by,
        )
        self.session.add(node)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ValidationAppError("节点 code 在该周期已存在", code="NODE_CODE_EXISTS") from exc
        self._outbox("evidence_node", node.id, node.version, "evidence.node.created", self._node_payload(node))
        await self.session.commit()
        return node

    async def get_node(self, node_id: uuid.UUID) -> EvidenceNode:
        node = await self.session.get(EvidenceNode, node_id)
        if node is None:
            raise NotFoundError("节点不存在")
        return node

    async def list_nodes(self, cycle_id: uuid.UUID) -> list[EvidenceNode]:
        result = await self.session.execute(
            select(EvidenceNode)
            .where(EvidenceNode.cycle_id == cycle_id, EvidenceNode.archived_at.is_(None))
            .order_by(EvidenceNode.code)
        )
        return list(result.scalars().all())

    async def update_node(self, node_id: uuid.UUID, payload, updated_by: uuid.UUID) -> EvidenceNode:
        node = await self.get_node(node_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(node, field, value)
        node.updated_by = updated_by
        node.version = int(node.version) + 1
        self._outbox("evidence_node", node.id, node.version, "evidence.node.updated", self._node_payload(node))
        await self.session.commit()
        return node

    async def delete_node(self, node_id: uuid.UUID) -> None:
        node = await self.get_node(node_id)
        edge_count = len(
            (
                await self.session.execute(
                    select(EvidenceEdge).where(
                        (EvidenceEdge.source_node_id == node_id)
                        | (EvidenceEdge.target_node_id == node_id),
                        EvidenceEdge.archived_at.is_(None),
                    )
                )
            ).scalars().all()
        )
        if edge_count:
            raise AppError("节点被边引用，只能归档", code="NODE_HAS_EDGES", status_code=409)
        self._outbox("evidence_node", node.id, node.version, "evidence.node.deleted", self._node_payload(node))
        await self.session.delete(node)
        await self.session.commit()

    # -- edges ----------------------------------------------------------

    async def create_edge(self, project_id: uuid.UUID, payload, created_by: uuid.UUID) -> EvidenceEdge:
        if not is_relation(payload.relation):
            raise ValidationAppError("未知关系类型", code="INVALID_RELATION")
        if payload.relation == "related_to" and not payload.rationale:
            raise ValidationAppError("related_to 关系必须提供 rationale", code="RATIONALE_REQUIRED")
        source = await self.get_node(payload.source_node_id)
        target = await self.get_node(payload.target_node_id)
        if source.project_id != project_id or target.project_id != project_id:
            raise AppError("节点不属于该项目", code="CROSS_PROJECT_EDGE", status_code=403)
        if source.cycle_id != payload.cycle_id or target.cycle_id != payload.cycle_id:
            raise ValidationAppError("边必须属于同一周期", code="CROSS_CYCLE_EDGE")
        if source.id == target.id and not self_loop_allowed(payload.relation):
            raise ValidationAppError("该关系不允许自环", code="SELF_LOOP_FORBIDDEN")
        if not relation_allowed(source.node_type, payload.relation, target.node_type):
            raise ValidationAppError(
                f"{source.node_type} 不能 {payload.relation} {target.node_type}",
                code="INVALID_RELATION_FOR_TYPES",
            )

        duplicate = (
            await self.session.execute(
                select(EvidenceEdge).where(
                    EvidenceEdge.source_node_id == source.id,
                    EvidenceEdge.target_node_id == target.id,
                    EvidenceEdge.relation == payload.relation,
                    EvidenceEdge.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if duplicate:
            raise ValidationAppError("该关系已存在", code="EDGE_ALREADY_EXISTS")

        edge = EvidenceEdge(
            project_id=project_id,
            cycle_id=payload.cycle_id,
            source_node_id=source.id,
            target_node_id=target.id,
            relation=payload.relation,
            stance=payload.stance,
            confidence=payload.confidence,
            rationale=payload.rationale,
            created_by=created_by,
        )
        self.session.add(edge)
        await self.session.flush()

        if payload.relation == "contradicts":
            target.has_unresolved_contradiction = True

        self._outbox("evidence_edge", edge.id, edge.version, "evidence.edge.created", self._edge_payload(edge))
        await self.session.commit()
        return edge

    async def list_edges(self, cycle_id: uuid.UUID) -> list[EvidenceEdge]:
        result = await self.session.execute(
            select(EvidenceEdge).where(
                EvidenceEdge.cycle_id == cycle_id, EvidenceEdge.archived_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def update_edge(self, edge_id: uuid.UUID, payload) -> EvidenceEdge:
        edge = await self.session.get(EvidenceEdge, edge_id)
        if edge is None:
            raise NotFoundError("边不存在")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(edge, field, value)
        edge.version = int(edge.version) + 1
        await self.session.commit()
        return edge

    async def delete_edge(self, edge_id: uuid.UUID) -> None:
        edge = await self.session.get(EvidenceEdge, edge_id)
        if edge is None:
            raise NotFoundError("边不存在")
        self._outbox("evidence_edge", edge.id, edge.version, "evidence.edge.deleted", self._edge_payload(edge))
        await self.session.delete(edge)
        await self.session.commit()

    async def graph(self, cycle_id: uuid.UUID) -> dict:
        nodes = await self.list_nodes(cycle_id)
        edges = await self.list_edges(cycle_id)
        return {
            "nodes": [
                {
                    "id": str(n.id),
                    "code": n.code,
                    "node_type": n.node_type,
                    "title": n.title,
                    "status": n.status,
                    "confidence": float(n.confidence) if n.confidence is not None else None,
                    "has_unresolved_contradiction": n.has_unresolved_contradiction,
                    "layout_x": (n.meta or {}).get("layout_x", 0),
                    "layout_y": (n.meta or {}).get("layout_y", 0),
                }
                for n in nodes
            ],
            "edges": [
                {
                    "id": str(e.id),
                    "source": str(e.source_node_id),
                    "target": str(e.target_node_id),
                    "relation": e.relation,
                    "stance": e.stance,
                }
                for e in edges
            ],
        }

    # -- internals -------------------------------------------------------

    def _outbox(self, aggregate_type: str, aggregate_id: uuid.UUID, version: int, event_type: str, payload: dict) -> None:
        self.session.add(
            OutboxEvent(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=int(version),
                event_type=event_type,
                payload=payload,
            )
        )

    @staticmethod
    def _node_payload(node: EvidenceNode) -> dict:
        return {
            "id": str(node.id),
            "project_id": str(node.project_id),
            "cycle_id": str(node.cycle_id),
            "node_type": node.node_type,
            "code": node.code,
            "status": node.status,
        }

    @staticmethod
    def _edge_payload(edge: EvidenceEdge) -> dict:
        return {
            "id": str(edge.id),
            "project_id": str(edge.project_id),
            "cycle_id": str(edge.cycle_id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "relation": edge.relation,
        }
