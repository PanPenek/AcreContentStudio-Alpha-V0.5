"""Vegetation / rock / terrain helpers for abs_world (pixel-art low-poly look, built on abs_pix).

    import abs_flora as F
    t = F.terrain("Ground", F.axis(120, 14, 0.5, 6), F.axis(120, 14, 0.5, 6), hfn, [X.mat("grass"), X.mat("sand")], mfn)
    oak = F.tree_round(seed=1)                 # -> bpy Mesh (prototype, not linked to the scene)
    F.place(oak, (3, 12, 0), yaw=40, s=1.1)    # linked duplicate object
    F.scatter([oak, pine], (-30, 30, 20, 40), 60, seed=2, avoid=[(-5, 6, -2, 8)], zfn=hfn)

Everything is built from raw numpy geometry (no bpy.ops) so a set with hundreds of trees builds in seconds.
Foliage = solid icosphere cores (box-projected leaf texture) + outward-facing alpha leaf-clump cards; crown normals
are bent outward from the crown centre so a crown shades like one soft volume with a leafy silhouette.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import abs_pix as X

TAU = math.pi * 2


def _rng(seed):
    return np.random.default_rng(seed)


# ------------------------------------------------------------------ extra textures (registered into X.GEN)
def _paint_blob(a, x, y, rx, ry, col):
    h, w = a.shape[:2]
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if (dx / (rx + 0.5)) ** 2 + (dy / (ry + 0.5)) ** 2 <= 1.0:
                X_, Y_ = x + dx, y + dy
                if 0 <= X_ < w and 0 <= Y_ < h:
                    a[Y_, X_, :3] = col
                    a[Y_, X_, 3] = 1


def _leafclump(base, size=48, seed=0, n_discs=8, hi=0.0):
    """Non-tiling leaf clump on transparent ground: dark interior, light leaves on top, ragged leafy edge."""
    r = _rng(seed)
    pal = X.shades(base, 5, 0.42, warm=0.05)
    a = np.zeros((size, size, 4), np.float32)
    ys, xs = np.mgrid[0:size, 0:size]
    m = np.zeros((size, size), bool)
    c = size / 2
    for _ in range(n_discs):
        ang, d = r.uniform(0, TAU), r.uniform(0, size * 0.2)
        px, py = c + math.cos(ang) * d, c + math.sin(ang) * d * 0.8
        rad = r.uniform(size * 0.13, size * 0.22)
        m |= (xs - px) ** 2 + (ys - py) ** 2 < rad ** 2
    nz = X._vnoise(size, size, 6, seed + 5)
    a[m, :3] = np.array(pal[0])[None]
    a[m, 3] = 1
    pts = np.argwhere(m)
    for _ in range(int(len(pts) * 0.55)):
        y, x = pts[r.integers(len(pts))]
        # light comes from the top: rows near the top + noise -> lighter leaves
        lt = (1 - y / size) * 0.75 + nz[y, x] * 0.45 + r.uniform(-0.15, 0.15) + hi
        tone = int(np.clip(lt * 4.2, 0, 4))
        col = np.array(pal[tone])
        _paint_blob(a, int(x), int(y), int(r.integers(1, 3)), 1, col)
        if tone >= 2 and y + 2 < size and m[min(size - 1, y + 2), x]:
            a[y + 2, x, :3] = pal[max(0, tone - 2)]  # leaf underside shadow pixel
    # a few see-through holes
    for _ in range(int(len(pts) * 0.015)):
        y, x = pts[r.integers(len(pts))]
        a[y, x, 3] = 0
    return a


def _frond(base="#5aa33a", w=64, h=20, seed=0):
    """Palm frond: rib along u (x), leaflets angled toward the tip on both sides, alpha."""
    r = _rng(seed)
    pal = X.shades(base, 4, 0.35)
    a = np.zeros((h, w, 4), np.float32)
    mid = h // 2
    for x0 in range(2, w - 2, 2):
        t = x0 / w
        L = int((h // 2 - 1) * min(1.0, 3.2 * t) * (1.0 - 0.75 * t ** 2) + r.integers(-1, 2))
        for side in (-1, 1):
            tone = 2 if side < 0 else 1
            for k in range(1, max(1, L)):
                X_ = x0 + k // 2
                Y_ = mid + side * k
                if 0 <= X_ < w and 0 <= Y_ < h:
                    a[Y_, X_, :3] = pal[tone + (1 if k < 3 and side < 0 else 0)]
                    a[Y_, X_, 3] = 1
    a[mid, :, :3] = pal[3] * np.array([1.05, 1.02, 0.8])
    a[mid, :, 3] = 1
    a[mid, w - 3:, 3] = 0
    return np.clip(a, 0, 1)


def _blades(cols, w=24, h=48, seed=0, density=0.7, heads=None, lean=0.3, minh=0.45):
    """Vertical grass / reed blades on alpha (row 0 = top). heads=[(colour, prob)] cattails / flowers."""
    r = _rng(seed)
    a = np.zeros((h, w, 4), np.float32)
    pals = [np.array(X._c(c)) for c in cols]
    for _ in range(int(w * density * 1.6)):
        x = r.uniform(0, w)
        bh = int(h * r.uniform(minh, 1.0))
        dx = r.uniform(-lean, lean)
        col = pals[r.integers(len(pals))]
        for k in range(bh):
            y = h - 1 - k
            xx = int(x + dx * k * (k / h))
            if 0 <= xx < w:
                f = 0.78 + 0.32 * (k / bh)
                a[y, xx, :3] = np.clip(col * f, 0, 1)
                a[y, xx, 3] = 1
        if heads:
            for hc, p in heads:
                if r.random() < p:
                    xx = int(np.clip(x + dx * bh * (bh / h), 0, w - 2))
                    y0 = h - bh
                    a[max(0, y0):y0 + 4, xx:xx + 2, :3] = X._c(hc)
                    a[max(0, y0):y0 + 4, xx:xx + 2, 3] = 1
                    break
    return a


def _papyrus(w=32, h=64, seed=0):
    r = _rng(seed)
    a = np.zeros((h, w, 4), np.float32)
    stem = np.array(X._c("#6f9a3a"))
    head = X.shades("#7fb340", 4, 0.3)
    for _ in range(6):
        x = r.integers(4, w - 4)
        top = r.integers(10, 26)
        for y in range(top, h):
            a[y, x, :3] = stem * (0.8 + 0.3 * (1 - y / h))
            a[y, x, 3] = 1
        for k in range(14):  # umbrella spray
            ang = math.radians(r.uniform(200, 340))
            L = r.uniform(4, 9)
            for s in np.linspace(0, L, int(L * 2)):
                X_, Y_ = int(x + math.cos(ang) * s), int(top + math.sin(ang) * s * 0.7)
                if 0 <= X_ < w and 0 <= Y_ < h:
                    a[Y_, X_, :3] = head[min(3, 1 + int(s / L * 3))]
                    a[Y_, X_, 3] = 1
    return a


def _seaweed(w=16, h=48, seed=0):
    r = _rng(seed)
    a = np.zeros((h, w, 4), np.float32)
    pal = X.shades("#3f8a3c", 4, 0.3)
    for _ in range(4):
        x0 = r.uniform(2, w - 2)
        ph = r.uniform(0, TAU)
        hh = int(h * r.uniform(0.55, 1.0))
        for k in range(hh):
            y = h - 1 - k
            x = int(x0 + 1.6 * math.sin(k * 0.35 + ph))
            for dx in (0, 1):
                if 0 <= x + dx < w:
                    a[y, x + dx, :3] = pal[1 + dx + (k % 7 == 0)]
                    a[y, x + dx, 3] = 1
    return a


def _birch(size=16, seed=0):
    r = _rng(seed)
    a = np.zeros((size, size, 3), np.float32)
    a[:] = X._c("#ece8dc")
    a[:, ::5] = X._c("#d8d2c4")
    for _ in range(9):
        x, y = r.integers(0, size, 2)
        l = r.integers(2, 5)
        for k in range(l):
            a[y, (x + k) % size] = X._c("#3b3530")
    return a


def _flowers(cols, w=16, h=12, seed=0):
    a = _blades(["#5fa83a", "#4c8f30"], w, h, seed, 0.8, lean=0.2, minh=0.5)
    r = _rng(seed + 9)
    for _ in range(5):
        x, y = r.integers(1, w - 2), r.integers(0, h // 2)
        col = X._c(cols[r.integers(len(cols))])
        a[y:y + 2, x:x + 2, :3] = col
        a[y:y + 2, x:x + 2, 3] = 1
        a[y, x + 1, :3] = (1, 0.95, 0.6)
    return a


def _cobble(base="#a8a294", size=32, seed=0):
    """Irregular paving stones."""
    r = _rng(seed)
    pal = X.shades(base, 4, 0.18)
    pts = r.uniform(0, size, (14, 2))
    ys, xs = np.mgrid[0:size, 0:size]
    d = np.full((size, size), 1e9)
    d2 = np.full((size, size), 1e9)
    idx = np.zeros((size, size), int)
    for i, (px, py) in enumerate(pts):
        for ox in (-size, 0, size):
            for oy in (-size, 0, size):
                dd = (xs - px - ox) ** 2 + (ys - py - oy) ** 2
                closer = dd < d
                d2 = np.where(closer, d, np.minimum(d2, dd))
                idx = np.where(closer, i, idx)
                d = np.where(closer, dd, d)
    tone = 1 + (idx % 3 == 0) + (idx % 5 == 0) * 0
    a = np.array(pal, np.float32)[np.clip(tone, 0, 3)]
    edge = np.sqrt(d2) - np.sqrt(d) < 1.4
    a[edge] = np.array(X._c("#6e6a60"))
    return a


def _ripple_water(base="#3aa0c8", size=32, seed=0):
    a = X._water(size, seed, base)
    return a


def _register():
    G = X.GEN
    G.setdefault("leafclump", lambda: _leafclump("#4f9a35", seed=101))
    G.setdefault("leafclump_light", lambda: _leafclump("#78bd3e", seed=102))
    G.setdefault("leafclump_dark", lambda: _leafclump("#2f7030", seed=103, hi=-0.05))
    G.setdefault("leafclump_yellow", lambda: _leafclump("#a5b83a", seed=104))
    G.setdefault("leafclump_olive", lambda: _leafclump("#6f8f3a", seed=105))
    G.setdefault("leaves_core", lambda: X._leaves("#3b7f2e", seed=106, alpha=False))
    G.setdefault("leaves_core_light", lambda: X._leaves("#5c9f35", seed=107, alpha=False))
    G.setdefault("pine_solid", lambda: X._leaves("#2c6637", seed=108, alpha=False))
    G.setdefault("cypress_solid", lambda: X._leaves("#35703a", seed=109, alpha=False))
    G.setdefault("frond", lambda: _frond())
    G.setdefault("frond_dry", lambda: _frond("#8fa040", seed=3))
    G.setdefault("reed_blades", lambda: _blades(["#6f9e3a", "#8dbb4c", "#5b8a30"], 24, 48, 110, 0.8,
                                               heads=[("#6b4528", 0.25)]))
    G.setdefault("grass_blades", lambda: _blades(["#5fae3a", "#78c244", "#4d9530"], 16, 12, 111, 0.9, lean=0.25))
    G.setdefault("dry_blades", lambda: _blades(["#b9b060", "#a39a4c", "#cfc47a"], 16, 12, 112, 0.7, lean=0.3))
    G.setdefault("papyrus", lambda: _papyrus())
    G.setdefault("seaweed", lambda: _seaweed())
    G.setdefault("bark_birch", lambda: _birch())
    G.setdefault("flowers_warm", lambda: _flowers(["#f2d44a", "#ee7b4a", "#ffffff"], seed=113))
    G.setdefault("flowers_cool", lambda: _flowers(["#e86fa8", "#b07ee8", "#ffffff"], seed=114))
    G.setdefault("cobble", lambda: _cobble())
    G.setdefault("cobble_warm", lambda: _cobble("#c9b08a", seed=5))
    G.setdefault("water_lake", lambda: _ripple_water("#3a9cc4", seed=115))
    G.setdefault("grass_lush", lambda: X._grass("#62b03a", seed=116))
    G.setdefault("grass_dark", lambda: X._grass("#4f9a33", seed=117))


_register()


# ------------------------------------------------------------------ raw geometry accumulator
_ICO = {}


def _ico_data(sub):
    if sub not in _ICO:
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
        v = np.array([x.co[:] for x in bm.verts], np.float64)
        f = [[x.index for x in face.verts] for face in bm.faces]
        bm.free()
        _ICO[sub] = (v, f)
    return _ICO[sub]


def _norm(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-9)


class Geo:
    """Accumulates verts/faces/material slots/UVs/custom normals, then builds one bpy Mesh."""

    def __init__(self):
        self.V, self.F, self.M, self.UV, self.N = [], [], [], [], []
        self.n = 0

    def add(self, verts, faces, mi=0, uvs=None, normals=None):
        verts = np.asarray(verts, np.float64)
        b = self.n
        for k, f in enumerate(faces):
            self.F.append([b + i for i in f])
            self.M.append(mi)
            self.UV.append(uvs[k] if uvs is not None else None)
        self.V.append(verts)
        self.N.append(np.full((len(verts), 3), np.nan) if normals is None else np.asarray(normals, np.float64))
        self.n += len(verts)
        return b

    # -- primitives
    def ico(self, c, radii, mi=0, sub=1, jitter=0.0, seed=0, ncenter=None, nblend=0.6):
        v0, f = _ico_data(sub)
        r = _rng(seed)
        v = v0 * (1 + r.uniform(-jitter, jitter, (len(v0), 1))) if jitter else v0.copy()
        v = v * np.asarray(radii) + np.asarray(c)
        nrm = None
        if ncenter is not None:
            nrm = _norm(nblend * _norm(v - np.asarray(ncenter)) + (1 - nblend) * _norm(v - np.asarray(c)))
        self.add(v, f, mi, normals=nrm)

    def cyl(self, p0, p1, r0, r1, mi=0, verts=7, cap=False, seed=None, jitter=0.0):
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        ax = p1 - p0
        L = np.linalg.norm(ax)
        z = ax / max(L, 1e-9)
        t = np.array((1, 0, 0)) if abs(z[0]) < 0.9 else np.array((0, 1, 0))
        x = _norm(np.cross(t, z))
        y = np.cross(z, x)
        r = _rng(seed or 0)
        vs = []
        for (p, rad) in ((p0, r0), (p1, r1)):
            for i in range(verts):
                a = TAU * i / verts
                rr = rad * (1 + (r.uniform(-jitter, jitter) if jitter else 0))
                vs.append(p + (x * math.cos(a) + y * math.sin(a)) * rr)
        fs = [[i, (i + 1) % verts, verts + (i + 1) % verts, verts + i] for i in range(verts)]
        if cap:
            fs.append(list(range(verts, 2 * verts)))
            fs.append(list(range(verts))[::-1])
        self.add(vs, fs, mi)

    def tube(self, pts, radii, mi=0, verts=7):
        for i in range(len(pts) - 1):
            self.cyl(pts[i], pts[i + 1], radii[i], radii[i + 1], mi, verts)

    def cone_star(self, c, r, h, mi=0, n=8, inner=0.72, seed=0, ncenter=None, droop=0.18):
        """Jagged pine tier: star-shaped skirt ring (alternating radii) up to an apex."""
        r_ = _rng(seed)
        c = np.asarray(c, float)
        vs = [c + (0, 0, h)]
        off = r_.uniform(0, TAU)
        for i in range(2 * n):
            a = off + TAU * i / (2 * n)
            rr = r * (1 if i % 2 == 0 else inner) * r_.uniform(0.9, 1.08)
            dz = -droop * h if i % 2 == 0 else 0.0
            vs.append(c + (math.cos(a) * rr, math.sin(a) * rr, dz))
        m = 2 * n
        fs = [[0, 1 + i, 1 + (i + 1) % m] for i in range(m)]
        vs.append(c + (0, 0, h * 0.12))
        fs += [[m + 1, 1 + (i + 1) % m, 1 + i] for i in range(m)]
        vs = np.array(vs)
        nrm = None
        if ncenter is not None:
            nrm = _norm(0.55 * _norm(vs - np.asarray(ncenter)) + 0.45 * np.array((0, 0, 0.6)) + 0.0)
        self.add(vs, fs, mi, normals=nrm)

    def box(self, c, size, mi=0, rotz=0.0):
        c = np.asarray(c, float)
        hx, hy, hz = np.asarray(size) / 2
        cz, sz = math.cos(rotz), math.sin(rotz)
        vs = []
        for (x, y, z) in [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]:
            px, py = x * hx, y * hy
            vs.append(c + (px * cz - py * sz, px * sz + py * cz, z * hz))
        fs = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
        self.add(vs, fs, mi)

    def card(self, c, w, h, normal, up=(0, 0, 1), mi=0, roll=0.0, nrm=None, uv=(0, 0, 1, 1)):
        n = _norm(normal)
        u = np.asarray(up, float)
        if abs(np.dot(u, n)) > 0.95:
            u = np.array((0, 1, 0)) if abs(n[1]) < 0.95 else np.array((1, 0, 0))
        rt = _norm(np.cross(u, n))
        u = np.cross(n, rt)
        if roll:
            cr, sr = math.cos(roll), math.sin(roll)
            rt, u = rt * cr + u * sr, -rt * sr + u * cr
        c = np.asarray(c, float)
        hw, hh = w / 2, h / 2
        vs = [c - rt * hw - u * hh, c + rt * hw - u * hh, c + rt * hw + u * hh, c - rt * hw + u * hh]
        u0, v0, u1, v1 = uv
        nn = None if nrm is None else np.tile(_norm(nrm), (4, 1)) if np.ndim(nrm) == 1 else nrm
        self.add(vs, [[0, 1, 2, 3]], mi, uvs=[[(u0, v0), (u1, v0), (u1, v1), (u0, v1)]], normals=nn)

    def vcard(self, base, w, h, yaw, mi=0, nrm_up=0.0):
        """Vertical card standing on base (bottom centre)."""
        n = np.array((math.sin(yaw), -math.cos(yaw), 0.0))
        c = np.asarray(base, float) + (0, 0, h / 2)
        nn = None
        if nrm_up:
            nn = _norm(n * (1 - nrm_up) + np.array((0, 0, nrm_up)))
        self.card(c, w, h, n, mi=mi, nrm=nn)

    def strip(self, pts, widths, side, mi=0, nrm=None):
        """Ribbon along pts (Nx3) with half-widths, spread along `side` vectors (Nx3). UV u along length."""
        pts = np.asarray(pts, float)
        n = len(pts)
        vs, fs, uvs = [], [], []
        for i in range(n):
            vs.append(pts[i] - side[i] * widths[i])
            vs.append(pts[i] + side[i] * widths[i])
        for i in range(n - 1):
            a = 2 * i
            fs.append([a, a + 2, a + 3, a + 1])
            u0, u1 = i / (n - 1), (i + 1) / (n - 1)
            uvs.append([(u0, 0), (u1, 0), (u1, 1), (u0, 1)])
        nn = None if nrm is None else np.tile(_norm(nrm), (len(vs), 1))
        self.add(vs, fs, mi, uvs=uvs, normals=nn)

    # -- output
    def build(self, name, mats):
        V = np.vstack(self.V) if self.V else np.zeros((0, 3))
        me = bpy.data.meshes.new(name)
        me.from_pydata(V.tolist(), [], self.F)
        for m in mats:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", self.M)
        if any(u is not None for u in self.UV):
            uvl = me.uv_layers.new(name="UVMap")
            flat = []
            for u in self.UV:
                if u is None:
                    flat.extend([0.0, 0.0] * 0)
                else:
                    pass
            data = np.zeros((len(me.loops), 2), np.float32)
            k = 0
            for f, u in zip(self.F, self.UV):
                if u is not None:
                    data[k:k + len(f)] = u
                k += len(f)
            uvl.data.foreach_set("uv", data.ravel())
        me.update()
        N = np.vstack(self.N)
        if np.isfinite(N).any():
            pn = np.zeros(len(me.polygons) * 3)
            me.polygons.foreach_get("normal", pn)
            pn = pn.reshape(-1, 3)
            lv = np.zeros(len(me.loops), int)
            me.loops.foreach_get("vertex_index", lv)
            lp = np.repeat(np.arange(len(me.polygons)), [len(f) for f in self.F])
            ln = N[lv]
            bad = ~np.isfinite(ln[:, 0])
            ln[bad] = pn[lp[bad]]
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
            try:
                me.normals_split_custom_set([tuple(x) for x in ln])
            except Exception as e:  # pragma: no cover
                print("custom normals failed", e)
        return me


# ------------------------------------------------------------------ placing
def _coll():
    return bpy.context.scene.collection


def obj(me, name=None, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name or me.name, me)
    _coll().objects.link(o)
    o.location = loc
    return o


def place(me, loc, yaw=0.0, s=1.0, name=None, tilt=(0.0, 0.0)):
    o = bpy.data.objects.new(name or me.name, me)
    _coll().objects.link(o)
    o.location = loc
    o.rotation_euler = (math.radians(tilt[0]), math.radians(tilt[1]), math.radians(yaw))
    o.scale = (s, s, s) if np.isscalar(s) else s
    return o


def _inside(x, y, rc):
    return rc[0] <= x <= rc[1] and rc[2] <= y <= rc[3]


def scatter(protos, area, count, seed=0, avoid=(), zfn=None, scale=(0.8, 1.2), mind=0.0, accept=None, sink=0.0,
            yaw=(0, 360), weights=None):
    """Place linked duplicates of random protos inside area=(x0,x1,y0,y1); avoid=[rects]; accept(x,y)->bool."""
    r = _rng(seed)
    pts, tries = [], 0
    while len(pts) < count and tries < count * 40:
        tries += 1
        x, y = r.uniform(area[0], area[1]), r.uniform(area[2], area[3])
        if any(_inside(x, y, rc) for rc in avoid):
            continue
        if accept is not None and not accept(x, y):
            continue
        if mind and any((x - p[0]) ** 2 + (y - p[1]) ** 2 < mind * mind for p in pts):
            continue
        pts.append((x, y))
    out = []
    w = None if weights is None else np.asarray(weights, float) / np.sum(weights)
    for (x, y) in pts:
        me = protos[r.choice(len(protos), p=w)]
        z = float(zfn(np.array(x), np.array(y))) if zfn is not None else 0.0
        out.append(place(me, (x, y, z - sink), r.uniform(*yaw), r.uniform(*scale)))
    return out


def line_scatter(protos, pts, step, jitter, seed=0, zfn=None, scale=(0.8, 1.2), sink=0.0):
    """Place along a polyline every ~step metres (hedges, reed belts, tree rows)."""
    r = _rng(seed)
    out = []
    for i in range(len(pts) - 1):
        a, b = np.asarray(pts[i], float), np.asarray(pts[i + 1], float)
        L = np.linalg.norm(b - a)
        for k in range(max(1, int(L / step))):
            p = a + (b - a) * (k / max(1, int(L / step))) + r.uniform(-jitter, jitter, 2)
            z = float(zfn(np.array(p[0]), np.array(p[1]))) if zfn is not None else 0.0
            out.append(place(protos[r.integers(len(protos))], (p[0], p[1], z - sink), r.uniform(0, 360),
                             r.uniform(*scale)))
    return out


# ------------------------------------------------------------------ terrain
def axis(half, fine_half, fine_step, coarse_step, grow=1.15, center=0.0):
    """Symmetric 1D coordinates: fine spacing within +-fine_half, growing to coarse_step out to +-half."""
    pos, x, step = [0.0], 0.0, fine_step
    while x < half:
        if x >= fine_half:
            step = min(coarse_step, step * grow)
        x += step
        pos.append(x)
    p = np.array(pos)
    return np.concatenate([-p[:0:-1], p]) + center


def terrain(name, xs, ys, hfn, mats, mfn=None, slope_mat=None, slope=0.62):
    """Displaced grid. hfn(X, Y)->Z (numpy). mfn(cx, cy, cz)->material index per face. slope_mat: index for steep faces."""
    Xg, Yg = np.meshgrid(np.asarray(xs, float), np.asarray(ys, float))
    Z = hfn(Xg, Yg)
    nx, ny = len(xs), len(ys)
    V = np.stack([Xg, Yg, Z], -1).reshape(-1, 3)
    I, J = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1))
    a = (J * nx + I).ravel()
    Fc = np.stack([a, a + 1, a + 1 + nx, a + nx], 1)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V))
    me.vertices.foreach_set("co", V.astype(np.float32).ravel())
    me.loops.add(Fc.size)
    me.loops.foreach_set("vertex_index", Fc.astype(np.int32).ravel())
    me.polygons.add(len(Fc))
    me.polygons.foreach_set("loop_start", np.arange(0, Fc.size, 4, dtype=np.int32))
    me.update(calc_edges=True)
    for m in mats:
        me.materials.append(m)
    if mfn is not None or slope_mat is not None:
        P = V[Fc]
        cen = P.mean(1)
        idx = np.zeros(len(Fc), np.int32) if mfn is None else np.asarray(mfn(cen[:, 0], cen[:, 1], cen[:, 2]), np.int32)
        if slope_mat is not None:
            n = np.cross(P[:, 1] - P[:, 0], P[:, 3] - P[:, 0])
            nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-9)
            idx = np.where(nz < slope, slope_mat, idx)
        me.polygons.foreach_set("material_index", idx)
    o = bpy.data.objects.new(name, me)
    _coll().objects.link(o)
    return o


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def fbm(x, y, seed=0, octaves=3, scale=20.0):
    """Cheap smooth noise for height fields (sum of sines with random phases; vectorised, deterministic)."""
    r = _rng(seed)
    out = np.zeros_like(np.asarray(x, float))
    amp, sc = 1.0, scale
    for _ in range(octaves):
        for _k in range(3):
            a = r.uniform(0, TAU)
            ph = r.uniform(0, TAU)
            out = out + amp * np.sin((x * math.cos(a) + y * math.sin(a)) / sc + ph) / 3
        amp *= 0.5
        sc *= 0.5
    return out


def flat_stage(x, y, rect=(-4.6, 5.6, -2.0, 6.4), blend=3.0):
    """Weight 1 inside the stage rect, fading to 0 over `blend` metres outside (multiply heights by 1-w)."""
    dx = np.maximum(np.maximum(rect[0] - x, x - rect[1]), 0)
    dy = np.maximum(np.maximum(rect[2] - y, y - rect[3]), 0)
    d = np.sqrt(dx * dx + dy * dy)
    return 1 - smoothstep(0, blend, d)


def water(name, loc, size, tex="water_lake", speed=(0.04, 0.015), opacity=0.78, amp=0.0, subdiv=2):
    """Animated pixel water plane; opacity<1 lets the lake bed / seaweed show through (dithered)."""
    m = X.mat(tex, name=f"{name}_mat", anim=speed, shadow=0.85)
    if opacity < 1:
        nt = m.node_tree
        out = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"][0]
        src = out.inputs[0].links[0].from_socket
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = opacity
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(src, mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs[0])
        try:
            m.surface_render_method = "DITHERED"
        except Exception:
            pass
    hx, hy = size[0] / 2, size[1] / 2
    n = max(1, subdiv)
    vs, fs = [], []
    for j in range(n + 1):
        for i in range(n + 1):
            vs.append((-hx + 2 * hx * i / n, -hy + 2 * hy * j / n, 0))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            fs.append([a, a + 1, a + n + 2, a + n + 1])
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs, [], fs)
    me.materials.append(m)
    o = obj(me, name, loc)
    if amp:
        w = o.modifiers.new("swell", "WAVE")
        w.height = amp
        w.width = 1.5
        w.speed = 0.03
        w.use_normal = False
    return o


# ------------------------------------------------------------------ vegetation prototypes (return bpy Mesh)
def _crown(g, r, center, R, n_cl, mi_core, mi_card, card_size=(1.6, 2.3), cards_per=5, flat=0.85, squash=0.85):
    """Leaf crown around center with radius R (x/y) made of n_cl clusters + outward cards."""
    center = np.asarray(center, float)
    cl = [(center, R * 0.62)]
    for k in range(n_cl - 1):
        a = r.uniform(0, TAU)
        el = r.uniform(-0.35, 0.9)
        d = R * r.uniform(0.35, 0.62)
        p = center + np.array((math.cos(a) * math.cos(el) * d, math.sin(a) * math.cos(el) * d, math.sin(el) * d * squash))
        cl.append((p, R * r.uniform(0.32, 0.5)))
    for (p, rad) in cl:
        g.ico(p, (rad, rad, rad * flat), mi_core, sub=1, jitter=0.12, seed=int(r.integers(1e6)), ncenter=center, nblend=0.75)
    for (p, rad) in cl:
        for _ in range(cards_per):
            d = _norm(r.normal(size=3) + np.array((0, 0, 0.35)))
            out = _norm(0.6 * d + 0.4 * _norm(p - center + 1e-6))
            if out[2] < -0.55:
                continue
            q = p + out * rad * r.uniform(0.7, 1.0)
            s = r.uniform(*card_size)
            nn = _norm(0.7 * _norm(q - center) + 0.3 * np.array((0, 0, 1)))
            g.card(q, s, s * 0.92, out, mi=mi_card, roll=r.uniform(-0.6, 0.6), nrm=nn)
    return cl


def tree_round(seed=0, h=8.0, crown_r=3.0, leaf="leafclump", core="leaves_core", bark="bark", n_cl=10, cards_per=6,
               trunk_r=0.28, name=None, crown_h=0.56, branches=4):
    """Deciduous tree: tapered trunk + branches + layered leaf clusters with leafy alpha cards."""
    r = _rng(seed)
    g = Geo()
    top = np.array((r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3), h * crown_h))
    mid = np.array((top[0] * 0.4, top[1] * 0.4, h * 0.35))
    g.tube([(0, 0, -0.3), mid, top], [trunk_r * 1.25, trunk_r * 0.85, trunk_r * 0.45], 0, verts=7)
    g.cyl((0, 0, -0.3), (0, 0, 0.25), trunk_r * 1.6, trunk_r * 1.2, 0, verts=7)   # root flare
    cc = top + np.array((0, 0, crown_r * 0.25))
    for b in range(branches):
        a = r.uniform(0, TAU)
        p0 = mid + (top - mid) * r.uniform(0.3, 0.8)
        p1 = cc + np.array((math.cos(a) * crown_r * 0.6, math.sin(a) * crown_r * 0.6, r.uniform(-0.6, 0.4)))
        g.cyl(p0, p1, trunk_r * 0.45, trunk_r * 0.2, 0, verts=5)
    _crown(g, r, cc, crown_r, n_cl, 1, 2, cards_per=cards_per)
    return g.build(name or f"tree_round_{seed}", [X.mat(bark), X.mat(core), X.mat(leaf, uv=True, alpha=True, shadow=0.66)])


def tree_tall(seed=0, h=11.0, crown_r=2.0, leaf="leafclump_light", core="leaves_core_light", bark="bark", name=None):
    """Tall poplar-ish tree (reference background): long visible trunk, stacked narrow clusters."""
    r = _rng(seed)
    g = Geo()
    lean = np.array((r.uniform(-0.4, 0.4), r.uniform(-0.4, 0.4), 0))
    g.tube([(0, 0, -0.3), lean * 0.5 + (0, 0, h * 0.5), lean + (0, 0, h * 0.95)], [0.24, 0.17, 0.08], 0, verts=6)
    for k in range(4):
        f = 0.42 + 0.15 * k
        c = lean * f + np.array((r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3), h * f))
        _crown(g, r, c, crown_r * (1.05 - 0.17 * k), 4, 1, 2, card_size=(1.5, 2.2), cards_per=5, flat=1.1, squash=1.2)
    return g.build(name or f"tree_tall_{seed}", [X.mat(bark), X.mat(core), X.mat(leaf, uv=True, alpha=True, shadow=0.66)])


def tree_birch(seed=0, h=7.5, name=None):
    r = _rng(seed)
    g = Geo()
    lean = np.array((r.uniform(-0.6, 0.6), r.uniform(-0.6, 0.6), 0))
    g.tube([(0, 0, -0.3), lean * 0.5 + (0, 0, h * 0.5), lean + (0, 0, h)], [0.14, 0.11, 0.05], 0, verts=6)
    for k in range(3):
        z = h * (0.55 + 0.15 * k)
        c = lean * (0.55 + 0.15 * k) + np.array((r.uniform(-0.4, 0.4), r.uniform(-0.4, 0.4), z))
        _crown(g, r, c, 1.3 - 0.2 * k, 2, 1, 2, card_size=(1.1, 1.6), cards_per=4)
    return g.build(name or f"tree_birch_{seed}", [X.mat("bark_birch"), X.mat("leaves_core_light"),
                                                 X.mat("leafclump_yellow", uv=True, alpha=True, shadow=0.66)])


def tree_pine(seed=0, h=10.0, r0=2.4, tiers=6, name=None, solid="pine_solid", bark="bark"):
    r = _rng(seed)
    g = Geo()
    g.cyl((0, 0, -0.3), (0, 0, h * 0.85), 0.24, 0.08, 0, verts=6)
    base = h * 0.18
    cen = np.array((0, 0, h * 0.55))
    for k in range(tiers):
        t = k / max(1, tiers - 1)
        rr = r0 * (1 - 0.78 * t) * r.uniform(0.92, 1.05)
        z = base + (h - base) * t * 0.82
        g.cone_star((0, 0, z), rr, (h - base) / tiers * 2.0, 1, n=7, seed=int(r.integers(1e6)), ncenter=cen)
    return g.build(name or f"tree_pine_{seed}", [X.mat(bark), X.mat(solid)])


def tree_cypress(seed=0, h=7.0, r0=0.9, name=None):
    """Narrow Mediterranean cypress (desert/park): stacked elongated clusters."""
    r = _rng(seed)
    g = Geo()
    g.cyl((0, 0, -0.3), (0, 0, 1.0), 0.15, 0.12, 0, verts=6)
    cen = np.array((0, 0, h * 0.5))
    for k in range(4):
        z = 1.0 + (h - 1.4) * (k + 0.5) / 4
        rr = r0 * (1.0 - 0.2 * abs(k - 1.2)) * r.uniform(0.9, 1.1)
        g.ico((r.uniform(-0.1, 0.1), r.uniform(-0.1, 0.1), z), (rr, rr, (h - 1.4) / 4 * 0.85), 1, sub=1, jitter=0.15,
              seed=int(r.integers(1e6)), ncenter=cen, nblend=0.6)
    for _ in range(14):
        z = r.uniform(1.4, h - 0.5)
        a = r.uniform(0, TAU)
        rr = r0 * 0.9 * (1 - abs(z / h - 0.45))
        q = np.array((math.cos(a) * rr, math.sin(a) * rr, z))
        out = _norm(np.array((math.cos(a), math.sin(a), 0.2)))
        g.card(q, 0.9, 1.3, out, mi=2, nrm=_norm(q - cen))
    return g.build(name or f"tree_cypress_{seed}", [X.mat("bark"), X.mat("cypress_solid"),
                                                   X.mat("leafclump_dark", uv=True, alpha=True, shadow=0.66)])


def bush(seed=0, r0=0.9, leaf="leafclump", core="leaves_core", n=3, name=None, flowers=None):
    r = _rng(seed)
    g = Geo()
    cen = np.array((0, 0, r0 * 0.55))
    for k in range(n):
        a = r.uniform(0, TAU)
        d = r0 * r.uniform(0.1, 0.55)
        p = np.array((math.cos(a) * d, math.sin(a) * d, r0 * r.uniform(0.45, 0.7)))
        rad = r0 * r.uniform(0.5, 0.75)
        g.ico(p, (rad, rad, rad * 0.8), 0, sub=1, jitter=0.15, seed=int(r.integers(1e6)), ncenter=cen, nblend=0.7)
        for _ in range(4):
            d3 = _norm(r.normal(size=3) + np.array((0, 0, 0.6)))
            q = p + d3 * rad * 0.8
            s = r0 * r.uniform(1.0, 1.4)
            g.card(q, s, s * 0.9, d3, mi=1, roll=r.uniform(-0.5, 0.5), nrm=_norm(q - cen + (0, 0, 0.4)))
    mats = [X.mat(core), X.mat(leaf, uv=True, alpha=True, shadow=0.66)]
    if flowers:
        for _ in range(7):
            d3 = _norm(r.normal(size=3) + np.array((0, 0, 0.9)))
            q = cen + d3 * r0 * 0.75
            g.ico(q, (0.07, 0.07, 0.06), 2, sub=1)
        mats.append(X.mat(flowers))
    return g.build(name or f"bush_{seed}", mats)


def palm(seed=0, h=7.0, lean=1.6, n_fronds=9, name=None, frond="frond"):
    """Palm: curved segmented trunk (ring texture + rims) + drooping alpha fronds + coconuts."""
    r = _rng(seed)
    g = Geo()
    a = r.uniform(0, TAU)
    dirv = np.array((math.cos(a), math.sin(a), 0))
    n = 8
    pts = [dirv * lean * (i / n) ** 1.7 + np.array((0, 0, h * i / n - 0.3 * (i == 0))) for i in range(n + 1)]
    rad = [0.24 - 0.09 * (i / n) for i in range(n + 1)]
    for i in range(n):
        g.cyl(pts[i], pts[i + 1], rad[i] * 1.08, rad[i + 1] * 0.92, 0, verts=7)
    top = pts[-1]
    g.ico(top + (0, 0, 0.1), (0.3, 0.3, 0.25), 0, sub=1)
    for k in range(3):
        aa = TAU * k / 3 + r.uniform(-0.3, 0.3)
        g.ico(top + (math.cos(aa) * 0.22, math.sin(aa) * 0.22, -0.15), (0.13, 0.13, 0.13), 2, sub=1)
    for k in range(n_fronds):
        aa = TAU * k / n_fronds + r.uniform(-0.2, 0.2)
        d = np.array((math.cos(aa), math.sin(aa), 0))
        side = np.cross(d, (0, 0, 1))
        up = r.uniform(0.35, 0.9)
        L = r.uniform(2.6, 3.4)
        seg = 6
        p = top + (0, 0, 0.15)
        dv = _norm(d + np.array((0, 0, up)))
        ps = [p.copy()]
        for i in range(seg):
            p = p + dv * L / seg
            ps.append(p.copy())
            dv = _norm(dv + np.array((0, 0, -0.32)))
        widths = [0.08 + 0.5 * math.sin(math.pi * min(1, (i / seg) * 1.15)) * 0.9 for i in range(seg + 1)]
        widths[-1] = 0.05
        # leaflets fold down a bit: tilt side vector
        sides = [_norm(side + np.array((0, 0, -0.25))) for _ in ps]
        g.strip(ps, widths, sides, mi=1, nrm=np.array((0, 0, 1)) + d * 0.3)
    return g.build(name or f"palm_{seed}", [X.mat("bark_palm"), X.mat(frond, uv=True, alpha=True, shadow=0.7),
                                           X.mat("#6b4a2a")])


def clump(tex, w=1.0, h=1.6, n=3, seed=0, name=None, spread=0.25, nrm_up=0.5, shadow=0.7):
    """Crossed alpha cards (reeds, papyrus, grass tufts, flowers, seaweed)."""
    r = _rng(seed)
    g = Geo()
    for k in range(n):
        yaw = math.pi * k / n + r.uniform(-0.2, 0.2)
        off = r.uniform(-spread, spread, 2)
        g.vcard((off[0], off[1], -0.05), w * r.uniform(0.85, 1.15), h * r.uniform(0.85, 1.1), yaw, 0, nrm_up=nrm_up)
    return g.build(name or f"clump_{tex}_{seed}", [X.mat(tex, uv=True, alpha=True, shadow=shadow)])


def rock(seed=0, size=(1.2, 1.0, 0.7), tex="rock", sub=1, jitter=0.22, name=None, tile_m=None):
    r = _rng(seed)
    g = Geo()
    v0, f = _ico_data(sub)
    v = v0 * (1 + r.uniform(-jitter, jitter, (len(v0), 1))) * np.asarray(size) / 2
    v[:, 2] = np.maximum(v[:, 2], -size[2] * 0.2)   # flat-ish bottom, sits on ground
    v[:, 2] += size[2] * 0.15
    g.add(v, f, 0)
    return g.build(name or f"rock_{tex}_{seed}", [X.mat(tex, tile_m=tile_m)])


def far_tree_blob(seed=0, h=9.0, r0=3.0, core="leaves_core", leaf="leafclump_dark", cards=8, name=None, bark="bark"):
    """Cheap background tree for tree lines: 3 clusters + a few cards."""
    r = _rng(seed)
    g = Geo()
    g.cyl((0, 0, -0.5), (0, 0, h * 0.6), 0.3, 0.15, 0, verts=5)
    cen = np.array((0, 0, h * 0.66))
    for k in range(3):
        p = cen + np.array((r.uniform(-1, 1) * r0 * 0.4, r.uniform(-1, 1) * r0 * 0.4, r.uniform(-0.3, 0.6) * r0 * 0.5))
        rad = r0 * r.uniform(0.55, 0.75)
        g.ico(p, (rad, rad, rad * 0.95), 1, sub=1, jitter=0.15, seed=int(r.integers(1e6)), ncenter=cen, nblend=0.8)
    for _ in range(cards):
        d = _norm(r.normal(size=3) + np.array((0, 0, 0.5)))
        q = cen + d * r0 * 0.75
        s = r0 * r.uniform(0.8, 1.1)
        g.card(q, s, s, d, mi=2, roll=r.uniform(-0.5, 0.5), nrm=_norm(d + (0, 0, 0.3)))
    return g.build(name or f"far_tree_{seed}", [X.mat(bark), X.mat(core), X.mat(leaf, uv=True, alpha=True, shadow=0.66)])


def cliff_band(name, pts, height, zfn=None, depth=3.0, tex="rock_red", cap_tex="sand", seed=0, step=1.6, res=1.4):
    """Rocky low-poly wall along a polyline (pts on the ground, wall faces to the LEFT of travel direction)
    with a flat-ish top cap. Strata: vertical rows displaced by noise."""
    r = _rng(seed)
    pts = np.asarray(pts, float)
    # resample
    P = [pts[0]]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, int(np.linalg.norm(b - a) / step))
        for k in range(1, n + 1):
            P.append(a + (b - a) * k / n)
    P = np.array(P)
    nU = len(P)
    rows = max(2, int(height / res) + 1)
    g = Geo()
    vs = []
    for i in range(nU):
        if i == 0:
            t = P[1] - P[0]
        elif i == nU - 1:
            t = P[-1] - P[-2]
        else:
            t = P[i + 1] - P[i - 1]
        t = _norm(np.array((t[0], t[1], 0)))
        nrm = np.array((-t[1], t[0], 0))      # left side
        z0 = float(zfn(np.array(P[i][0]), np.array(P[i][1]))) if zfn is not None else 0.0
        hh = height * r.uniform(0.85, 1.15)
        for j in range(rows):
            f = j / (rows - 1)
            push = r.uniform(-0.35, 0.35) + 0.5 * math.sin(f * 7 + i * 0.7) * 0.3 - f * 0.6
            vs.append(np.array((P[i][0], P[i][1], z0 - 0.5 + (hh + 0.5) * f)) + nrm * push)
        # cap row going back
        vs.append(np.array((P[i][0], P[i][1], z0 + hh)) - nrm * depth * 0.5 + nrm * -0.0)
        vs.append(np.array((P[i][0], P[i][1], z0 + hh * 0.9)) - nrm * depth)
    R = rows + 2
    fw, fc = [], []
    for i in range(nU - 1):
        for j in range(R - 1):
            a = i * R + j
            quad = [a, a + R, a + R + 1, a + 1]
            (fw if j < rows - 1 else fc).append(quad)
    g.add(vs, fw, 0)
    b = g.n
    g.V.append(np.zeros((0, 3)))
    g.N.append(np.zeros((0, 3)))
    for q in fc:
        g.F.append(q)
        g.M.append(1)
        g.UV.append(None)
    return obj(g.build(name, [X.mat(tex), X.mat(cap_tex)]), name)
