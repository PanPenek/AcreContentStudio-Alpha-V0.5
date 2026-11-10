# Reference research: Dr. Yuima, Seidon, and the "Sinaboto" format (2026-10-31)

Sources: 12 reels downloaded and analysed with yt-dlp, faster-whisper and ffmpeg scdet. The top Yuima and Seidon reels were
picked by view count from each profile's reels grid, plus a low-view reel from each channel for contrast. Raw data is in `research/refs/<channel>/<code>/`
(`sheet.jpg`, `analysis.json`, frames) and the numbers are in `research/refs/summary.json`.

## Who they are
- **@yuimasensei (Dr. Yuima)**: medical explainers. Top reels: 212K (awake brain surgery), 125K (carrots turn you orange),
  74.6K (hand sewn to ankle), 63.6K (nose grown on forehead), 56.1K. Low: 8.7K (snake antivenom).
- **@drinkseidon (Seidon hydration)**: a water brand doing history/survival explainers that end on water. Top: 78.3K
  (solar still on an island), 28K (Persian yakhchal desert ice), 20.5K (myth vs fact). Low: ~500 (optogenetics news).
- **Both credit "Original Neto model created by evanciao"**: they reuse one purchased low-poly, pixel-textured anime model.
  The look comes from the character asset, not from Blender tricks.

## Narrative (what separates the winners from the flops)
Winners use a **second-person problem chain**:
> "Good morning doctor. Your patient … So you X. But Y. So you Z. **This is <term>.** … Diagnosis complete, doctor."
> "You're stranded on an island … So you dig a hole … But the drops fall back … So you … **You see**, <science>. And by sunset, you take your first sip."

- Hook = an absurd but true outcome in the title ("Doctor, this is why we sewed his hand to his ankle").
- Each "But" adds a new obstacle and each "So you" a fix. The jargon term lands as the reward ("This is a forehead flap").
- Closing twist or reveal, then a fixed sign-off line. Seidon closes on a water callback.
- Both flops are third-person, news-style lists. **Avoid the host-lecture format** ("Lesson one…"): that's what ep01 did.

| | Yuima | Seidon | our ep01 |
|---|---|---|---|
| length | 63–87 s | 37–45 s | 68.7 s |
| words/sec | 2.2–2.4 | 2.3–3.0 | 2.7 |
| avg shot | 3–5 s | 1.6–2.2 s | 3.8 s |
| captions | ONE word, UPPERCASE, white pixel font + black outline, centre-low | short lowercase phrase, small pixel font, low centre | one word uppercase (OK) |

## Visual language
- **Character**: low-poly, flat colours, **pixel-art textures with a small palette** (an eye is ~40 texels across in an extreme
  close-up, the iris has 3–4 flat shades, no gradients). Faces are texture, not geometry. Yuima has no mesh outline; the
  Astolfo reference does have one, so we keep it.
- **Shots**: extreme face close-ups, prop/organ close-ups, x-ray see-through body overlays, CCTV "REC" frames, monitor UIs,
  a clipboard with a "COMPLETE" stamp, many locations per video (kitchen, ward, arctic, tower). The character acts out the story.
- **Overlays**: a top-left HUD counter in a yellow pixel font ("CARROTS: 14", "DAY 21", "SURGERY: 10H"), a progress bar HUD,
  **yellow labels with a leader line pointing at the object** ("LIVER——", "BETA-CAROTENE"), comic SFX bubbles ("GULP!"),
  orange label boxes on the scene (Seidon: "HEAT", "SHADE").
- **Environments (Seidon)**: pixel-art skies (banded gradient, pixel clouds, pixel sun with rays), sand with pixel noise,
  brick textures, a tiled flat ocean. Mostly flat, bright lighting.

## Changes made in Acre Blender Studio
1. Character: rebuilt from the user's Astolfo reference. Qwen-Edit-2511 makes a T-pose, image-to-3D runs (TRELLIS.2 / Pixal3D, native ComfyUI),
   the texture is palette-quantised to pixel art, and the face is a swappable pixel sprite (blink, talk, wink, happy).
2. Pixel pass: `abs_common.pixelize()` (box downscale + k-means palette) on every character texture.
3. Script Writer prompt switched to the second-person problem chain. Shots ≤ 3 s, labels point at objects, HUD counter.
4. New beat fields: `hud` (top-left counter), `point` (yellow label + leader line at a 3D target), `bubble` (SFX word at a target).
