# Stardust melody library

The current game build uses five traditional melodies and newly synthesized guide sounds. `source/melodies.py` contains the note sequences, syllables, timing, artwork generation and an optional offline audio renderer. `source/melody-audio.js` synthesizes the playback guides in the browser. It does not read `songs/`, any commercial master, isolated vocal, stem, sample library, downloaded MIDI or modern arrangement. The previous assets remain on disk for historical work but are excluded from this build.

## Composition sources

These are the underlying traditional melodies, with a short phrase or verse transposed for singing practice. The documents below establish the historical repertoire; their recordings, accompaniment arrangements and scanned artwork are not bundled in the game.

| Melody | Historical evidence | This exercise |
| --- | --- | --- |
| Twinkle, Twinkle, Little Star | The melody and words appear in [The Child's Own Music Book, p. 116](https://en.wikisource.org/wiki/The_Child%27s_Own_Music_Book/Twinkle,_Twinkle,_Little_Star), a 1918 collection. The [Library of Congress also catalogs an 1879 score](https://www.loc.gov/item/2023832590/). | Opening two lines, 12 seconds, G3–E4. |
| Frère Jacques | [BnF manuscript MS-1843, folio shown at view 106](https://gallica.bnf.fr/ark:/12148/btv1b10023704r/f106.item). The [IMSLP catalog](https://imslp.org/wiki/Fr%C3%A8re_Jacques_(Rameau,_Jean-Philippe)) dates that manuscript around 1772 and the first printed instance to 1811. Attribution to Rameau is qualified in that catalog. The BnF image service refused automated access during this update; its catalog pointer was verified through IMSLP. | Traditional French verse, 15 seconds, D3–E4. |
| Mary Had a Little Lamb | [The Child's Own Music Book, p. 49](https://en.wikisource.org/wiki/The_Child%27s_Own_Music_Book/Mary_Had_a_Little_Lamb) documents the familiar melodic contour in 1918. [Smithsonian Libraries](https://blog.library.si.edu/blog/2010/09/01/mary-had-a-little-lamb/) documents Sarah Josepha Hale's 1830 text and an earlier 1831 musical setting. The older setting is not used as evidence that every later arrangement is public domain. | First verse, 15 seconds, G3–D4. |
| Row, Row, Row Your Boat | [Millersville University's archive](https://www.millersvillearchives.com/exhibits/show/principals-and-presidents-at-m/eliphalet-oram-lyte--principal) identifies E. O. Lyte as a writer of the famous round, in its biography of the school's 1887–1912 principal. The [University of Pennsylvania catalog](https://onlinebooks.library.upenn.edu/webbin/book/browse?c=x&key=Hymns%2C+English+--+19th+century&type=lcsubc) lists the 1881 Franklin Square Song Collection associated with the tune. | First verse, 12.86 seconds, F3–F4. |
| London Bridge | [The Child's Own Music Book, p. 88, scan page 96](https://en.wikisource.org/wiki/Page:Childs_own_music_book.djvu/96) includes the familiar tune and opening verse. | First verse, 15 seconds, G3–E4. |

The 1918 volume is a [New York Public Library scan preserved by Internet Archive](https://archive.org/details/childsownmusicbo00wier); its [source record](https://en.wikisource.org/wiki/File:Childs_own_music_book.djvu) identifies the edition and editor Albert E. Wier (1879–1945). The implementation uses these old compositions, not modern sound recordings or copyrighted arrangements. These are established public-domain repertoire in the UK and US; this is not a claim that every recording bearing the same title is free to reuse everywhere.

## Sound and timing

- Guides are newly calculated sine waves plus small second and third harmonics, with short attack and release fades. They contain no voice, reverb, backing track or percussion beyond the count-in.
- The build embeds only notes, syllables and small original SVG artworks, around 40 KB for all five melodies. Playback AudioBuffers are synthesized once per selected melody at 16 kHz, mono, then cached. No audio files are downloaded or embedded. This sample rate is for guide playback only; it does not choose the microphone or upload sample rate.
- `notes` and `words` use seconds relative to the first sung note. `keyRoot` remains a pitch class; notes carry absolute MIDI pitches. A singer may use a comfortable octave.
- `listenBuf` contains a four-beat count-in, the melody and a 350 ms tail. `vocalBuf` is the melody without the count-in, retained as a compatibility name for Echo's excerpt playback; it is a synthesized instrument, not an artist vocal.
- `singBuf` contains only the four count-in clicks, then digital silence through the capture interval. No guide or accompaniment plays underneath a take through this buffer. The visual note path and lyric cue carry the rhythm while recording.
- `phraseEnd` is the musical phrase length. `take` adds a 350 ms end margin. The application decides how to repeat exercises to reach its 30 seconds of accepted source audio.
- `sourceType`, `provenance`, `captureHint`, `guideLabel`, and `captureBacking` describe the new input source explicitly. The original buffer field names remain available to all four game modes through `StardustMelodyAudio.decode(audioContext, song)`. The old embedded recording fields `listen`, `sing`, and `vocal` are omitted from the production JSON.

The wider Frère Jacques final leap and Row's octave give useful range variety. No one should strain for those pitches: use a comfortable octave, or choose the narrower Mary exercise. Headphones and quiet recording phases prevent guide bleed from contaminating the user's source recording.

## Rebuild

Run `python3 games/stardust/source/build.py` from the HOOK directory. It resolves paths from its own file, so another working directory also works. Python's standard library is sufficient. The build inlines the current `source/app.html`, `source/capture.js` and `source/melody-audio.js` placeholders when present, existing local branding, generated artwork and melody note data into both `games/stardust/index.html` and `games/stardust/HOOK-Stardust.html`. It makes no network requests.

## Verification

The five browser-generated buffers were checked using the same JavaScript generator with an AudioBuffer-compatible test context. Every guide and count-in contains finite, unclipped samples; every recording buffer is exactly zero after the count-in; durations match metadata to one sample; repeated decode calls reuse cached buffers. All five generated in about 59 ms on the development Mac. This is a synthesis and data check, not a physical microphone or speaker listening test.
