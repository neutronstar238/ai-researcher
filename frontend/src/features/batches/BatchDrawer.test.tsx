import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient, ApiError } from "../../lib/api/client";
import type { BatchRecord } from "../../lib/api/types";
import { runFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";
import { parseQuestionIds } from "./BatchDrawer";

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

function batchFixture(overrides: Partial<BatchRecord> = {}): BatchRecord {
  return {
    schema_version: "autoresearch-api-batch-preview-v1",
    batch_id: "batch-fixture123",
    status: "dry_run",
    dry_run: true,
    question_count: 125,
    created_at: "2026-08-20T06:30:00Z",
    items: [],
    batch_service_configured: false,
    question_pdf: "D:/private/questions.pdf",
    batch_service_receipt: { output_root: "D:/private/batches/batch-fixture123" },
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

test.each([
  ["blank input", "   ", []],
  ["one ID", "7", [7]],
  ["trimmed IDs sorted ascending", " 125, 2,17 ", [2, 17, 125]],
] as const)("strict parser accepts %s", (_caseName, raw, expected) => {
  expect(parseQuestionIds(raw)).toEqual(expected);
});

test.each([
  ["a trailing empty segment", "1,"],
  ["a leading empty segment", ",1"],
  ["an interior empty segment", "1,,2"],
  ["a decimal", "1.5"],
  ["a non-number", "one"],
  ["zero", "0"],
  ["an out-of-range ID", "126"],
] as const)("strict parser rejects %s without silently filtering it", (_caseName, raw) => {
  expect(() => parseQuestionIds(raw)).toThrow("题号必须是 1 到 125 的整数");
});

test("strict parser rejects duplicate IDs", () => {
  expect(() => parseQuestionIds("2, 1, 2")).toThrow("题号不能重复");
});

test("submits exactly the six normalized fields with the safe dry-run defaults", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createBatch).mockResolvedValue(batchFixture());
  const { queryClient } = renderAppAt("/projects");
  const cancel = vi.spyOn(queryClient, "cancelQueries");
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "  D:/science125.pdf  ");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  expect(apiClient.createBatch).toHaveBeenCalledWith({
    question_pdf: "D:/science125.pdf",
    start: 1,
    limit: 125,
    include_question_ids: [],
    resume: false,
    dry_run: true,
  });
  await waitFor(() => expect(cancel).toHaveBeenCalledWith({ queryKey: ["batches"], exact: true }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["batches"], exact: true });
});

test("starts a fresh exact batch GET after creation and ignores the older empty response", async () => {
  const user = userEvent.setup();
  const initialList = deferred<BatchRecord[]>();
  const created = batchFixture({ batch_id: "batch-race-new123", question_count: 4 });
  vi.mocked(apiClient.listBatches)
    .mockReturnValueOnce(initialList.promise)
    .mockResolvedValueOnce([created]);
  vi.mocked(apiClient.createBatch).mockResolvedValue(created);
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  await waitFor(() => expect(apiClient.listBatches).toHaveBeenCalledTimes(2));
  const receipt = await screen.findByLabelText("批量任务创建回执");
  expect(within(receipt).getByText("batch-race-new123")).toBeInTheDocument();

  await act(async () => initialList.resolve([]));
  const table = await screen.findByRole("table", { name: "批量任务记录" });
  expect(within(table).getByText("batch-race-new123")).toBeInTheDocument();
});

test("submits a sorted non-dry payload when the user explicitly opts into execution", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createBatch).mockResolvedValue(batchFixture({
    status: "submitted",
    dry_run: false,
    question_count: 3,
  }));
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.clear(screen.getByLabelText("起始题号"));
  await user.type(screen.getByLabelText("起始题号"), "3");
  await user.clear(screen.getByLabelText("题目数量"));
  await user.type(screen.getByLabelText("题目数量"), "8");
  await user.type(screen.getByLabelText("指定题号"), "5, 2, 4");
  await user.click(screen.getByLabelText("续跑已有结果"));
  await user.click(screen.getByLabelText("安全预览，不执行正式批量研究"));
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  expect(apiClient.createBatch).toHaveBeenCalledWith({
    question_pdf: "D:/science125.pdf",
    start: 3,
    limit: 8,
    include_question_ids: [2, 4, 5],
    resume: true,
    dry_run: false,
  });
});

test.each([
  ["blank PDF path", "服务器 PDF 路径", "   ", "请输入服务器 PDF 路径"],
  ["start below range", "起始题号", "0", "起始题号必须是 1 到 125 的整数"],
  ["start decimal", "起始题号", "1.5", "起始题号必须是 1 到 125 的整数"],
  ["limit above range", "题目数量", "126", "题目数量必须是 1 到 125 的整数"],
  ["limit non-number", "题目数量", "abc", "题目数量必须是 1 到 125 的整数"],
  ["empty question ID segment", "指定题号", "1,,2", "题号必须是 1 到 125 的整数"],
] as const)("rejects %s before calling the service", async (_caseName, label, value, message) => {
  const user = userEvent.setup();
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  if (label !== "服务器 PDF 路径") {
    await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  }
  const input = screen.getByLabelText(label);
  await user.clear(input);
  await user.type(input, value);
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(message);
  expect(alert.id).not.toBe("");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input.getAttribute("aria-describedby")?.split(" ")).toContain(alert.id);
  for (const unrelatedLabel of ["服务器 PDF 路径", "起始题号", "题目数量", "指定题号"]) {
    if (unrelatedLabel === label) continue;
    const unrelated = screen.getByLabelText(unrelatedLabel);
    expect(unrelated).not.toHaveAttribute("aria-invalid", "true");
    expect(unrelated.getAttribute("aria-describedby")?.split(" ") ?? []).not.toContain(alert.id);
  }
  expect(apiClient.createBatch).not.toHaveBeenCalled();
});

test("shows strict ID validation inline before calling the service", async () => {
  const user = userEvent.setup();
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.type(screen.getByLabelText("指定题号"), "1,,2");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  expect(screen.getByRole("alert")).toHaveTextContent("题号必须是 1 到 125 的整数");
  const idsInput = screen.getByLabelText("指定题号");
  expect(idsInput).toHaveValue("1,,2");
  expect(idsInput).not.toHaveAttribute("inputmode", "numeric");
  expect(apiClient.createBatch).not.toHaveBeenCalled();
});

test.each([
  [409, "question_pdf must be an existing local PDF file", true],
  [503, "non-dry batch execution is unavailable until a BatchRunService is configured", false],
] as const)("retains every field after backend %i rejection", async (status, message, dryRun) => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createBatch).mockRejectedValue(new ApiError(status, message, "service_error"));
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/missing.pdf");
  await user.clear(screen.getByLabelText("起始题号"));
  await user.type(screen.getByLabelText("起始题号"), "4");
  await user.clear(screen.getByLabelText("题目数量"));
  await user.type(screen.getByLabelText("题目数量"), "6");
  await user.type(screen.getByLabelText("指定题号"), "2, 6, 4");
  await user.click(screen.getByLabelText("续跑已有结果"));
  if (!dryRun) await user.click(screen.getByLabelText("安全预览，不执行正式批量研究"));
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(message);
  expect(screen.getByLabelText("服务器 PDF 路径")).toHaveValue("D:/missing.pdf");
  expect(screen.getByLabelText("起始题号")).toHaveValue(4);
  expect(screen.getByLabelText("题目数量")).toHaveValue(6);
  expect(screen.getByLabelText("指定题号")).toHaveValue("2, 6, 4");
  expect(screen.getByLabelText("续跑已有结果")).toBeChecked();
  expect(screen.getByLabelText("安全预览，不执行正式批量研究")).toHaveProperty("checked", dryRun);
  for (const label of ["服务器 PDF 路径", "起始题号", "题目数量", "指定题号"]) {
    const input = screen.getByLabelText(label);
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    expect(input.getAttribute("aria-describedby")?.split(" ") ?? []).not.toContain(alert.id);
  }
  expect(screen.getByRole("dialog", { name: "批量任务" })).toBeInTheDocument();
  expect(screen.getByRole("status")).not.toHaveTextContent("批量任务已创建");
});

test("blocks duplicate submission and every dismissal path while creation is pending", async () => {
  const user = userEvent.setup();
  const request = deferred<BatchRecord>();
  vi.mocked(apiClient.createBatch).mockReturnValue(request.promise);
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  const submit = screen.getByRole("button", { name: "创建批量任务" });
  fireEvent.click(submit);
  fireEvent.click(submit);

  await waitFor(() => expect(apiClient.createBatch).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "创建中…" })).toBeDisabled();
  await user.keyboard("{Escape}");
  fireEvent.mouseDown(screen.getByTestId("drawer-backdrop"));
  fireEvent.click(within(screen.getByRole("dialog", { name: "批量任务" })).getByRole("button", { name: "关闭" }));
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.getByRole("dialog", { name: "批量任务" })).toBeInTheDocument();

  await act(async () => request.reject(new Error("服务暂不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("服务暂不可用");
  expect(screen.getByRole("button", { name: "创建批量任务" })).toBeEnabled();
});

test("keeps keyboard focus trapped through pending and receipt states, then restores the trigger", async () => {
  const user = userEvent.setup();
  const request = deferred<BatchRecord>();
  vi.mocked(apiClient.createBatch).mockReturnValue(request.promise);
  renderAppAt("/projects");

  const trigger = screen.getByRole("button", { name: "批量任务" });
  trigger.focus();
  await user.keyboard("{Enter}");
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  const submit = screen.getByRole("button", { name: "创建批量任务" });
  submit.focus();
  await user.keyboard("{Enter}");

  const drawer = screen.getByRole("dialog", { name: "批量任务" });
  await screen.findByRole("button", { name: "创建中…" });
  expect(drawer).toContainElement(document.activeElement as HTMLElement);
  for (let index = 0; index < 6; index += 1) {
    await user.tab();
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
  }
  for (let index = 0; index < 6; index += 1) {
    await user.tab({ shift: true });
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
  }

  await act(async () => request.resolve(batchFixture({ batch_id: "batch-focus123" })));
  const receiptHeading = await within(drawer).findByRole("heading", { name: "批量任务创建回执" });
  expect(receiptHeading).toHaveFocus();
  expect(drawer).toContainElement(document.activeElement as HTMLElement);

  for (let index = 0; index < 4; index += 1) {
    await user.tab();
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
  }
  for (let index = 0; index < 4; index += 1) {
    await user.tab({ shift: true });
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
  }

  const close = within(drawer).getByRole("button", { name: "关闭" });
  await user.tab();
  expect(close).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(screen.queryByRole("dialog", { name: "批量任务" })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

test("keeps only the public success receipt visible until the user closes the drawer", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.createBatch).mockResolvedValue(batchFixture({
    batch_id: "batch-public123",
    status: "dry_run",
    question_count: 3,
    created_at: "2026-08-20T07:00:00Z",
  }));
  renderAppAt("/projects");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));

  const drawer = await screen.findByRole("dialog", { name: "批量任务" });
  expect(within(drawer).getByText("batch-public123")).toBeInTheDocument();
  expect(within(drawer).getByText("dry_run")).toBeInTheDocument();
  expect(within(drawer).getByText("3")).toBeInTheDocument();
  expect(within(drawer).getByText("2026-08-20T07:00:00Z")).toBeInTheDocument();
  expect(within(drawer).queryByText("D:/private/questions.pdf")).not.toBeInTheDocument();
  expect(within(drawer).queryByText("D:/private/batches/batch-fixture123")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("批量任务已创建");

  await user.click(within(drawer).getByRole("button", { name: "关闭" }));
  expect(screen.queryByRole("dialog", { name: "批量任务" })).not.toBeInTheDocument();
});

test("settles one successful creation normally under StrictMode", async () => {
  const user = userEvent.setup();
  const request = deferred<BatchRecord>();
  vi.mocked(apiClient.createBatch).mockReturnValue(request.promise);
  renderAppAt("/projects", { strict: true });

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));
  await act(async () => request.resolve(batchFixture({ batch_id: "batch-strict123" })));

  expect(await screen.findByText("batch-strict123")).toBeInTheDocument();
  expect(screen.getAllByText("批量任务已创建")).toHaveLength(1);
});

test("does not publish stale success after an in-flight drawer unmounts", async () => {
  const user = userEvent.setup();
  const request = deferred<BatchRecord>();
  vi.mocked(apiClient.createBatch).mockReturnValue(request.promise);
  const rendered = renderAppAt("/projects", { strict: true });
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");

  await user.click(screen.getByRole("button", { name: "批量任务" }));
  await user.type(screen.getByLabelText("服务器 PDF 路径"), "D:/science125.pdf");
  await user.click(screen.getByRole("button", { name: "创建批量任务" }));
  rendered.unmount();
  await act(async () => request.resolve(batchFixture({ batch_id: "batch-stale123" })));

  expect(invalidate).not.toHaveBeenCalled();
});
