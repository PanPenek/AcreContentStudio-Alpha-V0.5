"""Procedural low-poly pixel cat: build + parametric behaviours (no armature, pivot empties).

Local frame: cat faces -Y, up +Z, origin on the ground under the hips/chest centre.
cat_params(action, t) -> dict of numbers; blend_params(a, b, w); apply_params(rig, p, frame) keyframes it.
"""
import math

import bpy
import numpy as np
from mathutils import Euler

import abs_common as C

TAIL_N = 7
PALETTES = {
    "orange": {"fur": "#f2a24a", "stripe": "#c86a22", "white": "#fff3e3", "nose": "#f28aa0", "eye": "#7cc85a", "inner": "#f6b9c4"},
    "grey": {"fur": "#9aa0ad", "stripe": "#6b707d", "white": "#f4f2f2", "nose": "#e88aa0", "eye": "#e8c64a", "inner": "#f0b6c0"},
    "black": {"fur": "#2f2a35", "stripe": "#221e27", "white": "#3a3442", "nose": "#5c4450", "eye": "#f2d24a", "inner": "#6a4a5a"},
    "calico": {"fur": "#fbf3e8", "stripe": "#e08a3c", "white": "#ffffff", "nose": "#f28aa0", "eye": "#6ab4e0", "inner": "#f6b9c4"},
}


def _empty(name, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.03
    bpy.context.scene.collection.objects.link(e)
    if parent is not None:
        e.parent = parent
    e.location = loc
    e.rotation_mode = "XYZ"
    return e


def _mesh(kind, name, parent, loc, scale, mat, rot=(0, 0, 0), **kw):
    o = C.add_prim(kind, name, loc=(0, 0, 0), mat=mat, **kw)
    o.parent = parent
    o.location = loc
    o.scale = scale
    o.rotation_euler = rot
    return o


def stripe_img(pal, name):
    h, w = 16, 32
    a = np.zeros((h, w, 3), np.float32)
    fur, st = np.array(C.hex_rgb(pal["fur"])), np.array(C.hex_rgb(pal["stripe"]))
    a[:] = fur
    for x in range(w):
        if x % 6 in (0, 1):
            a[2:h - 3, x] = st
    a[h - 3:, :] = np.array(C.hex_rgb(pal["white"]))  # belly band (bottom of UV sphere)
    return C.img_from_array(name, a)


def build_cat(name="Cat", palette="orange", scale=1.0, outline=0.004):
    pal = PALETTES.get(palette, PALETTES["orange"])
    fur = C.toon_mat(name + "_fur", image=stripe_img(pal, name + "_stripes"), shade=0.78, shade_tint=(0.9, 0.78, 0.82))
    plain = C.toon_mat(name + "_furplain", color=C.hex_rgb(pal["fur"]), shade=0.78, shade_tint=(0.9, 0.78, 0.82))
    white = C.toon_mat(name + "_white", color=C.hex_rgb(pal["white"]), shade=0.84)
    nose = C.flat_mat(name + "_nose", C.hex_rgb(pal["nose"]))
    inner = C.flat_mat(name + "_inner", C.hex_rgb(pal["inner"]))
    eye_m = C.flat_mat(name + "_eye", C.hex_rgb(pal["eye"]))
    pupil = C.flat_mat(name + "_pupil", (0.08, 0.06, 0.1))
    shine = C.flat_mat(name + "_shine", (1, 1, 1))

    r = {"name": name}
    root = _empty(name + "_root")
    root.scale = (scale, scale, scale)
    hips = _empty(name + "_hips", root, (0, 0.1, 0.17))
    # long axis along Y (nose to tail); UV-sphere meridians become tabby bands, the bottom rows the white belly
    body = _mesh("sphere", name + "_body", hips, (0, -0.1, 0.0), (0.1, 0.19, 0.095), fur, segments=14, ring_count=8)
    chest = _empty(name + "_chest", hips, (0, -0.21, 0.0))
    _mesh("sphere", name + "_bib", chest, (0, -0.06, -0.01), (0.07, 0.05, 0.07), white, segments=10, ring_count=6)
    neck = _empty(name + "_neck", chest, (0, -0.05, 0.07))
    head = _empty(name + "_head", neck, (0, -0.03, 0.05))
    _mesh("sphere", name + "_skull", head, (0, 0, 0), (0.088, 0.08, 0.075), plain, segments=12, ring_count=8)
    _mesh("sphere", name + "_muzzle", head, (0, -0.058, -0.025), (0.045, 0.03, 0.03), white, segments=10, ring_count=6)
    _mesh("cone", name + "_nose", head, (0, -0.088, -0.008), (0.012, 0.008, 0.009), nose, vertices=3,
          rot=(math.radians(90), math.radians(180), 0))
    ears, eyes = [], []
    for sx in (-1, 1):
        ep = _empty(f"{name}_earpiv{sx}", head, (sx * 0.048, -0.005, 0.055))
        _mesh("cone", f"{name}_ear{sx}", ep, (0, 0, 0.03), (0.032, 0.02, 0.045), plain, vertices=4,
              rot=(0, 0, math.radians(45)))
        _mesh("cone", f"{name}_earin{sx}", ep, (0, -0.012, 0.026), (0.02, 0.008, 0.032), inner, vertices=4,
              rot=(0, 0, math.radians(45)))
        ears.append(ep)
        eyp = _empty(f"{name}_eyepiv{sx}", head, (sx * 0.034, -0.072, 0.012))
        _mesh("sphere", f"{name}_eye{sx}", eyp, (0, 0, 0), (0.019, 0.008, 0.021), eye_m, segments=10, ring_count=6)
        _mesh("sphere", f"{name}_pupil{sx}", eyp, (0, -0.005, 0), (0.007, 0.006, 0.017), pupil, segments=8, ring_count=6)
        _mesh("sphere", f"{name}_shine{sx}", eyp, (sx * -0.005, -0.009, 0.008), (0.004, 0.003, 0.004), shine,
              segments=6, ring_count=4)
        eyes.append(eyp)
    # whiskers
    for sx in (-1, 1):
        for k in (-1, 1):
            w = _mesh("cube", f"{name}_wh{sx}{k}", head, (sx * 0.06, -0.06, -0.025 + k * 0.006), (0.035, 0.0015, 0.0015),
                      pupil, rot=(0, math.radians(k * 8 * sx), math.radians(-sx * 12)))
    legs = {}
    for key, parent, pos in (("fl", chest, (-0.05, -0.02, -0.03)), ("fr", chest, (0.05, -0.02, -0.03)),
                             ("bl", hips, (-0.055, 0.02, -0.03)), ("br", hips, (0.055, 0.02, -0.03))):
        lp = _empty(f"{name}_leg_{key}", parent, pos)
        _mesh("cyl", f"{name}_legm_{key}", lp, (0, 0, -0.065), (0.026, 0.026, 0.065), plain, vertices=8)
        paw = _empty(f"{name}_paw_{key}", lp, (0, 0, -0.13))
        _mesh("sphere", f"{name}_pawm_{key}", paw, (0, -0.01, 0), (0.03, 0.036, 0.018), white, segments=8, ring_count=6)
        legs[key] = (lp, paw)
    tail, tail_m = [], []
    parent = _empty(name + "_tailbase", hips, (0, 0.08, 0.035))
    for i in range(TAIL_N):
        seg = _empty(f"{name}_tail{i}", parent, (0, 0.0 if i == 0 else 0.045, 0))
        rr = 0.022 * (1 - 0.05 * i)
        tm = _mesh("cyl", f"{name}_tailm{i}", seg, (0, 0.0225, 0), (rr, rr, 0.026), fur if i < TAIL_N - 1 else plain,
                   vertices=8, rot=(math.radians(90), 0, 0))
        tm["r0"] = rr
        tail.append(seg)
        tail_m.append(tm)
        parent = seg
    r.update(root=root, hips=hips, chest=chest, neck=neck, head=head, ears=ears, eyes=eyes, legs=legs, tail=tail, body=body,
             tail_m=tail_m)
    bpy.context.view_layer.update()
    meshes = [o for o in bpy.data.objects if o.name.startswith(name + "_") and o.type == "MESH"]
    for o in meshes:
        if not any(s in o.name for s in ("_wh", "_shine", "_pupil", "_nose", "_earin", "_eye")):
            C.add_outline(o, outline)
    r["meshes"] = meshes
    return r


# ------------------------------------------------------------------ behaviours
def _base():
    return {
        "x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "roll": 0.0,
        "hips_pitch": 0.0, "hips_z": 0.0, "chest_pitch": 0.0,
        "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0, "head_fwd": 0.0,
        "ears": 0.0, "eye_open": 1.0, "eye_look": 0.0,
        "leg_fl": 0.0, "leg_fr": 0.0, "leg_bl": 0.0, "leg_br": 0.0,
        "tail_pitch": [10.0] * TAIL_N, "tail_yaw": [0.0] * TAIL_N, "tail_puff": 1.0,
    }


def _blink(t, period=3.4, off=0.0):
    p = (t + off) % period
    return 0.1 if p < 0.12 else 1.0


def _tail_relaxed(t):
    s = math.sin(2 * math.pi * 0.35 * t)
    return [-25.0, -15, -8, -2, 6, 12, 18], [8 * s, 10 * s, 12 * s, 14 * s, 16 * s, 18 * s, 20 * s]


def _tail_up(t, hook=True):
    s = math.sin(2 * math.pi * 0.6 * t)
    pitch = [70.0, 14, 6, 2, 0, -25 if hook else 4, -35 if hook else 4]
    yaw = [3 * s, 3 * s, 4 * s, 5 * s, 6 * s, 8 * s, 10 * s]
    return pitch, yaw


def _tail_wrap(t):
    s = math.sin(2 * math.pi * 0.3 * t)
    return [-50.0, -30, -5, 0, 0, 0, 0], [20, 26, 30, 30, 28, 26 + 4 * s, 24 + 8 * s]


def _sit(p, t):
    p["hips_pitch"] = -38.0
    p["hips_z"] = -0.06
    p["chest_pitch"] = 8.0
    p["head_pitch"] = 30.0
    p["leg_fl"] = p["leg_fr"] = 8.0
    p["leg_bl"] = p["leg_br"] = 22.0
    p["tail_pitch"], p["tail_yaw"] = _tail_wrap(t)
    return p


def cat_params(action, t, opts=None):
    """t: seconds since the action started."""
    opts = opts or {}
    p = _base()
    p["eye_open"] = _blink(t)
    a = action or "sit"
    if a in ("sit", "idle", "look"):
        _sit(p, t)
        p["head_yaw"] = float(opts.get("head", 0.0)) + 6 * math.sin(2 * math.pi * 0.2 * t)
    elif a == "slow_blink":
        _sit(p, t)
        cyc = (t % 2.6) / 2.6
        e = 1.0
        if cyc < 0.3:
            e = 1 - 0.88 * C.smooth(cyc / 0.3)
        elif cyc < 0.55:
            e = 0.12
        elif cyc < 0.85:
            e = 0.12 + 0.88 * C.smooth((cyc - 0.55) / 0.3)
        p["eye_open"] = e
        p["head_roll"] = 6 * math.sin(math.pi * min(1, cyc * 2))
        p["head_yaw"] = float(opts.get("head", 0.0))
    elif a in ("walk", "tail_up", "trot"):
        sp = 3.0 if a != "trot" else 4.5
        ph = 2 * math.pi * sp * t * 0.5
        sw = 24
        p["leg_fl"], p["leg_br"] = sw * math.sin(ph), sw * math.sin(ph)
        p["leg_fr"], p["leg_bl"] = -sw * math.sin(ph), -sw * math.sin(ph)
        p["z"] = 0.006 * abs(math.sin(ph))
        p["head_pitch"] = 6.0
        p["head_yaw"] = float(opts.get("head", 0.0))
        p["tail_pitch"], p["tail_yaw"] = _tail_up(t, hook=True)
        p["walk_speed"] = opts.get("speed", 0.22)
    elif a == "stand":
        p["head_yaw"] = float(opts.get("head", 0.0))
        p["tail_pitch"], p["tail_yaw"] = _tail_up(t, hook=True) if opts.get("tail") == "up" else _tail_relaxed(t)
    elif a == "headbutt":
        cyc = (t % 1.6) / 1.6
        push = math.sin(math.pi * min(1, cyc * 1.6)) if cyc < 0.62 else 0.0
        p["head_fwd"] = 0.03 * push
        p["head_pitch"] = -10 + 18 * push
        p["head_roll"] = 28 * push
        p["head_yaw"] = float(opts.get("head", 0.0))
        p["chest_pitch"] = 8 * push
        p["eye_open"] = 1 - 0.85 * push
        p["ears"] = 0.25 * push
        p["tail_pitch"], p["tail_yaw"] = _tail_up(t, hook=True)
    elif a == "knead":
        p["hips_z"] = -0.06
        p["hips_pitch"] = -12.0
        p["head_pitch"] = 12.0
        ph = 2 * math.pi * 1.6 * t
        p["leg_fl"] = 25 + 30 * max(0, math.sin(ph))
        p["leg_fr"] = 25 + 30 * max(0, math.sin(ph + math.pi))
        p["leg_bl"] = p["leg_br"] = -60.0
        p["eye_open"] = 0.35
        p["tail_pitch"], p["tail_yaw"] = _tail_relaxed(t)
    elif a == "loaf":
        p["hips_z"] = -0.12
        p["leg_fl"] = p["leg_fr"] = 80.0
        p["leg_bl"] = p["leg_br"] = -80.0
        p["head_pitch"] = 8.0
        p["eye_open"] = 0.5 if (t % 4) > 0.3 else 0.1
        p["tail_pitch"], p["tail_yaw"] = _tail_wrap(t)
    elif a in ("belly_up", "belly_trap"):
        p["roll"] = float(opts.get("roll", -118.0))
        p["z"] = 0.09
        p["hips_z"] = -0.03
        wig = math.sin(2 * math.pi * 0.8 * t)
        p["leg_fl"], p["leg_fr"] = 55 + 10 * wig, 35 - 10 * wig
        p["leg_bl"], p["leg_br"] = -25.0, -10.0
        p["head_roll"] = -35.0
        p["head_pitch"] = 15.0
        p["eye_open"] = 0.6 if a == "belly_up" else 1.0
        p["tail_pitch"], p["tail_yaw"] = [-10.0, 0, 5, 5, 5, 5, 5], [30, 10, 8, 6, 6, 6, 6]
        if a == "belly_trap" and t > opts.get("trap_at", 1.0):
            k = t - opts.get("trap_at", 1.0)
            kick = math.sin(2 * math.pi * 6 * k)
            p["leg_bl"], p["leg_br"] = -40 + 45 * kick, -30 - 45 * kick
            p["leg_fl"], p["leg_fr"] = 100 + 25 * kick, 95 - 25 * kick
            p["ears"] = 0.8
            p["head_pitch"] = 10.0
    elif a in ("ears_back", "annoyed"):
        _sit(p, t)
        p["ears"] = 1.0
        p["eye_open"] = 0.55
        p["head_pitch"] = 18.0
        p["head_yaw"] = float(opts.get("head", 0.0))
        s = math.sin(2 * math.pi * 1.8 * t)
        p["tail_pitch"] = [-20.0, -10, 0, 5, 5, 5, 5]
        p["tail_yaw"] = [35 * s, 25 * s, 20 * s, 15 * s, 12 * s, 10 * s, 8 * s]
    elif a == "puff":
        p["hips_z"] = 0.02
        p["hips_pitch"] = 12.0
        p["chest_pitch"] = -18.0
        p["head_pitch"] = -12.0
        p["ears"] = 1.0
        p["eye_open"] = 1.0
        p["tail_puff"] = 1.9
        p["tail_pitch"], p["tail_yaw"] = [75.0, 8, 4, 2, 0, 0, 0], [0.0] * TAIL_N
    elif a == "groom":
        _sit(p, t)
        cyc = math.sin(2 * math.pi * 1.2 * t)
        p["leg_fl"] = 90 + 20 * cyc
        p["head_pitch"] = 45 + 8 * cyc
        p["head_yaw"] = -20.0
        p["eye_open"] = 0.2
    elif a == "sleep":
        p["hips_z"] = -0.12
        p["leg_fl"] = p["leg_fr"] = 80.0
        p["leg_bl"] = p["leg_br"] = -80.0
        p["head_pitch"] = 25.0
        p["head_yaw"] = 25.0
        p["eye_open"] = 0.06
        p["z"] = 0.003 * math.sin(2 * math.pi * 0.3 * t)
        p["tail_pitch"], p["tail_yaw"] = _tail_wrap(0)
    return p


def blend_params(a, b, w):
    if w <= 0:
        return a
    if w >= 1:
        return b
    o = {}
    for k in a:
        va, vb = a[k], b.get(k, a[k])
        if isinstance(va, list):
            o[k] = [x + (y - x) * w for x, y in zip(va, vb)]
        else:
            o[k] = va + (vb - va) * w
    return o


def apply_params(r, p, frame=None):
    rad = math.radians
    root = r["root"]
    root.location = (p["x"], p["y"], p["z"])
    root.rotation_euler = Euler((0, rad(p["roll"]), rad(p["yaw"])), "ZYX")
    r["hips"].location.z = 0.17 + p["hips_z"]
    r["hips"].rotation_euler = (rad(p["hips_pitch"]), 0, 0)
    r["chest"].rotation_euler = (rad(p["chest_pitch"] - p["hips_pitch"] * 0.6), 0, 0)
    r["head"].location = (0, -0.03 - p["head_fwd"], 0.05)
    r["head"].rotation_euler = Euler((rad(-p["head_pitch"] + p["hips_pitch"] * 0.0), rad(p["head_roll"]), rad(p["head_yaw"])), "ZXY")
    for i, ep in enumerate(r["ears"]):
        sx = -1 if i == 0 else 1
        ep.rotation_euler = (rad(-55 * p["ears"]), rad(sx * 35 * p["ears"]), 0)
    for e in r["eyes"]:
        e.scale = (1, 1, max(0.06, p["eye_open"]))
    for key in ("fl", "fr", "bl", "br"):
        lp, _ = r["legs"][key]
        lp.rotation_euler = (rad(p["leg_" + key]), 0, 0)
    pf = p["tail_puff"]
    for i, seg in enumerate(r["tail"]):
        seg.rotation_euler = (rad(p["tail_pitch"][i]), 0, rad(p["tail_yaw"][i]))
        tm = r["tail_m"][i]
        tm.scale = (tm["r0"] * pf, tm["r0"] * pf, 0.026)
    if frame is not None:
        objs = [root, r["hips"], r["chest"], r["head"]] + r["ears"] + r["eyes"] + [r["legs"][k][0] for k in r["legs"]] + r["tail"] + r["tail_m"]
        for o in objs:
            o.keyframe_insert("location", frame=frame)
            o.keyframe_insert("rotation_euler", frame=frame)
            o.keyframe_insert("scale", frame=frame)
