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
    // Content scripts receive only safe preferences and a queue count from the worker.
    async function settings() {
        const reply = await chrome.runtime.sendMessage({ type: "settings_get" });
        if (!reply?.ok)
            throw new Error("Extension settings unavailable");
        return reply.settings;
    }
    OwlPolicy.settings = settings;
    async function save(values) {
        const reply = await chrome.runtime.sendMessage({ type: "settings_set", values });
        if (!reply?.ok)
            throw new Error("Could not save preferences");
    }
    OwlPolicy.save = save;
    const listeners = new Map();
    function onChange(listener) {
        const bridge = (message) => { if (message.type === "public_settings_changed")
            listener(message.changes, "local"); };
        listeners.set(listener, bridge);
        chrome.runtime.onMessage.addListener(bridge);
    }
    OwlPolicy.onChange = onChange;
    function removeChange(listener) {
        const bridge = listeners.get(listener);
        if (bridge)
            chrome.runtime.onMessage.removeListener(bridge);
        listeners.delete(listener);
    }
    OwlPolicy.removeChange = removeChange;
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
