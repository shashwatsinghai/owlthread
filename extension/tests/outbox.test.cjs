const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const source = readFileSync("background.js","utf8");

function worker(store = {}) {
  let receive;
  const sent = [];
  store.localApiToken ||= "t".repeat(43);
  const state = {online:false, failStorage:false, fetchHook:null};
  const clone = structuredClone;
  const chrome = {
    runtime: {id:"test-extension",getURL:path=>"chrome-extension://test-extension/"+path, onMessage:{addListener(fn){receive=fn;}},onInstalled:{addListener(){}},onStartup:{addListener(){}}},
    commands: {onCommand:{addListener(){}}},
    alarms: {onAlarm:{addListener(){}},create:async()=>{}},
    action: {setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}},
    tabs:{query:async()=>[],sendMessage:async()=>{}},
    storage: {onChanged:{addListener(){}},local:{setAccessLevel:async()=>{},
      get:async defaults=>({...clone(defaults),...clone(store)}),
      set:async values=>{
        if(state.failStorage) throw new Error("Storage unavailable");
        Object.assign(store,clone(values));
      }
    }}
  };
  const context = vm.createContext({
    chrome,crypto:webcrypto,TextEncoder,Uint8Array,AbortSignal,URL,
    importScripts: file => vm.runInContext(readFileSync(file,"utf8"),context),
    fetch:async (url,options)=>{
      if(!state.online) throw new Error("Desktop offline");
      if(state.fetchHook) await state.fetchHook(url,options);
      sent.push({url,headers:options.headers,body:options.body ? JSON.parse(options.body) : null});
      return {ok:true,json:async()=>url.endsWith("/capture-smart") ? {status:"skipped",accepted:false,reason:"No durable signal"} : {status:"healthy",total_entries:0,model_ready:true}};
    }
  });
  vm.runInContext(source,context);
  const message = value=>new Promise(resolve=>receive(value,{id:chrome.runtime.id,url:chrome.runtime.getURL("popup/popup.html")},resolve));
  return {store,state,sent,message};
}

test("outbox survives worker restart and retry retains the idempotency key",async()=>{
  const first=worker();
  const result=await first.message({type:"capture",payload:{text:"Decision: Use local SQLite WAL",url:"https://chatgpt.com/c/one"}});
  assert.equal(result.ok,true);
  await first.message({type:"retry"}); // Drain scheduled flush while offline.
  assert.equal(first.store.outbox.length,1);
  assert.equal(first.sent.length,0);
  const key=first.store.outbox[0].payload.dedup_key;
  assert.match(key,/^[a-f0-9]{64}$/);
  const restarted=worker(first.store);
  restarted.state.online=true;
  await restarted.message({type:"retry"});
  assert.equal((await restarted.message({type:"health"})).ok,true);
  const captures=restarted.sent.filter(item=>item.url.endsWith("/capture"));
  assert.equal(captures.length,1);
  assert.equal(captures[0].body.dedup_key,key);
  assert.equal(captures[0].body.source,"browser_extension");
  assert.equal(restarted.store.outbox.length,0);
});

test("public preferences hide secrets and raw captures and reject invalid updates",async()=>{
  const f=worker({outbox:[{id:'old',payload:{text:'PRIVATE RAW NOTE'}}]});
  const response=await f.message({type:'settings_get'});
  assert.equal(response.settings.localApiToken,undefined);
  assert.equal(JSON.stringify(response).includes('PRIVATE RAW NOTE'),false);
  assert.equal(response.settings.outbox.length,1);
  for(const values of [{localApiToken:'overwrite'},{enabled:'false'},{companionPosition:{x:Infinity,y:0}},{'siteMode:example.com':'invalid'}]){
    assert.equal((await f.message({type:'settings_set',values})).ok,false);
  }
});

test("offline captures retain the original project across preference changes",async()=>{
  const f=worker({captureProject:'Alpha'});
  await f.message({type:'capture',payload:{text:'Decision: Keep project boundaries explicit.'}});
  await f.message({type:'retry'});
  f.store.captureProject='Beta';f.state.online=true;
  await f.message({type:'retry'});
  assert.equal(f.sent.find(x=>x.url.endsWith('/capture')).body.project,'Alpha');
});

test("legacy notes stay held until explicitly assigned to a project",async()=>{
  const f=worker({captureProject:'Reviewed',outbox:[{id:'legacy',payload:{text:'Old saved note'}}]});
  f.state.online=true;
  assert.equal((await f.message({type:'retry'})).ok,false);
  assert.equal(f.store.outbox.length,1);
  assert.equal(f.sent.some(x=>x.url.endsWith('/capture')),false);
  assert.equal((await f.message({type:'assign_legacy_queue'})).ok,true);
  assert.equal((await f.message({type:'retry'})).ok,true);
  assert.equal(f.sent.find(x=>x.url.endsWith('/capture')).body.project,'Reviewed');
});

test("concurrent captures are serialized, deduplicated and delivered before extraction",async()=>{
  const f=worker();
  const results=await Promise.all(Array.from({length:20},(_,i)=>f.message({type:"capture",payload:{text:"Decision number "+(i%10)}})));
  assert.equal(results.every(r=>r.ok),true);
  await f.message({type:"retry"});
  assert.equal(f.store.outbox.length,10);
  f.state.online=true;
  await f.message({type:"flush"});
  assert.equal(f.sent.filter(item=>item.url.endsWith("/capture")).length,10);
  assert.ok(f.sent.at(-1).url.endsWith("/flush"));
  assert.equal(f.store.outbox.length,0);
});

test("full queues and failed storage never acknowledge a lost capture",async()=>{
  const store={outbox:Array.from({length:100},(_,i)=>({id:String(i),payload:{text:"Saved "+i}}))};
  const f=worker(store);
  const result=await f.message({type:"capture",payload:{text:"New decision"}});
  assert.equal(result.ok,false);
  assert.match(result.error,/queue is full/i);
  assert.equal(store.outbox.length,100);
  const broken=worker();
  broken.state.failStorage=true;
  const failed=await broken.message({type:"capture",payload:{text:"Do not lose this"}});
  assert.equal(failed.ok,false);
  assert.match(failed.error,/Storage unavailable/);
  assert.equal(broken.store.outbox,undefined);
  const oversized=await broken.message({type:"capture",payload:{text:"X".repeat(200001)}});
  assert.equal(oversized.ok,false);
});

test("automatic AI turns are durably queued and sent without an importance-loss gate",async()=>{
  const f=worker();
  f.state.online=true;
  const result=await f.message({type:"capture",payload:{text:"Here is a generic explanation without a project decision.",url:"https://chatgpt.com/c/one",title:"Chat",capture_mode:"automatic"}});
  assert.equal(result.ok,true);
  await f.message({type:"retry"});
  assert.equal(f.sent.some(item=>item.url.endsWith("/capture-smart")),false);
  assert.equal(f.sent.some(item=>item.url.endsWith("/capture")),true);
  assert.equal(f.store.outbox.length,0);
});

test("a slow sync never delays saving a new manual note or overwrites it",async()=>{
  const f=worker();
  await f.message({type:"capture",payload:{text:"First note"}});
  await f.message({type:"retry"});
  let release;
  const slow=new Promise(resolve=>{release=resolve;});
  let started;
  const startedPromise=new Promise(resolve=>{started=resolve;});
  f.state.online=true;
  f.state.fetchHook=async url=>{if(url.endsWith("/capture")){started();await slow;}};
  const syncing=f.message({type:"retry"});
  await startedPromise;
  try {
    const saved=await Promise.race([f.message({type:"capture",payload:{text:"Second note"}}),new Promise(resolve=>setTimeout(()=>resolve({ok:false}),400))]);
    assert.equal(saved.ok,true,"manual capture must be durable without waiting for the desktop");
    assert.equal(f.store.outbox.length,2);
  } finally {release();}
  await syncing;
  assert.equal(f.store.outbox.length,1);
  assert.equal(f.store.outbox[0].payload.text,"Second note");
});

test("offline retry and extraction report failure without losing notes",async()=>{
  const f=worker();
  await f.message({type:"capture",payload:{text:"Keep this offline"}});
  assert.equal((await f.message({type:"retry"})).ok,false);
  assert.equal((await f.message({type:"flush"})).ok,false);
  assert.equal(f.store.outbox.length,1);
});

test("site refusals and streaming defaults are enforced in the worker",async()=>{
  const f=worker({"siteMode:example.com":"blocked"});
  for(const url of ["https://example.com/page","https://docs.example.com/page","https://www.youtube.com/watch?v=1","https://www.netflix.com/watch/1"]) {
    const result=await f.message({type:"capture",payload:{text:"Do not collect this",url}});
    assert.equal(result.ok,false,url);
  }
  assert.equal(f.store.outbox,undefined);
  assert.equal(f.sent.length,0);
});

test("offline automatic responses remain durable in the browser",async()=>{
  const f=worker();
  const result=await f.message({type:"capture",payload:{text:"Decision: keep the configured model in the desktop app.",url:"https://chatgpt.com/c/test",capture_mode:"automatic"}});
  assert.equal(result.ok,true);
  assert.equal(f.store.outbox.length,1);
  assert.equal(f.store.outbox[0].payload.capture_mode,"automatic");
});

test("a sent prompt is staged before the reply and completed into one durable turn",async()=>{
  const f=worker();
  const staged=await f.message({type:"turn_stage",payload:{user_text:"Build a billing API",turn_key:"turn_1",
    url:"https://chatgpt.com/c/one",platform:"chatgpt",conversation_id:"chatgpt:one"}});
  assert.equal(staged.ok,true);
  assert.equal(f.store.outbox.length,1);
  assert.equal(f.store.outbox[0].state,"staged");
  assert.match(f.store.outbox[0].payload.text,/User:\nBuild a billing API/);
  const completed=await f.message({type:"turn_complete",payload:{stage_id:staged.stage_id,
    assistant_text:"Use signed webhooks and SQLite WAL."}});
  assert.equal(completed.ok,true);
  assert.equal(f.store.outbox[0].state,"ready");
  assert.match(f.store.outbox[0].payload.text,/Assistant:\nUse signed webhooks/);
});
