"""Ming-3.0-tts bridge (runs inside tools/Ming-3.0-tts/.venv; MIT-licensed model, local GPU).

Design a voice once (from a text description), then clone it for every line so the host always sounds the same:
  python tts_ming.py design <voice_dir> "<english voice description>" ["<sample sentence>"]
      -> <voice_dir>/ref.wav, ref.txt, voice.json
  python tts_ming.py synth <voice_dir> <jobs.json>
      jobs.json = [{"text": "...", "out": "x.wav", "emotion": "happy|sad|angry|surprised|fearful|disgusted|neutral|null"}]
  python tts_ming.py builtin <voice_dir> <ip> ["<sample sentence>"]   (e.g. ip US_Emma) -> same files as design
Inline tags in text pass through: [Laughter] [Sigh] [Breathing] [Surprise-ah] [Surprise-oh] [Uhm] ...
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MING = os.path.join(ROOT, "tools", "Ming-3.0-tts")
MODEL = os.environ.get("ABS_MING_MODEL", os.path.join(ROOT, "tools", "models", "Ming-3.0-tts-0.5B"))
sys.path.insert(0, MING)

EMO = {"happy": "高兴", "sad": "悲伤", "angry": "愤怒", "fearful": "恐惧", "disgusted": "厌恶", "surprised": "惊讶", "neutral": "中性"}
SAMPLE = "Hi hi! Today I'm going to show you something really cool, so stay with me until the end, okay?"


def load():
    os.chdir(MING)  # the repo resolves its own frontend assets relative to cwd
    from ming_tts import MingTTS
    t0 = time.time()
    m = MingTTS(MODEL)
    print(f"[ming] model loaded in {time.time() - t0:.1f}s", flush=True)
    return m


def save(wav, sr, path):
    import soundfile as sf
    import numpy as np
    a = wav.detach().cpu().float().numpy() if hasattr(wav, "detach") else np.asarray(wav)
    sf.write(path, a.reshape(-1), sr)


def sample_rate(m):
    for k in ("sample_rate", "sr", "sampling_rate"):
        v = getattr(m, k, None)
        if isinstance(v, int):
            return v
    return 44100


def write_voice(voice_dir, m, wav, text, meta):
    os.makedirs(voice_dir, exist_ok=True)
    save(wav, sample_rate(m), os.path.join(voice_dir, "ref.wav"))
    open(os.path.join(voice_dir, "ref.txt"), "w", encoding="utf-8").write(text)
    json.dump({**meta, "engine": "ming-3.0-tts-0.5b", "created": time.time()}, open(os.path.join(voice_dir, "voice.json"), "w"), indent=1)
    print("VOICE", voice_dir, flush=True)


def design(voice_dir, style, text=SAMPLE):
    m = load()
    wav = m.synthesize(task="VOICE_DESIGN", text=text, controls={"style": style}, use_zero_spk_emb=True, raw_text=True)
    write_voice(voice_dir, m, wav, text, {"style": style})


def builtin(voice_dir, ip, text=SAMPLE):
    m = load()
    wav = m.synthesize(task="IP", text=text, controls={"ip": ip}, raw_text=True)
    write_voice(voice_dir, m, wav, text, {"ip": ip})


def normalize(text):
    """pynini (Ming's normalizer) has no Windows wheels, so we send raw_text and spell numbers ourselves."""
    import re
    import inflect
    eng = inflect.engine()

    def year(m):
        n = m.group(0)
        if len(n) == 4 and 1000 <= int(n) <= 2099 and not n.endswith("00"):
            return eng.number_to_words(n[:2]) + " " + (eng.number_to_words(n[2:]) if n[2] != "0" else "oh " + eng.number_to_words(n[3]))
        return eng.number_to_words(n.replace(",", ""), andword="")
    text = re.sub(r"(\d+)%", lambda m: m.group(1) + " percent", text)
    text = re.sub(r"\d[\d,]*(\.\d+)?", year, text)
    return text.replace("&", " and ")


def synth(voice_dir, jobs_path):
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    ref = os.path.join(voice_dir, "ref.wav")
    ref_text = open(os.path.join(voice_dir, "ref.txt"), encoding="utf-8").read().strip()
    m = load()
    for k, j in enumerate(jobs):
        t0 = time.time()
        emo = EMO.get((j.get("emotion") or "").lower())
        common = dict(text=normalize(j["text"]), prompt_wav_path=ref, prompt_text=ref_text, use_spk_emb=True,
                      language_id="en", raw_text=True)
        try:
            if emo and emo != "中性":
                wav = m.synthesize(task="EMOTION", controls={"emotion": emo}, **common)
            else:
                wav = m.synthesize(task="TTS", **common)
        except Exception as e:  # emotion path failed for this line: plain clone
            print(f"[ming] line {k} emotion fallback: {e}", flush=True)
            wav = m.synthesize(task="TTS", **common)
        save(wav, sample_rate(m), j["out"])
        print(f"[ming] {k + 1}/{len(jobs)} {time.time() - t0:.1f}s {j['text'][:60]}", flush=True)
    print("DONE", len(jobs), flush=True)


if __name__ == "__main__":
    cmd, a = sys.argv[1], sys.argv[2:]
    a[0] = os.path.abspath(a[0])  # load() chdirs into the Ming repo
    if cmd == "synth":
        a[1] = os.path.abspath(a[1])
    if cmd == "design":
        design(a[0], a[1], *(a[2:3]))
    elif cmd == "builtin":
        builtin(a[0], a[1], *(a[2:3]))
    elif cmd == "synth":
        synth(a[0], a[1])
    else:
        raise SystemExit(__doc__)
