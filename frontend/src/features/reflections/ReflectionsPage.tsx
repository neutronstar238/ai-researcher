import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { AsyncState } from "../../components/ui/AsyncState";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";
import type { RunRecord } from "../../lib/api/types";

const REVIEW_STATUSES = new Set(["failed", "interrupted"]);

export function ReflectionsPage() {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: apiClient.listRuns });
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ runId: string; message: string } | null>(null);
  const actionPendingRef = useRef(false);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const reviewRuns = useMemo(() => (runsQuery.data ?? [])
    .filter((run) => REVIEW_STATUSES.has(run.status))
    .sort((left, right) => timestamp(right.created_at) - timestamp(left.created_at) || left.run_id.localeCompare(right.run_id)), [runsQuery.data]);

  const resume = async (run: RunRecord) => {
    if (actionPendingRef.current) return;
    actionPendingRef.current = true;
    setPendingRunId(run.run_id);
    setActionError(null);
    try {
      await apiClient.resumeRun(run.run_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["runs"], exact: true }),
        queryClient.invalidateQueries({ queryKey: ["run", run.run_id], exact: true }),
        queryClient.invalidateQueries({ queryKey: ["run-stages", run.run_id], exact: true }),
      ]);
      if (mountedRef.current) notify({ tone: "success", message: "研究运行已恢复" });
    } catch (error) {
      if (mountedRef.current) setActionError({ runId: run.run_id, message: errorMessage(error) });
    } finally {
      actionPendingRef.current = false;
      if (mountedRef.current) setPendingRunId(null);
    }
  };

  return (
    <section className="feature-page">
      <div className="feature-heading">
        <h1>复盘洞察</h1>
        <p>仅列出服务端确认失败或中断的研究运行。</p>
      </div>
      <div className="feature-card">
        <AsyncState
          loading={runsQuery.isPending}
          error={runsQuery.error}
          empty={false}
          onRetry={() => void runsQuery.refetch()}
        >
          {reviewRuns.length === 0 ? (
            <div className="feature-empty"><strong>没有失败或中断的运行需要复盘</strong></div>
          ) : (
            <ul className="review-list" aria-label="待复盘运行">
              {reviewRuns.map((run) => (
                <li key={run.run_id}>
                  <div className="review-heading">
                    <strong>{run.direction}</strong>
                    <span className="status-badge" data-status={run.status}>{run.status}</span>
                  </div>
                  <dl className="compact-facts">
                    <div><dt>错误类型</dt><dd>{run.error?.type ?? "未提供"}</dd></div>
                    <div><dt>错误消息</dt><dd>{run.error?.message ?? "未提供"}</dd></div>
                    <div><dt>交付验证</dt><dd>{validationLabel(run.delivery_validation)}</dd></div>
                    <div><dt>恢复次数</dt><dd>{run.resume_count}</dd></div>
                    <div><dt>创建时间</dt><dd><time dateTime={run.created_at}>{formatDate(run.created_at)}</time></dd></div>
                  </dl>
                  {actionError?.runId === run.run_id ? <p className="form-error" role="alert">{actionError.message}</p> : null}
                  <button
                    className="button-secondary"
                    type="button"
                    disabled={pendingRunId !== null}
                    onClick={() => void resume(run)}
                    aria-label={`恢复${run.direction}`}
                  >
                    {pendingRunId === run.run_id ? "恢复中…" : "恢复运行"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </AsyncState>
      </div>
    </section>
  );
}

function validationLabel(value: Record<string, unknown> | null): string {
  if (!value) return "未提供";
  const status = typeof value.status === "string" ? value.status : "未提供";
  const valid = typeof value.valid === "boolean" ? value.valid ? "是" : "否" : "未提供";
  return `status: ${status} · valid: ${valid}`;
}

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "时间不可用" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message : "恢复失败，请重试。";
}
