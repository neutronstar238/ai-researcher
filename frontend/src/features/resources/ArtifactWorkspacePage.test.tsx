import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "../../lib/api/client";
import type { RunRecord } from "../../lib/api/types";
import { artifactFixtures, runFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/client")>();
  return {
    ...actual,
    apiClient: {
      getRun: vi.fn(),
      listRuns: vi.fn(),
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
  return runFixture({ artifacts: undefined, stages: undefined, ...overrides });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
});

test.each([
  ["/literature", "文献库", ["literature/broad/source.json"]],
  ["/experiments", "实验管理", ["pilot/metrics.json"]],
  ["/assets", "数据资产", ["literature/broad/source.json", "pilot/metrics.json", "plan/research-plan.pdf"]],
  ["/writing", "写作中心", ["plan/research-plan.pdf"]],
] as const)("loads stage-less summaries then filters real detail artifacts for %s", async (path, heading, expected) => {
  const run = summary({ direction: "服务端运行" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ artifacts: artifactFixtures() }));

  renderAppAt(path);

  expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  const list = await screen.findByRole("list", { name: `${heading}产物` });
  expect(within(list).getAllByRole("link").map((link) => link.textContent)).toEqual(expected);
  expect(apiClient.getRun).toHaveBeenCalledTimes(1);
  expect(apiClient.getRun).toHaveBeenCalledWith(run.run_id);
});

test("uses the server URL verbatim and never exposes output_dir or private paths", async () => {
  const run = summary();
  const artifact = {
    ...artifactFixtures()[0]!,
    relative_path: "literature/result file?.json",
    url: "/signed/download?token=a%2Fb&name=result%20file.json",
  };
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({
    artifacts: [artifact],
    output_dir: "D:/private/provider-responses",
  }));

  renderAppAt("/literature");

  const link = await screen.findByRole("link", { name: artifact.relative_path });
  expect(link).toHaveAttribute("href", artifact.url);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noreferrer");
  expect(screen.getByText(/literature · 640 bytes · application\/json · a{12}/)).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("D:/private");
  expect(document.body).not.toHaveTextContent("output_dir");
});

test("shows scoped list loading, list error retry, and a real no-run empty state", async () => {
  const user = userEvent.setup();
  const pending = deferred<RunRecord[]>();
  vi.mocked(apiClient.listRuns)
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce([]);

  renderAppAt("/assets");

  expect(screen.getByRole("heading", { name: "数据资产" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "正在加载运行列表" })).toBeInTheDocument();
  await act(async () => pending.reject(new Error("运行列表不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("运行列表不可用");
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("还没有研究运行")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "前往项目空间" })).toHaveAttribute("href", "/projects");
});

test("retains the selected run across detail errors and retries the exact identity", async () => {
  const user = userEvent.setup();
  const first = summary({ run_id: "run-first", direction: "第一个运行", status: "running" });
  const second = summary({ run_id: "run-second", direction: "第二个运行" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([first, second]);
  vi.mocked(apiClient.getRun)
    .mockRejectedValueOnce(new Error("详情不可用"))
    .mockResolvedValueOnce(runFixture({ run_id: first.run_id, direction: first.direction, artifacts: [] }));

  renderAppAt("/writing");

  const select = await screen.findByRole("combobox", { name: "研究运行" });
  expect(select).toHaveValue(first.run_id);
  expect(await screen.findByRole("alert")).toHaveTextContent("详情不可用");
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("写作中心暂无可用产物")).toBeInTheDocument();
  expect(select).toHaveValue(first.run_id);
  expect(apiClient.getRun).toHaveBeenNthCalledWith(2, first.run_id);
  expect(screen.getByRole("link", { name: "查看运行详情" })).toHaveAttribute("href", "/projects?run=run-first");
});

test("does not leak stale detail when a slower old run resolves after selection changes", async () => {
  const user = userEvent.setup();
  const oldRun = summary({ run_id: "run-old", direction: "旧运行", status: "running" });
  const newRun = summary({ run_id: "run-new", direction: "新运行" });
  const oldDetail = deferred<RunRecord>();
  const newDetail = deferred<RunRecord>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([oldRun, newRun]);
  vi.mocked(apiClient.getRun).mockImplementation((id) => id === oldRun.run_id ? oldDetail.promise : newDetail.promise);

  renderAppAt("/assets");
  const select = await screen.findByRole("combobox", { name: "研究运行" });
  await user.selectOptions(select, newRun.run_id);
  await waitFor(() => expect(apiClient.getRun).toHaveBeenCalledWith(newRun.run_id));
  await act(async () => newDetail.resolve(runFixture({
    run_id: newRun.run_id,
    direction: newRun.direction,
    artifacts: [{ ...artifactFixtures()[1]!, relative_path: "new/metrics.json" }],
  })));
  expect(await screen.findByRole("link", { name: "new/metrics.json" })).toBeInTheDocument();

  await act(async () => oldDetail.resolve(runFixture({
    run_id: oldRun.run_id,
    direction: oldRun.direction,
    artifacts: [{ ...artifactFixtures()[1]!, relative_path: "old/metrics.json" }],
  })));
  await waitFor(() => expect(screen.queryByRole("link", { name: "old/metrics.json" })).not.toBeInTheDocument());
  expect(select).toHaveValue(newRun.run_id);
  expect(apiClient.getRun).toHaveBeenCalledTimes(2);
});
