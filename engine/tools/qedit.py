"""Qwen-Image-Edit-2511 int8 (Apache-2.0) edits through a local ComfyUI API.

python qedit.py <server> <ref.png|-> <out_prefix> <seed> <w> <h> "<prompt>" [steps]   (ref "-" = text-to-image)
Graph: UNET int8 -> AuraFlow 3.1 -> CFGNorm -> Lightning LoRA -> KSampler(cfg1, euler/simple);
reference upscaled with RealESRGAN anime x4 -> 1.4 MP; latent = EmptySD3LatentImage(w,h).
"""
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid

SERVER, REF, OUT, SEED, W, H, PROMPT = sys.argv[1:8]
STEPS = int(sys.argv[8]) if len(sys.argv) > 8 else 8
INPUT_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI_rAzzren\ComfyUI\input")


def post(path, data):
    req = urllib.request.Request(SERVER + path, data=json.dumps(data).encode(), headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return json.loads(urllib.request.urlopen(SERVER + path).read())


T2I = REF in ("-", "none", "")  # no reference: plain text-to-image with the same model
name = f"abs_ref_{uuid.uuid4().hex[:6]}.png"
os.makedirs(INPUT_DIR, exist_ok=True)
if not T2I:
    shutil.copy(REF, os.path.join(INPUT_DIR, name))
lora = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors" if STEPS >= 8 else "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
g = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2511_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
    "3": {"class_type": "CFGNorm", "inputs": {"model": ["2", 0], "strength": 1.0}},
    "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["3", 0], "lora_name": lora, "strength_model": 1.0}},
    "5": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
    "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "7": {"class_type": "LoadImage", "inputs": {"image": name}},
    "8": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN_x4plus_anime_6B.pth"}},
    "9": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["8", 0], "image": ["7", 0]}},
    "10": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["9", 0], "upscale_method": "lanczos", "megapixels": 1.4, "resolution_steps": 16}},
    "11": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["5", 0], "prompt": PROMPT, "vae": ["6", 0], "image1": ["10", 0]}},
    "12": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["5", 0], "prompt": "", "vae": ["6", 0], "image1": ["10", 0]}},
    "13": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["11", 0], "reference_latents_method": "index_timestep_zero"}},
    "14": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["12", 0], "reference_latents_method": "index_timestep_zero"}},
    "15": {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(W), "height": int(H), "batch_size": 1}},
    "16": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": int(SEED), "steps": STEPS, "cfg": 1.0, "sampler_name": "euler",
                                                "scheduler": "simple", "positive": ["13", 0], "negative": ["14", 0], "latent_image": ["15", 0], "denoise": 1.0}},
    "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["6", 0]}},
    "18": {"class_type": "SaveImage", "inputs": {"images": ["17", 0], "filename_prefix": "abs/" + os.path.basename(OUT)}},
}
def png_size(path):
    import struct
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24]) if head[:8] == b"\x89PNG\r\n\x1a\n" else (0, 0)


if not T2I and png_size(REF)[0] * png_size(REF)[1] >= 900_000:
    # already ~1 MP: the 4x anime upscaler would make a 16 MP image and stall/thrash next to Qwen in VRAM
    g.pop("8"); g.pop("9")
    g["10"]["inputs"]["image"] = ["7", 0]
if T2I:
    for k in ("7", "8", "9", "10"):
        g.pop(k, None)
    for k in ("11", "12"):
        g[k]["inputs"].pop("image1")
r = post("/prompt", {"prompt": g, "client_id": "abs-qedit"})
pid = r["prompt_id"]
t0 = time.time()
while True:
    h = get(f"/history/{pid}")
    if pid in h:
        st = h[pid]["status"]
        if st.get("status_str") == "error":
            print("ERROR", json.dumps(st)[:1500])
            sys.exit(1)
        imgs = h[pid]["outputs"]["18"]["images"]
        break
    time.sleep(2)
outdir = os.path.join(r"C:\Users\rAzzren\AcreBlenderStudio\workspace\comfy_out")
src = os.path.join(outdir, imgs[0]["subfolder"], imgs[0]["filename"])
shutil.copy(src, OUT + ".png")
print("OK", OUT + ".png", f"{time.time() - t0:.1f}s")
