(() => {
  const get = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
  const toggles: Record<string, string> = {enabled: "enabled", visible: "companionVisible", motion: "companionMotion"};
  let refreshing = false, actionVersion = 0, hostname = "", settingsVersion = 0, busy = false;
  let savedSettings: Record<string, unknown> = {};
  get("pair").addEventListener("click",async()=>{
    const input=get<HTMLInputElement>("pair-token");
    const token=input.value.trim();input.value="";
    const result=await chrome.runtime.sendMessage({type:"pair",token});
    notice(result?.ok ? "Paired. Your manual notes can now sync." : result?.error || "Pairing failed",!result?.ok);
    await refresh(false);
  });
  get("save-project").addEventListener("click",async()=>{
    const project=get<HTMLInputElement>("capture-project").value.trim();
    if(!project || project.length>100 || /[\x00-\x1f]/.test(project)){notice("Enter a project name of 1 to 100 characters.",true);return;}
    await chrome.storage.local.set({captureProject:project});notice("New captures will be saved to "+project+".");
  });
  get("queue").addEventListener("toggle",async()=>{
    const saved=await chrome.storage.local.get({outbox:[]});
    get("queue-items").textContent=(Array.isArray(saved.outbox) ? saved.outbox : []).map((item:any)=>`${item.payload.project || "Unassigned legacy capture"}\n${item.payload.text}`).join("\n\n") || "No queued captures.";
  });
  get("clear-queue").addEventListener("click",async()=>{
    await chrome.runtime.sendMessage({type:"clear_queue"});get("queue-items").textContent="Queue cleared. Captures already sent to desktop remain there.";await settings();
  });
  get("assign-legacy").addEventListener("click",async()=>{await chrome.runtime.sendMessage({type:"assign_legacy_queue"});notice("Older notes assigned to your selected project. Reconnect to sync.");});
  function notice(text: string, error = false): void {
    get("notice").textContent = text; get("notice").classList.toggle("error", error);
  }
  function renderSite(): void {
    const permanentlyBlocked = OwlPolicy.hardBlocked(hostname);
    const allowed = OwlPolicy.allowed(savedSettings, hostname);
    get<HTMLSelectElement>("site-mode").value = OwlPolicy.mode(savedSettings, hostname);
    get<HTMLSelectElement>("site-mode").disabled = !hostname || permanentlyBlocked;
    get<HTMLButtonElement>("capture").disabled = busy || !allowed;
    get<HTMLButtonElement>("show").disabled = busy || !allowed;
    get("site-hint").textContent = !hostname ? "Open a regular website to use your owl." :
      permanentlyBlocked ? "Permanently blocked here: no owl, capture, page reading, queueing, or override." :
      OwlPolicy.mode(savedSettings, hostname) === "blocked" ? "Your choice is saved. No owl or new captures here until you allow it." :
      !allowed ? "Quiet by default. Allow the owl only if you want it here." :
      OwlPolicy.aiSites.includes(hostname) ? "New user prompts are staged immediately; completed replies join the same saved turn. Old history is left alone." :
      "Press Remember to save a sanitized page snapshot. No selection needed.";
  }
  async function settings(): Promise<void> {
    const revision = ++settingsVersion;
    const saved = await chrome.storage.local.get(null);
    if (revision !== settingsVersion) return;
    savedSettings = saved;
    if(document.activeElement!==get("capture-project")) get<HTMLInputElement>("capture-project").value=String(saved.captureProject || "General");
    for (const [id, key] of Object.entries(toggles)) get<HTMLInputElement>(id).checked = saved[key] !== false;
    get("queued").textContent = String(Array.isArray(saved.outbox) ? saved.outbox.length : 0);
    renderSite();
  }
  async function refresh(updateNotice = true): Promise<void> {
    if (refreshing) return;
    refreshing = true;
    const version = actionVersion;
    try {
      await settings();
      const health = await chrome.runtime.sendMessage({type: "health"});
      get("status").textContent = health?.ok ? "Desktop connected" : "Desktop offline";
      get("status").classList.toggle("online", health?.ok === true);
      get("connection-dot").classList.toggle("online", health?.ok === true);
      get("model").textContent = health?.ok ? health.model_ready && health.model_name ?
        "AI synthesis · " + health.model_name + " · managed in app" : "Automatic raw capture works locally; configure a model only for synthesis." :
        "Manual notes wait here. Open OwlThread to connect.";
      get("memories").textContent = health?.ok ? String(health.total_entries ?? 0) : "—";
      get("pending").textContent = health?.ok ? String(health.pending_captures ?? 0) : "—";
      if (updateNotice && version === actionVersion) notice(health?.ok ?
        "One memory across your browsers. Model settings and full history stay in OwlThread." :
        "Saves queue locally while the desktop is offline, including staged AI prompts.");
    } catch {
      get("status").textContent = "Connection unavailable";
      if (version === actionVersion) notice("Reload the extension, then reopen this popup.", true);
    } finally { refreshing = false; }
  }
  for (const [id, key] of Object.entries(toggles)) {
    get(id).addEventListener("change", async () => {
      actionVersion++;
      try { await chrome.storage.local.set({[key]: get<HTMLInputElement>(id).checked}); }
      catch { await settings(); notice("Could not save this setting. Please try again.", true); }
    });
  }
  get("site-mode").addEventListener("change", async () => {
    if (!hostname) return;
    actionVersion++;
    const choice = get<HTMLSelectElement>("site-mode").value;
    try {
      await chrome.storage.local.set({[OwlPolicy.key(hostname)]: choice});
      await settings();
      notice(choice === "blocked" ? "Saved. OwlThread will stay off on this site." : "Site choice saved.");
    } catch { await settings(); notice("Could not save your site choice. Please try again.", true); }
  });
  for (const [id, type] of [["show", "show_owl"], ["capture", "capture_active"], ["flush", "flush"], ["retry", "retry"]]) {
    get(id).addEventListener("click", async () => {
      if (busy) return;
      busy = true; actionVersion++;
      const buttons = ["show", "capture", "flush", "retry"];
      for (const button of buttons) get<HTMLButtonElement>(button).disabled = true;
      notice(type === "flush" ? "Extracting saved captures…" : type === "retry" ? "Reconnecting and syncing your notes…" : type === "show_owl" ? "Restoring your owl…" : "Saving the current turn or page…");
      try {
        const result = await chrome.runtime.sendMessage({type});
        await settings();
        if (!result?.ok) { notice(result?.error || "Could not complete the request.", true); return; }
        await refresh(false);
        const count = result.total_extracted ?? 0;
        notice(type === "show_owl" ? "Your small owl is on the page. Close this popup to meet it." :
          type === "retry" ? "Connected. Your saved notes have synced to OwlThread." :
          type === "flush" ? "Extracted " + count + " " + (count === 1 ? "memory" : "memories") + "." + (result.errors?.length ? " Some captures need another try." : "") :
          "Remembered. Saved here for sync to OwlThread.");
      } catch { notice("Could not connect to the extension. Reload it and try again.", true); }
      finally {
        busy = false;
        for (const button of buttons) get<HTMLButtonElement>(button).disabled = false;
        renderSite();
      }
    });
  }
  get("recent").addEventListener("toggle", async () => {
    if (!get<HTMLDetailsElement>("recent").open) return;
    const history = get("history");
    history.textContent = "Loading from OwlThread…";
    try {
      const result = await chrome.runtime.sendMessage({type: "recent_memories"});
      if (!result?.ok) throw new Error();
      const entries = Array.isArray(result.entries) ? result.entries : [];
      history.replaceChildren();
      if (!entries.length) history.textContent = "No memories yet. Save a note, then extract it in OwlThread.";
      for (const entry of entries) {
        const row = document.createElement("div"); row.className = "memory";
        const kind = document.createElement("small"); kind.textContent = String(entry.quadrant || "Memory");
        const body = document.createElement("div"); body.textContent = String(entry.content || entry.summary || entry.text || "").slice(0,300);
        row.append(kind, body); history.append(row);
      }
    } catch { history.textContent = "Open OwlThread to see your shared memories. Full history and controls are in the app."; }
  });
  chrome.storage.onChanged.addListener((_changes, area) => { if (area === "local") void settings().catch(() => undefined); });
  void (async () => {
    try {
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      hostname = OwlPolicy.host(tab?.url || "");
      get("site-host").textContent = hostname || "Browser page";
      get("site-host").title = hostname || "Open a website first";
    } catch { get("site-host").textContent = "Current tab unavailable"; }
    await refresh();
  })();
})();
