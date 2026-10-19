#!/usr/bin/env python3
"""Encode/decode a WAV through libopus with the same per-packet layout the client
would use, including simulated packet loss and (optionally) in-band FEC.

libopus is loaded with ctypes, so no headers or build step are needed.

Outputs, next to the requested prefix:
  <prefix>.wav    decoded audio at the encoder rate
  <prefix>.csv    packets, bytes, bitrate, timing, loss count
"""

import argparse
import ctypes
import ctypes.util
import math
import struct
import sys
import time
import wave

# opus_defines.h request codes (stable ABI values)
OPUS_SET_BITRATE_REQUEST = 4002
OPUS_SET_VBR_REQUEST = 4006
OPUS_SET_COMPLEXITY_REQUEST = 4010
OPUS_SET_INBAND_FEC_REQUEST = 4012
OPUS_SET_PACKET_LOSS_PERC_REQUEST = 4014
OPUS_SET_DTX_REQUEST = 4016
OPUS_SET_SIGNAL_REQUEST = 4024
OPUS_APPLICATION_VOIP = 2048
OPUS_SIGNAL_VOICE = 3001


def load_opus():
    path = ctypes.util.find_library("opus") or "libopus.so.0"
    lib = ctypes.CDLL(path)

    lib.opus_encoder_create.restype = ctypes.c_void_p
    lib.opus_encoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_int)]
    lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
    lib.opus_encoder_destroy.restype = None
    lib.opus_encoder_ctl.restype = ctypes.c_int
    lib.opus_encode.restype = ctypes.c_int
    lib.opus_encode.argtypes = [ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_int16), ctypes.c_int,
                                ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
    lib.opus_encoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]

    lib.opus_decoder_create.restype = ctypes.c_void_p
    lib.opus_decoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
    lib.opus_decoder_destroy.restype = None
    lib.opus_decode.restype = ctypes.c_int
    lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
                                ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.c_int]
    return lib


def parse_packet_frames(lib, packet):
    """number of 20 ms frames contained in one packet"""
    lib.opus_packet_get_nb_frames.restype = ctypes.c_int
    lib.opus_packet_get_nb_frames.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
    buf = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
    return lib.opus_packet_get_nb_frames(buf, len(packet))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("prefix")
    ap.add_argument("--bitrate", type=int, required=True, help="bits per second")
    ap.add_argument("--frames-per-packet", type=int, default=1,
                    help="20 ms frames carried in one datagram (1 = 50 pkt/s, 5 = 10 pkt/s)")
    ap.add_argument("--drop-every", type=int, default=0,
                    help="drop every Nth packet (0 = no loss)")
    ap.add_argument("--fec", action="store_true", help="enable in-band FEC and use it on loss")
    ap.add_argument("--dtx", action="store_true", help="enable discontinuous transmission")
    ap.add_argument("--expect-loss", type=int, default=0,
                    help="encoder's assumed loss percentage (sets FEC strength)")
    args = ap.parse_args()

    lib = load_opus()

    with wave.open(args.input, "rb") as w:
        rate = w.getframerate()
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            sys.exit("need 16-bit mono input")
        pcm = w.readframes(w.getnframes())
    samples = list(struct.unpack(f"<{len(pcm) // 2}h", pcm))

    frame_samples = rate // 50  # 20 ms
    if frame_samples * 50 != rate:
        sys.exit(f"sample rate {rate} is not divisible into 20 ms frames")

    frames = [samples[i:i + frame_samples] for i in range(0, len(samples) - frame_samples + 1, frame_samples)]
    if not frames:
        sys.exit("input too short")

    err = ctypes.c_int(0)
    enc = lib.opus_encoder_create(rate, 1, OPUS_APPLICATION_VOIP, ctypes.byref(err))
    if err.value != 0 or not enc:
        sys.exit(f"opus_encoder_create failed: {err.value}")
    for request, value in (
        (OPUS_SET_BITRATE_REQUEST, args.bitrate),
        (OPUS_SET_VBR_REQUEST, 1),
        (OPUS_SET_COMPLEXITY_REQUEST, 10),
        (OPUS_SET_SIGNAL_REQUEST, OPUS_SIGNAL_VOICE),
        (OPUS_SET_DTX_REQUEST, 1 if args.dtx else 0),
        (OPUS_SET_INBAND_FEC_REQUEST, 1 if args.fec else 0),
        (OPUS_SET_PACKET_LOSS_PERC_REQUEST, args.expect_loss),
    ):
        lib.opus_encoder_ctl(enc, request, value)

    packets = []
    encode_ns = 0
    for i in range(0, len(frames), args.frames_per_packet):
        group = frames[i:i + args.frames_per_packet]
        if not group:
            break
        flat = [v for f in group for v in f]
        pcm_buf = (ctypes.c_int16 * len(flat))(*flat)
        out = (ctypes.c_ubyte * 1275)()
        t0 = time.perf_counter_ns()
        n = lib.opus_encode(enc, pcm_buf, len(group) * frame_samples, out, 1275)
        encode_ns += time.perf_counter_ns() - t0
        if n < 0:
            sys.exit(f"opus_encode failed: {n}")
        packets.append(bytes(out[:n]))
    lib.opus_encoder_destroy(enc)

    dec = lib.opus_decoder_create(rate, 1, ctypes.byref(err))
    if err.value != 0 or not dec:
        sys.exit(f"opus_decoder_create failed: {err.value}")

    pcm_out = []
    decode_ns = 0
    dropped = 0
    for i, packet in enumerate(packets):
        lost = args.drop_every > 0 and (i % args.drop_every) == (args.drop_every - 1)
        if lost:
            dropped += 1
            # a lost packet: let FEC from the next packet fill it when enabled,
            # otherwise let the decoder conceal the gap
            if args.fec and i + 1 < len(packets):
                filler = packets[i + 1]
                buf = (ctypes.c_ubyte * len(filler)).from_buffer_copy(filler)
                out = (ctypes.c_int16 * (frame_samples * args.frames_per_packet))()
                t0 = time.perf_counter_ns()
                n = lib.opus_decode(dec, buf, len(filler), out, frame_samples * args.frames_per_packet, 1)
                decode_ns += time.perf_counter_ns() - t0
            else:
                out = (ctypes.c_int16 * (frame_samples * args.frames_per_packet))()
                t0 = time.perf_counter_ns()
                n = lib.opus_decode(dec, None, 0, out, frame_samples * args.frames_per_packet, 0)
                decode_ns += time.perf_counter_ns() - t0
            if n < 0:
                sys.exit(f"opus_decode (conceal) failed: {n}")
            pcm_out.extend(out[:n])
            continue

        buf = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        out = (ctypes.c_int16 * (frame_samples * args.frames_per_packet))()
        t0 = time.perf_counter_ns()
        n = lib.opus_decode(dec, buf, len(packet), out, frame_samples * args.frames_per_packet, 0)
        decode_ns += time.perf_counter_ns() - t0
        if n < 0:
            sys.exit(f"opus_decode failed: {n}")
        pcm_out.extend(out[:n])
    lib.opus_decoder_destroy(dec)

    with wave.open(args.prefix + ".wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(pcm_out)}h", *pcm_out))

    total_bytes = sum(len(p) for p in packets)
    max_packet = max(len(p) for p in packets)
    seconds = len(frames) * frame_samples / rate
    pkt_count = len(packets)
    wire_bits = total_bytes * 8 + pkt_count * (7 + 8 + 20) * 8  # + client header, UDP, IPv4

    with open(args.prefix + ".csv", "w") as f:
        f.write("metric,value\n")
        f.write(f"rate_hz,{rate}\n")
        f.write(f"seconds,{seconds:.3f}\n")
        f.write(f"frames_per_packet,{args.frames_per_packet}\n")
        f.write(f"packets,{pkt_count}\n")
        f.write(f"dropped,{dropped}\n")
        f.write(f"payload_bytes,{total_bytes}\n")
        f.write(f"avg_packet_bytes,{total_bytes / pkt_count:.1f}\n")
        f.write(f"max_packet_bytes,{max_packet}\n")
        f.write(f"bitrate_kbps_payload,{total_bytes * 8 / seconds / 1000:.2f}\n")
        f.write(f"bitrate_kbps_wire,{wire_bits / seconds / 1000:.2f}\n")
        f.write(f"encode_us_per_packet,{encode_ns / pkt_count / 1000:.2f}\n")
        f.write(f"decode_us_per_packet,{decode_ns / pkt_count / 1000:.2f}\n")

    print(f"{args.prefix}: rate={rate} fpp={args.frames_per_packet} packets={pkt_count} "
          f"avg_pkt={total_bytes / pkt_count:.1f}B max_pkt={max_packet}B payload={total_bytes * 8 / seconds / 1000:.2f} kbit/s "
          f"wire={wire_bits / seconds / 1000:.2f} kbit/s dropped={dropped}")


if __name__ == "__main__":
    main()
