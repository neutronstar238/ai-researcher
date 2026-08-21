import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AsyncState } from "../../components/ui/AsyncState";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Drawer } from "../../components/ui/Drawer";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";
import type { RunRecord, RunStatus } from "../../lib/api/types";

export interface RunDetailsDrawerProps {
  runId: string;
  onClose(): void;
}

const CANCELABLE_STATUSES = new Set<RunStatus>(["queued", "running"]);
const RESUMABLE_STATUSES = new Set<RunStatus>(["canceled", "completed", "failed", "interrupted"]);
const ACTIVE_STATUSES = new Set<RunStatus>(["queued", "running", "cancel_requested"]);

export function RunDetailsDrawer({ runId, onClose }: RunDetailsDrawerProps) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const actionPendingRef = useRef(false);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiClient.getRun(runId),
    refetchInterval: (query) => {
      const status = (query.state.data as RunRecord | undefined)?.status;
      return status && ACTIVE_STATUSES.has(status)
        ? 5_000
        : false;
    },
  });
  const resumeMutation = useMutation({ mutationFn: () => apiClient.resumeRun(runId) });
  const cancelMutation = useMutation({ mutationFn: () => apiClient.cancelRun(runId) });
  const evolutionMutation = useMutation({ mutationFn: () => apiClient.startEvolution(runId) });
  const run = runQuery.data?.run_id === runId ? runQuery.data : null;
  const identityError = runQuery.data && runQuery.data.run_id !== runId
    ? new Error("运行详情与所选 ID 不一致")
    : null;

  const invalidateRunData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["runs"] }),
      queryClient.invalidateQueries({ queryKey: ["run", runId] }),
      queryClient.invalidateQueries({ queryKey: ["run-stages", runId] }),
    ]);
  };

  const runAction = async (action: () => Promise<unknown>, successMessage: string) => {
    if (actionPendingRef.current) return;
    actionPendingRef.current = true;
    setActionError(null);
    try {
      await action();
      await invalidateRunData();
      if (mountedRef.current) notify({ tone: "success", message: successMessage });
    } catch (error) {
      if (mountedRef.current) setActionError(errorMessage(error));
    } finally {
      actionPendingRef.current = false;
    }
  };

  const handleEvolution = async () => {
    if (actionPendingRef.current) return;
    actionPendingRef.current = true;
    setActionError(null);
    try {
      await evolutionMutation.mutateAsync();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["evolution", runId] }),
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
      ]);
      if (mountedRef.current) notify({ tone: "success", message: "进化候选任务已发起" });
    } catch (error) {
      if (mountedRef.current) setActionError(errorMessage(error));
    } finally {
      actionPendingRef.current = false;
    }
  };

  const confirmCancel = async () => {
    await cancelMutation.mutateAsync();
    await invalidateRunData();
    if (mountedRef.current) notify({ tone: "success", message: "取消请求已提交" });
  };

  return (
    <Drawer open title="运行详情" onClose={onClose}>
      <AsyncState
        loading={runQuery.isPending}
        error={runQuery.error ?? identityError}
        empty={!runQuery.isPending && !runQuery.error && !identityError && run === null}
        onRetry={() => void runQuery.refetch()}
      >
        {run ? (
          <div className="run-details">
            <div className="run-detail-heading">
              <p className="run-direction">{run.direction}</p>
              <span className="status-badge" data-status={run.status}>{run.status}</span>
            </div>
            {run.error ? <p className="run-error" role="alert">{run.error.message}</p> : null}
            <dl className="run-detail-facts">
              <div><dt>运行 ID</dt><dd><code>{run.run_id}</code></dd></div>
              <div><dt>创建时间</dt><dd><time dateTime={run.created_at}>{formatDate(run.created_at)}</time></dd></div>
              <div><dt>恢复次数</dt><dd>{run.resume_count}</dd></div>
            </dl>

            <section className="run-detail-section" aria-labelledby="run-stage-heading">
              <h3 id="run-stage-heading">十二阶段</h3>
              {run.stages?.length ? (
                <ol className="run-stage-list" aria-label="研究阶段">
                  {run.stages.map((stage) => (
                    <li key={`${stage.ordinal}-${stage.stage_name}`} aria-label={`阶段 ${stage.ordinal} ${stage.label_zh}`}>
                      <span>{stage.ordinal}. {stage.label_zh}</span>
                      <span className="stage-status" data-status={stage.status}>{stage.status}</span>
                      <span>{stage.artifact_count} 个产物</span>
                      <code>{stage.checkpoint_hash?.slice(0, 10) ?? "无检查点"}</code>
                    </li>
                  ))}
                </ol>
              ) : <p className="detail-empty">服务未返回阶段数据</p>}
            </section>

            <section className="run-detail-section" aria-labelledby="run-artifact-heading">
              <h3 id="run-artifact-heading">公开产物</h3>
              {run.artifacts?.length ? (
                <ul className="artifact-list">
                  {run.artifacts.map((artifact) => (
                    <li key={`${artifact.relative_path}-${artifact.url}`}>
                      <a href={artifact.url} target="_blank" rel="noreferrer">{artifact.relative_path}</a>
                      <span>{artifact.category} · {formatBytes(artifact.bytes)}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="detail-empty">暂无公开产物</p>}
            </section>

            {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
            <div className="run-actions" aria-label="运行操作">
              {CANCELABLE_STATUSES.has(run.status) ? (
                <button className="button-danger" type="button" onClick={() => setCancelOpen(true)}>请求取消</button>
              ) : null}
              {RESUMABLE_STATUSES.has(run.status) ? (
                <button
                  className="button-secondary"
                  type="button"
                  disabled={resumeMutation.isPending || evolutionMutation.isPending}
                  onClick={() => void runAction(() => resumeMutation.mutateAsync(), "研究运行已恢复")}
                >
                  {resumeMutation.isPending ? "恢复中…" : "恢复运行"}
                </button>
              ) : null}
              {run.status === "completed" ? (
                <div className="evolution-action">
                  <button
                    className="button-primary"
                    type="button"
                    disabled={evolutionMutation.isPending || resumeMutation.isPending}
                    onClick={() => void handleEvolution()}
                  >
                    {evolutionMutation.isPending ? "发起中…" : "发起进化"}
                  </button>
                  <small>仅生成候选并验证，不授权 Skill 晋级</small>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </AsyncState>
      <ConfirmDialog
        open={cancelOpen}
        title="取消运行"
        description="取消只会请求后端在安全边界停止；运行中的同步任务可能继续到当前边界。"
        confirmLabel="确认取消"
        danger
        onConfirm={confirmCancel}
        onClose={() => setCancelOpen(false)}
      />
    </Drawer>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "操作失败，请重试。";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "时间不可用"
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  return `${(bytes / 1_024).toFixed(1)} KB`;
}
