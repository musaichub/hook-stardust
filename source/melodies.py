"""Original, deterministic synthesis of public-domain singing exercises.

No downloaded recordings, sample libraries, commercial stems or modern arrangements
are inputs to this module. Timing is in seconds from the first sung note. The old
listen/sing/vocal properties remain aliases for the game's audio-buffer interface.
"""
from array import array
import base64
import html
import io
import math
import sys
import wave

SAMPLE_RATE = 16000
PALETTE = ('#FFBB33', '#B4D9F3', '#B5FF8D', '#E7BCFF', '#FFC3FC')

# Semitone offsets from root; durations in quarter-note beats. Each word is a
# singable syllable; a trailing hyphen keeps multi-syllable words legible.
MELODIES = (
    dict(key='twinkle', title='Twinkle, Twinkle, Little Star', short='TWINKLE',
         bpm=80, root=55, year='Traditional',
         source='https://en.wikisource.org/wiki/The_Child%27s_Own_Music_Book/Twinkle,_Twinkle,_Little_Star',
         pitch=[0,0,7,7,9,9,7,5,5,4,4,2,2,0],
         beats=[1,1,1,1,1,1,2,1,1,1,1,1,1,2],
         lyrics='Twin- kle twin- kle lit- tle star How I won- der what you are'),
    dict(key='frere_jacques', title='Frère Jacques', short='FRÈRE JACQUES',
         bpm=128, root=55, year='Traditional',
         source='https://gallica.bnf.fr/ark:/12148/btv1b10023704r/f106.item',
         pitch=[0,2,4,0,0,2,4,0,4,5,7,4,5,7,7,9,7,5,4,0,7,9,7,5,4,0,0,-5,0,0,-5,0],
         beats=[1,1,1,1,1,1,1,1,1,1,2,1,1,2,.5,.5,.5,.5,1,1,.5,.5,.5,.5,1,1,1,1,2,1,1,2],
         lyrics='Frè- re Jac- ques Frè- re Jac- ques Dor- mez vous Dor- mez vous Son- nez les ma- ti- nes Son- nez les ma- ti- nes Ding ding dong Ding ding dong'),
    dict(key='mary_lamb', title='Mary Had a Little Lamb', short='MARY’S LAMB',
         bpm=128, root=55, year='Traditional',
         source='https://en.wikisource.org/wiki/The_Child%27s_Own_Music_Book/Mary_Had_a_Little_Lamb',
         pitch=[4,2,0,2,4,4,4,2,2,2,4,7,7,4,2,0,2,4,4,4,4,2,2,4,2,0],
         beats=[1,1,1,1,1,1,2,1,1,2,1,1,2,1,1,1,1,1,1,1,1,1,1,1,1,4],
         lyrics='Ma- ry had a lit- tle lamb Lit- tle lamb Lit- tle lamb Ma- ry had a lit- tle lamb Its fleece was white as snow'),
    dict(key='row_your_boat', title='Row, Row, Row Your Boat', short='ROW YOUR BOAT',
         bpm=112, root=53, year='Traditional',
         source='https://www.millersvillearchives.com/exhibits/show/principals-and-presidents-at-m/eliphalet-oram-lyte--principal',
         pitch=[0,0,0,2,4,4,2,4,5,7,12,12,12,7,7,7,4,4,4,0,0,0,7,5,4,2,0],
         beats=[1.5,1.5,1,.5,1.5,1,.5,1,.5,3,.5,.5,.5,.5,.5,.5,.5,.5,.5,.5,.5,.5,1,.5,1,.5,3],
         lyrics='Row row row your boat Gent- ly down the stream Mer- ri- ly mer- ri- ly mer- ri- ly mer- ri- ly Life is but a dream'),
    dict(key='london_bridge', title='London Bridge', short='LONDON BRIDGE',
         bpm=128, root=55, year='Traditional',
         source='https://en.wikisource.org/wiki/Page:Childs_own_music_book.djvu/96',
         pitch=[7,9,7,5,4,5,7,2,4,5,4,5,7,7,9,7,5,4,5,7,2,7,4,0],
         beats=[1.5,.5,1,1,1,1,2,1,1,2,1,1,2,1.5,.5,1,1,1,1,2,2,2,1,3],
         lyrics='Lon- don Bridge is fall- ing down Fall- ing down fall- ing down Lon- don Bridge is fall- ing down My fair la- dy'),
)


def data_uri(mime, contents):
    return 'data:' + mime + ';base64,' + base64.b64encode(contents).decode('ascii')


def tone(samples, start, duration, frequency, amplitude=.2):
    """A soft, dry additive tone with short fades; no reverb or sampled timbre."""
    first = round(start * SAMPLE_RATE)
    count = round(duration * SAMPLE_RATE)
    attack, release = .012, .045
    for i in range(min(count, len(samples) - first)):
        t = i / SAMPLE_RATE
        envelope = min(1.0, t / attack, (duration - t) / release)
        phase = 2 * math.pi * frequency * t
        value = (math.sin(phase) + .18 * math.sin(2 * phase) + .06 * math.sin(3 * phase)) / 1.24
        samples[first + i] += amplitude * max(0, envelope) * value


def wav_uri(samples):
    pcm = array('h', (round(max(-1.0, min(1.0, v)) * 32767) for v in samples))
    if sys.byteorder != 'little':
        pcm.byteswap()
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm.tobytes())
    return data_uri('audio/wav', out.getvalue())


def artwork(spec, number):
    """New HOOK-colour constellation artwork, generated from the note contour."""
    colour = PALETTE[number]
    pitches = spec['pitch']
    lo, hi = min(pitches), max(pitches)
    points = [(46 + i * 268 / (len(pitches) - 1), 232 - (p - lo) * 132 / max(1, hi - lo))
              for i, p in enumerate(pitches)]
    path = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    nodes = ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{6 if i % 3 else 10}" fill="{colour}" stroke="#181818" stroke-width="3"/>'
                    for i, (x, y) in enumerate(points))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 360">
<rect width="360" height="360" fill="#181818"/>
<circle cx="181" cy="175" r="122" fill="none" stroke="{colour}" stroke-opacity=".2" stroke-width="2"/>
<ellipse cx="181" cy="175" rx="165" ry="75" fill="none" stroke="{colour}" stroke-opacity=".2" stroke-width="2" transform="rotate(-28 181 175)"/>
<text x="26" y="39" fill="{colour}" font-family="sans-serif" font-size="12" font-weight="700" letter-spacing="3">MELODY / 0{number + 1}</text>
<polyline points="{path}" fill="none" stroke="{colour}" stroke-width="3"/>{nodes}
<path d="M28 285 H332" stroke="{colour}" stroke-width="2"/>
<text x="26" y="317" fill="#F7F5EF" font-family="sans-serif" font-size="18" font-weight="800">{html.escape(spec['short'])}</text>
<text x="26" y="339" fill="{colour}" font-family="sans-serif" font-size="10" letter-spacing="2">A MELODY EVERYONE KNOWS</text></svg>'''
    return data_uri('image/svg+xml', svg.encode())


def make_library(include_audio=False):
    songs = {}
    for index, spec in enumerate(MELODIES):
        syllables = spec['lyrics'].split()
        assert len(spec['pitch']) == len(spec['beats']) == len(syllables), spec['key']
        beat = 60 / spec['bpm']
        preroll = 4 * beat
        elapsed = 0
        notes, words = [], []
        for pitch, length, word in zip(spec['pitch'], spec['beats'], syllables):
            duration = length * beat
            notes.append(dict(t=round(elapsed, 6), dur=round(duration * .92, 6),
                              midi=spec['root'] + pitch, word=word))
            words.append(dict(t=round(elapsed, 6), end=round(elapsed + duration, 6), text=word, p=1))
            elapsed += duration
        take = round(elapsed + .35, 6)
        clip_duration = round(preroll + take, 6)
        songs[spec['key']] = dict(
            title=spec['title'], artist='Traditional', album='Public-domain melody', year=spec['year'],
            isrc='', bpm=spec['bpm'], beat=round(beat, 6), songKey='F major' if spec['root'] == 53 else 'G major',
            keyRoot=spec['root'] % 12, phraseStart=0, phraseEnd=round(elapsed, 6),
            bars=sum(spec['beats']) / 4, preroll=round(preroll, 6), take=take,
            clipStart=0, clipDur=clip_duration,
            beatsInClip=[round(i * beat, 6) for i in range(math.ceil(clip_duration / beat))],
            notes=notes, words=words, art=artwork(spec, index),
            sourceType='public-domain-synthesis', provenance=spec['source'],
            captureHint='Sing naturally, in a comfortable octave. Headphones keep the guide out of your recording.',
            guideLabel='Original synthesized melody guide', captureBacking='silent',
        )
        if include_audio:
            guide = array('f', [0]) * math.ceil(take * SAMPLE_RATE)
            for note in notes:
                tone(guide, note['t'], note['dur'], 440 * 2 ** ((note['midi'] - 69) / 12))
            listen = array('f', [0]) * math.ceil(clip_duration * SAMPLE_RATE)
            capture = array('f', [0]) * len(listen)
            for count in range(4):
                for audio in (listen, capture):
                    tone(audio, count * beat, .045, 880 if count == 0 else 660, .13)
            offset = round(preroll * SAMPLE_RATE)
            for i, sample in enumerate(guide):
                if offset + i < len(listen):
                    listen[offset + i] += sample
            songs[spec['key']].update(listen=wav_uri(listen), sing=wav_uri(capture), vocal=wav_uri(guide))
    return songs
