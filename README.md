# WoW 3.3.5a voice chat: Spirit IPMR vs Opus

A listening comparison between the voice codec shipped in the World of Warcraft 3.3.5a
client and Opus, with the bandwidth, PESQ and packet-loss numbers that go with it.

**The page:** https://sogladev.github.io/wow-voice-codecs/

Four samples, one list of configurations. Each clip is a complete utterance, 12 to 29
seconds, with nothing cut off, so switching between configurations changes only the codec
and switching between samples changes only the sentence. Playback position is kept across a
switch, there is a loop toggle for sitting on one phrase, and the names can be hidden for a
blind test.

## What the old codec is

The 3.3.5a client encodes voice with **Spirit IPMR** (`ComSat` in the client, the
`SPIRIT` sources in the decompilation). One 100 ms frame per UDP datagram, 8 kHz,
16-bit input, variable rate between 360 and 960 bits per frame. On speech it settles
around **6.2 kbit/s of payload, 9.0 kbit/s on the wire** including the client's 7-byte
voice header and UDP/IPv4. There is no loss concealment: a packet that does not arrive
is an empty jitter slot that gets played as silence.

## Measured results

Four sentences from LibriSpeech dev-clean (16 kHz, CC BY 4.0), averaged. Every
configuration is scored with PESQ-WB against the same 16 kHz original, so 8 kHz and
16 kHz pipelines share one scale. PESQ-WB is ITU-T P.862.2, higher is better, 4.5 is the
top of the scale. Wire bitrate includes the client's 7-byte voice header plus UDP and IPv4.

| configuration | band | wire kbit/s | pkt/s | max packet | PESQ-WB | STOI |
|---|---|---|---|---|---|---|
| **8 kHz ceiling** (reference cut to 4 kHz) | 8 kHz | – | – | – | **2.50** | 0.994 |
| today: Spirit IPMR, 100 ms packets | 8 kHz | 9.0 | 10 | 114 B | 1.50 | 0.856 |
| Opus 9.6 kbit/s, 100 ms packets | 8 kHz | 11.2 | 10 | 119 B | 2.04 | 0.885 |
| Opus 9.6 kbit/s, 60 ms packets | 8 kHz | 13.6 | 17 | 90 B | 2.21 | 0.895 |
| Opus 9.6 kbit/s, 100 ms packets | 16 kHz | 11.3 | 10 | 119 B | 2.64 | 0.858 |
| Opus 16 kbit/s, 100 ms packets | 16 kHz | 16.9 | 10 | 197 B | 4.04 | 0.904 |
| Opus 16 kbit/s, 60 ms packets | 16 kHz | 20.3 | 17 | 164 B | 4.28 | 0.911 |
| Opus 24 kbit/s, 60 ms packets | 16 kHz | 28.3 | 17 | 228 B | 4.47 | 0.917 |
| Opus 32 kbit/s, 60 ms packets | 16 kHz | 36.2 | 17 | 299 B | 4.52 | 0.920 |

With 5 % packet loss (one datagram in twenty):

| configuration | band | wire kbit/s | PESQ-WB |
|---|---|---|---|
| today: Spirit IPMR | 8 kHz | 9.0 | 1.39 |
| Opus 9.6 kbit/s, 60 ms, with FEC | 8 kHz | 13.7 | 1.81 |
| Opus 16 kbit/s, 60 ms, with FEC | 16 kHz | 20.4 | 2.82 |

Three conclusions:

- **The ceiling row is the point.** No codec choice can push an 8 kHz pipeline past 2.50,
  because the audio above 4 kHz was never captured. Codec quality inside 8 kHz is much
  closer to free: Opus at 9.6 kbit/s goes 1.50 → 2.21 for about 4 kbit/s more.
- **Bandwidth is the real lever.** 16 kHz at 16–24 kbit/s reaches 4.04–4.47. The 164–228
  byte packets no longer fit the client's 124-byte frame cap, so this is the step that
  needs the framing and time-base hooks, not just the codec hook.
- **Wideband at today's bitrate is the cheap middle step.** Opus at 9.6 kbit/s in
  100 ms packets has a 119-byte largest packet: it fits the existing cap, needs no framing
  work, and scores 2.64. Wideband Opus at 16 kbit/s needs 197 bytes for 4.04.

On the narrowband scale, where both sides are band-limited to 4 kHz and the ceiling row
does not apply, the same runs score 2.78 (IPMR) against 3.95 and 4.21 (Opus at 9.6 kbit/s,
100 ms and 60 ms). Both views are real; they answer different questions: "is the codec
better in the same band" and "how much does bandwidth buy".

## Viewing the page

`./serve.sh` is enough. It runs `tools/serve.py`, a small static server that implements
byte ranges: `python3 -m http.server` does not, and without ranges the browser treats the
audio as unseekable, so the seek bar and the position-preserving switching quietly stop
working. GitHub Pages serves ranges, so the deployed page is unaffected. `data.json` and `assets/clips/` are committed, so the page works
straight after a clone — **do not run `tools/build_site.py` just to look at it.**

`corpus/` and `out/` are local working directories (gitignored) that only exist after a
measurement run. `corpus/` holds the test speech, `out/` holds every decoded WAV plus a CSV
per run.

## Reproducing the numbers

The measurements need two things this repository does not ship: the decompiled 3.3.5a
client (Spirit IPMR is its codec, and it is not redistributed here) and libopus. Point
`DECOMP` at a decompiled client checkout; that tree is read, never modified.

```bash
DECOMP=/path/to/wowdecomp ./tools/build.sh     # builds the IPMR probe
./tools/run_matrix.sh                          # every configuration over every sample
./tools/build_site.py                          # clips + PESQ + data.json for this page
./serve.sh                                     # http://127.0.0.1:8788/
```

`build_site.py` refuses to write `data.json` when it finds no measurement outputs: it
prints what it expected and leaves the committed file untouched, so a half-configured run
cannot leave the page blank. If `data.json` ever does end up empty, `git checkout --
data.json` restores the shipped version.

`./tools/build_site.py` trims every clip to the same 10 second window, normalises them to
−20 LUFS, writes a WAV at the source rate plus a 192 kbit/s mono MP3 for the player,
recomputes PESQ and STOI, and rewrites `data.json`.

## Speech corpus

**LibriSpeech** dev-clean (CC BY 4.0, OpenSLR SLR12): four complete utterances at 16 kHz,
12 to 29 seconds each, in `corpus/items/`. Every sample is a 16 kHz recording, which is what lets the same
audio go through both an 8 kHz and a 16 kHz pipeline and be scored on one scale.

One speaker reads audiobook prose. That is fine for hearing codec artifacts and it keeps the
numbers reproducible by anyone, but it is not a raid: no headset microphone, no background
noise, no four people talking at once.

To add samples, drop 16 kHz WAVs into `corpus/items/` as `<name>_ref16.wav` (optionally a
`<name>.txt` with the id on line 1 and the text on line 2), add the name to `ITEMS` in
`tools/run_matrix.sh`, run it, then `tools/build_site.py`.

## Layout

```
index.html app.js styles.css data.json serve.sh   the page
assets/clips/                                     22 clips (11 WAV + 11 MP3)
RESULTS.md                                        the measurement report
tools/                                            harness: IPMR probe, Opus pipeline, PESQ/STOI, site build
```

`tools/spirit_probe.cpp` reproduces the client's packetisation exactly: five 20 ms
subframes encoded into one 100 ms frame, decoded with the same `while (bits - consumed >= 72)`
loop. `tools/opus_pipeline.py` drives libopus over ctypes so frame size, packet layout,
DTX, in-band FEC and simulated loss are all under test control.

## Fairness notes

- Clips are loudness-matched, otherwise the louder codec reads as the better one.
- The MP3 delivery layer is 192 kbit/s mono, roughly twenty times any candidate's own
  bitrate, and is upsampled to 48 kHz: it cannot mask the differences being shown.
- PESQ scores one clean signal against one degraded signal. It says nothing about four
  talkers at once, the game's mixing, or a real headset microphone in a room.
