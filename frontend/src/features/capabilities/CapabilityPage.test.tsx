import { cleanup, screen, within } from "@testing-library/react";
import { apiClient } from "../../lib/api/client";
import { healthFixture, runFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", () => ({
  apiClient: {
    evolution: vi.fn(),
    getRun: vi.fn(),
    getStages: vi.fn(),
    health: vi.fn(),
    listBatches: vi.fn(),
    listRuns: vi.fn(),
    skillCandidates: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.health).mockResolvedValue(healthFixture());
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.listBatches).mockResolvedValue([]);
  vi.mocked(apiClient.getStages).mockResolvedValue([]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
  vi.mocked(apiClient.skillCandidates).mockResolvedValue([]);
});

test.each([
  ["/knowledge", "知识图谱", "当前服务未提供知识图谱查询接口", /批准|拒绝|创建图谱/],
  ["/approvals", "审批中心", "当前服务未提供审批队列接口", /批准|拒绝/],
] as const)("renders the exact unsupported boundary at %s without API calls or fake actions", (path, heading, boundary, actions) => {
  renderAppAt(path);

  expect(screen.getByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "能力边界" })).toHaveTextContent(boundary);
  expect(screen.queryByRole("button", { name: actions })).not.toBeInTheDocument();
  for (const method of Object.values(apiClient)) expect(method).not.toHaveBeenCalled();
});

test.each([
  ["/", "研究总览"],
  ["/projects", "项目空间"],
  ["/literature", "文献库"],
  ["/experiments", "实验管理"],
  ["/assets", "数据资产"],
  ["/knowledge", "知识图谱"],
  ["/writing", "写作中心"],
  ["/reflections", "复盘洞察"],
  ["/agents", "智能体中心"],
  ["/approvals", "审批中心"],
  ["/settings", "系统设置"],
] as const)("gives %s exactly one semantic page h1 and eleven real navigation links", async (path, heading) => {
  renderAppAt(path);

  expect(await screen.findByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  const navigation = screen.getByRole("navigation", { name: "主导航" });
  const links = within(navigation).getAllByRole("link");
  expect(links).toHaveLength(11);
  for (const link of links) expect(link.getAttribute("href")).not.toBe("#");
  cleanup();
});
