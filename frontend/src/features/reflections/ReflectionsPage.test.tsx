import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient, ApiError } from "../../lib/api/client";
import type { RunRecord } from "../../lib/api/types";
import { runFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/client")>();
  return {
    ...actual,
    apiClient: {
      listRuns: vi.fn(),
      resumeRun: vi.fn(),
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

function failedRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return runFixture({
    artifacts: undefined,
    stages: undefined,
    status: "failed",
    error: { type: "ScientificGateError", message: "证据门未通过" },
    delivery_validation: null,
    ...overrides,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
});

test("orders only real failed and interrupted runs and renders validation facts without invention", async () => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([
    runFixture({ run_id: "run-completed", direction: "已完成", status: "completed" }),
    failedRun({ run_id: "run-older", direction: "较早失败", created_at: "2026-08-19T01:00:00Z", resume_count: 2 }),
    failedRun({
      run_id: "run-newer",
      direction: "较新中断",
      status: "interrupted",
      created_at: "2026-08-20T01:00:00Z",
      error: { type: "ApiProcessRestart", message: "服务进程重启" },
      delivery_validation: { status: "blocked", valid: false },
    }),
  ]);

  renderAppAt("/reflections");

  const list = await screen.findByRole("list", { name: "待复盘运行" });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[0]).toHaveTextContent("较新中断");
  expect(items[0]).toHaveTextContent("ApiProcessRestart");
  expect(items[0]).toHaveTextContent("服务进程重启");
  expect(items[0]).toHaveTextContent("blocked");
  expect(items[0]).toHaveTextContent("否");
  expect(items[1]).toHaveTextContent("较早失败");
  expect(items[1]).toHaveTextContent("未提供");
  expect(items[1]).toHaveTextContent("2");
  expect(list).not.toHaveTextContent("已完成");
  expect(document.body).not.toHaveTextContent("经验教训");
  expect(document.body).not.toHaveTextContent("审批人");
});

test("shows exact resume error inline and synchronously prevents duplicate actions", async () => {
  const user = userEvent.setup();
  const run = failedRun({ run_id: "run-resume-error", direction: "恢复失败研究" });
  const pending = deferred<RunRecord>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.resumeRun).mockReturnValue(pending.promise);

  renderAppAt("/reflections");
  const button = await screen.findByRole("button", { name: "恢复恢复失败研究" });
  await user.dblClick(button);
  expect(apiClient.resumeRun).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();

  await act(async () => pending.reject(new ApiError(409, "当前检查点不可恢复", "service_error")));
  expect(await screen.findByRole("alert")).toHaveTextContent("当前检查点不可恢复");
  expect(button).toBeEnabled();
});

test("invalidates the exact run caches and toasts only after server-confirmed resume", async () => {
  const user = userEvent.setup();
  const run = failedRun({ run_id: "run-resume-success", direction: "可恢复研究" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.resumeRun).mockResolvedValue(runFixture({ run_id: run.run_id, status: "queued" }));
  const { queryClient } = renderAppAt("/reflections", { strict: true });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

  await user.click(await screen.findByRole("button", { name: "恢复可恢复研究" }));

  expect(await screen.findByText("研究运行已恢复")).toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", run.run_id], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run-stages", run.run_id], exact: true });
});

test("suppresses stale settlement after unmount", async () => {
  const user = userEvent.setup();
  const run = failedRun({ run_id: "run-unmounted", direction: "卸载研究" });
  const pending = deferred<RunRecord>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.resumeRun).mockReturnValue(pending.promise);
  const rendered = renderAppAt("/reflections", { strict: true });
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");
  await user.click(await screen.findByRole("button", { name: "恢复卸载研究" }));
  rendered.unmount();

  await act(async () => pending.reject(new Error("卸载后的错误")));
  await waitFor(() => expect(screen.queryByText("卸载后的错误")).not.toBeInTheDocument());
  expect(invalidate).not.toHaveBeenCalled();
});

test("successful resume after navigation invalidates exact caches and refetches on return without a stale toast", async () => {
  const user = userEvent.setup();
  const run = failedRun({ run_id: "run-navigation-success", direction: "离开后恢复成功" });
  const pending = deferred<RunRecord>();
  vi.mocked(apiClient.listRuns)
    .mockResolvedValueOnce([run])
    .mockResolvedValueOnce([runFixture({ run_id: run.run_id, direction: run.direction, status: "queued" })]);
  vi.mocked(apiClient.resumeRun).mockReturnValue(pending.promise);
  const rendered = renderAppAt("/reflections", { strict: true });
  rendered.queryClient.setQueryDefaults(["runs"], { staleTime: Infinity });
  rendered.queryClient.setQueryData(["run", run.run_id], run);
  rendered.queryClient.setQueryData(["run-stages", run.run_id], [{ stage_id: "stage-old" }]);
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");
  await user.click(await screen.findByRole("button", { name: "恢复离开后恢复成功" }));
  await act(async () => { await rendered.router.navigate("/knowledge"); });

  await act(async () => pending.resolve(runFixture({ run_id: run.run_id, status: "queued" })));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"], exact: true }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", run.run_id], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run-stages", run.run_id], exact: true });
  expect(rendered.queryClient.getQueryState(["run", run.run_id])?.isInvalidated).toBe(true);
  expect(rendered.queryClient.getQueryState(["run-stages", run.run_id])?.isInvalidated).toBe(true);
  expect(screen.queryByText("研究运行已恢复")).not.toBeInTheDocument();

  await act(async () => { await rendered.router.navigate("/reflections"); });
  expect(await screen.findByText("没有失败或中断的运行需要复盘")).toBeInTheDocument();
  expect(apiClient.listRuns).toHaveBeenCalledTimes(2);
});

test("shows list loading, error retry, and an honest empty review state", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.listRuns)
    .mockRejectedValueOnce(new Error("复盘列表失败"))
    .mockResolvedValueOnce([runFixture({ status: "completed" })]);

  renderAppAt("/reflections");

  expect(await screen.findByRole("alert")).toHaveTextContent("复盘列表失败");
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("没有失败或中断的运行需要复盘")).toBeInTheDocument();
});
