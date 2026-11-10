"""Build a reusable stylised character asset from a VRoid VRM + a JSON recipe.

Run:  blender --background --python character_build.py -- <recipe.json> <out_dir> [--preview]
Writes <out_dir>/character.blend (+ character.json meta, preview.png / turnaround.png).
The episode scene builder appends the "CHAR" collection from character.blend.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abs_common as C  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RECIPE_PATH, OUT = os.path.abspath(argv[0]), os.path.abspath(argv[1])
PREVIEW = "--preview" in argv
R = json.load(open(RECIPE_PATH, encoding="utf-8"))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(OUT, exist_ok=True)


def rpath(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


# ------------------------------------------------------------------ import
bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene
before = set(bpy.data.objects)
bpy.ops.import_scene.vrm(filepath=rpath(R["base_vrm"]))
new = [o for o in bpy.data.objects if o not in before]
arm = [o for o in new if o.type == "ARMATURE"][0]
meshes = [o for o in new if o.type == "MESH"]
face = [o for o in meshes if o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 20][0]
hair = [o for o in meshes if any(m and "HAIR" in m.name for m in o.data.materials) and o is not face]
arm.name = "CHAR_" + R["id"]
for o in new:  # drop the VRM add-on's own outline / spring helpers modifiers; keep Armature
    if o.type == "MESH":
        for md in list(o.modifiers):
            if md.type != "ARMATURE":
                o.modifiers.remove(md)

# ------------------------------------------------------------------ textures: recolour then pixelate
for img_name, rules in R.get("recolor", {}).items():
    im = bpy.data.images.get(img_name)
    if im is None:
        print("WARN no image", img_name)
        continue
    C.recolor(im, rules)


def base_image(mat):
    best = None
    for n in mat.node_tree.nodes if mat.node_tree else []:
        if n.type == "TEX_IMAGE" and n.image:
            nm = n.image.name
            if nm.startswith(("Shader_", "Matcap", "Thumbnail")) or nm.endswith(("_nml", "_out", "_spe")):
                continue
            best = n.image
            break
    return best


pix = int(R.get("pixel_factor", 4))
seen = set()
mat_cfg = R.get("materials", {})
new_mats = {}
for o in meshes:
    for i, m in enumerate(o.data.materials):
        if m is None:
            continue
        if m.name in new_mats:
            o.data.materials[i] = new_mats[m.name]
            continue
        im = base_image(m)
        if im is not None and im.name not in seen:
            seen.add(im.name)
            f = pix * (2 if max(im.size) >= 2048 else 1)
            if "EYE" in m.name or "FACE" in m.name:
                f = max(1, pix // 2)  # keep eyes/mouth readable
            C.downscale(im, f)
        cfg = {"shade": 0.8, "alpha": True, "flat": False}
        for key, c in mat_cfg.items():
            if key in m.name:
                cfg.update(c)
        nm = C.toon_mat("ABS_" + m.name, image=im, shade=cfg["shade"], alpha=cfg["alpha"], flat=cfg["flat"],
                        shade_tint=tuple(cfg.get("tint", (0.88, 0.8, 0.92))))
        new_mats[m.name] = nm
        o.data.materials[i] = nm

# ------------------------------------------------------------------ rest-pose measurements
bpy.context.view_layer.update()
head_b = arm.data.bones["J_Bip_C_Head"]
HEAD = arm.matrix_world @ head_b.head_local
iris_z, iris_x = [], []
for p in face.data.polygons:
    mn = face.data.materials[p.material_index].name if face.data.materials[p.material_index] else ""
    if "EyeIris" in mn:
        c = face.matrix_world @ p.center
        iris_z.append(c.z)
        iris_x.append(abs(c.x))
EYE_Z = sum(iris_z) / len(iris_z) if iris_z else HEAD.z + 0.07
EYE_X = sum(iris_x) / len(iris_x) if iris_x else 0.03
print("HEAD", tuple(round(v, 3) for v in HEAD), "EYE_Z", round(EYE_Z, 3), "EYE_X", round(EYE_X, 3))

# ------------------------------------------------------------------ hair streak (front strand)
st = R.get("hair_streak")
if st and hair:
    smat = C.toon_mat("ABS_HairStreak", color=C.hex_rgb(st["color"]), shade=0.86)
    for h in hair:
        h.data.materials.append(smat)
        si = len(h.data.materials) - 1
        n = 0
        for p in h.data.polygons:
            pm = h.data.materials[p.material_index]
            if not pm or "HAIR" not in pm.name.upper():
                continue
            c = h.matrix_world @ p.center
            if st["x"][0] <= c.x <= st["x"][1] and c.y < HEAD.y + st.get("front_y", -0.03) and c.z > EYE_Z + st.get("min_dz", -0.02):
                p.material_index = si
                n += 1
        print("streak faces", h.name, n)

# ------------------------------------------------------------------ braid + bows (parented to the head bone)
extras = []
CHAR_COL = bpy.data.collections.new("CHAR")
sc.collection.children.link(CHAR_COL)


def bow(name, loc, size, color, rot=(0, 0, 0)):
    m = C.toon_mat(name + "_m", color=C.hex_rgb(color), shade=0.7)
    parts = []
    for sx in (-1, 1):
        lp = C.add_prim("cone", f"{name}_loop{sx}", loc=(0, 0, 0), vertices=4, radius1=size * 0.55, radius2=size * 0.12,
                        depth=size * 1.0, rot=(0, math.radians(90 * sx), 0), mat=m)
        lp.location = (sx * size * 0.5, 0, 0)
        lp.scale = (1, 1, 1)
        parts.append(lp)
    knot = C.add_prim("cube", f"{name}_knot", loc=(0, 0, 0), scale=(size * 0.16, size * 0.14, size * 0.16), mat=m)
    parts.append(knot)
    for sx in (-1, 1):
        tl = C.add_prim("cube", f"{name}_tail{sx}", loc=(sx * size * 0.18, 0.0, -size * 0.45),
                        scale=(size * 0.09, size * 0.04, size * 0.32), rot=(0, math.radians(sx * 18), 0), mat=m)
        parts.append(tl)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    b = bpy.context.object
    b.name = name
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    b.location = loc
    b.rotation_euler = rot
    return b


br = R.get("braid")
if br:
    sgn = 1 if br.get("side", "L") == "L" else -1
    n = int(br.get("segments", 12))
    p0 = Vector((sgn * br.get("x0", 0.055), HEAD.y + br.get("y0", 0.085), HEAD.z + br.get("z0", 0.05)))
    length = br.get("length", 0.6)
    mats = [C.toon_mat("ABS_Braid_a", color=C.hex_rgb(br["color"]), shade=0.78),
            C.toon_mat("ABS_Braid_b", color=C.hex_rgb(br.get("color2", br["color"])), shade=0.78)]
    prev = None
    segs = []
    for i in range(n):
        k = i / max(1, n - 1)
        pos = p0 + Vector((sgn * br.get("out", 0.06) * math.sin(k * math.pi * 0.6), br.get("back", 0.04) * k,
                           -length * k))
        r = br.get("radius", 0.042) * (1.0 - 0.35 * k)
        s = C.add_prim("ico", f"Braid_{i:02d}", loc=pos, subdivisions=1, radius=1.0, mat=mats[i % 2])
        s.scale = (r * 1.05, r * 0.9, r * 1.35)
        s.rotation_euler = (0, math.radians(28 * (1 if i % 2 else -1)), math.radians(15))
        segs.append(s)
    bpy.ops.object.select_all(action="DESELECT")
    for s in segs:
        s.select_set(True)
    bpy.context.view_layer.objects.active = segs[0]
    bpy.ops.object.join()
    braid = bpy.context.object
    braid.name = "Braid"
    extras.append(braid)
    endp = p0 + Vector((sgn * br.get("out", 0.06) * math.sin(math.pi * 0.6), br.get("back", 0.04), -length - 0.05))
    extras.append(bow("BraidBow", endp, br.get("bow_size", 0.11), br.get("bow", "#2b1b24"), rot=(0, 0, 0)))

hb = R.get("head_bows")
if hb:
    for sx in (-1, 1):
        loc = Vector((sx * hb.get("x", 0.085), HEAD.y + hb.get("y", 0.02), HEAD.z + hb.get("z", 0.15)))
        extras.append(bow(f"HeadBow{sx}", loc, hb.get("size", 0.075), hb.get("color", "#2b1b24"),
                          rot=(math.radians(hb.get("tilt_x", 10)), 0, math.radians(sx * hb.get("tilt", 28)))))

# pixel blush decals on the cheeks (raycast onto the face surface)
if R.get("blush", True):
    import numpy as np
    bl = np.zeros((6, 12, 4), np.float32)
    pink = C.hex_rgb(R.get("blush_color", "#f07f9c"))
    for x in range(12):
        for y in range(6):
            if (x + y) % 3 == 0 and 1 <= y <= 4:
                bl[y, x] = (*pink, 1)
    bim = C.img_from_array("ABS_blush", bl)
    bmat = C.toon_mat("ABS_Blush", image=bim, flat=True, alpha=True)
    tree, mw = C.bvh_for(face)
    inv = mw.inverted()
    for sx in (-1, 1):
        target = Vector((sx * (EYE_X + 0.006), HEAD.y - 0.3, EYE_Z - 0.032))
        o_l = inv @ target
        d_l = (inv.to_3x3() @ Vector((0, 1, 0))).normalized()
        hit = tree.ray_cast(o_l, d_l)
        if hit[0] is None:
            print("blush ray miss")
            continue
        pw = mw @ hit[0]
        nw = (mw.to_3x3() @ hit[1]).normalized()
        dec = C.add_prim("plane", f"Blush{sx}", loc=pw + nw * 0.0025, size=1.0, mat=bmat)
        dec.scale = (0.03, 0.015, 1)
        dec.rotation_euler = nw.to_track_quat("Z", "Y").to_euler()
        extras.append(dec)

for e in extras:
    C.parent_to_bone(e, arm, "J_Bip_C_Head")

# ------------------------------------------------------------------ outlines + collection + proportions
ol = float(R.get("outline", 0.0045))
for o in meshes:
    if o is not face:  # the face has drawn eyelines; a hull on it pokes through closed eyelids
        C.add_outline(o, ol)
for e in extras:
    if not e.name.startswith("Blush"):
        C.add_outline(e, ol * 0.8)

for o in [arm] + meshes + extras + [x for x in new if x.type == "EMPTY"]:
    for col in list(o.users_collection):
        col.objects.unlink(o)
    CHAR_COL.objects.link(o)

hs = float(R.get("head_scale", 1.0))
arm.pose.bones["J_Bip_C_Head"].scale = (hs, hs, hs)
for b, s in R.get("bone_scale", {}).items():
    if b in arm.pose.bones:
        arm.pose.bones[b].scale = (s, s, s)

# default resting expression
for k, v in R.get("default_face", {}).items():
    key = C.shape_key(face, k)
    if key:
        key.value = v

meta = {
    "id": R["id"], "name": R.get("name", R["id"]), "armature": arm.name, "face": face.name,
    "meshes": [o.name for o in meshes], "head": list(HEAD), "eye_z": EYE_Z,
    "height": float(max((arm.matrix_world @ b.tail_local).z for b in arm.data.bones)),
    "default_face": R.get("default_face", {}), "recipe": os.path.abspath(RECIPE_PATH),
}
json.dump(meta, open(os.path.join(OUT, "character.json"), "w"), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "character.blend"), compress=True)
print("SAVED", os.path.join(OUT, "character.blend"))

# ------------------------------------------------------------------ preview (not saved)
if PREVIEW:
    import numpy as np
    sc.render.engine = "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.31, 0.34, 1)
    # backdrop + grid floor like the reference sheet
    g = np.zeros((32, 32, 3), np.float32)
    g[:] = (0.22, 0.22, 0.23)
    g[::16, :] = (0.3, 0.3, 0.31)
    g[:, ::16] = (0.3, 0.3, 0.31)
    C.add_prim("plane", "PrevFloor", size=10, mat=C.toon_mat("pf", image=C.img_from_array("pfg", g), uv_scale=20, shade=0.9))
    C.add_prim("plane", "PrevWall", loc=(0, 8, 2), rot=(math.radians(90), 0, 0), size=10,
               mat=C.flat_mat("pw", (0.6, 0.59, 0.62)))
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    sun.data.energy = 3
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 50
    H = meta["height"]
    sc.render.resolution_x, sc.render.resolution_y = 768, 1024
    pose = C.merged(
        C.P(L_UpperArm=C.Rot("Y", 62) @ C.Rot("Z", 28), L_LowerArm=C.Rot("Z", 95), L_Hand=C.Rot("X", -20)),
        C.P(R_UpperArm=C.Rot("Y", 38) @ C.Rot("Z", 10), R_LowerArm=C.Rot("Y", 95) @ C.Rot("Z", 30), R_Hand=C.Rot("X", 10)),
        C.hand_shape("R", "peace"), C.hand_shape("L", "relaxed"),
        C.P(L_UpperLeg=C.Rot("Y", -4), R_UpperLeg=C.Rot("Y", 5), C_Head=C.Rot("Z", -6) @ C.Rot("X", 4)),
    )
    C.apply_pose(arm, pose)
    for k, v in R.get("preview_face", {}).items():
        key = C.shape_key(face, k)
        if key:
            key.value = v
    shots = [("preview", (0.15, -3.6, H * 0.55), (0, 0, H * 0.5), 0),
             ("p_side", (2.6, -2.5, H * 0.6), (0, 0, H * 0.5), 1), ("p_back", (0.4, 3.6, H * 0.6), (0, 0, H * 0.5), 2),
             ("p_face", (0.05, -1.25, H * 0.9), (0, 0, H * 0.88), 3)]
    for name, loc, tgt, _ in shots:
        C.look_at(cam, loc, tgt)
        sc.render.filepath = os.path.join(OUT, name + ".png")
        bpy.ops.render.render(write_still=True)
        print("PREVIEW", name)
