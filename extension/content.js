"use strict";
/**
 * Role-aware, incremental AI-turn capture plus an explicit sanitized snapshot.
 * Existing chat history is seeded as a baseline and is never replayed automatically.
 */
(() => {
    const hostname = OwlPolicy.normalizeHost(location.hostname);
    // This check intentionally happens before listeners, settings reads, or DOM work.
    if (OwlPolicy.hardBlocked(hostname))
        return;
    const platforms = {
        "chatgpt.com": {
            name: "chatgpt",
            assistantSelector: '[data-message-author-role="assistant"]',
            userSelector: '[data-message-author-role="user"]',
            composerSelector: '#prompt-textarea, textarea, [contenteditable="true"][role="textbox"]',
            sendSelector: '[data-testid="send-button"], button[aria-label="Send prompt"], button[aria-label="Send message"]'
        },
        "chat.openai.com": {
            name: "chatgpt",
            assistantSelector: '[data-message-author-role="assistant"]',
            userSelector: '[data-message-author-role="user"]',
            composerSelector: '#prompt-textarea, textarea, [contenteditable="true"][role="textbox"]',
            sendSelector: '[data-testid="send-button"], button[aria-label="Send prompt"], button[aria-label="Send message"]'
        },
        "claude.ai": {
            name: "claude",
            assistantSelector: '[data-testid="assistant-message"], .font-claude-message',
            userSelector: '[data-testid="user-message"], [data-testid="human-message"], .font-user-message',
            composerSelector: '[contenteditable="true"][role="textbox"], div.ProseMirror, textarea',
            sendSelector: 'button[aria-label="Send Message"], button[aria-label="Send message"], button[data-testid="send-button"]'
        },
        "chat.deepseek.com": {
            name: "deepseek",
            assistantSelector: '.ds-markdown, [data-message-author-role="assistant"]',
            userSelector: '[data-message-author-role="user"], [data-testid="user-message"], .ds-message-user',
            composerSelector: 'textarea, [contenteditable="true"][role="textbox"]',
            sendSelector: 'button[aria-label="Send"], button[aria-label="Send message"], [data-testid="send-button"]'
        }
    };
    const platform = platforms[hostname];
    const stopSelector = '[data-testid="stop-button"], button[aria-label="Stop response"], button[aria-label="Stop generating"], [data-is-streaming="true"], .result-streaming';
    const copySelector = '[data-testid="copy-turn-action-button"], button[aria-label="Copy"], button[aria-label="Copy response"], button[aria-label="Copy message"], button[data-testid="copy-message-button"], [role="button"][aria-label="Copy"]';
    // Reinstalling into an already open tab retires all listeners from the old copy.
    window.dispatchEvent(new Event("owlthread:dispose-observer"));
    function nodeText(node, limit = 100000) {
        return OwlPolicy.sanitizedText(node, limit);
    }
    function fieldText(element) {
        if (!element)
            return "";
        if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)
            return element.value.trim();
        return (element.innerText || element.textContent || "").trim();
    }
    function visibleComposer(scope) {
        if (!platform)
            return null;
        const local = scope?.querySelector(platform.composerSelector);
        if (local)
            return local;
        const candidates = [...document.querySelectorAll(platform.composerSelector)];
        return candidates.reverse().find(node => {
            const element = node;
            return !element.hidden && element.getAttribute("aria-hidden") !== "true";
        }) || null;
    }
    function eventPrompt(event) {
        if (!platform || !(event.target instanceof Element))
            return "";
        const target = event.target;
        const direct = target.closest(platform.composerSelector);
        if (direct)
            return fieldText(direct);
        const form = target.closest("form") || (target.matches("form") ? target : null);
        return fieldText(visibleComposer(form));
    }
    function conversationId() {
        const path = location.pathname.replace(/\/+$/, "") || "/";
        return `${platform?.name || "page"}:${hostname}:${path}`.slice(0, 500);
    }
    function formatTurn(userText, assistantText) {
        const user = userText.trim();
        const assistant = (assistantText || "").trim();
        return assistant ? `User:\n${user}\n\nAssistant:\n${assistant}` : `User:\n${user}`;
    }
    function currentSnapshot() {
        if (platform) {
            const assistant = [...document.querySelectorAll(platform.assistantSelector)]
                .filter(node => !node.parentElement?.closest(platform.assistantSelector))
                .filter(node => observer.completed(node)).at(-1);
            const users = [...document.querySelectorAll(platform.userSelector)]
                .filter(node => !node.parentElement?.closest(platform.userSelector));
            const user = assistant ? users.filter(candidate => !!(candidate.compareDocumentPosition(assistant) & Node.DOCUMENT_POSITION_FOLLOWING)).at(-1) : users.at(-1);
            const userText = user ? nodeText(user) : "";
            const assistantText = assistant ? nodeText(assistant) : "";
            const text = userText ? formatTurn(userText, assistantText) : assistantText ? `Assistant:\n${assistantText}` : "";
            return { text, platform: platform.name, url: location.href, title: document.title,
                capture_mode: "manual", capture_kind: "current_turn", conversation_id: conversationId() };
        }
        const visible = OwlPolicy.pageText();
        const heading = [document.title.trim() && `Title: ${document.title.trim()}`, `URL: ${location.href}`].filter(Boolean).join("\n");
        return { text: visible ? `${heading}\n\n${visible}` : heading, platform: "web", url: location.href,
            title: document.title, capture_mode: "manual", capture_kind: "current_page", conversation_id: conversationId() };
    }
    class ResilientTurnObserver {
        captured = new Set();
        pendingHashes = new Set();
        timer;
        enabled = false;
        page = location.href;
        armedAt = 0;
        lastArmAt = 0;
        turn;
        baselineUsers = new WeakMap();
        baselineAssistants = new WeakMap();
        mutationObserver = new MutationObserver(records => {
            if (!platform)
                return;
            const selectors = [platform.userSelector, platform.assistantSelector, stopSelector, copySelector].join(",");
            if (records.some(record => {
                const target = record.target.nodeType === 1 ? record.target : record.target.parentElement;
                return !!target?.closest(platform.userSelector + "," + platform.assistantSelector) ||
                    [...record.addedNodes, ...record.removedNodes].some(node => node instanceof Element && (node.matches(selectors) || !!node.querySelector(selectors))) ||
                    !!target?.matches(stopSelector + "," + copySelector);
            }))
                this.schedule();
        });
        seed() {
            if (!platform)
                return;
            this.page = location.href;
            this.baselineUsers = new WeakMap();
            this.baselineAssistants = new WeakMap();
            for (const node of document.querySelectorAll(platform.userSelector))
                this.baselineUsers.set(node, nodeText(node));
            for (const node of document.querySelectorAll(platform.assistantSelector))
                this.baselineAssistants.set(node, nodeText(node));
        }
        newKey() {
            const random = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : Math.random().toString(36).slice(2);
            return `${Date.now().toString(36)}-${random}`.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 96);
        }
        beginStage(userText) {
            if (!platform || !this.turn || this.turn.stage || !userText.trim())
                return;
            this.turn.userText = userText.trim().slice(0, 100000);
            const payload = { user_text: this.turn.userText, turn_key: this.turn.key, platform: platform.name,
                url: this.turn.page, title: document.title, conversation_id: conversationId() };
            this.turn.stage = chrome.runtime.sendMessage({ type: "turn_stage", payload }).then((reply) => reply?.ok && reply.stage_id ? reply.stage_id : undefined).catch(() => undefined);
        }
        arm(userText = "") {
            if (!this.enabled || !platform)
                return;
            const now = Date.now();
            if (this.turn && this.turn.page === location.href && now - this.lastArmAt < 2000 &&
                (!userText.trim() || !this.turn.userText || this.turn.userText === userText.trim())) {
                if (userText.trim())
                    this.beginStage(userText);
                return;
            }
            this.seed();
            this.armedAt = now;
            this.lastArmAt = now;
            this.turn = { key: this.newKey(), page: location.href, userText: "", stagedAt: now, stage: undefined };
            this.beginStage(userText);
            this.schedule();
        }
        start() {
            if (!platform)
                return;
            this.mutationObserver.observe(document.documentElement, { subtree: true, childList: true, characterData: true,
                attributes: true, attributeFilter: ["data-is-streaming", "aria-busy", "disabled", "aria-label", "data-testid", "class"] });
            this.schedule();
        }
        stop() {
            this.mutationObserver.disconnect();
            clearTimeout(this.timer);
        }
        setEnabled(enabled) {
            if (!platform || enabled === this.enabled)
                return;
            this.enabled = enabled;
            this.armedAt = 0;
            this.turn = undefined;
            if (enabled) {
                this.seed();
                this.start();
            }
            else
                this.stop();
        }
        resume() { if (this.enabled)
            this.start(); }
        schedule() {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => { void this.scan(); }, 1500);
        }
        completed(node) {
            if (document.querySelector(stopSelector) || node.closest('[aria-busy="true"], [data-is-streaming="true"]'))
                return false;
            let ancestor = node.parentElement;
            for (let depth = 0; ancestor && depth < 5 && ancestor !== document.body; depth++, ancestor = ancestor.parentElement) {
                if (platform && [...ancestor.querySelectorAll(platform.assistantSelector)].filter(candidate => !candidate.parentElement?.closest(platform.assistantSelector)).length > 1)
                    break;
                if ([...ancestor.querySelectorAll(copySelector)].some(control => !node.contains(control)))
                    return true;
            }
            return node.getAttribute("data-is-streaming") === "false";
        }
        async scan() {
            if (!this.enabled || !platform || !this.turn)
                return;
            if (this.page !== location.href || this.turn.page !== location.href) {
                if (OwlPolicy.newConversationTransition(this.turn.page, location.href)) {
                    this.page = location.href;
                    this.turn.page = location.href;
                }
                else {
                    this.captured.clear();
                    this.armedAt = 0;
                    this.turn = undefined;
                    this.seed();
                    return;
                }
            }
            if (!this.armedAt || Date.now() - this.armedAt > 600000)
                return;
            const turn = this.turn;
            if (!this.turn.userText) {
                const newUser = [...document.querySelectorAll(platform.userSelector)]
                    .filter(node => !node.parentElement?.closest(platform.userSelector))
                    .filter(node => this.baselineUsers.get(node) !== nodeText(node)).at(-1);
                if (newUser)
                    this.beginStage(nodeText(newUser));
            }
            if (!this.turn.stage || !this.turn.userText)
                return;
            const node = [...document.querySelectorAll(platform.assistantSelector)]
                .filter(candidate => !candidate.parentElement?.closest(platform.assistantSelector))
                .filter(candidate => this.baselineAssistants.get(candidate) !== nodeText(candidate)).at(-1);
            if (!node || !this.completed(node) || !node.isConnected)
                return;
            const text = nodeText(node);
            if (!text || text.length > 100000)
                return;
            const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(turn.key + "\0" + text));
            const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
            if (!this.enabled || this.turn !== turn || !this.completed(node) || this.captured.has(hash) || this.pendingHashes.has(hash) || !node.isConnected)
                return;
            if (nodeText(node) !== text)
                return;
            const stageId = await turn.stage;
            if (!stageId || this.turn !== turn || !this.enabled || !this.completed(node) || nodeText(node) !== text)
                return;
            this.pendingHashes.add(hash);
            try {
                const reply = await chrome.runtime.sendMessage({ type: "turn_complete", payload: {
                        stage_id: stageId, assistant_text: text, title: document.title, url: turn.page, conversation_id: conversationId()
                    } });
                if (reply?.ok) {
                    this.captured.add(hash);
                    if (this.captured.size > 2000)
                        this.captured.delete(this.captured.values().next().value);
                    if (this.turn === turn) {
                        this.armedAt = 0;
                        this.turn = undefined;
                    }
                }
            }
            catch {
                if (!chrome.runtime.id)
                    dispose();
            }
            finally {
                this.pendingHashes.delete(hash);
            }
        }
    }
    const observer = new ResilientTurnObserver();
    let disposed = false;
    let settingsRevision = 0;
    function loadSettings() {
        if (!platform)
            return;
        const revision = ++settingsRevision;
        void OwlPolicy.settings().then(settings => {
            if (!disposed && revision === settingsRevision)
                observer.setEnabled(settings.enabled !== false && OwlPolicy.allowed(settings, hostname));
        }).catch(() => dispose());
    }
    loadSettings();
    const onSettings = (changes, area) => {
        if (area && area !== "local")
            return;
        if (changes.enabled || Object.keys(changes).some(key => key.startsWith("siteMode:")))
            loadSettings();
    };
    const onMessage = (message, _sender, respond) => {
        if (message.type !== "capture_current")
            return;
        respond(currentSnapshot());
    };
    const onHide = () => observer.stop();
    const onShow = () => observer.resume();
    const onSubmit = (event) => observer.arm(eventPrompt(event));
    const onKey = (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.target instanceof Element &&
            event.target.closest(platform?.composerSelector || "__never__"))
            observer.arm(eventPrompt(event));
    };
    const onClick = (event) => {
        if (platform && event.target instanceof Element && event.target.closest(platform.sendSelector))
            observer.arm(eventPrompt(event));
    };
    function dispose() {
        disposed = true;
        observer.stop();
        OwlPolicy.removeChange(onSettings);
        chrome.runtime.onMessage.removeListener(onMessage);
        window.removeEventListener("pagehide", onHide);
        window.removeEventListener("pageshow", onShow);
        window.removeEventListener("owlthread:dispose-observer", dispose);
        document.removeEventListener("submit", onSubmit, true);
        document.removeEventListener("keydown", onKey, true);
        document.removeEventListener("click", onClick, true);
    }
    OwlPolicy.onChange(onSettings);
    chrome.runtime.onMessage.addListener(onMessage);
    window.addEventListener("pagehide", onHide);
    window.addEventListener("pageshow", onShow);
    window.addEventListener("owlthread:dispose-observer", dispose, { once: true });
    if (platform) {
        document.addEventListener("submit", onSubmit, true);
        document.addEventListener("keydown", onKey, true);
        document.addEventListener("click", onClick, true);
    }
})();
