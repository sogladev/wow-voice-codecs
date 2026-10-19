#!/usr/bin/env python3
"""Build the comparison site: clips, metrics and data.json.

The page has one comparison: every clip is 8 seconds of the same sentence, loudness
matched and delivered as MP3, so switching between them changes only the codec. Each
item (a sentence) is a 16 kHz recording, which is what lets an 8 kHz and a 16 kHz
pipeline be compared on the same material and scored on one scale.

Usage: ./tools/build_site.py [--site DIR] [--preview DIR]
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys

# whole samples, nothing trimmed: the point of a complete utterance is that no
# sentence is cut in half, which is exactly what made the first version awkward
CLIP_START = None
CLIP_LEN = None
MP3_BITRATE = "128k"
TARGET_LUFS = "-20"

ITEMS = ["item1", "item2", "item3", "item4"]

# id, label, band, group, note
CONFIGS = [
    ("ref16", "original, 16 kHz", "16 kHz", "reference",
     "The uncompressed recording everything else is compared against."),
    ("ceiling8k", "8 kHz ceiling: the same audio limited to 4 kHz", "8 kHz", "reference",
     "Not a codec. The recording band-limited to 4 kHz and upsampled, which is the best any 8 kHz pipeline can ever sound. Compare the rows under it against this one to see what bandwidth costs."),
    ("ipmr", "today: Spirit IPMR, 8 kHz, 100 ms packets", "8 kHz", "codec",
     "The 2007 codec, packetised exactly as the 3.3.5a client does: one 100 ms frame per datagram, 6.2 kbit/s of payload."),
    ("nb96_100", "Opus 9.6 kbit/s, 8 kHz, 100 ms packets", "8 kHz", "codec",
     "Opus narrowband in today's packet shape. Still 8 kHz, so it cannot pass the ceiling above."),
    ("nb96_60", "Opus 9.6 kbit/s, 8 kHz, 60 ms packets", "8 kHz", "codec",
     "Opus narrowband with shorter packets: better under loss, more per-packet overhead."),
    ("wb96_100", "Opus 9.6 kbit/s, 16 kHz, 100 ms packets", "16 kHz", "codec",
     "Wideband at today's bitrate. Its largest packet is 118 bytes, inside the client's 124-byte frame cap."),
    ("wb16_100", "Opus 16 kbit/s, 16 kHz, 100 ms packets", "16 kHz", "codec",
     "Wideband with real headroom. 192-byte packets, so this needs the frame cap lifted."),
    ("wb16_60", "Opus 16 kbit/s, 16 kHz, 60 ms packets", "16 kHz", "codec",
     "The balanced wideband setting."),
    ("wb24_60", "Opus 24 kbit/s, 16 kHz, 60 ms packets", "16 kHz", "codec",
     "Comfortable wideband if bandwidth is not scarce."),
    ("wb32_60", "Opus 32 kbit/s, 16 kHz, 60 ms packets", "16 kHz", "codec",
     "Diminishing returns start here."),

    ("ipmr_loss", "today: Spirit IPMR, 5 % packet loss", "8 kHz", "loss",
     "One packet in twenty missing. Today's client has no concealment, so the gaps are silence."),
    ("nb96_60_loss", "Opus 9.6 kbit/s, 8 kHz, 60 ms, 5 % loss + FEC", "8 kHz", "loss",
     "Same loss with in-band forward error correction."),
    ("wb16_60_loss", "Opus 16 kbit/s, 16 kHz, 60 ms, 5 % loss + FEC", "16 kHz", "loss",
     "Wideband with the same loss and FEC."),
]

RESAMPLE = {"nb": "8000", "wb": "16000"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read_csv(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for line in f:
            if "," in line and line[0].isalpha():
                k, v = line.strip().split(",")[:2]
                out[k] = v
    return out


class Resampler:
    def __init__(self):
        self.cache = {}

    def at(self, path, rate):
        key = (path, rate)
        if key not in self.cache:
            out = f"{path}.{rate}.wav"
            r = run(["sox", path, "-b", "16", "-r", rate, out, "rate", "-v", rate])
            self.cache[key] = out if r.returncode == 0 else path
        return self.cache[key]


def source_rate(path):
    r = run(["soxi", "-r", path])
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 48000


def clip(src, dst_base):
    """Whole sample, loudness matched, MP3 for the player."""
    mp3 = dst_base + ".mp3"
    tmp = dst_base + ".wav"
    rate = source_rate(src)
    trim = []
    if CLIP_START is not None:
        trim += ["-ss", CLIP_START]
    if CLIP_LEN is not None:
        trim += ["-t", CLIP_LEN]
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, *trim,
             "-af", f"loudnorm=I={TARGET_LUFS}:TP=-2:LRA=7",
             "-ar", str(rate), "-c:a", "pcm_s16le", tmp])
    if r.returncode != 0:
        print(f"  ffmpeg failed for {src}: {r.stderr[:160]}")
        return None
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", tmp,
             "-ar", "48000", "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, mp3])
    os.unlink(tmp)
    if r.returncode != 0:
        print(f"  mp3 failed for {src}: {r.stderr[:160]}")
        return None
    return mp3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None)
    ap.add_argument("--preview", default=None)
    args = ap.parse_args()

    here = pathlib.Path(__file__).resolve().parent
    root = pathlib.Path(args.preview).resolve() if args.preview else here.parent
    site = pathlib.Path(args.site).resolve() if args.site else here.parent
    clips_dir = site / "assets" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(root)
    resampler = Resampler()

    items_out = []
    per_config = {}
    missing = []

    for item in ITEMS:
        ref16 = f"corpus/items/{item}_ref16.wav"
        if not os.path.exists(ref16):
            missing.append(ref16)
            continue

        text = ""
        if os.path.exists(f"corpus/items/{item}.txt"):
            lines = [l.strip() for l in open(f"corpus/items/{item}.txt") if l.strip()]
            text = lines[1] if len(lines) > 1 else ""

        item_clips = {}
        for cid, label, band, group, note in CONFIGS:
            src = ref16 if cid == "ref16" else f"out/{item}_{cid}.wav"
            if not os.path.exists(src):
                missing.append(src)
                continue

            dst = clips_dir / f"{item}_{cid}"
            mp3 = clip(src, str(dst))
            if not mp3:
                continue
            item_clips[cid] = {"mp3": f"assets/clips/{item}_{cid}.mp3", "wav": None}

            if cid == "ref16":
                continue

            csv_meta = read_csv(f"out/{item}_{cid}.csv")
            score_src = resampler.at(src, RESAMPLE["wb"])
            r = run([sys.executable, str(here / "score.py"), ref16, score_src, "--mode", "wb"])
            pesq = stoi = None
            for line in r.stdout.splitlines():
                if line.startswith("pesq_wb,"):
                    pesq = float(line.split(",")[1])
                elif line.startswith("stoi,"):
                    stoi = float(line.split(",")[1])

            per_config.setdefault(cid, []).append({
                "item": item,
                "pesq": pesq,
                "stoi": stoi,
                "wire": float(csv_meta["bitrate_kbps_wire"]) if csv_meta.get("bitrate_kbps_wire") else None,
                "packetsPerSecond": (round(int(csv_meta["packets"]) / float(csv_meta["seconds"]), 1)
                                     if csv_meta.get("packets") and csv_meta.get("seconds") else None),
                "maxPacket": int(csv_meta["max_packet_bytes"]) if csv_meta.get("max_packet_bytes") else None,
            })

        items_out.append({
            "id": item,
            "label": f"sample {item[-1]}",
            "text": text,
            "clips": item_clips,
        })
        print(f"  {item}: {len(item_clips)} clips  {text[:52]}")

    if not items_out or not per_config:
        sys.exit(
            "no measurement outputs found, so data.json was left untouched.\n\n"
            "The page ships with data.json and assets/clips already committed; rebuilding them\n"
            "is only needed when you re-measure. To do that:\n\n"
            "  DECOMP=/path/to/wowdecomp ./tools/build.sh\n"
            "  ./tools/run_matrix.sh\n"
            "  ./tools/build_site.py\n\n"
            "Expected inputs: corpus/items/<item>_ref16.wav and the out/<item>_*.wav +\n"
            "out/<item>_*.csv files that run_matrix.sh produces.\n"
            f"Missing, for example: {missing[0] if missing else 'everything'}"
        )

    configs_out = []
    for cid, label, band, group, note in CONFIGS:
        rows = per_config.get(cid, [])
        if not rows and cid != "ref16":
            continue
        pesqs = [r["pesq"] for r in rows if r["pesq"] is not None]
        stois = [r["stoi"] for r in rows if r["stoi"] is not None]
        wires = [r["wire"] for r in rows if r["wire"] is not None]
        maxp = [r["maxPacket"] for r in rows if r["maxPacket"] is not None]
        pps = [r["packetsPerSecond"] for r in rows if r["packetsPerSecond"] is not None]
        configs_out.append({
            "id": cid, "label": label, "band": band, "group": group, "note": note,
            "pesq": round(sum(pesqs) / len(pesqs), 2) if pesqs else None,
            "pesqMin": round(min(pesqs), 2) if pesqs else None,
            "pesqMax": round(max(pesqs), 2) if pesqs else None,
            "stoi": round(sum(stois) / len(stois), 3) if stois else None,
            "wireKbps": round(sum(wires) / len(wires), 1) if wires else None,
            "packetsPerSecond": (sorted(set(pps))[0] if pps else None),
            "maxPacketBytes": max(maxp) if maxp else None,
        })

    data = {
        "generated": run(["date", "-u", "+%Y-%m-%d"]).stdout.strip(),
        "deliveryCodec": f"MP3 {MP3_BITRATE} mono, {TARGET_LUFS} LUFS",
        "corpus": "LibriSpeech dev-clean, 16 kHz, CC BY 4.0",
        "items": items_out,
        "configs": configs_out,
    }

    tmp = site / "data.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, site / "data.json")
    print(f"wrote {site / 'data.json'}: {len(items_out)} samples, {len(configs_out)} configurations")
    if missing:
        print(f"note: {len(missing)} expected inputs were missing, first: {missing[0]}")


if __name__ == "__main__":
    main()
