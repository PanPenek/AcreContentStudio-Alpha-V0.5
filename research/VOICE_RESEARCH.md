# Local TTS research for the host voice (2026-10-31)

Goal: a unique, cute anime-host English voice with per-line emotion, usable on a monetized channel, running on the RTX 3090.
Current engine: edge-tts (`en-US-AvaNeural` +12 Hz). It's an unofficial client for Microsoft's Edge read-aloud service: stock voice, little emotion control, and no clear commercial terms.

## Blind-listening ranking (Artificial Analysis, open-weights board, fetched 2026-10-31)
| # | Model | Elo | Weights license | Usable for us |
|---|---|---|---|---|
| 1 | Fish Audio Drama 3 | 1278 | fish-audio-research-license | no (research only) |
| 3 | Breeze TTS 2 | 1228 | non-commercial weights | no |
| 4 | **Ming-3.0-tts** (inclusionAI) | **1187** | **MIT** | **yes: highest-rated commercial-OK model** |
| 5 | Fish Audio S2 Pro | 1109 | research | no |
| 7 | Voxtral TTS (Mistral) | 1090 | CC-BY-NC-4.0 | no |
| 8 | Magpie Multilingual 357M | 1067 | NVIDIA Open Model | yes, but 5 stock voices, no design |
| 9 | Kokoro 82M | 1062 | Apache-2.0 | yes, but no cloning/design |
| 12 | Higgs Audio V3 | 1039 | Boson research/non-commercial | no |
| 13 | Chatterbox | 1024 | MIT (watermarks output) | yes |
Qwen3-TTS, VoxCPM2 and OmniVoice are not on this board.

## Shortlist (commercial-OK, voice design + cloning + emotion)
1. **Ming-3.0-tts 0.5B / tiny** (MIT, released Oct 2026). Voice Design from text, zero-shot clone, explicit
   emotion/speed/pitch/volume, 14 inline tags (laugh, sigh, breath, surprise, hesitation...), 44.1 kHz, EN+JA+5 more.
   Comfy-Org repackaged `ming3_tts_tiny_int8_convrot` (2026-10-28), so native ComfyUI support is arriving; the local
   ComfyUI has no Ming TTS node yet (needs an update). The official repo is tested on Linux H800/H20 only, so Windows is unverified.
2. **Qwen3-TTS 1.7B VoiceDesign + Base** (Apache-2.0, 3.4M downloads). Text-described voices, 3 s cloning,
   natural-language emotion direction; reviewers note its female voices sound "slightly breathy, stylized, anime-like",
   which suits us. Some users find it flat with poor clone samples (Darwin-TTS is a more expressive fine-tune).
   **Already wired into the local ComfyUI** (CCTech nodes: VoiceDesign / VoiceClone / SaveVoice / RoleBank). The weights
   folders are empty, about 4.5 GB to download.
3. **VoxCPM2 2B** (Apache-2.0, 1M downloads). Voice design via "(description)text", controllable cloning, 48 kHz,
   30 languages including **Polish**. RTF about 0.3 on a 4090.

Not for us: Irodori-TTS-Anime (Japanese only), Kokoro (no custom voice), Breeze/Fish/Voxtral/Higgs (licenses).

## Recommendation
Run a bake-off: design the same voice description on Ming-3.0, Qwen3-TTS and VoxCPM2, render the same 4 ep01 lines
(neutral, excited, whisper, laugh), and let Patryk pick by ear. Lock the winner as a saved reference clip, clone it for
every episode, and keep edge-tts as the fallback.

Sources: artificialanalysis.ai/text-to-speech/leaderboard/provider-voice/open-weights; HF model cards
(inclusionAI/Ming-3.0-tts-0.5B, Comfy-Org/Ming-3.0-TTS, Qwen/Qwen3-TTS-12Hz-1.7B-*, openbmb/VoxCPM2, BreezeBlue/Breeze-TTS-2,
fishaudio/drama-3, bosonai/higgs-tts-3-4b, mistralai/Voxtral-4B-TTS-2603); cartesia.ai/learn/open-source-tts;
texttolab.com/blog/qwen3-tts-review; r/LocalLLaMA "What TTS models do you recommend as today?" (Sep 2026).
