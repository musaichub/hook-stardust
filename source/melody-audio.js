/* Original additive-synthesis guides. No recordings or sample libraries. */
(function (global) {
  'use strict';
  const RATE = 16000;

  function tone(samples, start, duration, frequency, amplitude = 0.2) {
    const first = Math.round(start * RATE);
    const count = Math.min(Math.round(duration * RATE), samples.length - first);
    for (let i = 0; i < count; i++) {
      const t = i / RATE;
      const envelope = Math.max(0, Math.min(1, t / 0.012, (duration - t) / 0.045));
      const phase = 2 * Math.PI * frequency * t;
      samples[first + i] += amplitude * envelope * (
        Math.sin(phase) + 0.18 * Math.sin(2 * phase) + 0.06 * Math.sin(3 * phase)
      ) / 1.24;
    }
  }

  function buffer(context, seconds) {
    return context.createBuffer(1, Math.ceil(seconds * RATE), RATE);
  }

  function decode(context, song) {
    if (song.listenBuf && song.singBuf && song.vocalBuf) return song;
    if (song.sourceType !== 'public-domain-synthesis' || !song.notes.length) {
      throw new Error('This melody has no original guide sequence.');
    }
    const vocalBuf = buffer(context, song.take);
    const listenBuf = buffer(context, song.clipDur);
    const singBuf = buffer(context, song.clipDur);
    const guide = vocalBuf.getChannelData(0);
    const listen = listenBuf.getChannelData(0);
    const capture = singBuf.getChannelData(0);
    for (const note of song.notes) {
      tone(guide, note.t, note.dur, 440 * Math.pow(2, (note.midi - 69) / 12));
    }
    for (let count = 0; count < 4; count++) {
      const frequency = count === 0 ? 880 : 660;
      tone(listen, count * song.beat, 0.045, frequency, 0.13);
      tone(capture, count * song.beat, 0.045, frequency, 0.13);
    }
    const offset = Math.round(song.preroll * RATE);
    listen.set(guide.subarray(0, listen.length - offset), offset);
    // The recording interval is intentionally silent. Only the player's mic is
    // captured; the application supplies a visual beat and lyric guide.
    song.listenBuf = listenBuf;
    song.singBuf = singBuf;
    song.vocalBuf = vocalBuf;
    return song;
  }

  global.StardustMelodyAudio = Object.freeze({ decode, sampleRate: RATE });
})(typeof window === 'object' ? window : globalThis);
