import { useState } from "react";
import { useParams } from "react-router-dom";

import { useApprovals, useDecideApproval } from "../features/approvals/api";

const TYPE_LABELS: Record<string, string> = {
  experiment_run: "实验运行",
  data_import: "数据导入",
  content_publish: "内容发布",
  agent_high_risk_tool: "高风险工具",
};

const RISK_STYLES: Record<string, string> = {
  high: "bg-danger-soft text-danger",
  medium: "bg-warning-soft text-warning",
  low: "bg-success-soft text-success",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
};

export function ApprovalsPage() {
  const { projectId } = useParams();
  const [filter, setFilter] = useState<string>("pending");
  const { data: approvals } = useApprovals(projectId, filter === "all" ? undefined : filter);
  const decide = useDecideApproval(projectId);
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [comment, setComment] = useState("");

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">审批中心</h2>
        <div className="flex gap-1 rounded-md bg-surface-subtle p-1 text-sm">
          {["pending", "approved", "rejected", "all"].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              className={`rounded px-3 py-1 ${filter === value ? "bg-white text-primary shadow-sm" : "text-text-muted"}`}
            >
              {value === "all" ? "全部" : STATUS_LABELS[value] ?? value}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {approvals?.map((approval) => (
          <div key={approval.id} className="card">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text">
                    {TYPE_LABELS[approval.approval_type] ?? approval.approval_type}
                  </span>
                  <span className={`rounded px-1.5 py-0.5 text-xs ${RISK_STYLES[approval.risk_level] ?? "bg-surface-subtle text-text-muted"}`}>
                    {approval.risk_level}
                  </span>
                  <span className="rounded bg-surface-subtle px-1.5 py-0.5 text-xs text-text-muted">
                    {STATUS_LABELS[approval.status] ?? approval.status}
                  </span>
                </div>
                <p className="mt-1 text-sm text-text-secondary">{approval.request_reason ?? "—"}</p>
                <div className="mt-1 text-xs text-text-muted">
                  {new Date(approval.created_at).toLocaleString()} · 申请人 {approval.requested_by.slice(0, 8)}
                </div>
              </div>

              {approval.status === "pending" && (
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => decide.mutate({ approvalId: approval.id, decision: "approved" })}
                    disabled={decide.isPending}
                    className="rounded-md bg-success px-3 py-1.5 text-xs text-white hover:opacity-90 disabled:opacity-50"
                  >
                    批准
                  </button>
                  <button
                    type="button"
                    onClick={() => { setRejectId(approval.id); setComment(""); }}
                    className="rounded-md border border-danger px-3 py-1.5 text-xs text-danger hover:bg-danger-soft"
                  >
                    拒绝
                  </button>
                </div>
              )}
            </div>

            {rejectId === approval.id && (
              <div className="mt-3 space-y-2 rounded-md bg-surface-subtle p-3">
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="拒绝理由（必填）"
                  className="w-full rounded-md border border-border-strong px-3 py-2 text-sm"
                  rows={2}
                />
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setRejectId(null)} className="rounded-md px-3 py-1.5 text-xs text-text-secondary">取消</button>
                  <button
                    type="button"
                    disabled={!comment.trim() || decide.isPending}
                    onClick={() => decide.mutate({ approvalId: approval.id, decision: "rejected", comment })}
                    className="rounded-md bg-danger px-3 py-1.5 text-xs text-white disabled:opacity-50"
                  >
                    确认拒绝
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {approvals?.length === 0 && <p className="card py-10 text-center text-sm text-text-muted">暂无审批</p>}
      </div>
    </div>
  );
}
