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
    case "cancelling": return { cls: "pill-run", label: "停止中" };
    case "cancelled": return { cls: "pill-off", label: "已停止" };
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

// ---------- 本地持久化：工作空间 / Agent 模式在同会话内保持，除非手动更换 ----------
const LS_WS_PATH = "metamorph.ws_path";
const LS_WS_ID = "metamorph.ws_id";
const LS_AGENT_MODE = "metamorph.agent_mode";

function lsGet(key, fallback = "") {
  try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
}
function lsSet(key, val) {
  try { localStorage.setItem(key, val); } catch (e) { /* 隐私模式等忽略 */ }
}
function lsRemove(key) {
  try { localStorage.removeItem(key); } catch (e) {}
}

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
  setSendMode("send");
  clearPendingImages();
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
    if (modeSelect) {
      // 优先恢复用户上次选择，其次用后端默认
      const saved = lsGet(LS_AGENT_MODE);
      modeSelect.value = (saved && ["single", "multiagent"].includes(saved)) ? saved : data.mode;
    }
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
function addUserMessage(text, images = []) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "msg user";
  const time = new Date().toTimeString().slice(0, 5);
  const imgsHtml = images.length
    ? `<div class="msg-imgs">` + images.map((img) =>
        `<img src="${img.dataUrl}" class="msg-img" alt="${escapeHtml(img.name)}" title="${escapeHtml(img.name)}" />`
      ).join("") + `</div>`
    : "";
  div.innerHTML =
    `<div class="msg-col">` +
      imgsHtml +
      (text ? `<div class="bubble">${textToHtml(text)}</div>` : `<div class="bubble">[图片]</div>`) +
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

// ---------- 执行过程卡片 ----------
// 工具元数据：图标 + 动作词 + 目标摘要提取
const TOOL_META = {
  read_document: { icon: "📖", action: "读取", pick: (a) => a.path },
  web_search: { icon: "🔍", action: "检索", pick: (a) => a.query },
  web_fetch: { icon: "🌐", action: "抓取", pick: (a) => a.url },
  update_user_memory: { icon: "🧠", action: "更新记忆", pick: () => "" },
  update_task_list: { icon: "📋", action: "任务清单", pick: () => "" },
};

function buildToolRow(tool, args, ok, output) {
  const meta = TOOL_META[tool] || { icon: "🔧", action: tool, pick: () => "" };
  let target = "";
  try { target = String(meta.pick(args) || ""); } catch (e) { target = ""; }
  const wrap = document.createElement("div");
  wrap.className = "tool-row";
  const line = document.createElement("div");
  line.className = "tr-line" + (ok ? "" : " err");
  line.innerHTML =
    `<span class="tr-icon">${meta.icon}</span>` +
    `<span class="tr-action">${escapeHtml(meta.action)}</span>` +
    (target ? `<span class="tr-target">${escapeHtml(target)}</span>` : "") +
    `<span class="tr-status">${ok ? "✓" : "✕"}</span>`;
  const detail = document.createElement("div");
  detail.className = "tr-detail";
  detail.hidden = true;
  let argStr = "";
  try { argStr = JSON.stringify(args); } catch (e) { argStr = String(args); }
  const shown = output.slice(0, 800) + (output.length > 800 ? "…" : "");
  detail.innerHTML =
    `<div class="ci-args">参数: ${escapeHtml(argStr)}</div>` +
    (shown ? `<div class="ci-out">${escapeHtml(shown)}</div>` : "");
  line.addEventListener("click", () => { detail.hidden = !detail.hidden; });
  wrap.appendChild(line);
  wrap.appendChild(detail);
  return wrap;
}

function buildTaskListCard(tasksJson) {
  let tasks = [];
  try { tasks = JSON.parse(tasksJson) || []; } catch (e) { tasks = []; }
  if (!Array.isArray(tasks) || tasks.length === 0) return null;
  const done = tasks.filter((t) => t.status === "completed").length;
  const wrap = document.createElement("div");
  wrap.className = "tasklist";
  const statusIcon = { completed: "✓", in_progress: "▶", pending: "○" };
  wrap.innerHTML =
    `<div class="tl-head"><span class="tl-icon">☰</span>任务清单 ` +
    `<span class="tl-count">${done}/${tasks.length} 完成</span></div>` +
    `<div class="tl-items">` +
    tasks.map((t) => {
      const cls = t.status === "completed" ? " done" : (t.status === "in_progress" ? " doing" : "");
      return `<div class="tl-item${cls}"><span class="tl-status">${statusIcon[t.status] || "○"}</span>` +
        `<span class="tl-text">${escapeHtml(String(t.content || ""))}</span></div>`;
    }).join("") +
    `</div>`;
  return wrap;
}

function buildChainItem(ev, msgEl) {
  const type = ev.type || "event";

  if (type === "reasoning" || type === "model.decision") {
    // reasoning 与 model.decision 由 renderEventsInto 统一处理（需要跨事件维护流式缓冲）
    return null;
  }

  if (type === "tool.completed") {
    const ok = !!(ev.result && ev.result.ok);
    const out = ev.result && ev.result.output ? String(ev.result.output) : "";
    const err = ev.result && ev.result.error ? String(ev.result.error) : "";
    const args = ev.arguments || {};

    // 任务清单工具 → Task List 卡片
    if (ev.tool === "update_task_list") {
      return buildTaskListCard(args.tasks_json || "");
    }

    // 其他工具 → 单行条目，点击展开参数与输出
    return buildToolRow(ev.tool || "", args, ok, err || out);
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
    const cancelled = agent.metrics && agent.metrics.cancelled;
    const label = cancelled ? "已取消" : (agent.success ? "已完成角色任务" : "角色执行失败");
    wrap.innerHTML = `<div class="ci-head"><span class="ci-icon">👤</span><span class="ci-title">${escapeHtml(agent.role || agent.agent_id || "Agent")}</span></div>` +
      `<div class="ci-body">${label}</div>`;
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
        // 工具轮：模型叙述渲染为思考段落（无边框浅色文本，像思考流）
        const narrative = answerBuf.trim();
        if (narrative) {
          const para = document.createElement("div");
          para.className = "chain-thought";
          para.textContent = narrative;
          chainEl.appendChild(para);
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
    setSendMode("send");
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
  if (!ok || !data) {
    // run 丢失（如服务重启导致内存态清空且磁盘无记录）：停止轮询并收尾，避免无限轮询
    if (runId === state.currentRunId) {
      stopPolling();
      setStatusText(msgEl, "已中断");
      finishMessage(msgEl, {
        run_id: runId,
        status: "failed",
        result: { error: "运行记录丢失（服务可能已重启），请重新提交任务" },
      });
    }
    return;
  }
  // 先判断终态，再渲染事件：即使渲染抛异常，轮询也能正常停止
  const status = data.status;
  const TERMINAL = ["completed", "passed", "failed", "cancelled"];
  if (TERMINAL.includes(status)) {
    if (runId === state.currentRunId) stopPolling();
  }
  try {
    renderEventsInto(msgEl, await fetchEvents(runId));
  } catch (e) { /* 渲染失败不影响轮询收敛 */ }
  if (status === "queued") setStatusText(msgEl, "排队中…");
  else if (status === "running") setStatusText(msgEl, "调用 LLM 中…");
  else if (status === "cancelling") setStatusText(msgEl, "正在停止…");
  else setStatusText(msgEl, statusMeta(status).label);

  if (TERMINAL.includes(status)) {
    finishMessage(msgEl, data);
    await loadHistory();
  }
  scrollBottom();
}

// ---------- 图片上传 ----------
const pendingImages = [];  // [{name, dataUrl}]

function renderImgPreviews() {
  const box = document.getElementById("img-previews");
  if (!pendingImages.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = pendingImages.map((img, idx) =>
    `<div class="img-chip"><img src="${img.dataUrl}" alt="${escapeHtml(img.name)}" title="${escapeHtml(img.name)}" />` +
    `<button class="img-chip-del" data-idx="${idx}" title="移除">✕</button></div>`
  ).join("");
  box.querySelectorAll(".img-chip-del").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingImages.splice(Number(btn.dataset.idx), 1);
      renderImgPreviews();
    });
  });
}

function clearPendingImages() {
  pendingImages.length = 0;
  renderImgPreviews();
}

function handleImageFiles(fileList) {
  const files = Array.from(fileList || []).slice(0, 6 - pendingImages.length);
  files.forEach((file) => {
    if (!file.type.startsWith("image/")) return;
    if (file.size > 10 * 1024 * 1024) return;  // 与后端 10MB 上限一致
    const reader = new FileReader();
    reader.onload = () => {
      pendingImages.push({ name: file.name, dataUrl: reader.result });
      renderImgPreviews();
    };
    reader.readAsDataURL(file);
  });
}

// ---------- 本地文件夹选择（工作空间） ----------
const fsModal = document.getElementById("fs-modal");
let fsCurrentPath = "";      // 弹层中当前浏览的目录
let selectedWsPath = lsGet(LS_WS_PATH, "");  // 已确认的工作空间路径（刷新后恢复）

function updateWsUi() {
  const label = document.getElementById("ws-path-label");
  const clearBtn = document.getElementById("ws-clear-btn");
  const defaultLabel = document.getElementById("ws-default-label");
  const wsInput = document.getElementById("workspace-input");
  if (selectedWsPath) {
    label.textContent = selectedWsPath;
    label.title = selectedWsPath;
    label.hidden = false;
    clearBtn.hidden = false;
    defaultLabel.hidden = true;
    wsInput.hidden = true;
  } else {
    label.hidden = true;
    clearBtn.hidden = true;
    defaultLabel.hidden = false;
    wsInput.hidden = false;
  }
}

function fsBreadcrumb(path) {
  const el = document.getElementById("fs-breadcrumb");
  el.innerHTML = "";
  const rootBtn = document.createElement("button");
  rootBtn.className = "fs-crumb";
  rootBtn.textContent = "此电脑";
  rootBtn.addEventListener("click", () => fsNavigate(""));
  el.appendChild(rootBtn);
  if (!path) return;
  // 按 \ 分段生成可点击层级（保留盘符冒号）
  const parts = path.split("\\").filter(Boolean);
  let acc = "";
  parts.forEach((part, idx) => {
    acc = idx === 0 ? `${part}\\` : `${acc}\\${part}`;
    const sep = document.createElement("span");
    sep.className = "fs-crumb-sep";
    sep.textContent = "›";
    el.appendChild(sep);
    const btn = document.createElement("button");
    btn.className = "fs-crumb" + (idx === parts.length - 1 ? " current" : "");
    btn.textContent = part;
    btn.addEventListener("click", () => fsNavigate(acc));
    el.appendChild(btn);
  });
}

async function fsNavigate(path) {
  const listEl = document.getElementById("fs-list");
  listEl.innerHTML = `<div class="fs-empty">加载中…</div>`;
  const { ok, data } = await api(`/v1/fs/list?path=${encodeURIComponent(path)}`);
  if (!ok || !data) { listEl.innerHTML = `<div class="fs-empty">目录不可访问</div>`; return; }
  fsCurrentPath = data.path || "";
  fsBreadcrumb(fsCurrentPath);
  document.getElementById("fs-current").textContent = fsCurrentPath || "此电脑（选择盘符）";
  listEl.innerHTML = "";
  if (!fsCurrentPath) document.getElementById("fs-current").textContent = "";
  const entries = data.entries || [];
  if (entries.length === 0) {
    listEl.innerHTML = `<div class="fs-empty">此目录下没有子文件夹</div>`;
    return;
  }
  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "fs-item";
    item.innerHTML = `<span class="fs-item-icon">📁</span><span class="fs-item-name">${escapeHtml(entry.name)}</span>`;
    item.addEventListener("click", () => fsNavigate(entry.path));
    listEl.appendChild(item);
  });
}

function openFsModal() {
  fsModal.hidden = false;
  fsNavigate("");
}

function closeFsModal() {
  fsModal.hidden = true;
}

// ---------- 提交任务 ----------
async function submitTask(taskText) {
  if (state.busy || (!taskText && !pendingImages.length)) return;
  const workspaceId = document.getElementById("workspace-input").value.trim() || "default";
  const mode = document.getElementById("agent-mode").value;
  state.busy = true;
  setComposerDisabled(true);
  setChatHeader(taskText || "[图片]", `${mode === "multiagent" ? "自适应多 Agent" : "单 Agent"} · 正在执行`);

  const attached = pendingImages.map((p) => ({ name: p.name, dataUrl: p.dataUrl }));

  try {
    // 先上传图片（若有）：保存到工作空间 uploads/ 目录
    let savedImages = [];
    if (attached.length) {
      const upBody = { files: attached.map((p) => ({ name: p.name, data_base64: p.dataUrl })) };
      if (selectedWsPath) upBody.workspace_path = selectedWsPath;
      else upBody.workspace_id = workspaceId;
      const up = await api("/v1/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(upBody),
      });
      if (!up.ok) throw new Error(up.data && up.data.error ? up.data.error : "图片上传失败");
      savedImages = up.data.saved || [];
    }

    // 任务文本附加图片保存位置，模型可通过文件名感知上传内容
    let fullTask = taskText;
    if (savedImages.length) {
      fullTask = (fullTask ? fullTask + "\n" : "") +
        `（用户随任务上传了 ${savedImages.length} 张图片，已保存到工作空间：` +
        savedImages.map((s) => s.saved_path).join("、") + "）";
    }
    addUserMessage(taskText, attached);
    clearPendingImages();

    const bodyPayload = {
      task: fullTask,
      mode,
      conversation_id: state.currentConversationId,
    };
    if (selectedWsPath) bodyPayload.workspace_path = selectedWsPath;
    else bodyPayload.workspace_id = workspaceId;

    const { ok, data } = await api("/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyPayload),
    });
    if (!ok) throw new Error(data && data.error ? data.error : "提交失败");
    state.currentConversationId = data.conversation_id;
    state.currentRunId = data.run_id;
    const msgEl = addAssistantMessage(data.run_id);
    state.currentMessageEl = msgEl;
    setSendMode("stop");
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
    if (["completed", "passed", "failed", "cancelled"].includes(run.status)) {
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
    setSendMode("stop");
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
  promptInput.disabled = disabled;
  document.getElementById("agent-mode").disabled = disabled;
  document.getElementById("workspace-input").disabled = disabled;
  document.getElementById("upload-img-btn").disabled = disabled;
}

// 发送按钮双态：空闲=发送 ↑，运行中=停止 ⏹
function setSendMode(mode) {
  if (mode === "stop") {
    sendBtn.textContent = "⏹";
    sendBtn.title = "停止当前任务";
    sendBtn.classList.add("stopping");
    sendBtn.disabled = false;
  } else {
    sendBtn.textContent = "↑";
    sendBtn.title = "发送";
    sendBtn.classList.remove("stopping");
    sendBtn.disabled = false;
  }
}

async function stopCurrentRun() {
  if (!state.currentRunId) return;
  try { await api(`/v1/tasks/${state.currentRunId}/cancel`, { method: "POST" }); } catch (e) { /* 轮询会反映最终状态 */ }
  setStatusText(state.currentMessageEl, "正在停止…");
}

function autoGrow() {
  promptInput.style.height = "auto";
  promptInput.style.height = Math.min(promptInput.scrollHeight, 160) + "px";
}

function send() {
  const text = promptInput.value.trim();
  if ((!text && !pendingImages.length) || state.busy) return;
  promptInput.value = "";
  autoGrow();
  submitTask(text);
}

sendBtn.addEventListener("click", () => {
  if (state.busy && state.currentRunId) { stopCurrentRun(); return; }
  send();
});
promptInput.addEventListener("input", autoGrow);

// Agent 模式切换：持久化用户选择
document.getElementById("agent-mode").addEventListener("change", (event) => {
  lsSet(LS_AGENT_MODE, event.target.value);
});

// 工作空间 ID 输入：持久化用户输入（未选择文件夹时用）
document.getElementById("workspace-input").addEventListener("change", (event) => {
  lsSet(LS_WS_ID, event.target.value.trim() || "default");
});

// ---------- 图片上传事件绑定 ----------
document.getElementById("upload-img-btn").addEventListener("click", () => {
  document.getElementById("img-file-input").click();
});
document.getElementById("img-file-input").addEventListener("change", (event) => {
  handleImageFiles(event.target.files);
  event.target.value = "";  // 允许重复选择同一文件
});
promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});

document.getElementById("new-chat").addEventListener("click", resetChat);

// ---------- 文件夹选择事件绑定 ----------
document.getElementById("pick-folder-btn").addEventListener("click", openFsModal);
document.getElementById("fs-close-btn").addEventListener("click", closeFsModal);
document.getElementById("fs-select-btn").addEventListener("click", () => {
  if (!fsCurrentPath) return;
  selectedWsPath = fsCurrentPath;
  lsSet(LS_WS_PATH, selectedWsPath);
  updateWsUi();
  closeFsModal();
});
document.getElementById("ws-clear-btn").addEventListener("click", () => {
  selectedWsPath = "";
  lsRemove(LS_WS_PATH);
  updateWsUi();
});
// 点击遮罩关闭
fsModal.addEventListener("click", (event) => {
  if (event.target === fsModal) closeFsModal();
});

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
  // 恢复工作空间（路径或默认 ID）的 UI 显示
  const wsInput = document.getElementById("workspace-input");
  const savedWsId = lsGet(LS_WS_ID);
  if (wsInput && savedWsId) wsInput.value = savedWsId;
  updateWsUi();
  await loadInfo();
  await loadHistory();
})();
