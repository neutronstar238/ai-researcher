import { useState } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { EvidenceGraph } from "../components/evidence/EvidenceGraph";
import { EvidenceInspector } from "../components/evidence/EvidenceInspector";
import { WorkspaceShell } from "../components/layout/WorkspaceShell";
import { useEvidenceGraph } from "../features/evidence/api";
import { useCycles } from "../features/projects/api";

export function EvidenceWorkspacePage() {
  const { projectId, cycleId } = useParams();
  const { data: cycles } = useCycles(projectId);
  const { data: graph, isLoading, isError, error } = useEvidenceGraph(projectId, cycleId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedNode = graph?.nodes.find((n) => n.id === selectedId) ?? null;

  return (
    <WorkspaceShell
      explorer={
        <div>
          <div className="flex h-16 items-center gap-2 border-b border-border px-4">
            <Link
              to={`/projects/${projectId}/overview`}
              className="grid h-8 w-8 place-items-center rounded-md text-text-muted hover:bg-surface-subtle"
              aria-label="返回研究总览"
            >
              <ArrowLeft className="h-[18px] w-[18px]" strokeWidth={1.75} />
            </Link>
            <span className="truncate text-sm font-medium text-text">项目工作台</span>
          </div>
          <div className="px-4 py-3">
            <div className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
              <Search className="h-4 w-4 text-text-muted" />
              <input placeholder="搜索项目或周期" className="w-full bg-transparent text-sm outline-none" />
            </div>
          </div>
          <div className="space-y-2 px-4">
            {cycles?.map((cycle) => (
              <Link
                key={cycle.id}
                to={`/projects/${projectId}/cycles/${cycle.id}/evidence`}
                className={`flex items-center justify-between rounded-lg px-3 py-2.5 text-sm ${
                  cycle.id === cycleId ? "bg-primary-soft text-primary" : "hover:bg-surface-subtle"
                }`}
              >
                <span className="truncate">{cycle.name}</span>
                <span className={`h-2 w-2 rounded-full ${cycle.status === "active" ? "bg-primary" : "bg-disabled"}`} />
              </Link>
            ))}
            {!cycles?.length && <div className="py-8 text-center text-xs text-text-muted">暂无周期</div>}
          </div>
        </div>
      }
      inspector={<EvidenceInspector node={selectedNode} />}
    >
      <div className="border-b border-border bg-surface px-6 py-4">
        <div className="text-2xl font-bold text-text">项目工作台</div>
        <div className="text-sm text-text-secondary">科研证据链</div>
      </div>

      <div className="m-6 rounded-[12px] border border-border bg-surface">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-medium text-text">科研证据链</span>
          {graph && (
            <span className="tabular-nums text-xs text-text-muted">
              {graph.nodes.length} 节点 · {graph.edges.length} 关系
            </span>
          )}
        </div>
        {isLoading ? (
          <div className="h-[300px] animate-pulse bg-surface-subtle" />
        ) : isError ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-danger">
            {(error as Error).message}
          </div>
        ) : graph && graph.nodes.length ? (
          <EvidenceGraph data={graph} onSelect={setSelectedId} />
        ) : (
          <div className="flex h-[300px] items-center justify-center text-sm text-text-muted">
            尚无可展示证据链
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}
