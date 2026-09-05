/**
 * OwlThread Chrome Extension - Background Service Worker (Manifest V3)
 * Features: capture relay, offline queue, alarm-based retry
 */

const DEFAULT_SERVER_URL = "http://127.0.0.1:41789/capture";
const QUEUE_KEY = "owl_pending_queue";
const MAX_QUEUE_SIZE = 200;
const RETRY_ALARM_NAME = "owl_retry_queue";

// Get configured server URL from chrome.storage or fallback
async function getServerUrl() {
  const result = await chrome.storage.local.get(["serverUrl", "serverPort"]);
  if (result.serverUrl) {
    return result.serverUrl;
  }
  const port = result.serverPort || 41789;
  return `http://127.0.0.1:${port}/capture`;
}

// Get base server URL (without /capture path)
async function getBaseUrl() {
  const result = await chrome.storage.local.get(["serverPort"]);
  const port = result.serverPort || 41789;
  return `http://127.0.0.1:${port}`;
}

// Get active project chosen by user
async function getActiveProject() {
  const result = await chrome.storage.local.get(["owl_active_project"]);
  return result.owl_active_project || "General";
}

// ------------------------------------------------------------------
// Offline Queue Management & Toolbar Badges
// ------------------------------------------------------------------
async function updateActionBadge(count) {
  if (!chrome.action) return;
  try {
    if (typeof count !== "number") {
      const q = await getQueue();
      count = q.length;
    }
    if (count > 0) {
      chrome.action.setBadgeText({ text: String(count) });
      chrome.action.setBadgeBackgroundColor({ color: "#f59e0b" }); // warm amber
    } else {
      chrome.action.setBadgeText({ text: "" });
    }
  } catch (e) {}
}

async function getQueue() {
  const result = await chrome.storage.local.get([QUEUE_KEY]);
  return result[QUEUE_KEY] || [];
}

async function addToQueue(payload) {
  const queue = await getQueue();
  // Cap queue size to prevent storage overflow
  if (queue.length >= MAX_QUEUE_SIZE) {
    queue.shift(); // Drop oldest
  }
  queue.push({
    payload,
    queued_at: new Date().toISOString(),
  });
  await chrome.storage.local.set({ [QUEUE_KEY]: queue });
  updateActionBadge(queue.length);
  // Schedule retry alarm
  chrome.alarms.create(RETRY_ALARM_NAME, { delayInMinutes: 2 });
  return queue.length;
}

async function drainQueue() {
  const queue = await getQueue();
  if (queue.length === 0) {
    updateActionBadge(0);
    return;
  }

  const serverUrl = await getServerUrl();
  const remaining = [];

  for (const item of queue) {
    try {
      const response = await fetch(serverUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item.payload),
      });
      if (!response.ok) {
        remaining.push(item); // Keep for retry
      }
      // Success — item is drained
    } catch (e) {
      // Server still offline — keep all remaining
      remaining.push(item);
      const idx = queue.indexOf(item);
      remaining.push(...queue.slice(idx + 1));
      break;
    }
  }

  await chrome.storage.local.set({ [QUEUE_KEY]: remaining });
  updateActionBadge(remaining.length);
  if (remaining.length === 0) {
    chrome.alarms.clear(RETRY_ALARM_NAME);
  }
}

// ------------------------------------------------------------------
// Core Capture Sender (with crash guard & queue fallback)
// ------------------------------------------------------------------
async function sendCaptureToOwlThread(payload) {
  if (!payload || typeof payload !== "object") {
    return { success: false, error: "Empty or invalid capture payload" };
  }
  const serverUrl = await getServerUrl();
  const activeProj = await getActiveProject();
  const reqProj = payload.project_name;
  const projectName = (reqProj && reqProj !== "General") ? reqProj : activeProj;

  try {
    const response = await fetch(serverUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: payload.text,
        source_app: payload.source_app || "browser",
        project_name: projectName,
        url: payload.url,
        title: payload.title,
        metadata: {
          captured_at: new Date().toISOString(),
          container_type: payload.containerType || payload.type || "selection",
          ...payload.metadata,
        },
      }),
    });

    if (!response.ok) {
      // Server returned an error status — queue for retry
      const errText = await response.text().catch(() => "Unknown error");
      console.warn(`OwlThread server error (HTTP ${response.status}): ${errText}`);
      const qLen = await addToQueue(payload);
      return { success: false, queued: true, queue_length: qLen, error: `HTTP ${response.status}` };
    }

    // Parse JSON response safely
    let data = {};
    try {
      const responseText = await response.text();
      if (responseText && responseText.trim()) {
        data = JSON.parse(responseText);
      }
    } catch (parseErr) {
      console.warn("OwlThread: response was not valid JSON, but capture was accepted.");
      data = { status: "accepted" };
    }

    // Successful send — try to drain any queued items
    drainQueue().catch(() => {}); // Fire-and-forget

    return { success: true, data };
  } catch (error) {
    // Network error (server offline, connection refused, etc.)
    console.warn("OwlThread server offline, queueing capture:", error.message);
    const qLen = await addToQueue(payload);
    return { success: false, queued: true, queue_length: qLen, error: error.message };
  }
}

function isRestrictedUrl(url) {
  if (!url || typeof url !== "string") return true;
  const restrictedPrefixes = [
    "chrome://",
    "chrome-extension://",
    "edge://",
    "brave://",
    "about:",
    "view-source:",
    "https://chromewebstore.google.com",
    "https://chrome.google.com/webstore",
  ];
  return restrictedPrefixes.some((p) => url.startsWith(p));
}

// ------------------------------------------------------------------
// Manual Tab Capture Handler
// ------------------------------------------------------------------
async function handleCaptureOnTab(tab) {
  if (!tab || !tab.id || isRestrictedUrl(tab.url)) {
    return { success: false, error: "Cannot capture browser system or webstore pages" };
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const selection = window.getSelection();
        const selectedText = selection ? selection.toString().trim() : "";
        if (selectedText) {
          return { text: selectedText, type: "selection" };
        }
        const bodyText = document.body.innerText.trim();
        return { text: bodyText, type: "body_fallback" };
      },
    });

    if (!results || !results[0] || !results[0].result) {
      return;
    }

    const extracted = results[0].result;
    if (!extracted.text || !extracted.text.trim()) {
      return;
    }

    const hostname = new URL(tab.url).hostname;
    const activeProj = await getActiveProject();
    await sendCaptureToOwlThread({
      text: extracted.text,
      url: tab.url,
      title: tab.title,
      project_name: activeProj,
      containerType: extracted.type,
      metadata: { hostname: hostname },
    });
  } catch (err) {
    console.warn("Failed executing capture on tab:", err ? err.message : err);
  }
}

// ------------------------------------------------------------------
// Alarm Listener — Retry queued captures
// ------------------------------------------------------------------
const SYNC_ALARM_NAME = "owl_sync_state_alarm";

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === RETRY_ALARM_NAME) {
    console.log("[OwlThread] Retrying queued captures...");
    await drainQueue();
    const queue = await getQueue();
    if (queue.length > 0) {
      chrome.alarms.create(RETRY_ALARM_NAME, { delayInMinutes: 2 });
    }
  }

  if (alarm.name === SYNC_ALARM_NAME) {
    await syncBackendStateAndProjects();
  }
});

// ------------------------------------------------------------------
// Keyboard Command Listener (Ctrl+Shift+O)
// ------------------------------------------------------------------
chrome.commands.onCommand.addListener(async (command) => {
  if (command === "capture_selection") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      await handleCaptureOnTab(tab);
    }
  }
});

// ------------------------------------------------------------------
// 2-Way Desktop Coordination (Sites & State Sync)
// ------------------------------------------------------------------
async function syncBackendStateAndProjects() {
  const baseUrl = await getBaseUrl();
  try {
    // 1. Sync state & active project from Desktop App
    const stateRes = await fetch(`${baseUrl}/state`, { method: "GET" });
    if (stateRes.ok) {
      const stateData = await stateRes.json();
      if (stateData.active_project) {
        await chrome.storage.local.set({
          owl_active_project: stateData.active_project,
          owl_backend_connected: true,
          owl_backend_paused: !!stateData.is_paused,
        });
      }
    } else {
      await chrome.storage.local.set({ owl_backend_connected: false });
    }

    // 2. Sync domain permissions
    await syncSitesFromBackend();
  } catch (e) {
    await chrome.storage.local.set({ owl_backend_connected: false });
  }
}

async function syncSitesFromBackend() {
  const baseUrl = await getBaseUrl();
  try {
    const res = await fetch(`${baseUrl}/sites`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      const serverSites = data.sites || {};
      const local = await chrome.storage.local.get(["owl_site_permissions"]);
      const merged = { ...(local.owl_site_permissions || {}), ...serverSites };
      await chrome.storage.local.set({ owl_site_permissions: merged });
      return merged;
    }
  } catch (e) {
    // Backend offline
  }
  return null;
}

async function updateSitePermissionOnBackend(hostname, status) {
  const baseUrl = await getBaseUrl();
  try {
    await fetch(`${baseUrl}/sites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hostname, status }),
    });
  } catch (e) {
    // Offline
  }
}

// ------------------------------------------------------------------
// Central Message Listener for content script & popup
// ------------------------------------------------------------------
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "send_capture") {
    sendCaptureToOwlThread(request.payload)
      .then((res) => sendResponse(res))
      .catch((err) => sendResponse({ success: false, error: err ? err.message : "Error" }));
    return true; // Keep message channel open for async response
  }

  if (request.action === "capture_current_tab") {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => {
        if (tab) {
          return handleCaptureOnTab(tab);
        }
      })
      .then(() => sendResponse({ status: "done" }))
      .catch((err) => sendResponse({ status: "error", error: err ? err.message : "Error" }));
    return true;
  }

  if (request.action === "get_queue_count") {
    getQueue()
      .then((queue) => sendResponse({ count: queue.length }))
      .catch(() => sendResponse({ count: 0 }));
    return true;
  }

  if (request.action === "get_active_project") {
    getActiveProject()
      .then((proj) => sendResponse({ active_project: proj }))
      .catch(() => sendResponse({ active_project: "General" }));
    return true;
  }

  if (request.action === "sync_site_permission") {
    updateSitePermissionOnBackend(request.hostname, request.status)
      .then(() => sendResponse({ status: "synced" }))
      .catch(() => sendResponse({ status: "failed" }));
    return true;
  }

  if (request.action === "sync_now") {
    syncBackendStateAndProjects()
      .then(() => sendResponse({ status: "ok" }))
      .catch(() => sendResponse({ status: "failed" }));
    return true;
  }

  if (request.action === "get_backend_state") {
    (async () => {
      try {
        const baseUrl = await getBaseUrl();
        const r = await fetch(`${baseUrl}/state`, { method: "GET" });
        if (r.ok) {
          const data = await r.json();
          if (data && data.active_project) {
            await chrome.storage.local.set({
              owl_active_project: data.active_project,
              owl_backend_connected: true,
              owl_backend_paused: !!data.is_paused,
            });
          }
          sendResponse(data);
          return;
        }
      } catch (e) {
        // App is offline or unreachable — respond with offline state cleanly
      }
      sendResponse({ is_paused: false, offline: true });
    })();
    return true;
  }
});

// ------------------------------------------------------------------
// MV3 Port Connection & Keep-Alive Heartbeat Listener
// ------------------------------------------------------------------
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "owlthread-port") {
    console.log("[OwlThread Background] Connected port:", port.name);

    port.onMessage.addListener(async (message) => {
      // 1. Keep-alive heartbeat acknowledgment
      if (message && message.type === "heartbeat") {
        try {
          port.postMessage({ type: "heartbeat_ack", timestamp: Date.now() });
        } catch (e) {}
        return;
      }

      // 2. Assistant turn capture relay
      if (message && message.type === "assistant_turn_captured" && message.payload) {
        const turn = message.payload;
        await sendCaptureToOwlThread({
          text: turn.text,
          source_app: `web_${turn.platform || "ai_chat"}`,
          url: turn.url,
          title: turn.title,
          containerType: "assistant_turn",
          metadata: {
            fingerprint: turn.fingerprint,
            platform: turn.platform,
            turn_index: turn.metadata ? turn.metadata.turnIndex : undefined,
            captured_at: turn.timestamp || new Date().toISOString(),
            ...turn.metadata,
          },
        });
      }
    });

    port.onDisconnect.addListener(() => {
      console.log("[OwlThread Background] Port disconnected:", port.name);
    });
  }
});

// Setup background sync alarm & initial sync
function setupBackgroundSync() {
  updateActionBadge();
  drainQueue().catch(() => {});
  syncBackendStateAndProjects().catch(() => {});
  // Run background sync every 1 minute
  chrome.alarms.create(SYNC_ALARM_NAME, { periodInMinutes: 1 });
}

chrome.runtime.onStartup.addListener(setupBackgroundSync);
chrome.runtime.onInstalled.addListener(setupBackgroundSync);

