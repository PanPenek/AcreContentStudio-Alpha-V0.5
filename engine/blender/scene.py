"""Stage 2/3 — build the episode scene in Blender from episode.json + timeline.json, then stills or a full render.

blender --background --python engine/blender/scene.py -- <episode_dir> [--still 1,4,9] [--render] [--frames a b]
                                                               [--res 540x960] [--samples 8]
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import abs_cat as CAT  # noqa: E402
import abs_common as C  # noqa: E402
import abs_poses as PZ  # noqa: E402
import abs_retarget as RT  # noqa: E402
import abs_sets as SETS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
EP = os.path.abspath(argv[0])
ep = json.load(open(os.path.join(EP, "episode.json"), encoding="utf-8"))
TL = json.load(open(os.path.join(EP, "timeline.json"), encoding="utf-8"))
FPS, DUR = TL["fps"], TL["duration"]
NF = int(math.ceil(DUR * FPS))
BEATS, SHOTS, TALK = TL["beats"], TL["shots"], TL["talk"]
# Re-read staging fields (poses, cat actions, shots...) from episode.json so editing staging never needs new audio.
TIMING = {"i", "start", "end", "until", "words"}
if len(ep.get("beats", [])) == len(BEATS):
    for b, eb in zip(BEATS, ep["beats"]):
        for k in [k for k in b if k not in TIMING]:
            b.pop(k)
        b.update({k: v for k, v in eb.items() if k not in TIMING})
    SHOTS = []
    for b in BEATS:
        names = b.get("shots") or [b.get("shot", "wide")]
        a0, a1 = (b["start"] if b["i"] else 0.0), b["until"]
        for k, nm in enumerate(names):
            SHOTS.append([nm, a0 + (a1 - a0) * k / len(names), a0 + (a1 - a0) * (k + 1) / len(names), b["i"]])
CHAR_DIRS = [os.path.join(ROOT, "assets", "characters")] + ep.get("character_dirs", [])


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def F(t):
    return int(round(t * FPS)) + 1


def log(*a):
    print("[scene]", *a, flush=True)


# ------------------------------------------------------------------ scene setup
bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, NF
sc.render.engine = "BLENDER_EEVEE"
rx, ry = (int(v) for v in arg("--res", ep.get("render", {}).get("res", "1080x1920")).split("x"))
sc.render.resolution_x, sc.render.resolution_y = rx, ry
sc.render.filter_size = 0.6
sc.eevee.taa_render_samples = int(arg("--samples", ep.get("render", {}).get("samples", 16)))
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"

try:
    import abs_world as WORLD  # v0.3 full environments (abs_pix look)
except Exception as _e:  # pragma: no cover
    log("abs_world unavailable:", _e)
    WORLD = None
SET_NAME = ep.get("set", "cozy_room")
V3 = WORLD is not None and SET_NAME in WORLD.WORLDS
if V3:
    S = WORLD.WORLDS[SET_NAME](sc)
    S["cams"] = dict(S["cams"])
    log("world set", SET_NAME, "(v0.3)")
else:
    S = SETS.SETS.get(SET_NAME, SETS.cozy_room)()
    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (*S["world"], 1)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sc.collection.objects.link(sun)
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(48), math.radians(8), math.radians(28))
sc.render.filter_size = float(ep.get("render", {}).get("filter", 0.75))
ANCH = S["anchors"]
WORLD_OBJS = set(o.name for o in sc.objects)  # set dressing (may be cleared under big props)


def anchor(v, default):
    if v is None:
        return Vector(default)
    if isinstance(v, str):
        return Vector(ANCH.get(v, default))
    return Vector(v)


def beat_at(t):
    for b in BEATS:
        a0 = b["start"] if b["i"] else 0.0
        if a0 - 1e-6 <= t < b["until"]:
            return b
    return BEATS[-1]


def resolve(key):
    """Per-beat spec dicts inherit from previous beats."""
    out, cur = [], {}
    for b in BEATS:
        cur = {**cur, **(b.get(key) or {})}
        if key == "cat" and "to" not in (b.get(key) or {}):
            cur.pop("to", None)
        out.append(dict(cur))
    return out


HOST_SPEC, CAT_SPEC = resolve("host"), resolve("cat")

# ------------------------------------------------------------------ host character
host_id = (ep.get("characters") or {}).get("host")
arm = face = None
FACE_TEX = None
CMETA = {}
if host_id:
    cdir = next((os.path.join(d, host_id) for d in CHAR_DIRS if os.path.exists(os.path.join(d, host_id, "character.blend"))), None)
    if cdir is None:
        raise SystemExit(f"character '{host_id}' not built — run the Characters stage first")
    with bpy.data.libraries.load(os.path.join(cdir, "character.blend"), link=False) as (src, dst):
        dst.collections = ["CHAR"]
    col = dst.collections[0]
    sc.collection.children.link(col)
    arm = [o for o in col.all_objects if o.type == "ARMATURE"][0]
    face = next((o for o in col.all_objects if o.type == "MESH" and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 20), None)
    CMETA = json.load(open(os.path.join(cdir, "character.json"), encoding="utf-8")) if os.path.exists(os.path.join(cdir, "character.json")) else {}
    if face is None:  # projected characters: expressions are whole baked textures picked by the FaceIdx value node
        for o in col.all_objects:
            for m in (o.data.materials if o.type == "MESH" else []):
                if m and m.node_tree and "FaceIdx" in m.node_tree.nodes:
                    FACE_TEX = (m, m.node_tree.nodes["FaceIdx"].outputs[0])
        log("host face mode: texture swap,", len(CMETA.get("faces", [])), "expressions")
        try:
            CMETA["_recipe"] = json.load(open(CMETA["recipe"], encoding="utf-8"))
        except Exception:
            CMETA["_recipe"] = {}
    PZ.use_pose_set(CMETA.get("pose_set", ""))
    dz, dk = float(CMETA.get("cam_dz", 0.0)), float(CMETA.get("cam_dist", 1.0))
    if dz or dk != 1.0:  # big chibi heads: close-up sits lower and further back
        for cn in ("host",):
            if cn in S["cams"]:
                c_ = dict(S["cams"][cn])
                tg = Vector(c_["target"]) + Vector((0, 0, dz))
                for k in ("pos", "end"):
                    c_[k] = tuple(tg + (Vector(c_[k]) + Vector((0, 0, dz)) - tg) * dk)
                c_["target"] = tuple(tg)
                S["cams"][cn] = c_
    HOST_POS = anchor(ep.get("host_at", "host"), (-0.35, 0.12, 0))
    arm.location = HOST_POS
    arm.rotation_mode = "XYZ"
    log("host", host_id, "at", tuple(HOST_POS))

# ------------------------------------------------------------------ cat
PROP_SPECS = [p for p in (ep.get("props") or []) if isinstance(p, dict) and p.get("id")]
has_cat = any(b.get("cat") for b in BEATS) or "cat" in (ep.get("props") or [])
rig = CAT.build_cat("Cat", ep.get("cat_palette", "orange"), scale=ep.get("cat_scale", 1.0)) if has_cat else None


# start position of every beat: an explicit 'at' teleports (use on a cut), a 'to' walks there during the beat
CAT_START = []
_pos = Vector(ANCH.get("bench_mid", ANCH.get("center", (0.45, 0.6, 0.0))))
for _b in BEATS:
    _raw = _b.get("cat") or {}
    if _raw.get("at") is not None:
        _pos = anchor(_raw["at"], _pos)
    CAT_START.append(_pos.copy())
    if _raw.get("to") is not None:
        _pos = anchor(_raw["to"], _pos)


def yaw_to(src, dst):
    d = Vector(dst) - Vector(src)
    return math.degrees(math.atan2(d.x, -d.y))


def cat_state(t, _cache={}):
    """Cat params at time t (position integrates through walks)."""
    b = beat_at(t)
    spec = CAT_SPEC[b["i"]]
    pos = CAT_START[b["i"]].copy()
    lt = t - (b["start"] if b["i"] else 0.0)
    act = spec.get("action", "sit")
    p = CAT.cat_params(act, lt, spec)
    yaw = 0.0
    if spec.get("to") is not None:
        dst = anchor(spec["to"], pos)
        dist = (dst - pos).length
        speed = float(spec.get("speed", 0.25))
        k = min(1.0, lt * speed / max(1e-3, dist))
        cur = pos.lerp(dst, k)
        yaw = yaw_to(pos, dst) if dist > 1e-3 else 0.0
        if k >= 1.0 and act in ("walk", "tail_up", "trot"):
            p = CAT.cat_params("stand", lt, {**spec, "tail": "up"})
        pos = cur
    look = spec.get("face", "camera")
    if spec.get("to") is None:
        if look == "host" and arm is not None:
            yaw = yaw_to(pos, HOST_POS)
        elif isinstance(look, (int, float)):
            yaw = float(look)
        else:
            yaw = float(spec.get("yaw", -15.0))
    p["x"], p["y"] = pos.x, pos.y
    p["z"] = p["z"] + pos.z
    p["yaw"] = yaw
    return p, b


# ------------------------------------------------------------------ props (generated 3D objects)
PROPS = {}  # id -> {"root": empty, "base": Vector, "size": float, "spec": dict}


def _load_prop(spec):
    """Append the prop's meshes (assets/props/<slug>/prop.blend, built by the props stage) under an empty,
    scaled to spec.height (m), standing on its anchor. Missing asset -> labelled placeholder box."""
    pid = spec["id"]
    if spec.get("kit"):
        return _load_kit_prop(spec)
    root = bpy.data.objects.new(f"PROP_{pid}", None)
    sc.collection.objects.link(root)
    path = PROPS_LIB.get(pid)
    objs = []
    if path and os.path.exists(path):
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = [n for n in src.objects]
        for o in dst.objects:
            if o is not None and o.type == "MESH":
                sc.collection.objects.link(o)
                objs.append(o)
    if not objs:
        log("WARN prop", pid, "has no built asset - placeholder box")
        objs = [C.add_prim("cube", f"{pid}_placeholder", scale=(0.3, 0.3, 0.3), mat=C.toon_mat(f"{pid}_ph", color=(0.85, 0.7, 0.95)))]
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    h = float(spec.get("height", 1.0))
    s = h / max(1e-6, hi.z - lo.z)
    for o in objs:
        o.location = (o.location - pivot) * s
        o.scale = o.scale * s
        o.parent = root  # (outline Solidify thickness scales with the object: stays a fixed fraction of its height)
    base = anchor(spec.get("at", "center"), ANCH.get("center", (0.45, 0.6, 0.0)))
    if spec.get("offset"):
        base = base + Vector(spec["offset"])
    root.location = base
    root.rotation_euler = (0, 0, math.radians(float(spec.get("yaw", -20))))
    rad = max(hi.x - lo.x, hi.y - lo.y) * s / 2
    PROPS[pid] = {"root": root, "base": base.copy(), "height": h, "radius": rad, "spec": spec}
    log("prop", pid, "at", tuple(round(v, 2) for v in base), "height", h)


def _load_kit_prop(spec):
    """v0.3 props: procedural low-poly kit (abs_kit) at REAL size x spec.scale (default 1). Set dressing inside the
    prop's footprint is removed so palms/rocks don't poke through a dam."""
    import abs_kit as KIT
    pid = spec["id"]
    kroot = KIT.build(spec["kit"], spec.get("params") or {})
    root = bpy.data.objects.new(f"PROP_{pid}", None)
    sc.collection.objects.link(root)
    kroot.parent = root
    s0 = float(spec.get("scale", 1.0))
    if spec.get("height") and not spec.get("scale") and spec.get("fit_height"):
        s0 = float(spec["height"]) / max(1e-3, float(kroot.get("kit_height", 1.0)))
    base = anchor(spec.get("at", "center"), ANCH.get("center", (0.45, 0.6, 0.0)))
    if spec.get("offset"):
        base = base + Vector(spec["offset"])
    root.location = base
    root.rotation_euler = (0, 0, math.radians(float(spec.get("yaw", 0))))
    root.scale = (s0, s0, s0)
    size = list(kroot.get("kit_size", [1, 1, 1]))
    h = float(kroot.get("kit_height", size[2])) * s0
    rad = max(size[0], size[1]) * s0 / 2
    # footprint clear (world dressing only; ground/water/sky stay)
    bpy.context.view_layer.update()
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    for o in kroot.children_recursive:
        if o.type == "MESH":
            for c in o.bound_box:
                w = o.matrix_world @ Vector(c)
                lo, hi = Vector(map(min, lo, w)), Vector(map(max, hi, w))
    removed = 0
    if lo.x < 1e8:
        for o in list(sc.objects):
            if o.name not in WORLD_OBJS or o.type != "MESH":
                continue
            d = o.dimensions
            if max(d.x, d.y) > 25 or o.name.startswith(("Ground", "Nile", "Lake", "Sun", "Cloud", "Ridge")):
                continue
            L_ = o.matrix_world.translation
            if lo.x - 0.6 < L_.x < hi.x + 0.6 and lo.y - 0.6 < L_.y < hi.y + 0.6:
                bpy.data.objects.remove(o, do_unlink=True)
                removed += 1
    PROPS[pid] = {"root": root, "base": base.copy(), "height": h, "radius": rad, "spec": spec, "scale0": s0,
                  "big": rad > 2.5, "lo": lo, "hi": hi}
    log("kit prop", pid, spec["kit"], "at", tuple(round(v, 2) for v in base), "h", round(h, 2), "r", round(rad, 2),
        "cleared", removed)


PROPS_LIB = {p["id"]: p.get("asset") for p in PROP_SPECS}
for _ps in PROP_SPECS:
    _load_prop(_ps)


def prop_state(pid, t):
    """(visible scale, extra yaw deg, z offset) for a prop at time t from per-beat 'prop' actions:
    appear | hide | show | spin | bob | wiggle | still."""
    acts = []
    for b in BEATS:
        a = (b.get("prop") or {}).get(pid)
        if a:
            acts.append((b["start"] if b["i"] else 0.0, a))
    visible = not (acts and acts[0][1] == "appear")
    scale, yaw, dz, mode, t_mode = (1.0 if visible else 0.0), 0.0, 0.0, "still", 0.0
    for t0, a in acts:
        if t0 > t:
            break
        lt = t - t0
        if a == "appear":
            k = min(1.0, lt / 0.45)
            scale = 1.0 + 0.18 * math.sin(math.pi * k) if k < 1 else 1.0  # pop with overshoot
            scale *= C.smooth(k) if k < 1 else 1.0
            visible = True
        elif a == "hide":
            scale = max(0.0, 1.0 - lt / 0.3) if t0 > 0 else 0.0  # hidden from the start: no first-frame flash
        elif a == "show":
            scale = 1.0
        if a in ("spin", "bob", "wiggle", "still"):
            mode, t_mode = a, t0
    lt = t - t_mode
    if mode == "spin":
        yaw = 40.0 * lt
    elif mode == "bob":
        dz = 0.04 * math.sin(2 * math.pi * 0.8 * lt)
    elif mode == "wiggle":
        yaw = 6.0 * math.sin(2 * math.pi * 1.6 * lt)
    return scale, yaw, dz


# ------------------------------------------------------------------ bake animation
prev_q = {}
keys = {}
if arm is not None and face is not None:
    keys = {k: C.shape_key(face, k) for k in PZ.FACE_KEYS}
    keys = {k: v for k, v in keys.items() if v is not None}


def host_face_tex(t, spec, b):
    """Texture-swap expression index: mapped face, 'talk' while speaking, 'blink' every ~3.9 s."""
    fmap, faces, rec = CMETA.get("face_map", {}), CMETA.get("faces", []), CMETA.get("_recipe", {})
    name = fmap.get(spec.get("face", "smile"), "neutral")
    fr = min(len(TALK) - 1, int(t * FPS))
    if b.get("speaker", "host") == "host" and TALK[fr] > 0.3 and name in rec.get("talk_faces", ["neutral", "smug"]):
        name = "talk"
    elif name in rec.get("blink_faces", ["neutral", "smug", "talk"]) and (t % 3.9) < 0.12:
        name = "blink"
    return float(faces.index(name)) if name in faces else 0.0


def host_pose(t):
    b = beat_at(t)
    i = b["i"]
    lt = t - (b["start"] if i else 0.0)
    spec = HOST_SPEC[i]
    cur = PZ.POSES.get(spec.get("pose", "idle"), PZ.idle)(lt)
    if i > 0:
        w = C.smooth(lt / 0.4)
        if w < 1:
            prev = PZ.POSES.get(HOST_SPEC[i - 1].get("pose", "idle"), PZ.idle)(t - BEATS[i - 1]["start"])
            blended = dict(prev)
            C.blend_into(blended, cur, w)
            cur = blended
    cur = C.comb(cur, PZ._breath(t))
    if CMETA.get("ik"):  # non-VRoid proportions: re-solve the arms so hands land where the gesture means
        cur = RT.retarget(cur, CMETA["ik"])
    return cur, spec, b, lt


def host_face(t, spec, b, lt):
    f = dict(PZ.FACES.get(spec.get("face", "smile"), {}))
    i = b["i"]
    if i > 0 and lt < 0.3:
        pf = PZ.FACES.get(HOST_SPEC[i - 1].get("face", "smile"), {})
        w = C.smooth(lt / 0.3)
        f = {k: pf.get(k, 0) * (1 - w) + f.get(k, 0) * w for k in set(pf) | set(f)}
    fr = min(len(TALK) - 1, int(t * FPS))
    if b.get("speaker", "host") == "host" and arm is not None:
        f["Fcl_MTH_A"] = max(f.get("Fcl_MTH_A", 0), 0.85 * TALK[fr])
    if not any(k in f for k in ("Fcl_EYE_Close_R", "Fcl_EYE_Close_L")) and f.get("Fcl_EYE_Joy", 0) < 0.6:
        if (t % 3.9) < 0.12:
            f["Fcl_EYE_Close"] = 1.0
    return f


def host_yaw(spec):
    look = spec.get("look", "camera")
    if look == "cat":
        return 22.0
    if isinstance(look, (int, float)):
        return float(look)
    if look in PROPS and arm is not None:  # turn toward a prop, clamped to a 3/4 view (face stays readable in host shots)
        d = PROPS[look]["base"] - HOST_POS
        return max(-40.0, min(40.0, math.degrees(math.atan2(d.x, -d.y))))
    return 0.0


bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
last_yaw = None
for fr in range(1, NF + 1):
    t = (fr - 1) / FPS
    if rig is not None:
        p, _ = cat_state(t)
        CAT.apply_params(rig, p, frame=fr)
    if PROPS and (fr % 2 == 1 or fr == NF):
        for pid, P_ in PROPS.items():
            s_, yaw_, dz_ = prop_state(pid, t)
            r = P_["root"]
            s0 = P_.get("scale0", 1.0)
            if P_.get("big"):  # set-piece props cut in/out (a 20 m dam popping from zero looks silly)
                vis = s_ > 0.5
                r.scale = (s0 if vis else 1e-4,) * 3
                r.hide_render = not vis
            else:
                r.scale = (max(1e-4, s_ * s0),) * 3
                r.hide_render = s_ < 1e-3
            yaw_def = 0 if P_["spec"].get("kit") else -20
            r.rotation_euler = (0, 0, math.radians(float(P_["spec"].get("yaw", yaw_def)) + yaw_))
            r.location = P_["base"] + Vector((0, 0, dz_))
            for k in ("scale", "rotation_euler", "location", "hide_render"):
                r.keyframe_insert(k, frame=fr)
    if arm is not None:
        pose, spec, b, lt = host_pose(t)
        y = host_yaw(spec)
        last_yaw = y if last_yaw is None else last_yaw + (y - last_yaw) * 0.15
        arm.rotation_euler = (0, 0, math.radians(last_yaw))
        arm.keyframe_insert("rotation_euler", frame=fr)
        if fr % 2 == 1 or fr == NF:
            C.apply_pose(arm, pose, prev_q, frame=fr)
        if FACE_TEX is not None:
            FACE_TEX[1].default_value = host_face_tex(t, spec, b)
            FACE_TEX[1].keyframe_insert("default_value", frame=fr)
        fv = host_face(t, spec, b, lt)
        for k, kb in keys.items():
            kb.value = max(0.0, min(1.0, fv.get(k, 0.0)))
            kb.keyframe_insert("value", frame=fr)
    if fr % 300 == 0:
        log("baked", fr, "/", NF)

# ------------------------------------------------------------------ cameras
def focus_of(bi):
    """Which prop a beat's prop/two/card shots frame: beat 'focus' (inherited), else the first prop, else the cat."""
    for b in reversed(BEATS[:bi + 1]):
        if b.get("focus"):
            return b["focus"]
    if PROP_SPECS:
        return PROP_SPECS[0]["id"]
    return "cat" if rig is not None else None


HIDE_HOST = set()  # filled per call; read right after prop_cam() for the current shot


def frame_of(P_):
    """(base point, height, effective radius) the cameras frame. Set-piece props (big kits such as a dam across a
    valley) are framed on their FRONT face with a height-based radius - fitting the whole 20 m footprint into a 9:16
    frame made every prop shot a far-away postage stamp (or put the camera inside a dune)."""
    if not P_.get("big"):
        return P_["base"], P_["height"], P_["radius"]
    h, r = P_["height"], P_["radius"]
    front = float(P_["spec"].get("front", -0.42 * r))
    return P_["base"] + Vector((0, front, 0)), h, min(r, max(1.5, h * 0.9))


def prop_cam(name, pid):
    """Camera preset framing a prop (prop / prop_close / card) or host+prop (two), fitted to a 9:16 frame."""
    P_ = PROPS[pid]
    fb, h, r = frame_of(P_)
    c = fb + Vector((0, 0, h * 0.5))
    lens = {"prop": 35, "prop_close": 45, "card": 40, "two": 28}[name]
    vt = 18.0 / lens  # tan(half vertical fov), portrait: sensor width maps to the long (vertical) side
    ht = vt * rx / ry
    if name == "two" and arm is not None:
        lo_x, hi_x = min(HOST_POS.x - 0.35, c.x - r), max(HOST_POS.x + 0.35, c.x + r)
        cx = (lo_x + hi_x) / 2
        hh = max(1.6, h)
        tgt = Vector((cx, (HOST_POS.y + c.y) / 2, hh * 0.5))
        dist = max(hh * 1.12 / 2 / vt, (hi_x - lo_x) * 1.15 / 2 / ht)
        pos = tgt + Vector((0.25 * dist * 0.3, -dist, 0.12))
    else:
        fill = {"prop": 1.25, "prop_close": 0.8, "card": 1.0}.get(name, 1.25)
        tgt = c.copy()
        if name == "prop_close":
            tgt.z = fb.z + h * 0.62
        dist = max(h * fill / 2 / vt, 2 * r * fill / 2 / ht) + r
        # each shot type gets its own angle so card/prop/prop_close cuts don't repeat the same picture
        side0, up = {"prop": (0.28, 0.18 * h + 0.1), "prop_close": (0.12, 0.05 * h + 0.05), "card": (-0.32, 0.4 * h + 0.2)}[name]
        pos = tgt + Vector((side0 * dist, -dist, up))
        # a host sliver at the frame edge looks like a mistake: the shot loop hides her for this shot instead
        HIDE_HOST.add(name) if 0.0 < host_visibility(pos, tgt, vt, ht) < 1.0 else None
    return {"pos": tuple(pos), "target": tuple(tgt), "end": tuple(tgt + (pos - tgt) * 0.93), "lens": lens}


def host_visibility(pos, tgt, vt, ht):
    """Fraction of host sample points inside the frame (0 = out, 1 = fully in); 0 when there is no host."""
    if arm is None:
        return 0.0
    fwd = (tgt - pos).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    upv = right.cross(fwd)
    hh = float(CMETA.get("height", 1.55))
    # wide samples + 12% margin: hair, braid and gesturing arms reach well past the torso
    pts = [HOST_POS + Vector((dx, dy, z * hh)) for dx in (-0.38, 0.0, 0.38) for dy in (-0.2, 0.2) for z in (0.05, 0.35, 0.65, 0.95)]
    inside = edge = 0
    for q in pts:
        d = q - pos
        zc = d.dot(fwd)
        if zc <= 0.05:
            continue
        ax, ay = abs(d.dot(right) / (zc * ht)), abs(d.dot(upv) / (zc * vt))
        if ax < 0.9 and ay < 0.95:
            inside += 1
        elif ax < 1.12 and ay < 1.1:
            edge += 1
    if edge:
        return 0.5  # something sits on the frame edge: neither clean in nor clean out
    return inside / len(pts)


def ground_z(v):
    """Terrain height under v (ray cast down onto set geometry; 0 if nothing)."""
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, _n, _i, ob, _m = sc.ray_cast(dg, Vector((v.x, v.y, 60.0)), Vector((0, 0, -1)))
    while hit and ob is not None and not ob.name.startswith(("Ground", "Studio_Floor", "Class_Floor", "Kitchen_Floor", "Cozy_Floor")):
        hit, loc, _n, _i, ob, _m = sc.ray_cast(dg, loc - Vector((0, 0, 0.01)), Vector((0, 0, -1)))
    return loc.z if hit else 0.0


DYN_SHOTS = ("ots", "low", "ecu", "top", "side", "host_low", "orbit")


def dyn_cam(name, bi):
    """Reference-reel shot language, computed from the host + focused prop:
    ots (over the host's shoulder onto the prop), low (worm's-eye looking up at host + prop), ecu (extreme face
    close-up), host_low (low angle on the host), top (top-down map view of the prop, for arrow diagrams),
    side (profile view of the prop), orbit (slow arc around the prop)."""
    fid = focus_of(bi)
    P_ = PROPS.get(fid)
    hh = float(CMETA.get("height", 1.55)) if arm is not None else 1.5
    eye = float(CMETA.get("eye_z", hh * 0.86)) if arm is not None else 1.3
    hp = HOST_POS if arm is not None else Vector(ANCH.get("host", (-0.9, 0.3, 0)))
    if P_ is not None:
        fb_, ph, pr_ = frame_of(P_)
        pc = fb_ + Vector((0, 0, ph * 0.45))
    else:
        pc, ph, pr_ = Vector(ANCH.get("center", (1.2, 1.2, 0))) + Vector((0, 0, 0.8)), 1.6, 1.0
    vt = 18.0 / 28
    d = (pc - hp)
    d.z = 0
    d = d.normalized() if d.length > 1e-3 else Vector((1, 0, 0))
    perp = Vector((d.y, -d.x, 0))  # right-hand side when looking along d
    if name == "ots":
        big_ = P_ is not None and P_.get("big")
        back = 1.05 if big_ else 2.3
        pos = hp - d * back + perp * (0.42 if big_ else 0.75) + Vector((0, 0, eye + (0.3 if big_ else 0.45)))
        return {"pos": tuple(pos), "target": tuple(pc), "end": tuple(pos + d * 0.12), "lens": 26}
    if name == "low":
        # worm's-eye in front of the host: she stands big on the left, the prop towers behind her
        mid = hp.lerp(Vector((pc.x, pc.y, 0)), 0.5)
        if P_ is not None and P_.get("big"):
            pos = hp + Vector((0.55, -2.7, 0.25))
            tgt = Vector((mid.x, mid.y, max(1.3, ph * 0.55)))
        else:  # small prop: camera square-on to the host-prop pair so both fit
            sep = Vector((pc.x - hp.x, pc.y - hp.y, 0))
            nrm = Vector((sep.y, -sep.x, 0)).normalized() if sep.length > 1e-3 else Vector((0, -1, 0))
            if nrm.y > 0:
                nrm = -nrm
            dist = max(2.2, (sep.length + 0.8) * 1.1 / 2 / 0.46)
            pos = Vector((mid.x, mid.y, 0)) + nrm * dist + Vector((0, 0, 0.22))
            tgt = Vector((mid.x, mid.y, 1.05))
            return {"pos": tuple(pos), "target": tuple(tgt), "end": tuple(pos + Vector((0.2, 0.15, 0.04))), "lens": 22}
        return {"pos": tuple(pos), "target": tuple(tgt), "end": tuple(pos + Vector((0.25, 0.2, 0.05))), "lens": 18}
    if name == "host_low":
        pos = hp + Vector((0.35, -1.5, 0.35))
        tgt = hp + Vector((0, 0, eye - 0.05))
        return {"pos": tuple(pos), "target": tuple(tgt), "end": tuple(pos + Vector((0, 0.12, 0))), "lens": 28}
    if name == "ecu":  # head-and-shoulders punch-in (closer exposed the projected face texture)
        pos = hp + Vector((0.08, -1.6, eye - 0.02))
        tgt = hp + Vector((0, 0, eye - 0.16))
        return {"pos": tuple(pos), "target": tuple(tgt), "end": tuple(pos + Vector((0, 0.08, 0))), "lens": 45}
    if name == "top":
        span = max(pr_ * 2.2, min((pc - hp).length + 2.5, 14.0), 4.0)
        if P_ is not None and P_.get("big"):
            span = max(span, min(P_["radius"] * 1.6, 18.0))
            pc = P_["base"] + Vector((0, 0, ph * 0.45))
        z = span / 2 / (18.0 / 30) + 1.0
        cx = (pc + hp) / 2 if (pc - hp).length < pr_ * 1.5 + 3 else pc.copy()
        pos = Vector((cx.x, cx.y - 0.6, z))
        return {"pos": tuple(pos), "target": (cx.x, cx.y, 0.0), "end": tuple(pos + Vector((0, 0, -z * 0.06))), "lens": 30}
    if name == "side":
        dist = max(ph * 1.25 / 2 / vt, pr_ * 1.6) + pr_
        if P_ is not None and P_.get("big"):  # diagonal 3/4 view of the front face (a pure profile would sit in the hills)
            pos = pc + Vector((dist * 0.75, -dist * 0.6, ph * 0.3))
        else:
            pos = pc + Vector((dist, 0.4, ph * 0.15))
        return {"pos": tuple(pos), "target": tuple(pc), "end": tuple(pc + (pos - pc) * 0.92), "lens": 28}
    if name == "orbit":
        dist = max(ph * 1.3 / 2 / vt, pr_ * 1.5) + pr_
        pos = pc + Vector((-dist * 0.55, -dist * 0.85, ph * 0.35))
        end = pc + Vector((dist * 0.55, -dist * 0.85, ph * 0.35))
        return {"pos": tuple(pos), "target": tuple(pc), "end": tuple(end), "lens": 28}
    return None


# ------------------------------------------------------------------ diagram arrows (beat "arrows")
ARROW_MAT = None


def make_arrow(a, b, color, name, z=0.06, width=0.35):
    """Flat chunky pixel arrow on the ground from a to b (Vectors), drawn above the ground/water."""
    global ARROW_MAT
    import abs_pix as XP
    m = XP.mat(color, name=f"arrow_{color}", emit=True, fog=False)
    d = (b - a)
    d.z = 0
    L = d.length
    if L < 1e-3:
        return None
    u = d / L
    pp = Vector((-u.y, u.x, 0))
    head = min(L * 0.4, width * 2.4)
    w2, hw = width / 2, width * 1.2
    sh = L - head
    pts = [a + pp * w2, a + u * sh + pp * w2, a + u * sh + pp * hw, b, a + u * sh - pp * hw, a + u * sh - pp * w2, a - pp * w2]
    zz = max(a.z, b.z) + z
    vs = [(p.x, p.y, zz) for p in pts]
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs + [(v[0], v[1], zz + 0.05) for v in vs], [],
                   [list(range(7)), list(range(7, 14))[::-1]] + [[i, (i + 1) % 7, (i + 1) % 7 + 7, i + 7] for i in range(7)])
    me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    sc.collection.objects.link(o)
    return o


def pt_of(v):
    if isinstance(v, str):
        if v in PROPS:
            return PROPS[v]["base"] + Vector((0, 0, PROPS[v]["height"] * 0.5))
        if v == "host" and arm is not None:
            return HOST_POS + Vector((0, 0, 0.9))
        return Vector(ANCH.get(v, (0, 0, 0)))
    v = list(v) + [0] * (3 - len(v))
    return Vector(v)


ARROWS = []
for _b in BEATS:
    for k_, ar in enumerate(_b.get("arrows") or []):
        try:
            a_, b_ = pt_of(ar.get("from")), pt_of(ar.get("to"))
            if ar.get("rel"):  # relative to the focused prop
                base_ = PROPS[focus_of(_b["i"])]["base"] if focus_of(_b["i"]) in PROPS else Vector((0, 0, 0))
                a_, b_ = a_ + base_, b_ + base_
            o_ = make_arrow(a_, b_, ar.get("color", "#2f7fe0"), f"Arrow{_b['i']}_{k_}", width=float(ar.get("width", 0.35)))
            if o_ is not None:
                t0_ = _b["start"] if _b["i"] else 0.0
                ARROWS.append((o_, F(t0_ + float(ar.get("delay", 0.3))), F(_b["until"]), _b["i"]))
        except Exception as e_:
            log("arrow skipped:", e_)
def _arrow_windows(bi, fa_, fb_):
    """Arrows are diagram overlays: show them only in the beat's top/side shots (else the whole beat)."""
    w = [(max(fa_, F(t0)), F(t1)) for (nm_, t0, t1, b_) in SHOTS if b_ == bi and nm_ in ("top", "side")]
    return w or [(fa_, fb_)]


for o_, fa_, fb_, bi_ in ARROWS:
    o_.hide_render = True
    o_.keyframe_insert("hide_render", frame=1)
    for wa, wb in _arrow_windows(bi_, fa_, fb_):
        o_.hide_render = False
        o_.keyframe_insert("hide_render", frame=wa)
        o_.hide_render = True
        o_.keyframe_insert("hide_render", frame=wb)
if ARROWS:
    log("diagram arrows", len(ARROWS))

sc.timeline_markers.clear()
OCCLUDERS = []  # (prop id, first frame, last frame): small props hidden while they would block the lens
cams = []
HOST_HIDDEN = []  # (first frame, last frame) of shots where the host would only be a sliver at the edge
for i, (name, t0, t1, bi) in enumerate(SHOTS):
    fid = focus_of(bi)
    HIDE_HOST.clear()
    if name in ("prop", "prop_close", "card", "two") and fid in PROPS:
        pr = prop_cam(name, fid)
        if name in HIDE_HOST and arm is not None:
            HOST_HIDDEN.append((F(t0), max(F(t0), F(t1) - 1)))
    elif name in DYN_SHOTS:
        pr = dyn_cam(name, bi) or S["cams"]["wide"]
        if name in ("top", "side", "orbit") and arm is not None:
            fp = Vector(pr["pos"])
            _vt = 18.0 / pr["lens"]
            if 0.0 < host_visibility(fp, Vector(pr["target"]), _vt, _vt * rx / ry) < 1.0:
                HOST_HIDDEN.append((F(t0), max(F(t0), F(t1) - 1)))
    elif name in ("prop", "prop_close") and fid == "cat" and rig is not None:
        pr = S["cams"].get("cat") or S["cams"]["wide"]
    else:
        pr = S["cams"].get(name, S["cams"]["wide"])
    if pr.get("follow") == "cat" and rig is None:
        pr = S["cams"]["wide"]
    cam = bpy.data.objects.new(f"Cam{i:02d}_{name}", bpy.data.cameras.new(f"Cam{i:02d}"))
    sc.collection.objects.link(cam)
    cam.data.lens = pr.get("lens", 35)
    cam.data.clip_start = 0.05
    cam.data.clip_end = 600
    if pr.get("follow") == "cat" and rig is not None:
        # track the cat's real (evaluated) body/head centre so walks and rolls stay in frame
        fa, fb = F(t0), max(F(t0), F(t1) - 1)
        ema = None
        for fr in list(range(fa, fb + 1, 3)) + ([fb] if (fb - fa) % 3 else []):
            sc.frame_set(fr)
            ctr = (rig["body"].matrix_world.translation + rig["head"].matrix_world.translation) * 0.5
            ema = ctr.copy() if ema is None else ema.lerp(ctr, 0.35)
            k = (fr - fa) / max(1, fb - fa)
            pos = ema + Vector(pr["offset"])
            tgt = ema + Vector(pr["aim"])
            C.look_at(cam, pos.lerp(tgt, pr.get("dolly", 0.1) * k), tgt)
            cam.keyframe_insert("location", frame=fr)
            cam.keyframe_insert("rotation_euler", frame=fr)
        m = sc.timeline_markers.new(f"S{i:02d}_{name}", frame=fa)
        m.camera = cam
        cams.append(cam)
        continue
    pos, tgt = Vector(pr["pos"]), Vector(pr["target"])
    end = Vector(pr.get("end", pr["pos"]))
    # never park a lens inside another prop (an orbit around the millstones started inside the chute)
    for _k in range(10):
        bad = False
        for pid_, Q in PROPS.items():
            if pid_ == fid or Q.get("big"):
                continue
            for v_ in (pos, end):
                if math.hypot(v_.x - Q["base"].x, v_.y - Q["base"].y) < Q["radius"] + 0.35 and v_.z < Q["base"].z + Q["height"] + 0.3:
                    bad = True
        if not bad:
            break
        pos = tgt + (pos - tgt) * 1.18
        end = tgt + (end - tgt) * 1.18
    # a small prop between the lens and the subject is hidden for this shot (props are staging, not set dressing)
    if name not in ("wide", "establish", "two"):
        for pid_, Q in PROPS.items():
            if pid_ == fid or Q.get("big"):
                continue
            for k_ in range(1, 9):
                q_ = pos.lerp(tgt, k_ / 10.0)
                if math.hypot(q_.x - Q["base"].x, q_.y - Q["base"].y) < Q["radius"] + 0.15 and q_.z < Q["base"].z + Q["height"] + 0.1:
                    OCCLUDERS.append((pid_, F(t0), max(F(t0), F(t1) - 1)))
                    break
    if V3:  # never below the terrain (low shots outside the flat stage looked up through the ground)
        pos.z = max(pos.z, ground_z(pos) + 0.22)
        end.z = max(end.z, ground_z(end) + 0.22)
    for fr, pp in ((F(t0), pos), (max(F(t0), F(t1) - 1), end)):
        C.look_at(cam, pp, tgt)
        cam.keyframe_insert("location", frame=fr)
        cam.keyframe_insert("rotation_euler", frame=fr)
    m = sc.timeline_markers.new(f"S{i:02d}_{name}", frame=F(t0))
    m.camera = cam
    cams.append(cam)
# ---- lens clearance: set dressing (trees, tufts, rocks) right in front of a camera is removed
KEEP_PREFIX = ("Ground", "Nile", "Lake", "Sun", "Cloud", "Ridge", "Fountain", "Studio_", "Class_", "Kitchen_", "Cozy_")
_cam_lines = []
for cam in cams:
    ad = cam.animation_data
    if not ad or not ad.action:
        continue
    _fcs = list(getattr(ad.action, "fcurves", [])) or [fc for lay in getattr(ad.action, "layers", []) for st in lay.strips
                                                         for bag in st.channelbags for fc in bag.fcurves]
    fr_set = sorted({int(k.co[0]) for fc in _fcs for k in fc.keyframe_points} or {1})
    for fr in (fr_set[0], fr_set[-1]):
        sc.frame_set(fr)
        mw = cam.matrix_world
        _cam_lines.append((mw.translation.copy(), (mw.to_3x3() @ Vector((0, 0, -1))).normalized()))
sc.frame_set(1)
_removed = 0
if V3:
    for o in list(sc.objects):
        if o.type != "MESH" or o.name not in WORLD_OBJS or o.name.startswith(KEEP_PREFIX):
            continue
        dmx = max(o.dimensions.x, o.dimensions.y)
        if dmx > 18:
            continue
        L_ = o.matrix_world.translation
        top = L_.z + o.dimensions.z
        hit = False
        for (cp, cd) in _cam_lines:
            for k in range(14):
                q = cp + cd * (0.3 + k * 0.6)  # first ~8 m of every view ray
                if math.hypot(q.x - L_.x, q.y - L_.y) < 0.55 + dmx * 0.45 and L_.z - 0.3 < q.z < top + 0.3:
                    hit = True
                    break
            if hit:
                break
        if hit:
            bpy.data.objects.remove(o, do_unlink=True)
            _removed += 1
    log("lens clearance removed", _removed, "dressing objects")
for pid_, fa_, fb_ in OCCLUDERS:
    r_ = PROPS[pid_]["root"]
    for fr_ in range(fa_, fb_ + 1):
        r_.scale = (1e-4,) * 3
        r_.keyframe_insert("scale", frame=fr_)
if OCCLUDERS:
    log("props hidden while blocking a lens:", [(o[0], o[1], o[2]) for o in OCCLUDERS])
sc.camera = cams[0]
if HOST_HIDDEN and arm is not None:
    host_meshes = [o for o in col.all_objects if o.type == "MESH"]
    for o in host_meshes:
        o.hide_render = False
        o.keyframe_insert("hide_render", frame=1)
        for fa, fb in HOST_HIDDEN:
            o.hide_render = True
            o.keyframe_insert("hide_render", frame=fa)
            o.hide_render = False
            o.keyframe_insert("hide_render", frame=fb + 1)
    log("host hidden in", len(HOST_HIDDEN), "prop shots (she would only be a sliver at the frame edge)")
bpy.context.preferences.edit.keyframe_new_interpolation_type = "BEZIER"
if FACE_TEX is not None and FACE_TEX[0].node_tree.animation_data and FACE_TEX[0].node_tree.animation_data.action:
    _act = FACE_TEX[0].node_tree.animation_data.action
    _fcs = list(getattr(_act, "fcurves", [])) or [fc for lay in getattr(_act, "layers", []) for st in lay.strips
                                                    for bag in st.channelbags for fc in bag.fcurves]
    for fc in _fcs:
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT"

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(EP, "scene.blend"), compress=True)
log("SAVED scene.blend frames", NF)

if "--still" in argv:
    ts = [float(x) for x in arg("--still").split(",") if x.strip()]
    os.makedirs(os.path.join(EP, "stills"), exist_ok=True)
    for t in ts:
        f = min(NF, F(t))
        sc.frame_set(f)
        sc.render.filepath = os.path.join(EP, "stills", f"t{t:06.2f}.png")
        bpy.ops.render.render(write_still=True)
        log("STILL", t)
if "--render" in argv:
    a, b = 1, NF
    if "--frames" in argv:
        i = argv.index("--frames")
        a, b = int(argv[i + 1]), int(argv[i + 2])
    sc.frame_start, sc.frame_end = a, min(b, NF)
    sc.render.image_settings.file_format = "PNG"
    if "--resume" in argv:  # keep frames that already exist (interrupted render)
        sc.render.use_overwrite = False
        sc.render.use_placeholder = True
    os.makedirs(os.path.join(EP, "frames"), exist_ok=True)
    sc.render.filepath = os.path.join(EP, "frames", "f_")
    bpy.ops.render.render(animation=True)
    log("RENDER DONE", a, b)
