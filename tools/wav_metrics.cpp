// Small objective comparison helper for the voice-codec preview.
//
// Split across two commands:
//   wav_metrics snr  <ref8k.wav> <deg8k.wav>   -> SNR, segmental SNR, log-spectral distance
//   wav_metrics band <file.wav>                -> energy share per frequency band
//
// "snr" needs both files at 8000 Hz mono 16-bit, so that every candidate is
// compared inside the band the old codec can actually represent. "band" runs at
// the file's own rate and exists to show how much of the spectrum a candidate keeps.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

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
            if (!haveFmt) return false;
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
    return !out.samples.empty();
}

void fft(std::vector<double>& re, std::vector<double>& im) {
    const size_t n = re.size();
    for (size_t i = 1, j = 0; i < n; ++i) {
        size_t bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { std::swap(re[i], re[j]); std::swap(im[i], im[j]); }
    }
    for (size_t len = 2; len <= n; len <<= 1) {
        const double ang = -2.0 * M_PI / double(len);
        const double wRe = std::cos(ang);
        const double wIm = std::sin(ang);
        for (size_t i = 0; i < n; i += len) {
            double curRe = 1.0;
            double curIm = 0.0;
            for (size_t k = 0; k < len / 2; ++k) {
                const double uRe = re[i + k];
                const double uIm = im[i + k];
                const double vRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm;
                const double vIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe;
                re[i + k] = uRe + vRe;
                im[i + k] = uIm + vIm;
                re[i + k + len / 2] = uRe - vRe;
                im[i + k + len / 2] = uIm - vIm;
                const double nextRe = curRe * wRe - curIm * wIm;
                curIm = curRe * wIm + curIm * wRe;
                curRe = nextRe;
            }
        }
    }
}

// mean squared power of a 16-bit window, in dBFS-ish units
double framePowerDb(const std::vector<int16_t>& s, size_t start, size_t count) {
    double sum = 0.0;
    for (size_t i = 0; i < count; ++i) {
        const double v = double(s[start + i]);
        sum += v * v;
    }
    const double rms = std::sqrt(sum / double(count));
    return 20.0 * std::log10(rms + 1e-9);
}

int runSnr(const Wav& ref, const Wav& deg) {
    if (ref.sampleRate != 8000 || deg.sampleRate != 8000) {
        fprintf(stderr, "snr needs both files at 8000 Hz (got %d and %d)\n", ref.sampleRate, deg.sampleRate);
        return 2;
    }
    const size_t n0 = std::min(ref.samples.size(), deg.samples.size());
    if (!n0) { fprintf(stderr, "empty input\n"); return 2; }

    // Both codecs add algorithmic delay and the two are not wired in the same
    // order, so the decoded file is shifted against the reference. Find the shift
    // that lines them up, otherwise SNR just measures the offset.
    const int decim = 4;
    const size_t dn = n0 / decim;
    std::vector<double> dr(dn, 0.0);
    std::vector<double> dd(dn, 0.0);
    for (size_t i = 0; i < dn; ++i) {
        double sr = 0.0;
        double sd = 0.0;
        for (int k = 0; k < decim; ++k) {
            sr += double(ref.samples[i * decim + k]);
            sd += double(deg.samples[i * decim + k]);
        }
        dr[i] = sr / decim;
        dd[i] = sd / decim;
    }

    // search +/- 1 second at 2 kHz
    const long maxLag = long(2 * 8000 / decim);
    long best = 0;
    double bestScore = -1e300;
    for (long lag = -maxLag; lag <= maxLag; ++lag) {
        double score = 0.0;
        for (size_t i = 0; i + size_t(labs(lag)) < dn; i += 2) {
            const size_t a = i;
            const size_t b = (lag >= 0) ? i + size_t(lag) : i;
            const size_t r = (lag >= 0) ? i : i + size_t(-lag);
            if (r >= dn) break;
            score += dr[r] * dd[b];
        }
        if (score > bestScore) { bestScore = score; best = lag; }
    }
    const long lag = best * decim;
    const size_t n = n0 - size_t(labs(lag));

    auto refAt = [&](size_t i) { return (lag >= 0) ? ref.samples[i] : ref.samples[i + size_t(-lag)]; };
    auto degAt = [&](size_t i) { return (lag >= 0) ? deg.samples[i + size_t(lag)] : deg.samples[i]; };

    double sigEnergy = 0.0;
    double errEnergy = 0.0;
    for (size_t i = 0; i < n; ++i) {
        const double a = double(refAt(i));
        const double b = double(degAt(i));
        sigEnergy += a * a;
        errEnergy += (a - b) * (a - b);
    }
    const double globalSnr = 10.0 * std::log10((sigEnergy + 1e-12) / (errEnergy + 1e-12));

    // segmental SNR over speech-only 20 ms segments
    const size_t segLen = 160;
    double segSum = 0.0;
    size_t segCount = 0;
    for (size_t start = 0; start + segLen <= n; start += segLen) {
        double s = 0.0;
        for (size_t i = 0; i < segLen; ++i) {
            const double a = double(refAt(start + i));
            s += a * a;
        }
        const double segDb = 10.0 * std::log10(s / double(segLen) + 1e-12);
        if (segDb < -45.0) continue;  // skip pauses
        double e = 0.0;
        for (size_t i = 0; i < segLen; ++i) {
            const double d = double(refAt(start + i)) - double(degAt(start + i));
            e += d * d;
        }
        segSum += 10.0 * std::log10((s + 1e-12) / (e + 1e-12));
        ++segCount;
    }
    const double segSnr = segCount ? segSum / double(segCount) : 0.0;

    // log-spectral distance over the 0-4 kHz band
    const size_t fftSize = 512;  // 64 ms
    std::vector<double> re(fftSize);
    std::vector<double> im(fftSize);
    std::vector<double> window(fftSize);
    for (size_t i = 0; i < fftSize; ++i) window[i] = 0.5 - 0.5 * std::cos(2.0 * M_PI * double(i) / double(fftSize));

    double lsdSum = 0.0;
    size_t lsdCount = 0;
    std::vector<double> refDb(fftSize / 2);
    std::vector<double> degDb(fftSize / 2);
    for (size_t start = 0; start + fftSize <= n; start += fftSize) {
        double refPower = 0.0;
        for (size_t i = 0; i < fftSize; ++i) {
            const double a = double(refAt(start + i));
            refPower += a * a;
        }
        if (10.0 * std::log10(refPower / double(fftSize) + 1e-12) < -50.0) continue;

        for (int pass = 0; pass < 2; ++pass) {
            for (size_t i = 0; i < fftSize; ++i) {
                re[i] = (pass ? double(degAt(start + i)) : double(refAt(start + i))) * window[i];
                im[i] = 0.0;
            }
            fft(re, im);
            for (size_t k = 1; k < fftSize / 2; ++k) {
                const double mag = std::sqrt(re[k] * re[k] + im[k] * im[k]);
                (pass ? degDb : refDb)[k] = std::max(20.0 * std::log10(mag + 1e-6), -90.0);
            }
        }

        double acc = 0.0;
        for (size_t k = 1; k < fftSize / 2; ++k) {
            const double d = refDb[k] - degDb[k];
            acc += d * d;
        }
        lsdSum += std::sqrt(acc / double(fftSize / 2 - 1));
        ++lsdCount;
    }
    const double lsdDb = lsdCount ? lsdSum / double(lsdCount) : 0.0;

    printf("lag_ms,%.2f\n", double(lag) / 8.0);
    printf("snr_db,%.2f\n", globalSnr);
    printf("segsnr_db,%.2f\n", segSnr);
    printf("lsd_db,%.2f\n", lsdDb);
    printf("seconds,%.2f\n", double(n) / 8000.0);
    return 0;
}

int runBand(const Wav& w) {
    const size_t fftSize = 2048;
    if (w.samples.size() < fftSize) { fprintf(stderr, "file too short\n"); return 2; }

    const int bands[4] = {0, 4000, 8000, 16000};  // Hz edges: <4k, 4-8k, 8-16k, >16k
    double energy[4] = {0, 0, 0, 0};
    std::vector<double> re(fftSize);
    std::vector<double> im(fftSize);

    for (size_t start = 0; start + fftSize <= w.samples.size(); start += fftSize) {
        for (size_t i = 0; i < fftSize; ++i) {
            re[i] = double(w.samples[start + i]);
            im[i] = 0.0;
        }
        fft(re, im);
        for (size_t k = 1; k < fftSize / 2; ++k) {
            const double hz = double(k) * double(w.sampleRate) / double(fftSize);
            const double mag2 = re[k] * re[k] + im[k] * im[k];
            int band = 3;
            if (hz < bands[1]) band = 0;
            else if (hz < bands[2]) band = 1;
            else if (hz < bands[3]) band = 2;
            energy[band] += mag2;
        }
    }

    const double total = energy[0] + energy[1] + energy[2] + energy[3] + 1e-12;
    printf("rate_hz,%d\n", w.sampleRate);
    printf("share_0_4k,%.4f\n", energy[0] / total);
    printf("share_4_8k,%.4f\n", energy[1] / total);
    printf("share_8_16k,%.4f\n", energy[2] / total);
    printf("share_16k_plus,%.4f\n", energy[3] / total);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s snr <ref8k.wav> <deg8k.wav>\n       %s band <file.wav>\n", argv[0], argv[0]);
        return 2;
    }

    Wav a;
    if (!readWav(argv[2], a)) return 1;

    if (!strcmp(argv[1], "band")) return runBand(a);
    if (!strcmp(argv[1], "snr")) {
        if (argc < 4) { fprintf(stderr, "snr needs two files\n"); return 2; }
        Wav b;
        if (!readWav(argv[3], b)) return 1;
        return runSnr(a, b);
    }

    fprintf(stderr, "unknown command %s\n", argv[1]);
    return 2;
}
