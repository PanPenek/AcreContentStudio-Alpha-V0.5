"""Pixel-art look v0.3 (target: Patryk's reference reel - low-poly world, chunky tiling pixel textures, soft sun
shading, no outlines, depth haze).

    import abs_pix as X
    X.setup_look(sc, sky=("#7fb6f2", "#dcecff"), fog="#dcecff")     # world sky gradient, sun, EEVEE settings
    m = X.mat("stone_brick")                                        # tiling pixel material (box-projected)
    o = X.box("Wall", (0, 0, 1), (4, 0.6, 2), m)                    # real-size primitive (scale applied)

Textures are generated here (numpy, seamless, limited palettes) and sampled with Closest filtering in
OBJECT space with box projection, so every object shows the same texel density (TEXEL_M metres per texel)
whatever its size. Materials are emission-based: base * mix(shadow, 1, soft diffuse light) + distance fog,
so colours stay exactly as painted (no exposure drift) while shading/shadows still read.
"""
import math

import bpy
import numpy as np
from mathutils import Vector

import abs_common as C

AMBIENT = 0.3                 # flat world light seen by the diffuse term (sun adds up to 1.0 on top)
TEXEL_M = 1.0 / 24.0          # one texel = ~4 cm: a 16 px brick course is ~0.66 m (reference reel scale)
FOG = {"color": (0.86, 0.92, 1.0), "start": 6.0, "density": 0.035, "max": 0.85}
_TEX = {}
_MAT = {}


# ------------------------------------------------------------------ palette helpers
def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _c(v):
    return hx(v) if isinstance(v, str) else tuple(v)


def shades(base, n=4, spread=0.22, warm=0.04):
    """n shades dark->light around base (sRGB), hue-shifted: shadows cooler, lights warmer (pixel-art habit)."""
    b = np.array(_c(base), np.float32)
    out = []
    for i in range(n):
        k = (i / (n - 1) - 0.5) * 2 if n > 1 else 0
        c = b * (1 + spread * k)
        c = c + np.array((warm, warm * 0.5, -warm)) * k
        out.append(np.clip(c, 0, 1))
    return out


def _rng(seed):
    return np.random.default_rng(seed)


def _vnoise(w, h, cell, seed):
    """Seamless value noise 0..1 (wraps at the edges) with cell size in px."""
    r = _rng(seed)
    gw, gh = max(1, w // cell), max(1, h // cell)
    g = r.random((gh, gw))
    ys, xs = np.mgrid[0:h, 0:w]
    fx, fy = xs / cell, ys / cell
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a = g[y0 % gh, x0 % gw]
    b = g[y0 % gh, (x0 + 1) % gw]
    c = g[(y0 + 1) % gh, x0 % gw]
    d = g[(y0 + 1) % gh, (x0 + 1) % gw]
    return a * (1 - tx) * (1 - ty) + b * tx * (1 - ty) + c * (1 - tx) * ty + d * tx * ty


def _quant(v, pal, dither=0.0, seed=0):
    """Map 0..1 field to palette entries (optionally ordered-dithered)."""
    v = np.clip(v, 0, 0.9999)
    if dither:
        bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0 - 0.5
        h, w = v.shape
        v = np.clip(v + dither * np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w] / len(pal), 0, 0.9999)
    idx = (v * len(pal)).astype(int)
    return np.array(pal, np.float32)[idx]


# ------------------------------------------------------------------ texture generators (HxWx3|4 sRGB, row 0 = top)
def _noise_tex(base, size=32, cell=4, seed=1, n=4, spread=0.2, specks=None, dither=0.6):
    pal = shades(base, n, spread)
    v = 0.65 * _vnoise(size, size, cell, seed) + 0.35 * _rng(seed + 7).random((size, size))
    a = _quant(v, pal, dither)
    r = _rng(seed + 3)
    for col, k in (specks or []):
        for _ in range(k):
            x, y = r.integers(0, size, 2)
            a[y, x] = _c(col)
    return a


def _bricks(base, mortar, w=32, h=32, bw=8, bh=4, seed=2, jitter=0.12, spread=0.18, stagger=True, rough=0.0):
    r = _rng(seed)
    pal = shades(base, 4, spread)
    m = np.array(_c(mortar), np.float32)
    a = np.zeros((h, w, 3), np.float32)
    for row in range(h // bh):
        off = (bw // 2) * (row % 2) if stagger else 0
        for col in range(-1, w // bw + 1):
            x0 = col * bw + off
            tone = r.integers(1, 3)
            c = np.array(pal[tone]) * (1 + r.uniform(-jitter, jitter))
            for yy in range(bh):
                for xx in range(bw):
                    X, Y = (x0 + xx) % w, row * bh + yy
                    if yy == bh - 1 or xx == bw - 1:
                        a[Y, X] = m
                    elif yy == 0:
                        a[Y, X] = pal[3] if r.random() > rough else c
                    elif yy == bh - 2:
                        a[Y, X] = pal[0] * 1.02 if r.random() > 0.3 else c
                    else:
                        a[Y, X] = c if r.random() > 0.12 else pal[max(0, tone - 1)]
    return np.clip(a, 0, 1)


def _planks(base, w=32, h=32, ph=4, seed=3, vertical=False):
    r = _rng(seed)
    pal = shades(base, 4, 0.2)
    a = np.zeros((h, w, 3), np.float32)
    for row in range(h // ph):
        tone = r.integers(1, 3)
        cut = r.integers(0, w)
        for yy in range(ph):
            for x in range(w):
                Y = row * ph + yy
                c = pal[tone]
                if yy == ph - 1:
                    c = pal[0] * 0.85
                elif yy == 0:
                    c = pal[3]
                elif r.random() < 0.08:
                    c = pal[tone - 1]
                if x == cut:
                    c = pal[0] * 0.85
                a[Y, x] = c
    if vertical:
        a = np.ascontiguousarray(np.transpose(a, (1, 0, 2)))
    return a


def _leaves(base, size=32, seed=4, alpha=True):
    """Clustered leaf blobs on transparent ground (for foliage cards / crowns)."""
    r = _rng(seed)
    pal = shades(base, 4, 0.3)
    a = np.zeros((size, size, 4), np.float32)
    v = _vnoise(size, size, 4, seed)
    for _ in range(int(size * size * 0.18)):
        x, y = r.integers(0, size, 2)
        s = r.integers(1, 3)
        tone = 3 if v[y, x] > 0.62 else (2 if v[y, x] > 0.4 else 1)
        for dy in range(-s, s + 1):
            for dx in range(-s, s + 1):
                if dx * dx + dy * dy <= s * s:
                    X, Y = (x + dx) % size, (y + dy) % size
                    a[Y, X, :3] = pal[tone] if dy < s else pal[0]
                    a[Y, X, 3] = 1
    if not alpha:
        hole = a[..., 3] < 0.5
        a[hole, :3] = pal[0]
        a[..., 3] = 1
    return a


def _water(size=32, seed=5, base="#3f9fd0"):
    pal = shades(base, 4, 0.18)
    v = _vnoise(size, size, 8, seed)
    a = _quant(0.2 + 0.6 * v, pal[:3], 0.4)
    r = _rng(seed)
    for _ in range(size // 2):  # short white glints (reference water)
        x, y = r.integers(0, size, 2)
        l = r.integers(2, 5)
        for k in range(l):
            a[y, (x + k) % size] = (0.86, 0.95, 1.0) if k else pal[3]
    return a


def _grass(base="#6cbb3c", size=32, seed=6):
    a = _noise_tex(base, size, 6, seed, 4, 0.11, dither=0.5)
    r = _rng(seed)
    pal = shades(base, 4, 0.16)
    for _ in range(size // 2):
        x, y = r.integers(0, size, 2)
        a[y, x] = pal[3]
        a[(y + 1) % size, x] = pal[0]
    return a


def _sand(base="#e8cf92", size=32, seed=7):
    a = _noise_tex(base, size, 6, seed, 4, 0.12, specks=[("#c9a76a", 18), ("#f8e7b8", 14)], dither=0.7)
    return a


def _stripes(c1, c2, size=16, width=4, vertical=False):
    a = np.zeros((size, size, 3), np.float32)
    for i in range(size):
        col = _c(c1) if (i // width) % 2 == 0 else _c(c2)
        if vertical:
            a[:, i] = col
        else:
            a[i, :] = col
    return a


def _checker(c1, c2, size=16, cell=8):
    a = np.zeros((size, size, 3), np.float32)
    ys, xs = np.mgrid[0:size, 0:size]
    m = ((xs // cell + ys // cell) % 2) == 0
    a[m] = _c(c1)
    a[~m] = _c(c2)
    return a


def _roof(base, size=32, seed=8):
    """Overlapping shingle rows (scalloped dark lower edge)."""
    pal = shades(base, 4, 0.22)
    a = np.zeros((size, size, 3), np.float32)
    r = _rng(seed)
    for y in range(size):
        row = y // 4
        for x in range(size):
            xx = (x + (row % 2) * 4) % 8
            k = y % 4
            c = pal[2] if k < 2 else pal[1]
            if k == 3 or xx == 7:
                c = pal[0]
            if k == 0 and r.random() < 0.5:
                c = pal[3]
            a[y, x] = c
    return a


def _thatch(base="#c9a24e", size=32, seed=9):
    pal = shades(base, 4, 0.25)
    a = np.zeros((size, size, 3), np.float32)
    r = _rng(seed)
    for x in range(size):
        off = r.integers(0, 6)
        for y in range(size):
            k = (y + off) % 6
            a[y, x] = pal[3] if k == 0 else (pal[0] if k == 5 else pal[1 + (r.random() > 0.5)])
    return a


def _bark(base="#7a5233", size=16, seed=10):
    pal = shades(base, 4, 0.28)
    a = np.zeros((size, size, 3), np.float32)
    r = _rng(seed)
    for x in range(size):
        t = 1 + (x % 4 == 1) + (r.random() > 0.7)
        for y in range(size):
            a[y, x] = pal[min(3, t)] if x % 4 else pal[0]
            if r.random() < 0.06:
                a[y, x] = pal[0]
    return a


def _metal(base="#9aa3ad", size=16, seed=11):
    a = _noise_tex(base, size, 8, seed, 3, 0.12, dither=0.3)
    a[0, :] = shades(base, 4, 0.2)[3]
    a[:, 0] = shades(base, 4, 0.2)[3]
    for (x, y) in [(2, 2), (13, 2), (2, 13), (13, 13)]:
        a[y, x] = shades(base, 4, 0.3)[0]
    return a


def _tiles(base, grout, size=16, cell=8):
    a = np.zeros((size, size, 3), np.float32)
    a[:] = _c(base)
    hi = shades(base, 3, 0.1)[2]
    for i in range(0, size, cell):
        a[i, :] = _c(grout)
        a[:, i] = _c(grout)
        a[i + 1 if i + 1 < size else i, :] = hi
    a[::cell, :] = _c(grout)
    a[:, ::cell] = _c(grout)
    return a


def _cloud_tex(size=16):
    a = np.ones((size, size, 3), np.float32)
    a[size * 3 // 4:, :] = (0.86, 0.9, 0.98)
    return a


GEN = {
    # terrain
    "grass": lambda: _grass("#6cbb3c"),
    "grass_dry": lambda: _grass("#a9b45a", seed=16),
    "sand": lambda: _sand("#e8cf92"),
    "sand_wet": lambda: _sand("#cdb07a", seed=17),
    "dirt": lambda: _noise_tex("#9a6f45", 32, 4, 18, specks=[("#6e4b2c", 20), ("#b88b5c", 14)]),
    "mud": lambda: _noise_tex("#7d5a3a", 32, 6, 19, spread=0.14),
    "rock": lambda: _noise_tex("#8f8a82", 32, 5, 20, spread=0.26, specks=[("#6d6862", 30), ("#b3aea6", 20)]),
    "rock_red": lambda: _noise_tex("#b9774b", 32, 5, 21, spread=0.24, specks=[("#8e5636", 30)]),
    "snow": lambda: _noise_tex("#eef4fb", 32, 6, 22, spread=0.05),
    "water": lambda: _water(),
    "water_deep": lambda: _water(base="#2c7fb8", seed=23),
    "water_nile": lambda: _water(base="#3a9ab5", seed=24),
    "lava": lambda: _noise_tex("#e2561f", 32, 4, 25, spread=0.35, specks=[("#ffd45a", 30)]),
    # building
    "stone_brick": lambda: _bricks("#a59f94", "#6f6a62", seed=30),
    "stone_block": lambda: _bricks("#d9bf86", "#a68a58", bw=16, bh=8, seed=31, spread=0.12),   # limestone / pyramid
    "rubble": lambda: _bricks("#9c9488", "#5f5a53", bw=6, bh=4, seed=32, jitter=0.25, spread=0.3, rough=0.4),
    "mudbrick": lambda: _bricks("#c99a63", "#a37a49", bw=8, bh=4, seed=33, spread=0.12),
    "red_brick": lambda: _bricks("#b5523b", "#d8cbb8", seed=34),
    "concrete": lambda: _noise_tex("#b9b6ae", 32, 8, 35, spread=0.08, specks=[("#9c9991", 25)], dither=0.4),
    "concrete_dark": lambda: _noise_tex("#8e8b84", 32, 8, 36, spread=0.08, specks=[("#77746e", 25)], dither=0.4),
    "plaster": lambda: _noise_tex("#efe4cf", 32, 8, 37, spread=0.05, dither=0.3),
    "plaster_white": lambda: _noise_tex("#f4f1ea", 32, 8, 38, spread=0.04, dither=0.3),
    "planks": lambda: _planks("#b9874f"),
    "planks_dark": lambda: _planks("#7e5532", seed=39),
    "planks_red": lambda: _planks("#b23a2e", seed=40, vertical=True),        # barn boards
    "planks_light": lambda: _planks("#d9b27a", seed=41),
    "log": lambda: _bark("#8a5e3a", 16, 42),
    "bark": lambda: _bark("#7a5233", 16, 43),
    "bark_palm": lambda: _roof("#9a7a4f", 16, 44),
    "roof_red": lambda: _roof("#b5452f"),
    "roof_grey": lambda: _roof("#6f7680", seed=45),
    "roof_blue": lambda: _roof("#4f6fa8", seed=46),
    "thatch": lambda: _thatch(),
    "metal": lambda: _metal(),
    "metal_dark": lambda: _metal("#5d646c", seed=47),
    "rust": lambda: _noise_tex("#a4532c", 16, 4, 48, spread=0.3),
    "gold": lambda: _metal("#e5b53d", seed=49),
    # nature
    "leaves": lambda: _leaves("#4f9a35"),
    "leaves_light": lambda: _leaves("#79bf3f", seed=50),
    "leaves_dark": lambda: _leaves("#2f6e2a", seed=51),
    "leaves_solid": lambda: _leaves("#4f9a35", seed=52, alpha=False),
    "leaves_solid_light": lambda: _leaves("#74b83c", seed=53, alpha=False),
    "palm_leaf": lambda: _leaves("#5aa33a", seed=54),
    "reeds": lambda: _stripes("#6f9e3a", "#8dbb4c", 16, 2, vertical=True),
    "hay": lambda: _thatch("#e0bd5c", seed=55),
    # interior / misc
    "fabric_red": lambda: _noise_tex("#c8443c", 16, 4, 60, spread=0.12),
    "fabric_blue": lambda: _noise_tex("#3e64b0", 16, 4, 61, spread=0.12),
    "fabric_cream": lambda: _noise_tex("#efe2c4", 16, 4, 62, spread=0.08),
    "canvas": lambda: _noise_tex("#e9dcb8", 16, 4, 63, spread=0.08),
    "sail_orange": lambda: _noise_tex("#e8792b", 16, 4, 64, spread=0.08),
    "carpet": lambda: _checker("#8a5fbf", "#7a52ad", 16, 4),
    "floor_tiles": lambda: _checker("#efe8dc", "#c9b8a2", 16, 8),
    "wall_tiles": lambda: _tiles("#dff0ec", "#b9cfca"),
    "wallpaper": lambda: _stripes("#f2e6d6", "#ead9c4", 16, 4, vertical=True),
    "chalkboard": lambda: _noise_tex("#2f5a45", 32, 8, 65, spread=0.06),
    "paper": lambda: _noise_tex("#f6f1e2", 16, 8, 66, spread=0.03),
    "clay": lambda: _noise_tex("#c46a3f", 16, 4, 67, spread=0.14),
    "ceramic_white": lambda: _noise_tex("#f3f3ef", 16, 8, 68, spread=0.03),
    "glass": lambda: _noise_tex("#bfe4f2", 16, 8, 69, spread=0.05),
    "cloud": lambda: _cloud_tex(),
}


# ------------------------------------------------------------------ prop-kit textures (added for abs_kit.py)
def _strata(base, size=32, seed=70, band=(5, 9)):
    """Layered sedimentary rock: noise + dark bedding lines with lit lips + short cracks (wadi cliffs)."""
    pal = shades(base, 4, 0.24)
    a = _noise_tex(base, size, 5, seed, 4, 0.16, dither=0.5)
    r = _rng(seed)
    y = 0
    while True:
        y += int(r.integers(band[0], band[1] + 1))
        if y >= size:
            break
        for x in range(size):
            if r.random() > 0.15:
                a[y % size, x] = pal[0]
            if r.random() > 0.55:
                a[(y - 1) % size, x] = pal[3]
    for _ in range(size // 3):
        x, y = r.integers(0, size, 2)
        for k in range(int(r.integers(2, 4))):
            a[(y + k) % size, x] = pal[0]
    return a


def _gravel(base="#a39581", size=32, seed=71):
    pal = shades(base, 5, 0.3)
    a = _quant(0.3 + 0.4 * _vnoise(size, size, 4, seed), pal[1:4], 0.5)
    r = _rng(seed)
    for _ in range(int(size * size * 0.09)):
        x, y = r.integers(0, size, 2)
        t = int(r.integers(1, 5))
        a[y, x] = pal[t]
        a[y, (x + 1) % size] = pal[t]
        a[(y + 1) % size, x] = pal[max(0, t - 2)]
    return a


def _foam(size=32, seed=72, dark="#4f9fd1"):
    """White-water: vertical streaks (flow runs along v) of white / pale blue over blue."""
    r = _rng(seed)
    pal = [_c(dark), hx("#9fd6ee"), hx("#dff3fb"), (1.0, 1.0, 1.0)]
    a = np.zeros((size, size, 3), np.float32)
    for x in range(size):
        y = 0
        while y < size:
            ln = int(r.integers(2, 9))
            t = int(r.choice([0, 1, 2, 2, 3, 3, 3]))
            for k in range(ln):
                a[(y + k) % size, x] = pal[t]
            y += ln
    return a


def _water_mud(size=32, seed=78, base="#8f6b43"):
    pal = shades(base, 4, 0.2)
    v = _vnoise(size, size, 8, seed)
    a = _quant(0.2 + 0.6 * v, pal[:3], 0.4)
    r = _rng(seed)
    for _ in range(size // 2):
        x, y = r.integers(0, size, 2)
        for k in range(int(r.integers(2, 5))):
            a[y, (x + k) % size] = hx("#e9d6b4") if k else pal[3]
    return a


def _panels(base="#bdb9b0", size=48, pw=24, ph=12, seed=73):
    """Cast concrete with formwork panel joints and tie holes (modern dams, walls)."""
    a = _noise_tex(base, size, 8, seed, 3, 0.07, specks=[("#a19d95", 40)], dither=0.4)
    pal = shades(base, 4, 0.16)
    for y in range(0, size, ph):
        a[y, :] = pal[0]
        a[(y + 1) % size, :] = pal[3]
    for row, y in enumerate(range(0, size, ph)):
        off = (pw // 2) * (row % 2)
        for x in range(off, size + off, pw):
            a[y:y + ph, x % size] = pal[0]
        for x in range(off + pw // 4, size + off, pw // 2):
            a[(y + ph // 2) % size, x % size] = pal[0] * 0.8
    return a


def _sail_s(size=32, base="#e8792b"):
    """Orange sail cloth with a white pixel 'S' and a white stripe (reference reel boat). UV-mapped (v up)."""
    a = _noise_tex(base, size, 4, 64, spread=0.08)
    pal = shades(base, 4, 0.18)
    for y in range(0, size, 8):  # cloth panel seams
        a[y, :] = pal[0]
    glyph = ["#####", "#....", "#....", "#####", "....#", "....#", "#####"]
    sc, x0, y0 = 3, 9, 3
    for gy, row in enumerate(glyph):
        for gx, ch in enumerate(row):
            if ch == "#":
                a[y0 + gy * sc:y0 + (gy + 1) * sc, x0 + gx * sc:x0 + (gx + 1) * sc] = hx("#f6f1e6")
                a[min(size - 1, y0 + (gy + 1) * sc), x0 + gx * sc:x0 + (gx + 1) * sc] = np.minimum(
                    a[min(size - 1, y0 + (gy + 1) * sc), x0 + gx * sc:x0 + (gx + 1) * sc], pal[0] + 0.02)
    a[27:29, :] = hx("#f6f1e6")
    return a


def _palm_frond(w=16, h=32, seed=79, base="#5aa33a"):
    """RGBA frond: midrib down the centre, leaflets angled toward the tip (row 0 = tip). Map with UVs."""
    pal = shades(base, 4, 0.3)
    a = np.zeros((h, w, 4), np.float32)
    r = _rng(seed)
    mid = w // 2
    for y in range(h):
        a[y, mid - 1:mid + 1, :3] = hx("#7d8a3a")
        a[y, mid - 1:mid + 1, 3] = 1
    for y in range(2, h - 1, 2):
        t = 1 - y / h
        ln = int(round((mid - 1) * (math.sin(math.pi * min(1.0, t * 1.15)) ** 0.6))) if t > 0.03 else 0
        for side in (-1, 1):
            tone = 1 + int(r.integers(0, 3))
            for k in range(1, ln + 1):
                x = mid + k if side > 0 else mid - 1 - k
                yy = y - k // 2
                if 0 <= x < w and 0 <= yy < h:
                    a[yy, x, :3] = pal[min(3, tone)] if k < ln else pal[0]
                    a[yy, x, 3] = 1
                    if yy + 1 < h and a[yy + 1, x, 3] < 0.5:
                        a[yy + 1, x, :3] = pal[0]
                        a[yy + 1, x, 3] = 1
    return a


def _sacking(base="#c8ad7a", size=16, seed=80):
    a = _noise_tex(base, size, 4, seed, 3, 0.08, dither=0.3)
    pal = shades(base, 3, 0.14)
    a[::2, ::2] = pal[0]
    a[1::2, 1::2] = pal[2]
    return a


def _flame(size=16, seed=81):
    pal = [hx("#d8401c"), hx("#f07b22"), hx("#ffb230"), hx("#ffe48a")]
    return _quant(0.15 + 0.8 * _vnoise(size, size, 3, seed), pal, 0.6)


GEN.update({
    "rock_desert": lambda: _strata("#c49a6c", seed=70),          # ochre wadi cliffs
    "limestone_rock": lambda: _strata("#d3bd93", seed=76),       # pale quarry / cliff limestone
    "rock_grey": lambda: _strata("#8f8a82", seed=77, band=(6, 11)),
    "gravel": lambda: _gravel(),                                  # rubble core / wadi bed / paths
    "gravel_grey": lambda: _gravel("#9a978f", seed=82),
    "whitewater": lambda: _foam(),                                # spillway / rapids (flow along v)
    "whitewater_mud": lambda: _foam(seed=83, dark="#8a6a45"),
    "water_mud": lambda: _water_mud(),                            # flood water
    "concrete_panel": lambda: _panels(),                          # modern dam / bunker
    "asphalt": lambda: _noise_tex("#5d6066", 32, 6, 84, spread=0.1, specks=[("#7b7e84", 30)], dither=0.4),
    "log_h": lambda: np.ascontiguousarray(np.transpose(_bark("#8a5e3a", 16, 42), (1, 0, 2))),   # bark along X
    "planks_v": lambda: _planks("#b9874f", seed=85, vertical=True),
    "staves": lambda: _planks("#a8743f", seed=74, vertical=True),  # barrels / buckets
    "siding_grey": lambda: _planks("#8e9aa8", seed=75),           # bakery clapboard
    "siding_white": lambda: _planks("#e9e4d8", seed=86),
    "mud_plaster": lambda: _noise_tex("#d1a978", 32, 8, 87, spread=0.07, specks=[("#b48b5c", 20), ("#e2c191", 14)], dither=0.4),
    "awning_red": lambda: _stripes("#d2463c", "#f4efe6", 16, 4, vertical=True),
    "awning_blue": lambda: _stripes("#3f6fb8", "#f4efe6", 16, 4, vertical=True),
    "sail_s": lambda: _sail_s(),                                  # use with uv=True
    "palm_frond": lambda: _palm_frond(),                          # RGBA, use with uv=True, alpha=True
    "rope": lambda: _stripes("#d9c08a", "#a88a54", 8, 2),
    "sacking": lambda: _sacking(),
    "flame": lambda: _flame(),
    "iron": lambda: _metal("#4a4f57", seed=88),
})


def texture(name):
    """Packed Blender image for a generator name (cached)."""
    if name in _TEX:
        return _TEX[name]
    arr = GEN[name]()
    im = C.img_from_array(f"px_{name}", arr)
    _TEX[name] = im
    return im


def solid_tex(color, name=None):
    """Tiny 2-shade pixel texture from one colour (keeps the pixel feel on plain-coloured parts)."""
    key = name or f"solid_{_c(color)}"
    if key in _TEX:
        return _TEX[key]
    pal = shades(color, 3, 0.07)
    v = _rng(abs(hash(key)) % 1000).random((8, 8))
    a = _quant(0.15 + 0.7 * v, pal, 0.5)
    _TEX[key] = C.img_from_array(f"px_{key}"[:60], a)
    return _TEX[key]


# ------------------------------------------------------------------ materials
def _fog_mix(N, L, col):
    """col -> mix(col, fog, clamp((dist-start)*density)) * max."""
    cam = N.new("ShaderNodeCameraData")
    sub = N.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    L.new(cam.outputs["View Distance"], sub.inputs[0])
    sub.inputs[1].default_value = FOG["start"]
    mul = N.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.use_clamp = True
    L.new(sub.outputs[0], mul.inputs[0])
    mul.inputs[1].default_value = FOG["density"]
    mx = N.new("ShaderNodeMath")
    mx.operation = "MULTIPLY"
    L.new(mul.outputs[0], mx.inputs[0])
    mx.inputs[1].default_value = FOG["max"]
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.name = "FOG"
    L.new(mx.outputs[0], mix.inputs[0])
    L.new(col, mix.inputs[6])
    fc = C.srgb_to_lin(FOG["color"])
    mix.inputs[7].default_value = (float(fc[0]), float(fc[1]), float(fc[2]), 1)
    return mix.outputs[2]


def mat(tex, name=None, tile_m=None, shadow=0.62, uv=False, alpha=False, emit=False, tint=None,
        anim=None, fog=True, cull=False, shade_tint=(0.9, 0.92, 1.06)):
    """Pixel material.
    tex: generator name | (r,g,b) | '#hex' | bpy image.  tile_m: metres covered by one texture tile (default = px * TEXEL_M).
    uv=True samples the mesh UVs instead of object-space box projection (characters, signs, decals).
    anim=(du, dv) scrolls the texture per second (water, conveyor).  emit=True ignores lighting (sky, glow).
    """
    key = name or f"{tex}|{tile_m}|{uv}|{alpha}|{emit}|{tint}|{anim}|{shadow}"
    if key in _MAT:
        return _MAT[key]
    if isinstance(tex, bpy.types.Image):
        im = tex
    elif isinstance(tex, str) and tex in GEN:
        im = texture(tex)
    else:
        im = solid_tex(tex)
    m = bpy.data.materials.new(name or f"pm_{tex if isinstance(tex, str) else 'c'}")
    nt, out = C._nodes(m)
    N, L = nt.nodes, nt.links
    t = N.new("ShaderNodeTexImage")
    t.image = im
    t.interpolation = "Closest"
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    if uv:
        L.new(tc.outputs["UV"], mp.inputs[0])
        t.extension = "REPEAT"
    else:
        t.projection = "BOX"
        t.projection_blend = 0.0
        L.new(tc.outputs["Object"], mp.inputs[0])
        s = 1.0 / (tile_m or im.size[0] * TEXEL_M)
        mp.inputs["Scale"].default_value = (s, s, s)
    if anim:
        for k, sp in enumerate(anim):
            if sp:
                fc = mp.inputs["Location"].driver_add("default_value", k)
                fc.driver.type = "SCRIPTED"
                fc.driver.expression = f"frame*{sp / 30.0:.6f}"
    L.new(mp.outputs[0], t.inputs[0])
    base = t.outputs["Color"]
    if tint is not None:
        tm = N.new("ShaderNodeMix")
        tm.data_type = "RGBA"
        tm.blend_type = "MULTIPLY"
        tm.inputs[0].default_value = 1
        tl = C.srgb_to_lin(_c(tint))
        tm.inputs[7].default_value = (float(tl[0]), float(tl[1]), float(tl[2]), 1)
        L.new(base, tm.inputs[6])
        base = tm.outputs[2]
    if emit:
        col = base
    else:
        dif = N.new("ShaderNodeBsdfDiffuse")
        dif.inputs[0].default_value = (1, 1, 1, 1)
        s2r = N.new("ShaderNodeShaderToRGB")
        L.new(dif.outputs[0], s2r.inputs[0])
        ramp = N.new("ShaderNodeValToRGB")  # soft (not cel) shading: dark side keeps `shadow` of the colour
        ramp.color_ramp.interpolation = "EASE"
        sc_ = C.srgb_to_lin([shadow * shade_tint[0], shadow * shade_tint[1], min(1.0, shadow * shade_tint[2])])
        # light ~= AMBIENT (shadow side / cast shadow) .. AMBIENT + 1 (facing the sun)
        ramp.color_ramp.elements[0].position = AMBIENT + 0.02
        ramp.color_ramp.elements[0].color = (float(sc_[0]), float(sc_[1]), float(sc_[2]), 1)
        ramp.color_ramp.elements[1].position = AMBIENT + 0.6
        ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
        L.new(s2r.outputs[0], ramp.inputs[0])
        mul = N.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1
        L.new(base, mul.inputs[6])
        L.new(ramp.outputs[0], mul.inputs[7])
        col = mul.outputs[2]
    if fog:
        col = _fog_mix(N, L, col)
    em = N.new("ShaderNodeEmission")
    L.new(col, em.inputs[0])
    if alpha:
        tr = N.new("ShaderNodeBsdfTransparent")
        mix = N.new("ShaderNodeMixShader")
        gt = N.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.inputs[1].default_value = 0.5
        L.new(t.outputs["Alpha"], gt.inputs[0])
        L.new(gt.outputs[0], mix.inputs[0])
        L.new(tr.outputs[0], mix.inputs[1])
        L.new(em.outputs[0], mix.inputs[2])
        L.new(mix.outputs[0], out.inputs[0])
        try:
            m.surface_render_method = "DITHERED"
        except Exception:
            pass
    else:
        L.new(em.outputs[0], out.inputs[0])
    m.use_backface_culling = cull
    _MAT[key] = m
    return m


def color(c, **kw):
    return mat(_c(c), **kw)


# ------------------------------------------------------------------ geometry helpers (real sizes, scale applied)
def _finish(o, m, bevel=0.0, smooth=False):
    if m is not None:
        if isinstance(m, (list, tuple)):
            for mm in m:
                o.data.materials.append(mm)
        else:
            o.data.materials.append(m)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        bm = o.modifiers.new("bev", "BEVEL")
        bm.width = bevel
        bm.segments = 1
        bm.limit_method = "ANGLE"
    if smooth:
        bpy.ops.object.shade_smooth()
    else:
        bpy.ops.object.shade_flat()
    return o


def box(name, loc, size, m=None, rot=(0, 0, 0), bevel=0.0, parent=None):
    """Box centred at loc with full size (sx, sy, sz) in metres."""
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    _finish(o, m, bevel)
    if parent is not None:
        o.parent = parent
    return o


def cyl(name, loc, r, h, m=None, rot=(0, 0, 0), verts=10, r2=None, smooth=False, parent=None, cap=True):
    """Cylinder/cone centred at loc (r2 = top radius for a frustum)."""
    if r2 is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc, rotation=rot,
                                            end_fill_type="NGON" if cap else "NOTHING")
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2, depth=h, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    _finish(o, m, 0, smooth)
    if parent is not None:
        o.parent = parent
    return o


def ball(name, loc, r, m=None, scale=(1, 1, 1), sub=1, smooth=False, parent=None, ico=True):
    if ico:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub, radius=r, location=loc)
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=r, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    _finish(o, m, 0, smooth)
    if parent is not None:
        o.parent = parent
    return o


def mesh(name, verts, faces, m=None, parent=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    if m is not None:
        for mm in (m if isinstance(m, (list, tuple)) else [m]):
            me.materials.append(mm)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    if parent is not None:
        o.parent = parent
    return o


def prism(name, profile, depth, m=None, axis="x", loc=(0, 0, 0), parent=None):
    """Extrude a 2D profile [(u, z), ...] (counter-clockwise) along axis by depth (centred). Dam/wall sections."""
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
    o = mesh(name, vs, fs, m, parent)
    if axis == "x":  # keep outward normals
        bpy.context.view_layer.objects.active = o
    _recalc(o)
    return o


def _recalc(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def card(name, loc, w, h, m, yaw=0.0, parent=None, tilt=0.0):
    """Vertical quad with UVs 0..1 (foliage/sign/billboard). loc = bottom centre."""
    cz, sz = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    hw = w / 2
    vs = [(-hw, 0, 0), (hw, 0, 0), (hw, math.sin(math.radians(tilt)) * h, h), (-hw, math.sin(math.radians(tilt)) * h, h)]
    vs = [(loc[0] + x * cz - y * sz, loc[1] + x * sz + y * cz, loc[2] + z) for (x, y, z) in vs]
    o = mesh(name, vs, [(0, 1, 2, 3)], m, parent)
    uvl = o.data.uv_layers.new()
    for i, uvv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uvl.data[i].uv = uvv
    return o


def join(objs, name):
    objs = [o for o in objs if o is not None]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.object
    o.name = name
    return o


# ------------------------------------------------------------------ world + lighting
def setup_look(sc, sky=("#5f9fea", "#cfe4fb"), fog=None, sun_dir=(58, 0, -62), sun_disk=True, fog_start=None,
               fog_density=None, sun_energy=math.pi, ambient=1.0):
    """Sky gradient world (zenith, horizon), sun with soft shadows, EEVEE + colour settings for crisp output."""
    zen, hor = _c(sky[0]), _c(sky[1])
    if fog:
        FOG["color"] = _c(fog)
    else:
        FOG["color"] = hor
    if fog_start is not None:
        FOG["start"] = fog_start
    if fog_density is not None:
        FOG["density"] = fog_density
    w = bpy.data.worlds.new("PixWorld")
    sc.world = w
    w.use_nodes = True
    N, L = w.node_tree.nodes, w.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputWorld")
    lp = N.new("ShaderNodeLightPath")
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Generated"], sep.inputs[0])  # world 'Generated' = view direction
    ramp = N.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    zl, hl = C.srgb_to_lin(zen), C.srgb_to_lin(hor)
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (*[float(v) for v in hl], 1)
    ramp.color_ramp.elements[1].position = 0.45
    ramp.color_ramp.elements[1].color = (*[float(v) for v in zl], 1)
    L.new(sep.outputs["Z"], ramp.inputs[0])
    bg_cam = N.new("ShaderNodeBackground")
    L.new(ramp.outputs[0], bg_cam.inputs[0])
    bg_light = N.new("ShaderNodeBackground")  # what the diffuse shading sees: flat ambient
    bg_light.inputs[0].default_value = (AMBIENT * ambient, AMBIENT * ambient, AMBIENT * ambient, 1)  # linear
    mix = N.new("ShaderNodeMixShader")
    L.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    L.new(bg_light.outputs[0], mix.inputs[1])
    L.new(bg_cam.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs[0])
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sc.collection.objects.link(sun)
    sun.data.energy = sun_energy
    sun.data.angle = math.radians(3.0)
    sun.rotation_euler = tuple(math.radians(v) for v in sun_dir)
    try:
        sun.data.use_shadow = True
        sun.data.shadow_maximum_resolution = 0.01
    except Exception:
        pass
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.filter_size = 1.0
    try:
        sc.eevee.use_shadows = True
        sc.eevee.shadow_ray_count = 2
        sc.eevee.shadow_step_count = 8
    except Exception:
        pass
    return sun


def sky_extras(center=(0, 30, 0), sun_az=25, sun_el=34, clouds=7, seed=3, dist=60.0, sun_size=2.6):
    """Pixel sun disc + chunky low-poly clouds far behind the set (camera looks toward +Y)."""
    r = _rng(seed)
    az, el = math.radians(sun_az), math.radians(sun_el)
    sp = Vector(center) + Vector((math.sin(az) * dist, math.cos(az) * dist * 0.2, math.sin(el) * dist))
    sun_m = mat("#ffe7a3", name="sun_disc", emit=True, fog=False)
    s = cyl("SunDisc", sp, sun_size, 0.1, sun_m, rot=(math.radians(90), 0, 0), verts=8)
    ring = cyl("SunRing", sp + Vector((0, 0.2, 0)), sun_size * 1.25, 0.1, mat("#f6c86a", name="sun_ring", emit=True, fog=False),
               rot=(math.radians(90), 0, 0), verts=8)
    cm = mat("#ffffff", name="cloud", emit=True, fog=False)
    cs = mat("#e3ebf7", name="cloud_shade", emit=True, fog=False)
    objs = [s, ring]
    for i in range(clouds):
        x = r.uniform(-45, 45)
        z = r.uniform(18, 34)
        y = center[1] + r.uniform(-5, 15)
        w = r.uniform(5, 11)
        for k in range(r.integers(2, 4)):
            bw = w * r.uniform(0.4, 0.8)
            dx = r.uniform(-w / 2, w / 2)
            objs.append(box(f"Cloud{i}_{k}", (x + dx, y, z + k * 0.9), (bw, 2.0, 1.2 + r.uniform(0, 0.8)), cm))
        objs.append(box(f"CloudB{i}", (x, y + 0.5, z - 0.5), (w * 1.1, 2.0, 0.6), cs))
    return objs


def water_plane(name, loc, size, tex="water", subdiv=24, amp=0.025, speed=(0.05, 0.02), parent=None):
    """Animated water: scrolling pixel texture + gentle Wave-modifier swell."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=subdiv, y_subdivisions=subdiv, size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0], size[1], 1)
    _finish(o, mat(tex, name=f"{name}_mat", anim=speed, shadow=0.8))
    if amp:
        w = o.modifiers.new("swell", "WAVE")
        w.height = amp
        w.width = 1.2
        w.speed = 0.04
        w.narrowness = 1.5
        w.use_normal = False
    if parent is not None:
        o.parent = parent
    return o
