"""Stage runner used by the app (and usable from a terminal). Stdlib only.

    python engine/run.py <stage> <episode_dir> [--blender EXE] [--uv EXE] [--times 1,2,3] [--force]

stages: audio | character | props | stills | render | compose | all
Writes <episode_dir>/status.json  {stage, state, progress, message, updated, history[]}
and prints "@@PROGRESS <0..1> <text>" lines the app parses.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_BLENDER = r"C:\Users\rAzzren\Apps\blender-5.2.3-windows-x64\blender.exe"


def opt(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


class Status:
    def __init__(self, ep_dir):
        self.path = os.path.join(ep_dir, "status.json")
        try:
            self.data = json.load(open(self.path, encoding="utf-8"))
        except Exception:
            self.data = {"history": []}

    def set(self, stage, state, progress=None, message=""):
        d = self.data
        d.update(stage=stage, state=state, message=message[-400:], updated=time.time())
        if progress is not None:
            d["progress"] = round(float(progress), 4)
        if state in ("done", "error"):
            d.setdefault("history", []).append({"stage": stage, "state": state, "at": time.time(), "message": message[-200:]})
            d["history"] = d["history"][-60:]
            d.setdefault("stages", {})[stage] = {"state": state, "at": time.time()}
        tmp = self.path + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, self.path)
        print(f"@@PROGRESS {d.get('progress', 0):.4f} {stage}:{state} {message[-120:]}", flush=True)


def stream(cmd, cwd, on_line=None):
    print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        tail.append(line)
        tail = tail[-40:]
        if on_line:
            on_line(line)
        if not line.startswith("Fra:") and "Saved:" not in line:
            print(line, flush=True)
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"exit {rc}: " + " | ".join(tail[-6:]))
    return tail


def uv_cmd(uv, *withs):
    c = [uv, "run", "--no-project"]
    for w in withs:
        c += ["--with", w]
    return c + ["python"]


def stage_audio(ep, a, st):
    st.set("audio", "running", 0.05, "voice + sfx + music")
    stream(uv_cmd(a["uv"], "numpy", "edge-tts") + [os.path.join(HERE, "audio.py"), ep], ROOT)
    st.set("audio", "done", 1.0, "mix.wav + timeline.json")


def char_ids(ep):
    e = json.load(open(os.path.join(ep, "episode.json"), encoding="utf-8"))
    return [v for v in (e.get("characters") or {}).values() if v]


def stage_character(ep, a, st, force=False):
    for cid in char_ids(ep):
        out = os.path.join(ROOT, "assets", "characters", cid)
        recipe = os.path.join(ROOT, "assets", "characters", "recipes", cid + ".json")
        if os.path.exists(os.path.join(out, "character.blend")) and not force:
            continue
        if not os.path.exists(recipe):
            raise RuntimeError(f"no recipe for character {cid}")
        st.set("character", "running", 0.2, f"building {cid}")
        kind = json.load(open(recipe, encoding="utf-8")).get("kind")
        script = "rig_projected.py" if kind == "projected" else "character_build.py"
        stream([a["blender"], "--background", "--python", os.path.join(HERE, "blender", script), "--",
                recipe, out, "--preview"], ROOT)
    st.set("character", "done", 1.0, "characters ready")


def stage_props(ep, a, st, force=False):
    """Build every generated prop ({"id", "describe"} entries in episode.props) and write its asset path back."""
    path = os.path.join(ep, "episode.json")
    e = json.load(open(path, encoding="utf-8"))
    # v0.3: props with a "kit" are procedural (abs_kit, built inside scene.py, no AI). Image-to-3D (TRELLIS) only
    # for "describe" props without a kit, as a last resort.
    specs = [p for p in (e.get("props") or []) if isinstance(p, dict) and p.get("id") and p.get("describe") and not p.get("kit")]
    if not specs:
        st.set("props", "done", 1.0, "props are procedural kit models (built in the scene)")
        return
    py = sys.executable
    for k, p in enumerate(specs):
        st.set("props", "running", k / len(specs), f"building prop '{p['id']}' ({k + 1}/{len(specs)}, ~4 min each, cached after)")
        tail = stream([py, os.path.join(HERE, "tools", "make_prop.py"), p["describe"], "--blender", a["blender"]]
                      + (["--force"] if force else []), ROOT)
        asset = next((l.split("ASSET ", 1)[1].strip() for l in reversed(tail) if l.startswith("ASSET ")), None)
        if not asset:
            raise RuntimeError(f"prop {p['id']} produced no asset")
        p["asset"] = asset
    json.dump(e, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    subprocess.run([py, os.path.join(HERE, "tools", "comfy_server.py"), "stop"], check=False)
    st.set("props", "done", 1.0, f"{len(specs)} props ready")


def contact_sheet(ep):
    sd = os.path.join(ep, "stills")
    files = sorted(f for f in os.listdir(sd) if f.startswith("t") and f.endswith(".png"))
    if not files:
        return
    tmp = os.path.join(sd, "_seq")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for i, f in enumerate(files):
        shutil.copy(os.path.join(sd, f), os.path.join(tmp, f"s{i:03d}.png"))
    cols = min(9, len(files))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", os.path.join(tmp, "s%03d.png"), "-vf",
                    f"scale=270:480,tile={cols}x{(len(files) + cols - 1) // cols}", "-frames:v", "1",
                    os.path.join(ep, "contact.png")], check=False)
    shutil.rmtree(tmp, ignore_errors=True)


def refresh_shots(ep):
    """Staging edits (restage / auto-fix) can change a beat's shot list without new audio: recompute timeline shots
    from episode.json + the audio beat windows, the same way scene.py does, so stills/review/render agree."""
    tp = os.path.join(ep, "timeline.json")
    tl = json.load(open(tp, encoding="utf-8"))
    e = json.load(open(os.path.join(ep, "episode.json"), encoding="utf-8"))
    if len(e.get("beats", [])) != len(tl["beats"]):
        return tl
    shots = []
    for b, eb in zip(tl["beats"], e["beats"]):
        names = eb.get("shots") or [eb.get("shot", "wide")]
        a0, a1 = (b["start"] if b["i"] else 0.0), b["until"]
        for k, nm in enumerate(names):
            shots.append([nm, round(a0 + (a1 - a0) * k / len(names), 3), round(a0 + (a1 - a0) * (k + 1) / len(names), 3), b["i"]])
    if shots != tl["shots"]:
        tl["shots"] = shots
        json.dump(tl, open(tp, "w", encoding="utf-8"))
        print(f"[run] timeline shots refreshed from episode.json ({len(shots)} shots)", flush=True)
    return tl


def stage_stills(ep, a, st, times=None):
    tl = refresh_shots(ep)
    if not times:  # middle of every shot
        times = [round((s[1] + s[2]) / 2, 2) for s in tl["shots"]]
    shutil.rmtree(os.path.join(ep, "stills"), ignore_errors=True)
    st.set("stills", "running", 0.05, f"{len(times)} stills")
    done = [0]

    def on(line):
        if "[scene] STILL" in line:
            done[0] += 1
            st.set("stills", "running", done[0] / len(times), f"still {done[0]}/{len(times)}")
    stream([a["blender"], "--background", "--python", os.path.join(HERE, "blender", "scene.py"), "--", ep, "--still",
            ",".join(str(t) for t in times)], ROOT, on)
    contact_sheet(ep)
    st.set("stills", "done", 1.0, "contact.png")


def stage_render(ep, a, st):
    tl = refresh_shots(ep)
    nf = int(tl["duration"] * tl["fps"] + 0.999)
    fd = os.path.join(ep, "frames")
    # Resume when existing frames are newer than every input (an interrupted render); otherwise start fresh.
    inputs = [os.path.join(ep, f) for f in ("episode.json", "timeline.json")] + \
             [os.path.join(HERE, "blender", f) for f in os.listdir(os.path.join(HERE, "blender")) if f.endswith(".py")]
    newest_input = max(os.path.getmtime(f) for f in inputs if os.path.exists(f))
    have = [os.path.join(fd, f) for f in os.listdir(fd)] if os.path.isdir(fd) else []
    resume = bool(have) and min(os.path.getmtime(f) for f in have) > newest_input and "--fresh" not in sys.argv
    if not resume:
        shutil.rmtree(fd, ignore_errors=True)
    st.set("render", "running", len(have) / nf if resume else 0.0,
           f"resuming: {len(have)}/{nf} frames exist" if resume else f"0/{nf} frames")
    t0 = time.time()
    rx = re.compile(r"f_(\d{4})\.png")

    def on(line):
        if "Saved:" in line:
            m = rx.search(line)
            if m:
                k = int(m.group(1))
                if k % 15 == 0 or k == nf:
                    el = time.time() - t0
                    eta = el / max(1, k) * (nf - k)
                    st.set("render", "running", k / nf, f"{k}/{nf} frames, ~{int(eta // 60)}m{int(eta % 60):02d}s left")
    stream([a["blender"], "--background", "--python", os.path.join(HERE, "blender", "scene.py"), "--", ep, "--render"]
           + (["--resume"] if resume else []), ROOT, on)
    n = len([f for f in os.listdir(fd) if f.endswith(".png")]) if os.path.isdir(fd) else 0
    if n < nf:
        raise RuntimeError(f"render ended with {n}/{nf} frames")
    st.set("render", "done", 1.0, f"{nf} frames in {int(time.time() - t0)}s")


def stage_compose(ep, a, st):
    st.set("compose", "running", 0.3, "captions + overlays + mux")
    stream(uv_cmd(a["uv"], "pillow") + [os.path.join(HERE, "compose.py"), ep], ROOT)
    st.set("compose", "done", 1.0, "final.mp4")


def main(argv):
    stage, ep = argv[0], os.path.abspath(argv[1])
    a = {"blender": opt(argv, "--blender", os.environ.get("ABS_BLENDER", DEFAULT_BLENDER)),
         "uv": opt(argv, "--uv", shutil.which("uv") or "uv")}
    times = [float(x) for x in opt(argv, "--times", "").split(",") if x.strip()]
    st = Status(ep)
    order = {"audio": [stage_audio], "character": [lambda e, a_, s: stage_character(e, a_, s, "--force" in argv)],
             "props": [lambda e, a_, s: stage_props(e, a_, s, "--force" in argv)],
             "stills": [lambda e, a_, s: stage_stills(e, a_, s, times)], "render": [stage_render],
             "compose": [stage_compose],
             "all": [stage_audio, stage_character, stage_props, lambda e, a_, s: stage_stills(e, a_, s, None), stage_render,
                     stage_compose]}
    if stage not in order:
        raise SystemExit("unknown stage " + stage)
    cur = stage
    try:
        for fn in order[stage]:
            fn(ep, a, st)
            cur = st.data.get("stage", stage)
        if stage == "all":
            st.set("all", "done", 1.0, "episode complete")
    except Exception as e:
        st.set(st.data.get("stage", cur), "error", None, str(e))
        print("ERROR", e, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
