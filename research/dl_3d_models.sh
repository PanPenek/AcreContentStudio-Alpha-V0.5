#!/usr/bin/env bash
# Download the Pixal3D + TRELLIS.2 image-to-3D model set into ComfyUI-Shared/models (sequential, resumable).
set -u
export HF_TOKEN=$(cat ~/.cache/huggingface/token)
export HF_HUB_DISABLE_SYMLINKS_WARNING=1
M="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/models"
STAGE="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/_dl3d"
mkdir -p "$STAGE"
fail=0
get() { # repo path destdir
  local repo=$1 path=$2 dest="$M/$3" name; name=$(basename "$path")
  mkdir -p "$dest"
  if [ -f "$dest/$name" ]; then echo "SKIP $name"; return; fi
  echo "GET $repo/$path"
  for i in 1 2 3; do
    hf download "$repo" "$path" --local-dir "$STAGE" >/dev/null 2>&1 && break
    echo "retry $i $name"; sleep 5
  done
  if [ -f "$STAGE/$path" ]; then mv "$STAGE/$path" "$dest/$name" && echo "OK $name $(stat -c %s "$dest/$name")"; else echo "FAIL $name"; fail=1; fi
}
get Comfy-Org/BiRefNet background_removal/birefnet.safetensors background_removal
get Comfy-Org/MoGe geometry_estimation/moge_2_vitl_normal_fp16.safetensors geometry_estimation
get Comfy-Org/Pixal3D vae/trellis_2_texture_vae_bf16.safetensors vae
get Comfy-Org/Pixal3D vae/trellis_2_shape_vae_bf16.safetensors vae
get Comfy-Org/Pixal3D clip_vision/dino_v3_L_naf_fp32.safetensors clip_vision
get Comfy-Org/TRELLIS.2 diffusion_models/trellis_2_int8_convrot.safetensors diffusion_models
get Comfy-Org/Pixal3D diffusion_models/pixal3d_int8_convrot.safetensors diffusion_models
echo "DONE fail=$fail"
