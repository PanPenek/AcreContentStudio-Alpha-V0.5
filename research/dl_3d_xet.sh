#!/usr/bin/env bash
# Big DiTs via hf (xet) with a stall watchdog: restart hf if the staging dir stops growing for 90 s.
export HF_TOKEN=$(cat ~/.cache/huggingface/token); export HF_HUB_DISABLE_SYMLINKS_WARNING=1
M="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/models/diffusion_models"
ST="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/_dl3d/xet"; mkdir -p "$ST"
for rp in Comfy-Org/TRELLIS.2:diffusion_models/trellis_2_int8_convrot.safetensors Comfy-Org/Pixal3D:diffusion_models/pixal3d_int8_convrot.safetensors; do
  repo=${rp%%:*}; path=${rp#*:}; name=$(basename $path)
  [ -f "$M/$name" ] && { echo "SKIP $name"; continue; }
  for attempt in $(seq 1 30); do
    hf download "$repo" "$path" --local-dir "$ST" > /dev/null 2>&1 &
    pid=$!
    last=-1; still=0
    while kill -0 $pid 2>/dev/null; do
      sleep 15
      cur=$(du -sb "$ST" | cut -f1)
      if [ "$cur" = "$last" ]; then still=$((still+15)); else still=0; fi; last=$cur
      if [ $still -ge 90 ]; then echo "stall, restart $name (attempt $attempt)"; taskkill //PID $pid //T //F >/dev/null 2>&1; kill $pid 2>/dev/null; break; fi
    done
    wait $pid 2>/dev/null
    [ -f "$ST/$path" ] && break
  done
  if [ -f "$ST/$path" ]; then mv "$ST/$path" "$M/$name"; echo "OK $name $(stat -c %s "$M/$name")"; else echo "FAIL $name"; fi
done
echo DONE
