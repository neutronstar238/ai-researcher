import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.listBatches).mockResolvedValue([]);
  vi.mocked(apiClient.getStages).mockResolvedValue([]);
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
});

test("creates a trimmed run with the exact default payload and selects the server result", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createRun).mockResolvedValue(runFixture({
    run_id: "run-new12345",
    direction: "新问题",
    status: "queued",
    stages: undefined,
    artifacts: undefined,
  }));
  const { queryClient, router } = renderAppAt("/projects?q=%E6%9D%90%E6%96%99&view=table");
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "  新问题  ");
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(apiClient.createRun).toHaveBeenCalledWith({ direction: "新问题", dry_run: false });
  await waitFor(() => expect(router.state.location.search).toContain("run=run-new12345"));
  expect(router.state.location.search).toContain("q=%E6%9D%90%E6%96%99");
  expect(router.state.location.search).toContain("view=table");
  expect(screen.queryByRole("dialog", { name: "新建研究" })).not.toBeInTheDocument();
  expect(screen.getByText("研究运行已创建")).toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"] });
});

test("sends dry-run only when the user checks it", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createRun).mockResolvedValue(runFixture({ run_id: "run-dry12345", status: "dry_run" }));
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "Dry run 研究");
  await user.click(screen.getByLabelText("仅验证流程，不执行正式研究"));
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(apiClient.createRun).toHaveBeenCalledWith({ direction: "Dry run 研究", dry_run: true });
});

test("rejects a blank scientific question without calling the API", async () => {
  const user = userEvent.setup();
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "   ");
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(screen.getByRole("alert")).toHaveTextContent("请输入科学问题");
  expect(apiClient.createRun).not.toHaveBeenCalled();
});

test("keeps all user input after a 409 service rejection", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createRun).mockRejectedValue(new ApiError(409, "当前服务拒绝创建", "service_error"));
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "需保留的问题");
  await user.click(screen.getByLabelText("仅验证流程，不执行正式研究"));
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("当前服务拒绝创建");
  expect(screen.getByLabelText("科学问题")).toHaveValue("需保留的问题");
  expect(screen.getByLabelText("仅验证流程，不执行正式研究")).toBeChecked();
  expect(screen.getByRole("dialog", { name: "新建研究" })).toBeInTheDocument();
  expect(screen.getByRole("status")).not.toHaveTextContent("研究运行已创建");
});

test("blocks duplicate submission and every drawer dismissal while create is pending", async () => {
  const user = userEvent.setup();
  const request = deferred<RunRecord>();
  vi.mocked(apiClient.createRun).mockReturnValue(request.promise);
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "等待服务的问题");
  const submit = screen.getByRole("button", { name: "开始研究" });
  fireEvent.click(submit);
  fireEvent.click(submit);

  await waitFor(() => expect(apiClient.createRun).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "创建中…" })).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "新建研究" })).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByTestId("drawer-backdrop"));
  fireEvent.click(within(screen.getByRole("dialog", { name: "新建研究" })).getByRole("button", { name: "关闭" }));
  expect(screen.getByRole("dialog", { name: "新建研究" })).toBeInTheDocument();

  await act(async () => request.reject(new Error("服务暂不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("服务暂不可用");
  expect(screen.getByRole("button", { name: "开始研究" })).toBeEnabled();
});

test("Escape closes an idle create drawer and restores focus to its trigger", async () => {
  const user = userEvent.setup();
  renderAppAt("/projects");
  const trigger = screen.getByRole("button", { name: "新建研究" });

  await user.click(trigger);
  await user.keyboard("{Escape}");

  await waitFor(() => expect(screen.queryByRole("dialog", { name: "新建研究" })).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
});

test("selects a deferred server result against the latest browser search parameters", async () => {
  const user = userEvent.setup();
  const request = deferred<RunRecord>();
  vi.mocked(apiClient.createRun).mockReturnValue(request.promise);
  const { router } = renderAppAt("/projects?q=old&status=failed&tab=old");

  await user.click(screen.getByRole("button", { name: "新建研究" }));
  await user.type(screen.getByLabelText("科学问题"), "导航期间创建");
  await user.click(screen.getByRole("button", { name: "开始研究" }));
  await waitFor(() => expect(apiClient.createRun).toHaveBeenCalledTimes(1));

  await act(async () => {
    await router.navigate("/projects?q=new%20value&status=running&tab=new&extra=%2F%3F%23");
  });
  await act(async () => request.resolve(runFixture({
    run_id: "run/new ?#%",
    direction: "导航期间创建",
    status: "queued",
    stages: undefined,
    artifacts: undefined,
  })));

  await waitFor(() => expect(router.state.location.search).toContain("run=run%2Fnew+%3F%23%25"));
  expect(router.state.location.search).toBe("?q=new+value&status=running&tab=new&extra=%2F%3F%23&run=run%2Fnew+%3F%23%25");
  expect(router.state.location.search).not.toContain("old");
});
