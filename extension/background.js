"use strict";
(() => {
    importScripts("policy.js");
    const endpoint = "http://127.0.0.1:41789";
    class DesktopError extends Error {
        connection;
        constructor(message, connection) {
            super(message);
            this.connection = connection;
        }
    }
    // Longer than the content observer's ten-minute completion window.
    const stagedTurnTtlMs = 12 * 60 * 1000;
    const storageReady = chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
    function publicKey(key) { return ["enabled", "companionVisible", "companionMotion", "companionPosition"].includes(key) || /^siteMode:[a-z0-9.-]+$/.test(key); }
    function validSetting(key, value) {
        if (key.startsWith("siteMode:")) {
            const hostname = key.slice("siteMode:".length);
            return typeof value === "string" && ["allowed", "blocked", "default"].includes(value) && !(value === "allowed" && OwlPolicy.hardBlocked(hostname));
        }
        if (key === "companionPosition")
            return !!value && typeof value === "object" && ["x", "y"].every(k => typeof value[k] === "number" && Number.isFinite(value[k]) && Math.abs(value[k]) <= 100000) && Object.keys(value).length === 2;
        return ["enabled", "companionVisible", "companionMotion"].includes(key) && typeof value === "boolean";
    }
    function publicSettings(saved) {
        return { ...Object.fromEntries(Object.entries(saved).filter(([key]) => publicKey(key))),
            outbox: Array.isArray(saved.outbox) ? saved.outbox.map(() => ({})) : [] };
    }
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "local")
            return;
        const safe = Object.fromEntries(Object.entries(changes).filter(([key]) => publicKey(key)));
        if (changes.outbox)
            safe.outbox = { newValue: Array.isArray(changes.outbox.newValue) ? changes.outbox.newValue.map(() => ({})) : [] };
        if (Object.keys(safe).length)
            void chrome.tabs.query({ url: ["http://*/*", "https://*/*"] }).then(tabs => Promise.allSettled(tabs
                .filter(t => t.id !== undefined && !OwlPolicy.hardBlocked(OwlPolicy.host(t.url || "")))
                .map(t => chrome.tabs.sendMessage(t.id, { type: "public_settings_changed", changes: safe }))));
    });
    let chain = Promise.resolve();
    function serial(job) {
        const result = chain.then(job, job);
        chain = result.catch(() => undefined);
        return result;
    }
    async function digest(value) {
        const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
        return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
    }
    async function request(path, payload, tokenOverride) {
        await storageReady;
        const saved = await chrome.storage.local.get({ localApiToken: "" });
        const token = tokenOverride ?? saved.localApiToken;
        if (!token)
            throw new DesktopError("Pair this browser: copy the secret from desktop Settings into Connection settings below.", "unpaired");
        let response;
        try {
            response = await fetch(endpoint + path, {
                method: payload === undefined ? "GET" : "POST",
                headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
                redirect: "error",
                ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
                signal: AbortSignal.timeout(path === "/flush" ? 25000 : path === "/context" || path === "/capture-smart" ? 20000 : 5000)
            });
        }
        catch {
            throw new DesktopError("Desktop is not reachable. Open OwlThread; saved captures will retry automatically.", "offline");
        }
        let result;
        try {
            result = await response.json();
        }
        catch {
            throw new DesktopError(`Desktop returned an unreadable response (${response.status}). Reopen OwlThread and try again.`, "error");
        }
        if (!result || typeof result !== "object" || Array.isArray(result))
            throw new DesktopError("Desktop returned an invalid response.", "error");
        if (!response.ok) {
            if (response.status === 401 || response.status === 403)
                throw new DesktopError("This browser needs pairing again. Copy the current secret from desktop Settings.", "pairing_required");
            throw new DesktopError(typeof result.error === "string" ? result.error : "Local request failed", "error");
        }
        return result;
    }
    let syncing;
    let syncAgain = false;
    let retryTimer;
    let retryDelay = 5000;
    function retrySoon() {
        if (retryTimer)
            return;
        // MV3 can suspend timers. The persistent one-minute alarm remains the fallback.
        retryTimer = setTimeout(() => { retryTimer = undefined; void flushQueue().catch(() => undefined); }, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 20000);
    }
    async function drainQueue() {
        const outbox = await serial(async () => {
            const saved = await chrome.storage.local.get({ outbox: [] });
            const original = Array.isArray(saved.outbox) ? saved.outbox : [];
            const now = Date.now();
            let changed = false;
            const prepared = [];
            for (const item of original) {
                if (OwlPolicy.hardBlocked(OwlPolicy.host(item.payload?.url || ""))) {
                    changed = true;
                    continue;
                }
                if (item.state === "staged" && item.stagedAt && now - item.stagedAt >= stagedTurnTtlMs) {
                    changed = true;
                    prepared.push({ ...item, state: "ready", payload: { ...item.payload, capture_kind: "ai_prompt_only" } });
                }
                else
                    prepared.push(item);
            }
            if (changed)
                await chrome.storage.local.set({ outbox: prepared,
                    lastError: original.length !== prepared.length ? "A queued capture from a permanently blocked site was removed." : "" });
            return prepared;
        });
        let failure = "", retryable = false;
        for (const item of outbox) {
            try {
                if (item.state === "staged")
                    continue;
                if (!item.payload.project) {
                    failure = "Older queued notes need a project. Review the queue in Preferences.";
                    continue;
                }
                const currentSettings = await chrome.storage.local.get(null);
                if (OwlPolicy.hardBlocked(OwlPolicy.host(item.payload.url || "")))
                    continue;
                if (OwlPolicy.mode(currentSettings, OwlPolicy.host(item.payload.url || "")) === "blocked") {
                    failure = "A saved capture is held because its site is blocked. Allow the site to sync it.";
                    continue;
                }
                await request("/capture", item.payload);
                await serial(async () => {
                    const latest = await chrome.storage.local.get({ outbox: [] });
                    // Read again after the network call so new captures cannot be overwritten.
                    const remaining = latest.outbox.filter(candidate => candidate.id !== item.id);
                    await chrome.storage.local.set({ outbox: remaining, lastError: "",
                        lastCapture: Date.now(), lastSyncedProject: item.payload.project });
                });
            }
            catch (error) {
                failure = error instanceof Error ? error.message : "Start the OwlThread desktop app";
                retryable = error instanceof DesktopError && error.connection === "offline";
                break;
            }
        }
        await chrome.storage.local.set({ lastError: failure });
        await updateBadge();
        if (retryable)
            retrySoon();
        else {
            clearTimeout(retryTimer);
            retryTimer = undefined;
            retryDelay = 5000;
        }
        return failure ? { ok: false, error: failure } : { ok: true };
    }
    function flushQueue() {
        if (syncing) {
            syncAgain = true;
            return syncing;
        }
        syncing = (async () => {
            let result;
            do {
                syncAgain = false;
                result = await drainQueue();
            } while (result.ok && syncAgain);
            return result;
        })().finally(() => { syncing = undefined; });
        return syncing;
    }
    async function resumeQueue() {
        // A connection may recover while the previous failed delivery is still settling.
        if (syncing)
            await syncing;
        return flushQueue();
    }
    async function desktopStatus() {
        try {
            return await request("/status");
        }
        catch (error) {
            // Reauthorize a previously paired extension after app origin permissions reset.
            // Only a saved secret is used; an unpaired browser never gains access automatically.
            if (error instanceof DesktopError && ["pairing_required", "offline"].includes(error.connection)) {
                await request("/pair", {});
                return request("/status");
            }
            throw error;
        }
    }
    async function updateBadge() {
        const saved = await chrome.storage.local.get({ outbox: [] });
        const count = Array.isArray(saved.outbox) ? saved.outbox.length : 0;
        await chrome.action.setBadgeText({ text: count ? String(count) : "" });
        await chrome.action.setBadgeBackgroundColor({ color: "#d9b77a" });
    }
    async function checkSite(url, automatic = false) {
        const hostname = OwlPolicy.host(url);
        if (url && !hostname)
            throw new Error("Open a normal website to capture text.");
        if (OwlPolicy.hardBlocked(hostname))
            throw new Error("OwlThread is permanently off on this site.");
        const saved = await chrome.storage.local.get(null);
        if (hostname && !OwlPolicy.allowed(saved, hostname))
            throw new Error("OwlThread is off on this site. Allow it in the popup first.");
        if (automatic && (saved.enabled === false || !OwlPolicy.aiSites.includes(hostname)))
            throw new Error("Automatic capture is off on this site.");
    }
    async function enqueue(payload) {
        if (typeof payload?.text !== "string" || !payload.text.trim())
            return { ok: false, error: "No text to capture" };
        if (payload.text.length > 200000)
            return { ok: false, error: "Select a shorter passage (under 200,000 characters)" };
        await checkSite(payload.url || "", payload.capture_mode === "automatic");
        const preferences = await chrome.storage.local.get({ captureProject: "General" });
        payload = { ...payload, project: String(preferences.captureProject) };
        // Manual saves must never be swallowed by an automatic assessment of the same text.
        const id = await digest(payload.project + "\0" + (payload.capture_mode || "manual") + "\0" + (payload.url || "") + "\0" + payload.text);
        const saved = await chrome.storage.local.get({ outbox: [] });
        const outbox = Array.isArray(saved.outbox) ? saved.outbox : [];
        if (!outbox.some(item => item.id === id)) {
            if (outbox.length >= 100 || outbox.reduce((n, item) => n + item.payload.text.length, 0) + payload.text.length > 2_000_000) {
                return { ok: false, error: "Local queue is full. Start OwlThread and retry." };
            }
            outbox.push({ id, state: "ready", payload: { ...payload, source: "browser_extension", dedup_key: id } });
            await chrome.storage.local.set({ outbox });
        }
        // Acknowledge only after durable storage succeeds.
        void flushQueue().catch(() => undefined);
        void updateBadge().catch(() => undefined);
        return { ok: true };
    }
    async function stageTurn(payload) {
        const userText = typeof payload?.user_text === "string" ? payload.user_text.trim() : "";
        const turnKey = typeof payload?.turn_key === "string" && /^[A-Za-z0-9_-]{1,96}$/.test(payload.turn_key) ? payload.turn_key : "";
        const url = typeof payload?.url === "string" ? payload.url : "";
        if (!userText || userText.length > 100000 || !turnKey)
            return { ok: false, error: "The new user turn could not be staged." };
        await checkSite(url, true);
        const preferences = await chrome.storage.local.get({ captureProject: "General" });
        const project = String(preferences.captureProject || "General");
        const id = await digest(project + "\0ai-turn\0" + url + "\0" + turnKey);
        const saved = await chrome.storage.local.get({ outbox: [] });
        const outbox = Array.isArray(saved.outbox) ? saved.outbox : [];
        if (!outbox.some(item => item.id === id)) {
            const text = `User:\n${userText}`;
            if (outbox.length >= 100 || outbox.reduce((n, item) => n + (item.payload?.text?.length || 0), 0) + text.length > 2_000_000)
                return { ok: false, error: "Local queue is full. Start OwlThread and retry." };
            const platform = typeof payload.platform === "string" ? payload.platform.slice(0, 80) : "ai";
            const title = typeof payload.title === "string" ? payload.title.slice(0, 500) : "";
            const conversation = typeof payload.conversation_id === "string" ? payload.conversation_id.slice(0, 500) : "";
            outbox.push({ id, state: "staged", stagedAt: Date.now(), userText, payload: { text, source: "browser_extension", project,
                    platform, url, title, capture_mode: "automatic", capture_kind: "ai_turn", conversation_id: conversation, turn_key: turnKey, dedup_key: id } });
            await chrome.storage.local.set({ outbox });
            void updateBadge().catch(() => undefined);
        }
        return { ok: true, stage_id: id };
    }
    async function completeTurn(payload) {
        const stageId = typeof payload?.stage_id === "string" && /^[a-f0-9]{64}$/.test(payload.stage_id) ? payload.stage_id : "";
        const assistant = typeof payload?.assistant_text === "string" ? payload.assistant_text.trim() : "";
        if (!stageId || !assistant || assistant.length > 100000)
            return { ok: false, error: "The completed AI reply is invalid." };
        const saved = await chrome.storage.local.get({ outbox: [] });
        const outbox = Array.isArray(saved.outbox) ? saved.outbox : [];
        const index = outbox.findIndex(item => item.id === stageId && item.state === "staged");
        if (index < 0)
            return { ok: false, error: "The staged user turn is no longer available." };
        const item = outbox[index];
        await checkSite(item.payload.url || "", true);
        const completedUrl = typeof payload.url === "string" && OwlPolicy.newConversationTransition(item.payload.url || "", payload.url) ? payload.url : item.payload.url;
        if (completedUrl !== item.payload.url)
            await checkSite(completedUrl || "", true);
        const user = item.userText || item.payload.text.replace(/^User:\s*/i, "").trim();
        const text = `User:\n${user}\n\nAssistant:\n${assistant}`;
        if (text.length > 200000)
            return { ok: false, error: "The completed turn is too large to save." };
        outbox[index] = { ...item, state: "ready", payload: { ...item.payload, text, url: completedUrl,
                conversation_id: completedUrl !== item.payload.url && typeof payload.conversation_id === "string" ? payload.conversation_id.slice(0, 500) : item.payload.conversation_id,
                title: typeof payload.title === "string" ? payload.title.slice(0, 500) : item.payload.title } };
        await chrome.storage.local.set({ outbox });
        void flushQueue().catch(() => undefined);
        void updateBadge().catch(() => undefined);
        return { ok: true };
    }
    async function captureTab(tabId, tabUrl = "") {
        await checkSite(tabUrl);
        let payload;
        try {
            payload = await chrome.tabs.sendMessage(tabId, { type: "capture_current" });
        }
        catch { /* The current page may have no supported chat observer. */ }
        if (!payload?.text?.trim()) {
            try {
                await chrome.scripting.executeScript({ target: { tabId }, files: ["policy.js", "content.js"] });
                payload = await chrome.tabs.sendMessage(tabId, { type: "capture_current" });
            }
            catch {
                return { ok: false, error: "Open a normal website. Browser settings, new tabs and extension stores do not allow capture." };
            }
        }
        return payload?.text?.trim() ? enqueue(payload) : { ok: false, error: "This page has no visible text or completed AI turn to save." };
    }
    async function captureActive() {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        await checkSite(tab?.url || "");
        return tab?.id ? captureTab(tab.id, tab.url || "") : { ok: false, error: "Open a page to capture" };
    }
    async function injectCompanion(tabId, url = "") {
        await checkSite(url);
        await chrome.scripting.executeScript({ target: { tabId }, files: ["policy.js", "content.js", "companion.js"] });
    }
    async function restoreOpenTabs() {
        const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
        const saved = await chrome.storage.local.get(null);
        // Existing tabs otherwise do not receive new content scripts after an install/reload.
        await Promise.allSettled(tabs.filter(tab => tab.id !== undefined && !OwlPolicy.hardBlocked(OwlPolicy.host(tab.url || "")) &&
            OwlPolicy.allowed(saved, OwlPolicy.host(tab.url || ""))).map(tab => injectCompanion(tab.id, tab.url || "")));
    }
    chrome.runtime.onMessage.addListener((message, sender, respond) => {
        if (sender.id !== chrome.runtime.id || !message || typeof message.type !== "string")
            return;
        const trusted = !!sender.url?.startsWith(chrome.runtime.getURL(""));
        if (message.type === "clear_queue" && trusted) {
            void serial(() => chrome.storage.local.set({ outbox: [] })).then(() => respond({ ok: true }));
            return true;
        }
        if (message.type === "assign_legacy_queue" && trusted) {
            void serial(async () => {
                const saved = await chrome.storage.local.get({ outbox: [], captureProject: "General" });
                const outbox = Array.isArray(saved.outbox) ? saved.outbox : [];
                await chrome.storage.local.set({ outbox: outbox.map((item) => item.payload.project ? item : { ...item, payload: { ...item.payload, project: String(saved.captureProject) } }) });
            }).then(() => respond({ ok: true }));
            return true;
        }
        if (message.type === "settings_get") {
            void storageReady.then(() => chrome.storage.local.get(null)).then(saved => respond({ ok: true, settings: publicSettings(saved) }));
            return true;
        }
        if (message.type === "settings_set") {
            const values = message.values;
            if (!values || typeof values !== "object" || Array.isArray(values) || Object.keys(values).length > 20 || !Object.entries(values).every(([key, value]) => publicKey(key) && validSetting(key, value))) {
                respond({ ok: false });
                return;
            }
            void storageReady.then(() => chrome.storage.local.set(values)).then(() => respond({ ok: true })).catch(() => respond({ ok: false }));
            return true;
        }
        if (message.type === "pair") {
            if (!trusted || typeof message.token !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(message.token)) {
                respond({ ok: false, error: "Enter the pairing secret copied from desktop Settings." });
                return;
            }
            void request("/pair", {}, message.token).then(async () => { await chrome.storage.local.set({ localApiToken: message.token }); void resumeQueue().catch(() => undefined); respond({ ok: true }); }).catch(error => respond({ ok: false, error: error instanceof Error ? error.message : "Pairing failed. Check the secret and desktop connection." }));
            return true;
        }
        // A status check must not sit behind a slow extraction or offline capture retry.
        if (message.type === "health") {
            void desktopStatus().then(result => { void resumeQueue().catch(() => undefined); respond({ ok: true, ...result, connection: "connected" }); })
                .catch(error => respond({ ok: false, connection: error instanceof DesktopError ? error.connection : "error",
                error: error instanceof Error ? error.message : "Could not check the desktop connection." }));
            return true;
        }
        if (message.type === "recent_memories" && (!sender.tab || sender.url?.startsWith(chrome.runtime.getURL("")))) {
            void chrome.storage.local.get({ captureProject: "General" }).then(saved => request("/entries?limit=8&project=" + encodeURIComponent(String(saved.captureProject)))).then(result => respond({ ok: true, ...result }))
                .catch(() => respond({ ok: false, error: "Open OwlThread to view shared memories." }));
            return true;
        }
        if (message.type === "show_owl") {
            void (async () => {
                const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
                if (!tab?.id)
                    throw new Error("Open a website first.");
                await checkSite(tab.url || "");
                await chrome.storage.local.set({ companionVisible: true });
                await injectCompanion(tab.id, tab.url || "");
                return { ok: true };
            })().then(respond).catch(error => respond({ ok: false, error: String(error).includes("off on this site") ? "OwlThread is off on this site. Choose Allow in the site menu first." : "Open a normal website, then click Show owl again. Browser settings, new tabs and extension stores block extensions." }));
            return true;
        }
        if (message.type === "page_context") {
            void checkSite(sender.tab?.url || message.payload?.url || "").then(() => request("/context", message.payload)).then(result => respond({ ok: true, ...result }))
                .catch(() => respond({ ok: false, error: "Page understanding is unavailable. Check your site choice and desktop connection." }));
            return true;
        }
        void (async () => {
            if (message.type === "turn_stage") {
                const payload = { ...message.payload, ...(!trusted && sender.tab?.url ? { url: sender.tab.url } : {}) };
                return serial(() => stageTurn(payload));
            }
            if (message.type === "turn_complete") {
                const payload = { ...message.payload, ...(!trusted && sender.tab?.url ? { url: sender.tab.url } : {}) };
                return serial(() => completeTurn(payload));
            }
            if (message.type === "capture") {
                const payload = { ...message.payload, ...(!trusted && sender.tab?.url ? { url: sender.tab.url } : {}) };
                const result = await serial(() => enqueue(payload));
                if (!result.ok)
                    await chrome.storage.local.set({ lastError: result.error });
                return result;
            }
            if (message.type === "capture_active")
                return serial(captureActive);
            if (message.type === "capture_tab" && sender.tab?.id !== undefined) {
                await checkSite(sender.tab.url || "");
                return serial(() => captureTab(sender.tab.id, sender.tab.url || ""));
            }
            if (message.type === "retry") {
                await desktopStatus();
                return resumeQueue();
            }
            if (message.type === "flush") {
                const synced = await resumeQueue();
                if (!synced.ok)
                    return synced;
                const remaining = await chrome.storage.local.get({ outbox: [] });
                if (Array.isArray(remaining.outbox) && remaining.outbox.length)
                    return { ok: false, error: "Some captures are still syncing. Retry extraction in a moment." };
                return { ok: true, ...await request("/flush", {}) };
            }
            return { ok: false, error: "Unknown command" };
        })().then(respond).catch(error => respond({ ok: false, error: String(error) }));
        return true;
    });
    chrome.commands.onCommand.addListener(command => {
        if (command === "capture_selection") {
            void serial(captureActive).then(async (result) => {
                if (!result.ok)
                    await chrome.storage.local.set({ lastError: result.error });
            }).catch(() => undefined);
        }
    });
    chrome.alarms.onAlarm.addListener(alarm => {
        if (alarm.name === "retry-captures")
            void flushQueue().catch(() => undefined);
    });
    chrome.runtime.onInstalled.addListener(() => { void restoreOpenTabs().catch(() => undefined); void flushQueue().catch(() => undefined); });
    chrome.runtime.onStartup.addListener(() => { void restoreOpenTabs().catch(() => undefined); void flushQueue().catch(() => undefined); });
    void chrome.alarms.create("retry-captures", { periodInMinutes: 1 });
    // A woken/reloaded service worker must not leave its existing queue waiting for an alarm.
    void storageReady.then(() => flushQueue()).catch(() => undefined);
})();
