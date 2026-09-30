const {test} = require("node:test");
const assert = require("node:assert/strict");
const {JSDOM} = require("jsdom");
const {readFileSync} = require("node:fs");
const {webcrypto} = require("node:crypto");
const source = readFileSync("content.js","utf8");
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));

function fixture(host, markup="") {
  const dom = new JSDOM(markup,{url:"https://"+host+"/chat/test",runScripts:"outside-only"});
  const messages = [];
  const changes = []; const handlers = new Map();
  const store = {enabled:true};
  const window = dom.window;
  window.TextEncoder = TextEncoder;
  Object.defineProperty(window.crypto,"subtle",{value:webcrypto.subtle});
  window.chrome = {
    runtime: {
      id:"test-extension",
      sendMessage: async message => {
        if(message.type==="settings_get") return {ok:true,settings:{...store}};
        messages.push(message);
        if(message.type==="turn_stage") return {ok:true,stage_id:"a".repeat(64)};
        return {ok:true};
      },
      onMessage: {addListener(fn){if(fn.toString().includes("public_settings_changed")) {const bridge=(c,area)=>fn({type:"public_settings_changed",changes:c}); handlers.set(fn,bridge);changes.push(bridge);}},removeListener(fn){const bridge=handlers.get(fn);const i=changes.indexOf(bridge);if(i>=0)changes.splice(i,1);}}
    },
    storage: {local:{get:async()=>({...store})},onChanged:{addListener(fn){changes.push(fn)},removeListener(fn){const i=changes.indexOf(fn);if(i>=0)changes.splice(i,1);}}}
  };
  window.eval(readFileSync("policy.js","utf8") + "\nwindow.OwlPolicy = OwlPolicy;");
  window.eval(source);
  return {dom,window,messages,changes,store};
}

function sendPrompt(f,text) {
  const form=f.window.document.createElement("form");
  const composer=f.window.document.createElement("textarea");
  composer.value=text;
  form.append(composer);
  f.window.document.body.append(form);
  form.dispatchEvent(new f.window.Event("submit",{bubbles:true,cancelable:true}));
  form.remove();
}

async function completeReply(f,markup,prompt="Build the requested system") {
  await sleep(25);
  sendPrompt(f,prompt);
  await sleep(25);
  f.window.document.body.insertAdjacentHTML("beforeend",markup);
  await sleep(1700);
}

test("ChatGPT stages the user prompt immediately and completes exactly one combined turn",async()=>{
  const text="Decision: Use SQLite WAL for the local memory store. ".repeat(4);
  const f=fixture("chatgpt.com");
  await sleep(25);
  sendPrompt(f,"Build a local memory store");
  await sleep(25);
  const stage=f.messages.find(message=>message.type==="turn_stage");
  assert.ok(stage,"user prompt must be staged before an assistant response exists");
  assert.equal(stage.payload.user_text,"Build a local memory store");
  f.window.document.body.insertAdjacentHTML("beforeend",'<article><div data-message-author-role="assistant">'+text+'</div><button data-testid="copy-turn-action-button">Copy</button></article>');
  const html=f.window.document.body.innerHTML;
  await sleep(1700);
  const completes=f.messages.filter(message=>message.type==="turn_complete");
  assert.equal(completes.length,1);
  assert.equal(completes[0].payload.assistant_text,text.trim());
  assert.equal(f.window.document.body.innerHTML,html,"observer must not mutate DOM");
  f.window.document.querySelector("article").setAttribute("class","hover");
  await sleep(1700);
  assert.equal(f.messages.filter(message=>message.type==="turn_complete").length,1);
  f.dom.window.close();
});

test("streaming replies wait for a completion control",async()=>{
  const f=fixture("chatgpt.com");
  await sleep(25);
  sendPrompt(f,"Explain the architecture");
  f.window.document.body.insertAdjacentHTML("beforeend",'<article><div data-message-author-role="assistant">Still generating a detailed answer</div></article><button data-testid="stop-button">Stop</button>');
  await sleep(1700);
  assert.equal(f.messages.some(message=>message.type==="turn_complete"),false);
  f.window.document.querySelector('[data-testid="stop-button"]').remove();
  f.window.document.querySelector("article").insertAdjacentHTML("beforeend",'<button data-testid="copy-turn-action-button">Copy</button>');
  await sleep(1700);
  assert.equal(f.messages.filter(message=>message.type==="turn_complete").length,1);
  f.dom.window.close();
});

test("Claude and DeepSeek completed replies join their staged user prompt",async()=>{
  const text="Architecture: A single SQLite writer handles concurrent captures. ".repeat(3);
  for(const [host,markup] of [
    ["claude.ai",'<article><div data-testid="assistant-message"><div class="font-claude-message">'+text+'</div></div><button aria-label="Copy message">Copy</button></article>'],
    ["chat.deepseek.com",'<article><div class="ds-markdown">'+text+'</div><button aria-label="Copy">Copy</button></article>']
  ]) {
    const f=fixture(host);
    await completeReply(f,markup,"Design concurrent capture");
    assert.equal(f.messages.filter(message=>message.type==="turn_stage").length,1,host);
    assert.equal(f.messages.filter(message=>message.type==="turn_complete").length,1,host);
    f.dom.window.close();
  }
});

test("pause disconnects the observer and unsupported sites remain untouched",async()=>{
  const f=fixture("chatgpt.com");
  f.store.enabled=false;
  for(const changed of f.changes) changed({enabled:{newValue:false}});
  await completeReply(f,'<article><div data-message-author-role="assistant" data-is-streaming="false">Decision: Use SQLite locally.</div></article>');
  assert.equal(f.messages.length,0);
  f.dom.window.close();
  const other=fixture("example.com","<p>Private unrelated page</p>");
  await sleep(20);
  assert.equal(other.messages.length,0);
  assert.equal(other.window.document.body.innerHTML,"<p>Private unrelated page</p>");
  other.dom.window.close();
});

test("opening a chat never replays completed history",async()=>{
  const old='<article><div data-message-author-role="assistant" data-is-streaming="false">Old decision: use local storage.</div></article>';
  const f=fixture("chatgpt.com",old);
  await sleep(1700);
  assert.equal(f.messages.length,0);
  await completeReply(f,'<article><div data-message-author-role="assistant" data-is-streaming="false">New decision: keep captures durable.</div></article>',"Make the new decision durable");
  assert.equal(f.messages.filter(message=>message.type==="turn_complete").length,1);
  assert.match(f.messages.find(message=>message.type==="turn_complete").payload.assistant_text,/New decision/);
  f.dom.window.close();
});

test("hard-blocked pages install no observer or message listener",async()=>{
  const f=fixture("m.youtube.com","<p>Private video page</p>");
  await sleep(25);
  assert.equal(f.messages.length,0);
  assert.equal(f.changes.length,0);
  f.dom.window.close();
});

test("a first ChatGPT turn survives its new conversation URL being assigned",async()=>{
  const f=fixture("chatgpt.com");
  f.window.history.replaceState({},"","/");
  await sleep(25);
  sendPrompt(f,"Create the first decision");
  await sleep(25);
  f.window.history.pushState({},"","/c/new-conversation");
  f.window.document.body.insertAdjacentHTML("beforeend",'<article><div data-message-author-role="assistant" data-is-streaming="false">First answer is complete.</div></article>');
  await sleep(1700);
  const completed=f.messages.find(x=>x.type==="turn_complete");
  assert.ok(completed,"assigning a URL must not discard a sent turn");
  assert.equal(completed.payload.url,"https://chatgpt.com/c/new-conversation");
  f.dom.window.close();
});

test("switching between existing chats never attaches an unrelated reply to the staged prompt",async()=>{
  const f=fixture("chatgpt.com");
  await sleep(25);sendPrompt(f,"Prompt in the first chat");
  f.window.history.pushState({},"","/c/unrelated-chat");
  f.window.document.body.insertAdjacentHTML("beforeend",'<article><div data-message-author-role="assistant" data-is-streaming="false">An unrelated chat reply.</div></article>');
  await sleep(1700);
  assert.equal(f.messages.some(x=>x.type==="turn_complete"),false);
  f.dom.window.close();
});

test("a delayed acknowledgement from one turn cannot clear a newer staged turn",async()=>{
  const f=fixture("chatgpt.com");
  const original=f.window.chrome.runtime.sendMessage;
  let release;
  f.window.chrome.runtime.sendMessage=async message=>{
    const result=await original(message);
    if(message.type==="turn_complete" && !release) await new Promise(resolve=>{release=resolve;});
    return result;
  };
  await completeReply(f,'<article><div data-message-author-role="assistant" data-is-streaming="false">First completed reply.</div></article>',"First user request");
  assert.equal(typeof release,"function");
  sendPrompt(f,"Second user request");await sleep(25);release();
  f.window.document.body.insertAdjacentHTML("beforeend",'<article><div data-message-author-role="assistant" data-is-streaming="false">Second completed reply.</div></article>');
  await sleep(1700);
  const completed=f.messages.filter(x=>x.type==="turn_complete");
  assert.equal(completed.length,2);
  assert.equal(completed[1].payload.assistant_text,"Second completed reply.");
  f.dom.window.close();
});
