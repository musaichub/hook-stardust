#!/usr/bin/env node
/* Real browser/worklet recording tests. All service requests are intercepted. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/manondave/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const ROOT = path.resolve(__dirname, '..');
const QA = path.join(ROOT, 'qa');
const URL = process.env.STARDUST_TEST_URL || 'http://127.0.0.1:8765/';
const FIXTURE = '/tmp/stardust-original-voice-fixture.wav';
const GAMES = ['rocketfuel', 'moonshot', 'echo', 'jetpack'];
const args = process.argv.slice(2);
const exitSmoke = args.includes('--exit-smoke');
const namedGames = args.filter(arg => !arg.startsWith('--'));
const selected = namedGames.length ? namedGames : GAMES;
fs.mkdirSync(QA, { recursive: true });

function wavHeader(buffer, sampleRate, sampleCount) {
  buffer.write('RIFF', 0); buffer.writeUInt32LE(36 + sampleCount * 2, 4);
  buffer.write('WAVEfmt ', 8); buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24); buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36); buffer.writeUInt32LE(sampleCount * 2, 40);
}
function createFixture() {
  const rate = 48000, seconds = 180, count = rate * seconds;
  const out = Buffer.alloc(44 + count * 2); wavHeader(out, rate, count);
  // Three seconds of quiet for the actual room-noise calibration, then a fresh
  // harmonic vowel-like source. This is generated audio, never a copied voice.
  for (let i = rate * 3; i < count; i++) {
    const t = (i - rate * 3) / rate, phase = 2 * Math.PI * 220 * t;
    const ramp = Math.min(1, t / 0.04);
    const value = 0.1 * ramp * (0.7 * Math.sin(phase) + 0.2 * Math.sin(2 * phase) + 0.1 * Math.sin(3 * phase));
    out.writeInt16LE(Math.round(value * 32767), 44 + i * 2);
  }
  fs.writeFileSync(FIXTURE, out);
}
function readWav(buffer) {
  assert.equal(buffer.toString('ascii', 0, 4), 'RIFF');
  assert.equal(buffer.toString('ascii', 8, 12), 'WAVE');
  const rate = buffer.readUInt32LE(24), channels = buffer.readUInt16LE(22);
  const bits = buffer.readUInt16LE(34), bytes = buffer.readUInt32LE(40);
  assert.equal(channels, 1); assert.equal(bits, 16); assert.equal(buffer.length, 44 + bytes);
  assert.equal(bytes / 2, rate * 30);
  return { bytes:buffer.length, rate, channels, bits, frames:bytes / 2, seconds:bytes / 2 / rate };
}

const browsers = new Set();
const watchdog = setTimeout(async () => {
  console.error('Browser flow test exceeded 10-minute limit.');
  await Promise.allSettled([...browsers].map(browser => browser.close()));
  process.exit(2);
}, 600000);

async function gameFlow(key) {
  const began = Date.now(), errors = [], blocked = [], apiCalls = [];
  const service = { ready:false, training:false, posts:0, polls:0, upload:null };
  let browser, page, heartbeat;
  const log = message => console.log(`[${key} +${Math.round((Date.now() - began) / 1000)}s] ${message}`);
  try {
    browser = await chromium.launch({ channel:'chrome', headless:true, args:[
      '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${FIXTURE}`,
      '--autoplay-policy=no-user-gesture-required',
      '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
      '--disable-backgrounding-occluded-windows'
    ] });
    browsers.add(browser);
    const context = await browser.newContext({ viewport:{width:1440,height:1000}, permissions:['microphone'], acceptDownloads:true });
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if(message.type() === 'error' && !message.text().includes('favicon.ico')) errors.push(message.text()); });
    await page.route('**/api/**', async route => {
      const request = route.request(), pathname = new globalThis.URL(request.url()).pathname;
      apiCalls.push({ path:pathname, method:request.method() });
      const send = data => route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify(data) });
      if(pathname === '/api/status') return send({ready:service.ready, blockers:service.ready?[]:['Test service: live requests disabled.']});
      if(pathname === '/api/training' && service.training && request.method() === 'POST') {
        service.posts++;
        service.upload = readWav(request.postDataBuffer());
        assert.equal(request.headers()['x-model-name'], 'Browser QA voice');
        return send({job_id:`qa-${key}`,training_set_id:`qa-set-${key}`});
      }
      if(pathname === `/api/jobs/qa-${key}` && service.training) {
        service.polls++;
        return send(service.polls === 1 ? {status:'queued'} : {status:'succeeded',result:{model_id:`qa-model-${key}`}});
      }
      blocked.push(`${request.method()} ${pathname}`);
      return route.abort('blockedbyclient');
    });
    await page.goto(URL, {waitUntil:'networkidle'});
    await page.locator('#games .game').first().waitFor();
    if(key === selected[0]) {
      await page.screenshot({path:path.join(QA,'home.png'),fullPage:true});
      const mobile = await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,isMobile:true,hasTouch:true});
      const phone = await mobile.newPage();
      await phone.goto(URL,{waitUntil:'networkidle'});
      await phone.screenshot({path:path.join(QA,'home-mobile.png'),fullPage:true});
      assert(await phone.locator('#games .game').count() === 4);
      await mobile.close();
    }
    await page.locator('#games .game').nth(GAMES.indexOf(key)).click();
    assert.equal(await page.locator('#pick .rec').count(),5);
    assert.equal(await page.locator('#pick .rec.sel').count(),3);
    await page.locator('#btn-mic').click();
    log('Mic opened; waiting for real calibration.');
    await page.locator('#btn-start').waitFor({state:'visible',timeout:20000});
    await page.locator('#btn-start').click();
    log('Calibrated; starting gameplay.');
    heartbeat = setInterval(async () => {
      try { const snapshot = await page.evaluate(() => ({phase:__stardust.S.phase,round:__stardust.S.round,kept:__stardust.totalSec(),stage:__stardust.G.stage,pending:__stardust.captureInfo.pendingSeconds})); log(JSON.stringify(snapshot)); } catch {}
    },20000);
    const rounds = [];
    for(let step = 0; step < 12; step++) {
      await page.locator('#btn-go').waitFor({state:'visible',timeout:15000});
      await page.locator('#btn-go').click();
      await page.locator('#btn-next').waitFor({state:'visible',timeout:160000});
      const result = await page.evaluate(() => ({phase:__stardust.S.phase,round:__stardust.S.round,kept:__stardust.totalSec(),lead:document.querySelector('#res-lead').textContent}));
      assert.notEqual(result.phase,'interrupted',result.lead);
      rounds.push(result); log(`Round result: ${JSON.stringify(result)}`);
      await page.locator('#btn-next').click();
      await page.waitForFunction(() => ['intro','final'].includes(__stardust.S.phase),undefined,{timeout:15000});
      if(await page.evaluate(() => __stardust.S.phase === 'final')) break;
    }
    await page.locator('#s-final:not(.hidden)').waitFor({timeout:10000});
    clearInterval(heartbeat); heartbeat = null;
    const recording = await page.evaluate(async () => {
      const app=__stardust, pcm=app.mergedBuffer(), blob=app.wavBlob(pcm,app.S.sr), data=await blob.arrayBuffer(), view=new DataView(data);
      let peak=0,energy=0,invalid=0; for(const value of pcm){ if(!Number.isFinite(value)) invalid++;peak=Math.max(peak,Math.abs(value));energy+=value*value; }
      return {frames:pcm.length,sampleRate:app.S.sr,seconds:app.totalSec(),wavBytes:blob.size,wavFrames:view.getUint32(40,true)/2,wavRate:view.getUint32(24,true),peak,rms:Math.sqrt(energy/pcm.length),invalid,
        noiseFloor:app.capture.noiseFloor, takes:app.capture.takes.map(t=>({round:t.round,frames:t.pcm.length,quality:t.quality}))};
    });
    assert.equal(recording.seconds,30);
    assert.equal(recording.frames,recording.sampleRate*30);
    assert.equal(recording.wavFrames,recording.wavRate*30);
    assert.equal(recording.invalid,0); assert(recording.peak>0.01 && recording.peak<0.98);
    assert(recording.rms>0.004); assert(recording.takes.length>0);
    assert(recording.takes.every(t=>t.quality.accepted));
    assert.equal(await page.locator('#st-audio').textContent(),'30.0 s');
    assert.notEqual(await page.locator('#st-range').textContent(),'No pitch detected','Detected calibration and recorded voice must produce a pitch range.');
    await page.waitForFunction(() => document.querySelector('#service-status').textContent.includes('live requests disabled'));
    assert.equal(await page.locator('#btn-build').isDisabled(),true);
    assert.equal(service.posts,0); assert.equal(blocked.length,0);
    await page.screenshot({path:path.join(QA,`${key}-final.png`),fullPage:true});
    await page.locator('#btn-hear').click();
    await page.getByRole('button',{name:'Stop',exact:true}).waitFor();
    await page.getByRole('button',{name:'Stop',exact:true}).click();
    const downloadEvent=page.waitForEvent('download'); await page.locator('#btn-save').click();
    const download=await downloadEvent; const downloaded=await download.path();
    const saved=readWav(fs.readFileSync(downloaded));
    service.ready=true;service.training=true;
    await page.locator('#btn-refresh').click();
    await page.waitForFunction(() => !document.querySelector('#btn-build').disabled);
    await page.locator('#model-name').fill('Browser QA voice');
    await page.locator('#btn-build').click();
    await page.waitForFunction(() => document.querySelector('#service-status').textContent.includes('queued'));
    await page.waitForFunction(model => document.querySelector('#final-id').textContent === model,`qa-model-${key}`,{timeout:20000});
    assert.equal(service.posts,1);assert.equal(service.polls,2);assert.equal(service.upload.seconds,30);
    assert.equal(await page.locator('#transform-controls').isVisible(),true);
    assert.equal(blocked.length,0);assert.deepEqual(errors,[]);
    const report={game:key,passed:true,secondsElapsed:Math.round((Date.now()-began)/1000),rounds,recording,saved,mockedUpload:service.upload,apiCalls,errors,blocked};
    fs.writeFileSync(path.join(QA,`${key}-flow.json`),JSON.stringify(report,null,2));
    log(`PASS: ${recording.frames} real worklet samples, ${recording.sampleRate} Hz, exactly 30 s; WAV download and mocked training/poll passed.`);
    return report;
  } catch(error) {
    let state=null;
    if(page) {
      try{state=await page.evaluate(()=>({phase:window.__stardust?.S.phase,round:window.__stardust?.S.round,kept:window.__stardust?.totalSec(),mic:document.querySelector('#mic-status')?.textContent,capture:window.__stardust?.captureInfo,noise:window.__stardust?.capture?.noiseFloor,titleNote:document.querySelector('#title-note')?.textContent}));}catch{}
      try{await page.screenshot({path:path.join(QA,`${key}-failure.png`),fullPage:true});}catch{}
    }
    const report={game:key,passed:false,error:error.stack,state,apiCalls,errors,blocked};
    fs.writeFileSync(path.join(QA,`${key}-flow.json`),JSON.stringify(report,null,2));
    log(`FAIL: ${error.message}; state=${JSON.stringify(state)}`);
    return report;
  } finally {
    if(heartbeat) clearInterval(heartbeat);
    if(browser){browsers.delete(browser);await browser.close();}
  }
}

async function exitFlow() {
  const browser=await chromium.launch({channel:'chrome',headless:true,args:[
    '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${FIXTURE}`,'--autoplay-policy=no-user-gesture-required'
  ]});
  browsers.add(browser);
  const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['microphone']});
  const page=await context.newPage(), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ready:false,blockers:['Test service disabled.']})}));
  try {
    await page.goto(URL,{waitUntil:'networkidle'});
    await page.locator('#games .game').nth(1).click();
    await page.locator('#btn-mic').click();
    await page.locator('#btn-start').waitFor({state:'visible',timeout:20000});
    await page.locator('#btn-start').click();
    await page.locator('#btn-go').click();
    await page.waitForFunction(()=>__stardust.S.rec.active&&__stardust.captureInfo.pendingSeconds>0.5);
    await page.locator('#btn-exit').click();
    await page.locator('#s-home:not(.hidden)').waitFor();
    await page.waitForTimeout(2000);
    const state=await page.evaluate(()=>({phase:__stardust.S.phase,recording:__stardust.S.rec.active,
      stream:__stardust.S.stream,sourceOpen:!!__stardust.capture.node,home:!document.querySelector('#s-home').classList.contains('hidden'),
      result:!document.querySelector('#s-result').classList.contains('hidden')}));
    assert.equal(state.phase,'home');assert.equal(state.recording,false);assert.equal(state.stream,null);
    assert.equal(state.sourceOpen,false);assert.equal(state.home,true);assert.equal(state.result,false);assert.deepEqual(errors,[]);
    const report={passed:true,state,errors};
    fs.writeFileSync(path.join(QA,'exit-during-recording.json'),JSON.stringify(report,null,2));
    console.log('[exit smoke] PASS: recording stops, mic closes, home remains visible.');
    return report;
  } catch(error) {
    const report={passed:false,error:error.stack,errors};
    fs.writeFileSync(path.join(QA,'exit-during-recording.json'),JSON.stringify(report,null,2));
    console.error('[exit smoke] FAIL:',error.message);return report;
  } finally {browsers.delete(browser);await browser.close();}
}

(async()=>{
  createFixture();
  console.log('Generated original 180-second 48 kHz fixture; all /api requests mocked.');
  const results=await Promise.all(selected.map(gameFlow));
  const exitResult = exitSmoke ? await exitFlow() : null;
  clearTimeout(watchdog);
  const summaryFile = path.join(QA,'browser-flow-summary.json');
  let prior=[]; try{prior=JSON.parse(fs.readFileSync(summaryFile,'utf8')).results||[];}catch{}
  const merged = GAMES.map(game => results.find(result=>result.game===game)||prior.find(result=>result.game===game)).filter(Boolean);
  fs.writeFileSync(summaryFile,JSON.stringify({url:URL,generatedAt:new Date().toISOString(),latestRun:selected,results:merged,...(exitResult?{exitSmoke:exitResult}:{})},null,2));
  console.log(JSON.stringify(results.map(r=>({game:r.game,passed:r.passed,secondsElapsed:r.secondsElapsed,error:r.error?.split('\n')[0]})),null,2));
  process.exitCode=results.every(r=>r.passed)&&(!exitResult||exitResult.passed)?0:1;
})().catch(error=>{clearTimeout(watchdog);console.error(error);process.exitCode=1;});
