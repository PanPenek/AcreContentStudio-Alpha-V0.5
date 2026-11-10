"""Clean a projected character (v0.3 look): fixes the 'unfinished texture' problems Patryk saw.

blender --background --python engine/blender/clean_character.py -- <char_dir> [--src character.projected_v1.blend] [--res 1024] [--k 28]

1. Texture: every expression atlas is palette-quantised (shared k-means palette, head colours kept), a 3x3
   majority filter removes speckle noise, and island gutters (black) are flood-filled from the nearest island
   so seams can't bleed dark streaks / torn edges. Downscaled to --res with a mode filter (crisp, chunky).
2. Hands: vertices weighted to the hand/finger bones get a clean flat skin material (no smeared art).
3. Shading: the glossy Principled BSDF (white highlight blotches) is replaced by the abs_pix soft-toon emission
   shader (no specular), driven by the same FaceIdx expression chain. Outline thinner + warm dark.
Writes <char_dir>/character.blend (keep the source blend as the backup).
"""
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import abs_common as C  # noqa: E402
import abs_pix as X  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
CDIR = os.path.abspath(argv[0])


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


SRC = os.path.join(CDIR, arg("--src", "character.projected_v1.blend"))
RES = int(arg("--res", 1024))
K = int(arg("--k", 28))
bpy.ops.wm.open_mainfile(filepath=SRC)
body = bpy.data.objects["Body"]
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mat = next(m for m in body.data.materials if m and m.name == "char_final")
nt = mat.node_tree
face_imgs = [n.image for n in nt.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image]
print("[clean] expressions:", [i.name for i in face_imgs])


# ------------------------------------------------------------------ 1. textures
def load(im):
    w, h = im.size
    a = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def kmeans(px, k, iters=12, seed=0):
    rng = np.random.default_rng(seed)
    c = px[rng.choice(len(px), k, replace=False)]
    for _ in range(iters):
        d = ((px[:, None, :] - c[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            s = px[lab == j]
            if len(s):
                c[j] = s.mean(0)
    return c


def mode_down(idx, f):
    """Downscale an index map by integer factor f taking the most common index per block."""
    h, w = idx.shape
    blk = idx[:h // f * f, :w // f * f].reshape(h // f, f, w // f, f).transpose(0, 2, 1, 3).reshape(h // f, w // f, f * f)
    out = np.empty(blk.shape[:2], np.int32)
    best = np.zeros(blk.shape[:2], np.int32)
    for v in np.unique(blk):
        cnt = (blk == v).sum(-1)
        m = cnt > best
        out[m] = v
        best[m] = cnt[m]
    return out


def majority3(idx, valid, n):
    """3x3 majority filter (only on valid pixels); keeps a pixel when no neighbour value has >= 5 votes."""
    h, w = idx.shape
    pad = np.pad(idx, 1, mode="edge")
    stack = np.stack([pad[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)], -1)
    out = idx.copy()
    best = np.zeros((h, w), np.int32)
    win = idx.copy()
    for v in range(n):
        cnt = (stack == v).sum(-1)
        m = cnt > best
        win[m] = v
        best[m] = cnt[m]
    m = valid & (best >= 5)
    out[m] = win[m]
    return out


def fill_gutters(idx, valid, steps=24):
    """Grow islands into the invalid (black) gutter: each pass copies a valid neighbour into invalid pixels."""
    idx, valid = idx.copy(), valid.copy()
    for _ in range(steps):
        if valid.all():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sv = np.roll(valid, (dy, dx), (0, 1))
            si = np.roll(idx, (dy, dx), (0, 1))
            m = (~valid) & sv
            idx[m] = si[m]
            valid = valid | m
    return idx


base = load(face_imgs[0])
h0 = base.shape[0]
valid0 = (base[..., :3].sum(-1) > 0.04) & (base[..., 3] > 0.5)
px = base[..., :3][valid0]
px = px[np.random.default_rng(1).choice(len(px), min(60000, len(px)), replace=False)]
pal = kmeans(px, K)
# expression-specific colours (blush, open mouth, closed-eye lines) get their own entries from the diffs
extra = []
for im in face_imgs[1:]:
    a = load(im)[..., :3]
    diff = (np.abs(a - base[..., :3]).sum(-1) > 0.25) & valid0
    if diff.sum() > 50:
        extra.append(kmeans(a[diff][:20000], 3, seed=2))
if extra:
    pal = np.concatenate([pal] + extra, 0)
print("[clean] palette", len(pal))
f = max(1, h0 // RES)


# protect mask: UV area of the face (eyes, brows, mouth keep their dark lines)
def raster_mask(h, w, polys):
    m = np.zeros((h, w), bool)
    uvl = body.data.uv_layers.active.data
    for p in polys:
        uv = np.array([uvl[li].uv[:] for li in p.loop_indices])
        for k in range(1, len(uv) - 1):
            tri = np.array([uv[0], uv[k], uv[k + 1]]) * (w, h)
            x0, y0 = np.floor(tri.min(0)).astype(int)
            x1, y1 = np.ceil(tri.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0 - 1), max(0, y0 - 1), min(w, x1 + 2), min(h, y1 + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            ys, xs = np.mgrid[y0:y1, x0:x1] + 0.5
            a, b, c = tri
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
            l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
            ins = (l1 >= -0.05) & (l2 >= -0.05) & (1 - l1 - l2 >= -0.05)
            m[y0:y1, x0:x1] |= ins
    return m[::-1]  # pixel rows: image row 0 = bottom in Blender buffers; our arrays are bottom-up too -> keep


meta_eye = None
try:
    import json as _j
    meta_eye = _j.load(open(os.path.join(CDIR, "character.json"), encoding="utf-8")).get("eye_z")
except Exception:
    pass
ez = meta_eye or 1.33
mwb = body.matrix_world
face_polys = []
for p in body.data.polygons:
    c = mwb @ p.center
    n = (mwb.to_3x3() @ p.normal).normalized()
    if n.y < -0.3 and ez - 0.2 < c.z < ez + 0.06 and abs(c.x) < 0.14:
        face_polys.append(p)
PROTECT = raster_mask(h0, base.shape[1], face_polys)[::-1]
print("[clean] face protect polys", len(face_polys), "px", int(PROTECT.sum()))
lum = 0.2126 * pal[:, 0] + 0.7152 * pal[:, 1] + 0.0722 * pal[:, 2]
DARK = lum < 0.2


def drop_dark(idx, valid, protect, rad=3):
    """Dark (outline-remnant) pixels outside the face become the most common non-dark neighbour colour."""
    h, w = idx.shape
    L_ = lum[idx] * valid
    kk = 2 * rad + 1
    def box(a):
        pa = np.pad(a, rad + 1, mode="edge").cumsum(0).cumsum(1)
        return pa[kk:kk + h, kk:kk + w] - pa[0:h, kk:kk + w] - pa[kk:kk + h, 0:w] + pa[0:h, 0:w]
    mean = box(L_) / np.maximum(box(valid.astype(np.float64)), 1)
    # outline remnants: clearly darker than their surroundings (hair streaks, torn collar edges) or near-black
    dk = ((L_ < 0.62 * mean) | DARK[idx]) & valid & ~protect
    if not dk.any():
        return idx
    best = np.zeros((h, w), np.int32)
    win = idx.copy()
    pad = np.pad(idx, rad + 1, mode="edge")
    k = 2 * rad + 1
    for v in np.unique(idx[valid]):
        if lum[v] < 0.33:
            continue
        ii = (pad == v).astype(np.int32).cumsum(0).cumsum(1)
        cnt = ii[k:k + h, k:k + w] - ii[0:h, k:k + w] - ii[k:k + h, 0:w] + ii[0:h, 0:w]
        m = cnt > best
        win[m] = v
        best[m] = cnt[m]
    out = idx.copy()
    out[dk & (best > 0)] = win[dk & (best > 0)]
    return out


def minority(idx, valid, protect, rad=3, dom=0.55, own=0.18):
    """Speckle/streak removal: a pixel whose colour is rare in its window (< own) while one colour dominates
    (>= dom) takes that dominant colour. Region borders (no dominant colour) and the face are kept."""
    h, w = idx.shape
    k = 2 * rad + 1
    area = float(k * k)
    best = np.zeros((h, w), np.int32)
    win = idx.copy()
    owncnt = np.zeros((h, w), np.int32)
    pad = np.pad(idx, rad + 1, mode="edge")
    for v in np.unique(idx):
        ii = (pad == v).astype(np.int32).cumsum(0).cumsum(1)
        cnt = ii[k:k + h, k:k + w] - ii[0:h, k:k + w] - ii[k:k + h, 0:w] + ii[0:h, 0:w]
        m = cnt > best
        win[m] = v
        best[m] = cnt[m]
        sel = idx == v
        owncnt[sel] = cnt[sel]
    rep = valid & ~protect & (best >= dom * area) & (owncnt < own * area)
    out = idx.copy()
    out[rep] = win[rep]
    return out


# ---- flat per-face colours for everything except the face (UV islands of the TRELLIS mesh are tiny, so any texture
# sampling bleeds neighbour islands = the streaks / torn edges; one palette colour per polygon is clean low-poly look)
me = body.data
uvl = me.uv_layers.active.data
H_, W_ = base.shape[:2]
face_set = set(p.index for p in face_polys)
npoly = len(me.polygons)
fcol = np.zeros(npoly, np.int32)
for p in me.polygons:
    uv = np.array([uvl[li].uv[:] for li in p.loop_indices])
    c = uv.mean(0)
    pts = [c] + [c + (u - c) * 0.55 for u in uv]
    cols = []
    for q in pts:
        x = min(W_ - 1, max(0, int(q[0] * W_)))
        y = min(H_ - 1, max(0, int(q[1] * H_)))
        if valid0[y, x]:
            cols.append(base[y, x, :3])
    if not cols:
        cols = [base[min(H_ - 1, int(c[1] * H_)), min(W_ - 1, int(c[0] * W_)), :3]]
    cols = np.array(cols)
    lab = ((cols[:, None, :] - pal[None]) ** 2).sum(-1).argmin(1)
    vals, cnts = np.unique(lab, return_counts=True)
    fcol[p.index] = vals[cnts.argmax()]
# flatten: merge near-identical palette tones for the flat regions (hair read as a mosaic of 6 pinks)
order = np.argsort(-np.bincount(fcol, minlength=len(pal)))
rep = np.arange(len(pal))
for i in order:
    if rep[i] != i:
        continue
    for j in order:
        if j != i and rep[j] == j and np.abs(pal[i] - pal[j]).sum() < 0.1 and (np.bincount(fcol, minlength=len(pal))[j] <= np.bincount(fcol, minlength=len(pal))[i]):
            rep[j] = i
fcol = rep[fcol]
print("[clean] flat tones", len(np.unique(fcol)))
# adjacency (edge-sharing faces)
from collections import defaultdict
e2f = defaultdict(list)
for p in me.polygons:
    for ek in p.edge_keys:
        e2f[ek].append(p.index)
nbr = [[] for _ in range(npoly)]
for fs in e2f.values():
    if len(fs) == 2:
        a_, b_ = fs
        nbr[a_].append(b_)
        nbr[b_].append(a_)
for it in range(8):  # mode filter on the mesh: kills off-colour polygons + smooths jagged tone borders
    new = fcol.copy()
    for i in range(npoly):
        nb = nbr[i]
        if len(nb) < 2 or i in face_set:
            continue
        vals, cnts = np.unique(fcol[nb], return_counts=True)
        j = cnts.argmax()
        own_n = int((fcol[nb] == fcol[i]).sum())
        if vals[j] != fcol[i] and cnts[j] >= 2 and cnts[j] > own_n:
            new[i] = vals[j]
    changed = int((new != fcol).sum())
    fcol = new
    print("[clean] face-colour smoothing pass", it, "changed", changed)
attr = me.color_attributes.new("flat_col", "FLOAT_COLOR", "FACE")
ut = me.attributes.new("use_tex", "FLOAT", "FACE")
lin = np.where(pal <= 0.04045, pal / 12.92, ((pal + 0.055) / 1.055) ** 2.4)  # palette is sRGB -> linear attr
cols = np.ones((npoly, 4), np.float32)
cols[:, :3] = lin[fcol]
attr.data.foreach_set("color", cols.ravel())
ut.data.foreach_set("value", np.array([1.0 if i in face_set else 0.0 for i in range(npoly)], np.float32))
print("[clean] flat colours on", npoly - len(face_set), "polys; textured face polys", len(face_set))
# smooth normals: flat-shaded 40k noisy TRELLIS facets made the toon ramp sparkle like a mosaic
me.polygons.foreach_set("use_smooth", np.ones(npoly, bool))

for im in face_imgs:
    a = load(im)
    rgb = a[..., :3]
    valid = (rgb.sum(-1) > 0.04) & (a[..., 3] > 0.5)
    # nearest palette entry, chunked
    flat = rgb.reshape(-1, 3)
    lab = np.empty(len(flat), np.int32)
    for s in range(0, len(flat), 262144):
        d = ((flat[s:s + 262144, None, :] - pal[None]) ** 2).sum(-1)
        lab[s:s + 262144] = d.argmin(1)
    idx = lab.reshape(rgb.shape[:2])
    idx = majority3(idx, valid, len(pal))
    idx = fill_gutters(idx, valid, 40)
    if f > 1:
        idx = mode_down(idx, f)
        valid = valid.reshape(valid.shape[0] // f, f, valid.shape[1] // f, f).any(axis=(1, 3))
    idx = majority3(idx, np.ones_like(valid), len(pal))
    out = np.ones((*idx.shape, 4), np.float32)
    out[..., :3] = pal[idx]
    im.scale(idx.shape[1], idx.shape[0])
    im.pixels.foreach_set(out.ravel())
    im.update()
    im.pack()
    print("[clean] cleaned", im.name, idx.shape)

# ------------------------------------------------------------------ 2. hands
vg = {g.index: g.name for g in body.vertex_groups}
hand_v = set()
for v in body.data.vertices:
    w = sum(g.weight for g in v.groups if any(k in vg.get(g.group, "") for k in ("_Hand", "Thumb", "Index", "Middle", "Ring", "Little")))
    if w > 0.45:
        hand_v.add(v.index)
arm_v = set()
for v in body.data.vertices:
    if sum(g.weight for g in v.groups if "LowerArm" in vg.get(g.group, "")) > 0.6:
        arm_v.add(v.index)
neutral = load(face_imgs[0])[..., :3]
hh_, ww_ = neutral.shape[:2]
uvl = body.data.uv_layers.active.data
samp = []
for p in body.data.polygons:
    for li, vi in zip(p.loop_indices, p.vertices):
        if vi in arm_v:
            u, v_ = uvl[li].uv
            samp.append(neutral[min(hh_ - 1, int(v_ * hh_)), min(ww_ - 1, int(u * ww_))])
samp = np.array(samp) if samp else np.array([[0.98, 0.86, 0.78]])
lm = samp.mean(1)
keep = (lm >= np.percentile(lm, 30)) & (lm <= np.percentile(lm, 90))
samp = samp[keep] if keep.any() else samp
skin = np.median(samp, 0).astype(np.float32)
print("[clean] arm verts", len(arm_v), "samples", len(samp))
if not np.isfinite(skin).all():
    skin = np.array([0.98, 0.86, 0.78], np.float32)
print("[clean] hand verts", len(hand_v), "skin", skin)

# ------------------------------------------------------------------ 3. shading (soft toon emission, no specular)
pr = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
col_link = next((l for l in nt.links if l.to_node == pr and l.to_socket.name == "Base Color"), None)
col_out = col_link.from_socket
out_node = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
N, L = nt.nodes, nt.links
N.remove(pr)
dif = N.new("ShaderNodeBsdfDiffuse")
s2r = N.new("ShaderNodeShaderToRGB")
L.new(dif.outputs[0], s2r.inputs[0])
ramp = N.new("ShaderNodeValToRGB")
ramp.color_ramp.interpolation = "EASE"
sh = C.srgb_to_lin([0.74 * 0.97, 0.74 * 0.9, 0.74 * 1.0])  # warm-pink shadow (anime skin), lighter than props
ramp.color_ramp.elements[0].position = X.AMBIENT + 0.02
ramp.color_ramp.elements[0].color = (float(sh[0]), float(sh[1]), float(sh[2]), 1)
ramp.color_ramp.elements[1].position = X.AMBIENT + 0.45
L.new(s2r.outputs[0], ramp.inputs[0])
fa = N.new("ShaderNodeAttribute")
fa.attribute_name = "flat_col"
ua = N.new("ShaderNodeAttribute")
ua.attribute_name = "use_tex"
sel = N.new("ShaderNodeMix")
sel.data_type = "RGBA"
L.new(ua.outputs["Fac"], sel.inputs[0])
L.new(fa.outputs["Color"], sel.inputs[6])
L.new(col_out, sel.inputs[7])
mul = N.new("ShaderNodeMix")
mul.data_type = "RGBA"
mul.blend_type = "MULTIPLY"
mul.inputs[0].default_value = 1
L.new(sel.outputs[2], mul.inputs[6])
L.new(ramp.outputs[0], mul.inputs[7])
em = N.new("ShaderNodeEmission")
L.new(mul.outputs[2], em.inputs[0])
L.new(em.outputs[0], out_node.inputs[0])
for n in N:
    if n.bl_idname == "ShaderNodeTexImage":
        n.interpolation = "Closest"

# hand material: same toon, flat skin
hm = bpy.data.materials.new("char_hands")
hm.use_nodes = True
hn = hm.node_tree
for n in list(hn.nodes):
    hn.nodes.remove(n)
o2 = hn.nodes.new("ShaderNodeOutputMaterial")
d2 = hn.nodes.new("ShaderNodeBsdfDiffuse")
s2 = hn.nodes.new("ShaderNodeShaderToRGB")
r2 = hn.nodes.new("ShaderNodeValToRGB")
r2.color_ramp.interpolation = "EASE"
r2.color_ramp.elements[0].position = X.AMBIENT + 0.02
r2.color_ramp.elements[0].color = (float(sh[0]), float(sh[1]), float(sh[2]), 1)
r2.color_ramp.elements[1].position = X.AMBIENT + 0.45
m2 = hn.nodes.new("ShaderNodeMix")
m2.data_type = "RGBA"
m2.blend_type = "MULTIPLY"
m2.inputs[0].default_value = 1
sl = C.srgb_to_lin(skin)
m2.inputs[6].default_value = (float(sl[0]), float(sl[1]), float(sl[2]), 1)
e2 = hn.nodes.new("ShaderNodeEmission")
hn.links.new(d2.outputs[0], s2.inputs[0])
hn.links.new(s2.outputs[0], r2.inputs[0])
hn.links.new(r2.outputs[0], m2.inputs[7])
hn.links.new(m2.outputs[2], e2.inputs[0])
hn.links.new(e2.outputs[0], o2.inputs[0])
body.data.materials.append(hm)
hidx = len(body.data.materials) - 1
oidx = next(i for i, m in enumerate(body.data.materials) if m and m.name == "outline")
cidx = next(i for i, m in enumerate(body.data.materials) if m and m.name == "char_final")
for p in body.data.polygons:
    if p.material_index == cidx and sum(1 for v in p.vertices if v in hand_v) >= 2:
        p.material_index = hidx
# outline: solidify uses material_offset to the outline slot - keep it pointing at 'outline'
for md in body.modifiers:
    if md.type == "SOLIDIFY":
        md.material_offset = oidx - cidx if md.material_offset else md.material_offset
        md.thickness *= 0.6
om = bpy.data.materials["outline"]
for n in om.node_tree.nodes:
    if n.bl_idname == "ShaderNodeEmission":
        c = C.srgb_to_lin([0.28, 0.13, 0.18])
        n.inputs[0].default_value = (float(c[0]), float(c[1]), float(c[2]), 1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(CDIR, "character.blend"), compress=True)
print("[clean] SAVED", os.path.join(CDIR, "character.blend"))
