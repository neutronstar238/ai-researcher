import { useState } from "react";
import { useParams } from "react-router-dom";

import { useAcceptRecommendation, useReflection, useRunReflection } from "../features/reflection/api";
import { useCycles } from "../features/projects/api";

export function ReflectionsPage() {
  const { projectId } = useParams();
  const { data: cycles } = useCycles(projectId);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const activeCycleId = cycles?.find((c) => c.status === "active")?.id ?? cycles?.[0]?.id;
  const effectiveCycleId = cycleId ?? activeCycleId;

  const { data: reflection } = useReflection(projectId, effectiveCycleId);
  const run = useRunReflection(projectId, effectiveCycleId);
  const accept = useAcceptRecommendation(projectId, effectiveCycleId);
  const [accepted, setAccepted] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const metrics = reflection?.metrics;

  async function handleRun() {
    setError(null);
    try {
      await run.mutateAsync();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成复盘失败");
    }
  }

  async function handleAccept(recId: string) {
    setError(null);
    try {
      const result = await accept.mutateAsync(recId);
      setAccepted((prev) => ({ ...prev, [recId]: result.title }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "采纳建议失败");
    }
  }

  const cards = metrics
    ? [
        { label: "目标完成率", value: `${metrics.goal_completion_rate}%` },
        { label: "阶段", value: `${metrics.stage_completed}/${metrics.stage_total}` },
        { label: "失败运行", value: metrics.failed_experiment_runs },
        { label: "证据节点", value: metrics.evidence_nodes },
        { label: "未解决矛盾", value: metrics.unresolved_contradictions },
      ]
    : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">复盘洞察</h2>
        <div className="flex items-center gap-3">
          {cycles && cycles.length > 1 && (
            <select
              value={effectiveCycleId ?? ""}
              onChange={(e) => setCycleId(e.target.value)}
              className="rounded-md border border-border-strong px-3 py-2 text-sm"
            >
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>第 {c.sequence_no} 周期 · {c.name}</option>
              ))}
            </select>
          )}
          <button type="button" onClick={handleRun} disabled={run.isPending} className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50">
            {run.isPending ? "生成中…" : "生成复盘"}
          </button>
        </div>
      </div>

      {error && <div className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</div>}

      {metrics ? (
        <>
          <div className="grid grid-cols-5 gap-3">
            {cards.map((card) => (
              <div key={card.label} className="card py-4 text-center">
                <div className="text-2xl font-semibold tabular-nums text-text">{card.value}</div>
                <div className="mt-1 text-xs text-text-muted">{card.label}</div>
              </div>
            ))}
          </div>

          <div className="card">
            <h3 className="text-sm font-semibold text-text">行动建议</h3>
            <div className="mt-2 space-y-2">
              {reflection?.recommendations.map((rec) => (
                <div key={rec.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                  <div>
                    <div className="text-sm text-text">{rec.title}</div>
                    <div className="text-xs text-text-muted">{rec.reason}</div>
                  </div>
                  {accepted[rec.id] ? (
                    <span className="shrink-0 rounded bg-success-soft px-2 py-1 text-xs text-success">已采纳</span>
                  ) : (
                    <button type="button" onClick={() => handleAccept(rec.id)} disabled={accept.isPending} className="shrink-0 rounded-md bg-primary-soft px-2.5 py-1 text-xs text-primary hover:bg-primary hover:text-white disabled:opacity-50">
                      采纳为行动
                    </button>
                  )}
                </div>
              ))}
              {reflection?.recommendations.length === 0 && <p className="py-4 text-center text-xs text-text-muted">暂无建议</p>}
            </div>
          </div>
        </>
      ) : (
        <div className="card py-16 text-center text-sm text-text-muted">尚无复盘报告，点击「生成复盘」基于当前周期真实数据计算</div>
      )}
    </div>
  );
}
