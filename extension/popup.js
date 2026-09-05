/**
 * OwlThread Extension Popup Logic
 * Handles: tab navigation, health check, site permissions, settings, queue badge
 */

// Default prompts (must match backend defaults for Reset button)
const DEFAULT_EXTRACTION_PROMPT = `You are OwlThread — an ambient memory engine for builders.

You receive raw captured text from diverse sources: AI coding chats (Cursor, Copilot, ChatGPT), terminal output, browser pages, handwritten notes, and team communications.

Your job: extract ONLY durable, reusable knowledge that will be valuable weeks or months later.
Skip: greetings, filler, debugging noise, transient errors, and anything not worth remembering.

Classify each extracted fact into exactly ONE quadrant:
• technical_architecture — how things are built: stack choices, data models, API designs, infrastructure, file structures, deployment setups.
• business_rules — product/company logic: pricing, positioning, policies, constraints, market decisions, user segments, compliance requirements.
• settled_decisions — explicit decisions that were finalized, with reasoning if stated. These are commitments the team made.
• open_questions — unresolved items flagged for future decision. Things marked "TBD", "decide later", or debated without resolution.

Output format: strict JSON array of objects, each with:
  {"quadrant": "<one_of_four>", "summary": "<≤20 words>", "source_snippet": "<relevant excerpt>"}

Rules:
- Never force an entry. Return [] if nothing qualifies.
- Summaries must be actionable and specific, not vague.
- One fact per entry. Don't merge unrelated facts.
- Prefer precision over recall — missing a fact is better than hallucinating one.`;

const DEFAULT_PRIMER_PROMPT = `You are OwlThread's Context Primer — you compile project memory into a focused brief tailored to what the user needs right now.

You receive: the user's request, an intent tag, and relevant memory entries from four quadrants (technical_architecture, business_rules, settled_decisions, open_questions).

Output rules by intent:
• dev_task → Concise technical brief. Lead with architecture and decisions directly relevant to the task. Flag any open questions that might block implementation. Ready to paste into a coding assistant as context.
• external_comms → Narrative summary for a non-technical reader (investor, partner, client). Lead with what the product does and why it matters. Avoid jargon and internal implementation detail.
• status_query → Direct, factual answer citing only relevant entries. Use timestamps and source attribution.
• other → Balanced summary across relevant quadrants.

Constraints:
- ONLY use information from the provided memory entries. Never invent facts.
- If memory is insufficient, say so plainly. Don't fill gaps with assumptions.
- Keep output under 500 words unless the query demands more.
- Use markdown formatting for readability.`;

document.addEventListener("DOMContentLoaded", async () => {
  // ============ Element References ============
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const captureBtn = document.getElementById("capture-btn");
  const portInput = document.getElementById("server-port");
  const entriesLink = document.getElementById("dashboard-link") || document.getElementById("entries-link");
  const providerHintEl = document.getElementById("provider-hint");
  const queueBadge = document.getElementById("queue-badge");

  const projectSelect = document.getElementById("project-select");
  const newProjectBtn = document.getElementById("new-project-btn");
  const newProjectRow = document.getElementById("new-project-row");
  const newProjectName = document.getElementById("new-project-name");
  const saveProjectBtn = document.getElementById("save-project-btn");
  const cancelProjectBtn = document.getElementById("cancel-project-btn");

  const brainTitle = document.getElementById("brain-title");
  const brainModel = document.getElementById("brain-model");
  const brainCard = document.getElementById("brain-card");
  const brainConfigBtn = document.getElementById("brain-config-btn");

  const siteHostEl = document.getElementById("current-site-host");
  const siteStatusEl = document.getElementById("current-site-status");
  const toggleSiteBtn = document.getElementById("toggle-site-perm");

  const aiProviderEl = document.getElementById("ai-provider");
  const aiApiKeyEl = document.getElementById("ai-api-key");
  const aiModelEl = document.getElementById("ai-model");
  const toggleKeyBtn = document.getElementById("toggle-key-btn");
  const saveAiBtn = document.getElementById("save-ai-btn");
  const testAiBtn = document.getElementById("test-ai-btn");
  const aiTestStatus = document.getElementById("ai-test-status");

  const extractionPromptEl = document.getElementById("extraction-prompt");
  const primerPromptEl = document.getElementById("primer-prompt");
  const savePromptsBtn = document.getElementById("save-prompts-btn");
  const resetPromptsBtn = document.getElementById("reset-prompts-btn");
  const settingsStatusEl = document.getElementById("settings-status");

  let currentHostname = "local";
  let keyIsVisible = false;

  // ============ Tab Navigation ============
  function switchTab(tabName) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (btn) btn.classList.add("active");
    const tabEl = document.getElementById(`tab-${tabName}`);
    if (tabEl) tabEl.classList.add("active");

    if (tabName === "settings") {
      loadSettingsFromServer();
    }
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  brainConfigBtn.addEventListener("click", () => switchTab("settings"));

  // ============ Load Active Tab Hostname ============
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && !tab.url.startsWith("chrome://")) {
      const parsed = new URL(tab.url);
      currentHostname = parsed.hostname;
      siteHostEl.innerText = currentHostname;
    } else {
      siteHostEl.innerText = "Browser Tab";
    }
  } catch (e) {
    siteHostEl.innerText = "Current Tab";
  }

  // ============ Site Permissions ============
  async function refreshSitePermissionUI() {
    const res = await chrome.storage.local.get(["owl_site_permissions"]);
    const perms = res.owl_site_permissions || {};
    const status = perms[currentHostname];

    siteStatusEl.className = "site-tag";
    if (status === "allowed") {
      siteStatusEl.innerText = "Memory Active";
      siteStatusEl.classList.add("allowed");
      toggleSiteBtn.innerText = "Block Memory on Site";
    } else if (status === "blocked") {
      siteStatusEl.innerText = "Blocked";
      siteStatusEl.classList.add("blocked");
      toggleSiteBtn.innerText = "Allow Memory on Site";
    } else {
      siteStatusEl.innerText = "Not Configured";
      siteStatusEl.classList.add("pending");
      toggleSiteBtn.innerText = "Allow Memory on Site";
    }
  }

  await refreshSitePermissionUI();

  toggleSiteBtn.addEventListener("click", async () => {
    const res = await chrome.storage.local.get(["owl_site_permissions"]);
    const perms = res.owl_site_permissions || {};
    const current = perms[currentHostname];
    const newStatus = current === "allowed" ? "blocked" : "allowed";
    perms[currentHostname] = newStatus;
    await chrome.storage.local.set({ owl_site_permissions: perms });
    await refreshSitePermissionUI();

    // Sync to Desktop Backend
    const currentPort = await getPort();
    try {
      await fetch(`http://127.0.0.1:${currentPort}/sites`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hostname: currentHostname, status: newStatus }),
      });
    } catch (e) {}
  });

  // ============ Port Config & Health ============
  const stored = await chrome.storage.local.get(["serverPort", "owl_active_project"]);
  const port = stored.serverPort || 41789;
  portInput.value = port;
  entriesLink.href = `http://127.0.0.1:${port}/entries`;

  async function getPort() {
    return parseInt(portInput.value, 10) || 41789;
  }

  // ============ Projects Sync ============
  async function loadProjectsFromServer() {
    const currentPort = await getPort();
    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/projects`, { method: "GET" });
      if (resp.ok) {
        const data = await resp.json();
        const projects = data.projects || ["General"];
        const localActive = (await chrome.storage.local.get(["owl_active_project"])).owl_active_project;
        const activeProj = data.active_project || localActive || "General";

        projectSelect.innerHTML = "";
        projects.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p;
          opt.innerText = p;
          if (p === activeProj) opt.selected = true;
          projectSelect.appendChild(opt);
        });

        await chrome.storage.local.set({
          owl_active_project: activeProj,
          owl_projects_list: projects,
        });
        return;
      }
    } catch (e) {
      console.warn("Could not sync projects from server, using local cache:", e);
    }

    // Offline fallback from chrome.storage.local
    const localData = await chrome.storage.local.get(["owl_projects_list", "owl_active_project"]);
    const cachedProjects = localData.owl_projects_list || ["General"];
    const activeProj = localData.owl_active_project || "General";
    if (!cachedProjects.includes("General")) cachedProjects.unshift("General");

    projectSelect.innerHTML = "";
    cachedProjects.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.innerText = p;
      if (p === activeProj) opt.selected = true;
      projectSelect.appendChild(opt);
    });
  }

  projectSelect.addEventListener("change", async () => {
    const chosen = projectSelect.value;
    await chrome.storage.local.set({ owl_active_project: chosen });
    const currentPort = await getPort();
    try {
      await fetch(`http://127.0.0.1:${currentPort}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_project: chosen, name: chosen }),
      });
    } catch (e) {
      console.warn("Could not update active project on server:", e);
    }
  });

  newProjectBtn.addEventListener("click", () => {
    newProjectRow.classList.toggle("hidden");
    if (!newProjectRow.classList.contains("hidden")) {
      newProjectName.value = "";
      newProjectName.focus();
    }
  });

  cancelProjectBtn.addEventListener("click", () => {
    newProjectRow.classList.add("hidden");
    newProjectName.value = "";
  });

  async function handleCreateProject() {
    const name = newProjectName.value.trim();
    if (!name) return;

    saveProjectBtn.disabled = true;
    saveProjectBtn.innerText = "Adding...";

    // 1. Optimistic Local Update
    let exists = false;
    for (let opt of projectSelect.options) {
      if (opt.value.toLowerCase() === name.toLowerCase()) {
        opt.selected = true;
        exists = true;
        break;
      }
    }
    if (!exists) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.innerText = name;
      opt.selected = true;
      projectSelect.appendChild(opt);
    }
    projectSelect.value = name;

    const storedProjects = (await chrome.storage.local.get(["owl_projects_list"])).owl_projects_list || ["General"];
    if (!storedProjects.includes(name)) {
      storedProjects.push(name);
    }
    await chrome.storage.local.set({
      owl_active_project: name,
      owl_projects_list: storedProjects,
    });

    // 2. Sync to backend if running
    const currentPort = await getPort();
    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, active_project: name }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.projects)) {
          await chrome.storage.local.set({ owl_projects_list: data.projects });
          await loadProjectsFromServer();
        }
      }
    } catch (e) {
      console.warn("Server offline, project saved locally in extension:", e);
    }

    newProjectName.value = "";
    newProjectRow.classList.add("hidden");
    saveProjectBtn.disabled = false;
    saveProjectBtn.innerText = "Add";
  }

  saveProjectBtn.addEventListener("click", handleCreateProject);

  newProjectName.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCreateProject();
    } else if (e.key === "Escape") {
      newProjectRow.classList.add("hidden");
      newProjectName.value = "";
    }
  });

  // ============ Check Health & Brain Status ============
  async function checkHealth() {
    const currentPort = await getPort();
    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/state`, { method: "GET" });
      if (resp.ok) {
        const data = await resp.json();
        statusDot.className = "status-dot connected";
        statusText.innerText = `Connected (${data.total_entries || 0} memories)`;

        // Update Brain Status
        if (data.has_api_key && data.ai_provider !== "fallback") {
          brainTitle.innerText = `AI Brain: ${data.ai_provider.toUpperCase()}`;
          brainModel.innerText = data.ai_model || "Active Online";
          brainCard.style.borderColor = "rgba(16, 185, 129, 0.45)";
          brainTitle.style.color = "#a7f3d0";
        } else {
          brainTitle.innerText = "AI Brain: Offline";
          brainModel.innerText = "Heuristic (Click ⚙️ to add Key)";
          brainCard.style.borderColor = "rgba(99, 102, 241, 0.35)";
          brainTitle.style.color = "#c7d2fe";
        }
      } else {
        statusDot.className = "status-dot disconnected";
        statusText.innerText = "Service error";
      }
    } catch (e) {
      statusDot.className = "status-dot disconnected";
      statusText.innerText = "App not running";
      brainTitle.innerText = "AI Brain: App Offline";
      brainModel.innerText = "Start OwlThread Desktop App";
    }
  }

  await loadProjectsFromServer();
  await checkHealth();

  // ============ Queue Badge ============
  async function updateQueueBadge() {
    try {
      if (!chrome?.runtime?.id) return;
      const res = await chrome.runtime.sendMessage({ action: "get_queue_count" }).catch(() => null);
      if (res && res.count > 0) {
        queueBadge.innerText = res.count;
        queueBadge.classList.remove("hidden");
      } else {
        queueBadge.classList.add("hidden");
      }
    } catch (e) {
      // Ignore
    }
  }
  await updateQueueBadge();

  // ============ Port Change Handler ============
  portInput.addEventListener("change", async () => {
    const newPort = parseInt(portInput.value, 10) || 41789;
    await chrome.storage.local.set({
      serverPort: newPort,
      serverUrl: `http://127.0.0.1:${newPort}/capture`,
    });
    entriesLink.href = `http://127.0.0.1:${newPort}/entries`;
    await checkHealth();
    await loadProjectsFromServer();
  });

  // ============ Capture Button ============
  captureBtn.addEventListener("click", async () => {
    captureBtn.disabled = true;
    captureBtn.innerText = "Capturing...";
    try {
      if (chrome?.runtime?.id) {
        await chrome.runtime.sendMessage({ action: "capture_current_tab" }).catch(() => null);
      }
    } catch (e) {}

    setTimeout(async () => {
      captureBtn.disabled = false;
      captureBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        Captured!
      `;
      await checkHealth();
      await updateQueueBadge();
      setTimeout(() => {
        captureBtn.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="16"></line>
            <line x1="8" y1="12" x2="16" y2="12"></line>
          </svg>
          Snapshot Current Tab
        `;
      }, 1500);
    }, 400);
  });

  // ============ AI Settings: Show/Hide Key ============
  toggleKeyBtn.addEventListener("click", () => {
    keyIsVisible = !keyIsVisible;
    aiApiKeyEl.type = keyIsVisible ? "text" : "password";
    toggleKeyBtn.innerText = keyIsVisible ? "🔒" : "👁️";
  });

  function updateProviderHint() {
    if (!providerHintEl) return;
    const p = aiProviderEl.value;
    if (p === "gemini") {
      providerHintEl.innerText = "⚡ Free Tier: Fast & recommended (15 req/min, no billing needed at aistudio.google.com)";
      providerHintEl.style.color = "#38bdf8";
    } else if (p === "openai") {
      providerHintEl.innerText = "Requires paid OpenAI API key (sk-...) with GPT-4o-mini";
      providerHintEl.style.color = "#a5b4fc";
    } else if (p === "anthropic") {
      providerHintEl.innerText = "Requires Anthropic Claude API key (sk-ant-...)";
      providerHintEl.style.color = "#f472b6";
    } else if (p === "ollama") {
      providerHintEl.innerText = "Runs completely local on your machine at http://127.0.0.1:11434";
      providerHintEl.style.color = "#fbbf24";
    } else {
      providerHintEl.innerText = "Offline heuristic extraction (works anywhere with zero API key)";
      providerHintEl.style.color = "#94a3b8";
    }
  }

  aiProviderEl.addEventListener("change", () => {
    const p = aiProviderEl.value;
    if (p === "gemini") {
      aiModelEl.value = "gemini-2.0-flash";
    } else if (p === "openai") {
      aiModelEl.value = "gpt-4o-mini";
    } else if (p === "anthropic") {
      aiModelEl.value = "claude-3-5-haiku-latest";
    } else if (p === "ollama") {
      aiModelEl.value = "llama3";
    }
    updateProviderHint();
  });

  // ============ Settings: Load from Server ============
  async function loadSettingsFromServer() {
    const currentPort = await getPort();
    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/settings`, { method: "GET" });
      if (resp.ok) {
        const data = await resp.json();
        const settings = data.settings || {};
        extractionPromptEl.value = settings.extraction_prompt || DEFAULT_EXTRACTION_PROMPT;
        primerPromptEl.value = settings.primer_prompt || DEFAULT_PRIMER_PROMPT;

        // Load AI Settings
        aiProviderEl.value = settings.llm_provider || "fallback";
        aiApiKeyEl.value = settings.llm_api_key || "";
        aiModelEl.value = settings.llm_model || (aiProviderEl.value === "gemini" ? "gemini-2.0-flash" : "gpt-4o-mini");

        updateProviderHint();
        settingsStatusEl.innerText = "";
      } else {
        extractionPromptEl.value = DEFAULT_EXTRACTION_PROMPT;
        primerPromptEl.value = DEFAULT_PRIMER_PROMPT;
        updateProviderHint();
        settingsStatusEl.innerText = "⚠️ Could not load settings from server.";
      }
    } catch (e) {
      extractionPromptEl.value = DEFAULT_EXTRACTION_PROMPT;
      primerPromptEl.value = DEFAULT_PRIMER_PROMPT;
      updateProviderHint();
      settingsStatusEl.innerText = "⚠️ Server offline — showing defaults.";
    }
  }

  // ============ Save AI Key & Model ============
  saveAiBtn.addEventListener("click", async () => {
    const currentPort = await getPort();
    const payload = {
      llm_provider: aiProviderEl.value,
      llm_api_key: aiApiKeyEl.value.trim(),
      llm_model: aiModelEl.value.trim(),
    };

    saveAiBtn.disabled = true;
    saveAiBtn.innerText = "Saving...";

    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        aiTestStatus.innerText = "✅ AI Engine saved & active!";
        aiTestStatus.style.color = "#4ade80";
        await checkHealth();
      } else {
        aiTestStatus.innerText = "❌ Failed to save AI settings.";
        aiTestStatus.style.color = "#f87171";
      }
    } catch (e) {
      aiTestStatus.innerText = "❌ Server offline.";
      aiTestStatus.style.color = "#f87171";
    }

    saveAiBtn.disabled = false;
    saveAiBtn.innerText = "💾 Save AI Key";
  });

  // ============ Test AI Connection ============
  testAiBtn.addEventListener("click", async () => {
    const currentPort = await getPort();
    testAiBtn.disabled = true;
    testAiBtn.innerText = "Testing...";
    aiTestStatus.innerText = "Connecting to provider...";
    aiTestStatus.style.color = "#38bdf8";

    try {
      // Auto-save first so backend has latest credentials
      await fetch(`http://127.0.0.1:${currentPort}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm_provider: aiProviderEl.value,
          llm_api_key: aiApiKeyEl.value.trim(),
          llm_model: aiModelEl.value.trim(),
        }),
      });

      const resp = await fetch(`http://127.0.0.1:${currentPort}/test-ai`, { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        if (data.success) {
          aiTestStatus.innerText = `🟢 Connected: ${data.message || "OK"}`;
          aiTestStatus.style.color = "#4ade80";
        } else {
          aiTestStatus.innerText = `🔴 Failed: ${data.message || "Error"}`;
          aiTestStatus.style.color = "#f87171";
        }
      } else {
        aiTestStatus.innerText = `🔴 Server returned error HTTP ${resp.status}`;
        aiTestStatus.style.color = "#f87171";
      }
    } catch (e) {
      aiTestStatus.innerText = `🔴 Server offline or unreachable (${e.message})`;
      aiTestStatus.style.color = "#f87171";
    } finally {
      testAiBtn.disabled = false;
      testAiBtn.innerText = "⚡ Test";
      await checkHealth();
    }
  });

  // ============ Settings: Save Prompts ============
  savePromptsBtn.addEventListener("click", async () => {
    const currentPort = await getPort();
    const payload = {
      extraction_prompt: extractionPromptEl.value.trim(),
      primer_prompt: primerPromptEl.value.trim(),
    };

    savePromptsBtn.disabled = true;
    savePromptsBtn.innerText = "Saving...";

    try {
      const resp = await fetch(`http://127.0.0.1:${currentPort}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        const data = await resp.json();
        settingsStatusEl.innerText = `✅ ${data.message || "Saved!"}`;
        settingsStatusEl.style.color = "#4ade80";
      } else {
        settingsStatusEl.innerText = "❌ Failed to save settings.";
        settingsStatusEl.style.color = "#f87171";
      }
    } catch (e) {
      settingsStatusEl.innerText = "❌ Server offline — cannot save.";
      settingsStatusEl.style.color = "#f87171";
    }

    savePromptsBtn.disabled = false;
    savePromptsBtn.innerText = "💾 Save Prompts";
  });

  // ============ Settings: Reset Prompts ============
  resetPromptsBtn.addEventListener("click", () => {
    extractionPromptEl.value = DEFAULT_EXTRACTION_PROMPT;
    primerPromptEl.value = DEFAULT_PRIMER_PROMPT;
    settingsStatusEl.innerText = "↩️ Reset to defaults. Click Save to apply.";
    settingsStatusEl.style.color = "#fbbf24";
  });
});
