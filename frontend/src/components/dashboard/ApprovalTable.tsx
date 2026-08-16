import { useApproveApproval, useRejectApproval, type Approval } from "../../features/dashboard/api";

const RISK_META: Record<string, { label: string; className: string }> = {
  high: { label: "高", className: "bg-danger-soft text-danger" },
  medium: { label: "中", className: "bg-warning-soft text-warning" },
  low: { label: "低", className: "bg-primary-soft text-primary" },
};

function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export function ApprovalTable({
  projectId,
  approvals,
}: {
  projectId: string;
  approvals: Approval[];
}) {
  const approve = useApproveApproval(projectId);
  const reject = useRejectApproval(projectId);

  if (!approvals.length) {
    return <p className="py-8 text-center text-sm text-text-muted">暂无待审批事项</p>;
  }

  function handleReject(approval: Approval) {
    const reason = window.prompt(`拒绝「${approval.request_reason}」的原因：`);
    if (!reason) return;
    reject.mutate({ id: approval.id, comment: reason });
  }

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="bg-surface-subtle text-left text-xs text-text-muted">
          <th className="h-9 px-3 font-medium">事项</th>
          <th className="h-9 px-3 font-medium">类型</th>
          <th className="h-9 px-3 font-medium">提交人</th>
          <th className="h-9 px-3 font-medium">优先级</th>
          <th className="h-9 px-3 font-medium">操作</th>
        </tr>
      </thead>
      <tbody>
        {approvals.map((approval) => {
          const risk = RISK_META[approval.risk_level] ?? RISK_META.medium;
          return (
            <tr key={approval.id} className="border-t border-border-light">
              <td className="h-[52px] max-w-[180px] truncate px-3 text-sm text-text" title={approval.request_reason ?? ""}>
                {approval.request_reason ?? approval.approval_type}
              </td>
              <td className="h-[52px] px-3 text-sm text-text-secondary">{approval.approval_type}</td>
              <td className="h-[52px] px-3 font-mono text-xs text-text-muted">{shortId(approval.requested_by)}</td>
              <td className="h-[52px] px-3">
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${risk.className}`}>{risk.label}</span>
              </td>
              <td className="h-[52px] px-3">
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => approve.mutate({ id: approval.id })}
                    disabled={approve.isPending}
                    className="rounded-md bg-success-soft px-2 py-1 text-xs font-medium text-success hover:bg-success hover:text-white disabled:opacity-50"
                  >
                    批准
                  </button>
                  <button
                    type="button"
                    onClick={() => handleReject(approval)}
                    disabled={reject.isPending}
                    className="rounded-md bg-danger-soft px-2 py-1 text-xs font-medium text-danger hover:bg-danger hover:text-white disabled:opacity-50"
                  >
                    拒绝
                  </button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
