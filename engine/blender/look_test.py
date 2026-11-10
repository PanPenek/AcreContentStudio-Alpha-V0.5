"""Render a quick look-test of abs_pix (and optionally a kit prop / world set).

blender --background --python engine/blender/look_test.py -- <out.png> [--set NAME] [--prop KIT[:json-params]] [--cam x,y,z:tx,ty,tz:lens] [--res 720x1280]
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import abs_common as C  # noqa: E402
import abs_pix as X  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = os.path.abspath(argv[0])


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
rx, ry = (int(v) for v in arg("--res", "720x1280").split("x"))
sc.render.resolution_x, sc.render.resolution_y = rx, ry
sc.eevee.taa_render_samples = 16

S = None
if arg("--set"):
    import abs_world as W  # noqa: E402
    S = W.WORLDS[arg("--set")](sc)
else:
    X.setup_look(sc)
    X.sky_extras()
    g = X.box("Ground", (0, 0, -0.05), (60, 60, 0.1), X.mat("grass"))
    X.box("Wall", (1.2, 1.5, 0.75), (2.5, 0.5, 1.5), X.mat("stone_brick"))
    X.water_plane("Lake", (0, 6, 0.02), (14, 6))
    X.cyl("Trunk", (-1.4, 2, 1.0), 0.14, 2.0, X.mat("bark"), verts=7)
    for i, (dx, dz, r) in enumerate([(0, 2.3, 0.9), (0.4, 2.0, 0.6), (-0.4, 2.0, 0.65), (0, 2.8, 0.6)]):
        X.ball(f"Crown{i}", (-1.4 + dx, 2, dz), r, X.mat("leaves_solid"), sub=1)

if arg("--prop"):
    import abs_kit as K  # noqa: E402
    spec = arg("--prop")
    kit, _, params = spec.partition(":")
    root = K.build(kit, json.loads(params) if params else {})
    root.location = Vector((S or {}).get("anchors", {}).get("center", (0.45, 0.7, 0)))

if arg("--host"):
    p = os.path.abspath(arg("--host"))
    with bpy.data.libraries.load(os.path.join(p, "character.blend"), link=False) as (src, dst):
        dst.collections = ["CHAR"]
    sc.collection.children.link(dst.collections[0])
    arm = [o for o in dst.collections[0].all_objects if o.type == "ARMATURE"][0]
    arm.location = Vector((S or {}).get("anchors", {}).get("host", (-0.7, 0.2, 0)))

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
sc.collection.objects.link(cam)
sc.camera = cam
if arg("--cam"):
    a, b, l = arg("--cam").split(":")
    pos = [float(v) for v in a.split(",")]
    tgt = [float(v) for v in b.split(",")]
    cam.data.lens = float(l)
elif S and "wide" in S.get("cams", {}):
    c = S["cams"]["wide"]
    pos, tgt = c["pos"], c["target"]
    cam.data.lens = c.get("lens", 24)
else:
    pos, tgt = (0.5, -5.5, 1.6), (0.3, 2, 1.1)
    cam.data.lens = 24
cam.data.clip_end = 400
C.look_at(cam, pos, tgt)
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
if "--save" in argv:
    bpy.ops.wm.save_as_mainfile(filepath=OUT.rsplit(".", 1)[0] + ".blend")
print("LOOK_OK", OUT)
