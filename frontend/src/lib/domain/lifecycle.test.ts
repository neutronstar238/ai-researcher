import type { EvolutionStatus, StageRecord } from "../api/types";
import { stageFixtures } from "../../test/fixtures";
import { toProductLifecycle } from "./lifecycle";

test("maps the twelve backend stages into eight ordered Chinese product stages", () => {
  const result = toProductLifecycle(stageFixtures(4), "running", null);

  expect(result).toEqual([
    { key: "topic", label: "选题", state: "completed", completed: 2, total: 2 },
    { key: "literature", label: "文献", state: "completed", completed: 2, total: 2 },
    { key: "hypothesis", label: "假设", state: "active", completed: 0, total: 2 },
    { key: "experiment", label: "实验", state: "pending", completed: 0, total: 2 },
    { key: "validation", label: "验证", state: "pending", completed: 0, total: 1 },
    { key: "writing", label: "写作", state: "pending", completed: 0, total: 2 },
    { key: "reflection", label: "复盘", state: "pending", completed: 0, total: 1 },
    { key: "evolution", label: "进化", state: "pending", completed: 0, total: 1 },
  ]);
});

test.each([
  ["broad-literature-query", "topic"],
  ["focus-selection", "topic"],
  ["targeted-literature-query", "literature"],
  ["planning-literature-lock", "literature"],
  ["skill-routing", "hypothesis"],
  ["hypothesis-brainstorm", "hypothesis"],
  ["provisional-plan", "experiment"],
  ["real-pilot", "experiment"],
  ["postpilot-objective-review", "validation"],
  ["final-plan-revision", "writing"],
  ["render-plan", "writing"],
  ["independent-scientific-review", "reflection"],
])("assigns %s to the %s product stage", (stageName, productStage) => {
  const stages: StageRecord[] = stageFixtures().map((stage) => ({
    ...stage,
    status: stage.stage_name === stageName ? "completed" : "pending",
  }));

  const result = toProductLifecycle(stages, "failed", null);

  expect(result.find((stage) => stage.key === productStage)?.completed).toBe(1);
  expect(result.filter((stage) => stage.key !== productStage).every((stage) => stage.completed === 0)).toBe(true);
});

test("blocks a product stage when one of its checkpoints is invalid", () => {
  const invalidStage: StageRecord = {
    ...stageFixtures(1)[0]!,
    status: "invalid",
  };

  expect(toProductLifecycle([invalidStage], "failed", null)[0]?.state).toBe("blocked");
});

test("keeps later pending groups pending after an earlier group is blocked", () => {
  const stages = stageFixtures().map((stage) => ({
    ...stage,
    status: stage.stage_name === "broad-literature-query" ? "invalid" : "pending",
  })) as StageRecord[];

  const result = toProductLifecycle(stages, "running", null);

  expect(result[0]?.state).toBe("blocked");
  expect(result.slice(1).every((stage) => stage.state === "pending")).toBe(true);
});

test("does not mark a completed group active when a later group is unfinished", () => {
  const result = toProductLifecycle(stageFixtures(2), "queued", null);

  expect(result[0]?.state).toBe("completed");
  expect(result[1]?.state).toBe("active");
});

test("treats an empty stage response as an incomplete first product stage", () => {
  const result = toProductLifecycle([], "running", null);

  expect(result[0]).toEqual({
    key: "topic",
    label: "选题",
    state: "active",
    completed: 0,
    total: 2,
  });
  expect(result.slice(1).every((stage) => stage.state === "pending")).toBe(true);
});

test("keeps missing members incomplete and activates only the earliest incomplete group", () => {
  const firstTopicStage = stageFixtures(1)[0]!;
  const result = toProductLifecycle([firstTopicStage], "running", null);

  expect(result[0]).toEqual({
    key: "topic",
    label: "选题",
    state: "active",
    completed: 1,
    total: 2,
  });
  expect(result.slice(1).every((stage) => stage.state === "pending")).toBe(true);
});

test("keeps evolution pending without a receipt because mutation-pending state is not an input", () => {
  const result = toProductLifecycle(stageFixtures(12), "running", null);

  expect(result[7]).toEqual({
    key: "evolution",
    label: "进化",
    state: "pending",
    completed: 0,
    total: 1,
  });
});

test("completes evolution only when the service supplies a receipt", () => {
  const evolution: EvolutionStatus = {
    run_id: "run-fixture123",
    execution_enabled: true,
    mode: "frozen_service_available",
    selected_skills: {
      run_id: "run-fixture123",
      source_artifact: null,
      selection: {},
      skill_content_is_scientific_evidence: false,
    },
    skill_candidates: [],
    run_evolution_receipt: { status: "completed" },
    promotion_authorized: false,
    boundary: "human approval required",
  };

  expect(toProductLifecycle(stageFixtures(12), "completed", evolution)[7]).toEqual({
    key: "evolution",
    label: "进化",
    state: "completed",
    completed: 1,
    total: 1,
  });
});
