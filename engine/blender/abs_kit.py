"""Procedural low-poly pixel-art PROP KIT (target: Patryk's reference reel - genuinely modelled low-poly game props
with chunky tiling pixel textures, soft sun shading, no outlines).

    import abs_kit as K
    root = K.build("dam", {"state": "broken"})     # Empty KIT_dam at the origin, all parts parented to it
    K.catalog()                                     # [{'name','desc','params','size'}] for the Script Writer prompt

Conventions: real-world metres (a person is 1.6 m), base on z=0, centred on x/y, FRONT faces -Y. Parts are built as
real geometry (thickness, openings, steps) and textured with abs_pix materials sampled in OBJECT space, so texel size
is the same everywhere (abs_pix.TEXEL_M). Moving parts (wheels, water, flames, smoke, flags, bobbing boats) animate by
themselves through simple frame drivers / scrolling textures; nothing needs keyframes. Unknown kit names fall back to
`generic` (primitive composition from an LLM part list, or a tidy crate).

Root custom props: kit (resolved name), kit_height (nominal height of the hero object, e.g. the dam crest - use it to
scale to a requested height; valley abutments may stand taller), kit_size (w, d, h of the full bounding box).
"""
import math
import random
import traceback
from contextlib import contextmanager

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

import abs_pix as X

CH = 8 * X.TEXEL_M          # one limestone course of stone_block (8 texels = 1/3 m): steps snap to it
KITS = {}
_CNT = [0]


# ------------------------------------------------------------------ params / materials
def num(p, k, d):
    try:
        v = p.get(k, d)
        return float(d if v is None else v)
    except Exception:
        return float(d)


def flag(p, k, d):
    v = p.get(k, d)
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "none", "")
    return bool(v)


def word(p, k, d):
    v = p.get(k, d)
    return str(v if v is not None else d).strip().lower()


ALIAS_TEX = {
    "wood": "planks", "timber": "planks", "plank": "planks", "board": "planks", "wooden": "planks",
    "dark wood": "planks_dark", "stone": "stone_brick", "brick": "red_brick", "bricks": "red_brick",
    "limestone": "stone_block", "sandstone": "stone_block", "block": "stone_block", "granite": "rock_grey",
    "steel": "metal", "cloth": "canvas", "fabric": "canvas", "tent": "canvas", "leaf": "leaves_solid",
    "leaves": "leaves_solid", "foliage": "leaves_solid", "straw": "hay", "earth": "dirt", "soil": "dirt",
    "mud brick": "mudbrick", "adobe": "mudbrick", "roof": "roof_red", "tiles": "roof_red", "bark": "bark",
    "log": "log", "copper": "#c07a45", "bronze": "#b8863b", "silver": "#c9ced6", "white": "#f2efe8",
    "black": "#2b2b30", "red": "#c8443c", "blue": "#3e64b0", "green": "#4f9a35", "yellow": "#e8c23a",
    "orange": "#e8792b", "brown": "#7e5532", "grey": "#8e8b84", "gray": "#8e8b84", "pink": "#e88fb0",
    "purple": "#8a5fbf", "cream": "#efe2c4", "beige": "#d9c7a0", "tan": "#c9a978", "teal": "#3f9f9a",
    "pottery": "clay", "terracotta": "clay", "ceramic": "ceramic_white", "marble": "plaster_white",
    "ice": "glass", "rope": "rope", "sack": "sacking", "burlap": "sacking", "fire": "flame",
}


def T(tex, **kw):
    """Material from a generator name, '#hex', colour word, (r,g,b) or an existing material (never raises)."""
    if isinstance(tex, bpy.types.Material):
        return tex
    if tex is None:
        tex = "planks"
    if isinstance(tex, (tuple, list)):
        return X.mat(tuple(float(v) for v in tex[:3]), **kw)
    t = str(tex).strip()
    if t in X.GEN:
        return X.mat(t, **kw)
    if t.startswith("#"):
        h = t.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            int(h, 16)
            return X.mat("#" + h[:6], **kw)
        except ValueError:
            pass
    k = t.lower().replace("-", "_")
    if k in X.GEN:
        return X.mat(k, **kw)
    a = ALIAS_TEX.get(k.replace("_", " ")) or ALIAS_TEX.get(k)
    if a:
        return T(a, **kw)
    for g in X.GEN:
        if g in k or (len(k) > 3 and k in g):
            return X.mat(g, **kw)
    return X.mat("planks", **kw)


def DARK():
    return X.mat("#241a14", name="kit_dark_interior", emit=True)


# ------------------------------------------------------------------ mesh builder (batched geometry, one object)
HF = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]  # bottom top -Y +Y -X +X


def _mats6(m):
    if isinstance(m, dict):
        side = m.get("side", m.get("top"))
        return [m.get("bottom", side), m.get("top", side), m.get("front", side), m.get("back", side),
                m.get("left", side), m.get("right", side)]
    if isinstance(m, (list, tuple)):
        return list(m)
    return [m] * 6


def _rot(rot):
    return Euler(tuple(math.radians(a) for a in rot)).to_matrix().to_4x4()


class MB:
    """Accumulates low-poly parts (boxes, hexahedra, cylinders, lathes, prisms, strips) into ONE mesh object."""

    def __init__(self):
        self.v, self.f, self.fm, self.uv, self.mats = [], [], [], [], []
        self.T = Matrix.Identity(4)

    @contextmanager
    def at(self, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
        old = self.T
        self.T = old @ Matrix.Translation(Vector(loc)) @ _rot(rot) @ Matrix.Scale(scale, 4)
        try:
            yield self
        finally:
            self.T = old

    def _mi(self, m):
        for i, mm in enumerate(self.mats):
            if mm is m:
                return i
        self.mats.append(m)
        return len(self.mats) - 1

    def add(self, verts, faces, mats, uvs=None):
        b = len(self.v)
        self.v.extend(self.T @ Vector(v) for v in verts)
        for k, f in enumerate(faces):
            self.f.append(tuple(b + i for i in f))
            m = mats[k] if isinstance(mats, (list, tuple)) else mats
            self.fm.append(self._mi(m))
            self.uv.append(uvs[k] if uvs else None)
        return b

    def hexa(self, c8, m):
        """Eight corners indexed x-bit | y-bit<<1 | z-bit<<2 (any convex distortion of a box: wedges, ramps)."""
        self.add(c8, HF, _mats6(m))

    def box(self, c, s, m, rot=(0, 0, 0)):
        R = _rot(rot)
        pts = []
        for i in range(8):
            v = Vector((((i & 1) * 2 - 1) * s[0] / 2, (((i >> 1) & 1) * 2 - 1) * s[1] / 2, (((i >> 2) & 1) * 2 - 1) * s[2] / 2))
            pts.append(Vector(c) + (R @ v.to_4d()).to_3d())
        self.hexa(pts, m)

    def box2(self, a, b, m):
        """Axis-aligned box from min corner a to max corner b."""
        self.box(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2), (abs(b[0] - a[0]), abs(b[1] - a[1]), abs(b[2] - a[2])), m)

    def cyl(self, c, r, h, m, n=8, r2=None, rot=(0, 0, 0), caps=True, mcap=None, a0=None):
        """Cylinder/frustum/cone (r2=0) along local Z centred at c, rotated by rot (deg)."""
        r2 = r if r2 is None else r2
        a0 = (math.pi / n) if a0 is None else a0
        R = _rot(rot)
        vs = []
        for z, rr in ((-h / 2, r), (h / 2, r2)):
            for i in range(n):
                a = a0 + 2 * math.pi * i / n
                vs.append(Vector(c) + (R @ Vector((rr * math.cos(a), rr * math.sin(a), z, 1))).to_3d())
        fs, ms = [], []
        for i in range(n):
            j = (i + 1) % n
            fs.append((i, j, n + j, n + i))
            ms.append(m)
        if caps:
            fs.append(tuple(range(n))[::-1])
            fs.append(tuple(range(n, 2 * n)))
            ms += [mcap or m, mcap or m]
        self.add(vs, fs, ms)

    def lathe(self, c, prof, m, n=10, caps=True, mcap=None, mtop=None):
        """Revolve [(r, z), ...] (z increasing) around local Z at c. r=0 points collapse to a pole."""
        vs, rings = [], []
        for (r, z) in prof:
            ring = []
            for i in range(n):
                a = math.pi / n + 2 * math.pi * i / n
                ring.append(len(vs))
                vs.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a), c[2] + z))
            rings.append(ring)
        fs, ms = [], []
        for k in range(len(rings) - 1):
            for i in range(n):
                j = (i + 1) % n
                fs.append((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
                ms.append(m)
        if caps:
            fs.append(tuple(rings[0])[::-1])
            ms.append(mcap or m)
            fs.append(tuple(rings[-1]))
            ms.append(mtop or mcap or m)
        self.add(vs, fs, ms)

    def ico(self, c, r, m, scale=(1, 1, 1), jitter=0.0, rng=None, sub=0, rot=(0, 0, 0), flat_bottom=None):
        """Low-poly boulder/blob. m may be {'top': .., 'side': ..} (faces with normal.z > 0.6 get 'top')."""
        rng = rng or random.Random(1)
        t = (1 + 5 ** 0.5) / 2
        vs = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
              (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
        vs = [Vector(v).normalized() for v in vs]
        fs = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
              (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
              (8, 6, 7), (9, 8, 1)]
        for _ in range(sub):
            mid = {}
            nf = []

            def mp(a, b):
                key = (min(a, b), max(a, b))
                if key not in mid:
                    vs.append(((vs[a] + vs[b]) / 2).normalized())
                    mid[key] = len(vs) - 1
                return mid[key]
            for (a, b, cc) in fs:
                ab, bc, ca = mp(a, b), mp(b, cc), mp(cc, a)
                nf += [(a, ab, ca), (b, bc, ab), (cc, ca, bc), (ab, bc, ca)]
            fs = nf
        R = _rot(rot)
        out = []
        for v in vs:
            k = 1 + (rng.uniform(-jitter, jitter) if jitter else 0)
            w = Vector((v.x * r * scale[0] * k, v.y * r * scale[1] * k, v.z * r * scale[2] * k))
            if flat_bottom is not None and w.z < -flat_bottom:
                w.z = -flat_bottom
            out.append(Vector(c) + (R @ w.to_4d()).to_3d())
        if isinstance(m, dict):
            ms = []
            for f in fs:
                nrm = (out[f[1]] - out[f[0]]).cross(out[f[2]] - out[f[0]])
                nrm = (self.T.to_3x3() @ nrm).normalized() if nrm.length > 1e-9 else Vector((0, 0, 1))
                ms.append(m.get("top") if nrm.z > 0.6 else m.get("side", m.get("top")))
        else:
            ms = m
        self.add(out, fs, ms)

    def prism(self, prof, a0, a1, m, axis="x", edge_mats=None, cap=None):
        """Extrude profile [(u, z)] from a0 to a1 along axis ('x': u = y; 'y': u = x). edge_mats[i] = side between
        point i and i+1."""
        n = len(prof)
        vs = []
        for s in (a0, a1):
            for (u, z) in prof:
                vs.append((s, u, z) if axis == "x" else (u, s, z))
        fs = [tuple(range(n))[::-1], tuple(range(n, 2 * n))]
        ms = [cap or m, cap or m]
        for i in range(n):
            j = (i + 1) % n
            fs.append((i, j, n + j, n + i))
            ms.append(edge_mats[i] if edge_mats else m)
        self.add(vs, fs, ms)

    def strip(self, rows, m, up=(0, 0, 1), uvs=None):
        """Open grid surface from rows of points (water sheets, sails). Faces oriented toward `up`."""
        upv = Vector(up)
        for i in range(len(rows) - 1):
            for j in range(len(rows[i]) - 1):
                q = [Vector(rows[i][j]), Vector(rows[i][j + 1]), Vector(rows[i + 1][j + 1]), Vector(rows[i + 1][j])]
                uv = None
                if uvs:
                    uv = [uvs[i][j], uvs[i][j + 1], uvs[i + 1][j + 1], uvs[i + 1][j]]
                nrm = (q[1] - q[0]).cross(q[3] - q[0])
                if nrm.dot(upv) < 0:
                    q = q[::-1]
                    uv = uv[::-1] if uv else None
                self.add(q, [(0, 1, 2, 3)], m, [uv] if uv else None)

    def poly(self, pts, m, uv=None):
        self.add(pts, [tuple(range(len(pts)))], m, [uv] if uv else None)

    def empty(self):
        return not self.f

    def build(self, name, parent=None, origin=None, rot=None, bevel=0.0, recalc=True, bevel_angle=40.0):
        if not self.f:
            return None
        bm = bmesh.new()
        o0 = Vector(origin) if origin is not None else Vector((0, 0, 0))
        bv = [bm.verts.new(tuple(v - o0)) for v in self.v]
        uvl = bm.loops.layers.uv.new("UVMap") if any(self.uv) else None
        for f, mi, uv in zip(self.f, self.fm, self.uv):
            idx = []
            for i in f:
                if not idx or idx[-1] != i:
                    idx.append(i)
            if len(idx) > 1 and idx[0] == idx[-1]:
                idx.pop()
            if len(set(idx)) < 3:
                continue
            try:
                face = bm.faces.new([bv[i] for i in idx])
            except ValueError:
                continue
            face.material_index = mi
            if uvl is not None and uv and len(uv) == len(idx):
                for loop, u in zip(face.loops, uv):
                    loop[uvl].uv = u
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        if bevel:
            bm.edges.ensure_lookup_table()
            edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0) > math.radians(bevel_angle)]
            if edges:
                bmesh.ops.bevel(bm, geom=edges, offset=bevel, offset_type="OFFSET", segments=1, profile=0.5,
                                affect="EDGES", clamp_overlap=True)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in self.mats:
            me.materials.append(m)
        for pl in me.polygons:
            pl.use_smooth = False
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        o.location = o0
        if rot is not None:
            o.rotation_euler = tuple(math.radians(a) for a in rot)
        if parent is not None:
            o.parent = parent
        return o


def drive(o, path, idx, expr):
    fc = o.driver_add(path, idx) if idx is not None else o.driver_add(path)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = expr
    return fc


def empty(name, parent, loc=(0, 0, 0), rot=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.empty_display_size = 0.3
    e.location = loc
    e.rotation_euler = tuple(math.radians(a) for a in rot)
    e.parent = parent
    return e


def nm(base):
    _CNT[0] += 1
    return f"{base}_{_CNT[0]}"


# ------------------------------------------------------------------ shared building blocks
def wall(mb, axis, u0, u1, c, t, z0, z1, m, holes=()):
    """Slab with real rectangular openings. axis 'x': wall runs along x at y=c (thickness t along y);
    'y': along y at x=c. holes: [(ua, ub, za, zb)] in the wall's u/z coordinates."""
    hs = [(max(u0, a), min(u1, b), max(z0, za), min(z1, zb)) for (a, b, za, zb) in holes]
    us = sorted({u0, u1} | {h[0] for h in hs} | {h[1] for h in hs})
    zs = sorted({z0, z1} | {h[2] for h in hs} | {h[3] for h in hs})
    for j in range(len(zs) - 1):
        za, zb = zs[j], zs[j + 1]
        run = None
        for i in range(len(us) - 1):
            ua, ub = us[i], us[i + 1]
            um, zm = (ua + ub) / 2, (za + zb) / 2
            solid = not any(h[0] < um < h[1] and h[2] < zm < h[3] for h in hs)
            if solid:
                run = (run[0], ub) if run else (ua, ub)
            if (not solid or i == len(us) - 2) and run:
                a, b = run
                if axis == "x":
                    mb.box2((a, c - t / 2, za), (b, c + t / 2, zb), m)
                else:
                    mb.box2((c - t / 2, a, za), (c + t / 2, b, zb), m)
                run = None


def window(mb, axis, ua, ub, za, zb, face, out, mframe, mglass=None, cross=True, sill=True, fw=0.07):
    """Frame (+ optional glass/cross mullions/sill) for an opening in a wall whose outer face lies at `face`
    (y or x), `out` = -1/+1 direction pointing outside."""
    d = 0.05

    def B(u0, u1, z0, z1, depth0, depth1, m):
        if axis == "x":
            mb.box2((u0, face + out * depth0, z0), (u1, face + out * depth1, z1), m)
        else:
            mb.box2((face + out * depth0, u0, z0), (face + out * depth1, u1, z1), m)
    B(ua - fw, ub + fw, zb, zb + fw, -0.02, d, mframe)
    B(ua - fw, ub + fw, za - fw, za, -0.02, d, mframe)
    B(ua - fw, ua, za, zb, -0.02, d, mframe)
    B(ub, ub + fw, za, zb, -0.02, d, mframe)
    if sill:
        B(ua - fw - 0.04, ub + fw + 0.04, za - fw - 0.05, za - fw + 0.01, -0.02, d + 0.08, mframe)
    if mglass is not None:
        B(ua, ub, za, zb, -0.12, -0.1, mglass)
        if cross:
            um, zm = (ua + ub) / 2, (za + zb) / 2
            B(um - 0.025, um + 0.025, za, zb, -0.1, -0.06, mframe)
            B(ua, ub, zm - 0.025, zm + 0.025, -0.1, -0.06, mframe)


def gable_roof(R, name, w, d, z_eave, rise, m, overhang=0.3, thick=0.12, loc=(0, 0, 0), yaw=0.0, mgable=None,
               wall_t=0.0):
    """Gable roof, ridge along local X (shingle rows follow the ridge), built as its own object so the texture
    turns with `yaw`. Gable triangles (mgable) fill the ends between the walls."""
    mb = MB()
    hw = d / 2 + overhang
    run = d / 2
    slope = rise / run
    zl = z_eave - overhang * slope
    for s in (-1, 1):
        # outer eave edge (y = s*hw, z = zl) to ridge (y=0, z=z_eave+rise), thickness measured vertically
        x0, x1 = -w / 2 - overhang, w / 2 + overhang
        c8 = []
        for i in range(8):
            x = x1 if i & 1 else x0
            atr = (i >> 1) & 1  # 0 = eave, 1 = ridge
            y = s * hw if atr == 0 else -s * 0.0
            z = (zl if atr == 0 else z_eave + rise) + (thick if (i >> 2) & 1 else 0)
            c8.append((x, y, z))
        mb.hexa(c8, {"side": T("planks_dark"), "top": m, "bottom": T("planks_dark")})
    if mgable is not None:
        mb.prism([(-d / 2 + wall_t * 0, z_eave), (d / 2, z_eave), (0, z_eave + rise)], -w / 2, w / 2, mgable)
    o = mb.build(name, R, origin=loc)
    o.rotation_euler[2] = math.radians(yaw)
    return o


def smoke(R, name, base, n=4, size=0.22, rise=1.6, speed=0.012, color="#e4e4e4"):
    """Puffs rising from base, growing and wrapping (driver-only animation)."""
    m = X.mat(color, name=f"kit_smoke_{color}", shadow=0.85)
    for i in range(n):
        mb = MB()
        mb.box((0, 0, 0), (size, size, size), m, rot=(20 * i, 35, 10 * i))
        o = mb.build(nm(name), R, origin=(0, 0, 0))
        ph = i / n
        drive(o, "location", 0, f"{base[0]}+0.12*sin(frame*0.05+{i * 1.7:.2f})")
        drive(o, "location", 1, f"{base[1]}")
        drive(o, "location", 2, f"{base[2]}+{rise}*fmod(frame*{speed}+{ph:.3f},1.0)")
        for k in range(3):
            drive(o, "scale", k, f"0.5+1.1*fmod(frame*{speed}+{ph:.3f},1.0)")
        drive(o, "rotation_euler", 2, f"frame*0.02+{i}")


def flames(R, name, base, s=1.0, light=True):
    mats = [X.mat("flame", name="kit_flame", emit=True, anim=(0.0, 0.6)),
            X.mat("#ffe07a", name="kit_flame_core", emit=True)]
    for i, (h, w, mi, dx, dy) in enumerate([(0.55, 0.32, 0, 0, 0), (0.4, 0.22, 0, 0.09, -0.05), (0.38, 0.2, 0, -0.08, 0.06),
                                            (0.28, 0.14, 1, 0, 0)]):
        mb = MB()
        mb.cyl((0, 0, h * s / 2), w * s / 2, h * s, mats[mi], n=4, r2=0.02 * s)
        o = mb.build(nm(name), R, origin=(0, 0, 0))
        o.location = (base[0] + dx * s, base[1] + dy * s, base[2])
        drive(o, "scale", 2, f"1+0.22*sin(frame*0.5+{i * 2.1:.2f})")
        drive(o, "scale", 0, f"1+0.1*sin(frame*0.37+{i:.2f})")
        drive(o, "rotation_euler", 2, f"frame*0.04+{i * 0.8:.2f}")
    if light:
        L = bpy.data.objects.new(nm(name + "_light"), bpy.data.lights.new(nm("kitfire"), "POINT"))
        bpy.context.scene.collection.objects.link(L)
        L.data.energy = 40 * s
        L.data.color = (1.0, 0.6, 0.25)
        L.data.shadow_soft_size = 0.2
        L.location = (base[0], base[1], base[2] + 0.4 * s)
        L.parent = R
        drive(L.data, "energy", None, f"{40 * s}*(1+0.15*sin(frame*0.7))")


def water(R, name, x0, x1, y0, y1, z, tex="water", speed=(0.05, 0.02), amp=0.015):
    o = X.water_plane(nm(name), ((x0 + x1) / 2, (y0 + y1) / 2, z), (abs(x1 - x0), abs(y1 - y0)), tex=tex,
                      subdiv=12, amp=amp, speed=speed, parent=R)
    return o


def stone_ring(mb, c, r, n, m, rng, size=0.16):
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.1, 0.1)
        mb.ico((c[0] + r * math.cos(a), c[1] + r * math.sin(a), c[2] + size * 0.45), size, m,
               scale=(1.2, 1.0, 0.75), jitter=0.2, rng=rng, flat_bottom=size * 0.5)


def wheel(mb, r, w, m, n=12, spokes=6, rim=0.08):
    """Spoked wheel in the local XZ plane (axle along Y), centred at the current transform origin."""
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        c8 = []
        for k in range(8):
            a = a1 if k & 1 else a0
            y = (w / 2) * ((((k >> 1) & 1) * 2) - 1)
            rr = r if (k >> 2) & 1 else r - rim
            c8.append((rr * math.cos(a), y, rr * math.sin(a)))
        mb.hexa(c8, m)
    for i in range(spokes):
        a = 180.0 * i / spokes
        mb.box((0, 0, 0), (2 * (r - rim / 2), w * 0.45, 0.05), m, rot=(0, a, 0))
    mb.cyl((0, 0, 0), r * 0.18, w * 1.3, T("iron"), n=8, rot=(90, 0, 0))


# ------------------------------------------------------------------ registry
def kit(name, desc, params, size):
    def deco(fn):
        KITS[name] = {"fn": fn, "desc": desc, "params": params, "size": size}
        return fn
    return deco


ALIASES = {
    "intact_dam": ("dam", {"state": "ancient"}), "ancient_dam": ("dam", {"state": "ancient"}),
    "broken_dam": ("dam", {"state": "broken"}), "modern_dam": ("dam", {"state": "modern"}),
    "concrete_dam": ("dam", {"state": "modern"}), "spillway": ("dam", {"state": "modern"}),
    "house_mudbrick": ("mudbrick_house", {}), "mud_house": ("mudbrick_house", {}), "adobe": ("mudbrick_house", {}),
    "palm_tree": ("palm", {}), "date_palm": ("palm", {}), "mill": ("water_mill", {}), "watermill": ("water_mill", {}),
    "canoe": ("boat", {}), "log_boat": ("boat", {}), "ship": ("boat", {}), "raft": ("boat", {"sail": False}),
    "crate": ("crates", {"count": 1}), "box": ("crates", {"count": 1}), "amphora": ("pot", {"style": "amphora"}),
    "jar": ("pot", {"style": "jar"}), "vase": ("pot", {"style": "amphora"}), "signpost": ("sign", {}),
    "boulder": ("rock", {}), "rocks": ("rock", {}), "stone": ("rock", {}), "fire": ("campfire", {}),
    "bonfire": ("campfire", {}), "camp": ("workers_camp", {}), "construction_camp": ("workers_camp", {}),
    "shovel": ("tools", {"tool": "shovel"}), "pickaxe": ("tools", {"tool": "pickaxe"}),
    "hammer": ("tools", {"tool": "hammer"}), "bakery": ("house", {"style": "bakery"}),
    "cottage": ("house", {"style": "cottage"}), "shop": ("house", {"style": "bakery"}), "farm": ("barn", {}),
    "wagon": ("cart", {}), "cask": ("barrel", {}), "pier": ("dock", {}), "jetty": ("dock", {}),
    "pyramids": ("pyramid", {}), "tents": ("tent", {}), "stone_blocks": ("generic", {"mat": "stone_block"}),
}


def _resolve(kit_name):
    k = str(kit_name or "generic").strip().lower().replace(" ", "_").replace("-", "_")
    if k in KITS:
        return k, {}
    if k in ALIASES:
        return ALIASES[k]
    if k.endswith("s") and k[:-1] in KITS:
        return k[:-1], {}
    for name in KITS:  # 'old_stone_bridge' -> bridge
        if name != "generic" and name in k:
            return name, {}
    return "generic", {"noun": k}


def _bbox(root):
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    bpy.context.view_layer.update()
    for o in root.children_recursive:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def build(kit, params=None):
    """Build a kit prop; returns the root Empty KIT_<name> at the origin (front -Y, base z=0)."""
    params = dict(params or {})
    name, extra = _resolve(kit)
    for k, v in extra.items():
        params.setdefault(k, v)
    root = bpy.data.objects.new(f"KIT_{name}", None)
    bpy.context.scene.collection.objects.link(root)
    root.empty_display_size = 0.5
    root["kit"] = name
    try:
        h = KITS[name]["fn"](root, params)
    except Exception:
        traceback.print_exc()
        print(f"[abs_kit] {name} failed, generic fallback")
        for o in list(root.children_recursive):
            bpy.data.objects.remove(o, do_unlink=True)
        name = "generic"
        h = generic(root, {"mat": params.get("mat", "planks")})
    lo, hi = _bbox(root)
    if lo.x < 1e8:
        root["kit_size"] = [round(hi.x - lo.x, 3), round(hi.y - lo.y, 3), round(hi.z - lo.z, 3)]
        root["kit_height"] = float(h) if isinstance(h, (int, float)) else round(hi.z, 3)
    return root


def catalog():
    return [{"name": k, "desc": v["desc"], "params": v["params"], "size": v["size"]} for k, v in KITS.items()]


# ================================================================== DAM
def _valley(R, W, H, rock, top, seed, y0=-7.5, y1=9.0, slope=0.62, extra=0.9, floor="gravel"):
    """Rocky V-valley abutments as stepped low-poly ledges on both sides (+ river-bed strip). Returns valley
    half-width function."""
    rng = random.Random(seed)
    mb = MB()
    mr, mt = T(rock), T(top)
    lh = 0.5
    xb = max(1.6, W / 2 - H * slope)
    nl = int(math.ceil((H + extra) / lh))
    for side in (-1, 1):
        for i in range(nl):
            z0, z1 = i * lh, (i + 1) * lh
            xin = xb + z1 * slope
            xout = W / 2 + 5.4 - z1 * 0.8
            ya, yb = y0 + z1 * 0.8, y1 - z1 * 0.8
            if xout - xin < 0.8 or yb - ya < 1.0:
                break
            y = ya
            while y < yb - 0.25:
                y2 = min(yb, y + rng.uniform(0.9, 1.9))
                if yb - y2 < 0.5:
                    y2 = yb
                a = xin + rng.uniform(-0.15, 0.4)
                b = xout + rng.uniform(-0.6, 0.2)
                zt = z1 + (0.15 if rng.random() < 0.2 else 0.0)
                xa, xc = (a, b) if side > 0 else (-b, -a)
                mb.box2((xa, y, z0), (xc, y2, zt), {"top": mt, "side": mr})
                y = y2
        for k in range(5):  # fallen boulders at the foot
            yy = rng.uniform(y0 + 1, y1 - 2)
            if -4.5 < yy < 3.5:
                yy = rng.choice([-5.2, 4.8])
            mb.ico((side * (xb + rng.uniform(-0.1, 0.4)), yy, 0.18), rng.uniform(0.25, 0.45), {"top": mt, "side": mr},
                   scale=(1.2, 1.0, 0.8), jitter=0.2, rng=rng, flat_bottom=0.2)
    mb.build(nm("Valley"), R, bevel=0.035)
    # river-bed strip (jagged low-poly edge) slightly above z=0
    fb = MB()
    left, right = [], []
    yy = y0
    while yy <= y1 + 0.01:
        left.append((-xb - 0.5 - rng.uniform(0, 0.4), yy, 0.012))
        right.append((xb + 0.5 + rng.uniform(0, 0.4), yy, 0.012))
        yy += 1.5
    rows = [[l, r] for l, r in zip(left, right)]
    fb.strip(rows, T(floor))
    fb.build(nm("RiverBed"), R, recalc=False)
    return xb


def _dam_column(mb, x0, x1, n, kd, kc, ku, cw, sd, su, fs, mface, mcore, mcrest):
    for i in range(max(kd, kc, ku)):
        z0, z1 = i * CH, (i + 1) * CH
        yd = -(cw / 2 + (n - i) * sd)
        yu = cw / 2 + (n - i) * su
        if i < kd:
            mb.box2((x0, yd, z0), (x1, yd + fs, z1), mface)
        if i < kc:
            mb.box2((x0, yd + fs, z0), (x1, yu - fs, z1), {"side": mcore, "top": mcrest if i == n - 1 else mcore})
        if i < ku:
            mb.box2((x0, yu - fs, z0), (x1, yu, z1), mface)


def _block_pile(mb, c, rng, m, nx=3, ny=2, layers=2, bs=(0.66, 0.45, CH)):
    for l in range(layers):
        for i in range(nx - l):
            for j in range(ny):
                if rng.random() < 0.15 and l > 0:
                    continue
                x = c[0] + (i - (nx - l - 1) / 2) * (bs[0] + 0.03)
                y = c[1] + (j - (ny - 1) / 2) * (bs[1] + 0.03)
                mb.box((x, y, c[2] + bs[2] * (l + 0.5)), bs, m, rot=(0, 0, rng.uniform(-4, 4)))


def _sled(mb, c, yaw, load=True):
    with mb.at(c, (0, 0, yaw)):
        mw = T("planks_dark")
        for s in (-1, 1):
            mb.box((0, s * 0.32, 0.07), (1.5, 0.1, 0.14), mw)
            mb.hexa([(0.75, s * 0.32 - 0.05, 0.0), (1.0, s * 0.32 - 0.05, 0.22), (0.75, s * 0.32 + 0.05, 0.0),
                     (1.0, s * 0.32 + 0.05, 0.22), (0.75, s * 0.32 - 0.05, 0.14), (0.9, s * 0.32 - 0.05, 0.3),
                     (0.75, s * 0.32 + 0.05, 0.14), (0.9, s * 0.32 + 0.05, 0.3)], mw)
        for k in range(4):
            mb.box((-0.6 + k * 0.4, 0, 0.17), (0.12, 0.8, 0.06), T("planks"))
        if load:
            mb.box((0, 0, 0.2 + 0.25), (0.9, 0.62, 0.5), T("stone_block"))
            mb.cyl((1.25, 0.18, 0.12), 0.025, 0.7, T("rope"), n=4, rot=(0, 80, 10))
            mb.cyl((1.25, -0.18, 0.12), 0.025, 0.7, T("rope"), n=4, rot=(0, 80, -10))


def _norm_state(s):
    s = str(s or "ancient").lower()
    if any(k in s for k in ("broke", "breach", "fail", "destroy", "wash", "collapse", "ruin", "flood")):
        return "broken"
    if any(k in s for k in ("modern", "concrete", "spill", "new", "today")):
        return "modern"
    return "ancient"


@kit("dam", "Massive dam across a narrow rocky valley. state: 'ancient' = Egyptian Sadd el-Kafara style rubble core with "
            "stepped limestone block facing, crest walkway, workers' ramp, stone piles, low reservoir behind; 'broken' = the "
            "same dam with a V-shaped breach, tumbled blocks and muddy flood water rushing through (animated); 'modern' = "
            "concrete gravity dam with crest road + railings, stepped spillway channel with animated white water, intake "
            "tower and a full reservoir. Downstream face toward camera.",
     {"state": "ancient | broken | modern", "height": "crest height m (default 3.7 ancient, 4 modern)",
      "width": "valley width at the crest m (default 10)", "valley": "rocky abutments both ends (default true)",
      "water": "reservoir water (default true)", "ramp": "workers' ramp + stone piles (ancient, default true)",
      "terrain": "desert | green (abutment rock style)", "seed": "int"},
     (13, 14, 4.5))
def k_dam(R, p):
    state = _norm_state(p.get("state"))
    rng = random.Random(int(num(p, "seed", 7)))
    if state == "modern":
        return _dam_modern(R, p, rng)
    n = max(5, int(round(num(p, "height", 3.7) / CH)))
    H = n * CH
    W = max(5.0, num(p, "width", 10.0))
    cw, sd, su, fs = 1.5, 0.27, 0.21, 0.5
    valley = flag(p, "valley", True)
    green = word(p, "terrain", "desert").startswith("g")
    mface, mcore, mcrest = T("stone_block"), T("rubble"), T("gravel")
    xb = W / 2 - H * 0.62
    xe = W / 2 + 1.4 if valley else W / 2
    mb = MB()
    if state == "broken":
        g = min(W * 0.21, max(1.2, xb * 0.85))
        cwid = 0.34
        ncol = int(round(2 * g / cwid))
        cwid = 2 * g / ncol
        _dam_column(mb, -xe, -g, n, n, n, n, cw, sd, su, fs, mface, mcore, mcrest)
        _dam_column(mb, g, xe, n, n, n, n, cw, sd, su, fs, mface, mcore, mcrest)
        for i in range(ncol):
            x0 = -g + i * cwid
            xc = x0 + cwid / 2
            t = abs(xc) / g
            k = int(round(n * t ** 1.25)) + rng.choice([-1, 0, 0, 1])
            k = max(0, min(n - 1, k))
            if t < 0.22:
                k = 0
            if k == 0:
                continue
            kd = max(0, k - rng.choice([0, 1, 1, 2]))
            ku = max(0, k - rng.choice([0, 0, 1]))
            _dam_column(mb, x0, x0 + cwid, n, kd, k, ku, cw, sd, su, fs, mface, mcore, mcrest)
    else:
        _dam_column(mb, -xe, xe, n, n, n, n, cw, sd, su, fs, mface, mcore, mcrest)
    if not valley:  # finished ends
        for s in (-1, 1):
            for i in range(n):
                yd, yu = -(cw / 2 + (n - i) * sd), cw / 2 + (n - i) * su
                mb.box2((s * xe - 0.01 * s, yd, i * CH), (s * (xe + 0.02), yu, (i + 1) * CH), mface)
    mb.build(nm("DamBody"), R)

    ex = MB()  # extras: piles, ramp, debris
    if state == "ancient" and flag(p, "ramp", True):
        k = int(n * 0.72)
        zt = k * CH
        yf = -(cw / 2 + (n - k) * sd)
        x0, x1 = -0.6, min(3.6, xb + 0.4 + zt * 0.62 - 1.0)
        ya, yb = yf - 1.25, yf + 0.3
        ex.hexa([(x0, ya, 0), (x1, ya, 0), (x0, yb, 0), (x1, yb, 0), (x0, ya, 0.04), (x1, ya, zt), (x0, yb, 0.04),
                 (x1, yb, zt)], {"top": T("dirt"), "side": T("mudbrick")})
        ex.box2((x1 - 0.01, ya, 0), (x1 + 0.6, yb + 0.6, zt), {"top": T("dirt"), "side": T("mudbrick")})
        _block_pile(ex, (-2.6, -cw / 2 - n * sd - 1.6, 0), rng, mface, 3, 2, 2)
        _block_pile(ex, (-0.8, -cw / 2 - n * sd - 2.6, 0), rng, mface, 2, 1, 2)
        _sled(ex, (1.4, -cw / 2 - n * sd - 2.4, 0), -12)
        for i in range(6):  # rubble baskets / gravel heaps
            ex.ico((rng.uniform(-3.5, -1.5), rng.uniform(-6.5, -5.0), 0.1), rng.uniform(0.2, 0.35), mcore,
                   scale=(1.3, 1.1, 0.6), jitter=0.25, rng=rng, flat_bottom=0.1)
    if state == "broken":
        yd0 = -(cw / 2 + n * sd)
        for i in range(16):  # tumbled limestone blocks downstream
            yy = rng.uniform(yd0 - 5.5, yd0 + 0.2)
            spread = 0.8 + (yd0 - yy) * 0.45
            xx = rng.uniform(-spread, spread)
            if abs(xx) < 0.7 and yy > yd0 - 2.5:
                xx += 1.2 if xx >= 0 else -1.2
            ex.box((xx, yy, CH * 0.35), (0.66, 0.45, CH), mface,
                   rot=(rng.uniform(-18, 18), rng.uniform(-14, 14), rng.uniform(0, 180)))
        for i in range(5):  # blocks lying on the breach steps
            ex.box((rng.choice([-1, 1]) * rng.uniform(0.9, 1.6), rng.uniform(-1.8, -0.6), rng.uniform(0.3, 0.9)),
                   (0.6, 0.42, CH), mface, rot=(rng.uniform(-25, 25), rng.uniform(-25, 25), rng.uniform(0, 90)))
        for i in range(22):  # rubble lumps washed out of the core
            yy = rng.uniform(yd0 - 6.5, yd0 + 0.5)
            ex.ico((rng.uniform(-2.6, 2.6), yy, 0.06), rng.uniform(0.12, 0.3), mcore, scale=(1.2, 1.0, 0.7),
                   jitter=0.25, rng=rng, flat_bottom=0.08)
        ex.ico((0, yd0 - 2.8, 0.0), 2.4, T("gravel"), scale=(1.1, 1.5, 0.09), jitter=0.1, rng=rng)  # debris fan
    if not ex.empty():
        ex.build(nm("DamExtras"), R)

    if valley:
        _valley(R, W, H, "rock_grey" if green else "rock_desert", "grass_dry" if green else "sand", rng.randint(0, 999),
                floor="gravel")
    if flag(p, "water", True):
        yu0 = cw / 2 + n * su
        if state == "broken":
            water(R, "Reservoir", -W / 2 - 3, W / 2 + 3, 0.6, 7.6, 0.55, "water_mud", speed=(0.0, 0.08))
            # flood rushing through the breach toward the camera (-Y)
            fl = MB()
            yd0 = -(cw / 2 + n * sd)
            prof = [(yu0 + 1.0, 0.95, 0.54), (yu0 - 0.4, 0.9, 0.5), (0.0, 0.75, 0.42), (yd0 + 0.4, 0.8, 0.32),
                    (yd0 - 0.6, 1.0, 0.2), (yd0 - 2.0, 1.5, 0.12), (yd0 - 4.0, 2.2, 0.08), (-9.5, 2.8, 0.06)]
            rows = [[(-hw + 2 * hw * j / 4, y, z + 0.04 * math.sin(math.pi * j / 4)) for j in range(5)] for (y, hw, z) in prof]
            fl.strip(rows, X.mat("water_mud", name="kit_flood", anim=(0.0, 0.9), shadow=0.8))
            fo = MB()
            frows = [[(-hw * 0.7 + 1.4 * hw * j / 2, y, z + 0.02) for j in range(3)] for (y, hw, z) in prof[1:5]]
            fo.strip(frows, X.mat("whitewater_mud", name="kit_flood_foam", anim=(0.0, 1.4), alpha=False, shadow=0.85))
            fl.build(nm("Flood"), R, recalc=False)
            fo.build(nm("FloodFoam"), R, recalc=False)
            for i in range(6):
                bb = MB()
                bb.ico((0, 0, 0), rng.uniform(0.08, 0.14), X.mat("#efe6d2", name="kit_foam_bit", shadow=0.85), jitter=0.2,
                       rng=rng)
                o = bb.build(nm("FoamBit"), R, origin=(0, 0, 0))
                y = rng.uniform(yd0 - 3.0, yd0 + 0.5)
                drive(o, "location", 0, f"{rng.uniform(-0.6, 0.6):.2f}")
                drive(o, "location", 1, f"{y:.2f}-fmod(frame*0.03+{i * 0.37:.2f},1.0)*2.0")
                drive(o, "location", 2, f"0.28+0.05*sin(frame*0.3+{i})")
        else:
            water(R, "Reservoir", -W / 2 - 3, W / 2 + 3, 0.6, 7.6, H * 0.33, "water_nile")
        bank = MB()
        bank.hexa([(-W / 2 - 3, 6.9, 0), (W / 2 + 3, 6.9, 0), (-W / 2 - 3, 9.0, 0), (W / 2 + 3, 9.0, 0),
                   (-W / 2 - 3, 6.9, 0.05), (W / 2 + 3, 6.9, 0.05), (-W / 2 - 3, 9.0, H * 0.45), (W / 2 + 3, 9.0, H * 0.45)],
                  {"top": T("grass_dry" if green else "sand"), "side": T("rock_grey" if green else "rock_desert")})
        bank.build(nm("FarBank"), R)
    return H


def _dam_modern(R, p, rng):
    H = max(2.5, num(p, "height", 4.0))
    W = max(6.0, num(p, "width", 11.0))
    cw, sl, hv = 1.7, 0.78, 0.7
    ws = 2.4
    ns = max(4, int(round((H - 0.85) / CH)))
    Hs = ns * CH
    tr = sl * CH
    valley = flag(p, "valley", True)
    xe = W / 2 + 1.4 if valley else W / 2
    mc, mroad, mcd, mrail = T("concrete_panel"), T("asphalt"), T("concrete"), T("metal")
    mb = MB()
    prof = [(cw / 2, 0), (cw / 2, H), (-cw / 2, H), (-cw / 2, H - hv), (-cw / 2 - sl * (H - hv), 0)]
    em = [mc, mroad, mc, mc, mc]
    xw = ws / 2 + 0.3
    mb.prism(prof, -xe, -xw, mc, "x", em, cap=mcd)
    mb.prism(prof, xw, xe, mc, "x", em, cap=mcd)
    # stepped spillway body
    y_top = -cw / 2 + 0.35
    for i in range(ns):
        y_i = y_top - (ns - 1 - i) * tr
        mb.box2((-ws / 2 - 0.01, y_i, i * CH), (ws / 2 + 0.01, cw / 2, (i + 1) * CH), mcd)
    y0 = y_top - (ns - 1) * tr
    LB = 2.4
    # training walls (hold the road bridge, run down the chute and along the stilling basin)
    wp = [(cw / 2 + 0.15, 0), (cw / 2 + 0.15, H), (-cw / 2, H), (y0 - 0.05, CH + 0.75), (y0 - LB, CH + 0.75), (y0 - LB, 0)]
    mb.prism(wp, -xw, -ws / 2, mc, "x", cap=mcd)
    mb.prism(wp, ws / 2, xw, mc, "x", cap=mcd)
    mb.box2((-ws / 2, -cw / 2, H - 0.32), (ws / 2, cw / 2, H), {"side": mcd, "top": mroad})   # road bridge deck
    mb.box2((-ws / 2, y0 - LB, -0.05), (ws / 2, y0, 0.05), mcd)                             # basin floor
    mb.box2((-ws / 2, y0 - LB, 0.0), (ws / 2, y0 - LB + 0.3, 0.42), mcd)                     # end sill
    for s in (-1, 1):  # chute dentates
        mb.box2((s * 0.6 - 0.15, y0 - 1.2, 0.0), (s * 0.6 + 0.15, y0 - 0.9, 0.3), mcd)
    # crest railings + lamp posts
    xr = (W / 2 - H * 0.62 + H * 0.62) if valley else xe
    for yy in (-cw / 2 + 0.05, cw / 2 - 0.05):
        x = -xr
        while x <= xr + 1e-6:
            mb.box((x, yy, H + 0.3), (0.06, 0.06, 0.6), mrail)
            x += 0.9
        mb.box2((-xr, yy - 0.03, H + 0.56), (xr, yy + 0.03, H + 0.62), mrail)
        mb.box2((-xr, yy - 0.02, H + 0.3), (xr, yy + 0.02, H + 0.34), mrail)
    for x in (-xr * 0.55, xr * 0.55):
        mb.box((x, -cw / 2 + 0.05, H + 0.9), (0.08, 0.08, 1.8), T("iron"))
        mb.box((x, -cw / 2 + 0.25, H + 1.78), (0.12, 0.45, 0.08), T("iron"))
        mb.box((x, -cw / 2 + 0.42, H + 1.72), (0.12, 0.14, 0.05), X.mat("#fff4c2", name="kit_lamp", emit=True))
    # intake tower + footbridge
    tx, ty = -W * 0.26, cw / 2 + 1.5
    mb.box2((tx - 0.55, ty - 0.55, 0), (tx + 0.55, ty + 0.55, H + 0.2), mc)
    hut = T("plaster_white")
    mb.box2((tx - 0.65, ty - 0.65, H + 0.2), (tx + 0.65, ty + 0.65, H + 1.05), hut)
    for s in (-1, 1):
        mb.box2((tx - 0.22, ty + s * 0.65 - 0.03, H + 0.45), (tx + 0.22, ty + s * 0.65 + 0.03, H + 0.8), DARK())
    mb.box2((tx - 0.75, ty - 0.75, H + 1.05), (tx + 0.75, ty + 0.75, H + 1.15), mcd)
    mb.cyl((tx, ty, H + 1.4), 0.75 * 1.2, 0.5, T("roof_red"), n=4, r2=0.0, a0=math.pi / 4)
    mb.box2((tx - 0.35, cw / 2 - 0.1, H - 0.18), (tx + 0.35, ty - 0.55, H), mcd)
    for s in (-1, 1):
        mb.box2((tx + s * 0.35 - 0.03, cw / 2, H + 0.56), (tx + s * 0.35 + 0.03, ty - 0.55, H + 0.62), mrail)
        for yy in (cw / 2 + 0.2, (cw / 2 + ty - 0.55) / 2, ty - 0.6):
            mb.box((tx + s * 0.35, yy, H + 0.3), (0.05, 0.05, 0.6), mrail)
    mb.build(nm("DamConcrete"), R)

    # --- water
    Hw = Hs + 0.3
    if flag(p, "water", True):
        if valley:
            green = not word(p, "terrain", "green").startswith("d")
            xb = _valley(R, W, H, "rock_grey" if green else "rock_desert", "grass" if green else "sand",
                         rng.randint(0, 999), floor="gravel_grey" if green else "gravel")
        water(R, "Reservoir", -W / 2 - 3, W / 2 + 3, cw / 2 - 0.1, 7.6, Hw, "water_deep", speed=(0.03, -0.02))
        d = 0.07
        pts = [(cw / 2 + 0.8, Hw - 0.01), (cw / 2 - 0.05, Hw - 0.02), (y_top, Hs + d + 0.05)]
        for i in range(ns - 1, -1, -1):
            y_i = y_top - (ns - 1 - i) * tr
            pts.append((y_i - d, (i + 1) * CH + d))
            pts.append((y_i - d, i * CH + d + (0.3 if i == 0 else 0.0)))
            if i > 0:
                pts.append((y_i - tr + 0.0, i * CH + d))
        pts.append((y0 - LB + 0.3, 0.42))
        pts.append((y0 - LB - 0.4, 0.2))
        rows = [[(-ws / 2 + 0.01, y, z), (0.0, y, z + 0.02), (ws / 2 - 0.01, y, z)] for (y, z) in pts]
        sh = MB()
        sh.strip(rows, X.mat("whitewater", name="kit_spill", anim=(0.0, 1.2, 1.2), shadow=0.85), up=(0, -0.5, 0.85))
        sh.build(nm("SpillWater"), R, recalc=False)
        xr2 = (xb + 0.4) if valley else W / 2
        water(R, "River", -xr2, xr2, -9.5, y0 - LB - 0.3, 0.18, "water", speed=(0.0, 0.35))
        for i in range(7):
            bb = MB()
            bb.ico((0, 0, 0), rng.uniform(0.1, 0.16), X.mat("#ffffff", name="kit_foam_w", shadow=0.9), jitter=0.2, rng=rng)
            o = bb.build(nm("Foam"), R, origin=(0, 0, 0))
            drive(o, "location", 0, f"{rng.uniform(-ws / 2 + 0.3, ws / 2 - 0.3):.2f}")
            drive(o, "location", 1, f"{y0 - 0.3:.2f}-fmod(frame*0.02+{i * 0.29:.2f},1.0)*{LB + 1.5:.2f}")
            drive(o, "location", 2, f"0.42+0.06*sin(frame*0.35+{i})")
    elif valley:
        _valley(R, W, H, "rock_grey", "grass", rng.randint(0, 999))
    return H


# ================================================================== EGYPT
@kit("pyramid", "Egyptian limestone pyramid: 'giza' (fine stepped courses, gold capstone), 'stepped' (Djoser-style "
                "6 big tiers) or 'smooth' (white casing). Optional unfinished state with a construction ramp.",
     {"style": "giza | stepped | smooth", "base": "base width m (default 6)", "height": "m (default ~0.68*base)",
      "capstone": "gold tip (default true for giza/smooth)", "built": "0..1 fraction finished (default 1)"},
     (6, 6, 4))
def k_pyramid(R, p):
    style = word(p, "style", "giza")
    B = max(1.0, num(p, "base", 6.0))
    H = num(p, "height", B * 0.68)
    built = max(0.15, min(1.0, num(p, "built", 1.0)))
    ms = T("stone_block")
    mb = MB()
    top = H
    if style.startswith("smooth"):
        mcas = X.mat("#ede1c4", name="kit_casing")
        hb = B / 2
        vs = [(-hb, -hb, 0), (hb, -hb, 0), (hb, hb, 0), (-hb, hb, 0), (0, 0, H)]
        mb.add(vs, [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (3, 2, 1, 0)], mcas)
    else:
        tiers = 6 if style.startswith("step") else max(4, int(round(H / CH)))
        th = max(CH, round(H / tiers / CH) * CH)
        nb = int(math.ceil(tiers * built))
        for i in range(nb):
            w = B * (1 - i / tiers) if not style.startswith("step") else B * (1 - 0.13 * i)
            mb.box((0, 0, th * (i + 0.5)), (w, w, th), ms)
        top = th * nb
        H = th * tiers
        if built < 1:
            k = nb
            w = B * (1 - k / tiers)
            mb.hexa([(-w / 2 - 0.05, -B / 2 - 3.5, 0), (-w / 2 + 1.0, -B / 2 - 3.5, 0), (-w / 2 - 0.05, -w / 2 + 0.2, 0),
                     (-w / 2 + 1.0, -w / 2 + 0.2, 0), (-w / 2 - 0.05, -B / 2 - 3.5, 0.03), (-w / 2 + 1.0, -B / 2 - 3.5, 0.03),
                     (-w / 2 - 0.05, -w / 2 + 0.2, top), (-w / 2 + 1.0, -w / 2 + 0.2, top)],
                    {"top": T("dirt"), "side": T("mudbrick")})
            rng = random.Random(3)
            _block_pile(mb, (B / 2 - 0.2, -B / 2 - 1.2, 0), rng, ms, 3, 2, 2)
    if flag(p, "capstone", style != "stepped") and built >= 1:
        cap = th if not style.startswith("smooth") else H * 0.12
        cb = B * cap / H * (1.0 if style.startswith("smooth") else 1.6)
        z0 = top - (cap if style.startswith("smooth") else 0)
        mb.add([(-cb / 2, -cb / 2, z0), (cb / 2, -cb / 2, z0), (cb / 2, cb / 2, z0), (-cb / 2, cb / 2, z0),
                (0, 0, z0 + cap * 1.4)], [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (3, 2, 1, 0)], T("gold"))
    mb.build(nm("Pyramid"), R)
    return H


@kit("mudbrick_house", "Egyptian / desert mud-brick house: thick walls with real door and small windows, flat roof "
                       "with parapet, protruding palm-log beams, palm-frond awning on poles, outside stair to the roof, jars.",
     {"plaster": "smooth mud plaster instead of bare bricks (default false)", "width": "m (default 3.4)",
      "depth": "m (default 2.8)", "awning": "default true", "stairs": "default true"},
     (5, 4.5, 2.9))
def k_mudbrick_house(R, p):
    W, D, H, t = num(p, "width", 3.4), num(p, "depth", 2.8), 2.45, 0.3
    mw = T("mud_plaster" if flag(p, "plaster", False) else "mudbrick")
    mpl, mwood, mdk = T("mud_plaster"), T("planks_dark"), T("log")
    mb = MB()
    door = (-W / 2 + 0.55, -W / 2 + 1.35, 0, 1.75)
    win = (0.35, 0.95, 1.05, 1.5)
    wall(mb, "x", -W / 2, W / 2, -D / 2 + t / 2, t, 0, H, mw, [door, win])
    wall(mb, "x", -W / 2, W / 2, D / 2 - t / 2, t, 0, H, mw, [(-0.3, 0.2, 1.2, 1.55)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, -W / 2 + t / 2, t, 0, H, mw, [(-0.25, 0.2, 1.2, 1.55)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, W / 2 - t / 2, t, 0, H, mw, [(-0.25, 0.25, 1.2, 1.55)])
    mb.box2((-W / 2 + t + 0.01, -D / 2 + t + 0.01, 0.01), (W / 2 - t - 0.01, D / 2 - t - 0.01, H - 0.01), DARK())
    # roof slab + parapet
    mb.box2((-W / 2 - 0.06, -D / 2 - 0.06, H), (W / 2 + 0.06, D / 2 + 0.06, H + 0.16), mpl)
    for (a, b) in [((-W / 2 - 0.06, -D / 2 - 0.06), (W / 2 + 0.06, -D / 2 + 0.12)), ((-W / 2 - 0.06, D / 2 - 0.12), (W / 2 + 0.06, D / 2 + 0.06)),
                   ((-W / 2 - 0.06, -D / 2 + 0.12), (-W / 2 + 0.12, D / 2 - 0.12)), ((W / 2 - 0.12, -D / 2 + 0.12), (W / 2 + 0.06, D / 2 - 0.12))]:
        mb.box2((a[0], a[1], H + 0.16), (b[0], b[1], H + 0.48), mpl)
    for i in range(5):  # palm-log beam ends
        mb.cyl((-W / 2 + 0.4 + i * (W - 0.8) / 4, -D / 2 - 0.08, H - 0.12), 0.07, 0.3, mdk, n=6, rot=(90, 0, 0))
    # door + window details
    mb.box2((door[0] + 0.04, -D / 2 + t * 0.55, 0.02), (door[1] - 0.04, -D / 2 + t * 0.7, door[3]), mwood)
    mb.box2((door[0] - 0.1, -D / 2 - 0.06, door[3]), (door[1] + 0.1, -D / 2 + 0.05, door[3] + 0.14), mdk)
    for k in range(3):
        u = win[0] + (k + 1) * (win[1] - win[0]) / 4
        mb.box2((u - 0.02, -D / 2 + 0.1, win[2]), (u + 0.02, -D / 2 + 0.16, win[3]), mwood)
    mb.box2((win[0] - 0.06, -D / 2 - 0.05, win[2] - 0.08), (win[1] + 0.06, -D / 2 + 0.04, win[2]), mpl)
    # awning on poles
    if flag(p, "awning", True):
        ax0, ax1, ad = -W / 2 + 0.1, 0.25, 1.15
        for x in (ax0 + 0.08, ax1 - 0.08):
            mb.cyl((x, -D / 2 - ad + 0.08, 0.95), 0.045, 1.9, mdk, n=6)
        mb.box2((ax0, -D / 2 - ad + 0.03, 1.86), (ax1, -D / 2 - ad + 0.13, 1.94), mdk)
        mb.hexa([(ax0 - 0.1, -D / 2 - ad - 0.12, 1.9), (ax1 + 0.1, -D / 2 - ad - 0.12, 1.9), (ax0 - 0.1, -D / 2 + 0.02, 2.08),
                 (ax1 + 0.1, -D / 2 + 0.02, 2.08), (ax0 - 0.1, -D / 2 - ad - 0.12, 1.98), (ax1 + 0.1, -D / 2 - ad - 0.12, 1.98),
                 (ax0 - 0.1, -D / 2 + 0.02, 2.16), (ax1 + 0.1, -D / 2 + 0.02, 2.16)], {"top": T("thatch"), "side": T("hay")})
    if flag(p, "stairs", True):
        steps = 7
        for i in range(steps):
            h = (i + 1) * (H + 0.16) / steps
            y0 = D / 2 - 0.1 - (i + 1) * (D - 0.2) / steps
            mb.box2((W / 2, y0, 0), (W / 2 + 0.6, y0 + (D - 0.2) / steps, h), mw)
    mb.build(nm("MudHouse"), R)
    ex = MB()
    rng = random.Random(5)
    for i, (x, y) in enumerate([(door[1] + 0.25, -D / 2 - 0.35), (door[1] + 0.6, -D / 2 - 0.3)]):
        _pot_shape(ex, (x, y, 0), "amphora" if i == 0 else "jar", 0.8 + 0.2 * rng.random())
    ex.build(nm("MudHouseJars"), R)
    return H + 0.48


def _palm_into(R, base, h, lean, yaw, seed, name="Palm"):
    rng = random.Random(seed)
    mb = MB()
    mt = T("bark_palm")
    segs = 8
    pts = []
    for i in range(segs + 1):
        t = i / segs
        pts.append(Vector((lean * h * t * t, 0, h * t)))
    with mb.at(base, (0, 0, yaw)):
        for i in range(segs):
            a, b = pts[i], pts[i + 1]
            d = b - a
            tilt = math.degrees(math.atan2(d.x, d.z))
            r0 = 0.17 - 0.05 * i / segs
            mb.cyl(((a + b) / 2).to_tuple(), r0 + 0.025, d.length + 0.02, mt, n=7, r2=r0 - 0.02, rot=(0, tilt, 0))
        top = pts[-1]
        mb.ico(top.to_tuple(), 0.2, T("leaves_solid"), scale=(1, 1, 0.7), jitter=0.15, rng=rng)
        for k in range(4):
            a = k * 2.1 + 0.4
            mb.ico((top.x + 0.17 * math.cos(a), 0.17 * math.sin(a), top.z - 0.16), 0.09, X.mat("#6b4a2a", name="kit_coconut"),
                   rng=rng)
    mb.build(nm(name + "Trunk"), R)
    fr = MB()
    mfr = X.mat("palm_frond", uv=True, alpha=True, shadow=0.7)
    nf = 9
    with fr.at(base, (0, 0, yaw)):
        top = pts[-1]
        for k in range(nf):
            az = 2 * math.pi * k / nf + rng.uniform(-0.15, 0.15)
            up = 0.55 if k % 2 else 0.25
            L = rng.uniform(1.5, 1.9)
            dvec = Vector((math.cos(az), math.sin(az), 0))
            side = Vector((-math.sin(az), math.cos(az), 0))
            rows, uvs = [], []
            for i in range(6):
                t = i / 5
                c = top + dvec * (L * t) + Vector((0, 0, up * t - (up + 0.9) * t * t + 0.05))
                w = 0.36 * math.sin(math.pi * min(1.0, 0.15 + t * 0.95)) ** 0.6 + 0.04
                fold = Vector((0, 0, 0.07 * w / 0.36))
                rows.append([(c - side * w).to_tuple(), (c + fold).to_tuple(), (c + side * w).to_tuple()])
                uvs.append([(0.0, t), (0.5, t), (1.0, t)])
            fr.strip(rows, mfr, up=(0, 0, 1), uvs=uvs)
    fo = fr.build(nm(name + "Fronds"), R, recalc=False)
    if fo is not None:
        fo.location = (0, 0, 0)
    return fo


@kit("palm", "Date palm: curved ringed trunk, drooping leaf-blade crown (pixel fronds), coconuts/dates. Fronds sway.",
     {"height": "trunk height m (default 4.2)", "lean": "trunk curve 0..0.4 (default 0.18)", "count": "1-3 palms clump"},
     (3.6, 3.6, 5))
def k_palm(R, p):
    h = num(p, "height", 4.2)
    lean = num(p, "lean", 0.18)
    cnt = max(1, min(3, int(num(p, "count", 1))))
    spots = [((0, 0, 0), 0, h), ((1.1, 0.7, 0), 140, h * 0.78), ((-0.9, 0.9, 0), 250, h * 0.66)]
    for i in range(cnt):
        loc, yaw, hh = spots[i]
        fo = _palm_into(R, loc, hh, lean, yaw, 11 + i)
        if fo is not None:  # gentle sway of the crown
            drive(fo, "rotation_euler", 2, f"0.03*sin(frame*0.06+{i})")
    return h + 0.4


@kit("workers_camp", "Ancient builders' camp: canvas tent, stacked limestone blocks, a wooden sled hauling a block "
                     "with ropes, rope coil, water jars, tools on the ground.",
     {"seed": "int"}, (6, 5, 2))
def k_workers_camp(R, p):
    rng = random.Random(int(num(p, "seed", 4)))
    k_tent(empty(nm("CampTent"), R, (-1.6, 1.0, 0), (0, 0, 12)), {"color": "canvas"})
    mb = MB()
    _block_pile(mb, (1.3, 1.2, 0), rng, T("stone_block"), 3, 2, 3)
    _sled(mb, (0.9, -1.0, 0), 8)
    mb.cyl((2.7, -0.6, 0.06), 0.28, 0.12, T("rope"), n=10, r2=0.22)
    mb.cyl((2.7, -0.6, 0.15), 0.2, 0.08, T("rope"), n=10, r2=0.16)
    _pot_shape(mb, (-0.3, -0.9, 0), "amphora", 0.9)
    _pot_shape(mb, (-0.05, -1.15, 0), "jar", 0.8)
    mb.build(nm("Camp"), R)
    k_tools(empty(nm("CampTools"), R, (-1.4, -1.4, 0), (0, 0, -10)), {"tool": "all", "lean": False})
    return 2.0


# ================================================================== WATER / RIVER LIFE
@kit("water_mill", "Water mill: stone base, timber+plaster mill house with gable roof, door/window, an overshot "
                   "paddle wheel that ROTATES, wooden flume on posts with flowing water spilling onto the wheel, tail-race "
                   "stream.", {"roof": "roof_red | thatch | roof_grey", "speed": "wheel speed (default 1)"},
     (5.5, 7, 4))
def k_water_mill(R, p):
    W, D = 3.0, 2.6
    mb = MB()
    mst, mwl, mwd = T("stone_brick"), T("plaster"), T("planks_dark")
    mb.box2((-W / 2 - 0.1, -D / 2 - 0.1, 0), (W / 2 + 0.1, D / 2 + 0.1, 0.9), mst)
    t = 0.2
    door, win = (-0.9, -0.2, 0.9, 2.2), (0.3, 0.9, 1.45, 1.95)
    wall(mb, "x", -W / 2, W / 2, -D / 2 + t / 2, t, 0.9, 2.6, mwl, [door, win])
    wall(mb, "x", -W / 2, W / 2, D / 2 - t / 2, t, 0.9, 2.6, mwl, [(-0.3, 0.3, 1.45, 1.95)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, -W / 2 + t / 2, t, 0.9, 2.6, mwl, [(-0.3, 0.3, 1.45, 1.95)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, W / 2 - t / 2, t, 0.9, 2.6, mwl, [])
    mb.box2((-W / 2 + t, -D / 2 + t, 0.9), (W / 2 - t, D / 2 - t, 2.59), DARK())
    for x in (-W / 2, W / 2):  # timber corner posts + beams
        for y in (-D / 2, D / 2):
            mb.box((x, y, 1.75), (0.16, 0.16, 1.7), mwd)
    mb.box2((-W / 2 - 0.08, -D / 2 - 0.08, 2.5), (W / 2 + 0.08, -D / 2 + 0.06, 2.62), mwd)
    mb.box2((-W / 2 - 0.08, -D / 2 - 0.08, 0.9), (W / 2 + 0.08, -D / 2 + 0.06, 1.0), mwd)
    mb.box2((door[0] + 0.05, -D / 2 + 0.06, 0.92), (door[1] - 0.05, -D / 2 + 0.12, door[3]), T("planks"))
    window(mb, "x", win[0], win[1], win[2], win[3], -D / 2, -1, mwd, T("glass"))
    for i in range(3):  # entry steps
        mb.box2((door[0] - 0.1, -D / 2 - 0.35 - i * 0.3, 0), (door[1] + 0.1, -D / 2 - 0.05 - i * 0.3, 0.9 - i * 0.3), mst)
    mb.box2((W / 2 - 0.2, -0.2, 1.05), (W / 2 + 0.25, 0.2, 1.45), mst)  # axle bearing block
    mb.build(nm("MillHouse"), R)
    gable_roof(R, nm("MillRoof"), W, D, 2.6, 1.1, T(word(p, "roof", "roof_red")), overhang=0.3, mgable=mwl)
    # wheel (rotates about X)
    wr, wx = 1.15, W / 2 + 0.55
    wz = 1.3
    wb = MB()
    mwh = T("planks")
    with wb.at((0, 0, 0), (0, 0, 90)):
        wheel(wb, wr, 0.5, mwh, n=16, spokes=4, rim=0.1)
        for i in range(16):
            a = 360.0 * (i + 0.5) / 16
            with wb.at((0, 0, 0), (0, -a, 0)):
                wb.box((wr - 0.12, 0, 0), (0.32, 0.5, 0.04), T("planks_dark"))
    for s in (-1, 1):
        wb.box((s * 0.25, 0, 0), (0.05, 2 * wr - 0.15, 0.08), mwh)
    wo = wb.build(nm("MillWheel"), R, origin=(0, 0, 0))
    wo.location = (wx, 0, wz)
    drive(wo, "rotation_euler", 0, f"frame*{0.035 * num(p, 'speed', 1.0):.4f}")
    ax = MB()
    ax.cyl((W / 2 + 0.3, 0, wz), 0.07, 1.0, T("iron"), n=8, rot=(0, 90, 0))
    ax.build(nm("MillAxle"), R)
    # flume on posts + water
    fl = MB()
    fz = wz + wr + 0.25
    y0, y1 = 0.15, 5.0
    fl.box2((wx - 0.3, y0, fz - 0.05), (wx + 0.3, y1, fz), mwd)
    for s in (-1, 1):
        fl.box2((wx + s * 0.3 - 0.04, y0, fz - 0.05), (wx + s * 0.3 + 0.04, y1, fz + 0.25), mwd)
    for y in (1.8, 3.4, 4.8):
        for s in (-1, 1):
            fl.box((wx + s * 0.3, y, fz / 2), (0.1, 0.1, fz), T("log"))
        fl.box((wx, y, fz - 0.12), (0.75, 0.1, 0.1), mwd)
    fl.box2((wx - 0.9, y1, 0), (wx + 0.9, y1 + 1.2, fz + 0.2), {"top": T("grass"), "side": T("stone_brick")})  # headrace bank
    # tail-race channel with stone edges
    for s in (-1, 1):
        fl.box2((wx + s * 0.62 - 0.1, -4.5, 0), (wx + s * 0.62 + 0.1, 0.9, 0.18), mst)
    fl.build(nm("MillFlume"), R)
    wt = MB()
    mwt = X.mat("water", name="kit_flume_water", anim=(0.0, 0.8), shadow=0.85)
    wt.strip([[(wx - 0.26, y1 + 0.6, fz + 0.15), (wx + 0.26, y1 + 0.6, fz + 0.15)],
              [(wx - 0.26, y0, fz + 0.15), (wx + 0.26, y0, fz + 0.15)]], mwt)
    mfall = X.mat("whitewater", name="kit_fall", anim=(0.0, 0.0, 1.3), shadow=0.85)
    fall = []
    for i in range(7):  # water spilling over the wheel front, curving down
        a = math.radians(90 + i * 22)
        rr = wr + 0.06
        fall.append([(wx - 0.24, rr * math.cos(a) * -1 * 0 + -rr * math.sin(math.radians(i * 22)), wz + rr * math.cos(math.radians(i * 22))),
                     (wx + 0.24, -rr * math.sin(math.radians(i * 22)), wz + rr * math.cos(math.radians(i * 22)))])
    fall.insert(0, [(wx - 0.24, y0, fz + 0.15), (wx + 0.24, y0, fz + 0.15)])
    wt.strip(fall, mfall, up=(0, -1, 0.3))
    wt.strip([[(wx - 0.5, 0.9, 0.12), (wx + 0.5, 0.9, 0.12)], [(wx - 0.5, -4.5, 0.08), (wx + 0.5, -4.5, 0.08)]],
             X.mat("water", name="kit_tailrace", anim=(0.0, 0.5), shadow=0.85))
    wt.build(nm("MillWater"), R, recalc=False)
    return 3.8


@kit("boat", "Hollowed log boat (dugout) like the reference reel: bark-textured log hull with carved interior, "
             "plank seats, mast with orange 'S' sail on yard and boom, rigging, two oars. Bobs gently.",
     {"sail": "default true", "length": "m (default 4)", "sail_color": "sail_s (default) | canvas | fabric_red"},
     (4.2, 1.0, 3.2))
def k_boat(R, p):
    L = max(2.0, num(p, "length", 4.0))
    body = empty(nm("BoatBody"), R)
    drive(body, "location", 2, "0.025*sin(frame*0.07)")
    drive(body, "rotation_euler", 0, "0.02*sin(frame*0.05+1)")
    drive(body, "rotation_euler", 1, "0.012*sin(frame*0.04)")
    Rr, zc = 0.42, 0.42 + 0.17
    th = math.asin((zc - Rr) / Rr)
    ri = Rr - 0.08
    phi = math.asin((zc - Rr) / ri)
    m_out, m_in = T("log_h"), T("planks_light")
    mcnt = 12
    outer = [(Rr * math.cos(th - k * (math.pi + 2 * th) / mcnt), Rr + Rr * math.sin(th - k * (math.pi + 2 * th) / mcnt))
             for k in range(mcnt + 1)]
    inner = [(ri * math.cos(-math.pi - phi + k * (math.pi + 2 * phi) / mcnt),
              Rr + 0.03 + ri * math.sin(-math.pi - phi + k * (math.pi + 2 * phi) / mcnt)) for k in range(mcnt + 1)]
    inner = [(y, max(z, 0.13)) for (y, z) in inner]
    prof = outer + inner
    em = [m_out] * mcnt + [m_in] + [m_in] * mcnt + [m_in]
    mb = MB()
    e = L / 2 - 0.35
    mb.prism(prof, -e, e, m_out, "x", em, cap=m_in)
    endp = outer + [(outer[-1][0] * 0.0, zc)]
    for s in (-1, 1):  # solid log ends, slightly rounded toward the bow/stern
        mb.prism(outer, s * e, s * (e + 0.2), m_out, "x", [m_out] * mcnt + [m_in], cap=T("planks"))
        sc = 0.8
        o2 = [(y * sc, Rr + (z - Rr) * sc + (1 - sc) * 0.2) for (y, z) in outer]
        mb.prism(o2, s * (e + 0.2), s * (e + 0.35), m_out, "x", [m_out] * mcnt + [m_in], cap=T("planks"))
    ws = 2 * math.sqrt(max(0.01, ri ** 2 - (zc - 0.12 - Rr) ** 2)) + 0.04
    for x in (-L * 0.22, L * 0.2):
        mb.box((x, 0, zc - 0.1), (0.24, ws, 0.05), T("planks"))
    mb.box((0, 0, 0.15), (L - 0.9, 0.36, 0.04), T("planks"))  # floor boards
    mo = T("planks_light")
    for s in (-1, 1):  # oars resting along the hull
        with mb.at((-0.2, s * 0.22, zc + 0.03), (0, 0, s * 4)):
            mb.cyl((0, 0, 0), 0.025, 2.2, mo, n=6, rot=(0, 90, 0))
            mb.box((1.2, 0, 0), (0.42, 0.14, 0.03), mo)
    mb.build(nm("BoatHull"), R).parent = body
    if flag(p, "sail", True):
        mx = L * 0.12
        ms = MB()
        ms.cyl((mx, 0, 1.6), 0.05, 3.1, T("planks_light"), n=8)
        ms.box((mx, 0, 0.62), (0.18, 0.18, 0.12), T("planks"))
        ms.cyl((mx - 0.65, 0, 2.95), 0.03, 1.9, T("planks_light"), n=6, rot=(0, 90, 0))
        ms.cyl((mx - 0.75, 0, 1.05), 0.035, 2.0, T("planks_light"), n=6, rot=(0, 90, 0))
        for (a, b) in [((mx, 0, 3.1), (L / 2 - 0.2, 0, zc)), ((mx, 0, 3.1), (-L / 2 + 0.2, 0, zc))]:
            va, vb = Vector(a), Vector(b)
            d = vb - va
            ms.cyl(((va + vb) / 2).to_tuple(), 0.012, d.length, T("rope"), n=4,
                   rot=(0, math.degrees(math.atan2(d.x, d.z)), 0))
        ms.build(nm("BoatMast"), R).parent = body
        sm = MB()
        msail = X.mat(word(p, "sail_color", "sail_s"), uv=True, shadow=0.75) if word(p, "sail_color", "sail_s") in X.GEN \
            else T(p.get("sail_color"))
        x0, x1, z0, z1 = mx - 1.6, mx + 0.25, 1.1, 2.9
        rows, uvs = [], []
        for i in range(3):
            t = i / 2
            z = z0 + (z1 - z0) * t
            rows.append([(x0 + 0.1 * t, -0.04 * 0, z), ((x0 + x1) / 2, -0.12 * math.sin(math.pi * (0.3 + 0.4 * t)) - 0.02, z),
                         (x1, 0.0, z)])
            uvs.append([(0.0, t), (0.5, t), (1.0, t)])
        sm.strip(rows, msail, up=(0, -1, 0), uvs=uvs)
        so = sm.build(nm("BoatSail"), R, recalc=False, origin=(mx, 0, 0))
        so.parent = body
        drive(so, "rotation_euler", 2, "0.05*sin(frame*0.045)")
    return 3.1


@kit("dock", "Wooden dock / jetty: plank deck on log posts, mooring bollards, ladder, rope coil.",
     {"length": "m (default 4)"}, (1.8, 4, 1.1))
def k_dock(R, p):
    L = num(p, "length", 4.0)
    mb = MB()
    for i in range(int(L / 0.32)):
        mb.box((0, -L / 2 + 0.16 + i * 0.32, 0.72), (1.6, 0.29, 0.06), T("planks"), rot=(0, 0, (i % 3 - 1) * 0.8))
    for y in (-L / 2 + 0.15, 0, L / 2 - 0.15):
        for s in (-1, 1):
            mb.cyl((s * 0.72, y, 0.45), 0.09, 0.9 if abs(y) < L / 2 - 0.2 else 1.1, T("log"), n=7)
        mb.box((0, y, 0.62), (1.6, 0.12, 0.12), T("planks_dark"))
    for s in (-1, 1):
        mb.box((s * 0.74, 0, 0.64), (0.1, L, 0.1), T("planks_dark"))
        mb.cyl((s * 0.65, -L / 2 + 0.2, 0.95), 0.07, 0.4, T("planks_dark"), n=7)
    mb.cyl((0.4, -L / 2 + 0.5, 0.79), 0.2, 0.08, T("rope"), n=10)
    for k in range(4):
        mb.box((-0.55, -L / 2 - 0.05, 0.6 - k * 0.2), (0.4, 0.05, 0.04), T("planks_dark"))
    mb.build(nm("Dock"), R)
    return 0.75


# ================================================================== BUILDINGS
@kit("house", "Cosy village house (bakery by default, like the reference): clapboard walls on a stone footing, gable "
              "roof, brick chimney with rising smoke, door with frame, glazed windows, striped awning, sign board.",
     {"style": "bakery | cottage", "walls": "siding_grey | siding_white | plaster | planks | red_brick | stone_brick",
      "roof": "roof_grey | roof_red | roof_blue | thatch", "door_color": "#hex"},
     (5, 4.5, 4.6))
def k_house(R, p):
    style = word(p, "style", "bakery")
    W, D, Hw = 4.4, 3.2, 2.5
    mw = T(p.get("walls", "siding_grey" if style == "bakery" else "plaster"))
    mroof = T(p.get("roof", "roof_grey" if style == "bakery" else "roof_red"))
    mtrim = T("siding_white")
    mst = T("stone_brick")
    mb = MB()
    t = 0.2
    door = (-0.45, 0.45, 0.35, 2.15)
    wins = [(-1.85, -0.85, 1.0, 1.9), (0.85, 1.85, 1.0, 1.9)]
    mb.box2((-W / 2 - 0.08, -D / 2 - 0.08, 0), (W / 2 + 0.08, D / 2 + 0.08, 0.35), mst)
    wall(mb, "x", -W / 2, W / 2, -D / 2 + t / 2, t, 0.35, Hw, mw, [door] + wins)
    wall(mb, "x", -W / 2, W / 2, D / 2 - t / 2, t, 0.35, Hw, mw, [(-0.5, 0.5, 1.0, 1.8)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, -W / 2 + t / 2, t, 0.35, Hw, mw, [(-0.45, 0.45, 1.0, 1.8)])
    wall(mb, "y", -D / 2 + t, D / 2 - t, W / 2 - t / 2, t, 0.35, Hw, mw, [(-0.45, 0.45, 1.0, 1.8)])
    mb.box2((-W / 2 + t, -D / 2 + t, 0.35), (W / 2 - t, D / 2 - t, Hw - 0.01), X.mat("#4a3426", name="kit_warm_interior", emit=True))
    for x in (-W / 2, W / 2):
        for y in (-D / 2, D / 2):
            mb.box((x, y, (0.35 + Hw) / 2), (0.14, 0.14, Hw - 0.35), mtrim)
    for w in wins:
        window(mb, "x", w[0], w[1], w[2], w[3], -D / 2, -1, mtrim, T("glass"))
    window(mb, "x", -0.5, 0.5, 1.0, 1.8, D / 2, 1, mtrim, T("glass"))
    window(mb, "y", -0.45, 0.45, 1.0, 1.8, -W / 2, -1, mtrim, T("glass"))
    window(mb, "y", -0.45, 0.45, 1.0, 1.8, W / 2, 1, mtrim, T("glass"))
    dc = p.get("door_color", "#3f7a4a")
    mb.box2((door[0], -D / 2 + 0.08, door[2]), (door[1], -D / 2 + 0.12, door[3]), T(dc))
    mb.box2((door[0] + 0.12, -D / 2 + 0.05, 1.3), (door[1] - 0.12, -D / 2 + 0.08, 1.95), T("glass"))
    mb.box((door[1] - 0.15, -D / 2 + 0.03, 1.2), (0.06, 0.05, 0.06), T("gold"))
    for (a, b, za, zb) in [(door[0] - 0.08, door[0], door[2], door[3] + 0.08), (door[1], door[1] + 0.08, door[2], door[3] + 0.08),
                           (door[0] - 0.08, door[1] + 0.08, door[3], door[3] + 0.08)]:
        mb.box2((a, -D / 2 - 0.04, za), (b, -D / 2 + 0.03, zb), mtrim)
    mb.box2((door[0] - 0.2, -D / 2 - 0.5, 0), (door[1] + 0.2, -D / 2 - 0.08, 0.2), mst)  # step
    if style == "bakery":
        maw = T("awning_red")
        for w in wins:
            mb.hexa([(w[0] - 0.12, -D / 2 - 0.55, 1.98), (w[1] + 0.12, -D / 2 - 0.55, 1.98), (w[0] - 0.12, -D / 2, 2.25),
                     (w[1] + 0.12, -D / 2, 2.25), (w[0] - 0.12, -D / 2 - 0.55, 2.02), (w[1] + 0.12, -D / 2 - 0.55, 2.02),
                     (w[0] - 0.12, -D / 2, 2.29), (w[1] + 0.12, -D / 2, 2.29)], maw)
            mb.box2((w[0] - 0.12, -D / 2 - 0.57, 1.86), (w[1] + 0.12, -D / 2 - 0.53, 2.0), maw)
        # sign board over the door
        mb.box2((-0.85, -D / 2 - 0.08, 2.2), (0.85, -D / 2 - 0.02, 2.48), T("planks_dark"))
        mb.box2((-0.78, -D / 2 - 0.1, 2.24), (0.78, -D / 2 - 0.06, 2.44), T("#c94f3d"))
        for k in range(6):  # pixel lettering suggestion
            mb.box2((-0.6 + k * 0.21, -D / 2 - 0.115, 2.29), (-0.6 + k * 0.21 + 0.12, -D / 2 - 0.1, 2.39), T("#f4ead2"))
    else:
        for w in wins:  # flower boxes
            mb.box2((w[0] - 0.05, -D / 2 - 0.25, w[2] - 0.22), (w[1] + 0.05, -D / 2 - 0.02, w[2] - 0.04), T("planks_dark"))
            for k in range(4):
                mb.ico((w[0] + 0.12 + k * (w[1] - w[0] - 0.24) / 3, -D / 2 - 0.14, w[2] - 0.02), 0.08,
                       T(["#e2534a", "#f2c84b", "#e88fb0", "#ffffff"][k]), scale=(1, 1, 0.8))
    mb.build(nm("House"), R)
    gable_roof(R, nm("HouseRoof"), W, D, Hw, 1.3, mroof, overhang=0.35, mgable=mw)
    ch = MB()
    cx, cy = 1.2, 0.55
    ch.box2((cx - 0.28, cy - 0.28, Hw), (cx + 0.28, cy + 0.28, Hw + 1.9), T("red_brick"))
    ch.box2((cx - 0.34, cy - 0.34, Hw + 1.9), (cx + 0.34, cy + 0.34, Hw + 2.02), T("stone_brick"))
    ch.box2((cx - 0.2, cy - 0.2, Hw + 1.95), (cx + 0.2, cy + 0.2, Hw + 2.03), DARK())
    ch.build(nm("Chimney"), R)
    smoke(R, "Smoke", (cx, cy, Hw + 2.1), n=4, size=0.24)
    return Hw + 1.3


@kit("barn", "Red farm barn like the reference: vertical red board walls with white trim, big double doors with "
             "white X braces, hay-loft door, side windows, steep gable roof (ridge front-to-back), hay bales.",
     {"roof": "roof_grey | roof_red | roof_blue", "open": "doors open showing the hay inside (default false)"},
     (5.5, 6.5, 5))
def k_barn(R, p):
    W, D, Hw, t = 5.0, 6.0, 3.0, 0.2
    mw, mtr = T("planks_red"), T("siding_white")
    mb = MB()
    opn = flag(p, "open", False)
    door = (-1.25, 1.25, 0, 2.6)
    wall(mb, "x", -W / 2, W / 2, -D / 2 + t / 2, t, 0, Hw, mw, [door])
    wall(mb, "x", -W / 2, W / 2, D / 2 - t / 2, t, 0, Hw, mw, [])
    for s in (-1, 1):
        wall(mb, "y", -D / 2 + t, D / 2 - t, s * (W / 2 - t / 2), t, 0, Hw, mw, [(-1.6, -0.8, 1.5, 2.2), (0.8, 1.6, 1.5, 2.2)])
        for (a, b) in [(-1.6, -0.8), (0.8, 1.6)]:
            window(mb, "y", a, b, 1.5, 2.2, s * W / 2, s, mtr, T("glass"))
    mb.box2((-W / 2 + t, -D / 2 + t, 0.0), (W / 2 - t, D / 2 - t, Hw - 0.01), X.mat("#3b2a1e", name="kit_barn_in", emit=True))
    rise = 2.0
    for s in (-1, 1):  # gable ends (triangles) front and back, with loft door at front
        y = s * (D / 2 - t / 2)
        mb.prism([(-W / 2, Hw), (W / 2, Hw), (0, Hw + rise)], y - t / 2, y + t / 2, mw, "y")
    mb.box2((-0.55, -D / 2 - 0.05, Hw + 0.1), (0.55, -D / 2 + 0.02, Hw + 1.15), T("planks_red"))
    for (a, b, za, zb) in [(-0.62, -0.55, Hw + 0.05, Hw + 1.2), (0.55, 0.62, Hw + 0.05, Hw + 1.2), (-0.62, 0.62, Hw + 1.15, Hw + 1.22),
                           (-0.62, 0.62, Hw + 0.05, Hw + 0.12)]:
        mb.box2((a, -D / 2 - 0.07, za), (b, -D / 2 + 0.02, zb), mtr)
    mb.box2((-0.08, -D / 2 - 0.4, Hw + 1.3), (0.08, -D / 2 + 0.02, Hw + 1.42), T("planks_dark"))  # hay hoist beam
    for x in (-W / 2, W / 2):
        for y in (-D / 2, D / 2):
            mb.box((x, y, Hw / 2), (0.16, 0.16, Hw), mtr)
    mb.box2((-W / 2 - 0.08, -D / 2 - 0.09, Hw - 0.12), (W / 2 + 0.08, -D / 2 + 0.02, Hw), mtr)
    # doors with X braces
    for s in (-1, 1):
        if opn:
            x0 = s * 1.25
            with mb.at((x0, -D / 2 - 0.05, 0), (0, 0, s * -100 + (180 if s > 0 else 0))):
                pass
        dx0, dx1 = (door[0], 0) if s < 0 else (0, door[1])
        if opn:
            hx = door[0] if s < 0 else door[1]
            panel = ((hx - 0.05, -D / 2 - 1.25, 0.02), (hx + 0.05, -D / 2 - 0.02, 2.58))
            mb.box2(panel[0], panel[1], mw)
            continue
        yy = -D / 2 - 0.02
        mb.box2((dx0, yy - 0.04, 0.02), (dx1, yy + 0.06, 2.58), mw)
        cx, w_ = (dx0 + dx1) / 2, abs(dx1 - dx0)
        for (a, b, za, zb) in [(dx0, dx1, 2.46, 2.58), (dx0, dx1, 0.02, 0.14), (dx0, dx0 + 0.1, 0.02, 2.58), (dx1 - 0.1, dx1, 0.02, 2.58)]:
            mb.box2((a, yy - 0.08, za), (b, yy - 0.03, zb), mtr)
        diag = math.degrees(math.atan2(2.32, w_ - 0.2))
        for sg in (-1, 1):
            mb.box((cx, yy - 0.055, 1.3), (math.hypot(2.32, w_ - 0.2), 0.04, 0.1), mtr, rot=(0, sg * diag, 0))
    if opn:
        for k in range(3):
            mb.box((-0.6 + k * 0.6, -0.5 + (k % 2) * 0.4, 0.3), (0.55, 0.9, 0.6), T("hay"))
    mb.build(nm("Barn"), R)
    gable_roof(R, nm("BarnRoof"), D, W, Hw, rise, T(p.get("roof", "roof_grey")), overhang=0.3, thick=0.14, yaw=90)
    hb = MB()
    for (x, y, z) in [(W / 2 + 0.5, -D / 2 + 0.6, 0.3), (W / 2 + 0.5, -D / 2 + 1.6, 0.3), (W / 2 + 0.5, -D / 2 + 1.1, 0.9)]:
        hb.box((x, y, z), (0.6, 0.9, 0.6), T("hay"))
    hb.build(nm("HayBales"), R)
    return Hw + rise


@kit("bridge", "Bridge: 'stone' = arched limestone bridge with voussoir ring, parapets and ramps; 'wood' = log-beam "
               "plank bridge with posts and rails.", {"style": "stone | wood", "span": "m (default 4)"},
     (9, 2.2, 2.6))
def k_bridge(R, p):
    style = word(p, "style", "stone")
    S = max(2.0, num(p, "span", 4.0))
    mb = MB()
    if style.startswith("w"):
        z = 0.85
        for s in (-1, 1):
            mb.cyl((0, s * 0.65, z - 0.15), 0.13, S + 1.6, T("log_h"), n=8, rot=(0, 90, 0))
        for i in range(int((S + 1.4) / 0.3)):
            mb.box((-(S + 1.4) / 2 + 0.15 + i * 0.3, 0, z), (0.27, 1.7, 0.06), T("planks_v"), rot=(0, 0, (i % 3 - 1) * 1.2))
        for x in (-S / 2 - 0.6, -S / 4, 0, S / 4, S / 2 + 0.6):
            for s in (-1, 1):
                mb.box((x, s * 0.82, z + 0.45), (0.1, 0.1, 0.9 + (0.5 if abs(x) > S / 2 else 0)), T("log"))
        for s in (-1, 1):
            mb.box((0, s * 0.82, z + 0.85), (S + 1.3, 0.08, 0.08), T("planks_dark"))
            mb.box((0, s * 0.82, z + 0.5), (S + 1.3, 0.06, 0.06), T("planks_dark"))
            for x in (-S / 2 - 0.6, S / 2 + 0.6):
                mb.cyl((x, s * 0.65, z / 2 - 0.2), 0.12, z + 0.4, T("log"), n=7)
        mb.build(nm("Bridge"), R)
        return z + 0.9
    ms, mv, mtop = T("stone_brick"), T("stone_block"), T("gravel_grey")
    Wd, rise, zs = 1.8, S * 0.38, 0.25
    zt = zs + rise + 0.55
    Rad = (S * S / 4 + rise * rise) / (2 * rise)
    zc = zs + rise - Rad
    nseg = 12

    def za(x):
        return zc + math.sqrt(max(0.0, Rad * Rad - x * x))
    for i in range(nseg):
        x0, x1 = -S / 2 + S * i / nseg, -S / 2 + S * (i + 1) / nseg
        mb.hexa([(x0, -Wd / 2, za(x0)), (x1, -Wd / 2, za(x1)), (x0, Wd / 2, za(x0)), (x1, Wd / 2, za(x1)),
                 (x0, -Wd / 2, zt), (x1, -Wd / 2, zt), (x0, Wd / 2, zt), (x1, Wd / 2, zt)], {"side": ms, "top": mtop, "bottom": ms})
    for s in (-1, 1):
        mb.box2((s * S / 2, -Wd / 2, 0) if s > 0 else (-S / 2 - 1.0, -Wd / 2, 0),
                (S / 2 + 1.0, Wd / 2, zt) if s > 0 else (-S / 2, Wd / 2, zt), {"side": ms, "top": mtop})
        xa, xb = s * (S / 2 + 1.0), s * (S / 2 + 3.2)
        lo, hi = (xa, xb) if s > 0 else (xb, xa)
        z_lo = (0.02, zt) if s < 0 else (zt, 0.02)
        mb.hexa([(lo, -Wd / 2, 0), (hi, -Wd / 2, 0), (lo, Wd / 2, 0), (hi, Wd / 2, 0), (lo, -Wd / 2, z_lo[0]), (hi, -Wd / 2, z_lo[1]),
                 (lo, Wd / 2, z_lo[0]), (hi, Wd / 2, z_lo[1])], {"side": ms, "top": mtop})
    # voussoir ring (alternating), proud of the faces
    nv = 13
    a0 = math.asin(min(1.0, (S / 2) / Rad))
    for i in range(nv):
        t0, t1 = -a0 + 2 * a0 * i / nv, -a0 + 2 * a0 * (i + 1) / nv
        for s in (-1, 1):
            c8 = []
            for k in range(8):
                tt = t1 if k & 1 else t0
                y = s * (Wd / 2 + (0.05 if (k >> 1) & 1 else -0.02)) if s > 0 else s * (Wd / 2 + (0.05 if not (k >> 1) & 1 else -0.02))
                rr = Rad + (0.38 if (k >> 2) & 1 else 0.0)
                c8.append((rr * math.sin(tt), y, zc + rr * math.cos(tt)))
            mb.hexa(c8, mv if i % 2 else ms)
    # parapets
    for s in (-1, 1):
        y0 = s * (Wd / 2 - 0.12)
        mb.box2((-S / 2 - 1.0, y0 - 0.12, zt), (S / 2 + 1.0, y0 + 0.12, zt + 0.45), {"side": ms, "top": mv})
        for sx in (-1, 1):
            xa, xb = sx * (S / 2 + 1.0), sx * (S / 2 + 3.2)
            lo, hi = (xa, xb) if sx > 0 else (xb, xa)
            zl, zh = (zt, 0.02) if sx > 0 else (0.02, zt)
            mb.hexa([(lo, y0 - 0.12, zl), (hi, y0 - 0.12, zh), (lo, y0 + 0.12, zl), (hi, y0 + 0.12, zh),
                     (lo, y0 - 0.12, zl + 0.45), (hi, y0 - 0.12, zh + 0.3), (lo, y0 + 0.12, zl + 0.45), (hi, y0 + 0.12, zh + 0.3)],
                    {"side": ms, "top": mv})
    mb.build(nm("Bridge"), R)
    return zt + 0.45


@kit("well", "Village stone well: round block wall, dark water inside, two posts with crossbeam, crank, little "
             "shingle roof, wooden bucket on a rope.", {"roof": "roof_red | roof_grey | thatch"}, (1.8, 1.8, 2.4))
def k_well(R, p):
    mb = MB()
    n, ro, ri, h = 12, 0.75, 0.55, 0.8
    ms = T("stone_brick")
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        c8 = []
        for k in range(8):
            a = a1 if k & 1 else a0
            rr = ro if (k >> 1) & 1 else ri
            c8.append((rr * math.cos(a), rr * math.sin(a), h if (k >> 2) & 1 else 0))
        mb.hexa(c8, {"side": ms, "top": T("stone_block")})
    mb.cyl((0, 0, 0.45), ri + 0.02, 0.02, X.mat("water_deep", name="kit_well_water", anim=(0.01, 0.0)), n=n)
    for s in (-1, 1):
        mb.box((s * 0.66, 0, 1.25), (0.1, 0.1, 1.7), T("planks_dark"))
    mb.cyl((0, 0, 1.75), 0.06, 1.45, T("log_h"), n=8, rot=(0, 90, 0))
    mb.box((0.78, -0.12, 1.75), (0.04, 0.24, 0.04), T("iron"))
    mb.box((0.8, -0.24, 1.66), (0.04, 0.04, 0.2), T("iron"))
    mb.cyl((0, 0, 1.45), 0.012, 0.6, T("rope"), n=4)
    mb.lathe((0, 0, 0.98), [(0.13, 0), (0.16, 0.18), (0.0, 0.18)], T("staves"), n=8)
    mb.build(nm("Well"), R)
    gable_roof(R, nm("WellRoof"), 1.5, 0.9, 2.05, 0.45, T(word(p, "roof", "roof_red")), overhang=0.15, thick=0.06,
               yaw=90)
    return 2.5


# ================================================================== SMALL PROPS
@kit("cart", "Wooden hand/ox cart: plank bed with side boards, two spoked wheels on an axle, shafts. "
             "Cargo optional. Wheels turn when moving=true.",
     {"cargo": "hay | sacks | stones | crates | none (default sacks)", "moving": "spin the wheels (default false)"},
     (2.6, 1.6, 1.4))
def k_cart(R, p):
    mb = MB()
    mw, md = T("planks"), T("planks_dark")
    z = 0.62
    mb.box((0, 0, z), (1.7, 1.05, 0.07), mw)
    for s in (-1, 1):
        mb.box((0, s * 0.5, z + 0.22), (1.7, 0.05, 0.38), mw)
        mb.box((s * 0.85, 0, z + 0.22), (0.05, 1.05, 0.38), mw)
        mb.box((-1.25, s * 0.42, z - 0.05), (1.4, 0.07, 0.07), md, rot=(0, -6, s * 4))
    for x in (-0.82, 0.82):
        for y in (-0.5, 0.5):
            mb.box((x, y, z + 0.2), (0.07, 0.07, 0.45), md)
    mb.cyl((0, 0, 0.5), 0.05, 1.45, T("iron"), n=6, rot=(90, 0, 0))
    mb.box((-1.85, 0.0, z - 0.1), (0.07, 0.9, 0.06), md)
    cargo = word(p, "cargo", "sacks")
    rng = random.Random(9)
    if cargo.startswith("sack"):
        for i in range(5):
            mb.ico((-0.45 + (i % 3) * 0.45, -0.2 + (i // 3) * 0.4, z + 0.25 + (i // 3) * 0.12), 0.26, T("sacking"),
                   scale=(1.2, 0.85, 0.75), jitter=0.12, rng=rng)
    elif cargo.startswith("hay"):
        mb.box((0, 0, z + 0.45), (1.6, 0.95, 0.75), T("hay"))
    elif cargo.startswith("stone"):
        _block_pile(mb, (0, 0, z + 0.04), rng, T("stone_block"), 2, 2, 1, bs=(0.6, 0.42, CH))
    elif cargo.startswith("crate"):
        _crate(mb, (-0.35, 0, z + 0.04), 0.55)
        _crate(mb, (0.35, 0.05, z + 0.04), 0.5)
    mb.build(nm("Cart"), R)
    for s in (-1, 1):
        wb = MB()
        wheel(wb, 0.5, 0.08, md, n=12, spokes=4)
        o = wb.build(nm("CartWheel"), R, origin=(0, 0, 0))
        o.location = (0, s * 0.68, 0.5)
        if flag(p, "moving", False):
            drive(o, "rotation_euler", 1, "frame*0.06")
    return 1.3


def _crate(mb, base, s):
    c = (base[0], base[1], base[2] + s / 2)
    mb.box(c, (s * 0.96, s * 0.96, s * 0.96), T("planks_light"))
    f = s * 0.1
    md = T("planks_dark")
    for (dx, dz) in [(1, 0), (-1, 0)]:
        for (dy) in (-1, 1):
            mb.box((c[0] + dx * (s - f) / 2, c[1] + dy * (s - f) / 2, c[2]), (f, f, s), md)
    for dy in (-1, 1):
        for dz in (-1, 1):
            mb.box((c[0], c[1] + dy * (s - f) / 2, c[2] + dz * (s - f) / 2), (s, f, f), md)
    for dx in (-1, 1):
        for dz in (-1, 1):
            mb.box((c[0] + dx * (s - f) / 2, c[1], c[2] + dz * (s - f) / 2), (f, s, f), md)
    for dy in (-1, 1):  # diagonal brace on the faces
        mb.box((c[0], c[1] + dy * (s * 0.49), c[2]), (s * 1.18, f * 0.7, f * 0.9), md, rot=(0, 45, 0))


@kit("crates", "Stack of wooden crates with dark frames and braces.", {"count": "1-6 (default 4)"}, (1.6, 1.0, 1.3))
def k_crates(R, p):
    cnt = max(1, min(6, int(num(p, "count", 4))))
    spots = [((-0.33, 0, 0), 0.62), ((0.33, 0.05, 0), 0.6), ((0.0, 0.0, 0.62), 0.56), ((-0.2, 0.62, 0), 0.6),
             ((0.45, 0.6, 0), 0.55), ((0.1, 0.6, 0.6), 0.5)]
    mb = MB()
    for i in range(cnt):
        b, s = spots[i]
        _crate(mb, b, s)
    mb.build(nm("Crates"), R)
    return 1.2 if cnt >= 3 else 0.62


@kit("barrel", "Wooden barrels (bulged staves, iron hoops, lid).", {"count": "1-3 (default 1)"}, (0.7, 0.7, 0.9))
def k_barrel(R, p):
    cnt = max(1, min(3, int(num(p, "count", 1))))
    mb = MB()
    for i, (x, y) in enumerate([(0, 0), (0.62, 0.1), (0.3, 0.6)][:cnt]):
        prof = [(0.25, 0), (0.3, 0.2), (0.32, 0.42), (0.3, 0.64), (0.25, 0.84)]
        mb.lathe((x, y, 0), prof, T("staves"), n=12, mcap=T("planks"))
        for z, r in [(0.07, 0.272), (0.27, 0.317), (0.57, 0.317), (0.77, 0.272)]:
            mb.cyl((x, y, z), r, 0.05, T("iron"), n=12, caps=False)
        mb.cyl((x, y, 0.845), 0.22, 0.02, T("planks"), n=12)
    mb.build(nm("Barrels"), R)
    return 0.85


def _pot_shape(mb, base, style, s=1.0, m=None):
    m = m or T("clay")
    profs = {
        "amphora": [(0.03, 0), (0.1, 0.06), (0.2, 0.25), (0.22, 0.4), (0.18, 0.56), (0.08, 0.68), (0.06, 0.8), (0.1, 0.84)],
        "jar": [(0.12, 0), (0.22, 0.1), (0.26, 0.26), (0.22, 0.42), (0.14, 0.48), (0.16, 0.53)],
        "bowl": [(0.1, 0), (0.24, 0.08), (0.3, 0.18), (0.31, 0.22)],
    }
    prof = [(r * s, z * s) for (r, z) in profs.get(style, profs["jar"])]
    mb.lathe(base, prof, m, n=10, mtop=DARK())
    if style == "amphora":
        for sg in (-1, 1):
            mb.box((base[0] + sg * 0.13 * s, base[1], base[2] + 0.66 * s), (0.04 * s, 0.03 * s, 0.2 * s), m, rot=(0, sg * 25, 0))
    if style == "jar":
        mb.box((base[0], base[1] - 0.2 * s, base[2] + 0.31 * s), (0.36 * s, 0.03 * s, 0.03 * s), T("#e7d8b8"))


@kit("pot", "Clay pottery: amphora, wide storage jar or bowl (terracotta).",
     {"style": "amphora | jar | bowl", "count": "1-4 (default 1)", "mat": "clay (default) | ceramic_white | #hex"},
     (0.5, 0.5, 0.85))
def k_pot(R, p):
    style = word(p, "style", "amphora")
    cnt = max(1, min(4, int(num(p, "count", 1))))
    mb = MB()
    m = T(p.get("mat", "clay"))
    for i, (x, y, s) in enumerate([(0, 0, 1.0), (0.5, 0.15, 0.8), (-0.45, 0.2, 0.7), (0.15, 0.55, 0.9)][:cnt]):
        _pot_shape(mb, (x, y, 0), style, s, m)
    mb.build(nm("Pots"), R)
    return 0.85


@kit("tools", "Builder's tools: shovel, pickaxe, wooden mallet/hammer - laid on the ground or leaning.",
     {"tool": "all | shovel | pickaxe | hammer", "lean": "shovel leans upright (default true)"}, (1.4, 0.8, 1.1))
def k_tools(R, p):
    tool = word(p, "tool", "all")
    lean = flag(p, "lean", True)
    mb = MB()
    mw, mm = T("planks_light"), T("iron")
    if tool in ("all", "shovel"):
        pos, rot = ((-0.45, 0.1, 0.6), (-12, 0, 0)) if lean else ((-0.4, 0.05, 0.05), (90, 0, 15))
        with mb.at(pos, rot):
            mb.cyl((0, 0, 0.15), 0.025, 0.85, mw, n=6)
            mb.box((0, 0, 0.6), (0.16, 0.035, 0.035), mw)
            mb.box((0, 0, -0.35), (0.22, 0.03, 0.3), mm)
            mb.hexa([(-0.11, -0.015, -0.5), (0.11, -0.015, -0.5), (-0.11, 0.015, -0.5), (0.11, 0.015, -0.5),
                     (-0.08, -0.03, -0.6), (0.08, -0.03, -0.6), (-0.08, 0.0, -0.6), (0.08, 0.0, -0.6)][:4] +
                    [(-0.02, -0.01, -0.62), (0.02, -0.01, -0.62), (-0.02, 0.01, -0.62), (0.02, 0.01, -0.62)], mm)
        if lean:
            mb.box2((-0.65, 0.2, 0), (-0.25, 0.55, 0.45), T("log"))  # stump it leans on
    if tool in ("all", "pickaxe"):
        with mb.at((0.15, -0.1, 0.04), (0, 90, 25)):
            mb.cyl((0, 0, 0), 0.03, 0.9, mw, n=6)
            with mb.at((0, 0, 0.42)):
                for sg in (-1, 1):
                    mb.hexa([(0, -0.03, -0.03), (sg * 0.3, -0.012, -0.03 - 0.05), (0, 0.03, -0.03), (sg * 0.3, 0.012, -0.03 - 0.05),
                             (0, -0.03, 0.04), (sg * 0.3, -0.012, -0.03), (0, 0.03, 0.04), (sg * 0.3, 0.012, -0.03)], mm)
    if tool in ("all", "hammer"):
        with mb.at((0.55, 0.25, 0.04), (0, 90, -40)):
            mb.cyl((0, 0, 0), 0.025, 0.5, mw, n=6)
            mb.box((0, 0, 0.28), (0.12, 0.2, 0.12), T("planks_dark"))
    mb.build(nm("Tools"), R)
    return 0.9


@kit("tent", "A-frame canvas tent with ridge pole, open front flaps showing a dark inside, guy ropes and pegs.",
     {"color": "canvas | fabric_red | fabric_blue | fabric_cream | #hex", "length": "m (default 2.4)"},
     (2.6, 3, 1.7))
def k_tent(R, p):
    L, Wt, H = num(p, "length", 2.4), 2.0, 1.6
    mc = T(p.get("color", "canvas"))
    mb = MB()
    th = 0.04
    for s in (-1, 1):  # two slanted panels, ridge along y (door faces -Y)
        mb.hexa([(s * Wt / 2, -L / 2, 0.02), (s * Wt / 2 + s * th, -L / 2, 0.02), (s * Wt / 2, L / 2, 0.02), (s * Wt / 2 + s * th, L / 2, 0.02),
                 (0, -L / 2, H), (s * th, -L / 2, H + th), (0, L / 2, H), (s * th, L / 2, H + th)], mc)
    mb.prism([(-Wt / 2, 0.02), (Wt / 2, 0.02), (0, H)], L / 2 - 0.08, L / 2 - 0.04, mc, "y")
    mb.prism([(-Wt / 2 + 0.05, 0.0), (Wt / 2 - 0.05, 0.0), (0, H - 0.05)], -L / 2 + 0.3, -L / 2 + 0.33, DARK(), "y")
    for s in (-1, 1):  # rolled-open flaps
        mb.hexa([(s * Wt / 2 - s * 0.02, -L / 2 - 0.02, 0.02), (s * Wt / 2 * 0.45, -L / 2 - 0.02, H * 0.55), (s * Wt / 2 - s * 0.02, -L / 2 + 0.03, 0.02),
                 (s * Wt / 2 * 0.45, -L / 2 + 0.03, H * 0.55), (s * Wt / 2 - s * 0.24, -L / 2 - 0.02, 0.02), (s * 0.06, -L / 2 - 0.02, H * 0.97),
                 (s * Wt / 2 - s * 0.24, -L / 2 + 0.03, 0.02), (s * 0.06, -L / 2 + 0.03, H * 0.97)], mc)
    md = T("planks_dark")
    mb.cyl((0, 0, H + 0.03), 0.03, L + 0.3, md, n=6, rot=(90, 0, 0))
    for y in (-L / 2 - 0.1, L / 2 + 0.1):
        mb.cyl((0, y, (H + 0.15) / 2), 0.03, H + 0.15, md, n=6)
        a, b = Vector((0, y, H + 0.05)), Vector((0, y + (0.9 if y > 0 else -0.9), 0.02))
        d = b - a
        mb.cyl(((a + b) / 2).to_tuple(), 0.008, d.length, T("rope"), n=4, rot=(math.degrees(math.atan2(-d.y, d.z)) * -1, 0, 0))
        mb.box(b.to_tuple(), (0.05, 0.05, 0.12), md)
    mb.build(nm("Tent"), R)
    return H


@kit("sign", "Wooden signpost: post with a framed board and an arrow board (text not rendered).",
     {"arrow": "extra arrow board (default true)", "board": "planks_light | planks | #hex"}, (1.0, 0.2, 1.8))
def k_sign(R, p):
    mb = MB()
    md = T("planks_dark")
    mb.box((0, 0, 0.85), (0.1, 0.1, 1.7), md)
    mb.box((0, -0.07, 1.45), (1.0, 0.05, 0.45), T(p.get("board", "planks_light")))
    for (x, z, w, h) in [(0, 1.69, 1.06, 0.05), (0, 1.21, 1.06, 0.05), (-0.52, 1.45, 0.05, 0.53), (0.52, 1.45, 0.05, 0.53)]:
        mb.box((x, -0.08, z), (w, 0.06, h), md)
    for k in range(4):
        mb.box((-0.3 + k * 0.2, -0.1, 1.48), (0.12, 0.01, 0.12), T("#5a3a22"))
    if flag(p, "arrow", True):
        with mb.at((0.15, 0.07, 0.95), (0, 0, 8)):
            mb.box((0, 0, 0), (0.6, 0.05, 0.18), T("planks"))
            mb.add([(0.3, -0.025, -0.15), (0.3, -0.025, 0.15), (0.48, -0.025, 0.0), (0.3, 0.025, -0.15), (0.3, 0.025, 0.15),
                    (0.48, 0.025, 0.0)], [(0, 2, 1), (3, 4, 5), (0, 3, 5, 2), (1, 2, 5, 4), (0, 1, 4, 3)], T("planks"))
    mb.build(nm("Sign"), R)
    return 1.7


@kit("fence", "Fence run along X: wooden post-and-rail (default) or white picket.",
     {"length": "m (default 4)", "style": "rail | picket"}, (4, 0.2, 1.0))
def k_fence(R, p):
    L = max(1.0, num(p, "length", 4.0))
    style = word(p, "style", "rail")
    mb = MB()
    n = max(1, int(round(L / 1.2)))
    if style.startswith("pick"):
        mw = T("siding_white")
        k = int(L / 0.16)
        for i in range(k + 1):
            x = -L / 2 + i * L / k
            mb.box((x, 0, 0.42), (0.09, 0.03, 0.84), mw)
            mb.add([(x - 0.045, -0.015, 0.84), (x + 0.045, -0.015, 0.84), (x, -0.015, 0.92), (x - 0.045, 0.015, 0.84),
                    (x + 0.045, 0.015, 0.84), (x, 0.015, 0.92)], [(0, 1, 2), (5, 4, 3), (1, 4, 5, 2), (0, 2, 5, 3)], mw)
        for z in (0.25, 0.65):
            mb.box((0, 0.03, z), (L, 0.03, 0.07), mw)
    else:
        for i in range(n + 1):
            mb.box((-L / 2 + i * L / n, 0, 0.5), (0.12, 0.12, 1.0), T("log"))
        for z in (0.45, 0.82):
            for i in range(n):
                x = -L / 2 + (i + 0.5) * L / n
                mb.box((x, 0, z + (0.02 if i % 2 else 0)), (L / n + 0.1, 0.06, 0.1), T("planks_dark"), rot=(0, (i % 2) * 1.5 - 0.7, 0))
    mb.build(nm("Fence"), R)
    return 0.95


@kit("rock", "Chunky low-poly boulder cluster.", {"size": "m (default 1.2)", "style": "grey | desert | mossy"},
     (2, 1.6, 1.2))
def k_rock(R, p):
    s = num(p, "size", 1.2)
    style = word(p, "style", "grey")
    rng = random.Random(int(num(p, "seed", 2)))
    side = T({"desert": "rock_desert", "mossy": "rock_grey"}.get(style, "rock"))
    m = {"top": T("leaves_solid") if style == "mossy" else side, "side": side}
    mb = MB()
    for (x, y, r, sz) in [(0, 0, 0.55, 1.0), (0.55, 0.25, 0.35, 0.8), (-0.5, 0.15, 0.3, 0.7), (0.2, -0.45, 0.22, 0.6)]:
        mb.ico((x * s, y * s, r * s * 0.55 * sz), r * s, m, scale=(1.15, 1.0, 0.85 * sz), jitter=0.22, rng=rng, sub=1,
               rot=(0, 0, rng.uniform(0, 90)), flat_bottom=r * s * 0.3)
    mb.build(nm("Rocks"), R)
    return 0.9 * s


@kit("campfire", "Campfire: ring of stones, crossed logs, animated flickering flames, rising smoke, warm light.",
     {"smoke": "default true", "size": "scale (default 1)"}, (1.0, 1.0, 0.8))
def k_campfire(R, p):
    s = num(p, "size", 1.0)
    rng = random.Random(6)
    mb = MB()
    stone_ring(mb, (0, 0, 0), 0.42 * s, 9, T("rock"), rng, 0.13 * s)
    for i in range(4):
        a = i * 45 + 10
        mb.cyl((0, 0, 0.12 * s), 0.055 * s, 0.7 * s, T("log"), n=6, rot=(70, 0, a))
    mb.cyl((0, 0, 0.02), 0.3 * s, 0.03, X.mat("#3a2a20", name="kit_ash"), n=8)
    mb.build(nm("Campfire"), R)
    flames(R, "Flame", (0, 0, 0.05 * s), s)
    if flag(p, "smoke", True):
        smoke(R, "CampSmoke", (0, 0, 0.7 * s), n=4, size=0.16 * s, rise=1.4 * s, color="#d9d9d9")
    return 0.7 * s


# ================================================================== GENERIC FALLBACK
def _part(mb, part, i):
    shape = str(part.get("shape", "box")).lower()
    m = T(part.get("mat", part.get("material", part.get("color", "planks"))))
    at = list(part.get("at", part.get("pos", [0, 0, 0])) or [0, 0, 0]) + [0, 0, 0]
    rot = list(part.get("rot", [0, 0, 0]) or [0, 0, 0])
    rot = (rot + [0, 0, 0])[:3] if isinstance(rot, list) else [0, 0, float(rot)]
    sz = part.get("size", None)
    r = part.get("r", None)
    h = part.get("h", None)
    if isinstance(sz, (int, float)):
        sz = [sz, sz, sz]
    sz = [float(v) for v in (sz or [])] + [0.5, 0.5, 0.5]
    x, y, z = float(at[0]), float(at[1]), float(at[2])
    rot = [float(v) for v in rot]
    if shape in ("cyl", "cylinder", "cone", "tube", "pole", "disc", "disk"):
        rr = float(r) if r is not None else sz[0] / 2
        hh = float(h) if h is not None else sz[2]
        with mb.at((x, y, z), rot):
            mb.cyl((0, 0, hh / 2), rr, hh, m, n=10 if rr > 0.2 else 8, r2=0.0 if shape == "cone" else None)
    elif shape in ("ball", "sphere", "blob", "dome"):
        rr = float(r) if r is not None else sz[0] / 2
        sc = (1, 1, 1) if r is not None else (1, sz[1] / max(sz[0], 1e-3), sz[2] / max(sz[0], 1e-3))
        with mb.at((x, y, z), rot):
            mb.ico((0, 0, rr * sc[2]), rr, m, scale=sc, sub=1)
    elif shape in ("wedge", "ramp", "roof"):
        a, b, c = sz[0] / 2, sz[1] / 2, sz[2]
        with mb.at((x, y, z), rot):
            mb.hexa([(-a, -b, 0), (a, -b, 0), (-a, b, 0), (a, b, 0), (-a, -b, 0.001), (a, -b, 0.001), (-a, b, c), (a, b, c)], m)
    else:
        with mb.at((x, y, z), rot):
            mb.box((0, 0, sz[2] / 2), sz[:3], m)


@kit("generic", "Fallback for any other noun: composed from primitive parts you list (box/cyl/cone/ball/wedge with "
                "size, base-centre position 'at', rotation degrees and a texture name or #hex). No parts -> a tidy crate "
                "of the given 'mat' and 'size'.",
     {"parts": "[{'shape':'box|cyl|cone|ball|wedge','size':[x,y,z] (or 'r','h'),'at':[x,y,z] base centre,"
               "'rot':[deg,deg,deg],'mat':'texture name or #hex'}]", "mat": "texture for the no-parts crate",
      "size": "crate size m (default 0.8)"},
     (1, 1, 1))
def generic(R, p):
    parts = p.get("parts") or []
    mb = MB()
    if isinstance(parts, list) and parts:
        for i, part in enumerate(parts[:80]):
            if isinstance(part, dict):
                try:
                    _part(mb, part, i)
                except Exception:
                    traceback.print_exc()
    if mb.empty():
        s = num(p, "size", 0.8) if not isinstance(p.get("size"), (list, tuple)) else float(p["size"][0])
        m = p.get("mat")
        if m:
            mb.box((0, 0, s / 2), (s, s, s), T(m))
            f = s * 0.08
            for dx in (-1, 1):
                for dy in (-1, 1):
                    mb.box((dx * (s - f) / 2, dy * (s - f) / 2 - 0.004 * dy, s / 2), (f * 1.02, f * 1.02, s * 1.01), T("planks_dark"))
        else:
            _crate(mb, (0, 0, 0), s)
    o = mb.build(nm("Generic"), R)
    # recentre: base on z=0, centred on x/y
    lo = Vector((min(v.co.x for v in o.data.vertices), min(v.co.y for v in o.data.vertices), min(v.co.z for v in o.data.vertices)))
    hi = Vector((max(v.co.x for v in o.data.vertices), max(v.co.y for v in o.data.vertices), max(v.co.z for v in o.data.vertices)))
    off = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in o.data.vertices:
        v.co -= off
    return hi.z - lo.z
