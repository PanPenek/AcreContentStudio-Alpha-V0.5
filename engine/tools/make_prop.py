"""Generate a pixel-3D prop from a text description (cached by description).

python make_prop.py "<describe>" [--blender EXE] [--force]
-> assets/props/<slug>/prop.blend (+ front.png, back.png, mesh.glb, preview.png, prop.json); prints "ASSET <path>"

Pipeline (all local): Qwen-Edit-2511 text-to-image (front view) -> Qwen-Edit back view -> TRELLIS.2 shape ->
project_texture.py (pixelized front/back art baked onto the mesh, inverted-hull outline).
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, HERE)
import comfy_server  # noqa: E402

STYLE = ("single object only, isolated, centered, the whole object fully visible with empty margin around it, "
         "straight front view, eye level, low-poly 3D model with pixel-art textures, flat cel shading, bold dark outlines, "
         "bright cheerful colors, plain light grey background, no ground, no shadow, no text, no people")


def slug(describe):
    words = re.sub(r"[^a-z0-9 ]+", "", describe.lower()).split()[:4]
    return "_".join(words) + "_" + hashlib.sha1(describe.strip().lower().encode()).hexdigest()[:6]


def run(cmd):
    print("$", " ".join(cmd[:6]), "...", flush=True)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = (p.stdout + p.stderr).strip().splitlines()[-8:]
    for line in tail:
        if any(k in line for k in ("OK", "ERROR", "Error", "SAVED", "BAKED", "Traceback")):
            print("  ", line[:300], flush=True)
    if p.returncode != 0:
        raise SystemExit(f"step failed: {' | '.join(tail[-4:])}")
    return p.stdout


def build(describe, blender, force=False):
    d = os.path.join(ROOT, "assets", "props", slug(describe))
    out = os.path.join(d, "prop.blend")
    if os.path.exists(out) and not force:
        print("ASSET", out, flush=True)
        return out
    os.makedirs(d, exist_ok=True)
    srv = comfy_server.ensure()
    have = lambda n: os.path.exists(os.path.join(d, n))  # resume: keep finished steps after a crash
    seed = int(hashlib.sha1(describe.encode()).hexdigest()[:6], 16)
    py = sys.executable
    print("@@PROP 0.1 front view", flush=True)
    have("front.png") or run([py, os.path.join(HERE, "qedit.py"), srv, "-", os.path.join(d, "front"), str(seed), "1024", "1024",
         f"{describe}. {STYLE}", "8"])
    print("@@PROP 0.3 back view", flush=True)
    have("back.png") or run([py, os.path.join(HERE, "qedit.py"), srv, os.path.join(d, "front.png"), os.path.join(d, "back"), str(seed + 1), "1024", "1024",
         "Show this exact same object from directly behind: back view, rear side, camera behind it, same size and position "
         "in the frame, same low-poly 3D style with pixel-art textures, same colors and materials, same outlines, "
         "plain light grey background.", "8"])
    side = ("Rotate this exact same object 90 degrees and show it from the side: the part that was at the {e} edge of the "
            "image now faces the camera. Strict side view, eye level, same size in the frame, same low-poly 3D style with "
            "pixel-art textures, same colors and materials, same outlines, plain light grey background.")
    print("@@PROP 0.4 side views", flush=True)
    have("right.png") or run([py, os.path.join(HERE, "qedit.py"), srv, os.path.join(d, "front.png"), os.path.join(d, "right"),
                              str(seed + 2), "1024", "1024", side.format(e="RIGHT"), "8"])
    have("left.png") or run([py, os.path.join(HERE, "qedit.py"), srv, os.path.join(d, "front.png"), os.path.join(d, "left"),
                             str(seed + 3), "1024", "1024", side.format(e="LEFT"), "8"])
    comfy_server.free()  # unload Qwen-Edit (~20 GB) first: with both resident TRELLIS swaps (47 s/step) and ComfyUI aborts
    print("@@PROP 0.5 3D shape", flush=True)
    have("mesh.glb") or run([py, os.path.join(HERE, "trellis3d.py"), srv, os.path.join(d, "front.png"), os.path.join(d, "mesh.glb"),
         "--faces", "20000", "--seed", str(seed % 1000), "--upres", "1024"])
    comfy_server.free()  # give the GPU back before Blender bakes
    print("@@PROP 0.8 pixel texture bake", flush=True)
    run([blender, "--background", "--factory-startup", "--python", os.path.join(ENGINE, "blender", "project_texture.py"), "--",
         os.path.join(d, "mesh.glb"), os.path.join(d, "front.png"), os.path.join(d, "back.png"), out,
         "--px", "160", "--colors", "20", "--head-colors", "0", "--tex", "1024",
         "--right", os.path.join(d, "right.png"), "--left", os.path.join(d, "left.png")])
    json.dump({"describe": describe, "slug": slug(describe), "seed": seed}, open(os.path.join(d, "prop.json"), "w"), indent=1)
    print("@@PROP 1.0 done", flush=True)
    print("ASSET", out, flush=True)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    blender = a[a.index("--blender") + 1] if "--blender" in a else os.environ.get(
        "ABS_BLENDER", r"C:\Users\rAzzren\Apps\blender-5.2.3-windows-x64\blender.exe")
    build(a[0], blender, "--force" in a)
