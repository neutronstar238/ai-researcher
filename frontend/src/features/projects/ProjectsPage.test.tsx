import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "../../lib/api/client";
import type { BatchRecord, RunRecord, StageRecord } from "../../lib/api/types";
import { runFixture, stageFixtures } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/client")>();
  return {
    ...actual,
    apiClient: {
      cancelRun: vi.fn(),
      createBatch: vi.fn(),
      createRun: vi.fn(),
      evolution: vi.fn(),
      getRun: vi.fn(),
      getStages: vi.fn(),
      listBatches: vi.fn(),
      listRuns: vi.fn(),
      resumeRun: vi.fn(),
      startEvolution: vi.fn(),
    },
  };
});

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function summary(overrides: Partial<RunRecord> = {}): RunRecord {
  return runFixture({ stages: undefined, artifacts: undefined, ...overrides });
}

function batchSummary(overrides: Partial<BatchRecord> = {}): BatchRecord {
  return {
    schema_version: "autoresearch-api-batch-preview-v1",
    batch_id: "batch-fixture123",
    status: "dry_run",
    dry_run: true,
    question_count: 3,
    created_at: "2026-08-20T06:30:00Z",
    items: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.listBatches).mockResolvedValue([]);
  vi.mocked(apiClient.getStages).mockResolvedValue([]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
});

afterEach(() => {
  vi.useRealTimers();
});

test("derives production-shaped list progress from stable stage queries", async () => {
  const run = summary({ direction: "真实阶段研究", status: "running" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getStages).mockResolvedValue(stageFixtures(3));

  renderAppAt("/projects");

  const table = await screen.findByRole("table", { name: "研究运行" });
  expect(within(table).getByRole("row", { name: /真实阶段研究.*running.*25%/ })).toBeInTheDocument();
  expect(apiClient.getStages).toHaveBeenCalledWith(run.run_id);
});

test("shows honest unavailable progress and retries only that stage query", async () => {
  const user = userEvent.setup();
  const run = summary({ run_id: "run-stage-error", direction: "阶段失败研究" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getStages)
    .mockRejectedValueOnce(new Error("阶段接口不可用"))
    .mockResolvedValueOnce(stageFixtures(6));

  renderAppAt("/projects");

  const table = await screen.findByRole("table", { name: "研究运行" });
  expect(await within(table).findByText("进度不可用")).toBeInTheDocument();
  await user.click(within(table).getByRole("button", { name: "重试阶段失败研究的进度" }));
  expect(await within(table).findByText("50%")).toBeInTheDocument();
  expect(apiClient.getStages).toHaveBeenCalledTimes(2);
});

test("filters by question and status and reports an honest filtered empty state", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.listRuns).mockResolvedValue([
    summary({ run_id: "run-running-alpha", direction: "蛋白质折叠", status: "running" }),
    summary({ run_id: "run-failed-beta", direction: "材料发现", status: "failed" }),
  ]);

  renderAppAt("/projects");
  await screen.findByText("蛋白质折叠");

  await user.type(screen.getByRole("searchbox", { name: "搜索科学问题" }), "蛋白质");
  await user.selectOptions(screen.getByLabelText("运行状态"), "failed");

  expect(screen.getByText("没有符合当前筛选条件的运行")).toBeInTheDocument();
  expect(screen.queryByText("材料发现")).not.toBeInTheDocument();
});

test("renders loading, service error retry, and the no-run empty state", async () => {
  const user = userEvent.setup();
  const first = deferred<RunRecord[]>();
  vi.mocked(apiClient.listRuns)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce([]);

  renderAppAt("/projects");
  expect(screen.getAllByText("正在加载…")).toHaveLength(2);

  await act(async () => first.reject(new Error("运行列表不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("运行列表不可用");
  await user.click(screen.getByRole("button", { name: "重试" }));

  expect(await screen.findByText("还没有研究运行")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "新建研究" })).toHaveLength(2);
});

test("preserves all search parameters while selecting and closing an encoded run ID", async () => {
  const user = userEvent.setup();
  const runId = "run/id ?#%";
  const run = summary({ run_id: runId, direction: "保留参数研究", status: "running" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue({ ...run, stages: stageFixtures(2), artifacts: [] });
  const { router } = renderAppAt("/projects?q=%E4%BF%9D%E7%95%99&status=running&view=table");

  await user.click(await screen.findByRole("button", { name: "查看保留参数研究" }));

  expect(router.state.location.search).toContain("q=%E4%BF%9D%E7%95%99");
  expect(router.state.location.search).toContain("status=running");
  expect(router.state.location.search).toContain("view=table");
  expect(router.state.location.search).toContain("run=run%2Fid+%3F%23%25");
  await screen.findByRole("dialog", { name: "运行详情" });
  await user.click(screen.getByRole("button", { name: "关闭" }));

  expect(router.state.location.search).toBe("?q=%E4%BF%9D%E7%95%99&status=running&view=table");
});

test("keeps an unknown URL selection honest and closable", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockRejectedValue(new Error("run not found"));
  const { router } = renderAppAt("/projects?tab=all&run=unknown%2Fid");

  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  expect(await within(drawer).findByRole("alert")).toHaveTextContent("run not found");
  await user.click(within(drawer).getByRole("button", { name: "关闭" }));

  expect(router.state.location.search).toBe("?tab=all");
});

test("never exposes stale detail from a prior URL run ID", async () => {
  const oldRequest = deferred<RunRecord>();
  const newRequest = deferred<RunRecord>();
  vi.mocked(apiClient.getRun).mockImplementation((id) => id === "run-old-id" ? oldRequest.promise : newRequest.promise);
  const { router } = renderAppAt("/projects?run=run-old-id");

  await act(async () => {
    await router.navigate("/projects?run=run-new-id");
  });
  await act(async () => newRequest.resolve(runFixture({ run_id: "run-new-id", direction: "新运行详情" })));
  expect(await screen.findByText("新运行详情")).toBeInTheDocument();

  await act(async () => oldRequest.resolve(runFixture({ run_id: "run-old-id", direction: "旧运行详情" })));
  await waitFor(() => expect(screen.queryByText("旧运行详情")).not.toBeInTheDocument());
  expect(screen.getByText("新运行详情")).toBeInTheDocument();
});

test("enables one real batch control without regressing run filters or selection", async () => {
  const user = userEvent.setup();
  const run = summary({ run_id: "run-batch-regression", direction: "批量边界回归", status: "running" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue({ ...run, stages: stageFixtures(2), artifacts: [] });
  const { router } = renderAppAt("/projects?q=%E6%89%B9%E9%87%8F&status=running&view=table");

  const batchTrigger = screen.getByRole("button", { name: "批量任务" });
  expect(batchTrigger).toBeEnabled();
  await user.click(batchTrigger);
  expect(screen.getByRole("dialog", { name: "批量任务" })).toBeInTheDocument();
  await user.click(within(screen.getByRole("dialog", { name: "批量任务" })).getByRole("button", { name: "关闭" }));
  await user.click(await screen.findByRole("button", { name: "查看批量边界回归" }));

  expect(router.state.location.search).toContain("q=%E6%89%B9%E9%87%8F");
  expect(router.state.location.search).toContain("status=running");
  expect(router.state.location.search).toContain("view=table");
  expect(router.state.location.search).toContain("run=run-batch-regression");
  expect(apiClient.getStages).toHaveBeenCalledWith(run.run_id);
});

test("renders batch loading, service error retry, and an honest empty state", async () => {
  const user = userEvent.setup();
  const first = deferred<BatchRecord[]>();
  vi.mocked(apiClient.listBatches)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce([]);

  renderAppAt("/projects");
  const section = await screen.findByRole("region", { name: "批量任务记录" });
  expect(within(section).getByText("正在加载…")).toBeInTheDocument();

  await act(async () => first.reject(new Error("批量服务不可用")));
  expect(await within(section).findByRole("alert")).toHaveTextContent("批量服务不可用");
  await user.click(within(section).getByRole("button", { name: "重试" }));

  expect(await within(section).findByText("尚无批量任务")).toBeInTheDocument();
  expect(apiClient.listBatches).toHaveBeenCalledTimes(2);
});

test("preserves server batch order and renders only public receipt facts", async () => {
  vi.mocked(apiClient.listBatches).mockResolvedValue([
    batchSummary({
      batch_id: "batch-newer123",
      status: "submitted",
      question_count: 5,
      created_at: "2026-08-20T08:00:00Z",
      items: [],
      question_pdf: "D:/private/new.pdf",
      batch_service_receipt: { output_root: "D:/private/output" },
    }),
    batchSummary({
      batch_id: "batch-older123",
      status: "dry_run",
      question_count: 2,
      created_at: "2026-08-20T07:00:00Z",
      items: [],
    }),
  ]);

  renderAppAt("/projects");
  const table = await screen.findByRole("table", { name: "批量任务记录" });
  const rows = within(table).getAllByRole("row").slice(1);

  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("batch-newer123");
  expect(rows[0]).toHaveTextContent("submitted");
  expect(rows[0]).toHaveTextContent("5");
  expect(rows[1]).toHaveTextContent("batch-older123");
  expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
    "批量 ID",
    "状态",
    "题目数",
    "创建时间",
  ]);
  expect(within(table).queryByText(/%|已完成\s*\d|题目进度/)).not.toBeInTheDocument();
  expect(within(table).queryByText("D:/private/new.pdf")).not.toBeInTheDocument();
  expect(within(table).queryByText("D:/private/output")).not.toBeInTheDocument();
});

test.each([
  ["an empty list", []],
  ["an entirely terminal list", [summary({ run_id: "run-terminal-only", status: "completed" })]],
] as const)("does not permanently poll runs for %s", async (_caseName, runs) => {
  vi.useFakeTimers();
  vi.mocked(apiClient.listRuns).mockResolvedValue([...runs]);

  renderAppAt("/projects");
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(apiClient.listRuns).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(45_000); });
  expect(apiClient.listRuns).toHaveBeenCalledTimes(1);
});

test("polls runs only while the returned list has an active run", async () => {
  vi.useFakeTimers();
  vi.mocked(apiClient.listRuns).mockResolvedValue([
    summary({ run_id: "run-active-list", status: "running" }),
  ]);

  renderAppAt("/projects");
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(apiClient.listRuns).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(apiClient.listRuns).toHaveBeenCalledTimes(2);
});

test("polls an active visible stage query and performs one final refresh on terminal transition", async () => {
  vi.useFakeTimers();
  const active = summary({ run_id: "run-stage-transition", direction: "阶段转换", status: "running" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([active]);
  vi.mocked(apiClient.getStages).mockResolvedValue(stageFixtures(2));
  const { queryClient } = renderAppAt("/projects");
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(apiClient.getStages).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
  expect(apiClient.getStages).toHaveBeenCalledTimes(2);

  act(() => {
    queryClient.setQueryData(["runs"], [{ ...active, status: "completed" }]);
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(apiClient.getStages).toHaveBeenCalledTimes(3);

  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(apiClient.getStages).toHaveBeenCalledTimes(3);
});

test("requests stages only for the fixed number of currently filtered visible rows", async () => {
  const matching = Array.from({ length: 25 }, (_, index) => summary({
    run_id: `run-match-${String(index).padStart(3, "0")}`,
    direction: `匹配研究 ${index}`,
    status: "completed",
  }));
  const hidden = Array.from({ length: 5 }, (_, index) => summary({
    run_id: `run-other-${String(index).padStart(3, "0")}`,
    direction: `其他研究 ${index}`,
    status: "completed",
  }));
  vi.mocked(apiClient.listRuns).mockResolvedValue([...matching, ...hidden]);

  renderAppAt("/projects?q=%E5%8C%B9%E9%85%8D");

  await waitFor(() => expect(apiClient.getStages).toHaveBeenCalledTimes(20));
  expect(vi.mocked(apiClient.getStages).mock.calls.map(([id]) => id)).toEqual(
    matching.slice(0, 20).map((run) => run.run_id),
  );
  expect(screen.getByRole("table", { name: "研究运行" }).querySelectorAll("tbody tr")).toHaveLength(20);
  expect(screen.getByText("当前显示前 20 项匹配运行")).toBeInTheDocument();
});
