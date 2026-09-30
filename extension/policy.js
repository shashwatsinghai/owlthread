"use strict";
/** Shared site choices and immutable privacy boundaries. */
var OwlPolicy;
(function (OwlPolicy) {
    /** These domains are never inspected, injected into, queued, or sent to desktop. */
    OwlPolicy.hardBlockedSites = [
        "youtube.com", "youtu.be", "netflix.com", "primevideo.com", "disneyplus.com",
        "hotstar.com", "hulu.com", "twitch.tv", "spotify.com", "tiktok.com",
        "instagram.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
        "snapchat.com", "pinterest.com", "vimeo.com", "dailymotion.com", "kick.com",
        "soundcloud.com", "discord.com"
    ];
    OwlPolicy.aiSites = ["chatgpt.com", "chat.openai.com", "claude.ai", "chat.deepseek.com"];
    function normalizeHost(hostname) {
        return String(hostname || "").trim().toLowerCase().replace(/\.+$/, "").replace(/^www\./, "");
    }
    OwlPolicy.normalizeHost = normalizeHost;
    function host(url) {
        try {
            const parsed = new URL(url);
            return /^https?:$/.test(parsed.protocol) && !parsed.username && !parsed.password ? normalizeHost(parsed.hostname) : "";
        }
        catch {
            return "";
        }
    }
    OwlPolicy.host = host;
    /** AI apps assign a new chat URL after the first send without changing the page. */
    function newConversationTransition(from, to) {
        try {
            const before = new URL(from), after = new URL(to);
            if (before.origin !== after.origin || before.username || before.password || after.username || after.password)
                return false;
            const hostname = normalizeHost(before.hostname);
            if (["chatgpt.com", "chat.openai.com"].includes(hostname))
                return /^\/$/.test(before.pathname) && /^\/c\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
            if (hostname === "claude.ai")
                return /^\/(?:new)?\/?$/.test(before.pathname) && /^\/chat\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
            if (hostname === "chat.deepseek.com")
                return /^\/$/.test(before.pathname) && /^\/a\/chat\/s\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
            return false;
        }
        catch {
            return false;
        }
    }
    OwlPolicy.newConversationTransition = newConversationTransition;
    function key(hostname) { return "siteMode:" + hostname; }
    OwlPolicy.key = key;
    function hardBlocked(hostname) {
        const clean = normalizeHost(hostname);
        return OwlPolicy.hardBlockedSites.some(site => clean === site || clean.endsWith("." + site));
    }
    OwlPolicy.hardBlocked = hardBlocked;
    function mode(settings, hostname) {
        hostname = normalizeHost(hostname);
        if (hardBlocked(hostname))
            return "blocked";
        // A parent-domain refusal also covers its subdomains.
        const parts = hostname.split(".");
        for (let i = 0; i < parts.length - 1; i++) {
            if (settings[key(parts.slice(i).join("."))] === "blocked")
                return "blocked";
        }
        return settings[key(hostname)] === "allowed" ? "allowed" : "default";
    }
    OwlPolicy.mode = mode;
    function allowed(settings, hostname) {
        const choice = mode(settings, hostname);
        return !!normalizeHost(hostname) && choice !== "blocked";
    }
    OwlPolicy.allowed = allowed;
    // Old content scripts can outlive an extension reload, losing the runtime API.
    let invalidated = false;
    function runtime() {
        try {
            return !invalidated && typeof chrome !== "undefined" && chrome.runtime?.id ? chrome.runtime : undefined;
        }
        catch {
            return undefined;
        }
    }
    function runtimeAvailable() { return !!runtime(); }
    OwlPolicy.runtimeAvailable = runtimeAvailable;
    function getURL(path) {
        try {
            return runtime()?.getURL(path);
        }
        catch {
            return undefined;
        }
    }
    OwlPolicy.getURL = getURL;
    async function sendMessage(message) {
        const current = runtime();
        if (!current)
            throw new Error("Extension updated. Refresh this tab to reconnect your owl.");
        try {
            return await current.sendMessage(message);
        }
        catch (error) {
            if (String(error).includes("Extension context invalidated"))
                invalidated = true;
            if (!runtimeAvailable())
                throw new Error("Extension updated. Refresh this tab to reconnect your owl.");
            throw error;
        }
    }
    OwlPolicy.sendMessage = sendMessage;
    // Reinjection reuses this namespace. Retire its previous listeners before replacing
    // the maps, while their original event handles are still available for cleanup.
    const previousCleanup = OwlPolicy.disposeListeners;
    if (typeof previousCleanup === "function")
        previousCleanup();
    const messageListeners = new Map();
    function addMessageListener(listener) {
        if (messageListeners.has(listener))
            return true;
        try {
            const channel = runtime()?.onMessage;
            if (!channel)
                return false;
            channel.addListener(listener);
            messageListeners.set(listener, channel);
            return true;
        }
        catch {
            return false;
        }
    }
    OwlPolicy.addMessageListener = addMessageListener;
    function removeMessageListener(listener) {
        const channel = messageListeners.get(listener);
        messageListeners.delete(listener);
        // An invalidated event handle may throw even when chrome.runtime is absent.
        try {
            channel?.removeListener(listener);
        }
        catch { /* Continue DOM cleanup. */ }
    }
    OwlPolicy.removeMessageListener = removeMessageListener;
    // Content scripts receive only safe preferences and a queue count from the worker.
    async function settings() {
        const reply = await sendMessage({ type: "settings_get" });
        if (!reply?.ok)
            throw new Error("Extension settings unavailable");
        return reply.settings;
    }
    OwlPolicy.settings = settings;
    async function save(values) {
        const reply = await sendMessage({ type: "settings_set", values });
        if (!reply?.ok)
            throw new Error("Could not save preferences");
    }
    OwlPolicy.save = save;
    const listeners = new Map();
    function onChange(listener) {
        if (listeners.has(listener))
            return true;
        const bridge = (message) => {
            if (message?.type === "public_settings_changed" && message.changes && typeof message.changes === "object" && !Array.isArray(message.changes))
                listener(message.changes, "local");
        };
        if (!addMessageListener(bridge))
            return false;
        listeners.set(listener, bridge);
        return true;
    }
    OwlPolicy.onChange = onChange;
    function removeChange(listener) {
        const bridge = listeners.get(listener);
        if (bridge)
            removeMessageListener(bridge);
        listeners.delete(listener);
    }
    OwlPolicy.removeChange = removeChange;
    function disposeListeners() {
        for (const listener of messageListeners.keys())
            removeMessageListener(listener);
        listeners.clear();
    }
    OwlPolicy.disposeListeners = disposeListeners;
    function pageText() {
        const blocked = "input,textarea,select,option,[contenteditable],script,style,noscript,[hidden],[aria-hidden=true],#owlthread-companion";
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode(node) {
                const parent = node.parentElement;
                if (!parent || parent.closest(blocked) || !parent.getClientRects().length)
                    return NodeFilter.FILTER_REJECT;
                const style = getComputedStyle(parent);
                if (style.visibility === "hidden" || style.display === "none")
                    return NodeFilter.FILTER_REJECT;
                for (let element = parent; element; element = element.parentElement) {
                    if (getComputedStyle(element).opacity === "0")
                        return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            } });
        let text = "", node;
        while (text.length < 6000 && (node = walker.nextNode()))
            text += (node.nodeValue || "").replace(/\s+/g, " ") + " ";
        return text.trim().slice(0, 6000);
    }
    OwlPolicy.pageText = pageText;
    function sanitizedText(root, limit = 12000) {
        const clone = root.cloneNode(true);
        clone.querySelectorAll("input,textarea,select,option,button,script,style,noscript,[contenteditable],[hidden],[aria-hidden=true],#owlthread-companion").forEach(node => node.remove());
        return (clone.innerText || clone.textContent || "").replace(/\s+/g, " ").trim().slice(0, limit);
    }
    OwlPolicy.sanitizedText = sanitizedText;
    function pageSelection() {
        const selection = window.getSelection();
        const node = selection?.anchorNode;
        const parent = node instanceof Element ? node : node?.parentElement;
        if (parent?.closest("input,textarea,select,[contenteditable]"))
            return "";
        if (selection?.rangeCount) {
            const fields = document.querySelectorAll("input,textarea,select,[contenteditable],[hidden],[aria-hidden=true]");
            for (let i = 0; i < selection.rangeCount; i++) {
                const range = selection.getRangeAt(i);
                if (Array.from(fields).some(field => range.intersectsNode(field)))
                    return "";
            }
        }
        return (selection?.toString() || "").trim().slice(0, 4000);
    }
    OwlPolicy.pageSelection = pageSelection;
})(OwlPolicy || (OwlPolicy = {}));
