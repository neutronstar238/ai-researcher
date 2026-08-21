import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient, ApiError } from "../../lib/api/client";
import type { EvolutionReceipt, EvolutionStatus, RunRecord, SkillCandidate } from "../../lib/api/types";
import { runFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/client")>();
  return {
    ...actual,
    apiClient: {
      evolution: vi.fn(),
      listRuns: vi.fn(),
      skillCandidates: vi.fn(),
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

const candidate: SkillCandidate = {
  candidate_skill_id: "candidate-one",
  parent_skill: null,
  candidate_status: "shadow_evaluation",
  relative_path: "exploration/skills/candidates/candidate-one.md",
  promotion_authorized: false,
  promotion_boundary: "shadow evidence only",
};

function evolutionFixture(overrides: Partial<EvolutionStatus> = {}): EvolutionStatus {
  return {
    run_id: "run-completed",
    execution_enabled: false,
    mode: "query_only",
    selected_skills: {
      run_id: "run-completed",
      source_artifact: null,
      selection: null,
      skill_content_is_scientific_evidence: false,
    },
    skill_candidates: [candidate],
    run_evolution_receipt: null,
    promotion_authorized: false,
    boundary: "This endpoint only exposes persisted state.",
    ...overrides,
  };
}

function completedSummary(overrides: Partial<RunRecord> = {}): RunRecord {
  return runFixture({ run_id: "run-completed", artifacts: undefined, stages: undefined, ...overrides });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.listRuns).mockResolvedValue([]);
  vi.mocked(apiClient.skillCandidates).mockResolvedValue([]);
  vi.mocked(apiClient.evolution).mockResolvedValue(evolutionFixture());
});

test("renders real candidates and the mandatory no-promotion boundary without activation actions", async () => {
  vi.mocked(apiClient.skillCandidates).mockResolvedValue([
    { ...candidate, candidate_skill_id: "candidate-two", parent_skill: "parent-skill", relative_path: "exploration/skills/candidates/candidate-two.md" },
    candidate,
  ]);
  renderAppAt("/agents");

  const list = await screen.findByRole("list", { name: "Skill 候选" });
  expect(within(list).getAllByText("shadow_evaluation")).toHaveLength(2);
  const items = within(list).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("父 Skill：parent-skill");
  expect(items[1]).toHaveTextContent("父 Skill：无");
  expect(within(list).getByText(candidate.relative_path)).toBeInTheDocument();
  expect(screen.getByText("promotion_authorized: false")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /晋级|激活|promote/i })).not.toBeInTheDocument();
});

test("shows candidate errors with retry", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.skillCandidates)
    .mockRejectedValueOnce(new Error("候选接口失败"))
    .mockResolvedValueOnce([candidate]);
  renderAppAt("/agents");

  expect(await screen.findByRole("alert")).toHaveTextContent("候选接口失败");
  await user.click(screen.getByRole("button", { name: "重试候选列表" }));
  expect(await screen.findByText(candidate.relative_path)).toBeInTheDocument();
});

test("loads evolution only for selectable completed runs and shows persisted public truth", async () => {
  vi.mocked(apiClient.listRuns).mockResolvedValue([
    completedSummary({ direction: "完成运行" }),
    completedSummary({ run_id: "run-failed", direction: "失败运行", status: "failed" }),
  ]);
  vi.mocked(apiClient.evolution).mockResolvedValue(evolutionFixture({
    selected_skills: {
      run_id: "run-completed",
      source_artifact: "skill-routing.json",
      selection: { skill: "candidate-one" },
      skill_content_is_scientific_evidence: false,
    },
    run_evolution_receipt: { status: "shadow_validated" },
  }));

  renderAppAt("/agents");

  const select = await screen.findByRole("combobox", { name: "已完成运行" });
  expect(within(select).getAllByRole("option")).toHaveLength(1);
  expect(await screen.findByText("query_only")).toBeInTheDocument();
  expect(screen.getByText("否")).toBeInTheDocument();
  expect(screen.getByText("skill-routing.json")).toBeInTheDocument();
  expect(screen.getByText("已持久化")).toBeInTheDocument();
  expect(screen.getByText("This endpoint only exposes persisted state.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "发起进化" })).not.toBeInTheDocument();
});

test("starts enabled evolution once, then invalidates only exact evolution and skills", async () => {
  const user = userEvent.setup();
  const run = completedSummary({ direction: "可进化运行" });
  const pending = deferred<EvolutionReceipt>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.evolution).mockResolvedValue(evolutionFixture({ execution_enabled: true, mode: "frozen_service_available" }));
  vi.mocked(apiClient.startEvolution).mockReturnValue(pending.promise);
  const { queryClient } = renderAppAt("/agents", { strict: true });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

  const button = await screen.findByRole("button", { name: "发起进化" });
  await user.dblClick(button);
  expect(apiClient.startEvolution).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({
    schema_version: "autoresearch-api-skill-evolution-receipt-v1",
    run_id: run.run_id,
    status: "shadow_validated",
    result: {},
    promotion_authorized: false,
    created_at: "2026-08-20T08:00:00Z",
  }));

  expect(await screen.findByText("进化候选任务已发起")).toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["evolution", run.run_id], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skills"], exact: true });
  expect(document.body).not.toHaveTextContent("已晋级");
});

test("shows the exact service error for enabled evolution", async () => {
  const user = userEvent.setup();
  const run = completedSummary({ direction: "进化失败运行" });
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.evolution).mockResolvedValue(evolutionFixture({ execution_enabled: true }));
  vi.mocked(apiClient.startEvolution).mockRejectedValue(new ApiError(409, "已有进化回执不可读", "service_error"));
  renderAppAt("/agents");

  await user.click(await screen.findByRole("button", { name: "发起进化" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("已有进化回执不可读");
});

test("does not leak a slower prior evolution response into the newly selected run", async () => {
  const user = userEvent.setup();
  const oldRun = completedSummary({ run_id: "run-old", direction: "旧运行", created_at: "2026-08-20T02:00:00Z" });
  const newRun = completedSummary({ run_id: "run-new", direction: "新运行", created_at: "2026-08-19T02:00:00Z" });
  const oldEvolution = deferred<EvolutionStatus>();
  const newEvolution = deferred<EvolutionStatus>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([oldRun, newRun]);
  vi.mocked(apiClient.evolution).mockImplementation((id) => id === oldRun.run_id ? oldEvolution.promise : newEvolution.promise);
  renderAppAt("/agents");

  const select = await screen.findByRole("combobox", { name: "已完成运行" });
  await user.selectOptions(select, newRun.run_id);
  await act(async () => newEvolution.resolve(evolutionFixture({ run_id: newRun.run_id, boundary: "new-boundary" })));
  expect(await screen.findByText("new-boundary")).toBeInTheDocument();
  await act(async () => oldEvolution.resolve(evolutionFixture({ run_id: oldRun.run_id, boundary: "old-boundary" })));
  await waitFor(() => expect(screen.queryByText("old-boundary")).not.toBeInTheDocument());
});

test("successful action after selecting another run invalidates server caches and refetches when switching back without a stale toast", async () => {
  const user = userEvent.setup();
  const oldRun = completedSummary({ run_id: "run-action-old", direction: "旧动作运行", created_at: "2026-08-20T02:00:00Z" });
  const newRun = completedSummary({ run_id: "run-action-new", direction: "新动作运行", created_at: "2026-08-19T02:00:00Z" });
  const pending = deferred<EvolutionReceipt>();
  let oldEvolutionReads = 0;
  vi.mocked(apiClient.listRuns).mockResolvedValue([oldRun, newRun]);
  vi.mocked(apiClient.skillCandidates)
    .mockResolvedValueOnce([candidate])
    .mockResolvedValueOnce([{ ...candidate, candidate_skill_id: "candidate-refetched" }]);
  vi.mocked(apiClient.evolution).mockImplementation(async (id) => {
    if (id === oldRun.run_id) oldEvolutionReads += 1;
    return evolutionFixture({
      run_id: id,
      execution_enabled: true,
      mode: "frozen_service_available",
      boundary: id === oldRun.run_id && oldEvolutionReads > 1 ? "old-boundary-refetched" : `${id}-boundary-before`,
    });
  });
  vi.mocked(apiClient.startEvolution).mockReturnValue(pending.promise);
  const { queryClient } = renderAppAt("/agents", { strict: true });
  queryClient.setQueryDefaults(["skills"], { staleTime: Infinity });
  queryClient.setQueryDefaults(["evolution"], { staleTime: Infinity });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "发起进化" }));
  await user.selectOptions(screen.getByRole("combobox", { name: "已完成运行" }), newRun.run_id);
  expect(await screen.findByRole("button", { name: "发起中…" })).toBeDisabled();

  await act(async () => pending.resolve({
    schema_version: "autoresearch-api-skill-evolution-receipt-v1",
    run_id: oldRun.run_id,
    status: "shadow_validated",
    result: {},
    promotion_authorized: false,
    created_at: "2026-08-20T08:00:00Z",
  }));
  expect(await screen.findByRole("button", { name: "发起进化" })).toBeEnabled();
  expect(await screen.findByText("candidate-refetched")).toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["evolution", oldRun.run_id], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skills"], exact: true });
  expect(screen.queryByText("进化候选任务已发起")).not.toBeInTheDocument();

  await user.selectOptions(screen.getByRole("combobox", { name: "已完成运行" }), oldRun.run_id);
  expect(await screen.findByText("old-boundary-refetched")).toBeInTheDocument();
  expect(oldEvolutionReads).toBe(2);
});

test("successful evolution after unmount invalidates exact server caches without local settlement", async () => {
  const user = userEvent.setup();
  const run = completedSummary({ run_id: "run-unmounted-action", direction: "卸载动作运行" });
  const pending = deferred<EvolutionReceipt>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([run]);
  vi.mocked(apiClient.evolution).mockResolvedValue(evolutionFixture({ run_id: run.run_id, execution_enabled: true }));
  vi.mocked(apiClient.startEvolution).mockReturnValue(pending.promise);
  const rendered = renderAppAt("/agents", { strict: true });
  rendered.queryClient.setQueryData(["evolution", run.run_id], evolutionFixture({ run_id: run.run_id }));
  rendered.queryClient.setQueryData(["skills"], [candidate]);
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "发起进化" }));
  rendered.unmount();
  await act(async () => pending.resolve({
    schema_version: "autoresearch-api-skill-evolution-receipt-v1",
    run_id: run.run_id,
    status: "shadow_validated",
    result: {},
    promotion_authorized: false,
    created_at: "2026-08-20T08:00:00Z",
  }));

  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["evolution", run.run_id], exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skills"], exact: true });
  expect(rendered.queryClient.getQueryState(["evolution", run.run_id])?.isInvalidated).toBe(true);
  expect(rendered.queryClient.getQueryState(["skills"])?.isInvalidated).toBe(true);
  expect(screen.queryByText("进化候选任务已发起")).not.toBeInTheDocument();
});

test("rejected evolution after selection change neither invalidates nor leaks the old error", async () => {
  const user = userEvent.setup();
  const oldRun = completedSummary({ run_id: "run-reject-old", direction: "旧失败动作", created_at: "2026-08-20T02:00:00Z" });
  const newRun = completedSummary({ run_id: "run-reject-new", direction: "新运行", created_at: "2026-08-19T02:00:00Z" });
  const pending = deferred<EvolutionReceipt>();
  vi.mocked(apiClient.listRuns).mockResolvedValue([oldRun, newRun]);
  vi.mocked(apiClient.evolution).mockImplementation(async (id) => evolutionFixture({ run_id: id, execution_enabled: true }));
  vi.mocked(apiClient.startEvolution).mockReturnValue(pending.promise);
  const { queryClient } = renderAppAt("/agents", { strict: true });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "发起进化" }));
  await user.selectOptions(screen.getByRole("combobox", { name: "已完成运行" }), newRun.run_id);
  await act(async () => pending.reject(new Error("旧运行进化失败")));

  expect(await screen.findByRole("button", { name: "发起进化" })).toBeEnabled();
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.queryByText("旧运行进化失败")).not.toBeInTheDocument();
});
