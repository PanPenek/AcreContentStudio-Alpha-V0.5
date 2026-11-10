"""Render the exact ortho front/back silhouette of a mesh, framed to its bbox (x by z), for art<->mesh registration.
blender --background --python silhouette.py -- <mesh.glb> <out_prefix> <rows>
Writes <out_prefix>_front.png and _back.png (white = mesh), width = rows * W/H.
"""
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT, ROWS = argv[0], argv[1], int(argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
sc = bpy.context.scene
obj = next(o for o in sc.objects if o.type == "MESH")
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
vs = [v.co for v in obj.data.vertices]
lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
W, H = hi.x - lo.x, hi.z - lo.z
m = bpy.data.materials.new("w")
m.use_nodes = True
nt = m.node_tree
nt.nodes.clear()
em = nt.nodes.new("ShaderNodeEmission")
em.inputs[0].default_value = (1, 1, 1, 1)
o = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(em.outputs[0], o.inputs[0])
obj.data.materials.clear()
obj.data.materials.append(m)
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "SINGLE"
sc.display.shading.single_color = (1, 1, 1)
sc.display.render_aa = "OFF"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("W")
sc.world = w
w.color = (0, 0, 0)
sc.render.resolution_y = ROWS
sc.render.resolution_x = max(1, round(ROWS * W / H))
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(W, H)
cam.data.sensor_fit = "AUTO"
c = (lo + hi) / 2
for name, y, rz in (("front", lo.y - 5, 0), ("back", hi.y + 5, 3.14159265)):
    cam.location = Vector((c.x, y, c.z))
    cam.rotation_euler = (1.5707963, 0, rz)
    sc.render.filepath = f"{OUT}_{name}.png"
    bpy.ops.render.render(write_still=True)
print("SIL", W, H, sc.render.resolution_x, sc.render.resolution_y)
