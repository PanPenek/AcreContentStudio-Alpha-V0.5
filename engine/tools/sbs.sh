#!/usr/bin/env bash
# Side-by-side check: reference frames vs our stills, all at 720x1280.
# usage: bash engine/tools/sbs.sh <episode_dir> <out.png> still1.png still2.png [still3.png]
set -e
EP="$1"; OUT="$2"; shift 2
REF=workspace/reference_style
ARGS=(-i "$REF/r1.png" -i "$REF/r2.png")
for s in "$@"; do ARGS+=(-i "$EP/stills/$s"); done
N=$((2 + $#))
F=""
for i in $(seq 0 $((N - 1))); do F="$F[$i:v]scale=720:1280:flags=lanczos,setsar=1[v$i];"; done
for i in $(seq 0 $((N - 1))); do F="$F[v$i]"; done
ffmpeg -y -v error "${ARGS[@]}" -filter_complex "${F}hstack=inputs=$N" "$OUT"
echo "SBS $OUT"
