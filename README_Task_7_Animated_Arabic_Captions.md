# 7 Animated Arabic captions

## Summary

Task 7 extends FramePilot's existing caption settings and renderer with two optional styles:

- **Pop** scales the currently spoken word from 100% to 115% over 180 ms.
- **Karaoke** progressively highlights spoken words in the brand highlight color using discrete word-level ASS events. Spoken words remain filled in the highlight color while upcoming words stay in base text color.

The existing **Default** style remains the default. The implementation uses the existing transcript, caption layout, ASS subtitle generation, FFmpeg rendering, and per-session brand settings. It does not add a transcription system or a separate caption pipeline.

## User settings and persistence

The caption settings include a **Caption Animation Style** selector with `Default`, `Pop`, and `Karaoke`. The frontend reads the selected value, sends it through the existing brand-settings request, and restores it when loading the settings.

The value is validated by `CaptionStyle.animation_style` in `ai_director/common/schemas.py` and saved in the session's `brand.json` under `captions.animation_style`. Existing brand files without this field use `default`, so their previous appearance is preserved. Settings are stored per session.

To apply a saved style to a finished video, use the existing **Update video** action. It creates a new version and keeps the previous version.

## Rendering behavior

`ai_director/director/render.py` uses the existing caption items and their word-level start and end times:

- **Pop** applies an ASS scale transform to only the word active in that time span. Other words keep the normal caption scale. The 115% maximum limits line movement and overflow.
- **Karaoke** progressively highlights each spoken word in the brand highlight color matching the word timestamps from the transcript, keeping spoken words filled across mid-caption pauses and keeping preceding lines in multi-line captions fully coloured while preserving full bidirectional text shaping, RTL word order, and spacing.
- **Default** retains the existing caption behavior.

No equal-duration timing is estimated and no artificial word timestamps are generated. If a caption does not have word timings that match its text, it remains static rather than animating the entire sentence or fabricating word timing.
Karaoke and Pop render bilingual lines seamlessly as a block, keeping untimed lines in their base color.

## Arabic and mixed-language text

The implementation keeps the existing ASS rendering and font selection: Arial on Windows and Noto Naskh Arabic on other platforms. It retains the existing right-to-left encoding and Arabic right-to-left marks supplied by the caption layout. The text is not manually reversed or reshaped.

Pop and Karaoke animation tags preserve word boundaries and spacing without breaking Arabic cursive connections. Spoken words in Karaoke stay filled in the highlight color. The original Arabic, English, punctuation, and numbers remain in their natural reading order; strings are not manually reversed.

## Changed files

| File | Change |
| --- | --- |
| `ai_director/common/schemas.py` | Adds the validated animation-style setting, defaulting to `default`. |
| `ai_director/director/render.py` | Adds word-timed Pop and cumulative Karaoke ASS events to the existing renderer. Captions without word timings stay static. |
| `app/templates/brand_form.html` | Adds the style selector to the existing caption settings. |
| `app/static/brand.js` | Reads, saves, and restores the selected style through the existing brand-settings flow. |
| `app/static/i18n.js` | Adds Arabic and English labels for the selector and its options. |
| `app/main.py` | Includes the new setting in the existing brand-settings schema description. |
| `tests/test_caption_render.py` | Checks Pop scale tags, cumulative Karaoke word timing, vertical (9:16) rendering, and unchanged Default caption text. |
| `docs/task7-evidence/` | Contains visual acceptance screenshots (16:9 and 9:16 for numbers, mixed Arabic/English, and longest line) and a ten-word audio vs caption timing spot-check. |

## Verification and limitations

- The full test suite passed: **234 passed** (`pytest`).
- Focused caption-render tests cover Pop tags, cumulative Karaoke word timing, vertical (9:16) play resolutions, and Default regressions.
- Complete visual acceptance screenshots and audio timing spot-check are documented in [`docs/task7-evidence`](docs/task7-evidence/README.md).
- Word-level animation requires usable word timings from the existing transcript. When those timings are missing or do not align with the caption text, the caption is intentionally left static.
