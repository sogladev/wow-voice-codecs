# Spirit IPMR vs Opus — offline measurement report

Everything here was produced without touching the game: the 3.3.5a codec
(`ComSat/SPIRIT`, taken read-only from `/home/pc/wd/client/wowdecomp`) was compiled
as a standalone library, driven exactly the way `ComSatSoundCODEC.cpp` drives it,
and compared against Opus on speech.

Reproduce with `./build.sh`, `./run_preview.sh`, `./run_wideband.sh` in this directory.

## Corpus

| source | rate | length | why |
|---|---|---|---|
| `corpus/OSR_us_000_0010_8k.wav`, `..._0016_8k.wav` | 8 kHz | 33 s, 35 s | real recordings, published for VoIP codec testing |
| `corpus/tts*_ref*.wav` | 22 kHz source | 6 s each | speech-shaped filler only, see the caveat on band-limited material |
| `corpus/librispeech_16k.wav` | 16 kHz | 12 s | LibriSpeech dev-clean (CC BY 4.0), standard wideband test material |

PESQ (ITU-T P.862) and STOI are computed against the 8 kHz reference for narrowband
comparisons, and against a 16 kHz reference for wideband comparisons.

## How the old codec behaves, measured

The client encodes one 100 ms block per packet: five 20 ms subframes pushed into one
bit stream (`ComSatSoundCODEC.cpp:73`), and decodes by looping while
`bits - consumed >= 72` (`:131`). Bits per 100 ms block came out at **395–851 on
speech and up to 960 on loud material**, i.e. the variable-rate range the codec was
built for.

| measurement | value |
|---|---|
| payload bitrate on speech | 6.0–6.6 kbit/s |
| wire bitrate (7-byte client header + UDP/IPv4) | 8.8–9.4 kbit/s |
| packets per second | 10 |
| encode CPU | 275–360 µs per 100 ms block |
| decode CPU | 42–52 µs per 100 ms block |
| packet loss behaviour | no concealment at all: the client never calls the codec with the `lost` flag, a missing packet is an empty jitter slot played as silence |

That last line matters more than it looks: at 5 % loss the codec loses about
0.5 MOS purely from silence gaps.

## Narrowband comparison (real speech, 8 kHz in, 8 kHz out)

PESQ-LQO 1.0–4.5, higher is better. 5 % loss means every 20th packet dropped.

| configuration | wire kbit/s | pkt/s | max packet | PESQ clean | PESQ 5 % loss |
|---|---|---|---|---|---|
| **today: IPMR** | 9.2 | 10 | 107 B | **2.69** | 2.22 |
| Opus NB 9.6 k, 100 ms packets | 10.8 | 10 | 117 B | **3.91** | 2.91 |
| Opus NB 9.6 k, 60 ms packets | 13.1 | 17 | 91 B | **4.16** | 3.12 |
| Opus NB 9.6 k, 40 ms packets | 15.5 | 25 | 65 B | 4.14 | 2.90 |
| Opus NB 9.6 k, 20 ms packets | 22.5 | 50 | 34 B | 4.13 | 3.38 |
| Opus NB 6 k, 20 ms packets | 19.2 | 50 | 26 B | 3.22 | — |
| Opus NB 12 k, 20 ms packets | 25.1 | 50 | 42 B | 4.31 | — |
| Opus NB 15 k, 20 ms packets | 28.3 | 50 | 51 B | 4.40 | — |

Three findings:

1. **Codec-only swap is worth much more than the earlier estimate.** Opus narrowband
   at 9.6 kbit/s in 100 ms packets scores 3.91 against 2.69 for IPMR, and its largest
   packet is 117 bytes — inside both hard caps of the current pipeline (124 bytes in
   `LocalTalker::Frame::m_data`, 128 bytes in `VoicePacket::m_data`). This needs no
   framing change, no I/O change, just the codec.
2. **Packet size choice is a bandwidth decision, not a detail.** 50 packets per second
   spends 14 kbit/s on the 7-byte client header plus UDP/IPv4 before any audio. At
   10 packets per second the same audio costs 10.8 kbit/s on the wire.
3. **Packet loss is where Opus wins hardest in practice.** IPMR drops to 2.22 at 5 %
   loss because it has no concealment in this client; Opus with in-band FEC keeps 3.12
   at 60 ms packets, and 3.38 at 20 ms packets.

## Wideband: 16 kHz instead of 8 kHz

The 8 kHz corpus cannot show this part: it has no content above 4 kHz, so a wideband
codec has nothing extra to preserve. The wideband runs therefore use **LibriSpeech**
dev-clean (16 kHz, CC BY 4.0), two utterances concatenated into a 12 second sample.

Every candidate is scored with PESQ-WB against the same 16 kHz reference, including the
narrowband ones after upsampling. The ceiling row is the uncompressed reference cut to
4 kHz and upsampled: whatever the codec, an 8 kHz pipeline cannot score above it.

| configuration | PESQ-WB | STOI | payload kbit/s | wire kbit/s | max packet |
|---|---|---|---|---|---|
| 8 kHz ceiling (band-limited reference) | 2.22 | 0.992 | – | – | – |
| today: IPMR, 8 kHz, 100 ms | 1.37 | 0.843 | 6.3 | 9.1 | 111 B |
| Opus 9.6 k, 8 kHz, 100 ms | 1.82 | 0.880 | 8.5 | 11.3 | 117 B |
| Opus 9.6 k, 8 kHz, 60 ms | 1.94 | 0.890 | 9.1 | 13.7 | 84 B |
| Opus 16 k, 16 kHz, 60 ms | 4.27 | 0.907 | 15.8 | 20.5 | 153 B |
| Opus 24 k, 16 kHz, 60 ms | 4.47 | 0.916 | 23.9 | 28.5 | 219 B |
| Opus 32 k, 16 kHz, 60 ms | 4.51 | 0.918 | 31.9 | 36.5 | 295 B |

Two conclusions:

1. Codec quality inside 8 kHz is close to free: Opus at 9.6 kbit/s recovers most of what
   IPMR throws away (1.37 → 1.94 on this scale, 2.69 → 4.16 on the narrowband scale) for
   about 1.5 kbit/s more.
2. Bandwidth is the bigger lever. Wideband jumps to 4.27 at 20.5 kbit/s. The 153 byte
   largest packet no longer fits the client's 124-byte frame cap, so this is the step that
   needs the framing and time-base hooks described in the plan, not just the codec hook.

## Caveats

- PESQ scores one clean signal against one degraded signal. It cannot say anything
  about four simultaneous talkers, ducking, or how the game's own mixing sounds.
- CPU numbers are from this machine, one core, and only compare the two codecs
  relative to each other.
- The corpus is clean studio-ish speech plus some TTS. Game voice chat has keyboard
  noise, room tone and a headset microphone; the ranking of the codecs will not flip,
  but the absolute MOS will drop for all of them.
- The simulated loss drops packets in a fixed pattern. Real loss is bursty, which
  penalises longer packets more than this test does.

## Listening in a browser

`site/` holds a static page that plays these results: blind A/B switching on the same
snippet, a packet-loss section, the metric tables, and a wideband section that appears
once a real 16 kHz recording has been measured. See `site/README.md` for hosting.

```
./site/serve.sh        # http://127.0.0.1:8788/
```

## Files

- `src/spirit_probe.cpp` — IPMR encode/decode driven exactly like the client, WAV in/out, timing, loss simulation
- `src/opus_pipeline.py` — Opus through libopus via ctypes, per-packet encode/decode, FEC and loss simulation
- `src/wav_metrics.cpp` — delay-aligned SNR, segmental SNR, log-spectral distance, band energy
- `src/score.py` — PESQ and STOI wrappers
- `out/` — every decoded WAV, CSV per run, `out/spectro/` spectrograms, `out/listen/` a small A/B set
- `site/` — the comparison page (`index.html`, `app.js`, `styles.css`, `data.json`, `assets/clips/`), built by `site/build_site.py`
