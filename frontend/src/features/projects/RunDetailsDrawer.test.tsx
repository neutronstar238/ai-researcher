import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "../../lib/api/client";
import type { EvolutionReceipt, RunRecord } from "../../lib/api/types";
import { artifactFixtures, runFixture, stageFixtures } from "../../test/fixtures";
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
      getArtifactText: vi.fn(),
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

const evolutionReceipt: EvolutionReceipt = {
  schema_version: "autoresearch-api-skill-evolution-receipt-v1",
  run_id: "run-fixture123",
  status: "completed",
  result: {},
  promotion_authorized: false,
  created_at: "2026-08-20T08:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.listBatches).mockResolvedValue([]);
  vi.mocked(apiClient.getStages).mockResolvedValue([]);
  vi.mocked(apiClient.getArtifactText).mockResolvedValue("{}");
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture());
});

test("renders all twelve server stages and uses artifact URLs verbatim without private paths", async () => {
  const artifacts = artifactFixtures();
  artifacts[0] = {
    ...artifacts[0]!,
    relative_path: "reports/result file?.pdf",
    url: "/signed/download?token=a%2Fb&name=result%20file.pdf",
  };
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({
    direction: "十二阶段研究",
    stages: stageFixtures(12),
    artifacts,
  }));
  renderAppAt("/projects?run=run-fixture123");

  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  expect(await within(drawer).findAllByRole("listitem", { name: /阶段/ })).toHaveLength(12);
  expect(within(drawer).getByText("1. broad-literature-query")).toBeInTheDocument();
  expect(within(drawer).getAllByText("1 个产物")).toHaveLength(12);
  expect(within(drawer).getAllByText(/^1{10}$/)).not.toHaveLength(0);
  const artifact = within(drawer).getByRole("link", { name: "reports/result file?.pdf" });
  expect(artifact).toHaveAttribute("href", "/signed/download?token=a%2Fb&name=result%20file.pdf");
  expect(artifact).toHaveAttribute("target", "_blank");
  expect(artifact).toHaveAttribute("rel", "noreferrer");
  expect(drawer).not.toHaveTextContent("runs/research-api");
  expect(drawer).not.toHaveTextContent("output_dir");
});

test("shows model outputs inline and summarizes their logical call path", async () => {
  const user = userEvent.setup();
  const responseArtifact = {
    ...artifactFixtures()[0]!,
    relative_path: "literature/refinement/direction-focus-selection-response.json",
    bytes: 2048,
    url: "/api/runs/run-fixture123/artifacts/literature/refinement/direction-focus-selection-response.json",
  };
  const attemptArtifact = {
    ...artifactFixtures()[0]!,
    relative_path: "checkpoints/provider-call-attempts/focus-selection/call-1/attempt-01-reservation.json",
    url: "/api/runs/run-fixture123/artifacts/checkpoints/provider-call-attempts/focus-selection/call-1/attempt-01-reservation.json",
  };
  const stages = stageFixtures(1);
  stages[1] = { ...stages[1]!, status: "running" };
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({
    status: "running",
    stages,
    artifacts: [responseArtifact, attemptArtifact, artifactFixtures()[2]!],
  }));
  vi.mocked(apiClient.getArtifactText).mockResolvedValue(JSON.stringify({
    completion: {
      model_name: "qwen-test",
      parsed_json: { selected_candidate_number: 1, rationale: "真实模型输出" },
    },
  }));
  renderAppAt("/projects?run=run-fixture123");

  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  expect(drawer).toHaveAttribute("data-width", "wide");
  expect(await within(drawer).findAllByText("执行中")).toHaveLength(2);
  expect(within(drawer).getByText("研究阶段 → 模型请求 × 1 → 可查看响应 × 1 → 阶段检查点")).toBeInTheDocument();
  await user.click(within(drawer).getByRole("button", { name: /direction-focus-selection-response/ }));

  expect(await within(drawer).findByText("调用模型：qwen-test")).toBeInTheDocument();
  expect(within(drawer).getByText(/真实模型输出/)).toBeInTheDocument();
  expect(apiClient.getArtifactText).toHaveBeenCalledWith(responseArtifact.url);
  expect(within(drawer).getByRole("link", { name: /PDF 研究计划/ })).toHaveAttribute(
    "href",
    artifactFixtures()[2]!.url,
  );
  expect(within(drawer).queryByText(attemptArtifact.relative_path)).not.toBeInTheDocument();
});

test("promotes final Markdown and PDF plans to visible delivery links", async () => {
  const pdf = artifactFixtures()[2]!;
  const markdown = {
    ...pdf,
    relative_path: "plan/research-plan.md",
    media_type: "text/markdown",
    url: "/api/runs/run-fixture123/artifacts/plan/research-plan.md",
  };
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ artifacts: [markdown, pdf] }));
  renderAppAt("/projects?run=run-fixture123");

  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  expect(await within(drawer).findByRole("link", { name: /Markdown 研究计划/ })).toHaveAttribute(
    "href",
    markdown.url,
  );
  expect(within(drawer).getByRole("link", { name: /PDF 研究计划/ })).toHaveAttribute(
    "href",
    pdf.url,
  );
  expect(within(drawer).queryByText("研究计划（2）")).not.toBeInTheDocument();
});

test("shows the first pending stage as active while an older API process is still running", async () => {
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({
    status: "running",
    stages: stageFixtures(3),
  }));
  renderAppAt("/projects?run=run-fixture123");

  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  const fourthStage = await within(drawer).findByRole("listitem", { name: "阶段 4 planning-literature-lock" });
  const fifthStage = await within(drawer).findByRole("listitem", { name: "阶段 5 skill-routing" });
  expect(within(fourthStage).getByText("执行中")).toBeInTheDocument();
  expect(fifthStage).toHaveTextContent("待执行");
});

test.each([
  ["queued", true, false, false],
  ["running", true, false, false],
  ["cancel_requested", false, false, false],
  ["failed", false, true, false],
  ["interrupted", false, true, false],
  ["canceled", false, true, false],
  ["dry_run", false, false, false],
  ["completed", false, true, true],
] as const)("shows only backend-appropriate actions for %s", async (status, canCancel, canResume, canEvolve) => {
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status }));
  renderAppAt("/projects?run=run-fixture123");
  const drawer = await screen.findByRole("dialog", { name: "运行详情" });
  await within(drawer).findByText("测试研究");

  expect(Boolean(within(drawer).queryByRole("button", { name: "请求取消" }))).toBe(canCancel);
  expect(Boolean(within(drawer).queryByRole("button", { name: "恢复运行" }))).toBe(canResume);
  expect(Boolean(within(drawer).queryByRole("button", { name: "发起进化" }))).toBe(canEvolve);
});

test("requires danger confirmation, blocks duplicate cancel, and invalidates only after success", async () => {
  const user = userEvent.setup();
  const request = deferred<RunRecord>();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "running" }));
  vi.mocked(apiClient.cancelRun).mockReturnValue(request.promise);
  const { queryClient } = renderAppAt("/projects?run=run-fixture123");
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await screen.findByText("测试研究");
  await user.click(screen.getByRole("button", { name: "请求取消" }));
  expect(apiClient.cancelRun).not.toHaveBeenCalled();
  const confirm = screen.getByRole("dialog", { name: "取消运行" });
  fireEvent.click(within(confirm).getByRole("button", { name: "确认取消" }));
  fireEvent.click(within(confirm).getByRole("button", { name: "处理中…" }));

  await waitFor(() => expect(apiClient.cancelRun).toHaveBeenCalledTimes(1));
  expect(within(confirm).getByRole("button", { name: "处理中…" })).toBeDisabled();
  expect(invalidate).not.toHaveBeenCalled();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "取消运行" })).toBeInTheDocument();

  await act(async () => request.resolve(runFixture({ status: "cancel_requested" })));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "取消运行" })).not.toBeInTheDocument());
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", "run-fixture123"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run-stages", "run-fixture123"] });
  expect(screen.getByRole("status")).toHaveTextContent("取消请求已提交");
});

test("keeps rejected cancellation open and never announces success", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "running" }));
  vi.mocked(apiClient.cancelRun).mockRejectedValue(new Error("当前阶段拒绝取消"));
  renderAppAt("/projects?run=run-fixture123");

  await screen.findByText("测试研究");
  await user.click(screen.getByRole("button", { name: "请求取消" }));
  await user.click(screen.getByRole("button", { name: "确认取消" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("当前阶段拒绝取消");
  expect(screen.getByRole("dialog", { name: "取消运行" })).toBeInTheDocument();
  expect(screen.getByRole("status")).not.toHaveTextContent("取消请求已提交");
});

test("renders resume errors inline and invalidates run data only after retry succeeds", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "failed" }));
  vi.mocked(apiClient.resumeRun)
    .mockRejectedValueOnce(new Error("没有可恢复检查点"))
    .mockResolvedValueOnce(runFixture({ status: "queued" }));
  const { queryClient } = renderAppAt("/projects?run=run-fixture123");
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "恢复运行" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("没有可恢复检查点");
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).not.toHaveTextContent("研究运行已恢复");

  await user.click(screen.getByRole("button", { name: "恢复运行" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"] }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", "run-fixture123"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run-stages", "run-fixture123"] });
  expect(screen.getByRole("status")).toHaveTextContent("研究运行已恢复");
});

test("shows a resume rejection from the current run under React StrictMode", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "failed" }));
  vi.mocked(apiClient.resumeRun).mockRejectedValue(new Error("StrictMode 恢复被服务端拒绝"));
  renderAppAt("/projects?run=run-fixture123", { strict: true });

  await user.click(await screen.findByRole("button", { name: "恢复运行" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("StrictMode 恢复被服务端拒绝");
});

test("announces a successful resume from the current run under React StrictMode", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "failed" }));
  vi.mocked(apiClient.resumeRun).mockResolvedValue(runFixture({ status: "queued" }));
  renderAppAt("/projects?run=run-fixture123", { strict: true });

  await user.click(await screen.findByRole("button", { name: "恢复运行" }));

  expect(await screen.findByRole("status")).toHaveTextContent("研究运行已恢复");
});

test("limits evolution to completed runs, states the no-promotion boundary, and recovers from an error", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "completed" }));
  vi.mocked(apiClient.startEvolution)
    .mockRejectedValueOnce(new Error("进化服务未配置"))
    .mockResolvedValueOnce(evolutionReceipt);
  const { queryClient } = renderAppAt("/projects?run=run-fixture123");
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  const evolve = await screen.findByRole("button", { name: "发起进化" });
  expect(screen.getByText("仅生成候选并验证，不授权 Skill 晋级")).toBeInTheDocument();
  await user.click(evolve);
  expect(await screen.findByRole("alert")).toHaveTextContent("进化服务未配置");
  expect(invalidate).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "发起进化" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["evolution", "run-fixture123"] }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skills"] });
  expect(screen.getByRole("status")).toHaveTextContent("进化候选任务已发起");
  expect(screen.getByRole("status")).not.toHaveTextContent("晋级成功");
});

test("announces a successful evolution from the current run under React StrictMode", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "completed" }));
  vi.mocked(apiClient.startEvolution).mockResolvedValue(evolutionReceipt);
  renderAppAt("/projects?run=run-fixture123", { strict: true });

  await user.click(await screen.findByRole("button", { name: "发起进化" }));

  expect(await screen.findByRole("status")).toHaveTextContent("进化候选任务已发起");
});

test("danger confirmation owns Escape, then the detail drawer closes and preserves other parameters", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockResolvedValue(runFixture({ status: "running" }));
  const { router } = renderAppAt("/projects?status=running&run=run-fixture123");

  await user.click(await screen.findByRole("button", { name: "请求取消" }));
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "取消运行" })).toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "运行详情" })).toBeInTheDocument();

  await user.click(within(screen.getByRole("dialog", { name: "取消运行" })).getByRole("button", { name: "取消" }));
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "运行详情" })).not.toBeInTheDocument());
  expect(router.state.location.search).toBe("?status=running");
});

test("closes an old cancellation confirmation on run switch and only a new confirmation can cancel the new run", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.getRun).mockImplementation(async (id) => runFixture({
    run_id: id,
    direction: id === "run-old-cancel" ? "旧取消运行" : "新取消运行",
    status: "running",
  }));
  vi.mocked(apiClient.cancelRun).mockImplementation(async (id) => runFixture({ run_id: id, status: "cancel_requested" }));
  const { router } = renderAppAt("/projects?run=run-old-cancel");

  await user.click(await screen.findByRole("button", { name: "请求取消" }));
  expect(screen.getByRole("dialog", { name: "取消运行" })).toBeInTheDocument();
  await act(async () => { await router.navigate("/projects?run=run-new-cancel"); });

  expect(await screen.findByText("新取消运行")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "取消运行" })).not.toBeInTheDocument();
  expect(apiClient.cancelRun).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "请求取消" }));
  await user.click(screen.getByRole("button", { name: "确认取消" }));
  await waitFor(() => expect(apiClient.cancelRun).toHaveBeenCalledWith("run-new-cancel"));
  expect(apiClient.cancelRun).not.toHaveBeenCalledWith("run-old-cancel");
});

test("an old pending resume cannot block the new run and its rejection cannot leak", async () => {
  const user = userEvent.setup();
  const oldResume = deferred<RunRecord>();
  vi.mocked(apiClient.getRun).mockImplementation(async (id) => runFixture({
    run_id: id,
    direction: id === "run-old-resume" ? "旧恢复运行" : "新恢复运行",
    status: "failed",
  }));
  vi.mocked(apiClient.resumeRun).mockImplementation((id) => (
    id === "run-old-resume" ? oldResume.promise : Promise.resolve(runFixture({ run_id: id, status: "queued" }))
  ));
  const { router } = renderAppAt("/projects?run=run-old-resume");

  await user.click(await screen.findByRole("button", { name: "恢复运行" }));
  await waitFor(() => expect(apiClient.resumeRun).toHaveBeenCalledWith("run-old-resume"));
  await act(async () => { await router.navigate("/projects?run=run-new-resume"); });

  expect(await screen.findByText("新恢复运行")).toBeInTheDocument();
  const newResume = screen.getByRole("button", { name: "恢复运行" });
  expect(newResume).toBeEnabled();
  await act(async () => oldResume.reject(new Error("旧恢复失败不得泄漏")));
  expect(screen.queryByText("旧恢复失败不得泄漏")).not.toBeInTheDocument();

  await user.click(newResume);
  await waitFor(() => expect(apiClient.resumeRun).toHaveBeenCalledWith("run-new-resume"));
});

test("an old evolution rejection cannot leak or block evolution for the new completed run", async () => {
  const user = userEvent.setup();
  const oldEvolution = deferred<EvolutionReceipt>();
  vi.mocked(apiClient.getRun).mockImplementation(async (id) => runFixture({
    run_id: id,
    direction: id === "run-old-evolution" ? "旧进化运行" : "新进化运行",
    status: "completed",
  }));
  vi.mocked(apiClient.startEvolution).mockImplementation((id) => (
    id === "run-old-evolution"
      ? oldEvolution.promise
      : Promise.resolve({ ...evolutionReceipt, run_id: id })
  ));
  const { router } = renderAppAt("/projects?run=run-old-evolution");

  await user.click(await screen.findByRole("button", { name: "发起进化" }));
  await waitFor(() => expect(apiClient.startEvolution).toHaveBeenCalledWith("run-old-evolution"));
  await act(async () => { await router.navigate("/projects?run=run-new-evolution"); });

  expect(await screen.findByText("新进化运行")).toBeInTheDocument();
  const newEvolution = screen.getByRole("button", { name: "发起进化" });
  expect(newEvolution).toBeEnabled();
  await act(async () => oldEvolution.reject(new Error("旧进化失败不得泄漏")));
  expect(screen.queryByText("旧进化失败不得泄漏")).not.toBeInTheDocument();

  await user.click(newEvolution);
  await waitFor(() => expect(apiClient.startEvolution).toHaveBeenCalledWith("run-new-evolution"));
});
