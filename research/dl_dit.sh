#!/usr/bin/env bash
# one DiT via parallel ranged GET: dl_dit.sh <repo> <path>
G="C:/Users/rAzzren/AppData/Local/hermes/skills/creative/comfyui-local-ops/scripts/verify_parallel_get.sh"
M="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/models/diffusion_models"
ST="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/_dl3d/pg"
repo=$1; path=$2; name=$(basename $path)
[ -f "$M/$name" ] && { echo "SKIP $name"; exit 0; }
sha=$(curl -s "https://huggingface.co/api/models/$repo/tree/main/diffusion_models" | python -c "import json,sys; print(next(x['lfs']['oid'] for x in json.load(sys.stdin) if x['path']=='$path'))")
for i in $(seq 1 20); do bash "$G" "https://huggingface.co/$repo/resolve/main/$path" "$ST/$name" 16 "$sha" --hf-auth; rc=$?; [ $rc -eq 0 ] && break; sleep 5; done
[ $rc -eq 0 ] && mv "$ST/$name" "$M/$name" && echo "OK $name" || echo "FAIL $name"
