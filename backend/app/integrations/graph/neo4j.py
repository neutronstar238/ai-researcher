"""Neo4j projection client (spec §11.9).

Neo4j is a queryable projection of PostgreSQL business state, never the source
of truth. Every node/relationship carries ``source_id``/``source_edge_id`` and
``source_version`` so the dispatcher can upsert idempotently and reject stale
events (§3.4.4). All writes go through PostgreSQL first.
"""

from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import get_settings


class Neo4jProjection:
    def __init__(self) -> None:
        settings = get_settings()
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )

    async def close(self) -> None:
        await self.driver.close()

    async def upsert_node(self, node: dict) -> None:
        query = """
        MERGE (n:EvidenceNode {source_id: $source_id})
        SET n.project_id = $project_id,
            n.cycle_id = $cycle_id,
            n.type = $type,
            n.code = $code,
            n.title = $title,
            n.status = $status,
            n.confidence = $confidence,
            n.source_version = $source_version
        """
        await self._run(query, **node)

    async def delete_node(self, source_id: str) -> None:
        await self._run(
            "MATCH (n:EvidenceNode {source_id: $source_id}) DETACH DELETE n", source_id=source_id
        )

    async def upsert_edge(self, edge: dict) -> None:
        rel_type = str(edge["type"]).upper()
        query = f"""
        MATCH (a:EvidenceNode {{source_id: $source_id}})
        MATCH (b:EvidenceNode {{source_id: $target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r.source_edge_id = $source_edge_id,
            r.type = $type,
            r.stance = $stance,
            r.confidence = $confidence,
            r.source_version = $source_version
        """
        await self._run(query, **edge)

    async def delete_edge(self, source_edge_id: str) -> None:
        await self._run(
            "MATCH ()-[r]->() WHERE r.source_edge_id = $source_edge_id DELETE r",
            source_edge_id=source_edge_id,
        )

    async def clear_project(self, project_id: str) -> None:
        await self._run(
            "MATCH (n:EvidenceNode {project_id: $project_id}) DETACH DELETE n", project_id=project_id
        )

    async def count_nodes(self, project_id: str) -> int:
        record = await self._single(
            "MATCH (n:EvidenceNode {project_id: $project_id}) RETURN count(n) AS c",
            project_id=project_id,
        )
        return int(record["c"]) if record else 0

    async def count_edges(self, project_id: str) -> int:
        record = await self._single(
            "MATCH (a:EvidenceNode {project_id: $project_id})-[r]->(b) RETURN count(r) AS c",
            project_id=project_id,
        )
        return int(record["c"]) if record else 0

    async def _run(self, query: str, **params: object) -> None:
        async with self.driver.session() as session:
            await session.run(query, **params)

    async def _single(self, query: str, **params: object):
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return await result.single()
