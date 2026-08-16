import { useQuery } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface EvidenceNode {
  id: string;
  code: string;
  node_type: string;
  title: string;
  status: string;
  confidence: number | null;
  has_unresolved_contradiction: boolean;
  layout_x: number;
  layout_y: number;
}

export interface EvidenceEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  stance: string | null;
}

export interface EvidenceGraph {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
}

export function useEvidenceGraph(projectId: string | undefined, cycleId: string | undefined) {
  return useQuery<EvidenceGraph>({
    queryKey: ["evidence-graph", projectId, cycleId],
    queryFn: () => request<EvidenceGraph>(`/api/v1/projects/${projectId}/cycles/${cycleId}/evidence-graph`),
    enabled: Boolean(projectId) && Boolean(cycleId),
  });
}
