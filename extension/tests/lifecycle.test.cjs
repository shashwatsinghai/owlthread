/** Existing tabs must survive extension reloads, missing APIs and repeated injection. */
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {JSDOM} = require("jsdom");
const {webcrypto} = require("node:crypto");
const {Script} = require("node:vm");

const sources = Object.fromEntries(["policy", "content", "companion"].map(name => [name, readFileSync(name+".js", "utf8")]));
const tick = () => new Promise(resolve => setTimeout(resolve, 20));

function fixture({runtimeAvailable=true} = {}) {
  const dom = new JSDOM("<!doctype html><title>Lifecycle fixture</title><p>Visible fixture</p>", {
    url:"https://chatgpt.com/c/lifecycle-fixture", runScripts:"outside-only", pretendToBeVisual:true
  });
  const window = dom.window;
  const state = {invalid:false,failRegistration:false,failSettings:false,deferSettings:false};
  const pendingSettings=[];
  const bridges = new Set(), errors = [], messages = [];
  window.addEventListener("error", event => { errors.push(event.error || Error(event.message));event.preventDefault(); });
  window.TextEncoder = TextEncoder;
  Object.defineProperty(window.crypto, "subtle", {value:webcrypto.subtle});
  window.matchMedia = () => ({matches:false,addEventListener(){},removeEventListener(){}});
  const runtime = {
    id:"test-extension",
    getURL(path){if(state.invalid) throw Error("Extension context invalidated.");return "chrome-extension://test-extension/"+path;},
    async sendMessage(message){
      if(state.invalid) throw Error("Extension context invalidated.");
      messages.push(message);
      if(message.type==="settings_get" && state.failSettings) return {ok:false};
      if(message.type==="settings_get" && state.deferSettings) return new Promise(resolve=>pendingSettings.push(resolve));
      return message.type==="settings_get" ? {ok:true,settings:{enabled:true}} : {ok:true};
    },
    onMessage:{
      addListener(fn){if(state.invalid || state.failRegistration) throw Error("Extension context invalidated.");bridges.add(fn);},
      removeListener(fn){if(state.invalid) throw Error("Extension context invalidated.");bridges.delete(fn);}
    }
  };
  window.chrome = runtimeAvailable ? {runtime} : {};
  const active = new Map();
  for(const [name,target] of [["window",window],["document",window.document]]) {
    const add = target.addEventListener.bind(target), remove = target.removeEventListener.bind(target);
    target.addEventListener = (type,fn,options) => {
      const key=name+":"+type;
      if(!active.has(key)) active.set(key,new Set());active.get(key).add(fn);
      return add(type,fn,options);
    };
    target.removeEventListener = (type,fn,options) => {active.get(name+":"+type)?.delete(fn);return remove(type,fn,options);};
  }
  // Classic content scripts share global var bindings even when emitted in strict
  // mode. window.eval would create a fresh strict-eval var scope on each injection.
  const load = name => new Script(sources[name],{filename:name+".js"}).runInContext(dom.getInternalVMContext());
  const count = key => active.get(key)?.size || 0;
  return {dom,window,runtime,state,bridges,errors,messages,pendingSettings,load,count};
}

test("missing runtime at initialization does not install broken observers or owl controls",async()=>{
  const f=fixture({runtimeAvailable:false});
  try {
    f.load("policy");
    assert.doesNotThrow(()=>f.load("content"));
    assert.doesNotThrow(()=>f.load("companion"));
    await tick();
    assert.equal(f.window.document.querySelector("#owlthread-companion"),null);
    assert.equal(f.count("document:submit"),0);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("policy listeners survive reinjection and repeated registration stays idempotent",()=>{
  const f=fixture();
  try {
    f.load("policy");const listener=()=>{};
    f.window.OwlPolicy.onChange(listener);
    f.window.OwlPolicy.onChange(listener);
    assert.equal(f.bridges.size,1,"one callback must have one bridge");
    f.load("policy");
    f.window.OwlPolicy.removeChange(listener);
    assert.equal(f.bridges.size,0,"reinjecting policy must preserve removable bridge references");
  } finally {f.dom.window.close();}
});

test("observer cleanup completes when Chrome invalidates message listener APIs",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.load("content");await tick();
    assert.equal(f.count("document:submit"),1);
    f.state.invalid=true;
    f.window.dispatchEvent(new f.window.Event("owlthread:dispose-observer"));
    for(const key of ["document:submit","document:keydown","document:click","window:pagehide","window:pageshow","window:owlthread:dispose-observer"])
      assert.equal(f.count(key),0,key+" must be detached despite invalid extension APIs");
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("companion cleanup removes its DOM and browser listeners after runtime disappears",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.load("companion");await tick();
    assert.ok(f.window.document.querySelector("#owlthread-companion"));
    delete f.window.chrome.runtime;
    f.window.dispatchEvent(new f.window.Event("owlthread:dispose-companion"));
    assert.equal(f.window.document.querySelector("#owlthread-companion"),null);
    for(const key of ["window:resize","document:pointermove","document:pointerdown","document:keydown","document:visibilitychange","document:fullscreenchange"])
      assert.equal(f.count(key),0,key+" must be detached when runtime is absent");
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("repeated complete injection keeps exactly one observer and companion subscription",async()=>{
  const f=fixture();
  try {
    for(let i=0;i<4;i++){f.load("policy");f.load("content");f.load("companion");await tick();}
    assert.equal(f.bridges.size,3,"one direct observer listener and two settings bridges");
    assert.equal(f.count("document:submit"),1);
    assert.equal(f.count("window:resize"),1);
    assert.equal(f.window.document.querySelectorAll("#owlthread-companion").length,1);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("failed message listener registration leaves no active observer or orphan companion",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.state.failRegistration=true;
    assert.doesNotThrow(()=>f.load("content"));
    assert.doesNotThrow(()=>f.load("companion"));
    await tick();
    assert.equal(f.bridges.size,0);
    assert.equal(f.count("document:submit"),0);
    assert.equal(f.count("window:resize"),0);
    assert.equal(f.window.document.querySelector("#owlthread-companion"),null);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("rejected settings startup cleans up both capture handlers and companion controls",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.state.failSettings=true;f.load("content");f.load("companion");await tick();
    assert.equal(f.bridges.size,0);
    assert.equal(f.count("document:submit"),0);
    assert.equal(f.count("window:resize"),0);
    assert.equal(f.window.document.querySelector("#owlthread-companion"),null);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("runtime loss after initialization never sends the next prompt or page capture",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.load("content");f.load("companion");await tick();
    delete f.window.chrome.runtime;
    const form=f.window.document.createElement("form"),composer=f.window.document.createElement("textarea");
    composer.id="prompt-textarea";composer.value="A prompt after extension runtime loss";form.append(composer);f.window.document.body.append(form);
    form.dispatchEvent(new f.window.Event("submit",{bubbles:true,cancelable:true}));
    const host=f.window.document.querySelector("#owlthread-companion");
    host?.shadowRoot.querySelector(".capture").click();
    await tick();
    assert.equal(f.messages.filter(message=>["turn_stage","turn_complete","capture","capture_tab","capture_active"].includes(message.type)).length,0);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});

test("a retired settings response cannot hide or disable the reinjected companion",async()=>{
  const f=fixture();
  try {
    f.load("policy");f.state.deferSettings=true;f.load("content");f.load("companion");
    assert.equal(f.pendingSettings.length,2);
    f.state.deferSettings=false;f.load("policy");f.load("content");f.load("companion");await tick();
    const currentHost=f.window.document.querySelector("#owlthread-companion");
    assert.ok(currentHost);assert.equal(currentHost.shadowRoot.querySelector(".dock").hidden,false);
    for(const resolve of f.pendingSettings) resolve({ok:true,settings:{enabled:false,companionVisible:false,"siteMode:chatgpt.com":"blocked"}});
    await tick();
    assert.equal(f.window.document.querySelector("#owlthread-companion"),currentHost);
    assert.equal(currentHost.shadowRoot.querySelector(".dock").hidden,false);
    assert.equal(f.bridges.size,3);
    assert.equal(f.count("document:submit"),1);
    assert.deepEqual(f.errors,[]);
  } finally {f.dom.window.close();}
});
