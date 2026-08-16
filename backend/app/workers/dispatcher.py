"""Outbox dispatcher: project PostgreSQL evidence state to Neo4j (spec §3.4/§11.9).

Two entry points:
- ``--dispatch``: process unpublished ``outbox_events`` (at-least-once, idempotent).
- ``--rebuild <project_id>``: clear + re-project one project's evidence graph.

Consumers are idempotent: upserts key on ``source_id``/``source_edge_id`` and
stale versions never overwrite newer state (§3.4.4). Neo4j failure does not
roll back the committed business fact (§3.4.3).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import EvidenceEdge, EvidenceNode, OutboxEvent
from app.db.session import dispose_engine, get_session_factory
from app.integrations.graph.neo4j import Neo4jProjection


def _node_payload(node: EvidenceNode) -> dict:
    return {
        "source_id": str(node.id),
        "project_id": str(node.project_id),
        "cycle_id": str(node.cycle_id),
        "type": node.node_type,
        "code": node.code,
        "title": node.title[:2000],
        "status": node.status,
        "confidence": float(node.confidence) if node.confidence is not None else None,
        "source_version": int(node.version),
    }


def _edge_payload(edge: EvidenceEdge) -> dict:
    return {
        "source_edge_id": str(edge.id),
        "source_id": str(edge.source_node_id),
        "target_id": str(edge.target_node_id),
        "type": edge.relation,
        "stance": edge.stance,
        "confidence": float(edge.confidence) if edge.confidence is not None else None,
        "source_version": int(edge.version),
    }


async def dispatch_pending() -> int:
    factory = get_session_factory()
    graph = Neo4jProjection()
    processed = 0
    try:
        async with factory() as session:
            events = (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.created_at)
                    .limit(500)
                )
            ).scalars().all()
            for event in events:
                await _project_event(session, graph, event)
                event.published_at = datetime.now(UTC)
                event.attempt_count = int(event.attempt_count) + 1
                processed += 1
            await session.commit()
    finally:
        await graph.close()
    return processed


async def _project_event(session, graph: Neo4jProjection, event: OutboxEvent) -> None:
    if event.aggregate_type == "evidence_node":
        node = await session.get(EvidenceNode, event.aggregate_id)
        if node is None or node.archived_at is not None:
            await graph.delete_node(str(event.aggregate_id))
        else:
            await graph.upsert_node(_node_payload(node))
    elif event.aggregate_type == "evidence_edge":
        edge = await session.get(EvidenceEdge, event.aggregate_id)
        if edge is None or edge.archived_at is not None:
            await graph.delete_edge(str(event.aggregate_id))
        else:
            await graph.upsert_edge(_edge_payload(edge))


async def rebuild_project(project_id: uuid.UUID) -> dict:
    factory = get_session_factory()
    graph = Neo4jProjection()
    try:
        async with factory() as session:
            nodes = (
                await session.execute(
                    select(EvidenceNode).where(
                        EvidenceNode.project_id == project_id, EvidenceNode.archived_at.is_(None)
                    )
                )
            ).scalars().all()
            edges = (
                await session.execute(
                    select(EvidenceEdge).where(
                        EvidenceEdge.project_id == project_id, EvidenceEdge.archived_at.is_(None)
                    )
                )
            ).scalars().all()

            await graph.clear_project(str(project_id))
            for node in nodes:
                await graph.upsert_node(_node_payload(node))
            for edge in edges:
                await graph.upsert_edge(_edge_payload(edge))
        return {
            "project_id": str(project_id),
            "nodes": len(nodes),
            "edges": len(edges),
            "neo4j_nodes": await graph.count_nodes(str(project_id)),
            "neo4j_edges": await graph.count_edges(str(project_id)),
        }
    finally:
        await graph.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-Researcher outbox dispatcher")
    parser.add_argument("--dispatch", action="store_true", help="process unpublished outbox events")
    parser.add_argument("--rebuild", type=uuid.UUID, default=None, help="rebuild a project's Neo4j projection")
    args = parser.parse_args()
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.rebuild:
            result = await rebuild_project(args.rebuild)
            print(f"rebuilt: {result}")
        elif args.dispatch:
            processed = await dispatch_pending()
            print(f"dispatched: {processed} events")
        else:
            raise SystemExit("provide --dispatch or --rebuild <project_id>")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    main()
