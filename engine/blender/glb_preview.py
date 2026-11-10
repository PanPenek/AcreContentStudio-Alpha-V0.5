"""Turntable preview of a GLB/blend character: front, 3/4, side, back (+ optional face close-up).

blender --background --python glb_preview.py -- <model.glb|.blend> <out_prefix> [--pixel 0|1] [--unlit 0|1]
Writes <out_prefix>_sheet.png (4 views) and <out_prefix>_face.png.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
opts = dict(zip(argv[2::2], argv[3::2]))
UNLIT = opts.get("--unlit", "1") == "1"

if SRC.endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=SRC)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr, size = (lo + hi) / 2, hi - lo
print("BBOX", tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi), "faces", sum(len(o.data.polygons) for o in meshes))

if UNLIT:  # emission-only look: shows the texture exactly as painted (pixel-art style is flat-lit)
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if not bsdf or not out:
            continue
        link = bsdf.inputs["Base Color"].links
        em = nt.nodes.new("ShaderNodeEmission")
        if link:
            nt.links.new(link[0].from_socket, em.inputs["Color"])
            tex = link[0].from_node
            if tex.type == "TEX_IMAGE" and opts.get("--pixel", "1") == "1":
                tex.interpolation = "Closest"
        else:
            em.inputs["Color"].default_value = bsdf.inputs["Base Color"].default_value
        nt.links.new(em.outputs[0], out.inputs["Surface"])

sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = 512, 768
sc.render.film_transparent = False
sc.view_settings.view_transform = "Standard"
w = sc.world or bpy.data.worlds.new("W")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.8, 0.78, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
if not UNLIT:
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    sc.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
up_axis = 2  # glTF import converts Y-up to Z-up
H = size.z
cam.data.ortho_scale = H * 1.08
frames = []
for i, ang in enumerate([0, 45, 90, 180]):
    a = math.radians(ang)
    d = max(size.x, size.y, size.z) * 3
    # front = -Y in Blender after glTF import
    cam.location = ctr + Vector((math.sin(a) * d, -math.cos(a) * d, 0))
    cam.rotation_euler = (math.radians(90), 0, a)
    p = f"{OUT}_v{i}.png"
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    frames.append(p)
# face close-up: top 18% of height
cam.data.ortho_scale = H * 0.24
cam.location = Vector((ctr.x, ctr.y - max(size.x, size.y, size.z) * 3, lo.z + H * 0.88))
cam.rotation_euler = (math.radians(90), 0, 0)
sc.render.resolution_x, sc.render.resolution_y = 640, 640
sc.render.filepath = f"{OUT}_face.png"
bpy.ops.render.render(write_still=True)
print("FRAMES", frames)
