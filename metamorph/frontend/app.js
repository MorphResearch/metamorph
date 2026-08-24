"use strict";

// 简单的 API 封装（同源，无需额外配置跨域）
async function api(path, options) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  return { ok: res.ok, status: res.status, data };
}

// 根据 run 状态返回对应的样式类与文案
function statusMeta(status) {
  switch (status) {
    case "queued": return { cls: "pill-off", label: "排队中" };
    case "running": return { cls: "pill-run", label: "运行中" };
    case "passed": return { cls: "pill-ok", label: "通过" };
    case "failed": return { cls: "pill-err", label: "失败" };
    default: return { cls: "pill-off", label: status || "未知" };
  }
}

// 全局状态
const state = {
  currentRunId: null,
  pollTimer: null,
};

// ---------- 连接与信息 ----------
async function loadInfo() {
  const conn = document.getElementById("conn-pill");
  const prov = document.getElementById("provider-pill");
  try {
    const { ok, data } = await api("/v1/info");
    if (!ok) throw new Error("bad status");
    conn.textContent = "已连接";
    conn.className = "pill pill-ok";
    const model = data.model_name ? ` · ${data.model_name}` : "";
    prov.textContent = `${data.provider}${model}`;
    prov.className = "pill pill-info";
    prov.title = `工作区根目录: ${data.workspace_root} · 允许写入: ${data.allow_write ? "是" : "否"}`;
  } catch (e) {
    conn.textContent = "连接失败";
    conn.className = "pill pill-err";
    prov.textContent = "—";
    prov.className = "pill pill-info";
  }
}

// ---------- 运行历史 ----------
async function loadHistory() {
  const list = document.getElementById("history-list");
  try {
    const { ok, data } = await api("/v1/runs");
    if (!ok || !Array.isArray(data)) {
      list.innerHTML = '<li class="empty">加载失败</li>';
      return;
    }
    if (data.length === 0) {
      list.innerHTML = '<li class="empty">暂无运行记录</li>';
      return;
    }
    list.innerHTML = "";
    data.forEach((run) => {
      const li = document.createElement("li");
      if (run.run_id === state.currentRunId) li.classList.add("active");
      li.dataset.runId = run.run_id;
      const meta = statusMeta(run.status);
      li.innerHTML =
        `<span class="h-task">${escapeHtml(run.task)}</span>` +
        `<span class="h-meta"><span>${run.run_id}</span><span class="${meta.cls}">${meta.label}</span></span>`;
      li.addEventListener("click", () => openRun(run.run_id));
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = '<li class="empty">加载失败</li>';
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- 提交任务 ----------
document.getElementById("task-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = document.getElementById("submit-btn");
  const task = document.getElementById("task-input").value.trim();
  const workspaceId = document.getElementById("workspace-input").value.trim() || "default";
  if (!task) { alert("请填写任务描述"); return; }

  btn.disabled = true;
  btn.textContent = "提交中…";
  try {
    const { ok, data } = await api("/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, workspace_id: workspaceId }),
    });
    if (!ok) throw new Error(data && data.error ? data.error : "提交失败");
    await loadHistory();
    openRun(data.run_id);
  } catch (e) {
    alert("提交失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "提交任务";
  }
});

// ---------- 打开某次运行 ----------
async function openRun(runId) {
  stopPolling();
  state.currentRunId = runId;
  await refreshRun();
  await loadHistory();
  // 若仍在运行，则轮询
  const status = document.getElementById("detail-status").textContent;
  if (status === "排队中" || status === "运行中") {
    startPolling();
  }
}

async function refreshRun() {
  const { ok, data } = await api(`/v1/runs/${state.currentRunId}`);
  if (!ok || !data) {
    showEmpty("未找到该运行记录");
    return;
  }
  renderRun(data);
  const eventsRes = await api(`/v1/runs/${state.currentRunId}/events`);
  if (eventsRes.ok && Array.isArray(eventsRes.data)) {
    renderEvents(eventsRes.data);
  }
}

function showEmpty(msg) {
  document.getElementById("detail").hidden = true;
  const empty = document.getElementById("detail-empty");
  empty.hidden = false;
  empty.querySelector("p").textContent = msg;
}

function renderRun(run) {
  document.getElementById("detail-empty").hidden = true;
  const detail = document.getElementById("detail");
  detail.hidden = false;

  document.getElementById("detail-task").textContent = run.task || "(无任务描述)";
  document.getElementById("detail-runid").textContent = run.run_id;

  const meta = statusMeta(run.status);
  const statusEl = document.getElementById("detail-status");
  statusEl.textContent = meta.label;
  statusEl.className = "pill " + meta.cls;

  const result = run.result || {};
  const metrics = [
    ["状态", meta.label],
    ["步骤", result.steps != null ? result.steps : "—"],
    ["工具错误", result.tool_errors != null ? result.tool_errors : "—"],
    ["耗时(秒)", result.duration_seconds != null ? result.duration_seconds : "—"],
    ["模型", result.model || "—"],
  ];
  const mEl = document.getElementById("detail-metrics");
  mEl.innerHTML = metrics.map(([k, v]) =>
    `<div class="metric"><div class="k">${k}</div><div class="v">${escapeHtml(v)}</div></div>`
  ).join("");

  const answerBlock = document.getElementById("answer-block");
  if (result.answer) {
    answerBlock.hidden = false;
    document.getElementById("detail-answer").textContent = result.answer;
  } else {
    answerBlock.hidden = true;
  }

  const evalBlock = document.getElementById("evaluation-block");
  const ev = result.evaluation;
  if (ev) {
    evalBlock.hidden = false;
    const score = typeof ev.score === "number" ? (ev.score * 100).toFixed(0) + "%" : "—";
    let html = `<div class="check"><span>得分</span><span>${score}</span></div>`;
    const checks = ev.checks || {};
    for (const [k, v] of Object.entries(checks)) {
      html += `<div class="check"><span>${escapeHtml(k)}</span>` +
        `<span class="${v ? "pass" : "fail"}">${v ? "通过" : "未通过"}</span></div>`;
    }
    (ev.notes || []).forEach((n) => {
      html += `<div class="check" style="color:var(--muted);font-size:12px">${escapeHtml(n)}</div>`;
    });
    document.getElementById("detail-evaluation").innerHTML = html;
  } else {
    evalBlock.hidden = true;
  }
}

function renderEvents(events) {
  const tl = document.getElementById("event-timeline");
  if (!events.length) {
    tl.innerHTML = '<li class="empty" style="border:none;color:var(--muted)">暂无事件</li>';
    return;
  }
  tl.innerHTML = "";
  events.forEach((ev) => {
    const li = document.createElement("li");
    const type = ev.type || "event";
    if (type.includes("error")) li.classList.add("ev-error");
    if (type === "run.evaluated" || (ev.action === "finish")) li.classList.add("ev-finish");
    const time = (ev.timestamp || "").replace("T", " ").slice(0, 19);
    li.innerHTML =
      `<div class="t-type">${escapeHtml(type)}</div>` +
      `<div class="t-time">${escapeHtml(time)}</div>` +
      `<div class="t-detail">${escapeHtml(summarizeEvent(ev))}</div>`;
    tl.appendChild(li);
  });
}

function summarizeEvent(ev) {
  const parts = [];
  if (ev.action) parts.push(`action=${ev.action}`);
  if (ev.tool) parts.push(`tool=${ev.tool}`);
  if (ev.step != null) parts.push(`step=${ev.step}`);
  if (ev.error) parts.push(`error=${ev.error}`);
  if (ev.summary) parts.push(ev.summary);
  if (ev.answer) parts.push(ev.answer);
  if (ev.observation) {
    const o = String(ev.observation);
    parts.push("observation=" + (o.length > 300 ? o.slice(0, 300) + "…" : o));
  }
  if (ev.result && typeof ev.result === "object") {
    if (ev.result.output) parts.push("output=" + ev.result.output);
    if (ev.result.error) parts.push("result.error=" + ev.result.error);
  }
  return parts.join("  ·  ");
}

// ---------- 轮询 ----------
function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    if (!state.currentRunId) return;
    await refreshRun();
    await loadHistory();
    const status = document.getElementById("detail-status").textContent;
    if (status !== "排队中" && status !== "运行中") stopPolling();
  }, 1500);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

// ---------- 启动 ----------
(async function init() {
  await loadInfo();
  await loadHistory();
})();
