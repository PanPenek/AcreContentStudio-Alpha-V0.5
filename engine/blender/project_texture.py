"""Project front/back reference art onto a generated character mesh and bake it into its UV texture.
Pixel-art look: the source images are pixelized first (box downscale to --px rows + small palette),
and sampled with Closest, so the model carries real pixel texels that line up with the art.

blender --background --python project_texture.py -- <mesh.glb> <front.png> <back.png> <out.blend>
        [--px 200] [--colors 24] [--tex 2048] [--decimate 1.0] [--faces dir_with_expression_pngs]
Outputs <out.blend> (+ <out>_tex.png, and <out>_face_<name>.png per expression when --faces is given).
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[sys.argv.index("--") + 1:]
MESH, FRONT, BACK, OUT = argv[:4]
opt = dict(zip(argv[4::2], argv[5::2]))
PX = int(opt.get("--px", 280))
COLORS = int(opt.get("--colors", 24))
TEX = int(opt.get("--tex", 2048))
DECIMATE = float(opt.get("--decimate", 1.0))
FACES = opt.get("--faces")
STRIP = opt.get("--strip-outline", "1") == "1"
INSET = float(opt.get("--inset", 0.04))
HEAD_COLORS = int(opt.get("--head-colors", 12))  # fraction of model height
OUTLINE = float(opt.get("--outline", 0.0035))  # inverted-hull thickness, fraction of model height
OUTBASE = os.path.splitext(OUT)[0]


# ------------------------------------------------------------------ image helpers (numpy)
def load_rgba(path):
    im = bpy.data.images.load(path)
    w, h = im.size
    a = np.array(im.pixels[:], np.float32).reshape(h, w, 4)  # bottom-up rows
    bpy.data.images.remove(im)
    return a


def char_mask(a):
    """Foreground = everything NOT reachable from the image border through background-coloured pixels.
    (A plain threshold punches holes in white socks/shirt on a light-grey studio background; the
    art's dark outlines seal those regions off from the border flood fill.)"""
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])[:, :3]
    bg = np.median(border, 0)
    bglike = np.abs(a[..., :3] - bg).max(-1) < 0.06
    reach = np.zeros_like(bglike)
    reach[0], reach[-1], reach[:, 0], reach[:, -1] = bglike[0], bglike[-1], bglike[:, 0], bglike[:, -1]
    while True:
        g = reach.copy()
        g[1:] |= reach[:-1]
        g[:-1] |= reach[1:]
        g[:, 1:] |= reach[:, :-1]
        g[:, :-1] |= reach[:, 1:]
        g &= bglike
        if (g == reach).all():
            break
        reach = g
    return ~reach


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return xs.min(), xs.max() + 1, ys.min(), ys.max() + 1


def kmeans(px, k, iters=12):
    rng = np.random.default_rng(0)
    s = px[rng.choice(len(px), min(len(px), 30000), replace=False)]
    order = np.argsort(s @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    c = s[order[np.linspace(0, len(s) - 1, k).astype(int)]].copy()
    for _ in range(iters):
        lab = ((s[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (lab == j).any():
                c[j] = s[lab == j].mean(0)
    lab = ((px[:, None] - c[None]) ** 2).sum(-1).argmin(1)
    return c, lab


def strip_outline(a, mask, band=14, dark=0.28):
    """Remove the art's dark silhouette outline (it smears across side-facing polygons when projected):
    dark pixels within `band` px of the background are re-filled from the nearest non-outline colours.
    Interior linework (eyes, pleats) is untouched. The 3D inverted-hull outline replaces it."""
    er = mask.copy()
    for _ in range(band):
        e = er.copy()
        e[1:] &= er[:-1]
        e[:-1] &= er[1:]
        e[:, 1:] &= er[:, :-1]
        e[:, :-1] &= er[:, 1:]
        er = e
    lum = a[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bad = mask & ~er & (lum < dark)
    ok = mask & ~bad
    rgb = a[..., :3].copy()
    for _ in range(band * 2):
        if not (bad & ~ok).any():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(ok.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            acc += np.roll(np.roll(rgb * ok[..., None], dy, 0), dx, 1)
            cnt += np.roll(np.roll(ok, dy, 0), dx, 1)
        new = bad & ~ok & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        ok |= new
    out = a.copy()
    out[..., :3] = rgb
    return out


def pixelize_crop(a, mask, rows, colors, palette=None):
    """Crop to the character bbox, box-downscale to `rows` rows (square texels), quantise.
    Returns (pixel image rgba bottom-up, bbox in source px, palette)."""
    if STRIP:
        a = strip_outline(a, mask)
    x0, x1, y0, y1 = bbox(mask)
    crop, m = a[y0:y1, x0:x1, :3], mask[y0:y1, x0:x1].astype(np.float32)
    h, w = crop.shape[:2]
    nh = rows
    nw = max(1, int(round(w * nh / h)))
    ys = np.linspace(0, h, nh + 1).astype(int)
    xs = np.linspace(0, w, nw + 1).astype(int)
    out = np.zeros((nh, nw, 4), np.float32)
    for i in range(nh):
        for j in range(nw):
            mm = m[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if mm.sum() == 0:
                continue
            cc = crop[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            out[i, j, :3] = (cc * mm[..., None]).sum((0, 1)) / mm.sum()
            out[i, j, 3] = mm.mean()
    vis = out[..., 3] > 0.35
    rgb = out[..., :3][vis]
    if palette is None:
        # body palette + a dedicated head palette (top 22%): small but vital colours (violet irises,
        # blush) never win a body-wide k-means
        palette, _ = kmeans(rgb, colors)
        head = out[int(nh * 0.78):, :, :3][vis[int(nh * 0.78):]]  # bottom-up rows: top of head = high index
        if HEAD_COLORS > 0 and len(head) > 64:
            hp, _ = kmeans(head, HEAD_COLORS)
            palette = np.concatenate([palette, hp])
        lab = ((rgb[:, None] - palette[None]) ** 2).sum(-1).argmin(1)
    else:
        lab = ((rgb[:, None] - palette[None]) ** 2).sum(-1).argmin(1)
    out[..., :3][vis] = palette[lab]
    # dilate colours into empty texels so silhouette-edge samples never hit background
    filled = vis.copy()
    for _ in range(40):  # fill everything near the silhouette so edge samples never hit background
        nb = np.zeros_like(out[..., :3])
        cnt = np.zeros(vis.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(out[..., :3] * filled[..., None], dy, 0), dx, 1)
            sf = np.roll(np.roll(filled, dy, 0), dx, 1)
            nb += sh
            cnt += sf
        new = (~filled) & (cnt > 0)
        out[..., :3][new] = nb[new] / cnt[new][:, None]
        filled |= new
    out[..., 3] = 1.0
    return out, (x0, x1, y0, y1), palette


def to_image(name, a):
    h, w = a.shape[:2]
    im = bpy.data.images.new(name, w, h, alpha=True)
    im.colorspace_settings.name = "sRGB"  # must precede the pixel write: changing it regenerates the buffer
    im.pixels.foreach_set(np.ascontiguousarray(a, np.float32).ravel())
    im.update()  # without this, pack()/save() write the blank generated buffer
    return im


# ------------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=MESH)
obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if DECIMATE < 1.0:
    mod = obj.modifiers.new("dec", "DECIMATE")
    mod.ratio = DECIMATE
    bpy.ops.object.modifier_apply(modifier=mod.name)
for p in obj.data.polygons:
    p.use_smooth = False  # faceted low-poly shading
vs = np.array([v.co[:] for v in obj.data.vertices])
lo, hi = vs.min(0), vs.max(0)
print("MESH bbox", lo.round(3), hi.round(3), "faces", len(obj.data.polygons))

fa, ba = load_rgba(FRONT), load_rgba(BACK)
fm, bm_ = char_mask(fa), char_mask(ba)
fpix, fbb, pal = pixelize_crop(fa, fm, PX, COLORS)
bpix, bbb, _ = pixelize_crop(ba, bm_, PX, COLORS, palette=pal)  # shared palette = consistent colours
print("front bbox px", fbb, "pixel grid", fpix.shape[:2], "| back bbox", bbb, bpix.shape[:2])
fimg, bimg = to_image("front_px", fpix), to_image("back_px", bpix)
for _im in (fimg, bimg):  # keep the pixelized sources for inspection
    _im.filepath_raw = f"{OUTBASE}_{_im.name}.png"
    _im.file_format = "PNG"
    _im.save()
print("PXSTATS", float(fpix[..., :3].mean()), float(bpix[..., :3].mean()))
fimg.pack()
bimg.pack()
np.save(OUTBASE + "_palette.npy", pal)
SIDES = {}  # optional side art: right = camera at +X (image right = +Y), left = camera at -X (image right = -Y)
for key, path in (("right", opt.get("--right")), ("left", opt.get("--left"))):
    if path and os.path.exists(path):
        sa = load_rgba(path)
        spx, sbb, _ = pixelize_crop(sa, char_mask(sa), PX, COLORS, palette=pal)
        SIDES[key] = to_image(f"{key}_px", spx)
        SIDES[key].pack()
        print("side", key, "bbox", sbb)
if SIDES:
    INSET = 0.0  # real side art: no need to smear interior colours outward


def proj_material():
    """Front: u=(x-lo.x)/W, v=(z-lo.z)/H. Back: u mirrored. Blend on normal.y (front faces -Y)."""
    m = bpy.data.materials.new("char_proj")
    m.use_nodes = True
    nt = m.node_tree
    N = nt.nodes
    L = nt.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    # sample point pushed inward along the normal: side-facing polygons read stable interior colours
    # instead of the (row-to-row noisy) silhouette edge of the art
    # weight (1-|n.y|)^2: front/back-facing areas (face!) are sampled exactly, only side faces shift
    nsep0 = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], nsep0.inputs[0])
    ab = N.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"
    L.new(nsep0.outputs["Y"], ab.inputs[0])
    om = N.new("ShaderNodeMath"); om.operation = "SUBTRACT"; om.inputs[0].default_value = 1.0
    L.new(ab.outputs[0], om.inputs[1])
    sq = N.new("ShaderNodeMath"); sq.operation = "MULTIPLY"
    L.new(om.outputs[0], sq.inputs[0]); L.new(om.outputs[0], sq.inputs[1])
    kk = N.new("ShaderNodeMath"); kk.operation = "MULTIPLY"; kk.inputs[1].default_value = -INSET * float(hi[2] - lo[2])
    L.new(sq.outputs[0], kk.inputs[0])
    inset = N.new("ShaderNodeVectorMath")
    inset.operation = "MULTIPLY_ADD"
    L.new(geo.outputs["Normal"], inset.inputs[0])
    L.new(kk.outputs[0], inset.inputs[1])
    L.new(geo.outputs["Position"], inset.inputs[2])
    L.new(inset.outputs[0], sep.inputs[0])

    def lin(sock, a, b):  # (sock - a) / (b - a)
        n = N.new("ShaderNodeMapRange")
        n.inputs["From Min"].default_value = a
        n.inputs["From Max"].default_value = b
        n.clamp = True
        L.new(sock, n.inputs["Value"])
        return n.outputs["Result"]

    v = lin(sep.outputs["Z"], lo[2], hi[2])
    uf = lin(sep.outputs["X"], lo[0], hi[0])
    ub = lin(sep.outputs["X"], hi[0], lo[0])

    def tex(img, u):
        c = N.new("ShaderNodeCombineXYZ")
        L.new(u, c.inputs["X"])
        L.new(v, c.inputs["Y"])
        t = N.new("ShaderNodeTexImage")
        t.image = img
        t.interpolation = "Closest"
        t.extension = "EXTEND"
        L.new(c.outputs[0], t.inputs["Vector"])
        return t.outputs["Color"]

    cf, cb = tex(fimg, uf), tex(bimg, ub)
    nsep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], nsep.inputs[0])
    em = N.new("ShaderNodeEmission")
    if not SIDES:
        w = N.new("ShaderNodeMapRange")  # normal.y: -0.15 -> front(0), +0.15 -> back(1)
        w.inputs["From Min"].default_value = -0.15
        w.inputs["From Max"].default_value = 0.15
        w.clamp = True
        L.new(nsep.outputs["Y"], w.inputs["Value"])
        mix = N.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        L.new(w.outputs["Result"], mix.inputs["Factor"])
        L.new(cf, mix.inputs[6])
        L.new(cb, mix.inputs[7])
        L.new(mix.outputs[2], em.inputs["Color"])
    else:
        # 4-way blend, weights = max(0, +-normal component)^4 (sharp seams at ~45 deg), normalised
        def weight(comp, sign):
            m1 = N.new("ShaderNodeMath"); m1.operation = "MULTIPLY"; m1.inputs[1].default_value = sign
            L.new(nsep.outputs[comp], m1.inputs[0])
            m2 = N.new("ShaderNodeMath"); m2.operation = "MAXIMUM"; m2.inputs[1].default_value = 0.0
            L.new(m1.outputs[0], m2.inputs[0])
            m3 = N.new("ShaderNodeMath"); m3.operation = "POWER"; m3.inputs[1].default_value = 4.0
            L.new(m2.outputs[0], m3.inputs[0])
            return m3.outputs[0]
        ur = lin(sep.outputs["Y"], lo[1], hi[1])
        ul = lin(sep.outputs["Y"], hi[1], lo[1])
        fw = N.new("ShaderNodeMath"); fw.operation = "ADD"; fw.inputs[1].default_value = 0.02  # tops/bottoms fall back to front art
        L.new(weight("Y", -1.0), fw.inputs[0])
        views = [(cf, fw.outputs[0]), (cb, weight("Y", 1.0))]
        if "right" in SIDES:
            views.append((tex(SIDES["right"], ur), weight("X", 1.0)))
        if "left" in SIDES:
            views.append((tex(SIDES["left"], ul), weight("X", -1.0)))
        acc, wsum = None, None
        for col, wt in views:
            sc_ = N.new("ShaderNodeVectorMath"); sc_.operation = "SCALE"
            L.new(col, sc_.inputs[0]); L.new(wt, sc_.inputs["Scale"])
            if acc is None:
                acc, wsum = sc_.outputs[0], wt
                continue
            a_ = N.new("ShaderNodeVectorMath"); a_.operation = "ADD"
            L.new(acc, a_.inputs[0]); L.new(sc_.outputs[0], a_.inputs[1]); acc = a_.outputs[0]
            s_ = N.new("ShaderNodeMath"); s_.operation = "ADD"
            L.new(wsum, s_.inputs[0]); L.new(wt, s_.inputs[1]); wsum = s_.outputs[0]
        eps = N.new("ShaderNodeMath"); eps.operation = "ADD"; eps.inputs[1].default_value = 1e-4
        L.new(wsum, eps.inputs[0])
        inv = N.new("ShaderNodeMath"); inv.operation = "DIVIDE"; inv.inputs[0].default_value = 1.0
        L.new(eps.outputs[0], inv.inputs[1])
        fin = N.new("ShaderNodeVectorMath"); fin.operation = "SCALE"
        L.new(acc, fin.inputs[0]); L.new(inv.outputs[0], fin.inputs["Scale"])
        L.new(fin.outputs[0], em.inputs["Color"])
    L.new(em.outputs[0], out.inputs["Surface"])
    target = N.new("ShaderNodeTexImage")
    nt.nodes.active = target
    return m, nt, target


mat, nt, target = proj_material()
obj.data.materials.clear()
obj.data.materials.append(mat)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 1
sc.cycles.device = "CPU"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.device = "GPU"
except Exception as e:
    print("GPU bake unavailable:", e)
sc.render.bake.margin = 8
sc.view_settings.view_transform = "Standard"


def bake_to(name, path):
    img = bpy.data.images.new(name, TEX, TEX, alpha=False)
    img.colorspace_settings.name = "sRGB"
    target.image = img
    nt.nodes.active = target
    bpy.ops.object.bake(type="EMIT")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return img


tex_img = bake_to("char_tex", OUTBASE + "_tex.png")
print("BAKED", OUTBASE + "_tex.png")

# expression variants: re-bake using each face image as the FRONT (same framing as the T-pose sheet)
if FACES:
    for fn in sorted(os.listdir(FACES)):
        if not fn.endswith(".png"):
            continue
        a = load_rgba(os.path.join(FACES, fn))
        px, bb, _ = pixelize_crop(a, char_mask(a), PX, COLORS, palette=pal)
        fimg.scale(px.shape[1], px.shape[0])
        fimg.pixels.foreach_set(np.ascontiguousarray(px, np.float32).ravel())
        fimg.update()
        fimg.pack()
        bake_to("face_" + fn[:-4], f"{OUTBASE}_face_{fn[:-4]}.png")
        print("BAKED face", fn, "bbox", bb)

# final display material: plain image texture (Closest) on UVs, emission + toon-ish diffuse handled downstream
final = bpy.data.materials.new("char_final")
final.use_nodes = True
fn_ = final.node_tree.nodes
bsdf = fn_.get("Principled BSDF")
t = fn_.new("ShaderNodeTexImage")
t.image = bpy.data.images.load(OUTBASE + "_tex.png")
t.interpolation = "Closest"
final.node_tree.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 1.0
obj.data.materials.clear()
obj.data.materials.append(final)
if OUTLINE > 0:  # inverted hull: back-face-culled black shell (replaces the stripped 2D outline)
    ol = bpy.data.materials.new("outline")
    ol.use_nodes = True
    ol.use_backface_culling = True
    olb = ol.node_tree.nodes.get("Principled BSDF")
    ol.node_tree.nodes.remove(olb)
    e = ol.node_tree.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (0.02, 0.015, 0.02, 1)
    ol.node_tree.links.new(e.outputs[0], ol.node_tree.nodes["Material Output"].inputs["Surface"])
    obj.data.materials.append(ol)
    sol = obj.modifiers.new("outline", "SOLIDIFY")
    sol.thickness = OUTLINE * float(hi[2] - lo[2])
    sol.offset = 1.0
    sol.use_flip_normals = True
    sol.use_rim = False
    sol.material_offset = 1
obj.name = "character"
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED", OUT)
