# Spirit IPMR vs Opus — measurement report

Everything here was produced without touching the game: the 3.3.5a codec
(`ComSat/SPIRIT`, read from a decompiled client checkout and never modified) was compiled
as a standalone library, driven exactly the way `ComSatSoundCODEC.cpp` drives it, and
compared against Opus on speech.

Reproduce with `./tools/build.sh`, `./tools/run_matrix.sh`, `./tools/build_site.py`.

## Corpus

Four complete utterances from **LibriSpeech** dev-clean (CC BY 4.0, OpenSLR SLR12), 16 kHz,
12 to 29 seconds each, in `corpus/items/`. Nothing is trimmed: a clipped sample can stop in
the middle of a word, which makes both listening and PESQ worse for reasons unrelated to
the codec. The point of a 16 kHz source is that the same audio
can be pushed through an 8 kHz pipeline and a 16 kHz pipeline, so both can be scored
against one reference.

One speaker reads audiobook prose. That is enough to hear codec artifacts and keeps the
numbers reproducible without anyone's microphone, but it is not a raid: no headset
microphone, no room, no four talkers at once.

## How the old codec behaves, measured

The client encodes one 100 ms block per packet: five 20 ms subframes pushed into one bit
stream (`ComSatSoundCODEC.cpp:73`), and decodes by looping while `bits - consumed >= 72`
(`:131`).

| measurement | value |
|---|---|
| bits per 100 ms frame on speech | 395–887 |
| payload bitrate | 6.2–6.3 kbit/s |
| wire bitrate (7-byte client header + UDP/IPv4) | 9.0 kbit/s |
| packets per second | 10 |
| largest packet | 114 B |
| encode CPU | 280–360 µs per 100 ms block |
| decode CPU | 42–52 µs per 100 ms block |
| packet loss behaviour | no concealment: the client never calls the codec with the `lost` flag, a missing packet is an empty jitter slot played as silence |

## Results

PESQ-WB (ITU-T P.862.2) against the uncompressed 16 kHz original, averaged over the four
samples. Scoring on the wideband scale is deliberate: it is the only scale on which an
8 kHz pipeline and a 16 kHz pipeline mean the same thing, and it makes the ceiling visible.
Wire bitrate includes the 7-byte client header plus UDP and IPv4 overhead.

| configuration | band | wire kbit/s | pkt/s | max packet | PESQ-WB | STOI |
|---|---|---|---|---|---|---|
| 8 kHz ceiling (reference cut to 4 kHz) | 8 kHz | – | – | – | 2.50 | 0.994 |
| today: Spirit IPMR, 100 ms | 8 kHz | 9.0 | 10 | 114 B | 1.50 | 0.856 |
| Opus 9.6 k, 100 ms | 8 kHz | 11.2 | 10 | 119 B | 2.04 | 0.885 |
| Opus 9.6 k, 60 ms | 8 kHz | 13.6 | 17 | 90 B | 2.21 | 0.895 |
| Opus 9.6 k, 100 ms | 16 kHz | 11.3 | 10 | 119 B | 2.64 | 0.858 |
| Opus 16 k, 100 ms | 16 kHz | 16.9 | 10 | 197 B | 4.04 | 0.904 |
| Opus 16 k, 60 ms | 16 kHz | 20.3 | 17 | 164 B | 4.28 | 0.911 |
| Opus 24 k, 60 ms | 16 kHz | 28.3 | 17 | 228 B | 4.47 | 0.917 |
| Opus 32 k, 60 ms | 16 kHz | 36.2 | 17 | 299 B | 4.52 | 0.920 |

Packet loss, one datagram in twenty, with in-band FEC where the codec has it:

| configuration | band | wire kbit/s | PESQ-WB |
|---|---|---|---|
| today: Spirit IPMR | 8 kHz | 9.0 | 1.39 |
| Opus 9.6 k, 60 ms, FEC | 8 kHz | 13.7 | 1.81 |
| Opus 16 k, 60 ms, FEC | 16 kHz | 20.4 | 2.82 |

Narrowband cross-check: scored only inside 4 kHz, where the wideband ceiling does not
apply, the same runs are 2.78 (IPMR), 3.95 (Opus 9.6 k, 100 ms) and 4.21 (Opus 9.6 k,
60 ms). That is the "same band, better codec" view; the table above is the "what does
bandwidth buy" view.

### What the numbers say

1. **The ceiling row bounds everything built on 8 kHz.** 2.50 is the best an 8 kHz
   pipeline can score, because nothing above 4 kHz was ever captured. Any plan that keeps
   8 kHz inherits that limit.
2. **Codec quality inside 8 kHz is nearly free.** Opus at 9.6 kbit/s takes 1.50 → 2.21
   for about 4 kbit/s more wire bandwidth, and the 100 ms configuration (119 B) fits the
   client's 124-byte frame cap without touching the framing.
3. **Wideband is the real step, and it is cheap at the low end.** 16 kHz at 9.6 kbit/s
   scores 2.64 in a 119-byte packet: same cap, same packet rate, no framing work. The
   step to 4.04–4.47 needs 16–24 kbit/s, which is 164–228 bytes per packet and therefore
   the framing and time-base hooks.
4. **Packet-loss robustness is a separate upgrade.** Today's client drops to 1.44 at 5 %
   loss because it has no concealment at all; Opus with FEC keeps 1.81 at 8 kHz and 2.82
   at 16 kHz.

## Caveats

- PESQ scores one clean signal against one degraded signal. It cannot say anything about
  four simultaneous talkers, ducking, or how the game's own mixing sounds.
- CPU numbers are from one machine and one core, and only compare the two codecs
  relative to each other.
- The corpus is clean read speech from one speaker. The ranking of the codecs will not
  flip on real voice chat, but every absolute score will drop.
- Simulated loss drops packets in a fixed pattern; real loss is bursty, which penalises
  longer packets more than this test does.
- The MP3 in the page is a delivery layer for listening, not a measurement input: all
  numbers come from the decoded WAVs.

## Files

- `tools/spirit_probe.cpp` — IPMR encode/decode driven exactly like the client, WAV in/out, timing, loss simulation
- `tools/opus_pipeline.py` — Opus through libopus via ctypes, per-packet encode/decode, FEC and loss simulation
- `tools/wav_metrics.cpp` — delay-aligned SNR, segmental SNR, log-spectral distance, band energy
- `tools/score.py` — PESQ and STOI wrappers
- `tools/run_matrix.sh` — every configuration over every sample
- `tools/build_site.py` — clips, PESQ table and `data.json` for the page
- `corpus/items/` — the four 16 kHz samples (regenerated from LibriSpeech, not committed)
- `assets/clips/` — the page's clips
