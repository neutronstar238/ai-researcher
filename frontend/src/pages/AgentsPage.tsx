import { useState } from "react";
import { useParams } from "react-router-dom";

import { useAgentTasks, useAgents, useCreateTask, useRunTask, useTaskAction } from "../features/agents/api";
import { useTeams } from "../features/projects/api";

const STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  waiting_approval: "等待审批",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-surface-subtle text-text-muted",
  running: "bg-primary-soft text-primary",
  succeeded: "bg-success-soft text-success",
  failed: "bg-danger-soft text-danger",
  cancelled: "bg-surface-subtle text-text-muted",
  waiting_approval: "bg-warning-soft text-warning",
};

export function AgentsPage() {
  const { projectId } = useParams();
  const { data: teams } = useTeams();
  const teamId = teams?.[0]?.id;
  const { data: agents } = useAgents(projectId, teamId);
  const { data: tasks } = useAgentTasks(projectId);
  const createTask = useCreateTask(projectId);
  const action = useTaskAction(projectId);
  const runTask = useRunTask(projectId);

  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [taskType, setTaskType] = useState("literature_review");
  const [feedback, setFeedback] = useState<string | null>(null);

  async function handleCreate() {
    const agent = agents?.find((a) => a.id === selectedAgent);
    if (!agent?.active_version_id) {
      setFeedback("所选智能体无激活版本");
      return;
    }
    setFeedback(null);
    try {
      await createTask.mutateAsync({ agent_version_id: agent.active_version_id, task_type: taskType });
      setFeedback(`已创建任务「${taskType}」`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "创建任务失败");
    }
  }

  async function handleAction(taskId: string, taskAction: "cancel" | "retry") {
    setFeedback(null);
    try {
      await action.mutateAsync({ taskId, action: taskAction });
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleRun(taskId: string) {
    setFeedback(null);
    try {
      const task = await runTask.mutateAsync(taskId);
      setFeedback(`任务执行完成：${task.status}${task.error ? `（${JSON.stringify(task.error)}）` : ""}`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "执行失败");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">智能体中心</h2>
        <span className="text-xs text-text-muted">创建任务后点击「运行」调用已配置的 LLM 真实执行；未配置 Provider 时明确返回「未配置」而非伪造</span>
      </div>

      {feedback && <div className="rounded-md bg-surface-subtle px-3 py-2 text-sm text-text-secondary">{feedback}</div>}

      <section className="card">
        <h3 className="text-sm font-semibold text-text">启动任务</h3>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="min-w-[200px] flex-1">
            <span className="mb-1 block text-xs text-text-muted">智能体</span>
            <select value={selectedAgent ?? ""} onChange={(e) => setSelectedAgent(e.target.value)} className="w-full rounded-md border border-border-strong px-3 py-2 text-sm">
              <option value="">选择智能体…</option>
              {agents?.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.display_name}（{agent.key}）</option>
              ))}
            </select>
          </label>
          <label className="min-w-[200px] flex-1">
            <span className="mb-1 block text-xs text-text-muted">任务类型</span>
            <select value={taskType} onChange={(e) => setTaskType(e.target.value)} className="w-full rounded-md border border-border-strong px-3 py-2 text-sm">
              <option value="literature_review">文献综述</option>
              <option value="hypothesis_generation">假设生成</option>
              <option value="experiment_planning">实验规划</option>
              <option value="paper_writing">论文写作</option>
            </select>
          </label>
          <button type="button" onClick={handleCreate} disabled={!selectedAgent || createTask.isPending} className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50">
            {createTask.isPending ? "创建中…" : "启动"}
          </button>
        </div>
      </section>

      <section className="card">
        <h3 className="text-sm font-semibold text-text">智能体（{agents?.length ?? 0}）</h3>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {agents?.map((agent) => (
            <div key={agent.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-text">{agent.display_name}</span>
                <span className="rounded bg-success-soft px-1.5 py-0.5 text-xs text-success">{agent.status}</span>
              </div>
              <div className="mt-1 text-xs text-text-muted">{agent.description ?? "—"}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h3 className="text-sm font-semibold text-text">任务（{tasks?.length ?? 0}）</h3>
        <div className="mt-3 space-y-2">
          {tasks?.map((task) => {
            return (
              <div key={task.id} className="rounded-md border border-border px-3 py-2">
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <div className="text-sm text-text">{task.task_type}</div>
                    <div className="text-xs text-text-muted">
                      尝试 {task.attempt} · {new Date(task.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[task.status] ?? "bg-surface-subtle text-text-muted"}`}>
                      {STATUS_LABELS[task.status] ?? task.status}
                    </span>
                    {task.status === "queued" && (
                      <button type="button" onClick={() => handleRun(task.id)} disabled={runTask.isPending} className="rounded-md bg-primary px-2 py-1 text-xs text-white disabled:opacity-50">
                        {runTask.isPending ? "执行中…" : "运行"}
                      </button>
                    )}
                    {task.status === "running" && (
                      <button type="button" onClick={() => handleAction(task.id, "cancel")} disabled={action.isPending} className="rounded-md border border-border-strong px-2 py-1 text-xs text-text-secondary">取消</button>
                    )}
                    {task.status === "failed" && (
                      <button type="button" onClick={() => handleAction(task.id, "retry")} disabled={action.isPending} className="rounded-md bg-primary-soft px-2 py-1 text-xs text-primary">重试</button>
                    )}
                  </div>
                </div>
                {task.output && (
                  <div className="mt-2 max-h-24 overflow-auto rounded bg-surface-subtle px-2 py-1 text-xs text-text-secondary">
                    {typeof task.output === "object"
                      ? Object.values(task.output).join(" ").slice(0, 300)
                      : String(task.output).slice(0, 300)}
                  </div>
                )}
              </div>
            );
          })}
          {tasks?.length === 0 && <p className="py-6 text-center text-xs text-text-muted">暂无任务</p>}
        </div>
      </section>
    </div>
  );
}
