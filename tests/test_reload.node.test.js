const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.join(__dirname, '..');
const base = process.env.WORKSHOP_TEST_URL || 'http://127.0.0.1:8187';
let server;
test.before(async () => {
  if (process.env.WORKSHOP_TEST_URL) return;
  server = spawn(path.join(root, '.venv/bin/python'), ['-m','flask','--app','web.app','run','--port','8187'],
    {cwd:root, env:{...process.env,FLASK_SKIP_DOTENV:'1'},stdio:'ignore'});
  for(let i=0;i<100;i++) {
    try {if((await fetch(base+'/healthz')).ok) return;} catch (_) {}
    await new Promise(r=>setTimeout(r,100));
  }
  throw new Error('Test server did not start');
});
test.after(()=>server?.kill());

test('a PDF without fields survives reload with drafts, repairs, evidence and undo history', async()=>{
 const browser=await chromium.launch();
 try {
  const context=await browser.newContext({acceptDownloads:true});
  const page=await context.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.locator('#pdf-file').setInputFiles(path.join(__dirname,'plain-document.pdf'));
  await page.getByRole('button',{name:'Open workshop'}).click();
  await page.locator('#a11y-workshop').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  const route=page.url();assert.match(route,/\/review\/[a-f0-9-]{36}$/);
  const text=await page.locator('[data-aw-ref=main]').innerText();
  assert.match(text,/This PDF has no form fields/);assert.match(text,/not applicable/);
  await page.getByRole('button',{name:'Confirm title & language',exact:true}).click();
  await page.locator('#aw-title').fill('Community meeting — reviewed');
  await page.locator('#aw-language').selectOption('en-US');
  await page.getByRole('button',{name:'Confirm title & language',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#a11y-workshop').getAttribute('aria-busy') || document.querySelector('#a11y-workshop').getAttribute('aria-busy')==='false');
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  const record=await page.evaluate(async()=>{
    const db=await new Promise(r=>{const q=indexedDB.open('pdf-accessibility-workshop',1);q.onsuccess=()=>r(q.result)});
    return new Promise(r=>{const q=db.transaction('reviews').objectStore('reviews').getAll();q.onsuccess=()=>r({...q.result[0],hasSet:q.result[0].snapshot.decisions.tabConfirmedPages instanceof Set})});
  });
  assert.equal(record.snapshot.decisions.meta.title,'Community meeting — reviewed');
  assert.equal(record.snapshot.decisions.meta.confirmed,true);
  assert.equal(record.hasSet,true);
  assert.ok(record.snapshot.state.history.length>0);
  const historyCount=record.snapshot.state.history.length;
  await page.reload();
  await page.locator('#a11y-workshop').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  assert.equal(page.url(),route);
  await page.locator('[data-aw="task"][data-task="document"]').first().click();
  assert.equal(await page.locator('#aw-title').inputValue(),'Community meeting — reviewed');
  const restored=await page.evaluate(async()=>{
    const db=await new Promise(r=>{const q=indexedDB.open('pdf-accessibility-workshop',1);q.onsuccess=()=>r(q.result)});
    return new Promise(r=>{const q=db.transaction('reviews').objectStore('reviews').getAll();q.onsuccess=()=>r({...q.result[0],hasSet:q.result[0].snapshot.decisions.tabConfirmedPages instanceof Set})});
  });
  assert.equal(restored.snapshot.state.history.length,historyCount);
  assert.deepEqual(restored.snapshot.state.working,record.snapshot.state.working);
  // An unconfirmed draft must also survive, without becoming confirmed.
  await page.locator('#aw-title').fill('Unconfirmed draft');
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  assert.equal(await page.locator('#aw-title').inputValue(),'Unconfirmed draft');
  await page.locator('[data-aw="step"][data-step="test"]').click();
  await page.locator('[data-aw="external-record"][data-test="validator"]').click();
  await page.locator('label[for="aw-ext-validator-fail"]').click();
  await page.locator('#aw-ext-notes-validator').fill('Test evidence: headings need review');
  await page.locator('[data-aw="external-done"]').click();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Saved in this browser');
  assert.match(await page.locator('[data-aw-ref=main]').innerText(),/Test evidence: headings need review/);
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-aw="export"]').click()]);
  assert.match(download.suggestedFilename(),/accessible\.pdf$/);
  // The same URL in another browser has no server-stored document.
  const other=await browser.newContext();const missing=await other.newPage();await missing.goto(route);
  await missing.locator('#notice').waitFor({state:'visible'});
  assert.match(await missing.locator('#notice').innerText(),/not saved in this browser/);
  await other.close();
  page.on('dialog',d=>d.accept());await page.locator('[data-aw="close"]').click();
  await page.locator('#saved-reviews a').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Delete saved review of plain-document.pdf'}).click();
  await page.locator('#saved-reviews').waitFor({state:'hidden'});
  assert.deepEqual(errors,[]);
 } finally {await browser.close();}
});
