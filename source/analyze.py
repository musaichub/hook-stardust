#!/usr/bin/env python3
"""Analyse one song for HOOK Stardust.
Inputs: songs/<key>/tuned.wav plus the separated vocals/instrumental wavs.
Outputs: songs/<key>/phrase.json, listen.mp3 (full mix), sing.mp3 (instrumental), vocals_phrase.wav (for checking).
"""
import sys, json, pathlib, subprocess, math
import numpy as np, librosa, soundfile as sf
from scipy.ndimage import median_filter

key = sys.argv[1]
D = pathlib.Path('/home/claude/pitch/songs') / key
VOC = next(D.glob('*Vocals*.wav')); INS = next(D.glob('*Instrumental*.wav')); MIX = D / 'tuned.wav'
meta = json.load(open('/mnt/user-data/uploads/HOOK/games/stardust/songs/meta.json'))[key]
SR = 22050

print('loading', key)
voc, _ = librosa.load(str(VOC), sr=SR, mono=True)
mix, _ = librosa.load(str(MIX), sr=SR, mono=True)
dur = len(mix) / SR

# ---- beats and tempo (on the full mix) ----
tempo, beats = librosa.beat.beat_track(y=mix, sr=SR, hop_length=512, units='time', trim=False)
tempo = float(np.atleast_1d(tempo)[0])
beats = np.array(beats)
if len(beats) < 8: raise SystemExit('no beats')
beat_len = 60.0 / tempo
# fix double/half time into a singable range
while tempo > 150: tempo /= 2; beat_len = 60 / tempo; beats = beats[::2]
print(f'tempo {tempo:.1f} bpm, {len(beats)} beats, {dur:.1f} s')

# ---- key estimate (Krumhansl) ----
chroma = librosa.feature.chroma_cqt(y=mix, sr=SR)
cm = chroma.mean(axis=1)
maj = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]); mnr = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
best = (-2, 0, 'major')
for r in range(12):
    for name, prof in (('major', maj), ('minor', mnr)):
        c = np.corrcoef(np.roll(prof, r), cm)[0, 1]
        if c > best[0]: best = (c, r, name)
key_root, key_mode = best[1], best[2]
NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
print('key', NAMES[key_root], key_mode)

# ---- vocal pitch (pyin) ----
HOP = 256
f0, vflag, vprob = librosa.pyin(voc, fmin=70, fmax=1000, sr=SR, frame_length=2048, hop_length=HOP, fill_na=np.nan)
times = librosa.times_like(f0, sr=SR, hop_length=HOP)
rms = librosa.feature.rms(y=voc, frame_length=2048, hop_length=HOP)[0]
rms_db = librosa.amplitude_to_db(rms + 1e-9)
gate = rms_db > (rms_db.max() - 38)
midi = 12 * np.log2(np.where(np.isnan(f0), 1, f0) / 440) + 69
midi = np.where(np.isnan(f0) | ~gate | (vprob < 0.5), np.nan, midi)
# smooth
sm = midi.copy(); ok = ~np.isnan(sm)
sm[ok] = median_filter(sm[ok], size=7)
frame = HOP / SR

# ---- segment into notes ----
notes = []
i = 0; n = len(sm)
while i < n:
    if np.isnan(sm[i]): i += 1; continue
    j = i + 1
    while j < n and not np.isnan(sm[j]) and abs(sm[j] - sm[j-1]) < 0.7: j += 1
    seg = sm[i:j]
    if (j - i) * frame >= 0.09:
        notes.append({'t': float(times[i]), 'dur': float((j - i) * frame), 'midi': int(round(float(np.median(seg)))), 'dev': float(np.std(seg))})
    i = j
# merge adjacent same pitch with tiny gaps, drop very short
merged = []
for nt in notes:
    if merged and nt['midi'] == merged[-1]['midi'] and nt['t'] - (merged[-1]['t'] + merged[-1]['dur']) < 0.06:
        merged[-1]['dur'] = nt['t'] + nt['dur'] - merged[-1]['t']
    else: merged.append(nt)
notes = [m for m in merged if m['dur'] >= 0.12]
print('notes', len(notes))

# ---- phrase candidates on the beat grid ----
# phrase starts: notes beginning after a gap >= 0.35 s
starts = [nt['t'] for k, nt in enumerate(notes) if k == 0 or nt['t'] - (notes[k-1]['t'] + notes[k-1]['dur']) >= 0.35]
# chorus-ness: beat-synchronous chroma self similarity
bframes = librosa.time_to_frames(beats, sr=SR, hop_length=512)
cs = librosa.util.sync(chroma, bframes, aggregate=np.median)
def repeat_score(b0, nb):
    seg = cs[:, b0:b0+nb]
    if seg.shape[1] < nb: return 0
    v = seg.flatten(); v = (v - v.mean()) / (v.std() + 1e-9)
    best = []
    for s in range(0, cs.shape[1] - nb, 2):
        if abs(s - b0) < nb: continue
        w = cs[:, s:s+nb].flatten(); w = (w - w.mean()) / (w.std() + 1e-9)
        best.append(float(np.dot(v, w) / len(v)))
    best.sort(reverse=True)
    return float(np.mean(best[:3])) if best else 0

cands = []
for st in starts:
    bi = int(np.argmin(np.abs(beats - st)))
    if abs(beats[bi] - st) > beat_len * 0.6 or bi < 4: continue
    for nb in (4, 8, 12, 16):
        if bi + nb >= len(beats): continue
        t0, t1 = beats[bi], beats[bi + nb]
        L = t1 - t0
        if L < 3.2 or L > 7.5: continue
        inn = [nt for nt in notes if nt['t'] >= t0 - 0.05 and nt['t'] < t1 - 0.1]
        if len(inn) < 4 or len(inn) > 18: continue
        cov = sum(min(nt['dur'], t1 - nt['t']) for nt in inn) / L
        rng = max(nt['midi'] for nt in inn) - min(nt['midi'] for nt in inn)
        if rng < 3 or rng > 16: continue
        # vocal must end around the phrase end (not cut mid-note)
        tail_cut = any(nt['t'] < t1 and nt['t'] + nt['dur'] > t1 + 0.25 for nt in notes)
        rep = repeat_score(bi, nb)
        dens = len(inn) / L
        score = cov * 2 + min(rng, 9) / 9 + rep * 2.2 - (0.8 if tail_cut else 0) + (0.15 if nb in (8, 16) else 0) - abs(L - 5) * 0.3 + (0.2 if t0 > dur * 0.25 else 0) - (0.6 if dens < 1.1 else 0) + (0.3 if 1.4 <= dens <= 3.2 else 0)
        cands.append({'t0': float(t0), 't1': float(t1), 'beats': nb, 'bi': bi, 'score': score, 'cov': cov, 'rng': rng, 'rep': rep, 'n': len(inn), 'cut': tail_cut})
cands.sort(key=lambda c: -c['score'])
for c in cands[:6]: print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()})

def transcribe(a, b):
    try:
        from faster_whisper import WhisperModel
        global _wm
        if '_wm' not in globals(): _wm = WhisperModel('small', device='cpu', compute_type='int8')
        clip = voc[int(a * SR):int(b * SR)]
        clip16 = librosa.resample(clip, orig_sr=SR, target_sr=16000)
        segs, info = _wm.transcribe(clip16, word_timestamps=True, language=None if key == '5_sao_paulo' else 'en', beam_size=5, condition_on_previous_text=False, vad_filter=False)
        out = []
        for sg in segs:
            for w in (sg.words or []): out.append({'t': w.start + a, 'end': w.end + a, 'text': w.word.strip(), 'p': float(w.probability)})
        return out
    except Exception as e:
        print('whisper failed', e); return []
for c in cands[:6]:
    ws = transcribe(max(0, c['t0'] - 0.3), min(dur, c['t1'] + 0.5))
    ws = [w for w in ws if w['end'] > c['t0'] - 0.2 and w['t'] < c['t1'] + 0.2]
    c['words'] = ws; nw = len([w for w in ws if w['p'] > 0.3]); mp = float(np.mean([w['p'] for w in ws])) if ws else 0
    L = c['t1'] - c['t0']
    import re
    tt = [w for w in re.findall(r"[a-z']+", meta['title'].lower()) if len(w) >= 3 and w not in ('the','and','you','your')]
    ct = ' '.join(w['text'].lower() for w in ws)
    hit = sum(1 for w in tt if w in ct); title_bonus = min(1.3, hit * 0.55) if tt else 0
    c['score2'] = c['score'] + min(nw, 6) * 0.12 - (1.0 if nw < 3 else 0) + mp * 1.2 - (max(0, L - 5.5) * 0.5) - (0.6 if c['rng'] < 5 else 0) + title_bonus
    print(round(c['t0'], 2), c['beats'], 'words:', ' '.join(w['text'] for w in ws), '| p', round(mp, 2))
cands[:6] = sorted(cands[:6], key=lambda c: -c['score2'])
best = cands[0]
t0, t1, nb, bi = best['t0'], best['t1'], best['beats'], best['bi']
pre_bi = bi - 4  # one bar count-in from the real track
pre = float(beats[pre_bi])
tail = min(beat_len * 2, 1.2)
take = max(5.0, (t1 - t0) + tail)
end = t0 + take
phrase_notes = []
for nt in notes:
    if nt['t'] >= t0 - 0.05 and nt['t'] < t1 - 0.1:
        d = min(nt['dur'], t1 - nt['t'])
        phrase_notes.append({'t': round(nt['t'] - t0, 3), 'dur': round(d, 3), 'midi': nt['midi']})

# ---- lyrics (from the candidate pass) ----
words = [{'t': round(max(0, w['t'] - t0), 3), 'end': round(w['end'] - t0, 3), 'text': w['text'], 'p': round(w['p'], 2)} for w in best.get('words', [])]
print('words:', ' '.join(w['text'] for w in words))

# snap word onsets to the nearest detected note onset (pitch tracking is tighter than Whisper's timing)
onsets = [nt['t'] for nt in phrase_notes]
for w in words:
    if not onsets: break
    j = int(np.argmin([abs(o - w['t']) for o in onsets]))
    if abs(onsets[j] - w['t']) <= 0.22:
        shift = onsets[j] - w['t']; w['t'] = round(onsets[j], 3); w['end'] = round(max(w['t'] + 0.12, w['end'] + shift * 0.5), 3)
# one word per note: the word whose (snapped) onset is nearest and not later than the note's midpoint; melisma notes stay blank
used = set()
for nt in phrase_notes:
    bestw, bd = None, 9
    for wi, w in enumerate(words):
        if wi in used: continue
        d = abs(w['t'] - nt['t'])
        if d < bd and w['t'] <= nt['t'] + nt['dur'] * 0.5 + 0.05: bd, bestw = d, wi
    if bestw is not None and bd <= 0.3: nt['word'] = words[bestw]['text']; used.add(bestw)
    else: nt['word'] = ''

# ---- render clips ----
def render(src, out):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{pre:.3f}', '-t', f'{end - pre:.3f}', '-i', str(src), '-ac', '2', '-ar', '44100', '-af', f'afade=t=in:st=0:d=0.05,afade=t=out:st={end - pre - 0.35:.3f}:d=0.35', '-codec:a', 'libmp3lame', '-b:a', '160k', str(out)], check=True)
render(MIX, D / 'listen.mp3'); render(INS, D / 'sing.mp3')
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t0:.3f}', '-t', f'{t1 - t0:.3f}', '-i', str(VOC), '-ac', '1', '-ar', '22050', str(D / 'vocals_phrase.wav')], check=True)

out = {
    'key': key, 'title': meta['title'], 'artist': meta['artist'], 'album': meta['album'], 'year': meta['year'], 'isrc': meta['isrc'],
    'bpm': round(tempo, 2), 'beat': round(beat_len, 4), 'songKey': NAMES[key_root] + ' ' + key_mode, 'keyRoot': key_root,
    'phraseStart': round(t0, 3), 'phraseEnd': round(t1, 3), 'bars': nb // 4, 'preroll': round(t0 - pre, 3), 'take': round(take, 3),
    'clipStart': round(pre, 3), 'clipDur': round(end - pre, 3),
    'beatsInClip': [round(float(b - pre), 3) for b in beats[pre_bi: bi + nb + 3]],
    'notes': phrase_notes, 'words': words, 'candidates': [{k: v for k, v in c.items() if k != 'words'} for c in cands[:5]],
}
json.dump(out, open(D / 'phrase.json', 'w'), indent=1, ensure_ascii=False)
print('phrase', round(t0, 2), '->', round(t1, 2), f'({nb} beats, {t1 - t0:.2f} s), take {take:.2f} s, notes {len(phrase_notes)}')
print(' '.join(f"{NAMES[n['midi']%12]}{n['midi']//12-1}:{n['word']}" for n in phrase_notes))
