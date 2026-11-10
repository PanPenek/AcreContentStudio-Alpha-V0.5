"""Set library. Each set builder creates geometry and returns {"anchors": {...}, "cams": {...}, "world": rgb}.

Camera presets: name -> dict(pos, target, end (optional dolly end pos), lens). A preset may use
"follow": "cat" to aim at the cat's position at shot start (the scene builder resolves it).
"""
import math

import numpy as np

import abs_common as C


def _planks():
    h, w = 32, 32
    a = np.zeros((h, w, 3), np.float32)
    cols = [(0.78, 0.55, 0.36), (0.74, 0.51, 0.33), (0.81, 0.58, 0.38), (0.76, 0.53, 0.35)]
    for y in range(h):
        row = y // 8
        for x in range(w):
            c = np.array(cols[(row + (x + row * 11) // 16) % 4])
            if y % 8 == 0 or (x + row * 11) % 16 == 0:
                c = c * 0.78
            a[y, x] = c
    return C.img_from_array("planks", a)


def _wallpaper():
    h, w = 16, 16
    a = np.zeros((h, w, 3), np.float32)
    a[:] = (0.93, 0.86, 0.95)
    for (x, y) in [(3, 3), (11, 11), (4, 3), (3, 4), (11, 12), (12, 11)]:
        a[y, x] = (0.98, 0.72, 0.82)
    a[:, 7] = (0.9, 0.82, 0.93)
    return C.img_from_array("wallpaper", a)


def _sky():
    h, w = 32, 16
    a = np.zeros((h, w, 3), np.float32)
    for y in range(h):
        k = y / h
        a[y, :] = (0.55 + 0.35 * k, 0.78 + 0.15 * k, 1.0)
    for (x, y, l) in [(2, 8, 6), (9, 14, 5), (4, 20, 7)]:
        a[y, x:x + l] = (1, 1, 1)
        a[y - 1, x + 1:x + l - 1] = (1, 1, 1)
    return C.img_from_array("sky", a)


def _rug():
    h, w = 16, 24
    a = np.zeros((h, w, 3), np.float32)
    a[:] = (0.62, 0.48, 0.82)
    a[2:-2, 2:-2] = (0.98, 0.74, 0.5)
    a[4:-4, 4:-4] = (0.62, 0.48, 0.82)
    return C.img_from_array("rug", a)


def _cushion():
    h, w = 8, 8
    a = np.zeros((h, w, 3), np.float32)
    for y in range(h):
        for x in range(w):
            a[y, x] = (0.98, 0.7, 0.78) if (x // 2 + y // 2) % 2 == 0 else (1.0, 0.84, 0.88)
    return C.img_from_array("cushion", a)


def _poster_cat():
    a = np.zeros((20, 16, 3), np.float32)
    a[:] = (1.0, 0.96, 0.86)
    yy, xx = np.mgrid[0:20, 0:16]
    head = ((xx - 8) / 5.0) ** 2 + ((yy - 10) / 4.5) ** 2 < 1
    a[head] = (0.95, 0.63, 0.29)
    for (x, y) in [(4, 5), (5, 4), (5, 5), (11, 5), (10, 4), (10, 5)]:
        a[y, x] = (0.95, 0.63, 0.29)
    a[9, 6] = a[9, 10] = (0.1, 0.1, 0.1)
    a[11, 8] = (0.95, 0.5, 0.6)
    a[16:18, 3:13] = (0.55, 0.42, 0.75)
    return C.img_from_array("poster_cat", a)


def cozy_room():
    T = C.toon_mat
    C.add_prim("plane", "Floor", size=12, mat=T("floor", image=_planks(), uv_scale=9, shade=0.85))
    C.add_prim("plane", "Rug", loc=(0.1, 0.0, 0.003), size=1, scale=(1.6, 1.1, 1), mat=T("rug", image=_rug(), shade=0.86))
    wall = T("wall", image=_wallpaper(), uv_scale=10, shade=0.9)
    C.add_prim("plane", "BackWall", loc=(0, 1.0, 2.5), rot=(math.radians(90), 0, 0), size=1, scale=(10, 5, 1), mat=wall)
    C.add_prim("plane", "SideWall", loc=(-1.7, 0, 2.5), rot=(math.radians(90), 0, math.radians(90)), size=1,
               scale=(10, 5, 1), mat=T("wall2", image=_wallpaper(), uv_scale=10, shade=0.8))
    C.add_prim("cube", "Skirting", loc=(0, 0.985, 0.06), scale=(5, 0.015, 0.06), mat=T("skirt", color=(0.98, 0.95, 0.92)))
    # window + seat
    C.add_prim("cube", "WinFrame", loc=(0.6, 0.985, 1.32), scale=(0.62, 0.02, 0.5), mat=T("wf", color=(0.99, 0.97, 0.94)))
    C.add_prim("cube", "WinSky", loc=(0.6, 0.97, 1.32), scale=(0.55, 0.01, 0.43), mat=C.toon_mat("sky", image=_sky(), flat=True))
    C.add_prim("cube", "WinBarV", loc=(0.6, 0.96, 1.32), scale=(0.015, 0.01, 0.43), mat=T("wb", color=(0.99, 0.97, 0.94)))
    C.add_prim("cube", "WinBarH", loc=(0.6, 0.96, 1.32), scale=(0.55, 0.01, 0.015), mat=T("wb2", color=(0.99, 0.97, 0.94)))
    for sx in (-1, 1):
        C.add_prim("cube", f"Curtain{sx}", loc=(0.6 + sx * 0.66, 0.94, 1.35), scale=(0.12, 0.02, 0.58),
                   mat=T(f"cur{sx}", color=(0.97, 0.62, 0.7), shade=0.8))
    C.add_prim("cube", "Seat", loc=(0.6, 0.78, 0.22), scale=(0.75, 0.22, 0.22), mat=T("seat", color=(0.98, 0.94, 0.88), shade=0.82))
    C.add_prim("cube", "SeatCushion", loc=(0.6, 0.77, 0.475), scale=(0.72, 0.2, 0.035), mat=T("cush", image=_cushion(), uv_scale=4))
    C.add_prim("cube", "Pillow", loc=(1.15, 0.9, 0.58), rot=(math.radians(-15), 0, math.radians(10)), scale=(0.12, 0.05, 0.1),
               mat=T("pil", color=(0.62, 0.5, 0.86)))
    # props
    C.add_prim("cyl", "PlantPot", loc=(-1.25, 0.65, 0.14), scale=(0.13, 0.13, 0.14), vertices=8, mat=T("pot", color=(0.86, 0.5, 0.36)))
    for i, (dx, dz, s) in enumerate([(0, 0.42, 0.16), (-0.08, 0.34, 0.12), (0.09, 0.36, 0.12)]):
        C.add_prim("ico", f"Leaf{i}", loc=(-1.25 + dx, 0.65, dz), subdivisions=1, radius=s, mat=T("leaf", color=(0.46, 0.74, 0.42)))
    C.add_prim("cube", "Shelf", loc=(-0.9, 0.95, 1.45), scale=(0.4, 0.05, 0.02), mat=T("shelf", color=(0.72, 0.5, 0.34)))
    for i, c in enumerate([(0.55, 0.42, 0.75), (0.96, 0.66, 0.36), (0.42, 0.62, 0.86), (0.95, 0.55, 0.62)]):
        C.add_prim("cube", f"Book{i}", loc=(-1.15 + i * 0.07, 0.95, 1.55), scale=(0.025, 0.04, 0.09), mat=T(f"book{i}", color=c))
    C.add_prim("cube", "Poster", loc=(-0.9, 0.985, 1.05), scale=(0.2, 0.01, 0.25), mat=T("poster", image=_poster_cat(), flat=True))
    C.add_prim("cyl", "Bowl", loc=(1.45, 0.25, 0.03), scale=(0.08, 0.08, 0.03), vertices=10, mat=T("bowl", color=(0.42, 0.62, 0.86)))
    anchors = {
        "host": (-0.5, 0.5, 0.0), "bench_edge": (-0.06, 0.66, 0.51), "bench_left": (0.15, 0.74, 0.51), "bench_mid": (0.55, 0.74, 0.51),
        "bench_right": (1.0, 0.74, 0.51), "floor_front": (0.45, 0.05, 0.0), "floor_right": (1.1, 0.2, 0.0),
        "bench_offleft": (-0.6, 0.74, 0.51), "bench_offright": (1.8, 0.74, 0.51),
        # generic anchors (props): floor spots in front of the window seat
        "center": (0.45, 0.25, 0.0), "left": (-1.1, 0.35, 0.0), "right": (1.25, 0.25, 0.0), "back": (0.55, 0.74, 0.51),
        "front": (0.3, -0.25, 0.0),
    }
    cams = {
        "wide": {"pos": (-0.02, -2.05, 1.05), "target": (-0.02, 0.5, 0.86), "end": (-0.02, -1.9, 1.03), "lens": 27},
        "host": {"pos": (-0.45, -0.88, 1.36), "target": (-0.5, 0.5, 1.3), "end": (-0.45, -0.73, 1.35), "lens": 38},
        "host_full": {"pos": (-0.4, -1.9, 1.0), "target": (-0.5, 0.5, 0.88), "end": (-0.4, -1.7, 1.0), "lens": 32},
        "two": {"pos": (0.45, -1.35, 1.15), "target": (-0.22, 0.58, 0.92), "end": (0.4, -1.22, 1.13), "lens": 28},
        "cat": {"follow": "cat", "offset": (0.1, -0.95, 0.14), "aim": (0.0, 0.0, 0.03), "dolly": 0.12, "lens": 35},
        "card": {"follow": "cat", "offset": (0.03, -0.75, 0.1), "aim": (0.0, 0.0, 0.05), "dolly": 0.06, "lens": 38},
        "cat_low": {"follow": "cat", "offset": (0.32, -0.8, -0.04), "aim": (0.0, 0.0, 0.04), "dolly": 0.1, "lens": 30},
    }
    return {"anchors": anchors, "cams": cams, "world": (0.96, 0.9, 0.98)}


SETS = {"cozy_room": cozy_room}


# ------------------------------------------------------------------ generic sets
# Every set exposes the generic anchors "host", "center", "left", "right", "back", "front" so props
# and the host can be placed the same way everywhere; prop/two/card cameras are computed in scene.py
# from the focused prop, so a set only needs wide/host/host_full presets.
GENERIC_ANCHORS = ("host", "center", "left", "right", "back", "front")


def _grass():
    rng = np.random.default_rng(3)
    a = np.zeros((32, 32, 3), np.float32)
    base = np.array([(0.45, 0.72, 0.36), (0.41, 0.67, 0.33), (0.5, 0.76, 0.4)])
    a[:] = base[rng.integers(0, 3, (32, 32))]
    for _ in range(26):  # tiny flowers / darker tufts
        x, y = rng.integers(0, 32, 2)
        a[y, x] = (0.98, 0.92, 0.55) if rng.random() < 0.3 else (0.33, 0.56, 0.28)
    return C.img_from_array("grass", a)


def _sky_gradient(top, bottom, name, clouds=True):
    h, w = 64, 32
    a = np.zeros((h, w, 3), np.float32)
    for y in range(h):  # banded pixel gradient (bottom row = y 0 in Blender images)
        k = round((y / h) * 6) / 6
        a[y, :] = np.array(bottom) * (1 - k) + np.array(top) * k
    if clouds:
        for (x, y, l) in [(3, 40, 9), (18, 48, 8), (8, 55, 6), (22, 36, 5)]:
            a[y, x:x + l] = (1, 1, 1)
            a[y + 1, x + 1:x + l - 1] = (1, 1, 1)
    return C.img_from_array(name, a)


def _bark():
    a = np.zeros((16, 8, 3), np.float32)
    a[:] = (0.5, 0.33, 0.22)
    a[:, ::3] = (0.42, 0.27, 0.18)
    return C.img_from_array("bark", a)


def _water():
    a = np.zeros((16, 16, 3), np.float32)
    a[:] = (0.36, 0.66, 0.9)
    for y in range(0, 16, 4):
        a[y, (y * 3) % 16:(y * 3) % 16 + 4] = (0.75, 0.9, 1.0)
    return C.img_from_array("water", a)


def _tree(name, x, y, s, T, leaf):
    C.add_prim("cyl", f"{name}_trunk", loc=(x, y, 0.45 * s), scale=(0.09 * s, 0.09 * s, 0.45 * s), vertices=6,
               mat=T(f"{name}_bark", image=_bark(), shade=0.8))
    for k, (zz, rr) in enumerate([(1.05, 0.62), (1.45, 0.48), (1.8, 0.32)]):
        C.add_prim("cone", f"{name}_leaf{k}", loc=(x, y, zz * s), scale=(rr * s, rr * s, 0.42 * s), vertices=7, mat=leaf)


def forest():
    """Sunny forest clearing: grass, a stream behind the action area, ring of low-poly pines, pixel sky."""
    T = C.toon_mat
    C.add_prim("plane", "Ground", size=40, mat=T("ground", image=_grass(), uv_scale=40, shade=0.86))
    C.add_prim("plane", "Stream", loc=(0, 2.6, 0.004), size=1, scale=(40, 0.7, 1), mat=T("water", image=_water(), uv_scale=12, flat=True))
    C.add_prim("plane", "Sky", loc=(0, 14, 6), rot=(math.radians(90), 0, 0), size=1, scale=(60, 14, 1),
               mat=T("sky", image=_sky_gradient((0.45, 0.68, 0.98), (0.86, 0.95, 1.0), "forest_sky"), flat=True))
    leafs = [T(f"leaf{i}", color=c, shade=0.78) for i, c in enumerate([(0.3, 0.6, 0.34), (0.36, 0.66, 0.38), (0.26, 0.52, 0.32)])]
    rng = np.random.default_rng(11)
    spots = [(-3.2, 1.2), (-2.4, 3.8), (-4.5, 4.5), (3.4, 1.0), (2.6, 4.2), (4.8, 3.6), (-1.2, 5.5), (1.0, 6.2),
             (-5.6, 1.8), (5.8, 1.5), (0.2, 8.0), (-3.4, 7.4), (3.6, 7.6), (-6.4, 6.0), (6.6, 6.4)]
    for i, (x, y) in enumerate(spots):
        _tree(f"Tree{i}", x, y, 0.9 + 0.5 * rng.random(), T, leafs[i % 3])
    for i, (x, y, r) in enumerate([(-1.6, -0.4, 0.14), (1.9, 0.3, 0.18), (-0.6, 2.0, 0.1)]):
        C.add_prim("ico", f"Rock{i}", loc=(x, y, r * 0.5), subdivisions=1, radius=r, mat=T(f"rock{i}", color=(0.62, 0.62, 0.66)))
    anchors = {"host": (-0.75, 0.2, 0.0), "center": (0.45, 0.9, 0.0), "left": (-1.4, 0.9, 0.0), "right": (1.4, 0.9, 0.0),
               "back": (0.3, 2.6, 0.0), "front": (0.3, -0.3, 0.0)}
    cams = {
        "wide": {"pos": (-0.05, -2.3, 1.15), "target": (-0.05, 0.6, 0.88), "end": (-0.05, -2.1, 1.13), "lens": 24},
        "host": {"pos": (-0.7, -0.62, 1.36), "target": (-0.75, 0.2, 1.3), "end": (-0.7, -0.5, 1.35), "lens": 38},
        "host_full": {"pos": (-0.6, -1.7, 1.0), "target": (-0.75, 0.2, 0.88), "end": (-0.6, -1.5, 1.0), "lens": 32},
    }
    return {"anchors": anchors, "cams": cams, "world": (0.8, 0.9, 1.0)}


def studio():
    """Neutral infinite backdrop (warm cream): for topics with no natural location, or prop showcases."""
    T = C.toon_mat
    C.add_prim("plane", "Floor", size=40, mat=T("floor", color=(0.96, 0.9, 0.82), shade=0.9))
    C.add_prim("plane", "Backdrop", loc=(0, 4, 5), rot=(math.radians(90), 0, 0), size=1, scale=(40, 10, 1),
               mat=T("backdrop", image=_sky_gradient((0.99, 0.86, 0.72), (0.97, 0.93, 0.86), "studio_bg", clouds=False), flat=True))
    anchors = {"host": (-0.7, 0.2, 0.0), "center": (0.45, 0.7, 0.0), "left": (-1.3, 0.7, 0.0), "right": (1.3, 0.7, 0.0),
               "back": (0.3, 2.0, 0.0), "front": (0.3, -0.3, 0.0)}
    cams = {
        "wide": {"pos": (-0.05, -2.2, 1.12), "target": (-0.05, 0.5, 0.86), "end": (-0.05, -2.0, 1.1), "lens": 24},
        "host": {"pos": (-0.65, -0.62, 1.36), "target": (-0.7, 0.2, 1.3), "end": (-0.65, -0.5, 1.35), "lens": 38},
        "host_full": {"pos": (-0.55, -1.7, 1.0), "target": (-0.7, 0.2, 0.88), "end": (-0.55, -1.5, 1.0), "lens": 32},
    }
    return {"anchors": anchors, "cams": cams, "world": (0.98, 0.94, 0.88)}


SETS.update({"forest": forest, "studio": studio})


# ------------------------------------------------------------------ more generic sets (v0.3)
GENERIC_CAMS = {
    "wide": {"pos": (-0.05, -2.2, 1.12), "target": (-0.05, 0.5, 0.86), "end": (-0.05, -2.0, 1.1), "lens": 24},
    "host": {"pos": (-0.65, -0.62, 1.36), "target": (-0.7, 0.2, 1.3), "end": (-0.65, -0.5, 1.35), "lens": 38},
    "host_full": {"pos": (-0.55, -1.7, 1.0), "target": (-0.7, 0.2, 0.88), "end": (-0.55, -1.5, 1.0), "lens": 32},
}
GENERIC_ANCH = {"host": (-0.7, 0.2, 0.0), "center": (0.45, 0.7, 0.0), "left": (-1.3, 0.7, 0.0), "right": (1.3, 0.7, 0.0),
                "back": (0.3, 2.0, 0.0), "front": (0.3, -0.3, 0.0)}


def _checker(name, c1, c2, n=8, cell=2):
    a = np.zeros((n * cell, n * cell, 3), np.float32)
    for y in range(n * cell):
        for x in range(n * cell):
            a[y, x] = c1 if (x // cell + y // cell) % 2 == 0 else c2
    return C.img_from_array(name, a)


def _tiles(name, base, grout, cell=4):
    a = np.zeros((16, 16, 3), np.float32)
    a[:] = base
    a[::cell, :] = grout
    a[:, ::cell] = grout
    return C.img_from_array(name, a)


def _noise(name, cols, seed, size=32, specks=None):
    rng = np.random.default_rng(seed)
    a = np.array(cols, np.float32)[rng.integers(0, len(cols), (size, size))]
    for c, k in (specks or []):
        for _ in range(k):
            x, y = rng.integers(0, size, 2)
            a[y, x] = c
    return C.img_from_array(name, a)


def _back_wall(T, img_or_color, name="wall", y=3.0, h=3.2):
    kw = {"image": img_or_color, "uv_scale": 10} if not isinstance(img_or_color, tuple) else {"color": img_or_color}
    C.add_prim("cube", name, loc=(0, y + 0.05, h / 2), scale=(8, 0.05, h / 2), mat=T(name, shade=0.9, **kw))


def kitchen():
    """Bright home kitchen: checker floor, tiled back wall, counter with sink + stove, upper cabinets, window, fridge."""
    T = C.toon_mat
    C.add_prim("plane", "Floor", size=40, mat=T("kfloor", image=_checker("kchecker", (0.95, 0.93, 0.88), (0.82, 0.72, 0.62)), uv_scale=24, shade=0.88))
    _back_wall(T, _tiles("ktiles", (0.86, 0.94, 0.92), (0.74, 0.84, 0.82)), "kwall")
    wood, top = T("kcab", color=(0.86, 0.66, 0.46)), T("ktop", color=(0.93, 0.92, 0.9))
    C.add_prim("cube", "Counter", loc=(0, 2.68, 0.45), scale=(3.2, 0.3, 0.45), mat=wood)
    C.add_prim("cube", "CounterTop", loc=(0, 2.66, 0.92), scale=(3.25, 0.33, 0.03), mat=top)
    for i, x in enumerate((-2.6, -1.6, -0.6, 0.4, 1.4, 2.4)):
        C.add_prim("cube", f"Door{i}", loc=(x, 2.375, 0.45), scale=(0.44, 0.01, 0.38), mat=T(f"kdoor{i}", color=(0.9, 0.72, 0.52)))
        C.add_prim("cube", f"Upper{i}", loc=(x, 2.82, 2.05), scale=(0.46, 0.18, 0.38), mat=wood)
    C.add_prim("cube", "Sink", loc=(-0.6, 2.62, 0.93), scale=(0.35, 0.2, 0.02), mat=T("ksink", color=(0.66, 0.7, 0.74)))
    C.add_prim("cyl", "Tap", loc=(-0.6, 2.85, 1.08), scale=(0.025, 0.025, 0.14), vertices=8, mat=T("ktap", color=(0.7, 0.72, 0.76)))
    for i, x in enumerate((1.25, 1.65)):
        C.add_prim("cyl", f"Burner{i}", loc=(x, 2.6, 0.955), scale=(0.13, 0.13, 0.01), vertices=12, mat=T(f"kburn{i}", color=(0.22, 0.22, 0.26)))
    C.add_prim("cyl", "Pot", loc=(1.25, 2.6, 1.06), scale=(0.12, 0.12, 0.1), vertices=12, mat=T("kpot", color=(0.95, 0.45, 0.35)))
    C.add_prim("cube", "Window", loc=(-0.6, 2.98, 1.6), scale=(0.55, 0.02, 0.32),
               mat=T("kwin", image=_sky_gradient((0.5, 0.74, 1.0), (0.85, 0.94, 1.0), "kitchen_sky"), flat=True))
    C.add_prim("cube", "Fridge", loc=(-3.4, 2.55, 0.95), scale=(0.42, 0.4, 0.95), mat=T("kfridge", color=(0.94, 0.95, 0.97)))
    return {"anchors": dict(GENERIC_ANCH), "cams": dict(GENERIC_CAMS), "world": (0.97, 0.96, 0.93)}


def classroom():
    """School classroom: wood floor, cream wall, big green chalkboard with chalk doodles, teacher desk, clock, shelf."""
    T = C.toon_mat
    C.add_prim("plane", "Floor", size=40, mat=T("cfloor", image=_planks(), uv_scale=30, shade=0.86))
    _back_wall(T, (0.97, 0.92, 0.8), "cwall")
    board = np.zeros((24, 48, 3), np.float32)
    board[:] = (0.2, 0.38, 0.3)
    for (x, y, l) in [(4, 18, 14), (4, 15, 9), (4, 12, 18), (28, 6, 12), (30, 9, 8)]:
        board[y, x:x + l] = (0.9, 0.93, 0.9)
    yy, xx = np.mgrid[0:24, 0:48]
    ring = np.abs(np.hypot(xx - 38, yy - 16) - 4) < 0.6
    board[ring] = (0.98, 0.9, 0.55)
    C.add_prim("cube", "BoardFrame", loc=(0.2, 2.97, 1.55), scale=(1.65, 0.03, 0.72), mat=T("cframe", color=(0.7, 0.5, 0.32)))
    C.add_prim("cube", "Board", loc=(0.2, 2.94, 1.55), scale=(1.55, 0.02, 0.64), mat=T("cboard", image=C.img_from_array("chalk", board), flat=True))
    C.add_prim("cube", "Ledge", loc=(0.2, 2.9, 0.9), scale=(1.55, 0.05, 0.015), mat=T("cledge", color=(0.7, 0.5, 0.32)))
    C.add_prim("cube", "Desk", loc=(2.3, 2.2, 0.38), scale=(0.6, 0.3, 0.38), mat=T("cdesk", color=(0.78, 0.56, 0.36)))
    C.add_prim("cube", "Books", loc=(2.1, 2.2, 0.81), scale=(0.12, 0.09, 0.05), mat=T("cbooks", color=(0.86, 0.35, 0.38)))
    C.add_prim("sphere", "Apple", loc=(2.55, 2.15, 0.82), radius=0.05, mat=T("capple", color=(0.9, 0.25, 0.25)))
    C.add_prim("cyl", "Clock", loc=(-1.9, 2.95, 2.3), rot=(math.radians(90), 0, 0), scale=(0.2, 0.2, 0.02), vertices=16,
               mat=T("cclock", color=(0.98, 0.97, 0.94)))
    C.add_prim("cube", "Shelf", loc=(-3.0, 2.75, 0.8), scale=(0.6, 0.2, 0.8), mat=T("cshelf", color=(0.72, 0.52, 0.34)))
    for i in range(6):
        C.add_prim("cube", f"Book{i}", loc=(-3.4 + i * 0.15, 2.65, 1.25 - (i % 2) * 0.5), scale=(0.05, 0.12, 0.15),
                   mat=T(f"cbook{i}", color=[(0.5, 0.6, 0.9), (0.95, 0.75, 0.4), (0.6, 0.85, 0.6)][i % 3]))
    return {"anchors": dict(GENERIC_ANCH), "cams": dict(GENERIC_CAMS), "world": (0.98, 0.95, 0.88)}


def park():
    """City park: lawn, sandy path, bench, lamp post, round trees, low fence, blue sky."""
    T = C.toon_mat
    C.add_prim("plane", "Ground", size=40, mat=T("pground", image=_grass(), uv_scale=40, shade=0.86))
    C.add_prim("plane", "Path", loc=(0, 1.8, 0.004), size=1, scale=(40, 0.9, 1),
               mat=T("ppath", image=_noise("sand_path", [(0.9, 0.82, 0.64), (0.86, 0.78, 0.6), (0.92, 0.85, 0.68)], 5), uv_scale=20, flat=True))
    C.add_prim("plane", "Sky", loc=(0, 14, 6), rot=(math.radians(90), 0, 0), size=1, scale=(60, 14, 1),
               mat=T("psky", image=_sky_gradient((0.42, 0.66, 0.98), (0.85, 0.94, 1.0), "park_sky"), flat=True))
    wood, iron = T("pbench", color=(0.76, 0.5, 0.3)), T("piron", color=(0.25, 0.27, 0.3))
    C.add_prim("cube", "BenchSeat", loc=(2.0, 2.55, 0.42), scale=(0.7, 0.2, 0.03), mat=wood)
    C.add_prim("cube", "BenchBack", loc=(2.0, 2.73, 0.68), scale=(0.7, 0.03, 0.15), mat=wood)
    for i, x in enumerate((1.4, 2.6)):
        C.add_prim("cube", f"BenchLeg{i}", loc=(x, 2.6, 0.2), scale=(0.03, 0.17, 0.2), mat=iron)
    C.add_prim("cyl", "Lamp", loc=(-2.2, 2.6, 1.2), scale=(0.035, 0.035, 1.2), vertices=8, mat=iron)
    C.add_prim("sphere", "LampHead", loc=(-2.2, 2.6, 2.45), radius=0.13, mat=T("plamp", color=(1.0, 0.96, 0.75), flat=True))
    crowns = [T(f"pcrown{i}", color=c, shade=0.78) for i, c in enumerate([(0.36, 0.66, 0.36), (0.42, 0.72, 0.4)])]
    for i, (x, y, sc) in enumerate([(-3.4, 3.6, 1.0), (3.6, 3.8, 1.15), (-1.0, 5.2, 0.9), (1.6, 5.8, 1.1), (-5.0, 5.0, 1.2), (5.4, 5.6, 1.0)]):
        C.add_prim("cyl", f"PTrunk{i}", loc=(x, y, 0.55 * sc), scale=(0.08 * sc, 0.08 * sc, 0.55 * sc), vertices=6, mat=T(f"ptrunk{i}", image=_bark()))
        C.add_prim("ico", f"PCrown{i}", loc=(x, y, 1.45 * sc), subdivisions=1, radius=0.62 * sc, mat=crowns[i % 2])
    for i in range(14):
        C.add_prim("cube", f"Fence{i}", loc=(-6.5 + i, 3.1, 0.25), scale=(0.03, 0.03, 0.25), mat=T(f"pfence{i}", color=(0.97, 0.96, 0.92)))
    C.add_prim("cube", "FenceRail", loc=(0, 3.1, 0.4), scale=(7, 0.02, 0.025), mat=T("prail", color=(0.97, 0.96, 0.92)))
    return {"anchors": dict(GENERIC_ANCH), "cams": dict(GENERIC_CAMS), "world": (0.8, 0.9, 1.0)}


def desert():
    """Sunny desert / ancient-history backdrop: sand, dunes, distant pyramids, rocks, warm sky."""
    T = C.toon_mat
    sand = [(0.93, 0.8, 0.56), (0.9, 0.76, 0.52), (0.95, 0.83, 0.6)]
    C.add_prim("plane", "Ground", size=60, mat=T("dground", image=_noise("sand", sand, 9, specks=[((0.8, 0.66, 0.44), 30)]), uv_scale=40, shade=0.86))
    # (the rotated sky plane shows the gradient's first arg at the horizon: warm haze low, blue high)
    C.add_prim("plane", "Sky", loc=(0, 18, 10), rot=(math.radians(90), 0, 0), size=1, scale=(80, 12, 1),
               mat=T("dsky", image=_sky_gradient((0.99, 0.9, 0.74), (0.45, 0.68, 0.98), "desert_sky", clouds=False), flat=True))
    dune = T("ddune", color=(0.92, 0.76, 0.52), shade=0.84)
    for i, (x, y, sx, sz) in enumerate([(-5, 9, 4.5, 0.9), (4, 10, 5.5, 1.1), (0, 13, 7, 1.4), (-9, 12, 4, 1.0), (9, 12, 4, 0.8)]):
        C.add_prim("sphere", f"Dune{i}", loc=(x, y, 0), scale=(sx, 2.0, sz), mat=dune)
    stone = T("dpyr", color=(0.88, 0.74, 0.5), shade=0.74)
    for i, (x, y, s_) in enumerate([(-2.5, 11.0, 2.2), (1.8, 12.5, 1.6), (4.6, 13.5, 1.0)]):
        C.add_prim("cone", f"Pyramid{i}", loc=(x, y, s_ * 0.7), rot=(0, 0, math.radians(45)), vertices=4,
                   scale=(s_, s_, s_ * 0.7), mat=stone)
    for i, (x, y, r) in enumerate([(-1.8, -0.2, 0.16), (2.1, 0.5, 0.2), (-0.4, 2.4, 0.12), (2.8, 2.6, 0.26)]):
        C.add_prim("ico", f"DRock{i}", loc=(x, y, r * 0.45), subdivisions=1, radius=r, mat=T(f"drock{i}", color=(0.72, 0.6, 0.46)))
    return {"anchors": dict(GENERIC_ANCH), "cams": dict(GENERIC_CAMS), "world": (1.0, 0.94, 0.84)}


SETS.update({"kitchen": kitchen, "classroom": classroom, "park": park, "desert": desert})
