# Task 7 acceptance evidence

These are 60-second visual samples rendered from the existing `s03` transcript and word timings over a neutral background. They include Arabic, English, and the number `10`. The source recording and identifiable audio/video are not included in this PR.

| Style | 16:9 sample | 9:16 sample |
|---|---|---|
| Pop (115% word scale) | [pop_16x9.mp4](pop_16x9.mp4) | [pop_9x16.mp4](pop_9x16.mp4) |
| Karaoke (`\kf` timed fill) | [karaoke_16x9.mp4](karaoke_16x9.mp4) | [karaoke_9x16.mp4](karaoke_9x16.mp4) |

## Screenshots

The screenshots are extracted from the caption-only samples above, so no source video or audio is exposed.

At 27.4 seconds the caption contains `10`.

| Style | 16:9 | 9:16 |
|---|---|---|
| Pop, number | ![Pop 16:9 number](pop_16x9_27_4s.png) | ![Pop 9:16 number](pop_9x16_27_4s.png) |
| Karaoke, number | ![Karaoke 16:9 number](karaoke_16x9_27_4s.png) | ![Karaoke 9:16 number](karaoke_9x16_27_4s.png) |

At 29.8 seconds, the caption mixes Arabic with the English word `market`. These paired screenshots show the existing Default appearance and the Pop result:

| Default baseline | Pop result |
|---|---|
| ![Default baseline at 29.8 seconds](before_default_16x9_29_8s.png) | ![Pop at 29.8 seconds](pop_16x9_29_8s.png) |

Karaoke at the same timestamp:

| Style | 16:9 | 9:16 |
|---|---|---|
| Karaoke, mixed Arabic/English | ![Karaoke 16:9 mixed text](karaoke_16x9_29_8s.png) | ![Karaoke 9:16 mixed text](karaoke_9x16_29_8s.png) |

At 50.0 seconds the English translation is the longest line in this sample (72 characters). It stays inside the landscape frame and wraps within the portrait frame; the Arabic source line remains above it.

| Style | 16:9 | 9:16 |
|---|---|---|
| Pop, longest line | ![Pop 16:9 longest line](pop_16x9_50_0s.png) | ![Pop 9:16 longest line](pop_9x16_50_0s.png) |
| Karaoke, longest line | ![Karaoke 16:9 longest line](karaoke_16x9_50_0s.png) | ![Karaoke 9:16 longest line](karaoke_9x16_50_0s.png) |

## Ten-word timing spot-check

[`word-timing-spot-check.csv`](word-timing-spot-check.csv) compares ten spoken words, including the English word `market`, in the source audio interval with the generated ASS karaoke intervals. ASS stores karaoke durations in centiseconds, so each interval is quantized to 10 ms; all ten entries match the existing transcript word boundaries within that precision (0 ms for these timestamps).

The renderer uses the transcription's existing word timings; the spot-check confirms the ASS intervals against those audio-referenced transcript boundaries, not an independent speech-alignment model or human acoustic relabeling. The raw audio remains local because it contains an identifiable speaker, so this evidence does not claim an independent acoustic listening check.
