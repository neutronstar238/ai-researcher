import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { EvidenceGraph as GraphData } from "../../features/evidence/api";

const TYPE_LABELS: Record<string, string> = {
  research_question: "研究问题",
  paper: "文献",
  evidence: "证据",
  hypothesis: "假设",
  experiment: "实验",
  result: "结果",
  validation: "验证",
  claim: "主张",
  dataset: "数据集",
  method: "方法",
};

const RELATION_COLORS: Record<string, string> = {
  supports: "#16A34A",
  contradicts: "#DC2626",
};

function EvidenceNodeView({ data }: NodeProps) {
  const d = data as {
    code: string;
    nodeType: string;
    title: string;
    confidence: number | null;
    unresolved: boolean;
    status: string;
  };
  return (
    <div
      className={`w-[150px] rounded-[12px] border bg-white p-3 shadow-sm ${
        d.unresolved ? "border-danger" : "border-border-strong"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !bg-border-strong" />
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-semibold text-text">{d.code}</span>
        <span className="rounded bg-surface-subtle px-1.5 py-0.5 text-[10px] text-text-muted">
          {TYPE_LABELS[d.nodeType] ?? d.nodeType}
        </span>
      </div>
      <div className="mt-2 line-clamp-5 text-xs leading-5 text-text-secondary">{d.title}</div>
      <div className="mt-2 flex items-center justify-between text-[10px] text-text-muted">
        {d.confidence != null ? (
          <span className="tabular-nums">置信 {Math.round(d.confidence)}%</span>
        ) : (
          <span>—</span>
        )}
        {d.unresolved && <span className="text-danger">有矛盾</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !bg-border-strong" />
    </div>
  );
}

const nodeTypes = { evidence: EvidenceNodeView };

export function EvidenceGraph({
  data,
  onSelect,
  className = "h-[300px]",
}: {
  data: GraphData;
  onSelect: (id: string) => void;
  className?: string;
}) {
  const nodes: Node[] = data.nodes.map((n) => ({
    id: n.id,
    type: "evidence",
    position: { x: n.layout_x, y: n.layout_y },
    data: {
      code: n.code,
      nodeType: n.node_type,
      title: n.title,
      confidence: n.confidence,
      unresolved: n.has_unresolved_contradiction,
      status: n.status,
    },
  }));

  const edges: Edge[] = data.edges.map((e) => {
    const color = RELATION_COLORS[e.relation] ?? "#94A3B8";
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.relation,
      animated: e.relation === "contradicts",
      style: {
        stroke: color,
        strokeWidth: 2,
        strokeDasharray: e.relation === "contradicts" ? "6 4" : undefined,
      },
      labelStyle: { fill: "#64748B", fontSize: 10 },
      markerEnd: { type: MarkerType.ArrowClosed, color },
    };
  });

  return (
    <div className={`w-full ${className}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.65}
        maxZoom={1.5}
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#E5E7EB" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="!bg-surface" />
      </ReactFlow>
    </div>
  );
}
