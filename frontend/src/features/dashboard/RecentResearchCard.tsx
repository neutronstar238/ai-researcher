import type { RunRecord } from "../../lib/api/types";
import { coveragePercent } from "../../lib/domain/selectors";

const STATUS_LABELS: Record<RunRecord["status"], string> = {
  cancel_requested: "正在取消",
  canceled: "已取消",
  completed: "已完成",
  dry_run: "试运行",
  failed: "失败",
  interrupted: "已中断",
  queued: "排队中",
  running: "进行中",
};

function runTime(run: RunRecord): number {
  const value = Date.parse(run.finished_at ?? run.started_at ?? run.created_at);
  return Number.isNaN(value) ? 0 : value;
}

function formatDate(run: RunRecord): string {
  const timestamp = runTime(run);
  return timestamp === 0
    ? "未提供"
    : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(timestamp);
}

interface RecentResearchCardProps {
  runs: RunRecord[];
  onOpenRun(runId: string): void;
}

export function RecentResearchCard({ runs, onOpenRun }: RecentResearchCardProps) {
  const recentRuns = [...runs]
    .sort((left, right) => runTime(right) - runTime(left) || left.run_id.localeCompare(right.run_id))
    .slice(0, 5);

  return (
    <section className="dashboard-card dashboard-primary-card recent-research-card" aria-labelledby="recent-research-heading">
      <h2 id="recent-research-heading">近期研究</h2>
      {recentRuns.length === 0 ? (
        <p className="card-empty-message">有研究运行后将在这里显示。</p>
      ) : (
        <div className="table-scroll">
          <table className="dashboard-table" aria-label="近期研究">
            <thead><tr><th>研究方向</th><th>状态</th><th>阶段覆盖</th><th>更新时间</th></tr></thead>
            <tbody>
              {recentRuns.map((run) => {
                const coverage = coveragePercent(run.stages ?? []);
                return (
                  <tr key={run.run_id}>
                    <th scope="row">
                      <button type="button" onClick={() => onOpenRun(run.run_id)} aria-label={`打开${run.direction}`}>
                        {run.direction}
                      </button>
                    </th>
                    <td><span className="status-badge" data-status={run.status}>{STATUS_LABELS[run.status]}</span></td>
                    <td>{coverage === null ? "未提供" : `${coverage}%`}</td>
                    <td><time>{formatDate(run)}</time></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
