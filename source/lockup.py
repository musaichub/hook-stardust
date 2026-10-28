#!/usr/bin/env python3
"""Lockups in the HOOK sticker language: Marund letters as paths, bone sticker border, black outline, hard offset
shadow, plus a motif per mark. STARDUST (the collection) and the four games: ROCKET FUEL, MOONSHOT, ECHO, JETPACK.
Each mark gets an on-ink variant (coloured letters), an on-pink variant (ink letters) and previews."""
import pathlib, math
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

FONT = '/mnt/user-data/uploads/HOOK/brand/assets/fonts/26A1Marund-7000Sharp.otf'
OUT = pathlib.Path('/home/claude/pitch/out/brand'); OUT.mkdir(parents=True, exist_ok=True)
f = TTFont(FONT); gs = f.getGlyphSet(); cmap = f.getBestCmap(); upm = f['head'].unitsPerEm
hmtx = f['hmtx']; kern = {}
try:
    for t in f['GPOS'].table.LookupList.Lookup:
        for st in t.SubTable:
            if st.LookupType == 2 and st.Format == 1:
                for i, pairs in enumerate(st.PairSet):
                    g1 = st.Coverage.glyphs[i]
                    for pr in pairs.PairValueRecord:
                        kern[(g1, pr.SecondGlyph)] = pr.Value1.XAdvance if pr.Value1 else 0
except Exception: pass

BONE, INK, PINK, AMBER, SKY, LIME, LILAC, BLUE, RED, BLUSH = '#F7F5EF', '#181818', '#FF6CF7', '#FFBB33', '#B4D9F3', '#B5FF8D', '#E7BCFF', '#6C92FF', '#ED3B17', '#FFC3FC'

def word_path(text, size, tracking=-0.01):
    scale = size / upm; x = 0; d = []; prev = None
    for ch in text:
        g = cmap[ord(ch)]
        if prev: x += kern.get((prev, g), 0) * scale
        pen = SVGPathPen(gs); tp = TransformPen(pen, (scale, 0, 0, -scale, x, 0)); gs[g].draw(tp)
        d.append(pen.getCommands()); x += hmtx[g][0] * scale + tracking * size; prev = g
    return ' '.join(d), x

def sparkle(cx, cy, r, fill, sw=7):
    k = r * 0.28
    pts = [(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)]
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts) + ' Z'
    return f'<path d="{d}" fill="#000" transform="translate(5,5)"/><path d="{d}" fill="{fill}" stroke="#000" stroke-width="{sw}" stroke-linejoin="round"/>'
def dust(cx, cy, r, fill):
    return f'<circle cx="{cx+4}" cy="{cy+4}" r="{r+2}" fill="#000"/><circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="#000" stroke-width="5"/>'
def sticker_path(d, fill, transform=''):
    """A closed path drawn as a sticker: shadow, black outline, bone border, fill."""
    t = f' transform="{transform}"' if transform else ''
    return (f'<g{t}><path d="{d}" transform="translate(6,6)" fill="#000" stroke="#000" stroke-width="14" stroke-linejoin="round"/>'
            f'<path d="{d}" fill="#000" stroke="#000" stroke-width="14" stroke-linejoin="round"/>'
            f'<path d="{d}" fill="{BONE}" stroke="{BONE}" stroke-width="5" stroke-linejoin="round"/>'
            f'<path d="{d}" fill="{fill}"/></g>')
def rocket(x, y, s, rot=-35):
    """Small sticker rocket pointing right at scale s (unit length ~76)."""
    body = 'M38,0 Q24,-16 -12,-16 L-30,-16 L-30,16 L-12,16 Q24,16 38,0 Z'
    fins = 'M-16,-14 L-34,-30 L-30,-10 Z M-16,14 L-34,30 L-30,10 Z'
    nose = 'M38,0 Q28,-12 14,-14.5 L14,14.5 Q28,12 38,0 Z'
    flame = 'M-31,-8 L-72,0 L-31,8 Z'
    tr = f'translate({x},{y}) rotate({rot}) scale({s})'
    g = f'<g transform="{tr}">'
    g += f'<path d="{flame}" fill="{AMBER}" stroke="#000" stroke-width="4" stroke-linejoin="round"/><path d="M-31,-4 L-56,0 L-31,4 Z" fill="{RED}"/>'
    g += f'<g transform="translate(4,4)"><path d="{fins}" fill="#000"/><path d="{body}" fill="#000"/></g>'
    g += f'<path d="{fins}" fill="{PINK}" stroke="#000" stroke-width="3" stroke-linejoin="round"/>'
    g += f'<path d="{body}" fill="{BONE}" stroke="#000" stroke-width="3" stroke-linejoin="round"/>'
    g += f'<path d="{nose}" fill="{PINK}" stroke="#000" stroke-width="3" stroke-linejoin="round"/>'
    g += f'<circle cx="2" cy="0" r="8" fill="#000"/><circle cx="2" cy="0" r="5.5" fill="{SKY}"/><rect x="-14" y="-16" width="3" height="32" fill="#000"/></g>'
    return g

def make(name, text, letter_fill, size=160, motif=None, pad_left=120, pad_right=110, top=90, bottom=0):
    path, width = word_path(text, size)
    bottom += 48 + width * 0.035  # room for the 4 degree tilt and the hard shadow at the left end
    W = int(pad_left + width + pad_right); H = int(top + size * 1.2 + bottom)
    ox, oy = pad_left, top + size * 0.95
    def svg(fill, ground=None):
        g = f'<rect width="100%" height="100%" fill="{ground}"/>' if ground else ''
        word = f'<g transform="translate({ox},{oy}) rotate(-4 {width/2} -{size*0.35})">'
        word += f'<path d="{path}" transform="translate(12,12)" fill="#000" stroke="#000" stroke-width="30" stroke-linejoin="round"/>'
        word += f'<path d="{path}" fill="#000" stroke="#000" stroke-width="30" stroke-linejoin="round"/>'
        word += f'<path d="{path}" fill="{BONE}" stroke="{BONE}" stroke-width="16" stroke-linejoin="round"/>'
        word += f'<path d="{path}" fill="{fill}"/></g>'
        deco = motif(ox, oy, width, size, fill) if motif else ''
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"><title>{text} by HOOK</title>{g}{word}{deco}</svg>')
    (OUT / f'{name}-lockup-on-ink.svg').write_text(svg(letter_fill))
    (OUT / f'{name}-lockup-on-pink.svg').write_text(svg(INK))
    (OUT / f'{name}-lockup-preview-ink.svg').write_text(svg(letter_fill, INK))
    (OUT / f'{name}-lockup-preview-pink.svg').write_text(svg(INK, PINK))
    print(name, W, H)

# ---- motifs ----
def m_stardust(ox, oy, w, s, fill):
    return (sparkle(ox + w - 6, oy - s, 36, AMBER) + sparkle(ox - 6, oy + 34, 17, AMBER) + sparkle(ox + w * 0.56, oy - s * 1.12, 11, LIME)
            + dust(ox - 44, oy - 14, 10, SKY) + dust(ox - 70, oy + 4, 7, LIME) + dust(ox - 90, oy + 26, 5, BONE) + dust(ox - 104, oy + 50, 3.5, AMBER))
def m_rocket(ox, oy, w, s, fill):
    # a rocket blasting off from the K, flame trail of dust behind it
    d = ''.join(dust(ox - 36 - i * 24, oy + 10 + i * 6, 9 - i * 1.6, [AMBER, RED, AMBER, BONE][i]) for i in range(4))
    return rocket(ox + w + 16, oy - s * 1.0, 1.1, -36) + d + sparkle(ox - 10, oy - s * 1.05, 14, AMBER)
def m_moon(ox, oy, w, s, fill):
    # crescent moon sticker over the end of the word, dotted trajectory and a tiny rocket
    cx, cy, r = ox + w + 24, oy - s * 1.0, 46
    crescent = f'M{cx-r},{cy} a{r},{r} 0 1,0 {2*r},0 a{r},{r} 0 1,0 {-2*r},0 Z M{cx-r*0.82+r*0.5},{cy} a{r*0.82},{r*0.82} 0 1,0 {2*r*0.82},0 a{r*0.82},{r*0.82} 0 1,0 {-2*r*0.82},0 Z'
    moon = sticker_path(crescent, SKY).replace('<path d=', '<path fill-rule="evenodd" d=')
    crat = f'<circle cx="{cx-14}" cy="{cy-10}" r="6" fill="rgba(0,0,0,.18)"/><circle cx="{cx-6}" cy="{cy+16}" r="4" fill="rgba(0,0,0,.18)"/>'
    traj = f'<path d="M{ox-60},{oy+30} Q{ox-10},{oy-s*1.4} {cx-60},{cy+10}" fill="none" stroke="#000" stroke-width="9" stroke-linecap="round" stroke-dasharray="1 22"/><path d="M{ox-60},{oy+30} Q{ox-10},{oy-s*1.4} {cx-60},{cy+10}" fill="none" stroke="{BONE}" stroke-width="5" stroke-linecap="round" stroke-dasharray="1 22"/>'
    return traj + moon + crat + rocket(ox - 70, oy + 26, 0.62, -60) + sparkle(ox + w * 0.3, oy - s * 1.15, 10, AMBER)
def m_echo(ox, oy, w, s, fill):
    # echo rings fading off the last letter, and a star that "called"
    cx, cy = ox + w + 8, oy - s * 0.45
    rings = ''
    for i, (rr, col, sw) in enumerate([(40, LILAC, 9), (74, BLUE, 8), (108, SKY, 7)]):
        a0, a1 = -62, 62
        x0, y0 = cx + rr * math.cos(math.radians(a0)), cy + rr * math.sin(math.radians(a0))
        x1, y1 = cx + rr * math.cos(math.radians(a1)), cy + rr * math.sin(math.radians(a1))
        d = f'M{x0:.1f},{y0:.1f} A{rr},{rr} 0 0,1 {x1:.1f},{y1:.1f}'
        rings += f'<path d="{d}" transform="translate(5,5)" fill="none" stroke="#000" stroke-width="{sw+8}" stroke-linecap="round"/><path d="{d}" fill="none" stroke="#000" stroke-width="{sw+8}" stroke-linecap="round"/><path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linecap="round"/>'
    return rings + sparkle(ox - 16, oy - s * 1.0, 22, AMBER) + sparkle(ox - 44, oy - s * 0.5, 11, LILAC) + dust(ox - 60, oy + 10, 6, SKY)
def m_jetpack(ox, oy, w, s, fill):
    # twin jet flames under the word and lift lines rising past it
    def flame(x, y, sc):
        d = f'M{x-18*sc},{y} Q{x},{y+10*sc} {x+18*sc},{y} L{x+8*sc},{y+48*sc} L{x},{y+70*sc} L{x-8*sc},{y+48*sc} Z'
        return (f'<path d="{d}" transform="translate(5,5)" fill="#000" stroke="#000" stroke-width="12" stroke-linejoin="round"/>'
                f'<path d="{d}" fill="{AMBER}" stroke="#000" stroke-width="5" stroke-linejoin="round"/>'
                f'<path d="M{x-8*sc},{y+4*sc} L{x+8*sc},{y+4*sc} L{x},{y+40*sc} Z" fill="{RED}"/>')
    lines = ''
    for i, (lx, ly, ln) in enumerate([(ox - 46, oy - 20, 60), (ox - 70, oy + 10, 90), (ox + w + 40, oy - 30, 70), (ox + w + 64, oy + 6, 50)]):
        lines += f'<path d="M{lx},{ly} L{lx},{ly+ln}" stroke="#000" stroke-width="12" stroke-linecap="round"/><path d="M{lx},{ly} L{lx},{ly+ln}" stroke="{LIME if i%2 else SKY}" stroke-width="6" stroke-linecap="round"/>'
    return lines + flame(ox + w * 0.33, oy + 10, 1) + flame(ox + w * 0.62, oy + 14, 0.8) + sparkle(ox + w + 14, oy - s * 1.02, 24, AMBER)

make('stardust', 'STARDUST', PINK, motif=m_stardust, pad_right=95)
make('rocketfuel', 'ROCKET FUEL', AMBER, size=140, motif=m_rocket, pad_right=175, top=120)
make('moonshot', 'MOONSHOT', SKY, size=150, motif=m_moon, pad_right=190, top=110, bottom=10)
make('echo', 'ECHO', LILAC, size=170, motif=m_echo, pad_right=170, top=100)
make('jetpack', 'JETPACK', LIME, size=150, motif=m_jetpack, pad_right=140, top=100, bottom=80)
