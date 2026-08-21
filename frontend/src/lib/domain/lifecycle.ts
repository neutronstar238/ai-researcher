import type {
  EvolutionStatus,
  RunStatus,
  StageRecord,
} from "../api/types";

const PRODUCT_STAGE_GROUPS: ReadonlyArray<{
  key: string;
  label: string;
  backend: readonly string[];
}> = [
  { key: "topic", label: "选题", backend: ["broad-literature-query", "focus-selection"] },
  { key: "literature", label: "文献", backend: ["targeted-literature-query", "planning-literature-lock"] },
  { key: "hypothesis", label: "假设", backend: ["skill-routing", "hypothesis-brainstorm"] },
  { key: "experiment", label: "实验", backend: ["provisional-plan", "real-pilot"] },
  { key: "validation", label: "验证", backend: ["postpilot-objective-review"] },
  { key: "writing", label: "写作", backend: ["final-plan-revision", "render-plan"] },
  { key: "reflection", label: "复盘", backend: ["independent-scientific-review"] },
  { key: "evolution", label: "进化", backend: [] },
];

const ACTIVE_RUN_STATUSES = new Set<RunStatus>([
  "queued",
  "running",
  "cancel_requested",
]);

export type ProductStageState = "completed" | "active" | "pending" | "blocked";

export interface ProductStage {
  key: string;
  label: string;
  state: ProductStageState;
  completed: number;
  total: number;
}

export function toProductLifecycle(
  stages: StageRecord[],
  runStatus: RunStatus,
  evolution: EvolutionStatus | null,
): ProductStage[] {
  let incompleteBarrierAssigned = false;

  return PRODUCT_STAGE_GROUPS.map((group) => {
    if (group.key === "evolution") {
      const completed = evolution?.run_evolution_receipt ? 1 : 0;

      // Mutation-pending state is intentionally not inferred: it is not an input to this function.
      return {
        key: group.key,
        label: group.label,
        state: completed ? "completed" : "pending",
        completed,
        total: 1,
      };
    }

    const members = group.backend
      .map((stageName) => stages.find((stage) => stage.stage_name === stageName))
      .filter((stage): stage is StageRecord => stage !== undefined);
    const completed = members.filter((stage) => stage.status === "completed").length;
    const blocked = members.some((stage) => stage.status === "invalid");
    const isComplete = members.length === group.backend.length && completed === group.backend.length;
    let state: ProductStageState = blocked ? "blocked" : isComplete ? "completed" : "pending";

    if (!incompleteBarrierAssigned && state !== "completed") {
      incompleteBarrierAssigned = true;
      if (state === "pending" && ACTIVE_RUN_STATUSES.has(runStatus)) {
        state = "active";
      }
    }

    return { key: group.key, label: group.label, state, completed, total: group.backend.length };
  });
}
