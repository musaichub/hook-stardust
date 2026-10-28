/* Run with: node games/stardust/source/test_capture.cjs */
'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {StardustCapture, analyseCapture, joinPCM, workletSource} = require('./capture.js');

const sampleRate = 8000;
function tone(seconds, frequency = 173, amplitude = .12) {
  const out = new Float32Array(Math.round(seconds * sampleRate));
  for (let i = 0; i < out.length; i++) out[i] = Math.sin(i * frequency * Math.PI * 2 / sampleRate) * amplitude;
  return out;
}
function silence(seconds) { return new Float32Array(Math.round(seconds * sampleRate)); }

// Neither silent input nor a near-silent microphone may count towards 30 seconds.
assert.equal(analyseCapture(silence(3), sampleRate).accepted, false);
assert.equal(analyseCapture(tone(3, 200, .0005), sampleRate).accepted, false);

// Loud clipped input must be retried, not quietly normalized and accepted.
const clipped = tone(2, 200, 4);
for (let i = 0; i < clipped.length; i++) clipped[i] = Math.max(-1, Math.min(1, clipped[i]));
assert.equal(analyseCapture(clipped, sampleRate).code, 'clipping');

// Low, high and off-target pitches all remain acceptable source audio.
for (const frequency of [83, 173, 700]) assert.equal(analyseCapture(tone(2, frequency), sampleRate).accepted, true);
assert.equal(analyseCapture(tone(2, 173, .025), sampleRate, {noiseFloor:.012}).accepted, false);
assert.equal(analyseCapture(tone(2, 173, .15), sampleRate, {noiseFloor:.012}).accepted, true);

// Only quiet edges are trimmed: an internal pause and its neighbouring samples survive.
const sung = joinPCM([tone(.8), silence(.15), tone(.8, 212)]);
const edged = joinPCM([silence(.8), sung, silence(.8)]);
const checked = analyseCapture(edged, sampleRate);
assert.equal(checked.accepted, true);
assert.ok(checked.trimStart > .6 && checked.trimStart < .72);
assert.ok(checked.trimEnd > .58 && checked.trimEnd < .7);
const trimOffset = Math.round(checked.trimStart * sampleRate);
for (let i = 100; i < checked.pcm.length - 100; i++) assert.equal(checked.pcm[i], edged[trimOffset + i]);
const sparse = joinPCM([tone(.5), silence(3), tone(.5)]);
assert.equal(analyseCapture(sparse, sampleRate).code, 'gaps');

// Exercise the real processor: it captures only its input, downmixes stereo,
// never monitors the mic, and flushes every last frame before its stop message.
let Processor;
const messages = [];
class FakeProcessor {
  constructor() { this.port = {postMessage:data => messages.push(data), onmessage:null}; }
}
vm.runInNewContext(workletSource, {
  AudioWorkletProcessor:FakeProcessor, sampleRate,
  registerProcessor:(_name, Class) => { Processor = Class; },
  Float32Array, Math
});
const processor = new Processor();
const outputs = [[new Float32Array(128).fill(1)]];
processor.process([[new Float32Array(128).fill(.8)]], outputs);
assert.equal(messages.filter(m => m.type === 'pcm').length, 0);
assert.ok(outputs[0][0].every(value => value === 0));
processor.port.onmessage({data:{type:'start', id:7, maxFrames:1000}});
for (let i = 0; i < 10; i++) processor.process([[new Float32Array(128).fill(.2), new Float32Array(128).fill(.4)]], outputs);
const captured = joinPCM(messages.filter(m => m.type === 'pcm').map(m => m.pcm));
assert.equal(captured.length, 1000, 'The worklet stops on the exact requested sample frame.');
assert.ok(captured.every(value => Math.abs(value - .3) < 1e-6));
const finalIndex = messages.findIndex(m => m.type === 'stopped');
assert.ok(finalIndex > messages.findIndex(m => m.type === 'pcm'));
assert.equal(messages[finalIndex].frames, 1000);
messages.length = 0;
processor.port.onmessage({data:{type:'start', id:8, maxFrames:10000}});
for (let i = 0; i < 20; i++) processor.process([[new Float32Array(128).fill(.2)]], outputs);
processor.port.onmessage({data:{type:'stop', id:8}});
assert.equal(joinPCM(messages.filter(m => m.type === 'pcm').map(m => m.pcm)).length, 2560);
assert.equal(messages.at(-1).type, 'stopped');

// Exercise accepted-duration accounting, trimming, retries, reset and flush promises.
global.document = {hidden:false};
const capture = new StardustCapture({context:{sampleRate, state:'running'}});
capture.stream = {getAudioTracks:() => [{readyState:'live'}]};
let nextPCM;
capture.node = {port:{postMessage:message => {
  queueMicrotask(() => {
    if (message.type === 'start') capture._receive({type:'started', id:message.id});
    else {
      capture._receive({type:'pcm', id:message.id, pcm:nextPCM});
      capture._receive({type:'stopped', id:message.id, frames:nextPCM.length, reason:'stop'});
    }
  });
}}};
async function record(round, pcm, options) {
  nextPCM = pcm;
  await capture.start({round});
  assert.equal(capture.acceptedSeconds, capture.exportPCM().length / sampleRate);
  return capture.stop(options);
}

(async () => {
  let result = await record(0, silence(5));
  assert.equal(result.acceptedSeconds, 0);
  assert.equal(capture.acceptedSeconds, 0);
  result = await record(0, tone(12));
  assert.equal(result.acceptedSeconds, 12);
  result = await record(1, tone(12, 221));
  assert.equal(result.totalSeconds, 24);
  result = await record(2, tone(10, 185));
  assert.equal(result.acceptedSeconds, 6);
  assert.equal(result.totalSeconds, 30);
  assert.equal(result.complete, true);
  assert.equal(capture.exportPCM().length, 30 * sampleRate);
  assert.equal(await capture.start({round:3}), false);
  capture.removeRound(1);
  assert.equal(capture.acceptedSeconds, 18);
  assert.equal(capture.complete, false);
  result = await record(1, tone(12, 221), {discard:true});
  assert.equal(result.acceptedSeconds, 0);
  assert.equal(capture.acceptedSeconds, 18);
  assert.equal(result.quality.code, 'interrupted');
  await capture.reset();
  assert.equal(capture.acceptedSeconds, 0);
  assert.equal(capture.exportPCM().length, 0);
  nextPCM = tone(3);
  await capture.start({round:0});
  await capture.reset();
  assert.equal(capture.acceptedSeconds, 0, 'Reset cannot allow an unfinished phrase back into the next game.');
  console.log('Capture checks passed: quality, preserved phrasing, exact PCM flush, 30-second cap and retry/reset accounting.');
})().catch(error => { console.error(error); process.exitCode = 1; });
