/* AI-Researcher · 科研计划台 — frontend logic (vanilla JS, no build step) */

"use strict";

const state = {
  selected: null,
  runs: [],
  batches: [],
  candidates: [],
  activeTab: "runs",
};

const $ = (id) => document.getElementById(id);

const STATUS_LABELS = {
  dry_run: "预览",
  queued: "排队中",
  running: "运行中",
  cancel_requested: "停止请求中",
  canceled: "已取消",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};

const STAGE_STATE_LABELS = { completed: "完成", pending: "待执行", invalid: "校验失败" };

const CATEGORY_LABELS = {
  plan: "研究计划",
  review: "评审",
  evidence: "证据",
  evolution: "Skill 进化",
  internal: "内部制品",
  runtime: "运行期",
  other: "其它",
};

/* ------------------------------------------------------------------ */
/* utilities                                                           */
/* ------------------------------------------------------------------ */

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]
  ));
}

function formatBytes(value) {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function shortId(id) {
  return String(id || "").length > 22 ? String(id).slice(0, 22) + "…" : String(id || "");
}

function relativeTime(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const delta = Date.now() - then;
  const abs = Math.abs(delta);
  const fmt = (n, unit) => `${Math.floor(n)} ${unit}`;
  if (abs < 60_000) return "刚刚";
  if (abs < 3_600_000) return delta >= 0 ? fmt(abs / 60_000, "分钟前") : fmt(abs / 60_000, "分钟后");
  if (abs < 86_400_000) return delta >= 0 ? fmt(abs / 3_600_000, "小时前") : fmt(abs / 3_600_000, "小时后");
  return delta >= 0 ? fmt(abs / 86_400_000, "天前") : fmt(abs / 86_400_000, "天后");
}

function statusDot(status, { pulse = false } = {}) {
  const cls = pulse ? '<span class="pulse"></span>' : "";
  return cls;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

let toastTimer = null;
function toast(message, error = false) {
  const node = $("toast");
  node.textContent = message;
  node.className = error ? "show error" : "show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.className = ""; }, 3400);
}

/* ------------------------------------------------------------------ */
/* theme                                                               */
/* ------------------------------------------------------------------ */

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("ar-theme", theme); } catch (_) { /* ignore */ }
}

function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem("ar-theme"); } catch (_) { /* ignore */ }
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = stored || (prefersDark ? "dark" : "light");
  applyTheme(theme);
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });
}

/* ------------------------------------------------------------------ */
/* health                                                              */
/* ------------------------------------------------------------------ */

async function refreshHealth() {
  const pill = $("health");
  try {
    const health = await api("/api/health");
    if (health.status === "ok") {
      pill.dataset.state = "ok";
      pill.innerHTML = '<i class="dot"></i><span>本地服务正常</span>';
    } else {
      pill.dataset.state = "failed";
      pill.innerHTML = '<i class="dot"></i><span>服务异常</span>';
    }
  } catch (_) {
    pill.dataset.state = "failed";
    pill.innerHTML = '<i class="dot"></i><span>连接失败</span>';
  }
}

/* ------------------------------------------------------------------ */
/* sidebar lists                                                       */
/* ------------------------------------------------------------------ */

async function refreshRuns() {
  const payload = await api("/api/runs");
  state.runs = payload.runs || [];
  $("run-count").textContent = state.runs.length;
  renderRuns();
}

function renderRuns() {
  const root = $("runs");
  if (!state.runs.length) {
    root.innerHTML = '<p class="empty">尚无运行</p>';
    return;
  }
  root.innerHTML = state.runs.map((run) => {
    const active = ["queued", "running", "cancel_requested"].includes(run.status);
    return `
      <button class="item ${state.selected === run.run_id ? "selected" : ""}" data-run-id="${escapeHtml(run.run_id)}">
        <div class="item-top">
          <span class="badge status-${escapeHtml(run.status)}">${statusDot(run.status, { pulse: active })}${escapeHtml(STATUS_LABELS[run.status] || run.status)}</span>
        </div>
        <div class="item-title">${escapeHtml(run.direction)}</div>
        <div class="item-meta"><span class="id">${escapeHtml(shortId(run.run_id))}</span><span>·</span><span>${escapeHtml(relativeTime(run.created_at))}</span></div>
      </button>`;
  }).join("");

  root.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.runId));
  });
}

async function refreshBatches() {
  const payload = await api("/api/batches");
  state.batches = payload.batches || [];
  $("batch-count").textContent = state.batches.length;
  renderBatches();
}

function renderBatches() {
  const root = $("batches");
  if (!state.batches.length) {
    root.innerHTML = '<p class="empty">尚无批量任务</p>';
    return;
  }
  root.innerHTML = state.batches.map((batch) => `
    <button class="item" data-batch-id="${escapeHtml(batch.batch_id)}">
      <div class="item-top">
        <span class="badge status-${escapeHtml(batch.status || "dry_run")}">${escapeHtml(STATUS_LABELS[batch.status] || batch.status || "预览")}</span>
        <span class="chip">${Number(batch.question_count || 0)} 题</span>
      </div>
      <div class="item-title">${escapeHtml(batch.question_pdf || batch.batch_id)}</div>
      <div class="item-meta"><span class="id">${escapeHtml(shortId(batch.batch_id))}</span></div>
    </button>`).join("");

  root.querySelectorAll("[data-batch-id]").forEach((button) => {
    button.addEventListener("click", () => toast(`批量任务：${button.dataset.batchId}`, false));
  });
}

async function refreshSkills() {
  const payload = await api("/api/skills/candidates");
  state.candidates = payload.candidates || [];
  $("skill-count").textContent = state.candidates.length;
  renderSkills();
}

function renderSkills() {
  const root = $("skills");
  if (!state.candidates.length) {
    root.innerHTML = '<p class="empty">尚无 Skill 候选</p>';
    return;
  }
  root.innerHTML = state.candidates.map((item) => `
    <button class="item" data-skill-id="${escapeHtml(item.candidate_skill_id)}">
      <div class="item-top"><span class="badge status-completed">候选</span></div>
      <div class="item-title"><code>${escapeHtml(item.candidate_skill_id)}</code></div>
      <div class="item-meta"><span>${escapeHtml(item.candidate_status || "unknown")}</span>${item.parent_skill ? `<span>· 父：${escapeHtml(item.parent_skill)}</span>` : ""}</div>
    </button>`).join("");
}

async function refreshSidebar() {
  try {
    await Promise.all([refreshRuns(), refreshBatches(), refreshSkills()]);
  } catch (error) {
    // Keep last view; the health pill already reflects connectivity.
    console.warn("sidebar refresh failed", error);
  }
}

/* ------------------------------------------------------------------ */
/* run detail                                                          */
/* ------------------------------------------------------------------ */

async function selectRun(runId) {
  state.selected = runId;
  try {
    const [run, evolution] = await Promise.all([
      api(`/api/runs/${runId}`),
      api(`/api/runs/${runId}/evolution`),
    ]);
    renderDetail(run, evolution);
    renderRuns();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderDetail(run, evolution) {
  $("empty-detail").hidden = true;
  $("detail").hidden = false;

  $("run-direction").textContent = run.direction;
  $("run-id").textContent = run.run_id;
  $("run-kind").textContent = run.dry_run ? "Dry-run" : (run.kind === "batch" ? "批量" : "单题");

  const status = run.status;
  $("run-status").className = `badge status-${status}`;
  $("run-status").innerHTML = `${statusDot(status, { pulse: ["queued", "running", "cancel_requested"].includes(status) })}${escapeHtml(STATUS_LABELS[status] || status)}`;

  $("run-times").textContent = `创建 ${relativeTime(run.created_at)} · 完成 ${relativeTime(run.finished_at)}`;
  $("run-resume").textContent = run.resume_count ? `已续跑 ${run.resume_count} 次` : "未续跑";

  $("resume").disabled = ["dry_run", "queued", "running", "cancel_requested"].includes(status);
  $("cancel").disabled = !["queued", "running", "cancel_requested"].includes(status);
  $("evolve").disabled = status !== "completed" || !(evolution?.execution_enabled);

  renderError(run.error);
  renderValidation(run.delivery_validation);
  renderProgress(run.stages || []);
  renderStages(run.stages || [], status);
  renderArtifacts(run.artifacts || []);
  renderEvolution(evolution);
}

function renderError(error) {
  const node = $("run-error");
  if (!error) { node.hidden = true; node.innerHTML = ""; return; }
  node.hidden = false;
  node.innerHTML = `<h4>运行失败 · ${escapeHtml(error.type || "Error")}</h4><pre>${escapeHtml(error.message || "")}</pre>`;
}

function renderValidation(validation) {
  const node = $("run-validation");
  if (!validation || typeof validation !== "object") { node.hidden = true; node.innerHTML = ""; return; }
  const recommendation = validation.recommendation || validation.status;
  const ok = String(validation.passed ?? "") === "true" || /pass|minor_revision|completed/i.test(String(recommendation || ""));
  node.hidden = false;
  node.className = `alert ${ok ? "alert-ok" : "alert-error"}`;
  const rows = Object.entries(validation)
    .filter(([, v]) => v !== null && typeof v !== "object")
    .slice(0, 8)
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
    .join("");
  node.innerHTML = `<h4>交付校验${recommendation ? ` · ${escapeHtml(recommendation)}` : ""}</h4><dl class="kv">${rows}</dl>`;
}

function renderProgress(stages) {
  const total = stages.length;
  const done = stages.filter((stage) => stage.status === "completed").length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("progress-label").textContent = `${done} / ${total} 阶段完成`;
  $("progress-fill").style.width = `${pct}%`;
}

function renderStages(stages, runStatus) {
  const activeIndex = stages.findIndex((stage) => stage.status !== "completed");
  const running = runStatus === "running";
  $("stages").innerHTML = stages.map((stage, index) => {
    const stateCls = stage.status === "completed"
      ? "completed"
      : stage.status === "invalid"
        ? "invalid"
        : running && index === activeIndex
          ? "active"
          : "";
    const dotIcon = stage.status === "completed"
      ? '<svg viewBox="0 0 20 20" fill="none"><path d="M5 10.5l3.4 3.4L15 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
      : stage.status === "invalid"
        ? '<svg viewBox="0 0 20 20" fill="none"><path d="M10 5v5.5M10 14.2v.3" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'
        : stateCls === "active"
          ? '<svg viewBox="0 0 20 20" fill="currentColor"><circle cx="10" cy="10" r="4"/></svg>'
          : "";
    return `
      <div class="stage ${stateCls}">
        <div class="stage-dot">${dotIcon}</div>
        <div class="stage-body">
          <span class="stage-name">${String(stage.ordinal).padStart(2, "0")} · ${escapeHtml(stage.label_zh)}</span>
          <span class="stage-eng">${escapeHtml(stage.stage_name)}</span>
        </div>
        <div class="stage-side">
          <span class="mini-badge">${escapeHtml(STAGE_STATE_LABELS[stage.status] || stage.status)}</span>
          ${stage.artifact_count ? `<div style="margin-top:4px">${stage.artifact_count} 制品</div>` : ""}
        </div>
      </div>`;
  }).join("");
}

function renderArtifacts(artifacts) {
  const root = $("artifacts");
  if (!artifacts.length) {
    root.innerHTML = '<p class="empty">尚无可展示产物</p>';
    return;
  }
  const groups = {};
  for (const item of artifacts) {
    (groups[item.category] ||= []).push(item);
  }
  const order = ["plan", "evidence", "review", "evolution", "runtime", "internal", "other"];
  const sorted = Object.keys(groups).sort((a, b) => order.indexOf(a) - order.indexOf(b));

  root.innerHTML = `<div class="artifact-groups">${sorted.map((category) => `
    <div class="artifact-group">
      <div class="artifact-group-head"><span class="icon">${categoryIcon(category)}</span>${escapeHtml(CATEGORY_LABELS[category] || category)}</div>
      ${groups[category].map((item) => `
        <a class="artifact-item" href="${encodeURI(item.url)}" target="_blank" rel="noopener">
          <span class="file-badge ${escapeHtml(fileExt(item.relative_path))}">${escapeHtml(fileExt(item.relative_path).toUpperCase())}</span>
          <span class="artifact-name" title="${escapeHtml(item.relative_path)}">${escapeHtml(item.relative_path)}</span>
          <span class="artifact-sub"><span>${formatBytes(item.bytes)}</span><span>${escapeHtml((item.sha256 || "").slice(0, 8))}</span></span>
        </a>`).join("")}
    </div>`).join("")}</div>`;
}

function fileExt(path) {
  const name = String(path || "").split("/").pop();
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "file" : name.slice(dot + 1).toLowerCase().slice(0, 4);
}

function categoryIcon(category) {
  const icons = {
    plan: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M5 2.5h7l3 3V17.5H5z" stroke="currentColor" stroke-width="1.5"/><path d="M12 2.5v3h3" stroke="currentColor" stroke-width="1.5"/></svg>',
    evidence: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M3 16V9M8 16V4M13 16v-6M18 16V6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    review: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.5"/><path d="M13.2 13.2L17 17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    evolution: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M10 2.5l2.2 4.6 5 .7-3.6 3.5.9 5L10 13.9l-4.5 2.4.9-5-3.6-3.5 5-.7L10 2.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    runtime: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><circle cx="10" cy="10" r="2.2" fill="currentColor"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    internal: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M3 4h14v12H3z" stroke="currentColor" stroke-width="1.5"/><path d="M3 8h14" stroke="currentColor" stroke-width="1.5"/></svg>',
    other: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.5"/></svg>',
  };
  return icons[category] || icons.other;
}

function renderEvolution(evolution) {
  const node = $("evolution");
  if (!evolution) { node.innerHTML = '<p class="empty">暂无自进化状态</p>'; return; }

  const selected = evolution.selected_skills?.source_artifact || "尚未产生 Skill 路由制品";
  const candidates = evolution.skill_candidates || [];
  const receipt = evolution.run_evolution_receipt;
  const mode = evolution.mode === "query_only" ? "只读查询" : "冻结服务可用";

  node.innerHTML = `
    <div class="evolution-grid">
      <dl class="kv">
        <dt>Skill 路由制品</dt><dd>${escapeHtml(selected)}</dd>
        <dt>执行模式</dt><dd>${escapeHtml(mode)}</dd>
        <dt>自动晋升</dt><dd>永不（${escapeHtml(evolution.promotion_authorized ? "已授权" : "未授权")}）</dd>
        <dt>候选数量</dt><dd>${candidates.length}</dd>
      </dl>
      ${receipt ? `<div class="candidate"><code>${escapeHtml(receipt.run_id || "")}</code><small>${escapeHtml(receipt.status || "completed")}</small></div>` : ""}
      <div class="candidates">${candidates.map((item) => `
        <div class="candidate">
          <code>${escapeHtml(item.candidate_skill_id)}</code>
          <small>${escapeHtml(item.candidate_status || "unknown")}${item.parent_skill ? ` · 父 ${escapeHtml(item.parent_skill)}` : ""}</small>
        </div>`).join("") || '<p class="empty">暂无候选</p>'}
    </div>`;
}

/* ------------------------------------------------------------------ */
/* actions                                                             */
/* ------------------------------------------------------------------ */

$("resume").addEventListener("click", async () => {
  if (!state.selected) return;
  try {
    await api(`/api/runs/${state.selected}/resume`, { method: "POST" });
    toast("已从断点续跑");
    await selectRun(state.selected);
  } catch (error) { toast(error.message, true); }
});

$("cancel").addEventListener("click", async () => {
  if (!state.selected) return;
  try {
    const result = await api(`/api/runs/${state.selected}/cancel`, { method: "POST" });
    toast(result.cancellation_boundary ? "取消请求已记录（运行中的工作不会被强杀）" : "取消请求已记录");
    await selectRun(state.selected);
  } catch (error) { toast(error.message, true); }
});

$("evolve").addEventListener("click", async () => {
  if (!state.selected) return;
  try {
    await api(`/api/runs/${state.selected}/evolution`, { method: "POST" });
    toast("Skill 候选已生成（影子评估，未晋升）");
    await selectRun(state.selected);
  } catch (error) { toast(error.message, true); }
});

$("single-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({ direction: $("direction").value, dry_run: $("single-dry").checked }),
    });
    closeModal("modal-run");
    toast("运行已创建");
    $("direction").value = "";
    await refreshRuns();
    await selectRun(result.run_id);
  } catch (error) { toast(error.message, true); }
});

$("batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const includeQuestionIds = $("batch-ids").value.split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
  try {
    const result = await api("/api/batches", {
      method: "POST",
      body: JSON.stringify({
        question_pdf: $("question-pdf").value,
        start: Number($("batch-start").value),
        limit: Number($("batch-limit").value),
        include_question_ids: includeQuestionIds,
        dry_run: $("batch-dry").checked,
      }),
    });
    closeModal("modal-batch");
    toast(`批量任务 ${result.batch_id}：${result.question_count} 个问题`);
    await refreshBatches();
  } catch (error) { toast(error.message, true); }
});

/* ------------------------------------------------------------------ */
/* modals                                                              */
/* ------------------------------------------------------------------ */

function openModal(id) {
  $(id).hidden = false;
}
function closeModal(id) {
  $(id).hidden = true;
}
$("btn-new-run").addEventListener("click", () => openModal("modal-run"));
$("btn-new-batch").addEventListener("click", () => openModal("modal-batch"));
document.querySelectorAll(".modal-close").forEach((button) => {
  button.addEventListener("click", () => closeModal(button.dataset.close));
});
document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal(backdrop.id);
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    document.querySelectorAll(".modal-backdrop").forEach((backdrop) => { backdrop.hidden = true; });
  }
});

/* ------------------------------------------------------------------ */
/* tabs                                                                */
/* ------------------------------------------------------------------ */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.activeTab = tab.dataset.tab;
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      t.setAttribute("aria-selected", t === tab ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== state.activeTab;
    });
  });
});

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */

async function boot() {
  initTheme();
  await refreshHealth();
  try {
    await refreshSidebar();
  } catch (_) {
    // connectivity error already surfaced via the health pill
  }
  window.setInterval(async () => {
    try {
      await refreshRuns();
      await refreshHealth();
      const selected = state.runs.find((run) => run.run_id === state.selected);
      if (selected && ["queued", "running", "cancel_requested"].includes(selected.status)) {
        await selectRun(state.selected);
      }
    } catch (_) { /* keep last view */ }
  }, 3000);
}

boot();
