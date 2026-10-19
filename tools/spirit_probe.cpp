// Offline probe for the 3.3.5a voice codec (Spirit IPMR / IPMR6000).
//
// Reproduces exactly what the client does per 100 ms packet:
//   encode: 5 x 20 ms subframes (320 PCM bytes each) into one bit stream
//   decode: loop while (bits - consumed) >= 72, each call produces 320 PCM bytes
//
// The codec itself is compiled straight from the wowdecomp reference tree; this
// file only adds WAV I/O, packet-loss simulation and timing.
//
// Build: see build.sh

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <vector>

#include "Engine/Source/ComSat/ComSatSpirit.h"
#include "Engine/Source/ComSat/SPIRIT/ipmr.h"

namespace {

constexpr int kSampleRate = 8000;
constexpr int kPcmBytesPerFrame = 1600;      // 100 ms, 16-bit mono
constexpr int kPcmBytesPerSubframe = 320;    // 20 ms
constexpr int kSubframesPerFrame = 5;
constexpr int kMaxPacketBytes = 128;         // client: encoded[128], bits starts at 1024

struct Wav {
    int sampleRate = 0;
    int channels = 0;
    int bitsPerSample = 0;
    std::vector<int16_t> samples;
};

uint32_t rd32(const uint8_t* p) { return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
uint16_t rd16(const uint8_t* p) { return uint16_t(p[0] | (p[1] << 8)); }

bool readWav(const char* path, Wav& out) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return false; }
    std::vector<uint8_t> buf;
    uint8_t tmp[65536];
    size_t n;
    while ((n = fread(tmp, 1, sizeof(tmp), f)) > 0) buf.insert(buf.end(), tmp, tmp + n);
    fclose(f);

    if (buf.size() < 44 || memcmp(buf.data(), "RIFF", 4) || memcmp(buf.data() + 8, "WAVE", 4)) {
        fprintf(stderr, "%s: not a RIFF/WAVE file\n", path);
        return false;
    }

    size_t pos = 12;
    bool haveFmt = false;
    while (pos + 8 <= buf.size()) {
        const char* id = reinterpret_cast<const char*>(buf.data() + pos);
        uint32_t len = rd32(buf.data() + pos + 4);
        size_t body = pos + 8;
        if (body + len > buf.size()) len = static_cast<uint32_t>(buf.size() - body);

        if (!memcmp(id, "fmt ", 4) && len >= 16) {
            out.channels = rd16(buf.data() + body + 2);
            out.sampleRate = int(rd32(buf.data() + body + 4));
            out.bitsPerSample = rd16(buf.data() + body + 14);
            haveFmt = true;
        } else if (!memcmp(id, "data", 4)) {
            if (!haveFmt) { fprintf(stderr, "%s: data before fmt\n", path); return false; }
            if (out.bitsPerSample != 16 || out.channels != 1) {
                fprintf(stderr, "%s: need 16-bit mono, got %d-bit %d ch\n", path, out.bitsPerSample, out.channels);
                return false;
            }
            size_t count = len / 2;
            out.samples.resize(count);
            memcpy(out.samples.data(), buf.data() + body, count * 2);
        }
        pos = body + len + (len & 1);
    }

    if (out.samples.empty()) { fprintf(stderr, "%s: no samples\n", path); return false; }
    return true;
}

void put32(std::vector<uint8_t>& v, uint32_t x) { for (int i = 0; i < 4; ++i) v.push_back(uint8_t(x >> (8 * i))); }
void put16(std::vector<uint8_t>& v, uint16_t x) { v.push_back(uint8_t(x & 0xFF)); v.push_back(uint8_t(x >> 8)); }

bool writeWav(const char* path, const std::vector<int16_t>& samples, int sampleRate) {
    std::vector<uint8_t> v;
    uint32_t dataBytes = uint32_t(samples.size() * 2);
    v.insert(v.end(), {'R', 'I', 'F', 'F'});
    put32(v, 36 + dataBytes);
    v.insert(v.end(), {'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
    put32(v, 16);
    put16(v, 1);                      // PCM
    put16(v, 1);                      // mono
    put32(v, uint32_t(sampleRate));
    put32(v, uint32_t(sampleRate * 2));
    put16(v, 2);
    put16(v, 16);
    v.insert(v.end(), {'d', 'a', 't', 'a'});
    put32(v, dataBytes);
    const uint8_t* p = reinterpret_cast<const uint8_t*>(samples.data());
    v.insert(v.end(), p, p + dataBytes);

    FILE* f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "cannot write %s\n", path); return false; }
    fwrite(v.data(), 1, v.size(), f);
    fclose(f);
    return true;
}

double nowNs() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return double(ts.tv_sec) * 1e9 + double(ts.tv_nsec);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr,
            "usage: %s <in16k8000.wav> <out.wav> <csv|-> [dropEveryNthPacket]\n"
            "  drop 0 = no loss; 10 drops every 10th packet\n", argv[0]);
        return 2;
    }

    const char* inPath = argv[1];
    const char* outPath = argv[2];
    const char* csvPath = argv[3];
    int dropEvery = (argc > 4) ? atoi(argv[4]) : 0;

    Wav in;
    if (!readWav(inPath, in)) return 1;
    if (in.sampleRate != kSampleRate) {
        fprintf(stderr, "%s: expected %d Hz, got %d Hz (resample first)\n", inPath, kSampleRate, in.sampleRate);
        return 1;
    }

    // tables and codec state, plus 16 bytes so Init/encode can align like the client does
    std::vector<uint8_t> tables(sizeof(SPIRIT_IPMR_TABLES) + 16, 0);
    std::vector<uint8_t> encoderState(sizeof(SPIRIT_IPMR_STATE) + 16, 0);
    std::vector<uint8_t> decoderState(sizeof(SPIRIT_IPMR_STATE) + 16, 0);

    if (SPIRIT_IP_MR_V3_1_GenerateTables(tables.data())) {
        fprintf(stderr, "GenerateTables failed\n");
        return 1;
    }
    if (SPIRIT_IP_MR_V3_1_Init(encoderState.data(), tables.data())) {
        fprintf(stderr, "encoder Init failed\n");
        return 1;
    }
    if (SPIRIT_IP_MR_V3_1_Init(decoderState.data(), tables.data())) {
        fprintf(stderr, "decoder Init failed\n");
        return 1;
    }

    const size_t frameCount = in.samples.size() / (kPcmBytesPerFrame / 2);
    std::vector<int16_t> out(in.samples.size(), 0);

    double encodeNs = 0.0;
    double decodeNs = 0.0;
    size_t totalBits = 0;
    size_t packets = 0;
    size_t dropped = 0;
    int minBits = 1 << 30;
    int maxBits = 0;

    std::vector<uint8_t> packet(kMaxPacketBytes, 0);
    SPIRIT_IPMR_PARAMS params;
    params.unk_0000 = 0;
    params.unk_0004 = 0;
    params.unk_0006 = 1;

    for (size_t f = 0; f < frameCount; ++f) {
        const uint8_t* pcmIn = reinterpret_cast<const uint8_t*>(in.samples.data()) + f * kPcmBytesPerFrame;

        memset(packet.data(), 0, packet.size());
        SPIRIT_IPMR_STREAM encStream;
        encStream.m_data = packet.data();
        encStream.m_bits = 0;
        encStream.m_size = kMaxPacketBytes;

        SPIRIT_IPMR_INFO info;
        memset(&info, 0, sizeof(info));

        double t0 = nowNs();
        int32_t result = 0;
        for (int sub = 0; sub < kSubframesPerFrame; ++sub) {
            result = SPIRIT_IP_MR_V3_1_Encode(encoderState.data(), pcmIn + sub * kPcmBytesPerSubframe,
                &params, &encStream, &info);
            if (result) break;
        }
        double t1 = nowNs();
        encodeNs += t1 - t0;

        if (result) { fprintf(stderr, "encode failed on frame %zu\n", f); return 1; }

        const uint32_t bits = encStream.m_bits;
        uint32_t bytes = bits >> 3;
        if (bits & 7) ++bytes;

        totalBits += bits;
        ++packets;
        if (int(bits) < minBits) minBits = int(bits);
        if (int(bits) > maxBits) maxBits = int(bits);

        if (csvPath && strcmp(csvPath, "-")) {
            // written once at the end, see below
        }

        const bool lose = dropEvery > 0 && ((f % size_t(dropEvery)) == size_t(dropEvery - 1));

        int16_t* pcmOut = out.data() + f * (kPcmBytesPerFrame / 2);
        SPIRIT_IPMR_STREAM decStream;
        decStream.m_data = packet.data();
        decStream.m_bits = 0;
        decStream.m_size = bytes;

        double t2 = nowNs();
        if (lose) {
            ++dropped;
            // the client never calls the codec with the lost flag: a packet that
            // does not arrive leaves an empty jitter buffer slot, which is played
            // as silence. Building without -DIPMR_PLC models exactly that.
            for (int sub = 0; sub < kSubframesPerFrame; ++sub) {
#ifdef IPMR_PLC
                SPIRIT_IP_MR_V3_1_Decode(decoderState.data(), reinterpret_cast<uint8_t*>(pcmOut), &params, &decStream, 1);
#else
                memset(pcmOut, 0, kPcmBytesPerSubframe);
#endif
                pcmOut += kPcmBytesPerSubframe / 2;
            }
        } else {
            while (bits - decStream.m_bits >= 72) {
                if (SPIRIT_IP_MR_V3_1_Decode(decoderState.data(), reinterpret_cast<uint8_t*>(pcmOut), &params, &decStream, 0)) break;
                pcmOut += kPcmBytesPerSubframe / 2;
            }
        }
        double t3 = nowNs();
        decodeNs += t3 - t2;
    }

    if (!writeWav(outPath, out, kSampleRate)) return 1;

    const double seconds = double(in.samples.size()) / kSampleRate;
    fprintf(stderr, "frames=%zu packets=%zu dropped=%zu minBits=%d maxBits=%d\n", frameCount, packets, dropped, minBits, maxBits);
    fprintf(stderr, "payload bytes/s=%.1f  bitrate=%.1f kbit/s (payload only, no 7-byte header)\n",
        double(totalBits / 8) / seconds, double(totalBits) / seconds / 1000.0);
    fprintf(stderr, "wire bitrate including 7-byte header and UDP/IPv4 overhead: %.1f kbit/s\n",
        double(totalBits) / seconds / 1000.0 + (packets * (7.0 + 8.0 + 20.0) * 8.0) / seconds / 1000.0);
    fprintf(stderr, "encode=%.1f us/frame  decode=%.1f us/frame\n", encodeNs / double(frameCount) / 1000.0,
        decodeNs / double(frameCount) / 1000.0);

    if (csvPath && strcmp(csvPath, "-")) {
        FILE* csv = fopen(csvPath, "w");
        if (csv) {
            const double wireKbps = double(totalBits) / seconds / 1000.0 +
                (packets * (7.0 + 8.0 + 20.0) * 8.0) / seconds / 1000.0;
            fprintf(csv, "metric,value\n");
            fprintf(csv, "packets,%zu\n", packets);
            fprintf(csv, "seconds,%.3f\n", seconds);
            fprintf(csv, "bits_total,%zu\n", totalBits);
            fprintf(csv, "min_bits,%d\n", minBits);
            fprintf(csv, "max_bits,%d\n", maxBits);
            fprintf(csv, "max_packet_bytes,%d\n", (maxBits + 7) / 8);
            fprintf(csv, "bitrate_kbps_payload,%.2f\n", double(totalBits) / seconds / 1000.0);
            fprintf(csv, "bitrate_kbps_wire,%.2f\n", wireKbps);
            fprintf(csv, "encode_us_per_frame,%.2f\n", encodeNs / double(frameCount) / 1000.0);
            fprintf(csv, "decode_us_per_frame,%.2f\n", decodeNs / double(frameCount) / 1000.0);
            fclose(csv);
        }
    }
    return 0;
}
