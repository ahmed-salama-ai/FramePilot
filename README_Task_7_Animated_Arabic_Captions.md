# 7 Animated Arabic captions

## Summary

Task 7 extends FramePilot's existing caption settings and renderer with two optional styles:

- **Pop** scales the currently spoken word from 100% to 130% over 180 ms.
- **Karaoke** smoothly changes the current spoken word to the configured highlight color over 120 ms.

The existing **Default** style remains the default. The implementation uses the existing transcript, caption layout, ASS subtitle generation, FFmpeg rendering, and per-session brand settings. It does not add a transcription system or a separate caption pipeline.

## User settings and persistence

The caption settings include a **Caption Animation Style** selector with `Default`, `Pop`, and `Karaoke`. The frontend reads the selected value, sends it through the existing brand-settings request, and restores it when loading the settings.

The value is validated by `CaptionStyle.animation_style` in `ai_director/common/schemas.py` and saved in the session's `brand.json` under `captions.animation_style`. Existing brand files without this field use `default`, so their previous appearance is preserved. Settings are stored per session.

To apply a saved style to a finished video, use the existing **Update video** action. It creates a new version and keeps the previous version.

## Rendering behavior

`ai_director/director/render.py` uses the existing caption items and their word-level start and end times. `word_steps` creates caption events at those actual boundaries:

- **Pop** applies an ASS scale transform to only the word active in that time span. Other words keep the normal caption scale.
- **Karaoke** applies a short ASS color transition to the active word, using the configured word color.
- **Default** retains the existing caption behavior.

No equal-duration timing is estimated and no artificial word timestamps are generated. If a caption does not have word timings that match its text, it remains static rather than animating the entire sentence or fabricating word timing.

## Arabic and mixed-language text

The implementation keeps the existing ASS rendering and font selection: Arial on Windows and Noto Naskh Arabic on other platforms. It retains the existing right-to-left encoding and Arabic right-to-left marks supplied by the caption layout. The text is not manually reversed or reshaped.

Animation tags wrap only the active word and reset before the rest of the line. The original Arabic, English, punctuation, and numbers remain in their original text order so the existing text renderer can handle mixed-direction text.

## Changed files

| File | Change |
|---|---|
| `ai_director/common/schemas.py` | Adds the validated animation-style setting, defaulting to `default`. |
| `ai_director/director/render.py` | Adds word-timed Pop and Karaoke ASS events to the existing renderer. Captions without word timings stay static. |
| `app/templates/brand_form.html` | Adds the style selector to the existing caption settings. |
| `app/static/brand.js` | Reads, saves, and restores the selected style through the existing brand-settings flow. |
| `app/static/i18n.js` | Adds Arabic and English labels for the selector and its options. |
| `app/main.py` | Includes the new setting in the existing brand-settings schema description. |

## Verification and limitations

- The project test suite passed: **230 passed**.
- Python compilation completed successfully for `ai_director` and `app`.
- ASS generation was smoke-checked against the saved `s03` transcript with Pop and Karaoke selected; each generated the expected animation tags.
- A new full-length video render and a visual review of all font, screen-size, punctuation, and mixed-direction cases were not performed as part of this final code review. Review a newly updated video in the target environment before presenting it as final visual proof.
- Word-level animation requires usable word timings from the existing transcript. When those timings are missing or do not align with the caption text, the caption is intentionally left static.
