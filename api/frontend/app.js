"use strict";

// Metamorph chat workspace. The browser keeps only UI state; runs, messages,
// events, and lessons remain persisted in the Python API.

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

function textToHtml(s) {
  return escapeHtml(s).replace(/\n/g, "<br>");
}

function statusMeta(status) {
  switch (status) {
    case "queued": return { cls: "pill-off", label: "排队中" };
    case "running": return { cls: "pill-run", label: "运行中" };
    case "passed":
    case "completed": return { cls: "pill-ok", label: "已完成" };
    case "failed": return { cls: "pill-err", label: "失败" };
    default: return { cls: "pill-off", label: status || "未知" };
  }
}

const state = {
  currentConversationId: null,
  currentRunId: null,
  currentMessageEl: null,
  pollTimer: null,
  polling: false,
  busy: false,
};

const messagesEl = document.getElementById("messages");
const promptInput = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeWelcome() {
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function welcomeHtml() {
  return `<div class="welcome">` +
    `<div class="welcome-logo">◈</div>` +
    `<h2>我能帮你做什么？</h2>` +
    `<p>描述一个任务，Agent 会规划、调用工具并执行。你可以连续追问，也可以展开查看思考、工具调用和多 Agent 评估。</p>` +
    `<div class="suggestions">` +
      `<button class="chip" data-q="检查当前工作区并总结文件结构">检查当前工作区并总结文件结构</button>` +
      `<button class="chip" data-q="用 Python 写一个快速排序，并加测试用例">用 Python 写一个快速排序，并加测试用例</button>` +
      `<button class="chip" data-q="读取 README.md 并用一句话概括这个项目">读取 README.md 并用一句话概括这个项目</button>` +
    `</div></div>`;
}

function setChatHeader(title, subtitle) {
  const titleEl = document.getElementById("chat-title");
  const subtitleEl = document.getElementById("chat-subtitle");
  if (titleEl) titleEl.textContent = title || "新建任务";
  if (subtitleEl) subtitleEl.textContent = subtitle || "输入任务开始一次新的 Agent 运行";
}

function resetChat() {
  stopPolling();
  state.currentConversationId = null;
  state.currentRunId = null;
  state.currentMessageEl = null;
  state.busy = false;
  messagesEl.innerHTML = welcomeHtml();
  setChatHeader("新建任务", "输入任务开始一次新的 Agent 运行");
  setComposerDisabled(false);
  bindChips();
}

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
    const modeSelect = document.getElementById("agent-mode");
    if (modeSelect && ["single", "multiagent"].includes(data.mode)) modeSelect.value = data.mode;
  } catch (e) {
    conn.textContent = "连接失败";
    conn.className = "pill pill-err";
    prov.textContent = "—";
  }
}

// ---------- 会话历史 ----------
async function loadHistory() {
  const list = document.getElementById("history-list");
  try {
    const { ok, data } = await api("/v1/conversations");
    if (!ok || !Array.isArray(data)) {
      list.innerHTML = '<li class="empty">加载失败</li>';
      return;
    }
    if (data.length === 0) {
      list.innerHTML = '<li class="empty">暂无对话记录</li>';
      return;
    }
    list.innerHTML = "";
    data.forEach((conversation) => {
      const li = document.createElement("li");
      if (conversation.conversation_id === state.currentConversationId) li.classList.add("active");
      li.innerHTML =
        `<span class="h-task">${escapeHtml(conversation.task || "(无描述)")}</span>`;
      li.addEventListener("click", () => loadConversationIntoChat(conversation.conversation_id));
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = '<li class="empty">加载失败</li>';
  }
}

// ---------- 消息渲染 ----------
function addUserMessage(text) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "msg user";
  const time = new Date().toTimeString().slice(0, 5);
  div.innerHTML =
    `<div class="msg-col">` +
      `<div class="bubble">${textToHtml(text)}</div>` +
      `<div class="msg-time">${time}</div>` +
    `</div>`;
  messagesEl.appendChild(div);
  scrollBottom();
  return div;
}

function addAssistantMessage(runId) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "msg assistant";
  if (runId) div.dataset.runId = runId;
  div.innerHTML =
    `<div class="avatar">◈</div>` +
    `<div class="msg-col">` +
      `<div class="ai-name">Metamorph</div>` +
      `<div class="status-line"><span class="spinner"></span><span class="status-text">正在思考…</span></div>` +
      `<div class="chain"></div>` +
      `<div class="final-answer" hidden><div class="answer-body"></div></div>` +
    `</div>`;
  messagesEl.appendChild(div);
  scrollBottom();
  return div;
}

function ensureThinkingPanel(msgEl) {
  let panel = msgEl._thinkPanel;
  if (panel && panel.isConnected) return panel;
  panel = document.createElement("details");
  panel.className = "thinking";
  panel.open = !msgEl._thinkCollapsed;
  panel.innerHTML = `<summary><span class="think-icon">✦</span> 深度思考<span class="think-caret"></span></summary><div class="think-body"></div>`;
  panel._buf = "";
  // 记录用户手动折叠状态，轮询重建时不再强制展开
  panel.addEventListener("toggle", () => { msgEl._thinkCollapsed = !panel.open; });
  msgEl.querySelector(".chain").appendChild(panel);
  msgEl._thinkPanel = panel;
  return panel;
}

function buildChainItem(ev, msgEl) {
  const type = ev.type || "event";

  if (type === "reasoning" || type === "model.decision") {
    // reasoning 与 model.decision 由 renderEventsInto 统一处理（需要跨事件维护流式缓冲）
    return null;
  }

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
      `<div class="ci-body"><div class="ci-args">参数: ${escapeHtml(argStr)}</div>` +
      (shown ? `<div class="ci-out">${escapeHtml(shown)}</div>` : "") + `</div>`;
    return wrap;
  }

  if (type === "architecture.designed") {
    const architecture = ev.architecture || {};
    const roles = (architecture.roles || []).map(role => role.name).join("、");
    const wrap = document.createElement("div");
    wrap.className = "chain-item think";
    wrap.innerHTML = `<div class="ci-head"><span class="ci-icon">🧭</span><span class="ci-title">架构设计</span></div>` +
      `<div class="ci-body">${escapeHtml(architecture.strategy || "")} ${escapeHtml(roles)}</div>`;
    return wrap;
  }

  if (type === "agent.completed") {
    const agent = ev.agent || {};
    const wrap = document.createElement("div");
    wrap.className = "chain-item think";
    wrap.innerHTML = `<div class="ci-head"><span class="ci-icon">👤</span><span class="ci-title">${escapeHtml(agent.role || agent.agent_id || "Agent")}</span></div>` +
      `<div class="ci-body">${agent.success ? "已完成角色任务" : "角色执行失败"}</div>`;
    return wrap;
  }

  if (type === "contribution.evaluated") {
    const wrap = document.createElement("div");
    wrap.className = "chain-item tool";
    const count = ev.report && ev.report.agents ? ev.report.agents.length : 0;
    wrap.innerHTML = `<div class="ci-head"><span class="ci-icon">📊</span><span class="ci-title">贡献评估</span></div>` +
      `<div class="ci-body">已评估 ${count} 个 Agent 的边际贡献、纠错、独特性和冗余。</div>`;
    return wrap;
  }

  if (type === "lesson.exchanged" || type === "architecture.adjusted") {
    const wrap = document.createElement("div");
    wrap.className = "chain-item think";
    wrap.innerHTML = `<div class="ci-head"><span class="ci-icon">🔁</span><span class="ci-title">${type === "lesson.exchanged" ? "Lesson 已记录" : "下一轮架构建议"}</span></div>` +
      `<div class="ci-body">结果将用于后续任务的架构设计。</div>`;
    return wrap;
  }

  if (type.includes("error")) {
    const wrap = document.createElement("div");
    wrap.className = "chain-item tool err";
    wrap.innerHTML = `<div class="ci-head err"><span class="ci-icon">✕</span><span class="ci-title">${escapeHtml(type.replace("run.", ""))}</span></div>` +
      `<div class="ci-body">${escapeHtml(ev.error || "出错了")}</div>`;
    return wrap;
  }
  return null;
}

function renderEventsInto(msgEl, events) {
  const chainEl = msgEl.querySelector(".chain");
  const finalEl = msgEl.querySelector(".final-answer");
  const answerBody = finalEl.querySelector(".answer-body");
  chainEl.innerHTML = "";
  msgEl._thinkPanel = null;

  let reasoningBuf = "";   // 真实思考链缓冲（模型 reasoning 字段）
  let answerBuf = "";      // 当前轮回答流式缓冲
  let hasProcess = false;  // 是否有可展示的执行过程

  events.forEach((ev) => {
    const type = ev.type || "event";

    if (type === "reasoning") {
      if (ev.text) {
        reasoningBuf += ev.text;
        const panel = ensureThinkingPanel(msgEl);
        panel._buf = reasoningBuf;
        panel.querySelector(".think-body").textContent = reasoningBuf;
      }
      return;
    }

    if (type === "answer.delta") {
      answerBuf += ev.text || "";
      // 有可见内容才展开回答区；展示时去掉首尾空白，避免 pre-wrap 下开头换行产生空行
      if (answerBuf.trim()) {
        finalEl.hidden = false;
        answerBody.textContent = answerBuf.trim();
      }
      return;
    }

    if (type === "model.decision") {
      if (ev.action === "tool_call") {
        // 工具轮：把该轮流出的有效文本归档为步骤叙述，回答区清空等待最终答案
        // 注意 trim 判断：模型常在工具调用前只输出换行/空格，纯空白不渲染卡片
        const narrative = answerBuf.trim();
        if (narrative) {
          const wrap = document.createElement("div");
          wrap.className = "chain-item step";
          wrap.innerHTML =
            `<div class="ci-head"><span class="ci-dot"></span><span class="ci-title">第 ${escapeHtml(ev.step ?? "?")} 步</span>` +
            `<span class="ci-status">工具调用</span></div>` +
            `<div class="ci-body">${textToHtml(narrative)}</div>`;
          chainEl.appendChild(wrap);
          hasProcess = true;
        }
        answerBuf = "";
        answerBody.textContent = "";
        finalEl.hidden = true;
      }
      // action === "finish"：最终回答就是流式内容本身，不再渲染重复卡片
      return;
    }

    const item = buildChainItem(ev, msgEl);
    if (item) { chainEl.appendChild(item); hasProcess = true; }
  });

  // 思考面板：只有真实 reasoning 才存在；运行中展开，完成后自动折叠
  const panel = msgEl._thinkPanel;
  if (panel) {
    if (!state.busy && msgEl.dataset.runId !== state.currentRunId) panel.open = false;
  }

  if (!hasProcess && !reasoningBuf && !answerBuf) {
    chainEl.innerHTML = `<div class="chain-empty">正在连接模型…</div>`;
  } else if (!hasProcess && !reasoningBuf) {
    chainEl.innerHTML = "";
  }
}

function renderRunSummary(result) {
  if (!result || result.mode !== "multiagent") return "";
  const morphology = result.morphology || {};
  const architecture = result.architecture || {};
  const agents = result.agents || [];
  const report = result.contribution_report || {};
  const adjustment = result.architecture_adjustment || {};
  const operations = adjustment.operations || [];
  const roleNames = (architecture.roles || []).map(role => role.name).join("、") || "未返回";
  const contributionRows = (report.agents || []).map(item =>
    `<div class="metric-row"><span>${escapeHtml(item.agent_id)}</span><span>边际 ${item.marginal_contribution ?? "—"} · 纠错 ${item.error_correction ?? "—"} · 冗余 ${item.redundancy ?? "—"}</span></div>`
  ).join("");
  const operationText = operations.map(item => {
    const target = item.agents ? item.agents.join(" + ") : (item.agent_id || item.role || "架构");
    return `${item.action}: ${target}（${item.reason || ""}）`;
  }).join("；") || "保持当前架构";
  return `<details class="run-summary"><summary>🧬 查看自适应多 Agent 报告</summary>` +
    `<div class="summary-grid">` +
      `<div><span class="summary-label">任务形态</span><strong>${escapeHtml(morphology.task_kind || "general")}</strong></div>` +
      `<div><span class="summary-label">复杂度</span><strong>${escapeHtml(morphology.complexity || "—")}</strong></div>` +
      `<div><span class="summary-label">执行角色</span><strong>${agents.length} 个</strong></div>` +
      `<div><span class="summary-label">架构策略</span><strong>${escapeHtml(architecture.strategy || "—")}</strong></div>` +
    `</div>` +
    `<div class="summary-section"><span class="summary-label">角色分工</span><div>${escapeHtml(roleNames)}</div></div>` +
    (contributionRows ? `<div class="summary-section"><span class="summary-label">因果贡献代理指标</span>${contributionRows}</div>` : "") +
    `<div class="summary-section"><span class="summary-label">下一轮建议</span><div>${escapeHtml(operationText)}</div></div>` +
    `<div class="summary-note">建议状态：${escapeHtml(adjustment.requires_human_approval ? "等待人工确认" : "可应用")}</div>` +
  `</details>`;
}

function setStatusText(msgEl, text) {
  const status = msgEl.querySelector(".status-text");
  if (status) status.textContent = text;
}

function finishMessage(msgEl, run) {
  const statusLine = msgEl.querySelector(".status-line");
  const finalEl = msgEl.querySelector(".final-answer");
  const meta = statusMeta(run.status);
  const spinner = msgEl.querySelector(".spinner");
  if (spinner) spinner.remove();
  const result = run.result || {};

  // 运行结束：思考面板自动折叠（保留内容可展开回看）
  const panel = msgEl._thinkPanel;
  if (panel) panel.open = false;
  msgEl.classList.add("done");

  if (result.answer) {
    finalEl.hidden = false;
    // 首尾 trim：模型回答常以换行开头，pre-wrap 下会渲染成顶部空行
    finalEl.innerHTML = `<div class="answer-body">${textToHtml(result.answer.trim())}</div>` + renderRunSummary(result);
  } else if (run.status === "failed") {
    finalEl.hidden = false;
    finalEl.innerHTML = `<div class="answer-body error-text">任务未成功完成：${escapeHtml(result.error || run.result?.error || "未知错误")}</div>`;
  }
  // 完成态：移除顶部状态行与空的执行过程容器，底部仅保留状态小字
  if (statusLine) statusLine.remove();
  const chainEl = msgEl.querySelector(".chain");
  if (chainEl && !chainEl.querySelector(".chain-item, .thinking")) chainEl.hidden = true;
  const metaLine = document.createElement("div");
  metaLine.className = "msg-time";
  metaLine.innerHTML = `<span class="pill ${meta.cls}" style="font-size:10.5px">${meta.label}</span>`;
  msgEl.querySelector(".msg-col").appendChild(metaLine);
  if (run.run_id === state.currentRunId) {
    state.busy = false;
    setComposerDisabled(false);
    setChatHeader(document.getElementById("chat-title")?.textContent || "当前对话", "任务已完成，可以继续追问");
  }
}

async function fetchEvents(runId) {
  const response = await api(`/v1/runs/${runId}/events`);
  return response.ok && Array.isArray(response.data) ? response.data : [];
}

async function refreshRun(msgEl, runId = state.currentRunId) {
  if (!runId || !msgEl) return;
  const { ok, data } = await api(`/v1/runs/${runId}`);
  if (!ok || !data) return;
  renderEventsInto(msgEl, await fetchEvents(runId));
  const status = data.status;
  if (status === "queued") setStatusText(msgEl, "排队中…");
  else if (status === "running") setStatusText(msgEl, "调用 LLM 中…");
  else setStatusText(msgEl, statusMeta(status).label);

  if (["completed", "passed", "failed"].includes(status)) {
    if (runId === state.currentRunId) stopPolling();
    finishMessage(msgEl, data);
    await loadHistory();
  }
  scrollBottom();
}

// ---------- 提交任务 ----------
async function submitTask(taskText) {
  if (state.busy || !taskText) return;
  const workspaceId = document.getElementById("workspace-input").value.trim() || "default";
  const mode = document.getElementById("agent-mode").value;
  state.busy = true;
  setComposerDisabled(true);
  addUserMessage(taskText);
  setChatHeader(taskText, `${mode === "multiagent" ? "自适应多 Agent" : "单 Agent"} · 正在执行`);

  try {
    const { ok, data } = await api("/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task: taskText,
        workspace_id: workspaceId,
        mode,
        conversation_id: state.currentConversationId,
      }),
    });
    if (!ok) throw new Error(data && data.error ? data.error : "提交失败");
    state.currentConversationId = data.conversation_id;
    state.currentRunId = data.run_id;
    const msgEl = addAssistantMessage(data.run_id);
    state.currentMessageEl = msgEl;
    await loadHistory();
    await refreshRun(msgEl, data.run_id);
    startPolling(msgEl, data.run_id);
  } catch (e) {
    state.busy = false;
    setComposerDisabled(false);
    const message = addAssistantMessage(null);
    message.querySelector(".chain").innerHTML = `<div class="chain-item tool err"><div class="ci-head err"><span class="ci-icon">✕</span><span class="ci-title">提交失败</span></div><div class="ci-body">${escapeHtml(e.message)}</div></div>`;
    const spinner = message.querySelector(".spinner");
    if (spinner) spinner.remove();
    setStatusText(message, "失败");
  }
}

// ---------- 加载完整会话 ----------
async function loadConversationIntoChat(conversationId) {
  stopPolling();
  state.currentConversationId = conversationId;
  state.currentRunId = null;
  state.currentMessageEl = null;
  state.busy = false;
  setComposerDisabled(false);
  const { ok, data } = await api(`/v1/conversations/${conversationId}`);
  if (!ok || !data) return;

  messagesEl.innerHTML = "";
  const runs = data.runs || [];
  setChatHeader(runs[0]?.task || "历史对话", `${runs.length} 次任务 · 可继续追问`);
  let activeRun = null;
  let activeMessage = null;
  for (const run of runs) {
    addUserMessage(run.task || "(无描述)");
    const message = addAssistantMessage(run.run_id);
    renderEventsInto(message, await fetchEvents(run.run_id));
    if (["completed", "passed", "failed"].includes(run.status)) {
      finishMessage(message, run);
    } else {
      activeRun = run;
      activeMessage = message;
    }
  }
  await loadHistory();
  if (activeRun && activeMessage) {
    state.currentRunId = activeRun.run_id;
    state.currentMessageEl = activeMessage;
    state.busy = true;
    setComposerDisabled(true);
    startPolling(activeMessage, activeRun.run_id);
  }
  scrollBottom();
}

// ---------- 轮询 ----------
function startPolling(msgEl, runId) {
  stopPolling();
  state.currentRunId = runId;
  state.currentMessageEl = msgEl;
  state.pollTimer = setInterval(async () => {
    if (!state.currentRunId || state.currentRunId !== runId || state.polling) return;
    state.polling = true;
    try { await refreshRun(msgEl, runId); } finally { state.polling = false; }
  }, 400);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
  state.polling = false;
}

// ---------- 输入框交互 ----------
function setComposerDisabled(disabled) {
  sendBtn.disabled = disabled;
  promptInput.disabled = disabled;
  document.getElementById("agent-mode").disabled = disabled;
  document.getElementById("workspace-input").disabled = disabled;
}

function autoGrow() {
  promptInput.style.height = "auto";
  promptInput.style.height = Math.min(promptInput.scrollHeight, 160) + "px";
}

function send() {
  const text = promptInput.value.trim();
  if (!text || state.busy) return;
  promptInput.value = "";
  autoGrow();
  submitTask(text);
}

sendBtn.addEventListener("click", send);
promptInput.addEventListener("input", autoGrow);
promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});

document.getElementById("new-chat").addEventListener("click", resetChat);

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
  bindChips();
  await loadInfo();
  await loadHistory();
})();
