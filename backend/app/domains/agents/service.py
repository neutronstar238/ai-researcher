"""Agent application service (spec §16).

Phase 5：Agent 定义/版本、任务生命周期（状态机）、工具调用审计（风险分级 +
审批门禁）、预算纯函数 + 真实 LLM 编排（``run_task``：单轮 LLM 调用，OpenAI 兼容）。
完整 Orchestrator DAG（工具调用回环）仍待后续切片。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError
from app.core.agents import (
    TOOL_REGISTRY,
    is_allowed_task_transition,
    tool_requires_approval,
    tool_risk_level,
    tool_spec,
)
from app.db.models import (
    AgentDefinition,
    AgentTask,
    AgentToolCall,
    AgentVersion,
    Approval,
    EvidenceNode,
    Project,
)
from app.domains.agents.schemas import ToolCallIn
from app.domains.audit.service import record_audit
from app.domains.lifecycle.service import LifecycleService
from app.integrations.llm.base import get_provider


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- definitions ----------------------------------------------------

    async def list_agents(self, team_id: uuid.UUID) -> list[AgentDefinition]:
        result = await self.session.execute(
            select(AgentDefinition).where(AgentDefinition.team_id == team_id)
        )
        return list(result.scalars().all())

    async def get_agent(self, agent_id: uuid.UUID) -> AgentDefinition:
        agent = await self.session.get(AgentDefinition, agent_id)
        if agent is None:
            raise NotFoundError("Agent 不存在")
        return agent

    async def list_versions(self, agent_id: uuid.UUID) -> list[AgentVersion]:
        result = await self.session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no)
        )
        return list(result.scalars().all())

    # -- tasks ----------------------------------------------------------

    async def create_task(self, project_id: uuid.UUID, payload, requested_by: uuid.UUID) -> AgentTask:
        version = await self.session.get(AgentVersion, payload.agent_version_id)
        if version is None:
            raise NotFoundError("Agent 版本不存在")
        task = AgentTask(
            project_id=project_id,
            agent_version_id=payload.agent_version_id,
            task_type=payload.task_type,
            input=payload.input,
            budget=payload.budget or version.budget_policy,
            requested_by=requested_by,
        )
        self.session.add(task)
        await self.session.flush()
        record_audit(
            self.session,
            action="agent.task.created",
            actor_id=requested_by,
            project_id=project_id,
            target_type="agent_task",
            target_id=task.id,
        )
        await self.session.commit()
        return task

    async def get_task(self, task_id: uuid.UUID) -> AgentTask:
        task = await self.session.get(AgentTask, task_id)
        if task is None:
            raise NotFoundError("任务不存在")
        return task

    async def list_tasks(self, project_id: uuid.UUID) -> list[AgentTask]:
        result = await self.session.execute(
            select(AgentTask)
            .where(AgentTask.project_id == project_id)
            .order_by(AgentTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def cancel_task(self, task_id: uuid.UUID) -> AgentTask:
        task = await self.get_task(task_id)
        self._assert_transition(task, "cancelled")
        task.status = "cancelled"
        task.finished_at = datetime.now(UTC)
        await self.session.commit()
        return task

    async def retry_task(self, task_id: uuid.UUID) -> AgentTask:
        task = await self.get_task(task_id)
        self._assert_transition(task, "queued")
        task.status = "queued"
        task.attempt = int(task.attempt) + 1
        task.finished_at = None
        await self.session.commit()
        return task

    # -- 真实 LLM 编排（§16 Orchestrator：多轮工具调用回环）---------------

    DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["tool_call", "done"]},
            "tool_name": {"type": "string"},
            "arguments": {"type": "object"},
            "output": {"type": "object"},
            "reasoning": {"type": "string"},
        },
        "required": ["action"],
    }

    async def run_task(self, task_id: uuid.UUID, max_turns: int = 5) -> AgentTask:
        task = await self.get_task(task_id)
        self._assert_transition(task, "running")
        version = await self.session.get(AgentVersion, task.agent_version_id)
        if version is None:
            raise NotFoundError("Agent 版本不存在")

        task.status = "running"
        task.started_at = datetime.now(UTC)
        await self.session.commit()

        history: list[dict] = []
        usage_total: dict = {}
        final_output: dict | None = None

        try:
            provider = get_provider(version.model_provider)
            for _ in range(max_turns):
                prompt = self._build_orchestrator_prompt(task, version, history)
                response = await provider.complete(prompt, json_schema=self.DECISION_SCHEMA)
                usage_total = self._merge_usage(usage_total, response.usage)
                decision = response.structured or {}

                if decision.get("action") == "done":
                    final_output = decision.get("output") or {"content": response.content}
                    break

                tool_name = decision.get("tool_name") or ""
                arguments = decision.get("arguments") or {}
                result, waiting = await self._execute_tool(task, tool_name, arguments)
                history.append({"assistant": decision})
                history.append({"tool": result})
                if waiting:
                    break

            if task.status == "waiting_approval":
                task.output = {"content": "任务因高风险工具待审批而暂停", "status": "waiting_approval"}
            else:
                task.output = final_output or {"content": "达到最大轮数，未产出最终结果"}
            task.token_usage = usage_total or None
            if task.status != "waiting_approval":
                task.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - 结构化记录失败，不伪造输出
            task.status = "failed"
            task.error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        finally:
            task.finished_at = datetime.now(UTC)
            await self.session.commit()
        return task

    async def _execute_tool(self, task: AgentTask, tool_name: str, arguments: dict) -> tuple[dict, bool]:
        spec = tool_spec(tool_name)  # 未知工具抛 ValidationAppError
        call = await self.record_tool_call(
            task.id,
            ToolCallIn(tool_name=tool_name, arguments=arguments),
            task.project_id,
            task.requested_by,
        )
        if call.status == "waiting_approval":
            task.status = "waiting_approval"
            return {"requires_approval": True, "tool": tool_name, "risk": spec.risk_level}, True

        # 真实执行低风险工具（读/写低风险）；其余诚实标注未接入真实副作用
        if tool_name == "project.read":
            return {"result": await self._tool_project_read(task.project_id)}, False
        if tool_name == "evidence.propose":
            node = await self._tool_evidence_propose(task, arguments)
            return {"result": {"node_id": str(node.id), "code": node.code}}, False
        return {"result": {"tool": tool_name, "note": "工具已记录；真实副作用执行未接入"}}, False

    async def _tool_project_read(self, project_id: uuid.UUID) -> dict:
        project = await self.session.get(Project, project_id)
        current_stage = None
        if project is not None and project.current_cycle_id is not None:
            stages = await LifecycleService(self.session).list_stages(project.current_cycle_id)
            for stage in stages:
                if stage.status in {"running", "waiting_approval", "blocked"}:
                    current_stage = stage.stage_key
                    break
        return {
            "name": project.name if project else None,
            "research_domain": project.research_domain if project else None,
            "current_stage": current_stage,
        }

    async def _tool_evidence_propose(self, task: AgentTask, arguments: dict) -> EvidenceNode:
        project = await self.session.get(Project, task.project_id)
        cycle_id = task.cycle_id or (project.current_cycle_id if project else None)
        if cycle_id is None:
            raise ValidationAppError("无法确定证据节点所属周期", code="NO_CYCLE")
        node = EvidenceNode(
            project_id=task.project_id,
            cycle_id=cycle_id,
            node_type=arguments.get("node_type", "evidence"),
            code=arguments.get("code") or f"AUTO-{uuid.uuid4().hex[:8]}",
            title=arguments.get("title") or "Agent 提议证据",
            description=arguments.get("description"),
            status="draft",
            created_by=task.requested_by,
        )
        self.session.add(node)
        await self.session.commit()
        return node

    @staticmethod
    def _build_orchestrator_prompt(task: AgentTask, version: AgentVersion, history: list[dict]) -> str:
        tools = [
            {"name": t.name, "description": t.description, "risk": t.risk_level}
            for t in TOOL_REGISTRY.values()
        ]
        parts: list[str] = []
        if version.role_prompt:
            parts.append(version.role_prompt)
        parts.append(f"任务类型：{task.task_type}")
        parts.append(f"任务输入：{json.dumps(task.input or {}, ensure_ascii=False)}")
        parts.append(f"可用工具：{json.dumps(tools, ensure_ascii=False)}")
        if history:
            parts.append(f"历史：{json.dumps(history, ensure_ascii=False)}")
        parts.append("决定下一步：调用工具（tool_call）或完成（done）。")
        return "\n\n".join(parts)

    @staticmethod
    def _merge_usage(total: dict, usage: dict | None) -> dict:
        out = dict(total)
        if not usage:
            return out
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if usage.get(key) is not None:
                out[key] = int(out.get(key) or 0) + int(usage[key])
        return out

    # -- tool calls -----------------------------------------------------

    async def record_tool_call(
        self, task_id: uuid.UUID, payload, project_id: uuid.UUID, actor_id: uuid.UUID
    ) -> AgentToolCall:
        await self.get_task(task_id)
        risk_level = tool_risk_level(payload.tool_name)
        requires_approval = tool_requires_approval(payload.tool_name)

        approval_id: uuid.UUID | None = None
        status = "queued"
        if requires_approval:
            approval = Approval(
                project_id=project_id,
                approval_type=f"agent_tool:{payload.tool_name}",
                subject_type="agent_tool_call",
                request_reason=f"Agent 请求调用高风险工具 {payload.tool_name}",
                risk_level="high" if risk_level == "external_side_effect" else "medium",
                requested_by=actor_id,
            )
            self.session.add(approval)
            await self.session.flush()
            approval_id = approval.id
            status = "waiting_approval"

        call = AgentToolCall(
            task_id=task_id,
            step_id=payload.step_id,
            tool_name=payload.tool_name,
            risk_level=risk_level,
            arguments_redacted=payload.arguments,
            status=status,
            approval_id=approval_id,
        )
        self.session.add(call)
        await self.session.flush()
        if requires_approval:
            record_audit(
                self.session,
                action="agent.tool_call.high_risk",
                actor_id=actor_id,
                project_id=project_id,
                target_type="agent_tool_call",
                target_id=call.id,
                after_redacted={"tool_name": payload.tool_name, "risk_level": risk_level},
            )
        await self.session.commit()
        return call

    async def list_tool_calls(self, task_id: uuid.UUID) -> list[AgentToolCall]:
        result = await self.session.execute(
            select(AgentToolCall).where(AgentToolCall.task_id == task_id).order_by(AgentToolCall.id)
        )
        return list(result.scalars().all())

    @staticmethod
    def _assert_transition(task: AgentTask, target: str) -> None:
        if not is_allowed_task_transition(task.status, target):
            raise AppError(
                f"任务不允许从 {task.status} 转换到 {target}",
                code="ILLEGAL_TASK_TRANSITION",
                status_code=409,
            )
