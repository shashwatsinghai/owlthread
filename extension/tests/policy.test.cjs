const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({URL});
vm.runInContext(readFileSync("policy.js","utf8"),context);
const policy = context.OwlPolicy;

test("unavailable runtime gives actionable settings failures without exposing TypeErrors",async()=>{
  const throwingRuntime=Object.defineProperty({},"runtime",{get(){throw Error("Extension context invalidated.");}});
  for(const chrome of [undefined,{},throwingRuntime]) {
    const sandbox=vm.createContext({URL,chrome});
    vm.runInContext(readFileSync("policy.js","utf8"),sandbox);
    assert.equal(sandbox.OwlPolicy.runtimeAvailable(),false);
    assert.equal(sandbox.OwlPolicy.getURL("assets/owl-cozy-developer.png"),undefined);
    assert.equal(sandbox.OwlPolicy.onChange(()=>{}),false);
    await assert.rejects(sandbox.OwlPolicy.settings(),/Refresh this tab/);
    await assert.rejects(sandbox.OwlPolicy.save({enabled:false}),/Refresh this tab/);
  }
});

test("an invalidated send stops further sends even when a stale runtime id remains",async()=>{
  let attempts=0;
  const sandbox=vm.createContext({URL,chrome:{runtime:{id:"test",sendMessage:async()=>{attempts++;throw Error("Extension context invalidated.");}}}});
  vm.runInContext(readFileSync("policy.js","utf8"),sandbox);
  await assert.rejects(sandbox.OwlPolicy.settings(),/Refresh this tab/);
  assert.equal(sandbox.OwlPolicy.runtimeAvailable(),false);
  await assert.rejects(sandbox.OwlPolicy.save({enabled:false}),/Refresh this tab/);
  assert.equal(attempts,1);
});

test("settings bridge ignores unrelated or malformed messages and removes from the original event",()=>{
  const handlers=new Set();let calls=0;
  const channel={addListener:fn=>handlers.add(fn),removeListener:fn=>handlers.delete(fn)};
  const sandbox=vm.createContext({URL,chrome:{runtime:{id:"test",onMessage:channel}}});
  vm.runInContext(readFileSync("policy.js","utf8"),sandbox);
  const listener=()=>calls++;
  assert.equal(sandbox.OwlPolicy.onChange(listener),true);
  const bridge=[...handlers][0];
  for(const message of [null,{}, {type:"public_settings_changed"}, {type:"public_settings_changed",changes:[]}]) bridge(message);
  assert.equal(calls,0);
  bridge({type:"public_settings_changed",changes:{enabled:{newValue:false}}});
  assert.equal(calls,1);
  delete sandbox.chrome.runtime;
  assert.doesNotThrow(()=>sandbox.OwlPolicy.removeChange(listener));
  assert.equal(handlers.size,0);
});

test("streaming domains and subdomains are quiet without blocking lookalike names",()=>{
  for(const url of ["https://www.youtube.com/watch?v=1","https://youtu.be/1","https://www.netflix.com/browse","https://player.twitch.tv/","https://open.spotify.com/track/test"]) {
    assert.equal(policy.allowed({},policy.host(url)),false,url);
  }
  assert.equal(policy.allowed({},policy.host("https://youtube.com.example.org")),true);
  assert.equal(policy.allowed({},policy.host("chrome://extensions")),false);
});

test("refusal survives global visibility changes and only explicit site permission restores it",()=>{
  const settings={"siteMode:example.com":"blocked",companionVisible:true};
  assert.equal(policy.allowed(settings,"example.com"),false);
  assert.equal(policy.allowed(settings,"docs.example.com"),false);
  settings.companionVisible=false;
  settings.companionVisible=true;
  assert.equal(policy.allowed(settings,"example.com"),false);
  settings["siteMode:example.com"]="allowed";
  assert.equal(policy.allowed(settings,"example.com"),true);
});

test("hard-blocked sites cannot be restored by an allow preference",()=>{
  const settings={"siteMode:netflix.com":"allowed"};
  assert.equal(policy.allowed(settings,"netflix.com"),false);
  assert.equal(policy.mode(settings,"netflix.com"),"blocked");
  settings["siteMode:netflix.com"]="default";
  assert.equal(policy.allowed(settings,"netflix.com"),false);
});
