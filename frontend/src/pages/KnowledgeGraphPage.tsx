import { useState } from "react";
import { useParams } from "react-router-dom";

import { EvidenceGraph } from "../components/evidence/EvidenceGraph";
import { useEvidenceGraph } from "../features/evidence/api";
import { useCycles } from "../features/projects/api";

const NODE_TYPE_LABELS: Record<string, string> = {
  research_question: "研究问题",
  paper: "文献",
  hypothesis: "假设",
  experiment: "实验",
  validation: "验证",
  claim: "主张",
  evidence: "证据",
  result: "结果",
  dataset: "数据集",
  method: "方法",
};

export function KnowledgeGraphPage() {
  const { projectId } = useParams();
  const { data: cycles } = useCycles(projectId);
  const activeCycleId = cycles?.find((c) => c.status === "active")?.id ?? cycles?.[0]?.id;
  const [cycleId, setCycleId] = useState<string | null>(null);
  const effectiveCycleId = cycleId ?? activeCycleId;

  const { data: graph } = useEvidenceGraph(projectId, effectiveCycleId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = graph?.nodes.find((n) => n.id === selectedId);

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">知识图谱</h2>
        <div className="flex items-center gap-3">
          {cycles && cycles.length > 1 && (
            <select value={effectiveCycleId ?? ""} onChange={(e) => setCycleId(e.target.value)} className="rounded-md border border-border-strong px-3 py-2 text-sm">
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>第 {c.sequence_no} 周期 · {c.name}</option>
              ))}
            </select>
          )}
          <span className="text-xs text-text-muted">{graph?.nodes.length ?? 0} 节点 · {graph?.edges.length ?? 0} 关系</span>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="card min-w-0 flex-1 p-0">
          <EvidenceGraph data={graph ?? { nodes: [], edges: [] }} onSelect={setSelectedId} className="h-full" />
        </div>

        <aside className="card w-[300px] shrink-0 overflow-y-auto">
          {selected ? (
            <>
              <h3 className="text-sm font-semibold text-text">{selected.code}</h3>
              <span className="mt-1 inline-block rounded bg-surface-subtle px-1.5 py-0.5 text-xs text-text-muted">
                {NODE_TYPE_LABELS[selected.node_type] ?? selected.node_type}
              </span>
              <p className="mt-3 text-sm text-text-secondary">{selected.title}</p>
              <dl className="mt-4 space-y-2 text-xs">
                <div className="flex justify-between"><dt className="text-text-muted">状态</dt><dd className="text-text">{selected.status}</dd></div>
                <div className="flex justify-between"><dt className="text-text-muted">置信度</dt><dd className="tabular-nums text-text">{selected.confidence != null ? `${Math.round(selected.confidence)}%` : "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-text-muted">矛盾</dt><dd className={selected.has_unresolved_contradiction ? "text-danger" : "text-text"}>
                  {selected.has_unresolved_contradiction ? "有" : "无"}
                </dd></div>
              </dl>
            </>
          ) : (
            <p className="py-10 text-center text-sm text-text-muted">点击节点查看详情</p>
          )}
        </aside>
      </div>
    </div>
  );
}
