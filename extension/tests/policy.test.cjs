const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({URL});
vm.runInContext(readFileSync("policy.js","utf8"),context);
const policy = context.OwlPolicy;

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
