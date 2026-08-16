import { useAcceptCandidate, type TopicCandidate } from "../../features/dashboard/api";

const STATUS_META: Record<string, { label: string; className: string }> = {
  high_priority: { label: "高优先级", className: "bg-success-soft text-success" },
  medium_priority: { label: "中优先级", className: "bg-warning-soft text-warning" },
  exploring: { label: "探索中", className: "bg-surface-subtle text-text-muted" },
  proposed: { label: "提案中", className: "bg-surface-subtle text-text-muted" },
  accepted: { label: "已采纳", className: "bg-primary-soft text-primary" },
  rejected: { label: "已拒绝", className: "bg-surface-subtle text-text-muted" },
};

export function DiscoveryTable({
  projectId,
  candidates,
}: {
  projectId: string;
  candidates: TopicCandidate[];
}) {
  const accept = useAcceptCandidate(projectId);

  if (!candidates.length) {
    return <p className="py-8 text-center text-sm text-text-muted">暂无选题候选</p>;
  }

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="bg-surface-subtle text-left text-xs text-text-muted">
          <th className="h-9 px-3 font-medium">编号</th>
          <th className="h-9 px-3 font-medium">选题候选</th>
          <th className="h-9 px-3 font-medium">证据强度</th>
          <th className="h-9 px-3 font-medium">状态</th>
          <th className="h-9 px-3 font-medium">操作</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((candidate, index) => {
          const meta = STATUS_META[candidate.status] ?? STATUS_META.proposed;
          const strength = candidate.evidence_strength ?? 0;
          return (
            <tr key={candidate.id} className="border-t border-border-light">
              <td className="tabular-nums h-[55px] px-3 text-sm text-text-secondary">
                {String(index + 1).padStart(2, "0")}
              </td>
              <td className="h-[55px] max-w-[240px] truncate px-3 text-sm text-text" title={candidate.title}>
                {candidate.title}
              </td>
              <td className="h-[55px] px-3 text-sm">
                <span className="tabular-nums text-text-secondary">{Math.round(strength)}%</span>
                <div className="mt-1 h-1 w-16 overflow-hidden rounded-full bg-track">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${strength}%` }} />
                </div>
              </td>
              <td className="h-[55px] px-3">
                <span className={`rounded-full px-2 py-0.5 text-xs ${meta.className}`}>{meta.label}</span>
              </td>
              <td className="h-[55px] px-3">
                {candidate.status !== "accepted" && (
                  <button
                    type="button"
                    onClick={() => accept.mutate(candidate.id)}
                    disabled={accept.isPending}
                    className="rounded-md bg-primary-soft px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary hover:text-white disabled:opacity-50"
                  >
                    采纳
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
