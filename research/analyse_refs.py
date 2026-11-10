"""Transcribe + measure cuts for every downloaded reference reel. Writes refs/<u>/<code>/analysis.json and refs/summary.json."""
import glob
import json
import os
import re
import subprocess

from faster_whisper import WhisperModel

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs")
model = WhisperModel("small", device="cpu", compute_type="int8")
summary = []
for d in sorted(glob.glob(os.path.join(ROOT, "*", "*"))):
    v = os.path.join(d, "v.mp4")
    if not os.path.exists(v):
        continue
    out = os.path.join(d, "analysis.json")
    if os.path.exists(out):
        summary.append(json.load(open(out, encoding="utf-8")))
        continue
    info = {}
    ij = glob.glob(os.path.join(d, "*.info.json"))
    if ij:
        j = json.load(open(ij[0], encoding="utf-8"))
        info = {k: j.get(k) for k in ("title", "description", "duration", "view_count", "like_count", "comment_count", "uploader", "timestamp", "width", "height", "fps")}
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", v, "-vf", "scdet=threshold=8:sc_pass=1", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    cuts = [float(x) for x in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", p.stderr)]
    import wave
    import numpy as np
    w = wave.open(os.path.join(d, "a.wav"))
    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    segs, _ = model.transcribe(audio, word_timestamps=True)
    lines, words = [], 0
    for s in segs:
        lines.append([round(s.start, 2), round(s.end, 2), s.text.strip()])
        words += len(s.words or [])
    dur = info.get("duration") or 0
    a = {"dir": os.path.relpath(d, ROOT).replace("\\", "/"), **info, "cuts": cuts, "n_cuts": len(cuts),
         "avg_shot_s": round(dur / (len(cuts) + 1), 2) if dur else None, "words": words,
         "wps": round(words / dur, 2) if dur else None, "transcript": lines}
    json.dump(a, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    summary.append(a)
    print(a["dir"], "dur", dur, "views", info.get("view_count"), "cuts", len(cuts), "avg shot", a["avg_shot_s"], "wps", a["wps"])
json.dump(summary, open(os.path.join(ROOT, "summary.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
