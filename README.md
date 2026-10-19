# WoW 3.3.5a voice chat: Spirit IPMR vs Opus

A listening comparison between the voice codec shipped in the World of Warcraft 3.3.5a
client and Opus, with the bandwidth, PESQ and packet-loss numbers that go with it.

**The page:** https://sogladev.github.io/wow-voice-codecs/

It plays the same ten seconds of speech through each codec, so the only thing that
changes when you switch is the codec. Names can be hidden for a blind test, playback
position is kept across a switch, and every clip has a WAV download next to it because
the MP3 is only the delivery layer.

## What the old codec is

The 3.3.5a client encodes voice with **Spirit IPMR** (`ComSat` in the client, the
`SPIRIT` sources in the decompilation). One 100 ms frame per UDP datagram, 8 kHz,
16-bit input, variable rate between 360 and 960 bits per frame. On speech it settles
around **6.4 kbit/s of payload, 9.2 kbit/s on the wire** including the client's 7-byte
voice header and UDP/IPv4. There is no loss concealment: a packet that does not arrive
is an empty jitter slot that gets played as silence.

## Measured results, narrowband

PESQ is ITU-T P.862 (1.0–4.5, higher is better) against the uncompressed source.
Wire bitrate includes the 7-byte client header plus UDP and IPv4 overhead.

| configuration | wire kbit/s | pkt/s | max packet | PESQ | PESQ @ 5 % loss |
|---|---|---|---|---|---|
| today: IPMR | 9.2 | 10 | 107 B | 2.69 | 2.22 |
| Opus 10.8 kbit/s, 100 ms packets | 10.8 | 10 | 117 B | 3.91 | 2.91 |
| Opus 13.1 kbit/s, 60 ms packets | 13.1 | 17 | 91 B | 4.16 | 3.12 |
| Opus 22.5 kbit/s, 20 ms packets | 22.5 | 50 | 34 B | 4.13 | 3.38 |
| Opus 25 kbit/s, 20 ms packets | 25.1 | 50 | 42 B | 4.31 | – |
| Opus 28 kbit/s, 20 ms packets | 28.3 | 50 | 51 B | 4.40 | – |

Two things worth noticing:

- Opus at 9.6 kbit/s in the **same 100 ms packet shape** the client already uses scores
  3.91 instead of 2.69, and its largest packet is 117 bytes, inside both hard caps of the
  existing pipeline (`LocalTalker::Frame::m_data[124]`, `VoicePacket::m_data[128]`). That
  makes the codec swap worthwhile on its own, with no framing or transport changes.
- Packet size is a bandwidth decision. At 50 packets per second the 7-byte client header
  plus UDP/IPv4 costs 14 kbit/s before any audio; the same audio at 10 packets per second
  costs 10.8 kbit/s.

## Wideband: 16 kHz instead of 8 kHz

Measured on LibriSpeech dev-clean (16 kHz, CC BY 4.0). Every row is scored with
PESQ-WB against the same 16 kHz reference, so narrowband and wideband candidates share
one scale. The first row is not a codec: it is the uncompressed reference cut to 4 kHz
and upsampled, which is the best any 8 kHz pipeline can ever score.

| configuration | PESQ-WB | STOI | wire kbit/s |
|---|---|---|---|
| 8 kHz ceiling (band-limited reference) | 2.22 | 0.992 | – |
| today: IPMR, 8 kHz | 1.37 | 0.843 | 9.1 |
| Opus 9.6 kbit/s, 8 kHz, 100 ms | 1.82 | 0.880 | 11.3 |
| Opus 9.6 kbit/s, 8 kHz, 60 ms | 1.94 | 0.890 | 13.7 |
| Opus 9.6 kbit/s, 16 kHz, 100 ms | 2.51 | 0.855 | 11.4 |
| Opus 16 kbit/s, 16 kHz, 100 ms | 4.04 | 0.902 | 17.0 |
| Opus 16 kbit/s, 16 kHz, 60 ms | 4.27 | 0.907 | 20.5 |
| Opus 24 kbit/s, 16 kHz, 60 ms | 4.47 | 0.916 | 28.5 |
| Opus 32 kbit/s, 16 kHz, 60 ms | 4.51 | 0.918 | 36.5 |

The 9.6 kbit/s wideband row matters for scheduling the work: its largest packet is 118
bytes, inside the client's existing 124-byte frame cap, so wideband can start with only
the sample-rate change and no framing rework. Clearing the 8 kHz ceiling properly needs
16–24 kbit/s, and those packets are 153–219 bytes, which is the step that forces the
framing and time-base hooks.

Narrowband gets a better number for the same band (2.69 → 3.91 on the narrowband scale),
but it cannot leave the 8 kHz ceiling: at 20–28 kbit/s and 16 kHz, Opus scores 4.3–4.5 on
this scale for roughly double the bandwidth of today's protocol.

Full report, including the caveats: [RESULTS.md](RESULTS.md).

## Viewing the page

`./serve.sh` is enough. `data.json` and `assets/clips/` are committed, so the page works
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
./tools/run_preview.sh                         # narrowband runs over the 8 kHz corpus
./tools/run_wideband.sh corpus/librispeech_16k.wav
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

## Speech corpora

- Narrowband: the **Open Speech Repository** American English Harvard sentences at 8 kHz,
  published for VoIP codec testing.
- Wideband: **LibriSpeech** dev-clean utterances at 16 kHz (CC BY 4.0, OpenSLR SLR12),
  concatenated into a 12 second sample. This is standard material for speech codec work,
  which is why the published numbers do not depend on anyone's microphone.

`./tools/record_sample.sh` is still there if a real headset microphone sample is wanted:
the wideband section picks up `corpus/mic_sample_48k.*` in preference to the corpus when
it exists.

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
