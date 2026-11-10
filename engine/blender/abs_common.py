"""Shared Blender helpers for AcreBlenderStudio engine scripts (run inside Blender's Python).

Toon/pixel materials, inverted-hull outlines, pixel images from numpy, texture recolouring,
VRoid posing (T-pose-relative rotations) and small geometry builders.
"""
import math
import bpy
import numpy as np
from mathutils import Matrix, Vector


# ------------------------------------------------------------------ basics
def Rot(axis, deg):
    return Matrix.Rotation(math.radians(deg), 3, axis)


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def win(t, a, b, ramp=0.25):
    """1 inside [a,b] with smooth ramps, 0 outside."""
    if t < a - 1e-6 or t > b + 1e-6:
        return 0.0
    return smooth(min((t - a) / max(1e-3, ramp), (b - t) / max(1e-3, ramp)))


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


# ------------------------------------------------------------------ images
def img_from_array(name, arr):
    """arr: HxWx3/4 float sRGB-ish values, row 0 = TOP. Packed into the .blend."""
    h, w, ch = arr.shape
    im = bpy.data.images.new(name, w, h, alpha=True)
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :ch] = arr
    im.pixels.foreach_set(rgba[::-1].ravel())
    im.pack()
    return im


def img_to_array(im):
    """Returns HxWx4 float array, row 0 = TOP (Blender stores bottom-up)."""
    w, h = im.size
    buf = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)[::-1].copy()


def array_to_img(im, arr):
    im.pixels.foreach_set(np.ascontiguousarray(arr[::-1]).ravel())
    im.update()
    try:
        im.pack()
    except Exception:
        pass


def luminance(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def region_mask(h, w, region):
    """region = [x0, y0, x1, y1] in 0..1, y measured from the TOP of the image."""
    m = np.zeros((h, w), bool)
    if region is None:
        m[:] = True
        return m
    x0, y0, x1, y1 = region
    m[int(y0 * h):int(math.ceil(y1 * h)), int(x0 * w):int(math.ceil(x1 * w))] = True
    return m


def recolor(im, rules):
    """Apply recolour rules to an image (in place). Each rule:
    {mode: 'lum_map'|'fill', dark:'#hex', light:'#hex', color:'#hex', region:[x0,y0,x1,y1],
     lum:[lo,hi] (select by luminance 0..1), min_sat / max_sat (select by saturation),
     blue_only:bool, stretch:[plo,phi] percentile normalisation, strength:0..1}"""
    a = img_to_array(im)
    rgb = a[..., :3]
    h, w = rgb.shape[:2]
    L = luminance(rgb)
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
    for r in rules:
        m = region_mask(h, w, r.get("region"))
        if "lum" in r:
            lo, hi = r["lum"]
            m &= (L >= lo) & (L <= hi)
        if "min_sat" in r:
            m &= sat >= r["min_sat"]
        if "max_sat" in r:
            m &= sat <= r["max_sat"]
        if r.get("blue_only"):
            m &= (rgb[..., 2] > rgb[..., 0] + 0.04)
        if r.get("alpha_min") is not None:
            m &= a[..., 3] >= r["alpha_min"]
        if not m.any():
            continue
        k = float(r.get("strength", 1.0))
        if r["mode"] == "fill":
            c = np.array(hex_rgb(r["color"]), np.float32)
            rgb[m] = rgb[m] * (1 - k) + c * k
        elif r["mode"] == "lum_map":
            plo, phi = r.get("stretch", [2, 98])
            vals = L[m]
            lo, hi = np.percentile(vals, plo), np.percentile(vals, phi)
            t = np.clip((L - lo) / max(1e-4, hi - lo), 0, 1) ** float(r.get("gamma", 1.0))
            d = np.array(hex_rgb(r["dark"]), np.float32)
            li = np.array(hex_rgb(r["light"]), np.float32)
            new = d[None, None, :] + (li - d)[None, None, :] * t[..., None]
            rgb[m] = rgb[m] * (1 - k) + new[m] * k
        elif r["mode"] == "stripe":  # horizontal stripes in image space
            c = np.array(hex_rgb(r["color"]), np.float32)
            for y0, y1 in r["rows"]:
                mm = m.copy()
                mm[:int(y0 * h)] = False
                mm[int(math.ceil(y1 * h)):] = False
                rgb[mm] = c * (0.85 + 0.15 * L[mm, None])
    a[..., :3] = rgb
    array_to_img(im, a)


def downscale(im, factor, min_size=32):
    w, h = im.size
    if factor > 1 and w > min_size:
        im.scale(max(min_size, w // factor), max(min_size, h // factor))


def kmeans_palette(px, k, iters=10, seed=0):
    """px: Nx3 float. Returns (palette kx3, labels N). Deterministic k-means++-lite on a sample."""
    rng = np.random.default_rng(seed)
    sample = px[rng.choice(len(px), min(len(px), 20000), replace=False)] if len(px) > 20000 else px
    # init: spread by luminance quantiles (stable, avoids empty clusters)
    order = np.argsort(sample @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    cent = sample[order[np.linspace(0, len(order) - 1, k).astype(int)]].copy()
    for _ in range(iters):
        d = ((sample[:, None, :] - cent[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                cent[j] = sample[m].mean(0)
    lab = np.empty(len(px), np.int32)
    for s in range(0, len(px), 200000):  # chunked full assignment
        d = ((px[s:s + 200000, None, :] - cent[None, :, :]) ** 2).sum(-1)
        lab[s:s + 200000] = d.argmin(1)
    return cent, lab


def pixelize(im, max_size=128, colors=16, alpha_cut=0.5):
    """Pixel-art pass: box-average downscale so the long side is max_size texels, then quantise to a
    small k-means palette (kills gradients). Alpha is thresholded (hard pixel edges). In place."""
    w, h = im.size
    if w == 0 or h == 0:
        return
    s = min(1.0, max_size / max(w, h))
    nw, nh = max(4, int(round(w * s))), max(4, int(round(h * s)))
    a = img_to_array(im)
    if (nw, nh) != (w, h):  # box filter: average whole blocks (Blender's scale() is bilinear-ish)
        fy, fx = h / nh, w / nw
        ys = (np.arange(nh + 1) * fy).astype(int)
        xs = (np.arange(nw + 1) * fx).astype(int)
        cs = a.cumsum(0).cumsum(1)
        cs = np.pad(cs, ((1, 0), (1, 0), (0, 0)))
        tot = cs[ys[1:]][:, xs[1:]] - cs[ys[:-1]][:, xs[1:]] - cs[ys[1:]][:, xs[:-1]] + cs[ys[:-1]][:, xs[:-1]]
        area = ((ys[1:] - ys[:-1])[:, None] * (xs[1:] - xs[:-1])[None, :])[..., None]
        a = tot / np.maximum(area, 1)
        im.scale(nw, nh)
    rgb = a[..., :3].reshape(-1, 3).astype(np.float32)
    alpha = a[..., 3].reshape(-1)
    vis = alpha >= alpha_cut
    if colors and vis.sum() > colors:
        pal, lab = kmeans_palette(rgb[vis], colors)
        rgb[vis] = pal[lab]
    a = np.concatenate([rgb.reshape(nh, nw, 3), np.where(vis, 1.0, 0.0).reshape(nh, nw, 1)], -1).astype(np.float32)
    array_to_img(im, a)


# ------------------------------------------------------------------ materials
def _nodes(m):
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return nt, nt.nodes.new("ShaderNodeOutputMaterial")


def toon_mat(name, color=(1, 1, 1), image=None, shade=0.78, shade_tint=(0.86, 0.78, 0.92),
             alpha=False, flat=False, uv_scale=1.0, flash=None, threshold=0.12):
    """Emission-based 2-step cel material. color is sRGB (0..1)."""
    m = bpy.data.materials.new(name)
    nt, out = _nodes(m)
    N = nt.nodes
    L = nt.links
    if image is not None:
        tex = N.new("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Closest"
        if uv_scale != 1.0:
            tc = N.new("ShaderNodeTexCoord")
            mp = N.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (uv_scale, uv_scale, uv_scale)
            L.new(tc.outputs["UV"], mp.inputs[0])
            L.new(mp.outputs[0], tex.inputs[0])
        base = tex.outputs["Color"]
    else:
        rgb = N.new("ShaderNodeRGB")
        lin = srgb_to_lin(color)
        rgb.outputs[0].default_value = (float(lin[0]), float(lin[1]), float(lin[2]), 1)
        base = rgb.outputs[0]
        tex = None
    if flat:
        col = base
    else:
        dif = N.new("ShaderNodeBsdfDiffuse")
        s2r = N.new("ShaderNodeShaderToRGB")
        ramp = N.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"
        st = srgb_to_lin([shade * shade_tint[0], shade * shade_tint[1], shade * shade_tint[2]])
        ramp.color_ramp.elements[0].color = (float(st[0]), float(st[1]), float(st[2]), 1)
        ramp.color_ramp.elements[1].position = threshold
        ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
        L.new(dif.outputs[0], s2r.inputs[0])
        L.new(s2r.outputs[0], ramp.inputs[0])
        mul = N.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1
        L.new(base, mul.inputs[6])
        L.new(ramp.outputs[0], mul.inputs[7])
        col = mul.outputs[2]
    if flash is not None:  # animatable additive tint (node named FLASH, input 0 = amount)
        fl = N.new("ShaderNodeMix")
        fl.data_type = "RGBA"
        fl.name = "FLASH"
        fl.inputs[0].default_value = 0
        fc = srgb_to_lin(flash)
        fl.inputs[7].default_value = (float(fc[0]), float(fc[1]), float(fc[2]), 1)
        L.new(col, fl.inputs[6])
        col = fl.outputs[2]
    em = N.new("ShaderNodeEmission")
    L.new(col, em.inputs[0])
    if alpha and tex is not None:
        tr = N.new("ShaderNodeBsdfTransparent")
        mix = N.new("ShaderNodeMixShader")
        L.new(tex.outputs["Alpha"], mix.inputs[0])
        L.new(tr.outputs[0], mix.inputs[1])
        L.new(em.outputs[0], mix.inputs[2])
        L.new(mix.outputs[0], out.inputs[0])
        try:
            m.surface_render_method = "DITHERED"
        except Exception:
            pass
    else:
        L.new(em.outputs[0], out.inputs[0])
    return m


def flat_mat(name, color, strength=1.0):
    m = bpy.data.materials.new(name)
    nt, out = _nodes(m)
    em = nt.nodes.new("ShaderNodeEmission")
    lin = srgb_to_lin(color)
    em.inputs[0].default_value = (float(lin[0]), float(lin[1]), float(lin[2]), 1)
    em.inputs[1].default_value = strength
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


def outline_mat(color=(0.12, 0.07, 0.1)):
    name = "ABS_Outline"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = flat_mat(name, color)
    m.use_backface_culling = True
    try:
        m.use_backface_culling_shadow = True
    except Exception:
        pass
    return m


def add_outline(obj, thickness=0.006, color=(0.12, 0.07, 0.1)):
    """Inverted hull: solidify with flipped normals + backface-culled dark material."""
    if obj.type != "MESH":
        return
    om = outline_mat(color)
    if om.name not in [m.name for m in obj.data.materials if m]:
        obj.data.materials.append(om)
    idx = [i for i, m in enumerate(obj.data.materials) if m and m.name == om.name][0]
    mod = obj.modifiers.new("ABS_Outline", "SOLIDIFY")
    sc = obj.matrix_world.to_scale()
    s = max(1e-4, (abs(sc.x) + abs(sc.y) + abs(sc.z)) / 3.0)
    mod.thickness = -abs(thickness) / s
    mod.offset = 1.0
    mod.use_flip_normals = True
    mod.use_rim = False
    mod.material_offset = idx
    mod.use_quality_normals = True
    for mat in obj.data.materials:
        if mat and mat.name != om.name:
            mat.use_backface_culling = False


# ------------------------------------------------------------------ geometry
def add_prim(kind, name, loc=(0, 0, 0), scale=(1, 1, 1), rot=(0, 0, 0), mat=None, smooth_shade=False,
             parent=None, **kw):
    ops = {
        "cube": bpy.ops.mesh.primitive_cube_add,
        "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
        "ico": bpy.ops.mesh.primitive_ico_sphere_add,
        "cyl": bpy.ops.mesh.primitive_cylinder_add,
        "cone": bpy.ops.mesh.primitive_cone_add,
        "plane": bpy.ops.mesh.primitive_plane_add,
        "torus": bpy.ops.mesh.primitive_torus_add,
    }
    ops[kind](location=loc, rotation=rot, **kw)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    if mat is not None:
        o.data.materials.append(mat)
    if smooth_shade:
        bpy.ops.object.shade_smooth()
    if parent is not None:
        o.parent = parent
        o.matrix_parent_inverse = parent.matrix_world.inverted()
    return o


def parent_to_bone(obj, arm, bone):
    mw = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    bpy.context.view_layer.update()
    obj.matrix_world = mw


def look_at(cam, loc, target):
    cam.location = Vector(loc)
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# ------------------------------------------------------------------ VRoid posing
CTRL_BONES = [
    "J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_Neck", "J_Bip_C_Head",
    "J_Bip_L_Shoulder", "J_Bip_R_Shoulder",
    "J_Bip_L_UpperArm", "J_Bip_R_UpperArm", "J_Bip_L_LowerArm", "J_Bip_R_LowerArm",
    "J_Bip_L_Hand", "J_Bip_R_Hand",
    "J_Bip_L_UpperLeg", "J_Bip_R_UpperLeg", "J_Bip_L_LowerLeg", "J_Bip_R_LowerLeg",
    "J_Bip_L_Foot", "J_Bip_R_Foot",
]
FINGERS = ["Thumb", "Index", "Middle", "Ring", "Little"]
for _s in "LR":
    for _f in FINGERS:
        for _i in (1, 2, 3):
            CTRL_BONES.append(f"J_Bip_{_s}_{_f}{_i}")


def P(**kw):
    """P(L_UpperArm=Rot(...)) -> {'J_Bip_L_UpperArm': Matrix3}"""
    return {"J_Bip_" + k: v for k, v in kw.items()}


def merged(*ds):
    o = {}
    for d in ds:
        o.update(d)
    return o


def blend_into(cur, target, w):
    if w <= 0:
        return
    for b, M in target.items():
        q0 = cur.get(b, Matrix.Identity(3)).to_quaternion()
        q1 = M.to_quaternion()
        if q0.dot(q1) < 0:
            q1.negate()
        cur[b] = q0.slerp(q1, min(1.0, w)).to_matrix()


def comb(a, b):
    o = dict(a)
    for k, M in b.items():
        o[k] = o.get(k, Matrix.Identity(3)) @ M
    return o


def apply_pose(arm, spec, prev=None, frame=None):
    """spec: bone -> 3x3 rotation in the T-pose (parent-relative, world-axis) frame."""
    for b in CTRL_BONES:
        if b not in arm.pose.bones:
            continue
        pb = arm.pose.bones[b]
        pb.rotation_mode = "QUATERNION"
        S = spec.get(b, Matrix.Identity(3))
        R = arm.data.bones[b].matrix_local.to_3x3()
        q = (R.inverted() @ S @ R).to_quaternion()
        if prev is not None:
            if b in prev and prev[b].dot(q) < 0:
                q.negate()
            prev[b] = q
        pb.rotation_quaternion = q
        if frame is not None:
            pb.keyframe_insert("rotation_quaternion", frame=frame)


def finger_curl(side, finger, deg, spread=0.0):
    """Curl one finger (3 segments). side 'L'|'R'. Curl toward the palm (palm faces -Z in T-pose)."""
    sgn = 1 if side == "L" else -1
    out = {}
    if finger == "Thumb":
        # thumb curls across the palm: rotate about the hand's length axis-ish
        out[f"J_Bip_{side}_Thumb1"] = Rot("Z", -sgn * 0.0) @ Rot("X", sgn * deg * 0.25)
        out[f"J_Bip_{side}_Thumb2"] = Rot("Z", sgn * deg * 0.5)
        out[f"J_Bip_{side}_Thumb3"] = Rot("Z", sgn * deg * 0.6)
        return out
    for i, k in ((1, 1.0), (2, 1.1), (3, 0.8)):
        R = Rot("Y", sgn * deg * k)
        if i == 1 and spread:
            R = Rot("Z", sgn * spread) @ R
        out[f"J_Bip_{side}_{finger}{i}"] = R
    return out


def hand_shape(side, shape):
    o = {}
    if shape == "fist":
        for f in FINGERS:
            o.update(finger_curl(side, f, 85 if f != "Thumb" else 60))
    elif shape == "peace":
        o.update(finger_curl(side, "Index", 2, spread=-9))
        o.update(finger_curl(side, "Middle", 2, spread=7))
        o.update(finger_curl(side, "Ring", 88))
        o.update(finger_curl(side, "Little", 88))
        o.update(finger_curl(side, "Thumb", 70))
    elif shape == "point":
        o.update(finger_curl(side, "Index", 0))
        for f in ("Middle", "Ring", "Little"):
            o.update(finger_curl(side, f, 88))
        o.update(finger_curl(side, "Thumb", 55))
    elif shape == "relaxed":
        for f in FINGERS:
            o.update(finger_curl(side, f, 18 if f != "Thumb" else 10))
    elif shape == "open":
        for f in FINGERS:
            o.update(finger_curl(side, f, 3))
    return o


def shape_key(face, suffix):
    for k in face.data.shape_keys.key_blocks:
        if k.name.endswith(suffix):
            return k
    return None


def bvh_for(obj):
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    return BVHTree.FromObject(ev, dg), ev.matrix_world.copy()
