"""Voice audition: every candidate voice reads the same lines through the real episode path (clone + emotion),
stitched into one file with a short announcer gap. Usage: python voice_audition.py <out.mp3> voice_id [voice_id ...]"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, "tools", "Ming-3.0-tts", ".venv", "Scripts", "python.exe")
LINES = [
    ("Hi hi! This little house can turn a river into bread. No electricity. At all!", "happy"),
    ("Step three. The millstones! Two huge round stones. The bottom one stays still, the top one spins.", "surprised"),
    ("Pour grain in the middle hole, and it gets crushed into flour. [Laughter] Pretty smart, right?", "happy"),
]
out = os.path.abspath(sys.argv[1])
tmp = os.path.join(os.path.dirname(out), "_aud")
os.makedirs(tmp, exist_ok=True)
parts = []
for v in sys.argv[2:]:
    jobs = [{"text": t, "emotion": e, "out": os.path.join(tmp, f"{v}_{k}.wav")} for k, (t, e) in enumerate(LINES)]
    jp = os.path.join(tmp, f"{v}.json")
    json.dump(jobs, open(jp, "w", encoding="utf-8"))
    p = subprocess.run([PY, os.path.join(ROOT, "engine", "tts_ming.py"), "synth", os.path.join(ROOT, "assets", "voices", v), jp],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(v, "ok" if p.returncode == 0 else "FAIL " + p.stderr[-400:], flush=True)
    parts += [j["out"] for j in jobs if os.path.exists(j["out"])]
    parts.append("SILENCE")
lst = os.path.join(tmp, "list.txt")
sil = os.path.join(tmp, "sil.wav")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1.2", sil], check=True)
with open(lst, "w") as f:
    for x in parts:
        f.write(f"file '{(sil if x == 'SILENCE' else x).replace(os.sep, '/')}'\n")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-ar", "44100", "-ac", "1", "-b:a", "160k", out], check=True)
print("OUT", out)
