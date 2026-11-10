"""Stage 1 — audio + timeline for an episode.

    uv run --no-project --with numpy --with edge-tts python engine/audio.py <episode_dir>

Reads <episode_dir>/episode.json, writes vo/, mix.wav and timeline.json:
  beats (start/end/words), shots, per-frame host talk envelope, sfx list.
Everything is local and free: edge-tts voices, procedural 8-bit SFX, procedural chiptune.
"""
import asyncio
import json
import os
import subprocess
import sys
import wave

import numpy as np

SR = 44100
FPS = 30


def log(*a):
    print("[audio]", *a, flush=True)


# ------------------------------------------------------------------ tts
async def _tts(text, voice, path, rate, pitch):
    import edge_tts
    c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words = []
    with open(path, "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return words


def tts(text, voice, path, rate="+0%", pitch="+0Hz", tries=3):
    last = None
    for _ in range(tries):
        try:
            return asyncio.run(_tts(text, voice, path, rate, pitch))
        except Exception as e:  # network hiccup: retry
            last = e
            log("tts retry:", e)
    raise last


def to_wav(src):
    dst = os.path.splitext(src)[0] + ".wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1", "-ar", str(SR), dst], check=True)
    with wave.open(dst) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


# ------------------------------------------------------------------ local TTS (Ming-3.0-tts)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MING_PY = os.path.join(ROOT_DIR, "tools", "Ming-3.0-tts", ".venv", "Scripts", "python.exe")
FACE_EMOTION = {"happy": "happy", "fang_grin": "happy", "wink": "happy", "surprised": "surprised", "sad": "sad", "angry": "angry"}


def ming_batch(ep, vo_dir, voice_id):
    """Synthesize every beat with the cloned local voice in ONE model load. Returns {beat index: flac path}."""
    vdir = os.path.join(ROOT_DIR, "assets", "voices", voice_id)
    if not os.path.exists(os.path.join(vdir, "ref.wav")):
        raise SystemExit(f"voice '{voice_id}' has no reference clip (assets/voices/{voice_id}/ref.wav) - design it first")
    jobs, out = [], {}
    for i, b in enumerate(ep["beats"]):
        text = b.get("text", "").strip()
        if not text:
            continue
        f = os.path.join(vo_dir, f"b{i:02d}.flac")
        emo = b.get("emotion") or FACE_EMOTION.get((b.get("host") or {}).get("face", ""), "neutral")
        jobs.append({"text": text, "out": f, "emotion": emo})
        out[i] = f
    jp = os.path.join(vo_dir, "ming_jobs.json")
    json.dump(jobs, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    p = subprocess.run([MING_PY, os.path.join(ROOT_DIR, "engine", "tts_ming.py"), "synth", vdir, jp],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in (p.stdout + p.stderr).splitlines():
        if line.startswith("[ming]") or "Error" in line:
            log(line)
    if p.returncode != 0:
        raise SystemExit("Ming TTS failed: " + " | ".join((p.stdout + p.stderr).strip().splitlines()[-5:]))
    return out


def estimate_words(text, a):
    """No word boundaries from Ming: spread words over the voiced span, weighted by length."""
    import re as _re
    words = [w for w in _re.sub(r"\[[^\]]+\]", " ", text).split() if w]
    if not words:
        return []
    nz = np.where(np.abs(a) > 0.02)[0]
    t0 = nz[0] / SR if len(nz) else 0.0
    t1 = nz[-1] / SR if len(nz) else len(a) / SR
    wts = np.array([len(w) + 2.0 for w in words])
    edges = t0 + np.concatenate([[0], np.cumsum(wts)]) / wts.sum() * (t1 - t0)
    return [(float(edges[k]), float(edges[k + 1]), w) for k, w in enumerate(words)]


# ------------------------------------------------------------------ procedural sfx
rng = np.random.default_rng(11)


def t_(d):
    return np.arange(int(d * SR)) / SR


def env(n, a=0.004, decay=8.0):
    x = np.arange(n) / SR
    e = np.exp(-decay * x)
    na = max(1, int(a * SR))
    e[:na] *= np.linspace(0, 1, na)
    return e


def lp(x, k):
    return np.convolve(x, np.ones(k) / k, mode="same")


def sq(ph):
    return np.sign(np.sin(ph))


def adsr(n, a=0.02, r=0.08):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def formant(x, f, q=8.0):
    """Cheap 2-pole resonator (time-invariant)."""
    w = 2 * np.pi * f / SR
    r = np.exp(-w / (2 * q))
    a1, a2 = -2 * r * np.cos(w), r * r
    y = np.zeros_like(x)
    for i in range(2, len(x)):
        y[i] = x[i] - a1 * y[i - 1] - a2 * y[i - 2]
    return y / (np.abs(y).max() + 1e-6)


def meow(d=0.7, base=520, up=1.35):
    tt = t_(d)
    k = tt / d
    f0 = base * (1 + (up - 1) * np.sin(np.pi * np.clip(k * 1.15, 0, 1)) ** 1.2) * (1 - 0.25 * k)
    ph = 2 * np.pi * np.cumsum(f0) / SR
    src = sum((0.6 ** h) * np.sin(ph * (h + 1)) for h in range(8))
    # "mi" -> "aow": blend a bright and an open formant
    bright = formant(src, 2400, 6) * (1 - k) + formant(src, 900, 5) * k
    e = adsr(len(tt), 0.05, 0.18)
    return 0.32 * bright * e


def purr(d=1.6):
    tt = t_(d)
    am = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 26 * tt))
    n = lp(rng.standard_normal(len(tt)), 60)
    return 0.5 * n * am * adsr(len(tt), 0.2, 0.3) / (np.abs(n).max() + 1e-6)


def hiss(d=0.8):
    n = rng.standard_normal(int(d * SR))
    n = n - lp(n, 6)
    return 0.22 * n * adsr(len(n), 0.03, 0.25)


def sfx(kind):
    if kind == "whoosh":
        n = int(0.35 * SR)
        return 0.22 * lp(rng.standard_normal(n), 25) * np.sin(np.linspace(0, np.pi, n)) ** 2
    if kind == "pop":
        tt = t_(0.09)
        f = np.linspace(500, 1300, len(tt))
        return 0.35 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), decay=25)
    if kind == "sparkle":
        out = np.zeros(int(1.0 * SR))
        for i, fr in enumerate([1568, 2093, 2637, 3136]):
            s = int(i * 0.07 * SR)
            tt = t_(0.5)
            out[s:s + len(tt)] += 0.18 * np.sin(2 * np.pi * fr * tt) * env(len(tt), decay=7)
        return out
    if kind == "blip":
        tt = t_(0.12)
        return 0.2 * sq(2 * np.pi * 880 * tt) * env(len(tt), decay=30)
    if kind == "ding":
        tt = t_(1.2)
        return 0.28 * (np.sin(2 * np.pi * 1318 * tt) + 0.5 * np.sin(2 * np.pi * 2637 * tt)) * env(len(tt), decay=3.5)
    if kind == "boing":
        tt = t_(0.4)
        f = np.linspace(170, 600, len(tt)) * (1 + 0.08 * np.sin(2 * np.pi * 28 * tt))
        return 0.4 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), decay=6)
    if kind == "heart":
        out = np.zeros(int(0.7 * SR))
        for i, fr in enumerate([988, 1319]):
            s = int(i * 0.12 * SR)
            tt = t_(0.3)
            out[s:s + len(tt)] += 0.2 * sq(2 * np.pi * fr * tt) * env(len(tt), decay=12)
        return out
    if kind == "bonk":
        tt = t_(0.25)
        return 0.45 * (np.sin(2 * np.pi * 820 * tt) + 0.6 * np.sin(2 * np.pi * 410 * tt)) * env(len(tt), decay=22)
    if kind == "zap":
        tt = t_(0.5)
        f = np.linspace(1200, 200, len(tt))
        return 0.22 * sq(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), decay=6)
    if kind == "type":
        out = np.zeros(int(1.0 * SR))
        for i in range(9):
            s = int(i * 0.08 * SR)
            out[s:s + 600] += 0.25 * rng.standard_normal(600) * env(600, a=0.0005, decay=90)
        return out
    if kind == "meow":
        return meow()
    if kind == "meow_short":
        return meow(0.4, 600, 1.2)
    if kind == "trill":
        tt = t_(0.5)
        f = 700 + 80 * np.sin(2 * np.pi * 30 * tt)
        return 0.18 * np.sin(2 * np.pi * np.cumsum(f) / SR) * adsr(len(tt), 0.04, 0.15)
    if kind == "purr":
        return purr()
    if kind == "hiss":
        return hiss()
    raise ValueError("unknown sfx " + kind)


SFX_KINDS = ["whoosh", "pop", "sparkle", "blip", "ding", "boing", "heart", "bonk", "zap", "type", "meow", "meow_short",
             "trill", "purr", "hiss"]


def music(dur, bpm=100, seed=5, key=60, vol=1.0):
    beat = 60 / bpm
    n = int(dur * SR)
    out = np.zeros(n)
    k = key - 60
    chords = [[60 + k, 64 + k, 67 + k], [57 + k, 60 + k, 64 + k], [53 + k, 57 + k, 60 + k], [55 + k, 59 + k, 62 + k]]
    pent = [0, 2, 4, 7, 9]
    r = np.random.default_rng(seed)
    motif = [int(r.choice(pent)) + 12 * int(r.integers(0, 2)) for _ in range(16)]

    def hz(m):
        return 440 * 2 ** ((m - 69) / 12)

    step = beat / 2
    i = 0
    tp = 0.0
    while True:
        s = int(tp * SR)
        L = int(step * SR)
        if s + L >= n:
            break
        ch = chords[int(tp / (4 * beat)) % 4]
        tt = t_(step)
        if i % 2 == 0:
            out[s:s + L] += 0.3 * (2 / np.pi) * np.arcsin(np.sin(2 * np.pi * hz(ch[0] - 12) * tt)) * env(L, decay=3)
        if i % 16 not in (7, 15):
            out[s:s + L] += 0.08 * np.where(np.sin(2 * np.pi * hz(72 + k + motif[i % 16]) * tt) > 0.5, 1, -1) * env(L, decay=5)
        out[s:s + L] += 0.04 * sq(2 * np.pi * hz(ch[i % 3] + 12) * tt) * env(L, decay=9)
        if i % 4 == 2:  # hat
            hn = min(L, 1500)
            out[s:s + hn] += 0.04 * rng.standard_normal(hn) * env(hn, a=0.0005, decay=80)
        i += 1
        tp += step
    return out * vol


# ------------------------------------------------------------------ main
def build(ep_dir):
    ep = json.load(open(os.path.join(ep_dir, "episode.json"), encoding="utf-8"))
    vo_dir = os.path.join(ep_dir, "vo")
    os.makedirs(vo_dir, exist_ok=True)
    vcfg = ep.get("voice", {})
    voice = vcfg.get("narrator", "en-US-AvaNeural")
    rate, pitch = vcfg.get("rate", "+0%"), vcfg.get("pitch", "+0Hz")
    lead = float(ep.get("lead_in", 0.6))
    gap = float(ep.get("gap", 0.28))
    clips, beats, cur = [], [], lead
    local = ming_batch(ep, vo_dir, voice.split(":", 1)[1]) if voice.startswith("ming:") else {}
    if local:
        log(f"local voice {voice}: {len(local)} lines")
    for i, b in enumerate(ep["beats"]):
        text = b.get("text", "").strip()
        st = cur
        if text and i in local:
            a = to_wav(local[i])
            words = estimate_words(text, a)
        elif text:
            mp3 = os.path.join(vo_dir, f"b{i:02d}.mp3")
            words = tts(text, b.get("voice", voice), mp3, b.get("rate", rate), b.get("pitch", pitch))
            a = to_wav(mp3)
        if text:
            nz = np.where(np.abs(a) > 0.01)[0]
            a = a[:min(len(a), (nz[-1] if len(nz) else len(a)) + int(0.08 * SR))]
            clips.append((st, a, 1.0))
            en = st + len(a) / SR
        else:
            words, en = [], st + float(b.get("hold", 1.5))
        beats.append({**b, "i": i, "start": round(st, 3), "end": round(en, 3),
                      "words": [(round(st + w0, 3), round(st + w1, 3), w) for w0, w1, w in words]})
        cur = en + gap + float(b.get("pause_after", 0.0))
        log(f"{st:6.2f}-{en:6.2f}  {text[:70]}")
    dur = round(cur + float(ep.get("tail", 1.4)), 2)
    # beat windows run until the next beat starts (so shots/poses cover pauses)
    for i, b in enumerate(beats):
        b["until"] = beats[i + 1]["start"] if i + 1 < len(beats) else dur
    # shots: a beat may split into several shots
    shots = []
    for b in beats:
        names = b.get("shots") or [b.get("shot", "wide")]
        a0, a1 = b["start"] if b["i"] else 0.0, b["until"]
        for k, nm in enumerate(names):
            shots.append([nm, round(a0 + (a1 - a0) * k / len(names), 3), round(a0 + (a1 - a0) * (k + 1) / len(names), 3), b["i"]])
    # sfx: beat-level cues, offsets relative to beat start; cat sounds also
    fx = [(0.05, "type")] if ep.get("intro_type", True) else []
    for nm, s0, _, bi in shots[1:]:
        fx.append((max(0, s0 - 0.12), "whoosh"))
    for b in beats:
        for cue in b.get("sfx", []):
            kind, off = (cue, 0.0) if isinstance(cue, str) else (cue[0], float(cue[1]))
            fx.append((b["start"] + off, kind))
        if b.get("card"):
            fx.append((b["start"], "pop"))
    n = int(dur * SR)
    vbuf, fxbuf = np.zeros(n), np.zeros(n)
    for st, a, g in clips:
        i0 = int(st * SR)
        j = min(n, i0 + len(a))
        vbuf[i0:j] += g * a[:j - i0]
    for st, kind in fx:
        try:
            a = sfx(kind)
        except ValueError as e:
            log("skip", e)
            continue
        i0 = int(st * SR)
        j = min(n, i0 + len(a))
        if i0 < n:
            fxbuf[i0:j] += a[:j - i0]
    mcfg = ep.get("music", {})
    mus = music(dur, mcfg.get("bpm", 100), mcfg.get("seed", 5), mcfg.get("key", 60), mcfg.get("volume", 1.0))
    venv = np.convolve(np.abs(vbuf), np.ones(SR // 8) / (SR // 8), mode="same")
    mix = 0.15 * mus * (1 - 0.5 * np.clip(venv * 10, 0, 1)) + 0.7 * fxbuf + vbuf
    fade = int(1.2 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix = mix / (np.abs(mix).max() + 1e-6) * 0.92
    with wave.open(os.path.join(ep_dir, "mix.wav"), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    # per-frame talk envelope (host mouth), 0..1
    hop = SR // FPS
    nf = int(np.ceil(dur * FPS))
    talk = np.zeros(nf)
    for f in range(nf):
        seg = vbuf[f * hop:(f + 1) * hop]
        talk[f] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    talk = np.clip(talk / (np.percentile(talk[talk > 0], 95) + 1e-6 if (talk > 0).any() else 1), 0, 1)
    tl = {"duration": dur, "fps": FPS, "beats": beats, "shots": shots, "sfx": fx, "talk": [round(float(x), 3) for x in talk]}
    json.dump(tl, open(os.path.join(ep_dir, "timeline.json"), "w"), indent=1)
    log("duration", dur, "beats", len(beats), "shots", len(shots))
    return tl


if __name__ == "__main__":
    build(sys.argv[1])
