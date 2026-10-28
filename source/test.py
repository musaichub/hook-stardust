"""Headless playthrough of all four STARDUST games (touch mode), plus one mic-mode run of Rocket Fuel with Chromium's fake mic."""
import asyncio, pathlib, sys, time
from playwright.async_api import async_playwright

HTML = pathlib.Path('/home/claude/pitch/out/HOOK-Stardust.html').resolve().as_uri()
SHOT = pathlib.Path('/home/claude/pitch/shots'); SHOT.mkdir(exist_ok=True)

async def ev(pg, js): return await pg.evaluate(js)
async def phase(pg): return await ev(pg, '__stardust.S.phase')
async def wait_phase(pg, ph, timeout=40):
    t = time.time()
    while time.time() - t < timeout:
        if await phase(pg) == ph: return
        await pg.wait_for_timeout(50)
    raise RuntimeError(f'phase {ph} not reached (now {await phase(pg)})')
async def y_of(pg, midi): return await ev(pg, f'__stardust.midiToY({midi})')

async def drive_rocketfuel(pg, r, shots):
    await wait_phase(pg, 'listen'); await pg.wait_for_timeout(2000); await pg.screenshot(path=SHOT/f'rf-r{r}-listen.png')
    await wait_phase(pg, 'countin'); await wait_phase(pg, 'sing')
    notes = await ev(pg, '__stardust.S.notes.map(n=>({t0:n.t0,dur:n.dur,midi:n.midi}))')
    await pg.mouse.move(640, await y_of(pg, notes[0]['midi'])); await pg.mouse.down(); shot = False
    for i, n in enumerate(notes):
        el = await ev(pg, '__stardust.S.ac.currentTime-__stardust.S.t0'); w = (n['t0'] - el) * 1000
        if w > 0: await pg.wait_for_timeout(w)
        await pg.mouse.move(640, await y_of(pg, n['midi']))
        if not shot and i == min(3, len(notes) - 1): await pg.screenshot(path=SHOT/f'rf-r{r}-sing.png'); shot = True
    await pg.wait_for_timeout(900); await pg.mouse.up()

async def drive_moonshot(pg, r, shots):
    await wait_phase(pg, 'play'); shot = False; last = -1
    while await phase(pg) == 'play':
        st = await ev(pg, '__stardust.G.stage'); i = await ev(pg, '__stardust.G.i')
        if st == 'hold':
            midi = await ev(pg, '__stardust.G.targets[__stardust.G.i].midi')
            await pg.mouse.move(640, await y_of(pg, midi)); await pg.mouse.down()
            if not shot and i >= 1: await pg.wait_for_timeout(900); await pg.screenshot(path=SHOT/f'ms-r{r}-hold.png'); shot = True
            while await ev(pg, '__stardust.G.stage') == 'hold': await pg.wait_for_timeout(60)
            await pg.mouse.up()
        await pg.wait_for_timeout(80)

async def drive_echo(pg, r, shots):
    await wait_phase(pg, 'play'); shot = False
    while await phase(pg) == 'play':
        st = await ev(pg, '__stardust.G.stage')
        if st == 'call' and not shot:
            await pg.wait_for_timeout(600); await pg.screenshot(path=SHOT/f'echo-r{r}-call.png'); shot = True
        if st == 'reply':
            k = await ev(pg, '__stardust.G.k'); notes = await ev(pg, '__stardust.S.notes.map(n=>n.midi)')
            await pg.wait_for_timeout(250)
            for i in range(k):
                await pg.mouse.move(640, await y_of(pg, notes[i])); await pg.mouse.down(); await pg.wait_for_timeout(320)
                if i == 1 and r == 0: await pg.screenshot(path=SHOT/f'echo-r{r}-reply.png')
                await pg.mouse.up(); await pg.wait_for_timeout(160)
            while await ev(pg, '__stardust.G.stage') == 'reply': await pg.wait_for_timeout(60)
        await pg.wait_for_timeout(80)

async def drive_jetpack(pg, r, shots):
    await wait_phase(pg, 'play'); shot = False
    while await phase(pg) == 'play':
        st = await ev(pg, '__stardust.G.stage')
        if st == 'climb' and not await ev(pg, '!!__stardust.G.jump'):
            li = await ev(pg, '__stardust.G.li'); midi = await ev(pg, '__stardust.G.plats[__stardust.G.ladder[__stardust.G.li]].midi')
            await pg.mouse.move(640, await y_of(pg, midi)); await pg.mouse.down()
            if not shot and li >= 2: await pg.wait_for_timeout(150); await pg.screenshot(path=SHOT/f'jp-r{r}-climb.png'); shot = True
            t = time.time()
            while await ev(pg, '__stardust.G.li') == li and time.time() - t < 8: await pg.wait_for_timeout(50)
            await pg.mouse.up()
        await pg.wait_for_timeout(60)

DRIVERS = {'rocketfuel': drive_rocketfuel, 'moonshot': drive_moonshot, 'echo': drive_echo, 'jetpack': drive_jetpack}

async def play(pg, key, mode='touch'):
    await pg.click('#btn-home') if await pg.is_visible('#btn-home') else None
    idx = ['rocketfuel', 'moonshot', 'echo', 'jetpack'].index(key)
    await pg.click(f'.game >> nth={idx}'); await pg.wait_for_timeout(300)
    await pg.screenshot(path=SHOT/f'{key}-pick.png')
    if mode == 'touch': await pg.click('#btn-touch')
    else:
        await pg.click('#btn-mic'); await pg.wait_for_timeout(2500)
        if await pg.is_visible('#btn-start'): await pg.click('#btn-start')
        else: await pg.click('#btn-skipcal')
    for r in range(3):
        await wait_phase(pg, 'intro'); await pg.wait_for_function('!document.getElementById("btn-go").disabled', timeout=20000); await pg.wait_for_timeout(200)
        if r == 0: await pg.screenshot(path=SHOT/f'{key}-intro.png')
        await pg.click('#btn-go')
        if mode == 'touch': await DRIVERS[key](pg, r, True)
        await wait_phase(pg, 'result', 90); await pg.wait_for_timeout(800)
        if r == 0: await pg.screenshot(path=SHOT/f'{key}-result.png')
        print(' ', key, 'round', r, (await pg.text_content('#res-eyebrow')).strip(), '|', (await pg.text_content('#res-lead')).strip())
        await pg.click('#btn-next'); await pg.wait_for_timeout(300)
    if mode == 'mic':
        await wait_phase(pg, 'final', 60)
    else:
        await wait_phase(pg, 'final', 10)
    await pg.wait_for_timeout(400); await pg.screenshot(path=SHOT/f'{key}-final-{mode}.png')
    print(' ', key, 'final:', (await pg.text_content('#final-rank')).strip(), '|', (await pg.text_content('#st-audio')).strip(), '|', (await pg.text_content('#st-score')).strip())
    await pg.click('#btn-again'); await pg.wait_for_timeout(300)

async def main(which):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required','--use-gl=swiftshader'])
        ctx = await b.new_context(viewport={'width':1280,'height':800}, permissions=['microphone'])
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e))); pg.on('console', lambda m: errs.append('console:' + m.text) if m.type == 'error' else None)
        await pg.goto(HTML); await pg.wait_for_timeout(1000); await pg.screenshot(path=SHOT/'home.png')
        keys = ['rocketfuel', 'moonshot', 'echo', 'jetpack'] if which == 'all' else [which]
        for k in keys:
            await play(pg, k, 'touch')
        if which in ('all', 'mic'):
            await play(pg, 'moonshot', 'mic')
        await pg.set_viewport_size({'width': 390, 'height': 780}); await pg.wait_for_timeout(300); await pg.screenshot(path=SHOT/'home-phone.png', full_page=False)
        print('errors:', errs[:10])
        await b.close()

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'all'))
