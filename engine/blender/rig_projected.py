"""Rig a projection-textured character mesh (astolfo_v2 pipeline) with the VRoid J_Bip armature so abs_poses works.

blender --background --python rig_projected.py -- <recipe.json> <out_dir> [--preview]

recipe keys (astolfo_v2.json):
  kind: "projected", source_blend: proj blend with object "character" (front faces -Y, any scale),
  armature_blend: a built VRoid character.blend (its J_Bip rest pose is warped to this mesh),
  height: metres from floor to the top of the hair,
  z_map: [[vroid_z, frac_of_height], ...]      vertical landmarks (floor, ankle, knee, hip, chest, shoulder, neck, head, top)
  arm_x: [[vroid_x, frac], ...]                 T-pose arm landmarks (shoulder, upper arm, elbow, wrist, fingertip)
  arm_z: frac                                   arm centre height
  leg_x: [[vroid_z, frac], ...]                 leg centre x by height (legs splay)
  leg_y: frac                                   leg centre y (depth)
  faces: {expr: texture path}                   full baked textures, one per expression (texture-swap faces)
  cam_dz: metres added to host close-up cameras (big chibi heads sit lower)
Writes <out_dir>/character.blend (collection CHAR), character.json, preview.png, p_face.png, p_side.png.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
RECIPE, OUT = os.path.abspath(argv[0]), os.path.abspath(argv[1])
R = json.load(open(RECIPE, encoding="utf-8"))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
rp = lambda p: p if os.path.isabs(p) else os.path.join(ROOT, p)  # noqa: E731
CID = R["id"]
HGT = float(R["height"])
os.makedirs(OUT, exist_ok=True)


def lerp_map(pairs, v):
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    if v <= xs[0]:
        return ys[0] + (v - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0])
    if v >= xs[-1]:
        return ys[-1] + (v - xs[-1]) * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    return float(np.interp(v, xs, ys))


# ------------------------------------------------------------------ mesh: open, normalise to floor + height
bpy.ops.wm.open_mainfile(filepath=rp(R["source_blend"]))
sc = bpy.context.scene
body = bpy.data.objects["character"]
for o in list(bpy.data.objects):
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
body.name = "Body"
bpy.context.view_layer.objects.active = body
body.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
V = np.array([v.co[:] for v in body.data.vertices])
lo, hi = V.min(0), V.max(0)
s = HGT / (hi[2] - lo[2])
cx = (lo[0] + hi[0]) / 2
for v in body.data.vertices:
    v.co = Vector(((v.co.x - cx) * s, v.co.y * s, (v.co.z - lo[2]) * s))
body.data.update()
outline = next((m for m in body.modifiers if m.type == "SOLIDIFY"), None)
if outline:  # thickness was relative to the 1-unit source mesh
    outline.thickness *= s

# ------------------------------------------------------------------ armature: append VRoid rig, keep J_Bip body bones
with bpy.data.libraries.load(rp(R["armature_blend"]), link=False) as (src, dst):
    dst.objects = [n for n in src.objects]
arm = next(o for o in dst.objects if o and o.type == "ARMATURE")
for o in dst.objects:
    if o is not None and o is not arm:
        bpy.data.objects.remove(o, do_unlink=True)
sc.collection.objects.link(arm)
arm.name = arm.data.name = f"CHAR_{CID}"
arm.location = (0, 0, 0)
arm.rotation_mode = "XYZ"
arm.rotation_euler = (0, 0, 0)
arm.scale = (1, 1, 1)
arm.animation_data_clear()
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
    for c in list(pb.constraints):
        pb.constraints.remove(c)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abs_retarget as RT  # noqa: E402


def skel_of(a, head_c):
    return {"bones": {n: list(a.data.bones[n].head_local) for n in RT.ORDER if n in a.data.bones}, "head_c": head_c}


_hz = arm.data.bones["J_Bip_C_Head"].head_local.z
IK_REF = skel_of(arm, _hz + 0.5 * (R["z_map"][-1][0] - _hz))
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Little")
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
# fingertip of the VRoid rig (for the arm map) before deleting finger bones
for b in list(eb):
    keep = b.name == "Root" or (b.name.startswith("J_Bip") and not any(f in b.name for f in FINGERS))
    if not keep:
        eb.remove(b)

ZMAP = R["z_map"]
ARMX = R["arm_x"]
ARMZ = R["arm_z"] * HGT
ARM_S = (ARMX[-1][1] - ARMX[1][1]) * HGT / (ARMX[-1][0] - ARMX[1][0])
LEGX = R["leg_x"]
LEG_Y = R["leg_y"] * HGT
ARM_BONES = ("Shoulder", "UpperArm", "LowerArm", "Hand")
LEG_BONES = ("UpperLeg", "LowerLeg", "Foot", "ToeBase")


def warp(name, p):
    x, y, z = p
    if any(k in name for k in ARM_BONES) and "_C_" not in name:
        sg = 1 if x >= 0 else -1
        return Vector((sg * lerp_map(ARMX, abs(x)) * HGT, y * ARM_S, ARMZ + (z - R["arm_vroid_z"]) * ARM_S))
    zz = lerp_map(ZMAP, z) * HGT
    if any(k in name for k in LEG_BONES):
        sg = 1 if x >= 0 else -1
        yy = LEG_Y + (y - 0.005) * 1.4 if "Toe" in name or "Foot" in name else LEG_Y
        return Vector((sg * lerp_map(LEGX, z) * HGT, yy, zz))
    return Vector((x * R.get("body_x", 1.0), y * R.get("body_y", 1.0), zz))


# read every original joint first: connected bones share head/tail, so warping in place would warp some twice
orig = {b.name: (b.head.copy(), b.tail.copy()) for b in eb}
for b in eb:
    b.use_connect = False
for b in eb:
    h0, t0 = orig[b.name]
    b.head, b.tail = warp(b.name, h0), warp(b.name, t0)
# feet: point the foot to the toe of the (big) shoe, keep a sensible roll
for sd in "LR":
    f, tb = eb.get(f"J_Bip_{sd}_Foot"), eb.get(f"J_Bip_{sd}_ToeBase")
    if f and tb:
        tb.head = f.tail
        tb.tail = tb.head + Vector((0, -0.04, 0))
bpy.ops.object.mode_set(mode="OBJECT")

# ------------------------------------------------------------------ skin: region-aware distance weights
# Bone heat fails on TRELLIS meshes (not watertight; even a voxel proxy failed), so weights are computed directly:
# every vertex picks from the bones its body region may use (arm / leg / head / torso), weight ~ 1/d^4, top 3.
body.parent = None
for m in [m for m in body.modifiers if m.type == "ARMATURE"]:
    body.modifiers.remove(m)
for g in list(body.vertex_groups):
    body.vertex_groups.remove(g)
DEF = [bn for bn in arm.data.bones if bn.name.startswith("J_Bip")]
for bn in DEF:
    bn.use_deform = True
names = [bn.name for bn in DEF]
A = np.array([bn.head_local[:] for bn in DEF])
Bt = np.array([bn.tail_local[:] for bn in DEF])
P = np.array([v.co[:] for v in body.data.vertices])
ab = Bt - A
tt = np.clip(((P[:, None, :] - A[None]) * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-9)[None], 0, 1)
D = np.linalg.norm(P[:, None, :] - (A[None] + tt[..., None] * ab[None]), axis=-1)
x, z = P[:, 0], P[:, 2]
ax, zf = np.abs(x), z / HGT
side = np.where(x >= 0, "L", "R")
REG = R.get("regions", {})
arm_x0, arm_z0, arm_z1 = REG.get("arm_x", 0.135), REG.get("arm_z0", 0.645), REG.get("arm_z1", 0.75)
leg_z1, head_z0 = REG.get("leg_z1", 0.37), REG.get("head_z0", 0.75)
# (the braid hangs at |x| up to ~0.24H below the arm band: it must stay torso, or it follows the hand)
is_arm = ((ax / HGT > arm_x0) & (zf > arm_z0) & (zf < arm_z1)) | ((ax / HGT > REG.get("arm_x_any", 0.26)) & (zf > 0.6))
is_leg = (zf < leg_z1) & ~is_arm
is_head = (zf > head_z0) & ~is_arm
allow = np.zeros_like(D, dtype=bool)
col = {n: i for i, n in enumerate(names)}


def bones_of(*keys):
    return [i for n, i in col.items() if any(k in n for k in keys)]


for sd in "LR":
    m = side == sd
    allow[np.ix_(is_arm & m, bones_of(f"_{sd}_Shoulder", f"_{sd}_UpperArm", f"_{sd}_LowerArm", f"_{sd}_Hand"))] = True
    allow[np.ix_(is_leg & m, bones_of(f"_{sd}_UpperLeg", f"_{sd}_LowerLeg", f"_{sd}_Foot", f"_{sd}_ToeBase"))] = True
allow[np.ix_(is_arm & (ax / HGT < 0.2), bones_of("C_UpperChest", "C_Chest"))] = True
allow[np.ix_(is_head, bones_of("C_Head", "C_Neck"))] = True
torso = ~(is_arm | is_leg | is_head)
allow[np.ix_(torso, bones_of("C_Hips", "C_Spine", "C_Chest", "C_UpperChest", "C_Neck", "_Shoulder"))] = True
low = torso & (zf < REG.get("skirt_z1", 0.43))
for sd in "LR":
    allow[np.ix_(low & (side == sd), bones_of(f"_{sd}_UpperLeg"))] = True
W = np.where(allow, 1.0 / np.maximum(D, 0.01) ** 4, 0.0)
top = np.argsort(-W, axis=1)[:, :3]
groups = {n: body.vertex_groups.new(name=n) for n in names}
for vi in range(len(P)):
    ws = W[vi, top[vi]]
    tot = ws.sum()
    if tot <= 0:
        continue
    for bi, w in zip(top[vi], ws / tot):
        if w > 0.02:
            groups[names[bi]].add([vi], float(w), "REPLACE")
md = body.modifiers.new("Armature", "ARMATURE")
md.object = arm
body.parent = arm
print("weights: arm", int(is_arm.sum()), "leg", int(is_leg.sum()), "head", int(is_head.sum()), "torso", int(torso.sum()), flush=True)
# armature first, outline after
am = next(m for m in body.modifiers if m.type == "ARMATURE")
body.modifiers.move(body.modifiers.find(am.name), 0)

# ------------------------------------------------------------------ texture-swap faces
mat = next(m for m in body.data.materials if m and m.name != "outline")
nt = mat.node_tree
N, L = nt.nodes, nt.links
tex0 = next(n for n in N if n.type == "TEX_IMAGE")
dest = tex0.outputs["Color"].links[0].to_socket
uv = N.new("ShaderNodeUVMap")
idx = N.new("ShaderNodeValue")
idx.name = idx.label = "FaceIdx"
idx.outputs[0].default_value = 0.0
FACE_NAMES = list(R["faces"].keys())
prev = None
for k, fn in enumerate(FACE_NAMES):
    im = bpy.data.images.load(rp(R["faces"][fn]), check_existing=True)
    im.name = f"face_{fn}"
    im.pack()
    tn = N.new("ShaderNodeTexImage")
    tn.name = f"face_{fn}"
    tn.image = im
    tn.interpolation = "Closest"
    L.new(uv.outputs[0], tn.inputs[0])
    if prev is None:
        prev = tn.outputs["Color"]
        continue
    cmp = N.new("ShaderNodeMath")
    cmp.operation = "COMPARE"
    cmp.inputs[1].default_value = float(k)
    cmp.inputs[2].default_value = 0.5
    L.new(idx.outputs[0], cmp.inputs[0])
    mx = N.new("ShaderNodeMix")
    mx.data_type = "RGBA"
    L.new(cmp.outputs[0], mx.inputs["Factor"])
    L.new(prev, mx.inputs[6])
    L.new(tn.outputs["Color"], mx.inputs[7])
    prev = mx.outputs[2]
L.new(prev, dest)
N.remove(tex0)
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)

# ------------------------------------------------------------------ collection + save
col = bpy.data.collections.new("CHAR")
sc.collection.children.link(col)
for o in (arm, body):
    for c in list(o.users_collection):
        c.objects.unlink(o)
    col.objects.link(o)
body["abs_face_mode"] = "texture"
arm.data.pose_position = "POSE"
head_b = arm.data.bones["J_Bip_C_Head"]
IK_OWN = skel_of(arm, 0.5 * (head_b.head_local.z + HGT))
meta = {
    "id": CID, "name": R.get("name", CID), "armature": arm.name, "face": "Body", "meshes": ["Body"],
    "face_mode": "texture", "faces": FACE_NAMES, "face_map": R.get("face_map", {}),
    "head": list(head_b.head_local), "eye_z": lerp_map(ZMAP, 1.48) * HGT, "height": HGT,
    "cam_dz": R.get("cam_dz", 0.0), "cam_dist": R.get("cam_dist", 1.0), "pose_set": R.get("pose_set", ""), "ik": {"ref": IK_REF, "own": IK_OWN}, "recipe": RECIPE,
}
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "character.blend"), compress=True)
json.dump(meta, open(os.path.join(OUT, "character.json"), "w"), indent=1)
print("SAVED", os.path.join(OUT, "character.blend"), flush=True)

# ------------------------------------------------------------------ previews (not saved into the blend)
if "--preview" in argv:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import abs_common as C
    import abs_poses as PZ
    sc.render.engine = "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.6, 0.66, 1)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    C.apply_pose(arm, RT.retarget(PZ.idle(0.3), meta["ik"]))
    hz = HGT
    for name, pos, tgt, lens, res in (("preview", (0.25, -3.4, 0.55 * hz), (0, 0, 0.5 * hz), 40, (360, 560)),
                                       ("p_face", (0.08, -1.0, 0.9 * hz), (0, 0, 0.87 * hz), 50, (360, 360)),
                                       ("p_side", (2.4, -0.3, 0.55 * hz), (0, 0, 0.5 * hz), 45, (360, 560))):
        cam.data.lens = lens
        C.look_at(cam, pos, tgt)
        sc.render.resolution_x, sc.render.resolution_y = res
        sc.render.filepath = os.path.join(OUT, name + ".png")
        bpy.ops.render.render(write_still=True)
    print("PREVIEWS", OUT, flush=True)
