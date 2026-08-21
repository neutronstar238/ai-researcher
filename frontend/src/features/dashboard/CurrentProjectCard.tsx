import type { RunRecord } from "../../lib/api/types";
import { toProductLifecycle, type ProductStage } from "../../lib/domain/lifecycle";
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

const STAGE_STATE_LABELS: Record<ProductStage["state"], string> = {
  active: "进行中",
  blocked: "阻塞",
  completed: "已完成",
  pending: "待开始",
};

function formatDate(value: string | null): string {
  if (!value) return "未提供";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未提供";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

interface CurrentProjectCardProps {
  run: RunRecord | null;
  refreshError?: Error | null;
  onCreateRun(): void;
  onOpenRun(runId: string): void;
  onRetryDetails?(): void;
}

export function CurrentProjectCard({
  run,
  refreshError = null,
  onCreateRun,
  onOpenRun,
  onRetryDetails = () => undefined,
}: CurrentProjectCardProps) {
  if (!run) {
    return (
      <section className="dashboard-card dashboard-primary-card current-project-card" aria-labelledby="current-project-heading">
        <h2 id="current-project-heading">当前项目</h2>
        <div className="dashboard-empty">
          <strong>还没有研究运行</strong>
          <p>前往项目空间填写真实研究问题并创建运行。</p>
          <button className="button-primary" type="button" onClick={onCreateRun}>新建研究</button>
        </div>
      </section>
    );
  }

  const coverage = coveragePercent(run.stages ?? []);
  const updatedAt = run.finished_at ?? run.started_at ?? run.created_at;
  const lifecycle = run.stages === undefined
    ? []
    : toProductLifecycle(run.stages, run.status, null);
  const currentStage = lifecycle.find((stage) => stage.state === "active" || stage.state === "blocked")
    ?? lifecycle.find((stage) => stage.state === "pending")
    ?? lifecycle.at(-1);
  const currentStageText = currentStage
    ? `${currentStage.label}（${STAGE_STATE_LABELS[currentStage.state]}）`
    : "阶段数据未提供";
  const artifactCount = run.artifacts === undefined ? "未提供" : `${run.artifacts.length} 项`;

  return (
    <section className="dashboard-card dashboard-primary-card current-project-card" aria-labelledby="current-project-heading">
      <div className="card-heading-row">
        <h2 id="current-project-heading">当前项目</h2>
        <span className="status-badge" data-status={run.status}>{STATUS_LABELS[run.status]}</span>
      </div>
      <button className="current-project-link" type="button" onClick={() => onOpenRun(run.run_id)} aria-label={`打开${run.direction}`}>
        {run.direction}
      </button>
      <dl className="project-facts">
        <div>
          <dt>总体进度</dt>
          <dd className="project-progress">
            {coverage === null ? (
              <span>阶段数据未提供</span>
            ) : (
              <>
                <progress max="100" value={coverage} aria-label={`总体进度 ${coverage}%`} />
                <strong>{coverage}%</strong>
              </>
            )}
          </dd>
        </div>
        <div><dt>当前阶段</dt><dd>{currentStageText}</dd></div>
        <div><dt>恢复次数</dt><dd>{run.resume_count}</dd></div>
        <div><dt>公开产物</dt><dd>{artifactCount}</dd></div>
        <div><dt>最后更新</dt><dd>{formatDate(updatedAt)}</dd></div>
        <div>
          <dt>下一步行动</dt>
          <dd>
            <button
              className="project-fact-action"
              type="button"
              aria-label={`查看${run.direction}的阶段与产物`}
              onClick={() => onOpenRun(run.run_id)}
            >
              查看阶段与产物 →
            </button>
          </dd>
        </div>
      </dl>
      {run.error ? <p className="run-error" role="alert">{run.error.message}</p> : null}
      {refreshError ? (
        <div className="detail-refresh-error" role="alert">
          <span>{refreshError.message || "运行详情加载失败"}</span>
          <button className="button-secondary" type="button" onClick={onRetryDetails}>重试运行详情</button>
        </div>
      ) : null}
    </section>
  );
}
