#!/usr/bin/env python3
"""Build the current Stardust app with local branding and original melody guides.

Run from any directory: python3 /path/to/HOOK/games/stardust/source/build.py
No network, commercial recordings, third-party Python packages or audio tools are
required. The legacy songs folders are intentionally outside this build's inputs.
"""
import base64
import json
from pathlib import Path
import re
from melodies import make_library

SOURCE = Path(__file__).resolve().parent
OUT = SOURCE.parent
BRAND = OUT.parents[1] / 'brand' / 'assets'


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode('ascii')


def svg_uri(path):
    return 'data:image/svg+xml;base64,' + b64(path)


def build():
    songs = make_library()
    body = (SOURCE / 'app.html').read_text(encoding='utf-8')
    replacements = {
        '{{SONGS_JSON}}': json.dumps(songs, ensure_ascii=False, separators=(',', ':')),
        '{{MARUND700}}': b64(BRAND / 'fonts' / '26A1Marund-7000Sharp.otf'),
        '{{MARUND500}}': b64(BRAND / 'fonts' / '26A1Marund-5000Sharp.otf'),
        '{{HOOK_SVG}}': svg_uri(BRAND / 'logos' / 'hook-wordmark-pink-sticker.svg'),
        '{{HOOK_SVG_WHITE}}': svg_uri(BRAND / 'logos' / 'hook-wordmark-white-sticker.svg'),
        '{{VS_BLACK}}': 'data:image/png;base64,' + b64(OUT / 'voiceswap-black.png'),
        '{{VS_WHITE}}': 'data:image/png;base64,' + b64(OUT / 'voiceswap-white.png'),
        '{{LK_stardust_PINK}}': svg_uri(OUT / 'brand' / 'stardust-lockup-on-pink.svg'),
        '{{LK_rocketfuel_INK}}': svg_uri(OUT / 'brand' / 'rocketfuel-lockup-on-ink.svg'),
        '{{LOGOS_JSON}}': json.dumps({name: {
            'ink': svg_uri(OUT / 'brand' / f'{name}-lockup-on-ink.svg'),
            'pink': svg_uri(OUT / 'brand' / f'{name}-lockup-on-pink.svg')
        } for name in ['stardust', 'rocketfuel', 'moonshot', 'echo', 'jetpack']}),
    }
    if '{{MELODY_AUDIO_JS}}' in body:
        replacements['{{MELODY_AUDIO_JS}}'] = (SOURCE / 'melody-audio.js').read_text(encoding='utf-8')
    if '{{CAPTURE_JS}}' in body:
        replacements['{{CAPTURE_JS}}'] = (SOURCE / 'capture.js').read_text(encoding='utf-8')
    for token, value in replacements.items():
        if token not in body:
            raise ValueError(f'Missing expected app placeholder: {token}')
        body = body.replace(token, value)
    if re.search(r'\{\{[A-Za-z_][A-Za-z0-9_]*\}\}', body):
        raise ValueError('Unexpanded placeholder remains in app')
    standalone = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                  '<title>HOOK Stardust</title>'
                  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                  '<meta name="theme-color" content="#181818">'
                  '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
                  '</head><body>' + body + '</body></html>')
    # Both entry points are valid documents when served directly by the local app.
    for filename in ('index.html', 'HOOK-Stardust.html'):
        (OUT / filename).write_text(standalone, encoding='utf-8')
    print('Melodies:', ', '.join(f"{s['title']} ({s['phraseEnd']:.1f}s)" for s in songs.values()))
    print(f'Built {OUT / "index.html"} and HOOK-Stardust.html ({len(standalone.encode()) // 1024} KB each)')


if __name__ == '__main__':
    build()
