# Provenance and licensing

## Code and page

The page and the measurement harness in `tools/` are provided as-is for the discussion
of voice chat in World of Warcraft 3.3.5a private servers.

## Spirit IPMR

The 3.3.5a client's voice codec is not included in this repository. `tools/build.sh`
compiles against a decompiled client checkout pointed at by `DECOMP`, reading that tree
without modifying it. The decompilation is not the work of this repository.

## Speech corpus

The audio clips under `assets/clips/` are derived from the **Open Speech Repository**
American English recordings, published for VoIP codec testing:

    http://www.voiptroubleshooter.com/open_speech/american.html

Specifically `OSR_us_000_0010_8k.wav`, cut to a ten second window, loudness-normalised,
and re-encoded. See the source page for the terms that apply to those recordings.

## LibriSpeech

All clips under `assets/clips/` are derived from four utterances of **LibriSpeech**
dev-clean (OpenSLR SLR12, https://www.openslr.org/12/), read English speech at 16 kHz,
licensed under Creative Commons Attribution 4.0. Each is cut to an eight second window,
loudness-normalised and re-encoded; they are not the original files.

## Opus

Opus is used through libopus (Xiph.Org / IETF RFC 6716), licensed under BSD. The page
links no third-party assets and loads nothing from a CDN.

## Game names and trademarks

World of Warcraft and the related names and logos are trademarks of Blizzard
Entertainment. This page is an independent technical comparison and is not affiliated
with or endorsed by Blizzard.
