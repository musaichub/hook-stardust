/* Microphone-only PCM capture. No guide audio, pitch gating, normalization or denoising. */
(function (scope) {
  'use strict';

  const TARGET_SECONDS = 30;
  const PROCESSOR_NAME = 'stardust-microphone-pcm-v1';
  const loadedContexts = new WeakSet();
  const workletSource = `
class StardustMicrophonePCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.active = false;
    this.buffer = new Float32Array(2048);
    this.used = 0;
    this.frames = 0;
    this.levelFrames = 0;
    this.energy = 0;
    this.peak = 0;
    this.clipped = 0;
    this.port.onmessage = ({data}) => {
      if (data.type === 'start') {
        this.active = true;
        this.id = data.id;
        this.limit = data.maxFrames;
        this.frames = 0;
        this.used = 0;
        this.port.postMessage({type:'started', id:this.id});
      } else if (data.type === 'stop' && data.id === this.id) {
        this.finish('stop');
      }
    };
  }
  flush() {
    if (!this.used) return;
    const pcm = this.used === this.buffer.length ? this.buffer : this.buffer.slice(0, this.used);
    this.port.postMessage({type:'pcm', id:this.id, pcm}, [pcm.buffer]);
    this.buffer = new Float32Array(2048);
    this.used = 0;
  }
  finish(reason) {
    if (!this.active) return;
    this.active = false;
    this.flush();
    this.port.postMessage({type:'stopped', id:this.id, frames:this.frames, reason});
  }
  process(inputs, outputs) {
    // This output is deliberately silent; the microphone is never monitored.
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const input = inputs[0];
    if (!input || !input.length) return true;
    for (let i = 0; i < input[0].length; i++) {
      let sample = 0;
      for (let c = 0; c < input.length; c++) sample += input[c][i] || 0;
      sample /= input.length;
      this.energy += sample * sample;
      this.peak = Math.max(this.peak, Math.abs(sample));
      if (Math.abs(sample) >= .999) this.clipped++;
      this.levelFrames++;
      if (this.active) {
        this.buffer[this.used++] = sample;
        this.frames++;
        if (this.used === this.buffer.length) this.flush();
        if (this.frames >= this.limit) this.finish('limit');
      }
    }
    if (this.levelFrames >= sampleRate / 20) {
      this.port.postMessage({type:'level', rms:Math.sqrt(this.energy / this.levelFrames), peak:this.peak,
        clipped:this.clipped / this.levelFrames, frames:this.frames, id:this.id});
      this.levelFrames = 0;
      this.energy = 0;
      this.peak = 0;
      this.clipped = 0;
    }
    return true;
  }
}
registerProcessor('${PROCESSOR_NAME}', StardustMicrophonePCM);
`;

  function joinPCM(chunks) {
    const length = chunks.reduce((n, chunk) => n + chunk.length, 0);
    const pcm = new Float32Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      pcm.set(chunk, offset);
      offset += chunk.length;
    }
    return pcm;
  }

  /** Energy-based phrase checks preserve consonants, breath and internal pauses.
   * Pitch detection is intentionally absent: being off-key is not a recording defect.
   * A measured quiet-room floor may be supplied; never derive it from a sung phrase.
   */
  function analyseCapture(input, sampleRate, options = {}) {
    if (!(input instanceof Float32Array) || !Number.isFinite(sampleRate) || sampleRate < 8000) {
      throw new TypeError('Expected Float32 PCM and a valid sample rate.');
    }
    const frameSize = Math.max(1, Math.round(sampleRate * .02));
    const noiseFloor = Math.max(0, Number(options.noiseFloor) || .001);
    const threshold = Math.max(.004, noiseFloor * 2.5);
    const result = {accepted:false, code:'silence', message:'Sing a little closer to the mic, then try that phrase again.',
      rawSeconds:input.length / sampleRate, seconds:0, activeSeconds:0, activeRatio:0, rms:0, peak:0,
      clippedRatio:0, noiseFloor, threshold, trimStart:0, trimEnd:0, pcm:new Float32Array(0)};
    if (!input.length) return result;
    let first = -1, last = -1, activeFrames = 0, totalEnergy = 0, clipped = 0, invalid = 0;
    for (let offset = 0; offset < input.length; offset += frameSize) {
      const end = Math.min(offset + frameSize, input.length);
      let energy = 0;
      for (let i = offset; i < end; i++) {
        const sample = input[i];
        if (!Number.isFinite(sample)) { invalid++; continue; }
        energy += sample * sample;
        result.peak = Math.max(result.peak, Math.abs(sample));
        if (Math.abs(sample) >= .999) clipped++;
      }
      totalEnergy += energy;
      if (Math.sqrt(energy / (end - offset)) >= threshold) {
        if (first < 0) first = offset;
        last = end;
        activeFrames += end - offset;
      }
    }
    result.rms = Math.sqrt(totalEnergy / input.length);
    result.clippedRatio = clipped / input.length;
    result.activeSeconds = activeFrames / sampleRate;
    if (invalid) return {...result, code:'invalid', message:'The mic audio was interrupted. Please record that phrase again.'};
    if (result.clippedRatio > .003) {
      return {...result, code:'clipping', message:'The mic is distorting. Move it a little farther away and try again.'};
    }
    if (first < 0 || result.activeSeconds < .35) return result;
    // Trim only quiet edges. Keep a generous lead-in for consonants and a tail for breath.
    const start = Math.max(0, first - Math.round(sampleRate * .12));
    const end = Math.min(input.length, last + Math.round(sampleRate * .18));
    const length = end - start;
    result.trimStart = start / sampleRate;
    result.trimEnd = (input.length - end) / sampleRate;
    result.activeRatio = activeFrames / Math.max(1, length);
    if (length < sampleRate * .5) {
      return {...result, code:'short', message:'Keep singing a little longer so we can hear your voice clearly.'};
    }
    if (result.activeRatio < .45) {
      return {...result, code:'gaps', message:'Keep singing through the phrase. We need a little more of your voice.'};
    }
    const pcm = input.slice(start, end);
    // Five-millisecond edge fades prevent clicks when separate phrases are joined.
    const fade = Math.min(Math.round(sampleRate * .005), Math.floor(pcm.length / 2));
    for (let i = 0; i < fade; i++) {
      const gain = i / fade;
      pcm[i] *= gain;
      pcm[pcm.length - 1 - i] *= gain;
    }
    return {...result, accepted:true, code:'ok', message:'Phrase captured.', seconds:pcm.length / sampleRate, pcm};
  }

  class StardustCapture {
    constructor({context, onUpdate, onIssue, targetSeconds = TARGET_SECONDS} = {}) {
      this.context = context || null;
      this.onUpdate = onUpdate || (() => {});
      this.onIssue = onIssue || (() => {});
      this.targetSeconds = targetSeconds;
      this.sampleRate = context ? context.sampleRate : 48000;
      this.takes = [];
      this.noiseFloor = .001;
      this.settings = {};
      this.level = {rms:0, peak:0, clipped:0};
      this._serial = 0;
      this._current = null;
      this._lastResult = null;
      this._closing = false;
      this._levelHistory = [];
      this._onHidden = () => { if (document.hidden) this._interrupt('tab-hidden', 'Recording paused when you left the game. Try that phrase again.'); };
      this._onEnded = () => this._interrupt('microphone-lost', 'The microphone disconnected. Reconnect it and try again.');
      this._onMuted = () => this._interrupt('microphone-muted', 'The microphone was interrupted. Check your mic and try that phrase again.');
      this._onState = () => {
        if (this.context.state !== 'running') this._interrupt('audio-interrupted', 'Audio was interrupted. Return to the game and try that phrase again.');
      };
    }

    get acceptedFrames() { return this.takes.reduce((n, take) => n + take.pcm.length, 0); }
    get acceptedSeconds() { return this.acceptedFrames / this.sampleRate; }
    get pendingSeconds() { return this._current ? this._current.frames / this.sampleRate : 0; }
    get recording() { return !!this._current && !this._current.stopRequested; }
    get complete() { return this.acceptedFrames >= Math.round(this.targetSeconds * this.sampleRate); }

    async open() {
      if (this.stream && this.stream.getAudioTracks().some(track => track.readyState === 'live')) return this._openResult();
      if (!scope.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Microphone recording needs localhost or a secure HTTPS connection.');
      }
      if (!this.context) {
        this.context = new (scope.AudioContext || scope.webkitAudioContext)();
        this._ownsContext = true;
      }
      if (!this.context.audioWorklet || !scope.AudioWorkletNode) throw new Error('This browser does not support reliable microphone recording. Try a current version of Chrome or Safari.');
      this.sampleRate = this.context.sampleRate;
      if (this.context.state !== 'running') await this.context.resume();
      const stream = await navigator.mediaDevices.getUserMedia({audio:{
        channelCount:{ideal:1}, sampleRate:{ideal:this.sampleRate},
        echoCancellation:{ideal:false}, noiseSuppression:{ideal:false}, autoGainControl:{ideal:false}
      }, video:false});
      try {
        if (!loadedContexts.has(this.context)) {
          const url = URL.createObjectURL(new Blob([workletSource], {type:'application/javascript'}));
          try { await this.context.audioWorklet.addModule(url); }
          finally { URL.revokeObjectURL(url); }
          loadedContexts.add(this.context);
        }
        this.stream = stream;
        this.source = this.context.createMediaStreamSource(stream);
        this.node = new AudioWorkletNode(this.context, PROCESSOR_NAME, {numberOfInputs:1, numberOfOutputs:1, outputChannelCount:[1]});
        this.node.port.onmessage = event => this._receive(event.data);
        this.node.onprocessorerror = () => this._interrupt('capture-error', 'The microphone recorder stopped. Please reload the game and try again.');
        this.sink = this.context.createGain();
        this.sink.gain.value = 0;
        this.source.connect(this.node);
        this.node.connect(this.sink);
        this.sink.connect(this.context.destination);
        const track = stream.getAudioTracks()[0];
        this.settings = track.getSettings ? track.getSettings() : {};
        track.addEventListener('ended', this._onEnded);
        track.addEventListener('mute', this._onMuted);
        this.context.addEventListener('statechange', this._onState);
        document.addEventListener('visibilitychange', this._onHidden);
        this._closing = false;
        this._notify();
        return this._openResult();
      } catch (error) {
        stream.getTracks().forEach(track => track.stop());
        throw error;
      }
    }

    _openResult() { return {stream:this.stream, source:this.source, settings:this.settings, sampleRate:this.sampleRate}; }

    setNoiseFloor(rms) {
      if (Number.isFinite(rms) && rms >= 0) this.noiseFloor = Math.min(.2, Math.max(.0001, rms));
      return this.noiseFloor;
    }

    // Call only during an explicitly quiet-room check, before the singing check.
    async measureNoiseFloor(durationMs = 1000) {
      if (this._current) throw new Error('Measure room noise before recording a phrase.');
      this._levelHistory = [];
      await new Promise(resolve => setTimeout(resolve, Math.max(300, Math.min(3000, durationMs))));
      const levels = this._levelHistory.slice().sort((a, b) => a - b);
      if (levels.length) this.setNoiseFloor(levels[Math.floor(levels.length * .75)]);
      return this.noiseFloor;
    }

    async start({round = 0} = {}) {
      if (this._current) await this.stop();
      if (this.complete) return false;
      if (!this.node) await this.open();
      if (!this.stream.getAudioTracks().some(track => track.readyState === 'live')) throw new Error('The microphone disconnected. Reconnect it before recording.');
      if (document.hidden) throw new Error('Return to the game before recording.');
      if (this.context.state !== 'running') await this.context.resume();
      const take = {id:++this._serial, round, chunks:[], frames:0, discard:false, stopRequested:false};
      take.started = new Promise((resolve, reject) => { take.resolveStart = resolve; take.rejectStart = reject; });
      take.stopped = new Promise(resolve => { take.resolveStop = resolve; });
      this._current = take;
      this._lastResult = null;
      // Allow quiet edges to be trimmed without reducing the final accepted duration.
      const maxFrames = Math.ceil(Math.min(60, this.targetSeconds - this.acceptedSeconds + 2) * this.sampleRate);
      take.startTimer = setTimeout(() => {
        if (this._current !== take) return;
        take.discard = true;
        take.rejectStart(new Error('The microphone did not start. Try the mic check again.'));
        this.stop({discard:true});
      }, 3000);
      this.node.port.postMessage({type:'start', id:take.id, maxFrames});
      await take.started;
      this._notify();
      return true;
    }

    async stop({discard = false} = {}) {
      const take = this._current;
      if (!take) return this._lastResult || this._emptyResult();
      take.discard = take.discard || discard;
      if (!take.stopRequested) {
        take.stopRequested = true;
        this.node.port.postMessage({type:'stop', id:take.id});
        take.stopTimer = setTimeout(() => {
          if (this._current !== take) return;
          take.discard = true;
          this._finish(take, 'interrupted');
          this._issue('flush-failed', 'The recording was interrupted. Please try that phrase again.');
        }, 1500);
      }
      return take.stopped;
    }

    _receive(data) {
      if (data.type === 'level') {
        this.level = {rms:data.rms, peak:data.peak, clipped:data.clipped};
        if (!this._current) {
          this._levelHistory.push(data.rms);
          if (this._levelHistory.length > 80) this._levelHistory.shift();
        } else if (data.id === this._current.id) this._current.frames = Math.max(this._current.frames, data.frames);
        this._notify();
        return;
      }
      const take = this._current;
      if (!take || data.id !== take.id) return;
      if (data.type === 'started') {
        clearTimeout(take.startTimer);
        take.resolveStart();
      } else if (data.type === 'pcm') {
        take.chunks.push(data.pcm);
      } else if (data.type === 'stopped') {
        take.frames = data.frames;
        this._finish(take, data.reason);
      }
    }

    _finish(take, reason) {
      if (this._current !== take) return;
      clearTimeout(take.startTimer);
      clearTimeout(take.stopTimer);
      take.resolveStart();
      const raw = joinPCM(take.chunks);
      let quality = take.discard ? {accepted:false, code:'interrupted', message:'Interrupted phrase discarded.'}
        : analyseCapture(raw, this.sampleRate, {noiseFloor:this.noiseFloor});
      let pcm = quality.accepted ? quality.pcm : new Float32Array(0);
      const remaining = Math.max(0, Math.round(this.targetSeconds * this.sampleRate) - this.acceptedFrames);
      if (pcm.length > remaining) pcm = pcm.slice(0, remaining);
      // Do not retain a second large PCM reference inside the quality metadata.
      const {pcm:unusedPCM, ...metadata} = quality;
      quality = {...metadata, accepted:pcm.length > 0, seconds:pcm.length / this.sampleRate};
      if (pcm.length) this.takes.push({round:take.round, pcm, quality});
      const result = {takeId:take.id, round:take.round, pcm, quality, acceptedSeconds:pcm.length / this.sampleRate,
        totalSeconds:this.acceptedSeconds, complete:this.complete, reason};
      this._current = null;
      this._lastResult = result;
      take.chunks = [];
      take.resolveStop(result);
      this._notify();
      if (!quality.accepted && !take.discard) this._issue(quality.code, quality.message);
    }

    _emptyResult() {
      return {pcm:new Float32Array(0), quality:{accepted:false, code:'empty', message:'No phrase recorded.'},
        acceptedSeconds:0, totalSeconds:this.acceptedSeconds, complete:this.complete};
    }

    _interrupt(code, message) {
      if (this._closing) return;
      if (this._current) this.stop({discard:true});
      // Track loss matters even between phrases. An idle tab or context does not.
      if (this._current || code === 'microphone-lost' || code === 'capture-error') this._issue(code, message);
    }

    _issue(code, message) { try { this.onIssue({code, message}); } catch (error) { console.error(error); } }
    _notify() {
      try {
        this.onUpdate({recording:this.recording, acceptedSeconds:this.acceptedSeconds, pendingSeconds:this.pendingSeconds,
          totalSeconds:this.acceptedSeconds, complete:this.complete, level:this.level.rms, peak:this.level.peak,
          clipped:this.level.clipped, active:this.level.rms >= Math.max(.004, this.noiseFloor * 2.5), settings:this.settings});
      } catch (error) { console.error(error); }
    }

    removeRound(round) {
      if (this._current && this._current.round === round) throw new Error('Stop the current phrase before retrying this round.');
      this.takes = this.takes.filter(take => take.round !== round);
      this._lastResult = null;
      this._notify();
    }

    reset() {
      const pending = this._current ? this.stop({discard:true}) : Promise.resolve();
      this.takes = [];
      this._lastResult = null;
      this._notify();
      return pending;
    }

    exportPCM() { return joinPCM(this.takes.map(take => take.pcm)); }

    async close() {
      this._closing = true;
      if (this._current) await this.stop({discard:true});
      document.removeEventListener('visibilitychange', this._onHidden);
      if (this.context) this.context.removeEventListener('statechange', this._onState);
      if (this.stream) for (const track of this.stream.getTracks()) {
        track.removeEventListener('ended', this._onEnded);
        track.removeEventListener('mute', this._onMuted);
        track.stop();
      }
      if (this.source) this.source.disconnect();
      if (this.node) { this.node.disconnect(); this.node.port.close(); }
      if (this.sink) this.sink.disconnect();
      this.source = this.node = this.sink = this.stream = null;
      if (this._ownsContext && this.context.state !== 'closed') await this.context.close();
    }
  }

  scope.StardustCapture = StardustCapture;
  if (typeof module !== 'undefined' && module.exports) module.exports = {StardustCapture, analyseCapture, joinPCM, workletSource};
})(typeof window !== 'undefined' ? window : globalThis);
