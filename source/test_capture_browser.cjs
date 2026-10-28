/* Real Chromium AudioWorklet smoke; uses a generated input stream, never the physical mic.
 * Run: node games/stardust/source/test_capture_browser.cjs
 * Set PLAYWRIGHT_MODULE if Playwright is installed elsewhere.
 */
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '/Users/manondave/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const captureSource = fs.readFileSync(path.join(__dirname, 'capture.js'));
const server = http.createServer((request, response) => {
  response.setHeader('Content-Type', request.url === '/capture.js' ? 'text/javascript' : 'text/html');
  response.end(request.url === '/capture.js' ? captureSource : '<!doctype html><title>Stardust capture check</title><script src="/capture.js"></script>');
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({channel:'chrome', headless:true, args:['--autoplay-policy=no-user-gesture-required']});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      const context = new AudioContext({sampleRate:48000});
      await context.resume();
      const input = context.createMediaStreamDestination();
      const source = context.createOscillator(); source.frequency.value = 220;
      const inputGain = context.createGain(); inputGain.gain.value = 0;
      source.connect(inputGain).connect(input); source.start();
      // A separate loud guide reaches the speakers, but must never enter captured PCM.
      const guide = context.createOscillator(); guide.frequency.value = 1000;
      const guideGain = context.createGain(); guideGain.gain.value = .4;
      guide.connect(guideGain).connect(context.destination); guide.start();
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {value:async () => input.stream, configurable:true});
      const issues = [];
      const capture = new StardustCapture({context, onIssue:issue => issues.push(issue)});
      await capture.open();
      window.check = {context, source, guide, inputGain, capture, issues};
    });
    await page.evaluate(() => check.capture.start({round:0}));
    await page.waitForTimeout(1100);
    const silence = await page.evaluate(async () => {
      const result = await check.capture.stop();
      return {code:result.quality.code, frames:result.pcm.length, accepted:check.capture.acceptedSeconds};
    });
    assert.equal(silence.code, 'silence'); assert.equal(silence.frames, 0); assert.equal(silence.accepted, 0);

    await page.evaluate(async () => { check.inputGain.gain.value = 3; await check.capture.start({round:1}); });
    await page.waitForTimeout(1100);
    const clipping = await page.evaluate(async () => {
      const result = await check.capture.stop();
      return {code:result.quality.code, frames:result.pcm.length};
    });
    assert.equal(clipping.code, 'clipping'); assert.equal(clipping.frames, 0);

    await page.evaluate(async () => {
      check.inputGain.gain.value = .12;
      check.startedAt = performance.now();
      await check.capture.start({round:2});
    });
    await page.waitForFunction(() => check.capture.complete, null, {timeout:40000});
    const report = await page.evaluate(async () => {
      const result = await check.capture.stop();
      const pcm = check.capture.exportPCM();
      const rate = check.capture.sampleRate;
      function amplitude(frequency) {
        let real = 0, imaginary = 0;
        for (let i = rate; i < rate * 2; i++) {
          const phase = 2 * Math.PI * frequency * i / rate;
          real += pcm[i] * Math.cos(phase); imaginary += pcm[i] * Math.sin(phase);
        }
        return Math.hypot(real, imaginary) * 2 / rate;
      }
      const report = {sampleRate:rate, frames:pcm.length, seconds:pcm.length / rate,
        elapsedSeconds:(performance.now() - check.startedAt) / 1000, reason:result.reason,
        sourceAmplitude:amplitude(220), guideAmplitude:amplitude(1000),
        accepted:result.quality.accepted, rejectedChecks:check.issues.map(issue => issue.code)};
      await check.capture.close(); check.source.stop(); check.guide.stop(); await check.context.close();
      return report;
    });
    assert.equal(report.frames, report.sampleRate * 30);
    assert.equal(report.seconds, 30);
    assert.equal(report.accepted, true);
    assert.equal(report.reason, 'limit');
    assert.ok(report.elapsedSeconds >= 29, 'Evidence must come from real-time AudioWorklet capture.');
    assert.ok(report.sourceAmplitude > .1);
    assert.ok(report.guideAmplitude < .0001, 'The speaker guide must not leak digitally into captured PCM.');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({result:'passed', method:'Real Chromium AudioWorklet with generated input stream; physical microphone not tested', ...report}, null, 2));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
