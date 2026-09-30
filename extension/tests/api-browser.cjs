/** Real Chrome MV3 worker -> authenticated Python server -> SQLite -> extraction. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {createInterface}=require('node:readline');
const path=require('node:path');
const assert=require('node:assert/strict');
async function main(){
  const root=path.resolve(__dirname,'../..');
  const server=spawn(path.join(root,'.venv/Scripts/python.exe'),[path.join(root,'tools/browser_api_fixture.py')],{stdio:['pipe','pipe','inherit']});
  const line=await Promise.race([new Promise((resolve,reject)=>{createInterface({input:server.stdout}).once('line',resolve);server.once('exit',()=>reject(Error('Fixture exited')));}),new Promise((_,reject)=>setTimeout(()=>reject(Error('Server startup timeout')),15000).unref())]);
  const config=JSON.parse(line);
  const base=`http://127.0.0.1:${config.port}`;
  const browser=await chromium.launchPersistentContext('',{executablePath:process.env.OWLTHREAD_TEST_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,ignoreDefaultArgs:['--disable-extensions'],args:['--enable-unsafe-extension-debugging']});
  let checks=0;
  function check(value,label){assert.ok(value,label);checks++;}
  try{
    const page=browser.pages()[0];
    await page.goto('chrome://extensions/');await page.locator('#devMode').click();
    const cdp=await browser.browser().newBrowserCDPSession();
    const {id}=await cdp.send('Extensions.loadUnpacked',{path:path.join(root,'extension')});
    const worker=browser.serviceWorkers()[0] || await browser.waitForEvent('serviceworker');
    // Only the destination port changes. HTTP, credentials, Origin and responses are real.
    await worker.evaluate(base=>{const real=globalThis.fetch;globalThis.fetch=(url,opts)=>real(String(url).replace('http://127.0.0.1:41789',base),opts);},base);
    const popup=await browser.newPage();await popup.goto(`chrome-extension://${id}/popup/popup.html`);
    const send=message=>popup.evaluate(message=>chrome.runtime.sendMessage(message),message);
    const eventually=async(predicate,label)=>{
      const deadline=Date.now()+10000;
      while(Date.now()<deadline){if(await predicate()) return;await new Promise(resolve=>setTimeout(resolve,50));}
      throw Error(label);
    };
    const emptyQueue=()=>popup.evaluate(async()=>!(await chrome.storage.local.get({outbox:[]})).outbox.length);
    check((await send({type:'health'})).connection==='unpaired','unpaired worker reports the pairing requirement');
    await popup.evaluate(()=>chrome.storage.local.set({captureProject:'Browser Alpha'}));
    check((await send({type:'capture',payload:{text:'Decision: Use SQLite WAL for browser capture durability.',url:'https://example.com/note',capture_mode:'manual'}})).ok,'capture before pairing is durable offline');
    await popup.evaluate(()=>chrome.storage.local.set({captureProject:'Browser Beta'}));
    check((await send({type:'pair',token:config.token})).ok,'real extension pairing');
    await eventually(emptyQueue,'offline queue did not drain automatically after pairing');
    const pairedQueue=await popup.evaluate(()=>chrome.storage.local.get(['outbox','lastError']));
    check(pairedQueue.outbox.length===0,'pairing automatically drains the offline queue without retry');
    check((await send({type:'health'})).ok,'paired authenticated status');
    const auth={Authorization:'Bearer '+config.token};
    const json=async url=>(await fetch(base+url,{headers:auth})).json();
    check((await json('/status')).pending_captures===1,'capture persisted in SQLite');
    check((await send({type:'flush'})).total_extracted===1,'real extraction');
    check((await json('/entries?project=Browser%20Alpha')).entries.length===1,'queued capture keeps original project');
    check((await json('/entries?project=Browser%20Beta')).entries.length===0,'new project does not inherit capture');
    await popup.evaluate(()=>chrome.storage.local.set({captureProject:'Browser Concurrent'}));
    await worker.evaluate(()=>{
      const real=globalThis.fetch;globalThis.slowStarted=false;
      globalThis.releaseCapture=undefined;
      globalThis.fetch=async(url,options)=>{
        if(String(url).endsWith('/capture') && !globalThis.slowStarted){
          globalThis.slowStarted=true;await new Promise(resolve=>{globalThis.releaseCapture=resolve;});
        }
        return real(url,options);
      };
    });
    check((await send({type:'capture',payload:{text:'Decision: First concurrent capture stays durable.',url:'https://example.com/concurrent'}})).ok,'first slow capture stored');
    await eventually(()=>worker.evaluate(()=>globalThis.slowStarted),'slow capture did not start');
    check(await worker.evaluate(()=>globalThis.slowStarted),'delivery starts before second capture');
    check((await send({type:'capture',payload:{text:'Decision: Second concurrent capture must not wait for an alarm.',url:'https://example.com/concurrent'}})).ok,'new capture remains responsive during slow delivery');
    await worker.evaluate(()=>globalThis.releaseCapture());
    await eventually(emptyQueue,'captures added during delivery did not drain in the same sync');
    check((await json('/status')).pending_captures===2,'same sync persists both concurrent captures to real SQLite');
    const delivered=await json('/status');
    check(delivered.capture_transfer.browser_captures===3,'desktop reports received browser captures before extraction');
    const automatic=await send({type:'capture',payload:{text:'Decision: use a second database for sessions.',url:'https://chatgpt.com/c/fixture',capture_mode:'automatic'}});
    check(automatic.ok===true,'automatic raw capture does not depend on a configured model');
    check((await send({type:'retry'})).ok,'automatic raw capture drains through the durable endpoint');
    check((await json('/status')).pending_captures===3,'automatic raw capture persisted without model review');
    await browser.route('https://example.com/**',route=>route.fulfill({contentType:'text/html',body:'<title>Public note</title><p>Visible project note</p><input value="FORM_SECRET"><textarea>TEXTAREA_SECRET</textarea><div contenteditable>EDIT_SECRET</div><p hidden>HIDDEN_SECRET</p><p style="visibility:hidden">CSS_SECRET</p>'}));
    await page.goto('https://example.com/note');await page.locator('#owlthread-companion').waitFor({state:'attached'});
    const tab=await popup.evaluate(async()=> (await chrome.tabs.query({url:'https://example.com/*'}))[0].id);
    const isolated=await worker.evaluate(async tab=>(await chrome.scripting.executeScript({target:{tabId:tab},func:async()=>{
      let exposed=false;try{exposed=!!(await chrome.storage.local.get('localApiToken')).localApiToken;}catch{}
      const safe=await chrome.runtime.sendMessage({type:'settings_get'});
      const rejected=await chrome.runtime.sendMessage({type:'settings_set',values:{localApiToken:'stolen'}});
      return {exposed,safe,rejected,text:OwlPolicy.pageText()};
    }}))[0].result,tab);
    check(!isolated.exposed,'token inaccessible to content scripts');
    check(!('localApiToken' in isolated.safe.settings),'safe settings bridge excludes token');
    check(!isolated.rejected.ok,'content cannot overwrite credentials');
    check(!isolated.text.includes('SECRET') && isolated.text.includes('Visible project note'),'awareness omits forms and hidden text');
    const mixed=await worker.evaluate(async tab=>(await chrome.scripting.executeScript({target:{tabId:tab},func:()=>{
      const range=document.createRange();range.setStartBefore(document.querySelector('p'));range.setEndAfter(document.querySelector('[contenteditable]'));
      getSelection().removeAllRanges();getSelection().addRange(range);
      const value=OwlPolicy.pageSelection();getSelection().removeAllRanges();return value;
    }}))[0].result,tab);
    check(mixed==='','mixed selection cannot expose editable text');
    check((await fetch(base+'/entries')).status===401,'anonymous real HTTP read rejected');
    console.log(JSON.stringify({suite:'real-browser-api',checks,browser:await browser.browser().version(),passed:true,provider:'offline rules; no paid requests'}));
  }finally{await browser.close();server.stdin.end('\n');await new Promise(resolve=>server.once('exit',resolve));}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
