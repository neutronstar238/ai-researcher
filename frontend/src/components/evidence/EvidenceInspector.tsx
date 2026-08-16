import type { EvidenceNode } from "../../features/evidence/api";

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

export function EvidenceInspector({ node }: { node: EvidenceNode | null }) {
  if (!node) {
    return (
      <div className="px-4 py-6 text-center text-sm text-text-muted">
        <div className="text-base font-medium text-text">节点详情</div>
        <div className="mt-4 text-xs">点击证据图中的节点查看详情</div>
      </div>
    );
  }

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-text">{node.code}</span>
        <span className="rounded bg-surface-subtle px-2 py-0.5 text-xs text-text-muted">
          {TYPE_LABELS[node.node_type] ?? node.node_type}
        </span>
      </div>

      <div className="mt-2 text-sm leading-6 text-text-secondary">{node.title}</div>

      <dl className="mt-4 space-y-2 text-xs">
        <div className="flex justify-between">
          <dt className="text-text-muted">状态</dt>
          <dd className="text-text-secondary">{node.status}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-muted">置信度</dt>
          <dd className="tabular-nums text-text-secondary">
            {node.confidence != null ? `${Math.round(node.confidence)}%` : "—"}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-muted">未解决矛盾</dt>
          <dd className={node.has_unresolved_contradiction ? "text-danger" : "text-success"}>
            {node.has_unresolved_contradiction ? "是" : "否"}
          </dd>
        </div>
      </dl>

      <div className="mt-4 rounded-md bg-surface-subtle px-3 py-2 text-xs text-text-muted">
        文献证据、源文件与 Provenance 将在文献库接入后展示。
      </div>
    </div>
  );
}
