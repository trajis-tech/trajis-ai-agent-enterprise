const state = {
  mode: "agent",
  chatMode: "general",
  sessionId: sessionStorage.getItem("agentSession") || "",
  files: [],
  selectedFile: null,
  hydrated: false,
  project: null,
  turnId: null,
  approvalId: null,
  abort: null,
  busy: false,
  n8nReady: false,
  n8nReason: "",
  automation: { installed: false, running: false, reason: "" },
  search: { enabled: false, configured: false },
  gateway: { hasKey: false, displayName: "", requestUrl: "" },
};

const FETCH_TIMEOUT_MS = 20000;
const CHAT_TIMEOUT_MS = 180000;

function $(id) {
  return document.getElementById(id);
}

function setStatus(text, kind) {
  state.statusUntil = Date.now() + (kind === "err" ? 30000 : 5000);
  const el = $("statusText");
  const dot = $("statusDot");
  if (el) el.textContent = text;
  if (dot) dot.className = "status-indicator" + (kind ? " is-" + kind : "");
}

function closeMenus() {
  document.querySelectorAll(".toolbar-menu").forEach((m) => { m.hidden = true; });
  document.querySelectorAll(".toolbar-btn").forEach((btn) => {
    btn.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
  });
}

function showError(id, message) {
  const el = $(id);
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
}

function withTimeout(ms, signal) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new DOMException("timeout", "AbortError")), ms);
  if (signal) {
    if (signal.aborted) ac.abort(signal.reason);
    else signal.addEventListener("abort", () => ac.abort(signal.reason), { once: true });
  }
  return { signal: ac.signal, cancel: () => clearTimeout(timer) };
}

async function api(path, opts) {
  opts = opts || {};
  const timeout = withTimeout(opts.timeoutMs || FETCH_TIMEOUT_MS, opts.signal);
  try {
    const headers = new Headers(opts.headers || {});
    if (state.sessionId) headers.set("X-Agent-Session", state.sessionId);
    const res = await fetch(path, { ...opts, headers, signal: timeout.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  } catch (err) {
    if (err && err.name === "AbortError") throw new Error("連線逾時，請再試一次");
    throw err;
  } finally {
    timeout.cancel();
  }
}

function switchMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-segment-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.mode === mode);
    btn.setAttribute("aria-pressed", String(btn.dataset.mode === mode));
  });
  ["agent", "n8n", "files"].forEach((name) => {
    const el = $("view-" + name);
    if (!el) return;
    const on = name === mode;
    el.hidden = !on;
    el.classList.toggle("is-active", on);
  });
  if (mode === "n8n") loadN8n();
  if (mode === "files") loadFiles();
}

function updateSetupBanner() {
  const banner = $("setupBanner");
  if (!banner) return;
  const hasProject = Boolean(state.project && state.project.folder);
  const hasKey = Boolean(state.gateway && state.gateway.hasKey);
  if (hasProject && hasKey) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  if (!hasProject) {
    $("setupTitle").textContent = "先開啟專案";
    $("setupText").textContent = "Agent 只能改目前專案。新增後會建立 5碼-草稿，之後可再命名。";
  } else if (!hasKey) {
    $("setupTitle").textContent = "專案已就緒，請設定閘道";
    $("setupText").textContent = "尚未設定 API Key。設定閘道後即可開始 AI 工作。你也可以先到專案分頁匯入資料。";
  }
}

function renderSide() {
  $("sideProject").textContent = state.project ? state.project.folder : "未開啟";
  if (state.gateway && state.gateway.hasKey) {
    $("sideGateway").textContent = (state.gateway.displayName || "已設定") + " · 有金鑰";
  } else {
    $("sideGateway").textContent = "尚未設定金鑰";
  }
  const reasons = { "not started": "尚未啟動", starting: "啟動中", stopping: "停止中", stopped: "已停止", unavailable: "無法連線" };
  $("sideN8n").textContent = state.n8nReady ? "就緒" : (reasons[state.n8nReason] || state.n8nReason || "未就緒");
  $("sideMode").textContent = {general: "一般", plan: "計畫", ask: "唯讀"}[state.chatMode] || state.chatMode;
  const auto = state.automation || {};
  $("sideOpenRpa").textContent = auto.installed ? (auto.running ? "執行器已啟動" : "已安裝 · 執行時啟動") : (auto.reason || "runtime 未就緒");
  const search = state.search || {};
  $("sideSearch").textContent = search.enabled ? "已啟用" : (search.configured ? "已設定未啟用" : "未設定");
  $("sideTurn").textContent = state.turnId || "—";
}

function renderProject() {
  const has = Boolean(state.project && state.project.folder);
  $("sendBtn").disabled = !has || state.busy;
  $("chatInput").disabled = !has || state.busy;
  $("chatHint").textContent = has
    ? "檔案存於本機；對話與必要內容會送往模型閘道"
    : "請先新增或開啟專案，才能送出訊息";
  if (!has) {
    $("projectName").textContent = "尚未開啟專案";
    $("projectMeta").textContent = "請新增或開啟專案後再下指令";
    $("footerProject").textContent = "未開啟專案";
    $("filesEmpty").hidden = false;
    $("filesPane").hidden = true;
    $("filesEmptyText").textContent = "開啟專案後，這裡會列出專案檔案。";
  } else {
    $("projectName").textContent = state.project.folder;
    $("projectMeta").textContent = state.project.path || "";
    $("footerProject").textContent = state.project.folder;
  }
  $("undoBtn").disabled = !state.turnId || state.busy || state.chatMode !== "general";
  document.querySelectorAll('[data-action="newProject"], [data-action="openProject"]').forEach(b => { b.disabled = state.busy; });
  updateSetupBanner();
  renderSide();
}

function bindUi() {
  document.querySelectorAll(".mode-segment-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchMode(btn.dataset.mode));
  });
  document.querySelectorAll("[data-mode-jump]").forEach((btn) => {
    btn.addEventListener("click", () => switchMode(btn.dataset.modeJump));
  });

  document.querySelectorAll("[data-menu]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const menu = $("menu-" + btn.dataset.menu);
      if (!menu) return;
      const willOpen = menu.hidden;
      closeMenus();
      if (willOpen) {
        menu.hidden = false;
        btn.classList.add("is-open");
        btn.setAttribute("aria-expanded", "true");
      }
    });
  });

  document.addEventListener("click", () => closeMenus());
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeMenus();
  });

  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      closeMenus();
      handleAction(btn.dataset.action);
    });
  });

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dlg = btn.closest("dialog");
      if (dlg) dlg.close();
    });
  });

  $("createProjectBtn").addEventListener("click", createProject);
  $("saveGatewayBtn").addEventListener("click", saveGateway);
  $("openN8nBtn").addEventListener("click", () => switchMode("n8n"));
  $("fileSearch").addEventListener("input", renderFiles);
  $("importFiles").addEventListener("change", importFiles);
  $("downloadFileBtn").addEventListener("click", () => download("/api/files/download?path=" + encodeURIComponent(state.selectedFile), state.selectedFile.split("/").pop()).catch(err => setStatus(err.message, "err")));
  $("saveN8nKeyBtn").addEventListener("click", saveN8nKey);
  document.querySelectorAll("[data-prompt]").forEach(b => b.addEventListener("click", () => {
    $("chatInput").value = b.dataset.prompt; $("chatInput").focus();
  }));
  $("refreshFilesBtn").addEventListener("click", () => loadFiles());
  $("undoBtn").addEventListener("click", undoTurn);
  $("chatInput").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229) {
      ev.preventDefault();
      $("chatForm").requestSubmit();
    }
  });
  $("chatForm").addEventListener("submit", onChatSubmit);
  $("abortBtn").addEventListener("click", () => {
    if (state.abort) state.abort.abort();
  });
  $("approveBtn").addEventListener("click", () => resolveApproval("approve"));
  $("denyBtn").addEventListener("click", () => resolveApproval("deny"));
}

async function handleAction(action) {
  try {
    if (state.busy && ["newProject", "openProject"].includes(action)) return;
    if (action === "newProject") await openProjectDialog("new");
    else if (action === "openProject") await openProjectDialog("open");
    else if (action === "exportProject") await exportProject();
    else if (action === "openGateway") {
      await loadGateway();
      $("dlgGateway").showModal();
    } else if (action === "n8nKey") {
      $("dlgN8nKey").showModal();
    } else if (action === "openPrivacy") {
      window.alert("對話存在本機 .runtime/state.db；API key 在 app/config。Agent 看不到 .runtime。");
    } else if (action === "n8nRestart" || action === "n8nStop") {
      setStatus(action === "n8nStop" ? "正在停止 n8n" : "正在啟動 n8n", "busy");
      await api("/api/n8n", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action === "n8nStop" ? "stop" : "restart" }),
        timeoutMs: 60000,
      });
      await refreshStatus();
    } else if (action === "openHelp") {
      $("dlgHelp").showModal();
    }
  } catch (err) {
    setStatus(err.message || "操作失敗", "err");
  }
}

async function download(url, name) {
  const res = await fetch(url, { headers: { "X-Agent-Session": state.sessionId } });
  if (!res.ok) throw new Error((await res.json()).error || "下載失敗");
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

async function exportProject() {
  if (!state.project) throw new Error("請先開啟專案");
  await download("/api/files/export", state.project.folder + ".zip");
  setStatus("專案 ZIP 已下載", "ok");
}

async function importFiles() {
  const files = Array.from($("importFiles").files);
  if (!files.length || !state.project || state.busy) return;
  setBusy(true);
  try {
    for (const file of files) {
      if (file.size > 20 * 1024 * 1024) throw new Error(file.name + " 超過 20 MB");
      setStatus("正在匯入 " + file.name, "busy");
      const data = await api("/api/files/import?path=" + encodeURIComponent(file.name), { method: "POST", body: file });
      state.turnId = data.turn_id;
    }
    setStatus("檔案已匯入", "ok");
  } catch (err) { setStatus(err.message, "err"); }
  finally { $("importFiles").value = ""; setBusy(false); await loadFiles(); }
}

async function adoptProject(project) {
  state.project = project;
  state.sessionId = project.session_id;
  sessionStorage.setItem("agentSession", state.sessionId);
  state.turnId = null; state.approvalId = null; state.selectedFile = null;
  $("approvalCard").hidden = true;
  $("filePreview").textContent = "選取檔案以預覽";
  $("chatLog").replaceChildren();
  await hydrateSession();
  renderProject();
}

function renderChatMode() {
  $("undoBtn").disabled = !state.turnId || state.busy || state.chatMode !== "general";
  $("importFiles").disabled = state.busy || state.chatMode !== "general";
  $("chatMode").value = state.chatMode;
  $("chatMode").disabled = state.busy || !state.project;
  $("chatModeHint").textContent = {general: "可修改目前專案；發佈需批准", plan: "只分析與保存計畫，不修改專案或執行", ask: "只讀取與回答，不修改或執行"}[state.chatMode];
}

$("chatMode").addEventListener("change", async () => {
  const mode = $("chatMode").value;
  $("chatMode").disabled = true;
  try {
    const data = await api("/api/mode", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode})});
    state.chatMode = data.mode;
    await hydrateSession();
  } catch (err) { setStatus(err.message, "err"); }
  finally { renderChatMode(); }
});

async function hydrateSession() {
  const data = await api("/api/session");
  if (state.project) state.chatMode = (await api("/api/mode")).mode;
  renderChatMode();
  await loadPlans();
  $("chatLog").replaceChildren();
  for (const msg of data.messages || []) {
    if (msg.payload && msg.payload.content) addBubble(msg.role, msg.payload.content);
    if (msg.turn_id) state.turnId = msg.turn_id;
  }
  if (!$("chatLog").children.length) addBubble("system", "專案已就緒。匯入資料，或從下方選擇一個任務開始。");
  const pending = (data.pending || [])[0];
  state.approvalId = pending ? pending.approval_id : null;
  $("approvalCard").hidden = !pending;
  if (pending) $("approvalText").textContent = pending.notice || (pending.path + " · 僅發佈，不啟用流程");
  state.turnId = data.undo_turn_id || null;
  state.historyVersion = data.historyVersion;
  state.hydrated = true;
}

async function saveN8nKey() {
  showError("n8nKeyError", "");
  try {
    await api("/api/n8n", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "key", key: $("n8nApiKey").value }) });
    $("n8nApiKey").value = ""; $("dlgN8nKey").close();
    setStatus("n8n API Key 已儲存", "ok");
  } catch (err) { showError("n8nKeyError", err.message); }
}

async function openProjectDialog(intent) {
  $("dlgProjectTitle").textContent = intent === "new" ? "新增專案" : "開啟專案";
  $("projectListHint").textContent = intent === "new"
    ? "可直接新增；若要改開舊專案，點下方清單。"
    : "點選清單開啟，或改填主題後新增。";
  showError("projectError", "");
  try { await refreshProjects(); }
  catch (err) { showError("projectError", err.message || "無法列出專案"); }
  $("dlgProject").showModal();
  if (intent === "new") $("projectTopic").focus();
}

async function createProject() {
  showError("projectError", "");
  try {
    state.project = await api("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: $("projectTopic").value }),
    });
    await adoptProject(state.project);
    renderProject();
    addBubble("system", "已建立專案 " + state.project.folder + "。可以直接下指令。");
    $("dlgProject").close();
    setStatus("已開啟專案", "ok");
    switchMode("agent");
    $("chatInput").focus();
  } catch (err) {
    showError("projectError", err.message || "新增失敗");
  }
}

async function saveGateway() {
  showError("gatewayError", "");
  try {
    await api("/api/gateway", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKeyEncrypted: $("apiKey").value, requestUrl: $("gatewayEndpoint").value, model: $("gatewayModel").value, displayName: $("gatewayDisplayName").value }),
    });
    state.gateway.hasKey = Boolean($("apiKey").value) || state.gateway.hasKey;
    $("apiKey").value = "";
    $("dlgGateway").close();
    setStatus("閘道設定已儲存", "ok");
    await refreshStatus();
  } catch (err) {
    showError("gatewayError", err.message || "儲存失敗");
  }
}

async function loadGateway() {
  showError("gatewayError", "");
  try {
    const data = await api("/api/gateway");
    state.gateway = {
      hasKey: Boolean(data.hasKey),
      displayName: data.displayName || "",
      requestUrl: data.requestUrl || "",
    };
    $("gatewayName").textContent = data.displayName || data.requestUrl || "公司閘道";
    $("gatewayKeyState").textContent = data.hasKey ? "已設定金鑰" : "尚未設定金鑰";
    $("gatewayUrl").textContent = data.requestUrl || "";
    $("gatewayEndpoint").value = data.requestUrl || "";
    $("gatewayModel").value = (data.defaults || {}).model || "";
    $("gatewayDisplayName").value = data.displayName || "";
    $("apiKey").value = "";
  } catch (err) {
    $("gatewayName").textContent = "無法讀取閘道設定";
    $("gatewayKeyState").textContent = err.message;
    $("gatewayUrl").textContent = "";
  }
}

async function undoTurn() {
  if (!state.turnId) {
    setStatus("沒有可復原的回合", "err");
    return;
  }
  try {
    const result = await api("/api/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turn_id: state.turnId }),
    });
    state.turnId = null;
    renderProject();
    setStatus(result.restored.length ? "已復原本回合" : "此回合沒有檔案變更", "ok");
    addBubble("system", "已復原本回合檔案變更。");
    loadFiles();
  } catch (err) {
    setStatus(err.message || "復原失敗", "err");
  }
}

async function refreshProjects() {
  const data = await api("/api/projects");
  const box = $("projectList");
  const empty = $("projectListEmpty");
  box.innerHTML = "";
  const items = data.projects || [];
  empty.hidden = items.length > 0;
  items.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = p.folder;
    b.addEventListener("click", async () => {
      showError("projectError", "");
      try {
        state.project = await api("/api/projects/open", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder: p.folder }),
        });
        await adoptProject(state.project);
        renderProject();
        addBubble("system", "已開啟 " + state.project.folder + "。");
        $("dlgProject").close();
        setStatus("已開啟專案", "ok");
        switchMode("agent");
        $("chatInput").focus();
      } catch (err) {
        showError("projectError", err.message || "開啟失敗");
      }
    });
    box.appendChild(b);
  });
}

async function refreshStatus() {
  try {
    const data = await api("/api/status");
    state.project = data.project || null;
    if (state.project && (!state.hydrated || (data.historyVersion && data.historyVersion !== state.historyVersion))) await hydrateSession();
    if (data.gateway) {
      state.gateway = {
        hasKey: Boolean(data.gateway.hasKey),
        displayName: data.gateway.displayName || "",
        requestUrl: data.gateway.requestUrl || "",
      };
    }
    const n8n = data.n8n || {};
    state.n8nReady = Boolean(n8n.ready);
    state.n8nReason = n8n.reason || "unavailable";
    state.automation = data.automation || { installed: false, running: false, reason: "" };
    state.search = data.search || { enabled: false, configured: false };
    $("n8nDegraded").textContent = state.n8nReady
      ? "n8n 已就緒。"
      : ("n8n 目前無法使用：" + state.n8nReason + "。Agent 其餘功能仍可使用。");
    if (!state.n8nReady) {
      $("n8nFrame").hidden = true;
      if (($("n8nFrame").getAttribute("src") || "") !== "about:blank") {
        $("n8nFrame").src = "about:blank";
      }
    }
    renderProject();
    if (!state.busy && Date.now() > (state.statusUntil || 0)) {
      if (state.n8nReady) setStatus(state.project ? "就緒" : "待機", "ok");
      else setStatus(state.project ? "就緒（n8n 未啟動）" : "待機", state.project ? "ok" : "");
    }
    if (state.mode === "n8n") loadN8n();
  } catch (err) {
    setStatus(err.message || "無法連線後端", "err");
    renderProject();
  }
}

function loadN8n() {
  const frame = $("n8nFrame");
  const placeholder = $("n8nPlaceholder");
  if (!state.n8nReady) {
    placeholder.hidden = false;
    frame.hidden = true;
    return;
  }
  placeholder.hidden = true;
  frame.hidden = false;
  const src = frame.getAttribute("src") || "";
  if (!src || src === "about:blank") frame.src = "/n8n/";
}

async function loadFiles() {
  if (!state.project) return;
  try {
    const data = await api("/api/files");
    state.files = data.files || [];
    $("filesEmpty").hidden = true; $("filesPane").hidden = false;
    renderFiles();
  } catch (err) { setStatus(err.message, "err"); }
}

function renderFiles() {
  const query = $("fileSearch").value.toLowerCase();
  const files = state.files.filter(f => f.path.toLowerCase().includes(query));
  $("fileTree").replaceChildren();
  $("fileCount").textContent = files.length + " 個檔案";
  if (!files.length) {
    const empty = document.createElement("p"); empty.className = "muted";
    empty.textContent = query ? "找不到符合的檔案" : "尚無檔案，請匯入資料或請 Agent 建立。";
    $("fileTree").append(empty);
  }
  for (const f of files) {
    const b = document.createElement("button"); b.type = "button"; b.textContent = f.path;
    b.classList.toggle("is-active", state.selectedFile === f.path);
    b.addEventListener("click", async () => {
      state.selectedFile = f.path; renderFiles();
      $("filePreview").textContent = "正在讀取…";
      $("previewTitle").textContent = f.path;
      $("downloadFileBtn").disabled = false;
      try {
        const data = await api("/api/file?path=" + encodeURIComponent(f.path));
        if (state.selectedFile !== f.path) return;
        $("filePreview").textContent = data.binary ? "此檔案無法以文字預覽，請下載開啟。" :
          (data.content || "（空白檔案）") + (data.truncated ? "\n\n[僅顯示前 200 KB]" : "");
      } catch (err) { if (state.selectedFile === f.path) $("filePreview").textContent = err.message; }
    });
    $("fileTree").append(b);
  }
}

function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = "bubble " + role;
  div.textContent = text;
  $("chatLog").appendChild(div);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
  return div;
}

function setBusy(busy) {
  state.busy = busy;
  renderChatMode();
  $("sendBtn").disabled = busy || !state.project;
  $("abortBtn").disabled = !busy;
  $("chatInput").disabled = !state.project || busy;
  $("importFiles").disabled = busy || state.chatMode !== "general";
  renderProject();
}

async function onChatSubmit(ev) {
  ev.preventDefault();
  if (state.busy) return;
  if (!state.project) {
    openProjectDialog("new");
    return;
  }
  const text = $("chatInput").value.trim();
  if (!state.gateway.hasKey && !text.startsWith("/publish ") && !text.startsWith("/deploy-automation ")) {
    setStatus("請先設定模型閘道", "err");
    await handleAction("openGateway"); return;
  }
  if (!text) return;
  $("chatInput").value = "";
  addBubble("user", text);
  const loading = addBubble("loading", "處理中…");
  const live = addBubble("assistant", "");
  live.hidden = true;
  setBusy(true);
  setStatus("執行中", "busy");
  const ac = new AbortController();
  state.abort = ac;
  const timeout = withTimeout(CHAT_TIMEOUT_MS, ac.signal);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Agent-Session": state.sessionId },
      body: JSON.stringify({ message: text }),
      signal: timeout.signal,
    });
    if (!res.ok || !res.body) {
      let detail = "請求失敗";
      try { detail = (await res.json()).error || detail; } catch (_) { /* ignore */ }
      loading.remove();
      live.remove();
      $("chatInput").value = text;
      addBubble("system", detail);
      setStatus(detail, "err");
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let assistant = "";
    let sawError = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const event = (part.match(/^event: (.*)$/m) || [])[1];
        const dataLine = (part.match(/^data: (.*)$/m) || [])[1];
        if (!event || !dataLine) continue;
        const data = JSON.parse(dataLine);
        if (event === "status") {
          state.turnId = data.turn_id || state.turnId;
          loading.textContent = data.message || "Agent 正在處理專案…";
          renderSide();
        } else if (event === "token") {
          assistant += data.text || "";
          live.hidden = false;
          live.textContent = assistant;
          loading.hidden = true;
          $("chatLog").scrollTop = $("chatLog").scrollHeight;
        } else if (event === "approval") {
          state.approvalId = data.approval_id;
          $("approvalText").textContent = data.notice || data.path || data.tool || "publish_workflow";
          $("approvalCard").hidden = false;
        } else if (event === "done") {
          state.turnId = data.turn_id;
          renderSide();
        } else if (event === "error") {
          sawError = data.message || "執行失敗";
        }
      }
    }
    loading.remove();
    if (!assistant) live.remove();
    await loadFiles();
    if (sawError) addBubble("system", sawError);
    setStatus(sawError ? sawError : "待機", sawError ? "err" : "ok");
  } catch (err) {
    loading.remove();
    live.remove();
    if (err.name === "AbortError") {
      addBubble("system", ac.signal.aborted ? "已要求中止；已完成的檔案變更會保留，可使用復原。" : "等待回覆逾時；請確認閘道狀態。");
      setStatus("已中止", "err");
    } else {
      addBubble("system", err.message || "連線失敗");
      setStatus(err.message || "連線失敗", "err");
    }
  } finally {
    timeout.cancel();
    state.abort = null;
    setBusy(false);
  }
}

async function resolveApproval(decision) {
  if (!state.approvalId || state.busy) return;
  setBusy(true);
  $("approveBtn").disabled = $("denyBtn").disabled = true;
  try {
    const data = await api("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_id: state.approvalId, decision }),
      timeoutMs: CHAT_TIMEOUT_MS,
    });
    $("approvalCard").hidden = true;
    addBubble("assistant", decision === "approve" ? "已批准發佈。" : "已拒絕發佈。");
    if (data && data.result) addBubble("system", JSON.stringify(data.result));
    state.approvalId = null;
    await hydrateSession();
  } catch (err) {
    addBubble("system", err.message || "批准請求失敗");
    setStatus(err.message || "批准請求失敗", "err");
  } finally { setBusy(false); $("approveBtn").disabled = $("denyBtn").disabled = false; }
}

function boot() {
  try {
    bindUi();
    renderProject();
    addBubble("system", "歡迎使用本機 AI Agent。請先新增或開啟專案。");
    refreshStatus();
    setInterval(() => {
      if (!state.busy) refreshStatus().catch(() => {});
    }, 8000);
  } catch (err) {
    console.error(err);
    setStatus("前端初始化失敗：" + (err.message || err), "err");
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

$("searchSettingsBtn").addEventListener("click", async () => {
  try {
    const cfg = await api("/api/search/settings");
    $("searchUrl").value = cfg.url; $("searchEnabled").checked = cfg.enabled;
    $("searchSettingsError").textContent = "上游須開啟 JSON 格式。設定修改需要一般模式。";
    $("dlgSearch").showModal();
  } catch (err) { setStatus(err.message, "err"); }
});
$("searchClose").addEventListener("click", () => $("dlgSearch").close());
$("searchSettingsForm").addEventListener("submit", async (event) => {
  event.preventDefault(); $("searchSave").disabled = true;
  try {
    await api("/api/search/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:$("searchUrl").value, enabled:$("searchEnabled").checked})});
    $("searchSettingsError").textContent = "已儲存。可測試 MCP 與上游連線。";
  } catch (err) { $("searchSettingsError").textContent = err.message; }
  finally { $("searchSave").disabled = false; }
});
$("searchTest").addEventListener("click", async () => {
  $("searchTest").disabled = true; $("searchSettingsError").textContent = "正在測試…";
  try { await api("/api/search/test", {method:"POST", timeoutMs:30000}); $("searchSettingsError").textContent = "MCP 與 SearXNG JSON 連線成功"; }
  catch (err) { $("searchSettingsError").textContent = err.message; }
  finally { $("searchTest").disabled = false; }
});

async function loadPlans() {
  const data = await api("/api/plans");
  state.latestPlan = data.plans[0] || null;
  $("planCard").hidden = !state.latestPlan;
  $("planContent").textContent = state.latestPlan ? state.latestPlan.content : "";
}
$("executePlan").addEventListener("click", async () => {
  if (!state.latestPlan || state.busy) return;
  try {
    const data = await api("/api/mode", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({mode:"general"})});
    state.chatMode = data.mode; renderChatMode();
    $("chatInput").value = "請依照已保存計畫 " + state.latestPlan.id + " 執行。發佈仍按批准規則處理。\n\n" + state.latestPlan.content;
    await onChatSubmit({preventDefault() {}});
  } catch (err) { setStatus(err.message, "err"); }
});
async function loadAutomation() {
  const data = await api("/api/automation");
  $("automationHealth").textContent = data.health.reason || (data.health.installed ? "OpenRPA 已安裝 · 本機 Port 8771 · " + (data.health.running ? "執行器已啟動" : "執行時啟動") : "OpenRPA runtime 尚未就緒");
  $("automationRecover").hidden = !data.health.quarantined;
  $("automationRecover").disabled = state.chatMode !== "general";
  $("automationRuns").replaceChildren();
  if (!data.runs.length) $("automationRuns").textContent = "目前專案尚無執行記錄。可請 AI 建立整合部署包，批准後從 n8n 手動開始。";
  for (const run of data.runs) {
    const row = document.createElement("div"); row.className = "approval-card";
    const text = document.createElement("p"); text.textContent = run.run_id + " · " + run.status + (run.error ? " · " + run.error : ""); row.append(text);
    if (["queued", "starting", "running", "cancel_requested"].includes(run.status)) {
      const button = document.createElement("button"); button.textContent = "取消執行"; button.className = "secondary";
      button.disabled = state.chatMode !== "general";
      button.addEventListener("click", async () => { button.disabled = true; try { await api("/api/automation", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({run_id:run.run_id})}); await loadAutomation(); } catch (err) { setStatus(err.message,"err"); button.disabled = false; } });
      row.append(button);
    }
    $("automationRuns").append(row);
  }
}
$("automationStatusBtn").addEventListener("click", async () => { try { await loadAutomation(); $("dlgAutomation").showModal(); } catch (err) { setStatus(err.message,"err"); } });
$("automationRefresh").addEventListener("click", () => loadAutomation().catch(err => setStatus(err.message,"err")));
$("automationClose").addEventListener("click", () => $("dlgAutomation").close());

$("automationRecover").addEventListener("click", async () => {
  $("automationRecover").disabled = true;
  try { await api("/api/automation", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:"recover"})}); await loadAutomation(); }
  catch (err) { setStatus(err.message, "err"); $("automationRecover").disabled = false; }
});
