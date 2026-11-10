"""World sets (v0.3 look): complete low-poly pixel-art environments around a flat stage.

    import abs_world as W
    S = W.WORLDS["forest"](scene)   # -> {"anchors", "cams", "world", "stage"}

Stage convention (episode builder): host stands at anchors["host"] ~(-0.9, 0.3, 0) facing -Y (camera looks +Y);
props go to anchors center/left/right/back/front. The rect x[-4, 5] y[-1.5, 6] is flat (z=0) and clutter-free;
everything around it (all sides, incl. behind the camera at -Y) is environment. Indoor sets: walls + ceiling at 3.4 m.
"""
import math

import bpy
import numpy as np
from mathutils import Euler, Vector

import abs_flora as F
import abs_pix as X

R = math.radians
STAGE_RECT = (-4.6, 5.6, -2.0, 6.4)   # flat area (a bit larger than the promised x[-4,5] y[-1.5,6])

try:  # optional man-made kit from the other agent (not required)
    import abs_kit as K  # noqa: F401
except Exception:  # pragma: no cover
    K = None


# ------------------------------------------------------------------ shared
def _base_anchors(**over):
    a = {"host": (-0.9, 0.3, 0.0), "center": (1.2, 1.2, 0.0), "left": (-2.6, 1.6, 0.0), "right": (3.2, 1.8, 0.0),
         "back": (0.6, 4.5, 0.0), "front": (0.6, -0.4, 0.0)}
    a.update(over)
    return a


def _base_cams(**over):
    c = {
        "wide": {"pos": (0.7, -6.2, 2.3), "target": (0.7, 2.5, 1.45), "end": (0.7, -5.6, 2.2), "lens": 20},
        "host": {"pos": (-0.72, -1.75, 1.38), "target": (-0.9, 0.3, 1.24), "end": (-0.72, -1.6, 1.37), "lens": 50},
        "host_full": {"pos": (-0.6, -3.7, 1.05), "target": (-0.9, 0.3, 0.86), "end": (-0.6, -3.4, 1.03), "lens": 40},
        "establish": {"pos": (9.0, -15.0, 8.5), "target": (0.8, 4.0, 1.5), "end": (7.5, -13.5, 7.8), "lens": 22},
        "low": {"pos": (0.0, -3.0, 0.4), "target": (0.5, 3.0, 1.6), "lens": 20},
        "top": {"pos": (0.5, 1.5, 14.0), "target": (0.5, 1.6, 0.0), "lens": 30},
        "side_l": {"pos": (-7.5, 1.2, 1.7), "target": (1.0, 1.4, 1.2), "lens": 22},
        "side_r": {"pos": (8.5, 1.0, 1.7), "target": (0.0, 1.4, 1.2), "lens": 22},
        "ots": {"pos": (-1.6, 1.4, 1.55), "target": (1.2, 1.2, 1.0), "lens": 28},
        "reverse": {"pos": (1.0, 6.0, 1.6), "target": (-0.5, -2.0, 1.2), "lens": 22},
    }
    c.update(over)
    return c


def _result(anchors, cams, world, center=(0.5, 2.25), size=(9.0, 7.5)):
    return {"anchors": anchors, "cams": cams, "world": tuple(world), "stage": {"center": center, "size": size}}


class B:
    """Fast numpy builder for man-made parts (no bpy.ops): boxes / cylinders / prisms with per-part materials,
    built into ONE mesh object. Coordinates are local to the object; build(loc, rotz) places it."""

    def __init__(self):
        self.g = F.Geo()
        self.mats, self.idx = [], {}

    def _mi(self, m):
        if isinstance(m, str) or isinstance(m, tuple):
            m = X.mat(m)
        if m.name not in self.idx:
            self.idx[m.name] = len(self.mats)
            self.mats.append(m)
        return self.idx[m.name]

    def box(self, c, size, m, rot=(0, 0, 0)):
        mi = self._mi(m)
        hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
        M = Euler(rot).to_matrix() if any(rot) else None
        vs = []
        for (x, y, z) in [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]:
            v = Vector((x * hx, y * hy, z * hz))
            if M is not None:
                v = M @ v
            vs.append((c[0] + v.x, c[1] + v.y, c[2] + v.z))
        fs = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
        self.g.add(vs, fs, mi)

    def cyl(self, c, r, h, m, verts=8, r2=None, axis="z", cap=True):
        """Cylinder/cone centred at c, length h along axis ('x','y','z')."""
        mi = self._mi(m)
        d = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
        p0 = np.asarray(c) - np.asarray(d) * h / 2
        p1 = np.asarray(c) + np.asarray(d) * h / 2
        self.g.cyl(p0, p1, r, r if r2 is None else r2, mi, verts, cap=cap)

    def seg(self, p0, p1, r, m, verts=6, r2=None):
        self.g.cyl(p0, p1, r, r if r2 is None else r2, self._mi(m), verts, cap=True)

    def prism(self, profile, depth, m, axis="x", loc=(0, 0, 0)):
        """Profile [(u, z)] extruded along axis by depth (centred at loc). axis 'x': u = y; axis 'y': u = x."""
        mi = self._mi(m)
        n = len(profile)
        vs = []
        for s in (-depth / 2, depth / 2):
            for (u, z) in profile:
                if axis == "x":
                    vs.append((loc[0] + s, loc[1] + u, loc[2] + z))
                else:
                    vs.append((loc[0] + u, loc[1] + s, loc[2] + z))
        fs = [list(range(n))[::-1], list(range(n, 2 * n))]
        for i in range(n):
            j = (i + 1) % n
            fs.append([i, j, n + j, n + i])
        self.g.add(vs, fs, mi)

    def ico(self, c, radii, m, sub=1, jitter=0.0, seed=0):
        self.g.ico(c, radii, self._mi(m), sub=sub, jitter=jitter, seed=seed)

    def card(self, c, w, h, normal, m, up=(0, 0, 1)):
        self.g.card(c, w, h, normal, up=up, mi=self._mi(m))

    def gable_roof(self, w, d, wall_h, roof_h, wall_m, roof_m, overhang=0.35, t=0.16, ridge="x", c=(0, 0)):
        """Triangular gable (wall material) + two roof slabs; ridge along local x or y."""
        cx, cy = c
        if ridge == "x":
            self.prism([(-d / 2, wall_h), (d / 2, wall_h), (0, wall_h + roof_h)], w, wall_m, "x", (cx, cy, 0))
            ang = math.atan2(roof_h, d / 2)
            L = math.hypot(roof_h, d / 2) + overhang
            for s in (-1, 1):
                ym = s * (d / 4) + s * overhang / 2 * math.cos(ang) * 0.9
                zm = wall_h + roof_h / 2 - overhang / 2 * math.sin(ang) + t * 0.5
                self.box((cx, cy + ym, zm), (w + overhang * 2, L, t), roof_m, rot=(-s * ang, 0, 0))
        else:
            self.prism([(-w / 2, wall_h), (w / 2, wall_h), (0, wall_h + roof_h)], d, wall_m, "y", (cx, cy, 0))
            ang = math.atan2(roof_h, w / 2)
            L = math.hypot(roof_h, w / 2) + overhang
            for s in (-1, 1):
                xm = s * (w / 4) + s * overhang / 2 * math.cos(ang) * 0.9
                zm = wall_h + roof_h / 2 - overhang / 2 * math.sin(ang) + t * 0.5
                self.box((cx + xm, cy, zm), (L, d + overhang * 2, t), roof_m, rot=(0, s * ang, 0))

    def window(self, c, w, h, face, frame="#f1ece2", glass="glass", sill=True):
        """Window on a wall whose outward normal is face in {'-y','+y','-x','+x'}; c = centre on the wall plane."""
        sx = {"-y": (0, -1), "+y": (0, 1), "-x": (-1, 0), "+x": (1, 0)}[face]
        if sx[1]:
            self.box(c, (w + 0.16, 0.1, h + 0.16), frame)
            self.box((c[0], c[1] + sx[1] * 0.03, c[2]), (w, 0.1, h), glass)
            self.box((c[0], c[1] + sx[1] * 0.07, c[2]), (0.06, 0.04, h), frame)
            self.box((c[0], c[1] + sx[1] * 0.07, c[2]), (w, 0.04, 0.06), frame)
            if sill:
                self.box((c[0], c[1] + sx[1] * 0.1, c[2] - h / 2 - 0.08), (w + 0.3, 0.2, 0.08), frame)
        else:
            self.box(c, (0.1, w + 0.16, h + 0.16), frame)
            self.box((c[0] + sx[0] * 0.03, c[1], c[2]), (0.1, w, h), glass)
            self.box((c[0] + sx[0] * 0.07, c[1], c[2]), (0.04, 0.06, h), frame)
            self.box((c[0] + sx[0] * 0.07, c[1], c[2]), (0.04, w, 0.06), frame)
            if sill:
                self.box((c[0] + sx[0] * 0.1, c[1], c[2] - h / 2 - 0.08), (0.2, w + 0.3, 0.08), frame)

    def build(self, name, loc=(0, 0, 0), rotz=0.0, scale=1.0):
        me = self.g.build(name, self.mats)
        o = F.obj(me, name, loc)
        o.rotation_euler = (0, 0, rotz)
        if scale != 1.0:
            o.scale = (scale, scale, scale)
        return o


def gz(hfn, x, y):
    return float(hfn(np.array(float(x)), np.array(float(y))))


def build_barn(loc, rotz=0.0, s=1.0, name="Barn"):
    """Red barn (reference): board walls, white trim, big X doors, grey roof. Front faces local -Y."""
    b = B()
    w, d, wh, rh = 7.0, 5.5, 3.6, 2.3
    red, white = "planks_red", "#f1ece2"
    b.box((0, 0, wh / 2), (w, d, wh), red)
    b.gable_roof(w, d, wh, rh, red, "roof_grey", ridge="y")
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box((sx * (w / 2 + 0.02), sy * (d / 2 + 0.02), wh / 2), (0.16, 0.16, wh), white)
    dw, dh = 2.6, 2.8
    yf = -d / 2 - 0.05
    b.box((0, yf, dh / 2), (dw, 0.1, dh), red)
    b.box((0, yf - 0.02, dh), (dw + 0.2, 0.12, 0.16), white)
    for sx in (-1, 1):
        b.box((sx * dw / 2, yf - 0.02, dh / 2), (0.14, 0.12, dh), white)
        b.box((sx * dw / 4, yf - 0.05, dh / 2), (0.12, 0.08, math.hypot(dw / 2, dh) - 0.2), white,
              rot=(0, sx * math.atan2(dw / 2, dh), 0))
    b.box((0, yf, wh + 0.9), (1.1, 0.1, 1.0), "planks_dark")
    b.box((0, yf - 0.02, wh + 0.9), (1.3, 0.08, 1.2), white)
    b.box((0, 0, 0.0), (w + 0.2, d + 0.2, 0.5), "stone_brick")
    for sx in (-1, 1):
        b.window((sx * (w / 2 + 0.03), 0.6, 2.2), 0.9, 0.9, "+x" if sx > 0 else "-x", frame=white, sill=False)
    b.box((w / 2 + 0.9, -d / 2 + 0.4, 0.4), (0.8, 0.8, 0.8), "hay")
    b.box((w / 2 + 0.7, -d / 2 + 1.3, 0.4), (0.8, 0.8, 0.8), "hay")
    return b.build(name, loc, rotz, s)


def _smoke(loc, n=6, name="Smoke"):
    """Pixel smoke puffs rising from a chimney, looping (driver on z/x)."""
    out = []
    for k in range(n):
        sz = 0.35 + 0.1 * k
        b = B()
        b.box((0, 0, 0), (sz, sz, sz), X.mat("#eef0f2", name="smoke_m", shadow=0.85))
        o = b.build(f"{name}{k}", loc)
        period = 150
        ph = k * period / n
        for i, expr in ((2, f"{loc[2]:.3f} + ((frame+{ph:.1f}) % {period}) * 0.025"),
                        (0, f"{loc[0]:.3f} + ((frame+{ph:.1f}) % {period}) * 0.006")):
            fc = o.driver_add("location", i)
            fc.driver.type = "SCRIPTED"
            fc.driver.expression = expr
        out.append(o)
    return out


def build_bakery(loc, rotz=0.0, name="Bakery"):
    """Bakery (reference): grey clapboard, striped awning, green door, chimney with smoke. Front = local -Y."""
    b = B()
    w, d, wh, rh = 6.0, 4.6, 3.0, 1.7
    wall = "siding_grey" if "siding_grey" in X.GEN else "planks_light"
    b.box((0, 0, wh / 2), (w, d, wh), wall)
    b.gable_roof(w, d, wh, rh, wall, "roof_grey", ridge="x")
    yf = -d / 2
    b.box((1.5, yf - 0.04, 1.05), (0.95, 0.1, 2.1), "#2f7a4a")
    b.box((1.5, yf - 0.06, 2.15), (1.15, 0.1, 0.12), "#f4f1ea")
    b.box((1.85, yf - 0.1, 1.0), (0.08, 0.06, 0.08), "gold")
    b.window((-1.2, yf - 0.02, 1.4), 1.9, 1.1, "-y", frame="#f4f1ea")
    b.window((-1.2, -yf + 0.02, 1.5), 1.2, 0.9, "+y")
    for sx in (-1, 1):
        b.window((sx * (w / 2 + 0.02), 0, 1.5), 1.0, 0.9, "+x" if sx > 0 else "-x")
    aw = "awning_red" if "awning_red" in X.GEN else "awning"
    b.box((-1.2, yf - 0.55, 2.35), (2.5, 1.15, 0.08), aw, rot=(R(-22), 0, 0))
    b.box((-1.2, yf - 1.08, 2.08), (2.5, 0.06, 0.26), aw)
    b.box((0, yf - 0.06, wh - 0.25), (2.4, 0.08, 0.5), "#f4efe6")
    b.box((0, yf - 0.1, wh - 0.25), (2.1, 0.06, 0.32), "#8a3b2e")
    b.box((1.6, 0.6, wh + rh), (0.6, 0.6, 2.2), "red_brick")
    b.box((0, 0, 0.05), (w + 0.2, d + 0.2, 0.3), "stone_brick")
    o = b.build(name, loc, rotz)
    cz, sz = math.cos(rotz), math.sin(rotz)
    _smoke((loc[0] + 1.6 * cz - 0.6 * sz, loc[1] + 1.6 * sz + 0.6 * cz, loc[2] + wh + rh + 1.4))
    return o


def build_cabin(loc, rotz=0.0, name="Cabin", roof="roof_red"):
    b = B()
    w, d, wh, rh = 5.0, 4.0, 2.6, 1.6
    b.box((0, 0, wh / 2), (w, d, wh), "log_h" if "log_h" in X.GEN else "log")
    b.gable_roof(w, d, wh, rh, "planks_dark", roof, overhang=0.45, ridge="x")
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cyl((sx * w / 2, sy * d / 2, wh / 2), 0.17, wh, "log", verts=6)
    b.box((0.9, -d / 2 - 0.04, 1.0), (0.9, 0.1, 2.0), "planks_dark")
    b.window((-1.0, -d / 2 - 0.02, 1.4), 1.0, 0.9, "-y")
    b.window((0, d / 2 + 0.02, 1.4), 1.0, 0.9, "+y")
    b.box((-1.5, 0.7, wh + rh), (0.5, 0.5, 1.8), "stone_brick")
    b.box((0, -d / 2 - 0.9, 0.1), (w, 1.6, 0.2), "planks")
    return b.build(name, loc, rotz)


def build_house(loc, rotz=0.0, name="House", wall="plaster", roof="roof_red", w=5.5, d=4.5, wh=3.0, rh=1.8,
                floors=1, flat=False):
    b = B()
    H = wh * floors
    b.box((0, 0, H / 2), (w, d, H), wall)
    if flat:
        b.box((0, 0, H + 0.15), (w + 0.2, d + 0.2, 0.3), roof)
    else:
        b.gable_roof(w, d, H, rh, wall, roof, ridge="x")
    b.box((w * 0.25, -d / 2 - 0.04, 1.0), (0.9, 0.1, 2.0), "planks_dark")
    for fl in range(floors):
        z = 1.6 + fl * wh
        b.window((-w * 0.2, -d / 2 - 0.02, z), 1.0, 1.0, "-y")
        if fl:
            b.window((w * 0.25, -d / 2 - 0.02, z), 1.0, 1.0, "-y")
        b.window((-w * 0.2, d / 2 + 0.02, z), 1.0, 1.0, "+y")
        b.window((w / 2 + 0.02, 0, z), 1.0, 1.0, "+x")
        b.window((-w / 2 - 0.02, 0, z), 1.0, 1.0, "-x")
    return b.build(name, loc, rotz)


def build_dock(x, y0, y1, z=0.25, w=1.8, name="Dock"):
    b = B()
    b.box((x, (y0 + y1) / 2, z), (w, y1 - y0, 0.12), "planks")
    n = int((y1 - y0) / 2.2) + 1
    for i in range(n):
        yy = y0 + 0.3 + i * (y1 - y0 - 0.6) / max(1, n - 1)
        for sx in (-1, 1):
            hh = 2.2 + 0.5 * (i == n - 1)
            b.cyl((x + sx * (w / 2 - 0.05), yy, z - 1.6 + hh / 2), 0.11, hh, "log", verts=6)
    for sx in (-1, 1):
        b.box((x + sx * (w / 2 - 0.05), (y0 + y1) / 2, z - 0.15), (0.12, y1 - y0, 0.18), "planks_dark")
    return b.build(name)


def build_boat(loc, rotz=0.0, name="Boat", L=3.6, W=1.2):
    b = B()
    prof = [(-L / 2, 0.45), (-L / 2 + 0.5, 0.0), (L / 2 - 0.5, 0.0), (L / 2, 0.45), (L / 2, 0.55), (-L / 2, 0.55)]
    for sy in (-1, 1):
        b.prism(prof, 0.1, "planks", axis="y", loc=(0, sy * W / 2, 0))
    b.box((0, 0, 0.05), (L - 1.0, W, 0.1), "planks_dark")
    b.box((0.2, 0, 0.32), (0.4, W, 0.08), "planks")
    for sx in (-1, 1):
        b.box((sx * (L / 2 - 0.05), 0, 0.45), (0.1, W, 0.2), "planks")
    return b.build(name, loc, rotz)


def build_fence(pts, name="Fence", h=1.0, m="planks_light"):
    b = B()
    for i in range(len(pts) - 1):
        (x0, y0, z0), (x1, y1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        a = math.atan2(y1 - y0, x1 - x0)
        n = max(1, int(L / 1.6))
        for k in range(n + 1):
            t = k / n
            b.box((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z0 + (z1 - z0) * t + h / 2 - 0.1), (0.14, 0.14, h + 0.2), m)
        for zz in (0.45, 0.85):
            b.box(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2 + zz * h), (L, 0.07, 0.12), m, rot=(0, 0, a))
    return b.build(name)


def _sky(sc, sky, fog, sun_dir=(58, 0, -62), fog_start=14.0, fog_density=0.012, clouds=8, sun_az=28, sun_el=30,
         dist=110.0, back=True, sun=True):
    X.setup_look(sc, sky=sky, fog=fog, sun_dir=sun_dir, fog_start=fog_start, fog_density=fog_density)
    if sun:
        sp = (math.sin(R(sun_az)) * dist, dist * 0.9, math.sin(R(sun_el)) * dist)
        b = B()
        b.cyl((0, 0, 0), 3.4, 0.1, X.mat("#ffe7a3", name="sun_disc", emit=True, fog=False), verts=8, axis="y")
        b.cyl((0, 0.3, 0), 4.3, 0.1, X.mat("#f6c86a", name="sun_ring", emit=True, fog=False), verts=8, axis="y")
        b.build("SunDisc", sp)
    _clouds_only((0, dist, 0), clouds, 3)
    if back:
        _clouds_only((0, -dist, 0), clouds - 2, 11)
        _clouds_only((dist, 0, 0), 4, 12)
        _clouds_only((-dist, 0, 0), 4, 13)


def _clouds_only(center, n, seed):
    """Blocky white clouds on a far ring segment (camera-facing slabs)."""
    r = np.random.default_rng(seed)
    cm = X.mat("#ffffff", name="cloud", emit=True, fog=False)
    cs = X.mat("#e3ebf7", name="cloud_shade", emit=True, fog=False)
    side = abs(center[0]) > abs(center[1])
    b = B()
    for i in range(n):
        u = r.uniform(-70, 70)
        z = r.uniform(26, 48)
        w = r.uniform(9, 18)
        dd = r.uniform(-10, 10)
        for k in range(int(r.integers(2, 4))):
            bw = w * r.uniform(0.4, 0.8)
            du = r.uniform(-w / 2, w / 2)
            hh = 2.0 + r.uniform(0, 1.2)
            if side:
                b.box((center[0] + dd, u + du, z + k * 1.3), (3.0, bw, hh), cm)
            else:
                b.box((u + du, center[1] + dd, z + k * 1.3), (bw, 3.0, hh), cm)
        if side:
            b.box((center[0] + dd + 0.5, u, z - 0.7), (3.0, w * 1.1, 0.9), cs)
        else:
            b.box((u, center[1] + dd + 0.5, z - 0.7), (w * 1.1, 3.0, 0.9), cs)
    return b.build(f"Clouds{seed}")


def _register_tex():
    G = X.GEN
    G.setdefault("awning", lambda: X._stripes("#d8473a", "#f4efe6", 16, 4, vertical=True))
    G.setdefault("awning_green", lambda: X._stripes("#3f8f5a", "#f4efe6", 16, 4, vertical=True))
    G.setdefault("sign_bakery", lambda: X._noise_tex("#6b4a2e", 16, 4, 70, spread=0.12))
    G.setdefault("path_gravel", lambda: X._noise_tex("#c9b48e", 32, 4, 71, spread=0.16,
                                                     specks=[("#a8936c", 30), ("#e2d2ad", 20)]))


_register_tex()


# ------------------------------------------------------------------ FOREST (reference: lake, shore, dock, barn)
def _veg_kit(dark=False):
    """Shared vegetation prototypes for green sets."""
    k = {}
    k["round"] = [F.tree_round(s, h=8.0 + (s % 3) * 1.5, crown_r=2.8 + (s % 2) * 0.7,
                               leaf=("leafclump", "leafclump_light", "leafclump_dark", "leafclump")[s % 4],
                               core=("leaves_core", "leaves_core_light", "leaves_core", "leaves_core")[s % 4])
                  for s in range(4)]
    k["tall"] = [F.tree_tall(10 + s, h=11.0 + s * 1.5, crown_r=2.3) for s in range(3)]
    k["pine"] = [F.tree_pine(20 + s, h=9 + s * 2.5, r0=2.3 + s * 0.4) for s in range(2)]
    k["birch"] = [F.tree_birch(30 + s, h=8 + s) for s in range(2)]
    k["bush"] = [F.bush(40 + s, 0.8 + 0.25 * s, leaf=("leafclump", "leafclump_light", "leafclump_dark")[s % 3])
                 for s in range(3)]
    k["fbush"] = [F.bush(45, 0.7, flowers="#f2c2d8"), F.bush(46, 0.75, leaf="leafclump_light", flowers="#fff3a8")]
    k["far"] = [F.far_tree_blob(50 + s, h=9 + s * 2, r0=3.0 + s * 0.5,
                                core=("leaves_core", "pine_solid", "leaves_core_light")[s % 3]) for s in range(3)]
    k["tufts"] = [F.clump("grass_blades", 0.55, 0.42, 2, 64), F.clump("grass_blades", 0.7, 0.5, 3, 67),
                  F.clump("flowers_warm", 0.5, 0.38, 2, 65), F.clump("flowers_cool", 0.5, 0.38, 2, 66)]
    k["rocks"] = [F.rock(70 + s, (1.0 + s * 0.5, 0.8 + s * 0.4, 0.6 + s * 0.3)) for s in range(3)]
    k["trees"] = k["round"] + k["tall"] + k["pine"] + k["birch"]
    k["tw"] = [3, 3, 3, 3, 2.5, 2.5, 2.5, 1.0, 1.0, 1.0, 1.0]
    return k


def forest(sc):
    _sky(sc, ("#5d9fe6", "#d6e8f7"), "#d6e8f7", fog_start=18, fog_density=0.011)
    WL = -0.35
    LC, LR = (1.0, 17.0), (30.0, 8.0)        # lake ellipse: near shore y=9, far shore y=25

    def lake_d(x, y):
        nx, ny = (x - LC[0]) / LR[0], (y - LC[1]) / LR[1]
        return (np.sqrt(nx * nx + ny * ny) - 1.0) * LR[1]

    def hfn(x, y):
        d = lake_d(x, y)
        st = F.flat_stage(x, y, STAGE_RECT, 3.0)
        rr = np.hypot(x - 0.5, y - 4.0)
        out = WL + 0.35 * F.smoothstep(0.0, 2.6, d) + 0.6 * F.smoothstep(2.8, 4.2, d) * (y > LC[1])
        out = out + (1 - st) * (0.7 * F.fbm(x, y, 3, 2, 9.0) * F.smoothstep(2, 8, d)
                                + F.smoothstep(40, 120, rr) * (10 + 6 * F.fbm(x, y, 4, 2, 30.0)))
        inside = WL - 0.25 - 1.8 * F.smoothstep(0.0, 5.0, -d)
        z = np.where(d < 0, inside, out)
        return z * (1 - st)

    def path_x(y):
        return np.interp(y, [-40, -12, -4, 2, 6.5], [-8, -4.5, 6.5, 6.8, 7.2])

    def mfn(x, y, z):
        d = lake_d(x, y)
        idx = np.zeros_like(x, dtype=np.int32)                     # grass
        idx = np.where((d < 3.0) & (z < 0.12), 1, idx)             # sand beach
        idx = np.where((z < WL + 0.1), 2, idx)                     # wet sand at the waterline
        idx = np.where(z < WL - 0.7, 3, idx)                       # lake bed
        idx = np.where((np.abs(x - path_x(y)) < 0.7) & (y < 6.8) & (idx == 0), 4, idx)   # path to the dock
        idx = np.where((idx == 0) & (np.hypot(x - 0.5, y - 4) > 55), 5, idx)
        # sandy patch on the stage (reference: sandy shore in front of the grass)
        idx = np.where((y > 3.5 - 0.6 * np.sin(x * 0.7)) & (idx == 0) & (y < 7), 1, idx)
        return idx

    xs = F.axis(170, 16, 0.33, 7.0, center=0.5)
    ys = F.axis(170, 16, 0.33, 7.0, center=3.0)
    F.terrain("Ground", xs, ys, hfn,
              [X.mat("grass_lush"), X.mat("sand"), X.mat("sand_wet"), X.mat("mud"), X.mat("dirt"), X.mat("grass_dark")],
              mfn)
    F.water("Lake", (LC[0], LC[1], WL), (LR[0] * 2 + 6, LR[1] * 2 + 6), opacity=0.8)

    # ---- man-made (before scattering so trees avoid them)
    build_dock(7.6, 6.0, 15.0, z=0.22)
    build_boat((9.1, 12.8, WL + 0.02), R(92))
    build_barn((-12.0, 31.0, gz(hfn, -12, 31)), R(10))
    build_fence([(-17.5, 28.4, gz(hfn, -17.5, 28.4)), (-8.0, 28.0, gz(hfn, -8, 28)), (-6.5, 31.0, gz(hfn, -6.5, 31))])
    build_bakery((11.0, 30.0, gz(hfn, 11, 30)), R(-12))
    build_cabin((2.5, -15.0, gz(hfn, 2.5, -15)), R(180))
    build_barn((-15.5, 4.0, gz(hfn, -15.5, 4)), R(-90), s=0.9, name="Barn2")
    build_house((16.5, 3.0, gz(hfn, 16.5, 3)), R(90), name="HouseR", wall="planks_light")
    bld = [(-17, -7, 26.5, 36), (6.5, 15.5, 26.5, 34), (-1, 6, -19, -11.5), (-20, -11, -0.5, 8.5), (12.5, 20.5, -1, 7)]

    V = _veg_kit()
    trees, tw = V["trees"], V["tw"]
    stage_av = (STAGE_RECT[0] - 0.8, STAGE_RECT[1] + 0.8, STAGE_RECT[2] - 0.8, STAGE_RECT[3] + 0.4)
    dock_av = (6.0, 10.5, 4.0, 16.5)
    path_ok = lambda x, y: abs(x - path_x(y)) > 1.6  # noqa: E731
    on_land = lambda m: (lambda x, y: lake_d(x, y) > m and path_ok(x, y))  # noqa: E731
    av = [stage_av, dock_av] + bld + _cam_clear(_base_cams())
    # far shore tree line (dense, several rows)
    F.scatter(trees, (-50, 50, 28.0, 56), 170, 1, avoid=av, zfn=hfn, mind=2.5, accept=on_land(3.6), scale=(0.9, 1.4),
              weights=tw, sink=0.2)
    F.scatter(V["bush"] + V["fbush"], (-40, 40, 26.0, 30), 45, 2, avoid=av, zfn=hfn, accept=on_land(2.9), scale=(0.9, 1.6))
    # left / right banks
    F.scatter(trees, (-60, -7.5, -14, 30), 130, 3, avoid=av, zfn=hfn, mind=2.7, accept=on_land(2.5),
              scale=(0.85, 1.3), weights=tw, sink=0.2)
    F.scatter(trees, (10.0, 60, -14, 30), 130, 4, avoid=av, zfn=hfn, mind=2.7, accept=on_land(2.5),
              scale=(0.85, 1.3), weights=tw, sink=0.2)
    # behind the camera
    F.scatter(trees, (-55, 55, -60, -8.5), 170, 5, avoid=av, zfn=hfn, mind=3.0, accept=on_land(3), scale=(0.85, 1.3),
              weights=tw, sink=0.2)
    # stage frame: bushes + trees just outside the clearing
    F.scatter(V["bush"] + V["fbush"], (-10, 11, -8, 8.0), 36, 6, avoid=av + [(-3.5, 4.5, -11, -2.6)], zfn=hfn,
              accept=on_land(2.0), scale=(0.9, 1.6), mind=1.3)
    F.scatter(V["round"] + V["birch"], (-11, -5.8, -7, 7.5), 7, 16, avoid=av, zfn=hfn, mind=3.2, accept=on_land(2.5),
              scale=(0.9, 1.15), sink=0.2)
    F.scatter(V["round"] + V["tall"], (6.5, 12, -7, 5.0), 6, 17, avoid=av, zfn=hfn, mind=3.2, accept=on_land(2.5),
              scale=(0.9, 1.15), sink=0.2)
    # far hills ring
    F.scatter(V["far"], (-165, 165, -165, 165), 460, 7, zfn=hfn, mind=6,
              accept=lambda x, y: np.hypot(x - 0.5, y - 4) > 54 and lake_d(x, y) > 4, scale=(0.9, 1.6), sink=0.4)
    # shore + water details
    reeds = [F.clump("reed_blades", 1.0, 1.7, 3, 60 + s) for s in range(2)]
    weed = [F.clump("seaweed", 0.5, 1.4, 2, 62 + s, nrm_up=0.2) for s in range(2)]
    F.scatter(reeds, (-28, 30, 6, 27), 80, 8, zfn=hfn, avoid=[dock_av],
              accept=lambda x, y: -1.3 < lake_d(x, y) < 0.4 and not (-4.5 < x < 9.5 and y < 12), scale=(0.8, 1.3))
    F.scatter(reeds, (-9, -4.8, 7, 11), 7, 18, zfn=hfn, accept=lambda x, y: -1.2 < lake_d(x, y) < 0.3, scale=(0.9, 1.2))
    F.scatter(weed, (-25, 27, 8, 26), 80, 9, zfn=hfn, accept=lambda x, y: -6 < lake_d(x, y) < -1.2, scale=(0.8, 1.5))
    F.scatter(V["tufts"], (-30, 30, -25, 34), 420, 10, zfn=hfn, accept=on_land(1.0), avoid=[stage_av], scale=(0.8, 1.4))
    F.scatter(V["tufts"][:2], STAGE_RECT, 30, 11, zfn=hfn,
              accept=lambda x, y: path_ok(x, y) and not (-4 < x < 5 and -1.5 < y < 6) and y > -1.5, scale=(0.7, 1.0))
    F.scatter(V["rocks"], (-30, 30, 5, 30), 26, 12, zfn=hfn, accept=lambda x, y: -0.6 < lake_d(x, y) < 2.2,
              avoid=[stage_av, dock_av], scale=(0.5, 1.2), sink=0.15)

    anchors = _base_anchors(dock=(7.6, 10.0, 0.28), shore=(1.0, 8.0, -0.2), boat=(9.1, 12.8, WL + 0.1),
                            water=(1.0, 14.0, WL))
    cams = _base_cams()
    return _result(anchors, cams, X.hx("#a9cdf1"))


WORLDS = {"forest": forest}


# ------------------------------------------------------------------ DESERT (ancient Egypt: wadi mouth, Nile, village)
def _kit(name, params, loc, yaw=0.0, s=1.0):
    """abs_kit prop as set dressing (None if the kit module is missing)."""
    if K is None:
        return None
    try:
        root = K.build(name, params)
    except Exception as e:  # pragma: no cover
        print("[world] kit", name, "failed:", e)
        return None
    root.location = loc
    root.rotation_euler = (0, 0, R(yaw))
    root.scale = (s, s, s)
    return root


def _kit_mesh(name, params, label):
    """Bake a kit prop into ONE static mesh datablock (for scatter/linked duplicates). None if unavailable."""
    if K is None:
        return None
    root = K.build(name, params)
    bpy.context.view_layer.update()
    kids = [o for o in root.children_recursive if o.type == "MESH"]
    for o in kids:
        mw = o.matrix_world.copy()
        o.animation_data_clear()
        o.parent = None
        o.matrix_world = mw
    bpy.ops.object.select_all(action="DESELECT")
    for o in kids:
        o.select_set(True)
    bpy.context.view_layer.objects.active = kids[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.join()
    o = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    me = o.data
    me.name = label
    for x in list(root.children_recursive):
        if x is not o:
            bpy.data.objects.remove(x, do_unlink=True)
    bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.objects.remove(root, do_unlink=True)
    return me


def _ruins(cx, cy, seed=0, name="Ruins"):
    """Broken limestone colonnade: standing column stumps, fallen drums, low wall, a lintel block."""
    r = np.random.default_rng(seed)
    b = B()
    for i in range(5):
        x = cx + i * 1.6
        h = r.choice([3.2, 2.4, 1.3, 0.6, 2.9])
        b.cyl((x, cy, h / 2), 0.36, h, "stone_block", verts=10)
        b.box((x, cy, 0.12), (0.95, 0.95, 0.24), "stone_block")
        if h > 3:
            b.box((x, cy, h + 0.15), (0.95, 0.95, 0.3), "stone_block")
    b.box((cx + 0.8, cy, 3.5), (2.6, 0.8, 0.5), "stone_block")
    for i in range(4):
        b.cyl((cx + r.uniform(0, 6), cy - r.uniform(1.2, 2.6), 0.3), 0.34, 0.75, "stone_block", verts=10, axis="x")
    b.box((cx + 3.0, cy + 1.6, 0.5), (7.5, 0.7, 1.0), "stone_brick")
    b.box((cx + 1.0, cy + 1.6, 1.25), (2.6, 0.7, 0.5), "stone_brick")
    return b.build(name)


def _cam_clear(cams, r=2.6):
    """Rects around every camera preset position (no trees/houses right in front of a lens)."""
    out = []
    for c in cams.values():
        x, y = c["pos"][0], c["pos"][1]
        tx, ty = c["target"][0], c["target"][1]
        out.append((x - r, x + r, y - r, y + r))
        out.append((min(x, (x + tx) / 2) - 1.2, max(x, (x + tx) / 2) + 1.2, min(y, (y + ty) / 2) - 1.2, max(y, (y + ty) / 2) + 1.2))
    return out


def desert(sc):
    _sky(sc, ("#4f93e3", "#f2dfb9"), "#efdcb6", sun_dir=(55, 0, -50), fog_start=22, fog_density=0.009, clouds=5,
         sun_el=38)
    RIV = lambda y: 15.5 + 3.0 * np.sin(y / 19.0) + 1.5 * np.sin(y / 7.3)  # noqa: E731  Nile centre line x(y)
    RW = 3.6                                                                 # half width

    def riv_d(x, y):
        return np.abs(x - RIV(y)) - RW                                       # <0 in the river

    def hfn(x, y):
        st = F.flat_stage(x, y, STAGE_RECT, 3.5)
        d = riv_d(x, y)
        r0 = np.hypot(x - 0.5, y - 3.0)
        dunes = (1.2 + 2.6 * F.smoothstep(12, 60, r0)) * (0.5 + 0.5 * F.fbm(x, y, 21, 3, 14.0)) \
            + 0.9 * np.maximum(0, np.sin((x * 0.8 + y * 0.6) / 4.5 + F.fbm(x, y, 22, 2, 9.0) * 2.0))
        dunes = dunes * F.smoothstep(3.0, 14.0, d)                          # flat green banks along the river
        bank = -0.15 * F.smoothstep(2.5, 0.0, d)
        bed = -0.9 * F.smoothstep(0.0, -2.0, d)
        far = F.smoothstep(70, 150, r0) * 8.0
        z = (dunes + far) * (1 - st) + bank + bed
        return z

    def mfn(x, y, z):
        d = riv_d(x, y)
        idx = np.zeros_like(x, dtype=np.int32)                               # sand
        idx = np.where((d < 5.5) & (d > 0.6), 1, idx)                        # green bank (fields)
        idx = np.where((d <= 0.6), 2, idx)                                   # wet mud
        idx = np.where((idx == 0) & (F.fbm(x, y, 23, 2, 5.0) > 0.45), 3, idx)  # darker wind-blown sand
        idx = np.where((np.abs(x + 1.0 - 0.15 * y) < 0.9) & (y < -1.6) & (idx == 0), 4, idx)  # path
        return idx

    xs = F.axis(170, 18, 0.4, 7.0, center=0.5)
    ys = F.axis(170, 18, 0.4, 7.0, center=3.0)
    F.terrain("Ground", xs, ys, hfn,
              [X.mat("sand"), X.mat("grass_dry"), X.mat("mud"), X.mat("sand_wet"), X.mat("path_gravel")], mfn)
    # the Nile: a long animated water ribbon following the centre line
    rw = B()
    ys_r = np.linspace(-120, 140, 90)
    rows = []
    for y0 in ys_r:
        c = float(RIV(y0))
        rows.append([(c - RW - 0.2, y0, -0.32), (c + RW + 0.2, y0, -0.32)])
    me_v, me_f = [], []
    for i, rr in enumerate(rows):
        me_v += [rr[0], rr[1]]
        if i:
            a = 2 * (i - 1)
            me_f.append([a, a + 1, a + 3, a + 2])
    wm = X.mat("water_nile", name="nile_mat", anim=(0.0, 0.12), shadow=0.85)
    X.mesh("Nile", me_v, me_f, wm)

    # ---- wadi ridge behind the stage with a mouth (gap) behind the stage: a dam kit can plug it
    ridge_l = [(-90, 24), (-60, 21), (-35, 19), (-20, 18.5), (-11.5, 19.5)]
    ridge_r = [(12.0, 19.5), (11.5, 26), (9.5, 34)]
    F.cliff_band("RidgeL", ridge_l[::-1], 9.0, zfn=hfn, depth=10, tex="rock_red", cap_tex="sand", seed=31)
    F.cliff_band("RidgeL2", [(-9.5, 36), (-10.5, 28), (-11.5, 19.5)], 8.0, zfn=hfn, depth=8, tex="rock_red",
                 cap_tex="sand", seed=32)
    F.cliff_band("RidgeR", ridge_r, 8.0, zfn=hfn, depth=8, tex="rock_red", cap_tex="sand", seed=33)
    F.cliff_band("RidgeFar", [(-30, 70), (-5, 64), (25, 66), (60, 74)][::-1], 5.0, zfn=hfn, depth=12, tex="rock_red",
                 cap_tex="sand", seed=34)

    # ---- landmarks
    _kit("pyramid", {"style": "giza", "base": 26}, (-38, 95, gz(hfn, -38, 95)), 15)
    _kit("pyramid", {"style": "giza", "base": 18}, (-10, 115, gz(hfn, -10, 115)), 10)
    _kit("pyramid", {"style": "stepped", "base": 14}, (34, 105, gz(hfn, 34, 105)), -8)
    _kit("pyramid", {"style": "giza", "base": 20}, (-60, -95, gz(hfn, -60, -95)), 30)     # behind the camera
    _ruins(-14.5, 8.0, 3)
    _ruins(-9.0, -12.0, 4, name="Ruins2")
    village = [(23, 2, -95), (26, 9, -80), (22.5, 15, -100), (28, -5, -90), (25, -12, -70), (31, 4, -85),
               (-17, 1, 90), (-21, -6, 80), (-16.5, -12, 100), (6, -15, 180), (-3, -19, 170)]
    for i, (x, y, yaw) in enumerate(village):
        _kit("mudbrick_house", {"plaster": i % 2 == 0, "seed": i}, (x, y, gz(hfn, x, y)), yaw)
    _kit("workers_camp", {"seed": 5}, (8.2, 9.5, 0.0), -25)

    # ---- vegetation: palms along the river + oasis clusters; reeds/papyrus in the shallows
    palms = [m for m in (_kit_mesh("palm", {"height": 4.6 + s * 0.7, "lean": 0.1 + 0.08 * s, "seed": s}, f"palm_m{s}")
                         for s in range(4)) if m is not None] or [F.palm(s, h=6.5) for s in range(3)]
    rocks = [F.rock(80 + s, (1.0 + s * 0.6, 0.9 + s * 0.4, 0.6 + s * 0.35), tex="rock_red") for s in range(4)]
    papyrus = [F.clump("papyrus", 1.0, 2.2, 3, 90 + s) if "papyrus" in X.GEN else F.clump("reed_blades", 1.0, 1.8, 3, 90 + s)
               for s in range(2)]
    tufts = [F.clump("grass_blades", 0.6, 0.45, 2, 95), F.clump("grass_blades", 0.5, 0.35, 2, 96)]
    stage_av = (STAGE_RECT[0] - 0.6, STAGE_RECT[1] + 0.6, STAGE_RECT[2] - 0.6, STAGE_RECT[3] + 0.6)
    bld = [(x - 3.2, x + 3.2, y - 3.0, y + 3.0) for (x, y, _) in village] + [(-15.5, -6, 5, 11), (-10, -0.5, -15, -9),
                                                                              (5, 11.5, 6.5, 12.5)]
    cam_av = _cam_clear(_base_cams()) + [(-9.5, 10.5, -13, -1.6), (-9.5, 10.5, -1.6, 8)]   # keep camera spots clear
    av = [stage_av] + bld + cam_av
    on_bank = lambda lo, hi: (lambda x, y: lo < riv_d(x, y) < hi)  # noqa: E731
    F.scatter(palms, (-40, 60, -60, 90), 120, 41, avoid=av, zfn=hfn, mind=2.6, accept=on_bank(0.8, 7.5),
              scale=(0.85, 1.25), sink=0.1)
    F.scatter(palms, (-30, 12, -40, 16), 26, 42, avoid=av + [(-12, 12, 9, 40)], zfn=hfn, mind=3.0,
              accept=lambda x, y: riv_d(x, y) > 6 and (np.hypot(x + 19, y - 2) < 7 or np.hypot(x - 2, y + 17) < 8),
              scale=(0.8, 1.2), sink=0.1)
    F.scatter(palms, (-40, -11.5, 4, 19), 14, 48, avoid=av, zfn=hfn, mind=3.5, scale=(0.8, 1.2), sink=0.1)
    F.scatter(palms, (12.5, 40, 4, 19), 10, 49, avoid=av, zfn=hfn, mind=3.5, scale=(0.8, 1.2), sink=0.1)
    F.scatter(rocks, (-11, 11, 7, 19), 9, 50, zfn=hfn, scale=(0.5, 1.3), mind=2.5, sink=0.15)   # wadi floor
    F.scatter(palms[:2], (-9, 9, 10, 18), 4, 51, zfn=hfn, mind=4, scale=(0.8, 1.0), sink=0.1)
    F.scatter(palms, (-70, 70, -80, -20), 40, 43, avoid=av, zfn=hfn, mind=4, scale=(0.8, 1.2), sink=0.1)
    F.scatter(papyrus, (-20, 60, -100, 140), 220, 44, zfn=hfn, accept=on_bank(-1.2, 0.5), scale=(0.8, 1.3))
    F.scatter(tufts, (-30, 60, -60, 90), 260, 45, zfn=hfn, accept=on_bank(0.5, 5.5), avoid=av, scale=(0.8, 1.4))
    F.scatter(rocks, (-60, 60, -60, 70), 90, 46, zfn=hfn, avoid=av, accept=lambda x, y: riv_d(x, y) > 4,
              scale=(0.5, 1.6), mind=3, sink=0.15)
    F.scatter(rocks[:2], (-4.5, 5.5, -2, 6.5), 4, 47, zfn=hfn, avoid=[(-3, 4.5, -1.5, 5.8)], scale=(0.25, 0.45),
              sink=0.05)
    anchors = _base_anchors(river=(float(RIV(4.0)), 4.0, -0.3), wadi=(0.6, 13.0, 0.0), ruins=(-12.0, 8.0, 0.0),
                            village=(23.0, 6.0, 0.0))
    cams = _base_cams()
    return _result(anchors, cams, X.hx("#c9dcef"))


WORLDS["desert"] = desert


# ------------------------------------------------------------------ INDOOR sets (dollhouse rooms)
def _noshadow(o):
    try:
        o.visible_shadow = False
    except Exception:
        pass
    return o


INDOOR_WIDE = {"wide": {"pos": (0.7, -4.6, 1.6), "target": (0.7, 3.0, 1.3), "end": (0.7, -4.2, 1.58), "lens": 28}}


def _room(name, x0, x1, y0, y1, h, floor, wall, wain=None, ceil="plaster_white", sky=("#6fa8ee", "#d7e9ff"),
          windows=(), beams=True, view="forest"):
    """Four walls + ceiling around the stage. Walls/ceiling are backface-culled and cast no shadows, so outside cameras
    (establish, top) see in like a dollhouse and the sun still lights the interior. windows: [(wall, u, z, w, h)] with
    wall in 'back','left','right','front'."""
    _sky(sc_ := bpy.context.scene, sky, sky[1], fog_start=30, fog_density=0.006, clouds=6, back=True)
    X.box(f"{name}_Floor", ((x0 + x1) / 2, (y0 + y1) / 2, -0.05), (x1 - x0, y1 - y0, 0.1), X.mat(floor))
    wm = X.mat(wall, name=f"{name}_wallm", cull=True)
    T = 0.2

    def wall_box(nm_, c, size):
        o = X.box(nm_, c, size, wm)
        return _noshadow(o)

    # back (+y), front (-y), left (-x), right (+x): split around windows with simple segments
    def wall_with_windows(side, segs_axis_len, fixed, along_min, along_max, wins):
        cuts = sorted([(u - w / 2, u + w / 2, z, hh) for (s_, u, z, w, hh) in wins if s_ == side])
        a = along_min
        pieces = []
        for (ua, ub, z, hh) in cuts:
            pieces.append((a, ua, 0, h))
            pieces.append((ua, ub, 0, z - hh / 2))
            pieces.append((ua, ub, z + hh / 2, h))
            a = ub
        pieces.append((a, along_max, 0, h))
        for k, (ua, ub, za, zb) in enumerate(pieces):
            if ub - ua < 1e-3 or zb - za < 1e-3:
                continue
            if side in ("back", "front"):
                wall_box(f"{name}_W{side}{k}", ((ua + ub) / 2, fixed, (za + zb) / 2), (ub - ua, T, zb - za))
            else:
                wall_box(f"{name}_W{side}{k}", (fixed, (ua + ub) / 2, (za + zb) / 2), (T, ub - ua, zb - za))
        for (ua, ub, z, hh) in cuts:  # frames + sill + glass-less opening (outside view visible)
            fm = X.mat("planks_light", name=f"{name}_frame")
            if side in ("back", "front"):
                for zz in (z - hh / 2, z + hh / 2):
                    X.box(f"{name}_F{side}{ua:.1f}{zz:.1f}", ((ua + ub) / 2, fixed, zz), (ub - ua + 0.2, T + 0.08, 0.12), fm)
                for uu in (ua, ub):
                    X.box(f"{name}_F{side}{uu:.1f}", (uu, fixed, z), (0.12, T + 0.08, hh), fm)
                X.box(f"{name}_M{side}{ua:.1f}", ((ua + ub) / 2, fixed, z), (0.07, T * 0.6, hh), fm)
            else:
                for zz in (z - hh / 2, z + hh / 2):
                    X.box(f"{name}_F{side}{ua:.1f}{zz:.1f}", (fixed, (ua + ub) / 2, zz), (T + 0.08, ub - ua + 0.2, 0.12), fm)
                for uu in (ua, ub):
                    X.box(f"{name}_F{side}{uu:.1f}", (fixed, uu, z), (T + 0.08, 0.12, hh), fm)

    wall_with_windows("back", None, y1, x0, x1, windows)
    wall_with_windows("front", None, y0, x0, x1, windows)
    wall_with_windows("left", None, x0, y0, y1, windows)
    wall_with_windows("right", None, x1, y0, y1, windows)
    # inner faces need to face inward: the box walls are closed boxes, culling hides their outside faces only when the
    # camera is outside - fine for a dollhouse
    if wain:
        wmn = X.mat(wain, name=f"{name}_wain", cull=True)
        for (c, s_) in [(((x0 + x1) / 2, y1 - T / 2 - 0.03, 0.55), (x1 - x0, 0.06, 1.1)),
                        (((x0 + x1) / 2, y0 + T / 2 + 0.03, 0.55), (x1 - x0, 0.06, 1.1)),
                        ((x0 + T / 2 + 0.03, (y0 + y1) / 2, 0.55), (0.06, y1 - y0, 1.1)),
                        ((x1 - T / 2 - 0.03, (y0 + y1) / 2, 0.55), (0.06, y1 - y0, 1.1))]:
            _noshadow(X.box(f"{name}_wain", c, s_, wmn))
    cm = X.mat(ceil, name=f"{name}_ceil", emit=True, tint="#f3e6cf")  # faces down: never sunlit, keep it warm-bright
    cm.use_backface_culling = True
    # ceiling as a down-facing plane (seen from below only)
    vs = [(x0, y0, h), (x0, y1, h), (x1, y1, h), (x1, y0, h)]
    _noshadow(X.mesh(f"{name}_Ceiling", vs, [(0, 1, 2, 3)], cm))
    if beams:
        bm = X.mat("planks_dark", name=f"{name}_beam")
        for k in range(int((x1 - x0) / 2.2) + 1):
            xx = x0 + 1.1 + k * 2.2
            if xx < x1:
                _noshadow(X.box(f"{name}_Beam{k}", (xx, (y0 + y1) / 2, h - 0.12), (0.22, y1 - y0, 0.24), bm))
    # outside view (behind windows): a lawn + tree line + hills, so windows never show void
    X.box(f"{name}_Lawn", ((x0 + x1) / 2, (y0 + y1) / 2, -0.12), (160, 160, 0.1), X.mat("grass_lush" if "grass_lush" in X.GEN else "grass"))
    if view == "forest":
        V = _veg_kit()
        F.scatter(V["trees"], (-60, 60, -60, 60), 120, 77, avoid=[(x0 - 3, x1 + 3, y0 - 3, y1 + 3)], mind=4,
                  scale=(0.8, 1.2), weights=V["tw"], sink=0.2)
    return wm


def _shelf(b, c, w, h, d=0.35, seed=0, books=True, face="-y"):
    r = np.random.default_rng(seed)
    x, y = c
    b.box((x, y, h / 2), (w, d, h), "planks")
    n = max(2, int(h / 0.45))
    cols = ["#c8443c", "#3e64b0", "#e5b53d", "#4f9a35", "#8a5fbf", "#e8792b", "#efe2c4", "#2f6e5a"]
    for k in range(n):
        z = 0.1 + k * (h - 0.2) / n
        b.box((x, y - 0.02, z), (w - 0.06, d - 0.05, 0.04), "planks_dark")
        if books and k < n:
            xx = x - w / 2 + 0.08
            while xx < x + w / 2 - 0.12:
                bw = r.uniform(0.04, 0.09)
                bh = r.uniform(0.22, 0.34)
                if r.random() < 0.85:
                    b.box((xx + bw / 2, y - 0.03, z + 0.02 + bh / 2), (bw, d - 0.12, bh), cols[r.integers(len(cols))])
                xx += bw + 0.008
    return b


def _plant(loc, s=1.0, seed=0, name="Plant"):
    b = B()
    b.cyl((0, 0, 0.18 * s), 0.18 * s, 0.36 * s, "clay", verts=10, r2=0.22 * s)
    o = b.build(name, loc)
    me = F.bush(seed, 0.38 * s, leaf="leafclump")
    F.place(me, (loc[0], loc[1], loc[2] + 0.3 * s), 0, 0.9)
    return o


def studio(sc):
    """Cozy explainer workshop: wooden floor, warm plaster walls, beams, big windows onto a garden, shelves with
    books, desk with a lamp, chalkboard, plants, rug. Neutral default for any topic."""
    _room("Studio", -7.0, 8.0, -8.5, 8.0, 3.4, "planks", "plaster", wain="planks_light",
          windows=[("back", -4.0, 1.9, 2.6, 1.6), ("back", 4.6, 1.9, 2.6, 1.6), ("left", 2.0, 1.9, 2.4, 1.5),
                   ("right", 0.5, 1.9, 2.4, 1.5)])
    b = B()
    _shelf(b, (-1.0, 7.65), 2.2, 2.6, seed=1)
    _shelf(b, (1.4, 7.65), 2.2, 2.6, seed=2)
    _shelf(b, (-6.65, -3.0), 0.35, 2.2, seed=3)
    b.box((6.6, 4.0, 0.39), (1.6, 0.8, 0.06), "planks")                         # desk
    for dx in (-0.72, 0.72):
        for dy in (-0.32, 0.32):
            b.box((6.6 + dx, 4.0 + dy, 0.18), (0.07, 0.07, 0.36), "planks_dark")
    b.box((6.3, 4.1, 0.47), (0.35, 0.25, 0.1), "#c8443c")
    b.cyl((6.95, 4.15, 0.62), 0.02, 0.4, "metal", verts=6)
    b.cyl((6.95, 4.05, 0.84), 0.12, 0.14, "#e5b53d", verts=8, r2=0.05)
    b.box((-3.4, 7.85, 1.75), (2.4, 0.06, 1.3), "planks_dark")                  # chalkboard frame (between shelves)
    b.box((-3.4, 7.8, 1.75), (2.2, 0.05, 1.1), "chalkboard")
    b.box((0.4, 2.0, 0.008), (5.0, 3.6, 0.016), "carpet")                       # rug
    b.box((-5.5, 6.8, 0.35), (1.6, 0.8, 0.7), "planks")                         # workbench + tools
    b.box((-5.8, 6.8, 0.78), (0.5, 0.3, 0.16), "metal")
    b.cyl((-5.1, 6.7, 0.82), 0.12, 0.2, "clay", verts=10)
    b.build("StudioFurniture")
    for i, (x, y, s_) in enumerate([(-6.2, 7.2, 1.3), (7.2, 7.2, 1.2), (3.6, 7.4, 1.0), (-6.3, -6.5, 1.4), (7.3, -6.0, 1.3)]):
        _plant((x, y, 0.0), s_, 60 + i, name=f"Plant{i}")
    # hanging lamps (emissive, warm)
    lm = X.mat("#ffe2a0", name="lamp_glow", emit=True, fog=False)
    for i, x in enumerate((-3.0, 1.0, 5.0)):
        X.cyl(f"LampCord{i}", (x, 2.0, 3.0), 0.01, 0.8, X.mat("#3a3a3a"), verts=4)
        X.cyl(f"LampShade{i}", (x, 2.0, 2.55), 0.28, 0.22, X.mat("#2f6e5a"), verts=10, r2=0.08)
        X.ball(f"LampBulb{i}", (x, 2.0, 2.42), 0.09, lm)
    anchors = _base_anchors(shelf=(0.2, 7.0, 0.0), desk=(6.6, 4.0, 0.42), board=(-3.4, 7.0, 0.0))
    cams = _base_cams(establish={"pos": (9.5, -14.0, 9.0), "target": (0.5, 2.5, 1.0), "end": (8.5, -13.0, 8.5), "lens": 24},
                      reverse={"pos": (0.8, 6.8, 1.7), "target": (-0.5, -2.0, 1.2), "lens": 22}, **INDOOR_WIDE)
    return _result(anchors, cams, X.hx("#c9dcef"))


def classroom(sc):
    """Bright classroom: big chalkboard, rows of desks, teacher desk, windows, shelves, clock, posters."""
    _room("Class", -7.5, 8.0, -9.0, 8.0, 3.4, "floor_tiles", "plaster", wain="planks_light",
          windows=[("left", -3.0, 1.9, 2.4, 1.5), ("left", 2.5, 1.9, 2.4, 1.5), ("right", 1.0, 1.9, 2.4, 1.5)])
    b = B()
    b.box((0.5, 7.85, 1.7), (6.2, 0.08, 1.7), "planks_dark")
    b.box((0.5, 7.8, 1.7), (6.0, 0.06, 1.5), "chalkboard")
    b.box((0.5, 7.7, 0.92), (6.0, 0.12, 0.04), "planks_dark")
    b.cyl((5.2, 7.85, 2.75), 0.28, 0.06, "ceramic_white", verts=12, axis="y")
    b.box((4.6, 5.8, 0.4), (1.8, 0.8, 0.08), "planks")                          # teacher desk
    b.box((4.6, 6.15, 0.2), (1.8, 0.08, 0.4), "planks_dark")
    b.box((4.2, 5.8, 0.5), (0.3, 0.22, 0.12), "#3e64b0")
    b.ico((5.0, 5.75, 0.5), (0.06, 0.06, 0.06), "#c8443c")
    for row in range(3):                                                     # pupils' desks behind the camera side
        for col in range(4):
            x, y = -5.5 + col * 3.6, -3.5 - row * 1.8
            if -1.5 < x < 3.5 and y > -5:
                continue
            b.box((x, y, 0.38), (1.1, 0.6, 0.05), "planks_light")
            b.box((x, y + 0.25, 0.19), (1.0, 0.05, 0.38), "metal_dark")
            b.box((x, y - 0.55, 0.23), (0.45, 0.4, 0.04), "planks_light")
            b.box((x, y - 0.75, 0.45), (0.45, 0.04, 0.45), "planks_light")
    _shelf(b, (-6.0, 7.65), 2.4, 2.0, seed=5)
    _shelf(b, (7.6, -2.0), 0.35, 1.8, seed=6)
    for i, (x, c) in enumerate([(-3.5, "#e8792b"), (-2.2, "#4f9a35")]):
        b.box((x, 7.86, 2.3), (0.9, 0.04, 0.7), c)
        b.box((x, 7.84, 2.3), (0.75, 0.04, 0.55), "paper")
    b.build("ClassFurniture")
    _plant((7.0, 7.0, 0.0), 1.2, 71, "PlantC1")
    _plant((-7.0, -7.5, 0.0), 1.3, 72, "PlantC2")
    anchors = _base_anchors(board=(0.5, 7.0, 0.0), desk=(4.6, 5.8, 0.44))
    cams = _base_cams(establish={"pos": (9.5, -15.0, 9.0), "target": (0.5, 2.5, 1.0), "end": (8.5, -14.0, 8.5), "lens": 24},
                      reverse={"pos": (0.8, 6.8, 1.7), "target": (-0.5, -2.0, 1.2), "lens": 22}, **INDOOR_WIDE)
    return _result(anchors, cams, X.hx("#c9dcef"))


def kitchen(sc):
    """Home kitchen: tiled walls, counters with sink + stove, fridge, cabinets, window, table with chairs."""
    _room("Kitchen", -7.0, 7.5, -8.5, 7.5, 3.2, "floor_tiles", "wall_tiles", windows=[("back", -1.0, 1.8, 2.2, 1.2),
                                                                                    ("right", -1.0, 1.8, 2.0, 1.3)],
          beams=False)
    b = B()
    for (x0, x1) in ((-6.8, -2.3), (0.3, 5.5)):
        b.box(((x0 + x1) / 2, 7.05, 0.45), (x1 - x0, 0.7, 0.9), "planks_light")
        b.box(((x0 + x1) / 2, 7.0, 0.93), (x1 - x0 + 0.05, 0.75, 0.06), "concrete")
        b.box(((x0 + x1) / 2, 7.15, 2.3), (x1 - x0, 0.45, 0.8), "planks_light")
        k = int((x1 - x0) / 0.6)
        for i in range(k):
            xx = x0 + 0.3 + i * (x1 - x0) / k
            b.box((xx, 6.69, 0.47), ((x1 - x0) / k - 0.05, 0.03, 0.75), "planks")
            b.box((xx, 6.91, 2.3), ((x1 - x0) / k - 0.05, 0.03, 0.72), "planks")
    b.box((-1.0, 7.0, 0.92), (1.2, 0.6, 0.04), "metal")                            # sink under the window
    b.box((-1.0, 7.05, 0.45), (1.3, 0.7, 0.9), "planks_light")
    b.cyl((-1.0, 7.25, 1.1), 0.025, 0.3, "metal", verts=6)
    b.box((3.0, 7.0, 0.97), (0.9, 0.6, 0.02), "metal_dark")
    for (dx, dy) in ((-0.22, -0.13), (0.22, -0.13), (-0.22, 0.13), (0.22, 0.13)):
        b.cyl((3.0 + dx, 7.0 + dy, 0.99), 0.09, 0.02, "#2a2a2a", verts=10)
    b.cyl((2.78, 6.87, 1.08), 0.13, 0.16, "#c8443c", verts=10)
    b.box((6.6, 6.8, 1.0), (1.0, 0.8, 2.0), "ceramic_white")                      # fridge
    b.box((6.15, 6.38, 1.3), (0.04, 0.04, 0.5), "metal")
    b.box((-4.6, -3.0, 0.75), (1.8, 1.0, 0.06), "planks")                          # table + chairs
    for dx in (-0.8, 0.8):
        for dy in (-0.4, 0.4):
            b.box((-4.6 + dx, -3.0 + dy, 0.37), (0.07, 0.07, 0.74), "planks_dark")
    for dx in (-0.5, 0.5):
        for sy in (-1, 1):
            b.box((-4.6 + dx, -3.0 + sy * 0.8, 0.45), (0.42, 0.42, 0.05), "planks")
            b.box((-4.6 + dx, -3.0 + sy * 1.0, 0.75), (0.42, 0.05, 0.6), "planks")
    b.cyl((-4.6, -3.0, 0.85), 0.16, 0.14, "ceramic_white", verts=10)
    b.ico((-4.6, -3.0, 0.97), (0.06, 0.06, 0.06), "#e5b53d")
    b.build("KitchenFurniture")
    _plant((-6.4, 6.9, 0.96), 0.6, 81, "PlantK1")
    _plant((5.0, 7.0, 0.96), 0.5, 82, "PlantK2")
    anchors = _base_anchors(counter=(1.5, 6.6, 0.96), stove=(3.0, 6.4, 0.0), table=(-4.6, -3.0, 0.78))
    cams = _base_cams(establish={"pos": (9.0, -14.0, 8.5), "target": (0.5, 2.5, 1.0), "end": (8.0, -13.0, 8.0), "lens": 24},
                      reverse={"pos": (0.8, 6.0, 1.7), "target": (-0.5, -2.0, 1.2), "lens": 22}, **INDOOR_WIDE)
    return _result(anchors, cams, X.hx("#c9dcef"))


def cozy_room(sc):
    """Bedroom/living room for cat topics: window seat (cat anchors sit on it), shelves, plants, rug, bed corner."""
    _room("Cozy", -5.0, 6.0, -7.0, 2.4, 3.0, "planks", "wallpaper", wain="planks_light",
          windows=[("back", 0.6, 1.45, 1.4, 1.1), ("left", -2.0, 1.6, 1.6, 1.1)], beams=False)
    b = B()
    b.box((0.6, 2.05, 0.22), (1.6, 0.5, 0.44), "plaster_white")                    # window seat under the window
    b.box((0.6, 2.03, 0.475), (1.55, 0.46, 0.07), "fabric_red")
    b.box((1.25, 2.15, 0.6), (0.3, 0.12, 0.25), "fabric_blue")
    b.box((0.1, 0.1, 0.006), (3.2, 2.2, 0.012), "carpet")
    _shelf(b, (-2.6, 2.15), 1.6, 2.2, seed=9)
    _shelf(b, (4.2, 2.15), 1.4, 1.2, seed=10)
    b.box((4.6, -3.0, 0.3), (2.0, 2.6, 0.6), "fabric_cream")                       # bed corner
    b.box((4.6, -1.8, 0.75), (2.0, 0.15, 0.9), "planks")
    b.box((4.6, -2.3, 0.68), (1.4, 0.5, 0.18), "ceramic_white")
    b.cyl((1.45, 0.25, 0.03), 0.08, 0.06, "#3e64b0", verts=10)                    # cat bowl
    b.build("CozyFurniture")
    _plant((-1.25, 0.65, 0.0), 0.9, 91, "PlantZ1")
    _plant((5.4, 1.8, 1.2), 0.5, 92, "PlantZ2")
    anchors = _base_anchors(
        host=(-0.5, 0.5, 0.0), bench_edge=(-0.06, 1.86, 0.51), bench_left=(0.15, 1.95, 0.51), bench_mid=(0.55, 1.95, 0.51),
        bench_right=(1.0, 1.95, 0.51), floor_front=(0.45, 0.05, 0.0), floor_right=(1.1, 0.2, 0.0),
        bench_offleft=(-0.6, 1.95, 0.51), bench_offright=(1.8, 1.95, 0.51), center=(0.45, 0.25, 0.0),
        left=(-1.6, 0.6, 0.0), right=(1.6, 0.4, 0.0), back=(0.55, 1.95, 0.51), front=(0.3, -0.25, 0.0))
    cams = {
        "wide": {"pos": (-0.02, -3.2, 1.25), "target": (0.1, 1.2, 0.8), "end": (-0.02, -3.0, 1.22), "lens": 24},
        "host": {"pos": (-0.4, -1.3, 1.36), "target": (-0.5, 0.5, 1.22), "end": (-0.4, -1.15, 1.35), "lens": 45},
        "host_full": {"pos": (-0.35, -2.6, 1.0), "target": (-0.5, 0.5, 0.82), "end": (-0.35, -2.4, 1.0), "lens": 36},
        "two": {"pos": (0.5, -2.1, 1.2), "target": (0.1, 1.2, 0.85), "end": (0.45, -1.95, 1.18), "lens": 26},
        "cat": {"follow": "cat", "offset": (0.1, -0.95, 0.14), "aim": (0.0, 0.0, 0.03), "dolly": 0.12, "lens": 35},
        "card": {"follow": "cat", "offset": (0.03, -0.75, 0.1), "aim": (0.0, 0.0, 0.05), "dolly": 0.06, "lens": 38},
        "cat_low": {"follow": "cat", "offset": (0.32, -0.8, -0.04), "aim": (0.0, 0.0, 0.04), "dolly": 0.1, "lens": 30},
        "establish": {"pos": (7.0, -10.0, 6.5), "target": (0.3, 0.5, 0.8), "lens": 24},
        "reverse": {"pos": (0.6, 1.9, 1.5), "target": (-0.3, -2.0, 1.1), "lens": 22},
    }
    return _result(anchors, cams, X.hx("#c9dcef"), center=(0.4, -0.5), size=(6.0, 4.0))


def park(sc):
    """City park: lawn, gravel paths, benches, lamp posts, trees, flower beds, pond with a fountain, town houses behind."""
    _sky(sc, ("#5d9fe6", "#d6e8f7"), "#d6e8f7", fog_start=20, fog_density=0.01)

    def hfn(x, y):
        st = F.flat_stage(x, y, STAGE_RECT, 3.0)
        r0 = np.hypot(x - 0.5, y - 3.0)
        return (1 - st) * (0.4 * F.fbm(x, y, 5, 2, 10.0) * F.smoothstep(8, 20, r0) + F.smoothstep(60, 140, r0) * 6)

    def mfn(x, y, z):
        idx = np.zeros_like(x, dtype=np.int32)
        idx = np.where((np.abs(y - 1.0 - 0.08 * x) < 1.0) | (np.abs(x - 6.5 - 0.1 * y) < 0.9), 1, idx)
        return idx

    xs = F.axis(160, 16, 0.4, 7.0, center=0.5)
    ys = F.axis(160, 16, 0.4, 7.0, center=3.0)
    F.terrain("Ground", xs, ys, hfn, [X.mat("grass_lush" if "grass_lush" in X.GEN else "grass"), X.mat("path_gravel")], mfn)
    b = B()
    for i, (x, y, yaw) in enumerate([(-6.5, 3.2, 0), (9.5, 3.2, 0), (-6.0, -4.0, 180)]):
        b.box((x, y, 0.45), (1.8, 0.5, 0.06), "planks")
        b.box((x, y + 0.24 * (1 if yaw == 0 else -1), 0.75), (1.8, 0.06, 0.5), "planks")
        for dx in (-0.8, 0.8):
            b.box((x + dx, y, 0.22), (0.07, 0.45, 0.44), "metal_dark")
    for i, (x, y) in enumerate([(-5.0, 1.0), (8.5, 0.5), (-5.0, 8.0), (8.0, 9.0), (2.0, -6.5)]):
        b.cyl((x, y, 1.6), 0.06, 3.2, "metal_dark", verts=6)
        b.box((x, y, 3.3), (0.32, 0.32, 0.38), "glass")
        b.box((x, y, 3.52), (0.42, 0.42, 0.06), "metal_dark")
    b.cyl((1.0, 11.0, 0.25), 3.2, 0.5, "stone_brick", verts=16)                   # fountain pond rim
    b.cyl((1.0, 11.0, 0.9), 0.35, 1.3, "stone_block", verts=10)
    b.cyl((1.0, 11.0, 1.6), 0.9, 0.15, "stone_block", verts=12)
    for i, (x, y, c) in enumerate([(-8, 6, "#e86a8a"), (10.5, 6.5, "#f2c94c"), (-8.5, -1, "#a77bd8")]):
        b.box((x, y, 0.15), (2.4, 1.0, 0.3), "dirt")
    b.build("ParkFurniture")
    F.water("Fountain", (1.0, 11.0, 0.42), (5.8, 5.8), opacity=0.9)
    jets = X.mat("#e8f6ff", name="jet", emit=True, fog=False)
    for k in range(4):
        o = X.cyl(f"Jet{k}", (1.0, 11.0, 2.0 + 0.3 * k), 0.12 - 0.02 * k, 0.4, jets, verts=6)
        fc = o.driver_add("location", 2)
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = f"{2.0 + 0.3 * k:.2f}+0.08*sin(frame*0.4+{k})"
    V = _veg_kit()
    flowers = [F.clump("flowers_warm", 0.5, 0.38, 2, 65), F.clump("flowers_cool", 0.5, 0.38, 2, 66)]
    for (x, y) in [(-8, 6), (10.5, 6.5), (-8.5, -1)]:
        F.scatter(flowers, (x - 1.1, x + 1.1, y - 0.4, y + 0.4), 10, abs(int(x * 7 + y)) + 1, zfn=lambda a, c: np.full_like(a, 0.3))
    av = [(STAGE_RECT[0] - 0.8, STAGE_RECT[1] + 0.8, STAGE_RECT[2] - 0.8, STAGE_RECT[3] + 0.4), (-3, 5, 7, 15)] \
        + _cam_clear(_base_cams())
    F.scatter(V["round"] + V["tall"] + V["birch"], (-45, 45, -40, 40), 90, 101, avoid=av, zfn=hfn, mind=4.5, scale=(0.8, 1.2), sink=0.2)
    F.scatter(V["bush"] + V["fbush"], (-30, 30, -25, 30), 50, 102, avoid=av, zfn=hfn, mind=2.0, scale=(0.9, 1.4))
    F.scatter(V["tufts"], (-25, 25, -20, 25), 200, 103, avoid=av[:1], zfn=hfn, scale=(0.8, 1.3))
    for i, (x, y, yaw, wall, roof, fl) in enumerate([(-30, 40, 0, "plaster", "roof_red", 2), (-18, 44, 5, "red_brick", "roof_grey", 3),
                                                     (-5, 46, 0, "plaster_white", "roof_blue", 2), (8, 45, -5, "plaster", "roof_red", 3),
                                                     (21, 42, -8, "red_brick", "roof_grey", 2), (34, 38, -15, "plaster_white", "roof_red", 2),
                                                     (-36, -30, 180, "plaster", "roof_red", 2), (0, -42, 180, "red_brick", "roof_grey", 3),
                                                     (30, -34, 170, "plaster_white", "roof_blue", 2)]):
        build_house((x, y, gz(hfn, x, y)), R(yaw), name=f"Town{i}", wall=wall, roof=roof, w=7, d=6, floors=fl)
    anchors = _base_anchors(fountain=(1.0, 11.0, 0.0), bench=(-6.5, 3.2, 0.48))
    return _result(anchors, _base_cams(), X.hx("#a9cdf1"))


WORLDS.update({"studio": studio, "classroom": classroom, "kitchen": kitchen, "cozy_room": cozy_room, "park": park})
