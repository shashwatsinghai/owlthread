/** Shared site choices and immutable privacy boundaries. */
namespace OwlPolicy {
  export type Mode = "default" | "allowed" | "blocked";
  /** These domains are never inspected, injected into, queued, or sent to desktop. */
  export const hardBlockedSites = [
    "youtube.com", "youtu.be", "netflix.com", "primevideo.com", "disneyplus.com",
    "hotstar.com", "hulu.com", "twitch.tv", "spotify.com", "tiktok.com",
    "instagram.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
    "snapchat.com", "pinterest.com", "vimeo.com", "dailymotion.com", "kick.com",
    "soundcloud.com", "discord.com"
  ] as const;
  export const aiSites = ["chatgpt.com", "chat.openai.com", "claude.ai", "chat.deepseek.com"];
  export function normalizeHost(hostname: string): string {
    return String(hostname || "").trim().toLowerCase().replace(/\.+$/, "").replace(/^www\./, "");
  }
  export function host(url: string): string {
    try { const parsed = new URL(url); return /^https?:$/.test(parsed.protocol) && !parsed.username && !parsed.password ? normalizeHost(parsed.hostname) : ""; }
    catch { return ""; }
  }
  /** AI apps assign a new chat URL after the first send without changing the page. */
  export function newConversationTransition(from:string,to:string):boolean {
    try {
      const before=new URL(from),after=new URL(to);
      if(before.origin!==after.origin || before.username || before.password || after.username || after.password) return false;
      const hostname=normalizeHost(before.hostname);
      if(["chatgpt.com","chat.openai.com"].includes(hostname)) return /^\/$/.test(before.pathname) && /^\/c\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
      if(hostname==="claude.ai") return /^\/(?:new)?\/?$/.test(before.pathname) && /^\/chat\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
      if(hostname==="chat.deepseek.com") return /^\/$/.test(before.pathname) && /^\/a\/chat\/s\/[A-Za-z0-9_-]+\/?$/.test(after.pathname);
      return false;
    } catch {return false;}
  }
  export function key(hostname: string): string { return "siteMode:" + hostname; }
  export function hardBlocked(hostname: string): boolean {
    const clean = normalizeHost(hostname);
    return hardBlockedSites.some(site => clean === site || clean.endsWith("." + site));
  }
  export function mode(settings: Record<string, unknown>, hostname: string): Mode {
    hostname = normalizeHost(hostname);
    if (hardBlocked(hostname)) return "blocked";
    // A parent-domain refusal also covers its subdomains.
    const parts = hostname.split(".");
    for (let i = 0; i < parts.length - 1; i++) {
      if (settings[key(parts.slice(i).join("."))] === "blocked") return "blocked";
    }
    return settings[key(hostname)] === "allowed" ? "allowed" : "default";
  }
  export function allowed(settings: Record<string, unknown>, hostname: string): boolean {
    const choice = mode(settings, hostname);
    return !!normalizeHost(hostname) && choice !== "blocked";
  }

  // Content scripts receive only safe preferences and a queue count from the worker.
  export async function settings(): Promise<Record<string, any>> {
    const reply = await chrome.runtime.sendMessage({type:"settings_get"});
    if (!reply?.ok) throw new Error("Extension settings unavailable");
    return reply.settings;
  }
  export async function save(values: Record<string, unknown>): Promise<void> {
    const reply = await chrome.runtime.sendMessage({type:"settings_set", values});
    if (!reply?.ok) throw new Error("Could not save preferences");
  }
  type Listener = (changes: {[key:string]:chrome.storage.StorageChange}, area:string) => void;
  const listeners = new Map<Listener, (message:any) => void>();
  export function onChange(listener: Listener): void {
    const bridge = (message:any):void => { if(message.type === "public_settings_changed") listener(message.changes,"local"); };
    listeners.set(listener,bridge);
    chrome.runtime.onMessage.addListener(bridge);
  }
  export function removeChange(listener: Listener): void {
    const bridge=listeners.get(listener);
    if(bridge) chrome.runtime.onMessage.removeListener(bridge);
    listeners.delete(listener);
  }

  export function pageText(): string {
    const blocked="input,textarea,select,option,[contenteditable],script,style,noscript,[hidden],[aria-hidden=true],#owlthread-companion";
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode(node){
      const parent=node.parentElement;
      if(!parent || parent.closest(blocked) || !parent.getClientRects().length) return NodeFilter.FILTER_REJECT;
      const style=getComputedStyle(parent);
      if(style.visibility==="hidden" || style.display==="none") return NodeFilter.FILTER_REJECT;
      for(let element:Element|null=parent;element;element=element.parentElement){
        if(getComputedStyle(element).opacity==="0") return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    }});
    let text="",node:Node|null;
    while(text.length<6000 && (node=walker.nextNode())) text+=(node.nodeValue || "").replace(/\s+/g," ")+" ";
    return text.trim().slice(0,6000);
  }

  export function sanitizedText(root: Element, limit = 12000): string {
    const clone = root.cloneNode(true) as Element;
    clone.querySelectorAll("input,textarea,select,option,button,script,style,noscript,[contenteditable],[hidden],[aria-hidden=true],#owlthread-companion").forEach(node => node.remove());
    return ((clone as HTMLElement).innerText || clone.textContent || "").replace(/\s+/g, " ").trim().slice(0, limit);
  }

  export function pageSelection():string {
    const selection=window.getSelection();
    const node=selection?.anchorNode;
    const parent=node instanceof Element ? node : node?.parentElement;
    if(parent?.closest("input,textarea,select,[contenteditable]")) return "";
    if(selection?.rangeCount){
      const fields=document.querySelectorAll("input,textarea,select,[contenteditable],[hidden],[aria-hidden=true]");
      for(let i=0;i<selection.rangeCount;i++){
        const range=selection.getRangeAt(i);
        if(Array.from(fields).some(field=>range.intersectsNode(field))) return "";
      }
    }
    return (selection?.toString() || "").trim().slice(0,4000);
  }
}
