"use strict";

// ---------- 基础工具 ----------
async function api(path, options) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  return { ok: res.ok, status: res.status, data };
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// 把换行文本安全转为带 <br> 的 HTML
function textToHtml(s) {
  return escapeHtml(s).replace(/\n/g, "<br>");
}

function statusMeta(status) {
  switch (status) {
    case "queued": return { cls: "pill-off", label: "排队中" };
    case "running": return { cls: "pill-run", label: "运行中" };
    case "passed": return { cls: "pill-ok", label: "已通过" };
    case "failed": return { cls: "pill-err", label: "失败" };
    default: return { cls: "pill-off", label: status || "未知" };
  }
}

// ---------- 全局状态 ----------
const state = {
  currentRunId: null,
  pollTimer: null,
  busy: false,
};

// ---------- 连接信息 ----------
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
  }
}

// ---------- 历史 ----------
async function loadHistory() {
  const list = document.getElementById("history-list");
  try {
    const { ok, data } = await api("/v1/runs");
    if (!ok || !Array.isArray(data)) { list.innerHTML = '<li class="empty">加载失败</li>'; return; }
    if (data.length === 0) { list.innerHTML = '<li class="empty">暂无运行记录</li>'; return; }
    list.innerHTML = "";
    data.forEach((run) => {
      const li = document.createElement("li");
      if (run.run_id === state.currentRunId) li.classList.add("active");
      const meta = statusMeta(run.status);
      li.innerHTML =
        `<span class="h-task">${escapeHtml(run.task || "(无描述)")}</span>` +
        `<span class="h-meta"><span class="h-id">${run.run_id}</span><span class="${meta.cls}">${meta.label}</span></span>`;
      li.addEventListener("click", () => loadRunIntoChat(run.run_id));
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = '<li class="empty">加载失败</li>';
  }
}

// ---------- 消息渲染 ----------
const messagesEl = document.getElementById("messages");

function removeWelcome() {
  const w = messagesEl.querySelector(".welcome");
  if (w) w.remove();
}

function addUserMessage(text) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble">${textToHtml(text)}</div>`;
  messagesEl.appendChild(div);
  scrollBottom();
  return div;
}

// 新建一条 assistant 消息，返回其内部容器引用，便于后续逐步填充
function addAssistantMessage(runId) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "msg assistant";
  div.dataset.runId = runId;
  div.innerHTML =
    `<div class="avatar">◈</div>` +
    `<div class="bubble">` +
      `<div class="status-line"><span class="spinner"></span><span class="status-text">正在思考…</span></div>` +
      `<div class="chain"></div>` +
      `<div class="final-answer" hidden></div>` +
    `</div>`;
  messagesEl.appendChild(div);
  scrollBottom();
  return div;
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// 构建一条"思考/动作"条目（对话式思考链）
function buildChainItem(ev) {
  const type = ev.type || "event";
  const time = (ev.timestamp || "").replace("T", " ").slice(0, 19);

  // 1) LLM 的规划/思考（model.decision）
  if (type === "model.decision") {
    const wrap = document.createElement("div");
    wrap.className = "chain-item think";
    const summary = ev.summary || "（模型未返回思考摘要）";
    wrap.innerHTML =
      `<div class="ci-head"><span class="ci-dot"></span><span class="ci-title">思考 · 第 ${ev.step ?? "?"} 步</span>` +
      `<span class="ci-action">动作: ${escapeHtml(ev.action || "")}</span></div>` +
      `<div class="ci-body">${textToHtml(summary)}</div>`;
    return wrap;
  }

  // 2) 工具调用（tool.completed）
  if (type === "tool.completed") {
    const wrap = document.createElement("div");
    wrap.className = "chain-item tool";
    const ok = ev.result && ev.result.ok;
    const out = ev.result && ev.result.output ? String(ev.result.output) : "";
    const err = ev.result && ev.result.error ? String(ev.result.error) : "";
    let argStr = "";
    try { argStr = JSON.stringify(ev.arguments || {}); } catch (e) { argStr = String(ev.arguments || ""); }
    const shown = (err || out).slice(0, 600) + ((err || out).length > 600 ? "…" : "");
    wrap.innerHTML =
      `<div class="ci-head ${ok ? "" : "err"}"><span class="ci-icon">🔧</span>` +
      `<span class="ci-title">调用工具: ${escapeHtml(ev.tool || "")}</span>` +
      `<span class="ci-status">${ok ? "成功" : "失败"}</span></div>` +
      `<div class="ci-body">` +
        `<div class="ci-args">参数: ${escapeHtml(argStr)}</div>` +
        (shown ? `<div class="ci-out">${escapeHtml(shown)}</div>` : "") +
      `</div>`;
    return wrap;
  }

  // 3) 错误（model.error / observation 异常等）
  if (type.includes("error")) {
    const wrap = document.createElement("div");
    wrap.className = "chain-item tool err";
    wrap.innerHTML =
      `<div class="ci-head err"><span class="ci-icon">✕</span>` +
      `<span class="ci-title">${escapeHtml(type.replace("run.", ""))}</span></div>` +
      `<div class="ci-body">${escapeHtml(ev.error || "出错了")}</div>`;
    return wrap;
  }

  // 其它事件（run.started 等）折叠忽略，避免噪音
  return null;
}

// 把 run 的事件渲染进某条 assistant 消息（思考链）
function renderEventsInto(msgEl, events) {
  const chainEl = msgEl.querySelector(".chain");
  chainEl.innerHTML = "";
  let hasContent = false;
  events.forEach((ev) => {
    const item = buildChainItem(ev);
    if (item) { chainEl.appendChild(item); hasContent = true; }
  });
  if (!hasContent) {
    chainEl.innerHTML = `<div class="chain-empty">正在连接模型…</div>`;
  }
}

function setStatusText(msgEl, text) {
  const s = msgEl.querySelector(".status-text");
  if (s) s.textContent = text;
}

function finishMessage(msgEl, run) {
  const statusLine = msgEl.querySelector(".status-line");
  const finalEl = msgEl.querySelector(".final-answer");
  const meta = statusMeta(run.status);
  const spinner = msgEl.querySelector(".spinner");
  if (spinner) spinner.remove();

  const result = run.result || {};
  // 最终回答作为 AI 的正式回复（去掉评分卡，呈现纯对话体验）
  if (result.answer) {
    finalEl.hidden = false;
    finalEl.innerHTML = `<div class="answer-body">${textToHtml(result.answer)}</div>`;
  } else if (run.status === "failed") {
    finalEl.hidden = false;
    finalEl.innerHTML = `<div class="answer-body">任务未成功完成（失败）。</div>`;
  }

  if (statusLine) {
    statusLine.innerHTML = `<span class="pill ${meta.cls}" style="font-size:11px">${meta.label}</span>` +
      (result.steps != null ? ` <span class="mini">${result.steps} 步</span>` : "") +
      (result.duration_seconds != null ? ` <span class="mini">${result.duration_seconds}s</span>` : "") +
      (result.model ? ` <span class="mini">${escapeHtml(result.model)}</span>` : "");
  }
}

// ---------- 拉取并刷新一条运行 ----------
async function refreshRun(msgEl) {
  const { ok, data } = await api(`/v1/runs/${state.currentRunId}`);
  if (!ok || !data) return;
  const eventsRes = await api(`/v1/runs/${state.currentRunId}/events`);
  const events = eventsRes.ok && Array.isArray(eventsRes.data) ? eventsRes.data : [];
  renderEventsInto(msgEl, events);

  const st = data.status;
  if (st === "queued") setStatusText(msgEl, "排队中…");
  else if (st === "running") setStatusText(msgEl, "调用 LLM 中…");
  else setStatusText(msgEl, statusMeta(st).label);

  if (st === "passed" || st === "failed") {
    stopPolling();
    finishMessage(msgEl, data);
    await loadHistory();
  }
  scrollBottom();
}

// ---------- 提交任务（进入对话） ----------
async function submitTask(taskText) {
  if (state.busy) return;
  const workspaceId = document.getElementById("workspace-input").value.trim() || "default";
  if (!taskText) return;

  state.busy = true;
  setComposerDisabled(true);
  addUserMessage(taskText);

  try {
    const { ok, data } = await api("/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: taskText, workspace_id: workspaceId }),
    });
    if (!ok) throw new Error(data && data.error ? data.error : "提交失败");

    state.currentRunId = data.run_id;
    const msgEl = addAssistantMessage(data.run_id);
    await loadHistory();
    await refreshRun(msgEl);
    startPolling(msgEl);
  } catch (e) {
    const m = addAssistantMessage(null);
    m.querySelector(".chain").innerHTML = `<div class="chain-item tool err"><div class="ci-head err"><span class="ci-icon">✕</span><span class="ci-title">提交失败</span></div><div class="ci-body">${escapeHtml(e.message)}</div></div>`;
    const sp = m.querySelector(".spinner"); if (sp) sp.remove();
    setStatusText(m, "失败");
  } finally {
    state.busy = false;
    setComposerDisabled(false);
  }
}

// ---------- 查看历史运行 ----------
async function loadRunIntoChat(runId) {
  stopPolling();
  state.currentRunId = runId;
  const { ok, data } = await api(`/v1/runs/${runId}`);
  if (!ok || !data) return;
  removeWelcome();
  const msgEl = addAssistantMessage(runId);
  addUserMessage(data.task || "(无描述)");
  msgEl.remove(); // 顺序：先放 user，再放 assistant
  const realEl = addAssistantMessage(runId);
  await refreshRun(realEl);
  await loadHistory();
  if (data.status === "running" || data.status === "queued") startPolling(realEl);
}

// ---------- 轮询 ----------
function startPolling(msgEl) {
  stopPolling();
  state.pollTimer = setInterval(() => {
    if (!state.currentRunId) return;
    refreshRun(msgEl);
  }, 1500);
}
function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

// ---------- 输入框交互 ----------
function setComposerDisabled(disabled) {
  document.getElementById("send-btn").disabled = disabled;
  document.getElementById("prompt-input").disabled = disabled;
}

const promptInput = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");

function autoGrow() {
  promptInput.style.height = "auto";
  promptInput.style.height = Math.min(promptInput.scrollHeight, 160) + "px";
}
promptInput.addEventListener("input", autoGrow);

function send() {
  const text = promptInput.value.trim();
  if (!text || state.busy) return;
  promptInput.value = "";
  autoGrow();
  submitTask(text);
}

sendBtn.addEventListener("click", send);
promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.getElementById("new-chat").addEventListener("click", () => {
  stopPolling();
  state.currentRunId = null;
  messagesEl.innerHTML =
    `<div class="welcome">` +
      `<div class="welcome-logo">◈</div>` +
      `<h2>我能帮你做什么？</h2>` +
      `<p>描述一个任务，Agent 会规划、调用工具并执行，最后给出结果。你可以随时查看它的思考与执行过程。</p>` +
      `<div class="suggestions">` +
        `<button class="chip" data-q="检查当前工作区并总结文件结构">检查当前工作区并总结文件结构</button>` +
        `<button class="chip" data-q="用 Python 写一个快速排序，并加测试用例">用 Python 写一个快速排序，并加测试用例</button>` +
        `<button class="chip" data-q="读取 README.md 并用一句话概括这个项目">读取 README.md 并用一句话概括这个项目</button>` +
      `</div>` +
    `</div>`;
  bindChips();
});

document.querySelectorAll(".chip").forEach(bindChip);
function bindChip(chip) {
  chip.addEventListener("click", () => {
    promptInput.value = chip.dataset.q;
    autoGrow();
    send();
  });
}
function bindChips() {
  document.querySelectorAll(".chip").forEach(bindChip);
}

// ---------- 启动 ----------
(async function init() {
  await loadInfo();
  await loadHistory();
})();
