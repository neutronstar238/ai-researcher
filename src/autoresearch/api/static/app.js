const state = { selected: null, runs: [] };

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
  return payload;
}

function toast(message, error = false) {
  const node = $("toast");
  node.textContent = message;
  node.className = error ? "show error" : "show";
  window.setTimeout(() => { node.className = ""; }, 3200);
}

function statusLabel(status) {
  const labels = {
    dry_run: "预览", queued: "排队", running: "运行中", cancel_requested: "等待安全停止",
    canceled: "已取消", completed: "已完成", failed: "失败", interrupted: "可续跑",
  };
  return labels[status] || status;
}

async function refreshRuns() {
  const payload = await api("/api/runs");
  state.runs = payload.runs;
  const root = $("runs");
  root.innerHTML = "";
  if (!state.runs.length) {
    root.innerHTML = '<p class="empty">尚无运行</p>';
    return;
  }
  for (const run of state.runs) {
    const button = document.createElement("button");
    button.className = `run-card ${state.selected === run.run_id ? "selected" : ""}`;
    button.innerHTML = `<span class="status-dot ${run.status}"></span><span><strong>${escapeHtml(run.direction)}</strong><small>${statusLabel(run.status)} · ${escapeHtml(run.run_id)}</small></span>`;
    button.onclick = () => selectRun(run.run_id);
    root.appendChild(button);
  }
}

async function selectRun(runId) {
  state.selected = runId;
  const [run, evolution] = await Promise.all([
    api(`/api/runs/${runId}`),
    api(`/api/runs/${runId}/evolution`),
  ]);
  $("empty-detail").hidden = true;
  $("detail").hidden = false;
  $("run-id").textContent = run.run_id;
  $("run-direction").textContent = run.direction;
  $("run-status").textContent = statusLabel(run.status);
  $("run-status").className = `badge ${run.status}`;
  $("resume").disabled = ["dry_run", "queued", "running", "cancel_requested"].includes(run.status);
  $("cancel").disabled = !["queued", "running", "cancel_requested"].includes(run.status);
  renderStages(run.stages || []);
  renderArtifacts(run.artifacts || []);
  renderEvolution(evolution);
  await refreshRuns();
}

function renderStages(stages) {
  $("stages").innerHTML = stages.map((stage) => `
    <div class="stage ${stage.status}">
      <span class="stage-number">${String(stage.ordinal).padStart(2, "0")}</span>
      <span><strong>${escapeHtml(stage.label_zh)}</strong><small>${escapeHtml(stage.stage_name)}</small></span>
      <span class="stage-state">${stage.status === "completed" ? "完成" : "等待"}</span>
    </div>`).join("");
}

function renderArtifacts(artifacts) {
  const root = $("artifacts");
  if (!artifacts.length) {
    root.innerHTML = '<p class="empty">尚无可展示产物</p>';
    return;
  }
  const groups = Object.groupBy ? Object.groupBy(artifacts, (item) => item.category) : artifacts.reduce((acc, item) => {
    (acc[item.category] ||= []).push(item); return acc;
  }, {});
  root.innerHTML = Object.entries(groups).map(([category, items]) => `
    <div class="artifact-group"><h4>${escapeHtml(category)}</h4>${items.map((item) => `
      <a href="${encodeURI(item.url)}" target="_blank" rel="noopener">
        <span>${escapeHtml(item.relative_path)}</span><small>${formatBytes(item.bytes)} · ${item.sha256.slice(0, 10)}</small>
      </a>`).join("")}</div>`).join("");
}

function renderEvolution(data) {
  const selected = data.selected_skills?.source_artifact || "尚未产生 Skill 路由制品";
  const candidates = data.skill_candidates || [];
  $("evolution").innerHTML = `
    <p><strong>当前运行：</strong>${escapeHtml(selected)}</p>
    <p><strong>执行模式：</strong>只读查询；API 不生成、晋升或覆盖 Skill。</p>
    <p><strong>候选数量：</strong>${candidates.length}</p>
    ${candidates.map((item) => `<div class="candidate"><code>${escapeHtml(item.candidate_skill_id)}</code><span>${escapeHtml(item.candidate_status)}</span></div>`).join("")}`;
}

$("single-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/runs", { method: "POST", body: JSON.stringify({
      direction: $("direction").value, dry_run: $("single-dry").checked,
    }) });
    toast("运行已创建");
    await refreshRuns();
    await selectRun(result.run_id);
  } catch (error) { toast(error.message, true); }
});

$("batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const includeQuestionIds = $("batch-ids").value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item));
  try {
    const result = await api("/api/batches", { method: "POST", body: JSON.stringify({
      question_pdf: $("question-pdf").value,
      start: Number($("batch-start").value), limit: Number($("batch-limit").value),
      include_question_ids: includeQuestionIds, dry_run: $("batch-dry").checked,
    }) });
    toast(`批量任务 ${result.batch_id}：${result.question_count} 个问题`);
  } catch (error) { toast(error.message, true); }
});

$("resume").onclick = async () => {
  try { await api(`/api/runs/${state.selected}/resume`, { method: "POST" }); toast("已从断点续跑"); await selectRun(state.selected); }
  catch (error) { toast(error.message, true); }
};

$("cancel").onclick = async () => {
  try { await api(`/api/runs/${state.selected}/cancel`, { method: "POST" }); toast("取消请求已记录"); await selectRun(state.selected); }
  catch (error) { toast(error.message, true); }
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}
function formatBytes(value) { return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`; }

async function boot() {
  try {
    const health = await api("/api/health");
    $("health").textContent = health.status === "ok" ? "本地服务正常" : "服务异常";
    $("health").className = "badge completed";
    await refreshRuns();
    window.setInterval(async () => {
      try {
        await refreshRuns();
        const selected = state.runs.find((run) => run.run_id === state.selected);
        if (selected && ["queued", "running", "cancel_requested"].includes(selected.status)) await selectRun(state.selected);
      } catch (_) { /* keep last view */ }
    }, 3000);
  } catch (error) { $("health").textContent = "连接失败"; $("health").className = "badge failed"; }
}
boot();
