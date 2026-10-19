#!/usr/bin/env python3
"""PESQ (ITU-T P.862) and STOI for one reference/degraded pair.

Both files must share a rate: 8000 Hz for narrowband (``nb``) scoring, 16000 Hz
for wideband (``wb``) scoring. Samples are (re)resampled by the caller with sox.
"""

import argparse
import sys
import wave

import numpy as np
from pesq import pesq
from pystoi import stoi


def read(path):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            sys.exit(f"{path}: need 16-bit mono")
        return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("deg")
    ap.add_argument("--mode", choices=["nb", "wb"], required=True)
    args = ap.parse_args()

    rate_ref, ref = read(args.ref)
    rate_deg, deg = read(args.deg)
    expected = 8000 if args.mode == "nb" else 16000
    if rate_ref != expected or rate_deg != expected:
        sys.exit(f"{args.mode} needs both files at {expected} Hz (got {rate_ref}, {rate_deg})")

    n = min(len(ref), len(deg))
    ref, deg = ref[:n], deg[:n]

    mos = pesq(rate_ref, ref, deg, args.mode)
    s = stoi(ref, deg, rate_ref, extended=False)
    print(f"pesq_{args.mode},{mos:.3f}")
    print(f"stoi,{s:.3f}")
    print(f"seconds,{n / rate_ref:.2f}")


if __name__ == "__main__":
    main()
