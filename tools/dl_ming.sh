#!/usr/bin/env bash
# Ming-3.0-tts-0.5B: small files via hf, the big safetensors via parallel ranged GET (hf xet stalls here).
set -u
cd "$(dirname "$0")"
export HF_TOKEN=$(cat ~/.cache/huggingface/token) HF_HUB_DISABLE_SYMLINKS_WARNING=1
D=models/Ming-3.0-tts-0.5B
mkdir -p $D
hf download inclusionAI/Ming-3.0-tts-0.5B --local-dir $D --exclude "model.safetensors" "*.pdf" "figures/*" >/dev/null 2>&1 && echo "small files OK"
G="C:/Users/rAzzren/AppData/Local/hermes/skills/creative/comfyui-local-ops/scripts/verify_parallel_get.sh"
SHA=$(curl -s "https://huggingface.co/api/models/inclusionAI/Ming-3.0-tts-0.5B/tree/main" | python -c "import json,sys; print(next(x['lfs']['oid'] for x in json.load(sys.stdin) if x['path']=='model.safetensors'))")
if [ ! -f $D/model.safetensors ]; then
  for i in $(seq 1 15); do bash "$G" "https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B/resolve/main/model.safetensors" "$D/model.safetensors" 12 "$SHA" --hf-auth && break; sleep 5; done
fi
ls -la $D
[ -f $D/model.safetensors ] && echo MING_DL_OK || echo MING_DL_FAIL
