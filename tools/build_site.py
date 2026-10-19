#!/usr/bin/env python3
"""Build the static comparison site: clips, metrics and data.json.

Every clip is trimmed from the same source segment, loudness-normalised the same
way, and delivered as 192 kbit/s mono MP3 (plus the raw WAV for download), so the
only difference a listener hears between two clips is the voice codec itself.

Usage: ./build_site.py [--site DIR] [--preview DIR]
"""

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys

CLIP_START = "4"
CLIP_LEN = "10"
MP3_BITRATE = "192k"
TARGET_LUFS = "-20"

# id, label, source wav, reference wav for PESQ, pesq mode, group, description
VARIANTS = [
    # --- narrowband, same band as today's protocol ---
    ("ref8", "original (not compressed)", "corpus/osr0010_ref8.wav", None, None, "nb",
     "The recording the others are compared against. 8 kHz, the same band today's codec is limited to."),
    ("ipmr", "today: Spirit IPMR 6.4 kbit/s", "out/osr0010_ipmr8k.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "The 2007 codec, packetised exactly as the 3.3.5a client does: one 100 ms frame per datagram."),
    ("opus_nb_6k", "Opus 6 kbit/s, 20 ms", "out/osr0010_opus8k_6000_f1.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "Opus narrowband at the same bitrate as today, in small packets."),
    ("opus_nb_9k6_100", "Opus 9.6 kbit/s, 100 ms packets", "out/osr0010_opus8k_9600_f5.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "Opus narrowband in the same packet shape as today. Largest packet is 117 bytes, inside the client's 124-byte cap."),
    ("opus_nb_9k6_60", "Opus 9.6 kbit/s, 60 ms packets", "out/osr0010_opus8k_9600_f3.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "The best measured balance: 13.1 kbit/s on the wire for a PESQ of 4.16."),
    ("opus_nb_9k6_20", "Opus 9.6 kbit/s, 20 ms packets", "out/osr0010_opus8k_9600_f1.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "Same audio in small packets. Best loss behaviour, but the per-packet overhead doubles the wire cost."),
    ("opus_nb_12k", "Opus 12 kbit/s, 20 ms", "out/osr0010_opus8k_12000_f1.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "Narrowband ceiling: needs 150 bytes per 100 ms, so it no longer fits today's frame limit."),
    ("opus_nb_15k", "Opus 15 kbit/s, 20 ms", "out/osr0010_opus8k_15000_f1.wav", "corpus/osr0010_ref8.wav", "nb", "nb",
     "Above what narrowband can use. Included to show where narrowband stops improving."),

    # --- packet loss ---
    ("ipmr_loss", "today: IPMR, 5 % loss", "out/osr0010_ipmr8k_loss5.wav", "corpus/osr0010_ref8.wav", "nb", "loss",
     "What today's protocol does at 5 % packet loss: no concealment, the gaps are silence."),
    ("opus_loss_60", "Opus 9.6 kbit/s, 60 ms, 5 % loss + FEC", "out/osr0010_opus8k_9600_f3_loss5.wav",
     "corpus/osr0010_ref8.wav", "nb", "loss",
     "Same 5 % loss with in-band forward error correction, which today's client has no equivalent of."),
    ("opus_loss_20", "Opus 9.6 kbit/s, 20 ms, 5 % loss + FEC", "out/osr0010_opus8k_9600_f1_loss5.wav",
     "corpus/osr0010_ref8.wav", "nb", "loss",
     "Small packets shrink each loss to 20 ms, so the same loss pattern hurts less."),
]

# optional wideband section, filled in when a >=16 kHz recording has been measured
WIDEBAND = [
    ("ref16", "original", "corpus/{name}_ref16.wav", None, None, "wideband", "Wideband reference."),
    ("wb_16k", "Opus 16 kbit/s, 16 kHz", "out/{name}_opus16k_16000_f3.wav", "corpus/{name}_ref16.wav", "wb", "wideband", "Opus wideband."),
    ("wb_24k", "Opus 24 kbit/s, 16 kHz", "out/{name}_opus16k_24000_f3.wav", "corpus/{name}_ref16.wav", "wb", "wideband", "Opus wideband."),
    ("wb_32k", "Opus 32 kbit/s, 16 kHz", "out/{name}_opus16k_32000_f3.wav", "corpus/{name}_ref16.wav", "wb", "wideband", "Opus wideband."),
    ("fb_32k", "Opus 32 kbit/s, 48 kHz", "out/{name}_opus48k_32000_f3.wav", "corpus/{name}_ref16.wav", "wb", "wideband", "Opus fullband."),
    ("fb_48k", "Opus 48 kbit/s, 48 kHz", "out/{name}_opus48k_48000_f3.wav", "corpus/{name}_ref16.wav", "wb", "wideband", "Opus fullband."),
]


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


def pesq(ref, deg, mode):
    if not ref or not os.path.exists(ref) or not os.path.exists(deg):
        return None, None
    r = run([sys.executable, os.path.join(os.path.dirname(__file__), "score.py"), ref, deg, "--mode", mode])
    if r.returncode != 0:
        return None, None
    vals = {}
    for line in r.stdout.splitlines():
        if "," in line:
            k, v = line.split(",", 1)
            vals[k] = v
    return vals.get(f"pesq_{mode}"), vals.get("stoi")


def source_rate(path):
    r = run(["soxi", "-r", path])
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 48000


def trim_and_encode(src, dst_base, tmp_dir):
    """trim the shared segment, normalise loudness, write mp3 + wav

    The WAV keeps the source sample rate so it is the exact decoded output; the MP3
    is upsampled to 48 kHz because a lossy layer at 192 kbit/s on top of an 8 kHz
    voice codec cannot change what the voice codec did.
    """
    mp3 = dst_base + ".mp3"
    wav = dst_base + ".wav"
    rate = source_rate(src)
    # loudnorm runs at 192 kHz internally, so the output rate has to be pinned
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-ss", CLIP_START, "-t", CLIP_LEN,
             "-af", f"loudnorm=I={TARGET_LUFS}:TP=-2:LRA=7",
             "-ar", str(rate), "-c:a", "pcm_s16le", wav])
    if r.returncode != 0:
        print(f"  ffmpeg wav failed for {src}: {r.stderr[:200]}")
        return False
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
             "-ar", "48000", "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, mp3])
    if r.returncode != 0:
        print(f"  ffmpeg mp3 failed for {src}: {r.stderr[:200]}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None)
    ap.add_argument("--preview", default=None)
    args = ap.parse_args()

    here = pathlib.Path(__file__).resolve().parent
    preview = pathlib.Path(args.preview).resolve() if args.preview else here.parent
    site = pathlib.Path(args.site).resolve() if args.site else here.parent
    clips = site / "assets" / "clips"
    clips.mkdir(parents=True, exist_ok=True)

    os.chdir(preview)

    items = []
    for vid, label, src, ref, mode, group, note in VARIANTS:
        if not os.path.exists(src):
            print(f"skip {vid}: missing {src}")
            continue
        base = clips / vid
        if not trim_and_encode(src, str(base), str(clips)):
            continue
        p, s = pesq(ref, src, mode) if ref else (None, None)
        meta = read_csv(src[:-4] + ".csv")
        items.append({
            "id": vid, "label": label, "group": group, "note": note,
            "mp3": f"assets/clips/{vid}.mp3", "wav": f"assets/clips/{vid}.wav",
            "sourceRate": "8000",
            "pesq": p, "stoi": s,
            "wireKbps": meta.get("bitrate_kbps_wire"),
            "payloadKbps": meta.get("bitrate_kbps_payload"),
            "packetsPerSecond": (round(int(meta["packets"]) / float(meta["seconds"]), 1)
                                 if meta.get("packets") and meta.get("seconds") else None),
            "maxPacketBytes": meta.get("max_packet_bytes"),
        })
        print(f"  {vid}: pesq={p} stoi={s} wire={meta.get('bitrate_kbps_wire')}")

    wideband = []
    sample = "mic_sample_48k"
    if os.path.exists(f"corpus/{sample}_ref16.wav"):
        for vid, label, src_t, ref_t, mode, group, note in WIDEBAND:
            src = src_t.format(name=sample)
            ref = ref_t.format(name=sample) if ref_t else None
            if not os.path.exists(src):
                print(f"skip wideband {vid}: missing {src}")
                continue
            base = clips / vid
            if not trim_and_encode(src, str(base), str(clips)):
                continue
            p, s = pesq(ref, src, mode) if ref else (None, None)
            meta = read_csv(src[:-4] + ".csv")
            wideband.append({
                "id": vid, "label": label, "group": group, "note": note,
                "mp3": f"assets/clips/{vid}.mp3", "wav": f"assets/clips/{vid}.wav",
                "sourceRate": "16000" if "16k" in vid else "48000",
                "pesq": p, "stoi": s,
                "wireKbps": meta.get("bitrate_kbps_wire"),
                "payloadKbps": meta.get("bitrate_kbps_payload"),
                "packetsPerSecond": (round(int(meta["packets"]) / float(meta["seconds"]), 1)
                                     if meta.get("packets") and meta.get("seconds") else None),
                "maxPacketBytes": meta.get("max_packet_bytes"),
            })
            print(f"  wideband {vid}: pesq={p} wire={meta.get('bitrate_kbps_wire')}")

    data = {
        "generated": subprocess.run(["date", "-u", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip(),
        "narrowband": items,
        "wideband": wideband,
        "deliveryCodec": f"MP3 {MP3_BITRATE} mono, {TARGET_LUFS} LUFS",
        "corpus": "Open Speech Repository, American English, 8 kHz (voiptroubleshooter.com)",
    }
    (site / "data.json").write_text(json.dumps(data, indent=2))
    print(f"wrote {site / 'data.json'} ({len(items)} narrowband, {len(wideband)} wideband clips)")


if __name__ == "__main__":
    main()
