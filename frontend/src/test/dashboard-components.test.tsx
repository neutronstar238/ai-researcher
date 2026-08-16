import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalTable } from "../components/dashboard/ApprovalTable";
import { DiscoveryTable } from "../components/dashboard/DiscoveryTable";

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("dashboard cards", () => {
  it("renders approval table with actions", () => {
    render(
      <ApprovalTable
        projectId="p1"
        approvals={[
          {
            id: "a1",
            project_id: "p1",
            approval_type: "experiment_run",
            subject_type: null,
            status: "pending",
            risk_level: "high",
            request_reason: "运行实验组 S3",
            requested_by: "user-1",
            created_at: "2026-08-16T00:00:00Z",
          },
        ]}
      />,
      { wrapper },
    );
    expect(screen.getByText("运行实验组 S3")).toBeInTheDocument();
    expect(screen.getByText("批准")).toBeInTheDocument();
    expect(screen.getByText("拒绝")).toBeInTheDocument();
  });

  it("renders discovery table with strength and status", () => {
    render(
      <DiscoveryTable
        projectId="p1"
        candidates={[
          {
            id: "c1",
            title: "多模态大模型辅助蛋白质结构预测",
            evidence_strength: 92,
            status: "high_priority",
            research_question: null,
            rationale: null,
          },
        ]}
      />,
      { wrapper },
    );
    expect(screen.getByText("多模态大模型辅助蛋白质结构预测")).toBeInTheDocument();
    expect(screen.getByText("高优先级")).toBeInTheDocument();
    expect(screen.getByText("采纳")).toBeInTheDocument();
  });
});
