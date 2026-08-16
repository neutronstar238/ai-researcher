"""Deterministic demo seed (spec §25).

Development/test only; must be run explicitly. Uses stable UUIDs so repeated
runs are idempotent. Phase 1 seeds identity/team/project/cycles; later phases
append lifecycle, candidates, evidence nodes, approvals and agent health.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import (
    AgentDefinition,
    AgentVersion,
    Approval,
    CycleCoverageSnapshot,
    EvidenceEdge,
    EvidenceNode,
    Experiment,
    LifecycleStage,
    Paper,
    Project,
    ProjectMember,
    ProjectPaper,
    ResearchAction,
    ResearchCycle,
    Team,
    TeamMember,
    TopicCandidate,
    User,
)
from app.db.session import dispose_engine, get_session_factory
from app.domains.lifecycle.service import LifecycleService

_NS = uuid.UUID("6b2e1a5e-0000-4000-8000-000000000001")

DEMO_PASSWORD = "demo-password"


def _sid(key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"ai-researcher:{key}")


USERS = [
    ("owner", "owner@airesearcher.local", "李研究员", "owner"),
    ("researcher", "researcher@airesearcher.local", "王科研", "researcher"),
    ("reviewer", "reviewer@airesearcher.local", "赵评审", "reviewer"),
    ("guest", "guest@airesearcher.local", "陈访客", "guest"),
]

TEAM_SLUG = "yanqi-zhilian"
PROJECT_SLUG = "protein-ligand-multimodal"


async def _upsert_user(session: AsyncSession, key: str, email: str, name: str) -> User:
    user_id = _sid(f"user:{key}")
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name=name,
        )
        session.add(user)
    return user


async def seed(session: AsyncSession) -> dict[str, int]:
    counts = {"users": 0, "cycles": 0}

    for key, email, name, _role in USERS:
        await _upsert_user(session, key, email, name)
        counts["users"] += 1
    await session.flush()

    team_id = _sid("team:main")
    team = await session.get(Team, team_id)
    if team is None:
        team = Team(
            id=team_id,
            name="研启智链研究组",
            slug=TEAM_SLUG,
            owner_user_id=_sid("user:owner"),
        )
        session.add(team)
        await session.flush()
        for key, _email, _name, _role in USERS:
            session.add(TeamMember(team_id=team_id, user_id=_sid(f"user:{key}"), role="member"))

    project_id = _sid("project:main")
    project = await session.get(Project, project_id)
    if project is None:
        project = Project(
            id=project_id,
            team_id=team_id,
            name="基于多模态表征学习的蛋白质-小分子相互作用预测",
            slug=PROJECT_SLUG,
            research_domain="计算生物学",
            objective="利用多模态表征学习提升蛋白质-小分子相互作用预测精度",
            created_by=_sid("user:owner"),
        )
        session.add(project)
        await session.flush()
        for key, _email, _name, role in USERS:
            session.add(ProjectMember(project_id=project_id, user_id=_sid(f"user:{key}"), role=role))

    # 3 个周期，第 3 周期 active（spec §25）
    existing = (
        await session.execute(
            select(ResearchCycle).where(ResearchCycle.project_id == project_id)
        )
    ).scalars().all()
    if not existing:
        for seq, name in ((1, "第 1 周期：方法调研"), (2, "第 2 周期：特征与基线"), (3, "第 3 周期：多模态表征学习")):
            cycle = ResearchCycle(
                id=_sid(f"cycle:{seq}"),
                project_id=project_id,
                sequence_no=seq,
                name=name,
                status="completed" if seq < 3 else "active",
                created_by=_sid("user:owner"),
            )
            session.add(cycle)
            counts["cycles"] += 1
        await session.flush()
        project.current_cycle_id = _sid("cycle:3")

    # 为每个周期初始化 8 阶段（spec §12.1）；第 3 周期按 §6.2 设置状态。
    lifecycle = LifecycleService(session)
    for seq in (1, 2, 3):
        cycle_id = _sid(f"cycle:{seq}")
        stages = await lifecycle.list_stages(cycle_id)
        if not stages:
            stages = await lifecycle.initialize_cycle(cycle_id)
        if seq == 3:
            _apply_cycle3_lifecycle(stages)
        elif seq < 3:
            for stage in stages:
                stage.status = "completed"
                stage.progress = 100

    # 第 3 周期：一条下一步行动 + 3 个选题候选（spec §25）
    cycle3 = _sid("cycle:3")
    action_exists = (
        await session.execute(
            select(ResearchAction).where(ResearchAction.cycle_id == cycle3).limit(1)
        )
    ).scalars().first()
    if action_exists is None:
        session.add(
            ResearchAction(
                project_id=project_id,
                cycle_id=cycle3,
                stage_key="experiment",
                title="完成实验组 S3 Docking 评估并汇总结果",
                description="运行 S3 实验组对接评估并汇总指标与产物",
                status="open",
                priority=1,
                assignee_user_id=_sid("user:researcher"),
            )
        )
    candidates = (await session.execute(select(TopicCandidate).where(TopicCandidate.cycle_id == cycle3))).scalars().all()
    if not candidates:
        for title, strength in (
            ("多模态大模型辅助蛋白质结构预测", 92),
            ("自动实验规划 Agent", 78),
            ("蛋白质-小分子结合亲和力图神经网络", 64),
        ):
            session.add(
                TopicCandidate(
                    project_id=project_id,
                    cycle_id=cycle3,
                    title=title,
                    evidence_strength=strength,
                    status="high_priority" if strength >= 90 else "exploring",
                )
            )

    # 3 条待审批（spec §25）与 6 个证据覆盖快照（spec §6.5 趋势）
    approvals = (await session.execute(select(Approval).where(Approval.project_id == project_id))).scalars().all()
    if not approvals:
        for atype, _subject, reason, risk in (
            ("experiment_run", "S3 实验组 Docking 评估执行", "运行高资源实验组 S3", "high"),
            ("data_import", "ArXiv 文献批量导入（48 篇）", "批量导入外部文献", "medium"),
            ("content_publish", "论文初稿章节发布（方法）", "发布方法章节初稿", "low"),
        ):
            session.add(
                Approval(
                    project_id=project_id,
                    approval_type=atype,
                    subject_type=atype.split("_")[0],
                    request_reason=reason,
                    risk_level=risk,
                    requested_by=_sid("user:researcher"),
                    assigned_to=_sid("user:owner"),
                )
            )

    snapshots = (await session.execute(select(CycleCoverageSnapshot).where(CycleCoverageSnapshot.project_id == project_id))).scalars().all()
    if not snapshots:
        for index, (label, coverage) in enumerate(
            (("T-5", 48), ("T-4", 55), ("T-3", 61), ("T-2", 67), ("T-1", 69), ("当前", 62))
        ):
            session.add(
                CycleCoverageSnapshot(
                    project_id=project_id, period_index=index, label=label, coverage=coverage
                )
            )

    # 证据主链 6 节点 + 1 篇反驳论文（spec §25/§7.4）
    nodes = (await session.execute(select(EvidenceNode).where(EvidenceNode.cycle_id == cycle3))).scalars().all()
    if not nodes:
        node_specs = [
            ("RQ1", "research_question", "多模态表征能否提升蛋白质-小分子相互作用预测？", 40, 40),
            ("P1", "paper", "多模态表征学习在药物发现中的综述", 220, 40),
            ("H1", "hypothesis", "多模态表征优于单模态分子指纹", 400, 40),
            ("E1", "experiment", "多模态 vs 单模态基准实验", 580, 40),
            ("V1", "validation", "验证：多模态表征显著提升 AUROC", 760, 40),
            ("C1", "claim", "多模态表征学习可提升相互作用预测精度", 940, 40),
            ("P2", "paper", "质疑多模态表征泛化性的对照研究", 220, 200),
        ]
        for code, ntype, title, x, y in node_specs:
            session.add(
                EvidenceNode(
                    id=_sid(f"node:{code}"),
                    project_id=project_id,
                    cycle_id=cycle3,
                    node_type=ntype,
                    code=code,
                    title=title,
                    status="validated" if code in {"V1", "C1"} else "active",
                    confidence=85,
                    meta={"layout_x": x, "layout_y": y},
                    created_by=_sid("user:owner"),
                )
            )
        await session.flush()

    edges = (await session.execute(select(EvidenceEdge).where(EvidenceEdge.cycle_id == cycle3))).scalars().all()
    if not edges:
        edge_specs = [
            ("P1", "H1", "supports", "supports"),
            ("H1", "E1", "tested_by", None),
            ("E1", "V1", "produces", None),
            ("V1", "C1", "supports", "supports"),
            ("P2", "C1", "contradicts", "contradicts"),
        ]
        for source, target, relation, stance in edge_specs:
            session.add(
                EvidenceEdge(
                    project_id=project_id,
                    cycle_id=cycle3,
                    source_node_id=_sid(f"node:{source}"),
                    target_node_id=_sid(f"node:{target}"),
                    relation=relation,
                    stance=stance,
                    created_by=_sid("user:owner"),
                )
            )
        # 反驳边 → 目标主张标记未解决矛盾
        c1 = await session.get(EvidenceNode, _sid("node:C1"))
        if c1:
            c1.has_unresolved_contradiction = True

    # 3 篇项目论文（spec §25 文献统计）
    project_papers = (await session.execute(select(ProjectPaper).where(ProjectPaper.project_id == project_id))).scalars().all()
    if not project_papers:
        for title, year, doi in (
            ("多模态表示学习在分子建模中的进展", 2023, "10.0000/demo.multimodal.1"),
            ("蛋白质-小分子相互作用的深度学习综述", 2024, "10.0000/demo.pli.2"),
            ("图神经网络用于分子性质预测", 2022, "10.0000/demo.gnn.3"),
        ):
            paper = Paper(doi=doi, title=title, publication_year=year, metadata_source="seed")
            session.add(paper)
            await session.flush()
            session.add(ProjectPaper(project_id=project_id, paper_id=paper.id, added_by=_sid("user:owner")))

    # 1 个可运行实验定义（spec §25/§15）
    experiments = (await session.execute(select(Experiment).where(Experiment.cycle_id == cycle3))).scalars().all()
    if not experiments:
        session.add(
            Experiment(
                project_id=project_id,
                cycle_id=cycle3,
                code="E1",
                name="多模态 vs 单模态基准实验",
                objective="验证多模态表征是否优于单模态分子指纹",
                entrypoint='python -c "import json; print(json.dumps({\'mean\': 0.62, \'std\': 0.03}))"',
                status="active",
                created_by=_sid("user:owner"),
            )
        )

    # 6 个 Agent 定义 + 激活版本（spec §16.1）
    agents = (await session.execute(select(AgentDefinition).where(AgentDefinition.team_id == team_id))).scalars().all()
    if not agents:
        agent_specs = [
            ("research-planner", "Research Planner", "分解研究目标、生成计划与阶段建议"),
            ("discovery", "Discovery Agent", "检索趋势、生成选题候选"),
            ("literature", "Literature Agent", "查询、筛选、摘要、证据抽取"),
            ("evidence", "Evidence Agent", "建议节点、关系、矛盾"),
            ("experiment", "Experiment Agent", "设计实验、分析运行"),
            ("writing", "Writing Agent", "基于证据生成文档 Diff"),
        ]
        for key, display_name, description in agent_specs:
            agent = AgentDefinition(
                id=_sid(f"agent:{key}"),
                team_id=team_id,
                key=key,
                display_name=display_name,
                description=description,
                created_by=_sid("user:owner"),
            )
            session.add(agent)
            await session.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version_no=1,
                role_prompt=f"你是 {display_name}，遵循证据优先原则。",
                tool_policy={"allowed_tools": ["project.read"]},
                budget_policy={"max_tokens": 30000, "max_cost": 1.0, "max_tool_calls": 20},
                created_by=_sid("user:owner"),
            )
            session.add(version)
            await session.flush()
            agent.active_version_id = version.id

    await session.commit()
    return counts


def _apply_cycle3_lifecycle(stages: list[LifecycleStage]) -> None:
    """第 3 周期生命周期状态（spec §6.2）：选题/文献/假设完成，实验进行中 62%。"""
    settings = {
        "topic": ("completed", 100, 0),
        "literature": ("completed", 100, 532),
        "hypothesis": ("completed", 100, 4),
        "experiment": ("running", 62, 0),
    }
    for stage in stages:
        if stage.stage_key in settings:
            status, progress, evidence = settings[stage.stage_key]
            stage.status = status
            stage.progress = progress
            stage.evidence_count = evidence


async def _main(profile: str) -> int:
    if profile != "demo":
        raise SystemExit("only the 'demo' profile is supported")
    factory = get_session_factory()
    async with factory() as session:
        counts = await seed(session)
    await dispose_engine()
    print(f"seeded: {counts}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-Researcher deterministic seed")
    parser.add_argument("--profile", default="demo", choices=["demo"])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.profile)))


if __name__ == "__main__":
    main()
