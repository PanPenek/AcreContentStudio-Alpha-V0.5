G="C:/Users/rAzzren/AppData/Local/hermes/skills/creative/comfyui-local-ops/scripts/verify_parallel_get.sh"
M="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/models/clip_vision"; ST="$LOCALAPPDATA/Comfy-Desktop/ComfyUI-Shared/_dl3d/pg"
for i in $(seq 1 15); do bash "$G" "https://huggingface.co/Comfy-Org/TRELLIS.2/resolve/main/clip_vision/dino_v3_vit_l.safetensors" "$ST/dino_v3_vit_l.safetensors" 16 5cb785e458de7c460579082418af81f5c62380c181599344bdc60898c63468ee --hf-auth && break; sleep 5; done
mv "$ST/dino_v3_vit_l.safetensors" "$M/" && echo OK_DINO
