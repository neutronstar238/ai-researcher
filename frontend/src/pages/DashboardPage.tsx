import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { ApprovalTable } from "../components/dashboard/ApprovalTable";
import { DiscoveryTable } from "../components/dashboard/DiscoveryTable";
import { EvidenceCoverageChart } from "../components/dashboard/EvidenceCoverageChart";
import { LifecycleTimeline } from "../components/lifecycle/LifecycleTimeline";
import {
  useApprovals,
  useCoverage,
  useDashboard,
  useHealthReady,
  useHealthSummary,
  useTopicCandidates,
} from "../features/dashboard/api";
import { useProjectStore } from "../stores/projectStore";

const CHECK_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
};

function statusColor(status: string): string {
  if (status === "healthy") return "text-success";
  if (status === "degraded") return "text-warning";
  return "text-danger";
}

export function DashboardPage() {
  const { projectId } = useParams();
  const setCurrentProject = useProjectStore((state) => state.setCurrentProject);
  const ready = useHealthReady();
  const summary = useHealthSummary();
  const dashboard = useDashboard(projectId);
  const candidates = useTopicCandidates(projectId);
  const approvals = useApprovals(projectId);
  const coverage = useCoverage(projectId);

  useEffect(() => {
    setCurrentProject(projectId ?? null);
    return () => setCurrentProject(null);
  }, [projectId, setCurrentProject]);

  if (dashboard.isLoading) {
    return <div className="card h-40 animate-pulse bg-surface-subtle" />;
  }
  if (dashboard.isError) {
    return (
      <div className="card">
        <h2 className="text-lg font-semibold text-text">Dashboard 不可用</h2>
        <p className="mt-2 text-sm text-danger">{(dashboard.error as Error).message}</p>
      </div>
    );
  }

  const { project, lifecycle, statistics } = dashboard.data!;

  return (
    <div className="space-y-4">
      {/* 科研生命周期（§6.2） */}
      <section className="card">
        <h2 className="mb-6 text-lg font-semibold text-text">科研生命周期</h2>
        <LifecycleTimeline stages={lifecycle} />
      </section>

      <div className="grid grid-cols-2 gap-4">
        {/* 当前项目（§6.3） */}
        <section className="card">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-text">当前项目</h2>
            <span className="rounded-full bg-success-soft px-3 py-1 text-xs text-success">
              {project.status === "active" ? "进行中" : project.status}
            </span>
          </div>
          <div className="mt-3 text-[15px] font-semibold text-text">{project.name}</div>
          <div className="mt-1 text-sm text-text-muted">
            {project.research_domain ?? "未设置研究领域"}
          </div>

          <div className="mt-4 flex items-center gap-4">
            <div className="h-2 w-44 overflow-hidden rounded-full bg-track">
              <div className="h-full rounded-full bg-primary" style={{ width: `${project.progress_percent}%` }} />
            </div>
            <span className="tabular-nums text-sm font-semibold text-primary">
              {project.progress_percent}%
            </span>
          </div>

          {project.next_action && (
            <div className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-sm">
              <span className="font-medium text-text">下一步行动：</span>
              <span className="text-text-secondary">{project.next_action.title}</span>
            </div>
          )}

          <div className="mt-4 grid grid-cols-4 gap-3">
            {[
              ["文献证据", statistics.papers],
              ["实验运行", statistics.experiment_runs],
              ["数据集", statistics.datasets],
              ["图表", statistics.figures],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded-md border border-border px-3 py-2">
                <div className="tabular-nums text-[22px] font-bold text-brand-dark">{value}</div>
                <div className="text-xs text-text-muted">{label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* 今日发现 / 本周选题（§6.4） */}
        <section className="card">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-text">今日发现 / 本周选题</h2>
            <button type="button" className="text-sm text-primary">查看全部</button>
          </div>
          <DiscoveryTable projectId={projectId!} candidates={candidates.data ?? []} />
        </section>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* 研究证据覆盖趋势（§6.5） */}
        <section className="card">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-text">研究证据覆盖趋势</h2>
            <span className="text-xs text-text-muted">最近 6 周期</span>
          </div>
          {coverage.data && coverage.data.length ? (
            <EvidenceCoverageChart data={coverage.data} />
          ) : (
            <p className="py-12 text-center text-sm text-text-muted">尚无可计算主张</p>
          )}
        </section>

        {/* 待审批（§6.6） */}
        <section className="card">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-text">待审批</h2>
            <span className="tabular-nums text-xs text-text-muted">{approvals.data?.length ?? 0} 项</span>
          </div>
          <ApprovalTable projectId={projectId!} approvals={approvals.data ?? []} />
        </section>
      </div>

      {/* 系统状态（§6.7） */}
      <section className="card">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text">系统状态</h2>
          <span className={`text-sm font-medium ${ready.data?.status === "ready" ? "text-success" : "text-warning"}`}>
            {ready.data?.status === "ready" ? "就绪" : "降级"}
          </span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4">
          {Object.entries(ready.data?.checks ?? {}).map(([key, check]) => (
            <div key={key} className="flex items-center justify-between rounded-md border border-border px-4 py-3">
              <span className="text-sm text-text-secondary">{CHECK_LABELS[key] ?? key}</span>
              <span className={`text-sm font-medium ${statusColor(check.status)}`}>
                {check.status === "healthy" ? "正常" : check.status}
              </span>
            </div>
          ))}
        </div>
        {summary.data && (
          <div className="mt-4 flex flex-wrap gap-3 text-xs text-text-muted">
            <span>LLM 模型：{summary.data.llm_configured ? "已配置" : "未配置"}</span>
            <span>Embedding：{summary.data.embedding_configured ? "已配置" : "未配置"}</span>
            <span>实验运行器：{summary.data.experiment_runner_configured ? "已配置" : "未配置"}</span>
          </div>
        )}
      </section>
    </div>
  );
}
