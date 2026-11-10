#!/usr/bin/env bash
# Pixal3D + TRELLIS.2 set via parallel ranged GET (hf xet stalled). Sequential files, retry loop on exit 3.
set -u
G="C:/Users/rAzzren/AppData/Local/hermes/skills/creative/comfyui-local-ops/scripts/verify_parallel_get.sh"
M="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/models"
STAGE="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/_dl3d/pg"
mkdir -p "$STAGE"
fail=0
get() { # repo path destdir
  local repo=$1 path=$2 dest="$M/$3" name sha url rc
  name=$(basename "$path")
  [ -f "$dest/$name" ] && { echo "SKIP $name"; return; }
  sha=$(curl -s "https://huggingface.co/api/models/$repo/tree/main/$(dirname "$path")" | python -c "import json,sys; print(next(x['lfs']['oid'] for x in json.load(sys.stdin) if x['path']=='$path'))")
  url="https://huggingface.co/$repo/resolve/main/$path"
  echo "GET $name sha=$sha"
  for i in $(seq 1 12); do
    bash "$G" "$url" "$STAGE/$name" 8 "$sha" --hf-auth; rc=$?
    [ $rc -eq 0 ] && break
    echo "rc=$rc retry $i"; sleep 5
  done
  if [ -f "$STAGE/$name" ] && [ $rc -eq 0 ]; then mkdir -p "$dest"; mv "$STAGE/$name" "$dest/$name"; echo "OK $name"; else echo "FAIL $name rc=$rc"; fail=1; fi
}
get Comfy-Org/Pixal3D vae/trellis_2_texture_vae_bf16.safetensors vae
get Comfy-Org/Pixal3D vae/trellis_2_shape_vae_bf16.safetensors vae
get Comfy-Org/Pixal3D clip_vision/dino_v3_L_naf_fp32.safetensors clip_vision
echo "DONE fail=$fail"
