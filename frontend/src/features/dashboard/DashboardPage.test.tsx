import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunRecord } from "../../lib/api/types";
import { apiClient } from "../../lib/api/client";
import { artifactFixtures, healthFixture, runFixture, stageFixtures } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

const chartMocks = vi.hoisted(() => ({
  dispose: vi.fn(),
  init: vi.fn(),
  resize: vi.fn(),
  setOption: vi.fn(),
}));

vi.mock("echarts/core", () => ({
  init: chartMocks.init,
  use: vi.fn(),
}));

vi.mock("../../lib/api/client", () => ({
  apiClient: {
    getRun: vi.fn(),
    getStages: vi.fn(),
    health: vi.fn(),
    listRuns: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function runWithStages(overrides: Partial<RunRecord>, completed: number): RunRecord {
  return runFixture({ ...overrides, stages: stageFixtures(completed) });
}

function runSummary(overrides: Partial<RunRecord> = {}): RunRecord {
  return runFixture({
    finished_at: null,
    stages: undefined,
    started_at: null,
    ...overrides,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  chartMocks.dispose.mockReset();
  chartMocks.resize.mockReset();
  chartMocks.setOption.mockReset();
  chartMocks.init.mockReset().mockReturnValue({
    dispose: chartMocks.dispose,
    resize: chartMocks.resize,
    setOption: chartMocks.setOption,
  });
  vi.mocked(apiClient.health).mockResolvedValue(healthFixture());
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
  vi.mocked(apiClient.getStages).mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

test("provides ResizeObserver in the first test", () => {
  expect(globalThis.ResizeObserver).toBeTypeOf("function");
});

test("restores ResizeObserver for subsequent tests", () => {
  expect(globalThis.ResizeObserver).toBeTypeOf("function");
});

test("renders real run detail progress and the shell's single page header", async () => {
  const summary = runFixture({
    run_id: "run-real-protein",
    direction: "真实蛋白质研究",
    status: "running",
    stages: undefined,
  });
  vi.mocked(apiClient.listRuns).mockResolvedValue([summary]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(summary, 5));

  renderAppAt("/");

  const currentCard = await screen.findByRole("region", { name: "当前项目" });
  expect(within(currentCard).getByRole("button", { name: "打开真实蛋白质研究" })).toBeInTheDocument();
  expect(await within(currentCard).findByText("42%")).toBeInTheDocument();
  expect(document.querySelector(".header-title")).toHaveTextContent("研究总览");
  expect(screen.getByRole("heading", { name: "研究总览", level: 1 })).toHaveClass("sr-only");
  expect(screen.getByRole("list", { name: "研究生命周期" })).toHaveTextContent("假设进行中");
});

test("fills the current project card with real stage and public artifact detail", async () => {
  const user = userEvent.setup();
  const summary = runFixture({
    run_id: "run-density",
    direction: "真实密度研究",
    status: "running",
    stages: undefined,
    artifacts: undefined,
  });
  vi.mocked(apiClient.listRuns).mockResolvedValue([summary]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages({
    ...summary,
    artifacts: artifactFixtures(),
  }, 5));
  const { router } = renderAppAt("/");

  const currentCard = await screen.findByRole("region", { name: "当前项目" });
  expect(within(currentCard).getByText("假设（进行中）")).toBeInTheDocument();
  expect(within(currentCard).getByText("3 项")).toBeInTheDocument();
  await user.click(within(currentCard).getByRole("button", { name: "查看真实密度研究的阶段与产物" }));

  expect(router.state.location.pathname).toBe("/projects");
  expect(router.state.location.search).toBe("?run=run-density");
});

test("shows an honest no-run state, navigates to creation space, and skips detail", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  const { router } = renderAppAt("/");

  expect(await screen.findByText("还没有研究运行")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "新建研究" }));

  expect(router.state.location.pathname).toBe("/projects");
  expect(apiClient.getRun).not.toHaveBeenCalled();
});

test("shows initial loading and retries a failed run query", async () => {
  const user = userEvent.setup();
  const firstRequest = deferred<RunRecord[]>();
  vi.mocked(apiClient.listRuns)
    .mockReturnValueOnce(firstRequest.promise)
    .mockResolvedValueOnce([runFixture({ direction: "重试后的研究" })]);

  renderAppAt("/");
  expect(screen.getByText("正在加载…")).toBeInTheDocument();

  await act(async () => firstRequest.reject(new Error("运行列表不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("运行列表不可用");

  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("重试后的研究")).toBeInTheDocument();
});

test("keeps run content usable when health fails and retries health independently", async () => {
  const user = userEvent.setup();
  const run = runWithStages({ direction: "健康失败时仍可见" }, 8);
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue(run);
  vi.mocked(apiClient.health)
    .mockRejectedValueOnce(new Error("健康接口不可用"))
    .mockResolvedValueOnce(healthFixture());

  renderAppAt("/");

  const currentCard = await screen.findByRole("region", { name: "当前项目" });
  expect(within(currentCard).getByRole("button", { name: "打开健康失败时仍可见" })).toBeInTheDocument();
  const health = await screen.findByRole("region", { name: "系统健康" });
  expect(within(health).getByRole("alert")).toHaveTextContent("健康接口不可用");

  await user.click(within(health).getByRole("button", { name: "重试" }));
  expect(await within(health).findByText("服务正常")).toBeInTheDocument();
});

test("retains the last successful run list while a background refetch is pending", async () => {
  const initial = runWithStages({ run_id: "run-retained", direction: "保留中的真实研究" }, 4);
  const refreshed = runWithStages({ run_id: "run-retained", direction: "刷新后的真实研究" }, 5);
  const refetch = deferred<RunRecord[]>();
  vi.mocked(apiClient.listRuns)
    .mockResolvedValueOnce([initial])
    .mockReturnValueOnce(refetch.promise);
  vi.mocked(apiClient.getRun).mockResolvedValue(initial);
  const { queryClient } = renderAppAt("/");

  const recentTable = await screen.findByRole("table", { name: "近期研究" });
  expect(within(recentTable).getByText("保留中的真实研究")).toBeInTheDocument();

  void queryClient.refetchQueries({ queryKey: ["runs"] });
  await waitFor(() => expect(apiClient.listRuns).toHaveBeenCalledTimes(2));
  expect(within(recentTable).getByText("保留中的真实研究")).toBeInTheDocument();

  await act(async () => refetch.resolve([refreshed]));
  expect(await within(recentTable).findByText("刷新后的真实研究")).toBeInTheDocument();
});

test("renders the exact lifecycle, grids, and health section order after the shell header", async () => {
  const run = runWithStages({ direction: "顺序验证研究" }, 3);
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue(run);
  renderAppAt("/");

  const currentCard = await screen.findByRole("region", { name: "当前项目" });
  expect(within(currentCard).getByRole("button", { name: "打开顺序验证研究" })).toBeInTheDocument();
  const orderedElements = [
    document.querySelector(".app-header"),
    screen.getByRole("region", { name: "研究生命周期" }),
    screen.getByTestId("dashboard-primary-grid"),
    screen.getByTestId("dashboard-secondary-grid"),
    screen.getByRole("region", { name: "系统健康" }),
  ];

  expect(orderedElements.every((element) => element instanceof HTMLElement)).toBe(true);
  for (let index = 0; index < orderedElements.length - 1; index += 1) {
    expect(orderedElements[index]!.compareDocumentPosition(orderedElements[index + 1]!))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  }
});

test("states the approval capability boundary and offers no approval actions", async () => {
  renderAppAt("/");

  await screen.findByText("还没有研究运行");
  const approval = screen.getByRole("region", { name: "待审批" });
  expect(approval).toHaveTextContent("当前服务未提供审批队列接口");
  expect(within(approval).queryByRole("button")).not.toBeInTheDocument();
  expect(within(approval).queryByRole("link")).not.toBeInTheDocument();
});

test("shows the exact empty trend message when fewer than two runs have real stages", async () => {
  const runWithoutStages = runFixture({ run_id: "run-no-stages", stages: undefined });
  const singlePoint = runWithStages({ run_id: "run-one-point" }, 6);
  vi.mocked(apiClient.listRuns).mockResolvedValue([runWithoutStages, singlePoint]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithoutStages);
  renderAppAt("/");

  expect(await screen.findByText("积累至少两个运行后显示趋势")).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "研究证据覆盖趋势数据" })).not.toBeInTheDocument();
  expect(chartMocks.init).not.toHaveBeenCalled();
});

test("charts only real staged runs and provides a semantic table fallback", async () => {
  const runs = [
    runWithStages({ run_id: "run-quarter", direction: "四分之一覆盖", created_at: "2026-08-18T06:00:00Z" }, 3),
    runWithStages({ run_id: "run-half", direction: "二分之一覆盖", created_at: "2026-08-19T06:00:00Z" }, 6),
    runFixture({ run_id: "run-unstaged", direction: "无阶段运行", created_at: "2026-08-20T06:00:00Z", stages: undefined }),
  ];
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runs[2]!);
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => runs.find((run) => run.run_id === runId)?.stages ?? []);
  const view = renderAppAt("/");

  const fallback = await screen.findByRole("table", { name: "研究证据覆盖趋势数据" });
  expect(within(fallback).getByRole("row", { name: /四分之一覆盖 25%/ })).toBeInTheDocument();
  expect(within(fallback).getByRole("row", { name: /二分之一覆盖 50%/ })).toBeInTheDocument();
  expect(within(fallback).queryByText("无阶段运行")).not.toBeInTheDocument();
  expect(chartMocks.init).toHaveBeenCalledTimes(1);

  view.unmount();
  expect(chartMocks.dispose).toHaveBeenCalledTimes(1);
});

test("opens current and recent runs through deterministic project navigation", async () => {
  const user = userEvent.setup();
  const current = runWithStages({ run_id: "run-current", direction: "当前可打开研究", status: "running" }, 7);
  const recent = runWithStages({ run_id: "run-recent", direction: "近期可打开研究", status: "completed" }, 12);
  vi.mocked(apiClient.listRuns).mockResolvedValue([recent, current]);
  vi.mocked(apiClient.getRun).mockResolvedValue(current);
  const first = renderAppAt("/");

  const currentCard = await screen.findByRole("region", { name: "当前项目" });
  await user.click(within(currentCard).getByRole("button", { name: "打开当前可打开研究" }));
  expect(first.router.state.location.pathname).toBe("/projects");
  expect(first.router.state.location.search).toBe("?run=run-current");
  first.unmount();

  const second = renderAppAt("/");
  const recentTable = await screen.findByRole("table", { name: "近期研究" });
  await user.click(within(recentTable).getByRole("button", { name: "打开近期可打开研究" }));
  expect(second.router.state.location.pathname).toBe("/projects");
  expect(second.router.state.location.search).toBe("?run=run-recent");
});

test("health content is limited to API capability facts", async () => {
  renderAppAt("/");

  const health = await screen.findByRole("region", { name: "系统健康" });
  await within(health).findByText("服务正常");
  expect(health).toHaveTextContent("正式实验未启用");
  expect(health).toHaveTextContent("批量执行已配置");
  expect(health).toHaveTextContent("自进化未配置");
  expect(health).not.toHaveTextContent(/存储|GPU|备份/);
});

test("enriches stage-less production summaries into a real coverage trend", async () => {
  const runs = [
    runSummary({ run_id: "run-stage-a", direction: "阶段接口甲", created_at: "2026-08-18T06:00:00Z" }),
    runSummary({ run_id: "run-stage-b", direction: "阶段接口乙", created_at: "2026-08-19T06:00:00Z" }),
  ];
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(runs[1]!, 6));
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => runId === "run-stage-a" ? stageFixtures(3) : stageFixtures(6));

  renderAppAt("/");

  const trend = await screen.findByRole("table", { name: "研究证据覆盖趋势数据" });
  expect(within(trend).getByRole("row", { name: /阶段接口甲 25%/ })).toBeInTheDocument();
  expect(within(trend).getByRole("row", { name: /阶段接口乙 50%/ })).toBeInTheDocument();
  const recent = screen.getByRole("table", { name: "近期研究" });
  expect(within(recent).getByRole("row", { name: /阶段接口甲.*25%/ })).toBeInTheDocument();
});

test("selects and enriches only the deterministic latest six runs", async () => {
  const runs = [
    runSummary({ run_id: "run-old", direction: "旧运行", created_at: "2026-08-14T06:00:00Z" }),
    runSummary({ run_id: "run-tie-b", direction: "同刻乙", created_at: "2026-08-20T09:00:00Z" }),
    runSummary({ run_id: "run-six", direction: "第六新", created_at: "2026-08-17T06:00:00Z" }),
    runSummary({ run_id: "run-newest", direction: "最新运行", created_at: "2026-08-20T10:00:00Z" }),
    runSummary({ run_id: "run-eight", direction: "第八新", created_at: "2026-08-19T06:00:00Z" }),
    runSummary({ run_id: "run-tie-a", direction: "同刻甲", created_at: "2026-08-20T09:00:00Z" }),
    runSummary({ run_id: "run-too-old", direction: "最旧运行", created_at: "2026-08-13T06:00:00Z" }),
    runSummary({ run_id: "run-seven", direction: "第七新", created_at: "2026-08-18T06:00:00Z" }),
  ];
  const completedById: Record<string, number> = {
    "run-six": 1,
    "run-seven": 2,
    "run-eight": 3,
    "run-tie-a": 4,
    "run-tie-b": 5,
    "run-newest": 6,
  };
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(runs[3]!, 6));
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => stageFixtures(completedById[runId] ?? 0));
  const { queryClient } = renderAppAt("/");

  const trend = await screen.findByRole("table", { name: "研究证据覆盖趋势数据" });
  const rows = within(trend).getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(rows).toEqual([
    "第六新8%",
    "第七新17%",
    "第八新25%",
    "同刻甲33%",
    "同刻乙42%",
    "最新运行50%",
  ]);
  expect(vi.mocked(apiClient.getStages).mock.calls.map(([runId]) => runId)).toEqual([
    "run-newest",
    "run-tie-a",
    "run-tie-b",
    "run-eight",
    "run-seven",
    "run-six",
  ]);
  expect(queryClient.getQueryCache().findAll({ queryKey: ["run-stages"] }).map((query) => query.queryKey)).toEqual([
    ["run-stages", "run-newest"],
    ["run-stages", "run-tie-a"],
    ["run-stages", "run-tie-b"],
    ["run-stages", "run-eight"],
    ["run-stages", "run-seven"],
    ["run-stages", "run-six"],
  ]);
});

test("degrades one failed stage query without hiding the Dashboard", async () => {
  const runs = [
    runSummary({ run_id: "run-good-a", direction: "可用阶段甲", created_at: "2026-08-18T06:00:00Z" }),
    runSummary({ run_id: "run-broken", direction: "阶段暂不可用", created_at: "2026-08-19T06:00:00Z" }),
    runSummary({ run_id: "run-good-b", direction: "可用阶段乙", created_at: "2026-08-20T06:00:00Z" }),
  ];
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(runs[2]!, 8));
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => {
    if (runId === "run-broken") throw new Error("单个阶段接口失败");
    return runId === "run-good-a" ? stageFixtures(3) : stageFixtures(6);
  });

  renderAppAt("/");

  const recent = await screen.findByRole("table", { name: "近期研究" });
  expect(within(recent).getByRole("row", { name: /阶段暂不可用.*未提供/ })).toBeInTheDocument();
  const trend = screen.getByRole("table", { name: "研究证据覆盖趋势数据" });
  expect(within(trend).getByText("可用阶段甲")).toBeInTheDocument();
  expect(within(trend).getByText("可用阶段乙")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "研究生命周期" })).toBeInTheDocument();
});

test("drops prior-ID detail immediately when the selected current run changes", async () => {
  const oldSummary = runSummary({ run_id: "run-old-current", direction: "旧当前运行", status: "running", created_at: "2026-08-19T06:00:00Z" });
  const newSummary = runSummary({ run_id: "run-new-current", direction: "新当前运行", status: "running", created_at: "2026-08-20T06:00:00Z" });
  const newDetail = deferred<RunRecord>();
  vi.mocked(apiClient.listRuns).mockResolvedValueOnce([oldSummary]).mockResolvedValueOnce([newSummary]);
  vi.mocked(apiClient.getRun).mockImplementation((runId) => runId === oldSummary.run_id
    ? Promise.resolve(runWithStages(oldSummary, 3))
    : newDetail.promise);
  const { queryClient } = renderAppAt("/");

  const current = await screen.findByRole("region", { name: "当前项目" });
  expect(await within(current).findByText("25%")).toBeInTheDocument();
  await queryClient.refetchQueries({ queryKey: ["runs"] });

  expect(await within(current).findByRole("button", { name: "打开新当前运行" })).toBeInTheDocument();
  expect(within(current).queryByText("25%")).not.toBeInTheDocument();
  expect(current).toHaveTextContent("阶段数据未提供");
  await act(async () => newDetail.resolve(runWithStages(newSummary, 6)));
  expect(await within(current).findByText("50%")).toBeInTheDocument();
});

test("continues detail polling when same-ID detail remains active after the summary turns terminal", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const summary = runSummary({ run_id: "run-detail-active", direction: "详情仍运行", status: "completed" });
  const detail = runWithStages({ ...summary, status: "running", finished_at: null }, 5);
  vi.mocked(apiClient.listRuns).mockResolvedValue([summary]);
  vi.mocked(apiClient.getRun).mockResolvedValue(detail);
  renderAppAt("/");

  const current = await screen.findByRole("region", { name: "当前项目" });
  expect(await within(current).findByText("42%")).toBeInTheDocument();
  expect(current).toHaveTextContent("进行中");
  await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
  expect(apiClient.getRun).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});

test("uses a terminal detail consistently and stops polling despite an active summary", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const summary = runSummary({ run_id: "run-detail-terminal", direction: "详情已完成", status: "running" });
  const detail = runWithStages({ ...summary, status: "completed", finished_at: "2026-08-20T07:00:00Z" }, 12);
  vi.mocked(apiClient.listRuns).mockResolvedValue([summary]);
  vi.mocked(apiClient.getRun).mockResolvedValue(detail);
  renderAppAt("/");

  const current = await screen.findByRole("region", { name: "当前项目" });
  expect(await within(current).findByText("100%")).toBeInTheDocument();
  expect(current).toHaveTextContent("已完成");
  expect(current).not.toHaveTextContent("进行中");
  expect(screen.getByRole("list", { name: "研究生命周期" })).not.toHaveTextContent("进行中");
  await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
  expect(apiClient.getRun).toHaveBeenCalledTimes(1);
  vi.useRealTimers();
});

test("retains coherent detail during background failure and retries it in place", async () => {
  const user = userEvent.setup();
  const summary = runSummary({ run_id: "run-detail-retained", direction: "详情保留研究", status: "running" });
  const initialDetail = runWithStages(summary, 3);
  vi.mocked(apiClient.listRuns).mockResolvedValue([summary]);
  vi.mocked(apiClient.getRun)
    .mockResolvedValueOnce(initialDetail)
    .mockRejectedValueOnce(new Error("详情刷新失败"))
    .mockResolvedValueOnce(runWithStages(summary, 6));
  const { queryClient } = renderAppAt("/");

  const current = await screen.findByRole("region", { name: "当前项目" });
  expect(await within(current).findByText("25%")).toBeInTheDocument();
  await queryClient.refetchQueries({ queryKey: ["run", summary.run_id] });

  expect(within(current).getByText("25%")).toBeInTheDocument();
  expect(await within(current).findByRole("alert")).toHaveTextContent("详情刷新失败");
  await user.click(within(current).getByRole("button", { name: "重试运行详情" }));
  expect(await within(current).findByText("50%")).toBeInTheDocument();
  expect(within(current).queryByRole("alert")).not.toBeInTheDocument();
});

test("encodes reserved run ID characters in project navigation", async () => {
  const user = userEvent.setup();
  const run = runSummary({ run_id: "run/id ?#%", direction: "保留字符运行", status: "running" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(run, 1));
  const { router } = renderAppAt("/");

  const current = await screen.findByRole("region", { name: "当前项目" });
  await user.click(within(current).getByRole("button", { name: "打开保留字符运行" }));
  expect(router.state.location.search).toBe("?run=run%2Fid%20%3F%23%25");
});

test("resizes from ResizeObserver and disconnects before chart disposal", async () => {
  let resizeCallback: ResizeObserverCallback | undefined;
  const disconnect = vi.fn();
  const observe = vi.fn();
  class ObservableResizeObserver {
    constructor(callback: ResizeObserverCallback) { resizeCallback = callback; }
    disconnect = disconnect;
    observe = observe;
    unobserve() {}
  }
  vi.stubGlobal("ResizeObserver", ObservableResizeObserver);
  const runs = [
    runSummary({ run_id: "run-resize-a", direction: "缩放甲", created_at: "2026-08-18T06:00:00Z" }),
    runSummary({ run_id: "run-resize-b", direction: "缩放乙", created_at: "2026-08-19T06:00:00Z" }),
  ];
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(runs[1]!, 6));
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => runId === "run-resize-a" ? stageFixtures(3) : stageFixtures(6));
  const view = renderAppAt("/");

  await screen.findByRole("table", { name: "研究证据覆盖趋势数据" });
  expect(observe).toHaveBeenCalledTimes(1);
  act(() => resizeCallback?.([] as ResizeObserverEntry[], {} as ResizeObserver));
  expect(chartMocks.resize).toHaveBeenCalledTimes(1);

  view.unmount();
  expect(disconnect).toHaveBeenCalledTimes(1);
  expect(chartMocks.dispose).toHaveBeenCalledTimes(1);
});

test("polls stages for a non-current selected run while that run remains active", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const backgroundRun = runSummary({
    run_id: "run-background-active",
    direction: "后台活动运行",
    status: "running",
    created_at: "2026-08-19T06:00:00Z",
  });
  const currentRun = runSummary({
    run_id: "run-current-active",
    direction: "当前活动运行",
    status: "running",
    created_at: "2026-08-20T06:00:00Z",
  });
  vi.mocked(apiClient.listRuns).mockResolvedValue([backgroundRun, currentRun]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(currentRun, 6));
  vi.mocked(apiClient.getStages).mockResolvedValue(stageFixtures(3));
  renderAppAt("/");

  await waitFor(() => expect(apiClient.getStages).toHaveBeenCalledTimes(2));
  expect(vi.mocked(apiClient.getStages).mock.calls.filter(([runId]) => runId === backgroundRun.run_id)).toHaveLength(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
  expect(vi.mocked(apiClient.getStages).mock.calls.filter(([runId]) => runId === backgroundRun.run_id)).toHaveLength(2);
});

test("refreshes stages once when an active selected run becomes terminal, then stops polling it", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const activeRun = runSummary({
    run_id: "run-finishing",
    direction: "即将完成运行",
    status: "running",
    created_at: "2026-08-19T06:00:00Z",
  });
  const currentRun = runSummary({
    run_id: "run-still-active",
    direction: "仍在运行",
    status: "running",
    created_at: "2026-08-20T06:00:00Z",
  });
  const terminalRun = { ...activeRun, status: "completed" as const, finished_at: "2026-08-20T07:00:00Z" };
  vi.mocked(apiClient.listRuns)
    .mockResolvedValueOnce([activeRun, currentRun])
    .mockResolvedValueOnce([terminalRun, currentRun]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(currentRun, 6));
  vi.mocked(apiClient.getStages).mockResolvedValue(stageFixtures(3));
  const { queryClient } = renderAppAt("/");

  await waitFor(() => expect(apiClient.getStages).toHaveBeenCalledTimes(2));
  await queryClient.refetchQueries({ queryKey: ["runs"], exact: true });
  await waitFor(() => expect(
    vi.mocked(apiClient.getStages).mock.calls.filter(([runId]) => runId === activeRun.run_id),
  ).toHaveLength(2));

  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(vi.mocked(apiClient.getStages).mock.calls.filter(([runId]) => runId === activeRun.run_id)).toHaveLength(2);
});

test("keeps an unchanged chart instance across unrelated fetching renders and reinitializes for changed points", async () => {
  const healthRefetch = deferred<ReturnType<typeof healthFixture>>();
  const runs = [
    runSummary({ run_id: "run-chart-a", direction: "图表甲", status: "completed", created_at: "2026-08-19T06:00:00Z" }),
    runSummary({ run_id: "run-chart-b", direction: "图表乙", status: "completed", created_at: "2026-08-20T06:00:00Z" }),
  ];
  let firstRunStageRequests = 0;
  vi.mocked(apiClient.listRuns).mockResolvedValue(runs);
  vi.mocked(apiClient.getRun).mockResolvedValue(runWithStages(runs[1]!, 6));
  vi.mocked(apiClient.getStages).mockImplementation(async (runId) => {
    if (runId === runs[0]!.run_id) {
      firstRunStageRequests += 1;
      return stageFixtures(firstRunStageRequests === 1 ? 3 : 6);
    }
    return stageFixtures(6);
  });
  vi.mocked(apiClient.health)
    .mockResolvedValueOnce(healthFixture())
    .mockReturnValueOnce(healthRefetch.promise);
  const view = renderAppAt("/");

  const trend = await screen.findByRole("table", { name: "研究证据覆盖趋势数据" });
  await waitFor(() => expect(apiClient.getStages).toHaveBeenCalledTimes(2));
  const initializations = chartMocks.init.mock.calls.length;
  const disposals = chartMocks.dispose.mock.calls.length;

  void view.queryClient.refetchQueries({ queryKey: ["health"], exact: true });
  await waitFor(() => expect(view.container.querySelector(".dashboard-page")).toHaveAttribute("data-loading", "true"));
  expect(chartMocks.init).toHaveBeenCalledTimes(initializations);
  expect(chartMocks.dispose).toHaveBeenCalledTimes(disposals);

  await act(async () => healthRefetch.resolve(healthFixture()));
  await waitFor(() => expect(view.container.querySelector(".dashboard-page")).toHaveAttribute("data-loading", "false"));
  expect(chartMocks.init).toHaveBeenCalledTimes(initializations);
  expect(chartMocks.dispose).toHaveBeenCalledTimes(disposals);

  await view.queryClient.refetchQueries({ queryKey: ["run-stages", runs[0]!.run_id], exact: true });
  expect(await within(trend).findByRole("row", { name: /图表甲 50%/ })).toBeInTheDocument();
  expect(chartMocks.init).toHaveBeenCalledTimes(initializations + 1);
  expect(chartMocks.dispose).toHaveBeenCalledTimes(disposals + 1);
});
