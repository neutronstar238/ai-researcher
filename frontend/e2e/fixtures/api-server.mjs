// Browser-test fixture only; never imported by production code.
import { createServer } from "node:http";

const HOST = "127.0.0.1";
const PORT = 4174;
const STAGE_NAMES = [
  ["broad-literature-query", "广域文献检索"],
  ["focus-selection", "研究焦点选择"],
  ["targeted-literature-query", "定向文献检索"],
  ["planning-literature-lock", "规划文献锁定"],
  ["skill-routing", "Skill 路由"],
  ["hypothesis-brainstorm", "假设生成"],
  ["provisional-plan", "预备计划"],
  ["real-pilot", "真实预实验"],
  ["postpilot-objective-review", "预实验后复核"],
  ["final-plan-revision", "最终计划修订"],
  ["render-plan", "计划渲染"],
  ["independent-scientific-review", "独立科学审查"],
];

function makeStages(completed, invalidOrdinal = null) {
  return STAGE_NAMES.map(([stageName, label], index) => {
    const ordinal = index + 1;
    const isCompleted = ordinal <= completed;
    return {
      ordinal,
      stage_name: stageName,
      label_zh: label,
      status: ordinal === invalidOrdinal ? "invalid" : isCompleted ? "completed" : "pending",
      artifact_count: isCompleted ? ordinal : 0,
      checkpoint_hash: isCompleted ? ordinal.toString(16).repeat(64) : null,
    };
  });
}

function makeArtifacts(runId) {
  return [
    {
      relative_path: "literature/survey v1.json",
      category: "literature",
      bytes: 2048,
      sha256: "a".repeat(64),
      media_type: "application/json",
      url: `/api/runs/${runId}/artifacts/literature/survey%20v1.json?download=1&signature=fixed%2Btoken`,
    },
    {
      relative_path: "real-pilot/metrics.json",
      category: "metrics",
      bytes: 3072,
      sha256: "b".repeat(64),
      media_type: "application/json",
      url: `/api/runs/${runId}/artifacts/real-pilot/metrics.json?download=1`,
    },
    {
      relative_path: "data/observations.csv",
      category: "data",
      bytes: 4096,
      sha256: "c".repeat(64),
      media_type: "text/csv",
      url: `/api/runs/${runId}/artifacts/data/observations.csv?download=1`,
    },
    {
      relative_path: "plan/research-plan.pdf",
      category: "plan",
      bytes: 8192,
      sha256: "d".repeat(64),
      media_type: "application/pdf",
      url: `/api/runs/${runId}/artifacts/plan/research-plan.pdf?download=1`,
    },
  ];
}

function makeRun({ runId, direction, status, completed, createdAt, error = null }) {
  const terminal = ["completed", "failed", "canceled"].includes(status);
  return {
    schema_version: "autoresearch-api-run-v1",
    run_id: runId,
    kind: "single",
    direction,
    status,
    dry_run: false,
    preexperiment_policy: "required",
    dreaming_recall_enabled: false,
    output_dir: `runs/e2e/${runId}`,
    created_at: createdAt,
    started_at: status === "queued" ? null : createdAt.replace(":00:00Z", ":01:00Z"),
    finished_at: terminal ? createdAt.replace(":00:00Z", ":20:00Z") : null,
    resume_count: 0,
    cancel_requested: false,
    error,
    result: status === "completed" ? { status: "completed", evidence_count: 12 } : null,
    delivery_validation: status === "completed" ? { status: "passed", checks: 8 } : null,
    execution_boundary: {
      formal_experiment_enabled: false,
      result_paper_enabled: false,
      self_evolution_execution_enabled: false,
      api_owns_scientific_logic: false,
    },
    stages: makeStages(completed, status === "failed" ? completed + 1 : null),
    artifacts: makeArtifacts(runId),
  };
}

const runs = [
  makeRun({
    runId: "run-e2e-running",
    direction: "正在执行的测试研究",
    status: "running",
    completed: 5,
    createdAt: "2026-08-20T07:00:00Z",
  }),
  makeRun({
    runId: "run-e2e-completed",
    direction: "已完成的测试研究",
    status: "completed",
    completed: 12,
    createdAt: "2026-08-20T06:00:00Z",
  }),
  makeRun({
    runId: "run-e2e-failed",
    direction: "失败的测试研究",
    status: "failed",
    completed: 3,
    createdAt: "2026-08-20T05:00:00Z",
    error: { type: "ResearchApiError", message: "测试科学门阻断" },
  }),
];

const batches = [{
  schema_version: "autoresearch-api-batch-preview-v1",
  batch_id: "batch-e2e-seeded",
  status: "dry_run",
  dry_run: true,
  question_count: 2,
  created_at: "2026-08-20T04:00:00Z",
  items: [],
  batch_service_configured: false,
  question_pdf: "seeded-questions.pdf",
  start: 1,
  limit: 2,
  include_question_ids: [1, 2],
  provider_calls: 0,
}];

const EVOLUTION_SERVICE_CONFIGURED = true;

const health = {
  status: "ok",
  service: "autoresearch-local-api",
  deployment_scope: "local_single_user",
  authentication_enabled: false,
  formal_experiment_enabled: false,
  result_paper_enabled: false,
  self_evolution_execution_enabled: EVOLUTION_SERVICE_CONFIGURED,
  self_evolution_service_configured: EVOLUTION_SERVICE_CONFIGURED,
  automatic_skill_activation_enabled: false,
  batch_execution_configured: true,
};

const skillCandidates = [{
  candidate_skill_id: "candidate-e2e-001",
  parent_skill: "literature-review",
  candidate_status: "shadow_validated",
  relative_path: "exploration/skills/candidates/candidate-e2e-001.md",
  promotion_authorized: false,
  promotion_boundary: "human approval required",
}];

let runCounter = 1;
let batchCounter = 1;
const evolutionReceipts = new Map();

function clone(value) {
  return structuredClone(value);
}

function publicRun(run) {
  const { stages: _stages, artifacts: _artifacts, ...summary } = run;
  return clone(summary);
}

function runDetail(run) {
  return {
    ...publicRun(run),
    stages: clone(run.stages),
    artifacts: clone(run.artifacts),
  };
}

function json(response, status, payload) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(payload));
}

function error(response, status, code, message) {
  return json(response, status, { error: code, message });
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return null;
  }
}

function findRun(encodedRunId) {
  let runId;
  try {
    runId = decodeURIComponent(encodedRunId);
  } catch {
    return null;
  }
  return runs.find((run) => run.run_id === runId) ?? null;
}

function evolutionStatus(run) {
  const receipt = evolutionReceipts.get(run.run_id) ?? null;
  return {
    run_id: run.run_id,
    execution_enabled: EVOLUTION_SERVICE_CONFIGURED,
    mode: EVOLUTION_SERVICE_CONFIGURED ? "frozen_service_available" : "query_only",
    selected_skills: {
      run_id: run.run_id,
      source_artifact: "skills/selected-skills.json",
      selection: { selected: ["literature-review"] },
      skill_content_is_scientific_evidence: false,
    },
    skill_candidates: clone(skillCandidates),
    run_evolution_receipt: receipt,
    promotion_authorized: false,
    boundary: "候选仅在 shadow 模式验证；晋级需要人工审批",
  };
}

function routeArtifactDownload(request, response, pathname) {
  const match = pathname.match(/^\/api\/runs\/([^/]+)\/artifacts\/(.+)$/);
  if (!match || request.method !== "GET") return false;
  const run = findRun(match[1]);
  if (!run) {
    error(response, 404, "not_found", "run not found");
    return true;
  }
  const requestedPath = decodeURIComponent(match[2]);
  const artifact = run.artifacts.find((item) => item.relative_path === requestedPath);
  if (!artifact) {
    error(response, 404, "not_found", "artifact not found");
    return true;
  }
  const body = Buffer.from(`deterministic artifact: ${artifact.relative_path}\n`, "utf8");
  response.writeHead(200, {
    "cache-control": "no-store",
    "content-disposition": `attachment; filename="${artifact.relative_path.split("/").at(-1)}"`,
    "content-length": String(body.length),
    "content-type": artifact.media_type,
  });
  response.end(body);
  return true;
}

async function routeRun(request, response, pathname) {
  const match = pathname.match(/^\/api\/runs\/([^/]+)(?:\/(stages|artifacts|skills|resume|cancel|evolution))?$/);
  if (!match) return false;
  const run = findRun(match[1]);
  if (!run) {
    error(response, 404, "not_found", "run not found");
    return true;
  }
  const action = match[2] ?? null;

  if (request.method === "GET" && action === null) {
    json(response, 200, runDetail(run));
    return true;
  }
  if (request.method === "GET" && action === "stages") {
    json(response, 200, { run_id: run.run_id, stages: clone(run.stages) });
    return true;
  }
  if (request.method === "GET" && action === "artifacts") {
    json(response, 200, { run_id: run.run_id, artifacts: clone(run.artifacts) });
    return true;
  }
  if (request.method === "GET" && action === "skills") {
    json(response, 200, {
      run_id: run.run_id,
      source_artifact: "skills/selected-skills.json",
      selection: { selected: ["literature-review"] },
      skill_content_is_scientific_evidence: false,
    });
    return true;
  }
  if (request.method === "GET" && action === "evolution") {
    json(response, 200, evolutionStatus(run));
    return true;
  }
  if (request.method === "POST" && action === "resume") {
    if (!["canceled", "completed", "failed", "interrupted"].includes(run.status)) {
      error(response, 409, "run_not_resumable", "run cannot resume from its current status");
      return true;
    }
    run.status = "queued";
    run.resume_count += 1;
    run.cancel_requested = false;
    run.error = null;
    run.finished_at = null;
    json(response, 202, publicRun(run));
    return true;
  }
  if (request.method === "POST" && action === "cancel") {
    if (!["queued", "running"].includes(run.status)) {
      error(response, 409, "run_not_cancelable", "run cannot be canceled from its current status");
      return true;
    }
    run.status = run.status === "queued" ? "canceled" : "cancel_requested";
    run.cancel_requested = true;
    if (run.status === "canceled") run.finished_at = "2026-08-20T08:45:00Z";
    run.cancellation_boundary = "stop after current safe checkpoint";
    json(response, 202, publicRun(run));
    return true;
  }
  if (request.method === "POST" && action === "evolution") {
    if (run.status !== "completed") {
      error(response, 409, "evolution_not_available", "evolution requires a completed run");
      return true;
    }
    const receipt = {
      schema_version: "autoresearch-api-skill-evolution-receipt-v1",
      run_id: run.run_id,
      status: "shadow_validated",
      result: {
        status: "shadow_validated",
        candidate_skill_ids: ["candidate-e2e-001"],
        promotion_authorized: false,
      },
      promotion_authorized: false,
      created_at: "2026-08-20T08:30:00Z",
    };
    evolutionReceipts.set(run.run_id, clone(receipt));
    json(response, 201, receipt);
    return true;
  }
  error(response, 405, "method_not_allowed", "method not allowed");
  return true;
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", `http://${HOST}:${PORT}`);
    const { pathname } = url;

    if (request.method === "GET" && pathname === "/api/health") {
      return json(response, 200, health);
    }
    if (request.method === "GET" && pathname === "/api/runs") {
      return json(response, 200, { runs: runs.map(publicRun) });
    }
    if (request.method === "POST" && pathname === "/api/runs") {
      const input = await readJson(request);
      if (input === null) return error(response, 400, "invalid_json", "request body must be valid JSON");
      if (typeof input.direction !== "string" || !input.direction.trim()) {
        return error(response, 422, "validation_error", "direction is required");
      }
      const runId = `run-e2e-created-${String(runCounter).padStart(3, "0")}`;
      runCounter += 1;
      const run = makeRun({
        runId,
        direction: input.direction.trim(),
        status: input.dry_run === true ? "dry_run" : "queued",
        completed: 0,
        createdAt: "2026-08-20T08:00:00Z",
      });
      run.dry_run = input.dry_run === true;
      run.preexperiment_policy = input.preexperiment_policy ?? "if_supported";
      run.dreaming_recall_enabled = input.dreaming_recall_enabled !== false;
      if (run.dry_run) run.finished_at = "2026-08-20T08:00:00Z";
      runs.unshift(run);
      return json(response, 201, publicRun(run));
    }
    if (request.method === "GET" && pathname === "/api/batches") {
      return json(response, 200, { batches: clone(batches) });
    }
    if (request.method === "POST" && pathname === "/api/batches") {
      const input = await readJson(request);
      if (input === null) return error(response, 400, "invalid_json", "request body must be valid JSON");
      if (input.question_pdf === "server-error.pdf") {
        return error(response, 500, "fixture_batch_error", "确定性批量服务错误");
      }
      if (typeof input.question_pdf !== "string" || !input.question_pdf.trim()) {
        return error(response, 422, "batch_validation_error", "question_pdf is required");
      }
      const batch = {
        schema_version: "autoresearch-api-batch-submission-v1",
        batch_id: `batch-e2e-created-${String(batchCounter).padStart(3, "0")}`,
        status: input.dry_run !== false ? "dry_run" : "completed",
        dry_run: input.dry_run !== false,
        question_count: Array.isArray(input.include_question_ids) && input.include_question_ids.length > 0
          ? input.include_question_ids.length
          : Number(input.limit ?? 125),
        created_at: "2026-08-20T08:15:00Z",
        batch_service_receipt: {
          schema_version: "science125-batch-report-v2",
          literature_protocol: "two_stage_literature_v5",
          status: input.dry_run !== false ? "dry_run" : "completed",
          question_count: Array.isArray(input.include_question_ids) && input.include_question_ids.length > 0
            ? input.include_question_ids.length
            : Number(input.limit ?? 125),
          provider_calls: input.dry_run !== false ? 0 : 1,
        },
      };
      batchCounter += 1;
      batches.unshift(batch);
      return json(response, 201, clone(batch));
    }
    const batchMatch = pathname.match(/^\/api\/batches\/([^/]+)$/);
    if (request.method === "GET" && batchMatch) {
      const batchId = decodeURIComponent(batchMatch[1]);
      const batch = batches.find((item) => item.batch_id === batchId);
      return batch
        ? json(response, 200, clone(batch))
        : error(response, 404, "not_found", "batch not found");
    }
    if (request.method === "GET" && pathname === "/api/skills/candidates") {
      return json(response, 200, {
        candidates: clone(skillCandidates),
        promotion_authorized: false,
        mode: "query_only",
      });
    }
    if (routeArtifactDownload(request, response, pathname)) return;
    if (await routeRun(request, response, pathname)) return;
    return error(response, 404, "not_found", "fixture endpoint not found");
  } catch (requestError) {
    return error(response, 500, "fixture_error", requestError instanceof Error ? requestError.message : "fixture error");
  }
});

server.listen(PORT, HOST);

function closeServer() {
  server.close(() => process.exit(0));
}

process.once("SIGINT", closeServer);
process.once("SIGTERM", closeServer);
