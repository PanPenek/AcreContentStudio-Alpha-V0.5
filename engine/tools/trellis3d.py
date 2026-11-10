"""TRELLIS.2 image -> textured GLB through a local ComfyUI API (native nodes, Comfy-Org template
3d_pixal3d_trellis2_image_to_model with the Trellis.2 branch hard-wired).

python trellis3d.py <server> <image.png> <out.glb> [--faces 40000] [--seed 56] [--tex 2048]
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import time
import urllib.request
import uuid

ap = argparse.ArgumentParser()
ap.add_argument("server")
ap.add_argument("image")
ap.add_argument("out")
ap.add_argument("--faces", type=int, default=40000)
ap.add_argument("--seed", type=int, default=56)
ap.add_argument("--tex", type=int, default=2048)
ap.add_argument("--remesh", type=int, default=768)
ap.add_argument("--paint", action="store_true")
ap.add_argument("--upres", type=int, default=1536, help="upsample target; 1024 for bulky props (1536 = 50 s/step + crash on a boxy mill)")
ap.add_argument("--tex-clip", default=None, help="separate DINO for the texture stage (shape stays cached)")
args = ap.parse_args()
COMFY = os.path.expandvars(r"%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI_rAzzren\ComfyUI")
OUTDIR = r"C:\Users\rAzzren\AcreBlenderStudio\workspace\comfy_out"


def call(path, data=None):
    req = urllib.request.Request(args.server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read() or b"{}")


name = "abs3d_" + hashlib.sha1(open(args.image, "rb").read()).hexdigest()[:10] + ".png"  # stable name -> ComfyUI cache hits
shutil.copy(args.image, os.path.join(COMFY, "input", name))
prefix = f"abs3d/{os.path.splitext(os.path.basename(args.out))[0]}_{uuid.uuid4().hex[:4]}"
g = {
    "img": {"class_type": "LoadImage", "inputs": {"image": name}},
    "bgm": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
    "bg": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["bgm", 0], "image": ["img", 0]}},
    "crop": {"class_type": "ImageCropToMask", "inputs": {"images": ["img", 0], "masks": ["bg", 0], "width": 1024, "height": 1024,
                                                          "pad_factor": 1.1, "grow_mask": 0, "background": "#000000"}},
    "cropprev": {"class_type": "PreviewImage", "inputs": {"images": ["crop", 0]}},
    "cv": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "dino_v3_L_naf_fp32.safetensors"}},
    "cond": {"class_type": "Trellis2Conditioning", "inputs": {"clip_vision_model": ["cv", 0], "image": ["crop", 0]}},
    "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "trellis_2_int8_convrot.safetensors", "weight_dtype": "default"}},
    "svae": {"class_type": "VAELoader", "inputs": {"vae_name": "trellis_2_shape_vae_bf16.safetensors"}},
    "tvae": {"class_type": "VAELoader", "inputs": {"vae_name": "trellis_2_texture_vae_bf16.safetensors"}},
    # structure sampler model chain
    "cfgA": {"class_type": "CFGOverride", "inputs": {"model": ["unet", 0], "cfg": 1, "start_percent": 0.667, "end_percent": 1}},
    "resA": {"class_type": "RescaleCFG", "inputs": {"model": ["cfgA", 0], "multiplier": 0.7}},
    "msA": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["resA", 0], "shift": 5}},
    # shape samplers model chain
    "cfgB": {"class_type": "CFGOverride", "inputs": {"model": ["unet", 0], "cfg": 1, "start_percent": 0.769, "end_percent": 1}},
    "resB": {"class_type": "RescaleCFG", "inputs": {"model": ["cfgB", 0], "multiplier": 0.5}},
    "lat0": {"class_type": "EmptyTrellis2LatentStructure", "inputs": {"batch_size": 1}},
    "ks_struct": {"class_type": "KSampler", "inputs": {"model": ["msA", 0], "seed": args.seed, "steps": 12, "cfg": 7.5, "sampler_name": "euler",
                                                       "scheduler": "normal", "positive": ["cond", 0], "negative": ["cond", 1], "latent_image": ["lat0", 0], "denoise": 1}},
    "vox": {"class_type": "VaeDecodeStructureTrellis2", "inputs": {"samples": ["ks_struct", 0], "vae": ["svae", 0], "resolution": "32"}},
    "shape": {"class_type": "Trellis2ShapeStage", "inputs": {"positive": ["cond", 0], "negative": ["cond", 1], "voxel": ["vox", 0]}},
    "ks_shape": {"class_type": "KSampler", "inputs": {"model": ["resB", 0], "seed": 42, "steps": 20, "cfg": 7.5, "sampler_name": "euler",
                                                      "scheduler": "normal", "positive": ["shape", 0], "negative": ["shape", 1], "latent_image": ["shape", 2], "denoise": 1}},
    "up": {"class_type": "Trellis2UpsampleStage", "inputs": {"positive": ["shape", 0], "negative": ["shape", 1], "shape_latent": ["ks_shape", 0],
                                                             "vae": ["svae", 0], "target_resolution": args.upres}},
    "ks_up": {"class_type": "KSampler", "inputs": {"model": ["resB", 0], "seed": 42, "steps": 12, "cfg": 7.5, "sampler_name": "euler",
                                                   "scheduler": "simple", "positive": ["up", 0], "negative": ["up", 1], "latent_image": ["up", 2], "denoise": 1}},
    "mesh": {"class_type": "VaeDecodeShapeTrellis", "inputs": {"samples": ["ks_up", 0], "vae": ["svae", 0]}},
    "tex": {"class_type": "Trellis2TextureStage", "inputs": {"positive": ["up", 0], "negative": ["up", 1], "shape_latent": ["ks_up", 0]}},
    "ks_tex": {"class_type": "KSampler", "inputs": {"model": ["unet", 0], "seed": 43, "steps": 12, "cfg": 1, "sampler_name": "euler",
                                                    "scheduler": "normal", "positive": ["tex", 0], "negative": ["tex", 1], "latent_image": ["tex", 2], "denoise": 1}},
    "tvox": {"class_type": "VaeDecodeTextureTrellis", "inputs": {"samples": ["ks_tex", 0], "vae": ["tvae", 0], "shape_subdivides": ["mesh", 1]}},
    # mesh cleanup -> low poly -> UV -> bake
    "info": {"class_type": "GetMeshInfo", "inputs": {"mesh": ["mesh", 0]}},
    "remesh": {"class_type": "RemeshMesh", "inputs": {"mesh": ["info", 0], "resolution": args.remesh, "sign_mode": "solid", "sign_mode.fill": 20,
                                                      "sign_mode.qef": False, "band": 1, "project_back": 0, "fix_poles": False, "smooth_iters": 20,
                                                      "drop_small_components": 0.01, "precluster_max_verts": 20000000}},
    "dec": {"class_type": "DecimateMesh", "inputs": {"mesh": ["remesh", 0], "target_face_count": args.faces, "placement_mode": "midpoint"}},
    "sn1": {"class_type": "MeshSmoothNormals", "inputs": {"mesh": ["dec", 0], "crease_angle": 180}},
    "uv": {"class_type": "UnwrapMesh", "inputs": {"mesh": ["sn1", 0], "segmenter": "pec", "resolution": args.tex, "padding": 1, "weld_distance": 0.0002}},
    "bake": {"class_type": "BakeTextureFromVoxel", "inputs": {"mesh": ["uv", 0], "voxel_colors": ["tvox", 0], "texture_size": args.tex, "reference_mesh": ["mesh", 0]}},
    "apply": {"class_type": "ApplyTextureToMesh", "inputs": {"mesh": ["uv", 0], "base_color": ["bake", 0]}},
    "sn2": {"class_type": "MeshSmoothNormals", "inputs": {"mesh": ["apply", 0], "crease_angle": 180}},
    "save": {"class_type": "SaveGLB", "inputs": {"mesh": ["sn2", 0], "filename_prefix": prefix}},
    "savebase": {"class_type": "SaveImage", "inputs": {"images": ["bake", 0], "filename_prefix": prefix + "_basecolor"}},
}
if args.tex_clip:
    g["cv2"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": args.tex_clip}}
    g["cond2"] = {"class_type": "Trellis2Conditioning", "inputs": {"clip_vision_model": ["cv2", 0], "image": ["crop", 0]}}
    g["tex"]["inputs"]["positive"] = ["cond2", 0]
    g["tex"]["inputs"]["negative"] = ["cond2", 1]
if args.paint:  # debug: raw voxel colours painted onto the full-res decoded mesh (no UV bake)
    g["paint"] = {"class_type": "PaintMesh", "inputs": {"mesh": ["mesh", 0], "voxel_colors": ["tvox", 0]}}
    g["savepaint"] = {"class_type": "SaveGLB", "inputs": {"mesh": ["paint", 0], "filename_prefix": prefix + "_paint"}}
r = call("/prompt", {"prompt": g, "client_id": "abs-trellis"})
if r.get("node_errors"):
    print("NODE_ERRORS", json.dumps(r["node_errors"])[:2000])
pid = r["prompt_id"]
t0 = time.time()
while True:
    h = call(f"/history/{pid}")
    if pid in h:
        st = h[pid]["status"]
        if st.get("status_str") == "error":
            print("ERROR", json.dumps(st["messages"])[-2500:])
            raise SystemExit(1)
        if st.get("completed"):
            break
    time.sleep(3)
glbs = sorted(x for x in glob.glob(os.path.join(OUTDIR, prefix.replace("/", os.sep) + "*.glb")) if "_paint" not in x)
if not glbs:
    print("no glb found; outputs:", json.dumps(h[pid]["outputs"])[:1500])
    raise SystemExit(1)
os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
shutil.copy(glbs[-1], args.out)
for p in glob.glob(os.path.join(OUTDIR, prefix.replace("/", os.sep) + "_basecolor*.png"))[:1]:
    shutil.copy(p, os.path.splitext(args.out)[0] + "_basecolor.png")
print("OK", args.out, os.path.getsize(args.out), f"{time.time() - t0:.0f}s")
