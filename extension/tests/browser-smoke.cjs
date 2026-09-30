/** Real MV3 install smoke test. Uses an isolated browser profile and mocked capture transport. */
const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

async function run() {
  const stage = name => { if (process.env.OWLTHREAD_TEST_TRACE) console.log(`stage:${name}`); };
  const extension = path.resolve(__dirname, "..");
  const artifacts = path.resolve(extension, "tests/artifacts");
  fs.mkdirSync(artifacts, {recursive: true});
  const executablePath = process.env.OWLTHREAD_TEST_BROWSER || (process.platform === "win32" ? [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"
  ].find(candidate=>fs.existsSync(candidate)) : undefined);
  const label = process.env.OWLTHREAD_TEST_LABEL || (executablePath ? executablePath.toLowerCase().includes("brave") ? "brave" : "chrome" : "chromium");
  const context = await chromium.launchPersistentContext("", {
    ...(executablePath ? {executablePath} : {channel: "chromium"}),
    headless: true,
    viewport: {width: 1365, height: 900},
    ignoreDefaultArgs: ["--disable-extensions"],
    args: ["--enable-unsafe-extension-debugging"]
  });
  try {
    const page = context.pages()[0] || await context.newPage();
    page.setDefaultTimeout(30000);
    // Match a user's Load unpacked setup; CDP alone bypasses this for the first load,
    // but Chrome disables an unpacked extension on reload without Developer mode.
    await page.goto("chrome://extensions/");
    await page.locator("#devMode").click();
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await context.route("https://www.youtube.com/**", route => route.fulfill({contentType:"text/html",body:"<!doctype html><title>YouTube test</title><h1>A quiet video page</h1>"}));
    await context.route("https://www.netflix.com/**", route => route.fulfill({contentType:"text/html",body:"<!doctype html><title>Netflix test</title><h1>A quiet movie page</h1>"}));
    await context.route("https://example.com/**", route => route.fulfill({contentType: "text/html", body: `<!doctype html><html><head><title>OwlThread queue tutorial</title><style>body{margin:0;background:#f5f5ef;color:#283c34;font:16px/1.8 'Segoe UI',sans-serif}header{padding:25px 64px;border-bottom:1px solid #d9ded4;font-size:13px;letter-spacing:2px}main{max-width:730px;margin:80px auto;padding:30px}h1{font:55px/1.15 Georgia,serif;letter-spacing:-2px}p{color:#647469;max-width:610px}.tag{font-size:11px;letter-spacing:2px;color:#85936d}article{padding:24px;border:1px solid #d8dfd3;border-radius:16px;background:#fff8}button{background:hotpink;border:8px solid red}small{color:#83917e}</style></head><body><header>EXAMPLE <small> / TEST PAGE</small></header><main><div class="tag">IDEAS WORTH KEEPING</div><h1>A thought today.<br>A head start tomorrow.</h1><p>Your browser companion keeps useful context close, wherever the next idea takes you.</p><article><strong>A note for later</strong><p id="selection">Decision: Keep local captures in a durable queue so useful context survives a browser restart, even when the desktop is offline.</p></article><p>No selection is required. Your owl will take the current page from here.</p></main></body></html>`}));
    // Start with a page open BEFORE installation: this is the original missing-owl failure.
    await page.goto("https://example.com/owlthread-test");
    const cdp = await context.browser().newBrowserCDPSession();
    const {id} = await cdp.send("Extensions.loadUnpacked", {path: extension});
    let worker = context.serviceWorkers()[0] || await context.waitForEvent("serviceworker");
    assert.equal(worker.url().split("/")[2], id);
    // Health is read-only; record actual connectivity without writing to the user's memory.
    const actualHealth = await worker.evaluate(async () => {
      try {const r = await fetch("http://127.0.0.1:41789/health", {signal: AbortSignal.timeout(5000)});return (await r.json()).app === "OwlThread";}
      catch {return false;}
    });
    const replacement = context.waitForEvent("serviceworker", {predicate: candidate => candidate !== worker});
    await worker.evaluate(() => chrome.runtime.reload()).catch(() => undefined);
    worker = await replacement;
    const installTransport = async state => {
      await chrome.storage.local.set({localApiToken:"t".repeat(43)});
      globalThis.testOnline = state?.online || false; globalThis.testCaptures = state?.captures || []; globalThis.testRequests = state?.requests || [];
      globalThis.fetch = async (url, options = {}) => {
        globalThis.testRequests.push(url);
        if (!globalThis.testOnline) throw new Error("Desktop offline (test)");
        if(options.headers?.Authorization !== "Bearer "+"t".repeat(43)) throw new Error("Missing pairing token");
        if (url.endsWith("/capture")) globalThis.testCaptures.push(JSON.parse(options.body));
        const response = url.includes("/entries?") ? {entries:[{quadrant:"settled_decisions",summary:"Use one desktop memory across browsers."}]} : url.endsWith("/flush") ? {total_extracted: 1} : url.endsWith("/context") ?
          {summary:"A workspace note about durable local queues.",page_kind:"article",useful:true,intelligence:"model",model:"gemini-3.5-flash-lite"} :
          {status: "healthy", total_entries: 12, pending_captures: 0, model_ready:true, model_name:"gemini-3.5-flash-lite"};
        return new Response(JSON.stringify(response), {status: 200, headers: {"Content-Type": "application/json"}});
      };
    };
    await worker.evaluate(installTransport);
    const dock = page.locator("#owlthread-companion .dock");
    const owl = page.getByRole("button", {name: "Open OwlThread companion.", exact: false});
    const panel = page.getByRole("dialog", {name: "OwlThread memory companion"});
    await page.locator("#owlthread-companion").waitFor({state:"attached"});
    await dock.waitFor({state: "visible"});
    assert.equal(await worker.evaluate(()=>globalThis.testRequests.length),0,"page load makes no desktop calls");
    stage("owl-visible");
    assert.equal(await page.locator("#owlthread-companion").count(), 1);
    await page.locator("#owlthread-companion img").evaluate(img => img.decode());
    assert.match(await page.locator("#owlthread-companion .plush").getAttribute("src"),/owl-cozy-developer\.png$/);
    await page.screenshot({path: path.join(artifacts, label + "-owl.png")});
    assert.equal(await worker.evaluate(() => globalThis.testRequests.some(url => url.endsWith("/context"))),false,"page load must not trigger AI awareness");
    // Website styling must not leak into the owl controls.
    assert.equal(await owl.evaluate(el => getComputedStyle(el).borderTopWidth), "0px");
    await page.mouse.move(250,160);
    await page.waitForTimeout(120);
    const pupilX = await dock.evaluate(el => el.style.getPropertyValue("--pupil-x"));
    assert.ok(parseFloat(pupilX)<0,"pupils look left toward the pointer");
    await page.mouse.move(1360,810);
    await page.waitForTimeout(100);
    assert.ok(parseFloat(await dock.evaluate(el=>el.style.getPropertyValue("--pupil-x")))>0,"pupils also follow to the right");
    await page.mouse.move(250,160);
    await page.waitForFunction(()=>{const dock=document.querySelector("#owlthread-companion").shadowRoot.querySelector(".dock");return dock.classList.contains("blinking")||dock.classList.contains("double-blink");},{},{timeout:9000});
    stage("natural-blink");
    await owl.click();
    await panel.waitFor({state: "visible"});
    assert.equal(await worker.evaluate(() => globalThis.testRequests.some(url => url.endsWith("/context"))),false,"opening controls does not send page text");
    await page.getByRole("button", {name:"Understand this page"}).click();
    await page.waitForFunction(()=>document.querySelector("#owlthread-companion").shadowRoot.querySelector(".dock").classList.contains("inspecting"));
    await page.waitForFunction(()=>getComputedStyle(document.querySelector("#owlthread-companion").shadowRoot.querySelector(".magnifier")).opacity === "1");
    assert.equal(await page.locator("#owlthread-companion .magnifier svg").evaluate(el=>getComputedStyle(el).animationName),"glass-search");
    await page.screenshot({path:path.join(artifacts,label+"-inspecting.png")});
    let contextRequested = false;
    for (let attempt = 0; attempt < 25 && !contextRequested; attempt++) {
      contextRequested = await worker.evaluate(() => globalThis.testRequests.some(url => url.endsWith("/context")));
      if (!contextRequested) await page.waitForTimeout(40);
    }
    assert.equal(contextRequested,true,"explicit understanding triggers page awareness");
    stage("context-requested");
    await page.getByText("Desktop offline", {exact: true}).waitFor();
    await page.getByRole("button", {name: "Remember current turn / page"}).click();
    await page.waitForFunction(()=>document.querySelector("#owlthread-companion").shadowRoot.querySelector(".dock").classList.contains("saving"));
    await page.waitForFunction(()=>getComputedStyle(document.querySelector("#owlthread-companion").shadowRoot.querySelector(".activity")).opacity === "1");
    assert.equal(await page.locator("#owlthread-companion .writing-hand").evaluate(el=>getComputedStyle(el).animationName),"pencil-scribble");
    await page.screenshot({path:path.join(artifacts,label+"-writing.png")});
    await page.waitForFunction(() => document.querySelector("#owlthread-companion").shadowRoot.querySelector(".feedback").textContent.startsWith("Remembered."));
    assert.equal(await dock.evaluate(el => el.classList.contains("done")),true,"successful note uses the done pose");
    const saved = await worker.evaluate(() => chrome.storage.local.get("outbox"));
    assert.equal(saved.outbox.length, 1);
    assert.match(saved.outbox[0].payload.text, /Title: OwlThread queue tutorial/);
    assert.match(saved.outbox[0].payload.text, /Decision: Keep local captures/);
    await page.screenshot({path: path.join(artifacts, label + "-panel.png")});
    stage("capture-saved");
    await page.getByRole("button", {name: "Close companion panel", exact: true}).click();
    const before = await owl.boundingBox();
    assert.equal(before.width,64,"owl stays compact");
    // Capture the shipped character layers for a standalone animation preview.
    const mascot = await page.locator("#owlthread-companion").evaluate(host=>({
      css:host.shadowRoot.querySelector("style").textContent,
      owl:host.shadowRoot.querySelector(".owl").outerHTML
    }));
    mascot.owl=mascot.owl.replace(/chrome-extension:\/\/[^/]+\/assets\/owl-cozy-developer\.png/g,"../../assets/owl-cozy-developer.png");
    const poses=[["","Hello, developer.","A cozy little pair programmer."],["saving","One thought at a time.","Notebook out. Pencil moving."],["inspecting","Letâ€™s look closer.","A magnifying glass for page understanding."],["done","Kept for next time.","A happy hop when your note is safe."]];
    fs.writeFileSync(path.join(artifacts,"cozy-owl-preview.html"),`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Meet your cozy OwlThread</title><style>${mascot.css}
      body{margin:0;background:#13271f;color:#f7efda;font:14px/1.6 'Segoe UI',sans-serif;padding:44px 32px}main{max-width:940px;margin:auto}header{max-width:570px;margin-bottom:30px}.eyebrow{color:#d9bd8a;letter-spacing:2px;font-size:10px}h1{font:42px/1.12 Georgia,serif;margin:10px 0 14px}header p{color:#adc5b2}.gallery{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{border:1px solid #98b79b30;border-radius:20px;background:linear-gradient(145deg,#2c4231,#182d25);padding:18px;text-align:center}.stage{height:200px;display:grid;place-items:center}.dock{position:relative!important;inset:auto!important;width:64px;height:64px;transform:scale(2.25);pointer-events:none}.owl{width:64px;height:64px}.card h2{font:20px/1.2 Georgia,serif;margin:12px 0 8px}.card p{font-size:11px;color:#a9c0af;margin:0}.done .bird,.done .done-mark,.done .spark{animation-iteration-count:infinite}.note{margin-top:24px;color:#adc5b2;font-size:12px}.swatches{display:flex;align-items:center;gap:8px;margin:18px 0}.swatches i{width:14px;height:14px;border-radius:50%;background:#d7a261}.swatches i:nth-child(2){background:#f5e5c7}.swatches i:nth-child(3){background:#627044}.swatches span{font-size:11px;color:#bcd0b8}@media(max-width:740px){.gallery{grid-template-columns:repeat(2,1fr)}body{padding:28px 20px}}@media(prefers-reduced-motion:reduce){.done .done-mark{opacity:1}}
      </style></head><body><main><header><span class="eyebrow">OWLTHREAD Â· YOUR COZY DEV COMPANION</span><h1>A little owl.<br>A lot of personality.</h1><p>Code-bracket ears, a soft green hoodie, and a curious little face. Move your cursor to say hello.</p><div class="swatches"><i></i><i></i><i></i><span>Caramel Â· oat Â· moss</span></div></header><section class="gallery">${poses.map(([state,title,copy])=>`<article class="card"><div class="stage"><div class="dock ${state}">${mascot.owl}</div></div><h2>${title}</h2><p>${copy}</p></article>`).join("")}</section><p class="note">Shown larger so you can meet the details. Your browser owl stays a quiet 64px. Motion preferences are respected.</p></main><script src="cozy-owl-preview.js"></script></body></html>`);
    fs.writeFileSync(path.join(artifacts,"cozy-owl-preview.js"),`const docks=[...document.querySelectorAll('.dock')];const reduced=matchMedia('(prefers-reduced-motion:reduce)');document.addEventListener('pointermove',event=>{if(reduced.matches)return;for(const dock of docks){const b=dock.getBoundingClientRect(),dx=event.clientX-b.x-b.width/2,dy=event.clientY-b.y-b.height*.4,d=Math.max(120,Math.hypot(dx,dy));dock.style.setProperty('--pupil-x',dx/d*1.65+'px');dock.style.setProperty('--pupil-y',dy/d*1.25+'px');}});function blink(){if(!reduced.matches){docks[0].classList.add('double-blink');setTimeout(()=>docks[0].classList.remove('double-blink'),520);}setTimeout(blink,3100+Math.random()*2800);}blink();`);
    await page.mouse.move(before.x + 32, before.y + 35); await page.mouse.down();
    await page.mouse.move(180, 270, {steps: 15}); await page.mouse.up();
    assert.equal(await panel.isVisible(), false, "drag must not open controls");
    const moved = await owl.boundingBox();
    assert.ok(moved.x < before.x - 100);
    await page.reload(); await dock.waitFor({state: "visible"});
    const restored = await owl.boundingBox();
    assert.ok(Math.abs(restored.x - moved.x) < 2, "position survives reload");
    stage("drag-restored");
    await worker.evaluate(async () => {const [tab] = await chrome.tabs.query({url: "https://example.com/*"});for (let i=0;i<3;i++) await chrome.scripting.executeScript({target:{tabId:tab.id},files:["policy.js","content.js","companion.js"]});});
    assert.equal(await page.locator("#owlthread-companion").count(), 1, "repeated injection is idempotent");
    stage("reinjection");
    await page.setViewportSize({width: 380, height: 580});
    await owl.click(); await panel.waitFor({state: "visible"});
    stage("narrow-open");
    const bounds = await panel.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 380 && bounds.y >= 0 && bounds.y + bounds.height <= 581, "panel fits narrow viewport");
    await page.emulateMedia({reducedMotion: "reduce"});
    assert.equal(await page.locator(".bird").evaluate(el => getComputedStyle(el).animationName), "none");
    assert.equal(await page.locator(".pupil").first().evaluate(el=>getComputedStyle(el).animationName),"none");
    stage("reduced-motion");
    await page.getByRole("button", {name: "Never on this site", exact: true}).click();
    await dock.waitFor({state:"hidden"});
    await page.reload();
    await page.locator("#owlthread-companion").waitFor({state:"attached"});
    assert.equal(await dock.isVisible(), false);
    const denied=await worker.evaluate(()=>chrome.storage.local.get("siteMode:example.com"));
    assert.equal(denied["siteMode:example.com"],"blocked");
    await page.setViewportSize({width: 1365, height: 900});
    let popup = await context.newPage();
    popup.setDefaultTimeout(30000);
    popup.on("pageerror", error => pageErrors.push(error.message));
    await popup.goto(`chrome-extension://${id}/popup/popup.html`);
    stage("popup-loaded");
    await popup.getByText("Desktop offline", {exact: true}).waitFor();
    stage("popup-offline");
    // This test opens the popup in a full tab. Avoid OS-focus-dependent tab
    // switching; exercise the saved site choice through real extension storage.
    await popup.locator("#preferences").evaluate(el=>el.open=true);
    await popup.locator("#visible").uncheck();
    await popup.locator("#visible").check();
    assert.equal(await dock.isVisible(),false,"global visibility cannot undo a site refusal");
    await worker.evaluate(()=>chrome.storage.local.set({"siteMode:example.com":"allowed"}));
    await dock.waitFor({state:"visible"});
    await popup.locator("#motion").uncheck();
    if (process.env.OWLTHREAD_TEST_TRACE) console.log("motion-state", await worker.evaluate(()=>chrome.storage.local.get("companionMotion")), await popup.locator("#motion").isChecked(), await dock.getAttribute("class"));
    // The website is a background tab while its popup is active, so requestAnimationFrame
    // polling can be suspended even after the real storage listener has updated it.
    await page.waitForFunction(() => document.querySelector("#owlthread-companion").shadowRoot.querySelector(".dock").classList.contains("still"), null, {polling:100});
    await worker.evaluate(() => {globalThis.testOnline = true;});
    await popup.getByRole("button", {name: "Reconnect desktop"}).click();
    await popup.getByText("Desktop connected", {exact: true}).waitFor();
    assert.match(await popup.locator("#model").textContent(),/gemini-3.5-flash-lite/);
    stage("popup-connected");
    const synced = await worker.evaluate(async () => ({...(await chrome.storage.local.get("outbox")), sent: globalThis.testCaptures}));
    assert.equal(synced.outbox.length, 0); assert.equal(synced.sent.length, 1);
    await popup.getByRole("button", {name: "Extract saved memories"}).click();
    await popup.getByText("Extracted 1 memory.", {exact: true}).waitFor();
    await popup.locator("#recent").evaluate(el=>el.open=true);
    await popup.getByText("Use one desktop memory across browsers.",{exact:true}).waitFor();
    await popup.locator("#recent").evaluate(el=>el.open=false);
    await popup.locator("#preferences").evaluate(el=>el.open=false);
    await popup.setViewportSize({width: 360, height: 600});
    await popup.screenshot({path: path.join(artifacts, label + "-popup.png"), fullPage: true});
    const popupHeight=await popup.evaluate(()=>document.body.scrollHeight);
    assert.ok(popupHeight<=600,"collapsed popup fits browser height: "+popupHeight);
    assert.ok(await popup.evaluate(()=>document.documentElement.scrollWidth)<=360,"popup has no horizontal overflow");
    await popup.screenshot({path: path.join(artifacts, label + "-popup.png"), fullPage: true});
    await worker.evaluate(async () => {const [tab] = await chrome.tabs.query({url: "https://example.com/*"});await chrome.tabs.update(tab.id, {active:true});});
    // Invoke the toolbar capture command without selecting any text.
    const manual = await popup.evaluate(() => chrome.runtime.sendMessage({type: "capture_active"}));
    assert.equal(manual.ok, true, manual.error);
    const deliveryDeadline=Date.now()+5000;
    while((await worker.evaluate(async()=> (await chrome.storage.local.get({outbox:[]})).outbox.length)) && Date.now()<deliveryDeadline) await page.waitForTimeout(50);
    assert.equal(await worker.evaluate(async()=> (await chrome.storage.local.get({outbox:[]})).outbox.length),0,"captures drain before the active-tab reload");
    const mockState=await worker.evaluate(()=>({online:globalThis.testOnline,captures:globalThis.testCaptures,requests:globalThis.testRequests}));
    const nextWorker=context.waitForEvent("serviceworker",{predicate:candidate=>candidate!==worker});
    await worker.evaluate(()=>chrome.runtime.reload()).catch(()=>undefined);
    worker=await nextWorker;await worker.evaluate(installTransport,mockState);
    await page.locator("#owlthread-companion").waitFor({state:"attached"});await dock.waitFor({state:"visible"});
    assert.equal(await page.locator("#owlthread-companion").count(),1,"extension reload preserves one owl on the existing active tab");
    await worker.evaluate(async()=>{const [tab]=await chrome.tabs.query({url:"https://example.com/*"});for(let i=0;i<3;i++) await chrome.scripting.executeScript({target:{tabId:tab.id},files:["policy.js","content.js","companion.js"]});});
    assert.equal(await page.locator("#owlthread-companion").count(),1,"reinjection after a live reload remains idempotent");
    await owl.click();await panel.waitFor({state:"visible"});
    await page.getByRole("button",{name:"Remember current turn / page"}).click();
    await page.waitForFunction(()=>document.querySelector("#owlthread-companion").shadowRoot.querySelector(".feedback").textContent.startsWith("Remembered."));
    await page.getByRole("button",{name:"Close companion panel",exact:true}).click();
    stage("active-tab-reload-capture");
    await page.goto("chrome://extensions/");
    // Chrome closes extension-owned tabs on reload; the website tab stays open.
    if(popup.isClosed()) {
      popup=await context.newPage();popup.setDefaultTimeout(30000);
      popup.on("pageerror",error=>pageErrors.push(error.message));
      await popup.goto(`chrome-extension://${id}/popup/popup.html`);
    } else await popup.reload();
    const restricted = await popup.evaluate(() => chrome.runtime.sendMessage({type: "show_owl"}));
    assert.equal(restricted.ok, false);
    assert.match(restricted.error, /normal website/);
    const requestCount=await worker.evaluate(()=>globalThis.testRequests.length);
    await page.goto("https://www.youtube.com/watch?v=owlthread-test");
    await page.waitForTimeout(250);
    assert.equal(await page.locator("#owlthread-companion").count(),0,"YouTube is an immutable no-injection boundary");
    assert.equal(await worker.evaluate(()=>globalThis.testRequests.length),requestCount,"YouTube makes no requests");
    await page.goto("https://www.netflix.com/watch/test");
    await page.waitForTimeout(250);
    assert.equal(await page.locator("#owlthread-companion").count(),0,"Netflix is an immutable no-injection boundary");
    assert.equal(await worker.evaluate(()=>globalThis.testRequests.length),requestCount,"Netflix load makes no requests");
    assert.deepEqual(pageErrors, []);
    console.log(JSON.stringify({browser: label, installed: true, cozyArtwork:true, notebookWriting:true, magnifyingGlass:true, naturalBlink:true, compactOwl:true, hardBlockedYouTube:true, permanentSiteRefusal:true, noSelectionCapture:true, extensionReload: true, activeTabReloadCapture:true, actualDesktopHealth: actualHealth, explicitAwareness: true, eyeTracking: true, offlineCapture: true, sync: true, dragPersistence: true, reinjection: true, narrowViewport: true, reducedMotion: true, popup: true, restrictedPageFeedback: true, pageErrors, screenshots: artifacts}, null, 2));
  } finally { await context.close(); }
}
run().catch(error => {console.error(error);process.exitCode = 1;});
